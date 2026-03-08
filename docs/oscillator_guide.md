# State Variable Oscillator - Technical Guide

## 1. Quick Start

### Prerequisites

- **Python 3.8+** with packages: `pip install -r requirements.txt`
- **ngspice** installed (auto-detected, or set `NGSPICE_PATH` env var)
- **KiCad 9** installed (auto-detected, or set `KICAD_CLI_PATH` env var)

### Run a simulation

```bash
cd <repo_root>
python kicad_pipeline.py oscillator 121
```

This generates a SPICE netlist for DAC code D=121 (~1 kHz), runs ngspice, and outputs results to `sim_work/oscillator_d121_results.txt`.

### Generate block schematics

```bash
python kicad_pipeline.py osc_blocks
```

Produces 6 individual block PDFs + a merged `oscillator_blocks.pdf` in `sim_work/`.

---

## 2. Circuit Topology: KHN State Variable Oscillator

The oscillator is a **Kerwin-Huelsman-Newcomb (KHN) 3-op-amp biquad** state variable filter, configured to oscillate by providing sufficient loop gain.

### Signal Flow

```
        +-------+       +-------------+       +-------------+
  LP -->| U1    |--HP-->| U2          |--BP-->| U3          |--LP--+
  BP -->| Summing|      | Integrator 1|       | Integrator 2|      |
        | Amp   |      | (XDAC1)     |       | (XDAC2)     |      |
        +-------+       +-------------+       +-------------+      |
            ^                                                      |
            +------------------------------------------------------+
                              feedback loop
```

- **U1 (Summing Amp)**: Inverts and sums LP and BP feedback. Output = HP (high-pass).
- **U2 (Integrator 1)**: Integrates HP to produce BP (band-pass). MDAC controls frequency.
- **U3 (Integrator 2)**: Integrates BP to produce LP (low-pass). MDAC controls frequency.
- The phase inversion in U1 plus the two 90-degree integrations (U2, U3) create 360 degrees of phase shift around the loop, satisfying the Barkhausen criterion for oscillation.

### Op-amps

All three op-amps are **LM4562** dual low-noise op-amps (simulated with LM741 symbol in KiCad, LM4562 model in ngspice). GBW = 55 MHz.

---

## 3. Frequency Control: DAC7800 MDAC

Two **DAC7800** MDACs (multiplying DACs) replace the integration resistors in U2 and U3. The MDAC acts as a voltage-controlled resistor:

```
f = D / (4096 * 2*pi * R * C)
  = D / (4096 * 2*pi * 10k * 470p)
```

Where:
- **D** = DAC code (0-4095, we use 3-3632)
- **R** = 10k integration resistor (R4 for U2, R6 for U3)
- **C** = 470pF integration capacitor (C1 for U2, C2 for U3)

| DAC Code | Frequency |
|----------|-----------|
| D=3      | ~25 Hz    |
| D=121    | ~1 kHz    |
| D=970    | ~8 kHz    |
| D=3632   | ~30 kHz   |

The MCU (ADuCM362) writes DAC codes via SPI to both MDACs simultaneously.

---

## 4. Amplitude Control: Zener AGC

The oscillator uses **passive Zener diode AGC** (no active feedback loop). Back-to-back Zener diode pairs clamp the integrator outputs:

### Connection Topology (per integrator)

```
                 K     A     A     K
                 |--D1--|-----|--D2--|
                 |      anodes     |
                 |      joined     |
                 v                 v
          inv(-) node         output node
              |                    |
          [100M damping R]    [100M damping R]
              |                    |
          [470p int cap]      [470p int cap]
              |                    |
          op-amp inv(-)       op-amp output
```

- **D1/D2** (Integrator 1) and **D3/D4** (Integrator 2): DZ09, BV=1.1V
- Connected **anode-to-anode** in the center, **cathodes on the outside**
- Each cathode connects to the respective op-amp node (inverting input or output)
- Clamp level: BV + Vf = 1.1V + 0.7V = ~1.8V peak, ~1.27V RMS
- The 100M damping resistor (R5 for U2, R7 for U3) provides DC stability

This passive approach is simpler than the JFET-based AGC in the original friend's design (which used an AD636 RMS detector + LM324 error amplifier + 2N5457 JFET voltage-controlled resistor).

---

## 5. Six Functional Blocks

Each block has its own PDF schematic in `sim_work/`.

### Block 1: Summing Amplifier (U1)

**File**: `osc_block_summing_amp.pdf`

Combines LP and BP feedback signals with phase inversion. The HP output feeds both integrators, closing the oscillation loop.

- **HP = -(R1/R3) * LP - (R2/R3) * BP**
- R1 = R3 = 10k (LP gain = -1.0)
- R2 = 22k (BP gain = -2.2, sets Q)

### Block 2: Integrator 1 - HP to BP (U2 + XDAC1)

**File**: `osc_block_integrator1.pdf`

Integrates HP signal to produce BP output. DAC7800 MDAC controls effective resistance, setting oscillation frequency. Zener diodes (D1/D2, BV=1.1V) clamp output to ~1V RMS (passive AGC).

- **f = D / (4096 * 2pi * 10k * 470p)**
- C1 = 470pF integration capacitor
- R5 = 100M damping resistor (DC stability)
- D1/D2: back-to-back Zener AGC

### Block 3: AD636 RMS Detector (U4)

**File**: `osc_block_rms_detector.pdf`

Converts BP AC signal to DC voltage proportional to RMS amplitude. 1/5 attenuator scales ~1V RMS to ~200mV for AD636 input. MCU reads AIN0 to verify oscillation amplitude during calibration.

- **Vout_RMS = BP * R11/(R10+R11) = BP * 10k/(40k+10k) = BP/5**
- C3 = 10uF averaging capacitor
- AD636: true RMS-to-DC converter

### Block 4: Integrator 2 - BP to LP (U3 + XDAC2)

**File**: `osc_block_integrator2.pdf`

Second integrator converts BP to LP, completing the 90-degree phase shift chain. LP feeds back to summing amp, closing the oscillation loop. R8 (100k) provides DC load to prevent charge buildup.

- Mirrors Integrator 1 structure
- D3/D4: back-to-back Zener AGC
- R8 = 100k output load resistor

### Block 5: Power Supply + Startup Kick

**File**: `osc_block_power_supply.pdf`

R9 injects a brief pulse into HP at power-on to break equilibrium and start oscillation. Bulk caps filter supply noise.

- **PULSE(0, 0.1V, 0.1ms, 1ns, 1ns, 10us)**
- R9 = 100k (limits kick current)
- C6, C7 = 10uF bulk decoupling (+15V, -15V)
- C8 = 100nF (3.3V MCU supply decoupling)

### Block 6: ADuCM362 MCU (U5)

**File**: `osc_block_mcu.pdf`

Digital brain of the oscillator. Sets frequency via SPI to DAC7800 MDACs, measures actual frequency via Timer1 capture of BP zero-crossings (16MHz clock), reads amplitude via 24-bit ADC from AD636. Runs 16-point self-calibration stored in flash. UART host interface.

- SPI0: CLK, MOSI, CS -> DAC7800 XDAC1/XDAC2
- Timer1: P0.5 capture input for BP zero-crossing
- ADC0: AIN0 reads AD636 RMS output (PGA=4, Vref=1.2V)
- UART: 115200 8N1, commands: F/D/CAL/S/M/R/?

---

## 6. Simulation Pipeline

### Netlist Generation

`write_oscillator_netlist(dac_code)` in `kicad_pipeline.py` generates a SPICE `.cir` file with:

- LM4562 op-amp models (from included library)
- DAC7800 behavioural MDAC subcircuit
- DZ09 Zener diode model (BV=1.1V)
- Adaptive timing: simulation duration = 30 periods + 20% measurement window
- Measurement: zero-crossing of BP at 50% threshold

### Frequency Formula

```
f = D / (4096 * 2*pi * 10000 * 470e-12)
```

### Measurement

The simulation measures:
- **freq**: BP zero-crossing frequency (rise threshold at 200/201 of amplitude)
- **bp_pp**: BP peak-to-peak voltage
- **bp_rms**: BP RMS voltage
- **hp_pp**: HP peak-to-peak
- **lp_pp**: LP peak-to-peak

### Pass Criteria

| Metric | PASS | WARN | FAIL |
|--------|------|------|------|
| freq_err | < 5% | 5-15% | > 15% |

### Running from CLI

```bash
# Single frequency point
python kicad_pipeline.py oscillator 121

# 8-point sweep (via SimGUI)
cd SimGUI/SimGUI && dotnet run
```

---

## 7. Uncalibrated Error Analysis

The simulation shows systematic frequency error across the range:

| DAC Code | Expected (Hz) | Measured (Hz) | Error |
|----------|---------------|---------------|-------|
| 3        | 24.7          | 24.0          | -2.7% |
| 12       | 98.8          | 95.2          | -3.6% |
| 48       | 395.1         | 376.8         | -4.6% |
| 121      | 996.2         | 938.5         | -5.8% |
| 388      | 3193.8        | 2967.2        | -7.1% |
| 970      | 7984.5        | 7367.3        | -7.7% |
| 1940     | 15969.0       | 14836.1       | -7.1% |
| 3632     | 29895.0       | 27503.8       | -8.0% |

**Root cause**: LM4562 finite GBW (55 MHz) reduces effective gain at higher frequencies, causing the integrators to have slightly less than unity gain. The error is systematic, stable, and monotonic - correctable by calibration.

---

## 8. Firmware Calibration

The firmware in `firmware/oscillator/` implements self-calibration to correct the systematic frequency error.

### Source Files

| File | Purpose |
|------|---------|
| `osc_main.c` | Main loop, UART command processing |
| `osc_config.h` | Constants: SYSCLK, DAC range, ADC params |
| `osc_calibrate.c` | 16-point cal sweep, flash storage |
| `osc_calibrate.h` | Cal data structures |
| `osc_freq_measure.c` | Timer1 capture + ADC amplitude reading |
| `osc_dac7800.c` | SPI driver for DAC7800 |
| `osc_uart.c` | UART output helpers |
| `osc_system_init.c` | Clock, peripheral init |

### Calibration Sweep (`osc_calibrate.c`)

1. Write each of 16 log-spaced DAC codes (3, 6, 12, 24, ..., 3100, 3632)
2. Wait for settle: max(5 periods, AD636 time constant, 100ms), capped at 3s
3. Measure frequency: average 10 zero-crossing periods (3 for f < 50Hz)
4. Read AD636 RMS amplitude via 24-bit ADC
5. Calculate correction: `correction = expected_freq / measured_freq`
6. Store in `cal_data_t` struct

### Flash Storage

- Page 61 of ADuCM362 flash (512 bytes)
- Key sequence: 0xFDB3, 0x1F45
- Magic number validates stored data on boot

### Frequency Lookup (`calibrate_lookup`)

For a target frequency:
1. Find two bracketing calibration points
2. Linearly interpolate the correction factor
3. Apply: `corrected_code = ideal_code * interpolated_correction`
4. Clamp to DAC range (3-3632)

### Frequency Measurement Hardware (`osc_freq_measure.c`)

- **Timer1** in capture mode, PCLK source (16 MHz), no prescaler
- **P0.5**: BP zero-crossing input (AC-coupled, Schmitt trigger)
- Period = (capture[n+1] - capture[n]) / 16e6 seconds
- Resolution: 0.004% at 25 Hz, 0.19% at 30 kHz (averaged for better)
- Overflow tracking for periods > 65535 counts (< 244 Hz)

### ADC for Amplitude

- **ADC0**: 24-bit sigma-delta, PGA=4, internal 1.2V reference
- Range: +/-300mV (1.2V / 4)
- Resolution: 35.8 nV per LSB
- Reads AD636 RMS output on AIN0
- 1/5 attenuator undone in software: `v_rms = v_adc * 5`

---

## 9. UART Command Reference

Baud: 115200, 8N1. All responses prefixed with `$` for machine parsing.

| Command | Action | Response |
|---------|--------|----------|
| `F1000.0` | Set frequency to 1000 Hz (calibrated) | `$SET,target=1000.0,code=121,actual=998.3,rms=1023.5mV` |
| `D121` | Set raw DAC code | `$OSC,998.3,121,1023.5,12345` |
| `CAL` | Run 16-point calibration | `$CAL,1,3,24.0,1018.2,2.73%` ... `$INFO,Calibration saved` |
| `S` | Frequency sweep (all 16 cal points) | `$SWP,3,24.7,24.0,-2.73%,1018.2mV` ... |
| `M` | Single measurement | Updates internal state |
| `R` | Reset to default (D=121) | `$OSC,...` |
| `?` | Print status + help | `$INFO,DAC code: 121` ... |

---

## 10. SimGUI Integration

The SimGUI (.NET WinForms + ScottPlot) provides a graphical interface:

```bash
cd SimGUI/SimGUI
dotnet run
```

Features:
- 8-point DAC sweep with automatic simulation
- Calibration error simulation
- Grid display: DAC, Expected, Measured, Error%, Cal.Freq, Cal.Err, BP_RMS, Status
- CSV export of results
- Plot generation

---

## 11. Block PDF Schematics

### Individual Oscillator Blocks (6 files)

- `sim_work/osc_block_summing_amp_pdf/osc_block_summing_amp.pdf`
- `sim_work/osc_block_integrator1_pdf/osc_block_integrator1.pdf`
- `sim_work/osc_block_rms_detector_pdf/osc_block_rms_detector.pdf`
- `sim_work/osc_block_integrator2_pdf/osc_block_integrator2.pdf`
- `sim_work/osc_block_power_supply_pdf/osc_block_power_supply.pdf`
- `sim_work/osc_block_mcu_pdf/osc_block_mcu.pdf`

### Merged

- `sim_work/oscillator_blocks.pdf` (6 pages)

### Build Command

```bash
python kicad_pipeline.py osc_blocks
```

Each block includes: title, gain/frequency equations, component values, function description, and interface annotations showing connections to other blocks.
