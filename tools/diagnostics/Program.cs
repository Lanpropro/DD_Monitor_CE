using System;
using System.ComponentModel;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
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
            control.BackColor = control is TextBox || control is ComboBox || control is DiagnosticInput || control is DiagnosticTextArea || control is DiagnosticScrollBar || control is AttachmentGallery ? Surface : Background;
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

    internal sealed class DiagnosticTextBox : TextBox
    {
        [DllImport("user32.dll", CharSet = CharSet.Auto)]
        static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
        internal event EventHandler Scrolled;
        internal int FirstLine { get { return (int)SendMessage(Handle, 0xCE, IntPtr.Zero, IntPtr.Zero); } }
        internal int LineCount { get { return (int)SendMessage(Handle, 0xBA, IntPtr.Zero, IntPtr.Zero); } }
        internal int VisibleLines
        {
            get
            {
                int first = GetFirstCharIndexFromLine(FirstLine), next = GetFirstCharIndexFromLine(FirstLine + 1);
                int height = next >= 0 && first >= 0 ? GetPositionFromCharIndex(next).Y - GetPositionFromCharIndex(first).Y : Font.Height;
                return Math.Max(1, ClientSize.Height / Math.Max(1, height));
            }
        }
        internal int Maximum { get { return Math.Max(0, LineCount - VisibleLines); } }
        internal void ScrollToLine(int line)
        {
            SendMessage(Handle, 0xB6, IntPtr.Zero, (IntPtr)(Math.Max(0, Math.Min(Maximum, line)) - FirstLine));
        }
        protected override void WndProc(ref Message message)
        {
            if (message.Msg == 0x20A)
            {
                int delta = (short)((long)message.WParam >> 16);
                ScrollToLine(FirstLine - delta / 120 * (SystemInformation.MouseWheelScrollLines < 0 ? VisibleLines : SystemInformation.MouseWheelScrollLines));
                message.Result = IntPtr.Zero;
                return;
            }
            base.WndProc(ref message);
            if (message.Msg == 0xB6 || message.Msg == 0x111 || message.Msg == 0x100 || message.Msg == 0x102 || message.Msg == 0x202 || message.Msg == 0x5 || message.Msg == 0xC)
                if (Scrolled != null) Scrolled(this, EventArgs.Empty);
        }
    }

    internal sealed class DiagnosticScrollBar : Control
    {
        readonly DiagnosticTextBox editor;
        bool dragging;
        int startY, startLine;
        internal DiagnosticScrollBar(DiagnosticTextBox editor)
        {
            this.editor = editor;
            Dock = DockStyle.Right;
            Width = 14;
            DoubleBuffered = true;
            AccessibleRole = AccessibleRole.ScrollBar;
            AccessibleName = "垂直滚动条";
            editor.Scrolled += (s, e) => Invalidate();
            editor.TextChanged += (s, e) => Invalidate();
            editor.SizeChanged += (s, e) => Invalidate();
        }
        Rectangle Thumb()
        {
            int track = Math.Max(1, Height - 8);
            int height = Math.Min(track, Math.Max(24, track * editor.VisibleLines / Math.Max(1, editor.LineCount)));
            return new Rectangle(Width / 2 - 3, 4 + (track - height) * Math.Min(editor.FirstLine, editor.Maximum) / Math.Max(1, editor.Maximum), 6, height);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(BackColor);
            if (!editor.IsHandleCreated || editor.Maximum == 0) return;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var path = DiagnosticTheme.Round(Thumb(), 3))
            using (var brush = new SolidBrush(dragging ? DiagnosticTheme.Accent : Color.FromArgb(104, 111, 124))) e.Graphics.FillPath(brush, path);
        }
        protected override void OnMouseDown(MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left || editor.Maximum == 0) return;
            if (Thumb().Contains(e.Location)) { dragging = true; startY = e.Y; startLine = editor.FirstLine; Capture = true; }
            else editor.ScrollToLine(editor.FirstLine + (e.Y < Thumb().Top ? -editor.VisibleLines : editor.VisibleLines));
            Invalidate();
        }
        protected override void OnMouseMove(MouseEventArgs e)
        {
            if (dragging) editor.ScrollToLine(startLine + (e.Y - startY) * editor.Maximum / Math.Max(1, Height - 8 - Thumb().Height));
        }
        protected override void OnMouseUp(MouseEventArgs e) { dragging = false; Capture = false; Invalidate(); }
    }

    internal sealed class DiagnosticTextArea : Panel
    {
        internal DiagnosticTextArea(DiagnosticTextBox editor)
        {
            Dock = DockStyle.Fill;
            editor.ScrollBars = ScrollBars.None;
            editor.BorderStyle = BorderStyle.None;
            editor.Dock = DockStyle.Fill;
            Controls.Add(editor);
            Controls.Add(new DiagnosticScrollBar(editor));
        }
    }

    internal sealed class ImagePreview : Form
    {
        readonly PictureBox picture;
        internal ImagePreview(string path)
        {
            Text = "图片预览 · " + Path.GetFileName(path);
            ClientSize = new Size(880, 640);
            StartPosition = FormStartPosition.CenterParent;
            KeyPreview = true;
            using (var stream = new MemoryStream(ImageAttachment.Encode(path)))
            using (var image = Image.FromStream(stream))
                picture = new PictureBox { Dock = DockStyle.Fill, SizeMode = PictureBoxSizeMode.Zoom, Image = new Bitmap(image) };
            Controls.Add(picture);
            DiagnosticTheme.Apply(this);
            KeyDown += (s, e) => { if (e.KeyCode == Keys.Escape) Close(); };
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing && picture != null && picture.Image != null) { picture.Image.Dispose(); picture.Image = null; }
            base.Dispose(disposing);
        }
    }

    internal sealed class AttachmentGallery : Control
    {
        sealed class Item
        {
            internal string Path;
            internal Bitmap Thumbnail;
        }
        readonly List<Item> items = new List<Item>();
        readonly ToolTip tooltip = new ToolTip();
        int selected = -1, tipIndex = -1;
        internal string[] Paths { get { return items.Select(item => item.Path).ToArray(); } }
        internal event Action<string> PreviewRequested;

        internal AttachmentGallery()
        {
            Dock = DockStyle.Fill;
            DoubleBuffered = true;
            ResizeRedraw = true;
            AllowDrop = true;
            AccessibleName = "图片附件，可拖入图片";
            AccessibleRole = AccessibleRole.List;
            TabStop = true;
        }

        internal bool CanAccept(IDataObject data)
        {
            if (data == null || !data.GetDataPresent(DataFormats.FileDrop)) return false;
            var paths = data.GetData(DataFormats.FileDrop) as string[];
            return paths != null && paths.Length > 0 && Paths.Concat(paths).Distinct(StringComparer.OrdinalIgnoreCase).Count() <= ImageAttachment.MaximumCount &&
                paths.All(p => File.Exists(p) && new[] { ".png", ".jpg", ".jpeg", ".bmp", ".gif" }.Contains(Path.GetExtension(p).ToLowerInvariant()));
        }

        internal void AddDroppedFiles(IDataObject data)
        {
            if (data == null || !data.GetDataPresent(DataFormats.FileDrop)) throw new IOException("请拖入图片文件。");
            var paths = data.GetData(DataFormats.FileDrop) as string[];
            if (paths == null || paths.Length == 0) throw new IOException("请拖入图片文件。");
            AddFiles(paths);
        }

        internal void AddFiles(IEnumerable<string> paths)
        {
            var added = paths.Select(Path.GetFullPath).Except(Paths, StringComparer.OrdinalIgnoreCase).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
            if (items.Count + added.Length > ImageAttachment.MaximumCount) throw new IOException("最多添加 5 张图片。");
            var pending = new List<Item>();
            try
            {
                foreach (var path in added)
                    using (var stream = new MemoryStream(ImageAttachment.Encode(path)))
                    using (var image = Image.FromStream(stream))
                    {
                        int width = 180, height = 110;
                        var thumbnail = new Bitmap(width, height);
                        using (var graphics = Graphics.FromImage(thumbnail))
                        {
                            graphics.Clear(DiagnosticTheme.Surface);
                            graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
                            float scale = Math.Min((float)width / image.Width, (float)height / image.Height);
                            var size = new SizeF(image.Width * scale, image.Height * scale);
                            graphics.DrawImage(image, (width - size.Width) / 2, (height - size.Height) / 2, size.Width, size.Height);
                        }
                        pending.Add(new Item { Path = path, Thumbnail = thumbnail });
                    }
            }
            catch { foreach (var item in pending) item.Thumbnail.Dispose(); throw; }
            items.AddRange(pending);
            if (items.Count > 0) selected = items.Count - 1;
            Invalidate();
        }

        internal void RemoveSelected()
        {
            if (selected < 0 || selected >= items.Count) return;
            items[selected].Thumbnail.Dispose();
            items.RemoveAt(selected);
            selected = Math.Min(selected, items.Count - 1);
            tooltip.SetToolTip(this, "");
            tipIndex = -1;
            Invalidate();
        }

        int CellWidth { get { return Math.Max(1, Width / ImageAttachment.MaximumCount); } }
        internal Rectangle DeleteBounds(int index)
        {
            int size = Math.Max(18, Font.Height + 2);
            return new Rectangle((index + 1) * CellWidth - size - 6, 5, size, size);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            if (items.Count == 0)
            {
                TextRenderer.DrawText(e.Graphics, "将图片拖到这里，或点击“添加图片”", Font, ClientRectangle, DiagnosticTheme.Muted, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
                return;
            }
            for (int index = 0; index < items.Count; index++)
            {
                var cell = new Rectangle(index * CellWidth + 2, 1, Math.Max(10, CellWidth - 5), Height - 3);
                using (var border = DiagnosticTheme.Round(cell, 5))
                using (var pen = new Pen(index == selected ? DiagnosticTheme.Accent : Color.FromArgb(65, 69, 76), index == selected ? 2 : 1)) e.Graphics.DrawPath(pen, border);
                var image = new Rectangle(cell.X + 4, cell.Y + 3, cell.Width - 8, Math.Max(1, cell.Height - Font.Height - 9));
                float scale = Math.Min(image.Width / 180f, image.Height / 110f);
                var fitted = new RectangleF(image.X + (image.Width - 180 * scale) / 2, image.Y + (image.Height - 110 * scale) / 2, 180 * scale, 110 * scale);
                e.Graphics.DrawImage(items[index].Thumbnail, fitted);
                var caption = new Rectangle(cell.X + 4, cell.Bottom - Font.Height - 3, cell.Width - 8, Font.Height + 1);
                TextRenderer.DrawText(e.Graphics, Path.GetFileName(items[index].Path), Font, caption, DiagnosticTheme.Text, TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix);
                var delete = DeleteBounds(index);
                using (var brush = new SolidBrush(DiagnosticTheme.Background)) e.Graphics.FillEllipse(brush, delete);
                using (var pen = new Pen(DiagnosticTheme.Text, 2))
                {
                    float pad = delete.Width * 0.32f;
                    e.Graphics.DrawLine(pen, delete.Left + pad, delete.Top + pad, delete.Right - pad, delete.Bottom - pad);
                    e.Graphics.DrawLine(pen, delete.Right - pad, delete.Top + pad, delete.Left + pad, delete.Bottom - pad);
                }
            }
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            Focus();
            selected = e.X / CellWidth < items.Count ? e.X / CellWidth : -1;
            Invalidate();
            base.OnMouseDown(e);
        }
        protected override void OnMouseClick(MouseEventArgs e)
        {
            int index = e.X / CellWidth;
            if (e.Button == MouseButtons.Left && index >= 0 && index < items.Count)
            {
                selected = index;
                if (DeleteBounds(index).Contains(e.Location)) RemoveSelected();
                else if (PreviewRequested != null) PreviewRequested(items[index].Path);
            }
            base.OnMouseClick(e);
        }
        protected override void OnMouseMove(MouseEventArgs e)
        {
            int index = e.X / CellWidth;
            bool delete = index >= 0 && index < items.Count && DeleteBounds(index).Contains(e.Location);
            int tip = delete ? -index - 2 : index;
            if (tip != tipIndex) { tooltip.SetToolTip(this, index >= 0 && index < items.Count ? delete ? "删除此附件（不会删除原图）" : "点击查看：" + Path.GetFileName(items[index].Path) : ""); tipIndex = tip; }
            Cursor = index >= 0 && index < items.Count ? Cursors.Hand : Cursors.Default;
            base.OnMouseMove(e);
        }
        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Delete) { RemoveSelected(); e.Handled = true; }
            else if (e.KeyCode == Keys.Left || e.KeyCode == Keys.Right)
            { selected = Math.Max(0, Math.Min(items.Count - 1, selected + (e.KeyCode == Keys.Left ? -1 : 1))); Invalidate(); e.Handled = true; }
            base.OnKeyDown(e);
        }
        protected override void OnDragEnter(DragEventArgs e) { e.Effect = CanAccept(e.Data) ? DragDropEffects.Copy : DragDropEffects.None; base.OnDragEnter(e); }
        protected override void OnDragDrop(DragEventArgs e)
        {
            try { AddDroppedFiles(e.Data); }
            catch (Exception error) { MessageBox.Show(this, error.Message, "图片未添加", MessageBoxButtons.OK, MessageBoxIcon.Information); }
            base.OnDragDrop(e);
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing) { foreach (var item in items) item.Thumbnail.Dispose(); tooltip.Dispose(); }
            base.Dispose(disposing);
        }
    }

    internal sealed class DiagnosticForm : Form
    {
        readonly TextBox directory = new TextBox { Dock = DockStyle.Fill };
        readonly TextBox destination = new TextBox { Dock = DockStyle.Fill };
        readonly DiagnosticTextBox description = new DiagnosticTextBox { Multiline = true, Dock = DockStyle.Fill, MaxLength = 12000 };
        readonly TextBox happened = new TextBox { Dock = DockStyle.Fill, MaxLength = 200 };
        readonly DiagnosticProgress progress = new DiagnosticProgress { Dock = DockStyle.Fill };
        readonly Label status = new Label { AutoSize = true, Text = "准备就绪。主软件无法启动时，也可以生成诊断包。", Dock = DockStyle.Fill };
        readonly Button generate = new DiagnosticButton { Text = "生成诊断包", AutoSize = true, Height = 36, Primary = true };
        readonly Button folder = new DiagnosticButton { Text = "打开所在文件夹", AutoSize = true, Enabled = false };
        readonly Button summary = new DiagnosticButton { Text = "查看诊断摘要", AutoSize = true, Enabled = false };
        readonly Button detect = new DiagnosticButton { Text = "自动查找", AutoSize = true };
        readonly AttachmentGallery attachments = new AttachmentGallery();
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
            ClientSize = new Size(820, 850);
            MinimumSize = new Size(760, 820);
            StartPosition = FormStartPosition.CenterScreen;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 7, Padding = new Padding(24) };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 65));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 460));
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
            imagePanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 58));
            imagePanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 58));
            imagePanel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            var imageFrame = new DiagnosticInput { Dock = DockStyle.Fill };
            imageFrame.Controls.Add(attachments);
            imagePanel.Controls.Add(imageFrame, 0, 0);
            imagePanel.SetRowSpan(imageFrame, 2);
            var addImage = new DiagnosticButton { Text = "添加图片", Dock = DockStyle.Top, Height = 38 };
            imagePanel.Controls.Add(addImage, 1, 0);
            var imageHint = new Label { Text = "点击查看大图，右上角 × 删除；可拖入图片。最多 5 张，每张 ≤10MB，转换后合计 ≤25MB。请先遮挡个人信息。", AutoSize = true, Dock = DockStyle.Fill };
            imagePanel.Controls.Add(imageHint, 0, 2);
            imagePanel.SetColumnSpan(imageHint, 2);
            AddRow(5, "图片附件", imagePanel, null);
            addImage.Click += (s, e) => AddImages();
            attachments.PreviewRequested += path => {
                try { using (var dialog = new ImagePreview(path)) dialog.ShowDialog(this); }
                catch (Exception error) { MessageBox.Show(this, error.Message, "无法预览图片", MessageBoxButtons.OK, MessageBoxIcon.Information); }
            };
            var content = new DiagnosticTextBox {
                Multiline = true, ReadOnly = true, BorderStyle = BorderStyle.None,
                Dock = DockStyle.Fill, TabStop = false,
                Text = "收集范围\r\n系统与显卡驱动、软件版本与关键文件校验、脱敏配置、插件版本、近期日志、相关崩溃事件和手动添加的图片。\r\n\r\n不读取账号文件、插件私有设置、聊天记录、录制或内存转储。不联网，不修改配置，也不启动或关闭主软件。图片会去除元数据，但不会遮挡画面。请检查诊断包后再手动发送。"
            };
            var contentArea = new DiagnosticTextArea(content) { Margin = new Padding(3, 3, 11, 3), Padding = new Padding(8, 6, 8, 6) };
            layout.Controls.Add(contentArea, 0, 2);
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
            foreach (Control child in contentArea.Controls) child.BackColor = DiagnosticTheme.Background;
            content.ForeColor = imageHint.ForeColor = DiagnosticTheme.Muted;
            detect.Click += (s, e) => Detect(initial, true);
            Shown += (s, e) => Detect(initial, false);
        }

        void Detect(string initial, bool requested)
        {
            string startingDirectory = directory.Text;
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
                if (!requested && directory.Text != startingDirectory) return;
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
                    try
                    {
                        attachments.AddFiles(dialog.FileNames);
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
                if (textbox is DiagnosticTextBox) frame.Controls.Add(new DiagnosticTextArea((DiagnosticTextBox)textbox));
                else frame.Controls.Add(textbox);
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
            var images = attachments.Paths;
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
