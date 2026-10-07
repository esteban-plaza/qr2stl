"""Widgets propios con animaciones, pintados con la paleta del sistema (modo claro/oscuro)."""
from PySide6.QtCore import (Property, QEasingCurve, QEvent, QParallelAnimationGroup, QPointF,
                            QPropertyAnimation, QRectF, QSize, Qt, QTimer, QVariantAnimation,
                            Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QAbstractButton, QColorDialog, QDoubleSpinBox, QFileDialog,
                               QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QSizePolicy,
                               QSlider, QVBoxLayout, QWidget)

QWIDGETSIZE_MAX = 16777215
FAST = 160
MEDIUM = 260


# ---------------------------------------------------------------- colores
def accent(widget):
    pal = widget.palette()
    try:
        return pal.color(QPalette.Accent)
    except AttributeError:  # Qt < 6.6
        return pal.color(QPalette.Highlight)


def is_dark(widget):
    return widget.palette().color(QPalette.Window).lightnessF() < 0.5


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t,
                           a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t,
                           a.alphaF() + (b.alphaF() - a.alphaF()) * t)


def with_alpha(c: QColor, alpha: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(alpha)
    return c


def secondary_text(widget):
    return with_alpha(widget.palette().color(QPalette.WindowText), 0.55)


# ---------------------------------------------------------------- switch
class ToggleSwitch(QAbstractButton):
    """Interruptor estilo macOS: la perilla se desliza y el fondo pasa al color de acento."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(MEDIUM)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(38, 22)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = 22.0
        r = QRectF(0, (self.height() - h) / 2, 38, h)
        off = QColor(255, 255, 255, 40) if is_dark(self) else QColor(0, 0, 0, 30)
        on = accent(self)
        if not self.isEnabled():
            on = with_alpha(on, 0.4)
        p.setPen(Qt.NoPen)
        p.setBrush(mix(off, on, self._pos))
        p.drawRoundedRect(r, h / 2, h / 2)
        d = h - 4
        x = r.left() + 2 + (r.width() - d - 4) * self._pos
        knob = QRectF(x, r.top() + 2, d, d)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(knob.translated(0, 0.8))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(knob)
        if self.hasFocus():
            p.setPen(QPen(with_alpha(on, 0.5), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), h / 2 + 1.5, h / 2 + 1.5)


# ---------------------------------------------------------------- control segmentado
class SegmentedControl(QWidget):
    """Control segmentado: la «pastilla» seleccionada se desliza hasta la opción elegida."""
    currentChanged = Signal(int)

    def __init__(self, options, current=0, parent=None):
        super().__init__(parent)
        self.options = list(options)
        self._current = current
        self._hover = -1
        self._pill = QRectF()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(MEDIUM)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_pill)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(sum(fm.horizontalAdvance(o) + 24 for o in self.options) + 4, 28)

    def currentIndex(self):
        return self._current

    def setCurrentIndex(self, i, animate=True):
        if i == self._current or not 0 <= i < len(self.options):
            return
        self._current = i
        target = self._segment(i)
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._pill)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._pill = target
            self.update()
        self.currentChanged.emit(i)

    def _segment(self, i):
        w = (self.width() - 4) / max(1, len(self.options))
        return QRectF(2 + i * w, 2, w, self.height() - 4)

    def _on_pill(self, rect):
        self._pill = rect
        self.update()

    def resizeEvent(self, event):
        self._anim.stop()
        self._pill = self._segment(self._current)
        super().resizeEvent(event)

    def mouseMoveEvent(self, event):
        i = int((event.position().x() - 2) / ((self.width() - 4) / len(self.options)))
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, _event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        i = int((event.position().x() - 2) / ((self.width() - 4) / len(self.options)))
        self.setCurrentIndex(max(0, min(len(self.options) - 1, i)))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            step = -1 if event.key() == Qt.Key_Left else 1
            self.setCurrentIndex(max(0, min(len(self.options) - 1, self._current + step)))
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = is_dark(self)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22) if dark else QColor(0, 0, 0, 18))
        p.drawRoundedRect(QRectF(self.rect()), 7, 7)
        w = (self.width() - 4) / len(self.options)
        if 0 <= self._hover < len(self.options) and self._hover != self._current:
            p.setBrush(QColor(255, 255, 255, 14) if dark else QColor(0, 0, 0, 10))
            p.drawRoundedRect(self._segment(self._hover), 5, 5)
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawRoundedRect(self._pill.translated(0, 0.6), 5, 5)
        p.setBrush(QColor(255, 255, 255, 52) if dark else QColor("#ffffff"))
        p.drawRoundedRect(self._pill, 5, 5)
        text = self.palette().color(QPalette.WindowText)
        for i, label in enumerate(self.options):
            cell = QRectF(2 + i * w, 0, w, self.height())
            f = QFont(self.font())
            # el peso de la etiqueta acompaña a la pastilla mientras se desliza
            closeness = max(0.0, 1.0 - abs(self._pill.center().x() - cell.center().x()) / w)
            f.setWeight(QFont.Weight(int(400 + 200 * closeness)))
            p.setFont(f)
            p.setPen(mix(with_alpha(text, 0.7), text, closeness))
            p.drawText(cell, Qt.AlignCenter, label)
        if not self.isEnabled():
            p.fillRect(self.rect(), with_alpha(self.palette().color(QPalette.Window), 0.5))


# ---------------------------------------------------------------- slider + número
class SliderField(QWidget):
    """Etiqueta, campo numérico y slider sincronizados. Emite `valueChanged(float)`."""
    valueChanged = Signal(float)

    def __init__(self, label, value, lo, hi, step, decimals=1, suffix=" mm", tooltip="",
                 parent=None):
        super().__init__(parent)
        self._step = step
        self._lo = lo
        self._sync = False

        self.label = QLabel(label)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setAlignment(Qt.AlignRight)
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(92)
        self.spin.setAccelerated(True)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, round((hi - lo) / step))
        self.slider.setCursor(Qt.PointingHandCursor)
        if tooltip:
            for w in (self.label, self.spin, self.slider):
                w.setToolTip(tooltip)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.label, 1)
        top.addWidget(self.spin)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(2)
        lay.addLayout(top)
        lay.addWidget(self.slider)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(MEDIUM)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda v: self._set_slider(int(round(v))))

        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.setValue(value, animate=False)

    def value(self):
        return self.spin.value()

    def setValue(self, v, animate=True):
        self._sync = True
        self.spin.setValue(v)
        self._sync = False
        self._slide_to(v, animate)
        self.valueChanged.emit(self.spin.value())

    def _slide_to(self, v, animate):
        target = round((v - self._lo) / self._step)
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(float(self.slider.value()))
            self._anim.setEndValue(float(target))
            self._anim.start()
        else:
            self._set_slider(target)

    def _set_slider(self, i):
        self._sync = True
        self.slider.setValue(i)
        self._sync = False

    def _from_slider(self, i):
        if self._sync:
            return
        self._sync = True
        self.spin.setValue(self._lo + i * self._step)
        self._sync = False
        self.valueChanged.emit(self.spin.value())

    def _from_spin(self, v):
        if self._sync:
            return
        self._slide_to(v, True)  # escrito a mano: el slider viaja hasta el valor
        self.valueChanged.emit(v)


# ---------------------------------------------------------------- triángulo de despliegue
class Disclosure(QWidget):
    """Chevron que rota 90° al desplegar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._angle = 0.0

    def _get(self):
        return self._angle

    def _set(self, a):
        self._angle = a
        self.update()

    angle = Property(float, _get, _set)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(7, 7)
        p.rotate(self._angle)
        pen = QPen(secondary_text(self), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath(QPointF(-2, -4))
        path.lineTo(2.5, 0)
        path.lineTo(-2, 4)
        p.drawPath(path)


class Section(QWidget):
    """Sección del inspector: encabezado con chevron (y opcionalmente un switch) y un
    contenido que se despliega animando la altura y la opacidad."""
    toggled = Signal(bool)

    def __init__(self, title, expanded=True, switch=None, parent=None):
        super().__init__(parent)
        self._expanded = expanded
        self.switch = None

        self.header = QWidget()
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.installEventFilter(self)
        self.chevron = Disclosure()
        self.chevron.angle = 90.0 if expanded else 0.0
        self.title = QLabel(title)
        f = self.title.font()
        f.setWeight(QFont.DemiBold)
        self.title.setFont(f)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(0, 8, 0, 8)
        hl.setSpacing(6)
        hl.addWidget(self.chevron)
        hl.addWidget(self.title, 1)
        if switch is not None:
            self.switch = ToggleSwitch(switch)
            self.switch.toggled.connect(self._on_switch)
            hl.addWidget(self.switch)

        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(20, 0, 0, 10)
        self.content.setSpacing(8)
        if not expanded:
            self.body.setMaximumHeight(0)
            self.body.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.body)

        self._group = None

    def addWidget(self, w):
        self.content.addWidget(w)
        return w

    def addLayout(self, lay):
        self.content.addLayout(lay)
        return lay

    def isExpanded(self):
        return self._expanded

    def eventFilter(self, obj, event):
        if obj is self.header and event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                self.setExpanded(not self._expanded)
            return True
        return super().eventFilter(obj, event)

    def _on_switch(self, on):
        if self.switch is not None:
            self.body.setEnabled(on)
        self.setExpanded(on)
        self.toggled.emit(on)

    def setExpanded(self, on, animate=True):
        if on == self._expanded and self._group is None:
            return
        self._expanded = on
        if self._group is not None:
            self._group.stop()
            self._group = None
        if not animate or not self.isVisible():
            self.chevron.angle = 90.0 if on else 0.0
            self.body.setGraphicsEffect(None)
            self.body.setMaximumHeight(QWIDGETSIZE_MAX if on else 0)
            self.body.setVisible(on)
            return
        self.body.show()
        start = self.body.height() if self.body.maximumHeight() else 0
        end = self.body.sizeHint().height() if on else 0
        effect = QGraphicsOpacityEffect(self.body)
        self.body.setGraphicsEffect(effect)

        group = QParallelAnimationGroup(self)
        h = QPropertyAnimation(self.body, b"maximumHeight")
        h.setDuration(MEDIUM)
        h.setStartValue(start)
        h.setEndValue(end)
        h.setEasingCurve(QEasingCurve.OutCubic if on else QEasingCurve.InOutCubic)
        o = QPropertyAnimation(effect, b"opacity")
        o.setDuration(MEDIUM)
        o.setStartValue(effect.opacity() if not on else 0.0)
        o.setEndValue(1.0 if on else 0.0)
        c = QPropertyAnimation(self.chevron, b"angle")
        c.setDuration(MEDIUM)
        c.setEndValue(90.0 if on else 0.0)
        c.setEasingCurve(QEasingCurve.OutCubic)
        for a in (h, o, c):
            group.addAnimation(a)

        def done():
            self._group = None
            self.body.setGraphicsEffect(None)
            if on:
                self.body.setMaximumHeight(QWIDGETSIZE_MAX)
            else:
                self.body.hide()

        group.finished.connect(done)
        self._group = group
        group.start()


class Separator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), with_alpha(self.palette().color(QPalette.WindowText), 0.1))


# ---------------------------------------------------------------- avisos
class Banner(QWidget):
    """Lista de avisos que aparece y desaparece animando su altura."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addWidget(self.label)
        self._level = "warn"
        self.setMaximumHeight(0)
        self._anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._anim.setDuration(MEDIUM)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._shown = False

    def show_messages(self, messages, level="warn"):
        self._level = level
        if messages:
            icon = "⚠︎" if level == "warn" else "✕"
            self.label.setText("<br>".join(f"{icon}&nbsp; {m}" for m in messages))
            self.update()
            self._animate(self.heightForWidth(self.width()) if self.width() > 0
                          else self.sizeHint().height())
        else:
            self._animate(0)

    def heightForWidth(self, w):
        m = self.layout().contentsMargins()
        return self.label.heightForWidth(w - m.left() - m.right()) + m.top() + m.bottom()

    def _animate(self, end):
        self._shown = end > 0
        self._anim.stop()
        self._anim.setStartValue(self.maximumHeight())
        self._anim.setEndValue(end)
        self._anim.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._shown and self._anim.state() != QPropertyAnimation.Running:
            self.setMaximumHeight(self.heightForWidth(self.width()))

    def paintEvent(self, _event):
        if self.height() < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = QColor("#ff9f0a") if self._level == "warn" else QColor("#ff453a")
        p.setPen(QPen(with_alpha(base, 0.45), 1))
        p.setBrush(with_alpha(base, 0.16 if is_dark(self) else 0.12))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)


# ---------------------------------------------------------------- toast
class Toast(QWidget):
    """Notificación flotante que sube y se desvanece; opcionalmente con una acción."""

    def __init__(self, parent, anchor=None):
        super().__init__(parent)
        self.anchor = anchor  # widget sobre el que se centra (por defecto, el padre)
        self.label = QLabel()
        self.label.setStyleSheet("color: white;")
        f = self.label.font()
        f.setWeight(QFont.Medium)
        self.label.setFont(f)
        self.action = QLabel()
        self.action.setStyleSheet("color: #64d2ff; font-weight: 600;")
        self.action.setCursor(Qt.PointingHandCursor)
        self.action.installEventFilter(self)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(14)
        lay.addWidget(self.label)
        lay.addWidget(self.action)
        self._callback = None
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self.hide()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._group = None

    def eventFilter(self, obj, event):
        if obj is self.action and event.type() == QEvent.MouseButtonRelease:
            if self._callback:
                self._callback()
            self.dismiss()
            return True
        return super().eventFilter(obj, event)

    def show_message(self, text, action=None, callback=None, ms=4500):
        self.label.setText(text)
        self.action.setText(action or "")
        self.action.setVisible(bool(action))
        self._callback = callback
        self.adjustSize()
        self.show()
        self.raise_()
        end = self._target_pos()
        self._run(end + QPointF(0, 24).toPoint(), end, self._effect.opacity(), 1.0,
                  QEasingCurve.OutBack)
        self._timer.start(ms)

    def dismiss(self):
        if not self.isVisible():
            return
        self._timer.stop()
        start = self.pos()
        self._run(start, start + QPointF(0, 16).toPoint(), self._effect.opacity(), 0.0,
                  QEasingCurve.InCubic, hide=True)

    def _target_pos(self):
        par = self.parentWidget()
        area = par.rect()
        if self.anchor is not None:
            area = self.anchor.rect().translated(self.anchor.mapTo(par, self.anchor.rect().topLeft()))
        return QPointF(area.center().x() - self.width() / 2,
                       area.bottom() - self.height() - 72).toPoint()

    def _run(self, p0, p1, o0, o1, curve, hide=False):
        if self._group is not None:
            self._group.stop()
        g = QParallelAnimationGroup(self)
        a = QPropertyAnimation(self, b"pos")
        a.setDuration(380 if not hide else 220)
        a.setStartValue(p0)
        a.setEndValue(p1)
        a.setEasingCurve(curve)
        b = QPropertyAnimation(self._effect, b"opacity")
        b.setDuration(a.duration())
        b.setStartValue(o0)
        b.setEndValue(o1)
        g.addAnimation(a)
        g.addAnimation(b)
        if hide:
            g.finished.connect(self.hide)
        self._group = g
        g.start()

    def reposition(self):
        if self.isVisible() and (self._group is None or
                                 self._group.state() != QParallelAnimationGroup.Running):
            self.move(self._target_pos())

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(QColor(30, 30, 32, 235))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)


# ---------------------------------------------------------------- zona de drop
class DropZone(QWidget):
    """Zona para soltar un archivo (o hacer clic y elegirlo). Se ilumina al arrastrar."""
    fileDropped = Signal(str)

    def __init__(self, title, subtitle, extensions, dialog_filter, parent=None):
        super().__init__(parent)
        self.extensions = tuple(e.lower() for e in extensions)
        self.dialog_filter = dialog_filter
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(96)
        self.title = title
        self.subtitle = subtitle
        self._hover = 0.0
        self._phase = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(FAST)
        self._anim.valueChanged.connect(self._set_hover)
        self._march = QTimer(self)
        self._march.setInterval(16)
        self._march.timeout.connect(self._step)

    def _set_hover(self, v):
        self._hover = v
        self.update()

    def _step(self):
        self._phase = (self._phase + 0.6) % 20
        self.update()

    def _fade(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()
        if on:
            self._march.start()
        else:
            self._march.stop()

    def _path(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            if path.lower().endswith(self.extensions):
                return path
        return None

    def dragEnterEvent(self, event):
        if self._path(event):
            self._fade(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event):
        self._fade(False)

    def dropEvent(self, event):
        self._fade(False)
        path = self._path(event)
        if path:
            event.acceptProposedAction()
            self.fileDropped.emit(path)

    def enterEvent(self, _event):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.45)
        self._anim.start()

    def leaveEvent(self, _event):
        self._fade(False)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        path, _ = QFileDialog.getOpenFileName(self, self.title, "", self.dialog_filter)
        if path:
            self.fileDropped.emit(path)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ac = accent(self)
        idle = secondary_text(self)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(with_alpha(ac, 0.10 * self._hover))
        pen = QPen(mix(with_alpha(idle, 0.5), ac, self._hover), 1.5, Qt.CustomDashLine)
        pen.setDashPattern([5, 5])
        pen.setDashOffset(-self._phase)
        p.setPen(pen)
        p.drawRoundedRect(r, 10, 10)

        # flecha hacia abajo que «cae» un poco al pasar por encima
        cx, cy = r.center().x(), r.top() + 30 + 4 * self._hover
        p.setPen(QPen(mix(idle, ac, self._hover), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(cx, cy - 9), QPointF(cx, cy + 7))
        p.drawLine(QPointF(cx - 6, cy + 1), QPointF(cx, cy + 7))
        p.drawLine(QPointF(cx + 6, cy + 1), QPointF(cx, cy + 7))
        p.drawLine(QPointF(cx - 11, cy + 12), QPointF(cx + 11, cy + 12))

        text = self.palette().color(QPalette.WindowText)
        f = QFont(self.font())
        f.setWeight(QFont.Medium)
        p.setFont(f)
        p.setPen(text)
        p.drawText(QRectF(r.left(), r.top() + 50, r.width(), 20), Qt.AlignCenter, self.title)
        p.setFont(self.font())
        p.setPen(idle)
        p.drawText(QRectF(r.left(), r.top() + 68, r.width(), 20), Qt.AlignCenter, self.subtitle)


# ---------------------------------------------------------------- color
class ColorWell(QAbstractButton):
    """Círculo de color; al hacer clic abre el selector de colores del sistema."""
    colorChanged = Signal(QColor)

    def __init__(self, color, title="Color", parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._title = title
        self._grow = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(30, 30)
        self.clicked.connect(self._pick)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(FAST)
        self._anim.valueChanged.connect(self._set_grow)

    def _set_grow(self, v):
        self._grow = v
        self.update()

    def enterEvent(self, _event):
        self._anim.stop()
        self._anim.setStartValue(self._grow)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, _event):
        self._anim.stop()
        self._anim.setStartValue(self._grow)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def color(self):
        return QColor(self._color)

    def setColor(self, c):
        c = QColor(c)
        if c.isValid() and c != self._color:
            self._color = c
            self.update()
            self.colorChanged.emit(c)

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, self._title)
        if c.isValid():
            self.setColor(c)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = 22 + 4 * self._grow
        r = QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d)
        p.setPen(QPen(with_alpha(self.palette().color(QPalette.WindowText), 0.25), 1))
        p.setBrush(self._color)
        p.drawEllipse(r)


def caption(text):
    """Texto secundario chico, con ajuste de línea."""
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setOpenExternalLinks(True)
    lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
    f = lbl.font()
    f.setPointSizeF(max(9.0, f.pointSizeF() - 1.5))
    lbl.setFont(f)
    lbl.setForegroundRole(QPalette.PlaceholderText)
    return lbl

