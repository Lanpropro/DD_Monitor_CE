"""Check that v3 scene 05 uses supported product benefits instead of fake metrics."""

from html.parser import HTMLParser
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
HTML = PROJECT / "compositions" / "v3" / "18-05-why.html"


class SceneText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.current = None
        self.text = {}
        self.duration = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id") == "root":
            self.duration = float(values["data-duration"])
        if values.get("id") in {"l11", "l12", "l13"}:
            self.current = values["id"]
            self.text[self.current] = ""
            self.depth = 0
        if self.current and tag == "div":
            self.depth += 1

    def handle_data(self, data):
        if self.current:
            self.text[self.current] += data

    def handle_endtag(self, tag):
        if self.current and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.current = None


def main():
    scene = SceneText()
    scene.feed(HTML.read_text(encoding="utf-8"))
    assert scene.duration == 7.5
    assert set(scene.text) == {"l11", "l12", "l13"}
    assert "为啥不用浏览器" in scene.text["l11"]
    assert "九路画面，同屏可见" in scene.text["l12"]
    assert "横竖画面，自由摆放" in scene.text["l13"]
    assert all(word not in "".join(scene.text.values()) for word in ("平均", "超快", "超低", "[数值", "待核验"))
    print("v3 beat 05: three benefit scenes, no unsupported measurements")


if __name__ == "__main__":
    main()
