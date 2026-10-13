"""Local skin persistence, media playback, ownership and non-interference."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
platform._wmi_query = lambda *a: (_ for _ in ()).throw(OSError('Isolated skin test'))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import app as module, config, motion, theme
from ddm.dialogs import SettingsDialog
from ddm.plugins import PluginManager, read_manifest
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from ddm.skins import import_asset, validate_asset
from ddm.skin_settings import SkinSettings
from dev.selfcheck_tile_fullscreen import SilentPoller


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), 'Skin operation did not finish'


def main():
    app = QApplication([])
    module.StatusPoller = module.StatsPoller = SilentPoller
    with tempfile.TemporaryDirectory() as directory, patch.object(config, 'REPO', directory):
        folder = Path(directory)
        image = QImage(160, 90, QImage.Format_RGB32)
        image.fill(QColor('#E95C93'))
        source = folder / 'background.png'
        assert image.save(str(source))
        original = source.read_bytes()
        path = import_asset(source)
        assert (folder/path).read_bytes() == original and source.read_bytes() == original
        assert not list((folder/'utils/skins').glob('*.part'))
        try:
            import_asset(source, cancelled=lambda: True)
        except ValueError:
            pass
        else:
            raise AssertionError('Cancelled imports must not commit an asset')
        assert not list((folder/'utils/skins').glob('*.part'))
        bad = folder / 'bad.png'
        bad.write_text('invalid')
        try:
            validate_asset(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('Corrupt images must be rejected')
        with patch('PySide6.QtCore.QTimer.singleShot'):
            window = module.MainWindow([], [], layout_id='1x1',
                state={'plugins_enabled': [], 'settings': {'auto_update': False}})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.move(-10000, -10000)
        window.resize(1280, 800)
        window.show()
        QTest.qWait(20)
        layer = window.skin_controller.layer
        assert layer.player is None, 'Default/image skins must not create a video decoder'
        default_controls = SkinSettings(window.settings, window.skin_controller, window)
        assert default_controls.sidebar_toggle.isHidden(), 'Default background must hide the coverage switch'
        default_controls.deleteLater()
        hwnd = int(window.wall.tiles[0].video.winId())
        with patch.object(motion, 'enabled', return_value=False), patch.object(config, 'save') as save:
            window.set_skin({'skin_background': path, 'skin_mask': 35})
            assert save.call_args.args[0]['settings']['skin_background'] == path
            source.unlink()
            assert layer.image is not None and not layer.image.isNull()
            window.set_appearance('light')
            QTest.qWait(30)
            # The background must actually show through an empty native video surface.
            tile_image = window.wall.tiles[0].video.grab().toImage()
            color = tile_image.pixelColor(20, tile_image.height()//2)
            assert max(abs(a-b) for a, b in zip(color.getRgb()[:3], QColor('#F4F6F9').getRgb()[:3])) >= 10, 'Skin is hidden behind opaque UI panels'
            assert 'rgba(' not in window.sidebar.styleSheet(), 'Sidebar coverage must be opt-in'
            live_video = folder/'live.mp4'
            subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'color=c=blue:size=320x180:rate=15', '-t', '20', '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', str(live_video)], check=True)
            tile = window.wall.tiles[0]
            live = TilePlayer(tile.video, window, silent=True)
            window.players[tile] = live
            live.play(str(live_video))
            tile.set_video_active(True)
            wait_for(lambda: live.player.get_time() > 0)
            live_time = live.player.get_time()
            with patch('PySide6.QtCore.QTimer.singleShot'), patch('ddm.online.load_plugin_cache', return_value=None):
                dialog = SettingsDialog(window.settings, window.shortcuts, window)
            dialog.nav.setCurrentRow(1)
            dialog.setAttribute(Qt.WA_ShowWithoutActivating)
            dialog.move(-10000, -10000)
            dialog.show()
            controls = dialog.appearance_page.skin_settings
            assert controls.choose.isEnabled()
            assert not controls.sidebar_toggle.isHidden() and not controls.sidebar_toggle.isChecked()
            sidebar_point = QPoint(window.sidebar.width()//2, window.sidebar.height()-8)
            plain_color = window.sidebar.grab().toImage().pixelColor(sidebar_point)
            controls.sidebar_toggle.setChecked(True)
            QTest.qWait(30)
            covered_color = window.sidebar.grab().toImage().pixelColor(sidebar_point)
            assert 'rgba(' in window.sidebar.styleSheet() and covered_color != plain_color
            assert window.settings['skin_sidebar'] and save.call_args.args[0]['settings']['skin_sidebar']
            assert window.settings['skin_background'] == path and layer.mask == 35
            window.set_appearance('dark')
            assert 'rgba(' in window.sidebar.styleSheet()
            window.set_appearance('light')
            controls.sidebar_toggle.setChecked(False)
            QTest.qWait(30)
            assert window.sidebar.grab().toImage().pixelColor(sidebar_point) == plain_color
            assert 'rgba(' not in window.sidebar.styleSheet()
            controls.sidebar_toggle.setChecked(True)
            next_source = folder / 'next.png'
            image.fill(QColor('#426CDB'))
            image.save(str(next_source))
            controls.import_file(str(next_source))
            wait_for(lambda: controls.job is None)
            custom = controls.path
            assert window.settings['skin_background'] == custom
            assert layer.image.pixelColor(0, 0) == QColor('#426CDB')
            controls.mask_slider.setValue(50)
            assert layer.mask == 50 and window.settings['skin_mask'] == 50
            # Install through the existing ZIP API; it only executes after load.
            archive = folder / 'skin.zip'
            manifest = dict(id='test_skin', name='Test skin', description='Offline fixture', version='1.0',
                skin={'background': 'assets/background.png', 'mask': 20})
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('test_skin/plugin.json', json.dumps(manifest))
                package.writestr('test_skin/plugin.py', 'from ddm.plugins import Plugin\nplugin = Plugin()\n')
                package.writestr('test_skin/assets/background.png', original)
            manager = PluginManager(window, str(folder/'plugins'), enabled=[])
            manager.install_zip(str(archive))
            assert manager.active_skin() is None
            manager.load()
            window.plugins = manager
            window.refresh_skin()
            assert window.skin_controller.override['owner'] == 'test_skin'
            assert not controls.choose.isEnabled() and not controls.mask_slider.isEnabled()
            assert controls.sidebar_toggle.isHidden() and not controls.sidebar_toggle.isEnabled()
            assert controls.values()['skin_sidebar'], 'Plugin ownership must preserve the user preference'
            assert controls.mask_slider.value() == 20 and controls.values()['skin_mask'] == 50
            assert layer.mask == 20 and layer.image.pixelColor(0, 0) == QColor('#E95C93')
            window.set_skin({'skin_background': '', 'skin_mask': 0})
            assert window.settings['skin_background'] == custom
            manager.enabled.clear()
            window.refresh_skin()
            assert controls.choose.isEnabled() and layer.mask == 50
            assert controls.mask_slider.value() == 50
            assert not controls.sidebar_toggle.isHidden() and controls.sidebar_toggle.isChecked()
            assert 'rgba(' in window.sidebar.styleSheet()
            assert layer.image.pixelColor(0, 0) == QColor('#426CDB')
            manager.enabled.add('test_skin')
            window.refresh_skin()
            # Removing the active package must restore the saved custom background.
            manager.remove_plugin('test_skin')
            assert window.skin_controller.override is None and controls.choose.isEnabled()
            assert layer.image.pixelColor(0, 0) == QColor('#426CDB')
            # Reject a package asset that escapes its installed directory.
            escaping = folder / 'escape'
            escaping.mkdir()
            manifest.update(id='escape', skin={'background': '../background.png'})
            (escaping/'plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
            try:
                read_manifest(str(escaping), 'escape')
            except ValueError:
                pass
            else:
                raise AssertionError('Escaping skin asset paths must be rejected')
            assert int(window.wall.tiles[0].video.winId()) == hwnd
            output = ROOT/'work/appearance-delivery'
            output.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(output/'skin-light.png'))
            dialog.grab().save(str(output/'skin-settings.png'))
            controls.reset()
            assert controls.sidebar_toggle.isHidden() and not controls.sidebar_toggle.isChecked()
            assert not window.settings['skin_sidebar'] and 'rgba(' not in window.sidebar.styleSheet()
            window.set_skin({'skin_background': custom, 'skin_mask': 50, 'skin_sidebar': True})
            dialog.reject()
            video = folder/'background.mp4'
            subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'testsrc2=size=320x180:rate=15', '-f', 'lavfi',
                '-i', 'sine=frequency=440:sample_rate=44100', '-t', '1', '-c:v', 'libx264', '-c:a', 'aac',
                '-pix_fmt', 'yuv420p', str(video)], check=True)
            video_path = import_asset(video)
            window.set_skin({'skin_background': video_path, 'skin_mask': 35})
            wait_for(lambda: layer.image is not None)
            assert layer.player.audioOutput() is None and layer.player.loops() == QMediaPlayer.Infinite
            assert layer.player.playbackState() == QMediaPlayer.PlayingState
            QTest.qWait(1400)
            assert layer.player.playbackState() == QMediaPlayer.PlayingState, 'Background must loop'
            assert live.player.get_time() > live_time and live.player.is_playing(), 'Skin changes must leave live playback running'
            assert window.players[tile] is live and int(tile.video.winId()) == hwnd
            window.hide()
            QTest.qWait(30)
            assert layer.player.playbackState() == QMediaPlayer.PausedState
            window.show()
            wait_for(lambda: layer.player.playbackState() == QMediaPlayer.PlayingState)
            invalid_video = folder/'invalid.mp4'
            invalid_video.write_bytes(b'not a video')
            window.set_skin({'skin_background': import_asset(invalid_video), 'skin_mask': 35})
            wait_for(lambda: bool(window.skin_controller.error))
            assert layer.image is None and not layer.player.isPlaying()
            window.set_skin({'skin_background': window.settings['skin_background'], 'skin_mask': 40})
            assert window.skin_controller.error, 'Changing the mask must not hide a decoder error'
            window.set_skin({'skin_background': '', 'skin_mask': 35})
            assert layer.player.playbackState() == QMediaPlayer.StoppedState
            assert not theme._skin_active and 'rgba(' not in window.sidebar.styleSheet()
            missing = 'utils/skins/missing.png'
            window.set_skin({'skin_background': missing, 'skin_mask': 35})
            assert window.skin_controller.error and layer.image is None
            window.set_skin({'skin_background': '', 'skin_mask': 35})
            window.close()
        # Saved relative asset paths survive window reconstruction.
        with patch.object(config, 'CONFIG_PATH', str(folder/'saved-state.json')), patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
            config.save({'version': config.STATE_VERSION, 'plugins_enabled': [], 'settings': {'skin_background': custom, 'skin_mask': 50, 'skin_sidebar': True, 'auto_update': False}})
            persisted = config.load()
        with patch('PySide6.QtCore.QTimer.singleShot'):
            restored = module.MainWindow([], [], state=persisted)
        assert restored.skin_controller.layer.image.pixelColor(0, 0) == QColor('#426CDB')
        assert restored.settings['skin_sidebar'] and 'rgba(' in restored.sidebar.styleSheet()
        restored.close()
        theme.set_skin_active(False)
    print('PASS: copied/persisted image, opt-in sidebar coverage and conditional controls, asynchronous import, translucent panels, plugin install/override/disable/remove, path validation, muted looping video, pause/resume and stable video HWND')


if __name__ == '__main__':
    main()
