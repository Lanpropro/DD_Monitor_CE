"""下载并核验本项目固定版本的 Windows x64 libmpv。"""
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests


def main():
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / "ddm/assets/licenses/libmpv-SOURCE.json").read_text(encoding="utf-8"))
    target = root / "libmpv-2.dll"
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == source["dll_sha256"]:
        print("libmpv already verified")
        return
    with tempfile.TemporaryDirectory(prefix="ddm-mpv-") as temporary:
        folder = Path(temporary)
        archive = folder / source["asset"]
        with requests.get(source["url"], stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            with archive.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    handle.write(chunk)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != source["sha256"]:
            raise RuntimeError("libmpv archive checksum mismatch")
        subprocess.run(["tar.exe", "-xf", str(archive), "-C", str(folder)], check=True)
        library = folder / "libmpv-2.dll"
        if hashlib.sha256(library.read_bytes()).hexdigest() != source["dll_sha256"]:
            raise RuntimeError("libmpv DLL checksum mismatch")
        shutil.copyfile(library, target)
    print("libmpv downloaded and verified")


if __name__ == "__main__":
    main()
