"""Smoke test de la GUI. Se saltea si PySide6 no está instalado (p. ej. en Docker/CI de núcleo)."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qr2stl.gui import MainWindow  # noqa: E402
from test_gcode import fake_cura  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("qr2stl-tests")  # no tocar la config real del usuario
    QSettings().clear()
    return app


def test_window_refresh(app):
    w = MainWindow()
    w.url.setText("https://example.com")
    w.refresh()
    assert w.analysis is not None and w.analysis.pause_layer == 6
    assert "Pause Layer = 6" in w.cura_manual.text()
    w.url.setText("")
    w.refresh()
    assert w.analysis is None and not w.export_single_btn.isEnabled() and not w.export_3mf_btn.isEnabled()


def test_process_gcode(app, tmp_path):
    src = tmp_path / "qr.gcode"
    src.write_text(fake_cura(), newline="")
    w = MainWindow()
    w.process_gcode(str(src))
    out = tmp_path / "qr_pausa.gcode"
    assert out.exists() and "M0 " in out.read_text()
    assert "LAYER:6" in w.gcode_result.text()


def test_template_selection(app, tmp_path):
    import json
    import zipfile
    path = tmp_path / "t.3mf"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps({
            "printer_settings_id": "Bambu Lab H2S 0.4 nozzle",
            "filament_settings_id": ["a", "b"], "filament_type": ["PLA", "PLA"],
            "filament_colour": ["#000000", "#FFFFFF"]}))
        z.writestr("3D/3dmodel.model", '<model><metadata name="Application">BambuStudio-02.08</metadata></model>')
    w = MainWindow()
    w.set_template(str(path))
    assert w.template is not None
    assert (w.base_slot.currentData(), w.code_slot.currentData()) == (2, 1)  # claro/oscuro
    w2 = MainWindow()  # se recuerda entre sesiones
    assert w2.template is not None and w2.template.printer == "Bambu Lab H2S 0.4 nozzle"
    w2.set_template(None)
    assert MainWindow().template is None
