using System.Globalization;
using SimGUI.Models;

namespace SimGUI.Services;

public static class ResultParser
{
    // Per-range feedback resistors (9 ranges: 100/1k/10k/100k/1M/10M/100M/1G/10G)
    public static readonly Dictionary<int, double> RangeRf = new()
    {
        { 0, 100 }, { 1, 1e3 }, { 2, 10e3 }, { 3, 100e3 },
        { 4, 1e6 }, { 5, 10e6 }, { 6, 100e6 }, { 7, 1e9 }, { 8, 10e9 },
    };

    // Per-range injected channel currents (A) - MUST match kicad_pipeline.py RANGE_CURRENTS
    public static readonly Dictionary<int, Dictionary<int, double>> RangeCurrentsA = new()
    {
        { 0, new() { // Rf=100: mA range (0.5-10 mA)
            {1, 1.0e-3},   {2, 2.5e-3},   {3, 5.0e-3},   {4, 10.0e-3},
            {5, 7.5e-3},   {6, 3.0e-3},   {7, 1.5e-3},   {8, 8.0e-3},
            {9, 0.5e-3},  {10, 4.0e-3},  {11, 6.0e-3},  {12, 2.0e-3},
           {13, 9.0e-3},  {14, 3.5e-3},  {15, 5.5e-3},  {16, 1.2e-3},
        }},
        { 1, new() { // Rf=1k: sub-mA range (0.2-4 mA)
            {1, 0.4e-3},   {2, 1.0e-3},   {3, 2.0e-3},   {4, 4.0e-3},
            {5, 3.0e-3},   {6, 1.2e-3},   {7, 0.6e-3},   {8, 3.2e-3},
            {9, 0.2e-3},  {10, 1.6e-3},  {11, 2.4e-3},  {12, 0.8e-3},
           {13, 3.6e-3},  {14, 1.4e-3},  {15, 2.2e-3},  {16, 0.48e-3},
        }},
        { 2, new() { // Rf=10k: 100-µA range (20-400 µA)
            {1, 40e-6},    {2, 100e-6},   {3, 200e-6},   {4, 400e-6},
            {5, 300e-6},   {6, 120e-6},   {7, 60e-6},    {8, 320e-6},
            {9, 20e-6},   {10, 160e-6},  {11, 240e-6},  {12, 80e-6},
           {13, 360e-6},  {14, 140e-6},  {15, 220e-6},  {16, 48e-6},
        }},
        { 3, new() { // Rf=100k: 10-µA range (2-40 µA)
            {1, 4.0e-6},   {2, 10.0e-6},   {3, 20.0e-6},   {4, 40.0e-6},
            {5, 30.0e-6},   {6, 12.0e-6},   {7, 6.0e-6},    {8, 32.0e-6},
            {9, 2.0e-6},   {10, 16.0e-6},  {11, 24.0e-6},  {12, 8.0e-6},
           {13, 36.0e-6},  {14, 14.0e-6},  {15, 22.0e-6},  {16, 4.8e-6},
        }},
        { 4, new() { // Rf=1M: µA range (0.2-4 µA)
            {1, 0.4e-6},   {2, 1.0e-6},   {3, 2.0e-6},   {4, 4.0e-6},
            {5, 3.0e-6},   {6, 1.2e-6},   {7, 0.6e-6},   {8, 3.2e-6},
            {9, 0.2e-6},  {10, 1.6e-6},  {11, 2.4e-6},  {12, 0.8e-6},
           {13, 3.6e-6},  {14, 1.4e-6},  {15, 2.2e-6},  {16, 0.48e-6},
        }},
        { 5, new() { // Rf=10M: high-nA range (20-400 nA)
            {1, 40e-9},    {2, 100e-9},   {3, 200e-9},   {4, 400e-9},
            {5, 300e-9},   {6, 120e-9},   {7, 60e-9},    {8, 320e-9},
            {9, 20e-9},   {10, 160e-9},  {11, 240e-9},  {12, 80e-9},
           {13, 360e-9},  {14, 140e-9},  {15, 220e-9},  {16, 48e-9},
        }},
        { 6, new() { // Rf=100M: nanoamp range (2-40 nA)
            {1, 4.0e-9},   {2, 10.0e-9},   {3, 20.0e-9},   {4, 40.0e-9},
            {5, 30.0e-9},   {6, 12.0e-9},   {7, 6.0e-9},    {8, 32.0e-9},
            {9, 2.0e-9},   {10, 16.0e-9},  {11, 24.0e-9},  {12, 8.0e-9},
           {13, 36.0e-9},  {14, 14.0e-9},  {15, 22.0e-9},  {16, 4.8e-9},
        }},
        { 7, new() { // Rf=1G: sub-nanoamp range (0.05-1 nA)
            {1, 0.10e-9},   {2, 0.25e-9},   {3, 0.50e-9},   {4, 1.00e-9},
            {5, 0.75e-9},   {6, 0.30e-9},   {7, 0.15e-9},   {8, 0.80e-9},
            {9, 0.05e-9},  {10, 0.40e-9},  {11, 0.60e-9},  {12, 0.20e-9},
           {13, 0.90e-9},  {14, 0.35e-9},  {15, 0.55e-9},  {16, 0.12e-9},
        }},
        { 8, new() { // Rf=10G: femtoamp range (50-1000 fA)
            {1, 100e-15},   {2, 250e-15},   {3, 500e-15},   {4, 1000e-15},
            {5, 750e-15},   {6, 300e-15},   {7, 150e-15},   {8, 800e-15},
            {9, 50e-15},   {10, 400e-15},  {11, 600e-15},  {12, 200e-15},
           {13, 900e-15},  {14, 350e-15},  {15, 550e-15},  {16, 120e-15},
        }},
    };

    private const double RDut = 100e6;
    private const double ChannelPeriod = 0.200;
    private const int NumChannels = 16;
    private const double AdcRefV = 2.5;
    private const int AdcBits = 24;

    public static SimulationResult Parse(string filePath, int rangeIndex = -1)
    {
        // Auto-detect range from filename if not specified
        if (rangeIndex < 0)
        {
            rangeIndex = DetectRangeFromPath(filePath);
        }

        double Rf = RangeRf.GetValueOrDefault(rangeIndex, 1e9);
        var injectedCurrents = RangeCurrentsA.GetValueOrDefault(rangeIndex, RangeCurrentsA[7]);

        var result = new SimulationResult
        {
            ResultsFilePath = filePath,
            Timestamp = DateTime.Now,
            RangeIndex = rangeIndex,
            RfOhm = Rf,
            ChannelPeriodS = ChannelPeriod,
            NumChannels = NumChannels,
            AdcRefV = AdcRefV,
            AdcBits = AdcBits,
        };

        if (!File.Exists(filePath))
            throw new FileNotFoundException("Results file not found", filePath);

        var timeList = new List<double>();
        var tiaList = new List<double>();
        var chInputs = new List<double>[NumChannels];
        for (int i = 0; i < NumChannels; i++)
            chInputs[i] = new List<double>();

        using var reader = new StreamReader(filePath);
        string? line;
        while ((line = reader.ReadLine()) != null)
        {
            line = line.Trim();
            if (string.IsNullOrEmpty(line)) continue;

            var parts = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 36) continue;

            if (!double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out double t))
                continue;

            if (!double.TryParse(parts[33], NumberStyles.Float, CultureInfo.InvariantCulture, out double vTia))
                continue;

            timeList.Add(t);
            tiaList.Add(vTia);

            for (int ch = 0; ch < NumChannels; ch++)
            {
                int colIdx = ch * 2 + 1;
                if (double.TryParse(parts[colIdx], NumberStyles.Float, CultureInfo.InvariantCulture, out double vCh))
                    chInputs[ch].Add(vCh);
                else
                    chInputs[ch].Add(0);
            }
        }

        result.TimePoints = timeList.ToArray();
        result.TiaOutput = tiaList.ToArray();

        if (timeList.Count > 0)
            result.SimulationTimeSeconds = timeList[^1];

        double adcLsb = AdcRefV / Math.Pow(2, AdcBits);

        // Determine current scale for waveform display
        double refCurrent = injectedCurrents.GetValueOrDefault(1, 1e-9);
        double scaleMult = ChannelData.GetScaleMultiplier(refCurrent);

        for (int ch = 1; ch <= NumChannels; ch++)
        {
            double windowStart = (ch - 1) * ChannelPeriod;
            double windowEnd = ch * ChannelPeriod;
            double sampleTime = windowStart + ChannelPeriod * 0.80;

            double vTiaSteady = InterpolateAt(timeList, tiaList, sampleTime);
            double measuredCurrentA = -vTiaSteady / Rf;

            double vChInput = InterpolateAt(timeList, chInputs[ch - 1], sampleTime);

            double injectedA = injectedCurrents.GetValueOrDefault(ch, 0);
            double expectedVtia = -injectedA * Rf;

            double errorPct = injectedA != 0
                ? Math.Abs((measuredCurrentA - injectedA) / injectedA) * 100.0
                : 0;
            double deltaA = measuredCurrentA - injectedA;
            int adcCounts = (int)Math.Round(Math.Abs(vTiaSteady) / adcLsb);
            double signalLsbs = Math.Abs(vTiaSteady) / adcLsb;

            string status = errorPct switch
            {
                < 5.0 => "PASS",
                < 20.0 => "WARN",
                _ => "FAIL"
            };

            // Extract waveform segment for this channel's time window (scaled to display unit)
            var segTimes = new List<double>();
            var segCurrents = new List<double>();
            int step = Math.Max(1, timeList.Count / 10000);
            for (int i = 0; i < timeList.Count; i += step)
            {
                if (timeList[i] >= windowStart && timeList[i] <= windowEnd)
                {
                    segTimes.Add(timeList[i]);
                    segCurrents.Add(-tiaList[i] / Rf * scaleMult);  // scaled to display unit
                }
            }

            result.Channels.Add(new ChannelData
            {
                Channel = ch,
                RangeIndex = rangeIndex,
                InjectedA = injectedA,
                RDutMOhm = RDut / 1e6,
                MeasuredA = measuredCurrentA,
                VtiaMv = vTiaSteady * 1e3,
                VchInputMv = vChInput * 1e3,
                ExpectedVtiaMv = expectedVtia * 1e3,
                ErrorPercent = errorPct,
                DeltaA = deltaA,
                AdcCounts = adcCounts,
                AdcLsb = signalLsbs,
                WindowStartS = windowStart,
                WindowEndS = windowEnd,
                SampleTimeS = sampleTime,
                Temperature = 25.0,
                Status = status,
                SegmentTimes = segTimes.ToArray(),
                SegmentCurrentsScaled = segCurrents.ToArray(),
            });
        }

        return result;
    }

    public static int DetectRangeFromPath(string filePath)
    {
        string name = Path.GetFileName(filePath);
        // Match pattern: channel_switching_range{N}_results.txt
        for (int r = 0; r <= 3; r++)
        {
            if (name.Contains($"range{r}"))
                return r;
        }
        return 7; // default to Range 7 (1G)
    }

    private static double InterpolateAt(List<double> times, List<double> values, double targetTime)
    {
        if (times.Count == 0) return 0;
        if (targetTime <= times[0]) return values[0];
        if (targetTime >= times[^1]) return values[^1];

        int lo = 0, hi = times.Count - 1;
        while (hi - lo > 1)
        {
            int mid = (lo + hi) / 2;
            if (times[mid] <= targetTime)
                lo = mid;
            else
                hi = mid;
        }

        double t0 = times[lo], t1 = times[hi];
        double v0 = values[lo], v1 = values[hi];
        if (Math.Abs(t1 - t0) < 1e-30) return v0;
        double frac = (targetTime - t0) / (t1 - t0);
        return v0 + frac * (v1 - v0);
    }
}
