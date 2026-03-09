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
    private bool _showAmplitudePlot = false;

    private static readonly string SimWorkDir = Path.Combine(SimGUI.Services.SimulationRunner.RepoRoot, "sim_work");

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
        _showAmplitudePlot = false;

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

        // Show/hide toggle plot button (comparison only)
        _btnTogglePlot.Visible = _project is ComparisonConfig;
        _btnTogglePlot.Enabled = false;
        _btnTogglePlot.Text = "Amplitude View";

        // Show/hide generic circuit buttons
        _btnLoadCircuit.Visible = _project is GenericCircuitConfig;
        _btnViewCircuit.Visible = _project is GenericCircuitConfig;
        _btnViewCircuit.Enabled = false;
        _btnToggleView.Visible = _project is GenericCircuitConfig;
        _btnToggleView.Enabled = false;
        _btnToggleView.Text = "Bode View";

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
                2 => new ComparisonConfig(),
                3 => new GenericCircuitConfig(),
                _ => new ElectrometerConfig(),
            };
            SwitchProject(newProject);
        };

        _btnRunSim.Click += async (_, _) => await RunSimulation();
        _btnRunAll.Click += async (_, _) => await RunAllSweepPoints();
        _btnCalibrate.Click += (_, _) => RunCalibration();
        _btnTogglePlot.Click += (_, _) => ToggleComparisonPlot();
        _btnLoadCircuit.Click += async (_, _) => await LoadCircuitFile();
        _btnViewCircuit.Click += (_, _) => ViewCircuitInLTspice();
        _btnToggleView.Click += (_, _) => ToggleGenericView();
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

        // Comparison mode: run both MDAC + analog
        if (_project is ComparisonConfig compConfig)
        {
            await RunSingleComparisonAsync(compConfig);
            return;
        }

        // Generic circuit mode
        if (_project is GenericCircuitConfig genConfig)
        {
            await RunGenericCircuitAsync(genConfig);
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

        await _simRunner.RunGenericAsync(args);

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

        // Comparison mode: run both MDAC + analog at all points
        if (_project is ComparisonConfig compConfig)
        {
            await RunComparisonSweepAsync(compConfig);
            return;
        }

        // Generic circuit: RunAll is same as RunSingle (all analyses at once)
        if (_project is GenericCircuitConfig genConfig2)
        {
            await RunGenericCircuitAsync(genConfig2);
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

            await _simRunner.RunGenericAsync(args);

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
    // Comparison mode: single point
    // ------------------------------------------------------------------

    private async Task RunSingleComparisonAsync(ComparisonConfig compConfig)
    {
        int idx = SelectedSweepIndex;
        string pointName = compConfig.SweepPointNames[idx];

        _btnRunSim.Text = "Cancel";
        _btnRunAll.Enabled = false;
        _btnExportCsv.Enabled = false;
        _btnTogglePlot.Enabled = false;
        _txtOutput.Clear();

        AppendOutput($"========== COMPARING AT {pointName} ==========");

        // Run MDAC simulation
        string mdacArgs = compConfig.GetCommandArgs(idx);
        AppendOutput($"\n  [MDAC] Running: {mdacArgs}...");
        SetStatus($"MDAC: {pointName}...");
        await _simRunner.RunGenericAsync(mdacArgs);

        // Run Analog simulation
        string analogArgs = compConfig.GetAnalogCommandArgs(idx);
        AppendOutput($"\n  [ANALOG] Running: {analogArgs}...");
        SetStatus($"Analog: {pointName}...");
        await _simRunner.RunGenericAsync(analogArgs);

        _btnRunSim.Text = compConfig.RunSingleLabel;
        _btnRunAll.Enabled = true;

        // Parse both results
        string mdacPath = compConfig.GetResultsFilePath(idx);
        string analogPath = compConfig.GetAnalogResultsFilePath(idx);

        if (File.Exists(mdacPath) && File.Exists(analogPath))
        {
            try
            {
                var mdacResult = (OscillatorPointData)compConfig.ParseResults(mdacPath, idx);
                var analogResult = (OscillatorPointData)compConfig.ParseResults(analogPath, idx);
                var comparison = compConfig.BuildComparison(idx, mdacResult, analogResult);

                _dataGrid.Rows.Clear();
                compConfig.PopulateGrid(_dataGrid, comparison);

                _formsPlot.Plot.Clear();
                compConfig.PlotSingle(_formsPlot.Plot, comparison);
                _formsPlot.Refresh();

                compConfig.UpdateStatusBar(_statusLabels, comparison);
                compConfig.PrintReport(AppendOutput, comparison);

                _allResults.Clear();
                _allResults.Add(comparison);
                _btnExportCsv.Enabled = true;

                SetStatus($"{pointName} comparison complete");
            }
            catch (Exception ex)
            {
                SetStatus($"Parse error: {ex.Message}");
                AppendOutput($"Parse error: {ex.Message}");
            }
        }
        else
        {
            if (!File.Exists(mdacPath))
                AppendOutput($"  MDAC results missing: {mdacPath}");
            if (!File.Exists(analogPath))
                AppendOutput($"  Analog results missing: {analogPath}");
            SetStatus("Comparison failed - missing results");
        }
    }

    // ------------------------------------------------------------------
    // Comparison mode: full sweep
    // ------------------------------------------------------------------

    private async Task RunComparisonSweepAsync(ComparisonConfig compConfig)
    {
        _btnRunSim.Enabled = false;
        _btnRunAll.Text = "Cancel";
        _btnExportCsv.Enabled = false;
        _btnTogglePlot.Enabled = false;
        _allResults.Clear();
        _dataGrid.Rows.Clear();
        _formsPlot.Plot.Clear();
        _formsPlot.Refresh();
        _txtOutput.Clear();

        AppendOutput("========== COMPARISON SWEEP: MDAC vs ANALOG (8 POINTS x 2 DESIGNS = 16 SIMULATIONS) ==========");

        for (int i = 0; i < compConfig.SweepCount; i++)
        {
            string pointName = compConfig.SweepPointNames[i];
            AppendOutput($"\n>>> {pointName} <<<");
            SetStatus($"Point {i + 1}/{compConfig.SweepCount}: {pointName}...");
            _cboSweepPoint.SelectedIndex = i;

            // Run MDAC simulation
            string mdacArgs = compConfig.GetCommandArgs(i);
            AppendOutput($"  [MDAC] {mdacArgs}...");
            await _simRunner.RunGenericAsync(mdacArgs);

            // Run Analog simulation
            string analogArgs = compConfig.GetAnalogCommandArgs(i);
            AppendOutput($"  [ANALOG] {analogArgs}...");
            await _simRunner.RunGenericAsync(analogArgs);

            // Parse both results
            string mdacPath = compConfig.GetResultsFilePath(i);
            string analogPath = compConfig.GetAnalogResultsFilePath(i);

            if (File.Exists(mdacPath) && File.Exists(analogPath))
            {
                try
                {
                    var mdacResult = (OscillatorPointData)compConfig.ParseResults(mdacPath, i);
                    var analogResult = (OscillatorPointData)compConfig.ParseResults(analogPath, i);
                    var comparison = compConfig.BuildComparison(i, mdacResult, analogResult);
                    _allResults.Add(comparison);
                    compConfig.PopulateGrid(_dataGrid, comparison);
                    compConfig.PrintReport(AppendOutput, comparison);
                }
                catch (Exception ex)
                {
                    AppendOutput($"  Parse error at point {i}: {ex.Message}");
                }
            }
            else
            {
                if (!File.Exists(mdacPath))
                    AppendOutput($"  MDAC results missing: {mdacPath}");
                if (!File.Exists(analogPath))
                    AppendOutput($"  Analog results missing: {analogPath}");
            }
        }

        _btnRunSim.Enabled = true;
        _btnRunAll.Text = compConfig.RunAllLabel;
        _btnExportCsv.Enabled = _allResults.Count > 0;
        _btnTogglePlot.Enabled = _allResults.Count > 0;

        if (_allResults.Count > 0)
        {
            _showAmplitudePlot = false;
            _btnTogglePlot.Text = "Amplitude View";
            _formsPlot.Plot.Clear();
            compConfig.PlotAll(_formsPlot.Plot, _allResults);
            _formsPlot.Refresh();
            compConfig.UpdateStatusBarMulti(_statusLabels, _allResults);
        }

        // Print comparison summary
        compConfig.PrintSweepSummary(AppendOutput, _allResults);
        SetStatus($"Comparison done: {_allResults.Count}/{compConfig.SweepCount} points");
    }

    // ------------------------------------------------------------------
    // Toggle comparison plot view
    // ------------------------------------------------------------------

    private void ToggleComparisonPlot()
    {
        if (_project is not ComparisonConfig compConfig || _allResults.Count == 0) return;

        _showAmplitudePlot = !_showAmplitudePlot;
        _formsPlot.Plot.Clear();

        if (_showAmplitudePlot)
        {
            compConfig.PlotAmplitude(_formsPlot.Plot, _allResults);
            _btnTogglePlot.Text = "Frequency View";
        }
        else
        {
            compConfig.PlotAll(_formsPlot.Plot, _allResults);
            _btnTogglePlot.Text = "Amplitude View";
        }
        _formsPlot.Refresh();
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

                // Auto-detect: if filename contains "analog_osc", switch to comparison
                string fname = Path.GetFileName(dlg.FileName);
                object result;
                if (fname.Contains("analog_osc"))
                {
                    if (_project is not ComparisonConfig)
                    {
                        _cboProject.SelectedIndex = 2; // triggers SwitchProject
                    }
                    result = _project.ParseResults(dlg.FileName, idx);
                }
                else if (fname.Contains("oscillator"))
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
    // Generic circuit: Load + Analyze + Dialog
    // ------------------------------------------------------------------

    private async Task LoadCircuitFile()
    {
        if (_project is not GenericCircuitConfig genConfig) return;

        // Try LTspice examples folders, fall back to sim_work
        string ltspiceExamples = SimWorkDir;
        string[] examplePaths = new[]
        {
            @"C:\Program Files\LTC\LTspiceXVII\examples\Educational",
            @"C:\Program Files\LTC\LTspiceXVII\examples",
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "LTspice", "examples"),
        };
        foreach (var p in examplePaths)
        {
            if (Directory.Exists(p)) { ltspiceExamples = p; break; }
        }

        using var dlg = new OpenFileDialog
        {
            Title = "Load Circuit File",
            Filter = "All Circuit Files (*.asc;*.cir;*.net;*.sp)|*.asc;*.cir;*.net;*.sp|LTspice (*.asc)|*.asc|SPICE Netlist (*.cir;*.net;*.sp)|*.cir;*.net;*.sp|All Files (*.*)|*.*",
            InitialDirectory = ltspiceExamples,
        };

        if (dlg.ShowDialog() != DialogResult.OK) return;

        string circuitPath = dlg.FileName;
        SetStatus($"Analyzing: {Path.GetFileName(circuitPath)}...");
        AppendOutput($"Analyzing circuit: {circuitPath}");

        // Run analyze_circuit in Python
        string args = $"analyze_circuit \"{circuitPath}\"";
        string jsonOutput = "";

        var psi = new System.Diagnostics.ProcessStartInfo
        {
            FileName = FindPythonExe(),
            Arguments = $"\"{Path.Combine(SimulationRunner.RepoRoot, "kicad_pipeline.py")}\" {args}",
            WorkingDirectory = SimulationRunner.RepoRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };

        try
        {
            using var proc = System.Diagnostics.Process.Start(psi);
            if (proc == null) { SetStatus("Failed to start analysis"); return; }
            jsonOutput = await proc.StandardOutput.ReadToEndAsync();
            string errOutput = await proc.StandardError.ReadToEndAsync();
            await proc.WaitForExitAsync();

            if (!string.IsNullOrEmpty(errOutput))
                AppendOutput($"[Analysis stderr] {errOutput}");
        }
        catch (Exception ex)
        {
            SetStatus($"Analysis error: {ex.Message}");
            AppendOutput($"Analysis error: {ex.Message}");
            return;
        }

        // Parse the JSON analysis result
        try
        {
            var analysis = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(jsonOutput);
            if (analysis.TryGetProperty("error", out var err))
            {
                AppendOutput($"Analysis error: {err.GetString()}");
                SetStatus("Analysis failed");
                return;
            }

            string circuitName = "";
            string circuitType = "generic";
            string[] allNodes = Array.Empty<string>();
            string[] inputNodes = Array.Empty<string>();
            string[] outputNodes = Array.Empty<string>();
            var suggestedAnalyses = new List<(string id, string name, string desc, bool enabled)>();

            if (analysis.TryGetProperty("circuit_name", out var cn))
                circuitName = cn.GetString() ?? "";
            if (analysis.TryGetProperty("circuit_type", out var ct))
                circuitType = ct.GetString() ?? "generic";
            if (analysis.TryGetProperty("nodes", out var nodes))
            {
                if (nodes.TryGetProperty("all", out var an))
                    allNodes = an.EnumerateArray().Select(e => e.GetString() ?? "").Where(s => s != "").ToArray();
                if (nodes.TryGetProperty("inputs", out var inp))
                    inputNodes = inp.EnumerateArray().Select(e => e.GetString() ?? "").Where(s => s != "").ToArray();
                if (nodes.TryGetProperty("outputs", out var outp))
                    outputNodes = outp.EnumerateArray().Select(e => e.GetString() ?? "").Where(s => s != "").ToArray();
            }
            if (analysis.TryGetProperty("suggested_analyses", out var sa))
            {
                foreach (var item in sa.EnumerateArray())
                {
                    string id = item.TryGetProperty("id", out var sid) ? sid.GetString() ?? "" : "";
                    string name = item.TryGetProperty("name", out var sn) ? sn.GetString() ?? "" : "";
                    string desc = item.TryGetProperty("description", out var sd) ? sd.GetString() ?? "" : "";
                    bool enabled = item.TryGetProperty("enabled_by_default", out var se) && se.GetBoolean();
                    suggestedAnalyses.Add((id, name, desc, enabled));
                }
            }

            // Components summary
            string componentsSummary = "";
            if (analysis.TryGetProperty("components", out var comp))
            {
                var parts = new List<string>();
                foreach (var prop in comp.EnumerateObject())
                {
                    int count = prop.Value.GetInt32();
                    if (count > 0) parts.Add($"{count} {prop.Name}");
                }
                componentsSummary = string.Join(", ", parts);
            }

            AppendOutput($"  Circuit: {circuitName} ({circuitType})");
            AppendOutput($"  Components: {componentsSummary}");
            AppendOutput($"  Nodes: {string.Join(", ", allNodes)}");

            // Show analysis selection dialog
            using var analysisDlg = new AnalysisSelectionDialog(
                circuitName, circuitType, componentsSummary,
                allNodes, inputNodes, outputNodes,
                suggestedAnalyses);

            if (analysisDlg.ShowDialog() != DialogResult.OK) return;

            // Apply user selections
            genConfig.SetCircuitInfo(
                circuitPath, circuitName, circuitType,
                allNodes, analysisDlg.SelectedProbes, analysisDlg.SelectedAnalyses);

            // Update sweep combo with selected probes
            _cboSweepPoint.Items.Clear();
            foreach (var probe in analysisDlg.SelectedProbes)
                _cboSweepPoint.Items.Add($"Node: {probe}");
            if (_cboSweepPoint.Items.Count > 0)
                _cboSweepPoint.SelectedIndex = 0;

            Text = genConfig.FormTitle;
            genConfig.ClearStatusBar(_statusLabels);
            _btnViewCircuit.Enabled = circuitPath.EndsWith(".asc", StringComparison.OrdinalIgnoreCase);
            SetStatus($"Ready: {circuitName} ({circuitType}) - Click Simulate");

            AppendOutput($"  Selected analyses: {string.Join(", ", analysisDlg.SelectedAnalyses)}");
            AppendOutput($"  Selected probes: {string.Join(", ", analysisDlg.SelectedProbes)}");
        }
        catch (Exception ex)
        {
            AppendOutput($"JSON parse error: {ex.Message}");
            AppendOutput($"Raw output: {jsonOutput[..Math.Min(500, jsonOutput.Length)]}");
            SetStatus("Analysis parse error");
        }
    }

    private static string FindPythonExe()
    {
        string[] candidates = new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "Python", "Python312", "python.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "Python", "Python313", "python.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "Python", "Python311", "python.exe"),
        };
        foreach (var path in candidates)
            if (File.Exists(path)) return path;
        return "python";
    }

    // ------------------------------------------------------------------
    // Generic circuit: View in LTspice
    // ------------------------------------------------------------------

    private void ViewCircuitInLTspice()
    {
        if (_project is not GenericCircuitConfig genConfig || !genConfig.HasCircuit) return;

        string circuitPath = genConfig.CircuitPath;
        if (!File.Exists(circuitPath))
        {
            AppendOutput($"Circuit file not found: {circuitPath}");
            return;
        }

        // Find LTspice executable — prefer ADI version (has symbol libraries)
        string[] ltspicePaths = new[]
        {
            @"C:\Program Files\ADI\LTspice\LTspice.exe",
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "ADI", "LTspice", "LTspice.exe"),
            @"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe",
        };

        string? ltspice = ltspicePaths.FirstOrDefault(File.Exists);
        if (ltspice == null)
        {
            // Fallback: open with default association
            try
            {
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                {
                    FileName = circuitPath,
                    UseShellExecute = true,
                });
                AppendOutput($"Opened circuit: {circuitPath}");
            }
            catch (Exception ex)
            {
                AppendOutput($"Could not open circuit: {ex.Message}");
                MessageBox.Show($"Could not open {circuitPath}\n\nInstall LTspice to view circuit schematics.",
                    "View Circuit", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            return;
        }

        try
        {
            System.Diagnostics.Process.Start(ltspice, $"\"{circuitPath}\"");
            AppendOutput($"Opened in LTspice: {Path.GetFileName(circuitPath)}");
        }
        catch (Exception ex)
        {
            AppendOutput($"LTspice launch error: {ex.Message}");
        }
    }

    // ------------------------------------------------------------------
    // Generic circuit: Run simulation
    // ------------------------------------------------------------------

    private async Task RunGenericCircuitAsync(GenericCircuitConfig genConfig)
    {
        if (!genConfig.HasCircuit)
        {
            AppendOutput("No circuit loaded. Click 'Load Circuit' first.");
            SetStatus("No circuit loaded");
            return;
        }

        _btnRunSim.Text = "Cancel";
        _btnRunAll.Enabled = false;
        _btnLoadCircuit.Enabled = false;
        _btnExportCsv.Enabled = false;
        _btnToggleView.Enabled = false;
        _txtOutput.Clear();

        string args = genConfig.GetCommandArgs(0);
        AppendOutput($"Command: python kicad_pipeline.py {args}");
        AppendOutput($"Working dir: {SimulationRunner.RepoRoot}");
        SetStatus("Simulating...");

        try
        {
            await _simRunner.RunGenericAsync(args);
        }
        catch (Exception ex)
        {
            AppendOutput($"Simulation exception: {ex}");
            SetStatus("Simulation error");
        }

        _btnRunSim.Text = genConfig.RunSingleLabel;
        _btnRunAll.Enabled = true;
        _btnLoadCircuit.Enabled = true;

        // Parse results
        string metaPath = genConfig.GetResultsFilePath(0);
        string tranPath = Path.Combine(SimWorkDir, "generic_transient_results.txt");
        string acPath = Path.Combine(SimWorkDir, "generic_ac_bode_results.txt");

        AppendOutput($"Results meta: {(File.Exists(metaPath) ? "FOUND" : "MISSING")}");
        AppendOutput($"Transient data: {(File.Exists(tranPath) ? $"FOUND ({new FileInfo(tranPath).Length:N0} bytes)" : "MISSING")}");
        AppendOutput($"AC/Bode data: {(File.Exists(acPath) ? $"FOUND ({new FileInfo(acPath).Length:N0} bytes)" : "MISSING")}");

        if (File.Exists(metaPath))
        {
            try
            {
                AppendOutput("Parsing results...");
                var result = genConfig.ParseResults(metaPath, 0);

                if (result is GenericCircuitResult gcr)
                {
                    AppendOutput($"  Transient nodes: {gcr.TransientNodes.Count}");
                    AppendOutput($"  AC nodes: {gcr.AcNodes.Count}");
                    foreach (var tn in gcr.TransientNodes)
                        AppendOutput($"    {tn.NodeName}: {tn.Time.Length} pts, Vpp={tn.Vpp:F3}V, Status={tn.Status}");
                    foreach (var an in gcr.AcNodes)
                        AppendOutput($"    {an.NodeName}: {an.Frequency.Length} freq pts");

                    if (gcr.TransientNodes.Count == 0 && gcr.AcNodes.Count == 0)
                    {
                        AppendOutput("WARNING: No simulation data found in result files!");
                        AppendOutput($"  Check sim_work/ for generic_transient_results.txt and generic_ac_bode_results.txt");
                    }
                }

                // Rebuild grid
                _dataGrid.Columns.Clear();
                _dataGrid.Rows.Clear();
                foreach (var col in genConfig.CreateGridColumns())
                {
                    _dataGrid.Columns.Add(col);
                    if (col.Name != "Node" && col.Name != "Status")
                        col.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight;
                }
                genConfig.PopulateGrid(_dataGrid, result);

                // Render plot
                _formsPlot.Plot.Clear();
                genConfig.PlotSingle(_formsPlot.Plot, result);
                _formsPlot.Refresh();
                AppendOutput("Plot rendered.");

                genConfig.UpdateStatusBar(_statusLabels, result);
                genConfig.PrintReport(AppendOutput, result);
                _btnExportCsv.Enabled = true;

                _allResults.Clear();
                _allResults.Add(result);

                // Enable Bode toggle if AC data available
                _btnToggleView.Enabled = genConfig.HasAcData;

                SetStatus("Simulation complete");
            }
            catch (Exception ex)
            {
                SetStatus($"Parse error: {ex.Message}");
                AppendOutput($"Parse error: {ex.Message}");
                AppendOutput($"Stack: {ex.StackTrace}");
            }
        }
        else
        {
            SetStatus("Simulation failed - no results file");
            AppendOutput($"Results meta file not found: {metaPath}");
            if (File.Exists(tranPath))
                AppendOutput("  Transient data exists but meta JSON is missing. The Python script may have crashed.");
            AppendOutput("  Check output above for [ERR] messages from ngspice.");
        }
    }

    // ------------------------------------------------------------------
    // Toggle generic view (Transient / Bode)
    // ------------------------------------------------------------------

    private void ToggleGenericView()
    {
        if (_project is not GenericCircuitConfig genConfig || _allResults.Count == 0) return;

        // Toggle view mode
        genConfig.CurrentView = genConfig.CurrentView == GenericCircuitConfig.ViewMode.Transient
            ? GenericCircuitConfig.ViewMode.Bode
            : GenericCircuitConfig.ViewMode.Transient;

        _btnToggleView.Text = genConfig.CurrentView == GenericCircuitConfig.ViewMode.Transient
            ? "Bode View" : "Transient View";

        // Rebuild grid columns for new view
        _dataGrid.Columns.Clear();
        _dataGrid.Rows.Clear();
        foreach (var col in genConfig.CreateGridColumns())
        {
            _dataGrid.Columns.Add(col);
            if (col.Name != "Node" && col.Name != "Status")
                col.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight;
        }

        // Repopulate grid and replot
        if (_allResults[^1] is Models.GenericCircuitResult gcr)
        {
            genConfig.PopulateGrid(_dataGrid, gcr);
            _formsPlot.Plot.Clear();
            genConfig.PlotSingle(_formsPlot.Plot, gcr);
            _formsPlot.Refresh();
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
        _btnTogglePlot.Enabled = false;
        _showAmplitudePlot = false;
        _btnTogglePlot.Text = "Amplitude View";
        _btnToggleView.Enabled = false;
        _btnToggleView.Text = "Bode View";
        _project.ClearStatusBar(_statusLabels);
        SetStatus("Ready");
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    private void SetStatus(string text) => _lblToolStatus.Text = text;

    /// <summary>Apply common chart styling for better appearance.</summary>
    public static void StylePlot(ScottPlot.Plot plot)
    {
        // Background and data area
        plot.FigureBackground.Color = ScottPlot.Color.FromHex("#F0F4FA");
        plot.DataBackground.Color = ScottPlot.Colors.White;

        // Grid styling
        plot.Grid.MajorLineColor = ScottPlot.Color.FromHex("#D8E0EC");
        plot.Grid.MinorLineColor = ScottPlot.Color.FromHex("#ECF0F6");
        plot.Grid.MajorLineWidth = 1;

        // Axis styling
        plot.Axes.Bottom.Label.FontSize = 13;
        plot.Axes.Left.Label.FontSize = 13;
        plot.Axes.Bottom.TickLabelStyle.FontSize = 11;
        plot.Axes.Left.TickLabelStyle.FontSize = 11;
        plot.Axes.Bottom.MajorTickStyle.Length = 5;
        plot.Axes.Left.MajorTickStyle.Length = 5;

        // Legend styling
        plot.Legend.FontSize = 10;
        plot.Legend.OutlineColor = ScottPlot.Color.FromHex("#B0BED0");
    }

    private void AppendOutput(string text)
    {
        _txtOutput.AppendText($"[{DateTime.Now:HH:mm:ss}] {text}{Environment.NewLine}");
    }
}
