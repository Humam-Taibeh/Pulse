"""
Ambient background contract — composition, weight, and STILLNESS.

The field is static as of v10.5 (widgets._AmbientSimulation.STATIC): the
aurora orbs and the star scatter are the frame the animated field rendered
at t=0, and nothing advances them. Two halves to the contract, and both are
tested here:

WHAT MUST NOT MOVE. No timer, no drift, no twinkle, no pointer lean, and no
repaint that the window system did not ask for. The animated field's
cheapest configuration was a full-window repaint ten times a second, and a
repaint here is never "repaint the wash" — every surface above this widget
is translucent, so Qt re-rasterises the whole stack (18.5ms measured at
1300x860, of which the card grid alone is 10.9ms).

WHAT MUST NOT CHANGE. Freezing time is not licence to let the picture rot:
the orb peaks, the star weight in both themes, the wash's neutrality
against its canvas and the cost of a single paint are all still solved for
here, because the pixels a still field shows are the pixels it shows
forever.
"""
from __future__ import annotations

import math
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from conftest import settle

pytestmark = pytest.mark.native


def test_layer_is_built_and_reused(window, qapp):
    glow = window._glow
    glow._layer = None
    glow.repaint()
    first = glow._layer
    assert isinstance(first, QPixmap)
    assert glow._layer_size == (glow.width(), glow.height())
    glow.repaint()
    assert glow._layer is first, "layer rebuilt within its cadence window"


def test_the_clock_never_rebuilds_the_layer(window):
    """The inverse of what this asserted before v10.5, and deliberately so.

    The orb layer used to be resampled every _LAYER_MS because the aurora
    was moving. Against a frozen `_t` that cadence would re-rasterise a
    full-window pixmap purely to reproduce the identical image, so
    _ensure_layer now keys staleness on size and theme alone. Advancing the
    clock by any amount must therefore change nothing.
    """
    glow = window._glow
    glow.repaint()
    first = glow._layer
    glow._t += (glow._LAYER_MS / 1000.0) * 50       # a wall-clock eternity
    try:
        glow.repaint()
        assert glow._layer is first, (
            "the orb layer was rebuilt by the passage of time — a static "
            "field is paying an animated field's rasterisation bill for a "
            "pixmap that cannot have changed")
    finally:
        glow._t = 0.0
        glow._layer = None
        glow.repaint()


def test_only_one_layer_is_ever_retained(window):
    """The historical bug: caching keyed on window size minted a fresh
    ~1800px pixmap per resize step (1,323 pixmaps / 11.9 GB on one drag)."""
    glow = window._glow
    for width in range(1100, 1400, 40):
        window.resize(width, 820)
        glow.repaint()
    assert isinstance(glow._layer, QPixmap)
    layers = [v for v in vars(glow).values() if isinstance(v, QPixmap)]
    assert len(layers) == 1, "more than one full-size layer retained"


def test_theme_switch_invalidates_the_layer(window, qapp):
    glow = window._glow
    glow.repaint()
    assert glow._layer is not None
    window._toggle_theme_animated()
    settle(qapp, 900)
    glow.repaint()
    assert glow._layer is not None
    window._toggle_theme_animated()
    settle(qapp, 900)


class TestFreezeDuringSizeMove:
    """WM_ENTERSIZEMOVE parks the animation AND freezes the layer, so a
    resize drag cannot trigger a full-window layer rebuild per step."""

    def test_suspend_freezes_the_layer(self, floating):
        glow = floating._glow
        glow.repaint()
        try:
            glow.suspend()
            assert glow._frozen
            frozen = glow._layer
            floating.resize(1180, 780)
            glow.repaint()
            assert glow._layer is frozen, (
                "layer rebuilt mid-resize — the expensive path we removed")
        finally:
            glow.resume()

    def test_resume_rebuilds_at_the_final_size(self, floating, qapp):
        glow = floating._glow
        glow.suspend()
        floating.resize(1220, 800)
        glow.repaint()
        glow.resume()
        settle(qapp, 120)
        glow.repaint()
        assert not glow._frozen
        assert glow._layer_size == (glow.width(), glow.height())


class TestDensity:
    """The field is meant to read as depth, and depth is carried by the
    THREE TIERS more than by the count: same-sized stars at any density
    are a flat texture. Both halves are pinned here because both are the
    kind of number a later "tidy" quietly halves."""

    def test_the_field_is_dense(self, window):
        particles = window._glow._particles
        assert len(particles) >= 100, (
            f"{len(particles)} stars — the field was thinned back out")

    def test_every_depth_tier_is_populated(self, window):
        glow = window._glow
        dims = {round(p["dim"], 3) for p in glow._particles}
        assert len(dims) == len(glow._PARTICLE_TIERS), (
            f"stars carry {len(dims)} distinct tier alphas for "
            f"{len(glow._PARTICLE_TIERS)} tiers — the parallax is gone")
        # far stars must be both dimmer AND slower than near ones, or the
        # tiers read as random variation rather than as distance
        by_dim = sorted(glow._particles, key=lambda p: p["dim"])
        far = [p for p in by_dim if p["dim"] == by_dim[0]["dim"]]
        near = [p for p in by_dim if p["dim"] == by_dim[-1]["dim"]]
        assert max(p["spd"] for p in far) <= min(p["spd"] for p in near)
        # ...and smaller, in BOTH themes' sprite tables. Light carries its
        # own wider spans (see _STAR_SPAN_MUL); a multiplier that inverted
        # the tier ordering would put the far stars in front.
        for key in ("px_dark", "px_light"):
            assert max(p[key] for p in far) <= min(p[key] for p in near), (
                f"{key} does not increase with depth tier")

    def test_star_textures_are_shared_not_per_star(self, window):
        """The density is affordable because stars are quantised onto a
        handful of native-size textures. One texture per star would be
        both the old resize leak and a per-frame scaling cost."""
        glow = window._glow
        glow.repaint()
        assert glow._star_cache, "no star texture was ever built"
        assert len(glow._star_cache) <= 16, (
            f"{len(glow._star_cache)} star textures cached — sizes are no "
            "longer quantised")


# ============================================================
#  STAR VISIBILITY — solved against the worst covering surface
# ============================================================
#: The translucent surfaces a star is actually seen THROUGH, per theme, as
#: (label, rgb, alpha). Taken from the tokens themselves: `overlay` is the
#: content well, `panel` the sidebar. Nobody ever sees a star against the
#: bare canvas — the wash is the bottom widget in the shell.
#
# The LIGHT entries moved when the ground became a real grey (theme._LIGHT:
# bg_solid #F2F2F7 -> #D6D8E0, overlay rgb 242,242,247 -> 198,200,210). Note
# what did NOT move: both ALPHAS. The well's opacity is what scales star
# contrast — the separation pass that produced these colours was explicitly
# solved with the alphas pinned, because an earlier cut that raised the
# well to 0.94 measured an 88% drop in star deltaE. If a future palette
# edit changes an alpha here, these tests are the ones that should hurt.
_VEILS = {
    "dark":  [("content well", (5, 6, 10), 0.45),
              ("sidebar", (18, 20, 26), 0.55)],
    "light": [("content well", (198, 200, 210), 0.55),
              ("sidebar", (255, 255, 255), 0.60)],
}
_CANVAS = {"dark": (11, 13, 17), "light": (242, 242, 247)}


def _srgb_to_lab(rgb):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b)
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t + 16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _delta_e(a, b):
    return math.sqrt(sum((x - y) ** 2
                         for x, y in zip(_srgb_to_lab(a), _srgb_to_lab(b))))


def _over(src, alpha, dst):
    return tuple(s * alpha + d * (1 - alpha) for s, d in zip(src, dst))


def _mean_star_delta_e(glow, theme: str, tier_index: int, veil) -> float:
    """Area-weighted mean dE of one star of `tier_index`, composited over
    the canvas and then seen through `veil` — the number the eye actually
    integrates for a 4-16px dot."""
    _, vrgb, valpha = veil
    canvas = _CANVAS[theme]
    base = _over(vrgb, valpha, canvas)
    star = (38, 50, 120) if theme == "light" else (200, 214, 255)
    pmax = glow._STAR_PMAX[theme]

    share, (r_lo, r_hi), _spd, dim = glow._PARTICLE_TIERS[tier_index]
    radius = (r_lo + r_hi) / 2.0
    span = max(4, round(radius * glow._STAR_SPAN_MUL[theme]) * 2)

    def sprite_alpha(t):
        # the _star_pixmap gradient: 1.0 @ 0.0, 0.42 @ 0.30, 0.0 @ 1.0
        if t >= 1.0:
            return 0.0
        if t <= 0.30:
            return 1.0 + (0.42 - 1.0) * (t / 0.30)
        return 0.42 * (1.0 - (t - 0.30) / 0.70)

    total = 0.0
    count = 0
    half = span / 2.0
    for yy in range(span):
        for xx in range(span):
            dx, dy = xx + 0.5 - half, yy + 0.5 - half
            alpha = pmax * dim * sprite_alpha(math.hypot(dx, dy) / half)
            lit = _over(vrgb, valpha, _over(star, alpha, canvas))
            total += _delta_e(lit, base)
            count += 1
    return total / count


@pytest.mark.parametrize("tier_index", [0, 1, 2])
def test_light_stars_carry_the_same_weight_as_dark(window, tier_index):
    """A star is never seen against the bare canvas — it is seen through
    the content well (0.55) or the sidebar (0.60), which eat 45-60% of its
    delta before it reaches the eye. Light was tuned against the canvas
    anyway, so it shipped at 60-65% of dark's weight: the far tier, 46% of
    the whole field, measured 0.83 dE through the sidebar, under the ~1.0
    just-noticeable threshold. That is not a subtle effect, it is an
    absent one, and it is why light mode read as having no particles.

    Light is solved TO DARK rather than to a number of its own — the two
    modes have to read as one field in different light, and dark is the
    one that was already right. Measured through each theme's OWN worst
    covering surface, so the comparison is like-for-like.
    """
    glow = window._glow
    dark = min(_mean_star_delta_e(glow, "dark", tier_index, veil)
               for veil in _VEILS["dark"])
    light = min(_mean_star_delta_e(glow, "light", tier_index, veil)
                for veil in _VEILS["light"])
    assert light >= dark * 0.9, (
        f"tier {tier_index}: light stars measure {light:.2f} dE through "
        f"their worst covering surface against dark's {dark:.2f} — light "
        "is back to being solved against the bare canvas")
    assert light <= dark * 1.35, (
        f"tier {tier_index}: light stars measure {light:.2f} dE against "
        f"dark's {dark:.2f} — the field is louder in light than in dark, "
        "which reads as speckle on paper rather than as atmosphere")


def test_every_light_star_clears_the_just_noticeable_threshold(window):
    """The floor, stated directly: a star nobody can see is not ambience.
    ~1.0 dE is the classic JND; the far tier shipped at 0.83."""
    glow = window._glow
    for tier_index in range(len(glow._PARTICLE_TIERS)):
        worst = min(_mean_star_delta_e(glow, "light", tier_index, veil)
                    for veil in _VEILS["light"])
        assert worst >= 1.0, (
            f"light tier {tier_index} measures {worst:.2f} dE through its "
            "worst covering surface — below the just-noticeable threshold")


def test_dark_star_weight_is_untouched(window):
    """Light was the bug; dark was the reference. A change that 'fixes'
    light by also moving dark has re-tuned the mode that was correct."""
    glow = window._glow
    assert glow._STAR_PMAX["dark"] == 0.34
    assert glow._STAR_SPAN_MUL["dark"] == 3.0


#: The most mean channel spread the ambient wash may add to a canvas
#: before it stops shading the base colour and starts replacing it.
#: Calibrated against both ends: the shipping wash measures ~3.9 in light
#: and ~3.2 in dark, and the peaks that shipped the lavender canvas
#: measure ~10.4.
_WASH_TINT_CEILING = 6.0


def _wash_tint(glow, base_hex: str, multiply: bool) -> float:
    """Mean per-pixel channel spread the orb layer adds to `base_hex`,
    composited exactly the way paintEvent does it for that mode.

    The base's OWN spread is subtracted, so this measures what the wash
    contributes and nothing else — and it is read off the token rather
    than written down, which is the bug the first version of this had: it
    subtracted a hardcoded 5 for #F2F2F7 and would have silently gained
    two points of slack the moment the canvas token moved.
    """
    canvas = QPixmap(glow.width(), glow.height())
    canvas.fill(QColor(base_hex))
    painter = QPainter(canvas)
    if multiply:
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_Multiply)
    glow._layer = None
    painter.drawPixmap(0, 0, glow._ensure_layer())
    painter.end()

    base = QColor(base_hex)
    base_spread = (max(base.red(), base.green(), base.blue())
                   - min(base.red(), base.green(), base.blue()))
    img = canvas.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    tint = samples = 0
    for y in range(0, img.height(), 5):
        for x in range(0, img.width(), 5):
            px = img.pixel(x, y)
            r, g, b = (px >> 16) & 255, (px >> 8) & 255, px & 255
            tint += (max(r, g, b) - min(r, g, b)) - base_spread
            samples += 1
    return tint / samples


def test_the_light_wash_tints_the_paper_without_dyeing_it(window, qapp):
    """v11's rule, measured: light mode's canvas is a neutral system grey,
    and the multiply wash may shade it but must not turn it into a colour.
    The regression this catches shipped twice — the wash dragged the page
    to a visible lavender (#ECEAF4), which is a light mode whose defining
    colour is no longer 'system grey'.

    Measured off the orb layer composited exactly as paintEvent does it,
    so adding orbs, raising peaks or changing the blend all land here.
    """
    glow = window._glow
    started_light = window.theme.t["name"] == "light"
    if not started_light:
        window._toggle_theme_animated()
        settle(qapp, 900)
    try:
        assert glow._light
        mean = _wash_tint(glow, window.theme.t["bg_solid"], multiply=True)
        assert mean <= _WASH_TINT_CEILING, (
            f"the light wash adds {mean:.1f} of mean channel spread — the "
            "porcelain is being dyed, not tinted (the v10 regression that "
            "dragged #F2F2F7 to #ECEAF4 measures ~10)")
    finally:
        if not started_light:
            window._toggle_theme_animated()
            settle(qapp, 900)


def test_the_dark_wash_shades_the_obsidian_without_navying_it(window, qapp):
    """THE DARK TWIN, and it is new because dark only just needed one.

    Light had this guard from v11 and dark did not, on the reasoning that
    dark was the mode that was already right. v14 removed that asymmetry:
    the content well used to be 45% NEAR-BLACK, so the frame the wash
    showed through SUBTRACTED from it, and the obsidian palette raises the
    same well to a #121417 container. The identical orb peaks then landed
    on a base ~11 levels lighter across the whole content area and took the
    jet #090A0B canvas to #1A1D25 in the orb cores — a navy-tinted grey,
    which is exactly what the obsidian pass exists to remove, reached from
    the ambient layer instead of from the palette.

    Same ceiling as light, because it is the same requirement: the wash
    shades the canvas, it does not become the canvas.
    """
    glow = window._glow
    started_dark = window.theme.t["name"] == "dark"
    if not started_dark:
        window._toggle_theme_animated()
        settle(qapp, 900)
    try:
        assert not glow._light
        mean = _wash_tint(glow, window.theme.t["bg_solid"], multiply=False)
        assert mean <= _WASH_TINT_CEILING, (
            f"the dark wash adds {mean:.1f} of mean channel spread — the "
            "obsidian is being dyed, not shaded; the v13 peaks on the v14 "
            "raised well measure ~5.6 and read as navy")
    finally:
        if not started_dark:
            window._toggle_theme_animated()
            settle(qapp, 900)


def test_the_wash_is_still_visible_in_both_modes(window, qapp):
    """The corollary, and the reason the ceiling above is not simply set
    to zero: this is a LIVING background, and the cheapest way to pass a
    tint guard is to delete the effect. Every orb peak must stay clear of
    nothing at all."""
    glow = window._glow
    for mode in ("dark", "light"):
        peaks = glow._ORB_PEAKS[mode]
        assert len(peaks) == 5, f"{mode} lost an orb"
        assert min(peaks) > 0.02, (
            f"{mode} orb peaks {peaks} have been tuned down to nothing — "
            "the ambient field is the app's signature, not its overhead")
        assert list(peaks) == sorted(peaks, reverse=True), (
            f"{mode} orb peaks {peaks} no longer descend — the field's "
            "depth tiers come from this ordering")


def test_layer_rebuild_stays_inside_its_cadence(window, qapp):
    """A rebuild is no longer a background tax — it happens on a resize
    step and a theme toggle and at no other time — but it is still work on
    the UI thread at the two moments the user is most likely to notice
    latency: mid-drag, and mid-toggle. The ceiling stays where it was
    (a tenth of the cadence the field used to run at, ~10ms) because that
    is the budget a resize STEP has, not because anything still ticks."""
    glow = window._glow
    samples = []
    for _ in range(12):
        start = time.perf_counter()
        glow._build_layer(glow.width(), glow.height())
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    median = samples[len(samples) // 2]
    assert median < glow._LAYER_MS / 10.0, (
        f"orb layer rebuild median {median:.2f}ms against a "
        f"{glow._LAYER_MS}ms cadence — the ambient field is now a "
        "measurable share of the app's idle CPU")


#: Worst-case (whole-widget) repaint ceiling, per theme. Light is allowed
#: more because its layer is composited with CompositionMode_Multiply,
#: which is measurably dearer per pixel than dark's SourceOver — that is
#: the price of the wash being visible on porcelain at all. Measured on
#: the reference machine at 1360x900: 1.7ms dark, 2.2ms light, against a
#: 36ms frame at 28fps.
_PAINT_CEILING_MS = {"dark": 2.4, "light": 2.9}


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_paint_cost_stays_within_the_frame_budget(window, qapp, theme_name):
    """A full glow repaint must stay well inside one display frame — it
    competes with the OS move/size loop on the same thread, which is what
    made dragging stutter.

    BOTH themes, explicitly. This used to measure whichever theme the
    session happened to be in — always dark, since the toggle test puts it
    back — so the mode with the dearer blend was never measured at all.
    """
    glow = window._glow
    started = window.theme.t["name"]
    if started != theme_name:
        window._toggle_theme_animated()
        settle(qapp, 900)
    try:
        glow.repaint()                  # warm the layer
        samples = []
        for _ in range(30):
            glow._layer_t = glow._t     # keep the cache warm; measure the blit
            start = time.perf_counter()
            glow.render(QPixmap(glow.size()))
            samples.append((time.perf_counter() - start) * 1000)
        samples.sort()
        median = samples[len(samples) // 2]
        assert median < _PAINT_CEILING_MS[theme_name], (
            f"ambient repaint median {median:.2f}ms in {theme_name} — was "
            "~2.7ms before the layer cache; a regression here shows up as "
            "drag/resize stutter")
    finally:
        if window.theme.t["name"] != started:
            window._toggle_theme_animated()
            settle(qapp, 900)


# ============================================================
#  STILLNESS  (v10.5)
# ============================================================
# The field used to be alive: five orbs drifting and breathing on
# independent sine paths, 126 stars rising and twinkling, the whole sheet
# leaning toward the pointer. All of it is gone, and this section is what
# keeps it gone.
#
# The removal is implemented by STOPPING TIME rather than by deleting the
# field (see widgets._AmbientSimulation.STATIC), which is why the weight,
# neutrality and contrast tests above still hold unchanged: what is on
# screen is the exact frame the animated field rendered at t=0. That makes
# the stillness itself the only thing left to assert, and it has to be
# asserted at every layer that could reintroduce motion — the timer that
# would schedule it, the tick that would integrate it, the pointer that
# would bias it, and the repaint that would show it.

def test_the_field_declares_itself_static(window):
    """The one switch. If this is ever flipped back, every assertion below
    is expected to fail — which is the point of a single flag rather than
    a dozen independently-editable call sites."""
    assert window._glow.STATIC is True


def test_no_timer_is_ever_running(window, qapp):
    """The ambient loop is not merely idle, it is never armed.

    _arm() is the single choke point every path re-schedules through
    (showEvent, resume, _tick itself), so a running timer here means some
    path found its way around it.
    """
    glow = window._glow
    settle(qapp, 200)
    assert not glow._timer.isActive(), (
        "the ambient timer is running — the field is repainting the whole "
        "translucent widget stack behind an app that is doing nothing")
    glow._arm()
    glow._arm(10.0)
    assert not glow._timer.isActive(), "_arm() started the frozen timer"


def test_showing_the_field_does_not_start_it(window, qapp):
    """showEvent re-arms on both renderers. It must find _arm() closed."""
    glow = window._glow
    glow.hide()
    settle(qapp, 60)
    glow.show()
    settle(qapp, 120)
    assert not glow._timer.isActive()


def test_a_tick_cannot_advance_the_field(window):
    """Nothing schedules _tick, and _tick refuses anyway.

    "Nothing can move the field" is a stronger guarantee than "nothing
    currently schedules the thing that moves it", and the two renderers
    share this `_t` — a direct call that advanced it would desynchronise
    them from the single frozen frame both are drawing.
    """
    glow = window._glow
    before_t = glow._t
    before = [(p["x"], p["y"]) for p in glow._particles]
    glow._armed_at = time.perf_counter() - 0.5
    glow._tick()
    assert glow._t == before_t, "_tick advanced the clock on a static field"
    after = [(p["x"], p["y"]) for p in glow._particles]
    assert after == before, "a star moved"


def test_deferral_is_a_no_op(window):
    """defer() survives as a live method — its callers are asserting "the
    GUI thread is about to be busy", which stays true — but there are no
    ambient frames left to skip, so it must not arm any state."""
    glow = window._glow
    glow.defer(5000)
    assert glow._defer_until == 0.0


def test_the_pointer_no_longer_leans_the_field(window):
    """The one piece of motion a frozen `_t` would NOT have stopped: the
    lean is integrated from QCursor.pos(), not from the clock, so the orbs
    would have kept sliding under a static simulation. Neutered at the
    gain, so the arithmetic both renderers share stays identical."""
    glow = window._glow
    assert glow._POINTER_GAIN == 0.0
    assert glow._bias_x == 0.0 and glow._bias_y == 0.0


def test_an_idle_window_never_repaints_the_wash(window, qapp):
    """The end-to-end assertion, and the one the whole change is for: an
    app sitting still costs nothing at the bottom of its z-order."""
    glow = window._glow
    settle(qapp, 200)          # let any pending layout-driven paints land
    painted = []
    original = glow.update
    glow.update = lambda *a, **k: painted.append(1)
    try:
        settle(qapp, 700)
        assert not painted, (
            f"{len(painted)} ambient repaint(s) in 700ms of an idle window — "
            "each one re-rasterises every translucent surface above the "
            "wash (18.5ms measured at 1300x860)")
    finally:
        glow.update = original


def test_navigation_leaves_the_constellation_where_it_was(window, qapp):
    """End-to-end the other way: sweep every module and assert the field
    is bit-for-bit where it started. Under the animated field this was the
    opposite test — that the wash kept up with the wall clock across a
    sweep — and inverting it is the clearest statement of what changed."""
    from frontend.menu_structure import CATEGORIES

    window._revealed.clear()
    window.go_home()
    settle(qapp, 400)

    t_before = window._glow._t
    before = [(p["x"], p["y"]) for p in window._glow._particles]
    for _ in range(2):
        for index in range(len(CATEGORIES)):
            window.open_category(index)
            settle(qapp, 120)
    window.go_home()
    settle(qapp, 200)

    assert window._glow._t == t_before, "navigation advanced the field"
    assert [(p["x"], p["y"]) for p in window._glow._particles] == before
