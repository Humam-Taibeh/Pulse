"""
Arabic for the Ctrl+K command palette (v16) — the last high-traffic
surface still showing raw English after the dashboard/category-page/card
pass: every result row renders a card title the rest of the app already
translates, so leaving the palette out would have made SEARCHING for a
tweak the one place its Arabic name never appeared.

BUILT FRESH, NOT RETRANSLATED. CommandPalette is constructed new on every
Ctrl+K press (see its own class docstring — "no live re-theme needed"),
so `lang` is read once at construction like ConfirmDialog/
SoftwareCatalogDialog, and there is no retranslate() to test here.

MATCHING STAYS ENGLISH ON PURPOSE. _match_entry reads item["title"] and
["desc"] directly, in English, regardless of display language — only the
RENDERED row translates. So these tests search with English query text
even under lang="ar" and assert the RESULT renders translated; they do
not exercise Arabic-query matching (SEARCH_ALIASES' own existing
coverage handles that, unchanged by this pass).
"""
from __future__ import annotations

from conftest import show_dialog
from frontend.menu_structure import iter_leaf_items
from frontend.widgets import CommandPalette


def _open(window, qapp, lang="en"):
    palette = CommandPalette(window, window.theme.t, list(iter_leaf_items()), lang=lang)
    show_dialog(qapp, palette)
    return palette


class TestChrome:
    def test_defaults_to_english(self, window, qapp):
        palette = _open(window, qapp)
        try:
            assert palette._search.placeholderText() == \
                "Search apps, tweaks and tools…"
            assert palette._empty.text() == \
                "No apps, tweaks or tools match that search."
        finally:
            palette.deleteLater()
            qapp.processEvents()

    def test_arabic_translates_the_field_and_empty_state(self, window, qapp):
        palette = _open(window, qapp, lang="ar")
        try:
            assert palette._search.placeholderText() == \
                "ابحث في التطبيقات والتعديلات والأدوات…"
            palette._refilter("zzz_no_such_query_zzz")
            qapp.processEvents()
            assert palette._empty.isVisible()
            assert palette._empty.text() == \
                "لا توجد تطبيقات أو تعديلات أو أدوات مطابقة لهذا البحث."
        finally:
            palette.deleteLater()
            qapp.processEvents()

    def test_arabic_translates_the_footer_hints(self, window, qapp):
        from PySide6.QtWidgets import QLabel

        palette = _open(window, qapp, lang="ar")
        try:
            texts = {lbl.text() for lbl in palette.findChildren(QLabel)}
            assert "تنقّل" in texts
            assert "تشغيل" in texts
            assert "إغلاق" in texts
            assert "navigate" not in texts
        finally:
            palette.deleteLater()
            qapp.processEvents()


class TestResultRows:
    def test_a_result_title_translates(self, window, qapp):
        """'Global Dark Mode' is a real card title already covered by
        i18n_catalog.py — searching its own English text must still find
        it (matching stays English), but the row must render Arabic."""
        palette = _open(window, qapp, lang="ar")
        try:
            palette._refilter("Global Dark Mode")
            qapp.processEvents()
            assert palette._rows, "no results for an exact known title"
            titles = {row._title.text() for row in palette._rows.values()}
            assert "الوضع الداكن الشامل" in titles
            assert "Global Dark Mode" not in titles
        finally:
            palette.deleteLater()
            qapp.processEvents()

    def test_a_result_title_stays_english_by_default(self, window, qapp):
        palette = _open(window, qapp)
        try:
            palette._refilter("Global Dark Mode")
            qapp.processEvents()
            titles = {row._title.text() for row in palette._rows.values()}
            assert "Global Dark Mode" in titles
        finally:
            palette.deleteLater()
            qapp.processEvents()

    def test_a_group_header_translates(self, window, qapp):
        """_add_header renders the CATEGORY name ('System & Tweaks',
        home of Global Dark Mode), already covered since v16's first
        batch."""
        from PySide6.QtWidgets import QLabel

        palette = _open(window, qapp, lang="ar")
        try:
            palette._refilter("Global Dark Mode")
            qapp.processEvents()
            all_text = " ".join(lbl.text() for lbl in palette.findChildren(QLabel))
            assert "النظام والتعديلات" in all_text
        finally:
            palette.deleteLater()
            qapp.processEvents()

    def test_a_hub_hint_translates(self, window, qapp):
        """A result inside a hub shows the hub's own name as its hint
        (see _add_result) when there is no content-match reason — 'Global
        Dark Mode' has no hub, so use a known hub member instead."""
        palette = _open(window, qapp, lang="ar")
        try:
            palette._refilter("Reinstall Microsoft Edge")
            qapp.processEvents()
            assert palette._rows, "no results for a known hub sub-action"
            hints = {row._hint_text for row in palette._rows.values()}
            # the Microsoft Edge hub card's own title, translated
            assert any("Microsoft Edge" in h for h in hints)
        finally:
            palette.deleteLater()
            qapp.processEvents()

    def test_result_count_is_arabic(self, window, qapp):
        palette = _open(window, qapp, lang="ar")
        try:
            palette._refilter("Global Dark Mode")
            qapp.processEvents()
            assert palette._count.text() == "نتيجة واحدة"
        finally:
            palette.deleteLater()
            qapp.processEvents()
