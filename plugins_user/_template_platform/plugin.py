"""模板插件：接一个 B 站以外的直播间（抖音 / YouTube / Twitch 都照这个写）。

**为什么值得先看这个文件**：本体只认识「房间号 → 房间信息 + 一个 http 流地址」，
把这两件事交出来，播放、布局、音量、弹幕面板全都不需要改。所以接新平台的
工作量集中在「怎么把那个站的页面/接口变成一条能给 VLC 的流地址」。

三个必须实现的钩子
------------------
``kind``      平台短名，会存进房间信息里，用来区分「12345」是哪个站的
``matches``   判断一个房间号是不是本平台的（本体会按装载顺序问每个平台）
``room_info`` 拉房间信息（标题、主播、封面、是否在播）
``play_url``  给出可直接播放的 http 流地址

``play_url`` 的返回值
---------------------
``(url, 实际画质, 通道名)`` 或 ``(url, 实际画质, 通道名, 请求头)``。

**请求头一定要给对**，否则 CDN 403；而且 VLC 插件集没有 TLS，地址尽量用 http：

- B 站 app 通道：只认 App UA，**不能带** Referer
- B 站 web 通道：Chrome UA + Referer
- 其它站点：按各家的防盗链要求来（Twitch 有签名 token，YouTube 要解析 manifest）

想让本体认识某个房间号，添加直播间时得写成 ``<kind>:<房间号或链接>``，
例如 ``douyin:123456``。这是为了不和 B 站的纯数字房间号撞车。

录像怎么办
----------
不用在这里做。本体在每次取流成功后播报 ``stream.resolved`` 事件，事件里带着
``StreamSource``（url + 请求头）。录像插件拿这个结果去喂 ffmpeg 就行，
既不用二次取流，也不用碰播放器：

    def on_event(self, event, payload):
        if event != api.EVENT_STREAM_RESOLVED:
            return
        source = payload["source"]        # api.StreamSource
        subprocess.Popen(["ffmpeg", "-headers", format_headers(source.headers),
                          "-i", source.url, "-c", "copy", out_path])
"""
from ddm import plugins as api


class MyPlatform(api.Platform):
    kind = "myplatform"          # 房间号写 myplatform:xxx
    label = "我的平台"

    def matches(self, room_id: str) -> bool:
        return str(room_id).startswith(f"{self.kind}:")

    def normalize(self, room_id: str) -> str:
        """把用户粘的整条链接整理成 ``kind:room``。"""
        text = str(room_id or "").strip()
        if text.startswith(f"{self.kind}:"):
            return text
        # 例：从 https://example.com/live/123 里抠出 123
        tail = text.rstrip("/").rsplit("/", 1)[-1]
        return f"{self.kind}:{tail or text}"

    def room_info(self, room_id: str) -> api.RoomInfo | None:
        """拉一次房间信息。拿不到就返回 None，本体显示「房间 <id>」。"""
        raw = str(room_id).split(":", 1)[-1]
        # 这里换成真的接口调用（requests / 解析页面 / 调官方 API 都行）
        return api.RoomInfo(
            room_id=raw,
            uname="主播名",
            title="直播间标题",
            live=True,
            viewers="0",
            platform=self.kind,
        )

    def rooms_status(self, room_ids: list) -> dict:
        """批量查状态，用于轮询。返回 {room_id: {live, title, viewers}}。

        不做也能跑：本体就只会用 room_info 的单次结果。
        """
        return {}

    def play_url(self, room_id: str, quality: int = 250) -> tuple:
        raw = str(room_id).split(":", 1)[-1]
        # 换成真的取流：拿到 http(s) 的 flv/hls 地址
        url = f"http://127.0.0.1:9/{raw}.flv"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://example.com/"}
        return url, quality, self.kind, headers


class MyPlatformPlugin(api.Plugin):
    name = "我的平台"
    description = "接一个 B 站以外的直播间（模板，需要自己填接口）"
    version = "0.1"

    def on_load(self, context: api.PluginContext) -> None:
        context.register_platform(MyPlatform())
        context.log(f"已注册平台 {MyPlatform.kind}；"
                    f"添加直播间时写 {MyPlatform.kind}:房间号")


# 这个文件放在 plugins_user/ 下的任何一个子目录里、文件名是 plugin.py 就会被装载。
# 因为只是模板、接口都是假的，默认不启用：把下面这行改成构造实例，
# 或者把整个目录挪到 plugins_user/ 并删掉文件名里的下划线前缀即可。
plugin = None
