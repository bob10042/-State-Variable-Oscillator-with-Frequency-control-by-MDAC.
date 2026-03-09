namespace SimGUI;

/// <summary>
/// Dialog that presents circuit analysis results and lets the user
/// select which analyses to run and which nodes to probe.
/// </summary>
public class AnalysisSelectionDialog : Form
{
    private readonly CheckedListBox _analysisChecklist;
    private readonly CheckedListBox _probeChecklist;
    private readonly List<string> _analysisIds;

    public string[] SelectedAnalyses { get; private set; } = Array.Empty<string>();
    public string[] SelectedProbes { get; private set; } = Array.Empty<string>();

    public AnalysisSelectionDialog(
        string circuitName, string circuitType, string componentsSummary,
        string[] allNodes, string[] inputNodes, string[] outputNodes,
        List<(string id, string name, string desc, bool enabled)> suggestedAnalyses)
    {
        Text = $"Circuit Analysis: {circuitName}";
        Size = new Size(520, 560);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = false;
        MinimizeBox = false;
        BackColor = Color.FromArgb(235, 242, 250);

        // Circuit info panel
        var infoPanel = new Panel
        {
            Dock = DockStyle.Top,
            Height = 80,
            BackColor = Color.FromArgb(25, 55, 95),
            Padding = new Padding(12, 8, 12, 8),
        };

        var lblTitle = new Label
        {
            Text = $"Detected: {circuitType.ToUpper()}",
            ForeColor = Color.FromArgb(180, 210, 240),
            Font = new Font("Segoe UI", 14f, FontStyle.Bold),
            AutoSize = true,
            Location = new Point(12, 8),
        };

        var lblComponents = new Label
        {
            Text = $"Components: {componentsSummary}",
            ForeColor = Color.FromArgb(160, 190, 220),
            Font = new Font("Segoe UI", 9.5f),
            AutoSize = true,
            Location = new Point(12, 34),
        };

        string ioText = "";
        if (inputNodes.Length > 0) ioText += $"Input: {string.Join(", ", inputNodes)}";
        if (outputNodes.Length > 0)
            ioText += (ioText.Length > 0 ? "  |  " : "") + $"Output: {string.Join(", ", outputNodes)}";

        var lblIO = new Label
        {
            Text = ioText,
            ForeColor = Color.FromArgb(140, 180, 220),
            Font = new Font("Segoe UI", 9f),
            AutoSize = true,
            Location = new Point(12, 55),
        };

        infoPanel.Controls.AddRange(new Control[] { lblTitle, lblComponents, lblIO });

        // Analyses section
        var lblAnalyses = new Label
        {
            Text = "Select analyses to run:",
            Font = new Font("Segoe UI Semibold", 10f),
            ForeColor = Color.FromArgb(25, 55, 95),
            Location = new Point(16, 90),
            AutoSize = true,
        };

        _analysisIds = new List<string>();
        _analysisChecklist = new CheckedListBox
        {
            Location = new Point(16, 112),
            Size = new Size(472, 120),
            Font = new Font("Segoe UI", 9.5f),
            CheckOnClick = true,
            BorderStyle = BorderStyle.FixedSingle,
            BackColor = Color.White,
        };

        foreach (var (id, name, desc, enabled) in suggestedAnalyses)
        {
            _analysisIds.Add(id);
            int idx = _analysisChecklist.Items.Add($"{name} - {desc}");
            _analysisChecklist.SetItemChecked(idx, enabled);
        }

        // If no suggested analyses, add defaults
        if (suggestedAnalyses.Count == 0)
        {
            _analysisIds.Add("transient");
            int idx = _analysisChecklist.Items.Add("Time Domain (Transient) - Voltage waveforms over time");
            _analysisChecklist.SetItemChecked(idx, true);
            _analysisIds.Add("ac_bode");
            _analysisChecklist.Items.Add("Bode Plot (AC Analysis) - Gain and phase vs frequency");
        }

        // Probe nodes section
        var lblProbes = new Label
        {
            Text = "Probe nodes (select nodes to measure):",
            Font = new Font("Segoe UI Semibold", 10f),
            ForeColor = Color.FromArgb(25, 55, 95),
            Location = new Point(16, 240),
            AutoSize = true,
        };

        _probeChecklist = new CheckedListBox
        {
            Location = new Point(16, 262),
            Size = new Size(472, 180),
            Font = new Font("Consolas", 9.5f),
            CheckOnClick = true,
            BorderStyle = BorderStyle.FixedSingle,
            BackColor = Color.White,
            MultiColumn = allNodes.Length > 12,
            ColumnWidth = 120,
        };

        // Pre-check input/output nodes, leave others unchecked
        var preChecked = new HashSet<string>(inputNodes.Concat(outputNodes), StringComparer.OrdinalIgnoreCase);
        foreach (var node in allNodes)
        {
            int idx = _probeChecklist.Items.Add(node);
            _probeChecklist.SetItemChecked(idx, preChecked.Contains(node));
        }

        // If nothing pre-checked, check the first few named nodes
        if (preChecked.Count == 0 && allNodes.Length > 0)
        {
            int toCheck = Math.Min(4, allNodes.Length);
            for (int i = 0; i < toCheck; i++)
                _probeChecklist.SetItemChecked(i, true);
        }

        // Buttons
        var btnSimulate = new Button
        {
            Text = "Simulate",
            DialogResult = DialogResult.OK,
            Size = new Size(100, 35),
            Location = new Point(270, 470),
            Font = new Font("Segoe UI Semibold", 10f),
            BackColor = Color.FromArgb(60, 140, 80),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
        };
        btnSimulate.FlatAppearance.BorderSize = 0;

        var btnCancel = new Button
        {
            Text = "Cancel",
            DialogResult = DialogResult.Cancel,
            Size = new Size(100, 35),
            Location = new Point(390, 470),
            Font = new Font("Segoe UI", 10f),
            BackColor = Color.FromArgb(180, 60, 60),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
        };
        btnCancel.FlatAppearance.BorderSize = 0;

        // Select All / None buttons for probes
        var btnSelectAll = new Button
        {
            Text = "All",
            Size = new Size(50, 24),
            Location = new Point(16, 470),
            Font = new Font("Segoe UI", 8.5f),
            FlatStyle = FlatStyle.Flat,
        };
        btnSelectAll.Click += (_, _) =>
        {
            for (int i = 0; i < _probeChecklist.Items.Count; i++)
                _probeChecklist.SetItemChecked(i, true);
        };

        var btnSelectNone = new Button
        {
            Text = "None",
            Size = new Size(50, 24),
            Location = new Point(72, 470),
            Font = new Font("Segoe UI", 8.5f),
            FlatStyle = FlatStyle.Flat,
        };
        btnSelectNone.Click += (_, _) =>
        {
            for (int i = 0; i < _probeChecklist.Items.Count; i++)
                _probeChecklist.SetItemChecked(i, false);
        };

        AcceptButton = btnSimulate;
        CancelButton = btnCancel;

        Controls.AddRange(new Control[]
        {
            infoPanel, lblAnalyses, _analysisChecklist,
            lblProbes, _probeChecklist,
            btnSelectAll, btnSelectNone,
            btnSimulate, btnCancel,
        });

        FormClosing += (_, e) =>
        {
            if (DialogResult == DialogResult.OK)
            {
                // Collect selected analyses
                var analyses = new List<string>();
                for (int i = 0; i < _analysisChecklist.Items.Count; i++)
                {
                    if (_analysisChecklist.GetItemChecked(i) && i < _analysisIds.Count)
                        analyses.Add(_analysisIds[i]);
                }
                SelectedAnalyses = analyses.Count > 0 ? analyses.ToArray() : new[] { "transient" };

                // Collect selected probes
                var probes = new List<string>();
                for (int i = 0; i < _probeChecklist.Items.Count; i++)
                {
                    if (_probeChecklist.GetItemChecked(i))
                        probes.Add(_probeChecklist.Items[i].ToString() ?? "");
                }
                SelectedProbes = probes.Count > 0 ? probes.ToArray() : allNodes.Take(4).ToArray();
            }
        };
    }
}
