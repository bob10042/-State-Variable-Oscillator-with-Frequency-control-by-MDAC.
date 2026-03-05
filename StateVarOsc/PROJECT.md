# State Variable Oscillator — Project Tracker
## MDAC-Tuned, AGC-Stabilised, 20Hz-30kHz

---

## Objective

Design and simulate a state variable oscillator with:
- **Digitally-controlled frequency** via DAC7800 MDAC
- **Amplitude control** using Zener diode clamps across integrator caps
- **Output:** ~1V RMS sine, 20Hz-30kHz
- **Simultaneous outputs:** HP (cosine), BP (sine), LP (-cosine)

Built using **CircuitForge** (kicad_pipeline.py + SimGUI) -- same workflow as the TIA/electrometer project.

---

## Block Diagram

```
                    +---------------+
  DAC7800 --------->|  MDAC x2      | (sets integrator time constant)
  (12-bit)          +-------+-------+
                            |
         +------------------+------------------+
         |                  |                  |
    +----+----+        +----+----+        +----+----+
    | Summing  |------->| Integ 1 |------->| Integ 2 |
    |  Amp     |        | (LM4562)|        | (LM4562)|
    | (LM4562) |        +----+----+        +----+----+
    +----+----+              |                  |
         |              Zener clamp         Zener clamp
         |              (BV=1.1V)           (BV=1.1V)
         |                  |                  |
         +<----- BP (R_bp=22k) -----+         |
         +<----- LP (R_lp=10k) ----------------+
         +<----- HP (Rf=10k) --+
                                |
                             V(hp)
```

---

## Components

| Part     | Function              | SPICE Model Status         |
|----------|-----------------------|---------------------------|
| DAC7800  | 12-bit MDAC (freq)    | DONE -- behavioural subcircuit |
| LM4562   | Dual low-noise op-amp | DONE -- behavioural subcircuit |
| AD636    | RMS-to-DC converter   | DONE -- behavioural subcircuit (for future AGC) |
| J113     | N-ch JFET (AGC)       | DONE -- native SPICE model |

All models located in `StateVarOsc/models/` and verified standalone.

---

## Design Equations

### Oscillation Frequency
```
f_osc = D / (4096 * 2*pi * Rfb * Cint)
      = D / 0.1211                        (with Rfb=10k, Cint=470pF)
```

### Frequency Range (C = 470pF)
```
D = 3:     f = 24.8 Hz
D = 121:   f = 880 Hz (measured, 12% below calculated 1000 Hz)
D = 3632:  f = 30.0 kHz
```

### Amplitude Control
Zener diode clamps across integrator capacitors:
- Back-to-back Zeners (anode-to-anode), BV=1.1V
- Threshold: BV + Vf ~ 1.45V peak
- Measured: 2.91 Vpp = 1.03V RMS (target: 1.06V, 3% error)

---

## Phases

### Phase 1: SPICE Models [COMPLETE]
- [x] Build LM4562 behavioural op-amp model
- [x] Build DAC7800 behavioural MDAC model
- [x] Extract J113 JFET model from standard.jft
- [x] Build AD636 behavioural RMS detector model
- [x] Test each model standalone in ngspice

### Phase 2: Core Oscillator Netlist [COMPLETE]
- [x] Write basic SVF oscillator (3 op-amp, fixed R, 470pF caps)
- [x] Verify oscillation startup and frequency
- [x] Confirm HP/BP/LP outputs

### Phase 3: MDAC Frequency Control [COMPLETE]
- [x] Integrate DAC7800 model into both integrators
- [x] Verify frequency at D=121: measured 880 Hz
- [x] Confirm MDAC does not prevent oscillation

### Phase 4: Amplitude Control [COMPLETE]
- [x] v2: J113 in LP path -- FAILED (freq shift, AGC too slow)
- [x] v3-VCA: B-source VCA + error integrator -- FAILED (double-integrator instability)
- [x] v3-HP-hard: max/min on HP -- FAILED (subharmonic excitation, freq shifted to 346 Hz)
- [x] v3-LP-hard: max/min on LP -- FAILED (ngspice nonlinear B-source kills oscillation)
- [x] v3-LP-tanh: tanh on LP -- FAILED (same B-source issue)
- [x] Verification tests: freq_verify, rdamp_verify, bsource_verify -- all PASS
- [x] v3-Zener: Zener diode clamps (BV=1.1V) -- **PASS: 927 Hz, 2.91Vpp, 1.03V RMS**

### Phase 5: SimGUI Integration [NOT STARTED]
- [ ] Adapt SimGUI for oscillator sim (new result parser for freq/amplitude/THD)
- [ ] Define sweep ranges (frequency steps or DAC codes)
- [ ] Add oscillator result display
- [ ] "Run All" loop: sweep across frequency range
- [ ] Plot: frequency response, amplitude flatness

### Phase 6: KiCad Schematic [NOT STARTED]
- [ ] Add oscillator schematic builder to kicad_pipeline.py
- [ ] Component placement: 3 op-amp sections + 2x MDAC + Zener AGC
- [ ] Verification pass
- [ ] Scale and export

---

## Verified Test Results

### Model Tests (Phase 1)
| Test | Result |
|------|--------|
| test_lm4562.cir | PASS -- gain and bandwidth correct |
| test_j113.cir | PASS -- Rds vs Vgs matches datasheet |
| test_dac7800.cir | PASS -- linear attenuation verified |
| test_dac7800_dc.cir | PASS -- DC sweep |
| test_dac7800_ac.cir | PASS -- AC response |
| test_ad636.cir | PASS -- RMS output within 1% |

### Oscillator Tests (Phases 2-4)
| Test | Frequency | BP Vpp | Status |
|------|-----------|--------|--------|
| test_svo_core.cir | Correct | Clips (no AGC) | PASS |
| test_svo_mdac.cir | 880 Hz | Clips (no AGC) | PASS |
| test_freq_verify.cir | 880 Hz | 26.9V (clips) | PASS (baseline) |
| test_rdamp_verify.cir | 882 Hz | 26.9V | PASS (R_damp safe) |
| test_bsource_verify.cir | 883 Hz | 26.9V | PASS (B-source ok) |
| test_svo_full.cir (v2) | 359 Hz | Dead | FAIL |
| test_svo_full_v3.cir (Zener) | 927 Hz | 2.91V | **PASS** |

---

## File Locations

| Item | Path |
|------|------|
| Project folder | `~/Documents/LTspice/StateVarOsc/` |
| Models | `StateVarOsc/models/` (LM4562, J113, DAC7800, AD636) |
| Tests | `StateVarOsc/tests/` (13 test circuits) |
| Design doc | `StateVarOsc/DESIGN.md` |
| Calculations | `StateVarOsc/CALCULATIONS.md` |
| Build log | `StateVarOsc/BUILD_LOG.md` |
| Pipeline | `~/Documents/LTspice/kicad_pipeline.py` |
| SimGUI | `~/Documents/LTspice/SimGUI/` |
| This tracker | `StateVarOsc/PROJECT.md` |

---

## Session Log

### Session 1 — 2026-03-05
- Created project folder and tracker
- Reviewed spec: DAC7800 + LM4562 + AD636 + J113, 20Hz-30kHz, 1V RMS
- Audited SPICE model library: LM4562, DAC7800, J113 missing; AD637 present
- Identified CircuitForge integration points (new circuit type + SimGUI parser)

### Session 2 — 2026-03-05
- Built all 4 behavioural SPICE models (LM4562, J113, DAC7800, AD636)
- Verified each model standalone in ngspice
- Wrote DESIGN.md (component specs, topology) and CALCULATIONS.md (equations, BOM)
- Built core SVF oscillator -- oscillation verified
- Integrated MDAC frequency control -- 880 Hz at D=121 (12% offset from calculated)
- Wrote AGC v2 (J113 in LP path) -- not yet tested

### Session 3 — 2026-03-05
- Tested AGC v2: FAILED (freq=359Hz, oscillation died, J113 pinched off)
- Diagnosed: J113 in LP path shifts frequency + AGC too slow (tau=1s)
- Designed and tested 6 alternative AGC approaches:
  - v3-VCA: B-source VCA + error integrator -- unstable (double-integrator loop)
  - v3-HP-hard: HP limiter -- subharmonic excitation (346 Hz)
  - v3-LP-hard: LP hard limiter -- killed by nonlinear B-source
  - v3-LP-tanh: LP tanh limiter -- same B-source issue
  - Verification tests: confirmed R_damp and B-source unity buffer are safe
  - v3-Zener: Back-to-back Zener diodes -- **SUCCESS: 927Hz, 1.03V RMS**
- Tuned Zener BV from 0.9V to 1.1V for target amplitude
- Wrote BUILD_LOG.md with complete trial-and-error documentation
- Updated PROJECT.md with current status
- **Next:** SimGUI integration, KiCad schematic
