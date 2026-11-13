"""Local image/video backgrounds, independent of live-stream players."""
import os
from copy import deepcopy
import sys
from pathlib import Path
import time
import uuid

from PySide6.QtCore import QEvent, QObject, QRunnable, QRectF, Qt, QThread, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QPainter
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QWidget

from . import config, theme

from .skin_assets import (IMAGES, VIDEOS, validate_asset, import_asset, AssetImport)


def plugin_skin(plugin, folder):
    """Resolve a declarative skin inside its own installed plugin folder."""
    spec = plugin.skin
    if not isinstance(spec, dict):
        raise ValueError('皮肤必须是对象')
    version = spec.get('version', 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError('不支持的皮肤接口版本')
    if not isinstance(spec.get('background', '' if version == 2 else None), str):
        raise ValueError('皮肤需要 background 相对路径')
    root = Path(folder).resolve()
    relative = Path(spec.get('background') or '')
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root):
        raise ValueError('皮肤背景必须位于插件包内')
    if (version == 1 or spec.get('background')) and path.suffix.lower() not in IMAGES | VIDEOS:
        raise ValueError('皮肤背景格式不受支持')
    mask = spec.get('mask', 35)
    if type(mask) is not int or not 0 <= mask <= 100:
        raise ValueError('皮肤 mask 必须是 0–100 的整数')
    from .skin_parts import validate_parts
    parts = validate_parts(spec.get('parts', {}), root)
    return {'path': str(path) if spec.get('background') else '', 'mask': mask,
            'owner': plugin.context.name, 'name': plugin.name, 'version': version, 'parts': parts}


from .skin_background import (_FrameImage, BackgroundLayer)


class SkinController(QObject):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.layer = BackgroundLayer(window.centralWidget(), window)
        self.override = None
        self.error = ''
        self.layer.failed.connect(self._failed)
        sidebar = window.sidebar
        for attribute, key in (('refresh_button', 'refresh'),
                ('appearance_button', 'appearance'), ('toggle_button', 'sidebar_toggle'),
                ('settings_button', 'settings'), ('layout_button', 'layout'),
                ('import_button', 'import'), ('add_button', 'add')):
            button = getattr(sidebar, attribute)
            button.setProperty('skinPart', 'buttons.' + key)
            button.setProperty('skinIconOnly', key in ('sort', 'refresh', 'appearance', 'sidebar_toggle'))

    def refresh(self):
        if getattr(self.window, '_closing', False):
            return
        manager = getattr(self.window, 'plugins', None)
        self.override = manager.active_skin() if manager is not None else None
        settings = self.window.settings
        owner = self.override['owner'] if self.override else ''
        # Persist ownership so restarting does not discard later personal edits.
        if owner != settings.get('skin_package_owner', ''):
            settings['skin_package_owner'] = owner
            if self.override and self.override['version'] == 2:
                if self.override['path']:
                    for key in ('skin_background_override', 'skin_mask_override', 'skin_sidebar_override'):
                        settings[key] = False
                personal = deepcopy(settings.get('skin_parts', {}))
                for part in ('settings', 'layout_menu'):
                    package = self.override['parts']
                    if part not in package and not (part == 'layout_menu' and 'menus' in package):
                        continue
                    values = personal.get(part, {})
                    values.pop('builtin', None)
                    for entry in (values, values.get('dark', {}), values.get('light', {})):
                        entry.pop('image', None)
                settings['skin_parts'] = personal
        from .skin_parts import configure, validate_parts
        try:
            personal = validate_parts(settings.get('skin_parts', {}), Path(config.data_root()) / 'utils' / 'skins')
        except (OSError, ValueError) as error:
            personal = {}
            print(f'[皮肤] 个人分区配置无效：{error}', file=sys.stderr)
        configure(self.override.get('parts', {}) if self.override else {}, personal)
        use_package = self.override is not None and (self.override['version'] == 1
            or (bool(self.override['path']) and not settings.get('skin_background_override', False)))
        path = self.override['path'] if use_package else settings.get('skin_background', '')
        if path and not use_package:
            root = Path(config.data_root()).resolve()
            path = (root / path).resolve()
            if not path.is_relative_to(root / 'utils' / 'skins'):
                path = ''
        self.error = ''
        try:
            mask = max(0, min(100, int(settings.get('skin_mask', 35))))
        except (TypeError, ValueError):
            mask = 35
        legacy = self.override is not None and self.override['version'] == 1
        self.layer.mask = self.override['mask'] if use_package and (legacy or not settings.get('skin_mask_override')) else mask
        if not settings.get('skin_mask_enabled', True) and not legacy:
            self.layer.mask = 0
        theme.set_skin_active(bool(path), True)
        self.layer.load(str(path) if path else '', video_enabled=bool(settings.get('skin_video_enabled', True)))
        self.layer._visibility()
        self.error = self.layer.error
        self.layer.update()
        self.changed.emit()

    def _failed(self, message):
        self.error = message
        self.changed.emit()

    def stop(self):
        self.layer._generation += 1
        if self.layer.player is not None:
            self.layer.player.stop()
            self.layer.player.setSource(QUrl())
        self.layer._frame_pool.waitForDone()
        for job in self.window.findChildren(AssetImport):
            job.requestInterruption()
            job.wait()
