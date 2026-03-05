/**
 * osc_calibrate.c - Self-calibration routines
 *
 * 16 log-spaced DAC codes from 3 to 3632 are swept. At each point:
 *   1. Write DAC code
 *   2. Wait for oscillation to settle (5 periods + AD636 time constant)
 *   3. Measure frequency by averaging 10 zero-crossing periods
 *   4. Read AD636 RMS amplitude via ADC
 *   5. Calculate correction factor = expected_freq / measured_freq
 *
 * The correction table enables frequency-accurate operation despite
 * op-amp GBW, MDAC capacitance, and other systematic errors.
 *
 * Flash storage uses ADuCM362 page 61 (512 bytes, plenty for our struct).
 */

#include "osc_config.h"
#include "osc_calibrate.h"
#include "osc_dac7800.h"
#include "osc_freq_measure.h"
#include "osc_uart.h"

/* External timing functions */
extern uint32_t get_tick_ms(void);
extern void delay_ms(uint32_t ms);

/* 16 log-spaced DAC codes covering the full frequency range */
static const uint16_t cal_codes[CAL_POINTS] = {
    3, 6, 12, 24, 48, 97, 121, 194,
    388, 605, 970, 1211, 1940, 2421, 3100, 3632
};

bool calibrate_run(cal_data_t *data, bool verbose)
{
    data->magic = 0;
    data->num_points = CAL_POINTS;
    data->avg_correction = 1.0f;
    data->max_freq_error_pct = 0.0f;

    float total_correction = 0.0f;

    if (verbose) {
        uart_puts("$INFO,Starting calibration sweep\r\n");
    }

    for (int i = 0; i < CAL_POINTS; i++) {
        uint16_t code = cal_codes[i];
        data->points[i].dac_code = code;
        data->points[i].expected_hz = code_to_frequency(code);

        /* Write DAC code */
        dac7800_write(code);

        /* Calculate settle time:
         *   - At least 5 oscillation periods for frequency stability
         *   - At least AD636 time constant (80ms) for amplitude
         *   - Minimum 100ms for very high frequencies
         */
        float expected_period_ms = 1000.0f / data->points[i].expected_hz;
        uint32_t settle_ms = (uint32_t)(CAL_SETTLE_PERIODS * expected_period_ms);
        if (settle_ms < AD636_TAU_MS) settle_ms = AD636_TAU_MS;
        if (settle_ms < 100) settle_ms = 100;
        /* Cap at 3 seconds for very low frequencies */
        if (settle_ms > 3000) settle_ms = 3000;

        delay_ms(settle_ms);

        /* Measure frequency: average over multiple periods */
        uint16_t avg_periods = CAL_MEASURE_PERIODS;
        /* At very low frequencies, use fewer periods to avoid long waits */
        if (data->points[i].expected_hz < 50.0f) {
            avg_periods = 3;
        }
        data->points[i].measured_hz = freq_measure_hz(avg_periods);

        /* Measure amplitude */
        data->points[i].rms_v = read_ad636_rms();

        /* Calculate correction factor */
        if (data->points[i].measured_hz > 0.1f) {
            data->points[i].correction =
                data->points[i].expected_hz / data->points[i].measured_hz;
        } else {
            data->points[i].correction = 1.0f;
        }

        total_correction += data->points[i].correction;

        /* Track worst-case error */
        float error_pct = 0.0f;
        if (data->points[i].expected_hz > 0.1f) {
            error_pct = (data->points[i].measured_hz - data->points[i].expected_hz)
                      / data->points[i].expected_hz * 100.0f;
            if (error_pct < 0) error_pct = -error_pct;
        }
        if (error_pct > data->max_freq_error_pct) {
            data->max_freq_error_pct = error_pct;
        }

        /* Report progress */
        if (verbose) {
            uart_puts("$CAL,");
            uart_print_int("", i + 1);
            uart_puts(",");
            uart_print_int("", code);
            uart_puts(",");
            uart_print_float("", data->points[i].measured_hz, 1);
            uart_puts(",");
            uart_print_float("", data->points[i].rms_v * 1000.0f, 1);
            uart_puts(",");
            uart_print_float("", error_pct, 2);
            uart_puts("%\r\n");
        }
    }

    data->avg_correction = total_correction / (float)CAL_POINTS;
    data->magic = CAL_MAGIC;

    if (verbose) {
        uart_puts("$INFO,Calibration complete\r\n");
        calibrate_print_report(data);
    }

    return true;
}

uint16_t calibrate_lookup(const cal_data_t *data, float target_hz)
{
    if (data->magic != CAL_MAGIC || data->num_points < 2) {
        /* No valid cal data, use ideal formula */
        return frequency_to_code(target_hz);
    }

    /* Find the two calibration points bracketing the target frequency */
    const cal_point_t *pts = data->points;
    int n = data->num_points;

    /* Below lowest cal point */
    if (target_hz <= pts[0].expected_hz) {
        float corrected_code = (float)pts[0].dac_code * pts[0].correction;
        float ratio = target_hz / pts[0].expected_hz;
        corrected_code *= ratio;
        if (corrected_code < DAC_CODE_MIN) corrected_code = DAC_CODE_MIN;
        return (uint16_t)(corrected_code + 0.5f);
    }

    /* Above highest cal point */
    if (target_hz >= pts[n - 1].expected_hz) {
        float corrected_code = (float)pts[n - 1].dac_code * pts[n - 1].correction;
        float ratio = target_hz / pts[n - 1].expected_hz;
        corrected_code *= ratio;
        if (corrected_code > DAC_CODE_MAX) corrected_code = DAC_CODE_MAX;
        return (uint16_t)(corrected_code + 0.5f);
    }

    /* Linear interpolation between bracketing points */
    for (int i = 0; i < n - 1; i++) {
        if (target_hz >= pts[i].expected_hz &&
            target_hz <= pts[i + 1].expected_hz) {
            /* Interpolate correction factor */
            float frac = (target_hz - pts[i].expected_hz)
                       / (pts[i + 1].expected_hz - pts[i].expected_hz);
            float corr = pts[i].correction + frac *
                         (pts[i + 1].correction - pts[i].correction);

            /* Apply correction to ideal DAC code */
            float ideal_code = target_hz * FREQ_CONST;
            float corrected = ideal_code * corr;

            if (corrected < DAC_CODE_MIN) corrected = DAC_CODE_MIN;
            if (corrected > DAC_CODE_MAX) corrected = DAC_CODE_MAX;
            return (uint16_t)(corrected + 0.5f);
        }
    }

    /* Fallback (shouldn't reach here) */
    return frequency_to_code(target_hz);
}

/* ── Flash Operations ── */

/* ADuCM362 flash page address */
#define FLASH_PAGE_SIZE  512
#define FLASH_CAL_ADDR   (0x00000000 + CAL_FLASH_PAGE * FLASH_PAGE_SIZE)

/* Flash controller key sequence */
#define FLASH_KEY1       0xFDB3
#define FLASH_KEY2       0x1F45

bool calibrate_save_flash(const cal_data_t *data)
{
    /* Disable interrupts during flash operations */
    __disable_irq();

    /* Erase page */
    pADI_FEE->FEEADR0L = (FLASH_CAL_ADDR & 0xFFFF);
    pADI_FEE->FEEADR0H = (FLASH_CAL_ADDR >> 16);
    pADI_FEE->FEEKEY = FLASH_KEY1;
    pADI_FEE->FEEKEY = FLASH_KEY2;
    pADI_FEE->FEECMD = 0x01;  /* Page erase command */

    /* Wait for erase complete */
    while (pADI_FEE->FEESTA & 0x01) { }

    /* Check for errors */
    if (pADI_FEE->FEESTA & 0x04) {
        __enable_irq();
        return false;
    }

    /* Write data as 32-bit words */
    const uint32_t *src = (const uint32_t *)data;
    uint32_t addr = FLASH_CAL_ADDR;
    uint32_t words = (sizeof(cal_data_t) + 3) / 4;

    for (uint32_t i = 0; i < words; i++) {
        pADI_FEE->FEEADR0L = (addr & 0xFFFF);
        pADI_FEE->FEEADR0H = (addr >> 16);
        pADI_FEE->FEEDAT0L = (src[i] & 0xFFFF);
        pADI_FEE->FEEDAT0H = (src[i] >> 16);
        pADI_FEE->FEEKEY = FLASH_KEY1;
        pADI_FEE->FEEKEY = FLASH_KEY2;
        pADI_FEE->FEECMD = 0x02;  /* Write command */

        while (pADI_FEE->FEESTA & 0x01) { }

        if (pADI_FEE->FEESTA & 0x04) {
            __enable_irq();
            return false;
        }

        addr += 4;
    }

    __enable_irq();
    return true;
}

bool calibrate_load_flash(cal_data_t *data)
{
    /* Read directly from flash memory-mapped address */
    const cal_data_t *flash_data = (const cal_data_t *)FLASH_CAL_ADDR;

    if (flash_data->magic != CAL_MAGIC) {
        return false;
    }

    /* Copy from flash to RAM */
    const uint32_t *src = (const uint32_t *)flash_data;
    uint32_t *dst = (uint32_t *)data;
    uint32_t words = (sizeof(cal_data_t) + 3) / 4;

    for (uint32_t i = 0; i < words; i++) {
        dst[i] = src[i];
    }

    return true;
}

void calibrate_print_report(const cal_data_t *data)
{
    uart_puts("\r\n$INFO,=== CALIBRATION REPORT ===\r\n");
    uart_puts("$INFO, DAC   Expected   Measured   Error%  Corr   RMS(mV)\r\n");

    for (int i = 0; i < data->num_points; i++) {
        const cal_point_t *pt = &data->points[i];
        float err = 0.0f;
        if (pt->expected_hz > 0.1f) {
            err = (pt->measured_hz - pt->expected_hz) / pt->expected_hz * 100.0f;
        }

        uart_puts("$INFO,");
        uart_print_int(" ", pt->dac_code);
        uart_print_float("    ", pt->expected_hz, 1);
        uart_print_float("    ", pt->measured_hz, 1);
        uart_print_float("    ", err, 2);
        uart_print_float("%   ", pt->correction, 4);
        uart_print_float("   ", pt->rms_v * 1000.0f, 1);
        uart_puts("\r\n");
    }

    uart_puts("$INFO,---\r\n");
    uart_print_float("$INFO,Avg correction: ", data->avg_correction, 4);
    uart_puts("\r\n");
    uart_print_float("$INFO,Max freq error: ", data->max_freq_error_pct, 2);
    uart_puts("%\r\n");
}
