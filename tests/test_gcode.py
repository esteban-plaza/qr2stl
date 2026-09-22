import pytest

from qr2stl import gcode


def fake_cura(first=0.2, layer=0.2, total=2.0, flavor="Marlin", zhop=False, relative_e=False):
    """G-code mínimo con la forma del de Cura: ;LAYER:n, primer G0 con Z, G1 con E."""
    out = [f";FLAVOR:{flavor}", ";Generated with Cura_SteamEngine 5.8.1",
           "M140 S60", "M83" if relative_e else "M82", "G92 E0", "G28"]
    z, e, n = first, 0.0, 0
    while z <= total + 1e-9:
        out.append(f";LAYER:{n}")
        if zhop:
            out.append(f"G1 Z{z + 0.4:.2f}")
        out.append(f"G0 F6000 X10 Y10 Z{z:.2f}")
        for x in (20, 30):
            e += 1.0
            out.append(f"G1 F1200 X{x} Y10 E{1.0 if relative_e else e:.5f}")
        out.append(f";TIME_ELAPSED:{n}")
        n += 1
        z += layer
    out.append(";End of Gcode")
    return "\n".join(out)


def _pause_index(text):
    lines = text.split("\n")
    return lines, next(i for i, l in enumerate(lines) if l.startswith(gcode.MARKER))


@pytest.mark.parametrize("first, layer, base, expected_layer", [
    (0.2, 0.2, 1.2, 6),    # base = 6 capas → pausa antes de LAYER:6
    (0.3, 0.2, 1.2, 5),    # 0.3,0.5,…,1.1 | 1.3 (medio 1.2 ≥ base) → relieve desde LAYER:5
    (0.28, 0.2, 1.2, 6),   # capa 5 top 1.28, medio 1.18 < 1.2 → base
    (0.12, 0.12, 1.2, 10),
])
def test_pause_layer_from_z(first, layer, base, expected_layer):
    res = gcode.insert_pause(fake_cura(first, layer), base)
    assert res.layer == expected_layer
    lines, i = _pause_index(res.text)
    after = lines[i:]
    end = next(j for j, l in enumerate(after) if l == ";qr2stl: fin de la pausa")
    assert after[end + 1] == f";LAYER:{expected_layer}"


def test_matches_core_formula():
    from qr2stl import core
    for first in (0.12, 0.2, 0.24, 0.28, 0.3):
        n, z = core.pause_layer(1.2, 0.2, first)
        res = gcode.insert_pause(fake_cura(first, 0.2), 1.2)
        assert res.layer == n
        assert res.base_top_z == pytest.approx(z)


def test_block_restores_state_absolute_e():
    res = gcode.insert_pause(fake_cura(), 1.2)
    lines, i = _pause_index(res.text)
    block = lines[i:lines.index(";qr2stl: fin de la pausa")]
    assert "M0 Cambiar filamento" in block
    assert "G0 X30 Y10 F6000" in block                # vuelve a la última posición
    assert "G0 Z1.2 F600" in block                    # a la Z de la última capa de base
    assert block[-3:-1] == ["M82 ; extrusion absoluta", "G92 E12"]  # 6 capas × 2 mm
    assert block[-1] == "G1 F1200"


def test_block_relative_e_does_not_reset():
    res = gcode.insert_pause(fake_cura(relative_e=True), 1.2)
    assert "G92 E" not in res.text.split(gcode.MARKER)[1]


def test_purge_and_settings():
    s = gcode.PauseSettings(park_x=5, park_y=200, lift=15, retract=6, purge=30)
    res = gcode.insert_pause(fake_cura(), 1.2, s)
    assert "G0 X5 Y200 F6000" in res.text
    assert "G0 Z16.2 F600" in res.text
    assert "G1 E30 F150 ; purga" in res.text
    assert res.text.count("G1 E-6 F2400") == 2


def test_zhop_does_not_confuse_layer_z():
    res = gcode.insert_pause(fake_cura(zhop=True), 1.2)
    assert res.layer == 6 and res.layer_z == pytest.approx(1.4)


def test_crlf_preserved():
    res = gcode.insert_pause(fake_cura().replace("\n", "\r\n"), 1.2)
    assert "\r\n" in res.text and "\n" not in res.text.replace("\r\n", "")


@pytest.mark.parametrize("text, msg", [
    ("G1 X0\n", "Cura"),
    (fake_cura(flavor="Griffin"), "Marlin"),
    (fake_cura().replace(";LAYER:0", ";LAYER:-1\n;LAYER:0"), "raft"),
    (fake_cura(total=1.0), "Ninguna capa"),
])
def test_rejects(text, msg):
    with pytest.raises(ValueError, match=msg):
        gcode.insert_pause(text, 1.2)


def test_rejects_twice():
    once = gcode.insert_pause(fake_cura(), 1.2).text
    with pytest.raises(ValueError, match="ya tiene"):
        gcode.insert_pause(once, 1.2)
