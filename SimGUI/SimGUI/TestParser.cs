using SimGUI.Models;
using SimGUI.Services;

namespace SimGUI;

public static class TestParser
{
    public static void Run()
    {
        Console.WriteLine("=== Multi-Range Parser Test ===\n");

        string workDir = @"C:\Users\Robert\Documents\LTspice\sim_work";
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
    }
}
