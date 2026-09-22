"""Interfaz Qt (PySide6) de qr2stl."""
import os
import sys

from PySide6.QtCore import QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import bambu, core, gcode

DEBOUNCE_MS = 150
WARN_STYLE = "color: #b00"


class QrPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.matrix = None
        self.setMinimumSize(240, 240)

    def set_matrix(self, matrix):
        self.matrix = matrix
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        side = min(self.width(), self.height())
        ox, oy = (self.width() - side) / 2, (self.height() - side) / 2
        p.fillRect(QRectF(ox, oy, side, side), Qt.white)
        p.setPen(QColor("#999"))
        p.drawRect(QRectF(ox, oy, side - 1, side - 1))
        if not self.matrix:
            return
        n = len(self.matrix)
        px = side / n
        p.setPen(Qt.NoPen)
        p.setBrush(Qt.black)
        for r, row in enumerate(self.matrix):
            for c, v in enumerate(row):
                if v:
                    # +0.5 px de solape para que no aparezcan líneas finas entre módulos
                    p.drawRect(QRectF(ox + c * px, oy + r * px, px + 0.5, px + 0.5))


class GcodeDropZone(QFrame):
    """Zona para soltar un .gcode (o hacer clic y elegirlo)."""
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        self.setCursor(Qt.PointingHandCursor)
        self.label = QLabel("Arrastrá acá el .gcode de Cura\n(o hacé clic para elegirlo)")
        self.label.setAlignment(Qt.AlignCenter)
        QVBoxLayout(self).addWidget(self.label)
        self._set_hover(False)

    def _set_hover(self, on):
        self.setStyleSheet("GcodeDropZone { border: 2px dashed %s; border-radius: 8px; }"
                           % ("#2a7" if on else "#999"))

    @staticmethod
    def _gcode_path(event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            if path.lower().endswith((".gcode", ".gco", ".g")):
                return path
        return None

    def dragEnterEvent(self, event):
        if self._gcode_path(event):
            self._set_hover(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event):
        self._set_hover(False)

    def dropEvent(self, event):
        self._set_hover(False)
        path = self._gcode_path(event)
        if path:
            event.acceptProposedAction()
            self.fileDropped.emit(path)

    def mousePressEvent(self, _event):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir G-code", "", "G-code (*.gcode *.gco *.g)")
        if path:
            self.fileDropped.emit(path)


def _spin(value, lo, hi, step, decimals=2):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    return s


def _swatch(colour):
    pix = QPixmap(14, 14)
    pix.fill(QColor(colour) if QColor(colour).isValid() else QColor("#888"))
    return QIcon(pix)


def _note(text):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lbl


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QR → STL")
        self.analysis = None

        tabs = QTabWidget()
        tabs.addTab(self._config_tab(), "Configuración")
        tabs.addTab(self._export_tab(), "Exportar")
        QVBoxLayout(self).addWidget(tabs)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh)
        self.url.textChanged.connect(self._timer.start)
        for s in (self.size, self.base, self.relief, self.border, self.layer, self.first_layer):
            s.valueChanged.connect(self._timer.start)
        self.ecc.currentTextChanged.connect(self._timer.start)
        self.refresh()

    # ------------------------------------------------------------ pestañas
    def _config_tab(self):
        d = core.Params()
        self.url = QLineEdit(d.url)
        self.size = _spin(d.size, 5, 300, 5, 1)
        self.base = _spin(d.base, 0.1, 20, 0.2)
        self.relief = _spin(d.relief, 0.1, 20, 0.2)
        self.border = QSpinBox()
        self.border.setRange(0, 10)
        self.border.setValue(d.border)
        self.ecc = QComboBox()
        self.ecc.addItems(list(core.ECC))
        self.ecc.setCurrentText(d.ecc)
        self.layer = _spin(d.layer, 0.04, 1.0, 0.04)
        self.first_layer = _spin(d.first_layer, 0.04, 1.0, 0.04)
        self.first_layer.setToolTip('"Initial Layer Height" de Cura. Si difiere de la '
                                    'altura de capa, cambia el número de capa de la pausa.')

        form = QFormLayout()
        form.addRow("URL:", self.url)
        form.addRow("Lado total (mm)", self.size)
        form.addRow("Espesor base (mm)", self.base)
        form.addRow("Relieve (mm)", self.relief)
        form.addRow("Borde (módulos)", self.border)
        form.addRow("Corrección de error", self.ecc)
        form.addRow("Altura de capa (mm)", self.layer)
        form.addRow("Primera capa (mm)", self.first_layer)

        self.preview = QrPreview()
        top = QHBoxLayout()
        top.addLayout(form, 1)
        top.addWidget(self.preview, 1)

        self.info = _note("")
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(top)
        lay.addWidget(self.info)
        return w

    def _export_tab(self):
        sub = QTabWidget()
        sub.addTab(self._ender_tab(), "Ender (Cura, 1 extrusor)")
        sub.addTab(self._bambu_tab(), "Bambu Lab")
        return sub

    def _ender_tab(self):
        self.export_single_btn = QPushButton("Exportar STL…")
        self.export_single_btn.clicked.connect(self.export_stl)
        self.cura_manual = _note("")

        self.park_x = _spin(0, 0, 500, 5, 1)
        self.park_y = _spin(0, 0, 500, 5, 1)
        self.lift = _spin(10, 0, 100, 1, 1)
        self.retract = _spin(5, 0, 20, 0.5, 1)
        self.purge = _spin(0, 0, 200, 5, 1)
        self.purge.setToolTip("Filamento a extruir en el parking al reanudar. "
                              "0 si purgás a mano durante la pausa.")
        pause_form = QFormLayout()
        pause_form.addRow("Parking X / Y (mm)", self._pair(self.park_x, self.park_y))
        pause_form.addRow("Subir Z (mm)", self.lift)
        pause_form.addRow("Retracción (mm)", self.retract)
        pause_form.addRow("Purga al reanudar (mm)", self.purge)

        self.drop = GcodeDropZone()
        self.drop.fileDropped.connect(self.process_gcode)
        self.gcode_result = _note("")

        step1 = QGroupBox("1 · STL")
        l1 = QVBoxLayout(step1)
        row = QHBoxLayout()
        row.addWidget(_note("Base + módulos en relieve, en una sola malla."), 1)
        row.addWidget(self.export_single_btn)
        l1.addLayout(row)

        step2 = QGroupBox("2 · Pausa para cambio de filamento (M0)")
        l2 = QVBoxLayout(step2)
        l2.addWidget(_note("Sliceá el STL en Cura (sin raft), guardá el .gcode y soltalo acá. "
                           "Se genera un <nombre>_pausa.gcode al lado, con la pausa antes de la "
                           "primera capa del relieve (detectada por la Z real del G-code)."))
        l2.addLayout(pause_form)
        l2.addWidget(self.drop)
        l2.addWidget(self.gcode_result)
        l2.addWidget(self.cura_manual)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(step1)
        lay.addWidget(step2)
        lay.addStretch(1)
        return w

    def _bambu_tab(self):
        self.template = None
        self.template_label = _note("")
        pick = QPushButton("Elegir plantilla…")
        pick.clicked.connect(self.choose_template)
        clear = QPushButton("Quitar")
        clear.clicked.connect(lambda: self.set_template(None))
        self.base_slot = QComboBox()
        self.code_slot = QComboBox()
        self.export_3mf_btn = QPushButton("Exportar proyecto 3MF…")
        self.export_3mf_btn.clicked.connect(self.export_3mf)

        tpl = QGroupBox("Plantilla (impresora y filamentos)")
        lt = QVBoxLayout(tpl)
        lt.addWidget(_note(
            "Cualquier .3mf guardado desde Bambu Studio con la impresora y los filamentos que "
            "quieras usar (por ejemplo, uno bajado de MakerWorld). Se copian su impresora, "
            "filamentos y colores; la geometría no."))
        row = QHBoxLayout()
        row.addWidget(self.template_label, 1)
        row.addWidget(pick)
        row.addWidget(clear)
        lt.addLayout(row)
        slots = QFormLayout()
        slots.addRow("Filamento de la base", self.base_slot)
        slots.addRow("Filamento del código", self.code_slot)
        lt.addLayout(slots)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(tpl)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.export_3mf_btn)
        lay.addLayout(row)
        lay.addStretch(1)

        path = QSettings().value("bambu/template", "")
        if path and os.path.exists(path):
            self.set_template(path, quiet=True)
        else:
            self.set_template(None)
        return w

    def choose_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Plantilla de Bambu Studio", "", "3MF (*.3mf)")
        if path:
            self.set_template(path)

    def set_template(self, path, quiet=False):
        settings = QSettings()
        tpl = None
        if path:
            try:
                tpl = bambu.load_template(path)
            except ValueError as ex:
                if not quiet:
                    QMessageBox.warning(self, "Plantilla", str(ex))
                return
        self.template = tpl
        for combo in (self.base_slot, self.code_slot):
            combo.clear()
            combo.setEnabled(tpl is not None)
        if tpl is None:
            settings.remove("bambu/template")
            self.template_label.setText(
                "Sin plantilla: se exporta un 3MF estándar con la base en blanco y el código en "
                "negro; Bambu Studio te pide mapear esos colores a tus filamentos al abrirlo.")
            return
        settings.setValue("bambu/template", path)
        self.template_label.setText(f"{os.path.basename(path)} · {tpl.printer}")
        for f in tpl.filaments:
            label = f"{f.slot} · {f.type} {f.colour} · {f.name}"
            icon = _swatch(f.colour)
            self.base_slot.addItem(icon, label, f.slot)
            self.code_slot.addItem(icon, label, f.slot)
        by_light = sorted(tpl.filaments, key=lambda f: QColor(f.colour).lightnessF())
        base = int(settings.value("bambu/base_slot", by_light[-1].slot))  # el más claro
        code = int(settings.value("bambu/code_slot", by_light[0].slot))   # el más oscuro
        self.base_slot.setCurrentIndex(max(0, self.base_slot.findData(base)))
        self.code_slot.setCurrentIndex(max(0, self.code_slot.findData(code)))

    @staticmethod
    def _pair(a, b):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(a)
        h.addWidget(b)
        return w

    # ------------------------------------------------------------ lógica
    def params(self):
        return core.Params(
            url=self.url.text(), size=self.size.value(), base=self.base.value(),
            relief=self.relief.value(), border=self.border.value(), layer=self.layer.value(),
            first_layer=self.first_layer.value(), ecc=self.ecc.currentText())

    def refresh(self):
        try:
            a = core.analyze(self.params())
        except ValueError as ex:
            self.analysis = None
            self.preview.set_matrix(None)
            self.info.setStyleSheet(WARN_STYLE)
            self.info.setText(str(ex))
            self.cura_manual.setText("")
            for b in (self.export_single_btn, self.export_3mf_btn):
                b.setEnabled(False)
            return
        self.analysis = a
        self.preview.set_matrix(a.matrix)
        for b in (self.export_single_btn, self.export_3mf_btn):
            b.setEnabled(True)
        lines = [f"Versión {a.version} · {a.n}×{a.n} módulos · módulo = {a.module:.2f} mm",
                 f"Cambio de filamento al terminar la capa {a.pause_layer} (Z = {a.pause_z:.2f} mm)"]
        lines += ["⚠ " + w for w in a.warnings]
        self.info.setStyleSheet(WARN_STYLE if a.warnings else "")
        self.info.setText("\n".join(lines))
        self.cura_manual.setText(
            "Alternativa manual en Cura: Extensiones → Post Processing → Modify G-Code → "
            f"Pause at Height → By Layer → Pause Layer = {a.pause_layer} → método M0 (Marlin). "
            "Vale si la altura de capa y la de primera capa coinciden con las de Configuración.")

    def export_stl(self):
        self.refresh()
        if self.analysis is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar STL", "qr.stl", "STL (*.stl)")
        if not path:
            return
        p = self.params()
        try:
            files = core.generate(self.analysis.matrix, p.size, p.base, p.relief, "single", path)
        except OSError as ex:
            QMessageBox.critical(self, "Error", str(ex))
            return
        QMessageBox.information(self, "Listo", "Generado:\n" + "\n".join(files))

    def export_3mf(self):
        self.refresh()
        if self.analysis is None:
            return
        slots = {}
        if self.template is not None:
            slots = {"base_slot": self.base_slot.currentData(), "code_slot": self.code_slot.currentData()}
            if slots["base_slot"] == slots["code_slot"] and QMessageBox.question(
                    self, "Mismo filamento",
                    "La base y el código usan el mismo filamento: el QR va a salir de un solo "
                    "color. ¿Exportar igual?") != QMessageBox.Yes:
                return
            QSettings().setValue("bambu/base_slot", slots["base_slot"])
            QSettings().setValue("bambu/code_slot", slots["code_slot"])
        path, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", "qr.3mf", "3MF (*.3mf)")
        if not path:
            return
        if not path.lower().endswith(".3mf"):
            path += ".3mf"
        p = self.params()
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            bambu.write_project(path, self.analysis.matrix, p.size, p.base, p.relief, name,
                                self.template, **slots)
        except (OSError, ValueError) as ex:
            QMessageBox.critical(self, "Error", str(ex))
            return
        QMessageBox.information(self, "Listo", f"Generado:\n{path}")

    def pause_settings(self):
        return gcode.PauseSettings(park_x=self.park_x.value(), park_y=self.park_y.value(),
                                   lift=self.lift.value(), retract=self.retract.value(),
                                   purge=self.purge.value())

    def process_gcode(self, path):
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
            self.gcode_result.setStyleSheet(WARN_STYLE)
            self.gcode_result.setText(f"✗ {os.path.basename(path)}: {ex}")
            return
        self.gcode_result.setStyleSheet("color: #2a7")
        self.gcode_result.setText(
            f"✓ Pausa insertada antes de ;LAYER:{res.layer} (capa {res.layer + 1} del preview, "
            f"Z = {res.layer_z:.2f} mm). La base termina en Z = {res.base_top_z:.2f} mm.\n"
            f"Guardado: {out}")


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("qr2stl")
    app.setApplicationName("qr2stl")
    if "--selftest" in sys.argv:  # CI: verifica que el ejecutable empaquetado arranca
        app.setOrganizationName("qr2stl-selftest")
        w = MainWindow()
        w.url.setText("https://example.com")
        w.refresh()
        return 0 if w.analysis is not None else 1
    w = MainWindow()
    w.show()
    return app.exec()
