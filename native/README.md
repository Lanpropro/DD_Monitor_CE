# Windows D3D11 danmaku

The Python bridge prepares immutable premultiplied BGRA images. One C++ thread owns movement,
lanes, textures and the transparent DirectComposition swap chain for the whole wall. mpv keeps
its original windows and devices. `VideoDanmaku.add_event()` returns preparation-queue acceptance;
final admission and drops are reported by `status_snapshot()`.

## Build

Current development and frozen builds use PySide6 6.11.2. The extension has been built
and imported with Python 3.12.14 x64 and pybind11 3.0.1, with engine/renderer CTest checks.
Earlier validation used Python 3.13.7 x64, PySide6 6.9.3, MSVC 19.44 / VS Build Tools 2022,
Windows SDK 10.0.26100.0 and CMake 4.1.2. Install the C++ x64 tools and
Windows SDK with Visual Studio Build Tools, then install `requirements-dev.txt` into the
same Python environment used for freezing. No Qt C++ SDK is needed.

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
powershell -File dev/build_native_danmaku.ps1
.venv\Scripts\python.exe dev/run_checks.py --suite offline
.venv\Scripts\python.exe dev/run_checks.py --suite native
```

The build script creates a Release extension in `ddm/`, tests it with CTest, checks the ABI
by importing it with the selected interpreter and writes build evidence under `work/`.
Generated `.pyd` files are not committed. Build a matching extension for each Python ABI;
cp312-win_amd64 and cp313-win_amd64 have been exercised locally. CI checks both versions.

On Windows, the native backend is selected when the extension imports successfully.
Both launchers default to this selection and preserve an explicitly set Quick override.
`DDM_NATIVE_DANMAKU=0` selects the previous raster backend. `DDM_QTQUICK_DANMAKU=1`
retains the existing experimental Quick selection. Missing modules and initialization/runtime
failure restore the raster backend once; the host is stopped before its window is destroyed.

## Interface and lifetime

`NativeDanmakuHost` exposes `attach(hwnd)`, `update_scene(full_scene)`,
`submit_batch(images)`, `status_snapshot()`, `request_close()` and `reap()`.
Scene coordinates explicitly separate logical sizes from physical clip rectangles and masks.
Each view has a stable monotonically allocated ID, room epoch and style revision; the entire
wall has one layout revision. New and replacement images use stable comment IDs. Replacement
preserves movement progress; clearing a room cancels its previous epoch.

Images are copied at the binding entrance after validating format, dimensions, stride, byte
length and limits. Worker/render threads retain no Python or Qt objects. New-comment TTL is
500ms including preparation, binding copy, upload and queue wait; active-image replacement
does not reset movement or expire the active comment. There are at most 80 active comments
and 64 pending comments per view, 256 pending globally. Image and upload budgets are bounded.
Python reclaims metadata with the processed submission watermark and active/pending IDs.

The GUI maintains the input-transparent owned top-level host, its physical geometry and
immutable masks. It never drives native positions or waits for a live rendering thread.
Call `request_close()`, keep pumping GUI messages, and call `reap()` only after it returns
true; destroy the HWND afterwards. Main-window close follows this two-phase protocol.
Idle and paused hosts stop submitting frames; zero-size/minimized hosts suspend.

## Verification and acceptance

CTest tests the engine with an injected clock and real hardware composition pixels, opacity,
mask holes, clipping, control priority and asynchronous shutdown. Python checks cover image
parity, thread-private rasterization, queue cancellation, metadata, binding rejection/copy
ownership, four local mpv surfaces and continued rendering during GUI/Python work.
The four-video check needs FFmpeg on PATH or adjacent to the source root. It generates only
temporary local media and does not use user accounts, settings or live services.

```powershell
.venv\Scripts\python.exe main.py --native-danmaku-probe C:\temp\native-probe.json
.venv\Scripts\python.exe dev/benchmarks/benchmark_video_danmaku_render.py --backend native
```

The benchmark supports sustained normal/high/burst replay, 1080p30/60/mixed inputs and
baseline/disabled/native comparisons. See [measurement commands](../dev/benchmarks/README.md).
Native frames and Qt callbacks measure submitted work. Acceptance at real 60Hz and 120Hz
requires attributed final-display evidence: 10s warmup, 120s capture, three repeats,
P99 <= 1.25 display periods, >1.5-period ratio <= 0.1%, no >3-period steady-state pause,
matched image quality/admission density, CPU/GPU/DWM comparisons and a 30-minute soak.

PresentMon 2.6.0 was downloaded and signature/hash checked. The normal desktop token cannot
start its ETW session (exit 6). An explicitly authorized administrator capture produced CSV,
but the danmaku composition chain had 620 rows with no DisplayedTime. PresentMon's v2.6.0
implementation explicitly ignores some DirectComposition presentation dependencies.
An unobscured always-on-top follow-up returned nonzero per-chain DXGI statistics and 1004
valid PresentMon displayed-time rows out of 1224 for the native chain; the earlier all-NA
probe was also affected by window visibility. PresentMon support is not universally absent.
Final 60/120Hz display acceptance remains separate from this short pipeline validation.
The dedicated stdout collector supports a shared readable CSV without changing
user groups; a live --output_file CSV is locked exclusively by PresentMon.

`display_statistics(after_sequence, max_records)` provides optional benchmark diagnostics:
a bounded 32768-record history from the same render thread, sampled after frame permits and
Present. Regular GUI status polling never copies this history. The benchmark records raw
per-chain display counts, refresh/QPC anchors, errors and frame identities; its analyzer
rejects missing/disjoint/zero records, ambiguous count gaps and incomplete capture windows.
No DwmFlush or extra rendering thread is used. API support alone is not an acceptance result.
Do not substitute submitted-frame counters for this evidence. Cross-monitor DPI and physical
input checks must also be reported separately from automated local checks.

The frozen release build explicitly collects the matching extension, records its hash/ABI
and verifies the actual packaged import, attach, render, shutdown and fallback. It uses an
isolated output directory and includes no local credentials, settings, caches or installed
plugins. This feature does not change the application version or publish a release.

The release script freezes an isolated source snapshot under `work/freeze-source` and builds
its extension separately. It can run while another process has the development `.pyd` loaded;
Windows does not allow overwriting a loaded module. The source portable package retains only
source code and build instructions, without an ABI-specific `.pyd`.
