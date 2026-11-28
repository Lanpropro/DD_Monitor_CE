"""Check appearance design references and readable text palettes."""
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))


def check_gallery_vectors():
    def assignment(path, name):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        return next(node.value for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))

    data = (ROOT / "docs/references/ui-control-icon-data.js").read_text(encoding="utf-8")
    vectors = [json.loads(line.strip().rstrip(",")) for line in data.splitlines()
               if line.lstrip().startswith("[")]
    actual = {key: (source, svg) for _, key, _, source, svg in vectors}
    assert len(actual) == len(vectors), "duplicate inventory icon IDs"
    rail_path = "ddm/sidebar_navigation.py"
    settings_path = "ddm/settings_navigation.py"
    folder_path = "ddm/folder_icons.py"
    rail_nodes = assignment(rail_path, "PATHS")
    shared = {"REPLAY_ICON_PATH": ast.literal_eval(assignment("ddm/widget_support.py", "REPLAY_ICON_PATH"))}
    rail = {}
    for key, value in zip(rail_nodes.keys, rail_nodes.values):
        if isinstance(value, ast.JoinedStr):
            svg = "".join(part.value if isinstance(part, ast.Constant) else shared[part.value.id]
                          for part in value.values)
        else:
            svg = ast.literal_eval(value)
        rail[key.value] = svg
    settings = assignment(settings_path, "ICONS")
    names = ast.literal_eval(assignment("ddm/follow_folders.py", "ICON_NAMES"))
    folders = ast.literal_eval(assignment(folder_path, "PATHS"))
    expected = {f"rail-{key}": (rail_path, svg) for key, svg in rail.items()}
    for key, glyph in zip(settings.keys, settings.values):
        svg = ast.literal_eval(glyph) if isinstance(glyph, ast.Constant) else rail[ast.literal_eval(glyph.slice)]
        expected[f"settings-{ast.literal_eval(key)}"] = (settings_path, svg)
    expected.update({f"folder-{key}": (folder_path, svg) for key, svg in zip(names, folders, strict=True)})
    assert actual == expected, f"stale gallery SVG inventory: {actual.keys() ^ expected.keys()}"

    examples = (ROOT / "docs/references/ui-control-app-examples.js").read_text(encoding="utf-8")
    gallery_palette = examples.split("const labFolderColors = [", 1)[1].split("];", 1)[0]
    qt_colors = ast.literal_eval(assignment(folder_path, "COLORS").args[0].args[1])
    assert re.findall(r"#[\da-f]{6}", gallery_palette) == [color.lower() for color in qt_colors if color], (
        "gallery folder swatches must match the Qt palette and order"
    )


def main():
    check_gallery_vectors()
    gallery_styles = (ROOT / "docs/references/ui-control-playground.css").read_text(encoding="utf-8")
    pressed_styles = re.search(r"\.lab-control:active:enabled,\s*\.lab-demo\[data-state=pressed\][^{]*\{([^}]+)\}",
                               gallery_styles)
    assert pressed_styles, "live and fixed gallery button states must share the pressed style"
    pressed = pressed_styles.group(1)
    assert "background:" in pressed and "border" not in pressed and "outline" not in pressed, (
        "press feedback must change the fill without painting a focus border"
    )
    current = (ROOT / "docs/features/appearance-design.md").read_text(encoding="utf-8")
    assert "设置 → 外观" in current
    assert "archive/appearance-implementation-202610.md" in current
    assert "ddm/theme.py" in current and "ddm/folder_icons.py" in current
    doc = (ROOT / "docs/archive/appearance-implementation-202610.md").read_text(encoding="utf-8")
    assert "深浅色模式已实装" in doc
    assert "appearance-design.md" in (ROOT / "docs/features/customization-plan.md").read_text(encoding="utf-8")
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
    assert '底部控制条也采用浅色' in doc
    assert '点击图标直接切换深浅色，不弹出菜单或设置窗口' in doc
    assert '保存为手动选择' in doc
    assert '360ms 圆弧扩散过渡' in doc and '连续点击保留当前可见的混合画面' in doc
    assert '按钮的左上角' in doc and '不重新应用整份全局 QSS' in doc
    for requirement in ('避免用逻辑整数 QRegion 再裁切抗锯齿边缘',
                        '细边框向内收半像素', '半透明过渡像素', '正式原生视频浮层实现'):
        assert requirement in doc, requirement
    print("PASS: original dark appearance, actual UI placement and light text contrast")


if __name__ == "__main__":
    main()
