# Oscillator Comparison Guide: MDAC vs Analog (Friend's Design)

## Overview

The Comparison mode runs both oscillator designs at the same 8 frequency points and presents side-by-side results showing how they differ in frequency accuracy, amplitude stability, and waveform quality.

**MDAC Design** (this repo): Digitally-controlled state variable oscillator with DAC7800 MDACs, LM4562 op-amps, and Zener diode AGC. Frequency is set by a 12-bit DAC code.

**Analog Design** (friend's circuit): Traditional state variable oscillator with fixed R/C integrators, AD824 op-amps, and a JFET-based AGC loop using an AD637 RMS detector, LM324 error amplifier, and J113 JFETs as voltage-controlled resistors.

---

## Circuit Differences

| Feature | MDAC Design | Analog (Friend's) Design |
|---------|-------------|--------------------------|
| **Op-amps** | LM4562 (55 MHz GBW) | AD824 (2 MHz GBW) |
| **Frequency control** | DAC7800 MDAC in integrator path | Fixed resistors (R=10k) + capacitors (C=10nF) |
| **Frequency range** | 24 Hz - 30 kHz (12-bit digital) | Fixed ~1581 Hz (must change R or C to retune) |
| **Integrator C** | 470 pF (C0G/NP0) | 10 nF |
| **AGC method** | Passive Zener clamps (BV=1.1V) on integrator caps | Active: AD637 RMS detector + LM324 error amp + J113 JFET VCR |
| **AGC result** | Clean ~1V RMS, no clipping | **Broken**: clips at +/-15V rails (~30 Vpp) |
| **Summing amp feedback** | R_lp=10k, R_bp=22k, Rf=10k | R5=10k (fb), R6=10k (LP), R7=100k (BP inv), R8=33k (BP non-inv) |
| **Amplitude stability** | Stable across full frequency range | Uncontrolled - AGC loop has wrong polarity/gain |
| **THD** | < 1% (Zener soft-clip) | ~6% (hard rail clipping) |
| **MCU integration** | ADuCM362 with SPI, ADC, UART | None (purely analog) |

### Why the Friend's AGC Fails

The analog AGC loop has several design issues:

1. **R7 (100k) is too high**: This is the damping resistor from BP to the inverting input. With R5=10k feedback, the BP contribution is attenuated 10:1. The negative damping is too weak to control amplitude.

2. **R8 (33k) provides excessive positive feedback**: Connected from BP to the non-inverting input, this drives oscillation amplitude up faster than the AGC can respond.

3. **AD637 input not attenuated**: The full +/-15V clipped output feeds the RMS detector through only R9=10k. The AD637 reads ~8V RMS, saturating the error amplifier.

4. **JFET gate driven positive**: With the RMS reading at 8V and the error amp unable to compensate, the J113 gate sits at +0.43V (Vgs positive), keeping the JFET fully ON (low resistance = high gain) when it should be increasing resistance to reduce gain.

### What Would Fix the Friend's Circuit

| Component | Current | Change To | Why |
|-----------|---------|-----------|-----|
| **R7** | 100k | **22k** | Increase negative feedback damping |
| **R8** | 33k | **68k-100k** | Reduce positive feedback |
| **R9** | 10k | **47k-100k** | Attenuate AD637 input (prevent saturation) |
| **J1, J2** | J113 | **2N5457** | Wider Vgs control range (-0.5 to -6V) |
| **R16** | 1.5k | **4.7k-10k** | Adjust JFET bias point |

Or the simpler fix: replace the entire JFET/RMS AGC loop with back-to-back Zener diodes on the integrator capacitors (the approach this repo uses successfully).

---

## How to Run Comparisons

### In SimGUI (Recommended)

1. Launch SimGUI
2. Select **"Comparison"** from the project dropdown (top-left)
3. To compare at a single frequency: select a frequency point and click **"Compare Point"**
4. To compare across all frequencies: click **"Compare All"** (runs 16 simulations: 8 MDAC + 8 Analog)
5. Click **"Amplitude View"** to toggle between:
   - **Frequency Accuracy** chart: shows how close each design gets to the target frequency
   - **Amplitude Stability** chart: shows BP RMS voltage across frequency (1.03V target line)
6. Use **"Export CSV"** to save comparison data for external analysis

### Color Coding

| Element | Color | Marker |
|---------|-------|--------|
| Ideal/Target | Gray, dashed line | Open circles |
| MDAC Design | Steel Blue (40,120,200) | Filled circles |
| Analog Design | Burnt Orange (200,80,40) | Filled diamonds |

In the data grid:
- MDAC columns have a light blue tint
- Analog columns have a light orange tint
- "Winner" column shows which design has lower frequency error at each point

### Command Line (Python)

Run simulations individually from the command line:

```bash
# Run MDAC oscillator at D=121 (~1kHz)
python kicad_pipeline.py oscillator 121

# Run analog oscillator at 1000 Hz target
python kicad_pipeline.py analog_osc 1000

# Run analog oscillator at friend's original frequency
python kicad_pipeline.py analog_osc 1581

# Run analog oscillator at low frequency
python kicad_pipeline.py analog_osc 25
```

Results are written to `sim_work/`:
- MDAC: `oscillator_d{dac_code}_results.txt`
- Analog: `analog_osc_{freq}Hz_results.txt`

Both use the same key=value format:
```
freq = 880.5
bp_pp = 2.91
bp_rms = 1.028
hp_pp = 2.95
lp_pp = 2.87
```

---

## Model Substitutions

The analog circuit uses LTspice-specific components. For ngspice, the SVF core uses LM4562 op-amps with the friend's original component values. The broken AGC loop (AD637 RMS detector, LM324 error amp, J113 JFETs) is represented by the absence of any amplitude limiting - faithfully reproducing the clipping behavior seen in LTspice.

| Original (LTspice) | ngspice Approach | Justification |
|--------------------|-----------------|---------------|
| AD824 (3x op-amps) | LM4562 | Both are dual op-amps. LM4562 behavioural model available in `StateVarOsc/models/LM4562.lib`. |
| AD637 + LM324 + J113 AGC | Not included (broken) | Friend's AGC loop doesn't work - omitting it produces the same result: rail-to-rail clipping. |
| R7=100k (low damping) | R7=100k (same) | Original value preserved - this is why the oscillator clips. |
| No Zener clamps | No Zener clamps | Unlike the MDAC design, the friend's circuit has no passive amplitude limiting. |

Note: An AD824 behavioural model is also available at `StateVarOsc/models/AD824.lib` for future use.

All models are located in `StateVarOsc/models/`.

---

## Expected Results

### MDAC Design (verified)
- Frequency error: 3-12% systematic (op-amp dominant pole effect), consistent across range
- BP RMS: ~0.86-1.09V (stable, near 1.03V target)
- BP Vpp: ~2.4-3.1V (clean, no clipping)
- Status: PASS/WARN at all points, correctable by ADuCM362 calibration
- Example: D=605 → 4621 Hz (target 5002 Hz, 7.6% error), 3.09 Vpp, 1.09V RMS

### Analog Design (Friend's - verified)
- Frequency error: 0.2-8.4% (varies with frequency)
- BP RMS: ~9.0-9.5V (rail-to-rail clipping, 9x above 1.03V target)
- BP Vpp: ~25.6-27.0V (clipping at +/-13.5V supply rails)
- Status: FAIL at ALL points due to broken AGC
- Clipping WARNING appears at every frequency point
- Example: 1000 Hz target → 944 Hz (5.6% error), 26.9 Vpp, 9.52V RMS
- Example: 1581 Hz target → 1491 Hz (5.7% error), 26.9 Vpp, 9.51V RMS

### Summary
The comparison clearly shows that the MDAC design maintains controlled amplitude (~1V RMS, ~3Vpp) and predictable frequency across the full 24Hz-30kHz range, while the analog design clips at the rails at every frequency point (~27Vpp, ~9.5V RMS) because the JFET AGC loop cannot regulate amplitude.

---

## CSV Export Format

The comparison CSV contains one row per frequency point with columns:

```
Timestamp, TargetHz, DacCode,
MdacFreqHz, MdacErrPct, MdacBpVpp, MdacBpRms, MdacHpVpp, MdacLpVpp, MdacStatus,
AnalogFreqHz, AnalogErrPct, AnalogBpVpp, AnalogBpRms, AnalogHpVpp, AnalogLpVpp, AnalogStatus,
Winner
```

---

## Prerequisites

- **Python 3.12+** with numpy, matplotlib, scipy, kicad-sch-api
- **ngspice** installed at `C:\Spice64\bin\ngspice_con.exe` (or set `NGSPICE_PATH` env var)
- **.NET 8+ SDK** for building SimGUI
- **KiCad 9** (optional, for schematic viewing)

### ngspice Installation

ngspice was installed from the [GitHub nightly builds](https://github.com/gatk555/ngspice/actions) to `C:\Spice64\`. Set `SPICE_LIB_DIR=C:\Spice64\share\ngspice` if needed.

## Troubleshooting

- **ngspice not found**: Ensure `ngspice_con.exe` is at `C:\Spice64\bin\` or on PATH, or set `NGSPICE_PATH` environment variable.
- **Simulation timeout**: Low-frequency points may take 1-2 minutes. Allow up to 10 minutes for a full sweep.
- **Include path errors**: If ngspice reports "Could not find include file", the project path may contain spaces. The netlist uses quoted `.include` paths to handle this.
- **All analog points FAIL**: This is the **expected behavior** - the friend's AGC loop is fundamentally broken. The comparison exists to demonstrate this difference graphically.
