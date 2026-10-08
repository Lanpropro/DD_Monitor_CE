"""目录事务允许 Windows 短暂占用解压文件，失败时仍保留原异常。"""
import os
import time


def replace_directory(source, destination):
    for delay in (0.05, 0.1, 0.2, 0.4, 0.8, 1.6):
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            if getattr(error, "winerror", None) not in (5, 32, 33):
                raise
            time.sleep(delay)
    os.replace(source, destination)
