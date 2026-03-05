namespace SimGUI.Models;

public class SimulationResult
{
    public List<ChannelData> Channels { get; set; } = new();
    public double[] TimePoints { get; set; } = Array.Empty<double>();
    public double[] TiaOutput { get; set; } = Array.Empty<double>();
    public double SimulationTimeSeconds { get; set; }
    public DateTime Timestamp { get; set; } = DateTime.Now;
    public string ResultsFilePath { get; set; } = "";

    // Simulation parameters
    public int RangeIndex { get; set; } = 2;
    public double RfOhm { get; set; } = 1e9;
    public double ChannelPeriodS { get; set; } = 0.200;
    public int NumChannels { get; set; } = 16;
    public double AdcRefV { get; set; } = 2.5;
    public int AdcBits { get; set; } = 24;

    public string RangeName => RangeIndex switch
    {
        0 => "Range 0: Rf=100 (mA)",
        1 => "Range 1: Rf=1k (mA)",
        2 => "Range 2: Rf=10k (µA)",
        3 => "Range 3: Rf=100k (µA)",
        4 => "Range 4: Rf=1M (µA)",
        5 => "Range 5: Rf=10M (nA)",
        6 => "Range 6: Rf=100M (nA)",
        7 => "Range 7: Rf=1G (sub-nA)",
        8 => "Range 8: Rf=10G (fA)",
        _ => $"Range {RangeIndex}",
    };

    public string RfDisplay => RfOhm switch
    {
        >= 1e9 => $"{RfOhm / 1e9:F0}G",
        >= 1e6 => $"{RfOhm / 1e6:F0}M",
        >= 1e3 => $"{RfOhm / 1e3:F0}k",
        _ => $"{RfOhm:F0}",
    };

    public string CurrentUnit => Channels.Count > 0
        ? ChannelData.GetUnitLabel(Channels[0].InjectedA)
        : "nA";

    public double AverageErrorPercent =>
        Channels.Count > 0 ? Channels.Average(c => c.ErrorPercent) : 0;

    public double MaxErrorPercent =>
        Channels.Count > 0 ? Channels.Max(c => c.ErrorPercent) : 0;

    public int PassCount => Channels.Count(c => c.Status == "PASS");
    public int WarnCount => Channels.Count(c => c.Status == "WARN");
    public int FailCount => Channels.Count(c => c.Status == "FAIL");
}
