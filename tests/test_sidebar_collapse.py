"""
The collapsible sidebar (v16): expanded (icons + labels) vs compact
(icons only, centred), toggled from a chevron button pinned to the top
of the rail and persisted the same way theme/language already are.

WHAT "COMPACT" MEANS FOR A LABEL. Text is not elided or clipped — at the
rail's collapsed width there is barely room for the plaque itself, so a
sliver of clipped text would read as a rendering bug. It is blanked
outright and moves into the tooltip, the same trade every icon-only
Windows toolbar already makes.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from frontend import theme as TH
from frontend.widgets import NavButton


# ============================================================
#  PREFS
# ============================================================
class TestSidebarCollapsePrefs:

    def test_default_is_expanded(self):
        from utils import prefs

        prefs._settings().remove("ui/sidebar_collapsed")
        assert prefs.sidebar_collapsed() is False

    def test_round_trips_through_set_sidebar_collapsed(self):
        from utils import prefs

        prefs.set_sidebar_collapsed(True)
        assert prefs.sidebar_collapsed() is True
        prefs.set_sidebar_collapsed(False)   # leave the shared hive as found
        assert prefs.sidebar_collapsed() is False


# ============================================================
#  NavButton — compact is a distinct axis from rtl
# ============================================================
class TestNavButtonCompact:

    def test_compact_blanks_the_label_and_moves_it_to_the_tooltip(self, qapp):
        t = TH.tokens("dark")
        button = NavButton("package", "Software Management", "software", t)
        assert button.text() == "Software Management"
        assert button.toolTip() == ""

        button.set_compact(True)
        assert button.text() == ""
        assert button.toolTip() == "Software Management"

    def test_expanding_again_restores_the_label(self, qapp):
        t = TH.tokens("dark")
        button = NavButton("package", "Software Management", "software", t)
        button.set_compact(True)
        button.set_compact(False)
        assert button.text() == "Software Management"
        assert button.toolTip() == ""

    def test_set_compact_is_a_no_op_when_unchanged(self, qapp):
        """Guards the early-return, the same shape as set_rtl's own guard
        — a repeated call must not re-blank an already-compact label or
        re-fetch the tooltip from a title that has not changed."""
        t = TH.tokens("dark")
        button = NavButton("package", "Software Management", "software", t)
        button.set_compact(True)
        tooltip_before = button.toolTip()
        button.set_compact(True)
        assert button.toolTip() == tooltip_before

    def test_set_title_while_expanded_updates_the_visible_text(self, qapp):
        t = TH.tokens("dark")
        button = NavButton("gear", "Settings", "", t)
        button.set_title("الإعدادات")
        assert button.text() == "الإعدادات"

    def test_set_title_while_compact_updates_the_tooltip_not_the_text(self, qapp):
        """The exact bug set_title exists to prevent: a caller using plain
        setText() on a collapsed button would silently paint a label over
        a centred plaque the moment the rail expanded again, because
        nothing would remember the collapse should keep suppressing it."""
        t = TH.tokens("dark")
        button = NavButton("gear", "Settings", "", t)
        button.set_compact(True)
        button.set_title("الإعدادات")
        assert button.text() == "", (
            "a language change while collapsed leaked text onto an "
            "icon-only row")
        assert button.toolTip() == "الإعدادات"

    def test_expanding_after_a_title_change_while_compact_shows_the_new_title(
            self, qapp):
        t = TH.tokens("dark")
        button = NavButton("gear", "Settings", "", t)
        button.set_compact(True)
        button.set_title("الإعدادات")
        button.set_compact(False)
        assert button.text() == "الإعدادات"


# ============================================================
#  NavButton — compact wins over rtl for the painted plaque
# ============================================================
def _ink(image, x0, y0, x1, y1, y_step=2):
    return sum(image.pixelColor(x, y).alpha()
               for x in range(int(x0), int(x1))
               for y in range(int(y0), int(y1), y_step))


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("rtl", [False, True])
def test_a_compact_plaque_centres_regardless_of_direction(mode, rtl, qapp):
    """The collapsed rail must look identical in English and Arabic —
    there is no label left to clear space for on either side, so RTL's
    own left/right anchor swap (see test_i18n.py's LTR/RTL plaque test)
    is deliberately overridden while compact."""
    t = TH.tokens(mode)
    button = NavButton("package", "Software Management", "software", t)
    width, height = 84, 46           # PulseApp.SIDEBAR_WIDTH_COMPACT
    button.resize(width, height)
    button.set_rtl(rtl)
    button.set_compact(True)

    plaque = TH.PLAQUE_SIZE
    center_x = width / 2.0
    left_box = (0, 0, center_x - plaque / 2, height)
    right_box = (center_x + plaque / 2, 0, width, height)
    center_box = (center_x - plaque / 2, 0, center_x + plaque / 2, height)

    image = button.grab().toImage()
    center_ink = _ink(image, *center_box)
    edge_ink = _ink(image, *left_box) + _ink(image, *right_box)
    assert center_ink > edge_ink, (
        f"{mode}/rtl={rtl}: the compact plaque is not centred "
        f"({center_ink} centre vs {edge_ink} combined edges)")


# ============================================================
#  THE SHELL
# ============================================================
class TestShellCollapse:

    def test_the_toggle_flips_the_width(self, window, qapp):
        before = window._sidebar_collapsed
        try:
            if before:
                window._on_sidebar_toggle_clicked()
                qapp.processEvents()
            assert window._sidebar.width() == window.SIDEBAR_WIDTH_EXPANDED
            window._on_sidebar_toggle_clicked()
            qapp.processEvents()
            assert window._sidebar.width() == window.SIDEBAR_WIDTH_COMPACT
        finally:
            if window._sidebar_collapsed:
                window._on_sidebar_toggle_clicked()
                qapp.processEvents()

    def test_collapsing_hides_the_section_label_and_compacts_nav_buttons(
            self, window, qapp):
        try:
            window._apply_sidebar_collapsed(True)
            qapp.processEvents()
            assert not window._section.isVisible()
            assert window._settings_btn.text() == ""
            assert all(btn.text() == "" for btn in window._nav_buttons)
        finally:
            window._apply_sidebar_collapsed(False)
            qapp.processEvents()
            window._sidebar_collapsed = False

    def test_expanding_restores_the_section_label_and_nav_labels(
            self, window, qapp):
        titles_before = [btn.text() for btn in window._nav_buttons]
        try:
            window._apply_sidebar_collapsed(True)
            qapp.processEvents()
            window._apply_sidebar_collapsed(False)
            qapp.processEvents()
            assert window._section.isVisible()
            assert [btn.text() for btn in window._nav_buttons] == titles_before
            assert window._settings_btn.text() != ""
        finally:
            window._sidebar_collapsed = False

    def test_the_choice_is_persisted(self, window, qapp, monkeypatch):
        from utils import prefs

        stored: list[bool] = []
        monkeypatch.setattr(prefs, "set_sidebar_collapsed", stored.append)
        before = window._sidebar_collapsed
        try:
            window._on_sidebar_toggle_clicked()
            qapp.processEvents()
            assert stored == [not before]
        finally:
            if window._sidebar_collapsed != before:
                window._on_sidebar_toggle_clicked()
                qapp.processEvents()

    def test_the_toggle_button_has_a_tooltip_in_both_states(self, window, qapp):
        """Unlike the module buttons, the toggle's own meaning does not
        collapse away — it must never go silent."""
        try:
            assert window._sidebar_toggle.toolTip() != ""
            window._apply_sidebar_collapsed(True)
            qapp.processEvents()
            assert window._sidebar_toggle.toolTip() != ""
        finally:
            window._apply_sidebar_collapsed(False)
            qapp.processEvents()
            window._sidebar_collapsed = False

    def test_collapsed_and_rtl_combine_without_error(self, window, qapp):
        """The two axes this whole feature had to prove independent of
        each other — collapsing while Arabic is active, and switching
        language while collapsed, must both leave the shell in a sane
        state rather than raising or silently reverting one setting."""
        before_lang = window._language
        before_collapsed = window._sidebar_collapsed
        try:
            window._apply_sidebar_collapsed(True)
            qapp.processEvents()
            window._on_language_chosen("ar")
            qapp.processEvents()
            assert window._sidebar.layoutDirection() == Qt.LayoutDirection.RightToLeft
            assert window._sidebar.width() == window.SIDEBAR_WIDTH_COMPACT
            assert window._settings_btn.text() == "", (
                "Arabic retranslation leaked text onto a collapsed button")

            window._apply_sidebar_collapsed(False)
            qapp.processEvents()
            assert window._settings_btn.text() == "الإعدادات", (
                "expanding after a language change while collapsed did not "
                "show the translated title")
        finally:
            window._on_language_chosen(before_lang)
            window._apply_sidebar_collapsed(before_collapsed)
            window._sidebar_collapsed = before_collapsed
            qapp.processEvents()
