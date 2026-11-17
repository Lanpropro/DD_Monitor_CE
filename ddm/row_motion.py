"""Shared row positioning; callers own animation dictionaries and the GUI clock."""
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation
from shiboken6 import isValid


def glide_to(self, item, x: int, y: int, animate: bool, duration=150) -> None:
    target = QPoint(x, y)
    previous = self._animations.get(item)
    if previous is not None:
        if (animate and previous.state() != QPropertyAnimation.Stopped
                and previous.endValue() == target):
            return  # 同一落点的拖动事件不能重启动画，否则卡片始终追不上目标。
        previous.stop()
        self._animation_started.pop(previous, None)
        self._animations.pop(item)
        previous.deleteLater()
    if item.pos() == target:
        return
    if not animate:
        item.move(target)
        return
    animation = QPropertyAnimation(item, b"pos", item)
    animation.setDuration(duration)
    animation.setStartValue(item.pos())
    animation.setEndValue(target)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    self._animations[item] = animation
    animation.start()
    # The shared Qt/Quick animation clock stopped at time zero in captured
    # folder transitions. Keep Qt's interpolation, advance it on a GUI timer.
    animation.pause()
    self._animation_started[animation] = time.monotonic()
    if not self._animation_clock.isActive():
        self._animation_clock.start()

def advance_row_animations(self, *, finish=False) -> None:
    now = time.monotonic()
    for animation, started in list(self._animation_started.items()):
        if not isValid(animation):
            self._animation_started.pop(animation, None)
            continue
        duration = animation.duration()
        elapsed = duration if finish else min(duration, round((now - started) * 1000))
        animation.setCurrentTime(elapsed)
        if elapsed >= duration:
            animation.stop()
            self._animation_started.pop(animation, None)
    if not self._animation_started:
        self._animation_clock.stop()
