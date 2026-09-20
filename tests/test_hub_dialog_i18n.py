"""
Arabic for HubDialog and ActionRow (v10.17.2) — the shell every "PATH
Doctor", "Leftovers Cleaner", "Microsoft Edge", "Microsoft OneDrive" and
"Network & Connectivity" card opens into. The hub CARD itself already
translated (v16 — a hub is a GlassCard like any other), but the DIALOG
it opens read hub['title']/hub['desc']/item['title']/item['desc'] as raw
English, never routing through i18n_catalog at all — the exact
inconsistency this closes: a user who reads a translated Arabic card and
clicks it should not land on an all-English sheet.

WHAT TRANSLATES: the dialog's own title/desc (routed through the SAME
i18n_catalog entries the card already used), every ActionRow's title/
desc (new i18n_catalog entries — these only ever appear inside the
dialog, never as a card of their own), the action verb on each row's
button ("Scan"/"Restore"/"Prune"/... — i18n.py's hub.action.* keys,
reused across every hub), and the Close button.

WHAT STAYS ENGLISH, on purpose: product/brand names (Microsoft Edge,
Microsoft OneDrive, Winsock, TCP/IP, Intel/Realtek) — same convention
every other catalog translation already follows.

BOTH ARE BUILT FRESH ON EVERY OPEN, so `lang` is read once at
construction — no retranslate() to test, same shape as CommandPalette/
SoftwareCatalogDialog/the Office wizard.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from frontend import widgets as W
from frontend.menu_structure import CATEGORIES, category_items


def _shipped_hubs():
    """Read off the real menu structure, same discovery
    test_layout_contract.py's action-band tests already use — a hub
    added later is covered without anyone remembering to list it here."""
    return [item for cat in CATEGORIES for item in category_items(cat)
            if item.get("hub")]


def _texts(dialog) -> set[str]:
    out: set[str] = set()
    for lbl in dialog.findChildren(QLabel):
        out.add(lbl.text())
        full = getattr(lbl, "fullText", None)
        if full is not None:
            out.add(full())
    return out


HUBS = _shipped_hubs()
HUB_IDS = [hub["title"] for hub in HUBS]


def test_there_are_hubs_to_test():
    assert HUBS, "no hub cards found in the menu structure"


class TestHubDialogTranslation:

    @pytest.mark.parametrize("hub", HUBS, ids=HUB_IDS)
    def test_defaults_to_english(self, window, qapp, hub):
        dialog = W.HubDialog(window, hub, window.theme.t)
        try:
            texts = _texts(dialog)
            assert any(hub["title"] in t for t in texts)
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "Close" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    @pytest.mark.parametrize("hub", HUBS, ids=HUB_IDS)
    def test_the_dialog_and_every_row_translate_to_arabic(
            self, window, qapp, hub):
        from frontend import i18n_catalog as I18N_CAT

        dialog = W.HubDialog(window, hub, window.theme.t, lang="ar")
        try:
            texts = _texts(dialog)
            expected_title = I18N_CAT.tr_title(hub["title"], "ar")
            assert any(expected_title in t for t in texts), (
                f"{hub['title']!r} did not translate in its own dialog "
                f"({expected_title!r} not found)")
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "إغلاق" in labels

            for item in hub.get("items", []):
                expected = I18N_CAT.tr_title(item["title"], "ar")
                assert expected in texts, (
                    f"row {item['title']!r} did not translate "
                    f"({expected!r} not found)")
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    @pytest.mark.parametrize("hub", HUBS, ids=HUB_IDS)
    def test_no_row_button_is_still_an_english_verb_leftover(
            self, window, qapp, hub):
        """Every item this catalog ships supplies an explicit English
        "action" verb — this proves every one of them is in
        ActionRow._ACTION_VERB_KEYS, not just the ones this file happens
        to spell out."""
        dialog = W.HubDialog(window, hub, window.theme.t, lang="ar")
        try:
            rows = dialog.findChildren(W.ActionRow)
            assert rows, f"{hub['title']!r} opened with no ActionRows"
            for row in rows:
                verb = row.item.get("action")
                if not verb:
                    continue
                assert verb in W.ActionRow._ACTION_VERB_KEYS, (
                    f"{hub['title']!r} row {row.item['title']!r} uses "
                    f"action verb {verb!r}, which has no Arabic "
                    f"translation in ActionRow._ACTION_VERB_KEYS")
                assert row.button.text() != verb, (
                    f"{hub['title']!r} row {row.item['title']!r} still "
                    f"shows the raw English verb {verb!r} under Arabic")
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


class TestActionRowTranslation:

    def test_defaults_to_english(self, qapp, window):
        row = W.ActionRow({"title": "Prune Dead & Duplicate Entries",
                           "desc": "d"}, window.theme.t,
                          window.theme.t["accent"], "Prune")
        try:
            assert row._title.text() == "Prune Dead & Duplicate Entries"
            assert row.button.text() == "Prune"
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_translates_title_desc_and_verb(self, qapp, window):
        row = W.ActionRow(
            {"title": "Prune Dead & Duplicate Entries",
             "desc": "Removes only what is provably safe: duplicates, "
                     "unparseable entries, and folders missing from a "
                     "mounted internal disk. A restore point and a copy "
                     "of your current PATH are saved first."},
            window.theme.t, window.theme.t["accent"], "Prune", lang="ar")
        try:
            assert row._title.text() == "تقليم الإدخالات الميتة والمكرَّرة"
            assert row.button.text() == "تقليم"
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_the_danger_fallback_verb_translates_too(self, qapp, window):
        """No explicit "action" — _default_label's own fallback
        ("Remove" for a danger row) must translate exactly like an
        explicit one."""
        row = W.ActionRow({"title": "x", "desc": "d", "danger": True},
                          window.theme.t, window.theme.t["accent"],
                          lang="ar")
        try:
            assert row.button.text() == "إزالة"
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_the_neutral_fallback_verb_translates_too(self, qapp, window):
        row = W.ActionRow({"title": "x", "desc": "d"}, window.theme.t,
                          window.theme.t["accent"], lang="ar")
        try:
            assert row.button.text() == "تشغيل"
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_an_unknown_verb_degrades_to_itself(self, qapp, window):
        """The same "never crash, never block" contract i18n.tr() and
        i18n_catalog's own lookups hold — a verb this table has not
        learned yet must still render, in English, rather than raising
        or showing a blank button."""
        row = W.ActionRow({"title": "x", "desc": "d"}, window.theme.t,
                          window.theme.t["accent"], "Frobnicate", lang="ar")
        try:
            assert row.button.text() == "Frobnicate"
        finally:
            row.deleteLater(); qapp.processEvents()
