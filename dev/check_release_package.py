"""发布包自检：ZIP 完整、源码与打包工作区一致、覆盖升级保留用户数据。"""
import argparse
import hashlib
import json
import os
import tempfile
import time
import subprocess
import sys
import zipfile
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--out-dir", type=Path, default=repo / "results")
parser.add_argument("--old-zip", type=Path)
args = parser.parse_args()
results = args.out_dir.resolve()
sys.path.insert(0, str(repo))
from ddm.version import DISPLAY_NAME, VERSION, VERSION_TAG
name = f"{DISPLAY_NAME}-{VERSION_TAG}"
source = results / name
exe = results / f"{name}-exe"

for folder, zip_path in ((source, results / f"{name}.zip"),
                         (exe, results / f"{name}-exe.zip")):
    assert folder.is_dir() and zip_path.is_file(), f"发布包缺失：{zip_path}"
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None, f"ZIP 校验失败：{zip_path}"
        assert len(archive.namelist()) > 20, f"ZIP 内容不完整：{zip_path}"
        if folder == exe:
            names = archive.namelist()
            assert any(item.endswith(f"{VERSION_TAG}.exe") for item in names), "ZIP 中缺少新文件名的 exe"
            assert not any(item.endswith(f"{VERSION_TAG}-exe.exe") for item in names), \
                "ZIP 中仍有旧文件名的 exe"

for path in ("ddm/app.py", "ddm/widgets.py", "ddm/audio_output.py", "ddm/dialogs.py",
             "ddm/plugins.py", "docs/PLUGINS.md", f"RELEASE-{VERSION_TAG}.md"):
    original = (repo / path).read_bytes()
    packaged = (source / path).read_bytes()
    assert packaged.replace(b"\r\n", b"\n") == original.replace(b"\r\n", b"\n"), \
        f"源码包与打包工作区不一致：{path}"

assert (exe / f"{name}.exe").is_file(), "可执行文件缺失"
assert not (exe / f"{name}-exe.exe").exists(), "旧版 exe 文件名仍在包内"
assert f"{name}.exe" in (exe / "运行说明.txt").read_text(encoding="utf-8-sig"), \
    "运行说明中的 exe 文件名不正确"
for folder in (source, exe):
    assert (folder / "ffmpeg.exe").is_file(), "FFmpeg 缺失"
    assert (folder / "ffmpeg-license" / "LICENSE").is_file(), "FFmpeg 许可缺失"
    assert not (folder / "utils" / "config.json").exists(), "发布包包含个人配置"
    assert not (folder / "logs").exists(), "发布包包含运行日志"
    assert not any((folder / "plugins_user").iterdir()), "发布包包含本地用户插件"
    assert not (folder / "utils" / "accounts").exists(), "发布包包含登录数据"
    assert not (folder / "cache").exists(), "发布包包含缓存"
    assert not (folder / "videos").exists(), "发布包包含宣传片工程"
    assert not list((folder / "dev").glob("*promo*")), "发布包包含宣传片工具"
metadata = json.loads((results / "app-update.json").read_text(encoding="utf-8-sig"))
archive = results / f"{name}-exe.zip"
remote_name = f"DDMonitorCE-{VERSION_TAG}-exe.zip"
assert metadata["version"] == VERSION and metadata["asset_name"] == remote_name
assert metadata["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
assert metadata["size"] == archive.stat().st_size
assert metadata["notes"].replace("\r\n", "\n") == (repo / f"RELEASE-{VERSION_TAG}.md").read_text(encoding="utf-8")
assert metadata["url"].endswith(f"/{VERSION_TAG}/{remote_name}")
build = json.loads((exe / "ddm-build.json").read_text(encoding="utf-8-sig"))
assert build == {"version": VERSION, "update_protocol": 1, "platform": "windows-x64"}

if args.old_zip:
    # 用真实旧包模拟用户目录，合并解压新包，然后启动覆盖后的 exe。
    work = repo / "work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release_upgrade_", dir=work) as temporary:
        root = Path(temporary).resolve()
        assert root.is_relative_to(work.resolve())

        def overlay(path):
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    assert (root / member.filename).resolve().is_relative_to(root), \
                        "发布包路径越界"
                archive.extractall(root)

        overlay(args.old_zip)
        installed = root / f"{name}-exe"
        assert installed.is_dir(), "新旧包程序目录名称不一致"
        config = installed / "utils" / "config.json"
        config.parent.mkdir(exist_ok=True)
        config.write_text(json.dumps({"version": 2, "rooms": [], "wall": [],
                                      "ui": {"layout_landscape": "3x2"},
                                      "settings": {"decode_mode": "d3d11va"},
                                      "plugins_enabled": None}), encoding="utf-8")
        custom = installed / "plugins_user" / "upgrade_probe"
        custom.mkdir(parents=True)
        (custom / "plugin.json").write_text(json.dumps({"id": "upgrade_probe",
            "name": "Upgrade probe", "description": "Upgrade test", "version": "1.0"}),
            encoding="utf-8")
        (custom / "plugin.py").write_text(
            "from pathlib import Path\nfrom ddm.plugins import Plugin\n"
            "class Probe(Plugin):\n"
            "    def on_load(self, context):\n"
            "        Path(__file__).with_name('loaded.txt').write_text('loaded')\n"
            "plugin = Probe()\n", encoding="utf-8")
        preserved = [config, custom / "plugin.py", custom / "plugin.json"]
        for rel in ("cache/sentinel.bin", "logs/sentinel.bin", "recordings/sentinel.bin",
                    "plugins_user/danmaku_log/saved.txt", "plugins_user/upgrade_probe/data.bin"):
            path = installed / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"keep existing data")
            preserved.append(path)
        before = {path: path.read_bytes() for path in preserved}
        overlay(results / f"{name}-exe.zip")
        assert all(path.read_bytes() == data for path, data in before.items()), \
            "覆盖升级改写了配置、插件或用户数据"
        updated_exe = installed / f"{name}.exe"
        assert hashlib.sha256(updated_exe.read_bytes()).digest() == hashlib.sha256(
            (exe / f"{name}.exe").read_bytes()).digest(), "旧 exe 未被新包替换"
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.Popen([str(updated_exe)], cwd=installed, startupinfo=startup,
                                   env=dict(os.environ, DDM_NO_SAVE="1"))
        try:
            deadline = time.monotonic() + 25
            ready = False
            while time.monotonic() < deadline:
                assert process.poll() is None, "覆盖后的 exe 启动时退出"
                logs = list((installed / "logs").glob("ddm-*.log"))
                content = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in logs)
                if "[方向]" in content and (custom / "loaded.txt").exists():
                    ready = True
                    assert "已装载 弹幕记录" not in content, "升级后仍执行旧内置插件"
                    break
                time.sleep(0.2)
            assert ready, "覆盖后的 exe 未进入界面或未加载保留的用户插件"
            assert all(path.read_bytes() == data for path, data in before.items()), \
                "升级启动改变了保留数据"
        finally:
            process.kill()
            process.wait(timeout=10)
        print("OK: 旧版目录合并覆盖、配置/插件/数据保留、新 exe 启动与用户插件加载通过")

print(f"OK: {VERSION_TAG} 源码与 exe 发布包完整，ZIP、更新元数据和隐私检查通过")
