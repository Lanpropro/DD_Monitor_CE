"""设置里的插件卡片使用实际插件接口，启用选择只在保存时提交。"""
import os
import sys
import tempfile
import zipfile
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import plugins as plugin_api  # noqa: E402
from ddm.dialogs import SettingsDialog  # noqa: E402


def write_plugin(root, folder, source):
    path = os.path.join(root, folder)
    os.makedirs(path)
    with open(os.path.join(path, "plugin.py"), "w", encoding="utf-8") as handle:
        handle.write(source)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    with tempfile.TemporaryDirectory(prefix="ddm_plugin_settings_") as root:
        write_plugin(root, "active", "from ddm.plugins import Plugin\n"
                     "class Example(Plugin):\n"
                     "    name = '示例插件'\n"
                     "    description = '用于测试卡片'\n"
                     "    version = '1.2'\n"
                     "plugin = Example()\n")
        write_plugin(root, "disabled", "from ddm.plugins import Plugin\nplugin = Plugin()\n")
        write_plugin(root, "broken", "this is not python (\n")
        manager = plugin_api.PluginManager(plugins_dir=root,
                                           enabled=["active", "broken"])
        manager.load()
        catalog = {entry["id"]: entry for entry in manager.catalog()}
        assert catalog["active"]["name"] == "示例插件"
        assert catalog["active"]["description"] == "用于测试卡片"
        assert catalog["active"]["version"] == "1.2"
        assert catalog["active"]["status"] == "已加载"
        assert catalog["disabled"]["status"] == "已禁用"
        assert catalog["broken"]["status"] == "加载失败"

        dialog = SettingsDialog({}, {}, plugin_manager=manager)
        assert dialog.nav.item(4).text() == "插件"
        assert len(dialog.plugin_page.checks) == 3
        assert dialog.enabled_plugins() == ["active", "broken"]
        dialog.plugin_page.checks["disabled"].setChecked(True)
        assert dialog.enabled_plugins() is None
        assert manager.enabled == {"active", "broken"}, "对话框编辑期间不能更改管理器"
        dialog.plugin_page.checks["broken"].setChecked(False)
        assert dialog.enabled_plugins() == ["active", "disabled"]

        archive = os.path.join(root, "new_plugin.zip")
        sentinel = os.path.join(root, "loaded.txt")
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("new_plugin/plugin.json", '{"id":"new_plugin",'
                             '"name":"新插件","description":"来自清单",'
                             '"version":"2.0"}')
            package.writestr("new_plugin/plugin.py", "from ddm.plugins import Plugin\n"
                             f"open({sentinel!r}, 'w').write('loaded')\n"
                             "plugin = Plugin()\n")
        with patch("ddm.dialogs.QFileDialog.getOpenFileName", return_value=(archive, "")), \
                patch("ddm.dialogs.QMessageBox.information"):
            dialog.plugin_page.install_button.click()
        assert not os.path.exists(sentinel), "导入 ZIP 时不应执行插件代码"
        assert dialog.plugin_page.checks["new_plugin"].isChecked()
        assert next(item for item in manager.catalog() if item["id"] == "new_plugin") == {
            "id": "new_plugin", "name": "新插件", "description": "来自清单",
            "version": "2.0", "enabled": True, "status": "待重启", "reason": ""}
        assert "new_plugin" in manager.enabled
        restarted = plugin_api.PluginManager(plugins_dir=root, enabled=manager.enabled)
        restarted.load()
        assert os.path.exists(sentinel), "重启加载时才执行 plugin.py"
        assert any(plugin.name == "新插件" for plugin in restarted.plugins)

        unsafe = os.path.join(root, "unsafe.zip")
        with zipfile.ZipFile(unsafe, "w") as package:
            package.writestr("evil/plugin.json", '{"id":"evil","name":"X",'
                             '"description":"X","version":"1"}')
            package.writestr("evil/plugin.py", "")
            package.writestr("evil/../../escaped.txt", "bad")
        try:
            manager.install_zip(unsafe)
            assert False, "含有路径穿越的 ZIP 必须拒绝"
        except ValueError:
            pass
        assert not os.path.exists(os.path.join(root, "evil"))
        malformed = os.path.join(root, "malformed.zip")
        with zipfile.ZipFile(malformed, "w") as package:
            package.writestr("wrong/plugin.json", '{"id":"different",'
                             '"name":"X","description":"X","version":"1"}')
            package.writestr("wrong/plugin.py", "plugin = None\n")
        try:
            manager.install_zip(malformed)
            assert False, "清单 ID 与目录不一致必须拒绝"
        except ValueError:
            pass
        assert not os.path.exists(os.path.join(root, "wrong"))
        try:
            manager.install_zip(archive)
            assert False, "相同 ID 不能覆盖已有插件"
        except ValueError:
            pass
        dialog.deleteLater()
    app.processEvents()
    print("插件卡片、状态和启用选择：通过")


if __name__ == "__main__":
    main()
