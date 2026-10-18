"""Crop the original product screenshots into the prototype's image assets.

Run from the repository root:
    python website-prototype/build_assets.py
"""

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def save(image: Image.Image, name: str, size=None, quality: int = 82) -> None:
    if size:
        image = image.resize(size, Image.LANCZOS)
    image.convert("RGB").save(OUT / name, quality=quality, optimize=True)
    print(name, image.size)


def main() -> None:
    src1 = Image.open(ROOT / "docs/overview1_Landscape_mode.png")
    src2 = Image.open(ROOT / "docs/overview2_Landscape_mode.png")
    srcp = Image.open(ROOT / "docs/overview1_Portrait_Mode.png")

    # The main 16:9 stream, cropped past the app chrome.
    save(src1.crop((180, 120, 2610, 1330)), "hero-main.jpg", (1400, 699))
    # A game stream used as the second hero tile.
    save(src1.crop((150, 1500, 1030, 2070)), "tile-game.jpg", (880, 570))
    # The connected danmaku rail.
    save(src2.crop((2660, 1380, 3770, 2130)), "tile-danmaku.jpg", (888, 600))
    # The portrait layout's main stage, cropped inside the player.
    save(srcp.crop((572, 620, 1025, 1208)), "tile-portrait.jpg", (453, 588))
    # Whole-window references for the layout / recording sections.
    save(src1, "wall-landscape.jpg", (1920, 1080), quality=86)
    save(src2, "wall-danmaku.jpg", (1920, 1080), quality=86)
    save(srcp, "wall-portrait.jpg", (800, 1280), quality=86)


if __name__ == "__main__":
    main()
