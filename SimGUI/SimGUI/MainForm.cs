using SimGUI.Models;
using SimGUI.Projects;
using SimGUI.Services;
using ScottPlot;

namespace SimGUI;

public partial class MainForm : Form
{
    private readonly SimulationRunner _simRunner = new();
    private IProjectConfig _project;
    private readonly List<object> _allResults = new();

    private static readonly string SimWorkDir = @"C:\Users\Robert\Documents\LTspice\sim_work";

    public MainForm()
    {
        InitializeComponent();
        _project = new ElectrometerConfig(); // default
        SwitchProject(_project);
        WireEvents();
    }

    // ------------------------------------------------------------------
    // Project switching
    // ------------------------------------------------------------------

    private void SwitchProject(IProjectConfig project)
    {
        _project = project;
        _allResults.Clear();

        // Update form title
        Text = _project.FormTitle;

        // Update sweep point combo
        _cboSweepPoint.Items.Clear();
        foreach (var name in _project.SweepPointNames)
            _cboSweepPoint.Items.Add(name);
        _cboSweepPoint.SelectedIndex = Math.Min(_project.DefaultSweepIndex, _cboSweepPoint.Items.Count - 1);

        // Update button labels
        _btnRunSim.Text = _project.RunSingleLabel;
        _btnRunAll.Text = _project.RunAllLabel;

        // Show/hide calibrate button (oscillator only)
        _btnCalibrate.Visible = _project is OscillatorConfig;
        _btnCalibrate.Enabled = false;

        // Rebuild grid columns
        _dataGrid.Columns.Clear();
        _dataGrid.Rows.Clear();
        foreach (var col in _project.CreateGridColumns())
        {
            _dataGrid.Columns.Add(col);
            // Right-align numeric columns (skip Channel, Status-like columns)
            if (col.Name != "Channel" && col.Name != "Status" && col.Name != "Range" && col.Name != "DacCode")
                col.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight;
        }

        // Setup plot
        _formsPlot.Plot.Clear();
        _project.SetupPlot(_formsPlot.Plot);
        _formsPlot.Refresh();

        // Clear status bar
        _project.ClearStatusBar(_statusLabels);

        // Clear output
        _txtOutput.Clear();
        _btnExportCsv.Enabled = false;
        SetStatus("Ready");
    }

    // ------------------------------------------------------------------
    // Event wiring
    // ------------------------------------------------------------------

    private void WireEvents()
    {
        _cboProject.SelectedIndexChanged += (_, _) =>
        {
            IProjectConfig newProject = _cboProject.SelectedIndex switch
            {
                0 => new ElectrometerConfig(),
                1 => new OscillatorConfig(),
                _ => new ElectrometerConfig(),
            };
            SwitchProject(newProject);
        };

        _btnRunSim.Click += async (_, _) => await RunSimulation();
        _btnRunAll.Click += async (_, _) => await RunAllSweepPoints();
        _btnCalibrate.Click += (_, _) => RunCalibration();
        _btnLoadFile.Click += (_, _) => LoadResultFile();
        _btnExportCsv.Click += (_, _) => ExportCsv();
        _btnScreenshot.Click += (_, _) => TakeScreenshot();
        _btnClear.Click += (_, _) => ClearAll();

        _simRunner.OutputReceived += msg =>
        {
            if (InvokeRequired) Invoke(() => AppendOutput(msg));
            else AppendOutput(msg);
        };

        _simRunner.SimulationComplete += (success, msg) =>
        {
            if (InvokeRequired) Invoke(() => AppendOutput(msg));
            else AppendOutput(msg);
        };
    }

    private int SelectedSweepIndex => _cboSweepPoint.SelectedIndex >= 0
        ? _cboSweepPoint.SelectedIndex : _project.DefaultSweepIndex;

    // ------------------------------------------------------------------
    // Run single sweep point
    // ------------------------------------------------------------------

    private async Task RunSimulation()
    {
        if (_simRunner.IsRunning)
        {
            _simRunner.Cancel();
            _btnRunSim.Text = _project.RunSingleLabel;
            SetStatus("Cancelled");
            return;
        }

        int idx = SelectedSweepIndex;
        string args = _project.GetCommandArgs(idx);

        _btnRunSim.Text = "Cancel";
        _btnRunAll.Enabled = false;
        _btnExportCsv.Enabled = false;
        _btnCalibrate.Enabled = false;
        SetStatus($"Running {_project.SweepPointNames[idx]}...");
        _txtOutput.Clear();

        await Task.Run(() => _simRunner.RunGenericAsync(args));

        _btnRunSim.Text = _project.RunSingleLabel;
        _btnRunAll.Enabled = true;

        // Load results
        string resultsPath = _project.GetResultsFilePath(idx);
        if (File.Exists(resultsPath))
        {
            try
            {
                var result = _project.ParseResults(resultsPath, idx);
                _dataGrid.Rows.Clear();
                _project.PopulateGrid(_dataGrid, result);

                _formsPlot.Plot.Clear();
                _project.PlotSingle(_formsPlot.Plot, result);
                _formsPlot.Refresh();

                _project.UpdateStatusBar(_statusLabels, result);
                _project.PrintReport(AppendOutput, result);
                _btnExportCsv.Enabled = true;

                _allResults.Clear();
                _allResults.Add(result);

                SetStatus($"{_project.SweepPointNames[idx]} complete");
            }
            catch (Exception ex)
            {
                SetStatus($"Parse error: {ex.Message}");
                AppendOutput($"Parse error: {ex.Message}");
            }
        }
        else
        {
            SetStatus($"{_project.SweepPointNames[idx]} failed - no results file");
        }
    }

    // ------------------------------------------------------------------
    // Run ALL sweep points
    // ------------------------------------------------------------------

    private async Task RunAllSweepPoints()
    {
        if (_simRunner.IsRunning)
        {
            _simRunner.Cancel();
            SetStatus("Cancelled");
            return;
        }

        _btnRunSim.Enabled = false;
        _btnRunAll.Text = "Cancel";
        _btnExportCsv.Enabled = false;
        _btnCalibrate.Enabled = false;
        _allResults.Clear();
        _dataGrid.Rows.Clear();
        _formsPlot.Plot.Clear();
        _formsPlot.Refresh();
        _txtOutput.Clear();

        AppendOutput($"========== RUNNING {_project.ProjectName.ToUpper()} SWEEP: {_project.SweepCount} POINTS ==========");

        for (int i = 0; i < _project.SweepCount; i++)
        {
            string pointName = _project.SweepPointNames[i];
            string args = _project.GetCommandArgs(i);

            AppendOutput($"\n>>> {pointName} <<<");
            SetStatus($"Point {i + 1}/{_project.SweepCount}: {pointName}...");
            _cboSweepPoint.SelectedIndex = i;

            await Task.Run(() => _simRunner.RunGenericAsync(args));

            string resultsPath = _project.GetResultsFilePath(i);
            if (File.Exists(resultsPath))
            {
                try
                {
                    var result = _project.ParseResults(resultsPath, i);
                    _allResults.Add(result);
                    _project.PopulateGrid(_dataGrid, result);
                    _project.PrintReport(AppendOutput, result);
                }
                catch (Exception ex)
                {
                    AppendOutput($"Point {i} parse error: {ex.Message}");
                }
            }
            else
            {
                AppendOutput($"Point {i} FAILED - no results file");
            }
        }

        _btnRunSim.Enabled = true;
        _btnRunAll.Text = _project.RunAllLabel;
        _btnExportCsv.Enabled = _allResults.Count > 0;

        // Plot all results
        if (_allResults.Count > 0)
        {
            _formsPlot.Plot.Clear();
            _project.PlotAll(_formsPlot.Plot, _allResults);
            _formsPlot.Refresh();
            _project.UpdateStatusBarMulti(_statusLabels, _allResults);
        }

        // Print sweep summary
        if (_project is OscillatorConfig oscConfig)
        {
            oscConfig.PrintSweepReport(AppendOutput, _allResults);
            _btnCalibrate.Enabled = _allResults.Count >= 2;
            AppendOutput("\n>> Click 'Calibrate' to simulate ADuCM362 self-calibration <<");
        }
        else
        {
            PrintElectrometerSummary();
        }

        SetStatus($"Sweep done: {_allResults.Count}/{_project.SweepCount} points");
    }

    // ------------------------------------------------------------------
    // Calibration simulation (oscillator only)
    // ------------------------------------------------------------------

    private void RunCalibration()
    {
        if (_project is not OscillatorConfig oscConfig || _allResults.Count < 2) return;

        AppendOutput("\n========== ADuCM362 SELF-CALIBRATION SIMULATION ==========");
        AppendOutput("  Computing frequency correction factors from measured data...");
        AppendOutput("  Computing amplitude correction factors (AD636 AGC)...");

        // Apply calibration to all results
        oscConfig.ApplyCalibration(_allResults);

        // Rebuild grid with calibrated data
        _dataGrid.Rows.Clear();
        foreach (var result in _allResults)
            _project.PopulateGrid(_dataGrid, result);

        // Replot with calibration overlay
        _formsPlot.Plot.Clear();
        _project.PlotAll(_formsPlot.Plot, _allResults);
        _formsPlot.Refresh();

        // Print calibrated report
        oscConfig.PrintSweepReport(AppendOutput, _allResults);

        _project.UpdateStatusBarMulti(_statusLabels, _allResults);
        _btnCalibrate.Enabled = false; // already calibrated
        SetStatus("Calibration applied");
    }

    // ------------------------------------------------------------------
    // Electrometer summary (preserves existing behavior)
    // ------------------------------------------------------------------

    private void PrintElectrometerSummary()
    {
        var simResults = _allResults.OfType<SimulationResult>().ToList();
        if (simResults.Count == 0) return;

        AppendOutput("\n========== ALL RANGES SUMMARY ==========");
        int totalPass = 0, totalWarn = 0, totalFail = 0;
        foreach (var r in simResults)
        {
            AppendOutput($"  Range {r.RangeIndex} (Rf={r.RfDisplay}): {r.PassCount}P/{r.WarnCount}W/{r.FailCount}F  AvgErr={r.AverageErrorPercent:F1}%  MaxErr={r.MaxErrorPercent:F1}%");
            totalPass += r.PassCount;
            totalWarn += r.WarnCount;
            totalFail += r.FailCount;
        }
        AppendOutput($"  TOTAL: {totalPass}P / {totalWarn}W / {totalFail}F across {simResults.Count * 16} channels");
        if (totalFail == 0)
            AppendOutput("  >> ALL CHANNELS ALL RANGES WITHIN TOLERANCE <<");
        else
            AppendOutput($"  >> {totalFail} CHANNEL(S) EXCEED 20% ERROR <<");
    }

    // ------------------------------------------------------------------
    // Load / Parse
    // ------------------------------------------------------------------

    private void LoadResultFile()
    {
        using var dlg = new OpenFileDialog
        {
            Title = "Load Simulation Results",
            Filter = "Text Files (*.txt)|*.txt|All Files (*.*)|*.*",
            InitialDirectory = SimWorkDir,
        };

        if (dlg.ShowDialog() == DialogResult.OK)
        {
            SetStatus("Loading...");
            try
            {
                int idx = SelectedSweepIndex;

                // Auto-detect: if filename contains "oscillator", parse as oscillator
                string fname = Path.GetFileName(dlg.FileName);
                object result;
                if (fname.Contains("oscillator"))
                {
                    // Switch to oscillator project if not already
                    if (_project is not OscillatorConfig)
                    {
                        _cboProject.SelectedIndex = 1; // triggers SwitchProject
                    }
                    result = _project.ParseResults(dlg.FileName, idx);
                }
                else
                {
                    if (_project is not ElectrometerConfig)
                    {
                        _cboProject.SelectedIndex = 0;
                    }
                    int range = ResultParser.DetectRangeFromPath(dlg.FileName);
                    result = _project.ParseResults(dlg.FileName, range);
                }

                _dataGrid.Rows.Clear();
                _project.PopulateGrid(_dataGrid, result);

                _formsPlot.Plot.Clear();
                _project.PlotSingle(_formsPlot.Plot, result);
                _formsPlot.Refresh();

                _project.UpdateStatusBar(_statusLabels, result);
                _project.PrintReport(AppendOutput, result);

                _allResults.Clear();
                _allResults.Add(result);
                _btnExportCsv.Enabled = true;

                SetStatus("Loaded: " + fname);
            }
            catch (Exception ex)
            {
                SetStatus($"Load error: {ex.Message}");
                MessageBox.Show(ex.Message, "Load Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }

    // ------------------------------------------------------------------
    // Screenshot
    // ------------------------------------------------------------------

    private void TakeScreenshot()
    {
        using var dlg = new SaveFileDialog
        {
            Title = "Save Screenshot",
            Filter = "PNG Image (*.png)|*.png|JPEG Image (*.jpg)|*.jpg",
            FileName = $"SimGUI_{_project.ProjectName}_{DateTime.Now:yyyyMMdd_HHmmss}.png",
            InitialDirectory = SimWorkDir,
        };

        if (dlg.ShowDialog() == DialogResult.OK)
        {
            try
            {
                using var bmp = new Bitmap(Width, Height);
                DrawToBitmap(bmp, new Rectangle(0, 0, Width, Height));
                bmp.Save(dlg.FileName);
                AppendOutput($"Screenshot saved: {dlg.FileName}");
                SetStatus("Screenshot saved");
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "Screenshot Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }

    // ------------------------------------------------------------------
    // Export
    // ------------------------------------------------------------------

    private void ExportCsv()
    {
        if (_allResults.Count == 0) return;

        using var dlg = new SaveFileDialog
        {
            Title = "Export CSV",
            Filter = "CSV Files (*.csv)|*.csv",
            FileName = $"sim_{_project.ProjectName.ToLower()}_{DateTime.Now:yyyyMMdd_HHmmss}.csv",
            InitialDirectory = SimWorkDir,
        };

        if (dlg.ShowDialog() == DialogResult.OK)
        {
            try
            {
                _project.ExportCsv(dlg.FileName, _allResults);
                AppendOutput($"Exported to: {dlg.FileName}");
                SetStatus("Exported: " + Path.GetFileName(dlg.FileName));
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "Export Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }

    // ------------------------------------------------------------------
    // Clear
    // ------------------------------------------------------------------

    private void ClearAll()
    {
        _dataGrid.Rows.Clear();
        _formsPlot.Plot.Clear();
        _project.SetupPlot(_formsPlot.Plot);
        _formsPlot.Refresh();
        _txtOutput.Clear();
        _allResults.Clear();
        _btnExportCsv.Enabled = false;
        _btnCalibrate.Enabled = false;
        _project.ClearStatusBar(_statusLabels);
        SetStatus("Ready");
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    private void SetStatus(string text) => _lblToolStatus.Text = text;

    private void AppendOutput(string text)
    {
        _txtOutput.AppendText($"[{DateTime.Now:HH:mm:ss}] {text}{Environment.NewLine}");
    }
}
