"""Local-only manual SC acceptance window, using the production wall and store."""
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('DDM_QTQUICK_DANMAKU', '1')
if hasattr(platform, '_wmi_query'):
    platform._wmi_query = lambda *args: (_ for _ in ()).throw(OSError('SC simulator'))

from ddm import config

_data = tempfile.TemporaryDirectory(prefix='ddm-sc-simulator-')
config.DATA_ROOT = _data.name
config.CONFIG_PATH = str(Path(_data.name) / 'utils/config.json')

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDockWidget,
                              QFormLayout, QLabel, QLineEdit, QMainWindow,
                              QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QWidget)
from ddm import theme
from ddm.images import _cache_path
from ddm.super_chat import SuperChatStore
from ddm.widgets import WallGrid


class ScSimulator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('虚拟 SC 测试 · 头像与布局')
        self.resize(1240, 760)
        self.store = SuperChatStore()
        self.face_url = 'https://example.invalid/sc-simulator-avatar.png'
        face = QPixmap(96, 96)
        face.fill(QColor('#167da8'))
        painter = QPainter(face)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('white'))
        painter.drawEllipse(32, 16, 32, 32)
        painter.drawEllipse(18, 54, 60, 60)
        painter.end()
        path = Path(_cache_path(self.face_url, 'sc-avatars'))
        path.parent.mkdir(parents=True, exist_ok=True)
        face.save(str(path))
        self.sc_settings = dict(config.DEFAULT_SETTINGS, video_danmaku_size=24,
                                video_danmaku_scale=False)
        self.wall = WallGrid([{'room_id': '1', 'uname': '虚拟直播间', 'live': True}],
                             layout_id='dm_pair')
        self.setCentralWidget(self.wall)
        self.tile = self.wall.tiles[0]
        self.tile.video.setStyleSheet('background: qlineargradient(x1:0,y1:0,x2:1,y2:1, '
                                     'stop:0 #164e63, stop:1 #312e81);')
        self.tile.set_video_active(True)
        self.tile.set_live(True, '本机模拟')
        self.tile.set_recording_available(False)
        self.wall.danmaku.set_status('本机模拟')
        self.wall.danmaku.set_placeholder('虚拟弹幕会持续出现；醒目留言显示在弹幕栏右上角。')
        self.tile.danmaku_button.setChecked(True)
        self.tile.video_danmaku.apply_settings(self.sc_settings)

        controls = QWidget()
        controls.setMinimumWidth(260)
        form = QFormLayout(controls)
        hint = QLabel('本机模拟，不登录、不联网、不发送。\n相同编号更新内容；修改编号可添加多条。')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.number = QSpinBox()
        self.number.setRange(1, 999999)
        self.name = QLineEdit('虚拟用户')
        self.price = QSpinBox()
        self.price.setRange(1, 99999)
        self.price.setPrefix('¥ ')
        self.price.setValue(30)
        self.duration = QSpinBox()
        self.duration.setRange(1, 3600)
        self.duration.setSuffix(' 秒')
        self.duration.setValue(30)
        self.message = QPlainTextEdit('这是一条虚拟醒目留言，可以修改内容后再次添加。')
        self.message.setMaximumHeight(100)
        self.color = QComboBox()
        for label, value in (('金色', '#ffdd00'), ('深蓝', '#1f2a44'), ('粉色', '#ff88aa')):
            self.color.addItem(label, value)
        for label, widget in (('编号', self.number), ('用户名', self.name), ('金额', self.price),
                              ('有效期', self.duration), ('正文', self.message), ('卡片颜色', self.color)):
            form.addRow(label, widget)
        self.add_button = QPushButton('添加 / 更新')
        self.add_button.clicked.connect(self.add_chat)
        self.delete_button = QPushButton('删除当前编号')
        self.delete_button.clicked.connect(self.delete_chat)
        self.clear_button = QPushButton('清空全部')
        self.clear_button.clicked.connect(self.clear_chats)
        for button in (self.add_button, self.delete_button, self.clear_button):
            button.setObjectName('IconButton')
            form.addRow(button)
        self.add_button.setObjectName('PrimaryButton')
        self.visible_box = QCheckBox('显示滚动弹幕')
        self.visible_box.setChecked(True)
        self.visible_box.toggled.connect(self.tile.danmaku_button.setChecked)
        self.tile.danmaku_button.toggled.connect(self.visible_box.setChecked)
        form.addRow(self.visible_box)
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(80)
        self.opacity.valueChanged.connect(self.change_opacity)
        form.addRow('SC 不透明度', self.opacity)
        self.collapse_delay = QSpinBox()
        self.collapse_delay.setRange(1, 60)
        self.collapse_delay.setSuffix(' 秒')
        self.collapse_delay.setValue(7)
        self.collapse_delay.valueChanged.connect(lambda value: self.change_sc_settings({'super_chat_collapse_delay': value}))
        form.addRow('SC 自动折叠', self.collapse_delay)
        self.sc_scale = QSlider(Qt.Horizontal)
        self.sc_scale.setRange(75, 200)
        self.sc_scale.setValue(100)
        self.sc_scale.valueChanged.connect(lambda value: self.change_sc_settings({'super_chat_scale': value}))
        form.addRow('SC 大小', self.sc_scale)
        reset_position = QPushButton('恢复 SC 位置')
        reset_position.clicked.connect(lambda: self.change_sc_settings({'super_chat_position': None}))
        form.addRow(reset_position)
        self.sc_enabled = QCheckBox('显示醒目留言（SC）')
        self.sc_enabled.setChecked(True)
        self.sc_enabled.toggled.connect(self.change_sc_enabled)
        form.addRow(self.sc_enabled)
        self.layout_choice = QComboBox()
        self.layout_choice.addItem('画面＋弹幕栏', 'dm_pair')
        self.layout_choice.addItem('仅画面', '1x1')
        self.layout_choice.addItem('主画面＋2 小＋弹幕', 'dm_main3')
        self.layout_choice.currentIndexChanged.connect(
            self.change_layout)
        form.addRow('布局', self.layout_choice)
        self.tile.video_danmaku.superChatSettingsChanged.connect(self.change_sc_settings)
        self.tile.video_danmaku.superChatDismissed.connect(self.dismiss_chat)
        self.wall.danmaku.superChatDismissed.connect(self.dismiss_chat)
        appearance = QComboBox()
        appearance.addItem('深色', 'dark')
        appearance.addItem('浅色', 'light')
        appearance.currentIndexChanged.connect(lambda: self.change_theme(appearance.currentData()))
        form.addRow('界面', appearance)
        fullscreen = QPushButton('全屏预览（Esc 返回）')
        fullscreen.setObjectName('IconButton')
        fullscreen.setCheckable(True)
        fullscreen.toggled.connect(lambda checked: self.showFullScreen() if checked else self.showNormal())
        QShortcut(QKeySequence('Escape'), self, activated=lambda: fullscreen.setChecked(False))
        form.addRow(fullscreen)
        self.status = QLabel()
        form.addRow(self.status)
        dock = QDockWidget('虚拟留言控制台', self)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(controls)
        dock.setWidget(scroll)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.add_chat()

    def add_chat(self):
        now = int(time.time())
        self.store.upsert({'id': str(self.number.value()), 'uname': self.name.text(),
            'face': self.face_url,
            'price': self.price.value(), 'message': self.message.toPlainText(),
            'start_time': now, 'end_time': now + self.duration.value(),
            'background_color': self.color.currentData()})
        self.publish()

    def delete_chat(self):
        self.store.remove([str(self.number.value())])
        self.number.setValue(self.number.value() + 1)
        self.publish()

    def clear_chats(self):
        self.store = SuperChatStore()
        self.publish()

    def publish(self):
        chats = self.store.active()
        self.wall.danmaku.apply_super_chat_settings(self.sc_settings)
        self.wall.danmaku.set_super_chats(chats)
        self.tile.video_danmaku.set_super_chats(chats)
        self.status.setText(f'活动留言：{len(chats)} 条')

    def dismiss_chat(self, chat_id):
        self.store.dismiss(chat_id)
        self.publish()

    def tick(self):
        self.store.expire()
        self.publish()
        event = {'kind': 'danmaku', 'uname': '虚拟观众', 'text': '普通滚动弹幕共存测试'}
        self.wall.danmaku.add_event(event)
        self.tile.video_danmaku.add_event(event)

    def change_sc_settings(self, values):
        self.sc_settings.update(values)
        for control, key in ((self.sc_scale, 'super_chat_scale'),
                             (self.collapse_delay, 'super_chat_collapse_delay')):
            control.blockSignals(True)
            control.setValue(self.sc_settings[key])
            control.blockSignals(False)
        self.tile.video_danmaku.apply_settings(self.sc_settings)
        self.publish()

    def change_opacity(self, value):
        self.sc_settings['super_chat_opacity'] = value
        self.tile.video_danmaku.apply_settings(self.sc_settings)
        self.publish()

    def change_sc_enabled(self, checked):
        self.sc_settings['super_chat_enabled'] = checked
        self.tile.video_danmaku.apply_settings(self.sc_settings)
        self.publish()

    def change_layout(self):
        self.wall.set_layout(self.layout_choice.currentData())
        self.visible_box.setText('显示滚动弹幕' if self.wall.has_danmaku else '显示滚动弹幕与 SC')

    def change_theme(self, value):
        theme.apply(value)
        QApplication.instance().setStyleSheet(theme.qss())

    def closeEvent(self, event):
        self.timer.stop()
        self.tile.video_danmaku.clear()
        layer = self.wall._quick_danmaku_layer
        if layer is not None:
            layer.window.close()
        super().closeEvent(event)


def main():
    def offline(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto', 'socket.sendmsg'):
            raise RuntimeError('The SC simulator is offline')
    sys.addaudithook(offline)
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = ScSimulator()
    result = None
    if '--smoke' in sys.argv:
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.move(-20000, -20000)
        def finish():
            nonlocal result
            overlay = window.tile.video_danmaku
            point = overlay.super_chat_overlay.card_rects()[0].center() - overlay.super_chat_overlay._content_origin
            image = overlay.super_chat_overlay.render_image()
            scale = image.devicePixelRatio()
            result = {'passed': bool(window.store.active()) and
                window.wall.danmaku.super_chats.isVisible() and
                overlay.super_chat_overlay.isHidden() and
                overlay.super_chat_overlay.mask().contains(point.toPoint()) and
                image.pixelColor(round(point.x() * scale), round(point.y() * scale)).alpha() > 0,
                'renderer': 'Quick' if overlay._quick_layer is not None else 'QPainter'}
            window.close()
        QTimer.singleShot(1500, finish)
    window.show()
    code = app.exec()
    app.shutdown()
    if result is not None:
        output = ROOT / 'work/test-artifacts/sc-simulator/smoke.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
