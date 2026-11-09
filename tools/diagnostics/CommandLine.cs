using System;
using System.IO;
using System.Web.Script.Serialization;

namespace DDMonitorDiagnostics
{
    internal sealed class ExportRequest
    {
        public string root { get; set; }
        public string destination { get; set; }
        public string description { get; set; }
        public string happened { get; set; }
        public string reproduction { get; set; }
        public string[] attachments { get; set; }
        public object evidence { get; set; }
        public bool include_native_dumps { get; set; }
        public string mode { get; set; }
        public int pid { get; set; }
    }

    internal static class CommandLine
    {
        internal static bool TryRun(string[] args)
        {
            if (args.Length == 0 || (args[0] != "--collect-json" && args[0] != "--capture-json")) return false;
            var json = new JavaScriptSerializer { MaxJsonLength = 2 * 1024 * 1024 };
            var output = new StreamWriter(Console.OpenStandardOutput(), new System.Text.UTF8Encoding(false)) { AutoFlush = true };
            Action<object> send = value => output.WriteLine(json.Serialize(value));
            try
            {
                if (args.Length != 2 || new FileInfo(args[1]).Length > 2 * 1024 * 1024) throw new ArgumentException("诊断请求无效。");
                var request = json.Deserialize<ExportRequest>(File.ReadAllText(args[1]));
                if (request == null) throw new ArgumentException("诊断请求为空。");
                if (args[0] == "--capture-json")
                {
                    if (request.pid <= 0 || (request.mode != "folders" && request.mode != "drag")) throw new ArgumentException("现场采集类型无效。");
                    using (var client = new OnDemandClient())
                        send(new { kind = "capture", evidence = client.Capture(request.root, request.pid, request.mode) });
                }
                else
                {
                    string path = new Collector(request.root).Collect(request.destination, request.description ?? "", request.happened ?? "",
                        (percent, message) => send(new { kind = "progress", percent, message }),
                        request.reproduction ?? "尚未确认", request.attachments, request.evidence, request.include_native_dumps,
                        staging => send(new { kind = "staging", path = staging }));
                    send(new { kind = "result", path });
                }
            }
            catch (Exception error)
            {
                send(new { kind = "error", message = error.Message, error_type = error.GetType().Name });
                Environment.ExitCode = 1;
            }
            return true;
        }
    }
}
