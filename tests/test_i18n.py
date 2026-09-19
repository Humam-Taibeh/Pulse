"""
The EN/AR display-language foundation (v10.15): frontend.i18n, the prefs
key that persists the choice, and the shell surfaces that actually
retranslate — SettingsView (where the picker lives), the sidebar rail
(NavButton's RTL painting in particular), and StatusRail's tooltips.

WHAT THIS DOES NOT COVER. Per-module task-card titles/descriptions
(menu_structure.py), the live console, playbooks and the Health Report
stay English in this pass — see the scope note at the top of
frontend/i18n.py. Nothing here should start passing for those surfaces;
if it does, something drifted from the documented boundary.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from frontend import i18n as I18N
from frontend import theme as TH
from frontend.widgets import NavButton


# ============================================================
#  PREFS
# ============================================================
class TestLanguagePrefs:
    """Mutates prefs._settings() directly, the same convention
    test_history.py already uses — conftest._isolate_preferences (session,
    autouse) has already redirected it to a throwaway hive, so this never
    touches the real app's stored preference."""

    def test_default_is_english(self):
        from utils import prefs

        prefs._settings().remove("ui/language")
        assert prefs.language() == "en"

    def test_round_trips_through_set_language(self):
        from utils import prefs

        prefs.set_language("ar")
        assert prefs.language() == "ar"
        prefs.set_language("en")   # leave the shared hive as found
        assert prefs.language() == "en"

    def test_an_invalid_stored_value_falls_back_to_the_default(self):
        from utils import prefs

        prefs._settings().setValue("ui/language", "fr")
        assert prefs.language() == "en"
        prefs._settings().remove("ui/language")


# ============================================================
#  frontend.i18n.tr()
# ============================================================
class TestTranslate:

    def test_english_is_the_default_language(self):
        assert I18N.tr("dialog.cancel", "en") == "Cancel"

    def test_arabic_resolves_to_its_own_entry(self):
        assert I18N.tr("dialog.cancel", "ar") == "إلغاء"

    def test_a_missing_key_degrades_to_the_key_itself(self):
        """The same "never crash on a bad table lookup" posture as
        theme.glyph() — a half-translated surface must never become a
        broken one."""
        assert I18N.tr("no.such.key", "en") == "no.such.key"
        assert I18N.tr("no.such.key", "ar") == "no.such.key"

    def test_is_rtl_is_true_only_for_arabic(self):
        assert I18N.is_rtl("ar") is True
        assert I18N.is_rtl("en") is False


# ============================================================
#  SettingsView
# ============================================================
@pytest.fixture
def settings_ar(window, qapp):
    from frontend.widgets import SettingsView

    view = SettingsView(window.theme.t, is_admin=True, lang="ar")
    view.show()
    qapp.processEvents()
    yield view
    view.deleteLater()
    qapp.processEvents()


class TestSettingsViewLanguage:

    def test_defaults_to_english_for_every_existing_caller(self, window, qapp):
        """Backward-compatibility contract: every construction in
        test_settings_view.py omits `lang` and must keep rendering
        English — this is what makes that whole file valid without
        modification."""
        from frontend.widgets import SettingsView

        view = SettingsView(window.theme.t, is_admin=True)
        try:
            assert view.current_language() == "en"
            assert view._title.text() == "Settings"
        finally:
            view.deleteLater()
            qapp.processEvents()

    def test_arabic_construction_renders_arabic_and_sets_rtl(self, settings_ar):
        assert settings_ar.current_language() == "ar"
        assert settings_ar._title.text() == "الإعدادات"
        assert settings_ar.layoutDirection() == Qt.LayoutDirection.RightToLeft

    def test_choosing_a_language_only_asks(self, window, qapp):
        """Same "ASKS ONLY" shape as choose_theme_mode — main.py owns the
        persisted choice; the view is told the answer through
        set_language."""
        from frontend.widgets import SettingsView

        view = SettingsView(window.theme.t, is_admin=True)
        try:
            asked: list[str] = []
            view.language_requested.connect(asked.append)
            view.choose_language("ar")
            qapp.processEvents()
            assert asked == ["ar"]
            assert view.current_language() == "en", (
                "choosing must not itself change the page — only "
                "set_language does")
        finally:
            view.deleteLater()
            qapp.processEvents()

    def test_set_language_retranslates_every_group_title(self, window, qapp):
        from frontend.widgets import SettingsView

        view = SettingsView(window.theme.t, is_admin=True)
        try:
            view.set_language("ar")
            qapp.processEvents()
            titles = {label.text() for label in view._group_titles}
            assert titles == {
                "عام", "حماية النظام", "إدارة التكوين", "التحديثات"}
        finally:
            view.deleteLater()
            qapp.processEvents()

    def test_set_language_back_to_english_is_lossless(self, window, qapp):
        """A round trip must not leave stale Arabic text anywhere it
        touched — the risk a naive partial-retranslate would carry."""
        from frontend.widgets import SettingsView

        view = SettingsView(window.theme.t, is_admin=True)
        try:
            view.set_language("ar")
            qapp.processEvents()
            view.set_language("en")
            qapp.processEvents()
            assert view._title.text() == "Settings"
            assert view.layoutDirection() == Qt.LayoutDirection.LeftToRight
            assert {label.text() for label in view._group_titles} == {
                "General", "System Protection", "Configuration Management",
                "Updates"}
        finally:
            view.deleteLater()
            qapp.processEvents()

    def test_the_theme_mode_keys_are_unaffected_by_language(self, settings_ar):
        """theme_modes() identifies a mode by its English identifier
        ("dark"/"light"/"system") everywhere else in the app — only the
        DISPLAY text of THEME_CHOICES is language-dependent."""
        assert set(settings_ar.theme_modes()) == {"dark", "light", "system"}

    def test_a_missing_restore_note_variant_cannot_happen(self, window, qapp):
        """Both admin-state variants exist in Arabic too — the note is
        one of two fixed strings, not data-driven, so unlike the restore
        SUMMARY line it has no excuse to fall back to English."""
        from frontend.widgets import SettingsView

        admin_view = SettingsView(window.theme.t, is_admin=True, lang="ar")
        not_admin_view = SettingsView(window.theme.t, is_admin=False, lang="ar")
        try:
            assert admin_view.restore_note() != not_admin_view.restore_note()
            for view in (admin_view, not_admin_view):
                assert view.restore_note(), "empty restore note in Arabic"
        finally:
            admin_view.deleteLater()
            not_admin_view.deleteLater()
            qapp.processEvents()


# ============================================================
#  The shell: sidebar + language/theme independence
# ============================================================
class TestShellLanguageSwitch:

    def test_switching_language_leaves_the_theme_untouched(self, window, qapp):
        """Proves language and theme are independent axes — a language
        switch must not repaint a single colour token."""
        before_mode = window.theme.mode
        before_tokens = window.theme.t
        try:
            window._on_language_chosen("ar")
            qapp.processEvents()
            assert window.theme.mode == before_mode
            assert window.theme.t is before_tokens
        finally:
            window._on_language_chosen("en")
            qapp.processEvents()

    def test_switching_language_retranslates_the_sidebars_own_chrome(
            self, window, qapp):
        before = window._language
        try:
            window._on_language_chosen("ar")
            qapp.processEvents()
            assert window._section.text() == "الوحدات"
            assert window._settings_btn.text() == "الإعدادات"
            assert window.settings_view.current_language() == "ar"
        finally:
            window._on_language_chosen(before)
            qapp.processEvents()

    def test_the_four_module_buttons_keep_english_labels(self, window, qapp):
        """Deliberate: each module button is also its destination page's
        own header, and that page's tagline/filter/cards are still
        English — see i18n.py's note on why the label does not move
        while the layout direction still does."""
        before = window._language
        titles_before = [btn.text() for btn in window._nav_buttons]
        try:
            window._on_language_chosen("ar")
            qapp.processEvents()
            titles_after = [btn.text() for btn in window._nav_buttons]
            assert titles_after == titles_before
        finally:
            window._on_language_chosen(before)
            qapp.processEvents()

    def test_the_choice_is_persisted(self, window, qapp, monkeypatch):
        from utils import prefs

        stored: list[str] = []
        monkeypatch.setattr(prefs, "set_language", stored.append)
        before = window._language
        try:
            window._on_language_chosen("ar")
            qapp.processEvents()
            assert stored == ["ar"]
        finally:
            window._on_language_chosen(before)
            qapp.processEvents()


# ============================================================
#  NavButton — RTL is a painted concern, not just a QSS one
# ============================================================
def _ink(image, x0, y0, x1, y1, y_step=2):
    return sum(image.pixelColor(x, y).alpha()
               for x in range(int(x0), int(x1))
               for y in range(int(y0), int(y1), y_step))


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_plaque_moves_to_the_opposite_side_under_rtl(mode, qapp):
    """NavButton._paint_plaque anchors the icon well at a literal pixel
    offset via a raw QPainter box — Qt's automatic RTL mirroring covers
    QSS text-align/padding and standard layouts, but not that. This is
    the pixel proof set_rtl actually moves the anchor, not just that it
    runs without raising or that nav_button_qss's string changed."""
    t = TH.tokens(mode)
    button = NavButton("package", "Software Management", "software", t)
    width, height = 218, 46
    button.resize(width, height)

    plaque, gutter = TH.PLAQUE_SIZE, TH.SIDEBAR_GUTTER
    left_box = (gutter, 0, gutter + plaque, height)
    right_box = (width - gutter - plaque, 0, width - gutter, height)

    ltr = button.grab().toImage()
    ltr_left = _ink(ltr, *left_box)
    ltr_right = _ink(ltr, *right_box)
    assert ltr_left > ltr_right, (
        f"{mode}: LTR plaque is not the strongest ink in the left box "
        f"({ltr_left} left vs {ltr_right} right)")

    button.set_rtl(True)
    rtl = button.grab().toImage()
    rtl_left = _ink(rtl, *left_box)
    rtl_right = _ink(rtl, *right_box)
    assert rtl_right > rtl_left, (
        f"{mode}: the plaque did not move into the right box under RTL "
        f"({rtl_left} left vs {rtl_right} right)")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_set_rtl_is_a_no_op_when_unchanged(mode, qapp):
    """Guards the early-return in set_rtl: a repeated call with the same
    value must not repaint (and, more importantly, must not silently
    diverge self._t from what apply_theme last set)."""
    t = TH.tokens(mode)
    button = NavButton("package", "Software Management", "software", t)
    qss_before = button.styleSheet()
    button.set_rtl(False)      # already False at construction
    assert button.styleSheet() == qss_before
