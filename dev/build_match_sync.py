"""Build the optional plugin ZIP without installing it into the user's app."""
import json
from pathlib import Path
import zipfile

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "plugins_user" / "_match_sync"
FILES = ("plugin.json", "plugin.py", "engine.py", "media.py", "video.py", "viewer.py", "README.md")


def build(destination=None):
    manifest = json.loads((SOURCE / "plugin.json").read_text(encoding="utf-8"))
    target = Path(destination) if destination else REPO / "results" / f"match-sync-v{manifest['version']}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as package:
        for name in FILES:
            package.write(SOURCE / name, f"{manifest['id']}/{name}")
    return target


if __name__ == "__main__":
    print(build())
