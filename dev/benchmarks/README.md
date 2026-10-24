# 性能基准

从仓库根目录执行，需要开发依赖和 Windows 图形环境。工具只读取显示模式，不切换刷新率。

| 工具 | 测量范围 |
| --- | --- |
| [benchmark_danmaku_frames.py](benchmark_danmaku_frames.py) | 可见四格 Qt 绘制间隔与定时精度 |
| [benchmark_video_danmaku_render.py](benchmark_video_danmaku_render.py) | 四路本地 1080p 视频，持续确定性弹幕，raster / quick / native / none 的 CPU、接纳量、图片字节和后端状态 |
| [analyze_danmaku_present.py](analyze_danmaku_present.py) | 优先分析每链 DXGI 显示统计；也支持按 PID、原生弹幕 SwapChain 筛选 PresentMon CSV |

短测沿用 `--seconds`，每次一个重复、最多两秒预热；不限制旧版的 2–6 秒范围。

```powershell
python dev/benchmarks/benchmark_video_danmaku_render.py --backend quick --seconds 3 --ffmpeg E:/path/ffmpeg.exe
python dev/benchmarks/benchmark_video_danmaku_render.py --backend native --seconds 3 --video mixed --ffmpeg E:/path/ffmpeg.exe
python dev/selfcheck_danmaku_present_analysis.py
```

正式模式默认每组合预热 10 秒、采集 120 秒、重复 3 次。矩阵是实际 60Hz、120Hz × 1080p30 / 1080p60 / mixed × normal / high / burst；另做 30 分钟稳定性。完整视频墙必须在同一显示器；由操作者预先切换并核对实际屏幕模式。`normal` 每格每秒 2 条，`high` 每格每秒 8 条，`burst` 每格每五秒集中提交 50 条（落在 200ms 窗口内）。文字包含中文、英文、Unicode emoji、长文本、自发框和预置半透明图片。`none` 保留四路视频作为弹幕关闭对照。

```powershell
python dev/benchmarks/benchmark_video_danmaku_render.py --backend native --video mixed --density high --ffmpeg E:/path/ffmpeg.exe --presentmon work/tools/PresentMon-2.6.0-x64.exe
python dev/benchmarks/analyze_danmaku_present.py work/danmaku-benchmark/CAPTURE.csv --metadata work/danmaku-benchmark/CAPTURE.json --hz 59.94 --process-id PID --swapchain 0xADDRESS --output work/danmaku-benchmark/CAPTURE-analysis.json
```

每次采集独立 JSON / CSV / PresentMon 日志。JSON 保存源码 commit 和未提交文件、Python/Qt 版本、FFmpeg/本地视频/PresentMon SHA256、屏幕刷新率/DPR、primary 显示器可用模式、模式变化、进程 CPU、offered/queued/admitted/dropped、图片字节峰值及完整后端状态。native 的 admitted 来自原生计数差值，不能用 `add_event=True` 替代。原生入队及在途项目跨采集边界，计数差值不保证逐条守恒；需要完整状态解释边界。字节是图片资源量，CPU 只属于当前进程，不含 DWM；GPU 利用率、DWM CPU、内存趋势和资源差值仍需额外采集。

所有账号、配置、图片缓存和用户插件路径使用临时目录；禁用插件加载及账号/房间网络刷新，弹幕客户端替换为离线客户端，HTTP 与外部 socket 请求设防，视频只用本地文件。进程内 Python 防护不隔离原生库联网；本工具给 mpv 的源和循环播放参数均为本地文件。

Qt paintEvent/frameSwapped 与原生 frames 只说明内部提交工作。分析器仅采用官方最终显示字段 `DisplayedTime`（2.x）或 `MsBetweenDisplayChange`（1.x），拒绝只含 FrameTime / present 间隔的 CSV；过滤未显示行，按 PID 和 SwapChain 归因，核对 native host 地址、真实屏幕刷新率、稳定显示模式与至少 120 秒显示时长。CSV 哈希与 metadata 绑定，分析结果同时记录两份原始文件 SHA256。门槛为 P99 ≤ 1.25T、>1.5T 比例 ≤ 0.1%、没有 >3T，T=1000/实际Hz。缺证据返回 `unverified`（退出码 2）；满足证据后单次阈值通过/失败分别返回 0/1。单次 pass 仍不能代替三次重复、画质/接纳量一致的旧基线比较及完整矩阵验收。

## PresentMon 固定工具及当前探路结论

2026-10-24 已从 [官方 v2.6.0 release](https://github.com/GameTechDev/PresentMon/releases/tag/v2.6.0) 下载独立控制台 exe 到 `work/tools/PresentMon-2.6.0-x64.exe`，未安装系统组件。SHA256 与 GitHub API asset digest 相同：

```text
b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af
```

Windows Authenticode 返回 Valid，签名主体 Intel Corporation；实际 `--help` 确认 `--process_id`、`--output_file`、`--timed`、`--terminate_after_timed`、`--v2_metrics`、`--write_display_metadata`、`--session_name`。benchmark 在启动前核对该固定 SHA256，使用唯一 session，不终止其他采集、不请求提权。字段语义依据 [该 tag 的官方控制台说明](https://github.com/GameTechDev/PresentMon/blob/v2.6.0/README-ConsoleApplication.md)。显示元数据列包括 VidPnSourceId 和 LayerIndex，可防止把多显示器/多层混在一起统计。

真实短测已运行 none/mixed、raster/1080p30、quick/1080p60、native/mixed；四路视频均报告 d3d11va，native status 为 Running。当前显示器 P27A6VP 是 144Hz、DPR 1.5；primary 模式枚举含 2560×1440 的 60/119/120/144。未更改屏幕，所有短测结果均标记未验收。

PresentMon 实际启动捕获返回 exit 6，日志为 trace session access denied，要求管理员权限或 Performance Log Users。未自动提升权限或改用户组，因此当前没有最终显示 CSV，60Hz / 120Hz、性能改善、30 分钟稳定性均未验收。正式旧基线与 native 对照在主集成完成、采集权限具备后执行；不可把本次 144Hz 短测 CPU 或内部帧回调当作性能结论。

## 长时资源采样与同负载比较

benchmark 在采集期每秒将一条记录写入同名 `.samples.jsonl` 并立即 flush，适合中途检查 30 分钟 soak；最终报告保存时序文件 SHA256。使用 Win32 Psapi `PROCESS_MEMORY_COUNTERS_EX` 读取当前进程 WorkingSet / PrivateBytes，同时记录当前进程 CPU 和同 session DWM CPU（可访问时）。无法读取 DWM session 或进程 CPU 时记录原因并标记未验收，不改权限。GPU resource bytes 只表示原生纹理资源，GPU 利用率仍为 unverified。

时序还包含 image bytes、native pending 数量、Python metadata entries/浅层字节估算、已完成但待提交准备工作的 QImage+BGRA 字节和未完成任务数。共享字符串可能在 metadata 估算中重复计算；未完成任务和原生 pending 的独立像素字节当前接口不提供，因此明确标为不可观测，不能把估算当分配器实耗。报告 WorkingSet/PrivateBytes 首末/峰值及末 80% 线性趋势，趋势只供诊断。Qt 回调时间戳固定保留最后 8192 点，避免长测自带的无限列表制造内存增长。

`--sample-scale 1|2` 默认 2；native 通过 `DDM_NATIVE_DANMAKU_SAMPLE_SCALE`，raster/Quick 通过同一文字采样倍率，报告保留倍率与文字样式。1 倍与 2 倍必须分别报告画质，不能把降低倍率后的 CPU 当同画质改进。

每秒还记录四路实际 time-pos / vo-configured，报告各路不同播放位置数和输出配置样本数。这只能诊断解码和输出推进；窗口遮挡、蓝色 placeholder 或黑色视频仍须检查实际像素，所以 `video_visibility_status` 默认未验收。不能因为后端 Running 或四路 d3d11va 就声称视频可见。

root 协调窗口独占后，资源命令示例：

```powershell
python dev/checks/bootstrap.py dev/benchmarks/benchmark_video_danmaku_render.py --backend native --video mixed --density high --warmup 10 --capture 1800 --repeats 1 --sample-scale 2 --ffmpeg E:/path/ffmpeg.exe --output-dir work/danmaku-soak
python dev/checks/bootstrap.py dev/benchmarks/benchmark_video_danmaku_render.py --backend raster --video mixed --density high --warmup 10 --capture 120 --repeats 3 --sample-scale 2 --ffmpeg E:/path/ffmpeg.exe --output-dir work/danmaku-resource-raster
python dev/checks/bootstrap.py dev/benchmarks/benchmark_video_danmaku_render.py --backend native --video mixed --density high --warmup 10 --capture 120 --repeats 3 --sample-scale 2 --ffmpeg E:/path/ffmpeg.exe --output-dir work/danmaku-resource-native
python dev/benchmarks/analyze_danmaku_present.py --compare-resources BASELINE.json CANDIDATE.json --output COMPARISON.json
```

资源比较核对同源码 commit、视频/密度/屏幕、同 offered/admitted、文字画质/倍率、视频哈希、样本哈希、至少 10+120 秒和稳定显示模式。接纳量或倍率不同会返回未验收；CPU 差值仍列出但仅供描述，不能凭 CPU 独自判定改进。默认缺少视频像素证据也会返回未验收；人工复核实际像素后可在归档副本中将 `video_visibility_status` 写为 `verified ...` 并保留原报告哈希/审查记录。即使同源固定 144Hz 资源比较满足前提，也不替代真实 60/120Hz 最终显示验收。

## 统计审计修订（measurement_schema 2）

`dropped` 固定为 null。`drop_stage_counters` 保留 add_event 拒绝、Python 准备失败（含原生队列拒绝）和原生各类提交失败差值；这些阶段存在重叠，并且包含替换图片失败，不能相加，也不能当作唯一新弹幕丢弃数。替换失败的独立计数当前不可观测，明确为 null。每轮 ResourceSampler 会重置 CPU 差值基线。

最终显示分析要求 metadata 必须带匹配 CSV SHA256、预热至少 10 秒、配置与实测采集窗口均至少 120 秒。benchmark 在预热前启动或连接 PresentMon，等待 CSV 中实际出现本 PID 的已显示原始 QPC 行，并保存 readiness 观察时刻；资源窗口用 Win32 QueryPerformanceCounter / QueryPerformanceFrequency 记录。分析器从 `CPUStartQPC + DisplayLatency` 得到真实首次显示时刻，再用 `DisplayedTime` 构造显示区间，要求原始区间连续覆盖资源窗口起止，并在最终 CSV 中找到 readiness 原始行。只有通过这些核对才由分析结果给出 boundary verified；metadata 自填 verified 不构成证据。完整窗口至少 120 秒，不再放宽到 114 秒。跨边界帧用完整 DisplayedTime 参与长停顿阈值，避免裁掉边界停顿；统计显示覆盖时长只计窗口本身。仅有旧版显示时长字段而无此原始时间轴的 CSV 仍可描述统计，但正式边界保持 unverified。

资源比较还要求相同配置采集时长、实测窗口完整，以及哈希绑定的样本实际覆盖窗口（首样本不晚于 2 秒、末样本距结束不超过 2 秒、间隔不超过 2.5 秒、时序严格递增）。只含空对象的文件不构成资源证据。CPU 差值仍仅描述进程资源；文字样式参数一致不能替代实际画质核查。

源码指纹在进程启动阶段计算后保存在报告，运行中修改源码不会改变该进程启动时指纹。已经运行的旧 measurement 进程仍按旧字段解释，其无 schema 报告不得伪装为 schema 2 新测量。


## 一次管理员采集覆盖多个测试进程

仅在操作者明确授权管理员 ETW 后，可由操作者通过 [collect_danmaku_etw.ps1](collect_danmaku_etw.ps1) 启动一个外部 PresentMon，并只筛选本任务专用、唯一 exe 名称。不得省略 process filter，不使用普通 python.exe 名称，不加入用户组或更改永久设置。先验证专用运行时的 sys.executable / sys.prefix 和依赖；这里只给参数范例，路径、唯一名称及 timed 秒数应与本次计划对应。多进程之间存在空档时不要使用 terminate_on_proc_exit。PresentMon 的 output_file 在采集时独占文件，无法供 readiness 读取，因此脚本使用 output_stdout，逐行写入 FileShare.ReadWrite、AutoFlush 的共享 CSV；原始 stdout 和异步读取的 stderr 分别归档。脚本仅接受固定测试 exe 名称、1–86400 秒和 work/danmaku-etw 直属新 CSV，不代理任意命令；collector JSON 记录工具/脚本 hash、启动 QPC、子进程 PID、最终退出码和 CSV hash。

```powershell
Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','C:/ABS/dev/benchmarks/collect_danmaku_etw.ps1','-OutputCsv','C:/ABS/work/danmaku-etw/matrix.csv','-ProcessName','DDMDanmakuBench-20261024.exe','-Seconds','1800')
C:/ABS/work/benchmark-runtime/Scripts/DDMDanmakuBench-20261024.exe dev/checks/bootstrap.py dev/benchmarks/benchmark_video_danmaku_render.py --backend native --video mixed --density high --warmup 10 --capture 120 --repeats 3 --ffmpeg C:/ABS/ffmpeg.exe --presentmon-csv C:/ABS/work/danmaku-etw/matrix.csv --output-dir work/native-120
```

benchmark 在连接后最多等待 30 秒，期间继续处理 Qt 事件；CSV 中没有本 PID 已显示 raw-QPC 行就记录 readiness unverified，后续不能验收。外部 collector 须覆盖完整预热和采集；timed 到期前还应留尾部显示事件的余量。外部 CSV 还在写入时，benchmark 不将暂态哈希写成最终证据。等 collector 完全退出、CSV 固定后，再为每轮创建绑定副本（不覆盖原 JSON）：

```powershell
python dev/benchmarks/analyze_danmaku_present.py C:/ABS/work/danmaku-etw/matrix.csv --metadata C:/ABS/work/native-120/REPEAT.json --bind-external-csv C:/ABS/work/native-120/REPEAT-bound.json --hz 120 --process-id PID --swapchain 0xADDRESS --output C:/ABS/work/native-120/REPEAT-analysis.json
```

绑定副本保存原 metadata 路径与 SHA256，并绑定最终共享 CSV；分析器仍按各轮 PID、swapchain 和 raw-QPC 窗口筛选，不把整个 collector 时长当作该轮时长。采集 JSON 另记录实际加载的 native `.pyd` 绝对路径与 SHA256；每秒样本包含原生 `cpu_image_bytes`、准备任务 `prepare_reserved_bytes`，与 GPU bytes 分开保存。后两项是接口提供的资源计数，不能等同进程私有内存实耗。


## DirectComposition 最终显示的工具限制

2026-10-24 管理员 PresentMon 探路已经成功生成 PID 受限 CSV，排除了原先普通 token 的 ETW 权限阻塞；这不代表原生覆盖层最终显示已可测。`work/danmaku-etw/probe2.csv` 中，native host 独立归因的 `0x1cafa812830` 共 620 行，`DisplayedTime` 均为 NA；同 PID 部分 mpv swapchain 有非 NA 数据，不能替代覆盖层。

[PresentMon v2.6.0 官方实现](https://github.com/GameTechDev/PresentMon/blob/v2.6.0/PresentData/PresentMonTraceConsumer.cpp#L817) 的 redirected composition 路径主动移除 DirectComposition presents；[同 tag 的接口说明](https://github.com/GameTechDev/PresentMon/blob/v2.6.0/PresentData/PresentMonTraceConsumer.hpp#L92) 说明此类 composition dependencies 无法可靠追踪。上述实机现象与这个限制一致，但单次探路不能证明所有 DComp 路径均不可测。后续应先核对指定 native 地址是否真正出现可覆盖窗口的最终显示数据；若仍全 NA，分析器必须保持 unverified，不应把剩余全矩阵的 Present/CPU cadence 或其它 swapchain 填成 final-display 结果。需要另行验证可归因的显示统计或物理像素测量方法。


## 每 SwapChain 的 DXGI 显示统计

native benchmark 默认每秒调用有界 `host.display_statistics(after_sequence, 8192)`，预热期也采集，分页一直推进到已知最新记录。原始页立即 flush 到同名 `.display.jsonl`；报告绑定文件 SHA256、采集进程 PID、资源窗口 QPC 与实际加载 `.pyd` 的路径/hash。资源窗口结束后额外处理 250ms Qt 事件并取尾页，用来等待窗口尾部的显示反馈；这部分不计入资源 CPU/内存窗口。Qt 常规 status 不返回大数组，采集不调用 DwmFlush，也不新增渲染线程。

```powershell
python dev/benchmarks/benchmark_video_danmaku_render.py --backend native --video mixed --density high --warmup 10 --capture 120 --repeats 3 --ffmpeg E:/path/ffmpeg.exe --output-dir work/native-display-120
python dev/benchmarks/analyze_danmaku_present.py --dxgi-statistics work/native-display-120/REPEAT.display.jsonl --metadata work/native-display-120/REPEAT.json --hz 120 --process-id PID --swapchain 0xADDRESS --output work/native-display-120/REPEAT-analysis.json
```

这是指定 native swapchain 的 `IDXGISwapChain::GetFrameStatistics` 结果，不使用全局 DWM timing。依据 [Microsoft 字段说明](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/ns-dxgi-dxgi_frame_statistics) 与 [flip-model 显示反馈说明](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/dxgi-flip-model)，`SyncQPCTime` 对应 `SyncRefreshCount` 的时基，不能直接当作当前图像的最终显示时刻。分析器用下式将该图像的 `PresentRefreshCount` 映射到同一 QPC 时基：

```text
displayQPC = SyncQPCTime + signed32(PresentRefreshCount - SyncRefreshCount) * QPCFrequency / actualHz
```

只有相邻、不同且连续的 `PresentCount` 才生成单帧显示间隔，间隔跨越资源窗口边界时保留完整长度参与停顿阈值，覆盖时长只计资源窗口。`last_present_count` 仅为关联提交元数据的诊断字段，不参与显示间隔，也不用于补齐缺帧。相同 `PresentCount` 的自然重复会去重，允许 sync anchor 更新；但同一显示计数对应的 refresh count、运动/内容映射或推导显示时间发生冲突会返回 unverified。

`moving`、`active_count` 和 `frame_kind` 由 native 依据统计返回的显示 PresentCount 回查提交元数据，不把当前刚画的帧误标成已经显示的帧。正式窗口必须是可确认运动的 content；initial、clear、unknown、零统计、失败或 disjoint 出现在窗口内都会标记未验收。原始序号缺口、ring lost、PresentCount 跳号分别保留原因；跳号跨度仅列为 observed gap，不能假定中间每帧都已经显示，也不能将跨度伪装成某一帧的停顿。缺少连续运动内容的完整 120 秒边界覆盖仍为 unverified。API 受多显示器与其它全屏应用场景的可靠性限制，完整矩阵仍须固定实际显示模式和显示器归属，三次重复与画质/资源/接纳密度对照分别验收。


后续置顶探路修正：`work/dxgi-topmost-smoke/20261024-122849-24956` 使用 `--always-on-top` 后，native chain `0x1fd4604a080` 获得 2342 条非零 DXGI 统计，显示 PresentCount 对应 moving content，采集窗无 invalid sample。管理员 stdout collector 的共享 CSV 在采集期间可读取，readiness 握手成功；collector 最终 exit 0、写出 2862 行，同一 native chain 的 PresentMon 1224 行中有 1004 行有效 DisplayedTime。因此此前 probe2 的全 NA 现象主要与窗口遮挡相关；官方源码忽略的是部分 DirectComposition 路径，不能据此认定本应用的 PresentMon 最终显示通路必然不支持。该结果验证了两种真实数据通路，仍属短测；显示计数跳号仅作 observed gap，完整 60/120Hz、120 秒、三次重复与完整性验收仍需正式测量。`--always-on-top` 只影响本次测试窗口，报告保存 `window_always_on_top`；它不自动把视频像素可见性标为 verified。
