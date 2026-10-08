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


def test_multiline_text_shape(app):
    one = text_shape("HOLA")
    two = text_shape("HOLA\nMUNDO GRANDE")
    assert two.height == pytest.approx(1 + core.LINE_PITCH)
    assert two.width > one.width                  # manda la línea más ancha
    ys = [y for c in two.contours for y in c[:, 1]]
    assert max(ys) == pytest.approx(core.LINE_PITCH + 1, abs=0.08)
    assert min(ys) == pytest.approx(0, abs=0.05)
    # «HOLA» va centrada respecto de «MUNDO GRANDE»
    top = [x for c in two.contours if c[:, 1].min() > 1 for x in c[:, 0]]
    assert (min(top) + max(top)) / 2 == pytest.approx(two.width / 2, abs=0.05)


def test_multiline_edit_grows(win):
    h1 = win.text.height()
    win.text.setText("una\ndos\ntres")
    win.text._anim.stop()
    win.text.setFixedHeight(win.text._height_for(min(win.text.lineCount(), win.text.max_lines)))
    assert win.text.height() > h1 and win.text.lineCount() == 3
    win.text_section.switch.setChecked(True)
    assert win.params().text == "una\ndos\ntres"


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


def test_square_lock(win):
    win.url.setText("https://example.com")
    win.text_section.switch.setChecked(True)
    win.rebuild()
    assert not win.square_lock.isChecked()
    lay = win.model.layout
    assert lay.height > lay.width                     # rectángulo por la franja del texto
    win.square_lock.setChecked(True)
    win.rebuild()
    lay = win.model.layout
    assert lay.width == pytest.approx(lay.height)
    win.save_settings()
    assert MainWindow().square_lock.isChecked()       # se recuerda
    win.reset_defaults()
    assert not win.square_lock.isChecked()


def test_fixed_plate(win):
    win.url.setText("https://example.com")
    win.text_section.switch.setChecked(True)
    win.frame_section.switch.setChecked(True)
    win.rebuild()
    before = win.model.layout
    win.fixed_check.setChecked(True)                  # arranca con las medidas de ahora
    assert win.plate_w.value() == pytest.approx(round(before.width * 2) / 2)
    assert win.plate_h.value() == pytest.approx(round(before.height * 2) / 2)
    assert win.fixed_box.isRevealed() and not win.size_box.isRevealed()
    win.plate_h.setValue(win.plate_h.value() - 5, animate=False)    # más baja: algo se achica
    win.rebuild()
    lay = win.model.layout
    assert (lay.width, lay.height) == pytest.approx((win.plate_w.value(), win.plate_h.value()))
    qr_first = lay.qr_size
    win.priority.setCurrentIndex(1)                   # prioridad al texto
    win.rebuild()
    assert win.model.layout.qr_size < qr_first
    assert win.model.layout.text_size == pytest.approx(win.text_size.value())
    assert "texto mantiene" in win.priority_caption.text()
    win.square_lock.setChecked(True)                  # cuadrada: el alto sigue al ancho
    assert not win.plate_h.isEnabled()
    assert win.plate_h.value() == pytest.approx(win.plate_w.value())
    win.save_settings()
    w2 = MainWindow()
    assert w2.fixed_check.isChecked() and w2.priority.currentIndex() == 1
    assert w2.fixed_box.isRevealed() and not w2.size_box.isRevealed()
    win.reset_defaults()
    assert not win.fixed_check.isChecked() and win.priority.currentIndex() == 0


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


def test_relief_snaps_to_layer_multiples_by_default(win):
    assert win.relief_snap.isChecked()
    assert win.relief.value() == pytest.approx(0.8)
    win.relief.slider.setValue(win.relief.slider.value() + 1)   # una capa más
    assert win.relief.value() == pytest.approx(1.0)
    win.relief.spin.setValue(0.9)                                # escrito a mano: se ajusta
    assert win.relief.value() == pytest.approx(round(0.9 / 0.2) * 0.2)
    win.layer.setValue(0.12, animate=False)                      # cambia la grilla
    v = win.relief.value()
    assert abs(v / 0.12 - round(v / 0.12)) < 1e-6
    assert win.relief.default() == pytest.approx(0.84)           # múltiplo más cercano a 0,8
    win.relief_snap.setChecked(False)                            # sin el check: pasos finos
    win.relief.spin.setValue(0.9)
    assert win.relief.value() == pytest.approx(0.9)


def test_reset_button_per_slider(win):
    assert not win.size.reset_btn.isShown()
    win.size.setValue(70, animate=False)
    assert win.size.reset_btn.isShown()
    win.size.reset_btn.click()
    assert win.size.value() == pytest.approx(core.Params().size)
    assert not win.size.reset_btn.isShown()


def test_reset_all_and_undo(win):
    win.url.setText("https://queda.com")
    win.size.setValue(90, animate=False)
    win.border.setValue(4, animate=False)
    win.frame_section.switch.setChecked(True)
    win.relief_snap.setChecked(False)
    win.relief.setValue(1.32, animate=False)
    win.park_x.setValue(100)
    win.reset_defaults()
    d = core.Params()
    assert win.size.value() == pytest.approx(d.size) and win.border.value() == d.border
    assert win.relief.value() == pytest.approx(d.relief) and win.relief_snap.isChecked()
    assert not win.frame_section.switch.isChecked() and win.park_x.value() == 0
    assert win.url.text() == "https://queda.com"                 # el contenido no se toca
    assert all(not s.reset_btn.isShown() for s in win._sliders())
    assert win.toast.action.text() == "Deshacer"
    win.toast._callback()                                        # Deshacer
    assert win.size.value() == pytest.approx(90) and win.border.value() == 4
    assert win.frame_section.switch.isChecked() and not win.relief_snap.isChecked()
    assert win.relief.value() == pytest.approx(1.32) and win.park_x.value() == 100


def test_multicolor_export_is_disabled(win):
    assert not win.multicolor.isEnabled() and not win.multicolor.isChecked()


def test_suggested_name():
    assert window.suggested_name("https://www.example.com/x?y") == "qr-example.com.stl"
    assert window.suggested_name("hola mundo") == "qr.stl"
