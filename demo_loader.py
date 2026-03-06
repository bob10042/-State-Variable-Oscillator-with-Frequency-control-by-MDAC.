"""
LTspice Demo Circuit Loader
============================
Uses LTspice to generate netlist from .asc,
cleans it up for ngspice, simulates, and plots.
"""

import subprocess
import os
import re
import sys
import time
import numpy as np
import matplotlib.pyplot as plt

NGSPICE = r"C:\Spice64\bin\ngspice_con.exe"
LTSPICE = r"C:\Program Files\ADI\LTspice\LTspice.exe"
LIB_DIR = os.path.expanduser("~/Documents/LTspice/lib")
WORK_DIR = os.path.expanduser("~/Documents/LTspice/demo_work")


def read_ltspice_file(path):
    """Read an LTspice file, handling its encoding quirks."""
    # Try UTF-16LE first (common for LTspice generated files)
    for enc in ['utf-16-le', 'utf-8', 'latin-1', 'cp1252']:
        try:
            with open(path, 'r', encoding=enc) as f:
                content = f.read()
            # Verify it looks like a netlist
            if any(c in content.lower() for c in ['.end', '.tran', '.ac', 'wire']):
                return content
        except (UnicodeDecodeError, UnicodeError):
            continue

    # Fallback: read as bytes and decode aggressively
    with open(path, 'rb') as f:
        raw = f.read()
    # Strip null bytes (UTF-16 artifact)
    content = raw.replace(b'\x00', b'').decode('latin-1', errors='replace')
    return content


def generate_netlist(asc_path):
    """Use LTspice to generate .net from .asc."""
    print(f"Using LTspice to generate netlist from {os.path.basename(asc_path)}...")

    result = subprocess.run(
        [LTSPICE, "-netlist", asc_path],
        capture_output=True, timeout=30
    )
    time.sleep(2)

    base = os.path.splitext(asc_path)[0]
    net_path = base + ".net"

    if os.path.exists(net_path):
        content = read_ltspice_file(net_path)
        print(f"  Generated: {net_path}")
        return content
    else:
        print("  Failed to generate netlist!")
        return None


def clean_for_ngspice(raw_netlist):
    """Clean an LTspice netlist for ngspice compatibility."""
    lines = raw_netlist.split('\n')
    clean = []
    sim_cmd = None
    flag_nodes = set()
    lib_lines = []
    model_lines = []

    for line in lines:
        # Strip whitespace and non-printable chars
        line = line.strip()
        line = re.sub(r'[^\x20-\x7e]', '', line)  # ASCII only

        if not line:
            continue

        # Remove LTspice-specific inline comments with special chars
        # e.g., ";pnba In+)In-)V+)V-)OUT"
        if ';' in line:
            line = line[:line.index(';')].strip()

        if not line:
            continue

        # Skip .backanno
        if line.lower().startswith('.backanno'):
            continue

        # Skip .end (we add our own)
        if line.lower() == '.end':
            continue

        # Handle .lib directives
        if line.lower().startswith('.lib'):
            lib_name = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else ''
            # Resolve library path
            resolved = resolve_lib(lib_name)
            if resolved:
                lib_lines.append(resolved)
            continue

        # Capture simulation command
        if re.match(r'\.(tran|ac|dc|noise|op)\b', line, re.I):
            # Remove 'startup' keyword (ngspice doesn't support it)
            line = re.sub(r'\bstartup\b', '', line, flags=re.I).strip()
            sim_cmd = line
            continue

        # Capture .model / .subckt / .ends / .param / .step
        if re.match(r'\.(model|subckt|ends|param|step)\b', line, re.I):
            model_lines.append(line)
            continue

        # Comments starting with *
        if line.startswith('*'):
            clean.append(line)
            continue

        # Component lines - extract named nodes
        parts = line.split()
        if len(parts) >= 2:
            # First token is component name
            comp_name = parts[0]

            # Collect node names (not component values)
            # Nodes are the tokens between component name and value
            # For R, C, L: name node1 node2 value
            # For V, I: name node+ node- value
            # For Q, M, J, X: name nodes... model
            first_char = comp_name[0].upper()

            if first_char in ('R', 'C', 'L', 'V', 'I', 'D'):
                # 2-terminal: parts[1] and parts[2] are nodes
                for p in parts[1:3]:
                    if p not in ('0',) and not p.startswith('.'):
                        flag_nodes.add(p)
            elif first_char in ('Q', 'J', 'M'):
                # 3-4 terminal transistors
                for p in parts[1:4]:
                    if p not in ('0',) and not p.startswith('.'):
                        flag_nodes.add(p)
            elif first_char == 'X':
                # Subcircuit: all tokens except first and last are nodes
                for p in parts[1:-1]:
                    if p not in ('0',) and not p.startswith('.'):
                        flag_nodes.add(p)

        clean.append(line)

    return clean, sim_cmd, flag_nodes, lib_lines, model_lines


def resolve_lib(lib_name):
    """Resolve a .lib reference to a .include path for ngspice."""
    # Direct path?
    if os.path.exists(lib_name):
        return f".include {lib_name}"

    # Strip path, just use filename
    basename = os.path.basename(lib_name)
    name_no_ext = os.path.splitext(basename)[0]

    # Search common locations
    search_paths = [
        os.path.join(LIB_DIR, "sub", f"{name_no_ext}.sub"),
        os.path.join(LIB_DIR, "sub", basename),
        os.path.join(LIB_DIR, "cmp", basename),
        lib_name,  # as-is
    ]

    # Handle standard.xxx files
    if basename.startswith('standard.'):
        search_paths.insert(0, os.path.join(LIB_DIR, "cmp", basename))

    # Handle LTC.lib (contains all LT subcircuits)
    if basename.lower() == 'ltc.lib':
        # This is a meta-library - we need to find specific .sub files
        return None  # handled per-component

    for path in search_paths:
        if os.path.exists(path):
            return f".include {path}"

    return f"* WARNING: Library not found: {lib_name}"


def find_subckt_lib(subckt_name):
    """Find the .sub file containing a subcircuit definition."""
    sub_dir = os.path.join(LIB_DIR, "sub")
    # Direct match
    direct = os.path.join(sub_dir, f"{subckt_name}.sub")
    if os.path.exists(direct):
        return direct

    # Search all .sub files (slow but thorough)
    # For now just try common patterns
    for variant in [subckt_name, subckt_name.upper(), subckt_name.lower()]:
        p = os.path.join(sub_dir, f"{variant}.sub")
        if os.path.exists(p):
            return p

    return None


def build_ngspice_netlist(clean_lines, sim_cmd, flag_nodes, lib_lines,
                          model_lines, subckt_names):
    """Assemble the final ngspice-compatible netlist."""
    final = []

    # Title (first comment line)
    final.append(clean_lines[0] if clean_lines and clean_lines[0].startswith('*') else "* Demo circuit")
    final.append("")

    # Circuit lines
    for line in clean_lines[1:] if clean_lines[0].startswith('*') else clean_lines:
        final.append(line)
    final.append("")

    # Model definitions
    for m in model_lines:
        final.append(m)
    final.append("")

    # Library includes
    for lib in lib_lines:
        final.append(lib)

    # Find and include .sub files for subcircuits
    for name in subckt_names:
        sub_path = find_subckt_lib(name)
        if sub_path:
            final.append(f".include {sub_path}")
        else:
            final.append(f"* WARNING: subcircuit {name} not found")
    final.append("")

    # Simulation command
    if sim_cmd:
        final.append(sim_cmd)
    else:
        final.append(".tran 1u 10m")
    final.append("")

    # Pick interesting nodes to plot (named nodes, skip internal N### ones)
    named = sorted([n for n in flag_nodes if not re.match(r'^N\d+$', n)])
    internal = sorted([n for n in flag_nodes if re.match(r'^N\d+$', n)])
    plot_nodes = (named + internal)[:6]

    # Control block
    final.append(".control")
    final.append("run")
    if plot_nodes:
        save_str = " ".join([f"V({n})" for n in plot_nodes])
        final.append(f"wrdata results.txt {save_str}")
    final.append("quit")
    final.append(".endc")
    final.append("")
    final.append(".end")

    return "\n".join(final), plot_nodes


def run_ngspice(netlist_path):
    """Run ngspice simulation."""
    work_dir = os.path.dirname(netlist_path)
    print(f"Running ngspice...")

    result = subprocess.run(
        [NGSPICE, "-b", netlist_path],
        capture_output=True, text=True,
        cwd=work_dir, timeout=120
    )

    if result.stdout:
        lines = result.stdout.strip().split('\n')
        print("  Last 10 lines:")
        for l in lines[-10:]:
            print(f"    {l}")

    if result.returncode != 0 and result.stderr:
        err = result.stderr.strip().split('\n')
        print("  ERRORS:")
        for l in err[-8:]:
            print(f"    {l}")

    return result.returncode == 0


def plot_results(work_dir, node_names, title):
    """Plot the simulation results."""
    results_path = os.path.join(work_dir, "results.txt")
    if not os.path.exists(results_path):
        print("  No results file!")
        return None

    data = np.loadtxt(results_path)
    print(f"  Data shape: {data.shape}")

    ncols = data.shape[1]
    n_nodes = len(node_names)

    # ngspice wrdata writes paired columns: time1 val1 time2 val2 ...
    if ncols >= n_nodes * 2:
        time = data[:, 0]
        values = [data[:, i*2+1] for i in range(n_nodes)]
    else:
        time = data[:, 0]
        values = [data[:, i+1] for i in range(min(n_nodes, ncols-1))]

    n_plots = min(len(values), 4)
    fig, axes = plt.subplots(n_plots, 1, figsize=(14, n_plots * 2.5), sharex=True)
    if n_plots == 1:
        axes = [axes]

    fig.suptitle(title, fontsize=14, fontweight='bold')
    fig.patch.set_facecolor('#1a1a2e')
    colors = ['#00d4ff', '#ff6b6b', '#ffd93d', '#6bcb77', '#ff9f43', '#a29bfe']

    for i in range(n_plots):
        ax = axes[i]
        ax.set_facecolor('#16213e')
        ax.plot(time * 1000, values[i], color=colors[i % len(colors)], linewidth=0.8)
        ax.set_ylabel(f'V({node_names[i]})', color='white', fontsize=9)
        ax.tick_params(colors='white')
        ax.grid(True, alpha=0.2, color='white')
        for spine in ax.spines.values():
            spine.set_color('#333')

    axes[-1].set_xlabel('Time (ms)', color='white')
    plt.tight_layout()

    plot_path = os.path.join(work_dir, "demo_results.png")
    plt.savefig(plot_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    print(f"  Saved: {plot_path}")
    plt.close()
    return plot_path


def load_demo(asc_path):
    """Main: load .asc demo -> netlist -> simulate -> plot."""
    name = os.path.splitext(os.path.basename(asc_path))[0]
    print("=" * 60)
    print(f"  Loading: {name}")
    print("=" * 60)

    os.makedirs(WORK_DIR, exist_ok=True)

    # Step 1: LTspice generates netlist
    raw = generate_netlist(asc_path)
    if not raw:
        return

    # Step 2: Clean for ngspice
    clean, sim_cmd, nodes, libs, models = clean_for_ngspice(raw)

    # Find subcircuit references (X lines)
    subckt_names = set()
    for line in clean:
        if line.startswith('X') or line.startswith('x'):
            parts = line.split()
            if parts:
                subckt_names.add(parts[-1])  # last token is subckt name

    print(f"\n  Circuit lines: {len(clean)}")
    print(f"  Sim command: {sim_cmd}")
    print(f"  Nodes found: {sorted(nodes)}")
    print(f"  Subcircuits: {sorted(subckt_names)}")
    print(f"  Libraries: {len(libs)}")

    # Step 3: Build ngspice netlist
    netlist, plot_nodes = build_ngspice_netlist(
        clean, sim_cmd, nodes, libs, models, subckt_names
    )

    netlist_path = os.path.join(WORK_DIR, f"{name}_ngspice.cir")
    with open(netlist_path, 'w') as f:
        f.write(netlist)

    print(f"\n  Netlist saved: {netlist_path}")
    print(f"  Will plot: {plot_nodes}")

    # Print the netlist for inspection
    print(f"\n  --- Netlist ---")
    for line in netlist.split('\n'):
        print(f"  {line}")
    print(f"  --- End ---\n")

    # Step 4: Simulate
    success = run_ngspice(netlist_path)

    # Step 5: Plot
    if success:
        plot_results(WORK_DIR, plot_nodes, f"LTspice Demo: {name}")

    print("\nDone!")
    return netlist_path


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = os.path.expanduser(
            "~/Documents/LTspice/examples/Educational/Wien.asc"
        )
    load_demo(path)
