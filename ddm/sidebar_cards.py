"""Compatibility exports for follow-card components, in their original Qt subclass order."""
import os
import time
from PySide6.QtCore import (
    QEasingCurve, QMimeData, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, QTimer,
    Qt, Signal
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRegion
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy,
    QWidget
)

from shiboken6 import isValid

from . import motion, theme
from .avatar_widgets import Avatar
from .corner_geometry import continuous_path
from .player import TilePlayer
from .sidebar_drag import FOLDER_MIME, NAV_MIME, ROOM_MIME
from .ui.labels import ElidedLabel
from .widget_support import (
    BRAND_ASSETS_DIR, CAROUSEL_WIDTH, NAV_COMPACT_ITEM_HEIGHT, NAV_ITEM_GAP, NAV_ITEM_HEIGHT,
    NAV_LIST_ITEM_HEIGHT, PORTRAIT_LIST_HEIGHT, PORTRAIT_LIST_WIDTH, _allow_shrink, _ignore_mouse,
    _repolish
)

# Keep existing imported helpers/values and canonical class identities available.
from .live_alert import LiveAlert
from .sidebar_thumbnail import NavThumb
from .sidebar_item import NavSelectionCheck, NavItem
from .sidebar_folders import SmartFolderDialog, SmartFolderCard, FollowFolderButton
from .sidebar_list import RoomListBox, CarouselScroll
