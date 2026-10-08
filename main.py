"""DD监控室CE（重写版界面）启动入口。

    python main.py       # 带控制台，日志直接看
    pythonw main.py      # 不带控制台（run.cmd 用这个）

python-vlc 在 import 的时候就要知道 libvlc 在哪，所以先设好环境变量再导入 ddm。
"""
import os
import sys

# 旧0.3更新器要求带版本号的入口；该入口只转交到固定名称主程序。
if __name__ == "__main__" and getattr(sys, "frozen", False):
    from pathlib import Path
    entry = Path(sys.executable)
    fixed = entry.with_name("DD监控室CE.exe")
    if entry.name.startswith("DD监控室CE-v") and fixed.is_file():
        import subprocess
        command = [str(fixed), *sys.argv[1:]]
        if len(sys.argv) == 3 and sys.argv[1] == "--apply-update":
            raise SystemExit(subprocess.call(command, cwd=entry.parent))
        subprocess.Popen(command, cwd=entry.parent)
        raise SystemExit(0)

if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--apply-update":
    from ddm.update_install import run_helper
    raise SystemExit(run_helper(sys.argv[2]))

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)                       # 配置、日志、头像缓存都按这个目录算
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

VLC_DLL = os.path.join(PROJ, "libvlc.dll")
if os.path.isfile(VLC_DLL):          # 本目录自带运行库时优先用它
    os.environ.setdefault("PYTHON_VLC_LIB_PATH", VLC_DLL)

from ddm.app import main         # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
