"""Fixed host operations executed in the main Qt thread by DiagnosticEndpoint."""
import time

from . import layouts
from .settings_pages import PAGE_INDEX, SETTINGS_PAGES


def wall_state(host):
    slots = []
    for index, tile in enumerate(host.wall.tiles, 1):
        player = host.players.get(tile)
        slots.append(dict(slot=index, occupied=bool(tile.room.get('room_id')),
                          visible=tile.isVisible(), state=getattr(player, 'state', 'idle'),
                          paused=bool(tile.paused or getattr(player, 'paused', False))))
    return dict(layout=host.wall.layout_id, orientation=host.orientation, slots=slots,
                playing=sum(row['state'] == 'playing' and not row['paused'] for row in slots),
                picture_in_picture=host.picture_in_picture.active,
                last_layout_change=host.last_layout_change)


def settings_state(host):
    dialog = getattr(host, '_local_settings_dialog', None)
    if dialog is not None:
        index = dialog.nav.currentRow()
        return dict(window='local', visible=dialog.isVisible() and not dialog.isMinimized(),
                    page=SETTINGS_PAGES[index][0] if 0 <= index < len(SETTINGS_PAGES) else None)
    client = getattr(host, '_settings_process', None)
    if client is not None and (client.visible or client.pending is not None):
        return dict(window='worker', visible=not client.occlusion.isEmpty(), page=client.current_page)
    return dict(window='closed', visible=False, page=None)


def dispatch(host, request):
    operation = request.get('action')
    fields = {'state': (), 'layouts': (), 'set_layout': ('layout',),
              'settings_state': (), 'settings_pages': (), 'settings_open': ('page', 'entry'),
              'settings_close': (), 'open_pip': ('slots',), 'close_pip': (), 'remove': ('slot',)}
    if (type(operation) is not str or operation not in fields
            or request.keys() != {'protocol', 'mode', 'action', *fields[operation]}):
        raise ValueError('invalid-request')
    if operation == 'state':
        return wall_state(host)
    if operation == 'settings_state':
        return settings_state(host)
    if operation == 'settings_pages':
        return dict(pages=[dict(id=key, label=label) for key, label in SETTINGS_PAGES])
    presets = host.layout_presets
    if operation == 'layouts':
        return dict(builtin=list(layouts.BY_ID), saved=list(presets.items))
    if host._closing or host._fullscreen_tile is not None:
        raise ValueError('host-busy')
    if operation == 'settings_open':
        from PySide6.QtCore import QTimer
        page, entry = request['page'], request['entry']
        if type(page) is not str or page not in PAGE_INDEX:
            raise ValueError('unknown-settings-page')
        if entry not in ('sidebar', 'monitor') or (entry == 'monitor' and page != 'streamer_defaults'):
            raise ValueError('invalid-settings-entry')
        # The monitor entry can run a local dialog.exec(). Reply before entering its event loop.
        def open_page():
            if not host._closing:
                if entry == 'monitor':
                    host.sidebar.navigation.monitor_menu.settingsRequested.emit()
                else:
                    host._open_sidebar_settings(page)
        QTimer.singleShot(0, host, open_page)
        return dict(accepted=True)
    if operation == 'settings_close':
        dialog = getattr(host, '_local_settings_dialog', None)
        client = getattr(host, '_settings_process', None)
        if dialog is not None:
            dialog.close()
        elif client is not None:
            client.dismiss()
        return dict(accepted=True)
    started = time.perf_counter()
    pip = host.picture_in_picture
    if operation == 'set_layout':
        key = request['layout']
        if type(key) is not str or key not in layouts.BY_ID and key not in presets.items:
            raise ValueError('unknown-layout')
        if key in layouts.BY_ID:
            presets.select_builtin(key)
        else:
            presets.apply(key)
    elif operation == 'open_pip':
        slots = request['slots']
        if (not isinstance(slots, list) or not slots
                or any(type(slot) is not int or not 1 <= slot <= len(host.wall.tiles) for slot in slots)
                or len(set(slots)) != len(slots)
                or not pip.start([slot - 1 for slot in slots])):
            raise ValueError('invalid-pip-slots')
    elif operation == 'close_pip':
        if pip.active:
            pip.restore()
    elif operation == 'remove':
        slot = request['slot']
        if type(slot) is not int or not 1 <= slot <= len(host.wall.tiles):
            raise ValueError('invalid-slot')
        tile = host.wall.tiles[slot - 1]
        if not tile.room.get('room_id') or pip.active:
            raise ValueError('slot-unavailable')
        if tile in host.recorder.sessions or tile in host._pending_capture:
            raise ValueError('slot-recording')
        removal = host.wall_removal
        opened = removal.menu is None or not removal.menu.isVisible()
        if opened:
            removal.toggle_menu()
        try:
            removal.sync()
            removal.select('none')
            removal.toggle_selection(tile, True)
            if not removal.remove_selected():
                raise ValueError('wall-changed')
        finally:
            if opened:
                removal.menu.hide()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return dict(sync_ms=elapsed_ms, state=wall_state(host))
