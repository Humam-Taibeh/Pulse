"""
Perimeter-stroke cache fidelity and bounds.

paint_bevel_frame / paint_top_sheen are static for a given (size, radius,
alpha) but were re-stroked on every repaint. Profiling a full-window render
put the bevel alone at 1.60ms across 14 calls (17% of the frame) — stroking
an antialiased rounded rect with a GRADIENT PEN is a slow path in Qt's
raster engine. They are now rasterised once and blitted.

Caching is only acceptable if it is invisible, so this compares the blitted
result against a live stroke pixel-for-pixel. It also pins the cache bound:
an unbounded size-keyed pixmap cache is what once leaked 11.9GB on a drag.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                           QPen, QPixmap)

from frontend import animations as A


def _blit(width, height, radius, fn, **kw):
    pm = QPixmap(width, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    fn(p, QRect(0, 0, width, height), radius, **kw)
    p.end()
    return pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)


def _reference_bevel(width, height, radius, light_alpha, dark_alpha):
    """The pre-cache implementation, stroked live."""
    pm = QPixmap(width, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(Qt.BrushStyle.NoBrush)
    inner = QRectF(0, 0, width, height).adjusted(0.5, 0.5, -0.5, -0.5)
    grad = QLinearGradient(inner.topLeft(), inner.bottomRight())
    grad.setColorAt(0.0, QColor(255, 255, 255, int(255 * light_alpha)))
    grad.setColorAt(1.0, QColor(0, 0, 0, int(255 * dark_alpha)))
    p.setPen(QPen(QBrush(grad), 1.0))
    p.drawRoundedRect(inner, radius, radius)
    p.end()
    return pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)


def _max_delta(a: QImage, b: QImage) -> int:
    assert (a.width(), a.height()) == (b.width(), b.height())
    worst = 0
    for y in range(0, a.height(), 2):
        for x in range(0, a.width(), 2):
            pa, pb = a.pixel(x, y), b.pixel(x, y)
            for shift in (24, 16, 8, 0):
                worst = max(worst, abs(((pa >> shift) & 0xFF)
                                       - ((pb >> shift) & 0xFF)))
    return worst


@pytest.mark.parametrize("size,radius", [
    ((321, 152), 16), ((216, 46), 13), ((640, 300), 20),
])
def test_cached_bevel_is_pixel_identical(qapp, size, radius):
    width, height = size
    A._STROKE_CACHE.clear()
    cached = _blit(width, height, radius, A.paint_bevel_frame,
                   light_alpha=0.14, dark_alpha=0.20)
    reference = _reference_bevel(width, height, radius, 0.14, 0.20)
    assert _max_delta(cached, reference) == 0, (
        "cached bevel differs from a live stroke — the cache is visible")


def test_cached_bevel_reuses_the_pixmap(qapp):
    A._STROKE_CACHE.clear()
    _blit(321, 152, 16, A.paint_bevel_frame)
    assert len(A._STROKE_CACHE) == 1
    _blit(321, 152, 16, A.paint_bevel_frame)
    assert len(A._STROKE_CACHE) == 1, "identical stroke rasterised twice"


def test_alpha_variants_are_keyed_separately(qapp):
    """A card and a nav entry share a size but not their bevel alphas —
    if the key ignored them, one would wear the other's depth."""
    A._STROKE_CACHE.clear()
    _blit(300, 120, 16, A.paint_bevel_frame, light_alpha=0.14, dark_alpha=0.20)
    _blit(300, 120, 16, A.paint_bevel_frame, light_alpha=0.30, dark_alpha=0.05)
    assert len(A._STROKE_CACHE) == 2

    light = _blit(300, 120, 16, A.paint_bevel_frame,
                  light_alpha=0.14, dark_alpha=0.20)
    heavy = _blit(300, 120, 16, A.paint_bevel_frame,
                  light_alpha=0.30, dark_alpha=0.05)
    assert _max_delta(light, heavy) > 0, "different alphas produced one image"


def test_sheen_strength_is_keyed(qapp):
    A._STROKE_CACHE.clear()
    _blit(300, 120, 16, A.paint_top_sheen, strength=0.55)
    _blit(300, 120, 16, A.paint_top_sheen, strength=1.0)
    assert len(A._STROKE_CACHE) == 2


def test_zero_strength_sheen_paints_nothing(qapp):
    A._STROKE_CACHE.clear()
    _blit(300, 120, 16, A.paint_top_sheen, strength=0.0)
    assert not A._STROKE_CACHE


def test_cache_is_hard_bounded(qapp):
    """Every distinct size mints an entry; a resize drag sweeps hundreds.
    The bound is what stops that becoming a leak."""
    A._STROKE_CACHE.clear()
    for width in range(200, 200 + A._STROKE_CACHE_MAX * 2):
        _blit(width, 60, 12, A.paint_bevel_frame)
    assert len(A._STROKE_CACHE) <= A._STROKE_CACHE_MAX


def test_degenerate_sizes_do_not_raise(qapp):
    A._STROKE_CACHE.clear()
    for rect in (QRect(0, 0, 0, 0), QRect(0, 0, 10, 0), QRect(0, 0, 0, 10)):
        pm = QPixmap(10, 10)
        p = QPainter(pm)
        A.paint_bevel_frame(p, rect, 8)
        A.paint_top_sheen(p, rect, 8)
        p.end()
    assert not A._STROKE_CACHE


# ============================================================
#  DUAL-RAMP CAST SHADOW (v12.2)
# ============================================================
# The single ramp spent its entire falloff inside two pixels — measured, a
# "spread 6" shadow had a reach of ONE. It delivered a contact edge and no
# elevation, which is why cards read as drawn-on rather than raised. These
# pin the two-ramp construction that replaced it, and the three things that
# construction can silently lose.
_SHADOW_W, _SHADOW_H, _SHADOW_R = 320, 150, 14


#: The DARK THEME'S OWN resting alpha, so these measure what ships rather
#: than a literal that quietly stops tracking it. It was 0.26 through
#: v12.2; v13 raised it to 0.34 and dropped the contact ramp's amplitude
#: multiplier in the same change to hold the peak where it was, and that
#: pairing is only under test if this probes the real value.
_SHADOW_ALPHA = 0.34


def _shadow_image(alpha=_SHADOW_ALPHA, spread=6):
    A._STROKE_CACHE.clear()
    return _blit(_SHADOW_W, _SHADOW_H, _SHADOW_R, A.paint_drop_shadow,
                 alpha=alpha, spread=spread)


def _alpha_at(img, x, y):
    return QColor(img.pixelColor(x, y)).alpha()


def _bottom_profile(img, depth=16):
    x = _SHADOW_W // 2
    return [_alpha_at(img, x, _SHADOW_H - 1 - d) for d in range(depth)]


def _top_profile(img, depth=16):
    x = _SHADOW_W // 2
    return [_alpha_at(img, x, d) for d in range(depth)]


def test_the_shadow_reaches_past_the_contact_edge(qapp):
    """THE WHOLE POINT OF THE SECOND RAMP.

    The old construction measured 96, 29, 1, 0, 0... — everything inside
    two pixels. A shadow that stops at the edge IS an edge; elevation is
    the tail. If this regresses to a reach of 1-2px the ambient ramp has
    been lost, whatever the code still looks like.
    """
    profile = _bottom_profile(_shadow_image())
    reach = max((i for i, v in enumerate(profile) if v >= 2), default=0)
    assert reach >= 7, (
        f"cast shadow reaches only {reach}px inward ({profile[:10]}) — the "
        "ambient ramp is gone and this is a contact edge again")


def test_the_shadow_falloff_never_climbs(qapp):
    """A ramp step is a CLOSED rounded rect, so a badly-spaced ramp lays
    visible rings instead of a gradient. Monotonicity is what separates the
    two, and it is invisible in code — only the pixels show it."""
    profile = _bottom_profile(_shadow_image())
    climbs = [(i, profile[i], profile[i + 1])
              for i in range(len(profile) - 1) if profile[i + 1] > profile[i]]
    assert not climbs, (
        f"shadow alpha climbs back up at {climbs} — the ramp is banding "
        "into rings rather than falling off")


def test_the_ambient_ramp_never_touches_the_top_edge(qapp, monkeypatch):
    """Each ramp step's own top edge would otherwise land as a horizontal
    ring inside the card — the defect that made widening the old spread
    impossible. The ambient rect is spanned from -h to +h so only its sides
    and bottom arc fall inside the pixmap.

    Widening the AMBIENT ALONE must therefore change the top profile by
    exactly nothing. (`spread` cannot be used to probe this: it scales the
    contact ramp too, and the contact ramp is what legitimately paints the
    top.)
    """
    baseline = _top_profile(_shadow_image())

    smul, amul, exp, ybot = A._SHADOW_AMBIENT
    monkeypatch.setattr(A, "_SHADOW_AMBIENT", (smul * 3.0, amul, exp, ybot))
    widened = _top_profile(_shadow_image())

    assert widened == baseline, (
        f"tripling the ambient spread changed the top edge: {baseline[:8]} "
        f"-> {widened[:8]} — its top is no longer pinned off-canvas, so a "
        "wider ambient will smear rings across the card")


def test_the_shadow_stays_biased_downward(qapp):
    """Light comes from above. The bottom must carry visibly more weight
    than the top, or the card reads as outlined rather than lit."""
    img = _shadow_image()
    bottom, top = sum(_bottom_profile(img)), sum(_top_profile(img))
    assert bottom > top * 1.4, (
        f"shadow weight is {bottom} bottom vs {top} top — the vertical "
        "bias that makes it read as a cast shadow is gone")


def test_the_peak_edge_alpha_did_not_get_heavier(qapp):
    """The contact edge was never the problem. Everything the second ramp
    adds belongs in the tail — a darker edge just looks grubby."""
    peak = max(_bottom_profile(_shadow_image()))
    assert peak <= 100, (
        f"contact edge peaks at {peak}/255; the pre-v12.2 single ramp "
        "peaked at 96 and this must not exceed it meaningfully")


def test_both_ramps_share_one_cache_entry(qapp):
    """THE PERFORMANCE DOCTRINE. Two ramps must cost one blit, not two:
    they rasterise into the SAME pixmap under one key. A second entry here
    would double both the blit count and the pressure on a cache that
    clears wholesale at 96."""
    A._STROKE_CACHE.clear()
    _blit(_SHADOW_W, _SHADOW_H, _SHADOW_R, A.paint_drop_shadow,
          alpha=_SHADOW_ALPHA, spread=6)
    assert len(A._STROKE_CACHE) == 1, (
        f"one shadow minted {len(A._STROKE_CACHE)} cache entries")
    _blit(_SHADOW_W, _SHADOW_H, _SHADOW_R, A.paint_drop_shadow,
          alpha=_SHADOW_ALPHA, spread=6)
    assert len(A._STROKE_CACHE) == 1, "identical shadow rasterised twice"


def test_hover_lift_alphas_stay_separately_keyed(qapp):
    """GlassCard multiplies the resting alpha by HOVER_LIFT_SHADOW as the
    pointer arrives. Those variants must key apart or a hovered card wears
    a resting card's shadow."""
    A._STROKE_CACHE.clear()
    _blit(300, 120, 14, A.paint_drop_shadow, alpha=_SHADOW_ALPHA, spread=6)
    _blit(300, 120, 14, A.paint_drop_shadow, alpha=_SHADOW_ALPHA * 1.45, spread=6)
    assert len(A._STROKE_CACHE) == 2


def test_a_transparent_shadow_paints_nothing(qapp):
    A._STROKE_CACHE.clear()
    _blit(300, 120, 14, A.paint_drop_shadow, alpha=0.0, spread=6)
    _blit(300, 120, 14, A.paint_drop_shadow, alpha=_SHADOW_ALPHA, spread=0)
    assert not A._STROKE_CACHE


@pytest.mark.parametrize("size", [(0, 0), (10, 0), (0, 10), (4, 4), (2, 40)])
def test_degenerate_shadow_sizes_do_not_raise(qapp, size):
    """The ambient rect spans -h..+h and then insets; on a tiny widget that
    arithmetic can invert. It must break out, not throw."""
    A._STROKE_CACHE.clear()
    pm = QPixmap(40, 40)
    p = QPainter(pm)
    A.paint_drop_shadow(p, QRect(0, 0, *size), 12, _SHADOW_ALPHA, 6)
    p.end()
