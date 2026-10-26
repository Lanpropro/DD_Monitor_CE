using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace DDMonitorDiagnostics
{
    // DLL initialization runs only in a disposable child, never in the collector GUI.
    internal static class NativeDependencies
    {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr LoadLibraryEx(string path, IntPtr reserved, uint flags);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr AddDllDirectory(string directory);
        [DllImport("kernel32.dll")] static extern bool RemoveDllDirectory(IntPtr cookie);
        [DllImport("kernel32.dll")] static extern bool FreeLibrary(IntPtr module);
        [DllImport("kernel32.dll")] static extern uint SetErrorMode(uint mode);
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true)]
        static extern IntPtr GetProcAddress(IntPtr module, string name);
        [DllImport("kernel32.dll", EntryPoint = "GetProcAddress", ExactSpelling = true)]
        static extern IntPtr GetOrdinal(IntPtr module, IntPtr ordinal);

        internal sealed class Import
        {
            internal string Name;
            internal readonly List<string> Symbols = new List<string>();
        }

        internal static List<Import> ReadImports(byte[] bytes, out ushort machine)
        {
            if (bytes.Length < 64 || BitConverter.ToUInt16(bytes, 0) != 0x5a4d) throw new InvalidDataException("Not PE");
            int pe = checked((int)BitConverter.ToUInt32(bytes, 60));
            if (BitConverter.ToUInt32(bytes, pe) != 0x4550) throw new InvalidDataException("PE signature");
            machine = BitConverter.ToUInt16(bytes, pe + 4);
            int sections = BitConverter.ToUInt16(bytes, pe + 6);
            int optional = pe + 24, table = optional + BitConverter.ToUInt16(bytes, pe + 20);
            ushort magic = BitConverter.ToUInt16(bytes, optional);
            if (sections > 96 || (magic != 0x20b && magic != 0x10b)) throw new InvalidDataException("PE headers");
            Func<uint, int> offset = rva => {
                for (int i = 0; i < sections; i++)
                {
                    int entry = checked(table + i * 40);
                    uint start = BitConverter.ToUInt32(bytes, entry + 12), size = BitConverter.ToUInt32(bytes, entry + 16);
                    if (rva >= start && (ulong)rva < (ulong)start + size)
                    {
                        int result = checked((int)((ulong)BitConverter.ToUInt32(bytes, entry + 20) + rva - start));
                        if (result < bytes.Length) return result;
                    }
                }
                throw new InvalidDataException("Invalid RVA");
            };
            Func<int, string> text = at => {
                int end = at;
                while (end < bytes.Length && end - at < 1024 && bytes[end] != 0) end++;
                if (end == bytes.Length || end - at == 1024) throw new InvalidDataException("PE string");
                return Encoding.ASCII.GetString(bytes, at, end - at);
            };
            var imports = new List<Import>();
            uint directory = BitConverter.ToUInt32(bytes, optional + (magic == 0x20b ? 112 : 96) + 8);
            if (directory == 0) return imports;
            int descriptor = offset(directory), symbols = 0;
            for (int n = 0; n < 128; n++, descriptor = checked(descriptor + 20))
            {
                uint name = BitConverter.ToUInt32(bytes, descriptor + 12);
                if (name == 0) return imports;
                var import = new Import { Name = text(offset(name)) };
                if (!Regex.IsMatch(import.Name, @"^[a-zA-Z0-9_.-]+\.dll$", RegexOptions.IgnoreCase)) throw new InvalidDataException("Import name");
                uint thunk = BitConverter.ToUInt32(bytes, descriptor);
                if (thunk == 0) thunk = BitConverter.ToUInt32(bytes, descriptor + 16);
                int at = offset(thunk), stride = magic == 0x20b ? 8 : 4;
                for (; ; at = checked(at + stride))
                {
                    ulong symbol = stride == 8 ? BitConverter.ToUInt64(bytes, at) : BitConverter.ToUInt32(bytes, at);
                    if (symbol == 0) break;
                    if (++symbols > 4096) throw new InvalidDataException("Import limit");
                    ulong ordinal = stride == 8 ? 0x8000000000000000UL : 0x80000000UL;
                    import.Symbols.Add((symbol & ordinal) != 0 ? "#" + (symbol & 0xffff) : text(checked(offset(checked((uint)symbol)) + 2)));
                }
                imports.Add(import);
            }
            throw new InvalidDataException("Import directory limit");
        }

        static Dictionary<string, object> Result(string status) { return new Dictionary<string, object> { { "status", status } }; }

        internal static Dictionary<string, object> Inspect(string root)
        {
            var collector = new Collector(root);
            string library = new[] { "_internal/libmpv-2.dll", "libmpv-2.dll" }
                .Select(p => Path.Combine(root, p.Replace('/', Path.DirectorySeparatorChar))).FirstOrDefault(File.Exists);
            if (library == null) return Result("not_present");
            if (!collector.Safe(library)) return Result("link_skipped");
            ushort machine;
            List<Import> imports;
            try
            {
                if (new FileInfo(library).Length > 256L * 1024 * 1024) return Result("file_too_large");
                imports = ReadImports(File.ReadAllBytes(library), out machine);
            }
            catch (Exception error) { var invalid = Result("invalid_pe"); invalid["error_type"] = error.GetType().Name; return invalid; }
            if ((machine != 0x8664 && machine != 0x14c) || (machine == 0x8664) != Environment.Is64BitProcess)
                return Result("architecture_mismatch");
            string directory = Path.GetDirectoryName(library);
            // Reject linked private dependencies before allowing the Windows loader to use them.
            if (imports.Any(i => File.Exists(Path.Combine(directory, i.Name)) && !collector.Safe(Path.Combine(directory, i.Name))))
                return Result("link_skipped");
            var report = Result("load_failed");
            report["library"] = library;
            report["architecture"] = Environment.Is64BitProcess ? "x64" : "x86";
            report["vulkan_system_present"] = File.Exists(Path.Combine(Environment.SystemDirectory, "vulkan-1.dll"));
            report["vulkan_application_present"] = File.Exists(Path.Combine(directory, "vulkan-1.dll"));
            SetErrorMode(0x8003);
            IntPtr cookie = AddDllDirectory(directory);
            if (cookie == IntPtr.Zero) { report["win32_error"] = Marshal.GetLastWin32Error(); return report; }
            try
            {
                IntPtr module = LoadLibraryEx(library, IntPtr.Zero, 0x1100);
                int code = module == IntPtr.Zero ? Marshal.GetLastWin32Error() : 0;
                report["status"] = module == IntPtr.Zero ? "load_failed" : "loaded";
                report["win32_error"] = code;
                report["message"] = code == 0 ? "DLL 加载成功" : new Win32Exception(code).Message;
                if (module != IntPtr.Zero) FreeLibrary(module);
                var dependencies = new List<object>();
                foreach (var import in imports)
                {
                    module = LoadLibraryEx(import.Name, IntPtr.Zero, 0x1000);
                    code = module == IntPtr.Zero ? Marshal.GetLastWin32Error() : 0;
                    var row = new Dictionary<string, object> { { "name", import.Name }, { "win32_error", code } };
                    var missing = new List<string>();
                    if (module != IntPtr.Zero)
                        try
                        {
                            foreach (var symbol in import.Symbols)
                                if ((symbol.StartsWith("#") ? GetOrdinal(module, new IntPtr(int.Parse(symbol.Substring(1)))) : GetProcAddress(module, symbol)) == IntPtr.Zero)
                                    missing.Add(symbol);
                        }
                        finally { FreeLibrary(module); }
                    row["status"] = code != 0 ? "load_failed" : missing.Count > 0 ? "missing_exports" : "loaded";
                    row["missing_exports"] = missing.ToArray();
                    row["message"] = code == 0 ? "" : new Win32Exception(code).Message;
                    dependencies.Add(row);
                }
                report["dependencies"] = dependencies;
            }
            finally { RemoveDllDirectory(cookie); }
            return report;
        }

        internal static bool TryRun(string[] args)
        {
            if (args.Length != 2 || args[0] != "--native-probe") return false;
            SetErrorMode(0x8003);
            Dictionary<string, object> result;
            try { result = Inspect(args[1]); }
            catch (Exception error) { result = Result("unavailable"); result["error_type"] = error.GetType().Name; }
            // A windowed executable has no console code page; write UTF-8 to the
            // inherited pipe directly instead of setting Console.OutputEncoding.
            using (var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)))
                output.WriteLine(new JavaScriptSerializer().Serialize(result));
            return true;
        }

        internal static Dictionary<string, object> Collect(string root, int timeout = 10000)
        {
            var info = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location, "--native-probe \"" + root + "\\.\"") {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8
            };
            var output = new StringBuilder();
            using (var process = new Process { StartInfo = info })
            {
                process.OutputDataReceived += (s, e) => { if (e.Data != null) lock (output) { if (output.Length < 1024 * 1024) output.AppendLine(e.Data); } };
                process.ErrorDataReceived += (s, e) => { };
                process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
                if (!process.WaitForExit(timeout)) { process.Kill(); process.WaitForExit(); return Result("timeout"); }
                process.WaitForExit(); // Drain redirected asynchronous output.
                if (process.ExitCode != 0) { var crashed = Result("probe_crashed"); crashed["exit_code"] = process.ExitCode; return crashed; }
                try { return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(output.ToString()); }
                catch { return Result("invalid_probe_output"); }
            }
        }

        internal static string Summary(Dictionary<string, object> report)
        {
            string status = Convert.ToString(report["status"]);
            var issues = new List<string>();
            object rows;
            if (report.TryGetValue("dependencies", out rows))
                foreach (var row in (System.Collections.IEnumerable)rows)
                {
                    var item = row as IDictionary<string, object>;
                    if (item != null && Convert.ToString(item["status"]) != "loaded")
                        issues.Add(Convert.ToString(item["name"]) + "：" + Convert.ToString(item["status"]));
                }
            return "libmpv 检查：" + status + (issues.Count == 0 ? "" : "；依赖异常：" + string.Join("，", issues)) +
                "。详细错误码和缺少的函数入口见 native-dependencies.json。";
        }
    }
}
