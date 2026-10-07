"""Ventana principal: vista 3D a la izquierda e inspector a la derecha, al estilo macOS."""
import os
import subprocess
import sys
from urllib.parse import urlparse

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, QRectF, QSettings, QSize, Qt,
                            QTimer, QUrl, QVariantAnimation, Signal)
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QFontDatabase, QKeySequence, QPainter,
                           QPalette)
from PySide6.QtWidgets import (QDoubleSpinBox, QFileDialog, QFontComboBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
                               QToolBar, QVBoxLayout, QWidget)

from .. import __version__, core, gcode
from ..textshape import text_shape
from .viewer import Viewer
from .widgets import (Banner, ColorWell, DropZone, Section, SegmentedControl, Separator,
                      SliderField, Toast, ToggleSwitch, accent, caption, mix, with_alpha)

REBUILD_MS = 30
ECC_KEYS = list(core.ECC)
PRINTERS = ["Ender 3 · Cura", "Bambu Lab"]
COLOR_PRESETS = [("#f4f4f2", "#1c1c1e"), ("#1c1c1e", "#f4f4f2"), ("#ffd60a", "#1c1c1e"),
                 ("#0a84ff", "#ffffff"), ("#ff375f", "#ffffff"), ("#30d158", "#1c1c1e")]


class PrimaryButton(QPushButton):
    """Botón de acción principal con el color de acento; se aclara al pasar y se hunde al
    apretar (animado)."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = 0.0
        self._press = 0.0
        self._ah = QVariantAnimation(self)
        self._ah.setDuration(150)
        self._ah.valueChanged.connect(lambda v: self._set("_hover", v))
        self._ap = QVariantAnimation(self)
        self._ap.setDuration(90)
        self._ap.valueChanged.connect(lambda v: self._set("_press", v))
        f = self.font()
        f.setWeight(QFont.DemiBold)
        self.setFont(f)
        self.setMinimumHeight(30)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 36, 30)

    def _set(self, attr, v):
        setattr(self, attr, v)
        self.update()

    def _go(self, anim, start, end):
        anim.stop()
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    def enterEvent(self, e):
        self._go(self._ah, self._hover, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._go(self._ah, self._hover, 0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._go(self._ap, self._press, 1.0)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._go(self._ap, self._press, 0.0)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ac = accent(self)
        if not self.isEnabled():
            ac = with_alpha(self.palette().color(QPalette.WindowText), 0.18)
        color = mix(ac, ac.lighter(118), self._hover)
        color = mix(color, ac.darker(115), self._press)
        inset = 1.2 * self._press
        r = QRectF(self.rect()).adjusted(inset + 0.5, inset + 0.5, -inset - 0.5, -inset - 0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 35))
        p.drawRoundedRect(r.translated(0, 0.8), 7, 7)
        p.setBrush(color)
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QColor("white") if self.isEnabled() else
                 with_alpha(self.palette().color(QPalette.WindowText), 0.4))
        p.drawText(r, Qt.AlignCenter, self.text())


class FadeStack(QStackedWidget):
    """QStackedWidget que anima la altura al cambiar de página y solo ocupa el alto de la
    página visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(self._fit)

    def addWidget(self, w):
        i = super().addWidget(w)
        self._fit()
        return i

    def _fit(self, *_):
        for i in range(self.count()):
            page = self.widget(i)
            policy = QSizePolicy.Preferred if i == self.currentIndex() else QSizePolicy.Ignored
            page.setSizePolicy(QSizePolicy.Preferred, policy)
        self.updateGeometry()

    def setCurrentIndexAnimated(self, i):
        if i == self.currentIndex():
            return
        start = self.height()
        self.setCurrentIndex(i)
        end = self.currentWidget().sizeHint().height()
        anim = QPropertyAnimation(self, b"maximumHeight", self)
        anim.setDuration(260)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.finished.connect(lambda: self.setMaximumHeight(16777215))
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def sizeHint(self):
        return self.currentWidget().sizeHint() if self.currentWidget() else super().sizeHint()

    def minimumSizeHint(self):
        return self.currentWidget().minimumSizeHint() if self.currentWidget() else super().minimumSizeHint()


def _row(*widgets, stretch_first=True):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for i, x in enumerate(widgets):
        h.addWidget(x, 1 if (stretch_first and i == 0) else 0)
    return w


def _spin(value, lo, hi, step, decimals=1, suffix=" mm"):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setValue(value)
    s.setAlignment(Qt.AlignRight)
    return s


def mm(v, decimals=2):
    return f"{v:.{decimals}f}".replace(".", ",")


def default_font_family():
    """Una sans bien legible que exista en el sistema (las fuentes del sistema de macOS,
    tipo .AppleSystemUIFont, no aparecen en el selector)."""
    available = set(QFontDatabase.families())
    for fam in ("Avenir Next", "Helvetica Neue", "Segoe UI", "Arial", "DejaVu Sans"):
        if fam in available:
            return fam
    return QFont().family()


def reveal_in_file_manager(path):
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


def suggested_name(url):
    try:
        host = urlparse(url.strip()).hostname or ""
    except ValueError:
        host = ""
    host = host.removeprefix("www.")
    safe = "".join(ch if ch.isalnum() or ch in "-." else "-" for ch in host).strip("-.")
    return f"qr-{safe}.stl" if safe else "qr.stl"


class MainWindow(QMainWindow):
    modelChanged = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("qr2stl")
        self.setUnifiedTitleAndToolBarOnMac(True)
        self.resize(1180, 760)
        self.setMinimumSize(860, 560)
        self.settings = QSettings()
        self.analysis = None
        self.model = None
        self._text_cache = {}
        self._structure = None
        self._restoring = True

        self.viewer = Viewer()
        inspector = self._inspector()
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.viewer)
        split.addWidget(inspector)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        split.setHandleWidth(1)
        split.setSizes([800, 360])
        self.setCentralWidget(split)
        self.toast = Toast(self, self.viewer)  # hijo de la ventana: el QSplitter lo haría panel

        self._toolbar()
        self._menus()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REBUILD_MS)
        self._timer.timeout.connect(self.rebuild)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_settings)
        self._connect()
        self.restore_settings()
        self._restoring = False
        self.rebuild()

    # ------------------------------------------------------------ toolbar y menús
    def _toolbar(self):
        tb = QToolBar("Herramientas")
        tb.setMovable(False)
        tb.setFloatable(False)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.export_btn = PrimaryButton("Exportar STL…")
        self.export_btn.setToolTip("Guardar el modelo como STL (⌘E)")
        self.export_btn.clicked.connect(self.export_stl)
        tb.addWidget(self.export_btn)
        pad = QWidget()
        pad.setFixedWidth(8)
        tb.addWidget(pad)
        self.addToolBar(tb)

    def _menus(self):
        mb = self.menuBar()
        file = mb.addMenu("Archivo")
        self.export_action = QAction("Exportar STL…", self)
        self.export_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_action.triggered.connect(self.export_stl)
        file.addAction(self.export_action)
        gc = QAction("Insertar pausa en un G-code…", self)
        gc.setShortcut(QKeySequence("Ctrl+G"))
        gc.triggered.connect(self.choose_gcode)
        file.addAction(gc)
        file.addSeparator()
        reset = QAction("Restablecer valores", self)
        reset.triggered.connect(self.reset_defaults)
        file.addAction(reset)

        view = mb.addMenu("Visualización")
        for i, (name, key) in enumerate((("Perspectiva", "Ctrl+1"), ("Arriba", "Ctrl+2"),
                                         ("Frente", "Ctrl+3"))):
            a = QAction(name, self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _=False, i=i: self.viewer.set_view(i))
            view.addAction(a)
        view.addSeparator()
        self.rotate_action = QAction("Rotación automática", self)
        self.rotate_action.setCheckable(True)
        self.rotate_action.setChecked(True)
        self.rotate_action.toggled.connect(self.viewer.set_auto_rotate)
        view.addAction(self.rotate_action)

        help_ = mb.addMenu("Ayuda")
        about = QAction("Acerca de qr2stl", self)
        about.setMenuRole(QAction.AboutRole)
        about.triggered.connect(self.about)
        help_.addAction(about)

    def about(self):
        QMessageBox.about(self, "qr2stl",
                          f"<b>qr2stl {__version__}</b><p>Códigos QR imprimibles en 3D, "
                          "con marco y texto, para Cura y Bambu Studio.</p>")

    # ------------------------------------------------------------ inspector
    def _inspector(self):
        d = core.Params()
        panel = QWidget()
        panel.setObjectName("inspector")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(0)

        self.banner = Banner()
        lay.addWidget(self.banner)
        lay.addSpacing(4)

        # Contenido
        s = Section("Contenido")
        self.url = QLineEdit(d.url)
        self.url.setPlaceholderText("https://…")
        self.url.setClearButtonEnabled(True)
        s.addWidget(self.url)
        self.ecc = SegmentedControl(["L", "M", "Q", "H"], ECC_KEYS.index(d.ecc))
        self.ecc.setToolTip("Corrección de errores: más alta tolera más daño, pero agrega "
                            "módulos y los achica.")
        s.addWidget(_row(QLabel("Corrección de errores"), self.ecc))
        self.ecc_caption = caption("")
        s.addWidget(self.ecc_caption)
        lay.addWidget(s)
        lay.addWidget(Separator())

        # Tamaño
        s = Section("Tamaño")
        self.size = s.addWidget(SliderField("Lado del QR", d.size, 10, 200, 0.5, 1,
                                            tooltip="Incluye el borde blanco alrededor del código."))
        self.border = s.addWidget(SliderField("Borde blanco", d.border, 0, 8, 1, 0, " mód.",
                                              tooltip="El estándar pide 4 módulos; con base de "
                                                      "otro color, 2 alcanzan."))
        self.radius = s.addWidget(SliderField("Esquinas redondeadas", d.corner_radius, 0, 20,
                                              0.5, 1))
        lay.addWidget(s)
        lay.addWidget(Separator())

        # Relieve
        s = Section("Alturas")
        self.base = s.addWidget(SliderField("Espesor de la base", d.base, 0.4, 6, 0.04, 2,
                                            tooltip="Conviene que sea múltiplo de la altura de capa."))
        self.relief = s.addWidget(SliderField("Relieve", d.relief, 0.2, 4, 0.04, 2,
                                              tooltip="Código, marco y texto. Al menos 2 capas."))
        lay.addWidget(s)
        lay.addWidget(Separator())

        # Marco
        self.frame_section = Section("Marco", expanded=d.frame, switch=d.frame)
        self.frame_width = self.frame_section.addWidget(
            SliderField("Ancho", d.frame_width, 0.8, 10, 0.1, 1))
        self.frame_section.addWidget(caption("En relieve, del mismo color que el código, "
                                             "alrededor de toda la placa."))
        lay.addWidget(self.frame_section)
        lay.addWidget(Separator())

        # Texto
        self.text_section = Section("Texto debajo", expanded=False, switch=False)
        self.text = QLineEdit()
        self.text.setPlaceholderText("Escaneame")
        self.text.setClearButtonEnabled(True)
        self.text_section.addWidget(self.text)
        self.font_box = QFontComboBox()
        self.font_box.setCurrentFont(QFont(default_font_family()))
        self.bold = ToggleSwitch(True)
        self.text_section.addWidget(_row(self.font_box))
        self.text_section.addWidget(_row(QLabel("Negrita"), self.bold))
        self.text_size = self.text_section.addWidget(
            SliderField("Alto de las mayúsculas", d.text_size, 3, 25, 0.5, 1))
        lay.addWidget(self.text_section)
        lay.addWidget(Separator())

        # Colores
        s = Section("Colores de la vista previa", expanded=False)
        self.plate_color = ColorWell(COLOR_PRESETS[0][0], "Color de la base")
        self.code_color = ColorWell(COLOR_PRESETS[0][1], "Color del código")
        wells = QHBoxLayout()
        wells.setSpacing(10)
        for lbl, w in (("Base", self.plate_color), ("Código", self.code_color)):
            wells.addWidget(w)
            wells.addWidget(QLabel(lbl))
            wells.addSpacing(10)
        wells.addStretch(1)
        s.addLayout(wells)
        presets = QHBoxLayout()
        presets.setSpacing(4)
        for a, b in COLOR_PRESETS:
            btn = _PresetChip(a, b)
            btn.clicked.connect(lambda _=False, a=a, b=b: self._set_colors(a, b))
            presets.addWidget(btn)
        presets.addStretch(1)
        s.addLayout(presets)
        s.addWidget(caption("Solo para ver cómo queda: el color real lo da el filamento."))
        lay.addWidget(s)
        lay.addWidget(Separator())

        # Impresión
        s = Section("Impresión")
        self.printer = SegmentedControl(PRINTERS, 0)
        s.addWidget(self.printer)
        self.layer = s.addWidget(SliderField("Altura de capa", d.layer, 0.04, 0.6, 0.02, 2))
        self.first_layer = s.addWidget(SliderField(
            "Primera capa", d.first_layer, 0.04, 0.6, 0.02, 2,
            tooltip='"Initial Layer Height": si difiere de la altura de capa, cambia el '
                    'número de capa del cambio de color.'))
        self.pause_info = QLabel()
        self.pause_info.setWordWrap(True)
        self.pause_info.setTextFormat(Qt.RichText)
        s.addWidget(self.pause_info)
        self.printer_stack = FadeStack()
        self.printer_stack.addWidget(self._ender_page())
        self.printer_stack.addWidget(self._bambu_page())
        s.addWidget(self.printer_stack)
        lay.addWidget(s)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(330)
        scroll.setMaximumWidth(460)
        return scroll

    def _ender_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(caption(
            "Exportá el STL, sliceálo en Cura <b>sin raft</b> y soltá el .gcode acá: se genera "
            "<i>nombre</i>_pausa.gcode con la pausa M0 antes de la primera capa del relieve, "
            "detectada por la Z real del G-code."))
        self.drop = DropZone("Soltá el .gcode de Cura", "o hacé clic para elegirlo",
                             (".gcode", ".gco", ".g"), "G-code (*.gcode *.gco *.g)")
        self.drop.fileDropped.connect(self.process_gcode)
        lay.addWidget(self.drop)
        self.gcode_result = QLabel()
        self.gcode_result.setWordWrap(True)
        self.gcode_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.gcode_result.hide()
        lay.addWidget(self.gcode_result)

        opts = Section("Opciones de la pausa", expanded=False)
        opts.content.setContentsMargins(20, 0, 0, 4)
        self.park_x = _spin(0, 0, 500, 5)
        self.park_y = _spin(0, 0, 500, 5)
        self.lift = _spin(10, 0, 100, 1)
        self.retract = _spin(5, 0, 20, 0.5)
        self.purge = _spin(0, 0, 200, 5)
        self.purge.setToolTip("Filamento a extruir en el parking al reanudar. "
                              "0 si purgás a mano durante la pausa.")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.addRow("Parking X", self.park_x)
        form.addRow("Parking Y", self.park_y)
        form.addRow("Subir Z", self.lift)
        form.addRow("Retracción", self.retract)
        form.addRow("Purga al reanudar", self.purge)
        opts.addLayout(form)
        lay.addWidget(opts)
        self.cura_manual = caption("")
        lay.addWidget(self.cura_manual)
        lay.addStretch(1)
        return w

    def _bambu_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)
        self.bambu_steps = caption("")
        lay.addWidget(self.bambu_steps)

        self.multicolor = ToggleSwitch(False)
        self.multicolor.setEnabled(False)
        self.multicolor.setToolTip("Deshabilitado")
        title = QLabel("Proyecto 3MF multicolor")
        title.setEnabled(False)
        lay.addWidget(_row(title, self.multicolor))
        lay.addWidget(caption("Deshabilitado por ahora: Bambu Studio no carga bien el 3MF "
                              "multicolor. El cambio de filamento por capa da el mismo "
                              "resultado con un solo STL."))
        lay.addStretch(1)
        return w

    # ------------------------------------------------------------ señales
    def _sliders(self):
        return (self.size, self.border, self.radius, self.base, self.relief, self.frame_width,
                self.text_size, self.layer, self.first_layer)

    def _connect(self):
        for s in self._sliders():
            s.valueChanged.connect(self.schedule)
        self.url.textChanged.connect(self.schedule)
        self.text.textChanged.connect(self.schedule)
        self.font_box.currentFontChanged.connect(self.schedule)
        self.bold.toggled.connect(self.schedule)
        self.ecc.currentChanged.connect(self.schedule)
        self.frame_section.toggled.connect(self.schedule)
        self.text_section.toggled.connect(self._on_text_toggled)
        self.printer.currentChanged.connect(self._on_printer)
        self.plate_color.colorChanged.connect(self._colors_changed)
        self.code_color.colorChanged.connect(self._colors_changed)
        for s in (self.park_x, self.park_y, self.lift, self.retract, self.purge):
            s.valueChanged.connect(self._save_timer.start)
        self.viewer.set_colors(self.plate_color.color(), self.code_color.color())

    def _on_text_toggled(self, on):
        if on and not self.text.text().strip():
            self.text.setText("Escaneame")
        if on:
            QTimer.singleShot(0, self.text.setFocus)
        self.schedule()

    def _on_printer(self, i):
        self.printer_stack.setCurrentIndexAnimated(i)
        self._update_info()
        self._save_timer.start()

    def _set_colors(self, a, b):
        self.plate_color.setColor(QColor(a))
        self.code_color.setColor(QColor(b))

    def _colors_changed(self, _c=None):
        self.viewer.set_colors(self.plate_color.color(), self.code_color.color())
        self._save_timer.start()

    def schedule(self, *_):
        self._timer.start()
        if not self._restoring:
            self._save_timer.start()

    # ------------------------------------------------------------ lógica
    def params(self):
        return core.Params(
            url=self.url.text(), size=self.size.value(), base=self.base.value(),
            relief=self.relief.value(), border=int(round(self.border.value())),
            ecc=ECC_KEYS[self.ecc.currentIndex()], corner_radius=self.radius.value(),
            frame=self.frame_section.switch.isChecked(), frame_width=self.frame_width.value(),
            text=self.text.text() if self.text_section.switch.isChecked() else "",
            text_size=self.text_size.value(), layer=self.layer.value(),
            first_layer=self.first_layer.value())

    def _text(self, p):
        if not p.text.strip():
            return None
        key = (p.text.strip(), self.font_box.currentFont().family(), self.bold.isChecked())
        if key not in self._text_cache:
            if len(self._text_cache) > 32:
                self._text_cache.clear()
            self._text_cache[key] = text_shape(*key)
        return self._text_cache[key]

    def rebuild(self):
        p = self.params()
        try:
            a = core.analyze(p)
            model = core.build_model(p, a, self._text(p), exact=False)
        except ValueError as ex:
            self.analysis = self.model = None
            self.banner.show_messages([str(ex)], "error")
            self.viewer.set_message(str(ex))
            self.export_btn.setEnabled(False)
            self.export_action.setEnabled(False)
            self._update_info()
            return
        self.analysis, self.model = a, model
        structure = (p.frame, bool(p.text.strip()))
        if self._structure is not None and structure != self._structure:
            self.viewer.pulse()
        self._structure = structure
        lay = model.layout
        dims = f"{mm(lay.width, 1)} × {mm(lay.height, 1)} × {mm(model.top)} mm"
        stats = (f"QR v{a.version} · {a.n}×{a.n} módulos de {mm(a.module)} mm · "
                 f"cambio de color en la capa {a.pause_layer}")
        self.viewer.set_model(model, stats, dims)
        self.banner.show_messages(a.warnings + model.warnings)
        self.export_btn.setEnabled(True)
        self.export_action.setEnabled(True)
        self._update_info()
        self.modelChanged.emit()

    def _update_info(self):
        names = {"L": "tolera ~7% de daño", "M": "tolera ~15% de daño",
                 "Q": "tolera ~25% de daño", "H": "tolera ~30% de daño"}
        self.ecc_caption.setText(names[ECC_KEYS[self.ecc.currentIndex()][0]].capitalize() + ".")
        a = self.analysis
        if a is None:
            self.pause_info.setText("")
            self.cura_manual.setText("")
            self.bambu_steps.setText("")
            return
        layer = self.layer.value()
        next_z = a.pause_z + layer
        self.pause_info.setText(
            f"Cambio de color al terminar la capa <b>{a.pause_layer}</b> "
            f"(Z = {mm(a.pause_z)} mm).")
        self.cura_manual.setText(
            "Alternativa manual en Cura: Extensiones → Post Processing → Modify G-Code → "
            f"Pause at Height → By Layer → Pause Layer = <b>{a.pause_layer}</b> → método M0.")
        self.bambu_steps.setText(
            "<ol style='margin-left:-24px'>"
            "<li>Exportá el STL y abrilo en Bambu Studio.</li>"
            f"<li>Sliceá y, en la vista previa, subí el deslizador de capas hasta la capa "
            f"<b>{a.pause_layer + 1}</b> (Z = {mm(next_z)} mm).</li>"
            "<li>Hacé clic en el <b>+</b> del deslizador (o clic derecho → cambio de "
            "filamento) y elegí el filamento del código. Con AMS el cambio es automático.</li>"
            "</ol>")

    # ------------------------------------------------------------ exportar
    def export_stl(self):
        self.rebuild()
        if self.model is None:
            return
        folder = self.settings.value("export/folder", os.path.expanduser("~/Desktop"))
        start = os.path.join(folder, suggested_name(self.url.text()))
        path, _ = QFileDialog.getSaveFileName(self, "Exportar STL", start, "STL (*.stl)")
        if not path:
            return
        p = self.params()
        try:
            exact = core.build_model(p, core.analyze(p), self._text(p), exact=True)
            path = core.export_stl(exact, path)
        except (OSError, ValueError) as ex:
            QMessageBox.critical(self, "No se pudo guardar", str(ex))
            return
        self.settings.setValue("export/folder", os.path.dirname(path))
        self.toast.show_message(f"✓  Guardado {os.path.basename(path)}", "Mostrar",
                                lambda: reveal_in_file_manager(path))

    def pause_settings(self):
        return gcode.PauseSettings(park_x=self.park_x.value(), park_y=self.park_y.value(),
                                   lift=self.lift.value(), retract=self.retract.value(),
                                   purge=self.purge.value())

    def choose_gcode(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir G-code", "", "G-code (*.gcode *.gco *.g)")
        if path:
            self.printer.setCurrentIndex(0)
            self.process_gcode(path)

    def process_gcode(self, path):
        self.gcode_result.show()
        try:
            # surrogateescape: cualquier byte raro del archivo sale igual que entró
            with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
                text = f.read()
            res = gcode.insert_pause(text, self.base.value(), self.pause_settings())
            root, ext = os.path.splitext(path)
            out = f"{root}_pausa{ext}"
            with open(out, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                f.write(res.text)
        except (OSError, ValueError) as ex:
            self.gcode_result.setStyleSheet("color: #ff453a;")
            self.gcode_result.setText(f"✕ {os.path.basename(path)}: {ex}")
            return
        self.gcode_result.setStyleSheet("color: #30b158;")
        self.gcode_result.setText(
            f"✓ Pausa antes de ;LAYER:{res.layer} (capa {res.layer + 1} del preview, "
            f"Z = {mm(res.layer_z)} mm). La base termina en Z = {mm(res.base_top_z)} mm.")
        self.toast.show_message(f"✓  Guardado {os.path.basename(out)}", "Mostrar",
                                lambda: reveal_in_file_manager(out))

    # ------------------------------------------------------------ preferencias
    _KEYS = ("size", "border", "radius", "base", "relief", "frame_width", "text_size", "layer",
             "first_layer")

    def save_settings(self):
        s = self.settings
        s.setValue("p/url", self.url.text())
        for k in self._KEYS:
            s.setValue(f"p/{k}", getattr(self, k).value())
        s.setValue("p/ecc", self.ecc.currentIndex())
        s.setValue("p/frame", self.frame_section.switch.isChecked())
        s.setValue("p/text_on", self.text_section.switch.isChecked())
        s.setValue("p/text", self.text.text())
        s.setValue("p/font", self.font_box.currentFont().family())
        s.setValue("p/bold", self.bold.isChecked())
        s.setValue("p/printer", self.printer.currentIndex())
        s.setValue("p/plate_color", self.plate_color.color().name())
        s.setValue("p/code_color", self.code_color.color().name())
        for k in ("park_x", "park_y", "lift", "retract", "purge"):
            s.setValue(f"pause/{k}", getattr(self, k).value())

    def restore_settings(self):
        s = self.settings

        def num(key, default):
            try:
                return float(s.value(key, default))
            except (TypeError, ValueError):
                return default

        def flag(key, default):
            v = s.value(key, default)
            return v in (True, "true", "1", 1) if not isinstance(v, bool) else v

        self.url.setText(s.value("p/url", self.url.text()))
        for k in self._KEYS:
            w = getattr(self, k)
            w.setValue(num(f"p/{k}", w.value()), animate=False)
        self.ecc.setCurrentIndex(int(num("p/ecc", self.ecc.currentIndex())), animate=False)
        frame = flag("p/frame", False)
        self.frame_section.switch.setChecked(frame)
        self.frame_section.setExpanded(frame, animate=False)
        self.frame_section.body.setEnabled(frame)
        self.text.setText(s.value("p/text", ""))
        text_on = flag("p/text_on", False)
        self.text_section.switch.setChecked(text_on)
        self.text_section.setExpanded(text_on, animate=False)
        self.text_section.body.setEnabled(text_on)
        family = s.value("p/font", "")
        if family:
            self.font_box.setCurrentFont(QFont(family))
        self.bold.setChecked(flag("p/bold", True))
        printer = int(num("p/printer", 0))
        self.printer.setCurrentIndex(printer, animate=False)
        self.printer_stack.setCurrentIndex(printer)
        self._set_colors(s.value("p/plate_color", COLOR_PRESETS[0][0]),
                         s.value("p/code_color", COLOR_PRESETS[0][1]))
        for k in ("park_x", "park_y", "lift", "retract", "purge"):
            w = getattr(self, k)
            w.setValue(num(f"pause/{k}", w.value()))

    def reset_defaults(self):
        d = core.Params()
        for k, v in (("size", d.size), ("border", d.border), ("radius", d.corner_radius),
                     ("base", d.base), ("relief", d.relief), ("frame_width", d.frame_width),
                     ("text_size", d.text_size), ("layer", d.layer),
                     ("first_layer", d.first_layer)):
            getattr(self, k).setValue(v)  # los sliders viajan animados a su valor
        self.ecc.setCurrentIndex(ECC_KEYS.index(d.ecc))
        self.frame_section.switch.setChecked(False)
        self.text_section.switch.setChecked(False)
        self._set_colors(*COLOR_PRESETS[0])

    # ------------------------------------------------------------ eventos
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.toast.reposition()

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)


class _PresetChip(QPushButton):
    """Botoncito con dos colores (base / código)."""

    def __init__(self, a, b, parent=None):
        super().__init__(parent)
        self.a, self.b = QColor(a), QColor(b)
        self.setFixedSize(30, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Aplicar combinación")

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(self.a)
        p.drawRoundedRect(r, 6, 6)
        p.setBrush(self.b)
        inner = r.adjusted(r.width() * 0.3, r.height() * 0.28, -r.width() * 0.3, -r.height() * 0.28)
        p.drawRoundedRect(inner, 2, 2)
        p.setBrush(Qt.NoBrush)
        border = with_alpha(self.palette().color(QPalette.WindowText), 0.35 if self.underMouse() else 0.18)
        p.setPen(border)
        p.drawRoundedRect(r, 6, 6)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)
