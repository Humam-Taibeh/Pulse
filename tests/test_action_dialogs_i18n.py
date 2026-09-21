"""
Arabic for the v10.17.3 "completion pass" dialogs — the seven that were
still English-only after the InspectorDialog shell, PathConflictDialog
and LeftoversDialog were translated: StorageAnalyzerDialog,
DnsSwitcherDialog, ContextMenuDialog, CloseConfirmDialog,
ElevatePromptDialog, ShortcutSheetDialog and SelfUpdateDialog.

(DataHygieneDialog, NoticeDialog, RevertChoiceDialog, PlaybookDialog,
ActivationStatusDialog and PowerHealthDialog were translated in the same
pass but already exercised by test_data_hygiene.py / test_task_preview.py
/ test_busy_state.py / test_contract.py / test_audit_hardening.py /
test_layout_contract.py — no dedicated file for those here.)

WHAT TRANSLATES: title/loading chrome (the two InspectorDialog subclasses
here — StorageAnalyzerDialog, DnsSwitcherDialog, ContextMenuDialog — opt
in via TITLE_KEY/LOADING_KEY exactly like PathConflictDialog/
PowerHealthDialog), every button/badge/tooltip/status sentence, and two
finite backend/app-owned string sets translated via i18n_catalog's
exact-text lookup: utils.updater.can_apply()'s one refusal reason, and
PulseApp.SHORTCUTS' nine row descriptions.

WHAT STAYS ENGLISH: size units (MB/GB/…, same "_human()" convention as
StorageAnalyzerDialog's own byte formatter and everywhere else in the
app), and TaskResult.message when the backend actually supplies one.

BUILT FRESH ON EVERY OPEN — no retranslate() to test. StorageAnalyzer/
DnsSwitcher/ContextMenu are constructed with ps1_path="" and rendered by
calling `_render()` directly, WITHOUT an intervening qapp.processEvents()
call — letting one through lets the constructor's queued
QTimer.singleShot(0, self._start) fire and clobber the manual render with
an "engine unavailable" status, the same race test_path_conflict_i18n.py
and test_path_priority.py already avoid.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from frontend import widgets as W


def _texts(dialog) -> set[str]:
    out: set[str] = set()
    for lbl in dialog.findChildren(QLabel):
        out.add(lbl.text())
        full = getattr(lbl, "fullText", None)
        if full is not None:
            out.add(full())
    return out


def _buttons(dialog) -> set[str]:
    return {b.text() for b in dialog.findChildren(QPushButton)}


# ============================================================
#  STORAGE ANALYZER
# ============================================================
def _storage_report(**overrides) -> dict:
    report = {
        "available": True,
        "scanPath": "C:\\",
        "totalBytes": 50 * 1024 ** 3,
        "truncated": False,
        "roots": [{"path": "C:\\", "label": "Windows", "freeBytes": 10 * 1024 ** 3,
                   "totalBytes": 500 * 1024 ** 3}],
        "folders": [{"name": "Users", "path": r"C:\Users", "bytes": 30 * 1024 ** 3}],
        "files": [{"name": "big.bin", "path": r"C:\big.bin", "bytes": 5 * 1024 ** 3,
                   "modified": "2026-01-01"}],
    }
    report.update(overrides)
    return report


class TestStorageAnalyzerTranslation:
    def test_defaults_to_english(self, window, qapp):
        dialog = W.StorageAnalyzerDialog(window, "", window.theme.t)
        try:
            assert any("Storage Analyzer" in t for t in _texts(dialog))
            assert "Close" in _buttons(dialog)
            assert "Scan a Folder…" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_title_and_action_buttons_translate(self, window, qapp):
        dialog = W.StorageAnalyzerDialog(window, "", window.theme.t, lang="ar")
        try:
            assert any("محلِّل التخزين" in t for t in _texts(dialog))
            buttons = _buttons(dialog)
            assert "إغلاق" in buttons
            assert "إعادة الفحص" in buttons
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_drive_label_translates(self, window, qapp):
        dialog = W.StorageAnalyzerDialog(window, "", window.theme.t, lang="ar")
        try:
            assert any(t == "القرص" for t in _texts(dialog))
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_render_status_and_cards_translate(self, window, qapp):
        dialog = W.StorageAnalyzerDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_storage_report())
            texts = _texts(dialog)
            assert any("محسوبة" in t for t in texts)
            assert any(t == "أكبر المجلدات" for t in texts)
            assert any(t == "أكبر الملفات" for t in texts)
            assert any(t == "عن هذا التقرير" for t in texts)
            assert "إظهار" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_truncated_and_unavailable_states_translate(self, window, qapp):
        dialog = W.StorageAnalyzerDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_storage_report(truncated=True))
            texts = _texts(dialog)
            assert any("بلغ الفحص حد وقته المخصَّص" in t for t in texts)
            assert any(t == "فحص جزئي" for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_unreadable_path_state_translates(self, window, qapp):
        dialog = W.StorageAnalyzerDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_storage_report(available=False))
            texts = _texts(dialog)
            assert any("تعذّرت قراءة" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_empty_folder_and_file_notes_translate(self, window, qapp):
        dialog = W.StorageAnalyzerDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_storage_report(folders=[], files=[]))
            texts = _texts(dialog)
            assert any("لم تُوجد مجلدات فرعية" in t for t in texts)
            assert any("لم تُوجد ملفات قابلة للقراءة" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  DNS SWITCHER
# ============================================================
def _dns_report(**overrides) -> dict:
    report = {
        "dohSupported": True,
        "adapters": [{"name": "Ethernet", "activeKey": "dhcp", "v4": [],
                      "description": "Realtek PCIe GbE"}],
        "profiles": [{"key": "cloudflare", "name": "Cloudflare", "note": ""}],
    }
    report.update(overrides)
    return report


class TestDnsSwitcherTranslation:
    def test_defaults_to_english(self, window, qapp):
        dialog = W.DnsSwitcherDialog(window, "", window.theme.t)
        try:
            assert any("DNS & Network Profiles" in t for t in _texts(dialog))
            assert "Close" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_title_translates(self, window, qapp):
        dialog = W.DnsSwitcherDialog(window, "", window.theme.t, lang="ar")
        try:
            assert any("ملفات DNS والشبكة" in t for t in _texts(dialog))
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_no_adapters_state_translates(self, window, qapp):
        dialog = W.DnsSwitcherDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_dns_report(adapters=[]))
            texts = _texts(dialog)
            assert any("لم يُعثر على أي مهيّئ شبكة متصل" in t for t in texts)
            assert any(t == "المهيّئات" for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_an_adapter_card_translates_its_badge_and_rows(self, window, qapp):
        dialog = W.DnsSwitcherDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_dns_report())
            texts = _texts(dialog)
            assert any("متصل" in t for t in texts)
            buttons = _buttons(dialog)
            assert "تلقائي (DHCP)" in buttons
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_admin_required_card_translates_when_not_elevated(self, window, qapp):
        dialog = W.DnsSwitcherDialog(window, "", window.theme.t, is_admin=False, lang="ar")
        try:
            dialog._render(_dns_report())
            texts = _texts(dialog)
            assert any(t == "يتطلب صلاحيات المسؤول" for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_doh_unsupported_suffix_translates(self, window, qapp):
        dialog = W.DnsSwitcherDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_dns_report(dohSupported=False))
            texts = _texts(dialog)
            assert any("لا يمكن لهذا الإصدار من ويندوز تشفير DNS" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  CONTEXT MENU
# ============================================================
def _context_menu_report(**overrides) -> dict:
    report = {
        "hasBackup": True,
        "items": [
            {"managed": True, "enabled": True, "label": "Give access to",
             "scope": "HKCR", "owner": "shell32.dll", "clsid": "{111}"},
            {"managed": False, "enabled": True, "label": "Scan with Defender",
             "scope": "HKLM", "owner": "MsMpEng.exe", "clsid": "{222}"},
        ],
    }
    report.update(overrides)
    return report


class TestContextMenuTranslation:
    def test_defaults_to_english(self, window, qapp):
        dialog = W.ContextMenuDialog(window, "", window.theme.t)
        try:
            assert any("Right-Click Menu Entries" in t for t in _texts(dialog))
            assert "Restore All" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_title_and_restore_button_translate(self, window, qapp):
        dialog = W.ContextMenuDialog(window, "", window.theme.t, lang="ar")
        try:
            assert any("عناصر قائمة النقر بالزر الأيمن" in t for t in _texts(dialog))
            assert "استرجاع الكل" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_status_and_section_titles_translate(self, window, qapp):
        dialog = W.ContextMenuDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_context_menu_report())
            texts = _texts(dialog)
            assert any("معالِج(ات) مسجَّل(ة)" in t for t in texts)
            assert any(t == "العناصر القابلة للإدارة" for t in texts)
            assert any(t == "معالِجات أخرى" for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_toggle_row_visible_button_translates(self, window, qapp):
        dialog = W.ContextMenuDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_context_menu_report())
            assert "ظاهر" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_no_managed_note_translates(self, window, qapp):
        dialog = W.ContextMenuDialog(window, "", window.theme.t, lang="ar")
        try:
            only_other = _context_menu_report()
            only_other["items"] = [only_other["items"][1]]
            dialog._render(only_other)
            texts = _texts(dialog)
            assert any("لا يُدير Pulse أيًّا من المعالِجات" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  CLOSE CONFIRM
# ============================================================
class TestCloseConfirmTranslation:
    def test_defaults_to_english(self, window, qapp):
        dialog = W.CloseConfirmDialog(window, window.theme.t, "Deploying updates")
        try:
            texts = _texts(dialog)
            assert any("A task is still running" in t for t in texts)
            assert any("Deploying updates" in t for t in texts)
            assert "Keep Running" in _buttons(dialog)
            assert "Stop && Close" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_translates_to_arabic_with_the_task_title_interpolated(self, window, qapp):
        dialog = W.CloseConfirmDialog(window, window.theme.t, "Deploying updates", lang="ar")
        try:
            texts = _texts(dialog)
            assert any("لا تزال مهمة قيد التشغيل" in t for t in texts)
            assert any("Deploying updates" in t for t in texts), (
                "the running task's own title must stay as given, not be translated")
            buttons = _buttons(dialog)
            assert "متابعة التشغيل" in buttons
            assert "إيقاف && إغلاق" in buttons
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_default_task_name_translates_when_no_title_given(self, window, qapp):
        dialog = W.CloseConfirmDialog(window, window.theme.t, "", lang="ar")
        try:
            texts = _texts(dialog)
            assert any("عملية ما" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  ELEVATE PROMPT
# ============================================================
class TestElevatePromptTranslation:
    def test_defaults_to_english(self, window, qapp):
        dialog = W.ElevatePromptDialog(window, {"title": "Remove Edge"}, window.theme.t)
        try:
            texts = _texts(dialog)
            assert any("Administrator required" in t for t in texts)
            assert any("Remove Edge" in t for t in texts)
            assert "Relaunch as Administrator" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_translates_to_arabic_with_the_item_title_interpolated(self, window, qapp):
        dialog = W.ElevatePromptDialog(window, {"title": "Remove Edge"}, window.theme.t,
                                       lang="ar")
        try:
            texts = _texts(dialog)
            assert any("يتطلب صلاحيات المسؤول" in t for t in texts)
            assert any("Remove Edge" in t for t in texts), (
                "the action's own title must stay as given, not be translated")
            buttons = _buttons(dialog)
            assert "ليس الآن" in buttons
            assert "إعادة التشغيل كمسؤول" in buttons
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_default_action_name_translates_when_no_title_given(self, window, qapp):
        dialog = W.ElevatePromptDialog(window, {}, window.theme.t, lang="ar")
        try:
            texts = _texts(dialog)
            assert any("هذا الإجراء" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  SHORTCUT SHEET
# ============================================================
_SHORTCUTS = [
    ("Ctrl+K  or  Ctrl+F", "Search everything"),
    ("F1  or  ?", "This shortcut sheet"),
]


class TestShortcutSheetTranslation:
    def test_defaults_to_english(self, window, qapp):
        dialog = W.ShortcutSheetDialog(window, window.theme.t, _SHORTCUTS)
        try:
            texts = _texts(dialog)
            assert any("Keyboard shortcuts" in t for t in texts)
            assert any(t == "Search everything" for t in texts)
            assert "Close" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_header_close_button_and_row_descriptions_translate(self, window, qapp):
        dialog = W.ShortcutSheetDialog(window, window.theme.t, _SHORTCUTS, lang="ar")
        try:
            texts = _texts(dialog)
            assert any("اختصارات لوحة المفاتيح" in t for t in texts)
            assert any(t == "البحث في كل شيء" for t in texts)
            assert any(t == "ورقة الاختصارات هذه" for t in texts)
            # the key combination itself is not text to translate
            assert any(t == "Ctrl+K  or  Ctrl+F" for t in texts)
            assert "إغلاق" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  SELF UPDATE
# ============================================================
def _dummy_update(**overrides):
    from utils import updater
    fields = dict(
        version="99.0.0", tag="v99.0.0", notes="Test release notes.",
        url="https://example.invalid/PULSE_Setup_v99.0.0.exe",
        size=1024 * 1024, sums_url="https://example.invalid/SHA256SUMS",
        asset_name="PULSE_Setup_v99.0.0.exe", prerelease=False)
    fields.update(overrides)
    return updater.Update(**fields)


class TestSelfUpdateTranslation:
    def test_defaults_to_english(self, window, qapp):
        dialog = W.SelfUpdateDialog(window, window.theme.t, _dummy_update())
        try:
            texts = _texts(dialog)
            assert any("Pulse v99.0.0 is available" in t for t in texts)
            assert "Later" in _buttons(dialog)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_header_and_notes_page_buttons_translate(self, window, qapp):
        dialog = W.SelfUpdateDialog(window, window.theme.t, _dummy_update(), lang="ar")
        try:
            texts = _texts(dialog)
            assert any("الإصدار v99.0.0 من Pulse متاح" in t for t in texts)
            buttons = _buttons(dialog)
            assert "لاحقًا" in buttons
            # can_apply() is False off a pytest interpreter (not frozen),
            # so the notes page offers "View Release", not "Download &
            # Install" — see utils.updater.can_apply.
            assert "عرض الإصدار" in buttons
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_unfrozen_reason_note_translates(self, window, qapp):
        dialog = W.SelfUpdateDialog(window, window.theme.t, _dummy_update(), lang="ar")
        try:
            texts = _texts(dialog)
            assert any("يعمل Pulse من الشيفرة المصدرية" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_prerelease_tag_translates(self, window, qapp):
        dialog = W.SelfUpdateDialog(window, window.theme.t,
                                    _dummy_update(prerelease=True), lang="ar")
        try:
            texts = _texts(dialog)
            assert any(t == "1.0 MB  ·  إصدار تجريبي" for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_progress_and_verifying_labels_translate(self, window, qapp):
        dialog = W.SelfUpdateDialog(window, window.theme.t, _dummy_update(), lang="ar")
        try:
            dialog._on_progress(512 * 1024, 1024 * 1024)
            assert dialog._progress_label.text() == "جارٍ التنزيل… 0.5 / 1.0 MB"
            dialog._on_verifying()
            assert dialog._progress_label.text() == "جارٍ التحقق من SHA-256…"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_ready_page_translates(self, window, qapp):
        dialog = W.SelfUpdateDialog(window, window.theme.t, _dummy_update(), lang="ar")
        try:
            dialog._user_cancelled = False
            dialog._on_install_finished(True, r"C:\fake\installer.exe")
            texts = _texts(dialog)
            assert any("تم التحقق" in t for t in texts)
            assert any("99.0.0" in t for t in texts)
            buttons = _buttons(dialog)
            assert "إعادة التشغيل && التحديث" in buttons
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_error_page_translates(self, window, qapp):
        dialog = W.SelfUpdateDialog(window, window.theme.t, _dummy_update(), lang="ar")
        try:
            dialog._user_cancelled = False
            dialog._on_install_finished(False, "")
            texts = _texts(dialog)
            assert any("تعذّر تثبيت التحديث" in t for t in texts)
            buttons = _buttons(dialog)
            assert "إغلاق" in buttons
            assert "إعادة المحاولة" in buttons
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()
