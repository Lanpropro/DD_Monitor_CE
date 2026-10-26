"""Sync the editable GitHub Release body into this repository's release MD."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ddm import online, version


def sync(client, root=ROOT, release_version=version.VERSION):
    notes = online.release_notes(client, release_version)
    path = Path(root) / 'docs/releases' / f'RELEASE-v{release_version.removeprefix("v")}.md'
    if path.is_file() and path.read_text(encoding='utf-8-sig') == notes:
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(notes, encoding='utf-8')
    return path, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default=version.VERSION)
    args = parser.parse_args()
    with online.session() as client:
        path, changed = sync(client, release_version=args.version)
    print(('Synced: ' if changed else 'Unchanged: ') + str(path))


if __name__ == '__main__':
    main()
