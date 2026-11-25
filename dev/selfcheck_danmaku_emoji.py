"""Offline regression: Bilibili emotes survive parsing and both renderers."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DDM_NO_SAVE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QColor, QPixmap, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

from blivedm.models.web import DanmakuMessage
from ddm import theme
from ddm.danmaku import _Handler
from ddm.danmaku_content import content_runs, content_html
from ddm.video_danmaku import VideoDanmaku
from ddm.widgets import DanmakuPanel
from dev.selfcheck_video_danmaku import wait_comment_raster


URL = "https://example.invalid/emote.png?a=1&b=2"


def event_for(message):
    events = []
    _Handler(events.append)._on_danmaku(None, message)
    return events[0]


def main():
    app = QApplication(sys.argv)
    def wait_raster(overlay):
        deadline = time.monotonic() + 5
        while overlay._comment_raster_job is not None or overlay._comment_resize_timer.isActive():
            assert time.monotonic() < deadline
            QTest.qWait(10)
    app.setStyleSheet(theme.qss())
    extra = {"emots": {"[emoji]": {"url": URL}, "[bad]": None}}
    text = "前面[emoji]中间[emoji]后面 👨‍👩‍👧‍👦👍🏽 & <tag>"
    for encoded in (extra, json.dumps(extra)):
        message = DanmakuMessage(msg=text, uname="测试", mode_info={"extra": encoded})
        event = event_for(message)
        assert event["emoticons"] == {"[emoji]": URL}
        assert content_runs(event) == [("前面", ""), ("[emoji]", URL), ("中间", ""),
                                       ("[emoji]", URL), ("后面 👨‍👩‍👧‍👦👍🏽 & <tag>", "")]
    info = [[0, 1, 25, 0xffffff, 0, 0, 0, "", 0, 0, 0, 0, 0, {}, {},
             {"extra": json.dumps(extra)}], text, [1, "测试", 0, 0, 0, 0, 0, ""],
            [], [0, 0, 0, ""], [], 0, 0]
    assert event_for(DanmakuMessage.from_command(info))["emoticons"] == {"[emoji]": URL}
    for malformed in (None, [], "{", "null", '{"emots": []}'):
        event_bad = event_for(DanmakuMessage(msg=text, mode_info={"extra": malformed}))
        assert event_bad["text"] == text and not event_bad["emoticons"]
    for encoded in ({"url": URL, "emoticon_unique": "official_13"},
                    json.dumps({"url": URL, "emoticon_unique": "official_13"})):
        single = event_for(DanmakuMessage(msg="[emoji]", dm_type=1, emoticon_options=encoded))
        assert content_runs(single) == [("[emoji]", URL)]
        assert single["dm_type"] == 1 and single["emoticon_unique"] == "official_13"
    assert content_runs({"text": "😀👍🏽👨‍👩‍👧‍👦"}) == [("😀👍🏽👨‍👩‍👧‍👦", "")]

    # Use a non-square image to verify that both renderers preserve its full aspect ratio.
    pixmap = QPixmap(80, 40)
    pixmap.fill(QColor("#fc2387"))
    images = {URL: pixmap.toImage()}
    rendered = content_html(content_runs(event), images, 24)
    assert rendered.count("<img") == 2 and "[emoji]" not in rendered
    assert 'width="48" height="24"' in rendered
    assert "&amp;" in rendered and "&lt;tag&gt;" in rendered
    assert "[emoji]" in content_html(content_runs(event), {}, 24)

    host = QWidget()
    layout = QVBoxLayout(host)
    panel = DanmakuPanel()
    overlay = VideoDanmaku()
    overlay.setMinimumHeight(180)
    overlay.set_native_video(False)
    layout.addWidget(panel)
    layout.addWidget(overlay)
    host.resize(900, 600)
    host.show()
    overlay.apply_settings({"video_danmaku_scale": False, "video_danmaku_size": 28,
                            "video_danmaku_area": 100})
    overlay.set_enabled(True)
    overlay.set_active(True)
    app.processEvents()
    try:
        with patch.object(panel, "_ensure_emoticon"), patch.object(overlay, "_ensure_emoticon"):
            panel.add_event(event)
            assert "[emoji]" in panel.body.toPlainText()
            panel._on_emoticon_loaded(URL, pixmap)
            QTest.qWait(40)
            assert "[emoji]" not in panel.body.toPlainText()
            assert panel.body.toHtml().count("<img") == 2
            assert "👨‍👩‍👧‍👦👍🏽" in panel.body.toPlainText()
            panel.add_event(single)
            assert "[emoji]" not in panel.body.toPlainText()
            resource = panel.body.document().resource(QTextDocument.ImageResource, QUrl(URL))
            assert resource is not None and not resource.isNull()

            panel.clear()
            first, second, late = (f"https://example.invalid/{name}.png"
                                   for name in ("first", "second", "late"))
            panel.add_events({"text": f"message {index}" + ("[a][b]" if index < 18 else ""),
                              "emoticons": {"[a]": first, "[b]": second}}
                             for index in range(90))
            app.processEvents()
            bar = panel.body.verticalScrollBar()
            bar.setValue(bar.maximum() // 2)
            panel._on_user_scroll()
            point = QPoint(5, 6)
            anchor = panel.body.cursorForPosition(point)
            anchor_text = anchor.block().text()
            anchor_y = panel.body.cursorRect(anchor).y()
            with patch.object(panel, "_block_html", wraps=panel._block_html) as format_block:
                panel._on_emoticon_loaded(first, pixmap)
                panel._on_emoticon_loaded(second, pixmap)
                deadline = time.monotonic() + 2
                while panel.document_control._emoticon_refresh.isActive():
                    assert time.monotonic() < deadline
                    QTest.qWait(10)
                assert format_block.call_count == 18, "Each affected block should be rebuilt once"
            assert panel.body.toHtml().count("<img") == 36
            assert panel.body.document().blockCount() == 90
            current = panel.body.cursorForPosition(point)
            assert current.block().text() == anchor_text
            assert abs(panel.body.cursorRect(current).y() - anchor_y) <= 1

            panel.add_event({"text": "[late]", "emoticon": late})
            panel._on_emoticon_loaded(late, pixmap)
            assert panel.document_control._emoticon_refresh.isActive()
            panel.clear()
            panel.add_message("new room", "no old images")
            QTest.qWait(40)
            assert panel.body.toPlainText() == "new room：no old images"
            assert not panel.document_control._emoticon_refresh.isActive()

            assert overlay.add_event(single)
            wait_comment_raster(QApplication.instance(), overlay)
            comment = overlay.comments[0]
            before = comment.image.toImage()
            with patch.object(overlay, '_render_content', side_effect=AssertionError('Emoticon callbacks must not rasterize on GUI')):
                overlay._on_emoticon_loaded(URL, pixmap)
            wait_raster(overlay)
            assert len(overlay.comments) == 1 and comment.image.toImage() != before
            assert comment.image.width() > comment.image.height()
            assert any(comment.image.toImage().pixelColor(x, y).name() == "#fc2387"
                       for x in range(comment.image.width()) for y in range(comment.image.height()))
            overlay.apply_settings(dict(overlay.settings, video_danmaku_size=40))
            assert overlay.comments and overlay.comments[0].image.height() > before.height()
            overlay.clear()
            assert overlay.add_event(event)
            wait_comment_raster(QApplication.instance(), overlay)
            assert overlay.comments[0].runs == content_runs(event)
            overlay.clear()
            overlay._on_emoticon_loaded(URL, pixmap)
            assert not overlay.comments, "Late image loads must not resurrect cleared comments"
            assert overlay.add_event({"text": "😀👍🏽👨‍👩‍👧‍👦"})
            wait_comment_raster(QApplication.instance(), overlay)
            assert not overlay.comments[0].image.isNull()
            overlay.clear()
            overlay.apply_settings(dict(overlay.settings, video_danmaku_size=28))
            assert overlay.add_event(single)
            wait_comment_raster(QApplication.instance(), overlay)
            assert overlay.add_event({"text": "Unicode 😀👍🏽👨‍👩‍👧‍👦"})
            wait_comment_raster(QApplication.instance(), overlay)
            assert overlay.add_event(event)
            wait_comment_raster(QApplication.instance(), overlay)
            for comment in overlay.comments:
                comment.x = 30
            app.processEvents()
            output = Path(__file__).resolve().parent.parent / "work" / "emoji-preview.png"
            output.parent.mkdir(exist_ok=True)
            assert host.grab().save(str(output))
        # Exercise real QThread completion without network, including retry after failure.
        failed = "https://example.invalid/retry.png"
        with patch("ddm.images.load_pixmap", return_value=None):
            overlay._ensure_emoticon(failed)
            worker = overlay._emoticon_loaders[failed]
            assert worker.wait(2000)
            QTest.qWait(30)
            assert failed not in overlay._emoticon_loaders
            panel._ensure_emoticon(failed)
            assert panel._emoticon_loaders[-1].wait(2000)
            QTest.qWait(30)
            assert failed not in panel._loading_emoticons
        with patch("ddm.images.load_pixmap", return_value=pixmap):
            overlay._ensure_emoticon(failed)
            assert overlay._emoticon_loaders[failed].wait(2000)
            QTest.qWait(30)
            assert failed in overlay._images
    finally:
        host.close()
    print("PASS: parser, Unicode, inline/single emotes, fallback, HTML escaping, both views, resize and clear")


if __name__ == "__main__":
    main()
