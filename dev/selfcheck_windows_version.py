"""实际写入 Windows EXE 并读取品牌资源，不启动软件或读取用户配置。"""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import PyInstaller
from PyInstaller.utils.win32.versioninfo import (
    load_version_info_from_text_file, read_version_info_from_executable,
    write_version_info_to_executable,
)
from build_windows_version import build
from ddm.version import DISPLAY_NAME, VERSION


def main():
    with tempfile.TemporaryDirectory(prefix="DDM 品牌资源 ") as directory:
        root = Path(directory)
        metadata = root / "version.txt"
        build(metadata)
        info = load_version_info_from_text_file(str(metadata))
        major, minor, *_ = [int(part) for part in VERSION.split(".")] + [0, 0]
        assert info.ffi.fileVersionMS == (major << 16) | minor
        bootloader = Path(PyInstaller.__file__).parent / "bootloader/Windows-64bit-intel/runw.exe"
        exe = root / f"{DISPLAY_NAME}.exe"
        shutil.copy2(bootloader, exe)
        write_version_info_to_executable(str(exe), info)
        actual = read_version_info_from_executable(str(exe))
        fields = {entry.name: entry.val for entry in actual.kids[0].kids[0].kids}
        assert fields["FileDescription"] == DISPLAY_NAME
        assert fields["ProductName"] == DISPLAY_NAME
        assert fields["FileVersion"] == VERSION and fields["ProductVersion"] == VERSION
        assert fields["OriginalFilename"] == exe.name
    print("PASS: generated version resource, real Windows EXE description/product/name/version round trip")


if __name__ == "__main__":
    main()
