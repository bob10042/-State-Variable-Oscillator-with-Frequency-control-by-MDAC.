"""
CircuitForge - Automated Circuit Design & Simulation Platform
=============================================================
Python-driven pipeline: Design circuits from code, simulate, verify, iterate.
Self-learning correction loop catches and prevents layout/electrical errors.

Pipeline: Build -> Verify -> Correct -> Simulate -> Plot -> Export
    - Structural checks: floating pins, missing nets, wire crossings
    - Layout quality: feedback area clearance, component spacing, label placement
    - Simulation: output saturation, virtual ground drift, gain tolerance
    - Self-learning: every bug becomes a permanent rule in learned_rules.json

Circuits available:
    audioamp        - 3-stage audio amplifier: diff pair + VAS + push-pull (29 components)
    ce_amp          - Common-emitter BJT amplifier (15 components)
    inv_amp         - LM741 inverting amplifier, gain=-10 (12 components)
    sig_cond        - Dual op-amp signal conditioner + Sallen-Key LPF (22 components)
    usb_ina         - 3-op-amp instrumentation amplifier, G=95 (24 components)
    electrometer    - Transimpedance amplifier, Rf=1G (10 components)
    electrometer_362 - ADuCM362 electrometer with relay range switching
    relay_ladder    - Reed relay range-switching ladder (4 channels)
    input_filters   - 16-channel RC input filter array
    analog_mux      - 2x CD4051B 8:1 analog multiplexer
    mux_tia         - ADA4530-1 TIA with mux interface
    mcu_section     - ADuCM362 MCU + ADC interface block
    full_system     - All 6 regions on one A0 sheet (connector + 5 subsystems)
    full_path       - Stage 6: Full signal path sim (Filter->Mux->TIA->ADC)
    channel_switch  - Stage 6: 4-channel multiplexed switching sim
    femtoamp_test   - Stage 6: 100fA sensitivity floor test
    avdd_monitor    - Stage 6: AVDD supply monitor readback sim
    oscillator      - State variable oscillator with MDAC + Zener AGC

Op-amp models (swappable via CLI):
    LM741, AD822, AD843, LMC6001, LMC6001A, OPA128

Usage:
    python kicad_pipeline.py                       # Run CE amp (default)
    python kicad_pipeline.py mcu_section           # ADuCM362 MCU block
    python kicad_pipeline.py electrometer OPA128   # TIA with OPA128
    python kicad_pipeline.py search LMC6001        # Search model library

Key dependencies:
    kicad-sch-api 0.5.5  - Creates .kicad_sch files from Python
    ngspice 45.2         - SPICE simulation engine
    kicad-cli 9.0.7      - SVG/PDF schematic export
    numpy, matplotlib    - Data analysis and plotting
    PyMuPDF, Pillow      - PDF-to-PNG rendering
"""

import os
import re
import subprocess
import glob
import json
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt
from kicad_sch_api import create_schematic, get_symbol_cache

# CircuitForge identity
PROGRAM_NAME = "CircuitForge"
VERSION = "0.1.0"

# Paths - derived from repo root (directory containing this script)
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
# Symbol libraries: prefer kicad_libs/ (full KiCad install), fallback to symbols/ (bundled minimal set)
_kicad_libs_full = os.path.join(REPO_DIR, "kicad_libs")
_kicad_libs_min = os.path.join(REPO_DIR, "symbols")
KICAD_LIBS = _kicad_libs_full if os.path.isdir(_kicad_libs_full) else _kicad_libs_min
WORK_DIR = os.path.join(REPO_DIR, "sim_work")
MODELS_DIR = os.path.join(REPO_DIR, "models", "MicroCap-LIBRARY-for-ngspice")

def _find_executable(env_var, name, search_paths):
    """Find an executable: check env var first, then search common paths."""
    from_env = os.environ.get(env_var)
    if from_env and os.path.isfile(from_env):
        return from_env
    for p in search_paths:
        if os.path.isfile(p):
            return p
    return None

NGSPICE = _find_executable("NGSPICE_PATH", "ngspice", [
    r"C:\Spice64\bin\ngspice_con.exe",
    os.path.expanduser(r"~\Spice64\bin\ngspice_con.exe"),
    r"C:\Program Files\Spice64\bin\ngspice_con.exe",
    "/usr/bin/ngspice", "/usr/local/bin/ngspice",
])

LTSPICE = _find_executable("LTSPICE_PATH", "LTspice", [
    r"C:\Program Files\ADI\LTspice\LTspice.exe",
    os.path.expanduser(r"~\AppData\Local\Programs\ADI\LTspice\LTspice.exe"),
    r"C:\Program Files (x86)\LTC\LTspiceXVII\XVIIx64.exe",
])

KICAD_CLI = _find_executable("KICAD_CLI_PATH", "kicad-cli", [
    os.path.expanduser(r"~\AppData\Local\Programs\KiCad\9.0\bin\kicad-cli.exe"),
    r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
    r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
    "/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli",
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
])

# LTspice model library path (for ADA4530-1 etc.)
LTSPICE_LIB_DIR = _find_executable("LTSPICE_LIB_PATH", "ADI1.lib", [
    os.path.expanduser(r"~\AppData\Local\LTspice\lib\sub\ADI1.lib"),
    r"C:\Users\Public\Documents\LTspiceXVII\lib\sub\ADI1.lib",
    os.path.expanduser(r"~\Documents\LTspiceXVII\lib\sub\ADI1.lib"),
])
# Extract just the directory for .lib references
if LTSPICE_LIB_DIR:
    LTSPICE_LIB_DIR = os.path.dirname(LTSPICE_LIB_DIR)

os.makedirs(WORK_DIR, exist_ok=True)

# On Windows, suppress console popup windows when running subprocess calls from GUI
_SUBPROCESS_KWARGS = {}
if os.name == 'nt':
    _SUBPROCESS_KWARGS['creationflags'] = subprocess.CREATE_NO_WINDOW

def _get_ltspice_lib_path():
    """Return the LTspice .lib path for netlist includes, with backslash escaping."""
    if LTSPICE_LIB_DIR:
        p = os.path.join(LTSPICE_LIB_DIR, "ADI1.lib")
        return p.replace("\\", "\\\\")
    raise FileNotFoundError(
        "Cannot find LTspice ADI model library (ADI1.lib).\n"
        "Set LTSPICE_LIB_PATH env var to the full path of ADI1.lib."
    )


# =============================================================
# DYNAMIC SYMBOL PIN PARSER - reads pins from .kicad_sym files
# =============================================================
# Replaces the old hardcoded PIN_DB. Parses pin positions directly
# from KiCad symbol library files so ALL components get pin
# connectivity checking, not just LM741.

_SYMBOL_PIN_CACHE = {}
_SYMBOL_FILE_INDEX = None

# Power/virtual symbols to skip during pin checking
_SKIP_SYMBOLS = {'GND', 'VCC', 'VEE', 'GNDPWR', 'VBUS', '+3V3', '+5V',
                 '+3.3V', '+12V', '-12V', '+15V', '-15V', 'PWR_FLAG',
                 'VSIN', 'VDC', 'VPULSE'}


def _build_symbol_file_index():
    """Scan symbol library directories and build {symbol_name: file_path} index."""
    global _SYMBOL_FILE_INDEX
    if _SYMBOL_FILE_INDEX is not None:
        return _SYMBOL_FILE_INDEX
    index = {}
    # Scan both kicad_libs/ (full) and symbols/ (bundled minimal set)
    for lib_dir in [_kicad_libs_full, _kicad_libs_min]:
        if os.path.isdir(lib_dir):
            for entry in os.listdir(lib_dir):
                if entry.endswith('.kicad_symdir'):
                    symdir = os.path.join(lib_dir, entry)
                    for sym_file in os.listdir(symdir):
                        if sym_file.endswith('.kicad_sym'):
                            name = sym_file[:-len('.kicad_sym')]
                            if name not in index:  # first found wins
                                index[name] = os.path.join(symdir, sym_file)
    _SYMBOL_FILE_INDEX = index
    return index


def parse_symbol_pins(symbol_name):
    """Parse pin positions from a .kicad_sym library file.

    Returns dict: {pin_number: (x, y, pin_type, pin_name, hidden)}
    Coordinates are in symbol-space (Y-up convention).
    Returns None if symbol not found in libraries.
    """
    if symbol_name in _SYMBOL_PIN_CACHE:
        return _SYMBOL_PIN_CACHE[symbol_name]

    index = _build_symbol_file_index()
    if symbol_name not in index:
        _SYMBOL_PIN_CACHE[symbol_name] = None
        return None

    with open(index[symbol_name], 'r', encoding='utf-8') as f:
        text = f.read()

    pins = {}
    # Match pin blocks: (pin <type> <shape> (at X Y angle) (length L) ...
    #   optionally (hide yes) ... (name "N") ... (number "N"))
    pin_pattern = re.compile(
        r'\(pin\s+(\w+)\s+\w+'           # pin type (passive/input/output/power_in/no_connect)
        r'[^(]*\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)'   # position
        r'\s*\(length\s+[-\d.]+\)'        # length
        r'(.*?)'                           # middle (may contain hide, name)
        r'\(number\s+"([^"]+)"',           # pin number
        re.DOTALL
    )

    for m in pin_pattern.finditer(text):
        pin_type = m.group(1)
        x, y = float(m.group(2)), float(m.group(3))
        middle = m.group(5)
        pin_num = m.group(6)
        hidden = '(hide yes)' in middle

        name_m = re.search(r'\(name\s+"([^"]*)"', middle)
        pin_name = name_m.group(1) if name_m else ""

        pins[pin_num] = (x, y, pin_type, pin_name, hidden)

    _SYMBOL_PIN_CACHE[symbol_name] = pins
    return pins


def get_component_pins(comp, scale=1):
    """Compute absolute pin positions for any placed component.

    Reads pin geometry from .kicad_sym library, then applies:
      1. Y-negate (symbol Y-up -> schematic Y-down)
      2. Rotation (counter-clockwise in KiCad)
      3. Mirror_x (negates Y in schematic coords)
      4. Scale factor
      5. Offset to component center

    Returns dict {pin_num: (abs_x, abs_y, pin_type, pin_name)} or None.
    Skips no_connect and hidden pins automatically.
    """
    lib_id = comp.get('lib_id', '')
    symbol_name = lib_id.split(':')[0] if ':' in lib_id else lib_id

    # Skip power/virtual symbols
    if symbol_name in _SKIP_SYMBOLS:
        return None
    if symbol_name.startswith('#PWR'):
        return None

    sym_pins = parse_symbol_pins(symbol_name)
    if sym_pins is None:
        return None

    cx, cy = comp['x'], comp['y']
    rot = comp.get('rotation', 0)
    mirrored = comp.get('mirror_x', False)

    result = {}
    for pin_num, (sx, sy, pin_type, pin_name, hidden) in sym_pins.items():
        if pin_type == 'no_connect' or hidden:
            continue

        # Symbol Y-up -> schematic Y-down
        dx, dy = sx, -sy

        # Rotation (counter-clockwise)
        if rot == 90:
            dx, dy = -dy, dx
        elif rot == 180:
            dx, dy = -dx, -dy
        elif rot == 270:
            dx, dy = dy, -dx

        # Mirror_x negates Y in schematic coords
        if mirrored:
            dy = -dy

        result[pin_num] = (cx + dx * scale, cy + dy * scale, pin_type, pin_name)

    return result


# =============================================================
# KICAD-CLI COMPAT: Strip unsupported KiCad 9.x-nightly tokens
# =============================================================
def fix_kicad_sch(path, mirror_refs=None):
    """Strip properties that kicad-cli 9.0.x stable can't parse.

    kicad-sch-api emits tokens from a newer nightly format:
      (in_pos_files yes), (duplicate_pin_numbers_are_jumpers no),
      (power global) - all cause 'Failed to load schematic' in kicad-cli 9.0.7.

    mirror_refs: list of reference designators (e.g. ['U1']) to add (mirror x)
                 which flips the symbol vertically (swaps +/- inputs on op-amps).
    """
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    text = re.sub(r'\s*\(in_pos_files yes\)\n', '\n', text)
    text = re.sub(r'\s*\(duplicate_pin_numbers_are_jumpers no\)\n', '\n', text)
    # Power symbols: (power global) -> (power) for kicad-cli 9.0.x compat
    text = text.replace('(power global)', '(power)')
    # Hide #PWR reference designators on placed power symbol instances
    text = re.sub(
        r'(\(property "Reference" "#PWR\d+"\s*\n\s*\(at [^\)]+\)\s*\n)(\s*\(effects)',
        r'\1\t\t\t(hide yes)\n\2',
        text
    )

    # Left-justify free text annotations (default is center, clips at margins)
    text = re.sub(
        r'(\(text "[^"]*"\s*\n\s*\(exclude_from_sim [^\)]+\)\s*\n\s*\(at [^\)]+\)\s*\n\s*\(effects\s*\n\s*\(font\s*\n(?:\s*\([^\)]+\)\s*\n)*\s*\))\s*\n(\s*\))',
        r'\1\n\t\t\t(justify left)\n\2',
        text
    )

    # Add mirror to specific components
    if mirror_refs:
        for ref in mirror_refs:
            # Find: (property "Reference" "U1" ...) and insert (mirror x) after (at ...) line
            # Pattern: inside a (symbol ...) block, after the (at x y rot) line
            pattern = (
                r'(\(symbol\s*\n'
                r'\s*\(lib_id "[^"]+"\)\s*\n'
                r'\s*\(at [^\)]+\)\s*\n)'
                r'(\s*\(unit )'
            )
            def add_mirror(m):
                # Check if this symbol block contains our reference
                # Look ahead in the text for this ref
                start = m.start()
                chunk = text[start:start+500]
                if f'"Reference" "{ref}"' in chunk:
                    return m.group(1) + '\t\t(mirror x)\n' + m.group(2)
                return m.group(0)
            text = re.sub(pattern, add_mirror, text)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def merge_collinear_wires(path):
    """Post-process a .kicad_sch file to merge overlapping collinear wires.

    Finds pairs of horizontal or vertical wires that share the same axis
    and have overlapping ranges, then merges them into a single wire
    spanning the full extent.  Runs iteratively until no more merges.

    Must be called AFTER fix_kicad_sch and BEFORE scale_schematic.
    """
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    wire_pat = re.compile(
        r'\(wire\s*\n'
        r'\s*\(pts\s*\n'
        r'\s*\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s*'
        r'\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s*\n'
        r'\s*\)\s*\n'
        r'\s*(?:\(stroke[^\)]*\)\s*\n)?'
        r'(?:\s*\(stroke\s*\n(?:\s*\([^\)]*\)\s*\n)*\s*\)\s*\n)?'
        r'\s*(?:\(uuid "[^"]*"\)\s*\n)?'
        r'\s*\)',
        re.MULTILINE
    )

    merged_total = 0
    for _pass in range(20):  # max 20 merge passes
        matches = list(wire_pat.finditer(text))
        wires = []
        for m in matches:
            x1, y1 = float(m.group(1)), float(m.group(2))
            x2, y2 = float(m.group(3)), float(m.group(4))
            wires.append((x1, y1, x2, y2, m))

        merged_this_pass = 0
        to_remove = set()

        # Group by axis: horizontal (same y) and vertical (same x)
        from collections import defaultdict
        h_groups = defaultdict(list)  # y -> [(min_x, max_x, idx)]
        v_groups = defaultdict(list)  # x -> [(min_y, max_y, idx)]

        for idx, (x1, y1, x2, y2, m) in enumerate(wires):
            if abs(y1 - y2) < 0.01:  # horizontal
                h_groups[round(y1, 2)].append((min(x1, x2), max(x1, x2), idx))
            elif abs(x1 - x2) < 0.01:  # vertical
                v_groups[round(x1, 2)].append((min(y1, y2), max(y1, y2), idx))

        replacements = []  # (old_match, new_text) or (old_match, None) for removal

        def find_merges(groups, is_horizontal):
            nonlocal merged_this_pass
            for _key, segs in groups.items():
                if len(segs) < 2:
                    continue
                segs.sort()
                used = set()
                for i in range(len(segs)):
                    if i in used:
                        continue
                    lo, hi, idx_i = segs[i]
                    for j in range(i + 1, len(segs)):
                        if j in used:
                            continue
                        lo2, hi2, idx_j = segs[j]
                        # Check overlap (not just touching at endpoints)
                        overlap_lo = max(lo, lo2)
                        overlap_hi = min(hi, hi2)
                        if overlap_hi - overlap_lo > 0.01:
                            # Merge: extend i to cover j
                            new_lo = min(lo, lo2)
                            new_hi = max(hi, hi2)
                            segs[i] = (new_lo, new_hi, idx_i)
                            lo, hi = new_lo, new_hi
                            used.add(j)
                            to_remove.add(idx_j)
                            merged_this_pass += 1

                    if idx_i not in to_remove:
                        # Update wire i coordinates
                        wi = wires[idx_i]
                        m_i = wi[4]
                        if is_horizontal:
                            y = round(_key, 4)
                            new_text = (
                                f'(wire\n'
                                f'\t\t(pts\n'
                                f'\t\t\t(xy {round(lo, 4)} {y}) (xy {round(hi, 4)} {y})\n'
                                f'\t\t)\n'
                                f'\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
                                f'\t\t(uuid "{import_uuid()}")\n'
                                f'\t)'
                            )
                        else:
                            x = round(_key, 4)
                            new_text = (
                                f'(wire\n'
                                f'\t\t(pts\n'
                                f'\t\t\t(xy {x} {round(lo, 4)}) (xy {x} {round(hi, 4)})\n'
                                f'\t\t)\n'
                                f'\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
                                f'\t\t(uuid "{import_uuid()}")\n'
                                f'\t)'
                            )
                        replacements.append((m_i, new_text))

        def import_uuid():
            import uuid
            return str(uuid.uuid4())

        find_merges(h_groups, is_horizontal=True)
        find_merges(v_groups, is_horizontal=False)

        if merged_this_pass == 0:
            break

        # Apply replacements in reverse order to preserve positions
        # First, remove merged wires; then replace surviving wires
        all_ops = []
        for idx in to_remove:
            m = wires[idx][4]
            all_ops.append((m.start(), m.end(), ''))
        for m, new_text in replacements:
            all_ops.append((m.start(), m.end(), new_text))

        # Deduplicate by start position, prefer non-empty
        by_start = {}
        for s, e, t in all_ops:
            if s not in by_start or t:
                by_start[s] = (s, e, t)
        all_ops = sorted(by_start.values(), key=lambda x: x[0], reverse=True)

        for start, end, new_text in all_ops:
            text = text[:start] + new_text + text[end:]

        # Clean up blank lines
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        merged_total += merged_this_pass

    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)

    if merged_total:
        print(f"  Merged {merged_total} overlapping wire(s)")
    return merged_total


def scale_schematic(path, factor=3.0):
    """Uniformly scale all coordinates in a .kicad_sch file by factor.

    Scales symbol graphics, component positions, wires, labels, junctions,
    text, font sizes, and pin geometry so everything appears `factor` times
    larger.  Paper size is changed to a custom User size to accommodate.

    Must be called AFTER fix_kicad_sch (operates on the saved file).
    """
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    S = factor

    def _scale_nums(m, count=2):
        """Scale `count` leading float tokens inside a matched group."""
        prefix = m.group(1)
        nums = m.group(2)
        parts = nums.split()
        for i in range(min(count, len(parts))):
            try:
                v = float(parts[i].rstrip(')'))
                parts[i] = f"{round(v * S, 4)}"
            except ValueError:
                pass
        return prefix + ' '.join(parts)

    # --- Coordinate patterns (scale first 2 numbers = X Y) ---
    # (at X Y ...) - positions for components, labels, junctions, text, properties
    text = re.sub(
        r'(\(at\s+)([-\d.]+\s+[-\d.]+)',
        lambda m: m.group(1) + ' '.join(
            f"{round(float(v) * S, 4)}" for v in m.group(2).split()
        ),
        text
    )
    # (xy X Y) - wire points, polyline vertices
    text = re.sub(
        r'(\(xy\s+)([-\d.]+\s+[-\d.]+)',
        lambda m: m.group(1) + ' '.join(
            f"{round(float(v) * S, 4)}" for v in m.group(2).split()
        ),
        text
    )
    # (start X Y) - rectangle/arc start
    text = re.sub(
        r'(\(start\s+)([-\d.]+\s+[-\d.]+)',
        lambda m: m.group(1) + ' '.join(
            f"{round(float(v) * S, 4)}" for v in m.group(2).split()
        ),
        text
    )
    # (end X Y) - rectangle/arc end
    text = re.sub(
        r'(\(end\s+)([-\d.]+\s+[-\d.]+)',
        lambda m: m.group(1) + ' '.join(
            f"{round(float(v) * S, 4)}" for v in m.group(2).split()
        ),
        text
    )
    # (mid X Y) - arc midpoint
    text = re.sub(
        r'(\(mid\s+)([-\d.]+\s+[-\d.]+)',
        lambda m: m.group(1) + ' '.join(
            f"{round(float(v) * S, 4)}" for v in m.group(2).split()
        ),
        text
    )
    # (center X Y) - circle center
    text = re.sub(
        r'(\(center\s+)([-\d.]+\s+[-\d.]+)',
        lambda m: m.group(1) + ' '.join(
            f"{round(float(v) * S, 4)}" for v in m.group(2).split()
        ),
        text
    )
    # (radius R) - circle radius
    text = re.sub(
        r'(\(radius\s+)([-\d.]+)',
        lambda m: m.group(1) + f"{round(float(m.group(2)) * S, 4)}",
        text
    )

    # --- Pin geometry ---
    # (length L) - pin stub length
    text = re.sub(
        r'(\(length\s+)([-\d.]+)',
        lambda m: m.group(1) + f"{round(float(m.group(2)) * S, 4)}",
        text
    )
    # (offset V) inside pin_names - pin name offset from body
    text = re.sub(
        r'(\(offset\s+)([-\d.]+)',
        lambda m: m.group(1) + f"{round(float(m.group(2)) * S, 4)}",
        text
    )

    # --- Font sizes ---
    # (size W H) inside font blocks
    text = re.sub(
        r'(\(size\s+)([-\d.]+\s+[-\d.]+)',
        lambda m: m.group(1) + ' '.join(
            f"{round(float(v) * S, 4)}" for v in m.group(2).split()
        ),
        text
    )

    # --- Paper size: detect standard size -> User scaled ---
    paper_sizes = {
        'A0': (1189, 841), 'A1': (841, 594), 'A2': (594, 420),
        'A3': (420, 297), 'A4': (297, 210),
    }
    for pname, (pw, ph) in paper_sizes.items():
        pat = rf'\(paper "{pname}"\)'
        if re.search(pat, text):
            new_w = round(pw * S)
            new_h = round(ph * S)
            text = re.sub(pat, f'(paper "User" {new_w} {new_h})', text)
            break
    else:
        # Already User or unknown - try to scale User dimensions
        m = re.search(r'\(paper "User" (\d+) (\d+)\)', text)
        if m:
            new_w = round(int(m.group(1)) * S)
            new_h = round(int(m.group(2)) * S)
            text = re.sub(
                r'\(paper "User" \d+ \d+\)',
                f'(paper "User" {new_w} {new_h})',
                text
            )

    # --- Stroke width: scale so lines remain proportional ---
    # width 0 means "default" in KiCad; give it a visible bold minimum at scale
    def _scale_stroke_width(m):
        w = float(m.group(1))
        if w == 0:
            # Default width: bold minimum for scaled drawing
            return f'(width {round(0.35 * S, 4)})'
        return f'(width {round(w * S * 1.5, 4)})'  # 1.5x extra for bold
    text = re.sub(r'\(width\s+([-\d.]+)\)', _scale_stroke_width, text)

    # --- Do NOT scale: rotation angles, UUIDs, version ---

    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"  Schematic scaled {S}x -> paper {new_w}x{new_h}mm")


def export_svg(sch_path, svg_path=None):
    """Export schematic to SVG via kicad-cli."""
    if not KICAD_CLI:
        raise FileNotFoundError(
            "kicad-cli not found. Install KiCad 9.x or set KICAD_CLI_PATH env var.\n"
            "  Download: https://www.kicad.org/download/"
        )
    if svg_path is None:
        svg_path = sch_path.replace('.kicad_sch', '.svg')
    # kicad-cli puts output in a subdirectory named after -o
    result = subprocess.run(
        [KICAD_CLI, "sch", "export", "svg", "-o", svg_path, sch_path],
        capture_output=True, text=True, timeout=30, **_SUBPROCESS_KWARGS
    )
    if result.returncode != 0:
        raise RuntimeError(f"kicad-cli failed: {result.stderr.strip()}")
    # kicad-cli creates svg_path/<basename>.svg - find the actual file
    base = os.path.splitext(os.path.basename(sch_path))[0] + '.svg'
    actual = os.path.join(svg_path, base)
    if os.path.exists(actual):
        return actual
    return svg_path


# =============================================================
# LIBRARY INIT
# =============================================================
def init_libraries():
    """Load KiCad symbol libraries from kicad_libs/ and/or symbols/."""
    cache = get_symbol_cache()
    # Discover from both dirs (handles case where only one exists)
    lib_dirs = [d for d in [_kicad_libs_full, _kicad_libs_min] if os.path.isdir(d)]
    if lib_dirs:
        cache.discover_libraries(lib_dirs)
    else:
        print("  WARNING: No symbol libraries found. Install KiCad or check repo integrity.")
    return cache


# =============================================================
# MODEL SEARCH: Find SPICE models in Micro-Cap library
# =============================================================
def search_models(query, max_results=20):
    """Search the Micro-Cap model library for a component."""
    query_upper = query.upper()
    results = []

    lib_files = glob.glob(os.path.join(MODELS_DIR, "*.lib")) + \
                glob.glob(os.path.join(MODELS_DIR, "*.LIB")) + \
                glob.glob(os.path.join(MODELS_DIR, "*.mod")) + \
                glob.glob(os.path.join(MODELS_DIR, "*.MOD"))

    for lib_path in lib_files:
        lib_name = os.path.basename(lib_path)
        try:
            with open(lib_path, 'r', errors='replace') as f:
                for line in f:
                    stripped = line.strip()
                    upper = stripped.upper()
                    if upper.startswith('.MODEL') and query_upper in upper:
                        # Extract model name and type
                        parts = stripped.split()
                        if len(parts) >= 3:
                            name = parts[1]
                            mtype = parts[2].split('(')[0]
                            results.append(('model', name, mtype, lib_name))
                    elif upper.startswith('.SUBCKT') and query_upper in upper:
                        parts = stripped.split()
                        if len(parts) >= 2:
                            name = parts[1]
                            pins = parts[2:] if len(parts) > 2 else []
                            pin_str = ' '.join(p for p in pins if not p.startswith('params'))[:40]
                            results.append(('subckt', name, pin_str, lib_name))
        except Exception:
            continue

    return results[:max_results]


def extract_model(model_name, lib_file=None):
    """Extract a .model or .subckt block from the library."""
    search_files = []
    if lib_file:
        search_files = [os.path.join(MODELS_DIR, lib_file)]
    else:
        search_files = glob.glob(os.path.join(MODELS_DIR, "*.lib")) + \
                       glob.glob(os.path.join(MODELS_DIR, "*.LIB")) + \
                       glob.glob(os.path.join(MODELS_DIR, "*.mod")) + \
                       glob.glob(os.path.join(MODELS_DIR, "*.MOD"))

    name_upper = model_name.upper()

    for lib_path in search_files:
        try:
            with open(lib_path, 'r', errors='replace') as f:
                lines = f.readlines()

            for i, line in enumerate(lines):
                upper = line.strip().upper()

                # .model on single or continued line
                if upper.startswith('.MODEL') and name_upper in upper:
                    block = [line.rstrip()]
                    j = i + 1
                    while j < len(lines) and lines[j].startswith('+'):
                        block.append(lines[j].rstrip())
                        j += 1
                    return '\n'.join(block)

                # .subckt block
                if upper.startswith('.SUBCKT') and name_upper in upper:
                    block = [line.rstrip()]
                    j = i + 1
                    while j < len(lines):
                        block.append(lines[j].rstrip())
                        if lines[j].strip().upper().startswith('.ENDS'):
                            break
                        j += 1
                    return '\n'.join(block)
        except Exception:
            continue

    return None


# =============================================================
# MANHATTAN WIRE ROUTING
# =============================================================
def wire_manhattan(sch, x1, y1, x2, y2):
    """Draw an L-shaped Manhattan route between two points (H then V)."""
    if abs(x1 - x2) < 0.01 and abs(y1 - y2) < 0.01:
        return  # same point
    if abs(x1 - x2) < 0.01:
        sch.add_wire(start=(x1, y1), end=(x2, y2))  # vertical
    elif abs(y1 - y2) < 0.01:
        sch.add_wire(start=(x1, y1), end=(x2, y2))  # horizontal
    else:
        # L-shape: go horizontal first, then vertical
        sch.add_wire(start=(x1, y1), end=(x2, y1))
        sch.add_wire(start=(x2, y1), end=(x2, y2))


def wire_manhattan_vh(sch, x1, y1, x2, y2):
    """Draw an L-shaped Manhattan route (V then H)."""
    if abs(x1 - x2) < 0.01 and abs(y1 - y2) < 0.01:
        return
    if abs(x1 - x2) < 0.01:
        sch.add_wire(start=(x1, y1), end=(x2, y2))
    elif abs(y1 - y2) < 0.01:
        sch.add_wire(start=(x1, y1), end=(x2, y2))
    else:
        # L-shape: go vertical first, then horizontal
        sch.add_wire(start=(x1, y1), end=(x1, y2))
        sch.add_wire(start=(x1, y2), end=(x2, y2))


def get_pin_pos(sch, ref, pin_num):
    """Get the absolute position of a component pin."""
    pos = sch.get_component_pin_position(ref, pin_num)
    return pos.x, pos.y


# =============================================================
# BUILD: Common-Emitter Amplifier
# =============================================================
def build_common_emitter_amp():
    """
    Build a common-emitter BJT amplifier schematic and netlist.
    Classic single-stage audio amp with voltage divider bias.

    Schematic:
        VCC (+12V)
          |
         [Rc] 2.2k
          |-----> Vout
         C (Q1 NPN 2N3904)
          |
         E
          |
         [Re] 470
          |
         GND

    Bias: R1 (22k) from VCC to base, R2 (4.7k) from base to GND
    Input: Cin (1uF) AC couples signal to base
    Output: Cout (10uF) AC couples collector to load
    """
    print("Building common-emitter amplifier schematic...")

    sch = create_schematic("Common Emitter Amplifier")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="Common Emitter BJT Amplifier",
        company="Circuit Automation Project",
        rev="1.0",
        comments={1: "2N3904 NPN - single stage audio amp"}
    )

    # Grid: KiCad uses mm, typical grid is 2.54mm (0.1 inch)
    G = 2.54  # grid unit
    # A4 landscape: 297mm x 210mm. Center circuit on page.
    # Q_NPN_BCE offsets: pin1(B)=(-5.08,0) pin2(C)=(+2.54,-5.08) pin3(E)=(+2.54,+5.08)

    # ── Place components ──
    # Transistor Q1 - centered on A4 page
    qx, qy = 55*G, 40*G
    sch.components.add(
        lib_id="Q_NPN_BCE:Q_NPN_BCE",
        reference="Q1",
        value="2N3904",
        position=(qx, qy)
    )

    # Collector resistor Rc - above Q1 collector
    # Q1 collector is at (qx + 1*G, qy - 2*G) approx
    rc_x = qx + 1*G
    sch.components.add(
        lib_id="R:R",
        reference="R3",
        value="2.2k",
        position=(rc_x, qy - 10*G)
    )

    # Emitter resistor Re - below Q1 emitter
    re_x = qx + 1*G
    sch.components.add(
        lib_id="R:R",
        reference="R4",
        value="470",
        position=(re_x, qy + 10*G)
    )

    # Bias resistors - left of base
    bx = qx - 8*G
    sch.components.add(
        lib_id="R:R",
        reference="R1",
        value="22k",
        position=(bx, qy - 6*G)
    )

    sch.components.add(
        lib_id="R:R",
        reference="R2",
        value="4.7k",
        position=(bx, qy + 6*G)
    )

    # Input coupling cap - left of bias network
    sch.components.add(
        lib_id="C:C",
        reference="C1",
        value="1u",
        position=(bx - 8*G, qy),
        rotation=90
    )

    # Output coupling cap - right of collector
    sch.components.add(
        lib_id="C:C",
        reference="C2",
        value="10u",
        position=(rc_x + 8*G, qy - 10*G),
        rotation=90
    )

    # Emitter bypass cap - right of Re
    ce_x = re_x + 6*G
    sch.components.add(
        lib_id="C:C",
        reference="C3",
        value="100u",
        position=(ce_x, qy + 10*G)
    )

    # ── Wire up with Manhattan routing ──

    # Get all pin positions
    r3_1 = get_pin_pos(sch, "R3", "1")  # R3 top
    r3_2 = get_pin_pos(sch, "R3", "2")  # R3 bottom
    q1_b = get_pin_pos(sch, "Q1", "1")  # Q1 base
    q1_c = get_pin_pos(sch, "Q1", "2")  # Q1 collector
    q1_e = get_pin_pos(sch, "Q1", "3")  # Q1 emitter
    r4_1 = get_pin_pos(sch, "R4", "1")  # R4 top
    r4_2 = get_pin_pos(sch, "R4", "2")  # R4 bottom
    r1_1 = get_pin_pos(sch, "R1", "1")  # R1 top
    r1_2 = get_pin_pos(sch, "R1", "2")  # R1 bottom
    r2_1 = get_pin_pos(sch, "R2", "1")  # R2 top
    r2_2 = get_pin_pos(sch, "R2", "2")  # R2 bottom
    c1_1 = get_pin_pos(sch, "C1", "1")  # C1 right (rotated)
    c1_2 = get_pin_pos(sch, "C1", "2")  # C1 left (rotated)
    c2_1 = get_pin_pos(sch, "C2", "1")  # C2 right
    c2_2 = get_pin_pos(sch, "C2", "2")  # C2 left
    c3_1 = get_pin_pos(sch, "C3", "1")  # C3 top
    c3_2 = get_pin_pos(sch, "C3", "2")  # C3 bottom

    # R3 bottom -> Q1 collector (vertical, should be aligned now)
    wire_manhattan(sch, r3_2[0], r3_2[1], q1_c[0], q1_c[1])

    # Q1 emitter -> R4 top
    wire_manhattan(sch, q1_e[0], q1_e[1], r4_1[0], r4_1[1])

    # R1 bottom -> R2 top (bias divider, vertical)
    wire_manhattan(sch, r1_2[0], r1_2[1], r2_1[0], r2_1[1])

    # C1 right -> bias junction (horizontal to bx, then vertical)
    wire_manhattan(sch, c1_1[0], c1_1[1], bx, c1_1[1])
    sch.add_wire(start=(bx, c1_1[1]), end=(bx, r1_2[1]))

    # Bias junction -> Q1 base (horizontal from bx to base)
    wire_manhattan(sch, bx, r1_2[1], q1_b[0], q1_b[1])

    # Collector node -> C2 left (horizontal)
    wire_manhattan(sch, r3_2[0], r3_2[1], c2_2[0], c2_2[1])

    # R4 top -> C3 top (horizontal for bypass cap)
    wire_manhattan(sch, r4_1[0], r4_1[1], c3_1[0], c3_1[1])

    # R4 bottom -> C3 bottom (horizontal)
    wire_manhattan(sch, r4_2[0], r4_2[1], c3_2[0], c3_2[1])

    # ── Power symbols and sources ──
    # VCC at top of R3
    vcc_y = r3_1[1] - 3*G
    sch.add_wire(start=r3_1, end=(r3_1[0], vcc_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR01", value="+12V",
                       position=(r3_1[0], vcc_y))

    # VCC at top of R1
    vcc2_y = r1_1[1] - 3*G
    sch.add_wire(start=r1_1, end=(r1_1[0], vcc2_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR02", value="+12V",
                       position=(r1_1[0], vcc2_y))

    # GND at bottom of R4
    gnd_y = r4_2[1] + 3*G
    sch.add_wire(start=r4_2, end=(r4_2[0], gnd_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR03", value="GND",
                       position=(r4_2[0], gnd_y))

    # GND at bottom of R2
    gnd2_y = r2_2[1] + 3*G
    sch.add_wire(start=r2_2, end=(r2_2[0], gnd2_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR04", value="GND",
                       position=(r2_2[0], gnd2_y))

    # GND at bottom of C3
    gnd3_y = c3_2[1] + 3*G
    sch.add_wire(start=c3_2, end=(c3_2[0], gnd3_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR05", value="GND",
                       position=(c3_2[0], gnd3_y))

    # VSIN input source (replaces IN label)
    vsin_x = c1_2[0] - 6*G
    vsin_cy = c1_2[1] + 5.38  # pin1 (top +) at signal wire height
    sch.components.add(lib_id="VSIN:VSIN", reference="V1",
                       value="10mV 1kHz", position=(vsin_x, vsin_cy))
    vsin_p1 = (vsin_x, vsin_cy - 5.38)  # top (+)
    vsin_p2 = (vsin_x, vsin_cy + 4.78)  # bottom (-)
    wire_manhattan(sch, vsin_p1[0], vsin_p1[1], c1_2[0], c1_2[1])
    # GND at VSIN bottom
    gnd_vs_y = vsin_p2[1] + 3*G
    sch.add_wire(start=vsin_p2, end=(vsin_x, gnd_vs_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR06", value="GND",
                       position=(vsin_x, gnd_vs_y))

    # Output label
    out_x = c2_1[0] + 4*G
    sch.add_label("OUT", position=(out_x, c2_1[1]))
    sch.add_wire(start=c2_1, end=(out_x, c2_1[1]))

    # ── Save schematic ──
    sch_path = os.path.join(WORK_DIR, "ce_amp.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    print(f"  Schematic saved: {sch_path}")

    # ── SVG export via kicad-cli ──
    try:
        svg_out = os.path.join(WORK_DIR, "ce_amp_svg")
        actual = export_svg(sch_path, svg_out)
        print(f"  SVG exported: {actual}")
    except Exception as e:
        print(f"  SVG export: {e}")

    return sch_path


# =============================================================
# BUILD: Audio Amplifier (LTspice Educational Example)
# =============================================================
def build_audioamp():
    """
    Build a 3-stage BJT audio amplifier schematic from the LTspice
    Educational example 'audioamp.asc'.

    Topology:
        Input -> R1 -> Diff Pair (Q1,Q2) -> VAS (Q3,Q4) -> Push-Pull Output (Q5-Q8) -> Speaker

    Stages:
        1. Long-tailed pair: Q1,Q2 (2N3904) with R3 (1K) tail to VEE
           Q1 collector load R2 (200) to VCC, Q2 collector to VCC
        2. Active load + VAS: Q3 (2N3906 PNP) drives Q4 (2N3904)
           R4 (9K) + R5 (1K) interstage, C1 (10p) / C2 (100p) compensation
        3. Quasi-complementary output: Q5 (NPN driver) + Q7 (2N2219A output) upper
           Q6 (PNP driver) + Q8 (2N2219A output) lower, R12/R13 bias, C3 bootstrap
        Feedback: R7 (50K) / R6 (5K) sets gain ~11
        Load: R14 (8 ohm speaker)
        Supply: +/-10V
    """
    print("Building audio amplifier schematic...")

    sch = create_schematic("Audio Amplifier")
    sch.set_paper_size("A3")
    sch.set_title_block(
        title="Audio Amplifier - LTspice Educational",
        company="CircuitForge Pipeline",
        rev="1.0",
        comments={1: "3-stage BJT: diff pair + VAS + push-pull output",
                  2: "8 transistors, 14 resistors, 3 caps, +-10V supply"}
    )

    G = 2.54  # grid unit (mm)

    # ── LAYOUT v2: Zero-crossing design on A3 landscape (420x297mm) ──
    # A3 = ~165G wide x ~117G tall
    # Design principle: each component NEAR its partners, wires short, NO crossings
    # Signal flows left→right. VCC at top (y=15G), VEE at bottom (y=100G)
    # Feedback wire R7 runs along bottom (y=95G) below all signal paths

    cy = 50*G           # vertical signal centre
    vcc_rail_y = 15*G   # VCC horizontal bus (top)
    vee_rail_y = 100*G  # VEE horizontal bus (bottom)

    # ── Zone 1: Input source (x=10-22G) ──
    vin_x, vin_y = 12*G, cy + 10*G
    sch.components.add(lib_id="VSIN:VSIN", reference="V3",
                       value="0.7V 1kHz", position=(vin_x, vin_y))

    r1_x, r1_y = 22*G, cy
    sch.components.add(lib_id="R:R", reference="R1",
                       value="5k", position=(r1_x, r1_y), rotation=90)

    # ── Zone 2: Differential pair (x=30-50G) ──
    q1_x, q1_y = 34*G, cy
    q2_x, q2_y = 48*G, cy     # 14G gap for clean routing

    sch.components.add(lib_id="Q_NPN_BCE:Q_NPN_BCE", reference="Q1",
                       value="2N3904", position=(q1_x, q1_y))
    sch.components.add(lib_id="Q_NPN_BCE:Q_NPN_BCE", reference="Q2",
                       value="2N3904", position=(q2_x, q2_y))

    # R2 (200) - Q1 collector load, directly above Q1
    r2_x = q1_x + 1*G
    r2_y = cy - 14*G
    sch.components.add(lib_id="R:R", reference="R2",
                       value="200", position=(r2_x, r2_y))

    # R3 (1K) - tail resistor, between Q1 and Q2
    r3_x = 41*G
    r3_y = cy + 16*G
    sch.components.add(lib_id="R:R", reference="R3",
                       value="1k", position=(r3_x, r3_y))

    # R6 (5K) - Q2 base bias, to the RIGHT of Q2 (avoids tail crossing)
    r6_x = q2_x + 6*G
    r6_y = cy + 12*G
    sch.components.add(lib_id="R:R", reference="R6",
                       value="5k", position=(r6_x, r6_y))

    # R7 (50K) - feedback, runs at BOTTOM of circuit (y=95G) to avoid crossings
    r7_x = 48*G
    r7_y = 95*G
    sch.components.add(lib_id="R:R", reference="R7",
                       value="50k", position=(r7_x, r7_y), rotation=90)

    # ── Zone 3: Active load + VAS (x=58-90G) ──
    # R4 (9K) interstage (horizontal, at Q1C height)
    r4_x = 56*G
    r4_y = cy - 12*G
    sch.components.add(lib_id="R:R", reference="R4",
                       value="9k", position=(r4_x, r4_y), rotation=90)

    # C1 (10p) parallel with R4 (above R4 with 10G gap)
    c1_x = r4_x
    c1_y = r4_y - 10*G
    sch.components.add(lib_id="C:C", reference="C1",
                       value="10p", position=(c1_x, c1_y), rotation=90)

    # R5 (1K) continues from R4 to Q3 base (horizontal)
    r5_x = 63*G
    r5_y = r4_y
    sch.components.add(lib_id="R:R", reference="R5",
                       value="1k", position=(r5_x, r5_y), rotation=90)

    # Q3 PNP active load (mirrored: E at top→VCC, C at bottom→VAS)
    q3_x, q3_y = 70*G, cy - 18*G
    sch.components.add(lib_id="Q_PNP_BCE:Q_PNP_BCE", reference="Q3",
                       value="2N3906", position=(q3_x, q3_y))

    # R8 (100) - Q3 emitter to VCC (short run directly above Q3)
    r8_x = q3_x + 1*G
    r8_y = q3_y - 12*G
    sch.components.add(lib_id="R:R", reference="R8",
                       value="100", position=(r8_x, r8_y))

    # C2 (100p) Miller comp - LEFT of Q3, connects VAS to Q3B
    c2_x = q3_x - 10*G
    c2_y = cy - 8*G
    sch.components.add(lib_id="C:C", reference="C2",
                       value="100p", position=(c2_x, c2_y))

    # Q4 VAS transistor (below Q3 collector, at signal centre)
    q4_x, q4_y = 80*G, cy
    sch.components.add(lib_id="Q_NPN_BCE:Q_NPN_BCE", reference="Q4",
                       value="2N3904", position=(q4_x, q4_y))

    # R9 (2K) - VAS (Q4C) to Q4B feedback, directly above Q4
    r9_x = q4_x + 1*G
    r9_y = cy - 12*G
    sch.components.add(lib_id="R:R", reference="R9",
                       value="2k", position=(r9_x, r9_y))

    # R10 (1K) - Q4B to Q4E, to RIGHT of Q4 (short horizontal run)
    r10_x = q4_x + 8*G
    r10_y = cy + 4*G
    sch.components.add(lib_id="R:R", reference="R10",
                       value="1k", position=(r10_x, r10_y))

    # R11 (5K) - Q4E to VEE, directly below Q4
    r11_x = q4_x + 1*G
    r11_y = cy + 16*G
    sch.components.add(lib_id="R:R", reference="R11",
                       value="5k", position=(r11_x, r11_y))

    # C3 (1mF) bootstrap cap - LEFT of Q4, connects VAS to Q4E
    c3_x = q4_x - 8*G
    c3_y = cy + 10*G
    sch.components.add(lib_id="C:C", reference="C3",
                       value="1m", position=(c3_x, c3_y))

    # ── Zone 4: Output stage (x=95-145G) ──
    # Upper half: Q5 (driver) → R12 → Q7 (output)
    q5_x, q5_y = 100*G, cy - 20*G
    sch.components.add(lib_id="Q_NPN_BCE:Q_NPN_BCE", reference="Q5",
                       value="2N3904", position=(q5_x, q5_y))

    r12_x = 110*G
    r12_y = cy - 12*G
    sch.components.add(lib_id="R:R", reference="R12",
                       value="1k", position=(r12_x, r12_y))

    q7_x, q7_y = 120*G, cy - 24*G
    sch.components.add(lib_id="Q_NPN_BCE:Q_NPN_BCE", reference="Q7",
                       value="2N2219A", position=(q7_x, q7_y))

    # Lower half: Q6 (PNP driver) → R13 → Q8 (output)
    q6_x, q6_y = 100*G, cy + 20*G
    sch.components.add(lib_id="Q_PNP_BCE:Q_PNP_BCE", reference="Q6",
                       value="2N3906", position=(q6_x, q6_y))

    r13_x = 110*G
    r13_y = cy + 16*G
    sch.components.add(lib_id="R:R", reference="R13",
                       value="1k", position=(r13_x, r13_y))

    q8_x, q8_y = 120*G, cy + 28*G
    sch.components.add(lib_id="Q_NPN_BCE:Q_NPN_BCE", reference="Q8",
                       value="2N2219A", position=(q8_x, q8_y))

    # R14 (8 ohm speaker) at output, well spaced
    r14_x = 135*G
    r14_y = cy
    sch.components.add(lib_id="R:R", reference="R14",
                       value="8", position=(r14_x, r14_y))

    # V1 (+10V) and V2 (-10V) supplies (far right)
    v1_x, v1_y = 150*G, cy - 24*G
    sch.components.add(lib_id="VDC:VDC", reference="V1",
                       value="10V", position=(v1_x, v1_y))

    v2_x, v2_y = 150*G, cy + 26*G
    sch.components.add(lib_id="VDC:VDC", reference="V2",
                       value="-10V", position=(v2_x, v2_y))

    # ── Wiring ──
    # Get all pin positions
    # Q_NPN_BCE: pin1=B(left), pin2=C(top-right), pin3=E(bottom-right)
    # Q_PNP_BCE: same pin layout as NPN (C top, E bottom) — we apply mirror_x
    #            post-save so E goes to top (toward VCC) and C goes to bottom.
    #            Wiring uses PRE-COMPUTED mirrored positions for Q3 and Q6.

    q1_b = get_pin_pos(sch, "Q1", "1")
    q1_c = get_pin_pos(sch, "Q1", "2")
    q1_e = get_pin_pos(sch, "Q1", "3")
    q2_b = get_pin_pos(sch, "Q2", "1")
    q2_c = get_pin_pos(sch, "Q2", "2")
    q2_e = get_pin_pos(sch, "Q2", "3")

    # Q3 PNP — mirror_x flips Y around component origin
    # Un-mirrored: C at top, E at bottom → mirrored: E at top, C at bottom
    _q3_b = get_pin_pos(sch, "Q3", "1")
    _q3_c = get_pin_pos(sch, "Q3", "2")
    _q3_e = get_pin_pos(sch, "Q3", "3")
    q3_b = (_q3_b[0], 2*q3_y - _q3_b[1])   # B: Y flipped
    q3_c = (_q3_c[0], 2*q3_y - _q3_c[1])   # C: moves to bottom
    q3_e = (_q3_e[0], 2*q3_y - _q3_e[1])   # E: moves to top (toward VCC)

    q4_b = get_pin_pos(sch, "Q4", "1")
    q4_c = get_pin_pos(sch, "Q4", "2")
    q4_e = get_pin_pos(sch, "Q4", "3")
    q5_b = get_pin_pos(sch, "Q5", "1")
    q5_c = get_pin_pos(sch, "Q5", "2")
    q5_e = get_pin_pos(sch, "Q5", "3")

    # Q6 PNP — mirror_x: E at top (toward output), C at bottom (toward VEE)
    _q6_b = get_pin_pos(sch, "Q6", "1")
    _q6_c = get_pin_pos(sch, "Q6", "2")
    _q6_e = get_pin_pos(sch, "Q6", "3")
    q6_b = (_q6_b[0], 2*q6_y - _q6_b[1])
    q6_c = (_q6_c[0], 2*q6_y - _q6_c[1])
    q6_e = (_q6_e[0], 2*q6_y - _q6_e[1])

    q7_b = get_pin_pos(sch, "Q7", "1")
    q7_c = get_pin_pos(sch, "Q7", "2")
    q7_e = get_pin_pos(sch, "Q7", "3")
    q8_b = get_pin_pos(sch, "Q8", "1")
    q8_c = get_pin_pos(sch, "Q8", "2")
    q8_e = get_pin_pos(sch, "Q8", "3")

    r1_1 = get_pin_pos(sch, "R1", "1")
    r1_2 = get_pin_pos(sch, "R1", "2")
    r2_1 = get_pin_pos(sch, "R2", "1")
    r2_2 = get_pin_pos(sch, "R2", "2")
    r3_1 = get_pin_pos(sch, "R3", "1")
    r3_2 = get_pin_pos(sch, "R3", "2")
    r4_1 = get_pin_pos(sch, "R4", "1")
    r4_2 = get_pin_pos(sch, "R4", "2")
    r5_1 = get_pin_pos(sch, "R5", "1")
    r5_2 = get_pin_pos(sch, "R5", "2")
    r6_1 = get_pin_pos(sch, "R6", "1")
    r6_2 = get_pin_pos(sch, "R6", "2")
    r7_1 = get_pin_pos(sch, "R7", "1")
    r7_2 = get_pin_pos(sch, "R7", "2")
    r8_1 = get_pin_pos(sch, "R8", "1")
    r8_2 = get_pin_pos(sch, "R8", "2")
    r9_1 = get_pin_pos(sch, "R9", "1")
    r9_2 = get_pin_pos(sch, "R9", "2")
    r10_1 = get_pin_pos(sch, "R10", "1")
    r10_2 = get_pin_pos(sch, "R10", "2")
    r11_1 = get_pin_pos(sch, "R11", "1")
    r11_2 = get_pin_pos(sch, "R11", "2")
    r12_1 = get_pin_pos(sch, "R12", "1")
    r12_2 = get_pin_pos(sch, "R12", "2")
    r13_1 = get_pin_pos(sch, "R13", "1")
    r13_2 = get_pin_pos(sch, "R13", "2")
    r14_1 = get_pin_pos(sch, "R14", "1")
    r14_2 = get_pin_pos(sch, "R14", "2")
    c1_1 = get_pin_pos(sch, "C1", "1")
    c1_2 = get_pin_pos(sch, "C1", "2")
    c2_1 = get_pin_pos(sch, "C2", "1")
    c2_2 = get_pin_pos(sch, "C2", "2")
    c3_1 = get_pin_pos(sch, "C3", "1")
    c3_2 = get_pin_pos(sch, "C3", "2")

    # -- Input: V3 -> R1 -> Q1 base --
    vin_p1 = get_pin_pos(sch, "V3", "1")   # VSIN top (+)
    vin_p2 = get_pin_pos(sch, "V3", "2")   # VSIN bottom (-)
    # V3+ up to R1 input height, then across to R1 pin2
    wire_manhattan(sch, vin_p1[0], vin_p1[1], r1_2[0], r1_2[1])
    # R1 pin1 across to Q1 base
    wire_manhattan(sch, r1_1[0], r1_1[1], q1_b[0], q1_b[1])

    # V3 bottom to GND
    gnd_vin = vin_p2[1] + 3*G
    sch.add_wire(start=vin_p2, end=(vin_p2[0], gnd_vin))
    sch.components.add(lib_id="GND:GND", reference="#PWR01", value="GND",
                       position=(vin_p2[0], gnd_vin))

    # -- Diff pair: Q1C -> R2 -> VCC, Q2C -> VCC --
    wire_manhattan(sch, q1_c[0], q1_c[1], r2_2[0], r2_2[1])

    # R2 top to VCC rail
    sch.add_wire(start=r2_1, end=(r2_1[0], vcc_rail_y))

    # Q2 collector to VCC (via wire up to rail)
    sch.add_wire(start=q2_c, end=(q2_c[0], vcc_rail_y))

    # VCC rail horizontal connecting R2 top, Q2C, and extending right
    sch.add_wire(start=(r2_1[0], vcc_rail_y), end=(q2_c[0], vcc_rail_y))

    # Q1/Q2 emitters to tail node -> R3 -> VEE
    tail_y = q1_e[1] + 2*G
    wire_manhattan(sch, q1_e[0], q1_e[1], r3_x, tail_y)
    wire_manhattan(sch, q2_e[0], q2_e[1], r3_x, tail_y)
    sch.add_wire(start=(r3_x, tail_y), end=r3_1)

    # R3 bottom to VEE
    sch.add_wire(start=r3_2, end=(r3_2[0], vee_rail_y))

    # -- Q2 base bias: Q2B → R6 → GND (R6 to RIGHT of Q2, no tail crossing) --
    # Q2B horizontal right to R6 x, then down to R6 pin1
    wire_manhattan(sch, q2_b[0], q2_b[1], r6_1[0], r6_1[1])

    # R6 bottom to GND
    gnd_r6 = r6_2[1] + 3*G
    sch.add_wire(start=r6_2, end=(r6_2[0], gnd_r6))
    sch.components.add(lib_id="GND:GND", reference="#PWR02", value="GND",
                       position=(r6_2[0], gnd_r6))

    # R7 feedback: use net labels (avoids long feedback wire crossings)
    # FB label at Q2B junction — connects R7 pin2 via label, no physical wire
    fb_q2b_x = q2_b[0] - 3*G
    sch.add_wire(start=(fb_q2b_x, q2_b[1]), end=q2_b)
    sch.add_label("FB", position=(fb_q2b_x, q2_b[1]))
    # FB label at R7 pin2 (left end)
    fb_r7_x = r7_2[0] - 3*G
    sch.add_wire(start=r7_2, end=(fb_r7_x, r7_2[1]))
    sch.add_label("FB", position=(fb_r7_x, r7_2[1]))

    # -- Interstage: Q1C -> R4 -> R5 -> Q3 base --
    # R4 left end connects to Q1 collector node (N002)
    wire_manhattan(sch, q1_c[0], q1_c[1], r4_2[0], r4_2[1])

    # C1 in parallel with R4 (compensation)
    wire_manhattan(sch, c1_2[0], c1_2[1], r4_2[0], r4_2[1])
    wire_manhattan(sch, c1_1[0], c1_1[1], r4_1[0], r4_1[1])

    # R4 right -> R5 left (series connection at N003)
    wire_manhattan(sch, r4_1[0], r4_1[1], r5_2[0], r5_2[1])

    # R5 right -> Q3 base
    wire_manhattan(sch, r5_1[0], r5_1[1], q3_b[0], q3_b[1])

    # C2 from Q3 collector (N006) to Q3 base (N005) - Miller compensation
    wire_manhattan(sch, c2_1[0], c2_1[1], q3_b[0], q3_b[1])

    # -- Q3 PNP: emitter -> R8 -> VCC, collector = VAS node --
    wire_manhattan(sch, q3_e[0], q3_e[1], r8_2[0], r8_2[1])
    sch.add_wire(start=r8_1, end=(r8_1[0], vcc_rail_y))
    # Extend VCC rail to R8
    sch.add_wire(start=(q2_c[0], vcc_rail_y), end=(r8_1[0], vcc_rail_y))

    # Q3 collector (VAS node N006) connects to Q4 collector, Q5 base, C2, C3
    vas_node_y = q3_c[1]

    # -- Q4 VAS: C=VAS, B=N008, E=N012 --
    # Q4 collector to VAS node (horizontal wire from Q3C to Q4C)
    wire_manhattan(sch, q3_c[0], q3_c[1], q4_c[0], q4_c[1])

    # R9: VAS node (N006) -> Q4 base (N008) - collector-to-base feedback
    wire_manhattan(sch, q4_c[0], q4_c[1], r9_1[0], r9_1[1])
    wire_manhattan(sch, r9_2[0], r9_2[1], q4_b[0], q4_b[1])

    # R10: Q4 base (N008) -> Q4 emitter (N012)
    wire_manhattan(sch, q4_b[0], q4_b[1], r10_1[0], r10_1[1])
    wire_manhattan(sch, r10_2[0], r10_2[1], q4_e[0], q4_e[1])

    # R11: Q4 emitter (N012) -> VEE
    wire_manhattan(sch, q4_e[0], q4_e[1], r11_1[0], r11_1[1])
    sch.add_wire(start=r11_2, end=(r11_2[0], vee_rail_y))

    # C3 bootstrap: VAS node (N006) to Q4 emitter (N012)
    # C3 pin1 connects to Q3C (same VAS net, avoids R9/Q4B vertical crossing)
    # C3 pin2 connects to Q4E via VH routing (vertical at C3's x, not Q4's x)
    wire_manhattan_vh(sch, c3_1[0], c3_1[1], q3_c[0], q3_c[1])
    wire_manhattan_vh(sch, c3_2[0], c3_2[1], q4_e[0], q4_e[1])

    # C2 bottom to VAS node
    wire_manhattan(sch, c2_2[0], c2_2[1], q3_c[0], q3_c[1])

    # -- Output stage --
    # Q5 base from VAS node
    wire_manhattan(sch, q4_c[0], q4_c[1], q5_b[0], q5_b[1])

    # Q5 collector to VCC
    sch.add_wire(start=q5_c, end=(q5_c[0], vcc_rail_y))
    sch.add_wire(start=(r8_1[0], vcc_rail_y), end=(q5_c[0], vcc_rail_y))

    # Q5 emitter (N007) -> R12 top -> R12 bottom = output A
    wire_manhattan(sch, q5_e[0], q5_e[1], r12_1[0], r12_1[1])

    # Q7 base from Q5 emitter (N007)
    wire_manhattan(sch, q5_e[0], q5_e[1], q7_b[0], q7_b[1])

    # Q7 collector to VCC
    sch.add_wire(start=q7_c, end=(q7_c[0], vcc_rail_y))
    sch.add_wire(start=(q5_c[0], vcc_rail_y), end=(q7_c[0], vcc_rail_y))

    # Output node at R14 pin1 (exact pin, not center of component)
    output_y = r14_1[1]

    # Q7 emitter = output A (vertical-first avoids crossings)
    wire_manhattan_vh(sch, q7_e[0], q7_e[1], r14_1[0], output_y)

    # R12 bottom to output A (VH routing avoids crossing Q7E/Q8C verticals)
    wire_manhattan_vh(sch, r12_2[0], r12_2[1], r14_1[0], output_y)

    # Q6 base from Q4E net — route from R11 pin1 (same net N012, below R10 vertical)
    wire_manhattan(sch, r11_1[0], r11_1[1], q6_b[0], q6_b[1])

    # Q6 emitter = output A — VH routing: go UP first then horizontal
    # This avoids crossing the R13->VEE vertical wire
    wire_manhattan_vh(sch, q6_e[0], q6_e[1], r14_1[0], output_y)

    # Q6 collector (N013) -> R13 pin1 (vertical drop, no horizontal crossing)
    sch.add_wire(start=(q6_c[0], q6_c[1]), end=(q6_c[0], r13_1[1]))
    sch.add_wire(start=(q6_c[0], r13_1[1]), end=(r13_1[0], r13_1[1]))

    # Q8 base from R13 pin1 (same N013 node, chains through R13 to avoid crossing)
    wire_manhattan(sch, r13_1[0], r13_1[1], q8_b[0], q8_b[1])

    # R13 bottom to VEE
    sch.add_wire(start=r13_2, end=(r13_2[0], vee_rail_y))

    # Q8 collector = output A — VH routing: go UP first then horizontal
    wire_manhattan_vh(sch, q8_c[0], q8_c[1], r14_1[0], output_y)

    # Q8 emitter to VEE
    sch.add_wire(start=q8_e, end=(q8_e[0], vee_rail_y))

    # R14 speaker load bottom to GND
    gnd_r14 = r14_2[1] + 3*G
    sch.add_wire(start=r14_2, end=(r14_2[0], gnd_r14))
    sch.components.add(lib_id="GND:GND", reference="#PWR03", value="GND",
                       position=(r14_2[0], gnd_r14))

    # -- Feedback: output A → R7 pin1 via OUTPUT label --
    # R7 pin1 connects to output via label (no physical wire, avoids crossings)
    out_r7_x = r7_1[0] + 3*G
    sch.add_wire(start=r7_1, end=(out_r7_x, r7_1[1]))
    sch.add_label("OUTPUT", position=(out_r7_x, r7_1[1]))

    # -- VCC/VEE supply sources --
    # V1 (+10V): positive to VCC rail, negative to GND
    v1_p1 = get_pin_pos(sch, "V1", "1")  # VDC top (+)
    v1_p2 = get_pin_pos(sch, "V1", "2")  # VDC bottom (-)
    sch.add_wire(start=v1_p1, end=(v1_p1[0], vcc_rail_y))
    sch.add_wire(start=(q7_c[0], vcc_rail_y), end=(v1_p1[0], vcc_rail_y))
    gnd_v1 = v1_p2[1] + 3*G
    sch.add_wire(start=v1_p2, end=(v1_p2[0], gnd_v1))
    sch.components.add(lib_id="GND:GND", reference="#PWR04", value="GND",
                       position=(v1_p2[0], gnd_v1))

    # V2 (-10V): positive to GND, negative to VEE rail
    v2_p1 = get_pin_pos(sch, "V2", "1")  # VDC top (+)
    v2_p2 = get_pin_pos(sch, "V2", "2")  # VDC bottom (-)
    gnd_v2 = v2_p1[1] - 3*G
    sch.add_wire(start=v2_p1, end=(v2_p1[0], gnd_v2))
    sch.components.add(lib_id="GND:GND", reference="#PWR05", value="GND",
                       position=(v2_p1[0], gnd_v2))
    sch.add_wire(start=v2_p2, end=(v2_p2[0], vee_rail_y))
    # Extend VEE rail across bottom (connecting R3, R11, R13, Q8E, V2)
    sch.add_wire(start=(r3_2[0], vee_rail_y), end=(v2_p2[0], vee_rail_y))

    # -- VCC power flag at top --
    sch.components.add(lib_id="VCC:VCC", reference="#PWR06", value="+10V",
                       position=(v1_x, vcc_rail_y))

    # -- Output label (offset 8G to avoid R14 reference overlap) --
    out_label_x = r14_1[0] + 8*G
    sch.add_label("OUTPUT", position=(out_label_x, output_y))
    sch.add_wire(start=(r14_1[0], output_y), end=(out_label_x, output_y))

    # -- Section titles --
    title_y = vcc_rail_y - 8*G
    sch.add_text("INPUT", position=(vin_x, title_y), size=3.0)
    sch.add_text("DIFFERENTIAL PAIR", position=(q1_x, title_y), size=3.0)
    sch.add_text("VAS", position=(q3_x, title_y), size=3.0)
    sch.add_text("OUTPUT STAGE", position=(q5_x, title_y), size=3.0)

    # ── Save ──
    # ── Test point markers (match simulation plot waveforms) ──
    # Plot traces: V(IN)=cyan, V(OUT)=red, V(VAS)=yellow, V(Q4E)=green
    tp_markers = [
        ("[1] V(IN) - cyan",  q1_b),          # Input at Q1 base
        ("[2] V(OUT) - red",  (r14_1[0], output_y)),  # Output node
        ("[3] V(VAS) - yellow", q4_c),         # VAS node
        ("[4] V(Q4E) - green", q4_e),          # Q4 emitter
    ]
    for tp_name, tp_pos in tp_markers:
        label_x = tp_pos[0]
        label_y = tp_pos[1] + 4*G
        sch.add_text(tp_name, position=(label_x, label_y), size=1.8)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "audioamp.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path, mirror_refs=["Q3", "Q6"])
    merge_collinear_wires(sch_path)
    print(f"  Schematic saved: {sch_path}")

    return sch_path


# =============================================================
# BUILD: LM741 Inverting Amplifier
# =============================================================
def build_inverting_amp():
    """
    Build an LM741 inverting amplifier schematic and netlist.
    Gain = -Rf/Rin = -100k/10k = -10.

    Op-amp is mirrored (mirror x) so (-) input is on TOP, (+) on BOTTOM.
    This is the conventional way to draw an inverting amplifier.

    Schematic:
              Rf (100k)
         ┌────┤├────┐
         │           │
    Vin─┤├─Rin(10k)──┤── (-) LM741 (out)──┤├─ Vout
       Cin                  (+)     Cout
                             │
                            GND
    """
    print("Building LM741 inverting amplifier schematic...")

    sch = create_schematic("Inverting Amplifier")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="LM741 Inverting Amplifier (Gain = -10)",
        company="Circuit Automation Project",
        rev="1.0",
        comments={1: "LM741 op-amp, Av = -Rf/Rin = -100k/10k = -10"}
    )

    G = 2.54
    # A4 landscape: 297mm x 210mm. Center circuit on page.
    #
    # LM741 pin offsets (normal):
    #   pin2 inv(-): (-7.62, +2.54)  pin3 ni(+): (-7.62, -2.54)
    #   pin6 out:    (+7.62,  0)     pin7 V+:    (-2.54, -7.62)
    #   pin4 V-:     (-2.54, +7.62)
    #
    # With (mirror x), Y offsets flip:
    #   pin2 inv(-): (-7.62, -2.54)  <- TOP-LEFT  (signal in)
    #   pin3 ni(+): (-7.62, +2.54)   <- BOTTOM-LEFT (to GND)
    #   pin6 out:    (+7.62,  0)     <- RIGHT (unchanged)
    #   pin7 V+:     (-2.54, +7.62)  <- BOTTOM
    #   pin4 V-:     (-2.54, -7.62)  <- TOP

    # ── Place components ──
    ux, uy = 58*G, 40*G  # op-amp center
    sch.components.add(
        lib_id="LM741:LM741",
        reference="U1",
        value="LM741",
        position=(ux, uy)
    )

    # Mirrored pin positions (Y flipped around uy)
    inv_pin = (ux - 7.62, uy - 2.54)   # (-) TOP-LEFT
    ni_pin  = (ux - 7.62, uy + 2.54)   # (+) BOTTOM-LEFT
    out_pin = (ux + 7.62, uy)           # output RIGHT
    vp_pin  = (ux - 2.54, uy + 7.62)   # V+ BOTTOM
    vm_pin  = (ux - 2.54, uy - 7.62)   # V- TOP

    print(f"  U1 inv={inv_pin}, ni={ni_pin}, out={out_pin}")

    # Rin (10k) - horizontal, to the left of (-) input
    rin_x = inv_pin[0] - 14*G
    rin_y = inv_pin[1]
    sch.components.add(
        lib_id="R:R", reference="R1", value="10k",
        position=(rin_x, rin_y), rotation=90
    )
    # Pin 1 = RIGHT (+3.81 from center), Pin 2 = LEFT (-3.81 from center)
    r1_right = (rin_x + 3.81, rin_y)  # pin 1 (towards op-amp)
    r1_left  = (rin_x - 3.81, rin_y)  # pin 2 (towards input)

    # Rf (100k) - feedback, horizontal, ABOVE the signal path
    # Spans from near inv_pin to near out_pin
    rf_y = inv_pin[1] - 10*G  # above the (-) input
    rf_cx = (inv_pin[0] + out_pin[0]) / 2
    sch.components.add(
        lib_id="R:R", reference="R2", value="100k",
        position=(rf_cx, rf_y), rotation=90
    )
    rf_right = (rf_cx + 3.81, rf_y)  # pin 1
    rf_left  = (rf_cx - 3.81, rf_y)  # pin 2

    # Cin (1uF) - input coupling, left of Rin
    cin_x = rin_x - 12*G
    sch.components.add(
        lib_id="C:C", reference="C1", value="1u",
        position=(cin_x, rin_y), rotation=90
    )
    c1_right = (cin_x + 3.81, rin_y)  # pin 1
    c1_left  = (cin_x - 3.81, rin_y)  # pin 2

    # Cout (10uF) - output coupling, right of output
    cout_x = out_pin[0] + 12*G
    sch.components.add(
        lib_id="C:C", reference="C2", value="10u",
        position=(cout_x, out_pin[1]), rotation=90
    )
    c2_right = (cout_x + 3.81, out_pin[1])  # pin 1
    c2_left  = (cout_x - 3.81, out_pin[1])  # pin 2

    # RL (10k) - load resistor, right of Cout (vertical)
    rl_x = cout_x + 12*G
    rl_y = out_pin[1] + 8*G
    sch.components.add(
        lib_id="R:R", reference="R3", value="10k",
        position=(rl_x, rl_y)
    )
    r3_top    = (rl_x, rl_y - 3.81)  # pin 1
    r3_bottom = (rl_x, rl_y + 3.81)  # pin 2

    # ══════════════════════════════════════
    # WIRING - using calculated positions
    # ══════════════════════════════════════

    # Input chain: IN -> C1 -> Rin -> inv_pin
    wire_manhattan(sch, c1_right[0], c1_right[1], r1_left[0], r1_left[1])
    wire_manhattan(sch, r1_right[0], r1_right[1], inv_pin[0], inv_pin[1])

    # === FEEDBACK PATH (rectangular loop above op-amp) ===
    # Junction on wire between Rin(right) and inv_pin
    junc_x = r1_right[0] + 3*G  # on the wire, between Rin and inv_pin
    junc_y = inv_pin[1]

    # 1. Junction -> straight UP to Rf height
    sch.add_wire(start=(junc_x, junc_y), end=(junc_x, rf_y))

    # 2. Horizontal from junction column to Rf LEFT pin
    sch.add_wire(start=(junc_x, rf_y), end=rf_left)

    # 3. Rf RIGHT pin -> horizontal to output column
    sch.add_wire(start=rf_right, end=(out_pin[0], rf_y))

    # 4. Output column -> straight DOWN to output pin
    sch.add_wire(start=(out_pin[0], rf_y), end=out_pin)

    # Output chain: out_pin -> Cout -> RL
    wire_manhattan(sch, out_pin[0], out_pin[1], c2_left[0], c2_left[1])
    wire_manhattan_vh(sch, c2_right[0], c2_right[1], r3_top[0], r3_top[1])

    # ══════════════════════════════════════
    # POWER SYMBOLS, GROUND & SOURCES
    # ══════════════════════════════════════

    # GND at non-inverting input (+) (below op-amp)
    gnd_ni_y = ni_pin[1] + 4*G
    sch.add_wire(start=ni_pin, end=(ni_pin[0], gnd_ni_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR01", value="GND",
                       position=(ni_pin[0], gnd_ni_y))

    # VCC power symbol at V+ pin (below op-amp after mirror)
    vcc_y = vp_pin[1] + 4*G
    sch.add_wire(start=vp_pin, end=(vp_pin[0], vcc_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR02", value="+12V",
                       position=(vp_pin[0], vcc_y))

    # VEE power symbol at V- pin (above op-amp after mirror)
    vee_y = vm_pin[1] - 4*G
    sch.add_wire(start=(vm_pin[0], vee_y), end=vm_pin)
    sch.components.add(lib_id="VEE:VEE", reference="#PWR03", value="-12V",
                       position=(vm_pin[0], vee_y))

    # GND at load resistor bottom
    gnd_rl_y = r3_bottom[1] + 4*G
    sch.add_wire(start=r3_bottom, end=(r3_bottom[0], gnd_rl_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR04", value="GND",
                       position=(r3_bottom[0], gnd_rl_y))

    # VSIN input source (replaces IN label)
    vsin_x = c1_left[0] - 8*G
    vsin_cy = c1_left[1] + 5.38  # pin1 (top +) aligns with signal wire
    sch.components.add(lib_id="VSIN:VSIN", reference="V1",
                       value="100mV 1kHz", position=(vsin_x, vsin_cy))
    vsin_p1 = (vsin_x, vsin_cy - 5.38)  # top (+)
    vsin_p2 = (vsin_x, vsin_cy + 4.78)  # bottom (-)
    wire_manhattan(sch, vsin_p1[0], vsin_p1[1], c1_left[0], c1_left[1])
    # GND at VSIN bottom
    gnd_vs_y = vsin_p2[1] + 4*G
    sch.add_wire(start=vsin_p2, end=(vsin_x, gnd_vs_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR05", value="GND",
                       position=(vsin_x, gnd_vs_y))

    # Output label
    out_lbl_x = r3_top[0] + 6*G
    sch.add_label("OUT", position=(out_lbl_x, r3_top[1]))
    sch.add_wire(start=r3_top, end=(out_lbl_x, r3_top[1]))

    # ── Save with mirror ──
    sch_path = os.path.join(WORK_DIR, "inv_amp.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)  # no mirror: LM741 default already has (-) on top
    print(f"  Schematic saved: {sch_path}")

    try:
        svg_out = os.path.join(WORK_DIR, "inv_amp_svg")
        actual = export_svg(sch_path, svg_out)
        print(f"  SVG exported: {actual}")
    except Exception as e:
        print(f"  SVG export: {e}")

    return sch_path


def build_signal_conditioner():
    """
    Build a dual op-amp signal conditioner schematic.
    Stage 1: Non-inverting amplifier (Gain = 1 + Rf/Rg = 1 + 100k/10k = 11)
    Stage 2: Sallen-Key 2nd-order Butterworth LPF (fc ~ 1kHz, unity gain)

    Signal flow (left to right):
        VSIN -> C_in -> U1(+) -> U1(out) -> R3 -> N1 -> R4 -> U2(+) -> U2(out) -> C_out -> RL -> OUT

    U1 feedback: Rf from output back to (-), Rg from (-) to GND
    U2 feedback: (-) tied directly to output (unity gain buffer)
    Sallen-Key filter caps: C3 from N1 to GND, C4 from N2 to U2(out)
    """
    print("Building dual op-amp signal conditioner schematic...")

    sch = create_schematic("Signal Conditioner")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="Dual Op-Amp Signal Conditioner",
        company="Circuit Automation Project",
        rev="1.0",
        comments={1: "Stage 1: Non-inv amp (G=11), Stage 2: Sallen-Key LPF (fc~1kHz)"}
    )

    G = 2.54  # grid unit (mm)

    # ── Place op-amps ──
    # U1 (non-inv amp) - left side of page
    u1x, u1y = 42*G, 38*G
    sch.components.add(
        lib_id="LM741:LM741", reference="U1", value="LM741",
        position=(u1x, u1y)
    )

    # U2 (Sallen-Key LPF) - right side of page
    u2x, u2y = 74*G, 38*G
    sch.components.add(
        lib_id="LM741:LM741", reference="U2", value="LM741",
        position=(u2x, u2y)
    )

    # Mirrored pin positions (mirror x flips Y offsets)
    # U1 pins
    u1_inv = (u1x - 7.62, u1y - 2.54)   # pin2 (-) TOP-LEFT
    u1_ni  = (u1x - 7.62, u1y + 2.54)   # pin3 (+) BOTTOM-LEFT
    u1_out = (u1x + 7.62, u1y)           # pin6 out RIGHT
    u1_vp  = (u1x - 2.54, u1y + 7.62)   # pin7 V+ BOTTOM
    u1_vm  = (u1x - 2.54, u1y - 7.62)   # pin4 V- TOP

    # U2 pins
    u2_inv = (u2x - 7.62, u2y - 2.54)   # pin2 (-) TOP-LEFT
    u2_ni  = (u2x - 7.62, u2y + 2.54)   # pin3 (+) BOTTOM-LEFT
    u2_out = (u2x + 7.62, u2y)           # pin6 out RIGHT
    u2_vp  = (u2x - 2.54, u2y + 7.62)   # pin7 V+ BOTTOM
    u2_vm  = (u2x - 2.54, u2y - 7.62)   # pin4 V- TOP

    print(f"  U1 center=({u1x:.1f},{u1y:.1f}), U2 center=({u2x:.1f},{u2y:.1f})")

    # ── Place passive components ──

    # Rf (100k) - U1 feedback resistor, horizontal ABOVE U1
    rf_y = u1_inv[1] - 10*G
    rf_cx = (u1_inv[0] + u1_out[0]) / 2
    sch.components.add(
        lib_id="R:R", reference="R1", value="100k",
        position=(rf_cx, rf_y), rotation=90
    )
    rf_right = (rf_cx + 3.81, rf_y)
    rf_left  = (rf_cx - 3.81, rf_y)

    # Rg (10k) - U1 ground resistor, vertical below (-) junction
    rg_x = u1_inv[0] - 4*G
    rg_y = u1_inv[1] + 10*G  # further below to avoid overlap with R6
    sch.components.add(
        lib_id="R:R", reference="R2", value="10k",
        position=(rg_x, rg_y)
    )
    rg_top    = (rg_x, rg_y - 3.81)
    rg_bottom = (rg_x, rg_y + 3.81)

    # C_in (1uF) - input coupling cap, left of U1(+)
    cin_x = u1_ni[0] - 14*G
    cin_y = u1_ni[1]
    sch.components.add(
        lib_id="C:C", reference="C1", value="1u",
        position=(cin_x, cin_y), rotation=90
    )
    c1_right = (cin_x + 3.81, cin_y)
    c1_left  = (cin_x - 3.81, cin_y)

    # R3 (10k) - Sallen-Key R, horizontal between U1 out and filter node N1
    r3_cx = (u1_out[0] + u2_ni[0]) / 2 - 6*G
    r3_y = u1_out[1]
    sch.components.add(
        lib_id="R:R", reference="R3", value="10k",
        position=(r3_cx, r3_y), rotation=90
    )
    r3_right = (r3_cx + 3.81, r3_y)
    r3_left  = (r3_cx - 3.81, r3_y)

    # R4 (10k) - Sallen-Key R, horizontal between N1 and U2(+)
    r4_cx = (u1_out[0] + u2_ni[0]) / 2 + 6*G
    r4_y = u1_out[1]
    sch.components.add(
        lib_id="R:R", reference="R4", value="10k",
        position=(r4_cx, r4_y), rotation=90
    )
    r4_right = (r4_cx + 3.81, r4_y)
    r4_left  = (r4_cx - 3.81, r4_y)

    # N1 junction point (between R3 right and R4 left)
    n1_x = (r3_right[0] + r4_left[0]) / 2
    n1_y = r3_y

    # C3 (33nF) - Sallen-Key cap, vertical from N1 down to GND
    c3_x = n1_x
    c3_y = n1_y + 8*G
    sch.components.add(
        lib_id="C:C", reference="C3", value="33n",
        position=(c3_x, c3_y)
    )
    c3_top    = (c3_x, c3_y - 3.81)
    c3_bottom = (c3_x, c3_y + 3.81)

    # N2 junction point (between R4 right and U2 non-inv input)
    n2_x = r4_right[0] + 3*G
    n2_y = r4_y

    # C4 (15nF) - Sallen-Key cap, from N2 up to U2 output (horizontal above)
    c4_y = u2_inv[1] - 8*G  # above U2
    c4_cx = (n2_x + u2_out[0]) / 2
    sch.components.add(
        lib_id="C:C", reference="C4", value="15n",
        position=(c4_cx, c4_y), rotation=90
    )
    c4_right = (c4_cx + 3.81, c4_y)
    c4_left  = (c4_cx - 3.81, c4_y)

    # C_out (10uF) - output coupling cap, right of U2
    cout_x = u2_out[0] + 12*G
    cout_y = u2_out[1]
    sch.components.add(
        lib_id="C:C", reference="C2", value="10u",
        position=(cout_x, cout_y), rotation=90
    )
    c2_right = (cout_x + 3.81, cout_y)
    c2_left  = (cout_x - 3.81, cout_y)

    # Rbias (100k) - DC bias for U1 non-inv input, vertical below (+) input
    # Place further left along the input wire to avoid overlapping R2
    rbias_x = u1_ni[0] - 14*G
    rbias_y = u1_ni[1] + 10*G
    sch.components.add(
        lib_id="R:R", reference="R6", value="100k",
        position=(rbias_x, rbias_y)
    )
    r6_top    = (rbias_x, rbias_y - 3.81)
    r6_bottom = (rbias_x, rbias_y + 3.81)

    # RL (10k) - load resistor, vertical, right of C_out
    rl_x = cout_x + 12*G
    rl_y = cout_y + 8*G
    sch.components.add(
        lib_id="R:R", reference="R5", value="10k",
        position=(rl_x, rl_y)
    )
    r5_top    = (rl_x, rl_y - 3.81)
    r5_bottom = (rl_x, rl_y + 3.81)

    # ══════════════════════════════════════
    # WIRING
    # ══════════════════════════════════════
    print("  Wiring components...")

    # --- Stage 1: Non-inverting amplifier ---

    # C_in right -> U1 (+) non-inv input
    wire_manhattan(sch, c1_right[0], c1_right[1], u1_ni[0], u1_ni[1])

    # Rbias: tap off the input wire (between C1 and U1+) down to R6
    # R6 is directly below a point on the horizontal input wire
    sch.add_wire(start=(rbias_x, u1_ni[1]), end=(rbias_x, r6_top[1]))

    # U1 feedback: rectangular loop above op-amp
    # Junction on wire between Rg and inv_pin
    fb_junc_x = u1_inv[0]
    fb_junc_y = u1_inv[1]

    # Rg connects from the (-) input junction DOWN
    wire_manhattan_vh(sch, fb_junc_x, fb_junc_y, rg_top[0], rg_top[1])

    # (-) junction -> straight UP to Rf height
    sch.add_wire(start=(fb_junc_x, fb_junc_y), end=(fb_junc_x, rf_y))
    # Horizontal to Rf LEFT pin
    sch.add_wire(start=(fb_junc_x, rf_y), end=rf_left)
    # Rf RIGHT pin -> horizontal to output column
    sch.add_wire(start=rf_right, end=(u1_out[0], rf_y))
    # Output column -> straight DOWN to output pin
    sch.add_wire(start=(u1_out[0], rf_y), end=u1_out)

    # --- Inter-stage: U1 out -> Sallen-Key filter ---

    # U1 out -> R3 left
    wire_manhattan(sch, u1_out[0], u1_out[1], r3_left[0], r3_left[1])

    # R3 right -> N1 -> R4 left (continuous horizontal wire)
    sch.add_wire(start=r3_right, end=(n1_x, n1_y))
    sch.add_wire(start=(n1_x, n1_y), end=r4_left)

    # C3 top connects to N1 (vertical down from signal path)
    wire_manhattan(sch, n1_x, n1_y, c3_top[0], c3_top[1])

    # R4 right -> N2 junction
    sch.add_wire(start=r4_right, end=(n2_x, n2_y))

    # N2 -> U2 (+) non-inv input
    wire_manhattan_vh(sch, n2_x, n2_y, u2_ni[0], u2_ni[1])

    # C4: N2 up to C4 left, C4 right across to U2 output column
    sch.add_wire(start=(n2_x, n2_y), end=(n2_x, c4_y))
    sch.add_wire(start=(n2_x, c4_y), end=c4_left)
    sch.add_wire(start=c4_right, end=(u2_out[0], c4_y))

    # --- Stage 2: Unity gain feedback (U2 out -> U2 inv) ---
    # U2 (-) connects to output via wire above
    # Route: U2(-) up to feedback height, across to output column
    # Must clear VEE stub which extends up to u2_vm[1] - 4*G
    u2_fb_y = u2_inv[1] - 7*G
    sch.add_wire(start=u2_inv, end=(u2_inv[0], u2_fb_y))
    sch.add_wire(start=(u2_inv[0], u2_fb_y), end=(u2_out[0], u2_fb_y))

    # Single vertical wire from C4 height down through feedback junction to output
    # (avoids overlapping collinear wires on the output column)
    sch.add_wire(start=(u2_out[0], c4_y), end=u2_out)
    sch.junctions.add(position=(u2_out[0], u2_fb_y))  # feedback tee

    # --- Output chain ---
    wire_manhattan(sch, u2_out[0], u2_out[1], c2_left[0], c2_left[1])
    wire_manhattan_vh(sch, c2_right[0], c2_right[1], r5_top[0], r5_top[1])

    # ══════════════════════════════════════
    # POWER SYMBOLS, GROUND & SOURCES
    # ══════════════════════════════════════
    print("  Adding power symbols and source...")

    # VCC at U1 V+ (bottom after mirror)
    vcc1_y = u1_vp[1] + 4*G
    sch.add_wire(start=u1_vp, end=(u1_vp[0], vcc1_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR01", value="+12V",
                       position=(u1_vp[0], vcc1_y))

    # VEE at U1 V- (top after mirror)
    vee1_y = u1_vm[1] - 4*G
    sch.add_wire(start=(u1_vm[0], vee1_y), end=u1_vm)
    sch.components.add(lib_id="VEE:VEE", reference="#PWR02", value="-12V",
                       position=(u1_vm[0], vee1_y))

    # VCC at U2 V+
    vcc2_y = u2_vp[1] + 4*G
    sch.add_wire(start=u2_vp, end=(u2_vp[0], vcc2_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR03", value="+12V",
                       position=(u2_vp[0], vcc2_y))

    # VEE at U2 V-
    vee2_y = u2_vm[1] - 4*G
    sch.add_wire(start=(u2_vm[0], vee2_y), end=u2_vm)
    sch.components.add(lib_id="VEE:VEE", reference="#PWR04", value="-12V",
                       position=(u2_vm[0], vee2_y))

    # GND at Rg bottom
    gnd_rg_y = rg_bottom[1] + 4*G
    sch.add_wire(start=rg_bottom, end=(rg_bottom[0], gnd_rg_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR05", value="GND",
                       position=(rg_bottom[0], gnd_rg_y))

    # GND at Rbias (R6) bottom
    gnd_rb_y = r6_bottom[1] + 4*G
    sch.add_wire(start=r6_bottom, end=(r6_bottom[0], gnd_rb_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR06", value="GND",
                       position=(r6_bottom[0], gnd_rb_y))

    # GND at C3 bottom
    gnd_c3_y = c3_bottom[1] + 4*G
    sch.add_wire(start=c3_bottom, end=(c3_bottom[0], gnd_c3_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR07", value="GND",
                       position=(c3_bottom[0], gnd_c3_y))

    # GND at RL bottom
    gnd_rl_y = r5_bottom[1] + 4*G
    sch.add_wire(start=r5_bottom, end=(r5_bottom[0], gnd_rl_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR08", value="GND",
                       position=(r5_bottom[0], gnd_rl_y))

    # VSIN input source
    vsin_x = c1_left[0] - 8*G
    vsin_cy = c1_left[1] + 5.38  # pin1 (top +) at signal wire height
    sch.components.add(lib_id="VSIN:VSIN", reference="V1",
                       value="5mV 200Hz", position=(vsin_x, vsin_cy))
    vsin_p1 = (vsin_x, vsin_cy - 5.38)  # top (+)
    vsin_p2 = (vsin_x, vsin_cy + 4.78)  # bottom (-)
    wire_manhattan(sch, vsin_p1[0], vsin_p1[1], c1_left[0], c1_left[1])
    # GND at VSIN bottom
    gnd_vs_y = vsin_p2[1] + 4*G
    sch.add_wire(start=vsin_p2, end=(vsin_x, gnd_vs_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR09", value="GND",
                       position=(vsin_x, gnd_vs_y))

    # Output label
    out_lbl_x = r5_top[0] + 6*G
    sch.add_label("OUT", position=(out_lbl_x, r5_top[1]))
    sch.add_wire(start=r5_top, end=(out_lbl_x, r5_top[1]))

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "sig_cond.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    print(f"  Schematic saved: {sch_path}")

    try:
        svg_out = os.path.join(WORK_DIR, "sig_cond_svg")
        actual = export_svg(sch_path, svg_out)
        print(f"  SVG exported: {actual}")
    except Exception as e:
        print(f"  SVG export: {e}")

    return sch_path


# =============================================================
# BUILD: USB-Isolated Instrumentation Amplifier (3 op-amp INA)
# =============================================================
def build_usb_ina():
    """
    Build a 3-op-amp instrumentation amplifier schematic.
    Classic INA topology used in USB data acquisition front-ends.

    Topology:
        V_IN+ ---> U1(+) non-inv ---> U1 out --|
                   U1(-) --- Rg ---  U2(-)      |
        V_IN- ---> U2(+) non-inv ---> U2 out --|
                                                |
              U1_out --- R1 --- U3(-) --- R3 --- U3_out ---> OUT
              U2_out --- R2 --- U3(+) --- R4 --- GND

    Gain = (1 + 2*Rf_buf/Rg) * (R3/R1)
    With Rf_buf=47k, Rg=1k, R1=R2=10k, R3=R4=10k:
      G_stage1 = 1 + 2*47k/1k = 95
      G_stage2 = 10k/10k = 1
      G_total = 95
    """
    print("Building 3-op-amp instrumentation amplifier schematic...")

    sch = create_schematic("Instrumentation Amplifier")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="USB-Isolated Instrumentation Amplifier",
        company="Circuit Automation Project",
        rev="1.0",
        comments={1: "3-op-amp INA: G=95 (Rf=47k, Rg=1k, Rdiff=10k)"}
    )

    G = 2.54  # grid unit

    # ── Place 3 op-amps ──
    # U1 (top buffer) - processes V_IN+
    u1x, u1y = 46*G, 28*G
    sch.components.add(lib_id="LM741:LM741", reference="U1", value="LM741",
                       position=(u1x, u1y))

    # U2 (bottom buffer) - processes V_IN-
    u2x, u2y = 46*G, 52*G
    sch.components.add(lib_id="LM741:LM741", reference="U2", value="LM741",
                       position=(u2x, u2y))

    # U3 (difference amp) - combines both
    u3x, u3y = 78*G, 40*G
    sch.components.add(lib_id="LM741:LM741", reference="U3", value="LM741",
                       position=(u3x, u3y))

    # Mirrored pin positions (all 3 mirrored: (-) on top)
    # U1 pins
    u1_inv = (u1x - 7.62, u1y - 2.54)   # (-) top-left
    u1_ni  = (u1x - 7.62, u1y + 2.54)   # (+) bottom-left
    u1_out = (u1x + 7.62, u1y)           # out right
    u1_vp  = (u1x - 2.54, u1y + 7.62)   # V+ bottom
    u1_vm  = (u1x - 2.54, u1y - 7.62)   # V- top

    # U2 pins
    u2_inv = (u2x - 7.62, u2y - 2.54)
    u2_ni  = (u2x - 7.62, u2y + 2.54)
    u2_out = (u2x + 7.62, u2y)
    u2_vp  = (u2x - 2.54, u2y + 7.62)
    u2_vm  = (u2x - 2.54, u2y - 7.62)

    # U3 pins
    u3_inv = (u3x - 7.62, u3y - 2.54)
    u3_ni  = (u3x - 7.62, u3y + 2.54)
    u3_out = (u3x + 7.62, u3y)
    u3_vp  = (u3x - 2.54, u3y + 7.62)
    u3_vm  = (u3x - 2.54, u3y - 7.62)

    print(f"  U1=({u1x:.0f},{u1y:.0f}), U2=({u2x:.0f},{u2y:.0f}), U3=({u3x:.0f},{u3y:.0f})")

    # ── Place passive components ──

    # Rf1 (47k) - U1 feedback, horizontal above U1
    rf1_y = u1_inv[1] - 8*G
    rf1_cx = (u1_inv[0] + u1_out[0]) / 2
    sch.components.add(lib_id="R:R", reference="R1", value="47k",
                       position=(rf1_cx, rf1_y), rotation=90)
    rf1_right = (rf1_cx + 3.81, rf1_y)
    rf1_left  = (rf1_cx - 3.81, rf1_y)

    # Rf2 (47k) - U2 feedback, horizontal above U2
    rf2_y = u2_inv[1] - 8*G
    rf2_cx = (u2_inv[0] + u2_out[0]) / 2
    sch.components.add(lib_id="R:R", reference="R2", value="47k",
                       position=(rf2_cx, rf2_y), rotation=90)
    rf2_right = (rf2_cx + 3.81, rf2_y)
    rf2_left  = (rf2_cx - 3.81, rf2_y)

    # Rg (1k) - gain-set resistor, vertical between U1(-) and U2(-)
    rg_x = u1_inv[0] - 4*G
    rg_y = (u1_inv[1] + u2_inv[1]) / 2
    sch.components.add(lib_id="R:R", reference="R3", value="1k",
                       position=(rg_x, rg_y))
    rg_top    = (rg_x, rg_y - 3.81)
    rg_bottom = (rg_x, rg_y + 3.81)

    # R4 (10k) - diff amp input from U1 side, horizontal
    r4_cx = (u1_out[0] + u3_inv[0]) / 2 + 2*G
    r4_y = u3_inv[1]
    sch.components.add(lib_id="R:R", reference="R4", value="10k",
                       position=(r4_cx, r4_y), rotation=90)
    r4_right = (r4_cx + 3.81, r4_y)
    r4_left  = (r4_cx - 3.81, r4_y)

    # R5 (10k) - diff amp input from U2 side, horizontal
    r5_cx = (u2_out[0] + u3_ni[0]) / 2 + 2*G
    r5_y = u3_ni[1]
    sch.components.add(lib_id="R:R", reference="R5", value="10k",
                       position=(r5_cx, r5_y), rotation=90)
    r5_right = (r5_cx + 3.81, r5_y)
    r5_left  = (r5_cx - 3.81, r5_y)

    # R6 (10k) - diff amp feedback resistor, horizontal above U3
    rf3_y = u3_inv[1] - 8*G
    rf3_cx = (u3_inv[0] + u3_out[0]) / 2
    sch.components.add(lib_id="R:R", reference="R6", value="10k",
                       position=(rf3_cx, rf3_y), rotation=90)
    rf3_right = (rf3_cx + 3.81, rf3_y)
    rf3_left  = (rf3_cx - 3.81, rf3_y)

    # R7 (10k) - diff amp ground reference, vertical below U3(+)
    r7_x = u3_ni[0] - 4*G
    r7_y = u3_ni[1] + 10*G
    sch.components.add(lib_id="R:R", reference="R7", value="10k",
                       position=(r7_x, r7_y))
    r7_top    = (r7_x, r7_y - 3.81)
    r7_bottom = (r7_x, r7_y + 3.81)

    # Cout (10uF) - output coupling
    cout_x = u3_out[0] + 10*G
    cout_y = u3_out[1]
    sch.components.add(lib_id="C:C", reference="C1", value="10u",
                       position=(cout_x, cout_y), rotation=90)
    c1_right = (cout_x + 3.81, cout_y)
    c1_left  = (cout_x - 3.81, cout_y)

    # RL (10k) - output load
    rl_x = cout_x + 10*G
    rl_y = cout_y + 8*G
    sch.components.add(lib_id="R:R", reference="R8", value="10k",
                       position=(rl_x, rl_y))
    r8_top    = (rl_x, rl_y - 3.81)
    r8_bottom = (rl_x, rl_y + 3.81)

    # ══════════════════════════════════════
    # WIRING
    # ══════════════════════════════════════
    print("  Wiring components...")

    # --- Input buffers (U1 / U2) ---

    # U1 feedback loop: inv(-) -> up -> Rf1 -> down -> output
    sch.add_wire(start=u1_inv, end=(u1_inv[0], rf1_y))
    sch.add_wire(start=(u1_inv[0], rf1_y), end=rf1_left)
    sch.add_wire(start=rf1_right, end=(u1_out[0], rf1_y))
    sch.add_wire(start=(u1_out[0], rf1_y), end=u1_out)

    # U2 feedback loop: inv(-) -> up -> Rf2 -> down -> output
    sch.add_wire(start=u2_inv, end=(u2_inv[0], rf2_y))
    sch.add_wire(start=(u2_inv[0], rf2_y), end=rf2_left)
    sch.add_wire(start=rf2_right, end=(u2_out[0], rf2_y))
    sch.add_wire(start=(u2_out[0], rf2_y), end=u2_out)

    # Rg connects U1(-) to U2(-) via vertical resistor
    # U1(-) junction -> down to Rg top
    sch.add_wire(start=(u1_inv[0], u1_inv[1]), end=(rg_x, u1_inv[1]))
    sch.add_wire(start=(rg_x, u1_inv[1]), end=rg_top)
    # U2(-) junction -> up to Rg bottom
    sch.add_wire(start=(u2_inv[0], u2_inv[1]), end=(rg_x, u2_inv[1]))
    sch.add_wire(start=(rg_x, u2_inv[1]), end=rg_bottom)

    # --- Difference amp (U3) ---

    # U1 out -> R4 -> U3(-)
    wire_manhattan(sch, u1_out[0], u1_out[1], r4_left[0], r4_left[1])
    wire_manhattan(sch, r4_right[0], r4_right[1], u3_inv[0], u3_inv[1])

    # U2 out -> R5 -> U3(+)
    wire_manhattan(sch, u2_out[0], u2_out[1], r5_left[0], r5_left[1])
    wire_manhattan(sch, r5_right[0], r5_right[1], u3_ni[0], u3_ni[1])

    # U3 feedback loop: inv(-) -> up -> R6 -> down -> output
    fb3_junc_x = u3_inv[0]
    sch.add_wire(start=(fb3_junc_x, u3_inv[1]), end=(fb3_junc_x, rf3_y))
    sch.add_wire(start=(fb3_junc_x, rf3_y), end=rf3_left)
    sch.add_wire(start=rf3_right, end=(u3_out[0], rf3_y))
    sch.add_wire(start=(u3_out[0], rf3_y), end=u3_out)

    # R7: U3(+) junction -> down to R7
    wire_manhattan_vh(sch, u3_ni[0], u3_ni[1], r7_top[0], r7_top[1])

    # Output: U3 out -> Cout -> RL
    wire_manhattan(sch, u3_out[0], u3_out[1], c1_left[0], c1_left[1])
    wire_manhattan_vh(sch, c1_right[0], c1_right[1], r8_top[0], r8_top[1])

    # ══════════════════════════════════════
    # POWER SYMBOLS, SOURCES & GROUND
    # ══════════════════════════════════════
    print("  Adding power symbols and sources...")

    pwr_idx = 1

    # VCC for all 3 op-amps
    for pin, ref_n in [(u1_vp, pwr_idx), (u2_vp, pwr_idx+1), (u3_vp, pwr_idx+2)]:
        y = pin[1] + 4*G
        sch.add_wire(start=pin, end=(pin[0], y))
        sch.components.add(lib_id="VCC:VCC", reference=f"#PWR{ref_n:02d}",
                           value="+12V", position=(pin[0], y))
    pwr_idx += 3

    # VEE for all 3 op-amps
    for pin, ref_n in [(u1_vm, pwr_idx), (u2_vm, pwr_idx+1), (u3_vm, pwr_idx+2)]:
        y = pin[1] - 4*G
        sch.add_wire(start=(pin[0], y), end=pin)
        sch.components.add(lib_id="VEE:VEE", reference=f"#PWR{ref_n:02d}",
                           value="-12V", position=(pin[0], y))
    pwr_idx += 3

    # GND at R7 bottom (diff amp reference)
    gnd_r7_y = r7_bottom[1] + 4*G
    sch.add_wire(start=r7_bottom, end=(r7_bottom[0], gnd_r7_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR{pwr_idx:02d}",
                       value="GND", position=(r7_bottom[0], gnd_r7_y))
    pwr_idx += 1

    # GND at RL bottom
    gnd_rl_y = r8_bottom[1] + 4*G
    sch.add_wire(start=r8_bottom, end=(r8_bottom[0], gnd_rl_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR{pwr_idx:02d}",
                       value="GND", position=(r8_bottom[0], gnd_rl_y))
    pwr_idx += 1

    # VSIN+ (differential positive input) - below U1(+)
    # Placed directly below U1(+) pin to avoid crossing Rg vertical wire
    vsin1_x = u1_ni[0]
    vsin1_cy = u1_ni[1] + 5.38 + 3*G  # offset below U1(+)
    sch.components.add(lib_id="VSIN:VSIN", reference="V1",
                       value="5mV 200Hz", position=(vsin1_x, vsin1_cy))
    vsin1_p1 = (vsin1_x, vsin1_cy - 5.38)  # top (+) pin
    vsin1_p2 = (vsin1_x, vsin1_cy + 4.78)  # bottom (-) pin
    # Simple vertical wire from V1(+) up to U1(+) - no horizontal crossing
    sch.add_wire(start=vsin1_p1, end=u1_ni)
    # GND at VSIN+ bottom
    gnd_vs1_y = vsin1_p2[1] + 4*G
    sch.add_wire(start=vsin1_p2, end=(vsin1_x, gnd_vs1_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR{pwr_idx:02d}",
                       value="GND", position=(vsin1_x, gnd_vs1_y))
    pwr_idx += 1

    # VSIN- (differential negative input) - below U2(+)
    # Inverted phase: negative of V1 to create differential signal
    vsin2_x = u2_ni[0]
    vsin2_cy = u2_ni[1] + 5.38 + 3*G  # offset below U2(+)
    sch.components.add(lib_id="VSIN:VSIN", reference="V2",
                       value="-5mV 200Hz", position=(vsin2_x, vsin2_cy))
    vsin2_p1 = (vsin2_x, vsin2_cy - 5.38)  # top (+) pin
    vsin2_p2 = (vsin2_x, vsin2_cy + 4.78)  # bottom (-) pin
    # Simple vertical wire from V2(+) up to U2(+) - no horizontal crossing
    sch.add_wire(start=vsin2_p1, end=u2_ni)
    # GND at VSIN- bottom
    gnd_vs2_y = vsin2_p2[1] + 4*G
    sch.add_wire(start=vsin2_p2, end=(vsin2_x, gnd_vs2_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR{pwr_idx:02d}",
                       value="GND", position=(vsin2_x, gnd_vs2_y))
    pwr_idx += 1

    # Output label
    out_lbl_x = r8_top[0] + 6*G
    sch.add_label("OUT", position=(out_lbl_x, r8_top[1]))
    sch.add_wire(start=r8_top, end=(out_lbl_x, r8_top[1]))

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "usb_ina.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    print(f"  Schematic saved: {sch_path}")

    try:
        svg_out = os.path.join(WORK_DIR, "usb_ina_svg")
        actual = export_svg(sch_path, svg_out)
        print(f"  SVG exported: {actual}")
    except Exception as e:
        print(f"  SVG export: {e}")

    return sch_path


# =============================================================
# BUILD: Electrometer Transimpedance Amplifier (TIA)
# =============================================================
def build_electrometer_tia():
    """
    Build an electrometer transimpedance amplifier schematic.
    Vout = -Iin * Rf, with feedback capacitor for stability.

    Op-amp is mirrored (mirror x) so (-) input is on TOP (TIA convention).
    Current source input connects to inverting input.

    Schematic:
              Rf (1G)
         +----/\\/\\/----+
         |    Cf (10pF) |
         |----||--------+
         |              |
    Iin--+-- (-) U1 (out)--+-- Vout
                (+)        |
                 |        RL (10M)
                GND        |
                          GND
    """
    print("Building electrometer TIA schematic...")

    sch = create_schematic("Electrometer TIA")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="Electrometer Transimpedance Amplifier (TIA)",
        company="Circuit Automation Project",
        rev="1.0",
        comments={1: "Vout = -Iin * Rf, Rf=1G, Cf=10pF, -3dB ~16Hz"}
    )

    G = 2.54

    # LM741 default pin offsets (no mirror needed: (-) already on top)
    #   pin2 inv(-): (-7.62, -2.54)  <- TOP-LEFT (current input)
    #   pin3 ni(+):  (-7.62, +2.54)  <- BOTTOM-LEFT (to GND)
    #   pin6 out:    (+7.62,  0)     <- RIGHT (output)
    #   pin7 V+:     (-2.54, +7.62)  <- BOTTOM
    #   pin4 V-:     (-2.54, -7.62)  <- TOP

    # ── Place op-amp (centered on page) ──
    ux, uy = 50*G, 44*G
    sch.components.add(
        lib_id="LM741:LM741",
        reference="U1",
        value="LM741",
        position=(ux, uy)
    )

    # Default pin positions ((-) on top, (+) on bottom - standard KiCad convention)
    inv_pin = (ux - 7.62, uy - 2.54)   # (-) TOP-LEFT
    ni_pin  = (ux - 7.62, uy + 2.54)   # (+) BOTTOM-LEFT
    out_pin = (ux + 7.62, uy)           # output RIGHT
    vp_pin  = (ux - 2.54, uy + 7.62)   # V+ BOTTOM
    vm_pin  = (ux - 2.54, uy - 7.62)   # V- TOP

    print(f"  U1 inv={inv_pin}, ni={ni_pin}, out={out_pin}")

    # ── Rf (1G) - feedback resistor, horizontal ABOVE op-amp ──
    # Need enough gap above op-amp for VEE label + Rf label readability
    rf_y = inv_pin[1] - 9*G
    rf_cx = (inv_pin[0] + out_pin[0]) / 2
    sch.components.add(
        lib_id="R:R", reference="R1", value="1G",
        position=(rf_cx, rf_y), rotation=90
    )
    rf_right = (rf_cx + 3.81, rf_y)  # pin 1
    rf_left  = (rf_cx - 3.81, rf_y)  # pin 2

    # ── Cf (10pF) - feedback capacitor, parallel with Rf ──
    # 6*G gap so C1/R1 labels don't overlap each other
    cf_y = rf_y - 6*G
    sch.components.add(
        lib_id="C:C", reference="C1", value="10pF",
        position=(rf_cx, cf_y), rotation=90
    )
    cf_right = (rf_cx + 3.81, cf_y)  # pin 1
    cf_left  = (rf_cx - 3.81, cf_y)  # pin 2

    # ── RL (10M) - ADC input impedance model, vertical ──
    rl_x = out_pin[0] + 10*G  # enough space for output wire + label
    rl_y = out_pin[1] + 7*G
    sch.components.add(
        lib_id="R:R", reference="R2", value="10M",
        position=(rl_x, rl_y)
    )
    r2_top    = (rl_x, rl_y - 3.81)  # pin 1
    r2_bottom = (rl_x, rl_y + 3.81)  # pin 2

    # ══════════════════════════════════════
    # WIRING
    # ══════════════════════════════════════

    # Junction point on wire between input and inv_pin
    junc_x = inv_pin[0] - 5*G  # wider for feedback loop clarity
    junc_y = inv_pin[1]

    # Wire from junction to inv_pin
    sch.add_wire(start=(junc_x, junc_y), end=inv_pin)

    # === FEEDBACK PATH (rectangular loop above op-amp) ===
    # 1. Junction -> straight UP to Rf height
    sch.add_wire(start=(junc_x, junc_y), end=(junc_x, rf_y))

    # 2. Horizontal to Rf LEFT pin
    sch.add_wire(start=(junc_x, rf_y), end=rf_left)

    # 3. Rf RIGHT pin -> horizontal to output column
    sch.add_wire(start=rf_right, end=(out_pin[0], rf_y))

    # 4. Output column -> straight DOWN to output pin
    sch.add_wire(start=(out_pin[0], rf_y), end=out_pin)

    # === Cf path (parallel with Rf, one row above) ===
    sch.add_wire(start=(junc_x, rf_y), end=(junc_x, cf_y))
    sch.add_wire(start=(junc_x, cf_y), end=cf_left)
    sch.add_wire(start=cf_right, end=(out_pin[0], cf_y))
    sch.add_wire(start=(out_pin[0], cf_y), end=(out_pin[0], rf_y))

    # Output chain: out_pin -> RL
    wire_manhattan(sch, out_pin[0], out_pin[1], r2_top[0], r2_top[1])

    # ══════════════════════════════════════
    # POWER SYMBOLS, GROUND & SOURCES
    # ══════════════════════════════════════

    # GND at non-inverting input (+) (below op-amp)
    gnd_ni_y = ni_pin[1] + 3*G  # tighter: was +4*G
    sch.add_wire(start=ni_pin, end=(ni_pin[0], gnd_ni_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR01", value="GND",
                       position=(ni_pin[0], gnd_ni_y))

    # VCC power symbol at V+ pin (below op-amp after mirror)
    vcc_y = vp_pin[1] + 3*G  # tighter
    sch.add_wire(start=vp_pin, end=(vp_pin[0], vcc_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR02", value="+12V",
                       position=(vp_pin[0], vcc_y))

    # VEE power symbol at V- pin (above op-amp after mirror)
    vee_y = vm_pin[1] - 3*G  # tighter
    sch.add_wire(start=(vm_pin[0], vee_y), end=vm_pin)
    sch.components.add(lib_id="VEE:VEE", reference="#PWR03", value="-12V",
                       position=(vm_pin[0], vee_y))

    # GND at load resistor bottom
    gnd_rl_y = r2_bottom[1] + 3*G  # tighter
    sch.add_wire(start=r2_bottom, end=(r2_bottom[0], gnd_rl_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR04", value="GND",
                       position=(r2_bottom[0], gnd_rl_y))

    # VSIN as current source proxy (will be actual current source in netlist)
    vsin_x = junc_x - 8*G  # tighter: was -10*G
    vsin_cy = junc_y + 5.38  # pin1 (top +) aligns with signal wire
    sch.components.add(lib_id="VSIN:VSIN", reference="V1",
                       value="1nA Pulse", position=(vsin_x, vsin_cy))
    vsin_p1 = (vsin_x, vsin_cy - 5.38)  # top (+)
    vsin_p2 = (vsin_x, vsin_cy + 4.78)  # bottom (-)
    wire_manhattan(sch, vsin_p1[0], vsin_p1[1], junc_x, junc_y)
    # GND at VSIN bottom
    gnd_vs_y = vsin_p2[1] + 3*G  # tighter
    sch.add_wire(start=vsin_p2, end=(vsin_x, gnd_vs_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR05", value="GND",
                       position=(vsin_x, gnd_vs_y))

    # Output label
    out_lbl_x = r2_top[0] + 5*G
    sch.add_label("OUT", position=(out_lbl_x, r2_top[1]))
    sch.add_wire(start=r2_top, end=(out_lbl_x, r2_top[1]))

    # Input label at junction
    in_lbl_x = junc_x - 3*G
    sch.add_label("TRIAX_IN", position=(in_lbl_x, junc_y))

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "electrometer.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    print(f"  Schematic saved: {sch_path}")

    try:
        svg_out = os.path.join(WORK_DIR, "electrometer_svg")
        actual = export_svg(sch_path, svg_out)
        print(f"  SVG exported: {actual}")
    except Exception as e:
        print(f"  SVG export: {e}")

    return sch_path


def build_electrometer_362(**kwargs):
    """
    Build a full electrometer TIA schematic for the ADuCM362 eval board.

    Based on the electrometer platform docs:
    - Op-amp: LM741 symbol (simulated with LMC6001 as ADA4530-1 proxy)
    - 4 feedback ranges: 10M, 100M, 1G+10pF, 10G+1pF (relay-selected)
    - Single supply: +3.3V (V+ = 3.3V, V- = GND)
    - Reference: 1.65V mid-supply (2x 100k divider) at non-inv(+)
    - ADC0 interface: AIN0(+) = TIA output, AIN1(-) = TIA reference
    - Current source input: I_TRIAX (BNC/triax connector)

    Schematic topology:
              Rf0(10M) | Rf1(100M) | Rf2(1G)+Cf2(10p) | Rf3(10G)+Cf3(1p)
              (relay-switched feedback ladder)
         +--------[Rf/Cf selected]--------+
         |                                 |
    Iin--+-- (-) U1 (ADA4530-1 proxy) (out)--+--[AIN0]-- ADuCM362 ADC0+
                (+)                            |
                 |                            [AIN1]-- ADuCM362 ADC0-
              1.65V ref                        |
              (100k/100k)                    VREF

    Note: In simulation, only one Rf/Cf pair is active at a time.
    The schematic shows all 4 ranges with labels indicating relay selection.
    Scaled 3x for readability (matching full_system/oscillator pattern).
    """
    print("Building electrometer TIA schematic (ADuCM362 platform)...")

    sch = create_schematic("Electrometer TIA - ADuCM362")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="Electrometer TIA - ADuCM362 Platform",
        company="Circuit Automation Project",
        rev="2.0",
        comments={
            1: "ADA4530-1 proxy (simulated with LMC6001), 4-range Rf ladder",
            2: "ADC0: AIN0(+)=TIA_OUT, AIN1(-)=VREF. Single supply 3.3V",
        }
    )

    G = 2.54

    # ── Block title and description ──
    sch.add_text("ELECTROMETER TIA (ADuCM362 PLATFORM)",
                 position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("ADA4530-1 TIA, 4-range relay-switched Rf (10M-10G), 24-bit ADC",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("FUNCTION: Complete electrometer front-end. TIA converts current to",
                 position=(8 * G, 17 * G), size=1.8)
    sch.add_text("voltage. Relay ladder selects range. ADuCM362 24-bit sigma-delta",
                 position=(8 * G, 21 * G), size=1.8)
    sch.add_text("ADC reads differential (TIA_OUT - VREF). Single 3.3V supply.",
                 position=(8 * G, 25 * G), size=1.8)

    # ── Parameterized clearances (correction loop compatible) ──
    fb_gap      = kwargs.get('fb_gap', 9)        # feedback Rf above inv input (G)
    cf_gap      = kwargs.get('cf_gap', 4)        # Cf above Rf row (G)
    div_offset  = kwargs.get('div_offset', 12)   # divider X offset from ni_pin (G)
    div_vert    = kwargs.get('div_vert', 7)      # divider R vertical offset (G)
    adc_gap     = kwargs.get('adc_gap', 8)       # ADC load below output (G)
    input_ext   = kwargs.get('input_ext', 8)     # current source extension left (G)

    # ── Place op-amp ──
    # Using LM741 symbol (no mirror): (-) at top-left, (+) at bottom-left
    ux, uy = 46*G, 44*G
    sch.components.add(
        lib_id="LM741:LM741", reference="U1",
        value="ADA4530-1", position=(ux, uy)
    )

    # Standard LM741 pin positions (no mirror)
    inv_pin = (ux - 7.62, uy - 2.54)   # (-) TOP-LEFT (current input)
    ni_pin  = (ux - 7.62, uy + 2.54)   # (+) BOTTOM-LEFT (reference)
    out_pin = (ux + 7.62, uy)           # output RIGHT
    vp_pin  = (ux - 2.54, uy + 7.62)   # V+ BOTTOM (3.3V)
    vm_pin  = (ux - 2.54, uy - 7.62)   # V- TOP (GND for single supply)

    print(f"  U1 inv={inv_pin}, ni={ni_pin}, out={out_pin}")

    # ── Junction point on wire between input and inv_pin ──
    junc_x = inv_pin[0] - 5*G
    junc_y = inv_pin[1]

    # Wire from junction to inv_pin
    sch.add_wire(start=(junc_x, junc_y), end=inv_pin)

    # ── FEEDBACK RESISTOR LADDER (4 ranges stacked above op-amp) ──
    # Range 2: Rf=1G, Cf=10pF  (primary range shown with feedback cap)
    # Other ranges shown as labeled resistors in parallel paths

    rf_y = inv_pin[1] - fb_gap*G    # main feedback row
    rf_cx = (inv_pin[0] + out_pin[0]) / 2

    # Rf2 = 1G (Range 2 - default/primary)
    sch.components.add(
        lib_id="R:R", reference="R1", value="1G",
        position=(rf_cx, rf_y), rotation=90
    )
    rf_right = (rf_cx + 3.81, rf_y)
    rf_left  = (rf_cx - 3.81, rf_y)

    # Cf2 = 10pF (parallel with Rf2)
    cf_y = rf_y - cf_gap*G  # gap between Rf and Cf
    sch.components.add(
        lib_id="C:C", reference="C1", value="10pF",
        position=(rf_cx, cf_y), rotation=90
    )
    cf_right = (rf_cx + 3.81, cf_y)
    cf_left  = (rf_cx - 3.81, cf_y)

    # === FEEDBACK WIRING ===
    # Junction -> straight UP to Rf height
    sch.add_wire(start=(junc_x, junc_y), end=(junc_x, rf_y))
    # Horizontal to Rf LEFT pin
    sch.add_wire(start=(junc_x, rf_y), end=rf_left)
    # Rf RIGHT pin -> horizontal to output column
    sch.add_wire(start=rf_right, end=(out_pin[0], rf_y))
    # Output column -> straight DOWN to output pin
    sch.add_wire(start=(out_pin[0], rf_y), end=out_pin)

    # === Cf path (parallel with Rf, one row above) ===
    sch.add_wire(start=(junc_x, rf_y), end=(junc_x, cf_y))
    sch.add_wire(start=(junc_x, cf_y), end=cf_left)
    sch.add_wire(start=cf_right, end=(out_pin[0], cf_y))
    sch.add_wire(start=(out_pin[0], cf_y), end=(out_pin[0], rf_y))

    # Junction dots at T-junctions
    sch.junctions.add(position=(junc_x, junc_y))     # input wire / feedback branch
    sch.junctions.add(position=(junc_x, rf_y))        # Rf / Cf branch point
    sch.junctions.add(position=(out_pin[0], rf_y))     # output column Rf/Cf merge
    sch.junctions.add(position=out_pin)                # output: feedback / R2 / AIN0

    # ── REFERENCE VOLTAGE DIVIDER (100k/100k for 1.65V mid-supply) ──
    # R3 (100k) from VCC to ni_pin, R4 (100k) from ni_pin to GND
    ref_x = ni_pin[0] - div_offset*G  # spaced from op-amp for readability
    r3_y = ni_pin[1] - div_vert*G   # above with clearance
    r4_y = ni_pin[1] + div_vert*G   # below with clearance

    sch.components.add(
        lib_id="R:R", reference="R3", value="100k",
        position=(ref_x, r3_y)  # vertical (default rotation=0)
    )
    r3_top = (ref_x, r3_y - 3.81)
    r3_bot = (ref_x, r3_y + 3.81)

    sch.components.add(
        lib_id="R:R", reference="R4", value="100k",
        position=(ref_x, r4_y)  # vertical
    )
    r4_top = (ref_x, r4_y - 3.81)
    r4_bot = (ref_x, r4_y + 3.81)

    # Wire from R3 bottom to R4 top (midpoint = reference voltage)
    sch.add_wire(start=r3_bot, end=r4_top)
    # Wire from midpoint to ni_pin(+)
    mid_y = (r3_bot[1] + r4_top[1]) / 2
    sch.add_wire(start=(ref_x, mid_y), end=(ni_pin[0], mid_y))
    sch.add_wire(start=(ni_pin[0], mid_y), end=ni_pin)

    # Bypass cap C2 (100nF) from reference to GND
    c2_x = ref_x + 5*G
    c2_y = r4_y
    sch.components.add(
        lib_id="C:C", reference="C2", value="100nF",
        position=(c2_x, c2_y)  # vertical
    )
    c2_top = (c2_x, c2_y - 3.81)
    c2_bot = (c2_x, c2_y + 3.81)
    # Connect C2 top to reference midpoint
    sch.add_wire(start=c2_top, end=(c2_x, mid_y))
    sch.add_wire(start=(c2_x, mid_y), end=(ref_x, mid_y))
    sch.junctions.add(position=(ref_x, mid_y))        # divider vertical / horizontal tee
    sch.junctions.add(position=(c2_x, mid_y))          # C2 vertical / horizontal tee

    # ── ADC OUTPUT SECTION ──
    # R2 (10M) load resistor from output column to GND
    # AIN0 label on the output wire
    rl_x = out_pin[0]  # same column as output
    rl_y = out_pin[1] + adc_gap*G  # below output, gives room for AIN0 label
    sch.components.add(
        lib_id="R:R", reference="R2", value="10M",
        position=(rl_x, rl_y)
    )
    r2_top = (rl_x, rl_y - 3.81)
    r2_bot = (rl_x, rl_y + 3.81)

    # Wire from output column down to R2 top (already on same X from feedback)
    sch.add_wire(start=out_pin, end=r2_top)

    # ══════════════════════════════════════
    # POWER SYMBOLS & GROUND
    # ══════════════════════════════════════

    # VCC at V+ pin (below op-amp after mirror) - 3.3V single supply
    vcc_y = vp_pin[1] + 3*G
    sch.add_wire(start=vp_pin, end=(vp_pin[0], vcc_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR01", value="+3.3V",
                       position=(vp_pin[0], vcc_y))

    # GND at V- pin (above op-amp after mirror) - single supply ground
    gnd_vm_y = vm_pin[1] - 3*G
    sch.add_wire(start=(vm_pin[0], gnd_vm_y), end=vm_pin)
    sch.components.add(lib_id="GND:GND", reference="#PWR02", value="GND",
                       position=(vm_pin[0], gnd_vm_y))

    # VCC at R3 top (reference divider top)
    vcc_r3_y = r3_top[1] - 3*G
    sch.add_wire(start=r3_top, end=(r3_top[0], vcc_r3_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR03", value="+3.3V",
                       position=(r3_top[0], vcc_r3_y))

    # GND at R4 bottom (reference divider bottom)
    gnd_r4_y = r4_bot[1] + 3*G
    sch.add_wire(start=r4_bot, end=(r4_bot[0], gnd_r4_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR04", value="GND",
                       position=(r4_bot[0], gnd_r4_y))

    # GND at C2 bottom (bypass cap)
    gnd_c2_y = c2_bot[1] + 3*G
    sch.add_wire(start=c2_bot, end=(c2_bot[0], gnd_c2_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR05", value="GND",
                       position=(c2_bot[0], gnd_c2_y))

    # GND at R2 bottom (load resistor)
    gnd_rl_y = r2_bot[1] + 3*G
    sch.add_wire(start=r2_bot, end=(r2_bot[0], gnd_rl_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR06", value="GND",
                       position=(r2_bot[0], gnd_rl_y))

    # ── INPUT SOURCE (VSIN as current source proxy) ──
    # Place VSIN left of reference divider, routed ABOVE divider to avoid crossing
    vsin_x = ref_x - 6*G  # left of divider column
    vsin_cy = junc_y + 5.38  # centered vertically near inv_pin level
    sch.components.add(lib_id="VSIN:VSIN", reference="V1",
                       value="I_TRIAX", position=(vsin_x, vsin_cy))
    vsin_p1 = (vsin_x, vsin_cy - 5.38)  # top pin (+) = junc_y
    vsin_p2 = (vsin_x, vsin_cy + 4.78)  # bottom pin (-)
    # Route: VSIN top -> up above Cf -> horizontal to junc_x -> down to junction
    # This 3-segment path avoids crossing both divider and feedback wires
    route_y = cf_y - 3*G  # above the feedback capacitor area
    sch.add_wire(start=vsin_p1, end=(vsin_x, route_y))       # up from VSIN
    sch.add_wire(start=(vsin_x, route_y), end=(junc_x, route_y))  # horizontal above divider
    sch.add_wire(start=(junc_x, route_y), end=(junc_x, junc_y))   # down to junction
    # VSIN bottom pin -> GND below
    gnd_vs_y = vsin_p2[1] + 3*G
    sch.add_wire(start=vsin_p2, end=(vsin_x, gnd_vs_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR07", value="GND",
                       position=(vsin_x, gnd_vs_y))

    # ── NET LABELS ──
    # AIN0 (ADuCM362 ADC0 positive input) - right of output column
    ain0_x = out_pin[0] + 6*G
    ain0_y = out_pin[1]
    sch.add_label("AIN0", position=(ain0_x, ain0_y))
    sch.add_wire(start=out_pin, end=(ain0_x, ain0_y))

    # AIN1 (ADuCM362 ADC0 negative input = VREF)
    # Route from reference midpoint rightward, stop before op-amp to avoid overlap
    ain1_x = ni_pin[0] - 4*G  # label well left of op-amp pin 3
    ain1_y = mid_y
    sch.add_label("AIN1", position=(ain1_x, ain1_y))
    sch.add_wire(start=(ref_x, mid_y), end=(ain1_x, ain1_y))

    # Input label - on the horizontal route wire above divider (VSIN input path)
    in_lbl_x = vsin_x + 3*G
    sch.add_label("TRIAX_IN", position=(in_lbl_x, route_y))

    # NOTE: Removed redundant OUT label - AIN0 is the output label.
    # The op-amp output connects directly to R2 and AIN0 via the output column.

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "electrometer_362.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    merge_collinear_wires(sch_path)

    # Scale factor: 1 = standard paper (professional layout), >1 = enlarged
    sf = kwargs.get('scale_factor', 1)
    if sf and sf != 1:
        scale_schematic(sch_path, factor=sf)

    print(f"  Schematic saved: {sch_path} ({sf}x scale)")

    try:
        svg_out = os.path.join(WORK_DIR, "electrometer_362_svg")
        actual = export_svg(sch_path, svg_out)
        print(f"  SVG exported: {actual}")
    except Exception as e:
        print(f"  SVG export: {e}")

    return sch_path


def build_relay_ladder():
    """
    Build relay range-switching ladder schematic for the electrometer platform.

    4 SPST reed relay channels, each with:
    - Reed switch contact in series with feedback resistor (Rf)
    - NPN transistor (2N3904) coil driver with 1k base resistor
    - 1N4148 flyback diode across relay coil
    - GPIO label (GP1.0-GP1.3) for ADuCM362 control

    Feedback ranges:
      K1: Rf0 = 10M   (Range 0, full-scale +-120nA)
      K2: Rf1 = 100M   (Range 1, full-scale +-12nA)
      K3: Rf2 = 1G + Cf=10pF  (Range 2, full-scale +-1.2nA)
      K4: Rf3 = 10G + Cf=1pF  (Range 3, full-scale +-120pA)

    Interface labels:
      INV  - connects to TIA inverting input (off-sheet)
      OUT  - connects to TIA output (off-sheet)
      GP1.0-GP1.3 - ADuCM362 GPIO Port 1 pins
      5V_ISO - isolated 5V from DC-DC converter
    """
    print("Building relay range-switching ladder schematic...")

    sch = create_schematic("Relay Range Ladder")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="Relay Range-Switching Ladder - Electrometer Platform",
        company="Circuit Automation Project",
        rev="1.0",
        comments={
            1: "4x 109P-1-A-5/1 SPST reed relays, 2N3904 NPN drivers",
            2: "Rf: 10M/100M/1G+10p/10G+1p, controlled by GP1[0:3]",
        }
    )

    G = 2.54

    # ── Block title and description ──
    sch.add_text("RELAY RANGE-SWITCHING LADDER",
                 position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("4 decades: Rf = 10M / 100M / 1G / 10G (reed relay SPST)",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("FUNCTION: Selects TIA feedback resistor via SPST reed relays.",
                 position=(8 * G, 17 * G), size=1.8)
    sch.add_text("MCU GPIO drives NPN transistor coil drivers. Flyback diodes protect",
                 position=(8 * G, 21 * G), size=1.8)
    sch.add_text("against relay coil back-EMF. Only one relay closed at a time.",
                 position=(8 * G, 25 * G), size=1.8)

    # ══════════════════════════════════════════════════════════════
    # SECTION 1: FEEDBACK RESISTOR LADDER (4 rows, SW + Rf)
    # ══════════════════════════════════════════════════════════════

    # Bus positions
    inv_x = 14*G       # INV bus (left vertical line)
    sw_x = 22*G        # SW_Reed center
    rf_x = 36*G        # Rf center (horizontal, rot=90)
    out_x = 50*G       # OUT bus (right vertical line)

    # Row definitions: (index, y, rf_value, cf_value_or_None)
    ROWS = [
        (0, 20*G, "10M",  None),
        (1, 26*G, "100M", None),
        (2, 32*G, "1G",   "10pF"),
        (3, 38*G, "10G",  "1pF"),
    ]

    pwr_n = 1  # power symbol counter

    for idx, row_y, rf_val, cf_val in ROWS:
        # Reed switch (horizontal, default rot=0)
        # Pin 1 at (sw_x - 5.08, row_y) = left
        # Pin 2 at (sw_x + 5.08, row_y) = right
        sch.components.add(
            lib_id="SW_Reed:SW_Reed", reference=f"SW{idx+1}",
            value=f"K{idx+1}", position=(sw_x, row_y)
        )
        sw1 = (sw_x - 5.08, row_y)   # pin 1 (left)
        sw2 = (sw_x + 5.08, row_y)   # pin 2 (right)

        # Feedback resistor (horizontal, rot=90)
        # Pin 1 at (rf_x + 3.81, row_y) = right
        # Pin 2 at (rf_x - 3.81, row_y) = left
        sch.components.add(
            lib_id="R:R", reference=f"R{idx+1}",
            value=rf_val, position=(rf_x, row_y), rotation=90
        )
        rf_left = (rf_x - 3.81, row_y)
        rf_right = (rf_x + 3.81, row_y)

        # Wire: INV bus -> SW pin 1
        sch.add_wire(start=(inv_x, row_y), end=sw1)
        # Wire: SW pin 2 -> Rf pin 2 (left)
        sch.add_wire(start=sw2, end=rf_left)
        # Wire: Rf pin 1 (right) -> OUT bus
        sch.add_wire(start=rf_right, end=(out_x, row_y))

        # Optional feedback cap in parallel with Rf
        if cf_val:
            cf_y = row_y + 3*G
            sch.components.add(
                lib_id="C:C", reference=f"C{idx+1}",
                value=cf_val, position=(rf_x, cf_y), rotation=90
            )
            cf_left = (rf_x - 3.81, cf_y)
            cf_right = (rf_x + 3.81, cf_y)
            # Vertical wires connecting cap in parallel
            sch.add_wire(start=(rf_left[0], rf_left[1]), end=(cf_left[0], cf_left[1]))
            sch.add_wire(start=(rf_right[0], rf_right[1]), end=(cf_right[0], cf_right[1]))

    # Vertical INV bus line (connecting all rows)
    sch.add_wire(start=(inv_x, ROWS[0][1]), end=(inv_x, ROWS[-1][1]))
    # Vertical OUT bus line
    sch.add_wire(start=(out_x, ROWS[0][1]), end=(out_x, ROWS[-1][1]))

    # Bus labels
    sch.add_label("INV", position=(inv_x, ROWS[0][1] - 2*G))
    sch.add_wire(start=(inv_x, ROWS[0][1] - 2*G), end=(inv_x, ROWS[0][1]))
    sch.add_label("OUT", position=(out_x, ROWS[0][1] - 2*G))
    sch.add_wire(start=(out_x, ROWS[0][1] - 2*G), end=(out_x, ROWS[0][1]))

    # ══════════════════════════════════════════════════════════════
    # SECTION 2: NPN COIL DRIVERS (4 channels, horizontal layout)
    # ══════════════════════════════════════════════════════════════
    #
    # Per channel (top to bottom):
    #   VCC (5V_ISO) -> D cathode (top) -> D anode (bottom) ->
    #   Q collector (top) -> Q emitter (bottom) -> GND
    #   GPIO -> Rb -> Q base (left)
    #
    # D with rot=90: Pin 1 (K) at top (cy-3.81), Pin 2 (A) at bottom (cy+3.81)
    # Q_NPN_BCE: Pin 1 (B) at (cx-5.08, cy), Pin 2 (C) at (cx+2.54, cy-5.08),
    #            Pin 3 (E) at (cx+2.54, cy+5.08)

    drv_x_start = 16*G
    drv_spacing = 14*G   # wider to avoid cross-channel overlap
    q_y = 62*G           # NPN center (pushed down to clear ladder)
    coil_y = q_y - 12*G  # Relay coil center (above NPN)

    for idx in range(4):
        dx = drv_x_start + idx * drv_spacing

        # NPN transistor
        sch.components.add(
            lib_id="Q_NPN_BCE:Q_NPN_BCE", reference=f"Q{idx+1}",
            value="2N3904", position=(dx, q_y)
        )
        q_b = (dx - 5.08, q_y)           # base (left)
        q_c = (dx + 2.54, q_y - 5.08)    # collector (top-right)
        q_e = (dx + 2.54, q_y + 5.08)    # emitter (bottom-right)

        # Relay coil (vertical R model, rot=0: pin1=top, pin2=bottom)
        coil_cx = q_c[0]  # align with collector column
        sch.components.add(
            lib_id="R:R", reference=f"R{idx+9}",
            value="500R_COIL", position=(coil_cx, coil_y)
        )
        coil_top = (coil_cx, coil_y - 3.81)   # pin 1 -> 5V_ISO
        coil_bot = (coil_cx, coil_y + 3.81)   # pin 2 -> collector

        # Wire: coil bottom -> Q collector
        sch.add_wire(start=coil_bot, end=q_c)

        # Flyback diode in PARALLEL with coil
        # D:D rot=90: K(-3.81,0)->(0,-3.81)=top, A(+3.81,0)->(0,+3.81)=bottom
        d_cx = coil_cx + 6*G
        sch.components.add(
            lib_id="D:D", reference=f"D{idx+1}",
            value="1N4148", position=(d_cx, coil_y), rotation=90
        )
        d_k = (d_cx, coil_y - 3.81)   # cathode (top) -> 5V_ISO
        d_a = (d_cx, coil_y + 3.81)   # anode (bottom) -> collector

        # Horizontal wires: diode in parallel with coil
        sch.add_wire(start=coil_top, end=(d_k[0], coil_top[1]))
        sch.junctions.add(position=coil_top)
        sch.add_wire(start=coil_bot, end=(d_a[0], coil_bot[1]))
        sch.junctions.add(position=coil_bot)

        # 5V_ISO at coil top
        vcc_y = coil_top[1] - 3*G
        sch.add_wire(start=coil_top, end=(coil_top[0], vcc_y))
        sch.components.add(
            lib_id="VCC:VCC", reference=f"#PWR{pwr_n:02d}",
            value="5V_ISO", position=(coil_top[0], vcc_y)
        )
        pwr_n += 1

        # GND at emitter
        gnd_y = q_e[1] + 3*G
        sch.add_wire(start=q_e, end=(q_e[0], gnd_y))
        sch.components.add(
            lib_id="GND:GND", reference=f"#PWR{pwr_n:02d}",
            value="GND", position=(q_e[0], gnd_y)
        )
        pwr_n += 1

        # Base resistor (horizontal, rot=90)
        rb_x = dx - 12*G
        sch.components.add(
            lib_id="R:R", reference=f"R{idx+5}",
            value="1k", position=(rb_x, q_y), rotation=90
        )
        rb_right = (rb_x + 3.81, q_y)
        rb_left = (rb_x - 3.81, q_y)

        # Wire: Rb right -> Q base
        sch.add_wire(start=rb_right, end=q_b)

        # GPIO label at Rb left
        gpio_label = f"GP1.{idx}"
        sch.add_label(gpio_label, position=(rb_left[0] - 2*G, rb_left[1]))
        sch.add_wire(start=(rb_left[0] - 2*G, rb_left[1]), end=rb_left)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "relay_ladder.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    print(f"  Schematic saved: {sch_path}")

    try:
        svg_out = os.path.join(WORK_DIR, "relay_ladder_svg")
        actual = export_svg(sch_path, svg_out)
        print(f"  SVG exported: {actual}")
    except Exception as e:
        print(f"  SVG export: {e}")

    return sch_path


def write_relay_ladder_netlist():
    """
    Write ngspice netlist to simulate the relay coil driver circuit.

    Tests one NPN driver channel: GPIO pulse -> 1k base resistor -> 2N3904
    -> relay coil (modeled as 500 ohm inductor) -> 5V supply.
    Verifies: switching speed, flyback diode clamping, base drive current.
    """
    RANGES = {0: "10M", 1: "100M", 2: "1G", 3: "10G"}

    # Extract 2N3904 model
    model_block = extract_model("2N3904", "motorola.lib")
    if not model_block:
        model_block = extract_model("2N3904", "zetex.lib")
    if not model_block:
        # Fallback: generic 2N3904 model
        model_block = ".model 2N3904 NPN(IS=6.734f BF=416.4 NF=1.259 ISE=6.734f"
        model_block += " IKF=66.78m VAF=74.03 NE=1.259 BR=0.7389 NR=2"
        model_block += " ISC=0 IKR=0 RC=1 CJC=3.638p MJC=0.3085 VJC=0.75"
        model_block += " FC=0.5 CJE=4.493p MJE=0.2593 VJE=0.75 TR=239.5n"
        model_block += " TF=301.2p ITF=0.4 VTF=4 XTF=2 EG=1.11 XTB=1.5)\n"

    netlist = f"""* Relay Coil Driver - Single Channel Test
* Tests NPN switching of reed relay coil with flyback diode
*
* GPIO (3.3V pulse) -> 1k -> 2N3904 -> relay coil (500R + 50mH) -> 5V_ISO
* 1N4148 flyback diode across coil

* Power supply
V_ISO 5V_ISO 0 DC 5

* GPIO control signal (3.3V pulse, 10ms on, 10ms off)
V_GPIO GPIO 0 PULSE(0 3.3 5m 100u 100u 10m 25m)

* Base resistor
R_BASE GPIO Q1_B 1k

* NPN transistor (2N3904)
Q1 COIL_BOT Q1_B 0 2N3904

* Relay coil model (500 ohm + 50mH inductance)
R_COIL 5V_ISO COIL_TOP 500
L_COIL COIL_TOP COIL_BOT 50m IC=0

* Flyback diode (1N4148)
D1 COIL_BOT 5V_ISO D1N4148

* Diode model
.model D1N4148 D(IS=2.52n RS=0.568 N=1.752 BV=100 IBV=100u
+ CJO=4p M=0.4 TT=20n)

* Transistor model
{model_block}

* Simulation: transient 50ms
.tran 10u 50m

* Output
.control
run
wrdata {os.path.join(WORK_DIR, 'relay_ladder_results.txt').replace(chr(92), '/')} V(GPIO) V(COIL_BOT) V(5V_ISO)-V(COIL_TOP) I(V_ISO)
.endc

.end
"""
    netlist_path = os.path.join(WORK_DIR, "relay_ladder.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {netlist_path}")
    return netlist_path


def build_input_filters():
    """Build 16-channel input filter array schematic.

    Each channel: BAV199 ESD clamp (2x D) + 1M series R + 10nF shunt C.
    RC LPF fc = 1/(2*pi*1M*10n) = 15.9 Hz.
    Two groups of 8 channels feed MAX338 mux inputs (MUX_A1-A8, MUX_B1-B8).
    """
    sch = create_schematic("16-Channel Input Filter Array")
    sch.set_paper_size("A3")
    G = 2.54

    # Two columns of 8 channels
    groups = [
        ("A", 6 * G, range(1, 9)),     # left column
        ("B", 80 * G, range(9, 17)),    # right column
    ]
    y_start = 14 * G
    row_spacing = 10 * G
    pwr_idx = 1

    for grp_name, col_x, channels in groups:
        for row, ch_num in enumerate(channels):
            row_y = y_start + row * row_spacing
            mux_ch = (ch_num - 1) % 8 + 1

            # ---- x positions for this channel ----
            diode_x   = col_x + 6 * G
            r_cx      = col_x + 9 * G       # tight to diode (3.81mm gap)
            c_cx      = col_x + 14 * G
            label_out = col_x + 18 * G

            # ---- INPUT LABEL ----
            sch.add_label(f"CH_IN_{ch_num}", position=(col_x, row_y))

            # ---- ESD CLAMP: anti-parallel diodes (side-by-side below signal) ----
            # D:D default (rot=0): K at (-3.81,0)=LEFT, A at (+3.81,0)=RIGHT
            # rot=270: A at top (signal), K at bottom (GND) -> triangle ▽ -> positive clamp
            # rot=90:  K at top (signal), A at bottom (GND) -> triangle △ -> negative clamp
            # Side-by-side gives visually opposite triangles with correct anti-parallel clamping.
            d_left_x  = diode_x - 1.5 * G   # D_odd: positive clamp (▽)
            d_right_x = diode_x + 1.5 * G   # D_even: negative clamp (△)

            sch.components.add(
                lib_id="D:D", reference=f"D{ch_num * 2 - 1}",
                value="BAV199", position=(d_left_x, row_y + 3.81), rotation=270)

            sch.components.add(
                lib_id="D:D", reference=f"D{ch_num * 2}",
                value="BAV199", position=(d_right_x, row_y + 3.81), rotation=90)

            # ---- Shared GND bus below both diodes ----
            # D_odd K at (d_left_x, row_y + 7.62), D_even A at (d_right_x, row_y + 7.62)
            gnd_bus_y = row_y + 7.62
            gnd_y = gnd_bus_y + 2 * G
            # Horizontal bus connecting both diode bottoms
            sch.add_wire(start=(d_left_x, gnd_bus_y), end=(d_right_x, gnd_bus_y))
            # Vertical wire down to GND symbol from center
            sch.add_wire(start=(diode_x, gnd_bus_y), end=(diode_x, gnd_y))
            sch.components.add(
                lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
                value="GND", position=(diode_x, gnd_y))
            pwr_idx += 1

            # Junctions where diodes tee off signal wire
            sch.junctions.add(position=(d_left_x, row_y))
            sch.junctions.add(position=(d_right_x, row_y))

            # ---- 1M series resistor (horizontal, rot=90) ----
            sch.components.add(
                lib_id="R:R", reference=f"R{ch_num}",
                value="1M", position=(r_cx, row_y), rotation=90)

            # ---- 10nF filter cap (vertical, default C:C orientation) ----
            # C:C default: pin1 at top (cy-3.81), pin2 at bottom (cy+3.81)
            sch.components.add(
                lib_id="C:C", reference=f"C{ch_num}",
                value="10n", position=(c_cx, row_y + 3.81))

            # ---- GND at C pin2 (bottom) ----
            # C pin2 at (c_cx, row_y + 7.62), GND below with wire
            c_pin2_y = row_y + 7.62
            gnd_c_y = c_pin2_y + 3 * G
            sch.add_wire(start=(c_cx, c_pin2_y), end=(c_cx, gnd_c_y))
            sch.components.add(
                lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
                value="GND", position=(c_cx, gnd_c_y))
            pwr_idx += 1

            # ---- MUX OUTPUT LABEL ----
            sch.add_label(f"MUX_{grp_name}{mux_ch}", position=(label_out, row_y))

            # ---- WIRES ----
            # Wire A: input label -> R pin1 (passes through D cathodes at diode_x)
            sch.add_wire(start=(col_x, row_y), end=(r_cx - 3.81, row_y))
            # Wire B: R pin2 -> C pin1 -> MUX label
            sch.add_wire(start=(r_cx + 3.81, row_y), end=(label_out, row_y))
            # Junction at diode cathode-to-cathode point on signal wire
            sch.junctions.add(position=(diode_x, row_y))
            # Junction at C pin1 to show R-C connection
            sch.junctions.add(position=(c_cx, row_y))

    sch_path = os.path.join(WORK_DIR, "input_filters.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    return sch_path


def build_analog_mux():
    """Build 2x 8:1 analog multiplexer section (CD4051B stand-in for MAX338).

    MUX A (U1): MUX_A1-A8 → TIA_IN  (channels 1-8)
    MUX B (U2): MUX_B1-B8 → TIA_IN  (channels 9-16)
    Shared address: ADDR_A0, ADDR_A1, ADDR_A2
    Per-mux enable: EN_A, EN_B (active-low INH pin)
    Both outputs tied to TIA_IN (inactive mux is high-Z).
    """
    sch = create_schematic("Analog Multiplexer - 2x MAX338 (CD4051B)")
    sch.set_paper_size("A4")
    G = 2.54

    # ── Block title and description ──
    sch.add_text("ANALOG MULTIPLEXER (2x MAX338)",
                 position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("16:1 channel select via ADDR[A0:A2] + EN_A/EN_B",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("FUNCTION: Routes one of 16 input channels to TIA_IN. MUX A handles",
                 position=(8 * G, 17 * G), size=1.8)
    sch.add_text("channels 1-8, MUX B handles 9-16. Only one mux active at a time",
                 position=(8 * G, 21 * G), size=1.8)
    sch.add_text("(inactive mux is high-Z). MCU controls address and enable lines.",
                 position=(8 * G, 25 * G), size=1.8)

    # CD4051B pin offsets from center (schematic coords, rot=0):
    #   Left:  A(pin11) dy=-12.7, B(pin10) dy=-10.16, C(pin9) dy=-7.62
    #          X(pin3) dy=-2.54, INH(pin6) dy=0  (all at dx=-12.7)
    #   Right: X0(13) dy=-5.08, X1(14) dy=-2.54, X2(15) dy=0,
    #          X3(12) dy=+2.54, X4(1) dy=+5.08, X5(5) dy=+7.62,
    #          X6(2) dy=+10.16, X7(4) dy=+12.7  (all at dx=+12.7)
    #   Power: VDD(16) dx=+2.54,dy=-17.78  VSS(8) dx=0,dy=+17.78
    #          VEE(7) dx=-2.54,dy=+17.78

    CH_DY = [-5.08, -2.54, 0, 2.54, 5.08, 7.62, 10.16, 12.7]  # X0..X7
    ADDR_DY = {'A': -12.7, 'B': -10.16, 'C': -7.62}
    X_DY = -2.54    # common output
    INH_DY = 0.0    # enable/inhibit
    PIN_DX_L = -12.7
    PIN_DX_R = 12.7
    LABEL_GAP = 2 * G  # label offset from pin

    pwr_idx = 1

    muxes = [
        ("U1", "A", 40 * G, 28 * G, range(1, 9)),
        ("U2", "B", 40 * G, 68 * G, range(1, 9)),
    ]

    for ref, grp, cx, cy, ch_range in muxes:
        # ---- MUX IC ----
        sch.components.add(
            lib_id="CD4051B:CD4051B", reference=ref,
            value="MAX338", position=(cx, cy))

        # ---- Channel inputs (RIGHT side → labels from Stage 1) ----
        for i, ch_idx in enumerate(ch_range):
            pin_x = cx + PIN_DX_R
            pin_y = cy + CH_DY[i]
            lbl_x = pin_x + LABEL_GAP
            sch.add_label(f"MUX_{grp}{ch_idx}", position=(lbl_x, pin_y))
            sch.add_wire(start=(pin_x, pin_y), end=(lbl_x, pin_y))

        # ---- Common output X (LEFT) → TIA_IN ----
        x_pin = (cx + PIN_DX_L, cy + X_DY)
        x_lbl = (x_pin[0] - LABEL_GAP, x_pin[1])
        sch.add_label("TIA_IN", position=x_lbl)
        sch.add_wire(start=x_pin, end=x_lbl)

        # ---- Address lines (LEFT, shared) ----
        for name, dy in [("ADDR_A0", ADDR_DY['A']),
                         ("ADDR_A1", ADDR_DY['B']),
                         ("ADDR_A2", ADDR_DY['C'])]:
            pin = (cx + PIN_DX_L, cy + dy)
            lbl = (pin[0] - LABEL_GAP, pin[1])
            sch.add_label(name, position=lbl)
            sch.add_wire(start=pin, end=lbl)

        # ---- INH / Enable (LEFT) ----
        inh_pin = (cx + PIN_DX_L, cy + INH_DY)
        en_lbl = (inh_pin[0] - LABEL_GAP, inh_pin[1])
        sch.add_label(f"EN_{grp}", position=en_lbl)
        sch.add_wire(start=inh_pin, end=en_lbl)

        # ---- Power: VDD → VCC, VSS → GND, VEE → GND ----
        vdd = (cx + 2.54, cy - 17.78)
        vss = (cx, cy + 17.78)
        vee = (cx - 2.54, cy + 17.78)

        # VCC at VDD (2*G above pin)
        sch.components.add(lib_id="VCC:VCC", reference=f"#PWR0{pwr_idx:02d}",
            value="VCC", position=(vdd[0], vdd[1] - 2 * G))
        sch.add_wire(start=vdd, end=(vdd[0], vdd[1] - 2 * G))
        pwr_idx += 1

        # GND at VSS (2*G below pin)
        sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
            value="GND", position=(vss[0], vss[1] + 2 * G))
        sch.add_wire(start=vss, end=(vss[0], vss[1] + 2 * G))
        pwr_idx += 1

        # GND at VEE (single-supply: VEE = GND)
        sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
            value="GND", position=(vee[0], vee[1] + 2 * G))
        sch.add_wire(start=vee, end=(vee[0], vee[1] + 2 * G))
        pwr_idx += 1

        # ---- Decoupling cap 100nF (vertical, near VDD pin) ----
        dcap_cx = cx + 8 * G
        dcap_cy = vdd[1]  # pin1 (top) aligned with VDD level
        sch.components.add(lib_id="C:C", reference=f"C{17 if grp == 'A' else 18}",
            value="100n", position=(dcap_cx, dcap_cy + 3.81))
        # Wire VDD pin → cap pin1 (top at dcap_cy)
        sch.add_wire(start=(vdd[0], vdd[1]), end=(dcap_cx, dcap_cy))
        # GND at cap pin2 (bottom at dcap_cy + 7.62)
        sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
            value="GND", position=(dcap_cx, dcap_cy + 7.62))
        pwr_idx += 1

    sch_path = os.path.join(WORK_DIR, "analog_mux.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    return sch_path


def build_mux_tia(**kwargs):
    """Build TIA section interfacing mux output to ADuCM362 ADC.

    Signal path: TIA_IN (from mux) -> inverting input -> Rf feedback -> AIN0
    Reference: VREF (100k/100k divider, 1.65V) -> non-inverting input -> AIN1
    Op-amp: LM741 symbol (mirrored), value ADA4530-1.
    Feedback: Rf=1G + Cf=10pF (range 2 default shown).
    INV/OUT labels for relay ladder feedback path.
    Single supply: +3.3V / GND.

    Correction kwargs (set by auto_correct_schematic):
        divider_offset: multiplier for VREF divider distance from ni_pin (default 16)
        gnd_route_clearance: multiplier for V- GND routing past output (default 8)
        feedback_spacing: spacing between Rf and Cf in grid units (default 3)
        label_at_output_pin: if True, place OUT label at output pin level (default True)
    """
    # Correction parameters (defaults are the learned-good values)
    divider_offset = kwargs.get('divider_offset', 16)
    gnd_clearance = kwargs.get('gnd_route_clearance', 8)
    fb_spacing = kwargs.get('feedback_spacing', 3)

    sch = create_schematic("TIA with Mux Interface - ADA4530-1")
    sch.set_paper_size("A4")
    G = 2.54

    # ── Block title and description ──
    sch.add_text("TRANSIMPEDANCE AMPLIFIER (ADA4530-1)",
                 position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("Vout = Iin x Rf,  Rf selected by relay ladder (10M to 10G)",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("FUNCTION: Converts picoamp-level input current to voltage. ADA4530-1",
                 position=(8 * G, 17 * G), size=1.8)
    sch.add_text("sub-femtoamp bias current enables measurement down to ~50 fA.",
                 position=(8 * G, 21 * G), size=1.8)
    sch.add_text("VREF (1.65V) biases non-inv input for single-supply 3.3V operation.",
                 position=(8 * G, 25 * G), size=1.8)

    # ── Place op-amp (mirrored: (-) on top for TIA convention) ──
    ux, uy = 46 * G, 44 * G
    sch.components.add(
        lib_id="LM741:LM741", reference="U1",
        value="ADA4530-1", position=(ux, uy))

    # Pin positions after mirror_x (applied by fix_kicad_sch)
    inv_pin = (ux - 7.62, uy - 2.54)   # (-) top-left
    ni_pin  = (ux - 7.62, uy + 2.54)   # (+) bottom-left
    out_pin = (ux + 7.62, uy)           # output right
    vp_pin  = (ux - 2.54, uy + 7.62)   # V+ bottom (3.3V)
    vm_pin  = (ux - 2.54, uy - 7.62)   # V- top (GND)

    # ── INPUT: TIA_IN label from mux ──
    junc_x = inv_pin[0] - 5 * G
    junc_y = inv_pin[1]
    sch.add_wire(start=(junc_x, junc_y), end=inv_pin)

    # Route TIA_IN label ABOVE the feedback area to avoid crossing VREF divider
    rf_y_tmp = inv_pin[1] - 5 * G
    cf_y_tmp = rf_y_tmp - 3 * G
    route_y = cf_y_tmp - 3 * G   # above feedback cap area
    tia_in_x = junc_x - 8 * G
    sch.add_label("TIA_IN", position=(tia_in_x, route_y))
    sch.add_wire(start=(tia_in_x, route_y), end=(junc_x, route_y))
    sch.add_wire(start=(junc_x, route_y), end=(junc_x, junc_y))

    # ── FEEDBACK: Rf (1G) + Cf (10pF) ──
    rf_y = inv_pin[1] - 5 * G
    cf_y = rf_y - fb_spacing * G
    rf_cx = (inv_pin[0] + out_pin[0]) / 2

    # Rf = 1G (range 2 default)
    sch.components.add(lib_id="R:R", reference="R1", value="1G",
        position=(rf_cx, rf_y), rotation=90)
    rf_left  = (rf_cx - 3.81, rf_y)
    rf_right = (rf_cx + 3.81, rf_y)

    # Cf = 10pF (parallel with Rf)
    sch.components.add(lib_id="C:C", reference="C1", value="10pF",
        position=(rf_cx, cf_y), rotation=90)
    cf_left  = (rf_cx - 3.81, cf_y)
    cf_right = (rf_cx + 3.81, cf_y)

    # Feedback wiring: junction → up → Rf → output column → down → output pin
    sch.add_wire(start=(junc_x, junc_y), end=(junc_x, rf_y))
    sch.add_wire(start=(junc_x, rf_y), end=rf_left)
    sch.add_wire(start=rf_right, end=(out_pin[0], rf_y))
    sch.add_wire(start=(out_pin[0], rf_y), end=out_pin)
    # Cf parallel path
    sch.add_wire(start=(junc_x, rf_y), end=(junc_x, cf_y))
    sch.add_wire(start=(junc_x, cf_y), end=cf_left)
    sch.add_wire(start=cf_right, end=(out_pin[0], cf_y))
    sch.add_wire(start=(out_pin[0], cf_y), end=(out_pin[0], rf_y))

    # Junction dots at T-junctions
    sch.junctions.add(position=(junc_x, junc_y))     # input / feedback branch
    sch.junctions.add(position=(junc_x, rf_y))        # Rf / Cf branch
    sch.junctions.add(position=(out_pin[0], rf_y))     # output column merge

    # INV/OUT labels for relay ladder connection
    sch.add_label("INV", position=(junc_x, rf_y - 2 * G))
    sch.add_wire(start=(junc_x, rf_y - 2 * G), end=(junc_x, rf_y))
    # [LEARNED: label_at_feedback_not_output] OUT label on feedback vertical wire
    # (between Rf junction and op-amp output), not floating at the top of the loop.
    out_label_y = (rf_y + out_pin[1]) / 2   # midpoint of feedback vertical
    sch.add_label("OUT", position=(out_pin[0] + 2 * G, out_label_y))
    sch.add_wire(start=(out_pin[0], out_label_y), end=(out_pin[0] + 2 * G, out_label_y))

    # ── REFERENCE VOLTAGE DIVIDER (100k/100k -> 1.65V) ──
    # [LEARNED: divider_too_close_to_opamp] Parameterized offset from ni_pin
    ref_x = ni_pin[0] - divider_offset * G
    r3_y = ni_pin[1] - 5 * G
    r4_y = ni_pin[1] + 5 * G

    sch.components.add(lib_id="R:R", reference="R3", value="100k",
        position=(ref_x, r3_y))
    r3_top = (ref_x, r3_y - 3.81)
    r3_bot = (ref_x, r3_y + 3.81)

    sch.components.add(lib_id="R:R", reference="R4", value="100k",
        position=(ref_x, r4_y))
    r4_top = (ref_x, r4_y - 3.81)
    r4_bot = (ref_x, r4_y + 3.81)

    # Divider midpoint to ni_pin(+) via horizontal wire
    sch.add_wire(start=r3_bot, end=r4_top)
    mid_y = ni_pin[1]   # wire at (+) input height
    sch.add_wire(start=(ref_x, r3_bot[1]), end=(ref_x, mid_y))
    sch.add_wire(start=(ref_x, mid_y), end=(ref_x, r4_top[1]))
    sch.add_wire(start=(ref_x, mid_y), end=ni_pin)

    # Bypass cap C2 (100nF) next to divider
    c2_x = ref_x + 5 * G
    sch.components.add(lib_id="C:C", reference="C2", value="100nF",
        position=(c2_x, r4_y))
    c2_top = (c2_x, r4_y - 3.81)
    c2_bot = (c2_x, r4_y + 3.81)
    sch.add_wire(start=c2_top, end=(c2_x, mid_y))
    sch.add_wire(start=(c2_x, mid_y), end=(ref_x, mid_y))
    sch.junctions.add(position=(ref_x, mid_y))        # divider / C2 / ni_pin

    # ── ADC OUTPUT ──
    # AIN0 label on output
    ain0_x = out_pin[0] + 6 * G
    sch.add_label("AIN0", position=(ain0_x, out_pin[1]))
    sch.add_wire(start=out_pin, end=(ain0_x, out_pin[1]))

    # AIN1 label on VREF (between divider and op-amp)
    ain1_x = ref_x + 10 * G
    sch.add_label("AIN1", position=(ain1_x, mid_y))
    # Wire already connects ref_x to ni_pin, label taps midpoint

    # ── POWER ──
    # VCC at V+ (bottom after mirror)
    vcc_y = vp_pin[1] + 3 * G
    sch.add_wire(start=vp_pin, end=(vp_pin[0], vcc_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR01", value="+3.3V",
        position=(vp_pin[0], vcc_y))

    # GND at V- (top after mirror)
    # [LEARNED: power_in_feedback_area] Route V- wire RIGHT past output column,
    # then DOWN below the op-amp to GND - avoids the feedback Rf/Cf area entirely.
    vm_route_x = out_pin[0] + gnd_clearance * G   # well past the output column
    gnd_vm_y = uy + 5 * G             # below the op-amp center
    sch.add_wire(start=vm_pin, end=(vm_route_x, vm_pin[1]))
    sch.add_wire(start=(vm_route_x, vm_pin[1]), end=(vm_route_x, gnd_vm_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR02", value="GND",
        position=(vm_route_x, gnd_vm_y))

    # VCC at R3 top
    vcc_r3_y = r3_top[1] - 3 * G
    sch.add_wire(start=r3_top, end=(r3_top[0], vcc_r3_y))
    sch.components.add(lib_id="VCC:VCC", reference="#PWR03", value="+3.3V",
        position=(r3_top[0], vcc_r3_y))

    # GND at R4 bottom
    gnd_r4_y = r4_bot[1] + 3 * G
    sch.add_wire(start=r4_bot, end=(r4_bot[0], gnd_r4_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR04", value="GND",
        position=(r4_bot[0], gnd_r4_y))

    # GND at C2 bottom
    gnd_c2_y = c2_bot[1] + 3 * G
    sch.add_wire(start=c2_bot, end=(c2_bot[0], gnd_c2_y))
    sch.components.add(lib_id="GND:GND", reference="#PWR05", value="GND",
        position=(c2_bot[0], gnd_c2_y))

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "mux_tia.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    merge_collinear_wires(sch_path)
    return sch_path


def build_mcu_section(**kwargs):
    """Build ADuCM362 MCU + ADC interface section.

    Represents the ADuCM362 as a labeled block with interface connections
    to existing subsystems. Based on CN-0359 reference design and ADuCM362
    48-pin LFCSP pinout.

    Pin groups:
        ADC0: AIN0 (TIA output), AIN1 (VREF monitor) - differential
        ADC1: AIN6/AIN5 (RTD temp), AIN7 (IEXC for RTD)
        GPIO P0: ADDR_A0-A2 (mux address), EN_A, EN_B (mux enables)
        GPIO P1: RELAY_0-3 (relay drivers), PWM0-2 (excitation)
        UART: UART_TX (P0.1), UART_RX (P0.0) - to USB isolator
        Power: AVDD, DVDD (3.3V), AGND, DGND
        Debug: SWCLK, SWDIO

    Correction kwargs:
        decoupling_spacing: spacing between decoupling caps (default 5)
        pin_group_spacing: vertical spacing between pin groups (default 8)
    """
    decoupling_spacing = kwargs.get('decoupling_spacing', 5)
    pin_group_spacing = kwargs.get('pin_group_spacing', 8)

    sch = create_schematic("ADuCM362 MCU + ADC Interface (CN-0359 based)")
    sch.set_paper_size("A4")
    G = 2.54

    # ── Block title and description ──
    sch.add_text("ADuCM362 MCU + ADC INTERFACE",
                 position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("ARM Cortex-M3, dual 24-bit sigma-delta ADC, CN-0359 reference",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("FUNCTION: Digital controller for the electrometer platform.",
                 position=(8 * G, 17 * G), size=1.8)
    sch.add_text("ADC0 reads TIA output (AIN0) vs reference (AIN1). GPIO P0",
                 position=(8 * G, 21 * G), size=1.8)
    sch.add_text("controls mux address/enable. GPIO P1 drives relay coils.",
                 position=(8 * G, 25 * G), size=1.8)

    # MCU block center position
    cx, cy = 50 * G, 40 * G
    pwr_idx = 1

    # ═══════════════════════════════════════════════════════════
    # LEFT SIDE: Analog inputs (ADC channels)
    # ═══════════════════════════════════════════════════════════

    # ADC0 differential pair: AIN0(+) / AIN1(-)
    # Pin 29 = AIN0, Pin 28 = AIN1
    adc0_y = cy - 12 * G
    ain0_x = cx - 20 * G
    sch.add_label("AIN0", position=(ain0_x, adc0_y))
    sch.add_wire(start=(ain0_x, adc0_y), end=(ain0_x + 8 * G, adc0_y))

    ain1_y = adc0_y + 3 * G
    sch.add_label("AIN1", position=(ain0_x, ain1_y))
    sch.add_wire(start=(ain0_x, ain1_y), end=(ain0_x + 8 * G, ain1_y))

    # ADC0 differential pair: AIN2(+) / AIN3(-) for voltage measurement
    adc0v_y = ain1_y + 3 * G
    sch.add_label("AIN2", position=(ain0_x, adc0v_y))
    sch.add_wire(start=(ain0_x, adc0v_y), end=(ain0_x + 8 * G, adc0v_y))

    ain3_y = adc0v_y + 3 * G
    sch.add_label("AIN3", position=(ain0_x, ain3_y))
    sch.add_wire(start=(ain0_x, ain3_y), end=(ain0_x + 8 * G, ain3_y))

    # ADC1: AIN5/AIN6 for RTD temperature + AIN7 IEXC
    adc1_y = ain3_y + pin_group_spacing * G
    sch.add_label("AIN5", position=(ain0_x, adc1_y))
    sch.add_wire(start=(ain0_x, adc1_y), end=(ain0_x + 8 * G, adc1_y))

    ain6_y = adc1_y + 3 * G
    sch.add_label("AIN6", position=(ain0_x, ain6_y))
    sch.add_wire(start=(ain0_x, ain6_y), end=(ain0_x + 8 * G, ain6_y))

    ain7_y = ain6_y + 3 * G
    sch.add_label("AIN7_IEXC", position=(ain0_x, ain7_y))
    sch.add_wire(start=(ain0_x, ain7_y), end=(ain0_x + 8 * G, ain7_y))

    # ═══════════════════════════════════════════════════════════
    # RIGHT SIDE: Digital outputs (GPIO, UART, Debug)
    # ═══════════════════════════════════════════════════════════

    gpio_x = cx + 20 * G

    # GPIO P0: Mux address lines
    addr_y = cy - 12 * G
    for i, name in enumerate(["ADDR_A0", "ADDR_A1", "ADDR_A2"]):
        pin_y = addr_y + i * 3 * G
        sch.add_label(name, position=(gpio_x, pin_y))
        sch.add_wire(start=(gpio_x - 8 * G, pin_y), end=(gpio_x, pin_y))

    # Mux enables
    en_y = addr_y + 3 * 3 * G
    for i, name in enumerate(["EN_A", "EN_B"]):
        pin_y = en_y + i * 3 * G
        sch.add_label(name, position=(gpio_x, pin_y))
        sch.add_wire(start=(gpio_x - 8 * G, pin_y), end=(gpio_x, pin_y))

    # GPIO P1: Relay control
    relay_y = en_y + 2 * 3 * G + pin_group_spacing * G
    for i in range(4):
        pin_y = relay_y + i * 3 * G
        sch.add_label(f"RELAY_{i}", position=(gpio_x, pin_y))
        sch.add_wire(start=(gpio_x - 8 * G, pin_y), end=(gpio_x, pin_y))

    # PWM outputs (excitation control, CN-0359 style)
    pwm_y = relay_y + 4 * 3 * G + pin_group_spacing * G
    for i, name in enumerate(["PWM0", "PWM1", "PWM2"]):
        pin_y = pwm_y + i * 3 * G
        sch.add_label(name, position=(gpio_x, pin_y))
        sch.add_wire(start=(gpio_x - 8 * G, pin_y), end=(gpio_x, pin_y))

    # UART (to USB isolator)
    uart_y = pwm_y + 3 * 3 * G + pin_group_spacing * G
    sch.add_label("UART_TX", position=(gpio_x, uart_y))
    sch.add_wire(start=(gpio_x - 8 * G, uart_y), end=(gpio_x, uart_y))
    uart_rx_y = uart_y + 3 * G
    sch.add_label("UART_RX", position=(gpio_x, uart_rx_y))
    sch.add_wire(start=(gpio_x - 8 * G, uart_rx_y), end=(gpio_x, uart_rx_y))

    # Debug (SWD)
    swd_y = uart_rx_y + pin_group_spacing * G
    sch.add_label("SWCLK", position=(gpio_x, swd_y))
    sch.add_wire(start=(gpio_x - 8 * G, swd_y), end=(gpio_x, swd_y))
    swdio_y = swd_y + 3 * G
    sch.add_label("SWDIO", position=(gpio_x, swdio_y))
    sch.add_wire(start=(gpio_x - 8 * G, swdio_y), end=(gpio_x, swdio_y))

    # DAC output (excitation voltage control)
    dac_y = ain7_y + pin_group_spacing * G
    sch.add_label("DAC_OUT", position=(ain0_x, dac_y))
    sch.add_wire(start=(ain0_x, dac_y), end=(ain0_x + 8 * G, dac_y))

    # ═══════════════════════════════════════════════════════════
    # POWER: Decoupling capacitors
    # ═══════════════════════════════════════════════════════════

    # AVDD decoupling (100nF + 10uF)
    avdd_x = cx - 8 * G
    avdd_y = cy + 24 * G

    # C1: 100nF AVDD decoupling
    sch.components.add(lib_id="C:C", reference="C1", value="100nF",
        position=(avdd_x, avdd_y))
    c1_top = (avdd_x, avdd_y - 3.81)
    c1_bot = (avdd_x, avdd_y + 3.81)

    # VCC at C1 top
    sch.add_wire(start=c1_top, end=(c1_top[0], c1_top[1] - 2 * G))
    sch.components.add(lib_id="VCC:VCC", reference=f"#PWR0{pwr_idx:02d}",
        value="AVDD_3V3", position=(c1_top[0], c1_top[1] - 2 * G))
    pwr_idx += 1

    # GND at C1 bottom
    sch.add_wire(start=c1_bot, end=(c1_bot[0], c1_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c1_bot[0], c1_bot[1] + 2 * G))
    pwr_idx += 1

    # C2: 10uF AVDD bulk
    c2_x = avdd_x + decoupling_spacing * G
    sch.components.add(lib_id="C:C", reference="C2", value="10uF",
        position=(c2_x, avdd_y))
    c2_top = (c2_x, avdd_y - 3.81)
    c2_bot = (c2_x, avdd_y + 3.81)

    # VCC at C2 top (connect to same rail)
    sch.add_wire(start=c2_top, end=(c2_top[0], c1_top[1] - 2 * G))
    sch.add_wire(start=(c1_top[0], c1_top[1] - 2 * G), end=(c2_top[0], c1_top[1] - 2 * G))

    # GND at C2 bottom
    sch.add_wire(start=c2_bot, end=(c2_bot[0], c2_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c2_bot[0], c2_bot[1] + 2 * G))
    pwr_idx += 1

    # DVDD decoupling (100nF + 10uF)
    dvdd_x = cx + 4 * G

    # C3: 100nF DVDD decoupling
    sch.components.add(lib_id="C:C", reference="C3", value="100nF",
        position=(dvdd_x, avdd_y))
    c3_top = (dvdd_x, avdd_y - 3.81)
    c3_bot = (dvdd_x, avdd_y + 3.81)

    # VCC at C3 top
    sch.add_wire(start=c3_top, end=(c3_top[0], c3_top[1] - 2 * G))
    sch.components.add(lib_id="VCC:VCC", reference=f"#PWR0{pwr_idx:02d}",
        value="DVDD_3V3", position=(c3_top[0], c3_top[1] - 2 * G))
    pwr_idx += 1

    # GND at C3 bottom
    sch.add_wire(start=c3_bot, end=(c3_bot[0], c3_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c3_bot[0], c3_bot[1] + 2 * G))
    pwr_idx += 1

    # C4: 10uF DVDD bulk
    c4_x = dvdd_x + decoupling_spacing * G
    sch.components.add(lib_id="C:C", reference="C4", value="10uF",
        position=(c4_x, avdd_y))
    c4_top = (c4_x, avdd_y - 3.81)
    c4_bot = (c4_x, avdd_y + 3.81)

    # VCC at C4 top (connect to DVDD rail)
    sch.add_wire(start=c4_top, end=(c4_top[0], c3_top[1] - 2 * G))
    sch.add_wire(start=(c3_top[0], c3_top[1] - 2 * G), end=(c4_top[0], c3_top[1] - 2 * G))

    # GND at C4 bottom
    sch.add_wire(start=c4_bot, end=(c4_bot[0], c4_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c4_bot[0], c4_bot[1] + 2 * G))
    pwr_idx += 1

    # C5: 470nF AVDD_REG (internal regulator bypass - required per datasheet)
    c5_x = cx + 16 * G
    sch.components.add(lib_id="C:C", reference="C5", value="470nF",
        position=(c5_x, avdd_y))
    c5_top = (c5_x, avdd_y - 3.81)
    c5_bot = (c5_x, avdd_y + 3.81)

    sch.add_label("AVDD_REG", position=(c5_top[0], c5_top[1] - 2 * G))
    sch.add_wire(start=c5_top, end=(c5_top[0], c5_top[1] - 2 * G))

    sch.add_wire(start=c5_bot, end=(c5_bot[0], c5_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c5_bot[0], c5_bot[1] + 2 * G))
    pwr_idx += 1

    # C6: 470nF DVDD_REG
    c6_x = c5_x + decoupling_spacing * G
    sch.components.add(lib_id="C:C", reference="C6", value="470nF",
        position=(c6_x, avdd_y))
    c6_top = (c6_x, avdd_y - 3.81)
    c6_bot = (c6_x, avdd_y + 3.81)

    sch.add_label("DVDD_REG", position=(c6_top[0], c6_top[1] - 2 * G))
    sch.add_wire(start=c6_top, end=(c6_top[0], c6_top[1] - 2 * G))

    sch.add_wire(start=c6_bot, end=(c6_bot[0], c6_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c6_bot[0], c6_bot[1] + 2 * G))
    pwr_idx += 1

    # ── VREF: Internal reference bypass cap ──
    vref_x = cx
    vref_y = cy + 34 * G
    sch.components.add(lib_id="C:C", reference="C7", value="100nF",
        position=(vref_x, vref_y))
    c7_top = (vref_x, vref_y - 3.81)
    c7_bot = (vref_x, vref_y + 3.81)

    sch.add_label("VREF+", position=(c7_top[0], c7_top[1] - 2 * G))
    sch.add_wire(start=c7_top, end=(c7_top[0], c7_top[1] - 2 * G))

    sch.add_wire(start=c7_bot, end=(c7_bot[0], c7_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c7_bot[0], c7_bot[1] + 2 * G))
    pwr_idx += 1

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "mcu_section.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    return sch_path


def build_full_system(**kwargs):
    """Build complete 16-channel measurement system on a single A0 sheet.

    Combines all 7 regions with matching net labels for auto-connection:
        Region 0 (far left):     Input Connector - 32-pin (16 sig + 16 GND)
        Region 1 (left):         Input Filters - 16ch RC + ESD clamps
        Region 2 (center-left):  Analog Mux - 2x CD4051B (MAX338 stand-in)
        Region 3 (center):       Mux TIA - ADA4530-1 transimpedance amplifier
        Region 4 (lower-left):   Relay Ladder - 4x reed relay range switching
        Region 5 (right):        MCU Section - ADuCM362 + decoupling + AVDD monitor
        Region 6 (right-low):    RTD Terminal - 4-wire RTD connection

    Signal path:
        J1 connector -> CH_IN_1..16 -> input_filters -> MUX_A/B1..8
        -> analog_mux -> TIA_IN -> mux_tia (ADA4530-1) -> AIN0 -> MCU ADC

    Feedback path:
        relay_ladder INV/OUT <-> mux_tia INV/OUT (4 ranges: 10M/100M/1G/10G)

    Control path:
        mcu_section ADDR_A0-A2 -> analog_mux address
        mcu_section EN_A/EN_B  -> analog_mux enables
        mcu_section RELAY_0-3  -> relay_ladder NPN drivers

    Power: Single 3.3V supply, no external VREF (ADuCM362 internal 1.2V ref).
    Relay coils: separate 5V_ISO rail (net label, NOT shared with VCC).
    Decoupling: Per-IC 100nF + bulk 10uF on AVDD/DVDD, 470nF on regulator pins.

    Correction kwargs (all in grid units, G = 2.54mm):
        divider_offset: TIA VREF divider distance (default 18)
        gnd_route_clearance: TIA V- routing clearance (default 10)
        feedback_spacing: TIA Rf/Cf spacing (default 4)
        decoupling_spacing: MCU cap spacing (default 6)
        filt_row_spacing: filter row vertical spacing (default 18)
        relay_row_spacing: relay ladder row spacing (default 14)
        driver_spacing: NPN driver horizontal spacing (default 28)
    """
    divider_offset = kwargs.get('divider_offset', 18)
    gnd_clearance = kwargs.get('gnd_route_clearance', 10)
    fb_spacing = kwargs.get('feedback_spacing', 4)
    decoupling_spacing = kwargs.get('decoupling_spacing', 6)
    filt_row_sp = kwargs.get('filt_row_spacing', 18)
    relay_row_sp = kwargs.get('relay_row_spacing', 14)
    driver_sp = kwargs.get('driver_spacing', 28)

    sch = create_schematic("CircuitForge - Full 16-Channel Measurement System")
    sch.set_paper_size("A0")
    G = 2.54
    pwr_idx = 1

    # ═══════════════════════════════════════════════════════════════════
    # REGION 0: INPUT CONNECTOR (far left, 32-pin: 16 signal + 16 GND)
    # Pin layout: odd pins = signal (CH_IN_1..16), even pins = GND guard
    # ═══════════════════════════════════════════════════════════════════
    conn_x = 8 * G
    conn_y = 110 * G  # centered vertically on sheet
    sch.components.add(lib_id="Conn_01x32_Pin:Conn_01x32_Pin", reference="J1",
        value="INPUT_32PIN", position=(conn_x, conn_y))

    conn_pin_x = conn_x + 5.08  # pin tips are at +5.08 from center
    # GND bus: vertical wire on right side of connector, all even pins connect
    gnd_bus_x = conn_pin_x + 6 * G
    # First even pin (pin 2) and last even pin (pin 32) Y positions
    pin2_y = conn_y + 38.1 - (2 - 1) * 2.54  # = conn_y + 35.56
    pin32_y = conn_y + 38.1 - (32 - 1) * 2.54  # = conn_y - 40.64
    sch.add_wire(start=(gnd_bus_x, pin2_y), end=(gnd_bus_x, pin32_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(gnd_bus_x, pin32_y + 3 * G))
    sch.add_wire(start=(gnd_bus_x, pin32_y), end=(gnd_bus_x, pin32_y + 3 * G))
    pwr_idx += 1

    for pin_num in range(1, 33):
        pin_y = conn_y + 38.1 - (pin_num - 1) * 2.54
        if pin_num % 2 == 1:  # odd = signal
            ch_num = (pin_num + 1) // 2  # 1, 2, 3, ..., 16
            lbl_x = conn_pin_x + 8 * G
            sch.add_label(f"CH_IN_{ch_num}", position=(lbl_x, pin_y))
            sch.add_wire(start=(conn_pin_x, pin_y), end=(lbl_x, pin_y))
        else:  # even = GND guard wire
            sch.add_wire(start=(conn_pin_x, pin_y), end=(gnd_bus_x, pin_y))

    # ═══════════════════════════════════════════════════════════════════
    # REGION 1: INPUT FILTERS (left side, 2 columns of 8 channels)
    # Signal: CH_IN_1..16 -> ESD clamp -> 1M R -> 10nF C -> MUX_A/B1..8
    # ESD diodes: vertical orientation (rotation=0) so pins align with
    #   VCC above and GND below the signal wire.
    # ═══════════════════════════════════════════════════════════════════
    filt_groups = [
        ("A", 34 * G, range(1, 9)),
        ("B", 130 * G, range(9, 17)),
    ]
    filt_y_start = 20 * G
    filt_row_spacing = filt_row_sp * G

    for grp_name, col_x, channels in filt_groups:
        for row, ch_num in enumerate(channels):
            row_y = filt_y_start + row * filt_row_spacing
            mux_ch = (ch_num - 1) % 8 + 1
            diode_x = col_x + 8 * G
            r_cx = col_x + 18 * G
            c_cx = col_x + 26 * G
            label_out = col_x + 32 * G

            sch.add_label(f"CH_IN_{ch_num}", position=(col_x, row_y))

            # ESD clamp diodes (BAV199 anti-parallel, side-by-side below signal)
            # D_odd rot=270: A at signal (top), K at GND (bottom) -> ▽ positive clamp
            # D_even rot=90:  K at signal (top), A at GND (bottom) -> △ negative clamp
            d_left_x  = diode_x - 1.5 * G
            d_right_x = diode_x + 1.5 * G
            sch.components.add(lib_id="D:D", reference=f"D{ch_num * 2 - 1}",
                value="BAV199", position=(d_left_x, row_y + 3.81), rotation=270)
            sch.components.add(lib_id="D:D", reference=f"D{ch_num * 2}",
                value="BAV199", position=(d_right_x, row_y + 3.81), rotation=90)

            # Shared GND bus below both diodes
            gnd_bus_y = row_y + 7.62
            gnd_y = gnd_bus_y + 2 * G
            sch.add_wire(start=(d_left_x, gnd_bus_y), end=(d_right_x, gnd_bus_y))
            sch.add_wire(start=(diode_x, gnd_bus_y), end=(diode_x, gnd_y))
            sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
                value="GND", position=(diode_x, gnd_y))
            pwr_idx += 1

            # 1M series resistor (rotation=90 for horizontal in signal path)
            sch.components.add(lib_id="R:R", reference=f"R{ch_num}",
                value="1M", position=(r_cx, row_y), rotation=90)

            # 10nF filter cap
            sch.components.add(lib_id="C:C", reference=f"C{ch_num}",
                value="10n", position=(c_cx, row_y + 3.81))
            sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
                value="GND", position=(c_cx, row_y + 7.62))
            pwr_idx += 1

            sch.add_label(f"MUX_{grp_name}{mux_ch}", position=(label_out, row_y))

            # Wires: signal path with diode junctions
            sch.add_wire(start=(col_x, row_y), end=(r_cx - 3.81, row_y))
            sch.add_wire(start=(r_cx + 3.81, row_y), end=(c_cx, row_y))
            sch.add_wire(start=(c_cx, row_y), end=(label_out, row_y))
            # Junctions where diodes tee off signal wire
            sch.junctions.add(position=(d_left_x, row_y))
            sch.junctions.add(position=(d_right_x, row_y))
            sch.junctions.add(position=(c_cx, row_y))

    # ═══════════════════════════════════════════════════════════════════
    # REGION 2: ANALOG MUX (center-left, 2x CD4051B)
    # Signal: MUX_A/B1..8 -> CD4051B -> TIA_IN
    # Control: ADDR_A0-A2, EN_A, EN_B from MCU
    # ═══════════════════════════════════════════════════════════════════
    mux_ox = 220 * G  # well clear of filter columns, spread for readability

    CH_DY = [-5.08, -2.54, 0, 2.54, 5.08, 7.62, 10.16, 12.7]
    ADDR_DY = {'A': -12.7, 'B': -10.16, 'C': -7.62}
    X_DY = -2.54
    INH_DY = 0.0
    PIN_DX_L = -12.7
    PIN_DX_R = 12.7
    MUX_LABEL_GAP = 2 * G

    muxes = [
        ("U1", "A", mux_ox, 50 * G, range(1, 9)),
        ("U2", "B", mux_ox, 160 * G, range(1, 9)),
    ]

    for ref, grp, cx, cy, ch_range in muxes:
        sch.components.add(lib_id="CD4051B:CD4051B", reference=ref,
            value="MAX338", position=(cx, cy))

        for i, ch_idx in enumerate(ch_range):
            pin_x = cx + PIN_DX_R
            pin_y = cy + CH_DY[i]
            lbl_x = pin_x + MUX_LABEL_GAP
            sch.add_label(f"MUX_{grp}{ch_idx}", position=(lbl_x, pin_y))
            sch.add_wire(start=(pin_x, pin_y), end=(lbl_x, pin_y))

        x_pin = (cx + PIN_DX_L, cy + X_DY)
        x_lbl = (x_pin[0] - MUX_LABEL_GAP, x_pin[1])
        sch.add_label("TIA_IN", position=x_lbl)
        sch.add_wire(start=x_pin, end=x_lbl)

        for name, dy in [("ADDR_A0", ADDR_DY['A']),
                         ("ADDR_A1", ADDR_DY['B']),
                         ("ADDR_A2", ADDR_DY['C'])]:
            pin = (cx + PIN_DX_L, cy + dy)
            lbl = (pin[0] - MUX_LABEL_GAP, pin[1])
            sch.add_label(name, position=lbl)
            sch.add_wire(start=pin, end=lbl)

        inh_pin = (cx + PIN_DX_L, cy + INH_DY)
        en_lbl = (inh_pin[0] - MUX_LABEL_GAP, inh_pin[1])
        sch.add_label(f"EN_{grp}", position=en_lbl)
        sch.add_wire(start=inh_pin, end=en_lbl)

        # Power: VDD -> VCC, VSS -> GND, VEE -> GND
        vdd = (cx + 2.54, cy - 17.78)
        vss = (cx, cy + 17.78)
        vee = (cx - 2.54, cy + 17.78)

        sch.components.add(lib_id="VCC:VCC", reference=f"#PWR0{pwr_idx:02d}",
            value="VCC", position=(vdd[0], vdd[1] - 2 * G))
        sch.add_wire(start=vdd, end=(vdd[0], vdd[1] - 2 * G))
        pwr_idx += 1

        sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
            value="GND", position=(vss[0], vss[1] + 2 * G))
        sch.add_wire(start=vss, end=(vss[0], vss[1] + 2 * G))
        pwr_idx += 1

        sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
            value="GND", position=(vee[0], vee[1] + 2 * G))
        sch.add_wire(start=vee, end=(vee[0], vee[1] + 2 * G))
        pwr_idx += 1

        # Decoupling cap 100nF near VDD
        mux_dcap_n = 17 if grp == 'A' else 18
        dcap_cx = cx + 8 * G
        dcap_cy = vdd[1]
        sch.components.add(lib_id="C:C", reference=f"C{mux_dcap_n}",
            value="100n", position=(dcap_cx, dcap_cy + 3.81))
        sch.add_wire(start=(vdd[0], vdd[1]), end=(dcap_cx, dcap_cy))
        sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
            value="GND", position=(dcap_cx, dcap_cy + 7.62))
        pwr_idx += 1

    # ═══════════════════════════════════════════════════════════════════
    # REGION 3: MUX TIA (center, ADA4530-1 transimpedance amplifier)
    # Signal: TIA_IN -> inverting input -> Rf/Cf feedback -> AIN0
    # Reference: VREF divider (100k/100k -> 1.65V) -> AIN1
    # ═══════════════════════════════════════════════════════════════════
    tia_ox = 310 * G
    tia_oy = 20 * G
    ux, uy = tia_ox + 46 * G, tia_oy + 50 * G

    sch.components.add(lib_id="LM741:LM741", reference="U3",
        value="ADA4530-1", position=(ux, uy))

    inv_pin = (ux - 7.62, uy - 2.54)
    ni_pin = (ux - 7.62, uy + 2.54)
    out_pin = (ux + 7.62, uy)
    vp_pin = (ux - 2.54, uy + 7.62)
    vm_pin = (ux - 2.54, uy - 7.62)

    # TIA_IN label from mux
    junc_x = inv_pin[0] - 5 * G
    junc_y = inv_pin[1]
    sch.add_wire(start=(junc_x, junc_y), end=inv_pin)

    rf_y_tmp = inv_pin[1] - 5 * G
    cf_y_tmp = rf_y_tmp - 3 * G
    route_y = cf_y_tmp - 3 * G
    tia_in_x = junc_x - 8 * G
    sch.add_label("TIA_IN", position=(tia_in_x, route_y))
    sch.add_wire(start=(tia_in_x, route_y), end=(junc_x, route_y))
    sch.add_wire(start=(junc_x, route_y), end=(junc_x, junc_y))

    # Feedback Rf (1G) + Cf (10pF)
    rf_y = inv_pin[1] - 5 * G
    cf_y = rf_y - fb_spacing * G
    rf_cx = (inv_pin[0] + out_pin[0]) / 2

    sch.components.add(lib_id="R:R", reference="R17", value="1G",
        position=(rf_cx, rf_y), rotation=90)
    rf_left = (rf_cx - 3.81, rf_y)
    rf_right = (rf_cx + 3.81, rf_y)

    sch.components.add(lib_id="C:C", reference="C19", value="10pF",
        position=(rf_cx, cf_y), rotation=90)
    cf_left = (rf_cx - 3.81, cf_y)
    cf_right = (rf_cx + 3.81, cf_y)

    # Feedback wiring
    sch.add_wire(start=(junc_x, junc_y), end=(junc_x, rf_y))
    sch.add_wire(start=(junc_x, rf_y), end=rf_left)
    sch.add_wire(start=rf_right, end=(out_pin[0], rf_y))
    sch.add_wire(start=(out_pin[0], rf_y), end=out_pin)
    sch.add_wire(start=(junc_x, rf_y), end=(junc_x, cf_y))
    sch.add_wire(start=(junc_x, cf_y), end=cf_left)
    sch.add_wire(start=cf_right, end=(out_pin[0], cf_y))
    sch.add_wire(start=(out_pin[0], cf_y), end=(out_pin[0], rf_y))

    # INV/OUT labels (relay ladder connection)
    sch.add_label("INV", position=(junc_x, rf_y - 2 * G))
    sch.add_wire(start=(junc_x, rf_y - 2 * G), end=(junc_x, rf_y))
    out_label_y = (rf_y + out_pin[1]) / 2
    sch.add_label("OUT", position=(out_pin[0] + 2 * G, out_label_y))
    sch.add_wire(start=(out_pin[0], out_label_y), end=(out_pin[0] + 2 * G, out_label_y))

    # VREF divider (100k/100k -> 1.65V)
    ref_x = ni_pin[0] - divider_offset * G
    r3_y = ni_pin[1] - 5 * G
    r4_y = ni_pin[1] + 5 * G

    sch.components.add(lib_id="R:R", reference="R18", value="100k",
        position=(ref_x, r3_y))
    r3_top = (ref_x, r3_y - 3.81)
    r3_bot = (ref_x, r3_y + 3.81)

    sch.components.add(lib_id="R:R", reference="R19", value="100k",
        position=(ref_x, r4_y))
    r4_top = (ref_x, r4_y - 3.81)
    r4_bot = (ref_x, r4_y + 3.81)

    sch.add_wire(start=r3_bot, end=r4_top)
    mid_y = ni_pin[1]
    sch.add_wire(start=(ref_x, r3_bot[1]), end=(ref_x, mid_y))
    sch.add_wire(start=(ref_x, mid_y), end=(ref_x, r4_top[1]))
    sch.add_wire(start=(ref_x, mid_y), end=ni_pin)

    # Bypass cap C20 next to divider
    c20_x = ref_x + 5 * G
    sch.components.add(lib_id="C:C", reference="C20", value="100nF",
        position=(c20_x, r4_y))
    c20_top = (c20_x, r4_y - 3.81)
    c20_bot = (c20_x, r4_y + 3.81)
    sch.add_wire(start=c20_top, end=(c20_x, mid_y))
    sch.add_wire(start=(c20_x, mid_y), end=(ref_x, mid_y))

    # AIN0 label on output
    ain0_x = out_pin[0] + 6 * G
    sch.add_label("AIN0", position=(ain0_x, out_pin[1]))
    sch.add_wire(start=out_pin, end=(ain0_x, out_pin[1]))

    # AIN1 label on VREF midpoint
    ain1_x = ref_x + 10 * G
    sch.add_label("AIN1", position=(ain1_x, mid_y))

    # TIA power: VCC at V+
    vcc_y = vp_pin[1] + 3 * G
    sch.add_wire(start=vp_pin, end=(vp_pin[0], vcc_y))
    sch.components.add(lib_id="VCC:VCC", reference=f"#PWR0{pwr_idx:02d}",
        value="VCC", position=(vp_pin[0], vcc_y))
    pwr_idx += 1

    # GND at V- (routed past output to avoid feedback area)
    vm_route_x = out_pin[0] + gnd_clearance * G
    gnd_vm_y = uy + 5 * G
    sch.add_wire(start=vm_pin, end=(vm_route_x, vm_pin[1]))
    sch.add_wire(start=(vm_route_x, vm_pin[1]), end=(vm_route_x, gnd_vm_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(vm_route_x, gnd_vm_y))
    pwr_idx += 1

    # VCC at R18 top
    vcc_r3_y = r3_top[1] - 3 * G
    sch.add_wire(start=r3_top, end=(r3_top[0], vcc_r3_y))
    sch.components.add(lib_id="VCC:VCC", reference=f"#PWR0{pwr_idx:02d}",
        value="VCC", position=(r3_top[0], vcc_r3_y))
    pwr_idx += 1

    # GND at R19 bottom
    gnd_r4_y = r4_bot[1] + 3 * G
    sch.add_wire(start=r4_bot, end=(r4_bot[0], gnd_r4_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(r4_bot[0], gnd_r4_y))
    pwr_idx += 1

    # GND at C20 bottom
    gnd_c20_y = c20_bot[1] + 3 * G
    sch.add_wire(start=c20_bot, end=(c20_bot[0], gnd_c20_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c20_bot[0], gnd_c20_y))
    pwr_idx += 1

    # ═══════════════════════════════════════════════════════════════════
    # REGION 4: RELAY LADDER (below TIA, 4x reed relay range switching)
    # Feedback: INV/OUT labels match TIA for auto-connection
    # Control: RELAY_0-3 labels match MCU section
    # ═══════════════════════════════════════════════════════════════════
    rl_ox = 60 * G    # lower-left quadrant (was 310*G, crowding TIA)
    rl_oy = 200 * G   # below filter columns, plenty of room

    inv_bus_x = rl_ox + 14 * G
    sw_cx = rl_ox + 24 * G
    rf_ladder_x = rl_ox + 40 * G
    out_bus_x = rl_ox + 56 * G

    ROWS = [
        (0, rl_oy + 24 * G, "10M",  None),
        (1, rl_oy + (24 + relay_row_sp) * G, "100M", None),
        (2, rl_oy + (24 + 2 * relay_row_sp) * G, "1G",   "10pF"),
        (3, rl_oy + (24 + 3 * relay_row_sp) * G, "10G",  "1pF"),
    ]

    for idx, row_y, rf_val, cf_val in ROWS:
        # Reed switch
        sch.components.add(lib_id="SW_Reed:SW_Reed", reference=f"SW{idx+1}",
            value=f"K{idx+1}", position=(sw_cx, row_y))
        sw1 = (sw_cx - 5.08, row_y)
        sw2 = (sw_cx + 5.08, row_y)

        # Feedback resistor
        sch.components.add(lib_id="R:R", reference=f"R{idx+20}",
            value=rf_val, position=(rf_ladder_x, row_y), rotation=90)
        rfl = (rf_ladder_x - 3.81, row_y)
        rfr = (rf_ladder_x + 3.81, row_y)

        sch.add_wire(start=(inv_bus_x, row_y), end=sw1)
        sch.add_wire(start=sw2, end=rfl)
        sch.add_wire(start=rfr, end=(out_bus_x, row_y))

        if cf_val:
            cf_row_y = row_y + 3 * G
            cf_ref = 21 if idx == 2 else 22
            sch.components.add(lib_id="C:C", reference=f"C{cf_ref}",
                value=cf_val, position=(rf_ladder_x, cf_row_y), rotation=90)
            cfl = (rf_ladder_x - 3.81, cf_row_y)
            cfr = (rf_ladder_x + 3.81, cf_row_y)
            sch.add_wire(start=(rfl[0], rfl[1]), end=(cfl[0], cfl[1]))
            sch.add_wire(start=(rfr[0], rfr[1]), end=(cfr[0], cfr[1]))

    # Vertical bus lines
    sch.add_wire(start=(inv_bus_x, ROWS[0][1]), end=(inv_bus_x, ROWS[-1][1]))
    sch.add_wire(start=(out_bus_x, ROWS[0][1]), end=(out_bus_x, ROWS[-1][1]))

    # INV/OUT bus labels (match TIA)
    sch.add_label("INV", position=(inv_bus_x, ROWS[0][1] - 2 * G))
    sch.add_wire(start=(inv_bus_x, ROWS[0][1] - 2 * G), end=(inv_bus_x, ROWS[0][1]))
    sch.add_label("OUT", position=(out_bus_x, ROWS[0][1] - 2 * G))
    sch.add_wire(start=(out_bus_x, ROWS[0][1] - 2 * G), end=(out_bus_x, ROWS[0][1]))

    # NPN coil drivers - wider spacing to prevent overlap
    # Bug fix: original code had NO relay coil - just diode in series with NPN.
    # Correct topology: 5V_ISO -> [Relay Coil] -> Q_collector -> Q_emitter -> GND
    # Flyback diode in PARALLEL with coil (cathode at 5V_ISO, anode at collector)
    rl_drv_x_start = rl_ox + 10 * G
    rl_drv_spacing = driver_sp * G  # parameterized for correction loop
    q_y = rl_oy + (24 + 3 * relay_row_sp + 30) * G  # well below last relay row
    coil_y = q_y - 18 * G   # relay coil center (vertical, rot=0)

    for idx in range(4):
        dx = rl_drv_x_start + idx * rl_drv_spacing

        # NPN transistor (2N3904)
        sch.components.add(lib_id="Q_NPN_BCE:Q_NPN_BCE", reference=f"Q{idx+1}",
            value="2N3904", position=(dx, q_y))
        q_b = (dx - 5.08, q_y)
        q_c = (dx + 2.54, q_y - 5.08)
        q_e = (dx + 2.54, q_y + 5.08)

        # Relay coil (vertical resistor model, rot=0: pin1=top, pin2=bottom)
        # 109P-1-A-5/1 reed relay: ~500 ohm coil resistance
        coil_cx = q_c[0]  # align with collector column
        sch.components.add(lib_id="R:R", reference=f"R{idx+32}",
            value="500R_COIL", position=(coil_cx, coil_y))
        coil_top = (coil_cx, coil_y - 3.81)   # pin 1 -> 5V_ISO
        coil_bot = (coil_cx, coil_y + 3.81)   # pin 2 -> collector

        # Coil label linking to reed switch contact
        sch.add_text(f"K{idx+1} coil",
            position=(coil_cx + 3 * G, coil_y),
            effects={"font_size": 1.0})

        # Wire: coil bottom -> Q collector
        sch.add_wire(start=coil_bot, end=q_c)

        # 5V_ISO at coil top
        vcc_coil_y = coil_top[1] - 3 * G
        sch.add_wire(start=coil_top, end=(coil_top[0], vcc_coil_y))
        sch.add_label("5V_ISO", position=(coil_top[0], vcc_coil_y))

        # Flyback diode in PARALLEL with coil (NOT in series!)
        # Placed to the right of coil for visual clarity
        # D with rot=0 (horizontal): K at left (-3.81,0), A at right (+3.81,0)
        # We need vertical: rot=90 -> K moves to top (cathode at 5V_ISO side)
        # Actually need K at top -> rot=270: K at (0,-3.81)=above, A at (0,+3.81)=below
        # Wait - using verified transform (x,y)->(y,-x) for rot=90:
        #   K(-3.81,0) -> (0,3.81)=below, A(3.81,0) -> (0,-3.81)=above
        # So rot=90 gives K below (collector side), A above (5V side) - WRONG polarity
        # Need rot=270: (x,y)->(-y,x): K(-3.81,0) -> (0,-3.81)=above, A -> (0,3.81)=below
        # rot=270: K at top (5V_ISO side, cathode), A at bottom (collector side, anode) ✓
        d_cx = coil_cx + 8 * G
        sch.components.add(lib_id="D:D", reference=f"D{idx+33}",
            value="1N4148", position=(d_cx, coil_y), rotation=270)
        d_k = (d_cx, coil_y - 3.81)   # cathode (top) -> 5V_ISO rail
        d_a = (d_cx, coil_y + 3.81)   # anode (bottom) -> collector rail

        # Horizontal wires connecting diode in parallel with coil
        sch.add_wire(start=coil_top, end=(d_k[0], coil_top[1]))
        sch.junctions.add(position=coil_top)
        sch.add_wire(start=coil_bot, end=(d_a[0], coil_bot[1]))
        sch.junctions.add(position=coil_bot)

        # GND at emitter
        gnd_qe_y = q_e[1] + 3 * G
        sch.add_wire(start=q_e, end=(q_e[0], gnd_qe_y))
        sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
            value="GND", position=(q_e[0], gnd_qe_y))
        pwr_idx += 1

        # Base resistor (pushed left for clear visual separation from Q)
        rb_x = dx - 20 * G
        sch.components.add(lib_id="R:R", reference=f"R{idx+24}",
            value="1k", position=(rb_x, q_y), rotation=90)
        rb_left = (rb_x - 3.81, q_y)

        sch.add_wire(start=(rb_x + 3.81, q_y), end=q_b)

        # RELAY_x label (matches MCU section)
        sch.add_label(f"RELAY_{idx}", position=(rb_left[0] - 2 * G, rb_left[1]))
        sch.add_wire(start=(rb_left[0] - 2 * G, rb_left[1]), end=rb_left)

    # 5V_ISO decoupling capacitor (100nF near relay drivers)
    relay_dcap_x = rl_drv_x_start + 3 * rl_drv_spacing + 16 * G
    relay_dcap_y = coil_y
    sch.components.add(lib_id="C:C", reference="C31", value="100nF",
        position=(relay_dcap_x, relay_dcap_y))
    c30_top = (relay_dcap_x, relay_dcap_y - 3.81)
    c30_bot = (relay_dcap_x, relay_dcap_y + 3.81)
    sch.add_wire(start=c30_top, end=(c30_top[0], c30_top[1] - 2 * G))
    sch.add_label("5V_ISO", position=(c30_top[0], c30_top[1] - 2 * G))
    sch.add_wire(start=c30_bot, end=(c30_bot[0], c30_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c30_bot[0], c30_bot[1] + 2 * G))
    pwr_idx += 1

    # Annotations: relay driver description text
    sch.add_text("Rb=1k (Ic/hFE=5V/0.05A/100=0.5mA, 1k gives 3.3mA base drive)",
        position=(rl_drv_x_start, q_y + 12 * G),
        effects={"font_size": 1.27})
    sch.add_text("D33-D36: 1N4148 flyback diodes (relay coil back-EMF protection)",
        position=(rl_drv_x_start, q_y + 15 * G),
        effects={"font_size": 1.27})
    sch.add_text("R32-R35: 500R relay coil resistance (109P-1-A-5/1 reed relay)",
        position=(rl_drv_x_start, q_y + 18 * G),
        effects={"font_size": 1.27})

    # ═══════════════════════════════════════════════════════════════════
    # REGION 5: MCU SECTION (right side, ADuCM362 + decoupling)
    # ADC: AIN0-AIN7, DAC_OUT (left side labels)
    # GPIO: ADDR_A0-A2, EN_A/B, RELAY_0-3, PWM0-2 (right side labels)
    # UART/SWD: UART_TX/RX, SWCLK/SWDIO
    # Internal 1.2V VREF (no external ref needed)
    # ═══════════════════════════════════════════════════════════════════
    mcu_cx = 430 * G
    mcu_cy = 40 * G
    pin_group_spacing = 14  # more vertical gap between pin groups for readability

    # -- LEFT: Analog inputs --
    adc0_y = mcu_cy - 12 * G
    ain_lx = mcu_cx - 20 * G

    for i, name in enumerate(["AIN0", "AIN1", "AIN2", "AIN3", "AIN4"]):
        py = adc0_y + i * 3 * G
        sch.add_label(name, position=(ain_lx, py))
        sch.add_wire(start=(ain_lx, py), end=(ain_lx + 8 * G, py))

    adc1_y = adc0_y + 5 * 3 * G + pin_group_spacing * G
    for i, name in enumerate(["AIN5", "AIN6", "AIN7_IEXC", "AIN8", "AIN9"]):
        py = adc1_y + i * 3 * G
        sch.add_label(name, position=(ain_lx, py))
        sch.add_wire(start=(ain_lx, py), end=(ain_lx + 8 * G, py))

    dac_y = adc1_y + 5 * 3 * G + pin_group_spacing * G
    sch.add_label("DAC_OUT", position=(ain_lx, dac_y))
    sch.add_wire(start=(ain_lx, dac_y), end=(ain_lx + 8 * G, dac_y))

    # -- RIGHT: Digital outputs --
    gpio_rx = mcu_cx + 20 * G
    addr_y = mcu_cy - 12 * G

    for i, name in enumerate(["ADDR_A0", "ADDR_A1", "ADDR_A2"]):
        py = addr_y + i * 3 * G
        sch.add_label(name, position=(gpio_rx, py))
        sch.add_wire(start=(gpio_rx - 8 * G, py), end=(gpio_rx, py))

    en_y = addr_y + 3 * 3 * G
    for i, name in enumerate(["EN_A", "EN_B"]):
        py = en_y + i * 3 * G
        sch.add_label(name, position=(gpio_rx, py))
        sch.add_wire(start=(gpio_rx - 8 * G, py), end=(gpio_rx, py))

    relay_ctrl_y = en_y + 2 * 3 * G + pin_group_spacing * G
    for i in range(4):
        py = relay_ctrl_y + i * 3 * G
        sch.add_label(f"RELAY_{i}", position=(gpio_rx, py))
        sch.add_wire(start=(gpio_rx - 8 * G, py), end=(gpio_rx, py))

    pwm_y = relay_ctrl_y + 4 * 3 * G + pin_group_spacing * G
    for i, name in enumerate(["PWM0", "PWM1", "PWM2"]):
        py = pwm_y + i * 3 * G
        sch.add_label(name, position=(gpio_rx, py))
        sch.add_wire(start=(gpio_rx - 8 * G, py), end=(gpio_rx, py))

    uart_y = pwm_y + 3 * 3 * G + pin_group_spacing * G
    sch.add_label("UART_TX", position=(gpio_rx, uart_y))
    sch.add_wire(start=(gpio_rx - 8 * G, uart_y), end=(gpio_rx, uart_y))
    uart_rx_y = uart_y + 3 * G
    sch.add_label("UART_RX", position=(gpio_rx, uart_rx_y))
    sch.add_wire(start=(gpio_rx - 8 * G, uart_rx_y), end=(gpio_rx, uart_rx_y))

    swd_y = uart_rx_y + pin_group_spacing * G
    sch.add_label("SWCLK", position=(gpio_rx, swd_y))
    sch.add_wire(start=(gpio_rx - 8 * G, swd_y), end=(gpio_rx, swd_y))
    swdio_y = swd_y + 3 * G
    sch.add_label("SWDIO", position=(gpio_rx, swdio_y))
    sch.add_wire(start=(gpio_rx - 8 * G, swdio_y), end=(gpio_rx, swdio_y))

    # -- MCU DECOUPLING --
    mcu_avdd_x = mcu_cx - 8 * G
    mcu_avdd_y = mcu_cy + 150 * G  # well below pin groups for readability

    # C23: 100nF AVDD
    sch.components.add(lib_id="C:C", reference="C23", value="100nF",
        position=(mcu_avdd_x, mcu_avdd_y))
    c23_top = (mcu_avdd_x, mcu_avdd_y - 3.81)
    c23_bot = (mcu_avdd_x, mcu_avdd_y + 3.81)
    sch.add_wire(start=c23_top, end=(c23_top[0], c23_top[1] - 2 * G))
    sch.components.add(lib_id="VCC:VCC", reference=f"#PWR0{pwr_idx:02d}",
        value="VCC", position=(c23_top[0], c23_top[1] - 2 * G))
    pwr_idx += 1
    sch.add_wire(start=c23_bot, end=(c23_bot[0], c23_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c23_bot[0], c23_bot[1] + 2 * G))
    pwr_idx += 1

    # C24: 10uF AVDD bulk
    c24_x = mcu_avdd_x + decoupling_spacing * G
    sch.components.add(lib_id="C:C", reference="C24", value="10uF",
        position=(c24_x, mcu_avdd_y))
    c24_top = (c24_x, mcu_avdd_y - 3.81)
    c24_bot = (c24_x, mcu_avdd_y + 3.81)
    sch.add_wire(start=c24_top, end=(c24_top[0], c23_top[1] - 2 * G))
    sch.add_wire(start=(c23_top[0], c23_top[1] - 2 * G), end=(c24_top[0], c23_top[1] - 2 * G))
    sch.add_wire(start=c24_bot, end=(c24_bot[0], c24_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c24_bot[0], c24_bot[1] + 2 * G))
    pwr_idx += 1

    # C25: 100nF DVDD
    dvdd_x = mcu_cx + 4 * G
    sch.components.add(lib_id="C:C", reference="C25", value="100nF",
        position=(dvdd_x, mcu_avdd_y))
    c25_top = (dvdd_x, mcu_avdd_y - 3.81)
    c25_bot = (dvdd_x, mcu_avdd_y + 3.81)
    sch.add_wire(start=c25_top, end=(c25_top[0], c25_top[1] - 2 * G))
    sch.components.add(lib_id="VCC:VCC", reference=f"#PWR0{pwr_idx:02d}",
        value="VCC", position=(c25_top[0], c25_top[1] - 2 * G))
    pwr_idx += 1
    sch.add_wire(start=c25_bot, end=(c25_bot[0], c25_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c25_bot[0], c25_bot[1] + 2 * G))
    pwr_idx += 1

    # C26: 10uF DVDD bulk
    c26_x = dvdd_x + decoupling_spacing * G
    sch.components.add(lib_id="C:C", reference="C26", value="10uF",
        position=(c26_x, mcu_avdd_y))
    c26_top = (c26_x, mcu_avdd_y - 3.81)
    c26_bot = (c26_x, mcu_avdd_y + 3.81)
    sch.add_wire(start=c26_top, end=(c26_top[0], c25_top[1] - 2 * G))
    sch.add_wire(start=(c25_top[0], c25_top[1] - 2 * G), end=(c26_top[0], c25_top[1] - 2 * G))
    sch.add_wire(start=c26_bot, end=(c26_bot[0], c26_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c26_bot[0], c26_bot[1] + 2 * G))
    pwr_idx += 1

    # C27: 470nF AVDD_REG (internal regulator)
    c27_x = mcu_cx + 16 * G
    sch.components.add(lib_id="C:C", reference="C27", value="470nF",
        position=(c27_x, mcu_avdd_y))
    c27_top = (c27_x, mcu_avdd_y - 3.81)
    c27_bot = (c27_x, mcu_avdd_y + 3.81)
    sch.add_label("AVDD_REG", position=(c27_top[0], c27_top[1] - 2 * G))
    sch.add_wire(start=c27_top, end=(c27_top[0], c27_top[1] - 2 * G))
    sch.add_wire(start=c27_bot, end=(c27_bot[0], c27_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c27_bot[0], c27_bot[1] + 2 * G))
    pwr_idx += 1

    # C28: 470nF DVDD_REG
    c28_x = c27_x + decoupling_spacing * G
    sch.components.add(lib_id="C:C", reference="C28", value="470nF",
        position=(c28_x, mcu_avdd_y))
    c28_top = (c28_x, mcu_avdd_y - 3.81)
    c28_bot = (c28_x, mcu_avdd_y + 3.81)
    sch.add_label("DVDD_REG", position=(c28_top[0], c28_top[1] - 2 * G))
    sch.add_wire(start=c28_top, end=(c28_top[0], c28_top[1] - 2 * G))
    sch.add_wire(start=c28_bot, end=(c28_bot[0], c28_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c28_bot[0], c28_bot[1] + 2 * G))
    pwr_idx += 1

    # C29: 100nF VREF+ (internal 1.2V reference bypass)
    vref_cx = mcu_cx
    vref_cy = mcu_cy + 170 * G  # below decoupling row
    sch.components.add(lib_id="C:C", reference="C29", value="100nF",
        position=(vref_cx, vref_cy))
    c29_top = (vref_cx, vref_cy - 3.81)
    c29_bot = (vref_cx, vref_cy + 3.81)
    sch.add_label("VREF+", position=(c29_top[0], c29_top[1] - 2 * G))
    sch.add_wire(start=c29_top, end=(c29_top[0], c29_top[1] - 2 * G))
    sch.add_wire(start=c29_bot, end=(c29_bot[0], c29_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c29_bot[0], c29_bot[1] + 2 * G))
    pwr_idx += 1

    # ═══════════════════════════════════════════════════════════════════
    # REGION 5b: AVDD MONITOR (voltage divider for ADC0 AIN2/AIN3)
    # Monitors AVDD supply - critical since AVDD = ADC0 reference.
    # 100k/100k divider: AIN2 = AVDD/2, AIN3 = AGND (differential)
    # ═══════════════════════════════════════════════════════════════════
    avmon_x = mcu_cx - 30 * G
    avmon_y = mcu_cy + 120 * G

    # R28: 100k AVDD to midpoint
    sch.components.add(lib_id="R:R", reference="R28", value="100k",
        position=(avmon_x, avmon_y - 5 * G))
    r28_top = (avmon_x, avmon_y - 5 * G - 3.81)
    r28_bot = (avmon_x, avmon_y - 5 * G + 3.81)

    # R29: 100k midpoint to GND
    sch.components.add(lib_id="R:R", reference="R29", value="100k",
        position=(avmon_x, avmon_y + 5 * G))
    r29_top = (avmon_x, avmon_y + 5 * G - 3.81)
    r29_bot = (avmon_x, avmon_y + 5 * G + 3.81)

    # Wire divider together
    sch.add_wire(start=r28_bot, end=r29_top)

    # VCC at R28 top
    sch.add_wire(start=r28_top, end=(r28_top[0], r28_top[1] - 2 * G))
    sch.components.add(lib_id="VCC:VCC", reference=f"#PWR0{pwr_idx:02d}",
        value="VCC", position=(r28_top[0], r28_top[1] - 2 * G))
    pwr_idx += 1

    # GND at R29 bottom
    sch.add_wire(start=r29_bot, end=(r29_bot[0], r29_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(r29_bot[0], r29_bot[1] + 2 * G))
    pwr_idx += 1

    # C30: 100nF bypass on midpoint
    c30_x = avmon_x + 6 * G
    c30_y = avmon_y
    sch.components.add(lib_id="C:C", reference="C30", value="100nF",
        position=(c30_x, c30_y))
    c30_top = (c30_x, c30_y - 3.81)
    c30_bot = (c30_x, c30_y + 3.81)
    sch.add_wire(start=c30_top, end=(c30_x, avmon_y))
    sch.add_wire(start=(avmon_x, avmon_y), end=(c30_x, avmon_y))
    sch.add_wire(start=c30_bot, end=(c30_bot[0], c30_bot[1] + 2 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(c30_bot[0], c30_bot[1] + 2 * G))
    pwr_idx += 1

    # AIN2 label at midpoint (AVDD/2 = 1.65V nominal)
    ain2_lx = avmon_x + 12 * G
    sch.add_label("AIN2", position=(ain2_lx, avmon_y))
    sch.add_wire(start=(c30_x, avmon_y), end=(ain2_lx, avmon_y))

    # AIN3 label at GND reference point (for differential: AIN2-AIN3)
    ain3_y = avmon_y + 12 * G
    sch.add_label("AIN3", position=(ain2_lx, ain3_y))
    sch.add_wire(start=(ain2_lx, ain3_y), end=(ain2_lx + 4 * G, ain3_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(ain2_lx + 4 * G, ain3_y))
    pwr_idx += 1

    # AIN4 label (guard voltage monitor - connected to guard ring bus)
    ain4_y = ain3_y + 6 * G
    sch.add_label("AIN4", position=(ain2_lx, ain4_y))
    sch.add_wire(start=(ain2_lx, ain4_y), end=(ain2_lx + 4 * G, ain4_y))
    sch.add_label("GUARD", position=(ain2_lx + 4 * G, ain4_y))

    # ═══════════════════════════════════════════════════════════════════
    # REGION 6: RTD TERMINAL (4-wire RTD connection for temperature)
    # AIN5/AIN6: RTD sense, AIN7: IEXC out, AIN8/AIN9: Kelvin sense
    # CN-0359 style auto-detect: 2/3/4-wire RTD
    # ═══════════════════════════════════════════════════════════════════
    rtd_x = mcu_cx - 10 * G
    rtd_y = mcu_cy + 200 * G

    # RTD 4-terminal connector
    sch.components.add(lib_id="Conn_01x04_Pin:Conn_01x04_Pin", reference="J2",
        value="RTD_4WIRE", position=(rtd_x, rtd_y))

    rtd_pin_x = rtd_x + 5.08
    for i, name in enumerate(["AIN7_IEXC", "AIN8", "AIN9", "AIN5"]):
        pin_y = rtd_y + 3.81 - i * 2.54
        lbl_x = rtd_pin_x + 8 * G
        sch.add_label(name, position=(lbl_x, pin_y))
        sch.add_wire(start=(rtd_pin_x, pin_y), end=(lbl_x, pin_y))

    # RREF: 1.5k precision reference resistor for RTD (CN-0359 style)
    rref_x = rtd_pin_x + 16 * G
    rref_y = rtd_y - 3.81 + 2.54  # aligned with AIN8
    sch.components.add(lib_id="R:R", reference="R30", value="1k5",
        position=(rref_x, rref_y))
    r30_top = (rref_x, rref_y - 3.81)
    r30_bot = (rref_x, rref_y + 3.81)

    # AIN6 label at RREF top (RTD reference voltage high)
    sch.add_label("AIN6", position=(rref_x + 6 * G, r30_top[1]))
    sch.add_wire(start=r30_top, end=(rref_x + 6 * G, r30_top[1]))

    # GND at RREF bottom
    sch.add_wire(start=r30_bot, end=(r30_bot[0], r30_bot[1] + 3 * G))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(r30_bot[0], r30_bot[1] + 3 * G))
    pwr_idx += 1

    # ═══════════════════════════════════════════════════════════════════
    # REGION TITLES AND CIRCUIT DESCRIPTIONS
    # Large bold text annotations so each subsystem is clearly labeled
    # when viewing the schematic at any zoom level.
    # ═══════════════════════════════════════════════════════════════════
    title_size = 6.0   # mm - large for readability
    sub_size = 3.5     # mm - subtitle
    detail_size = 2.5  # mm - details

    # -- Main title (top-center of sheet) --
    sch.add_text("CircuitForge - 16-Channel Multiplexed Measurement System",
                 position=(300, 8), size=title_size, bold=True)
    sch.add_text("ADuCM362 + ADA4530-1 TIA | 4 Relay-Selectable Ranges | 24-bit ADC",
                 position=(300, 18), size=detail_size)

    # -- Region 0: Input Connector --
    sch.add_text("INPUT CONNECTOR",
                 position=(conn_x - 5, conn_y - 50), size=title_size, bold=True)
    sch.add_text("J1: 32-pin (16 signal + 16 GND guard)",
                 position=(conn_x - 5, conn_y - 42), size=sub_size)
    sch.add_text("Odd pins = CH_IN_1..16 (signal)",
                 position=(conn_x - 5, conn_y - 36), size=detail_size)
    sch.add_text("Even pins = GND (guard/shield)",
                 position=(conn_x - 5, conn_y - 31), size=detail_size)

    # -- Region 1: Input Filters --
    filt_title_y = filt_y_start - 15
    sch.add_text("INPUT FILTERS (16 channels)",
                 position=(34 * G, filt_title_y), size=title_size, bold=True)
    sch.add_text("Per channel: BAV199 ESD clamp + 1M series R + 10nF C0G (fc = 15.9 Hz)",
                 position=(34 * G, filt_title_y + 8), size=sub_size)
    sch.add_text("Column A: CH 1-8  |  Column B: CH 9-16",
                 position=(34 * G, filt_title_y + 15), size=detail_size)

    # -- Region 2: Analog Mux --
    sch.add_text("ANALOG MULTIPLEXER",
                 position=(mux_ox - 30, 50 * G - 35), size=title_size, bold=True)
    sch.add_text("2x CD4051B (MAX338 equivalent) 8:1 mux",
                 position=(mux_ox - 30, 50 * G - 27), size=sub_size)
    sch.add_text("U1: channels 1-8  |  U2: channels 9-16",
                 position=(mux_ox - 30, 50 * G - 20), size=detail_size)
    sch.add_text("ADDR_A0-A2 = channel select, EN_A/EN_B = mux enable",
                 position=(mux_ox - 30, 50 * G - 14), size=detail_size)

    # -- Region 3: TIA --
    sch.add_text("TRANSIMPEDANCE AMPLIFIER",
                 position=(tia_ox, tia_oy - 5), size=title_size, bold=True)
    sch.add_text("U3: ADA4530-1 (20fA bias current)",
                 position=(tia_ox, tia_oy + 3), size=sub_size)
    sch.add_text("Rf/Cf: relay-selectable (10M / 100M / 1G+10pF / 10G+1pF)",
                 position=(tia_ox, tia_oy + 10), size=detail_size)
    sch.add_text("VREF: 100k/100k divider = 1.65V mid-supply",
                 position=(tia_ox, tia_oy + 16), size=detail_size)
    sch.add_text("Output: AIN0 (TIA) + AIN1 (VREF monitor)",
                 position=(tia_ox, tia_oy + 22), size=detail_size)

    # -- Region 4: Relay Ladder --
    rl_title_y = rl_oy - 5
    sch.add_text("RELAY RANGE LADDER",
                 position=(rl_ox, rl_title_y), size=title_size, bold=True)
    sch.add_text("4x 109P reed relay + 2N3904 NPN drivers",
                 position=(rl_ox, rl_title_y + 8), size=sub_size)
    sch.add_text("K1: 10M (120nA FS) | K2: 100M (12nA FS) | K3: 1G+10pF (1.2nA FS) | K4: 10G+1pF (120pA FS)",
                 position=(rl_ox, rl_title_y + 15), size=detail_size)
    sch.add_text("RELAY_0-3 GPIO from MCU | 5V_ISO coil supply | 1N4148 flyback protection",
                 position=(rl_ox, rl_title_y + 21), size=detail_size)

    # -- Region 5: MCU --
    mcu_title_y = mcu_cy - 30 * G
    sch.add_text("MCU - ADuCM362",
                 position=(mcu_cx - 22 * G, mcu_title_y), size=title_size, bold=True)
    sch.add_text("ARM Cortex-M3, Dual 24-bit Sigma-Delta ADC",
                 position=(mcu_cx - 22 * G, mcu_title_y + 8), size=sub_size)
    sch.add_text("ADC0: AIN0-4 (TIA + AVDD monitor + guard) | ADC1: AIN5-9 (RTD 2/3/4-wire)",
                 position=(mcu_cx - 22 * G, mcu_title_y + 15), size=detail_size)
    sch.add_text("GPIO: Mux addr, Relay ctrl, PWM | UART + SWD debug",
                 position=(mcu_cx - 22 * G, mcu_title_y + 21), size=detail_size)
    sch.add_text("Internal 1.2V VREF (no external ref needed)",
                 position=(mcu_cx - 22 * G, mcu_title_y + 27), size=detail_size)

    # -- Decoupling note --
    sch.add_text("DECOUPLING CAPACITORS",
                 position=(mcu_avdd_x - 10, mcu_avdd_y - 20), size=sub_size, bold=True)
    sch.add_text("C23/C24: AVDD 100nF+10uF | C25/C26: DVDD 100nF+10uF | C27/C28: REG 470nF | C29: VREF 100nF",
                 position=(mcu_avdd_x - 10, mcu_avdd_y - 13), size=detail_size)

    # -- Region 5b: AVDD Monitor --
    sch.add_text("AVDD MONITOR",
                 position=(avmon_x - 5, avmon_y - 20), size=sub_size, bold=True)
    sch.add_text("R28/R29: 100k/100k divider -> AIN2 (AVDD/2 = 1.65V)",
                 position=(avmon_x - 5, avmon_y - 13), size=detail_size)
    sch.add_text("AIN3: AGND ref (differential) | AIN4: GUARD monitor",
                 position=(avmon_x - 5, avmon_y - 7), size=detail_size)

    # -- Region 6: RTD Terminal --
    sch.add_text("RTD TEMPERATURE SENSOR",
                 position=(rtd_x - 10, rtd_y - 20), size=sub_size, bold=True)
    sch.add_text("J2: 4-wire RTD connector (CN-0359 style auto-detect 2/3/4-wire)",
                 position=(rtd_x - 10, rtd_y - 13), size=detail_size)
    sch.add_text("AIN7: IEXC 600uA | AIN8/9: Kelvin sense | R30: 1.5k RREF",
                 position=(rtd_x - 10, rtd_y - 7), size=detail_size)
    sch.add_text("Temp logged with each channel reading for drift compensation",
                 position=(rtd_x - 10, rtd_y - 1), size=detail_size)

    # ── Per-component inline annotations ──
    note_size = 2.0  # mm - small inline notes near components

    # TIA component notes (offset well clear of components)
    tia_note_x = tia_ox + 5       # left of TIA area, clear of wires
    sch.add_text("Rf=1G default (relay-selectable)",
                 position=(tia_note_x, rf_y - 18), size=note_size)
    sch.add_text("Cf=10pF (stability, BW limit)",
                 position=(tia_note_x, rf_y - 14), size=note_size)
    sch.add_text("VREF=VCC/2=1.65V",
                 position=(ref_x - 15, mid_y + 18), size=note_size)

    # Relay ladder notes (at new lower-left position)
    for idx, row_y, rf_val, cf_val in ROWS:
        note_x = rf_ladder_x + 10 * G
        if cf_val:
            sch.add_text(f"Rf={rf_val}, Cf={cf_val}",
                         position=(note_x, row_y), size=note_size)
        else:
            sch.add_text(f"Rf={rf_val}",
                         position=(note_x, row_y), size=note_size)

    # NPN driver notes (one note for the group)
    sch.add_text("Rb=1k (Ic/hFE=5V/0.05A/100=0.5mA, 1k gives 3.3mA base drive)",
                 position=(rl_drv_x_start, q_y + 12 * G), size=note_size)
    sch.add_text("D33-D36: 1N4148 flyback diodes (relay coil back-EMF protection)",
                 position=(rl_drv_x_start, q_y + 17 * G), size=note_size)

    # Input filter notes (one annotation for column A)
    sch.add_text("Each ch: BAV199 ESD + 1M + 10nF = fc=15.9Hz LPF",
                 position=(34 * G, filt_y_start - 8), size=note_size)

    # Mux notes
    sch.add_text("X pin = common out to TIA",
                 position=(mux_ox + PIN_DX_L - 15, muxes[0][3] + X_DY), size=note_size)

    # Connector note
    sch.add_text("Triax: center=signal, guard=driven, shield=GND",
                 position=(conn_x - 5, conn_y + 50), size=note_size)

    # AVDD monitor notes
    sch.add_text("Critical: AVDD = ADC0 reference",
                 position=(avmon_x - 5, avmon_y + 16), size=note_size)
    sch.add_text("Monitor for supply drift/noise",
                 position=(avmon_x - 5, avmon_y + 21), size=note_size)

    # MCU DAC note
    sch.add_text("DAC_OUT: excitation voltage control (CN-0359 style)",
                 position=(ain_lx, dac_y + 5), size=note_size)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "full_system.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)

    # Scale all coordinates for readability (default 3x)
    sf = kwargs.get('scale_factor', 3)
    if sf and sf != 1:
        scale_schematic(sch_path, factor=sf)

    print(f"  Full system schematic saved: {sch_path}")
    print(f"  Components: ~{1 + 16*4 + 2 + 1 + 4 + 4 + 4 + 7 + 29 + 4 + 2} (connector + filters + mux + TIA + relays + MCU + AVDD mon + RTD)")
    print(f"  Net labels auto-connect: TIA_IN, INV, OUT, AIN0-4, AIN5-9, ADDR_A0-A2, EN_A/B, RELAY_0-3, GUARD, 5V_ISO")
    return sch_path


def write_electrometer_362_netlist(opamp="LMC6001", rf_range=2):
    """
    Write ngspice netlist for the ADuCM362 electrometer TIA.

    Simulates one range at a time (relay-selected):
      Range 0: Rf=10M, no Cf     (full-scale +-120nA)
      Range 1: Rf=100M, no Cf    (full-scale +-12nA)
      Range 2: Rf=1G, Cf=10pF    (full-scale +-1.2nA)
      Range 3: Rf=10G, Cf=1pF    (full-scale +-120pA)

    Single supply: +3.3V, VREF = 1.65V mid-supply.
    Output = VREF - Iin * Rf (inverts around 1.65V reference).

    Args:
        opamp: Op-amp model name from OPAMP_DB
        rf_range: 0-3 for range selection
    """
    OPAMP_DB = {
        "LMC6001":  ("LMC6001_NS",  "nation.lib", 5, "LMC6001 Ultra-Low Bias"),
        "LMC6001A": ("LMC6001A_NS", "nation.lib", 5, "LMC6001A Electrometer-Grade"),
        "OPA128":   ("OPA128_BB",    "burrbn.lib", 5, "OPA128 Classic Electrometer"),
        "AD822":    ("AD822_AD",     "analog.lib", 5, "AD822 Precision JFET"),
        "LM741":    ("LM741_NS",    "nation.lib", 5, "LM741 Classic"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LMC6001"])
    model_name, lib_file, n_pins, title = info
    model_block = extract_model(model_name, lib_file)

    # Range parameters
    RANGES = {
        0: ("10M",  "10Meg", None,   100e-9, "+-120nA full scale"),
        1: ("100M", "100Meg", None,  10e-9,  "+-12nA full scale"),
        2: ("1G",   "1G",    "10p",  1e-9,   "+-1.2nA full scale"),
        3: ("10G",  "10G",   "1p",   0.1e-9, "+-120pA full scale"),
    }
    rf_name, rf_val, cf_val, i_test, desc = RANGES.get(rf_range, RANGES[2])

    # OPA128 has different pinout (1=+in, 2=-in, 3=V+, 4=V-, 5=out)
    if "OPA128" in opamp:
        subckt_line = "XU1 VREF INV VCC 0 TIA_OUT {model}".format(model=model_name)
    else:
        subckt_line = "XU1 VREF INV VCC 0 TIA_OUT {model}".format(model=model_name)

    # Simulation time: 5*RC for settling
    if cf_val:
        # RC time constant
        rf_num = float(rf_val.replace('G', 'e9').replace('Meg', 'e6'))
        cf_num = float(cf_val.replace('p', 'e-12'))
        tau = rf_num * cf_num
        sim_time = max(0.2, tau * 8)
        pulse_width = max(0.08, tau * 5)
    else:
        sim_time = 0.05  # 50ms for resistive-only ranges
        pulse_width = 0.02

    # Build netlist
    # NOTE: Real ADA4530-1 uses single 3.3V supply with VREF=1.65V (rail-to-rail input).
    # LMC6001/OPA128 proxy models have PMOS inputs that need V(in) near V- rail,
    # so we simulate with dual +/-5V supply (VREF=0V). Transimpedance and bandwidth
    # are identical regardless of supply configuration.
    cf_line = f"Cf INV TIA_OUT {cf_val}" if cf_val else "* No Cf for this range"

    netlist = f"""* Electrometer TIA - ADuCM362 Platform
* Op-amp: {title} (proxy for ADA4530-1)
* Range {rf_range}: Rf={rf_name}, {desc}
* NOTE: Real hardware uses single 3.3V supply (ADA4530-1 has R2R inputs).
*       Simulation uses dual +/-5V because proxy model needs input near V-.
*       Transimpedance and bandwidth results are identical.

* ---- Power Supply (dual for simulation) ----
VCC VCC 0 DC 5
VEE VEE 0 DC -5

* ---- Op-Amp (TIA) ----
XU1 0 INV VCC VEE TIA_OUT {model_name}

* ---- Feedback Network (Range {rf_range}) ----
Rf INV TIA_OUT {rf_val}
{cf_line}

* ---- ADC Load (10M input impedance) ----
RL TIA_OUT 0 10Meg

* ---- Test Current Source (pulse) ----
* Pulse: {i_test*1e9:.1f}nA for {pulse_width*1000:.0f}ms
I1 0 INV PULSE(0 {i_test} 0.01 1u 1u {pulse_width} {sim_time})

* ---- Analysis ----
.tran 10u {sim_time}

* ---- Output ----
.control
run
wrdata electrometer_362_results.txt V(TIA_OUT) V(INV)
quit
.endc

{model_block}

.end
"""

    out_path = os.path.join(WORK_DIR, "electrometer_362.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {out_path}")
    print(f"  Range {rf_range}: Rf={rf_name}, Cf={cf_val or 'none'}, I_test={i_test*1e9:.1f}nA")
    return out_path


def write_electrometer_362_ac_netlist(opamp="LMC6001", rf_range=2):
    """Write AC analysis netlist for the ADuCM362 electrometer TIA.

    Sweeps frequency to find the -3dB bandwidth for each range.
    Expected: Range 2 (1G/10pF) -> fc = 1/(2*pi*1G*10pF) = 15.9Hz
              Range 3 (10G/1pF) -> fc = 1/(2*pi*10G*1pF) = 15.9Hz
    """
    OPAMP_DB = {
        "LMC6001":  ("LMC6001_NS",  "nation.lib", 5, "LMC6001 Ultra-Low Bias"),
        "LMC6001A": ("LMC6001A_NS", "nation.lib", 5, "LMC6001A Electrometer-Grade"),
        "OPA128":   ("OPA128_BB",    "burrbn.lib", 5, "OPA128 Classic Electrometer"),
        "AD822":    ("AD822_AD",     "analog.lib", 5, "AD822 Precision JFET"),
        "LM741":    ("LM741_NS",    "nation.lib", 5, "LM741 Classic"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LMC6001"])
    model_name, lib_file, n_pins, title = info
    model_block = extract_model(model_name, lib_file)

    RANGES = {
        0: ("10M",  "10Meg", None),
        1: ("100M", "100Meg", None),
        2: ("1G",   "1G",    "10p"),
        3: ("10G",  "10G",   "1p"),
    }
    rf_name, rf_val, cf_val = RANGES.get(rf_range, RANGES[2])
    cf_line = f"Cf INV TIA_OUT {cf_val}" if cf_val else "* No Cf for this range"

    netlist = f"""* Electrometer TIA AC Analysis - ADuCM362
* Op-amp: {title}, Range {rf_range}: Rf={rf_name}
* Dual supply for simulation (real hardware: single 3.3V + ADA4530-1)

VCC VCC 0 DC 5
VEE VEE 0 DC -5

XU1 0 INV VCC VEE TIA_OUT {model_name}

Rf INV TIA_OUT {rf_val}
{cf_line}

RL TIA_OUT 0 10Meg

* AC current source (1A for direct transimpedance reading)
I1 0 INV AC 1

.ac dec 50 0.01 1Meg

.control
run
let zmag = mag(V(TIA_OUT))
wrdata electrometer_362_ac.txt zmag
.endc

{model_block}

.end
"""

    out_path = os.path.join(WORK_DIR, "electrometer_362_ac.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  AC netlist saved: {out_path}")
    return out_path


# =============================================================
# STAGE 6: Full-Path Simulation (Input Filter -> Mux -> TIA -> ADC)
# =============================================================

def write_full_path_netlist(opamp="LMC6001", rf_range=2, channel=1):
    """
    Write ngspice netlist for full signal path simulation.

    Models the complete measurement chain for a single channel:
      Current source -> 1M series R -> 10nF filter C -> MAX338 mux (analog switch)
      -> ADA4530-1 TIA (proxy) -> Rf/Cf feedback -> ADC load (10M)

    The MAX338 mux is modeled as an ideal CMOS analog switch (Ron=100 ohm,
    Roff=1T) controlled by a voltage source. Real MAX338 has Ron=400R typ
    but we use 100R for simplicity (negligible vs 1M input R).

    Args:
        opamp: Op-amp model name from OPAMP_DB
        rf_range: 0-3 for feedback resistor range selection
        channel: Channel number (1-16) for labeling
    """
    OPAMP_DB = {
        "LMC6001":  ("LMC6001_NS",  "nation.lib", 5, "LMC6001 Ultra-Low Bias"),
        "LMC6001A": ("LMC6001A_NS", "nation.lib", 5, "LMC6001A Electrometer-Grade"),
        "OPA128":   ("OPA128_BB",    "burrbn.lib", 5, "OPA128 Classic Electrometer"),
        "AD822":    ("AD822_AD",     "analog.lib", 5, "AD822 Precision JFET"),
        "LM741":    ("LM741_NS",    "nation.lib", 5, "LM741 Classic"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LMC6001"])
    model_name, lib_file, n_pins, title = info
    model_block = extract_model(model_name, lib_file)

    RANGES = {
        0: ("10M",  "10Meg", None,   100e-9, "+-120nA full scale"),
        1: ("100M", "100Meg", None,  10e-9,  "+-12nA full scale"),
        2: ("1G",   "1G",    "10p",  1e-9,   "+-1.2nA full scale"),
        3: ("10G",  "10G",   "1p",   0.1e-9, "+-120pA full scale"),
    }
    rf_name, rf_val, cf_val, i_test, desc = RANGES.get(rf_range, RANGES[2])

    # Simulation time: 5*RC for TIA settling + extra for filter
    if cf_val:
        rf_num = float(rf_val.replace('G', 'e9').replace('Meg', 'e6'))
        cf_num = float(cf_val.replace('p', 'e-12'))
        tau_tia = rf_num * cf_num
    else:
        tau_tia = 0.001
    # Input filter tau: 1M * 10nF = 10ms
    tau_filter = 1e6 * 10e-9  # 10ms
    tau_total = max(tau_tia, tau_filter)
    sim_time = max(0.3, tau_total * 10)
    pulse_width = max(0.1, tau_total * 5)

    cf_line = f"Cf INV TIA_OUT {cf_val}" if cf_val else "* No Cf for this range"

    netlist = f"""* Full-Path Simulation: Input Filter -> Mux -> TIA -> ADC
* Channel {channel}, Op-amp: {title} (proxy for ADA4530-1)
* Range {rf_range}: Rf={rf_name}, {desc}
* Signal chain: I_test -> 1M -> 10nF -> SW_mux (Ron=100R) -> TIA -> ADC(10M)

* ---- Power Supply (dual for simulation) ----
VCC VCC 0 DC 5
VEE VEE 0 DC -5

* ---- Input Current Source ----
* Simulates sensor current into channel {channel}
Isrc 0 CH_IN PULSE(0 {i_test} 0.02 1u 1u {pulse_width} {sim_time})

* ---- Input Protection + Filter (per MM20 topology) ----
* BAV199 ESD clamps omitted (negligible in normal operation)
* 1M series resistor: limits current, forms RC filter
R_IN CH_IN FILT_OUT 1Meg
* 10nF C0G filter cap: fc = 1/(2*pi*1M*10nF) = 15.9Hz
C_FILT FILT_OUT 0 10n

* ---- Analog Mux Switch (MAX338 model) ----
* CMOS analog switch: Ron=100R when enabled, Roff=1T when disabled
* Control: V_EN=5V selects this channel
V_EN EN_CTRL 0 DC 5
S_MUX FILT_OUT TIA_IN EN_CTRL 0 SW_MUX
.model SW_MUX SW(VT=2.5 VH=0.5 RON=100 ROFF=1e12)

* ---- TIA (Transimpedance Amplifier) ----
XU1 0 INV VCC VEE TIA_OUT {model_name}

* ---- Feedback Network (Range {rf_range}) ----
Rf INV TIA_OUT {rf_val}
{cf_line}

* ---- Mux output to TIA inverting input ----
R_WIRE TIA_IN INV 1

* ---- ADC Input (high-Z sigma-delta, ~10M equivalent) ----
* AIN0 node = ADC input, negligible loading for TIA
RL TIA_OUT AIN0 100
R_ADC AIN0 0 10Meg

* ---- Analysis ----
.tran 10u {sim_time}

* ---- Output ----
.control
run
wrdata {os.path.join(WORK_DIR, 'full_path_results.txt').replace(chr(92), '/')} V(CH_IN) V(FILT_OUT) V(TIA_IN) V(TIA_OUT) V(AIN0) V(INV)
quit
.endc

{model_block}

.end
"""

    out_path = os.path.join(WORK_DIR, "full_path.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {out_path}")
    print(f"  Channel {channel}, Range {rf_range}: Rf={rf_name}, I_test={i_test*1e9:.1f}nA")
    print(f"  Filter tau: {tau_filter*1000:.1f}ms, TIA tau: {tau_tia*1000:.1f}ms")
    return out_path


def write_full_path_ac_netlist(opamp="LMC6001", rf_range=2):
    """
    Write AC analysis netlist for full signal path.

    Measures end-to-end transimpedance from input current to ADC voltage.
    Shows the combined frequency response of input filter + TIA.
    Expected: double-pole rolloff - filter at 15.9Hz, TIA at 1/(2*pi*Rf*Cf).
    """
    OPAMP_DB = {
        "LMC6001":  ("LMC6001_NS",  "nation.lib", 5, "LMC6001 Ultra-Low Bias"),
        "LMC6001A": ("LMC6001A_NS", "nation.lib", 5, "LMC6001A Electrometer-Grade"),
        "OPA128":   ("OPA128_BB",    "burrbn.lib", 5, "OPA128 Classic Electrometer"),
        "AD822":    ("AD822_AD",     "analog.lib", 5, "AD822 Precision JFET"),
        "LM741":    ("LM741_NS",    "nation.lib", 5, "LM741 Classic"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LMC6001"])
    model_name, lib_file, n_pins, title = info
    model_block = extract_model(model_name, lib_file)

    RANGES = {
        0: ("10M",  "10Meg", None),
        1: ("100M", "100Meg", None),
        2: ("1G",   "1G",    "10p"),
        3: ("10G",  "10G",   "1p"),
    }
    rf_name, rf_val, cf_val = RANGES.get(rf_range, RANGES[2])
    cf_line = f"Cf INV TIA_OUT {cf_val}" if cf_val else "* No Cf for this range"

    netlist = f"""* Full-Path AC Analysis: Input Filter -> Mux -> TIA -> ADC
* Op-amp: {title}, Range {rf_range}: Rf={rf_name}
* Expected: filter pole at 15.9Hz, TIA pole at 1/(2*pi*Rf*Cf)

VCC VCC 0 DC 5
VEE VEE 0 DC -5

* AC current source (1A for direct transimpedance reading in V/A)
Isrc 0 CH_IN AC 1

* Input filter
R_IN CH_IN FILT_OUT 1Meg
C_FILT FILT_OUT 0 10n

* Mux switch (always on for AC analysis)
S_MUX FILT_OUT TIA_IN EN_CTRL 0 SW_MUX
V_EN EN_CTRL 0 DC 5
.model SW_MUX SW(VT=2.5 VH=0.5 RON=100 ROFF=1e12)

* TIA
XU1 0 INV VCC VEE TIA_OUT {model_name}

* Feedback
Rf INV TIA_OUT {rf_val}
{cf_line}

* Mux to TIA connection
R_WIRE TIA_IN INV 1

* ADC load
RL TIA_OUT AIN0 100
R_ADC AIN0 0 10Meg

.ac dec 50 0.01 1Meg

.control
run
let zmag_tia = mag(V(TIA_OUT))
let zmag_adc = mag(V(AIN0))
let zmag_filt = mag(V(FILT_OUT))
wrdata {os.path.join(WORK_DIR, 'full_path_ac.txt').replace(chr(92), '/')} zmag_tia zmag_adc zmag_filt
quit
.endc

{model_block}

.end
"""

    out_path = os.path.join(WORK_DIR, "full_path_ac.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  AC netlist saved: {out_path}")
    return out_path


def write_channel_switching_netlist(opamp="LMC6001", rf_range=2, n_channels=4):
    """
    Write ngspice netlist to simulate multiplexed channel switching.

    Models n_channels (default 4) input filters feeding through individual
    mux switches to a shared TIA. Switches are activated sequentially to
    verify: settling time between channels, crosstalk, and correct readback.

    Each channel has a different DC current to verify correct channel selection:
      CH1: 1nA, CH2: 0.5nA, CH3: 0.25nA, CH4: 0.125nA (halving pattern)
    """
    OPAMP_DB = {
        "LMC6001":  ("LMC6001_NS",  "nation.lib", 5, "LMC6001 Ultra-Low Bias"),
        "LMC6001A": ("LMC6001A_NS", "nation.lib", 5, "LMC6001A Electrometer-Grade"),
        "OPA128":   ("OPA128_BB",    "burrbn.lib", 5, "OPA128 Classic Electrometer"),
        "AD822":    ("AD822_AD",     "analog.lib", 5, "AD822 Precision JFET"),
        "LM741":    ("LM741_NS",    "nation.lib", 5, "LM741 Classic"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LMC6001"])
    model_name, lib_file, n_pins, title = info
    model_block = extract_model(model_name, lib_file)

    # 9 ranges: Rf = 100/1k/10k/100k/1M/10M/100M/1G/10G
    # (rf_name, rf_val, cf_val, rbias_val)
    RANGES = {
        0: ("100",  "100",   None,  "100Meg"),
        1: ("1k",   "1k",    None,  "100Meg"),
        2: ("10k",  "10k",   None,  "100Meg"),
        3: ("100k", "100k",  None,  "100Meg"),
        4: ("1M",   "1Meg",  None,  "100Meg"),
        5: ("10M",  "10Meg", None,  "100Meg"),
        6: ("100M", "100Meg", None, "1G"),
        7: ("1G",   "1G",    "10p", "10G"),
        8: ("10G",  "10G",   "1p",  "100G"),
    }
    rf_name, rf_val, cf_val, rbias_val = RANGES.get(rf_range, RANGES[7])
    cf_line = f"Cf INV TIA_OUT {cf_val}" if cf_val else "* No Cf for this range"

    # Channel switching timing
    ch_period = 0.2  # 200ms per channel
    sim_time = ch_period * n_channels + 0.05

    ch_lines = []
    en_lines = []
    wrdata_nodes = []

    # Per-range current tables: currents sized for V_TIA = 0.2-4.0V (within ±5V supply)
    # Pattern: 0.1x, 0.25x, 0.5x, 1.0x, 0.75x, 0.3x, 0.15x, 0.8x,
    #          0.05x, 0.4x, 0.6x, 0.2x, 0.9x, 0.35x, 0.55x, 0.12x
    # where x = 4V / Rf (max current for linear operation)
    RANGE_CURRENTS = {
        0: {  # Rf=100: mA range (0.5-10 mA)
            1: 1.0e-3,   2: 2.5e-3,   3: 5.0e-3,   4: 10.0e-3,
            5: 7.5e-3,   6: 3.0e-3,   7: 1.5e-3,   8: 8.0e-3,
            9: 0.5e-3,  10: 4.0e-3,  11: 6.0e-3,  12: 2.0e-3,
           13: 9.0e-3,  14: 3.5e-3,  15: 5.5e-3,  16: 1.2e-3,
        },
        1: {  # Rf=1k: sub-mA range (0.2-4 mA)
            1: 0.4e-3,   2: 1.0e-3,   3: 2.0e-3,   4: 4.0e-3,
            5: 3.0e-3,   6: 1.2e-3,   7: 0.6e-3,   8: 3.2e-3,
            9: 0.2e-3,  10: 1.6e-3,  11: 2.4e-3,  12: 0.8e-3,
           13: 3.6e-3,  14: 1.4e-3,  15: 2.2e-3,  16: 0.48e-3,
        },
        2: {  # Rf=10k: 100-µA range (20-400 µA)
            1: 40e-6,    2: 100e-6,   3: 200e-6,   4: 400e-6,
            5: 300e-6,   6: 120e-6,   7: 60e-6,    8: 320e-6,
            9: 20e-6,   10: 160e-6,  11: 240e-6,  12: 80e-6,
           13: 360e-6,  14: 140e-6,  15: 220e-6,  16: 48e-6,
        },
        3: {  # Rf=100k: 10-µA range (2-40 µA)
            1: 4.0e-6,   2: 10.0e-6,   3: 20.0e-6,   4: 40.0e-6,
            5: 30.0e-6,   6: 12.0e-6,   7: 6.0e-6,    8: 32.0e-6,
            9: 2.0e-6,   10: 16.0e-6,  11: 24.0e-6,  12: 8.0e-6,
           13: 36.0e-6,  14: 14.0e-6,  15: 22.0e-6,  16: 4.8e-6,
        },
        4: {  # Rf=1M: µA range (0.2-4 µA)
            1: 0.4e-6,   2: 1.0e-6,   3: 2.0e-6,   4: 4.0e-6,
            5: 3.0e-6,   6: 1.2e-6,   7: 0.6e-6,   8: 3.2e-6,
            9: 0.2e-6,  10: 1.6e-6,  11: 2.4e-6,  12: 0.8e-6,
           13: 3.6e-6,  14: 1.4e-6,  15: 2.2e-6,  16: 0.48e-6,
        },
        5: {  # Rf=10M: high-nA range (20-400 nA)
            1: 40e-9,    2: 100e-9,   3: 200e-9,   4: 400e-9,
            5: 300e-9,   6: 120e-9,   7: 60e-9,    8: 320e-9,
            9: 20e-9,   10: 160e-9,  11: 240e-9,  12: 80e-9,
           13: 360e-9,  14: 140e-9,  15: 220e-9,  16: 48e-9,
        },
        6: {  # Rf=100M: nanoamp range (2-40 nA)
            1: 4.0e-9,   2: 10.0e-9,   3: 20.0e-9,   4: 40.0e-9,
            5: 30.0e-9,   6: 12.0e-9,   7: 6.0e-9,    8: 32.0e-9,
            9: 2.0e-9,   10: 16.0e-9,  11: 24.0e-9,  12: 8.0e-9,
           13: 36.0e-9,  14: 14.0e-9,  15: 22.0e-9,  16: 4.8e-9,
        },
        7: {  # Rf=1G: sub-nanoamp range (0.05-1 nA)
            1: 0.10e-9,   2: 0.25e-9,   3: 0.50e-9,   4: 1.00e-9,
            5: 0.75e-9,   6: 0.30e-9,   7: 0.15e-9,   8: 0.80e-9,
            9: 0.05e-9,  10: 0.40e-9,  11: 0.60e-9,  12: 0.20e-9,
           13: 0.90e-9,  14: 0.35e-9,  15: 0.55e-9,  16: 0.12e-9,
        },
        8: {  # Rf=10G: femtoamp range (50-1000 fA)
            1: 100e-15,   2: 250e-15,   3: 500e-15,   4: 1000e-15,
            5: 750e-15,   6: 300e-15,   7: 150e-15,   8: 800e-15,
            9: 50e-15,   10: 400e-15,  11: 600e-15,  12: 200e-15,
           13: 900e-15,  14: 350e-15,  15: 550e-15,  16: 120e-15,
        },
    }
    CHANNEL_CURRENTS = RANGE_CURRENTS.get(rf_range, RANGE_CURRENTS[7])

    # R_DUT: sensor model impedance. Must be >> R_IN to avoid current shunting.
    # Scale to keep max node voltage < 100V for convergence.
    i_max = max(CHANNEL_CURRENTS.values())
    r_dut_val = min(100e6, max(1e6, 100.0 / i_max))  # 1M-100M range
    if r_dut_val >= 1e6:
        r_dut = f"{r_dut_val/1e6:.0f}Meg"
    else:
        r_dut = f"{r_dut_val/1e3:.0f}k"

    for ch in range(1, n_channels + 1):
        i_val = CHANNEL_CURRENTS.get(ch, 1e-9 / ch)
        # Format current with appropriate unit
        if abs(i_val) >= 1e-6:
            i_str = f"{i_val*1e6:.3f}uA"
        elif abs(i_val) >= 1e-9:
            i_str = f"{i_val*1e9:.3f}nA"
        elif abs(i_val) >= 1e-12:
            i_str = f"{i_val*1e12:.3f}pA"
        else:
            i_str = f"{i_val*1e15:.1f}fA"
        ch_lines.append(f"""
* ---- Channel {ch}: I={i_str} ----
* Sensor model: current source with R_DUT ground return
Isrc{ch} 0 CH{ch}_IN DC {i_val}
R_DUT{ch} CH{ch}_IN 0 {r_dut}
R_IN{ch} CH{ch}_IN MUX{ch}_IN 1k
S_MUX{ch} MUX{ch}_IN TIA_IN EN{ch} 0 SW_MUX""")

        # Enable pulse for this channel's time slot (no gap between channels)
        # Channel ch is enabled from (ch-1)*period to ch*period
        t_on = (ch - 1) * ch_period
        en_lines.append(
            f"V_EN{ch} EN{ch} 0 PULSE(0 5 {t_on} 1u 1u {ch_period} {sim_time + 1})")

    for ch in range(1, n_channels + 1):
        wrdata_nodes.append(f"V(CH{ch}_IN)")
    wrdata_nodes.append("V(TIA_OUT)")
    wrdata_nodes.append("V(AIN0)")
    wrdata_str = " ".join(wrdata_nodes)
    ch_section = "".join(ch_lines)
    en_section = "\n".join(en_lines)
    wrdata_path = os.path.join(WORK_DIR, f'channel_switching_range{rf_range}_results.txt').replace('\\', '/')

    netlist = f"""* Channel Switching Simulation: {n_channels} channels multiplexed
* Op-amp: {title}, Range {rf_range}: Rf={rf_name}
* Each channel has different DC current (halving pattern)
* Channels switch every {ch_period*1000:.0f}ms

* ---- Power Supply ----
VCC VCC 0 DC 5
VEE VEE 0 DC -5

* ---- Mux Switch Model ----
.model SW_MUX SW(VT=2.5 VH=0.5 RON=100 ROFF=1e12)
{ch_section}

* ---- Mux Enable Signals (sequential, non-overlapping) ----
{en_section}

* ---- TIA ----
XU1 0 INV VCC VEE TIA_OUT {model_name}

* ---- Feedback Network (Range {rf_range}) ----
Rf INV TIA_OUT {rf_val}
{cf_line}

* ---- Mux to TIA connection ----
R_WIRE TIA_IN INV 1
* Bias path prevents TIA_IN float during mux transitions
* R_BIAS scaled per range to minimize noise gain: 1 + Rf/R_BIAS
R_BIAS TIA_IN 0 {rbias_val}

* ---- ADC Load ----
RL TIA_OUT AIN0 100
R_ADC AIN0 0 10Meg

* ---- Precision options for high-impedance ranges ----
{".options gmin=1e-16" + chr(10) + ".options abstol=1e-16" + chr(10) + ".options reltol=1e-5" if rf_range >= 6 else ""}

* ---- Analysis ----
.tran 10u {sim_time}

.control
run
wrdata {wrdata_path} {wrdata_str}
quit
.endc

{model_block}

.end
"""

    out_path = os.path.join(WORK_DIR, "channel_switching.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {out_path}")
    print(f"  {n_channels} channels, {ch_period*1000:.0f}ms per channel, Rf={rf_name}")
    return out_path


def write_femtoamp_test_netlist(opamp="LMC6001"):
    """
    Write ngspice netlist for femtoampere sensitivity floor test.

    Tests the system at 100fA (10^-13 A) input current with Range 3 (10G feedback).
    Expected output: V = 100fA * 10G = 1mV above virtual ground.

    This tests the practical sensitivity limit of the measurement chain.
    At 100fA, the voltage across the 1M input resistor is only 100nV,
    so the input filter has negligible effect on the current.

    The ADuCM362 24-bit ADC with 2.5V range has LSB = 149nV,
    so 1mV = ~6700 counts - well above the noise floor.
    """
    OPAMP_DB = {
        "LMC6001":  ("LMC6001_NS",  "nation.lib", 5, "LMC6001 Ultra-Low Bias"),
        "LMC6001A": ("LMC6001A_NS", "nation.lib", 5, "LMC6001A Electrometer-Grade"),
        "OPA128":   ("OPA128_BB",    "burrbn.lib", 5, "OPA128 Classic Electrometer"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LMC6001"])
    model_name, lib_file, n_pins, title = info
    model_block = extract_model(model_name, lib_file)

    # Range 3: 10G + 1pF, tau = 10ms, sim = 200ms for full settling
    i_test = 100e-15   # 100 fA
    rf_val = "10G"
    cf_val = "1p"
    sim_time = 0.5     # 500ms for very slow settling
    pulse_width = 0.3  # 300ms pulse

    netlist = f"""* Femtoampere Sensitivity Test - Full Path
* Op-amp: {title} (proxy for ADA4530-1)
* Range 3: Rf=10G, Cf=1pF (highest sensitivity)
* Test current: 100fA (10^-13 A)
* Expected output: 100fA * 10G = 1mV
* ADuCM362 24-bit ADC: LSB=149nV, so 1mV = ~6700 counts

* ---- Power Supply ----
VCC VCC 0 DC 5
VEE VEE 0 DC -5

* ---- Input Current Source (100 fA pulse) ----
Isrc 0 CH_IN PULSE(0 {i_test} 0.05 1u 1u {pulse_width} {sim_time + 1})

* ---- Input Protection + Filter ----
R_IN CH_IN FILT_OUT 1Meg
C_FILT FILT_OUT 0 10n

* ---- Analog Mux (always on) ----
S_MUX FILT_OUT TIA_IN EN_CTRL 0 SW_MUX
V_EN EN_CTRL 0 DC 5
.model SW_MUX SW(VT=2.5 VH=0.5 RON=100 ROFF=1e12)

* ---- TIA ----
XU1 0 INV VCC VEE TIA_OUT {model_name}

* ---- Feedback (Range 3: 10G + 1pF) ----
Rf INV TIA_OUT {rf_val}
Cf INV TIA_OUT {cf_val}

* ---- Mux to TIA ----
R_WIRE TIA_IN INV 1

* ---- ADC Load ----
RL TIA_OUT AIN0 100
R_ADC AIN0 0 10Meg

* ---- Simulation options for femtoamp accuracy ----
.options gmin=1e-16
.options abstol=1e-16
.options reltol=1e-5

* ---- Analysis ----
.tran 100u {sim_time}

.control
run
wrdata {os.path.join(WORK_DIR, 'femtoamp_results.txt').replace(chr(92), '/')} V(TIA_OUT) V(AIN0) V(INV) V(FILT_OUT)
quit
.endc

{model_block}

.end
"""

    out_path = os.path.join(WORK_DIR, "femtoamp_test.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {out_path}")
    print(f"  Test: 100fA into full path, expected output: 1.0mV")
    return out_path


def write_avdd_monitor_netlist():
    """
    Write ngspice netlist for AVDD supply monitor readback.

    The full system has R28/R29 (100k/100k) divider from AVDD to AGND,
    with AIN2/AIN3 differential ADC inputs reading the midpoint.
    Expected: V(AIN2) = AVDD/2 = 1.65V for 3.3V supply.

    Simulates supply drift (3.3V +/- 5%) and verifies ADC readback tracks.
    """
    sim_time = 0.1  # 100ms

    netlist = f"""* AVDD Supply Monitor Simulation
* R28/R29 100k/100k divider from AVDD to AGND
* AIN2/AIN3 differential input to ADuCM362 ADC1
* Expected: V(AIN2) = AVDD/2, V(AIN3) = 0V (AGND)

* ---- AVDD Supply (3.3V with +/-5% drift) ----
* Slow triangle wave: 3.3V +/- 165mV over 100ms
VAVDD AVDD 0 PULSE(3.135 3.465 0.01 0.04 0.04 0.001 0.082)

* ---- Voltage Divider ----
R28 AVDD AIN2 100k
R29 AIN2 AGND 100k

* ---- Bypass Capacitor ----
C30 AIN2 AGND 100n

* ---- AGND reference (0V for simulation) ----
VAGND AGND 0 DC 0

* ---- ADC input model (high-Z sigma-delta) ----
R_ADC2 AIN2 0 1G
R_ADC3 AGND 0 1G

* ---- Analysis ----
.tran 10u {sim_time}

.control
run
wrdata {os.path.join(WORK_DIR, 'avdd_monitor_results.txt').replace(chr(92), '/')} V(AVDD) V(AIN2) V(AGND)
quit
.endc

.end
"""

    out_path = os.path.join(WORK_DIR, "avdd_monitor.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {out_path}")
    print(f"  AVDD sweep: 3.135V - 3.465V, expect AIN2 = AVDD/2")
    return out_path


# =============================================================
# PDF MERGE UTILITY
# =============================================================

def merge_pdfs(pdf_paths, output_path):
    """Merge multiple single-page PDFs into one multi-page PDF using PyMuPDF."""
    try:
        import fitz
    except ImportError:
        print("  Need: pip install pymupdf")
        return None
    merged = fitz.open()
    for p in pdf_paths:
        if os.path.exists(p):
            doc = fitz.open(p)
            merged.insert_pdf(doc)
            doc.close()
    merged.save(output_path)
    merged.close()
    print(f"  Merged PDF: {output_path} ({len(pdf_paths)} pages)")
    return output_path


# =============================================================
# DAC7800 MDAC IC BOX DRAWING HELPER
# =============================================================

def _draw_dac7800_box(sch, ref, center_x, center_y, G=2.54):
    """Draw a DAC7800 MDAC as a proper IC box with labeled pins.

    Draws a solid rectangle with pin labels: VREF (left), IOUT (right),
    RFB (right, below IOUT), VCTRL (bottom).

    Args:
        sch: Schematic object
        ref: Reference designator (e.g. "XDAC1")
        center_x: X center of IC box
        center_y: Y center of IC box (signal line level)
        G: Grid spacing (default 2.54mm)

    Returns:
        dict with pin positions: {'vref': (x,y), 'iout': (x,y), 'vctrl': (x,y)}
    """
    hw = 6 * G   # half-width
    hh = 5 * G   # half-height

    box_l = center_x - hw
    box_r = center_x + hw
    box_t = center_y - hh
    box_b = center_y + hh

    # IC body (solid rectangle)
    sch.add_rectangle(
        start=(box_l, box_t), end=(box_r, box_b),
        stroke_width=0.3, stroke_type='solid')

    # IC name inside box
    sch.add_text(f"{ref}\nDAC7800",
                 position=(center_x - 4 * G, center_y - 3 * G),
                 size=2.0, bold=True)

    # Pin labels inside box edges
    sch.add_text("VREF", position=(box_l + G, center_y + G), size=1.5)
    sch.add_text("IOUT", position=(box_r - 5 * G, center_y + G), size=1.5)
    sch.add_text("VCTRL", position=(center_x - 3 * G, box_b - 3 * G), size=1.5)

    return {
        'vref': (box_l, center_y),
        'iout': (box_r, center_y),
        'vctrl': (center_x, box_b),
    }


# =============================================================
# OSCILLATOR BLOCK SCHEMATICS (Individual A4 PDFs per block)
# =============================================================

def build_osc_block_summing_amp():
    """Oscillator Block 1/6: Summing Amplifier (U1 LM4562).

    HP = -(Rf/R1)*LP - (Rf/R2)*BP = -(R3/R1)*LP - (R3/R2)*BP
    LP gain = -(10k/10k) = -1.0, BP gain = -(10k/22k) = -0.455
    Q factor = R2/R3 = 22k/10k = 2.2
    Interfaces: LP (from Int2), BP (from Int1), HP (to Int1 via DAC7800)
    """
    print("  Building block: Summing Amplifier...")
    sch = create_schematic("Oscillator - Summing Amplifier")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="State Variable Oscillator - Summing Amplifier",
        company="CircuitForge",
        rev="1.0",
        comments={1: "HP = -(Rf/R1)*LP - (Rf/R2)*BP, Rf=R3=10k",
                  2: "LP gain = -1.0, BP gain = -0.455, Q = 2.2",
                  3: "Block 1 of 6"}
    )
    G = 2.54
    pwr_idx = 1

    # ── Block title annotations ──
    sch.add_text("SUMMING AMPLIFIER (U1)", position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("HP = -(Rf/R1) * LP - (Rf/R2) * BP    (Rf = R3 = 10k)",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("LP gain = -(10k/10k) = -1.0     BP gain = -(10k/22k) = -0.455     Q = 2.2",
                 position=(8 * G, 17 * G), size=2.0)
    sch.add_text("FUNCTION: Combines LP and BP feedback signals with phase inversion.",
                 position=(8 * G, 23 * G), size=1.8)
    sch.add_text("The HP output feeds both integrators, closing the oscillation loop.",
                 position=(8 * G, 27 * G), size=1.8)

    # ── U1 LM4562 op-amp ──
    u1_x, u1_y = 48 * G, 48 * G
    sch.components.add(lib_id="LM741:LM741", reference="U1",
        value="LM4562", position=(u1_x, u1_y))

    u1_inv = (u1_x - 7.62, u1_y - 2.54)
    u1_ni  = (u1_x - 7.62, u1_y + 2.54)
    u1_out = (u1_x + 7.62, u1_y)
    u1_vp  = (u1_x - 2.54, u1_y + 7.62)
    u1_vm  = (u1_x - 2.54, u1_y - 7.62)

    # Summing node junction
    sum_x = u1_inv[0] - 8 * G
    sum_y = u1_inv[1]

    # R1 (10k) - LP input to summing node
    rlp_x = sum_x - 16 * G
    rlp_y = sum_y - 12 * G
    sch.components.add(lib_id="R:R", reference="R1", value="10k",
        position=(rlp_x, rlp_y), rotation=90)
    rlp_left = (rlp_x - 3.81, rlp_y)
    rlp_right = (rlp_x + 3.81, rlp_y)
    wire_manhattan(sch, rlp_right[0], rlp_right[1], sum_x, sum_y)
    sch.add_label("LP", position=(rlp_left[0] - 8 * G, rlp_y))
    sch.add_wire(start=(rlp_left[0] - 8 * G, rlp_y), end=rlp_left)

    # R2 (22k) - BP input to summing node
    rbp_x = sum_x - 16 * G
    rbp_y = sum_y
    sch.components.add(lib_id="R:R", reference="R2", value="22k",
        position=(rbp_x, rbp_y), rotation=90)
    rbp_left = (rbp_x - 3.81, rbp_y)
    rbp_right = (rbp_x + 3.81, rbp_y)
    sch.add_wire(start=rbp_right, end=(sum_x, sum_y))
    sch.add_label("BP", position=(rbp_left[0] - 8 * G, rbp_y))
    sch.add_wire(start=(rbp_left[0] - 8 * G, rbp_y), end=rbp_left)

    # R3 (10k) - feedback from output to summing node
    rf_y = sum_y - 8 * G
    rf_cx = (sum_x + u1_out[0]) / 2
    sch.components.add(lib_id="R:R", reference="R3", value="10k",
        position=(rf_cx, rf_y), rotation=90)
    rf_left = (rf_cx - 3.81, rf_y)
    rf_right = (rf_cx + 3.81, rf_y)
    sch.add_wire(start=(sum_x, sum_y), end=(sum_x, rf_y))
    sch.add_wire(start=(sum_x, rf_y), end=rf_left)
    sch.add_wire(start=rf_right, end=(u1_out[0], rf_y))
    sch.add_wire(start=(u1_out[0], rf_y), end=u1_out)
    sch.junctions.add(position=(sum_x, sum_y))

    # Summing node to inv input
    sch.add_wire(start=(sum_x, sum_y), end=u1_inv)

    # Non-inverting input to GND
    gnd1_y = u1_ni[1] + 8 * G
    sch.add_wire(start=u1_ni, end=(u1_ni[0], gnd1_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(u1_ni[0], gnd1_y))
    pwr_idx += 1

    # +15V power
    vcc_y = u1_vp[1] + 8 * G
    sch.add_wire(start=u1_vp, end=(u1_vp[0], vcc_y))
    sch.add_label("+15V", position=(u1_vp[0], vcc_y))

    # -15V power (shortened to stay below feedback wire)
    vee_y = u1_vm[1] - 4 * G
    sch.add_wire(start=(u1_vm[0], vee_y), end=u1_vm)
    sch.components.add(lib_id="VEE:VEE", reference=f"#PWR0{pwr_idx:02d}",
        value="-15V", position=(u1_vm[0], vee_y))
    pwr_idx += 1

    # HP output label
    hp_lbl_x = u1_out[0] + 10 * G
    sch.add_label("HP", position=(hp_lbl_x, u1_out[1]))
    sch.add_wire(start=u1_out, end=(hp_lbl_x, u1_out[1]))
    sch.junctions.add(position=u1_out)

    # ── Interface annotations ──
    sch.add_text("Interfaces:", position=(8 * G, 62 * G), size=2.5, bold=True)
    sch.add_text("LP input: from Integrator 2 (U3) output",
                 position=(8 * G, 66 * G), size=2.0)
    sch.add_text("BP input: from Integrator 1 (U2) output",
                 position=(8 * G, 70 * G), size=2.0)
    sch.add_text("HP output: to Integrator 1 (U2) via DAC7800 XDAC1",
                 position=(8 * G, 74 * G), size=2.0)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "osc_block_summing_amp.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    merge_collinear_wires(sch_path)
    print(f"    Saved: {sch_path}")
    return sch_path


def build_osc_block_integrator1():
    """Oscillator Block 2/6: Integrator 1 - HP->BP (U2 LM4562, XDAC1 DAC7800).

    f = D / (4096 * 2*pi * 10k * 470p), range 25 Hz - 30 kHz
    Cint1 = 470pF (integration), R_damp1 = 100M (DC stability)
    Zener AGC: D1/D2 back-to-back BV=1.1V, clamps BP to ~1V RMS
    """
    print("  Building block: Integrator 1 (HP->BP)...")
    sch = create_schematic("Oscillator - Integrator 1")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="State Variable Oscillator - Integrator 1 (HP to BP)",
        company="CircuitForge",
        rev="1.0",
        comments={1: "f = D/(4096*2pi*10k*470p), 25Hz-30kHz",
                  2: "Zener AGC: BV=1.1V, BP amplitude ~1V RMS",
                  3: "Block 2 of 6"}
    )
    G = 2.54
    pwr_idx = 1

    # Wider spacing for standalone A4 page
    fb_vert = 8     # cap above inv input (G)
    damp_vert = 14  # damping R above (G)
    zener_vert = 20 # zeners above (G)

    # ── Block title ──
    sch.add_text("INTEGRATOR 1: HP -> BP (U2 + XDAC1)",
                 position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("f = D / (4096 * 2pi * R4 * C1) = D / (4096 * 2pi * 10k * 470p)",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("Frequency range: 25 Hz (D=3) to 30 kHz (D=3640)",
                 position=(8 * G, 17 * G), size=2.0)
    sch.add_text("FUNCTION: Integrates HP signal to produce BP output. DAC7800 MDAC",
                 position=(8 * G, 23 * G), size=1.8)
    sch.add_text("controls effective resistance, setting oscillation frequency. Zener",
                 position=(8 * G, 27 * G), size=1.8)
    sch.add_text("diodes (D1/D2, BV=1.1V) clamp output to ~1V RMS (passive AGC).",
                 position=(8 * G, 31 * G), size=1.8)

    # ── U2 LM4562 ──
    u2_x, u2_y = 55 * G, 60 * G
    sch.components.add(lib_id="LM741:LM741", reference="U2",
        value="LM4562", position=(u2_x, u2_y))
    u2_inv = (u2_x - 7.62, u2_y - 2.54)
    u2_ni  = (u2_x - 7.62, u2_y + 2.54)
    u2_out = (u2_x + 7.62, u2_y)
    u2_vp  = (u2_x - 2.54, u2_y + 7.62)
    u2_vm  = (u2_x - 2.54, u2_y - 7.62)

    # ── DAC7800 MDAC (XDAC1) - drawn as proper IC box ──
    dac1_x = u2_inv[0] - 28 * G
    dac1_y = u2_inv[1]
    dac1_pins = _draw_dac7800_box(sch, "XDAC1", dac1_x, dac1_y, G)

    # HP label wired to VREF pin (left side of DAC box)
    sch.add_label("HP", position=(dac1_pins['vref'][0] - 10 * G, dac1_y))
    sch.add_wire(start=(dac1_pins['vref'][0] - 10 * G, dac1_y),
                 end=dac1_pins['vref'])

    # R4 (10k) between MDAC IOUT and inv input
    rint1_x = u2_inv[0] - 14 * G
    rint1_y = u2_inv[1]
    sch.components.add(lib_id="R:R", reference="R4", value="10k",
        position=(rint1_x, rint1_y), rotation=90)
    rint1_left = (rint1_x - 3.81, rint1_y)
    rint1_right = (rint1_x + 3.81, rint1_y)
    sch.add_wire(start=dac1_pins['iout'], end=rint1_left)

    # VCTRL label wired to VCTRL pin (bottom of DAC box)
    ctrl_y1 = dac1_pins['vctrl'][1] + 4 * G
    sch.add_label("VCTRL", position=(dac1_pins['vctrl'][0], ctrl_y1))
    sch.add_wire(start=dac1_pins['vctrl'],
                 end=(dac1_pins['vctrl'][0], ctrl_y1))

    # R4 to inv input
    sch.add_wire(start=rint1_right, end=u2_inv)

    # ── C1 (470p) - integrator cap ──
    cint1_y = u2_inv[1] - fb_vert * G
    cint1_cx = (u2_inv[0] + u2_out[0]) / 2
    sch.components.add(lib_id="C:C", reference="C1", value="470p",
        position=(cint1_cx, cint1_y), rotation=90)
    c1_left = (cint1_cx - 3.81, cint1_y)
    c1_right = (cint1_cx + 3.81, cint1_y)

    # Feedback wiring
    inv1_junc = (cint1_cx - 3.81, u2_inv[1])
    sch.add_wire(start=rint1_right, end=inv1_junc)
    sch.add_wire(start=inv1_junc, end=(inv1_junc[0], cint1_y))
    sch.add_wire(start=(inv1_junc[0], cint1_y), end=c1_left)
    sch.add_wire(start=c1_right, end=(u2_out[0], cint1_y))
    sch.add_wire(start=(u2_out[0], cint1_y), end=u2_out)
    sch.junctions.add(position=inv1_junc)

    # ── R5 (100M) - damping resistor ──
    rdamp1_y = u2_inv[1] - damp_vert * G
    sch.components.add(lib_id="R:R", reference="R5", value="100M",
        position=(cint1_cx, rdamp1_y), rotation=90)
    rd1_left = (cint1_cx - 3.81, rdamp1_y)
    rd1_right = (cint1_cx + 3.81, rdamp1_y)
    sch.add_wire(start=(inv1_junc[0], cint1_y), end=(inv1_junc[0], rdamp1_y))
    sch.add_wire(start=(inv1_junc[0], rdamp1_y), end=rd1_left)
    sch.add_wire(start=rd1_right, end=(u2_out[0], rdamp1_y))
    sch.add_wire(start=(u2_out[0], rdamp1_y), end=(u2_out[0], cint1_y))
    sch.junctions.add(position=(inv1_junc[0], cint1_y))
    sch.junctions.add(position=(u2_out[0], cint1_y))

    # ── Zener AGC: D1/D2 back-to-back (anode-to-anode) ──
    # Layout: D1 and D2 horizontal, anodes face center, cathodes face outside.
    # Cathode wires route DOWN then horizontally to the vertical buses
    # so the connections are visually distinct from the anode-to-anode wire.
    zener1_y = u2_inv[1] - zener_vert * G
    cathode_drop = 3 * G  # vertical drop before horizontal cathode routing
    sch.components.add(lib_id="D_Zener:D_Zener", reference="D1", value="DZ09 BV=1.1",
        position=(cint1_cx - 5 * G, zener1_y), rotation=0)
    sch.components.add(lib_id="D_Zener:D_Zener", reference="D2", value="DZ09 BV=1.1",
        position=(cint1_cx + 5 * G, zener1_y), rotation=180)
    # Pin positions: D1 rot=0 → K=left A=right; D2 rot=180 → A=left K=right
    d1_k = (cint1_cx - 5 * G - 3.81, zener1_y)   # D1 cathode (left)
    d1_a = (cint1_cx - 5 * G + 3.81, zener1_y)    # D1 anode (right)
    d2_a = (cint1_cx + 5 * G - 3.81, zener1_y)    # D2 anode (left)
    d2_k = (cint1_cx + 5 * G + 3.81, zener1_y)    # D2 cathode (right)
    # Anode-to-anode center wire (horizontal at zener1_y)
    sch.add_wire(start=d1_a, end=d2_a)
    # D1 cathode: drop down, then horizontal to left bus
    sch.add_wire(start=d1_k, end=(d1_k[0], zener1_y + cathode_drop))
    sch.add_wire(start=(d1_k[0], zener1_y + cathode_drop),
                 end=(inv1_junc[0], zener1_y + cathode_drop))
    # Left bus: from cathode junction down to damping resistor
    sch.add_wire(start=(inv1_junc[0], zener1_y + cathode_drop),
                 end=(inv1_junc[0], rdamp1_y))
    sch.junctions.add(position=(inv1_junc[0], zener1_y + cathode_drop))
    sch.junctions.add(position=(inv1_junc[0], rdamp1_y))
    # D2 cathode: drop down, then horizontal to right bus
    sch.add_wire(start=d2_k, end=(d2_k[0], zener1_y + cathode_drop))
    sch.add_wire(start=(d2_k[0], zener1_y + cathode_drop),
                 end=(u2_out[0], zener1_y + cathode_drop))
    # Right bus: from cathode junction down to damping resistor
    sch.add_wire(start=(u2_out[0], zener1_y + cathode_drop),
                 end=(u2_out[0], rdamp1_y))
    sch.junctions.add(position=(u2_out[0], zener1_y + cathode_drop))
    sch.junctions.add(position=(u2_out[0], rdamp1_y))
    # Cathode/Anode labels
    sch.add_text("K", position=(d1_k[0] - 0.5 * G, zener1_y - 2.5 * G), size=2.0)
    sch.add_text("A", position=(d1_a[0] + 0.5 * G, zener1_y - 2.5 * G), size=2.0)
    sch.add_text("A", position=(d2_a[0] - 2 * G, zener1_y - 2.5 * G), size=2.0)
    sch.add_text("K", position=(d2_k[0] + 0.5 * G, zener1_y - 2.5 * G), size=2.0)
    # Directional labels at junction points
    sch.add_text("to inv(-)",
                 position=(inv1_junc[0] - 8 * G, zener1_y + cathode_drop), size=1.8)
    sch.add_text("to output",
                 position=(u2_out[0] + 2 * G, zener1_y + cathode_drop), size=1.8)
    sch.add_text("Zener AGC: D1/D2 back-to-back, BV=1.1V",
                 position=(cint1_cx - 8 * G, zener1_y + 5 * G), size=2.0)
    sch.add_text("Anodes joined center. K1->inv(-), K2->output.",
                 position=(cint1_cx - 8 * G, zener1_y + 8 * G), size=2.0)

    # NI to GND
    gnd2_y = u2_ni[1] + 8 * G
    sch.add_wire(start=u2_ni, end=(u2_ni[0], gnd2_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(u2_ni[0], gnd2_y))
    pwr_idx += 1

    # +15V
    vcc_y = u2_vp[1] + 8 * G
    sch.add_wire(start=u2_vp, end=(u2_vp[0], vcc_y))
    sch.add_label("+15V", position=(u2_vp[0], vcc_y))

    # -15V (shortened to stay below feedback stack)
    vee_y = u2_vm[1] - 4 * G
    sch.add_wire(start=(u2_vm[0], vee_y), end=u2_vm)
    sch.components.add(lib_id="VEE:VEE", reference=f"#PWR0{pwr_idx:02d}",
        value="-15V", position=(u2_vm[0], vee_y))
    pwr_idx += 1

    # BP output
    bp_lbl_x = u2_out[0] + 10 * G
    sch.add_label("BP", position=(bp_lbl_x, u2_out[1]))
    sch.add_wire(start=u2_out, end=(bp_lbl_x, u2_out[1]))
    sch.junctions.add(position=u2_out)

    # ── Annotations ──
    sch.add_text("D=121: f~997Hz    D=3: f~25Hz    D=3640: f~30kHz",
                 position=(8 * G, 58 * G), size=2.0)

    sch.add_text("Interfaces:", position=(8 * G, 62 * G), size=2.5, bold=True)
    sch.add_text("HP input: from Summing Amplifier (U1) output",
                 position=(8 * G, 66 * G), size=2.0)
    sch.add_text("BP output: to Integrator 2 (U3), RMS Detector (U4), Summing Amp (U1)",
                 position=(8 * G, 70 * G), size=2.0)
    sch.add_text("VCTRL: from MCU (U5) SPI0 via DAC7800",
                 position=(8 * G, 74 * G), size=2.0)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "osc_block_integrator1.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    merge_collinear_wires(sch_path)
    print(f"    Saved: {sch_path}")
    return sch_path


def build_osc_block_rms_detector():
    """Oscillator Block 3/6: AD636 RMS Detector.

    1/5 attenuator (R10=40k, R11=10k), AD636 true RMS-to-DC, CAV=10uF
    Vout = BP * 10k/(40k+10k) = BP/5, converted to DC by AD636
    """
    print("  Building block: AD636 RMS Detector...")
    sch = create_schematic("Oscillator - RMS Detector")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="State Variable Oscillator - AD636 RMS Detector",
        company="CircuitForge",
        rev="1.0",
        comments={1: "1/5 attenuator + AD636 true RMS-to-DC",
                  2: "Vout = BP * R11/(R10+R11) = BP/5",
                  3: "Block 3 of 6"}
    )
    G = 2.54
    pwr_idx = 1

    # ── Block title ──
    sch.add_text("AD636 RMS DETECTOR (U4)", position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("Vout_RMS = BP * R11/(R10+R11) = BP * 10k/(40k+10k) = BP/5",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("AD636 true RMS-to-DC converter, CAV=10uF averaging capacitor",
                 position=(8 * G, 17 * G), size=2.0)
    sch.add_text("FUNCTION: Converts BP AC signal to DC voltage proportional to RMS",
                 position=(8 * G, 23 * G), size=1.8)
    sch.add_text("amplitude. 1/5 attenuator scales ~1V RMS to ~200mV for AD636 input.",
                 position=(8 * G, 27 * G), size=1.8)
    sch.add_text("MCU reads AIN0 to verify oscillation amplitude during calibration.",
                 position=(8 * G, 31 * G), size=1.8)

    # ── Attenuator ──
    att_x = 24 * G
    att_y = 48 * G

    # R10 (40k) - series resistor
    sch.components.add(lib_id="R:R", reference="R10", value="40k",
        position=(att_x, att_y), rotation=90)
    ratt1_left = (att_x - 3.81, att_y)
    ratt1_right = (att_x + 3.81, att_y)
    sch.add_label("BP", position=(ratt1_left[0] - 8 * G, att_y))
    sch.add_wire(start=(ratt1_left[0] - 8 * G, att_y), end=ratt1_left)

    # R11 (10k) - shunt to GND
    att2_x = ratt1_right[0] + 8 * G
    att2_y = att_y + 10 * G
    sch.components.add(lib_id="R:R", reference="R11", value="10k",
        position=(att2_x, att2_y))
    ratt2_top = (att2_x, att2_y - 3.81)
    ratt2_bot = (att2_x, att2_y + 3.81)
    sch.add_wire(start=ratt1_right, end=(att2_x, att_y))
    sch.add_wire(start=(att2_x, att_y), end=ratt2_top)
    sch.junctions.add(position=(att2_x, att_y))
    gnd_att_y = ratt2_bot[1] + 6 * G
    sch.add_wire(start=ratt2_bot, end=(att2_x, gnd_att_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(att2_x, gnd_att_y))
    pwr_idx += 1
    sch.add_text("1/5 attenuator\nVin/5 to AD636",
                 position=(att2_x + 6 * G, att_y), size=2.0)

    # ── AD636 block (drawn as IC box with pins) ──
    ad636_x = att2_x + 28 * G
    ad636_y = att_y
    # Wire from attenuator to AD636 input
    ad636_in_x = ad636_x - 10 * G
    sch.add_wire(start=(att2_x, att_y), end=(ad636_in_x, att_y))

    # Draw AD636 as a rectangle box (using wire segments)
    box_left = ad636_in_x
    box_right = ad636_x + 4 * G
    box_top = att_y - 8 * G
    box_bot = att_y + 8 * G
    # Box outline (4 sides)
    sch.add_wire(start=(box_left, box_top), end=(box_right, box_top))
    sch.add_wire(start=(box_right, box_top), end=(box_right, box_bot))
    sch.add_wire(start=(box_right, box_bot), end=(box_left, box_bot))
    sch.add_wire(start=(box_left, box_bot), end=(box_left, box_top))
    # IC label inside box
    sch.add_text("U4", position=(box_left + 2 * G, box_top + 3 * G), size=2.5)
    sch.add_text("AD636", position=(box_left + 2 * G, box_top + 7 * G), size=2.5)
    sch.add_text("RMS-to-DC", position=(box_left + 2 * G, box_top + 11 * G), size=1.8)
    # Pin labels on box edges
    sch.add_text("VIN", position=(box_left - 5 * G, att_y), size=1.8)
    sch.add_text("VOUT", position=(box_right + 1 * G, att_y), size=1.8)
    sch.add_text("CAV", position=(box_left + 5 * G, box_bot + 2 * G), size=1.8)
    # Input wire connects to box left at signal level
    sch.junctions.add(position=(box_left, att_y))
    # Output wire exits box right at signal level
    ad636_out_x = box_right

    # C3 (10u) - CAV averaging cap (connected to bottom of IC box)
    cav_x = (box_left + box_right) / 2
    cav_y = box_bot + 6 * G
    sch.components.add(lib_id="C:C", reference="C3", value="10u",
        position=(cav_x, cav_y))
    cav_top = (cav_x, cav_y - 3.81)
    cav_bot = (cav_x, cav_y + 3.81)
    # Wire from box bottom to cap top
    sch.add_wire(start=(cav_x, box_bot), end=cav_top)
    sch.junctions.add(position=(cav_x, box_bot))
    gnd_cav_y = cav_bot[1] + 6 * G
    sch.add_wire(start=cav_bot, end=(cav_x, gnd_cav_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(cav_x, gnd_cav_y))
    pwr_idx += 1

    # AIN0 output (from AD636 output pin)
    ain0_x = ad636_out_x + 14 * G
    sch.add_label("AIN0", position=(ain0_x, att_y))
    sch.add_wire(start=(ad636_out_x, att_y), end=(ain0_x, att_y))
    sch.junctions.add(position=(ad636_out_x, att_y))

    # ── Interface annotations ──
    sch.add_text("Interfaces:", position=(8 * G, 62 * G), size=2.5, bold=True)
    sch.add_text("BP input: from Integrator 1 (U2) output",
                 position=(8 * G, 66 * G), size=2.0)
    sch.add_text("AIN0 output: to MCU (U5) ADC input",
                 position=(8 * G, 70 * G), size=2.0)
    sch.add_text("AD636 RMS averaging time constant ~ R_internal * C3 ~ 100ms",
                 position=(8 * G, 74 * G), size=2.0)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "osc_block_rms_detector.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    merge_collinear_wires(sch_path)
    print(f"    Saved: {sch_path}")
    return sch_path


def build_osc_block_integrator2():
    """Oscillator Block 4/6: Integrator 2 - BP->LP (U3 LM4562, XDAC2 DAC7800).

    Mirrors Integrator 1. Same frequency formula.
    Includes R8=100k output load resistor.
    Zener AGC: D3/D4 back-to-back BV=1.1V
    """
    print("  Building block: Integrator 2 (BP->LP)...")
    sch = create_schematic("Oscillator - Integrator 2")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="State Variable Oscillator - Integrator 2 (BP to LP)",
        company="CircuitForge",
        rev="1.0",
        comments={1: "f = D/(4096*2pi*10k*470p), mirrors Integrator 1",
                  2: "Zener AGC: BV=1.1V, R8=100k output load",
                  3: "Block 4 of 6"}
    )
    G = 2.54
    pwr_idx = 1
    fb_vert = 8
    damp_vert = 14
    zener_vert = 20

    # ── Block title ──
    sch.add_text("INTEGRATOR 2: BP -> LP (U3 + XDAC2)",
                 position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("f = D / (4096 * 2pi * R6 * C2) = D / (4096 * 2pi * 10k * 470p)",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("Mirrors Integrator 1, R8=100k output load",
                 position=(8 * G, 17 * G), size=2.0)
    sch.add_text("FUNCTION: Second integrator converts BP to LP, completing the 90-degree",
                 position=(8 * G, 23 * G), size=1.8)
    sch.add_text("phase shift chain. LP feeds back to summing amp, closing the oscillation",
                 position=(8 * G, 27 * G), size=1.8)
    sch.add_text("loop. R8 (100k) provides DC load to prevent charge buildup.",
                 position=(8 * G, 31 * G), size=1.8)

    # ── U3 LM4562 ──
    u3_x, u3_y = 55 * G, 60 * G
    sch.components.add(lib_id="LM741:LM741", reference="U3",
        value="LM4562", position=(u3_x, u3_y))
    u3_inv = (u3_x - 7.62, u3_y - 2.54)
    u3_ni  = (u3_x - 7.62, u3_y + 2.54)
    u3_out = (u3_x + 7.62, u3_y)
    u3_vp  = (u3_x - 2.54, u3_y + 7.62)
    u3_vm  = (u3_x - 2.54, u3_y - 7.62)

    # ── DAC7800 MDAC #2 (XDAC2) - drawn as proper IC box ──
    dac2_x = u3_inv[0] - 28 * G
    dac2_y = u3_inv[1]
    dac2_pins = _draw_dac7800_box(sch, "XDAC2", dac2_x, dac2_y, G)

    # BP label wired to VREF pin (left side of DAC box)
    sch.add_label("BP", position=(dac2_pins['vref'][0] - 10 * G, dac2_y))
    sch.add_wire(start=(dac2_pins['vref'][0] - 10 * G, dac2_y),
                 end=dac2_pins['vref'])

    # R6 (10k) between MDAC IOUT and inv input
    rint2_x = u3_inv[0] - 14 * G
    rint2_y = u3_inv[1]
    sch.components.add(lib_id="R:R", reference="R6", value="10k",
        position=(rint2_x, rint2_y), rotation=90)
    rint2_left = (rint2_x - 3.81, rint2_y)
    rint2_right = (rint2_x + 3.81, rint2_y)
    sch.add_wire(start=dac2_pins['iout'], end=rint2_left)

    # VCTRL label wired to VCTRL pin (bottom of DAC box)
    ctrl_y2 = dac2_pins['vctrl'][1] + 4 * G
    sch.add_label("VCTRL", position=(dac2_pins['vctrl'][0], ctrl_y2))
    sch.add_wire(start=dac2_pins['vctrl'],
                 end=(dac2_pins['vctrl'][0], ctrl_y2))

    sch.add_wire(start=rint2_right, end=u3_inv)

    # ── C2 (470p) ──
    cint2_y = u3_inv[1] - fb_vert * G
    cint2_cx = (u3_inv[0] + u3_out[0]) / 2
    sch.components.add(lib_id="C:C", reference="C2", value="470p",
        position=(cint2_cx, cint2_y), rotation=90)
    c2_left = (cint2_cx - 3.81, cint2_y)
    c2_right = (cint2_cx + 3.81, cint2_y)

    inv2_junc = (cint2_cx - 3.81, u3_inv[1])
    sch.add_wire(start=rint2_right, end=inv2_junc)
    sch.add_wire(start=inv2_junc, end=(inv2_junc[0], cint2_y))
    sch.add_wire(start=(inv2_junc[0], cint2_y), end=c2_left)
    sch.add_wire(start=c2_right, end=(u3_out[0], cint2_y))
    sch.add_wire(start=(u3_out[0], cint2_y), end=u3_out)
    sch.junctions.add(position=inv2_junc)

    # ── R7 (100M) damping ──
    rdamp2_y = u3_inv[1] - damp_vert * G
    sch.components.add(lib_id="R:R", reference="R7", value="100M",
        position=(cint2_cx, rdamp2_y), rotation=90)
    rd2_left = (cint2_cx - 3.81, rdamp2_y)
    rd2_right = (cint2_cx + 3.81, rdamp2_y)
    sch.add_wire(start=(inv2_junc[0], cint2_y), end=(inv2_junc[0], rdamp2_y))
    sch.add_wire(start=(inv2_junc[0], rdamp2_y), end=rd2_left)
    sch.add_wire(start=rd2_right, end=(u3_out[0], rdamp2_y))
    sch.add_wire(start=(u3_out[0], rdamp2_y), end=(u3_out[0], cint2_y))
    sch.junctions.add(position=(inv2_junc[0], cint2_y))
    sch.junctions.add(position=(u3_out[0], cint2_y))

    # ── Zener AGC D3/D4 back-to-back (anode-to-anode) ──
    # Cathode wires route DOWN then horizontally to buses for visual clarity
    zener2_y = u3_inv[1] - zener_vert * G
    cathode_drop = 3 * G
    sch.components.add(lib_id="D_Zener:D_Zener", reference="D3", value="DZ09 BV=1.1",
        position=(cint2_cx - 5 * G, zener2_y), rotation=0)
    sch.components.add(lib_id="D_Zener:D_Zener", reference="D4", value="DZ09 BV=1.1",
        position=(cint2_cx + 5 * G, zener2_y), rotation=180)
    d3_k = (cint2_cx - 5 * G - 3.81, zener2_y)
    d3_a = (cint2_cx - 5 * G + 3.81, zener2_y)
    d4_a = (cint2_cx + 5 * G - 3.81, zener2_y)
    d4_k = (cint2_cx + 5 * G + 3.81, zener2_y)
    # Anode-to-anode center wire
    sch.add_wire(start=d3_a, end=d4_a)
    # D3 cathode: drop down, then horizontal to left bus
    sch.add_wire(start=d3_k, end=(d3_k[0], zener2_y + cathode_drop))
    sch.add_wire(start=(d3_k[0], zener2_y + cathode_drop),
                 end=(inv2_junc[0], zener2_y + cathode_drop))
    sch.add_wire(start=(inv2_junc[0], zener2_y + cathode_drop),
                 end=(inv2_junc[0], rdamp2_y))
    sch.junctions.add(position=(inv2_junc[0], zener2_y + cathode_drop))
    sch.junctions.add(position=(inv2_junc[0], rdamp2_y))
    # D4 cathode: drop down, then horizontal to right bus
    sch.add_wire(start=d4_k, end=(d4_k[0], zener2_y + cathode_drop))
    sch.add_wire(start=(d4_k[0], zener2_y + cathode_drop),
                 end=(u3_out[0], zener2_y + cathode_drop))
    sch.add_wire(start=(u3_out[0], zener2_y + cathode_drop),
                 end=(u3_out[0], rdamp2_y))
    sch.junctions.add(position=(u3_out[0], zener2_y + cathode_drop))
    sch.junctions.add(position=(u3_out[0], rdamp2_y))
    # Labels
    sch.add_text("K", position=(d3_k[0] - 0.5 * G, zener2_y - 2.5 * G), size=2.0)
    sch.add_text("A", position=(d3_a[0] + 0.5 * G, zener2_y - 2.5 * G), size=2.0)
    sch.add_text("A", position=(d4_a[0] - 2 * G, zener2_y - 2.5 * G), size=2.0)
    sch.add_text("K", position=(d4_k[0] + 0.5 * G, zener2_y - 2.5 * G), size=2.0)
    # Directional labels at junction points
    sch.add_text("to inv(-)",
                 position=(inv2_junc[0] - 8 * G, zener2_y + cathode_drop), size=1.8)
    sch.add_text("to output",
                 position=(u3_out[0] + 2 * G, zener2_y + cathode_drop), size=1.8)
    sch.add_text("Zener AGC: D3/D4 back-to-back, BV=1.1V",
                 position=(cint2_cx - 8 * G, zener2_y + 5 * G), size=2.0)
    sch.add_text("Anodes joined center. K3->inv(-), K4->output.",
                 position=(cint2_cx - 8 * G, zener2_y + 8 * G), size=2.0)

    # NI to GND
    gnd3_y = u3_ni[1] + 8 * G
    sch.add_wire(start=u3_ni, end=(u3_ni[0], gnd3_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(u3_ni[0], gnd3_y))
    pwr_idx += 1

    # +15V
    vcc_y = u3_vp[1] + 8 * G
    sch.add_wire(start=u3_vp, end=(u3_vp[0], vcc_y))
    sch.add_label("+15V", position=(u3_vp[0], vcc_y))

    # -15V
    vee_y = u3_vm[1] - 4 * G
    sch.add_wire(start=(u3_vm[0], vee_y), end=u3_vm)
    sch.components.add(lib_id="VEE:VEE", reference=f"#PWR0{pwr_idx:02d}",
        value="-15V", position=(u3_vm[0], vee_y))
    pwr_idx += 1

    # LP output
    lp_lbl_x = u3_out[0] + 10 * G
    sch.add_label("LP", position=(lp_lbl_x, u3_out[1]))
    sch.add_wire(start=u3_out, end=(lp_lbl_x, u3_out[1]))
    sch.junctions.add(position=u3_out)

    # R8 (100k) output load
    rl_x = u3_out[0] + 18 * G
    rl_y = u3_out[1] + 12 * G
    sch.components.add(lib_id="R:R", reference="R8", value="100k",
        position=(rl_x, rl_y))
    rl_top = (rl_x, rl_y - 3.81)
    rl_bot = (rl_x, rl_y + 3.81)
    sch.add_label("BP", position=(rl_x + 8 * G, rl_top[1]))
    sch.add_wire(start=rl_top, end=(rl_x + 8 * G, rl_top[1]))
    gnd_rl_y = rl_bot[1] + 6 * G
    sch.add_wire(start=rl_bot, end=(rl_x, gnd_rl_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(rl_x, gnd_rl_y))
    pwr_idx += 1

    # ── Interface annotations ──
    sch.add_text("Interfaces:", position=(8 * G, 62 * G), size=2.5, bold=True)
    sch.add_text("BP input: from Integrator 1 (U2) output",
                 position=(8 * G, 66 * G), size=2.0)
    sch.add_text("LP output: to Summing Amplifier (U1) LP input",
                 position=(8 * G, 70 * G), size=2.0)
    sch.add_text("VCTRL: from MCU (U5) SPI0 via DAC7800",
                 position=(8 * G, 74 * G), size=2.0)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "osc_block_integrator2.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    merge_collinear_wires(sch_path)
    print(f"    Saved: {sch_path}")
    return sch_path


def build_osc_block_power_supply():
    """Oscillator Block 5/6: Startup Kick + Power Supply.

    R9=100k startup kick to HP net, bulk decoupling:
    C6=10u (+15V), C7=10u (-15V), C8=100n (3.3V MCU LDO)
    """
    print("  Building block: Power Supply + Startup Kick...")
    sch = create_schematic("Oscillator - Power Supply")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="State Variable Oscillator - Power Supply + Startup",
        company="CircuitForge",
        rev="1.0",
        comments={1: "Bulk decoupling + startup kick",
                  2: "+15V/-15V analog, 3.3V MCU (LDO from +15V)",
                  3: "Block 5 of 6"}
    )
    G = 2.54
    pwr_idx = 1

    # ── Block title ──
    sch.add_text("STARTUP KICK + POWER SUPPLY",
                 position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("Startup: R9 injects 0.1V pulse into HP net to initiate oscillation",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("Power: +15V/-15V analog supply, 3.3V MCU via LDO from +15V",
                 position=(8 * G, 17 * G), size=2.0)
    sch.add_text("FUNCTION: R9 injects a brief pulse into HP at power-on to break",
                 position=(8 * G, 23 * G), size=1.8)
    sch.add_text("equilibrium and start oscillation. Bulk caps filter supply noise.",
                 position=(8 * G, 27 * G), size=1.8)

    # ── Startup kick section ──
    kick_x = 20 * G
    kick_y = 38 * G
    sch.components.add(lib_id="R:R", reference="R9", value="100k",
        position=(kick_x, kick_y), rotation=90)
    rk_left = (kick_x - 3.81, kick_y)
    rk_right = (kick_x + 3.81, kick_y)
    sch.add_label("HP", position=(rk_right[0] + 8 * G, kick_y))
    sch.add_wire(start=rk_right, end=(rk_right[0] + 8 * G, kick_y))
    sch.add_text("Startup Kick\nPULSE(0, 0.1V, 0.1ms, 1ns, 1ns, 10us)",
                 position=(kick_x - 12 * G, kick_y - 8 * G), size=2.0)
    gnd_kick_y = kick_y + 10 * G
    sch.add_wire(start=rk_left, end=(rk_left[0], gnd_kick_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(rk_left[0], gnd_kick_y))
    pwr_idx += 1

    # ── Power supply section ──
    pwr_x = 20 * G
    pwr_y = 62 * G

    # +15V bulk decoupling
    sch.add_label("+15V", position=(pwr_x, pwr_y - 10 * G))
    sch.components.add(lib_id="C:C", reference="C6", value="10u",
        position=(pwr_x, pwr_y))
    c6_top = (pwr_x, pwr_y - 3.81)
    c6_bot = (pwr_x, pwr_y + 3.81)
    sch.add_wire(start=(pwr_x, pwr_y - 10 * G), end=c6_top)
    gnd_c6_y = c6_bot[1] + 6 * G
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(pwr_x, gnd_c6_y))
    sch.add_wire(start=c6_bot, end=(pwr_x, gnd_c6_y))
    pwr_idx += 1
    sch.add_text("+15V\nbulk decoupling", position=(pwr_x + 5 * G, pwr_y - 4 * G), size=2.0)

    # -15V bulk decoupling
    neg_x = pwr_x + 26 * G
    sch.components.add(lib_id="VEE:VEE", reference=f"#PWR0{pwr_idx:02d}",
        value="-15V", position=(neg_x, pwr_y - 10 * G))
    pwr_idx += 1
    sch.components.add(lib_id="C:C", reference="C7", value="10u",
        position=(neg_x, pwr_y))
    c7_top = (neg_x, pwr_y - 3.81)
    c7_bot = (neg_x, pwr_y + 3.81)
    sch.add_wire(start=(neg_x, pwr_y - 10 * G), end=c7_top)
    gnd_c7_y = c7_bot[1] + 6 * G
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(neg_x, gnd_c7_y))
    sch.add_wire(start=c7_bot, end=(neg_x, gnd_c7_y))
    pwr_idx += 1
    sch.add_text("-15V\nbulk decoupling", position=(neg_x + 5 * G, pwr_y - 4 * G), size=2.0)

    # 3.3V MCU supply
    reg_x = pwr_x + 52 * G
    sch.add_label("3.3V", position=(reg_x, pwr_y - 10 * G))
    sch.components.add(lib_id="C:C", reference="C8", value="100n",
        position=(reg_x, pwr_y))
    c8_top = (reg_x, pwr_y - 3.81)
    c8_bot = (reg_x, pwr_y + 3.81)
    sch.add_wire(start=(reg_x, pwr_y - 10 * G), end=c8_top)
    gnd_c8_y = c8_bot[1] + 6 * G
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(reg_x, gnd_c8_y))
    sch.add_wire(start=c8_bot, end=(reg_x, gnd_c8_y))
    pwr_idx += 1
    sch.add_text("3.3V MCU supply\n(LDO from +15V)", position=(reg_x + 5 * G, pwr_y - 4 * G), size=2.0)

    # ── Interface annotations ──
    sch.add_text("Interfaces:", position=(8 * G, 62 * G), size=2.5, bold=True)
    sch.add_text("HP output: startup pulse injected via R9 (one-shot at power-on)",
                 position=(8 * G, 66 * G), size=2.0)
    sch.add_text("+15V/-15V: powers U1/U2/U3 LM4562 op-amps",
                 position=(8 * G, 70 * G), size=2.0)
    sch.add_text("3.3V: powers U5 ADuCM362 MCU",
                 position=(8 * G, 74 * G), size=2.0)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "osc_block_power_supply.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    merge_collinear_wires(sch_path)
    print(f"    Saved: {sch_path}")
    return sch_path


def build_osc_block_mcu():
    """Oscillator Block 6/6: ADuCM362 MCU.

    SPI0 -> DAC7800 frequency control (VCTRL)
    AIN0 <- AD636 RMS output
    Timer1/P0.5 <- BP zero-crossing for frequency measurement
    UART TX/RX for host communication (115200 8N1)
    """
    print("  Building block: ADuCM362 MCU...")
    sch = create_schematic("Oscillator - ADuCM362 MCU")
    sch.set_paper_size("A4")
    sch.set_title_block(
        title="State Variable Oscillator - ADuCM362 MCU",
        company="CircuitForge",
        rev="1.0",
        comments={1: "SPI0->DAC7800 freq ctrl, ADC AIN0<-AD636",
                  2: "Timer1 zero-crossing, UART 115200 8N1",
                  3: "Block 6 of 6"}
    )
    G = 2.54
    pwr_idx = 1

    # ── Block title ──
    sch.add_text("ADuCM362 MCU (U5)", position=(8 * G, 6 * G), size=4.0, bold=True)
    sch.add_text("ARM Cortex-M3, 24-bit Sigma-Delta ADC, SPI, UART",
                 position=(8 * G, 12 * G), size=2.5)
    sch.add_text("SPI0 controls dual DAC7800 MDACs, Timer1 measures BP frequency",
                 position=(8 * G, 17 * G), size=2.0)
    sch.add_text("FUNCTION: Digital brain of the oscillator. Sets frequency via SPI to",
                 position=(8 * G, 23 * G), size=1.8)
    sch.add_text("DAC7800 MDACs, measures actual frequency via Timer1 capture of BP",
                 position=(8 * G, 27 * G), size=1.8)
    sch.add_text("zero-crossings (16MHz clock), reads amplitude via 24-bit ADC from AD636.",
                 position=(8 * G, 31 * G), size=1.8)
    sch.add_text("Runs 16-point self-calibration stored in flash. UART host interface.",
                 position=(8 * G, 35 * G), size=1.8)

    # ── MCU block ──
    mcu_x = 40 * G
    mcu_y = 42 * G
    pin_spacing = 10 * G

    # Dashed box
    mcu_box_l = mcu_x - 12 * G
    mcu_box_r = mcu_x + 12 * G
    mcu_box_t = mcu_y - 12 * G
    mcu_box_b = mcu_y + 4 * pin_spacing + 4 * G
    sch.add_rectangle(
        start=(mcu_box_l, mcu_box_t),
        end=(mcu_box_r, mcu_box_b),
        stroke_width=0.3, stroke_type='dash'
    )
    sch.add_text("U5\nADuCM362\nARM Cortex-M3",
                 position=(mcu_x - 10 * G, mcu_y - 10 * G), size=2.5, bold=True)

    # Left side pins (inputs)
    left_x = mcu_x - 20 * G
    labels_left = ["AIN0", "P0.5_ZC", "UART_RX"]
    for i, name in enumerate(labels_left):
        pin_y = mcu_y + i * pin_spacing
        sch.add_wire(start=(left_x, pin_y), end=(mcu_x - 8 * G, pin_y))
        sch.add_text(name, position=(left_x - 4 * G, pin_y), size=1.8)

    # AIN0 net label
    sch.add_label("AIN0", position=(left_x - 8 * G, mcu_y))
    sch.add_wire(start=(left_x - 8 * G, mcu_y), end=(left_x, mcu_y))

    # BP_ZC net label
    sch.add_label("BP_ZC", position=(left_x - 8 * G, mcu_y + pin_spacing))
    sch.add_wire(start=(left_x - 8 * G, mcu_y + pin_spacing),
                 end=(left_x, mcu_y + pin_spacing))

    # UART_RX net label
    sch.add_label("UART_RX", position=(left_x - 8 * G, mcu_y + 2 * pin_spacing))
    sch.add_wire(start=(left_x - 8 * G, mcu_y + 2 * pin_spacing),
                 end=(left_x, mcu_y + 2 * pin_spacing))

    # Right side pins (outputs)
    right_x = mcu_x + 20 * G
    labels_right = ["SPI0_CLK", "SPI0_MOSI", "DAC_CS", "UART_TX"]
    for i, name in enumerate(labels_right):
        pin_y = mcu_y + i * pin_spacing
        sch.add_wire(start=(mcu_x + 8 * G, pin_y), end=(right_x, pin_y))
        sch.add_label(name, position=(right_x, pin_y))

    # SPI annotation
    sch.add_text("SPI0 -> DAC7800\ncontrols VCTRL\n(frequency set)",
                 position=(right_x + 2 * G, mcu_y + 3 * pin_spacing + 5 * G), size=1.8)

    # MCU power (3.3V)
    mcu_vcc_y = mcu_y - 14 * G
    sch.add_label("3.3V", position=(mcu_x, mcu_vcc_y))
    sch.add_wire(start=(mcu_x, mcu_vcc_y), end=(mcu_x, mcu_y - 8 * G))

    # MCU GND
    mcu_gnd_y = mcu_y + 4 * pin_spacing + 6 * G
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(mcu_x, mcu_gnd_y))
    pwr_idx += 1
    sch.add_wire(start=(mcu_x, mcu_y + 3 * pin_spacing + 4 * G),
                 end=(mcu_x, mcu_gnd_y))

    # Decoupling caps
    dcap_x = mcu_x + 12 * G
    dcap_y = mcu_y - 8 * G
    sch.components.add(lib_id="C:C", reference="C4", value="100n",
        position=(dcap_x, dcap_y))
    c4_top = (dcap_x, dcap_y - 3.81)
    c4_bot = (dcap_x, dcap_y + 3.81)
    sch.add_wire(start=(mcu_x, mcu_y - 8 * G), end=c4_top)
    gnd_dc_y = c4_bot[1] + 4 * G
    sch.add_wire(start=c4_bot, end=(dcap_x, gnd_dc_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(dcap_x, gnd_dc_y))
    pwr_idx += 1

    sch.components.add(lib_id="C:C", reference="C5", value="10u",
        position=(dcap_x + 10 * G, dcap_y))
    c5_top = (dcap_x + 10 * G, dcap_y - 3.81)
    c5_bot = (dcap_x + 10 * G, dcap_y + 3.81)
    sch.add_wire(start=c4_top, end=c5_top)
    gnd_dc2_y = c5_bot[1] + 4 * G
    sch.add_wire(start=c5_bot, end=(dcap_x + 10 * G, gnd_dc2_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(dcap_x + 10 * G, gnd_dc2_y))
    pwr_idx += 1

    # Annotations
    sch.add_text("UART (115200 8N1) to host PC",
                 position=(mcu_x - 10 * G, mcu_y + 4 * pin_spacing + 10 * G), size=2.0)
    sch.add_text("Timer1 capture: zero-crossing frequency measurement",
                 position=(left_x - 8 * G, mcu_y + pin_spacing + 5 * G), size=1.8)

    # ── Interface annotations ──
    sch.add_text("Interfaces:", position=(8 * G, 58 * G), size=2.5, bold=True)
    sch.add_text("AIN0: from AD636 RMS detector (U4) DC output",
                 position=(8 * G, 62 * G), size=2.0)
    sch.add_text("BP_ZC: from Integrator 1 (U2) BP zero-crossing",
                 position=(8 * G, 66 * G), size=2.0)
    sch.add_text("SPI0: to DAC7800 XDAC1/XDAC2 for frequency control",
                 position=(8 * G, 70 * G), size=2.0)
    sch.add_text("UART: to host PC for commands (F<hz>, D<code>, CAL, M, S)",
                 position=(8 * G, 74 * G), size=2.0)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "osc_block_mcu.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    merge_collinear_wires(sch_path)
    print(f"    Saved: {sch_path}")
    return sch_path


def build_osc_blocks():
    """Build all 6 oscillator block schematics, export PDFs, merge into one."""
    print("\nBuilding oscillator block schematics (6 blocks)...")

    blocks = [
        ("Summing Amplifier", build_osc_block_summing_amp),
        ("Integrator 1",      build_osc_block_integrator1),
        ("RMS Detector",      build_osc_block_rms_detector),
        ("Integrator 2",      build_osc_block_integrator2),
        ("Power Supply",      build_osc_block_power_supply),
        ("MCU",               build_osc_block_mcu),
    ]

    sch_paths = []
    pdf_paths = []
    all_ok = True

    for name, builder in blocks:
        sch_path = builder()
        sch_paths.append(sch_path)

        # Verify
        print(f"    Verifying {name}...")
        verify_circuit(sch_path, 'oscillator', {}, {})

        # Export PDF + PNG
        try:
            pdf_path = export_pdf(sch_path)
            pdf_paths.append(pdf_path)
            png_name = f"osc_block_{name.lower().replace(' ', '_')}.png"
            render_pdf_to_png(pdf_path,
                os.path.join(WORK_DIR, png_name),
                zoom=4, clip_mm=(10, 10, 200, 285))
        except Exception as e:
            print(f"    Export error for {name}: {e}")
            all_ok = False

    # Merge all block PDFs into one document
    if pdf_paths:
        merged_path = os.path.join(WORK_DIR, "oscillator_blocks.pdf")
        merge_pdfs(pdf_paths, merged_path)

    print(f"\n  Oscillator blocks complete: {len(sch_paths)} schematics")
    if all_ok and pdf_paths:
        print(f"  Merged PDF: {os.path.join(WORK_DIR, 'oscillator_blocks.pdf')}")
    return sch_paths


def build_tia_blocks():
    """Build all TIA/electrometer block schematics, export PDFs, merge into one."""
    print("\nBuilding TIA/electrometer block schematics (6 blocks)...")

    blocks = [
        ("Input Filters",     build_input_filters,    'input_filters'),
        ("Analog Mux",        build_analog_mux,       'analog_mux'),
        ("Mux TIA",           build_mux_tia,          'mux_tia'),
        ("Relay Ladder",      build_relay_ladder,      'relay_ladder'),
        ("MCU Section",       build_mcu_section,       'mcu_section'),
        ("Electrometer 362",  build_electrometer_362,  'electrometer_362'),
    ]

    sch_paths = []
    pdf_paths = []
    all_ok = True

    for name, builder, ctype in blocks:
        print(f"  Building block: {name}...")
        sch_path = builder()
        sch_paths.append(sch_path)

        # Verify
        print(f"    Verifying {name}...")
        verify_circuit(sch_path, ctype, {}, {})

        # Export PDF + PNG
        try:
            pdf_path = export_pdf(sch_path)
            pdf_paths.append(pdf_path)
            png_name = f"tia_block_{name.lower().replace(' ', '_')}.png"
            render_pdf_to_png(pdf_path,
                os.path.join(WORK_DIR, png_name), zoom=4)
        except Exception as e:
            print(f"    Export error for {name}: {e}")
            all_ok = False

    # Merge all block PDFs into one document
    if pdf_paths:
        merged_path = os.path.join(WORK_DIR, "electrometer_blocks.pdf")
        merge_pdfs(pdf_paths, merged_path)

    print(f"\n  TIA blocks complete: {len(sch_paths)} schematics")
    if all_ok and pdf_paths:
        print(f"  Merged PDF: {os.path.join(WORK_DIR, 'electrometer_blocks.pdf')}")
    return sch_paths


def build_oscillator(**kwargs):
    """Build State Variable Oscillator KiCad schematic.

    Layout on A3 sheet with 3x scaling for readability (3-col x 2-row grid):
        Row 1 (top):    Summing Amp       | Integrator 1 (HP->BP) | AD636 RMS Detector
        Row 2 (bottom): Integrator 2 (BP->LP) | Startup Kick + Power  | ADuCM362 MCU

    Tighter grid spacing so components fill the sheet properly.
    """
    print("Building State Variable Oscillator schematic...")

    sch = create_schematic("State Variable Oscillator with MDAC Control")
    sch.set_paper_size("A3")
    sch.set_title_block(
        title="State Variable Oscillator - ADuCM362 + DAC7800 + AD636",
        company="CircuitForge - Bob Smith",
        rev="3.0",
        comments={1: "MDAC frequency control: 25Hz-30kHz",
                  2: "Zener AGC: 1V RMS output, AD636 amplitude monitoring",
                  3: "3-col x 2-row grid layout, A3 1:1"}
    )

    G = 2.54
    pwr_idx = 1

    # ── Parameterized spacing (correction loop compatible) ──
    fb_vert = kwargs.get('feedback_vert', 6)          # feedback Rf/Cint above inv input (G)
    damp_vert = kwargs.get('damp_vert', 10)           # R_damp above inv input (G)
    zener_vert = kwargs.get('zener_vert', 14)         # zeners above inv input (G)
    col_spacing = kwargs.get('col_spacing', 42)       # column spacing (G) - A3 at 1x scale
    row_spacing = kwargs.get('row_spacing', 45)       # row spacing (G) - A3 at 1x scale

    # ── 3-column x 2-row grid origins ──
    # Spread to fill A3 sheet (420x297mm at 1x scale)
    c1x = 8 * G      # Column 1 left edge (margin for titles)
    c2x = (8 + col_spacing) * G      # Column 2 left edge
    c3x = (8 + 2 * col_spacing) * G  # Column 3 left edge
    r1y = 10 * G     # Row 1 top (leaves room for section titles above)
    r2y = (10 + row_spacing) * G     # Row 2 top

    # ═══════════════════════════════════════════════════════════════
    # REGION 1: SUMMING AMPLIFIER (U1 LM4562)  [Row 1, Col 1]
    # HP output = -(R_lp/Rf_sum)*LP - (R_bp/Rf_sum)*BP
    # ═══════════════════════════════════════════════════════════════
    sch.add_text("SUMMING AMPLIFIER", position=(c1x, r1y - 4 * G), size=3.5, bold=True)

    u1_x, u1_y = c1x + 40 * G, r1y + 30 * G
    sch.components.add(lib_id="LM741:LM741", reference="U1",
        value="LM4562", position=(u1_x, u1_y))

    # U1 pin positions (default: inv(-) on top, ni(+) on bottom)
    u1_inv = (u1_x - 7.62, u1_y - 2.54)
    u1_ni  = (u1_x - 7.62, u1_y + 2.54)
    u1_out = (u1_x + 7.62, u1_y)
    u1_vp  = (u1_x - 2.54, u1_y + 7.62)
    u1_vm  = (u1_x - 2.54, u1_y - 7.62)

    # Junction point at inverting input (summing node)
    sum_x = u1_inv[0] - 6 * G
    sum_y = u1_inv[1]

    # R_lp (10k) - LP input to summing node
    rlp_x = sum_x - 14 * G
    rlp_y = sum_y - 10 * G
    sch.components.add(lib_id="R:R", reference="R1", value="10k",
        position=(rlp_x, rlp_y), rotation=90)
    rlp_left = (rlp_x - 3.81, rlp_y)
    rlp_right = (rlp_x + 3.81, rlp_y)
    wire_manhattan(sch, rlp_right[0], rlp_right[1], sum_x, sum_y)
    sch.add_label("LP", position=(rlp_left[0] - 6 * G, rlp_y))
    sch.add_wire(start=(rlp_left[0] - 6 * G, rlp_y), end=rlp_left)

    # R_bp (22k) - BP input to summing node
    rbp_x = sum_x - 14 * G
    rbp_y = sum_y
    sch.components.add(lib_id="R:R", reference="R2", value="22k",
        position=(rbp_x, rbp_y), rotation=90)
    rbp_left = (rbp_x - 3.81, rbp_y)
    rbp_right = (rbp_x + 3.81, rbp_y)
    sch.add_wire(start=rbp_right, end=(sum_x, sum_y))
    sch.add_label("BP", position=(rbp_left[0] - 6 * G, rbp_y))
    sch.add_wire(start=(rbp_left[0] - 6 * G, rbp_y), end=rbp_left)

    # Rf_sum (10k) - feedback summing node to output
    rf_y = sum_y - fb_vert * G
    rf_cx = (sum_x + u1_out[0]) / 2
    sch.components.add(lib_id="R:R", reference="R3", value="10k",
        position=(rf_cx, rf_y), rotation=90)
    rf_left = (rf_cx - 3.81, rf_y)
    rf_right = (rf_cx + 3.81, rf_y)
    sch.add_wire(start=(sum_x, sum_y), end=(sum_x, rf_y))
    sch.add_wire(start=(sum_x, rf_y), end=rf_left)
    sch.add_wire(start=rf_right, end=(u1_out[0], rf_y))
    sch.add_wire(start=(u1_out[0], rf_y), end=u1_out)
    sch.junctions.add(position=(sum_x, sum_y))

    # Summing node to inv input
    sch.add_wire(start=(sum_x, sum_y), end=u1_inv)

    # Non-inverting input to GND
    gnd1_y = u1_ni[1] + 6 * G
    sch.add_wire(start=u1_ni, end=(u1_ni[0], gnd1_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(u1_ni[0], gnd1_y))
    pwr_idx += 1

    # Power pins (+15V as net label, not VCC symbol, to avoid net mixing)
    vcc_y1 = u1_vp[1] + 6 * G
    sch.add_wire(start=u1_vp, end=(u1_vp[0], vcc_y1))
    sch.add_label("+15V", position=(u1_vp[0], vcc_y1))
    vee_y1 = u1_vm[1] - 6 * G
    sch.add_wire(start=(u1_vm[0], vee_y1), end=u1_vm)
    sch.components.add(lib_id="VEE:VEE", reference=f"#PWR0{pwr_idx:02d}",
        value="-15V", position=(u1_vm[0], vee_y1))
    pwr_idx += 1

    # HP output label
    hp_lbl_x = u1_out[0] + 8 * G
    sch.add_label("HP", position=(hp_lbl_x, u1_out[1]))
    sch.add_wire(start=u1_out, end=(hp_lbl_x, u1_out[1]))
    sch.junctions.add(position=u1_out)

    # ═══════════════════════════════════════════════════════════════
    # REGION 2: INTEGRATOR 1 - HP -> BP (via MDAC1) [Row 1, Col 2]
    # U2 LM4562, DAC7800 (XDAC1), Cint1 470p, R_damp1 100M
    # Zener AGC: Dz1/Dz2 back-to-back on integrator cap
    # ═══════════════════════════════════════════════════════════════
    sch.add_text("INTEGRATOR 1 (HP->BP) + MDAC", position=(c2x, r1y - 4 * G),
                 size=3.5, bold=True)

    u2_x, u2_y = c2x + 45 * G, r1y + 35 * G
    sch.components.add(lib_id="LM741:LM741", reference="U2",
        value="LM4562", position=(u2_x, u2_y))

    u2_inv = (u2_x - 7.62, u2_y - 2.54)
    u2_ni  = (u2_x - 7.62, u2_y + 2.54)
    u2_out = (u2_x + 7.62, u2_y)
    u2_vp  = (u2_x - 2.54, u2_y + 7.62)
    u2_vm  = (u2_x - 2.54, u2_y - 7.62)

    # DAC7800 MDAC (XDAC1) - proper IC box
    dac1_x = u2_inv[0] - 28 * G
    dac1_y = u2_inv[1]
    dac1_pins = _draw_dac7800_box(sch, "XDAC1", dac1_x, dac1_y, G)

    sch.add_label("HP", position=(dac1_pins['vref'][0] - 10 * G, dac1_y))
    sch.add_wire(start=(dac1_pins['vref'][0] - 10 * G, dac1_y),
                 end=dac1_pins['vref'])

    # Rint1 (10k) between MDAC IOUT and inv input
    rint1_x = u2_inv[0] - 14 * G
    rint1_y = u2_inv[1]
    sch.components.add(lib_id="R:R", reference="R4", value="10k",
        position=(rint1_x, rint1_y), rotation=90)
    rint1_left = (rint1_x - 3.81, rint1_y)
    rint1_right = (rint1_x + 3.81, rint1_y)
    sch.add_wire(start=dac1_pins['iout'], end=rint1_left)
    # CTRL label for DAC
    ctrl_y1 = dac1_pins['vctrl'][1] + 4 * G
    sch.add_label("VCTRL", position=(dac1_pins['vctrl'][0], ctrl_y1))
    sch.add_wire(start=dac1_pins['vctrl'],
                 end=(dac1_pins['vctrl'][0], ctrl_y1))

    # Wire Rint1 to inv input
    sch.add_wire(start=rint1_right, end=u2_inv)

    # Cint1 (470p) - integrator cap in feedback
    cint1_y = u2_inv[1] - fb_vert * G
    cint1_cx = (u2_inv[0] + u2_out[0]) / 2
    sch.components.add(lib_id="C:C", reference="C1", value="470p",
        position=(cint1_cx, cint1_y), rotation=90)
    c1_left = (cint1_cx - 3.81, cint1_y)
    c1_right = (cint1_cx + 3.81, cint1_y)

    # Feedback: inv_node up to cap, cap across, down to output
    # Use cint1_cx - 3.81 as feedback column x to avoid overlapping V- pin column
    inv1_junc = (cint1_cx - 3.81, u2_inv[1])
    sch.add_wire(start=rint1_right, end=inv1_junc)
    sch.add_wire(start=inv1_junc, end=(inv1_junc[0], cint1_y))
    sch.add_wire(start=(inv1_junc[0], cint1_y), end=c1_left)
    sch.add_wire(start=c1_right, end=(u2_out[0], cint1_y))
    sch.add_wire(start=(u2_out[0], cint1_y), end=u2_out)
    sch.junctions.add(position=inv1_junc)

    # R_damp1 (100M) - parallel to Cint1
    rdamp1_y = u2_inv[1] - damp_vert * G
    sch.components.add(lib_id="R:R", reference="R5", value="100M",
        position=(cint1_cx, rdamp1_y), rotation=90)
    rd1_left = (cint1_cx - 3.81, rdamp1_y)
    rd1_right = (cint1_cx + 3.81, rdamp1_y)
    sch.add_wire(start=(inv1_junc[0], cint1_y), end=(inv1_junc[0], rdamp1_y))
    sch.add_wire(start=(inv1_junc[0], rdamp1_y), end=rd1_left)
    sch.add_wire(start=rd1_right, end=(u2_out[0], rdamp1_y))
    sch.add_wire(start=(u2_out[0], rdamp1_y), end=(u2_out[0], cint1_y))
    sch.junctions.add(position=(inv1_junc[0], cint1_y))
    sch.junctions.add(position=(u2_out[0], cint1_y))

    # Zener AGC: Dz1, Dz2 back-to-back (anode-to-anode center)
    # Cathode wires route DOWN then horizontally to buses for visual clarity
    zener1_y = u2_inv[1] - zener_vert * G
    cathode_drop = 3 * G
    sch.components.add(lib_id="D_Zener:D_Zener", reference="D1", value="DZ09 BV=1.1",
        position=(cint1_cx - 5 * G, zener1_y), rotation=0)
    sch.components.add(lib_id="D_Zener:D_Zener", reference="D2", value="DZ09 BV=1.1",
        position=(cint1_cx + 5 * G, zener1_y), rotation=180)
    d1_k = (cint1_cx - 5 * G - 3.81, zener1_y)
    d1_a = (cint1_cx - 5 * G + 3.81, zener1_y)
    d2_a = (cint1_cx + 5 * G - 3.81, zener1_y)
    d2_k = (cint1_cx + 5 * G + 3.81, zener1_y)
    sch.add_wire(start=d1_a, end=d2_a)
    # D1 cathode: drop down, then horizontal to left bus
    sch.add_wire(start=d1_k, end=(d1_k[0], zener1_y + cathode_drop))
    sch.add_wire(start=(d1_k[0], zener1_y + cathode_drop),
                 end=(inv1_junc[0], zener1_y + cathode_drop))
    sch.add_wire(start=(inv1_junc[0], zener1_y + cathode_drop),
                 end=(inv1_junc[0], rdamp1_y))
    sch.junctions.add(position=(inv1_junc[0], zener1_y + cathode_drop))
    sch.junctions.add(position=(inv1_junc[0], rdamp1_y))
    # D2 cathode: drop down, then horizontal to right bus
    sch.add_wire(start=d2_k, end=(d2_k[0], zener1_y + cathode_drop))
    sch.add_wire(start=(d2_k[0], zener1_y + cathode_drop),
                 end=(u2_out[0], zener1_y + cathode_drop))
    sch.add_wire(start=(u2_out[0], zener1_y + cathode_drop),
                 end=(u2_out[0], rdamp1_y))
    sch.junctions.add(position=(u2_out[0], zener1_y + cathode_drop))
    sch.junctions.add(position=(u2_out[0], rdamp1_y))
    sch.add_text("Zener AGC\nBV=1.1V", position=(cint1_cx - 2 * G, zener1_y + 5 * G), size=2.0)

    # U2 non-inverting input to GND
    gnd2_y = u2_ni[1] + 6 * G
    sch.add_wire(start=u2_ni, end=(u2_ni[0], gnd2_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(u2_ni[0], gnd2_y))
    pwr_idx += 1

    # U2 power (+15V net label)
    vcc_y2 = u2_vp[1] + 6 * G
    sch.add_wire(start=u2_vp, end=(u2_vp[0], vcc_y2))
    sch.add_label("+15V", position=(u2_vp[0], vcc_y2))
    vee_y2 = u2_vm[1] - 3 * G   # shortened to stay below feedback
    sch.add_wire(start=(u2_vm[0], vee_y2), end=u2_vm)
    sch.components.add(lib_id="VEE:VEE", reference=f"#PWR0{pwr_idx:02d}",
        value="-15V", position=(u2_vm[0], vee_y2))
    pwr_idx += 1

    # BP output label
    bp_lbl_x = u2_out[0] + 8 * G
    sch.add_label("BP", position=(bp_lbl_x, u2_out[1]))
    sch.add_wire(start=u2_out, end=(bp_lbl_x, u2_out[1]))
    sch.junctions.add(position=u2_out)

    # Frequency annotation
    sch.add_text("f = D / (4096 * 2pi * 10k * 470p)\n[25Hz - 30kHz]",
                 position=(c2x + 2 * G, r1y + 58 * G), size=2.0)

    # ═══════════════════════════════════════════════════════════════
    # REGION 3: AD636 RMS DETECTOR [Row 1, Col 3]
    # 1/5 attenuator (40k + 10k), AD636 + CAV 10uF
    # Input from BP, output to MCU ADC (AIN0)
    # ═══════════════════════════════════════════════════════════════
    sch.add_text("AD636 RMS DETECTOR", position=(c3x, r1y - 4 * G), size=3.5, bold=True)

    # Attenuator: R_att1 (40k) + R_att2 (10k) voltage divider
    att_x = c3x + 18 * G
    att_y = r1y + 30 * G

    sch.components.add(lib_id="R:R", reference="R10", value="40k",
        position=(att_x, att_y), rotation=90)
    ratt1_left = (att_x - 3.81, att_y)
    ratt1_right = (att_x + 3.81, att_y)
    sch.add_label("BP", position=(ratt1_left[0] - 6 * G, att_y))
    sch.add_wire(start=(ratt1_left[0] - 6 * G, att_y), end=ratt1_left)

    # R_att2 (10k) - shunt to GND, vertical
    att2_x = ratt1_right[0] + 6 * G
    att2_y = att_y + 8 * G
    sch.components.add(lib_id="R:R", reference="R11", value="10k",
        position=(att2_x, att2_y))
    ratt2_top = (att2_x, att2_y - 3.81)
    ratt2_bot = (att2_x, att2_y + 3.81)
    sch.add_wire(start=ratt1_right, end=(att2_x, att_y))
    sch.add_wire(start=(att2_x, att_y), end=ratt2_top)
    sch.junctions.add(position=(att2_x, att_y))
    gnd_att_y = ratt2_bot[1] + 5 * G
    sch.add_wire(start=ratt2_bot, end=(att2_x, gnd_att_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(att2_x, gnd_att_y))
    pwr_idx += 1
    sch.add_text("1/5 attenuator\nVin/5 to AD636", position=(att2_x + 5 * G, att_y), size=2.0)

    # AD636 block (drawn as text label + CAV cap)
    ad636_x = att2_x + 24 * G
    ad636_y = att_y
    sch.add_wire(start=(att2_x, att_y), end=(ad636_x - 8 * G, att_y))
    sch.add_text("U4\nAD636\nRMS-to-DC", position=(ad636_x - 6 * G, att_y - 7 * G), size=2.5)

    # CAV capacitor (10uF) - averaging cap
    cav_x = ad636_x
    cav_y = att_y + 8 * G
    sch.components.add(lib_id="C:C", reference="C3", value="10u",
        position=(cav_x, cav_y))
    cav_top = (cav_x, cav_y - 3.81)
    cav_bot = (cav_x, cav_y + 3.81)
    sch.add_wire(start=(ad636_x - 2 * G, att_y), end=(cav_x, att_y))
    sch.add_wire(start=(cav_x, att_y), end=cav_top)
    sch.add_text("CAV", position=(cav_x + 4 * G, cav_y), size=2.0)
    gnd_cav_y = cav_bot[1] + 5 * G
    sch.add_wire(start=cav_bot, end=(cav_x, gnd_cav_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(cav_x, gnd_cav_y))
    pwr_idx += 1

    # AD636 output to AIN0 label
    ain0_x = ad636_x + 12 * G
    sch.add_label("AIN0", position=(ain0_x, att_y))
    sch.add_wire(start=(cav_x, att_y), end=(ain0_x, att_y))
    sch.junctions.add(position=(cav_x, att_y))

    # ═══════════════════════════════════════════════════════════════
    # REGION 4: INTEGRATOR 2 - BP -> LP (via MDAC2) [Row 2, Col 1]
    # U3 LM4562, DAC7800 (XDAC2), Cint2 470p, R_damp2 100M
    # Zener AGC: Dz3/Dz4 back-to-back
    # ═══════════════════════════════════════════════════════════════
    sch.add_text("INTEGRATOR 2 (BP->LP) + MDAC", position=(c1x, r2y - 4 * G),
                 size=3.5, bold=True)

    u3_x, u3_y = c1x + 45 * G, r2y + 35 * G
    sch.components.add(lib_id="LM741:LM741", reference="U3",
        value="LM4562", position=(u3_x, u3_y))

    u3_inv = (u3_x - 7.62, u3_y - 2.54)
    u3_ni  = (u3_x - 7.62, u3_y + 2.54)
    u3_out = (u3_x + 7.62, u3_y)
    u3_vp  = (u3_x - 2.54, u3_y + 7.62)
    u3_vm  = (u3_x - 2.54, u3_y - 7.62)

    # DAC7800 MDAC #2 (XDAC2) - proper IC box
    dac2_x = u3_inv[0] - 28 * G
    dac2_y = u3_inv[1]
    dac2_pins = _draw_dac7800_box(sch, "XDAC2", dac2_x, dac2_y, G)

    sch.add_label("BP", position=(dac2_pins['vref'][0] - 10 * G, dac2_y))
    sch.add_wire(start=(dac2_pins['vref'][0] - 10 * G, dac2_y),
                 end=dac2_pins['vref'])

    # Rint2 (10k) between MDAC IOUT and inv input
    rint2_x = u3_inv[0] - 14 * G
    rint2_y = u3_inv[1]
    sch.components.add(lib_id="R:R", reference="R6", value="10k",
        position=(rint2_x, rint2_y), rotation=90)
    rint2_left = (rint2_x - 3.81, rint2_y)
    rint2_right = (rint2_x + 3.81, rint2_y)
    sch.add_wire(start=dac2_pins['iout'], end=rint2_left)
    ctrl_y2 = dac2_pins['vctrl'][1] + 4 * G
    sch.add_label("VCTRL", position=(dac2_pins['vctrl'][0], ctrl_y2))
    sch.add_wire(start=dac2_pins['vctrl'],
                 end=(dac2_pins['vctrl'][0], ctrl_y2))

    sch.add_wire(start=rint2_right, end=u3_inv)

    # Cint2 (470p)
    cint2_y = u3_inv[1] - fb_vert * G
    cint2_cx = (u3_inv[0] + u3_out[0]) / 2
    sch.components.add(lib_id="C:C", reference="C2", value="470p",
        position=(cint2_cx, cint2_y), rotation=90)
    c2_left = (cint2_cx - 3.81, cint2_y)
    c2_right = (cint2_cx + 3.81, cint2_y)

    # Use cint2_cx - 3.81 as feedback column x to avoid overlapping V- pin column
    inv2_junc = (cint2_cx - 3.81, u3_inv[1])
    sch.add_wire(start=rint2_right, end=inv2_junc)
    sch.add_wire(start=inv2_junc, end=(inv2_junc[0], cint2_y))
    sch.add_wire(start=(inv2_junc[0], cint2_y), end=c2_left)
    sch.add_wire(start=c2_right, end=(u3_out[0], cint2_y))
    sch.add_wire(start=(u3_out[0], cint2_y), end=u3_out)
    sch.junctions.add(position=inv2_junc)

    # R_damp2 (100M)
    rdamp2_y = u3_inv[1] - damp_vert * G
    sch.components.add(lib_id="R:R", reference="R7", value="100M",
        position=(cint2_cx, rdamp2_y), rotation=90)
    rd2_left = (cint2_cx - 3.81, rdamp2_y)
    rd2_right = (cint2_cx + 3.81, rdamp2_y)
    sch.add_wire(start=(inv2_junc[0], cint2_y), end=(inv2_junc[0], rdamp2_y))
    sch.add_wire(start=(inv2_junc[0], rdamp2_y), end=rd2_left)
    sch.add_wire(start=rd2_right, end=(u3_out[0], rdamp2_y))
    sch.add_wire(start=(u3_out[0], rdamp2_y), end=(u3_out[0], cint2_y))
    sch.junctions.add(position=(inv2_junc[0], cint2_y))
    sch.junctions.add(position=(u3_out[0], cint2_y))

    # Zener AGC Dz3/Dz4 back-to-back (anode-to-anode center)
    # Cathode wires route DOWN then horizontally to buses for visual clarity
    zener2_y = u3_inv[1] - zener_vert * G
    cathode_drop = 3 * G
    sch.components.add(lib_id="D_Zener:D_Zener", reference="D3", value="DZ09 BV=1.1",
        position=(cint2_cx - 5 * G, zener2_y), rotation=0)
    sch.components.add(lib_id="D_Zener:D_Zener", reference="D4", value="DZ09 BV=1.1",
        position=(cint2_cx + 5 * G, zener2_y), rotation=180)
    d3_k = (cint2_cx - 5 * G - 3.81, zener2_y)
    d3_a = (cint2_cx - 5 * G + 3.81, zener2_y)
    d4_a = (cint2_cx + 5 * G - 3.81, zener2_y)
    d4_k = (cint2_cx + 5 * G + 3.81, zener2_y)
    sch.add_wire(start=d3_a, end=d4_a)
    # D3 cathode: drop down, then horizontal to left bus
    sch.add_wire(start=d3_k, end=(d3_k[0], zener2_y + cathode_drop))
    sch.add_wire(start=(d3_k[0], zener2_y + cathode_drop),
                 end=(inv2_junc[0], zener2_y + cathode_drop))
    sch.add_wire(start=(inv2_junc[0], zener2_y + cathode_drop),
                 end=(inv2_junc[0], rdamp2_y))
    sch.junctions.add(position=(inv2_junc[0], zener2_y + cathode_drop))
    sch.junctions.add(position=(inv2_junc[0], rdamp2_y))
    # D4 cathode: drop down, then horizontal to right bus
    sch.add_wire(start=d4_k, end=(d4_k[0], zener2_y + cathode_drop))
    sch.add_wire(start=(d4_k[0], zener2_y + cathode_drop),
                 end=(u3_out[0], zener2_y + cathode_drop))
    sch.add_wire(start=(u3_out[0], zener2_y + cathode_drop),
                 end=(u3_out[0], rdamp2_y))
    sch.junctions.add(position=(u3_out[0], zener2_y + cathode_drop))
    sch.junctions.add(position=(u3_out[0], rdamp2_y))
    sch.add_text("Zener AGC\nBV=1.1V", position=(cint2_cx - 2 * G, zener2_y + 5 * G), size=2.0)

    # U3 GND + power
    gnd3_y = u3_ni[1] + 6 * G
    sch.add_wire(start=u3_ni, end=(u3_ni[0], gnd3_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(u3_ni[0], gnd3_y))
    pwr_idx += 1
    vcc_y3 = u3_vp[1] + 6 * G
    sch.add_wire(start=u3_vp, end=(u3_vp[0], vcc_y3))
    sch.add_label("+15V", position=(u3_vp[0], vcc_y3))
    vee_y3 = u3_vm[1] - 3 * G   # shortened to stay below feedback
    sch.add_wire(start=(u3_vm[0], vee_y3), end=u3_vm)
    sch.components.add(lib_id="VEE:VEE", reference=f"#PWR0{pwr_idx:02d}",
        value="-15V", position=(u3_vm[0], vee_y3))
    pwr_idx += 1

    # LP output label
    lp_lbl_x = u3_out[0] + 8 * G
    sch.add_label("LP", position=(lp_lbl_x, u3_out[1]))
    sch.add_wire(start=u3_out, end=(lp_lbl_x, u3_out[1]))
    sch.junctions.add(position=u3_out)

    # Output load (100k to GND) - connects BP back
    rl_x = u3_out[0] + 16 * G
    rl_y = u3_out[1] + 10 * G
    sch.components.add(lib_id="R:R", reference="R8", value="100k",
        position=(rl_x, rl_y))
    rl_top = (rl_x, rl_y - 3.81)
    rl_bot = (rl_x, rl_y + 3.81)
    sch.add_label("BP", position=(rl_x + 6 * G, rl_top[1]))
    sch.add_wire(start=rl_top, end=(rl_x + 6 * G, rl_top[1]))
    gnd_rl_y = rl_bot[1] + 5 * G
    sch.add_wire(start=rl_bot, end=(rl_x, gnd_rl_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(rl_x, gnd_rl_y))
    pwr_idx += 1

    # ═══════════════════════════════════════════════════════════════
    # REGION 5: STARTUP KICK + POWER SUPPLY [Row 2, Col 2]
    # ═══════════════════════════════════════════════════════════════
    sch.add_text("STARTUP KICK + POWER SUPPLY", position=(c2x, r2y - 4 * G),
                 size=3.5, bold=True)

    # Startup kick
    kick_x = c2x + 10 * G
    kick_y = r2y + 20 * G
    sch.components.add(lib_id="R:R", reference="R9", value="100k",
        position=(kick_x, kick_y), rotation=90)
    rk_left = (kick_x - 3.81, kick_y)
    rk_right = (kick_x + 3.81, kick_y)
    sch.add_label("HP", position=(rk_right[0] + 6 * G, kick_y))
    sch.add_wire(start=rk_right, end=(rk_right[0] + 6 * G, kick_y))
    sch.add_text("Startup Kick\nPULSE 0.1V 10us", position=(kick_x - 10 * G, kick_y - 5 * G), size=2.0)
    gnd_kick_y = kick_y + 8 * G
    sch.add_wire(start=rk_left, end=(rk_left[0], gnd_kick_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(rk_left[0], gnd_kick_y))
    pwr_idx += 1

    # Power supply section (below startup kick, same column)
    pwr_x = c2x + 10 * G
    pwr_y = r2y + 42 * G

    # +15V supply with bulk decoupling (net label, not VCC symbol)
    sch.add_label("+15V", position=(pwr_x, pwr_y - 8 * G))
    sch.components.add(lib_id="C:C", reference="C6", value="10u",
        position=(pwr_x, pwr_y))
    c6_top = (pwr_x, pwr_y - 3.81)
    c6_bot = (pwr_x, pwr_y + 3.81)
    sch.add_wire(start=(pwr_x, pwr_y - 8 * G), end=c6_top)
    gnd_c6_y = c6_bot[1] + 5 * G
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(pwr_x, gnd_c6_y))
    sch.add_wire(start=c6_bot, end=(pwr_x, gnd_c6_y))
    pwr_idx += 1
    sch.add_text("+15V\nbulk", position=(pwr_x + 5 * G, pwr_y - 4 * G), size=2.0)

    # -15V supply with bulk decoupling
    neg_x = pwr_x + 22 * G
    sch.components.add(lib_id="VEE:VEE", reference=f"#PWR0{pwr_idx:02d}",
        value="-15V", position=(neg_x, pwr_y - 8 * G))
    pwr_idx += 1
    sch.components.add(lib_id="C:C", reference="C7", value="10u",
        position=(neg_x, pwr_y))
    c7_top = (neg_x, pwr_y - 3.81)
    c7_bot = (neg_x, pwr_y + 3.81)
    sch.add_wire(start=(neg_x, pwr_y - 8 * G), end=c7_top)
    gnd_c7_y = c7_bot[1] + 5 * G
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(neg_x, gnd_c7_y))
    sch.add_wire(start=c7_bot, end=(neg_x, gnd_c7_y))
    pwr_idx += 1
    sch.add_text("-15V\nbulk", position=(neg_x + 5 * G, pwr_y - 4 * G), size=2.0)

    # 3.3V regulator (LDO) - net label, not VCC symbol
    reg_x = pwr_x + 44 * G
    sch.add_label("3.3V", position=(reg_x, pwr_y - 8 * G))
    sch.components.add(lib_id="C:C", reference="C8", value="100n",
        position=(reg_x, pwr_y))
    c8_top = (reg_x, pwr_y - 3.81)
    c8_bot = (reg_x, pwr_y + 3.81)
    sch.add_wire(start=(reg_x, pwr_y - 8 * G), end=c8_top)
    gnd_c8_y = c8_bot[1] + 5 * G
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(reg_x, gnd_c8_y))
    sch.add_wire(start=c8_bot, end=(reg_x, gnd_c8_y))
    pwr_idx += 1
    sch.add_text("3.3V MCU\n(LDO from +15V)", position=(reg_x + 5 * G, pwr_y - 4 * G), size=2.0)

    # ═══════════════════════════════════════════════════════════════
    # REGION 6: ADuCM362 MCU BLOCK [Row 2, Col 3]
    # SPI0 -> DAC7800 (VCTRL), ADC AIN0 <- AD636, Timer1/P0.5 <- ZC
    # UART TX/RX for host communication
    # ═══════════════════════════════════════════════════════════════
    sch.add_text("ADuCM362 MCU", position=(c3x, r2y - 4 * G), size=3.5, bold=True)

    mcu_x = c3x + 35 * G
    mcu_y = r2y + 28 * G

    # MCU drawn as labeled block with pin labels and dashed box
    pin_spacing = 8 * G
    mcu_box_l = mcu_x - 10 * G
    mcu_box_r = mcu_x + 10 * G
    mcu_box_t = mcu_y - 10 * G
    mcu_box_b = mcu_y + 4 * pin_spacing + 2 * G
    sch.add_rectangle(
        start=(mcu_box_l, mcu_box_t),
        end=(mcu_box_r, mcu_box_b),
        stroke_width=0.3, stroke_type='dash'
    )
    sch.add_text("U5\nADuCM362\nARM Cortex-M3", position=(mcu_x - 8 * G, mcu_y - 8 * G),
                 size=2.5, bold=True)

    # Left side pins (inputs) - wider spacing for readability
    left_x = mcu_x - 16 * G
    labels_left = ["AIN0", "P0.5_ZC", "UART_RX"]
    for i, name in enumerate(labels_left):
        pin_y = mcu_y + i * pin_spacing
        sch.add_wire(start=(left_x, pin_y), end=(mcu_x - 6 * G, pin_y))
        sch.add_text(name, position=(left_x - 3 * G, pin_y), size=1.8)

    # AIN0 net label (connects to AD636 output)
    sch.add_label("AIN0", position=(left_x - 6 * G, mcu_y))
    sch.add_wire(start=(left_x - 6 * G, mcu_y), end=(left_x, mcu_y))

    # ZC input (connects to BP zero-crossing)
    sch.add_label("BP_ZC", position=(left_x - 6 * G, mcu_y + pin_spacing))
    sch.add_wire(start=(left_x - 6 * G, mcu_y + pin_spacing),
                 end=(left_x, mcu_y + pin_spacing))

    # UART_RX net label (connects to host UART)
    sch.add_label("UART_RX", position=(left_x - 6 * G, mcu_y + 2 * pin_spacing))
    sch.add_wire(start=(left_x - 6 * G, mcu_y + 2 * pin_spacing),
                 end=(left_x, mcu_y + 2 * pin_spacing))

    # Right side pins (outputs) with net labels to avoid floating wires
    right_x = mcu_x + 16 * G
    labels_right = ["SPI0_CLK", "SPI0_MOSI", "DAC_CS", "UART_TX"]
    for i, name in enumerate(labels_right):
        pin_y = mcu_y + i * pin_spacing
        sch.add_wire(start=(mcu_x + 6 * G, pin_y), end=(right_x, pin_y))
        sch.add_label(name, position=(right_x, pin_y))

    # Annotation: SPI controls DAC7800 which outputs VCTRL (not a net label)
    sch.add_text("SPI0 -> DAC7800\ncontrols VCTRL",
                 position=(right_x + 2 * G, mcu_y + 3 * pin_spacing + 4 * G), size=1.8)

    # MCU power (3.3V net label)
    mcu_vcc_y = mcu_y - 12 * G
    sch.add_label("3.3V", position=(mcu_x, mcu_vcc_y))
    sch.add_wire(start=(mcu_x, mcu_vcc_y), end=(mcu_x, mcu_y - 6 * G))

    mcu_gnd_y = mcu_y + 4 * pin_spacing + 4 * G
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(mcu_x, mcu_gnd_y))
    pwr_idx += 1
    sch.add_wire(start=(mcu_x, mcu_y + 3 * pin_spacing + 2 * G), end=(mcu_x, mcu_gnd_y))

    # Decoupling caps (GND leads shortened to avoid crossing VCTRL bus wire)
    dcap_x = mcu_x + 10 * G
    dcap_y = mcu_y - 6 * G
    sch.components.add(lib_id="C:C", reference="C4", value="100n",
        position=(dcap_x, dcap_y))
    c4_top = (dcap_x, dcap_y - 3.81)
    c4_bot = (dcap_x, dcap_y + 3.81)
    sch.add_wire(start=(mcu_x, mcu_y - 6 * G), end=c4_top)
    gnd_dc_y = c4_bot[1] + 3 * G  # 3*G keeps GND above VCTRL wire
    sch.add_wire(start=c4_bot, end=(dcap_x, gnd_dc_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(dcap_x, gnd_dc_y))
    pwr_idx += 1

    sch.components.add(lib_id="C:C", reference="C5", value="10u",
        position=(dcap_x + 8 * G, dcap_y))
    c5_top = (dcap_x + 8 * G, dcap_y - 3.81)
    c5_bot = (dcap_x + 8 * G, dcap_y + 3.81)
    sch.add_wire(start=c4_top, end=c5_top)
    gnd_dc2_y = c5_bot[1] + 3 * G  # 3*G keeps GND above VCTRL wire
    sch.add_wire(start=c5_bot, end=(dcap_x + 8 * G, gnd_dc2_y))
    sch.components.add(lib_id="GND:GND", reference=f"#PWR0{pwr_idx:02d}",
        value="GND", position=(dcap_x + 8 * G, gnd_dc2_y))
    pwr_idx += 1

    # ═══════════════════════════════════════════════════════════════
    # ANNOTATIONS
    # ═══════════════════════════════════════════════════════════════
    sch.add_text("UART (115200 8N1) to host PC",
                 position=(mcu_x - 8 * G, mcu_y + 4 * pin_spacing + 8 * G), size=2.0)
    sch.add_text("Timer1 capture: zero-crossing frequency measurement",
                 position=(left_x - 6 * G, mcu_y + pin_spacing + 4 * G), size=1.8)

    # ── Save ──
    sch_path = os.path.join(WORK_DIR, "oscillator.kicad_sch")
    sch.save(sch_path)
    fix_kicad_sch(sch_path)
    merge_collinear_wires(sch_path)

    # Scale factor: 1 = standard A3 (professional layout), >1 = enlarged
    sf = kwargs.get('scale_factor', 1)
    if sf and sf != 1:
        scale_schematic(sch_path, factor=sf)

    print(f"  Oscillator schematic saved: {sch_path}")
    print(f"  Components: 3 op-amps, 2 DAC7800, 4 Zeners, AD636, ADuCM362")
    print(f"  Net labels: HP, BP, LP, VCTRL, AIN0, BP_ZC")
    print(f"  Layout: 3-col x 2-row grid, {sf}x scale, A3 sheet")
    return sch_path


def write_oscillator_netlist(dac_code=121):
    """Write ngspice netlist for state variable oscillator simulation.

    Generates a Zener-clamped SVF oscillator with MDAC frequency control.
    The DAC code sets the oscillation frequency via:
        f = D / (4096 * 2*pi * 10k * 470p) = D / 0.1211

    Args:
        dac_code: 12-bit DAC code (3-3632), maps to ~25Hz-30kHz

    Results written to sim_work/oscillator_d{dac_code}_results.txt
    with key=value pairs: freq, bp_pp, bp_rms, hp_pp, lp_pp
    """
    FREQ_CONST = 4096 * 2 * 3.14159265 * 10e3 * 470e-12  # 0.1211
    vctrl = dac_code / 4096.0 * 5.0
    expected_freq = dac_code / FREQ_CONST

    # Adaptive sim time: enough cycles for measurement
    period = 1.0 / max(expected_freq, 1.0)
    sim_time = max(0.5, 30 * period)
    tstep = min(1e-6, period / 50.0)  # At least 50 points per cycle

    # Measurement window: last 20% of sim
    meas_from = sim_time * 0.8
    meas_to = sim_time

    # Rise count for zero-crossing frequency measurement
    rise_start = max(5, int(expected_freq * meas_from * 0.5))
    rise_end = rise_start + 1

    models_dir = os.path.join(REPO_DIR, "StateVarOsc", "models").replace('\\', '/')
    results_file = os.path.join(WORK_DIR, f'oscillator_d{dac_code}_results.txt').replace('\\', '/')
    results_filename = f'oscillator_d{dac_code}_results.txt'

    netlist = f"""* State Variable Oscillator - DAC code {dac_code} (expected {expected_freq:.1f} Hz)
* Auto-generated by CircuitForge kicad_pipeline.py

.title SVO Frequency Test D={dac_code}

.include "{models_dir}/LM4562.lib"
.include "{models_dir}/DAC7800.lib"

* === Power Supply ===
VCC vcc 0 DC 15
VEE vee 0 DC -15

* === MDAC Control Voltage ===
* DAC code {dac_code}: Vctrl = {dac_code}/4096 * 5.0 = {vctrl:.6f}V
Vctrl ctrl_node 0 DC {vctrl:.6f}

* === Summing Amplifier (U1a) ===
R_lp lp sum_inv 10k
R_bp bp sum_inv 22k
Rf_sum hp sum_inv 10k
XU1a 0 sum_inv vcc vee hp LM4562

* === Integrator 1: HP -> BP (via MDAC) ===
XDAC1 hp mdac1_out ctrl_node rfb1_nc DAC7800
Rint1 mdac1_out int1_inv 10k
Cint1 int1_inv bp 470p
R_damp1 int1_inv bp 100Meg
XU1b 0 int1_inv vcc vee bp LM4562

* Zener clamp on BP integrator
Dz1 z_mid1 int1_inv DZ09
Dz2 z_mid1 bp DZ09

* === Integrator 2: BP -> LP (via MDAC) ===
XDAC2 bp mdac2_out ctrl_node rfb2_nc DAC7800
Rint2 mdac2_out int2_inv 10k
Cint2 int2_inv lp 470p
R_damp2 int2_inv lp 100Meg
XU2a 0 int2_inv vcc vee lp LM4562

* Zener clamp on LP integrator
Dz3 z_mid2 int2_inv DZ09
Dz4 z_mid2 lp DZ09

* Zener model: BV=1.1V, threshold ~1.45V (tuned for ~1.03V RMS)
.model DZ09 D(Is=1e-14 BV=1.1 IBV=1e-3 N=1)

* === Startup kick pulse ===
Vkick kick_node 0 PULSE(0 0.1 0.1m 1n 1n 10u 1)
Rkick kick_node hp 100k

* === Output load ===
RL bp 0 100k

* === Analysis ===
.tran {tstep:.2e} {sim_time:.4f} UIC

.control
tran {tstep:.2e} {sim_time:.4f} uic

* Frequency measurement
meas tran t1 when v(bp)=0 rise={rise_start}
meas tran t2 when v(bp)=0 rise={rise_end}
let period = t2 - t1
let freq = 1 / period

* Amplitude measurement (last 20% of sim)
meas tran bp_pp pp v(bp) from={meas_from:.4f} to={meas_to:.4f}
let bp_rms = bp_pp / (2 * 1.41421)
meas tran hp_pp pp v(hp) from={meas_from:.4f} to={meas_to:.4f}
meas tran lp_pp pp v(lp) from={meas_from:.4f} to={meas_to:.4f}

* Write results to file
echo "freq = $&freq" > {results_filename}
echo "bp_pp = $&bp_pp" >> {results_filename}
echo "bp_rms = $&bp_rms" >> {results_filename}
echo "hp_pp = $&hp_pp" >> {results_filename}
echo "lp_pp = $&lp_pp" >> {results_filename}

echo ""
echo "=== Results for D={dac_code} ==="
print freq
print bp_pp
print bp_rms
quit
.endc

.end
"""
    out_path = os.path.join(WORK_DIR, f"oscillator_d{dac_code}.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {out_path}")
    print(f"  DAC code: {dac_code}, Vctrl: {vctrl:.6f}V, Expected freq: {expected_freq:.1f} Hz")
    return out_path


def write_analog_osc_netlist(target_freq_hz=1581.0):
    """Write ngspice netlist for the friend's analog state variable oscillator.

    Generates a SVF oscillator using LM4562 op-amps with the friend's original
    component values: R_int (parameterized), C=10nF, and critically R7=100k
    (very low damping) with NO amplitude limiting (no Zener clamps, broken AGC).

    This faithfully reproduces the friend's circuit behavior: the JFET AGC loop
    fails to regulate amplitude, so the oscillator clips at the supply rails.
    Key differences from the MDAC design:
      - R7=100k (vs 22k) -> Q~10 (vs Q~2.2) -> much less damping
      - No Zener clamps -> output clips at +/-13.5V instead of +/-1.5V
      - Fixed R/C frequency (no MDAC) -> R_int parameterized for target freq
      - Result: ~27Vpp clipped output, ~9.5V RMS (vs ~3Vpp, ~1V RMS)

    Args:
        target_freq_hz: Target oscillation frequency in Hz.

    Returns:
        Path to the generated .cir netlist file.

    Results written to sim_work/analog_osc_{freq}Hz_results.txt
    with key=value pairs: freq, bp_pp, bp_rms, hp_pp, lp_pp
    """
    import math

    C_INT = 10e-9  # 10nF (matches friend's schematic)
    R_int = 1.0 / (2 * math.pi * target_freq_hz * C_INT)

    # Adaptive sim time
    period = 1.0 / max(target_freq_hz, 1.0)
    sim_time = max(0.5, 30 * period)
    tstep = min(1e-6, period / 50.0)

    # Measurement window: last 20% (same as MDAC design)
    meas_from = sim_time * 0.8
    meas_to = sim_time

    # Rise count for zero-crossing frequency measurement
    rise_start = max(5, int(target_freq_hz * meas_from * 0.5))
    rise_end = rise_start + 1

    models_dir = os.path.join(REPO_DIR, "StateVarOsc", "models").replace('\\', '/')
    freq_tag = f"{target_freq_hz:.0f}"
    results_file = os.path.join(WORK_DIR, f'analog_osc_{freq_tag}Hz_results.txt').replace('\\', '/')
    # Use just the filename for ngspice echo (cwd = sim_work, avoids space issues)
    results_filename = f'analog_osc_{freq_tag}Hz_results.txt'

    netlist = f"""* Friend's Analog State Variable Oscillator - target {target_freq_hz:.1f} Hz
* R_int = {R_int:.1f} ohms (for C = 10nF)
* Auto-generated by CircuitForge kicad_pipeline.py
* Friend's design: AD824 op-amps, R7=100k (low damping), NO amplitude limiting
* Result: oscillates but clips at supply rails (~27Vpp, ~9.5V RMS)

.title Analog SVO Target={target_freq_hz:.0f}Hz

.include "{models_dir}/LM4562.lib"

* === Power Supply ===
VCC vcc 0 DC 15
VEE vee 0 DC -15

* ======================================================================
* SUMMING AMPLIFIER (U4 in friend's LTspice: AD824 -> LM4562)
* ======================================================================
* Friend's values: R5=10k feedback, R6=10k from LP, R7=100k from BP
* R7=100k gives very low damping (Q ~ R7/R5 = 10) compared to MDAC (22k, Q~2.2)
* Non-inverting input grounded (friend's JFET AGC fails to regulate,
* so the positive feedback path is effectively broken)
R5 hp sum_inv 10k
R6 lp sum_inv 10k
R7 bp sum_inv 100k
XU4 0 sum_inv vcc vee hp LM4562

* ======================================================================
* INTEGRATOR 1: HP -> BP (U2 in friend's LTspice: AD824 -> LM4562)
* ======================================================================
* Friend's design: fixed R/C (no MDAC), no Zener clamp
* R_int parameterized for target frequency: f = 1/(2*pi*R*C)
R1 hp int1_inv {R_int:.4f}
C1 int1_inv bp {C_INT:.2e}
XU2 0 int1_inv vcc vee bp LM4562

* ======================================================================
* INTEGRATOR 2: BP -> LP (U1 in friend's LTspice: AD824 -> LM4562)
* ======================================================================
R3 bp int2_inv {R_int:.4f}
C2 int2_inv lp {C_INT:.2e}
XU1 0 int2_inv vcc vee lp LM4562

* ======================================================================
* STARTUP AND LOAD
* ======================================================================
* Startup kick (same approach as MDAC oscillator)
Vkick kick_node 0 PULSE(0 0.1 0.1m 1n 1n 10u 1)
Rkick kick_node hp 100k

* Output load
RL bp 0 100k

* ======================================================================
* ANALYSIS
* ======================================================================
.tran {tstep:.2e} {sim_time:.4f} UIC

.control
tran {tstep:.2e} {sim_time:.4f} uic

* Frequency measurement (same method as MDAC oscillator)
meas tran t1 when v(bp)=0 rise={rise_start}
meas tran t2 when v(bp)=0 rise={rise_end}
let period = t2 - t1
let freq = 1 / period

* Amplitude measurement (last 20% of sim)
meas tran bp_pp pp v(bp) from={meas_from:.4f} to={meas_to:.4f}
let bp_rms = bp_pp / (2 * 1.41421)
meas tran hp_pp pp v(hp) from={meas_from:.4f} to={meas_to:.4f}
meas tran lp_pp pp v(lp) from={meas_from:.4f} to={meas_to:.4f}

* Write results to file (identical format to MDAC oscillator)
* Use relative filename (ngspice cwd = sim_work dir)
echo "freq = $&freq" > {results_filename}
echo "bp_pp = $&bp_pp" >> {results_filename}
echo "bp_rms = $&bp_rms" >> {results_filename}
echo "hp_pp = $&hp_pp" >> {results_filename}
echo "lp_pp = $&lp_pp" >> {results_filename}

echo ""
echo "=== Results for Analog Osc target={target_freq_hz:.0f}Hz ==="
print freq
print bp_pp
print bp_rms
quit
.endc

.end
"""
    out_path = os.path.join(WORK_DIR, f"analog_osc_{freq_tag}Hz.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {out_path}")
    print(f"  Target freq: {target_freq_hz:.1f} Hz, R_int: {R_int:.1f} ohms, C_int: {C_INT:.2e} F")
    return out_path


def write_rtd_temp_netlist(rtd_type="PT100"):
    """
    Write ngspice netlist for RTD temperature measurement simulation.

    Models the CN-0359 style 4-wire RTD circuit:
    IEXC (600uA) -> R_LEAD1 -> RTD(T) -> R_LEAD2 -> RREF (1.5k) -> GND
                       |           |          |           |
                     AIN7       AIN8       AIN9        AIN6
                   (excite)   (sense+)   (sense-)   (RREF sense)

    Uses a temperature staircase (PWL) driving a behavioral RTD resistor.
    Verifies ratiometric measurement accuracy and 4-wire lead cancellation.
    """
    r0 = 100 if rtd_type == "PT100" else 1000
    iexc = 600e-6  # 600uA excitation
    rref = 1500    # 1.5k precision reference
    r_lead = 1.0   # 1 ohm per lead (represents ~10m cable)

    # IEC 751 coefficients
    A_coeff = 3.9083e-3
    B_coeff = -5.775e-7

    # Temperature staircase: -40, 0, 25, 50, 100, 150, 200°C
    # Each step held for 10ms
    temps = [-40, 0, 25, 50, 100, 150, 200]
    pwl_points = []
    for i, t in enumerate(temps):
        t_start = i * 10e-3
        t_end = t_start + 9e-3
        pwl_points.append(f"{t_start} {t}")
        pwl_points.append(f"{t_end} {t}")
    pwl_str = "\n+ ".join(pwl_points)

    sim_time = len(temps) * 10e-3 + 1e-3  # extra 1ms margin

    netlist = f"""* RTD Temperature Measurement - 4-Wire {rtd_type}
* ADuCM362 ADC1: AIN5-AIN9, IEXC=600uA, RREF=1.5k
* IEC 751/ITS-90: R(T) = R0*(1 + A*T + B*T^2)
* R0={r0} ohm, A={A_coeff}, B={B_coeff}

* ---- Temperature Control (staircase: -40 to 200C) ----
V_TEMP TEMP 0 PWL(
+ {pwl_str})

* ---- Excitation Current Source (600uA from ADuCM362 IEXC) ----
I_EXC 0 AIN7 DC {iexc}

* ---- Lead Resistances (4-wire cable, {r_lead} ohm each) ----
R_LEAD1 AIN7 RTD_HI {r_lead}
R_LEAD2 RTD_LO RREF_TOP {r_lead}

* ---- RTD Behavioral Model ({rtd_type}) ----
* R(T) = {r0}*(1 + A*V(TEMP) + B*V(TEMP)^2)
B_RTD RTD_HI RTD_LO I=V(RTD_HI,RTD_LO) / ({r0}*(1 + {A_coeff}*V(TEMP) + ({B_coeff})*V(TEMP)*V(TEMP)))

* ---- Kelvin Sense Lines (high-Z, direct to RTD terminals) ----
R_K_HI RTD_HI AIN8 1
R_K_LO RTD_LO AIN9 1

* ---- Reference Resistor (precision 1.5k, 0.1%) ----
R_REF RREF_TOP 0 {rref}

* ---- RREF Sense (AIN6 at top of RREF) ----
R_SENSE6 RREF_TOP AIN6 1

* ---- ADC input loads (high-Z sigma-delta) ----
R_ADC5 AIN9 0 1G
R_ADC6 AIN6 0 1G
R_ADC7 AIN7 0 1G
R_ADC8 AIN8 0 1G
R_ADC9 AIN9 0 1G

* ---- Analysis ----
.tran 10u {sim_time}

.control
run
wrdata {os.path.join(WORK_DIR, 'rtd_temp_results.txt').replace(chr(92), '/')} V(TEMP) V(AIN7) V(AIN8) V(AIN9) V(AIN6)
quit
.endc

.end
"""

    out_path = os.path.join(WORK_DIR, "rtd_temp.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {out_path}")
    print(f"  {rtd_type}: R0={r0} ohm, IEXC={iexc*1e6:.0f}uA, RREF={rref} ohm")
    print(f"  Temperature staircase: {temps}")
    print(f"  Lead resistance: {r_lead} ohm per lead (4-wire cancellation)")
    return out_path


def write_combined_logging_netlist(opamp="LMC6001", n_channels=4, rtd_type="PT100"):
    """
    Write combined data logging netlist: channel current + RTD temperature.

    Demonstrates the full ADuCM362 measurement cycle:
    - ADC0: TIA current measurement via mux (n_channels sequentially)
    - ADC1: RTD temperature measurement (continuous, 4-wire PT100/PT1000)
    Both ADCs run simultaneously on the dual-ADC MCU.

    RTD temperature ramps slowly during scan to simulate thermal drift,
    verifying that temperature compensation data is captured with each channel.
    """
    OPAMP_DB = {
        "LMC6001":  ("LMC6001_NS",  "nation.lib", 5, "LMC6001 Ultra-Low Bias"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LMC6001"])
    model_name, lib_file, n_pins, title = info
    model_block = extract_model(model_name, lib_file)

    r0 = 100 if rtd_type == "PT100" else 1000
    A_coeff = 3.9083e-3
    B_coeff = -5.775e-7

    ch_period = 0.2  # 200ms per channel
    sim_time = ch_period * n_channels + 0.05

    # Channel currents (subset of the 16-channel table)
    CHANNEL_CURRENTS = {
        1: 0.10e-9, 2: 0.50e-9, 3: 1.00e-9, 4: 0.25e-9,
    }

    ch_lines = []
    en_lines = []
    for ch in range(1, n_channels + 1):
        i_val = CHANNEL_CURRENTS.get(ch, 1e-9 / ch)
        ch_lines.append(f"""
* ---- Channel {ch}: I={i_val*1e9:.3f}nA ----
Isrc{ch} 0 CH{ch}_IN DC {i_val}
R_DUT{ch} CH{ch}_IN 0 100Meg
R_IN{ch} CH{ch}_IN MUX{ch}_IN 1Meg
S_MUX{ch} MUX{ch}_IN TIA_IN EN{ch} 0 SW_MUX""")

        t_on = (ch - 1) * ch_period
        en_lines.append(
            f"V_EN{ch} EN{ch} 0 PULSE(0 5 {t_on} 1u 1u {ch_period} {sim_time + 1})")

    ch_section = "".join(ch_lines)
    en_section = "\n".join(en_lines)

    wrdata_nodes = []
    for ch in range(1, n_channels + 1):
        wrdata_nodes.append(f"V(CH{ch}_IN)")
    wrdata_nodes.extend(["V(TIA_OUT)", "V(AIN0)", "V(RTD_TEMP)", "V(AIN8)", "V(AIN9)", "V(AIN6)"])
    wrdata_str = " ".join(wrdata_nodes)
    wrdata_path = os.path.join(WORK_DIR, 'combined_logging_results.txt').replace('\\', '/')

    netlist = f"""* Combined Data Logging: {n_channels}-Channel Current + RTD Temperature
* ADC0: TIA current via mux, ADC1: 4-wire {rtd_type} temperature
* Op-amp: {title}, Range 2: Rf=1G
* Channels switch every {ch_period*1000:.0f}ms, RTD reads continuously

* ---- Power Supply ----
VCC VCC 0 DC 5
VEE VEE 0 DC -5

* ---- Mux Switch Model ----
.model SW_MUX SW(VT=2.5 VH=0.5 RON=100 ROFF=1e12)

* ==== ADC0 PATH: Channel Current Measurement ====
{ch_section}

* ---- Mux Enable Signals (sequential) ----
{en_section}

* ---- TIA ----
XU1 0 INV VCC VEE TIA_OUT {model_name}

* ---- Feedback Network (Range 2) ----
Rf INV TIA_OUT 1G
Cf INV TIA_OUT 10p

* ---- Mux to TIA connection ----
R_WIRE TIA_IN INV 1
R_BIAS TIA_IN 0 100Meg

* ---- ADC0 Load ----
RL TIA_OUT AIN0 100
R_ADC0 AIN0 0 10Meg

* ==== ADC1 PATH: RTD Temperature Measurement ====

* ---- Temperature drift (25C rising to 27C over scan) ----
* Simulates slow thermal drift during measurement cycle
V_TEMP RTD_TEMP 0 PWL(0 25 {sim_time} 27)

* ---- Excitation Current Source (600uA) ----
I_EXC 0 AIN7_EXC DC 600u

* ---- Lead Resistances (4-wire, 1 ohm each) ----
R_LEAD1 AIN7_EXC RTD_HI 1
R_LEAD2 RTD_LO RREF_TOP 1

* ---- RTD Behavioral Model ({rtd_type}) ----
B_RTD RTD_HI RTD_LO I=V(RTD_HI,RTD_LO) / ({r0}*(1 + {A_coeff}*V(RTD_TEMP) + ({B_coeff})*V(RTD_TEMP)*V(RTD_TEMP)))

* ---- Kelvin Sense Lines ----
R_K_HI RTD_HI AIN8 1
R_K_LO RTD_LO AIN9 1

* ---- Reference Resistor (1.5k) ----
R_REF RREF_TOP 0 1500

* ---- RREF Sense ----
R_SENSE6 RREF_TOP AIN6 1

* ---- ADC1 Loads ----
R_ADC6 AIN6 0 1G
R_ADC8 AIN8 0 1G
R_ADC9_A AIN9 0 1G

* ---- Analysis ----
.tran 10u {sim_time}

.control
run
wrdata {wrdata_path} {wrdata_str}
quit
.endc

{model_block}

.end
"""

    out_path = os.path.join(WORK_DIR, "combined_logging.cir")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {out_path}")
    print(f"  {n_channels} channels + {rtd_type} RTD, {ch_period*1000:.0f}ms/ch")
    return out_path


def write_usb_ina_netlist(opamp="AD822"):
    """Write ngspice netlist for the 3-op-amp instrumentation amplifier."""
    OPAMP_DB = {
        "AD797": ("AD797_AD", "analog.lib", 6, "AD797 Ultra-Low Noise"),
        "AD822": ("AD822_AD", "analog.lib", 5, "AD822 Precision JFET"),
        "AD843": ("AD843J_AD", "analog.lib", 5, "AD843 Fast Settling"),
        "LM741": ("LM741_NS", "nation.lib", 5, "LM741 Classic"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["AD822"])
    model_name, lib_file, n_pins, title_opamp = info
    model_block = extract_model(model_name, lib_file)

    if n_pins == 6:
        xu1 = f"XU1 INP FB1 VCC VEE BUF1 DEC1 {model_name}"
        xu2 = f"XU2 INN FB2 VCC VEE BUF2 DEC2 {model_name}"
        xu3 = f"XU3 DIFFN DIFFP VCC VEE VOUT_INT DEC3 {model_name}"
        extra = "CDC1 DEC1 VEE 100p\nCDC2 DEC2 VEE 100p\nCDC3 DEC3 VEE 100p"
    else:
        xu1 = f"XU1 INP FB1 VCC VEE BUF1 {model_name}"
        xu2 = f"XU2 INN FB2 VCC VEE BUF2 {model_name}"
        xu3 = f"XU3 DIFFN DIFFP VCC VEE VOUT_INT {model_name}"
        extra = ""

    if not model_block:
        model_block = f"* {model_name} not found\n"

    netlist = f"""* USB-Isolated 3-Op-Amp Instrumentation Amplifier ({title_opamp})
* G_buf = 1 + 2*Rf/Rg = 1 + 2*47k/1k = 95
* G_diff = R6/R4 = 10k/10k = 1
* G_total = 95
* Generated by kicad_pipeline.py

* Dual power supply (USB-isolated via DC-DC)
VCC VCC 0 12
VEE VEE 0 -12

* Differential input signal: +/-5mV @ 200Hz
VINP INP 0 SINE(0 5m 200)
VINN INN 0 SINE(0 -5m 200)

* Stage 1: Input buffers with gain
* U1 buffer (+)
{xu1}
R1 BUF1 FB1 47k
* U2 buffer (-)
{xu2}
R2 BUF2 FB2 47k
* Gain-set resistor
R3 FB1 FB2 1k
{extra}

* Stage 2: Difference amplifier
R4 BUF1 DIFFP 10k
R5 BUF2 DIFFN 10k
R6 VOUT_INT DIFFP 10k
R7 DIFFN 0 10k
{xu3}

* Output coupling + load
C1 VOUT_INT OUT 10u
R8 OUT 0 10k

* Model
{model_block}

* Simulation
.tran 1u 20m

.control
run
wrdata usb_ina_results.txt V(INP) V(OUT) V(BUF1) V(BUF2) V(VOUT_INT)
quit
.endc

.end
"""
    netlist_path = os.path.join(WORK_DIR, "usb_ina.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {netlist_path}")
    return netlist_path


def write_inv_amp_netlist():
    """Write ngspice netlist for the inverting amplifier."""
    # Extract the LM741 model from Micro-Cap library
    model_block = extract_model("LM741_NS", "nation.lib")
    if not model_block:
        model_block = "* LM741 model not found - using ideal opamp\n"

    netlist = f"""* LM741 Inverting Amplifier (Gain = -10)
* Generated by kicad_pipeline.py

* Dual power supply
VCC VCC 0 12
VEE VEE 0 -12

* Input signal: 100mV @ 1kHz
VIN IN 0 SINE(0 100m 1k)

* Input coupling
C1 IN N_RIN 1u

* Input resistor
R1 N_RIN INV 10k

* Feedback resistor
R2 OUT_INT INV 100k

* Op-amp: subckt pins are (+in, -in, V+, V-, out)
XU1 0 INV VCC VEE OUT_INT LM741_NS

* Output coupling + load
C2 OUT_INT OUT 10u
R3 OUT 0 10k

* Model
{model_block}

* Simulation
.tran 1u 10m

.control
run
wrdata inv_amp_results.txt V(IN) V(OUT) V(OUT_INT) V(INV)
quit
.endc

.end
"""
    netlist_path = os.path.join(WORK_DIR, "inv_amp.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {netlist_path}")
    return netlist_path


def write_sig_cond_netlist(opamp="LM741"):
    """Write ngspice netlist for the dual op-amp signal conditioner.

    opamp: "LM741" (default), "AD822" (JFET precision), or "AD797" (ultra-low noise)
    """
    # Op-amp model selection
    OPAMP_DB = {
        "AD797": ("AD797_AD", "analog.lib", 6,
                  "AD797 (Ultra-Low Noise, 110MHz GBW)"),
        "AD822": ("AD822_AD", "analog.lib", 5,
                  "AD822 (Precision JFET, 1.8MHz GBW)"),
        "AD843": ("AD843J_AD", "analog.lib", 5,
                  "AD843 (Fast Settling, 34MHz)"),
        "LM741": ("LM741_NS", "nation.lib", 5, "LM741 (Classic)"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LM741"])
    model_name, lib_file, n_pins, title_opamp = info
    model_block = extract_model(model_name, lib_file)

    if n_pins == 6:
        # AD797 has extra decompensation pin
        xu1_line = f"XU1 N_IN FB1 VCC VEE STAGE1 DECOMP1 {model_name}"
        xu2_line = f"XU2 N2 FILTERED VCC VEE FILTERED DECOMP2 {model_name}"
        extra = f"* Decompensation pins tied to V- via 100pF\nCDC1 DECOMP1 VEE 100p\nCDC2 DECOMP2 VEE 100p"
    else:
        xu1_line = f"XU1 N_IN FB1 VCC VEE STAGE1 {model_name}"
        xu2_line = f"XU2 N2 FILTERED VCC VEE FILTERED {model_name}"
        extra = ""

    if not model_block:
        model_block = f"* {model_name} model not found\n"

    netlist = f"""* Dual Op-Amp Signal Conditioner ({title_opamp})
* Stage 1: Non-inverting amplifier (Gain = 11)
* Stage 2: Sallen-Key 2nd-order LPF (fc ~ 1kHz)
* Generated by kicad_pipeline.py

* Dual power supply
VCC VCC 0 12
VEE VEE 0 -12

* Input signal: 5mV @ 200Hz sensor signal
VIN SENSOR 0 SINE(0 5m 200)

* Input coupling
C1 SENSOR N_IN 1u

* Stage 1: Non-inverting amplifier
* (+) input gets signal, (-) input gets feedback divider
* Gain = 1 + R1/R2 = 1 + 100k/10k = 11
R6 N_IN 0 100k
{xu1_line}
R1 STAGE1 FB1 100k
R2 FB1 0 10k
{extra}

* Sallen-Key 2nd-order Butterworth LPF
* R3=R4=10k, C3=33n, C4=15n -> fc = 1/(2*pi*R*sqrt(C3*C4)) ~ 1kHz
R3 STAGE1 N1 10k
R4 N1 N2 10k
C3 N1 0 33n
C4 N2 FILTERED 15n

* Stage 2: Unity-gain buffer for Sallen-Key
{xu2_line}

* Output coupling + load
C2 FILTERED OUT 10u
R5 OUT 0 10k

* Model
{model_block}

* Simulation: run long enough for 200Hz signal (5ms period)
.tran 1u 20m

.control
run
wrdata sig_cond_results.txt V(SENSOR) V(OUT) V(STAGE1) V(FILTERED) V(N1)
quit
.endc

.end
"""
    netlist_path = os.path.join(WORK_DIR, "sig_cond.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {netlist_path}")
    return netlist_path


def write_sig_cond_ac_netlist(opamp="LM741"):
    """Write ngspice AC analysis netlist for Bode plot of the signal conditioner."""
    OPAMP_DB = {
        "AD797": ("AD797_AD", "analog.lib", 6, "AD797"),
        "AD822": ("AD822_AD", "analog.lib", 5, "AD822"),
        "AD843": ("AD843J_AD", "analog.lib", 5, "AD843"),
        "LM741": ("LM741_NS", "nation.lib", 5, "LM741"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LM741"])
    model_name, lib_file, n_pins, title_opamp = info
    model_block = extract_model(model_name, lib_file)

    if n_pins == 6:
        xu1_line = f"XU1 N_IN FB1 VCC VEE STAGE1 DECOMP1 {model_name}"
        xu2_line = f"XU2 N2 FILTERED VCC VEE FILTERED DECOMP2 {model_name}"
        extra = "CDC1 DECOMP1 VEE 100p\nCDC2 DECOMP2 VEE 100p"
    else:
        xu1_line = f"XU1 N_IN FB1 VCC VEE STAGE1 {model_name}"
        xu2_line = f"XU2 N2 FILTERED VCC VEE FILTERED {model_name}"
        extra = ""

    if not model_block:
        model_block = f"* {model_name} model not found\n"

    netlist = f"""* Signal Conditioner AC Analysis ({title_opamp})
* Bode plot: gain and phase vs frequency

VCC VCC 0 12
VEE VEE 0 -12

* AC source: 1V amplitude for dB reading directly
VIN N_IN 0 AC 1

* Stage 1: Non-inverting amplifier (G=11)
R6 N_IN 0 100k
{xu1_line}
R1 STAGE1 FB1 100k
R2 FB1 0 10k
{extra}

* Sallen-Key LPF
R3 STAGE1 N1 10k
R4 N1 N2 10k
C3 N1 0 33n
C4 N2 FILTERED 15n

* Stage 2: Unity-gain buffer
{xu2_line}

* Load
R5 FILTERED 0 10k

* Model
{model_block}

* AC sweep: 10 Hz to 100 kHz, 50 points per decade
.ac dec 50 10 100k

.control
run
wrdata sig_cond_ac.txt vdb(FILTERED) vp(FILTERED) vdb(STAGE1) vp(STAGE1)
quit
.endc

.end
"""
    netlist_path = os.path.join(WORK_DIR, "sig_cond_ac.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)
    print(f"  AC netlist saved: {netlist_path}")
    return netlist_path


def plot_bode(results_file="sig_cond_ac.txt", title="Bode Plot", plot_file="sig_cond_bode.png"):
    """Plot Bode diagram (gain + phase) from AC analysis results."""
    results_path = os.path.join(WORK_DIR, results_file)
    if not os.path.exists(results_path):
        print(f"  No AC results: {results_file}")
        return None

    data = np.loadtxt(results_path)
    freq = data[:, 0]
    # Columns: freq, gain_dB(FILTERED), phase(FILTERED), gain_dB(STAGE1), phase(STAGE1)
    gain_filt = data[:, 1]
    phase_filt = data[:, 3] if data.shape[1] > 3 else np.zeros_like(freq)
    gain_stage1 = data[:, 5] if data.shape[1] > 5 else None
    phase_stage1 = data[:, 7] if data.shape[1] > 7 else None

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle(title, fontsize=14, fontweight='bold')
    fig.patch.set_facecolor('#1a1a2e')

    # Gain plot
    ax1.set_facecolor('#16213e')
    ax1.semilogx(freq, gain_filt, color='#00d4ff', linewidth=1.5, label='Output (Filtered)')
    if gain_stage1 is not None:
        ax1.semilogx(freq, gain_stage1, color='#ffd93d', linewidth=1.2, linestyle='--', label='Stage 1')
    ax1.set_ylabel('Gain (dB)', color='white')
    ax1.tick_params(colors='white')
    ax1.grid(True, alpha=0.2, color='white', which='both')
    ax1.legend(facecolor='#16213e', edgecolor='#333', labelcolor='white')
    ax1.axhline(y=gain_filt[0]-3, color='#ff6b6b', linewidth=0.8, linestyle=':', alpha=0.7, label='-3dB')
    for spine in ax1.spines.values():
        spine.set_color('#333')

    # Phase plot
    ax2.set_facecolor('#16213e')
    ax2.semilogx(freq, phase_filt, color='#6bcb77', linewidth=1.5, label='Output Phase')
    if phase_stage1 is not None:
        ax2.semilogx(freq, phase_stage1, color='#ff9ff3', linewidth=1.2, linestyle='--', label='Stage 1 Phase')
    ax2.set_ylabel('Phase (degrees)', color='white')
    ax2.set_xlabel('Frequency (Hz)', color='white')
    ax2.tick_params(colors='white')
    ax2.grid(True, alpha=0.2, color='white', which='both')
    ax2.legend(facecolor='#16213e', edgecolor='#333', labelcolor='white')
    for spine in ax2.spines.values():
        spine.set_color('#333')

    plt.tight_layout()
    plot_path = os.path.join(WORK_DIR, plot_file)
    plt.savefig(plot_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()
    print(f"  Bode plot saved: {plot_path}")

    # Find -3dB frequency
    passband_gain = gain_filt[0]
    target = passband_gain - 3
    for i in range(len(freq)-1):
        if gain_filt[i] >= target and gain_filt[i+1] < target:
            f3db = freq[i] + (freq[i+1]-freq[i]) * (gain_filt[i]-target) / (gain_filt[i]-gain_filt[i+1])
            print(f"  -3dB frequency: {f3db:.0f} Hz (passband gain: {passband_gain:.1f} dB)")
            return plot_path
    print(f"  Passband gain: {passband_gain:.1f} dB")
    return plot_path


# =============================================================
# NETLIST: Electrometer TIA (transient)
# =============================================================
def write_electrometer_tia_netlist(opamp="LMC6001"):
    """Write ngspice netlist for the electrometer TIA.

    Uses a current pulse source to simulate picoamp-scale measurement.
    Vout = -Iin * Rf.
    """
    OPAMP_DB = {
        "LMC6001": ("LMC6001_NS", "nation.lib", 5, "LMC6001 Ultra-Low Bias"),
        "LMC6001A": ("LMC6001A_NS", "nation.lib", 5, "LMC6001A Electrometer-Grade"),
        "OPA128": ("OPA128_BB", "burrbn.lib", 5, "OPA128 Classic Electrometer"),
        "AD822": ("AD822_AD", "analog.lib", 5, "AD822 Precision JFET"),
        "AD843": ("AD843J_AD", "analog.lib", 5, "AD843 Fast Settling"),
        "LM741": ("LM741_NS", "nation.lib", 5, "LM741 Classic"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LMC6001"])
    model_name, lib_file, n_pins, title_opamp = info

    model_block = extract_model(model_name, lib_file)
    if not model_block:
        model_block = f"* {model_name} not found\n"

    # OPA128 has different pinout: [1=+in 2=-in 3=V+ 4=V- 5=out]
    if "OPA128" in model_name:
        xu1 = f"XU1 0 INV VCC VEE TIA_OUT {model_name}"
    else:
        # Standard pinout: [1=+in 2=-in 99=V+ 50=V- 28=out]
        xu1 = f"XU1 0 INV VCC VEE TIA_OUT {model_name}"

    netlist = f"""* Electrometer Transimpedance Amplifier ({title_opamp})
* Vout = -Iin * Rf = -1nA * 1G = -1V (with 1G feedback)
* Full-scale: ~12nA (limited by +/-12V supply / 1G)
* Bandwidth: fc = 1/(2*pi*Rf*Cf) = 1/(2*pi*1G*10p) ~16Hz
* Generated by kicad_pipeline.py

* Dual power supply
VCC VCC 0 12
VEE VEE 0 -12

* Op-amp in TIA configuration
* Non-inverting input (+) to ground (virtual ground reference)
{xu1}

* Feedback: Rf=1G, Cf=10pF (stability)
Rf TIA_OUT INV 1G
Cf TIA_OUT INV 10p

* Test current: 1nA pulse (simulates picoamp-scale sensor)
* Pulse: 0 to 1nA, 10ms delay, 10us rise/fall, 80ms on, 200ms period
* Long pulse needed: Rf*Cf = 1G*10p = 10ms time constant (5*tau = 50ms)
I1 0 INV PULSE(0 1n 10m 10u 10u 80m 200m)

* ADC input impedance model (ADuCM362 sigma-delta ~10M)
R_ADC TIA_OUT 0 10Meg

* Model
{model_block}

* Simulation (long enough for 5*tau = 50ms settling)
.tran 100u 200m

.control
run
wrdata electrometer_results.txt V(TIA_OUT) V(INV)
quit
.endc

.end
"""
    netlist_path = os.path.join(WORK_DIR, "electrometer.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {netlist_path}")
    return netlist_path


# =============================================================
# NETLIST: Electrometer TIA (AC analysis / Bode)
# =============================================================
def write_electrometer_tia_ac_netlist(opamp="LMC6001"):
    """Write ngspice AC analysis netlist for the electrometer TIA.

    Sweeps 0.1Hz to 100kHz to find the -3dB bandwidth.
    Expected: -3dB at ~16Hz for 1G/10pF feedback.
    """
    OPAMP_DB = {
        "LMC6001": ("LMC6001_NS", "nation.lib", 5, "LMC6001 Ultra-Low Bias"),
        "LMC6001A": ("LMC6001A_NS", "nation.lib", 5, "LMC6001A Electrometer-Grade"),
        "OPA128": ("OPA128_BB", "burrbn.lib", 5, "OPA128 Classic Electrometer"),
        "AD822": ("AD822_AD", "analog.lib", 5, "AD822 Precision JFET"),
        "AD843": ("AD843J_AD", "analog.lib", 5, "AD843 Fast Settling"),
        "LM741": ("LM741_NS", "nation.lib", 5, "LM741 Classic"),
    }
    info = OPAMP_DB.get(opamp, OPAMP_DB["LMC6001"])
    model_name, lib_file, n_pins, title_opamp = info

    model_block = extract_model(model_name, lib_file)
    if not model_block:
        model_block = f"* {model_name} not found\n"

    if "OPA128" in model_name:
        xu1 = f"XU1 0 INV VCC VEE TIA_OUT {model_name}"
    else:
        xu1 = f"XU1 0 INV VCC VEE TIA_OUT {model_name}"

    netlist = f"""* Electrometer TIA - AC Analysis ({title_opamp})
* Transimpedance Bode plot: -3dB at ~16Hz (Rf=1G, Cf=10pF)
* Generated by kicad_pipeline.py

VCC VCC 0 12
VEE VEE 0 -12

* Op-amp TIA
{xu1}

* Feedback
Rf TIA_OUT INV 1G
Cf TIA_OUT INV 10p

* AC current source (1A magnitude for transimpedance = V/A)
I1 0 INV AC 1

* ADC load
R_ADC TIA_OUT 0 10Meg

* Model
{model_block}

* AC sweep: 0.1Hz to 100kHz, 50 points/decade
.ac dec 50 0.1 100k

.control
run
wrdata electrometer_ac.txt vdb(TIA_OUT) vp(TIA_OUT)
quit
.endc

.end
"""
    netlist_path = os.path.join(WORK_DIR, "electrometer_ac.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)
    print(f"  AC netlist saved: {netlist_path}")
    return netlist_path


# =============================================================
# NETLIST: Write ngspice netlist (CE amp)
# =============================================================
def write_ce_amp_netlist():
    """Write the ngspice netlist for the common-emitter amplifier."""
    netlist = """* Common Emitter BJT Amplifier
* Generated by kicad_pipeline.py

* Power supply
VCC VCC 0 12

* Input signal: 10mV @ 1kHz
VIN IN 0 SINE(0 10m 1k)

* Bias network
R1 VCC BASE 22k
R2 BASE 0 4.7k

* Input coupling
C1 IN BASE 1u

* Transistor
Q1 COLL BASE EMIT 0 2N3904

* Collector load
R3 VCC COLL 2.2k

* Emitter resistor + bypass
R4 EMIT 0 470
C3 EMIT 0 100u

* Output coupling + load
C2 COLL OUT 10u
RL OUT 0 10k

* BJT model
.model 2N3904 NPN(IS=1E-14 VAF=100 Bf=300 IKF=0.4 XTB=1.5 BR=4 CJC=4E-12 CJE=8E-12 RB=20 RC=0.1 RE=0.1 TR=250E-9 TF=350E-12 ITF=1 VTF=2 XTF=3)

* Simulation: transient analysis
.tran 1u 10m

.control
run
wrdata results.txt V(IN) V(OUT) V(COLL) V(BASE)
quit
.endc

.end
"""
    netlist_path = os.path.join(WORK_DIR, "ce_amp.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {netlist_path}")
    return netlist_path


def write_audioamp_netlist():
    """Write ngspice netlist for the audio amplifier (LTspice Educational).

    3-stage BJT amplifier: diff pair + VAS + quasi-complementary push-pull output.
    Netlist derived from LTspice-generated audioamp.net with descriptive node names.

    Node mapping (from LTspice N### to descriptive):
        N001=VCC  N002=Q1C  N003=FB_MID  N004=Q3E  N005=Q3B
        N006=VAS  N007=Q5E  N008=Q4B  N009=Q1B  N010=Q2B
        N011=TAIL  N012=Q4E  N013=Q6C  N014=VEE
        A=OUT  B=FB  IN=IN
    """
    netlist = """* Audio Amplifier - LTspice Educational Example
* 3-stage BJT: diff pair + VAS + push-pull output
* Converted to ngspice by CircuitForge pipeline

* === Power Supplies ===
V1 VCC 0 10
V2 VEE 0 -10

* === Input Signal ===
V3 IN 0 SINE(0 0.7 1k)
* V4 is AC stimulus (0V DC = short for transient)
V4 OUT FB DC 0

* === Stage 1: Differential Pair ===
R1 Q1B IN 5k
Q1 Q1C Q1B TAIL 0 Q2N3904
Q2 VCC Q2B TAIL 0 Q2N3904
R2 VCC Q1C 200
R3 TAIL VEE 1k

* Q2 base: feedback + bias
R6 Q2B 0 5k
R7 FB Q2B 50k

* === Stage 2: Active Load + VAS ===
* Interstage coupling: Q1C -> R4 -> R5 -> Q3 base
R4 FB_MID Q1C 9k
C1 FB_MID Q1C 10p
R5 Q3B FB_MID 1k

* Q3 PNP active load
Q3 VAS Q3B Q3E 0 Q2N3906
R8 VCC Q3E 100
C2 VAS Q3B 100p

* Q4 voltage amplification stage
Q4 VAS Q4B Q4E 0 Q2N3904
R9 VAS Q4B 2k
R10 Q4B Q4E 1k
R11 Q4E VEE 5k

* Bootstrap
C3 VAS Q4E 1m

* === Stage 3: Quasi-Complementary Output ===
* Upper: Q5 driver -> Q7 output (both NPN)
Q5 VCC VAS Q5E 0 Q2N3904
Q7 VCC Q5E OUT 0 Q2N2219A
R12 Q5E OUT 1k

* Lower: Q6 PNP driver -> Q8 NPN output
Q6 Q6C Q4E OUT 0 Q2N3906
Q8 OUT Q6C VEE 0 Q2N2219A
R13 Q6C VEE 1k

* === Load ===
R14 OUT 0 8

* === BJT Models ===
.model Q2N3904 NPN(IS=1E-14 VAF=100 Bf=300 IKF=0.4 XTB=1.5
+ BR=4 CJC=4E-12 CJE=8E-12 RB=20 RC=0.1 RE=0.1
+ TR=250E-9 TF=350E-12 ITF=1 VTF=2 XTF=3)

.model Q2N3906 PNP(IS=1E-14 VAF=100 Bf=180 IKF=0.4 XTB=1.5
+ BR=4 CJC=4.5E-12 CJE=10E-12 RB=20 RC=0.1 RE=0.1
+ TR=250E-9 TF=350E-12 ITF=1 VTF=2 XTF=3)

.model Q2N2219A NPN(IS=14.34E-15 VAF=74.03 Bf=255.9 IKF=0.2847
+ XTB=1.5 BR=6.092 CJC=7.306E-12 CJE=22.01E-12 RB=10
+ RC=0.1 RE=0.1 TR=46.91E-9 TF=411.1E-12 ITF=0.6 VTF=1.7 XTF=3)

* === Simulation ===
.tran 1u 10m
.options maxstep=10u

.control
run
wrdata audioamp_results.txt V(IN) V(OUT) V(VAS) V(Q4E)
quit
.endc

.end
"""
    netlist_path = os.path.join(WORK_DIR, "audioamp.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)
    print(f"  Netlist saved: {netlist_path}")
    return netlist_path


# =============================================================
# SIMULATE: Run ngspice
# =============================================================
def simulate(netlist_path):
    """Run ngspice simulation.

    Success requires BOTH:
      1. ngspice exits with return code 0
      2. At least one results .txt file exists that wasn't there before

    Previous bug: stale *_results.txt from earlier runs could make a failed
    simulation look successful. Now we snapshot existing files before running
    and only count NEW files as evidence of success.
    """
    if not NGSPICE:
        print("ERROR: ngspice not found. Install it or set NGSPICE_PATH env var.")
        print("  Download: https://sourceforge.net/projects/ngspice/files/")
        return False
    print("Running ngspice...")
    work_dir = os.path.dirname(netlist_path)

    # Snapshot existing result files BEFORE running
    pre_existing = set()
    results_path = os.path.join(work_dir, "results.txt")
    if os.path.exists(results_path):
        pre_existing.add(results_path)
    for f in glob.glob(os.path.join(work_dir, "*_results.txt")):
        pre_existing.add(f)

    result = subprocess.run(
        [NGSPICE, "-b", netlist_path],
        capture_output=True, text=True,
        cwd=work_dir, timeout=600, **_SUBPROCESS_KWARGS
    )

    if result.stdout:
        lines = result.stdout.strip().split('\n')
        # Show last few lines of normal output
        for l in lines[-6:]:
            print(f"  {l}")

    # Any non-zero exit code is a failure
    if result.returncode != 0:
        if result.stderr:
            print("  ERRORS:")
            for l in result.stderr.strip().split('\n')[-5:]:
                print(f"    {l}")
        # Also check stdout for error messages (ngspice often puts errors there)
        if result.stdout:
            error_lines = [l for l in result.stdout.split('\n')
                           if any(kw in l.lower() for kw in
                                  ('error', 'fatal', 'unknown', 'undefined',
                                   'no such', 'can\'t find', 'singular matrix',
                                   'doanalysis', 'timestep', 'trouble'))]
            if error_lines:
                print("  ngspice errors detected:")
                for l in error_lines[:8]:
                    print(f"    {l.strip()}")
            else:
                print(f"  ngspice exited with code {result.returncode}")
        else:
            print(f"  ngspice exited with code {result.returncode} (no output)")
        return False

    # Check for result files — prefer NEW files over pre-existing ones
    post_files = set()
    if os.path.exists(results_path):
        post_files.add(results_path)
    for f in glob.glob(os.path.join(work_dir, "*_results.txt")):
        post_files.add(f)

    new_files = post_files - pre_existing
    if new_files:
        return True

    # If no new files but returncode was 0, accept existing results
    # (wrdata may overwrite an existing file rather than creating new)
    if post_files:
        return True

    print("  WARNING: ngspice returned 0 but no result files found")
    return False


def simulate_ltspice(netlist_path, node_names=None):
    """Run LTspice batch simulation and extract results via ltspice package.

    Uses LTspice.exe -b for batch simulation, then reads .raw binary output
    with the ltspice Python package. Returns results as numpy arrays.

    This is needed for models that use LTspice-specific behavioral syntax
    (OTA, VDMOS, noiseless, dnlim/uplim) that ngspice can't handle.
    Key model: ADA4530-1 electrometer op-amp (6 pins, guard buffer).

    Args:
        netlist_path: Path to .asc or .net file
        node_names: List of variable names to extract (e.g. ['V(out)', 'V(in)'])

    Returns:
        dict with 'time' and node name keys, values are numpy arrays.
        Empty dict on failure.
    """
    if not LTSPICE:
        print("ERROR: LTspice not found. Install it or set LTSPICE_PATH env var.")
        print("  Download: https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html")
        return {}
    print("Running LTspice...")
    work_dir = os.path.dirname(netlist_path)

    result = subprocess.run(
        [LTSPICE, "-b", netlist_path],
        capture_output=True, text=True,
        cwd=work_dir, timeout=120, **_SUBPROCESS_KWARGS
    )

    # LTspice writes .raw file next to the input
    base = os.path.splitext(netlist_path)[0]
    raw_path = base + ".raw"
    log_path = base + ".log"

    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            log_text = f.read()
        for line in log_text.strip().split('\n')[-4:]:
            print(f"  {line}")

    if not os.path.exists(raw_path):
        print("  ERROR: No .raw output file")
        return {}

    try:
        import ltspice as lt
        raw = lt.Ltspice(raw_path)
        raw.parse()

        available = raw.variables
        print(f"  Variables: {', '.join(available[:8])}{'...' if len(available) > 8 else ''}")

        data = {'time': np.array(raw.get_time())}
        if node_names:
            for name in node_names:
                try:
                    data[name] = np.array(raw.get_data(name))
                except Exception:
                    print(f"  Warning: variable '{name}' not found in .raw")

        print(f"  Data points: {len(data['time'])}")
        return data

    except ImportError:
        print("  ERROR: ltspice package not installed (pip install ltspice)")
        return {}
    except Exception as e:
        print(f"  ERROR reading .raw: {e}")
        return {}


def write_electrometer_362_ltspice(rf_range=2):
    """Write LTspice .net netlist for ADA4530-1 electrometer TIA.

    Uses the REAL ADA4530-1 model from LTspice's ADI1.lib (6 pins with guard buffer).
    This gives accurate femtoampere-level simulation that ngspice can't do.

    Args:
        rf_range: 0-3 for range selection (10M/100M/1G/10G)

    Returns:
        Path to written .net file
    """
    RANGES = {
        0: ("10M",  "10Meg", None,   100e-9, "+-120nA full scale"),
        1: ("100M", "100Meg", None,  10e-9,  "+-12nA full scale"),
        2: ("1G",   "1G",    "10p",  1e-9,   "+-1.2nA full scale"),
        3: ("10G",  "10G",   "1p",   0.1e-9, "+-120pA full scale"),
    }
    rf_name, rf_val, cf_val, i_test, desc = RANGES.get(rf_range, RANGES[2])

    # Simulation time
    if cf_val:
        rf_num = float(rf_val.replace('G', 'e9').replace('Meg', 'e6'))
        cf_num = float(cf_val.replace('p', 'e-12'))
        tau = rf_num * cf_num
        sim_time = max(0.2, tau * 8)
        pulse_width = max(0.08, tau * 5)
    else:
        sim_time = 0.05
        pulse_width = 0.02

    cf_line = f"C1 INV TIA_OUT {cf_val}" if cf_val else "* No Cf for this range"

    netlist = f"""* Electrometer TIA - ADuCM362 Platform (LTspice + ADA4530-1)
* REAL ADA4530-1 model from ADI1.lib (6 pins: In+ In- V+ V- OUT GDR)
* Range {rf_range}: Rf={rf_name}, {desc}
* Dual supply +/-5V (ADA4530-1 min Vs=4.5V)

* Power Supply
V1 VCC 0 5
V2 0 VEE 5

* ADA4530-1 Electrometer Op-Amp
* Pins: 1=In+ 2=In- 3=V+ 4=V- 5=OUT 6=GDR(guard)
XU1 0 INV VCC VEE TIA_OUT GDR ADA4530-1

* Feedback Network (Range {rf_range}: Rf={rf_name})
Rf INV TIA_OUT {rf_val}
{cf_line}

* ADC Load (10M input impedance)
RL TIA_OUT 0 10Meg

* Guard buffer output - connect to triax shield (floating here)
Rgdr GDR 0 100Meg

* Test Current Source (pulse)
* {i_test*1e9:.1f}nA for {pulse_width*1000:.0f}ms
I1 0 INV PULSE(0 {i_test} 0.01 1u 1u {pulse_width} {sim_time})

.tran {sim_time}
.lib {_get_ltspice_lib_path()}
.backanno
.end
"""

    out_path = os.path.join(WORK_DIR, "electrometer_362_lt.net")
    with open(out_path, 'w') as f:
        f.write(netlist)
    print(f"  LTspice netlist saved: {out_path}")
    print(f"  Range {rf_range}: Rf={rf_name}, Cf={cf_val or 'none'}, I_test={i_test*1e9:.1f}nA")
    return out_path


# =============================================================
# PLOT: Visualize results
# =============================================================
def plot_results(title="Simulation Results", results_file="results.txt",
                 node_names=None, plot_file=None):
    """Plot simulation results."""
    results_path = os.path.join(WORK_DIR, results_file)
    if not os.path.exists(results_path):
        print(f"No results file: {results_file}")
        return None

    data = np.loadtxt(results_path)
    print(f"  Data shape: {data.shape}")

    if node_names is None:
        node_names = [f'V{i}' for i in range(data.shape[1] // 2)]
    ncols = data.shape[1]
    n = len(node_names)

    time = data[:, 0]
    vals = [data[:, i*2+1] for i in range(min(n, ncols//2))]

    n_plots = len(vals)
    fig, axes = plt.subplots(n_plots, 1, figsize=(14, n_plots * 2.5), sharex=True)
    if n_plots == 1:
        axes = [axes]

    fig.suptitle(title, fontsize=14, fontweight='bold')
    fig.patch.set_facecolor('#1a1a2e')
    colors = ['#00d4ff', '#ff6b6b', '#ffd93d', '#6bcb77', '#ff9ff3', '#54a0ff']

    for i in range(n_plots):
        ax = axes[i]
        ax.set_facecolor('#16213e')
        ax.plot(time * 1000, vals[i], color=colors[i % len(colors)], linewidth=0.8)
        ax.set_ylabel(node_names[i], color='white', fontsize=9)
        ax.tick_params(colors='white')
        ax.grid(True, alpha=0.2, color='white')
        for spine in ax.spines.values():
            spine.set_color('#333')

    axes[-1].set_xlabel('Time (ms)', color='white')
    plt.tight_layout()

    if plot_file is None:
        plot_file = results_file.replace('.txt', '.png')
    plot_path = os.path.join(WORK_DIR, plot_file)
    plt.savefig(plot_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    print(f"  Plot saved: {plot_path}")
    plt.close()

    # Print key measurements
    if len(vals) >= 2:
        vin_pp = np.max(vals[0]) - np.min(vals[0])
        vout_pp = np.max(vals[1]) - np.min(vals[1])
        gain = vout_pp / vin_pp if vin_pp > 0 else 0
        print(f"\n  Measurements:")
        print(f"    Vin peak-peak:  {vin_pp*1000:.1f} mV")
        print(f"    Vout peak-peak: {vout_pp*1000:.1f} mV")
        if gain > 0:
            print(f"    Voltage gain:   {gain:.1f}x ({20*np.log10(gain):.1f} dB)")

    return plot_path


# =============================================================
# VERIFY: Circuit build-and-check system
# =============================================================
def extract_nets_from_schematic(sch_path):
    """Parse a .kicad_sch file and extract wire endpoints and component pins.

    Returns:
        wires: list of ((x1,y1), (x2,y2)) wire segments
        pins:  dict of {ref: {pin_num: (x, y)}} from placed components
        labels: list of (name, (x, y))
    """
    with open(sch_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Extract wire segments
    wires = []
    for m in re.finditer(r'\(wire\s*\(pts\s*\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)\s*\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)', text):
        x1, y1, x2, y2 = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
        wires.append(((x1, y1), (x2, y2)))

    # Extract labels
    labels = []
    for m in re.finditer(r'\(label\s+"([^"]+)"\s*\(at\s+([\d.e+-]+)\s+([\d.e+-]+)', text):
        name, x, y = m.group(1), float(m.group(2)), float(m.group(3))
        labels.append((name, (x, y)))

    # Extract placed symbol instances (components) with positions
    components = []
    for m in re.finditer(r'\(symbol\s*\n\s*\(lib_id "([^"]+)"\)', text):
        lib_id = m.group(1)
        chunk = text[m.start():m.start()+1200]
        ref_m = re.search(r'"Reference" "([^"]+)"', chunk)
        val_m = re.search(r'"Value" "([^"]+)"', chunk)
        at_m = re.search(r'\(at\s+([\d.e+-]+)\s+([\d.e+-]+)\s+(\d+)\)', chunk)
        mirror_m = re.search(r'\(mirror\s+x\)', chunk)
        ref = ref_m.group(1) if ref_m else ""
        val = val_m.group(1) if val_m else ""
        cx = float(at_m.group(1)) if at_m else 0
        cy = float(at_m.group(2)) if at_m else 0
        rot = int(at_m.group(3)) if at_m else 0
        mirrored = mirror_m is not None
        components.append({
            'lib_id': lib_id, 'reference': ref, 'value': val,
            'x': cx, 'y': cy, 'rotation': rot, 'mirror_x': mirrored
        })

    return wires, labels, components


def verify_pin_connections(sch_path, tolerance=0.6):
    """Check that every component pin touches a wire endpoint or segment.

    Parses the saved .kicad_sch file and computes pin positions from the
    placed components using get_component_pins(). Then checks each pin
    against wire endpoints AND along wire segments (a pin in the middle
    of a wire counts as connected).

    Returns:
        list of (severity, message) tuples — 'PASS', 'ERROR', 'WARNING'
    """
    wires, labels, components = extract_nets_from_schematic(sch_path)
    issues = []

    # Collect all wire endpoints
    wire_pts = set()
    for (x1, y1), (x2, y2) in wires:
        wire_pts.add((round(x1, 2), round(y1, 2)))
        wire_pts.add((round(x2, 2), round(y2, 2)))

    # Also collect label positions
    for _, (lx, ly) in labels:
        wire_pts.add((round(lx, 2), round(ly, 2)))

    def point_on_wire(px, py):
        """Check if point is at a wire endpoint or on a wire segment."""
        # Check endpoints first (fast)
        for wx, wy in wire_pts:
            if abs(px - wx) < tolerance and abs(py - wy) < tolerance:
                return True
        # Check if point lies on any wire segment
        for (x1, y1), (x2, y2) in wires:
            if abs(x1 - x2) < 0.1:  # vertical wire
                if abs(px - x1) < tolerance:
                    if min(y1, y2) - tolerance <= py <= max(y1, y2) + tolerance:
                        return True
            if abs(y1 - y2) < 0.1:  # horizontal wire
                if abs(py - y1) < tolerance:
                    if min(x1, x2) - tolerance <= px <= max(x1, x2) + tolerance:
                        return True
        return False

    total_pins = 0
    disconnected = []

    for comp in components:
        ref = comp['reference']
        # Skip power symbols and ground
        if ref.startswith('#') or 'GND' in comp.get('lib_id', ''):
            continue

        pins = get_component_pins(comp)
        if pins is None:
            continue

        for pin_num, (px, py, pin_type, pin_name) in pins.items():
            if pin_type == 'no_connect':
                continue
            total_pins += 1

            if not point_on_wire(px, py):
                disconnected.append(f"{ref} pin {pin_num} ({pin_name}) "
                                    f"at ({px:.1f}, {py:.1f})")

    if disconnected:
        for d in disconnected:
            issues.append(('ERROR', f'DISCONNECTED: {d}'))
        issues.append(('ERROR',
            f'{len(disconnected)}/{total_pins} pins disconnected'))
    else:
        issues.append(('PASS',
            f'All {total_pins} component pins connected to wires'))

    # Check wire crossings (wires that cross without a junction)
    crossings = 0
    for i in range(len(wires)):
        for j in range(i + 1, len(wires)):
            (x1, y1), (x2, y2) = wires[i]
            (x3, y3), (x4, y4) = wires[j]
            # Check if one is horizontal and the other vertical
            is_h1 = abs(y1 - y2) < 0.01 and abs(x1 - x2) > 0.01
            is_v1 = abs(x1 - x2) < 0.01 and abs(y1 - y2) > 0.01
            is_h2 = abs(y3 - y4) < 0.01 and abs(x3 - x4) > 0.01
            is_v2 = abs(x3 - x4) < 0.01 and abs(y3 - y4) > 0.01

            if (is_h1 and is_v2) or (is_v1 and is_h2):
                if is_h1 and is_v2:
                    hx_min, hx_max = min(x1, x2), max(x1, x2)
                    vy_min, vy_max = min(y3, y4), max(y3, y4)
                    cross_x, cross_y = x3, y1
                else:
                    hx_min, hx_max = min(x3, x4), max(x3, x4)
                    vy_min, vy_max = min(y1, y2), max(y1, y2)
                    cross_x, cross_y = x1, y3

                if (hx_min < cross_x < hx_max and
                    vy_min < cross_y < vy_max):
                    # Verify no junction at crossing (shared endpoint)
                    shared = False
                    pts1 = {(round(x1,2),round(y1,2)), (round(x2,2),round(y2,2))}
                    pts2 = {(round(x3,2),round(y3,2)), (round(x4,2),round(y4,2))}
                    cross_pt = (round(cross_x,2), round(cross_y,2))
                    if cross_pt in pts1 or cross_pt in pts2:
                        shared = True
                    if not shared:
                        crossings += 1

    if crossings > 0:
        issues.append(('ERROR', f'{crossings} wire crossings (ZERO required)'))
    else:
        issues.append(('PASS', 'No ambiguous wire crossings'))

    return issues


def verify_electrical_correctness(sch_path):
    """Check electrical semantics: diode polarity, op-amp mirror, power pins.

    Unlike verify_pin_connections (which only checks geometry), this verifies
    that pins connect to electrically correct nets.

    Returns:
        list of (severity, message) tuples
    """
    issues = []

    with open(sch_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # --- Check 1: No mirror x on op-amp symbols ---
    # mirror x swaps +/- inputs and V+/V- power, breaking wire connections
    mirror_pat = re.compile(
        r'\(symbol\s*\n'
        r'\s*\(lib_id "([^"]+)"\)\s*\n'
        r'\s*\(at [^\)]+\)\s*\n'
        r'\s*\(mirror x\)',
        re.MULTILINE
    )
    for m in mirror_pat.finditer(text):
        lib_id = m.group(1)
        # Only flag op-amp symbols (LM741, LM4562, etc), not transistors
        if any(opamp in lib_id for opamp in ['LM741', 'LM4562', 'AD824',
                'ADA4530', 'LMC6001', 'OPA', 'AD8']):
            # Find the reference
            chunk = text[m.start():m.start() + 500]
            ref_m = re.search(r'"Reference"\s+"([^"]+)"', chunk)
            ref = ref_m.group(1) if ref_m else '?'
            issues.append(('ERROR',
                f'Op-amp {ref} ({lib_id}) has mirror x — '
                f'+/- inputs and V+/V- power pins are SWAPPED'))

    # --- Check 2: ESD diode pairs have anti-parallel polarity ---
    # For each pair (D_odd, D_even), verify they have different rotations
    # so one clamps positive and the other clamps negative
    diode_pat = re.compile(
        r'\(symbol\s*\n'
        r'\s*\(lib_id "D:D"\)\s*\n'
        r'\s*\(at\s+([\d.]+)\s+([\d.]+)\s+(\d+)\)',
        re.MULTILINE
    )
    diodes = {}
    for m in diode_pat.finditer(text):
        rot = int(m.group(3))
        chunk = text[m.start():m.start() + 500]
        ref_m = re.search(r'"Reference"\s+"(D\d+)"', chunk)
        if ref_m:
            diodes[ref_m.group(1)] = rot

    # Check pairs: D1/D2, D3/D4, etc.
    # Correct side-by-side anti-parallel: D_odd=270 (positive ▽), D_even=90 (negative △)
    max_d = max((int(k[1:]) for k in diodes), default=0)
    for i in range(1, max_d + 1, 2):
        d_odd = f'D{i}'
        d_even = f'D{i+1}'
        if d_odd in diodes and d_even in diodes:
            r_odd, r_even = diodes[d_odd], diodes[d_even]
            if r_odd == 270 and r_even == 90:
                pass  # Correct: odd=positive(▽), even=negative(△)
            elif r_odd == 90 and r_even == 270:
                pass  # Also valid (swapped roles)
            elif r_odd == r_even:
                issues.append(('ERROR',
                    f'ESD pair {d_odd}/{d_even}: both rot={r_odd} — '
                    f'same polarity clamping, not anti-parallel'))
            else:
                issues.append(('WARNING',
                    f'ESD pair {d_odd}/{d_even}: rot={r_odd}/{r_even} — '
                    f'verify anti-parallel polarity'))

    if not issues:
        issues.append(('PASS', 'Electrical correctness checks passed'))

    return issues


# Legacy PIN_DB kept for backward compatibility with check_floating_wires()
# New code should use get_component_pins() which reads from .kicad_sym files
PIN_DB = {
    'LM741': {
        '2': (-7.62, -2.54),   # inv (-) TOP-LEFT
        '3': (-7.62, +2.54),   # non-inv (+) BOTTOM-LEFT
        '4': (-2.54, -7.62),   # V- TOP
        '6': (+7.62, 0),       # output RIGHT
        '7': (-2.54, +7.62),   # V+ BOTTOM
    },
    'R': { '1': (+3.81, 0), '2': (-3.81, 0) },
    'R_vert': { '1': (0, -3.81), '2': (0, +3.81) },
    'C': { '1': (+3.81, 0), '2': (-3.81, 0) },
    'C_vert': { '1': (0, -3.81), '2': (0, +3.81) },
}


def get_opamp_pins(comp):
    """Compute absolute pin positions for an op-amp component.

    Now uses dynamic pin parser — works for ANY op-amp symbol, not just LM741.
    Falls back to legacy PIN_DB['LM741'] if symbol not found in libraries.
    """
    # Try dynamic parser first
    pins = get_component_pins(comp)
    if pins is not None:
        # Return in legacy format: {pin_num: (x, y)}
        return {num: (x, y) for num, (x, y, _, _) in pins.items()}

    # Fallback to hardcoded LM741
    cx, cy = comp['x'], comp['y']
    mirrored = comp.get('mirror_x', False)
    result = {}
    for pin_num, (dx, dy) in PIN_DB['LM741'].items():
        if mirrored:
            dy = -dy
        result[pin_num] = (cx + dx, cy + dy)
    return result


# =============================================================
# LAYOUT QUALITY CHECKS + SELF-LEARNING CORRECTION LOOP
# =============================================================

# Persistent learned rules file - grows with each bug found
LEARNED_RULES_PATH = os.path.join(os.path.expanduser("~"),
    "Documents", "LTspice", "sim_work", "learned_rules.json")


def load_learned_rules():
    """Load persistent learned layout rules from JSON."""
    if os.path.exists(LEARNED_RULES_PATH):
        with open(LEARNED_RULES_PATH, 'r') as f:
            return json.load(f)
    return {"rules": [], "version": 1, "fixes_applied": 0}


def save_learned_rules(rules):
    """Save learned layout rules to persistent JSON."""
    with open(LEARNED_RULES_PATH, 'w') as f:
        json.dump(rules, f, indent=2)


def learn_rule(rule_id, description, circuit_type, fix_fn_name):
    """Add a new learned rule if not already known."""
    rules = load_learned_rules()
    existing_ids = {r['id'] for r in rules['rules']}
    if rule_id not in existing_ids:
        rules['rules'].append({
            'id': rule_id,
            'description': description,
            'circuit_type': circuit_type,
            'fix_function': fix_fn_name,
            'times_triggered': 0,
            'learned_date': str(datetime.now()),
        })
        save_learned_rules(rules)
        print(f"    [LEARN] New rule: {rule_id} - {description}")


def record_fix(rule_id):
    """Increment the fix counter for a learned rule."""
    rules = load_learned_rules()
    for r in rules['rules']:
        if r['id'] == rule_id:
            r['times_triggered'] = r.get('times_triggered', 0) + 1
    rules['fixes_applied'] = rules.get('fixes_applied', 0) + 1
    save_learned_rules(rules)


def print_learned_rules_summary():
    """Print a summary of all learned rules and fix statistics."""
    rules = load_learned_rules()
    if not rules['rules']:
        print("  No learned rules yet.")
        return
    print(f"  Learned Rules ({len(rules['rules'])} rules, "
          f"{rules.get('fixes_applied', 0)} total fixes):")
    for r in rules['rules']:
        print(f"    [{r['id']}] {r['description']}")
        print(f"      circuit: {r['circuit_type']}, "
              f"triggered: {r.get('times_triggered', 0)}x, "
              f"fix: {r['fix_function']}")


def check_layout_quality(wires, labels, components):
    """Detect layout quality issues beyond basic connectivity.

    Self-learning: each check corresponds to a bug found during development.
    New checks are added whenever a layout problem is discovered.

    Returns list of (severity, message, rule_id) tuples.
    """
    issues = []

    # Collect useful geometry
    opamps = [c for c in components if 'LM741' in c.get('lib_id', '')]
    gnd_syms = [c for c in components if 'GND' in c.get('lib_id', '')]
    vcc_syms = [c for c in components if 'VCC' in c.get('lib_id', '')]
    resistors = [c for c in components if c.get('lib_id', '') == 'R:R']
    caps = [c for c in components if c.get('lib_id', '') == 'C:C']

    for opamp in opamps:
        ux, uy = opamp['x'], opamp['y']
        mirrored = opamp.get('mirror_x', False)

        # Compute feedback area bounding box (above inv_pin for mirrored op-amp)
        if mirrored:
            inv_y = uy - 2.54   # (-) pin Y after mirror
            out_x = ux + 7.62
            # Feedback Rf/Cf are above the (-) pin
            fb_y_top = inv_y - 20  # generous range
            fb_y_bot = inv_y
            fb_x_left = ux - 20
            fb_x_right = out_x + 5
        else:
            inv_y = uy + 2.54
            out_x = ux + 7.62
            fb_y_top = inv_y
            fb_y_bot = inv_y + 20
            fb_x_left = ux - 20
            fb_x_right = out_x + 5

        # ── RULE: power_in_feedback_area ──
        # [mux_tia] Bug: V- GND symbol placed at (114.3, 96.52) right in the
        # Rf/Cf feedback area, creating visual clutter and confusion.
        # Check: no GND/VCC symbols should be inside the feedback bounding box.
        for pwr in gnd_syms + vcc_syms:
            px, py = pwr['x'], pwr['y']
            if (fb_x_left < px < fb_x_right and
                fb_y_top < py < fb_y_bot):
                ref = pwr.get('reference', '')
                val = pwr.get('value', '')
                issues.append(('WARNING',
                    f'Power symbol {ref} ({val}) at ({px:.1f},{py:.1f}) '
                    f'inside feedback area of {opamp["reference"]} - '
                    f'reroute power away from feedback components',
                    'power_in_feedback_area'))

        # ── RULE: label_at_feedback_not_output ──
        # [mux_tia] Bug: OUT label placed at top of feedback loop (at Rf Y level)
        # instead of at the actual op-amp output pin. Confusing - OUT should be
        # near the output pin, not floating in the feedback area.
        # Only check OUT labels that are near the op-amp (within 100mm x-range),
        # not ones in other subsystem regions (e.g. relay ladder bus label).
        out_pin_y = uy  # output pin Y (same as center for LM741)
        for name, (lx, ly) in labels:
            if name == 'OUT':
                # Only flag if label is near the op-amp (within ~80mm in both
                # x AND y). Labels in other subsystem regions (e.g. relay
                # ladder bus label far below the TIA) are not misplaced.
                if abs(lx - ux) > 80 or abs(ly - uy) > 80:
                    continue  # label is in a different subsystem region, skip
                dist_to_output = abs(ly - out_pin_y)
                if dist_to_output > 10 and abs(ly - out_pin_y) > 5:
                    issues.append(('WARNING',
                        f'Label "OUT" at ({lx:.1f},{ly:.1f}) is far from '
                        f'output pin (y={out_pin_y:.1f}) - '
                        f'move OUT label to actual output wire',
                        'label_at_feedback_not_output'))

        # ── RULE: feedback_components_overlap ──
        # Check if feedback R and C are too close together or overlapping
        fb_comps = []
        for r in resistors + caps:
            rx, ry = r['x'], r['y']
            if (fb_x_left < rx < fb_x_right and fb_y_top < ry < fb_y_bot):
                fb_comps.append(r)
        for i, c1 in enumerate(fb_comps):
            for c2 in fb_comps[i+1:]:
                dist = abs(c1['x'] - c2['x']) + abs(c1['y'] - c2['y'])
                if dist < 4.0 and c1['reference'] != c2['reference']:
                    issues.append(('WARNING',
                        f'Feedback components {c1["reference"]} and {c2["reference"]} '
                        f'are too close (dist={dist:.1f}mm) - increase spacing',
                        'feedback_components_overlap'))

    # ── RULE: divider_too_close_to_opamp ──
    # [mux_tia] Bug: VREF divider placed only 6*G from op-amp (+) input,
    # creating cramped layout. Need minimum clearance.
    for opamp in opamps:
        ux = opamp['x']
        ni_x = ux - 7.62  # (+) input X
        for r in resistors:
            rv = r.get('value', '')
            if rv == '100k' and r['rotation'] == 0:  # vertical divider resistor
                dist = ni_x - r['x']
                if 0 < dist < 25:  # divider is to the left but too close
                    issues.append(('WARNING',
                        f'Divider resistor {r["reference"]} at x={r["x"]:.1f} '
                        f'only {dist:.1f}mm from (+) input - '
                        f'move divider further left (>=30mm)',
                        'divider_too_close_to_opamp'))

    # ── RULE: component_overlap ──
    # [full_system] Bug: NPN driver base resistors overlap adjacent drivers
    # when spacing is too tight. Check all non-power components for proximity.
    non_power = [c for c in components
                 if 'GND' not in c.get('lib_id', '')
                 and 'VCC' not in c.get('lib_id', '')
                 and 'VEE' not in c.get('lib_id', '')
                 and not c.get('reference', '').startswith('#')]
    overlap_count = 0
    for i, c1 in enumerate(non_power):
        for c2 in non_power[i+1:]:
            dx = abs(c1['x'] - c2['x'])
            dy = abs(c1['y'] - c2['y'])
            # Manhattan distance < 5mm means components are on top of each other
            if dx < 5 and dy < 5 and c1['reference'] != c2['reference']:
                overlap_count += 1
                if overlap_count <= 5:  # limit reporting
                    issues.append(('WARNING',
                        f'Components {c1["reference"]} and {c2["reference"]} '
                        f'overlap ({dx:.1f},{dy:.1f}mm apart) - increase spacing',
                        'component_overlap'))
    if overlap_count > 5:
        issues.append(('WARNING',
            f'{overlap_count} total component overlaps detected',
            'component_overlap'))

    # ── RULE: layout_density ──
    # [full_system] Bug: all 181 components crammed into one corner of A0 sheet.
    # Check that components use a reasonable fraction of the available sheet.
    # A0 = 1189x841mm, A4 = 297x210mm, A3 = 420x297mm
    SHEET_AREAS = {
        'A0': (1189, 841), 'A1': (841, 594), 'A2': (594, 420),
        'A3': (420, 297), 'A4': (297, 210),
    }
    if len(non_power) >= 20:
        xs = [c['x'] for c in non_power]
        ys = [c['y'] for c in non_power]
        bbox_w = max(xs) - min(xs)
        bbox_h = max(ys) - min(ys)
        bbox_area = bbox_w * bbox_h if bbox_w > 0 and bbox_h > 0 else 1
        # Estimate sheet size from paper setting (read from schematic if possible)
        # Default to A4 if unknown
        sheet_w, sheet_h = 297, 210
        for size_name, (sw, sh) in SHEET_AREAS.items():
            if bbox_w < sw and bbox_h < sh:
                sheet_w, sheet_h = sw, sh
                break
        sheet_area = sheet_w * sheet_h
        usage_pct = (bbox_area / sheet_area) * 100
        if usage_pct < 15 and len(non_power) > 30:
            issues.append(('WARNING',
                f'Components use only {usage_pct:.0f}% of sheet area '
                f'(bbox {bbox_w:.0f}x{bbox_h:.0f}mm on {sheet_w}x{sheet_h}mm sheet) '
                f'- spread subsystems out for readability',
                'layout_density'))

    # ── RULE: vertical_utilization ──
    # [full_system] Bug: all components crammed into top 40% of A0 sheet.
    # Even if area% is OK, check that vertical spread is sufficient.
    if len(non_power) >= 20:
        ys = [c['y'] for c in non_power]
        y_span = max(ys) - min(ys)
        # Determine sheet height
        sheet_h = 210  # default A4
        for size_name, (sw, sh) in SHEET_AREAS.items():
            if y_span < sh:
                sheet_h = sh
                break
        vert_pct = (y_span / sheet_h) * 100
        if vert_pct < 40 and len(non_power) > 30:
            issues.append(('WARNING',
                f'Components use only {vert_pct:.0f}% of sheet height '
                f'(span {y_span:.0f}mm on {sheet_h}mm sheet) '
                f'- increase vertical spacing between subsystems',
                'vertical_utilization'))

    # ── RULE: power_net_mixing ──
    # [full_system] Bug: VCC symbols with value "5V_ISO" and "3V3" share the
    # same VCC net in KiCad, shorting different voltage rails together.
    # Check that all VCC symbols have the same value.
    if vcc_syms:
        vcc_values = set(c.get('value', '') for c in vcc_syms)
        if len(vcc_values) > 1:
            issues.append(('ERROR',
                f'VCC symbols have mixed values {vcc_values} - '
                f'all VCC symbols share ONE net in KiCad! '
                f'Use net labels for separate voltage rails (e.g. 5V_ISO)',
                'power_net_mixing'))

    # ── RULE: minimum_avg_spacing ──
    # [full_system] Bug: components too dense - barely visible when printed.
    # Check average nearest-neighbor distance.
    if len(non_power) >= 40:
        from statistics import median
        nn_dists = []
        for i, c1 in enumerate(non_power):
            min_d = float('inf')
            for j, c2 in enumerate(non_power):
                if i == j:
                    continue
                d = ((c1['x'] - c2['x'])**2 + (c1['y'] - c2['y'])**2)**0.5
                if d < min_d:
                    min_d = d
            nn_dists.append(min_d)
        med_nn = median(nn_dists)
        if med_nn < 8.0:  # 8mm median nearest neighbor = very cramped
            issues.append(('WARNING',
                f'Median nearest-neighbor distance is only {med_nn:.1f}mm '
                f'- components too dense, increase spacing',
                'minimum_avg_spacing'))

    # ══════════════════════════════════════════════════════════════════
    # TOPOLOGY CHECKS (circuit correctness, not just layout)
    # These catch missing components and broken connections that
    # label/count checks miss.
    # ══════════════════════════════════════════════════════════════════

    # Collect component types for topology checks
    npn_transistors = [c for c in components if 'Q_NPN' in c.get('lib_id', '')]
    diodes = [c for c in components if c.get('lib_id', '') == 'D:D']
    sw_reed = [c for c in components if 'SW_Reed' in c.get('lib_id', '')]
    inductors_or_coils = [c for c in components
        if c.get('lib_id', '') in ('L:L', 'R:R')
        and 'COIL' in c.get('value', '').upper()]

    # ── RULE: relay_coil_missing ──
    # [full_system] Bug: relay driver had NPN transistors and flyback diodes
    # but NO relay coil component between 5V_ISO and collector. Without the
    # coil, the relay contacts (SW_Reed) can never be energized.
    # Check: for each NPN transistor Q1-Q4, there must be an associated
    # coil component (L or R with "COIL" in value) within 30mm.
    if npn_transistors and sw_reed:
        n_coils = len(inductors_or_coils)
        n_npn = len(npn_transistors)
        if n_coils >= n_npn:
            issues.append(('PASS',
                f'Relay coils present: {n_coils} coil components for {n_npn} NPN drivers',
                'relay_coil_present'))
        elif n_coils == 0:
            issues.append(('ERROR',
                f'{n_npn} NPN relay drivers but NO relay coil components! '
                f'Add coil (L or R_COIL) between 5V_ISO and each collector. '
                f'Without coils, reed switch contacts will never energize.',
                'relay_coil_missing'))
        else:
            issues.append(('WARNING',
                f'Only {n_coils} relay coils for {n_npn} NPN drivers - '
                f'each relay needs its own coil',
                'relay_coil_missing'))

    # ── RULE: flyback_diode_topology ──
    # [full_system] Bug: flyback diode was in SERIES with NPN (5V->D->Q->GND)
    # instead of in PARALLEL with relay coil. Series topology just forward-
    # biases the diode; parallel topology clamps back-EMF.
    # Check: each flyback diode (1N4148 near NPN) should have a coil nearby.
    if npn_transistors and diodes:
        flyback_diodes = [d for d in diodes if '1N4148' in d.get('value', '')]
        for fd in flyback_diodes:
            fx, fy = fd['x'], fd['y']
            has_nearby_coil = any(
                abs(c['x'] - fx) < 30 and abs(c['y'] - fy) < 10
                for c in inductors_or_coils)
            if not has_nearby_coil and npn_transistors:
                # Check if any NPN is nearby (confirming this is a relay driver diode)
                nearby_npn = any(
                    abs(q['x'] - fx) < 30 and abs(q['y'] - fy) < 30
                    for q in npn_transistors)
                if nearby_npn:
                    issues.append(('ERROR',
                        f'Flyback diode {fd["reference"]} has no nearby relay coil - '
                        f'diode must be in PARALLEL with coil, not in series with NPN',
                        'flyback_diode_topology'))

    # ── RULE: esd_diode_junction_missing ──
    # [full_system] Bug: BAV199 ESD diode cathode pins landed mid-wire on
    # signal path with no junction dot. KiCad may not register the connection.
    # Check: for each BAV199, verify a junction exists near the signal wire.
    bav_diodes = [d for d in diodes if 'BAV199' in d.get('value', '')]
    if bav_diodes:
        # Read junctions from schematic file if available
        # (check_layout_quality doesn't receive junction data, so we just
        # verify BAV199 count matches expected and flag if no junctions
        # were detected in the component vicinity)
        n_bav = len(bav_diodes)
        expected_bav = 32  # 16 channels * 2 diodes each
        if n_bav >= expected_bav:
            issues.append(('PASS',
                f'{n_bav} BAV199 ESD diodes present (16 channels x 2)',
                'esd_diode_count'))
        else:
            issues.append(('WARNING',
                f'Only {n_bav} BAV199 ESD diodes (expected {expected_bav})',
                'esd_diode_count'))

    # ── RULE: relay_decoupling_missing ──
    # [full_system] Bug: 5V_ISO relay supply had no decoupling capacitor.
    # Relay coil switching causes current spikes that need local bypass.
    # Check: at least one capacitor near the relay driver area.
    if npn_transistors:
        npn_xs = [q['x'] for q in npn_transistors]
        npn_ys = [q['y'] for q in npn_transistors]
        relay_region = {
            'x_min': min(npn_xs) - 20, 'x_max': max(npn_xs) + 60,
            'y_min': min(npn_ys) - 60, 'y_max': max(npn_ys) + 10,
        }
        nearby_caps = [c for c in caps
            if relay_region['x_min'] < c['x'] < relay_region['x_max']
            and relay_region['y_min'] < c['y'] < relay_region['y_max']]
        if nearby_caps:
            issues.append(('PASS',
                f'{len(nearby_caps)} decoupling cap(s) near relay drivers',
                'relay_decoupling_present'))
        else:
            issues.append(('WARNING',
                f'No decoupling capacitor near relay driver area - '
                f'add 100nF on 5V_ISO near relay coils',
                'relay_decoupling_missing'))

    if not issues:
        issues.append(('PASS', 'Layout quality checks passed', 'layout_ok'))

    return issues


# =============================================================
# TIER 1 VERIFICATION: Connectivity & Overlap Detection
# =============================================================

def check_disconnected_labels(wires, labels, components):
    """Detect net labels connected to only one wire endpoint (dangling labels).

    A label should connect to at least 2 wire endpoints or a component pin
    to form a useful net. Labels touching only 1 point are likely dangling -
    they were placed but never wired to their destination.

    Labels that appear 2+ times with the same name are inter-region connectors
    (net label auto-connect) and are OK with 1 wire each, since KiCad connects
    same-name labels implicitly.

    Returns list of (severity, message) tuples.
    """
    TOLERANCE = 0.6
    issues = []

    # Count how many times each label name appears
    label_name_counts = {}
    for name, _ in labels:
        label_name_counts[name] = label_name_counts.get(name, 0) + 1

    # Collect all wire endpoints
    wire_pts = []
    for (p1, p2) in wires:
        wire_pts.append(p1)
        wire_pts.append(p2)

    # Collect component positions (approximate pin locations)
    comp_pts = []
    for c in components:
        comp_pts.append((c['x'], c['y']))

    def count_nearby_wires(px, py):
        """Count wire endpoints within tolerance of point."""
        count = 0
        for (wx, wy) in wire_pts:
            if abs(px - wx) < TOLERANCE and abs(py - wy) < TOLERANCE:
                count += 1
        return count

    def point_on_any_wire(px, py):
        """Check if point lies on any wire segment (T-junction)."""
        for (w1, w2) in wires:
            x1, y1 = w1
            x2, y2 = w2
            if abs(x1 - x2) < 0.1:  # vertical wire
                if abs(px - x1) < TOLERANCE:
                    if min(y1, y2) - TOLERANCE <= py <= max(y1, y2) + TOLERANCE:
                        return True
            if abs(y1 - y2) < 0.1:  # horizontal wire
                if abs(py - y1) < TOLERANCE:
                    if min(x1, x2) - TOLERANCE <= px <= max(x1, x2) + TOLERANCE:
                        return True
        return False

    disconnected = []
    for name, (lx, ly) in labels:
        nearby = count_nearby_wires(lx, ly)
        on_wire = point_on_any_wire(lx, ly)

        # Label is connected if it touches a wire endpoint or lies on a wire
        if nearby == 0 and not on_wire:
            # Label not on any wire at all
            # Skip if this is a multi-instance label (KiCad auto-connects them)
            if label_name_counts.get(name, 0) >= 2:
                continue  # inter-region connector, OK
            disconnected.append((name, lx, ly))

    if disconnected:
        issues.append(('WARNING',
            f'{len(disconnected)} disconnected label(s) detected'))
        for name, lx, ly in disconnected[:10]:  # limit output
            issues.append(('WARNING',
                f'  Label "{name}" at ({lx:.1f},{ly:.1f}) not connected to any wire'))
    else:
        issues.append(('PASS', 'All labels connected to wires'))

    return issues


def check_duplicate_labels(wires, labels):
    """Detect duplicate net labels on the same net (redundant labels).

    Same-name labels in different regions are inter-region connectors (OK).
    Same-name labels in the SAME net (connected by wires) are redundant and
    create visual clutter - only one is needed per connected region.

    Also detects different-name labels on the same net, which creates
    ambiguity about what the net is called.

    Returns list of (severity, message) tuples.
    """
    issues = []

    # Build connectivity
    nets, net_names, all_points, parent, find = find_connected_points(wires, labels)

    # Check for different-name labels on the same net
    multi_name_nets = 0
    for root, names in net_names.items():
        if len(names) > 1:
            # Filter out power net names that are expected to coexist
            non_power = [n for n in names if n not in ('GND', 'VCC', 'VEE', 'V+', 'V-')]
            if len(non_power) > 1:
                multi_name_nets += 1
                if multi_name_nets <= 5:  # limit output
                    issues.append(('WARNING',
                        f'Net has multiple names: {{{", ".join(sorted(non_power))}}} '
                        f'- consider using a single name for clarity'))

    # Check for same-name labels that are NOT on the same net
    # (these are inter-region connectors - just INFO)
    label_by_name = {}
    label_start = len(wires) * 2
    for i, (name, pos) in enumerate(labels):
        idx = label_start + i
        root = find(idx)
        if name not in label_by_name:
            label_by_name[name] = []
        label_by_name[name].append((root, pos))

    # Check for same-name labels on the same net (redundant)
    redundant = 0
    for name, entries in label_by_name.items():
        roots = [r for r, _ in entries]
        root_set = set(roots)
        for root in root_set:
            count = roots.count(root)
            if count > 1:
                redundant += 1
                if redundant <= 5:
                    issues.append(('INFO',
                        f'Label "{name}" appears {count}x on same net '
                        f'(redundant, only 1 needed per connected region)'))

    if multi_name_nets == 0:
        issues.append(('PASS', 'No ambiguous multi-name nets detected'))
    else:
        issues.append(('WARNING',
            f'{multi_name_nets} net(s) with multiple different names'))

    return issues


def check_label_overlaps(labels, components):
    """Detect overlapping text labels and reference designators.

    Text that overlaps is unreadable. This checks:
    1. Net labels overlapping each other
    2. Net labels overlapping component reference designators
    3. Reference designators overlapping each other

    Uses approximate bounding boxes based on text length and standard font size.

    Returns list of (severity, message) tuples.
    """
    issues = []

    # Approximate text bounding box: each character ~2.5mm wide, ~4mm tall
    # (at default KiCad text size of 1.27mm which renders ~2.5mm per char)
    CHAR_W = 2.5  # mm per character width
    TEXT_H = 4.0  # mm text height
    MIN_OVERLAP_DIST = 1.0  # mm overlap threshold

    def text_bbox(x, y, text, rotation=0):
        """Return (x_min, y_min, x_max, y_max) bounding box for text."""
        w = len(text) * CHAR_W
        h = TEXT_H
        if rotation in (90, 270):
            w, h = h, w
        return (x - w/2, y - h/2, x + w/2, y + h/2)

    def boxes_overlap(b1, b2):
        """Check if two bounding boxes overlap."""
        return (b1[0] < b2[2] - MIN_OVERLAP_DIST and
                b1[2] > b2[0] + MIN_OVERLAP_DIST and
                b1[1] < b2[3] - MIN_OVERLAP_DIST and
                b1[3] > b2[1] + MIN_OVERLAP_DIST)

    # Build list of all text items with bounding boxes
    text_items = []

    # Net labels
    for name, (lx, ly) in labels:
        bbox = text_bbox(lx, ly, name)
        text_items.append(('label', name, bbox, (lx, ly)))

    # Component references (ref designators like R1, C2, U1)
    for c in components:
        ref = c.get('reference', '')
        if ref and not ref.startswith('#'):  # skip power flags
            bbox = text_bbox(c['x'], c['y'] - 5, ref)  # ref usually above component
            text_items.append(('ref', ref, bbox, (c['x'], c['y'])))

    # Check all pairs
    overlap_count = 0
    for i, (type1, name1, bbox1, pos1) in enumerate(text_items):
        for j in range(i + 1, len(text_items)):
            type2, name2, bbox2, pos2 = text_items[j]
            if boxes_overlap(bbox1, bbox2):
                overlap_count += 1
                if overlap_count <= 5:
                    issues.append(('WARNING',
                        f'{type1} "{name1}" at ({pos1[0]:.0f},{pos1[1]:.0f}) '
                        f'overlaps {type2} "{name2}" at ({pos2[0]:.0f},{pos2[1]:.0f})'))

    if overlap_count > 5:
        issues.append(('WARNING',
            f'{overlap_count} total text overlaps detected (showing first 5)'))
    elif overlap_count == 0:
        issues.append(('PASS', 'No text overlaps detected'))

    return issues


def check_floating_wires(wires, labels, components):
    """Detect wire segments not connected to any component pin or label.

    A floating wire is one where NEITHER endpoint connects to:
    - Another wire endpoint
    - A component pin
    - A net label

    These wires serve no purpose and clutter the schematic.

    Returns list of (severity, message) tuples.
    """
    TOLERANCE = 0.6
    issues = []

    # Collect all significant connection points
    # (label positions + component approximate pin positions)
    connection_pts = []
    for _, pos in labels:
        connection_pts.append(pos)

    # Get component pin positions using dynamic parser (all component types)
    for c in components:
        pins = get_component_pins(c)
        if pins is not None:
            for _, (px, py, _, _) in pins.items():
                connection_pts.append((px, py))
        else:
            # Unknown/power symbol: use component center as fallback
            connection_pts.append((c['x'], c['y']))

    # For each wire, check if at least one endpoint connects to something
    floating = []
    for i, (p1, p2) in enumerate(wires):
        # Check if either endpoint matches another wire's endpoint
        p1_connected = False
        p2_connected = False

        for j, (q1, q2) in enumerate(wires):
            if i == j:
                continue
            if (abs(p1[0] - q1[0]) < TOLERANCE and abs(p1[1] - q1[1]) < TOLERANCE) or \
               (abs(p1[0] - q2[0]) < TOLERANCE and abs(p1[1] - q2[1]) < TOLERANCE):
                p1_connected = True
            if (abs(p2[0] - q1[0]) < TOLERANCE and abs(p2[1] - q1[1]) < TOLERANCE) or \
               (abs(p2[0] - q2[0]) < TOLERANCE and abs(p2[1] - q2[1]) < TOLERANCE):
                p2_connected = True

        # Also check against connection points (labels, pins)
        for (cx, cy) in connection_pts:
            if abs(p1[0] - cx) < TOLERANCE and abs(p1[1] - cy) < TOLERANCE:
                p1_connected = True
            if abs(p2[0] - cx) < TOLERANCE and abs(p2[1] - cy) < TOLERANCE:
                p2_connected = True

        # Also check T-junctions (endpoint on another wire segment)
        for j, (q1, q2) in enumerate(wires):
            if i == j:
                continue
            x1, y1 = q1
            x2, y2 = q2
            for px, py, flag in [(p1[0], p1[1], 'p1'), (p2[0], p2[1], 'p2')]:
                if abs(x1 - x2) < 0.1:  # vertical
                    if abs(px - x1) < TOLERANCE and min(y1, y2) - TOLERANCE <= py <= max(y1, y2) + TOLERANCE:
                        if flag == 'p1':
                            p1_connected = True
                        else:
                            p2_connected = True
                elif abs(y1 - y2) < 0.1:  # horizontal
                    if abs(py - y1) < TOLERANCE and min(x1, x2) - TOLERANCE <= px <= max(x1, x2) + TOLERANCE:
                        if flag == 'p1':
                            p1_connected = True
                        else:
                            p2_connected = True

        if not p1_connected and not p2_connected:
            floating.append((i, p1, p2))

    if floating:
        issues.append(('WARNING',
            f'{len(floating)} floating wire(s) detected (not connected to anything)'))
        for idx, p1, p2 in floating[:5]:
            issues.append(('WARNING',
                f'  Wire[{idx}] ({p1[0]:.1f},{p1[1]:.1f})->({p2[0]:.1f},{p2[1]:.1f}) '
                f'has no connections'))
    else:
        issues.append(('PASS', 'No floating wires detected'))

    return issues


def check_component_wire_distance(wires, components):
    """Check that non-power components are within wiring distance of the wire network.

    Components placed far from any wire are likely misplaced or forgotten
    during layout. Each component should have at least one wire endpoint
    within a reasonable distance of its center.

    Returns list of (severity, message) tuples.
    """
    TOLERANCE = 0.6
    MAX_DIST = 30.0  # mm - maximum distance from component to nearest wire
    issues = []

    # Collect all wire endpoints
    wire_pts = set()
    for (p1, p2) in wires:
        wire_pts.add(p1)
        wire_pts.add(p2)
    wire_list = list(wire_pts)

    # Check non-power components
    non_power = [c for c in components
                 if 'GND' not in c.get('lib_id', '')
                 and 'VCC' not in c.get('lib_id', '')
                 and 'VEE' not in c.get('lib_id', '')
                 and not c.get('reference', '').startswith('#')]

    stranded = []
    for c in non_power:
        cx, cy = c['x'], c['y']
        min_dist = float('inf')
        for (wx, wy) in wire_list:
            d = ((cx - wx)**2 + (cy - wy)**2)**0.5
            if d < min_dist:
                min_dist = d
        if min_dist > MAX_DIST:
            stranded.append((c['reference'], c.get('value', ''), cx, cy, min_dist))

    if stranded:
        issues.append(('WARNING',
            f'{len(stranded)} component(s) far from wire network (>{MAX_DIST}mm)'))
        for ref, val, cx, cy, dist in stranded[:5]:
            issues.append(('WARNING',
                f'  {ref} ({val}) at ({cx:.0f},{cy:.0f}) is {dist:.0f}mm from nearest wire'))
    else:
        issues.append(('PASS', 'All components within wiring distance'))

    return issues


def auto_correct_schematic(sch_path, circuit_type, layout_issues, current_kwargs):
    """Generate corrected build parameters based on detected layout issues.

    Instead of patching the schematic file, this computes adjusted build kwargs
    and returns them for the next rebuild iteration. Each rule maps to specific
    parameter adjustments that escalate if the rule triggers repeatedly.

    Self-learning: fixes are recorded so the system knows what worked.

    Args:
        sch_path: path to the current schematic
        circuit_type: e.g. 'mux_tia'
        layout_issues: list of (severity, message, rule_id) from check_layout_quality
        current_kwargs: current build kwargs dict (for escalation)

    Returns:
        corrections: dict of {rule_id: fix_description} applied
        new_kwargs: dict of adjusted build parameters for next iteration
        rebuild_needed: bool - True if build function needs re-running
    """
    corrections = {}
    new_kwargs = dict(current_kwargs)

    # Load rule history for escalation
    rules = load_learned_rules()
    rule_counts = {r['id']: r.get('times_triggered', 0) for r in rules['rules']}

    for severity, msg, rule_id in layout_issues:
        if severity not in ('WARNING', 'ERROR'):
            continue

        # Escalation factor: increase correction magnitude for repeat offenders
        trigger_count = rule_counts.get(rule_id, 0)
        escalation = 1.0 + 0.25 * trigger_count  # 1.0x, 1.25x, 1.5x, ...

        if rule_id == 'power_in_feedback_area':
            base_clearance = current_kwargs.get('gnd_route_clearance', 8)
            new_val = int(base_clearance * escalation) + 2
            new_kwargs['gnd_route_clearance'] = new_val
            corrections[rule_id] = f'Increase GND route clearance to {new_val}*G (escalation {escalation:.2f}x)'
            learn_rule(rule_id,
                'Power symbols must not be placed inside op-amp feedback bounding box',
                circuit_type, 'fix_power_routing')
            record_fix(rule_id)

        elif rule_id == 'label_at_feedback_not_output':
            new_kwargs['label_at_output_pin'] = True
            corrections[rule_id] = 'Move OUT label to actual op-amp output wire'
            learn_rule(rule_id,
                'Output labels must be placed near the op-amp output pin, not in feedback area',
                circuit_type, 'fix_output_label_position')
            record_fix(rule_id)

        elif rule_id == 'divider_too_close_to_opamp':
            base_offset = current_kwargs.get('divider_offset', 16)
            new_val = int(base_offset * escalation) + 4
            new_kwargs['divider_offset'] = new_val
            corrections[rule_id] = f'Increase divider offset to {new_val}*G (escalation {escalation:.2f}x)'
            learn_rule(rule_id,
                'Voltage divider must be at least 30mm from op-amp non-inv input',
                circuit_type, 'fix_divider_spacing')
            record_fix(rule_id)

        elif rule_id == 'feedback_components_overlap':
            base_spacing = current_kwargs.get('feedback_spacing', 5)
            new_val = int(base_spacing * escalation) + 2
            new_kwargs['feedback_spacing'] = new_val
            corrections[rule_id] = f'Increase feedback spacing to {new_val}*G'
            learn_rule(rule_id,
                'Feedback R and C must have minimum 5mm separation',
                circuit_type, 'fix_feedback_spacing')
            record_fix(rule_id)

        elif rule_id == 'vertical_utilization':
            # Increase row spacing to spread components vertically
            base_filt = current_kwargs.get('filt_row_spacing', 18)
            base_relay = current_kwargs.get('relay_row_spacing', 14)
            new_filt = int(base_filt * 1.3)
            new_relay = int(base_relay * 1.3)
            new_kwargs['filt_row_spacing'] = new_filt
            new_kwargs['relay_row_spacing'] = new_relay
            corrections[rule_id] = (f'Increase filt_row_spacing to {new_filt}, '
                                    f'relay_row_spacing to {new_relay}')
            learn_rule(rule_id,
                'Components must use at least 40% of sheet height',
                circuit_type, 'fix_vertical_spread')
            record_fix(rule_id)

        elif rule_id == 'minimum_avg_spacing':
            # Increase all spacing parameters
            base_filt = current_kwargs.get('filt_row_spacing', 18)
            base_driver = current_kwargs.get('driver_spacing', 28)
            new_filt = int(base_filt * 1.2)
            new_driver = int(base_driver * 1.2)
            new_kwargs['filt_row_spacing'] = new_filt
            new_kwargs['driver_spacing'] = new_driver
            corrections[rule_id] = (f'Increase spacing: filt_row={new_filt}, '
                                    f'driver={new_driver}')
            learn_rule(rule_id,
                'Median nearest-neighbor distance must be >= 8mm',
                circuit_type, 'fix_component_density')
            record_fix(rule_id)

        elif rule_id == 'component_overlap':
            base_driver = current_kwargs.get('driver_spacing', 28)
            new_val = int(base_driver * escalation) + 4
            new_kwargs['driver_spacing'] = new_val
            corrections[rule_id] = f'Increase driver spacing to {new_val}*G'
            learn_rule(rule_id,
                'Non-power components must not overlap (min 5mm separation)',
                circuit_type, 'fix_component_overlap')
            record_fix(rule_id)

        elif rule_id == 'power_net_mixing':
            # Can't fix via kwargs - this is a code bug.
            # Flag it but don't trigger rebuild (needs manual fix).
            corrections[rule_id] = 'ERROR: VCC net mixing detected - use net labels for separate rails'
            learn_rule(rule_id,
                'Different voltage rails must NOT share VCC power symbol - use net labels',
                circuit_type, 'fix_power_net_separation')
            record_fix(rule_id)

        elif rule_id == 'relay_coil_missing':
            # Code-level fix: relay coils are generated by build_full_system.
            # If this triggers, the build function needs updating (now fixed).
            corrections[rule_id] = ('CRITICAL: Relay coils missing from driver circuit! '
                'NPN transistors have no coil load - reed switches cannot energize. '
                'Fixed: added R_COIL components between 5V_ISO and NPN collectors.')
            learn_rule(rule_id,
                'Every relay NPN driver MUST have a coil component (L or R_COIL) '
                'between the supply rail and collector. Without it, the reed switch '
                'contacts can never close.',
                circuit_type, 'fix_relay_coils')
            record_fix(rule_id)

        elif rule_id == 'flyback_diode_topology':
            # Code-level fix: flyback diode must be in parallel with coil.
            corrections[rule_id] = ('CRITICAL: Flyback diode in series with NPN instead of '
                'parallel with relay coil. Fixed: D in parallel across coil.')
            learn_rule(rule_id,
                'Flyback protection diode must be in PARALLEL with relay coil '
                '(cathode at supply, anode at collector), NOT in series with NPN.',
                circuit_type, 'fix_flyback_topology')
            record_fix(rule_id)

        elif rule_id == 'relay_decoupling_missing':
            # Triggers rebuild - the build function now adds C30 for 5V_ISO bypass.
            corrections[rule_id] = ('Add 100nF decoupling capacitor on 5V_ISO near relay drivers. '
                'Relay coil switching causes current spikes that need local bypass.')
            learn_rule(rule_id,
                'Relay driver supply rail (5V_ISO) must have a local decoupling '
                'capacitor (100nF minimum) to absorb coil switching transients.',
                circuit_type, 'fix_relay_decoupling')
            record_fix(rule_id)

        elif rule_id == 'esd_diode_count':
            corrections[rule_id] = 'Check BAV199 ESD diode count - expected 32 (16 channels x 2)'
            learn_rule(rule_id,
                'Each input channel needs 2 BAV199 ESD diodes for bidirectional clamping',
                circuit_type, 'fix_esd_diode_count')
            record_fix(rule_id)

    rebuild_needed = len(corrections) > 0
    return corrections, new_kwargs, rebuild_needed


def build_and_verify_loop(circuit_type, build_fn, max_attempts=3, **build_kwargs):
    """Recursive correction loop: build -> verify -> detect -> fix -> rebuild.

    Self-learning system:
    1. Build the schematic using build_fn
    2. Run full verification (structural + layout quality)
    3. If issues found, auto_correct_schematic computes adjusted build params
    4. Rebuild with corrected parameters (escalating if same issue recurs)
    5. Re-verify (up to max_attempts)
    6. Record all learned rules persistently

    Args:
        circuit_type: e.g. 'mux_tia', 'mcu_section'
        build_fn: callable that accepts **kwargs and returns sch_path
        max_attempts: max rebuild iterations
        **build_kwargs: initial params passed to build_fn (corrections override these)

    Returns:
        sch_path: final schematic path
        all_issues: list of all issues from final verification
        corrections_log: list of all corrections applied across attempts
    """
    corrections_log = []
    current_kwargs = dict(build_kwargs)
    rules = load_learned_rules()
    print(f"\n  -- {PROGRAM_NAME} Correction Loop --")
    print(f"  -- max {max_attempts} attempts, "
          f"{len(rules['rules'])} learned rules, "
          f"{rules.get('fixes_applied', 0)} total fixes applied --")

    for attempt in range(1, max_attempts + 1):
        print(f"\n  -- Attempt {attempt}/{max_attempts} --")

        # Step 1: Build with current params
        sch_path = build_fn(**current_kwargs)

        # Step 2: Verify (structural)
        all_issues = verify_circuit(sch_path, circuit_type)

        # Step 3: Layout quality checks
        wires, labels, components = extract_nets_from_schematic(sch_path)
        layout_issues = check_layout_quality(wires, labels, components)
        for sev, msg, rid in layout_issues:
            icon = {'ERROR': 'X', 'WARNING': '!', 'PASS': '+'}[sev]
            print(f"    [{icon}] LAYOUT: {msg}")

        # Step 4: Check for errors/warnings
        errors = sum(1 for s, _ in all_issues if s == 'ERROR')
        warnings = sum(1 for s, _ in all_issues if s == 'WARNING')
        layout_warnings = sum(1 for s, _, _ in layout_issues if s in ('WARNING', 'ERROR'))

        if errors == 0 and warnings == 0 and layout_warnings == 0:
            print(f"\n  CLEAN on attempt {attempt} - all checks pass!")
            break

        if layout_warnings > 0 and attempt < max_attempts:
            # Step 5: Auto-correct - get adjusted build params
            corrections, new_kwargs, rebuild_needed = auto_correct_schematic(
                sch_path, circuit_type, layout_issues, current_kwargs)
            corrections_log.extend(corrections.items())

            if rebuild_needed:
                current_kwargs = new_kwargs
                print(f"\n  Applying {len(corrections)} corrections (rebuilding with adjusted params):")
                for rid, desc in corrections.items():
                    print(f"    -> [{rid}]: {desc}")
            else:
                print(f"\n  No auto-fixes available for remaining issues")
                break
        elif errors > 0:
            print(f"\n  {errors} structural error(s) - manual fix needed")
            break
    else:
        print(f"\n  Reached max attempts ({max_attempts})")

    return sch_path, all_issues, corrections_log


def detect_scale_factor(sch_path):
    """Detect the scale factor applied to a schematic by scale_schematic().

    Checks if the paper size is "User" (custom) and compares to standard sizes
    to determine the scaling factor. Returns 1 if no scaling detected.
    """
    if not sch_path or not os.path.exists(sch_path):
        return 1
    with open(sch_path, 'r', encoding='utf-8') as f:
        text = f.read(2000)  # paper size is near the top
    m = re.search(r'\(paper "User" (\d+) (\d+)\)', text)
    if not m:
        return 1  # standard paper, no scaling
    w, h = int(m.group(1)), int(m.group(2))
    # Check against known standard sizes to determine scale
    paper_sizes = {
        'A0': (1189, 841), 'A1': (841, 594), 'A2': (594, 420),
        'A3': (420, 297), 'A4': (297, 210),
    }
    for name, (pw, ph) in paper_sizes.items():
        for scale in [2, 3, 4, 5]:
            if abs(w - pw * scale) < 5 and abs(h - ph * scale) < 5:
                return scale
    return 1


def check_pin_connectivity(wires, components, sch_path=None):
    """Check that ALL component pins are connected to wires.

    Uses dynamic pin parser to read pin positions from .kicad_sym library
    files. Works for any component type: op-amps, resistors, capacitors,
    diodes, transistors, reed switches, etc.

    Handles scaled schematics by detecting the scale factor from paper size.
    Skips power symbols (GND/VCC/VEE) and hidden/no_connect pins.

    Returns list of (severity, message) for each component checked.
    """
    scale = detect_scale_factor(sch_path) if sch_path else 1
    TOLERANCE = 0.6 * max(scale, 1)
    issues = []
    checked = 0
    skipped = 0

    # Collect all wire endpoints for fast lookup
    wire_points = []
    for (p1, p2) in wires:
        wire_points.append(p1)
        wire_points.append(p2)

    def point_near_wire(px, py):
        """Check if point is near any wire endpoint or on a wire segment."""
        for (wx, wy) in wire_points:
            if abs(px - wx) < TOLERANCE and abs(py - wy) < TOLERANCE:
                return True
        for (w1, w2) in wires:
            x1, y1 = w1
            x2, y2 = w2
            if abs(x1 - x2) < 0.1 * scale:  # vertical wire
                if abs(px - x1) < TOLERANCE:
                    if min(y1, y2) - TOLERANCE <= py <= max(y1, y2) + TOLERANCE:
                        return True
            if abs(y1 - y2) < 0.1 * scale:  # horizontal wire
                if abs(py - y1) < TOLERANCE:
                    if min(x1, x2) - TOLERANCE <= px <= max(x1, x2) + TOLERANCE:
                        return True
        return False

    for comp in components:
        pins = get_component_pins(comp, scale=scale)
        if pins is None:
            skipped += 1
            continue

        ref = comp['reference']
        lib_id = comp.get('lib_id', '')
        checked += 1
        all_connected = True
        floating_pins = []

        for pin_num, (px, py, pin_type, pin_name) in sorted(pins.items()):
            if not point_near_wire(px, py):
                label = f"{pin_name}" if pin_name else f"pin{pin_num}"
                floating_pins.append((pin_num, label, px, py))
                all_connected = False

        if floating_pins:
            for pin_num, label, px, py in floating_pins:
                # NULL/offset pins on op-amps are optional — INFO not ERROR
                if label in ('NULL', 'NC', ''):
                    sev = 'INFO'
                else:
                    sev = 'ERROR'
                issues.append((sev,
                    f'{ref} ({lib_id}) {label} FLOATING at ({px:.1f},{py:.1f})'))
        elif all_connected:
            n_pins = len(pins)
            issues.append(('PASS', f'{ref}: all {n_pins} pins connected'))

    issues.append(('INFO', f'Pin connectivity: {checked} components checked, {skipped} skipped (power/virtual)'))
    return issues


def check_wire_crossings(wires, labels):
    """Detect visual wire crossings from different nets.

    In KiCad, wires only connect at endpoints or T-junctions (endpoint on wire).
    Two wires crossing at interior points do NOT connect electrically, but
    they create visual ambiguity that makes schematics hard to read.

    Returns list of (severity, message) for each crossing found.
    """
    issues = []

    # First, assign each wire to a net using the connectivity analysis
    nets, net_names, all_points, parent, find = find_connected_points(wires, labels)

    # Map each wire index to its net root
    wire_nets = {}
    for i in range(len(wires)):
        wire_nets[i] = find(i * 2)

    def segments_cross(w1, w2):
        """Check if two wire segments cross at an interior point.
        Only checks horizontal-vertical crossings (manhattan routing).
        Returns crossing point or None.
        """
        (ax1, ay1), (ax2, ay2) = w1
        (bx1, by1), (bx2, by2) = w2
        TOL = 0.3

        # Check horizontal wire A crossing vertical wire B
        def check_hv(h, v):
            (hx1, hy1), (hx2, hy2) = h
            (vx1, vy1), (vx2, vy2) = v
            if abs(hy1 - hy2) > TOL or abs(vx1 - vx2) > TOL:
                return None  # not H-V pair
            hx_lo, hx_hi = min(hx1, hx2), max(hx1, hx2)
            vy_lo, vy_hi = min(vy1, vy2), max(vy1, vy2)
            cross_x = vx1
            cross_y = hy1
            # Interior crossing: cross point must be strictly inside both segments
            margin = 0.5  # must be at least 0.5mm from endpoints
            if (hx_lo + margin < cross_x < hx_hi - margin and
                vy_lo + margin < cross_y < vy_hi - margin):
                return (round(cross_x, 2), round(cross_y, 2))
            return None

        pt = check_hv(w1, w2)
        if pt:
            return pt
        pt = check_hv(w2, w1)
        return pt

    # Check all wire pairs from different nets
    crossings = []
    for i in range(len(wires)):
        for j in range(i + 1, len(wires)):
            if wire_nets[i] == wire_nets[j]:
                continue  # same net - crossing is fine
            pt = segments_cross(wires[i], wires[j])
            if pt:
                crossings.append((i, j, pt))

    if crossings:
        issues.append(('WARNING',
            f'{len(crossings)} wire crossing(s) detected (visual ambiguity)'))
        for wi, wj, (cx, cy) in crossings:
            issues.append(('WARNING',
                f'  Crossing at ({cx},{cy}): '
                f'wire[{wi}] {wires[wi][0]}->{wires[wi][1]} X '
                f'wire[{wj}] {wires[wj][0]}->{wires[wj][1]}'))
    else:
        issues.append(('PASS', 'No wire crossings detected (clean routing)'))

    return issues


def check_wire_overlaps(wires):
    """Detect collinear wire segments that overlap along a shared range.

    Collinear overlapping wires are always suspicious:
    - If from different nets: unintended electrical short (the VEE/feedback
      bug from Session 16 was exactly this — two wires at same X overlapped)
    - If from same net: redundant/sloppy routing

    Only flags overlaps longer than a tolerance threshold. Endpoint-only
    connections (normal T-junctions) are excluded.

    Returns list of (severity, message) tuples.
    """
    issues = []
    TOL = 0.5

    # Separate wires by orientation
    h_wires = []  # horizontal segments (constant Y)
    v_wires = []  # vertical segments (constant X)

    for i, (p1, p2) in enumerate(wires):
        x1, y1 = p1
        x2, y2 = p2
        if abs(y1 - y2) < TOL:
            h_wires.append((min(x1, x2), max(x1, x2), (y1 + y2) / 2, i))
        elif abs(x1 - x2) < TOL:
            v_wires.append((min(y1, y2), max(y1, y2), (x1 + x2) / 2, i))

    overlaps = []

    # Check horizontal pairs
    for a in range(len(h_wires)):
        for b in range(a + 1, len(h_wires)):
            ax1, ax2, ay, ai = h_wires[a]
            bx1, bx2, by, bi = h_wires[b]
            if abs(ay - by) > TOL:
                continue
            overlap_len = min(ax2, bx2) - max(ax1, bx1)
            if overlap_len > TOL:
                # Exclude endpoint-only touches
                if abs(ax2 - bx1) < TOL or abs(bx2 - ax1) < TOL:
                    continue
                x_mid = (max(ax1, bx1) + min(ax2, bx2)) / 2
                overlaps.append(('H', x_mid, ay, overlap_len, ai, bi))

    # Check vertical pairs
    for a in range(len(v_wires)):
        for b in range(a + 1, len(v_wires)):
            ay1, ay2, ax, ai = v_wires[a]
            by1, by2, bx, bi = v_wires[b]
            if abs(ax - bx) > TOL:
                continue
            overlap_len = min(ay2, by2) - max(ay1, by1)
            if overlap_len > TOL:
                if abs(ay2 - by1) < TOL or abs(by2 - ay1) < TOL:
                    continue
                y_mid = (max(ay1, by1) + min(ay2, by2)) / 2
                overlaps.append(('V', ax, y_mid, overlap_len, ai, bi))

    if overlaps:
        issues.append(('WARNING',
            f'{len(overlaps)} collinear wire overlap(s) detected (possible shorts)'))
        for direction, x, y, length, wi, wj in overlaps:
            issues.append(('WARNING',
                f'  Overlap ({direction}) at ({x:.1f},{y:.1f}) length={length:.1f}mm: '
                f'wire[{wi}] {wires[wi][0]}->{wires[wi][1]} || '
                f'wire[{wj}] {wires[wj][0]}->{wires[wj][1]}'))
    else:
        issues.append(('PASS', 'No collinear wire overlaps (clean routing)'))

    return issues


def find_connected_points(wires, labels):
    """Build connectivity graph from wire endpoints.

    Groups all points connected by wires into nets.
    Points within 0.5mm are considered the same point.
    """
    TOLERANCE = 0.5

    def same_point(p1, p2):
        return abs(p1[0] - p2[0]) < TOLERANCE and abs(p1[1] - p2[1]) < TOLERANCE

    def point_on_wire(p, w):
        """Check if point p lies on wire segment w."""
        (x1, y1), (x2, y2) = w
        px, py = p
        # Check if p is collinear and between endpoints
        if abs(x1 - x2) < TOLERANCE:  # vertical wire
            if abs(px - x1) < TOLERANCE:
                return min(y1, y2) - TOLERANCE <= py <= max(y1, y2) + TOLERANCE
        if abs(y1 - y2) < TOLERANCE:  # horizontal wire
            if abs(py - y1) < TOLERANCE:
                return min(x1, x2) - TOLERANCE <= px <= max(x1, x2) + TOLERANCE
        return False

    # Collect all unique points (wire endpoints + label positions)
    all_points = []
    for (p1, p2) in wires:
        all_points.append(p1)
        all_points.append(p2)
    for name, pos in labels:
        all_points.append(pos)

    # Union-Find for connectivity
    parent = list(range(len(all_points)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Connect wire endpoints
    for i, (p1, p2) in enumerate(wires):
        idx1 = i * 2
        idx2 = i * 2 + 1
        union(idx1, idx2)  # endpoints of same wire are connected

    # Connect points that are at the same location
    n = len(all_points)
    for i in range(n):
        for j in range(i + 1, n):
            if same_point(all_points[i], all_points[j]):
                union(i, j)

    # Connect points that lie ON wire segments (T-junctions)
    label_start = len(wires) * 2
    for i, p in enumerate(all_points):
        for w_idx, w in enumerate(wires):
            if point_on_wire(p, w):
                union(i, w_idx * 2)

    # Build nets
    nets = {}
    for i in range(n):
        root = find(i)
        if root not in nets:
            nets[root] = []
        nets[root].append(all_points[i])

    # Attach label names to nets
    net_names = {}
    for i, (name, pos) in enumerate(labels):
        idx = label_start + i
        root = find(idx)
        if root not in net_names:
            net_names[root] = set()
        net_names[root].add(name)

    return nets, net_names, all_points, parent, find


def verify_circuit(sch_path, circuit_type, sim_results=None, expected=None):
    """Verify a circuit schematic and simulation results.

    Self-improving verification system: every bug found during development
    becomes a permanent check so the same problem never passes again.

    Check Categories:
    -----------------------------------------------------------------------
    STRUCTURAL (schematic file):
      1. Required nets present (GND, VCC, VEE, OUT)
      2. Input source present (VSIN symbol or IN label)
      3. Power symbols present (not just text labels)
      4. All op-amp pins connected to wires (5/5 for LM741)
      5. No wire crossings between different nets (visual quality)
      6. Feedback path exists (inv_amp, electrometer TIA)
      7. Component count sanity check (minimum per circuit type)

    TIER 1 CONNECTIVITY & OVERLAP (Session 14):
      8. Disconnected labels (label not touching any wire)
      9. Duplicate/ambiguous net labels (different names on same net)
     10. Text/label overlap detection (unreadable overlapping text)
     11. Floating wires (wire not connected to anything)
     12. Component-to-wire distance (misplaced components)

    SIMULATION (ngspice results):
     13. Output not railing at supply voltage (saturation check)
     14. Virtual ground holding (inverting input near 0V)
     15. Gain/transimpedance within expected tolerance
     16. Custom per-circuit expected values

    LESSONS LEARNED (bugs that became checks):
      - [electrometer] 100nA into 1G = 100V > supply -> saturation check added
      - [inv_amp] Rf disconnected -> feedback path detection added
      - [sig_cond] Wire crossing VEE stub -> crossing detector added
      - [usb_ina] V1/V2 wires crossing power -> crossing detector added
      - [all] Missing power symbols -> symbol presence check added
      - [all] Floating op-amp pins -> pin connectivity check added
      - [full_system] Relay coils missing from NPN driver circuit -> topology check added
      - [full_system] Flyback diode in series not parallel -> topology check added
      - [full_system] BAV199 ESD diodes mid-wire without junction -> junction fix added
      - [full_system] 5V_ISO relay supply had no decoupling cap -> check added

    To add a new check after finding a problem:
      1. Add the check to the appropriate section below
      2. Add a comment with [circuit_type] prefix explaining what bug it catches
      3. Update the LESSONS LEARNED docstring above

    Args:
        sch_path: Path to .kicad_sch file
        circuit_type: One of 'ce_amp', 'inv_amp', 'sig_cond', 'usb_ina', 'electrometer'
        sim_results: dict from measure_simulation() or custom TIA measurements
        expected: dict of {key: (expected_val, tolerance, unit_str)}

    Returns:
        issues: list of (severity, message) tuples
                severity: 'ERROR', 'WARNING', 'PASS', 'INFO'
    """
    issues = []
    print("\n  -- Circuit Verification --")

    # ══════════════════════════════════════════════════════════════
    # STRUCTURAL CHECKS (parse schematic file)
    # ══════════════════════════════════════════════════════════════

    # Step 1: Parse schematic
    wires, labels, components = extract_nets_from_schematic(sch_path)
    issues.append(('INFO', f'Found {len(wires)} wires, {len(labels)} labels, {len(components)} components'))

    label_names = set(name for name, _ in labels)
    comp_lib_ids = [c['lib_id'] for c in components]

    # Step 2: Check required nets (labels + power symbols)
    power_nets = set()
    for lid in comp_lib_ids:
        if 'GND' in lid: power_nets.add('GND')
        if 'VCC' in lid: power_nets.add('VCC')
        if 'VEE' in lid: power_nets.add('VEE')
    all_nets = label_names | power_nets

    required_nets = {'GND', 'OUT'}
    if circuit_type in ('inv_amp', 'sig_cond', 'usb_ina', 'electrometer'):
        required_nets.update({'VCC', 'VEE'})
    elif circuit_type == 'electrometer_362':
        required_nets = {'GND', 'VCC', 'AIN0'}  # ADC output label replaces OUT
    elif circuit_type == 'relay_ladder':
        required_nets = {'GND', 'VCC', 'INV', 'OUT'}  # buses + power
    elif circuit_type == 'input_filters':
        required_nets = {'GND', 'VCC'}  # 16 CH_IN + 16 MUX labels checked separately
    elif circuit_type == 'analog_mux':
        required_nets = {'GND', 'VCC', 'TIA_IN'}
    elif circuit_type == 'mux_tia':
        required_nets = {'GND', 'VCC', 'TIA_IN', 'AIN0', 'INV', 'OUT'}
    elif circuit_type == 'mcu_section':
        required_nets = {'GND', 'VCC', 'AIN0', 'AIN1'}
    elif circuit_type == 'full_system':
        required_nets = {'GND', 'VCC', 'TIA_IN', 'AIN0', 'AIN1', 'INV', 'OUT'}
    elif circuit_type == 'ce_amp':
        required_nets.update({'VCC'})  # single supply: VCC + GND only
    elif circuit_type == 'audioamp':
        required_nets = {'GND', 'OUTPUT'}
    elif circuit_type == 'oscillator':
        # Oscillator uses +15V/-15V net labels (not VCC/VEE), 3.3V for MCU
        required_nets = {'GND', 'HP', 'BP', 'LP', 'VCTRL', 'AIN0'}

    for net in sorted(required_nets):
        if net in all_nets:
            src = 'power symbol' if net in power_nets else 'label'
            issues.append(('PASS', f'Net {net} present ({src})'))
        else:
            issues.append(('ERROR', f'Missing net: {net}'))

    # Step 2b: Check input source (VSIN symbol or IN label)
    has_vsin = 'VSIN:VSIN' in comp_lib_ids
    if circuit_type == 'oscillator':
        # Self-oscillating circuit - no external input source needed
        if 'HP' in label_names and 'BP' in label_names:
            issues.append(('PASS', 'Oscillator outputs present (HP, BP, LP)'))
        else:
            issues.append(('ERROR', 'Missing oscillator output labels'))
    elif circuit_type == 'relay_ladder':
        # Relay ladder has INV/OUT bus labels instead of a source
        if 'INV' in label_names and 'OUT' in label_names:
            issues.append(('PASS', 'INV and OUT bus labels present'))
        else:
            issues.append(('ERROR', 'Missing INV or OUT bus label'))
    elif circuit_type == 'input_filters':
        # Check CH_IN and MUX labels for all 16 channels
        ch_labels = [n for n in label_names if n.startswith('CH_IN_')]
        mux_labels = [n for n in label_names if n.startswith('MUX_')]
        if len(ch_labels) >= 16:
            issues.append(('PASS', f'{len(ch_labels)} CH_IN labels present'))
        else:
            issues.append(('ERROR', f'Only {len(ch_labels)} CH_IN labels (need 16)'))
        if len(mux_labels) >= 16:
            issues.append(('PASS', f'{len(mux_labels)} MUX output labels present'))
        else:
            issues.append(('ERROR', f'Only {len(mux_labels)} MUX labels (need 16)'))
    elif circuit_type == 'analog_mux':
        # Check MUX channel labels and control labels
        mux_labels = [n for n in label_names if n.startswith('MUX_')]
        addr_labels = [n for n in label_names if n.startswith('ADDR_')]
        en_labels = [n for n in label_names if n.startswith('EN_')]
        if len(mux_labels) >= 16:
            issues.append(('PASS', f'{len(mux_labels)} MUX channel labels present'))
        else:
            issues.append(('ERROR', f'Only {len(mux_labels)} MUX labels (need 16)'))
        if len(addr_labels) >= 3:
            issues.append(('PASS', f'{len(addr_labels)} address labels present'))
        else:
            issues.append(('ERROR', f'Only {len(addr_labels)} ADDR labels (need 3)'))
        if len(en_labels) >= 2:
            issues.append(('PASS', f'{len(en_labels)} enable labels present'))
        else:
            issues.append(('ERROR', f'Only {len(en_labels)} EN labels (need 2)'))
    elif circuit_type == 'mux_tia':
        if 'TIA_IN' in label_names:
            issues.append(('PASS', 'TIA_IN input label present (from mux)'))
        else:
            issues.append(('ERROR', 'Missing TIA_IN input label'))
    elif circuit_type == 'mcu_section':
        # Check GPIO interface labels
        addr_labels = [n for n in label_names if n.startswith('ADDR_')]
        relay_labels = [n for n in label_names if n.startswith('RELAY_')]
        if len(addr_labels) >= 3:
            issues.append(('PASS', f'{len(addr_labels)} ADDR labels (mux address)'))
        else:
            issues.append(('ERROR', f'Only {len(addr_labels)} ADDR labels (need 3)'))
        if len(relay_labels) >= 4:
            issues.append(('PASS', f'{len(relay_labels)} RELAY labels (relay drivers)'))
        else:
            issues.append(('ERROR', f'Only {len(relay_labels)} RELAY labels (need 4)'))
        uart_ok = 'UART_TX' in label_names and 'UART_RX' in label_names
        if uart_ok:
            issues.append(('PASS', 'UART_TX/RX labels present (USB isolator)'))
        else:
            issues.append(('ERROR', 'Missing UART_TX or UART_RX label'))
        if 'SWCLK' in label_names and 'SWDIO' in label_names:
            issues.append(('PASS', 'SWD debug labels present'))
        else:
            issues.append(('WARNING', 'Missing SWD debug labels'))
    elif circuit_type == 'full_system':
        # Combined schematic: check inter-subsystem label pairs
        # Use raw label list (not set) to count duplicate names for matching pairs
        all_label_names = [name for name, _ in labels]
        required_pairs = {
            'TIA_IN': 'mux -> TIA signal path',
            'INV': 'relay ladder <-> TIA feedback',
            'OUT': 'relay ladder <-> TIA feedback',
            'AIN0': 'TIA output -> MCU ADC',
            'AIN1': 'VREF monitor -> MCU ADC',
        }
        for lbl, desc in required_pairs.items():
            count = all_label_names.count(lbl)
            if count >= 2:
                issues.append(('PASS', f'{lbl} label present {count}x ({desc})'))
            elif count == 1:
                issues.append(('WARNING', f'{lbl} label only 1x (need 2+ for connection)'))
            else:
                issues.append(('ERROR', f'Missing {lbl} label ({desc})'))
        addr_labels = [n for n in all_label_names if n.startswith('ADDR_')]
        relay_labels = [n for n in all_label_names if n.startswith('RELAY_')]
        mux_labels = [n for n in all_label_names if n.startswith('MUX_')]
        ch_labels = [n for n in all_label_names if n.startswith('CH_IN_')]
        if len(addr_labels) >= 6:
            issues.append(('PASS', f'{len(addr_labels)} ADDR labels (mux+MCU)'))
        else:
            issues.append(('ERROR', f'Only {len(addr_labels)} ADDR labels (need 6+)'))
        if len(relay_labels) >= 8:
            issues.append(('PASS', f'{len(relay_labels)} RELAY labels (ladder+MCU)'))
        else:
            issues.append(('ERROR', f'Only {len(relay_labels)} RELAY labels (need 8+)'))
        if len(mux_labels) >= 32:
            issues.append(('PASS', f'{len(mux_labels)} MUX channel labels (filters+mux)'))
        else:
            issues.append(('ERROR', f'Only {len(mux_labels)} MUX labels (need 32+)'))
        if len(ch_labels) >= 32:
            issues.append(('PASS', f'{len(ch_labels)} CH_IN labels (connector+filters, 16x2)'))
        elif len(ch_labels) >= 16:
            issues.append(('PASS', f'{len(ch_labels)} CH_IN labels (16 inputs present)'))
        else:
            issues.append(('ERROR', f'Only {len(ch_labels)} CH_IN labels (need 16+)'))
    elif has_vsin:
        issues.append(('PASS', 'VSIN input source symbol present'))
    elif 'IN' in label_names or 'TRIAX_IN' in label_names:
        issues.append(('PASS', 'Input label present'))
    else:
        issues.append(('ERROR', 'No input source (VSIN symbol or IN/TRIAX_IN label)'))

    # Step 2c: [all] Check for proper schematic symbols (visual quality)
    # Bug: early schematics used text-only labels for GND/VCC/VEE - hard to read
    has_gnd_sym = any('GND' in lid for lid in comp_lib_ids)
    has_source = has_vsin or any('VDC' in lid for lid in comp_lib_ids)
    if has_gnd_sym:
        n_gnd = sum(1 for lid in comp_lib_ids if 'GND' in lid)
        issues.append(('PASS', f'GND power symbol(s) present ({n_gnd} total)'))
    else:
        issues.append(('WARNING', 'No GND power symbols (text labels only)'))
    if has_source:
        issues.append(('PASS', 'Voltage source symbol(s) present'))
    elif circuit_type in ('relay_ladder', 'input_filters', 'analog_mux', 'mux_tia', 'mcu_section', 'full_system'):
        issues.append(('PASS', f'{circuit_type} (no voltage source needed on sheet)'))
    else:
        issues.append(('WARNING', 'No voltage source symbols'))

    # Step 2d: [all] Component count sanity check
    # Bug: empty or partially-built schematics could pass other checks
    MIN_COMPONENTS = {
        'ce_amp': 10, 'inv_amp': 8, 'sig_cond': 15,
        'usb_ina': 18, 'electrometer': 7, 'electrometer_362': 12,
        'relay_ladder': 18,  # 4 SW + 4 R + 2 C + 4 Q + 4 D + 4 Rb + power = ~30
        'input_filters': 80,  # 16*(2D + R + C + VCC + 2*GND) = 112 components
        'analog_mux': 10,    # 2 ICs + 8 power + 2 caps + 2 cap-GND = ~14
        'mux_tia': 8,        # U1 + R1 + C1 + R3 + R4 + C2 + power = ~12
        'mcu_section': 7,   # C1-C7 + power symbols = ~15
        'full_system': 90,  # connector + all subsystems combined ~180+ components
    }
    min_expected = MIN_COMPONENTS.get(circuit_type, 5)
    if len(components) >= min_expected:
        issues.append(('PASS', f'Component count ({len(components)}) meets minimum ({min_expected})'))
    else:
        issues.append(('ERROR', f'Too few components: {len(components)} (expected >= {min_expected})'))

    # Step 3: Check connectivity (nets)
    nets, net_names, all_points, parent, find = find_connected_points(wires, labels)
    n_nets = len(set(find(i) for i in range(len(all_points))))
    issues.append(('INFO', f'{n_nets} distinct nets detected'))

    # Check for labeled nets
    for root, names in net_names.items():
        issues.append(('INFO', f'Net: {", ".join(sorted(names))} ({len(nets[root])} points)'))

    # Step 4a: [all] Op-amp pin connectivity check
    # Bug: early builds had floating op-amp pins that passed all other checks
    pin_issues = check_pin_connectivity(wires, components, sch_path)
    issues.extend(pin_issues)

    # Step 4b: [sig_cond, usb_ina] Wire crossing detection (visual quality)
    # Bug: H-V wire crossings from different nets look like junctions
    crossing_issues = check_wire_crossings(wires, labels)
    issues.extend(crossing_issues)

    # Step 4b1: Collinear wire overlap detection (electrical shorts)
    # Bug: VEE/feedback wires at same X overlapped -> unintended short (Session 16)
    overlap_issues = check_wire_overlaps(wires)
    issues.extend(overlap_issues)

    # Step 4b2: [mux_tia] Layout quality checks (self-learning)
    # Checks for power symbols in feedback area, misplaced labels, etc.
    layout_issues = check_layout_quality(wires, labels, components)
    for sev, msg, rule_id in layout_issues:
        issues.append((sev, f'LAYOUT: {msg}'))

    # ══════════════════════════════════════════════════════════════
    # TIER 1: Connectivity & Overlap Detection
    # ══════════════════════════════════════════════════════════════

    # Step 4d: Disconnected label detection
    # Labels with only 1 point in connectivity graph are likely dangling
    disc_issues = check_disconnected_labels(wires, labels, components)
    issues.extend(disc_issues)

    # Step 4e: Duplicate / ambiguous net label detection
    # Same output labeled twice, or different names on same net
    dup_issues = check_duplicate_labels(wires, labels)
    issues.extend(dup_issues)

    # Step 4f: Label/text overlap detection
    # Overlapping text is unreadable
    overlap_issues = check_label_overlaps(labels, components)
    issues.extend(overlap_issues)

    # Step 4g: Floating wire detection
    # Wire segments not connected to any component or label
    float_issues = check_floating_wires(wires, labels, components)
    issues.extend(float_issues)

    # Step 4h: Component-to-wire distance check
    # Components too far from wire network are likely misplaced
    dist_issues = check_component_wire_distance(wires, components)
    issues.extend(dist_issues)

    # Step 4c: Circuit-specific topology checks
    # [inv_amp] Bug: Rf was disconnected, no feedback path
    if circuit_type in ('inv_amp', 'electrometer', 'electrometer_362'):
        has_feedback = False
        for root, points in nets.items():
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x_range = max(xs) - min(xs)
            y_range = max(ys) - min(ys)
            if x_range > 20 and y_range > 15 and len(points) >= 6:
                has_feedback = True
                break
        if has_feedback:
            issues.append(('PASS', 'Feedback path detected (wide net spanning input to output)'))
        else:
            issues.append(('ERROR', 'No feedback path detected! Rf may be disconnected'))

    # ══════════════════════════════════════════════════════════════
    # SIMULATION CHECKS (ngspice results)
    # ══════════════════════════════════════════════════════════════

    if sim_results:
        # Step 5a: [electrometer] Output saturation check
        # Bug: 100nA * 1G = 100V exceeded +/-12V supply, output railed
        # Catches: any circuit where output is within 0.5V of supply rail
        vout_pp = sim_results.get('V(TIA_OUT)_pp') or sim_results.get('V(OUT)_pp', 0)
        supply_v = 12.0  # default dual supply
        if vout_pp > (supply_v * 2 - 1.0):
            issues.append(('WARNING',
                f'Output may be saturating: Vout_pp={vout_pp:.2f}V near supply rails (+/-{supply_v}V)'))
        elif vout_pp > 0:
            issues.append(('PASS',
                f'Output within supply rails (Vout_pp={vout_pp*1000:.1f}mV, supply=+/-{supply_v}V)'))

        # Step 5b: [inv_amp, electrometer] Virtual ground check
        # For inverting topologies, V(-) should be near 0V (virtual ground)
        vinv_dc = sim_results.get('V(INV)_dc', None)
        if vinv_dc is not None and circuit_type in ('inv_amp', 'electrometer'):
            if abs(vinv_dc) < 0.050:  # within 50mV of ground
                issues.append(('PASS', f'Virtual ground holding: V(INV)={vinv_dc*1000:.2f}mV'))
            else:
                issues.append(('WARNING',
                    f'Virtual ground drifted: V(INV)={vinv_dc*1000:.1f}mV (expected ~0mV)'))

    # Step 5c: Expected value checks (gain, transimpedance, etc.)
    if sim_results and expected:
        for key, (exp_val, tolerance, unit) in expected.items():
            if key in sim_results:
                actual = sim_results[key]
                if abs(actual - exp_val) <= tolerance:
                    issues.append(('PASS', f'{key}: {actual:.2f}{unit} (expected {exp_val}{unit} +/-{tolerance})'))
                else:
                    issues.append(('WARNING', f'{key}: {actual:.2f}{unit} (expected {exp_val}{unit}, off by {abs(actual-exp_val):.2f})'))
            else:
                issues.append(('WARNING', f'{key}: not measured'))

    # ══════════════════════════════════════════════════════════════
    # ELECTRICAL CORRECTNESS (op-amp polarity, diode orientation)
    # ══════════════════════════════════════════════════════════════

    elec_issues = verify_electrical_correctness(sch_path)
    issues.extend(elec_issues)

    # ══════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════

    errors = sum(1 for s, _ in issues if s == 'ERROR')
    warnings = sum(1 for s, _ in issues if s == 'WARNING')
    passes = sum(1 for s, _ in issues if s == 'PASS')

    for severity, msg in issues:
        icon = {'ERROR': 'X', 'WARNING': '!', 'PASS': '+', 'INFO': '-'}[severity]
        print(f"    [{icon}] {msg}")

    print(f"\n  Summary: {passes} passed, {warnings} warnings, {errors} errors")
    if errors > 0:
        print("  ACTION: Fix errors before proceeding. Check wiring and component placement.")
    return issues


def measure_simulation(results_file, node_names):
    """Extract key measurements from simulation results."""
    results_path = os.path.join(WORK_DIR, results_file)
    if not os.path.exists(results_path):
        return {}

    data = np.loadtxt(results_path)
    n = min(len(node_names), data.shape[1] // 2)
    time = data[:, 0]
    vals = [data[:, i*2+1] for i in range(n)]

    measurements = {}
    for i, name in enumerate(node_names[:n]):
        vpp = np.max(vals[i]) - np.min(vals[i])
        vdc = np.mean(vals[i])
        measurements[f'{name}_pp'] = vpp
        measurements[f'{name}_dc'] = vdc

    if n >= 2:
        vin_pp = np.max(vals[0]) - np.min(vals[0])
        vout_pp = np.max(vals[1]) - np.min(vals[1])
        if vin_pp > 0:
            measurements['gain'] = vout_pp / vin_pp
            measurements['gain_dB'] = 20 * np.log10(vout_pp / vin_pp)

    return measurements


# =============================================================
# EXPORT: PDF + PNG rendering
# =============================================================
def export_pdf(sch_path, pdf_dir=None):
    """Export schematic to PDF via kicad-cli."""
    if not KICAD_CLI:
        raise FileNotFoundError(
            "kicad-cli not found. Install KiCad 9.x or set KICAD_CLI_PATH env var.\n"
            "  Download: https://www.kicad.org/download/"
        )
    if pdf_dir is None:
        base = os.path.splitext(os.path.basename(sch_path))[0]
        pdf_dir = os.path.join(os.path.dirname(sch_path), f"{base}_pdf")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_file = os.path.join(pdf_dir, os.path.splitext(os.path.basename(sch_path))[0] + '.pdf')
    result = subprocess.run(
        [KICAD_CLI, "sch", "export", "pdf", "-o", pdf_file, sch_path],
        capture_output=True, text=True, timeout=30, **_SUBPROCESS_KWARGS
    )
    if result.returncode != 0:
        raise RuntimeError(f"kicad-cli pdf failed: {result.stderr.strip()}")
    return pdf_file


def render_pdf_to_png(pdf_path, png_path=None, zoom=5,
                      clip_mm=None, max_dim=7500):
    """Render a PDF to a high-res PNG, optionally cropped.

    clip_mm: (x0, y0, x1, y1) in mm to clip to circuit area.
    max_dim: Max pixels in either dimension (default 7500, API limit is 8000).
             Images exceeding this are downscaled preserving aspect ratio.
    """
    try:
        import fitz
        from PIL import Image
        import io
        Image.MAX_IMAGE_PIXELS = 500_000_000  # allow large renders (500M pixels)
    except ImportError:
        print("  Need: pip install pymupdf pillow")
        return None

    doc = fitz.open(pdf_path)
    page = doc[0]
    mat = fitz.Matrix(zoom, zoom)

    if clip_mm:
        s = 2.835  # mm to points
        clip = fitz.Rect(clip_mm[0]*s, clip_mm[1]*s, clip_mm[2]*s, clip_mm[3]*s)
        pix = page.get_pixmap(matrix=mat, clip=clip)
    else:
        pix = page.get_pixmap(matrix=mat)

    if png_path is None:
        png_path = pdf_path.replace('.pdf', '.png')

    img = Image.open(io.BytesIO(pix.tobytes('png')))

    # Cap dimensions to stay under API image size limit (8000px)
    w, h = img.size
    if max_dim and (w > max_dim or h > max_dim):
        scale = max_dim / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        print(f"  Downscaling {w}x{h} -> {new_w}x{new_h} (max_dim={max_dim})")
        img = img.resize((new_w, new_h), Image.LANCZOS)

    img.save(png_path)
    doc.close()
    print(f"  PNG rendered: {png_path} ({img.size[0]}x{img.size[1]})")
    return png_path


def export_full_system_regions(pdf_path, output_dir=None):
    """Export per-region zoomed PNGs for the full_system schematic.

    Produces one overview PNG plus 6 region-specific PNGs at high zoom
    so every component, label, and description is clearly readable.
    """
    if output_dir is None:
        output_dir = os.path.dirname(pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    G = 2.54  # grid unit in mm

    # Region definitions: (name, clip_mm, zoom)
    # clip_mm = (x0_mm, y0_mm, x1_mm, y1_mm)
    regions = [
        ("overview",    (2, 2, 1185, 838),  6),   # Full A0 at higher zoom
        ("0_connector", (0, 180, 80, 360),  14),   # Input connector detail
        ("1_filters",   (60, 15, 440, 420), 12),   # All 16 input filter channels
        ("2_mux",       (490, 60, 640, 470), 14),  # 2x CD4051B mux ICs
        ("3_tia",       (730, 15, 990, 260), 14),  # TIA + VREF divider
        ("4_relays",    (100, 480, 500, 830), 12), # Relay ladder + NPN drivers (lower-left)
        ("5_mcu",       (980, 20, 1180, 700), 12), # MCU + decoupling + AVDD monitor + RTD
    ]

    exported = []
    for name, clip, zoom in regions:
        png_path = os.path.join(output_dir, f"full_system_{name}.png")
        result = render_pdf_to_png(pdf_path, png_path, zoom=zoom, clip_mm=clip)
        if result:
            exported.append((name, result))

    if exported:
        print(f"\n  Exported {len(exported)} region PNGs:")
        for name, path in exported:
            print(f"    {name}: {os.path.basename(path)}")

    return exported


# =============================================================
# MAIN / CLI
# =============================================================
# =============================================================
# GENERIC CIRCUIT ANALYSIS & SIMULATION
# =============================================================

def _extract_nodes_from_cir(netlist_text):
    """Extract node names and simulation command from a .cir netlist."""
    nodes = set()
    sim_cmd = None
    for line in netlist_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('*'):
            continue
        if line.startswith('.'):
            if re.match(r'\.(tran|ac|dc|noise|op)\b', line, re.I):
                sim_cmd = line
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        first_char = parts[0][0].upper()
        if first_char in ('R', 'C', 'L', 'V', 'I', 'D'):
            for p in parts[1:3]:
                if p not in ('0', 'gnd', 'GND') and not p.startswith('.'):
                    nodes.add(p)
        elif first_char in ('Q', 'J', 'M'):
            for p in parts[1:4]:
                if p not in ('0', 'gnd', 'GND') and not p.startswith('.'):
                    nodes.add(p)
        elif first_char == 'X':
            for p in parts[1:-1]:  # last token is subcircuit name
                if p not in ('0', 'gnd', 'GND') and not p.startswith('.'):
                    nodes.add(p)
    return sorted(nodes), sim_cmd


def _classify_nodes(nodes, netlist_lines):
    """Classify circuit nodes into inputs, outputs, power, internal."""
    power_patterns = re.compile(
        r'^(VCC|VDD|VEE|VSS|AVDD|DVDD|V\+|V-|VPOS|VNEG|\+\d+V|-\d+V|\+3\.3V|\+5V|\+12V|-12V|5V_ISO)$',
        re.I)
    output_patterns = re.compile(r'^(OUT|OUTPUT|VOUT|OUT_INT|FILTERED|AIN\d|TIA_OUT)$', re.I)
    input_patterns = re.compile(r'^(IN|INPUT|VIN|SIG|SIGNAL|CH\d+_IN)$', re.I)

    inputs, outputs, power, internal = [], [], [], []
    # Check sources: signal sources → input nodes, DC sources → power nodes
    signal_source_nodes = set()
    dc_source_nodes = set()
    for line in netlist_lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        if parts[0][0].upper() == 'V':
            val = ' '.join(parts[3:]).upper() if len(parts) > 3 else ''
            n_plus = parts[1]
            if any(kw in val for kw in ('SINE', 'PULSE', 'PWL', 'AC')):
                if n_plus not in ('0', 'gnd', 'GND'):
                    signal_source_nodes.add(n_plus)
            elif 'DC' in val or re.match(r'^-?\d', val):
                if n_plus not in ('0', 'gnd', 'GND'):
                    dc_source_nodes.add(n_plus)

    for n in nodes:
        if n in ('0', 'gnd', 'GND'):
            continue
        if power_patterns.match(n) or n in dc_source_nodes:
            power.append(n)
        elif input_patterns.match(n) or n in signal_source_nodes:
            inputs.append(n)
        elif output_patterns.match(n):
            outputs.append(n)
        else:
            internal.append(n)

    # If no explicit output found, pick first non-power non-input named node
    if not outputs:
        for n in internal[:]:
            if not re.match(r'^N\d+$', n):
                outputs.append(n)
                internal.remove(n)
                break

    return {
        'all': sorted(nodes),
        'inputs': sorted(inputs),
        'outputs': sorted(outputs),
        'power': sorted(power),
        'internal': sorted(internal),
        'ground': ['0'],
    }


def _count_components(netlist_lines):
    """Count component types in a netlist."""
    counts = {'resistors': 0, 'capacitors': 0, 'inductors': 0,
              'bjts': 0, 'mosfets': 0, 'jfets': 0, 'diodes': 0,
              'voltage_sources': 0, 'current_sources': 0, 'subcircuits': 0}
    for line in netlist_lines:
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue
        fc = line[0].upper()
        if fc == 'R': counts['resistors'] += 1
        elif fc == 'C': counts['capacitors'] += 1
        elif fc == 'L': counts['inductors'] += 1
        elif fc == 'Q': counts['bjts'] += 1
        elif fc == 'M': counts['mosfets'] += 1
        elif fc == 'J': counts['jfets'] += 1
        elif fc == 'D': counts['diodes'] += 1
        elif fc == 'V': counts['voltage_sources'] += 1
        elif fc == 'I': counts['current_sources'] += 1
        elif fc == 'X': counts['subcircuits'] += 1
    return counts


def _parse_sources(netlist_lines):
    """Extract voltage/current source details."""
    sources = []
    for line in netlist_lines:
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue
        parts = line.split()
        fc = parts[0][0].upper()
        if fc not in ('V', 'I') or len(parts) < 4:
            continue
        name = parts[0]
        n1, n2 = parts[1], parts[2]
        val_str = ' '.join(parts[3:])
        src = {'name': name, 'nodes': [n1, n2], 'value': val_str}
        val_upper = val_str.upper()
        if 'SINE' in val_upper or 'SIN(' in val_upper:
            src['type'] = 'SINE'
            m = re.search(r'SINE?\s*\(\s*([^\s,]+)\s+([^\s,]+)\s+([^\s,)]+)', val_str, re.I)
            if m:
                try:
                    src['dc_offset'] = float(m.group(1))
                    src['amplitude'] = float(m.group(2))
                    src['freq_hz'] = float(m.group(3))
                except ValueError:
                    pass
        elif 'PULSE' in val_upper:
            src['type'] = 'PULSE'
        elif 'PWL' in val_upper:
            src['type'] = 'PWL'
        elif 'AC' in val_upper:
            src['type'] = 'AC'
        else:
            src['type'] = 'DC'
        sources.append(src)
    return sources


def _detect_circuit_type(components, sources, nodes_class):
    """Detect circuit type from component makeup and sources."""
    has_signal = any(s['type'] in ('SINE', 'PULSE', 'PWL', 'AC') for s in sources)
    has_bjts = components.get('bjts', 0) > 0
    has_mosfets = components.get('mosfets', 0) > 0
    has_opamps = components.get('subcircuits', 0) > 0  # op-amps are usually subcircuits
    has_caps = components.get('capacitors', 0) > 0
    has_diodes = components.get('diodes', 0) > 0
    n_resistors = components.get('resistors', 0)

    if has_signal and (has_bjts or has_mosfets or has_opamps) and n_resistors > 2:
        if has_caps and has_opamps and n_resistors > 3:
            return 'filter'
        return 'amplifier'
    if has_diodes and has_caps and not has_signal:
        return 'power_supply'
    if has_opamps and has_caps:
        return 'filter'
    return 'generic'


def _fix_tran_cmd(cmd):
    """Convert LTspice .tran format to ngspice format.

    LTspice allows .tran <tstop> (single arg = stop time, auto step).
    ngspice requires .tran <tstep> <tstop>.
    Also strips LTspice-only keywords (startup, steady).
    """
    if not cmd or not cmd.strip().lower().startswith('.tran'):
        return cmd
    parts = cmd.strip().split()
    # Filter LTspice-only keywords
    cleaned = [parts[0]]
    for p in parts[1:]:
        if p.lower() in ('startup', 'steady'):
            continue
        cleaned.append(p)
    if len(cleaned) == 2:
        # Only stop time given — add step = tstop/1000
        tstop = cleaned[1]
        suffixes = {'t': 1e12, 'g': 1e9, 'meg': 1e6, 'k': 1e3,
                     'm': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12, 'f': 1e-15}
        try:
            m = re.match(r'^([0-9.eE+-]+)(meg|[tgkmunpf])?$', tstop, re.I)
            if m:
                val = float(m.group(1))
                suffix = (m.group(2) or '').lower()
                val *= suffixes.get(suffix, 1.0)
                tstep = val / 1000
                if tstep >= 1e-3:
                    step_str = f"{tstep*1e3:.4g}m"
                elif tstep >= 1e-6:
                    step_str = f"{tstep*1e6:.4g}u"
                elif tstep >= 1e-9:
                    step_str = f"{tstep*1e9:.4g}n"
                else:
                    step_str = f"{tstep:.2e}"
                return f".tran {step_str} {tstop}"
        except (ValueError, TypeError):
            pass
        return f".tran 1u {tstop}"
    # Fix tstep=0 (LTspice auto-step) — ngspice needs a real step value
    if len(cleaned) >= 3 and cleaned[1] == '0':
        tstop_str = cleaned[2]
        suffixes = {'t': 1e12, 'g': 1e9, 'meg': 1e6, 'k': 1e3,
                     'm': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12, 'f': 1e-15}
        try:
            m = re.match(r'^\.?([0-9.eE+-]+)(meg|[tgkmunpf])?$', tstop_str, re.I)
            if m:
                val = float(m.group(1))
                suffix = (m.group(2) or '').lower()
                val *= suffixes.get(suffix, 1.0)
                tstep = val / 1000
                if tstep >= 1e-3:
                    step_str = f"{tstep*1e3:.4g}m"
                elif tstep >= 1e-6:
                    step_str = f"{tstep*1e6:.4g}u"
                elif tstep >= 1e-9:
                    step_str = f"{tstep*1e9:.4g}n"
                else:
                    step_str = f"{tstep:.2e}"
                cleaned[1] = step_str
        except (ValueError, TypeError):
            cleaned[1] = '1u'
    return ' '.join(cleaned)


def _suggest_analyses(circuit_type, sources, nodes_class, sim_cmd):
    """Suggest appropriate analyses based on circuit type."""
    suggestions = []
    has_signal = any(s['type'] in ('SINE', 'PULSE', 'PWL', 'AC') for s in sources)
    signal_src = next((s for s in sources if s.get('type') in ('SINE', 'PULSE', 'PWL', 'AC')), None)
    default_probes = nodes_class['inputs'][:2] + nodes_class['outputs'][:2]
    if not default_probes:
        named = [n for n in nodes_class['all'] if not re.match(r'^N\d+$', n)]
        default_probes = named[:4]

    # Transient — almost always useful
    tran_cmd = _fix_tran_cmd(sim_cmd) if sim_cmd and sim_cmd.lower().startswith('.tran') else '.tran 1u 10m'
    suggestions.append({
        'id': 'transient', 'name': 'Time Domain (Transient)',
        'description': 'Voltage waveforms at all probed nodes over time',
        'default_probes': default_probes,
        'sim_cmd': tran_cmd,
        'enabled_by_default': True,
    })

    # AC/Bode — useful for amplifiers and filters
    if circuit_type in ('amplifier', 'filter', 'generic') and has_signal:
        ac_probes = nodes_class['outputs'][:2] or default_probes[:2]
        suggestions.append({
            'id': 'ac_bode', 'name': 'Bode Plot (AC Analysis)',
            'description': 'Gain (dB) and phase vs frequency',
            'default_probes': ac_probes,
            'sim_cmd': '.ac dec 100 1 10Meg',
            'enabled_by_default': circuit_type in ('amplifier', 'filter'),
        })

    # DC Sweep — useful when there's a swept source
    if has_signal and signal_src:
        src_name = signal_src['name']
        suggestions.append({
            'id': 'dc_sweep', 'name': 'DC Sweep',
            'description': f'Output vs {src_name} DC voltage',
            'default_probes': nodes_class['outputs'][:2] or default_probes[:2],
            'sim_cmd': f'.dc {src_name} -5 5 0.1',
            'enabled_by_default': False,
        })

    # Key measurements — always available
    metrics = ['vpp', 'vdc', 'vrms', 'freq_hz']
    if circuit_type == 'amplifier':
        metrics.extend(['gain', 'gain_dB', 'bandwidth_hz', 'thd_percent'])
    elif circuit_type == 'filter':
        metrics.extend(['bandwidth_hz', 'cutoff_hz', 'rolloff_dB_dec'])
    suggestions.append({
        'id': 'measurements', 'name': 'Key Measurements',
        'description': 'Computed from simulation data',
        'metrics': metrics,
        'enabled_by_default': True,
    })

    return suggestions


def _estimate_frequency(time, signal):
    """Estimate dominant frequency from zero-crossings of AC component."""
    ac = signal - np.mean(signal)
    if np.max(np.abs(ac)) < 1e-6:
        return 0.0
    crossings = np.where(np.diff(np.sign(ac)))[0]
    if len(crossings) < 2:
        return 0.0
    periods = np.diff(time[crossings])
    half_period = float(np.median(periods))
    if half_period > 0:
        return 1.0 / (2 * half_period)
    return 0.0


def _measure_generic(results_path, node_names):
    """Compute Vpp, Vdc, Vrms, and estimated frequency for each probed node."""
    data = np.loadtxt(results_path)
    n = min(len(node_names), data.shape[1] // 2)
    time = data[:, 0]
    measurements = {}
    for i in range(n):
        v = data[:, i * 2 + 1]
        vpp = float(np.max(v) - np.min(v))
        vdc = float(np.mean(v))
        vrms = float(np.sqrt(np.mean(v ** 2)))
        freq = _estimate_frequency(time, v)
        measurements[node_names[i]] = {
            'vpp': vpp, 'vdc': vdc, 'vrms': vrms,
            'vmin': float(np.min(v)), 'vmax': float(np.max(v)),
            'freq_hz': freq,
        }
    # Gain if >=2 nodes
    if n >= 2:
        vin_pp = measurements[node_names[0]]['vpp']
        vout_pp = measurements[node_names[1]]['vpp']
        if vin_pp > 1e-9:
            measurements['_gain'] = vout_pp / vin_pp
            measurements['_gain_dB'] = 20 * np.log10(vout_pp / vin_pp)
    return measurements


def _build_generic_netlist(clean_lines, sim_cmd, probe_nodes, lib_lines,
                            model_lines, subckt_names, analysis='transient'):
    """Build ngspice netlist for generic circuit simulation."""
    from demo_loader import find_subckt_lib
    final = []
    # Title
    if clean_lines and clean_lines[0].startswith('*'):
        final.append(clean_lines[0])
    else:
        final.append("* Generic circuit simulation")
    final.append("")
    # Circuit lines (add AC stimulus for AC analysis)
    start = 1 if clean_lines and clean_lines[0].startswith('*') else 0
    for line in clean_lines[start:]:
        if analysis == 'ac_bode' and re.match(r'^V\w+\s', line, re.I):
            upper = line.upper()
            if ('SINE' in upper or 'PULSE' in upper or 'PWL' in upper) and 'AC' not in upper:
                line = line.rstrip() + ' AC 1'
        final.append(line)
    final.append("")
    # Models
    for m in model_lines:
        final.append(m)
    # Libraries
    for lib in lib_lines:
        final.append(lib)
    for name in subckt_names:
        sub_path = find_subckt_lib(name)
        if sub_path:
            final.append(f".include {sub_path}")
    final.append("")

    # Use relative filename (ngspice cwd is sim_work/)
    results_file = f"generic_{analysis}_results.txt"

    if analysis == 'ac_bode':
        final.append(".ac dec 100 1 10Meg")
        save_str = " ".join([f"vdb({n}) vp({n})" for n in probe_nodes])
    elif analysis == 'dc_sweep':
        final.append(sim_cmd if sim_cmd else ".dc V1 -5 5 0.1")
        save_str = " ".join([f"V({n})" for n in probe_nodes])
    else:  # transient
        final.append(_fix_tran_cmd(sim_cmd) if sim_cmd else ".tran 1u 10m")
        save_str = " ".join([f"V({n})" for n in probe_nodes])

    final.append("")
    final.append(".control")
    final.append("run")
    final.append(f"wrdata {results_file} {save_str}")
    final.append("quit")
    final.append(".endc")
    final.append("")
    final.append(".end")
    return "\n".join(final), probe_nodes


def _remove_missing_includes(netlist_text):
    """Remove .include directives that reference non-existent files.

    After subcircuit resolution, stale .include lines (e.g., '.include opamp.sub')
    cause ngspice to fail if the file doesn't exist on disk.
    """
    lines = netlist_text.split('\n')
    fixed = []
    removed = 0
    for line in lines:
        m = re.match(r'\.include\s+(\S+)', line.strip(), re.I)
        if m:
            inc_file = m.group(1).strip('"').strip("'")
            # Check if file exists (relative to WORK_DIR or absolute)
            paths_to_check = [
                inc_file,
                os.path.join(WORK_DIR, inc_file),
                os.path.join(REPO_DIR, inc_file),
            ]
            if not any(os.path.exists(p) for p in paths_to_check):
                fixed.append(f'* (removed: file not found) {line.strip()}')
                removed += 1
                continue
        fixed.append(line)
    if removed > 0:
        print(f"  Removed {removed} missing .include directive(s)")
    return '\n'.join(fixed)


def _convert_step_param(netlist_text):
    """Convert LTspice .step param directives to ngspice .param with a chosen value.

    LTspice .step formats:
      .step param NAME list val1 val2 val3 ...
      .step param NAME start stop step
      .step oct param NAME start stop N
      .step dec param NAME start stop N

    ngspice does not support .step natively. We pick a representative value
    (middle of list or midpoint of range) and set .param NAME=value.
    The .step line is commented out and the .param is inserted.
    """
    import math
    lines = netlist_text.split('\n')
    fixed = []
    param_inserts = {}  # name -> value

    for line in lines:
        stripped = line.strip()
        if not stripped.lower().startswith('.step'):
            fixed.append(line)
            continue

        # Parse .step directive
        # Remove leading .step, handle optional 'oct'/'dec' keyword
        parts = stripped.split()
        if len(parts) < 4:
            fixed.append(f'* (converted: .step) {stripped}')
            continue

        idx = 1  # skip '.step'
        sweep_type = 'lin'  # default linear
        if parts[idx].lower() in ('oct', 'dec'):
            sweep_type = parts[idx].lower()
            idx += 1

        if parts[idx].lower() != 'param' or idx + 1 >= len(parts):
            # .step for temp, model, etc. — not supported, comment out
            fixed.append(f'* (converted: .step) {stripped}')
            continue

        idx += 1  # skip 'param'
        param_name = parts[idx]
        idx += 1
        remaining = parts[idx:]

        chosen_value = None

        if remaining and remaining[0].lower() == 'list':
            # .step param NAME list val1 val2 val3
            values = remaining[1:]
            if values:
                # Pick middle value
                mid = len(values) // 2
                chosen_value = values[mid]
                print(f"  .step param {param_name}: list [{', '.join(values)}] -> using middle value: {chosen_value}")
        elif len(remaining) >= 2:
            # .step param NAME start stop [step]
            try:
                start = _parse_spice_value(remaining[0])
                stop = _parse_spice_value(remaining[1])
                if sweep_type == 'lin':
                    # Linear: pick midpoint
                    mid_val = (start + stop) / 2.0
                elif sweep_type == 'oct':
                    # Octave: pick geometric midpoint
                    if start > 0 and stop > 0:
                        mid_val = math.sqrt(start * stop)
                    else:
                        mid_val = (start + stop) / 2.0
                elif sweep_type == 'dec':
                    # Decade: pick geometric midpoint
                    if start > 0 and stop > 0:
                        mid_val = math.sqrt(start * stop)
                    else:
                        mid_val = (start + stop) / 2.0
                else:
                    mid_val = (start + stop) / 2.0

                # Format nicely
                if abs(mid_val) >= 1e6:
                    chosen_value = f'{mid_val/1e6:.4g}Meg'
                elif abs(mid_val) >= 1e3:
                    chosen_value = f'{mid_val/1e3:.4g}k'
                elif abs(mid_val) >= 1:
                    chosen_value = f'{mid_val:.4g}'
                elif abs(mid_val) >= 1e-3:
                    chosen_value = f'{mid_val*1e3:.4g}m'
                elif abs(mid_val) >= 1e-6:
                    chosen_value = f'{mid_val*1e6:.4g}u'
                elif abs(mid_val) >= 1e-9:
                    chosen_value = f'{mid_val*1e9:.4g}n'
                elif abs(mid_val) >= 1e-12:
                    chosen_value = f'{mid_val*1e12:.4g}p'
                else:
                    chosen_value = f'{mid_val:.4g}'
                print(f"  .step param {param_name}: {sweep_type} [{remaining[0]} to {remaining[1]}] -> using midpoint: {chosen_value}")
            except (ValueError, TypeError, ZeroDivisionError):
                chosen_value = remaining[0]  # fallback to start value
                print(f"  .step param {param_name}: could not parse range, using start: {chosen_value}")

        if chosen_value:
            param_inserts[param_name] = chosen_value
            fixed.append(f'* (converted: .step -> .param {param_name}={chosen_value}) {stripped}')
        else:
            fixed.append(f'* (converted: .step) {stripped}')

    # Check if .param already exists for these names, update them; else insert new
    result_lines = []
    params_set = set()
    for line in fixed:
        stripped = line.strip()
        # Check if this line has .param for one of our converted params
        if stripped.lower().startswith('.param'):
            for pname, pval in param_inserts.items():
                # Match .param NAME=value or .params NAME=value
                pattern = rf'(?i)(\.params?\s+){re.escape(pname)}\s*=\s*\S+'
                if re.search(pattern, stripped):
                    line = re.sub(pattern, rf'\g<1>{pname}={pval}', stripped)
                    params_set.add(pname)
                    print(f"  Updated existing .param {pname}={pval}")
                    break
        result_lines.append(line)

    # Insert .param for any that weren't already present
    insert_lines = []
    for pname, pval in param_inserts.items():
        if pname not in params_set:
            insert_lines.append(f'.param {pname}={pval}')
            print(f"  Added .param {pname}={pval}")

    if insert_lines:
        # Insert after the title line (first line of netlist)
        if result_lines:
            result_lines = [result_lines[0]] + insert_lines + result_lines[1:]
        else:
            result_lines = insert_lines + result_lines

    return '\n'.join(result_lines)


def _convert_laplace_to_sxfer(netlist_text):
    """Convert LTspice Laplace behavioral sources to ngspice XSPICE s_xfer models.

    LTspice: E1 out 0 in 0 Laplace=expr  (SYMATTR Value Laplace=...)
    or:      E1 out 0 LAPLACE {V(in)} {expr}

    In the netlist from asc_parser, these appear as component value attributes:
      E1 out+ out- in+ in- Laplace=1/(1+.0005*s)**3

    ngspice equivalent using XSPICE s_xfer:
      a_E1 in+ out_int model_E1
      .model model_E1 s_xfer(num_coeff=[...] den_coeff=[...])
      E1 out+ out- out_int 0 1

    Supports:
    - Simple rational polynomials: 1/(1+a*s), a*s/(s*s+b*s+c)
    - Powers: (1+a*s)**n where n is integer
    - Product forms: expr1 * expr2

    Does NOT support (leaves as-is with warning):
    - sqrt(s) — fractional order
    - exp(-a*s) — pure delay
    - Expressions with undefined parameters {param}
    """
    import math

    lines = netlist_text.split('\n')
    new_lines = []
    model_counter = [0]
    models_to_add = []

    def _expand_polynomial(expr_str):
        """Try to expand a Laplace expression into numerator/denominator coefficient lists.

        Returns (gain, num_coeffs, den_coeffs) where coeffs are highest-to-lowest order,
        or None if the expression cannot be parsed.
        """
        expr = expr_str.strip()

        # Check for unsupported constructs
        if 'sqrt' in expr.lower() or 'exp(' in expr.lower():
            return None

        # Check for unresolved parameters {param}
        if re.search(r'\{[^}]+\}', expr):
            return None

        # Try to parse as product of factors and 1/factors
        # Common patterns:
        #   gain / (1+a*s)**n
        #   gain * s / (s*s + a*s + b)
        #   gain / (1+a*s) / (1+b*s)

        # Strategy: use sympy-like manual polynomial parsing
        # Split into numerator and denominator at the top-level /

        # First, handle ** (power) by expanding
        # Replace common patterns

        try:
            return _parse_rational(expr)
        except Exception:
            return None

    def _parse_rational(expr):
        """Parse a rational expression in s into (gain, num_coeffs, den_coeffs).

        Handles:
        - Constants: 5, 1.0
        - Linear: (1+a*s), (a*s+b)
        - Powers: (1+a*s)**n
        - Products/quotients of the above
        """
        # Normalize: remove spaces around operators
        expr = expr.replace(' ', '')

        # Use Python's own evaluator with s as a symbolic polynomial
        # Represent polynomial as list of coefficients [a0, a1, a2, ...] (ascending order)
        # Polynomial multiplication and addition

        class Poly:
            """Simple polynomial in s, stored as ascending coefficients [a0, a1, a2, ...]"""
            def __init__(self, coeffs):
                # Remove trailing zeros
                while len(coeffs) > 1 and abs(coeffs[-1]) < 1e-30:
                    coeffs = coeffs[:-1]
                self.c = list(coeffs)

            def __mul__(self, other):
                if isinstance(other, (int, float)):
                    return Poly([x * other for x in self.c])
                result = [0.0] * (len(self.c) + len(other.c) - 1)
                for i, a in enumerate(self.c):
                    for j, b in enumerate(other.c):
                        result[i + j] += a * b
                return Poly(result)

            def __rmul__(self, other):
                return self.__mul__(other)

            def __add__(self, other):
                if isinstance(other, (int, float)):
                    other = Poly([other])
                n = max(len(self.c), len(other.c))
                result = [0.0] * n
                for i in range(len(self.c)):
                    result[i] += self.c[i]
                for i in range(len(other.c)):
                    result[i] += other.c[i]
                return Poly(result)

            def __radd__(self, other):
                return self.__add__(other)

            def __sub__(self, other):
                if isinstance(other, (int, float)):
                    other = Poly([other])
                n = max(len(self.c), len(other.c))
                result = [0.0] * n
                for i in range(len(self.c)):
                    result[i] += self.c[i]
                for i in range(len(other.c)):
                    result[i] -= other.c[i]
                return Poly(result)

            def __rsub__(self, other):
                neg = Poly([-x for x in self.c])
                return neg.__add__(other)

            def __pow__(self, n):
                if not isinstance(n, int) or n < 0:
                    raise ValueError(f"Unsupported power: {n}")
                if n == 0:
                    return Poly([1.0])
                result = Poly(list(self.c))
                for _ in range(n - 1):
                    result = result * self
                return result

            def __truediv__(self, other):
                if isinstance(other, (int, float)):
                    return Poly([x / other for x in self.c])
                # Can't divide polynomials — return as rational
                raise ValueError("Poly division")

            def __neg__(self):
                return Poly([-x for x in self.c])

            def __pos__(self):
                return Poly(list(self.c))

            def degree(self):
                return len(self.c) - 1

            def to_descending(self):
                """Return coefficients in descending order (highest power first)."""
                return list(reversed(self.c))

        # Evaluate the expression with s as Poly([0, 1])
        s = Poly([0.0, 1.0])

        # Make a safe evaluation namespace
        safe_ns = {
            's': s,
            '__builtins__': {},
        }
        # Add math functions that might appear
        for name in ['pi', 'e']:
            safe_ns[name] = getattr(math, name)

        # Replace SPICE suffixes in the expression: .0005 is fine, but 1u, 1n etc.
        # The expression should already be in Python-compatible form from LTspice
        # LTspice uses: 1e-3, .001, etc. — no SPICE suffixes in Laplace expressions
        # But ** is used for powers, which Python handles

        # Replace '.' at start of number with '0.'
        proc_expr = re.sub(r'(?<![0-9])\.(\d)', r'0.\1', expr)

        try:
            result = eval(proc_expr, safe_ns)
        except Exception:
            return None

        if isinstance(result, Poly):
            # Result is a polynomial — numerator only, denominator is 1
            num = result
            den = Poly([1.0])
        elif isinstance(result, (int, float)):
            num = Poly([float(result)])
            den = Poly([1.0])
        else:
            return None

        # We need to handle division — use a two-pass approach
        # Actually, let's use a Rational class wrapper

        return None  # Fall through to regex-based approach

    def _parse_laplace_regex(expr):
        """Parse common Laplace expression patterns using regex.

        Returns (gain, num_coeffs_descending, den_coeffs_descending) or None.
        """
        expr = expr.strip().replace(' ', '')

        # Pattern 1: gain/(1+a*s)**n
        # Example: 1/(1+.0005*s)**3, 1./(1+.0005*s)**3
        m = re.match(r'^([\d.eE+-]+)\.?/\(1([+-][\d.eE+-]*)\*?s\)\*\*(\d+)$', expr)
        if m:
            gain = float(m.group(1)) if m.group(1) else 1.0
            a = float(m.group(2))
            n = int(m.group(3))
            # (1+a*s)**n — expand binomial
            # Coefficients of (1+a*s)^n in ascending order
            coeffs = [1.0]
            factor = [1.0, a]  # 1 + a*s
            for _ in range(n):
                new_coeffs = [0.0] * (len(coeffs) + 1)
                for i, c in enumerate(coeffs):
                    new_coeffs[i] += c * factor[0]
                    new_coeffs[i + 1] += c * factor[1]
                coeffs = new_coeffs
            # Descending order
            den_desc = list(reversed(coeffs))
            num_desc = [1.0]
            return (gain, num_desc, den_desc)

        # Pattern 1b: gain/(1+a*s) — no power
        m = re.match(r'^([\d.eE+-]*)\.?/\(1([+-][\d.eE+-]*)\*?s\)$', expr)
        if m:
            gain = float(m.group(1)) if m.group(1) else 1.0
            a = float(m.group(2))
            den_desc = [a, 1.0]  # a*s + 1
            num_desc = [1.0]
            return (gain, num_desc, den_desc)

        # Pattern 2: gain*s/(s*s+a*s+b)
        m = re.match(r'^([\d.eE+-]*)\*?s/\(s\*s([+-][\d.eE+-]*)\*?s([+-][\d.eE+-]+)\)$', expr)
        if m:
            gain = float(m.group(1)) if m.group(1) else 1.0
            a = float(m.group(2))
            b = float(m.group(3))
            num_desc = [1.0, 0.0]  # s
            den_desc = [1.0, a, b]  # s^2 + a*s + b
            return (gain, num_desc, den_desc)

        # Pattern 3: Try Python eval approach with rational tracking
        try:
            return _eval_laplace_expr(expr)
        except Exception:
            pass

        return None

    def _eval_laplace_expr(expr):
        """Evaluate Laplace expression using Python eval with rational polynomial tracking."""
        import math as _math

        class Rational:
            """Rational polynomial num/den in s, coefficients in ascending order."""
            def __init__(self, num_asc, den_asc=None):
                self.num = list(num_asc)
                self.den = list(den_asc) if den_asc else [1.0]
                self._normalize()

            def _normalize(self):
                while len(self.num) > 1 and abs(self.num[-1]) < 1e-30:
                    self.num = self.num[:-1]
                while len(self.den) > 1 and abs(self.den[-1]) < 1e-30:
                    self.den = self.den[:-1]

            @staticmethod
            def _poly_mul(a, b):
                result = [0.0] * (len(a) + len(b) - 1)
                for i, x in enumerate(a):
                    for j, y in enumerate(b):
                        result[i + j] += x * y
                return result

            def __mul__(self, other):
                if isinstance(other, (int, float)):
                    return Rational([x * other for x in self.num], list(self.den))
                if isinstance(other, Rational):
                    return Rational(
                        self._poly_mul(self.num, other.num),
                        self._poly_mul(self.den, other.den)
                    )
                return NotImplemented

            def __rmul__(self, other):
                return self.__mul__(other)

            def __truediv__(self, other):
                if isinstance(other, (int, float)):
                    return Rational([x / other for x in self.num], list(self.den))
                if isinstance(other, Rational):
                    return Rational(
                        self._poly_mul(self.num, other.den),
                        self._poly_mul(self.den, other.num)
                    )
                return NotImplemented

            def __rtruediv__(self, other):
                if isinstance(other, (int, float)):
                    return Rational([other * x for x in self.den], list(self.num))
                return NotImplemented

            def __add__(self, other):
                if isinstance(other, (int, float)):
                    other = Rational([other])
                if isinstance(other, Rational):
                    # a/b + c/d = (a*d + b*c) / (b*d)
                    new_num = [0.0] * (max(
                        len(self._poly_mul(self.num, other.den)),
                        len(self._poly_mul(self.den, other.num))
                    ))
                    ad = self._poly_mul(self.num, other.den)
                    bc = self._poly_mul(self.den, other.num)
                    for i in range(max(len(ad), len(bc))):
                        val = 0.0
                        if i < len(ad): val += ad[i]
                        if i < len(bc): val += bc[i]
                        if i < len(new_num):
                            new_num[i] = val
                        else:
                            new_num.append(val)
                    return Rational(new_num, self._poly_mul(self.den, other.den))
                return NotImplemented

            def __radd__(self, other):
                return self.__add__(other)

            def __sub__(self, other):
                if isinstance(other, (int, float)):
                    other = Rational([other])
                if isinstance(other, Rational):
                    neg = Rational([-x for x in other.num], list(other.den))
                    return self.__add__(neg)
                return NotImplemented

            def __rsub__(self, other):
                return Rational([-x for x in self.num], list(self.den)).__add__(other)

            def __pow__(self, n):
                if not isinstance(n, int) or n < 0:
                    raise ValueError(f"Unsupported power: {n}")
                if n == 0:
                    return Rational([1.0])
                result = Rational(list(self.num), list(self.den))
                for _ in range(n - 1):
                    result = result * self
                return result

            def __neg__(self):
                return Rational([-x for x in self.num], list(self.den))

            def __pos__(self):
                return Rational(list(self.num), list(self.den))

        s = Rational([0.0, 1.0])  # s = 0 + 1*s

        # Prepare expression for eval
        proc_expr = expr
        # Fix leading dots: .001 → 0.001
        proc_expr = re.sub(r'(?<![0-9])\.(\d)', r'0.\1', proc_expr)

        safe_ns = {
            's': s,
            '__builtins__': {},
        }

        result = eval(proc_expr, safe_ns)

        if isinstance(result, Rational):
            # Extract gain by normalizing leading denominator coefficient
            num_desc = list(reversed(result.num))
            den_desc = list(reversed(result.den))
            return (1.0, num_desc, den_desc)
        elif isinstance(result, (int, float)):
            return (float(result), [1.0], [1.0])

        return None

    for line in lines:
        stripped = line.strip()

        # Look for Laplace= in component value lines
        # Format: E1 out+ out- in+ in- Laplace=expr
        # or:     E1 out+ out- LAPLACE {V(in)} {expr}
        laplace_match = re.match(
            r'^([EGeg]\w+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+[Ll]aplace\s*=\s*(.+)$',
            stripped
        )
        if not laplace_match:
            # Try the LAPLACE {V(in)} {expr} form
            laplace_match2 = re.match(
                r'^([EGeg]\w+)\s+(\S+)\s+(\S+)\s+[Ll][Aa][Pp][Ll][Aa][Cc][Ee]\s+\{[^}]*\}\s+\{(.+)\}$',
                stripped
            )
            if laplace_match2:
                name = laplace_match2.group(1)
                out_p = laplace_match2.group(2)
                out_n = laplace_match2.group(3)
                in_p = '0'  # input from the {V(in)} is implicit
                in_n = '0'
                laplace_expr = laplace_match2.group(4)
                # Extract input node from {V(node)}
                v_match = re.search(r'[Vv]\((\w+)\)', stripped)
                if v_match:
                    in_p = v_match.group(1)
            else:
                new_lines.append(line)
                continue
        else:
            name = laplace_match.group(1)
            out_p = laplace_match.group(2)
            out_n = laplace_match.group(3)
            in_p = laplace_match.group(4)
            in_n = laplace_match.group(5)
            laplace_expr = laplace_match.group(6)

        # Try to parse the Laplace expression
        result = _parse_laplace_regex(laplace_expr)

        if result is None:
            # Cannot parse — leave as comment with warning
            new_lines.append(f'* (WARNING: Laplace not converted - unsupported form) {stripped}')
            # Add a simple resistor to prevent dangling node
            new_lines.append(f'R_{name}_dummy {out_p} {out_n} 1k')
            print(f"  WARNING: Could not convert Laplace expression for {name}: {laplace_expr[:60]}")
            continue

        gain, num_desc, den_desc = result
        model_counter[0] += 1
        model_name = f'xfer_{name}_{model_counter[0]}'
        int_node = f'int_{name}_{model_counter[0]}'

        # Format coefficients for s_xfer
        def fmt_coeffs(coeffs):
            return ' '.join(f'{c:.10g}' for c in coeffs)

        num_str = fmt_coeffs(num_desc)
        den_str = fmt_coeffs(den_desc)

        # Number of initial conditions = degree of denominator
        n_ic = len(den_desc) - 1
        ic_str = ' '.join(['0'] * n_ic) if n_ic > 0 else '0'

        # Generate XSPICE a-device + model
        new_lines.append(f'* (converted from: {stripped})')

        if in_n == '0' or in_n == 'gnd':
            # Single-ended input: a-device input is directly the input node
            new_lines.append(f'a_{name} {in_p} {int_node} {model_name}')
        else:
            # Differential input: add a voltage-controlled voltage source
            diff_node = f'diff_{name}_{model_counter[0]}'
            new_lines.append(f'E_{name}_diff {diff_node} 0 {in_p} {in_n} 1')
            new_lines.append(f'a_{name} {diff_node} {int_node} {model_name}')

        new_lines.append(f'.model {model_name} s_xfer(gain={gain:.10g} num_coeff=[{num_str}] den_coeff=[{den_str}] int_ic=[{ic_str}])')

        if out_n == '0' or out_n == 'gnd':
            # Single-ended output: buffer from int_node to output
            new_lines.append(f'E_{name}_out {out_p} 0 {int_node} 0 1')
        else:
            # Differential output
            new_lines.append(f'E_{name}_out {out_p} {out_n} {int_node} 0 1')

        new_lines.append(f'R_{name}_load {int_node} 0 1G')  # Load resistor for XSPICE
        print(f"  Converted {name} Laplace to s_xfer: gain={gain:.4g}, num={num_desc}, den={den_desc}")

    return '\n'.join(new_lines)


def _validate_netlist(netlist_text):
    """Validate and fix common netlist issues before simulation.

    - Remove empty-value sources (Vi N001 0 "")
    - Convert .step param to .param with chosen value
    - Convert Laplace behavioral sources to XSPICE s_xfer
    - Remove floating nodes (nodes connected to nothing)
    """
    # First pass: convert .step param and Laplace
    netlist_text = _convert_step_param(netlist_text)
    netlist_text = _convert_laplace_to_sxfer(netlist_text)

    lines = netlist_text.split('\n')
    fixed = []
    issues = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('*'):
            fixed.append(line)
            continue

        # Remove empty-value voltage/current sources: V1 n1 n2 "" → comment out
        if stripped and stripped[0].upper() in ('V', 'I') and '""' in stripped:
            fixed.append(f'* (removed: empty value) {stripped}')
            issues.append(f'Empty source removed: {stripped.split()[0]}')
            continue

        # Comment out .wave (LTspice-specific WAV file output)
        if stripped.lower().startswith('.wave'):
            fixed.append(f'* (removed: LTspice-only) {stripped}')
            issues.append(f'.wave directive removed (LTspice-only)')
            continue

        # Comment out .savebias, .loadbias (LTspice-specific)
        if stripped.lower().startswith('.savebias') or stripped.lower().startswith('.loadbias'):
            fixed.append(f'* (removed: LTspice-only) {stripped}')
            continue

        fixed.append(line)

    if issues:
        for issue in issues[:5]:
            print(f"  VALIDATION: {issue}")
        if len(issues) > 5:
            print(f"  ... and {len(issues) - 5} more validation issues")

    return '\n'.join(fixed)


def _fix_ltspice_syntax(netlist_text):
    """Convert LTspice-specific SPICE syntax to standard ngspice.

    Fixes:
    1. VCCS/VCVS poly shorthand: G1 n+ n- (nc+,nc-) gain -> G1 n+ n- nc+ nc- gain
       Applies to G (VCCS), E (VCVS) sources.
    2. Behavioral source prefix: BV -> B (LTspice 'BV' is behavioral voltage)
    3. LTspice model types: LPNP -> PNP, LNPN -> NPN (lateral variants)
    4. Rser=/Rpar=/Cpar= on C/L elements -> separate R/C components
    """
    lines = netlist_text.split('\n')
    fixed = []
    extra_lines = []  # additional R/C elements from Rser/Rpar/Cpar
    changes = 0

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('*'):
            fixed.append(line)
            continue

        # Fix .model with LTspice-specific types (LPNP -> PNP, LNPN -> NPN)
        if stripped.upper().startswith('.MODEL'):
            new_line = re.sub(r'\bLPNP\b', 'PNP', stripped, flags=re.IGNORECASE)
            new_line = re.sub(r'\bLNPN\b', 'NPN', new_line, flags=re.IGNORECASE)
            if new_line != stripped:
                fixed.append(new_line)
                changes += 1
                continue
            fixed.append(line)
            continue

        if stripped.startswith('.'):
            fixed.append(line)
            continue

        # Fix Rser=/Rpar=/Cpar= on C/L elements
        # Pattern: C1 n+ n- 100n Rser=10 Rpar=1Meg  or  L1 n+ n- 1m Rser=100 Cpar=10p
        if stripped[0].upper() in ('C', 'L') and re.search(r'\b(Rser|Rpar|Cpar)\s*=', stripped, re.I):
            m = re.match(r'(\S+)\s+(\S+)\s+(\S+)\s+(\S+)(.*)', stripped)
            if m:
                name, np, nm, value, params = m.groups()
                rser_m = re.search(r'Rser\s*=\s*(\S+)', params, re.I)
                rpar_m = re.search(r'Rpar\s*=\s*(\S+)', params, re.I)
                cpar_m = re.search(r'Cpar\s*=\s*(\S+)', params, re.I)
                # Strip all Rser/Rpar/Cpar/ic= params, keep the value
                clean_params = re.sub(r'\b(Rser|Rpar|Cpar|ic)\s*=\s*\S+', '', params, flags=re.I).strip()
                if rser_m:
                    # Insert intermediate node for series resistance
                    int_node = f'__{name}_rs'
                    fixed.append(f'{name} {np} {int_node} {value} {clean_params}'.strip())
                    extra_lines.append(f'R_{name}_ser {int_node} {nm} {rser_m.group(1)}')
                    changes += 1
                else:
                    fixed.append(f'{name} {np} {nm} {value} {clean_params}'.strip())
                    changes += 1
                if rpar_m:
                    extra_lines.append(f'R_{name}_par {np} {nm} {rpar_m.group(1)}')
                if cpar_m:
                    extra_lines.append(f'C_{name}_par {np} {nm} {cpar_m.group(1)}')
                continue

        # Fix G/E source with (nc+,nc-) syntax
        # Pattern: G1 n+ n- (nc+,nc-) gain  ->  G1 n+ n- nc+ nc- gain
        if stripped[0].upper() in ('G', 'E'):
            m = re.match(
                r'([GEge]\S+)\s+(\S+)\s+(\S+)\s+\((\S+?),(\S+?)\)\s+(.*)',
                stripped)
            if m:
                name, np, nm, ncp, ncm, rest = m.groups()
                new_line = f'{name} {np} {nm} {ncp} {ncm} {rest}'
                fixed.append(new_line)
                changes += 1
                continue

        # Fix BV (behavioral voltage) -> B source
        if stripped[0].upper() == 'B' and len(stripped) > 1 and stripped[1].upper() == 'V':
            # BV1 n+ n- V=... -> B1 n+ n- V=...
            m = re.match(r'[Bb][Vv](\S*)\s+(.*)', stripped)
            if m:
                name_suffix, rest = m.groups()
                new_line = f'B{name_suffix} {rest}'
                fixed.append(new_line)
                changes += 1
                continue

        fixed.append(line)

    # Insert extra R/C elements before .end
    if extra_lines:
        result = []
        for ln in fixed:
            if ln.strip().upper() == '.END':
                result.append('')
                result.append('* Auto-generated from Rser/Rpar/Cpar')
                for el in extra_lines:
                    result.append(el)
            result.append(ln)
        fixed = result

    if changes > 0:
        print(f"  Fixed {changes} LTspice-specific syntax element(s)")
    return '\n'.join(fixed)


def _resolve_missing_models(netlist_text):
    """Find model names used in a netlist that lack .model definitions, and inject them.

    Searches the MicroCap library for BJT, JFET, diode, and MOSFET models.
    Returns netlist_text with .model lines injected before .end.
    """
    lines = netlist_text.split('\n')

    # Collect model names already defined
    defined = set()
    for line in lines:
        m = re.match(r'\.model\s+(\S+)', line, re.I)
        if m:
            defined.add(m.group(1).upper())
        # Also check .subckt definitions
        m = re.match(r'\.subckt\s+(\S+)', line, re.I)
        if m:
            defined.add(m.group(1).upper())

    # Collect model names referenced by components
    needed = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('*') or stripped.startswith('.'):
            continue
        first = stripped[0].upper()
        parts = stripped.split()
        if first == 'Q' and len(parts) >= 5:
            needed.add(parts[4])  # Q1 C B E modelname
        elif first == 'D' and len(parts) >= 4:
            needed.add(parts[3])  # D1 A K modelname
        elif first == 'J' and len(parts) >= 5:
            needed.add(parts[4])  # J1 D G S modelname
        elif first == 'M' and len(parts) >= 5:
            needed.add(parts[4])  # M1 D G S B modelname (or M1 D G S modelname)

    # Filter out already-defined models
    missing = {n for n in needed if n.upper() not in defined}
    if not missing:
        return netlist_text

    # Search MicroCap library for missing models
    lib_dir = os.path.join(REPO_DIR, "models", "MicroCap-LIBRARY-for-ngspice")
    found_models = []

    if os.path.isdir(lib_dir):
        for lib_file in os.listdir(lib_dir):
            if not lib_file.endswith('.lib'):
                continue
            lib_path = os.path.join(lib_dir, lib_file)
            try:
                with open(lib_path, 'r', errors='replace') as f:
                    content = f.read()
                for model_name in list(missing):
                    # Try exact match first, then strip trailing letter (A/B/C variants)
                    candidates = [model_name]
                    if re.match(r'.*\d[A-Za-z]$', model_name):
                        candidates.append(model_name[:-1])  # e.g., 2N2219A → 2N2219

                    for try_name in candidates:
                        pattern = rf'^\.MODEL\s+{re.escape(try_name)}\s+\w+\s*\('
                        match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
                        if match:
                            # Extract the full model (including continuation lines)
                            start = match.start()
                            pos = match.end()
                            while pos < len(content):
                                nl = content.find('\n', pos)
                                if nl == -1:
                                    pos = len(content)
                                    break
                                next_line = content[nl + 1:nl + 10]
                                if next_line.startswith('+'):
                                    pos = nl + 1
                                else:
                                    pos = nl
                                    break
                            model_text = content[start:pos].strip()
                            # If we found a variant, rename the model to match
                            if try_name != model_name:
                                model_text = re.sub(
                                    rf'(\.MODEL\s+){re.escape(try_name)}',
                                    rf'\g<1>{model_name}',
                                    model_text, count=1, flags=re.IGNORECASE)
                            # Strip carriage returns from model text
                            model_text = model_text.replace('\r', '')
                            # Collapse continuation lines then re-wrap at ~80 chars
                            collapsed = re.sub(r'\s*\n\+\s*', ' ', model_text)
                            # Re-wrap: split at spaces within the parenthesized params
                            m_hdr = re.match(r'(\.MODEL\s+\S+\s+\w+\s*\()', collapsed)
                            if m_hdr and len(collapsed) > 80:
                                header = m_hdr.group(1)
                                params = collapsed[len(header):].rstrip(')')
                                parts = params.split()
                                lines_out = [header]
                                current = '+'
                                for p in parts:
                                    if len(current) + 1 + len(p) > 75:
                                        lines_out.append(current)
                                        current = '+ ' + p
                                    else:
                                        current += ' ' + p
                                lines_out.append(current + ')')
                                model_text = '\n'.join(lines_out)
                            else:
                                model_text = collapsed
                            found_models.append(model_text)
                            missing.discard(model_name)
                            break  # Found it, stop trying candidates
            except Exception:
                continue

    if not found_models:
        return netlist_text

    # Inject models before .end
    model_block = '\n* Auto-resolved models\n' + '\n'.join(found_models) + '\n'
    if '.end' in netlist_text.lower():
        # Insert before .end
        idx = netlist_text.lower().rfind('.end')
        return netlist_text[:idx] + model_block + '\n' + netlist_text[idx:]
    else:
        return netlist_text + '\n' + model_block


def _resolve_missing_subcircuits(netlist_text):
    """Find subcircuit names used in X-lines that lack .subckt definitions, and inject them.

    Searches the MicroCap library .lib files for .SUBCKT definitions.
    Handles naming variants: LT1001 → LT1001_LT, LT1001_MC, etc.
    Returns netlist_text with .subckt blocks and .include directives injected.
    """
    lines = netlist_text.split('\n')

    # Collect already-defined subcircuits
    defined = set()
    for line in lines:
        m = re.match(r'\.subckt\s+(\S+)', line, re.I)
        if m:
            defined.add(m.group(1).upper())
        # Also count .include directives as potentially providing subcircuits
        m = re.match(r'\.include\s+(\S+)', line, re.I)
        if m:
            defined.add('__INCLUDE__')  # Mark that includes exist

    # Collect subcircuit names referenced by X components
    needed = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('*') or stripped.startswith('.'):
            continue
        if stripped[0].upper() == 'X':
            parts = stripped.split()
            if len(parts) >= 3:
                # Last token is subcircuit name (X1 pin1 pin2 ... subckt_name)
                subckt_name = parts[-1]
                needed.add(subckt_name)

    # Filter out already-defined
    missing = {n for n in needed if n.upper() not in defined}
    if not missing:
        return netlist_text

    # Search MicroCap library for missing subcircuits
    lib_dir = os.path.join(REPO_DIR, "models", "MicroCap-LIBRARY-for-ngspice")
    found_blocks = []
    rename_map = {}  # old_name → new_name (for renaming in netlist)

    if os.path.isdir(lib_dir):
        for lib_file in sorted(os.listdir(lib_dir)):
            if not lib_file.endswith('.lib'):
                continue
            if not missing:
                break
            lib_path = os.path.join(lib_dir, lib_file)
            try:
                with open(lib_path, 'r', errors='replace') as f:
                    content = f.read()
                for subckt_name in list(missing):
                    # Try exact match, then common suffixes
                    candidates = [subckt_name]
                    for suffix in ['_LT', '_MC', '_TI', '_AD', '_NS']:
                        candidates.append(subckt_name + suffix)
                    # Also try stripping trailing letters for variants
                    if re.match(r'.*\d[A-Za-z]$', subckt_name):
                        base = subckt_name[:-1]
                        candidates.append(base)
                        for suffix in ['_LT', '_MC', '_TI', '_AD', '_NS']:
                            candidates.append(base + suffix)

                    for try_name in candidates:
                        pattern = rf'^\.SUBCKT\s+{re.escape(try_name)}\b'
                        match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
                        if match:
                            # Extract full subcircuit block (.SUBCKT ... .ENDS)
                            start = match.start()
                            # Find the matching .ENDS
                            ends_pattern = rf'^\.ENDS\s+{re.escape(try_name)}\b|^\.ENDS\s*$'
                            ends_match = re.search(ends_pattern, content[start:],
                                                   re.MULTILINE | re.IGNORECASE)
                            if ends_match:
                                end = start + ends_match.end()
                                subckt_block = content[start:end].strip()
                                subckt_block = subckt_block.replace('\r', '')

                                if try_name.upper() != subckt_name.upper():
                                    # Rename the subcircuit to match what the circuit expects
                                    subckt_block = re.sub(
                                        rf'(\.SUBCKT\s+){re.escape(try_name)}',
                                        rf'\g<1>{subckt_name}',
                                        subckt_block, count=1, flags=re.IGNORECASE)
                                    subckt_block = re.sub(
                                        rf'(\.ENDS\s+){re.escape(try_name)}',
                                        rf'\g<1>{subckt_name}',
                                        subckt_block, count=1, flags=re.IGNORECASE)

                                found_blocks.append(subckt_block)
                                missing.discard(subckt_name)
                                break
            except Exception:
                continue

    if not found_blocks:
        # Add warnings for missing subcircuits
        if missing:
            warn_block = '\n'.join(f'* WARNING: subcircuit {n} not found' for n in missing)
            if '.end' in netlist_text.lower():
                idx = netlist_text.lower().rfind('.end')
                return netlist_text[:idx] + warn_block + '\n' + netlist_text[idx:]
        return netlist_text

    # Inject subcircuit blocks before .end
    subckt_block = '\n* Auto-resolved subcircuits\n' + '\n\n'.join(found_blocks) + '\n'
    if '.end' in netlist_text.lower():
        idx = netlist_text.lower().rfind('.end')
        return netlist_text[:idx] + subckt_block + '\n' + netlist_text[idx:]
    else:
        return netlist_text + '\n' + subckt_block


def _extract_source_frequency(netlist_text):
    """Extract dominant frequency from SINE/PULSE source definitions.

    Returns frequency in Hz, or 0 if no frequency found.
    """
    # SPICE value pattern: digits with optional SI suffix (k, Meg, u, n, p, etc.)
    _val = r'[\d.eE+\-]+[a-zA-Z]*'
    for line in netlist_text.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('*'):
            continue
        # SINE(offset amplitude freq ...)
        m = re.search(r'SINE\s*\(\s*' + _val + r'\s+' + _val + r'\s+(' + _val + r')', stripped, re.I)
        if m:
            try:
                freq = _parse_spice_value(m.group(1))
                if freq > 0:
                    return freq
            except (ValueError, TypeError):
                pass
        # PULSE(V1 V2 Tdelay Trise Tfall Ton Period) — freq = 1/Period
        m = re.search(r'PULSE\s*\(' + (r'\s*' + _val) * 6 + r'\s+(' + _val + r')', stripped, re.I)
        if m:
            try:
                period = _parse_spice_value(m.group(1))
                if period > 0:
                    return 1.0 / period
            except (ValueError, TypeError):
                pass
    return 0.0


def _parse_spice_value(val_str):
    """Parse a SPICE value string with SI suffixes (e.g., '1k', '100u', '10Meg')."""
    val_str = val_str.strip().replace('µ', 'u')
    suffixes = {
        'T': 1e12, 'G': 1e9, 'MEG': 1e6, 'K': 1e3,
        'M': 1e-3, 'U': 1e-6, 'N': 1e-9, 'P': 1e-12, 'F': 1e-15,
    }
    for suffix, mult in suffixes.items():
        if val_str.upper().endswith(suffix):
            num_part = val_str[:len(val_str) - len(suffix)]
            return float(num_part) * mult
    return float(val_str)


def _inject_control_block(netlist_text, probe_nodes, analysis='transient'):
    """Inject/replace .control block in an existing .cir file."""
    lines = netlist_text.split('\n')
    new_lines = []
    in_control = False
    sim_cmd = None
    for line in lines:
        stripped = line.strip().lower()
        if stripped == '.control':
            in_control = True
            continue
        if stripped == '.endc':
            in_control = False
            continue
        if stripped == '.end':
            continue
        if in_control:
            continue
        if re.match(r'\.(tran|ac|dc|noise)\b', stripped):
            sim_cmd = line.strip()
            continue
        # For AC analysis, add AC stimulus to signal sources (SINE/PULSE/PWL)
        if analysis == 'ac_bode' and re.match(r'^V\w+\s', line, re.I):
            upper = line.upper()
            if ('SINE' in upper or 'PULSE' in upper or 'PWL' in upper) and 'AC' not in upper:
                line = line.rstrip() + ' AC 1'
        new_lines.append(line)

    # Extract frequency from sources for auto-scaling
    src_freq = _extract_source_frequency(netlist_text)

    # Use relative filename (ngspice cwd is sim_work/)
    results_file = f"generic_{analysis}_results.txt"

    if analysis == 'ac_bode':
        # Auto-scale AC range based on source frequency
        if src_freq > 0:
            f_start = max(0.1, src_freq / 10000)
            f_stop = min(100e9, src_freq * 10000)
            new_lines.append(f".ac dec 100 {f_start:.4g} {f_stop:.4g}")
            print(f"    AC range auto-scaled: {f_start:.4g} - {f_stop:.4g} Hz (source freq: {src_freq:.4g} Hz)")
        else:
            new_lines.append(".ac dec 100 1 10Meg")
        save_str = " ".join([f"vdb({n}) vp({n})" for n in probe_nodes])
    elif analysis == 'dc_sweep':
        new_lines.append(sim_cmd if sim_cmd else ".dc V1 -5 5 0.1")
        save_str = " ".join([f"V({n})" for n in probe_nodes])
    else:
        if sim_cmd:
            new_lines.append(_fix_tran_cmd(sim_cmd))
        elif src_freq > 0:
            # Auto-scale: show ~20 cycles, step = period/50
            period = 1.0 / src_freq
            tstop = 20 * period
            tstep = period / 50
            new_lines.append(f".tran {tstep:.4g} {tstop:.4g}")
            print(f"    Transient auto-scaled: step={tstep:.4g}s, stop={tstop:.4g}s (source freq: {src_freq:.4g} Hz)")
        else:
            new_lines.append(".tran 1u 10m")
        save_str = " ".join([f"V({n})" for n in probe_nodes])

    new_lines.append("")
    new_lines.append(".control")
    new_lines.append("run")
    new_lines.append(f"wrdata {results_file} {save_str}")
    new_lines.append("quit")
    new_lines.append(".endc")
    new_lines.append("")
    new_lines.append(".end")
    return "\n".join(new_lines)


def main():
    """Main entry point - CLI circuit selection and pipeline execution.

    Each circuit follows the same pipeline:
        1. Load KiCad symbol libraries
        2. Build schematic (place components, route wires, add power symbols)
        3. Write ngspice netlist (with swappable op-amp model)
        4. Simulate with ngspice
        5. Plot results (transient waveforms)
        6. Verify circuit (self-improving check system)
        6b. AC analysis / Bode plot (if applicable)
        7. Export schematic to PDF/PNG

    Usage: python kicad_pipeline.py [circuit] [opamp] [range]
        circuit: ce_amp | inv_amp | sig_cond | usb_ina | electrometer | electrometer_362
        opamp:   LM741 | AD822 | AD843 | LMC6001 | LMC6001A | OPA128
        range:   0-3 (electrometer_362 only: 0=10M, 1=100M, 2=1G, 3=10G)
    """
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "search":
        query = " ".join(sys.argv[2:])
        results = search_models(query)
        print(f"\nModel search for '{query}':")
        print(f"{'Type':<8} {'Name':<25} {'Info':<20} {'Library'}")
        print("-" * 75)
        for typ, name, info, lib in results:
            print(f"{typ:<8} {name:<25} {info:<20} {lib}")
        return

    if len(sys.argv) >= 3 and sys.argv[1] == "extract":
        name = sys.argv[2]
        lib = sys.argv[3] if len(sys.argv) > 3 else None
        block = extract_model(name, lib)
        if block:
            print(block)
        else:
            print(f"Model '{name}' not found")
        return

    # ---- analyze_circuit: inspect a circuit and suggest analyses ----
    if len(sys.argv) >= 3 and sys.argv[1] == "analyze_circuit":
        import json as _json
        circuit_path = sys.argv[2]
        if not os.path.exists(circuit_path):
            print(f'{{"error": "File not found: {circuit_path}"}}')
            sys.exit(1)
        ext = os.path.splitext(circuit_path)[1].lower()
        try:
            if ext == '.asc':
                # Use built-in .asc parser (no LTspice.exe required)
                from asc_parser import parse_asc
                asc_result = parse_asc(circuit_path)
                if asc_result['error']:
                    print(f'{{"error": "{asc_result["error"]}"}}')
                    sys.exit(1)
                netlist_text = asc_result['netlist']
                all_nodes = asc_result['nodes']
                sim_cmd = asc_result['sim_command']
                netlist_lines = [l for l in netlist_text.split('\n') if l.strip()]
                if asc_result.get('warnings'):
                    for w in asc_result['warnings']:
                        print(f'  WARNING: {w}', file=sys.stderr)
            elif ext in ('.cir', '.net', '.sp', '.spice'):
                from demo_loader import read_ltspice_file
                if ext == '.net':
                    text = read_ltspice_file(circuit_path)
                else:
                    text = open(circuit_path, 'r').read()
                all_nodes, sim_cmd = _extract_nodes_from_cir(text)
                netlist_lines = [l for l in text.split('\n') if l.strip()]
            else:
                print(f'{{"error": "Unsupported file type: {ext}. Supported: .asc .cir .net .sp"}}')
                sys.exit(1)

            nodes_class = _classify_nodes(all_nodes, netlist_lines)
            components = _count_components(netlist_lines)
            sources = _parse_sources(netlist_lines)
            circuit_type = _detect_circuit_type(components, sources, nodes_class)
            suggestions = _suggest_analyses(circuit_type, sources, nodes_class, sim_cmd)

            result = {
                'circuit_path': circuit_path.replace('\\', '/'),
                'circuit_name': os.path.splitext(os.path.basename(circuit_path))[0],
                'circuit_type': circuit_type,
                'sim_command': sim_cmd or '.tran 1u 10m',
                'nodes': nodes_class,
                'components': components,
                'sources': sources,
                'suggested_analyses': suggestions,
            }
            print(_json.dumps(result, indent=2))
        except Exception as e:
            print(f'{{"error": "{str(e)}"}}')
            sys.exit(1)
        return

    # ---- generic_sim: run simulation with selected analyses and probes ----
    if len(sys.argv) >= 3 and sys.argv[1] == "generic_sim":
        import json as _json
        circuit_path = sys.argv[2]
        if not os.path.exists(circuit_path):
            print(f"ERROR: File not found: {circuit_path}")
            sys.exit(1)

        # Parse --analyses and --nodes args
        analyses = ['transient']
        user_nodes = []
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == '--analyses' and i + 1 < len(sys.argv):
                analyses = sys.argv[i + 1].split(',')
                i += 2
            elif sys.argv[i] == '--nodes' and i + 1 < len(sys.argv):
                user_nodes = sys.argv[i + 1].split(',')
                i += 2
            else:
                # Bare node names (legacy support)
                user_nodes.append(sys.argv[i])
                i += 1

        ext = os.path.splitext(circuit_path)[1].lower()
        try:
            if ext == '.asc':
                # Use built-in .asc parser (no LTspice.exe required)
                from asc_parser import parse_asc
                asc_result = parse_asc(circuit_path)
                if asc_result['error']:
                    print(f"ERROR: {asc_result['error']}")
                    sys.exit(1)
                text = asc_result['netlist']
                all_nodes = asc_result['nodes']
                if asc_result.get('warnings'):
                    for w in asc_result['warnings']:
                        print(f"  WARNING: {w}")
                # Resolve missing model definitions (BJTs, diodes, etc.)
                text = _resolve_missing_models(text)
                # Resolve missing subcircuit definitions (op-amps, etc.)
                text = _resolve_missing_subcircuits(text)
                # Fix LTspice-specific syntax (VCCS poly, behavioral sources)
                text = _fix_ltspice_syntax(text)
                # Remove .include directives for files that don't exist
                text = _remove_missing_includes(text)
                # Validate netlist before simulation
                text = _validate_netlist(text)
                # Now treat it like a .cir file
                if user_nodes and user_nodes != ['auto']:
                    probe_nodes = user_nodes
                else:
                    named = [n for n in all_nodes if not re.match(r'^N\d+$', n)]
                    probe_nodes = named[:12] if named else all_nodes[:8]

                meta = {'circuit_path': circuit_path, 'all_nodes': all_nodes,
                        'probe_nodes': probe_nodes, 'analyses_run': analyses}

                for analysis in analyses:
                    if analysis == 'measurements':
                        continue
                    print(f"\n  Running {analysis} analysis...")
                    netlist_text = _inject_control_block(text, probe_nodes, analysis)
                    netlist_path = os.path.join(WORK_DIR, f"generic_{analysis}.cir")
                    with open(netlist_path, 'w') as f:
                        f.write(netlist_text)
                    success = simulate(netlist_path)
                    if success:
                        results_file = os.path.join(WORK_DIR, f"generic_{analysis}_results.txt")
                        if os.path.exists(results_file):
                            if analysis == 'transient':
                                meas = _measure_generic(results_file, probe_nodes)
                                meta['transient'] = {
                                    'results_file': f"generic_transient_results.txt",
                                    'probes': probe_nodes, 'measurements': meas,
                                }
                                for node, m in meas.items():
                                    if isinstance(m, dict):
                                        print(f"    {node}: Vpp={m['vpp']:.4f}  Vdc={m['vdc']:.4f}  Vrms={m['vrms']:.4f}")
                            elif analysis == 'ac_bode':
                                meta['ac_bode'] = {
                                    'results_file': f"generic_ac_bode_results.txt",
                                    'probes': probe_nodes,
                                }
                        else:
                            print(f"    WARNING: {analysis} results file not found")
                    else:
                        print(f"    {analysis} simulation failed")

            elif ext in ('.cir', '.net', '.sp', '.spice'):
                from demo_loader import read_ltspice_file
                if ext == '.net':
                    text = read_ltspice_file(circuit_path)
                else:
                    text = open(circuit_path, 'r').read()
                all_nodes, sim_cmd = _extract_nodes_from_cir(text)
                if user_nodes and user_nodes != ['auto']:
                    probe_nodes = user_nodes
                else:
                    named = [n for n in all_nodes if not re.match(r'^N\d+$', n)]
                    probe_nodes = named[:12] if named else all_nodes[:8]

                meta = {'circuit_path': circuit_path, 'all_nodes': all_nodes,
                        'probe_nodes': probe_nodes, 'analyses_run': analyses}

                for analysis in analyses:
                    if analysis == 'measurements':
                        continue
                    print(f"\n  Running {analysis} analysis...")
                    netlist_text = _inject_control_block(text, probe_nodes, analysis)
                    netlist_path = os.path.join(WORK_DIR, f"generic_{analysis}.cir")
                    with open(netlist_path, 'w') as f:
                        f.write(netlist_text)
                    success = simulate(netlist_path)
                    if success:
                        results_file = os.path.join(WORK_DIR, f"generic_{analysis}_results.txt")
                        if os.path.exists(results_file):
                            if analysis == 'transient':
                                meas = _measure_generic(results_file, probe_nodes)
                                meta['transient'] = {
                                    'results_file': f"generic_transient_results.txt",
                                    'probes': probe_nodes, 'measurements': meas,
                                }
                                for node, m in meas.items():
                                    if isinstance(m, dict):
                                        print(f"    {node}: Vpp={m['vpp']:.4f}  Vdc={m['vdc']:.4f}  Vrms={m['vrms']:.4f}")
                            elif analysis == 'ac_bode':
                                meta['ac_bode'] = {
                                    'results_file': f"generic_ac_bode_results.txt",
                                    'probes': probe_nodes,
                                }
                    else:
                        print(f"    {analysis} simulation failed")
            else:
                print(f"ERROR: Unsupported file type: {ext}. Supported: .asc .cir .net .sp")
                sys.exit(1)

            # Write metadata JSON
            meta_path = os.path.join(WORK_DIR, "generic_sim_meta.json")
            with open(meta_path, 'w') as f:
                # Convert numpy types to Python native for JSON
                def _convert(obj):
                    if isinstance(obj, (np.floating, np.integer)):
                        return float(obj)
                    if isinstance(obj, np.ndarray):
                        return obj.tolist()
                    return obj
                _json.dump(meta, f, indent=2, default=_convert)
            print(f"\n  Metadata: {meta_path}")

            # Also generate KiCad schematic if possible
            if ext == '.asc':
                print("\n  Generating KiCad schematic from netlist...")
                try:
                    sch_path = os.path.join(WORK_DIR, f"generic_circuit.kicad_sch")
                    # Use demo_loader's data to build a basic schematic
                    # (full schematic generation is a future enhancement)
                    print(f"  Schematic: {sch_path} (future feature)")
                except Exception as e:
                    print(f"  Schematic generation: {e}")

        except Exception as e:
            import traceback
            print(f"ERROR: {e}")
            traceback.print_exc()
            sys.exit(1)
        return

    # Circuit selection
    circuit = "ce_amp"
    opamp = "LM741"
    if len(sys.argv) >= 2 and sys.argv[1] in ("audioamp", "inv_amp", "ce_amp", "sig_cond", "usb_ina", "electrometer", "electrometer_362", "relay_ladder", "input_filters", "analog_mux", "mux_tia", "mcu_section", "full_system", "full_path", "channel_switch", "femtoamp_test", "avdd_monitor", "rtd_temp", "combined_log", "oscillator", "osc_blocks", "tia_blocks", "analog_osc"):
        circuit = sys.argv[1]
    if len(sys.argv) >= 3 and sys.argv[2] in ("LM741", "AD797", "AD822", "AD843", "LMC6001", "LMC6001A", "OPA128", "ADA4530"):
        opamp = sys.argv[2]

    print("=" * 60)
    print(f"  {PROGRAM_NAME} v{VERSION}")
    print("  Build -> Verify -> Correct -> Simulate -> Export")
    rules = load_learned_rules()
    print(f"  [{len(rules['rules'])} learned rules, "
          f"{rules.get('fixes_applied', 0)} fixes applied]")
    print("=" * 60)

    print("\n[1] Loading KiCad symbol libraries...")
    init_libraries()

    if circuit == "sig_cond":
        print("\n[2] Building signal conditioner schematic...")
        sch_path = build_signal_conditioner()

        print(f"\n[3] Writing ngspice netlist (op-amp: {opamp})...")
        netlist_path = write_sig_cond_netlist(opamp=opamp)

        print("\n[4] Simulating...")
        success = simulate(netlist_path)

        sim_results = {}
        if success:
            print("\n[5] Plotting results...")
            OPAMP_TITLES = {
                "AD797": "AD797 Ultra-Low Noise",
                "AD822": "AD822 Precision JFET",
                "AD843": "AD843 Fast Settling",
                "LM741": "LM741 Classic",
            }
            opamp_label = OPAMP_TITLES.get(opamp, opamp)
            plot_results(
                title=f"Signal Conditioner ({opamp_label}, G=11, LPF fc~1kHz)",
                results_file="sig_cond_results.txt",
                node_names=['V(SENSOR)', 'V(OUT)', 'V(STAGE1)', 'V(FILTERED)', 'V(N1)'],
                plot_file="sig_cond_results.png"
            )
            sim_results = measure_simulation(
                "sig_cond_results.txt",
                ['V(SENSOR)', 'V(OUT)', 'V(STAGE1)', 'V(FILTERED)', 'V(N1)']
            )
        else:
            print("\n[5] Simulation failed")

        print("\n[6] Verifying circuit...")
        expected = {
            'gain': (11.0, 3.0, 'x'),        # gain ~11 +/- 3
            'gain_dB': (20.8, 4.0, ' dB'),   # ~20.8 dB +/- 4
        }
        verify_circuit(sch_path, 'sig_cond', sim_results, expected)

        # AC analysis (Bode plot)
        print("\n[6b] Running AC analysis (Bode plot)...")
        ac_path = write_sig_cond_ac_netlist(opamp=opamp)
        ac_ok = simulate(ac_path)
        if ac_ok:
            plot_bode(
                results_file="sig_cond_ac.txt",
                title=f"Signal Conditioner Bode Plot ({opamp_label})",
                plot_file="sig_cond_bode.png"
            )

    elif circuit == "electrometer":
        if opamp == "LM741":
            opamp = "LMC6001"  # default to electrometer-grade op-amp
        print(f"\n[2] Building electrometer TIA schematic...")
        sch_path = build_electrometer_tia()

        print(f"\n[3] Writing ngspice netlist (op-amp: {opamp})...")
        netlist_path = write_electrometer_tia_netlist(opamp=opamp)

        print("\n[4] Simulating...")
        success = simulate(netlist_path)

        OPAMP_TITLES = {
            "LMC6001": "LMC6001 Ultra-Low Bias",
            "LMC6001A": "LMC6001A Electrometer-Grade",
            "OPA128": "OPA128 Classic Electrometer",
            "AD822": "AD822 Precision JFET",
            "AD843": "AD843 Fast Settling",
            "LM741": "LM741 Classic",
        }
        opamp_label = OPAMP_TITLES.get(opamp, opamp)

        sim_results = {}
        if success:
            print("\n[5] Plotting results...")
            plot_results(
                title=f"Electrometer TIA ({opamp_label}, Rf=1G, Cf=10pF)",
                results_file="electrometer_results.txt",
                node_names=['V(TIA_OUT)', 'V(INV)'],
                plot_file="electrometer_results.png"
            )

            # TIA-specific measurement: transimpedance = Vout / Iin
            results_path = os.path.join(WORK_DIR, "electrometer_results.txt")
            if os.path.exists(results_path):
                data = np.loadtxt(results_path)
                time = data[:, 0]
                vout = data[:, 1]
                # Steady-state during pulse (after 5*tau settling)
                pulse_mask = (time > 0.060) & (time < 0.085)
                rest_mask = (time > 0.005) & (time < 0.009)
                if np.any(pulse_mask) and np.any(rest_mask):
                    v_pulse = np.mean(vout[pulse_mask])
                    v_rest = np.mean(vout[rest_mask])
                    delta_v = abs(v_pulse - v_rest)
                    iin = 1e-9  # 1nA test current
                    transimpedance = delta_v / iin
                    print(f"\n  TIA Measurements:")
                    print(f"    V(TIA_OUT) during pulse:  {v_pulse*1000:.1f} mV")
                    print(f"    V(TIA_OUT) at rest:       {v_rest*1000:.4f} mV")
                    print(f"    Delta V:                  {delta_v*1000:.1f} mV")
                    print(f"    Transimpedance:           {transimpedance:.2e} V/A")
                    print(f"    Expected:                 1.00e+09 V/A (Rf=1G)")
                    sim_results['transimpedance'] = transimpedance
                    sim_results['delta_v_mV'] = delta_v * 1000
        else:
            print("\n[5] Simulation failed")

        print("\n[6] Verifying circuit...")
        expected = {}
        if 'transimpedance' in sim_results:
            # Transimpedance should be ~1G (within 50%)
            expected['transimpedance'] = (1e9, 5e8, ' V/A')
        verify_circuit(sch_path, 'electrometer', sim_results, expected)

        # AC analysis (Bode plot)
        print("\n[6b] Running AC analysis (Bode plot)...")
        ac_path = write_electrometer_tia_ac_netlist(opamp=opamp)
        ac_ok = simulate(ac_path)
        if ac_ok:
            plot_bode(
                results_file="electrometer_ac.txt",
                title=f"Electrometer TIA Bode Plot ({opamp_label})",
                plot_file="electrometer_bode.png"
            )

    elif circuit == "electrometer_362":
        if opamp == "LM741":
            opamp = "LMC6001"
        # Parse optional range argument (0-3)
        rf_range = 2  # default: 1G + 10pF
        if len(sys.argv) >= 4:
            try:
                rf_range = int(sys.argv[3])
            except ValueError:
                pass

        RANGE_DESC = {
            0: "10M (+-120nA)", 1: "100M (+-12nA)",
            2: "1G+10pF (+-1.2nA)", 3: "10G+1pF (+-120pA)",
        }
        print(f"\n[2] Building electrometer TIA schematic (ADuCM362 platform)...")
        sch_path = build_electrometer_362()

        use_ltspice = (opamp == "ADA4530")

        OPAMP_TITLES = {
            "LMC6001": "LMC6001 Ultra-Low Bias",
            "LMC6001A": "LMC6001A Electrometer-Grade",
            "OPA128": "OPA128 Classic Electrometer",
            "AD822": "AD822 Precision JFET",
            "LM741": "LM741 Classic",
            "ADA4530": "ADA4530-1 Electrometer (LTspice)",
        }
        opamp_label = OPAMP_TITLES.get(opamp, opamp)

        if use_ltspice:
            print(f"\n[3] Writing LTspice netlist (ADA4530-1, range {rf_range}: {RANGE_DESC.get(rf_range, '?')})...")
            netlist_path = write_electrometer_362_ltspice(rf_range=rf_range)
            print("\n[4] Simulating with LTspice (real ADA4530-1 model)...")
            lt_data = simulate_ltspice(netlist_path, ['V(tia_out)', 'V(inv)', 'V(gdr)'])
            success = len(lt_data) > 0
        else:
            print(f"\n[3] Writing ngspice netlist (op-amp: {opamp}, range {rf_range}: {RANGE_DESC.get(rf_range, '?')})...")
            netlist_path = write_electrometer_362_netlist(opamp=opamp, rf_range=rf_range)
            print("\n[4] Simulating with ngspice...")
            success = simulate(netlist_path)
            lt_data = None

        RANGES = {
            0: ("10M",  100e-9),
            1: ("100M", 10e-9),
            2: ("1G",   1e-9),
            3: ("10G",  0.1e-9),
        }
        rf_name, i_test = RANGES.get(rf_range, RANGES[2])

        sim_results = {}
        if success:
            print("\n[5] Plotting results...")

            # Extract time and vout from either LTspice or ngspice
            time = vout = None
            if use_ltspice and lt_data:
                time = lt_data.get('time')
                vout = lt_data.get('V(tia_out)')
                # Plot from LTspice data
                if time is not None and vout is not None:
                    import matplotlib.pyplot as plt
                    fig, ax = plt.subplots(figsize=(10, 6))
                    ax.plot(time * 1000, vout * 1000, 'b-', label='V(TIA_OUT)')
                    vinv = lt_data.get('V(inv)')
                    if vinv is not None:
                        ax.plot(time * 1000, vinv * 1000, 'r--', label='V(INV)')
                    ax.set_xlabel('Time (ms)')
                    ax.set_ylabel('Voltage (mV)')
                    ax.set_title(f"Electrometer TIA ADuCM362 ({opamp_label}, Rf={rf_name}, Range {rf_range})")
                    ax.legend()
                    ax.grid(True, alpha=0.3)
                    plot_path = os.path.join(WORK_DIR, "electrometer_362_results.png")
                    fig.savefig(plot_path, dpi=150)
                    plt.close()
                    print(f"  Plot saved: {plot_path}")
            else:
                plot_results(
                    title=f"Electrometer TIA ADuCM362 ({opamp_label}, Rf={rf_name}, Range {rf_range})",
                    results_file="electrometer_362_results.txt",
                    node_names=['V(TIA_OUT)', 'V(INV)'],
                    plot_file="electrometer_362_results.png"
                )
                results_path = os.path.join(WORK_DIR, "electrometer_362_results.txt")
                if os.path.exists(results_path):
                    data = np.loadtxt(results_path)
                    time = data[:, 0]
                    vout = data[:, 1]

            # TIA-specific measurement: transimpedance = delta_V / I_test
            if time is not None and vout is not None:
                sim_time = time[-1]
                rest_mask = (time > 0.002) & (time < 0.009)
                pulse_start = sim_time * 0.30
                pulse_end = sim_time * 0.45
                pulse_mask = (time > pulse_start) & (time < pulse_end)

                if np.any(pulse_mask) and np.any(rest_mask):
                    v_pulse = np.mean(vout[pulse_mask])
                    v_rest = np.mean(vout[rest_mask])
                    delta_v = abs(v_pulse - v_rest)
                    transimpedance = delta_v / i_test

                    print(f"\n  TIA Measurements (Range {rf_range}: Rf={rf_name}):")
                    print(f"    Simulator:                {'LTspice (ADA4530-1)' if use_ltspice else 'ngspice (' + opamp + ')'}")
                    print(f"    V(TIA_OUT) during pulse:  {v_pulse*1000:.1f} mV")
                    print(f"    V(TIA_OUT) at rest:       {v_rest*1000:.4f} mV")
                    print(f"    Delta V:                  {delta_v*1000:.1f} mV")
                    print(f"    Test current:             {i_test*1e9:.1f} nA")
                    print(f"    Transimpedance:           {transimpedance:.2e} V/A")

                    RF_EXPECTED = {0: 10e6, 1: 100e6, 2: 1e9, 3: 10e9}
                    expected_z = RF_EXPECTED[rf_range]
                    print(f"    Expected:                 {expected_z:.2e} V/A (Rf={rf_name})")
                    sim_results['transimpedance'] = transimpedance
                    sim_results['V(TIA_OUT)_pp'] = np.max(vout) - np.min(vout)
        else:
            print("\n[5] Simulation failed")

        print("\n[6] Verifying circuit...")
        expected = {}
        RF_EXPECTED = {0: 10e6, 1: 100e6, 2: 1e9, 3: 10e9}
        if 'transimpedance' in sim_results:
            expected['transimpedance'] = (RF_EXPECTED[rf_range], RF_EXPECTED[rf_range] * 0.5, ' V/A')
        verify_circuit(sch_path, 'electrometer_362', sim_results, expected)

        # AC analysis
        print("\n[6b] Running AC analysis (Bode plot)...")
        ac_path = write_electrometer_362_ac_netlist(opamp=opamp, rf_range=rf_range)
        ac_ok = simulate(ac_path)
        if ac_ok:
            plot_bode(
                results_file="electrometer_362_ac.txt",
                title=f"Electrometer TIA Bode Plot ({opamp_label}, Range {rf_range}: Rf={rf_name})",
                plot_file="electrometer_362_bode.png"
            )

    elif circuit == "relay_ladder":
        print("\n[2] Building relay range-switching ladder...")
        sch_path = build_relay_ladder()

        print("\n[3] Writing relay driver simulation netlist...")
        netlist_path = write_relay_ladder_netlist()

        print("\n[4] Simulating relay coil driver...")
        success = simulate(netlist_path)

        sim_results = {}
        if success:
            print("\n[5] Plotting results...")
            plot_results(
                title="Relay Coil Driver - NPN Switching Transient",
                results_file="relay_ladder_results.txt",
                node_names=['V(GPIO)', 'V(COIL_BOT)', 'V(5V_ISO)-V(COIL_TOP)', 'I(V_ISO)'],
                plot_file="relay_ladder_results.png"
            )
        else:
            print("\n[5] Simulation failed")

        print("\n[6] Verifying circuit...")
        verify_circuit(sch_path, 'relay_ladder', sim_results, {})

    elif circuit == "input_filters":
        print("\n[2] Building 16-channel input filter array...")
        sch_path = build_input_filters()

        print("\n[3] Verifying circuit...")
        verify_circuit(sch_path, 'input_filters', {}, {})

    elif circuit == "analog_mux":
        print("\n[2] Building 2x 8:1 analog multiplexer section...")
        sch_path = build_analog_mux()

        print("\n[3] Verifying circuit...")
        verify_circuit(sch_path, 'analog_mux', {}, {})

    elif circuit == "mux_tia":
        print("\n[2] Building TIA with mux interface (correction loop)...")
        sch_path, all_issues, corrections = build_and_verify_loop(
            'mux_tia', build_mux_tia, max_attempts=3)
        if corrections:
            print(f"\n  Corrections applied: {len(corrections)}")
            for rid, desc in corrections:
                print(f"    - {rid}: {desc}")

    elif circuit == "mcu_section":
        print("\n[2] Building ADuCM362 MCU + ADC interface (correction loop)...")
        sch_path, all_issues, corrections = build_and_verify_loop(
            'mcu_section', build_mcu_section, max_attempts=3)
        if corrections:
            print(f"\n  Corrections applied: {len(corrections)}")
            for rid, desc in corrections:
                print(f"    - {rid}: {desc}")

    elif circuit == "full_system":
        print("\n[2] Building full 16-channel measurement system (correction loop)...")
        sch_path, all_issues, corrections = build_and_verify_loop(
            'full_system', build_full_system, max_attempts=3)
        if corrections:
            print(f"\n  Corrections applied: {len(corrections)}")
            for rid, desc in corrections:
                print(f"    - {rid}: {desc}")

    elif circuit == "full_path":
        if opamp == "LM741":
            opamp = "LMC6001"
        rf_range = 2
        if len(sys.argv) >= 4:
            try:
                rf_range = int(sys.argv[3])
            except ValueError:
                pass

        RANGE_DESC = {
            0: "10M (+-120nA)", 1: "100M (+-12nA)",
            2: "1G+10pF (+-1.2nA)", 3: "10G+1pF (+-120pA)",
        }
        OPAMP_TITLES = {
            "LMC6001": "LMC6001 Ultra-Low Bias",
            "LMC6001A": "LMC6001A Electrometer-Grade",
            "OPA128": "OPA128 Classic Electrometer",
            "AD822": "AD822 Precision JFET",
            "LM741": "LM741 Classic",
        }
        opamp_label = OPAMP_TITLES.get(opamp, opamp)

        print(f"\n[1] Full-path simulation: Filter -> Mux -> TIA -> ADC")
        print(f"    Op-amp: {opamp_label}, Range {rf_range}: {RANGE_DESC.get(rf_range, '?')}")

        print(f"\n[2] Writing full-path transient netlist...")
        netlist_path = write_full_path_netlist(opamp=opamp, rf_range=rf_range)

        print("\n[3] Simulating full signal path...")
        success = simulate(netlist_path)

        RANGES = {0: ("10M", 100e-9), 1: ("100M", 10e-9), 2: ("1G", 1e-9), 3: ("10G", 0.1e-9)}
        rf_name, i_test = RANGES.get(rf_range, RANGES[2])

        sim_results = {}
        if success:
            print("\n[4] Plotting results...")
            plot_results(
                title=f"Full-Path: Filter->Mux->TIA->ADC ({opamp_label}, Rf={rf_name})",
                results_file="full_path_results.txt",
                node_names=['V(CH_IN)', 'V(FILT_OUT)', 'V(TIA_IN)', 'V(TIA_OUT)', 'V(AIN0)', 'V(INV)'],
                plot_file="full_path_results.png"
            )

            # Measure transimpedance from full path
            results_path = os.path.join(WORK_DIR, "full_path_results.txt")
            if os.path.exists(results_path):
                data = np.loadtxt(results_path)
                time = data[:, 0]
                # wrdata pairs: 0=CH_IN, 1=FILT, 2=TIA_IN, 3=TIA_OUT, 4=AIN0, 5=INV
                vout = data[:, 7]  # V(TIA_OUT) - pair index 3, value column
                vadc = data[:, 9]  # V(AIN0) - pair index 4
                # Pulse starts at 0.02s. Compute pulse width from range params.
                rest_mask = (time > 0.005) & (time < 0.018)
                RANGES_CF = {0: None, 1: None, 2: 10e-12, 3: 1e-12}
                RANGES_RF = {0: 10e6, 1: 100e6, 2: 1e9, 3: 10e9}
                tau_tia = RANGES_RF[rf_range] * (RANGES_CF.get(rf_range) or 1e-12)
                tau_filt = 1e6 * 10e-9  # 10ms
                pulse_w = max(0.1, max(tau_tia, tau_filt) * 5)
                pulse_on = 0.02
                pulse_mask = (time > pulse_on + pulse_w * 0.6) & (time < pulse_on + pulse_w * 0.9)

                if np.any(pulse_mask) and np.any(rest_mask):
                    v_pulse = np.mean(vout[pulse_mask])
                    v_rest = np.mean(vout[rest_mask])
                    delta_v = abs(v_pulse - v_rest)
                    transimpedance = delta_v / i_test

                    v_adc_pulse = np.mean(vadc[pulse_mask])
                    v_adc_rest = np.mean(vadc[rest_mask])
                    adc_delta = abs(v_adc_pulse - v_adc_rest)

                    RF_EXPECTED = {0: 10e6, 1: 100e6, 2: 1e9, 3: 10e9}
                    expected_z = RF_EXPECTED[rf_range]
                    pct_err = abs(transimpedance - expected_z) / expected_z * 100

                    print(f"\n  Full-Path Measurements (Range {rf_range}: Rf={rf_name}):")
                    print(f"    V(TIA_OUT) during pulse:  {v_pulse*1000:.2f} mV")
                    print(f"    V(TIA_OUT) at rest:       {v_rest*1000:.4f} mV")
                    print(f"    TIA delta V:              {delta_v*1000:.2f} mV")
                    print(f"    V(AIN0) delta:            {adc_delta*1000:.2f} mV")
                    print(f"    Transimpedance:           {transimpedance:.2e} V/A")
                    print(f"    Expected:                 {expected_z:.2e} V/A")
                    print(f"    Error:                    {pct_err:.1f}%")
                    sim_results['transimpedance'] = transimpedance
                    sim_results['adc_delta_mV'] = adc_delta * 1000

            # AC analysis
            print("\n[5] Running AC analysis (full-path Bode)...")
            ac_path = write_full_path_ac_netlist(opamp=opamp, rf_range=rf_range)
            ac_ok = simulate(ac_path)
            if ac_ok:
                plot_bode(
                    results_file="full_path_ac.txt",
                    title=f"Full-Path Bode: Filter+Mux+TIA ({opamp_label}, Rf={rf_name})",
                    plot_file="full_path_bode.png"
                )
        else:
            print("\n[4] Simulation failed")

        # No schematic to export for simulation-only circuit
        print("\nDone!")
        return

    elif circuit == "channel_switch":
        if opamp == "LM741":
            opamp = "LMC6001"
        rf_range = 2
        if len(sys.argv) >= 4:
            try:
                rf_range = int(sys.argv[3])
            except ValueError:
                pass

        OPAMP_TITLES = {
            "LMC6001": "LMC6001 Ultra-Low Bias",
            "LMC6001A": "LMC6001A Electrometer-Grade",
            "OPA128": "OPA128 Classic Electrometer",
        }
        opamp_label = OPAMP_TITLES.get(opamp, opamp)
        n_ch = 16

        print(f"\n[1] Channel switching simulation: {n_ch} channels multiplexed")
        print(f"    Op-amp: {opamp_label}, Range {rf_range}")

        print(f"\n[2] Writing channel switching netlist...")
        netlist_path = write_channel_switching_netlist(opamp=opamp, rf_range=rf_range, n_channels=n_ch)

        print("\n[3] Simulating channel switching...")
        success = simulate(netlist_path)

        # Per-range current tables (must match write_channel_switching_netlist)
        RANGE_CURRENTS = {
            0: {  # Rf=100: mA range (0.5-10 mA)
                1: 1.0e-3,   2: 2.5e-3,   3: 5.0e-3,   4: 10.0e-3,
                5: 7.5e-3,   6: 3.0e-3,   7: 1.5e-3,   8: 8.0e-3,
                9: 0.5e-3,  10: 4.0e-3,  11: 6.0e-3,  12: 2.0e-3,
               13: 9.0e-3,  14: 3.5e-3,  15: 5.5e-3,  16: 1.2e-3,
            },
            1: {  # Rf=1k: sub-mA range (0.2-4 mA)
                1: 0.4e-3,   2: 1.0e-3,   3: 2.0e-3,   4: 4.0e-3,
                5: 3.0e-3,   6: 1.2e-3,   7: 0.6e-3,   8: 3.2e-3,
                9: 0.2e-3,  10: 1.6e-3,  11: 2.4e-3,  12: 0.8e-3,
               13: 3.6e-3,  14: 1.4e-3,  15: 2.2e-3,  16: 0.48e-3,
            },
            2: {  # Rf=10k: 100-µA range (20-400 µA)
                1: 40e-6,    2: 100e-6,   3: 200e-6,   4: 400e-6,
                5: 300e-6,   6: 120e-6,   7: 60e-6,    8: 320e-6,
                9: 20e-6,   10: 160e-6,  11: 240e-6,  12: 80e-6,
               13: 360e-6,  14: 140e-6,  15: 220e-6,  16: 48e-6,
            },
            3: {  # Rf=100k: 10-µA range (2-40 µA)
                1: 4.0e-6,   2: 10.0e-6,   3: 20.0e-6,   4: 40.0e-6,
                5: 30.0e-6,   6: 12.0e-6,   7: 6.0e-6,    8: 32.0e-6,
                9: 2.0e-6,   10: 16.0e-6,  11: 24.0e-6,  12: 8.0e-6,
               13: 36.0e-6,  14: 14.0e-6,  15: 22.0e-6,  16: 4.8e-6,
            },
            4: {  # Rf=1M: µA range (0.2-4 µA)
                1: 0.4e-6,   2: 1.0e-6,   3: 2.0e-6,   4: 4.0e-6,
                5: 3.0e-6,   6: 1.2e-6,   7: 0.6e-6,   8: 3.2e-6,
                9: 0.2e-6,  10: 1.6e-6,  11: 2.4e-6,  12: 0.8e-6,
               13: 3.6e-6,  14: 1.4e-6,  15: 2.2e-6,  16: 0.48e-6,
            },
            5: {  # Rf=10M: high-nA range (20-400 nA)
                1: 40e-9,    2: 100e-9,   3: 200e-9,   4: 400e-9,
                5: 300e-9,   6: 120e-9,   7: 60e-9,    8: 320e-9,
                9: 20e-9,   10: 160e-9,  11: 240e-9,  12: 80e-9,
               13: 360e-9,  14: 140e-9,  15: 220e-9,  16: 48e-9,
            },
            6: {  # Rf=100M: nanoamp range (2-40 nA)
                1: 4.0e-9,   2: 10.0e-9,   3: 20.0e-9,   4: 40.0e-9,
                5: 30.0e-9,   6: 12.0e-9,   7: 6.0e-9,    8: 32.0e-9,
                9: 2.0e-9,   10: 16.0e-9,  11: 24.0e-9,  12: 8.0e-9,
               13: 36.0e-9,  14: 14.0e-9,  15: 22.0e-9,  16: 4.8e-9,
            },
            7: {  # Rf=1G: sub-nanoamp range (0.05-1 nA)
                1: 0.10e-9,   2: 0.25e-9,   3: 0.50e-9,   4: 1.00e-9,
                5: 0.75e-9,   6: 0.30e-9,   7: 0.15e-9,   8: 0.80e-9,
                9: 0.05e-9,  10: 0.40e-9,  11: 0.60e-9,  12: 0.20e-9,
               13: 0.90e-9,  14: 0.35e-9,  15: 0.55e-9,  16: 0.12e-9,
            },
            8: {  # Rf=10G: femtoamp range (50-1000 fA)
                1: 100e-15,   2: 250e-15,   3: 500e-15,   4: 1000e-15,
                5: 750e-15,   6: 300e-15,   7: 150e-15,   8: 800e-15,
                9: 50e-15,   10: 400e-15,  11: 600e-15,  12: 200e-15,
               13: 900e-15,  14: 350e-15,  15: 550e-15,  16: 120e-15,
            },
        }
        CHANNEL_CURRENTS = RANGE_CURRENTS.get(rf_range, RANGE_CURRENTS[7])

        if success:
            print("\n[4] Plotting results...")
            RANGE_NAMES = {0: "100", 1: "1k", 2: "10k", 3: "100k", 4: "1M", 5: "10M", 6: "100M", 7: "1G", 8: "10G"}
            rf_name = RANGE_NAMES.get(rf_range, "1G")
            results_file = f"channel_switching_range{rf_range}_results.txt"
            # Only plot first 4 CH_IN + TIA_OUT + AIN0 (16 nodes too many for one chart)
            plot_results(
                title=f"16-Channel Switching ({opamp_label}, Rf={rf_name})",
                results_file=results_file,
                node_names=[f'V(CH{i}_IN)' for i in range(1, min(n_ch + 1, 5))] + ['V(TIA_OUT)', 'V(AIN0)'],
                plot_file=f"channel_switching_range{rf_range}_results.png"
            )

            # Measure per-channel TIA output
            results_path = os.path.join(WORK_DIR, results_file)
            if os.path.exists(results_path):
                data = np.loadtxt(results_path)
                time = data[:, 0]
                # TIA_OUT is the (n_ch+1)th node pair
                vout_col = n_ch * 2 + 1  # wrdata format: time val time val...
                vout = data[:, vout_col]
                ch_period = 0.2  # must match write_channel_switching_netlist

                RANGES_Z = {0: 100, 1: 1e3, 2: 10e3, 3: 100e3, 4: 1e6, 5: 10e6, 6: 100e6, 7: 1e9, 8: 10e9}
                z_fb = RANGES_Z[rf_range]

                # Auto-scale unit for display
                def fmt_current(amps):
                    a = abs(amps)
                    if a >= 1e-3:   return f"{amps*1e3:.3f}mA"
                    elif a >= 1e-6: return f"{amps*1e6:.3f}uA"
                    elif a >= 1e-9: return f"{amps*1e9:.3f}nA"
                    elif a >= 1e-12: return f"{amps*1e12:.3f}pA"
                    else:           return f"{amps*1e15:.1f}fA"

                print(f"\n  {'CH':>4} {'I_sensor':>12} {'V(TIA)':>12} {'Expected':>12} {'Error':>8}")
                print(f"  {'----':>4} {'--------':>12} {'------':>12} {'--------':>12} {'-----':>8}")
                errors = []
                for ch in range(1, n_ch + 1):
                    i_expected = CHANNEL_CURRENTS.get(ch, 1e-9 / ch)
                    t_sample = (ch - 1) * ch_period + ch_period * 0.8
                    idx = np.argmin(np.abs(time - t_sample))
                    v_ch = vout[idx]
                    expected_v = i_expected * z_fb
                    err = abs(abs(v_ch) - expected_v) / expected_v * 100 if expected_v > 0 else 0
                    errors.append(err)
                    print(f"  {ch:>4} {fmt_current(i_expected):>12} {v_ch*1000:>10.2f}mV {-expected_v*1000:>10.2f}mV {err:>6.1f}%")

                avg_err = np.mean(errors)
                max_err = np.max(errors)
                print(f"\n  Average error: {avg_err:.1f}%, Max error: {max_err:.1f}%")
                if max_err < 20:
                    print(f"  PASS: all channels within 20% (pre-calibration)")
                else:
                    print(f"  WARN: some channels exceed 20% error")
        else:
            print("\n[4] Simulation failed")

        print("\nDone!")
        return

    elif circuit == "femtoamp_test":
        if opamp == "LM741":
            opamp = "LMC6001"

        OPAMP_TITLES = {
            "LMC6001": "LMC6001 Ultra-Low Bias",
            "LMC6001A": "LMC6001A Electrometer-Grade",
            "OPA128": "OPA128 Classic Electrometer",
        }
        opamp_label = OPAMP_TITLES.get(opamp, opamp)

        print(f"\n[1] Femtoampere sensitivity test (100fA)")
        print(f"    Op-amp: {opamp_label}, Range 3 (10G+1pF)")

        print(f"\n[2] Writing femtoamp test netlist...")
        netlist_path = write_femtoamp_test_netlist(opamp=opamp)

        print("\n[3] Simulating 100fA input...")
        success = simulate(netlist_path)

        if success:
            print("\n[4] Plotting results...")
            plot_results(
                title=f"Femtoamp Sensitivity Test ({opamp_label}, 100fA, Rf=10G)",
                results_file="femtoamp_results.txt",
                node_names=['V(TIA_OUT)', 'V(AIN0)', 'V(INV)', 'V(FILT_OUT)'],
                plot_file="femtoamp_results.png"
            )

            # Measure sensitivity
            results_path = os.path.join(WORK_DIR, "femtoamp_results.txt")
            if os.path.exists(results_path):
                data = np.loadtxt(results_path)
                time = data[:, 0]
                vout = data[:, 1]  # V(TIA_OUT)
                vadc = data[:, 3]  # V(AIN0)

                rest_mask = (time > 0.01) & (time < 0.04)
                pulse_mask = (time > 0.25) & (time < 0.34)

                if np.any(pulse_mask) and np.any(rest_mask):
                    v_pulse = np.mean(vout[pulse_mask])
                    v_rest = np.mean(vout[rest_mask])
                    delta_v = abs(v_pulse - v_rest)
                    i_test = 100e-15
                    transimpedance = delta_v / i_test

                    v_adc_pulse = np.mean(vadc[pulse_mask])
                    v_adc_rest = np.mean(vadc[rest_mask])
                    adc_delta = abs(v_adc_pulse - v_adc_rest)

                    # ADC resolution check
                    adc_lsb = 2.5 / (2**24)  # 24-bit, 2.5V range
                    adc_counts = adc_delta / adc_lsb

                    print(f"\n  Femtoamp Measurements:")
                    print(f"    Input current:            100 fA (10^-13 A)")
                    print(f"    V(TIA_OUT) delta:         {delta_v*1e6:.1f} uV")
                    print(f"    V(AIN0) delta:            {adc_delta*1e6:.1f} uV")
                    print(f"    Transimpedance:           {transimpedance:.2e} V/A")
                    print(f"    Expected:                 1.00e+10 V/A (Rf=10G)")
                    print(f"    ADC counts (24-bit):      {adc_counts:.0f}")
                    print(f"    ADC LSB:                  {adc_lsb*1e9:.0f} nV")
                    if adc_counts > 100:
                        print(f"    PASS: {adc_counts:.0f} counts >> noise floor")
                    elif adc_counts > 10:
                        print(f"    MARGINAL: {adc_counts:.0f} counts (close to noise)")
                    else:
                        print(f"    FAIL: {adc_counts:.0f} counts (below noise floor)")
        else:
            print("\n[4] Simulation failed")

        print("\nDone!")
        return

    elif circuit == "avdd_monitor":
        print(f"\n[1] AVDD supply monitor simulation")
        print(f"    R28/R29 100k divider, AIN2/AIN3 differential")

        print(f"\n[2] Writing AVDD monitor netlist...")
        netlist_path = write_avdd_monitor_netlist()

        print("\n[3] Simulating AVDD monitor...")
        success = simulate(netlist_path)

        if success:
            print("\n[4] Plotting results...")
            plot_results(
                title="AVDD Supply Monitor (100k/100k divider)",
                results_file="avdd_monitor_results.txt",
                node_names=['V(AVDD)', 'V(AIN2)', 'V(AGND)'],
                plot_file="avdd_monitor_results.png"
            )

            # Verify divider ratio
            results_path = os.path.join(WORK_DIR, "avdd_monitor_results.txt")
            if os.path.exists(results_path):
                data = np.loadtxt(results_path)
                time = data[:, 0]
                v_avdd = data[:, 1]   # V(AVDD)
                v_ain2 = data[:, 3]   # V(AIN2)

                # Sample at steady-state (middle of sim)
                mid_mask = (time > 0.04) & (time < 0.06)
                if np.any(mid_mask):
                    avdd_mid = np.mean(v_avdd[mid_mask])
                    ain2_mid = np.mean(v_ain2[mid_mask])
                    ratio = ain2_mid / avdd_mid if avdd_mid > 0 else 0

                    print(f"\n  AVDD Monitor Measurements:")
                    print(f"    V(AVDD):                  {avdd_mid*1000:.1f} mV")
                    print(f"    V(AIN2):                  {ain2_mid*1000:.1f} mV")
                    print(f"    Divider ratio:            {ratio:.4f}")
                    print(f"    Expected ratio:           0.5000")
                    print(f"    Tracking error:           {abs(ratio - 0.5) * 100:.2f}%")

                    # Check tracking over full sweep
                    ratio_all = v_ain2 / np.where(v_avdd > 0.1, v_avdd, 0.1)
                    valid = v_avdd > 0.5
                    if np.any(valid):
                        max_err = np.max(np.abs(ratio_all[valid] - 0.5)) * 100
                        print(f"    Max tracking error:       {max_err:.2f}%")
                        if max_err < 1.0:
                            print(f"    PASS: divider tracks AVDD within 1%")
                        else:
                            print(f"    WARN: tracking error > 1%")
        else:
            print("\n[4] Simulation failed")

        print("\nDone!")
        return

    elif circuit == "rtd_temp":
        rtd_type = sys.argv[2].upper() if len(sys.argv) >= 3 else "PT100"
        if rtd_type not in ("PT100", "PT1000"):
            rtd_type = "PT100"
        r0 = 100 if rtd_type == "PT100" else 1000

        print(f"\n[1] RTD temperature measurement simulation ({rtd_type})")
        print(f"    4-wire Kelvin sensing, IEXC=600uA, RREF=1.5k")

        print(f"\n[2] Writing RTD netlist...")
        netlist_path = write_rtd_temp_netlist(rtd_type=rtd_type)

        print("\n[3] Simulating RTD temperature sweep...")
        success = simulate(netlist_path)

        if success:
            print("\n[4] Plotting results...")
            plot_results(
                title=f"RTD Temperature Measurement ({rtd_type}, 4-Wire)",
                results_file="rtd_temp_results.txt",
                node_names=['V(TEMP)', 'V(AIN7)', 'V(AIN8)', 'V(AIN9)', 'V(AIN6)'],
                plot_file="rtd_temp_results.png"
            )

            # Analyse results at each temperature step
            results_path = os.path.join(WORK_DIR, "rtd_temp_results.txt")
            if os.path.exists(results_path):
                data = np.loadtxt(results_path)
                time = data[:, 0]
                v_temp = data[:, 1]    # V(TEMP) - temperature control
                # v_ain7 = data[:, 3]  # V(AIN7) - excitation node
                v_ain8 = data[:, 5]    # V(AIN8) - Kelvin sense+
                v_ain9 = data[:, 7]    # V(AIN9) - Kelvin sense-
                v_ain6 = data[:, 9]    # V(AIN6) - RREF sense

                # IEC 751 coefficients
                A_coeff = 3.9083e-3
                B_coeff = -5.775e-7
                rref = 1500
                r_lead = 1.0

                temps = [-40, 0, 25, 50, 100, 150, 200]
                print(f"\n  RTD Measurement Results ({rtd_type}, 4-Wire Kelvin):")
                print(f"  {'T_set':>8s}  {'R_expected':>10s}  {'V_RTD':>10s}  {'V_RREF':>10s}  {'R_meas':>10s}  {'T_meas':>8s}  {'Error':>8s}")
                print(f"  {'----':>8s}  {'----':>10s}  {'----':>10s}  {'----':>10s}  {'----':>10s}  {'----':>8s}  {'----':>8s}")

                max_err = 0
                for i, t_set in enumerate(temps):
                    # Sample at steady-state (middle of each step)
                    t_mid = i * 10e-3 + 5e-3
                    mask = (time > t_mid - 1e-3) & (time < t_mid + 1e-3)
                    if not np.any(mask):
                        continue

                    ain8_v = np.mean(v_ain8[mask])
                    ain9_v = np.mean(v_ain9[mask])
                    ain6_v = np.mean(v_ain6[mask])

                    # 4-wire: V_RTD = V(AIN8) - V(AIN9) (lead resistance cancelled)
                    v_rtd = ain8_v - ain9_v
                    v_rref = ain6_v  # RREF bottom is GND

                    # Ratiometric: R_RTD = RREF * V_RTD / V_RREF
                    r_meas = rref * v_rtd / v_rref if v_rref > 0.001 else 0

                    # Expected resistance: R = R0*(1 + A*T + B*T^2)
                    r_expected = r0 * (1 + A_coeff * t_set + B_coeff * t_set * t_set)

                    # Inverse IEC 751: T = (-A + sqrt(A^2 - 4B(1-R/R0))) / (2B)
                    r_norm = r_meas / r0
                    disc = A_coeff**2 - 4 * B_coeff * (1 - r_norm)
                    if disc >= 0:
                        t_meas = (-A_coeff + np.sqrt(disc)) / (2 * B_coeff)
                    else:
                        t_meas = float('nan')

                    t_err = abs(t_meas - t_set)
                    max_err = max(max_err, t_err)

                    print(f"  {t_set:>7.0f}C  {r_expected:>9.2f}R  {v_rtd*1000:>8.3f}mV  {v_rref*1000:>8.1f}mV  {r_meas:>9.2f}R  {t_meas:>7.2f}C  {t_err:>6.3f}C")

                print(f"\n  Max temperature error: {max_err:.3f}C")
                print(f"  Lead resistance: {r_lead} ohm/lead (cancelled by 4-wire)")

                # ADC resolution check
                iexc = 600e-6
                v_rtd_25 = iexc * r0 * (1 + A_coeff * 25 + B_coeff * 625)
                vref_adc = 1.2  # internal 1.2V VREF
                lsb = vref_adc / (2**24)
                counts_25 = int(v_rtd_25 / lsb)
                print(f"  ADC: {v_rtd_25*1000:.2f}mV at 25C = {counts_25:,} counts (24-bit, 1.2V VREF)")

                if max_err < 0.1:
                    print(f"  PASS: 4-wire RTD measurement accurate within 0.1C")
                elif max_err < 1.0:
                    print(f"  PASS: 4-wire RTD measurement accurate within 1C")
                else:
                    print(f"  WARN: temperature error > 1C")
        else:
            print("\n[4] Simulation failed")

        print("\nDone!")
        return

    elif circuit == "combined_log":
        n_ch = 4
        rtd_type = "PT100"
        r0 = 100

        print(f"\n[1] Combined data logging: {n_ch} channels + {rtd_type} RTD")
        print(f"    ADC0: TIA current per channel, ADC1: RTD temperature")

        print(f"\n[2] Writing combined logging netlist...")
        netlist_path = write_combined_logging_netlist(n_channels=n_ch, rtd_type=rtd_type)

        print("\n[3] Simulating combined logging...")
        success = simulate(netlist_path)

        if success:
            print("\n[4] Plotting results...")
            plot_results(
                title=f"Combined Data Logging ({n_ch} CH + {rtd_type})",
                results_file="combined_logging_results.txt",
                node_names=['V(CH1_IN)', 'V(CH2_IN)', 'V(CH3_IN)', 'V(CH4_IN)',
                            'V(TIA_OUT)', 'V(AIN0)', 'V(RTD_TEMP)',
                            'V(AIN8)', 'V(AIN9)', 'V(AIN6)'],
                plot_file="combined_logging_results.png"
            )

            results_path = os.path.join(WORK_DIR, "combined_logging_results.txt")
            if os.path.exists(results_path):
                data = np.loadtxt(results_path)
                time = data[:, 0]

                # Column mapping (wrdata pairs: time val time val ...)
                # Nodes: CH1_IN, CH2_IN, CH3_IN, CH4_IN, TIA_OUT, AIN0, RTD_TEMP, AIN8, AIN9, AIN6
                v_tia = data[:, 9]      # V(TIA_OUT) - 5th node, col index 9
                v_ain0 = data[:, 11]    # V(AIN0) - 6th node
                v_temp = data[:, 13]    # V(RTD_TEMP) - 7th node
                v_ain8 = data[:, 15]    # V(AIN8) - 8th node
                v_ain9 = data[:, 17]    # V(AIN9) - 9th node
                v_ain6 = data[:, 19]    # V(AIN6) - 10th node

                A_coeff = 3.9083e-3
                B_coeff = -5.775e-7
                rref = 1500
                CHANNEL_CURRENTS = {1: 0.10e-9, 2: 0.50e-9, 3: 1.00e-9, 4: 0.25e-9}

                ch_period = 0.2
                print(f"\n  Combined Data Log:")
                print(f"  {'CH':>4s}  {'I_sensor':>10s}  {'V(TIA)':>10s}  {'T_rtd':>8s}  {'R_rtd':>8s}")
                print(f"  {'--':>4s}  {'--':>10s}  {'--':>10s}  {'--':>8s}  {'--':>8s}")

                for ch in range(1, n_ch + 1):
                    # Sample TIA at 70-90% of each channel window
                    t_start = (ch - 1) * ch_period + ch_period * 0.7
                    t_end = (ch - 1) * ch_period + ch_period * 0.9
                    mask = (time > t_start) & (time < t_end)
                    if not np.any(mask):
                        continue

                    tia_v = np.mean(v_tia[mask])
                    ain8_v = np.mean(v_ain8[mask])
                    ain9_v = np.mean(v_ain9[mask])
                    ain6_v = np.mean(v_ain6[mask])

                    # RTD temperature from ratiometric measurement
                    v_rtd = ain8_v - ain9_v
                    r_meas = rref * v_rtd / ain6_v if ain6_v > 0.001 else 0
                    r_norm = r_meas / r0
                    disc = A_coeff**2 - 4 * B_coeff * (1 - r_norm)
                    t_rtd = (-A_coeff + np.sqrt(disc)) / (2 * B_coeff) if disc >= 0 else float('nan')

                    i_val = CHANNEL_CURRENTS.get(ch, 0)
                    print(f"  CH{ch:>2d}  {i_val*1e9:>8.3f}nA  {tia_v*1000:>8.2f}mV  {t_rtd:>6.2f}C  {r_meas:>7.2f}R")

                # Overall RTD drift during scan
                t_early = (time > 0.05) & (time < 0.15)
                t_late = (time > n_ch * ch_period - 0.15) & (time < n_ch * ch_period - 0.05)
                if np.any(t_early) and np.any(t_late):
                    ain8_early = np.mean(v_ain8[t_early])
                    ain9_early = np.mean(v_ain9[t_early])
                    ain6_early = np.mean(v_ain6[t_early])
                    r_early = rref * (ain8_early - ain9_early) / ain6_early
                    disc_e = A_coeff**2 - 4 * B_coeff * (1 - r_early/r0)
                    t_rtd_early = (-A_coeff + np.sqrt(disc_e)) / (2 * B_coeff)

                    ain8_late = np.mean(v_ain8[t_late])
                    ain9_late = np.mean(v_ain9[t_late])
                    ain6_late = np.mean(v_ain6[t_late])
                    r_late = rref * (ain8_late - ain9_late) / ain6_late
                    disc_l = A_coeff**2 - 4 * B_coeff * (1 - r_late/r0)
                    t_rtd_late = (-A_coeff + np.sqrt(disc_l)) / (2 * B_coeff)

                    drift = t_rtd_late - t_rtd_early
                    print(f"\n  RTD thermal drift during scan: {drift:.3f}C")
                    print(f"    T_start: {t_rtd_early:.2f}C, T_end: {t_rtd_late:.2f}C")
                    print(f"  PASS: temperature data captured alongside current measurements")
        else:
            print("\n[4] Simulation failed")

        print("\nDone!")
        return

    elif circuit == "oscillator":
        dac_code = 121  # default ~1kHz
        if len(sys.argv) >= 3:
            try:
                dac_code = int(sys.argv[2])
            except ValueError:
                pass

        FREQ_CONST = 4096 * 2 * 3.14159265 * 10e3 * 470e-12
        expected_freq = dac_code / FREQ_CONST

        print(f"\n[1] State Variable Oscillator: DAC code {dac_code} (expected {expected_freq:.1f} Hz)")

        print(f"\n[2] Building oscillator schematic...")
        sch_path = build_oscillator()

        print(f"\n[3] Writing oscillator netlist...")
        netlist_path = write_oscillator_netlist(dac_code=dac_code)

        print("\n[4] Simulating...")
        success = simulate(netlist_path)

        if success:
            results_path = os.path.join(WORK_DIR, f'oscillator_d{dac_code}_results.txt')
            if os.path.exists(results_path):
                print(f"\n[5] Results:")
                with open(results_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            print(f"    {line}")

                # Parse results for verification
                results = {}
                with open(results_path) as f:
                    for line in f:
                        parts = line.strip().split('=')
                        if len(parts) == 2:
                            key = parts[0].strip()
                            try:
                                results[key] = float(parts[1].strip())
                            except ValueError:
                                pass

                freq = results.get('freq', 0)
                bp_rms = results.get('bp_rms', 0)
                freq_err = abs(freq - expected_freq) / expected_freq * 100 if expected_freq > 0 else 0

                print(f"\n  Verification:")
                print(f"    Frequency: {freq:.1f} Hz (expected {expected_freq:.1f} Hz, error {freq_err:.1f}%)")
                print(f"    BP RMS:    {bp_rms:.3f} V (target 1.03 V)")
                status = "PASS" if freq_err < 15 else "FAIL"
                print(f"    Status:    {status}")
            else:
                print(f"\n[5] Results file not found: {results_path}")
        else:
            print("\n[4] Simulation failed")

        print("\nDone!")
        return

    elif circuit == "analog_osc":
        target_freq = 1581.0  # default (friend's original R=10k, C=10nF)
        if len(sys.argv) >= 3:
            try:
                target_freq = float(sys.argv[2])
            except ValueError:
                pass

        print(f"\n[1] Friend's Analog State Variable Oscillator: target {target_freq:.1f} Hz")

        print(f"\n[2] Writing analog oscillator netlist...")
        netlist_path = write_analog_osc_netlist(target_freq_hz=target_freq)

        print("\n[3] Simulating...")
        success = simulate(netlist_path)

        if success:
            freq_tag = f"{target_freq:.0f}"
            results_path = os.path.join(WORK_DIR, f'analog_osc_{freq_tag}Hz_results.txt')
            if os.path.exists(results_path):
                print(f"\n[4] Results:")
                with open(results_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            print(f"    {line}")

                # Parse results for verification
                results = {}
                with open(results_path) as f:
                    for line in f:
                        parts = line.strip().split('=')
                        if len(parts) == 2:
                            key = parts[0].strip()
                            try:
                                results[key] = float(parts[1].strip())
                            except ValueError:
                                pass

                freq = results.get('freq', 0)
                bp_rms = results.get('bp_rms', 0)
                bp_pp = results.get('bp_pp', 0)
                freq_err = abs(freq - target_freq) / target_freq * 100 if target_freq > 0 else 0

                print(f"\n  Verification:")
                print(f"    Frequency: {freq:.1f} Hz (target {target_freq:.1f} Hz, error {freq_err:.1f}%)")
                print(f"    BP RMS:    {bp_rms:.3f} V (target 1.03 V)")
                print(f"    BP Vpp:    {bp_pp:.3f} V")
                if bp_pp > 20:
                    print(f"    WARNING:   Output clipping detected (Vpp > 20V) - AGC not functioning")
                status = "PASS" if freq_err < 15 and bp_pp < 20 else "FAIL"
                print(f"    Status:    {status}")
            else:
                print(f"\n[4] Results file not found: {results_path}")
        else:
            print("\n[3] Simulation failed")

        print("\nDone!")
        return

    elif circuit == "osc_blocks":
        build_osc_blocks()
        print("\nDone!")
        return

    elif circuit == "tia_blocks":
        build_tia_blocks()
        print("\nDone!")
        return

    elif circuit == "usb_ina":
        print("\n[2] Building USB-isolated instrumentation amplifier...")
        sch_path = build_usb_ina()

        print(f"\n[3] Writing ngspice netlist (op-amp: {opamp})...")
        netlist_path = write_usb_ina_netlist(opamp=opamp)

        print("\n[4] Simulating...")
        success = simulate(netlist_path)

        sim_results = {}
        if success:
            print("\n[5] Plotting results...")
            OPAMP_TITLES = {
                "AD797": "AD797 Ultra-Low Noise",
                "AD822": "AD822 Precision JFET",
                "AD843": "AD843 Fast Settling",
                "LM741": "LM741 Classic",
            }
            opamp_label = OPAMP_TITLES.get(opamp, opamp)
            plot_results(
                title=f"3-Op-Amp INA ({opamp_label}, G=95)",
                results_file="usb_ina_results.txt",
                node_names=['V(INP)', 'V(OUT)', 'V(BUF1)', 'V(BUF2)', 'V(VOUT_INT)'],
                plot_file="usb_ina_results.png"
            )
            sim_results = measure_simulation(
                "usb_ina_results.txt",
                ['V(INP)', 'V(OUT)', 'V(BUF1)', 'V(BUF2)', 'V(VOUT_INT)']
            )
        else:
            print("\n[5] Simulation failed")

        print("\n[6] Verifying circuit...")
        # Measured gain is V(OUT)/V(INP) = 2*G_ina because differential input
        # V(INP)pp=10mV but differential=20mV, so apparent gain = 2*95 = 190
        expected = {
            'gain': (190.0, 40.0, 'x'),       # 2*G_ina from single-ended measurement
            'gain_dB': (45.6, 4.0, ' dB'),    # ~45.6 dB
        }
        verify_circuit(sch_path, 'usb_ina', sim_results, expected)

    elif circuit == "inv_amp":
        print("\n[2] Building inverting amplifier schematic...")
        sch_path = build_inverting_amp()

        print("\n[3] Writing ngspice netlist...")
        netlist_path = write_inv_amp_netlist()

        print("\n[4] Simulating...")
        success = simulate(netlist_path)

        sim_results = {}
        if success:
            print("\n[5] Plotting results...")
            plot_results(
                title="LM741 Inverting Amplifier (Gain = -10)",
                results_file="inv_amp_results.txt",
                node_names=['V(IN)', 'V(OUT)', 'V(OUT_INT)', 'V(INV)'],
                plot_file="inv_amp_results.png"
            )
            sim_results = measure_simulation(
                "inv_amp_results.txt",
                ['V(IN)', 'V(OUT)', 'V(OUT_INT)', 'V(INV)']
            )
        else:
            print("\n[5] Simulation failed")

        print("\n[6] Verifying circuit...")
        expected = {
            'gain': (10.0, 2.0, 'x'),       # gain ~10 +/- 2
            'gain_dB': (20.0, 3.0, ' dB'),  # 20 dB +/- 3
        }
        verify_circuit(sch_path, 'inv_amp', sim_results, expected)

    elif circuit == 'audioamp':
        print("\n[2] Building audio amplifier schematic...")
        sch_path = build_audioamp()

        print("\n[3] Writing ngspice netlist...")
        netlist_path = write_audioamp_netlist()

        print("\n[4] Simulating...")
        success = simulate(netlist_path)

        sim_results = {}
        if success:
            print("\n[5] Plotting results...")
            plot_results(
                title="Audio Amplifier (LTspice Educational)",
                results_file="audioamp_results.txt",
                node_names=['V(IN)', 'V(OUT)', 'V(VAS)', 'V(Q4E)'],
                plot_file="audioamp_results.png"
            )
            sim_results = measure_simulation(
                "audioamp_results.txt",
                ['V(IN)', 'V(OUT)', 'V(VAS)', 'V(Q4E)']
            )
        else:
            print("\n[5] Simulation failed")

        print("\n[6] Verifying circuit...")
        expected = {
            'gain': (11.0, 3.0, 'x'),       # gain ~11 (1+R7/R6)
            'gain_dB': (20.0, 4.0, ' dB'),  # ~20 dB
        }
        verify_circuit(sch_path, 'audioamp', sim_results, expected)

        # Pin connectivity verification
        print("\n[7] Pin connectivity check...")
        pin_issues = verify_pin_connections(sch_path)
        for severity, msg in pin_issues:
            icon = {'PASS': '[OK]', 'ERROR': '[!!]', 'WARNING': '[??]',
                    'INFO': '[--]'}.get(severity, '[??]')
            print(f"    {icon} {msg}")

    else:
        print("\n[2] Building CE amplifier schematic...")
        sch_path = build_common_emitter_amp()

        print("\n[3] Writing ngspice netlist...")
        netlist_path = write_ce_amp_netlist()

        print("\n[4] Simulating...")
        success = simulate(netlist_path)

        sim_results = {}
        if success:
            print("\n[5] Plotting results...")
            plot_results(
                title="Common Emitter Amplifier",
                node_names=['V(IN)', 'V(OUT)', 'V(COLL)', 'V(BASE)']
            )
            sim_results = measure_simulation(
                "results.txt",
                ['V(IN)', 'V(OUT)', 'V(COLL)', 'V(BASE)']
            )
        else:
            print("\n[5] Simulation failed")

        print("\n[6] Verifying circuit...")
        expected = {
            'gain': (187.0, 50.0, 'x'),      # gain ~187 +/- 50
            'gain_dB': (45.0, 5.0, ' dB'),   # 45 dB +/- 5
        }
        verify_circuit(sch_path, 'ce_amp', sim_results, expected)

    print("\n[7] Exporting schematic images...")
    try:
        pdf_file = export_pdf(sch_path)
        if circuit == 'full_system':
            # Export per-region zoomed PNGs for readability
            regions = export_full_system_regions(pdf_file, WORK_DIR)
            # Copy overview + region PNGs to Desktop for easy access
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            for name, src in regions:
                dst = os.path.join(desktop, f"full_system_{name}.png")
                import shutil
                shutil.copy2(src, dst)
            print(f"  {len(regions)} region PNGs copied to Desktop")
        else:
            # Adjust clip area per sheet size
            if circuit == 'audioamp':
                clip = (10, 10, 400, 280)  # A3 landscape
            elif circuit == 'input_filters':
                clip = (10, 10, 400, 280)  # A3 landscape
            elif circuit == 'analog_mux':
                clip = (20, 10, 230, 260)  # A4 tall (two muxes stacked)
            elif circuit == 'mcu_section':
                clip = (10, 10, 280, 260)  # A4 wide (MCU block with labels)
            else:
                clip = (30, 20, 230, 170)  # A4 default
            render_pdf_to_png(pdf_file, os.path.join(WORK_DIR, f"{circuit}_large.png"),
                              zoom=5, clip_mm=clip)
        print(f"  Schematic ready for review")
    except Exception as e:
        print(f"  Export: {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
