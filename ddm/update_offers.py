"""Installed plugin update comparison and release-note selection."""
from . import online, plugin_updates


def plugin_update_offers(manager, offers):
    installed = {entry['id']: entry for entry in manager.catalog()} if manager else {}
    pending = plugin_updates.pending_versions(manager) if manager else {}
    result = []
    for offer in offers:
        existing = installed.get(offer['id'])
        if not existing or offer['id'] in pending or not offer.get('available'):
            continue
        try:
            newer = online.version_key(offer['version']) > online.version_key(existing['version'])
        except (ValueError, KeyError):
            newer = False
        if newer:
            result.append(offer)
    return result


def plugin_update_notes(manager, offers):
    return {offer['id']: '更新日志 · v' + offer['version'] + '\n' +
            (offer.get('notes') or '暂无更新日志')
            for offer in plugin_update_offers(manager, offers)}
