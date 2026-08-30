"""
src/frontend/animations.py

MOTION SUBSYSTEM — every animation in the app, engineered for 60 fps.

Performance doctrine (this is what fixed the stutter):
    1. NO QGraphicsEffect in steady state. QGraphicsDropShadowEffect and
       friends force the whole widget subtree through a CPU-rasterized
       offscreen pixmap on every repaint — that was the old hover-glow lag.
       Hover glows are now painted directly in paintEvent (GlowController
       + paint_glow_frame): a two-pass gradient stroke, microseconds each.
    2. NO setStyleSheet() inside timers. The old shimmer rebuilt a QSS
       string every 40 ms, forcing a full style re-polish 25×/sec.
       ShimmerBar paints its gradient itself; a repaint costs ~0.05 ms.
    3. QVariantAnimation everywhere. It rides Qt's unified animation
       driver (~60 fps, frame-coalesced) instead of ad-hoc QTimers, and
       gives us clean easing curves for free.
    4. Opacity effects appear ONLY transiently (cascade entrance / page
       fade), are shared with a QParallelAnimationGroup, and are destroyed
       the instant the animation finishes.

Import graph: theme.py <- animations.py <- widgets.py <- main.py
(this module never imports widgets or main).
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPoint,
    QPointF, QPropertyAnimation, QRectF, QSequentialAnimationGroup,
    QVariantAnimation, Qt,
)
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

# ============================================================
#  MOTION CONSTANTS — one place to tune the whole app's feel
# ============================================================
HOVER_MS      = 130    # glow ramp in/out
CASCADE_MS    = 170    # per-card entrance
CASCADE_GAP   = 26     # stagger between waves
CASCADE_RISE  = 18     # px slide-up distance
PAGE_FADE_MS  = 150    # stacked-page cross fade

#: Hard ceiling on a cascade's STAGGER window, and the reason navigation
#: stopped feeling slow.
#:
#: The stagger used to be `card_index * CASCADE_GAP`, i.e. unbounded in the
#: number of cards. Measured on the shipping pages, that made the entrance
#: duration a function of page density:
#:
#:     Utilities & Tools   14 cards -> 13*26 + 170 = 508 ms
#:     Software Management 13 cards -> 12*26 + 170 = 482 ms
#:
#: and 508 ms is exactly what the switch to that module measured end to end.
#: The page was laid out and painted within ~2 ms; everything after that was
#: this animation withholding content. A denser module was PUNISHED with a
#: longer wait, which is precisely backwards.
#:
#: Two changes bound it. Callers now stagger by WAVE (a grid row) rather
#: than per card — cards that share a row light together, which is how the
#: eye reads a grid anyway — and whatever the wave count, the total stagger
#: is compressed to fit this budget. The entrance can never cost more than
#: CASCADE_BUDGET_MS + CASCADE_MS, on any page, at any column count.
CASCADE_BUDGET_MS = 190
SHIMMER_MS    = 1200   # one full progress sweep (indeterminate loop, not a
                       # transition — left at its original pace on purpose)

EASE_OUT  = QEasingCurve.Type.OutCubic
EASE_INOUT = QEasingCurve.Type.InOutQuad


# ============================================================
#  HOVER GLOW — effect-free, cursor-tracking border sweep
# ============================================================
class GlowController(QObject):
    """Drives a hover glow WITHOUT QGraphicsEffect.

    Install on any widget whose paintEvent calls paint_glow_frame():

        self._glow = GlowController(self, accent="#00d4ff")
        ...
        def paintEvent(self, e):
            super().paintEvent(e)
            p = QPainter(self)
            paint_glow_frame(p, self.rect(), radius=16,
                             color=self._glow.color,
                             intensity=self._glow.intensity,
                             cursor=self._glow.cursor)

    The controller animates a 0..1 intensity on Enter/Leave (OutCubic,
    HOVER_MS) and tracks the cursor so the radial sweep follows the mouse.
    Repaints are driven by the animation frames + hover moves only.
    """

    def __init__(self, widget: QWidget, accent: str = "#4cc2ff"):
        super().__init__(widget)
        self._widget = widget
        self._intensity = 0.0
        self._cursor = QPointF()
        self.color = QColor(accent)
        # Per-mode glow weights (theme.glow_alphas) — owned here so every
        # paint site reads the same pair it already reads color/intensity
        # from. Defaults match dark mode; apply_theme overwrites both.
        self.halo_alpha = 0.38
        self.edge_alpha = 0.90

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(HOVER_MS)
        self._anim.setEasingCurve(EASE_OUT)
        self._anim.valueChanged.connect(self._on_frame)

        widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        widget.installEventFilter(self)

    # -- public state read by paintEvent ----------------------
    @property
    def intensity(self) -> float:
        return self._intensity

    @property
    def cursor(self) -> QPointF:
        return self._cursor

    def set_accent(self, accent: str):
        """Live theme switch — next repaint uses the new color."""
        self.color = QColor(accent)
        self._widget.update()

    def set_alphas(self, halo: float, edge: float):
        """Live theme switch for the glow weights — call alongside
        set_accent with theme.glow_alphas(t)."""
        self.halo_alpha = halo
        self.edge_alpha = edge
        self._widget.update()

    # -- internals --------------------------------------------
    def _on_frame(self, value: float):
        self._intensity = float(value)
        self._widget.update()

    def _ramp_to(self, target: float):
        self._anim.stop()
        self._anim.setStartValue(self._intensity)
        self._anim.setEndValue(target)
        self._anim.start()

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.HoverEnter:
            self._cursor = event.position()
            self._ramp_to(1.0)
        elif et == QEvent.Type.HoverLeave:
            self._ramp_to(0.0)
        elif et == QEvent.Type.HoverMove and self._intensity > 0.0:
            self._cursor = event.position()
            self._widget.update()
        return False


def clip_to_surface(painter: QPainter, rect, radius: int) -> None:
    """Confine everything painted after this to the surface's OWN rounded
    shape. Call inside a painter.save()/restore() pair.

    THIS IS THE FIX FOR "THE BORDER OVERFLOWS ON HOVER", and the defect it
    removes is a change of SILHOUETTE, not of geometry — which is why it
    survived every check that looked at widget rects.

    A card's four corner wedges (the area between the rounded boundary and
    the square widget rect) are transparent, and every perimeter stroke in
    this module is drawn on a rounded rect INSET from that boundary. An
    inset rounded rect is not concentric with its parent unless the radius
    is shrunk to match — the arcs are, now (see paint_accent_hairline) —
    but the PEN still has width, and half of it lands outside whatever path
    it is centred on. The glow's outer halo is a 5px pen: 2.5px of it sits
    beyond its own path, which at the corners is beyond the card.

    Measured on a 320x156 card at radius 12, hovered at full intensity:
    paint_glow_frame put 88 pixels of accent ink at up to alpha 57 into the
    corner wedges, and paint_accent_hairline another 28 at alpha 58. At
    rest the same corners carry 8 pixels at alpha 13. So hovering did not
    merely light the card's edge — it grew ink outside the card's shape,
    and the eye reads a silhouette that changes between two states as the
    box having moved.

    Clipping is the right instrument rather than insetting each stroke
    further: an inset changes where the light sits (and a glow that stops
    3px short of the edge is no longer an edge glow), while a clip changes
    only whether ink may leave the shape. Inside the boundary every stroke
    lands exactly where it did before, so the treatment is unchanged.

    NOT APPLIED TO THE CAST SHADOW. paint_drop_shadow's whole job is to
    paint outside the surface; clipping it would delete it.
    """
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), float(radius), float(radius))
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)


def paint_glow_frame(painter: QPainter, rect, radius: int,
                     color: QColor, intensity: float,
                     cursor: QPointF | None = None,
                     halo_alpha: float = 0.38, edge_alpha: float = 0.90):
    """Paint a radial-gradient border glow centered on the cursor.

    Two gradient strokes on a rounded rect — no offscreen buffers, no
    effects, safe to call on every repaint. Cost is negligible even with
    a full grid of cards hovered rapidly.

    halo_alpha / edge_alpha are per-mode weights (theme.glow_alphas);
    call sites that own a GlowController pass its `.halo_alpha` /
    `.edge_alpha` so a theme switch retunes every glow at once. Defaults
    are the dark-mode pair.
    """
    if intensity <= 0.01:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # Pass 1 below is a FIVE PIXEL pen on a path 1px inside the boundary,
    # so 1.5px of it falls outside the card entirely. See clip_to_surface.
    clip_to_surface(painter, rect, radius)

    center = cursor if cursor is not None else QPointF(rect.center())
    reach = max(rect.width(), rect.height()) * 0.95
    inner = rect.adjusted(1, 1, -1, -1)
    # THE HALO GETS ITS OWN PATH, inset by half its own pen width so the
    # OUTER edge of a 5px stroke lands on the surface boundary rather than
    # 1.5px beyond it. The clip above already stops the ink escaping; this
    # is what stops it being clipped in the first place, which matters
    # because a 5px gradient pen sheared off by a clip edge reads as a hard
    # line where the design wants a fade. Inside the boundary the light is
    # unchanged — the band simply runs [0, +5] from the edge instead of
    # [-1.5, +3.5].
    halo_pen = 5.0
    halo_inset = halo_pen / 2.0
    halo_rect = QRectF(rect).adjusted(halo_inset, halo_inset,
                                      -halo_inset, -halo_inset)
    halo_radius = max(0.0, radius - halo_inset)
    # Shrunk with the inset, for the reason spelled out in
    # paint_accent_hairline: an inset rounded rect at an unchanged radius is
    # not concentric with its boundary. It matters less here (both passes are
    # soft gradients) but pass 2 is a 1.6px near-crisp edge sitting directly
    # under the hairline, so leaving it mis-curved would put back a faint
    # second corner line the moment the hairline stopped drawing one.
    inner_radius = max(0.0, radius - 1)

    # pass 1: soft outer halo
    halo = QRadialGradient(center, reach)
    c = QColor(color)
    c.setAlphaF(halo_alpha * intensity)
    halo.setColorAt(0.0, c)
    c2 = QColor(color)
    c2.setAlphaF(0.0)
    halo.setColorAt(1.0, c2)
    painter.setPen(QPen(QBrush(halo), halo_pen))
    painter.drawRoundedRect(halo_rect, halo_radius, halo_radius)

    # pass 2: crisp inner edge
    edge = QRadialGradient(center, reach * 0.8)
    e1 = QColor(color)
    e1.setAlphaF(edge_alpha * intensity)
    edge.setColorAt(0.0, e1)
    e2 = QColor(color)
    e2.setAlphaF(0.10 * intensity)
    edge.setColorAt(1.0, e2)
    painter.setPen(QPen(QBrush(edge), 1.6))
    painter.drawRoundedRect(inner, inner_radius, inner_radius)
    painter.restore()


def paint_accent_hairline(painter: QPainter, rect, radius: int,
                          color: QColor, intensity: float,
                          alpha: float = 0.55, width: float = 1.0):
    """A uniform 1px accent border that fades in with hover.

    The COMPANION to paint_glow_frame, not a replacement for it, and the
    pair is deliberate: the glow is a radial sweep centred on the cursor,
    so it lights the edge nearest the pointer and leaves the far side of a
    wide card unchanged — beautiful up close, but on its own it never quite
    says "this whole card is the thing you are pointing at". This draws the
    full perimeter at an even weight underneath it. Together they read as a
    lit edge with a bright spot travelling along it.

    A SOLID pen, unlike every other stroke in this module, which is why it
    needs no pixmap cache: the caching machinery exists because Qt's
    software rasteriser evaluates a GRADIENT pen per pixel along the stroke
    (~114 us a card). A flat colour is a fast path — microseconds — and
    caching it per hover frame would cost more than it saved.

    CONCENTRICITY (the corner-doubling fix). `radius` is the radius of the
    surface's OUTER boundary — the one QSS draws at the widget rect. Insetting
    a rounded rect does not preserve its corner geometry: the arc centre moves
    in with the rect, so an inset path drawn at the SAME radius bulges away
    from the boundary everywhere except the four straight runs. At the 45°
    point of a 14px corner the stroke landed 0.707px inside the boundary
    instead of 0.5 — a 0.207px drift, invisible on the flat edges and just
    wide enough at the corners for antialiasing to resolve the hairline and
    the card's own border as TWO lines. That is the ugly double edge; the
    hairline was never misplaced, only mis-curved.

    Concentric requires shrinking the radius by the same inset, so the arc
    centre stays put. The inset is derived from the pen width rather than
    hardcoded, so a caller asking for a heavier stroke still gets it fully
    inside the boundary instead of half of it clipped away.
    """
    if intensity <= 0.01:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # Concentric arcs (below) put the stroke's CENTRE where it belongs;
    # the outer half of the pen still crosses the boundary at the corners.
    clip_to_surface(painter, rect, radius)
    edge = QColor(color)
    edge.setAlphaF(max(0.0, min(1.0, alpha * intensity)))
    painter.setPen(QPen(edge, width))
    inset = width / 2.0
    inner = QRectF(rect).adjusted(inset, inset, -inset, -inset)
    r = max(0.0, radius - inset)
    painter.drawRoundedRect(inner, r, r)
    painter.restore()


def paint_nav_indicator(painter: QPainter, rect, c1: QColor, c2: QColor,
                        inset: int = 8, bar_width: float = 3.0):
    """Left-edge active-item bar for the selected sidebar entry — the same
    affordance Windows 11 Settings uses to mark its selected nav item.
    A short rounded bar with the app's accent->accent2 brand gradient
    running top to bottom; call only while the item is selected (see
    widgets.NavButton.paintEvent). One drawRoundedRect, no offscreen buffer.
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    bar = QRectF(rect.left() + 4, rect.top() + inset,
                bar_width, rect.height() - inset * 2)
    grad = QLinearGradient(bar.topLeft(), bar.bottomLeft())
    grad.setColorAt(0.0, c1)
    grad.setColorAt(1.0, c2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(grad))
    painter.drawRoundedRect(bar, bar_width / 2.0, bar_width / 2.0)
    painter.restore()


# ------------------------------------------------------------------
#  PERIMETER STROKE CACHE
# ------------------------------------------------------------------
# The bevel and sheen below are STATIC for a given (size, radius, alpha)
# — they do not vary with hover, focus or animation state — yet they were
# re-stroked on every repaint of every card and nav entry. Profiling a
# full-window render put paint_bevel_frame at 1.60 ms across 14 calls
# (~114 us each), 17% of the entire frame: stroking an antialiased rounded
# rect with a GRADIENT PEN is a slow path in Qt's software rasterizer,
# because the gradient is evaluated per pixel along the stroke.
#
# Rendering each distinct stroke once into a transparent pixmap and
# blitting it afterwards keeps the result pixel-identical while turning
# the per-repaint cost into a plain alpha blit.
#
# The cache is keyed on everything that changes the pixels (including the
# device pixel ratio, so a mixed-DPI multi-monitor setup can't blit a
# stroke rasterised for the wrong display) and is HARD-BOUNDED — an
# unbounded size-keyed pixmap cache is exactly what once leaked 11.9 GB
# across a single resize drag.
_STROKE_CACHE: dict[tuple, QPixmap] = {}
_STROKE_CACHE_MAX = 96


def _cached_stroke(painter: QPainter, rect, key: tuple, draw) -> None:
    """Blit a cached perimeter stroke, rasterising it on first use.
    `draw(p, w, h)` paints the stroke into a w x h transparent pixmap."""
    width, height = int(rect.width()), int(rect.height())
    if width <= 0 or height <= 0:
        return
    device = painter.device()
    try:
        dpr = float(device.devicePixelRatioF())
    except AttributeError:
        dpr = 1.0
    dpr = dpr or 1.0
    full_key = (width, height, round(dpr, 3)) + key
    pixmap = _STROKE_CACHE.get(full_key)
    if pixmap is None:
        pixmap = QPixmap(max(1, round(width * dpr)), max(1, round(height * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.NoBrush)
        draw(p, width, height)
        p.end()
        if len(_STROKE_CACHE) >= _STROKE_CACHE_MAX:
            _STROKE_CACHE.clear()
        _STROKE_CACHE[full_key] = pixmap
    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.drawPixmap(rect.topLeft(), pixmap)
    painter.restore()


#: THE DUAL-RAMP CAST SHADOW, as multipliers on the single (alpha, spread)
#: pair theme.shadow_alphas hands over. Kept here rather than in theme.py
#: because these describe the RASTERISATION, not the design weight: theme
#: still owns "how dark, how far", this owns "in what shape".
#:
#: Each tuple is (spread_mul, alpha_mul, falloff_exp, ...):
#:
#:   CONTACT  — the tight, near-opaque line that puts the card in touch with
#:              the surface. Short and steep. This is essentially what the
#:              old single ramp already was: at ybot 0.35 its strokes piled
#:              up inside ~2px of the bottom edge, so measured, the shipping
#:              "spread 6" shadow had a reach of ONE pixel. It read as an
#:              edge, never as height.
#:
#:   AMBIENT  — the wide, faint halo that reads as elevation, and the half
#:              that did not exist before. ybot 1.0 is what makes it a
#:              gradient rather than a stack: each successive stroke clears
#:              the last by a full pixel, so the falloff is actually spent
#:              across `spread` px instead of collapsing onto the edge.
#:
#: v13 drops the CONTACT amplitude 1.15 -> 0.85. It is not a taste change
#: and it is not independent of theme.shadow_alphas: that function raised
#: its dark weight 0.26 -> 0.34 in the same revision, and this multiplier
#: is what decides where the extra weight lands. Left at 1.15 the raise
#: would have gone almost entirely into the contact line (peak 91 -> 116 of
#: 255), which is the "grubby lower lip" the dual ramp was built to get rid
#: of. At 0.85 the contact peak holds at ~94 while the ambient — whose
#: multiplier is unchanged, so it scales with the raise — gains the full
#: 30%. Elevation is the tail; the edge was never the problem.
_SHADOW_CONTACT = (0.50, 0.85, 2.4, 2.00, 0.40)   # + (ytop, ybot)
_SHADOW_AMBIENT = (2.00, 0.36, 1.5, 1.00)          # + (ybot); top is pinned


def paint_drop_shadow(painter: QPainter, rect, radius: int,
                      alpha: float = 0.055, spread: int = 6):
    """The soft cast shadow under an elevated surface — the primary
    elevation cue in both themes (see theme.shadow_alphas).

    Qt QSS has no box-shadow, and QGraphicsDropShadowEffect is off the table
    here: it re-renders the widget into an offscreen buffer every repaint,
    which is precisely the per-frame cost animations.py exists to avoid, and
    it would apply to every card in a grid at once.

    So the shadow is painted, and painted INSIDE the widget rect — a layout
    clips a child to its own geometry, so there is no canvas outside a card
    to cast onto. That sounds like a compromise and mostly isn't: what the
    eye reads as a drop shadow is the soft darkening gradient hugging the
    lower edge of the surface, and drawing that gradient just inside the
    edge produces the same cue. The tell it cannot reproduce is a shadow
    falling ON a neighbour, which at these alphas is invisible anyway.

    TWO RAMPS, NOT ONE (v12.2), because the single ramp was only ever
    producing half the effect. Measured on a 320x150 card at the dark
    theme's own alpha, reading pixel alpha upward from the bottom edge:

        one ramp, spread 6 ....  96  29   1   0   0   0   0  ->  reach  1px
        contact + ambient .....  91  25  17  14  12  10   8  ->  reach  9px

    The old construction spent its whole falloff inside two pixels, so it
    delivered a crisp contact edge and no elevation at all — which is why
    cards read as drawn-on rather than raised. The peak is deliberately
    UNCHANGED (96 -> 91): the edge was never the problem, and darkening it
    further would just look grubby. Everything gained is in the new tail.

    THE AMBIENT'S TOP IS PINNED OFF-CANVAS, and that is a correctness fix
    rather than a flourish. Each ramp step is a CLOSED rounded rect, so its
    top edge lands as a horizontal ring inside the card. The old ramp did
    this too (its top profile reads 43 23 43 9 22 — visibly non-monotone),
    and simply widening the spread would have smeared those rings across
    26px of the card's upper half. Spanning the ambient rect from -h to
    +h instead means only its sides and bottom arc are ever inside the
    pixmap. Measured, the ambient contributes exactly ZERO to the top
    profile, and the total top weight drops from 164 to 108.

    BOTH RAMPS RASTERISE INTO ONE CACHED PIXMAP under one key, so a grid of
    cards still costs exactly one blit each — the per-frame budget is
    byte-for-byte what it was. Only the one-time rasterisation grows, from
    6 strokes to 15, and only on a cache miss.
    """
    if alpha <= 0.002 or spread <= 0:
        return
    peak = int(255 * alpha)
    if peak <= 0:
        return

    c_smul, c_amul, c_exp, c_ytop, c_ybot = _SHADOW_CONTACT
    a_smul, a_amul, a_exp, a_ybot = _SHADOW_AMBIENT
    contact_spread = max(1, int(round(spread * c_smul)))
    ambient_spread = max(1, int(round(spread * a_smul)))
    contact_peak = int(peak * c_amul)
    ambient_peak = int(peak * a_amul)

    def draw(p, width, height):
        w, h = float(width), float(height)

        # -- ambient first, so the contact edge composites ON TOP of it --
        for i in range(ambient_spread):
            a = int(ambient_peak * (1.0 - i / float(ambient_spread)) ** a_exp)
            if a <= 0:
                continue
            inset = 0.5 + i
            # Spans -h..+h: the top edge (and its corners) sit outside the
            # pixmap, so only the sides and the bottom arc ever render.
            inner = QRectF(0.0, -h, w, h * 2.0).adjusted(
                inset, 0.0, -inset, -inset * a_ybot)
            if inner.width() <= 1 or inner.height() <= 1:
                break
            p.setPen(QPen(QColor(0, 0, 0, a), 1.0))
            p.drawRoundedRect(inner, radius, radius)

        # -- contact: short, steep, and biased hard toward the bottom --
        for i in range(contact_spread):
            a = int(contact_peak * (1.0 - i / float(contact_spread)) ** c_exp)
            if a <= 0:
                continue
            inset = 0.5 + i
            inner = QRectF(0.0, 0.0, w, h).adjusted(
                inset, inset * c_ytop, -inset, -inset * c_ybot)
            if inner.width() <= 1 or inner.height() <= 1:
                break
            p.setPen(QPen(QColor(0, 0, 0, a), 1.0))
            p.drawRoundedRect(inner, radius, radius)

    _cached_stroke(painter, rect, ("shadow", int(radius), peak, int(spread)),
                   draw)


def paint_bevel_frame(painter: QPainter, rect, radius: int,
                      light_alpha: float = 0.14, dark_alpha: float = 0.20):
    """Permanent glass-edge bevel — depth + a sub-pixel highlight in one
    pass. A single rounded-rect stroke whose pen is a diagonal gradient:
    a bright top-left highlight sweeping through to a soft bottom-right
    shadow. This is the alternative to per-side `border-top-color` /
    `border-bottom-color` QSS rules, which artifact at rounded corners in
    Qt's software rasterizer (see card_qss's comment on the same finding).

    Cached and blitted rather than re-stroked — see _cached_stroke.
    """
    light = int(255 * light_alpha)
    dark = int(255 * dark_alpha)

    def draw(p, width, height):
        # inset by half a device pixel so a 1px cosmetic pen lands crisply
        # instead of anti-aliasing across two rows
        inner = QRectF(0.0, 0.0, float(width), float(height)).adjusted(
            0.5, 0.5, -0.5, -0.5)
        grad = QLinearGradient(inner.topLeft(), inner.bottomRight())
        grad.setColorAt(0.0, QColor(255, 255, 255, light))
        grad.setColorAt(1.0, QColor(0, 0, 0, dark))
        p.setPen(QPen(QBrush(grad), 1.0))
        p.drawRoundedRect(inner, radius, radius)

    _cached_stroke(painter, rect, ("bevel", int(radius), light, dark), draw)


# ============================================================
#  v7 MATERIAL — squircle corners, top sheen, Aurora lit edge
# ============================================================
def squircle_path(rect, radius: float, smoothing: float = 0.55) -> QPainterPath:
    """A continuous-corner ("squircle") rounded-rect path — the Apple-style
    super-ellipse Qt's own `drawRoundedRect` (plain circular arcs) can't
    produce. Each corner is a single cubic Bézier whose transition spreads
    WIDER along the edge than a circular arc (d > radius), so curvature eases
    in and out of the straight edges instead of meeting them abruptly. Used
    only on the featured/hero bento card, where the softer corner is worth
    the (still microsecond) extra path cost; standard cards keep the cheaper
    QSS radius."""
    rf = QRectF(rect)
    d = min(float(radius) * (1.0 + smoothing),
            min(rf.width(), rf.height()) / 2.0)
    h = d * 0.45   # Bézier handle length — < d keeps the corner continuous
    x0, y0, x1, y1 = rf.left(), rf.top(), rf.right(), rf.bottom()
    path = QPainterPath()
    path.moveTo(x0 + d, y0)
    path.lineTo(x1 - d, y0)
    path.cubicTo(x1 - h, y0, x1, y0 + h, x1, y0 + d)
    path.lineTo(x1, y1 - d)
    path.cubicTo(x1, y1 - h, x1 - h, y1, x1 - d, y1)
    path.lineTo(x0 + d, y1)
    path.cubicTo(x0 + h, y1, x0, y1 - h, x0, y1 - d)
    path.lineTo(x0, y0 + d)
    path.cubicTo(x0, y0 + h, x0 + h, y0, x0 + d, y0)
    path.closeSubpath()
    return path


def paint_top_sheen(painter: QPainter, rect, radius: int,
                    strength: float = 1.0, peak: int = 150,
                    depth: float = 3.0):
    """A crisp 1px highlight hugging the TOP edge of a surface, fading to
    nothing within a few pixels — the 'lit from above' tell that separates a
    premium material from a flat translucent panel. A perimeter stroke whose
    pen brush is a short vertical gradient (bright white at the very top,
    transparent just below, PadSpread keeping the sides/bottom clear), so
    only the top edge lights up. Cached and blitted — see _cached_stroke.

    `peak` (the white alpha at full strength) and `depth` (how far down the
    fade runs) ARRIVE FROM THE THEME — see theme.sheen_alphas — because the
    single hard-coded 150 could not serve both canvases, for opposite
    reasons in each:

      * on obsidian, 150 x the resting 0.55 strength is alpha 82, which on
        a #22252E card lifts the top edge by about six levels of grey. It
        is present under measurement and invisible across a room.

      * on paper it was worse than weak, it was BACKWARDS. The light card
        is #FFFFFF and its hairline is #B7BAC4 (183) against a #F2F2F7
        (242) well — so the untreated top edge is DARKER than the surface
        behind it. That is the optical signature of a groove, not a lift,
        and no amount of shadow underneath fixes an edge that reads as cut
        into the page. Bleaching that top hairline toward white is what
        flips it: at light's peak the top edge lands lighter than the well
        it sits against, so the eye finally reads the card as standing
        proud of the page rather than stamped into it.

    The stroke also moves from a 0.75px inset to 0.5px, so it lands ON the
    QSS border row rather than straddling it and antialiasing across two.
    That is what makes the light-mode bleach a clean edge instead of a
    smear.
    """
    if strength <= 0.01:
        return
    hi_alpha = int(peak * strength)
    if hi_alpha <= 0:
        return
    fade = max(1.0, float(depth))

    def draw(p, width, height):
        inner = QRectF(0.0, 0.0, float(width), float(height)).adjusted(
            0.5, 0.5, -0.5, -0.5)
        grad = QLinearGradient(inner.left(), inner.top(),
                               inner.left(), inner.top() + fade)
        grad.setColorAt(0.0, QColor(255, 255, 255, hi_alpha))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(QPen(QBrush(grad), 1.0))
        p.drawRoundedRect(inner, radius, radius)

    _cached_stroke(painter, rect,
                   ("sheen", int(radius), hi_alpha, round(fade, 2)), draw)


def paint_aurora_edge(painter: QPainter, path: QPainterPath,
                      c1: QColor, c2: QColor, c3: QColor,
                      width: float = 1.4, intensity: float = 0.9):
    """Stroke a path (typically a squircle_path) with the signature Aurora
    tri-tone sweep — indigo → violet → magenta running diagonally — for the
    featured card's lit edge and any 'this is the important surface' accent.
    One gradient-pen stroke; the caller supplies the already-themed QColors."""
    if intensity <= 0.01:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    br = path.boundingRect()
    grad = QLinearGradient(br.topLeft(), br.bottomRight())
    for stop, col in ((0.0, c1), (0.5, c2), (1.0, c3)):
        c = QColor(col)
        c.setAlphaF(intensity)
        grad.setColorAt(stop, c)
    painter.setPen(QPen(QBrush(grad), width))
    painter.drawPath(path)
    painter.restore()


# ============================================================
#  RIPPLE — one-shot expanding click feedback, effect-free
# ============================================================
class RippleController(QObject):
    """Drives a click ripple WITHOUT QGraphicsEffect — the same pattern as
    GlowController: a widget owns one controller, reads `.progress` /
    `.origin` in its own paintEvent via paint_ripple_frame(), and calls
    `.trigger(pos)` on mouse press. One QVariantAnimation, no timers."""

    def __init__(self, widget: QWidget, duration_ms: int = 320):
        super().__init__(widget)
        self._widget = widget
        self._progress = 0.0
        self._origin = QPointF()

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration_ms)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(EASE_OUT)
        self._anim.valueChanged.connect(self._on_frame)

    @property
    def progress(self) -> float:
        return self._progress

    @property
    def origin(self) -> QPointF:
        return self._origin

    def trigger(self, origin: QPointF):
        self._origin = QPointF(origin)
        self._anim.stop()
        self._anim.start()

    def _on_frame(self, value: float):
        self._progress = float(value)
        self._widget.update()


def paint_ripple_frame(painter: QPainter, rect, radius: int, color: QColor,
                       progress: float, origin: QPointF):
    """Paint an expanding, fading accent-tinted ripple from a click point.

    Clipped to the widget's own rounded rect so it never bleeds onto
    neighboring cards; one radial-gradient fill, no offscreen buffer.

    This was the FIRST painter here to clip itself, and for years the only
    one — see clip_to_surface, which generalised it once the hover glow
    turned out to need the same guarantee for the same reason.
    """
    if progress <= 0.0 or progress >= 1.0:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    clip_to_surface(painter, rect, radius)

    max_r = float(rect.width() + rect.height())  # generous — always covers
    r = max(max_r * progress, 1.0)
    grad = QRadialGradient(origin, r)
    c0 = QColor(color)
    c0.setAlphaF(0.16 * (1.0 - progress))
    c1 = QColor(color)
    c1.setAlphaF(0.0)
    grad.setColorAt(0.0, c0)
    grad.setColorAt(1.0, c1)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawEllipse(origin, r, r)
    painter.restore()


# ============================================================
#  SHIMMER BAR — painted progress sweep (zero stylesheet churn)
# ============================================================
class ShimmerBar(QWidget):
    """Thin indeterminate progress bar: a cyan→purple band sweeping across
    a faint track. All painting, no QSS, driven by one looping
    QVariantAnimation on Qt's 60 fps animation driver."""

    def __init__(self, parent: QWidget | None = None, height: int = 6):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._phase = 0.0
        self._c1 = QColor("#4cc2ff")
        self._c2 = QColor("#8a7dff")
        self._track = QColor(255, 255, 255, 14)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(SHIMMER_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_frame)
        self.hide()

    # -- theme ------------------------------------------------
    def set_theme(self, t: dict):
        self._c1 = QColor(t["accent"])
        self._c2 = QColor(t["accent2"])
        self._track = QColor(*t["shimmer_track"])
        self.update()

    # -- control ----------------------------------------------
    def start(self):
        self.show()
        self._anim.start()

    def stop(self):
        self._anim.stop()
        self.hide()

    # -- internals --------------------------------------------
    def _on_frame(self, value: float):
        self._phase = float(value)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect()
        rad = r.height() / 2.0

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._track)
        p.drawRoundedRect(r, rad, rad)

        # band sweeps from fully off-left to fully off-right
        w = r.width()
        band_w = w * 0.45
        cx = -band_w + self._phase * (w + 2 * band_w)
        grad = QLinearGradient(cx, 0, cx + band_w, 0)
        t0 = QColor(self._c1)
        t0.setAlpha(0)
        grad.setColorAt(0.0, t0)
        grad.setColorAt(0.35, self._c1)
        grad.setColorAt(0.75, self._c2)
        t1 = QColor(self._c2)
        t1.setAlpha(0)
        grad.setColorAt(1.0, t1)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(r, rad, rad)


# ============================================================
#  CASCADE — staggered slide-up + fade-in card entrance
# ============================================================
class CascadeAnimator(QObject):
    """Cinematic entrance for a grid of cards.

    Each widget gets pause(i·GAP) → parallel(fade 0→1, rise +26px→0),
    all inside ONE QParallelAnimationGroup so Qt schedules every frame
    together. Opacity effects exist only for the duration of the run and
    are removed in _cleanup — steady-state rendering stays effect-free.
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._group: QParallelAnimationGroup | None = None
        self._staged: list[tuple[QWidget, QGraphicsOpacityEffect, QPoint]] = []
        self._host: QWidget | None = None

    @staticmethod
    def wave_stagger(waves: list[int], stagger_ms: int = CASCADE_GAP,
                     budget_ms: int = CASCADE_BUDGET_MS) -> float:
        """The per-wave delay that fits `waves` inside the stagger budget.

        Returns `stagger_ms` outright while the entrance already fits, so a
        short page keeps the hand-tuned rhythm exactly; a page with more
        waves than the budget allows gets them proportionally tightened
        rather than serialised. See CASCADE_BUDGET_MS.
        """
        span = max(waves) if waves else 0
        if span <= 0:
            return float(stagger_ms)
        return min(float(stagger_ms), budget_ms / float(span))

    def play(self, widgets: list[QWidget],
             waves: list[int] | None = None,
             stagger_ms: int = CASCADE_GAP,
             duration_ms: int = CASCADE_MS,
             rise_px: int = CASCADE_RISE,
             budget_ms: int = CASCADE_BUDGET_MS):
        """Run the entrance over `widgets`.

        `waves` assigns each widget to a stagger group — pass the widget's
        GRID ROW and a row lights as one, which both reads better than a
        left-to-right trickle and shortens the entrance by the column
        count. Defaults to one wave per widget (the pre-v1.1 behaviour).
        """
        self.stop()  # settle any previous run instantly
        if not widgets:
            return
        if waves is None or len(waves) != len(widgets):
            waves = list(range(len(widgets)))
        gap = self.wave_stagger(waves, stagger_ms, budget_ms)

        # This animation drives each card's `pos` DIRECTLY, which means it
        # is briefly fighting the layout that owns those positions. If the
        # window is resized mid-cascade, the layout re-places the cards but
        # the running animation keeps driving them toward the targets it
        # captured BEFORE the resize — cards end up stranded at stale
        # coordinates, overhanging the grid. Watching the host lets the
        # cascade bow out the moment the layout changes underneath it.
        self._host = widgets[0].parentWidget()
        if self._host is not None:
            self._host.installEventFilter(self)

        group = QParallelAnimationGroup(self)
        for i, w in enumerate(widgets):
            target = w.pos()  # layout has already placed it
            effect = QGraphicsOpacityEffect(w)
            effect.setOpacity(0.0)
            w.setGraphicsEffect(effect)
            w.move(target + QPoint(0, rise_px))
            self._staged.append((w, effect, target))

            fade = QPropertyAnimation(effect, b"opacity")
            fade.setDuration(duration_ms)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(EASE_OUT)

            rise = QPropertyAnimation(w, b"pos")
            rise.setDuration(duration_ms)
            rise.setStartValue(target + QPoint(0, rise_px))
            rise.setEndValue(target)
            rise.setEasingCurve(EASE_OUT)

            both = QParallelAnimationGroup()
            both.addAnimation(fade)
            both.addAnimation(rise)

            seq = QSequentialAnimationGroup()
            seq.addPause(int(waves[i] * gap))
            seq.addAnimation(both)
            group.addAnimation(seq)

        group.finished.connect(self._cleanup)
        self._group = group
        group.start()

    def eventFilter(self, obj, event):
        if (obj is self._host and event.type() == QEvent.Type.Resize
                and self._group is not None):
            # the layout just moved everything — abandon the entrance
            self.stop()
        return False

    def stop(self):
        """Cancel a running cascade and settle widgets to their final state."""
        if self._group is not None:
            self._group.stop()
        self._cleanup()

    def _cleanup(self):
        for w, _effect, target in self._staged:
            try:
                w.setGraphicsEffect(None)   # deletes the effect
                w.move(target)
            except RuntimeError:
                pass  # widget was destroyed mid-flight (page closed)
        self._staged.clear()
        if self._host is not None:
            try:
                self._host.removeEventFilter(self)
                # The `target` positions restored above were captured before
                # the cascade started and may now be stale (a resize is
                # exactly why we stop early). The LAYOUT is the authority on
                # where a card belongs, so hand placement back to it rather
                # than leaving the animation's idea of "final" in place.
                layout = self._host.layout()
                if layout is not None:
                    layout.activate()
            except RuntimeError:
                pass
            self._host = None
        if self._group is not None:
            self._group.deleteLater()
            self._group = None


# ============================================================
#  PAGE FADE — transient cross-fade for QStackedWidget pages
# ============================================================
class PageFader(QObject):
    """Fade-in (with an optional subtle rise) for the page a QStackedWidget
    just switched to. The opacity effect lives only for PAGE_FADE_MS, then
    is removed; a transient position offset is always restored."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._anim: QParallelAnimationGroup | None = None
        self._page: QWidget | None = None
        self._target: QPoint | None = None

    def fade_in(self, page: QWidget, duration_ms: int = PAGE_FADE_MS,
                rise_px: int = 0):
        self._finish()  # settle any in-flight fade first

        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)

        group = QParallelAnimationGroup(self)

        fade = QPropertyAnimation(effect, b"opacity")
        fade.setDuration(duration_ms)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(EASE_OUT)
        group.addAnimation(fade)

        self._target = None
        if rise_px:
            # weighted entrance: the page settles upward into place
            self._target = QPoint(page.pos())
            page.move(self._target + QPoint(0, rise_px))
            rise = QPropertyAnimation(page, b"pos")
            rise.setDuration(duration_ms)
            rise.setStartValue(self._target + QPoint(0, rise_px))
            rise.setEndValue(self._target)
            rise.setEasingCurve(EASE_OUT)
            group.addAnimation(rise)

        group.finished.connect(self._finish)
        self._page = page
        self._anim = group
        group.start()

    def _finish(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        if self._page is not None:
            try:
                self._page.setGraphicsEffect(None)
                if self._target is not None:
                    self._page.move(self._target)
            except RuntimeError:
                pass
            self._page = None
        self._target = None
