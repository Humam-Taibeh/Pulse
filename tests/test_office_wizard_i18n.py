"""
Arabic for OfficeWizardDialog and ToolInstallWizardDialog (v10.17.1) — the
two surfaces frontend/i18n.py's and i18n_catalog.py's own scope notes, and
every CHANGELOG.md entry through v10.17.0, named explicitly as the last
still-English "dialogs reached from a card" (alongside the Restore Point
Browser and Health Report, which stay out of scope here on purpose).

WHAT TRANSLATES: every static chrome string across all five OfficeWizard
steps (choice, auto_confirm, guide, locate, confirm) — the step subtitle,
every label/button/tooltip, the three choice-page GlassCards (routed
through frontend.i18n_catalog, same lookup-by-English-text mechanism
every other card uses) — and ToolInstallWizardDialog's note/buttons/
tooltip, plus the one caller-supplied `desc` PulseApp's bundled-app
restore flow opens it with.

WHAT STAYS ENGLISH, on purpose: product/brand names (Office, Word,
Excel...), file paths and file names (setup.exe, configuration.xml, a
detected folder path), and the QSS embedded in f-strings (not content).

BOTH DIALOGS ARE BUILT FRESH ON EVERY OPEN, so `lang` is read once at
construction — no retranslate() to test, same shape as CommandPalette/
SoftwareCatalogDialog/the three test_ops_dialogs_i18n.py dialogs.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from frontend import widgets as W


def _texts(dialog) -> set[str]:
    """Every QLabel's rendered text, PLUS fullText() for any label that
    carries one (ClampedLabel/ElidedCaption, used by GlassCard's title/
    desc) — .text() alone would miss a card title/desc that is currently
    elided, same pitfall test_catalog_i18n.py's own round-trip tests
    guard against."""
    out: set[str] = set()
    for lbl in dialog.findChildren(QLabel):
        out.add(lbl.text())
        full = getattr(lbl, "fullText", None)
        if full is not None:
            out.add(full())
    return out


# ============================================================
#  OFFICE WIZARD
# ============================================================
def _office_wizard(window, qapp, lang="en"):
    dialog = W.OfficeWizardDialog(window, window.theme.t, lang=lang)
    dialog.show()
    qapp.processEvents()
    return dialog


class TestOfficeWizardTranslation:

    def test_defaults_to_english(self, window, qapp):
        dialog = _office_wizard(window, qapp)
        try:
            texts = _texts(dialog)
            assert any("Microsoft Office Deployment" in t for t in texts)
            assert dialog._step_label.text() == "Choose how you'd like to proceed"
            assert any("Automated Cloud Download" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_title_and_choice_step_translate(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            texts = _texts(dialog)
            assert any("نشر Microsoft Office" in t for t in texts)
            assert dialog._step_label.text() == "اختر كيف تريد المتابعة"
            assert any("لدي مجلد Office جاهز بالفعل" in t for t in texts)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_cancel_button_translates(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "إلغاء" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_step_label_updates_per_page_in_arabic(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            dialog._goto("auto_confirm")
            assert dialog._step_label.text() == "تنزيل سحابي تلقائي"
            dialog._goto("guide")
            assert dialog._step_label.text() == "دليل المبتدئين — احصل على الأدوات الرسمية"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_auto_download_page_translates(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            dialog._goto("auto_confirm")
            qapp.processEvents()
            texts = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "سيُنزِّل Pulse عميل" in texts
            assert "مهم: عند ظهور نافذة إعداد Microsoft" in texts
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "تنزيل && تثبيت الآن" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_guide_page_translates(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            dialog._goto("guide")
            qapp.processEvents()
            texts = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "افتح أداة النشر أدناه" in texts
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "🌐  فتح أداة نشر Office   ↗" in labels
            assert "لدي الملفات الآن  ›" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_locate_found_page_translates(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            dialog._goto("locate")
            setup = Path(r"C:\Users\Test\Desktop\Office\setup.exe")
            config = Path(r"C:\Users\Test\Desktop\Office\configuration.xml")
            dialog._render_locate_found(r"C:\Users\Test\Desktop\Office", setup, [config])
            qapp.processEvents()
            texts = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "وُجد في" in texts
            assert "الإعداد:" in texts and "التكوين:" in texts
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "متابعة  ›" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_locate_found_multi_config_picker_translates(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            dialog._goto("locate")
            setup = Path(r"C:\Office\setup.exe")
            configs = [Path(r"C:\Office\configuration.xml"),
                       Path(r"C:\Office\configuration-Office365-x64.xml")]
            dialog._render_locate_found(r"C:\Office", setup, configs)
            qapp.processEvents()
            texts = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "أيها يجب أن يستخدم Pulse" in texts
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert any("(موصى به)" in t for t in labels)
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_locate_missing_page_translates(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            dialog._goto("locate")
            dialog._render_locate_missing(r"C:\Users\Test\Desktop\Office")
            qapp.processEvents()
            texts = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "لم يُعثر تلقائيًا على مجلد Office" in texts
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "إعادة محاولة الاكتشاف التلقائي" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_browse_incomplete_page_translates(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            dialog._goto("locate")
            dialog._render_browse_incomplete(r"C:\SomeFolder", None, [])
            qapp.processEvents()
            texts = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "ينقصه" in texts
            assert "setup.exe" in texts   # the missing-item names stay English
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "تصفّح مجددًا" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_confirm_page_translates(self, window, qapp):
        dialog = _office_wizard(window, qapp, lang="ar")
        try:
            dialog.setup_path = r"C:\Office\setup.exe"
            dialog.config_path = r"C:\Office\configuration.xml"
            dialog._goto("confirm")
            qapp.processEvents()
            assert dialog._step_label.text() == "تأكيد وتثبيت"
            texts = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "الإعداد:" in texts and "التكوين:" in texts
            assert "مهم: عند ظهور نافذة إعداد Microsoft" in texts
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "تثبيت الآن" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  TOOL INSTALL WIZARD (per-app winget option picker)
# ============================================================
def _tool_wizard(window, qapp, lang="en", url="https://example.com/app"):
    dialog = W.ToolInstallWizardDialog(
        window, "Example.App", "Example App",
        "Example App is a thing that does things.", url, window.theme.t,
        lang=lang)
    dialog.show()
    qapp.processEvents()
    return dialog


class TestToolInstallWizardTranslation:

    def test_defaults_to_english(self, window, qapp):
        dialog = _tool_wizard(window, qapp)
        try:
            assert dialog.install_btn.text() == "Automated Install (winget)"
            assert dialog.website_btn.text() == "Visit Official Website"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_translates_to_arabic(self, window, qapp):
        dialog = _tool_wizard(window, qapp, lang="ar")
        try:
            assert dialog.install_btn.text() == "تثبيت تلقائي (winget)"
            assert dialog.website_btn.text() == "زيارة الموقع الرسمي"
            assert dialog.website_btn.toolTip() == \
                "يفتح صفحة تنزيل Example App الرسمية في متصفحك."
            texts = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "يثبِّت Pulse هذا بصمت عبر winget" in texts
            labels = {b.text() for b in dialog.findChildren(QPushButton)}
            assert "إلغاء" in labels
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_generic_website_tooltip_translates_when_no_url(self, window, qapp):
        dialog = _tool_wizard(window, qapp, lang="ar", url="")
        try:
            assert dialog.website_btn.toolTip() == \
                "يفتح بحثًا على الويب عن صفحة التنزيل الرسمية."
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_restore_flow_desc_translates(self, window, qapp):
        """PulseApp._RESTORE_TARGETS is the one caller that supplies its
        own `desc` (not catalog text) — main.py routes it through
        tool_install.not_installed_desc so it isn't the one English
        sentence left inside an otherwise-Arabic dialog."""
        from frontend import i18n

        assert i18n.tr("tool_install.not_installed_desc", "ar").format(
            name="Microsoft Edge") == "Microsoft Edge غير مثبَّت حاليًا. اختر كيف تريد إعادته."
