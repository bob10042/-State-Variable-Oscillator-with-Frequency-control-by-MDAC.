namespace SimGUI.Models;

/// <summary>
/// Holds simulation result for one probe node in a generic circuit.
/// </summary>
public class GenericNodeResult
{
    public string NodeName { get; set; } = "";

    // Transient data
    public double[] Time { get; set; } = Array.Empty<double>();
    public double[] Voltage { get; set; } = Array.Empty<double>();

    // AC/Bode data
    public double[] Frequency { get; set; } = Array.Empty<double>();
    public double[] MagnitudeDb { get; set; } = Array.Empty<double>();
    public double[] PhaseDeg { get; set; } = Array.Empty<double>();

    // Measurements
    public double Vpp { get; set; }
    public double Vdc { get; set; }
    public double Vrms { get; set; }
    public double Vmin { get; set; }
    public double Vmax { get; set; }
    public double FreqHz { get; set; }

    public string Status => Vpp > 0.001 ? "OK" : "FLAT";
}

/// <summary>
/// Suggested analysis from the Python circuit analyzer.
/// </summary>
public class SuggestedAnalysis
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public string SimCmd { get; set; } = "";
    public string[] DefaultProbes { get; set; } = Array.Empty<string>();
    public bool EnabledByDefault { get; set; }
}

/// <summary>
/// Complete generic circuit simulation result: all probed nodes + metadata.
/// </summary>
public class GenericCircuitResult
{
    public string CircuitPath { get; set; } = "";
    public string CircuitName { get; set; } = "";
    public string CircuitType { get; set; } = "";
    public string SimCommand { get; set; } = "";
    public DateTime Timestamp { get; set; } = DateTime.Now;

    // Node classification
    public string[] AllNodes { get; set; } = Array.Empty<string>();
    public string[] InputNodes { get; set; } = Array.Empty<string>();
    public string[] OutputNodes { get; set; } = Array.Empty<string>();
    public string[] PowerNodes { get; set; } = Array.Empty<string>();

    // Suggested analyses
    public List<SuggestedAnalysis> SuggestedAnalyses { get; set; } = new();

    // Probe results
    public string[] ProbedNodes { get; set; } = Array.Empty<string>();
    public List<GenericNodeResult> TransientNodes { get; set; } = new();
    public List<GenericNodeResult> AcNodes { get; set; } = new();
    public string[] AnalysesRun { get; set; } = Array.Empty<string>();

    // Key measurements
    public double Gain { get; set; }
    public double GainDb { get; set; }
}
