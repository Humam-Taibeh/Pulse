"""
Navigation and engine performance contract.

The defect these pin down was reported as "switching between the four
modules feels laggy, heavy, like the app is freezing", and it was two
independent things wearing one symptom.

1. THE SWITCH WAS NOT SLOW — THE ENTRANCE WAS. Every page is built up
   front and lives in the QStackedWidget, so raising one measured 1.7 ms
   warm. What followed it was a per-card staggered cascade whose length
   was `card_index * CASCADE_GAP`: unbounded in page density, so the
   14-card module took 508 ms to finish assembling itself, EVERY visit,
   including the tenth. Measured end to end, warm, round-robin over all
   four modules: 399.8 ms mean / 523.7 ms worst before, 31.9 / 34.8 after.

2. THE AMBIENT WASH WAS SATURATING THE GUI THREAD. AmbientGlow is the
   bottom widget in the shell and everything above it is translucent by
   design, so its update() dirties the whole window and Qt repaints every
   card, panel and chrome element on top of it: 18.5 ms a frame, of which
   the glow's own paint is 2.7. At the old 36 ms interval that blocked the
   main thread 46.2% of wall time at idle, in blocks of up to 31 ms —
   which is what every click, including a nav click, had to queue behind.

Both are the kind of regression that reads as "the machine is slow"
rather than as a bug, so the contracts are asserted here rather than left
to be noticed.
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QEventLoop

from conftest import settle
from frontend import theme as TH
from frontend.animations import (
    CASCADE_BUDGET_MS, CASCADE_GAP, CASCADE_MS, CascadeAnimator,
)
from frontend.main import CategoryPage
from frontend.menu_structure import CATEGORIES


def _page(qapp, index: int = 1) -> CategoryPage:
    page = CategoryPage(CATEGORIES[index], TH.ThemeManager().t)
    page.resize(1200, 900)
    qapp.processEvents()
    return page


# ============================================================
#  1. THE ENTRANCE IS BUDGETED, NOT PER-CARD
# ============================================================
class TestCascadeBudget:
    """The entrance may cost what it likes on a small page; what it may
    never do is get LONGER because a module is denser."""

    def test_a_short_page_keeps_the_hand_tuned_rhythm(self):
        assert CascadeAnimator.wave_stagger([0, 1, 2]) == CASCADE_GAP

    @pytest.mark.parametrize("span", range(1, 40))
    def test_no_page_can_exceed_the_stagger_budget(self, span):
        waves = list(range(span + 1))
        gap = CascadeAnimator.wave_stagger(waves)
        assert gap * span <= CASCADE_BUDGET_MS + 1e-9, (
            f"{span + 1} waves stagger out to {gap * span:.0f} ms — the "
            "entrance is unbounded in page size again, which is exactly "
            "the 508 ms Utilities & Tools switch")

    def test_a_single_wave_never_divides_by_zero(self):
        assert CascadeAnimator.wave_stagger([0]) == CASCADE_GAP
        assert CascadeAnimator.wave_stagger([]) == CASCADE_GAP

    def test_the_whole_entrance_fits_one_bounded_envelope(self):
        """The number that matters to a user: worst case from click to the
        last card being lit, on the densest page the app can grow."""
        waves = list(range(200))
        worst = CascadeAnimator.wave_stagger(waves) * 199 + CASCADE_MS
        assert worst <= CASCADE_BUDGET_MS + CASCADE_MS


class TestEntranceWaves:
    """The cascade animates the layout that exists — visible cards,
    grouped by the grid row they are actually drawn on."""

    def test_cards_sharing_a_row_share_a_wave(self, qapp):
        page = _page(qapp)
        page._relayout(3)
        cards, waves = page.entrance_waves()
        assert len(cards) == len(waves)
        rows = {}
        for card, wave in zip(cards, waves):
            rows.setdefault(page._grid.getItemPosition(
                page._grid.indexOf(card))[0], set()).add(wave)
        for row, assigned in rows.items():
            assert len(assigned) == 1, (
                f"grid row {row} is split across waves {assigned} — the "
                "entrance is staggering per card again")

    def test_there_is_exactly_one_wave_per_occupied_grid_row(self, qapp):
        """The exact contract. Note this is NOT `cards / columns`: a band
        never shares a row with the band below it, so a page of small bands
        legitimately produces more waves than the column count alone
        implies. What must hold is that a wave IS a row."""
        page = _page(qapp)
        page._relayout(3)
        cards, waves = page.entrance_waves()
        assert len(cards) > 6, "test needs a dense page to be meaningful"
        occupied = {page._grid.getItemPosition(page._grid.indexOf(c))[0]
                    for c in cards}
        assert max(waves) + 1 == len(occupied), (
            f"{max(waves) + 1} waves over {len(occupied)} occupied rows — "
            "the entrance is no longer staggering by row")
        assert max(waves) + 1 < len(cards), (
            "one wave per card is the unbounded per-card stagger again")

    def test_hidden_cards_are_neither_animated_nor_given_a_slot(self, qapp):
        """A filtered-out card used to be staged (effect installed, position
        driven, effect torn down) AND to consume a stagger slot, so a page
        filtered down to two cards still waited out a full entrance."""
        page = _page(qapp)
        page._relayout(3)
        page._visible = page.cards[:2]
        for i, card in enumerate(page.cards):
            card.setVisible(i < 2)
        cards, waves = page.entrance_waves()
        assert cards == page.cards[:2]
        assert max(waves) == 0, "two cards in one row is one wave"


# ============================================================
#  2. A PAGE IS REVEALED ONCE; RETURNING TO IT IS INSTANT
# ============================================================
@pytest.mark.native
class TestInstantRevisit:

    def test_returning_to_a_module_runs_no_entrance(self, window, qapp):
        window.open_category(0)
        settle(qapp, 450)
        window.open_category(1)
        settle(qapp, 450)

        window.open_category(0)
        for _ in range(8):
            qapp.processEvents()
        assert window.cascade._group is None, (
            "a module the user has already read is re-animating on every "
            "return — that is latency, not polish")
        assert all(c.graphicsEffect() is None for c in window.pages[0].cards)

    def test_every_module_is_revealed_at_most_once(self, window, qapp):
        for _ in range(3):
            for index in range(len(CATEGORIES)):
                window.open_category(index)
                settle(qapp, 60)
        assert window._revealed == set(range(len(CATEGORIES)))

    def test_a_warm_switch_settles_inside_a_frame_budget(self, window, qapp):
        """The user-facing number. Measured the way a user experiences it:
        click, then wait until the app stops doing work."""
        for index in range(len(CATEGORIES)):
            window.open_category(index)
            settle(qapp, 450)
        window.go_home()
        settle(qapp, 300)

        worst = 0.0
        for lap in range(3):
            for index in range(len(CATEGORIES)):
                start = time.perf_counter()
                window.open_category(index)
                last = start
                while (time.perf_counter() - last) < 0.040:
                    if qapp.processEvents(
                            QEventLoop.ProcessEventsFlag.AllEvents, 2):
                        last = time.perf_counter()
                    if (time.perf_counter() - start) > 1.5:
                        break
                worst = max(worst, (last - start) * 1000.0)
        assert worst < 150.0, (
            f"worst warm module switch settled in {worst:.0f} ms — this "
            "measured 399.8 ms mean / 523.7 ms worst before the entrance "
            "was budgeted")


# ============================================================
#  3. THE GRID DOES NOT ACCUMULATE ROWS
# ============================================================
class TestGridRelayout:
    """The filtered-empty label used to be parked at row 900, which made
    every page a 901-row grid, and _relayout cleared stretches by sweeping
    `range(rowCount() + 1)` — a call that EXTENDS the grid when it runs
    past the end. So every relayout added a row, forever: observed live at
    904 and climbing by one per resize step."""

    def test_repeated_relayouts_do_not_grow_the_grid(self, qapp):
        page = _page(qapp)
        page._relayout(3)
        before = page._grid.rowCount()
        for _ in range(40):
            page._cols = 0
            page._applied_unit = -1
            page._relayout(3)
        assert page._grid.rowCount() == before, (
            f"the grid grew from {before} to {page._grid.rowCount()} rows "
            "over 40 relayouts — the row leak is back")

    def test_the_grid_is_only_as_tall_as_its_content(self, qapp):
        page = _page(qapp)
        page._relayout(3)
        assert page._grid.rowCount() < 40, (
            f"{page._grid.rowCount()} rows for {len(page.cards)} cards — "
            "something is parked far below the content again")

    def test_the_stretch_sweep_stays_bounded(self, qapp):
        page = _page(qapp)
        for cols in (1, 2, 3, 4, 2, 1):
            page._cols = 0
            page._applied_unit = -1
            page._relayout(cols)
            assert page._stretch_high <= page._grid.rowCount(), (
                "the high-water mark has drifted past the grid it bounds")

    def test_exactly_one_row_carries_the_stretch(self, qapp):
        """The anchoring rule the whole layout depends on: content rows take
        none, one trailing row takes it all."""
        page = _page(qapp)
        page._cols = 0
        page._relayout(3)
        stretched = [r for r in range(page._grid.rowCount() + 1)
                     if page._grid.rowStretch(r)]
        assert len(stretched) == 1, (
            f"rows {stretched} all carry stretch — a short page will float "
            "in the middle of the canvas instead of anchoring to the top")

    def test_the_remeasure_is_coalesced_not_queued_per_relayout(self, qapp):
        """A drag-resize runs _relayout per resize step. Each one used to
        queue its own singleShot invalidate+activate, so dozens of redundant
        full layout passes landed the moment the drag stopped."""
        page = _page(qapp)
        for _ in range(25):
            page._cols = 0
            page._applied_unit = -1
            page._relayout(3)
        assert page._remeasure.isActive()
        fired = []
        page._remeasure.timeout.connect(lambda: fired.append(1))
        settle(qapp, 120)
        assert len(fired) == 1, (
            f"{len(fired)} re-measures queued for 25 relayouts")


class TestEmptyState:
    """Moving the label off row 900 must not cost it its job."""

    def test_it_sits_after_the_content(self, qapp):
        page = _page(qapp)
        page._cols = 0
        page._relayout(3)
        index = page._grid.indexOf(page._empty)
        assert index >= 0, "the empty-state label left the grid entirely"
        row = page._grid.getItemPosition(index)[0]
        last = max(page._grid.getItemPosition(page._grid.indexOf(c))[0]
                   for c in page._visible)
        assert row > last, (
            f"the empty-state label is on row {row}, inside content that "
            f"runs to row {last}")

    def test_a_filter_matching_nothing_still_says_so(self, qapp):
        page = _page(qapp)
        applied = next(i for i, (_label, key) in enumerate(page.FILTERS)
                       if key == "applied")
        page._filter.setCurrentIndex(applied)
        qapp.processEvents()
        assert not page._visible, "test needs a filter that matches nothing"
        assert page._empty.isVisibleTo(page), (
            "a filter matched nothing and the page renders blank — "
            "indistinguishable from a broken module")

    def test_it_hides_again_when_the_filter_clears(self, qapp):
        page = _page(qapp)
        applied = next(i for i, (_label, key) in enumerate(page.FILTERS)
                       if key == "applied")
        page._filter.setCurrentIndex(applied)
        qapp.processEvents()
        page._filter.setCurrentIndex(0)
        qapp.processEvents()
        assert page._visible
        assert not page._empty.isVisibleTo(page)


# ============================================================
#  4. THE AMBIENT WASH YIELDS THE GUI THREAD
# ============================================================
@pytest.mark.native
class TestAmbientGovernor:

    def test_the_cadence_is_locked_to_the_layer_cadence(self, window):
        """The arithmetic that makes the rate free rather than a quality
        cut: the orb composite is only rebuilt every _LAYER_MS, so ticking
        faster than that repaints an IDENTICAL aurora — at the old 36 ms
        interval, two of every three full-window repaints were duplicates."""
        glow = window._glow
        assert glow._INTERVAL_MS == glow._LAYER_MS

    def test_it_backs_off_when_the_thread_is_contended(self, window):
        glow = window._glow
        original = glow._interval
        try:
            glow._interval = float(glow._INTERVAL_MS)
            glow._govern(60.0)
            assert glow._interval > glow._INTERVAL_MS
        finally:
            glow._interval = original

    def test_the_back_off_has_a_ceiling(self, window):
        glow = window._glow
        original = glow._interval
        try:
            for _ in range(80):
                glow._govern(900.0)
            assert glow._interval == glow._MAX_INTERVAL_MS, (
                "the ambient field can be starved indefinitely — at some "
                "point the drift visibly steps")
        finally:
            glow._interval = original

    def test_it_recovers_to_the_base_rate_when_the_thread_is_free(self, window):
        glow = window._glow
        original = glow._interval
        try:
            glow._interval = float(glow._MAX_INTERVAL_MS)
            for _ in range(200):
                glow._govern(0.0)
            assert glow._interval == pytest.approx(float(glow._INTERVAL_MS))
        finally:
            glow._interval = original

    def test_it_never_runs_faster_than_its_base_cadence(self, window):
        glow = window._glow
        original = glow._interval
        try:
            for _ in range(200):
                glow._govern(0.0)
            assert glow._interval >= glow._INTERVAL_MS
        finally:
            glow._interval = original


@pytest.mark.native
class TestAmbientQuietDuringNavigation:
    """A page transition must not be sharing the GUI thread with the wash.

    This class used to be TestAmbientDefer, and it tested the mechanism —
    defer() pushing a deadline out, the field skipping frames until it
    passed, then picking itself back up unaided. As of v10.5 the field is
    static (widgets._AmbientSimulation.STATIC), so there is no frame to
    skip and defer() is a no-op.

    The GUARANTEE the mechanism existed to provide is the thing worth
    keeping, and it is now unconditional rather than scheduled: the wash
    never lands an 18.5ms full-window repaint in the middle of a
    transition, because it never repaints on its own at all. Tested at the
    same seam as before — a real module switch on a real window — so a
    regression that reintroduced ambient motion would fail HERE, where the
    user would actually have felt it, and not only in the unit-level
    stillness tests in test_ambient.py.
    """

    #: What a settled transition is allowed to have cost the wash. A page
    #: swap genuinely moves opaque surfaces over it, and set_occluders is
    #: then OBLIGED to dirty the strips that just became visible — a wash
    #: that declined would leave the old page's card footprints as holes.
    #: The number is small and, crucially, does not scale with how long the
    #: transition takes: an animated field billed one full-window repaint
    #: per 100ms for the whole 360ms first-visit cascade and kept billing
    #: afterwards.
    _OCCLUDER_REPAINT_CEILING = 8

    def _count_repaints(self, glow, qapp, action, ms: int) -> int:
        painted = []
        original = glow.update
        glow.update = lambda *a, **k: painted.append(1)
        try:
            action()
            settle(qapp, ms)
        finally:
            glow.update = original
        return len(painted)

    def test_a_module_switch_costs_the_wash_almost_nothing(self, window, qapp):
        glow = window._glow
        window.go_home()
        settle(qapp, 250)
        try:
            count = self._count_repaints(
                glow, qapp, lambda: window.open_category(1), 600)
            assert count <= self._OCCLUDER_REPAINT_CEILING, (
                f"{count} ambient repaint(s) during a module switch — each "
                "re-rasterises every translucent surface above the wash, "
                "which is the hitch deferral was introduced to remove")
        finally:
            window.go_home()
            settle(qapp, 200)

    def test_the_wash_goes_silent_once_the_transition_lands(self, window, qapp):
        """The half that separates 'the layout moved it' from 'it is
        animating'. Occluder churn stops when the page settles; a timer
        would not, and this is where the difference shows."""
        glow = window._glow
        window.go_home()
        settle(qapp, 250)
        try:
            window.open_category(1)
            settle(qapp, 700)                  # let the switch fully land
            count = self._count_repaints(glow, qapp, lambda: None, 700)
            assert count == 0, (
                f"{count} ambient repaint(s) in 700ms AFTER a transition had "
                "settled — nothing in the layout is still moving, so the "
                "field is animating itself")
        finally:
            window.go_home()
            settle(qapp, 200)

    def test_a_first_visit_cascade_costs_the_wash_almost_nothing(
            self, window, qapp):
        """The worst case: a module opened for the first time runs the
        entrance cascade, the longest stretch of GUI-thread work the app
        ever schedules (PAGE_FADE_MS, then CASCADE_BUDGET_MS + CASCADE_MS).
        It was also the deferral's longest hold — 360ms during which the
        animated field wanted three full-window repaints."""
        glow = window._glow
        window._revealed.clear()
        window.go_home()
        settle(qapp, 250)
        try:
            count = self._count_repaints(
                glow, qapp, lambda: window.open_category(2), 800)
            assert count <= self._OCCLUDER_REPAINT_CEILING, (
                f"{count} ambient repaint(s) across a first-visit cascade")
        finally:
            window.go_home()
            settle(qapp, 200)

    def test_deferring_arms_nothing(self, window):
        """main.py still calls defer() around every transition and cascade.
        Those calls are asserting "the GUI thread is about to be busy",
        which stays true and stays worth saying — but they must not leave
        state behind on a field that has no frames to defer."""
        glow = window._glow
        glow.defer(800)
        glow.defer(20)
        assert glow._defer_until == 0.0
        assert not glow._timer.isActive()
