# DD监控室CE 软件修改交接

- 更新时间：2026-09-25（Asia/Hong_Kong）
- 交接编号：`DDM-SOFTWARE-2026-09-25`
- 工作目录：`F:\CodexAppManager\Code\DD_Monitor_CE`
- 分支：`main`。写本文时基线提交为 `6762775`；接手时以 `git log -1` 核对。
- 状态：材料已核对，仅保存交接；未新建接续任务。

## 当前目标与用户已确认的行为

- 布局缩小时，优先把**正在开播**的格子保留进较少的显示位。例：1+5 中主格和下排最左格开播，切 1+2 时应显示这两格；实现和回归在 `ddm/app.py:_prioritize_live_tiles()`、`dev/selfcheck_layout_live_priority.py`（`6fed3d1`）。
- `F` 进入单格全屏，再按 `F` 或 `Esc` 均退出；格子底栏有全屏按钮。此前退出全屏出现窗口收缩、页面刷新及卡顿，相关迭代在 `7650f7c` 至 `6a1daab`。用户确认“没有刷新了”，但之后仍报告卡顿；最新性能提交没有新的用户验收反馈。
- 全屏问题的用户原始录屏在本机 `H:\Videos_output\2026-09-25 16-42-11.mp4`、`16-44-39.mp4`、`17-32-40.mp4`、`18-04-11.mp4`（后面三项同目录）；换机器需另带走。
- 刷新直播状态要正确处理下播（`db0afa6`）。断流重连常态开启，不再给用户一个开关（`a8ad442`）。默认静音属于格子状态，不应被误表述为主播全局状态。
- 录制、即时重放和每格独立音频已加入。设置文字的定位见提交 `5c9648d` 及 `ddm/dialogs.py`；录制/回放功能和性能改动见 `a7b3b11`、`383e0dd`、`58ad042`、`31638f7`、`0b38921`、`46706b1`。软件与视频是两条工作线；不要从宣传片镜头倒推软件行为。

## 本轮回退及当前未解决问题

用户最后报告**收起后的关注栏头像全部消失**。上一轮尝试修复并提交 `bce6cba`，改了 `ddm/widgets.py`、`ddm/images.py`、`ddm/app.py`，增加头像占位显示及按房间号缓存；用户本轮明确要求“回退修改”。现已用 `6762775` 独立 revert，`git diff 6a1daab HEAD -- ddm/app.py ddm/images.py ddm/widgets.py dev/selfcheck_sidebar_compact_avatars.py` 为空，新增自检文件也已删除。**头像问题因此仍未解决**，不能写成已修复。

上一轮的离线合成图复现显示：给 `NavThumb` 主动注入 `QPixmap` 后，收起状态头像能显示；没有图片时，`set_thumb_size()` 会按 `bool(self.face.pixmap())` 隐藏占位头像。真实环境中“为什么所有主播头像没有加载/显示”尚未确认；不能把这个假设当成最终根因，也不要未经复现直接重放 `bce6cba`。

## 主要文件与验证入口

| 范围 | 路径 |
| --- | --- |
| 软件主窗口、状态刷新、布局优先级、全屏 | `ddm/app.py`、`ddm/window_fullscreen.py` |
| 关注栏头像、收起布局、格子控件 | `ddm/widgets.py`；关键类 `Avatar`、`NavThumb`、`NavItem`、`Sidebar` |
| 头像下载与缓存 | `ddm/images.py`；启动时房间记录来自 `ddm/config.py:build_rooms()`，先是占位，随后状态轮询补资料 |
| 直播接口和状态轮询 | `ddm/bili.py`，`rooms_status()` / `StatusPoller` |
| 设置文案 | `ddm/dialogs.py`、`ddm/config.py`，详见 `5c9648d` |
| 现成自检 | `dev/selfcheck_portrait_compact.py`、`dev/selfcheck_avatars.py`、`dev/selfcheck_layout_live_priority.py`；全屏相关测试需在 `dev/` 里按现行代码查找 |

本次回退后已验证：`dev/selfcheck_portrait_compact.py`、`dev/selfcheck_layout_live_priority.py` 通过；`python -m compileall -q ddm` 通过。上述是离线/合成数据验证，未验证真实 B 站接口下的头像加载。真实直播/软件性能仍须用户运行环境复测。

## 工作区与接续动作

交接时既存未提交内容：`ddm/dialogs.py`、`idea.txt`、`videos/dd-monitor-ce-promo/raw/take-events.json` 有修改；`HANDOFF-PROMO-V3*.md`、`dev/mock_portrait.py`、`dev/portrait_mock.html` 等未跟踪。它们不是本次回退产生的，不要 `git add -A`、覆盖或清理。另有 `ddm_plugins_dd3l0oxq/` 目录枚举时权限警告，未对它做处理。

接续软件线时，第一步先在真实/可控 Qt 场景分别检查**有头像图片**和**无头像图片**的收起/展开：记录 `NavThumb._face_source`、`face.pixmap()`、显隐、几何，以及 `AvatarLoader`/状态轮询是否收到 `face` URL。确定数据丢失还是 UI 隐藏后做最小修复；为两种状态补回归测试，运行相关自检，并按仓库 `AGENTS.md` 每次改动对应 Git commit。任何新的头像修复都需要用户重新验收收起态画面。

仅保存的接续开场白：`$project-handoff 请读取 F:\CodexAppManager\Code\DD_Monitor_CE\HANDOFF-SOFTWARE-2026-09-25.md（DDM-SOFTWARE-2026-09-25），在原仓库继续软件修改。先只读核对 6762775 回退和关注栏头像问题，区分图片缺失与 UI 隐藏，再提出最小复现及第一步。`
