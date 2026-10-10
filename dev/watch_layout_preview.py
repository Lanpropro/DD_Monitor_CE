from pathlib import Path
import subprocess
import sys
import time

preview = Path(__file__).with_name("preview_resizable_corner.py")


def start_preview():
    return subprocess.Popen(
        [sys.executable, str(preview)],
        cwd=preview.parent.parent,
    )


def stop_preview(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


last_modified = preview.stat().st_mtime_ns
process = start_preview()
print("正在监控预览脚本。修改并保存后会自动重启；Ctrl+C 停止。")

try:
    while True:
        time.sleep(0.5)

        try:
            modified = preview.stat().st_mtime_ns
        except FileNotFoundError:
            continue

        if modified != last_modified:
            last_modified = modified
            print("发现文件变化，重新打开预览……")
            stop_preview(process)
            process = start_preview()

except KeyboardInterrupt:
    print("停止预览。")

finally:
    stop_preview(process)