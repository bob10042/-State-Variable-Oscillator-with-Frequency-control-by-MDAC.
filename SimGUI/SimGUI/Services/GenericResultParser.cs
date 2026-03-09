using System.Globalization;
using System.Text.Json;
using SimGUI.Models;

namespace SimGUI.Services;

/// <summary>
/// Parses generic circuit simulation results from wrdata + JSON metadata.
/// </summary>
public static class GenericResultParser
{
    public static GenericCircuitResult Parse(string simWorkDir, string[] probeNodes)
    {
        var result = new GenericCircuitResult { ProbedNodes = probeNodes };

        // Read metadata JSON
        string metaPath = Path.Combine(simWorkDir, "generic_sim_meta.json");
        Dictionary<string, JsonElement>? tranMeasurements = null;

        if (File.Exists(metaPath))
        {
            string json = File.ReadAllText(metaPath);
            var meta = JsonSerializer.Deserialize<JsonElement>(json);

            if (meta.TryGetProperty("circuit_path", out var cp))
                result.CircuitPath = cp.GetString() ?? "";
            if (meta.TryGetProperty("all_nodes", out var an))
                result.AllNodes = an.EnumerateArray().Select(e => e.GetString() ?? "").ToArray();
            if (meta.TryGetProperty("probe_nodes", out var pn))
                result.ProbedNodes = pn.EnumerateArray().Select(e => e.GetString() ?? "").ToArray();
            if (meta.TryGetProperty("analyses_run", out var ar))
                result.AnalysesRun = ar.EnumerateArray().Select(e => e.GetString() ?? "").ToArray();

            // Transient measurements
            if (meta.TryGetProperty("transient", out var tran) &&
                tran.TryGetProperty("measurements", out var meas))
            {
                tranMeasurements = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(
                    meas.GetRawText());

                // Extract gain if available
                if (tranMeasurements != null)
                {
                    if (tranMeasurements.TryGetValue("_gain", out var g) && g.ValueKind == JsonValueKind.Number)
                        result.Gain = g.GetDouble();
                    if (tranMeasurements.TryGetValue("_gain_dB", out var gdb) && gdb.ValueKind == JsonValueKind.Number)
                        result.GainDb = gdb.GetDouble();
                }
            }
        }

        result.CircuitName = Path.GetFileNameWithoutExtension(result.CircuitPath);

        // Parse transient results
        string tranPath = Path.Combine(simWorkDir, "generic_transient_results.txt");
        if (File.Exists(tranPath))
        {
            result.TransientNodes = ParseWrdata(tranPath, result.ProbedNodes, tranMeasurements);
        }

        // Parse AC/Bode results (format: freq, vdb, freq, vp pairs per node)
        string acPath = Path.Combine(simWorkDir, "generic_ac_bode_results.txt");
        if (File.Exists(acPath))
        {
            result.AcNodes = ParseAcData(acPath, result.ProbedNodes);
        }

        return result;
    }

    private static List<GenericNodeResult> ParseWrdata(string path, string[] probeNodes,
        Dictionary<string, JsonElement>? measurements)
    {
        var nodes = new List<GenericNodeResult>();
        var timeArrays = new List<List<double>>();
        var valArrays = new List<List<double>>();

        for (int i = 0; i < probeNodes.Length; i++)
        {
            timeArrays.Add(new List<double>());
            valArrays.Add(new List<double>());
        }

        foreach (var line in File.ReadAllLines(path))
        {
            var trimmed = line.Trim();
            if (string.IsNullOrEmpty(trimmed)) continue;
            var parts = trimmed.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 2) continue;

            for (int i = 0; i < probeNodes.Length && (i * 2 + 1) < parts.Length; i++)
            {
                if (double.TryParse(parts[i * 2], NumberStyles.Float,
                        CultureInfo.InvariantCulture, out double t) &&
                    double.TryParse(parts[i * 2 + 1], NumberStyles.Float,
                        CultureInfo.InvariantCulture, out double v))
                {
                    timeArrays[i].Add(t);
                    valArrays[i].Add(v);
                }
            }
        }

        for (int i = 0; i < probeNodes.Length; i++)
        {
            var node = new GenericNodeResult
            {
                NodeName = probeNodes[i],
                Time = timeArrays[i].ToArray(),
                Voltage = valArrays[i].ToArray(),
            };

            // Pull measurements from JSON
            if (measurements != null && measurements.TryGetValue(probeNodes[i], out var m)
                && m.ValueKind == JsonValueKind.Object)
            {
                node.Vpp = GetDouble(m, "vpp");
                node.Vdc = GetDouble(m, "vdc");
                node.Vrms = GetDouble(m, "vrms");
                node.Vmin = GetDouble(m, "vmin");
                node.Vmax = GetDouble(m, "vmax");
                node.FreqHz = GetDouble(m, "freq_hz");
            }
            else if (node.Voltage.Length > 0)
            {
                node.Vpp = node.Voltage.Max() - node.Voltage.Min();
                node.Vdc = node.Voltage.Average();
                node.Vrms = Math.Sqrt(node.Voltage.Select(v => v * v).Average());
                node.Vmin = node.Voltage.Min();
                node.Vmax = node.Voltage.Max();
            }

            nodes.Add(node);
        }

        return nodes;
    }

    private static List<GenericNodeResult> ParseAcData(string path, string[] probeNodes)
    {
        var nodes = new List<GenericNodeResult>();

        // AC wrdata: for each node, 2 variables: vdb(N) and vp(N)
        // So for N nodes: freq, vdb0, freq, vp0, freq, vdb1, freq, vp1...
        // = 4 columns per node
        var freqArrays = new List<List<double>>();
        var magArrays = new List<List<double>>();
        var phaseArrays = new List<List<double>>();

        for (int i = 0; i < probeNodes.Length; i++)
        {
            freqArrays.Add(new List<double>());
            magArrays.Add(new List<double>());
            phaseArrays.Add(new List<double>());
        }

        foreach (var line in File.ReadAllLines(path))
        {
            var trimmed = line.Trim();
            if (string.IsNullOrEmpty(trimmed)) continue;
            var parts = trimmed.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 4) continue;

            for (int i = 0; i < probeNodes.Length; i++)
            {
                int magCol = i * 4;      // freq for vdb
                int magValCol = i * 4 + 1; // vdb value
                int phaseCol = i * 4 + 2;  // freq for vp (same freq)
                int phaseValCol = i * 4 + 3; // vp value

                if (phaseValCol >= parts.Length) break;

                if (double.TryParse(parts[magCol], NumberStyles.Float,
                        CultureInfo.InvariantCulture, out double freq) &&
                    double.TryParse(parts[magValCol], NumberStyles.Float,
                        CultureInfo.InvariantCulture, out double mag) &&
                    double.TryParse(parts[phaseValCol], NumberStyles.Float,
                        CultureInfo.InvariantCulture, out double phase))
                {
                    freqArrays[i].Add(freq);
                    magArrays[i].Add(mag);
                    phaseArrays[i].Add(phase);
                }
            }
        }

        for (int i = 0; i < probeNodes.Length; i++)
        {
            nodes.Add(new GenericNodeResult
            {
                NodeName = probeNodes[i],
                Frequency = freqArrays[i].ToArray(),
                MagnitudeDb = magArrays[i].ToArray(),
                PhaseDeg = phaseArrays[i].ToArray(),
            });
        }

        return nodes;
    }

    private static double GetDouble(JsonElement el, string prop)
    {
        if (el.TryGetProperty(prop, out var val) && val.TryGetDouble(out double d))
            return d;
        return 0;
    }
}
