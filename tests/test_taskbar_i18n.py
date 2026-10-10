"""
Arabic for the v1.2 "TASKBAR" band (System & Tweaks) — five granular,
independently-revertible registry toggles (TaskbarSearchIconOnly,
TaskbarShowEndTask, TaskbarHideCopilot, TaskbarHideTaskView,
TaskbarDisableTransparency).

Ordinary menu_structure.py catalog data, so it translates through the same
mechanism every other card on this page already uses — frontend.
i18n_catalog's exact-English-text lookup (TITLES/DESCRIPTIONS) via
GlassCard.retranslate() — and this file follows the same pattern as
test_start_menu_file_explorer_i18n.py rather than inventing a new one.

NOT COVERED, on purpose: each card's `note` field ("Windows 11, version
23H2 or later" / "Windows 11 only") — GlassCard renders that field raw
with no i18n_catalog lookup at all, the same pre-existing gap every other
note-bearing card (MinimalistTaskbar, StartHideRecommended) already has.
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from frontend import theme as TH


_SYSTEM_TWEAKS_PAGE_INDEX = 1  # CATEGORIES[1] == "system" (System & Tweaks)

_TASKBAR_TITLES = [
    "Compact Search Box",
    "Enable Taskbar End Task",
    "Hide Copilot Button",
    "Hide Task View Button",
    "Disable Transparency Effects",
]

_EXPECTED_ARABIC_TITLES = {
    "Compact Search Box": "مربع بحث مضغوط",
    "Enable Taskbar End Task": "تفعيل ‘إنهاء المهمة’ في شريط المهام",
    "Hide Copilot Button": "إخفاء زر Copilot",
    "Hide Task View Button": "إخفاء زر عرض المهام",
    "Disable Transparency Effects": "تعطيل تأثيرات الشفافية",
}


def _card_by_title(page, title: str):
    for card in page.cards:
        if card.item.get("title") == title:
            return card
    raise AssertionError(f"no card titled {title!r} on this page")


class TestTaskbarCardsExist:
    def test_all_five_cards_are_on_the_system_tweaks_page(self, window):
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        titles = {card.item.get("title") for card in page.cards}
        missing = [t for t in _TASKBAR_TITLES if t not in titles]
        assert not missing, f"missing cards: {missing}"

    def test_every_card_task_matches_its_glyph_and_is_unique(self, window):
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        for title in _TASKBAR_TITLES:
            card = _card_by_title(page, title)
            glyph_key = card.item.get("glyph")
            assert glyph_key in TH.GLYPHS, f"{title!r} glyph {glyph_key!r} missing from GLYPHS"

    def test_no_task_name_collides_with_an_existing_card(self, window):
        # The whole reason this batch is built on different registry
        # values than the bundled Minimalist Taskbar tweak — see
        # 01-Catalogs.ps1's comment on the catalog entries themselves.
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        tasks = [card.item.get("task") for card in page.cards if card.item.get("task")]
        assert len(tasks) == len(set(tasks)), "duplicate task name on System & Tweaks"


class TestTaskbarTranslation:
    def test_defaults_to_english(self, window):
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        for title in _TASKBAR_TITLES:
            card = _card_by_title(page, title)
            assert card._title.fullText() == title

    def test_the_band_header_translates(self, window, qapp):
        before = window._language
        page = window.pages[_SYSTEM_TWEAKS_PAGE_INDEX]
        try:
            page.retranslate("ar")
            qapp.processEvents()
            band_labels = {
                header.findChild(QLabel, "bandTitle").text()
                for header, _cards in page._bands if header is not None
            }
            assert "شريط المهام" in band_labels
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
            for title in _TASKBAR_TITLES:
                card = _card_by_title(page, title)
                assert card._title.fullText() == title
        finally:
            page.retranslate(before)
            qapp.processEvents()
