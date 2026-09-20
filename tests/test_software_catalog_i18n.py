"""
Arabic for SoftwareCatalogDialog (v16) — the last content surface named
explicitly as in-scope by i18n_catalog.py's own docstring: pillar title/
blurb, every group name, the tab strip, the bulk-install button, and all
46 tools' WhyYouNeedIt line. A tool's own DisplayName ("Google Chrome",
"Docker Desktop") is deliberately never translated — see the module
docstring on both i18n_catalog.py and here.

BUILT FRESH, NOT RETRANSLATED, like CommandPalette — `lang` is read once
at construction (this dialog is reopened, never re-skinned in place), so
there is no retranslate() to test.

A REAL BUG THIS FILE PINS DOWN: _plain_tab_label used to decide "does
this tab label start with an emoji?" by checking `not head.isascii()`.
An Arabic pillar title with no emoji prefix ("البرامج الأساسية
اليومية", the combined/all-pillars view's own tab) is ALSO non-ASCII, so
that check would misread its first word as a stray glyph and strip it —
a translated tab silently losing a word, worse than staying English.
Fixed to test isalpha() instead (an emoji is never alphabetic in either
script); test_the_combined_view_arabic_tab_keeps_its_first_word below is
the regression guard, proven to fail against the old isascii() check.
"""
from __future__ import annotations

from frontend import widgets as W
from frontend.menu_structure import SOFTWARE_CATALOG, catalog_section


def _dialog(window, qapp, item, sections, lang="en"):
    dialog = W.SoftwareCatalogDialog(window, item, window.theme.t, sections, lang=lang)
    dialog.show()
    qapp.processEvents()
    return dialog


ESSENTIALS_CARD = {"icon": "\U0001f5a5️", "title": "Essential Daily Software"}
RUNTIMES_CARD = {"icon": "\U0001f9f1", "title": "Runtimes & Hardware Drivers"}


class TestScopedDialog:
    def test_the_header_title_translates(self, window, qapp):
        from PySide6.QtWidgets import QLabel

        dialog = _dialog(window, qapp, ESSENTIALS_CARD,
                         [catalog_section("essentials")], lang="ar")
        try:
            texts = [lbl.text() for lbl in dialog.findChildren(QLabel)]
            assert any("البرامج الأساسية اليومية" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_blurb_translates_with_the_real_count(self, window, qapp):
        section = catalog_section("essentials")
        total = sum(len(tools) for _g, tools in section["groups"])
        dialog = _dialog(window, qapp, ESSENTIALS_CARD, [section], lang="ar")
        try:
            text = dialog._blurb.text()
            assert "لا شيء محدَّد مسبقًا" in text
            assert str(total) in text
            assert "Nothing is pre-selected" not in text
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_defaults_to_english(self, window, qapp):
        dialog = _dialog(window, qapp, ESSENTIALS_CARD,
                         [catalog_section("essentials")])
        try:
            assert "Nothing is pre-selected" in dialog._blurb.text()
            assert dialog._all_btn.text() == "Select All"
            assert dialog._none_btn.text() == "Deselect All"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_select_all_and_deselect_all_translate(self, window, qapp):
        dialog = _dialog(window, qapp, ESSENTIALS_CARD,
                         [catalog_section("essentials")], lang="ar")
        try:
            assert dialog._all_btn.text() == "تحديد الكل"
            assert dialog._none_btn.text() == "إلغاء تحديد الكل"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_group_header_translates(self, window, qapp):
        from PySide6.QtWidgets import QLabel

        dialog = _dialog(window, qapp, ESSENTIALS_CARD,
                         [catalog_section("essentials")], lang="ar")
        try:
            texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
            assert "🌐 المتصفحات والتواصل" in texts
            assert "🌐 Browsers & Communication" not in texts
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_scoped_tab_label_translates(self, window, qapp):
        dialog = _dialog(window, qapp, ESSENTIALS_CARD,
                         [catalog_section("essentials")], lang="ar")
        try:
            tab_texts = {btn.text() for btn in dialog._tab_buttons.values()}
            assert any("المتصفحات والتواصل" in t for t in tab_texts)
            assert any(t.startswith("الكل") for t in tab_texts), (
                "the 'All' tab did not translate: " + repr(tab_texts))
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_bulk_button_translates(self, window, qapp):
        """Only the runtimes pillar declares a bulk action."""
        dialog = _dialog(window, qapp, RUNTIMES_CARD,
                         [catalog_section("runtimes")], lang="ar")
        try:
            assert dialog._bulk_btn.text() == "تثبيت كل التبعيات الأساسية"
            assert "يحدِّد كل بيئات التشغيل الأساسية" in dialog._bulk_btn.toolTip()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_footnote_translates(self, window, qapp):
        from PySide6.QtWidgets import QLabel

        dialog = _dialog(window, qapp, RUNTIMES_CARD,
                         [catalog_section("runtimes")], lang="ar")
        try:
            texts = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "OpenGL وVulkan" in texts
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_cancel_and_deploy_translate(self, window, qapp):
        from PySide6.QtWidgets import QPushButton

        dialog = _dialog(window, qapp, ESSENTIALS_CARD,
                         [catalog_section("essentials")], lang="ar")
        try:
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "إلغاء" in labels
            assert "نشر المحدَّد" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_live_counter_translates_as_rows_are_ticked(self, window, qapp):
        dialog = _dialog(window, qapp, ESSENTIALS_CARD,
                         [catalog_section("essentials")], lang="ar")
        try:
            assert dialog._count_label.text() == "0 محدَّد"
            first_row = next(iter(dialog._rows.values()))
            first_row.checkbox.setChecked(True)
            qapp.processEvents()
            assert dialog._count_label.text() == "1 محدَّد"
            assert dialog._deploy_btn.text() == "نشر المحدَّد (1)"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


class TestCombinedDialog:
    def test_the_empty_state_translates(self, window, qapp):
        dialog = _dialog(window, qapp,
                         {"icon": "\U0001f4e6", "title": "Software Catalog"},
                         SOFTWARE_CATALOG, lang="ar")
        try:
            assert dialog._empty.text() == "لا توجد تطبيقات في هذه الفئة."
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_blurb_translates(self, window, qapp):
        total = sum(len(tools) for s in SOFTWARE_CATALOG for _g, tools in s["groups"])
        dialog = _dialog(window, qapp,
                         {"icon": "\U0001f4e6", "title": "Software Catalog"},
                         SOFTWARE_CATALOG, lang="ar")
        try:
            text = dialog._blurb.text()
            assert str(total) in text
            assert "في مكان واحد" in text
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_combined_view_arabic_tab_keeps_its_first_word(self, window, qapp):
        """THE REGRESSION GUARD — see the module docstring. A pillar tab
        in the combined view has NO emoji prefix, so its Arabic label
        must render in full, not missing its first word."""
        dialog = _dialog(window, qapp,
                         {"icon": "\U0001f4e6", "title": "Software Catalog"},
                         SOFTWARE_CATALOG, lang="ar")
        try:
            tab_texts = [btn.text() for btn in dialog._tab_buttons.values()]
            assert any(t.startswith("البرامج الأساسية اليومية")
                      for t in tab_texts), (
                "the essentials pillar's Arabic tab lost its first word: "
                + repr(tab_texts))
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


class TestDevHubRowTranslation:
    def test_the_tooltip_translates_but_the_app_name_does_not(self, window, qapp):
        dialog = _dialog(window, qapp, ESSENTIALS_CARD,
                         [catalog_section("essentials")], lang="ar")
        try:
            chrome_row = next(
                r for aid, r in dialog._rows.items() if aid == "Google.Chrome")
            assert chrome_row.checkbox.text() == "Google Chrome"
            assert chrome_row.checkbox.toolTip() == \
                "متصفح ويب سريع وآمن من Google."
            assert "Google" in chrome_row.website_btn.toolTip()
            assert "فتح صفحة تنزيل" in chrome_row.website_btn.toolTip()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_requires_hint_translates_around_the_english_app_name(
            self, window, qapp):
        """NetBeans/PyCharm/IntelliJ/Open WebUI 'need' a JDK/Python/
        Ollama — the dependency's own name stays English (it is itself
        an app name), only the surrounding template translates."""
        dialog = _dialog(window, qapp,
                         {"icon": "\U0001f9d1‍\U0001f4bb",
                          "title": "Developer, AI & Engineering"},
                         [catalog_section("development")], lang="ar")
        try:
            hinted = [r for r in dialog._rows.values()
                     if r._hint_label is not None]
            assert hinted, "no dependent row found to check"
            text = hinted[0]._hint_label.text()
            assert text.startswith("↳ يحتاج")
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_defaults_to_english(self, window, qapp):
        dialog = _dialog(window, qapp, ESSENTIALS_CARD,
                         [catalog_section("essentials")])
        try:
            chrome_row = next(
                r for aid, r in dialog._rows.items() if aid == "Google.Chrome")
            assert chrome_row.checkbox.toolTip() == \
                "Fast, secure web browser from Google."
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()
