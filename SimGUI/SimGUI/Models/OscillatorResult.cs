namespace SimGUI.Models;

public class OscillatorPointData
{
    public int DacCode { get; set; }
    public double ExpectedFreqHz { get; set; }
    public double MeasuredFreqHz { get; set; }
    public double FreqErrorPercent { get; set; }
    public double BpVpp { get; set; }
    public double BpRms { get; set; }
    public double HpVpp { get; set; }
    public double LpVpp { get; set; }
    public string Status { get; set; } = "OK";
    public DateTime Timestamp { get; set; } = DateTime.Now;

    // Calibration simulation fields (populated after sweep)
    public bool IsCalibrated { get; set; }
    public double CalibratedFreqHz { get; set; }
    public double CalibratedFreqErrorPercent { get; set; }
    public double CalibratedRmsV { get; set; }
    public double FreqCorrectionFactor { get; set; } = 1.0;
    public double AmpCorrectionFactor { get; set; } = 1.0;
    public string CalibratedStatus { get; set; } = "";

    /// <summary>
    /// Format frequency for display (auto-scale Hz/kHz)
    /// </summary>
    public static string FormatFreq(double hz)
    {
        if (hz >= 1000) return $"{hz / 1000:F2} kHz";
        return $"{hz:F1} Hz";
    }
}
