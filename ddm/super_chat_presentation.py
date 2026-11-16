"""Super Chat layout, preview, avatar and drawing helpers."""
from __future__ import annotations
import time
import math
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTextCharFormat, QTextCursor, QTextDocument, QTextOption, QTransform
from PySide6.QtWidgets import QApplication
from .corner_geometry import continuous_path
from . import motion, theme
from .images import AvatarLoader, load_cached_image
from .skin_preview import SkinPreview
from .super_chat_model import (SC_USER_COLOR, SC_PRICE_COLOR, SC_CONTENT_COLOR, SC_BODY_PADDING, _number, super_chat_palette)


from .super_chat_layout import (sc_message_document, sc_card_height, sc_card_geometry, sc_placement_rects, sc_stack_rects, paint_sc_background, readable_text_color)


from .super_chat_animation import (SuperChatPresentation)


from .super_chat_preview import (SuperChatPlacementPreview)


from .super_chat_avatar import (SuperChatAvatar, paint_sc_avatar)
