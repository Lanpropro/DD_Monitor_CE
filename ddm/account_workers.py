"""Cancellable account-to-room resolution worker for follow import."""
from copy import deepcopy
from PySide6.QtCore import QThread, Signal


class FollowAccountResolver(QThread):
    updated = Signal(dict)
    progress = Signal(int, int)

    def __init__(self, platform, accounts, parent, *, start_index=0):
        super().__init__(parent)
        self.platform = platform
        self.accounts = deepcopy(accounts)
        self.next_index = start_index
        self.failures = 0

    def run(self):
        cancelled = self.isInterruptionRequested
        for index in range(self.next_index, len(self.accounts)):
            if cancelled():
                break
            account = self.accounts[index]
            if account.get("follow_account_ref") or not account.get("room_id") or account.get("live_known") is False:
                error_kind = ""
                try:
                    resolved = self.platform.resolve_follow_account(account, cancelled)
                except Exception as error:  # 单个账号失败不影响其余关注，也不覆盖原身份。
                    self.failures += 1
                    error_kind = type(error).__name__
                    resolved = dict(account)
                if cancelled():
                    break
                if resolved is not None:
                    resolved = dict(resolved, follow_resolve_error=error_kind,
                                    follow_resolve_note="未取得房间号" if not resolved.get("room_id") else
                                    "未取得直播状态" if resolved.get("live_known") is False else "")
                    self.updated.emit(resolved)
            self.next_index = index + 1
            self.progress.emit(self.next_index, len(self.accounts))
