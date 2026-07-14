"""Render the code-native SVG application mark to required PNG sizes."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]


def render_icons() -> tuple[Path, ...]:
    source = ROOT / "resources" / "icon.svg"
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise RuntimeError(f"invalid SVG icon: {source}")
    outputs: list[Path] = []
    for size in (24, 64, 128):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        output = ROOT / "resources" / f"icon_{size}.png"
        if not image.save(str(output), "PNG"):
            raise RuntimeError(f"failed to save icon: {output}")
        outputs.append(output)
    return tuple(outputs)


if __name__ == "__main__":
    application = QGuiApplication.instance() or QGuiApplication(sys.argv)
    del application
    for path in render_icons():
        print(path)
