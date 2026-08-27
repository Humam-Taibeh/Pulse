"""
The self-updater's status chip — theme.update_pill_qss / widgets.UpdatePill.

Every assertion here was written against a MEASUREMENT, which is the
standard the palette, layout and visual-finish suites already hold. The
component exists because two of those measurements came back bad:

  * the updater's only persistent surface was the sidebar footer, which
    appended "· Update available" to its own identity line at the `caption`
    role — 10px, weight 500, on text_faint, the quietest step in the ramp.
    The app's most actionable notification was rendered in its faintest
    type, and only became emphatic once the pointer arrived;

  * the first draft of the replacement deepened its own tint on hover, and
    measured 4.49:1 in light/warn — UNDER AA, and the exact "badge-tint
    trap" state_chip_qss documents, arrived at from the other direction.

The hover finding is why test_c_* below is the load-bearing test in this
file: it pins the plate ACROSS interaction states, so contrast can never
again become a function of where the pointer is.
"""
from __future__ import annotations

import inspect
import re

import pytest

from frontend import theme as TH
from frontend.widgets import ActivityDrawer, UpdatePill


# ============================================================
#  COLOUR MATHS (shared with the palette / visual-polish suites)
# ============================================================
def _srgb(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(rgb) -> float:
    r, g, b = (_srgb(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(fg, bg) -> float:
    a, b = _lum(fg), _lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _rgb(value: str):
    r, g, b, _a = TH._parse_color(value)
    return (r, g, b)


#: WCAG AA for normal-size text. The pill renders at TYPE['micro'] (9px) —
#: unambiguously normal text, so the 3:1 large-text allowance never applies.
_AA = 4.5

_TONED = ("checking", "current", "available")
_MODES = ("dark", "light")


# ============================================================
#  QSS BLOCK PARSING
# ============================================================
def _block(qss: str, state: str | None, pseudo: str = "") -> str:
    """The declaration body for one selector. `state=None` is the neutral
    resting rule (no [state=...] attribute)."""
    if state is None:
        pattern = r"QPushButton#updatePill\s*\{(.*?)\}"
    else:
        pattern = (r"QPushButton#updatePill\[state=\"" + re.escape(state)
                   + r"\"\]" + re.escape(pseudo) + r"\s*\{(.*?)\}")
    matches = re.findall(pattern, qss, re.S)
    assert matches, f"no rule for state={state!r} pseudo={pseudo!r}"
    # The bare selector also prefixes the [state=...] ones; take the first,
    # which is the neutral rule emitted before any toned block.
    return matches[0]


def _decl(block: str, prop: str) -> str:
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*([^;]+);", block)
    assert match, f"no {prop!r} in {block!r}"
    return match.group(1).strip()


# ============================================================
#  1. CONTRAST — AA AT REST, IN EVERY STATE, IN BOTH THEMES
# ============================================================
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("state", _TONED)
def test_a_every_toned_state_clears_aa_at_rest(mode, state):
    """The whole point of the component. The surface it replaced was
    legible only once hovered; this one has to hold with the pointer
    somewhere else entirely."""
    t = TH.tokens(mode)
    block = _block(TH.update_pill_qss(t), state)
    fg, bg = _rgb(_decl(block, "color")), _rgb(_decl(block, "background"))
    assert _ratio(fg, bg) >= _AA, (
        f"{state} pill in {mode} measures {_ratio(fg, bg):.2f}:1 at rest")


@pytest.mark.parametrize("mode", _MODES)
def test_a_the_neutral_resting_state_clears_aa(mode):
    """The pre-check state carries no tone, so nothing about the toned
    solve protects it. It is text_muted on the flat card tier."""
    t = TH.tokens(mode)
    block = _block(TH.update_pill_qss(t), None)
    fg, bg = _rgb(_decl(block, "color")), _rgb(_decl(block, "background"))
    assert _ratio(fg, bg) >= _AA, (
        f"neutral pill in {mode} measures {_ratio(fg, bg):.2f}:1")


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("state", _TONED)
def test_b_the_plate_is_opaque(mode, state):
    """A translucent plate would let the rail's own panel wash through, so
    the chip's contrast — and its colour — would become a function of what
    is BEHIND it. A status chip must report exactly one thing."""
    t = TH.tokens(mode)
    fill = _decl(_block(TH.update_pill_qss(t), state), "background")
    _r, _g, _b, a = TH._parse_color(fill)
    assert a >= 1.0, f"{state} pill in {mode} fills with {fill!r} (alpha {a})"


# ============================================================
#  2. THE LOAD-BEARING ONE — the plate never moves
# ============================================================
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("state", _TONED)
def test_c_hover_and_press_do_not_touch_the_plate(mode, state):
    """THE REGRESSION GUARD.

    Deepening the tint on hover is the obvious way to build this, and it
    measured 4.49:1 (light/warn) — under AA. Interaction is carried by the
    RING instead, which costs nothing because it is not the surface the
    text sits on. If a future edit reintroduces a hover fill, contrast
    silently becomes a function of pointer position again; this fails
    first, with the reason attached.
    """
    qss = TH.update_pill_qss(TH.tokens(mode))
    rest = _decl(_block(qss, state), "background")
    for pseudo in (":hover", ":pressed"):
        moved = _decl(_block(qss, state, pseudo), "background")
        assert moved == rest, (
            f"{state} pill in {mode} repaints its plate on {pseudo} "
            f"({rest!r} -> {moved!r}) — re-measure before allowing this; "
            "an own-hue tint at 0.13 lands at 4.49:1")


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("state", _TONED)
def test_c_interaction_is_carried_by_the_ring(mode, state):
    """The corollary: if the plate cannot move, the border MUST, or the
    pill has no hover state at all — the defect sidebar_version_qss was
    written to fix, one control over."""
    qss = TH.update_pill_qss(TH.tokens(mode))
    weights = [_decl(_block(qss, state, p), "border")
               for p in ("", ":hover", ":pressed")]
    assert len(set(weights)) == 3, (
        f"{state} pill in {mode} renders {len(set(weights))} distinct ring "
        f"weights across rest/hover/press: {weights}")


def test_c_the_ring_ladder_only_ever_climbs():
    """rest < hover < press, so the pill cannot acknowledge a press more
    faintly than a hover."""
    r = TH.UPDATE_PILL_RING
    assert r["rest"] < r["hover"] < r["press"]
    assert r["rest"] < r["actionable"] < r["hover"], (
        "'available' rests hotter than the quiet states but must not "
        "already be at hover weight, or hovering it says nothing")


# ============================================================
#  3. ONE CONTROL AT FOUR SETTINGS
# ============================================================
def test_d_every_state_shares_one_geometry():
    """Four settings of one control, not four kinds of object — the same
    contract state_chip_qss holds for its verdicts."""
    qss = TH.update_pill_qss(TH.tokens("dark"))
    shapes = set()
    for state in (None, *_TONED):
        block = _block(qss, state)
        shapes.add(tuple(_decl(block, p) for p in (
            "border-radius", "padding", "font-size", "font-weight",
            "letter-spacing")))
    assert len(shapes) == 1, f"pill renders at {len(shapes)} geometries: {shapes}"


def test_d_the_cta_tone_is_the_one_that_measured_safe():
    """Amber, not the brand violet: on this plate accent2 lands at 4.67:1
    in dark — a pass with 0.17 to spare — against warn's 5.35:1."""
    assert TH.UPDATE_PILL_TONES["available"] == "warn"
    t = TH.tokens("dark")
    plate = TH.blend(t["card"], TH.alpha(t["accent2"], TH.CHIP_TONE_WHISPER))
    assert _ratio(_rgb(t["accent2"]), _rgb(plate)) < _ratio(
        _rgb(t["warn"]),
        _rgb(TH.blend(t["card"], TH.alpha(t["warn"], TH.CHIP_TONE_WHISPER)))), (
        "the violet alternative now measures better than amber — re-run the "
        "comparison in update_pill_qss before switching")


# ============================================================
#  4. RENDERING BUDGET — no QSS rebuild on a state flip
# ============================================================
def test_e_a_state_flip_never_rebuilds_qss():
    """States are dynamic-property flips repolished in place, the StatePill
    mechanic. Calling setStyleSheet per transition would re-parse the whole
    sheet on every check — and this one is driven by a background timer at
    launch, which is precisely the pattern the rendering budget forbids."""
    source = inspect.getsource(UpdatePill.set_state)
    assert "setStyleSheet" not in source, (
        "UpdatePill.set_state rebuilds its stylesheet")
    assert "unpolish" in source and "polish" in source, (
        "UpdatePill.set_state must repolish for the [state=...] rule to take")


def test_e_the_sheet_is_built_once_per_theme_apply():
    """apply_theme is the ONLY place the sheet is set."""
    setters = [name for name in ("set_state", "set_busy", "_sync_visibility",
                                 "_lock_width")
               if "setStyleSheet" in inspect.getsource(getattr(UpdatePill, name))]
    assert not setters, f"{setters} set a stylesheet outside apply_theme"


def test_e_no_graphics_effect(qapp):
    """The rail's chips are QSS surfaces. A QGraphicsEffect here would put
    the whole rail on an unbudgeted offscreen-render path."""
    pill = UpdatePill(TH.tokens("dark"))
    assert pill.graphicsEffect() is None


# ============================================================
#  5. LAYOUT — the pill cannot shift anything, including itself
# ============================================================
def test_f_width_is_locked_across_every_state(qapp):
    """Locked to the widest label it can ever show, so the three states
    cannot jitter its own left edge."""
    pill = UpdatePill(TH.tokens("dark"))
    widths = set()
    for state in _TONED:
        pill.set_state(state, "")
        widths.add(pill.width())
    assert len(widths) == 1, f"pill changes width across states: {widths}"


def test_f_the_lock_is_derived_not_hardcoded(qapp):
    """From fontMetrics(), so it survives DPI scaling and font fallback. A
    literal would clip on the first machine whose Segoe UI disagreed."""
    source = inspect.getsource(UpdatePill._lock_width)
    assert "fontMetrics" in source and "horizontalAdvance" in source
    pill = UpdatePill(TH.tokens("dark"))
    fm = pill.fontMetrics()
    widest = max(fm.horizontalAdvance(v) for v in UpdatePill.TEXTS.values())
    assert pill.width() >= widest, (
        f"locked width {pill.width()} clips the widest label ({widest}px)")


def test_f_the_pill_sits_directly_after_the_stretch(qapp):
    """Its no-reflow property depends entirely on this slot: items right of
    a stretch keep their distance from the right edge, so the pill can
    appear and relabel without moving LIVE OUTPUT, the state pill, the
    tools or the chevron. Anywhere else in the rail and it shoves them."""
    drawer = ActivityDrawer(TH.tokens("dark"))
    layout = drawer._rail.layout()
    items = [layout.itemAt(i) for i in range(layout.count())]
    stretch_at = next(i for i, it in enumerate(items) if it.spacerItem())
    after = items[stretch_at + 1].widget()
    assert after is drawer.update_pill, (
        f"the item after the rail's stretch is {type(after).__name__}, not "
        "the UpdatePill — its no-reflow guarantee is gone")


def test_f_showing_the_pill_moves_nothing_to_its_right(qapp, window):
    """The guarantee, measured rather than argued."""
    from conftest import settle
    pill = window.update_pill
    pill.setVisible(False)
    settle(qapp, 40)
    before = {name: getattr(window.activity, name).pos().x()
              for name in ("_console_label", "state_pill", "_toggle")}
    pill.set_state("available", "")
    settle(qapp, 40)
    after = {name: getattr(window.activity, name).pos().x()
             for name in before}
    assert before == after, f"showing the pill moved {before} -> {after}"
    pill.setVisible(False)
    settle(qapp, 40)


# ============================================================
#  6. THE RAIL STILL FITS
# ============================================================
def test_g_the_pill_fits_the_rail_wherever_it_is_visible(qapp, window):
    """The measurement that set the label lengths. At the window's minimum
    width the rail is handed ~608px and its six existing controls need
    ~497, so the chip has ~110px to live in. "↑ UPDATE READY" locked the
    width at 114 and pushed the rail to 623 — over. The terse set locks at
    95 and fits."""
    from conftest import settle
    window.resize(window.minimumWidth(), window.minimumHeight())
    settle(qapp, 80)
    rail = window.activity._rail
    window.update_pill.set_state("available", "")
    settle(qapp, 40)
    assert rail.minimumSizeHint().width() <= rail.width(), (
        f"rail needs {rail.minimumSizeHint().width()}px but has "
        f"{rail.width()}px with the pill shown — shorten UpdatePill.TEXTS")

    window.update_pill.setVisible(False)
    # `window` is session-scoped: hand it back at the size the fixture
    # promises, or every later test inherits a minimum-width shell.
    window.resize(1300, 860)
    settle(qapp, 80)


def test_g_the_pill_costs_a_running_rail_nothing(qapp, window):
    """While a task runs the chip must be free, not merely small.

    NOTE ON WHAT THIS DOES *NOT* ASSERT. The rail is already
    over-subscribed at the minimum width once a task reveals the 112px
    Stop button: measured on a clean tree, before this component existed,
    it needs 621px against the ~608 it is given. That is a PRE-EXISTING
    defect of the rail and fixing it means teaching `status_text` /
    'LIVE OUTPUT' to elide, which is a different change. So the contract
    here is the one this component owes: it must not make that worse by a
    single pixel.
    """
    from conftest import settle
    window.resize(window.minimumWidth(), window.minimumHeight())
    settle(qapp, 80)
    rail = window.activity._rail
    window.update_pill.set_state("available", "")
    window.activity.set_running(True)
    window.stop_btn.show()
    settle(qapp, 60)

    suppressed = rail.minimumSizeHint().width()
    # Probe: force it back in and confirm it WOULD have cost width, so a
    # future edit that quietly drops the suppression cannot pass this by
    # making the pill zero-width instead.
    window.update_pill.setVisible(True)
    settle(qapp, 60)
    intruding = rail.minimumSizeHint().width()
    window.update_pill.setVisible(False)
    settle(qapp, 60)

    assert intruding > suppressed, (
        "the pill costs the rail nothing even when shown — this test can no "
        "longer detect the suppression being removed")
    assert rail.minimumSizeHint().width() == suppressed, (
        "the pill is still charging the rail width while a task runs")

    window.activity.set_running(False)
    window.stop_btn.hide()
    window.update_pill.setVisible(False)
    window.resize(1300, 860)
    settle(qapp, 80)


def test_g_the_pill_stands_down_while_a_task_runs(qapp):
    """And comes back afterwards, in the state it was already reporting —
    a suppressed notification that never returns is a lost one."""
    drawer = ActivityDrawer(TH.tokens("dark"))
    pill = drawer.update_pill
    assert pill.isHidden(), "pill should not occupy the rail before a check"

    pill.set_state("available", "")
    assert not pill.isHidden()

    drawer.set_running(True)
    assert pill.isHidden(), "pill did not stand down for a running task"

    drawer.set_running(False)
    assert not pill.isHidden(), "pill never came back after the task"
    assert pill.property("state") == "available", (
        "pill forgot what it was reporting while suppressed")


def test_g_a_check_during_a_task_does_not_force_the_pill_back(qapp):
    """The silent launch check and a task can overlap. Resolving one must
    not shove the chip into a rail that has no room for it."""
    drawer = ActivityDrawer(TH.tokens("dark"))
    drawer.set_running(True)
    drawer.update_pill.set_state("available", "")
    assert drawer.update_pill.isHidden(), (
        "a check resolving mid-task re-showed the pill")
    drawer.set_running(False)
    assert not drawer.update_pill.isHidden()


# ============================================================
#  7. THE SURFACE IT REPLACED
# ============================================================
@pytest.mark.parametrize("mode", _MODES)
def test_h_the_sidebar_footer_is_off_the_text_floor(mode):
    """It is still a control (the second way into a check), and a control
    must not sit on text_faint — which is where it sat while it was also
    carrying "· Update available"."""
    t = TH.tokens(mode)
    rest = _decl(re.search(r"QPushButton\s*\{(.*?)\}",
                           TH.sidebar_version_qss(t), re.S).group(1), "color")
    assert rest != t["text_faint"], (
        f"the sidebar footer is back on the text floor in {mode}")
    assert rest == t["text_muted"]


def test_h_the_footer_no_longer_reports_update_status():
    """Exactly one surface owns the answer. Two would drift."""
    import frontend.main as main_mod
    source = inspect.getsource(main_mod.PulseApp._on_update_checked)
    assert "_side_footer.setText" not in source, (
        "the footer is reporting update status again — that job belongs to "
        "the UpdatePill, which is legible at rest")
    assert "update_pill.set_state" in source


def test_h_both_entry_points_share_one_handler():
    """The pill and the footer must honour the same in-flight and
    pending-update guards; two copies would let a second check start."""
    import frontend.main as main_mod
    source = inspect.getsource(main_mod.PulseApp._build_ui)
    assert "self.update_pill.clicked.connect(self._on_footer_clicked)" in source
    assert "self._side_footer.clicked.connect(self._on_footer_clicked)" in source
