# DD监控室CE 宣传片交接（视频线）

- 更新时间：2026-09-25（Asia/Hong_Kong）
- 交接编号：`DDM-VIDEO-2026-09-25`
- 工作目录：`F:\CodexAppManager\Code\DD_Monitor_CE\videos\dd-monitor-ce-promo`
- 仓库：`F:\CodexAppManager\Code\DD_Monitor_CE`，分支 `main`。写本文时基线提交为 `6762775`；接手时以 `git log -1` 核对。
- 状态：材料已核对，仅保存交接；未新建接续任务。

这份文件只记录宣传片。历史交接 `HANDOFF-PROMO-V3.md`、`HANDOFF-PROMO-V3-S2.md`、`HANDOFF-PROMO-V3-S3.md` 描述的是更早阶段，其中“04 素材缺失”“06 仍是模板”“连播只到 03”等状态已过时。接手时以现有源码、素材和用户最新反馈核对，不把旧交接当成新指令。

## 目标与已确认方向

- 用 HTML/HyperFrames 制作 DD监控室CE 宣传片，以真实软件截图和录屏展示功能；参考 `Video_reference/来看看最新的_MC_启动器___LauncherX.29543304125.mp4` 的字体节奏、转场和色场。软件实际画面优先于 DOM 伪造。
- 最初分镜来自仓库根 `Video_reference/Script.txt`；现行实现的增补记录在 `SCRIPT-v3.md`，若二者与用户后续明确修改冲突，以后续修改为准。
- 配乐来自 `Video_reference/【合集】一口气看完17个Microsoft微软官方广告.2022年-Microsoft_-_Loop.550193601.mp4`，片尾标注 `BGM · Microsoft-Loop`。04 的直播声音在约 25 秒处渐入、渐出，左右声道两格同时播放。
- 06 不介绍插件。1+5 录屏按 REC 点击顺序移动镜头，再退远；即时重放聚焦 PR 时间轴的长短两段素材，并用“更高效的录制切片，切出爆点”；反馈与关于项目在同一页，右侧同心圆弧运动；最后使用真实九格画面墙抽拉，`画面墙3` 只截取实录的两排。
- 用户最后针对视频的反馈是：移除即时重放右上角和画面墙左上角占位标记，调整长短素材选中框（蓝框两侧多出、黄框偏右）。对应提交为 `d05014c`、`664ef65`；尚无用户明确的最终验收结论。

## 当前可检查成果

| 内容 | 文件/说明 |
| --- | --- |
| 当前 01–07 连播样片 | `videos/dd-monitor-ce-promo/renders/v3-01-07-design-preview.mp4`；本机 `ffprobe` 实测 78.566667 秒。`renders/` 被忽略，不在 Git 中 |
| 06 现行场景 | `videos/dd-monitor-ce-promo/compositions/v3/18-06-design.html`；`18-06-oss.html` 是上一版，勿误当成现行样片 |
| 07 结尾 | `videos/dd-monitor-ce-promo/compositions/v3/18-07-end.html`，含 BGM 署名 |
| 连播混音/组装 | `videos/dd-monitor-ce-promo/tools/assemble_v3_01_07_design.py`，单段验证在 `tools/test_v3_01_07_design.py` |
| 06 素材处理 | `videos/dd-monitor-ce-promo/tools/build_v3_06_recorded_assets.py` |
| 当前脚本 | `videos/dd-monitor-ce-promo/SCRIPT-v3.md`、`SCRIPT-06-RECORDED.md`；后者的早期时间估计仍需以实际成片为准 |
| 原始录屏 | 仓库根 `Video_reference/录制.mp4`、`pr片段.mp4`、`画面墙1.mp4`、`画面墙2.mp4`、`画面墙3.mp4`、`左声道.mp4`、`右声道.mp4`、`声音打开.mp4`、`聚焦卡片_卡片预览.mp4` |
| 本地配乐 | `videos/dd-monitor-ce-promo/assets/bgm/ms-loop.wav`，由用户指定的微软广告合集提取 |

01 为九格真实画面拆分拼入；03 使用聚焦卡片录屏；04 已接入声音展示，解决了双声道展示末尾停帧问题（`ee0b61f`）；05 是贴近软件风格的文字动效，早期“平均缓冲时长/平均内存占用”没有实测值，现版改为功能文案；06 已换真实录屏（`2b07d05`、`931836d`）。此前 03–07 模板状态和 05 的数值占位记录不可直接套用。

## 未提交内容、限制与待核对

- `videos/dd-monitor-ce-promo/raw/take-events.json` 在本次交接时有**既存未提交修改**，不是本次回退或交接造成的；不要覆盖、清理或顺手提交。根目录 `idea.txt`、`ddm/dialogs.py` 等也有其它未提交工作。
- `Video_reference/` 和 `renders/` 是本机素材/产物，换机器需另行带走。本次没有重新渲染成片；78.566667 秒是现有文件时长，不代表用户已批准最终版。
- `BRIEF.md` 和早期 `SCRIPT-v3.md` 某些段落仍写“约 60 秒”“06 模板”或旧拍号；现行 06 场景和样片已与之不同。不要静默按旧总长重剪。
- 直播画面涉及真实主播，录屏与音轨的使用范围按用户已给素材及后续发布要求处理；当前没有发布授权或发布动作。

## 接续第一步与验收

先只读对照 `18-06-design.html`、组装脚本、`tools/test_v3_01_07_design.py` 和现有连播文件，确认 06 的 REC 跟随、PR 选框、画面墙裁切、04 双声道及片尾 BGM 名称在当前样片中的实际效果；再按用户反馈决定是否继续调整。修改 HTML 前读取工程 `AGENTS.md` 和 HyperFrames 相关技能；改动后按工程要求运行 `npm run check`、相关视频测试与必要渲染，逐镜头检查真实像素/裁切，并提交对应 Git commit。没有本轮启动的预览服务或渲染任务；其它进程状态未核实。

仅保存的接续开场白：`$project-handoff 请读取 F:\CodexAppManager\Code\DD_Monitor_CE\HANDOFF-VIDEO-2026-09-25.md（DDM-VIDEO-2026-09-25），在原仓库继续宣传片。先只读核对现行 06 场景、78.566667 秒样片及最近的 PR 选框修正，再说明差异和第一步。`
