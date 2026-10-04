"""用当前 Windows 用户的 DPAPI 保存平台登录 Cookie。"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re

from . import config


def _crypt(data: bytes, *, decrypt=False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("当前系统不支持加密保存登录，请取消记住登录")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError("平台登录状态加密或解密失败，请重新登录")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


class AccountStore:
    def __init__(self, platform: str, root=None):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", platform):
            raise ValueError("Invalid account platform")
        self.path = Path(root or Path(config.REPO) / "utils" / "accounts") / (platform + ".bin")

    def load(self) -> list[str]:
        if not self.path.exists():
            return []
        result = json.loads(_crypt(self.path.read_bytes(), decrypt=True))
        if not isinstance(result, list) or not all(isinstance(item, str) for item in result):
            raise ValueError("Invalid saved cookies")
        return result

    def save(self, cookies: list[str]) -> None:
        encoded = _crypt(json.dumps(cookies).encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
