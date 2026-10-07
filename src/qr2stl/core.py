"""Núcleo de qr2stl: matriz QR, geometría (placa, código, marco, texto), STL y pausa.

No depende de Qt. El texto llega como polígonos ya vectorizados (ver `textshape.py`),
así el núcleo se puede testear sin una interfaz.

La geometría se arma en 2D y se extruye con manifold3d, que devuelve siempre una malla
cerrada y manifold (sin caras internas ni aristas compartidas por 4 caras):

    placa:   contorno (rectángulo con esquinas redondeadas) extruido de 0 a `base`
    relieve: código ∪ marco ∪ texto, extruido de `base` a `base + relief`

Todo lo que está por encima de `base` es del segundo color, así una sola pausa en la
capa correcta pinta el código, el marco y el texto.
"""
import math
import struct
from functools import lru_cache
from dataclasses import dataclass, field

import numpy as np
import qrcode
from manifold3d import CrossSection, FillRule, JoinType, Manifold
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q

ECC = {"L (7%)": ERROR_CORRECT_L, "M (15%)": ERROR_CORRECT_M,
       "Q (25%)": ERROR_CORRECT_Q, "H (30%)": ERROR_CORRECT_H}

MIN_MODULE_MM = 1.5
MIN_TEXT_MM = 4.0
TEXT_BAND = 1.6      # alto de la franja del texto, en múltiplos del alto de las mayúsculas
_EPS = 1e-6


# ---------------------------------------------------------------- QR
@lru_cache(maxsize=16)
def _qr_cached(data, ecc, border):
    qr = qrcode.QRCode(version=None, error_correction=ecc, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    return tuple(tuple(row) for row in qr.get_matrix()), qr.version


def qr_matrix(data, ecc, border):
    """Matriz del QR (con el borde incluido) y versión. Cacheada: mover un slider que no
    cambia el contenido no vuelve a calcular el QR."""
    matrix, version = _qr_cached(data, ecc, border)
    return [list(row) for row in matrix], version


# ---------------------------------------------------------------- Parámetros
@dataclass
class Params:
    url: str = "https://"
    size: float = 50.0          # lado del QR, borde incluido
    base: float = 1.2
    relief: float = 0.8
    border: int = 2
    ecc: str = "M (15%)"
    corner_radius: float = 0.0
    frame: bool = False
    frame_width: float = 2.0
    text: str = ""              # vacío = sin texto
    text_size: float = 6.0      # alto de las mayúsculas
    layer: float = 0.2
    first_layer: float = 0.2


@dataclass
class TextShape:
    """Texto vectorizado: contornos cerrados con el alto de mayúsculas = 1 y la línea
    base en y = 0. Exteriores y agujeros con sentido de giro opuesto (regla NonZero)."""
    contours: list
    width: float


@dataclass
class Layout:
    width: float        # placa, X
    height: float       # placa, Y
    pad: float          # ancho del marco (0 sin marco)
    band: float         # alto de la franja del texto (0 sin texto)
    qr_origin: tuple    # esquina inferior izquierda del QR
    module: float


@dataclass
class Analysis:
    matrix: list
    version: int
    n: int
    module: float
    pause_layer: int
    pause_z: float
    layout: Layout
    warnings: list = field(default_factory=list)


@dataclass
class Model:
    vertices: np.ndarray    # (V, 3) float32, mm
    triangles: np.ndarray   # (T, 3) uint32
    base: float
    top: float
    layout: Layout
    warnings: list = field(default_factory=list)

    @property
    def num_triangles(self):
        return len(self.triangles)


# ---------------------------------------------------------------- Pausa
def pause_layer(base, layer, first_layer=None):
    """Cantidad de capas que forman la base y Z real donde termina la última.

    Cura slicea cada capa por su punto medio ("Slicing Tolerance: Middle", default):
    una capa es de base si su punto medio queda por debajo de `base`.
    La capa 0 mide `first_layer`; la capa i >= 1 va de first + (i-1)*layer a first + i*layer.

    El número devuelto es el que va en Cura → Pause at Height → "Pause Layer"
    (modo By Layer): en Cura 5.x la pausa se inserta antes de `;LAYER:<n>` (0-based)
    y en Cura 6 al final de la capa <n> del preview (1-based); en ambos casos se
    completan exactamente n capas antes de pausar. Sin raft.
    """
    first = layer if first_layer is None else first_layer
    if first >= base:
        return 1, first
    n = math.ceil((base - first) / layer + 0.5 - _EPS)
    return n, first + (n - 1) * layer


def _is_multiple(value, step):
    k = value / step
    return abs(k - round(k)) < _EPS


# ---------------------------------------------------------------- Análisis
def layout_for(p: Params, n: int) -> Layout:
    module = p.size / n
    pad = p.frame_width if p.frame else 0.0
    band = p.text_size * TEXT_BAND if p.text.strip() else 0.0
    width = p.size + 2 * pad
    height = p.size + band + 2 * pad
    return Layout(width, height, pad, band, (pad, pad + band), module)


def analyze(p: Params) -> Analysis:
    """Calcula la matriz, el layout y los avisos. Lanza ValueError si los parámetros no sirven."""
    data = p.url.strip()
    if not data:
        raise ValueError("Escribí una URL o un texto para el QR.")
    if p.size <= 0 or p.base <= 0 or p.relief <= 0 or p.layer <= 0 or p.first_layer <= 0:
        raise ValueError("Las medidas tienen que ser mayores que cero.")
    if p.frame and p.frame_width <= 0:
        raise ValueError("El ancho del marco tiene que ser mayor que cero.")
    if p.text.strip() and p.text_size <= 0:
        raise ValueError("El alto del texto tiene que ser mayor que cero.")
    try:
        matrix, version = qr_matrix(data, ECC[p.ecc], p.border)
    except qrcode.exceptions.DataOverflowError:
        raise ValueError("El contenido no entra en un QR (es demasiado largo).") from None
    n = len(matrix)
    lay = layout_for(p, n)
    k, z = pause_layer(p.base, p.layer, p.first_layer)

    warns = []
    if lay.module < MIN_MODULE_MM:
        warns.append(f"Módulo chico ({lay.module:.2f} mm): agrandá el lado o acortá la URL.")
    if p.frame and p.border < 1:
        warns.append("Con marco y borde 0 el marco se pega al código y el QR no se lee.")
    if p.text.strip() and p.text_size < MIN_TEXT_MM:
        warns.append(f"Texto de menos de {MIN_TEXT_MM:g} mm: los trazos pueden no salir.")
    if p.corner_radius > min(lay.width, lay.height) / 2:
        warns.append("El radio de las esquinas es más grande que media placa.")
    if p.first_layer >= p.base:
        warns.append("La base no supera la primera capa.")
    elif not _is_multiple(p.base - p.first_layer, p.layer):
        warns.append(f"La base no cae en un borde de capa: el cambio queda en Z = {z:.2f} mm.")
    if not _is_multiple(p.relief, p.layer):
        warns.append("El relieve no es múltiplo de la altura de capa.")
    elif round(p.relief / p.layer) < 2:
        warns.append("Relieve de una sola capa: poco contraste.")
    return Analysis(matrix, version, n, lay.module, k, z, lay, warns)


# ---------------------------------------------------------------- Geometría 2D
def _rect(x0, y0, x1, y1):
    return np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], dtype=float)


def plate_outline(width, height, radius) -> CrossSection:
    r = max(0.0, min(radius, width / 2 - _EPS, height / 2 - _EPS))
    if r <= 1e-3:
        return CrossSection([_rect(0, 0, width, height)])
    inner = CrossSection([_rect(r, r, width - r, height - r)])
    return inner.offset(r, JoinType.Round, circular_segments=max(32, int(r * 24)))


def code_section(matrix, origin, module) -> CrossSection:
    runs = _code_runs(matrix, origin, module)   # tramos: menos contornos para unir
    quads = [_rect(*r) for r in runs]
    return CrossSection(quads, FillRule.Positive) if quads else CrossSection()


def frame_section(outline: CrossSection, width) -> CrossSection:
    return outline - outline.offset(-width, JoinType.Miter, miter_limit=2.0)


def text_section(shape: TextShape, lay: Layout, size, warnings) -> CrossSection:
    if not shape.contours or shape.width <= 0:
        return CrossSection()
    avail = lay.width - 2 * lay.pad - 2 * max(lay.module, 1.0)
    scale = size
    if shape.width * scale > avail:
        scale = avail / shape.width
        warnings.append(f"El texto no entraba: se achicó a {scale:.1f} mm de alto.")
    cx = lay.width / 2 - shape.width * scale / 2
    cy = lay.pad + lay.band / 2 - scale / 2
    contours = [np.asarray(c, dtype=float) * scale + (cx, cy) for c in shape.contours]
    return CrossSection(contours, FillRule.NonZero)


# ---------------------------------------------------------------- Modelo 3D
def _code_runs(matrix, origin, module):
    """Tramos horizontales de módulos oscuros: [(x0, y0, x1, y1)] en mm."""
    n = len(matrix)
    ox, oy = origin
    runs = []
    for r, row in enumerate(matrix):
        y0 = oy + (n - 1 - r) * module   # fila 0 arriba => no espejado
        c = 0
        while c < n:
            if not row[c]:
                c += 1
                continue
            start = c
            while c < n and row[c]:
                c += 1
            runs.append((ox + start * module, y0, ox + c * module, y0 + module))
    return np.array(runs, dtype=np.float64).reshape(-1, 4)


# caja unitaria: 8 vértices y 12 triángulos con las normales hacia afuera
_BOX_V = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                   (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)], dtype=np.float64)
_BOX_T = np.array([(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
                   (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)],
                  dtype=np.uint32)


def _boxes(runs, z0, z1):
    """Una caja cerrada por tramo, sin triangulación ni booleanas (vista previa)."""
    k = len(runs)
    lo = np.column_stack([runs[:, 0], runs[:, 1], np.full(k, z0)])
    size = np.column_stack([runs[:, 2] - runs[:, 0], runs[:, 3] - runs[:, 1], np.full(k, z1 - z0)])
    verts = (lo[:, None, :] + size[:, None, :] * _BOX_V[None]).reshape(-1, 3)
    tris = (_BOX_T[None] + (np.arange(k, dtype=np.uint32) * 8)[:, None, None]).reshape(-1, 3)
    return verts, tris


def _mesh_arrays(solid):
    mesh = solid.to_mesh()
    return (np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3],
            np.asarray(mesh.tri_verts, dtype=np.uint32))


def build_model(p: Params, a: Analysis, text: TextShape | None = None,
                exact: bool = True) -> Model:
    """exact=True: una sola malla cerrada (unión booleana), para exportar.
    exact=False: varios cuerpos cerrados que se tocan pero no se solapan (placa, marco y
    texto, y una caja por tramo del código), sin triangular el código ni hacer booleanas
    3D. Es mucho más rápido y alcanza para la vista previa."""
    lay = a.layout
    warns = []
    outline = plate_outline(lay.width, lay.height, p.corner_radius)
    extras = CrossSection()
    if p.frame:
        extras = extras + frame_section(outline, p.frame_width)
    if text is not None and p.text.strip():
        extras = extras + (text_section(text, lay, p.text_size, warns) ^ outline)

    plate = outline.extrude(p.base)
    if exact:
        raised = code_section(a.matrix, lay.qr_origin, lay.module) + extras
        solid = plate
        if not raised.is_empty():
            solid = plate + raised.extrude(p.relief).translate((0, 0, p.base))
        verts, tris = _mesh_arrays(solid)
    else:
        parts = [plate]
        if not extras.is_empty():
            parts.append(extras.extrude(p.relief).translate((0, 0, p.base)))
        verts, tris = _mesh_arrays(Manifold.compose(parts))
        bv, bt = _boxes(_code_runs(a.matrix, lay.qr_origin, lay.module), p.base, p.base + p.relief)
        tris = np.vstack([tris, bt + len(verts)]).astype(np.uint32)
        verts = np.vstack([verts, bv])
    return Model(np.ascontiguousarray(verts, dtype=np.float32), np.ascontiguousarray(tris),
                 p.base, p.base + p.relief, lay, warns)


def face_normals(vertices, triangles):
    v = vertices[triangles]
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    length = np.linalg.norm(n, axis=1, keepdims=True)
    length[length == 0] = 1.0
    return (n / length).astype(np.float32)


def write_stl(path, vertices, triangles):
    vertices = np.asarray(vertices, dtype=np.float32)
    triangles = np.asarray(triangles)
    rec = np.zeros(len(triangles), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"] = face_normals(vertices, triangles)
    rec["v"] = vertices[triangles]
    with open(path, "wb") as f:
        f.write(b"qr2stl".ljust(80, b" "))
        f.write(struct.pack("<I", len(triangles)))
        f.write(rec.tobytes())
    return path


def export_stl(model: Model, path):
    if not path.lower().endswith(".stl"):
        path += ".stl"
    return write_stl(path, model.vertices, model.triangles)
