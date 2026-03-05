/**
 * osc_uart.h - UART driver for host communication
 *
 * 115200 baud, 8N1 on P0.6 (RX) / P0.7 (TX).
 * Interrupt-driven TX with ring buffer.
 * Polled RX with single-character read.
 */

#ifndef OSC_UART_H
#define OSC_UART_H

#include <stdint.h>

/**
 * Initialize UART at 115200 baud.
 * Configures P0.6/P0.7 and enables TX interrupt.
 */
void uart_init(void);

/**
 * Send a null-terminated string (non-blocking, buffered).
 * Characters are queued in a TX ring buffer and sent by interrupt.
 */
void uart_puts(const char *s);

/**
 * Send a single character (non-blocking, buffered).
 */
void uart_putc(char c);

/**
 * Check if a character has been received.
 * @return  true if a character is available
 */
bool uart_rx_ready(void);

/**
 * Read a received character (blocking if none available).
 * @return  received character
 */
char uart_getc(void);

/**
 * Print a formatted float with specified decimal places.
 * Lightweight alternative to printf for embedded use.
 *
 * @param prefix  string prefix (e.g. "freq=")
 * @param value   float value
 * @param decimals number of decimal places (0-6)
 */
void uart_print_float(const char *prefix, float value, int decimals);

/**
 * Print a formatted integer.
 * @param prefix  string prefix (e.g. "code=")
 * @param value   integer value
 */
void uart_print_int(const char *prefix, int32_t value);

#endif
