/**
 * osc_uart.c - UART driver for host communication
 *
 * UART0 on P0.6 (RX) / P0.7 (TX), 115200 baud, 8N1.
 * TX is interrupt-driven with a 256-byte ring buffer.
 * RX is polled (single character at a time for command parsing).
 *
 * Baud rate calculation:
 *   COMDIV = PCLK / (16 * baud * 2^OSR_override)
 *   For 115200: COMDIV = 16e6 / (16 * 115200) = 8.68 -> use fractional divider
 *   COMDIV=8, DIVN=3, DIVM=1 -> exact 115200 from 16 MHz PCLK
 */

#include "osc_config.h"
#include "osc_uart.h"

/* TX ring buffer */
static volatile char     tx_buf[TX_BUF_SIZE];
static volatile uint16_t tx_head = 0;
static volatile uint16_t tx_tail = 0;
static volatile bool     tx_busy = false;

void uart_init(void)
{
    /*
     * Configure GPIO:
     *   P0.6 = UART0_RX (AF1)
     *   P0.7 = UART0_TX (AF1)
     */
    pADI_GP0->GPCON = (pADI_GP0->GPCON & ~GP0CON_CON6_MSK)
                     | (1u << (6 * 2));   /* P0.6 = AF1 (UART RX) */
    pADI_GP0->GPCON = (pADI_GP0->GPCON & ~GP0CON_CON7_MSK)
                     | (1u << (7 * 2));   /* P0.7 = AF1 (UART TX) */

    /* Enable UART clock */
    pADI_CLKCTL->CLKDIS &= ~CLKDIS_DISUARTCLK_MSK;

    /* Configure baud rate: 115200 from 16 MHz PCLK */
    pADI_UART->COMDIV  = 8;              /* integer divider */
    pADI_UART->COMFBR  = (1 << 15)       /* FBR enable */
                        | (3 << 11)       /* DIVN = 3 */
                        | (1 << 0);       /* DIVM = 1 */

    /* 8 data bits, no parity, 1 stop bit */
    pADI_UART->COMCON  = COMCON_WLS_8BITS;

    /* Enable TX interrupt (fires when TX holding register empty) */
    pADI_UART->COMIEN = COMIEN_ETBEI_EN;

    /* Enable UART interrupt in NVIC */
    NVIC_SetPriority(UART_IRQn, 3);
    NVIC_EnableIRQ(UART_IRQn);
}

/**
 * UART interrupt handler.
 * Sends next character from TX ring buffer, or stops if empty.
 */
void UART_Int_Handler(void)
{
    uint16_t iir = pADI_UART->COMIIR;

    /* TX holding register empty */
    if ((iir & COMIIR_STA_MSK) == COMIIR_STA_TXBUFEMPTY) {
        if (tx_head != tx_tail) {
            pADI_UART->COMTX = tx_buf[tx_tail];
            tx_tail = (tx_tail + 1) % TX_BUF_SIZE;
        } else {
            tx_busy = false;
        }
    }
}

void uart_putc(char c)
{
    uint16_t next = (tx_head + 1) % TX_BUF_SIZE;

    /* Wait if buffer full */
    while (next == tx_tail) { }

    tx_buf[tx_head] = c;
    tx_head = next;

    /* Kick off transmission if idle */
    if (!tx_busy) {
        tx_busy = true;
        pADI_UART->COMTX = tx_buf[tx_tail];
        tx_tail = (tx_tail + 1) % TX_BUF_SIZE;
    }
}

void uart_puts(const char *s)
{
    while (*s) {
        uart_putc(*s++);
    }
}

bool uart_rx_ready(void)
{
    return (pADI_UART->COMLSR & COMLSR_DR_MSK) != 0;
}

char uart_getc(void)
{
    while (!uart_rx_ready()) {
        __WFI();
    }
    return (char)pADI_UART->COMRX;
}

void uart_print_float(const char *prefix, float value, int decimals)
{
    uart_puts(prefix);

    if (value < 0.0f) {
        uart_putc('-');
        value = -value;
    }

    /* Integer part */
    uint32_t ipart = (uint32_t)value;
    float fpart = value - (float)ipart;

    /* Convert integer part to string (reverse) */
    char ibuf[12];
    int ilen = 0;
    if (ipart == 0) {
        ibuf[ilen++] = '0';
    } else {
        while (ipart > 0) {
            ibuf[ilen++] = '0' + (ipart % 10);
            ipart /= 10;
        }
    }
    /* Print reversed */
    for (int i = ilen - 1; i >= 0; i--) {
        uart_putc(ibuf[i]);
    }

    if (decimals > 0) {
        uart_putc('.');
        /* Fractional part */
        for (int d = 0; d < decimals; d++) {
            fpart *= 10.0f;
            uint8_t digit = (uint8_t)fpart;
            uart_putc('0' + digit);
            fpart -= (float)digit;
        }
    }
}

void uart_print_int(const char *prefix, int32_t value)
{
    uart_puts(prefix);

    if (value < 0) {
        uart_putc('-');
        value = -value;
    }

    char buf[12];
    int len = 0;
    if (value == 0) {
        buf[len++] = '0';
    } else {
        while (value > 0) {
            buf[len++] = '0' + (value % 10);
            value /= 10;
        }
    }
    for (int i = len - 1; i >= 0; i--) {
        uart_putc(buf[i]);
    }
}
