"""Tests de la GUI con la plataforma offscreen (sin visor 3D). Se saltean sin PySide6."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qr2stl import core  # noqa: E402
from qr2stl.textshape import text_shape  # noqa: E402
from qr2stl.ui import window  # noqa: E402
from qr2stl.ui.window import MainWindow  # noqa: E402
from test_core import _edge_balance  # noqa: E402
from test_gcode import fake_cura  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("qr2stl-tests")  # no tocar la config real del usuario
    app.setApplicationName("qr2stl")
    QSettings().clear()
    return app


@pytest.fixture
def win(app):
    QSettings().clear()
    w = MainWindow()
    yield w
    w.close()


def test_text_shape_is_normalised(app):
    shape = text_shape("HOLA")
    assert shape.contours and shape.width > 2
    ys = [y for c in shape.contours for y in c[:, 1]]
    assert min(ys) == pytest.approx(0, abs=0.05) and max(ys) == pytest.approx(1, abs=0.08)
    assert text_shape("   ").contours == []


def test_text_with_holes_builds_closed_mesh(app):
    p = core.Params(url="https://example.com", text="ABO8", frame=True, corner_radius=3)
    a = core.analyze(p)
    m = core.build_model(p, a, text_shape(p.text))
    assert _edge_balance(m.triangles) == {}


def test_rebuild_and_errors(win):
    win.url.setText("https://example.com")
    win.rebuild()
    assert win.model is not None and win.export_btn.isEnabled()
    assert win.analysis.pause_layer == 6
    assert "Pause Layer = <b>6</b>" in win.cura_manual.text()
    assert "capa <b>7</b>" in win.bambu_steps.text()
    win.url.setText("")
    win.rebuild()
    assert win.model is None and not win.export_btn.isEnabled()
    assert not win.export_action.isEnabled()


def test_frame_and_text_change_geometry(win):
    win.url.setText("https://example.com")
    win.rebuild()
    plain = win.model.layout
    win.frame_section.switch.setChecked(True)
    win.text_section.switch.setChecked(True)   # sin texto escrito pone uno de ejemplo
    win.rebuild()
    assert win.text.text() == "Escaneame"
    lay = win.model.layout
    assert lay.pad == pytest.approx(win.frame_width.value())
    assert lay.height > plain.height and lay.width > plain.width
    assert win.params().text == "Escaneame"
    win.text_section.switch.setChecked(False)
    assert win.params().text == ""


def test_slider_and_spin_stay_in_sync(win):
    win.size.slider.setValue(win.size.slider.value() + 20)   # 20 pasos de 0,5 mm
    assert win.size.value() == pytest.approx(60.0)
    win.size.spin.setValue(80)
    win.size._anim.stop()
    assert win.params().size == pytest.approx(80)


def test_export_stl(win, tmp_path, monkeypatch):
    win.url.setText("https://example.com")
    target = str(tmp_path / "salida.stl")
    monkeypatch.setattr(window.QFileDialog, "getSaveFileName", lambda *a, **k: (target, ""))
    win.export_stl()
    data = open(target, "rb").read()
    count = int.from_bytes(data[80:84], "little")
    assert len(data) == 84 + 50 * count and count > 0


def test_process_gcode(win, tmp_path):
    src = tmp_path / "qr.gcode"
    src.write_text(fake_cura(), newline="")
    win.process_gcode(str(src))
    out = tmp_path / "qr_pausa.gcode"
    assert out.exists() and "M0 " in out.read_text()
    assert "LAYER:6" in win.gcode_result.text()


def test_settings_are_remembered(app):
    QSettings().clear()
    w = MainWindow()
    w.url.setText("https://recordame.com")
    w.frame_section.switch.setChecked(True)
    w.radius.setValue(3.5, animate=False)
    w.printer.setCurrentIndex(1)
    w.save_settings()
    w2 = MainWindow()
    assert w2.url.text() == "https://recordame.com"
    assert w2.frame_section.switch.isChecked()
    assert w2.radius.value() == pytest.approx(3.5)
    assert w2.printer.currentIndex() == 1 and w2.printer_stack.currentIndex() == 1


def test_multicolor_export_is_disabled(win):
    assert not win.multicolor.isEnabled() and not win.multicolor.isChecked()


def test_suggested_name():
    assert window.suggested_name("https://www.example.com/x?y") == "qr-example.com.stl"
    assert window.suggested_name("hola mundo") == "qr.stl"
