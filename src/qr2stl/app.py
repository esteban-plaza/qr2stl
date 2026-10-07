"""Punto de entrada de la app."""
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication

from . import __version__
from .ui import resources


def _selftest(app):
    """CI: verifica que el ejecutable empaquetado arranca, genera un modelo y que el visor
    3D (QML + Qt Quick 3D) carga."""
    from .ui.window import MainWindow
    app.setOrganizationName("qr2stl-selftest")
    w = MainWindow()
    w.url.setText("https://example.com")
    w.text_section.switch.setChecked(True)
    w.frame_section.switch.setChecked(True)
    w.rebuild()
    if w.model is None or w.model.num_triangles == 0:
        print("selftest: no se generó el modelo", file=sys.stderr)
        return 1
    if w.viewer.quick is not None and not w.viewer.ok:
        print("selftest: el visor 3D no cargó:\n" + "\n".join(w.viewer.errors), file=sys.stderr)
        return 2
    print(f"selftest ok: {w.model.num_triangles} triángulos, visor 3D: {w.viewer.ok}")
    return 0


def main():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform.startswith("win"):
        # Direct3D 11 es lo más compatible en Windows (incluye WARP por software)
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    app = QApplication(sys.argv)
    app.setOrganizationName("qr2stl")
    app.setApplicationName("qr2stl")
    app.setApplicationDisplayName("qr2stl")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(resources.icon_path()))
    if os.environ.get("QR2STL_SCREENSHOT"):
        app.setOrganizationName("qr2stl-dev")  # no tocar las preferencias reales
    if "--selftest" in sys.argv:
        return _selftest(app)
    from .ui.window import MainWindow
    w = MainWindow()
    w.show()
    shot = os.environ.get("QR2STL_SCREENSHOT")
    if shot:  # desarrollo: guarda una captura de la ventana y sale
        def grab():
            w.grab().save(shot)
            app.quit()
        QTimer.singleShot(int(os.environ.get("QR2STL_SCREENSHOT_MS", "3500")), grab)
    return app.exec()
