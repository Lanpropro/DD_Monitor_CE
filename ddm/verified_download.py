"""Cancellable file download with size/hash verification and bounded transport retries."""
import hashlib
import logging
import os
from pathlib import Path
import time
import requests


def download(offer, destination, client, cancelled=lambda: False, progress=lambda *_: None):
    """完整下载并校验后才交付文件；取消或失败清理半成品。"""
    destination = Path(destination)
    partial = destination.with_suffix(destination.suffix + '.part')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        for attempt in range(3):
            if cancelled():
                raise InterruptedError('下载已取消')
            digest, received = hashlib.sha256(), 0
            progress(0, offer['size'])
            started = time.monotonic()
            try:
                # 每次从官方地址重新取得重定向，不复用 CDN 的临时签名地址。
                with client.get(offer['url'], stream=True, timeout=(5, 15)) as response:
                    response.raise_for_status()
                    logging.getLogger(__name__).info('Update download connected: attempt=%s connect_seconds=%.3f bytes=%s',
                                                     attempt + 1, time.monotonic() - started, offer['size'])
                    with partial.open('wb') as output:
                        for chunk in response.iter_content(128 * 1024):
                            if cancelled():
                                raise InterruptedError('下载已取消')
                            if not chunk:
                                continue
                            received += len(chunk)
                            if received > offer['size']:
                                raise ValueError('下载大小超过发布包记录')
                            output.write(chunk)
                            digest.update(chunk)
                            progress(received, offer['size'])
                if cancelled():
                    raise InterruptedError('下载已取消')
                if received != offer['size'] or digest.hexdigest() != offer['sha256']:
                    raise ValueError('安装包完整性校验失败，请重新下载')
                os.replace(partial, destination)
                logging.getLogger(__name__).info('Update download verified: bytes=%s seconds=%.3f attempts=%s',
                                                 received, time.monotonic() - started, attempt + 1)
                return str(destination)
            except (requests.ConnectionError, requests.Timeout,
                    requests.exceptions.ChunkedEncodingError) as error:
                logging.getLogger(__name__).warning('Update download interrupted: attempt=%s bytes=%s seconds=%.3f error=%s',
                    attempt + 1, received, time.monotonic() - started, type(error).__name__)
                partial.unlink(missing_ok=True)
                if cancelled():
                    raise InterruptedError('下载已取消')
                if attempt == 2:
                    raise
                # SSL EOF 等短暂连接故障自动重试；等待期间仍可取消。
                for _ in range(10 * (attempt + 1)):
                    if cancelled():
                        raise InterruptedError('下载已取消')
                    time.sleep(0.05)
    finally:
        partial.unlink(missing_ok=True)
