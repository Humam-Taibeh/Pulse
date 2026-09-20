"""
Arabic for the three "primary interactive dialogs" named explicitly in
the v16.1 request — Update Center, Bloatware Purge, Startup Manager —
closing the gap the v16 translation pass left open: the dashboard,
category pages, cards, command palette and Software Catalog all
translated, but a user who actually clicked into one of these three
still hit an all-English dialog mid-session, which is the exact
"noticeable disconnect" the request named.

WHAT TRANSLATES: every static chrome string (headers, buttons, badges,
tooltips, section titles, empty/error/clean states, filter chips) plus
two backend-authored data tables that are Pulse's own copy, not a live
system's — BloatRow's "Note" field (01-Catalogs.ps1's $Script:BloatCatalog,
48 entries) and StartupRow's "Reason" field (05-Startup.ps1's rule
tables, 43 entries) — both routed through frontend.i18n_catalog exactly
like SOFTWARE_CATALOG's "why" field already was.

WHAT STAYS ENGLISH, on purpose: app/package/program NAMES (proper
nouns — "Google Chrome", "TikTok", "OneDrive"), and anything that is
itself live PowerShell output (TaskResult.message, the caveat a scan
appends when it could not read staged packages, a Trigger value the
backend supplies) — the same "live console stays English" boundary
already documented for the rest of the app.

ALL THREE DIALOGS ARE BUILT FRESH ON EVERY OPEN (their own class
docstrings say so), so `lang` is read once at construction, like
CommandPalette/SoftwareCatalogDialog — there is no retranslate() to
test here.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog, QLabel, QPushButton

from frontend import widgets as W
from utils.helpers import TaskResult


# ============================================================
#  UPDATE CENTER
# ============================================================
def _update_payload(*rows):
    return list(rows)


def _update_row(app_id, name, running=()):
    return {"Id": app_id, "Name": name, "CurrentVersion": "1.0",
            "AvailableVersion": "2.0", "Running": bool(running),
            "RunningProcesses": list(running)}


@pytest.fixture
def no_live_update_scan(monkeypatch):
    monkeypatch.setattr(W.UpdateCenterDialog, "_start_scan", lambda self: None)


def _update_center(window, qapp, lang="en"):
    dialog = W.UpdateCenterDialog(window, "", window.theme.t, lang=lang)
    dialog.show()
    qapp.processEvents()
    return dialog


class TestUpdateCenterTranslation:
    def test_defaults_to_english(self, window, qapp, no_live_update_scan):
        dialog = _update_center(window, qapp)
        try:
            texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
            assert any("Update Center" in t for t in texts)
            assert dialog._subtitle.text() == "Scanning installed apps against winget…"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_header_and_subtitle_translate(self, window, qapp, no_live_update_scan):
        dialog = _update_center(window, qapp, lang="ar")
        try:
            texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
            assert any("مركز التحديثات" in t for t in texts)
            assert dialog._subtitle.text() == "جارٍ فحص التطبيقات المثبَّتة عبر winget…"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_empty_state_translates(self, window, qapp, no_live_update_scan):
        dialog = _update_center(window, qapp, lang="ar")
        try:
            dialog._on_scan_finished(TaskResult(success=True, message="ok", data=[]))
            qapp.processEvents()
            assert dialog._stack.currentWidget() is dialog._empty_page
            # _empty_page's own static message (_build_empty_page), not
            # _subtitle's dynamic "up to date" line (a different key).
            texts = {lbl.text() for lbl in dialog._empty_page.findChildren(QLabel)}
            assert any("كل التطبيقات المثبَّتة عند أحدث إصدار لها" in t for t in texts), texts
            assert dialog._subtitle.text() == "كل التطبيقات المثبَّتة محدَّثة."
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_running_row_badge_and_tooltip_translate(self, window, qapp, no_live_update_scan):
        dialog = _update_center(window, qapp, lang="ar")
        try:
            dialog._on_scan_finished(TaskResult(
                success=True, message="ok",
                data=_update_payload(_update_row("Valve.Steam", "Steam", ["steam"]))))
            qapp.processEvents()
            row = dialog._rows["Valve.Steam"]
            assert row._running_chip.text() == "قيد التشغيل"
            assert "steam" in row._running_chip.toolTip()
            assert "سيُغلق" in row._running_chip.toolTip()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_website_button_tooltip_translates_with_the_app_name(
            self, window, qapp, no_live_update_scan):
        dialog = _update_center(window, qapp, lang="ar")
        try:
            dialog._on_scan_finished(TaskResult(
                success=True, message="ok",
                data=_update_payload(_update_row("7zip.7zip", "7-Zip"))))
            qapp.processEvents()
            row = dialog._rows["7zip.7zip"]
            assert "7-Zip" in row.website_btn.toolTip()
            assert "فتح صفحة تنزيل" in row.website_btn.toolTip()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_deploy_button_and_counter_translate(self, window, qapp, no_live_update_scan):
        dialog = _update_center(window, qapp, lang="ar")
        try:
            dialog._on_scan_finished(TaskResult(
                success=True, message="ok",
                data=_update_payload(_update_row("7zip.7zip", "7-Zip"),
                                     _update_row("Valve.Steam", "Steam"))))
            qapp.processEvents()
            assert dialog._count_label.text() == "2 محدَّد"
            assert dialog._deploy_btn.text() == "تحديث الكل (2)"
            dialog._rows["7zip.7zip"].checkbox.setChecked(False)
            qapp.processEvents()
            assert dialog._count_label.text() == "1 محدَّد"
            assert dialog._deploy_btn.text() == "تحديث المحدَّد (1)"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_running_confirmation_uses_the_singular_sentence(
            self, window, qapp, no_live_update_scan, monkeypatch):
        dialog = _update_center(window, qapp, lang="ar")
        try:
            dialog._on_scan_finished(TaskResult(
                success=True, message="ok",
                data=_update_payload(_update_row("Valve.Steam", "Steam", ["steam"]))))
            qapp.processEvents()
            captured = {}

            def grab(self):
                captured["title"] = self.findChild(QLabel, None) and " ".join(
                    lbl.text() for lbl in self.findChildren(QLabel))
                return QDialog.DialogCode.Rejected

            monkeypatch.setattr(W.ConfirmDialog, "exec", grab)
            dialog._accept_selection()
            qapp.processEvents()
            assert "بعض هذه التطبيقات قيد التشغيل" in captured["title"]
            assert "Steam" in captured["title"]
            assert "مفتوح الآن" in captured["title"], (
                "used the plural Arabic sentence for a single running app")
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_running_confirmation_uses_the_plural_sentence(
            self, window, qapp, no_live_update_scan, monkeypatch):
        dialog = _update_center(window, qapp, lang="ar")
        try:
            dialog._on_scan_finished(TaskResult(
                success=True, message="ok",
                data=_update_payload(
                    _update_row("Valve.Steam", "Steam", ["steam"]),
                    _update_row("Mozilla.Firefox", "Firefox", ["firefox"]))))
            qapp.processEvents()
            captured = {}

            def grab(self):
                captured["text"] = " ".join(
                    lbl.text() for lbl in self.findChildren(QLabel))
                return QDialog.DialogCode.Rejected

            monkeypatch.setattr(W.ConfirmDialog, "exec", grab)
            dialog._accept_selection()
            qapp.processEvents()
            assert "مفتوحة الآن" in captured["text"], (
                "used the singular Arabic sentence for two running apps")
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  BLOATWARE PURGE
# ============================================================
_BLOAT_ENTRIES = [
    {"Id": "BingNews", "Name": "News", "Group": "core",
     "Note": "MSN news feed.",
     "Detected": True, "Optional": False, "Installed": ["Microsoft.BingNews"],
     "Provisioned": [], "Desktop": []},
    {"Id": "TikTok", "Name": "TikTok", "Group": "promo",
     "Note": "Pre-installed on many OEM images.",
     "Detected": False, "Optional": False, "Installed": [],
     "Provisioned": [], "Desktop": []},
    {"Id": "XboxGamingOverlay", "Name": "Xbox Gaming Overlay",
     "Group": "gaming", "Note": "Game Bar itself, including its screen capture.",
     "Detected": True, "Optional": True,
     "Installed": ["Microsoft.XboxGamingOverlay"], "Provisioned": [],
     "Desktop": []},
]


@pytest.fixture
def no_live_bloat_scan(monkeypatch):
    monkeypatch.setattr(W.BloatwarePurgeDialog, "_start_scan", lambda self: None)


def _purge(window, qapp, lang="en", entries=None):
    dialog = W.BloatwarePurgeDialog(window, "", window.theme.t, lang=lang)
    dialog.show()
    qapp.processEvents()
    dialog._render(list(entries if entries is not None else _BLOAT_ENTRIES))
    qapp.processEvents()
    return dialog


class TestBloatwarePurgeTranslation:
    def test_defaults_to_english(self, window, qapp, no_live_bloat_scan):
        dialog = _purge(window, qapp)
        try:
            assert dialog._all_btn.text() == "Select All Installed"
            row = dialog._rows["BingNews"]
            assert row._badge.text() == "INSTALLED"
            # the note carries a package-name suffix (see BloatRow.__init__)
            # since this fixture entry declares an Installed package
            assert row._note.fullText().startswith("MSN news feed.")
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_header_and_toolbar_translate(self, window, qapp, no_live_bloat_scan):
        dialog = _purge(window, qapp, lang="ar")
        try:
            texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
            assert any("إزالة البرامج غير المرغوبة" in t for t in texts)
            assert dialog._all_btn.text() == "تحديد كل المثبَّت"
            assert dialog._stubs_btn.text() == "تحديد كل الامتدادات"
            assert dialog._none_btn.text() == "إلغاء تحديد الكل"
            assert dialog._show_absent.text() == "عرض الحزم غير المثبَّتة"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_section_header_translates_with_the_right_counts(
            self, window, qapp, no_live_bloat_scan):
        dialog = _purge(window, qapp, lang="ar")
        try:
            texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
            assert any(t == "امتدادات وترويجات مثبَّتة مسبقًا  ·  0 من 1 موجود"
                      for t in texts), texts
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_bloat_row_translates_its_badge_and_note(
            self, window, qapp, no_live_bloat_scan):
        dialog = _purge(window, qapp, lang="ar")
        try:
            row = dialog._rows["BingNews"]
            assert row._badge.text() == "مثبَّت"
            assert row._note.fullText().startswith("خلاصة أخبار MSN.")
            assert row.checkbox.text() == "News", "the package NAME must stay English"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_an_absent_row_translates_its_badge(self, window, qapp, no_live_bloat_scan):
        dialog = _purge(window, qapp, lang="ar")
        try:
            row = dialog._rows["TikTok"]
            assert row._badge.text() == "غير موجود"
            assert row._badge.toolTip() == "يتحقق Pulse من وجوده ولم يجده هنا."
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_optional_badge_translates(self, window, qapp, no_live_bloat_scan):
        dialog = _purge(window, qapp, lang="ar")
        try:
            row = dialog._rows["XboxGamingOverlay"]
            assert row._optional_badge.text() == "اختياري"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_count_and_purge_button_translate(self, window, qapp, no_live_bloat_scan):
        # _select_all(True) pre-ticks detected rows EXCEPT the optional
        # (Xbox) group — BingNews is the only detected, non-optional row
        # in _BLOAT_ENTRIES, so exactly one is pre-selected.
        dialog = _purge(window, qapp, lang="ar")
        try:
            assert dialog._count.text() == "1 محدَّد"
            assert dialog._purge_btn.text() == "إزالة آمنة (1)"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_cancel_becomes_close_on_a_clean_machine_in_arabic(
            self, window, qapp, no_live_bloat_scan):
        clean_entries = [{**e, "Detected": False} for e in _BLOAT_ENTRIES
                         if not e["Optional"]]
        dialog = _purge(window, qapp, lang="ar", entries=clean_entries)
        try:
            assert dialog._cancel_btn.text() == "إغلاق"
            texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
            assert "نظامك نظيف" in texts
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_no_match_message_translates(self, window, qapp, no_live_bloat_scan):
        dialog = _purge(window, qapp, lang="ar")
        try:
            dialog._search.setText("zzz_no_such_package_zzz")
            dialog._sync_visibility()
            qapp.processEvents()
            assert "لا يوجد مثبَّت يطابق" in dialog._no_match.text()
            assert "zzz_no_such_package_zzz" in dialog._no_match.text()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  STARTUP MANAGER
# ============================================================
_STARTUP_ITEMS = [
    {"Id": "a", "Name": "OneDrive", "Enabled": True, "Impact": "High",
     "Recommendation": "Disable",
     "Reason": "Cloud sync — keeps syncing in the background; launch it "
               "manually or sign in to files.com when you actually need it.",
     "Type": "Registry", "Protected": False, "TargetPresent": True},
    {"Id": "b", "Name": "RealtekAudio", "Enabled": True, "Impact": "Low",
     "Recommendation": "Keep",
     "Reason": "Audio driver tray helper — needed for sound device "
               "switching/effects to work correctly.",
     "Type": "Registry", "Protected": True, "TargetPresent": True},
    {"Id": "c", "Name": "Ghost", "Enabled": True, "Impact": "Medium",
     "Recommendation": "Review", "Reason": "Not a recognized publisher — "
     "check what it is before disabling it.",
     "Type": "Folder", "Protected": False, "TargetPresent": False},
]


@pytest.fixture
def no_live_startup_scan(monkeypatch):
    monkeypatch.setattr(W.StartupManagerDialog, "_start_scan", lambda self: None)


def _startup_manager(window, qapp, lang="en", items=None):
    dialog = W.StartupManagerDialog(window, "", window.theme.t, lang=lang)
    dialog.show()
    qapp.processEvents()
    dialog._populate_rows(list(items if items is not None else _STARTUP_ITEMS))
    dialog._stack.setCurrentWidget(dialog._results_page)
    qapp.processEvents()
    return dialog


class TestStartupManagerTranslation:
    def test_defaults_to_english(self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp)
        try:
            assert dialog._chip_all.text() == "All 3"
            row = dialog._rows["a"]
            assert row._rec_badge.text() == "Recommended to Disable"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_header_and_filter_chips_translate(self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
            assert any("مدير بدء التشغيل" in t for t in texts)
            assert dialog._chip_all.text() == "الكل 3"
            assert dialog._chip_enabled.text() == "3 مفعَّل"
            assert dialog._chip_recommended.text() == "1 يُنصح بتعطيله"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_row_recommendation_and_reason_translate(
            self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            row = dialog._rows["a"]
            assert row._rec_badge.text() == "يُنصح بتعطيله"
            assert "مزامنة سحابية" in row._meta.text()
            assert row._name.fullText() == "OneDrive", (
                "the entry's own NAME must stay English")
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_protected_row_shows_system_critical_and_its_tooltip(
            self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            row = dialog._rows["b"]
            assert row._rec_badge.text() == "حرج للنظام"
            assert "لا يوصي Pulse أبدًا" in row.toolTip()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_missing_target_row_shows_the_missing_badge_and_reason(
            self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            row = dialog._rows["c"]
            assert row._missing_badge.text() == "مفقود"
            assert "لم يعد مثبَّتًا" in row._meta.text()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_impact_badge_translates_when_estimated(
            self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            row = dialog._rows["a"]
            assert row._impact_badge.text() == "أثر عالي"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_impact_badge_translates_when_measured(
            self, window, qapp, no_live_startup_scan):
        items = [{**_STARTUP_ITEMS[0], "ImpactMeasured": True,
                  "BootDelayMs": 2500, "BootDelaySamples": 3}]
        dialog = _startup_manager(window, qapp, lang="ar", items=items)
        try:
            row = dialog._rows["a"]
            assert row._impact_badge.text() == "يؤخر الإقلاع 2.5 ث"
            assert "قاسه ويندوز" in row._impact_badge.toolTip()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_type_label_translates(self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            assert "السجل (مفتاح Run)" in dialog._rows["a"]._meta.text()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_section_headers_translate(self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
            assert any(t.startswith("⚠️  يُنصح بتعطيله   ·   1") for t in texts), texts
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_optimize_button_translates(self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            assert dialog._optimize_btn.text() == "تحسين بدء التشغيل (1)"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_boot_summary_base_sentence_translates(
            self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            dialog._subtitle.setText(
                W.StartupManagerDialog._boot_summary({}, [], "ar"))
            assert "قابلة للتراجع" in dialog._subtitle.text()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_filter_note_translates(self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            dialog._toggle_filter("recommended")
            qapp.processEvents()
            assert "مُصفًّى" in dialog._filter_note.text()
            assert "1 من 3" in dialog._filter_note.text()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_close_button_translates(self, window, qapp, no_live_startup_scan):
        dialog = _startup_manager(window, qapp, lang="ar")
        try:
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "إغلاق" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()
