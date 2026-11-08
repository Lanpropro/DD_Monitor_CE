"""插件商店和软件更新页面；联网、下载和解压都在工作线程执行。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRectF, QThread, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea, QStyledItemDelegate, QTextBrowser, QVBoxLayout, QWidget

from .corner_geometry import continuous_path
from . import config, motion, online, plugin_updates, theme, update_install, version
from .ui import ActionButton, AnimatedDialog, ElidedLabel, page_header
from .update_version import installed_revision, release_label


from .update_notice import (UpdateDot, set_update_dot, UpdateNavDelegate, UpdateNotice, _notifications_hidden)


from .update_offers import (plugin_update_offers, plugin_update_notes)


from .online_tasks import (_retired_online_tasks, _release_online_task, _wait_online_tasks_on_exit, OnlineTask, OnlinePage)


from .plugin_store_ui import (PluginBrowserToolbar, PluginDetailsDialog, PluginStorePage)


from .app_update_ui import (AppUpdatePage)


from .result_notice import (ResultNotice, show_result)


