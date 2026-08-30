"""
Layout & dialog standards — the v1.0+ Phase 0 guards.

These encode the visual standards that previously existed only as
convention, and each one is here because the thing it forbids ALREADY
SHIPPED once and was found by measuring rather than by looking:

  * a dialog whose content floor exceeded the window it opens in (the
    Software Catalog's 5-tab row forced a 1637px panel against a 1100px
    cap, so the panel was wider than the app at every window size);
  * a sparse row of "matching" tiles that were not the same width, because
    the shared column width was measured off the wrong size hint;
  * a section band whose header outlived its own cards under a filter, so
    the title sat over the next band's content and mislabelled it.

None of these raises. All three are invisible until somebody renders the
exact combination that exposes them, which is what makes them worth
pinning.
"""
from __future__ import annotations

import ast
import os
import re

import pytest
from PySide6.QtWidgets import QFrame, QLabel, QPushButton

from conftest import settle
from frontend import theme as TH
from frontend.main import CategoryPage
from frontend.menu_structure import (
    CATEGORIES, category_bands, category_items, category_operations,
)

_FRONTEND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "frontend")


# ============================================================
#  THE SPACING SCALE
# ============================================================
#: Layout calls whose integer arguments are pixel measurements.
_SPACING_CALLS = ("setSpacing", "addSpacing", "insertSpacing",
                  "setContentsMargins")


def _off_scale_calls(path: str) -> list[tuple[int, str]]:
    allowed = {0} | set(TH.SPACE.values())
    source = open(path, encoding="utf-8").read()
    lines = source.splitlines()
    out = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _SPACING_CALLS):
            continue
        literals = [a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, int)]
        if literals and not all(v in allowed for v in literals):
            out.append((node.lineno, lines[node.lineno - 1].strip()))
    return out


@pytest.mark.parametrize("module", ["main.py", "widgets.py", "animations.py",
                                    "health_report.py", "playbooks.py"])
def test_every_layout_measurement_comes_off_the_scale(module):
    """No hand-picked pixel gaps. Anywhere.

    theme.SPACE exists because the app once carried 13 distinct spacing
    values and margins like (15, 13, 16, 13) — the root cause of its
    "almost aligned" feel. The scale was introduced but never enforced,
    so 57 calls had drifted back to hand-picked numbers (1, 2, 3, 6, 7,
    9, 10, 14, 18, 20, 28, 30, 34), every one within 2px of a step it
    could have used. A comment is not a constraint; this is.

    If a surface genuinely needs a step the scale does not have, ADD THE
    STEP (with the reason, as "xxs" and "xxl" were added) rather than
    writing the number here.
    """
    off_scale = _off_scale_calls(os.path.join(_FRONTEND, module))
    listing = "\n".join(f"  {module}:{ln}  {text}" for ln, text in off_scale)
    assert not off_scale, (
        f"{len(off_scale)} layout call(s) off TH.SPACE "
        f"{sorted(TH.SPACE.values())}:\n{listing}")


# ============================================================
#  THE TYPE SCALE
# ============================================================
#: `font-size: 13px` written straight into a QSS string.
_FONT_SIZE_LITERAL = re.compile(r"font-size:\s*(\d+)px")

#: Qt modules only. health_report.py writes CSS for a standalone exported
#: HTML document — a different medium, its own typography, no access to
#: these tokens when a browser renders it. See the note on TH.TYPE.
_TYPED_MODULES = ["theme.py", "main.py", "widgets.py",
                  "animations.py", "playbooks.py"]


@pytest.mark.parametrize("module", _TYPED_MODULES)
def test_every_font_size_comes_off_the_type_scale(module):
    """No hand-picked type sizes. Anywhere.

    The exact defect SPACE was introduced to kill, one axis over: ten
    distinct font-size literals were hand-written into about sixty QSS
    strings with no rule about which to reach for. The clearest symptom was
    a pair — the breadcrumb separator chevron at 17px and the card's
    drill-in chevron at 18px, the same element doing the same job one
    screen apart, different for no reason anyone could state.

    A size written here is a size nobody chose. Pick a role from TH.TYPE,
    or add a step with its reason, exactly as the spacing scale requires.
    """
    source = open(os.path.join(_FRONTEND, module), encoding="utf-8").read()
    lines = source.splitlines()
    off_scale = [(i + 1, lines[i].strip())
                 for i, line in enumerate(lines)
                 for _ in _FONT_SIZE_LITERAL.finditer(line)]
    listing = "\n".join(f"  {module}:{ln}  {text}" for ln, text in off_scale)
    assert not off_scale, (
        f"{len(off_scale)} font-size literal(s) not off TH.TYPE "
        f"{sorted(TH.TYPE.values())}:\n{listing}")


def test_the_type_scale_has_no_redundant_steps():
    """Two roles resolving to the same pixel size are one role with two
    names — the scale describing itself as finer than it is. (It is fine
    for a size to be UNUSED for a while; it is not fine for two steps to
    be indistinguishable.)"""
    by_size = {}
    for role, px in TH.TYPE.items():
        by_size.setdefault(px, []).append(role)
    clashes = {px: roles for px, roles in by_size.items() if len(roles) > 1}
    assert not clashes, f"TH.TYPE steps sharing a size: {clashes}"


# ============================================================
#  THE RADIUS RAMP
# ============================================================
#: `border-radius: 12px` written straight into a QSS string.
_RADIUS_LITERAL = re.compile(r"border-radius:\s*(\d+)px")


def test_the_radius_ramp_is_exactly_three_tiers():
    """The third scale, held to the same standard as SPACE and TYPE.

    Through v12 this ran five steps — 8/10/12/14/18 — and five steps is
    what fragmentation looks like once it has been given names. Two pixels
    is below the threshold at which a corner difference reads as a
    decision and above the threshold at which it reads as sloppiness, so a
    10px button beside a 12px icon well beside a 14px card read as one
    family drawn slightly wrong rather than as three levels of anything.

    Three tiers, and the semantic names deliberately COLLIDE onto them:
    `control`, `plaque` and `card` all resolving to 12 is the scale
    asserting that a button, an icon well and a card ARE the same tier,
    which is a statement the old ramp had no way to make.
    """
    tiers = sorted(set(TH.RADIUS.values()))
    assert tiers == [8, 12, 16], (
        f"the radius ramp is back to {len(tiers)} values {tiers} — see the "
        "note on TH.RADIUS for why three is the whole point")


def test_every_semantic_radius_lands_on_a_tier():
    """A name is allowed to share a tier. A name is not allowed to invent
    one — that is how five steps happened the first time."""
    tiers = set(TH.RADIUS.values())
    strays = {name: px for name, px in TH.RADIUS.items() if px not in tiers}
    assert not strays, f"radius names off the ramp: {strays}"


@pytest.mark.parametrize("module", _TYPED_MODULES)
def test_every_radius_literal_is_a_tier_or_sub_chip(module):
    """No hand-picked corners in QSS, the same guard the spacing and type
    scales already carry.

    Two things are legal besides a tier. ZERO, because a surface can be
    deliberately square — the shell is, and has its own test saying so
    (test_rendering.test_shell_paints_square_corners). And anything BELOW
    the smallest tier, because a scrollbar handle or a meter bar is not a
    surface with a corner style, it is a 4px-thick sliver whose radius is
    half its own thickness. What is forbidden is the middle: a literal
    sitting between the tiers is a corner nobody chose, and it is exactly
    what `border-radius: 10px` would be.
    """
    tiers = set(TH.RADIUS.values())
    source = open(os.path.join(_FRONTEND, module), encoding="utf-8").read()
    lines = source.splitlines()
    off_ramp = [(i + 1, line.strip())
                for i, line in enumerate(lines)
                for m in _RADIUS_LITERAL.finditer(line)
                if int(m.group(1)) not in tiers
                and int(m.group(1)) >= min(tiers)]
    listing = "\n".join(f"  {module}:{ln}  {text}"
                        for ln, text in off_ramp)
    assert not off_ramp, (
        f"{len(off_ramp)} border-radius literal(s) off the ramp "
        f"{sorted(tiers)}:\n{listing}")


def test_an_inset_child_stays_concentric():
    """TH.inner_radius exists because `RADIUS['chip']-1` was written into
    seven QSS strings by hand. Two rounded rects sharing a centre only read
    as one nested object when their radii differ by exactly the gap between
    them."""
    for outer in sorted(set(TH.RADIUS.values())):
        for inset in (1, 2, 3):
            assert TH.inner_radius(outer, inset) == max(2, outer - inset)


def test_an_inset_child_never_squares_off():
    """A deep inset must not hand back a 0 radius: a square corner inside a
    rounded surface is the one result worse than a mismatched one."""
    assert TH.inner_radius(TH.RADIUS["chip"], 99) >= 2


# ============================================================
#  THE ICON SCALE
# ============================================================
#: `TH.icon_font(20)` — a glyph size written straight into a call.
_ICON_SIZE_LITERAL = re.compile(r"icon_font\(\s*(\d+)\s*\)")


def test_the_icon_ramp_is_exactly_three_tiers():
    """The fifth scale, held to the same standard as SPACE, TYPE and
    RADIUS. Glyphs shipped at SIX hand-picked sizes (12, 13, 15, 16, 19,
    21), and three of those were the same element — a Fluent glyph in a
    PLAQUE_SIZE well — drawn at three sizes in three places."""
    tiers = sorted(set(TH.ICON.values()))
    assert len(tiers) == 3, (
        f"the icon ramp is back to {len(tiers)} values {tiers} — see the "
        "note on TH.ICON for why three is the point")
    assert min(tiers) >= 12 and max(tiers) <= 24


def test_one_well_is_one_glyph_size_everywhere():
    """The defect the scale was added for, asserted directly.

    PLAQUE_SIZE already guarantees that a sidebar entry, a category card
    and a dialog action row paint the same 36px WELL. It said nothing about
    what goes inside, so the three drew 16px, 21px and 19px glyphs in it —
    which is the same 'one module is one object' rule failing one level
    further in than the rule was written.
    """
    from frontend.widgets import ActionRow, GlassCard
    assert GlassCard._ICON_BASE_PX == TH.ICON["plaque"]
    assert ActionRow._ICON_PX == TH.ICON["plaque"]
    # ...and the well itself is still the shared one on both.
    assert ActionRow._PLAQUE == GlassCard._PLAQUE


@pytest.mark.parametrize("module", ["main.py", "widgets.py"])
def test_every_icon_size_comes_off_the_scale(module):
    """No hand-picked glyph sizes, the same guard the other four scales
    carry.

    Scoped to TH.icon_font() calls deliberately: the scale governs glyphs
    drawn in the Fluent ICON FONT. A '●' set in the UI font at 12px (the
    activity rail's status dot) is a dot diameter, not an icon size, and
    holding it to this ramp would be enforcing a rule about a different
    thing because it happens to be a small number.
    """
    tiers = set(TH.ICON.values())
    source = open(os.path.join(_FRONTEND, module), encoding="utf-8").read()
    off_ramp = [(i + 1, line.strip())
                for i, line in enumerate(source.splitlines())
                for m in _ICON_SIZE_LITERAL.finditer(line)
                if int(m.group(1)) not in tiers]
    listing = chr(10).join(f"  {module}:{ln}  {text}"
                           for ln, text in off_ramp)
    assert not off_ramp, (
        f"{len(off_ramp)} icon size literal(s) off the ramp "
        f"{sorted(tiers)}:" + chr(10) + listing)


# ============================================================
#  THE PADDING ROLES
# ============================================================
def test_every_padding_role_lands_on_the_spacing_scale():
    """PAD names two of SPACE's steps; it does not invent numbers.

    The point of a second vocabulary is to say WHICH step a kind of
    surface takes, not to open a second scale beside the first — which is
    exactly how the app came to have five padding recipes for one
    question in the first place.
    """
    steps = set(TH.SPACE.values())
    for role, value in TH.PAD.items():
        assert value in steps, (
            f"PAD[{role!r}] = {value} is not a SPACE step {sorted(steps)}")
    assert TH.PAD["sheet"] > TH.PAD["surface"], (
        "a floating sheet must carry MORE air than a card, or the two "
        "roles are one role with two names")


@pytest.mark.parametrize("width", [1000, 1400, 2200])
def test_home_and_a_module_share_one_content_column(window, qapp, width):
    """Opening a module must not move the page sideways.

    Both pages are swapped into the same QStackedWidget inside the same
    content frame, so any difference in their own root padding shifts the
    whole column on every navigation. It did: the dashboard padded itself
    by `xl` and a category page by `sm`, which measured as a 16px jump at
    every window size — flush on neither side of the transition, in a
    shell whose two halves are otherwise pixel-aligned.

    Measured at the SHELL, not at each page, because that is the frame
    both are drawn into and the only one in which "did it move?" is a
    question with an answer.
    """
    from PySide6.QtCore import QPoint

    original = window.size()
    window.resize(width, 900)
    settle(qapp, 120)
    try:
        def left(widget):
            return widget.mapTo(window._shell, QPoint(0, 0)).x()

        window.go_home()
        settle(qapp, 120)
        home = left(window.welcome._hero)

        window.open_category(1)
        settle(qapp, 200)
        page = window.pages[1]
        module = left(page._home)

        assert home == module, (
            f"@{width}px the dashboard's column starts at x={home} and a "
            f"module page's at x={module} — the content jumps "
            f"{abs(home - module)}px sideways when you navigate")
    finally:
        window.resize(original)
        window.go_home()
        settle(qapp, 120)


def test_every_card_grid_shares_one_gutter(qapp, window):
    """Three card grids at three gutters is the "almost aligned" feel the
    spacing scale exists to remove.

    The dashboard's health row ran 12, its quick actions 24, and a module
    page's card grid 16 — and the first two sit one above the other on the
    same screen, so the mismatch was visible without navigating anywhere.
    """
    welcome = window.welcome
    gutter = TH.SPACE["lg"]
    grids = {
        "the dashboard's health row": welcome._tile_row.spacing(),
        "the dashboard's quick actions": welcome._grid.spacing(),
        "a module page's card grid": window.pages[0]._grid.spacing(),
    }
    off = {name: value for name, value in grids.items() if value != gutter}
    assert not off, (
        f"card grids off the shared {gutter}px gutter: {off}")


def test_six_quick_actions_stay_a_two_by_three_block(window, qapp):
    """A ten-element launcher does not get denser as the window grows.

    v14 let the quick actions resolve to SIX columns from about 1440p up,
    on the argument that three columns would stretch each card past 500px.
    Measured at 2560 maximised, six across gave a 340px card whose own
    title wrapped to two lines — the crowded half of the same defect, and
    a composition that reads as one squeezed row above a void rather than
    as a launcher.

    The even-split rule (see WelcomePage._even_split) still narrows the
    block on a small window; what it may never do is widen it, because 4
    and 5 leave orphans and 6 crushes.
    """
    original = window.size()
    try:
        for width in (1400, 2000, 2400):
            window.resize(width, 1000)
            settle(qapp, 200)
            assert window.welcome._cols == 3, (
                f"@{width}px the quick actions laid out at "
                f"{window.welcome._cols} columns, not the 2x3 block six "
                "actions are composed as")
        # ...and it still narrows when there genuinely is no room
        window.resize(_MIN_W, _MIN_H)
        settle(qapp, 200)
        assert window.welcome._cols <= 2, (
            "the block did not narrow at the app's minimum width")
    finally:
        window.resize(original)
        settle(qapp, 120)


# ============================================================
#  SECTION BANDS
# ============================================================
class TestSectionBands:
    """A band is rhythm inside a page, never another level of navigation."""

    def test_every_category_declares_items_or_groups(self):
        for category in CATEGORIES:
            assert category.get("items") or category.get("groups"), (
                f"{category['title']} declares neither items nor groups")

    def test_bands_never_lose_a_card(self):
        """category_items must flatten to exactly the cards the bands hold —
        a card that exists in `groups` but not in the flattened view is
        invisible to the counter, the palette and playbook validation."""
        for category in CATEGORIES:
            banded = [item for _title, items in category_bands(category)
                      for item in items]
            assert banded == category_items(category), (
                f"{category['title']}: bands and category_items disagree")

    def test_banded_categories_have_titled_bands(self):
        """An untitled band inside a multi-band category would render as a
        gap with no explanation."""
        for category in CATEGORIES:
            if not category.get("groups"):
                continue
            for title, items in category_bands(category):
                assert title.strip(), (
                    f"{category['title']} has an untitled band")
                assert items, (
                    f"{category['title']} band {title!r} is empty")

    def test_no_band_is_a_wall(self):
        """The defect bands exist to fix. Twelve undifferentiated cards was
        the starting point; a band that grows back to that size has simply
        moved the wall down a level."""
        for category in CATEGORIES:
            for title, items in category_bands(category):
                assert len(items) <= 8, (
                    f"{category['title']} band {title!r} has {len(items)} "
                    "cards — split it rather than letting a band become the "
                    "wall it replaced")

    def test_operation_count_sees_through_bands(self):
        for category in CATEGORIES:
            assert category_operations(category) >= len(category_items(category))


@pytest.mark.parametrize("index", range(len(CATEGORIES)))
def test_band_headers_die_with_their_cards(qapp, index):
    """A header survives only while one of its OWN cards is visible.

    Filtering to a state no card on the page reports must leave NO headers
    behind: a surviving title over the next band's cards actively
    mislabels them, which is worse than the undifferentiated grid.
    """
    page = CategoryPage(CATEGORIES[index], TH.ThemeManager().t)
    page.resize(1200, 800)

    # isHidden(), NOT isVisible(): the page is never shown in a headless
    # run, and isVisible() is False for every child of an unshown parent —
    # which would make the orphan assertion below pass for the wrong
    # reason, on a page where every header actually survived. isHidden()
    # reports the widget's OWN explicit state, which is what is under test.
    def shown(widget) -> bool:
        return not widget.isHidden()

    # every card starts unbadged, so "Action due" matches nothing anywhere
    due_index = [key for _label, key in CategoryPage.FILTERS].index("due")
    page._filter.setCurrentIndex(due_index)
    qapp.processEvents()

    headers = [h for h, _cards in page._bands if h is not None]
    orphans = [h for h in headers if shown(h)]
    assert not orphans, (
        f"{CATEGORIES[index]['title']}: {len(orphans)} band header(s) "
        "survived a filter that hid every card beneath them")
    assert shown(page._empty), "the filtered-empty state was not shown"
    assert not any(shown(c) for c in page.cards), "a card survived the filter"

    page._filter.setCurrentIndex(0)
    qapp.processEvents()
    assert all(shown(h) for h in headers), (
        "clearing the filter did not bring every band header back")
    assert not shown(page._empty), "the empty state outlived the filter"


@pytest.mark.parametrize("index", range(len(CATEGORIES)))
def test_every_card_renders_on_a_ladder_step(qapp, index):
    """Card heights are three deliberate sizes, not a continuum.

    Both halves of this shipped broken and both were invisible without
    measuring the running app. The floor (GlassCard.CARD_MIN_H) was
    documented from v10 and enforced nowhere the layout looks: a wrapping
    card reports hasHeightForWidth(), so QGridLayout sizes its row from
    QWidgetItem::heightForWidth, which consults neither sizeHint() nor
    minimumSizeHint() — 26 of 41 cards rendered under the floor and three
    at 101px against a documented 128. And with the floor honoured the
    heights still spanned seven distinct values across four modules, so
    cards matched inside a band and disagreed across bands: the same
    "almost aligned" quality TH.SPACE exists to remove, one axis over.

    Asserted against the rendered geometry rather than the hints, because
    the hints were the thing that was lying.
    """
    from frontend.widgets import GlassCard

    page = CategoryPage(CATEGORIES[index], TH.ThemeManager().t)
    page.resize(1360, 900)
    qapp.processEvents()

    cards = page.findChildren(GlassCard)
    assert cards, f"{CATEGORIES[index]['title']}: no cards to measure"
    off_ladder = [(c.item["title"], c.height()) for c in cards
                  if c.height() not in GlassCard.CARD_STEPS]
    assert not off_ladder, (
        f"{CATEGORIES[index]['title']}: card(s) off the ladder "
        f"{GlassCard.CARD_STEPS}: {off_ladder}")


@pytest.mark.parametrize("index", range(len(CATEGORIES)))
def test_snapping_a_card_never_clips_its_content(qapp, index):
    """The ladder may only ever ADD air, never remove it.

    _snap_height rounds upward for exactly this reason, and the property
    is worth pinning separately from the ladder itself: a future step
    inserted in the middle of CARD_STEPS, or a padding change that pushes
    the anatomy past the top step, would start silently cropping card
    descriptions — the failure mode the pre-v10 146px cap had, which
    nobody noticed because clipped text simply is not drawn.
    """
    from frontend.widgets import GlassCard

    page = CategoryPage(CATEGORIES[index], TH.ThemeManager().t)
    page.resize(1360, 900)
    qapp.processEvents()

    squeezed = []
    for card in page.findChildren(GlassCard):
        natural = card.layout().totalMinimumSize().height()
        if card.height() < natural:
            squeezed.append((card.item["title"], card.height(), natural))
    assert not squeezed, (
        f"{CATEGORIES[index]['title']}: card(s) shorter than their own "
        f"content needs (title, rendered, required): {squeezed}")


def test_band_headers_are_themed_in_both_modes(qapp):
    """A band header is built from plain QLabel/QFrame, so an un-styled one
    renders in the platform palette — white text on white in light mode."""
    theme = TH.ThemeManager()
    for _ in range(2):
        page = CategoryPage(CATEGORIES[1], theme.t)   # System & Tweaks: banded
        for header, _cards in page._bands:
            assert header is not None
            title = header.findChild(QLabel, "bandTitle")
            rule = header.findChild(QFrame, "bandRule")
            assert title is not None and title.styleSheet(), (
                f"band title unstyled in {theme.t['name']} mode")
            assert rule is not None and rule.styleSheet(), (
                f"band rule unstyled in {theme.t['name']} mode")
        theme.toggle()


@pytest.mark.parametrize("width", [1100, 1440, 1920])
def test_content_column_edges_line_up(window, qapp, width):
    """The card grid and the page header share one content column.

    Measured, because this is the class of defect that never looks like a
    bug and always looks like sloppiness: the grid shipped with margins of
    (2, 4, 12, 4), which put the last card's right edge 34px inside the
    count chip above it while the left edge sat 2px OUTSIDE the
    breadcrumb — flush on one side, floating on the other. The band rule
    separately overhung the last card by one 16px gutter because it
    spanned MAX_COLUMNS rather than the live column count.
    """
    original = window.size()
    window.resize(width, 900)
    qapp.processEvents()
    try:
        window.open_category(1)          # System & Tweaks: banded, 12 cards
        for _ in range(6):
            qapp.processEvents()
        page = window.pages[1]

        def left(widget):
            return widget.mapTo(page, widget.rect().topLeft()).x()

        def right(widget):
            return widget.mapTo(page, widget.rect().topRight()).x()

        # EVERY band, not just the first. v1.1 introduced bands smaller
        # than the column count (System & Tweaks' two-card NETWORK band),
        # and a header that spans the full width regardless draws its rule
        # across empty canvas — invisible to a check that only ever looked
        # at a band with more cards than columns.
        for index, (header, cards) in enumerate(page._bands):
            assert header is not None
            assert left(cards[0]) == left(page._home), (
                f"@{width}px band {index}: cards start "
                f"{left(cards[0]) - left(page._home)}px from the page "
                "header's left edge")

            last = cards[min(page._cols, len(cards)) - 1]
            assert right(header) == right(last), (
                f"@{width}px band {index}: the band rule overhangs the last "
                f"card of its first row by {right(header) - right(last)}px")
    finally:
        window.resize(original)
        qapp.processEvents()


@pytest.mark.parametrize("index", range(len(CATEGORIES)))
def test_no_band_header_overlaps_its_own_cards(window, qapp, index):
    """Vertical separation, MEASURED — the y-axis twin of the column-edge
    check above, and a defect that shipped for exactly as long as nobody
    measured it.

    A card's height is heightForWidth-dependent, so Qt resolves it lazily
    and the first layout pass sizes rows from provisional heights. On a
    page whose band ends with a partly-filled row (Utilities & Tools: four
    cards over three columns) that left the NEXT band's header drawn 18px
    inside its own first card. _relayout early-returns while the column
    count is unchanged, so nothing re-ran it either — the page corrected
    itself only if an unrelated resize happened to re-activate the grid,
    which is precisely the kind of bug that looks like a rendering glitch
    and gets dismissed as one.
    """
    # The window fixture is shared for the whole session, so its size is
    # borrowed and put back — a leaked resize silently re-measures every
    # geometry test that runs after this one.
    original = window.size()
    window.resize(1500, 950)
    try:
        window.open_category(index)
        for _ in range(8):
            qapp.processEvents()
        page = window.pages[index]

        for band, (header, cards) in enumerate(page._bands):
            assert header is not None
            top = min(c.geometry().y() for c in cards)
            bottom = header.geometry().y() + header.geometry().height()
            assert bottom <= top, (
                f"{CATEGORIES[index]['title']} band {band}: the header runs "
                f"to y={bottom} but its first card starts at y={top} — the "
                f"title is drawn {bottom - top}px inside the card it labels")
    finally:
        window.resize(original)
        qapp.processEvents()


def test_band_headers_hug_the_cards_they_label(qapp):
    """Proximity: a header belongs to the band BELOW it, so the air above
    it must exceed the air below. Equidistant headers read as loose rows
    rather than as groups."""
    page = CategoryPage(CATEGORIES[1], TH.ThemeManager().t)
    page.resize(1200, 900)
    qapp.processEvents()
    for index, (header, cards) in enumerate(page._bands):
        assert header is not None
        top = header.layout().contentsMargins().top()
        if index == 0:
            assert top == 0, "the first band already has the page header above it"
        else:
            assert top > 0, (
                f"band {index} has no separation from the band above it")


# ============================================================
#  SPARSE MODE
# ============================================================
def test_sparse_mode_is_dormant(qapp):
    """SPARSE_MAX_CARDS dropped to 2 because the only page it still caught
    was one it was never designed for. If a page falls to 2 cards later
    this test is the prompt to look at the centred layout again on
    purpose, rather than discovering it in a screenshot."""
    caught = [c["title"] for c in CATEGORIES
              if len(category_items(c)) <= CategoryPage.SPARSE_MAX_CARDS]
    assert not caught, (
        f"sparse mode now applies to {caught} — confirm the centred, "
        "width-capped composition is really what those pages want")


def test_sparse_columns_would_share_one_width(qapp):
    """The shared unit is measured off sizeHint, not minimumSizeHint: the
    minimum is what a card can be SQUEEZED to (~214px with its description
    wrapped hard), which is not what an unstretched column resolves to.
    Measuring the wrong one shipped a 526px tile beside a 430px one."""
    page = CategoryPage(CATEGORIES[0], TH.ThemeManager().t)
    page.resize(1400, 800)
    qapp.processEvents()
    unit = page._sparse_unit()
    widest = max(c.sizeHint().width() for c in page.cards)
    assert unit >= widest, (
        f"sparse unit {unit} is under the widest card's sizeHint {widest} — "
        "columns would resolve to different widths")
    assert unit >= CategoryPage.SPARSE_CARD_W


# ============================================================
#  DIALOG STANDARDS
# ============================================================
#: Every dialog the app can open, with the arguments its constructor needs.
#: Kept explicit rather than discovered by walking PulseDialog subclasses:
#: a discovered list silently shrinks to nothing if the base class is
#: renamed, and would then pass while testing zero dialogs.
def _dialog_specs(window):
    from frontend import menu_structure as MS
    from frontend import widgets as W

    t = window.theme.t
    item = {"icon": "📦", "title": "Demo", "desc": "Demo card.",
            "task": "SystemInfo"}
    hub = {"icon": "🛠️", "title": "Hub", "desc": "Hub.", "hub": True,
           "items": [item]}
    return [
        ("ConfirmDialog", lambda: W.ConfirmDialog(window, item, t)),
        ("HubDialog", lambda: W.HubDialog(window, hub, t)),
        ("SoftwareCatalogDialog", lambda: W.SoftwareCatalogDialog(
            window, item, t, MS.SOFTWARE_CATALOG)),
        ("CommandPalette", lambda: W.CommandPalette(
            window, t, list(MS.iter_leaf_items()))),
        ("ShortcutSheetDialog", lambda: W.ShortcutSheetDialog(
            window, t, [("Ctrl+K", "Search")])),
        ("ElevatePromptDialog", lambda: W.ElevatePromptDialog(window, item, t)),
        ("CloseConfirmDialog", lambda: W.CloseConfirmDialog(window, t, "Demo")),
        ("PowerHealthDialog", lambda: W.PowerHealthDialog(window, "", t)),
        ("RestorePointDialog", lambda: W.RestorePointDialog(window, "", t)),
        ("StorageAnalyzerDialog", lambda: W.StorageAnalyzerDialog(window, "", t)),
    ]


#: The app's own minimum window size. A dialog is opened INSIDE this, so a
#: panel wider than it is a panel hanging off the window.
_MIN_W, _MIN_H = 752, 620

#: Mirrors _dialog_specs' keys. Declared separately because parametrize is
#: evaluated at COLLECTION time, before the `window` fixture that
#: _dialog_specs needs exists.
_DIALOG_NAMES = [
    "ConfirmDialog", "HubDialog", "SoftwareCatalogDialog", "CommandPalette",
    "ShortcutSheetDialog", "ElevatePromptDialog", "CloseConfirmDialog",
    "PowerHealthDialog", "RestorePointDialog", "StorageAnalyzerDialog",
]


def test_the_dialog_roster_is_complete(window):
    """Keeps _DIALOG_NAMES honest against _dialog_specs — a name added to
    one and not the other would silently stop testing a dialog."""
    assert sorted(_DIALOG_NAMES) == sorted(n for n, _b in _dialog_specs(window))


@pytest.mark.parametrize("name", _DIALOG_NAMES)
def test_dialog_panel_fits_the_minimum_window(window, qapp, name):
    """THE guard that would have caught the Software Catalog regression.

    A responsive panel takes its width from a content floor that OVERRIDES
    both its own cap and the host window (see widgets._content_width_floor),
    so a single wide row — the catalog's five labelled tabs — can drag the
    whole dialog wider than the app. Nothing raises; the panel simply
    hangs off the window.
    """
    from frontend.widgets import refit_dialog

    original = window.size()
    window.resize(_MIN_W, _MIN_H)
    qapp.processEvents()
    try:
        spec = dict(_dialog_specs(window))
        dialog = spec[name]()
        dialog.resize(window.size())
        dialog.show()
        qapp.processEvents()
        refit_dialog(dialog)
        qapp.processEvents()

        panel = getattr(dialog, "panel", None)
        assert panel is not None, f"{name} did not build a chrome panel"
        floor = panel.layout().minimumSize().width() if panel.layout() else 0
        assert floor <= _MIN_W, (
            f"{name}'s content floor is {floor}px against a {_MIN_W}px "
            "minimum window — wrap wide button rows in widgets._chip_strip "
            "so the row reports a small minimum and scrolls instead")
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()
    finally:
        window.resize(original)
        qapp.processEvents()


def test_every_dialog_uses_the_shared_chrome(window, qapp):
    """`panel` is what _dialog_chrome installs. A dialog without one has
    hand-rolled its own frame and will drift from the rest of the app."""
    missing = []
    for name, build in _dialog_specs(window):
        dialog = build()
        if getattr(dialog, "panel", None) is None:
            missing.append(name)
        dialog.reject()
        dialog.deleteLater()
    qapp.processEvents()
    assert not missing, f"dialogs not built on _dialog_chrome: {missing}"


# ============================================================
#  THE ACTION BAND  (v10.5)
# ============================================================
def _shipped_hubs():
    """The hubs that shipped the defect this band exists to fix.

    Read off the real menu structure rather than named, so a third hub
    added later is covered without anyone remembering to add it here.
    """
    return [item for cat in CATEGORIES for item in category_items(cat)
            if item.get("hub")]


def test_there_are_hubs_to_test():
    """Guards the discovery above: if hubs stop being declared with the
    `hub` key, every assertion below would pass while testing nothing."""
    assert _shipped_hubs(), "no hub cards found in the menu structure"


@pytest.mark.parametrize("host_size", [(752, 620), (1300, 860), (2560, 1440)])
def test_a_hub_never_stretches_past_the_action_band(window, qapp, host_size):
    """THE regression this band was added for.

    Built on the selector band, a two-action hub opened at up to 1280x900:
    two rows, stretched and centred, in a panel sized for a fourteen-card
    page. The complaint was "massive dead space", and it only got worse on
    the big displays nobody develops on - which is why the widest case here
    is 1440p rather than the developer's own window.
    """
    from frontend import widgets as W

    original = window.size()
    window.resize(*host_size)
    qapp.processEvents()
    try:
        for hub in _shipped_hubs():
            dialog = W.HubDialog(window, hub, window.theme.t)
            dialog.show()
            qapp.processEvents()
            W.refit_dialog(dialog)
            qapp.processEvents()
            width = dialog.panel.width()
            assert W._ACTION_WIDTH_MIN <= width <= W._ACTION_WIDTH_MAX, (
                f"{hub['title']} opened {width}px wide at host {host_size} - "
                f"outside the action band "
                f"[{W._ACTION_WIDTH_MIN}, {W._ACTION_WIDTH_MAX}]")
            dialog.reject()
            dialog.deleteLater()
        qapp.processEvents()
    finally:
        window.resize(original)
        qapp.processEvents()


def test_a_hub_is_only_as_tall_as_what_it_offers(window, qapp):
    """Height HUGS content - that is the difference in KIND between the two
    bands, not merely a smaller number. A hub with more actions must be
    taller than one with fewer; a fixed height would make them identical
    and both of them mostly empty."""
    from frontend import widgets as W

    heights = {}
    for hub in _shipped_hubs():
        dialog = W.HubDialog(window, hub, window.theme.t)
        dialog.show()
        qapp.processEvents()
        W.refit_dialog(dialog)
        qapp.processEvents()
        heights[len(hub["items"])] = dialog.panel.height()
        # Compared against the SELECTOR band's cap, not its floor. Both
        # bands hug their content as of v10.6, so the floor no longer
        # separates them - what still does is that a two-action hub must
        # come nowhere near the height a thirty-row list is allowed.
        cap = W._selector_panel_height_cap(dialog)
        assert dialog.panel.height() < cap * 0.75, (
            f"{hub['title']} is {dialog.panel.height()}px tall against a "
            f"{cap}px selector cap - it is not hugging its two rows")
        dialog.reject()
        dialog.deleteLater()
    qapp.processEvents()
    if len(heights) > 1:
        counts = sorted(heights)
        assert heights[counts[-1]] > heights[counts[0]], (
            f"a {counts[-1]}-action hub is no taller than a {counts[0]}-"
            f"action one ({heights}) - the panel is not sized by its content")


def test_every_hub_action_is_one_action_row(window, qapp):
    """One row per offered action, in order, and nothing else in the list.
    A hub that silently dropped or doubled a sub-action would still look
    perfectly right."""
    from frontend import widgets as W
    from frontend.menu_structure import hub_items

    for hub in _shipped_hubs():
        dialog = W.HubDialog(window, hub, window.theme.t)
        rows = dialog.panel.findChildren(W.ActionRow)
        assert len(rows) == len(hub_items(hub)), hub["title"]
        assert ([r.item["title"] for r in rows]
                == [i["title"] for i in hub_items(hub)])
        dialog.reject()
        dialog.deleteLater()
    qapp.processEvents()


def test_a_hubs_action_buttons_share_one_right_edge(window, qapp):
    """Each button sizes itself to its own verb, so "Remove" and
    "Reinstall" came out 78 and 80 wide - a two-pixel stagger on the
    dialog's right edge, which is exactly the "almost aligned" class of
    defect the layout scales exist to remove."""
    from frontend import widgets as W

    for hub in _shipped_hubs():
        dialog = W.HubDialog(window, hub, window.theme.t)
        dialog.show()
        qapp.processEvents()
        widths = {r.button.width()
                  for r in dialog.panel.findChildren(W.ActionRow)}
        assert len(widths) == 1, (
            f"{hub['title']}'s action buttons are {sorted(widths)} wide")
        dialog.reject()
        dialog.deleteLater()
    qapp.processEvents()


def test_a_destructive_row_is_tinted_rather_than_wireframed(qapp):
    """The destructive treatment, asserted at the factory.

    A hard red outline around a transparent row makes the teardown the
    loudest thing on a dialog whose other option is the safe one - it
    advertises exactly the action the user is least likely to want. The
    fill has to be present, and it has to be QUIET.
    """
    for mode in ("dark", "light"):
        t = TH.ThemeManager(mode, None).t
        danger = TH.action_row_qss(t, t["accent"], danger=True)
        safe = TH.action_row_qss(t, t["accent"], danger=False)
        assert TH.alpha(t["err"], TH.DANGER_TINT) in danger, (
            f"{mode}: the destructive row has no tinted fill")
        assert TH.alpha(t["err"], TH.DANGER_LINE) in danger
        assert t["err"] not in safe, (
            f"{mode}: a non-destructive row is wearing the error tone")
    assert TH.DANGER_TINT <= 0.12, (
        f"the destructive tint is {TH.DANGER_TINT} - past ~0.12 it stops "
        "shouldering the row and starts dyeing it")
    assert TH.DANGER_LINE < 0.30, (
        "the destructive hairline is back at wireframe weight")


def test_a_destructive_row_cannot_be_fired_by_a_stray_click(window, qapp):
    """The whole row is clickable as a convenience, the way a native
    settings list behaves - but never for a destructive action, where a
    stray click on a description would start an irreversible task."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from frontend import widgets as W

    t = window.theme.t
    # PARENTED, and deleted in the finally. A parentless QWidget is a
    # top-level WINDOW that outlives the test and is destroyed at
    # interpreter shutdown - by which point the QApplication may already be
    # gone, and a widget destroyed after its application is one of the ways
    # a fully green session still exits non-zero.
    danger = W.ActionRow({"title": "Purge", "desc": "d", "danger": True}, t,
                         t["accent"], parent=window)
    safe = W.ActionRow({"title": "Restore", "desc": "d"}, t, t["accent"],
                       parent=window)
    fired = []
    danger.activated.connect(lambda: fired.append("danger"))
    safe.activated.connect(lambda: fired.append("safe"))
    try:
        for row in (danger, safe):
            row.resize(560, 80)
            QTest.mouseClick(row, Qt.MouseButton.LeftButton,
                             pos=QPoint(row.width() // 2, row.height() // 2))
        qapp.processEvents()
        assert fired == ["safe"], (
            f"row-wide click fired {fired} - a destructive action must be "
            "reachable only through its own button")
    finally:
        for row in (danger, safe):
            row.setParent(None)
            row.deleteLater()
        qapp.processEvents()


# ============================================================
#  CONTENT HUGGING  (v10.6)
# ============================================================
def _rows(count):
    return [{"Id": f"A.B{i}", "Name": f"App {i}", "CurrentVersion": "1.0",
             "AvailableVersion": "2.0"} for i in range(count)]


@pytest.fixture
def quiet_update_center(monkeypatch):
    """The Update Center without its live winget scan — see the note in
    tests/test_live_updater.py. These tests are about geometry."""
    from frontend import widgets as W
    monkeypatch.setattr(W.UpdateCenterDialog, "_start_scan", lambda self: None)


def test_a_selector_grows_with_its_content(window, qapp, quiet_update_center):
    """THE DEFECT THIS BAND WAS REBUILT FOR.

    Selectors used to be given a FIXED height derived from the window, so
    the Update Center holding ONE update rendered at the same height as one
    holding thirty — roughly 500px of empty black under a single row, which
    is what the screenshots that prompted this pass show.
    """
    from PySide6.QtWidgets import QDialog
    from frontend import widgets as W
    from utils.helpers import TaskResult

    heights = {}
    for count in (1, 3, 8):
        dialog = W.UpdateCenterDialog(window, "", window.theme.t)
        dialog.show()
        qapp.processEvents()
        dialog._on_scan_finished(
            TaskResult(success=True, message="ok", data=_rows(count)))
        qapp.processEvents()
        W.refit_dialog(dialog)
        qapp.processEvents()
        heights[count] = dialog.panel.height()
        dialog.reject()
        dialog.deleteLater()
    qapp.processEvents()

    assert heights[1] < heights[3] < heights[8], (
        f"the panel does not track its row count: {heights}")
    assert heights[1] < 320, (
        f"a ONE-row Update Center is {heights[1]}px tall — it is reserving "
        "space for rows that do not exist")


def test_a_fit_scroll_measures_its_content_at_the_width_it_gets(window, qapp):
    """THE SECOND HALF OF "HUG YOUR CONTENT", and the one that shipped
    broken for as long as FitScroll existed.

    FitScroll forwards the inner widget's height so a dialog can size to
    what is actually in it. It asked for that height with
    `layout.sizeHint()`, which Qt measures against the layout's own
    PREFERRED width — and every wrapping QLabel in the app prefers a
    narrower column than an 840px selector panel gives it. So the hint
    described a taller, skinnier version of the content than the one that
    would be painted: the dialog sized itself to the phantom, the real
    text wrapped onto fewer lines, and the leftover became dead space
    under the last row.

    Measured on the DNS switcher before the fix: the host layout hinted
    311px while the same content at the panel's real width occupied 266.
    45px of void on a 467px dialog, entirely from asking the wrong
    question — which is the same class of defect, and the same visible
    symptom, that FitScroll was written to remove.

    The guard is stated against a widget whose height genuinely depends on
    its width, so it fails if the height-for-width path is dropped.

    IT ASSERTS THAT THE TWO ANSWERS DIFFER, NOT WHICH ONE IS LARGER. The
    direction is a property of the fixture's screen, not of the defect: a
    word-wrapping QLabel's sizeHint() is measured at the width Qt thinks it
    would PREFER, and for a 1100-character label that is a wide, short box
    (956px here) — wider than the 840px panel, so the naive hint comes out
    SHORTER, the opposite way round from the DNS switcher measured above.
    That cap moves with the display (it is screen-derived, and the
    offscreen platform's virtual screen is 800x800), so an assertion on the
    direction is an assertion about the machine running the suite. The
    defect itself — reporting sizeHint().height() instead of the height at
    the viewport's width — is caught exactly by the pair below: the value
    must not be the naive hint, and must be the height-for-width one.
    """
    from PySide6.QtWidgets import QLabel, QWidget
    from frontend import widgets as W

    host = QWidget()
    lay = W.scroll_host_layout(host)
    label = QLabel("word " * 220)
    label.setWordWrap(True)
    lay.addWidget(label)
    lay.addStretch()

    scroll = W.FitScroll()
    scroll.setWidget(host)
    scroll.setParent(window)
    scroll.resize(840, 400)
    # show(), and it is load-bearing. setParent() HIDES a widget, and Qt
    # defers resize events for hidden widgets until they are shown — so
    # without this the viewport never left its default 640px and every
    # number here described a width the area was never actually given.
    scroll.show()
    qapp.processEvents()

    viewport_w = scroll.viewport().width()
    at_width = scroll._content_height()
    naive = lay.sizeHint().height()
    try:
        assert lay.hasHeightForWidth(), (
            "the fixture no longer has a width-dependent height, so it "
            "cannot detect the defect it was written for")
        assert viewport_w == pytest.approx(840, abs=20), (
            f"the viewport is {viewport_w}px, not the 840 it was resized "
            "to — the measurement below is against the wrong width")
        assert at_width != naive, (
            f"FitScroll reports {at_width}px, which is exactly what the "
            "layout's own sizeHint() hints — it is back to measuring at "
            "the layout's preferred width")
        assert at_width == pytest.approx(
            lay.heightForWidth(viewport_w), abs=4), (
            "the reported height is not the content's height at the width "
            "the viewport actually gives it")
    finally:
        scroll.hide()
        scroll.setParent(None)
        scroll.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("name", ["dns", "power", "restore", "storage"])
def test_an_inspector_leaves_no_void_under_its_content(window, qapp, name):
    """The same guarantee end to end, on the dialogs the redesign named.

    A panel whose height exceeds what its own scroll area is showing IS
    the black void, whatever the intermediate hints claim — so this
    measures the finished geometry rather than any one widget's opinion of
    it.
    """
    from frontend import widgets as W

    builders = {
        "dns":     lambda: W.DnsSwitcherDialog(window, "", window.theme.t),
        "power":   lambda: W.PowerHealthDialog(window, "", window.theme.t),
        "restore": lambda: W.RestorePointDialog(window, "", window.theme.t),
        "storage": lambda: W.StorageAnalyzerDialog(window, "", window.theme.t),
    }
    dialog = builders[name]()
    dialog.show()
    settle(qapp, 120)
    try:
        scroll = dialog._scroll
        # The area may be squeezed by the panel's cap (a long report
        # scrolls, which is correct); what must never happen is the
        # reverse — the area given MORE room than its content fills.
        slack = scroll.height() - scroll._content_height()
        # ...unless the panel is sitting on the band's own FLOOR, which is
        # a different thing from a void and the one case where empty space
        # is a decision. A dialog is not allowed to be 150px tall just
        # because that is all it has to say; below _SELECTOR_HEIGHT_MIN it
        # stops reading as a panel and starts reading as a tooltip. The
        # defect this guards against measured 45px of slack at a panel
        # height of 467 — nowhere near the floor.
        at_floor = dialog.panel.height() <= W._SELECTOR_HEIGHT_MIN + 2
        assert slack <= 4 or at_floor, (
            f"{name}: {slack}px of empty scroll viewport under the last "
            f"row at a panel height of {dialog.panel.height()} — the panel "
            "is reserving space for content that is not there")
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


def test_a_selector_stops_growing_at_the_cap_and_scrolls(
        window, qapp, quiet_update_center):
    """Hugging is not licence to outgrow the window. Past the cap the list
    scrolls inside a panel that has stopped growing."""
    from frontend import widgets as W
    from utils.helpers import TaskResult

    dialog = W.UpdateCenterDialog(window, "", window.theme.t)
    dialog.show()
    qapp.processEvents()
    dialog._on_scan_finished(
        TaskResult(success=True, message="ok", data=_rows(60)))
    qapp.processEvents()
    W.refit_dialog(dialog)
    qapp.processEvents()
    try:
        cap = W._selector_panel_height_cap(dialog)
        assert dialog.panel.height() <= cap
        assert dialog.panel.height() <= window.height(), (
            "the panel grew past the window it opens inside")
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("host_size", [(1100, 700), (1360, 900), (2560, 1440)])
def test_every_selector_stays_inside_the_width_band(window, qapp, host_size,
                                                    quiet_update_center):
    """760-840, at every window size.

    The one documented exception is a content floor wider than the band —
    see _selector_panel_width — so the assertion allows a panel to exceed
    the ceiling only when its own layout demands it, and never to fall
    under the floor.
    """
    from frontend import widgets as W

    original = window.size()
    window.resize(*host_size)
    qapp.processEvents()
    try:
        for name, build in _dialog_specs(window):
            dialog = build()
            if getattr(dialog, "_responsive_panel", None) != "selector":
                dialog.reject()
                dialog.deleteLater()
                continue
            dialog.show()
            qapp.processEvents()
            W.refit_dialog(dialog)
            qapp.processEvents()
            width = dialog.panel.width()
            floor = dialog.panel.layout().minimumSize().width()
            assert width >= W._SELECTOR_WIDTH_MIN, (
                f"{name} is {width}px wide at {host_size} — under the band")
            assert width <= max(W._SELECTOR_WIDTH_MAX, floor), (
                f"{name} is {width}px wide at {host_size} against a "
                f"{W._SELECTOR_WIDTH_MAX}px ceiling and a {floor}px content "
                "floor")
            dialog.reject()
            dialog.deleteLater()
        qapp.processEvents()
    finally:
        window.resize(original)
        qapp.processEvents()


def test_a_page_stack_reports_the_current_page(window, qapp, quiet_update_center):
    """QStackedLayout's hint is the MAX over every page, so a dialog that
    hugs its content pays for its tallest page forever. Measured before
    fit_stack: a one-row Update Center reserved the height of its
    empty-state page (a hero glyph, a centred sentence and two stretches)
    — ~90px of black under a single row."""
    from frontend import widgets as W
    from utils.helpers import TaskResult

    dialog = W.UpdateCenterDialog(window, "", window.theme.t)
    dialog.show()
    qapp.processEvents()
    dialog._on_scan_finished(
        TaskResult(success=True, message="ok", data=_rows(1)))
    qapp.processEvents()
    try:
        stack = dialog._stack
        current = stack.currentWidget()
        tallest = max(stack.widget(i).sizeHint().height()
                      for i in range(stack.count()))
        assert stack.sizeHint().height() <= current.sizeHint().height() + 4, (
            f"the stack reports {stack.sizeHint().height()}px for a page "
            f"that wants {current.sizeHint().height()}px (tallest page: "
            f"{tallest}px) — hidden pages are still being counted")
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


def test_fit_scroll_follows_rows_added_after_construction(window, qapp):
    """Qt caches a child's hint. The Update Center streams rows in as its
    scan finds them, so a FitScroll that only measured once would report
    the height it had while empty — which it did, until setWidget started
    watching for LayoutRequest."""
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    from frontend import widgets as W

    scroll = W.FitScroll(parent=window)
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    scroll.setWidget(host)
    scroll.show()
    qapp.processEvents()
    try:
        empty = scroll.sizeHint().height()
        for i in range(5):
            row = QLabel(f"row {i}")
            row.setFixedHeight(40)
            lay.addWidget(row)
        qapp.processEvents()
        filled = scroll.sizeHint().height()
        assert filled >= empty + 5 * 40 - 8, (
            f"hint went {empty} -> {filled} after adding 200px of rows")
    finally:
        scroll.setParent(None)
        scroll.deleteLater()
        qapp.processEvents()


def test_fit_scroll_can_be_squeezed_below_its_content(window, qapp):
    """minimumSizeHint is 0 on purpose: past the panel's cap the area must
    yield and scroll, not push the dialog past the window."""
    from frontend import widgets as W

    scroll = W.FitScroll(parent=window)
    assert scroll.minimumSizeHint().height() == 0


# ============================================================
#  FLOATING SURFACES - dialogs, popups, menus
# ============================================================
def test_every_menu_surface_composes_the_shared_material(qapp):
    """The command palette and every combo popup are the same object: a
    list floating over the page. They had drifted - the palette hovered on
    `card_hover` (then an accent-tinted CARD lift, which paints an indigo
    streak down a menu being scrubbed) while the combo popup had no hover
    rule at all and no item padding.

    THE SECOND HALF OF THAT GUARANTEE MOVED IN v15 rather than being
    dropped. It used to be spelled "and not card_hover", which only worked
    while the two tokens differed; the palette now answers hover with ONE
    neutral lift on every surface in the app, so card_hover IS row_hover
    and the old assertion would fail on the fix. What it was actually
    protecting - that a menu row never lifts toward the brand - is now
    asserted directly against the accent, which is the thing that must not
    appear.
    """
    for mode in ("dark", "light"):
        t = TH.ThemeManager(mode, None).t
        surfaces = {"palette": TH.palette_list_qss(t),
                    "combo": TH.filter_combo_qss(t, t["accent"])}
        for name, qss in surfaces.items():
            assert t["row_hover"] in qss, (
                f"{mode}/{name} does not use the neutral hover pill")
            assert TH.alpha(t["accent"], 0.05) not in qss, (
                f"{mode}/{name} hovers on an accent tint rather than the "
                "shared neutral pill")


def test_one_hover_weight_answers_the_pointer_everywhere(qapp):
    """A card and a menu row are two surfaces asking one question, and
    through v14 they answered it differently: the card lifted toward indigo
    at 0.085 while a row lifted toward white at 0.06. Same pointer, same
    meaning, two colours at two weights depending on what it happened to be
    over. v15 gives the app one hover."""
    for mode in ("dark", "light"):
        t = TH.ThemeManager(mode, None).t
        assert t["card_hover"] == t["row_hover"], (
            f"{mode}: the card and the menu row hover differently "
            f"({t['card_hover']} vs {t['row_hover']})")
        r, g, b, _a = TH._parse_color(t["card_hover"])
        assert r == g == b, (
            f"{mode}: the hover lift {t['card_hover']} carries a hue - a "
            "plate is raised by light, not by colour")


# ============================================================
#  THE COMMAND PALETTE
# ============================================================
def _palette(window):
    from frontend.menu_structure import iter_leaf_items
    from frontend.widgets import CommandPalette
    return CommandPalette(window, window.theme.t, list(iter_leaf_items()))


def _press(dialog, key, qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    dialog.eventFilter(dialog._search,
                       QKeyEvent(QEvent.Type.KeyPress, key,
                                 Qt.KeyboardModifier.NoModifier))
    qapp.processEvents()


def test_the_palette_groups_results_under_module_headers(window, qapp):
    """Results carry their module as a DIVIDER, not as trailing text.

    Rows used to be one formatted string — icon, title, category and the
    reason a catalog card matched, all concatenated — so the module name
    was repeated on every row and long titles were pushed into an
    ellipsis by context nobody was reading twice.

    Grouping must not cost relevance: groups are ordered by their own
    best-scoring member, so the top result overall is still the first row
    on screen. It has simply acquired a heading.
    """
    from PySide6.QtCore import Qt

    dialog = _palette(window)
    dialog.show()
    settle(qapp, 80)
    try:
        dialog._search.setText("re")
        settle(qapp, 80)
        rows = [(i, dialog._list.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(dialog._list.count())]
        headers = [i for i, data in rows if data == dialog._HEADER]
        assert headers, "no section dividers — the results are not grouped"
        assert headers[0] == 0, (
            "the list opens on a result rather than on the divider that "
            "names its group")
        # every result is under a header, and the first selectable row is
        # the one immediately after the first header — i.e. the top hit
        assert dialog._list.currentRow() == 1, (
            f"the palette opened on row {dialog._list.currentRow()}, not on "
            "the top result")
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


def test_palette_navigation_steps_over_its_own_dividers(window, qapp):
    """Section headers are items in the same list — that is what lets a
    divider scroll with the group it names — so Up/Down have to step OVER
    them. A keyboard-first surface where an arrow key can land on a
    non-selectable row is one where Enter sometimes does nothing.
    """
    from PySide6.QtCore import Qt

    dialog = _palette(window)
    dialog.show()
    settle(qapp, 80)
    try:
        dialog._search.setText("re")
        settle(qapp, 80)
        headers = {i for i in range(dialog._list.count())
                   if not dialog._is_result(i)}
        assert headers, "the fixture query no longer produces dividers"

        seen = []
        for _ in range(dialog._list.count() + 2):     # past the wrap point
            _press(dialog, Qt.Key.Key_Down, qapp)
            seen.append(dialog._list.currentRow())
        assert not (set(seen) & headers), (
            f"Down landed on divider rows {sorted(set(seen) & headers)}")
        assert seen[-1] in seen[:-1], (
            "Down never wrapped — the last result is a dead end")

        for _ in range(dialog._list.count() + 2):
            _press(dialog, Qt.Key.Key_Up, qapp)
            assert dialog._list.currentRow() not in headers, (
                "Up landed on a divider")

        # ...and Enter runs whatever is selected
        _press(dialog, Qt.Key.Key_Return, qapp)
        assert dialog.chosen_item is not None, (
            "Enter did not launch the selected result")
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


def test_the_palette_states_its_own_bindings(window, qapp):
    """The app's only keyboard-first surface shipped with no statement of
    what its keys do — Up/Down/Enter/Escape all worked and nothing said
    so, which makes a power feature discoverable by guessing."""
    from PySide6.QtWidgets import QLabel

    dialog = _palette(window)
    dialog.show()
    settle(qapp, 80)
    try:
        captions = " ".join(w.text() for w in dialog.findChildren(QLabel))
        for word in ("navigate", "run", "close"):
            assert word in captions, (
                f"the palette's hint bar does not mention {word!r}")
        dialog._search.setText("re")
        settle(qapp, 80)
        assert "result" in dialog._count.text(), (
            "the palette does not report how many results it found")
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


def test_every_floating_list_marks_selection_at_one_weight(qapp):
    """A row in a dropdown and a row in the command palette are the same
    object: the entry the list is currently reporting.

    Until v15.1 one function drew both, so they could not disagree. The
    palette's rows became item WIDGETS in that change — they have to be,
    to align a hint to the right edge of the row — which means its sheet
    can no longer compose menu_item_qss, and the weights would have been
    a copy from the moment they were written. They come off named
    constants instead, and this is what says so.
    """
    for mode in ("dark", "light"):
        t = TH.ThemeManager(mode, None).t
        tint = TH.alpha(t["accent"], TH.ROW_SELECT_TINT)
        line = TH.alpha(t["accent"], TH.ROW_SELECT_LINE)
        for name, qss in (("palette", TH.palette_list_qss(t)),
                          ("menu", TH.menu_item_qss(t, "QListWidget::item"))):
            assert tint in qss, (
                f"{mode}/{name} does not fill a selected row at "
                f"ROW_SELECT_TINT ({TH.ROW_SELECT_TINT})")
            assert line in qss, (
                f"{mode}/{name} does not outline a selected row at "
                f"ROW_SELECT_LINE ({TH.ROW_SELECT_LINE})")


def test_the_hover_pill_never_outweighs_a_real_selection(qapp):
    """Hover says "the pointer is here". Selection says something the list
    is reporting. If the pointer's weight ever reaches the selection's, the
    two become indistinguishable while scrubbing a menu."""
    for mode in ("dark", "light"):
        t = TH.ThemeManager(mode, None).t
        hover = TH._parse_color(t["row_hover"])[3]
        assert 0.03 <= hover <= 0.10, (
            f"{mode}: the hover pill is at {hover} - outside the weight at "
            "which it reads as a pointer rather than as a state")
        assert hover < 0.16, "hover has reached the selection tint's weight"


def test_a_floating_surface_casts_the_shared_two_layer_shadow(window, qapp):
    """Elevation is TWO layers, and one mechanism cannot supply both: a
    single shadow is either tight enough to seat a surface or soft enough
    to lift it, never both. The outer (ambient) layer is the
    QGraphicsDropShadowEffect asserted below; the inner (contact) layer is
    the ramp DepthCard paints just inside its own edge, which happens only
    if the panel was given its theme - and no dialog panel had been, since
    the depth tokens landed."""
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    from frontend import widgets as W        # noqa: F401  (fixture parity)

    dx, dy, blur, opacity = TH.DIALOG_SHADOW
    for name, build in _dialog_specs(window):
        dialog = build()
        effect = dialog.panel.graphicsEffect()
        assert isinstance(effect, QGraphicsDropShadowEffect), name
        assert effect.blurRadius() == blur, name
        assert (effect.xOffset(), effect.yOffset()) == (dx, dy), name
        assert effect.color().alpha() == round(255 * opacity), name
        assert dialog.panel._shadow is not None, (
            f"{name}'s panel was built without a theme, so it casts an "
            "outer shadow with no contact edge and no lit top face")
        assert dialog.panel._sheen is not None, name
        dialog.reject()
        dialog.deleteLater()
    qapp.processEvents()


# ============================================================
#  DIALOG FOOTERS
# ============================================================
#: `cancel.setFixedSize(96, 36)` — a hand-picked footer button box.
_FIXED_BUTTON_BOX = re.compile(r"setFixedSize\(\s*(\d+)\s*,\s*%d\s*\)"
                               % TH.CONTROL_H)


def test_no_footer_button_carries_a_hand_picked_width():
    """Widths came off ten different literals — 96, 110, 112, 120, 122,
    128, 132, 140, 150, 160, 170, 214 — one per button, for one element.

    A FIXED width is also wrong on its own terms wherever the label is
    not fixed, and several are not: the Update Center's CTA cycles through
    "Update Selected", "Update Selected (3)" and "Update All (14)" inside
    one 160px box, so the same button reads cramped at its longest label
    and adrift at its shortest. widgets.size_dialog_button replaces both
    halves with a floor plus the button's own sizeHint.
    """
    strays = []
    for module in ("main.py", "widgets.py"):
        source = open(os.path.join(_FRONTEND, module), encoding="utf-8").read()
        for i, line in enumerate(source.splitlines()):
            if _FIXED_BUTTON_BOX.search(line):
                strays.append(f"  {module}:{i + 1}  {line.strip()}")
    assert not strays, (
        f"{len(strays)} dialog button(s) still carry a hand-picked width — "
        "use widgets.size_dialog_button (or dialog_footer, which calls "
        "it):\n" + chr(10).join(strays))


@pytest.mark.parametrize("name", _DIALOG_NAMES)
def test_every_dialog_footer_shares_one_baseline(window, qapp, name):
    """A dialog's action bar is one SET of buttons, and a set has to look
    like one: same height, same floor, growing only for a label that
    genuinely needs the room.

    Measured on the ACTUAL widgets rather than on the source, because the
    source guard above can only see the literals it knows the shape of —
    a button sized through some other route would pass it and still ship
    a footer with two different heights in it.
    """
    from frontend import widgets as W

    spec = dict(_dialog_specs(window))
    dialog = spec[name]()
    dialog.show()
    qapp.processEvents()
    try:
        # Identified by the MARK widgets.size_dialog_button leaves, not by
        # geometry. Guessing from height would sweep up icon-only tools and
        # in-row controls, and would go quiet about the one button that had
        # actually drifted — a drifted button is exactly the one a
        # geometric guess stops recognising as a footer button.
        buttons = [b for b in dialog.panel.findChildren(QPushButton)
                   if b.property("dialogAction")]
        if not buttons:
            # The command palette is the one dialog with no action bar at
            # all: Enter runs the highlighted result and Escape closes it,
            # so a footer would be two buttons restating the keyboard. An
            # empty footer is a design decision here, not a drift.
            assert name == "CommandPalette", (
                f"{name} has no dialog action buttons — either it hand-rolled "
                "its footer instead of using widgets.dialog_footer, or it "
                "genuinely has none and belongs in this exemption")
            return
        wrong_height = [(b.text(), b.height()) for b in buttons
                        if b.isVisible() and b.height() != TH.CONTROL_H]
        assert not wrong_height, (
            f"{name}: footer button(s) off CONTROL_H={TH.CONTROL_H}: "
            f"{wrong_height}")
        too_narrow = [(b.text(), b.width()) for b in buttons
                      if b.isVisible() and b.width() < W._FOOTER_BTN_W]
        assert not too_narrow, (
            f"{name}: footer button(s) under the {W._FOOTER_BTN_W}px floor: "
            f"{too_narrow}")
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


class TestChipStrip:
    """The scrolling pill row (catalog tabs, DNS profiles).

    Both halves of its geometry shipped broken once, in opposite
    directions: the strip first squeezed its pills because the scrollbar
    took its space out of a viewport sized to the pills alone, and the fix
    for that (pinning the row with QLayout.setAlignment) stopped the
    scroll area from ever learning the row overflowed — leaving the fifth
    tab clipped and unreachable, with no scrollbar to say so.
    """

    def _strip(self, dialog):
        from PySide6.QtWidgets import QScrollArea
        from frontend.widgets import _CHIP_H, _CHIP_LANE
        strips = [s for s in dialog.findChildren(QScrollArea)
                  if s.height() == _CHIP_H + _CHIP_LANE]
        assert strips, "the catalog's tab strip is not a _chip_strip"
        return strips[0]

    #: Narrow enough that the catalog's five tabs cannot fit whatever the
    #: font metrics are on the machine running this. The overflow behaviour
    #: is the thing under test, and since the filter field moved off this
    #: row (see test_the_filter_field_has_its_own_row) the tabs DO fit at
    #: the app's own minimum window — so the overflow has to be forced
    #: rather than waited for, or these two assertions quietly stop testing
    #: anything on a machine with a slightly narrower font.
    _FORCE_OVERFLOW_W = 240

    def test_the_scrollbar_lane_is_exactly_reserved(self, window, qapp):
        """Viewport == pill height WHILE THE BAR IS SHOWING: the lane the
        strip adds and the space Qt takes for the bar have to be the same
        number, or the pills shift by the difference the moment the row
        overflows."""
        from frontend.widgets import _CHIP_H
        dialog = dict(_dialog_specs(window))["SoftwareCatalogDialog"]()
        dialog.show()
        qapp.processEvents()
        strip = self._strip(dialog)
        strip.setFixedWidth(self._FORCE_OVERFLOW_W)
        qapp.processEvents()
        assert strip.horizontalScrollBar().isVisible(), (
            "the strip was squeezed below its content and still shows no "
            "scrollbar — the rest of this assertion would be vacuous")
        assert strip.viewport().height() == _CHIP_H, (
            f"viewport {strip.viewport().height()}px against a {_CHIP_H}px "
            "pill — the lane and the scrollbar disagree")
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()

    def test_an_overflowing_strip_can_actually_be_scrolled(self, window, qapp):
        """A row wider than its viewport MUST scroll: a clipped tab with no
        scrollbar is a filter the user simply cannot reach.

        This used to squeeze the WINDOW to the app minimum and rely on the
        five tabs not fitting the panel. They fit now — the filter field
        that used to take ~190px out of this row moved to its own row above
        it — so the strip is squeezed directly instead. The property is
        unchanged and the trigger is no longer a coincidence of font
        metrics."""
        dialog = dict(_dialog_specs(window))["SoftwareCatalogDialog"]()
        dialog.show()
        qapp.processEvents()
        strip = self._strip(dialog)
        strip.setFixedWidth(self._FORCE_OVERFLOW_W)
        qapp.processEvents()
        assert strip.horizontalScrollBar().maximum() > 0, (
            "a strip narrower than its own pills does not scroll — its "
            "overflowing tabs are unreachable")
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()

    def test_the_filter_field_has_its_own_row(self, window, qapp):
        """The field and the tabs are TWO rows, and this is the assertion
        that used to say the opposite.

        They shared one line, with the field pinned to the right of a
        SCROLLING strip. A scroll area takes the width it is given and
        reports overflow instead of asking for more, so the two never
        competed honestly: the strip surrendered the field's ~190px and
        put a tab under the scrollbar at every window size, while the field
        itself was 180px on a panel three times that wide. Both are fixed
        by the split, and both would come back the moment someone merged
        the rows again — so what is pinned here is the separation itself,
        the field spanning the content width, and the two never overlapping.
        """
        dialog = dict(_dialog_specs(window))["SoftwareCatalogDialog"]()
        dialog.show()
        qapp.processEvents()
        strip = self._strip(dialog)
        field = dialog._search

        field_rect = field.rect().translated(
            field.mapTo(dialog.panel, field.rect().topLeft()))
        strip_rect = strip.rect().translated(
            strip.mapTo(dialog.panel, strip.rect().topLeft()))
        assert not field_rect.intersects(strip_rect), (
            f"the filter field {field_rect} overlaps the tab strip "
            f"{strip_rect} — they are back on one row")
        assert field_rect.bottom() <= strip_rect.top(), (
            "the filter field is not above the tab strip")
        assert field.width() == strip.width(), (
            f"the field is {field.width()}px against a {strip.width()}px "
            "strip — it no longer spans the content column")
        tab = next(iter(dialog._tab_buttons.values()))
        assert tab.height() == field.height(), (
            "a tab pill and the filter field are both controls and must "
            "share one height")
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()


#: Widgets that paint PLATFORM chrome unless they are told not to — a
#: sunken Fusion frame around a stack, a stock Windows scrollbar with
#: arrow buttons on a scroll area or a self-scrolling list. Each one
#: shipped visible in at least one surface: the Office wizard's steps, the
#: Update Center's and Startup Manager's state pages (frames), the Welcome
#: and category card grids (bars) and the Ctrl+K palette (bar).
_PLATFORM_CHROME = ("QStackedWidget", "QScrollArea", "QListWidget")


def _unstyled_chrome(root) -> list[str]:
    from PySide6.QtWidgets import QListWidget, QScrollArea, QStackedWidget
    out = []
    for cls in (QStackedWidget, QScrollArea, QListWidget):
        for widget in root.findChildren(cls):
            if not widget.styleSheet():
                out.append(f"{cls.__name__} in {type(widget.parent()).__name__}")
    return out


def test_no_surface_shows_stock_platform_chrome(window, qapp):
    """Every stack, scroll area and list states its own style.

    These are the only widgets in the app that render platform chrome by
    default, and an unstyled one does not look broken — it looks like
    Windows, in the middle of a surface that looks like Pulse.
    """
    offenders = {}
    for name, build in _dialog_specs(window):
        dialog = build()
        found = _unstyled_chrome(dialog)
        if found:
            offenders[name] = found
        dialog.reject()
        dialog.deleteLater()
    for page in [window.welcome, *window.pages]:
        found = _unstyled_chrome(page)
        if found:
            offenders[type(page).__name__] = found
    qapp.processEvents()
    assert not offenders, f"unstyled platform chrome: {offenders}"


def test_filtering_dialogs_declare_an_empty_state(window, qapp):
    """A surface that can filter itself to nothing must SAY so. A blank
    bordered box is indistinguishable from a broken dialog — the defect
    the command palette shipped with until Phase 0."""
    for name in ("SoftwareCatalogDialog", "CommandPalette"):
        dialog = dict(_dialog_specs(window))[name]()
        assert getattr(dialog, "_empty", None) is not None, (
            f"{name} can filter to zero results but has no empty state")
        dialog.reject()
        dialog.deleteLater()
    qapp.processEvents()


# ============================================================
#  THE PLAQUE AND CONTROL SCALES (v14)
# ============================================================
def test_one_module_is_one_plaque_size_everywhere():
    """A card's icon well and the sidebar entry that OPENS that card are
    the same object seen twice. They were built by two pieces of code that
    agreed on the tint and on nothing else, so they shipped at 36px and
    30px — a six-pixel difference between two views of one thing, which
    nobody chose and nobody could have noticed side by side because they
    are never side by side.

    IconPlaque's widget is deliberately LARGER than the scale: it reserves
    _PAD on each side for the halo to bleed outward into (see the note
    there), so the WELL it paints is what has to match, not the footprint.
    """
    from frontend.widgets import GlassCard, IconPlaque, NavButton
    assert NavButton._PLAQUE == TH.PLAQUE_SIZE, (
        f"the sidebar plaque is {NavButton._PLAQUE}px against the scale's "
        f"{TH.PLAQUE_SIZE}px")
    well = GlassCard._PLAQUE - 2 * IconPlaque._PAD
    assert well == TH.PLAQUE_SIZE, (
        f"the card's plaque well measures {well}px (a "
        f"{GlassCard._PLAQUE}px widget less {IconPlaque._PAD}px of halo "
        f"reserve each side) against the scale's {TH.PLAQUE_SIZE}px")


def test_the_nav_label_clears_the_plaque_it_sits_beside():
    """The plaque is PAINTED and the label is QSS text, so nothing in Qt
    keeps the two apart — the left padding is the only thing standing
    between a 36px well and the title running over it. Widening the
    plaque without widening the padding is a silent overlap."""
    from frontend.widgets import NavButton
    qss = TH.nav_button_qss(TH.tokens("dark"))
    match = re.search(r"padding-left:\s*(\d+)px", qss)
    assert match, "nav_button_qss no longer declares a left padding"
    assert int(match.group(1)) >= NavButton._PLAQUE_X + TH.PLAQUE_SIZE, (
        f"nav labels start at {match.group(1)}px, inside the plaque that "
        f"ends at {NavButton._PLAQUE_X + TH.PLAQUE_SIZE}px")


#: Heights something may be fixed to that are NOT the control scale, each
#: because it is a different KIND of object rather than a primary control
#: that got away. Enumerated (not a range) so a genuinely new number has
#: to be argued for here before it can ship:
#:
#:    22  status/state chip     26  rail tool, Stop button
#:    24  update badge          28  drawer chevron, rail button
#:    30  caption button        34  the page accent rail
#:    44  the Activity rail     46  nav row, search field
#:    50  wizard link row       96  dashboard hero
#:   172  live console         200  a scrolled sub-list
#:
#: Deliberately pruned to what the tree actually uses — a list carrying
#: values nothing sets is a list that exempts the next stray by accident.
#:
#: v15 RETIRED 32 AND RE-LABELLED 30. The two 32px entries were the
#: category page's filter combo and the Storage Analyzer's drive picker —
#: dropdowns, which are operable controls and now sit on the scale with
#: every other one. 30 survives for exactly one object: the title bar's
#: 40x30 caption buttons, whose geometry is Windows', not ours. (The
#: chip-strip pill it used to name is CONTROL_H now; see widgets._CHIP_H.)
_CONTROL_HEIGHT_EXEMPT = {22, 24, 26, 28, 30, 34, 44, 46, 50,
                          96, 172, 200}


def test_primary_controls_share_one_height():
    """The fourth scale, held to the same standard as SPACE, RADIUS and
    TYPE. Dialog action bars had converged on 36 by convention, and the
    two controls that had NOT — a 38px "Optimize Startup" and a 42px "Run
    as Administrator" — were the only buttons in the app that looked
    hand-placed. A convention nothing names is a convention that drifts,
    which is the argument every other scale in this file already made.
    """
    literal = re.compile(r"setFixedHeight\((\d+)\)|setFixedSize\(\d+,\s*(\d+)\)")
    strays = []
    for module in ("main.py", "widgets.py"):
        path = os.path.join(_FRONTEND, module)
        for i, line in enumerate(open(path, encoding="utf-8").read().splitlines()):
            for match in literal.finditer(line):
                px = int(match.group(1) or match.group(2))
                if px == TH.CONTROL_H or px in _CONTROL_HEIGHT_EXEMPT or px <= 14:
                    continue
                strays.append(f"  {module}:{i + 1}  {line.strip()}")
    assert not strays, (
        f"{len(strays)} control height(s) off the scale "
        f"(CONTROL_H={TH.CONTROL_H}, exempt={sorted(_CONTROL_HEIGHT_EXEMPT)}):\n"
        + "\n".join(strays))


def test_the_control_height_clears_the_type_it_carries():
    """A named height is only worth having if it FITS. The tallest label a
    primary button carries is the `body` role, and a control has to give
    it room to breathe on both sides or the scale is just a smaller
    number that clips."""
    assert TH.CONTROL_H >= TH.TYPE["body"] + 2 * TH.SPACE["sm"], (
        f"CONTROL_H {TH.CONTROL_H} leaves under {TH.SPACE['sm']}px above "
        f"and below a {TH.TYPE['body']}px label")
