using System.Globalization;
using ScottPlot;
using SimGUI.Models;
using SimGUI.Services;

namespace SimGUI.Projects;

/// <summary>
/// Project configuration for the 16-channel electrometer / TIA simulation.
/// Wraps existing ResultParser, ChannelData, and SimulationResult logic.
/// 9 ranges (Rf = 100 to 10G), 16 channels per range.
/// </summary>
public class ElectrometerConfig : IProjectConfig
{
    private static readonly string WorkDir = SimGUI.Services.SimulationRunner.RepoRoot;

    // 16 distinct colours for channel traces
    private static readonly ScottPlot.Color[] ChColors = new ScottPlot.Color[]
    {
        new(0x1f, 0x77, 0xb4), new(0xff, 0x7f, 0x0e), new(0x2c, 0xa0, 0x2c), new(0xd6, 0x27, 0x28),
        new(0x94, 0x67, 0xbd), new(0x8c, 0x56, 0x4b), new(0xe3, 0x77, 0xc2), new(0x7f, 0x7f, 0x7f),
        new(0xbc, 0xbd, 0x22), new(0x17, 0xbe, 0xcf), new(0xaa, 0x40, 0xfc), new(0x00, 0x80, 0x80),
        new(0xff, 0x69, 0xb4), new(0xa5, 0x2a, 0x2a), new(0x00, 0xbf, 0xff), new(0xff, 0xd7, 0x00),
    };

    public string ProjectName => "Electrometer";
    public string FormTitle => "SimGUI - 16-Channel Electrometer Simulation (All Ranges)";

    public string[] SweepPointNames => new[]
    {
        "Range 0: Rf=100 (mA)",
        "Range 1: Rf=1k (mA)",
        "Range 2: Rf=10k (uA)",
        "Range 3: Rf=100k (uA)",
        "Range 4: Rf=1M (uA)",
        "Range 5: Rf=10M (nA)",
        "Range 6: Rf=100M (nA)",
        "Range 7: Rf=1G (sub-nA)",
        "Range 8: Rf=10G (fA)",
    };

    public string RunSingleLabel => "Run Range";
    public string RunAllLabel => "Run All Ranges";
    public int DefaultSweepIndex => 7; // Range 7 (1G)
    public int SweepCount => 9;

    public string[] StatusBarLabels => new[]
        { "Range", "Channels", "Sim Time", "Avg Err", "Max Err", "P/W/F" };

    // ---- Runner ----

    public string GetCommandArgs(int sweepIndex)
    {
        return $"channel_switch LMC6001 {sweepIndex}";
    }

    public string GetResultsFilePath(int sweepIndex)
    {
        return Path.Combine(WorkDir, "sim_work", $"channel_switching_range{sweepIndex}_results.txt");
    }

    // ---- Grid ----

    public DataGridViewColumn[] CreateGridColumns()
    {
        return new DataGridViewColumn[]
        {
            new DataGridViewTextBoxColumn { Name = "Range", HeaderText = "Rf", Width = 40 },
            new DataGridViewTextBoxColumn { Name = "Channel", HeaderText = "CH", Width = 35 },
            new DataGridViewTextBoxColumn { Name = "Injected", HeaderText = "Injected" },
            new DataGridViewTextBoxColumn { Name = "Measured", HeaderText = "Measured" },
            new DataGridViewTextBoxColumn { Name = "Delta", HeaderText = "Delta" },
            new DataGridViewTextBoxColumn { Name = "ErrorPct", HeaderText = "Error (%)" },
            new DataGridViewTextBoxColumn { Name = "VtiaMv", HeaderText = "V_TIA (mV)" },
            new DataGridViewTextBoxColumn { Name = "VexpMv", HeaderText = "V_Expected (mV)" },
            new DataGridViewTextBoxColumn { Name = "VchMv", HeaderText = "V_Input (mV)" },
            new DataGridViewTextBoxColumn { Name = "AdcCounts", HeaderText = "ADC Counts" },
            new DataGridViewTextBoxColumn { Name = "Status", HeaderText = "Result", Width = 50 },
        };
    }

    public void PopulateGrid(DataGridView grid, object result)
    {
        if (result is not SimulationResult simResult) return;

        foreach (var ch in simResult.Channels)
        {
            int rowIdx = grid.Rows.Add(
                simResult.RfDisplay,
                ch.Channel,
                ch.InjectedDisplay,
                ch.MeasuredDisplay,
                ch.DeltaDisplay,
                ch.ErrorPercent,
                ch.VtiaMv,
                ch.ExpectedVtiaMv,
                ch.VchInputMv,
                ch.AdcCounts,
                ch.Status
            );

            StyleGridRow(grid, rowIdx, ch.Status);

            // Channel colour coding
            int ci = (ch.Channel - 1) % ChColors.Length;
            var cc = ChColors[ci];
            grid.Rows[rowIdx].Cells["Channel"].Style.BackColor = System.Drawing.Color.FromArgb(cc.R, cc.G, cc.B);
            grid.Rows[rowIdx].Cells["Channel"].Style.ForeColor = System.Drawing.Color.White;
            grid.Rows[rowIdx].Cells["Channel"].Style.Font = new System.Drawing.Font("Consolas", 9f, System.Drawing.FontStyle.Bold);
        }
    }

    public void StyleGridRow(DataGridView grid, int rowIdx, string status)
    {
        var row = grid.Rows[rowIdx];

        row.DefaultCellStyle.BackColor = status switch
        {
            "PASS" => System.Drawing.Color.FromArgb(210, 240, 220),
            "WARN" => System.Drawing.Color.FromArgb(255, 245, 200),
            "FAIL" => System.Drawing.Color.FromArgb(255, 215, 215),
            _ => SystemColors.Window,
        };

        row.Cells["Status"].Style.Font = new System.Drawing.Font("Segoe UI", 9f, System.Drawing.FontStyle.Bold);
        row.Cells["Status"].Style.ForeColor = status switch
        {
            "PASS" => System.Drawing.Color.FromArgb(0, 120, 0),
            "WARN" => System.Drawing.Color.FromArgb(180, 120, 0),
            "FAIL" => System.Drawing.Color.FromArgb(200, 0, 0),
            _ => SystemColors.ControlText,
        };
    }

    // ---- Parser ----

    public object ParseResults(string filePath, int sweepIndex)
    {
        return ResultParser.Parse(filePath, sweepIndex);
    }

    // ---- Plot ----

    public void SetupPlot(Plot plot)
    {
        MainForm.StylePlot(plot);
        plot.Title("TIA Output - 16 Channel Scan");
        plot.XLabel("Time (s)");
        plot.YLabel("Current");
        plot.Legend.IsVisible = true;
        plot.Legend.Alignment = ScottPlot.Alignment.UpperRight;
    }

    public void PlotSingle(Plot plot, object result)
    {
        plot.Clear();
        MainForm.StylePlot(plot);
        if (result is not SimulationResult simResult) return;
        if (simResult.TimePoints.Length == 0 || simResult.Channels.Count == 0) return;

        string unit = simResult.CurrentUnit;

        foreach (var ch in simResult.Channels)
        {
            if (ch.SegmentTimes.Length < 2) continue;
            int ci = (ch.Channel - 1) % ChColors.Length;
            var scatter = plot.Add.Scatter(ch.SegmentTimes, ch.SegmentCurrentsScaled);
            scatter.LineWidth = 2f;
            scatter.MarkerSize = 0;
            scatter.Color = ChColors[ci];
            scatter.LegendText = $"CH{ch.Channel} ({ch.InjectedDisplay})";
        }

        // Shaded windows + expected markers
        foreach (var ch in simResult.Channels)
        {
            int ci = (ch.Channel - 1) % ChColors.Length;
            double yExpected = ch.InjectedScaled;

            var vspan = plot.Add.VerticalSpan(ch.WindowStartS, ch.WindowEndS);
            vspan.FillColor = ChColors[ci].WithAlpha(25);

            var marker = plot.Add.Scatter(
                new[] { ch.SampleTimeS },
                new[] { yExpected });
            marker.MarkerSize = 8;
            marker.MarkerShape = ScottPlot.MarkerShape.OpenTriangleUp;
            marker.Color = ChColors[ci];
            marker.LineWidth = 0;
            marker.LegendText = "";
        }

        // Channel boundary lines
        for (int ch = 1; ch <= 16; ch++)
        {
            double boundary = ch * 0.200;
            if (boundary < simResult.SimulationTimeSeconds)
            {
                var vline = plot.Add.VerticalLine(boundary);
                vline.LineWidth = 1;
                vline.LinePattern = ScottPlot.LinePattern.Dotted;
                vline.Color = new ScottPlot.Color(120, 140, 170);
            }
        }

        // Channel labels
        double yMax = simResult.Channels.Max(c =>
            c.SegmentCurrentsScaled.Length > 0 ? c.SegmentCurrentsScaled.Max() : 0);
        for (int ch = 1; ch <= 16; ch++)
        {
            double mid = (ch - 0.5) * 0.200;
            if (mid < simResult.SimulationTimeSeconds)
            {
                var txt = plot.Add.Text($"CH{ch}", mid, yMax * 1.02);
                txt.LabelFontSize = 9;
                txt.LabelFontColor = ChColors[(ch - 1) % ChColors.Length];
                txt.LabelAlignment = ScottPlot.Alignment.UpperCenter;
                txt.LabelBold = true;
            }
        }

        plot.Title($"TIA Current per Channel - {simResult.RangeName}");
        plot.YLabel($"Current ({unit})");
        plot.XLabel("Time (s)");
        plot.Axes.AutoScale();
        plot.Axes.Margins(bottom: 0.05, top: 0.12);
    }

    public void PlotAll(Plot plot, List<object> results)
    {
        plot.Clear();
        MainForm.StylePlot(plot);
        var simResults = results.OfType<SimulationResult>().ToList();
        if (simResults.Count == 0) return;

        double timeOffset = 0;

        foreach (var simResult in simResults)
        {
            foreach (var ch in simResult.Channels)
            {
                if (ch.SegmentTimes.Length < 2) continue;
                int ci = (ch.Channel - 1) % ChColors.Length;
                double[] offsetTimes = ch.SegmentTimes.Select(t => t + timeOffset).ToArray();
                var scatter = plot.Add.Scatter(offsetTimes, ch.SegmentCurrentsScaled);
                scatter.LineWidth = 1.5f;
                scatter.MarkerSize = 0;
                scatter.Color = ChColors[ci];
                scatter.LegendText = simResult == simResults[0] ? $"CH{ch.Channel}" : "";
            }

            // Range label
            double rangeMid = timeOffset + simResult.SimulationTimeSeconds / 2;
            double yRange = simResult.Channels.Max(c =>
                c.SegmentCurrentsScaled.Length > 0 ? c.SegmentCurrentsScaled.Max() : 0);
            var label = plot.Add.Text($"Rf={simResult.RfDisplay} ({simResult.CurrentUnit})", rangeMid, yRange * 1.05);
            label.LabelFontSize = 11;
            label.LabelFontColor = new ScottPlot.Color(25, 55, 95);
            label.LabelAlignment = ScottPlot.Alignment.UpperCenter;
            label.LabelBold = true;

            if (timeOffset > 0)
            {
                var sep = plot.Add.VerticalLine(timeOffset);
                sep.LineWidth = 2;
                sep.Color = new ScottPlot.Color(180, 60, 60);
                sep.LinePattern = ScottPlot.LinePattern.Dashed;
            }

            timeOffset += simResult.SimulationTimeSeconds + 0.2;
        }

        plot.Title("All Ranges - 16-Channel Electrometer Verification");
        plot.XLabel("Time (s) - ranges concatenated");
        plot.YLabel("Current (auto-scaled per range)");
        plot.Axes.AutoScale();
        plot.Axes.Margins(bottom: 0.05, top: 0.15);
    }

    // ---- Status bar ----

    public void UpdateStatusBar(ToolStripStatusLabel[] labels, object result)
    {
        if (result is not SimulationResult r || labels.Length < 6) return;
        labels[0].Text = $"Rf={r.RfDisplay}";
        labels[1].Text = $"Channels: {r.Channels.Count}/16";
        labels[2].Text = $"Sim: {r.SimulationTimeSeconds:F2}s";
        labels[3].Text = $"Avg Err: {r.AverageErrorPercent:F1}%";
        labels[4].Text = $"Max Err: {r.MaxErrorPercent:F1}%";
        labels[5].Text = $"P:{r.PassCount} W:{r.WarnCount} F:{r.FailCount}";
    }

    public void UpdateStatusBarMulti(ToolStripStatusLabel[] labels, List<object> results)
    {
        var simResults = results.OfType<SimulationResult>().ToList();
        if (simResults.Count == 0 || labels.Length < 6) return;

        int totalCh = simResults.Sum(r => r.Channels.Count);
        int totalP = simResults.Sum(r => r.PassCount);
        int totalW = simResults.Sum(r => r.WarnCount);
        int totalF = simResults.Sum(r => r.FailCount);
        double avgErr = simResults.Average(r => r.AverageErrorPercent);
        double maxErr = simResults.Max(r => r.MaxErrorPercent);

        labels[0].Text = "All Ranges";
        labels[1].Text = $"Channels: {totalCh}/{simResults.Count * 16}";
        labels[2].Text = $"Ranges: {simResults.Count}/9";
        labels[3].Text = $"Avg Err: {avgErr:F1}%";
        labels[4].Text = $"Max Err: {maxErr:F1}%";
        labels[5].Text = $"P:{totalP} W:{totalW} F:{totalF}";
    }

    public void ClearStatusBar(ToolStripStatusLabel[] labels)
    {
        string[] defaults = { "Range: --", "Channels: 0/16", "Sim: --",
                              "Avg Err: --", "Max Err: --", "P/W/F: --" };
        for (int i = 0; i < Math.Min(labels.Length, defaults.Length); i++)
            labels[i].Text = defaults[i];
    }

    // ---- Report ----

    public void PrintReport(Action<string> output, object result)
    {
        if (result is not SimulationResult r) return;

        output("");
        output($"=== VERIFICATION REPORT: {r.RangeName} ===");
        output($"  Rf = {r.RfDisplay} | Period = {r.ChannelPeriodS * 1e3:F0}ms | ADC = {r.AdcBits}-bit / {r.AdcRefV}V ref");
        output($"  {"CH",-4} {"Injected",-16} {"Measured",-16} {"Delta",-16} {"Error",-8} {"V_TIA(mV)",-12} {"ADC",-10} {"Result",-6}");
        output($"  {"--",-4} {"--------",-16} {"--------",-16} {"-----",-16} {"-----",-8} {"---------",-12} {"---",-10} {"------",-6}");

        foreach (var ch in r.Channels)
        {
            string marker = ch.Status == "PASS" ? " " : (ch.Status == "WARN" ? "*" : "X");
            output($" {marker}CH{ch.Channel,-2} {ch.InjectedDisplay,-16} {ch.MeasuredDisplay,-16} {ch.DeltaDisplay,-16} {ch.ErrorPercent,5:F1}%  {ch.VtiaMv,9:F3}mV  {ch.AdcCounts,8:N0}  {ch.Status}");
        }

        output($"\n  Avg Error: {r.AverageErrorPercent:F1}% | Max Error: {r.MaxErrorPercent:F1}%");
        output($"  PASS: {r.PassCount} | WARN: {r.WarnCount} | FAIL: {r.FailCount}");

        if (r.FailCount == 0)
            output("  >> ALL CHANNELS WITHIN TOLERANCE <<");
        else
            output($"  >> {r.FailCount} CHANNEL(S) EXCEED 20% ERROR <<");
    }

    // ---- CSV export ----

    public void ExportCsv(string filePath, List<object> results)
    {
        var simResults = results.OfType<SimulationResult>().ToList();
        if (simResults.Count == 0) return;

        if (simResults.Count == 1)
            CsvExporter.ExportChannels(filePath, simResults[0]);
        else
            CsvExporter.ExportMultiRange(filePath, simResults);
    }
}
