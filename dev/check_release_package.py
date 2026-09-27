"""发布包自检：确认两个 ZIP 可读，且源码包来自已提交版本。"""
import subprocess
import zipfile
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
results = repo / "results"
name = "DD监控室CE-v0.2"
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
            assert any(item.endswith("v0.2.exe") for item in names), "ZIP 中缺少新文件名的 exe"
            assert not any(item.endswith("v0.2-exe.exe") for item in names), \
                "ZIP 中仍有旧文件名的 exe"

for path in ("ddm/app.py", "ddm/audio_output.py", "ddm/dialogs.py",
             "RELEASE-v0.2.md"):
    committed = subprocess.check_output(["git", "show", f"HEAD:{path}"], cwd=repo)
    packaged = (source / path).read_bytes()
    assert packaged.replace(b"\r\n", b"\n") == committed.replace(b"\r\n", b"\n"), \
        f"源码包与已提交版本不一致：{path}"

assert (exe / f"{name}.exe").is_file(), "可执行文件缺失"
assert not (exe / f"{name}-exe.exe").exists(), "旧版 exe 文件名仍在包内"
assert f"{name}.exe" in (exe / "运行说明.txt").read_text(encoding="utf-8-sig"), \
    "运行说明中的 exe 文件名不正确"
for folder in (source, exe):
    assert (folder / "ffmpeg.exe").is_file(), "FFmpeg 缺失"
    assert (folder / "ffmpeg-license" / "LICENSE").is_file(), "FFmpeg 许可缺失"
    assert not (folder / "utils" / "config.json").exists(), "发布包包含个人配置"
    assert not (folder / "logs").exists(), "发布包包含运行日志"

print("OK: v0.2 源码与 exe 发布包完整，ZIP 可读，源码与 HEAD 一致")
