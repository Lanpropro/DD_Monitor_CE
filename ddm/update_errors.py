"""Readable failure reasons for online update operations."""
import errno
import zipfile
import requests


def error_message(error):
    if isinstance(error, requests.exceptions.ProxyError):
        return '无法连接代理服务器，请检查代理设置后重试'
    if isinstance(error, requests.exceptions.SSLError):
        return '安全连接验证失败，请检查系统时间和代理证书设置'
    if isinstance(error, requests.ConnectTimeout):
        return '连接服务器超时，请检查网络或代理后重试'
    if isinstance(error, (requests.ReadTimeout, requests.Timeout)):
        return '等待服务器传输数据超时，请稍后重试'
    if isinstance(error, requests.exceptions.ChunkedEncodingError):
        return '下载连接提前中断，文件未接收完整，请检查网络或代理后重试'
    if isinstance(error, requests.ConnectionError):
        return '无法连接服务器或连接已断开，请检查网络或代理后重试'
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else None
        reasons = {403: '服务器拒绝访问，请稍后重试或打开发布页面',
                   404: '服务器上已找不到此更新包，请重新检查更新',
                   429: '服务器请求次数已达上限，请稍后重试'}
        if status in reasons:
            return reasons[status] + f'（HTTP {status}）'
        if status is not None:
            return f'服务器请求失败（HTTP {status}），请稍后重试'
        if str(error) == 'GitHub 查询额度暂时用尽，请稍后重试或打开发布页面':
            return str(error)
    if isinstance(error, requests.RequestException):
        return '网络请求未能完成，请检查网络或代理后重试'
    if isinstance(error, zipfile.BadZipFile):
        return '更新包损坏或不是有效的 ZIP 文件，请重新下载'
    if isinstance(error, OSError):
        if error.errno == errno.ENOSPC:
            return '磁盘空间不足，无法保存更新包，请释放空间后重试'
        if isinstance(error, PermissionError) or error.errno in (errno.EACCES, errno.EPERM):
            return '无法写入更新文件，请检查目录权限或文件是否被占用'
        return '本地文件读写失败，请检查磁盘空间和目录权限后重试'
    # Validation errors already raised by our package/update modules are in Chinese.
    text = str(error)
    if isinstance(error, ValueError) and any('\u4e00' <= char <= '\u9fff' for char in text):
        return text
    return '更新操作未能完成，请重试；若仍失败，请反馈问题及诊断日志'
