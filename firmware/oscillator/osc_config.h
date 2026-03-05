/**
 * osc_config.h - ADuCM362 configuration for State Variable Oscillator
 *
 * Hardware interface:
 *   SPI0: DAC7800 frequency control (P1.4=CLK, P1.5=MOSI, P1.3=CS)
 *   ADC0 AIN0: AD636 RMS output (via 1/5 attenuator)
 *   Timer1 / GPIO P0.5: BP zero-crossing input for frequency measurement
 *   UART: Host communication (P0.6=RX, P0.7=TX)
 *
 * Pin mapping matches build_oscillator() KiCad schematic.
 */

#ifndef OSC_CONFIG_H
#define OSC_CONFIG_H

#include <ADuCM360.h>
#include <stdint.h>
#include <stdbool.h>

/* ── System Clock ── */
#define SYSCLK_HZ           16000000UL
#define SYSTICK_HZ           1000         /* 1ms tick for precise timing */
#define SYSTICK_RELOAD       (SYSCLK_HZ / SYSTICK_HZ - 1)

/* ── UART ── */
#define UART_BAUD            115200
#define UART_RX_BIT          6
#define UART_TX_BIT          7

/* ── Oscillator Circuit Constants ── */
#define RFB_OHM              10000.0f      /* DAC7800 internal Rfb */
#define CINT_F               470.0e-12f    /* Integrator cap (C0G/NP0) */
#define TWO_PI               6.28318530f
#define FREQ_CONST           (4096.0f * TWO_PI * RFB_OHM * CINT_F)  /* 0.1211 */

/* DAC code limits */
#define DAC_CODE_MIN         3
#define DAC_CODE_MAX         3632
#define DAC_FULL_RANGE       4096

/* Frequency range (Hz) */
#define FREQ_MIN_HZ          24.8f
#define FREQ_MAX_HZ          30000.0f

/* ── Amplitude Target ── */
#define RMS_TARGET_V         1.00f         /* 1.0V RMS output */
#define RMS_TOLERANCE_V      0.02f         /* +/-2% deadband for AGC */
#define AD636_ATTEN_RATIO    5.0f          /* 1/5 input attenuator (40k + 10k) */

/* AD636 averaging */
#define AD636_CAV_UF         10.0f
#define AD636_RINT_OHM       8000.0f
#define AD636_TAU_MS         ((uint32_t)(AD636_RINT_OHM * AD636_CAV_UF * 1e-3f))  /* 80ms */

/* ── Calibration ── */
#define CAL_POINTS           16
#define CAL_SETTLE_PERIODS   5             /* wait 5 oscillation periods */
#define CAL_MEASURE_PERIODS  10            /* average 10 periods */
#define CAL_MAGIC            0xCA1B0A7DUL  /* magic for valid cal data */
#define CAL_FLASH_PAGE       61            /* flash page for cal storage */

/* ── AGC ── */
#define AGC_UPDATE_MS        100           /* AGC loop update rate */
#define AGC_STEP             1             /* digipot step per iteration */
#define DIGIPOT_INIT         56            /* initial code (~22k of 100k) */
#define DIGIPOT_MAX          255

/* ── SPI0 Pin Mapping (DAC7800) ── */
#define SPI_CLK_PORT         pADI_GP1
#define SPI_CLK_BIT          4             /* P1.4 = SPI0_CLK */
#define SPI_MOSI_PORT        pADI_GP1
#define SPI_MOSI_BIT         5             /* P1.5 = SPI0_MOSI */
#define DAC_CS_PORT          pADI_GP1
#define DAC_CS_BIT           3             /* P1.3 = CS_A (GPIO) */

/* ── Zero-Crossing Input ── */
#define ZC_PORT              pADI_GP0
#define ZC_BIT               5             /* P0.5 = BP comparator input */

/* ── ADC for AD636 ── */
#define ADC_PGA_GAIN         4             /* PGA = 4 for 0-300mV range */
#define ADC_VREF             1.2f          /* internal reference */
#define ADC_FULLSCALE        8388608.0f    /* 2^23 (signed) */
#define ADC_LSB_V            (ADC_VREF / (ADC_PGA_GAIN * ADC_FULLSCALE))

/* ── TX Buffer ── */
#define TX_BUF_SIZE          256

/* ── UART Packet Formats ── */
/* Oscillator status: $OSC,<freq_hz>,<dac_code>,<rms_mV>,<status>,<tick_ms>\r\n */
/* Calibration:       $CAL,<point>,<dac_code>,<freq_hz>,<rms_mV>\r\n             */
/* Info:              $INFO,<message>\r\n                                         */

#endif /* OSC_CONFIG_H */
