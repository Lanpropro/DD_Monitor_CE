"""设置里的插件卡片使用实际插件接口，启用选择只在保存时提交。"""
import os
import sys
import tempfile

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
        dialog.deleteLater()
    app.processEvents()
    print("插件卡片、状态和启用选择：通过")


if __name__ == "__main__":
    main()
