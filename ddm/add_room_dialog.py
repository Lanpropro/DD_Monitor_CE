"""Room link validation and add-to-folder dialog."""
import re
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QLineEdit, QPushButton, QVBoxLayout
from . import theme
from .follow_folders import default_folder
from .motion import AnimatedDialog
from .room_folder_controls import _add_folder_option, _create_folder_for_dialog


class AddRoomDialog(AnimatedDialog):
    """输入房间号或直播间链接。"""

    def __init__(self, parent=None, *, room_id_resolver=None, folders=None, folder_creator=None):
        super().__init__(parent)
        self.setWindowTitle("添加直播间")
        self.resize(400, 170)
        self.room_id = ""
        self.folder_id = ""
        self.room_id_resolver = room_id_resolver
        self.folder_names = {folder['name'] for folder in folders or []}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("房间号或直播间链接"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("输入房间号或链接")
        self.edit.returnPressed.connect(self.accept)
        layout.addWidget(self.edit)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("添加到文件夹"))
        self.folder_button = QPushButton(default_folder(folders)["name"])
        self.folder_button.setObjectName("IconButton")
        self.folder_button.setToolTip("选择普通文件夹；智能文件夹会按规则自动归类")
        folder_menu = QMenu(self.folder_button)
        options = [("", default_folder(folders)["name"])] + [(folder["id"], folder["name"]) for folder in folders or []
                                       if folder.get("type", "normal") == "normal"]
        for folder_id, name in options:
            _add_folder_option(self, folder_menu, folder_id, name)
        self.folder_button.setMenu(folder_menu)
        folder_row.addWidget(self.folder_button, 1)
        self.new_folder_button = QPushButton("新建文件夹")
        self.new_folder_button.setObjectName("IconButton")
        self.new_folder_button.setAutoDefault(False)
        self.new_folder_button.setEnabled(folder_creator is not None)
        self.new_folder_button.clicked.connect(lambda: _create_folder_for_dialog(self, folder_creator))
        folder_row.addWidget(self.new_folder_button)
        layout.addLayout(folder_row)

        self.hint = QLabel("支持 B 站房间号")
        self.hint.setObjectName("AppSubtitle")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("添加")
        confirm.setObjectName("PrimaryButton")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

    def _select_folder(self, action) -> None:
        self.folder_id = action.data()
        self.folder_button.setText(action.text())
        for option in self.folder_button.menu().actions():
            option.setChecked(option is action)

    def accept(self) -> None:
        text = self.edit.text().strip()
        from .room_input import bili_room_id, extract_room_input, is_bili_short_url
        try:
            text = extract_room_input(text)
        except ValueError as error:
            self.hint.setText(str(error))
            self.hint.setStyleSheet(f"color: {theme.ERROR}")
            return
        if self.room_id_resolver is not None:
            try:
                room_id = self.room_id_resolver(text)
            except ValueError as error:
                self.hint.setText(str(error))
                self.hint.setStyleSheet(f"color: {theme.ERROR}")
                return
            if room_id:
                self.room_id = room_id
                super().accept()
                return
        # Short links are expanded later by the existing background info query.
        room_id = text if is_bili_short_url(text) else bili_room_id(text)
        if not room_id and '://' not in text:
            digits = re.findall(r"\d+", text)
            room_id = digits[0] if len(digits) == 1 else ""
        if not room_id:
            self.hint.setText("没识别到房间号，请检查输入")
            self.hint.setStyleSheet(f"color: {theme.ERROR}")
            return
        self.room_id = room_id
        super().accept()
