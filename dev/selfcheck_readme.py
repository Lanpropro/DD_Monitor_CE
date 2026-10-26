"""验证功能版 README 的下载版本、链接、网页展示图与贡献者入口。"""
import ast
from pathlib import Path
import re


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
    web_source = '\n'.join((ROOT / 'website-prototype' / name).read_text(encoding='utf-8')
                           for name in ('index.html', 'app.js'))
    images = [Path(target) for target in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', readme)
              if '://' not in target]
    assert images, 'missing software screenshots'
    for path in images:
        assert path.parts[0] == 'website-prototype', f'screenshot is not a website asset: {path}'
        assert path.relative_to('website-prototype').as_posix() in web_source, \
            f'screenshot is not used by the website: {path}'
    assert 'https://contrib.rocks/image?repo=Lanpropro/DD_Monitor_CE' in readme
    assert 'https://github.com/Lanpropro/DD_Monitor_CE/graphs/contributors' in readme
    print("PASS: feature README downloads, local links/anchors, website screenshots and contributor wall")


if __name__ == "__main__":
    check()
