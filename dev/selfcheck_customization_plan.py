"""验证外观更新计划的范围、状态和代码入口。"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main():
    content = (ROOT / "docs/customization-plan.md").read_text(encoding="utf-8")
    for heading in ("目标与现状", "第一阶段：深浅色模式", "第二阶段：皮肤",
                    "第三阶段：自定义布局", "直播间组合预设（待实现）", "实施顺序与交付"):
        assert f"## {heading}" in content, heading
    assert "深浅色与背景皮肤已实装" in content
    assert "下次计划发布版本：0.4（未发布）" in content
    release_gate = content.split("## 0.4 发布前置条件", 1)[1].split("## 目标与现状", 1)[0]
    assert "保存并恢复布局、主播及所在位置" in release_gate
    assert "皮肤／美化功能" in release_gate and "用户逐项验收" in release_gate
    assert "不修改软件版本号、不发布更新、不合并远端 PR 或上传源码" in release_gate
    assert "当前软件版本继续保持 0.3.1" in release_gate
    assert content.count("验收：") == 4
    for path in re.findall(r"`(ddm/[^`]+\.py)`", content):
        assert (ROOT / path).is_file(), path
    assert "新增格子保持空白" in content
    assert "不打断录制和弹幕" in content
    assert "1+5布局中的6位主播" in content
    assert "普通布局扩容仍保持新增格子为空" in content
    skin_section = content.split("## 第二阶段：皮肤", 1)[1].split("## 第三阶段", 1)[0]
    assert "https://github.com/elysia395/dsh-wallpaper-engine" in skin_section
    assert "不连接 Wallpaper Engine" in skin_section
    assert "图片、视频和皮肤插件" in skin_section
    print("PASS: customization plan stages, pending status, acceptance and code references")


if __name__ == "__main__":
    main()
