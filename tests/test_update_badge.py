"""
The self-updater's status chip — theme.update_badge_qss / widgets.UpdateBadge.

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
from frontend.widgets import ActivityDrawer, UpdateBadge


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
        pattern = r"QPushButton#updateBadge\s*\{(.*?)\}"
    else:
        pattern = (r"QPushButton#updateBadge\[state=\"" + re.escape(state)
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
    block = _block(TH.update_badge_qss(t), state)
    fg, bg = _rgb(_decl(block, "color")), _rgb(_decl(block, "background"))
    assert _ratio(fg, bg) >= _AA, (
        f"{state} pill in {mode} measures {_ratio(fg, bg):.2f}:1 at rest")


@pytest.mark.parametrize("mode", _MODES)
def test_a_the_neutral_resting_state_clears_aa(mode):
    """The pre-check state carries no tone, so nothing about the toned
    solve protects it. It is text_muted on the flat card tier."""
    t = TH.tokens(mode)
    block = _block(TH.update_badge_qss(t), None)
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
    fill = _decl(_block(TH.update_badge_qss(t), state), "background")
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
    qss = TH.update_badge_qss(TH.tokens(mode))
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
    qss = TH.update_badge_qss(TH.tokens(mode))
    weights = [_decl(_block(qss, state, p), "border")
               for p in ("", ":hover", ":pressed")]
    assert len(set(weights)) == 3, (
        f"{state} pill in {mode} renders {len(set(weights))} distinct ring "
        f"weights across rest/hover/press: {weights}")


def test_c_the_ring_ladder_only_ever_climbs():
    """rest < hover < press, so the pill cannot acknowledge a press more
    faintly than a hover."""
    r = TH.UPDATE_BADGE_RING
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
    qss = TH.update_badge_qss(TH.tokens("dark"))
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
    assert TH.UPDATE_BADGE_TONES["available"] == "warn"
    t = TH.tokens("dark")
    plate = TH.blend(t["card"], TH.alpha(t["accent2"], TH.CHIP_TONE_WHISPER))
    assert _ratio(_rgb(t["accent2"]), _rgb(plate)) < _ratio(
        _rgb(t["warn"]),
        _rgb(TH.blend(t["card"], TH.alpha(t["warn"], TH.CHIP_TONE_WHISPER)))), (
        "the violet alternative now measures better than amber — re-run the "
        "comparison in update_badge_qss before switching")


# ============================================================
#  4. RENDERING BUDGET — no QSS rebuild on a state flip
# ============================================================
def test_e_a_state_flip_never_rebuilds_qss():
    """States are dynamic-property flips repolished in place, the StatePill
    mechanic. Calling setStyleSheet per transition would re-parse the whole
    sheet on every check — and this one is driven by a background timer at
    launch, which is precisely the pattern the rendering budget forbids."""
    source = inspect.getsource(UpdateBadge.set_state)
    assert "setStyleSheet" not in source, (
        "UpdateBadge.set_state rebuilds its stylesheet")
    assert "unpolish" in source and "polish" in source, (
        "UpdateBadge.set_state must repolish for the [state=...] rule to take")


def test_e_the_sheet_is_built_once_per_theme_apply():
    """apply_theme is the ONLY place the sheet is set."""
    setters = [name for name in ("set_state", "set_busy", "_sync_visibility",
                                 "_lock_width")
               if "setStyleSheet" in inspect.getsource(getattr(UpdateBadge, name))]
    assert not setters, f"{setters} set a stylesheet outside apply_theme"


def test_e_no_graphics_effect(qapp):
    """The rail's chips are QSS surfaces. A QGraphicsEffect here would put
    the whole rail on an unbudgeted offscreen-render path."""
    pill = UpdateBadge(TH.tokens("dark"))
    assert pill.graphicsEffect() is None


# ============================================================
#  5. LAYOUT — the badge cannot shift anything, including itself
# ============================================================
def test_f_width_is_locked_across_every_state(qapp):
    """Locked to the widest label it can ever show, so the three states
    cannot jitter the sidebar's width as the badge relabels itself."""
    badge = UpdateBadge(TH.tokens("dark"))
    widths = set()
    for state in _TONED:
        badge.set_state(state, "")
        widths.add(badge.minimumWidth())
    assert len(widths) == 1, f"badge changes width across states: {widths}"


def test_f_the_lock_is_derived_not_hardcoded(qapp):
    """From fontMetrics(), so it survives DPI scaling and font fallback. A
    literal would clip on the first machine whose Segoe UI disagreed."""
    source = inspect.getsource(UpdateBadge._lock_width)
    assert "fontMetrics" in source and "horizontalAdvance" in source
    badge = UpdateBadge(TH.tokens("dark"))
    fm = badge.fontMetrics()
    widest = max(fm.horizontalAdvance(v) for v in UpdateBadge.TEXTS.values())
    assert badge.minimumWidth() >= widest, (
        f"locked width {badge.minimumWidth()} clips the widest label "
        f"({widest}px)")


def test_f_the_badge_sits_directly_above_the_identity_line(qapp, window):
    """The whole point of the v14 move: the answer and the control the user
    reaches for are ONE place. A badge somewhere else in the shell is a
    second surface to keep in sync, which is the defect it came from."""
    side = window._sidebar.layout()
    widgets = [side.itemAt(i).widget() for i in range(side.count())
               if side.itemAt(i).widget() is not None]
    assert window.update_badge in widgets, (
        "the update badge has left the sidebar")
    assert (widgets.index(window.update_badge) + 1
            == widgets.index(window._side_footer)), (
        "the badge is no longer directly above the identity line it shares "
        "a handler with")


def test_f_the_badge_never_widens_the_sidebar(qapp, window):
    """It appears and disappears at runtime, so it must fit inside the
    width the rail already has — otherwise every update notification
    reflows the whole window."""
    from conftest import settle
    settle(qapp, 40)
    before = window._sidebar.width()
    window.update_badge.set_state("available", "")
    settle(qapp, 60)
    assert window._sidebar.width() == before, (
        f"showing the badge moved the sidebar {before} -> "
        f"{window._sidebar.width()}px")
    assert (window.update_badge.minimumWidth()
            <= window._sidebar.contentsRect().width()), (
        "the badge's locked width does not fit the sidebar it lives in")
    window.update_badge.set_state("current", "")
    settle(qapp, 40)


# ============================================================
#  6. THE ACTIVITY RAIL IT LEFT
# ============================================================
def test_g_the_rail_no_longer_carries_the_update_chip(qapp):
    """The move has to be real. A rail that still holds a reference is a
    rail that will grow one back."""
    drawer = ActivityDrawer(TH.tokens("dark"))
    assert not hasattr(drawer, "update_pill")
    assert not hasattr(drawer, "update_badge")
    assert not drawer._rail.findChildren(UpdateBadge)


def test_g_the_rail_carries_only_status_and_the_way_in(qapp):
    """THE DECLUTTER, PINNED.

    The rail shipped with the status dot, the status text, the update
    chip, a 'LIVE OUTPUT' caption, the state pill, four icon tools, the
    pin chevron and a size grip — nine permanent controls on the strip
    whose entire purpose is being the SMALL thing a collapsed drawer costs.

    What a collapsed drawer can honestly report is the system's state and
    the way in. Everything describing the OUTPUT belongs with the output.
    """
    from frontend.widgets import StatePill
    drawer = ActivityDrawer(TH.tokens("dark"))
    layout = drawer._rail.layout()
    live = [layout.itemAt(i).widget() for i in range(layout.count())
            if layout.itemAt(i).widget() is not None]
    assert live == [drawer.status_dot, drawer.status_text,
                    drawer.stop_btn, drawer._toggle], (
        "the rail is carrying "
        f"{[type(w).__name__ for w in live]} — it is meant to carry the "
        "status dot, its text, the Stop button and the drawer toggle")
    assert not drawer._rail.findChildren(StatePill)


def test_g_the_output_tools_moved_into_the_body(qapp):
    """Not deleted — relocated. A 'clear the output' button beside a
    COLLAPSED drawer acts on something the user cannot see, which is the
    argument for the move; deleting the actions instead would take away
    four things the console is actually good for."""
    drawer = ActivityDrawer(TH.tokens("dark"))
    assert len(drawer._tools) == 4, "the output actions were dropped, not moved"
    for tool in drawer._tools:
        assert drawer._body.isAncestorOf(tool), (
            f"{tool.toolTip()!r} is still living on the always-visible rail")
    for name in ("_console_label", "state_pill"):
        widget = getattr(drawer, name)
        assert drawer._body.isAncestorOf(widget), (
            f"{name} still costs rail height while the drawer is shut")


def test_g_the_rail_fits_at_the_window_minimum(qapp, window):
    """The measurement the old rail could not pass.

    Recorded in the previous revision of this file as a known defect: with
    the update chip suppressed and the Stop button shown, the nine-control
    rail needed 621px against the ~608 it is handed at the window's
    minimum width, so something was being clipped. Four controls fit with
    room to spare, and the status text is now the elastic one, so a long
    task title elides instead of shoving the chevron off the end.
    """
    from conftest import settle
    window.resize(window.minimumWidth(), window.minimumHeight())
    window.activity.set_running(True)
    window.stop_btn.show()
    settle(qapp, 80)
    rail = window.activity._rail
    assert rail.minimumSizeHint().width() <= rail.width(), (
        f"rail needs {rail.minimumSizeHint().width()}px but has "
        f"{rail.width()}px with a task running")
    window.activity.set_running(False)
    window.stop_btn.hide()
    # `window` is session-scoped: hand it back at the size the fixture
    # promises, or every later test inherits a minimum-width shell.
    window.resize(1300, 860)
    settle(qapp, 80)


# ============================================================
#  7. WHEN THE BADGE IS ALLOWED ON SCREEN
# ============================================================
def test_h_only_an_actionable_state_earns_a_permanent_surface(qapp):
    """'Up to date' is a toast, not a chip. A permanent surface reporting
    that nothing is happening is exactly the chrome this pass removes —
    and it is the reason the badge could come back to the sidebar at all
    without re-cluttering it."""
    badge = UpdateBadge(TH.tokens("dark"))
    assert badge.isHidden(), "the badge takes a surface before any check"

    badge.set_state("available", "")
    assert not badge.isHidden(), "an update ready to install is not shown"

    badge.set_state("current", "")
    assert badge.isHidden(), "'up to date' took a permanent surface"


def test_h_a_silent_launch_check_stays_off_screen(qapp):
    """The app talking about itself, unprompted, for the two seconds a
    background probe takes. A check the USER asked for does report."""
    badge = UpdateBadge(TH.tokens("dark"))
    badge.set_state("checking", "", loud=False)
    assert badge.isHidden(), "the silent launch probe showed a chip"

    badge.set_state("checking", "", loud=True)
    assert not badge.isHidden(), (
        "a check the user asked for gives no feedback at all")


def test_h_the_badge_stands_down_while_a_task_runs(qapp):
    """And comes back afterwards, in the state it was already reporting —
    a suppressed notification that never returns is a lost one."""
    badge = UpdateBadge(TH.tokens("dark"))
    badge.set_state("available", "")
    assert not badge.isHidden()

    badge.set_busy(True)
    assert badge.isHidden(), "badge did not stand down for a running task"

    badge.set_busy(False)
    assert not badge.isHidden(), "badge never came back after the task"
    assert badge.property("state") == "available", (
        "badge forgot what it was reporting while suppressed")


def test_h_a_check_during_a_task_does_not_force_the_badge_back(qapp):
    """The silent launch check and a task can overlap. Resolving one must
    not push a control the user cannot act on back on screen —
    _open_update_dialog refuses to install mid-run anyway."""
    badge = UpdateBadge(TH.tokens("dark"))
    badge.set_busy(True)
    badge.set_state("available", "")
    assert badge.isHidden(), "a check resolving mid-task re-showed the badge"
    badge.set_busy(False)
    assert not badge.isHidden()


def test_h_the_busy_flag_is_driven_from_both_run_routes():
    """A playbook owns its own QThread, so "is something running" answered
    False for the longest operation the app can perform (see
    PulseApp._busy). The badge must stand down for BOTH routes or it
    stands down for neither reliably."""
    import frontend.main as main_mod
    single = inspect.getsource(main_mod.PulseApp._start_task)
    playbook = inspect.getsource(main_mod.PulseApp._start_playbook)
    assert "update_badge.set_busy(True)" in single
    assert "update_badge.set_busy(True)" in playbook
    done = (inspect.getsource(main_mod.PulseApp._finish_common)
            + inspect.getsource(main_mod.PulseApp._report_playbook_result))
    assert done.count("update_badge.set_busy(False)") == 2


# ============================================================
#  8. THE SURFACE IT REPLACED
# ============================================================
@pytest.mark.parametrize("mode", _MODES)
def test_i_the_sidebar_footer_is_off_the_text_floor(mode):
    """It is still a control (the second way into a check), and a control
    must not sit on text_faint — which is where it sat while it was also
    carrying "· Update available"."""
    t = TH.tokens(mode)
    rest = _decl(re.search(r"QPushButton\s*\{(.*?)\}",
                           TH.sidebar_version_qss(t), re.S).group(1), "color")
    assert rest != t["text_faint"], (
        f"the sidebar footer is back on the text floor in {mode}")
    assert rest == t["text_muted"]


def test_i_the_footer_no_longer_reports_update_status():
    """Exactly one surface owns the answer. Two would drift."""
    import frontend.main as main_mod
    source = inspect.getsource(main_mod.PulseApp._on_update_checked)
    assert "_side_footer.setText" not in source, (
        "the footer is reporting update status again — that job belongs to "
        "the UpdateBadge, which is legible at rest")
    assert "update_badge.set_state" in source


def test_i_both_entry_points_share_one_handler():
    """The badge and the footer must honour the same in-flight and
    pending-update guards; two copies would let a second check start."""
    import frontend.main as main_mod
    source = inspect.getsource(main_mod.PulseApp._build_ui)
    assert "self.update_badge.clicked.connect(self._on_footer_clicked)" in source
    assert "self._side_footer.clicked.connect(self._on_footer_clicked)" in source
