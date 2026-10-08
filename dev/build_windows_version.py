"""生成 Windows EXE 品牌信息，供 PyInstaller 的 --version-file 使用。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm.version import DISPLAY_NAME, VERSION


def build(output: Path) -> None:
    numbers = tuple(int(part) for part in VERSION.split("."))
    file_version = (numbers + (0, 0, 0, 0))[:4]
    strings = {
        "FileDescription": DISPLAY_NAME,
        "ProductName": DISPLAY_NAME,
        "FileVersion": VERSION,
        "ProductVersion": VERSION,
        "InternalName": DISPLAY_NAME,
        "OriginalFilename": f"{DISPLAY_NAME}.exe",
    }
    entries = ",\n            ".join(f"StringStruct({key!r}, {value!r})" for key, value in strings.items())
    output.write_text(f"""VSVersionInfo(
    ffi=FixedFileInfo(filevers={file_version!r}, prodvers={file_version!r},
                      mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('080404b0', [
            {entries}
        ])]), VarFileInfo([VarStruct('Translation', [2052, 1200])])]
)
""", encoding="utf-8")


if __name__ == "__main__":
    build(Path(sys.argv[1]))
