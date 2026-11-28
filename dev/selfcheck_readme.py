"""验证 README 的下载版本、导航、品牌图、截图与贡献者链接。"""
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
    published = re.search(r"当前已发布版本 \*\*([\d.]+)\*\*", readme)
    download_version = published.group(1) if published else version
    assert all(value == download_version for value in archives + executables), "stale README download version"
    links = re.findall(r"\]\(([^)]+)\)", readme)
    links += re.findall(r'<a\s+href="([^"]+)"', readme)
    release_download = f"https://github.com/Lanpropro/DD_Monitor_CE/releases/download/v{download_version}/"
    for filename in ("DDMonitorSetup.exe", f"DDMonitorCE-v{download_version}-exe.zip"):
        assert release_download + filename in links, f"download must point to the published release: {filename}"
    if download_version != version:
        assert f"本地候选版本 **{version}**" in readme, "Unpublished source version must be identified as a local candidate"
    anchors = {re.sub(r"[^\w\s\-]", "", heading.lower()).replace(" ", "-")
               for heading in re.findall(r"^#{1,6}\s+(.+)$", readme, re.M)}
    for target in links:
        if target.startswith("#"):
            assert target[1:] in anchors, f"missing section: {target}"
        elif "://" not in target:
            assert (ROOT / target.split("#", 1)[0]).is_file(), f"missing local file: {target}"
    assert {"下载", "快速开始", "主要功能", "插件扩展", "使用帮助与反馈", "致谢与许可"} <= anchors
    images = [target for target in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', readme)
              if '://' not in target]
    assert images == [
        'docs/assets/screenshots/overview4_Landscape_mode.png',
        'docs/assets/screenshots/overview2_Portrait_Mode.png',
        'docs/assets/screenshots/overview5_Landscape_mode.png',
    ], 'README must use the selected current screenshots'
    logos = re.findall(r'<img\s+src="([^"]+)"', readme)
    assert logos == ['design/icon-concepts/app-icon-badge.png'], 'README must use the selected brand logo'
    tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0'))
    for image in logos + images:
        assert image in tracked and (ROOT / image).is_file(), f'README image must be included in the repository: {image}'
    assert f'docs/releases/RELEASE-v{download_version}.md' in links
    assert 'https://github.com/Lanpropro/DD_Monitor_CE/graphs/contributors' in links
    print("PASS: README downloads, local links/anchors, selected tracked images and contributor link")


if __name__ == "__main__":
    check()
