"""Check the revised 06–07 storyboard's coverage and source handoff."""

import re
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "SCRIPT-06-RECORDED.md"


def main():
    text = SCRIPT.read_text(encoding="utf-8")
    main_script = (PROJECT / "SCRIPT-v3.md").read_text(encoding="utf-8")
    spans = [
        (float(start), float(end))
        for start, end in re.findall(r"^\| (\d+\.\d+)–(\d+\.\d+) \|", text, re.MULTILINE)
    ]
    assert spans[0][0] == 0.0 and spans[-1][1] == 30.9
    assert all(start < end for start, end in spans)
    assert all(abs(left[1] - right[0]) < 0.001 for left, right in zip(spans, spans[1:]))
    for required in ("六次点击", "即时重放", "同一信息页", "同心圆弧", "上下首尾拼接", "07 结尾"):
        assert required in text, required
    assert "及时重放" not in text and "及时重放" not in main_script
    assert "插件" not in text
    assert "SCRIPT-06-RECORDED.md" in main_script
    assert "18-06-design.html" in main_script
    assert "v3-01-07-design-preview.mp4" in main_script
    print("06–07 storyboard: contiguous timing, required beats and pending sources verified")


if __name__ == "__main__":
    main()
