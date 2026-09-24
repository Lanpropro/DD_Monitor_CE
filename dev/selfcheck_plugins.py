"""自查：插件接口。

分三段：
1. 管理器本身（装载 / 跳过 / 事件 / 平台注册冲突 / 菜单项 / 异常隔离）——不联窗口；
2. 本体的接线（``stream.resolved`` 事件带请求头、格子右键菜单能拿到插件项、
   取流结果记在格子上）——需要一个窗口，播放全部打桩；
3. 示例插件（plugins_user/danmaku_log）真的能用。
"""
import os
import sys
import tempfile
import time
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, plugins as plugin_api, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [
    {"room_id": "9001", "uname": "主播甲", "title": "房间甲", "live": True,
     "muted": True, "volume": 42, "quality": 250},
]

PLUGIN_SOURCE = '''
from ddm import plugins as api


class DemoSender(api.DanmakuSender):
    def available(self):
        return True, ""

    def send(self, room_id, text):
        return True, f"demo:{room_id}:{text}"


class DemoPlatform(api.Platform):
    kind = "demo"
    label = "示例站"

    def matches(self, room_id):
        return str(room_id).startswith("demo:")

    def room_info(self, room_id):
        return api.RoomInfo(room_id=room_id, uname="示例主播", live=True,
                            platform=self.kind)

    def play_url(self, room_id, quality=250):
        return f"http://127.0.0.1:9/{room_id}.flv", quality, "demo", {"X-Demo": "1"}


class Exploding(api.Plugin):
    name = "会炸的插件"

    def on_event(self, event, payload):
        raise RuntimeError("故意炸一下")


class DemoPlugin(api.Plugin):
    name = "演示插件"
    description = "把接口每一条都走一遍"
    version = "0.1"

    def on_load(self, context):
        self.context = context
        self.loaded = True
        context.register_platform(DemoPlatform())
        context.register_danmaku_sender(DemoSender())

    def on_event(self, event, payload):
        seen.append(event)

    def tile_actions(self, tile):
        return [("演示动作", lambda: tile.room.setdefault("demo_clicked", True))]


seen = []
plugin = DemoPlugin()
'''


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def write_plugin(root: str, name: str, source: str) -> None:
    folder = os.path.join(root, name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "plugin.py"), "w", encoding="utf-8") as handle:
        handle.write(source)


def part_one() -> None:
    print("=== 1. 管理器：装载、事件、平台、异常隔离 ===")
    root = tempfile.mkdtemp(prefix="ddm_plugins_")
    write_plugin(root, "demo", PLUGIN_SOURCE)
    write_plugin(root, "broken", "this is not python (\n")
    write_plugin(root, "notaplugin", "thing = 1\n")
    os.makedirs(os.path.join(root, "_ignored"), exist_ok=True)

    manager = plugin_api.PluginManager(plugins_dir=root, enabled=["demo", "broken", "notaplugin"])
    manager.plugin_settings = {}
    manager.load()
    print(f"  装载：{manager.summary}")
    print(f"  跳过：{manager.skipped}")
    assert [p.name for p in manager.plugins] == ["演示插件"], manager.plugins
    skipped_names = {name for name, _ in manager.skipped}
    assert skipped_names == {"broken", "notaplugin"}, skipped_names
    print("  坏插件只坏自己，没拖垮装载")

    print("\n=== 2. 事件广播 + 单个插件抛异常不影响别人 ===")
    # 再装一个坏在事件里的插件：它的异常不能挡住 demo 收事件
    write_plugin(root, "flaky", PLUGIN_SOURCE.replace(
        "class DemoPlugin(api.Plugin):", "class DemoPlugin(api.Plugin):\n    pass\n\n\nclass _X(api.Plugin):"))
    manager2 = plugin_api.PluginManager(plugins_dir=root, enabled=["demo", "flaky"])
    manager2.plugin_settings = {}
    manager2.load()
    manager2.emit(plugin_api.EVENT_STARTED)
    demo = next(p for p in manager2.plugins if p.name == "演示插件")
    module = sys.modules.get("ddm_plugin_demo")
    seen = getattr(module, "seen", [])
    print(f"  demo 收到事件：{seen}（管理器共 {len(manager2.plugins)} 个插件）")
    assert plugin_api.EVENT_STARTED in seen, "坏插件的异常不能挡住好插件收事件"

    print("\n=== 3. 平台：matches / room_info / play_url ===")
    platform = manager.platforms.get("demo")
    assert platform is not None, "插件注册的平台应该在表里"
    print(f"  平台：{platform.kind} / {platform.label}")
    assert platform.matches("demo:42") and not platform.matches("9001")
    info = platform.room_info("demo:42")
    assert info is not None and info.platform == "demo"
    print(f"  room_info -> {info.as_dict()}")
    url, qn, channel, headers = platform.play_url("demo:42", 250)
    print(f"  play_url -> {url} qn={qn} 通道={channel} 头={headers}")
    assert channel == "demo" and headers == {"X-Demo": "1"}

    print("\n=== 4. 平台重名直接报错（不许悄悄覆盖）===")
    other = plugin_api.PluginManager(plugins_dir=root)
    other.plugin_settings = {}
    other.register_platform("甲方", platform)
    try:
        other.register_platform("乙方", platform)
    except ValueError as error:
        print(f"  如期报错：{error}")
    else:
        raise AssertionError("同一个 kind 注册两次必须报错")

    print("\n=== 5. tile_actions：菜单项与回调隔离 ===")
    class FakeTile:
        room = {"room_id": "demo:42"}

    actions = manager.tile_actions(FakeTile())
    labels = [label for label, _cb, _name in actions]
    print(f"  菜单项：{labels}")
    assert labels == ["演示动作"], labels
    manager.run_action(actions[0][1])
    assert FakeTile.room.get("demo_clicked") is True, "回调应该被真的调用"
    manager.run_action(lambda: (_ for _ in ()).throw(RuntimeError("炸")))
    print("  回调抛异常时只打印，不往外冒")
    print("  注意：上面那几条 Traceback 是本自检**故意**喂进去的坏插件/坏回调，"
          "用来验证隔离；看到它们说明隔离生效。")

    print("\n=== 6. 插件自己的配置读写 ===")
    saved = {"count": 0}
    manager.plugin_settings = {"demo": {}}
    manager._save_settings = lambda: saved.__setitem__("count", saved["count"] + 1)
    demo_context = plugin_api.PluginContext(manager, "demo")
    demo_context.set_setting("token", "abc")
    print(f"  写入后：{manager.plugin_settings['demo']} 落盘次数={saved['count']}")
    assert demo_context.setting("token") == "abc"
    assert saved["count"] == 1, "改配置要通知本体落盘"


def part_two(app) -> None:
    print("\n=== 7. 本体接线：取流结果 + 事件 + 格子菜单 ===")
    bili.play_url = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("selfcheck：不联网"))
    window = MainWindow([dict(r) for r in ROOMS], [dict(r) for r in ROOMS], layout_id="1x1")
    window.setGeometry(-8000, -8000, 900, 560)
    window.show()
    settle(app, 1.2)
    tile = window.wall.tiles[0]

    print(f"  已装载插件：{window.plugins.summary}")
    assert window.plugins.plugins, "plugins_user 下的插件应该被自动装载"
    assert window.plugins.danmaku_sender is not None, "示例插件应提供发弹幕能力"

    print("\n=== 7a. 关注卡片：浏览器入口及插件可选网页地址 ===")
    item = window.sidebar.items()[0]
    def browser_action(card):
        return next((action for action in card._context_menu().actions()
                     if action.text() == "用默认浏览器打开直播间"), None)

    action = browser_action(item)
    assert action is not None, "B 站数字房间应该有浏览器入口"
    with patch("ddm.app.webbrowser.open") as opened:
        action.trigger()
        assert opened.call_args.args == ("https://live.bilibili.com/9001",)
    assert window._room_browser_url({"room_id": "demo:42"}) == ""
    assert window._room_browser_url({"room_id": "https://example.com"}) == ""
    plugin_item = window.sidebar._append_item({"room_id": "demo:42", "uname": "插件房间"})
    assert browser_action(plugin_item) is None, "插件不提供 room_url 时应隐藏"

    class WebPlatform(plugin_api.Platform):
        kind = "demo"
        def matches(self, room_id):
            return str(room_id).startswith("demo:")
        def room_url(self, room_id):
            return "https://example.com/live/42"

    window.plugins.register_platform("测试", WebPlatform())
    action = browser_action(plugin_item)
    assert action is not None, "插件提供 URL 后应显示入口"
    with patch("ddm.app.webbrowser.open") as opened:
        action.trigger()
        assert opened.call_args.args == ("https://example.com/live/42",)
    window.plugins.platforms["demo"].room_url = lambda _id: "file:///local/secret"
    assert browser_action(plugin_item) is None, "非网页 URL 不应打开"

    events: list = []
    received: dict = {}

    class Recorder(plugin_api.Plugin):
        name = "记录器"

        def on_event(self, event, payload):
            events.append(event)
            if event == plugin_api.EVENT_STREAM_RESOLVED:
                received["source"] = payload.get("source")

    window.plugins.plugins.append(Recorder())

    # 直接调 _play_on：这是取流成功后的落点，插件事件就从这里发出去
    window._play_on(tile, "http://127.0.0.1:9/live.flv", 250, "app",
                    options=None, headers={"User-Agent": "UA-x"})
    settle(app, 0.4)
    print(f"  收到事件：{[e for e in events if e == plugin_api.EVENT_STREAM_RESOLVED]}")
    assert plugin_api.EVENT_STREAM_RESOLVED in events, "取流成功要播报 stream.resolved"
    source = received.get("source")
    assert source is not None, "事件里要带上取流结果"
    print(f"  StreamSource：room={source.room_id} url={source.url} "
          f"通道={source.channel} 画质={source.quality} 头={source.headers}")
    assert source.headers.get("User-Agent") == "UA-x", "请求头必须一起给插件（录像要用）"

    print(f"  格子记下取流结果：url={bool(tile.stream_url)} "
          f"通道={tile.stream_profile} 头={tile.stream_headers}")
    assert tile.stream_url == "http://127.0.0.1:9/live.flv"
    assert tile.stream_profile == "app"
    assert tile.stream_headers.get("User-Agent") == "UA-x"

    print("\n=== 8. 格子右键菜单带上插件的项 ===")
    tile.plugin_actions = []
    window._fill_plugin_menu(tile)
    labels = [label for label, _cb in tile.plugin_actions]
    print(f"  插件菜单项：{labels}")
    assert "复制流地址" in labels, f"示例插件的「复制流地址」应在菜单里，实际 {labels}"
    menu = tile.build_menu()
    menu_labels = [a.text() for a in menu.actions() if a.text()]
    print(f"  整个菜单：{menu_labels}")
    assert "复制流地址" in menu_labels, "插件项要真的出现在菜单里"
    # 本体原有的项一个都不能少
    for expected in ("静音", "刷新重连", "放到主画面", "关闭这一路", "画质", "声道"):
        assert expected in menu_labels or expected == "静音", f"菜单丢了本体的项：{expected}"

    print("\n=== 9. 关闭时插件收到 app.closing 并卸载 ===")
    events.clear()
    window.close()
    settle(app, 0.5)
    print(f"  关闭时收到：{[e for e in events if e == plugin_api.EVENT_CLOSING]}")
    assert plugin_api.EVENT_CLOSING in events, "关窗要通知插件收尾"


def part_three() -> None:
    print("\n=== 10. 示例插件：弹幕落盘 ===")
    # 打包成 exe 之后 __file__ 在 _internal 里面：插件目录和图片缓存都必须跟着
    # config.REPO（它认得 frozen）走，否则 exe 版永远是「[插件] 0 个插件」，
    # 头像也会写进运行库目录里。
    from ddm import config as config_module
    from ddm import images as images_module
    print(f"  插件目录={plugin_api.DEFAULT_PLUGINS_DIR}")
    print(f"  图片缓存根目录={images_module.REPO}")
    assert plugin_api.DEFAULT_PLUGINS_DIR == os.path.join(config_module.REPO, "plugins_user"), \
        "插件目录要放在程序旁边（config.REPO），不能用 __file__ 推"
    assert images_module.REPO == config_module.REPO, "图片缓存也要放在程序旁边"
    root = tempfile.mkdtemp(prefix="ddm_demo_")
    manager = plugin_api.PluginManager(
        plugins_dir=os.path.join(REPO, "plugins_user"), enabled=None)
    manager.plugin_settings = {}
    manager.load()
    assert manager.plugins, "示例插件应该被装载"
    log_dir = os.path.join(REPO, "plugins_user", "_danmaku_log")
    room_file = os.path.join(log_dir, "9001.log")
    if os.path.exists(room_file):
        os.remove(room_file)
    manager.emit(plugin_api.EVENT_DANMAKU, room_id="9001",
                 message={"kind": "danmaku", "uname": "某人", "text": "测试一条弹幕"})
    assert os.path.exists(room_file), f"弹幕应该落到 {room_file}"
    with open(room_file, encoding="utf-8") as handle:
        content = handle.read()
    print(f"  写入内容：{content.strip()!r}")
    assert "测试一条弹幕" in content and "某人" in content
    os.remove(room_file)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    part_one()
    part_two(app)
    part_three()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
