# 旧宣传片封存与新片制作约定

- 封存编号：`DDM-PROMO-ARCHIVE-20261004-01`
- 日期：2026-10-04（Asia/Hong_Kong）
- 本机 ZIP：`results/dd-monitor-ce-promo-archive-2026-10-04.zip`
- ZIP 大小：3,768,646,229 字节，约 3.51 GiB。
- ZIP SHA-256：`3f9bde92f1fa181c39a356e239e54482abc70186541f5d67799868ea4de17b9d`
- 校验报告：同目录 `dd-monitor-ce-promo-archive-2026-10-04.verification.json`。
- 校验摘要：同目录 `dd-monitor-ce-promo-archive-2026-10-04.sha256`。

## 封存范围与验证

完整保留 `videos/dd-monitor-ce-promo/` 和 `Video_reference/` 的全部文件，包括隐藏目录、HTML 工程、制作工具、原始录屏、图片、BGM、音效、参考片、封面、快照和历次渲染。另收录三个 `HANDOFF-PROMO*.md`、`HANDOFF-VIDEO-2026-09-25.md` 和新视频交接记录的封存时快照。原目录保留，未移动或删除。ZIP 内的路径相对于主仓库根目录，解压时可恢复原目录结构；运行依赖仍需原软件与运行环境。

共收录 2,395 个源文件、3,933,422,215 字节；额外附带 `ARCHIVE-MANIFEST.json`，逐文件记录路径、大小与 SHA-256。包内条目无重复，清单完整；全部条目已解压读取，通过 ZIP CRC 和 SHA-256 检查，并与本机原文件逐项比对一致。

相关验证程序为 `dev/verify_promo_archive.py`，测试为 `dev/test_verify_promo_archive.py`。两项测试通过，覆盖有效归档、源内容变更、源文件丢失与 ZIP 缺失条目。验证整个封存包通过；未修改旧片 HTML 或插件业务代码。

## 已确认的新片要求

- 约一分钟，比赛二路功能与软件更新为主要内容。
- 国内平台与 Twitch、YouTube 在视频叙事中作为同一项跨平台直播能力；源码仍为两个独立插件包。
- 用户提供初步脚本，由接手任务补全其余内容并制作可供用户修改的视频版本；不把此前建议的时间分配视为定稿。
- 用户重新录制素材；使用 HTML 制作动效，关键动作及切镜对齐音乐节拍。音乐尚未提供或选定。
- 延续旧片视觉风格。软件演示使用真实素材；比赛二路尚未完成，效果与文案按实际验证范围决定。

## 技能核对结论

- 用户指定的 `.codex/skills/hyperframes/SKILL.md` 与 `.agents/skills/hyperframes/SKILL.md` 内容一致。
- HyperFrames 负责可寻帧的 HTML 时间轴、媒体播放、预览与渲染；core 管理片段时序，animation 与 keyframes 管理文字、转场和镜头运动。
- motion-web 负责构图、缓动与动效设计参考。它的鼠标、滚动、自由运行时钟和交互弹簧示例不能直接充当离线渲染时间轴，需转换为确定性的动画。
- 音乐驱动的专用流程使用 music-to-video 的 `audiomap.json`。CLI 的 `beats` 是另一项 Studio 节拍网格工具，不能替代前者的分析流程。具体工作流待用户初稿和音乐到位后按最终内容选择。
- 本轮只检查技能与封存旧片，没有安装/升级技能，也没有制作新片、录制、渲染或发布。
