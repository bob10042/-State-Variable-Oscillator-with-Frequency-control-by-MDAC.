using System.Runtime.InteropServices;

namespace SimGUI;

static class Program
{
    // Suppress Windows Error Reporting crash dialogs from child processes (ngspice)
    [DllImport("kernel32.dll")]
    private static extern uint SetErrorMode(uint uMode);
    private const uint SEM_FAILCRITICALERRORS = 0x0001;
    private const uint SEM_NOGPFAULTERRORBOX = 0x0002;
    private const uint SEM_NOOPENFILEERRORBOX = 0x8000;

    [STAThread]
    static void Main(string[] args)
    {
        // Suppress crash dialog popups from child processes (ngspice)
        SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);

        if (args.Length > 0 && args[0] == "--test")
        {
            TestParser.Run();
            return;
        }

        ApplicationConfiguration.Initialize();

        // Catch unhandled exceptions - log to file, no popups
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, e) =>
        {
            string msg = $"[{DateTime.Now:HH:mm:ss}] Thread Exception:\n{e.Exception}";
            string logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "crash.log");
            try { File.AppendAllText(logPath, msg + "\n\n"); } catch { }
            // No popup - silently log and continue
        };
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
        {
            string msg = $"[{DateTime.Now:HH:mm:ss}] Unhandled Exception:\n{e.ExceptionObject}";
            string logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "crash.log");
            try { File.AppendAllText(logPath, msg + "\n\n"); } catch { }
            // No popup - silently log and continue
        };

        Application.Run(new MainForm());
    }
}
