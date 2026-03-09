namespace SimGUI.Models;

/// <summary>
/// Holds paired comparison data for MDAC vs Analog oscillator at one frequency point.
/// Built from two OscillatorPointData results (one per design) at the same target frequency.
/// </summary>
public class ComparisonPointData
{
    // Frequency point identity
    public int SweepIndex { get; set; }
    public int DacCode { get; set; }
    public double TargetFreqHz { get; set; }

    // MDAC design results
    public double MdacFreqHz { get; set; }
    public double MdacFreqErrorPercent { get; set; }
    public double MdacBpVpp { get; set; }
    public double MdacBpRms { get; set; }
    public double MdacHpVpp { get; set; }
    public double MdacLpVpp { get; set; }
    public string MdacStatus { get; set; } = "";

    // Analog (friend's) design results
    public double AnalogFreqHz { get; set; }
    public double AnalogFreqErrorPercent { get; set; }
    public double AnalogBpVpp { get; set; }
    public double AnalogBpRms { get; set; }
    public double AnalogHpVpp { get; set; }
    public double AnalogLpVpp { get; set; }
    public string AnalogStatus { get; set; } = "";

    // Computed deltas
    public double FreqDeltaHz => MdacFreqHz - AnalogFreqHz;
    public double RmsDeltaV => MdacBpRms - AnalogBpRms;
    public double VppDeltaV => MdacBpVpp - AnalogBpVpp;

    /// <summary>Which design has lower frequency error at this point.</summary>
    public string Winner => MdacFreqErrorPercent <= AnalogFreqErrorPercent ? "MDAC" : "Analog";

    public DateTime Timestamp { get; set; } = DateTime.Now;
}
