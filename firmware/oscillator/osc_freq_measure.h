/**
 * osc_freq_measure.h - Frequency measurement via zero-crossing timing
 */

#ifndef OSC_FREQ_MEASURE_H
#define OSC_FREQ_MEASURE_H

#include <stdint.h>

/**
 * Initialize Timer1 for capture mode on the BP zero-crossing input.
 * GPIO P0.5 is configured as Timer1 capture input.
 */
void freq_measure_init(void);

/**
 * Measure the oscillation frequency by timing zero-crossings.
 * Averages over num_periods full cycles for accuracy.
 *
 * @param num_periods  Number of periods to average (1-100)
 * @return             Measured frequency in Hz, or 0 if timeout
 */
float freq_measure_hz(uint16_t num_periods);

/**
 * Measure a single period (time between two rising edges).
 *
 * @return  Period in seconds, or 0 if timeout
 */
float freq_measure_period_s(void);

/**
 * Read the AD636 RMS output via ADC0.
 * The AD636 output (0-200mV) is read with PGA=4, 1.2V internal ref.
 * Result is multiplied by the attenuator ratio (5x) to get oscillator RMS.
 *
 * @return  Oscillator RMS voltage in volts
 */
float read_ad636_rms(void);

#endif
