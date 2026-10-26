// Console-only test driver; never included in the distributed GUI.
using System;
using DDMonitorDiagnostics;

internal static class DiagnosticsTests
{
    static int Main(string[] args)
    {
        try
        {
            var collector = new Collector(args[0]);
            Console.WriteLine(collector.Collect(args[1], "测试播放黑屏", "2026-10-26 10:00", (p, text) => { }));
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.GetType().Name); return 1; }
    }
}
