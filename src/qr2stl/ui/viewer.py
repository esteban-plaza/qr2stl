"""Vista previa 3D con Qt Quick 3D (RHI: Metal en macOS, Direct3D en Windows)."""
import os
from pathlib import Path

import numpy as np
from PySide6.QtCore import Q_ARG, QByteArray, QEvent, QMetaObject, Qt, QUrl
from PySide6.QtGui import QColor, QPalette, QVector3D
from PySide6.QtQml import QmlElement
from PySide6.QtQuick3D import QQuick3DGeometry
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import core
from .widgets import accent, is_dark

QML_IMPORT_NAME = "Qr2Stl"
QML_IMPORT_MAJOR_VERSION = 1
QML_FILE = Path(__file__).with_name("viewer.qml")


@QmlElement
class MeshGeometry(QQuick3DGeometry):
    """Geometría cargada desde Python: triángulos sin indexar (sombreado plano) o líneas."""

    def set_triangles(self, positions: np.ndarray, normals: np.ndarray):
        self._upload(np.hstack([positions, normals]).astype(np.float32), positions,
                     QQuick3DGeometry.PrimitiveType.Triangles, with_normals=True)

    def set_lines(self, positions: np.ndarray):
        self._upload(positions.astype(np.float32), positions,
                     QQuick3DGeometry.PrimitiveType.Lines, with_normals=False)

    def _upload(self, data, positions, primitive, with_normals):
        self.clear()
        if len(positions) == 0:
            self.update()
            return
        sem = QQuick3DGeometry.Attribute.Semantic
        f32 = QQuick3DGeometry.Attribute.ComponentType.F32Type
        self.setStride(data.shape[1] * 4)
        self.setPrimitiveType(primitive)
        self.addAttribute(sem.PositionSemantic, 0, f32)
        if with_normals:
            self.addAttribute(sem.NormalSemantic, 12, f32)
        self.setVertexData(QByteArray(np.ascontiguousarray(data).tobytes()))
        lo, hi = positions.min(axis=0), positions.max(axis=0)
        self.setBounds(QVector3D(*map(float, lo)), QVector3D(*map(float, hi)))
        self.update()


def split_parts(model: core.Model):
    """Separa la malla en placa y relieve (por la altura del centro de cada triángulo) y
    la desindexa con normales por cara. El relieve se devuelve relativo a z = base."""
    v = model.vertices[model.triangles]                       # (T, 3, 3)
    normals = core.face_normals(model.vertices, model.triangles)
    raised = v[:, :, 2].mean(axis=1) > model.base + 1e-4

    def flat(mask, dz=0.0):
        tri = v[mask].copy()
        tri[:, :, 2] -= dz
        n = np.repeat(normals[mask], 3, axis=0)
        return tri.reshape(-1, 3), n

    return flat(~raised), flat(raised, model.base)


def grid_lines(width, height, step=10.0, margin=None):
    margin = max(width, height) * 0.8 if margin is None else margin
    x0, x1 = -margin, width + margin
    y0, y1 = -margin, height + margin
    pts = []
    for x in np.arange(np.floor(x0 / step) * step, x1 + 1e-6, step):
        pts += [(x, y0, 0), (x, y1, 0)]
    for y in np.arange(np.floor(y0 / step) * step, y1 + 1e-6, step):
        pts += [(x0, y, 0), (x1, y, 0)]
    arr = np.array(pts, dtype=np.float32)
    arr[:, 0] -= width / 2
    arr[:, 1] -= height / 2
    return arr


def quick3d_available():
    """Qt Quick 3D necesita una GPU real: con la plataforma offscreen (tests) no se usa."""
    if os.environ.get("QR2STL_NO_3D"):
        return False
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.platformName() not in ("offscreen", "minimal")


class Viewer(QWidget):
    """Envuelve el QQuickWidget; si Qt Quick 3D no está disponible muestra un aviso."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.quick = None
        self.root = None
        self.errors = []
        self._plate = self._code = self._grid = None
        if quick3d_available():
            self.quick = QQuickWidget(self)
            self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
            self.quick.setClearColor(self.palette().color(QPalette.Window))
            self.quick.setSource(QUrl.fromLocalFile(str(QML_FILE)))
            if self.quick.status() == QQuickWidget.Error:
                self.errors = [e.toString() for e in self.quick.errors()]
            else:
                self.root = self.quick.rootObject()
                self._plate = self.root.findChild(MeshGeometry, "plateGeo")
                self._code = self.root.findChild(MeshGeometry, "codeGeo")
                self._grid = self.root.findChild(MeshGeometry, "gridGeo")
            lay.addWidget(self.quick)
        if self.root is None:
            msg = "Vista 3D no disponible"
            if self.errors:
                msg += "\n\n" + "\n".join(self.errors)
            lbl = QLabel(msg)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        self._apply_palette()

    @property
    def ok(self):
        return self.root is not None and self._plate is not None

    def _set(self, name, value):
        if self.root is not None:
            self.root.setProperty(name, value)

    def _apply_palette(self):
        pal = self.palette()
        dark = is_dark(self)
        bg = pal.color(QPalette.Window)
        bg = bg.darker(115) if dark else bg.darker(104)
        self._set("bgColor", bg)
        self._set("fgColor", pal.color(QPalette.WindowText))
        self._set("accentColor", accent(self))
        self._set("dark", dark)
        if self.quick is not None:
            self.quick.setClearColor(bg)

    def changeEvent(self, event):
        if event.type() in (QEvent.PaletteChange, QEvent.ApplicationPaletteChange):
            self._apply_palette()
        super().changeEvent(event)

    def set_colors(self, plate: QColor, code: QColor):
        self._set("plateColor", plate)
        self._set("codeColor", code)

    def set_model(self, model: core.Model | None, stats="", dims=""):
        if not self.ok:
            return
        if model is None:
            self._set("hasModel", False)
            return
        (pp, pn), (cp, cn) = split_parts(model)
        self._plate.set_triangles(pp, pn)
        self._code.set_triangles(cp, cn)
        lay = model.layout
        if (self.root.property("plateW"), self.root.property("plateH")) != (lay.width, lay.height):
            self._grid.set_lines(grid_lines(lay.width, lay.height))
        self._set("baseZ", float(model.base))
        self._set("plateT", float(model.top))
        self._set("plateW", float(lay.width))
        self._set("plateH", float(lay.height))
        self._set("stats", stats)
        self._set("dims", dims)
        self._set("message", "")
        self._set("hasModel", True)

    def set_message(self, text):
        self._set("message", text)
        if text:
            self._set("hasModel", False)

    def _call(self, name, *args):
        if self.root is not None:
            QMetaObject.invokeMethod(self.root, name, *args)

    def set_view(self, i):
        self._call("setView", Q_ARG("QVariant", i))

    def pulse(self):
        self._call("pulse")

    def auto_rotate(self):
        return bool(self.root.property("autoRotate")) if self.root is not None else False

    def set_auto_rotate(self, on):
        self._set("autoRotate", bool(on))

