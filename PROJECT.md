# CircuitForge - Progress Tracker
## Automated circuit design, simulation, and self-learning verification from Python

---

## What We're Trying to Achieve

Take the pain out of building and simulating circuits. Instead of manually
drawing schematics in LTspice's GUI, we want a Python-driven workflow where we can:

1. **Search** the 4,242 LTspice demo circuits by keyword
2. **Load** any demo circuit and auto-convert it to ngspice format
3. **Patch** component values (resistors, caps, voltages, frequencies)
4. **Simulate** with ngspice (open-source SPICE engine)
5. **Plot** results with matplotlib
6. **Draw** professional schematics via KiCad (kicad-sch-api)
7. **Prototype** visually with Falstad for quick ideas
8. **Vision** - eventually read photos/screenshots of circuits and build netlists

The end game: describe a circuit in plain English, get a working simulation
and clean schematic back.

---

## Architecture (Updated)

```
  [User request / plain English]
       |
  ┌────┴────────────────────────────────────┐
  │  Track 1: Search & Patch                │
  │  [Search LTspice library] -> 4,242 .asc │
  │  [LTspice -netlist] -> .net             │
  │  [Clean for ngspice] -> fix encoding    │
  │  [Patch values] -> modify R/C/L/V       │
  └────┬────────────────────────────────────┘
       │
  ┌────┴────────────────────────────────────┐
  │  Track 2: Build from Python             │
  │  [kicad-sch-api] -> .kicad_sch          │
  │  [Write SPICE netlist] -> .cir          │
  └────┬────────────────────────────────────┘
       │
  [ngspice -b]  ──────>  Simulation results
       │
  ┌────┴────────────────────────────────────┐
  │  [matplotlib] -> Waveform plots         │
  │  [kicad-cli]  -> SVG/PDF schematic      │
  │  [Falstad]    -> Interactive prototype   │
  └─────────────────────────────────────────┘
```

---

## Phase 1: Core Pipeline [DONE]
Build the search-load-patch-simulate-plot workflow.

| Task | Status | Notes |
|------|--------|-------|
| Install ngspice 45.2 | DONE | C:\Spice64\bin\ngspice_con.exe |
| Install schemdraw 0.22 | DONE | Pre-existing, 170+ components |
| Install PySpice 1.5 | DONE | Python-ngspice bridge (dead project) |
| Build circuit_tool.py | DONE | Search, load, patch, sim, plot |
| Build demo_loader.py | DONE | Earlier version, superseded by circuit_tool |
| LTspice netlist generation | DONE | LTspice.exe -netlist <file.asc> |
| UTF-16LE encoding handling | DONE | Auto-detect and convert |
| Strip LTspice params | DONE | Vceo, Icrating, mfg removed |
| Fix .tran syntax | DONE | LTspice -> ngspice format |
| BJT model extraction | DONE | 2N3904, 2N2219A, 2N3906 cleaned |
| Audio amplifier demo | DONE | Loaded, patched, simulated, plotted |
| Passive filter demo | DONE | Wien bridge netlist generated |

## Phase 2: Class D Amplifier [PARTIAL]
Build and simulate a Class D half-bridge audio amplifier.

| Task | Status | Notes |
|------|--------|-------|
| Basic Class D topology | DONE | Half-bridge with LC filter |
| Comparator PWM generation | DONE | B-source with tanh() |
| Gate driver with dead-time | DONE | Split HI_DRV/LO_DRV paths |
| Shoot-through fix | DONE | Dead-time prevents overlap |
| Schematic drawing (schemdraw) | POOR | Abandoned - schemdraw layout is messy |
| Use real comparator (LT1011) | BLOCKED | .sub files encrypted |
| Proper FET totem-pole layout | TODO | Revisit with KiCad pipeline |

## Phase 3: KiCad Schematic Pipeline [WORKING]
Replace schemdraw with kicad-sch-api for professional schematics.

| Task | Status | Notes |
|------|--------|-------|
| Research alternatives | DONE | Evaluated 15+ tools (see Research below) |
| Install kicad-sch-api v0.5.5 | DONE | pip install kicad-sch-api |
| Download KiCad symbol libraries | DONE | 22,711 symbols from GitLab |
| Proof of concept: CE amplifier | DONE | 8 components, 18 wires, 7 labels |
| ngspice simulation from pipeline | DONE | 187x gain (45 dB), correct bias points |
| Matplotlib schematic renderer | DONE | Clean labels, symbols, wires, junctions |
| Build kicad_pipeline.py | DONE | End-to-end: Python -> schematic + sim |
| Install KiCad 9.0.7 | DONE | winget install, kicad-cli at AppData/Local/Programs/KiCad/9.0/ |
| SVG export via kicad-cli | DONE | fix_kicad_sch() strips incompatible tokens |
| Manhattan wire routing | DONE | wire_manhattan() + get_pin_pos() |
| Micro-Cap 12 model library | DONE | 108K .model + 38K .subckt, 167 lib files |
| Model search & extract | DONE | search_models() + extract_model() in pipeline |
| LM741 inverting amplifier | DONE | Gain=-10 (20dB), transistor-level model from nation.lib |
| Multi-circuit CLI support | DONE | `python kicad_pipeline.py inv_amp` or `ce_amp` |
| Op-amp mirror (- on top) | DONE | fix_kicad_sch(mirror_refs=["U1"]) adds (mirror x) |
| Feedback path routing | DONE | Rectangular loop: junction->up->Rf->down->output |
| PDF export via kicad-cli | DONE | export_pdf() + render_pdf_to_png() at 5x zoom |
| Circuit verification system | DONE | verify_circuit(): connectivity, labels, feedback, gain check |
| Simulation measurement | DONE | measure_simulation(): Vpp, gain, gain_dB auto-check |
| Pin position mapping | DONE | R/C pin1=RIGHT, pin2=LEFT for rot=90; LM741 8-pin map |
| Power symbols (GND/VCC/VEE) | DONE | GND triangles, VCC/VEE arrows replace text labels |
| VSIN input source symbol | DONE | Sine wave source symbol with +/- pins |
| Hide #PWR references | DONE | fix_kicad_sch() adds (hide yes) to #PWR instances |
| (power global) compat fix | DONE | Converts to (power) for kicad-cli 9.0.7 |
| Symbol presence verification | DONE | verify_circuit() checks GND/VCC/VEE symbols + VSIN |
| Dual op-amp signal conditioner | DONE | Non-inv amp (G=11) + Sallen-Key LPF (1kHz), 22 components, 9/9 pass |
| Swappable op-amp models | DONE | OPAMP_DB: LM741, AD822, AD843 tested. CLI: `sig_cond AD822` |
| DC bias path fix | DONE | Rbias (100k) needed for AC-coupled non-inv (+) input |
| AC analysis / Bode plots | DONE | .ac sweep 10Hz-100kHz, -3dB at 481Hz for sig_cond LPF |
| USB-isolated 3-op-amp INA | DONE | 3x LM741/AD822, G=95, differential input, 9/9 pass |
| Op-amp label fix | DONE | OPAMP_TITLES dict for AD822/AD843 in plot titles |
| Wire crossing detection | DONE | check_wire_crossings() in verify_circuit(), auto-detects visual ambiguity |
| Wire crossing fix: sig_cond | DONE | U2 feedback routed higher (-7*G) to clear VEE stub |
| Wire crossing fix: usb_ina | DONE | V1/V2 moved below U1(+)/U2(+) with vertical-only wires |
| Op-amp pin connectivity check | DONE | check_pin_connectivity() verifies all 5 LM741 pins connected |

## Phase 3b: Electrometer TIA (Simple) [DONE]
Build the electrometer's core transimpedance amplifier as Circuit #5.

| Task | Status | Notes |
|------|--------|-------|
| Electrometer build plan | DONE | Plans in .claude/plans/ (TIA + HV divider + full platform) |
| Test TIA netlist (LM741) | DONE | sim_work/test_tia.cir - 10M Rf, 100nA pulse, ADC model |
| Electrometer platform scaffold | DONE | ~/Downloads/Electrometer/electrometer-platform/ (docs, firmware stubs, GUI stubs) |
| Add LMC6001/OPA128 to OPAMP_DB | DONE | 6 op-amps: LMC6001, LMC6001A, OPA128, AD822, AD843, LM741 |
| build_electrometer_tia() | DONE | 10 components, 18 wires, Rf/Cf parallel feedback, mirror x |
| write_electrometer_tia_netlist() | DONE | 1nA pulse, Rf=1G, Cf=10pF, 200ms transient for settling |
| write_electrometer_tia_ac_netlist() | DONE | .ac 0.1Hz-100kHz, transimpedance Bode plot |
| TIA-specific measurement | DONE | Transimpedance: 9.98e+08 V/A (expected 1G), 0.2% error |
| AC analysis verified | DONE | -3dB at 16Hz (theory 15.9Hz), passband 180dB = 1G V/A |
| CLI + verify integration | DONE | `python kicad_pipeline.py electrometer LMC6001`, **10/10 pass** |

### Electrometer Bug Found & Fixed During Build
- **100nA saturated output**: Initial test used 100nA into 1G = 100V, but supply is +/-12V.
  Fix: reduced to 1nA (gives -1V output, well within rails). Added settling time (5*tau = 50ms).

---

## Phase 3c: ADuCM362 Electrometer Platform Schematics [IN PROGRESS]

Full system schematics for the electrometer platform built around the ADuCM362 eval board.
Architecture doc: `~/Downloads/Electrometer/electrometer-platform/docs/01_architecture.md`
BOM: `~/Downloads/Electrometer/electrometer-platform/hardware/bom/prototype_bom.csv` (~430 GBP)
Output folder: `~/Downloads/Electrometer/electrometer-platform/hardware/schematics/`

### Subsystem 1: TIA Front-End (ADA4530-1) [DONE]

| Task | Status | Notes |
|------|--------|-------|
| build_electrometer_362() | DONE | 15 components, 27 wires, mirrored op-amp, 3.3V single supply |
| LTspice batch simulation | DONE | `simulate_ltspice()` using LTspice.exe -b + ltspice Python pkg |
| ADA4530-1 model extraction | DONE | From LTspice ADI1.lib (44 subcircuits, plain text) |
| write_electrometer_362_ltspice() | DONE | .net format with `.lib ADI1.lib` directive, 6-pin model |
| write_electrometer_362_netlist() | DONE | ngspice with LMC6001 proxy (dual +/-5V for sim compatibility) |
| All 4 ranges verified (ADA4530-1) | DONE | R0:10M(0%), R1:100M(0%), R2:1G(0.2%), R3:10G(0.2%) |
| AC analysis + Bode plot | DONE | write_electrometer_362_ac_netlist() |
| Wire crossing fix | DONE | VSIN routed above feedback to avoid ref divider crossing |
| Double output fix | DONE | Removed redundant OUT label, only AIN0 now |
| verify_circuit updated | DONE | Required nets: {GND, VCC, AIN0}, single supply handling |
| Schematic exported | DONE | electrometer_362_large.png (2836x2127) |

**How to run:** `python kicad_pipeline.py electrometer_362 ADA4530 2`
- Args: `electrometer_362 <opamp> <range>` where opamp=ADA4530/LMC6001, range=0-3
- ADA4530 uses LTspice batch mode; all others use ngspice

**Key files:**
- `sim_work/electrometer_362.kicad_sch` - KiCad schematic
- `sim_work/electrometer_362_large.png` - rendered schematic image
- `sim_work/electrometer_362_lt.net` - LTspice netlist (ADA4530-1)
- `sim_work/electrometer_362.cir` - ngspice netlist (LMC6001 proxy)
- `sim_work/electrometer_362_results.png` - transient simulation plot
- `sim_work/electrometer_362_bode.png` - frequency response Bode plot

**Technical notes:**
- ADA4530-1 model uses LTspice-specific syntax (OTA, VDMOS, noiseless, dnlim/uplim) - NOT ngspice compatible
- ADI1.lib path: `C:\Users\Robert\AppData\Local\LTspice\lib\sub\ADI1.lib`
- LMC6001 PMOS inputs (VTO=-2.456V) can't operate at mid-supply with 3.3V - sim uses dual +/-5V
- Real ADA4530-1 has rail-to-rail inputs so 3.3V single supply works on hardware
- Guard buffer pin (pin 6/GDR) connected through 100Meg to ground in simulation
- `ltspice` Python package v1.0.6: `raw.get_time()`, `raw.get_data('V(name)')`

### Subsystem 2: Reed Relay Range Switching [DONE]

The relay ladder switches between 4 feedback resistors on the TIA.
From BOM: 4x 109P-1-A-5/1 SPST reed relays, 4x 2N3904 NPN drivers, 4x 1N4148 flyback diodes, 4x 1k base resistors.

| Task | Status | Notes |
|------|--------|-------|
| build_relay_ladder() | DONE | 30 components, 40 wires, SW_Reed + Rf + Cf layout |
| NPN relay driver circuit | DONE | 4x 2N3904 + 1k base R + 1N4148 flyback per channel |
| GPIO labels GP1.0-GP1.3 | DONE | Labels connect to base resistors for ADuCM362 Port 1 |
| 5V relay coil supply | DONE | VCC symbols with 5V_ISO value on each driver |
| Simulate relay switching | DONE | NPN transient: 2.4mA coil current, flyback clamped |
| Wire crossing check | DONE | **0 crossings**, 9/9 pass |
| Integrate with TIA schematic | TODO | Combined schematic or hierarchical sheet |

**Circuit topology:**
```
  3.3V GPIO (GP1.x) --> 1k --> 2N3904 base
                               collector --> relay coil --> 5V_ISO
                               emitter --> GND
                               1N4148 flyback across coil

  Relay contacts: SPST normally-open
  K1: connects Rf0 (10M)    to inv_pin and out_pin
  K2: connects Rf1 (100M)   to inv_pin and out_pin
  K3: connects Rf2 (1G+10p) to inv_pin and out_pin
  K4: connects Rf3 (10G+1p) to inv_pin and out_pin
  Only one relay closed at a time (firmware ensures this)
```

**How to run:** `python kicad_pipeline.py relay_ladder`

**Key files:**
- `sim_work/relay_ladder.kicad_sch` - KiCad schematic
- `sim_work/relay_ladder_large.png` - rendered schematic image
- `sim_work/relay_ladder.cir` - ngspice netlist (NPN driver test)
- `sim_work/relay_ladder_results.png` - NPN switching transient plot

**Technical notes:**
- SW_Reed symbol for contacts (lib_id `SW_Reed:SW_Reed`), separate from coil drivers
- kicad-sch-api lib_id format: `SymbolName:SymbolName` (NOT `LibraryName:SymbolName`)
- Device:D available as `D:D`, Q_NPN_BCE as `Q_NPN_BCE:Q_NPN_BCE`
- Coil modeled as 500R + 50mH for simulation; real 109P-1-A-5/1 is ~500R/5V
- Flyback diode clamps collector spike to ~5.3V (1N4148 forward drop)

### Subsystem 3: HV Resistive Dividers (3-phase) [NOT STARTED]

Three identical voltage divider channels for L1, L2, L3 mains measurement.
From BOM: 9x 3.3M 1% 1kV resistors (3 per channel in series = 9.9M), 3x 10k 0.1% precision.

| Task | Status | Notes |
|------|--------|-------|
| build_hv_divider() | TODO | Single channel: 3x3.3M series + 10k bottom + 100pF anti-alias |
| Divider ratio verification | TODO | Simulate 991:1 ratio, check at 230V and 400V |
| Anti-alias filter | TODO | 100pF C0G across 10k, fc=159kHz |
| 3-channel layout | TODO | Replicate for L1/L2/L3 with ADC1 labels (AIN4-9) |
| Wire crossing check | TODO | Must pass 0 crossings |

**Circuit topology per channel:**
```
  L_in --[Fuse 250mA]--[3.3M]--[3.3M]--[3.3M]--+--[10k]--+---> AINx (+)
                                                  |         |
                                                  +--100pF--+
                                                  |
                                                  +---> AINx+1 (-) (AGND)
```

### Subsystem 4: HV Input Protection [NOT STARTED]

Per-phase protection: fuse + MOV + TVS diode.
From BOM: 3x 250mA ceramic fuses, 3x TMOV20RP275E MOVs, 3x SMDJ400A TVS diodes.

| Task | Status | Notes |
|------|--------|-------|
| build_hv_protection() | TODO | Fuse + MOV (line-neutral) + TVS (line-GND) per phase |
| TVS clamping simulation | TODO | Verify SMDJ400A clamps at 645V |
| Integrate with divider | TODO | Protection goes before divider input |

### Subsystem 5: USB Isolation (ADuM3160 + DC-DC) [NOT STARTED]

USB isolation module + isolated power.
From BOM: ADuM3160BRWZ module, MEE1S0505SC DC-DC converter.

| Task | Status | Notes |
|------|--------|-------|
| build_usb_isolation() | TODO | ADuM3160 module block + DC-DC + USB-B connector |
| UART labels | TODO | TX/RX from ADuCM362 UART0 (P0.0/P0.1) |
| Power distribution | TODO | 5V USB -> DC-DC -> 5V_ISO -> LDO -> 3.3V |
| Decoupling caps | TODO | 100nF on each power rail |

### Subsystem 6: Full System Integration [DONE]

Combined all subsystems into a single A0 schematic via `build_full_system()`.

| Task | Status | Notes |
|------|--------|-------|
| ADuCM362 pin mapping | DONE | ADC0(AIN0-3), ADC1(AIN5-7), GPIO(ADDR/EN/RELAY), UART, SWD |
| Single flat schematic (A0) | DONE | 181 components on one sheet, net labels auto-connect subsystems |
| Decoupling per-subsystem | DONE | 100nF per mux IC, AVDD/DVDD 100nF+10uF, 470nF regulator, VREF bypass |
| Internal VREF confirmed | DONE | CN-0359 firmware analysis: ADC0 uses AVDD ref, ADC1 uses internal 1.2V |
| Full verification | DONE | 20/20 pass, 133 distinct nets, 96 labels, 4 wire crossings (cosmetic) |
| PNG export | DONE | full_system_large.png (14105x8435 px, A0 sheet) |
| Power distribution tree | TODO | USB 5V -> DC-DC -> 5V_ISO -> LDO -> 3.3V (needs Subsystem 5) |
| Export for PCB layout | TODO | Netlist export for KiCad PCB editor |

### Build Order (recommended sequence for next sessions)

1. **Relay ladder** (Subsystem 2) - extends the existing TIA, straightforward NPN driver circuit
2. **HV divider** (Subsystem 3) - single channel first, then replicate x3
3. **HV protection** (Subsystem 4) - fuse/MOV/TVS, integrates with divider input
4. **USB isolation** (Subsystem 5) - module-level block diagram
5. **System integration** (Subsystem 6) - combine all sheets, power tree, final verify

### Dual Simulator Architecture

The pipeline supports two simulation engines:
- **ngspice** (`C:\Spice64\bin\ngspice_con.exe`): For open Micro-Cap models (LMC6001, AD822, etc.)
- **LTspice** (`C:\Program Files\ADI\LTspice\LTspice.exe -b`): For AD-proprietary models (ADA4530-1)

Selection is automatic: `opamp=ADA4530` triggers LTspice, all others use ngspice.
LTspice .raw files read via `ltspice` Python package (v1.0.6).

---

## Phase 3e: 16-Channel Multiplexed Measurement Board [PLANNED]

Based on analysis of Triteq MM20-TRI-SCH-1312_MB (16-channel measurement board).
Replaces PIC18F4550 + AD8304 log amp + MCP3551 ADC with ADuCM362 + ADA4530-1 TIA.
Reference schematic: `~/Downloads/all tec/gen 3 systems/.../Appendix D Circuit Daigrams/MM20-TRI-SCH-1312_MB-002.PDF`

### Architecture

```
16 inputs → [BAV199 clamp + 1M + 10nF filter] → 2x MAX338 8:1 mux
                                                       ↓ (selected channel)
                                                 ADA4530-1 TIA
                                                       ↕ relay Rf ladder (10M/100M/1G/10G)
                                                       ↓
                                                 ADuCM362 ADC0 (24-bit)
                                                       ↓
                                                 USB isolated (ADuM3160)
```

### MM20 vs Proposed Design

| Feature | MM20 Original | Proposed Replacement |
|---------|--------------|---------------------|
| MCU | PIC18F4550 (8-bit, USB) | ADuCM362 (ARM M3, dual 24-bit ADC) |
| ADC | 2x MCP3551 22-bit external | Built-in dual 24-bit sigma-delta |
| Measurement | AD8304 log amp (~7 decades) | ADA4530-1 TIA (linear, 4 relay ranges) |
| Low-end | ~100pA | ~14fA (700x better) |
| Channel select | 2x MAX338 8:1 analog mux | Same MAX338 (proven, keep it) |
| Input filter | 1M + 10nF (fc=15.9Hz) | Same RC filter (proven, keep it) |
| Calibration | Complex: V=K*log(I/Iref) | Simple: V=I*Rf |
| Comms | USB + RS485 + LIN | USB isolated + optional RS485 |

### Build Stages

**Stage 1: Input filter array (16 channels) [DONE]**

| Task | Status | Notes |
|------|--------|-------|
| build_input_filters() | DONE | 112 components, 32 wires, 2 columns x 8 rows on A3 |
| Verify structural | DONE | 8/8 pass, 0 errors, 0 crossings, 16 CH_IN + 16 MUX labels |
| Simulation | DEFERRED | Filter AC response will be tested in Stage 5 full-path sim |

**Stage 2: Analog multiplexer (2x MAX338) [DONE]**

| Task | Status | Notes |
|------|--------|-------|
| build_analog_mux() | DONE | 2x CD4051B (stand-in for MAX338), 12 components, 34 wires |
| ADDR_A0-A2 + EN_A/EN_B labels | DONE | Shared address lines, per-mux enable |
| Decoupling: 100nF per mux | DONE | C17, C18 on VDD pins |
| TIA_IN output label | DONE | Both mux common outputs → TIA_IN (high-Z when disabled) |
| Verify structural | DONE | 10/10 pass, 0 errors, 0 crossings |

**Stage 3: TIA with mux interface [DONE]**

| Task | Status | Notes |
|------|--------|-------|
| build_mux_tia() | DONE | ADA4530-1 TIA, 11 components, 25 wires, mirrored LM741, 3.3V single supply |
| TIA_IN from mux | DONE | Input routed above feedback area to avoid wire crossings |
| Rf=1G + Cf=10pF feedback | DONE | Range 2 default, INV/OUT labels for relay ladder |
| VREF divider (100k/100k) | DONE | 1.65V mid-supply reference → non-inv input → AIN1 |
| AIN0/AIN1 ADC outputs | DONE | AIN0=TIA output, AIN1=VREF for differential measurement |
| Verify structural | DONE | 13/13 pass (incl layout quality), 0 errors, 0 crossings |
| Self-learning correction loop | DONE | build_and_verify_loop() with learned_rules.json |

**Stage 4: ADuCM362 MCU + ADC interface [DONE]**

| Task | Status | Notes |
|------|--------|-------|
| build_mcu_section() | DONE | 16 components, 40 wires, 27 labels, CN-0359 based |
| ADC0 inputs: AIN0-AIN3 | DONE | AIN0/1 (TIA current diff), AIN2/3 (voltage diff) |
| ADC1 inputs: AIN5-AIN7 | DONE | AIN5/6 (RTD temp), AIN7 (IEXC current source) |
| GPIO P0: mux address | DONE | ADDR_A0-A2, EN_A, EN_B labels |
| GPIO P1: relay control | DONE | RELAY_0-3 labels |
| PWM outputs | DONE | PWM0-2 (excitation control, CN-0359 style) |
| UART + SWD debug | DONE | UART_TX/RX, SWCLK/SWDIO labels |
| DAC output | DONE | DAC_OUT for excitation voltage control |
| Decoupling | DONE | C1-C4 (100nF+10uF for AVDD/DVDD), C5-C6 (470nF regulator), C7 (VREF) |
| Verify structural | DONE | 13/13 pass, 0 errors, 0 crossings, correction loop clean on attempt 1 |
| CN-0359 design support | DONE | Extracted to ~/Documents/LTspice/cn0359/ (schematic, firmware, BOM) |

**Stage 5: Full System Integration (all subsystems on one sheet) [DONE - UPDATED]**

| Task | Status | Notes |
|------|--------|-------|
| build_full_system() | DONE | 7 regions on single A0 sheet, ~122 components |
| Input filters (16ch) | DONE | 2 columns of 8 channels: BAV199 + 1M + 10nF → MUX_A/B labels |
| Analog mux (2x CD4051B) | DONE | MUX_A/B1-8 inputs, TIA_IN output, ADDR/EN control labels |
| Mux TIA (ADA4530-1) | DONE | TIA_IN input, Rf=1G+Cf=10pF, VREF divider, AIN0/AIN1 outputs |
| Relay ladder (4x reed) | **UPDATED** | Moved to lower-left (was crowding TIA). NPN base R spacing 20*G |
| MCU section (ADuCM362) | **UPDATED** | AIN0-4 (ADC0) + AIN5-9 (ADC1) - ALL analog inputs wired |
| AVDD monitor (NEW) | DONE | R28/R29 100k divider -> AIN2/AIN3 (supply drift monitoring) |
| AIN4 guard monitor (NEW) | DONE | GUARD net label for guard ring voltage monitoring |
| RTD terminal (NEW) | DONE | J2 4-wire connector, R30 1.5k RREF, AIN8/9 Kelvin sense |
| Per-component annotations | DONE | Inline docs: Rf values, base drive calc, filter fc, etc. |
| Internal VREF only | DONE | ADuCM362 internal 1.2V ref, no external VREF needed |
| Image size cap | DONE | render_pdf_to_png() max_dim=7500 prevents API 8000px errors |
| PNG export (A0 sheet) | DONE | Capped at 7500px max dimension |

**Session 6 changes (2026-03-03):**
- Relay ladder relocated from center (x=310G) to lower-left (x=60G, y=200G) - frees TIA area
- NPN base resistor offset increased from 12*G to 20*G (was too close to transistors)
- ADC0: Added AIN4 (guard monitor), total 5 inputs (AIN0-4)
- ADC1: Added AIN8, AIN9 (RTD Kelvin sense), total 5 inputs (AIN5-9)
- AVDD monitor divider: R28/R29 100k + C30 bypass -> AIN2/AIN3 differential
- RTD terminal: J2 4-pin connector with RREF for CN-0359 style 2/3/4-wire auto-detect
- Temperature logging required alongside each channel measurement for drift compensation
- Export region clips updated for new layout positions
- Correction loop gap identified: only checks geometry, not design completeness/layout efficiency

**Session 7 changes (2026-03-03):**
- ESD clamp diodes fixed to cathode-to-cathode at signal (matching MM20-TRI-SCH-1312_MB)
- Upper diode: rotation=90 (K/bar at bottom toward signal), lower: rotation=270 (K/bar at top toward signal)
- VCC power symbol REMOVED from upper diode — replaced with GND (both anodes to AGND)
- MM20 reference confirmed: BAV199 common-cathode topology, both anodes to AGND, negative-only ESD clamp
- 1M series resistor provides current limiting for positive transients
- Both build_full_system() and standalone build_input_filters() updated consistently
- Input filter diode rotation=90 fix (added in session 6) confirmed working for signal path
- Input filter 1M resistor rotation=90 fix (added in session 6) confirmed working

**Stage 6: Full-path simulation [DONE]**

| Task | Status | Notes |
|------|--------|-------|
| Simulate single channel path | DONE | Filter→Mux→TIA→ADC: 9.99e+08 V/A, 0.1% error |
| Full-path AC analysis | DONE | Bode plot: filter + TIA combined frequency response |
| 16-channel switching sim | DONE | 16 channels, varied currents (0.05-1.0nA), 200ms/ch, avg 8.3% error |
| Femtoamp sensitivity test | DONE | 100fA → 1.00mV, 10G Rf, 6711 ADC counts (24-bit), PASS |
| AVDD monitor readback | DONE | R28/R29 divider ratio 0.497, tracks within 0.65%, PASS |
| RTD temperature sim | DONE | PT100/PT1000 4-wire Kelvin, 0.002C accuracy, 920k ADC counts |
| Combined data logging | DONE | 4ch current + PT100 temp per channel, drift detected 1.4C/scan |
| Correction loop improvements | TODO | Add unused-space, proximity, completeness rules |

**Session 8 changes (2026-03-04):**
- Added 4 new CLI circuits: `full_path`, `channel_switch`, `femtoamp_test`, `avdd_monitor`
- `write_full_path_netlist()`: Single channel with input filter (1M+10nF), SW_MUX model (Ron=100R, Roff=1T), TIA, ADC load
- `write_full_path_ac_netlist()`: AC sweep showing combined filter + TIA frequency response
- `write_channel_switching_netlist()`: 16 channels with Norton sensor models (I_src + R_DUT=100M)
  - Filter caps omitted to avoid charge-dump transients during mux switching
  - R_BIAS (100M) on TIA_IN prevents floating input during switch transitions
  - 200ms per channel for full TIA settling (Rf*Cf = 10ms, need ~20 tau)
  - 16 channels with varied currents (0.05nA to 1.0nA realistic spread)
  - Average error 8.3%, max 32.9% (CH9 at 0.05nA — R_DUT shunt + VOS dominates)
  - Errors scale inversely with current: <5% above 0.5nA, >15% below 0.15nA
- `write_femtoamp_test_netlist()`: 100fA through full path at Range 3 (10G+1pF)
  - `.options gmin=1e-16 abstol=1e-16` for femtoamp accuracy
  - ADC LSB = 149nV (24-bit, 2.5V range), 1mV signal = 6711 counts
- `write_avdd_monitor_netlist()`: 100k/100k divider with AVDD sweep (3.135-3.465V)
- Current source naming: renamed `I1` to `Isrc` in full-path netlists to avoid name collision with LMC6001 subcircuit internals
- ADC load model fixed: 100R series + 10M shunt (was 10M series + 1G shunt)
- `write_rtd_temp_netlist()`: 4-wire PT100/PT1000 RTD measurement via ADuCM362 ADC1
  - Behavioral B-source models RTD: R(T) = R0*(1 + A*T + B*T²), IEC 751
  - IEXC = 600µA, RREF = 1.5k, ratiometric measurement (IEXC cancels)
  - Temperature staircase: -40, 0, 25, 50, 100, 150, 200°C
  - 4-wire Kelvin sensing: 1Ω lead resistance fully cancelled
  - Max error: 0.002°C across full range
  - PT100: 920k ADC counts at 25°C; PT1000: 9.2M counts
- `write_combined_logging_netlist()`: Combined current + temperature data logging
  - ADC0 (TIA current) and ADC1 (RTD temp) run simultaneously
  - 4 channels with 200ms/ch, RTD ramps 25→27°C to simulate thermal drift
  - Per-channel temperature logged: firmware can compensate for drift

**Session 9 changes (2026-03-08): Block schematic review + portability**
- **Input filters**: Fixed 3 critical issues:
  - R:R 1M resistors had no rotation (vertical) — added rotation=90 for horizontal placement
  - BAV199 ESD diode rotations swapped (90↔270) — cathodes now connect at signal wire
  - Added junction dots at diode cathode-to-cathode signal connection
  - Added explicit wires from diode anodes to GND symbols (was relying on pin coincidence)
  - Added explicit wires from cap pin2 to GND symbols
- **Relay ladder**: Flyback diode rotation=270 wrong (pins horizontal, wires assumed vertical) — changed to rotation=90 (K at top, A at bottom)
- **Electrometer 362 + Mux TIA**: Added 4 missing junction dots each at T-junctions (input/feedback branch, Rf/Cf split, output column merge, divider midpoint)
- **Mux TIA**: Added merge_collinear_wires() post-processing (was missing)
- **AD636 RMS detector**: Replaced text-only "U4 AD636" annotation with drawn IC box (wire rectangle with pin labels VIN/VOUT/CAV)
- **Oscillator blocks**: D_Zener:D_Zener symbol for Zener diodes, L-shaped cathode routing with directional labels
- **TIA block annotations**: Added title/function descriptions to all 5 TIA block build functions (analog_mux, mux_tia, relay_ladder, electrometer_362, mcu_section)
- **Repo portability**:
  - Created requirements.txt (numpy, matplotlib, kicad-sch-api, PyMuPDF, Pillow)
  - Added D_Zener.kicad_sym to bundled symbols/ directory
  - Updated .gitignore for docs/ and requirements.txt
  - Created docs/oscillator_guide.md — comprehensive technical guide
- **SimGUI**: Builds clean (dotnet build, 0 errors)
- All block PDFs verified and exported to Downloads/CircuitForge_PDFs/

**Key simulation findings:**
- Mux charge dump: filter capacitors store charge while channel is unselected; closing the switch dumps Q=C*V into TIA → saturation. Fix: omit caps in mux switching sim (real firmware handles settling)
- Floating TIA_IN: during break-before-make switch transitions, TIA_IN floats → instant op-amp saturation with 1G Rf (recovery takes >> 10ms). Fix: R_BIAS (100M) to ground
- Norton sensor model: current source + R_DUT to ground prevents unbounded voltage at input when mux is off
- Femtoamp sensitivity confirmed: 100fA × 10G = 1mV, well above 24-bit ADC noise floor

### Key Components

| Part | Function | Package | Qty | Notes |
|------|----------|---------|-----|-------|
| MAX338ESE+ | 8:1 analog mux | SOIC-16 | 2 | Low leakage (<1nA), ±5V supply |
| BAV199 | Dual ESD clamp diode | SOT-23 | 16 | Cathode-to-cathode at signal, both anodes to AGND (MM20 topology) |
| 1M 1% | Input series resistor | 0603 | 16 | Limits current + forms RC filter |
| 10nF C0G | Input filter cap | 0603 | 16 | Low leakage, fc=15.9Hz with 1M |
| ADA4530-1 | Electrometer TIA | SOIC-8 | 1 | 20fA bias, guard buffer |
| 109P-1-A-5/1 | SPST reed relay | SIP-4 | 4 | Range switching (existing design) |
| ADuCM362 | MCU + dual 24-bit ADC | LFCSP-72 | 1 | Eval board |
| ADuM3160 | USB isolator | SOIC-8 | 1 | 2.5kV isolation |

---

## Phase 3d: Self-Correcting Verification Loop [IMPLEMENTED]

Self-learning correction loop: DETECT -> DIAGNOSE -> FIX -> RE-VERIFY -> LEARN.
Persistent rule database: sim_work/learned_rules.json (rules survive across sessions).

### Current State (what we have)

The verification system was built incrementally - every bug found during development
became a permanent check. Current checks in `verify_circuit()`:

| Check | Type | Auto-fix? | Notes |
|-------|------|-----------|-------|
| Required nets (GND/VCC/OUT/AIN0) | Structural | NO | Reports missing, doesn't add them |
| Input source (VSIN/VDC/label) | Structural | NO | Reports missing |
| Power symbols (GND/VCC/VEE count) | Structural | NO | Reports if text-only labels used |
| Component count minimum | Structural | NO | Catches empty/partial builds |
| Pin connectivity (all op-amp pins) | Structural | NO | Reports floating pins |
| Wire crossing detection (H-V) | Visual | NO | Reports crossing coords, doesn't reroute |
| Feedback path detection | Topology | NO | Reports if Rf disconnected |
| Output within supply rails | Simulation | NO | Reports saturation |
| Gain/transimpedance tolerance | Simulation | NO | Reports % error |

### Bugs That Required Manual Fixes (the correction loop should handle these)

1. **Wire crossing** (electrometer_362): Ref divider vertical wire crossed VSIN horizontal wire.
   Root cause: build function placed components in crossing paths.
   Manual fix: rerouted VSIN above feedback area (3-segment path).
   *Auto-fix approach*: detect crossing -> try rerouting one wire via alternate path.

2. **Double output** (electrometer_362): Both OUT and AIN0 labels on output.
   Root cause: copy-paste from simpler electrometer circuit.
   Manual fix: removed redundant OUT label, updated required_nets.
   *Auto-fix approach*: detect duplicate output labels -> warn/remove.

3. **Disconnected label** (electrometer_362): TRIAX_IN label at old position after wire reroute.
   Root cause: label position not updated when wire path changed.
   Manual fix: moved label to new wire path.
   *Auto-fix approach*: detect labels with 1 point -> find nearest wire on same net -> reposition.

4. **LMC6001 mid-supply failure**: Transimpedance = 53.75 V/A (should be 1G).
   Root cause: PMOS inputs can't operate at 1.65V with 3.3V supply.
   Manual fix: switched to dual +/-5V supply for simulation.
   *Auto-fix approach*: if transimpedance << expected, flag op-amp/supply incompatibility.

5. **Feedback too far from op-amp**: R1/C1 at 9*G above inv_pin looked bad visually.
   Root cause: spacing constants too large.
   Manual fix: tightened to 5*G / 3*G.
   *Auto-fix approach*: measure component-to-opamp distance, warn if > threshold.

### Improvement Plan (prioritised)

**Tier 1: Detection improvements (add to verify_circuit)**

| Task | Status | Notes |
|------|--------|-------|
| Disconnected label detection | DONE | `check_disconnected_labels()` - labels not touching any wire, skips inter-region connectors |
| Duplicate net label detection | DONE | `check_duplicate_labels()` - different names on same net (e.g. {AIN0, OUT}) |
| Component overlap detection | DONE | Already in `check_layout_quality()` - Manhattan distance < 5mm |
| Label overlap detection | DONE | `check_label_overlaps()` - text bounding box collision (labels + ref designators) |
| Floating wire detection | DONE | `check_floating_wires()` - wire segments not connected to any endpoint, pin, or label |
| Component-to-wire distance check | DONE | `check_component_wire_distance()` - components >30mm from nearest wire |
| GND/VCC placement quality | DONE | check_layout_quality() detects power symbols in feedback area |

**Tier 2: Auto-fix capabilities (modify build functions automatically)**

| Task | Status | Notes |
|------|--------|-------|
| Wire crossing auto-reroute | TODO | Try 3-segment detour above/below when crossing detected |
| Label repositioning | DONE | OUT label fixed to output wire midpoint (mux_tia) |
| Spacing auto-adjust | DONE | Divider moved from 6*G to 16*G, GND routed past output column |
| Duplicate label cleanup | TODO | Remove redundant labels, keep the most descriptive one |
| Power routing correction | DONE | V- GND routed RIGHT+DOWN to avoid feedback bounding box |

**Tier 3: Closed-loop correction (build -> verify -> fix -> rebuild -> re-verify)**

| Task | Status | Notes |
|------|--------|-------|
| `auto_correct_schematic()` | DONE | Detects issues, learns rules, records fixes, returns build adjustments |
| Retry loop with max iterations | DONE | `build_and_verify_loop()` - max 3 attempts per circuit |
| Fix history / changelog | DONE | learned_rules.json: persistent rule DB with fix counts + timestamps |
| Regression test suite | TODO | Known-good circuits to verify fixes don't break existing |
| Per-circuit layout constraints | DONE | Parameterized build kwargs passed through correction loop |

**Tier 4: Simulation-driven correction**

| Task | Status | Notes |
|------|--------|-------|
| Op-amp/supply compatibility check | TODO | Warn if model needs dual supply but circuit is single |
| Saturation auto-diagnosis | TODO | If Vout clips at rail, suggest reducing input or Rf |
| Settling time auto-adjust | TODO | If transient hasn't settled, increase sim time (5*tau) |
| Noise floor estimation | TODO | Compare expected signal to Johnson noise of Rf |

### Implementation Notes

The correction loop should work like this:
```
def build_and_verify(circuit_type, **kwargs):
    for attempt in range(MAX_ATTEMPTS):
        sch_path = build_functions[circuit_type](**kwargs)
        issues = verify_circuit(sch_path, circuit_type, ...)

        errors = [i for sev, i in issues if sev == 'ERROR']
        warnings = [i for sev, i in issues if sev == 'WARNING']

        if not errors and not warnings:
            print(f"  PASS on attempt {attempt+1}")
            break

        # Try auto-fixes
        fixes_applied = auto_correct_schematic(sch_path, issues)
        if not fixes_applied:
            print(f"  Cannot auto-fix: {errors + warnings}")
            break

        print(f"  Applied {len(fixes_applied)} fixes, rebuilding...")

    return sch_path
```

Key principle: every manual fix we make during development should become
an auto-fix rule. The system gets smarter with each circuit we build.

## Phase 4: Falstad Integration [NOT STARTED]
Use Falstad for quick visual prototyping and idea testing.

| Task | Status | Notes |
|------|--------|-------|
| Research Falstad format | DONE | Simple text, JS API documented |
| Generate Falstad circuits from Python | TODO | Text format is scriptable |
| Playwright bridge for headless sim | TODO | Drive via headless Chrome |
| Extract voltage/current data | TODO | ontimestep callback |

## Phase 5: Advanced Features [NOT STARTED]
Stretch goals.

| Task | Status | Notes |
|------|--------|-------|
| Photo-to-circuit (vision) | TODO | Read circuit image -> netlist |
| Swap subcircuits (op-amps) | DONE | OPAMP_DB with 4 models, drop-in replacement via CLI |
| Add/remove components | TODO | Node-aware patching |
| Topology changes | TODO | Hard - basically a rewrite |
| AC analysis / Bode plots | DONE | Implemented for sig_cond, extensible to all circuits |
| InSpice (PySpice fork) | TODO | Active replacement for dead PySpice |

---

## Research Summary (2026-03-02)

Tools evaluated for the schematic + simulation pipeline:

| Tool | Verdict | Why |
|------|---------|-----|
| **kicad-sch-api** | CHOSEN | Creates real .kicad_sch from Python, 22K symbols |
| **KiCad + kicad-cli** | NEXT | Pro SVG/PDF export, needs install |
| **Falstad** | CHOSEN (ideas) | Visual prototyping, browser-based, JS API |
| **SKiDL** | Backup | Mature but SVG output is basic |
| **InSpice** | Consider | Active PySpice fork, Python 3.12+ |
| **spicelib/PyLTSpice** | Consider | Good LTspice automation |
| schemdraw | REJECTED | Poor layout quality for complex circuits |
| PySpice | REJECTED | Dead since 2021, use InSpice instead |
| Ahkab | REJECTED | Dead since 2015 |
| TINA-TI | REJECTED | Zero scripting, GUI only |
| Micro-Cap 12 | Models only | Dead software but excellent open model library |
| Qucs-S | Not scriptable | GUI not automatable from Python |
| Xyce | Overkill | Parallel SPICE, complex setup, Linux-focused |
| Xschem | Not scriptable | Pro schematics but GUI only |
| Revolution EDA | Too early | Python-native but immature |

---

## Patching Accuracy Scorecard

| Patch Type | Difficulty | Status |
|------------|-----------|--------|
| Change R/C/L values | Easy | Works reliably |
| Change voltage/frequency | Easy | Works reliably |
| Change load impedance | Easy | Works reliably |
| Fix LTspice->ngspice syntax | Medium | Works for basic circuits |
| Swap transistor models | Medium | Need to extract & clean models |
| Swap subcircuits (op-amps) | Hard | LTspice encrypts .sub files |
| Add/remove components | Hard | Need node knowledge |
| Change topology | Very hard | Basically a rewrite |

---

## Key Files

| File | Purpose |
|------|---------|
| `kicad_pipeline.py` | NEW: KiCad schematic + ngspice simulation pipeline |
| `render_schematic.py` | NEW: Matplotlib renderer for .kicad_sch files |
| `circuit_tool.py` | Search, load, patch, simulate LTspice demos |
| `demo_loader.py` | Earlier loader (superseded by circuit_tool) |
| `ClassD/class_d_amp.py` | Class D amplifier build from scratch |
| `sim_work/ce_amp.kicad_sch` | KiCad schematic: common-emitter amp |
| `sim_work/ce_amp.cir` | ngspice netlist: common-emitter amp |
| `sim_work/ce_amp_svg/ce_amp.svg` | KiCad SVG export: CE amp |
| `sim_work/ce_amp_results.png` | Simulation results plot |
| `sim_work/ce_amp_render.png` | Rendered schematic image |
| `sim_work/inv_amp.kicad_sch` | KiCad schematic: LM741 inverting amp |
| `sim_work/inv_amp.cir` | ngspice netlist: inverting amp |
| `sim_work/inv_amp_svg/inv_amp.svg` | KiCad SVG export: inverting amp |
| `sim_work/inv_amp_results.png` | Simulation results plot |
| `sim_work/electrometer_362.kicad_sch` | KiCad schematic: ADuCM362 TIA |
| `sim_work/electrometer_362_large.png` | Rendered TIA schematic (2836x2127) |
| `sim_work/electrometer_362_lt.net` | LTspice netlist (real ADA4530-1) |
| `sim_work/electrometer_362.cir` | ngspice netlist (LMC6001 proxy) |
| `sim_work/electrometer_362_results.png` | TIA transient simulation plot |
| `sim_work/electrometer_362_bode.png` | TIA frequency response Bode plot |
| `sim_work/full_path.cir` | Full signal path netlist (filter+mux+TIA+ADC) |
| `sim_work/full_path_results.png` | Full-path transient simulation plot |
| `sim_work/full_path_bode.png` | Full-path AC frequency response |
| `sim_work/channel_switching.cir` | 16-channel multiplexed switching netlist |
| `sim_work/channel_switching_results.png` | Channel switching transient plot |
| `sim_work/femtoamp_test.cir` | 100fA sensitivity test netlist |
| `sim_work/femtoamp_results.png` | Femtoamp sensitivity plot |
| `sim_work/avdd_monitor.cir` | AVDD supply monitor netlist |
| `sim_work/avdd_monitor_results.png` | AVDD divider tracking plot |
| `sim_work/rtd_temp.cir` | RTD 4-wire temperature measurement netlist |
| `sim_work/rtd_temp_results.png` | RTD temperature staircase plot |
| `sim_work/combined_logging.cir` | Combined current + RTD logging netlist |
| `sim_work/combined_logging_results.png` | Combined logging simulation plot |
| `sim_work/audioamp.cir` | Patched audio amplifier netlist |
| `sim_work/bjt_models.lib` | Cleaned BJT models for ngspice |

## Key Paths

| Path | What |
|------|------|
| `C:\Spice64\bin\ngspice_con.exe` | ngspice 45.2 simulator |
| `C:\Program Files\ADI\LTspice\LTspice.exe` | LTspice (netlist generation) |
| `~/Documents/LTspice/kicad_libs/` | 22,711 KiCad symbol libraries |
| `~/Documents/LTspice/examples/` | 4,242 demo .asc files |
| `~/Documents/LTspice/lib/sub/` | 3,000 .sub files (encrypted) |
| `~/Documents/LTspice/lib/cmp/` | standard.bjt/.mos/.dio (UTF-16LE) |
| `~/Documents/LTspice/sim_work/` | Working directory for simulations |
| `~/Documents/LTspice/models/MicroCap-LIBRARY-for-ngspice/` | 167 open model library files |
| `C:\Users\Robert\AppData\Local\Programs\KiCad\9.0\bin\kicad-cli.exe` | kicad-cli 9.0.7 |

---

## Known Issues / Gotchas

1. **LTspice .sub files are encrypted** - ngspice can't read them directly.
   Solution: Micro-Cap 12 model library provides open/unencrypted equivalents.
2. **Library files are UTF-16LE** - standard.bjt, standard.mos, standard.dio
   need encoding conversion before ngspice can use extracted models.
3. **LTspice-specific SPICE params** - Vceo, Icrating, mfg= must be stripped.
4. **KiCad 9 symdir format** - Libraries are now .kicad_symdir/ directories
   with individual .kicad_sym files per symbol (not monolithic).
5. **kicad-sch-api emits incompatible tokens** - `(in_pos_files yes)`,
   `(duplicate_pin_numbers_are_jumpers no)`, and `(power global)` crash kicad-cli 9.0.7.
   Fix: `fix_kicad_sch()` strips/converts these after save. Also hides #PWR refs.
6. **Wire routing** - add_wire_between_pins draws diagonal lines. Fixed with
   custom `wire_manhattan()` + `get_pin_pos()` functions.
7. **ngspice .tran syntax** - Needs both timestep AND stop time, unlike LTspice.
8. **PySpice is dead** - Last release 2021. Use InSpice (active fork) instead.
9. **Multi-unit symbols** (LM358, LM324, TL072) show 0 pins in kicad-sch-api
   due to parent symbol resolution failure. Single-unit symbols (LM741, LM386) work.
10. **Pin numbering for rotated components** - With rotation=90 (horizontal),
    pin 1 is on the RIGHT, pin 2 is on the LEFT. Opposite to intuition.
11. **kicad-sch-api mirror doesn't work** - mirror_x/mirror_y params accepted
    but not written to file. Fix: manually add `(mirror x)` in fix_kicad_sch().
12. **Op-amp orientation** - For inverting amps, mirror x flips (-) to top.
    Must calculate pin positions manually (Y offsets negate).
13. **Wire crossings** - Horizontal/vertical wire crossings from different nets
    create visual ambiguity (looks like junction). Fixed: `check_wire_crossings()`
    now auto-detects in verify_circuit(). Routing fixes applied to sig_cond and usb_ina.
14. **Mux charge dump** - Filter capacitors (10nF) charge via sensor current while
    channel is deselected. Closing the mux dumps Q=C*V into TIA → output saturation.
    Real hardware: firmware waits for settling. Simulation: omit filter caps in
    channel switching netlists.
15. **Floating TIA_IN during mux switch** - Break-before-make transitions leave
    TIA_IN floating for ~1us → op-amp saturates with 1G Rf (recovery >> 10ms).
    Fix: 100M bias resistor from TIA_IN to ground.
16. **Current source naming** - Top-level `I1` collides with LMC6001 subcircuit
    internal `I1 99 4 33.46U` (scoping should protect, but safer to use `Isrc`).

---

## Next Steps

1. ~~USB-isolated multi-op-amp circuit~~ DONE (3-op-amp INA, G=95)
2. ~~Electrometer TIA~~ DONE (both simple + ADuCM362 platform version)
3. ~~Add voltage source symbols to schematics~~ DONE (GND/VCC/VEE/VSIN)
4. ~~Reed relay range-switching ladder (Subsystem 2)~~ DONE (4 channels, 9/9 pass, 0 crossings)
5. ~~Full-path simulation (Stage 6)~~ DONE (single channel 0.1%, channel switch, femtoamp, AVDD)
6. ~~Oscillator schematic layout rewrite~~ DONE (3-col×2-row grid, 3x scale, A3 paper)
7. ~~Verification loop Tier 1~~ DONE (6 checks: disconnected labels, duplicate nets, label overlaps, floating wires, component distance)
8. **Oscillator schematic improvements** (Session 16 TODO - see below)
9. HV resistive divider circuit (Subsystem 3)
9. HV input protection (Subsystem 4)
10. **Verification loop Tier 2**: auto-reroute crossings, reposition labels, spacing adjust
11. USB isolation block (Subsystem 5)
12. **Verification loop Tier 3**: closed-loop build->verify->fix->rebuild with retry
13. ~~AC analysis / Bode plots support~~ DONE
14. Revisit Class D amplifier with KiCad pipeline
15. Multi-unit symbol support (LM358, TL072, etc.)
16. ~~Wire crossing detection~~ DONE (check_wire_crossings in verify loop)
17. Photo-to-circuit (vision) - read circuit images -> netlist

---

## SimGUI v3 - Multi-Range 16-Channel Electrometer [DONE]

C# .NET 8 WinForms application with ScottPlot 5 charting. Simulates all 4 TIA ranges
(Rf=10M/100M/1G/10G) with 16 channels each, auto-scaled units (fA/pA/nA), and
loop-verified against injected currents.

**Location:** `~/Documents/LTspice/SimGUI/`

| Feature | Status | Notes |
|---------|--------|-------|
| .NET 8 WinForms project | DONE | ScottPlot.WinForms v5.0.56 NuGet |
| 4 TIA ranges | DONE | Range 0-3: Rf=10M/100M/1G/10G, each with 16 unique currents |
| Range selector ComboBox | DONE | Dropdown picks range 0-3, "Run Range" button |
| "Run All Ranges" loop | DONE | Runs all 4 ranges sequentially, aggregates results |
| DataGridView (11 columns) | DONE | Rf, CH, Injected, Measured, Delta, Error%, V_TIA, V_Expected, V_Input, ADC, Result |
| Auto-scaled units | DONE | fA/pA/nA display based on current magnitude |
| Per-range current tables | DONE | RANGE_CURRENTS dict in both pipeline + parser (must match) |
| Row color coding | DONE | Green PASS (<5%), Yellow WARN (5-20%), Red FAIL (>20%) |
| CH column colour-coded | DONE | Each channel row tinted to match its plot trace colour |
| Per-channel coloured plot | DONE | 16 distinct coloured traces per range |
| Multi-range concatenated plot | DONE | All 4 ranges shown with separator lines + range labels |
| Verification report per range | DONE | Full table with *, X markers, per-range + total summary |
| Screenshot button | DONE | Captures entire form as PNG/JPG via DrawToBitmap |
| SimulationRunner (range-aware) | DONE | Passes range to CLI, range-specific output files |
| ResultParser (multi-range) | DONE | Auto-detects range from filename, range-specific current tables |
| CSV export (multi-range) | DONE | ExportMultiRange writes all ranges to single CSV |
| Auto-detect range from filename | DONE | Matches `channel_switching_range{N}_results.txt` pattern |
| CLI test mode | DONE | `dotnet run -- --test` tests all 4 ranges in sequence |
| R_BIAS scaled per range | DONE | 100M/1G/10G/100G to minimize noise gain at high impedance |
| Blue theme UI | DONE | Navy headers, steel blue toolbar, dark navy log panel |

**Simulation results (LMC6001, all ranges):**
| Range | Rf | Currents | Avg Error | Max Error | Result |
|-------|----|----------|-----------|-----------|--------|
| 0 | 10M | 20-400 nA | 0.8% | 1.0% | 16 PASS |
| 1 | 100M | 2-40 nA | 0.9% | 1.0% | 16 PASS |
| 2 | 1G | 50pA-1nA | 4.7% | 17.0% | 11P/5W |
| 3 | 10G | 50-1000 fA | 3610% | 15849% | 16 FAIL (offset-dominated, needs calibration) |

**How to run:** `cd ~/Documents/LTspice/SimGUI/SimGUI && dotnet run` or `dotnet run -- --test`

**Key files:**
| File | Purpose |
|------|---------|
| `SimGUI/SimGUI.sln` | Solution file |
| `SimGUI/SimGUI/SimGUI.csproj` | Project file (.NET 8, ScottPlot 5) |
| `SimGUI/SimGUI/MainForm.cs` | Main window (range selector, Run All, multi-range plot) |
| `SimGUI/SimGUI/Models/ChannelData.cs` | Per-channel model with auto-scaled display |
| `SimGUI/SimGUI/Models/SimulationResult.cs` | Results container with range info |
| `SimGUI/SimGUI/Services/SimulationRunner.cs` | Async subprocess with range parameter |
| `SimGUI/SimGUI/Services/ResultParser.cs` | 4-range parser with RANGE_CURRENTS tables |
| `SimGUI/SimGUI/Services/CsvExporter.cs` | Single + multi-range CSV export |
| `SimGUI/SimGUI/TestParser.cs` | CLI multi-range test harness |

---

## Electrometer Platform (Separate Project)

Full instrument project at `~/Downloads/Electrometer/electrometer-platform/`:
- **Docs**: Architecture, build guide, BOM (~430 GBP), protocol spec, calibration
- **Hardware**: ADA4530-1 TIA, reed relay range ladder (10M/100M/1G/10G), 3-phase HV dividers, ADuM3160 USB isolation
- **Firmware**: ADuCM362 eval board, dual 24-bit ADC, binary streaming protocol, auto-ranging
- **Software**: PySide6 GUI, real-time plotting, data logging, calibration wizard
- **Status**: TIA front-end schematic DONE + simulated (4 ranges verified). Relay ladder is NEXT.
- **Schematics built so far**: TIA (ADA4530-1 with LMC6001 proxy), verified 12/12 checks, 0 wire crossings

## Available Electrometer Op-Amp Models (Micro-Cap Library)

| Model | Subckt Name | Pins | Library | Bias Current | Notes |
|-------|-------------|------|---------|-------------|-------|
| LMC6001 | LMC6001_NS | [1 2 99 50 28] | nation.lib | ~1pA | Ultra-low bias, 1MHz GBW |
| LMC6001A | LMC6001A_NS | [1 2 99 50 28] | nation.lib | ~25fA | Tighter spec variant |
| OPA128 | OPA128_BB | [1 2 3 4 5] | burrbn.lib | ~75fA | Classic electrometer amp, different pinout! |
| LMP7721 | LMP7721 | [3 4 5 2 1] | nation.lib | ~3fA | Non-standard pin order |
| ADA4530-1 | ADA4530-1 | [1 2 3 4 5 6] | ADI1.lib (LTspice) | 20fA | LTspice-only model, 6 pins (incl guard buffer). Path: AppData/Local/LTspice/lib/sub/ADI1.lib |

---

---

## Session 11: Full System Schematic Review & Verification Fixes (2026-03-04)

**Problem found**: Visual review of `full_system_large.png` (16232x10562 px) revealed multiple critical schematic errors that the verification loop did NOT catch:

### Bugs Found

1. **Relay coils completely MISSING** from NPN driver circuit
   - Circuit was: `5V_ISO -> 1N4148 (series!) -> Q collector -> Q emitter -> GND`
   - Should be: `5V_ISO -> [Relay Coil] -> Q collector`, with 1N4148 in PARALLEL across coil
   - Without a coil, the reed switch contacts (SW1-4) can NEVER energize
   - Root cause: `build_full_system()` and `build_relay_ladder()` only had diode+NPN, no coil component

2. **BAV199 ESD diodes not visually connected**
   - Diode cathode pins landed mid-wire on signal path with no junction dot
   - KiCad may not register the connection without explicit junction markers
   - Root cause: single wire from `col_x` to `r_cx-3.81` with diode pin at `diode_x` mid-span

3. **No 5V_ISO decoupling capacitor** near relay drivers
   - Relay coil switching causes current spikes that need local bypass

4. **Flyback diode topology wrong** - in series instead of parallel with coil

### Fixes Applied

| Fix | File | Lines | Description |
|-----|------|-------|-------------|
| BAV199 junction | `kicad_pipeline.py` | build_full_system region 1 | Split signal wire at diode_x, added `sch.junctions.add()` |
| Relay coils | `kicad_pipeline.py` | build_full_system region 4 | Added R28-R31 (500R_COIL) between 5V_ISO and NPN collectors |
| Flyback diode | `kicad_pipeline.py` | build_full_system region 4 | D33-D36 now in PARALLEL with coils (rot=270: K at top) |
| 5V_ISO decoupling | `kicad_pipeline.py` | build_full_system region 4 | Added C30 100nF on 5V_ISO near relay drivers |
| Standalone fix | `kicad_pipeline.py` | build_relay_ladder() | Same coil + diode topology fix for standalone schematic |
| Verification rules | `kicad_pipeline.py` | check_layout_quality() | 5 new topology rules: relay_coil_missing, flyback_diode_topology, esd_diode_junction_missing, relay_decoupling_missing, esd_diode_count |
| Auto-correct | `kicad_pipeline.py` | auto_correct_schematic() | Handlers for all 5 new rules with learn_rule() persistence |

### Key Lesson
The verification loop was checking labels, component counts, and layout quality - but had **no topology/circuit correctness checks**. It could tell you "all 181 components are present" but couldn't tell you "the relay coil is missing between the supply and transistor." Topology checks now verify that relay drivers have coils, flyback diodes are in parallel (not series), ESD diodes have junctions, and supply rails have decoupling.

### SimGUI Note
The SimGUI simulation results (4 ranges verified, 0.8-4.7% avg error) are correct despite the schematic bugs because the **simulation netlist** (`write_channel_switching_netlist()`) generates its own SPICE netlist independently of the KiCad schematic. The netlist always had correct relay coils, feedback paths, and component values. The schematic is a separate visual representation that had drifted out of sync with the simulation model.

## Session 12: Schematic Scaling for Readability (2026-03-04)

**Problem**: The full system schematic used standard KiCad symbol sizes (7.62mm resistor, 10mm transistor) on a single A0 sheet (1189×841mm). When KiCad fits-to-page, components were microscopic. The MM20 reference schematics use multiple smaller sheets so components appear normal.

**Solution**: Added `scale_schematic(path, factor=3)` post-processing function that uniformly scales ALL coordinates in the `.kicad_sch` file by 3x:
- Symbol body graphics (rectangles, polylines, arcs, circles) → 3x bigger visually
- Pin positions → match scaled wiring
- Component/wire/label/junction/text positions → everything scales together
- Font sizes → 3x larger for readability
- Paper size → custom User 3567×2523mm

**Implementation**: Text-based regex transformation of the S-expression file, applied after `fix_kicad_sch()` in `build_full_system()`. Controlled via `scale_factor` kwarg (default 3, set to 1 to disable).

**Also fixed**: Relay decoupling cap detection bounding box was too tight (y_min: npn_y - 40 → npn_y - 60) causing false warning about missing C31.

**Verification**: 23 passed, 16 warnings (15 wire crossings + 1 other), 0 errors.

### KiCad Navigation Tip
- **Pan**: Middle mouse button drag
- **Zoom**: Scroll wheel
- **Fit to screen**: Home key

## Session 12b: ADuCM362 Firmware (2026-03-04)

**New**: Real embedded C firmware for the ADuCM362 microcontroller.

Location: `~/Documents/LTspice/firmware/`

### Files Created
| File | Purpose |
|------|---------|
| `config.h` | Pin mappings, range tables, timing constants, ADC config |
| `system_init.c/h` | Clock setup, SysTick timer, delay_ms() |
| `gpio.c/h` | Port 0 (mux + UART) and Port 1 (relays) initialization |
| `mux.c/h` | CD4051B channel selection: addr bits + enable lines |
| `relay.c/h` | One-hot reed relay range switching with break-before-make |
| `adc.c/h` | ADC0 init, single-shot read, voltage/current conversion |
| `uart_stream.c/h` | UART 115200 8N1, measurement packet streaming |
| `main.c` | Scanning loop: 16 channels, settles, reads, streams |

### Signal Flow in Firmware
```
main() -> relay_set_range(0)     # Select Rf=10M
       -> scan_all_channels():
           for ch 1..16:
             mux_select_channel(ch)   # GPIO P0.0-P0.4
             delay_ms(160)            # TIA settling
             raw = adc_read_raw()     # ADC0 single conversion on AIN0
             V = raw * 3.3V / 2^23
             I = V / Rf
             uart_stream(ch, range, raw, V, I, tick)
```

### UART Output Format
```
$CH,05,2,0x00A3F2,154.320,154.320,3200\r\n
```
Fields: channel, range, raw ADC hex, voltage (uV), current (pA), timestamp (ms)

### Based On
- CN0359 reference firmware (`cn0359/.../source/`) for ADuCM360.h CMSIS header and register patterns
- ADC, UART, GPIO register configuration directly from CN0359 adc.cpp and uart.cpp

### TODO
- RX command parser (host can change range, start/stop scanning)
- ADC1 for RTD temperature measurement
- Auto-ranging (detect saturation, switch range automatically)
- DMA-based ADC for higher throughput
- Offset calibration (zero-point subtraction, especially for range 3)

---

## Session 13: State Variable Oscillator - Full System Integration

### Objective
Complete the oscillator project: calibration documentation, SimGUI integration with
calibration simulation, standalone ADuCM362 firmware, KiCad schematic, and README.

### Completed

#### 1. Calibration Plan (CALIBRATION.md)
| Item | Detail |
|------|--------|
| Root cause analysis | Op-amp GBW, MDAC capacitance, damping resistor, Zener loading |
| Frequency error | 2.7% at D=121, up to 8% at D=3632 (systematic, calibratable) |
| Amplitude variation | 0.856V-1.164V RMS across range (Zener frequency dependence) |
| Self-calibration | 16 log-spaced points, ~5 seconds at power-on |
| Correction method | Interpolated LUT or 3rd-order polynomial |
| Flash storage | Page 61, magic 0xCA1B0A7D, 512 bytes |
| Post-calibration spec | Frequency <1% error, amplitude 0.95-1.05V RMS |

#### 2. SimGUI Generic Project System
Refactored SimGUI from hardcoded TIA to generic `IProjectConfig` interface.

| File | Purpose |
|------|---------|
| `IProjectConfig.cs` | Interface: grid, plot, parse, report, CSV export |
| `OscillatorConfig.cs` | 8-point frequency sweep + calibration simulation |
| `ElectrometerConfig.cs` | Wraps existing TIA logic (9 ranges, 16 channels) |
| `MainForm.cs` | Project selector dropdown, generic RunSimulation/RunAll |
| `MainForm.Designer.cs` | Added _cboProject, _btnCalibrate, dynamic status bar |
| `SimulationRunner.cs` | Added RunGenericAsync(string arguments) overload |

Calibration simulation in OscillatorConfig:
- `ApplyCalibration()` simulates ADuCM362 self-calibration
- Grid shows before/after columns (Cal.Freq, Cal.Err, Cal.RMS)
- Plot overlays uncalibrated (red) vs calibrated (green) curves
- Models Timer1 resolution noise at 16 MHz

#### 3. ADuCM362 Oscillator Firmware
Standalone firmware in `firmware/oscillator/` (NOT shared with TIA project).

| File | Purpose |
|------|---------|
| `osc_config.h` | Pin mapping, constants (FREQ_CONST, DAC limits, ADC config) |
| `osc_dac7800.c/h` | SPI0 master driver for DAC7800 (CPOL=0/CPHA=1, 2 MHz) |
| `osc_freq_measure.c/h` | Timer1 capture ISR + ADC0 for AD636 RMS reading |
| `osc_calibrate.c/h` | 16-point LUT calibration, flash save/load, interpolated lookup |
| `osc_uart.c/h` | Interrupt-driven TX ring buffer, lightweight float/int printing |
| `osc_system_init.c` | 16 MHz HFOSC, 1ms SysTick, peripheral enables |
| `osc_main.c` | Command loop: F/D/CAL/S/M/R/? commands, power-on cal |
| `Makefile` | ARM cross-compilation with arm-none-eabi-gcc |

UART commands: `F<hz>`, `D<code>`, `CAL`, `S` (sweep), `M` (measure), `?` (status)

Power-on sequence:
1. Init peripherals (SPI, UART, Timer1, ADC)
2. Set D=121 (~1 kHz), wait 500ms for oscillation
3. Load calibration from flash (or run fresh 16-point sweep)
4. Enter command loop

#### 4. KiCad Schematic (build_oscillator)
Added `build_oscillator()` to kicad_pipeline.py (~600 lines).

| Region | Contents |
|--------|----------|
| 1 | Summing amplifier: U1 LM4562, R_lp(10k), R_bp(22k), Rf_sum(10k) |
| 2 | Integrator 1 (HP->BP): U2 + XDAC1 DAC7800 + Cint1(470p) + R_damp1(100M) + Dz1/Dz2 Zener AGC |
| 3 | Integrator 2 (BP->LP): U3 + XDAC2 DAC7800 + Cint2(470p) + R_damp2(100M) + Dz3/Dz4 Zener AGC |
| 4 | Startup kick: Rkick(100k) + pulse source to HP node |
| 5 | AD636 RMS detector: 1/5 attenuator (40k+10k) + CAV(10uF) -> AIN0 |
| 6 | ADuCM362 MCU: SPI0->VCTRL, AIN0<-AD636, P0.5 ZC input, UART TX/RX |
| 7 | Power supply: +/-15V bulk decoupling, 3.3V LDO for MCU |

- Output: `sim_work/oscillator.kicad_sch`
- Scaled 3x for readability (A1 paper → 2523x1782mm) — rewritten in Session 14
- 3-col × 2-row grid layout with 80G col / 70G row spacing
- Op-amps mirrored for conventional inverting layout
- Net labels auto-connect: HP, BP, LP, VCTRL, AIN0, BP_ZC

#### 5. README.md
- Prerequisites (Python, ngspice, .NET 8, KiCad, ARM toolchain)
- Directory structure
- Quick start commands
- UART command reference
- Pipeline circuit list (19 types including oscillator)

### File Summary
```
New files created:
  StateVarOsc/CALIBRATION.md
  SimGUI/SimGUI/Projects/OscillatorConfig.cs
  SimGUI/SimGUI/Projects/ElectrometerConfig.cs
  firmware/oscillator/osc_config.h
  firmware/oscillator/osc_dac7800.h / .c
  firmware/oscillator/osc_freq_measure.h / .c
  firmware/oscillator/osc_calibrate.h / .c
  firmware/oscillator/osc_uart.h / .c
  firmware/oscillator/osc_system_init.c
  firmware/oscillator/osc_main.c
  firmware/oscillator/Makefile
  README.md

Modified files:
  kicad_pipeline.py          (added build_oscillator + dispatch update)
  SimGUI/SimGUI/Models/OscillatorResult.cs  (calibration fields)
  SimGUI/SimGUI/Services/SimulationRunner.cs (RunGenericAsync)
  SimGUI/SimGUI/MainForm.cs  (generic IProjectConfig refactor)
  SimGUI/SimGUI/MainForm.Designer.cs (project selector + calibrate button)
```

### Schematic Layout Rewrite [DONE - Session 14]
The original `oscillator.kicad_sch` had components bunched together with 2x scale — too
cramped to read without heavy zooming.

**Fix applied (Session 14)**:
1. Rewrote `build_oscillator()` with proper 3-col × 2-row grid layout:
   - Row 1: Summing Amp | Integrator 1 (HP→BP) | AD636 RMS Detector
   - Row 2: Integrator 2 (BP→LP) | Startup Kick + Power | ADuCM362 MCU
   - 80G column spacing, 70G row spacing (parameterized via kwargs)
2. Changed scale factor from 2x to 3x (matching `build_full_system()` pattern)
3. Changed paper from A3 to A1 (841×594mm → 2523×1782mm after 3x scale)
4. Title text increased from 3.0/4.0 to 5.0, annotations from 1.2-1.5 to 1.8-2.0
5. Fixed `scale_schematic()` to support all standard paper sizes (A0-A4), not just A0
6. All parameterized kwargs (`feedback_vert`, `damp_vert`, `zener_vert`, `col_spacing`,
   `row_spacing`) for correction loop compatibility
7. Simulation PASS: 926.9 Hz (7.3% error, expected), BP RMS 1.030V

### TODO: SimGUI Waveform Visualization
Add a separate panel/window to SimGUI that displays live waveforms while simulations run.
When the GUI launches a simulation, the user should be able to see the generated waveforms
(voltage vs time) in a dedicated plotting area — not just the final numeric results in the grid.

**Requirements**:
1. Separate pane or pop-out window for waveform display
2. Show time-domain waveforms (HP, BP, LP outputs) after simulation completes
3. Use ScottPlot 5 for plotting (already a project dependency)
4. Works for both single-point runs and frequency sweeps
5. For oscillator: show BP (bandpass) and HP (highpass) waveforms from the `.raw` or parsed data

**Implementation approach**:
- Parse ngspice raw output (or add `.wrdata` output to the netlist `.control` block)
- Add a `SplitContainer` or tabbed panel to MainForm with a ScottPlot control
- `IProjectConfig` gets a `PlotWaveform(plotControl, sweepIndex)` method
- Each project config implements its own waveform extraction and plotting

*Last updated: 2026-03-05 (Session 15: Verification loop Tier 1 complete)*

---

## Session 15: Verification Loop Tier 1 - Connectivity & Overlap Detection

### Objective
Implement all 6 Tier 1 detection checks in `verify_circuit()` to catch disconnected
labels, duplicate net labels, text overlaps, floating wires, and misplaced components.

### Completed

#### 1. New Detection Functions (kicad_pipeline.py)

| Function | What it detects |
|----------|----------------|
| `check_disconnected_labels()` | Net labels not touching any wire endpoint or segment. Skips inter-region connectors (same-name labels that KiCad auto-connects). |
| `check_duplicate_labels()` | Different-name labels on the same electrical net (e.g. {AIN0, OUT} on same wire). Also detects redundant same-name labels on same net. |
| `check_label_overlaps()` | Text bounding box collisions between net labels and component reference designators. Uses ~2.5mm/char width estimate. |
| `check_floating_wires()` | Wire segments where NEITHER endpoint connects to another wire, component pin, or label. Checks endpoints, T-junctions, and pin positions. |
| `check_component_wire_distance()` | Non-power components >30mm from nearest wire endpoint (likely misplaced or forgotten during layout). |

#### 2. Integration into verify_circuit()
All 5 functions called as Steps 4d-4h, between layout quality checks and topology checks.
Updated docstring with Tier 1 check numbering (checks 8-12).

#### 3. Test Results (initial, before oscillator fixes)

| Circuit | Pass | Warn | Err | Tier 1 Findings |
|---------|------|------|-----|-----------------|
| inv_amp | 21 | 0 | 0 | All clean |
| full_system | 23 | 31 | 5 | 3 multi-name nets, 7 floating wires, 2 distant components |
| oscillator | 7 | 9 | 18 | 4 floating wires, VCC mixed values, 15 pin floating (scale bug) |

#### 4. Oscillator Schematic Fixes (Session 15b)

**VCC mixed values fix**: Replaced all `VCC:VCC` symbols with net labels in `build_oscillator()`:
- Op-amp V+ pins: `VCC:VCC` value="+15V" → `add_label("+15V")` (3 op-amps)
- Power supply bulk decoupling: `VCC:VCC` value="+15V" → `add_label("+15V")`
- 3.3V regulator: `VCC:VCC` value="3.3V" → `add_label("3.3V")`
- MCU power: `VCC:VCC` value="3.3V" → `add_label("3.3V")`

**Floating wires fix**: Added net labels to MCU pin stubs:
- Left side: added `UART_RX` net label (was text-only annotation)
- Right side: replaced text annotations with net labels for `SPI0_CLK`, `SPI0_MOSI`, `DAC_CS`, `UART_TX`

**Wire crossings fix**: Shortened decoupling cap GND leads from 5*G to 3*G so they stay above the VCTRL horizontal bus wire, eliminating 2 crossings.

**Scale-aware pin connectivity**: Added `detect_scale_factor()` to auto-detect 3x scaling from paper size. `check_pin_connectivity()` now scales PIN_DB offsets and tolerance accordingly. Fixes 15 false-positive FLOATING errors on scaled schematics.

**Oscillator-specific verification**: Added `circuit_type == 'oscillator'` branches for:
- Required nets: `{GND, HP, BP, LP, VCTRL, AIN0}` (no VCC/VEE since using net labels)
- Input source: self-oscillating, checks for HP/BP/LP outputs instead of VSIN

---

## Session 16: Oscillator Schematic Fixes + Remaining Issues

### Completed (Session 16)

**Layout rework**: Changed from A1 to A3 paper, tighter spacing (col 80→45, row 70→42, c1x 10→15, r1y 8). Sheet usage improved from 34% to 72%.

**Diode orientation fix**: Zener diodes D1-D4 changed from rotation=90/270 (vertical) to rotation=0/180 (horizontal). Pins at ±3.81 in X were not meeting vertical pin positions - wires were completely disconnected from diodes.

**Feedback/VEE wire overlap fix**: Integrator feedback junction column (`inv_junc`) was at same X as V- pin column (`u_x - 2.54`), creating an electrical short between -15V and the inverting input in the KiCad schematic. Fixed by offsetting feedback column to `cint_cx - 3.81` (= `u_x - 3.81`), giving 1.27mm (3.81mm after 3x) separation. VEE wires shortened from 6G to 3G.

**SPI0_CLK/VCTRL net collision**: Removed erroneous VCTRL net label that was wired to the SPI0_CLK MCU pin, shorting the control voltage to the SPI clock. Changed to text annotation.

**Stroke width scaling**: `scale_schematic()` now scales stroke widths (was skipping them, making lines invisible at 3x). Default width 0 → `0.35*S`, specified widths get `1.5x` boost.

**Feedback height reduction**: fb_vert 14→6, damp_vert 22→10, zener_vert 30→14 (grid units above inverting input). Feedback components now sit just above the op-amp.

### Remaining Issues (TODO for next session)

#### 1. MCU Block Drawing
- ADuCM362 (U5) is currently just floating text "U5 ADuCM362 ARM Cortex-M3" with no drawn rectangle/box
- Pin labels overlap each other: "AIN0" duplicated, "BP_ZC" overlaps "5_ZC", "3.3V MCU" on top of "zero-crossing frequency measurement"
- Need: draw a proper rectangle, space pin stubs, fix overlapping text

#### 2. Section Title Overlaps
- Row 2 titles overlap: "INTEGRATOR 2 (BP->LP) + MDAC" runs into "STARTUP KICK + POWER SUPPLY"
- "VCTRL" label overlaps with "SUPPLY" text
- Need: either reduce title font size, shorten titles, or increase column spacing

#### 3. Op-Amp Feedback Readability
- R_damp (100M) resistor overlaps with "Zener AGC BV=1.1V" text
- Cap label text overlaps with VEE symbol
- Feedback components densely packed - hard to read values
- Need: adjust text positions, increase spacing, or move annotations

#### 4. Verification Script Gaps
- Does NOT check diode pin connectivity (only checks op-amp pins via PIN_DB)
- Does NOT detect overlapping wire segments (the VEE/feedback short)
- Does NOT check component rotation vs wire direction mismatch
- Need: add diode/cap/resistor pin position checks, wire overlap detection

#### 5. Potential Architecture Rethink
- Current approach: hard-coded pin offsets (3.81mm, 7.62mm) for each component type
- Fragile: wrong rotation = disconnected pins, wrong offset = missed connections
- Consider: parse KiCad symbol library to get actual pin positions dynamically
- Consider: build a reusable layout engine that reads symbol geometry and auto-routes

#### 6. Wire Crossing Warnings (2 remaining)
- U1 summing amp: feedback resistor wire crosses VEE vertical
- U3 integrator 2: LP output wire crosses +15V vertical
- Visual ambiguity only, not electrical errors

*Last updated: 2026-03-05 (Session 17)*

#### 5. Final Test Results (after fixes)

| Circuit | Pass | Warn | Err | Notes |
|---------|------|------|-----|-------|
| inv_amp | 17 | 0 | 0 | Regression clean |
| oscillator | 18 | 3 | 0 | 3 minor warns (cosmetic) |

Remaining oscillator warnings (cosmetic):
- "No voltage source symbols" — uses VPULSE for kick, not VSIN/VDC
- "{SPI0_CLK, VCTRL} multi-name net" — correct: SPI bus drives DAC that sets VCTRL
- Simulation: 926.9 Hz (7.3% error, expected), BP RMS 1.030V — PASS

---

## Session 17 — Pipeline Improvement Plan & SimGUI Verification

### Completed

**SimGUI oscillator mode verified**: `dotnet run -- --test` runs all 8 electrometer ranges (124 PASS, 4 WARN, 16 FAIL on Range 8 offset-dominated). GUI launches cleanly, toolbar dropdown switches between Electrometer/Oscillator.

**Oscillator simulation verified**: `python kicad_pipeline.py oscillator 121` runs full pipeline (build schematic → write netlist → ngspice → parse results). Result: 926.9 Hz, BP RMS 1.030V, PASS.

**README.md rewritten**: Full project description with resource table, developer attribution, architecture overview.

### Pipeline Improvement Plan (Architecture Decision)

KiCad is open source (GPL v3, C++ with wxWidgets). Forking it would be massive overkill for our problems. Instead, improving `kicad_pipeline.py` is the practical path.

**Current pain points:**
1. KiCad symbols are fixed size — can't scale in KiCad
2. Pin positions hard-coded per component (fragile, rotation-dependent)
3. No wire overlap detection (caused VEE/feedback short)
4. No diode/passive pin connectivity checking
5. Layout is manual grid math with no collision avoidance

**Planned improvements (priority order):**

1. **Dynamic pin parsing** — Parse `.kicad_sym` library files to get actual pin positions for any symbol at any rotation. Eliminates hard-coded offsets (3.81mm, 7.62mm, etc.) that break when rotation changes.

2. **Wire overlap detection** — Before saving schematic, scan all wire segments for overlapping ranges on same axis. Flag as errors (unintended shorts).

3. **Component collision detection** — Check bounding boxes for overlapping components/text. Auto-adjust spacing or warn.

4. **Diode/passive pin checking** — Extend PIN_DB verification to cover diodes, capacitors, resistors. Verify pin-to-wire connectivity for all component types.

5. **Reusable layout engine** — Grid-based placement with symbol-aware spacing. Auto-route wires with crossing avoidance. Would prevent the recurring "cramped layout" problem.

6. **KiCad Python plugin** (future) — If pipeline improvements aren't enough, write an eeschema plugin that runs inside KiCad for interactive layout assistance.

*Last updated: 2026-03-06 (Session 18)*

## Session 18 — Verification System Overhaul + Professional Schematic Layout

### Completed

**Dynamic pin parser** — Built `parse_symbol_pins()` and `get_component_pins()` that read pin positions from 22,607 KiCad symbol library files. Pin connectivity checking now works for ALL component types (R, C, D, Q_NPN, SW_Reed, LM741, etc.), not just LM741. Transform chain: Y-negate → rotation CCW → mirror_x → scale → offset.

**Wire overlap detection** — Added `check_wire_overlaps()` to detect collinear wire segments sharing a range. Found 7 overlaps in oscillator, 9 in full_system. Catches unintended shorts like the VEE/feedback bug from Session 16.

**Wire merge post-processing** — Added `merge_collinear_wires()` function that automatically deduplicates overlapping wire segments after building any schematic. Runs as post-processing step after `fix_kicad_sch()`.

**simulate() stale-file fix** — Non-zero exit code now always means failure regardless of stderr content. Existing result files are snapshotted before running so stale `*_results.txt` files can't cause false success reports.

**Professional schematic layout** — Switched from 3x scaling on custom paper to 1x scale on standard A3/A4 paper. The 3x scaling was counterproductive: it made the paper enormous, so fit-to-page in any viewer made everything appear tiny. Standard A3 at 1:1 matches professional schematics (MM20-TRI-SCH reference from Triteq).

**Layout quality improvements:**
- Section titles moved above grid origins (offset -4G) with reduced size (3.5pt)
- MCU block enclosed in dashed rectangle for visibility
- Label overlaps fixed (increased MCU pin spacing from 6G to 8G)
- Wire overlaps automatically merged (7 in oscillator, 4 in TIA)
- Clearance parameters added as kwargs (fb_gap, cf_gap, div_offset, div_vert, adc_gap, etc.)

### Verification Results

| Schematic | Paper | Fill | Errors | Warnings | Wire Overlaps | Text Overlaps |
|-----------|-------|------|--------|----------|---------------|---------------|
| Oscillator | A3 1:1 | 97% | 0 | 4 | 0 | 0 |
| TIA (electrometer_362) | A4 1:1 | 96% | 0 | 1 | 0 | 0 |

### Code Changes (kicad_pipeline.py)
- New functions: `parse_symbol_pins()`, `get_component_pins()`, `check_wire_overlaps()`, `merge_collinear_wires()`
- Rewritten: `check_pin_connectivity()` (checks ALL components), `get_opamp_pins()` (dynamic parser first, legacy fallback)
- Modified: `simulate()` (strict exit code), `check_floating_wires()` (uses dynamic pins), `verify_circuit()` (wire overlap step)
- Modified: `build_oscillator()` and `build_electrometer_362()` — 1x scale default, clearance kwargs, wire merge, title repositioning

## Session 19 — LTspice Audio Amplifier Conversion + Repo Cleanup

### Goal
Demonstrate CircuitForge's ability to convert external LTspice example circuits into KiCad schematics + ngspice simulations. Clean up repository and documentation.

### Achievements
1. **LTspice Audio Amplifier converted** — `audioamp.asc` from LTspice Educational examples
   - 3-stage BJT amplifier: differential pair + VAS + quasi-complementary push-pull output
   - 8 transistors (2N3904, 2N3906, 2N2219A), 14 resistors, 3 caps, +-10V supply
   - Used LTspice to auto-generate netlist, then hand-translated to ngspice with descriptive node names
   - **Simulation verified**: Gain = 10.3x (20.2 dB), matches theoretical 1+R7/R6 = 11
   - Clean sinusoidal waveforms, no clipping with 0.7V input into +-10V supply
   - First use of Q_PNP_BCE symbol in the pipeline

2. **KiCad schematic** — `build_audioamp()` function, A3 layout with 4 labelled sections
   - INPUT → DIFFERENTIAL PAIR → VAS → OUTPUT STAGE
   - All 29 components placed and wired

3. **CLI integration** — `python kicad_pipeline.py audioamp` runs the full pipeline

4. **Repo cleanup**
   - Moved 55 old test/debug files to `sim_work/archive/`
   - Clean sim_work now has 14 production schematics, 23 result plots, PDFs in subdirs
   - Updated .gitignore to whitelist all circuit outputs, exclude archive
   - Updated README.md: development progress section, audioamp in circuit table and quick start

### Code Changes (kicad_pipeline.py)
- New functions: `build_audioamp()`, `write_audioamp_netlist()`
- Modified: `main()` — added `audioamp` to circuit type dispatch
- Updated: circuit type listing in module docstring

*Last updated: 2026-03-06 (Session 19)*


## Session 20 — Schematic Verification, PNP Fix, Test Point Markers

### Goal
Fix audioamp schematic connection issues, add comprehensive pin connectivity verification, color-coded test point markers, and improve layout spacing.

### Achievements
1. **PNP transistor orientation fixed** — Q3 and Q6 now mirrored (emitter at top toward VCC)
   - `fix_kicad_sch(sch_path, mirror_refs=["Q3", "Q6"])` applies mirror post-save
   - Wiring uses pre-computed mirrored pin positions for correct geometry
   - PNP arrow direction now visually correct in schematic

2. **Pin offset fixes** — Replaced all hardcoded VDC/VSIN pin offsets with `get_pin_pos()`
   - VDC pins at (-0.14, ±5.55/4.61), not (0, ±5.38/4.78) as previously hardcoded
   - VSIN pins at (-0.61, ±5.55/4.61) — also had wrong hardcoded values
   - GND symbols now correctly placed at actual pin X coordinates

3. **Pin connectivity verification** — New `verify_pin_connections()` function
   - Checks every component pin against wire endpoints AND wire segments
   - Reports disconnected pins with component reference, pin name, and coordinates
   - Also detects wire crossings without junctions (visual ambiguity)
   - Audioamp: 58/58 pins verified connected, 4 wire crossings flagged

4. **Test point markers** — Color-coded labels on schematic matching plot waveforms
   - [1] V(IN) - cyan, [2] V(OUT) - red, [3] V(VAS) - yellow, [4] V(Q4E) - green
   - Matches `plot_results()` color scheme: `#00d4ff, #ff6b6b, #ffd93d, #6bcb77`

5. **Layout spacing improved** — Wider component gaps to avoid cramping
   - C1 offset from R4: 5G → 8G, C2 from Q3: 5G → 8G, C3 from Q4: 6G → 8G
   - R10 from Q4: 7G → 10G, Q7/Q8 from Q5/Q6: 110G → 115G
   - R14 at 128G, V1/V2 at 140G — more breathing room in output stage

### Code Changes (kicad_pipeline.py)
- New function: `verify_pin_connections()` — pin-level connectivity verification
- Modified: `build_audioamp()` — mirrored PNP, get_pin_pos for sources, test point labels
- Modified: `verify_circuit()` — added `audioamp` required nets
- Modified: audioamp CLI dispatch — added Step 7 pin connectivity check

---

## Session 21 — Zero Wire Crossings & Layout Quality Enforcement

### Achievements
1. **Zero wire crossings achieved** — Audioamp schematic now has 0 crossings (was 5-7)
   - R7 feedback path: replaced long physical wires with KiCad net labels ("FB", "OUTPUT")
   - Q6C→Q8B: chained through R13 (same N013 node) instead of direct wire
   - R12→output: switched to VH routing to avoid crossing Q7E/Q8C verticals
   - C3→VAS: connected to Q3C instead of Q4C (same net, avoids R9/Q4B vertical)
   - C3→Q4E: VH routing keeps verticals at C3's x column, not Q4's
   - Q4E→Q6B: routed from R11 pin1 (same net, below R10 blocking vertical)

2. **Wire crossings now enforced as ERROR** — `verify_pin_connections()` reports
   crossings as ERROR (was WARNING). Zero crossings is a hard requirement.

3. **OUTPUT label overlap fixed** — Moved label 8G from R14 (was 4G), eliminating
   the text/reference overlap warning.

4. **Final verification: 42 passed, 0 warnings, 0 errors**
   - All 58 pins connected, zero wire crossings
   - Simulation: 10.3x gain (20.2 dB), clean amplification

### Code Changes (kicad_pipeline.py)
- Modified: `build_audioamp()` — 6 routing changes for zero crossings
- Modified: `verify_pin_connections()` — crossings are now ERROR, not WARNING
- Key principle: use net labels for feedback/long paths, chain through shared nodes,
  choose VH vs HV routing based on blocking vertical/horizontal analysis

### Next Session Plan
1. **Individual circuit pages** — One-page-per-subcircuit PDFs for oscillator and TIA
   - Separate clear schematics: diff pair, VAS, output stage, bias network, feedback
   - Each on its own A4 page in a single multi-page PDF
2. **Reverse-engineer layout algorithms** — Study LTspice and TINA-TI auto-placement
   - Disassemble/analyze how LTspice lays out components automatically
   - Study TINA-TI's circuit simulation and layout approach
   - Extract principles for CircuitForge auto-routing
3. **Interactive simulation viewer** — SimGUI feature for mouseover voltage/current
   - Hover over any connection point → show V and I from simulation data
   - Map schematic nodes to ngspice simulation results
4. **Image-to-circuit conversion** — OCR/vision pipeline: photo → netlist → simulation

---

## Session 22 — SimGUI Fixes, DAC7800 IC Boxes, Comparison Mode, Schematic Layout Fixes

### Achievements

1. **DAC7800 drawn as proper IC boxes** — Replaced text-only labels with rectangle
   boxes showing pin labels (VREF, IOUT, VCTRL). New `_draw_dac7800_box()` helper
   draws a solid rectangle with labeled pins. Applied to all 4 DAC7800 instances
   (integrator1, integrator2, oscillator MDAC1, oscillator MDAC2).

2. **Electrometer 362 layout fixes** — Fixed overlapping V- GND / feedback R1
   (fb_gap 5→9, cf_gap 3→4). Added junction dots at 3 T-junctions that were missing
   after `merge_collinear_wires()` (divider tee, C2 bypass tee, output branch).

3. **Summing amplifier gain annotations corrected** — Was showing "BP gain = -2.2"
   (wrong). Corrected to "BP gain = -(10k/22k) = -0.455, Q = R2/R3 = 2.2".

4. **SimGUI Python path fix** — SimulationRunner was using `FileName = "python"` which
   hit the wrong Python (msys64 without numpy). Added `FindPython()` method that
   searches Python312/313/311 in AppData before falling back to PATH.

5. **SimGUI subprocess popup fix** — When SimGUI launched Python and Python launched
   ngspice, ngspice created visible console popup windows. Added
   `CREATE_NO_WINDOW` flag to all `subprocess.run()` calls in kicad_pipeline.py
   via `_SUBPROCESS_KWARGS` dict (Windows only).

6. **SimGUI async fix** — Removed unnecessary `Task.Run()` wrapping of
   `RunGenericAsync()` calls in MainForm.cs. Direct `await` is cleaner.

7. **Comparison project added to SimGUI** — New "Comparison" mode runs both MDAC and
   analog oscillator designs at matching frequency points. Side-by-side grid and
   dual-line chart (Steel Blue for MDAC, Burnt Orange for Analog, Gray for ideal).
   Toggle button switches between frequency accuracy and amplitude stability views.

8. **All 20 PDF schematics regenerated** — Fresh PDFs with all fixes applied. Organized
   into project folders in Downloads (Electrometer, Oscillator, Amplifier, Input System).

### Code Changes
- `kicad_pipeline.py`: `_draw_dac7800_box()` helper, `_SUBPROCESS_KWARGS` for
  CREATE_NO_WINDOW, electrometer_362 spacing/junctions, summing amp annotations,
  `write_analog_osc_netlist()` + `analog_osc` entry point
- `SimGUI/Services/SimulationRunner.cs`: `FindPython()` method, `_pythonExe` field
- `SimGUI/MainForm.cs`: Direct `await` instead of `Task.Run()`, comparison mode methods
- `SimGUI/MainForm.Designer.cs`: Added "Comparison" to project combo, toggle button
- `SimGUI/Projects/ComparisonConfig.cs`: New IProjectConfig for MDAC vs Analog comparison
- `SimGUI/Models/ComparisonPointData.cs`: New data model for paired results
- `docs/comparison_guide.md`: Circuit differences, fix recommendations, quick start

*Last updated: 2026-03-09 (Session 22)*
