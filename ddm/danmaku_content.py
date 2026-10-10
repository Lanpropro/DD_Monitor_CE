"""Shared text/image runs for the chat list and video overlay."""
import html
import re


def content_runs(event: dict) -> list[tuple[str, str]]:
    """Return (fallback text, image URL), preserving Unicode and run order."""
    text = str(event.get("text") or "")
    if event.get("emoticon"):
        return [(text, str(event["emoticon"]))]
    emotes = event.get("emoticons") or {}
    if not isinstance(emotes, dict):
        return [(text, "")]
    emotes = {key: url for key, url in emotes.items()
              if isinstance(key, str) and key and isinstance(url, str) and url}
    if not emotes:
        return [(text, "")]
    pattern = "(" + "|".join(re.escape(key) for key in sorted(emotes, key=len, reverse=True)) + ")"
    return [(part, emotes.get(part, "")) for part in re.split(pattern, text) if part]


def content_html(runs, images, height: int) -> str:
    parts = []
    for text, url in runs:
        image = images.get(url) if url else None
        if image is None or image.isNull():
            parts.append(html.escape(text))
        else:
            width = max(1, round(image.width() * height / max(1, image.height())))
            parts.append(f'<img src="{html.escape(url, quote=True)}" '
                         f'width="{width}" height="{height}">')
    return "".join(parts)
