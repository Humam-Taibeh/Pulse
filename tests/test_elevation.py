"""
Elevation and material contracts — the v13 "masterpiece tier" pass.

v13 changed four things about how every surface in the app is built, and
each one is here because it is the kind of change that LOOKS applied while
being silently reverted by a single number:

  * the radius ramp collapsed from five steps to three (pinned next door,
    in test_layout_contract);
  * the cast shadow's weight went up while its contact edge deliberately
    did NOT (theme.shadow_alphas paired with animations._SHADOW_CONTACT);
  * the lit top edge became theme-driven, because the one hard-coded
    alpha it used to carry was invisible on paper and nearly invisible on
    obsidian;
  * the icon well and the status badge stopped being QSS rectangles and
    became painted materials — with the hard requirement that everything
    added lives at the EDGE and cannot cost the glyph or the 9px label a
    point of contrast.

The last of those is the one worth stating plainly: this suite exists
mostly to prove that a visual upgrade did not quietly spend the app's
accessibility budget to pay for itself.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from frontend import animations as A
from frontend import theme as TH
from frontend.widgets import IconPlaque, StatusChip


@pytest.fixture(autouse=True)
def _qt(qapp):
    """Everything here rasterises a pixmap or polishes a widget, and a
    QPixmap without a live QApplication does not raise — it takes the
    interpreter down with it (exit 127, no traceback, two dots and
    silence). Autouse rather than threaded through thirty signatures."""
    return qapp


# ============================================================
#  COLOUR MATHS (shared with the palette and polish suites)
# ============================================================
def _srgb(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(rgb) -> float:
    r, g, b = (_srgb(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _rgb(value: str):
    r, g, b, _a = TH._parse_color(value)
    return (r, g, b)


def _ratio(fg, bg) -> float:
    a, b = _lum(fg), _lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


#: WCAG AA for normal-size text.
_AA = 4.5


# ============================================================
#  1. THE CAST SHADOW — WEIGHT WENT INTO THE TAIL
# ============================================================
# theme.shadow_alphas and animations._SHADOW_CONTACT are a PAIR: the first
# raised its weight in v13 and the second dropped its amplitude in the same
# change so the extra weight could only land in the ambient tail. Either
# one moving alone silently undoes the other, and the failure is not a
# crash — it is a card with a grubby lower lip and no more elevation than
# it had before.
def _bottom_profile(alpha, depth=16, w=320, h=150):
    A._STROKE_CACHE.clear()
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    A.paint_drop_shadow(p, QRect(0, 0, w, h), TH.RADIUS["card"], alpha, 6)
    p.end()
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    return [QColor(img.pixelColor(w // 2, h - 1 - d)).alpha()
            for d in range(depth)]


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_shadow_is_heavier_than_the_version_it_replaced(mode):
    """The v12.2 weights, pinned as a floor. They are duplicated here
    rather than imported for the usual reason: a test that read the number
    from the code it checks would pass whatever the code said."""
    was = {"dark": 0.26, "light": 0.055}[mode]
    alpha, _spread = TH.shadow_alphas(TH.tokens(mode))
    assert alpha > was, (
        f"{mode} casts at {alpha}, no heavier than the v12.2 {was} the "
        "elevation pass was meant to move past")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_extra_weight_landed_in_the_tail_not_on_the_edge(mode):
    """THE WHOLE POINT OF THE PAIRING.

    Measured on the shipping alpha against the same alpha rendered through
    the v12.2 contact multiplier: the tail has to gain and the peak has to
    hold. A regression here means someone raised shadow_alphas without
    touching _SHADOW_CONTACT, and the app's cards now have a darker edge
    instead of more air underneath them.
    """
    alpha, _spread = TH.shadow_alphas(TH.tokens(mode))
    shipped = _bottom_profile(alpha)

    smul, _amul, exp, ytop, ybot = A._SHADOW_CONTACT
    original = A._SHADOW_CONTACT
    try:
        A._SHADOW_CONTACT = (smul, 1.15, exp, ytop, ybot)   # the v12.2 value
        unbalanced = _bottom_profile(alpha)
    finally:
        A._SHADOW_CONTACT = original

    assert shipped[0] < unbalanced[0], (
        f"{mode} contact edge peaks at {shipped[0]}, no lighter than the "
        f"{unbalanced[0]} an unrebalanced ramp would give — the raise went "
        "onto the edge")
    assert sum(shipped[2:]) >= sum(unbalanced[2:]) * 0.95, (
        f"{mode} lost tail weight ({sum(shipped[2:])} vs "
        f"{sum(unbalanced[2:])}) — the rebalance overshot and took the "
        "elevation with it")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_shadow_still_reaches_past_its_contact_edge(mode):
    """The v12.2 guarantee, re-asserted at the v13 weights: a shadow that
    stops at the edge IS an edge."""
    alpha, _spread = TH.shadow_alphas(TH.tokens(mode))
    profile = _bottom_profile(alpha)
    reach = max((i for i, v in enumerate(profile) if v >= 2), default=0)
    assert reach >= 5, (
        f"{mode} cast shadow reaches only {reach}px inward ({profile[:10]})")


# ============================================================
#  2. THE LIT TOP EDGE
# ============================================================
def _top_edge_colour(mode: str, strength_extra: float = 0.0) -> QColor:
    """What the card's top row of pixels actually becomes once the sheen
    has composited over the QSS hairline. This is the only honest way to
    ask the question — the sheen is a gradient pen over a border, and no
    amount of reading the alphas tells you where it lands."""
    t = TH.tokens(mode)
    peak, depth, rest = TH.sheen_alphas(t)
    card = TH.blend(t["bg_solid"], t["card"])
    line = TH.to_qcolor(TH.blend(card, t["card_line"]))
    w, h = 320, 150
    pm = QPixmap(w, h)
    pm.fill(line)                    # the hairline row, pre-composited
    p = QPainter(pm)
    A._STROKE_CACHE.clear()
    A.paint_top_sheen(p, QRect(0, 0, w, h), TH.RADIUS["card"],
                      strength=min(1.0, rest + strength_extra),
                      peak=peak, depth=depth)
    p.end()
    return QColor(pm.toImage().pixelColor(w // 2, 0))


def _lum_of(colour: QColor) -> float:
    """Relative luminance, 0..1 — the same scale _ratio works in. Stated
    because the obvious mistake here is to compare these numbers as if
    they were 0-255 channel levels, which makes every threshold pass."""
    return _lum((colour.red(), colour.green(), colour.blue()))


def _lift(lit: QColor, base: QColor) -> float:
    """How much brighter the lit edge is than what it replaced, as a
    contrast ratio — a unit that means the same thing on obsidian and on
    paper, which a luminance DIFFERENCE does not."""
    return _ratio((lit.red(), lit.green(), lit.blue()),
                  (base.red(), base.green(), base.blue()))


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_top_edge_reads_as_lit_rather_than_as_a_groove(mode):
    """The defect this replaced, and it was WORSE on light than weak.

    A card's untreated top edge is its hairline. In light mode that
    hairline is #B7BAC4 against a #F2F2F7 well — darker than the page
    behind it, which is the optical signature of something cut INTO the
    page rather than sitting on it. No amount of shadow underneath fixes
    an edge that reads as a groove.

    The requirement in both modes is the same: the top row must end up
    brighter than the untreated hairline by a margin the eye can resolve,
    so the surface reads as catching light from above.

    THE FLOOR IS CAPPED BY THE HEADROOM, which v14's clean-minimal light
    hairline made load-bearing. A flat 1.5 was fair while light's hairline
    was #B7BAC4 on a white card; against the spec's much subtler rgba(0,0,0,
    0.17) the hairline is #D4D4D4, and bleaching it ALL THE WAY to the
    card's own face — the most any sheen can ever do there — is 1.48:1. A
    fixed 1.5 would therefore be asking for a lift that does not exist,
    which is a broken test rather than a strict one. Dark has no such cap:
    its hairline sits on obsidian and the sheen overshoots the face into a
    real highlight (3.58:1), so 1.5 still binds there.
    """
    t = TH.tokens(mode)
    card = TH.blend(t["bg_solid"], t["card"])
    hairline = TH.to_qcolor(TH.blend(card, t["card_line"]))
    lit = _top_edge_colour(mode)
    gain = _lift(lit, hairline)
    ceiling = _lift(TH.to_qcolor(card), hairline)
    floor = min(1.5, ceiling * 0.97)
    assert gain >= floor, (
        f"{mode} top edge measures {gain:.2f}:1 against its own hairline "
        f"({hairline.name()} -> {lit.name()}), under the {floor:.2f}:1 floor "
        f"(ceiling {ceiling:.2f}:1) — that is not an edge lift, "
        "it is a rounding error")


def test_the_light_mode_edge_stops_reading_as_cut_into_the_page():
    """Light's specific job: the top row has to end up level with the
    card's own face, so the boundary becomes a face-to-face luminance step
    from the card (255) to the well (242) instead of a drawn dark line."""
    t = TH.tokens("light")
    card = TH.to_qcolor(TH.blend(t["bg_solid"], t["card"]))
    well = TH.to_qcolor(t["bg_solid"])
    lit = _top_edge_colour("light")
    assert _lum_of(lit) > _lum_of(well), (
        f"the light top edge ({lit.name()}) is still darker than the well "
        f"({well.name()}) — it reads as a groove, which is what v13 set "
        "out to fix")
    assert _lum_of(card) - _lum_of(lit) < 0.08, (
        f"the light top edge ({lit.name()}) has not resolved into the "
        f"card's face ({card.name()}) — a partial bleach is a smudge, "
        "worse than no bleach at all")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_a_hovered_card_catches_more_light_than_a_resting_one(mode):
    """Both elevation cues move the same way — the shadow deepens and the
    top edge brightens. A lift that did one without the other would read
    as the card pressing IN."""
    rest = _lum_of(_top_edge_colour(mode))
    hovered = _lum_of(_top_edge_colour(mode, TH.HOVER_LIFT_SHEEN))
    assert hovered > rest, (
        f"{mode} top edge is {hovered:.1f} hovered against {rest:.1f} at "
        "rest — hovering the card dims its lit edge")


def test_the_resting_strength_is_a_theme_value_not_a_shared_constant():
    """The two modes are not spending the same budget on the same thing:
    light erases its hairline in one go, dark spends its rim gradually.
    A single shared resting strength is what made light's bleach land
    halfway and read as a smear."""
    _p_light, _d_light, rest_light = TH.sheen_alphas(TH.tokens("light"))
    _p_dark, _d_dark, rest_dark = TH.sheen_alphas(TH.tokens("dark"))
    assert rest_light != rest_dark
    assert 0.0 < rest_dark <= 1.0 and 0.0 < rest_light <= 1.0


# ============================================================
#  3. ICON PLAQUES — REFINED WITHOUT SPENDING CONTRAST
# ============================================================
def test_the_icon_well_is_one_neutral_surface_everywhere():
    """v10.6 REPLACED THE PLAQUE MATERIAL WITH A SURFACE.

    This test used to pin the halo's arithmetic: the well was washed in its
    module's accent, an ambient halo was painted OUTWARD into reserved
    padding, and the whole in-plaque contrast solve depended on that halo
    never bleeding inward and changing the surface under the glyph.

    There is no halo now, and no accent wash. Six accents across fourteen
    cards was six competing hues on one screen, each already stated by the
    glyph sitting in the well — so the well became a single low-alpha
    NEUTRAL and the colour stayed on the glyph, where it is not repeated.

    What is worth pinning is what replaced it: one token, used by both
    painters, at a weight low enough to stay a surface rather than become
    a chip. If these drift apart the sidebar and the card grid stop being
    the same object at two scales, which is the whole reason PLAQUE_SIZE
    exists.
    """
    from frontend.widgets import IconPlaque, NavButton

    for mode in ("dark", "light"):
        t = TH.tokens(mode)
        well = TH.to_qcolor(t["plaque_well"])
        assert 0.02 <= well.alphaF() <= 0.08, (
            f"{mode} icon well is at {well.alphaF():.3f} — outside the "
            "weight at which it reads as a surface rather than a chip")
    # Dark lightens, light darkens: white on porcelain is invisible.
    assert TH.to_qcolor(TH.tokens("dark")["plaque_well"]).red() == 255
    assert TH.to_qcolor(TH.tokens("light")["plaque_well"]).red() == 0
    # No padding is reserved any more — the widget IS the well.
    assert IconPlaque._PAD == 0
    assert NavButton._PLAQUE == TH.PLAQUE_SIZE


#: `plaque_well` is already an rgba() string, so TH.alpha (which takes a
#: hex colour) cannot restate it at a new opacity — the channels have to be
#: parsed and re-emitted. Lifting the well is the only thing that needs it.
def _at_alpha(rgba: str, a: float) -> str:
    r, g, b, _a = TH._parse_color(rgba)
    return f"rgba({r}, {g}, {b}, {a})"


#: Every surface a module glyph's well can be painted on, as
#: (name, how to composite it) — the real ones, taken from the two
#: painters rather than from the retired tint table.
#:
#: THE RAIL IS THE HALF THAT USED TO BE MISSING. The old sweep measured
#: the card and only the card, which was already incomplete when it was
#: written: NavButton paints the same well on the sidebar's PANEL, a
#: different tier, and lifts it again when the entry is selected. So the
#: two surfaces the sidebar can put a glyph on were never measured, and
#: the one that was measured stopped existing in v10.6.
def _well_surfaces(t: dict) -> list[tuple[str, str]]:
    from frontend.widgets import NavButton

    # The canvas is a two-stop ramp and the sidebar spans it, so the panel
    # is composited over BOTH ends and the darker/lighter result is kept
    # as its own surface — a glyph has to clear the floor at the top of
    # the rail and at the bottom of it.
    well = TH.to_qcolor(t["plaque_well"])
    lifted = _at_alpha(t["plaque_well"],
                       min(1.0, well.alphaF() * NavButton._SELECTED_LIFT))
    card = TH.blend(t["bg_solid"], t["card"])
    surfaces = [("card", TH.blend(card, t["plaque_well"]))]
    for edge in ("bg_grad_top", "bg_grad_bottom"):
        panel = TH.blend(t[edge], t["panel"])
        surfaces.append((f"rail@{edge}", TH.blend(panel, t["plaque_well"])))
        surfaces.append((f"rail@{edge}/selected", TH.blend(panel, lifted)))
    return surfaces


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_every_module_glyph_clears_its_floor_on_the_well_that_ships(mode):
    """The floor for a graphic object is 3:1, measured against the well
    the app ACTUALLY PAINTS.

    This test used to compute the well from theme.plaque_tints — a
    per-mode accent wash at 0.24/0.13 dark and 0.15/0.08 light. That
    construction was deleted in v10.6 along with the halo and the two
    hairlines around it, so for several versions the guard was measuring a
    surface that no longer existed anywhere in the product: a solve for a
    coloured well, run against a grid of glyphs that had been sitting on a
    NEUTRAL one since the module palette collapsed. It passed the whole
    time, and would have kept passing if `plaque_well` had been taken to
    an alpha that swallowed the glyph whole — which is the only failure it
    was ever there to catch.

    It now composites `plaque_well` exactly as IconPlaque and NavButton do,
    on every tier either of them can land it on. That is a strictly wider
    sweep than the old one (five surfaces against one) as well as a real
    one.
    """
    t = TH.tokens(mode)
    failures = []
    for glyph, value in t["module"].items():
        for surface, well in _well_surfaces(t):
            ratio = _ratio(_rgb(value), _rgb(well))
            if ratio < 3.0:
                failures.append(f"{glyph} on {surface} {ratio:.2f}:1")
    assert not failures, f"{mode} glyphs under the 3:1 floor: {failures}"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_lifting_the_rail_well_never_costs_the_glyph_its_floor(mode):
    """SELECTION LIFTS THE WELL RATHER THAN COLOURING IT, and the lift is
    the one number describing this element that lives outside theme.py.

    NavButton multiplies the neutral's alpha by _SELECTED_LIFT so "which
    module is live" stays a question of VALUE — legible at a glance and in
    both themes — instead of a question of hue against the glyph sitting
    in it. That trade only holds while the lifted well stays a SURFACE:
    push the multiplier far enough and the well becomes a chip, closing on
    the glyph it is supposed to be a backdrop for.

    Two things are pinned. The lifted well must still read as a surface
    (the same 0.02-0.08 band the resting well is held to above, with the
    lift applied), and it must move enough to be seen at all — a
    "selected" state nobody can perceive is not a state.
    """
    from frontend.widgets import NavButton

    t = TH.tokens(mode)
    resting = TH.to_qcolor(t["plaque_well"]).alphaF()
    lifted = min(1.0, resting * NavButton._SELECTED_LIFT)
    assert lifted > resting * 1.5, (
        f"{mode}: selection lifts the well from {resting:.3f} to "
        f"{lifted:.3f} — not enough to read as a state")
    assert lifted <= 0.16, (
        f"{mode}: the selected well is at {lifted:.3f}, which is a chip "
        f"behind the glyph rather than a surface under it")
    # and the glyph still clears the graphic-object floor on it
    for edge in ("bg_grad_top", "bg_grad_bottom"):
        panel = TH.blend(t[edge], t["panel"])
        well = TH.blend(panel, _at_alpha(t["plaque_well"], lifted))
        for glyph, value in t["module"].items():
            ratio = _ratio(_rgb(value), _rgb(well))
            assert ratio >= 3.0, (
                f"{mode}: {glyph} falls to {ratio:.2f}:1 on a selected "
                f"rail well at {edge}")


def test_the_plaque_glyph_colour_is_all_that_is_left_in_qss():
    """A QLabel that also declares a background or a border would paint a
    second, unstyled box on top of everything the painter just did — the
    exact failure that makes a painted QLabel look like a bug."""
    t = TH.tokens("dark")
    qss = TH.icon_plaque_qss(t, t["module"]["software"])
    assert "background: transparent" in qss
    assert "border: none" in qss
    assert "qlineargradient" not in qss, (
        "the well is painted now (widgets.IconPlaque); a QSS gradient here "
        "would double-draw it")


# ============================================================
#  4. STATUS CHIPS — ONE GEOMETRY, AND A RIM THAT COSTS NOTHING
# ============================================================
_CHIP_GEOMETRY = ("border-radius", "padding", "font-size", "font-weight",
                  "letter-spacing")


def _decls(qss: str) -> dict:
    import re
    out = {}
    for prop in _CHIP_GEOMETRY:
        match = re.search(rf"{prop}:\s*([^;]+);", qss)
        assert match, f"{prop} missing from {qss!r}"
        out[prop] = match.group(1).strip()
    return out


def test_the_card_badge_and_the_update_badge_are_one_object():
    """update_badge_qss has claimed to share state_chip_qss's geometry "to
    the pixel" since it shipped, and it did not: the chip ran 2px of
    vertical padding against the badge's 3px. A comment is not a
    constraint. Both now compose theme._CHIP_TYPE, and this is what says
    so."""
    t = TH.tokens("dark")
    chip = _decls(TH.state_chip_qss(t, "applied"))
    badge = _decls(TH.update_badge_qss(t))
    assert chip == badge, (
        f"the card badge and the update badge render differently: {chip} vs "
        f"{badge}")


def test_the_chip_corner_stays_in_pill_territory():
    """Not a MATHEMATICAL pill, and theme.CHIP_PAD_V says why: that needs
    radius >= height/2, which at 20px is a 10 that exists on no tier of the
    ramp. Inventing a corner for the smallest object in the app is the
    fragmentation the three-tier collapse was for.

    What must hold is that the corner keeps turning through most of the
    chip's half-height. Below about 70% the tag stops reading as a pill and
    starts reading as a box with the edges knocked off — and the way that
    regresses is silently, by someone adding vertical padding without
    looking at the corner."""
    from PySide6.QtWidgets import QLabel
    t = TH.tokens("dark")
    label = QLabel("APPLIED")
    label.setStyleSheet(TH.state_chip_qss(t, "applied"))
    label.ensurePolished()
    height = label.sizeHint().height()
    turn = TH.RADIUS["chip"] / (height / 2.0)
    assert turn >= 0.70, (
        f"a {height}px chip at radius {TH.RADIUS['chip']} turns through "
        f"only {turn:.0%} of its half-height — that is a box, not a pill")
    assert TH.RADIUS["chip"] == min(TH.RADIUS.values()), (
        "a chip must sit on the SMALL tier of the ramp")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_chip_rim_fades_out_before_the_text_begins(mode):
    """THE PROPERTY THAT LET THE RIM SHIP, and it is the same one as the
    plaque halo's.

    Every luminance gradient ACROSS the plate was tried first and every one
    cost AA — a 0.04 white lift alone drops the dark DEFAULT verdict from
    4.59:1 to 4.07:1, because the plate is the surface the 9px text is
    solved against. The rim survives only by living entirely in the border
    and the pixel beside it.
    """
    _peak, depth = TH.chip_sheen(TH.tokens(mode))
    text_starts = TH.CHIP_PAD_V + 1          # padding, plus the 1px border
    assert depth < text_starts, (
        f"{mode} chip rim fades over {depth}px but the label starts at "
        f"{text_starts}px — the rim is now under the text and the contrast "
        "table in state_chip_qss no longer describes what ships")


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("verdict", ["applied", "mixed", "due", "default"])
def test_the_badge_plate_is_untouched_by_the_restyle(mode, verdict):
    """The v13 chip is a restyle of everything EXCEPT the plate. If the
    plate moved, the AA table moved with it."""
    t = TH.tokens(mode)
    import re
    qss = TH.state_chip_qss(t, verdict)
    fill = re.search(r"background:\s*([^;]+);", qss).group(1).strip()
    fg = re.search(r"color:\s*([^;]+);", qss).group(1).strip()
    assert _ratio(_rgb(fg), _rgb(fill)) >= _AA
    assert TH._parse_color(fill)[3] >= 1.0, (
        "the plate went translucent — the card's running/flash tint will "
        "bleed through the badge again")


def test_a_chip_with_no_theme_yet_paints_without_raising():
    """StatusChip is constructed before apply_theme reaches it (GlassCard
    builds its whole footer first). A paint in that window must be a
    no-op, not a crash."""
    chip = StatusChip("APPLIED")
    chip.resize(80, 17)
    pm = QPixmap(chip.size())
    chip.render(pm)
    chip.deleteLater()


# ============================================================
#  5. TYPE HIERARCHY — TITLES SEPARATE FROM DESCRIPTIONS
# ============================================================
def test_a_card_title_outweighs_its_description_on_every_axis():
    """The v1.0 audit called the hierarchy low-contrast and v7 answered on
    SIZE alone; the weight stayed at 650, a value that exists in no type
    system and reads as "a bit bolder". A card title is the only thing read
    when scanning a grid of nine, so it has to separate on size AND weight
    AND colour, not on one of them."""
    title_size, title_weight, title_colour, _extra = TH._LABEL_ROLES["card"]
    desc_size, desc_weight, desc_colour, _ = TH._LABEL_ROLES["desc"]
    assert int(title_size.rstrip("px")) - int(desc_size.rstrip("px")) >= 3
    assert int(title_weight) - int(desc_weight) >= 200
    assert title_colour == "text" and desc_colour != "text", (
        "the title and its description sit on the same colour step")


@pytest.mark.parametrize("role", ["title", "dialog", "card"])
def test_every_heading_weight_comes_off_the_weight_scale(role):
    """650 and 680 were nobody's decision. TH.WEIGHT exists for the same
    reason TH.TYPE and TH.SPACE do."""
    _size, weight, _colour, _extra = TH._LABEL_ROLES[role]
    assert int(weight) in TH.WEIGHT.values(), (
        f"the {role} role is set at {weight}, which is not a step on "
        f"TH.WEIGHT {sorted(TH.WEIGHT.values())}")


@pytest.mark.parametrize("role", ["title", "dialog", "card"])
def test_headings_carry_negative_tracking(role):
    """The half nobody adds. Default spacing suits 12px body copy; at
    heading sizes it leaves the word looking loose and unresolved, and
    pulling it in is what makes a title read as machined rather than
    merely bold."""
    _size, _weight, _colour, extra = TH._LABEL_ROLES[role]
    assert "letter-spacing: -" in extra, (
        f"the {role} role sets no negative tracking")


def test_the_tracking_pull_scales_with_the_size():
    """Tracking is an optical correction, not a constant: the hero's -0.5
    applied to a 16px card title would visibly jam the letters."""
    def pull(role):
        _s, _w, _c, extra = TH._LABEL_ROLES[role]
        return abs(float(extra.split("letter-spacing:")[1]
                         .split("px")[0].strip()))
    assert pull("title") > pull("dialog") > pull("card") > 0


def test_the_muted_half_of_the_hierarchy_was_left_alone():
    """The hierarchy is the GAP. Every point of weight added to the
    description closes it again, which is how a 'strengthen the titles'
    pass usually ends up changing nothing."""
    for role in ("desc", "body", "tagline"):
        _size, weight, _colour, extra = TH._LABEL_ROLES[role]
        assert int(weight) <= TH.WEIGHT["medium"], (
            f"the {role} role has been bolded to {weight}")
        assert "letter-spacing" not in extra
