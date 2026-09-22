import os
import struct
from collections import Counter

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
    for t in tris:
        for i in range(3):
            directed[(t[i], t[(i + 1) % 3])] += 1
    return {e: k for e, k in directed.items() if directed[(e[1], e[0])] != k}


def _volume(tris):
    v = 0.0
    for a, b, c in tris:
        v += (a[0] * (b[1] * c[2] - b[2] * c[1])
              - a[1] * (b[0] * c[2] - b[2] * c[0])
              + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return v / 6.0


def _bounds(tris):
    pts = [p for t in tris for p in t]
    return tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3))


@pytest.fixture
def matrix():
    return _matrix()


def test_matrix_includes_border(matrix):
    n = len(matrix)
    assert n == 21 + 4 * (core.qr_matrix(URL, core.ECC["M (15%)"], 2)[1] - 1) + 2 * 2
    assert not any(matrix[0]) and not any(matrix[-1])


@pytest.mark.parametrize("border", [0, 2, 4])
def test_single_mesh_is_closed(border):
    m = _matrix(border=border)
    n = len(m)
    tris = core.build_mesh(core.single_cells(m, 1.2, 0.8), n, 50 / n)
    assert _edge_balance(tris) == {}


def test_split_meshes_are_closed(matrix):
    n = len(matrix)
    base_cells, code_cells = core.split_cells(matrix, 1.2, 0.8)
    for cells in (base_cells, code_cells):
        assert _edge_balance(core.build_mesh(cells, n, 50 / n)) == {}


def test_single_volume_and_bounds(matrix):
    n = len(matrix)
    size, base, relief = 50.0, 1.2, 0.8
    cell = size / n
    dark = sum(map(sum, matrix))
    tris = core.build_mesh(core.single_cells(matrix, base, relief), n, cell)
    assert _volume(tris) == pytest.approx(size * size * base + dark * cell * cell * relief)
    lo, hi = _bounds(tris)
    assert lo == pytest.approx((0, 0, 0))
    assert hi == pytest.approx((size, size, base + relief))


def test_split_volumes(matrix):
    n = len(matrix)
    size, base, relief = 40.0, 1.0, 0.6
    cell = size / n
    dark = sum(map(sum, matrix))
    base_cells, code_cells = core.split_cells(matrix, base, relief)
    assert _volume(core.build_mesh(base_cells, n, cell)) == pytest.approx(size * size * base)
    code = core.build_mesh(code_cells, n, cell)
    assert _volume(code) == pytest.approx(dark * cell * cell * relief)
    lo, hi = _bounds(code)
    assert lo[2] == pytest.approx(base) and hi[2] == pytest.approx(base + relief)


def test_not_mirrored(matrix):
    """El finder pattern de arriba a la izquierda (fila 0, col 0 sin borde) tiene que quedar
    en X chico / Y grande visto desde arriba."""
    n = len(matrix)
    border = 2
    cells = core.single_cells(matrix, 1.0, 1.0)
    r, c = border, border  # esquina del finder de arriba a la izquierda: siempre oscuro
    assert matrix[r][c]
    tris = core.build_mesh({(r, c): cells[(r, c)]}, n, 1.0)
    lo, hi = _bounds(tris)
    assert (lo[0], hi[1]) == pytest.approx((border, n - border))


def test_write_stl(tmp_path, matrix):
    n = len(matrix)
    tris = core.build_mesh(core.single_cells(matrix, 1.2, 0.8), n, 50 / n)
    path = tmp_path / "qr.stl"
    core.write_stl(path, tris)
    raw = path.read_bytes()
    (count,) = struct.unpack_from("<I", raw, 80)
    assert count == len(tris)
    assert len(raw) == 84 + 50 * count


def test_generate_modes(tmp_path, matrix):
    files = core.generate(matrix, 50, 1.2, 0.8, "single", str(tmp_path / "a.stl"))
    assert [os.path.basename(p) for p in files] == ["a.stl"]
    files = core.generate(matrix, 50, 1.2, 0.8, "split", str(tmp_path / "b.stl"))
    assert [os.path.basename(p) for p in files] == ["b_base.stl", "b_codigo.stl"]


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


def test_analyze_defaults():
    a = core.analyze(core.Params(url=URL))
    assert a.pause_layer == 6 and a.pause_z == pytest.approx(1.2)
    assert a.warnings == []


@pytest.mark.parametrize("kwargs, fragment", [
    ({"size": 20}, "módulo chico"),
    ({"relief": 0.2}, "1 sola capa"),
    ({"relief": 0.5}, "no es múltiplo"),
    ({"base": 1.1}, "borde de capa"),
    ({"first_layer": 0.3}, "borde de capa"),
    ({"border": 0}, None),
])
def test_analyze_warnings(kwargs, fragment):
    a = core.analyze(core.Params(url=URL, **kwargs))
    if fragment is None:
        assert a.warnings == []
    else:
        assert any(fragment in w for w in a.warnings)


@pytest.mark.parametrize("kwargs", [{"url": "  "}, {"size": 0}, {"url": "x" * 5000}])
def test_analyze_invalid(kwargs):
    with pytest.raises(ValueError):
        core.analyze(core.Params(**{"url": URL, **kwargs}))

