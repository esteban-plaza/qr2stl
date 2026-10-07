import struct
from collections import Counter

import numpy as np
import pytest

from qr2stl import core

URL = "https://example.com/qr2stl"


def _matrix(url=URL, ecc="M (15%)", border=2):
    m, _ = core.qr_matrix(url, core.ECC[ecc], border)
    return m


def _edge_balance(tris):
    """Cada arista dirigida (a→b) tiene que aparecer tantas veces como su inversa (b→a).
    Eso implica que no hay aristas con una sola cara y que el winding es consistente."""
    directed = Counter()
    for t in tris.tolist():
        for i in range(3):
            directed[(t[i], t[(i + 1) % 3])] += 1
    return {e: k for e, k in directed.items() if directed[(e[1], e[0])] != k}


def _volume(model):
    v = model.vertices.astype(np.float64)[model.triangles]
    return float(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6.0)


def _square(w=1.0, h=1.0, x=0.0, y=0.0):
    return np.array([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], dtype=float)


def _model(**kw):
    text = kw.pop("text_shape", None)
    p = core.Params(**{"url": URL, **kw})
    a = core.analyze(p)
    return p, a, core.build_model(p, a, text)


# ---------------------------------------------------------------- QR
def test_matrix_includes_border():
    m, version = core.qr_matrix(URL, core.ECC["M (15%)"], 2)
    assert len(m) == 21 + 4 * (version - 1) + 2 * 2
    assert not any(m[0]) and not any(row[0] for row in m)


# ---------------------------------------------------------------- malla
@pytest.mark.parametrize("kw", [
    {}, {"border": 0}, {"frame": True}, {"corner_radius": 5},
    {"frame": True, "corner_radius": 6, "frame_width": 3},
    {"text": "AB", "text_shape": core.TextShape([_square(0.6), _square(0.6, x=0.8)], 1.4)},
])
def test_mesh_is_closed(kw):
    _, _, m = _model(**kw)
    assert m.num_triangles > 0
    assert _edge_balance(m.triangles) == {}
    assert _volume(m) > 0  # normales hacia afuera


def test_preview_model_matches_exact_volume():
    kw = dict(url=URL, frame=True, corner_radius=4)
    p = core.Params(**kw)
    a = core.analyze(p)
    fast, exact = core.build_model(p, a, exact=False), core.build_model(p, a)
    assert _volume(fast) == pytest.approx(_volume(exact), rel=1e-6)
    assert _edge_balance(fast.triangles) == {}  # dos cuerpos cerrados


def test_volume_and_bounds():
    p, a, m = _model()
    dark = sum(map(sum, a.matrix))
    expected = p.size * p.size * p.base + dark * a.module ** 2 * p.relief
    assert _volume(m) == pytest.approx(expected, rel=1e-4)
    lo, hi = m.vertices.min(0), m.vertices.max(0)
    assert lo == pytest.approx([0, 0, 0], abs=1e-4)
    assert hi == pytest.approx([p.size, p.size, p.base + p.relief], abs=1e-4)


def _covered(model, z, points):
    """Para cada punto XY, si hay una cara horizontal a la altura z que lo cubre."""
    v = model.vertices[model.triangles].astype(np.float64)
    flat = np.all(np.abs(v[:, :, 2] - z) < 1e-4, axis=1)
    a, b, c = (v[flat, i, :2] for i in range(3))
    out = []
    for pt in points:
        d = lambda p1, p2: (pt[0] - p2[:, 0]) * (p1[:, 1] - p2[:, 1]) - (p1[:, 0] - p2[:, 0]) * (pt[1] - p2[:, 1])
        d1, d2, d3 = d(a, b), d(b, c), d(c, a)
        neg = (d1 < 0) | (d2 < 0) | (d3 < 0)
        pos = (d1 > 0) | (d2 > 0) | (d3 > 0)
        out.append(bool(np.any(~(neg & pos))))
    return out


def test_not_mirrored():
    """Celda por celda, la cara superior del relieve coincide con la matriz: fila 0 arriba
    (Y máxima) y columna 0 a la izquierda."""
    p, a, m = _model(border=1)
    n, mod = a.n, a.module
    pts = [((c + 0.5) * mod, (n - 1 - r + 0.5) * mod) for r in range(n) for c in range(n)]
    expected = [bool(a.matrix[r][c]) for r in range(n) for c in range(n)]
    assert _covered(m, p.base + p.relief, pts) == expected


def test_frame_layout_and_volume():
    p, a, m = _model(frame=True, frame_width=3)
    lay = m.layout
    assert (lay.width, lay.height) == pytest.approx((p.size + 6, p.size + 6))
    assert lay.qr_origin == pytest.approx((3, 3))
    dark = sum(map(sum, a.matrix))
    plate = lay.width * lay.height
    frame = plate - p.size * p.size
    expected = plate * p.base + (dark * a.module ** 2 + frame) * p.relief
    assert _volume(m) == pytest.approx(expected, rel=1e-4)


def test_text_band_and_fit():
    shape = core.TextShape([_square(2.0, 1.0)], 2.0)   # «texto» de 2 × 1 (mayúsculas = 1)
    p, a, m = _model(text="X", text_size=5, text_shape=shape)
    lay = m.layout
    assert lay.band == pytest.approx(5 * core.TEXT_BAND)
    assert lay.height == pytest.approx(p.size + lay.band)
    assert lay.qr_origin[1] == pytest.approx(lay.band)
    dark = sum(map(sum, a.matrix))
    expected = lay.width * lay.height * p.base + (dark * a.module ** 2 + 10 * 5) * p.relief
    assert _volume(m) == pytest.approx(expected, rel=1e-4)
    assert m.warnings == []

    wide = core.TextShape([_square(40.0, 1.0)], 40.0)  # no entra: se achica
    _, _, m = _model(text="X", text_size=5, text_shape=wide)
    assert any("achicó" in w for w in m.warnings)
    assert m.vertices[:, 0].min() >= 0 and m.vertices[:, 0].max() <= m.layout.width + 1e-4


def test_text_hole_is_kept():
    outer = _square(1.0, 1.0)
    hole = (_square(0.5, 0.5, 0.25, 0.25))[::-1]    # sentido opuesto = agujero
    _, _, solid = _model(text="O", text_size=8, text_shape=core.TextShape([outer], 1.0))
    _, _, ring = _model(text="O", text_size=8, text_shape=core.TextShape([outer, hole], 1.0))
    assert _volume(solid) - _volume(ring) == pytest.approx((8 * 0.5) ** 2 * 0.8, rel=1e-4)


def test_empty_text_shape_is_ignored():
    _, _, a = _model(text="X", text_shape=core.TextShape([], 0.0))
    assert a.num_triangles > 0 and _edge_balance(a.triangles) == {}


def test_write_stl(tmp_path):
    _, _, m = _model()
    path = core.export_stl(m, str(tmp_path / "qr"))
    assert path.endswith("qr.stl")
    data = open(path, "rb").read()
    (count,) = struct.unpack_from("<I", data, 80)
    assert count == m.num_triangles and len(data) == 84 + 50 * count
    n = np.frombuffer(data[84:84 + 12], dtype="<f4")
    assert np.linalg.norm(n) == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------- pausa
@pytest.mark.parametrize("base, layer, first, expected_n, expected_z", [
    (1.2, 0.2, None, 6, 1.2),    # caso por defecto: 6 capas de base, pausa layer = 6
    (1.2, 0.2, 0.2, 6, 1.2),
    (1.0, 0.2, 0.2, 5, 1.0),
    (1.2, 0.12, 0.12, 10, 1.2),
    (1.2, 0.2, 0.32, 5, 1.12),   # capa 5 va de 1.12 a 1.32, medio 1.22 > 1.2 → ya es relieve
    (1.2, 0.2, 0.28, 6, 1.28),   # capa 6 va de 1.08 a 1.28, medio 1.18 < 1.2 → es base
    (1.2, 0.2, 0.4, 5, 1.2),
    (0.2, 0.2, 0.3, 1, 0.3),     # base más fina que la primera capa
])
def test_pause_layer(base, layer, first, expected_n, expected_z):
    n, z = core.pause_layer(base, layer, first)
    assert n == expected_n
    assert z == pytest.approx(expected_z)


# ---------------------------------------------------------------- análisis
def test_analyze_defaults():
    a = core.analyze(core.Params(url=URL))
    assert a.pause_layer == 6 and a.pause_z == pytest.approx(1.2)
    assert a.warnings == []


@pytest.mark.parametrize("kwargs, fragment", [
    ({"size": 20}, "módulo chico"),
    ({"relief": 0.2}, "una sola capa"),
    ({"relief": 0.5}, "no es múltiplo"),
    ({"base": 1.1}, "borde de capa"),
    ({"first_layer": 0.3}, "borde de capa"),
    ({"frame": True, "border": 0}, "marco"),
    ({"text": "hola", "text_size": 3}, "texto"),
    ({"corner_radius": 40}, "radio"),
    ({"border": 0}, None),
    ({"frame": True, "text": "hola"}, None),
])
def test_analyze_warnings(kwargs, fragment):
    a = core.analyze(core.Params(url=URL, **kwargs))
    if fragment is None:
        assert a.warnings == []
    else:
        assert any(fragment in w.lower() for w in a.warnings), a.warnings


@pytest.mark.parametrize("kwargs", [
    {"url": "  "}, {"size": 0}, {"url": "x" * 5000},
    {"frame": True, "frame_width": 0}, {"text": "hola", "text_size": 0},
])
def test_analyze_invalid(kwargs):
    with pytest.raises(ValueError):
        core.analyze(core.Params(**{"url": URL, **kwargs}))
