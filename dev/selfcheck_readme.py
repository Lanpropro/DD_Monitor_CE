"""验证 README 的版本示例、仓库内链接和章节锚点。"""
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
    assert archives and "DD监控室CE.exe" in readme, "missing portable download or fixed launch name"
    assert all(value == version for value in archives + executables), "stale README version"
    anchors = {re.sub(r"[^\w\s\-]", "", heading.lower()).replace(" ", "-")
               for heading in re.findall(r"^#{1,6}\s+(.+)$", readme, re.M)}
    for target in re.findall(r"\]\(([^)]+)\)", readme):
        if target.startswith("#"):
            assert target[1:] in anchors, f"missing section: {target}"
        elif "://" not in target:
            assert (ROOT / target.split("#", 1)[0]).is_file(), f"missing local file: {target}"
    assert {"软件更新", "关注列表与文件夹", "插件"} <= anchors
    print("PASS: README version, portable filenames, local links and section anchors")


if __name__ == "__main__":
    check()
