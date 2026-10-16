"""Draw the Ventris app icon (ventris/assets/ventris.png). Run: python scripts/make_icon.py"""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

SIZE = 1024
OUT = Path(__file__).resolve().parent.parent / "ventris" / "assets" / "ventris.png"


def main() -> None:
    QGuiApplication([])
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = SIZE / 1024

    # tile
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(64 * s, 64 * s, 896 * s, 896 * s), 200 * s, 200 * s)
    grad = QLinearGradient(QPointF(0, 64 * s), QPointF(0, 960 * s))
    grad.setColorAt(0, QColor("#24324a"))
    grad.setColorAt(1, QColor("#121a29"))
    p.fillPath(tile, grad)

    def bar(x, y, w, color, h=56):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x * s, y * s, w * s, h * s), h * s / 2, h * s / 2)
        p.fillPath(path, QColor(color))

    # code lines on the left
    for y, w in [(250, 300), (350, 220), (550, 260), (650, 320), (750, 180)]:
        bar(170, y, w, "#5b6b85")
    # the highlighted line and its explanation panel
    bar(170, 450, 280, "#ffa348")
    panel = QPainterPath()
    panel.addRoundedRect(QRectF(560 * s, 300 * s, 300 * s, 360 * s), 48 * s, 48 * s)
    p.fillPath(panel, QColor("#e8eef8"))
    pointer = QPainterPath()
    pointer.moveTo(470 * s, 478 * s)
    pointer.lineTo(560 * s, 430 * s)
    pointer.lineTo(560 * s, 526 * s)
    pointer.closeSubpath()
    p.fillPath(pointer, QColor("#e8eef8"))
    for y, w in [(360, 200), (430, 160), (500, 210), (570, 130)]:
        bar(610, y, w, "#8aa0c4", h=36)
    p.end()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(OUT))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
