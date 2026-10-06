"""从已有插件 ZIP 生成 Release 商店目录；不执行代码，也不创建安装包。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import online
from ddm.plugins import PLUGIN_ID


def build(archives, tag):
    entries = []
    for archive in archives:
        archive = Path(archive)
        with zipfile.ZipFile(archive) as package:
            manifests = [name for name in package.namelist() if name.count('/') == 1 and name.endswith('/plugin.json')]
            if len(manifests) != 1:
                raise ValueError('每个插件包只能包含一个 plugin.json')
            manifest = json.loads(package.read(manifests[0]))
        plugin_id = manifest['id']
        if not PLUGIN_ID.fullmatch(plugin_id) or plugin_id not in online.KNOWN_PLUGINS:
            raise ValueError('目录只收录官方维护的插件')
        online.version_key(manifest['version'])
        entry = {key: manifest[key] for key in ('id', 'name', 'description', 'version')}
        entry.update(min_app_version=manifest.get('min_app_version', '0.3'),
                     asset_name=archive.name, size=archive.stat().st_size,
                     sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                     url=f'https://github.com/{online.PLUGIN_REPOSITORY}/releases/download/{tag}/{archive.name}')
        online.manifest_offer(entry, online.PLUGIN_REPOSITORY)
        entries.append(entry)
    if len({entry['id'] for entry in entries}) != len(entries):
        raise ValueError('同一插件不能重复收录')
    return {'plugins': entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', type=Path, default=Path('plugin-catalog.json'))
    parser.add_argument('archives', nargs='+', type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(build(args.archives, args.tag), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
