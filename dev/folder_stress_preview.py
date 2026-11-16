"""Isolated synthetic Qt folder scale probe; no accounts, network, media or screenshots."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'dev')]
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget
from ddm import config, images, motion, theme
from ddm.responsiveness_probe import process_counters
from ddm.sidebar_thumbnail import NavThumb
from ddm.sidebar_widgets import Sidebar
from ddm.ui import ActionButton


MAX_RECORDS = 160
REPORT_LIMIT = 1024 * 1024
SCOPE = 'Synthetic Qt scale evidence; not live-user playback or performance improvement evidence'


def fixture(rooms, folders, copies):
    entries = [dict(room_id=f'fixture:room_{index:05d}', uname=f'合成主播 {index:05d}',
                    title='仅用于规模回归，无真实直播', live=index % 4 == 0)
               for index in range(rooms)]
    groups = [dict(id=f'fixture_folder_{index}', name=f'合成文件夹 {index + 1}', type='normal',
                   rooms=[room['room_id'] for room in entries[index::folders]], collapsed=True,
                   sort='custom') for index in range(folders)]
    groups += [dict(id=f'fixture_copy_{index}', name=f'合成在播副本 {index + 1}', type='smart',
                    collapsed=True, sort='custom', rooms=[],
                    rule=dict(status='live', sources=[], display='copy')) for index in range(copies)]
    return entries, groups


class FolderStressWindow(QWidget):
    def __init__(self, args, counters):
        super().__init__()
        self.args, self.counters = args, counters
        self.records, self.dropped, self.success = [], 0, None
        self.method_counts = {}
        self._measuring = False
        self._gaps = []
        self._previous = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._heartbeat)
        self.timer.start()
        started = time.perf_counter()
        before = self._baseline()
        rooms, folders = fixture(args.rooms, args.folders, args.copies)
        self.setWindowTitle('文件夹规模压力验收 · 合成数据')
        self.resize(1100, 800)
        self.setObjectName('SettingsPage')
        layout = QHBoxLayout(self)
        self.sidebar = Sidebar(rooms, auto_compact=False)
        self._hook_method(self.sidebar, 'resort')
        self._hook_method(self.sidebar.list_box, 'relayout')
        self._hook_method(self.sidebar, 'folder_entries')
        self._hook_method(self.sidebar, 'refresh_strip')
        self.sidebar.set_folders(folders)
        cover = QPixmap(640, 360)
        cover.fill(Qt.darkCyan)
        for item in self.sidebar.items():
            item.thumb.set_cover(cover)
        layout.addWidget(self.sidebar)
        panel = QVBoxLayout()
        title = QLabel('全部展开规模验收')
        title.setObjectName('SettingsTitle')
        panel.addWidget(title)
        hint = QLabel('使用真实 Qt 卡片与合成房间；不联网、不播放、不读取日常账号。\n'
                      '构造与各操作分别计时；监测本身有开销，不能替代真实用户现场。\n'
                      '可使用左侧真实文件夹按钮和筛选；右侧按钮记录展开、收起和滚动。')
        hint.setWordWrap(True)
        panel.addWidget(hint)
        controls = QHBoxLayout()
        for text, callback in (
            ('全部展开', lambda: self.sidebar.set_all_folders_collapsed(False)),
            ('全部折叠', lambda: self.sidebar.set_all_folders_collapsed(True)),
            ('切换在播过滤', lambda: self.sidebar.navigation.set_live_only(not self.sidebar.live_only)),
            ('滚至底部', self.scroll_bottom),
            ('记录当前状态', lambda: self.measure('snapshot', lambda: None))):
            button = ActionButton(text, self)
            button.clicked.connect(callback)
            controls.addWidget(button)
        panel.addLayout(controls)
        self.summary = QLabel('')
        self.summary.setWordWrap(True)
        panel.addWidget(self.summary)
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(MAX_RECORDS)
        panel.addWidget(self.log, 1)
        panel.addWidget(QLabel('结果目录：' + str(args.output)))
        layout.addLayout(panel, 1)
        self._install_operation_hooks()
        sync_ms = (time.perf_counter() - started) * 1000
        self.show()
        QTest.qWait(60)
        self._record('setup', started, sync_ms, before)

    def _heartbeat(self):
        now = time.perf_counter()
        self._gaps.append((now - self._previous) * 1000)
        self._gaps = self._gaps[-500:]
        self._previous = now

    def _baseline(self):
        return dict(counters=self.counters.copy(), methods={name: values.copy()
                    for name, values in self.method_counts.items()})

    def _hook_method(self, owner, name):
        original = getattr(owner, name)
        def timed(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                values = self.method_counts.setdefault(name, dict(calls=0, total_ms=0))
                values['calls'] += 1
                values['total_ms'] += (time.perf_counter() - started) * 1000
        setattr(owner, name, timed)

    def _install_operation_hooks(self):
        control = self.sidebar.folder_control
        bulk = control.set_all_folders_collapsed
        control.set_all_folders_collapsed = lambda collapsed: self.measure(
            'collapse_all' if collapsed else 'expand_all', lambda: bulk(collapsed))
        navigation = self.sidebar.navigation
        live = navigation.set_live_only
        navigation.set_live_only = lambda enabled: self.measure(
            'live_only' if enabled else 'all_statuses', lambda: live(enabled))

    def measure(self, name, operation):
        if self._measuring:
            return operation()
        self._measuring = True
        before = self._baseline()
        self._gaps.clear()
        self._previous = started = time.perf_counter()
        try:
            result = operation()
            sync_ms = (time.perf_counter() - started) * 1000
            QApplication.processEvents()
            QTest.qWait(60)
            self._record(name, started, sync_ms, before)
            return result
        finally:
            self._measuring = False

    def _record(self, name, started, sync_ms, before):
        settled_ms = (time.perf_counter() - started) * 1000
        sampled = time.perf_counter()
        items = self.sidebar.items()
        on_screen = [item for item in items if not item.thumb.visibleRegion().isEmpty()]
        dirty = [item for item in items if item.thumb._cover_dirty]
        methods = {key: dict(calls=value['calls'] - before['methods'].get(key, {}).get('calls', 0),
                            total_ms=round(value['total_ms'] - before['methods'].get(key, {}).get('total_ms', 0), 3))
                   for key, value in self.method_counts.items()}
        record = dict(stage=name, operation_ms=round(sync_ms, 3), settled_ms=round(settled_ms, 3),
                      max_event_gap_ms=round(max(self._gaps, default=sync_ms), 3),
                      counters=process_counters(), methods=methods,
                      render_calls={key: value - before['counters'].get(key, 0)
                                    for key, value in self.counters.items()},
                      widgets=len(self.sidebar.findChildren(QWidget)), rooms=len(items),
                      avatars=len(self.sidebar._head_strip._avatars), copies=len(self.sidebar._smart_cards),
                      active_players=sum(item.thumb._player is not None for item in items),
                      visible_cards=len(on_screen), dirty_covers=len(dirty),
                      dirty_visible_covers=sum(item.thumb._cover_dirty for item in on_screen),
                      live_only=self.sidebar.live_only,
                      collapsed_folders=sum(folder['collapsed'] for folder in self.sidebar.folders))
        record['sample_ms'] = round((time.perf_counter() - sampled) * 1000, 3)
        self.records.append(record)
        if len(self.records) > MAX_RECORDS:
            self.records.pop(0)
            self.dropped += 1
        self.summary.setText(f"{name}：同步 {sync_ms:.1f} ms；GUI 最大间隔 {record['max_event_gap_ms']:.1f} ms；"
                             f"屏内 {len(on_screen)}，待裁封面 {len(dirty)}，控件 {record['widgets']}")
        self.log.appendPlainText(json.dumps(record, ensure_ascii=False))
        self.write_report()
        print(json.dumps(record, ensure_ascii=False), flush=True)

    def write_report(self):
        report = dict(scope=SCOPE, rooms_requested=self.args.rooms, folders_requested=self.args.folders,
                      copies_requested=self.args.copies, success=self.success, dropped_records=self.dropped,
                      observation='Counters and settle waits add overhead; timings are descriptive, not pass thresholds',
                      stages=self.records)
        self.args.output.mkdir(parents=True, exist_ok=True)
        for name, text in (
            ('summary.json', json.dumps(report, ensure_ascii=False, indent=2)),
            ('events.jsonl', '\n'.join(json.dumps(row, ensure_ascii=False) for row in self.records) + '\n')):
            encoded = text.encode('utf-8')
            if len(encoded) > REPORT_LIMIT:
                raise RuntimeError('Stress report exceeded its bounded output size')
            (self.args.output / name).write_bytes(encoded)

    def scroll_bottom(self):
        bar = self.sidebar.scroll.verticalScrollBar()
        self.measure('scroll_bottom', lambda: bar.setValue(bar.maximum()))

    def smoke(self):
        self.sidebar.set_all_folders_collapsed(False)
        pending = [item for item in self.sidebar.items()
                   if item.thumb._cover_dirty and item.thumb.visibleRegion().isEmpty() and not item.filtered_out]
        assert pending, 'Scale fixture must include deferred offscreen covers'
        self.scroll_bottom()
        target = pending[-1]
        self.measure('scroll_to_deferred', lambda: self.sidebar.scroll.verticalScrollBar().setValue(target.y()))
        assert not target.thumb.visibleRegion().isEmpty(), 'Deferred card must enter the viewport'
        assert not target.thumb._cover_dirty, 'Deferred cover must render after scrolling into view'
        self.sidebar.set_all_folders_collapsed(True)
        assert not self.sidebar.visible_items()
        self.sidebar.navigation.set_live_only(True)
        self.sidebar.set_all_folders_collapsed(False)
        assert all(item.room.get('live') for item in self.sidebar.visible_items())
        assert len(self.sidebar.rooms()) == self.args.rooms
        assert all(row['active_players'] == 0 for row in self.records)
        self.success = True
        self.write_report()

    def closeEvent(self, event):
        self.timer.stop()
        self.write_report()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview-folder-stress', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--rooms', type=int, default=500)
    parser.add_argument('--folders', type=int, default=20)
    parser.add_argument('--copies', type=int, default=1)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'work' / 'folder-stress' /
                        datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S'))
    args = parser.parse_args()
    if not 100 <= args.rooms <= 5000 or not 1 <= args.folders <= args.rooms or not 0 <= args.copies <= 5:
        parser.error('rooms must be 100..5000, folders 1..rooms, copies 0..5')
    counters = dict(cover_calls=0, cover_renders=0, face_calls=0)
    render_cover, render_face = NavThumb._render_cover, NavThumb._render_face
    def cover(thumb):
        counters['cover_calls'] += 1
        before = thumb.cover.pixmap()
        key = before.cacheKey() if before is not None else None
        render_cover(thumb)
        after = thumb.cover.pixmap()
        if after is not None and not after.isNull() and after.cacheKey() != key:
            counters['cover_renders'] += 1
    def face(thumb):
        counters['face_calls'] += 1
        render_face(thumb)
    with tempfile.TemporaryDirectory(prefix='ddm-folder-stress-') as temporary, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'DATA_ROOT', temporary))
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')))
        stack.enter_context(patch.object(images, 'REPO', temporary))
        stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('Stress probe must stay offline')))
        stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        stack.enter_context(patch.object(NavThumb, '_render_cover', cover))
        stack.enter_context(patch.object(NavThumb, '_render_face', face))
        app = QApplication.instance() or QApplication([])
        app.setStyleSheet(theme.qss())
        window = FolderStressWindow(args, counters)
        try:
            if args.smoke:
                window.smoke()
                print('PASS: synthetic folder scale, offline and deferred cover restoration', flush=True)
                return 0
            return app.exec()
        except BaseException:
            window.success = False
            raise
        finally:
            window.close()


if __name__ == '__main__':
    raise SystemExit(main())
