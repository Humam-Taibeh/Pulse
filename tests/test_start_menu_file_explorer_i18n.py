"""
Arabic for the v1.1 "START MENU" and "FILE EXPLORER" bands (System &
Tweaks) — nine granular, independently-revertible registry toggles
(StartHideRecommended, StartDisableWebSearch, StartDisableRecentTracking,
StartDisableSuggestions, ExplorerLaunchToThisPC, ExplorerShowFileExt,
ExplorerShowHidden, ExplorerShowProtected, ExplorerHideRecommended).

Both bands are ordinary menu_structure.py catalog data, so they translate
through the same mechanism every other card on this page already uses —
frontend.i18n_catalog's exact-English-text lookup (TITLES/DESCRIPTIONS)
via GlassCard.retranslate() — and this file follows the same pattern as
test_catalog_i18n.py's own band-header / card-translation tests rather
than inventing a new one.

NOT COVERED, on purpose: each card's `note` field ("Windows 11 only" /
"Windows 11, version 22H2 or later") — GlassCard renders that field raw
with no i18n_catalog lookup at all, the same pre-existing gap every other
note-bearing card (MinimalistTaskbar, ClassicContextMenu) already has.
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from frontend import theme as TH


_SYSTEM_TWEAKS_PAGE_INDEX = 1  # CATEGORIES[1] == "system" (System & Tweaks)

_START_MENU_TITLES = [
    "Remove Start Recommendations",
    "Disable Start Web Search",
    "Disable Recent-Item Tracking",
    "Disable Start Suggestions",
]
_FILE_EXPLORER_TITLES = [
    "Launch to This PC",
    "Always Show File Extensions",
    "Show Hidden Files",
    "Show Protected System Files",
    "Remove Explorer Recommendations",
]
_ALL_TITLES = _START_MENU_TITLES + _FILE_EXPLORER_TITLES

_EXPECTED_ARABIC_TITLES = {
    "Remove Start Recommendations": "إزالة توصيات قائمة ابدأ",
    "Disable Start Web Search": "تعطيل بحث الويب في قائمة ابدأ",
    "Disable Recent-Item Tracking": "تعطيل تتبع العناصر الأخيرة",
    "Disable Start Suggestions": "تعطيل اقتراحات قائمة ابدأ",
    "Launch to This PC": "الانتقال إلى هذا الجهاز",
    "Always Show File Extensions": "إظهار امتدادات الملفات دائمًا",
    "Show Hidden Files": "إظهار الملفات المخفية",
    "Show Protected System Files": "إظهار ملفات النظام المحمية",
    "Remove Explorer Recommendations": "إزالة توصيات مستكشف الملفات",
}


def _card_by_title(page, title: str):
    for card in page.cards:
        if card.item.get("title") == title:
            return card
    raise AssertionError(f"no card titled {title!r} on this page")


class TestStartMenuFileExplorerCardsExist:
    def test_all_nine_cards_are_on_the_system_tweaks_page(self, window):
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        titles = {card.item.get("title") for card in page.cards}
        missing = [t for t in _ALL_TITLES if t not in titles]
        assert not missing, f"missing cards: {missing}"

    def test_every_card_task_matches_its_glyph_and_is_unique(self, window):
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        for title in _ALL_TITLES:
            card = _card_by_title(page, title)
            glyph_key = card.item.get("glyph")
            assert glyph_key in TH.GLYPHS, f"{title!r} glyph {glyph_key!r} missing from GLYPHS"


class TestStartMenuFileExplorerTranslation:
    def test_defaults_to_english(self, window):
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        for title in _ALL_TITLES:
            card = _card_by_title(page, title)
            assert card._title.fullText() == title

    def test_the_band_headers_translate(self, window, qapp):
        before = window._language
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        try:
            page.retranslate("ar")
            qapp.processEvents()
            band_labels = {
                header.findChild(QLabel, "bandTitle").text()
                for header, _cards in page._bands if header is not None
            }
            assert "قائمة ابدأ" in band_labels
            assert "مستكشف الملفات" in band_labels
        finally:
            page.retranslate(before)
            qapp.processEvents()

    def test_every_card_title_and_description_translate(self, window, qapp):
        before = window._language
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        try:
            page.retranslate("ar")
            qapp.processEvents()
            for title, expected_ar in _EXPECTED_ARABIC_TITLES.items():
                card = _card_by_title(page, title)
                assert card._title.fullText() == expected_ar
                # every description must have actually changed from the
                # English source — i.e. it is not silently falling back
                assert card._desc.fullText() != card.item["desc"]
        finally:
            page.retranslate(before)
            qapp.processEvents()

    def test_retranslating_back_to_english_is_lossless(self, window, qapp):
        before = window._language
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        try:
            page.retranslate("ar")
            qapp.processEvents()
            page.retranslate("en")
            qapp.processEvents()
            for title in _ALL_TITLES:
                card = _card_by_title(page, title)
                assert card._title.fullText() == title
        finally:
            page.retranslate(before)
            qapp.processEvents()
