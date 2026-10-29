# 插件接口

美化插件通过清单的 `skin` 字段或 `Plugin.skin` 提供素材。新版 `skin.version: 2` 支持分区底色、背景、按钮和图标，个人修改优先于美化包；旧版背景插件保持原有接管行为。包仍使用普通插件的安装、启停及卸载流程。格式与逐项测试步骤见 [皮肤与美化包](skins.md)。

不想塞进本体的功能放这里：录像、接抖音/YouTube/Twitch、发弹幕、给格子加菜单项。
插件是**普通 Python 代码**，和本体同进程运行，能力等价于本体代码 —— 只装自己看过源码的插件。

> 本页只写**已经实现**的接口。哪些功能打算做、卡在哪、要动哪些文件，见
> [`idea.md`](local/idea.md)。

## 目录约定

### 源码、模板与安装副本的边界

下文的运行时 `plugins_user/` 相对于当前数据目录。安装版默认位于当前用户的 AppData，便携版和源码版默认位于程序旁；在设置→软件更新→数据与存储迁移数据后，插件安装、更新和私有文件跟随新目录。仓库中的源码及模板位置保持不变。

通过软件安装 ZIP 时，每个插件自动生成 `.ddm-plugin-files.txt`，仅记录安装包中的文件；更新时保留旧记录并合并新版记录。主软件卸载时，勾选清除个人信息会按此记录删除插件文件，保留插件运行后生成或用户另行放入的未登记文件。尚无记录的旧插件仅清理入口和描述文件。

`plugins_user` 同时容纳开发资料和运行时安装目录，不能整目录提交、删除或复制进发布包。

| 路径 | 角色与维护位置 | Git 与发布边界 |
| --- | --- | --- |
| `plugins_user/_match_sync/` | 比赛二路插件的已跟踪源码，在本仓库维护 | 提交源码；下划线前缀使其不自动装载。`python dev/build_match_sync.py` 单独生成 ZIP，ZIP 顶层为 `match_sync/` |
| `plugins_user/_template_platform/` | 本仓库维护的平台插件开发模板 | 提交模板；不自动装载。开发新插件时复制到独立源码目录，修改 ID 和清单后再打包安装 |
| `plugins_user/match_sync/` | 比赛二路的本机安装副本 | Git 忽略；不作为唯一源码。修改应先落实到 `_match_sync` 并测试、提交，再重新打包安装 |
| `plugins_user/domestic_live/`、`global_live/`、旧 `huya_watch/` | 独立仓库 DD_Monitor_Plugins 的本机安装副本 | Git 忽略；源码在独立仓库提交，ZIP 单独发布 |
| `plugins_user/.updates/`、`_danmaku_log/` | 更新暂存或旧插件保留的数据 | 本机资料，Git 忽略；不作为源码或模板 |
| 其他 `<插件ID>/` | 用户主动安装的运行时代码 | 不随本体源码提交；新增本机插件目录时核对忽略规则，避免误加入 Git |

本体源码仓库保留上述两类已跟踪开发目录；`dev/build_release.ps1` 生成的便携包排除整个 `plugins_user/*` 并创建空安装目录，EXE 包同样从空安装目录开始。插件 ZIP 由各自发布流程提供，不把开发模板或本机安装副本作为本体内置插件。

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
- 旧插件没有 `plugin.json` 仍可从磁盘加载；新 ZIP 包必须有清单。装载不会覆盖同 ID 的已有插件，也不会当场执行代码，重启后生效。
- 以 `_` 或 `.` 开头的目录会被**跳过**（给模板和插件自己的数据用）。
- 装载失败的插件只会被跳过并在 stderr 打印原因，不会影响程序启动。

可在「设置 → 插件」点击「装载插件…」选择 ZIP，查看插件卡片、当前加载状态，并切换启用状态或删除插件。安装和删除文件是即时操作；已加载插件在本次进程中仍运行，重启后才会停止。即使随后取消设置窗口，文件操作也不会撤销。开关更改在下次启动时生效。
插件安装、删除或启用选择改变后，设置窗口底部的「保存」会变为「保存并重启」，点击后保存当前设置及插件启用选择，正常收尾录制、插件与播放器后重新启动。启用选择改回原样且没有文件变更时，按钮恢复「保存」。源码运行和打包 EXE 均沿用当前程序入口。通用热重载暂不支持：现有插件可持有界面信号、线程和本机资源，接口尚不能保证彻底卸载。
也可直接在 `utils/config.json` 的 `plugins_enabled` 写入插件目录名数组，
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
国内插件目前试用斗鱼关注导入，需要新版宿主；其他平台尚未提供此能力。

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
| `app.closing` | — | 要退出了，收尾放这里 |
| `stream.resolved` | `source`（`StreamSource`）、`tile` | **录像**用的就是它 |
| `stream.failed` | `tile`、`reason`（在 `_on_resolve_failed` 里） | 取流失败 |
| `tile.playing` | `tile`、`room` | 这一路真的播起来了 |
| `room.live` / `room.offline` | `tile`、`room` | 开播 / 下播 |
| `danmaku.message` | `room_id`、`message` | 弹幕、礼物、上舰、SC |
| `danmaku.status` | `room_id`、`status` | 弹幕连接状态文字 |
| `tile.added` / `tile.removed` | `tile` | 格子增删 |

`StreamSource` 就是这一路的取流结果：

```python
StreamSource(room_id, url, quality, channel, headers, platform, uname, title)
```

`headers` 是拉这个地址**必须**带的请求头。B 站 app 通道的地址不能带 Referer、
web 通道必须带，弄反了 CDN 直接 403 —— 所以别自己猜，直接用这里给的。

录像的写法（不用二次取流、不用碰播放器）：

```python
def on_event(self, event, payload):
    if event != api.EVENT_STREAM_RESOLVED:
        return
    source = payload["source"]
    args = ["ffmpeg"]
    for name, value in source.headers.items():
        args += ["-headers", f"{name}: {value}\r\n"]
    args += ["-i", source.url, "-c", "copy", f"{source.room_id}.flv"]
    subprocess.Popen(args)
```

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

添加时使用平台的 `normalize` 标准化输入，后台 `room_info` 构建关注卡片。
卡片拖入画面墙或右键“加入画面墙”后，后台 `play_url` 的结果交给 libmpv
格子播放；请求头随流地址传给播放器。可选 `room_quality_options` 返回
`[{"qn": 10000, "desc": "原画"}]`，未实现时沿用原有菜单。

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
抖音平台若能取得主播个人资料头图，可通过 `RoomInfo.extra['banner_url']` 或状态字典的
`banner_url` 提供图片地址；紧凑卡片和主播相关通知优先使用它，缺失或下载失败时裁切直播封面。
虎牙、斗鱼等传统直播平台始终使用封面；平台标识沿用现有 Logo。
平台请求必须有超时；本体分别处理平台与 B 站房间，不会把前缀房间号传给
B 站取流、在线人数或弹幕接口。当前跨平台悬停预览和弹幕尚未接入。

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

返回 `(显示文字, 回调)` 的列表。回调里的异常只会打印到 stderr，不会冒到界面线程。
本体的菜单项和插件的项之间会自动加分隔线。

## 五、插件自己的配置

```python
context.setting("token", "")            # 读
context.set_setting("token", "abc")     # 写，并通知本体落盘
```

存在 `utils/config.json` 的 `plugins.<目录名>` 段下。

## 边界与保证

- **插件异常不会拖垮本体**：`on_load`、`on_event`、`tile_actions`、菜单回调都被包住。
  坏插件只坏它自己。
- **装载顺序**：按目录名排序。同一个平台被两个插件注册会报错。
- **卸载**：关窗时先发 `app.closing`，再调 `on_unload()`，然后才存配置、放播放器。
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

`function/plugin-tile-extensions` 提供上述接口；配套插件源码在
[DD_Monitor_Plugins](https://github.com/Lanpropro/DD_Monitor_Plugins) 的本地
`codex/bili-live` 分支。使用插件管理器安装 `dist/bili_live-1.0.zip`，按现有流程保存并重启。
继续在本体账号界面登录 B 站，各数字房间格子自动显示输入、表情、礼物和发送控件。
禁用/移除插件同样在重启后生效；登录持久化、播放和接收弹幕仍由本体负责。
插件在装载前检查必要公开接口，旧版本本体会报告兼容性要求。

该 ZIP 当前是本地产物，网站没有对应下载条目。

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
