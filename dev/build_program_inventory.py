"""Generate reproducible release inventories without reading local user data."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm.legacy_cleanup import INVENTORY
from ddm.update_install import PROTECTED, relative_path


def legacy_catalog(archives):
    releases, files = [], {}
    for archive in sorted(map(Path, archives)):
        match = re.fullmatch(r'DD监控室CE-v(\d+(?:\.\d+)*)-exe\.zip', archive.name)
        if not match:
            raise ValueError('需要带版本号的本体 EXE 发布 ZIP')
        with archive.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        count, seen = 0, set()
        with zipfile.ZipFile(archive) as package:
            entries = [item for item in package.infolist() if not item.is_dir()]
            tops = {PurePosixPath(item.filename).parts[0] for item in entries}
            if len(tops) != 1:
                raise ValueError('发布包必须包含唯一程序目录')
            for item in entries:
                path = PurePosixPath(item.filename)
                if (len(path.parts) < 2 or '\\' in item.filename
                        or any(part in ('', '.', '..') for part in item.filename.split('/'))
                        or path.is_absolute() or (item.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError('发布包路径无效')
                name = '/'.join(path.parts[1:])
                if path.parts[1].casefold() in PROTECTED:
                    continue
                relative_path(name)
                if name.casefold() in seen:
                    raise ValueError('发布包包含重复路径')
                seen.add(name.casefold())
                with package.open(item) as source:
                    file_hash = hashlib.file_digest(source, 'sha256').hexdigest()
                variant = {'size': item.file_size, 'sha256': file_hash}
                values = files.setdefault(name, [])
                if variant not in values:
                    values.append(variant)
                count += 1
        releases.append({'version': match[1], 'archive_sha256': digest, 'program_files': count})
    return {'schema': 1, 'releases': releases, 'files': dict(sorted(files.items()))}


def write_inventory(payload):
    root = Path(payload).resolve()
    build = json.loads((root / 'ddm-build.json').read_text(encoding='utf-8-sig'))
    names = []
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if path.is_symlink() or path.is_junction():
            raise ValueError('程序包不能包含链接')
        if name.split('/')[0].casefold() in PROTECTED:
            continue
        if path.is_file():
            relative_path(name)
            names.append(name)
    names = sorted(set(names) | {INVENTORY})
    result = {'schema': 1, 'version': build['version'], 'files': names}
    (root / INVENTORY).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--payload', type=Path)
    group.add_argument('--archives', type=Path, nargs='+')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.payload:
        result = write_inventory(args.payload)
    else:
        if args.output is None:
            parser.error('--archives requires --output')
        result = legacy_catalog(args.archives)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Inventory: {len(result['files'])} program paths")


if __name__ == '__main__':
    main()
