# crb/widgets.py - Clash Rekt Bot controls: toggle switch, setting rows, cards, stat tiles, segments.
#
# Accessibility: every control takes keyboard focus (Tab), shows a focus ring, has an accessible
# name/description (screen readers) and a tooltip; toggles work with Space/Enter; numbers have
# visible -/+ buttons (no tiny spin arrows) and accept typing; hit targets are >= 36 px.
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from crb import icons, theme

_REDUCE_MOTION = {'on': False}


def set_reduce_motion(on):
    _REDUCE_MOTION['on'] = bool(on)


class ToggleSwitch(QAbstractButton):
    """An animated on/off switch. Checkable button: Space/Enter toggles, accessible as a checkbox."""

    def __init__(self, scheme='night', parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._scheme = scheme
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b'offset', self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def set_scheme(self, scheme):
        self._scheme = scheme
        self.update()

    def sizeHint(self):
        return QSize(52, 30)

    def _get_offset(self):
        return self._offset

    def _set_offset(self, v):
        self._offset = v
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked):
        end = 1.0 if checked else 0.0
        if _REDUCE_MOTION['on'] or not self.isVisible():
            self._set_offset(end)
            return
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(end)
        self._anim.start()

    def setChecked(self, on):          # keep the knob in sync when set programmatically
        super().setChecked(on)
        self._set_offset(1.0 if on else 0.0)

    def paintEvent(self, _event):
        c = theme.colors(self._scheme)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = 46, 26
        x, y = 3, (self.height() - h) / 2
        track = QColor(c['primary'] if self.isChecked() else c['track_off'])
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
        knob = h - 6
        kx = x + 3 + self._offset * (w - knob - 6)
        p.setBrush(QColor(c['knob']))
        p.drawEllipse(QRectF(kx, y + 3, knob, knob))
        # on/off glyph inside the track so state is not shown by colour alone
        p.setPen(QPen(QColor(c['primary_text'] if self.isChecked() else c['muted']), 2))
        if self.isChecked():
            p.drawLine(int(x + 12), int(y + 8), int(x + 12), int(y + h - 8))
        else:
            p.drawEllipse(QRectF(x + w - 18, y + 8, 10, 10))
        if self.hasFocus():
            p.setPen(QPen(QColor(c['focus']), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, y - 2, w + 4, h + 4), (h + 4) / 2, (h + 4) / 2)
        p.end()


class Stepper(QWidget):
    """Number input: [-] [ value ] [+] with large buttons; typing works too."""
    valueChanged = Signal(object)

    def __init__(self, kind, minimum, maximum, step, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.minus = QPushButton('−')
        self.plus = QPushButton('+')
        for b in (self.minus, self.plus):
            b.setFixedSize(40, 38)
            b.setAutoRepeat(True)
            b.setStyleSheet('QPushButton { padding: 0px; font-size: 15pt; font-weight: 700; }')
        # A QLineEdit, not a QSpinBox: with a styled border and hidden arrows Qt collapses a spin
        # box's text field to 1 px (Qt bug, seen 11 Nov), so the value was invisible.
        self._float = kind == 'float'
        self._min, self._max, self._step = minimum, maximum, step or 1
        self._sep = maximum >= 10_000
        self._value = minimum
        self.box = QLineEdit()
        self.box.setAlignment(Qt.AlignCenter)
        self.box.setFixedHeight(38)
        self.box.setMinimumWidth(130 if self._sep else 80)
        self.box.setMaximumWidth(170 if self._sep else 110)
        self.box.editingFinished.connect(self._typed)
        self.minus.clicked.connect(lambda: self._step_by(-1))
        self.plus.clicked.connect(lambda: self._step_by(1))
        self.minus.setAccessibleName('Decrease')
        self.plus.setAccessibleName('Increase')
        lay.addWidget(self.minus)
        lay.addWidget(self.box)
        lay.addWidget(self.plus)
        self.setFixedHeight(40)
        self._show()

    def _fmt(self, v):
        if self._float:
            return f'{v:.2f}'
        return f'{int(v):,}' if self._sep else str(int(v))

    def _show(self):
        self.box.setText(self._fmt(self._value))

    def _clamp(self, v):
        v = max(self._min, min(self._max, v))
        return round(v, 2) if self._float else int(v)

    def _set(self, v, emit):
        v = self._clamp(v)
        changed = v != self._value
        self._value = v
        self._show()
        if changed and emit:
            self.valueChanged.emit(v)

    def _step_by(self, direction):
        self._set(self._value + direction * self._step, emit=True)

    def _typed(self):
        raw = self.box.text().replace(',', '').replace(' ', '').strip()
        try:
            v = float(raw) if self._float else int(float(raw))
        except ValueError:
            self._show()                       # not a number: put the old value back
            return
        self._set(v, emit=True)

    def keyPressEvent(self, event):            # arrow keys / PageUp/PageDown step like a spin box
        k = event.key()
        if k in (Qt.Key_Up, Qt.Key_PageUp):
            self._step_by(1 if k == Qt.Key_Up else 10)
        elif k in (Qt.Key_Down, Qt.Key_PageDown):
            self._step_by(-1 if k == Qt.Key_Down else -10)
        else:
            super().keyPressEvent(event)

    def value(self):
        return self._value

    def setValue(self, v):
        try:
            self._set(float(v) if self._float else int(v), emit=False)
        except (TypeError, ValueError):
            pass

    def setAccessibleName(self, name):
        super().setAccessibleName(name)
        self.box.setAccessibleName(name)


class Segmented(QWidget):
    """Few-option choice as a row of buttons (one checked)."""
    valueChanged = Signal(object)

    def __init__(self, choices, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._values = []
        for i, (value, label) in enumerate(choices):
            b = QPushButton(label)
            b.setObjectName('Segment')
            b.setCheckable(True)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self._values.append(value)
        self.group.idClicked.connect(lambda i: self.valueChanged.emit(self._values[i]))

    def value(self):
        i = self.group.checkedId()
        return self._values[i] if i >= 0 else None

    def setValue(self, v):
        if v in self._values:
            self.group.button(self._values.index(v)).setChecked(True)


class Choice(QComboBox):
    valueChanged = Signal(object)

    def __init__(self, choices, parent=None):
        super().__init__(parent)
        self.set_choices(choices)
        self.setMinimumWidth(220)
        self.currentIndexChanged.connect(lambda _i: self.valueChanged.emit(self.value()))

    def set_choices(self, choices):
        cur = self.value() if self.count() else None
        self.blockSignals(True)
        self.clear()
        for value, label in choices:
            self.addItem(label, value)
        if cur is not None:
            self.setValue(cur)
        self.blockSignals(False)

    def value(self):
        return self.currentData()

    def setValue(self, v):
        i = self.findData(v)
        if i >= 0:
            self.setCurrentIndex(i)


class TextField(QLineEdit):
    valueChanged = Signal(object)

    def __init__(self, placeholder='', parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setMinimumWidth(280)
        self.editingFinished.connect(lambda: self.valueChanged.emit(self.text().strip()))

    def value(self):
        return self.text().strip()

    def setValue(self, v):
        self.setText('' if v is None else str(v))


class Card(QFrame):
    """A titled section card."""

    def __init__(self, title='', hint='', icon_name=None, scheme='night', parent=None):
        super().__init__(parent)
        self.setObjectName('Card')
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 16, 20, 16)
        self.body.setSpacing(6)
        if title:
            head = QHBoxLayout()
            head.setSpacing(10)
            if icon_name:
                ic = QLabel()
                ic.setPixmap(icons.pixmap(icon_name, theme.colors(scheme)['primary'], 22))
                head.addWidget(ic)
            t = QLabel(title)
            t.setObjectName('CardTitle')
            head.addWidget(t)
            head.addStretch(1)
            self.head = head
            self.body.addLayout(head)
            if hint:
                h = QLabel(hint)
                h.setObjectName('CardHint')
                h.setWordWrap(True)
                self.body.addWidget(h)
            self.body.addSpacing(4)

    def add(self, w):
        self.body.addWidget(w)
        return w

    def add_divider(self):
        d = QFrame()
        d.setObjectName('Divider')
        self.body.addWidget(d)


class SettingRow(QWidget):
    """Title + help text on the left, the control on the right."""

    def __init__(self, title, help_text, control, parent=None):
        super().__init__(parent)
        self.control = control
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName('RowTitle')
        self.title.setWordWrap(True)
        self.title.setBuddy(control)
        text.addWidget(self.title)
        self.help = QLabel(help_text or '')
        self.help.setObjectName('Help')
        self.help.setWordWrap(True)
        self.help.setVisible(bool(help_text))
        text.addWidget(self.help)
        lay.addLayout(text, 1)
        lay.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        control.setAccessibleName(title)
        control.setAccessibleDescription(help_text or '')
        control.setToolTip(help_text or title)

    def set_available(self, ok, reason=''):
        self.control.setEnabled(ok)
        self.title.setEnabled(ok)
        base = self.control.accessibleDescription()
        self.help.setText(base if ok else (f'{base}  (Needs: {reason})' if reason else base))


class StatTile(QFrame):
    def __init__(self, label, icon_name, color, parent=None):
        super().__init__(parent)
        self.setObjectName('Tile')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(2)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, color, 18))
        top.addWidget(ic)
        lab = QLabel(label)
        lab.setObjectName('StatLabel')
        top.addWidget(lab)
        top.addStretch(1)
        lay.addLayout(top)
        self.value = QLabel('—')
        self.value.setObjectName('StatValue')
        self.value.setAccessibleName(label)
        lay.addWidget(self.value)
        self.sub = QLabel('')
        self.sub.setObjectName('Help')
        lay.addWidget(self.sub)
        self.setMinimumWidth(150)

    def set(self, value, sub=''):
        self.value.setText(value)
        self.sub.setText(sub)


class StatusPill(QLabel):
    """Status text in a coloured pill: the text always says the state (not colour only)."""

    def __init__(self, scheme='night', parent=None):
        super().__init__(parent)
        self._scheme = scheme
        self.set_state('Idle')

    def set_scheme(self, scheme):
        self._scheme = scheme
        self.set_state(self.text().strip('● '))

    def set_state(self, state):
        c = theme.colors(self._scheme)
        color = {'Running': c['success'], 'Paused': c['warning'], 'Stopped': c['muted'],
                 'Idle': c['muted'], 'Error': c['danger'], 'Starting': c['info']}.get(state, c['info'])
        self.setText(f'● {state}')
        self.setAccessibleName(f'Bot status: {state}')
        self.setStyleSheet(f'QLabel {{ color: {color}; border: 1px solid {color}; border-radius: 12px;'
                           f' padding: 4px 12px; font-weight: 700; }}')
