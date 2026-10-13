"""Offline regression: Bilibili emotes survive parsing and both renderers."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DDM_NO_SAVE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QPixmap, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

from blivedm.models.web import DanmakuMessage
from ddm import theme
from ddm.danmaku import _Handler
from ddm.danmaku_content import content_runs, content_html
from ddm.video_danmaku import VideoDanmaku
from ddm.widgets import DanmakuPanel


URL = "https://example.invalid/emote.png?a=1&b=2"


def event_for(message):
    events = []
    _Handler(events.append)._on_danmaku(None, message)
    return events[0]


def main():
    app = QApplication(sys.argv)
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
    for encoded in ({"url": URL}, json.dumps({"url": URL})):
        single = event_for(DanmakuMessage(msg="[emoji]", dm_type=1, emoticon_options=encoded))
        assert content_runs(single) == [("[emoji]", URL)]
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
            assert "[emoji]" not in panel.body.toPlainText()
            assert panel.body.toHtml().count("<img") == 2
            assert "👨‍👩‍👧‍👦👍🏽" in panel.body.toPlainText()
            panel.add_event(single)
            assert "[emoji]" not in panel.body.toPlainText()
            resource = panel.body.document().resource(QTextDocument.ImageResource, QUrl(URL))
            assert resource is not None and not resource.isNull()

            assert overlay.add_event(single)
            comment = overlay.comments[0]
            before = comment.image.toImage()
            overlay._on_emoticon_loaded(URL, pixmap)
            assert len(overlay.comments) == 1 and comment.image.toImage() != before
            assert comment.image.width() > comment.image.height()
            assert any(comment.image.toImage().pixelColor(x, y).name() == "#fc2387"
                       for x in range(comment.image.width()) for y in range(comment.image.height()))
            overlay.apply_settings(dict(overlay.settings, video_danmaku_size=40))
            assert overlay.comments and overlay.comments[0].image.height() > before.height()
            overlay.clear()
            assert overlay.add_event(event)
            assert overlay.comments[0].runs == content_runs(event)
            overlay.clear()
            overlay._on_emoticon_loaded(URL, pixmap)
            assert not overlay.comments, "Late image loads must not resurrect cleared comments"
            assert overlay.add_event({"text": "😀👍🏽👨‍👩‍👧‍👦"})
            assert not overlay.comments[0].image.isNull()
            overlay.clear()
            overlay.apply_settings(dict(overlay.settings, video_danmaku_size=28))
            assert overlay.add_event(single)
            assert overlay.add_event({"text": "Unicode 😀👍🏽👨‍👩‍👧‍👦"})
            assert overlay.add_event(event)
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
