# 插件接口

`context.retain_media_source(factory, prepared)` 将插件已准备的二进制媒体读取器交给播放器，返回随机路径的本机回环 HTTP 地址。读取器实现 `read(size)`、幂等 `close()`，可选 `network_speed()`；`factory(cancelled)` 为录制等额外消费者创建独立读取器，不共享消费位置。插件负责协议、分片和复用，宿主负责 HTTP 交付及停止生命周期。播放器切档、停止或插件卸载时关闭读取器；取消后未使用的地址也会清理。该接口不读取账号配置。

`context.ffmpeg_executable()` 返回宿主录制功能所用的 FFmpeg 路径。平台的 `play_url`、`preview_url` 可声明 `cancelled` 回调，后台取流器会传入取消状态；旧签名保持兼容。回归入口为根 `run.cmd --check-media-sources`。

> 类型：参考 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-16 ｜ 读者：插件作者

## 本页导航

面向插件作者。建议先读[目录约定](#目录约定)和[最小插件](#最小插件)，再按需要查看事件、平台、发送、
菜单、格子控件、登录与录制服务。新增能力会标注“配套开发接口”，使用前先检查宿主是否提供对应字段或方法；
旧宿主忽略未知能力时，插件应保留降级路径。

## 搜索匹配（配套开发接口）

`from ddm.search import matches_query` 提供与本体共用的纯文本匹配：`matches_query(text, query)`支持中文、英文、数字、拼音全拼与首字母；空白分隔多个词按AND匹配，空查询返回真。底层 `matches_text(text, term)` 保留既有单项匹配语义。两者不修改数据、不查询账号资料、不访问网络；插件保留自己的检索字段、筛选与排序。

所有插件搜索框遵守[搜索框统一约定](development/ui-components.md#搜索框统一约定)。此接口已在当前开发源码实现，版本号本身不证明旧安装包已包含；插件应在配套要求中写明所需本体能力，缺接口时不能静默降为普通子串匹配。

## 独立工作进程启动（配套开发接口）

`ddm.plugins.worker_command(__file__, 'worker_module')`返回程序路径和参数列表，供插件自己的`QProcess`使用；源码与打包EXE共用`--plugin-worker`入口。模块必须是插件目录内的单个Python模块，提供无参数`run()`，返回退出码。入口只建立相对导入包，不执行`plugin.py/on_load`、发现其他插件或初始化主窗口/账号配置。插件自行管理进程、界面、数据协议与退出清理，不跨进程传递Qt对象。

这是新增能力，使用前检查`hasattr(api, 'worker_command')`；旧本体可保留原实现。进程隔离不构成插件权限沙箱；只运行用户已安装并信任的插件源码。版本号本身不保证已包含此开发接口。

## 独立浏览器账号与关注（配套开发接口）

平台可选提供`browser_login_url`、`browser_cookie_domains`、`browser_account_info(session, cancelled)`与`browser_follow_rooms(session, cancelled)`。
以下浏览器登录选择仅适用于已提供上述能力的平台；未提供`browser_login_url`的插件继续使用原有OAuth或网页登录入口。宿主提供可选接口不代表当前安装的海外插件已经接入。
宿主账号窗口在首次登录且本机已配置该平台的OAuth客户端时优先使用官方授权；未配置时提供无需开发者客户端的网页登录。已有OAuth或网页登录会话沿用原流程，网页登录页也保留OAuth高级入口。客户端配置损坏时仍可选择网页登录；离线检查不读取本机客户端配置。旧宿主忽略这些可选字段，继续使用原有OAuth能力。
YouTube和Twitch导入页提供“重新读取”，重新请求当前账号的关注；窗口内切换平台继续保留上次列表及勾选。YouTube订阅接口不返回开播状态，频道以`live_known=False`导入，由正常状态刷新流程补齐。
浏览器由`account_browser.py`以临时独立资料目录启动，支持本机Chrome或Edge。用户在普通窗口登录并关闭后，才通过同一临时资料目录的后台浏览器读取指定平台域的Cookie，不在登录页面启用调试，也不使用日常浏览器资料。HTTP(S)代理从当前进程传入登录浏览器，回环控制连接始终直连。完成或取消后释放本次进程与资料目录，持久登录仅沿用AccountStore的DPAPI存储。
工作线程拥有请求会话，平台通过`cancelled()`停止分页；只有完整成功才发布关注列表。`session.ddm_follow_progress(count)`为可选的已读取数量反馈。网络失败不等于登录失效；仅身份被明确拒绝时抛出既有`LoginRequiredError`并回到网页登录。
离线入口：根`run.cmd --check-browser-accounts`。本项只验证替身与会话边界，真实Google/Twitch登录、官网验证与订阅完整性仍需用户手动验收，不代表播放性能改善。

## 录制服务 v1（配套开发接口）

插件可覆盖 `Plugin.recording_settings(parent)`，返回一个由父级拥有的 Qt 控件，或返回 `None`。
本体在首次打开“设置 → 录制”时调用，按插件名放在本体参数下方的独立区域；可选 `Plugin.recording_settings_title` 指定区域标题。页面公开 `add_recording_mode(widget)`，用于在页首放置插件拥有的格子录制方式选择。独立设置进程也嵌入本体的同一页面，不在工作进程加载插件或账号。
插件控件通过自己的公开服务与持久化接口保存配置，不向本体 `settings()` 塞入私有字段；卸载时插件停止回调并禁用仍存活的控件，Qt 对象由页面销毁。
旧宿主忽略此可选钩子，插件仍可保留工作区入口。相关离线检查：`python dev/selfcheck_recording_plugin_settings.py`。

`context.recording` 在 GUI 线程提供 `api_version == 1` 的录制桥接；旧版本没有该属性。
默认沿用本体录制；功能插件可注册录制会话实现，播放后端不变。`options()` 返回录制目录、FFmpeg 路径及尚在导出的文件；
`sources()` 返回来源 ID、房间、会话 ID、状态和开始时间，不返回流 URL 或凭据。

`control(source_id, action, session_id=...)` 支持 `record`、`stop`、`buffer`、
`stop_buffer`、`save_replay`，沿用本体画质/设置流程。传入 `session_id` 时会核对当前会话，变化后拒绝旧操作；省略时不做会话代次校验。
主播监控的后台来源可通过 `sources()` 的 `recording_mode` 获取会话启动时的选项（`normal`、`clip`、`None` 表示沿用全局）。录制启停由主播监控管理。
`open_settings()` 打开本体录制设置。

`register_backend(RecordingSessionSubclass, enabled=True)` 将本体后续新建的录制/缓存会话交给插件，
沿用原按钮、画质控制、重连、磁盘空间和退出管理；同一时间仅允许一个插件拥有注册。
基类为 `ddm.recording.RecordingSession`，扩展 `parts_directory`、`segment_options`、
`update_review`、`save_recording` 和 `review_info`。`segment_seconds` 同时用于分段与缓存范围计算。
`export_input(parts, playlist)` 为本体快速保存提供稳定的 FFmpeg 输入参数，默认仍为 concat；
HLS 会话可生成含初始化段/断点的冻结 VOD 输入。`snapshot_info(parts)` 可补充 `index_format`
及 `segments`（含 `init` 路径）；宿主同时为媒体与初始化段建立租约，调用者不可将 fMP4 片段当独立 MP4。
`save_recording(parts)` 返回已有的持久录播入口时不重复合并或删除其原分段；返回 None 使用原导出。
`live_recording(source_id, session_id)` 返回插件已发布的可读索引及媒体范围，拒绝过期会话。
卸载恢复默认会话工厂，已开始的会话仍使用原实现正常收尾；会话不得依赖插件界面或有效 context。
`set_backend_enabled(bool)` 在已注册实现与本体原版之间互斥切换，有活动录制/缓存时拒绝切换；`enabled=False` 可在装载时直接保留本体录制。会话类的 `supports_replay=False` 禁止纯缓存、手动/自动即时重放；会话的 `recording_message(event, path)` 为开始、续录、持久保存提供对应通知。普通原版录制在插件拥有后端注册时保留房间信息与封面/头像旁路文件，供录像库检索，不改动未装载插件时的文件命名和输出。
此项是 v1 的新增能力，插件应检查方法是否存在；已发布版本号不保证包含该开发接口。

`select_backend(session_factory=None)` 在注册所有权内选择本体或插件会话类，有活动录制/缓存时拒绝更换；不传会话类表示本体。它允许插件提供同时输出本体文件和切片归档的会话类，不必另开一套取流或操作宿主私有状态。
可选的 `register_background_clip_backend(RecordingSessionSubclass)` 由已注册后端的插件调用，用于主播监控中明确选择切片的后续会话。既有会话继续使用原实现。插件应检查宿主是否提供此方法。
`record_danmaku(room_id, message)` 在GUI线程向匹配房间、实现了该可选方法的录制会话转交弹幕副本。
录制会话可设置 `wants_danmaku = True`。本体为录制中的房间保持共享弹幕订阅，和画面及面板共用连接。仅缓存、停止录制和明确不支持直播弹幕的来源不产生订阅需求。
会话的 `recording_started()` 在纯缓存升级为录制时返回是否需重新建立输出分段，重启由本体管理；`recording_directories()` 返回需要核验剩余空间的目录，默认仅本体保存位置。
会话类可选字符串 `recording_directory` 提供实际录制目录；未提供时沿用本体目录，原画锁定入口也使用同一目录判断。
`review_parts()` 默认返回缓存及已封口分段，双输出会话可只返回切片分段用于插件快照；本体即时回放仍使用本体分段。
`additional_recordings()` 在完整保存后返回附加成品路径及错误文本，由本体通知；附加输出收尾先于本体分段为空的判断，避免一侧缺失阻断另一侧。

`snapshot(source_id, session_id)` 返回已封口分段列表、房间、会话及快照时间和 `lease`。
分段租约同时防止缓存裁剪与录制合并后的删除；调用者只能读取，不能修改原分段。
插件应在后台生成稳定本地副本，GUI 线程调用 `release(lease)`，不可长时间占用缓存。
活动尾段不在快照中；断流后媒体时间与墙钟时间不是无缝映射。

停用或关闭后拒绝新操作，`release`/`close` 仍可释放已有租约；装载失败与卸载会兜底释放。
插件自己的进程、线程与预览由插件 `on_unload` 收尾。当前本体先收尾录制、再发关闭事件及卸载插件，
因此插件不得依赖 `app.closing` 提前于本体录制收尾。

美化插件通过清单的 `skin` 字段或 `Plugin.skin` 提供素材。新版 `skin.version: 2` 支持分区底色、背景、按钮和图标，个人修改优先于美化包；旧版背景插件保持原有接管行为。包仍使用普通插件的安装、启停及卸载流程。格式与逐项测试步骤见 [皮肤与美化包](features/skins.md)。

不想塞进本体的功能放这里：录像、接抖音/YouTube/Twitch、发弹幕、给格子加菜单项。
插件是**普通 Python 代码**，和本体同进程运行，能力等价于本体代码 —— 只装自己看过源码的插件。

> 本页记录**已经实现**的插件接口。

## 目录约定

### 源码、模板与安装副本的边界

下文的运行时 `plugins_user/` 相对于当前数据目录。安装版默认位于当前用户的 AppData，便携版和源码版默认位于程序旁；在设置→软件更新→数据与存储迁移数据后，插件安装、更新及保存在当前数据目录的私有文件跟随新目录。插件自行写到固定程序路径的额外文件不会因此改变保存位置，具体以插件说明和实现为准。仓库中的源码及模板位置保持不变。

通过软件安装 ZIP 时，每个插件自动生成 `.ddm-plugin-files.txt`，仅记录安装包中的文件；更新时保留旧记录并合并新版记录。主软件卸载时，勾选清除个人信息会按此记录删除插件文件，保留插件运行后生成或用户另行放入的未登记文件。尚无记录的旧插件仅清理入口和描述文件。

`plugins_user` 同时容纳开发资料和运行时安装目录，不能整目录提交、删除或复制进发布包。

| 路径 | 角色与维护位置 | Git 与发布边界 |
| --- | --- | --- |
| `plugins_user/_template_platform/` | 本仓库维护的平台插件开发模板 | 提交模板；不自动装载。开发新插件时复制到独立源码目录，修改 ID 和清单后再打包安装 |
| `plugins_user/match_sync/` | 比赛二路的本机安装副本 | Git 忽略；现行源码在[独立插件仓库](https://github.com/Lanpropro/DD_Monitor_Plugins/tree/match-sync-v1.7.0/plugins/match_sync)，在该仓库验证、打包和发布 |
| `plugins_user/domestic_live/`、`global_live/`、旧 `huya_watch/` | 独立仓库 DD_Monitor_Plugins 的本机安装副本 | Git 忽略；源码在独立仓库提交，ZIP 单独发布 |
| `plugins_user/.updates/`、`_danmaku_log/` | 更新暂存或旧插件保留的数据 | 本机资料，Git 忽略；不作为源码或模板 |
| 其他 `<插件ID>/` | 用户主动安装的运行时代码 | 不随本体源码提交；新增本机插件目录时核对忽略规则，避免误加入 Git |

本体源码仓库只保留上述已跟踪的开发模板；分离前的比赛二路 v1.3 源码可从本体 Git 历史追溯，现行开发以独立插件仓库为准。`dev/build_release.ps1` 生成的便携包排除整个 `plugins_user/*` 并创建空安装目录，EXE 包同样从空安装目录开始。插件 ZIP 由各自发布流程提供，不把开发模板或本机安装副本作为本体内置插件。

提交前使用 `git ls-files plugins_user` 检查已跟踪文件；用 `git check-ignore --no-index <安装副本路径>` 检查本机目录是否被忽略。`.gitignore` 只防止普通添加，不会自动备份已忽略的安装副本，也不能替代源码仓库提交。涉及插件修改时先确认所属源码位置，再按[贡献指南](../CONTRIBUTING.md)验证和提交。

### 运行时安装结构

旧内置插件 ID `danmaku_log` 已停用，其弹幕记录功能由本体提供。覆盖升级保留旧目录和数据，但不再加载该插件或显示其卡片。

```
plugins_user/
  <插件ID>/
    plugin.json      # 名称、说明和版本；设置页不执行代码即可显示
    plugin.py        # 必须存在，里面要有一个叫 plugin 的 Plugin 实例
```

- 新插件以 ZIP 导入，内部只能有一个顶层目录，目录名是插件 ID：小写英文字母开头，后续可含小写字母、数字和下划线。插件页支持将一个或多个插件包直接拖入；也接受内部包含相同 ZIP 结构的自解压 EXE，只读取归档内容，不运行 EXE。普通 EXE 安装程序不符合插件格式，不能导入。
- ZIP 中必须有 `<插件ID>/plugin.json` 和 `<插件ID>/plugin.py`，其他资源文件可放在同一目录下。`plugin.json` 格式如下：

```json
{"id": "my_plugin", "name": "我的插件", "description": "一句话说明", "version": "1.0"}
```

- `id` 必须与目录名一致；`name`、`description`、`version` 必须是非空字符串。设置页优先从清单读取卡片信息，启动时才导入 `plugin.py`、查找 `plugin` 实例并调用 `on_load`。
- 可选的 `min_app_version` 声明最低本体版本。插件商店及在线更新按它检查兼容性，缺省按 `0.3` 处理；手动导入 ZIP 和启动装载不执行这一版本门槛检查。使用新增接口的插件仍应在 `on_load` 检查必要方法，给出兼容要求或降级路径，不能只依赖版本号。
- 旧插件没有 `plugin.json` 仍可从磁盘加载；新 ZIP 包必须有清单。装载不会覆盖同 ID 的已有插件，也不会当场执行代码，重启后生效。
- 以 `_` 或 `.` 开头的目录会被**跳过**（给模板和插件自己的数据用）。
- 装载失败的插件只会被跳过并在 stderr 打印原因，不会影响程序启动。

可在「设置 → 插件」点击「装载插件…」选择 ZIP，查看插件卡片、当前加载状态，并切换启用状态或删除插件。安装和删除文件是即时操作；已加载插件在本次进程中仍运行，重启后才会停止。关闭设置窗口不会撤销文件操作。启用选择自动保存，在下次启动时生效。
手动导入只新增尚不存在的插件 ID；同 ID 的在线升级由商店暂存后重启应用，见[在线更新](online-updates.md#发布插件)。插件页的「删除」会删除整个插件目录、该插件的待应用更新和插件配置段，包括目录内未登记的自建数据；需要保留的内容应先备份。这与主软件卸载时按文件清单清理的范围不同。
插件安装、删除或启用选择改变后，插件页标题旁会显示「重启以应用」；点击前会等待尚未完成的设置保存，再正常收尾录制、插件与播放器并重新启动。仅更改启用选择并改回原样时，该按钮隐藏；文件已变更时仍需重启。源码运行和打包 EXE 均沿用当前程序入口。通用热重载暂不支持：现有插件可持有界面信号、线程和本机资源，接口尚不能保证彻底卸载。
也可直接在当前数据目录 `utils/config.json` 的 `plugins_enabled` 写入插件目录名数组，
不写或写 `null` 表示全部启用。

国内和海外直播扩展的源码及安装包在独立仓库
[DD_Monitor_Plugins](https://github.com/Lanpropro/DD_Monitor_Plugins) 维护。
从该仓库 Releases 下载单个插件 ZIP 后导入；软件仓库及新发布包不内置这两个扩展。
国内插件 ID 为 `domestic_live`，海外插件 ID 为 `global_live`。

### 平台关注导入

平台可选提供 `follow_login_url`（官方登录/关注页面）、`follow_cookie_domain`
（登录 Cookie 的站点域）和 `follow_rooms(session, cancelled)`。
本体的「导入关注」会展示已启用且支持此功能的平台；未提供能力的插件仍按原方式添加房间。
`follow_rooms` 在后台线程运行，返回普通房间字典列表，必须设置请求超时、检查每页
`cancelled()`、保留未开播主播，并在登录失效或数据不完整时抛出异常。
本体负责用户勾选、去重、保存关注和图片显示，不自动把导入结果加入播放格子。
抖音可选实现 `follow_accounts(session, cancelled)`，返回所有关注账号，包含
`anchor_uid`、`sec_uid` 和显示资料；无法确认房间时 `room_id` 为空，不猜测 UID 是房间号。
`resolve_follow_account(account, cancelled)` 仅用公开直播记录补齐房间资料，在列表出现后
由宿主的后台线程执行。单次补充最多运行约 30 秒（当前有超时的请求收尾后停止），
可手动停止或重试；打开缓存不自动请求。待识别的勾选账号单独保存在当前账号的加密缓存，
不会写入侧栏房间或播放器；下次识别成功后保留勾选，用户点击导入后才加入侧栏。
插件通过自身设置持久化固定房间与主播 UID 的对应关系，空响应不会删除已有映射。
登录浏览器按平台隔离并仅在主动导入时加载；Windows 登录 Cookie 用 DPAPI 加密保存于
`utils/accounts/<platform>.bin`，不会进入普通插件设置，也不传给取流及弹幕接口。
关闭导入窗口或软件会取消分页并等待当前有超时的请求收尾。
当前独立插件源码中，虎牙、斗鱼、抖音、Twitch 和 YouTube 均提供关注读取入口；实际可用范围取决于安装的插件版本及平台登录状态。抖音未识别房间按上述补充流程处理。

支持登录的平台另提供 `account_info(session, cancelled)`，返回 `uid/uname/face`。
可提供 `account_login_url` 指向独立官方登录页，登录与关注导入均使用此页面；
未提供时沿用 `follow_login_url`，关注接口的 Referer 仍由插件指定。
原 B 站账号按钮现为统一登录入口：未登录可选择平台，已登录菜单可继续登录其他平台。
账号栏优先展示 B 站，否则展示已登录且插件启用的其他平台，显示昵称、ID 和平台图标。
第三方账号信息与 Cookie 一起加密保存；启动恢复显示信息时不加载网页登录浏览器。
「退出登录」仅退出当前展示的账号，其余账号继续保留；关注导入仍需用户主动勾选。

安装 `domestic_live` 后，旧 `huya_watch` 的启用选择和插件设置自动迁移；
新旧目录共存时只加载并展示新插件，原有房间 ID、关注和格子暂存数据继续沿用。

## 最小插件

```python
from ddm import plugins as api


class MyPlugin(api.Plugin):
    def on_load(self, context: api.PluginContext) -> None:
        context.log("装载完成")

    def on_event(self, event: str, payload: dict) -> None:
        if event == api.EVENT_DANMAKU:
            print(payload["message"]["text"])


plugin = MyPlugin()
```

清单负责展示元数据；`plugin.py` 只需导出一个 `Plugin` 子类实例。

## 一、事件（只读地观察）

本体在关键时刻把状态播出去，插件只读，不要改 `payload` 里的对象。

| 事件 | payload | 用途 |
| --- | --- | --- |
| `app.started` | — | 界面已就绪 |
| `app.closing` | — | 本体录制已收尾，即将卸载插件 |
| `stream.resolved` | `source`（`StreamSource`）、`tile` | **录像**用的就是它 |
| `stream.failed` | `tile`、`reason`（在 `_on_resolve_failed` 里） | 取流失败 |
| `tile.playing` | `tile`、`room` | 这一路真的播起来了 |
| `tile.stopped` | `tile`、`room` | 格子播放已停止或正在换流，不等于房间下播 |
| `room.live` / `room.offline` | `tile`、`room` | 开播 / 下播 |
| `danmaku.message` | `room_id`、`message` | 弹幕、礼物、上舰、SC |
| `danmaku.status` | `room_id`、`status` | 弹幕连接状态文字 |
| `tile.added` / `tile.removed` | `tile`、`room` | 房间加入或移出画面墙，可能复用已有空格子 |
| `account.changed` | `platform`、`generation` | 账号身份变化，凭据另读快照 |
| `account.credentials_updated` | `platform`、`generation`、`fields` | 同一账号凭据字段变化，不含字段值 |
| `settings.changed` | — | 保留的事件名，当前宿主没有派发入口 |

普通弹幕事件可提供字符串 `uid`（兼容 `user_id` / `author_id`）及 `uname`。本体在进入展示与 `danmaku.message` 订阅前按全局词条及平台用户规则过滤，并补充来源 `platform`、`room_id`；已屏蔽消息不向插件派发。平台由宿主房间标识确定，用户ID只在所属平台内比较，支持非数字ID；无ID时快捷屏蔽明确使用昵称。独立国内、海外插件的协议适配保留可用发送者ID，无需发送控件或账号登录即可屏蔽。

`StreamSource` 就是这一路的取流结果：

```python
StreamSource(room_id, url, quality, channel, headers, platform, uname, title)
```

`headers` 是拉这个地址**必须**带的请求头。B 站 app 通道的地址不能带 Referer、
web 通道必须带，弄反了 CDN 直接 403 —— 所以别自己猜，直接用这里给的。

录像的写法（复用已解析的地址与请求头，不用访问播放器对象）：

```python
import subprocess


def on_event(self, event, payload):
    if event != api.EVENT_STREAM_RESOLVED:
        return
    source = payload["source"]
    args = ["ffmpeg"]
    if source.headers:
        args += ["-headers", "".join(f"{name}: {value}\r\n"
                                    for name, value in source.headers.items())]
    filename = source.room_id.replace(":", "_") + ".flv"
    args += ["-i", source.url, "-c", "copy", filename]
    subprocess.Popen(args)
```

此例只展示取流参数；插件须保存子进程句柄，在停止或 `on_unload` 中收尾，并自行处理失败和重连。需要本体统一管理录制、缓存和退出时，使用前面的录制服务。

## 二、平台（让本体认识 B 站以外的站）

实现 `matches` / `room_info` / `play_url` 三个钩子并注册：

```python
class MyPlatform(api.Platform):
    kind = "douyin"
    label = "抖音"
    room_input_hint = "抖音直播间链接"  # 可选：添加窗口按装载平台显示

    def matches(self, room_id): ...      # 判断房间号是不是本平台
    def room_info(self, room_id): ...     # -> api.RoomInfo 或 None
    def play_url(self, room_id, quality=250): ...  # -> (url, 画质, 通道[, 请求头])
    def room_url(self, room_id): ...  # 可选：直播间 http(s) 网页地址；空串则不显示浏览器入口


class MyPlugin(api.Plugin):
    def on_load(self, context):
        context.register_platform(MyPlatform())
```

房间号写成 `<kind>:<房间号或链接>`（例如 `douyin:123456`），用来和 B 站的纯数字房间号区分。
完整骨架见 `plugins_user/_template_platform/plugin.py`。

### 格子播放与关注卡片

频道来源、列表解析、预设数据和图片资源由插件提供。宿主复用原生添加面板、列表筛选、关注文件夹和播放器。需要下面的频道列表接口时，可在加载前检查 `hasattr(api, 'RoomList')`。初版 v0.8 的 `Platform` 已能提供单个房间，但没有这个接口。

平台可以实现 `room_input_presets() -> list[RoomInfo]`。宿主在打开添加直播间面板时读取预设，此方法在界面线程运行，直接返回本地频道元数据。预设卡片使用稳定房间 ID，平台的 `matches`、`room_info` 和 `play_url` 应支持这些 ID。用户点选后，宿主按当前文件夹导入关注卡片；从空格打开时也只添加到关注。

提供多频道来源的平台可以实现可选的 `room_list(room_id, cancelled) -> api.RoomList`。宿主使用 `matches` 和 `normalize` 选择平台并标准化输入，在添加直播间的后台线程调用 `room_list`。插件应在解析和网络读取之间检查 `cancelled()`。宿主将 `RoomList.rooms` 中的 `RoomInfo` 显示在频道选择窗口，使用条目的 `extra['import_group']` 分组。用户确认后，`RoomList.store` 可在主线程接收已选房间 ID 并保存播放所需的数据。用 `choose=False` 返回唯一房间可沿用普通添加和上墙流程。文件导入的平台可通过 `room_input_file_filter` 声明 Qt 文件过滤器，例如 `播放列表 (*.example)`。文件选择和粘贴链接使用相同的归一化和解析流程。

已关注的频道由 `rooms_status(room_ids)` 和其他平台一起刷新。可以用 `extra['live_known'] = False` 表示尚未确认开播状态。平台设定 `live_from_playback` 后，宿主也会用原生播放器实际出画确认开播。需要从本地恢复旧卡片资料时，可实现 `restore_follow_rooms(rooms)`，在界面线程就地补齐名称和标题。

平台可以实现 `room_card_branding(room_id) -> dict`。宿主在创建和恢复关注卡片时于界面线程调用，只读取本地元数据。可用键为 `avatar_path`（包内头像图的绝对路径）、`badge_path`（包内平台角标图的绝对路径）、`badge_from_avatar`（复用 `RoomInfo.face` 加载的头像）和 `label`（角标提示与无障碍名称）。没有专属标识时返回空字典。此接口只影响关注卡片的图像，平台归属和播放仍使用原来的 `kind`。

将 `capture_first_playback_cover` 设为 `True` 可为缺少本地封面的关注卡片生成封面。宿主在画面墙进入正常视频播放时从当前播放器异步获取首张可用画面，保存到原有封面缓存。

添加时使用平台的 `normalize` 标准化输入，后台 `room_info` 构建关注卡片。
卡片拖入画面墙或右键“加入画面墙”后，后台 `play_url` 的结果交给 libmpv
格子播放；请求头随流地址传给播放器。可选 `room_quality_options` 返回
`[{"qn": 10000, "desc": "原画"}]`，未实现时沿用原有菜单。
画质由播放源决定时，返回单项 `[{"qn": 0, "desc": "源自适应"}]`。宿主在取到原生播放器报告的实际分辨率前显示这条说明，出画后显示宽高数值。两者均为只读。

需要按来源编码选流的平台可实现可选方法
`play_url_for_codec(room_id, quality=250, *, codec="avc")`，返回
`(url, actual_quality, platform_profile, headers, actual_codec)`。
非 B 站只会收到 `hevc` 或 `avc`，不会收到 `av1`；全局/单窗 AV1 偏好
在本体取流阶段转换为 HEVC → H.264，H.264 偏好只请求 H.264。
实现必须依据接口编码字段或 HLS CODECS 验证来源，不能仅修改 URL 或容器来宣称编码。
没有目标格式时抛 `api.StreamCodecUnavailable`；网络与登录异常保留原含义。
登录明确失效时停止编码轮换；HEVC 取流失败可尝试 H.264，全部失败仍回报取流错误。
平台通道名继续返回原 `kind`，请求头和画质属于实际选中的来源。
旧版 `play_url(room_id, quality)` 无需改签名；兼容路径不猜测实际编码，
播放后通过解码器读数展示格式。预览仍走 `preview_url`。

平台实现 `rooms_status` 供后台刷新，返回以带平台前缀的房间号为键的字典，
字段与 `RoomInfo.as_dict()` 一致。网络失败不能返回伪造的下播状态。
平台可通过 `RoomInfo.extra['display_room_id']` 及状态字典提供显示用房间号（字符串），
供关注栏与画中画选择器搜索；该字段随平台房间资料保存，不能替换播放与弹幕使用的 `room_id`。
抖音平台若能取得主播个人资料头图，可通过 `RoomInfo.extra['banner_url']` 或状态字典的
`banner_url` 提供图片地址；紧凑卡片和主播相关通知优先使用它，缺失或下载失败时裁切直播封面。
虎牙、斗鱼等传统直播平台始终使用封面；平台标识沿用现有 Logo。
平台请求必须有超时；本体分别处理平台与 B 站房间，不会把前缀房间号传给
B 站取流、在线人数或弹幕接口。宿主通过平台可选的 `preview_url` 和 `danmaku_client` 接入悬停预览与弹幕；具体能力由已安装插件提供。

点播等非直播媒体可在格子房间字典中声明
`room[api.ROOM_SUPPORTS_LIVE_DANMAKU] = False`（字段名 `supports_live_danmaku`）。
本体据此排除弹幕栏来源候选、自动选择、直接指定和拖放，并停止对应实时弹幕订阅。
未声明的既有直播房间继续可选，包括尚未开播的房间；不按 `live=False` 一概排除。
此能力仅限制实时直播弹幕来源，不控制插件按视频时间轴提供的历史弹幕。

卡片基本资料与格子位置随配置保存，启动时状态为待刷新，后台恢复播放。
禁用或删除插件后保留关注与位置，在格子提示启用插件。
国内直播平台安装在 `plugins_user/domestic_live`，支持虎牙、斗鱼和抖音；
海外直播平台安装在 `plugins_user/global_live`，支持 Twitch 和 YouTube。
使用与验收步骤见独立插件仓库中各插件的 README。

同一个 `kind` 注册两次会直接报错 —— 静默覆盖会让两家插件互相打架，不如当场炸出来。

## 三、发弹幕

弹幕接收与显示属于本体功能。以下旧式发送器接口继续兼容；独立的 `bili_live` 插件通过
本文后面的格子控件扩展和登录快照接口提供行内发送、表情及礼物界面：

```python
class MySender(api.DanmakuSender):
    def available(self):
        return True, ""                 # (能不能发, 不能发的原因)

    def send(self, room_id, text):
        return True, "已发送"            # (成功?, 给用户看的说明)


class MyPlugin(api.Plugin):
    def on_load(self, context):
        context.register_danmaku_sender(MySender())
```

## 四、格子右键菜单

```python
def tile_actions(self, tile):
    return [("开始录制", lambda: start(tile.room))]
```

返回 `(显示文字, 回调)` 的列表。回调在界面线程同步执行，普通 Python 异常由本体捕获并打印到 stderr。
本体的菜单项和插件的项之间会自动加分隔线。

## 五、插件自己的配置

```python
context.setting("show_badge", True)           # 读
context.set_setting("show_badge", False)     # 写，并通知本体落盘
```

存在当前数据目录 `utils/config.json` 的 `plugins.<目录名>` 段下，由本体的保存回调落盘。源码版或便携版默认在程序旁，安装版及迁移后的目录见前面的目录约定。

## 边界与保证

- **回调与线程**：生命周期、界面注册、配置读写、凭据和录制桥接在 GUI 线程使用；事件在派发线程同步执行，管理器不自动创建后台线程。平台的 `room_info`、`rooms_status`、取流及关注读取由宿主工作线程调用，`matches`、`normalize` 等同步查询应快速返回。耗时任务由插件自行管理；`notify`、`request_login` 是下文明确允许工作线程调用的接口。
- **普通异常隔离**：`on_load`、`on_event`、`tile_actions`、菜单回调中的普通 Python 异常由本体捕获。此机制不能隔离主线程阻塞、原生库崩溃或插件进程权限。
- **装载顺序**：清单声明 `replaces` 的插件先装载，两组内部各按目录名排序。同一个平台被两个插件注册会报错。
- **卸载**：实际退出时先收尾本体录制，再发 `app.closing`、调 `on_unload()`，然后存配置、释放播放器；隐藏到托盘不卸载插件。
  插件起的线程要在这里停掉，否则 Qt 退出时会崩。
- **插件不是沙箱**：它拿到的是真实窗口对象和进程权限。这是刻意的取舍 ——
  录像、抓别的平台这类事本来就需要完整的网络和文件访问。

## 格子内控件扩展

插件可调用 `context.register_tile_control("controls", factory, priority=100)`。
`factory(TileControlContext)` 返回 `ddm.plugins.TileControl`；其中 `parent` 是本体管理的
容器，`room` 是房间副本，`invalidate_layout()` 请求重新分配底栏空间。
`TileControl(widget, minimum_width=90, preferred_width=240)` 可覆盖
`set_room(room)`、`interaction_active()` 和 `shutdown()`。每个格子（包括初始空格子）
只构造一次；每次房间赋值均通知。插件自行隐藏不支持房间的 widget，本体独立隐藏宽度
不足的容器。优先级高的先分配，优先级相同时保持注册顺序。
不支持的房间无需重新注册，移除格子或卸载时 `shutdown()` 只调用一次。
注册在 `on_load` 成功之后生效；不要修改格子私有布局或包裹本体方法。

播放控件的圆角弹窗可通过 `getattr(ddm.ui, 'paint_playback_popup', None)` 探测材质绘制入口。
支持时，在透明弹窗的 `paintEvent` 中传入 `(popup, painter, rect, radius)` 绘制底板，并设置
`playbackGlassPopup` 属性为 `True`，让弹窗在宿主修改毛玻璃设置时重绘。弹窗应保留所属窗口的
Qt 父子关系。旧宿主使用插件自己的底板绘制。

## 格子字幕覆盖层

插件可在 GUI 线程调用以下接口，在当前播放格上显示宿主管理的独立字幕，不需要把文本写入弹幕列表或访问播放器内部状态：

```python
context.set_tile_caption(
    tile,
    original="原文",
    translated="译文",
    style={"mode": "both", "lines": 2, "opacity": 65,
           "width": 80, "height": 18, "font_size": 24},
    visible=True,
    on_style_changed=lambda tile, style: save_caption_preferences(tile, style),
)
context.clear_tile_caption(tile)
```

`mode` 支持 `both`、`original`、`translation`；`lines` 为 1–4；`opacity` 为 0–100；`width` 为视频宽度的 20%–100%；`height` 为可用高度的 8%–45%；`font_size` 为 10–64 px。字体过大时宿主按当前字幕框高度安全截断。黑色背景按每行实际文字宽度绘制，不覆盖整个字幕框。

样式另支持 `x`、`y`（0–100，分别表示字幕框在剩余横向／纵向可移动空间中的位置，默认 50／100）及 `locked`（默认 False）。未锁定时拖动文字区域移动、拖动右下角缩放，双击恢复位置与大小；右键可锁定、切换原文／译文、调整字号或复位。锁定后鼠标穿透，插件应在自己的面板或格子菜单提供解锁入口。位置随视频大小及播放栏安全区域归一化，不保存绝对屏幕坐标。

`on_style_changed` 是可选的 GUI 线程回调 `(tile, style_dict)`，只在用户完成手势或点击快捷操作时触发，正文不进入样式。插件自行保存偏好并在下一次写字幕时带回；宿主不复制插件设置。回调随所有者接管、清除或卸载断开，旧所有者不能收到新字幕编辑。旧宿主可能不接受此关键字，可省略它回退到静态覆盖层。

`context.create_caption_preview(parent)` 返回使用同一渲染器和手势的嵌入式设置预览，提供 `set_style(dict)` 和 `styleChanged(dict)`；预览始终可操作，保留传入的真实锁定偏好，不创建 native 浮窗。`context.room_presentation(tile)` 返回房间 ID、名称及与画中画选择器相同的缓存头像 `pixmap`，无网络或截图操作；插件可用它构建房间多选界面。

职责边界：`video_caption.py` 拥有当前字幕与样式、绘制和 native 层级；`caption_geometry.py` 计算归一化安全位置；`caption_interaction.py` 处理编辑手势与快捷菜单；`caption_toolbar.py` 提供字幕上方的图标快捷栏，不占用字幕文字区域，不保存第二份样式；`caption_preview.py` 复用真实渲染组件并桥接预览参数；`plugin_types.py` 维护回调所有权与公开预览／房间展示入口。预览与实际字幕通过映射交换值，不共享可变控件状态。

未锁定字幕悬停时显示图标栏，提供显示内容、字号、位置复位和锁定；鼠标离开字幕及工具栏后收起。工具栏跟随字幕并限制在视频安全区域，清除、隐藏和销毁字幕时一并回收。锁定后仍从格子右键或设置页解锁。

字幕覆盖层不进入弹幕队列，显示状态与 `video_danmaku.set_enabled()` 独立；关闭弹幕不关闭字幕，清除字幕后再开启弹幕也不会恢复字幕。视频源本身包含的字幕仍由视频播放，与插件字幕开关无关。

本体冻结构建显式保留 `tarfile` 和 `bz2`，供独立插件在用户确认后准备 `.tar.bz2` 模型；只提供标准库能力，模型选择、下载、校验及同意流程仍由插件自身负责，导入 ZIP 不执行插件安装逻辑。

字幕使用宿主的独立覆盖层，位于视频、弹幕和醒目留言之上；全屏显示，画中画隐藏。播放栏显示或收起时，字幕安全区域随可用画面高度调整。字幕不会进入 `VideoDanmaku` 的弹幕轨道，真实弹幕仍可经过字幕区域；清除字幕不会停止插件任务。

`set_tile_caption()` 返回 `False` 表示当前宿主不支持覆盖层，插件应回退到自己的独立字幕窗。字幕正文不写入宿主日志或插件设置。

字幕所有者由 PluginManager 维护，公开接口位于 `plugin_types.py`。失活上下文不能再写入字幕，但可以清除仍属于自己的字幕；不会清除后续由其他上下文接管的内容。装载失败、卸载、格子换房和关闭均清理相应字幕。

## 登录快照与交互状态

`context.credentials(platform)` 返回 `CredentialSnapshot(platform, generation, values)`，
未注册的平台返回 `None`。`values` 为独立只读映射，快照 repr 不输出密钥。
`account.changed` 事件只包含 `platform`、`generation`；读取新快照获取当前凭据。
本体目前为 `bilibili` 提供 `SESSDATA`、`bili_jct`、`buvid3`，继续使用本体登录入口。
工作线程使用事先捕获的副本，不得在线程中访问这些 GUI 接口。

发现设备标识后，可在 GUI 线程调用
`context.update_credentials("bilibili", {"buvid3": value}, expected_generation=generation)`。
旧账号代次返回 `False`；未知字段或不支持的更新抛出 `ValueError`。
本体仅在设备 Cookie 为空时接收并持久化，保留后来登录取得的设备身份。
此更新不推进账号代次；`account.credentials_updated` 仅包含平台、代次与字段名列表。
禁止把凭据写入插件设置或日志。

控件的 `interaction_active()` 可为编辑焦点、输入法组合、打开的弹窗返回 `True`，
本体据此保持全屏控件可见（包括指针离开格子时），并暂缓播放器快捷键，
即使指针位于其他格子。隐藏或禁用的控件不参与查询。

## 通知与登录入口

`context.notify(message, *, rooms=(), kind="info", on_click=None) -> bool`
将通知排入 GUI 线程，沿用主窗口上方的通知栏。`kind` 支持 `info`、`warning`、`live`；
`rooms` 是房间字典序列，调用时复制，用于展示头像。需要让用户识别失败房间时，
插件应同时把捕获的房间名和房间号写入 `message`，不依赖后来已切换的格子状态。
`on_click` 是可选无参函数，点击会先关闭通知再执行它；异常由本体隔离。

`context.request_login(platform, *, reauthenticate=False) -> bool`
通过本体已有的登录界面登录指定平台，`reauthenticate=True` 直接进入重新验证流程。
调用总是排入 GUI 队列，因此可安全地在通知点击动作中调用，不会让模态登录窗口
嵌入通知的鼠标回调。网络错误、余额不足或权限不足不应自动要求重新登录；
仅当接口明确拒绝凭据或账号尚未登录时提供该动作。

```python
context.notify("【示例主播（房间 120）】发送失败：登录失效，点击重新登录",
               rooms=({"room_id": "120", "uname": "示例主播"},), kind="warning",
               on_click=lambda: context.request_login("bilibili", reauthenticate=True))
```

这两个接口允许工作线程调用，返回 `True` 表示已接受排队，不保证窗口稍后仍可显示。
没有窗口或相应能力时返回 `False`；插件装载失败、管理器卸载、主窗口关闭或 Qt 对象
销毁后，待处理调用和保留的点击动作均失效。插件仍须自行检查请求的账号、房间和
控件生命周期，过滤已经过期的后台结果；无需访问本体私有通知字段或登录字段。

## bili_live 配套安装

上述接口由本体提供；配套插件源码在
[DD_Monitor_Plugins 的 `plugins/bili_live/` 发布源码](https://github.com/Lanpropro/DD_Monitor_Plugins/tree/bili-live-v1.1/plugins/bili_live)。
从软件插件商店或该仓库的[正式 Releases](https://github.com/Lanpropro/DD_Monitor_Plugins/releases) 安装与本体兼容的 `bili_live` 包，在插件页按提示重启。
继续在本体账号界面登录 B 站，各数字房间格子自动显示输入、表情、礼物和发送控件。
禁用/移除插件同样在重启后生效；登录持久化、播放和接收弹幕仍由本体负责。
插件在装载前检查必要公开接口，旧版本本体会报告兼容性要求。

具体安装包版本以正式 Release 和包内 `plugin.json` 为准。

### 控件居中与宽度预算

格子把全部可用控件放进一个居中的扩展区域，按优先级、注册顺序分配宽度。
使用弹幕布局时，弹幕栏对应房间的扩展区域移到弹幕栏下方，使用该栏的可用宽度；其他格子保留各自底栏控件。切回普通布局或进入单格全屏时恢复原位置。移动复用同一控件，不重新创建输入框或清除草稿；不支持当前房间时隐藏发送区域。
该区域最多为 `min(520, max(300, int(tile_width * 0.45)))` 逻辑像素；
空间不足时收窄并限制在现有播放器按钮之间，低优先级控件的最小宽度放不下时隐藏。
200 像素等窄格优先保留音量、录制及全屏入口；插件不能依赖其控件始终可见。
`preferred_width` 是多控件分配时的偏好，单个控件可以扩展到区域上限。
控件自行改变可用性、可见性或宽度声明后，调用 `invalidate_layout()`。
本体不保存发送草稿、不获取互动表情或发送礼物；这些能力由插件实现。

格子控件可实现 `TileControl.focus_input()`，聚焦自己的输入并返回 `True`；默认返回 `False`。本体弹幕输入快捷键按优先级向可见且启用的控件请求聚焦，不访问平台专用输入框。`interaction_active()` 应覆盖输入焦点与浮窗交互，以保护全屏控制条。

画面弹幕与弹幕栏均通过左键单击打开透明底的横向“复制 / +1”悬浮功能栏。画面弹幕悬停时仅暂停该条，不再自动弹出；弹幕栏消息悬停时显示圆角高亮，功能栏打开期间保留高亮。“+1”复用实现了 `focus_input()` 的发送控件：在该控件内找到唯一的、同一窗口下可编辑的 `QLineEdit`，填写原文并派发 Enter，继续使用插件既有的登录、发送中状态和协议检查。不会直接请求平台发送接口，也不会把礼物或其他弹窗中的输入框当作发送入口。布局空间不足而隐藏的发送区仍可复用；插件隐藏或禁用自身控件时不可用。功能栏保存打开时的房间号，切房后不发送；超过输入框长度限制时不截断发送。

独立表情消息（`dm_type=1`）保留 `emoticon_unique`，通过可选的 `TileControl.repeat_message(event)` 发送。控件应复用自己的表情发送流程及登录、忙碌检查，并返回是否已受理；默认返回 `False`。本体在调用前检查房间是否仍相同及控件是否可用。缺少表情编号或插件未实现该接口时禁用表情“+1”，不退回发送描述文本；复制仍使用原文本，混合文字的行内表情继续走普通文字发送。

## 独立工作区入口（配套开发接口）

`context.register_workspace_control(control_id, tool_button, priority=0)` 将插件的 `QToolButton` 注册到可搜索的功能中心，返回是否有可用侧栏。无界面宿主返回 False，插件可保留旧入口；没有插件时仍可从功能中心进入插件商店。

按钮的 QAction、选中状态和点击行为继续由插件负责。宿主管理按钮顺序、图标主题以及展开/收起/竖屏的位置；竖屏入口跟随顶部横栏，不改动原账号/布局/设置区域。注册期间宿主接管按钮的父控件与图标呈现，使用透明底的图标；不可自行挪动已注册按钮。

使用稳定的插件内 ID，以 priority 升序排列。同一 owner/ID 重复注册会拒绝；停用后拒绝新注册。`unregister_workspace_control(control_id)` 在插件收尾时注销并延迟释放按钮，卸载或装载失败也会按插件归属兜底清理。

插件可在已注册按钮上设置布尔属性 `workspaceRunning` 并调用 `update()`，表示功能实际运行中。宿主在侧栏图标统一着色及按压/悬停变换之后，在按钮右上角单独绘制 7px 绿色圆点；该状态独立于菜单展开、选中和焦点，停止时设置 False。插件仍持有实际业务状态，宿主只绘制指示，不触发后台任务。侧栏图标按按钮屏幕的设备像素比请求，避免高 DPI 下先生成小图再放大。

插件可在注册前将按钮的 `dockMotion` 设为 `slide-in-left`，鼠标移入时在图标背后绘制向右掠过的短线，图标保持原位。键盘操作和关闭系统动画时不播放线条动效。


横屏时全局按钮使用独立的 48px 功能轨，关注卡片区域保留原宽度。首次按优先级固定前两个插件，用户可按需取消或固定任意数量的已注册功能；固定区超出可用高度时可滚动查看，功能中心仍支持搜索和滚动。固定偏好保存在 `ui.workspace_pins`，取消全部固定也会保留。功能中心中的操作调用原按钮，不复制插件逻辑或停止后台任务。竖屏时使用顶部的功能中心入口，不展开整排插件按钮。

关注管理集中在标题的“＋”与“更多”菜单；布局、画中画、通知、外观、设置移入功能轨，账号入口仍在关注区底部。关注支持直播中筛选和卡片／列表切换；收起后保留原有头像窄栏及功能轨。

### 嵌入主界面的功能页

`context.show_workspace(widget, manages_content=False, pause_wall_playback=False)` 将 QWidget 嵌入主内容区并替换画面墙显示，返回是否成功。功能页必须使用普通 QWidget 而非独立窗口；返回/关闭页面恢复原内容的可见状态，后台任务由插件管理，不能因返回而取消。播放型功能页可设置 `pause_wall_playback=True`，在显示期间暂停画面墙观看，退出后恢复。录制继续进行，保留的播放器在功能页显示期间静音。

`context.create_workspace_player(video_widget)` 在 GUI 线程为功能页的 QWidget 创建本体原生播放器。插件在视频承载控件显示后使用 `play(url, profile, headers=None)` 开始播放，通过 `stateChanged` 接收 `connecting`、`buffering`、`playing`、`frozen` 和 `error` 等状态。`set_muted(bool)` 控制声音。页面关闭或插件卸载时调用 `release()` 释放播放资源，重新播放时可创建新的播放器。旧宿主需先检查此方法是否存在。

播放器的 `playback_timing()` 返回当前播放秒数和可定位的媒体时长。未知值返回 `None`。可定位时 `seek_to(seconds)` 请求跳到指定播放位置。

`context.create_plugin_widget(plugin_id, capability, parent, **options)` 在 GUI 线程调用已启用插件的 `create_embedded_widget(capability, parent, caller, **options)`。各提供方定义能力名称和选项。提供方缺失或不支持该能力时返回 `None`。提供的控件以调用方传入的容器为父对象，调用方在关闭页面时负责关闭并释放控件。

`context.workspace_background_mask()` 返回本体生效的背景蒙版强度（0 到 100）。关闭蒙版时返回 0。功能页可监听 `context.workspace_background_changed` 更新蒙版强度，无背景控制器时该信号为 `None`。可同时监听 `theme.signals().changed` 更新蒙版颜色。

使用本体 `Tile` 的功能页可以将 `roomDropOnly` 动态属性设为 `True`，保留关注卡片拖放并关闭空状态的添加按钮和右键菜单。

同一时刻只显示一个功能页；切换会关闭上一页，原有 QAction/关闭信号随之同步。需要自己管理内容显隐的旧功能页（如比赛二路）使用 manages_content=True，仅复用互斥与宿主布局；保留其原有播放/嵌入/收尾流程。页随主内容区调整大小，主窗口临时隐藏后仍保持当前页，插件卸载恢复画面墙。注册为可选中状态的功能入口互斥，防止旧的延迟切换覆盖最后选择。

左侧关注图标会正常关闭当前功能页并返回画面墙；若页面在 `closeEvent` 中拒绝关闭，则保留页面及其选中图标。只在关注栏中搜索或浏览不会退出功能页，导航选中状态跟随实际显示的内容。关闭页面不应取消插件的后台任务。

再次点击当前功能页对应的功能栏入口，或在功能中心再次选中该入口，会走同一关闭流程。其他插件按钮继续触发原有动作。

## 独立平台替代组合包（配套0.7.3开发接口）

清单可声明`platforms`提供的平台种类、`replaces`被替代的组合插件ID，以及`inherit_settings`允许继承的设置键；`replaces_platforms`声明旧公开组合包含的平台，用于兼容没有迁移接口的旧包。只有安装器生成文件清单的完整包会接管平台；源码入口模板不会触发迁移。

`context.platform_replaced(kind)`返回当前组合插件的平台是否已由安装的独立包接管，包含独立包被关闭的情况。旧组合入口应跳过这些平台，避免重复注册及关闭后反弹。一个组合包全部平台均有独立包时，宿主跳过组合装载并隐藏其目录项，但保留旧目录和设置。

首次迁移深复制声明的设置并继承旧启用状态，既有新设置优先；后续保存的独立禁用选择不会被旧组合重新启用。平台kind、房间ID及账号存储键保持不变。安装器先建立新设置项，保留安装后立即取消启用的选择。加载失败会清理本次注册的平台，避免留下无主数据。

迁移协调位于`plugin_replacements.py`，插件生命周期和状态仍由原所有者管理。专项`python dev/selfcheck_plugin_replacements.py`只使用临时插件与内存设置。回滚需移除独立包或恢复插件备份；仅关闭独立包会继续阻止组合包提供该平台。

旧公开组合包没有平台接管接口时，宿主等待其原有平台的完整替代组，或提示先更新兼容组合包；部分安装保留旧组，避免重复注册和丢失剩余平台。新增且不属于旧组的平台可以并存。

商店下载线程只验证和安装文件；设置继承、启用及保存由安装完成的主线程回调执行，避免后台任务改写界面所持状态。安装后立即关闭平台的选择同样保留到重启。

## 关注侧栏页面（开发接口）

`context.register_sidebar_page(page_id, widget, title=..., icon=...)` 在展开的左侧关注栏添加一个插件页面入口，返回是否注册成功；无窗口宿主返回 `False`。使用前检查接口是否存在，版本号不保证包含此开发接口。`unregister_sidebar_page(page_id)` 撤掉该入口。可选 `on_filter(text)` 接收共享搜索框的查询；本体保存并恢复关注与各插件页的搜索词，不修改关注标题或上方控件结构，只切换下方内容。

本体 `sidebar_pages` 持有所属插件、入口和当前页，负责关注/插件页切换、收起/横栏回退及插件卸载时的所有权清理；页面注册后成为 Sidebar 子控件，注销后隐藏并解除父对象，由插件负责停止请求、定时器和删除。页面内容和本地排序由插件唯一持有，不写入本体直播关注集合。该接口不替换中央工作区，也不改变画面墙拖放协议。


## 侧栏卡片拖影（开发接口）

`context.start_sidebar_drag(source, mime, pixmap, hotspot, global_pos, on_finished=callback)` 复用关注卡片的应用内拖动会话，先显示拖影再返回True；忙碌或无GUI时返回False。插件可在True返回后隐藏原位。该路径不进入Windows OLE；需要跨应用拖放的功能继续自行使用原生拖动。使用前检查方法是否存在。

源控件持有MIME直到回调；`on_finished`在放下或取消、释放输入捕获和会话状态后调用一次（源对象仍有效时）。`cancel_sidebar_drag()`只取消当前插件拥有的会话；页面注销、插件卸载或源控件隐藏会取消并释放鼠标/键盘。若source为QAbstractScrollArea，会话滚轮/位置采样使用该控件。平台视频协议与列表排序仍由插件处理。
