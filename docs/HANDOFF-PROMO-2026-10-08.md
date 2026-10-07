# 宣传片交接：PROMO-20261008-01

更新时间：2026-10-08，Asia/Hong_Kong。用户要求“执行交接并新建对话”，范围是当前宣传片工程维护和后续真实素材微调，不接续软件业务开发、网站、账号或其他对话任务。

## 接手结果（2026-10-08 01:12，Asia/Hong_Kong）

- 状态：已接手。接手对话 `01a11758-8cca-7382-a41f-0a33ba0d0491` 已收到源任务继续指令；宣传片及本交接区修改权已移交，等待用户新素材或具体微调反馈。
- 只读核验时 HEAD 为 `fd93ce7`，main 与目录一致，`bdd9019`、`6de857d` 均为 HEAD 祖先；既有未跟踪保护项一致，无阻止接续的差异。
- 实际 `ffprobe` 结果：样片 07 为 H.264/AAC、60.000000 秒、1920×1080、30/1、1800 帧、88733939 bytes。国内重置原源及派生素材存在，当前 HTML 的关键字幕、连续配乐和待补段与交接一致。
- `Get-Process` 确认既有预览 PID `48276` 为 node；`Invoke-WebRequest http://127.0.0.1:3017/` 返回 HTTP 200、1264 bytes。仅确认服务首页可访问，未验证浏览器播放，不重新启动服务。
- 下一次素材替换入口：`compositions/audition.html` 对应 41.515–49.091 秒（7.576 秒双解说原声，收到素材后压低配乐）；`compositions/updates.html` 对应 49.091–56.061 秒（6.970 秒关注管理、画面弹幕、插件管理操作）。两条路径相对 `videos/dd-monitor-ce-plugins-promo/`，时间入口在 `index.html`；两段均待用户补录。
- 本次只更新交接记录及相关记录测试，不重跑完整视频回归、不重渲染或改动满意的字幕、音乐和画面；根状态文件继续被忽略。

## 工作目录与版本

- 项目根目录：`F:/CodexAppManager/Code/DD_Monitor_CE`；同项目 local 环境，main 分支。
- 交接登记：根目录 `PROJECT_STATE.md` 顶部 `PROMO-20261008-01` 区。该状态文件被忽略，只在本机保存；不得覆盖其余历史任务区。
- 源对话：`01a10311-fd87-7491-9383-35f6a782efc0`。接手对话和执行状态以登记区为准。
- 业务基线提交：`bdd9019`（国内重置素材及 Studio 本地依赖）、`6de857d`（VideoTogether 兼容修复）。交接资料提交会在其后，不能据此判断业务基线丢失。
- 当前无本任务未提交业务改动。既有未跟踪保护项：`console.log('ERR'`、`dev/mock_portrait.py`、`dev/portrait_mock.html`、`dev/test_verify_promo_archive.py`、`dev/verify_promo_archive.py`、`plugins_user/match_sync/`；实时 Git 状态优先，不清理或一起提交。

## 关键成果与资料

路径相对于上述根目录；媒体和工作证据大多被 Git 忽略，仅本机存在。

- 工程：`videos/dd-monitor-ce-plugins-promo/index.html`，9 个 `compositions/*.html` 子场景；精确时长、字幕、排版和动画以当前 HTML 为准。
- 最新导出：`videos/dd-monitor-ce-plugins-promo/renders/sample-v7.mp4`，60 秒、1920×1080、30fps、1800 帧，约 84.6 MB。最新兼容修复只影响扩展接管，不改变画面，无需重新编码已有成片。
- 原始素材：`Video_reference/`；派生素材：工程 `assets/`；音乐：工程 `.media/audio/bgm/bgm_001.mp3`；许可记录：工程 `MEDIA.md`。
- 当前视频来源：工程 `sources.json`；海外逐格范围：`cell-selections.json`；旧 `domestic-cell-selections.json` 为样片 06 历史记录，不是样片 07 当前国内来源。
- 脚本：`docs/VIDEO-SCRIPT-2026-10-07.md`；版本记录：`docs/VIDEO-SAMPLE-2026-10-07.md`。文件含历史段落，样片 07 和当前 HTML 覆盖旧顺序、卡片数、国内替换方案、海外字幕说明及未复现错误的旧结论。
- 真实 `limited` 调用栈、兼容方法和用户验收：工程 `PREVIEW-TROUBLESHOOTING.md`。它覆盖上述文档中“根因未确认”的旧状态。
- 旧片已封存：`results/dd-monitor-ce-promo-archive-2026-10-04.zip`，旧原目录保留；详情与校验信息在 `docs/VIDEO-ARCHIVE-2026-10-04.md`。不再重复打包，不动旧 ZIP。

## 当前有效决定

1. 约 1 分钟、HTML / HyperFrames / GSAP 动效、真实软件录屏、制作虚拟指针，动作卡音乐节奏。深灰、近白和青蓝，大字号中文。
2. 展示顺序为国内 Apex 1+5 → 海外九格 → 比赛二路 → 独立双解说试听 → 软件本体更新 → 片尾。国内不再是九格；九张关注卡片不等于九个直播窗口。
3. 国内使用 `Video_reference/国内apex1+5 重置.mp4` 原源 8.9–25.3 秒，派生 `assets/domestic-apex-v7.mp4`；开场与国内连续播放派生 0–16.364 秒。六窗来自同一整墙实录，无逐格替换、循环或变速。右中格到原源 17.86 秒才揭示，避开早期暂停/桌面。
4. 用户确认从录屏最顶部部分可见卡片开始，随后八张完整卡片；不要补造被截掉的卡片上半部。九卡间隔 .34 秒；国内局部 3.8–4.7 秒拉回、4.9 秒起六窗间隔 .212 秒揭示。
5. 海外优先同时最高画质实录；网络不足仍允许逐格高清拼接。当前 `global-stitched.mp4` 从两条录屏选各格 6.06 秒，不能包装成同时九路高清流畅的性能证明。用户已删除片中的旧拼接说明，当前 HTML 未显示该说明；历史脚本仍写显示说明，二者有差异。保留现有用户字幕，不自行恢复已删除文本；若新增拼接方式或性能表述，需要结合用户意图确认表达。
6. 用户字幕保留：开场“红队绿队一起看。”；国内“为你的ALGS观看如“虎”添翼”；海外“海外的直播也一样 / 国（内）外大神视角一屏掌握”。当前更新文案是“让每次打开，都更顺手。”及“关注，整理有序 / 弹幕，随心调整 / 插件，集中管理”，以 HTML 为准。
7. Twitch / YouTube 作为同一海外插件的叙事，跨平台整体作为一项能力；不要拆成两则广告。比赛二路基本开发完成，但当前录屏展示手动微调，注明“自动对齐优先，必要时手动微调。”及“本段录屏展示手动偏移微调”。用户可能无法重录手动操作，不要求强行补录；不把手动录屏称为自动对齐演示。
8. 二路登场、对齐、弹幕和试听占位使用同一源 `二路直播对齐.mp4` 原源约 6–32.667 秒连续内容，避免换到别的比赛素材；23–24 秒突变已修复，保留连续交接。
9. 音乐用户最终选择 Future Bass Tech Corporate — PaulYudin，许可见 MEDIA.md。曾授权截断静音制造反差，但后续明确修复平台切换音乐停止和二路断音：当前片中连续，开头 .65 秒淡入、片尾淡出，不恢复旧约 21 秒或 23–24 秒静音。
10. 原始直播录屏无有效直播声音。41.515–49.091 秒独立 audition 段预留真实双解说，7.576 秒，无弹幕宣传字幕；现在只有原声待补提示和 BGM，不伪造人声。用户提供有声素材后替换该段并压低配乐。
11. 本体总结仅关注管理、画面弹幕、插件管理；不纳入平台或二路插件功能。49.091–56.061 秒当前为软件全景占位且有待替换提示，对应三项本体操作录屏待补。

## 已验证及运行状态

- 样片 07 素材、规格、关键帧、逐格冻结、源帧匹配、连续音乐、二路同源、文字等验证通过；可见国内窗最长低变化 .4 秒，回归门限 .5 秒。完整成片解码通过。
- 最新 Python 验证：`python -m unittest dev.test_plugins_promo_sample dev.test_video_script_20261007 -v`，21 项通过；其中调用 `node --test dev/test_promo_videotogether.cjs`，6 项扩展专项回归通过。
- 最新 HyperFrames 0.8.140 `check` 零错误、零警告、零 INFO，300 动画采样；实际 Studio Lint 空 findings。最新检查报告 `work/limited-runtime/check.json`；素材及成片证据 `work/plugins-promo-v7/`。
- limited 根因真实栈来自 Edge VideoTogether 3.0.23 的 isLimited → VideoClicked。其每 5 秒 15 请求限流把预览多视频 play/pause/seeked 误报为 error。当前入口标记本合成视频 VideoTogetherDisabled 并仅移除该扩展已知监听器，微任务覆盖晚注入及动态挂载；保留框架事件和 console.error。用户明确验收“刷新后不再出现”。无该扩展的 IAB 未复现不能作为唯一验收依据。
- 临时诊断脚本和网络采集均已移除；127.0.0.1:3018 采集器已停止，旧日志 `work/limited-runtime/events.jsonl` 仅作本机证据。
- 托管后台预览已核实运行：PID 48276，`http://127.0.0.1:3017/#project/dd-monitor-ce-plugins-promo`。日志 `C:/Users/Lan/.local/state/hyperframes/previews/ff67ce049c97bff0.log`。属于项目托管服务，不是旧 exec 回合的临时进程；不要另启占用同端口的预览。
- 最新预览截图 `work/limited-runtime/preview-fixed.jpg`。没有进行发布、推送或软件打包。

## 接续第一步与边界

接手先只读核对交接编号、目录、main/提交祖先、工程、成片、素材、预览状态及上述限制，返回差异，不修改业务文件。源对话登记并发送继续指令后，第一步检查成片 ffprobe 规格和既有预览服务可用性，将本交接登记更新为“已接手”，附实际核验结果，整理下一次素材替换入口。已通过的完整测试不为交接无故重跑。

然后等待用户新素材或具体微调反馈：双解说原声与本体录屏尚未收到；不要自行改变满意的文案、节奏、音乐或猜测最终素材。新改动必须相关测试、HyperFrames check 和 Git commit。未授权公开发布、推送、软件业务修改、浏览器扩展全局禁用或安装；不新建 worktree、不 fork 携带整段旧历史。读取相关 HyperFrames 技能后再改动或渲染视频。
