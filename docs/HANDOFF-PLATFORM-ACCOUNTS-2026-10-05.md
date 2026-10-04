# 多平台关注导入交接

交接编号：`PLATFORM-FOLLOWS-20261005-01`。更新时间：2026-10-05，Asia/Hong_Kong。

## 本次任务与成果

用户要求修复斗鱼关注导入仍需要手动点击读取的问题，完成后保存交接并新建对话。
用户已明确：问题发生在**关闭导入窗口后重新打开**，而非同一窗口来回切换。

- 工作目录：`F:\CodexAppManager\Code\DD_Monitor_CE`，分支 `main`。
- 本次修复提交：`ff8af3e`（自动读取已登录平台关注）。
- 前一次修复：`9e3180f`，仅保留同一导入窗口内的列表，不能覆盖重新打开窗口。
- 当前成果：已登录斗鱼后，重新打开导入窗口并选择斗鱼会自动读取最新列表；读取期间显示与 B 站一致的列表加载布局，不导航登录页。
- 同一窗口切回平台直接恢复已成功读取的页面，包括勾选、搜索和目标文件夹；成功的空列表也保留。
- 登录失效、请求失败或登录状态保存失败时回退官方登录页，由用户重新登录或重试；没有无限自动重试。
- 未勾选“记住登录”时，同次软件运行内可复用内存 Cookie，并保留该选择；没有新增明文凭据文件。
- 退出账号清除内存会话；取消自动读取会取消后台请求并等待结束，忽略迟到结果。
- 源码修复及模拟平台回归已完成；**用户真实斗鱼账号验收尚未完成**。没有自动访问用户 Cookie 或配置，没有重启或终止用户正在运行的软件。

## 实现位置

- `ddm/account_dialog.py`：平台按钮、窗口内页面缓存、已登录平台的自动读取入口、共享加载布局、失败回退、取消收尾。
- `ddm/platform_login.py`：隔离 WebEngine Cookie、官方登录、后台请求、读取失败信号、内存会话与记住登录选择的恢复。
- `ddm/app.py`：登录身份优先级、统一菜单、关注导入入口、内存会话生命周期与退出账号。
- `ddm/account_store.py`：已有 Windows DPAPI 加密存储；本轮未修改。
- `ddm/dialogs.py` 的 `FollowImportDialog`：勾选、按名称搜索、普通文件夹选择；本轮未修改业务实现。

请保持浏览器嵌入窗口的现有处理：在创建 WebEngine 前将 QDialog 改为 Qt.Widget，不拆开删除浏览器/page，不随平台切换销毁浏览器树。

## 验证证据与运行

Python：`F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe -X utf8`。

Qt 6.11 为此解释器默认版本；Qt 6.9 通过单次命令环境 `PYTHONPATH=F:/CodexAppManager/Code/DD_Monitor_CE/work/deps` 切换。
生产入口为项目根目录 `run.cmd`（源码启动）；本轮未打包 EXE 或上传软件/插件。
用户需关闭旧进程，再从 `run.cmd` 启动新代码；旧 EXE 不会自动包含这次修复。

通过的相关回归：

- `dev/selfcheck_platform_follow_reopen.py`：重新创建导入窗口、自动读取最新/空列表、不导航登录页、内存/加密存储会话、记住登录选择、登录失效回退及重试、取消与退出账号。Qt 6.11/6.9 通过。
- `dev/selfcheck_account_dialog.py`：同窗平台切换、选择隔离、页面释放、失败重试与取消。Qt 6.11/6.9 通过。
- `dev/selfcheck_accounts.py`：登录身份、B 站优先级、账号菜单、Cookie 原域恢复及退出。Qt 6.11/6.9 通过。
- `dev/selfcheck_platform_follows.py`：DPAPI、真实 off-record WebEngine、后台线程、Cookie 域隔离、导入去重与取消。Qt 6.11/6.9 通过。
- `dev/selfcheck_account_render.py`：实际 Windows 桌面合成截图，8 次往返及 2 次重新打开导入窗口，颜色、尺寸和边界正确，没有新增登录导航。Qt 6.11/6.9 通过。
- `dev/selfcheck_follow_import.py`：名称搜索、整行勾选、文件夹、宿主保存与去重。Qt 6.11/6.9 通过；本轮补充了点击前同步 QCursor 位置，消除取决于用户鼠标位置的测试误报。
- `dev/selfcheck_account_recovery.py`：账号失败恢复和退出后旧请求隔离，Qt 6.11 通过。
- 以 `9e3180f` 的旧 AccountPlatformDialog 替换测试类，新的复开用例失败，确认旧实现确实遗漏此入口；当前实现通过。

测试使用虚构账号与 Cookie。除加密存储分支用例在局部设 DDM_NO_SAVE=0 并替换 AccountStore.load/save/clear 外，均为 DDM_NO_SAVE=1，不能读取真实配置、Cookie 或直播签名链接。
不要并行运行原生窗口截图测试；用户软件可能置顶，截图用例仅将自己的测试窗口置顶，未修改用户软件。
窗口截图保存在被忽略的 `work/preview/account-switch-*.png`，仅本机可用。

## 仍有效的产品约束

- 国内平台合并一个插件：`domestic_live`，虎牙、斗鱼、抖音；海外平台单独插件：`global_live`，Twitch、YouTube。
- 核心是关注栏卡片与拖入软件格子正常播放，原生播放和弹幕是后续能力；不要退回网页快捷方式。
- 平台标识使用图标；只有单一平台时不显示关注卡片的平台标识；图标背景透明。
- 插件禁用时，其关注和格子内容转为暂存，禁用期间不显示，重新启用可恢复。
- 保持竖屏布局/预览适配和各平台自身清晰度选项；海外自动清晰度已有实现，不统一改成 B 站的档位。
- 登录/导入平台按钮内置于统一窗口；B 站账号优先显示，无 B 站登录时显示其他账号头像/UID及平台图标。
- 账号及关注导入当前可用的平台是 B 站和斗鱼；虎牙、抖音、Twitch、YouTube 的账号关注导入未在本轮实现，不能宣称已经支持。
- 软件和插件分开仓库，插件共用公开仓库 `Lanpropro/DD_Monitor_Plugins`；网站工作有独立对话，本交接不接管其发布。
- 历史用户曾要求两插件版本 1.0；本轮只读发现本机 domestic_live 清单为 1.1、global_live 为 1.0。版本变化归属其他并行工作，未在本轮修改，接手应重新读取当前清单而非自行回退。

## 并行工作与交接边界

本项目还有软件与比赛二路插件对话并行编辑。只提交本次明确修改路径，不能 git add -A、清理或重置整个工作区。
本轮交付时保护项包括 `ddm/dialogs.py`、比赛插件相关测试及 `plugins_user/_match_sync/` 的修改，
以及 `console.log('ERR'`、`dev/mock_portrait.py`、`dev/portrait_mock.html`、`dev/selfcheck_douyu_playback_auth.py`、
`dev/selfcheck_match_sync_chat.py`、`plugins_user/match_sync/` 等未跟踪项。接手以实时 git status 为准；本轮没有覆盖或提交这些内容。

## 接续第一步与验收

1. 先只读核对目录、交接编号、`ff8af3e` 及文件存在、当前 Git 状态、授权边界，返回差异；等待源对话的交接登记与继续指令。
2. 收到继续指令后，运行 `dev/selfcheck_platform_follow_reopen.py` 和 `dev/selfcheck_account_dialog.py` 做接手复核，记录实际结果及“已接手”状态。
3. 接续多平台账号与关注功能维护，先等待用户从 run.cmd 重启后验收：登录斗鱼 → 关闭导入窗口 → 重新打开 → 选择斗鱼，自动出现列表；窗口内 B 站/斗鱼切换保留勾选；退出斗鱼后需重新登录。
4. 如果用户仍报告问题，先确认当前入口/版本与同窗或复开场景，再复现；不要仅重复上次页面缓存方案。
5. 用户验收前不把任务写为“用户已验收”。未经新授权不发布、推送、打包、接管网站/比赛插件或自行增加其他平台登录。

交接实时登记保存在项目根目录被忽略的 `PROJECT_STATE.md` 顶部；它仅本机可用，保留下方其他任务记录。本文件是可提交的无凭据简报。
