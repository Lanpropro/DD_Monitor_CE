// Console-only test driver; never included in the distributed GUI.
using System;
using System.Linq;
using System.Web.Script.Serialization;
using DDMonitorDiagnostics;

internal static class DiagnosticsTests
{
    static int Main(string[] args)
    {
        try
        {
            Console.OutputEncoding = new System.Text.UTF8Encoding(false);
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
        catch (Exception error) { Console.Error.WriteLine(error.GetType().Name); return 1; }
    }
}
