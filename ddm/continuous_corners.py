"""Continuous rectangular surfaces while Qt retains control contents and geometry.

Qt style sheets only expose circular corner arcs. Keep their layout and text
rules, and draw the rectangular fills/outlines with one shared path instead.
"""
from functools import lru_cache
from hashlib import sha256
import re
from weakref import WeakKeyDictionary

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QAbstractItemView, QCheckBox, QMenu,
                              QStyle, QStyleOptionButton, QWidget)


from .corner_geometry import continuous_path


_RULE = re.compile(r'([^{}]+)\{([^{}]*)\}')
_COMMENT = re.compile(r'/\*.*?\*/', re.S)
_ATTR = re.compile(r'\[([\w-]+)(?:\s*=\s*[\"\']?([^\]"\']*)[\"\']?)?\]')
_STATE = re.compile(r'(?<!:):(?!:)(!?[\w-]+)')
_compiled = {}
_roots = set()
_ancestor_properties = set()
_filter = None


def _terminal(selector):
    return re.sub(r'\[[^]]*\]|(?<!:):(?!:)[!\w-]+', '', selector.split()[-1])


@lru_cache(maxsize=128)
def _rules(source):
    source = _COMMENT.sub('', source)
    if '{' not in source and ':' in source:
        source = '* {' + source + '}'
    result = []
    for selectors, body in _RULE.findall(source):
        declarations = {}
        for declaration in body.split(';'):
            if ':' in declaration:
                key, value = declaration.split(':', 1)
                declarations[key.strip()] = value.strip()
        for selector in selectors.split(','):
            selector = selector.strip()
            if selector:
                for part in selector.split()[:-1]:
                    _ancestor_properties.update(name for name, _value in _ATTR.findall(part))
                specificity = (selector.count('#')*100 +
                    (len(_ATTR.findall(selector))+len(_STATE.findall(selector)))*10 +
                    len(re.findall(r'(?:^|\s|>)Q\w+', selector)))
                result.append((selector, declarations, specificity))
    return result


def source_stylesheet(style):
    return _compiled.get(style, (style, ()))[0]


def stylesheet(source, *, application=False):
    """Convert surface rules only; padding, border widths and content stay in QSS."""
    if not source or source in _compiled:
        return source
    rules = _rules(source)
    local_roots = {_terminal(s) for s, d, _n in rules
                   if any(k.startswith('border-') and k.endswith('radius') for k in d)}
    if application:
        _roots.update(local_roots - {'*'})
    affected = local_roots | _roots
    result = []
    changed = False
    for selector, declarations, _specificity in rules:
        values = dict(declarations)
        terminal = _terminal(selector)
        # Sliders, radio buttons and scrollbar handles intentionally stay circular.
        supported = ('::' not in terminal or terminal.endswith('::item') or
                     terminal in ('QCheckBox::indicator', '#NavCheck::indicator'))
        if terminal in affected and supported:
            for key, value in list(values.items()):
                if key in ('background', 'background-color') and not value.startswith(('url(', 'qlineargradient', 'qradialgradient')):
                    values[key] = 'transparent'
                    changed = True
                elif key == 'border' or re.fullmatch(r'border-(top|right|bottom|left)', key):
                    if value not in ('none', '0', '0px'):
                        values[key] = re.sub(r'(#[\da-fA-F]+|rgba?\([^)]*\)|palette\([^)]*\)|[a-zA-Z]+)$',
                                             'transparent', value)
                        changed = True
                elif key.startswith('border-') and key.endswith('color'):
                    values[key] = 'transparent'
                    changed = True
                elif key.startswith('border-') and key.endswith('radius'):
                    values[key] = '0'
                    changed = True
                elif key == 'border-image':
                    values[key] = 'none'
                    changed = True
        result.append(selector+' {'+';'.join(k+':'+v for k,v in values.items())+';}')
    if not changed:
        return source
    # Different fills/radii can reduce to the same native transparent QSS.
    # Keep their source recipes distinct without adding a dynamic Qt property.
    rendered = '\n'.join(result) + '\n/* continuous:'+sha256(source.encode()).hexdigest()[:20]+' */'
    _compiled[rendered] = (source, rules)
    app = QApplication.instance()
    if app is not None:
        install(app)
    return rendered


def _states(widget):
    return {'hover': widget.underMouse(), 'focus': widget.hasFocus(),
            'disabled': not widget.isEnabled(),
            'pressed': getattr(widget, 'isDown', lambda: False)(),
            'checked': getattr(widget, 'isChecked', lambda: False)(),
            'selected': False, 'horizontal': True, 'vertical': False}


@lru_cache(maxsize=128)
def _indexed(source):
    by_id, by_type = {}, {}
    rules = _compiled.get(source)
    rules = rules[1] if rules is not None else _rules(source)
    for index, rule in enumerate(rules):
        terminal = rule[0].split()[-1]
        identity = re.search(r'#([\w-]+)', terminal)
        if identity:
            by_id.setdefault(identity[1], []).append((index, rule))
        else:
            kind = re.match(r'\w+|\*', terminal)
            by_type.setdefault(kind[0] if kind else '*', []).append((index, rule))
    return by_id, by_type


def _simple(widget, selector, states, subcontrol):
    controls = re.findall(r'::([\w-]+)', selector)
    if (controls[0] if controls else '') != subcontrol:
        return False
    for name, value in _ATTR.findall(selector):
        actual = widget.property(name)
        if value:
            actual = str(actual).lower() if isinstance(actual, bool) else str(actual)
            if actual != value.strip():
                return False
        elif actual is None:
            return False
    for state in _STATE.findall(selector):
        if bool(states.get(state.lstrip('!'), False)) == state.startswith('!'):
            return False
    bare = re.sub(r'\[[^]]*\]|::[\w-]+|(?<!:):(?!:)[!\w-]+', '', selector)
    identity = re.search(r'#([\w-]+)', bare)
    if identity and widget.objectName() != identity[1]:
        return False
    kind = bare.split('#', 1)[0]
    return not kind or kind == '*' or widget.inherits(kind)


def _matches(widget, selector, states, subcontrol=''):
    parts = selector.replace('>', ' > ').split()
    if not parts or not _simple(widget, parts[-1], states, subcontrol):
        return False
    index = len(parts)-2
    parent = widget.parentWidget()
    while index >= 0:
        direct = parts[index] == '>'
        if direct:
            index -= 1
        while parent is not None and not _simple(parent, parts[index], _states(parent), ''):
            if direct:
                return False
            parent = parent.parentWidget()
        if parent is None:
            return False
        parent = parent.parentWidget()
        index -= 1
    return True


def _color(value, palette):
    from . import theme
    if value in ('none', '', 'transparent'):
        return QColor(Qt.transparent)
    match = re.fullmatch(r'palette\(([^)]+)\)', value)
    if match:
        roles = {name.lower().replace('_',''): role for name, role in QPalette.ColorRole.__members__.items()}
        # QSS's transparent native background changes a widget's Base/Button
        # brushes. These tokens belong to the application's stable theme palette.
        return QApplication.palette().color(roles[match[1].replace('-','')])
    color = theme.qcolor(value)
    if value.startswith('rgba('):
        color.setAlpha(int(float(value[5:-1].split(',')[-1])*255))
    return color


def _number(value):
    match = re.match(r'[\d.]+', value)
    return float(match[0]) if match else 0


@lru_cache(maxsize=32)
def _image(path):
    return QPixmap(path)


def _paint(painter, rect, values, palette):
    radius = _number(values.get('border-radius', '0'))
    radii = tuple(_number(values.get('border-'+corner+'-radius', str(radius)))
                  for corner in ('top-left','top-right','bottom-right','bottom-left'))
    if not any(key.endswith('radius') for key in values):
        return False
    border = values.get('border', 'none').split(maxsplit=2)
    width = _number(values.get('border-width', border[0]))
    color = values.get('border-color', border[2] if len(border)>2 else 'transparent')
    fill = values.get('background-color', values.get('background', 'transparent'))
    if fill.startswith(('url(', 'qlineargradient', 'qradialgradient')):
        return False
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(_color(color, palette), width) if width else QPen(Qt.NoPen)
    border_style = values.get('border-style', border[1] if len(border)>1 else 'solid')
    pen.setStyle({'dashed':Qt.DashLine,'dotted':Qt.DotLine,'none':Qt.NoPen}.get(border_style,pen.style()))
    painter.setPen(pen)
    painter.setBrush(_color(fill, palette))
    inset = width/2
    surface = QRectF(rect).adjusted(inset, inset, -inset, -inset)
    path = continuous_path(surface, max(0, radius-inset), corners=(
        tuple(max(0,r-inset) for r in radii) if len(set(radii))>1 else None))
    if len(set(radii)) == 1 and radius >= min(rect.width(),rect.height())/2-1:
        path = QPainterPath()
        path.addRoundedRect(surface, max(0,radius-inset), max(0,radius-inset))
    painter.drawPath(path)
    image = re.search(r'url\(["\']?([^\)"\']+)["\']?\)', values.get('border-image',''))
    if image:
        painter.save()
        painter.setClipPath(path)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(rect), _image(image[1]), QRectF(_image(image[1]).rect()))
        painter.restore()
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
    for side, start, end in (
            ('top', surface.topLeft(), surface.topRight()),
            ('right', surface.topRight(), surface.bottomRight()),
            ('bottom', surface.bottomLeft(), surface.bottomRight()),
            ('left', surface.topLeft(), surface.bottomLeft())):
        edge = values.get('border-'+side, '').split(maxsplit=2)
        if len(edge) == 3 and _number(edge[0]):
            painter.setClipPath(path)
            painter.setPen(QPen(_color(edge[2], palette), _number(edge[0])))
            painter.drawLine(start, end)
    painter.restore()
    return True


class SurfaceFilter(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.cache = WeakKeyDictionary()
        self.changing = False
        self.global_style = app.styleSheet()

    def values(self, widget, subcontrol='', overrides=None):
        states = _states(widget)
        states.update(overrides or {})
        sources = [self.global_style]
        ancestors = []
        current = widget
        while current is not None:
            ancestors.append(current)
            current = current.parentWidget()
        sources.extend(w.styleSheet() for w in reversed(ancestors) if w.styleSheet())
        key = widget.objectName(), subcontrol, tuple(states.items()), tuple(sources)
        cached = self.cache.setdefault(widget, {})
        if key in cached:
            return cached[key]
        result = {}
        for source in sources:
            by_id, by_type = _indexed(source)
            candidates = list(by_id.get(widget.objectName(), ()))
            for kind, rows in by_type.items():
                if kind == '*' or widget.inherits(kind):
                    candidates.extend(rows)
            matched = [(priority, i, values) for i, (selector, values, priority) in candidates
                       if _matches(widget, selector, states, subcontrol)]
            for _priority, _index, values in sorted(matched, key=lambda row: row[:2]):
                if 'border' in values:
                    for prop in tuple(result):
                        if prop.startswith('border-') and not prop.endswith('radius'):
                            result.pop(prop)
                result.update(values)
        cached[key] = result
        return result

    def eventFilter(self, widget, event):
        if not isinstance(widget, QWidget):
            return False
        kind = event.type()
        if kind in (QEvent.Polish, QEvent.StyleChange) and not self.changing:
            source = widget.styleSheet()
            rendered = stylesheet(source)
            if rendered != source:
                self.changing = True
                try:
                    widget.setStyleSheet(rendered)
                finally:
                    self.changing = False
            self.global_style = QApplication.instance().styleSheet()
            self.cache.pop(widget, None)
        elif kind in (QEvent.DynamicPropertyChange, QEvent.ParentChange, QEvent.EnabledChange):
            if kind == QEvent.DynamicPropertyChange and bytes(event.propertyName()).decode() in _ancestor_properties:
                self.cache.clear()
            else:
                self.cache.pop(widget, None)
        elif kind == QEvent.Paint:
            values = self.values(widget)
            if not widget.property('tileButton') and any(key.endswith('radius') for key in values):
                painter = QPainter(widget)
                _paint(painter, widget.rect(), values, widget.palette())
                painter.end()
            if isinstance(widget, QMenu) and widget.activeAction() is not None:
                painter = QPainter(widget)
                _paint(painter, widget.actionGeometry(widget.activeAction()),
                       self.values(widget, 'item', {'selected':True}), widget.palette())
                painter.end()
            if isinstance(widget, QCheckBox):
                option = QStyleOptionButton()
                widget.initStyleOption(option)
                rect = widget.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, widget)
                painter = QPainter(widget)
                _paint(painter, rect, self.values(widget, 'indicator'), widget.palette())
                painter.end()
            view = widget.parentWidget()
            if (isinstance(view, QAbstractItemView) and widget is view.viewport()
                    and not view.property('customItemSurface')):
                hovered = view.indexAt(widget.mapFromGlobal(QCursor.pos()))
                indexes = view.selectionModel().selectedIndexes()
                if hovered.isValid() and hovered not in indexes:
                    indexes.append(hovered)
                painter = QPainter(widget)
                for index in indexes:
                    rect = view.visualRect(index)
                    if widget.rect().intersects(rect):
                        _paint(painter, rect, self.values(view, 'item', {
                            'selected': view.selectionModel().isSelected(index),
                            'hover': index == hovered}), view.palette())
                painter.end()
        return False


def install(app):
    global _filter
    if _filter is None:
        _filter = SurfaceFilter(app)
        app.installEventFilter(_filter)
