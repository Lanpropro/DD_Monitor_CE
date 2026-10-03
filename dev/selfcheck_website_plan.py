"""Check website brief assets, scope and initial plugin download links."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "website-plan.md"


def main():
    content = PLAN.read_text(encoding="utf-8")
    for heading in ("目标", "页面范围", "首批插件与下载", "已有素材与内容入口",
                    "技术与托管建议", "项目入口与参考", "验收"):
        assert f"## {heading}" in content, heading
    for target in re.findall(r"\]\(([^)]+)\)", content):
        if target.startswith("https://"):
            continue
        assert (PLAN.parent / target).is_file(), target
    for plugin_id in ("domestic_live", "global_live"):
        url = ("https://github.com/Lanpropro/DD_Monitor_Plugins/releases/"
               f"download/v1.0/{plugin_id}-1.0.zip")
        assert url in content, plugin_id
    assert "软件本身" in content
    assert "公开软件安装包兼容性仍需核实" in content
    print("PASS: website scope, source assets and both version 1.0 download links")


if __name__ == "__main__":
    main()
