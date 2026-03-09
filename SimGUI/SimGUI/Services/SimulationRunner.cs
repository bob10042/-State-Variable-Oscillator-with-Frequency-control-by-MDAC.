using System.Diagnostics;

namespace SimGUI.Services;

public class SimulationRunner
{
    public event Action<string>? OutputReceived;
    public event Action<bool, string>? SimulationComplete;
    public event Action<int, bool, string>? RangeComplete;  // range, success, message

    private readonly string _pythonScript;
    private readonly string _workingDir;
    private Process? _process;
    private bool _cancelRequested;

    public bool IsRunning => _process != null && !_process.HasExited;

    public static readonly Dictionary<int, string> RangeNames = new()
    {
        { 0, "Range 0: Rf=100 (mA)" },
        { 1, "Range 1: Rf=1k (mA)" },
        { 2, "Range 2: Rf=10k (µA)" },
        { 3, "Range 3: Rf=100k (µA)" },
        { 4, "Range 4: Rf=1M (µA)" },
        { 5, "Range 5: Rf=10M (nA)" },
        { 6, "Range 6: Rf=100M (nA)" },
        { 7, "Range 7: Rf=1G (sub-nA)" },
        { 8, "Range 8: Rf=10G (fA)" },
    };

    public static readonly Dictionary<int, string> RangeShortNames = new()
    {
        { 0, "100" }, { 1, "1k" }, { 2, "10k" }, { 3, "100k" },
        { 4, "1M" }, { 5, "10M" }, { 6, "100M" }, { 7, "1G" }, { 8, "10G" },
    };

    private readonly string _pythonExe;

    public SimulationRunner()
    {
        // Derive repo root: SimGUI.exe is in SimGUI/SimGUI/bin/…, repo root is 4 levels up
        // Fallback: walk up from current directory looking for kicad_pipeline.py
        _workingDir = FindRepoRoot();
        _pythonScript = Path.Combine(_workingDir, "kicad_pipeline.py");
        _pythonExe = FindPython();
    }

    private static string? _cachedRepoRoot;

    /// <summary>Repo root path (resolved once at startup, cached).</summary>
    public static string RepoRoot => _cachedRepoRoot ??= FindRepoRoot();

    private static string FindPython()
    {
        // Prefer Python312 with numpy/py7zr installed (avoids msys64 python)
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
        {
            if (File.Exists(path)) return path;
        }
        // Fallback to PATH (may pick up wrong python)
        return "python";
    }

    private static string FindRepoRoot()
    {
        // Try relative to the executable location (works from bin/Debug/net8.0/)
        string? exeDir = Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
        if (exeDir != null)
        {
            // Walk up looking for kicad_pipeline.py
            string dir = exeDir;
            for (int i = 0; i < 8; i++)
            {
                if (File.Exists(Path.Combine(dir, "kicad_pipeline.py")))
                    return dir;
                string? parent = Path.GetDirectoryName(dir);
                if (parent == null || parent == dir) break;
                dir = parent;
            }
        }
        // Try current working directory and walk up
        string cwd = Directory.GetCurrentDirectory();
        for (int i = 0; i < 8; i++)
        {
            if (File.Exists(Path.Combine(cwd, "kicad_pipeline.py")))
                return cwd;
            string? parent = Path.GetDirectoryName(cwd);
            if (parent == null || parent == cwd) break;
            cwd = parent;
        }
        // Last resort: current directory
        return Directory.GetCurrentDirectory();
    }

    /// <summary>
    /// Run with generic arguments string (used by IProjectConfig).
    /// </summary>
    public async Task RunGenericAsync(string arguments)
    {
        if (IsRunning)
        {
            OutputReceived?.Invoke("Simulation already running.");
            return;
        }

        var psi = new ProcessStartInfo
        {
            FileName = _pythonExe,
            Arguments = $"\"{_pythonScript}\" {arguments}",
            WorkingDirectory = _workingDir,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };

        try
        {
            OutputReceived?.Invoke($"Starting: python kicad_pipeline.py {arguments}");
            _process = Process.Start(psi);
            if (_process == null)
            {
                SimulationComplete?.Invoke(false, "Failed to start process");
                return;
            }

            _process.OutputDataReceived += (_, e) =>
            {
                if (e.Data != null) OutputReceived?.Invoke(e.Data);
            };
            _process.ErrorDataReceived += (_, e) =>
            {
                if (e.Data != null) OutputReceived?.Invoke($"[ERR] {e.Data}");
            };

            _process.BeginOutputReadLine();
            _process.BeginErrorReadLine();

            await _process.WaitForExitAsync();
            int exitCode = _process.ExitCode;
            _process = null;

            if (exitCode == 0)
                SimulationComplete?.Invoke(true, "Simulation completed");
            else
                SimulationComplete?.Invoke(false, $"Simulation failed (exit code {exitCode})");
        }
        catch (Exception ex)
        {
            _process = null;
            SimulationComplete?.Invoke(false, $"Error: {ex.Message}");
        }
    }

    public async Task RunAsync(string circuit = "channel_switch", int range = 7)
    {
        if (IsRunning)
        {
            OutputReceived?.Invoke("Simulation already running.");
            return;
        }

        var psi = new ProcessStartInfo
        {
            FileName = _pythonExe,
            Arguments = $"\"{_pythonScript}\" {circuit} LMC6001 {range}",
            WorkingDirectory = _workingDir,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };

        try
        {
            OutputReceived?.Invoke($"Starting simulation: {circuit} range {range} ({RangeShortNames.GetValueOrDefault(range, "?")})");
            _process = Process.Start(psi);
            if (_process == null)
            {
                SimulationComplete?.Invoke(false, "Failed to start process");
                return;
            }

            _process.OutputDataReceived += (_, e) =>
            {
                if (e.Data != null) OutputReceived?.Invoke(e.Data);
            };
            _process.ErrorDataReceived += (_, e) =>
            {
                if (e.Data != null) OutputReceived?.Invoke($"[ERR] {e.Data}");
            };

            _process.BeginOutputReadLine();
            _process.BeginErrorReadLine();

            await _process.WaitForExitAsync();
            int exitCode = _process.ExitCode;
            _process = null;

            if (exitCode == 0)
                SimulationComplete?.Invoke(true, $"Range {range} simulation completed");
            else
                SimulationComplete?.Invoke(false, $"Range {range} simulation failed (exit code {exitCode})");
        }
        catch (Exception ex)
        {
            _process = null;
            SimulationComplete?.Invoke(false, $"Error: {ex.Message}");
        }
    }

    public async Task RunAllRangesAsync()
    {
        _cancelRequested = false;

        for (int range = 0; range <= 8; range++)
        {
            if (_cancelRequested) break;

            OutputReceived?.Invoke($"\n{'='} RANGE {range}: Rf={RangeShortNames[range]} {'='}");
            await RunAsync("channel_switch", range);

            string resultsPath = GetResultsFilePath(range);
            bool success = File.Exists(resultsPath);
            RangeComplete?.Invoke(range, success, resultsPath);

            if (!success)
                OutputReceived?.Invoke($"WARNING: Range {range} results file not found at {resultsPath}");
        }
    }

    public void Cancel()
    {
        _cancelRequested = true;
        if (_process != null && !_process.HasExited)
        {
            try
            {
                _process.Kill(entireProcessTree: true);
                OutputReceived?.Invoke("Simulation cancelled.");
            }
            catch { }
            _process = null;
        }
    }

    public string GetResultsFilePath(int range = 7)
    {
        return Path.Combine(_workingDir, "sim_work", $"channel_switching_range{range}_results.txt");
    }
}
