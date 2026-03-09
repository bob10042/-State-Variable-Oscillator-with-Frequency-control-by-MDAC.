using System.Globalization;
using ScottPlot;
using SimGUI.Models;
using SimGUI.Services;

namespace SimGUI.Projects;

/// <summary>
/// Project configuration for comparing the MDAC oscillator (repo design) against
/// the friend's analog oscillator (AD824/AD636/J113 JFET AGC) at matching frequencies.
/// Runs both simulations at each of the 8 standard DAC code frequency points and
/// presents side-by-side results with distinct color-coded charts.
/// </summary>
public class ComparisonConfig : IProjectConfig
{
    private const double FREQ_CONST = 4096.0 * 2 * 3.14159265 * 10e3 * 470e-12; // 0.1211

    private static readonly int[] SweepDacCodes = { 3, 12, 60, 121, 605, 1211, 2421, 3632 };

    private static readonly string WorkDir = SimulationRunner.RepoRoot;

    // --- Color palette (colorblind-friendly: blue vs orange) ---
    private static readonly ScottPlot.Color IdealColor = new(100, 100, 100);
    private static readonly ScottPlot.Color MdacColor = new(40, 120, 200);
    private static readonly ScottPlot.Color AnalogColor = new(200, 80, 40);

    // ---- IProjectConfig implementation ----

    public string ProjectName => "Comparison";
    public string FormTitle => "SimGUI - Oscillator Comparison: MDAC vs Analog";

    public string[] SweepPointNames => SweepDacCodes
        .Select(d =>
        {
            double hz = d / FREQ_CONST;
            return $"{OscillatorPointData.FormatFreq(hz)} (D={d})";
        }).ToArray();

    public string RunSingleLabel => "Compare Point";
    public string RunAllLabel => "Compare All";
    public int DefaultSweepIndex => 3; // D=121 (~1kHz)
    public int SweepCount => SweepDacCodes.Length;

    public string[] StatusBarLabels => new[]
        { "Points", "MDAC Avg Err", "Analog Avg Err", "MDAC RMS", "Analog RMS", "Winner" };

    // ---- Runner args ----

    public string GetCommandArgs(int sweepIndex)
    {
        int dac = SweepDacCodes[sweepIndex];
        return $"oscillator {dac}";
    }

    /// <summary>Get command args for the analog oscillator at the matching frequency.</summary>
    public string GetAnalogCommandArgs(int sweepIndex)
    {
        double targetHz = SweepDacCodes[sweepIndex] / FREQ_CONST;
        return $"analog_osc {targetHz:F1}";
    }

    public string GetResultsFilePath(int sweepIndex)
    {
        int dac = SweepDacCodes[sweepIndex];
        return Path.Combine(WorkDir, "sim_work", $"oscillator_d{dac}_results.txt");
    }

    /// <summary>Get results file path for the analog oscillator.</summary>
    public string GetAnalogResultsFilePath(int sweepIndex)
    {
        double targetHz = SweepDacCodes[sweepIndex] / FREQ_CONST;
        return Path.Combine(WorkDir, "sim_work", $"analog_osc_{targetHz:F0}Hz_results.txt");
    }

    // ---- Grid ----

    public DataGridViewColumn[] CreateGridColumns()
    {
        return new DataGridViewColumn[]
        {
            new DataGridViewTextBoxColumn { Name = "Target", HeaderText = "Target (Hz)", Width = 85 },
            new DataGridViewTextBoxColumn { Name = "MdacFreq", HeaderText = "MDAC Freq", Width = 80 },
            new DataGridViewTextBoxColumn { Name = "MdacErr", HeaderText = "MDAC Err%", Width = 68 },
            new DataGridViewTextBoxColumn { Name = "MdacRms", HeaderText = "MDAC RMS", Width = 70 },
            new DataGridViewTextBoxColumn { Name = "MdacVpp", HeaderText = "MDAC Vpp", Width = 68 },
            new DataGridViewTextBoxColumn { Name = "MdacStat", HeaderText = "MDAC", Width = 48 },
            new DataGridViewTextBoxColumn { Name = "AnalogFreq", HeaderText = "Analog Freq", Width = 85 },
            new DataGridViewTextBoxColumn { Name = "AnalogErr", HeaderText = "Analog Err%", Width = 72 },
            new DataGridViewTextBoxColumn { Name = "AnalogRms", HeaderText = "Analog RMS", Width = 75 },
            new DataGridViewTextBoxColumn { Name = "AnalogVpp", HeaderText = "Analog Vpp", Width = 72 },
            new DataGridViewTextBoxColumn { Name = "AnalogStat", HeaderText = "Analog", Width = 52 },
            new DataGridViewTextBoxColumn { Name = "Winner", HeaderText = "Better", Width = 55 },
        };
    }

    public void PopulateGrid(DataGridView grid, object result)
    {
        if (result is not ComparisonPointData cp) return;

        int rowIdx = grid.Rows.Add(
            $"{cp.TargetFreqHz:F1}",
            $"{cp.MdacFreqHz:F1}", $"{cp.MdacFreqErrorPercent:F2}",
            $"{cp.MdacBpRms:F3}", $"{cp.MdacBpVpp:F3}", cp.MdacStatus,
            $"{cp.AnalogFreqHz:F1}", $"{cp.AnalogFreqErrorPercent:F2}",
            $"{cp.AnalogBpRms:F3}", $"{cp.AnalogBpVpp:F3}", cp.AnalogStatus,
            cp.Winner
        );
        StyleGridRow(grid, rowIdx, cp.Winner == "MDAC" ? "PASS" : "WARN");
    }

    public void StyleGridRow(DataGridView grid, int rowIdx, string status)
    {
        var row = grid.Rows[rowIdx];

        // Tint MDAC columns blue
        var mdacTint = System.Drawing.Color.FromArgb(225, 238, 255);
        foreach (var colName in new[] { "MdacFreq", "MdacErr", "MdacRms", "MdacVpp", "MdacStat" })
            row.Cells[colName].Style.BackColor = mdacTint;

        // Tint Analog columns warm orange
        var analogTint = System.Drawing.Color.FromArgb(255, 238, 225);
        foreach (var colName in new[] { "AnalogFreq", "AnalogErr", "AnalogRms", "AnalogVpp", "AnalogStat" })
            row.Cells[colName].Style.BackColor = analogTint;

        // Status cell styling
        foreach (var colName in new[] { "MdacStat", "AnalogStat" })
        {
            var cell = row.Cells[colName];
            cell.Style.Font = new System.Drawing.Font("Segoe UI", 9f, System.Drawing.FontStyle.Bold);
            string val = cell.Value?.ToString() ?? "";
            cell.Style.ForeColor = val switch
            {
                "PASS" => System.Drawing.Color.FromArgb(0, 120, 0),
                "WARN" => System.Drawing.Color.FromArgb(180, 120, 0),
                "FAIL" => System.Drawing.Color.FromArgb(200, 0, 0),
                _ => SystemColors.ControlText,
            };
        }

        // Winner cell
        var winnerCell = row.Cells["Winner"];
        winnerCell.Style.Font = new System.Drawing.Font("Segoe UI", 9f, System.Drawing.FontStyle.Bold);
        winnerCell.Style.ForeColor = winnerCell.Value?.ToString() == "MDAC"
            ? System.Drawing.Color.FromArgb(30, 100, 180)
            : System.Drawing.Color.FromArgb(180, 70, 30);
    }

    // ---- Parser ----

    public object ParseResults(string filePath, int sweepIndex)
    {
        int dac = SweepDacCodes[sweepIndex];
        double expectedHz = dac / FREQ_CONST;
        return OscillatorResultParser.Parse(filePath, dac, expectedHz);
    }

    /// <summary>
    /// Build a ComparisonPointData from paired MDAC + Analog results.
    /// </summary>
    public ComparisonPointData BuildComparison(int sweepIndex,
        OscillatorPointData mdac, OscillatorPointData analog)
    {
        double targetHz = SweepDacCodes[sweepIndex] / FREQ_CONST;
        return new ComparisonPointData
        {
            SweepIndex = sweepIndex,
            DacCode = SweepDacCodes[sweepIndex],
            TargetFreqHz = targetHz,
            MdacFreqHz = mdac.MeasuredFreqHz,
            MdacFreqErrorPercent = mdac.FreqErrorPercent,
            MdacBpVpp = mdac.BpVpp,
            MdacBpRms = mdac.BpRms,
            MdacHpVpp = mdac.HpVpp,
            MdacLpVpp = mdac.LpVpp,
            MdacStatus = mdac.Status,
            AnalogFreqHz = analog.MeasuredFreqHz,
            AnalogFreqErrorPercent = analog.FreqErrorPercent,
            AnalogBpVpp = analog.BpVpp,
            AnalogBpRms = analog.BpRms,
            AnalogHpVpp = analog.HpVpp,
            AnalogLpVpp = analog.LpVpp,
            AnalogStatus = analog.Status,
        };
    }

    // ---- Plot ----

    public void SetupPlot(Plot plot)
    {
        MainForm.StylePlot(plot);
        plot.Title("Oscillator Comparison: MDAC (blue) vs Analog (orange)");
        plot.XLabel("Target Frequency (Hz)");
        plot.YLabel("Measured Frequency (Hz)");
        plot.Legend.IsVisible = true;
        plot.Legend.Alignment = ScottPlot.Alignment.UpperLeft;
    }

    public void PlotSingle(Plot plot, object result)
    {
        plot.Clear();
        MainForm.StylePlot(plot);
        if (result is not ComparisonPointData cp) return;

        var bars = new List<ScottPlot.Bar>
        {
            new() { Position = 0, Value = cp.TargetFreqHz,
                     FillColor = IdealColor, Label = "Target" },
            new() { Position = 1, Value = cp.MdacFreqHz,
                     FillColor = MdacColor, Label = "MDAC" },
            new() { Position = 2, Value = cp.AnalogFreqHz,
                     FillColor = AnalogColor, Label = "Analog" },
        };
        plot.Add.Bars(bars.ToArray());
        plot.Title($"Comparison at {OscillatorPointData.FormatFreq(cp.TargetFreqHz)}");
        plot.YLabel("Frequency (Hz)");
        plot.Axes.AutoScale();
    }

    public void PlotAll(Plot plot, List<object> results)
    {
        plot.Clear();
        MainForm.StylePlot(plot);
        var points = results.OfType<ComparisonPointData>()
            .OrderBy(p => p.TargetFreqHz).ToList();
        if (points.Count == 0) return;

        double[] targetFreqs = points.Select(p => p.TargetFreqHz).ToArray();
        double[] mdacFreqs = points.Select(p => p.MdacFreqHz).ToArray();
        double[] analogFreqs = points.Select(p => p.AnalogFreqHz).ToArray();

        // Ideal line (target = measured would be perfect)
        var idealLine = plot.Add.Scatter(targetFreqs, targetFreqs);
        idealLine.LineWidth = 2;
        idealLine.LinePattern = ScottPlot.LinePattern.Dashed;
        idealLine.Color = IdealColor;
        idealLine.MarkerSize = 6;
        idealLine.MarkerShape = ScottPlot.MarkerShape.OpenCircle;
        idealLine.LegendText = "Ideal (perfect)";

        // MDAC line (steel blue, filled circles)
        var mdacLine = plot.Add.Scatter(targetFreqs, mdacFreqs);
        mdacLine.LineWidth = 2.5f;
        mdacLine.Color = MdacColor;
        mdacLine.MarkerSize = 8;
        mdacLine.MarkerShape = ScottPlot.MarkerShape.FilledCircle;
        mdacLine.LegendText = "MDAC Design";

        // Analog line (burnt orange, filled diamonds)
        var analogLine = plot.Add.Scatter(targetFreqs, analogFreqs);
        analogLine.LineWidth = 2.5f;
        analogLine.Color = AnalogColor;
        analogLine.MarkerSize = 8;
        analogLine.MarkerShape = ScottPlot.MarkerShape.FilledDiamond;
        analogLine.LegendText = "Analog Design";

        // Error annotations at each point
        for (int i = 0; i < points.Count; i++)
        {
            var cp = points[i];
            double yPos = Math.Max(cp.MdacFreqHz, cp.AnalogFreqHz);
            var txt = plot.Add.Text(
                $"M:{cp.MdacFreqErrorPercent:F1}%  A:{cp.AnalogFreqErrorPercent:F1}%",
                cp.TargetFreqHz, yPos);
            txt.LabelFontSize = 7;
            txt.LabelFontColor = new ScottPlot.Color(80, 80, 80);
            txt.LabelAlignment = ScottPlot.Alignment.LowerLeft;
        }

        plot.Title("Frequency Accuracy: MDAC (blue) vs Analog (orange)");
        plot.XLabel("Target Frequency (Hz)");
        plot.YLabel("Measured Frequency (Hz)");
        plot.Axes.AutoScale();
        plot.Axes.Margins(top: 0.15, right: 0.05);
    }

    /// <summary>
    /// Alternate plot: Amplitude comparison across frequency.
    /// Shows BP RMS for both designs against the 1.03V target.
    /// </summary>
    public void PlotAmplitude(Plot plot, List<object> results)
    {
        plot.Clear();
        MainForm.StylePlot(plot);
        var points = results.OfType<ComparisonPointData>()
            .OrderBy(p => p.TargetFreqHz).ToList();
        if (points.Count == 0) return;

        double[] targetFreqs = points.Select(p => p.TargetFreqHz).ToArray();
        double[] mdacRms = points.Select(p => p.MdacBpRms).ToArray();
        double[] analogRms = points.Select(p => p.AnalogBpRms).ToArray();

        // Target RMS line (1.03V)
        var targetLine = plot.Add.HorizontalLine(1.03);
        targetLine.LineWidth = 1.5f;
        targetLine.LinePattern = ScottPlot.LinePattern.Dashed;
        targetLine.Color = IdealColor;
        targetLine.LegendText = "Target RMS (1.03V)";

        // MDAC RMS (steel blue)
        var mdacRmsLine = plot.Add.Scatter(targetFreqs, mdacRms);
        mdacRmsLine.LineWidth = 2.5f;
        mdacRmsLine.Color = MdacColor;
        mdacRmsLine.MarkerSize = 8;
        mdacRmsLine.MarkerShape = ScottPlot.MarkerShape.FilledCircle;
        mdacRmsLine.LegendText = "MDAC BP RMS";

        // Analog RMS (burnt orange)
        var analogRmsLine = plot.Add.Scatter(targetFreqs, analogRms);
        analogRmsLine.LineWidth = 2.5f;
        analogRmsLine.Color = AnalogColor;
        analogRmsLine.MarkerSize = 8;
        analogRmsLine.MarkerShape = ScottPlot.MarkerShape.FilledDiamond;
        analogRmsLine.LegendText = "Analog BP RMS";

        // Annotations showing Vpp for clipping detection
        for (int i = 0; i < points.Count; i++)
        {
            var cp = points[i];
            if (cp.AnalogBpVpp > 20)
            {
                var ann = plot.Add.Text(
                    $"CLIP {cp.AnalogBpVpp:F0}Vpp",
                    cp.TargetFreqHz, cp.AnalogBpRms);
                ann.LabelFontSize = 7;
                ann.LabelFontColor = new ScottPlot.Color(200, 0, 0);
                ann.LabelAlignment = ScottPlot.Alignment.LowerCenter;
            }
        }

        plot.Title("Amplitude Stability: MDAC (blue) vs Analog (orange)");
        plot.XLabel("Target Frequency (Hz)");
        plot.YLabel("BP RMS Voltage (V)");
        plot.Axes.AutoScale();
        plot.Axes.Margins(top: 0.15);
    }

    // ---- Status bar ----

    public void UpdateStatusBar(ToolStripStatusLabel[] labels, object result)
    {
        if (result is not ComparisonPointData cp || labels.Length < 6) return;
        labels[0].Text = $"f={OscillatorPointData.FormatFreq(cp.TargetFreqHz)}";
        labels[1].Text = $"MDAC Err={cp.MdacFreqErrorPercent:F1}%";
        labels[2].Text = $"Analog Err={cp.AnalogFreqErrorPercent:F1}%";
        labels[3].Text = $"MDAC RMS={cp.MdacBpRms:F3}V";
        labels[4].Text = $"Analog RMS={cp.AnalogBpRms:F3}V";
        labels[5].Text = cp.Winner;
    }

    public void UpdateStatusBarMulti(ToolStripStatusLabel[] labels, List<object> results)
    {
        var pts = results.OfType<ComparisonPointData>().ToList();
        if (pts.Count == 0 || labels.Length < 6) return;
        double mdacAvg = pts.Average(p => p.MdacFreqErrorPercent);
        double analogAvg = pts.Average(p => p.AnalogFreqErrorPercent);
        int mdacWins = pts.Count(p => p.Winner == "MDAC");
        labels[0].Text = $"{pts.Count} points";
        labels[1].Text = $"MDAC Avg: {mdacAvg:F1}%";
        labels[2].Text = $"Analog Avg: {analogAvg:F1}%";
        labels[3].Text = $"MDAC RMS: {pts.Average(p => p.MdacBpRms):F3}V";
        labels[4].Text = $"Analog RMS: {pts.Average(p => p.AnalogBpRms):F3}V";
        labels[5].Text = $"MDAC wins {mdacWins}/{pts.Count}";
    }

    public void ClearStatusBar(ToolStripStatusLabel[] labels)
    {
        string[] defaults = { "Points: --", "MDAC Err: --", "Analog Err: --",
                              "MDAC RMS: --", "Analog RMS: --", "Winner: --" };
        for (int i = 0; i < Math.Min(labels.Length, defaults.Length); i++)
            labels[i].Text = defaults[i];
    }

    // ---- Report ----

    public void PrintReport(Action<string> output, object result)
    {
        if (result is not ComparisonPointData cp) return;
        output($"  f={cp.TargetFreqHz,8:F1}Hz  MDAC:{cp.MdacFreqHz,8:F1}Hz({cp.MdacFreqErrorPercent:F1}%) RMS={cp.MdacBpRms:F3}V  Analog:{cp.AnalogFreqHz,8:F1}Hz({cp.AnalogFreqErrorPercent:F1}%) RMS={cp.AnalogBpRms:F3}V  [{cp.Winner}]");
    }

    /// <summary>Print full comparison sweep summary.</summary>
    public void PrintSweepSummary(Action<string> output, List<object> results)
    {
        var pts = results.OfType<ComparisonPointData>().OrderBy(p => p.TargetFreqHz).ToList();
        if (pts.Count == 0) return;

        output("\n========== COMPARISON SUMMARY ==========");
        output($"  {"Target Hz",-12} {"MDAC Hz",-10} {"Err%",-7} {"RMS V",-8} {"Analog Hz",-10} {"Err%",-7} {"RMS V",-8} {"Winner",-7}");
        output($"  {new string('-', 75)}");

        foreach (var cp in pts)
        {
            output($"  {cp.TargetFreqHz,10:F1}  {cp.MdacFreqHz,9:F1} {cp.MdacFreqErrorPercent,5:F1}%  {cp.MdacBpRms,6:F3}  {cp.AnalogFreqHz,9:F1} {cp.AnalogFreqErrorPercent,5:F1}%  {cp.AnalogBpRms,6:F3}  {cp.Winner}");
        }

        double mdacAvgErr = pts.Average(p => p.MdacFreqErrorPercent);
        double analogAvgErr = pts.Average(p => p.AnalogFreqErrorPercent);
        int mdacWins = pts.Count(p => p.Winner == "MDAC");

        output($"\n  MDAC:   Avg Err = {mdacAvgErr:F1}%  |  Avg RMS = {pts.Average(p => p.MdacBpRms):F3}V  |  Vpp range: {pts.Min(p => p.MdacBpVpp):F2}-{pts.Max(p => p.MdacBpVpp):F2}V");
        output($"  Analog: Avg Err = {analogAvgErr:F1}%  |  Avg RMS = {pts.Average(p => p.AnalogBpRms):F3}V  |  Vpp range: {pts.Min(p => p.AnalogBpVpp):F2}-{pts.Max(p => p.AnalogBpVpp):F2}V");
        output($"  MDAC wins {mdacWins}/{pts.Count} frequency points");

        if (pts.Any(p => p.AnalogBpVpp > 20))
            output("  WARNING: Analog design clipping detected (Vpp > 20V) - AGC not functioning correctly");
    }

    // ---- CSV export ----

    public void ExportCsv(string filePath, List<object> results)
    {
        var pts = results.OfType<ComparisonPointData>().OrderBy(p => p.TargetFreqHz).ToList();
        using var w = new StreamWriter(filePath);
        w.WriteLine("Timestamp,TargetHz,DacCode,MdacFreqHz,MdacErrPct,MdacBpVpp,MdacBpRms,MdacHpVpp,MdacLpVpp,MdacStatus,AnalogFreqHz,AnalogErrPct,AnalogBpVpp,AnalogBpRms,AnalogHpVpp,AnalogLpVpp,AnalogStatus,Winner");
        foreach (var cp in pts)
        {
            w.WriteLine(string.Format(CultureInfo.InvariantCulture,
                "{0},{1:F1},{2},{3:F1},{4:F2},{5:F4},{6:F4},{7:F4},{8:F4},{9},{10:F1},{11:F2},{12:F4},{13:F4},{14:F4},{15:F4},{16},{17}",
                cp.Timestamp.ToString("yyyy-MM-dd HH:mm:ss"),
                cp.TargetFreqHz, cp.DacCode,
                cp.MdacFreqHz, cp.MdacFreqErrorPercent, cp.MdacBpVpp, cp.MdacBpRms, cp.MdacHpVpp, cp.MdacLpVpp, cp.MdacStatus,
                cp.AnalogFreqHz, cp.AnalogFreqErrorPercent, cp.AnalogBpVpp, cp.AnalogBpRms, cp.AnalogHpVpp, cp.AnalogLpVpp, cp.AnalogStatus,
                cp.Winner));
        }
    }
}
