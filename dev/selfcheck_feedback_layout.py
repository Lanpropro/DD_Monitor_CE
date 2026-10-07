"""同一插件在已安装与商店页中的卡片尺寸、边距、标题与间距一致。"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QPoint

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from ddm import theme
from ddm.dialogs import PluginSettingsPage
from ddm.online_ui import PluginStorePage


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    entry = {"id": "example", "name": "示例插件", "version": "1.0", "description": "插件功能说明",
             "enabled": True, "status": "已加载"}
    manager = SimpleNamespace(catalog=lambda: [entry.copy()])
    with patch("ddm.plugin_updates.pending_versions", return_value={}), \
            patch.object(PluginStorePage, "open_catalog"):
        owner = QWidget()
        owner.resize(800, 600)
        page = PluginSettingsPage(manager)
        QVBoxLayout(owner).addWidget(page)
        page.store_page.show_offers([{**entry, "available": True}])
        page.store_page.status.setText("选择插件即可下载安装，重启后启用。")
        owner.show()
        app.processEvents()
        installed = page.cards.itemAt(0).widget()
        size = installed.size()
        installed_top = installed.mapTo(page, QPoint()).y()
        page.tabs.setCurrentIndex(1)
        app.processEvents()
        store = page.store_page.cards.itemAt(0).widget()
        assert installed_top == store.mapTo(page, QPoint()).y(), (installed_top, store.mapTo(page, QPoint()).y())
        assert installed.size() == store.size(), (size, store.size())
        assert installed.layout().contentsMargins() == store.layout().contentsMargins()
        assert installed.layout().spacing() == store.layout().spacing() == 6
        assert page.cards.spacing() == page.store_page.cards.spacing() == 10
        assert installed.findChild(QLabel, "PluginName").font() == store.findChild(QLabel, "PluginName").font()
        page.store_page.stop()
        owner.close()
    print("PASS: installed/store first-card alignment, size, margins, row spacing and title font")


if __name__ == "__main__":
    main()
