"""
The bloatware dialog's batch/filter toolbar, and the module header's
applied ratio (v10.14).

WHY A FILTER FIELD IS CORRECT HERE AND WAS REMOVED ELSEWHERE. Two surfaces
in this app dropped a text filter on a stated rule — a field earns its row
by the size of what it narrows, and SoftwareCatalogDialog's fifteen grouped
rows behind a counted chip strip did not earn one. The purge catalog is 48
entries across four sections, and the question it gets asked is "does Pulse
remove <this app>?", which is a lookup rather than a browse. The other half
of that removal is pinned below too: the field must not take focus on open,
because the dialog has to open with the keyboard on the LIST.

WHY THE PILLS ARE SPLIT. "Select All Bloatware" was one control over two
different decisions — an app REGISTERED on this machine, and a Start-menu
tile Windows has not downloaded yet. The safety rule both inherit is the
one _select_all already carried: no bulk control may ever tick the
optional Xbox tier.
"""
from __future__ import annotations

import pytest

from conftest import settle, show_dialog, wait_until
from frontend import theme as TH
from frontend.menu_structure import CATEGORIES


def _entry(entry_id, name, group="promo", presence="installed", optional=False):
    detected = presence != "absent"
    return {"Id": entry_id, "Name": name, "Group": group,
            "Note": "What removing this one costs, in one sentence.",
            "Detected": detected, "Presence": presence, "Optional": optional,
            "Installed": [], "Provisioned": [], "Desktop": [], "Startup": []}


#: One row per presence tier, plus an optional one that is INSTALLED — the
#: case a pill could sweep if it went by detection rather than by tier.
_ENTRIES = [
    _entry("BingWeather", "Weather", presence="installed"),
    _entry("Clipchamp", "Clipchamp", presence="installed"),
    _entry("DisneyPlus", "Disney+", presence="pinned"),
    _entry("Spotify", "Spotify Stub", presence="staged"),
    _entry("TikTok", "TikTok", presence="absent"),
    _entry("KLiteCodec", "K-Lite Codec Pack", group="codec", presence="installed"),
    _entry("XboxGamingOverlay", "Xbox Game Bar", group="gaming",
           presence="installed", optional=True),
]


@pytest.fixture
def purge(window, qapp, monkeypatch):
    from frontend.widgets import BloatwarePurgeDialog

    # No live scan: what is under test is what the dialog does with an
    # inventory, not which packages this machine happens to carry.
    monkeypatch.setattr(BloatwarePurgeDialog, "_start_scan", lambda self: None)
    dialog = BloatwarePurgeDialog(window, "", window.theme.t)
    show_dialog(qapp, dialog)
    dialog._render([dict(e) for e in _ENTRIES])
    settle(qapp, 60)
    yield dialog
    dialog.reject()
    dialog.deleteLater()
    qapp.processEvents()


def _selected(dialog) -> set[str]:
    return {row.entry_id for row in dialog._rows.values() if row.is_selected()}


def _type(dialog, qapp, text: str):
    """Type into the filter and let the debounce land."""
    dialog._search.setText(text)
    settle(qapp, 260)


# ============================================================
#  QUICK-SELECT PILLS
# ============================================================
class TestThePills:

    def test_installed_ticks_only_registered_packages(self, purge, qapp):
        purge._select_all(False)
        purge._all_btn.click()
        settle(qapp, 40)
        assert _selected(purge) == {"BingWeather", "Clipchamp", "KLiteCodec"}

    def test_stubs_ticks_tiles_and_staged_packages(self, purge, qapp):
        """The ones that come back after a feature update — a different
        decision from removing software you actually installed."""
        purge._select_all(False)
        purge._stubs_btn.click()
        settle(qapp, 40)
        assert _selected(purge) == {"DisneyPlus", "Spotify"}

    def test_no_pill_ever_sweeps_the_optional_tier(self, purge, qapp):
        """THE MOST DAMAGING CLICK IN THE APP, if it were wrong — and the
        Xbox row here is INSTALLED, so a pill keying off detection rather
        than tier would take it."""
        purge._select_all(False)
        purge._all_btn.click()
        purge._stubs_btn.click()
        settle(qapp, 40)
        assert "XboxGamingOverlay" not in _selected(purge)

    def test_a_pill_only_ticks_what_is_on_screen(self, purge, qapp):
        """With a filter active, a pill that silently ticked hidden rows
        would be the trap SoftwareCatalogDialog's own rule warns about."""
        _type(purge, qapp, "clipchamp")
        purge._select_all(False)
        purge._all_btn.click()
        settle(qapp, 40)
        assert _selected(purge) == {"Clipchamp"}

    def test_deselect_all_stays_global_even_while_filtered(self, purge, qapp):
        """Turning everything off is never the dangerous direction, so it
        is the one control that ignores the filter."""
        purge._all_btn.click()
        _type(purge, qapp, "weather")
        purge._none_btn.click()
        settle(qapp, 40)
        assert _selected(purge) == set()


# ============================================================
#  THE FILTER
# ============================================================
class TestTheFilter:

    def test_it_matches_the_display_name(self, purge, qapp):
        _type(purge, qapp, "disney")
        assert purge._rows["DisneyPlus"].isVisible()
        assert not purge._rows["BingWeather"].isVisible()

    def test_it_matches_the_package_id(self, purge, qapp):
        """The id is what a forum thread or a winget command names, and it
        is not a substring of the display name: "KLiteCodec" vs "K-Lite
        Codec Pack"."""
        _type(purge, qapp, "klitecodec")
        assert purge._rows["KLiteCodec"].isVisible()
        assert not purge._rows["Clipchamp"].isVisible()

    def test_it_is_debounced_rather_than_per_keystroke(self, purge, qapp):
        purge._search.setText("disney")
        assert purge._search_debounce.isActive(), "the filter did not coalesce"
        assert purge._rows["BingWeather"].isVisible(), (
            "the list re-filtered before the debounce elapsed")
        settle(qapp, 260)
        assert not purge._rows["BingWeather"].isVisible()

    def test_the_field_does_not_take_focus_on_open(self, purge):
        """The other half of why SoftwareCatalogDialog's field was removed:
        a dialog that opens with the keyboard in a text box cannot be
        driven with Space and the arrow keys."""
        from PySide6.QtCore import Qt

        assert purge._search.focusPolicy() == Qt.FocusPolicy.ClickFocus
        assert not purge._search.hasFocus()

    def test_clearing_it_restores_the_whole_list(self, purge, qapp):
        _type(purge, qapp, "disney")
        _type(purge, qapp, "")
        assert purge._rows["BingWeather"].isVisible()
        assert purge._rows["DisneyPlus"].isVisible()

    def test_a_section_header_goes_with_its_last_visible_row(self, purge, qapp):
        """A heading over nothing is the floating-header defect the
        section counts were introduced to fix."""
        _type(purge, qapp, "klitecodec")          # the only codec entry
        shown = [header.text().upper() for header, _rows, _present
                 in purge._sections if header.isVisible()]
        assert any("THIRD-PARTY" in text for text in shown), (
            "the matching row's own section header was hidden with it")
        assert not any("PRE-INSTALLED" in text for text in shown), (
            "a section whose every row is filtered out kept its heading")


class TestTheEmptyFilteredList:

    def test_it_says_when_the_matches_are_merely_folded_away(self, purge, qapp):
        """"No results" while the answer sits behind a toggle is the
        unhelpful half of a filter."""
        _type(purge, qapp, "tiktok")            # present in the catalog, absent here
        assert purge._no_match.isVisible()
        text = purge._no_match.text().lower()
        assert "tiktok" in text
        assert "not on this pc" in text or "aren't installed" in text

    def test_revealing_absent_packages_answers_it(self, purge, qapp):
        _type(purge, qapp, "tiktok")
        purge._show_absent.setChecked(True)
        assert wait_until(qapp, purge._rows["TikTok"].isVisible)
        assert not purge._no_match.isVisible()

    def test_nothing_is_said_when_the_list_has_rows(self, purge, qapp):
        _type(purge, qapp, "disney")
        assert not purge._no_match.isVisible()


# ============================================================
#  THE COUNTER
# ============================================================
class TestTheCounter:

    def test_it_reports_the_selection(self, purge, qapp):
        purge._select_all(False)
        purge._all_btn.click()
        settle(qapp, 40)
        assert purge._count.text().startswith("3 selected")

    def test_it_reports_what_the_filter_is_hiding(self, purge, qapp):
        """The selection is global and the list is not — "3 selected" over
        one visible row reads as a bug until the badge says so."""
        purge._select_all(False)
        purge._all_btn.click()
        _type(purge, qapp, "clipchamp")
        text = purge._count.text()
        assert "3 selected" in text
        # SIX, not seven: the denominator is what the list would show
        # without the filter, and TikTok is folded away as not installed.
        # Counting it contradicted the subtitle's "catalogued package(s)
        # found" and left the reader to account for the difference.
        assert "1 of 6 shown" in text

    def test_revealing_absent_packages_widens_the_denominator(self, purge, qapp):
        """The hidden row joins the count when it joins the list — the two
        must describe the same list."""
        purge._show_absent.setChecked(True)
        _type(purge, qapp, "o")               # matches several, both tiers
        assert "of 7 shown" in purge._count.text()

    def test_it_says_nothing_about_shown_rows_when_unfiltered(self, purge, qapp):
        purge._select_all(False)
        purge._all_btn.click()
        settle(qapp, 40)
        assert "shown" not in purge._count.text()


# ============================================================
#  THE MODULE HEADER'S APPLIED RATIO
# ============================================================
def _page(qapp, index: int = 1):
    from frontend.main import CategoryPage

    return CategoryPage(CATEGORIES[index], TH.ThemeManager().t)


class TestTheAppliedRatio:

    def test_it_reports_applied_over_probed(self, qapp):
        page = _page(qapp)
        try:
            probed = [c for c in page.cards][:3]
            assert len(probed) >= 3, "this module has too few cards to test"
            probed[0].set_applied("applied")
            probed[1].set_applied("applied")
            probed[2].set_applied("default")
            page.refresh_filter()
            assert page._applied_chip.isVisibleTo(page)
            assert page._applied_chip.text() == "2 OF 3 APPLIED"
        finally:
            page.deleteLater()
            qapp.processEvents()

    def test_a_module_with_no_readable_state_shows_no_ratio(self, qapp):
        """A page of routines and reports would otherwise advertise
        "0 OF 0 APPLIED", which is a statistic about nothing."""
        page = _page(qapp)
        try:
            for card in page.cards:
                card.set_applied(None)
            page.refresh_filter()
            assert not page._applied_chip.isVisibleTo(page)
        finally:
            page.deleteLater()
            qapp.processEvents()

    def test_a_routine_is_not_counted_as_unapplied(self, qapp):
        """ACTION DUE is a routine's timing, not a configuration — folding
        it into the denominator would make every module look half-done."""
        page = _page(qapp)
        try:
            for card in page.cards:
                card.set_applied(None)
            page.cards[0].set_applied("applied")
            page.cards[1].set_applied("due")
            page.refresh_filter()
            assert page._applied_chip.text() == "1 OF 1 APPLIED"
        finally:
            page.deleteLater()
            qapp.processEvents()

    def test_the_ratio_ignores_the_status_filter(self, qapp):
        """The filter narrows what you are LOOKING at; a ratio that moved
        with it would report the filter rather than the machine."""
        page = _page(qapp)
        try:
            for card in page.cards:
                card.set_applied(None)
            page.cards[0].set_applied("applied")
            page.cards[1].set_applied("default")
            page.refresh_filter()
            before = page._applied_chip.text()
            index = [page._filter.itemData(i) for i in
                     range(page._filter.count())].index("applied")
            page._filter.setCurrentIndex(index)
            qapp.processEvents()
            assert page._applied_chip.text() == before
        finally:
            page.deleteLater()
            qapp.processEvents()
