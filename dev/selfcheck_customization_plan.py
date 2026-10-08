"""验证外观更新计划的范围、状态和代码入口。"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main():
    content = (ROOT / "docs/customization-plan.md").read_text(encoding="utf-8")
    for heading in ("目标与现状", "第一阶段：深浅色模式", "第二阶段：皮肤",
                    "第三阶段：自定义布局", "实施顺序与交付"):
        assert f"## {heading}" in content, heading
    assert "状态：待实现" in content
    assert content.count("验收：") == 3
    for path in re.findall(r"`(ddm/[^`]+\.py)`", content):
        assert (ROOT / path).is_file(), path
    assert "新增格子保持空白" in content
    assert "不打断录制和弹幕" in content
    print("PASS: customization plan stages, pending status, acceptance and code references")


if __name__ == "__main__":
    main()
