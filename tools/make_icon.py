"""Genera src/qr2stl/ui/icon.png (1024×1024): squircle estilo macOS con un QR en relieve.

    .venv/bin/python tools/make_icon.py
"""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qr2stl.core import ECC, qr_matrix  # noqa: E402

S = 1024
OUT = Path(__file__).resolve().parents[1] / "src/qr2stl/ui/icon.png"


def squircle(rect, n=5.0, steps=400):
    import math
    cx, cy = rect.center().x(), rect.center().y()
    a, b = rect.width() / 2, rect.height() / 2
    path = QPainterPath()
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        x = cx + a * (abs(c) ** (2 / n)) * (1 if c >= 0 else -1)
        y = cy + b * (abs(s) ** (2 / n)) * (1 if s >= 0 else -1)
        path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
    path.closeSubpath()
    return path


def main():
    if QGuiApplication.instance() is None:
        main.app = QGuiApplication(sys.argv)  # la base de fuentes vive en la app
    img = QImage(S, S, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    body = QRectF(100, 100, 824, 824)   # márgenes del template de íconos de macOS
    shape = squircle(body)
    p.setPen(Qt.NoPen)
    for i in range(18):                 # sombra suave
        p.setBrush(QColor(0, 0, 0, 5))
        p.drawPath(squircle(body.adjusted(-i, -i + 14, i, i + 14)))
    g = QLinearGradient(body.topLeft(), body.bottomLeft())
    g.setColorAt(0, QColor("#3a8dff"))
    g.setColorAt(1, QColor("#0a5bd8"))
    p.setBrush(g)
    p.drawPath(shape)

    # placa blanca en perspectiva leve, con el QR en relieve
    plate = QRectF(232, 212, 560, 600)
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawRoundedRect(plate.translated(0, 22), 48, 48)
    p.setBrush(QColor("#dfe4ea"))
    p.drawRoundedRect(plate.translated(0, 12), 48, 48)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(plate, 48, 48)

    matrix, _ = qr_matrix("qr2stl", ECC["L (7%)"], 0)
    n = len(matrix)
    area = QRectF(plate.left() + 50, plate.top() + 50, plate.width() - 100, plate.width() - 100)
    m = area.width() / n
    for dy, col in ((7, QColor("#000000")), (0, QColor("#1c1c1e"))):
        p.setBrush(col if dy == 0 else QColor(0, 0, 0, 90))
        for r, row in enumerate(matrix):
            for c, v in enumerate(row):
                if v:
                    p.drawRect(QRectF(area.left() + c * m, area.top() + r * m + dy * 0.5,
                                      m + 0.6, m + 0.6))
    # «texto» debajo
    p.setBrush(QColor("#1c1c1e"))
    y = area.bottom() + 26
    p.drawRoundedRect(QRectF(plate.center().x() - 130, y, 260, 22), 11, 11)
    p.end()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(OUT))
    print(OUT)


if __name__ == "__main__":
    main()
