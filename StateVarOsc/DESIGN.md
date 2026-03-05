# State Variable Oscillator — Design Document

## 1. Component Specifications (from datasheets)

### 1.1 LM4562 — Dual High-Performance Audio Op-Amp (Texas Instruments)

| Parameter | Min | Typ | Max | Unit |
|-----------|-----|-----|-----|------|
| Supply voltage (±Vs) | ±2.5 | — | ±17 | V |
| Open-loop gain (Aol) | — | 140 | — | dB |
| Gain-bandwidth product | — | 55 | — | MHz |
| Slew rate | — | 20 | — | V/µs |
| Input offset voltage | — | 0.1 | 4 | mV |
| Input bias current | — | 10 | 72 | nA |
| Input noise voltage | — | 2.7 | — | nV/√Hz |
| Input noise current | — | 1.6 | — | pA/√Hz |
| CMRR | — | 120 | — | dB |
| PSRR | — | 120 | — | dB |
| Output voltage swing (±15V) | — | ±13.5 | — | V |
| Output current | — | ±26 | — | mA |
| Input resistance | — | 10 | — | MΩ |

**Notes:**
- Dual package (2 op-amps per chip)
- Unity-gain stable
- Used for: summing amplifier + two integrators (3 of 4 sections used)
- PSpice model from TI has known bugs (swapped pins, floating nodes)
- LME49710 is electrically identical (single version)

### 1.2 DAC7800 — 12-bit Dual Multiplying DAC (Texas Instruments)

| Parameter | Min | Typ | Max | Unit |
|-----------|-----|-----|-----|------|
| Resolution | — | 12 | — | bits |
| INL | — | ±0.5 | ±1 | LSB |
| DNL | — | ±0.5 | ±1 | LSB |
| Reference voltage | -10 | — | +10 | V |
| Settling time (0.01%) | — | 1 | — | µs |
| Output capacitance | 30 | — | 70 | pF |
| Supply voltage | — | +5 | — | V |
| R-2R ladder R value | — | ~10 | — | kΩ |
| Feedback resistor (Rfb) | — | ~10 | — | kΩ |
| Serial clock rate | — | 10 | — | MHz |

**MDAC operation:**
- Voltage mode: Vout = Vref × D/4096 (D = digital code, 0–4095)
- As variable attenuator: gain = D/4096
- In our oscillator: controls integrator time constant
- Effective resistance: Reff = Rfb × 4096/D
- At D=1: Reff = 10k × 4096 = 41 MΩ (lowest frequency)
- At D=4095: Reff ≈ 10 kΩ (highest frequency)

### 1.3 AD636 — Low-Level True RMS-to-DC Converter (Analog Devices)

| Parameter | Min | Typ | Max | Unit |
|-----------|-----|-----|-----|------|
| Input signal range | 0 | — | 200 | mV rms |
| Extended range (ext atten) | — | — | 7 | V rms |
| Accuracy (10mV–200mV) | — | ±1mV ±0.5% | — | — |
| Bandwidth (-3dB, 200mV) | — | 1 | — | MHz |
| Bandwidth (-3dB, 1mV) | — | 14 | — | kHz |
| Supply voltage (±Vs) | ±2.5 | — | ±16.5 | V |
| Supply current | — | 800 | — | µA |
| Averaging time const | — | 8kΩ × CAV | — | s |
| Output impedance | — | ~1 | — | Ω |
| Crest factor (for 1% err) | — | 3 | — | — |

**RMS computation:**
- Vrms = sqrt(1/T × ∫₀ᵀ V²(t) dt)
- Internal 8kΩ resistor with external CAV sets averaging
- For 20Hz operation: CAV ≥ 100µF (τ = 800ms, 16 cycles at 20Hz)
- For 30kHz: CAV = 1µF is fine (τ = 8ms, 240 cycles)
- Compromise: CAV = 10µF (τ = 80ms, good for >50Hz)
- Used for AGC: output compared to 1V reference, error drives J113

### 1.4 J113 — N-Channel JFET (Linear Systems / ON Semi)

| Parameter | Min | Typ | Max | Unit |
|-----------|-----|-----|-----|------|
| Pinch-off voltage (Vp/Vto) | -0.5 | -1.4 | -3 | V |
| Idss | — | ~30 | — | mA |
| Rds(on) at Vgs=0 | — | ~30 | — | Ω |
| Rds range (Vgs: 0 to Vp) | 30 | — | >10k | Ω |
| Gate-source cap (Cgs) | — | 5.7 | — | pF |
| Gate-drain cap (Cgd) | — | 6.5 | — | pF |

**SPICE model (from standard.jft — already in LTspice library):**
```
.model J113 NJF(Beta=9.109m Betatce=-0.5 Vto=-1.382 Vtotc=-2.5m
+ Lambda=8m Is=205.2f Xti=3 Isr=1988f Nr=2 Alpha=20.98u N=1
+ Rd=1 Rs=1 Cgd=6.46p Cgs=5.74p Fc=0.5 Vk=123.7 M=407m Pb=1
+ Kf=12300f Af=1 Mfg=Linear_Systems)
```

**AGC usage:**
- Drain-source used as voltage-controlled resistor
- Vgs controls Rds: Vgs=0 → ~30Ω, Vgs→Vp → very high
- Operates in linear (triode) region with small Vds
- AD636 output compared to setpoint → error → J113 gate

---

## 2. Circuit Topology

### 2.1 State Variable Filter / Oscillator

The classic SVF uses three op-amps:
1. **Summing amplifier (U1a)**: combines HP, LP, and feedback
2. **Integrator 1 (U1b)**: HP → BP (bandpass)
3. **Integrator 2 (U2a)**: BP → LP (lowpass)

For oscillation, the Q is set to infinity (positive feedback = negative feedback).
Three simultaneous outputs: HP (highpass), BP (bandpass = sine), LP (lowpass).

### 2.2 Frequency Control via MDAC

Each integrator has: Vout = -1/(R×C) × ∫Vin dt

Replace R with MDAC:
- MDAC acts as multiplying attenuator: gain = D/4096
- Effective time constant: τ = (4096/D) × Rfb × C
- Oscillation frequency: f = D / (4096 × 2π × Rfb × C)

Choose Rfb = 10kΩ (internal to DAC7800):
- For f=20Hz: D = 20 × 4096 × 2π × 10k × C → need C value
- For f=30kHz: D = 30k × 4096 × 2π × 10k × C

With C = 2.2nF:
- f = D / (4096 × 2π × 10k × 2.2n) = D / (0.5655)
- D=12 → f ≈ 21 Hz
- D=4095 → f ≈ 7238 Hz — too low!

With C = 470pF:
- f = D / (4096 × 2π × 10k × 470p) = D / (0.1211)
- D=3 → f ≈ 25 Hz
- D=3632 → f ≈ 30,000 Hz ✓

**Selected: C = 470pF** → D range ~3 to ~3632 for 20Hz–30kHz.

### 2.3 AGC Loop

1. AD636 monitors BP output (sine) RMS level
2. Compared to 1V DC reference via error amplifier
3. Error signal drives J113 gate
4. J113 Rds controls feedback attenuation in summing amp
5. Loop stabilises output at 1V RMS

AGC time constant must be:
- Fast enough: settle within a few cycles at lowest frequency (20Hz → ~200ms)
- Slow enough: not distort the waveform (no amplitude modulation at signal freq)
- CAV = 10µF → τ = 80ms is a good starting point

---

## 3. Behavioural Model Design

### 3.1 LM4562 Behavioural Op-Amp

Modelled as:
- Differential input stage: Rin=10MΩ, Ibias=10nA, Vos=0.1mV
- Voltage-controlled voltage source: Aol=140dB (10^7)
- Single dominant pole: fp = GBW/Aol = 55MHz/10^7 = 5.5 Hz
- Output stage: Rout=50Ω, slew rate limiting via diode clamps
- Rail clamping: output limited to ±(Vs-1.5V)

### 3.2 DAC7800 Behavioural MDAC

Modelled as:
- Voltage multiplier: Vout = Vin × Vctrl/Vref
- Using B-source (behavioural source)
- Control voltage represents D/4096 × Vref
- Includes output capacitance (50pF) and resistance

For simulation simplicity:
- Use .param DAC_CODE to set the digital code
- Internal calculation: gain = DAC_CODE/4096
- Applied as resistor value or voltage multiplier

### 3.3 AD636 Behavioural RMS Detector

Modelled as:
- Square the input: V² = Vin × Vin
- Average with RC: V²_avg via 8kΩ + external CAV
- Square root: Vrms = sqrt(V²_avg)
- Using B-sources for nonlinear operations
- External CAV pin for user-selected averaging capacitor

### 3.4 J113 JFET

Native SPICE model — no behavioural needed. Direct from standard.jft.

---

## 4. Simulation Plan

### 4.1 Phase 1: Individual Model Tests
1. LM4562: inverting amp G=-1, check gain and bandwidth
2. DAC7800: ramp Vctrl, verify linear attenuation
3. AD636: apply 1kHz sine, verify DC output matches RMS
4. J113: sweep Vgs, plot Rds

### 4.2 Phase 2: Core Oscillator
1. Fixed-frequency SVF oscillator (no MDAC, no AGC)
2. Verify oscillation startup
3. Measure frequency, amplitude, THD

### 4.3 Phase 3: MDAC Integration
1. Replace fixed R with MDAC model
2. Sweep DAC codes, measure frequency vs code
3. Verify linearity

### 4.4 Phase 4: AGC Integration
1. Add AD636 + J113 AGC loop
2. Verify 1V RMS lock across frequency range
3. Measure settling time and amplitude flatness
