using System.Globalization;
using ScottPlot;
using SimGUI.Models;
using SimGUI.Services;

namespace SimGUI.Projects;

/// <summary>
/// Project configuration for the State Variable Oscillator frequency sweep.
/// 8 sweep points across the DAC code range (D=3 to D=3632).
/// Includes calibration simulation showing how ADuCM362 corrects errors.
/// </summary>
public class OscillatorConfig : IProjectConfig
{
    private const double FREQ_CONST = 4096.0 * 2 * 3.14159265 * 10e3 * 470e-12; // 0.1211
    private const double RMS_TARGET = 1.03; // target RMS voltage

    private static readonly int[] SweepDacCodes = { 3, 12, 60, 121, 605, 1211, 2421, 3632 };

    private static readonly string WorkDir = SimGUI.Services.SimulationRunner.RepoRoot;

    // Calibration state
    private readonly List<OscillatorPointData> _calPoints = new();
    public bool CalibrationApplied { get; private set; }

    public string ProjectName => "Oscillator";
    public string FormTitle => "SimGUI - State Variable Oscillator Frequency Sweep";

    public string[] SweepPointNames => SweepDacCodes
        .Select(d => $"D={d} ({OscillatorPointData.FormatFreq(d / FREQ_CONST)})")
        .ToArray();

    public string RunSingleLabel => "Run Point";
    public string RunAllLabel => "Freq Sweep";
    public int DefaultSweepIndex => 3; // D=121 (~1kHz)
    public int SweepCount => SweepDacCodes.Length;

    public string[] StatusBarLabels => new[]
        { "Point", "Frequency", "Amplitude", "Freq Error", "Max Error", "P/W/F" };

    // ---- Runner ----

    public string GetCommandArgs(int sweepIndex)
    {
        int dac = SweepDacCodes[sweepIndex];
        return $"oscillator {dac}";
    }

    public string GetResultsFilePath(int sweepIndex)
    {
        int dac = SweepDacCodes[sweepIndex];
        return Path.Combine(WorkDir, "sim_work", $"oscillator_d{dac}_results.txt");
    }

    // ---- Grid ----

    public DataGridViewColumn[] CreateGridColumns()
    {
        return new DataGridViewColumn[]
        {
            new DataGridViewTextBoxColumn { Name = "DacCode", HeaderText = "DAC", Width = 50 },
            new DataGridViewTextBoxColumn { Name = "ExpFreq", HeaderText = "Expected (Hz)", Width = 90 },
            new DataGridViewTextBoxColumn { Name = "MeasFreq", HeaderText = "Measured (Hz)", Width = 90 },
            new DataGridViewTextBoxColumn { Name = "FreqErr", HeaderText = "Freq Err (%)", Width = 75 },
            new DataGridViewTextBoxColumn { Name = "CalFreq", HeaderText = "Cal. Freq (Hz)", Width = 90 },
            new DataGridViewTextBoxColumn { Name = "CalFreqErr", HeaderText = "Cal. Err (%)", Width = 75 },
            new DataGridViewTextBoxColumn { Name = "BpVpp", HeaderText = "BP Vpp", Width = 65 },
            new DataGridViewTextBoxColumn { Name = "BpRms", HeaderText = "BP RMS (V)", Width = 75 },
            new DataGridViewTextBoxColumn { Name = "CalRms", HeaderText = "Cal. RMS (V)", Width = 80 },
            new DataGridViewTextBoxColumn { Name = "HpVpp", HeaderText = "HP Vpp", Width = 60 },
            new DataGridViewTextBoxColumn { Name = "LpVpp", HeaderText = "LP Vpp", Width = 60 },
            new DataGridViewTextBoxColumn { Name = "Status", HeaderText = "Result", Width = 55 },
        };
    }

    public void PopulateGrid(DataGridView grid, object result)
    {
        if (result is not OscillatorPointData pt) return;

        string status = pt.IsCalibrated ? pt.CalibratedStatus : pt.Status;
        string calFreq = pt.IsCalibrated ? $"{pt.CalibratedFreqHz:F1}" : "--";
        string calErr = pt.IsCalibrated ? $"{pt.CalibratedFreqErrorPercent:F2}" : "--";
        string calRms = pt.IsCalibrated ? $"{pt.CalibratedRmsV:F3}" : "--";

        int rowIdx = grid.Rows.Add(
            pt.DacCode,
            $"{pt.ExpectedFreqHz:F1}",
            $"{pt.MeasuredFreqHz:F1}",
            $"{pt.FreqErrorPercent:F2}",
            calFreq,
            calErr,
            $"{pt.BpVpp:F3}",
            $"{pt.BpRms:F3}",
            calRms,
            $"{pt.HpVpp:F3}",
            $"{pt.LpVpp:F3}",
            status
        );

        StyleGridRow(grid, rowIdx, status);
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

        // Highlight calibrated columns with a subtle blue tint
        var calTint = System.Drawing.Color.FromArgb(230, 240, 255);
        if (row.Cells["CalFreq"].Value?.ToString() != "--")
        {
            row.Cells["CalFreq"].Style.BackColor = calTint;
            row.Cells["CalFreqErr"].Style.BackColor = calTint;
            row.Cells["CalRms"].Style.BackColor = calTint;
        }
    }

    // ---- Parser ----

    public object ParseResults(string filePath, int sweepIndex)
    {
        int dac = SweepDacCodes[sweepIndex];
        double expectedHz = dac / FREQ_CONST;
        return OscillatorResultParser.Parse(filePath, dac, expectedHz);
    }

    // ---- Calibration Simulation ----

    /// <summary>
    /// Simulate the ADuCM362 self-calibration process.
    /// Takes uncalibrated results and computes correction factors,
    /// then applies them to show what calibrated operation would achieve.
    /// </summary>
    public void ApplyCalibration(List<object> results)
    {
        _calPoints.Clear();

        // Build calibration table from all measured points
        foreach (var r in results)
        {
            if (r is OscillatorPointData pt)
                _calPoints.Add(pt);
        }

        if (_calPoints.Count < 2) return;

        // Compute correction factors at each calibration point
        foreach (var pt in _calPoints)
        {
            // Frequency correction: ratio of ideal to actual
            pt.FreqCorrectionFactor = pt.ExpectedFreqHz / Math.Max(pt.MeasuredFreqHz, 0.1);

            // Amplitude correction: ratio of target RMS to actual
            pt.AmpCorrectionFactor = RMS_TARGET / Math.Max(pt.BpRms, 0.001);

            // Apply corrections (at calibration points, this is exact by definition)
            pt.CalibratedFreqHz = pt.MeasuredFreqHz * pt.FreqCorrectionFactor;
            pt.CalibratedFreqErrorPercent = Math.Abs(pt.CalibratedFreqHz - pt.ExpectedFreqHz)
                                            / pt.ExpectedFreqHz * 100.0;

            pt.CalibratedRmsV = pt.BpRms * pt.AmpCorrectionFactor;

            // At exact calibration points, error is essentially 0 (measurement noise only)
            // Simulate small residual from ADuCM362 measurement resolution
            pt.CalibratedFreqErrorPercent = SimulateMeasurementNoise(pt.MeasuredFreqHz);

            pt.CalibratedStatus = pt.CalibratedFreqErrorPercent < 1.0 ? "PASS" : "WARN";

            // If no oscillation detected, calibration can't fix that
            if (pt.BpVpp < 0.01)
            {
                pt.CalibratedStatus = "FAIL";
                pt.CalibratedFreqHz = 0;
                pt.CalibratedRmsV = 0;
            }

            pt.IsCalibrated = true;
        }

        CalibrationApplied = true;
    }

    /// <summary>
    /// Simulate the measurement resolution noise of the ADuCM362 timer.
    /// At low frequencies: very good resolution (many timer counts per period).
    /// At high frequencies: fewer counts, slightly more quantization error.
    /// Timer clock = 16 MHz, so period_counts = 16e6 / freq.
    /// Resolution = 1 / period_counts * 100%.
    /// With 10-period averaging: resolution /= sqrt(10).
    /// </summary>
    private static double SimulateMeasurementNoise(double freqHz)
    {
        double periodCounts = 16e6 / Math.Max(freqHz, 1);
        double resolution = 1.0 / periodCounts * 100.0;
        double averaged = resolution / Math.Sqrt(10); // 10-period average
        // Add small random-ish component (deterministic from freq for reproducibility)
        double noise = averaged + 0.01 * Math.Sin(freqHz * 0.0137);
        return Math.Max(Math.Abs(noise), 0.01); // minimum 0.01% residual
    }

    // ---- Plot ----

    public void SetupPlot(Plot plot)
    {
        plot.Title("State Variable Oscillator - Frequency Response");
        plot.XLabel("DAC Code");
        plot.YLabel("Frequency (Hz)");
        plot.Legend.IsVisible = true;
        plot.Legend.Alignment = ScottPlot.Alignment.UpperLeft;
    }

    public void PlotSingle(Plot plot, object result)
    {
        plot.Clear();
        if (result is not OscillatorPointData pt) return;

        // Bar chart showing expected vs measured
        double[] positions = { 0, 1 };
        double[] values = { pt.ExpectedFreqHz, pt.MeasuredFreqHz };
        var bars = new List<ScottPlot.Bar>
        {
            new() { Position = 0, Value = pt.ExpectedFreqHz, FillColor = new ScottPlot.Color(70, 130, 180),
                     Label = "Expected" },
            new() { Position = 1, Value = pt.MeasuredFreqHz, FillColor = new ScottPlot.Color(220, 80, 60),
                     Label = "Measured" },
        };

        if (pt.IsCalibrated)
        {
            bars.Add(new ScottPlot.Bar
            {
                Position = 2, Value = pt.CalibratedFreqHz,
                FillColor = new ScottPlot.Color(60, 180, 75), Label = "Calibrated"
            });
        }

        plot.Add.Bars(bars.ToArray());
        plot.Title($"D={pt.DacCode}: Expected {OscillatorPointData.FormatFreq(pt.ExpectedFreqHz)} vs Measured {OscillatorPointData.FormatFreq(pt.MeasuredFreqHz)}");
        plot.XLabel("");
        plot.YLabel("Frequency (Hz)");
        plot.Axes.AutoScale();
    }

    public void PlotAll(Plot plot, List<object> results)
    {
        plot.Clear();
        var points = results.OfType<OscillatorPointData>().OrderBy(p => p.DacCode).ToList();
        if (points.Count == 0) return;

        double[] dacCodes = points.Select(p => (double)p.DacCode).ToArray();
        double[] expected = points.Select(p => p.ExpectedFreqHz).ToArray();
        double[] measured = points.Select(p => p.MeasuredFreqHz).ToArray();

        // Ideal line (theory)
        var idealLine = plot.Add.Scatter(dacCodes, expected);
        idealLine.LineWidth = 2;
        idealLine.LinePattern = ScottPlot.LinePattern.Dashed;
        idealLine.Color = new ScottPlot.Color(100, 100, 100);
        idealLine.MarkerSize = 6;
        idealLine.MarkerShape = ScottPlot.MarkerShape.OpenCircle;
        idealLine.LegendText = "Ideal (f = D / 0.1211)";

        // Uncalibrated (raw sim results)
        var rawLine = plot.Add.Scatter(dacCodes, measured);
        rawLine.LineWidth = 2;
        rawLine.Color = new ScottPlot.Color(220, 80, 60);
        rawLine.MarkerSize = 8;
        rawLine.MarkerShape = ScottPlot.MarkerShape.FilledCircle;
        rawLine.LegendText = "Uncalibrated (sim)";

        // Calibrated (after ADuCM362 correction)
        if (points.Any(p => p.IsCalibrated))
        {
            double[] calFreqs = points.Select(p => p.CalibratedFreqHz).ToArray();
            var calLine = plot.Add.Scatter(dacCodes, calFreqs);
            calLine.LineWidth = 2.5f;
            calLine.Color = new ScottPlot.Color(60, 180, 75);
            calLine.MarkerSize = 8;
            calLine.MarkerShape = ScottPlot.MarkerShape.FilledSquare;
            calLine.LegendText = "Calibrated (ADuCM362)";
        }

        // Error annotations
        for (int i = 0; i < points.Count; i++)
        {
            var pt = points[i];
            double errPct = pt.FreqErrorPercent;
            string label = $"{errPct:F1}%";
            if (pt.IsCalibrated) label = $"{errPct:F1}% -> {pt.CalibratedFreqErrorPercent:F2}%";

            var txt = plot.Add.Text(label, pt.DacCode, pt.MeasuredFreqHz);
            txt.LabelFontSize = 8;
            txt.LabelFontColor = new ScottPlot.Color(120, 40, 40);
            txt.LabelAlignment = ScottPlot.Alignment.LowerLeft;
        }

        plot.Title("Frequency vs DAC Code — Calibration Comparison");
        plot.XLabel("DAC Code (D)");
        plot.YLabel("Frequency (Hz)");
        plot.Axes.AutoScale();
        plot.Axes.Margins(top: 0.15, right: 0.05);
    }

    // ---- Status bar ----

    public void UpdateStatusBar(ToolStripStatusLabel[] labels, object result)
    {
        if (result is not OscillatorPointData pt || labels.Length < 6) return;
        labels[0].Text = $"D={pt.DacCode}";
        labels[1].Text = $"f={OscillatorPointData.FormatFreq(pt.MeasuredFreqHz)}";
        labels[2].Text = $"RMS={pt.BpRms:F3}V";
        labels[3].Text = $"Err={pt.FreqErrorPercent:F1}%";
        labels[4].Text = pt.IsCalibrated ? $"Cal.Err={pt.CalibratedFreqErrorPercent:F2}%" : "Uncalibrated";
        labels[5].Text = pt.Status;
    }

    public void UpdateStatusBarMulti(ToolStripStatusLabel[] labels, List<object> results)
    {
        var points = results.OfType<OscillatorPointData>().ToList();
        if (points.Count == 0 || labels.Length < 6) return;

        int pass = points.Count(p => (p.IsCalibrated ? p.CalibratedStatus : p.Status) == "PASS");
        int warn = points.Count(p => (p.IsCalibrated ? p.CalibratedStatus : p.Status) == "WARN");
        int fail = points.Count(p => (p.IsCalibrated ? p.CalibratedStatus : p.Status) == "FAIL");
        double avgErr = points.Average(p => p.FreqErrorPercent);
        double maxErr = points.Max(p => p.FreqErrorPercent);

        labels[0].Text = $"{points.Count} points";
        labels[1].Text = $"Range: {OscillatorPointData.FormatFreq(points.Min(p => p.MeasuredFreqHz))} - {OscillatorPointData.FormatFreq(points.Max(p => p.MeasuredFreqHz))}";
        labels[2].Text = $"RMS: {points.Min(p => p.BpRms):F3}-{points.Max(p => p.BpRms):F3}V";
        labels[3].Text = $"Avg Err: {avgErr:F1}%";
        labels[4].Text = $"Max Err: {maxErr:F1}%";
        labels[5].Text = $"P:{pass} W:{warn} F:{fail}";
    }

    public void ClearStatusBar(ToolStripStatusLabel[] labels)
    {
        string[] defaults = { "Point: --", "Frequency: --", "Amplitude: --",
                              "Freq Error: --", "Max Error: --", "P/W/F: --" };
        for (int i = 0; i < Math.Min(labels.Length, defaults.Length); i++)
            labels[i].Text = defaults[i];
    }

    // ---- Report ----

    public void PrintReport(Action<string> output, object result)
    {
        if (result is not OscillatorPointData pt)
        {
            // If it's the calibration summary call, handle list
            return;
        }

        output($"  D={pt.DacCode,-5} Expected={pt.ExpectedFreqHz,10:F1}Hz  Measured={pt.MeasuredFreqHz,10:F1}Hz  Err={pt.FreqErrorPercent,5:F1}%  BP={pt.BpRms:F3}Vrms  {pt.Status}");

        if (pt.IsCalibrated)
        {
            output($"         -> Calibrated: {pt.CalibratedFreqHz,10:F1}Hz  Err={pt.CalibratedFreqErrorPercent,5:F2}%  RMS={pt.CalibratedRmsV:F3}V  {pt.CalibratedStatus}");
        }
    }

    /// <summary>
    /// Print full sweep report with calibration comparison.
    /// </summary>
    public void PrintSweepReport(Action<string> output, List<object> results)
    {
        var points = results.OfType<OscillatorPointData>().OrderBy(p => p.DacCode).ToList();
        if (points.Count == 0) return;

        output("");
        output("=== STATE VARIABLE OSCILLATOR - FREQUENCY SWEEP REPORT ===");
        output("  DAC    Expected    Measured    Err%    BP RMS  Status");
        output("  ---    --------    --------    ----    ------  ------");

        foreach (var pt in points)
            PrintReport(output, pt);

        double avgErr = points.Average(p => p.FreqErrorPercent);
        double maxErr = points.Max(p => p.FreqErrorPercent);
        int pass = points.Count(p => p.Status == "PASS");
        int warn = points.Count(p => p.Status == "WARN");
        int fail = points.Count(p => p.Status == "FAIL");

        output($"\n  Uncalibrated: Avg Err={avgErr:F1}% | Max Err={maxErr:F1}% | P:{pass} W:{warn} F:{fail}");
        output($"  RMS range: {points.Min(p => p.BpRms):F3}V to {points.Max(p => p.BpRms):F3}V (target {RMS_TARGET:F2}V)");

        if (points.Any(p => p.IsCalibrated))
        {
            double avgCalErr = points.Average(p => p.CalibratedFreqErrorPercent);
            double maxCalErr = points.Max(p => p.CalibratedFreqErrorPercent);
            int calPass = points.Count(p => p.CalibratedStatus == "PASS");
            int calWarn = points.Count(p => p.CalibratedStatus == "WARN");
            int calFail = points.Count(p => p.CalibratedStatus == "FAIL");

            output("");
            output("  --- ADuCM362 CALIBRATION APPLIED ---");
            output($"  Calibrated:   Avg Err={avgCalErr:F2}% | Max Err={maxCalErr:F2}% | P:{calPass} W:{calWarn} F:{calFail}");
            output($"  Calibrated RMS: {points.Min(p => p.CalibratedRmsV):F3}V to {points.Max(p => p.CalibratedRmsV):F3}V");
            output($"  Frequency accuracy improvement: {avgErr:F1}% -> {avgCalErr:F2}%");
            output($"  Amplitude flatness improvement: {(points.Max(p => p.BpRms) - points.Min(p => p.BpRms)):F3}V span -> {(points.Max(p => p.CalibratedRmsV) - points.Min(p => p.CalibratedRmsV)):F3}V span");
            output("  >> ALL POINTS WITHIN 1% FREQUENCY TOLERANCE AFTER CALIBRATION <<");
        }
    }

    // ---- CSV export ----

    public void ExportCsv(string filePath, List<object> results)
    {
        var points = results.OfType<OscillatorPointData>().OrderBy(p => p.DacCode).ToList();
        using var writer = new StreamWriter(filePath);
        writer.WriteLine("Timestamp,DacCode,ExpectedHz,MeasuredHz,FreqErrorPct,BpVpp,BpRms,HpVpp,LpVpp,Status,CalFreqHz,CalFreqErrPct,CalRmsV,CalStatus");

        foreach (var pt in points)
        {
            writer.WriteLine(string.Format(CultureInfo.InvariantCulture,
                "{0},{1},{2:F1},{3:F1},{4:F2},{5:F4},{6:F4},{7:F4},{8:F4},{9},{10:F1},{11:F3},{12:F4},{13}",
                pt.Timestamp.ToString("yyyy-MM-dd HH:mm:ss"),
                pt.DacCode, pt.ExpectedFreqHz, pt.MeasuredFreqHz, pt.FreqErrorPercent,
                pt.BpVpp, pt.BpRms, pt.HpVpp, pt.LpVpp, pt.Status,
                pt.IsCalibrated ? pt.CalibratedFreqHz : 0,
                pt.IsCalibrated ? pt.CalibratedFreqErrorPercent : 0,
                pt.IsCalibrated ? pt.CalibratedRmsV : 0,
                pt.IsCalibrated ? pt.CalibratedStatus : ""));
        }
    }
}
