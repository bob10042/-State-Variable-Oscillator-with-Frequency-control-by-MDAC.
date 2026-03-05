using System.Globalization;
using SimGUI.Models;

namespace SimGUI.Services;

public static class CsvExporter
{
    public static void ExportChannels(string filePath, SimulationResult result)
    {
        using var writer = new StreamWriter(filePath);
        writer.WriteLine("Timestamp,Range,Rf,Channel,Injected_A,Measured_A,Delta_A,Error_Pct,V_TIA_mV,V_Expected_mV,V_Input_mV,ADC_Counts,Temperature_C,Status");

        string ts = result.Timestamp.ToString("yyyy-MM-dd HH:mm:ss");
        foreach (var ch in result.Channels)
        {
            writer.WriteLine(string.Format(CultureInfo.InvariantCulture,
                "{0},{1},{2},{3},{4:E6},{5:E6},{6:E6},{7:F2},{8:F4},{9:F4},{10:F4},{11},{12:F1},{13}",
                ts, ch.RangeIndex, result.RfDisplay, ch.Channel,
                ch.InjectedA, ch.MeasuredA, ch.DeltaA,
                ch.ErrorPercent, ch.VtiaMv, ch.ExpectedVtiaMv, ch.VchInputMv,
                ch.AdcCounts, ch.Temperature, ch.Status));
        }
    }

    public static void ExportMultiRange(string filePath, List<SimulationResult> results)
    {
        using var writer = new StreamWriter(filePath);
        writer.WriteLine("Timestamp,Range,Rf,Channel,Injected_A,Measured_A,Delta_A,Error_Pct,V_TIA_mV,V_Expected_mV,V_Input_mV,ADC_Counts,Temperature_C,Status");

        foreach (var result in results)
        {
            string ts = result.Timestamp.ToString("yyyy-MM-dd HH:mm:ss");
            foreach (var ch in result.Channels)
            {
                writer.WriteLine(string.Format(CultureInfo.InvariantCulture,
                    "{0},{1},{2},{3},{4:E6},{5:E6},{6:E6},{7:F2},{8:F4},{9:F4},{10:F4},{11},{12:F1},{13}",
                    ts, ch.RangeIndex, result.RfDisplay, ch.Channel,
                    ch.InjectedA, ch.MeasuredA, ch.DeltaA,
                    ch.ErrorPercent, ch.VtiaMv, ch.ExpectedVtiaMv, ch.VchInputMv,
                    ch.AdcCounts, ch.Temperature, ch.Status));
            }
        }
    }
}
