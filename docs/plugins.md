# 插件接口

不想塞进本体的功能放这里：录像、接抖音/YouTube/Twitch、发弹幕、给格子加菜单项。
插件是**普通 Python 代码**，和本体同进程运行，能力等价于本体代码 —— 只装自己看过源码的插件。

> 本页只写**已经实现**的接口。哪些功能打算做、卡在哪、要动哪些文件，见
> [`idea.txt`](../idea.txt)。

## 目录约定

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
卡片拖入画面墙或右键“加入画面墙”后，后台 `play_url` 的结果交给现有 VLC
格子播放；请求头随流地址传给播放器。可选 `room_quality_options` 返回
`[{"qn": 10000, "desc": "原画"}]`，未实现时沿用原有菜单。

平台实现 `rooms_status` 供后台刷新，返回以带平台前缀的房间号为键的字典，
字段与 `RoomInfo.as_dict()` 一致。网络失败不能返回伪造的下播状态。
平台请求必须有超时；本体分别处理平台与 B 站房间，不会把前缀房间号传给
B 站取流、在线人数或弹幕接口。当前跨平台悬停预览和弹幕尚未接入。

卡片基本资料与格子位置随配置保存，启动时状态为待刷新，后台恢复播放。
禁用或删除插件后保留关注与位置，在格子提示启用插件。
虎牙 v0.2.0 位于 `plugins_user/huya_watch`，使用 Streamlink 8.6.1 解析公开
直播流。可添加 `huya:房间号` 或虎牙官方房间链接；旧网页卡片自动迁移。
使用与验收步骤见 `plugins_user/huya_watch/README.md`。

同一个 `kind` 注册两次会直接报错 —— 静默覆盖会让两家插件互相打架，不如当场炸出来。

## 三、发弹幕

弹幕接收与显示属于本体功能。发弹幕接口留给之后能完整实现认证和发送的插件：

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
