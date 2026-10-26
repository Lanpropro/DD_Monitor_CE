using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("DDMonitorDiagnostics")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.0.0.0")]

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

    internal sealed class DiagnosticForm : Form
    {
        readonly TextBox directory = new TextBox { Dock = DockStyle.Fill };
        readonly TextBox destination = new TextBox { Dock = DockStyle.Fill };
        readonly TextBox description = new TextBox { Multiline = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, MaxLength = 12000 };
        readonly TextBox happened = new TextBox { Dock = DockStyle.Fill, MaxLength = 200 };
        readonly ProgressBar progress = new ProgressBar { Dock = DockStyle.Fill };
        readonly Label status = new Label { AutoSize = true, Text = "准备就绪。主软件无法启动时，也可以生成诊断包。", Dock = DockStyle.Fill };
        readonly Button generate = new Button { Text = "生成诊断包", AutoSize = true, Height = 36 };
        readonly Button folder = new Button { Text = "打开所在文件夹", AutoSize = true, Enabled = false };
        readonly Button summary = new Button { Text = "查看诊断摘要", AutoSize = true, Enabled = false };
        readonly BackgroundWorker worker = new BackgroundWorker { WorkerReportsProgress = true };
        readonly TableLayoutPanel inputs;
        string zipPath;

        internal DiagnosticForm(string initial)
        {
            Text = "DD监控室CE · 诊断工具 " + Collector.ToolVersion;
            Font = new Font("Microsoft YaHei UI", 10);
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(760, 700);
            MinimumSize = new Size(720, 730);
            StartPosition = FormStartPosition.CenterScreen;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 7, Padding = new Padding(24) };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 55));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 240));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 26));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 45));
            Controls.Add(layout);
            layout.Controls.Add(new Label { Text = "生成问题现场快照", Font = new Font(Font.FontFamily, 19, FontStyle.Bold), Dock = DockStyle.Fill, AutoSize = true }, 0, 0);
            inputs = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 4 };
            inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));
            inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 82));
            inputs.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            inputs.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            inputs.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            inputs.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.Controls.Add(inputs, 0, 1);
            AddRow(0, "软件目录", directory, () => Browse(directory, "选择 DD监控室CE 所在文件夹"));
            AddRow(1, "保存到", destination, () => Browse(destination, "选择诊断包保存位置"));
            AddRow(2, "发生时间", happened, null);
            AddRow(3, "问题描述", description, null);
            var content = new TextBox {
                Multiline = true, ReadOnly = true, BorderStyle = BorderStyle.None, BackColor = SystemColors.Control,
                ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, TabStop = false,
                Text = "收集范围\r\nWindows 版本、CPU、内存、显卡驱动；软件版本、关键文件校验值；脱敏后的配置、插件版本、近期日志、相关崩溃事件与进程状态。\r\n\r\n隐私说明\r\n不读取账号文件、插件私有设置、聊天记录、录制、截图或内存转储。配置与日志会过滤常见凭据、链接及本机路径。自由文本日志可能含其他个人信息，请检查诊断包后再发送。\r\n\r\n工具只读取所选软件目录和系统诊断信息，不联网，不修改配置，也不启动或关闭主软件。"
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
            directory.Text = HasApp(initial) ? Path.GetFullPath(initial) : "";
            destination.Text = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            happened.Text = DateTime.Now.ToString("yyyy-MM-dd HH:mm") + " 左右";
            generate.Click += Generate;
            folder.Click += (s, e) => Process.Start("explorer.exe", "/select,\"" + zipPath + "\"");
            summary.Click += (s, e) => ShowSummary();
            worker.ProgressChanged += (s, e) => { progress.Value = e.ProgressPercentage; status.Text = (string)e.UserState; };
            worker.RunWorkerCompleted += Completed;
            FormClosing += (s, e) => { if (worker.IsBusy) { e.Cancel = true; status.Text = "正在收集，请等待诊断包生成后关闭。"; } };
        }

        static bool HasApp(string path)
        {
            try { return Directory.Exists(path) && (File.Exists(Path.Combine(path, "main.py")) || File.Exists(Path.Combine(path, "ddm-build.json")) || Directory.GetFiles(path, "DD监控室*.exe").Length > 0); }
            catch { return false; }
        }

        void AddRow(int row, string label, Control control, Action browse)
        {
            inputs.Controls.Add(new Label { Text = label, AutoSize = true, Padding = new Padding(0, 5, 0, 0) }, 0, row);
            control.Margin = new Padding(3, 3, 8, 9);
            inputs.Controls.Add(control, 1, row);
            if (browse == null) inputs.SetColumnSpan(control, 2);
            else
            {
                var button = new Button { Text = "浏览…", AutoSize = true, Dock = DockStyle.Top };
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
            zipPath = null;
            inputs.Enabled = generate.Enabled = folder.Enabled = summary.Enabled = false;
            progress.Value = 0;
            // A fresh worker handler per collection avoids retaining previous form inputs.
            DoWorkEventHandler run = null;
            run = (s, e) => {
                try { e.Result = collector.Collect(output, problem, time, (p, text) => worker.ReportProgress(p, text)); }
                finally { worker.DoWork -= run; }
            };
            worker.DoWork += run;
            worker.RunWorkerAsync();
        }

        void Completed(object sender, RunWorkerCompletedEventArgs args)
        {
            inputs.Enabled = generate.Enabled = true;
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
                    dialog.ShowDialog(this);
                }
            }
            catch (Exception error) { MessageBox.Show(this, error.Message, "无法打开摘要"); }
        }
    }
}
