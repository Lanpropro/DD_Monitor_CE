"""后台验证真实并发下载/解压、独立失败重试及 Qt 界面持续响应。"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import requests
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ddm import config, online, plugin_updates
from ddm.dialogs import SettingsDialog
from ddm.plugins import PluginManager


def wait(app, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate(), "Background operation timed out"


def main():
    app = QApplication([])
    ids = ("domestic_live", "global_live")
    packages = {}
    for plugin_id in ids:
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr(plugin_id + "/plugin.json", json.dumps({"id": plugin_id,
                "name": plugin_id, "description": "fixture", "version": "1.1"}))
            archive.writestr(plugin_id + "/plugin.py", "# never executed during install")
        packages[plugin_id] = data.getvalue()
    downloading = {key: threading.Event() for key in ids}
    extracting = {key: threading.Event() for key in ids}
    download_gate = threading.Event()
    extract_gates = {key: threading.Event() for key in ids}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_GET(self):
            plugin_id = self.path.strip("/")
            if plugin_id not in packages:
                self.send_error(404)
                return
            data = packages[plugin_id]
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            downloading[plugin_id].set()
            assert download_gate.wait(8)
            self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_install = plugin_updates.install
    def install(manager, archive, offer):
        extracting[offer["id"]].set()
        assert extract_gates[offer["id"]].wait(8)
        return original_install(manager, archive, offer)
    dialog = None
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = PluginManager(plugins_dir=str(root / "plugins"), enabled=[])
            for plugin_id in ids:
                target = root / "plugins" / plugin_id
                target.mkdir(parents=True)
                (target / "plugin.json").write_text(json.dumps({"id": plugin_id, "name": plugin_id,
                    "description": "old", "version": "1.0"}), encoding="utf-8")
                (target / "plugin.py").write_text("# previous version", encoding="utf-8")
            with patch.object(config, "REPO", str(root)), patch.object(online, "session", requests.Session), patch.object(plugin_updates, "install", side_effect=install):
                dialog = SettingsDialog({}, {}, plugin_manager=manager)
                page = dialog.plugin_page.store_page
                offers = [{"id": key, "name": key, "description": "fixture", "version": "1.1",
                    "available": True, "url": f"http://127.0.0.1:{server.server_port}/{key}",
                    "asset_name": key + ".zip", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                    for key, data in packages.items()]
                broken = dict(offers[0], id="match_sync", name="failure", url=f"http://127.0.0.1:{server.server_port}/missing")
                page._catalog_ready(offers + [broken])
                ticks = []
                timer = QTimer()
                timer.setInterval(10)
                timer.timeout.connect(lambda: ticks.append(1))
                timer.start()
                page.buttons[ids[0]].click()
                assert page.buttons[ids[1]].isEnabled(), "First download blocks other plugins"
                page.buttons[ids[1]].click()
                page.install_offer(offers[0])
                assert len(page.jobs) == 2, "Duplicate or serialized plugin download"
                wait(app, lambda: all(event.is_set() for event in downloading.values()) and len(ticks) >= 5)
                assert not dialog.confirm_button.isEnabled()
                # 一个插件失败，不阻止其余插件继续下载，并恢复该插件重试按钮。
                page.buttons["match_sync"].click()
                wait(app, lambda: page.buttons["match_sync"].isEnabled())
                assert len(page.jobs) == 2 and "操作失败" in page.status.text()
                download_gate.set()
                wait(app, lambda: all(event.is_set() for event in extracting.values())
                     and all(page.buttons[key].text() == "校验/解压中" for key in ids))
                assert all(page.buttons[key].text() == "校验/解压中" for key in ids)
                before = len(ticks)
                wait(app, lambda: len(ticks) >= before + 5)
                extract_gates[ids[0]].set()
                wait(app, lambda: len(page.jobs) == 1)
                assert plugin_updates.pending_versions(manager) == {ids[0]: "1.1"}
                assert page.buttons[ids[0]].text() == "待重启"
                assert not page.buttons[ids[1]].isEnabled() and page.buttons["match_sync"].isEnabled()
                extract_gates[ids[1]].set()
                wait(app, lambda: not page.jobs)
                assert plugin_updates.pending_versions(manager) == dict.fromkeys(ids, "1.1")
                assert dialog.confirm_button.isEnabled()
                assert all(page.buttons[key].text() == "待重启" for key in ids)
                timer.stop()
                dialog.close()
                app.processEvents()
    finally:
        download_gate.set()
        for gate in extract_gates.values():
            gate.set()
        if dialog:
            dialog.plugin_page.store_page.stop()
        server.shutdown()
        server.server_close()
        thread.join()
    print("PASS: concurrent HTTP downloads and extraction; responsive UI; per-plugin progress, deduplication, isolated failure and pending updates")


if __name__ == "__main__":
    main()
