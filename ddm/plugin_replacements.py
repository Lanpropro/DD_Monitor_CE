"""Migration from a bundled plugin to independently installed providers."""
from copy import deepcopy
from pathlib import Path
from .plugin_manifest import PLUGIN_INVENTORY, RETIRED_BUNDLED_PLUGINS


def inherit_settings(manager, plugin_id, manifest, *, enable_from_legacy=False):
    legacy = (manifest or {}).get('replaces')
    if not legacy or plugin_id in manager.plugin_settings:
        return
    previous = manager.plugin_settings.get(legacy) or {}
    manager.plugin_settings[plugin_id] = {
        key: deepcopy(previous[key]) for key in manifest.get('inherit_settings', []) if key in previous}
    if enable_from_legacy and manager.enabled is not None and legacy in manager.enabled:
        manager.enabled.add(plugin_id)


def prepare(manager, manifest_reader):
    manifests = {}
    entries = []
    for folder in sorted(Path(manager.plugins_dir).iterdir()):
        if folder.name.startswith(('.', '_')) or folder.name in RETIRED_BUNDLED_PLUGINS:
            continue
        try:
            if not (folder / 'plugin.py').is_file():
                continue
        except OSError as error:
            manager.skipped.append((folder.name, f'无法读取插件目录：{error}'))
            continue
        entries.append(folder.name)
        try:
            manifests[folder.name] = manifest_reader(str(folder), folder.name) or {}
        except (OSError, ValueError):
            continue  # The normal loader reports invalid manifests.
    exclusions, providers, legacy_platforms = {}, {}, {}
    for plugin_id, manifest in manifests.items():
        legacy = manifest.get('replaces')
        if not legacy:
            continue
        # Source entry templates are assembled by the plugin build tool; only
        # packages installed by the host may take over an existing provider.
        if not (Path(manager.plugins_dir) / plugin_id / PLUGIN_INVENTORY).is_file():
            continue
        inherit_settings(manager, plugin_id, manifest, enable_from_legacy=True)
        providers[plugin_id] = legacy
        exclusions.setdefault(legacy, set()).update(manifest['platforms'])
        legacy_platforms.setdefault(legacy, set()).update(manifest.get('replaces_platforms', []))
    manager._replaced_plugins = {
        legacy for legacy, kinds in exclusions.items()
        if (expected := set(manifests.get(legacy, {}).get('platforms') or legacy_platforms[legacy]))
        and expected.issubset(kinds)}
    # Released bundles predating the query API cannot omit just one platform.
    # Preserve them until the whole replacement group is installed or updated.
    manager._blocked_replacements = {
        plugin_id for plugin_id, legacy in providers.items()
        if legacy in manifests and not manifests[legacy].get('platforms') and
        legacy not in manager._replaced_plugins and
        (not legacy_platforms[legacy] or
         set(manifests[plugin_id]['platforms']).intersection(legacy_platforms[legacy])) and
        (manager.enabled is None or legacy in manager.enabled)}
    blocked_legacy = {providers[plugin_id] for plugin_id in manager._blocked_replacements}
    manager._platform_replacements = {key: value for key, value in exclusions.items() if key not in blocked_legacy}
    return sorted(entries, key=lambda name: (not bool(manifests.get(name, {}).get('replaces')), name))
