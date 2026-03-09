namespace SimGUI;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--test")
        {
            TestParser.Run();
            return;
        }

        ApplicationConfiguration.Initialize();

        // Catch unhandled exceptions and log them
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, e) =>
        {
            string msg = $"Thread Exception:\n{e.Exception}";
            string logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "crash.log");
            File.WriteAllText(logPath, msg);
            MessageBox.Show(msg, "SimGUI Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        };
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
        {
            string msg = $"Unhandled Exception:\n{e.ExceptionObject}";
            string logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "crash.log");
            File.WriteAllText(logPath, msg);
            MessageBox.Show(msg, "SimGUI Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        };

        Application.Run(new MainForm());
    }
}
