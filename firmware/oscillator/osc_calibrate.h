/**
 * osc_calibrate.h - Self-calibration routines for oscillator
 *
 * At power-on, the ADuCM362 runs a 16-point frequency sweep, measuring
 * actual vs expected frequency at each DAC code. This builds a correction
 * lookup table (LUT) stored in flash. During operation, the LUT is
 * interpolated to find the correct DAC code for any target frequency.
 *
 * Calibration also measures amplitude at each point to verify AGC stability.
 */

#ifndef OSC_CALIBRATE_H
#define OSC_CALIBRATE_H

#include <stdint.h>
#include <stdbool.h>

/* Single calibration measurement point */
typedef struct {
    uint16_t dac_code;          /* DAC code written */
    float    expected_hz;       /* Ideal frequency */
    float    measured_hz;       /* Actual measured frequency */
    float    correction;        /* correction = expected / measured */
    float    rms_v;             /* Measured RMS amplitude */
} cal_point_t;

/* Full calibration dataset */
typedef struct {
    uint32_t    magic;                  /* CAL_MAGIC if valid */
    uint16_t    num_points;             /* Number of cal points */
    cal_point_t points[CAL_POINTS];     /* Calibration data */
    float       avg_correction;         /* Average correction factor */
    float       max_freq_error_pct;     /* Worst-case frequency error */
} cal_data_t;

/**
 * Run the full calibration sequence.
 * Sweeps through 16 log-spaced DAC codes, measuring frequency at each.
 * Results are stored in the cal_data structure.
 *
 * @param data     Pointer to calibration data structure to fill
 * @param verbose  If true, send progress to UART
 * @return  true if calibration completed successfully
 */
bool calibrate_run(cal_data_t *data, bool verbose);

/**
 * Look up the corrected DAC code for a target frequency.
 * Uses linear interpolation between calibration points.
 *
 * @param data      Pointer to valid calibration data
 * @param target_hz Target frequency in Hz
 * @return          Corrected DAC code to achieve target frequency
 */
uint16_t calibrate_lookup(const cal_data_t *data, float target_hz);

/**
 * Save calibration data to flash page.
 * Uses ADuCM362 flash erase + write.
 *
 * @param data  Pointer to calibration data to save
 * @return      true if write succeeded
 */
bool calibrate_save_flash(const cal_data_t *data);

/**
 * Load calibration data from flash.
 * Checks magic number for validity.
 *
 * @param data  Pointer to calibration data structure to fill
 * @return      true if valid data was found in flash
 */
bool calibrate_load_flash(cal_data_t *data);

/**
 * Print calibration summary to UART.
 */
void calibrate_print_report(const cal_data_t *data);

#endif
