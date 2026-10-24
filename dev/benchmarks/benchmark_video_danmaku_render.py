"""Four local 1080p videos with deterministic sustained danmaku and optional ETW capture.

Qt callbacks and native frame counters describe work submitted, never final display acceptance.
"""
import argparse
from collections import deque
from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

PRESENTMON_SHA256 = "b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def benchmark_window_state(defaults):
    return {"plugins_enabled": [],
            "settings": dict(defaults, auto_update=False, preview_on_hover=False)}


def qpc_clock():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    value, frequency = ctypes.c_longlong(), ctypes.c_longlong()
    if not kernel.QueryPerformanceCounter(ctypes.byref(value)) or not kernel.QueryPerformanceFrequency(ctypes.byref(frequency)):
        raise OSError("QueryPerformanceCounter/Frequency failed")
    return value.value, frequency.value


def wait_for_presentmon(csv_path, app, process, timeout=30):
    """Wait for an actual displayed row belonging to this benchmark process."""
    import csv
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if process and process.poll() not in (None, 0):
            return {"status": "unverified", "reason": "PresentMon exited before a displayed row"}
        try:
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    if (row.get("ProcessID") == str(os.getpid()) and row.get("CPUStartQPC")
                            and row.get("DisplayedTime") not in (None, "NA", "")):
                        value = int(row["CPUStartQPC"])
                        if float(row["DisplayedTime"]) > 0:
                            return {"status": "observed", "observed_qpc": qpc_clock()[0],
                                    "row_cpu_start_qpc": value, "process_id": os.getpid()}
        except (OSError, ValueError, TypeError):
            pass
        time.sleep(.05)
    return {"status": "unverified", "reason": "No flushed displayed raw-QPC row for benchmark PID within timeout"}


def native_binary_provenance():
    module = sys.modules.get("ddm._native_danmaku")
    filename = getattr(module, "__file__", None)
    if not filename:
        return None
    path = Path(filename).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class DisplayStatisticsRecorder:
    def __init__(self, host, path):
        self.host = host
        self.path = path
        self.cursor = 0
        self.lost = 0
        self.errors = []
        self.handle = path.open("w", encoding="utf-8")

    def sample(self):
        if self.errors:
            return
        try:
            for _ in range(8):
                page = self.host.display_statistics(self.cursor, 8192)
                records = page.get("samples", [])
                self.lost += page.get("lost_count", 0)
                page.update(process_id=os.getpid(), poll_qpc=qpc_clock()[0], after_sequence=self.cursor)
                self.handle.write(json.dumps(page, ensure_ascii=False) + "\n")
                self.handle.flush()
                if records:
                    self.cursor = records[-1]["record_sequence"]
                if self.cursor >= page["latest_sequence"]:
                    return
                if not records:
                    raise ValueError("Native display statistics pagination made no progress")
            raise ValueError("Native display statistics backlog exceeds bounded drain")
        except Exception as error:
            self.errors.append(f"{type(error).__name__}: {error}")

    def close(self):
        if not self.handle.closed:
            self.handle.close()

    def summary(self):
        return {"display_statistics": str(self.path.resolve()),
                "display_statistics_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                "display_statistics_status": "unverified" if self.errors or self.lost else "observed",
                "display_statistics_errors": self.errors, "display_statistics_lost_count": self.lost,
                "display_statistics_latest_sequence": self.cursor}


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
        "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
        "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


class ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class ResourceSampler:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for name in ("Process32FirstW", "Process32NextW"):
            getattr(self.kernel, name).argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        self.kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        self.current = self.kernel.GetCurrentProcess()
        self.dwm_handle = None
        self.dwm_pid = None
        self.dwm_reason = "No accessible DWM process in the current session"
        session = wintypes.DWORD()
        self.kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
        snapshot = self.kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot != ctypes.c_void_p(-1).value:
            try:
                entry = ProcessEntry()
                entry.dwSize = ctypes.sizeof(entry)
                available = self.kernel.Process32FirstW(snapshot, ctypes.byref(entry))
                while available:
                    candidate_session = wintypes.DWORD()
                    if entry.szExeFile.lower() == "dwm.exe":
                        queried = self.kernel.ProcessIdToSessionId(entry.th32ProcessID, ctypes.byref(candidate_session))
                        if not queried:
                            self.dwm_pid = entry.th32ProcessID
                            self.dwm_reason = f"DWM session lookup unavailable, Win32 error {ctypes.get_last_error()}"
                        elif candidate_session.value == session.value:
                            self.dwm_pid = entry.th32ProcessID
                            self.dwm_handle = self.kernel.OpenProcess(0x1000, False, self.dwm_pid)
                            if not self.dwm_handle:
                                self.dwm_reason = f"DWM OpenProcess unavailable, Win32 error {ctypes.get_last_error()}"
                            break
                    available = self.kernel.Process32NextW(snapshot, ctypes.byref(entry))
            finally:
                self.kernel.CloseHandle(snapshot)
        self.previous = None

    def reset(self):
        self.previous = None

    def cpu_seconds(self, handle):
        times = [wintypes.FILETIME() for _ in range(4)]
        if not handle or not self.kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            return None
        return sum((value.dwHighDateTime << 32) + value.dwLowDateTime for value in times[2:]) / 1e7

    def sample(self, elapsed):
        memory = ProcessMemoryCounters()
        memory.cb = ctypes.sizeof(memory)
        valid = self.psapi.GetProcessMemoryInfo(self.current, ctypes.byref(memory), memory.cb)
        own_cpu, dwm_cpu = self.cpu_seconds(self.current), self.cpu_seconds(self.dwm_handle)
        result = {"elapsed_seconds": elapsed, "working_set_bytes": memory.WorkingSetSize if valid else None,
            "private_bytes": memory.PrivateUsage if valid else None,
            "memory_error": None if valid else ctypes.get_last_error(),
            "process_cpu_seconds": own_cpu, "dwm_cpu_seconds": dwm_cpu,
            "dwm_pid": self.dwm_pid, "dwm_cpu_status": "available" if dwm_cpu is not None else "unverified",
            "dwm_cpu_reason": None if dwm_cpu is not None else self.dwm_reason,
            "process_cpu_percent_one_core": None, "dwm_cpu_percent_one_core": None}
        if self.previous:
            interval = elapsed - self.previous["elapsed_seconds"]
            if interval > 0:
                for prefix in ("process", "dwm"):
                    current, previous = result[f"{prefix}_cpu_seconds"], self.previous[f"{prefix}_cpu_seconds"]
                    if current is not None and previous is not None:
                        result[f"{prefix}_cpu_percent_one_core"] = (current - previous) / interval * 100
        self.previous = result
        return result

    def close(self):
        if self.dwm_handle:
            self.kernel.CloseHandle(self.dwm_handle)
            self.dwm_handle = None


def memory_trend(samples, field):
    values = [(sample["elapsed_seconds"], sample[field]) for sample in samples if sample.get(field) is not None]
    if not values:
        return {"status": "unverified"}
    steady = values[len(values) // 5:]
    slope = statistics.linear_regression(*zip(*steady)).slope if len(steady) > 1 else None
    return {"first_bytes": values[0][1], "last_bytes": values[-1][1],
            "peak_bytes": max(value for _, value in values), "tail_80_percent_bytes_per_second": slope,
            "status": "observed; trend is diagnostic, no automatic stability acceptance"}


def drop_stage_counters(rejected, start, end):
    before, after = start.get("counters", {}), end.get("counters", {})
    return {"add_event_rejected": rejected,
            "prepare_failures_including_native_queue_rejections": end.get("dropped_prepare", 0) - start.get("dropped_prepare", 0) if end else None,
            "native_submission_failures": {key: value - before.get(key, 0) for key, value in after.items() if key.startswith("dropped_")},
            "replacement_failures": None}


def preparation_memory(native):
    if native is None:
        return {"metadata_entries": 0, "python_metadata_bytes_estimate": 0,
                "prepare_pending": 0, "prepare_ready_pixel_bytes": 0, "prepare_unfinished_jobs": 0}
    entries = native.entries
    estimated = sys.getsizeof(entries)
    for entry in entries.values():
        estimated += sum(sys.getsizeof(value) for value in (entry, vars(entry), entry.text, entry.runs))
        estimated += sum(sys.getsizeof(run) + sum(sys.getsizeof(part) for part in run) for run in entry.runs)
    ready_bytes, unfinished = 0, 0
    jobs = [job for view in native.views.values() for job in view.jobs]
    for job in jobs:
        if not job.future.done():
            unfinished += 1
            continue
        if job.future.cancelled():
            continue
        try:
            prepared = job.future.result()
            ready_bytes += prepared.image.sizeInBytes() + len(prepared.bgra)
        except Exception:
            pass
    return {"metadata_entries": len(entries), "python_metadata_bytes_estimate": estimated,
            "prepare_pending": len(jobs), "prepare_ready_pixel_bytes": ready_bytes,
            "prepare_unfinished_jobs": unfinished, "native_pending_image_bytes": None,
            "pending_bytes_status": "Only completed Python job pixels observable; unfinished/native pending bytes unavailable",
            "metadata_bytes_status": "Python shallow estimate; shared strings may be counted repeatedly"}


def source_fingerprint():
    digest = hashlib.sha256()
    paths = list((ROOT / "ddm").glob("*.py"))
    paths += [path for path in (ROOT / "native" / "src").rglob("*") if path.suffix in (".cpp", ".h")]
    paths.append(Path(__file__))
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def stats(frames):
    frames = tuple(frames)
    intervals = sorted((b - a) / 1e6 for a, b in zip(frames, frames[1:]))
    return {"frames": len(frames), "p50_ms": statistics.median(intervals) if intervals else None,
            "p95_ms": intervals[min(len(intervals) - 1, int(len(intervals) * .95))] if intervals else None,
            "max_ms": max(intervals, default=None)}


def display_modes():
    if sys.platform != "win32":
        return []
    modes = set()
    user32 = ctypes.windll.user32
    device = None  # Qt screen names can be monitor names rather than GDI device names.
    user32.EnumDisplaySettingsW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
    for index in range(10000):
        data = ctypes.create_string_buffer(220)
        struct.pack_into("H", data, 68, 220)
        if not user32.EnumDisplaySettingsW(device, index, data):
            break
        width, height, _, hz = struct.unpack_from("4I", data, 172)
        modes.add((width, height, hz))
    return sorted(modes)


def deny_external_network(denied):
    def audit(event, arguments):
        if event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"):
            host = arguments[0]
        elif event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
            host = arguments[1][0]
        else:
            return
        if host in (None, "localhost", "localhost.", b"localhost"):
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        denied.append(event)
        raise RuntimeError("Benchmark attempted external networking")
    sys.addaudithook(audit)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("native", "raster", "quick", "none"), required=True)
    parser.add_argument("--seconds", type=float, help="Short smoke capture; overrides formal defaults")
    parser.add_argument("--warmup", type=float, default=10)
    parser.add_argument("--capture", type=float, default=120)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--video", choices=("1080p30", "1080p60", "mixed"), default="mixed")
    parser.add_argument("--density", choices=("normal", "high", "burst"), default="normal")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work" / "danmaku-benchmark")
    parser.add_argument("--sample-scale", choices=(1, 2), type=int, default=2)
    parser.add_argument("--always-on-top", action="store_true", help="Keep only the benchmark window above other applications")
    parser.add_argument("--ffmpeg", type=Path, help="Explicit local FFmpeg exe")
    parser.add_argument("--presentmon", type=Path, help="Verified portable PresentMon v2.6.0 exe")
    parser.add_argument("--presentmon-csv", type=Path, help="Raw-QPC CSV from an already running collector restricted to benchmark processes")
    args = parser.parse_args()
    if args.presentmon and args.presentmon_csv:
        parser.error("Use either an owned collector or an external collector CSV")
    if args.seconds is not None:
        args.capture, args.warmup, args.repeats = args.seconds, min(args.warmup, 2), 1
    if (not math.isfinite(args.capture) or not math.isfinite(args.warmup)
            or args.capture <= 0 or args.warmup < 0 or args.repeats < 1):
        parser.error("Capture/repeats must be positive; warmup must be nonnegative")
    return args


def main():
    args = parse_args()
    if args.presentmon and hashlib.sha256(args.presentmon.read_bytes()).hexdigest() != PRESENTMON_SHA256:
        raise ValueError("PresentMon must match the pinned official v2.6.0 executable SHA256")
    os.environ["DDM_NO_SAVE"] = "1"
    os.environ["DDM_NATIVE_DANMAKU_SAMPLE_SCALE"] = str(args.sample_scale)
    os.environ["DDM_NATIVE_DANMAKU"] = "1" if args.backend == "native" else "0"
    os.environ["DDM_QTQUICK_DANMAKU"] = "1" if args.backend == "quick" else "0"
    denied = []
    deny_external_network(denied)
    from PySide6.QtCore import QThread, Qt, Signal, qVersion
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication
    from ddm import config
    from ddm.recording import ffmpeg_path
    ffmpeg = str(args.ffmpeg.resolve()) if args.ffmpeg else ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_hash = source_fingerprint()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).splitlines()
    app = QApplication([sys.argv[0]])
    if app.platformName() != "windows":
        print(json.dumps({"status": "unverified", "reason": "Windows visible backend required"}))
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    with tempfile.TemporaryDirectory(prefix="ddm-benchmark-") as temp, ExitStack() as stack:
        stack.enter_context(patch.object(config, "REPO", temp))
        stack.enter_context(patch.object(config, "CONFIG_PATH", str(Path(temp) / "utils/config.json")))
        from ddm import images, plugins, theme
        from ddm.app import MainWindow
        from ddm.player import TilePlayer
        from ddm.video_danmaku import VideoDanmaku

        class OfflineClient(QThread):
            message = Signal(dict)
            status = Signal(str)

            def __init__(self, room_id, parent=None):
                super().__init__(parent)

            def start(self, priority: QThread.Priority = QThread.Priority.InheritPriority):
                self.status.emit("已连接")

            def stop(self):
                pass

        stack.enter_context(patch("ddm.app.DanmakuClient", OfflineClient))
        stack.enter_context(patch.object(images, "REPO", temp))
        stack.enter_context(patch.object(images, "CACHE_DIR", str(Path(temp) / "cache/avatars")))
        stack.enter_context(patch.object(plugins, "DEFAULT_PLUGINS_DIR", str(Path(temp) / "plugins_user")))
        stack.enter_context(patch.object(plugins.PluginManager, "load"))
        http_guard = stack.enter_context(patch("requests.sessions.Session.request", side_effect=RuntimeError("Offline benchmark")))
        for name in ("start_all", "start_tile", "refresh_status", "refresh_stats", "refresh_account",
                     "refresh_follow", "load_cached_covers", "load_cached_avatars", "load_room_avatars",
                     "_restore_platform_accounts", "_sync_platform_rooms", "_check_startup_update"):
            stack.enter_context(patch.object(MainWindow, name))
        app.setStyleSheet(theme.qss())
        sources = {}
        rates = [30] * 4 if args.video == "1080p30" else [60] * 4 if args.video == "1080p60" else [30, 60, 30, 60]
        for rate in sorted(set(rates)):
            source = str(Path(temp) / f"video-{rate}.mp4")
            subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", f"testsrc2=s=1920x1080:r={rate}", "-t", "3", "-an", "-c:v",
                            "libx264", "-preset", "ultrafast", "-crf", "24", "-pix_fmt", "yuv420p", source], check=True)
            sources[rate] = source
        stack.enter_context(patch.object(VideoDanmaku, "TEXT_SAMPLE_SCALE", args.sample_scale))
        sampler = ResourceSampler()
        stack.callback(sampler.close)
        paint_frames = {}
        original_paint = VideoDanmaku.paintEvent

        def paint(overlay, event):
            paint_frames.setdefault(overlay, deque(maxlen=8192)).append(time.perf_counter_ns())
            original_paint(overlay, event)

        stack.enter_context(patch.object(VideoDanmaku, "paintEvent", paint))
        rooms = [{"room_id": str(1000 + index), "uname": f"本地视频 {index}", "live": True} for index in range(4)]
        for repeat in range(args.repeats):
            window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="2x2",
                                state=benchmark_window_state(config.DEFAULT_SETTINGS))
            window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, args.always_on_top)
            window.setGeometry(40, 60, 1200, 800)
            window.show()
            app.processEvents()
            counters = {"offered": 0, "queued": 0, "rejected": 0}
            sampler.reset()
            frame_swaps = deque(maxlen=8192)
            samples = []
            samples_file = None
            process = None
            capture_log = None
            sample_log = None
            display_recorder = None
            prefix = args.output_dir / f"{run_id}-{args.backend}-{args.video}-{args.density}-{repeat + 1}"
            emote = QImage(24, 24, QImage.Format.Format_ARGB32_Premultiplied)
            emote.fill(QColor(20, 180, 240, 128))
            emote_url = "https://example.invalid/offline-emote.png"
            try:
                for tile, rate in zip(window.wall.tiles, rates):
                    player = TilePlayer(tile.video, tile)
                    player.freeze_watch = False
                    window.players[tile] = player
                    player.play(sources[rate], options=("audio=no",))
                    player._set("loop-file", "inf")
                    player.set_muted(True)
                    tile.set_video_active(True)
                    tile.danmaku_button.setChecked(args.backend != "none")
                    overlay = tile.video_danmaku
                    overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False,
                                                video_danmaku_size=24, video_danmaku_area=100,
                                                video_danmaku_outline_width=2))
                    overlay._images[emote_url] = emote
                if args.backend == "native":
                    window.wall.tiles[0].video_danmaku.add_event({"text": "预热"})
                native = getattr(window.wall, "_native_danmaku_layer", None)
                if native is not None:
                    native._images[emote_url] = emote
                    native._image_bytes += emote.sizeInBytes()
                quick = getattr(window.wall, "_quick_danmaku_layer", None)
                if args.backend == "native" and native is None:
                    raise RuntimeError("Requested native backend fell back; benchmark invalid")
                if args.backend == "quick":
                    # Quick is lazy until the first accepted event.
                    window.wall.tiles[0].video_danmaku.add_event({"text": "预热"})
                    quick = window.wall._quick_danmaku_layer
                    if quick is None:
                        raise RuntimeError("Requested Quick backend fell back")
                    quick.window.frameSwapped.connect(lambda: frame_swaps.append(time.perf_counter_ns()))
                csv_path = args.presentmon_csv.resolve() if args.presentmon_csv else prefix.with_suffix(".csv")
                if args.presentmon:
                    capture_log = prefix.with_suffix(".presentmon.log").open("w", encoding="utf-8")
                    process = subprocess.Popen([str(args.presentmon.resolve()), "--process_id", str(os.getpid()),
                        "--output_file", str(csv_path), "--timed", str(math.ceil(args.warmup + args.capture + 40)),
                        "--terminate_after_timed", "--qpc_time", "--v2_metrics", "--write_display_metadata",
                        "--no_console_stats", "--session_name", f"DDMonitor-{os.getpid()}-{repeat}"],
                        stdout=capture_log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
                readiness = (wait_for_presentmon(csv_path, app, process) if args.presentmon or args.presentmon_csv
                             else {"status": "unverified", "reason": "No collector requested"})
                if native is not None:
                    display_recorder = DisplayStatisticsRecorder(native.host, prefix.with_suffix(".display.jsonl"))
                    display_recorder.sample()
                phase_start_qpc, qpc_frequency = qpc_clock()
                phase_start = time.perf_counter()
                capture_start = phase_start + args.warmup
                capture_end = capture_start + args.capture
                next_offer = phase_start
                sequence = 0
                captured = False
                status_start = {}
                cpu_start = 0
                capture_wall_start = 0
                capture_start_qpc = 0
                screen_start = None
                mode_changed = False
                image_bytes_peak = 0
                next_sample = capture_start
                next_display_sample = phase_start
                while time.perf_counter() < capture_end:
                    now = time.perf_counter()
                    if not captured and now >= capture_start:
                        captured = True
                        samples_file = prefix.with_suffix(".samples.jsonl")
                        sample_log = samples_file.open("w", encoding="utf-8")
                        counters = {key: 0 for key in counters}
                        image_bytes_peak = 0
                        paint_frames.clear()
                        frame_swaps.clear()
                        capture_start_qpc = qpc_clock()[0]
                        capture_wall_start = time.perf_counter()
                        capture_end = capture_wall_start + args.capture
                        cpu_start = time.process_time()
                        status_start = native.status_snapshot() if native else {}
                        screen_start = (window.screen().name(), window.screen().refreshRate(), window.screen().geometry())
                    if now >= next_offer:
                        count = 50 if args.density == "burst" else 1
                        step = 5 if args.density == "burst" else .125 if args.density == "high" else .5
                        # Bound catch-up after GUI stalls without losing deterministic sequence order.
                        next_offer = max(next_offer + step, now)
                        if args.backend != "none":
                            for tile in window.wall.tiles:
                                for _ in range(count):
                                    sequence += 1
                                    variants = ("中文弹幕 Hello gyp 😀", "较长弹幕 " + "中英混合 gyp " * 8, "半透明 [emote]", "self sent")
                                    variant = (sequence + sequence // 4) % 4
                                    event = {"text": f"{variants[variant]} {sequence}",
                                             "color": ("#ffffff", "#ff8844", "#44ff88")[sequence % 3],
                                             "self_sent": variant == 3}
                                    if variant == 2:
                                        event["emoticons"] = {"[emote]": emote_url}
                                    counters["offered"] += 1
                                    queued = bool(tile.video_danmaku.add_event(event))
                                    counters["queued"] += queued
                                    counters["rejected"] += not queued
                    app.processEvents()
                    if display_recorder is not None and now >= next_display_sample:
                        next_display_sample = now + 1
                        display_recorder.sample()
                    if captured:
                        current_screen = (window.screen().name(), window.screen().refreshRate(), window.screen().geometry())
                        mode_changed |= current_screen != screen_start
                    if captured and sample_log is not None and now >= next_sample:
                        next_sample = now + 1
                        sample = sampler.sample(time.perf_counter() - capture_wall_start)
                        status = native.status_snapshot() if native else {}
                        image_bytes = status.get("image_bytes", 0) if native else sum(
                            comment.image.width() * comment.image.height() * 4
                            for tile in window.wall.tiles for comment in tile.video_danmaku.comments)
                        image_bytes_peak = max(image_bytes_peak, image_bytes)
                        sample.update(preparation_memory(native))
                        sample.update({"image_bytes": image_bytes, "cpu_image_bytes": status.get("cpu_image_bytes"),
                            "prepare_reserved_bytes": status.get("prepare_reserved_bytes"),
                            "gpu_resource_bytes": status.get("gpu_bytes"),
                            "native_pending_count": len(status.get("pending", [])),
                            "video_time_positions": [player._prop("time-pos") for player in window.players.values()],
                            "video_output_configured": [player._prop("vo-configured", False) for player in window.players.values()],
                            "gpu_utilization_status": "unverified; GPU utilization not collected"})
                        samples.append(sample)
                        sample_log.write(json.dumps(sample, ensure_ascii=False) + "\n")
                        sample_log.flush()
                    time.sleep(.003)
                if not captured:
                    raise RuntimeError("Benchmark did not reach the resource capture window")
                capture_end_qpc = qpc_clock()[0]
                wall_seconds = time.perf_counter() - capture_wall_start
                cpu_seconds = time.process_time() - cpu_start
                status_end = native.status_snapshot() if native else {}
                if display_recorder is not None:
                    tail_deadline = time.perf_counter() + .25
                    while time.perf_counter() < tail_deadline:
                        app.processEvents()
                        time.sleep(.003)
                    display_recorder.sample()
                    display_recorder.close()
                if process:
                    try:
                        process.wait(timeout=45)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=5)
                if capture_log:
                    capture_log.close()
                screen = window.screen()
                screen_end = (screen.name(), screen.refreshRate(), screen.geometry())
                start_counts, end_counts = status_start.get("counters", {}), status_end.get("counters", {})
                native_counts = {key: value - start_counts.get(key, 0) for key, value in end_counts.items()}
                address = status_end.get("swap_chain_address", status_end.get("swapchain_address"))
                if isinstance(address, int):
                    address = hex(address)
                report = {"status": "unverified", "display_acceptance": "Not evaluated; prefer per-chain DXGI display-statistics analyzer when available",
                    "source_commit": revision, "source_dirty": dirty, "source_code_sha256": source_hash, "python": sys.version, "qt_version": qVersion(),
                    "ffmpeg_sha256": hashlib.sha256(Path(ffmpeg).read_bytes()).hexdigest(),
                    "source_video_sha256": {str(rate): hashlib.sha256(Path(source).read_bytes()).hexdigest() for rate, source in sources.items()},
                    "window_always_on_top": args.always_on_top,
                    "sample_scale": args.sample_scale, "render_quality": {"sample_scale": args.sample_scale, "font_px": 24, "outline_width": 2},
                    "backend": args.backend, "video": args.video, "video_rates": rates, "density": args.density,
                    "repeat": repeat + 1, "repeats": args.repeats, "warmup_seconds": args.warmup,
                    "capture_seconds": args.capture, "smoke": args.seconds is not None, "pid": os.getpid(),
                    "measurement_schema": 2,
                    "final_display_capture_boundary_status": "raw_qpc_pending_analysis",
                    "presentmon_readiness": readiness,
                    "capture_qpc": {"frequency": qpc_frequency, "warmup_start": phase_start_qpc,
                                    "start": capture_start_qpc, "end": capture_end_qpc},
                    "presentmon_csv": str(csv_path.resolve()),
                    "external_presentmon_csv": bool(args.presentmon_csv),
                    "native_binary": native_binary_provenance(),
                    "screen_name": screen.name(), "screen_hz": screen.refreshRate(),
                    "screen_size": [screen.size().width(), screen.size().height()], "screen_dpr": screen.devicePixelRatio(),
                    "primary_display_available_modes": display_modes(),
                    "display_mode_changed_during_capture": mode_changed or screen_start != screen_end,
                    "offered": counters["offered"], "queued": counters["queued"],
                    "admitted": native_counts.get("admitted") if native else counters["queued"],
                    "dropped": None,
                    "drop_stage_counters": drop_stage_counters(counters["rejected"], status_start, status_end),
                    "dropped_measurement": "Stage counters overlap and include replacement failures; unique original-comment drops are not observable and must not be summed",
                    "resource_samples": str(samples_file.resolve()) if samples_file else None,
                    "resource_samples_sha256": hashlib.sha256(samples_file.read_bytes()).hexdigest() if samples_file else None,
                    "working_set_trend": memory_trend(samples, "working_set_bytes"),
                    "private_bytes_trend": memory_trend(samples, "private_bytes"),
                    "dwm_cpu_status": samples[-1]["dwm_cpu_status"] if samples else "unverified",
                    "dwm_cpu_reason": samples[-1]["dwm_cpu_reason"] if samples else "No samples",
                    "video_output_diagnostics": [{"distinct_time_positions": len({sample["video_time_positions"][index] for sample in samples}),
                        "output_configured_samples": sum(bool(sample["video_output_configured"][index]) for sample in samples)} for index in range(4)],
                    "gpu_utilization_status": "unverified; no GPU utilization capture",
                    "video_visibility_status": "unverified; time-pos/vo-configured confirm decode/output, not unobscured pixels",
                    "cadence_sample_limit": 8192,
                    "native_counter_delta": native_counts, "image_bytes_peak": image_bytes_peak,
                    "image_bytes_peak_measurement": "1-second sampled peak",
                    "backend_status_start": status_start, "backend_status_end": status_end,
                    "wall_seconds": wall_seconds, "process_cpu_seconds": cpu_seconds,
                    "process_cpu_percent_one_core": cpu_seconds / wall_seconds * 100,
                    "decoder": [player._prop("hwdec-current") for player in window.players.values()],
                    "submitted_cadence": {"shared_quick": stats(frame_swaps)} if quick else {
                        f"tile_{index}": stats(paint_frames.get(tile.video_danmaku, [])) for index, tile in enumerate(window.wall.tiles)},
                    "presentmon_exit_code": process.returncode if process else None,
                    "presentmon_exe_sha256": hashlib.sha256(args.presentmon.read_bytes()).hexdigest() if args.presentmon else None,
                    "swapchain_attribution": {"address": address, "process_id": os.getpid(),
                        "evidence": "native host status" if address else None},
                    "network_attempts_blocked": denied, "unexpected_http_calls": http_guard.call_count, "measurement": "Qt/internal counters are not final DWM display evidence"}
                if display_recorder is not None:
                    report.update(display_recorder.summary())
                if csv_path.exists() and not args.presentmon_csv:
                    report["csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
                prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"report": str(prefix.with_suffix(".json").resolve()),
                    "backend": args.backend, "screen_hz": report["screen_hz"],
                    "offered": report["offered"], "admitted": report["admitted"],
                    "presentmon_exit_code": report["presentmon_exit_code"],
                    "status": "unverified"}, ensure_ascii=False))
            finally:
                if display_recorder is not None:
                    display_recorder.close()
                if sample_log:
                    sample_log.close()
                if process and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                if capture_log and not capture_log.closed:
                    capture_log.close()
                window.close()
                close_deadline = time.monotonic() + 10
                while window.isVisible() and time.monotonic() < close_deadline:
                    app.processEvents()
                    time.sleep(.01)
                app.processEvents()
    if denied or http_guard.call_count:
        raise RuntimeError(f"Blocked unexpected network attempts: sockets={len(denied)}, HTTP={http_guard.call_count}")


if __name__ == "__main__":
    main()
