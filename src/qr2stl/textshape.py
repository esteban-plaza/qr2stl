"""Vectoriza texto con las fuentes del sistema (QPainterPath) para el núcleo.

Necesita una QGuiApplication creada (la base de fuentes de Qt vive ahí).
"""
import numpy as np
from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath

from .core import TextShape

_PX = 200.0  # tamaño de rasterización de la curva: más grande = curvas más finas


def text_shape(text: str, family: str = "", bold: bool = True) -> TextShape:
    text = text.strip()
    if not text:
        return TextShape([], 0.0)
    font = QFont(family) if family else QFont()
    font.setPixelSize(int(_PX))
    font.setBold(bold)
    font.setHintingPreference(QFont.PreferNoHinting)
    font.setKerning(True)
    cap = QFontMetricsF(font).capHeight() or _PX * 0.7

    path = QPainterPath()
    path.addText(0, 0, font, text)
    rect = path.boundingRect()
    if rect.isEmpty():
        return TextShape([], 0.0)
    contours = []
    for poly in path.toSubpathPolygons():
        pts = np.array([(pt.x(), pt.y()) for pt in poly], dtype=float)
        if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        # Qt usa Y hacia abajo y la línea base en y = 0: se da vuelta Y y se normaliza
        # para que las mayúsculas midan 1 y el texto arranque en x = 0.
        pts[:, 0] -= rect.left()
        pts[:, 1] = -pts[:, 1]
        contours.append(pts / cap)
    return TextShape(contours, rect.width() / cap)
