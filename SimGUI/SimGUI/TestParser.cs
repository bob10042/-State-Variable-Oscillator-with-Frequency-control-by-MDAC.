using SimGUI.Models;
using SimGUI.Services;

namespace SimGUI;

public static class TestParser
{
    public static void Run()
    {
        Console.WriteLine("=== Multi-Range Parser Test ===\n");

        string workDir = Path.Combine(SimGUI.Services.SimulationRunner.RepoRoot, "sim_work");
        int totalPass = 0, totalWarn = 0, totalFail = 0;

        for (int range = 0; range <= 8; range++)
        {
            string resultsFile = Path.Combine(workDir, $"channel_switching_range{range}_results.txt");

            if (!File.Exists(resultsFile))
            {
                Console.WriteLine($"Range {range}: file not found ({resultsFile})\n");
                continue;
            }

            Console.WriteLine(new string('=', 120));
            Console.WriteLine($"RANGE {range}: Rf={SimulationRunner.RangeShortNames[range]}");
            Console.WriteLine(new string('=', 120));

            var result = ResultParser.Parse(resultsFile, range);

            Console.WriteLine($"Data points: {result.TimePoints.Length:N0}");
            Console.WriteLine($"Sim time:    {result.SimulationTimeSeconds:F4} s");
            Console.WriteLine($"Rf:          {result.RfDisplay}");
            Console.WriteLine($"ADC:         {result.AdcBits}-bit, {result.AdcRefV}V ref");
            Console.WriteLine();

            Console.WriteLine($"{"CH",-4} {"Injected",-16} {"Measured",-16} {"Delta",-16} {"Err(%)",-8} {"V_TIA(mV)",-12} {"V_exp(mV)",-12} {"ADC",-10} {"Status",-6}");
            Console.WriteLine(new string('-', 120));

            foreach (var ch in result.Channels)
            {
                string marker = ch.Status == "PASS" ? " " : (ch.Status == "WARN" ? "*" : "X");
                Console.WriteLine($"{marker}CH{ch.Channel,-2} {ch.InjectedDisplay,-16} {ch.MeasuredDisplay,-16} {ch.DeltaDisplay,-16} {ch.ErrorPercent,-8:F1} {ch.VtiaMv,-12:F3} {ch.ExpectedVtiaMv,-12:F3} {ch.AdcCounts,-10:N0} {ch.Status,-6}");
            }

            Console.WriteLine();
            Console.WriteLine($"Avg Error: {result.AverageErrorPercent:F1}% | Max Error: {result.MaxErrorPercent:F1}%");
            Console.WriteLine($"PASS: {result.PassCount} | WARN: {result.WarnCount} | FAIL: {result.FailCount}");
            Console.WriteLine();

            totalPass += result.PassCount;
            totalWarn += result.WarnCount;
            totalFail += result.FailCount;
        }

        Console.WriteLine(new string('=', 120));
        Console.WriteLine($"TOTAL ACROSS ALL RANGES: PASS={totalPass} WARN={totalWarn} FAIL={totalFail}");
        if (totalFail == 0 && totalPass > 0)
            Console.WriteLine(">> ALL CHANNELS ALL RANGES WITHIN TOLERANCE <<");
        Console.WriteLine(new string('=', 120));

        // --- Generic Circuit Parser Test ---
        Console.WriteLine("\n\n=== Generic Circuit Parser Test ===\n");
        TestGenericParser(workDir);
    }

    private static void TestGenericParser(string workDir)
    {
        string metaPath = Path.Combine(workDir, "generic_sim_meta.json");
        if (!File.Exists(metaPath))
        {
            Console.WriteLine($"  generic_sim_meta.json not found at {metaPath}");
            Console.WriteLine("  Run: python kicad_pipeline.py generic_sim \"<circuit>.asc\" first");
            return;
        }

        Console.WriteLine($"  Meta file: {metaPath}");

        string[] probes = { "A", "B", "IN" };
        try
        {
            var result = GenericResultParser.Parse(workDir, probes);

            Console.WriteLine($"  Circuit: {result.CircuitName} ({result.CircuitPath})");
            Console.WriteLine($"  All nodes: {string.Join(", ", result.AllNodes)}");
            Console.WriteLine($"  Probed: {string.Join(", ", result.ProbedNodes)}");
            Console.WriteLine($"  Analyses run: {string.Join(", ", result.AnalysesRun)}");
            Console.WriteLine($"  Gain: {result.Gain:F2}x ({result.GainDb:F1} dB)");

            Console.WriteLine($"\n  Transient nodes: {result.TransientNodes.Count}");
            foreach (var tn in result.TransientNodes)
            {
                Console.WriteLine($"    {tn.NodeName}: {tn.Time.Length} pts, Vpp={tn.Vpp:F4}, Vdc={tn.Vdc:F4}, Vrms={tn.Vrms:F4}, Freq={tn.FreqHz:F1}Hz, Status={tn.Status}");
            }

            Console.WriteLine($"\n  AC/Bode nodes: {result.AcNodes.Count}");
            foreach (var an in result.AcNodes)
            {
                Console.WriteLine($"    {an.NodeName}: {an.Frequency.Length} freq pts, {an.MagnitudeDb.Length} mag pts, {an.PhaseDeg.Length} phase pts");
                if (an.MagnitudeDb.Length > 0)
                    Console.WriteLine($"      DC gain={an.MagnitudeDb[0]:F1}dB, Peak={an.MagnitudeDb.Max():F1}dB");
            }

            // Validation
            bool pass = true;
            if (result.TransientNodes.Count == 0) { Console.WriteLine("  FAIL: No transient nodes!"); pass = false; }
            if (result.AcNodes.Count == 0) { Console.WriteLine("  FAIL: No AC nodes!"); pass = false; }
            foreach (var tn in result.TransientNodes)
            {
                if (tn.Time.Length < 10) { Console.WriteLine($"  FAIL: {tn.NodeName} has only {tn.Time.Length} time points!"); pass = false; }
                if (tn.Voltage.Length != tn.Time.Length) { Console.WriteLine($"  FAIL: {tn.NodeName} time/voltage length mismatch!"); pass = false; }
            }
            Console.WriteLine(pass ? "\n  >> GENERIC PARSER TEST PASSED <<" : "\n  >> GENERIC PARSER TEST FAILED <<");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"  EXCEPTION: {ex.Message}");
            Console.WriteLine($"  Stack: {ex.StackTrace}");
        }
    }
}
