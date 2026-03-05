/**
 * osc_dac7800.c - DAC7800 SPI driver
 *
 * The DAC7800 is a 12-bit dual MDAC used for oscillator frequency control.
 * We use SPI0 in master mode, CPOL=0 CPHA=1 (mode 1), MSB first.
 * CS is driven manually via GPIO P1.3.
 *
 * SPI data format (16-bit word, MSB first):
 *   Bit 15-14: Don't care (sent as 0)
 *   Bit 13:    /LDAC = 0 (update output immediately on CS rising edge)
 *   Bit 12:    PD = 0 (normal operation, not power-down)
 *   Bit 11-0:  DAC code D11..D0
 *
 * Reference: DAC7800 datasheet, SPI timing diagrams
 *            CN0359 SPI patterns for ADuCM360
 */

#include "osc_config.h"
#include "osc_dac7800.h"

void dac7800_init(void)
{
    /*
     * Configure GPIO P1.3 as CS output (active low)
     */
    DAC_CS_PORT->GPCON &= ~GP1CON_CON3_MSK;   /* GPIO function */
    DAC_CS_PORT->GPOEN |= (1u << DAC_CS_BIT);  /* output */
    DAC_CS_PORT->GPSET  = (1u << DAC_CS_BIT);  /* CS high (deselected) */

    /*
     * Configure SPI0 pins:
     *   P1.4 = SPI0_SCLK (alternate function)
     *   P1.5 = SPI0_MOSI (alternate function)
     * Note: P1.6 = SPI0_MISO not needed (DAC7800 is write-only in our config)
     */
    pADI_GP1->GPCON = (pADI_GP1->GPCON & ~GP1CON_CON4_MSK)
                     | (1u << (4 * 2));  /* P1.4 = AF1 (SPI0_SCLK) */
    pADI_GP1->GPCON = (pADI_GP1->GPCON & ~GP1CON_CON5_MSK)
                     | (1u << (5 * 2));  /* P1.5 = AF1 (SPI0_MOSI) */

    /*
     * SPI0 configuration:
     *   Master mode
     *   CPOL=0, CPHA=1 (SPI mode 1, data clocked on falling edge)
     *   MSB first
     *   8-bit transfers (we send 2 bytes per transaction)
     *   Clock divider: PCLK/4 = 4 MHz (well within DAC7800's 10 MHz max)
     */
    pADI_SPI0->SPICON = SPICON_MOD_TX1RX1     /* Full duplex (TX only used) */
                       | SPICON_MASEN_EN        /* Master mode */
                       | SPICON_CPOL_LOW        /* CPOL=0: idle low */
                       | SPICON_CPHA_SAMPLETRAILING /* CPHA=1 */
                       | SPICON_TFLUSH_EN       /* Flush TX FIFO */
                       | SPICON_ENABLE_EN;      /* Enable SPI */

    /* SPI clock divider: PCLK (16 MHz) / 4 = 4 MHz */
    pADI_SPI0->SPIDIV = 3;  /* divider = (SPIDIV+1)*2 = 8, so 16M/8 = 2MHz */

    /* Clear flush bit */
    pADI_SPI0->SPICON &= ~SPICON_TFLUSH_EN;
}

/**
 * Wait for SPI TX FIFO to have space.
 */
static void spi_wait_tx_ready(void)
{
    while (!(pADI_SPI0->SPISTA & SPISTA_TXFSTA_MSK)) {
        /* TX FIFO not empty yet - wait */
    }
    /* Actually we need to check if TX is done */
    while (pADI_SPI0->SPISTA & SPISTA_TXFSTA_MSK) {
        /* Wait for TX FIFO to drain */
    }
}

void dac7800_write(uint16_t code)
{
    /* Clamp to 12 bits */
    code &= 0x0FFF;

    /* Build 16-bit SPI word:
     * [15:14] = 00 (don't care)
     * [13]    = 0  (/LDAC = 0, update on CS rise)
     * [12]    = 0  (PD = 0, normal operation)
     * [11:0]  = code
     */
    uint16_t spi_word = code;  /* bits 13,12 = 0 already */

    uint8_t msb = (uint8_t)(spi_word >> 8);
    uint8_t lsb = (uint8_t)(spi_word & 0xFF);

    /* Assert CS low */
    DAC_CS_PORT->GPCLR = (1u << DAC_CS_BIT);

    /* Send MSB first */
    pADI_SPI0->SPITX = msb;
    /* Wait for transfer complete */
    while (!(pADI_SPI0->SPISTA & SPISTA_TXFSTA_MSK)) { }
    while (pADI_SPI0->SPISTA & SPISTA_TXFSTA_MSK) { }
    (void)pADI_SPI0->SPIRX;  /* dummy read to clear RXFSTA */

    /* Send LSB */
    pADI_SPI0->SPITX = lsb;
    while (!(pADI_SPI0->SPISTA & SPISTA_TXFSTA_MSK)) { }
    while (pADI_SPI0->SPISTA & SPISTA_TXFSTA_MSK) { }
    (void)pADI_SPI0->SPIRX;

    /* Deassert CS (rising edge latches data in DAC7800) */
    DAC_CS_PORT->GPSET = (1u << DAC_CS_BIT);
}

uint16_t frequency_to_code(float freq_hz)
{
    float code_f = freq_hz * FREQ_CONST;

    if (code_f < (float)DAC_CODE_MIN)
        code_f = (float)DAC_CODE_MIN;
    if (code_f > (float)DAC_CODE_MAX)
        code_f = (float)DAC_CODE_MAX;

    return (uint16_t)(code_f + 0.5f);
}

float code_to_frequency(uint16_t code)
{
    if (code == 0) return 0.0f;
    return (float)code / FREQ_CONST;
}
