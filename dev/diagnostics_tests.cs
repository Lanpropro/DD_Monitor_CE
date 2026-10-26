// Console-only test driver; never included in the distributed GUI.
using System;
using System.Linq;
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
