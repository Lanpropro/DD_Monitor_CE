"""加载 Qt 自带中文翻译，统一标准控件和网页控件的默认菜单。"""
from pathlib import Path

import PySide6
from PySide6.QtCore import QTranslator


def install_chinese_translations(app):
    if getattr(app, "_chinese_translators", None):
        return
    directory = Path(PySide6.__file__).parent / "translations"
    app._chinese_translators = []
    for catalog in ("qtbase_zh_CN", "qtwebengine_zh_CN"):
        translator = QTranslator(app)
        if translator.load(str(directory / f"{catalog}.qm")):
            app.installTranslator(translator)
            app._chinese_translators.append(translator)
