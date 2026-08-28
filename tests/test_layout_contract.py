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
        assert dialog.panel.height() < W._SELECTOR_HEIGHT_MIN, (
            f"{hub['title']} is {dialog.panel.height()}px tall - taller than "
            "the SELECTOR band's own floor, so it is not hugging anything")
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
#  FLOATING SURFACES - dialogs, popups, menus
# ============================================================
def test_every_menu_surface_composes_the_shared_material(qapp):
    """The command palette and every combo popup are the same object: a
    list floating over the page. They had drifted - the palette hovered on
    `card_hover` (the accent-tinted CARD lift, which paints an indigo
    streak down a menu being scrubbed) while the combo popup had no hover
    rule at all and no item padding."""
    for mode in ("dark", "light"):
        t = TH.ThemeManager(mode, None).t
        surfaces = {"palette": TH.command_list_qss(t),
                    "combo": TH.filter_combo_qss(t, t["accent"])}
        for name, qss in surfaces.items():
            assert t["row_hover"] in qss, (
                f"{mode}/{name} does not use the neutral hover pill")
            assert t["card_hover"] not in qss, (
                f"{mode}/{name} still hovers on the accent-tinted card lift")


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

    def test_the_scrollbar_lane_is_exactly_reserved(self, window, qapp):
        """Viewport == pill height: the lane the strip adds and the space
        Qt takes for the bar have to be the same number, or the pills
        shift by the difference the moment the row overflows."""
        from frontend.widgets import _CHIP_H
        dialog = dict(_dialog_specs(window))["SoftwareCatalogDialog"]()
        dialog.show()
        qapp.processEvents()
        strip = self._strip(dialog)
        assert strip.viewport().height() == _CHIP_H, (
            f"viewport {strip.viewport().height()}px against a {_CHIP_H}px "
            "pill — the lane and the scrollbar disagree")
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()

    def test_an_overflowing_strip_can_actually_be_scrolled(self, window, qapp):
        """At the app's minimum width the five tabs cannot all fit, so the
        strip MUST scroll: a clipped tab with no scrollbar is a filter the
        user simply cannot reach."""
        from frontend.widgets import refit_dialog
        original = window.size()
        window.resize(_MIN_W, _MIN_H)
        qapp.processEvents()
        try:
            dialog = dict(_dialog_specs(window))["SoftwareCatalogDialog"]()
            dialog.resize(window.size())
            dialog.show()
            qapp.processEvents()
            refit_dialog(dialog)
            qapp.processEvents()
            strip = self._strip(dialog)
            assert strip.horizontalScrollBar().maximum() > 0, (
                "the tab strip does not scroll at the minimum window size — "
                "its overflowing tabs are unreachable")
            dialog.reject()
            dialog.deleteLater()
            qapp.processEvents()
        finally:
            window.resize(original)
            qapp.processEvents()

    def test_the_filter_row_shares_one_top_edge(self, window, qapp):
        """Tabs and search field are one control row and must read as one:
        the field is aligned to the strip's TOP, not its centre, because
        the strip is taller than its pills by the scrollbar lane."""
        dialog = dict(_dialog_specs(window))["SoftwareCatalogDialog"]()
        dialog.show()
        qapp.processEvents()
        strip = self._strip(dialog)
        panel = dialog.panel
        tab = next(iter(dialog._tab_buttons.values()))
        tab_top = tab.mapTo(panel, tab.rect().topLeft()).y()
        field_top = dialog._search.mapTo(
            panel, dialog._search.rect().topLeft()).y()
        assert tab_top == field_top, (
            f"the tabs start at y={tab_top} and the filter field at "
            f"y={field_top} — the row is misaligned by "
            f"{abs(tab_top - field_top)}px")
        assert tab.height() == dialog._search.height()
        assert strip.width() > 0
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
#:    24  update badge          28  drawer chevron
#:    30  chip-strip pill       32  inline drive selector
#:    34  the page accent rail  44  the Activity rail itself
#:    46  nav row, search field 50  wizard link row
#:    96  dashboard hero       172  live console
#:   200  a scrolled sub-list
#:
#: Deliberately pruned to what the tree actually uses — a list carrying
#: values nothing sets is a list that exempts the next stray by accident.
_CONTROL_HEIGHT_EXEMPT = {22, 24, 26, 28, 30, 32, 34, 44, 46, 50,
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
