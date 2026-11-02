using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Diagnostics.Eventing.Reader;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Management;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace DDMonitorDiagnostics
{
    internal static class AppDiscovery
    {
        internal static bool HasApp(string path)
        {
            try { return Directory.Exists(path) && (File.Exists(Path.Combine(path, "main.py")) || File.Exists(Path.Combine(path, "ddm-build.json")) || Directory.GetFiles(path, "*.exe").Any(p => IsAppName(Path.GetFileNameWithoutExtension(p)))); }
            catch { return false; }
        }

        static bool IsAppName(string name)
        {
            return Regex.IsMatch(name, @"^(?:DD监控室(?:CE)?|DDMonitorCE)(?:-v[\d.]+)?$", RegexOptions.IgnoreCase);
        }

        internal static string[] Candidates(IEnumerable<string> paths)
        {
            var result = new List<string>();
            foreach (var path in paths)
                try
                {
                    if (string.IsNullOrWhiteSpace(path)) continue;
                    var full = Path.GetFullPath(path);
                    if (File.Exists(full)) full = Path.GetDirectoryName(full);
                    if (HasApp(full) && !result.Contains(full, StringComparer.OrdinalIgnoreCase)) result.Add(full);
                }
                catch { }
            return result.ToArray();
        }

        internal static string[] Find(string initial)
        {
            var paths = new List<string> { initial };
            foreach (var process in Process.GetProcesses())
                using (process)
                    try { if (IsAppName(process.ProcessName)) paths.Add(Path.GetDirectoryName(process.MainModule.FileName)); }
                    catch { }
            foreach (var hive in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
                foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
                    try
                    {
                        using (var registry = RegistryKey.OpenBaseKey(hive, view))
                        using (var uninstall = registry.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"))
                            if (uninstall != null)
                                foreach (var id in uninstall.GetSubKeyNames())
                                    using (var key = uninstall.OpenSubKey(id))
                                        if (key != null && Convert.ToString(key.GetValue("DisplayName")).StartsWith("DD监控室CE", StringComparison.OrdinalIgnoreCase))
                                            paths.Add(Convert.ToString(key.GetValue("InstallLocation")));
                    }
                    catch { }
            paths.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "DDMonitorCE"));
            paths.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "DDMonitorCE"));
            paths.AddRange(Nearby(initial));
            return Candidates(paths);
        }

        internal static string[] Nearby(string initial)
        {
            var full = Path.GetFullPath(initial);
            var directory = File.Exists(full) ? Path.GetDirectoryName(full) : full.TrimEnd('\\', '/');
            if (directory.Length < Path.GetPathRoot(full).Length) directory = Path.GetPathRoot(full);
            var paths = new List<string>();
            var roots = new List<string> { directory };
            // Only inspect nearby result/results folders, never recursively scan parent drives.
            for (int level = 0; level < 3 && directory != null; level++)
            {
                paths.Add(directory);
                if (new[] { "result", "results" }.Contains(Path.GetFileName(directory).ToLowerInvariant())) roots.Add(directory);
                foreach (var name in new[] { "result", "results" }) roots.Add(Path.Combine(directory, name));
                directory = Path.GetDirectoryName(directory);
            }
            var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var queue = new Queue<Tuple<string, int>>(roots.Select(p => Tuple.Create(p, 0)));
            while (queue.Count > 0 && visited.Count < 512)
            {
                var next = queue.Dequeue();
                if (!visited.Add(next.Item1)) continue;
                try
                {
                    if (!Directory.Exists(next.Item1) || (File.GetAttributes(next.Item1) & FileAttributes.ReparsePoint) != 0) continue;
                    if (HasApp(next.Item1)) { paths.Add(next.Item1); continue; }
                    if (next.Item2 >= 3) continue;
                    foreach (var child in Directory.EnumerateDirectories(next.Item1).Take(512))
                        if (!new[] { "utils", "cache", "logs", "plugins_user", "_internal", "work", ".git", ".venv" }.Contains(Path.GetFileName(child).ToLowerInvariant()))
                            queue.Enqueue(Tuple.Create(child, next.Item2 + 1));
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
            return Candidates(paths);
        }
    }

    internal static class ImageAttachment
    {
        internal const int MaximumCount = 5;
        internal const int MaximumBytes = 20 * 1024 * 1024;
        internal const int MaximumTotalBytes = 50 * 1024 * 1024;

        internal static byte[] Encode(string path)
        {
            var extension = Path.GetExtension(path).ToLowerInvariant();
            if (!new[] { ".png", ".jpg", ".jpeg", ".bmp", ".gif" }.Contains(extension)) throw new IOException("仅支持 PNG、JPG、BMP 或 GIF 图片。");
            using (var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (source.Length > MaximumBytes) throw new IOException("每张图片不能超过 20MB。");
                using (var image = Image.FromStream(source, true, true))
                {
                    if (image.Width > 8192 || image.Height > 8192 || (long)image.Width * image.Height > 40000000) throw new IOException("图片尺寸过大，请缩小后添加。");
                    // Render the first frame into a new PNG, omitting EXIF/location metadata.
                    using (var bitmap = new Bitmap(image.Width, image.Height))
                    using (var graphics = Graphics.FromImage(bitmap))
                    using (var output = new MemoryStream())
                    {
                        graphics.DrawImage(image, 0, 0, image.Width, image.Height);
                        bitmap.Save(output, ImageFormat.Png);
                        if (output.Length > MaximumBytes) throw new IOException("转换后的图片超过 20MB，请缩小后添加。");
                        return output.ToArray();
                    }
                }
            }
        }
    }

    internal sealed class Redactor
    {
        internal static readonly Regex Sensitive = new Regex(
            "password|passwd|pwd|token|secret|cookie|authorization|credential|sessdata|bili_jct|csrf|api.?key|access.?key|dedeuserid|buvid|account|oauth",
            RegexOptions.IgnoreCase);
        readonly HashSet<string> secrets = new HashSet<string>();

        internal void Remember(object value)
        {
            var map = value as IDictionary<string, object>;
            if (map != null) { foreach (var item in map.Values) Remember(item); return; }
            var list = value as IList;
            if (list != null) { foreach (var item in list) Remember(item); return; }
            var text = value as string;
            if (text != null && text.Length >= 4) secrets.Add(text);
        }

        internal object Clean(object value)
        {
            var map = value as IDictionary<string, object>;
            if (map != null)
            {
                var result = new Dictionary<string, object>();
                foreach (var pair in map)
                {
                    if (Sensitive.IsMatch(pair.Key) || pair.Key == "plugins")
                    {
                        Remember(pair.Value);
                        result[pair.Key] = "[已省略私密配置]";
                    }
                    else result[pair.Key] = Clean(pair.Value);
                }
                return result;
            }
            var list = value as IList;
            if (list != null) return list.Cast<object>().Select(Clean).ToArray();
            return value is string ? Text((string)value) : value;
        }

        internal string Text(string value)
        {
            if (value == null) return "";
            foreach (var secret in secrets.OrderByDescending(s => s.Length)) value = value.Replace(secret, "[凭据已脱敏]");
            // Logs can contain entire cookie dictionaries or signed playback URLs.
            value = Regex.Replace(value, @"(?im)^.*(?:password|passwd|\bpwd\b|token|secret|cookie|authorization|bearer|credential|sessdata|bili_jct|csrf|api.?key|access.?key|dedeuserid|buvid|oauth).*$(?:\r?\n[ \t]+.*)*", "[已省略可能含凭据的日志行]");
            value = Regex.Replace(value, @"(?i)\b(?:https?|rtmps?|wss?)://[^\s""<>]+", "[链接已脱敏]");
            value = Regex.Replace(value, @"(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n""<>|]*", "[本机路径]");
            foreach (var name in new[] { Environment.UserName, Environment.MachineName })
                if (name.Length >= 3) value = Regex.Replace(value, @"\b" + Regex.Escape(name) + @"\b", "[本机标识]", RegexOptions.IgnoreCase);
            return value;
        }
    }

    internal sealed class Collector
    {
        internal const string ToolVersion = "1.2";
        internal const int TextLimit = 2 * 1024 * 1024;
        internal const int ConfigLimit = 8 * 1024 * 1024;
        readonly string root;
        readonly string dataRoot;
        string recordingDirectory;
        readonly Redactor redact = new Redactor();
        readonly List<string> warnings = new List<string>();
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = 32 * 1024 * 1024, RecursionLimit = 100 };

        internal Collector(string directory, string userDataHome = null)
        {
            root = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar);
            if (!Directory.Exists(root)) throw new IOException("软件目录不存在。");
            if (!Safe(root)) throw new IOException("请选择实际软件目录，不要选择目录链接。");
            if (!File.Exists(Path.Combine(root, "main.py")) && !File.Exists(Path.Combine(root, "ddm-build.json")) && AppExecutables().Length == 0)
                throw new IOException("所选目录未找到 DD监控室CE 主程序或版本文件，请选择软件所在文件夹。");
            dataRoot = root;
            using (var hash = SHA256.Create())
            {
                var identity = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(root.ToLowerInvariant()))).Replace("-", "").ToLowerInvariant().Substring(0, 16);
                var home = userDataHome ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DDMonitorCE");
                var location = Path.Combine(home, "locations", identity + ".json");
                if (File.Exists(location))
                    try
                    {
                        if (new FileInfo(location).Length > 65536 || !SafeWithin(Path.GetDirectoryName(location), location)) throw new IOException();
                        var values = json.DeserializeObject(File.ReadAllText(location, Encoding.UTF8)) as IDictionary<string, object>;
                        var candidate = Path.GetFullPath(Convert.ToString(values["root"])).TrimEnd(Path.DirectorySeparatorChar);
                        if (!Directory.Exists(candidate) || !SafeWithin(candidate, candidate)) throw new IOException();
                        dataRoot = candidate;
                    }
                    catch { warnings.Add("独立数据目录不可读取，未回退收集旧配置或日志。"); dataRoot = null; }
            }
        }

        internal bool Safe(string path)
        {
            return SafeWithin(root, path);
        }

        static bool SafeWithin(string boundary, string path)
        {
            var full = Path.GetFullPath(path);
            if (boundary == null || (!full.Equals(boundary, StringComparison.OrdinalIgnoreCase) && !full.StartsWith(boundary + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))) return false;
            for (var item = new FileInfo(full) as FileSystemInfo; item != null; item = Directory.GetParent(item.FullName))
            {
                if ((File.Exists(item.FullName) || Directory.Exists(item.FullName)) && (File.GetAttributes(item.FullName) & FileAttributes.ReparsePoint) != 0) return false;
            }
            return true;
        }

        string[] AppExecutables()
        {
            return Directory.GetFiles(root, "*.exe").Where(p => Regex.IsMatch(Path.GetFileNameWithoutExtension(p), @"^(?:DD监控室(?:CE)?|DDMonitorCE)(?:-v[\d.]+)?$", RegexOptions.IgnoreCase)).ToArray();
        }

        string Read(string relative, int maximum, bool tail)
        {
            bool personal = relative.StartsWith("utils/") || relative.StartsWith("plugins_user/") || relative.StartsWith("logs/");
            var boundary = personal ? dataRoot : root;
            if (boundary == null) return null;
            var path = Path.Combine(boundary, relative);
            if (!File.Exists(path)) return null;
            if (!SafeWithin(boundary, path)) { warnings.Add(relative + "：跳过链接文件。"); return null; }
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            {
                if (stream.Length > maximum)
                {
                    if (!tail) { warnings.Add(relative + "：文件过大，未收集。"); return null; }
                    stream.Seek(-maximum, SeekOrigin.End);
                    warnings.Add(relative + "：仅收集末尾 2MB。");
                }
                using (var reader = new StreamReader(stream, Encoding.UTF8, true))
                {
                    var chars = new char[maximum];
                    int used = 0, count;
                    while (used < chars.Length && (count = reader.Read(chars, used, chars.Length - used)) > 0) used += count;
                    return new string(chars, 0, used);
                }
            }
        }

        object Config(string relative)
        {
            try
            {
                string text = Read(relative, ConfigLimit, false);
                if (text == null) return new { status = "missing_or_skipped" };
                var data = json.DeserializeObject(text);
                if (!(data is IDictionary<string, object>)) throw new FormatException();
                if (relative == "utils/config.json")
                {
                    var values = (IDictionary<string, object>)data;
                    object settingsValue, directoryValue;
                    if (values.TryGetValue("settings", out settingsValue))
                    {
                        var settings = settingsValue as IDictionary<string, object>;
                        if (settings != null && settings.TryGetValue("recording_dir", out directoryValue)
                            && directoryValue is string && !string.IsNullOrWhiteSpace((string)directoryValue))
                            recordingDirectory = Path.GetFullPath(Path.Combine(root, (string)directoryValue));
                    }
                }
                // Discover private values before sanitizing strings elsewhere in the config.
                RememberPrivate(data);
                return redact.Clean(data);
            }
            catch (Exception error)
            {
                warnings.Add(relative + "：读取或解析失败（" + error.GetType().Name + "），未收集原文。");
                return new { status = "unreadable_or_invalid" };
            }
        }

        void RememberPrivate(object value)
        {
            var map = value as IDictionary<string, object>;
            if (map != null)
                foreach (var pair in map)
                    if (Redactor.Sensitive.IsMatch(pair.Key) || pair.Key == "plugins") redact.Remember(pair.Value);
                    else RememberPrivate(pair.Value);
            var list = value as IList;
            if (list != null) foreach (var item in list) RememberPrivate(item);
        }

        object Software()
        {
            var files = new List<object>();
            var names = AppExecutables().Select(Path.GetFileName).Concat(new[] {
                "ddm-build.json", "ddm-program-inventory.json", "ddm/version.py", "main.py", "ffmpeg.exe",
                "libmpv-2.dll", "_internal/libmpv-2.dll", "_internal/python313.dll", "_internal/python312.dll",
                "_internal/PySide6/Qt6Core.dll", "_internal/PySide6/Qt6Gui.dll", "_internal/PySide6/Qt6Quick.dll",
                "_internal/PySide6/plugins/platforms/qwindows.dll" });
            foreach (var name in names)
            {
                var path = Path.Combine(root, name.Replace('/', Path.DirectorySeparatorChar));
                var exists = File.Exists(path) && Safe(path);
                var row = new Dictionary<string, object> { { "file", name }, { "present", exists } };
                if (exists)
                {
                    try
                    {
                        var info = new FileInfo(path);
                        row["size"] = info.Length;
                        row["modified_utc"] = info.LastWriteTimeUtc.ToString("o");
                        row["file_version"] = FileVersionInfo.GetVersionInfo(path).FileVersion;
                        if (info.Length <= 256 * 1024 * 1024)
                            using (var hash = SHA256.Create())
                            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                                row["sha256"] = BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
                    }
                    catch (Exception error) { warnings.Add(name + "：元数据读取失败（" + error.GetType().Name + "）。"); }
                }
                files.Add(row);
            }
            var metadata = new Dictionary<string, object> { { "files", files } };
            foreach (var file in new[] { "ddm-build.json", "ddm-program-inventory.json" })
                try
                {
                    var text = Read(file, ConfigLimit, false);
                    if (text == null) continue;
                    var data = json.DeserializeObject(text) as IDictionary<string, object>;
                    if (data == null) throw new FormatException();
                    metadata[file] = data.Where(p => new[] { "version", "schema", "platform", "update_protocol" }.Contains(p.Key)).ToDictionary(p => p.Key, p => p.Value);
                    if (file == "ddm-program-inventory.json" && data.ContainsKey("files"))
                    {
                        var inventory = data["files"] as object[];
                        if (inventory != null)
                        {
                            var missing = new List<string>();
                            foreach (var entry in inventory.Take(20000))
                            {
                                var relative = entry as string;
                                if (relative == null || Path.IsPathRooted(relative) || relative.Split('/', '\\').Any(p => p == "..")) continue;
                                var path = Path.Combine(root, relative);
                                if (Safe(path) && !File.Exists(path)) missing.Add(relative);
                            }
                            metadata["inventory_missing"] = missing.Take(100).ToArray();
                            metadata["inventory_missing_count"] = missing.Count;
                        }
                    }
                }
                catch (Exception error) { warnings.Add(file + "：无法解析（" + error.GetType().Name + "）。"); }
            var source = Read("ddm/version.py", 32768, false);
            if (source != null) metadata["source_version"] = Regex.Match(source, "(?m)^VERSION\\s*=\\s*[\"']([^\"']+)").Groups[1].Value;
            var notes = Directory.GetFiles(root, "RELEASE*.md").Take(10).Select(Path.GetFileName).ToArray();
            metadata["release_notes_files"] = notes;
            metadata["release_notes_headings"] = notes.Select(n => {
                try { return (Read(n, TextLimit, false) ?? "").Split('\n').FirstOrDefault(s => s.StartsWith("#")) ?? ""; }
                catch { return "[无法读取]"; }
            }).ToArray();
            return metadata;
        }

        object Plugins()
        {
            var result = new List<object>();
            if (dataRoot == null) return result;
            var folder = Path.Combine(dataRoot, "plugins_user");
            if (!Directory.Exists(folder) || !SafeWithin(dataRoot, folder)) return result;
            foreach (var directory in Directory.GetDirectories(folder).Take(100))
            {
                var id = Path.GetFileName(directory);
                if (!Regex.IsMatch(id, "^[a-z][a-z0-9_]*$") || !SafeWithin(dataRoot, directory)) continue;
                try
                {
                    var text = Read("plugins_user/" + id + "/plugin.json", 262144, false);
                    var data = text == null ? null : json.DeserializeObject(text) as IDictionary<string, object>;
                    result.Add(new { id, version = data != null && data.ContainsKey("version") ? Convert.ToString(data["version"]) : "unknown" });
                }
                catch { warnings.Add("插件 " + id + "：无法读取版本清单。"); }
            }
            return result;
        }

        object SystemInfo()
        {
            var result = new Dictionary<string, object> { { "os_64bit", Environment.Is64BitOperatingSystem }, { "clr", Environment.Version.ToString() } };
            using (var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion"))
                if (key != null)
                    foreach (var name in new[] { "ProductName", "DisplayVersion", "CurrentBuildNumber", "UBR", "EditionID" }) result[name] = key.GetValue(name);
            foreach (var item in new[] {
                new[] { "Win32_OperatingSystem", "Caption,Version,BuildNumber,OSArchitecture,TotalVisibleMemorySize,FreePhysicalMemory" },
                new[] { "Win32_Processor", "Name,NumberOfCores,NumberOfLogicalProcessors" },
                new[] { "Win32_VideoController", "Name,DriverVersion,DriverDate,AdapterRAM,CurrentHorizontalResolution,CurrentVerticalResolution" } })
            {
                try
                {
                    using (var query = new ManagementObjectSearcher("SELECT " + item[1] + " FROM " + item[0]))
                    {
                        query.Options.Timeout = TimeSpan.FromSeconds(10);
                        var rows = new List<object>();
                        using (var values = query.Get())
                            foreach (ManagementObject value in values)
                                using (value) rows.Add(item[1].Split(',').ToDictionary(name => name, name => value[name]));
                        result[item[0]] = rows;
                    }
                }
                catch (Exception error) { warnings.Add(item[0] + "：系统信息不可用（" + error.GetType().Name + "）。"); }
            }
            return result;
        }

        object Processes()
        {
            var names = AppExecutables().Select(Path.GetFileNameWithoutExtension).ToArray();
            var rows = new List<object>();
            foreach (var name in names)
                foreach (var process in Process.GetProcessesByName(name))
                    using (process)
                        try
                        {
                            if (!Path.GetFullPath(process.MainModule.FileName).Equals(Path.Combine(root, name + ".exe"), StringComparison.OrdinalIgnoreCase)) continue;
                            rows.Add(new { name, pid = process.Id, memory_bytes = process.WorkingSet64, started = process.StartTime.ToString("o") });
                        }
                        catch { warnings.Add("相关进程状态不可读取。"); }
            return rows;
        }

        object CrashEvents()
        {
            var result = new List<object>();
            try
            {
                var query = new EventLogQuery("Application", PathType.LogName,
                    "*[System[(EventID=1000 or EventID=1001 or EventID=1002 or EventID=1026) and TimeCreated[timediff(@SystemTime) <= 604800000]]]") { ReverseDirection = true };
                using (var reader = new EventLogReader(query))
                    for (int scanned = 0; scanned < 1000 && result.Count < 30; scanned++)
                    {
                        using (var entry = reader.ReadEvent(TimeSpan.FromSeconds(3)))
                        {
                            if (entry == null) break;
                            // Match the selected installation path, not crashes from unrelated apps.
                            var values = entry.Properties.Select(p => Convert.ToString(p.Value)).ToArray();
                            if (!values.Any(v => v.IndexOf(root + "\\", StringComparison.OrdinalIgnoreCase) >= 0)) continue;
                            result.Add(new { id = entry.Id, time = entry.TimeCreated.HasValue ? entry.TimeCreated.Value.ToString("o") : "", provider = entry.ProviderName, fields = values.Select(redact.Text).ToArray() });
                        }
                    }
            }
            catch (Exception error) { warnings.Add("崩溃事件不可读取（" + error.GetType().Name + "）；其余内容仍已收集。"); }
            return result;
        }

        internal string Collect(string destination, string problem, string happened, Action<int, string> progress,
            string reproducibility = "尚未确认", string[] attachments = null)
        {
            if (!new[] { "稳定复现", "概率触发", "尚未确认" }.Contains(reproducibility)) throw new ArgumentException("请选择有效的复现情况。");
            attachments = attachments ?? new string[0];
            if (attachments.Length > ImageAttachment.MaximumCount) throw new IOException("最多添加 5 张图片。");
            var images = new Dictionary<string, byte[]>();
            foreach (var path in attachments)
            {
                images["attachments/image-" + (images.Count + 1).ToString("00") + ".png"] = ImageAttachment.Encode(path);
                if (images.Values.Sum(bytes => bytes.Length) > ImageAttachment.MaximumTotalBytes) throw new IOException("图片附件合计不能超过 50MB，请减少或缩小图片。");
            }
            progress(5, "读取并脱敏配置…");
            var config = Config("utils/config.json");
            var backup = Config("utils/config.json.bak");
            // Apply values found in the backup to the primary config as well.
            config = redact.Clean(config);
            var entries = new Dictionary<string, string>();
            Action<string, object> add = (name, value) => entries[name] = json.Serialize(redact.Clean(value));
            Action<string, Func<object>> section = (name, collect) => {
                try { add(name, collect()); }
                catch (Exception error)
                {
                    warnings.Add(name + "：收集失败（" + error.GetType().Name + "），其余内容继续收集。");
                    add(name, new { status = "unavailable", error_type = error.GetType().Name });
                }
            };
            add("config/current.json", config);
            add("config/backup.json", backup);
            add("problem.json", new { description = problem, happened, reproducibility, attachments = images.Keys.ToArray(), collected = DateTimeOffset.Now.ToString("o"), tool_version = ToolVersion });
            progress(20, "核对软件版本和关键文件…");
            section("software.json", Software);
            progress(30, "检查播放器 DLL 加载及直接依赖…");
            Dictionary<string, object> native = null;
            section("native-dependencies.json", () => native = NativeDependencies.Collect(root));
            section("plugins.json", Plugins);
            progress(40, "读取系统、显卡与相关进程…");
            section("system.json", SystemInfo);
            section("processes.json", Processes);
            progress(60, "筛选近期日志与崩溃事件…");
            var logs = dataRoot == null ? null : Path.Combine(dataRoot, "logs");
            try
            {
                if (logs != null && Directory.Exists(logs) && SafeWithin(dataRoot, logs))
                    foreach (var path in Directory.GetFiles(logs).Where(p => Regex.IsMatch(Path.GetFileName(p), @"^(ddm(?:-\d{4}-\d{2}-\d{2}|-crash)?\.log(?:\.[1-5])?|(?:update[^\\/]*|updater[^\\/]*)\.log)$", RegexOptions.IgnoreCase)).OrderByDescending(p => Path.GetFileName(p).Equals("ddm-crash.log", StringComparison.OrdinalIgnoreCase)).ThenByDescending(File.GetLastWriteTimeUtc).Take(5))
                        AddLog(entries, "logs/" + Path.GetFileName(path));
            }
            catch (Exception error) { warnings.Add("日志目录无法枚举（" + error.GetType().Name + "）。"); }
            AddLog(entries, "ddm-pyinstaller-paths.txt");
            section("recording-diagnostics.json", () => RecordingLogs(entries));
            section("platform-diagnostics.json", () => PlatformDiagnostics(entries));
            section("crash-events.json", CrashEvents);
            add("collection.json", new { schema = 1, warnings, limits = "最多5份近期主程序日志及5份录制FFmpeg日志，每份末尾2MB；7天内最多30条匹配安装路径的崩溃事件。", privacy = "不读取账号文件、插件私有配置、聊天记录、录制视频、缓存或内存转储；仅读取配置指定录制目录.ddm-parts内的近期FFmpeg日志；图片仅包含手动选择的附件，移除元数据但不遮挡画面内容；不联网、不启动或关闭软件。" });
            entries["诊断摘要.txt"] = "DD监控室CE 诊断快照 v" + ToolVersion + "\r\n生成时间：" + DateTimeOffset.Now.ToString("o") +
                "\r\n\r\n问题：" + redact.Text(problem) + "\r\n发生时间：" + redact.Text(happened) +
                "\r\n复现情况：" + reproducibility + "\r\n图片附件：" + images.Count + " 张（转为PNG，移除元数据；画面内容未自动脱敏）。" +
                "\r\n\r\n" + (native == null ? "libmpv 检查未完成，见收集提示。" : redact.Text(NativeDependencies.Summary(native))) +
                "\r\n\r\nplatform-diagnostics.json：平台响应、查询、取流和播放器错误的已有日志摘要，无需手工筛选；缺少记录不代表正常，不自动判定根因。" +
                "\r\nrecording-diagnostics.json、recording/：近期录制FFmpeg日志及HTTP拒绝、地址到期时间摘要，签名地址已脱敏，不包含录制视频。" +
                "\r\n\r\nsoftware.json：软件版本、关键文件SHA256和清单缺失项（存在性不等于完整性验证）。\r\nnative-dependencies.json：隔离子进程中的 libmpv 加载、Win32错误码、直接依赖与函数入口检查。\r\nsystem.json：Windows、CPU、内存、显卡驱动。\r\nconfig/：脱敏配置；plugins.json：插件版本。\r\nlogs/：近期日志；crash-events.json：相关Windows崩溃事件。\r\n" +
                "未找到崩溃事件不表示软件未崩溃；这是现有线索快照，不能还原崩溃前内存。\r\n请检查诊断包后手动发送给维护者，工具不会自动上传。\r\n\r\n收集提示：\r\n" + (warnings.Count == 0 ? "无。" : string.Join("\r\n", warnings.Select(redact.Text)));
            progress(85, "写入诊断 ZIP…");
            var output = Path.Combine(Path.GetFullPath(destination), "DDMonitorCE-diagnostics-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N").Substring(0, 6) + ".zip");
            // CreateNew prevents overwriting any existing user file. No raw staging files.
            using (var stream = new FileStream(output, FileMode.CreateNew, FileAccess.Write))
            {
                try
                {
                    using (var zip = new ZipArchive(stream, ZipArchiveMode.Create, true))
                    {
                        foreach (var entry in entries)
                            using (var writer = new StreamWriter(zip.CreateEntry(entry.Key, CompressionLevel.Optimal).Open(), new UTF8Encoding(false))) writer.Write(entry.Value);
                        foreach (var image in images)
                            using (var target = zip.CreateEntry(image.Key, CompressionLevel.Optimal).Open()) target.Write(image.Value, 0, image.Value.Length);
                    }
                }
                catch { stream.Close(); File.Delete(output); throw; }
            }
            progress(100, "诊断包已生成，请检查后手动发送。");
            return output;
        }

        object RecordingLogs(Dictionary<string, string> entries)
        {
            var result = new List<object>();
            if (string.IsNullOrEmpty(recordingDirectory)) return new { status = "not_configured", files = result };
            var folder = Path.Combine(recordingDirectory, ".ddm-parts");
            if (!Directory.Exists(folder)) return new { status = "missing", files = result };
            if (!SafeWithin(folder, folder)) throw new IOException("录制日志目录为链接。");
            foreach (var path in Directory.GetFiles(folder, "*.log").OrderByDescending(File.GetLastWriteTimeUtc).Take(5))
            {
                if (!SafeWithin(folder, path)) { warnings.Add("录制日志：跳过链接文件。"); continue; }
                try
                {
                    string text;
                    using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                    {
                        stream.Seek(Math.Max(0, stream.Length - TextLimit), SeekOrigin.Begin);
                        using (var reader = new StreamReader(stream, Encoding.UTF8, true)) text = reader.ReadToEnd();
                    }
                    var name = "recording/ffmpeg-" + (result.Count + 1).ToString("00") + ".log";
                    entries[name] = redact.Text(text);
                    var expires = Regex.Matches(text, @"[?&]expires=(\d{9,12})(?:&|\s|$)").Cast<Match>()
                        .Select(m => m.Groups[1].Value).Distinct().Take(10).ToArray();
                    result.Add(new { log = name, http_403 = text.IndexOf("403 Forbidden", StringComparison.OrdinalIgnoreCase) >= 0,
                        expires_unix_seconds = expires, modified_utc = File.GetLastWriteTimeUtc(path).ToString("o") });
                }
                catch (Exception error) { warnings.Add("录制日志：读取失败（" + error.GetType().Name + "）。"); }
            }
            return new { status = result.Count == 0 ? "not_recorded" : "observed", files = result };
        }

        void AddLog(Dictionary<string, string> entries, string relative)
        {
            try
            {
                var text = Read(relative, TextLimit, true);
                if (text != null) entries[relative] = redact.Text(text);
            }
            catch (Exception error) { warnings.Add(relative + "：读取失败（" + error.GetType().Name + "）。"); }
        }

        object PlatformDiagnostics(Dictionary<string, string> entries)
        {
            // Reuse the bounded, already-redacted log copies. Never load plugins or make requests.
            var events = new List<object>();
            var counts = new Dictionary<string, int>();
            foreach (var entry in entries.Where(p => p.Key.StartsWith("logs/")).OrderBy(p => p.Key, StringComparer.Ordinal))
            {
                var lines = entry.Value.Split('\n');
                for (int index = 0; index < lines.Length; index++)
                {
                    var line = lines[index].TrimEnd('\r');
                    if (!Regex.IsMatch(line, @"\[(?:Issue13-test\d+|平台诊断|状态刷新失败|取流失败|画质档位)\]")) continue;
                    var stage = Regex.Match(line, @"阶段=(\w+)");
                    var category = stage.Success ? stage.Groups[1].Value :
                        line.Contains("[画质档位]") ? "source_ready" : "failure_summary";
                    counts[category] = counts.ContainsKey(category) ? counts[category] + 1 : 1;
                    events.Add(new { log = entry.Key, line = index + 1, stage = category, text = line });
                }
            }
            return new { status = events.Count == 0 ? "not_recorded" : "observed", counts,
                events = events.Skip(Math.Max(0, events.Count - 1000)).ToArray(),
                note = "仅汇总已有日志；未记录某阶段不代表正常。记录位于日志截取范围内，行号对应包内日志。" };
        }
    }
}
