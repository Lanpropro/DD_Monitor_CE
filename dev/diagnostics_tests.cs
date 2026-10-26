// Console-only test driver; never included in the distributed GUI.
using System;
using System.Linq;
using System.IO;
using System.Drawing;
using System.Reflection;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using DDMonitorDiagnostics;

internal static class DiagnosticsTests
{
    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            Console.OutputEncoding = new System.Text.UTF8Encoding(false);
            if (args[0] == "--gallery")
            {
                using (var gallery = new AttachmentGallery { Size = new Size(600, 100), BackColor = DiagnosticTheme.Surface })
                {
                    var data = new DataObject(DataFormats.FileDrop, new[] { args[1] });
                    if (!gallery.AllowDrop || !gallery.CanAccept(data)) throw new Exception("File drop unavailable");
                    var enter = new DragEventArgs(data, 0, 0, 0, DragDropEffects.Copy, DragDropEffects.None);
                    typeof(AttachmentGallery).GetMethod("OnDragEnter", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(gallery, new object[] { enter });
                    if (enter.Effect != DragDropEffects.Copy) throw new Exception("Drop cursor unavailable");
                    typeof(AttachmentGallery).GetMethod("OnDragDrop", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(gallery, new object[] { enter });
                    gallery.AddDroppedFiles(data);
                    if (gallery.Paths.Length != 1) throw new Exception("Duplicate attachment");
                    string previewPath = null;
                    gallery.PreviewRequested += path => previewPath = path;
                    var click = typeof(AttachmentGallery).GetMethod("OnMouseClick", BindingFlags.Instance | BindingFlags.NonPublic);
                    click.Invoke(gallery, new object[] { new MouseEventArgs(MouseButtons.Left, 1, 30, 45, 0) });
                    if (previewPath != args[1] || gallery.Paths.Length != 1) throw new Exception("Thumbnail click must preview without removing");
                    using (var preview = new ImagePreview(previewPath))
                    {
                        var picture = preview.Controls.OfType<PictureBox>().Single();
                        if (picture.Image.Width != 2 || picture.Image.Height != 2 || picture.SizeMode != PictureBoxSizeMode.Zoom) throw new Exception("Full-size preview unavailable");
                    }
                    using (var image = new Bitmap(600, 100))
                    {
                        gallery.DrawToBitmap(image, new Rectangle(0, 0, 600, 100));
                        bool red = false;
                        for (int y = 10; y < 65; y++)
                            for (int x = 20; x < 90; x++)
                            {
                                var pixel = image.GetPixel(x, y);
                                if (pixel.R > 200 && pixel.G < 50) red = true;
                            }
                        if (!red) throw new Exception("Thumbnail not rendered");
                    }
                    using (File.Open(args[1], FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
                    if (gallery.CanAccept(new DataObject(DataFormats.Text, "not a file"))) throw new Exception("Text drop accepted");
                    if (gallery.CanAccept(new DataObject(DataFormats.FileDrop, new[] { args[2] }))) throw new Exception("Non-image drop accepted");
                    try { gallery.AddFiles(new[] { args[3], args[2] }); throw new Exception("Invalid batch accepted"); }
                    catch (IOException) { }
                    if (gallery.Paths.Length != 1) throw new Exception("Partial batch retained");
                    try { gallery.AddFiles(Enumerable.Range(0, 6).Select(i => Path.Combine(Path.GetDirectoryName(args[1]), "image-" + i + ".png"))); throw new Exception("Excessive batch accepted"); }
                    catch (IOException) { }
                    // Export through exactly the paths retained by the thumbnail/drop control.
                    var galleryCollector = new Collector(args[4]);
                    var package = galleryCollector.Collect(args[5], "拖入图片测试", "test", (p, text) => { }, "尚未确认", gallery.Paths);
                    Console.WriteLine(package);
                    previewPath = null;
                    var delete = gallery.DeleteBounds(0);
                    click.Invoke(gallery, new object[] { new MouseEventArgs(MouseButtons.Left, 1, delete.Left + delete.Width / 2, delete.Top + delete.Height / 2, 0) });
                    if (gallery.Paths.Length != 0) throw new Exception("Attachment removal failed");
                    if (previewPath != null || !File.Exists(args[1])) throw new Exception("Delete must only remove the attachment");
                    return 0;
                }
            }
            if (args[0] == "--nearby")
            {
                Console.WriteLine(new JavaScriptSerializer().Serialize(AppDiscovery.Nearby(args[1])));
                return 0;
            }
            if (args[0] == "--scroll")
            {
                using (var form = new Form())
                using (var editor = new DiagnosticTextBox { Multiline = true, Text = string.Join("\r\n", Enumerable.Range(0, 100)) })
                using (var area = new DiagnosticTextArea(editor))
                {
                    form.Controls.Add(area);
                    form.CreateControl();
                    var handle = editor.Handle;
                    editor.ScrollToLine(15);
                    if (editor.FirstLine != 15 || editor.ScrollBars != ScrollBars.None) throw new Exception("Scrolling failed: " + editor.FirstLine + "/" + editor.Maximum + "/" + editor.LineCount + "/" + editor.ClientSize);
                    editor.ScrollToLine(int.MaxValue);
                    if (editor.FirstLine != editor.Maximum) throw new Exception("Scroll clamp failed: " + editor.FirstLine + "/" + editor.Maximum + "/" + editor.VisibleLines + "/" + editor.Font.Height);
                    editor.Text = "short";
                    editor.ScrollToLine(0);
                    if (editor.FirstLine != 0 || editor.Maximum != 0) throw new Exception("Scroll reset failed");
                    Console.WriteLine("scroll passed");
                    return 0;
                }
            }
            if (args[0] == "--discover")
            {
                Console.WriteLine(new JavaScriptSerializer().Serialize(AppDiscovery.Candidates(args.Skip(1))));
                return 0;
            }
            var collector = new Collector(args[0]);
            Console.WriteLine(collector.Collect(args[1], "测试播放黑屏", "2026-10-26 10:00", (p, text) => { },
                args.Length > 2 ? args[2] : "尚未确认", args.Skip(3).ToArray()));
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.GetType().Name + ": " + error.Message); return 1; }
    }
}
