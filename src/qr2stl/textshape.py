"""Vectoriza texto con las fuentes del sistema (QPainterPath) para el núcleo.

Necesita una QGuiApplication creada (la base de fuentes de Qt vive ahí).
"""
import numpy as np
from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath

from .core import LINE_PITCH, TextShape, text_block_height, text_lines

_PX = 200.0  # tamaño de rasterización de la curva: más grande = curvas más finas


def _line_contours(line, font):
    """Contornos de una línea en píxeles (Y hacia abajo, línea base en y = 0) y su caja."""
    path = QPainterPath()
    path.addText(0, 0, font, line)
    rect = path.boundingRect()
    contours = []
    for poly in path.toSubpathPolygons():
        pts = np.array([(pt.x(), pt.y()) for pt in poly], dtype=float)
        if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(pts) >= 3:
            contours.append(pts)
    return contours, rect


def text_shape(text: str, family: str = "", bold: bool = True) -> TextShape:
    """Texto de una o varias líneas, cada una centrada. Las mayúsculas miden 1, la línea
    base de la última línea está en y = 0 y el bloque arranca en x = 0."""
    lines = text_lines(text)
    if not lines:
        return TextShape([], 0.0, 0.0)
    font = QFont(family) if family else QFont()
    font.setPixelSize(int(_PX))
    font.setBold(bold)
    font.setHintingPreference(QFont.PreferNoHinting)
    font.setKerning(True)
    cap = QFontMetricsF(font).capHeight() or _PX * 0.7

    shaped = [_line_contours(line, font) if line else ([], None) for line in lines]
    widths = [r.width() / cap if r is not None and not r.isEmpty() else 0.0 for _, r in shaped]
    width = max(widths)
    if width <= 0:
        return TextShape([], 0.0, 0.0)
    contours = []
    n = len(lines)
    for i, ((cs, rect), w) in enumerate(zip(shaped, widths)):
        if not cs:
            continue
        baseline = (n - 1 - i) * LINE_PITCH        # la primera línea va arriba
        dx = (width - w) / 2                       # centrada respecto de la más ancha
        for pts in cs:
            # Qt usa Y hacia abajo: se da vuelta Y y se normaliza al alto de mayúsculas
            out = np.empty_like(pts)
            out[:, 0] = (pts[:, 0] - rect.left()) / cap + dx
            out[:, 1] = -pts[:, 1] / cap + baseline
            contours.append(out)
    return TextShape(contours, width, text_block_height(n))
