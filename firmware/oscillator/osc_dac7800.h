/**
 * osc_dac7800.h - DAC7800 SPI driver for frequency control
 */

#ifndef OSC_DAC7800_H
#define OSC_DAC7800_H

#include <stdint.h>

/**
 * Initialize SPI0 for DAC7800 communication.
 * Configures P1.3 as CS (GPIO), P1.4/P1.5 as SPI CLK/MOSI.
 */
void dac7800_init(void);

/**
 * Write a 12-bit code to the DAC7800.
 * SPI word format: [15:14]=don't care, [13]=!LDAC (0=update), [12]=PD, [11:0]=code
 *
 * @param code  12-bit DAC code (0-4095)
 */
void dac7800_write(uint16_t code);

/**
 * Calculate DAC code for a target frequency.
 * Uses ideal formula: D = f_target * FREQ_CONST
 *
 * @param freq_hz  Target frequency in Hz
 * @return         12-bit DAC code (clamped to DAC_CODE_MIN..DAC_CODE_MAX)
 */
uint16_t frequency_to_code(float freq_hz);

/**
 * Calculate expected frequency for a DAC code.
 * Uses ideal formula: f = D / FREQ_CONST
 *
 * @param code  12-bit DAC code
 * @return      Expected frequency in Hz
 */
float code_to_frequency(uint16_t code);

#endif
