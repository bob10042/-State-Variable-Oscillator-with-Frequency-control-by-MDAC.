namespace SimGUI;

partial class MainForm
{
    private System.ComponentModel.IContainer components = null;

    protected override void Dispose(bool disposing)
    {
        if (disposing && (components != null))
            components.Dispose();
        base.Dispose(disposing);
    }

    #region Windows Form Designer generated code

    private void InitializeComponent()
    {
        components = new System.ComponentModel.Container();

        // ---- Color palette (blue theme) ----
        var headerBg = Color.FromArgb(25, 55, 95);
        var toolStripBg = Color.FromArgb(220, 232, 245);
        var outputBg = Color.FromArgb(15, 30, 60);
        var outputFg = Color.FromArgb(180, 210, 240);
        var altRowBg = Color.FromArgb(232, 240, 250);
        var statusBg = Color.FromArgb(200, 218, 240);

        // ---- ToolStrip ----
        _toolStrip = new ToolStrip();
        _toolStrip.BackColor = toolStripBg;
        _toolStrip.GripStyle = ToolStripGripStyle.Hidden;
        _toolStrip.Padding = new Padding(4, 2, 4, 2);

        // Project selector combo (Electrometer / Oscillator)
        _cboProject = new ToolStripComboBox("Project") { DropDownStyle = ComboBoxStyle.DropDownList, Width = 120 };
        _cboProject.Items.AddRange(new object[] { "Electrometer", "Oscillator", "Comparison", "General Circuit" });
        _cboProject.SelectedIndex = 0;

        // Sweep point selector combo (populated dynamically by project)
        _cboSweepPoint = new ToolStripComboBox("SweepPoint") { DropDownStyle = ComboBoxStyle.DropDownList, Width = 220 };

        _btnRunSim = new ToolStripButton("Run Range") { Image = null, DisplayStyle = ToolStripItemDisplayStyle.Text };
        _btnRunAll = new ToolStripButton("Run All Ranges") { DisplayStyle = ToolStripItemDisplayStyle.Text };
        _btnCalibrate = new ToolStripButton("Calibrate") { DisplayStyle = ToolStripItemDisplayStyle.Text, Enabled = false, Visible = false };
        _btnTogglePlot = new ToolStripButton("Amplitude View") { DisplayStyle = ToolStripItemDisplayStyle.Text, Enabled = false, Visible = false };
        _btnLoadCircuit = new ToolStripButton("Load Circuit") { DisplayStyle = ToolStripItemDisplayStyle.Text, Visible = false };
        _btnViewCircuit = new ToolStripButton("View Circuit") { DisplayStyle = ToolStripItemDisplayStyle.Text, Enabled = false, Visible = false };
        _btnToggleView = new ToolStripButton("Bode View") { DisplayStyle = ToolStripItemDisplayStyle.Text, Enabled = false, Visible = false };
        _btnLoadFile = new ToolStripButton("Load File") { DisplayStyle = ToolStripItemDisplayStyle.Text };
        _btnExportCsv = new ToolStripButton("Export CSV") { DisplayStyle = ToolStripItemDisplayStyle.Text, Enabled = false };
        _btnScreenshot = new ToolStripButton("Screenshot") { DisplayStyle = ToolStripItemDisplayStyle.Text };
        _btnClear = new ToolStripButton("Clear") { DisplayStyle = ToolStripItemDisplayStyle.Text };
        _lblToolStatus = new ToolStripLabel("Ready") { Alignment = ToolStripItemAlignment.Right, ForeColor = Color.FromArgb(25, 55, 95) };
        _toolStrip.Items.AddRange(new ToolStripItem[] {
            _cboProject, new ToolStripSeparator(),
            _cboSweepPoint, new ToolStripSeparator(),
            _btnRunSim, new ToolStripSeparator(),
            _btnRunAll, new ToolStripSeparator(),
            _btnCalibrate, new ToolStripSeparator(),
            _btnTogglePlot, new ToolStripSeparator(),
            _btnLoadCircuit, new ToolStripSeparator(),
            _btnViewCircuit, new ToolStripSeparator(),
            _btnToggleView, new ToolStripSeparator(),
            _btnLoadFile, new ToolStripSeparator(),
            _btnExportCsv, new ToolStripSeparator(),
            _btnScreenshot, new ToolStripSeparator(),
            _btnClear,
            _lblToolStatus
        });

        // ---- SplitContainer ----
        _splitContainer = new SplitContainer();
        _splitContainer.Dock = DockStyle.Fill;
        _splitContainer.Orientation = Orientation.Vertical;
        _splitContainer.SplitterDistance = 480;
        _splitContainer.SplitterWidth = 5;
        _splitContainer.BackColor = Color.FromArgb(180, 200, 225);

        // ---- DataGridView (left panel) ----
        _dataGrid = new DataGridView();
        _dataGrid.Dock = DockStyle.Fill;
        _dataGrid.AllowUserToAddRows = false;
        _dataGrid.AllowUserToDeleteRows = false;
        _dataGrid.ReadOnly = true;
        _dataGrid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        _dataGrid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.AllCells;
        _dataGrid.RowHeadersVisible = false;
        _dataGrid.BackgroundColor = Color.FromArgb(245, 248, 255);
        _dataGrid.GridColor = Color.FromArgb(190, 210, 235);
        _dataGrid.BorderStyle = BorderStyle.None;
        _dataGrid.DefaultCellStyle.Font = new Font("Consolas", 9f);
        _dataGrid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(100, 150, 210);
        _dataGrid.ColumnHeadersDefaultCellStyle.Font = new Font("Segoe UI Semibold", 8.5f);
        _dataGrid.ColumnHeadersDefaultCellStyle.BackColor = headerBg;
        _dataGrid.ColumnHeadersDefaultCellStyle.ForeColor = Color.White;
        _dataGrid.ColumnHeadersHeight = 30;
        _dataGrid.EnableHeadersVisualStyles = false;
        _dataGrid.AlternatingRowsDefaultCellStyle.BackColor = altRowBg;
        _dataGrid.RowTemplate.Height = 22;
        // Columns are set dynamically by project config

        // ---- ScottPlot (right panel) ----
        _formsPlot = new ScottPlot.WinForms.FormsPlot();
        _formsPlot.Dock = DockStyle.Fill;

        // ---- StatusStrip ----
        _statusStrip = new StatusStrip();
        _statusStrip.BackColor = statusBg;
        // 6 status labels (generic, populated by project config)
        _statusLabels = new ToolStripStatusLabel[6];
        for (int i = 0; i < 6; i++)
        {
            _statusLabels[i] = new ToolStripStatusLabel("--") { ForeColor = headerBg };
            _statusStrip.Items.Add(_statusLabels[i]);
        }

        // ---- Output log (bottom dock) ----
        _txtOutput = new TextBox();
        _txtOutput.Multiline = true;
        _txtOutput.ReadOnly = true;
        _txtOutput.ScrollBars = ScrollBars.Vertical;
        _txtOutput.Dock = DockStyle.Bottom;
        _txtOutput.Height = 90;
        _txtOutput.Font = new Font("Consolas", 8.5f);
        _txtOutput.BackColor = outputBg;
        _txtOutput.ForeColor = outputFg;

        // ---- Assemble ----
        ((System.ComponentModel.ISupportInitialize)_splitContainer).BeginInit();
        _splitContainer.SuspendLayout();
        ((System.ComponentModel.ISupportInitialize)_dataGrid).BeginInit();

        _splitContainer.Panel1.Controls.Add(_dataGrid);
        _splitContainer.Panel2.Controls.Add(_formsPlot);

        Controls.Add(_splitContainer);
        Controls.Add(_txtOutput);
        Controls.Add(_toolStrip);
        Controls.Add(_statusStrip);

        ((System.ComponentModel.ISupportInitialize)_dataGrid).EndInit();
        ((System.ComponentModel.ISupportInitialize)_splitContainer).EndInit();
        _splitContainer.ResumeLayout(false);

        // ---- Form properties ----
        AutoScaleMode = AutoScaleMode.Font;
        ClientSize = new Size(1600, 900);
        Text = "SimGUI - Circuit Simulation";
        StartPosition = FormStartPosition.CenterScreen;
        WindowState = FormWindowState.Maximized;
        MinimumSize = new Size(1100, 650);
        BackColor = Color.FromArgb(235, 242, 250);
    }

    #endregion

    private ToolStrip _toolStrip;
    private ToolStripComboBox _cboProject;
    private ToolStripComboBox _cboSweepPoint;
    private ToolStripButton _btnRunSim;
    private ToolStripButton _btnRunAll;
    private ToolStripButton _btnCalibrate;
    private ToolStripButton _btnTogglePlot;
    private ToolStripButton _btnLoadCircuit;
    private ToolStripButton _btnViewCircuit;
    private ToolStripButton _btnToggleView;
    private ToolStripButton _btnLoadFile;
    private ToolStripButton _btnExportCsv;
    private ToolStripButton _btnScreenshot;
    private ToolStripButton _btnClear;
    private ToolStripLabel _lblToolStatus;
    private SplitContainer _splitContainer;
    private DataGridView _dataGrid;
    private ScottPlot.WinForms.FormsPlot _formsPlot;
    private StatusStrip _statusStrip;
    private ToolStripStatusLabel[] _statusLabels;
    private TextBox _txtOutput;
}
