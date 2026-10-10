"""
tools/make_brand.py

Renders every piece of Pulse's brand artwork from src/frontend/brand.py:

  assets/pulse.ico                 the app/exe/installer icon, 7 layers
  assets/brand/pulse-icon.svg      the tile icon, vector
  assets/brand/pulse-icon-512.png  the tile icon, raster (README, releases)
  assets/brand/pulse-mark.svg      the bare mark on transparency, vector
  assets/brand/pulse-mark-512.png  the bare mark, raster — the source
                                   tools/make_installer_art.py composes from

EVERY ICO LAYER IS DRAWN AT ITS OWN SIZE, not downscaled from 256. A
downscaled 16px layer is a smear; drawn natively it gets brand.STROKE_SMALL
and a pixel-aligned tile, which is what keeps it legible in a taskbar.

Then re-run tools/make_installer_art.py so the Setup wizard follows.

Run:  python tools/make_brand.py
"""
from __future__ import annotations

import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

from frontend import brand  # noqa: E402

_ASSETS = os.path.join(_ROOT, "assets")
_BRAND = os.path.join(_ASSETS, "brand")

#: The layers Windows actually asks an .ico for, across DPI scales.
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def _blank(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    return img


def _to_pil(img: QImage) -> Image.Image:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def render_icon(size: int) -> Image.Image:
    img = _blank(size)
    p = QPainter(img)
    brand.paint_icon(p, size)
    p.end()
    return _to_pil(img)


def render_mark(size: int) -> Image.Image:
    img = _blank(size)
    p = QPainter(img)
    pad = size * brand.MARK_PAD
    brand.paint_mark(p, QRectF(pad, pad, size - 2 * pad, size - 2 * pad),
                     QColor(brand.SWEEP_START), QColor(brand.SWEEP_END))
    p.end()
    return _to_pil(img)


def write_ico(path: str) -> None:
    layers = [render_icon(s) for s in ICO_SIZES]
    # Pillow writes one entry per requested size from the image it is given
    # unless append_images supplies a native frame of that exact size.
    largest = layers[-1]
    largest.save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                 append_images=layers[:-1])


def main() -> int:
    # QPainter on a QImage needs a QGuiApplication alive for the raster engine.
    if QGuiApplication.instance() is None:
        main.app = QGuiApplication([])
    os.makedirs(_BRAND, exist_ok=True)

    written = []
    ico = os.path.join(_ASSETS, "pulse.ico")
    write_ico(ico)
    written.append(ico)

    for name, data in (("pulse-icon.svg", brand.svg_icon()),
                       ("pulse-mark.svg", brand.svg_mark())):
        path = os.path.join(_BRAND, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)
        written.append(path)

    for name, image in (("pulse-icon-512.png", render_icon(512)),
                        ("pulse-mark-512.png", render_mark(512))):
        path = os.path.join(_BRAND, name)
        image.save(path, optimize=True)
        written.append(path)

    for path in written:
        print(f"  {os.path.relpath(path, _ROOT):34} {os.path.getsize(path):>8,} bytes")
    print("\nNext: python tools/make_installer_art.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
