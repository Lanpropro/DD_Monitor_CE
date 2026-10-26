"""验证功能版 README 的下载版本、链接、展示图与贡献者入口。"""
import ast
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def check():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    module = ast.parse((ROOT / "ddm/version.py").read_text(encoding="utf-8"))
    version = next(ast.literal_eval(node.value) for node in module.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "VERSION"
                           for target in node.targets))
    archives = re.findall(r"DDMonitorCE-v([\d.]+)-exe\.zip", readme)
    executables = re.findall(r"DD监控室CE-v([\d.]+)\.exe", readme)
    assert archives and "DDMonitorSetup.exe" in readme, "missing portable or installer download"
    assert all(value == version for value in archives + executables), "stale README version"
    anchors = {re.sub(r"[^\w\s\-]", "", heading.lower()).replace(" ", "-")
               for heading in re.findall(r"^#{1,6}\s+(.+)$", readme, re.M)}
    for target in re.findall(r"\]\(([^)]+)\)", readme):
        if target.startswith("#"):
            assert target[1:] in anchors, f"missing section: {target}"
        elif "://" not in target:
            assert (ROOT / target.split("#", 1)[0]).is_file(), f"missing local file: {target}"
    assert {"功能特性", "插件扩展", "下载", "文档", "贡献者", "致谢与许可"} <= anchors
    images = [Path(target) for target in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', readme)
              if '://' not in target]
    assert [path.as_posix() for path in images] == [
        'docs/overview4_Landscape_mode.png', 'docs/overview5_Landscape_mode.png',
        'docs/overview2_Portrait_Mode.png'], 'README must use the selected current screenshots'
    tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0'))
    for path in images:
        assert path.as_posix() in tracked, f'screenshot must be included in the repository: {path}'
    assert 'https://contrib.rocks/image?repo=Lanpropro/DD_Monitor_CE' in readme
    assert 'https://github.com/Lanpropro/DD_Monitor_CE/graphs/contributors' in readme
    print("PASS: feature README downloads, local links/anchors, selected tracked screenshots and contributor wall")


if __name__ == "__main__":
    check()
