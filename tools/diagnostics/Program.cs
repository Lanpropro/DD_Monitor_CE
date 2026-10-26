using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("DDMonitorDiagnostics")]
[assembly: System.Reflection.AssemblyVersion("1.1.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.1.0.0")]

namespace DDMonitorDiagnostics
{
    internal static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new DiagnosticForm(args.Length > 0 ? args[0] : AppDomain.CurrentDomain.BaseDirectory));
        }
    }

    internal static class DiagnosticTheme
    {
        internal static readonly Color Background = Color.FromArgb(34, 36, 40);
        internal static readonly Color Surface = Color.FromArgb(48, 51, 56);
        internal static readonly Color Text = Color.FromArgb(241, 242, 245);
        internal static readonly Color Muted = Color.FromArgb(178, 184, 195);
        internal static readonly Color Accent = Color.FromArgb(0, 161, 214);

        internal static GraphicsPath Round(RectangleF rect, float radius)
        {
            var path = new GraphicsPath();
            float d = radius * 2;
            path.AddArc(rect.Left, rect.Top, d, d, 180, 90);
            path.AddArc(rect.Right - d, rect.Top, d, d, 270, 90);
            path.AddArc(rect.Right - d, rect.Bottom - d, d, d, 0, 90);
            path.AddArc(rect.Left, rect.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }

        internal static void Apply(Control control)
        {
            control.BackColor = control is TextBox || control is ListBox || control is ComboBox || control is DiagnosticInput ? Surface : Background;
            control.ForeColor = Text;
            foreach (Control child in control.Controls) Apply(child);
        }
    }

    internal sealed class DiagnosticInput : Panel
    {
        internal DiagnosticInput() { DoubleBuffered = true; Padding = new Padding(8, 6, 8, 6); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Parent.BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var path = DiagnosticTheme.Round(new RectangleF(1, 1, Width - 3, Height - 3), 7))
            using (var brush = new SolidBrush(DiagnosticTheme.Surface))
            using (var pen = new Pen(Color.FromArgb(65, 69, 76)))
            { e.Graphics.FillPath(brush, path); e.Graphics.DrawPath(pen, path); }
        }
    }

    internal sealed class DiagnosticButton : Button
    {
        bool hovered;
        internal bool Primary;
        internal DiagnosticButton() { FlatStyle = FlatStyle.Flat; FlatAppearance.BorderSize = 0; UseVisualStyleBackColor = false; Padding = new Padding(12, 5, 12, 5); DoubleBuffered = true; }
        protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hovered = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Parent.BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            var color = !Enabled ? Color.FromArgb(44, 47, 52) : Primary ? DiagnosticTheme.Accent : hovered ? Color.FromArgb(68, 72, 80) : DiagnosticTheme.Surface;
            using (var path = DiagnosticTheme.Round(new RectangleF(1, 1, Width - 3, Height - 3), Math.Min(Height / 2 - 2, 16)))
            using (var brush = new SolidBrush(color))
            using (var pen = new Pen(Focused ? DiagnosticTheme.Accent : Color.FromArgb(65, 69, 76)))
            { e.Graphics.FillPath(brush, path); e.Graphics.DrawPath(pen, path); }
            TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, Enabled ? DiagnosticTheme.Text : Color.FromArgb(112, 119, 130), TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }
    }

    internal sealed class DiagnosticProgress : Control
    {
        int value;
        internal int Value { get { return value; } set { this.value = value; AccessibleDescription = value + "%"; Invalidate(); } }
        internal DiagnosticProgress() { DoubleBuffered = true; AccessibleRole = AccessibleRole.ProgressBar; AccessibleName = "收集进度"; }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var track = DiagnosticTheme.Round(new RectangleF(0, 2, Width - 1, Height - 5), 4))
            using (var brush = new SolidBrush(DiagnosticTheme.Surface)) e.Graphics.FillPath(brush, track);
            if (value <= 0) return;
            using (var fill = DiagnosticTheme.Round(new RectangleF(0, 2, Math.Max(8, (Width - 1) * value / 100f), Height - 5), 4))
            using (var brush = new SolidBrush(DiagnosticTheme.Accent)) e.Graphics.FillPath(brush, fill);
        }
    }

    internal sealed class DiagnosticForm : Form
    {
        readonly TextBox directory = new TextBox { Dock = DockStyle.Fill };
        readonly TextBox destination = new TextBox { Dock = DockStyle.Fill };
        readonly TextBox description = new TextBox { Multiline = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, MaxLength = 12000 };
        readonly TextBox happened = new TextBox { Dock = DockStyle.Fill, MaxLength = 200 };
        readonly DiagnosticProgress progress = new DiagnosticProgress { Dock = DockStyle.Fill };
        readonly Label status = new Label { AutoSize = true, Text = "准备就绪。主软件无法启动时，也可以生成诊断包。", Dock = DockStyle.Fill };
        readonly Button generate = new DiagnosticButton { Text = "生成诊断包", AutoSize = true, Height = 36, Primary = true };
        readonly Button folder = new DiagnosticButton { Text = "打开所在文件夹", AutoSize = true, Enabled = false };
        readonly Button summary = new DiagnosticButton { Text = "查看诊断摘要", AutoSize = true, Enabled = false };
        readonly Button detect = new DiagnosticButton { Text = "自动查找", AutoSize = true };
        readonly ListBox attachments = new ListBox { Dock = DockStyle.Fill, IntegralHeight = false, HorizontalScrollbar = true, DisplayMember = "Name", BorderStyle = BorderStyle.None };
        readonly RadioButton repeatable = new RadioButton { Text = "稳定复现", AutoSize = true };
        readonly RadioButton intermittent = new RadioButton { Text = "概率触发", AutoSize = true };
        readonly RadioButton unknown = new RadioButton { Text = "尚未确认", AutoSize = true, Checked = true };
        readonly BackgroundWorker worker = new BackgroundWorker { WorkerReportsProgress = true };
        readonly TableLayoutPanel inputs;
        string zipPath;

        internal DiagnosticForm(string initial)
        {
            Text = "DD监控室CE · 诊断工具 " + Collector.ToolVersion;
            Font = new Font("Microsoft YaHei UI", 10);
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(820, 810);
            MinimumSize = new Size(760, 780);
            StartPosition = FormStartPosition.CenterScreen;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 7, Padding = new Padding(24) };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 65));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 420));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 18));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 26));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 50));
            Controls.Add(layout);
            var header = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2 };
            header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
            header.Controls.Add(new Label { Text = "诊断快照", Font = new Font(Font.FontFamily, 22, FontStyle.Bold), Dock = DockStyle.Fill, AutoSize = true });
            header.Controls.Add(detect);
            layout.Controls.Add(header, 0, 0);
            inputs = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 6 };
            inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));
            inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));
            inputs.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            inputs.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            inputs.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            inputs.RowStyles.Add(new RowStyle(SizeType.Absolute, 100));
            inputs.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
            inputs.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.Controls.Add(inputs, 0, 1);
            AddRow(0, "软件目录", directory, () => Browse(directory, "选择 DD监控室CE 所在文件夹"));
            AddRow(1, "保存到", destination, () => Browse(destination, "选择诊断包保存位置"));
            AddRow(2, "发生时间", happened, null);
            AddRow(3, "问题描述", description, null);
            var reproduction = new FlowLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(0, 5, 0, 0) };
            reproduction.Controls.AddRange(new Control[] { repeatable, intermittent, unknown });
            AddRow(4, "复现情况", reproduction, null);
            var imagePanel = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 3, ColumnCount = 2 };
            imagePanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            imagePanel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
            imagePanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
            imagePanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
            imagePanel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            var imageFrame = new DiagnosticInput { Dock = DockStyle.Fill };
            imageFrame.Controls.Add(attachments);
            imagePanel.Controls.Add(imageFrame, 0, 0);
            imagePanel.SetRowSpan(imageFrame, 2);
            var addImage = new DiagnosticButton { Text = "添加图片", Dock = DockStyle.Fill };
            var removeImage = new DiagnosticButton { Text = "移除所选", Dock = DockStyle.Fill };
            imagePanel.Controls.Add(addImage, 1, 0);
            imagePanel.Controls.Add(removeImage, 1, 1);
            var imageHint = new Label { Text = "可选，最多 5 张。请先遮挡个人信息；画面内容不会自动脱敏。", AutoSize = true, Dock = DockStyle.Fill };
            imagePanel.Controls.Add(imageHint, 0, 2);
            imagePanel.SetColumnSpan(imageHint, 2);
            AddRow(5, "图片附件", imagePanel, null);
            addImage.Click += (s, e) => AddImages();
            removeImage.Click += (s, e) => { if (attachments.SelectedIndex >= 0) attachments.Items.RemoveAt(attachments.SelectedIndex); };
            var content = new TextBox {
                Multiline = true, ReadOnly = true, BorderStyle = BorderStyle.None,
                ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, TabStop = false,
                Text = "收集范围\r\n系统与显卡驱动、软件版本与关键文件校验、脱敏配置、插件版本、近期日志、相关崩溃事件和手动添加的图片。\r\n\r\n不读取账号文件、插件私有设置、聊天记录、录制或内存转储。不联网，不修改配置，也不启动或关闭主软件。图片会去除元数据，但不会遮挡画面。请检查诊断包后再手动发送。"
            };
            layout.Controls.Add(content, 0, 2);
            layout.Controls.Add(progress, 0, 3);
            layout.Controls.Add(status, 0, 4);
            layout.Controls.Add(new Label { Text = "提示：请描述操作步骤、实际表现和预期结果，避免填写密码或 Cookie。", AutoSize = true, Dock = DockStyle.Fill, ForeColor = SystemColors.GrayText }, 0, 5);
            var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
            buttons.Controls.Add(generate);
            buttons.Controls.Add(folder);
            buttons.Controls.Add(summary);
            layout.Controls.Add(buttons, 0, 6);
            directory.Text = AppDiscovery.HasApp(initial) ? Path.GetFullPath(initial) : "";
            destination.Text = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            happened.Text = DateTime.Now.ToString("yyyy-MM-dd HH:mm") + " 左右";
            generate.Click += Generate;
            folder.Click += (s, e) => Process.Start("explorer.exe", "/select,\"" + zipPath + "\"");
            summary.Click += (s, e) => ShowSummary();
            worker.ProgressChanged += (s, e) => { progress.Value = e.ProgressPercentage; status.Text = (string)e.UserState; };
            worker.RunWorkerCompleted += Completed;
            FormClosing += (s, e) => { if (worker.IsBusy) { e.Cancel = true; status.Text = "正在收集，请等待诊断包生成后关闭。"; } };
            DiagnosticTheme.Apply(this);
            content.BackColor = DiagnosticTheme.Background;
            content.ForeColor = imageHint.ForeColor = DiagnosticTheme.Muted;
            detect.Click += (s, e) => Detect(initial, true);
            Shown += (s, e) => { if (directory.Text.Length == 0) Detect(initial, false); };
        }

        void Detect(string initial, bool requested)
        {
            detect.Enabled = false;
            status.Text = "正在查找软件目录…";
            var search = new BackgroundWorker();
            search.DoWork += (s, e) => e.Result = AppDiscovery.Find(initial);
            search.RunWorkerCompleted += (s, e) => {
                search.Dispose();
                if (IsDisposed) return;
                detect.Enabled = !worker.IsBusy;
                var found = e.Error == null ? (string[])e.Result : new string[0];
                if (worker.IsBusy) return;
                if (found.Length == 0) { status.Text = "未找到软件目录，请点击“浏览”手动选择。"; return; }
                if (!requested && directory.Text.Length != 0) return;
                if (found.Length == 1) directory.Text = found[0];
                else
                    using (var picker = new Form { Text = "选择软件目录", ClientSize = new Size(720, 140), StartPosition = FormStartPosition.CenterParent, Font = Font, MinimizeBox = false, MaximizeBox = false })
                    {
                        var choices = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Top, FlatStyle = FlatStyle.Flat };
                        choices.Items.AddRange(found);
                        choices.SelectedIndex = 0;
                        var use = new DiagnosticButton { Text = "使用此目录", Dock = DockStyle.Bottom, Height = 40, Primary = true, DialogResult = DialogResult.OK };
                        picker.Padding = new Padding(20);
                        picker.Controls.Add(choices);
                        picker.Controls.Add(use);
                        picker.AcceptButton = use;
                        DiagnosticTheme.Apply(picker);
                        if (picker.ShowDialog(this) == DialogResult.OK) directory.Text = (string)choices.SelectedItem;
                    }
                status.Text = directory.Text.Length > 0 ? "已识别软件目录，可直接生成诊断包或重新选择。" : "请选择需要排查的软件目录。";
            };
            search.RunWorkerAsync();
        }

        void AddImages()
        {
            using (var dialog = new OpenFileDialog { Title = "添加问题图片（请先遮挡个人信息）", Filter = "图片|*.png;*.jpg;*.jpeg;*.bmp;*.gif", Multiselect = true })
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    var selected = attachments.Items.Cast<FileInfo>().Select(f => f.FullName).Concat(dialog.FileNames).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
                    try
                    {
                        if (selected.Length > ImageAttachment.MaximumCount) throw new IOException("最多添加 5 张图片。");
                        foreach (var path in dialog.FileNames) ImageAttachment.Encode(path);
                        attachments.Items.Clear();
                        attachments.Items.AddRange(selected.Select(p => new FileInfo(p)).ToArray());
                    }
                    catch (Exception error) { MessageBox.Show(this, error.Message, "图片未添加", MessageBoxButtons.OK, MessageBoxIcon.Information); }
                }
        }

        void AddRow(int row, string label, Control control, Action browse)
        {
            inputs.Controls.Add(new Label { Text = label, AutoSize = true, Padding = new Padding(0, 5, 0, 0) }, 0, row);
            var textbox = control as TextBox;
            if (textbox != null)
            {
                textbox.BorderStyle = BorderStyle.None;
                var frame = new DiagnosticInput { Dock = DockStyle.Fill };
                frame.Controls.Add(textbox);
                control = frame;
            }
            control.Margin = new Padding(3, 3, 8, 9);
            inputs.Controls.Add(control, 1, row);
            if (browse == null) inputs.SetColumnSpan(control, 2);
            else
            {
                var button = new DiagnosticButton { Text = "浏览…", AutoSize = true, Dock = DockStyle.Top };
                button.Click += (s, e) => browse();
                inputs.Controls.Add(button, 2, row);
            }
        }

        void Browse(TextBox target, string title)
        {
            using (var dialog = new FolderBrowserDialog { Description = title, SelectedPath = target.Text, ShowNewFolderButton = target == destination })
                if (dialog.ShowDialog(this) == DialogResult.OK) target.Text = dialog.SelectedPath;
        }

        void Generate(object sender, EventArgs args)
        {
            Collector collector;
            string output;
            try
            {
                if (string.IsNullOrWhiteSpace(directory.Text)) throw new IOException("请先选择软件目录。");
                collector = new Collector(directory.Text);
                output = Path.GetFullPath(destination.Text);
                if (!Directory.Exists(output)) throw new IOException("保存目录不存在，请重新选择。");
            }
            catch (Exception error) { MessageBox.Show(this, error.Message, "请检查目录", MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
            string problem = description.Text, time = happened.Text;
            string reproduction = repeatable.Checked ? repeatable.Text : intermittent.Checked ? intermittent.Text : unknown.Text;
            var images = attachments.Items.Cast<FileInfo>().Select(f => f.FullName).ToArray();
            zipPath = null;
            inputs.Enabled = generate.Enabled = folder.Enabled = summary.Enabled = detect.Enabled = false;
            progress.Value = 0;
            // A fresh worker handler per collection avoids retaining previous form inputs.
            DoWorkEventHandler run = null;
            run = (s, e) => {
                try { e.Result = collector.Collect(output, problem, time, (p, text) => worker.ReportProgress(p, text), reproduction, images); }
                finally { worker.DoWork -= run; }
            };
            worker.DoWork += run;
            worker.RunWorkerAsync();
        }

        void Completed(object sender, RunWorkerCompletedEventArgs args)
        {
            inputs.Enabled = generate.Enabled = detect.Enabled = true;
            if (args.Error != null)
            {
                progress.Value = 0;
                status.Text = "生成失败，可更换保存目录后重试。";
                MessageBox.Show(this, args.Error.Message, "诊断包未生成", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            zipPath = (string)args.Result;
            folder.Enabled = summary.Enabled = true;
            status.Text = "已生成：" + Path.GetFileName(zipPath) + "\r\n请查看摘要与收集提示，检查内容后手动发送。";
        }

        void ShowSummary()
        {
            try
            {
                using (var zip = System.IO.Compression.ZipFile.OpenRead(zipPath))
                using (var reader = new StreamReader(zip.GetEntry("诊断摘要.txt").Open()))
                using (var dialog = new Form { Text = "诊断摘要", Size = new Size(760, 580), StartPosition = FormStartPosition.CenterParent, Font = Font })
                {
                    dialog.Controls.Add(new TextBox { Text = reader.ReadToEnd(), Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Both, Dock = DockStyle.Fill });
                    DiagnosticTheme.Apply(dialog);
                    dialog.ShowDialog(this);
                }
            }
            catch (Exception error) { MessageBox.Show(this, error.Message, "无法打开摘要"); }
        }
    }
}
