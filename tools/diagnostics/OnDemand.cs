using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Management;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;

namespace DDMonitorDiagnostics
{
    internal sealed class LiveTarget
    {
        internal int Pid;
        internal string Started;
        public override string ToString() { return "进程 " + Pid + " · 启动于 " + Started; }
    }

    internal sealed class OnDemandClient : IDisposable
    {
        readonly object gate = new object();
        NamedPipeClientStream pipe;
        bool cancelled;
        readonly List<byte> pending = new List<byte>();
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = 1024 * 1024, RecursionLimit = 100 };
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetNamedPipeServerProcessId(IntPtr pipe, out uint pid);
        delegate bool EnumWindow(IntPtr window, IntPtr data);
        [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindow callback, IntPtr data);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr window, StringBuilder name, int count);
        [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window, out Rect rect);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32.dll")] static extern bool IsHungAppWindow(IntPtr window);
        [DllImport("user32.dll")] static extern IntPtr GetParent(IntPtr window);
        [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr window, uint command);
        [StructLayout(LayoutKind.Sequential)] struct Rect { internal int Left, Top, Right, Bottom; }

        internal static LiveTarget[] Find(string directory)
        {
            var root = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar);
            var targets = new List<LiveTarget>();
            bool source = File.Exists(Path.Combine(root, "main.py"));
            foreach (var process in Process.GetProcesses())
                using (process)
                    try
                    {
                        if (process.MainWindowHandle == IntPtr.Zero) continue;
                        string path = process.MainModule.FileName;
                        if (Path.GetDirectoryName(path).Equals(root, StringComparison.OrdinalIgnoreCase)
                            && System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileNameWithoutExtension(path), @"^(DD监控室(CE)?|DDMonitorCE)(-v[\d.]+)?$", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                            targets.Add(new LiveTarget { Pid = process.Id, Started = process.StartTime.ToString("HH:mm:ss") });
                        else if (source && (process.ProcessName == "python" || process.ProcessName == "pythonw"))
                            using (var query = new ManagementObjectSearcher("SELECT CommandLine FROM Win32_Process WHERE ProcessId=" + process.Id))
                            using (var results = query.Get())
                                foreach (ManagementObject row in results)
                                    using (row)
                                    {
                                        string command = Convert.ToString(row["CommandLine"]).Replace('/', '\\');
                                        if (new[] { "main.py", @"dev\diagnose_drag_windows.py" }.Any(entry =>
                                            command.IndexOf(Path.Combine(root, entry), StringComparison.OrdinalIgnoreCase) >= 0))
                                            targets.Add(new LiveTarget { Pid = process.Id, Started = process.StartTime.ToString("HH:mm:ss") });
                                    }
                    }
                    catch (System.ComponentModel.Win32Exception) { }
                    catch (InvalidOperationException) { }
                    catch (ManagementException) { }
            return targets.ToArray();
        }

        internal static object ExternalSnapshot(int pid)
        {
            const int limit = 4096;
            var rows = new List<object>();
            var roots = new List<IntPtr>();
            EnumWindows((window, data) => {
                uint owner; GetWindowThreadProcessId(window, out owner);
                if (owner == pid) roots.Add(window);
                return true;
            }, IntPtr.Zero);
            // Read every top-level window before descendants; a busy video wall must
            // not consume the entire budget before the sidebar is visited.
            var pending = new Queue<IntPtr>(roots.OrderByDescending(IsWindowVisible));
            var seen = new HashSet<IntPtr>();
            bool truncated = false;
            while (pending.Count > 0)
            {
                var window = pending.Dequeue();
                uint owner;
                uint thread = GetWindowThreadProcessId(window, out owner);
                if (owner != pid || !seen.Add(window)) continue;
                if (rows.Count >= limit) { truncated = true; break; }
                var name = new StringBuilder(256);
                GetClassName(window, name, name.Capacity);
                Rect rect;
                bool valid = GetWindowRect(window, out rect);
                rows.Add(new { hwnd = window.ToInt64().ToString("x"), thread, cls = name.ToString(),
                    parent = GetParent(window).ToInt64().ToString("x"), visible = IsWindowVisible(window),
                    hung = IsHungAppWindow(window), rect = valid ? new[] { rect.Left, rect.Top, rect.Right - rect.Left, rect.Bottom - rect.Top } : null });
                var siblings = new HashSet<IntPtr>();
                for (var child = GetWindow(window, 5); child != IntPtr.Zero && siblings.Add(child); child = GetWindow(child, 2))
                {
                    if (pending.Count + rows.Count >= limit + 1) { truncated = true; break; }
                    pending.Enqueue(child);
                }
            }
            return new { pid, windows = rows, truncated, window_limit = limit,
                traversal = "breadth-first", internal_state_available = false };
        }

        string ReadLine(NamedPipeClientStream stream, int timeout)
        {
            var buffer = new byte[4096];
            var clock = Stopwatch.StartNew();
            while (pending.Count <= 1024 * 1024)
            {
                int newline = pending.IndexOf(10);
                if (newline >= 0)
                {
                    string line = Encoding.UTF8.GetString(pending.GetRange(0, newline).ToArray());
                    pending.RemoveRange(0, newline + 1);
                    return line;
                }
                int remaining = timeout - (int)clock.ElapsedMilliseconds;
                if (remaining <= 0) throw new IOException("软件未在限定时间内返回现场。");
                var read = stream.BeginRead(buffer, 0, buffer.Length, null, null);
                int count;
                using (read.AsyncWaitHandle)
                {
                    if (!read.AsyncWaitHandle.WaitOne(remaining)) throw new IOException("软件未响应现场采集请求。");
                    count = stream.EndRead(read);
                }
                if (count == 0) throw new IOException("软件已退出或中断采集连接。");
                pending.AddRange(buffer.Take(count));
            }
            throw new IOException("现场记录超过大小限制。");
        }

        internal object Capture(string directory, int pid, string mode)
        {
            if (mode != "folders" && mode != "drag") throw new ArgumentException("未知的现场类型。");
            string root = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar);
            var external = ExternalSnapshot(pid);
            try
            {
                using (var stream = new NamedPipeClientStream(".", "DDMonitorCE-diagnostics-" + pid, PipeDirection.InOut, PipeOptions.Asynchronous))
                {
                    lock (gate) { if (cancelled) throw new OperationCanceledException(); pipe = stream; }
                    stream.Connect(1200);
                    uint server;
                    if (!GetNamedPipeServerProcessId(stream.SafePipeHandle.DangerousGetHandle(), out server) || server != pid)
                        throw new IOException("采集接口与所选软件进程不匹配。");
                    byte[] request = Encoding.UTF8.GetBytes(json.Serialize(new { protocol = 1, mode }) + "\n");
                    stream.Write(request, 0, request.Length); stream.Flush();
                    var reply = json.Deserialize<Dictionary<string, object>>(ReadLine(stream, 6000));
                    if (Convert.ToString(reply["status"]) == "armed")
                        reply = json.Deserialize<Dictionary<string, object>>(ReadLine(stream, 65000));
                    if (Convert.ToString(reply["status"]) != "complete") throw new IOException("软件拒绝采集请求，可能已有另一项采集。");
                    if (Convert.ToInt32(reply["pid"]) != pid || Convert.ToInt32(reply["protocol"]) != 1
                        || !Path.GetFullPath(Convert.ToString(reply["root"])).TrimEnd(Path.DirectorySeparatorChar).Equals(root, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("现场来源与所选软件目录不匹配。");
                    return new { status = "captured", mode, captured_at = DateTimeOffset.Now.ToString("o"), host = reply, external };
                }
            }
            catch (Exception error)
            {
                lock (gate) if (cancelled) throw new OperationCanceledException();
                if (!(error is IOException || error is TimeoutException || error is UnauthorizedAccessException)) throw;
                return new { status = "external-only", mode, pid, captured_at = DateTimeOffset.Now.ToString("o"),
                    limitation = "未取得主程序内部状态：可能是旧版不支持、界面未响应或进程已退出。仅保存 Windows 窗口快照和已有日志，不能据此认定软件正常。",
                    reason = error.Message, external };
            }
            finally { lock (gate) pipe = null; }
        }

        public void Dispose()
        {
            lock (gate) { cancelled = true; if (pipe != null) pipe.Dispose(); }
        }
    }
}
