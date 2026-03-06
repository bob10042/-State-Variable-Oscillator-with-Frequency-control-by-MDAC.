# CircuitForge - Automated Circuit Design & Simulation Platform

**Developer:** Bob Smith

CircuitForge is a Python-driven utility that automates the entire circuit design,
simulation, and verification workflow. Rather than manually drawing schematics in a
GUI and hand-writing SPICE netlists, CircuitForge lets you define a circuit in Python
and produces everything you need: a professional KiCad schematic, a SPICE netlist,
simulation results, and publication-quality plots.

## Development Progress

CircuitForge is under active development, with the pipeline improving each session:

- **Schematic quality**: Professional A3/A4 layouts at 1:1 scale (no post-scaling),
  with wire overlap detection, collinear wire merging, and configurable component spacing.
  Layout quality is benchmarked against industry-standard schematics (Triteq MM20 series).
- **Verification system**: Automated pin connectivity checks, floating wire detection,
  text overlap analysis, and dynamic pin parsing from KiCad symbol libraries.
- **LTspice conversion**: Can convert LTspice example circuits (.asc files) into
  KiCad schematics + ngspice simulations. The `demo_loader.py` tool handles the
  LTspice-to-ngspice netlist translation automatically.
- **20 circuit types** currently supported, from simple BJT amplifiers to a complete
  16-channel electrometer system with MCU firmware.

## What CircuitForge Does

CircuitForge takes a circuit description and drives it through a complete
build-simulate-verify pipeline:

1. **Schematic Generation** - Programmatically builds KiCad `.kicad_sch` files using
   the `kicad-sch-api` library. Components are placed on a scaled grid layout with
   proper wiring, power flags, and annotation. The LM741 KiCad symbol is used as a
   generic op-amp drawing shape throughout the pipeline (it provides the standard
   triangle symbol with inverting/non-inverting inputs and output) - the actual
   simulated device is set independently via the component value and SPICE model
   (e.g. the electrometer draws an LM741 symbol but simulates with LMC6001 as a
   proxy for the ADA4530-1 femtoamp-grade amplifier).

2. **Netlist Generation** - Writes SPICE `.cir` netlists independently of the
   schematic. The netlist references real SPICE models from vendor `.lib` files
   (National, Analog Devices, TI) stored in the `kicad_libs/` directory. Stimulus
   sources, analysis commands (`.tran`, `.ac`), and `.control` blocks are all
   generated automatically.

3. **Simulation** - Launches ngspice (or LTspice for specialty models like the
   ADA4530-1) in batch mode. The pipeline captures `wrdata` output files containing
   time-series voltage and current data for all nodes of interest.

4. **Result Parsing and Verification** - Parses raw simulation output, extracts
   per-channel measurements (settle time, DC level, accuracy vs expected), and runs
   automated pass/warn/fail checks against configurable tolerances.

5. **Self-Learning Correction** - Maintains a `learned_rules.json` file of schematic
   and netlist fixes discovered during previous runs. When the pipeline encounters a
   known issue (duplicate references, missing power nets, encoding problems), it
   auto-corrects before simulation, avoiding repeated manual fixes.

6. **Plotting** - Generates matplotlib plots of simulation waveforms with
   auto-scaled axes, channel annotations, and measurement markers. Plots are saved
   as PNG files alongside the simulation data.

7. **SimGUI** - A .NET 8 WinForms desktop application (using ScottPlot 5 for
   charting) that wraps the Python pipeline with a graphical interface. It provides
   project-selectable configurations (Electrometer, Oscillator), one-click simulation
   runs across all parameter ranges, and interactive result browsing.

8. **Firmware Generation** - Produces C source code for the ADuCM362 microcontroller
   that runs the physical hardware: ADC configuration, multiplexer scanning, relay
   range switching, UART streaming, and self-calibration routines.

## How CircuitForge Uses Its Resources

| Resource | Purpose |
|----------|---------|
| `kicad_pipeline.py` | Core engine (~10000 lines). Contains all circuit builders, netlist generators, simulators, plotters, and the self-learning correction loop. Run from the command line with a circuit type and parameters. |
| `kicad_libs/` | Custom KiCad symbol libraries (`.kicad_sym`) and SPICE model files (`.lib`, `.sub`). Includes vendor models for LMC6001, LM4562, DAC7800, AD636, CD4051B, and relay drivers. The LM741 symbol library provides the generic op-amp schematic shape used across all circuit types. |
| `sim_work/` | Working directory where all generated files land: `.kicad_sch` schematics, `.cir` netlists, `.txt` raw results, `.png` plots, and intermediate files. |
| `learned_rules.json` | Accumulated auto-correction rules. Each entry maps a problem pattern to its fix, so the pipeline improves over successive runs. |
| `ngspice` (`C:\Spice64\`) | Open-source SPICE simulator. CircuitForge invokes `ngspice_con.exe` in batch mode, passing the generated `.cir` netlist and collecting `wrdata` output. |
| `LTspice` | Used as a secondary simulator for circuits requiring proprietary models (e.g. the ADA4530-1 femtoamp op-amp) not available in ngspice. |
| `SimGUI/` | .NET 8 WinForms GUI built with ScottPlot 5. Calls `kicad_pipeline.py` as a subprocess, parses results, and provides interactive charts. Configured via `IProjectConfig` implementations for each project type. |
| `firmware/` | C source for the ADuCM362 target MCU. Compiled with `arm-none-eabi-gcc`. Includes drivers for SPI (DAC7800), UART, ADC, GPIO (mux/relay control), and flash-based calibration storage. |
| `StateVarOsc/` | Design documents, hand calculations, and standalone ngspice test circuits for the state variable oscillator sub-project. |

## Projects

### Electrometer (16-Channel TIA)
- 16-channel multiplexed transimpedance amplifier
- 9 ranges: Rf = 100 to 10G (mA down to fA)
- ADuCM362 MCU with 24-bit sigma-delta ADC
- Reed relay range switching

### State Variable Oscillator
- MDAC-controlled frequency: 25 Hz - 30 kHz
- Zener AGC for 1V RMS amplitude stability
- DAC7800 dual MDAC for integrator time constant control
- AD636 RMS-to-DC converter for amplitude monitoring
- ADuCM362 self-calibration firmware

## Prerequisites

### Python (3.10+)
```
pip install numpy matplotlib kicad-sch-api
```

### ngspice
Download from https://sourceforge.net/projects/ngspice/files/
- Install to `C:\Spice64\` (default)
- The pipeline uses `C:\Spice64\bin\ngspice_con.exe`

### .NET 8 SDK (for SimGUI)
Download from https://dotnet.microsoft.com/download/dotnet/8.0

### KiCad 9.x (optional, for viewing schematics)
Download from https://www.kicad.org/download/

### ARM Toolchain (optional, for firmware)
- `arm-none-eabi-gcc` for ADuCM362 firmware compilation
- ADuCM360/362 CMSIS device pack headers

## Directory Structure

```
LTspice/
  kicad_pipeline.py          # Main pipeline (~10000 lines, 20 circuit types)
  demo_loader.py             # LTspice .asc to ngspice converter
  PROJECT.md                 # Project tracker
  sim_work/                  # Simulation working directory (generated files)
  kicad_libs/                # Custom KiCad symbol libraries
  StateVarOsc/
    DESIGN.md                # Oscillator design document
    CALCULATIONS.md          # Frequency/amplitude calculations
    CALIBRATION.md           # ADuCM362 calibration plan
    models/                  # SPICE models (LM4562, DAC7800, AD636)
    tests/                   # ngspice test circuits
  SimGUI/SimGUI/             # .NET 8 WinForms GUI
    Projects/                # IProjectConfig implementations
      IProjectConfig.cs      # Generic project interface
      OscillatorConfig.cs    # Oscillator frequency sweep + calibration sim
      ElectrometerConfig.cs  # 16-channel TIA wrapper
    Models/                  # Data models
    Services/                # Result parsers, CSV export, simulation runner
    MainForm.cs              # Main GUI (generic, project-switchable)
  firmware/
    *.c, *.h                 # TIA/electrometer firmware (ADuCM362)
    oscillator/              # Oscillator firmware (standalone)
      osc_main.c             # Main loop + UART commands
      osc_calibrate.c/h      # Self-calibration (16-point LUT + flash)
      osc_dac7800.c/h        # SPI driver for DAC7800
      osc_freq_measure.c/h   # Timer1 capture + AD636 ADC
      osc_uart.c/h           # UART driver (115200 8N1)
      osc_system_init.c      # Clock, SysTick, peripheral init
      osc_config.h           # Pin mapping, constants
      Makefile               # ARM cross-compilation
```

## Quick Start

### Run a simulation
```bash
# Audio amplifier (LTspice educational example, 8 BJTs)
python kicad_pipeline.py audioamp

# Oscillator at D=121 (~1 kHz)
python kicad_pipeline.py oscillator 121

# Electrometer range 2 (1G feedback)
python kicad_pipeline.py channel_switch LMC6001 2

# Full system schematic
python kicad_pipeline.py full_system
```

### Run SimGUI
```bash
cd SimGUI/SimGUI
dotnet run
```
Select project (Electrometer/Oscillator) from the toolbar dropdown.

### CLI test mode
```bash
cd SimGUI/SimGUI
dotnet run -- --test
```

## Oscillator UART Commands

When the ADuCM362 firmware is running:

| Command | Description |
|---------|-------------|
| `F1000.0` | Set frequency to 1000 Hz (calibrated) |
| `D121` | Set raw DAC code |
| `CAL` | Run calibration sweep (16 points) |
| `S` | Run frequency sweep |
| `M` | Single measurement (freq + RMS) |
| `?` | Print status |
| `R` | Reset to default (1 kHz) |

## Pipeline Circuits

| Circuit | Description |
|---------|-------------|
| `audioamp` | 3-stage BJT audio amplifier (diff pair + VAS + push-pull, G=11) |
| `ce_amp` | Common-emitter BJT amplifier |
| `inv_amp` | LM741 inverting amplifier (G=-10) |
| `sig_cond` | Dual op-amp signal conditioner + LPF |
| `usb_ina` | 3-op-amp INA (G=95) |
| `electrometer` | Single TIA (Rf=1G) |
| `electrometer_362` | ADuCM362 electrometer + relays |
| `full_system` | Complete 16-ch system on A0 sheet |
| `channel_switch` | 16-channel mux switching sim |
| `oscillator` | State variable oscillator + MDAC |
| `femtoamp_test` | 100 fA sensitivity test |
| `avdd_monitor` | AVDD supply monitor |
