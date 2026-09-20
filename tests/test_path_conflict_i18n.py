"""
Arabic for PathConflictDialog — PATH Doctor's "Fix Shadowed Tools" card
(v10.17.2) — and the widgets.InspectorDialog base shell it and every
other read-only inspector build on (PowerHealthDialog, StorageAnalyzerDialog,
DnsSwitcherDialog, ContextMenuDialog; RestorePointDialog deliberately
excluded — the Restore Point Browser stays English on purpose, see
frontend/i18n.py's own module docstring).

WHAT TRANSLATES: the dialog's title/loading line (TITLE_KEY/LOADING_KEY),
Close/Re-scan/Restart-as-administrator and its tooltip, every status
sentence, the per-toolchain badge and "Commands" label, System/Your PATH,
the "+N more folder(s)" suffix, and the backend's own short verdict
button text ("Use this one"/"In use"/"Needs administrator"/...) — Pulse's
own deterministic copy, translated via i18n_catalog exactly like
BloatRow's Note/StartupRow's Reason.

WHAT STAYS ENGLISH, on purpose: the long-form `reason` tooltip (backend-
authored, freely interpolated with paths/counts — the same "live/dynamic
explanation" boundary the console log and a scan's own caveat already
sit on), and TaskResult.message when the backend actually supplies one.

BUILT FRESH ON EVERY OPEN, so `lang` is read once at construction — no
retranslate() to test.
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


def _report(**overrides) -> dict:
    report = {
        "entries": 24,
        "elevated": True,
        "conflicts": [{
            "key": "python",
            "command": "Python",
            "commands": ["pip", "python"],
            "count": 2,
            "options": [
                {"path": r"C:\Python311",
                 "dirs": [r"C:\Python311\Scripts", r"C:\Python311"],
                 "scope": "Machine", "version": "3.11.9",
                 "commands": ["pip", "python"], "winner": True,
                 "action": "none", "short": "In use",
                 "reason": "Python already runs from C:\\Python311."},
                {"path": r"C:\Python313",
                 "dirs": [r"C:\Python313"],
                 "scope": "User", "version": "3.13.1",
                 "commands": ["python"], "winner": False,
                 "action": "blocked", "short": "Needs administrator",
                 "reason": "Run Pulse as administrator to promote this one."},
            ],
        }],
    }
    report.update(overrides)
    return report


class TestPathConflictDialogTranslation:

    def test_defaults_to_english(self, window, qapp):
        dialog = W.PathConflictDialog(window, "", window.theme.t)
        try:
            texts = _texts(dialog)
            assert any("Shadowed Tools" in t for t in texts)
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "Close" in labels
            assert "Re-scan" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_title_and_chrome_translate_to_arabic(self, window, qapp):
        dialog = W.PathConflictDialog(window, "", window.theme.t, lang="ar")
        try:
            texts = _texts(dialog)
            assert any("الأدوات المتراكبة" in t for t in texts)
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "إغلاق" in labels
            assert "إعادة الفحص" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_no_conflicts_state_translates(self, window, qapp):
        dialog = W.PathConflictDialog(window, "", window.theme.t, lang="ar")
        try:
            # No processEvents() between construction and _render(): the
            # constructor queues QTimer.singleShot(0, self._start), and
            # letting that fire here would overwrite this manual render
            # with the (unconfigured ps1_path="") engine-unavailable
            # status — the same race test_path_priority.py's own
            # PathConflictDialog tests already avoid.
            dialog._render(_report(conflicts=[]))
            texts = _texts(dialog)
            assert any("لا شيء متراكب" in t for t in texts)
            assert any("لا شيء لإصلاحه" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_conflict_status_and_cards_translate(self, window, qapp):
        dialog = W.PathConflictDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render(_report())
            texts = _texts(dialog)
            assert any("سلسلة أدوات واحدة" in t for t in texts)
            # the backend's own verdict strings, translated via
            # i18n_catalog — both are BUTTON labels, not QLabels
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "قيد الاستخدام" in labels
            assert "يتطلب صلاحيات المسؤول" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_plural_conflict_status_translates(self, window, qapp):
        dialog = W.PathConflictDialog(window, "", window.theme.t, lang="ar")
        try:
            two = _report()
            two["conflicts"].append(dict(two["conflicts"][0], key="node",
                                         command="Node"))
            dialog._render(two)
            texts = _texts(dialog)
            assert any("سلاسل أدوات" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_elevate_button_and_tooltip_translate_when_shown(
            self, window, qapp):
        dialog = W.PathConflictDialog(window, "", window.theme.t,
                                      is_admin=False, lang="ar")
        try:
            dialog._render(_report())
            assert not dialog._elevate_btn.isHidden()
            assert dialog._elevate_btn.text() == "إعادة التشغيل كمسؤول"
            assert "صلاحيات مرتفعة" in dialog._elevate_btn.toolTip()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_an_unmapped_verdict_string_degrades_to_itself(self, window, qapp):
        """The same "never crash, never block" contract i18n_catalog's
        own lookups hold everywhere else."""
        dialog = W.PathConflictDialog(window, "", window.theme.t, lang="ar")
        try:
            odd = _report()
            odd["conflicts"][0]["options"][0]["short"] = "Something New"
            dialog._render(odd)
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "Something New" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


class TestInspectorDialogBaseTranslation:
    """RestorePointDialog is the control: it must NOT translate, proving
    TITLE_KEY/LOADING_KEY are opt-in rather than something a language
    switch forces onto every InspectorDialog subclass."""

    def test_restore_point_dialog_stays_english_even_if_asked(
            self, window, qapp):
        dialog = W.RestorePointDialog(window, "", window.theme.t)
        try:
            texts = _texts(dialog)
            assert any("Restore Point" in t for t in texts)
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "Close" in labels
            assert "إغلاق" not in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_a_missing_engine_message_translates(self, window, qapp):
        dialog = W.PathConflictDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._ps1 = ""
            dialog._start()
            assert "المحرك غير متاح" in dialog._status.text()
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()
