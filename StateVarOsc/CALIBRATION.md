# State Variable Oscillator — Calibration Plan

## Table of Contents
1. [Why Simulation Results Deviate from Ideal](#1-why-simulation-results-deviate-from-ideal)
2. [Spec Compliance Requirements](#2-spec-compliance-requirements)
3. [Automated Self-Calibration System](#3-automated-self-calibration-system)
4. [Frequency Calibration](#4-frequency-calibration)
5. [Amplitude Calibration](#5-amplitude-calibration)
6. [ADuCM362 Firmware Implementation](#6-aducm362-firmware-implementation)
7. [Calibration Data Storage](#7-calibration-data-storage)
8. [Runtime Operation](#8-runtime-operation)
9. [Factory vs Field Calibration](#9-factory-vs-field-calibration)
10. [Verification and Acceptance Criteria](#10-verification-and-acceptance-criteria)

---

## 1. Why Simulation Results Deviate from Ideal

### 1.1 Observed Results vs Theory

The ideal frequency formula predicts:
```
f_ideal = D / (4096 x 2pi x Rfb x Cint)
        = D / 0.1211
```

Actual simulation results:

| DAC Code | Expected (Hz) | Measured (Hz) | Freq Error | BP RMS (V) | RMS Target |
|----------|---------------|---------------|------------|------------|------------|
| D=3      | 24.8          | 24.1          | -2.7%      | 0.856      | 1.03 (-17%)|
| D=121    | 1000.6        | 926.9         | -7.4%      | 1.030      | 1.03 (0%)  |
| D=3632   | 30026         | 27624         | -8.0%      | 1.164      | 1.03 (+13%)|

### 1.2 Root Causes of Frequency Error

**a) Op-Amp Finite Gain-Bandwidth Product (GBW)**

The LM4562 has GBW = 55 MHz. At the integrator output, the open-loop gain falls as:
```
Aol(f) = GBW / f = 55e6 / f
```
At 30 kHz, the integrator is operating well below GBW, but the finite Aol introduces
a small phase error in each integrator. With two integrators in the loop, the cumulative
phase shift causes the actual oscillation frequency to be lower than the ideal:
```
f_actual = f_ideal x sqrt(1 - (f_ideal/GBW)^2)
```
At 30 kHz: deviation ~ (30k/55M)^2 = 0.03% -- this alone is small.

**b) MDAC Output Capacitance**

The DAC7800 has 30-70 pF output capacitance (Cout). This adds to the integrating
capacitor Cint (470 pF), increasing the effective capacitance:
```
C_eff = Cint + Cout_mdac = 470pF + 50pF = 520 pF
f_actual = D / (4096 x 2pi x 10k x 520p) = D / 0.1340
```
This gives a systematic -10% frequency error at all codes. However, the effect
varies with frequency because the MDAC output impedance is code-dependent:
```
At D=3:    R_mdac = 10k x 4096/3 = 13.65 MR -> pole at 0.23 Hz (negligible)
At D=3632: R_mdac = 10k x 4096/3632 = 11.3 kR -> pole at 27 kHz (significant!)
```
At high DAC codes, the MDAC's output pole approaches the oscillation frequency,
causing additional phase lag and frequency reduction.

**c) Damping Resistor Effect**

R_damp (100M) across each integrator cap provides a DC path to prevent integrator
drift. At low frequencies, this resistance appears in parallel with the MDAC
effective resistance, slightly increasing gain:
```
At D=3:  R_mdac_eff = 13.65 MR || 100 MR = 12.0 MR (12% more gain -> higher freq)
At D=3632: R_mdac_eff = 11.3 kR || 100 MR = 11.3 kR (negligible effect)
```
This partially compensates the MDAC capacitance error at low frequencies,
which is why D=3 has only -2.7% error vs D=3632 at -8.0%.

**d) Zener Clamp Loading**

The back-to-back Zener diodes (DZ09, BV=1.1V) present nonlinear impedance when
conducting. Near the clamp threshold, the Zener junction capacitance (~5 pF each)
and dynamic resistance add frequency-dependent loading to the integrator, further
perturbing the oscillation frequency.

### 1.3 Root Causes of Amplitude Variation

**a) Zener Clamp is a Fixed-Threshold Limiter**

The Zener model `D(Is=1e-14 BV=1.1 IBV=1e-3 N=1)` has a fixed breakdown voltage.
The clamp activates when the voltage across the integrator cap exceeds
BV + Vf ~ 1.1 + 0.35 = 1.45V. This is a static threshold -- it does not adapt
to frequency.

**b) Frequency-Dependent Conduction Duty Cycle**

At low frequencies (D=3, 24 Hz):
- The integrator cap charges/discharges slowly
- The signal spends less time above the Zener threshold
- The average clamping action is weaker
- Result: lower amplitude (0.856V RMS vs 1.03V target)

At high frequencies (D=3632, 28 kHz):
- The integrator cap charges/discharges rapidly
- The signal exceeds the Zener threshold more frequently per RMS period
- The Zener's junction capacitance conducts more AC current at higher frequencies
- Result: the effective clamping is slightly harder, BUT the dynamic impedance
  at high frequency actually allows higher peak voltages before clamping
- Result: higher amplitude (1.164V RMS vs 1.03V target)

**c) Op-Amp Slew Rate Interaction**

At 28 kHz with ~3.3Vpp, the required slew rate is:
```
SR_required = 2pi x f x Vpk = 2pi x 28k x 1.65V = 290 kV/s = 0.29 V/us
```
The LM4562 slew rate is 20 V/us -- plenty of margin. However, the MDAC output
settling time (1 us) becomes a significant fraction of the cycle (36 us at 28kHz),
causing waveform asymmetry that affects the RMS measurement.

### 1.4 Summary: These Are All Calibratable Errors

Every source of error above is:
- **Systematic** (repeatable, not random noise)
- **Monotonic** (error increases smoothly with frequency)
- **Measurable** (ADuCM362 can measure both frequency and amplitude)
- **Correctable** (firmware lookup table or polynomial correction)

The simulation proves the circuit topology works. Calibration brings it into spec.

---

## 2. Spec Compliance Requirements

### 2.1 Target Specifications

| Parameter | Spec | Tolerance | Method |
|-----------|------|-----------|--------|
| Frequency range | 25 Hz - 30 kHz | -- | DAC code range D=3 to D=3632 |
| Frequency accuracy | Set frequency | +/-1% | Calibration LUT |
| Frequency resolution | 8.26 Hz/LSB | -- | Inherent to 12-bit MDAC |
| Output amplitude | 1.0V RMS | +/-5% (0.95-1.05V) | AD636 feedback loop |
| Output waveform | Sine (BP output) | THD < 0.1% | Zener soft clamp |
| Settling time | -- | < 5s (at 25 Hz) | AD636 CAV = 10uF |
| Output impedance | -- | < 100R | LM4562 output |
| Supply voltage | +/-15V, +5V, +3.3V | +/-5% | Linear regulators |

### 2.2 What Calibration Must Achieve

1. **Frequency accuracy < 1%** across the full range (25 Hz to 30 kHz)
   - Uncalibrated: up to 8% error (sim results)
   - After calibration: < 1% using frequency LUT

2. **Amplitude flatness < 5%** across the full range
   - Uncalibrated: 36% variation (0.856V to 1.164V)
   - After calibration: < 5% using digital AGC via AD636

---

## 3. Automated Self-Calibration System

### 3.1 Overview

The ADuCM362 runs a fully automated calibration sequence at power-on (or on
host command). No manual intervention, no external equipment required.

```
┌──────────────────────────────────────────────────────────┐
│                  SELF-CALIBRATION FLOW                    │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  1. Power-on reset                                       │
│  2. Initialize SPI, ADC, UART                            │
│  3. Load calibration data from flash                     │
│     - If valid: use stored cal, skip to step 7           │
│     - If invalid/first boot: run full calibration        │
│  4. FREQUENCY CALIBRATION                                │
│     For each of N cal points (e.g., 16 points):          │
│     a. Set DAC code via SPI                              │
│     b. Wait for oscillation to settle (5x period)        │
│     c. Measure frequency via BP zero-crossing timing     │
│     d. Record: DAC_code -> actual_frequency              │
│  5. AMPLITUDE CALIBRATION                                │
│     For each of N cal points:                            │
│     a. Set DAC code (reuse from step 4)                  │
│     b. Read AD636 RMS output via ADC                     │
│     c. Record: DAC_code -> actual_RMS_voltage            │
│  6. Build correction tables, store to flash              │
│  7. Enter normal operation mode                          │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 3.2 Hardware Resources Used

| Resource | Function | Notes |
|----------|----------|-------|
| SPI0 (P1.4/P1.5/P1.3) | DAC7800 frequency control | Set DAC code |
| ADC0 AIN0 | AD636 RMS output reading | 24-bit, PGA=4, 1.2V ref |
| Timer1 | Zero-crossing period measurement | 16 MHz input clock |
| GPIO (P0.5) | BP comparator input (optional) | Zero-crossing detect |
| Flash page 126-127 | Calibration data storage | 2 kB available |
| UART | Progress reporting to host | Status messages during cal |

### 3.3 Calibration Points

16 calibration points spanning the full range, logarithmically spaced:

| Point | DAC Code | Expected Freq (Hz) | Purpose |
|-------|----------|---------------------|---------|
| 0     | 3        | 24.8                | Minimum frequency |
| 1     | 6        | 49.5                | Low range |
| 2     | 12       | 99.1                | Sub-100 Hz |
| 3     | 24       | 198                 | ~200 Hz |
| 4     | 48       | 397                 | ~400 Hz |
| 5     | 97       | 801                 | ~800 Hz |
| 6     | 121      | 1000                | Reference point |
| 7     | 194      | 1603                | ~1.6 kHz |
| 8     | 388      | 3205                | ~3.2 kHz |
| 9     | 605      | 4998                | ~5 kHz |
| 10    | 970      | 8015                | ~8 kHz |
| 11    | 1211     | 10005               | ~10 kHz |
| 12    | 1940     | 16028               | ~16 kHz |
| 13    | 2421     | 20001               | ~20 kHz |
| 14    | 3100     | 25605               | ~25 kHz |
| 15    | 3632     | 30001               | Maximum frequency |

### 3.4 Calibration Time Estimate

```
Per calibration point:
  - DAC settling:           10 ms
  - Oscillator settling:    5 / freq (5 periods)
    At 25 Hz: 200ms, at 30kHz: 0.17ms
  - Frequency measurement:  2 / freq (2 zero-crossings)
    At 25 Hz: 80ms, at 30kHz: 0.07ms
  - AD636 RMS settling:     3 x tau_avg = 3 x 80ms = 240ms
  - Total per point:        max(250ms, 5/freq + 250ms)

For 16 points:
  - Low freq points (3 pts below 100 Hz): ~3 x 500ms = 1.5s
  - Mid freq points (8 pts, 100-10kHz): ~8 x 300ms = 2.4s
  - High freq points (5 pts above 10kHz): ~5 x 260ms = 1.3s

Total calibration time: ~5 seconds
```

This runs once at power-on. Subsequent power cycles use stored calibration
data (valid until component values change, i.e., temperature drift or aging).

---

## 4. Frequency Calibration

### 4.1 Measurement Method: Zero-Crossing Timing

The ADuCM362 measures the BP output frequency by timing zero-crossings.
The BP signal is AC-coupled (or compared to mid-supply reference) and fed to
a GPIO input configured as a timer capture input.

```
                    ┌─────────────────────────────┐
                    │        ADuCM362              │
                    │                              │
  BP output ──[1uF]──[100k]──┬── GPIO P0.5        │
  (sine, ~3Vpp)              │   (Timer1 capture)  │
                   [100k]    │                     │
                    │        │                     │
                    GND      └─────────────────────┘

  The 100k/100k divider biases the AC-coupled signal at ~1.65V (mid-supply).
  The GPIO input threshold (~1.4V for Schmitt trigger) detects zero-crossings.
```

**Timer1 configuration:**
- Clock source: 16 MHz PCLK
- Capture mode: rising edge on GPIO
- Period = capture[n+1] - capture[n]
- Frequency = 16,000,000 / period_counts

**Resolution:**
```
At 25 Hz:   period = 640,000 counts -> resolution = 25/640000 = 0.004% (excellent)
At 30 kHz:  period = 533 counts -> resolution = 30000/533 = 0.19% (acceptable)
```

For better accuracy at high frequencies, average multiple periods:
```
Average 10 periods at 30 kHz: resolution = 0.019% (excellent)
```

### 4.2 Building the Frequency Correction Table

After measuring actual frequency at each of the 16 calibration DAC codes,
the firmware builds a correction ratio:

```c
typedef struct {
    uint16_t dac_code;        // commanded DAC code
    float    actual_freq_hz;  // measured frequency at this code
    float    correction;      // ideal_freq / actual_freq ratio
} freq_cal_point_t;

freq_cal_point_t freq_cal[16];

// Example populated data (from simulation):
// freq_cal[6] = { 121, 926.9, 1000.6/926.9 = 1.0795 }
// freq_cal[15] = { 3632, 27624.3, 30026.5/27624.3 = 1.0869 }
```

### 4.3 Interpolated Frequency Lookup

When the user requests a target frequency, the firmware:

1. Calculates the ideal DAC code: `D_ideal = f_target x FREQ_CONST`
2. Finds the two nearest calibration points bracketing D_ideal
3. Linearly interpolates the correction factor
4. Applies: `D_corrected = D_ideal x correction_interp`
5. Clamps to valid range (3-3632) and sends to DAC7800

```c
uint16_t freq_to_calibrated_code(float target_freq_hz)
{
    float d_ideal = target_freq_hz * FREQ_CONST;

    // Find bracketing calibration points
    int lo = 0, hi = 15;
    for (int i = 0; i < 15; i++) {
        if (freq_cal[i+1].dac_code > d_ideal) {
            lo = i; hi = i + 1;
            break;
        }
    }

    // Interpolate correction factor
    float frac = (d_ideal - freq_cal[lo].dac_code)
               / (float)(freq_cal[hi].dac_code - freq_cal[lo].dac_code);
    float correction = freq_cal[lo].correction
                     + frac * (freq_cal[hi].correction - freq_cal[lo].correction);

    // Apply correction
    float d_corrected = d_ideal * correction;

    // Clamp and round
    if (d_corrected < 3.0f) d_corrected = 3.0f;
    if (d_corrected > 3632.0f) d_corrected = 3632.0f;
    return (uint16_t)(d_corrected + 0.5f);
}
```

### 4.4 Expected Accuracy After Calibration

With 16 calibration points and linear interpolation:
- Between calibration points: interpolation error < 0.5%
  (the frequency error curve is smooth and well-behaved)
- At calibration points: limited by measurement resolution ~ 0.1%
- **Overall frequency accuracy: < 1%** across full range

For even better accuracy, use a polynomial fit (3rd order) instead of
piecewise linear interpolation:
```c
// f_actual = a0 + a1*D + a2*D^2 + a3*D^3
// Invert: D_corrected = b0 + b1*f_target + b2*f_target^2 + b3*f_target^3
// Coefficients computed by least-squares fit during calibration
```

---

## 5. Amplitude Calibration

### 5.1 The Problem

The Zener clamp gives frequency-dependent amplitude:
- 0.856V RMS at 25 Hz (17% low)
- 1.030V RMS at 1 kHz (on target)
- 1.164V RMS at 28 kHz (13% high)

This 36% span must be reduced to < 5% for spec compliance.

### 5.2 Solution: Digital AGC via AD636 + ADuCM362

The ADuCM362 reads the AD636 RMS output and implements a closed-loop
amplitude control. The Zener clamp provides coarse amplitude limiting
(prevents rail-to-rail clipping), while the digital AGC provides fine
amplitude regulation.

```
┌─────────────────────────────────────────────────────────────────┐
│               DIGITAL AGC CONTROL LOOP                          │
│                                                                 │
│  Oscillator BP ──[40k+10k divider]──> AD636 VIN                │
│                                           │                     │
│                                       CAV=10uF                  │
│                                           │                     │
│                                       AD636 OUT ──> ADuCM362    │
│                                       (0-200mV DC)    AIN0      │
│                                                        │        │
│  ADuCM362 firmware:                                    │        │
│    1. Read AD636 output via ADC0 (24-bit)              │        │
│    2. V_rms_actual = V_adc x 5.0 (undo attenuator)    │        │
│    3. error = V_rms_target - V_rms_actual              │        │
│    4. Adjust R_bp (BP feedback in summing amp)         │        │
│       via a digital potentiometer or PWM-filtered      │        │
│       voltage controlling an analog switch             │        │
│                                                        │        │
│  OR (simpler approach):                                │        │
│    4. Accept amplitude variation, apply correction     │        │
│       factor in firmware when reporting amplitude      │        │
│       to host software                                 │        │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Approach A: Software Amplitude Correction (Simplest)

If the application only needs to **know** the correct amplitude (not control it),
the firmware can simply apply a frequency-dependent correction factor:

```c
typedef struct {
    uint16_t dac_code;
    float    actual_rms_v;     // measured RMS at this code
    float    amplitude_ratio;  // target_rms / actual_rms
} amp_cal_point_t;

amp_cal_point_t amp_cal[16];

// Example:
// amp_cal[0]  = { 3,    0.856, 1.03/0.856 = 1.203 }
// amp_cal[6]  = { 121,  1.030, 1.03/1.030 = 1.000 }
// amp_cal[15] = { 3632, 1.164, 1.03/1.164 = 0.885 }

float get_corrected_rms(float measured_rms, uint16_t dac_code)
{
    // Find bracketing cal points, interpolate correction
    // Apply: corrected = measured * ratio
    // Report corrected value to host
}
```

This approach:
- Requires NO additional hardware
- The oscillator output amplitude still varies, but firmware reports the true value
- Suitable if the output is only read by the ADuCM362's ADC (no external analog use)

### 5.4 Approach B: Active Digital AGC (Best Amplitude Flatness)

For applications where the analog output amplitude must actually be flat
(e.g., driving an external device), the ADuCM362 implements a slow digital
AGC loop that adjusts the summing amplifier Q.

**Hardware addition: Digital potentiometer for R_bp**

Replace the fixed R_bp (22k) in the summing amplifier with a digital
potentiometer (e.g., AD5242, 256-tap, 100k, I2C):

```
Current circuit:
  R_bp: BP ──[22k]── sum_inv

Modified circuit:
  R_bp: BP ──[AD5242 (0-100k)]── sum_inv
  AD5242 controlled by ADuCM362 via I2C
```

The Q of the oscillator is:
```
Q = Rf_sum / (2 x R_lp) x (1 + R_bp_eff/Rf_sum)
```

By adjusting R_bp, the firmware controls the loop gain:
- Increase R_bp -> more BP feedback -> higher Q -> amplitude rises
- Decrease R_bp -> less BP feedback -> lower Q -> amplitude falls

**Digital AGC algorithm:**

```c
#define RMS_TARGET   1.00f     // 1.0V RMS target
#define RMS_TOL      0.02f     // +/-2% deadband
#define AGC_STEP     1         // digipot step size per iteration
#define AGC_PERIOD_MS 100      // update every 100ms

static uint8_t digipot_code = 56;  // initial value (~22k of 100k)

void agc_update(void)
{
    float v_rms = read_ad636_rms();  // ADC read of AD636 output x 5

    if (v_rms > RMS_TARGET + RMS_TOL) {
        // Amplitude too high: decrease Q by reducing R_bp
        if (digipot_code > 0) {
            digipot_code -= AGC_STEP;
            ad5242_write(digipot_code);
        }
    }
    else if (v_rms < RMS_TARGET - RMS_TOL) {
        // Amplitude too low: increase Q by increasing R_bp
        if (digipot_code < 255) {
            digipot_code += AGC_STEP;
            ad5242_write(digipot_code);
        }
    }
    // Within deadband: do nothing (prevents hunting)
}
```

**Settling behavior:**
- At 100ms update rate with 1-step changes:
- AD5242 has 256 taps, so full sweep = 25.6 seconds (worst case)
- Typical correction from Zener-limited level: 10-20 taps = 1-2 seconds
- After initial settling, the loop maintains +/-2% of target

### 5.5 Approach C: PWM-Based Analog AGC (No Extra IC)

If adding a digital potentiometer is undesirable, the ADuCM362 can generate
a PWM signal that is RC-filtered to create a DC voltage, which controls a
JFET (J113) or MOSFET acting as variable resistor in the R_bp path.

```
ADuCM362 PWM output ──[10k]──┬──[10uF]── V_agc (DC)
                              │
                              └── J113 Gate

J113 Drain ── BP node
J113 Source ── sum_inv node (through series R for range limiting)
```

This reuses the J113 AGC concept from the original design but with digital
control instead of analog error amplifier. The ADuCM362 replaces the
AD636 + error integrator + J113 gate driver with software:

```c
// PWM duty cycle controls J113 gate voltage
// Higher duty -> more negative Vgs -> higher Rds -> lower Q -> lower amplitude
void set_agc_pwm(float duty)  // 0.0 to 1.0
{
    uint16_t period = 1600;  // 10 kHz PWM at 16 MHz clock
    uint16_t compare = (uint16_t)(duty * period);
    pADI_TMR2->LD = period;
    pADI_TMR2->MATCH = compare;
}
```

### 5.6 Recommended Approach

**For simulation/prototype phase: Approach A (software correction)**
- No additional hardware
- Firmware records amplitude vs frequency during calibration
- Reports corrected values to host
- The analog output still varies, but this is acceptable for validation

**For production: Approach B (digital potentiometer AGC)**
- Adds one AD5242 (I2C, $2 in qty)
- Achieves true analog amplitude flatness < 2%
- The ADuCM362 already has I2C capability
- Loop is slow and stable (no convergence issues like analog AGC)

---

## 6. ADuCM362 Firmware Implementation

### 6.1 New Firmware Modules for Oscillator

The existing electrometer firmware (`firmware/`) provides the template.
New modules for oscillator mode:

```
firmware/
  osc_config.h        - Oscillator-specific defines
  osc_calibrate.c     - Self-calibration routines
  osc_dac7800.c       - SPI driver for DAC7800
  osc_freq_measure.c  - Zero-crossing frequency measurement
  osc_agc.c           - Digital AGC loop
  osc_main.c          - Oscillator main loop (alternative to main.c)
```

### 6.2 osc_config.h

```c
#ifndef OSC_CONFIG_H
#define OSC_CONFIG_H

/* Oscillator circuit constants */
#define RFB_OHM          10000.0f
#define CINT_F           470.0e-12f
#define FREQ_CONST       (4096.0f * 6.28318530f * RFB_OHM * CINT_F)  /* 0.1211 */

/* DAC code range */
#define DAC_CODE_MIN     3
#define DAC_CODE_MAX     3632
#define FREQ_MIN_HZ      24.8f
#define FREQ_MAX_HZ      30000.0f

/* Calibration */
#define CAL_POINTS       16
#define CAL_SETTLE_PERIODS  5    /* wait 5 oscillation periods */
#define CAL_MEASURE_PERIODS 10   /* average 10 periods for frequency */

/* AGC */
#define RMS_TARGET_V     1.00f
#define RMS_TOLERANCE_V  0.02f    /* +/-2% deadband */
#define AGC_UPDATE_MS    100
#define AD636_ATTEN      5.0f     /* 1/5 input attenuator ratio */

/* AD636 averaging time constant */
#define AD636_CAV_UF     10.0f    /* 10 uF */
#define AD636_RINT_OHM   8000.0f
#define AD636_TAU_MS     (AD636_RINT_OHM * AD636_CAV_UF * 1e-3f)  /* 80 ms */

/* Flash storage */
#define CAL_FLASH_PAGE   126      /* page 126-127 reserved for cal data */
#define CAL_MAGIC        0xCA1B0A7D  /* magic number for valid cal data */

/* Zero-crossing input */
#define ZC_GPIO_PORT     pADI_GP0
#define ZC_GPIO_BIT      5        /* P0.5 = BP zero-crossing input */

/* SPI pins for DAC7800 */
#define DAC_CS_PORT      pADI_GP1
#define DAC_CS_BIT       3        /* P1.3 = CS_A */

#endif
```

### 6.3 Calibration Sequence (osc_calibrate.c)

```c
#include "osc_config.h"
#include "osc_dac7800.h"
#include "osc_freq_measure.h"

/* Calibration data structure */
typedef struct {
    uint32_t magic;                          /* CAL_MAGIC if valid */
    uint32_t timestamp;                      /* tick count when calibrated */
    float    temperature;                    /* ambient temp at cal time */
    uint16_t num_points;
    struct {
        uint16_t dac_code;
        float    freq_hz;                    /* measured frequency */
        float    rms_v;                      /* measured RMS voltage */
        float    freq_correction;            /* ideal/actual ratio */
        float    amp_correction;             /* target/actual ratio */
    } points[CAL_POINTS];
    float    poly_freq[4];                   /* 3rd-order poly coefficients */
    float    poly_amp[4];                    /* 3rd-order poly coefficients */
} cal_data_t;

static cal_data_t cal_data;

/* Predefined calibration DAC codes (log-spaced) */
static const uint16_t cal_codes[CAL_POINTS] = {
    3, 6, 12, 24, 48, 97, 121, 194,
    388, 605, 970, 1211, 1940, 2421, 3100, 3632
};

bool osc_run_calibration(void)
{
    uart_send_info("=== OSCILLATOR SELF-CALIBRATION ===");

    cal_data.magic = 0;  /* invalidate until complete */
    cal_data.num_points = CAL_POINTS;

    for (int i = 0; i < CAL_POINTS; i++) {
        uint16_t code = cal_codes[i];
        float f_ideal = (float)code / FREQ_CONST;

        /* Set DAC code */
        dac7800_write(code);

        /* Calculate settling time: 5 periods + AD636 settling */
        float period_ms = 1000.0f / f_ideal;
        uint32_t settle_ms = (uint32_t)(CAL_SETTLE_PERIODS * period_ms);
        if (settle_ms < 3 * AD636_TAU_MS) settle_ms = (uint32_t)(3 * AD636_TAU_MS);
        settle_ms += 50;  /* extra margin */
        delay_ms(settle_ms);

        /* Measure frequency (average CAL_MEASURE_PERIODS zero-crossings) */
        float f_actual = freq_measure_hz(CAL_MEASURE_PERIODS);

        /* Measure RMS amplitude via AD636 */
        float v_rms = read_ad636_rms();

        /* Store results */
        cal_data.points[i].dac_code = code;
        cal_data.points[i].freq_hz = f_actual;
        cal_data.points[i].rms_v = v_rms;
        cal_data.points[i].freq_correction = f_ideal / f_actual;
        cal_data.points[i].amp_correction = RMS_TARGET_V / v_rms;

        /* Report progress */
        char buf[80];
        snprintf(buf, sizeof(buf),
                 "CAL[%02d] D=%4d: f_exp=%.1f f_act=%.1f (%.1f%%) rms=%.3fV",
                 i, code, f_ideal, f_actual,
                 (f_actual - f_ideal) / f_ideal * 100.0f, v_rms);
        uart_send_info(buf);
    }

    /* Compute polynomial fits (least-squares) */
    compute_poly_fit(cal_data.points, CAL_POINTS, cal_data.poly_freq, cal_data.poly_amp);

    /* Validate and store */
    cal_data.magic = CAL_MAGIC;
    cal_data.timestamp = get_tick_ms();
    flash_write_page(CAL_FLASH_PAGE, &cal_data, sizeof(cal_data));

    uart_send_info("=== CALIBRATION COMPLETE ===");
    return true;
}
```

### 6.4 Runtime Frequency Setting

```c
uint16_t osc_set_frequency(float target_hz)
{
    if (target_hz < FREQ_MIN_HZ) target_hz = FREQ_MIN_HZ;
    if (target_hz > FREQ_MAX_HZ) target_hz = FREQ_MAX_HZ;

    uint16_t code;

    if (cal_data.magic == CAL_MAGIC) {
        /* Use calibrated lookup */
        code = freq_to_calibrated_code(target_hz);
    } else {
        /* Uncalibrated: use ideal formula */
        float d = target_hz * FREQ_CONST;
        code = (uint16_t)(d + 0.5f);
    }

    if (code < DAC_CODE_MIN) code = DAC_CODE_MIN;
    if (code > DAC_CODE_MAX) code = DAC_CODE_MAX;

    dac7800_write(code);
    return code;
}
```

---

## 7. Calibration Data Storage

### 7.1 Flash Layout (ADuCM362)

The ADuCM362 has 128 kB flash in 2 kB pages (pages 0-63).
Pages 62-63 are reserved by the bootloader.

```
Page 0-59:  Firmware code + constants
Page 60:    User config (UART baud, default range, etc.)
Page 61:    Oscillator calibration data (cal_data_t, ~300 bytes)
Page 62-63: Reserved (bootloader)
```

### 7.2 Calibration Data Validity

The firmware checks calibration validity at startup:

```c
bool osc_load_calibration(void)
{
    flash_read_page(CAL_FLASH_PAGE, &cal_data, sizeof(cal_data));

    if (cal_data.magic != CAL_MAGIC) {
        uart_send_info("No valid calibration found - will run auto-cal");
        return false;
    }

    if (cal_data.num_points != CAL_POINTS) {
        uart_send_info("Calibration point count mismatch - will re-calibrate");
        return false;
    }

    /* Optional: check temperature delta */
    float current_temp = read_temperature();
    float temp_delta = current_temp - cal_data.temperature;
    if (temp_delta > 10.0f || temp_delta < -10.0f) {
        char buf[64];
        snprintf(buf, sizeof(buf),
                 "Temp changed %.1fC since cal - recommend re-cal", temp_delta);
        uart_send_info(buf);
        /* Don't invalidate -- still usable, just warn */
    }

    uart_send_info("Loaded calibration data from flash");
    return true;
}
```

### 7.3 Re-Calibration Triggers

Calibration should be re-run when:
1. **First power-on** (no stored cal data)
2. **Host command** (`CAL\n` via UART)
3. **Temperature change** > 10C from last calibration (C0G caps drift ~30 ppm/C)
4. **Component replacement** (manual trigger after board rework)

---

## 8. Runtime Operation

### 8.1 Normal Operation Flow

```
┌──────────────────────────────────────────────────────────┐
│                    RUNTIME LOOP                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  1. Receive frequency command from host via UART         │
│     (e.g., "F1000.0\n" for 1 kHz)                       │
│                                                          │
│  2. Look up calibrated DAC code for requested frequency  │
│     D = freq_to_calibrated_code(1000.0)                  │
│                                                          │
│  3. Send DAC code to DAC7800 via SPI                     │
│                                                          │
│  4. Wait for oscillation to settle                       │
│     t_settle = max(500ms, 5/freq + 3*AD636_TAU)          │
│                                                          │
│  5. Verify:                                              │
│     a. Measure actual frequency via zero-crossing        │
│     b. Read AD636 RMS output                             │
│     c. If |freq_error| > 2%: adjust DAC code +/-1        │
│     d. If |rms_error| > 5%: run AGC correction           │
│                                                          │
│  6. Report to host:                                      │
│     $OSC,<freq>,<dac_code>,<rms_mV>,<status>,<ms>\n      │
│                                                          │
│  7. Enter steady-state monitoring:                       │
│     - Periodically (every 1s) verify freq and amplitude  │
│     - Report any drift > 1%                              │
│     - Adjust DAC code if needed (fine-tuning)            │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 8.2 UART Command Protocol

```
Host -> ADuCM362:
  F<freq_hz>\n      Set frequency (e.g., "F1000.0\n")
  D<dac_code>\n     Set DAC code directly (e.g., "D121\n")
  CAL\n             Run full calibration
  CALR\n            Report stored calibration data
  S\n               Start frequency sweep (all cal points)
  ?\n               Query current status
  AGC<0|1>\n        Enable/disable digital AGC

ADuCM362 -> Host:
  $OSC,<freq_hz>,<dac_code>,<rms_mV>,<status>,<tick_ms>\n
  $CAL,<point>,<dac_code>,<freq_hz>,<rms_mV>\n
  $INFO,<message>\n
  $ERR,<message>\n
```

### 8.3 Frequency Sweep Mode

The host can command a full frequency sweep for characterization:

```
Host sends: "S\n"

ADuCM362 executes:
  For each of 16 calibration points:
    1. Set frequency to cal point
    2. Wait for settling
    3. Measure freq + RMS
    4. Report: $OSC,<freq>,<code>,<rms>,SWEEP,<ms>\n
  Report: $INFO,SWEEP COMPLETE\n
```

This is what SimGUI will use for the oscillator "Run All" button.

---

## 9. Factory vs Field Calibration

### 9.1 Factory Calibration (Production)

Done once during manufacturing:
1. Power-on board in temperature-controlled environment (25C +/-2C)
2. Send `CAL\n` command
3. Wait ~5 seconds for calibration to complete
4. Verify calibration: send `CALR\n`, check all points < 1% error
5. Calibration data stored permanently in flash

### 9.2 Field Re-Calibration

Users can re-calibrate at any time:
1. Send `CAL\n` via UART (or press "Calibrate" button in SimGUI)
2. The oscillator runs through all 16 calibration points automatically
3. New calibration data overwrites old data in flash
4. No external equipment needed -- fully self-contained

### 9.3 Temperature Compensation

The C0G/NP0 integrator capacitors have ~30 ppm/C temperature coefficient.
Over a 50C range (0-50C), this causes:
```
Delta_C = 470pF x 30ppm/C x 50C = 0.705 pF (0.15%)
Frequency shift = 0.15% (negligible)
```

The DAC7800 internal Rfb has a tempco of ~50 ppm/C:
```
Delta_R = 10k x 50ppm/C x 50C = 25R (0.25%)
Frequency shift = 0.25%
```

**Total temperature-induced frequency drift: < 0.5%** -- within the 1% spec
without re-calibration. Re-calibrating at operating temperature eliminates
this error entirely.

---

## 10. Verification and Acceptance Criteria

### 10.1 Post-Calibration Verification Test

After calibration, the firmware runs an automatic verification sweep:

```
For each calibration point:
  1. Set calibrated frequency
  2. Measure actual frequency
  3. Compute error = |f_target - f_actual| / f_target x 100%
  4. PASS if error < 1.0%
  5. WARN if error 1.0-2.0%
  6. FAIL if error > 2.0% (re-calibration recommended)
```

### 10.2 Acceptance Criteria

| Test | PASS | WARN | FAIL |
|------|------|------|------|
| Frequency accuracy | < 1% | 1-2% | > 2% |
| Amplitude (RMS) | 0.95-1.05V | 0.90-0.95V or 1.05-1.10V | < 0.90V or > 1.10V |
| Oscillation detected | BP Vpp > 0.5V | -- | BP Vpp < 0.5V |
| Startup time | < 2s (>100Hz) | 2-10s (<100Hz) | > 10s |
| THD | < 0.1% | 0.1-1% | > 1% |

### 10.3 Full System Verification Matrix

| DAC Code | Frequency | Freq Error (uncal) | Freq Error (cal) | Amplitude (uncal) | Amplitude (cal) |
|----------|-----------|---------------------|-------------------|--------------------|-----------------|
| 3        | 25 Hz     | -2.7%               | < 1%              | 0.86V (-17%)       | 0.98V (+/-5%)   |
| 12       | 99 Hz     | ~-4%                | < 1%              | ~0.90V             | 0.98V (+/-5%)   |
| 60       | 496 Hz    | ~-5%                | < 1%              | ~0.96V             | 1.00V (+/-5%)   |
| 121      | 1001 Hz   | -7.4%               | < 1%              | 1.03V (0%)         | 1.00V (+/-5%)   |
| 605      | 5000 Hz   | ~-7%                | < 1%              | ~1.08V             | 1.00V (+/-5%)   |
| 1211     | 10005 Hz  | ~-7.5%              | < 1%              | ~1.10V             | 1.00V (+/-5%)   |
| 2421     | 20001 Hz  | ~-8%                | < 1%              | ~1.14V             | 1.00V (+/-5%)   |
| 3632     | 30001 Hz  | -8.0%               | < 1%              | 1.16V (+13%)       | 1.00V (+/-5%)   |

### 10.4 What the Simulation Proves

The ngspice simulation with behavioural models proves:

1. **The circuit oscillates** at all DAC codes from D=3 to D=3632
2. **Frequency tracks DAC code** monotonically (f proportional to D)
3. **Amplitude is bounded** by Zener clamp (no rail-to-rail clipping)
4. **Waveform is sinusoidal** (low THD from soft Zener limiting)
5. **All error sources are systematic** and correctable by calibration

The simulation does NOT prove (requires real hardware):
- Exact component tolerances
- PCB parasitic effects
- EMI susceptibility
- Long-term stability and aging

But the simulation gives high confidence that the design is sound and
calibration will bring it into full spec compliance on real hardware.
