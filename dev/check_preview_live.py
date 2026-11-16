"""验证关注卡片悬停预览并通过 libmpv 抓帧，不读取本机账号。

用法：python dev/check_preview_live.py 房间号
      python dev/check_preview_live.py --source 本地视频 --output 输出目录
"""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from unittest.mock import patch
from ddm import bili, config, images, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from selfcheck_mpv import pump, ready


def snapshot_stats(path: str) -> tuple[int, int]:
    """返回宽度与采样颜色数，用来检查抓帧是否包含有效画面。"""
    image = QImage(path)
    if image.isNull():
        return 0, 0
    colors = set()
    for y in range(0, image.height(), 7):
        for x in range(0, image.width(), 7):
            colors.add(image.pixel(x, y))
    return image.width(), len(colors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("room_id", nargs="?")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(REPO) / "work/preview-live")
    args = parser.parse_args()
    if bool(args.room_id) == bool(args.source):
        parser.error("指定房间号或 --source 本地视频，两者选一")
    if args.source and not args.source.is_file():
        parser.error("本地视频不存在")
    room = ({"room_id": "1001", "uname": "Local preview", "live": True}
            if args.source else bili.room_info(args.room_id))
    if not room or not room.get("live"):
        print("房间未开播或无法获取公开信息")
        return 1
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    with tempfile.TemporaryDirectory(prefix="ddm-preview-check-") as directory, ExitStack() as stack:
        stack.enter_context(patch.object(config, "DATA_ROOT", directory))
        stack.enter_context(patch.object(config, "CONFIG_PATH", str(Path(directory) / "config.json")))
        stack.enter_context(patch.object(images, "REPO", directory))
        stack.enter_context(patch("ddm.plugins.DEFAULT_PLUGINS_DIR", directory))
        for method in ("refresh_status", "refresh_stats", "refresh_account", "_check_startup_update"):
            stack.enter_context(patch.object(MainWindow, method))
        if args.source:
            stack.enter_context(patch.object(bili, "play_url", return_value=(
                str(args.source.resolve()), 250, "web", {})))
            stack.enter_context(patch.object(bili, "room_quality_options", return_value=[]))
        state = {"plugins_enabled": [], "settings": {"close_behavior": "exit",
                 "preview_on_hover": True, "danmaku_enabled": False, "auto_update": False}}
        window = MainWindow([dict(room)], [], layout_id="1x1", state=state)
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.setGeometry(-8000, -8000, 1200, 700)
        try:
            window.show()
            window.sidebar.set_card_mode(True)
            app.processEvents()
            item = window.sidebar.items()[0]
            preview = window.hover_preview
            stack.enter_context(patch.object(preview, "_cursor_on_item", return_value=True))
            preview.on_hover(item.room)
            for _ in range(300):
                if item.thumb._player is not None:
                    break
                pump(app, 0.05)
            player = item.thumb._player
            assert player is not None, "悬停必须创建预览播放器"
            ready(app, player)
            assert item.thumb.video.isVisible() and player.silent and player.muted
            args.output.mkdir(parents=True, exist_ok=True)
            shot = args.output / "thumb_frame.png"
            player.player.screenshot_to_file(str(shot.resolve()), includes="video")
            width, colors = snapshot_stats(str(shot))
            assert width > 0 and colors >= 20, "缩略图里没有有效画面"
            assert window.sidebar.grab().save(str(args.output / "sidebar_thumbs.png"), "PNG")
            print(f"PASS: libmpv hover preview frame, width={width}, colors={colors}, silent=True")
        finally:
            window.close()
            app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
