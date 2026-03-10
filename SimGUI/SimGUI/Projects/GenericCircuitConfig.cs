using System.Globalization;
using System.Text.Json;
using ScottPlot;
using SimGUI.Models;
using SimGUI.Services;

namespace SimGUI.Projects;

/// <summary>
/// Project configuration for generic circuit simulation.
/// Loads any .asc (LTspice) or .cir (ngspice) circuit, runs
/// user-selected analyses (transient, AC/Bode), and displays results.
/// </summary>
public class GenericCircuitConfig : IProjectConfig
{
    private static readonly string WorkDir = SimulationRunner.RepoRoot;
    private static readonly string SimWorkDir = Path.Combine(WorkDir, "sim_work");

    // 12-colour palette for node traces
    private static readonly ScottPlot.Color[] NodeColors = new ScottPlot.Color[]
    {
        ScottPlot.Color.FromHex("#1f77b4"), ScottPlot.Color.FromHex("#ff7f0e"),
        ScottPlot.Color.FromHex("#2ca02c"), ScottPlot.Color.FromHex("#d62728"),
        ScottPlot.Color.FromHex("#9467bd"), ScottPlot.Color.FromHex("#8c564b"),
        ScottPlot.Color.FromHex("#e377c2"), ScottPlot.Color.FromHex("#7f7f7f"),
        ScottPlot.Color.FromHex("#bcbd22"), ScottPlot.Color.FromHex("#17becf"),
        ScottPlot.Color.FromHex("#aa40fc"), ScottPlot.Color.FromHex("#008080"),
    };

    // Dynamic state — set by MainForm after analyze_circuit
    private string _circuitPath = "";
    private string _circuitName = "";
    private string _circuitType = "";
    private string[] _allNodes = Array.Empty<string>();
    private string[] _selectedProbes = Array.Empty<string>();
    private string[] _selectedAnalyses = { "transient" };
    private GenericCircuitResult? _lastResult;

    // View mode toggle
    public enum ViewMode { Transient, Bode }
    public ViewMode CurrentView { get; set; } = ViewMode.Transient;

    // IProjectConfig implementation
    public string ProjectName => "General Circuit";
    public string FormTitle => string.IsNullOrEmpty(_circuitName)
        ? "SimGUI - General Circuit Simulator"
        : $"SimGUI - {_circuitName} ({_circuitType})";

    public string[] SweepPointNames => _selectedProbes.Length > 0
        ? _selectedProbes.Select(n => $"Node: {n}").ToArray()
        : new[] { "(Load a circuit first)" };

    public string RunSingleLabel => "Simulate";
    public string RunAllLabel => "Simulate All";
    public int DefaultSweepIndex => 0;
    public int SweepCount => Math.Max(_selectedProbes.Length, 1);

    public string[] StatusBarLabels => new[]
        { "Circuit", "Type", "Nodes", "Analysis", "Gain", "Status" };

    // --- Public configuration methods (called by MainForm) ---

    public void SetCircuitInfo(string path, string name, string circuitType,
        string[] allNodes, string[] selectedProbes, string[] selectedAnalyses)
    {
        _circuitPath = path;
        _circuitName = name;
        _circuitType = circuitType;
        _allNodes = allNodes;
        _selectedProbes = selectedProbes;
        _selectedAnalyses = selectedAnalyses;
    }

    public string CircuitPath => _circuitPath;
    public string[] SelectedProbes => _selectedProbes;
    public string[] SelectedAnalyses => _selectedAnalyses;
    public bool HasCircuit => !string.IsNullOrEmpty(_circuitPath);
    public bool HasAcData => _lastResult?.AcNodes.Count > 0;

    // ---- Runner ----

    public string GetCommandArgs(int sweepIndex)
    {
        string analyses = string.Join(",", _selectedAnalyses);
        string nodes = string.Join(",", _selectedProbes);
        return $"generic_sim \"{_circuitPath}\" --analyses {analyses} --nodes {nodes}";
    }

    public string GetResultsFilePath(int sweepIndex)
    {
        return Path.Combine(SimWorkDir, "generic_sim_meta.json");
    }

    // ---- Grid ----

    public DataGridViewColumn[] CreateGridColumns()
    {
        if (CurrentView == ViewMode.Bode)
        {
            return new DataGridViewColumn[]
            {
                new DataGridViewTextBoxColumn { Name = "Node", HeaderText = "Node", Width = 80 },
                new DataGridViewTextBoxColumn { Name = "DcGain", HeaderText = "DC Gain (dB)", Width = 90 },
                new DataGridViewTextBoxColumn { Name = "MaxGain", HeaderText = "Peak (dB)", Width = 80 },
                new DataGridViewTextBoxColumn { Name = "MinPhase", HeaderText = "Min Phase (\u00b0)", Width = 85 },
                new DataGridViewTextBoxColumn { Name = "MaxPhase", HeaderText = "Max Phase (\u00b0)", Width = 85 },
                new DataGridViewTextBoxColumn { Name = "Status", HeaderText = "Status", Width = 55 },
            };
        }

        return new DataGridViewColumn[]
        {
            new DataGridViewTextBoxColumn { Name = "Node", HeaderText = "Node", Width = 80 },
            new DataGridViewTextBoxColumn { Name = "Vpp", HeaderText = "Vpp (V)", Width = 75 },
            new DataGridViewTextBoxColumn { Name = "Vdc", HeaderText = "Vdc (V)", Width = 75 },
            new DataGridViewTextBoxColumn { Name = "Vrms", HeaderText = "Vrms (V)", Width = 75 },
            new DataGridViewTextBoxColumn { Name = "Vmin", HeaderText = "Vmin (V)", Width = 75 },
            new DataGridViewTextBoxColumn { Name = "Vmax", HeaderText = "Vmax (V)", Width = 75 },
            new DataGridViewTextBoxColumn { Name = "Freq", HeaderText = "Freq (Hz)", Width = 85 },
            new DataGridViewTextBoxColumn { Name = "Status", HeaderText = "Status", Width = 55 },
        };
    }

    public void PopulateGrid(DataGridView grid, object result)
    {
        if (result is not GenericCircuitResult gcr) return;

        if (CurrentView == ViewMode.Bode)
        {
            foreach (var node in gcr.AcNodes)
            {
                double dcGain = node.MagnitudeDb.Length > 0 ? node.MagnitudeDb[0] : 0;
                double maxGain = node.MagnitudeDb.Length > 0 ? node.MagnitudeDb.Max() : 0;
                double minPhase = node.PhaseDeg.Length > 0 ? node.PhaseDeg.Min() : 0;
                double maxPhase = node.PhaseDeg.Length > 0 ? node.PhaseDeg.Max() : 0;
                string status = node.MagnitudeDb.Length > 0 ? "OK" : "NO DATA";

                int rowIdx = grid.Rows.Add(
                    node.NodeName,
                    $"{dcGain:F1}",
                    $"{maxGain:F1}",
                    $"{minPhase:F1}",
                    $"{maxPhase:F1}",
                    status
                );
                StyleGridRow(grid, rowIdx, status);
            }
        }
        else
        {
            foreach (var node in gcr.TransientNodes)
            {
                int rowIdx = grid.Rows.Add(
                    node.NodeName,
                    $"{node.Vpp:F4}",
                    $"{node.Vdc:F4}",
                    $"{node.Vrms:F4}",
                    $"{node.Vmin:F4}",
                    $"{node.Vmax:F4}",
                    node.FreqHz > 0 ? $"{node.FreqHz:F1}" : "--",
                    node.Status
                );
                StyleGridRow(grid, rowIdx, node.Status);
            }
        }
    }

    public void StyleGridRow(DataGridView grid, int rowIdx, string status)
    {
        var row = grid.Rows[rowIdx];
        row.DefaultCellStyle.BackColor = status switch
        {
            "OK" => System.Drawing.Color.FromArgb(210, 240, 220),
            "FLAT" => System.Drawing.Color.FromArgb(255, 245, 200),
            "NO DATA" => System.Drawing.Color.FromArgb(255, 215, 215),
            _ => SystemColors.Window,
        };

        row.Cells["Status"].Style.Font = new System.Drawing.Font("Segoe UI", 9f, System.Drawing.FontStyle.Bold);
        row.Cells["Status"].Style.ForeColor = status switch
        {
            "OK" => System.Drawing.Color.FromArgb(0, 120, 0),
            "FLAT" => System.Drawing.Color.FromArgb(180, 120, 0),
            "NO DATA" => System.Drawing.Color.FromArgb(200, 0, 0),
            _ => SystemColors.ControlText,
        };

        // Colour-code node name
        int ci = rowIdx % NodeColors.Length;
        var cc = NodeColors[ci];
        row.Cells["Node"].Style.BackColor = System.Drawing.Color.FromArgb(cc.R, cc.G, cc.B);
        row.Cells["Node"].Style.ForeColor = System.Drawing.Color.White;
        row.Cells["Node"].Style.Font = new System.Drawing.Font("Consolas", 9f, System.Drawing.FontStyle.Bold);
    }

    // ---- Parser ----

    public object ParseResults(string filePath, int sweepIndex)
    {
        _lastResult = GenericResultParser.Parse(SimWorkDir, _selectedProbes);
        return _lastResult;
    }

    // ---- Plot ----

    public void SetupPlot(Plot plot)
    {
        MainForm.StylePlot(plot);
        plot.Title("General Circuit Simulation");
        plot.XLabel("Time (s)");
        plot.YLabel("Voltage (V)");
        plot.Legend.IsVisible = true;
        plot.Legend.Alignment = ScottPlot.Alignment.UpperRight;
    }

    public void PlotSingle(Plot plot, object result)
    {
        if (result is not GenericCircuitResult gcr) return;

        if (CurrentView == ViewMode.Bode && gcr.AcNodes.Count > 0)
            PlotBode(plot, gcr);
        else
            PlotTransient(plot, gcr);
    }

    public void PlotAll(Plot plot, List<object> results)
    {
        // For generic circuit, PlotAll is same as PlotSingle with the last result
        if (results.Count > 0 && results[^1] is GenericCircuitResult gcr)
            PlotSingle(plot, gcr);
    }

    // Light background tints for stacked lanes (alternating)
    private static readonly ScottPlot.Color[] LaneBgColors = new ScottPlot.Color[]
    {
        ScottPlot.Color.FromHex("#EBF2FA"),  // light blue
        ScottPlot.Color.FromHex("#FFF8EB"),  // light amber
        ScottPlot.Color.FromHex("#EBFAEF"),  // light green
        ScottPlot.Color.FromHex("#FAEBEB"),  // light red
        ScottPlot.Color.FromHex("#F3EBFA"),  // light purple
        ScottPlot.Color.FromHex("#FAFAEB"),  // light yellow
    };

    private void PlotTransient(Plot plot, GenericCircuitResult gcr)
    {
        plot.Clear();
        MainForm.StylePlot(plot);
        plot.Legend.IsVisible = true;
        plot.Legend.Alignment = ScottPlot.Alignment.UpperRight;

        if (gcr.TransientNodes.Count == 0)
        {
            plot.Title("No Transient Data Available");
            plot.Add.Annotation("Run simulation to see waveforms");
            return;
        }

        // Filter to nodes with enough data
        var validNodes = gcr.TransientNodes.Where(n => n.Time.Length >= 2).ToList();
        if (validNodes.Count == 0)
        {
            plot.Title("No Valid Waveform Data");
            plot.Add.Annotation("All nodes have < 2 data points");
            return;
        }

        // Use stacked lanes when 2+ signals, overlaid for single
        if (validNodes.Count >= 2)
            PlotTransientStacked(plot, validNodes, gcr);
        else
            PlotTransientSingle(plot, validNodes[0], gcr);
    }

    /// <summary>Single waveform - full plot area, thick line, measurements shown.</summary>
    private void PlotTransientSingle(Plot plot, GenericNodeResult node, GenericCircuitResult gcr)
    {
        var scatter = plot.Add.Scatter(node.Time, node.Voltage);
        scatter.LineWidth = 3f;
        scatter.MarkerSize = 0;
        scatter.Color = NodeColors[0];
        scatter.LegendText = $"{node.NodeName}  Vpp={node.Vpp:F3}  Vdc={node.Vdc:F3}  Vrms={node.Vrms:F3}";

        // Add zero reference line
        var zline = plot.Add.HorizontalLine(0);
        zline.LineWidth = 1;
        zline.LinePattern = ScottPlot.LinePattern.Dotted;
        zline.Color = new ScottPlot.Color(160, 160, 160);
        zline.LegendText = "";

        string title = string.IsNullOrEmpty(_circuitName)
            ? $"Transient - {node.NodeName}"
            : $"{_circuitName} - {node.NodeName}";
        if (node.FreqHz > 0) title += $" | f={FormatFreq(node.FreqHz)}";

        plot.Title(title);
        plot.XLabel("Time (s)");
        plot.YLabel("Voltage (V)");
        plot.Axes.AutoScale();
        plot.Axes.Margins(bottom: 0.05, top: 0.10);
    }

    /// <summary>Stacked oscilloscope-style lanes, one per node.</summary>
    private void PlotTransientStacked(Plot plot, List<GenericNodeResult> nodes, GenericCircuitResult gcr)
    {
        int N = nodes.Count;
        double laneSpacing = 1.15;  // gap between normalized lanes (1.0 = signal, 0.15 = gap)
        double totalHeight = N * laneSpacing;

        // Get time range for background rectangles
        double tMin = nodes.Min(n => n.Time[0]);
        double tMax = nodes.Max(n => n.Time[^1]);
        double tPad = (tMax - tMin) * 0.02;

        for (int i = 0; i < N; i++)
        {
            var node = nodes[i];
            int ci = i % NodeColors.Length;

            // Calculate normalization: map [vmin, vmax] -> [laneBase, laneBase+1]
            double vmin = node.Voltage.Min();
            double vmax = node.Voltage.Max();
            double vrange = vmax - vmin;
            if (vrange < 1e-12) vrange = 1.0;  // flat signal fallback

            // Lane occupies Y range: [laneBase, laneBase + 1.0]
            // Bottom node is index 0, top node is index N-1
            double laneBase = (N - 1 - i) * laneSpacing;

            // Background band for this lane
            int bgIdx = i % LaneBgColors.Length;
            var rect = plot.Add.Rectangle(tMin - tPad, tMax + tPad, laneBase - 0.02, laneBase + 1.02);
            rect.FillColor = LaneBgColors[bgIdx];
            rect.LineWidth = 0;
            rect.LegendText = "";

            // Separator line between lanes
            if (i < N - 1)
            {
                var sep = plot.Add.HorizontalLine(laneBase + 1.02 + 0.05);
                sep.LineWidth = 1;
                sep.LinePattern = ScottPlot.LinePattern.Solid;
                sep.Color = ScottPlot.Color.FromHex("#B0BED0");
                sep.LegendText = "";
            }

            // Normalize voltage data into this lane
            double[] yNorm = new double[node.Voltage.Length];
            for (int j = 0; j < node.Voltage.Length; j++)
                yNorm[j] = (node.Voltage[j] - vmin) / vrange + laneBase;

            // Plot the waveform
            var scatter = plot.Add.Scatter(node.Time, yNorm);
            scatter.LineWidth = 2.5f;
            scatter.MarkerSize = 0;
            scatter.Color = NodeColors[ci];
            scatter.LegendText = $"{node.NodeName}  [{vmin:F2}V .. {vmax:F2}V]  Vpp={node.Vpp:F3}";

            // Mid-line for this lane (center reference)
            var midLine = plot.Add.HorizontalLine(laneBase + 0.5);
            midLine.LineWidth = 0.5f;
            midLine.LinePattern = ScottPlot.LinePattern.Dotted;
            midLine.Color = new ScottPlot.Color(180, 180, 180);
            midLine.LegendText = "";

            // Node label at left edge
            var label = plot.Add.Text(
                $" {node.NodeName}",
                tMin - tPad * 0.5,
                laneBase + 0.5);
            label.LabelFontSize = 12;
            label.LabelBold = true;
            label.LabelFontColor = NodeColors[ci];
            label.LabelAlignment = ScottPlot.Alignment.MiddleLeft;

            // Scale annotation at right edge (min/max voltage)
            var scaleLabel = plot.Add.Text(
                $"{vmax:F2}V\n{vmin:F2}V",
                tMax + tPad * 0.3,
                laneBase + 0.5);
            scaleLabel.LabelFontSize = 9;
            scaleLabel.LabelFontColor = new ScottPlot.Color(100, 100, 100);
            scaleLabel.LabelAlignment = ScottPlot.Alignment.MiddleLeft;
        }

        string title = string.IsNullOrEmpty(_circuitName)
            ? "Transient Analysis"
            : $"{_circuitName} - Transient";
        if (gcr.Gain > 0)
            title += $" | Gain={gcr.Gain:F1}x ({gcr.GainDb:F1}dB)";

        plot.Title(title);
        plot.XLabel("Time (s)");
        plot.YLabel("");  // Y-axis is normalized, no units
        plot.Axes.Left.TickLabelStyle.IsVisible = false;  // hide Y ticks (normalized)
        plot.Axes.Left.MajorTickStyle.Length = 0;
        plot.Axes.Left.MinorTickStyle.Length = 0;
        plot.Axes.SetLimits(
            left: tMin - tPad * 2, right: tMax + tPad * 3,
            bottom: -0.15, top: totalHeight + 0.1);
    }

    private static string FormatFreq(double hz)
    {
        if (hz >= 1e6) return $"{hz / 1e6:F2} MHz";
        if (hz >= 1e3) return $"{hz / 1e3:F1} kHz";
        return $"{hz:F1} Hz";
    }

    private void PlotBode(Plot plot, GenericCircuitResult gcr)
    {
        plot.Clear();
        MainForm.StylePlot(plot);
        plot.Legend.IsVisible = true;
        plot.Legend.Alignment = ScottPlot.Alignment.UpperRight;

        if (gcr.AcNodes.Count == 0)
        {
            plot.Title("No Bode Data Available");
            plot.Add.Annotation("Run AC analysis to see Bode plot");
            return;
        }

        // Use right Y-axis for phase
        var rightAxis = plot.Axes.Right;
        rightAxis.Label.Text = "Phase (\u00b0)";
        rightAxis.Label.FontSize = 13;
        rightAxis.TickLabelStyle.FontSize = 11;

        for (int i = 0; i < gcr.AcNodes.Count; i++)
        {
            var node = gcr.AcNodes[i];
            if (node.Frequency.Length < 2) continue;

            int ci = i % NodeColors.Length;

            // Magnitude trace (left Y-axis) - thick solid line
            var magScatter = plot.Add.Scatter(node.Frequency, node.MagnitudeDb);
            magScatter.LineWidth = 3f;
            magScatter.MarkerSize = 0;
            magScatter.Color = NodeColors[ci];
            double dcGain = node.MagnitudeDb.Length > 0 ? node.MagnitudeDb[0] : 0;
            magScatter.LegendText = $"|{node.NodeName}| DC={dcGain:F1}dB";

            // Phase trace (right Y-axis) - dashed, offset color
            if (node.PhaseDeg.Length > 0)
            {
                var phaseColor = NodeColors[(ci + 6) % NodeColors.Length];
                var phaseScatter = plot.Add.Scatter(node.Frequency, node.PhaseDeg);
                phaseScatter.LineWidth = 2f;
                phaseScatter.MarkerSize = 0;
                phaseScatter.Color = phaseColor;
                phaseScatter.LinePattern = ScottPlot.LinePattern.Dashed;
                phaseScatter.LegendText = $"\u2220{node.NodeName} (\u00b0)";
                phaseScatter.Axes.YAxis = rightAxis;
            }

            // -3dB reference line per node (at DC gain - 3)
            if (node.MagnitudeDb.Length > 0)
            {
                double bwLine = dcGain - 3.0;
                var bwRef = plot.Add.HorizontalLine(bwLine);
                bwRef.LineWidth = 1;
                bwRef.LinePattern = ScottPlot.LinePattern.DenselyDashed;
                bwRef.Color = NodeColors[ci].WithAlpha(80);
                bwRef.LegendText = "";
            }
        }

        // 0dB reference line
        var hline = plot.Add.HorizontalLine(0);
        hline.LineWidth = 1;
        hline.LinePattern = ScottPlot.LinePattern.Dotted;
        hline.Color = new ScottPlot.Color(150, 150, 150);
        hline.LegendText = "0 dB";

        string title = string.IsNullOrEmpty(_circuitName)
            ? "Bode Plot (AC Analysis)"
            : $"{_circuitName} - Bode Plot";

        plot.Title(title);
        plot.XLabel("Frequency (Hz)");
        plot.Axes.Left.Label.Text = "Magnitude (dB)";

        // Log scale for frequency axis
        plot.Axes.Bottom.Min = gcr.AcNodes.Min(n =>
            n.Frequency.Length > 0 ? n.Frequency.Min() : 1);
        plot.Axes.AutoScale();
        plot.Axes.Margins(bottom: 0.05, top: 0.10);
    }

    // ---- Status bar ----

    public void UpdateStatusBar(ToolStripStatusLabel[] labels, object result)
    {
        if (result is not GenericCircuitResult gcr || labels.Length < 6) return;
        labels[0].Text = string.IsNullOrEmpty(_circuitName) ? "Circuit: --" : _circuitName;
        labels[1].Text = string.IsNullOrEmpty(_circuitType) ? "Type: --" : _circuitType;
        labels[2].Text = $"Nodes: {gcr.TransientNodes.Count}";
        labels[3].Text = string.Join("+", gcr.AnalysesRun);
        labels[4].Text = gcr.Gain > 0 ? $"Gain: {gcr.GainDb:F1}dB" : "Gain: --";
        int ok = gcr.TransientNodes.Count(n => n.Status == "OK");
        labels[5].Text = $"OK: {ok}/{gcr.TransientNodes.Count}";
    }

    public void UpdateStatusBarMulti(ToolStripStatusLabel[] labels, List<object> results)
    {
        if (results.Count > 0)
            UpdateStatusBar(labels, results[^1]);
    }

    public void ClearStatusBar(ToolStripStatusLabel[] labels)
    {
        string[] defaults = { "Circuit: --", "Type: --", "Nodes: --",
                              "Analysis: --", "Gain: --", "Status: --" };
        for (int i = 0; i < Math.Min(labels.Length, defaults.Length); i++)
            labels[i].Text = defaults[i];
    }

    // ---- Report ----

    public void PrintReport(Action<string> output, object result)
    {
        if (result is not GenericCircuitResult gcr) return;

        output("");
        output($"=== GENERIC CIRCUIT REPORT: {gcr.CircuitName} ===");
        output($"  Circuit: {gcr.CircuitPath}");
        output($"  Analyses: {string.Join(", ", gcr.AnalysesRun)}");
        output($"  Probed nodes: {string.Join(", ", gcr.ProbedNodes)}");

        if (gcr.Gain > 0)
            output($"  Gain: {gcr.Gain:F2}x ({gcr.GainDb:F1} dB)");

        if (gcr.TransientNodes.Count > 0)
        {
            output("");
            output("  --- Transient Results ---");
            output($"  {"Node",-12} {"Vpp",10} {"Vdc",10} {"Vrms",10} {"Freq (Hz)",12} {"Status",-6}");
            output($"  {"----",-12} {"---",10} {"---",10} {"----",10} {"---------",12} {"------",-6}");

            foreach (var node in gcr.TransientNodes)
            {
                string freq = node.FreqHz > 0 ? $"{node.FreqHz:F1}" : "--";
                output($"  {node.NodeName,-12} {node.Vpp,10:F4} {node.Vdc,10:F4} {node.Vrms,10:F4} {freq,12} {node.Status,-6}");
            }
        }

        if (gcr.AcNodes.Count > 0)
        {
            output("");
            output("  --- AC/Bode Results ---");
            foreach (var node in gcr.AcNodes)
            {
                double dcGain = node.MagnitudeDb.Length > 0 ? node.MagnitudeDb[0] : 0;
                double peakGain = node.MagnitudeDb.Length > 0 ? node.MagnitudeDb.Max() : 0;
                output($"  {node.NodeName}: DC Gain={dcGain:F1}dB  Peak={peakGain:F1}dB  Points={node.Frequency.Length}");
            }
        }
    }

    // ---- CSV export ----

    public void ExportCsv(string filePath, List<object> results)
    {
        var gcr = results.OfType<GenericCircuitResult>().LastOrDefault();
        if (gcr == null) return;

        using var writer = new StreamWriter(filePath);

        if (CurrentView == ViewMode.Bode && gcr.AcNodes.Count > 0)
        {
            // AC data: Frequency, then magnitude+phase per node
            var headers = new List<string> { "Frequency_Hz" };
            foreach (var n in gcr.AcNodes)
            {
                headers.Add($"{n.NodeName}_dB");
                headers.Add($"{n.NodeName}_deg");
            }
            writer.WriteLine(string.Join(",", headers));

            int maxLen = gcr.AcNodes.Max(n => n.Frequency.Length);
            for (int row = 0; row < maxLen; row++)
            {
                var vals = new List<string>();
                double freq = gcr.AcNodes[0].Frequency.Length > row
                    ? gcr.AcNodes[0].Frequency[row] : 0;
                vals.Add(freq.ToString("G6", CultureInfo.InvariantCulture));

                foreach (var n in gcr.AcNodes)
                {
                    double mag = n.MagnitudeDb.Length > row ? n.MagnitudeDb[row] : 0;
                    double phase = n.PhaseDeg.Length > row ? n.PhaseDeg[row] : 0;
                    vals.Add(mag.ToString("F3", CultureInfo.InvariantCulture));
                    vals.Add(phase.ToString("F3", CultureInfo.InvariantCulture));
                }
                writer.WriteLine(string.Join(",", vals));
            }
        }
        else if (gcr.TransientNodes.Count > 0)
        {
            // Transient data: Time, then voltage per node
            var headers = new List<string> { "Time_s" };
            foreach (var n in gcr.TransientNodes)
                headers.Add(n.NodeName);
            writer.WriteLine(string.Join(",", headers));

            int maxLen = gcr.TransientNodes.Max(n => n.Time.Length);
            for (int row = 0; row < maxLen; row++)
            {
                var vals = new List<string>();
                double time = gcr.TransientNodes[0].Time.Length > row
                    ? gcr.TransientNodes[0].Time[row] : 0;
                vals.Add(time.ToString("G6", CultureInfo.InvariantCulture));

                foreach (var n in gcr.TransientNodes)
                {
                    double v = n.Voltage.Length > row ? n.Voltage[row] : 0;
                    vals.Add(v.ToString("G6", CultureInfo.InvariantCulture));
                }
                writer.WriteLine(string.Join(",", vals));
            }
        }
    }
}
