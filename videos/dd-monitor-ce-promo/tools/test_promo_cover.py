"""Check the editable cover and its exported 16:9 image."""

from pathlib import Path

from PIL import Image, ImageStat


COVER = Path(__file__).resolve().parents[1] / "covers"


def main():
    html = (COVER / "promo-cover.html").read_text(encoding="utf-8")
    assert 'src="recorded-grid.png"' in html
    assert "九路直播" in html and "一屏掌控" in html
    assert "DD监控室CE" in html

    with Image.open(COVER / "recorded-grid.png") as source:
        assert source.size == (1600, 892)
    with Image.open(COVER / "promo-cover.png") as exported:
        assert exported.size == (1920, 1080)
        ground = exported.getpixel((50, 50))[:3]
        assert max(ground) < 50, "cover should use the software's dark palette"
        assert exported.getpixel((48, 50))[:3] != ground, "background grid is missing"
        assert exported.getpixel((1500, 180))[1] > ground[1], "cyan light behind the window is missing"
        screenshot = exported.crop((900, 350, 1700, 820)).convert("RGB")
        assert min(ImageStat.Stat(screenshot).stddev) > 30

    print("promo cover: source, copy, colors and 1920x1080 export verified")


if __name__ == "__main__":
    main()
