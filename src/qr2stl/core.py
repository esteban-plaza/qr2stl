"""Núcleo de qr2stl: matriz QR, malla, STL y cálculo de la pausa. Sin dependencias de UI."""
import math
import os
import struct
from dataclasses import dataclass, field

import qrcode
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q

ECC = {"L (7%)": ERROR_CORRECT_L, "M (15%)": ERROR_CORRECT_M,
       "Q (25%)": ERROR_CORRECT_Q, "H (30%)": ERROR_CORRECT_H}

MIN_MODULE_MM = 1.5
_EPS = 1e-6


# ---------------------------------------------------------------- QR
def qr_matrix(data, ecc, border):
    qr = qrcode.QRCode(version=None, error_correction=ecc, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.get_matrix(), qr.version  # la matriz ya incluye el borde


# ---------------------------------------------------------------- Malla
def build_mesh(cells, n, cell):
    """cells: {(fila, col): (z0, z1)}. Genera una superficie cerrada
    (sin caras internas) a partir de columnas por celda."""
    tris = []
    # Todas las paredes se parten en todos los niveles Z usados; así los bordes verticales
    # de paredes vecinas coinciden y no quedan uniones en T (pasaba con borde 0).
    levels = sorted({z for zz in cells.values() for z in zz})

    def split(lo, hi):
        cuts = [lo] + [z for z in levels if lo < z < hi] + [hi]
        return list(zip(cuts, cuts[1:]))

    def quad(a, b, c, d):
        tris.append((a, b, c))
        tris.append((a, c, d))

    def exposed(z0, z1, nb):
        if nb is None:
            return split(z0, z1)
        segs = []
        if nb[1] < z1:
            segs.append((max(z0, nb[1]), z1))
        if nb[0] > z0:
            segs.append((z0, min(z1, nb[0])))
        return [s for lo, hi in segs if hi > lo for s in split(lo, hi)]

    for (r, c), (z0, z1) in cells.items():
        x0, x1 = c * cell, (c + 1) * cell
        y0, y1 = (n - 1 - r) * cell, (n - r) * cell  # fila 0 arriba => no espejado
        quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))  # techo
        quad((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0))  # piso
        for lo, hi in exposed(z0, z1, cells.get((r, c + 1))):  # +X
            quad((x1, y0, lo), (x1, y1, lo), (x1, y1, hi), (x1, y0, hi))
        for lo, hi in exposed(z0, z1, cells.get((r, c - 1))):  # -X
            quad((x0, y1, lo), (x0, y0, lo), (x0, y0, hi), (x0, y1, hi))
        for lo, hi in exposed(z0, z1, cells.get((r - 1, c))):  # +Y
            quad((x1, y1, lo), (x0, y1, lo), (x0, y1, hi), (x1, y1, hi))
        for lo, hi in exposed(z0, z1, cells.get((r + 1, c))):  # -Y
            quad((x0, y0, lo), (x1, y0, lo), (x1, y0, hi), (x0, y0, hi))
    return tris


def single_cells(matrix, base, relief):
    n = len(matrix)
    return {(r, c): (0.0, base + (relief if matrix[r][c] else 0.0))
            for r in range(n) for c in range(n)}


def split_cells(matrix, base, relief):
    n = len(matrix)
    base_cells = {(r, c): (0.0, base) for r in range(n) for c in range(n)}
    code_cells = {(r, c): (base, base + relief)
                  for r in range(n) for c in range(n) if matrix[r][c]}
    return base_cells, code_cells


def write_stl(path, tris):
    with open(path, "wb") as f:
        f.write(b"qr2stl".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            l = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
            f.write(struct.pack("<12fH", nx / l, ny / l, nz / l, *a, *b, *c, 0))


def generate(matrix, size, base, relief, mode, path):
    """mode: "single" (1 STL) o "split" (_base + _codigo). Devuelve las rutas escritas."""
    n = len(matrix)
    cell = size / n
    root, _ = os.path.splitext(path)
    if mode == "single":
        write_stl(root + ".stl", build_mesh(single_cells(matrix, base, relief), n, cell))
        return [root + ".stl"]
    base_cells, code_cells = split_cells(matrix, base, relief)
    write_stl(root + "_base.stl", build_mesh(base_cells, n, cell))
    write_stl(root + "_codigo.stl", build_mesh(code_cells, n, cell))
    return [root + "_base.stl", root + "_codigo.stl"]


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


@dataclass
class Params:
    url: str = "https://"
    size: float = 50.0
    base: float = 1.2
    relief: float = 0.8
    border: int = 2
    layer: float = 0.2
    first_layer: float = 0.2
    ecc: str = "M (15%)"


@dataclass
class Analysis:
    matrix: list
    version: int
    n: int
    module: float
    pause_layer: int
    pause_z: float
    warnings: list = field(default_factory=list)


def analyze(p: Params) -> Analysis:
    """Calcula la matriz y los avisos. Lanza ValueError si los parámetros no sirven."""
    data = p.url.strip()
    if not data:
        raise ValueError("La URL está vacía.")
    if p.size <= 0 or p.base <= 0 or p.relief <= 0 or p.layer <= 0 or p.first_layer <= 0:
        raise ValueError("Las medidas tienen que ser > 0.")
    try:
        matrix, version = qr_matrix(data, ECC[p.ecc], p.border)
    except qrcode.exceptions.DataOverflowError:
        raise ValueError("La URL no entra en un QR (demasiado larga).") from None
    n = len(matrix)
    module = p.size / n
    k, z = pause_layer(p.base, p.layer, p.first_layer)

    warns = []
    if module < MIN_MODULE_MM:
        warns.append("módulo chico (< 1.5 mm): agrandá el lado o acortá la URL")
    if p.first_layer >= p.base:
        warns.append("la base no supera la primera capa")
    elif not _is_multiple(p.base - p.first_layer, p.layer):
        warns.append(f"la base no cae en un borde de capa: el cambio queda en Z = {z:.2f} mm")
    if not _is_multiple(p.relief, p.layer):
        warns.append("el relieve no es múltiplo de la altura de capa")
    elif round(p.relief / p.layer) < 2:
        warns.append("relieve de 1 sola capa: poco contraste")
    return Analysis(matrix, version, n, module, k, z, warns)
