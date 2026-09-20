"""
Arabic for the dashboard, the sidebar module labels, every CategoryPage's
own chrome, and the task-card catalog itself (v16) — the pass that
closes the gap v10.15's frontend/i18n.py deliberately left open
("translating only the sidebar button would read as broken, not as a
foundation").

LIVE PAGES NEED TELLING, NOT JUST BUILDING RIGHT. WelcomePage and every
CategoryPage are constructed once and kept alive for the app's lifetime,
so this file tests BOTH axes: a fresh construction under lang="ar", and
a live retranslate() call against a page that was already built in
English — the two paths that had to independently work for a running
session's language switch to be correct.
"""
from __future__ import annotations

import pytest

from frontend import i18n_catalog
from frontend import theme as TH
from frontend.widgets import GlassCard


# ============================================================
#  i18n_catalog itself
# ============================================================
class TestCatalogLookup:

    def test_english_passes_through_unchanged(self):
        assert i18n_catalog.tr_title("Software Management", "en") == \
            "Software Management"
        assert i18n_catalog.tr_desc(
            "Install, update and remove software", "en") == \
            "Install, update and remove software"

    def test_arabic_resolves_a_known_entry(self):
        assert i18n_catalog.tr_title("Software Management", "ar") == \
            "إدارة البرامج"

    def test_a_missing_arabic_entry_falls_back_to_english(self):
        """The same "never crash, never block" contract i18n.tr() holds
        — a card whose Arabic translation has not been written yet must
        still render, in English, rather than showing a raw dict-miss or
        raising."""
        assert i18n_catalog.tr_title("Something Not In The Table", "ar") == \
            "Something Not In The Table"
        assert i18n_catalog.tr_desc("Also not translated.", "ar") == \
            "Also not translated."


# ============================================================
#  GlassCard
# ============================================================
def _item(title="Software Management", desc="Install, update and remove software"):
    return {"glyph": "package", "title": title, "desc": desc}


class TestGlassCardTranslation:

    def test_constructing_in_arabic_shows_arabic_title_and_desc(self, qapp):
        t = TH.tokens("dark")
        card = GlassCard(_item(), "software", t, lang="ar")
        assert card._title.text() == "إدارة البرامج"
        assert card._desc.text() == "تثبيت البرامج وتحديثها وإزالتها"

    def test_defaults_to_english(self, qapp):
        t = TH.tokens("dark")
        card = GlassCard(_item(), "software", t)
        assert card._title.text() == "Software Management"

    def test_retranslate_updates_an_already_built_card(self, qapp):
        """The exact scenario GlassCard.retranslate exists for: a card
        built in English (the common case — WelcomePage/CategoryPage are
        constructed once, at launch) whose language changes live."""
        t = TH.tokens("dark")
        card = GlassCard(_item(), "software", t, lang="en")
        assert card._title.text() == "Software Management"
        card.retranslate("ar")
        assert card._title.text() == "إدارة البرامج"
        assert card._desc.text() == "تثبيت البرامج وتحديثها وإزالتها"

    def test_retranslate_back_to_english_is_lossless(self, qapp):
        t = TH.tokens("dark")
        card = GlassCard(_item(), "software", t, lang="en")
        card.retranslate("ar")
        card.retranslate("en")
        assert card._title.text() == "Software Management"
        assert card._desc.text() == "Install, update and remove software"

    def test_the_status_badge_translates(self, qapp):
        t = TH.tokens("dark")
        card = GlassCard(_item(), "software", t, lang="ar")
        card.set_applied("applied")
        assert card._applied_chip.text() == "مُطبَّق"
        card.retranslate("en")
        # set_applied is re-run by retranslate whenever a verdict is set
        assert card._applied_chip.text() == "APPLIED"

    def test_a_hub_cards_meta_pill_translates(self, qapp):
        item = {**_item(), "hub": True,
                "items": [{"title": "a"}, {"title": "b"}]}
        t = TH.tokens("dark")
        card = GlassCard(item, "software", t, lang="ar")
        assert card._meta_texts == ["2 خيارات"]
        card.retranslate("en")
        assert card._meta_texts == ["2 options"]

    def test_a_single_option_hub_uses_the_singular_form(self, qapp):
        item = {**_item(), "hub": True, "items": [{"title": "a"}]}
        t = TH.tokens("dark")
        card = GlassCard(item, "software", t, lang="ar")
        assert card._meta_texts == ["خيار واحد"]


# ============================================================
#  WelcomePage
# ============================================================
class TestWelcomePageTranslation:

    def test_constructing_in_arabic_translates_dashboard_chrome(
            self, window, qapp):
        from frontend.main import WelcomePage

        page = WelcomePage(window.theme.t, True, True, lang="ar")
        try:
            assert page._tag.fullText() == "أداة تنسيق ويندوز"
            assert page._health_section.text() == "حالة النظام"
            assert page._section.text() == "إجراءات سريعة"
            assert page._tiles["cpu"]._caption.text() == "حمل المعالج"
        finally:
            page.deleteLater()
            qapp.processEvents()

    def test_retranslate_updates_an_already_built_page(self, window, qapp):
        """The real scenario: window.welcome is built once, in English,
        at launch — this proves a live switch reaches it."""
        before = window._language
        try:
            assert window.welcome._tag.fullText() == "Windows Orchestration Toolkit"
            window.welcome.retranslate("ar")
            qapp.processEvents()
            assert window.welcome._tag.fullText() == "أداة تنسيق ويندوز"
            assert window.welcome._health_section.text() == "حالة النظام"
            for card in window.welcome.action_cards():
                # every quick-action title is a real catalog title, so it
                # must have moved off whatever English text it started at
                assert card._title.text() != ""
        finally:
            window.welcome.retranslate(before)
            qapp.processEvents()


class TestStorageTileTranslation:
    """A REAL BUG caught by the v16 Arabic smoke test, not by any of the
    tests above: the storage tile's headline value came straight from
    utils.helpers.SystemPulseSampler as a pre-formatted, English-only
    "{n:.0f} GB free" string — baked in below the i18n layer entirely,
    so it stayed "394 GB free" under Arabic. Worse, the tooltip template
    then appended its OWN "free" after that already-English text,
    producing "394 GB free free on the system drive". Fixed by having
    the sampler return the raw disk_free_gb float and formatting it at
    the call site through i18n, same shape as every other dashboard
    figure."""

    class _FakeSampler:
        def __init__(self, disk_free_gb):
            self._disk_free_gb = disk_free_gb

        def sample(self):
            return {"cpu": 0.1, "mem": 0.4, "mem_text": "6.4 / 16 GB",
                    "disk": 0.6, "disk_free_gb": self._disk_free_gb}

    def test_the_sampler_no_longer_pre_formats_english_text(self):
        from utils.helpers import SystemPulseSampler

        out = SystemPulseSampler().sample()
        assert "disk_text" not in out, (
            "the pre-formatted English disk_text key is back — main.py's "
            "tile value/tooltip must format disk_free_gb themselves")
        assert "disk_free_gb" in out

    def test_the_tile_value_translates(self, window, qapp):
        real_sampler = window.welcome._pulse_sampler
        window.welcome._pulse_sampler = self._FakeSampler(394.0)
        before = window._language
        try:
            window.welcome.retranslate("ar")
            window.welcome._tick_pulse()
            qapp.processEvents()
            assert window.welcome._tiles["storage"]._value.text() == \
                "394 GB خالية"
            assert "free" not in window.welcome._tiles["storage"]._value.text()
        finally:
            window.welcome.retranslate(before)
            window.welcome._pulse_sampler = real_sampler
            qapp.processEvents()

    def test_the_tooltip_does_not_duplicate_the_word_free(self, window, qapp):
        real_sampler = window.welcome._pulse_sampler
        window.welcome._pulse_sampler = self._FakeSampler(394.0)
        try:
            window.welcome._tick_pulse()
            qapp.processEvents()
            tooltip = window.welcome._tiles["storage"].toolTip()
            assert tooltip.count("free") == 1, (
                f"'free' appears {tooltip.count('free')} times: {tooltip!r}")
        finally:
            window.welcome._pulse_sampler = real_sampler
            qapp.processEvents()

    def test_a_missing_reading_shows_the_dash_placeholder(self, window, qapp):
        real_sampler = window.welcome._pulse_sampler
        window.welcome._pulse_sampler = self._FakeSampler(None)
        try:
            window.welcome._tick_pulse()
            qapp.processEvents()
            assert window.welcome._tiles["storage"]._value.text() == "—"
            assert window.welcome._tiles["storage"].toolTip() == ""
        finally:
            window.welcome._pulse_sampler = real_sampler
            qapp.processEvents()


# ============================================================
#  CategoryPage
# ============================================================
class TestCategoryPageTranslation:

    def test_constructing_in_arabic_translates_the_header(self, window, qapp):
        from frontend.main import CategoryPage
        from frontend.menu_structure import CATEGORIES

        page = CategoryPage(CATEGORIES[0], window.theme.t, lang="ar")
        try:
            assert page._title.text() == "إدارة البرامج"
            assert page._tagline.text() == "تثبيت البرامج وتحديثها وإزالتها"
            assert "الرئيسية" in page._home.text()
        finally:
            page.deleteLater()
            qapp.processEvents()

    def test_retranslate_updates_an_already_built_page(self, window, qapp):
        before = window._language
        page = window.pages[0]   # Software Management, built in English
        try:
            assert page._title.text() == "Software Management"
            page.retranslate("ar")
            qapp.processEvents()
            assert page._title.text() == "إدارة البرامج"
            assert page._tagline.text() == "تثبيت البرامج وتحديثها وإزالتها"
            assert "الرئيسية" in page._home.text()
            # the filter combo's items retranslate in place
            assert page._filter.itemText(0) == "كل العمليات"
            # every card on the page retranslated too
            for card in page.cards:
                assert card._title.text() != ""
        finally:
            page.retranslate(before)
            qapp.processEvents()

    def test_band_headers_translate(self, window, qapp):
        """Software Management is banded (INSTALL / MANAGE INSTALLED /
        PREINSTALLED & BUNDLED) — proves _band_titles stays correctly
        paired with _bands through a live switch."""
        from PySide6.QtWidgets import QLabel

        before = window._language
        page = window.pages[0]
        try:
            page.retranslate("ar")
            qapp.processEvents()
            band_labels = {
                header.findChild(QLabel, "bandTitle").text()
                for header, _cards in page._bands if header is not None
            }
            assert "تثبيت" in band_labels
        finally:
            page.retranslate(before)
            qapp.processEvents()

    def test_the_count_chip_translates(self, window, qapp):
        before = window._language
        page = window.pages[0]
        try:
            page.retranslate("ar")
            qapp.processEvents()
            # plural/singular form depends on the live card count, but
            # either way it must not still be showing the English word
            assert "OPERATION" not in page._count_chip.text()
        finally:
            page.retranslate(before)
            qapp.processEvents()


# ============================================================
#  A live switch reaches the currently-visible page too
# ============================================================
def test_a_language_switch_retranslates_the_open_category_page(window, qapp):
    before_lang = window._language
    try:
        window.open_category(0)
        qapp.processEvents()
        window._on_language_chosen("ar")
        qapp.processEvents()
        assert window.pages[0]._title.text() == "إدارة البرامج"
    finally:
        window._on_language_chosen(before_lang)
        window.go_home()
        qapp.processEvents()
