# 插件接口

不想塞进本体的功能放这里：录像、接抖音/YouTube/Twitch、发弹幕、给格子加菜单项。
插件是**普通 Python 代码**，和本体同进程运行，能力等价于本体代码 —— 只装自己看过源码的插件。

> 本页只写**已经实现**的接口。哪些功能打算做、卡在哪、要动哪些文件，见
> [`idea.txt`](../idea.txt)。

## 目录约定

```
plugins_user/
  <插件名>/
    plugin.py        # 必须存在，里面要有一个叫 plugin 的 Plugin 实例
```

- `plugins_user/` 下的每个子目录都会被扫描；目录名就是插件的标识（也叫 `name`）。
- 以 `_` 或 `.` 开头的目录会被**跳过**（给模板和插件自己的数据用）。
  `plugins_user/_danmaku_log/` 就是弹幕日志的落盘位置。
- 装载失败的插件只会被跳过并在 stderr 打印原因，不会影响程序启动。

启用在配置里控制：`utils/config.json` 的 `plugins_enabled` 写成插件目录名的数组，
不写或写 `null` 表示全部启用。

## 最小插件

```python
from ddm import plugins as api


class MyPlugin(api.Plugin):
    name = "我的插件"
    description = "一句话说明"
    version = "1.0"

    def on_load(self, context: api.PluginContext) -> None:
        context.log("装载完成")

    def on_event(self, event: str, payload: dict) -> None:
        if event == api.EVENT_DANMAKU:
            print(payload["message"]["text"])


plugin = MyPlugin()
```

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


class MyPlugin(api.Plugin):
    def on_load(self, context):
        context.register_platform(MyPlatform())
```

房间号写成 `<kind>:<房间号或链接>`（例如 `douyin:123456`），用来和 B 站的纯数字房间号区分。
完整骨架见 `plugins_user/_template_platform/plugin.py`。

同一个 `kind` 注册两次会直接报错 —— 静默覆盖会让两家插件互相打架，不如当场炸出来。

## 三、发弹幕

各家平台的发送方式差异太大，本体不内置，改成「插件实现、本体调用」：

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

B 站的具体做法见 `plugins_user/danmaku_log/plugin.py`：走
`POST https://api.live.bilibili.com/msg/send`，需要 `SESSDATA`（本体已保存）
和 `bili_jct`（CSRF 票据，目前要自己填进插件配置）。

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
