"""Check appearance design references and readable text palettes."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))


def main():
    doc = (ROOT / "docs/appearance-design.md").read_text(encoding="utf-8")
    assert "深浅色模式已实装" in doc
    assert "appearance-design.md" in (ROOT / "docs/customization-plan.md").read_text(encoding="utf-8")
    rows = re.findall(r"\| [^|]+ (\w+) \| (#[0-9A-F]{6}) \|", doc)
    colors = dict(rows)
    for text in ("TEXT1", "TEXT2", "TEXT3"):
        for background in ("BG", "SIDEBAR", "CONTENT", "CONTENT_HOVER", "ELEVATED"):
            values = sorted((luminance(colors[text]), luminance(colors[background])))
            contrast = (values[1] + .05) / (values[0] + .05)
            assert contrast >= 4.5, (text, background, contrast)
    for text in ('#202630', '#4A5565', '#B93665'):
        contrast = (luminance('#F7F9FC') + .05) / (luminance(text) + .05)
        assert contrast >= 4.5, ('overlay', text, contrast)
    for requirement in ("colorSchemeChanged", "不重新绑定视频 HWND", "取消不改变配置",
                        "utils/folder-icons/", "PNG、JPEG、ICO", "5MB", "4096×4096",
                        "回退默认图标", "普通文件夹和智能文件夹", "175%",
                        "外置主题入口", "独立「外观」页面", "用户确认后再实装",
                        "22×22 纯图标按钮", "排序」和刷新按钮之间", "深色完全沿用当前软件",
                        "真实 `Sidebar`、`WallGrid` 和 `SettingsDialog`"):
        assert requirement in doc, requirement
    assert '格子顶部悬浮栏也改为浅色' in doc
    assert '不改变底部控制条' in doc
    for requirement in ('避免用逻辑整数 QRegion 再裁切抗锯齿边缘',
                        '细边框向内收半像素', '半透明过渡像素', '正式原生视频浮层实现'):
        assert requirement in doc, requirement
    print("PASS: original dark appearance, actual UI placement and light text contrast")


if __name__ == "__main__":
    main()
