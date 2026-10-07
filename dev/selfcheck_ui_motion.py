"""界面动效：真实鼠标点击、明显入场、中间帧、连续打断、最终位置和系统动画关闭。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import config, motion, theme
from ddm.dialogs import AddRoomDialog, SettingsDialog
from ddm.online_ui import UpdateNotice
from ddm.widgets import Sidebar


def main():
    callback_errors = []
    original_hook = sys.excepthook
    def capture_error(kind, error, trace):
        callback_errors.append(error)
        original_hook(kind, error, trace)
    sys.excepthook = capture_error
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    with patch.object(motion, "enabled", return_value=True):
        dialog = AddRoomDialog()
        dialog.show()
        app.processEvents()
        target = QPoint(dialog._entrance_target)
        assert dialog._entrance.state() == QAbstractAnimation.Running
        assert dialog._entrance.duration() == 160
        assert dialog.pos().y() > target.y() and dialog.windowOpacity() == 1
        for frame in (0, 20, 40, 60, 80):
            dialog._entrance.setCurrentTime(frame)
            assert dialog.windowOpacity() == 1, "entrance must never change window opacity"
        dialog._entrance.setCurrentTime(80)
        assert target.y() < dialog.pos().y() < target.y() + 20
        QTest.qWait(180)
        assert dialog.pos() == target and dialog.windowOpacity() == 1
        dialog.hide()
        dialog.show()
        app.processEvents()
        dialog.reject()
        assert not dialog.isVisible() and dialog.pos() == target
        assert dialog._entrance.state() != QAbstractAnimation.Running
        dialog.show()
        app.processEvents()
        dragged_position = dialog.pos() + QPoint(60, 40)
        dialog.move(dragged_position)
        app.processEvents()
        assert dialog._entrance.state() != QAbstractAnimation.Running
        assert dialog.windowOpacity() == 1
        dialog.reject()
        assert dialog.pos() == dragged_position, "user positioning must survive closing"
        with patch.object(motion, "enabled", return_value=False):
            dialog.show()
            app.processEvents()
            assert dialog.windowOpacity() == 1 and dialog.pos() == dragged_position
            assert dialog._entrance.state() != QAbstractAnimation.Running
            dialog.reject()

        for ratio in (1, 2):
            source = QPixmap(200 * ratio, 100 * ratio)
            source.setDevicePixelRatio(ratio)
            source.fill(QColor("red"))
            lifted, hotspot = motion.lifted_drag(source, QPoint(40, 30))
            assert lifted.devicePixelRatio() == ratio
            assert lifted.width() == 231 * ratio and lifted.height() == round(100 * ratio * 1.055) + 20 * ratio
            assert hotspot == QPoint(52, 42)
            image = lifted.toImage()
            assert image.pixelColor(0, 0).alpha() == 0
            assert image.pixelColor(50 * ratio, 50 * ratio).red() == 255
            assert source.width() == 200 * ratio
            with patch.object(motion, "enabled", return_value=False):
                plain, plain_hotspot = motion.lifted_drag(source, QPoint(40, 30))
                assert plain.cacheKey() == source.cacheKey() and plain_hotspot == QPoint(40, 30)

        settings = SettingsDialog(config.DEFAULT_SETTINGS, {})
        settings.show()
        app.processEvents()
        assert settings._entrance.duration() == 160
        assert settings.windowOpacity() == 1
        for frame in (0, 40, 80, 120):
            settings._entrance.setCurrentTime(frame)
            assert settings.windowOpacity() == 1
        original = settings.settings()
        nav = settings.nav
        QTest.mouseClick(nav.viewport(), Qt.LeftButton, pos=nav.visualItemRect(nav.item(1)).center())
        assert settings.stack.currentIndex() == 1
        assert settings.stack._fade.state() == QAbstractAnimation.Running
        assert settings.stack._effect.opacity() == 0.25 and settings.stack._fade.duration() == 260
        settings.stack._fade.setCurrentTime(80)
        opacity = settings.stack._effect.opacity()
        assert 0.25 < opacity < 1
        QTest.mouseClick(nav.viewport(), Qt.LeftButton, pos=nav.visualItemRect(nav.item(2)).center())
        assert settings.stack.currentIndex() == 2
        assert settings.stack._effect.opacity() >= opacity, "rapid switching must not flash from the initial opacity"
        QTest.qWait(350)
        assert settings.stack.graphicsEffect() is None
        assert settings.settings() == original
        # 程序跳转 / 键盘导航不播放动画。
        nav.setCurrentRow(3)
        assert settings.stack.graphicsEffect() is None
        with patch.object(motion, "enabled", return_value=False):
            QTest.mouseClick(nav.viewport(), Qt.LeftButton, pos=nav.visualItemRect(nav.item(0)).center())
            assert settings.stack.graphicsEffect() is None
        settings.reject()

        for side in ("left", "top"):
            sidebar = Sidebar([{"room_id": str(i), "uname": str(i), "live": False} for i in range(4)],
                              auto_compact=False)
            sidebar.resize(248, 900)
            folder = sidebar.create_folder("Apex")
            other = sidebar.create_folder("其他")
            sidebar.move_to_folder(["0", "1"], folder)
            sidebar.move_to_folder(["2", "3"], other)
            sidebar.set_side(side)
            if side == "top":
                sidebar.resize(1400, sidebar.height())
            sidebar.show()
            app.processEvents()
            button = sidebar._folder_buttons[folder]
            following = sidebar._folder_buttons[other]
            original_pos = following.pos()
            QTest.mouseClick(button, Qt.LeftButton)
            assert sidebar.get_folder(folder)["collapsed"]
            animation = sidebar.list_box._animations[following]
            assert animation.state() == QAbstractAnimation.Running
            assert animation.duration() == 280
            animation.setCurrentTime(75)
            intermediate = following.pos()
            assert intermediate != original_pos and intermediate != animation.endValue()
            QTest.mouseClick(button, Qt.LeftButton)
            assert not sidebar.get_folder(folder)["collapsed"]
            revealed = next(item for item in sidebar.items() if item.room["room_id"] == "0")
            entrance = sidebar.list_box._animations[revealed]
            delta = entrance.startValue() - entrance.endValue()
            assert (delta.x(), delta.y()) == ((24, 0) if side == "top" else (0, 24))
            QTest.qWait(350)
            assert following.pos() == original_pos
            with patch.object(motion, "enabled", return_value=False):
                QTest.mouseClick(button, Qt.LeftButton)
                assert sidebar.get_folder(folder)["collapsed"]
                assert all(anim.state() != QAbstractAnimation.Running for anim in sidebar.list_box._animations.values())
            old_positions = {item: QPoint(item.pos()) for item in sidebar.items()}
            for rid in ("new-a", "new-b"):
                assert sidebar.add_room({"room_id": rid, "uname": rid, "live": False})
            sidebar.move_to_folder(["new-a", "new-b"], other)
            final_positions = {item: QPoint(item.pos()) for item in sidebar.items()
                               if item.room["room_id"].startswith("new-")}
            app.processEvents()
            assert not sidebar._entering_room_ids
            for item, final_pos in final_positions.items():
                animation = sidebar.list_box._animations[item]
                assert animation.duration() == 220 and animation.endValue() == final_pos
                delta = animation.startValue() - final_pos
                assert (delta.x(), delta.y()) == ((24, 0) if side == "top" else (0, 24))
                animation.setCurrentTime(75)
                assert item.pos() != final_pos and item.pos() != animation.startValue()
            assert all(item.pos() == pos for item, pos in old_positions.items())
            QTest.qWait(260)
            assert all(item.pos() == pos for item, pos in final_positions.items())
            sidebar.toggle_folder(other)
            sidebar.add_room({"room_id": "hidden-new", "uname": "hidden", "live": False})
            sidebar.move_to_folder(["hidden-new"], other)
            app.processEvents()
            hidden = next(item for item in sidebar.items() if item.room["room_id"] == "hidden-new")
            assert hidden.isHidden() and hidden not in sidebar.list_box._animations
            removed = {"room_id": "removed-new", "uname": "removed", "live": False}
            sidebar.add_room(removed)
            sidebar.remove_room(removed)
            app.processEvents()
            assert not sidebar._entering_room_ids
            with patch.object(motion, "enabled", return_value=False):
                sidebar.add_room({"room_id": "instant-new", "uname": "instant", "live": False})
                app.processEvents()
                instant = next(item for item in sidebar.items() if item.room["room_id"] == "instant-new")
                assert instant not in sidebar.list_box._animations and not sidebar._card_entry_timer.isActive()
            sidebar.close()

        parent = QWidget()
        parent.resize(900, 600)
        parent.show()
        app.processEvents()
        notice = UpdateNotice(parent)
        offer = {"version": "0.3.1"}
        notice.show_offer(offer)
        assert notice._motion.state() == QAbstractAnimation.Running and notice._progress == 0
        assert notice._motion.duration() == 240
        assert notice.y() == parent.mapToGlobal(parent.rect().topLeft()).y() + 20 - 24
        notice._motion.setCurrentTime(80)
        assert 0 < notice._progress < 1
        QTest.qWait(200)
        assert notice._progress == 1
        anchored = notice.pos()
        notice.timer.timeout.emit()
        assert not notice.timer.isActive() and notice._leaving
        notice._motion.setCurrentTime(70)
        assert notice.y() < anchored.y()
        progress = notice._progress
        notice.show_offer(offer)
        assert not notice._leaving and notice._progress == progress
        QTest.qWait(350)
        assert notice.isVisible() and notice.pos() == anchored
        activated = []
        notice.activated.connect(lambda: activated.append(True))
        QTest.mouseClick(notice.action, Qt.LeftButton)
        assert activated == [True] and not notice.isVisible()
        assert notice._motion.state() != QAbstractAnimation.Running
        with patch.object(motion, "enabled", return_value=False):
            notice.show_offer(offer)
            assert notice._progress == 1 and notice._motion.state() != QAbstractAnimation.Running
            notice.dismiss()
            assert not notice.isVisible()
        notice.show_offer(offer)
        parent.hide()
        app.processEvents()
        assert not notice.isVisible() and notice._motion.state() != QAbstractAnimation.Running
        parent.close()
    sys.excepthook = original_hook
    assert not callback_errors, callback_errors
    print("PASS: dialog entrance/interruption, drag lift/HiDPI, settings, folder/new-card reveal, notice and reduced motion")


if __name__ == "__main__":
    main()
