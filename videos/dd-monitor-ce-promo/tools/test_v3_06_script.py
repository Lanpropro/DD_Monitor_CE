"""Check that the proposed scene 06 storyboard covers its full timeline."""

import re
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "SCRIPT-06-RECORDED.md"


def main():
    content = SCRIPT.read_text(encoding="utf-8")
    ranges = [(float(a), float(b)) for a, b in re.findall(r"^\| (\d+\.\d+)–(\d+\.\d+) \|", content, re.M)]
    assert len(ranges) == 5
    assert ranges[0][0] == 0 and ranges[-1][1] == 15.5
    assert all(abs(end - next_start) < 0.001 for (_, end), (next_start, _) in zip(ranges, ranges[1:]))
    assert "[待录]" in content and "06-plugin-demo.mp4" in content
    assert "Video_reference/9格布局.mp4" in content
    assert "SCRIPT-06-RECORDED.md" in (PROJECT / "SCRIPT-v3.md").read_text(encoding="utf-8")
    print("v3 scene 06 script: continuous 15.5s plan, recorded footage requirements identified")


if __name__ == "__main__":
    main()
