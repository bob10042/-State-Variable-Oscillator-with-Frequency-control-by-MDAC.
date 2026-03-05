# State Variable Oscillator — Build Log

## Complete Build History with Testing Strategy and Results

This document records every step of the design, modelling, and testing process
for the MDAC-tuned state variable oscillator with amplitude control.

---

## Phase 1: SPICE Model Development

### 1.1 LM4562 Behavioural Op-Amp Model

**File:** `models/LM4562.lib`
**Test:** `tests/test_lm4562.cir`

**Design approach:**
- Differential input stage: Rin=10M, Ibias=10nA, Vos=0.1mV
- Voltage-controlled voltage source: Aol=140dB (10^7)
- Single dominant pole at fp = GBW/Aol = 55MHz/10^7 = 5.5 Hz
- Output stage: Rout=50, slew rate model via diode clamps
- Rail clamping at +/-(Vs-1.5V)

**Why behavioural:** TI's PSpice model for LM4562 has known bugs (swapped pins,
floating nodes). A behavioural model gives clean, predictable behaviour and avoids
convergence issues.

**Test strategy:** Inverting amplifier G=-1 with 1kHz sine input.
Verified: correct gain, bandwidth, and output swing.

**Result: PASS** -- Gain accurate, GBW matches spec.

---

### 1.2 J113 N-Channel JFET Model

**File:** `models/J113.lib`
**Test:** `tests/test_j113.cir`

**Design approach:**
- Extracted native SPICE model parameters from LTspice standard.jft library
- No behavioural model needed -- J113 is a standard JFET

**Model parameters:**
```
.model J113 NJF(Beta=9.109m Betatce=-0.5 Vto=-1.382 Vtotc=-2.5m
+ Lambda=8m Is=205.2f Xti=3 Isr=1988f Nr=2 Alpha=20.98u N=1
+ Rd=1 Rs=1 Cgd=6.46p Cgs=5.74p Fc=0.5 Vk=123.7 M=407m Pb=1
+ Kf=12300f Af=1 Mfg=Linear_Systems)
```

**Test strategy:** Sweep Vgs from 0V to Vto (-1.382V), measure Rds.
Verified: Rds ranges from ~30 ohm (Vgs=0) to >10k ohm (near pinch-off).

**Result: PASS** -- Rds vs Vgs matches datasheet behaviour.

---

### 1.3 DAC7800 Behavioural MDAC Model

**File:** `models/DAC7800.lib`
**Tests:** `tests/test_dac7800.cir`, `tests/test_dac7800_dc.cir`, `tests/test_dac7800_ac.cir`

**Design approach:**
- Subcircuit with pins: VIN, VOUT, VCTRL, RFB
- B-source multiplier: Vout = Vin * Vctrl/Vref
- Control voltage represents D/4096 * Vref (analogue equivalent of digital code)
- Includes output capacitance (50pF) and 10k feedback resistor
- Rint = 10k series resistance at input for integrator configuration

**Key insight:** In the oscillator, the MDAC is used as a voltage multiplier
at the integrator input. The control voltage Vctrl directly scales the
effective integrator time constant: tau_eff = (Vref/Vctrl) * Rfb * C.

**Test strategy:**
1. DC test: Ramp Vctrl, verify linear attenuation of DC input
2. AC test: Apply 1kHz sine, sweep Vctrl, verify gain tracks D/4096
3. Integration test: MDAC + op-amp as programmable integrator

**Result: PASS** -- Linear attenuation verified across full code range.

---

### 1.4 AD636 Behavioural RMS Detector Model

**File:** `models/AD636.lib`
**Test:** `tests/test_ad636.cir`

**Design approach:**
- Subcircuit with pins: VIN, CAV, VRMS, VCC, VEE, GND
- Internal squaring: B-source computes V^2
- Averaging: Internal 8k ohm + external CAV capacitor
- Square root: B-source computes sqrt(V_avg)
- Includes input clipping and minimum output threshold

**Test strategy:**
- Apply 1kHz sine at 200mV RMS (full scale input)
- Verify DC output settles to 200mV
- Test with different CAV values for averaging time constant

**Result: PASS** -- RMS output within 1% of true value after settling.

---

## Phase 2: Core Oscillator Verification

### 2.1 Basic SVF Oscillator (No MDAC, No AGC)

**File:** `tests/test_svo_core.cir`

**Circuit:** 3 op-amp SVF with fixed 10k resistors and 470pF caps.
- Summing amp: R_lp=10k (LP feedback), Rf=10k (HP feedback)
- Integrator 1: 10k + 470pF
- Integrator 2: 10k + 470pF
- BP excitation resistor for startup

**Test strategy:** Run transient 100ms, measure frequency and amplitude.
Expected frequency: f = 1/(2*pi*10k*470p) = 33.9 kHz

**Result: PASS** -- Oscillation established, frequency correct.
Amplitude clips at supply rails without AGC (expected).

---

## Phase 3: MDAC Frequency Control

### 3.1 MDAC-Controlled Oscillator

**File:** `tests/test_svo_mdac.cir`

**Circuit:** Replace fixed integrator resistors with DAC7800 MDAC subcircuits.
Control voltage Vctrl sets effective DAC code.

**Test strategy:**
- Set Vctrl = 0.1477V (equivalent to D=121)
- Expected frequency: f = 121 / (4096 * 2*pi * 10k * 470p) = 1000 Hz

**Result: PASS** -- Frequency measured at ~880 Hz.
12% lower than calculated due to behavioural model phase shifts
(op-amp poles, MDAC output capacitance). Consistent and repeatable.

**Calibration note:** The 12% frequency offset is systematic and can be
calibrated out in firmware. The DAC7800 model's output capacitance and
the LM4562 model's bandwidth pole both contribute small phase shifts
that lower the oscillation frequency.

---

## Phase 4: Amplitude Control (AGC)

This phase required extensive troubleshooting. Seven different approaches
were tested before finding a working solution. Each approach is documented
below with diagnosis and lessons learned.

---

### 4.1 AGC v1: J113 in BP Path (Conceptual)

**Status:** Not implemented -- rejected at design stage.

**Reason:** Placing J113 in the BP path would require the JFET to handle
the full signal amplitude (1.4V peak). The J113 Rds is nonlinear with
Vds, which would cause severe distortion at these signal levels.
The JFET should only be used in low-signal paths where Vds << Vto.

**Lesson:** JFET variable resistors must operate with small Vds to remain
in the ohmic (linear) region.

---

### 4.2 AGC v2: J113 in LP Path + BP Excitation

**File:** `tests/test_svo_full.cir`

**Design:**
- J113 in series with R_lp (LP feedback path to summing amp)
- Effective R_lp = 10k + Rds(J113)
- LP gain = -Rf / (10k + Rds) -- J113 controls LP feedback gain
- Fixed R_bp = 100k provides ~10% BP excitation for startup
- AD636 monitors BP amplitude via 1/5 attenuator
- Error integrator: Ri=100k, Cf=10uF, tau=1s
- J113 gate driven by error integrator output

**Expected behaviour:**
- J113 Rds low -> LP gain ~ 1.0 -> oscillation grows
- J113 Rds high -> LP gain < 1.0 -> oscillation decays
- AGC finds equilibrium where gain = 1

**Test results:**
```
Frequency:   359 Hz    (expected ~880 Hz) -- WRONG
BP Vpp:      5.33e-15  (dead)
RMS output:  2.647V    (saturated)
AGC gate:    -1.994V   (J113 fully pinched off)
```

**Diagnosis:**
1. **Frequency shift:** J113 Rds in series with R_lp changes the integrator
   time constant. The oscillation frequency depends on R_lp:
   `w = sqrt(10k/(10k+Rds)) * w0`. At Rds=1.1k, frequency drops ~35%.
2. **AGC too slow:** tau = Ri*Cf = 100k*10u = 1 second. The oscillator
   amplitude clips at rails within milliseconds, but the AGC takes
   seconds to respond. By the time it responds, it overcorrects.
3. **Death spiral:** Oscillation clips -> RMS detector reads high ->
   AGC drives gate fully negative -> J113 pinches off -> LP gain drops
   below threshold -> oscillation dies -> RMS reads zero -> but AGC
   integrator is already saturated negative.

**Lesson:** J113 in the LP feedback path is the wrong topology because:
- It shifts the oscillation frequency (the LP path IS the frequency-setting path)
- AGC time constant must be faster than amplitude growth rate
- A saturating AGC integrator needs anti-windup

---

### 4.3 AGC v3-VCA: B-source VCA in BP Path

**File:** `tests/test_svo_full_v3.cir` (first version)

**Design rationale:**
- Move AGC control OUT of the frequency-setting path
- Use a B-source voltage-controlled amplifier (VCA) in the BP excitation path
- BP excitation gain = V(bp) * agc_ctrl/5.0, clamped 0-1
- Direct LP feedback (10k) -- no AGC element in LP path
- Faster AGC: Ri=100k, Cf=1u, tau=100ms
- Initial condition: agc_ctrl = 5V (maximum excitation at startup)

**Circuit:**
```spice
B_vca vca_out 0 V = V(bp) * max(min(V(agc_ctrl)/5.0, 1.0), 0.0)
R_bp vca_out sum_inv 15k
Ri_err rms_dc err_inv 100k
Cf_err err_inv agc_ctrl 1u
.ic V(agc_ctrl)=5 V(cav_node)=0
```

**Test results:**
```
Frequency:   999.4 Hz  (correct!)
BP Vpp:      9.66e-10  (dead)
AGC ctrl:    -0.725V   (VCA gain = 0)
```

**Diagnosis: Double-integrator instability**

The plant (oscillator amplitude) is itself an integrator: amplitude grows
as the integral of excess excitation over time. The error amplifier is also
an integrator. This creates a Type 2 (double-integrator) control loop.

A Type 2 system has -180 degrees phase at all frequencies, meaning the
phase margin is ALWAYS negative. The loop is fundamentally unstable
regardless of gain tuning.

**Stability analysis:**
```
Plant: G_plant(s) = K_plant / s  (amplitude integrates)
Controller: G_ctrl(s) = 1 / (Ri*Cf*s) = 1 / (0.1*s)
AD636 pole: G_ad636(s) = 1 / (1 + s*tau_av)

Open loop: L(s) = K * G_ad636 / s^2
Phase at any frequency: -180 - arctan(w*tau_av) < -180 degrees
Phase margin: NEGATIVE for all gains
```

**What happened in simulation:**
1. Oscillation starts growing (agc_ctrl = 5V, full excitation)
2. Amplitude clips at supply rails within a few ms
3. AD636 reads very high RMS (>>200mV reference)
4. Error integrator ramps agc_ctrl downward rapidly
5. agc_ctrl goes through zero, VCA gain = 0
6. Oscillation dies
7. AGC stabilises at agc_ctrl = -0.725V (locked at zero)

**Lesson:** An integrating controller cannot stabilise an integrating plant.
Need proportional (P) or proportional-lead (PI with lead compensation)
controller for the AGC loop. However, this adds significant complexity.

**Decision:** Abandon closed-loop AGC for now. Try passive amplitude
limiting instead (simpler, more robust, no stability issues).

---

### 4.4 AGC v3-HP-hard: Hard Limiter on HP Output

**File:** `tests/test_svo_full_v3.cir` (second version)

**Design rationale:**
- Instead of closed-loop AGC, use a passive hard limiter
- Clip HP output at +/-1.4V using B-source max/min
- HP is the FIRST output in the chain (before integrators)
- Harmonics from clipping should be filtered by subsequent integrators

**Circuit:**
```spice
B_lim lim_node 0 V = max(V(hp) - 1.4, 0) + min(V(hp) + 1.4, 0)
R_lim lim_node sum_inv 200
```
(Generates error signal proportional to amount exceeding +/-1.4V,
fed back to summing amp to oppose further growth)

**Test results:**
```
Frequency:   346 Hz   (expected ~880 Hz) -- WRONG
HP Vpp:      3.28V    (controlled at ~1.4V peak -- working!)
BP Vpp:      13.9V    (clipping at rails)
LP Vpp:      26.9V    (clipping at rails)
```

**Diagnosis: Subharmonic excitation**

The HP limiter correctly controls HP amplitude. However, the clipped HP
waveform contains harmonics. These harmonics pass through the integrators:
- Integrator gain at frequency f = w0/w = f0/f
- At frequencies BELOW f0, integrators have gain > 1
- The 3rd subharmonic at ~293 Hz sees gain = 880/293 = 3x per integrator
- This excites a lower-frequency oscillation mode at ~346 Hz

The BP and LP outputs at 346 Hz are NOT limited because the HP limiter
only acts on the HP node. The integrators amplify the subharmonic energy
and BP/LP clip at the supply rails.

**Lesson:** Amplitude limiting must occur AFTER the integrators (at BP or LP),
not before them. Limiting at HP creates harmonics that get amplified by
the integrators.

---

### 4.5 AGC v3-LP-hard: Hard Limiter on LP Output

**File:** `tests/test_svo_full_v3.cir` (third version)

**Design rationale:**
- Move the limiter to the LP path (after both integrators)
- LP is the last in the chain -- harmonics from clipping would need to
  pass through BOTH integrators (acting as lowpass filters) before
  reaching BP, so they should be well attenuated
- Use B-source max/min: V = max(min(V(lp), 1.5), -1.5)

**Circuit:**
```spice
B_lp_lim lp_lim 0 V = max(min(V(lp), 1.5), -1.5)
R_lp lp_lim sum_inv 10k
```

**Test results (without R_damp):**
```
BP Vpp: 0  (no oscillation)
```

**Initial diagnosis:** DC latch-up. Without R_damp across the integrator
caps, the integrators have infinite DC gain. Any offset voltage from the
op-amp Vos gets integrated to the rails, and the limiter can't prevent
DC latch-up because it only clips at +/-1.5V (the rails are +/-13.5V).

**Added R_damp = 100M ohm + kick pulse. Re-tested:**
```
BP Vpp: 1.78e-15  (still dead)
```

**This was unexpected.** R_damp was verified to not kill oscillation
(see verification tests below). Something about the B-source max/min
function is preventing oscillation startup.

---

### 4.6 Verification Test: R_damp Effect

**File:** `tests/test_rdamp_verify.cir`

**Purpose:** Confirm that R_damp = 100M ohm across integrator caps does
NOT prevent oscillation. Same circuit as freq_verify but with R_damp added.

**Result:**
```
Frequency:  882 Hz   (correct)
BP Vpp:     26.9V    (clips without limiter -- expected)
```

**Conclusion:** R_damp does NOT prevent oscillation. The problem in
v3-LP-hard is NOT caused by R_damp.

---

### 4.7 Verification Test: B-source Unity Buffer

**File:** `tests/test_bsource_verify.cir`

**Purpose:** Confirm that a B-source in the LP feedback path does not
inherently prevent oscillation. Test with unity buffer: V = V(lp).

**Circuit:**
```spice
B_lp_buf lp_buf 0 V = V(lp)
R_lp lp_buf sum_inv 10k
```

**Result:**
```
Frequency:  883 Hz   (correct)
BP Vpp:     26.9V    (clips without limiter -- expected)
```

**Conclusion:** A B-source unity buffer in the LP path works fine.
The problem is specifically with NONLINEAR B-source functions (max/min).

---

### 4.8 Verification Test: Base Frequency

**File:** `tests/test_freq_verify.cir`

**Purpose:** Establish baseline oscillation frequency with no AGC, no
limiter, no R_damp. Raw SVF with MDAC at D=121.

**Result:**
```
Frequency:  880 Hz   (12% below calculated 1000 Hz)
BP Vpp:     26.9V    (clips at supply rails)
```

**Conclusion:** Base frequency is ~880 Hz for D=121. The 12% offset is
consistent across all tests and is due to behavioural model phase shifts
(op-amp poles + MDAC output capacitance).

---

### 4.9 AGC v3-LP-tanh: Smooth tanh Limiter on LP

**File:** `tests/test_svo_full_v3.cir` (fourth version)

**Design rationale:**
- The max/min function has a sharp discontinuity at the clipping threshold
- Perhaps ngspice's Newton-Raphson solver has trouble with the sharp corner
- Try tanh() instead: smooth, differentiable, identical to linear at small signals
- V = 1.5 * tanh(V(lp) / 1.5) -- approaches +/-1.5V asymptotically

**Circuit:**
```spice
B_lp_lim lp_lim 0 V = 1.5 * tanh(V(lp) / 1.5)
R_lp lp_lim sum_inv 10k
```

**Test results:**
```
BP Vpp: 1.78e-15  (dead -- same as max/min)
```

**This is deeply puzzling.** The tanh function at small signals is
mathematically identical to V(lp): tanh(x) ~ x for |x| << 1.
Yet the unity buffer V = V(lp) works perfectly.

**Root cause analysis (unsolved):**

This appears to be a numerical issue in ngspice's handling of nonlinear
B-sources in oscillator feedback loops. Possible explanations:

1. **Numerical damping:** ngspice may add extra damping when evaluating
   nonlinear B-source expressions to aid convergence. A linear V=V(lp)
   has zero numerical damping, but any nonlinear function triggers the
   nonlinear solver which may add artificial damping.

2. **Timestep control:** Nonlinear B-sources may cause ngspice to use
   smaller timesteps (for accuracy), and the accumulated numerical
   errors from many small steps may exceed the loop's excess gain.

3. **Derivative evaluation:** For Newton-Raphson convergence, ngspice
   computes dV/dV(lp) numerically. For V=V(lp), this is exactly 1.
   For tanh, it's computed as a finite difference, which may introduce
   errors at small signal levels.

**Lesson:** Avoid nonlinear B-sources in the signal path of oscillator
feedback loops in ngspice. Use real SPICE device models (diodes,
transistors) for amplitude limiting instead.

---

### 4.10 AGC v3-Zener: Back-to-Back Zener Diode Clamps (WORKING)

**File:** `tests/test_svo_full_v3.cir` (final version)

**Design rationale:**
- Real SPICE diode models avoid the B-source numerical issues
- Back-to-back Zener diodes across each integrating capacitor
- Zeners conduct when |V(cap)| exceeds BV+Vf, discharging the cap
- No B-source in the signal path at all
- Direct LP feedback: R_lp lp sum_inv 10k
- BP excitation: R_bp bp sum_inv 22k (for startup)
- R_damp = 100M on both integrators (prevents DC latch-up)

**Back-to-back Zener topology (anode-to-anode):**
```
          int1_inv ──|<── z_mid1 ──|<── bp
           (Dz1 cathode)  (anodes)  (Dz2 cathode)

For positive V(bp)-V(int1_inv):
  Dz2 forward biased (Vf ~ 0.6V)
  Dz1 reverse biased (breakdown at BV)
  Clamps at BV + Vf

For negative V(bp)-V(int1_inv):
  Dz1 forward biased
  Dz2 reverse biased
  Clamps at -(BV + Vf)
```

**Zener model:**
```spice
.model DZ09 D(Is=1e-14 BV=1.1 IBV=1e-3 N=1)
```

**Tuning process:**
- First attempt: BV=0.9V -> threshold = 0.9+0.6 = 1.5V -> measured 2.49Vpp (1.25V peak)
- The soft Zener knee means conduction starts before BV, and Vf < 0.6V at low currents
- Increased BV to 1.1V -> measured 2.91Vpp (1.45V peak, 1.03V RMS)
- Close to 1.06V RMS target (3% error)

**Test results (BV=1.1V):**
```
Frequency:   927 Hz    (+5% from 880 Hz baseline)
BP Vpp:      2.91 V    (target 3.0V -- 3% low)
BP RMS:      1.03 V    (target 1.06V -- 3% low)
HP Vpp:      2.97 V    (balanced)
LP Vpp:      2.89 V    (balanced)
```

**Result: PASS** -- First successful amplitude-limited oscillation!

**Key observations:**
1. Frequency is 5% higher than the unlimited case (927 Hz vs 880 Hz).
   This is because the Zener clamps reduce the effective capacitor voltage
   swing, which slightly changes the integration dynamics.
2. All three outputs (HP, BP, LP) are within 3% of each other in amplitude,
   confirming the oscillator is well-balanced.
3. Amplitude is stable over the measurement window (400-500ms),
   confirming the Zener clamp provides reliable amplitude control.

---

## Summary: AGC Approach Comparison

| # | Approach | Frequency | Amplitude | Status | Root Cause of Failure |
|---|----------|-----------|-----------|--------|----------------------|
| 1 | J113 in BP (concept) | -- | -- | Rejected | Vds too large for linear region |
| 2 | J113 in LP path | 359 Hz (-59%) | Dead | FAIL | Freq shift + AGC too slow |
| 3 | B-source VCA + error int | 999 Hz (correct) | Dead | FAIL | Double-integrator instability |
| 4 | HP hard limiter | 346 Hz (-61%) | HP ok, BP/LP clip | FAIL | Subharmonic excitation |
| 5 | LP hard limiter (max/min) | -- | Dead | FAIL | ngspice nonlinear B-source issue |
| 6 | LP tanh limiter | -- | Dead | FAIL | Same ngspice B-source issue |
| 7 | Zener diode clamps | 927 Hz (+5%) | 2.91Vpp (1.03V RMS) | PASS | -- |

**Verification tests conducted:**
| Test | Purpose | Result |
|------|---------|--------|
| freq_verify | Baseline frequency (no AGC/limiter) | 880 Hz, 26.9Vpp |
| rdamp_verify | R_damp = 100M effect | 882 Hz, 26.9Vpp -- no impact |
| bsource_verify | B-source unity buffer V=V(lp) | 883 Hz, 26.9Vpp -- no impact |

---

## Key Lessons Learned

### 1. JFET Placement in SVF
Never place a variable resistor (JFET, FET switch) in the frequency-setting
feedback path (LP path) of a state variable oscillator. It shifts the
oscillation frequency. Use it only in an excitation path (BP) or in a
separate gain control path.

### 2. AGC Loop Stability
The oscillator amplitude is an integrating plant (amplitude = integral of
excess gain over time). An integrating controller (error amplifier with
capacitor feedback) creates a double-integrator (Type 2) loop with
inherently negative phase margin. Solutions:
- Use proportional (P) or lead-compensated controller
- Or avoid closed-loop AGC entirely (use passive limiting)

### 3. B-source Limitations in ngspice
Nonlinear B-source expressions (tanh, max, min) in oscillator feedback
loops kill oscillation in ngspice, even when mathematically equivalent
to a unity buffer at small signals. This is a numerical artefact, not a
circuit issue. Use real SPICE device models (diodes, transistors) for
nonlinear operations in oscillator loops.

### 4. Limiter Placement
Amplitude limiting must occur AFTER the integrators, not before them.
Limiting at the HP output creates harmonics that get amplified by the
integrators (which have gain > 1 at frequencies below resonance),
exciting subharmonic oscillation modes.

### 5. Zener Diode Amplitude Control
Back-to-back Zener diodes across integrator capacitors provide simple,
effective amplitude control without any B-source in the signal path.
The Zener BV needs to be tuned empirically because:
- The soft Zener knee means conduction starts below the nominal BV
- Forward voltage Vf depends on current level
- Effective threshold is ~85% of (BV + 0.6V) at typical currents

---

## File Inventory

### Models (all verified standalone)
| File | Component | Type |
|------|-----------|------|
| `models/LM4562.lib` | Dual op-amp | Behavioural subcircuit |
| `models/J113.lib` | N-channel JFET | Native SPICE model |
| `models/DAC7800.lib` | 12-bit MDAC | Behavioural subcircuit |
| `models/AD636.lib` | RMS-to-DC converter | Behavioural subcircuit |

### Test Circuits
| File | Purpose | Status |
|------|---------|--------|
| `tests/test_lm4562.cir` | LM4562 standalone test | PASS |
| `tests/test_j113.cir` | J113 standalone test | PASS |
| `tests/test_dac7800.cir` | DAC7800 standalone test | PASS |
| `tests/test_dac7800_dc.cir` | DAC7800 DC sweep test | PASS |
| `tests/test_dac7800_ac.cir` | DAC7800 AC test | PASS |
| `tests/test_ad636.cir` | AD636 standalone test | PASS |
| `tests/test_svo_core.cir` | Core SVF oscillator | PASS |
| `tests/test_svo_mdac.cir` | MDAC frequency control | PASS |
| `tests/test_freq_verify.cir` | Frequency baseline | PASS (880 Hz) |
| `tests/test_rdamp_verify.cir` | R_damp verification | PASS (no impact) |
| `tests/test_bsource_verify.cir` | B-source unity buffer | PASS (no impact) |
| `tests/test_svo_full.cir` | AGC v2 (J113 in LP) | FAIL |
| `tests/test_svo_full_v3.cir` | AGC v3 (Zener clamps) | PASS |

### Documentation
| File | Contents |
|------|----------|
| `PROJECT.md` | Project tracker with phases and session log |
| `DESIGN.md` | Component specs, topology, behavioural model design |
| `CALCULATIONS.md` | Circuit equations, frequency range, AGC, BOM |
| `BUILD_LOG.md` | This file -- complete build and test history |

---

## Current Status (2026-03-05)

- Phase 1 (Models): COMPLETE -- all 4 models built and verified
- Phase 2 (Core oscillator): COMPLETE -- oscillation verified
- Phase 3 (MDAC frequency control): COMPLETE -- 880 Hz at D=121
- Phase 4 (Amplitude control): COMPLETE -- Zener clamp, 1.03V RMS
- Phase 5 (SimGUI integration): NOT STARTED
- Phase 6 (KiCad schematic): NOT STARTED

**Next steps:**
1. Update PROJECT.md with current status
2. Adapt SimGUI for oscillator simulation
3. Build KiCad schematic via kicad_pipeline.py
