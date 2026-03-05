/**
 * osc_main.c - State Variable Oscillator controller main program
 *
 * ADuCM362-based oscillator controller with:
 *   - MDAC frequency control via DAC7800 (SPI)
 *   - Frequency measurement via zero-crossing timing (Timer1 capture)
 *   - Amplitude measurement via AD636 RMS detector (24-bit ADC)
 *   - Automated self-calibration with flash storage
 *   - UART command interface for host control
 *
 * Power-on sequence:
 *   1. Init peripherals (clock, SPI, UART, Timer1, ADC)
 *   2. Set DAC to default code (D=121, ~1 kHz)
 *   3. Wait for oscillation to start
 *   4. Load calibration from flash, or run fresh calibration
 *   5. Enter command loop
 *
 * UART commands:
 *   F<hz>    Set frequency (e.g. F1000.0)
 *   D<code>  Set raw DAC code (e.g. D121)
 *   CAL      Run calibration sweep
 *   S        Run frequency sweep (all 16 cal points)
 *   M        Single measurement (freq + amplitude)
 *   ?        Print status and calibration info
 *   R        Reset to default frequency
 */

#include "osc_config.h"
#include "osc_dac7800.h"
#include "osc_freq_measure.h"
#include "osc_calibrate.h"
#include "osc_uart.h"

/* Provided by osc_system_init.c */
extern void system_init(void);
extern uint32_t get_tick_ms(void);
extern void delay_ms(uint32_t ms);

/* ── Global State ── */
static cal_data_t  cal_data;
static bool        cal_valid = false;
static uint16_t    current_dac_code = 121;
static float       current_freq_hz  = 0.0f;
static float       current_rms_v    = 0.0f;

/* Command buffer */
#define CMD_BUF_SIZE 64
static char cmd_buf[CMD_BUF_SIZE];
static uint8_t cmd_len = 0;

/* ── Forward declarations ── */
static void process_command(const char *cmd);
static void set_frequency(float freq_hz);
static void set_dac_code(uint16_t code);
static void do_measurement(void);
static void do_sweep(void);
static void print_status(void);
static float parse_float(const char *s);
static int32_t parse_int(const char *s);

/* ── Main ── */

int main(void)
{
    /* 1. System init */
    system_init();

    /* 2. Peripheral init */
    uart_init();
    dac7800_init();
    freq_measure_init();

    uart_puts("\r\n$INFO,State Variable Oscillator Controller\r\n");
    uart_puts("$INFO,ADuCM362 + DAC7800 + AD636\r\n");

    /* 3. Set initial frequency (D=121 ~1 kHz) */
    dac7800_write(current_dac_code);
    uart_puts("$INFO,DAC set to D=121 (~1 kHz)\r\n");

    /* 4. Wait for oscillation to establish + AD636 settle */
    uart_puts("$INFO,Waiting for oscillation...\r\n");
    delay_ms(500);

    /* 5. Load or run calibration */
    if (calibrate_load_flash(&cal_data)) {
        cal_valid = true;
        uart_puts("$INFO,Loaded calibration from flash\r\n");
        calibrate_print_report(&cal_data);
    } else {
        uart_puts("$INFO,No stored calibration - running fresh\r\n");
        cal_valid = calibrate_run(&cal_data, true);
        if (cal_valid) {
            calibrate_save_flash(&cal_data);
            uart_puts("$INFO,Calibration saved to flash\r\n");
        }
    }

    /* Restore default frequency after calibration sweep */
    dac7800_write(current_dac_code);
    delay_ms(200);

    /* Initial measurement */
    do_measurement();
    print_status();

    uart_puts("$INFO,Ready. Type ? for help\r\n");

    /* 6. Command loop */
    while (1) {
        if (uart_rx_ready()) {
            char c = uart_getc();

            if (c == '\r' || c == '\n') {
                if (cmd_len > 0) {
                    cmd_buf[cmd_len] = '\0';
                    process_command(cmd_buf);
                    cmd_len = 0;
                }
            } else if (c == '\b' || c == 0x7F) {
                /* Backspace */
                if (cmd_len > 0) cmd_len--;
            } else if (cmd_len < CMD_BUF_SIZE - 1) {
                cmd_buf[cmd_len++] = c;
            }
        } else {
            __WFI();  /* Sleep until next interrupt */
        }
    }
}

/* ── Command Processing ── */

static void process_command(const char *cmd)
{
    switch (cmd[0]) {
    case 'F': case 'f': {
        /* F<freq_hz> - set frequency using calibrated lookup */
        float freq = parse_float(&cmd[1]);
        if (freq > 0.0f) {
            set_frequency(freq);
        } else {
            uart_puts("$ERR,Invalid frequency\r\n");
        }
        break;
    }

    case 'D': case 'd': {
        /* D<code> - set raw DAC code */
        int32_t code = parse_int(&cmd[1]);
        if (code >= DAC_CODE_MIN && code <= DAC_CODE_MAX) {
            set_dac_code((uint16_t)code);
        } else {
            uart_puts("$ERR,DAC code out of range (3-3632)\r\n");
        }
        break;
    }

    case 'C': case 'c':
        /* CAL - run calibration */
        uart_puts("$INFO,Running calibration...\r\n");
        cal_valid = calibrate_run(&cal_data, true);
        if (cal_valid) {
            calibrate_save_flash(&cal_data);
            uart_puts("$INFO,Calibration saved\r\n");
        }
        /* Restore current frequency */
        dac7800_write(current_dac_code);
        delay_ms(200);
        do_measurement();
        break;

    case 'S': case 's':
        /* S - frequency sweep */
        do_sweep();
        /* Restore current frequency */
        dac7800_write(current_dac_code);
        delay_ms(200);
        do_measurement();
        break;

    case 'M': case 'm':
        /* M - single measurement */
        do_measurement();
        break;

    case 'R': case 'r':
        /* R - reset to default */
        set_dac_code(121);
        break;

    case '?':
        /* ? - print status and help */
        print_status();
        uart_puts("$INFO,Commands: F<hz> D<code> CAL S M R ?\r\n");
        break;

    default:
        uart_puts("$ERR,Unknown command: ");
        uart_puts(cmd);
        uart_puts("\r\n");
        break;
    }
}

static void set_frequency(float freq_hz)
{
    uint16_t code;

    if (cal_valid) {
        code = calibrate_lookup(&cal_data, freq_hz);
    } else {
        code = frequency_to_code(freq_hz);
    }

    current_dac_code = code;
    dac7800_write(code);

    /* Wait for settle */
    float period_ms = 1000.0f / freq_hz;
    uint32_t settle = (uint32_t)(5.0f * period_ms);
    if (settle < 100) settle = 100;
    if (settle > 2000) settle = 2000;
    delay_ms(settle);

    /* Measure actual result */
    do_measurement();

    uart_puts("$SET,");
    uart_print_float("target=", freq_hz, 1);
    uart_puts(",");
    uart_print_int("code=", code);
    uart_puts(",");
    uart_print_float("actual=", current_freq_hz, 1);
    uart_puts(",");
    uart_print_float("rms=", current_rms_v * 1000.0f, 1);
    uart_puts("mV\r\n");
}

static void set_dac_code(uint16_t code)
{
    current_dac_code = code;
    dac7800_write(code);

    /* Settle time based on expected frequency */
    float expected = code_to_frequency(code);
    float period_ms = 1000.0f / expected;
    uint32_t settle = (uint32_t)(5.0f * period_ms);
    if (settle < 100) settle = 100;
    if (settle > 2000) settle = 2000;
    delay_ms(settle);

    do_measurement();

    uart_puts("$OSC,");
    uart_print_float("", current_freq_hz, 1);
    uart_puts(",");
    uart_print_int("", current_dac_code);
    uart_puts(",");
    uart_print_float("", current_rms_v * 1000.0f, 1);
    uart_puts(",");
    uart_print_int("", get_tick_ms());
    uart_puts("\r\n");
}

static void do_measurement(void)
{
    /* Number of periods to average depends on frequency */
    uint16_t avg_periods = 10;
    float expected = code_to_frequency(current_dac_code);
    if (expected < 50.0f) avg_periods = 3;
    if (expected > 5000.0f) avg_periods = 20;

    current_freq_hz = freq_measure_hz(avg_periods);
    current_rms_v = read_ad636_rms();
}

static void do_sweep(void)
{
    uart_puts("$INFO,=== FREQUENCY SWEEP ===\r\n");
    uart_puts("$INFO, DAC   Expected   Measured   Error%   RMS(mV)\r\n");

    /* Use same DAC codes as calibration */
    static const uint16_t sweep_codes[] = {
        3, 6, 12, 24, 48, 97, 121, 194,
        388, 605, 970, 1211, 1940, 2421, 3100, 3632
    };

    for (int i = 0; i < 16; i++) {
        uint16_t code = sweep_codes[i];
        float expected = code_to_frequency(code);

        /* If calibrated, use corrected code */
        uint16_t actual_code = code;
        if (cal_valid) {
            actual_code = calibrate_lookup(&cal_data, expected);
        }

        dac7800_write(actual_code);

        /* Settle */
        float period_ms = 1000.0f / expected;
        uint32_t settle = (uint32_t)(5.0f * period_ms);
        if (settle < 100) settle = 100;
        if (settle > 3000) settle = 3000;
        delay_ms(settle);

        /* Measure */
        uint16_t avg = (expected < 50.0f) ? 3 : 10;
        float meas_hz = freq_measure_hz(avg);
        float rms = read_ad636_rms();

        float err = 0.0f;
        if (expected > 0.1f) {
            err = (meas_hz - expected) / expected * 100.0f;
        }

        uart_puts("$SWP,");
        uart_print_int("", code);
        uart_puts(",");
        uart_print_float("", expected, 1);
        uart_puts(",");
        uart_print_float("", meas_hz, 1);
        uart_puts(",");
        uart_print_float("", err, 2);
        uart_puts("%,");
        uart_print_float("", rms * 1000.0f, 1);
        uart_puts("mV\r\n");
    }

    uart_puts("$INFO,Sweep complete\r\n");
}

static void print_status(void)
{
    uart_puts("\r\n$INFO,--- Oscillator Status ---\r\n");
    uart_print_int("$INFO,DAC code: ", current_dac_code);
    uart_puts("\r\n");
    uart_print_float("$INFO,Frequency: ", current_freq_hz, 1);
    uart_puts(" Hz\r\n");
    uart_print_float("$INFO,Expected:  ", code_to_frequency(current_dac_code), 1);
    uart_puts(" Hz\r\n");
    uart_print_float("$INFO,RMS:       ", current_rms_v * 1000.0f, 1);
    uart_puts(" mV\r\n");
    uart_puts("$INFO,Calibration: ");
    uart_puts(cal_valid ? "VALID" : "NONE");
    uart_puts("\r\n");
    if (cal_valid) {
        uart_print_float("$INFO,Max cal error: ",
                         cal_data.max_freq_error_pct, 2);
        uart_puts("%\r\n");
    }
}

/* ── Simple parsers (no stdlib float/int parse to save flash) ── */

static float parse_float(const char *s)
{
    /* Skip whitespace */
    while (*s == ' ') s++;

    float sign = 1.0f;
    if (*s == '-') { sign = -1.0f; s++; }
    else if (*s == '+') { s++; }

    float result = 0.0f;
    while (*s >= '0' && *s <= '9') {
        result = result * 10.0f + (float)(*s - '0');
        s++;
    }

    if (*s == '.') {
        s++;
        float frac = 0.1f;
        while (*s >= '0' && *s <= '9') {
            result += (float)(*s - '0') * frac;
            frac *= 0.1f;
            s++;
        }
    }

    return sign * result;
}

static int32_t parse_int(const char *s)
{
    while (*s == ' ') s++;

    int32_t sign = 1;
    if (*s == '-') { sign = -1; s++; }
    else if (*s == '+') { s++; }

    int32_t result = 0;
    while (*s >= '0' && *s <= '9') {
        result = result * 10 + (*s - '0');
        s++;
    }

    return sign * result;
}
