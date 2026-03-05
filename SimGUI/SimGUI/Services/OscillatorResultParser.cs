using System.Globalization;
using System.Text.RegularExpressions;
using SimGUI.Models;

namespace SimGUI.Services;

public static class OscillatorResultParser
{
    private static readonly Regex ValuePattern = new(
        @"^\s*(\w+)\s*=\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)",
        RegexOptions.Compiled);

    /// <summary>
    /// Parse oscillator results file (key = value format from ngspice .control echo).
    /// Expected keys: freq, bp_pp, bp_rms, hp_pp, lp_pp
    /// </summary>
    public static OscillatorPointData Parse(string filePath, int dacCode, double expectedHz)
    {
        var values = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);

        foreach (var line in File.ReadAllLines(filePath))
        {
            var match = ValuePattern.Match(line);
            if (match.Success)
            {
                string key = match.Groups[1].Value;
                if (double.TryParse(match.Groups[2].Value,
                    NumberStyles.Float, CultureInfo.InvariantCulture, out double val))
                    values[key] = val;
            }
        }

        double freq = values.GetValueOrDefault("freq", 0);
        double bp_pp = values.GetValueOrDefault("bp_pp", 0);
        double bp_rms = values.GetValueOrDefault("bp_rms", 0);
        double hp_pp = values.GetValueOrDefault("hp_pp", 0);
        double lp_pp = values.GetValueOrDefault("lp_pp", 0);

        double freqErr = expectedHz > 0 ? Math.Abs(freq - expectedHz) / expectedHz * 100 : 0;

        string status = freqErr switch
        {
            < 5 => "PASS",
            < 15 => "WARN",
            _ => "FAIL"
        };

        // Also fail if no oscillation detected
        if (bp_pp < 0.01) status = "FAIL";

        return new OscillatorPointData
        {
            DacCode = dacCode,
            ExpectedFreqHz = expectedHz,
            MeasuredFreqHz = freq,
            FreqErrorPercent = freqErr,
            BpVpp = bp_pp,
            BpRms = bp_rms,
            HpVpp = hp_pp,
            LpVpp = lp_pp,
            Status = status,
        };
    }
}
