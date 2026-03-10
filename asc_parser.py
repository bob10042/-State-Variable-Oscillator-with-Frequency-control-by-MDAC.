"""
LTspice .asc file parser — generates SPICE netlists from LTspice schematics.

Parses the plain-text .asc format directly, without requiring LTspice.exe.
Handles WIRE connectivity, SYMBOL placement with rotation, FLAG node naming,
and TEXT directives. Looks up .asy files for custom symbol pin positions.

Pin offsets verified against LTspice XVII Educational examples:
    audioamp.asc, colpits.asc, astable.asc, Wien.asc
"""

import os
import re
from collections import defaultdict


# =============================================================
# Built-in symbol pin offsets at R0 rotation
# =============================================================
# Format: { 'symbol_name': [(dx, dy, spice_order, pin_name), ...] }
# Verified by tracing wire endpoints in LTspice XVII schematics.

BUILTIN_PINS = {
    # Two-terminal passives
    'res':     [(16, 16, 1, '1'), (16, 96, 2, '2')],
    'cap':     [(16,  0, 1, '1'), (16, 64, 2, '2')],
    'polcap':  [(16,  0, 1, '+'), (16, 64, 2, '-')],
    'ind':     [(16, 16, 1, '1'), (16, 96, 2, '2')],
    'ind2':    [(16, 16, 1, '1'), (16, 96, 2, '2')],
    # Sources
    'voltage': [(0, 16, 1, '+'), (0, 96, 2, '-')],
    'current': [(0, 16, 1, '+'), (0, 96, 2, '-')],
    # Behavioral sources (2-terminal)
    'bv':      [(0, 16, 1, '+'), (0, 96, 2, '-')],
    'bi':      [(0, 16, 1, '+'), (0, 96, 2, '-')],
    'bi2':     [(0, 16, 1, '+'), (0, 96, 2, '-')],
    # Controlled sources (4-terminal: out+, out-, in+, in-)
    'e':       [(0, 16, 1, 'out+'), (0, 96, 2, 'out-'),
                (-48, 32, 3, 'in+'), (-48, 80, 4, 'in-')],
    'e2':      [(0, 16, 1, 'out+'), (0, 96, 2, 'out-'),
                (-48, 32, 3, 'in+'), (-48, 80, 4, 'in-')],
    'g':       [(0, 16, 1, 'out+'), (0, 96, 2, 'out-'),
                (-48, 32, 3, 'in+'), (-48, 80, 4, 'in-')],
    'g2':      [(0, 16, 1, 'out+'), (0, 96, 2, 'out-'),
                (-48, 32, 3, 'in+'), (-48, 80, 4, 'in-')],
    'f':       [(0, 16, 1, 'out+'), (0, 96, 2, 'out-'),
                (-48, 32, 3, 'in+'), (-48, 80, 4, 'in-')],
    'h':       [(0, 16, 1, 'out+'), (0, 96, 2, 'out-'),
                (-48, 32, 3, 'in+'), (-48, 80, 4, 'in-')],
    # Diode
    'diode':   [(16,  0, 1, 'A'), (16, 64, 2, 'K')],
    'zener':   [(16,  0, 1, 'A'), (16, 64, 2, 'K')],
    'schottky':[(16,  0, 1, 'A'), (16, 64, 2, 'K')],
    'LED':     [(16,  0, 1, 'A'), (16, 64, 2, 'K')],
    'varactor':[(16,  0, 1, 'A'), (16, 64, 2, 'K')],
    # BJTs (NPN/PNP have same physical layout, different arrow)
    'npn':     [(64,  0, 1, 'C'), (0, 48, 2, 'B'), (64, 96, 3, 'E')],
    'pnp':     [(64,  0, 1, 'C'), (0, 48, 2, 'B'), (64, 96, 3, 'E')],
    'npn2':    [(64,  0, 1, 'C'), (0, 48, 2, 'B'), (64, 96, 3, 'E')],
    'pnp2':    [(64,  0, 1, 'C'), (0, 48, 2, 'B'), (64, 96, 3, 'E')],
    'npn3':    [(64,  0, 1, 'C'), (0, 48, 2, 'B'), (64, 96, 3, 'E')],
    'pnp3':    [(64,  0, 1, 'C'), (0, 48, 2, 'B'), (64, 96, 3, 'E')],
    # JFETs
    'njf':     [(48,  0, 1, 'D'), (0, 64, 2, 'G'), (48, 96, 3, 'S')],
    'pjf':     [(48,  0, 1, 'D'), (0, 64, 2, 'G'), (48, 96, 3, 'S')],
    # MOSFETs
    'nmos':    [(48,  0, 1, 'D'), (0, 64, 2, 'G'), (48, 96, 3, 'S')],
    'pmos':    [(48,  0, 1, 'D'), (0, 64, 2, 'G'), (48, 96, 3, 'S')],
    'nmos4':   [(48,  0, 1, 'D'), (0, 64, 2, 'G'), (48, 96, 3, 'S'), (48, 48, 4, 'B')],
    'pmos4':   [(48,  0, 1, 'D'), (0, 64, 2, 'G'), (48, 96, 3, 'S'), (48, 48, 4, 'B')],
    # Switches
    'sw':      [(16,  0, 1, '1'), (16, 64, 2, '2')],
    'csw':     [(16,  0, 1, '1'), (16, 64, 2, '2')],
    # Transmission line (4 pins: port1+, port1-, port2+, port2-)
    'tline':   [(-48, -16, 1, 'L+'), (-48, 16, 2, 'L-'),
                (48, -16, 3, 'R+'), (48, 16, 4, 'R-')],
    # Crystal oscillator (2-terminal like cap)
    'xtal':    [(16,  0, 1, '1'), (16, 64, 2, '2')],
    # Jumper/wire (2-terminal, just a short)
    'jumper':  [(16,  0, 1, '1'), (16, 64, 2, '2')],
    # Opamps (standard 5-pin: In+ In- V+ V- OUT)
    'opamp':   [(-32, 80, 1, 'In+'), (-32, 48, 2, 'In-'),
                (0, 32, 3, 'V+'), (0, 96, 4, 'V-'), (32, 64, 5, 'OUT')],
    'opamp2':  [(-32, 80, 1, 'In+'), (-32, 48, 2, 'In-'),
                (0, 32, 3, 'V+'), (0, 96, 4, 'V-'), (32, 64, 5, 'OUT')],
}

# SPICE prefix mapping: symbol type → netlist prefix letter
SPICE_PREFIX = {
    'res': 'R', 'cap': 'C', 'polcap': 'C', 'ind': 'L', 'ind2': 'L',
    'voltage': 'V', 'current': 'I',
    'bv': 'B', 'bi': 'B', 'bi2': 'B',
    'e': 'E', 'e2': 'E', 'g': 'G', 'g2': 'G', 'f': 'F', 'h': 'H',
    'diode': 'D', 'zener': 'D', 'schottky': 'D', 'LED': 'D', 'varactor': 'D',
    'npn': 'Q', 'pnp': 'Q', 'npn2': 'Q', 'pnp2': 'Q',
    'npn3': 'Q', 'pnp3': 'Q',
    'njf': 'J', 'pjf': 'J',
    'nmos': 'M', 'pmos': 'M', 'nmos4': 'M', 'pmos4': 'M',
    'sw': 'S', 'csw': 'W',
    'tline': 'T', 'xtal': 'X', 'jumper': 'R',
    'opamp': 'X', 'opamp2': 'X',
}


# =============================================================
# Rotation transforms
# =============================================================
# LTspice rotation codes: R0, R90, R180, R270, M0, M90, M180, M270
# M = mirror (negate X) then rotate.
# Verified against audioamp.asc, colpits.asc, astable.asc, Wien.asc.

def _transform(dx, dy, rot):
    """Apply LTspice rotation/mirror transform to pin offset (dx, dy)."""
    if rot == 'R0':
        return (dx, dy)
    elif rot == 'R90':
        return (-dy, dx)
    elif rot == 'R180':
        return (-dx, -dy)
    elif rot == 'R270':
        return (dy, -dx)
    elif rot == 'M0':
        return (-dx, dy)
    elif rot == 'M90':
        return (dy, dx)
    elif rot == 'M180':
        return (dx, -dy)
    elif rot == 'M270':
        return (-dy, -dx)
    else:
        return (dx, dy)  # Unknown rotation, treat as R0


# =============================================================
# Union-Find for coordinate connectivity
# =============================================================

class UnionFind:
    """Disjoint set data structure for merging connected coordinates."""

    def __init__(self):
        self.parent = {}
        self.rank = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


# =============================================================
# .asy symbol file parser
# =============================================================

def parse_asy_file(asy_path):
    """Parse an .asy symbol file and return pin definitions.

    Returns list of (dx, dy, spice_order, pin_name) tuples,
    or None if file cannot be parsed.
    """
    if not os.path.exists(asy_path):
        return None

    try:
        with open(asy_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception:
        return None

    pins = []
    prefix = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith('SYMATTR Prefix'):
            prefix = line.split(None, 2)[2].strip() if len(line.split(None, 2)) > 2 else None

        if line.startswith('PIN '):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    px, py = int(parts[1]), int(parts[2])
                except ValueError:
                    i += 1
                    continue
                pin_name = ''
                spice_order = 0
                # Read subsequent PINATTR lines
                j = i + 1
                while j < len(lines):
                    attr_line = lines[j].strip()
                    if attr_line.startswith('PINATTR PinName'):
                        pin_name = attr_line.split(None, 2)[2].strip() if len(attr_line.split(None, 2)) > 2 else ''
                    elif attr_line.startswith('PINATTR SpiceOrder'):
                        try:
                            spice_order = int(attr_line.split()[-1])
                        except ValueError:
                            pass
                    elif attr_line.startswith('PIN ') or attr_line.startswith('SYMATTR') or not attr_line.startswith('PINATTR'):
                        break
                    j += 1
                pins.append((px, py, spice_order, pin_name))
        i += 1

    if not pins:
        return None

    # Sort by SpiceOrder if available
    pins.sort(key=lambda p: (p[2] if p[2] > 0 else 999, p[0], p[1]))
    return pins


def _find_asy_file(symbol_name, asc_dir):
    """Search for an .asy file for a custom symbol.

    Searches: same dir as .asc, LTspice lib/sym, LTspice XVII lib/sym.
    symbol_name may contain path separators (e.g., 'opamps\\LT1001').
    """
    # Normalize path separators
    sym_path = symbol_name.replace('\\', os.sep).replace('/', os.sep)

    search_dirs = [
        asc_dir,
        os.path.expanduser(r'~\AppData\Local\LTspice\lib\sym'),
        r'C:\Program Files\LTC\LTspiceXVII\lib\sym',
        r'C:\Program Files (x86)\LTC\LTspiceXVII\lib\sym',
    ]

    for base in search_dirs:
        if not os.path.isdir(base):
            continue
        candidate = os.path.join(base, sym_path + '.asy')
        if os.path.exists(candidate):
            return candidate
        # Also try case-insensitive on Windows
        candidate_lower = os.path.join(base, sym_path.lower() + '.asy')
        if os.path.exists(candidate_lower):
            return candidate_lower

    return None


# =============================================================
# Main .asc parser
# =============================================================

def parse_asc(asc_path):
    """Parse an LTspice .asc schematic file.

    Returns a dict with:
        'netlist': str - complete SPICE netlist text
        'nodes': list[str] - all node names
        'components': list[dict] - component info
        'directives': list[str] - SPICE directives from TEXT statements
        'sim_command': str - simulation command (e.g., '.tran 10m')
        'models': list[str] - .model statements
        'error': str or None
    """
    if not os.path.exists(asc_path):
        return {'error': f'File not found: {asc_path}', 'netlist': ''}

    asc_dir = os.path.dirname(os.path.abspath(asc_path))

    try:
        # LTspice .asc files use Windows-1252 encoding (µ = 0xB5 for micro)
        with open(asc_path, 'r', encoding='cp1252', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        return {'error': f'Cannot read file: {e}', 'netlist': ''}

    # Parse all statements
    wires = []          # [(x1, y1, x2, y2), ...]
    flags = []          # [(x, y, name), ...]
    symbols = []        # [{'type': ..., 'x': ..., 'y': ..., 'rot': ..., 'attrs': {}}, ...]
    directives = []     # SPICE directives from TEXT statements
    models = []         # .model statements
    sim_command = ''

    current_symbol = None

    for line in lines:
        line = line.rstrip('\n\r')
        stripped = line.strip()

        if stripped.startswith('WIRE '):
            parts = stripped.split()
            if len(parts) >= 5:
                try:
                    wires.append((int(parts[1]), int(parts[2]),
                                  int(parts[3]), int(parts[4])))
                except ValueError:
                    pass

        elif stripped.startswith('FLAG '):
            parts = stripped.split()
            if len(parts) >= 4:
                try:
                    # Sanitize node name for ngspice compatibility
                    fname = parts[3]
                    # Replace +/- chars that cause parsing issues in V(+V) etc.
                    fname = fname.replace('+', 'p').replace('-', 'n')
                    # Remove other invalid chars (keep alphanumeric and _)
                    fname = re.sub(r'[^A-Za-z0-9_]', '_', fname)
                    flags.append((int(parts[1]), int(parts[2]), fname))
                except ValueError:
                    pass

        elif stripped.startswith('SYMBOL '):
            # Save previous symbol if any
            if current_symbol:
                symbols.append(current_symbol)
            parts = stripped.split()
            if len(parts) >= 5:
                try:
                    current_symbol = {
                        'type': parts[1],
                        'x': int(parts[2]),
                        'y': int(parts[3]),
                        'rot': parts[4],
                        'attrs': {},
                    }
                except ValueError:
                    current_symbol = None

        elif stripped.startswith('SYMATTR '):
            if current_symbol:
                parts = stripped.split(None, 2)
                if len(parts) >= 3:
                    current_symbol['attrs'][parts[1]] = parts[2]
                elif len(parts) == 2:
                    current_symbol['attrs'][parts[1]] = ''

        elif stripped.startswith('WINDOW '):
            pass  # Visual only, ignore

        elif stripped.startswith('TEXT '):
            # Extract SPICE directives (prefixed with !)
            m = re.match(r'TEXT\s+[-\d]+\s+[-\d]+\s+\w+\s+\d+\s+(.*)', stripped)
            if m:
                text_content = m.group(1)
                if text_content.startswith('!'):
                    directive = text_content[1:].strip()
                    # Convert µ to u for SPICE compatibility
                    directive = directive.replace('\u00b5', 'u').replace('\u03bc', 'u')
                    # Handle multi-line (LTspice uses \n in TEXT)
                    for sub_line in directive.split('\\n'):
                        sub_line = sub_line.strip()
                        if not sub_line:
                            continue
                        upper = sub_line.upper()
                        if upper.startswith('.TRAN') or upper.startswith('.AC') or upper.startswith('.DC') or upper.startswith('.NOISE'):
                            sim_command = sub_line
                        if upper.startswith('.MODEL'):
                            models.append(sub_line)
                        directives.append(sub_line)

    # Don't forget last symbol
    if current_symbol:
        symbols.append(current_symbol)

    # ---- Build coordinate connectivity using Union-Find ----
    uf = UnionFind()

    # Connect wire endpoints
    for x1, y1, x2, y2 in wires:
        uf.union((x1, y1), (x2, y2))

    # Cache for .asy file lookups
    asy_cache = {}

    # Map for path-prefixed symbols to their built-in equivalent
    MISC_SYMBOL_MAP = {
        'jumper': 'jumper', 'xtal': 'xtal',
        'diac': 'diode', 'triac': 'nmos',  # approximate: 2-pin / 3-pin
        'nigbt': 'nmos',  # IGBT ≈ 3-pin like MOSFET (G, C, E)
        'towtom2': 'nmos',  # Townsend tube ≈ 3-pin
        'varistor': 'res',  # varistor ≈ 2-pin resistor
    }

    def _get_pins(sym):
        """Get pin offsets for a symbol, checking built-in table then .asy files."""
        sym_type = sym['type'].lower()
        # Strip path prefix for built-in lookup
        base_name = sym_type.split('\\')[-1].split('/')[-1]

        if base_name in BUILTIN_PINS:
            return BUILTIN_PINS[base_name]

        # Check misc/specialfunctions symbol mapping
        if base_name in MISC_SYMBOL_MAP:
            mapped = MISC_SYMBOL_MAP[base_name]
            if mapped in BUILTIN_PINS:
                return BUILTIN_PINS[mapped]

        # Check cache
        if sym_type in asy_cache:
            return asy_cache[sym_type]

        # Try to find and parse .asy file
        asy_path = _find_asy_file(sym['type'], asc_dir)
        if asy_path:
            pins = parse_asy_file(asy_path)
            asy_cache[sym_type] = pins
            return pins

        # Fallback: detect opamp-like symbols from path or prefix
        if sym_type.startswith('opamps\\') or sym_type.startswith('opamps/') or \
           sym_type.upper().startswith('OPAMPS\\') or sym_type.upper().startswith('OPAMPS/'):
            pins = BUILTIN_PINS.get('opamp')
            asy_cache[sym_type] = pins
            return pins

        prefix = sym.get('attrs', {}).get('Prefix', '').upper()
        if prefix in ('X', 'XU') and base_name not in BUILTIN_PINS:
            # Assume 5-pin opamp layout
            pins = BUILTIN_PINS.get('opamp')
            asy_cache[sym_type] = pins
            return pins

        asy_cache[sym_type] = None
        return None

    # ---- Connect component pins to the wire network ----
    component_pins = []  # [(symbol_dict, [(abs_x, abs_y, spice_order, pin_name), ...]), ...]

    for sym in symbols:
        pins = _get_pins(sym)
        if pins is None:
            # Unknown symbol — we can't determine connectivity
            component_pins.append((sym, None))
            continue

        abs_pins = []
        for dx, dy, order, name in pins:
            tdx, tdy = _transform(dx, dy, sym['rot'])
            ax, ay = sym['x'] + tdx, sym['y'] + tdy
            abs_pins.append((ax, ay, order, name))
            # Register this coordinate in the union-find
            uf.find((ax, ay))

        component_pins.append((sym, abs_pins))

    # ---- Connect pins to wires ----
    # A pin connects to a wire if the pin coordinate matches a wire endpoint
    # The union-find already has all wire endpoints connected.
    # We just need to union pin coordinates with any wire endpoint at the same position.

    # Build a set of all wire endpoint coordinates for fast lookup
    wire_coords = set()
    for x1, y1, x2, y2 in wires:
        wire_coords.add((x1, y1))
        wire_coords.add((x2, y2))

    for sym, abs_pins in component_pins:
        if abs_pins is None:
            continue
        for ax, ay, _, _ in abs_pins:
            if (ax, ay) in wire_coords:
                uf.union((ax, ay), (ax, ay))  # Already connected via wire endpoints
            # Also check if any wire endpoint is at this exact coordinate
            # (already handled by Union-Find find/union being idempotent)

    # Flag coordinates also connect to the wire network
    for fx, fy, fname in flags:
        uf.find((fx, fy))
        if (fx, fy) in wire_coords:
            pass  # Already in the network

    # ---- Assign node names ----
    # Each connected component (set of coordinates) gets a node name.
    # Named flags take priority, then auto-generated names.

    # First, gather all coordinates and their root representatives
    all_coords = set()
    for x1, y1, x2, y2 in wires:
        all_coords.add((x1, y1))
        all_coords.add((x2, y2))
    for sym, abs_pins in component_pins:
        if abs_pins:
            for ax, ay, _, _ in abs_pins:
                all_coords.add((ax, ay))
    for fx, fy, _ in flags:
        all_coords.add((fx, fy))

    # Map root → node name
    root_to_name = {}
    auto_counter = [0]

    # First pass: assign names from flags
    for fx, fy, fname in flags:
        root = uf.find((fx, fy))
        if fname == '0':
            root_to_name[root] = '0'
        elif root not in root_to_name or root_to_name[root].startswith('N'):
            root_to_name[root] = fname

    def _get_node_name(coord):
        root = uf.find(coord)
        if root in root_to_name:
            return root_to_name[root]
        # Auto-generate name
        auto_counter[0] += 1
        name = f'N{auto_counter[0]:03d}'
        root_to_name[root] = name
        return name

    # ---- Generate netlist ----
    netlist_lines = []
    circuit_name = os.path.splitext(os.path.basename(asc_path))[0]
    netlist_lines.append(f'* {circuit_name}')
    netlist_lines.append(f'* Generated by asc_parser.py from {os.path.basename(asc_path)}')
    netlist_lines.append('')

    all_node_names = set()
    components_info = []
    unknown_symbols = []
    used_names = {}  # Track used component names: name_upper -> count

    def _fix_spice_value(val):
        """Convert LTspice value encoding to ngspice-compatible."""
        # LTspice uses µ (U+00B5) for micro — ngspice wants 'u'
        val = val.replace('\u00b5', 'u').replace('\u03bc', 'u')
        # Also handle Ω → ohm (just strip it, value is implicit)
        val = val.replace('\u2126', '').replace('\u03a9', '')
        return val

    for sym, abs_pins in component_pins:
        inst_name = sym['attrs'].get('InstName', '')
        value = _fix_spice_value(sym['attrs'].get('Value', ''))
        spice_line = _fix_spice_value(sym['attrs'].get('SpiceLine', ''))
        sym_type_lower = sym['type'].lower().split('\\')[-1].split('/')[-1]

        if abs_pins is None:
            unknown_symbols.append(sym)
            continue

        # Sort pins by spice order
        sorted_pins = sorted(abs_pins, key=lambda p: p[2])

        # Get node names for each pin
        pin_nodes = []
        for ax, ay, order, pname in sorted_pins:
            node = _get_node_name((ax, ay))
            pin_nodes.append(node)
            if node != '0':
                all_node_names.add(node)

        # Determine SPICE prefix
        prefix = SPICE_PREFIX.get(sym_type_lower, '')
        if not prefix:
            # Check attrs for prefix
            attr_prefix = sym['attrs'].get('Prefix', '').strip()
            if attr_prefix:
                prefix = attr_prefix[0] if attr_prefix[0].isalpha() else 'X'
            else:
                prefix = 'X'  # Default to subcircuit

        # Build instance name
        if inst_name:
            # Ensure instance name starts with correct SPICE prefix
            if inst_name[0].upper() == prefix[0].upper():
                spice_name = inst_name
            else:
                # LTspice may use Q for JFETs, but ngspice requires J
                # Replace the first letter with the correct prefix
                suffix = inst_name[1:] if len(inst_name) > 1 else '1'
                spice_name = prefix + suffix
        else:
            spice_name = f'{prefix}_{sym_type_lower}'

        # Ensure unique component names (avoid duplicates that crash ngspice)
        name_key = spice_name.upper()
        if name_key in used_names:
            used_names[name_key] += 1
            # Append suffix to make unique: R1 -> R1_2, R1_3, etc.
            spice_name = f'{spice_name}_{used_names[name_key]}'
        else:
            used_names[name_key] = 1

        # Build netlist line based on component type
        nodes_str = ' '.join(pin_nodes)

        if prefix.upper() in ('R', 'C', 'L'):
            # Passive: R1 node1 node2 value
            line = f'{spice_name} {nodes_str} {value}'
            if spice_line:
                line += f' {spice_line}'
        elif prefix.upper() == 'V':
            # Voltage source: V1 node+ node- value
            line = f'{spice_name} {nodes_str} {value}'
        elif prefix.upper() == 'I':
            # Current source: I1 node+ node- value
            line = f'{spice_name} {nodes_str} {value}'
        elif prefix.upper() == 'B':
            # Behavioral source: B1 node+ node- V=expr or I=expr
            # bv → V=, bi/bi2 → I=
            if sym_type_lower == 'bv':
                line = f'{spice_name} {nodes_str} {value}'
            else:
                line = f'{spice_name} {nodes_str} {value}'
        elif prefix.upper() in ('E', 'G'):
            # VCVS/VCCS: E1 out+ out- in+ in- gain_or_expr
            line = f'{spice_name} {nodes_str} {value}'
        elif prefix.upper() in ('F', 'H'):
            # CCCS/CCVS: F1 out+ out- Vsource gain
            line = f'{spice_name} {nodes_str} {value}'
        elif prefix.upper() == 'T':
            # Transmission line: T1 port1+ port1- port2+ port2- Z0=val Td=val
            if spice_line:
                line = f'{spice_name} {nodes_str} {spice_line}'
            elif value:
                line = f'{spice_name} {nodes_str} {value}'
            else:
                line = f'{spice_name} {nodes_str} Z0=50 Td=1n'
        elif prefix.upper() == 'D':
            # Diode: D1 anode cathode model
            line = f'{spice_name} {nodes_str} {value}'
        elif prefix.upper() == 'Q':
            # BJT: Q1 C B E model
            line = f'{spice_name} {nodes_str} {value}'
        elif prefix.upper() in ('J', 'M'):
            # JFET/MOSFET: J1 D G S model
            line = f'{spice_name} {nodes_str} {value}'
            if spice_line:
                line += f' {spice_line}'
        elif prefix.upper() in ('X', 'U'):
            # Subcircuit: X1 pin1 pin2 ... subckt_name
            # If no value, use the base symbol name as subckt name
            subckt_name = value if value else sym['type'].split('\\')[-1].split('/')[-1]
            line = f'{spice_name} {nodes_str} {subckt_name}'
        elif prefix.upper() == 'S':
            # Voltage-controlled switch: S1 n+ n- nc+ nc- model
            line = f'{spice_name} {nodes_str} {value}'
        elif prefix.upper() == 'W':
            # Current-controlled switch: W1 n+ n- Vsource model
            line = f'{spice_name} {nodes_str} {value}'
        else:
            line = f'{spice_name} {nodes_str} {value}'

        netlist_lines.append(line)
        components_info.append({
            'name': spice_name,
            'type': sym_type_lower,
            'value': value,
            'nodes': pin_nodes,
            'prefix': prefix,
        })

    # Add model statements from TEXT directives
    if models:
        netlist_lines.append('')
        netlist_lines.append('* Models')
        for m in models:
            netlist_lines.append(m)

    # Add other directives (excluding sim commands and models)
    other_directives = []
    for d in directives:
        upper = d.upper().strip()
        if upper.startswith('.MODEL'):
            continue  # Already added
        if upper.startswith('.TRAN') or upper.startswith('.AC') or upper.startswith('.DC') or upper.startswith('.NOISE'):
            continue  # Sim command handled separately
        other_directives.append(d)

    if other_directives:
        netlist_lines.append('')
        netlist_lines.append('* Directives')
        for d in other_directives:
            netlist_lines.append(d)

    # Add sim command
    if sim_command:
        netlist_lines.append('')
        netlist_lines.append(sim_command)

    # End statement
    netlist_lines.append('')
    netlist_lines.append('.end')

    # Collect all unique node names (excluding ground)
    all_nodes_sorted = sorted(n for n in all_node_names if n != '0')

    # Build warnings for unknown symbols
    warnings = []
    if unknown_symbols:
        for sym in unknown_symbols:
            warnings.append(f"Unknown symbol '{sym['type']}' (inst: {sym['attrs'].get('InstName', '?')})")

    return {
        'netlist': '\n'.join(netlist_lines),
        'nodes': all_nodes_sorted,
        'components': components_info,
        'directives': directives,
        'sim_command': sim_command,
        'models': models,
        'warnings': warnings,
        'error': None,
    }


def asc_to_cir(asc_path, output_path=None):
    """Convert an .asc file to a .cir SPICE netlist file.

    Args:
        asc_path: Path to the .asc file
        output_path: Path for output .cir file (default: same name with .cir extension)

    Returns:
        (success: bool, output_path: str, error: str or None)
    """
    result = parse_asc(asc_path)

    if result['error']:
        return False, '', result['error']

    if not output_path:
        output_path = os.path.splitext(asc_path)[0] + '.cir'

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result['netlist'])
    except Exception as e:
        return False, '', f'Cannot write output: {e}'

    return True, output_path, None


# =============================================================
# Search for .model and .lib files referenced by an .asc
# =============================================================

def find_model_files(asc_path, model_names):
    """Search for .model/.lib files that define the given model names.

    Looks in: same dir as .asc, LTspice lib directories.
    Returns list of (model_name, file_path) tuples found.
    """
    asc_dir = os.path.dirname(os.path.abspath(asc_path))

    search_dirs = [
        asc_dir,
        os.path.expanduser(r'~\AppData\Local\LTspice\lib\cmp'),
        os.path.expanduser(r'~\AppData\Local\LTspice\lib\sub'),
        r'C:\Program Files\LTC\LTspiceXVII\lib\cmp',
        r'C:\Program Files\LTC\LTspiceXVII\lib\sub',
    ]

    found = []
    for name in model_names:
        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            # Check for standard .lib or .sub files
            for ext in ('.lib', '.sub', '.mod'):
                candidate = os.path.join(d, name + ext)
                if os.path.exists(candidate):
                    found.append((name, candidate))
                    break
            # Also check standard.bjt, standard.mos etc
            for std_file in ('standard.bjt', 'standard.mos', 'standard.jft',
                             'standard.dio'):
                std_path = os.path.join(d, std_file)
                if os.path.exists(std_path):
                    try:
                        with open(std_path, 'r', errors='replace') as f:
                            content = f.read()
                        if re.search(rf'\.model\s+{re.escape(name)}\s',
                                     content, re.IGNORECASE):
                            found.append((name, std_path))
                            break
                    except Exception:
                        pass
    return found


# =============================================================
# Standalone CLI
# =============================================================

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python asc_parser.py <file.asc> [output.cir]")
        print("  Converts LTspice .asc schematic to SPICE netlist (.cir)")
        sys.exit(1)

    asc_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else None

    result = parse_asc(asc_file)

    if result['error']:
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    if result.get('warnings'):
        for w in result['warnings']:
            print(f"WARNING: {w}")

    print(f"Parsed: {len(result['components'])} components, {len(result['nodes'])} nodes")
    print(f"Nodes: {', '.join(result['nodes'][:20])}")
    if result['sim_command']:
        print(f"Sim command: {result['sim_command']}")

    if out_file:
        success, path, err = asc_to_cir(asc_file, out_file)
        if success:
            print(f"Written: {path}")
        else:
            print(f"ERROR: {err}")
    else:
        print()
        print(result['netlist'])
