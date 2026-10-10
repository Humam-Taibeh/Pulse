"""
The EN/AR display-language foundation (v10.15): frontend.i18n, the prefs
key that persists the choice, and the shell surfaces that actually
retranslate — SettingsView (where the picker lives, and where the
elevation state that used to live in the sidebar's widgets.StatusRail
moved to in v10.17.2 — see test_settings_view.py's TestTheSessionGroup),
the sidebar rail (NavButton's RTL painting in particular), and the
activity drawer's own canonical states.

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
                "عام", "حماية النظام", "إدارة التكوين", "التحديثات",
                "الجلسة"}
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
                "Updates", "Session"}
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

    def test_the_four_module_buttons_translate_with_their_pages(
            self, window, qapp):
        """v16: the boundary v10.15 drew here (module label stays English
        because its destination page was still all-English) is closed —
        the destination pages translate now too (see
        TestCategoryPageTranslation), so the button does not have to lag
        behind them anymore."""
        before = window._language
        titles_before = [btn.text() for btn in window._nav_buttons]
        try:
            window._on_language_chosen("ar")
            qapp.processEvents()
            titles_after = [btn.text() for btn in window._nav_buttons]
            assert titles_after == [
                "إدارة البرامج", "النظام والتعديلات",
                "الصيانة والأمان", "الأدوات والمرافق"]
            assert titles_after != titles_before
        finally:
            window._on_language_chosen(before)
            qapp.processEvents()
            assert [btn.text() for btn in window._nav_buttons] == titles_before

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
#  ActivityDrawer — the bottom status strip (v10.17.1)
# ============================================================
class TestActivityDrawerLanguage:
    """CHANGELOG.md named this "the bottom status bar" as the last
    hardcoded-English chrome surface. Only the rail's own canonical
    states translate — a dynamic phase line or task name stays English
    along with the live console it echoes into, same boundary as
    everywhere else (see main._status_key / _set_canonical_status)."""

    def test_constructing_in_arabic_shows_arabic_chrome(self, window, qapp):
        from frontend.widgets import ActivityDrawer

        drawer = ActivityDrawer(window.theme.t, lang="ar")
        try:
            assert drawer.status_text.fullText() == "النظام جاهز"
            assert drawer.stop_btn.text() == "■  إيقاف المهمة"
            assert drawer.stop_btn.toolTip() == (
                "إيقاف قسري للمهمة الجارية (يُنهي شجرة العمليات بأكملها)")
            assert drawer._toggle.toolTip() == "تثبيت الإخراج المباشر مفتوحًا"
        finally:
            drawer.deleteLater()
            qapp.processEvents()

    def test_defaults_to_english(self, window, qapp):
        from frontend.widgets import ActivityDrawer

        drawer = ActivityDrawer(window.theme.t)
        try:
            assert drawer.status_text.fullText() == "System Ready"
            assert drawer.stop_btn.text() == "■  Stop Task"
        finally:
            drawer.deleteLater()
            qapp.processEvents()

    def test_the_pin_tooltip_tracks_checked_state_in_either_language(
            self, window, qapp):
        from frontend.widgets import ActivityDrawer

        drawer = ActivityDrawer(window.theme.t, lang="ar")
        try:
            drawer._toggle.setChecked(True)
            qapp.processEvents()
            assert drawer._toggle.toolTip() == "إلغاء تثبيت الإخراج المباشر"
        finally:
            drawer.deleteLater()
            qapp.processEvents()

    def test_a_language_switch_retranslates_the_idle_rail(self, window, qapp):
        """The real scenario: the window's own drawer, built once in
        English at launch, on a live switch through the same
        _on_language_chosen path every other surface uses."""
        before = window._language
        try:
            assert window.status_text.fullText() == "System Ready"
            window._on_language_chosen("ar")
            qapp.processEvents()
            assert window.status_text.fullText() == "النظام جاهز"
            assert window.stop_btn.toolTip() == (
                "إيقاف قسري للمهمة الجارية (يُنهي شجرة العمليات بأكملها)")
            assert window.activity._toggle.toolTip() == \
                "تثبيت الإخراج المباشر مفتوحًا"
        finally:
            window._on_language_chosen(before)
            qapp.processEvents()

    def test_round_trip_back_to_english_is_lossless(self, window, qapp):
        before = window._language
        try:
            baseline = (window.status_text.fullText(), window.stop_btn.toolTip(),
                        window.activity._toggle.toolTip())
            window._on_language_chosen("ar")
            qapp.processEvents()
            assert (window.status_text.fullText(), window.stop_btn.toolTip(),
                    window.activity._toggle.toolTip()) != baseline
            window._on_language_chosen("en")
            qapp.processEvents()
            assert (window.status_text.fullText(), window.stop_btn.toolTip(),
                    window.activity._toggle.toolTip()) == baseline
        finally:
            window._on_language_chosen(before)
            qapp.processEvents()

    def test_a_dynamic_status_is_not_clobbered_by_a_language_switch(
            self, window, qapp):
        """A task's own phase/title text (main._status_key = None) stays
        exactly as reported, same boundary as the live console — a
        language switch mid-run must not silently rewrite it into a
        canonical string it never was."""
        before = window._language
        before_key = window._status_key
        try:
            window._status_key = None
            window._set_status("busy", "Executing: Something Specific …")
            window._on_language_chosen("ar")
            qapp.processEvents()
            assert window.status_text.fullText() == "Executing: Something Specific …"
        finally:
            window._status_key = before_key
            window._on_language_chosen(before)
            qapp.processEvents()

    def test_the_stopping_label_survives_a_switch_while_disabled(
            self, window, qapp):
        """stop_btn.isEnabled() is how _apply_language tells the two
        visible labels apart (no extra state to keep in sync) — this
        pins that contract."""
        before = window._language
        try:
            window.stop_btn.show()
            window.stop_btn.setEnabled(False)
            window.stop_btn.setText("Stopping…")
            window._on_language_chosen("ar")
            qapp.processEvents()
            assert window.stop_btn.text() == "جارٍ الإيقاف…"
        finally:
            window.stop_btn.hide()
            window.stop_btn.setEnabled(True)
            window._on_language_chosen(before)
            qapp.processEvents()


# ============================================================
#  Cold launch with a PERSISTED non-English language
# ============================================================
class TestLaunchWithPersistedLanguage:
    """THE REGRESSION: a session that chose Arabic last time crashed on
    every subsequent launch with 'PulseApp' object has no attribute
    'activity' — _build_ui's early self._apply_language(self._language)
    call (there specifically so a persisted-Arabic session opens
    translated/RTL from frame one, not just after re-picking it in
    Settings) ran before self.activity/self.status_text/self.stop_btn
    existed. v10.17.1's ActivityDrawer.retranslate() call inside
    _apply_language is what turned a pre-existing ordering assumption
    into a crash.

    The `window` fixture used by every other test in this file always
    launches in English (prefs default), so it never exercised this path
    — that is exactly why this needs its own cold-construction test
    rather than reusing `window`."""

    def test_a_persisted_arabic_language_does_not_crash_on_launch(
            self, fresh_window, qapp):
        from utils import prefs

        prefs.set_language("ar")
        try:
            win = fresh_window()   # must not raise
            assert win.activity is not None
            assert win.status_text.fullText() == "النظام جاهز"
            assert win._sidebar.layoutDirection() == Qt.LayoutDirection.RightToLeft
        finally:
            prefs.set_language("en")

    def test_a_persisted_english_language_still_launches_untranslated(
            self, fresh_window, qapp):
        from utils import prefs

        prefs.set_language("en")
        win = fresh_window()
        assert win.status_text.fullText() == "System Ready"
        assert win._sidebar.layoutDirection() == Qt.LayoutDirection.LeftToRight


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
