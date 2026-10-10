"""
The Pulse mark — one source of truth for every place the logo appears.

WHAT THE MARK IS. A single heartbeat trace: a flat baseline, one beat
(a short rise, a deep dip, a tall spike), back to baseline, ending in a
lit "live" point. It says the product's name rather than decorating it,
and it is built from straight segments with round joins so it survives
being drawn 16px tall in a taskbar as well as 256px in Explorer.

WHO DRAWS IT.
  * widgets.BrandMark paints it live in the title bar and the dashboard
    masthead, in the THEME's sweep (accent2 -> accent), so it follows
    light/dark like every other surface.
  * tools/make_brand.py renders the fixed-colour ARTWORK — the .ico, the
    PNG/SVG brand files under assets/brand/, and (through
    tools/make_installer_art.py) the Setup wizard images.

Both read the geometry below, so the in-app mark and the icon on the
desktop cannot drift apart.

Pure QtGui: no widgets, so tools can import it with only a QGuiApplication.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)

#: The trace, in a unit square (x right, y down). Baseline at 0.56 — a
#: hair below centre, because the beat's tall spike above it carries more
#: visual weight than the dip below, and this is where the two balance.
LINE: tuple[tuple[float, float], ...] = (
    (0.08, 0.56),
    (0.31, 0.56),
    (0.39, 0.42),
    (0.50, 0.78),
    (0.62, 0.20),
    (0.72, 0.56),
    (0.77, 0.56),
)

#: The live point the trace runs into, and its radius (unit square). A
#: hair of air between it and the trace's end, so it reads as a point the
#: line is heading for rather than a blob on the line.
HEAD: tuple[float, float] = (0.885, 0.56)
HEAD_R = 0.062

#: Stroke width as a fraction of the box. Small renders (<= 32px) get the
#: heavier one: at 16px the regular weight is a 1.4px line and antialiasing
#: takes most of it.
STROKE = 0.085
STROKE_SMALL = 0.125

#: Fixed ARTWORK colours (icon, installer, README). Brighter than the
#: in-app theme tokens on purpose: an icon competes with every other icon
#: on a desktop and a taskbar, an in-app mark only with its own chrome.
SWEEP_START = "#5fd6f2"   # cyan  — the theme's accent2 family, lifted
SWEEP_END = "#9c8cff"     # indigo-violet — the theme's accent family, lifted
TILE_TOP = "#1b2030"
TILE_BOTTOM = "#07080c"
TILE_LINE = "#ffffff"     # hairline rim, drawn at low alpha

#: Tile corner radius as a fraction of the tile — Windows 11's own app
#: tiles sit close to this.
TILE_RADIUS = 0.225


def line_path(box: QRectF) -> QPainterPath:
    """The trace mapped into `box`."""
    path = QPainterPath()
    for i, (x, y) in enumerate(LINE):
        pt = QPointF(box.left() + x * box.width(), box.top() + y * box.height())
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    return path


def sweep(box: QRectF, start: QColor, end: QColor) -> QLinearGradient:
    """The brand sweep, left to right across the mark's own box."""
    grad = QLinearGradient(box.left(), box.center().y(),
                           box.right(), box.center().y())
    grad.setColorAt(0.0, start)
    grad.setColorAt(1.0, end)
    return grad


def paint_mark(p: QPainter, box: QRectF, start: QColor, end: QColor,
               small: bool = False, head_glow: bool = True) -> None:
    """The trace plus its live point, in `box`. Caller owns opacity and
    any halo behind it."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    width = box.width() * (STROKE_SMALL if small else STROKE)
    pen = QPen(QBrush(sweep(box, start, end)), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(line_path(box))

    centre = QPointF(box.left() + HEAD[0] * box.width(),
                     box.top() + HEAD[1] * box.height())
    r = box.width() * HEAD_R * (1.25 if small else 1.0)
    p.setPen(Qt.PenStyle.NoPen)
    if head_glow and not small:
        glow = QRadialGradient(centre, r * 3.2)
        g0 = QColor(end)
        g0.setAlphaF(0.55)
        g1 = QColor(end)
        g1.setAlphaF(0.0)
        glow.setColorAt(0.0, g0)
        glow.setColorAt(1.0, g1)
        p.setBrush(glow)
        p.drawEllipse(centre, r * 3.2, r * 3.2)
    p.setBrush(end)
    p.drawEllipse(centre, r, r)
    if not small:
        # a white-hot core, so the point reads as lit rather than as a dot
        core = QColor("#ffffff")
        core.setAlphaF(0.85)
        p.setBrush(core)
        p.drawEllipse(centre, r * 0.45, r * 0.45)
    p.restore()


def paint_icon(p: QPainter, size: int) -> None:
    """The full app icon — tile, glow, rim, mark — filling a size x size
    canvas that the caller has already cleared to transparent."""
    small = size <= 32
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # Small sizes run edge to edge; large ones keep a hair of margin so
    # the rim's antialiasing is not clipped by the canvas.
    inset = 0.0 if small else size * 0.02
    tile = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    radius = tile.width() * TILE_RADIUS

    shape = QPainterPath()
    shape.addRoundedRect(tile, radius, radius)

    bg = QLinearGradient(tile.topLeft(), tile.bottomLeft())
    bg.setColorAt(0.0, QColor(TILE_TOP))
    bg.setColorAt(1.0, QColor(TILE_BOTTOM))
    p.fillPath(shape, bg)

    p.setClipPath(shape)
    # the beat's glow, centred on the spike rather than the tile
    glow_c = QPointF(tile.left() + tile.width() * 0.56,
                     tile.top() + tile.height() * 0.50)
    glow = QRadialGradient(glow_c, tile.width() * 0.55)
    g0 = QColor(SWEEP_END)
    g0.setAlphaF(0.26)
    g1 = QColor(SWEEP_START)
    g1.setAlphaF(0.0)
    glow.setColorAt(0.0, g0)
    glow.setColorAt(1.0, g1)
    p.fillRect(tile, glow)
    # a soft sheen across the top third
    sheen = QLinearGradient(tile.topLeft(), QPointF(tile.left(), tile.top() + tile.height() * 0.45))
    s0 = QColor("#ffffff")
    s0.setAlphaF(0.07)
    s1 = QColor("#ffffff")
    s1.setAlphaF(0.0)
    sheen.setColorAt(0.0, s0)
    sheen.setColorAt(1.0, s1)
    p.fillRect(tile, sheen)
    p.setClipping(False)

    if not small:
        rim = QColor(TILE_LINE)
        rim.setAlphaF(0.10)
        pen = QPen(rim, max(1.0, size / 256.0))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        half = pen.widthF() / 2.0
        p.drawRoundedRect(tile.adjusted(half, half, -half, -half),
                          radius - half, radius - half)

    pad = tile.width() * (0.10 if small else 0.14)
    paint_mark(p, tile.adjusted(pad, pad, -pad, -pad),
               QColor(SWEEP_START), QColor(SWEEP_END), small=small)
    p.restore()


#: Margin around the bare mark on its own canvas, as a fraction of the
#: canvas — enough for the live point's glow (HEAD_R x 3.2) to fade out
#: before the edge instead of being clipped by it.
MARK_PAD = 0.12


def svg_mark(size: int = 512) -> str:
    """The bare mark as SVG (transparent), for docs and the README."""
    pad = size * MARK_PAD
    s = size - 2 * pad
    pts = " ".join(f"{pad + x * s:.1f},{pad + y * s:.1f}" for x, y in LINE)
    hx, hy = pad + HEAD[0] * s, pad + HEAD[1] * s
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <defs>
    <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{SWEEP_START}"/>
      <stop offset="1" stop-color="{SWEEP_END}"/>
    </linearGradient>
    <radialGradient id="head">
      <stop offset="0" stop-color="{SWEEP_END}" stop-opacity="0.55"/>
      <stop offset="1" stop-color="{SWEEP_END}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <polyline points="{pts}" fill="none" stroke="url(#sweep)" stroke-width="{STROKE * s:.1f}" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="{hx:.1f}" cy="{hy:.1f}" r="{HEAD_R * s * 3.2:.1f}" fill="url(#head)"/>
  <circle cx="{hx:.1f}" cy="{hy:.1f}" r="{HEAD_R * s:.1f}" fill="{SWEEP_END}"/>
  <circle cx="{hx:.1f}" cy="{hy:.1f}" r="{HEAD_R * s * 0.45:.1f}" fill="#ffffff" fill-opacity="0.85"/>
</svg>
"""


def svg_icon(size: int = 512) -> str:
    """The full tile icon as SVG — same composition as paint_icon."""
    s = size
    inset = s * 0.02
    t = s - 2 * inset
    r = t * TILE_RADIUS
    pad = t * 0.14
    m = t - 2 * pad
    ox = oy = inset + pad
    pts = " ".join(f"{ox + x * m:.1f},{oy + y * m:.1f}" for x, y in LINE)
    hx, hy = ox + HEAD[0] * m, oy + HEAD[1] * m
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 {s} {s}">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{TILE_TOP}"/>
      <stop offset="1" stop-color="{TILE_BOTTOM}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.56" cy="0.50" r="0.55">
      <stop offset="0" stop-color="{SWEEP_END}" stop-opacity="0.26"/>
      <stop offset="1" stop-color="{SWEEP_START}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="0.45">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.07"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{SWEEP_START}"/>
      <stop offset="1" stop-color="{SWEEP_END}"/>
    </linearGradient>
    <radialGradient id="head">
      <stop offset="0" stop-color="{SWEEP_END}" stop-opacity="0.55"/>
      <stop offset="1" stop-color="{SWEEP_END}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect x="{inset:.1f}" y="{inset:.1f}" width="{t:.1f}" height="{t:.1f}" rx="{r:.1f}" fill="url(#tile)"/>
  <rect x="{inset:.1f}" y="{inset:.1f}" width="{t:.1f}" height="{t:.1f}" rx="{r:.1f}" fill="url(#glow)"/>
  <rect x="{inset:.1f}" y="{inset:.1f}" width="{t:.1f}" height="{t:.1f}" rx="{r:.1f}" fill="url(#sheen)"/>
  <rect x="{inset + 1:.1f}" y="{inset + 1:.1f}" width="{t - 2:.1f}" height="{t - 2:.1f}" rx="{r - 1:.1f}" fill="none" stroke="#ffffff" stroke-opacity="0.10" stroke-width="{max(1.0, s / 256):.1f}"/>
  <polyline points="{pts}" fill="none" stroke="url(#sweep)" stroke-width="{STROKE * m:.1f}" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="{hx:.1f}" cy="{hy:.1f}" r="{HEAD_R * m * 3.2:.1f}" fill="url(#head)"/>
  <circle cx="{hx:.1f}" cy="{hy:.1f}" r="{HEAD_R * m:.1f}" fill="{SWEEP_END}"/>
  <circle cx="{hx:.1f}" cy="{hy:.1f}" r="{HEAD_R * m * 0.45:.1f}" fill="#ffffff" fill-opacity="0.85"/>
</svg>
"""
