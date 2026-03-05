namespace SimGUI.Models;

public class ChannelData
{
    public int Channel { get; set; }
    public int RangeIndex { get; set; }           // TIA range (0-8)

    // Injected (known) values from simulation netlist - stored in Amps
    public double InjectedA { get; set; }
    public double RDutMOhm { get; set; }

    // Measured values from TIA output - stored in Amps
    public double MeasuredA { get; set; }
    public double VtiaMv { get; set; }
    public double VchInputMv { get; set; }

    // Verification
    public double ExpectedVtiaMv { get; set; }
    public double ErrorPercent { get; set; }
    public double DeltaA { get; set; }            // Absolute difference in Amps
    public int AdcCounts { get; set; }
    public double AdcLsb { get; set; }

    // Timing
    public double WindowStartS { get; set; }
    public double WindowEndS { get; set; }
    public double SampleTimeS { get; set; }

    public double Temperature { get; set; }
    public string Status { get; set; } = "OK";

    // Per-channel waveform segment (for coloured plot)
    public double[] SegmentTimes { get; set; } = Array.Empty<double>();
    public double[] SegmentCurrentsScaled { get; set; } = Array.Empty<double>();

    // ---- Auto-scaled display properties ----
    public string InjectedDisplay => FormatCurrent(InjectedA);
    public string MeasuredDisplay => FormatCurrent(MeasuredA);
    public string DeltaDisplay => FormatCurrent(DeltaA);
    public string UnitLabel => GetUnitLabel(InjectedA);
    public double InjectedScaled => ScaleCurrent(InjectedA);
    public double MeasuredScaled => ScaleCurrent(MeasuredA);
    public double DeltaScaled => ScaleCurrent(DeltaA);

    public static string FormatCurrent(double amps)
    {
        double a = Math.Abs(amps);
        if (a >= 1e-3)  return $"{amps * 1e3:F4} mA";
        if (a >= 1e-6)  return $"{amps * 1e6:F4} µA";
        if (a >= 1e-9)  return $"{amps * 1e9:F4} nA";
        if (a >= 1e-12) return $"{amps * 1e12:F3} pA";
        return $"{amps * 1e15:F1} fA";
    }

    public static string GetUnitLabel(double amps)
    {
        double a = Math.Abs(amps);
        if (a >= 1e-3) return "mA";
        if (a >= 1e-6) return "µA";
        if (a >= 1e-9) return "nA";
        if (a >= 1e-12) return "pA";
        return "fA";
    }

    public static double ScaleCurrent(double amps)
    {
        double a = Math.Abs(amps);
        if (a >= 1e-3) return amps * 1e3;
        if (a >= 1e-6) return amps * 1e6;
        if (a >= 1e-9) return amps * 1e9;
        if (a >= 1e-12) return amps * 1e12;
        return amps * 1e15;
    }

    public static double GetScaleMultiplier(double amps)
    {
        double a = Math.Abs(amps);
        if (a >= 1e-3) return 1e3;
        if (a >= 1e-6) return 1e6;
        if (a >= 1e-9) return 1e9;
        if (a >= 1e-12) return 1e12;
        return 1e15;
    }
}
