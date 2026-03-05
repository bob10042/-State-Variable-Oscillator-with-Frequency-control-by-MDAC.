# CircuitForge - Automated Circuit Design & Simulation Platform

Python-driven pipeline for circuit design, simulation, and verification using KiCad + ngspice.

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
  kicad_pipeline.py          # Main pipeline (~8500 lines, 19 circuit types)
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
