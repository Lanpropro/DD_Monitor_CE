"""验证外观更新计划的范围、状态和代码入口。"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main():
    content = (ROOT / "docs/customization-plan.md").read_text(encoding="utf-8")
    for heading in ("目标与现状", "第一阶段：深浅色模式", "第二阶段：皮肤",
                    "第三阶段：自定义布局", "直播间组合预设（首版待验收）", "实施顺序与交付"):
        assert f"## {heading}" in content, heading
    assert "深浅色与背景皮肤已实装" in content
    assert "当前版本：0.4" in content
    release_gate = content.split("## 0.4 发布状态", 1)[1].split("## 目标与现状", 1)[0]
    assert "保存并恢复布局、主播及所在位置" in release_gate
    assert "皮肤／美化功能" in release_gate and "用户逐项验收" in release_gate
    assert "用户确认继续补齐 PR 并发布 0.4" in release_gate
    assert "当前软件版本为 0.4" in release_gate
    assert content.count("验收：") == 4
    for path in re.findall(r"`(ddm/[^`]+\.py)`", content):
        assert (ROOT / path).is_file(), path
    assert "新增格子保持空白" in content
    assert "不打断录制和弹幕" in content
    assert "1+5布局中的6位主播" in content
    assert "普通布局扩容仍保持新增格子为空" in content
    assert "[直播间组合预设设计](room-presets-design.md)" in content
    design = (ROOT / "docs/room-presets-design.md").read_text(encoding="utf-8")
    assert "首版已实现，纳入 0.4" in design
    assert "现有的“布局预设”弹层" in design and "直播间组合" in design
    for field in ("layout.ratios", "layout.danmaku_cell", "slots", "room_id", "volume", "muted", "audio_channel"):
        assert f"`{field}`" in design, field
    for requirement in ("实际分区比例", "空格子同样保存", "进入全屏前的原始状态",
                        "内置布局卡片仍只管理格子排布", "录制", "旧配置", "物理格位"):
        assert requirement in design, requirement
    skin_section = content.split("## 第二阶段：皮肤", 1)[1].split("## 第三阶段", 1)[0]
    assert "https://github.com/elysia395/dsh-wallpaper-engine" in skin_section
    assert "不连接 Wallpaper Engine" in skin_section
    assert "图片、视频和皮肤插件" in skin_section
    print("PASS: customization plan stages, pending status, acceptance and code references")


if __name__ == "__main__":
    main()
