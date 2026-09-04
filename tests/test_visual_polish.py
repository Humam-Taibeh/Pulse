"""
Visual finish contracts — the v1.1 cosmetic polish pass.

Every assertion here replaced something that was found by MEASURING the
running app rather than by looking at it, which is the same standard the
layout and palette suites hold:

  * the card status badges tinted themselves in their own hue, the exact
    "badge-tint trap" the palette's status tokens document, and it cost
    them AA — 4.02:1 in light mode on a state-tinted card, on the smallest
    type in the product;
  * the masthead tagline did not elide, it CLIPPED, losing 40px mid-glyph
    at the app's own 980px minimum window width;
  * ElidedCaption measured its size hint off the text it had already
    elided, so the first squeeze was permanent — a ratchet;
  * four input fields had drifted to three different hover weights and the
    most-used one (Ctrl+K) had no hover state at all;
  * console_qss carried a byte-for-byte copy of the shared scrollbar rules.

None of these raises. All of them are invisible until somebody renders the
exact combination that exposes them.
"""
from __future__ import annotations

import re

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout

from conftest import settle
from frontend import theme as TH
from frontend.widgets import (
    _CHIP_LANE, ElidedCaption, HealthTile, NavButton, StatusDot,
)


# ============================================================
#  COLOUR MATHS (shared with the palette suite's approach)
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


def _over(rgba, base):
    r, g, b, a = rgba
    return tuple(round(f * a + k * (1 - a)) for f, k in zip((r, g, b), base))


def _chip_background(qss: str) -> str:
    match = re.search(r"background:\s*([^;]+);", qss)
    assert match, f"no background in chip QSS: {qss!r}"
    return match.group(1).strip()


#: WCAG AA for normal-size text. These chips are 9px — unambiguously
#: normal text, so the 3:1 large-text allowance does not apply.
_AA = 4.5


# ============================================================
#  1. STATUS BADGES
# ============================================================
@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("verdict", ["applied", "mixed", "due", "default"])
def test_a_status_badge_clears_aa_on_the_worst_card_it_can_land_on(mode, verdict):
    """The badge's plate is OPAQUE, so the worst surface is the plate
    itself — whatever the card underneath is doing. That is the property
    under test as much as the ratio: before this, the same chip measured
    differently on a resting card and a running one."""
    t = TH.tokens(mode)
    qss = TH.state_chip_qss(t, verdict)
    fill = _rgb(_chip_background(qss))
    fg = _rgb(re.search(r"color:\s*([^;]+);", qss).group(1).strip())
    assert _ratio(fg, fill) >= _AA, (
        f"{verdict} badge in {mode} measures {_ratio(fg, fill):.2f}:1 — the "
        "own-hue tint that failed at 4.02:1 is back")


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("verdict", ["applied", "mixed", "due", "default"])
def test_a_status_badge_plate_is_opaque(mode, verdict):
    """A translucent plate lets the card's running / flash tint through, so
    the badge's contrast — and its colour — become a function of what the
    CARD is doing. A status badge must report exactly one thing."""
    t = TH.tokens(mode)
    fill = _chip_background(TH.state_chip_qss(t, verdict))
    _r, _g, _b, a = TH._parse_color(fill)
    assert a >= 1.0, (
        f"{verdict} badge in {mode} fills with {fill!r} (alpha {a}) — the "
        "card's state tint will bleed through it")


def test_every_verdict_shares_one_badge_geometry():
    """Three settings of one control, not three kinds of object. The
    neutral DEFAULT chip used to be the odd one out — transparent where
    the toned pair were filled."""
    t = TH.tokens("dark")
    shapes = set()
    for verdict in ("applied", "mixed", "due", "default"):
        qss = TH.state_chip_qss(t, verdict)
        shapes.add((
            re.search(r"border-radius:\s*([^;]+);", qss).group(1).strip(),
            re.search(r"padding:\s*([^;]+);", qss).group(1).strip(),
            re.search(r"font-size:\s*([^;]+);", qss).group(1).strip(),
            re.search(r"font-weight:\s*([^;]+);", qss).group(1).strip(),
            re.search(r"letter-spacing:\s*([^;]+);", qss).group(1).strip(),
        ))
    assert len(shapes) == 1, f"badges render at {len(shapes)} geometries: {shapes}"


def test_the_tone_whisper_stays_under_the_measured_ceiling():
    """CHIP_TONE_WHISPER is the one number that can walk this back toward
    the failure it fixed, so it is pinned with its reason."""
    assert TH.CHIP_TONE_WHISPER <= 0.10, (
        "the badge is being tinted back toward its own hue; re-measure the "
        "contrast table in state_chip_qss before raising this")


# ============================================================
#  2. SCROLLBARS — ONE DEFINITION
# ============================================================
def test_every_scrolling_surface_composes_the_shared_scrollbar():
    """console_qss carried its own copy of all fourteen rules. A copy is a
    thing that drifts, and this one was invisible because a QPlainTextEdit
    scrolls itself and so never picked up the shared sheet."""
    t = TH.tokens("dark")
    shared = TH.scrollbar_qss(t)
    for name in ("scroll_area_qss", "console_qss", "chip_strip_qss",
                 "palette_list_qss"):
        built = getattr(TH, name)(t)
        assert "QScrollBar::handle:vertical" in built, (
            f"{name} defines no scrollbar at all")
        # the shared sheet must be present verbatim, not paraphrased
        assert shared.strip() in built, (
            f"{name} does not compose scrollbar_qss — it has its own copy")


def test_the_pill_strip_lane_is_derived_from_the_scrollbar():
    """Two literals that agreed only by luck. When they disagreed the
    handle resolved to zero pixels: a strip that scrolls with no visible
    scrollbar.

    The strip derives from chip_strip_lane(), NOT scrollbar_lane(): the
    main bar's lane was widened to give the pointer something to hit, and
    the pill strip deliberately kept its own shorter one."""
    assert _CHIP_LANE == TH.chip_strip_lane()
    assert f"height: {TH.chip_strip_lane()}px" in TH.chip_strip_qss(
        TH.tokens("dark"))


def test_the_pill_strip_stayed_out_of_the_wider_lane():
    """The strip's bar sits under a 30px row of tabs, where the main bar's
    grab lane would read as a slab drawn across the tab bar rather than as
    a scrollbar. Pinned because the obvious "tidy-up" is to collapse the
    two lanes back into one number."""
    assert TH.chip_strip_lane() < TH.scrollbar_lane()


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_scrollbar_acknowledges_a_drag(mode):
    t = TH.tokens(mode)
    qss = TH.scrollbar_qss(t)
    assert "QScrollBar::handle:vertical:pressed" in qss
    assert "QScrollBar::handle:horizontal:pressed" in qss


# ============================================================
#  2b. SCROLLBAR GEOMETRY — RENDERED AND COUNTED, NOT DECLARED
#
#  The bar was reported as "too narrow to easily grab", and measuring it
#  found something worse than the report: `width: 6px` with `margin: 2px`
#  left a TWO-PIXEL groove, so both the painted thumb and — the part that
#  actually matters — the slider's hit rect were 2px wide. Qt derives the
#  drag target from that rect, so the bar was a 2px moving target.
#
#  These render a real QScrollBar and count pixels rather than asserting
#  on the stylesheet text, because the stylesheet is exactly what was
#  wrong: every rule in it was present, spelled correctly, and combined
#  into a control nobody could hit.
# ============================================================
def _render_bar(qss: str, lane: int):
    """(painted thumb px, slider hit-rect px) for a bar wearing `qss`."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QScrollBar, QStyle, QStyleOptionSlider

    bar = QScrollBar(Qt.Orientation.Vertical)
    bar.setStyleSheet(qss)
    # A page step well inside the range puts a real handle mid-groove, so
    # the widest opaque run below crosses its BODY rather than a rounded
    # end cap (which is what made an earlier version of this measurement
    # report 2px for a 6px thumb).
    bar.setRange(0, 100)
    bar.setPageStep(20)
    bar.setValue(40)
    bar.resize(lane, 300)

    image = QImage(bar.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    bar.render(painter, QPoint())
    painter.end()

    # The thumb is the widest run of pixels clearly above the track: the
    # track itself is drawn now, so a bare "alpha > 0" would measure the
    # whole lane.
    thumb = 0
    for y in range(image.height()):
        lit = sum(1 for x in range(image.width())
                  if image.pixelColor(x, y).alpha() > 40)
        thumb = max(thumb, lit)

    option = QStyleOptionSlider()
    bar.initStyleOption(option)
    hit = bar.style().subControlRect(
        QStyle.ComplexControl.CC_ScrollBar, option,
        QStyle.SubControl.SC_ScrollBarSlider, bar)
    return thumb, hit.width()


def _hover_sheet(qss: str) -> str:
    """`qss` with the handle's :hover rules promoted to the resting state.

    Qt only applies :hover to a sub-control the pointer is actually over,
    and an offscreen render has no pointer. Promoting the rule is honest
    because the hover block is declared AFTER the base one at equal
    specificity, so this is the same cascade Qt itself resolves — it just
    reaches the answer without a mouse."""
    return qss.replace("::handle:vertical:hover", "::handle:vertical")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_scrollbar_thumb_is_within_the_fluent_band(mode, qapp):
    """6-8px of painted thumb — Windows 11's own resting/hover pair."""
    thumb, _hit = _render_bar(TH.scrollbar_qss(TH.tokens(mode)),
                              TH.scrollbar_lane())
    assert thumb == TH.SCROLLBAR["thumb"], (
        f"resting thumb rendered {thumb}px, not "
        f"{TH.SCROLLBAR['thumb']}px")
    assert 6 <= thumb <= 8, f"{thumb}px is outside the 6-8px Fluent band"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_thumb_grows_under_the_pointer(mode, qapp):
    """The expand affordance. A thumb that only changes COLOUR on hover
    still leaves the user aiming at the same hairline."""
    t = TH.tokens(mode)
    resting, _ = _render_bar(TH.scrollbar_qss(t), TH.scrollbar_lane())
    hovered, _ = _render_bar(_hover_sheet(TH.scrollbar_qss(t)),
                             TH.scrollbar_lane())
    assert hovered > resting, (
        f"the thumb does not grow on hover ({resting}px -> {hovered}px)")
    assert hovered == TH.SCROLLBAR["thumb_hover"]
    assert 6 <= hovered <= 8, f"{hovered}px is outside the 6-8px Fluent band"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_grab_target_is_far_wider_than_the_thumb(mode, qapp):
    """THE ACTUAL DEFECT. Qt hit-tests a drag against
    subControlRect(SC_ScrollBarSlider); the old sheet left that rect 2px
    wide, so the bar was a two-pixel moving target however it looked.

    The lane is the target and the thumb is only what is drawn inside it,
    which is why the inset is a MARGIN on the handle rather than a smaller
    bar: a margin shrinks the paint and leaves the rect alone."""
    thumb, hit = _render_bar(TH.scrollbar_qss(TH.tokens(mode)),
                             TH.scrollbar_lane())
    assert hit == TH.scrollbar_lane(), (
        f"the slider's hit rect is {hit}px, not the full "
        f"{TH.scrollbar_lane()}px lane — the inset is shrinking the TARGET, "
        "not just the paint")
    assert hit >= 12, f"a {hit}px grab target is still a hard one to hit"
    assert hit > thumb, "the lane gives the pointer nothing over the thumb"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_scrollbar_track_is_visible(mode):
    """A lane you cannot see is a lane you cannot aim into. `transparent`
    was the old value for both bars."""
    t = TH.tokens(mode)
    assert t["scroll_track"] != "transparent"
    assert f"background: {t['scroll_track']}" in TH.scrollbar_qss(t)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_scroll_corner_is_never_platform_grey(mode):
    """The square where two bars meet renders as a stock grey tile unless
    it is explicitly cleared."""
    assert "QAbstractScrollArea::corner" in TH.scrollbar_qss(TH.tokens(mode))


# ============================================================
#  3. INPUT FIELDS — ONE HOVER, ONE FOCUS
# ============================================================
#: (builder, needs an accent argument)
#:
#: v15.1 renamed the palette's entry. `command_input_qss` styled a bare
#: QLineEdit; the field is a bordered FRAME around a chromeless input now,
#: so that it can carry a leading search mark (see palette_field_qss).
_FIELDS = [
    ("sidebar_search_qss", False),
    ("filter_combo_qss", True),
    ("catalog_search_qss", True),
    ("palette_field_qss", False),
]

#: How a field is allowed to say "the keyboard is in me". A pseudo-state
#: for the fields that ARE the focusable widget; a dynamic property for
#: the one that is a container around it, where QSS has no parent
#: selector and a :focus rule would light a border nobody draws.
_FOCUS_MARKS = (":focus", '[focused="true"]')


@pytest.mark.parametrize("name,accented", _FIELDS)
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_every_field_answers_both_the_pointer_and_the_keyboard(name, accented, mode):
    t = TH.tokens(mode)
    build = getattr(TH, name)
    qss = build(t, t["accent"]) if accented else build(t)
    assert ":hover" in qss, (
        f"{name} never acknowledges the pointer — the defect the Ctrl+K "
        "palette shipped with")
    if name != "sidebar_search_qss":     # a button, focus is not its state
        assert any(mark in qss for mark in _FOCUS_MARKS), (
            f"{name} does not mark keyboard focus by any of {_FOCUS_MARKS}")


@pytest.mark.parametrize("name,accented", _FIELDS)
def test_every_field_uses_the_shared_state_weights(name, accented):
    """Hover was 0.45 / 0.35 / 0.45 / absent and focus 0.65 / 0.65 / 0.55
    across these four. Nothing chose those numbers."""
    t = TH.tokens("dark")
    build = getattr(TH, name)
    qss = build(t, t["accent"]) if accented else build(t)
    hover = f"{TH.FIELD['hover']:.3f}"
    assert hover in qss, (
        f"{name} does not use TH.FIELD['hover'] ({TH.FIELD['hover']})")


def test_focus_outranks_hover():
    """The scale has to stay ordered, or focus becomes the quieter state."""
    assert TH.FIELD["focus"] > TH.FIELD["hover"]


# ============================================================
#  4. CARD HOVER ELEVATION
# ============================================================
def test_the_hover_lift_is_quantized():
    """paint_drop_shadow and paint_top_sheen cache rasterised strokes keyed
    on alpha, behind a hard 96-entry bound that clears WHOLESALE. A
    continuous lift would mint a fresh full-size stroke every frame of
    every hover and thrash the cache for the entire app."""
    seen = {TH.hover_lift(i / 500.0) for i in range(501)}
    assert len(seen) <= TH.HOVER_LIFT_STEPS + 1, (
        f"{len(seen)} distinct lift values — the stroke cache will thrash")


def test_the_hover_lift_spans_rest_to_full():
    assert TH.hover_lift(0.0) == 0.0
    assert TH.hover_lift(1.0) == 1.0
    assert TH.hover_lift(0.5) == pytest.approx(0.5)


def test_a_hovered_card_rises_rather_than_flattening():
    """Both cues move in the same direction. A lift that deepened the
    shadow while dulling the sheen would read as the card pressing IN."""
    assert TH.HOVER_LIFT_SHADOW > 1.0
    assert TH.HOVER_LIFT_SHEEN > 0.0


@pytest.mark.native
def test_a_hovered_card_paints_its_accent_perimeter(window, qapp):
    """The hairline is what says 'this whole card'; the cursor-tracking
    glow only lights the edge nearest the pointer."""
    from PySide6.QtGui import QPixmap
    window.open_category(1)
    settle(qapp, 400)
    card = window.pages[1].cards[0]

    def render():
        shot = QPixmap(card.size())
        card.render(shot)
        return shot.toImage()

    card._glow._intensity = 0.0
    rest = render()
    card._glow._intensity = 1.0
    hovered = render()
    card._glow._intensity = 0.0

    # sample the left edge, mid-height: away from the corners, and away
    # from the cursor the glow sweep centres on (0,0 by default)
    y = hovered.height() // 2
    changed = sum(1 for x in range(0, 3)
                  if hovered.pixel(x, y) != rest.pixel(x, y))
    assert changed, (
        "the far edge of a hovered card is unchanged — only the cursor "
        "sweep is painting, so the hairline is gone")


# ============================================================
#  5. THE MASTHEAD TAGLINE
# ============================================================
class TestElidedCaption:

    def test_the_size_hint_is_measured_off_the_full_text(self, qapp):
        """The ratchet: QLabel.sizeHint() reports the CURRENT text, which
        is the elided string, so the hint shrinks to the elision and the
        elision never reverses. Fixed once the caption stopped asking the
        base class."""
        cap = ElidedCaption(max_width=400)
        cap.setFullText("Enterprise-Grade Windows Orchestration")
        wide = cap.sizeHint().width()
        # shown, because Qt only delivers the resize event that drives the
        # elision to a widget that is actually realised
        cap.show()
        cap.resize(80, 20)
        qapp.processEvents()
        try:
            assert cap.text() != cap.fullText(), "test needs an actual elision"
            assert cap.sizeHint().width() == wide, (
                "the size hint collapsed to the elided width — the caption "
                "can never grow back when the room returns")
        finally:
            cap.hide()
            cap.deleteLater()
            qapp.processEvents()

    def test_the_width_ceiling_is_per_instance(self, qapp):
        """The card footer's 120px cap must not follow the class onto the
        masthead, where it would truncate a 255px tagline at every size."""
        text = "Enterprise-Grade Windows Orchestration"
        narrow = ElidedCaption()
        narrow.setFullText(text)
        wide = ElidedCaption(max_width=400)
        wide.setFullText(text)
        assert narrow.sizeHint().width() == ElidedCaption.MAX_WIDTH
        assert wide.sizeHint().width() > ElidedCaption.MAX_WIDTH

    def test_it_never_forces_its_parent_wider(self, qapp):
        cap = ElidedCaption(max_width=400)
        cap.setFullText("Enterprise-Grade Windows Orchestration")
        assert cap.minimumSizeHint().width() == 0

    @pytest.mark.parametrize("text", [
        "Windows Orchestration Toolkit",            # advance 191, needs 192
        "Enterprise-Grade Windows Orchestration",   # advance 255, needs 255
        "Deploy · Tune · Repair · Report",
        "Ran 3d ago · ~2m",
        "A",
        "iiiii",
        "WWWWW",
    ])
    def test_the_hint_wins_a_width_the_text_actually_fits_in(self, qapp, text):
        """sizeHint() measures with horizontalAdvance() but the caption
        ELIDES with elidedText(), and the two disagree by up to a pixel on
        the trailing glyph. A hint of exactly the advance therefore wins a
        width elidedText then judges insufficient — so the caption elides
        at every size and never renders in full.

        Which side of the rounding a string lands on depends on its final
        glyph, so this was a latent trap that any caption-text change could
        spring. It did: 'Windows Orchestration Toolkit' has advance 191 but
        needs 192, and the masthead tagline elided even on a 1500px window.
        """
        cap = ElidedCaption(max_width=4000)
        cap.setFullText(text)
        granted = cap.sizeHint().width()
        painted = cap.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, granted)
        assert painted == text, (
            f"sizeHint() asks for {granted}px but elidedText() still "
            f"truncates {text!r} at that width — the caption can never "
            "render in full")

    def test_a_caption_on_a_PLATE_elides_inside_its_padding(self, window, qapp):
        """The v10.5 regression, and the one failure mode this whole class
        exists to prevent — reintroduced by putting it on a tinted plate.

        Every caller until the Activity drawer's phase chip sat on a
        transparent background, so `width()` and the drawing area were the
        same number and eliding against the former was harmlessly wrong.
        theme.stage_chip_qss reserves 8px each side plus a 1px border: the
        label measured the string against the OUTER width, judged that it
        fit, and Qt then drew it into a rect 18px narrower — so the tail
        was CLIPPED mid-glyph instead of eliding, with no ellipsis to say
        anything had been dropped.
        """
        from frontend import theme as TH
        from frontend.widgets import ElidedCaption

        for mode in ("dark", "light"):
            t = TH.ThemeManager(mode, None).t
            # PARENTED and never shown. A parentless QLabel that is show()n
            # is a real top-level window on the runner's desktop, and one
            # left to be destroyed at interpreter shutdown can take a green
            # session's exit code with it. ensurePolished() is what the
            # measurement actually needs - the font-size lives in the
            # stylesheet, so fontMetrics() reports the default UI font until
            # the style has been applied.
            label = ElidedCaption(max_width=320, parent=window)
            label.setStyleSheet(TH.stage_chip_qss(t))
            label.setFullText(
                "Downloading Mozilla Firefox 145.0 (replacing 144.0.2)...")
            label.ensurePolished()
            label.resize(label.sizeHint())
            qapp.processEvents()
            try:
                room = label.contentsRect().width()
                assert room < label.width(), (
                    "the plate reserves no chrome — this test is measuring "
                    "nothing")
                drawn = label.fontMetrics().horizontalAdvance(label.text())
                assert drawn <= room, (
                    f"{mode}: the caption draws {drawn}px of text into "
                    f"{room}px of room — it is clipping, not eliding")
            finally:
                label.setParent(None)
                label.deleteLater()
        qapp.processEvents()

    def test_a_squeezed_plate_caption_still_shows_an_ellipsis(self, window, qapp):
        """...and when it genuinely does not fit, it says so. A clip is
        indistinguishable from a sentence that happened to end there."""
        from frontend import theme as TH
        from frontend.widgets import ElidedCaption

        t = TH.ThemeManager("dark", None).t
        label = ElidedCaption(max_width=320, parent=window)
        label.setStyleSheet(TH.stage_chip_qss(t))
        label.setFullText(
            "Downloading Microsoft Visual Studio Code 1.108.2 (replacing "
            "1.107.0)...")
        label.ensurePolished()
        label.resize(140, label.sizeHint().height())
        qapp.processEvents()
        try:
            assert "…" in label.text(), (
                f"squeezed to 140px the caption rendered {label.text()!r} "
                "with no ellipsis")
            assert (label.fontMetrics().horizontalAdvance(label.text())
                    <= label.contentsRect().width())
        finally:
            label.setParent(None)
            label.deleteLater()
        qapp.processEvents()

    def test_the_hint_is_not_padded_beyond_what_is_needed(self, qapp):
        """The slack above must stay a rounding allowance, not become a
        margin — a caption that over-asks pushes its neighbours around."""
        cap = ElidedCaption(max_width=4000)
        text = "Windows Orchestration Toolkit"
        cap.setFullText(text)
        advance = cap.fontMetrics().horizontalAdvance(text)
        assert cap.sizeHint().width() <= advance + 1, (
            "the caption is asking for more than a pixel of slack")


@pytest.mark.native
class TestMastheadTagline:

    def test_it_renders_in_full_when_there_is_room(self, window, qapp):
        original = window.size()
        try:
            # The masthead lives on the welcome page, and a page the stack
            # is not showing never receives the resize that re-elides it —
            # the session-shared window fixture may be parked on a module.
            window.go_home()
            window.resize(1400, 900)
            settle(qapp, 250)
            tag = window.welcome._tag
            assert tag.text() == tag.fullText(), (
                "the tagline is truncated on a wide window")
        finally:
            window.resize(original)
            settle(qapp, 150)

    def test_the_shipped_tagline_fits_at_the_apps_minimum_width(
            self, window, qapp):
        """The shipped copy must not need eliding at ANY size the app can
        be at. 'Windows Orchestration Toolkit' is 192px, which the masthead
        can afford even at the 980px minimum.

        This is the guard on the copy itself: lengthen the tagline without
        re-measuring WelcomePage._TAGLINE_W and it starts truncating on
        real windows, which is what the previous, longer tagline did.
        """
        original = window.size()
        try:
            window.go_home()
            window.resize(window.minimumWidth(), 800)
            settle(qapp, 300)
            tag = window.welcome._tag
            assert tag.text() == tag.fullText(), (
                f"the shipped tagline {tag.fullText()!r} truncates at the "
                f"app's own {window.minimumWidth()}px minimum — either "
                "shorten it or re-measure WelcomePage._TAGLINE_W")
        finally:
            window.resize(original)
            settle(qapp, 150)

    # The two tests below drive the masthead with a deliberately overlong
    # string rather than the shipped tagline. They are about the ELISION
    # MACHINERY in the real layout — clip-vs-elide, and the size-hint
    # ratchet — and tying them to the shipped copy meant they silently
    # stopped exercising anything the moment that copy got short enough to
    # always fit (which is exactly what happened when the tagline changed).
    #
    # The per-instance width cap is lifted with it, so the squeeze comes
    # purely from the WINDOW. Left at _TAGLINE_W the cap alone would hold a
    # long string elided at every size, and "it came back" could never be
    # observed — the test would be measuring the cap, not the ratchet.
    _LONG = ("A Deliberately Overlong Masthead Tagline Used Only To Force "
             "The Squeeze In These Tests")

    @staticmethod
    def _drive_long(tag):
        """Swap in the long text + an effectively unlimited cap; returns
        the restore thunk."""
        text, cap = tag.fullText(), tag._max_width
        tag._max_width = 4000
        tag.setFullText(TestMastheadTagline._LONG)

        def restore():
            tag._max_width = cap
            tag.setFullText(text)
        return restore

    def test_it_elides_rather_than_clipping_when_squeezed(self, window, qapp):
        """A plain QLabel squeezed below its text width does not elide — it
        clips mid-glyph with nothing to say anything was lost."""
        original = window.size()
        tag = window.welcome._tag
        restore = self._drive_long(tag)
        try:
            window.go_home()
            window.resize(window.minimumWidth(), 800)
            settle(qapp, 300)
            painted = tag.fontMetrics().horizontalAdvance(tag.text())
            # +1: elidedText() and horizontalAdvance() disagree by up to a
            # pixel on the trailing glyph (the same Qt quirk ElidedCaption.
            # sizeHint() allows for), so elidedText can return a string
            # that measures one pixel over the budget it was handed.
            # Tolerating that costs this guard nothing — the clipping it
            # exists to catch dropped FORTY pixels, not one.
            assert painted <= tag.width() + 1, (
                f"the tagline paints {painted}px into a {tag.width()}px "
                "label — it is being clipped, not elided")
            assert tag.text() != tag.fullText()
            assert tag.text().endswith("…"), (
                "truncated with no ellipsis — nothing tells the user text "
                "was dropped")
        finally:
            restore()
            window.resize(original)
            settle(qapp, 150)

    def test_it_comes_back_when_the_window_grows(self, window, qapp):
        original = window.size()
        tag = window.welcome._tag
        restore = self._drive_long(tag)
        try:
            window.go_home()
            window.resize(window.minimumWidth(), 800)
            settle(qapp, 300)
            assert tag.text() != tag.fullText(), "test needs a real elision"
            window.resize(1400, 900)
            settle(qapp, 300)
            assert tag.text() == tag.fullText(), (
                "the tagline stayed elided after the window grew — the "
                "size-hint ratchet is back")
        finally:
            restore()
            window.resize(original)
            settle(qapp, 150)


# ============================================================
#  6. THE LIVE STATUS INDICATOR
# ============================================================
class TestStatusDot:

    def test_the_idle_breath_is_slower_and_shallower_than_the_busy_one(self):
        """Amplitude and rate move together. A slow breath at the busy
        depth reads as something wrong; a fast one at the idle depth reads
        as a rendering glitch."""
        busy_ms, busy_floor = StatusDot._BUSY
        idle_ms, idle_floor = StatusDot._IDLE
        assert idle_ms > busy_ms
        assert idle_floor > busy_floor

    def test_the_idle_breath_is_subtle_enough_not_to_pull_the_eye(self):
        _idle_ms, idle_floor = StatusDot._IDLE
        assert idle_floor >= 0.6, (
            "an idle indicator dipping this deep reads as a warning "
            "blinking at the user")

    def test_it_keeps_breathing_when_work_finishes(self, qapp):
        """The whole point of the change: 'System Ready' should look alive,
        not printed. stop_pulse() used to freeze the dot solid."""
        from PySide6.QtCore import QVariantAnimation
        dot = StatusDot()
        dot.show()
        qapp.processEvents()
        try:
            dot.start_pulse()
            assert dot._anim.duration() == StatusDot._BUSY[0]
            dot.stop_pulse()
            assert dot._anim.duration() == StatusDot._IDLE[0]
            assert dot._anim.state() == QVariantAnimation.State.Running, (
                "the status dot went static when the task ended")
        finally:
            dot.hide()
            dot.deleteLater()
            qapp.processEvents()

    def test_it_does_not_animate_while_hidden(self, qapp):
        from PySide6.QtCore import QVariantAnimation
        dot = StatusDot()
        dot.show()
        qapp.processEvents()
        dot.hide()
        qapp.processEvents()
        assert dot._anim.state() != QVariantAnimation.State.Running
        dot.deleteLater()
        qapp.processEvents()


# ============================================================
#  7. THE FROSTED MODAL BACKDROP
# ============================================================
@pytest.mark.native
class TestFrostedBackdrop:

    def _catalog(self, window):
        from frontend import menu_structure as MS
        from frontend import widgets as W
        item = {"icon": "\U0001F4E6", "title": "Demo", "desc": "Demo.",
                "task": "SystemInfo"}
        return W.SoftwareCatalogDialog(window, item, window.theme.t,
                                       MS.SOFTWARE_CATALOG)

    def test_a_modal_frosts_what_it_covers(self, window, qapp):
        dialog = self._catalog(window)
        dialog.resize(window.size())
        dialog.show()
        qapp.processEvents()
        try:
            assert dialog._frost is not None, (
                "the modal fell back to a flat scrim — no glass at all")
            assert not dialog._frost.isNull()
        finally:
            dialog.reject()
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_frost_matches_the_geometry_it_is_painted_into(self, window, qapp):
        """THE BACKDROP ARTIFACT REGRESSION.

        Note what this does NOT do: pre-`resize()` the dialog to the host
        before showing it. Every other test in this class does, and that is
        exactly why none of them caught this — pre-sizing makes the
        construction-time geometry equal to the post-refit geometry, so the
        capture happens to be taken for the right rectangle and the race
        disappears. Opened the way the app actually opens one, a PulseDialog
        is still its construction size in showEvent, and refit_dialog
        expands it to the host's whole body only afterwards.

        Capturing before that ran produced a frost sized and offset for the
        wrong rectangle, which paintEvent then stretched across the full
        backdrop — a flat hard-edged block with the real content smeared and
        misregistered around it. It corrected itself when the 120ms refrost
        timer fired, so it was invisible to a late screenshot and glaring
        during the entrance, especially on a slow machine where the broken
        frame simply stays up longer.

        Asserting the frost is registered to the FINAL geometry is what
        pins it: a stale-geometry capture cannot satisfy this.
        """
        dialog = self._catalog(window)
        dialog.show()                      # no pre-resize — the real path
        qapp.processEvents()
        try:
            frost = dialog._frost
            assert frost is not None, "no frost captured at all"
            # Compared in LOGICAL pixels, which is the frame the dialog's
            # own geometry is in. The frost is held at device resolution
            # and tagged with the display ratio (v13.1 — see
            # _capture_backdrop), so dividing it back out is what makes
            # this arithmetic independent of the display scale it runs on.
            # It used to compare against size // _BLUR_DOWNSCALE, which
            # broke the moment the capture stopped being retained small.
            logical_w = frost.width() / frost.devicePixelRatio()
            logical_h = frost.height() / frost.devicePixelRatio()
            assert abs(logical_w - dialog.width()) <= 2, (
                f"frost covers {logical_w:.0f}x{logical_h:.0f} logical px but "
                f"the dialog it paints into is "
                f"{dialog.width()}x{dialog.height()} — the capture was taken "
                "before refit_dialog set the final geometry, so the backdrop "
                "is a stretched, misregistered rectangle")
            assert abs(logical_h - dialog.height()) <= 2
        finally:
            dialog.reject()
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_frost_is_resolved_rather_than_magnified(self, window, qapp):
        """THIS ASSERTION IS THE REVERSE OF THE ONE IT REPLACES, and the
        reversal is the fix rather than a relaxation of it.

        The old test pinned "kept small on purpose", on the reasoning that
        magnifying at paint time costs nothing because the extra pixels
        carry no information. They carry no information and they carry a
        very visible artifact: one bilinear pass across a 10x (12.5x on a
        1.25x display) magnification renders every source texel as a flat
        tile with a hard-ish border, which is the chunky-square backdrop
        this was reported as.

        So the capture is resolved to the size it will be drawn at, once,
        and blitted 1:1 forever after. The old economics were also measured
        and were simply wrong in the other direction: the resolved blit
        costs 3.83 ms against 3.53 ms for the magnifying one, because 1.9M
        pixels of memory traffic beats 12K pixels of scaling. It is 0.3 ms
        per repaint bought deliberately, not a saving.

        What must NOT come back is the magnification, in either direction:
        the frost's logical size has to equal the rect it fills.
        """
        dialog = self._catalog(window)
        dialog.resize(window.size())
        dialog.show()
        qapp.processEvents()
        try:
            frost = dialog._frost
            assert frost is not None
            magnification = dialog.width() / (frost.width()
                                              / frost.devicePixelRatio())
            assert abs(magnification - 1.0) < 0.01, (
                f"the backdrop is magnified {magnification:.2f}x at paint "
                "time — that magnification IS the chunky-tile artifact")
        finally:
            dialog.reject()
            dialog.deleteLater()
            qapp.processEvents()

    def test_a_resize_does_not_recapture_per_step(self, window, qapp):
        """A capture renders the whole host window. A drag emits resize
        events continuously, and paying per step would put the backdrop
        refresh directly in the way of the drag."""
        dialog = self._catalog(window)
        dialog.resize(window.size())
        dialog.show()
        qapp.processEvents()
        try:
            captures = []
            original = dialog._capture_backdrop

            def counted():
                captures.append(1)
                return original()

            dialog._capture_backdrop = counted
            dialog._refrost.timeout.disconnect()
            dialog._refrost.timeout.connect(counted)
            for width in range(900, 1000, 10):
                dialog.resize(width, dialog.height())
                qapp.processEvents()
            assert not captures, "captured mid-drag"
            settle(qapp, 320)
            assert len(captures) == 1, (
                f"{len(captures)} captures for one resize burst")
        finally:
            dialog.reject()
            dialog.deleteLater()
            qapp.processEvents()

    def test_a_parentless_dialog_degrades_to_the_flat_scrim(self, qapp):
        """Failure is silent and total by design — the flat scrim is what
        shipped for every version before this."""
        from frontend.widgets import PulseDialog
        dialog = PulseDialog(None)
        dialog.resize(400, 300)
        dialog._capture_backdrop()
        assert dialog._frost is None
        dialog.deleteLater()
        qapp.processEvents()


# ============================================================
#  8. THE FLAT-SURFACE RULE (v15)
# ============================================================
#: Every QSS factory that paints a real SURFACE — something a user reads
#: text off, rather than a chip, a rule or a control. These are the sheets
#: that carried `glass_fill`.
_SURFACE_FACTORIES = [
    ("card",         lambda t: TH.card_qss(t, t["accent"])),
    ("card/danger",  lambda t: TH.card_qss(t, t["accent"], danger=True)),
    ("dialog panel", lambda t: TH.dialog_panel_qss(t, t["accent"])),
    ("hero banner",  lambda t: TH.hero_banner_qss(t)),
    ("toast",        lambda t: TH.toast_qss(t, t["accent"])),
    ("sidebar",      lambda t: TH.sidebar_qss(t)),
    ("content",      lambda t: TH.content_qss(t)),
]


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("name,factory", _SURFACE_FACTORIES,
                         ids=[n for n, _ in _SURFACE_FACTORIES])
def test_no_surface_paints_a_gradient_across_its_own_face(mode, name, factory):
    """A SURFACE IS ONE FLAT COLOUR (theme.py, the note above `blend`).

    Through v14 every one of these declared its fill as a `glass_fill` — a
    qlineargradient running a white sheen down into the base over the top
    13-20% of the widget. Consistent, and still the single loudest thing on
    a category page: fourteen cards is fourteen luminance ramps on the
    exact surfaces whose job is to be a calm plate for text.

    The elevation those ramps were reaching for is bought twice over at the
    EDGE, where it costs the plate nothing — the 1px hairline, plus the
    painted top sheen and multi-layer cast shadow (test_elevation measures
    both). So a gradient in a surface fill is not a tuning choice any more;
    it is the frosted material coming back.

    The shell is deliberately absent: its gradient IS the canvas, it is
    pinned by test_contract.test_the_canvas_is_the_specified_obsidian_ramp,
    and nothing reads text directly off it.
    """
    qss = factory(TH.ThemeManager(mode, None).t)
    offenders = [line.strip() for line in qss.splitlines()
                 if "gradient" in line and "background" in line]
    assert not offenders, (
        f"{mode}/{name} paints a gradient across its own face: {offenders}")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_elevated_surface_is_the_one_the_spec_names(mode):
    """Two dark neutrals, and the card is the second of them.

    v14 spent the elevated-surface value (#121418) on the CONTAINERS, so
    the sidebar and content frame sat at card brightness and the cards had
    to climb above them — three tones for a language that has two, with the
    card in the wrong place. The stack is pinned here rather than described
    in a comment because the failure mode is a container quietly creeping
    back up to meet the card.
    """
    t = TH.ThemeManager(mode, None).t
    canvas = _rgb(t["bg_solid"])
    container = _over(TH._parse_color(t["overlay"]), canvas)
    card = _over(TH._parse_color(t["card"]), canvas)
    if mode == "dark":
        assert card == (0x12, 0x14, 0x18), (
            f"the dark card is {card}, not the specified #121418")
        assert _lum(card) > _lum(container) > _lum(canvas), (
            f"the dark stack is not canvas -> container -> card "
            f"({canvas} / {container} / {card})")
    else:
        assert card == (255, 255, 255), (
            f"the light card is {card}, not pure white")
        assert _lum(card) > _lum(container), (
            "the light card no longer rises off its container")


# ============================================================
#  9. THE NAV RAIL'S EDGE
# ============================================================
# NATIVE: this renders a real nav row and reads the pixels back off its
# four edges. Qt's offscreen platform composites differently enough that
# the measurement does not hold there — the test failed on any headless
# machine while claiming to be platform-independent, which made a green
# local run mean less than it looked like it did. CI runs with a real
# desktop, so this has always executed there and still does.
@pytest.mark.native
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_nav_rail_carries_no_edge_at_rest(mode, qapp):
    """A BEVEL IS AN EDGE ON A SURFACE, AND A RESTING NAV ROW IS NOT ONE.

    nav_button_qss describes the rail as a ghost: `background-color:
    transparent`, `border: 1px solid transparent`, only the painted plaque
    and the label carrying weight. NavButton.paintEvent then drew a full
    rounded-rect bevel over that transparency on every repaint — and drew
    it at paint_bevel_frame's OWN defaults (0.14 white / 0.20 black), the
    one theme-agnostic painted edge left in the app.

    The two modes therefore rendered the rail as two different components.
    On obsidian both halves of that diagonal gradient disappear into the
    panel, so dark got the ghost rail as designed. On porcelain both land,
    so light mode drew a closed grey rectangle around all four entries —
    outlines on rows that have no fill to outline, and the reason the rail
    reads as a stack of boxes in a light-mode screenshot and as a list of
    labels in a dark one.

    Measured off the PIXELS the row itself puts down. Its QSS fill is
    transparent, so a resting entry should contribute NOTHING outside its
    plaque and its label — every edge sample comes back fully transparent,
    and the panel underneath shows through untouched.
    """
    t = TH.tokens(mode)
    host = QFrame()
    host.setObjectName("sidebar")
    host.setStyleSheet(TH.chrome_qss(t))
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    button = NavButton("package", "Software Management", "software", t)
    button.set_selected(False)
    # AT REST IS FOUR STATES, NOT THREE. Selection and hover were already
    # controlled here; keyboard focus was not. Showing a window hands
    # focus to its first focusable child — the only child, in this fixture
    # — so this row arrived FOCUSED, and once NavButton gained a focus
    # ring (v10.9.5, after the rail measured zero changed pixels on focus)
    # the test read that ring as a bevel at rest: accent #8a9edb at alpha
    # 242 on all four edges.
    #
    # A focused row is SUPPOSED to carry an edge; that ring is the fix,
    # not the defect. Focus is switched OFF here rather than cleared after
    # show, because clearing it does not hold: the activation event that
    # arrives during settle() hands focus straight back, which is why the
    # first attempt at this still failed.
    #
    # The guard is untouched by that. What it was written for is an
    # UNCONDITIONAL bevel, which paints whether or not anything is
    # focusable. The complementary fact — that a focused row DOES carry an
    # edge — is pinned in tests/test_focus_visuals.py.
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    lay.addWidget(button)
    host.resize(360, 46)
    host.show()
    settle(qapp, 60)

    image = button.grab().toImage()
    width, height = image.width(), image.height()
    # a column past the end of the label, where the row is nothing but panel
    clear_x = width - 24
    reference = image.pixelColor(clear_x, height // 2)
    edges = {
        "top":    image.pixelColor(clear_x, 0),
        "bottom": image.pixelColor(clear_x, height - 1),
        "left":   image.pixelColor(0, height // 2),
        "right":  image.pixelColor(width - 1, height // 2),
    }
    host.hide()

    assert reference.alpha() == 0, (
        "the reference sample is not bare panel — the row's label or plaque "
        "has grown into it and the measurement below means nothing")
    drawn = {name: (c.name(), c.alpha())
             for name, c in edges.items() if c.alpha() > 0}
    assert not drawn, (
        f"{mode}: a resting nav entry draws its own edges {drawn} over a "
        f"fill it declares transparent")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_a_nav_entry_is_beveled_once_it_has_a_surface(mode, qapp):
    """The cue is not deleted, it is spent where it means something.

    A SELECTED entry has a real fill (the brand sweep) and a real border,
    so it is an object, and it gets the same edge treatment every other
    elevated surface in the app takes.
    """
    t = TH.tokens(mode)
    button = NavButton("package", "Software Management", "software", t)
    button.resize(218, 46)
    button.set_selected(True)
    lit = button.grab().toImage()
    button._bevel = (0.0, 0.0)
    flat = button.grab().toImage()
    assert lit != flat, (
        f"{mode}: a selected nav entry paints no bevel at all")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_nav_bevel_is_the_modes_own_weight(mode, qapp):
    """...and it comes off the theme, not off the painter's signature.

    theme.bevel_alphas splits the pair per mode because the two canvases
    receive light in opposite directions: obsidian keeps a real top-left
    highlight, porcelain spends its whole (small) budget on the
    bottom-right contact edge and none on a white highlight it has nothing
    to highlight against. The rail was the one widget ignoring that.
    """
    t = TH.tokens(mode)
    button = NavButton("package", "Software Management", "software", t)
    assert button._bevel == TH.bevel_alphas(t), (
        f"{mode}: the nav bevel is {button._bevel}, not the mode's "
        f"{TH.bevel_alphas(t)}")
    assert button._bevel != (0.14, 0.20), (
        f"{mode}: the nav bevel is still paint_bevel_frame's default pair")


# ============================================================
#  10. THE HEALTH ROW'S SEVERITY CHANNEL
# ============================================================
def test_a_health_tile_keeps_its_tone_across_a_theme_switch(qapp):
    """The meter is the tile's ONLY severity channel, and a theme switch
    used to turn it off.

    HealthTile.set_tone exists for tiles whose severity is not a ratio —
    ACTIONS DUE is emerald at zero and amber at anything above it, which
    no threshold on the number itself would say. apply_theme then
    re-derived the tone from the FRACTION unconditionally, so switching
    themes silently discarded the override and the meter fell back to the
    plain interactive accent.

    That is visible in any pair of light/dark screenshots taken either
    side of a toggle: the same three overdue actions read amber in the
    mode the app launched in and indigo in the other one, with nothing
    about the machine having changed. The override is stored as a KEY now
    and re-resolved against whichever palette is current.
    """
    dark, light = TH.tokens("dark"), TH.tokens("light")
    tile = HealthTile("ACTIONS DUE", dark)
    tile.set_value("3", 1.0)
    tile.set_tone("warn")
    assert tile._tone.name() == dark["warn"]

    tile.apply_theme(light)
    assert tile._tone.name() == light["warn"], (
        "a theme switch dropped the tile's tone override back to the "
        "ratio's answer")

    tile.apply_theme(dark)
    assert tile._tone.name() == dark["warn"]


def test_a_fresh_ratio_drops_a_standing_tone_override(qapp):
    """The number and its severity are ONE report.

    A caller that hands the tile a new ratio without a new tone is asking
    for the threshold answer — otherwise the first set_tone in a session
    would pin the meter's colour for the life of the tile, which is the
    opposite failure to the one above and just as silent.
    """
    dark = TH.tokens("dark")
    tile = HealthTile("MEMORY", dark)
    tile.set_tone("err")
    assert tile._tone.name() == dark["err"]
    tile.set_value("11%", 0.11)
    assert tile._tone.name() == TH.health_tone(dark, 0.11), (
        "a stale tone override outlived the value it was reporting on")


# ============================================================
#  11. THE SEARCH DOORWAY'S MARK
# ============================================================
#: The colour magnifier the doorway used to lead with.
_MAGNIFIER = "\U0001f50d"


def test_the_search_doorway_wears_the_line_icon_not_an_emoji(window):
    """ONE ICON LANGUAGE IN THE CHROME.

    Every glyph in the shell is a monochrome Fluent line icon that
    re-tints itself with the theme — the nav plaques, the card plaques,
    the status rail, the card chevrons. The sidebar's search doorway led
    with a literal colour emoji: the only one left in the app's persistent
    chrome, at the very top of the rail, immediately above four of the
    line icons it does not match. It cannot simply BE the button's text
    the way the status rail's glyphs are (one widget, one font — the label
    beside it would render in the icon family too), so it is carried as an
    icon rendered from the same GLYPHS table.
    """
    if not TH.has_icon_font():
        # NOT a module-level skipif: has_icon_font() reaches QFontDatabase,
        # and touching that during collection — before conftest's qapp
        # fixture has built a QApplication — takes the interpreter down with
        # a fail-fast exception and no traceback.
        pytest.skip("no OS icon font — the emoji fallback is correct")
    assert not window._search_btn.icon().isNull(), (
        "the search doorway carries no icon")
    assert _MAGNIFIER not in window._search_btn.text(), (
        "the search doorway still leads with the magnifier emoji")


def test_the_search_mark_is_rendered_for_the_screen_it_lands_on(qapp):
    """A 15px pixmap upscaled to 150% is a soft icon beside crisp text,
    which is a worse defect than the emoji it replaces. theme.glyph_icon
    rasterises at the screen's device pixel ratio."""
    icon = TH.glyph_icon("search", TH.ICON["inline"], "#ffffff")
    if not TH.has_icon_font():
        assert icon is None, "no icon font, but glyph_icon produced an icon"
        return
    assert icon is not None and not icon.isNull()
    dpr = qapp.primaryScreen().devicePixelRatio()
    expected = round(TH.ICON["inline"] * dpr)
    assert icon.availableSizes()[0].width() == expected, (
        f"the search mark is rasterised at "
        f"{icon.availableSizes()[0].width()}px for a {dpr}x screen, not "
        f"{expected}px")


def test_glyph_icon_falls_back_rather_than_rendering_nothing(qapp):
    """An unknown key has no codepoint and no emoji, so there is nothing
    to draw — None, and the caller keeps its own text. A helper that
    returned an empty QIcon here would leave a silent hole in a control."""
    assert TH.glyph_icon("no-such-glyph", 15, "#ffffff") is None
