"""国内插件更名：启用选择、设置、旧包兼容与新旧目录共存。"""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
from ddm.plugins import PluginManager  # noqa: E402


def plugin(root, plugin_id, *, fail=False):
    folder = root / plugin_id
    folder.mkdir()
    (folder / "plugin.json").write_text(json.dumps({"id": plugin_id, "name": "国内直播平台",
        "version": "0.5.1", "description": "test"}), encoding="utf-8")
    source = "from ddm.plugins import Plugin, Platform\nclass Domestic(Platform):\n    kind='huya'\n"
    source += "class Test(Plugin):\n    def on_load(self, context):\n"
    source += ("        raise AssertionError('Legacy plugin must not load')\n" if fail else
               "        context.register_platform(Domestic())\n")
    source += "plugin=Test()\n"
    (folder / "plugin.py").write_text(source, encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        plugin(root, "domestic_live")
        plugin(root, "huya_watch", fail=True)
        for enabled in (["huya_watch", "other"], ["domestic_live"], None, []):
            manager = PluginManager(plugins_dir=directory, enabled=enabled)
            manager.plugin_settings = {"huya_watch": {"keep": 1, "shared": "old"},
                                       "domestic_live": {"shared": "new"}}
            manager.load()
            assert manager.skipped == ([("domestic_live", "配置里没有启用")] if enabled == [] else [])
            assert manager.plugin_settings == {"domestic_live": {"keep": 1, "shared": "new"}}
            assert {item["id"] for item in manager.catalog()} == {"domestic_live"}
            if enabled == []:
                assert manager.enabled == set() and not manager.plugins
                assert not manager.catalog()[0]["enabled"]
            else:
                assert manager._platform_owner == {"huya": "domestic_live"}
                assert manager.plugins[0].context.setting("keep") == 1
                if enabled is not None:
                    assert "huya_watch" not in manager.enabled and "domestic_live" in manager.enabled
            assert (root / "huya_watch" / "plugin.py").is_file()  # 保留旧文件
            manager.unload()
    with tempfile.TemporaryDirectory() as directory:
        plugin(Path(directory), "huya_watch")
        manager = PluginManager(plugins_dir=directory, enabled=["huya_watch"])
        manager.load()
        assert manager.enabled == {"huya_watch"} and not manager.skipped
        assert manager._platform_owner == {"huya": "huya_watch"}
        manager.unload()
    print("PASS: renamed settings, enabled/disabled/all selection, no duplicate load and legacy-only compatibility")


if __name__ == "__main__":
    main()
