# 错误日志功能完善计划

记录日期：2026-10-25。状态：阶段 1-5 已实现；发布包实跑验证见交付说明。

## 目标

把现有的“把 stderr 追加到文件 + 卡死/崩溃转储”完善成一套可长期使用、
用户能直接提供、开发者能据此定位问题的错误日志。

1. 同时记录 `stdout` 和 `stderr`，普通 `print()` 不再漏记。
2. 统一接入 Python `logging`，有明确的日志级别、格式、轮转和过期清理。
3. 不再让 `except Exception: pass` 静默吞掉异常；按场景记录完整调用栈。
4. 启动时记录设备软硬件信息、系统信息和运行环境。
5. 启动失败时也留下日志并写明失败阶段和原因，包括首次启动失败。
6. 暂不增加界面上的日志查看、打开或导出入口。

## 现状

| 能力 | 当前实现 | 问题 |
| --- | --- | --- |
| 文件日志 | `ddm/app.py:62` 的 `setup_file_log()` 把 `stderr` 同步写入 `logs/ddm-日期.log` | 只镜像 `stderr`；启动较晚；没有日志级别和轮转 |
| 普通输出 | 各模块大量使用 `print()`，其中很多没有指定 `file=sys.stderr` | `ddm/app.py:1436` 的 `[取流失败]` 等 `stdout` 信息不会进入文件 |
| Qt 消息 | `ddm/app.py:95` 的 `qInstallMessageHandler()` 记录 Qt 消息 | 只处理 Qt，不处理 Python 未捕获异常和普通后台线程异常 |
| 卡死/硬崩 | `ddm/watchdog.py:44` 用 `faulthandler` 写所有线程调用栈 | 自己持有文件句柄，未与日志轮转协调 |
| 三方库日志 | `ddm/danmaku.py:29` 只把 `blivedm` 调到 ERROR | 没有统一的根日志配置，其他库的告警和异常容易丢失 |
| 插件异常 | `ddm/plugins.py:343` 等位置使用 `traceback.print_exc()` | 能进 `stderr` 日志，但没有插件、钩子、动作等上下文 |
| 静默异常 | `ddm/` 中有多处 `except Exception: pass` | 用户只看到功能失效，日志里没有任何线索 |
| 首次启动 | `ddm/app.py:3296` 在导入应用模块并创建 `QApplication` 之后才建立日志 | `PySide6`、`libmpv`、`ddm.app` 等早期导入失败时没有文件日志 |
| 发布包 | `dev/check_release_package.py:55` 要求发布包不带 `logs/` | 运行时必须能自行创建日志目录，首次启动也要能创建 |

`logs/` 已被 `.gitignore:4` 忽略。本地已创建空目录；它不应进入发布包，
由程序在启动时按需创建。

## 模块设计

按 `codebase-design` 的深模块原则，把日志细节集中到一个模块，调用方只面对
很小的接口。

### 模块

新增 `ddm/diagnostics.py`，只依赖标准库完成日志初始化；不在模块顶层导入
`PySide6`、`mpv` 或 `ddm.config`，保证导入阶段失败时仍能记日志。

### 接口

```python
session = diagnostics.start(argv=sys.argv, log_dir=None, level=None)
with session.phase("window_build"):
    window = MainWindow(...)
session.log_system_info()
session.close()

logger = diagnostics.get_logger("player")
logger.error("stream resolve failed", extra={"room_id": room_id})
```

- `start()` 幂等：重复调用返回同一个会话，不重复挂 handler。
- `phase(name)` 是上下文管理器：记录阶段开始、耗时、成功或失败；异常时写完整
  调用栈后继续向上抛出。
- `log_system_info()` 在 Qt 初始化完成后记录完整软硬件信息，失败只记警告。
- `get_logger(name)` 返回 `ddm.<name>` 标准 `logging.Logger`。
- `close()` 刷盘、关闭 handler；不关闭用户的原始 `stdout`/`stderr`。

### 实现内容

接口背后统一处理：

- 文件 handler、格式化、敏感信息脱敏、轮转和过期清理。
- `stdout`/`stderr` 镜像，带递归保护。
- `sys.excepthook`、`threading.excepthook`、`sys.unraisablehook`。
- Qt 消息处理、`faulthandler`、卡死看门狗和硬崩转储。
- 最小启动信息、完整系统信息、运行 ID 和启动阶段。
- 控制台输出开关；打包成 windowed exe 后没有控制台也不报错。

### Seam 与测试面

外部 seam 是 `start()` 和 `LogSession`；测试通过这个接口使用临时目录、注入
级别和阶段，不依赖内部 handler 类。文件、控制台、Qt、`faulthandler` 都是
实现内部细节，不暴露给调用方。

### 删除测试

如果删除 `ddm/diagnostics.py`，`setup_file_log`、stdout/stderr 镜像、异常钩子、
Qt 消息、脱敏、轮转、系统信息、启动失败处理和看门狗文件协调会重新散落到
`main.py`、`app.py`、`watchdog.py` 和多个业务模块中，因此这个模块不是
透传层，值得保留。

## 日志模型

### 级别

- `DEBUG`：可开关的诊断信息；预期内的清理、取消、Qt 对象已释放等。
- `INFO`：启动、退出、配置加载、布局切换、插件装载等正常生命周期事件。
- `WARNING`：可恢复的异常和降级，例如单路取流失败、一次重连失败、日志轮转失败。
- `ERROR`：用户可见功能失败或未预期异常，例如窗口构建失败、录制启动失败、
  插件回调异常。
- `CRITICAL`：进程级故障、Qt fatal、硬崩前现场标记。

默认级别为 `INFO`；支持环境变量 `DDM_LOG_LEVEL=DEBUG` 临时提高详细度。
未迁移的旧 `print()`：`stdout` 按 `INFO` 记录，`stderr` 按 `WARNING` 记录，
迁移到标准 logger 后再使用真实级别。

### 格式

每行包含时间、级别、类别、事件和可检索的上下文：

```text
2026-10-25 02:30:01.123 INFO  ddm.startup phase=window_shown elapsed_ms=812 run=7f3a1c9e
2026-10-25 02:30:02.456 ERROR ddm.player event=stream_resolve_failed room_id=12345
```

- 每次启动生成一个短运行 ID，启动失败日志也能关联到对应运行。
- 异常使用 `logger.exception()` 写入完整 traceback。
- 为高频重复错误增加按“事件 + 异常类型 + 调用位置”的短时间去重，避免日志
  被同一错误刷满；保留首次完整现场和重复次数。

### 文件与保留

- 普通日志：`logs/ddm.log`，UTF-8，行缓冲。
- 轮转：单文件 5 MiB，最多保留 5 个历史文件（`ddm.log.1` 到 `ddm.log.5`）。
- 过期清理：启动时删除 14 天以前的轮转文件和旧的 `ddm-*.log`。
- 崩溃现场：`logs/ddm-crash.log`，由 `faulthandler` 和看门狗追加写；
  它不参与普通日志轮转，避免轮转后硬崩栈写进已归档文件。
- `logs/` 在最早启动阶段创建；创建失败时退回控制台/系统临时目录并记录原因。

保留现有“日志目录跟着程序目录走”的便携版约定：源码运行放仓库
`logs/`，冻结 exe 放 exe 同级 `logs/`。

## 启动失败与首次启动

### 早期引导

调整 `main.py` 顺序：

1. 解析源码/冻结模式下的程序目录，加入 `sys.path`。
2. 只导入 `ddm.diagnostics`，在任何 Qt、mpv、业务模块导入之前调用
   `diagnostics.start(argv)`。
3. 写入最小启动信息：应用版本、exe/入口路径、Python、系统、架构、PID、
   启动时间、是否首次启动、脱敏后的参数。
4. 再导入 `ddm.app` 并进入原有主流程。

这样以下早期失败都能留下日志和原因：

- `PySide6` 缺失或 DLL 加载失败；
- `libmpv-2.dll` 缺失/版本不匹配；
- `ddm.app` 或其依赖导入失败；
- 配置文件读取失败；
- `QApplication` 创建失败；
- 主窗口构建、插件装载或首次用户须知失败。

### 阶段与失败出口

在 `main.py` 和 `ddm.app.main()` 的关键步骤外层使用
`with session.phase("...")`，至少覆盖：

- `bootstrap`
- `import_app`
- `qt_init`
- `config_load`
- `user_notice`
- `plugin_load`
- `window_build`
- `window_shown`
- `event_loop`
- `shutdown`

失败时统一写出：

- `[启动失败]` 标记；
- 阶段名、异常类型、异常文本和 traceback；
- 日志文件路径；
- 后续可执行的最小提示。

Qt 已创建时用 `QMessageBox` 提示；Qt 尚未创建时用标准库 `ctypes` 调
Windows `MessageBoxW`；两者都不可用时只写控制台并返回非零退出码。
`--apply-update` 更新助手也要先建立日志，再执行原有更新逻辑。

### 首次启动

首次启动不依赖 `utils/config.json` 是否成功读取：

- 在读取配置前判断 `utils/config.json` 是否存在，记录 `first_run=true`；
- 日志目录在判断之前创建；
- 用户须知显示、确认、关闭路径各记录一条生命周期日志；
- 首次启动失败也写同一份日志，不要求用户先同意须知或完成登录。

### 能力边界

PyInstaller bootloader 在 Python 启动前就失败（例如 exe 自身缺少关键运行库）
时，程序代码还没有机会运行，无法由本项目日志捕获。计划中不把这类问题伪装成
“已记录”；通过发布包自检、依赖校验和启动说明覆盖，必要时再单独评估一个
轻量启动器。这是本计划的已知限制。

## 系统信息

分两层采集，避免拖慢窗口出现：

### 早期最小信息

- 应用版本、显示名、是否冻结、exe/源码路径、工作目录；
- Windows 版本、构建号、架构、区域和时区；
- Python 版本、实现、位数、进程 ID、启动时间；
- 是否首次启动、命令行参数（脱敏）；
- 日志目录、日志级别。

### Qt 就绪后的完整信息

- CPU 型号、逻辑/物理核心数；
- 物理内存、可用磁盘空间；
- 显卡/显示适配器、驱动版本、显存（能取到多少记多少）；
- 屏幕分辨率、缩放比例、刷新率；
- 默认音频设备及可用输出设备；
- Qt 版本、libmpv 版本、FFmpeg 路径和版本、解码模式；
- 已启用插件、插件版本；
- 进程内可疑覆盖层模块（复用 `ddm/overlay.py`）。

采集全部尽力而为：单项失败记 `WARNING`，不能让启动失败。硬件编码器探测
（会启动多次 FFmpeg）不在启动时执行；只在录制初始化或用户明确诊断时记录。
不新增 `psutil` 等运行时依赖，优先用标准库、Qt 和 Windows API。

### 隐私与脱敏

日志可能被用户直接上传，必须默认脱敏：

- 不记录 `SESSDATA`、cookie、token、Authorization、代理密码；
- 不记录直播间 URL 的签名查询串；
- 不记录账号凭证文件内容；
- 路径中的用户名替换为 `%USERPROFILE%`；
- 不记录 IP、MAC、磁盘序列号等不必要的设备标识。

脱敏发生在 formatter 层，所有来源（logger、print 镜像、异常文本、Qt 消息）
都经过同一入口；另加测试防止以后新增的日志绕过。

## 静默异常治理

不采用“所有 `except` 都打 ERROR”的一刀切，否则正常的退出收尾、Qt 对象已释放
等会刷满日志。按结果分类：

| 场景 | 处理 |
| --- | --- |
| 用户可见功能失败、未预期异常 | `logger.exception()`，级别 `ERROR` |
| 单路失败但程序可继续、自动重连 | `logger.warning(..., exc_info=True)` |
| 预期内的取消、关闭、对象已释放 | `logger.debug(..., exc_info=True)` |
| 纯探测、确实无影响的清理 | 保留窄异常捕获，并写注释说明原因；不吞宽泛 `Exception` |

执行步骤：

1. 盘点 `ddm/` 中全部 `except Exception` 和 `pass`，按模块列出允许静默的
   真实场景。
2. 优先处理 `ddm/app.py`、`ddm/player.py`、`ddm/recording.py`、
   `ddm/plugins.py`、`ddm/online*.py`、`ddm/bili.py`、`ddm/danmaku.py`；
3. 补充上下文：模块、动作、房间号、插件 ID、播放/录制阶段；
4. 高频错误按签名去重；
5. 增加静态自检：宽泛 `except Exception` 的处理器不能只有 `pass`，必须调用
   日志 API 或使用明确的允许标记；
6. 插件回调异常统一记录插件 ID 和钩子名，插件侧可通过标准 logging 写日志。

## stdout/stderr 与旧代码迁移

1. 用 `_ConsoleMirror` 同时保留原控制台输出并写入 logger；覆盖
   `write/flush/isatty`，设置递归保护，避免日志 handler 写回镜像造成死循环。
2. 先全部镜像，保证 `[取流失败]` 等现有 `stdout` 信息立即进入日志。
3. 分批把 `print()` 迁移到 `diagnostics.get_logger(...)`：
   优先错误、取流、播放、录制、插件和启动路径，再处理纯界面提示。
4. 迁移后删除重复的 `file=sys.stderr, flush=True` 写法；控制台输出由
   diagnostics 的 console handler 负责。
5. `run-console.cmd` 仍然看到实时输出；`run.cmd`/windowed exe 没有控制台时
   只写文件，不抛 `NoneType` 异常。

## 与现有模块的衔接

| 现有位置 | 调整 |
| --- | --- |
| `ddm/app.py` 的 `setup_file_log()` | 移入 `ddm/diagnostics.py`；`main.py` 更早调用 |
| `ddm/app.py` 的 Qt 消息处理 | 由 diagnostics 安装；fatal 仍转储所有线程 |
| `ddm/watchdog.py` | 接收日志目录/会话，卡死栈写 `ddm-crash.log`；保持现有 4 秒阈值和去重行为 |
| `ddm/plugins.py` | `traceback.print_exc()` 改为带插件/钩子上下文的 `logger.exception()` |
| `ddm/danmaku.py` | 保留 `blivedm` 降噪，但异常状态和连接失败写统一日志 |
| `dev/selfcheck_qt_log.py` | 改为通过新接口验证 Qt 消息和无控制台场景 |
| `dev/selfcheck_watchdog.py` | 改为验证崩溃文件、轮转不串文件、同一次卡死只写一次 |
| `dev/selfcheck_user_notice.py` | 更新对 `setup_file_log` 的补丁点，验证首次启动日志 |
| `dev/check_release_package.py` | 发布包仍不能带 `logs/`；运行后应自动生成新日志文件 |
| `README.md:343` | 更新日志路径、轮转策略、级别和脱敏说明 |

## 实施阶段

每个阶段都包含实现、对应测试和独立 Git 提交。

### 阶段 1：日志核心与早期引导

- 新增 `ddm/diagnostics.py`，实现 `start()`、`LogSession`、格式化、脱敏、
  文件 handler、轮转和保留策略。
- 在 `main.py` 最前面建立日志，再导入应用。
- 接管 `stdout`/`stderr`、Python 异常钩子、Qt 消息和 `faulthandler`。
- 保持 `run-console.cmd` 和 windowed exe 两种运行方式。
- 新增 `dev/selfcheck_logging.py`。

验收：控制台和文件同时有输出；无控制台不崩；轮转和过期清理可测试；重复
初始化不重复写行。

### 阶段 2：启动失败与首次启动

- 给关键启动步骤加阶段记录。
- 实现 Qt/ctypes 两级失败提示和非零退出码。
- 记录首次启动、用户须知和 `--apply-update` 助手。
- 更新 `dev/selfcheck_user_notice.py`，新增启动失败子进程自检。

验收：临时目录首次启动、无配置、导入 Qt/mpv 失败、窗口构建抛异常时，都生成
日志并写明阶段与异常；日志路径可在提示或控制台找到。

### 阶段 3：系统信息与隐私

- 实现轻量早期信息和 Qt 就绪后的完整系统信息。
- 接入显示、音频、libmpv、FFmpeg、插件和覆盖层信息。
- 加脱敏测试，覆盖 token、cookie、URL 查询串和用户目录。

验收：正常启动日志有完整的软硬件摘要；采集单项失败不影响启动；日志中不含
测试假凭证和用户名。

### 阶段 4：静默异常与旧输出迁移

- 盘点并治理宽泛异常和 `pass`。
- 分批迁移 `print()`，优先错误和故障恢复路径。
- 接入插件日志上下文和 `threading`/`unraisable` 异常。
- 增加禁止新增静默宽泛异常的静态自检。

验收：故意制造取流、插件、线程、Qt 槽和录制异常，均能在日志中看到级别、
上下文和 traceback；预期收尾异常不制造 ERROR 噪音。

### 阶段 5：发布与文档回归

- 更新 README、运行说明和发布包自检。
- 验证源码包/exe 首次运行创建 `logs/`，发布包本身不含日志。
- 运行相关自检和有网络/原生窗口条件的全量检查。

验收：发布检查通过；用户拿到新包后首次启动即可获得日志；不新增日志入口。

## 测试计划

新增 `dev/selfcheck_logging.py`，至少覆盖：

1. `stdout` 和 `stderr` 的 `print()` 都进入文件，中文和 emoji 不乱码。
2. 标准 `logging` 调用的级别、格式、运行 ID 和上下文正确。
3. 日志 handler 写入不会再次触发镜像，无递归、无重复行。
4. 重复 `start()` 不重复挂 handler。
5. 超过大小上限后轮转，历史文件数量和过期清理符合策略。
6. `sys.excepthook`、`threading.excepthook`、`sys.unraisablehook` 都留下 traceback。
7. Qt 警告/fatal 消息进入日志；fatal 时写崩溃文件。
8. 卡死看门狗与普通日志同时写入不串文件；同一次卡死只写一次完整栈。
9. 系统信息采集成功和单项失败两种路径都不影响启动。
10. 假 token、cookie、带签名 URL、用户目录在日志中已脱敏。
11. 无 `utils/config.json` 的首次启动仍创建日志并记录 `first_run=true`。
12. 子进程模拟 `ddm.app` 导入失败，返回非零且日志包含 `[启动失败]`、阶段、
    异常类型和 traceback。
13. 宽泛 `except Exception` 只有 `pass` 的代码被静态自检拦下。
14. 发布包不含 `logs/`；第一次运行后生成 `logs/ddm.log`。

同时更新：

- `dev/selfcheck_qt_log.py`
- `dev/selfcheck_watchdog.py`
- `dev/selfcheck_user_notice.py`
- `dev/selfcheck_repository_files.py`
- `dev/check_release_package.py`

验证顺序：新增/更新的离屏自检 → `dev/run-checks.cmd` 中可在当前环境运行的
检查 → 发布包检查（如本机具备打包依赖）。需要真实直播流、网络或原生窗口的
自检单独记录结果，不把未执行说成通过。

## 验收标准

1. 第一次启动、配置缺失、Qt/mpv 导入失败和主窗口构建失败都能在 `logs/` 留下
   日志，且写明失败阶段、异常和日志路径。
2. `print()` 无论写 `stdout` 还是 `stderr`，都能在文件中找到；源码控制台运行
   仍然实时可见。
3. 日志有统一级别、格式、运行 ID、轮转和 14 天过期清理。
4. 日志包含应用、系统、CPU、内存、显卡、显示、音频、Qt、libmpv、FFmpeg 和
   插件信息；采集失败不阻塞启动。
5. 未捕获异常、后台线程异常、Qt 消息、插件回调和看门狗/硬崩都有记录。
6. `except Exception: pass` 不再静默吞掉宽泛异常；预期收尾异常使用 DEBUG 并
   有注释说明。
7. token、cookie、签名 URL 和用户名不出现在日志中。
8. 发布包不包含 `logs/`，但用户首次运行会自动创建。
9. 不增加日志查看、打开或导出入口；README 只说明文件位置和携带日志的方法。
10. 所有新增及相关自检通过，失败项和未运行项在交付说明中明确列出。

## 风险与取舍

- 日志量：全量镜像旧 `print()` 可能放大输出；通过级别、去重和迁移逐步收敛。
- 性能：系统信息采集放在窗口显示后；硬件编码器探测不在启动时执行。
- 隐私：默认脱敏，宁可少记路径和设备标识，也不把凭证写进日志。
- 多实例：多个进程同时写同一日志时只保证追加和行级完整性，不承诺跨进程
  轮转协调；如以后出现多实例需求，再单独设计文件锁。
- bootloader 级失败：Python 代码运行前的 exe 启动失败无法由本方案捕获，作为
  已知限制记录，不用“日志已生成”掩盖。
- 兼容性：旧 `ddm-*.log` 会在首次启动时被识别并清理过期文件；不删除用户最近
  的日志，也不改配置中的任何设置。

## 提交计划

1. `docs: plan comprehensive error logging`：本计划。
2. `feat(diagnostics): add structured logging and early bootstrap`：阶段 1。
3. `fix(startup): log startup failures and first-run diagnostics`：阶段 2。
4. `feat(diagnostics): collect system and privacy-safe environment info`：阶段 3。
5. `fix(logging): replace silent broad exceptions and legacy output`：阶段 4。
6. `test(release): verify runtime log creation and retention`：阶段 5。
