"""Qt stream, room, account and status workers; Bilibili API keeps canonical credentials and functions."""
import inspect
import sys
import time
import requests
from PySide6.QtCore import QThread, Signal
from . import qt_lifecycle


class StreamResolver(QThread):
    """在后台线程取流，避免阻塞界面。"""

    resolved = Signal(str, str, int, str, list)   # room_id, url, 实际画质, 通道, 可选档位
    failed = Signal(str, str)       # room_id, 原因

    def __init__(self, room_id: str, quality: int = 250, parent=None,
                 *, source_offset: int = 0, platform=None, preview: bool = False,
                 codec: str = "avc", strict_codec: bool = False):
        from . import bili as api
        super().__init__(parent)
        self.room_id = str(room_id)
        self.quality = quality
        self.source_offset = source_offset
        self.platform = platform
        self.preview = preview
        self.codec = codec if codec in api.CODEC_PARAM else "avc"
        self.strict_codec = strict_codec
        self.codec_unavailable = False
        self.source_codec = ""
        self.codec_probe_note = ""
        self.original_quality_note = ""
        self.headers: dict = {}          # 本次取流的请求头，交给播放器/插件
        self.login_required = False
        self.failure_quality_options = []
        self._cancelled = False

    def cancel(self) -> None:
        """作废这次取流：跑完当前这步就收工，结果不再发出来。

        以前这里是 ``QThread.terminate()`` —— 强杀一个正阻塞在 socket 读上的
        线程，会留下没释放的锁 / GIL 和坏掉的线程本地存储（控制台里那几行
        "QThreadStorage: entry ... destroyed before end of thread" 就是证据），
        主线程随后可能直接卡死：窗口不动、也不退出。只置个标志、让线程自己
        跑完最后一步，代价是最多再等一次请求超时，换来的是绝不会卡死。
        """
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def _platform_play_url(self) -> tuple:
        from . import bili as api
        from .plugins import LoginRequiredError, Platform, StreamCodecUnavailable

        platform = self.platform
        if platform is None:
            raise ValueError("未指定取流平台")
        # Static lookup avoids treating dynamically fabricated mock attributes as hooks.
        hook = (getattr(platform, "play_url_for_codec", None)
                if inspect.getattr_static(platform, "play_url_for_codec", None) is not None
                else None)
        legacy = (not callable(hook)
                  or getattr(hook, "__func__", None) is Platform.play_url_for_codec)
        candidates = ("avc",) if self.codec == "avc" else ("hevc", "avc")
        prefix = "AV1 仅 B 站；" if self.codec == "av1" else ""
        fallback_note = ""
        retrieval_error = None
        for codec in candidates:
            if self._cancelled:
                raise api.Cancelled()
            try:
                if callable(hook):
                    result = hook(self.room_id, self.quality, codec=codec)
                    if not isinstance(result, (tuple, list)) or len(result) != 5:
                        raise ValueError("平台编码接口必须返回五项取流结果")
                    actual_codec = result[4]
                    if actual_codec != codec and not (legacy and actual_codec == ""):
                        raise StreamCodecUnavailable(f"平台未提供已验证的 {codec.upper()} 直播源")
                else:
                    if codec != "avc":
                        raise StreamCodecUnavailable("旧版平台插件不支持选择 HEVC 直播源")
                    result = platform.play_url(self.room_id, self.quality)
                    actual_codec = ""
                if not isinstance(result, (tuple, list)):
                    raise TypeError("平台取流结果必须为元组或列表")
                url, current, profile = result[:3]
                if not isinstance(url, str) or not url.strip():
                    raise ValueError("平台未返回有效直播地址")
                headers = dict(result[3]) if len(result) > 3 else {}
            except (api.Cancelled, LoginRequiredError):
                raise
            except Exception as error:
                if not isinstance(error, StreamCodecUnavailable):
                    retrieval_error = error
                if codec == candidates[-1]:
                    if retrieval_error is not None:
                        raise retrieval_error
                    raise
                fallback_note = ("HEVC 直播源不可用，已回退 H.264"
                                 if isinstance(error, StreamCodecUnavailable)
                                 else "HEVC 取流失败，已回退 H.264")
                continue
            self.source_codec = actual_codec
            if legacy:
                self.codec_probe_note = prefix + "旧版插件使用兼容取流，实际编码以解码读数为准"
            elif fallback_note:
                self.codec_probe_note = prefix + fallback_note
            elif prefix:
                self.codec_probe_note = prefix + "本房间使用 HEVC"
            return url, current, profile, headers
        raise StreamCodecUnavailable("平台未提供可用的直播源格式")

    def run(self) -> None:
        from . import bili as api
        if self._cancelled:
            return
        try:
            if self.platform is not None:
                result = (self.platform.preview_url(self.room_id) if self.preview
                          else self._platform_play_url())
                url, current, profile = result[:3]
                headers = dict(result[3]) if len(result) > 3 else {}
                current = int(current)
                if (not isinstance(url, str) or not url.strip()
                        or not -(2 ** 31) <= current < 2 ** 31
                        or not isinstance(profile, str)):
                    raise ValueError("平台取流结果无效")
            elif self.room_id.isdigit():
                url, current, profile, headers = api.play_url(
                    self.room_id, self.quality, cancelled=self.is_cancelled,
                    source_offset=self.source_offset, codec=self.codec,
                    allow_codec_fallback=not self.strict_codec)
            else:
                raise ValueError("请启用对应的平台插件并重启")
            if self._cancelled:
                return
            options = ([] if self.preview else
                       self.platform.room_quality_options(self.room_id) if self.platform
                       else api.room_quality_options(self.room_id,
                                                 api.codec_from_profile(profile) or self.codec))
            if (self.platform is None and not self.preview
                    and (self.strict_codec or api.codec_from_profile(profile) in api.HLS_ONLY_CODECS)
                    and not any(int(option["qn"]) >= 10000 for option in options)):
                name = {"avc": "H.264", "hevc": "HEVC", "av1": "AV1"}[self.codec]
                self.original_quality_note = (f"{name} 未提供原画" if options
                                              else f"未能验证 {name} 的原画档位")
                if self.strict_codec:
                    raise RuntimeError(self.original_quality_note)
                if self._cancelled:
                    return
                url, current, profile, headers = api.play_url(
                    self.room_id, self.quality, cancelled=self.is_cancelled,
                    source_offset=self.source_offset, codec="avc")
                if self._cancelled:
                    return
                options = api.room_quality_options(self.room_id, "avc")
            options = options or []
            if not isinstance(options, list):
                raise TypeError("平台画质档位必须为列表")
            if options:
                print(f"[画质档位] {self.room_id}: "
                      + " / ".join(f"{item['desc']}({item['qn']})" for item in options),
                      file=sys.stderr, flush=True)
        except api.Cancelled:
            return                       # 作废：不发结果，也不算失败
        except api.CodecUnavailable as error:
            self.codec_unavailable = True
            if not self._cancelled:
                self.failed.emit(self.room_id, str(error))
            return
        except Exception as error:  # noqa: BLE001
            from .plugins import LoginRequiredError, StreamCodecUnavailable
            self.login_required = isinstance(error, LoginRequiredError)
            self.codec_unavailable = isinstance(error, StreamCodecUnavailable)
            if self.platform is not None and not self.preview and not self._cancelled:
                try:
                    options = self.platform.room_quality_options(self.room_id)
                    self.failure_quality_options = [dict(item) for item in options]
                    if not any(int(item["qn"]) == 10000 for item in self.failure_quality_options):
                        self.failure_quality_options.insert(0, {"qn": 10000, "desc": "最高可用"})
                except Exception:  # A menu lookup must not replace the original playback error.
                    self.failure_quality_options = [{"qn": 10000, "desc": "最高可用"}]
            if not self._cancelled:
                self.failed.emit(self.room_id, str(error))
            return
        if self._cancelled:
            return
        self.headers = headers
        if self.platform is None:
            self.source_codec = api.codec_from_profile(profile)
        self.resolved.emit(self.room_id, url, current, profile, options)


class InfoResolver(QThread):
    """在后台线程查房间信息（添加直播间时用）。"""

    resolved = Signal(dict)
    failed = Signal(str)

    def __init__(self, room_id: str, parent=None, *, platform=None):
        super().__init__(parent)
        self.room_id = str(room_id)
        self.platform = platform
        self.error_message = ""
        self.browser_verification = False

    def run(self) -> None:
        from . import bili as api
        self.error_message = ""
        self.browser_verification = False
        try:
            if self.platform is not None:
                result = self.platform.room_info(self.room_id)
                info = result.as_dict() if result is not None else None
            else:
                from .room_input import is_bili_short_url, resolve_bili_share
                room_id = resolve_bili_share(self.room_id) if is_bili_short_url(self.room_id) else self.room_id
                info = api.room_info(room_id) if room_id.isdigit() else None
        except Exception as error:  # noqa: BLE001
            self.browser_verification = getattr(error, "browser_verification", False) is True
            message = getattr(error, "user_message", "")
            if isinstance(message, str) and message.strip():
                self.error_message = message[:600]
            elif isinstance(error, requests.Timeout):
                self.error_message = "房间资料请求超时，请稍后重试"
            elif isinstance(error, requests.HTTPError):
                status = error.response.status_code if error.response is not None else "未知"
                self.error_message = f"房间资料请求失败（HTTP {status}），请稍后重试"
            elif isinstance(error, requests.RequestException):
                self.error_message = "房间资料连接失败，请检查网络或代理设置后重试"
            else:
                self.error_message = "未能解析房间资料，请确认完整直播间链接；持续失败时请反馈平台、版本与失败时间"
            # 异常原文可能包含账号凭证或带签名 URL，只记录类型与明确可展示的提示。
            print(f"[添加直播间] {type(error).__name__}: {self.error_message}", file=sys.stderr)
            info = None
        if info is None:
            self.failed.emit(self.room_id)
        else:
            self.resolved.emit(info)


class FollowLoader(QThread):
    """后台拉取关注列表。"""

    loaded = Signal(list)
    failed = Signal(str)

    def run(self) -> None:
        from . import bili as api
        try:
            self.loaded.emit(api.follow_rooms())
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))


class StatusPoller(QThread):
    """定时批量刷新关注房间的直播状态。"""

    updated = Signal(dict)
    failed = Signal(str)
    status_ready = Signal()

    @qt_lifecycle.construction
    def __init__(self, room_ids: list[str], parent=None, *, platforms=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)
        self.platforms = platforms or {}

    @qt_lifecycle.running
    def run(self) -> None:
        from . import bili as api
        bili_ids = [rid for rid in self.room_ids if str(rid).isdigit()]
        status, uids = {}, {}
        try:
            status, uids = api._rooms_status_base(bili_ids)
            if status:
                # 后续补头像会修改原字典，不能改变已排队的状态快照。
                self.updated.emit({rid: dict(info) for rid, info in status.items()})
            missing = set(bili_ids) - status.keys()
            if missing:
                self.failed.emit(f"{len(missing)} 个房间没有返回状态")
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))
        # 各平台查完就送达；失败不阻塞其他平台，也不误标成下播。
        for kind, platform in self.platforms.items():
            ids = [rid for rid in self.room_ids if str(rid).startswith(kind + ":")]
            if not ids:
                continue
            try:
                self.updated.emit(platform.rooms_status(ids))
            except Exception:  # noqa: BLE001
                self.failed.emit(f"{platform.label or kind} 状态获取失败")
        self.status_ready.emit()
        before = {rid: info.get("face") for rid, info in status.items()}
        api._fill_faces(status, uids)
        enriched = {rid: info for rid, info in status.items() if info.get("face") != before[rid]}
        if enriched:
            self.updated.emit(enriched)


class AccountLoader(QThread):
    """后台获取当前登录账号信息。"""

    loaded = Signal(dict)
    failed = Signal()

    def run(self) -> None:
        from . import bili as api
        account = api.my_account()
        if account:
            self.loaded.emit(account)
        else:
            self.failed.emit()


class StatsPoller(QThread):
    """批量取"看过人数"（只对画面墙上的房间调用）。"""

    updated = Signal(dict)

    @qt_lifecycle.construction
    def __init__(self, room_ids: list[str], parent=None):
        super().__init__(parent)
        self.room_ids = [str(item) for item in room_ids]

    @qt_lifecycle.running
    def run(self) -> None:
        from . import bili as api
        result = {}
        for room_id in self.room_ids:
            stats = api.room_stats(room_id)
            if stats:
                result[room_id] = stats
            time.sleep(0.2)          # 稍微错开，避免触发风控
        if result:
            self.updated.emit(result)
