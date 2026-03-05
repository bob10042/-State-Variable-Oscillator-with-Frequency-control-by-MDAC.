# State Variable Oscillator — Circuit Calculations

## Table of Contents
1. [State Variable Filter Theory](#1-state-variable-filter-theory)
2. [Oscillation Conditions](#2-oscillation-conditions)
3. [Frequency Control via MDAC](#3-frequency-control-via-mdac)
4. [Component Value Selection](#4-component-value-selection)
5. [AGC Loop Design](#5-agc-loop-design)
6. [RMS Detector Averaging](#6-rms-detector-averaging)
7. [Power Supply & Headroom](#7-power-supply--headroom)
8. [ESP32 Digital Control Interface](#8-esp32-digital-control-interface)
9. [Noise Analysis](#9-noise-analysis)
10. [Complete Bill of Materials](#10-complete-bill-of-materials)

---

## 1. State Variable Filter Theory

### 1.1 Basic Topology

The state variable filter (SVF) uses three op-amp sections:
- **U1a**: Summing amplifier (inverts and sums HP + LP feedback)
- **U1b**: Integrator 1 (HP → BP, bandpass output)
- **U2a**: Integrator 2 (BP → LP, lowpass output)

### 1.2 Transfer Functions

For the standard SVF with equal integrator time constants:

```
                    -s² / (R1·C·ω₀)
H_HP(s) = ────────────────────────────────
           s² + s·ω₀/Q + ω₀²

                    -s·ω₀ / (R1·C·ω₀)
H_BP(s) = ────────────────────────────────
           s² + s·ω₀/Q + ω₀²

                    -ω₀² / (R1·C·ω₀)
H_LP(s) = ────────────────────────────────
           s² + s·ω₀/Q + ω₀²
```

Where:
- `ω₀ = 1/(R_int × C_int)` — natural frequency (rad/s)
- `f₀ = ω₀/(2π)` — frequency in Hz
- `Q = R3/(2×R1)` — quality factor (for oscillation, Q → ∞)

### 1.3 Circuit Equations

**Summing amplifier (U1a):**
```
V_HP = -(R1/R1)·V_LP - (R3/R1)·V_BP + external input (if any)
     = -V_LP - (R3/R1)·V_BP
```

**Integrator 1 (U1b):**
```
V_BP = -1/(R_int × C_int) × ∫ V_HP dt
```

**Integrator 2 (U2a):**
```
V_LP = -1/(R_int × C_int) × ∫ V_BP dt
```

---

## 2. Oscillation Conditions

### 2.1 Barkhausen Criterion

For sustained oscillation, the loop gain must equal exactly 1 at the oscillation frequency:
- **Gain condition:** |A·β| = 1
- **Phase condition:** ∠(A·β) = 0° (or 360°)

### 2.2 SVF as Oscillator

Setting Q = ∞ means zero damping. In the SVF, Q is controlled by the ratio R3/R1 in the summing amplifier. For oscillation:

```
Q = R3 / (2 × R1)
```

When Q → ∞: R3 → ∞ (remove the BP feedback resistor from the summing amp).

In practice, Q is controlled by the AGC loop: the J113 JFET replaces R3, and its resistance is adjusted to maintain exactly unity loop gain.

### 2.3 Oscillation Frequency

```
f_osc = 1 / (2π × R_int × C_int)
```

Where R_int and C_int are the integrator resistor and capacitor.

### 2.4 Output Waveforms

At the oscillation frequency:
- **V_HP**: Highpass output = cosine (90° phase lead from BP)
- **V_BP**: Bandpass output = sine (lowest distortion — this is the main output)
- **V_LP**: Lowpass output = -cosine (90° phase lag from BP)

All three outputs have the same frequency and amplitude.

---

## 3. Frequency Control via MDAC

### 3.1 MDAC as Variable Resistor

The DAC7800 in voltage mode acts as a programmable attenuator:

```
Gain = D / 4096
```

Where D = 12-bit digital code (0 to 4095).

When placed at the input of the integrator, the MDAC multiplies the input signal before integration:

```
V_out = -1/(R_fb × C) × ∫ (D/4096 × V_in) dt
```

The effective integration time constant becomes:

```
τ_eff = R_fb × C × 4096 / D
```

### 3.2 Oscillation Frequency with MDAC

Substituting into the frequency equation:

```
f_osc = D / (4096 × 2π × R_fb × C_int)
```

This gives a linear frequency-vs-code relationship (f ∝ D).

### 3.3 Frequency Range Calculation

**Given:**
- f_min = 20 Hz (at D_min)
- f_max = 30,000 Hz (at D_max)
- R_fb = 10 kΩ (internal to DAC7800)
- D range: 1 to 4095

**Solving for C_int:**

From f_osc = D / (4096 × 2π × R_fb × C_int):

```
C_int = D / (4096 × 2π × R_fb × f_osc)
```

At maximum frequency (f = 30 kHz, D = D_max):
```
C_int = D_max / (4096 × 2π × 10k × 30k)
```

We want D_max ≤ 4095, so:
```
C_int = 4095 / (4096 × 2π × 10k × 30k)
      = 4095 / (7.72 × 10⁹)
      = 530 pF
```

**Check minimum frequency at D_min:**
```
f_min = D_min / (4096 × 2π × 10k × 530p)
      = D_min / (0.1362)
```

For f_min = 20 Hz: D_min = 20 × 0.1362 = 2.72 → **D_min = 3**

At D = 3: f = 3 / 0.1362 = **22.0 Hz** ✓

**Verification:**
```
D = 3:     f = 3 / (4096 × 2π × 10k × 530p)    = 22.0 Hz    ✓
D = 100:   f = 100 / 0.1362                      = 734 Hz     ✓
D = 1000:  f = 1000 / 0.1362                     = 7.34 kHz   ✓
D = 4095:  f = 4095 / 0.1362                     = 30.07 kHz  ✓
```

### 3.4 Selected Value

**C_int = 470 pF** (nearest standard E12 value below 530 pF)

With C = 470 pF:
```
Frequency constant = 4096 × 2π × 10k × 470p = 0.1211

D = 3:     f = 3 / 0.1211     = 24.8 Hz
D = 4:     f = 4 / 0.1211     = 33.0 Hz
D = 100:   f = 100 / 0.1211   = 826 Hz
D = 1000:  f = 1000 / 0.1211  = 8.26 kHz
D = 3632:  f = 3632 / 0.1211  = 30.0 kHz
D = 4095:  f = 4095 / 0.1211  = 33.8 kHz
```

**Usable range: D = 3 to 3632 → 24.8 Hz to 30.0 kHz**

Frequency resolution at key points:
```
At 20 Hz:   Δf per LSB = 1/0.1211 = 8.26 Hz  (coarse)
At 1 kHz:   Δf per LSB = 8.26 Hz              (0.8%)
At 10 kHz:  Δf per LSB = 8.26 Hz              (0.08%)
At 30 kHz:  Δf per LSB = 8.26 Hz              (0.03%)
```

Note: Frequency resolution is constant in Hz (linear), which means poor relative resolution at low frequencies. This is inherent to the MDAC-controlled SVF topology.

---

## 4. Component Value Selection

### 4.1 Integrator Components

| Component | Value | Purpose |
|-----------|-------|---------|
| C_int     | 470 pF | Integrator capacitor (C0G/NP0 ceramic) |
| R_fb      | 10 kΩ  | MDAC internal feedback resistor |

**Capacitor type:** Must use C0G/NP0 for temperature stability and linearity. X7R or X5R will cause frequency drift and distortion.

### 4.2 Summing Amplifier Components

| Component | Value | Purpose |
|-----------|-------|---------|
| R1 (HP input) | 10 kΩ | Sets gain from HP output |
| R2 (LP feedback) | 10 kΩ | Sets gain from LP output |
| R_agc (J113) | Variable | AGC-controlled Q (replaces R3) |

Summing amp equation:
```
V_HP = -(R2/R1)·V_LP - (R_agc/R1)·V_BP
     = -V_LP - (R_agc/10k)·V_BP
```

For oscillation: R_agc must be set by the AGC loop to achieve exactly unity loop gain.

### 4.3 MDAC Configuration

The DAC7800 is used in **voltage-multiplying mode**:
- VREF pin: connected to integrator input signal
- IOUT1 pin: connected to op-amp summing junction (virtual ground)
- RFB pin: connected to op-amp output (forms feedback)

The op-amp + MDAC combination acts as a programmable-gain integrator:
```
V_out = -(D/4096) × (1/(R_fb × C)) × ∫ V_in dt
```

### 4.4 Component Tolerances

| Parameter | Requirement | Notes |
|-----------|-------------|-------|
| C_int tolerance | ±2% C0G | Sets absolute frequency accuracy |
| C_int matching | ±1% between integrators | Sets output symmetry |
| R_fb (internal) | Fixed in DAC7800 | ~10 kΩ ± 20% (affects absolute freq) |
| R1, R2 | ±1% metal film | Sets gain symmetry |

---

## 5. AGC Loop Design

### 5.1 Purpose

Without AGC, the oscillator amplitude is determined by op-amp clipping, which produces high distortion. The AGC loop:
1. Measures the output RMS level
2. Compares to a reference (1V RMS)
3. Adjusts the J113 JFET resistance to control loop gain
4. Maintains amplitude at exactly 1V RMS with low distortion

### 5.2 J113 as Variable Resistor

In the linear (ohmic) region with small Vds:

```
Rds ≈ 1 / (2 × Beta × (Vgs - Vto))
```

Where:
- Beta = 9.109 mA/V² (from SPICE model)
- Vto = -1.382 V (pinch-off voltage)

```
At Vgs = 0V:     Rds = 1/(2 × 9.109m × (0-(-1.382))) = 1/(25.16m) = 39.7 Ω
At Vgs = -0.5V:  Rds = 1/(2 × 9.109m × (-0.5+1.382)) = 1/(16.08m) = 62.2 Ω
At Vgs = -1.0V:  Rds = 1/(2 × 9.109m × (-1.0+1.382)) = 1/(6.96m)  = 143.6 Ω
At Vgs = -1.3V:  Rds = 1/(2 × 9.109m × (-1.3+1.382)) = 1/(1.49m)  = 670 Ω
At Vgs = -1.38V: Rds → very large (near pinch-off)
```

### 5.3 AGC Operating Point

For oscillation at 1V RMS:
- V_BP amplitude = 1V RMS = 1.414V peak
- The J113 Vds must be small (< 100mV) to stay in ohmic region
- This means the J113 is placed in a low-signal-level feedback path

**Configuration:** J113 in the summing amplifier feedback, with a voltage divider to keep Vds small.

### 5.4 AGC Loop Components

```
                     ┌─────────────────────────┐
  V_BP ──[attenuator]──> AD636 ──> V_rms       │
                                    │           │
                          V_ref ──(─)── error   │
                          (1V DC)   │           │
                                  [R_loop]      │
                                    │           │
                                  [C_loop]      │
                                    │           │
                                 J113 Gate ─────┘
```

### 5.5 Input Attenuator for AD636

The AD636 input range is 0–200 mV RMS. Our oscillator outputs 1V RMS.
Need a 1/5 attenuator (1V → 200mV):

```
                 R_att1 = 40 kΩ
V_BP ──[40kΩ]──┬──[10kΩ]── GND
                │    R_att2
                └── AD636 VIN

Gain = R_att2 / (R_att1 + R_att2) = 10k / (40k + 10k) = 1/5
```

At the AD636 input: 1V RMS × 0.2 = 200 mV RMS (full scale)

### 5.6 Error Amplifier

The AD636 output (DC voltage = RMS of input) is compared to a reference:

```
V_ref = 200 mV  (corresponds to 1V RMS at oscillator output)
V_error = V_rms - V_ref
```

When amplitude is too high: V_error > 0 → drive J113 gate more negative → increase Rds → reduce Q → amplitude drops.

When amplitude is too low: V_error < 0 → drive J113 gate less negative → decrease Rds → increase Q → amplitude rises.

### 5.7 Loop Integrator

The error signal is integrated to provide smooth control:

```
R_loop = 100 kΩ
C_loop = 1 µF
τ_loop = R_loop × C_loop = 100 ms
```

This gives:
- At 20 Hz: ~2 cycles per time constant (marginal, but workable)
- At 1 kHz: ~100 cycles per time constant (good)
- At 30 kHz: ~3000 cycles per time constant (excellent)

### 5.8 Reference Voltage

Use a precision voltage reference:
```
V_ref = 200 mV
```

Can be derived from supply with a resistive divider + op-amp buffer, or use a voltage reference IC.

For initial simulation, a DC source is sufficient.

---

## 6. RMS Detector Averaging

### 6.1 AD636 Averaging Time Constant

Internal resistance: R_avg = 8 kΩ
External capacitor: C_AV

```
τ_avg = R_avg × C_AV = 8000 × C_AV
```

### 6.2 Requirements

The averaging must satisfy two competing requirements:

1. **Sufficient averaging:** τ_avg >> 1/f_osc (many cycles for accurate RMS)
2. **Fast enough response:** τ_avg should allow the AGC to track amplitude changes

### 6.3 C_AV Selection

For the lowest frequency (20 Hz), we need at least ~10 cycles for 1% RMS accuracy:

```
τ_avg = 10 / f_min = 10 / 20 = 500 ms
C_AV = τ_avg / 8000 = 500m / 8k = 62.5 µF
```

**Select C_AV = 100 µF** (electrolytic, gives τ = 800 ms)

At each frequency:
```
f = 20 Hz:   cycles/τ = 20 × 0.8 = 16 cycles   (good)
f = 100 Hz:  cycles/τ = 100 × 0.8 = 80 cycles   (excellent)
f = 1 kHz:   cycles/τ = 1000 × 0.8 = 800 cycles (excellent)
f = 30 kHz:  cycles/τ = 30000 × 0.8 = 24000     (excellent)
```

### 6.4 RMS Ripple

The residual ripple on the DC output (at 2×f_osc) is approximately:

```
Ripple = V_rms / (4π × f × τ_avg)
```

At 20 Hz: Ripple = 0.2V / (4π × 20 × 0.8) = 0.2 / 201 = 1.0 mV (0.5%)
At 1 kHz: Ripple = 0.2V / (4π × 1000 × 0.8) = 20 µV (0.01%)

### 6.5 Settling Time

Time for AGC to settle after frequency change (5τ for 99.3%):

```
t_settle ≈ 5 × (τ_avg + τ_loop)
         = 5 × (800ms + 100ms)
         = 4.5 seconds
```

This is slow but acceptable for a precision oscillator. For faster settling at higher frequencies, C_AV could be switched (smaller cap at higher frequencies).

---

## 7. Power Supply & Headroom

### 7.1 Supply Voltage Selection

```
V_supply = ±15V
```

Reasons:
- LM4562 operates ±2.5V to ±17V (±15V is standard)
- AD636 operates ±2.5V to ±16.5V (±15V is within range)
- DAC7800 needs +5V logic supply (separate regulator)
- 1V RMS = 1.414V peak, well within ±13.5V output swing

### 7.2 Output Headroom

```
V_swing = ±(15 - 1.5) = ±13.5V  (LM4562 with ±15V supply)
V_peak_osc = 1.414V             (1V RMS)
Headroom = 13.5 - 1.414 = 12.1V (plenty of margin)
```

### 7.3 JFET Bias Headroom

J113 gate voltage range: 0V to -1.382V (Vto)
The AGC error signal must swing in this range.

### 7.4 Power Consumption

```
LM4562 (×2 packages, 4 sections): 2 × 5.2mA = 10.4 mA
AD636:                             0.8 mA
J113:                              negligible (gate leakage only)
DAC7800:                           2 mA (from 5V logic supply)
Biasing resistors:                 ~1 mA
────────────────────────────────────────
Total (±15V rail):                 ~13 mA
Total (5V logic):                  ~2 mA
```

---

## 8. ADuCM362 Digital Control Interface

### 8.1 Why ADuCM362?

The ADuCM362 is already used in the TIA/electrometer project. We have:
- Firmware templates in `~/Documents/LTspice/firmware/`
- CMSIS headers from CN0359 reference in `~/Documents/LTspice/cn0359/`
- ARM compiler (arm-none-eabi-gcc) in `~/Documents/LTspice/tools/`
- Proven SPI and UART drivers

The ADuCM362 can:
- Send 12-bit codes to DAC7800 via SPI0 (up to 16 MHz)
- Read the AD636 RMS output via its 24-bit sigma-delta ADC (high precision)
- Provide UART output for PC interface (frequency, amplitude, status)
- Run frequency sweep and calibration algorithms
- Optionally implement digital AGC (replacing analog AGC loop)

### 8.2 DAC7800 SPI Interface

```
ADuCM362 Pin     DAC7800 Pin    Function
────────────     ───────────    ────────
P1.4 (SPI0_CLK)  SCLK          Serial clock (up to 10 MHz)
P1.5 (SPI0_MOSI) SDI           Serial data in
P1.3 (GPIO)      CS_A          Chip select, DAC A
P1.2 (GPIO)      CS_B          Chip select, DAC B
```

SPI data format: 16 bits
```
Bit 15-14: Don't care
Bit 13:    /LDAC (0 = update output immediately)
Bit 12:    PD (0 = normal, 1 = power down)
Bit 11-0:  DAC code (D11-D0, MSB first)
```

### 8.3 Frequency Setting Code (ADuCM362 C)

```c
#include "ADuCM362.h"

#define RFB       10000.0f    // 10 kΩ internal feedback
#define CINT      470e-12f    // 470 pF integrator cap
#define FREQ_CONST (4096.0f * 2.0f * 3.14159265f * RFB * CINT)  // = 0.1211

// Calculate DAC code for desired frequency
uint16_t frequency_to_code(float freq_hz) {
    float code = freq_hz * FREQ_CONST;
    if (code < 1.0f) code = 1.0f;
    if (code > 4095.0f) code = 4095.0f;
    return (uint16_t)(code + 0.5f);  // round to nearest
}

// Send code to DAC7800 via SPI0
void dac7800_write(uint16_t code) {
    uint16_t spi_word = code & 0x0FFF;  // bits 11-0 = code, bit 13=0 (LDAC)

    pADI_GP1->GPCLR = (1 << 3);        // CS low
    pADI_SPI0->SPITX = (spi_word >> 8); // MSB first
    while (!(pADI_SPI0->SPISTA & 0x01)); // wait TX done
    pADI_SPI0->SPITX = (spi_word & 0xFF);
    while (!(pADI_SPI0->SPISTA & 0x01));
    pADI_GP1->GPSET = (1 << 3);        // CS high
}

// Example usage:
// dac7800_write(frequency_to_code(1000.0f));  // Set 1 kHz
// dac7800_write(frequency_to_code(10000.0f)); // Set 10 kHz
```

### 8.4 ADC Reading (RMS monitoring via sigma-delta ADC)

The ADuCM362 has a 24-bit sigma-delta ADC — far more precise than a 12-bit SAR.
AD636 output (0–200mV) can be read directly on AIN+ with internal PGA.

```c
// Read AD636 output via ADuCM362 ADC
// AD636 output: 0-200mV DC (= 0-1V RMS at oscillator)
// ADC: 24-bit, Vref = 1.2V internal, PGA gain = 4
// Range: ±300mV (1.2V / 4)
// Resolution: 1.2V / (4 × 2^23) = 35.8 nV per LSB

float read_rms_voltage(void) {
    // Single conversion on AIN4 (AD636 output)
    int32_t adc_raw = adc_read_channel(4);  // from adc.c template

    float v_adc = (float)adc_raw * 1.2f / (4.0f * 8388608.0f);  // PGA=4
    float v_rms_osc = v_adc * 5.0f;  // undo 1/5 attenuator
    return v_rms_osc;  // oscillator RMS in volts
}
```

### 8.5 UART Output Format

Reuse the TIA project format:
```
$OSC,<freq_hz>,<dac_code>,<rms_mV>,<thd_pct>,<ms>\r\n
```

Example: `$OSC,1000.0,121,1002.3,0.005,12345\r\n`

### 8.6 No Level Shifting Needed

The ADuCM362 runs at 3.3V but the DAC7800 accepts logic levels as low as 2.4V (VIH).
The ADuCM362 GPIO output high is ~3.3V, which exceeds 2.4V. No level shifting required
when the DAC7800 VDD = 5V (TTL-compatible inputs).

---

## 9. Noise Analysis

### 9.1 Op-Amp Noise

LM4562 voltage noise: e_n = 2.7 nV/√Hz
LM4562 current noise: i_n = 1.6 pA/√Hz

For the integrator with R_fb = 10 kΩ:
```
Voltage noise contribution: e_n = 2.7 nV/√Hz
Current noise × R: i_n × R_fb = 1.6 pA/√Hz × 10 kΩ = 16 nV/√Hz
Resistor thermal noise: e_R = √(4kTR) = √(4 × 1.38e-23 × 300 × 10k) = 12.9 nV/√Hz

Total per integrator: √(2.7² + 16² + 12.9²) = √(7.3 + 256 + 166) = √429 = 20.7 nV/√Hz
```

### 9.2 Output Noise at 1 kHz (BW = 10 Hz)

```
V_noise = 20.7 nV/√Hz × √(10 Hz) × Q_eff
```

For a well-regulated oscillator (AGC active), the effective Q at output is very high but noise is filtered by the AGC bandwidth. Expected output noise floor: < 1 mV RMS (> 60 dB SNR at 1V RMS output).

### 9.3 Phase Noise

At 1 kHz offset from carrier:
```
L(f) ≈ -10 × log10(kT × f₀ / (2 × Q² × P_carrier × f_offset²))
```

Precise calculation requires full simulation, but expected: < -80 dBc/Hz at 1 kHz offset for audio applications.

---

## 10. Complete Bill of Materials

### 10.1 Active Components

| Ref | Part | Package | Qty | Function |
|-----|------|---------|-----|----------|
| U1 | LM4562NA | SOIC-8 | 1 | Summing amp (A) + Integrator 1 (B) |
| U2 | LM4562NA | SOIC-8 | 1 | Integrator 2 (A) + AGC error amp (B) |
| U3 | DAC7800 | SOIC-16 | 1 | 12-bit MDAC (frequency control) |
| U4 | AD636JH | TO-100 / CDIP | 1 | RMS-to-DC converter |
| Q1 | J113 | TO-92 | 1 | N-ch JFET (AGC gain element) |
| U5 | ADuCM362 | LFCSP-48 | 1 | Digital controller (SPI + ADC) |

### 10.2 Passive Components

| Ref | Value | Type | Qty | Function |
|-----|-------|------|-----|----------|
| C1, C2 | 470 pF | C0G/NP0 ±2% | 2 | Integrator capacitors |
| C_AV | 100 µF | Electrolytic | 1 | AD636 averaging capacitor |
| C_loop | 1 µF | Film | 1 | AGC loop integrator |
| C_byp | 100 nF | X7R | 6 | Supply bypass (each IC) |
| C_bulk | 10 µF | Electrolytic | 2 | Supply bulk (±15V) |
| R1, R2 | 10 kΩ | 1% metal film | 2 | Summing amp input resistors |
| R_att1 | 40 kΩ | 1% | 1 | AD636 input attenuator |
| R_att2 | 10 kΩ | 1% | 1 | AD636 input attenuator |
| R_loop | 100 kΩ | 1% | 1 | AGC loop resistor |
| R_ref | Divider TBD | 1% | 2 | Reference voltage for AGC |

### 10.3 Power Supply

| Component | Specification |
|-----------|---------------|
| V+ | +15V regulated |
| V- | -15V regulated |
| V_logic | +5V regulated (for DAC7800) |
| V_esp | +3.3V (from ESP32 regulator) |

---

## Summary of Key Design Parameters

```
┌────────────────────────────────────────────────────────┐
│ OSCILLATOR PARAMETERS                                  │
├────────────────────────────────────────────────────────┤
│ Frequency range:     24.8 Hz — 33.8 kHz               │
│ Usable range:        24.8 Hz — 30 kHz                  │
│ Output amplitude:    1V RMS (1.414V peak)              │
│ Output impedance:    ~50 Ω (op-amp output)             │
│ DAC code range:      D = 3 to D = 3632                 │
│ Frequency per LSB:   8.26 Hz                           │
│ Integrator C:        470 pF C0G                        │
│ MDAC Rfb:            10 kΩ (internal)                  │
│ Supply voltage:      ±15V analog, +5V logic            │
│ AGC settling time:   ~4.5 seconds (worst case at 20Hz) │
│ AD636 averaging:     τ = 800 ms (C_AV = 100 µF)       │
│ AGC loop:            τ = 100 ms (R=100k, C=1µF)       │
│ Expected THD:        < 0.01% (AGC regulated)           │
│ Expected SNR:        > 60 dB                           │
└────────────────────────────────────────────────────────┘
```
