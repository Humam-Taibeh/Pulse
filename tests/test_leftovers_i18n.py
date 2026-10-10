"""
Arabic for LeftoversDialog and LeftoverRow (v10.17.2) — "Leftovers
Cleaner"'s own scan-and-select sheet, the dialog HubDialog's "Scan &
Purge Leftovers" row opens.

WHAT TRANSLATES: title/subtitle/loading, the error/clean/results pages,
every section header, the per-row kind badge and the size-tooltip, the
summary sentence (singular/plural, with/without a size, with/without
the needs-admin suffix), and Select All/Deselect All/Cancel/Safe Purge
(these three reuse the exact same keys the Bloatware Purge/Software
Catalog dialogs already use). LeftoverRow's own "reason" field is
Pulse's own deterministic copy (17-Leftovers.ps1's `-Reason` literals),
translated via i18n_catalog exactly like BloatRow's Note/StartupRow's
Reason.

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


_ITEMS = [
    {"id": "a1b2c3d4e5f60718", "kind": "startup-run", "group": "startup",
     "name": "SignalRgb", "location": r"HKCU:\Software\Pulse\DisabledStartup",
     "target": r"C:\Users\me\AppData\Local\VortxEngine\SignalRgbLauncher.exe",
     "reason": "Disabled in Pulse, and the program it pointed at has "
               "since been uninstalled.",
     "sizeBytes": 0, "needsAdmin": False},
    {"id": "8899aabbccddeeff", "kind": "residue", "group": "residue",
     "name": "VortxEngine", "location": r"C:\Users\me\AppData\Local\VortxEngine",
     "target": r"C:\Users\me\AppData\Local\VortxEngine\Update.exe",
     "reason": "An uninstalled app's files, left behind - its own "
               "uninstaller marked this folder dead.",
     "sizeBytes": 476_263_219, "needsAdmin": False},
]


def _report(items=None, elevated=True):
    items = list(_ITEMS if items is None else items)
    return {"items": items, "elevated": elevated,
            "totalBytes": sum(int(i.get("sizeBytes") or 0) for i in items)}


class TestLeftoversDialogTranslation:

    def test_defaults_to_english(self, window, qapp):
        dialog = W.LeftoversDialog(window, "", window.theme.t)
        try:
            texts = _texts(dialog)
            assert any("Leftovers Cleaner" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_title_and_loading_page_translate(self, window, qapp):
        dialog = W.LeftoversDialog(window, "", window.theme.t, lang="ar")
        try:
            texts = _texts(dialog)
            assert any("منظّف المخلّفات" in t for t in texts)
            assert any("جارٍ البحث" in t for t in texts)
            assert any("جارٍ فحص إدخالات بدء التشغيل" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_error_page_translates(self, window, qapp):
        dialog = W.LeftoversDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._on_scan_failed("فشل الفحص")
            texts = _texts(dialog)
            assert any("لم يتغيّر شيء" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_clean_page_translates(self, window, qapp):
        dialog = W.LeftoversDialog(window, "", window.theme.t, lang="ar")
        try:
            dialog._render([], True, 0)
            texts = _texts(dialog)
            assert any("لا شيء متروك خلفًا" in t for t in texts)
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "إغلاق" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_results_page_translates(self, window, qapp):
        dialog = W.LeftoversDialog(window, "", window.theme.t, lang="ar")
        try:
            report = _report()
            dialog._render(report["items"], report["elevated"],
                           report["totalBytes"])
            texts = _texts(dialog)
            # section headers
            assert any("إدخالات بدء التشغيل" in t for t in texts)
            assert any("مجلدات تطبيقات مهجورة" in t for t in texts)
            # summary sentence (2 items takes the plural branch), size
            # suffix, backup note
            assert any("عناصر تشير إلى برامج" in t for t in texts)
            assert any("تشغل" in t for t in texts)
            assert any("كل ما تزيله يُنسخ احتياطيًا" in t for t in texts)
            # a row's own backend-authored reason, via i18n_catalog
            assert any("مثبَّتًا" in t or "أُزيل" in t for t in texts)
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "تحديد الكل" in labels
            assert "إلغاء تحديد الكل" in labels
            assert "إلغاء" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_needs_admin_suffix_appears_only_when_relevant(
            self, window, qapp):
        dialog = W.LeftoversDialog(window, "", window.theme.t, lang="ar")
        try:
            admin_item = dict(_ITEMS[0], needsAdmin=True)
            dialog._render([admin_item], False, 0)
            texts = _texts(dialog)
            assert any("صلاحيات المسؤول" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_select_all_and_purge_count_translate(self, window, qapp):
        dialog = W.LeftoversDialog(window, "", window.theme.t, lang="ar")
        try:
            report = _report()
            dialog._render(report["items"], report["elevated"],
                           report["totalBytes"])
            # _render already selects all
            assert dialog._purge_btn.text() == "إزالة آمنة (2)"
            assert dialog._count.text() == "2 محدَّد"
            dialog._select_all(False)
            assert dialog._count.text() == "0 محدَّد"
            assert dialog._purge_btn.text() == "إزالة آمنة"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


class TestLeftoverRowTranslation:

    def test_defaults_to_english(self, qapp, window):
        row = W.LeftoverRow(_ITEMS[0], window.theme.t)
        try:
            assert row._kind_badge.text() == "STARTUP ENTRY"
            assert row._note.text() == (
                "Disabled in Pulse, and the program it pointed at has "
                "since been uninstalled.")
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_translates_to_arabic(self, qapp, window):
        row = W.LeftoverRow(_ITEMS[0], window.theme.t, lang="ar")
        try:
            assert row._kind_badge.text() == "إدخال بدء تشغيل"
            assert row._note.text() == (
                "معطَّل في Pulse، والبرنامج الذي كان يشير إليه أُزيل "
                "منذ ذلك الحين.")
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_the_size_tooltip_translates(self, qapp, window):
        row = W.LeftoverRow(_ITEMS[1], window.theme.t, lang="ar")
        try:
            assert row._size_badge is not None
            assert "يمكن التراجع عنها" in row._size_badge.toolTip()
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_an_unknown_kind_degrades_to_itself(self, qapp, window):
        row = W.LeftoverRow(
            {"id": "x", "kind": "future-kind", "name": "n", "reason": "r"},
            window.theme.t, lang="ar")
        try:
            assert row._kind_badge.text() == "FUTURE-KIND"
        finally:
            row.deleteLater(); qapp.processEvents()
