using ScottPlot;

namespace SimGUI.Projects;

/// <summary>
/// Defines a project configuration for SimGUI.
/// Each project type (Electrometer, Oscillator, etc.) implements this interface
/// to provide project-specific grid columns, parsing, plotting, and sweep logic.
/// </summary>
public interface IProjectConfig
{
    string ProjectName { get; }
    string FormTitle { get; }

    // Toolbar
    string[] SweepPointNames { get; }
    string RunSingleLabel { get; }
    string RunAllLabel { get; }
    int DefaultSweepIndex { get; }
    int SweepCount { get; }

    // Runner
    string GetCommandArgs(int sweepIndex);
    string GetResultsFilePath(int sweepIndex);

    // Grid
    DataGridViewColumn[] CreateGridColumns();
    void PopulateGrid(DataGridView grid, object result);
    void StyleGridRow(DataGridView grid, int rowIdx, string status);

    // Parser
    object ParseResults(string filePath, int sweepIndex);

    // Plot
    void PlotSingle(Plot plot, object result);
    void PlotAll(Plot plot, List<object> results);

    // Status bar
    void UpdateStatusBar(ToolStripStatusLabel[] labels, object result);
    void UpdateStatusBarMulti(ToolStripStatusLabel[] labels, List<object> results);
    void ClearStatusBar(ToolStripStatusLabel[] labels);
    string[] StatusBarLabels { get; }

    // Report
    void PrintReport(Action<string> appendOutput, object result);

    // CSV export
    void ExportCsv(string filePath, List<object> results);

    // Plot setup
    void SetupPlot(Plot plot);
}
