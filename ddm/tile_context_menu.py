"""Tile context menu; mutable state and Qt ownership stay with Tile."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QMenu, QSlider, QVBoxLayout, QWidget, QWidgetAction


class TileContextMenu:
    def __init__(self, host):
        self.host = host

    def build_menu(self, *, menu_type) -> QMenu:
        QMenu = menu_type
        """右键菜单：音量滑条 + 画质 + 声道 + 常规操作。"""
        host = self.host
        menu = QMenu(host)

        # 音量（菜单里嵌滑条）
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(10, 6, 10, 4)
        holder_layout.setSpacing(4)
        volume_label = QLabel(f"音量 {host.volume}")
        volume_label.setObjectName("AppSubtitle")
        holder_layout.addWidget(volume_label)
        slider = QSlider(Qt.Horizontal, holder)
        slider.setRange(0, 100)
        slider.setValue(host.volume)
        slider.setFixedWidth(170)
        slider.valueChanged.connect(lambda value: (
            volume_label.setText(f"音量 {value}"), host.set_volume(value)))
        holder_layout.addWidget(slider)
        wrapper = QWidgetAction(menu)
        wrapper.setDefaultWidget(holder)
        wrapper.setData('volume')
        menu.addAction(wrapper)
        menu.addSeparator()

        quality_menu = menu.addMenu("画质")
        quality_menu.menuAction().setData('quality')
        for name, value in host._quality_choices():
            action = quality_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(value == host.quality)
            action.triggered.connect(lambda _checked=False, v=value: host.set_quality(v))

        menu.addAction("当前窗口编解码设置…", host.codecSettingsRequested.emit).setData('codec')
        info = menu.addAction("直播流信息…", lambda: QTimer.singleShot(0, host, host.streamInfoRequested.emit))
        info.setEnabled(bool(host.room.get('room_id')))
        info.setData('stream_info')

        # 声道：0 默认、3 只左、4 只右、2 反向立体声、5 杜比。
        # 只有「只左 / 只右」能把两路画面分到两只耳朵，其余是原程序的音效档。
        audio_menu = menu.addMenu("声道")
        audio_menu.menuAction().setData('audio_channel')
        for name, value in (("默认（跟随片源）", 0), ("只播左声道", 3),
                            ("只播右声道", 4), ("反向立体声", 2), ("杜比矩阵下混（多声道源）", 5)):
            action = audio_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(value == host.audio_channel)
            action.triggered.connect(lambda _checked=False, v=value: host.set_audio_channel(v))
        menu.addSeparator()
        menu.addAction("取消静音" if host.muted else "静音", host._toggle_mute).setData('mute')
        menu.addAction("弹幕观看设置…", lambda: QTimer.singleShot(0, host,
            lambda: host.danmaku_settings_menu.open_at(
                host.danmaku_button, host.video_danmaku.settings))).setData('danmaku_settings')
        menu.addAction("刷新重连", lambda: host.reloadRequested.emit(host.room)).setData('reload')
        menu.addAction("全屏查看", lambda: host.fullscreenRequested.emit(host)).setData('fullscreen')
        if host.plugin_actions:
            # 插件加的一项占一行；组与组之间用分隔线断开，免得和本体的项混在一起
            menu.addSeparator()
            for label, callback in host.plugin_actions:
                menu.addAction(label, callback).setData('plugins')
        menu.addSeparator()
        if not (host.property("pictureInPicture") or host.property("fullscreen")):
            menu.addAction("切换为弹幕", host.paneEditRequested.emit).setData('switch_danmaku')
        menu.addAction("关闭这一路", lambda: host.closeRequested.emit(host.room)).setData('close')
        from .tile_menu import arrange_menu
        arrange_menu(menu, host._video_danmaku_global_settings.get('tile_context_menu'))
        return menu
