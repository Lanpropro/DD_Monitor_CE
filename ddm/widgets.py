"""Compatibility exports for widgets; implementations live with their UI responsibilities.

Keep exports ordered so existing Qt subclasses load in their original sequence.
"""
import math
import os
import sys
import time
from uuid import uuid4

from PySide6.QtCore import (
    QEasingCurve, QEvent, QMimeData, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize,
    Qt, QTimer, QUrl, Signal, QVariantAnimation
)
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QCursor, QDrag, QFont, QFontMetrics, QIcon, QKeySequence,
    QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPalette, QPen, QPixmap,
    QRegion, QShortcut, QTextDocument, QTextOption
)
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QInputDialog, QLineEdit,
    QMenu, QPushButton, QScrollArea, QSizePolicy, QSlider, QStyle, QTextBrowser, QStyleOption,
    QStyleOptionMenuItem, QStyleOptionToolButton, QToolButton, QVBoxLayout, QWidget, QWidgetAction
)

from .corner_geometry import continuous_path
from . import layouts, motion, resize_layout, theme
from .sidebar_drag import FOLDER_MIME, NAV_MIME, ROOM_MIME, SidebarDrag
from .workspace_controls import WorkspaceControls
from .sidebar_navigation import NavigationButton, RAIL_WIDTH, SidebarNavigation
from .dock_feedback import icon_color
# Keep existing imports of avatar components compatible.
from .avatar_widgets import AVATAR_COLORS, Avatar, PinnedArc, RoomStrip, circular_pixmap
from .config import (
    DEFAULT_SETTINGS, DEFAULT_VOLUME, VIDEO_DANMAKU_SETTING_KEYS, codec_overrides,
    video_danmaku_overrides
)
from . import version as version_module
from .auto_quality import AUTO_QUALITY, OVERSEAS_PLATFORMS
from .images import AvatarLoader
from .danmaku_content import content_runs, content_html
from . import follow_folders
from .watch_history import SORT_TIP, WatchHistory
from .folder_icons import FolderIconDialog, create_folder_dialog, folder_icon
from .search import matches_text
from .player import TilePlayer
from .video_surface import VideoCorner, VideoSurface
from .badge_surface import BadgeSurface
# Preserve existing badge imports while keeping these components independent.
from .playback_badges import (
    ASSETS_DIR, BADGE_HEIGHT, HOLE_MARGIN, HOLE_SIZE, LoadingIndicator, LoadingLabel, StreamBadge,
    TimeBadge, TitleBadge, _badge_font
)
# Preserve legacy control imports and shared drawing helpers.
from .playback_controls import (
    DanmakuToggleButton, PauseButton, RecordingButton, RefreshButton, SidebarToggleButton,
    TileButton, VolumeButton, VolumePopup, _draw_arrow_head, _icon_color
)
from .fullscreen_bar import FullscreenBar
from .fullscreen_cursor import set_native_cursor
from .video_danmaku import VideoDanmaku
from .video_danmaku_settings import VideoDanmakuSettings
from .super_chat_avatar import SuperChatAvatar, paint_sc_avatar
from .super_chat_animation import SuperChatPresentation
from .super_chat_layout import paint_sc_background, sc_stack_rects, sc_card_height, sc_placement_rects
from .super_chat_model import format_price, format_remaining, super_chat_palette, SC_USER_COLOR, SC_PRICE_COLOR, SC_CONTENT_COLOR, remaining_seconds, order_super_chats, SC_BODY_PADDING

from .widget_support import (
    BRAND_ASSETS_DIR, CAROUSEL_WIDTH, DANMAKU_MIME, NAV_COMPACT_ITEM_HEIGHT, NAV_ITEM_GAP,
    NAV_ITEM_HEIGHT, NAV_LIST_ITEM_HEIGHT, PORTRAIT_LIST_HEIGHT, PORTRAIT_LIST_WIDTH,
    QUALITY_CHOICES, QUALITY_NAMES, TILE_BAR_HEIGHT, TILE_MIME, WATCHING_TEXT, _allow_shrink,
    _ignore_mouse, _repolish, rounded_pixmap
)


from .danmaku_widgets import (
    _brightness, _is_running, _medal_chip, DanmakuTextBrowser, DanmakuBottomButton,
    SuperChatAvatarView, SuperChatMessage, SuperChatCard, SuperChatStack, DanmakuConnectionIcon,
    DanmakuPanel, _escape
)


# Keep Qt subclass loading in the same order as the original definitions.
from .ui.labels import ElidedLabel


from .account_widgets import (AccountPopupMenu, AccountRow)


from .sidebar_cards import (
    LiveAlert, NavThumb, NavSelectionCheck, NavItem, SmartFolderDialog, SmartFolderCard,
    FollowFolderButton, RoomListBox, CarouselScroll
)


# Preserve the original toolbar subclass loading order.
from .ui.toolbar import BarIconButton


from .sidebar_widgets import (AppearanceButton, Sidebar)


from .tile_widgets import (Tile)


from .wall_widgets import (best_columns, WallPaneBorder, WallResizePreview, WallGrid)


from .layout_picker import (LayoutPicker)

