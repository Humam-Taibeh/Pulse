"""
src/frontend/i18n.py

DISPLAY LANGUAGE (v10.15) — a manual English/Arabic choice, not a
translated app.

WHAT THIS COVERS, ON PURPOSE. Retranslating the whole shell in one pass —
every module's task-card titles and descriptions (menu_structure.py),
the live PowerShell console log, playbooks, the Health Report — is a
much larger, separately-tracked effort (see ROADMAP.md). This first pass
covers the surfaces a user reaches before choosing what to do: the
sidebar rail, the Settings page itself (where the language picker lives),
the footer's tooltips, and the confirm-dialog chrome every destructive
action shares. A key with no entry in STRINGS degrades to the key
itself — visible-but-safe, matching theme.glyph()'s "a missing table
entry degrades, never crashes" posture — rather than raising, so a
half-translated surface never becomes a broken one.

NOT "FOLLOW WINDOWS". Unlike theme.py's system-sync mode, this reads no
OS locale API at all: a user picks English or Arabic, and that choice is
what set_language persists. There is nothing here for
tests/test_system_theme_events.py's exclusive-OS-read guard to cover,
because there is no OS read to guard.

RTL IS A LAYOUT DIRECTION, NOT A TRANSLATION DETAIL. is_rtl(lang) is the
one place that decision is made; callers ask it rather than comparing
against "ar" directly, so a third RTL language later needs one line
changed here instead of an audit of every call site.
"""
from __future__ import annotations

#: Every value `language` may take. Mirrors utils.prefs.LANGUAGES, which
#: is what stores it between launches — kept as two separate constants
#: (like theme.ThemeManager.MODES / prefs.THEME_MODES) rather than one
#: shared import, since frontend/ and utils/ do not otherwise cross-import
#: each other's small constant tables.
LANGUAGES = ("en", "ar")


def is_rtl(lang: str) -> bool:
    return lang == "ar"


#: {key: {"en": ..., "ar": ...}}. A value may carry `{placeholder}` tokens
#: for .format() at the call site — dates, counts and versions cannot be
#: baked in here.
STRINGS: dict[str, dict[str, str]] = {
    # -- sidebar -----------------------------------------------------
    "sidebar.search": {
        "en": "Search everything…",
        "ar": "ابحث في كل شيء…",
    },
    "sidebar.search_tooltip": {
        "en": "Search every app, tweak and tool  (Ctrl+K)",
        "ar": "ابحث في كل تطبيق وتعديل وأداة  (Ctrl+K)",
    },
    "sidebar.section": {
        "en": "MODULES",
        "ar": "الوحدات",
    },
    # Deliberately NO "sidebar.module.*" entries. Each nav button's label
    # is also that module's own page header (main.py:1046, category["title"]
    # sourced from menu_structure.py) and leads straight into a page whose
    # tagline, filter and every card are still English — translating only
    # the sidebar button would read as broken, not as a foundation. The
    # four module names travel together with the rest of their page's
    # content as one future unit (see ROADMAP.md), not split across passes.
    "sidebar.settings": {
        "en": "Settings",
        "ar": "الإعدادات",
    },

    # -- settings: page chrome ----------------------------------------
    "settings.title": {
        "en": "Settings",
        "ar": "الإعدادات",
    },
    "settings.tagline": {
        "en": "How Pulse looks, how this PC is protected, and how its "
              "setup travels to the next machine.",
        "ar": "كيف يبدو Pulse، وكيف يُحمى هذا الجهاز، وكيف ينتقل إعداده "
              "إلى الجهاز التالي.",
    },

    # -- settings: General ---------------------------------------------
    "settings.group.general": {
        "en": "General",
        "ar": "عام",
    },
    "settings.theme.dark": {
        "en": "Dark",
        "ar": "داكن",
    },
    "settings.theme.dark_hint": {
        "en": "Pulse's own dark palette, whatever Windows is set to.",
        "ar": "نسق Pulse الداكن الخاص به، بصرف النظر عن إعداد ويندوز.",
    },
    "settings.theme.light": {
        "en": "Light",
        "ar": "فاتح",
    },
    "settings.theme.light_hint": {
        "en": "Pulse's own light palette, whatever Windows is set to.",
        "ar": "نسق Pulse الفاتح الخاص به، بصرف النظر عن إعداد ويندوز.",
    },
    "settings.theme.system": {
        "en": "System",
        "ar": "النظام",
    },
    "settings.theme.system_hint": {
        "en": "Follow Windows' own light/dark setting, and change when "
              "it does.",
        "ar": "اتّبع إعداد ويندوز للوضع الفاتح أو الداكن، وغيّره عند "
              "تغييره.",
    },
    "settings.language": {
        "en": "Language",
        "ar": "اللغة",
    },
    "settings.language.en": {
        "en": "English",
        "ar": "English",
    },
    "settings.language.ar": {
        "en": "العربية",
        "ar": "العربية",
    },

    # -- settings: System Protection ------------------------------------
    "settings.group.protection": {
        "en": "System Protection",
        "ar": "حماية النظام",
    },
    "settings.restore.button": {
        "en": "Create Restore Point",
        "ar": "إنشاء نقطة استعادة",
    },
    "settings.restore.button_tooltip": {
        "en": "Takes a System Restore checkpoint now, so today's changes "
              "can be rolled back as a set.",
        "ar": "يأخذ نقطة استعادة للنظام الآن، حتى يمكن التراجع عن "
              "تغييرات اليوم دفعة واحدة.",
    },
    # SAID BEFORE THE CLICK, not after the failure — see SettingsView._
    # build_protection. Two fixed variants (admin / not admin), not
    # data-driven, so unlike the restore-point SUMMARY line below they
    # translate cleanly.
    "settings.restore.note_admin": {
        "en": "Pulse takes one automatically before the first system "
              "change of a session.",
        "ar": "يأخذ Pulse واحدة تلقائيًا قبل أول تغيير في النظام خلال "
              "الجلسة.",
    },
    "settings.restore.note_needs_admin": {
        "en": "Taking a checkpoint needs Administrator — Pulse will ask "
              "to relaunch when you click.",
        "ar": "أخذ نقطة استعادة يتطلب صلاحيات المسؤول — سيطلب منك Pulse "
              "إعادة التشغيل عند الضغط.",
    },
    # The restore-point SUMMARY line itself (newest checkpoint's date,
    # description and count) is data-driven — including a name Windows
    # itself assigned the checkpoint — and stays English in this pass;
    # see SettingsView._sync_restore_summary.

    # -- settings: Configuration Management ------------------------------
    "settings.group.configuration": {
        "en": "Configuration Management",
        "ar": "إدارة التكوين",
    },
    "settings.configuration.caption": {
        "en": "Write this PC's applied tweaks and catalogued apps to a "
              "profile, then apply it on another machine. A profile is "
              "an ordinary Pulse playbook, so it can only run operations "
              "this app already offers.",
        "ar": "اكتب تعديلات هذا الجهاز المطبَّقة وتطبيقاته المسجَّلة إلى "
              "ملف تعريف، ثم طبِّقه على جهاز آخر. ملف التعريف هو كتيّب "
              "تشغيل عادي في Pulse، فلا يمكنه تنفيذ سوى العمليات التي "
              "يوفّرها هذا التطبيق أصلًا.",
    },
    "settings.export.button": {
        "en": "Export Setup…",
        "ar": "تصدير الإعداد…",
    },
    "settings.export.button_tooltip": {
        "en": "Reads which catalogued apps are installed, then writes a "
              ".pulse.json profile.",
        "ar": "يقرأ التطبيقات المسجَّلة المثبَّتة، ثم يكتب ملف تعريف "
              ".pulse.json.",
    },
    "settings.import.button": {
        "en": "Import & Apply…",
        "ar": "استيراد وتطبيق…",
    },
    "settings.import.button_tooltip": {
        "en": "Runs a profile on this PC: applies its tweaks and installs "
              "its apps, one step at a time, starting with a restore "
              "point.",
        "ar": "يشغِّل ملف تعريف على هذا الجهاز: يطبِّق تعديلاته ويثبِّت "
              "تطبيقاته خطوة بخطوة، بدءًا بنقطة استعادة.",
    },

    # -- settings: Updates ------------------------------------------------
    "settings.group.updates": {
        "en": "Updates",
        "ar": "التحديثات",
    },
    "settings.updates.button": {
        "en": "Check for Updates",
        "ar": "التحقق من التحديثات",
    },
    "settings.updates.button_tooltip": {
        "en": "Checks GitHub for a newer Pulse release.",
        "ar": "يتحقق من GitHub بحثًا عن إصدار أحدث من Pulse.",
    },

    # -- footer chrome: the sidebar's one remaining control -----------
    # v16 ("ultra-clean footer") removed the theme toggle, the update
    # badge and the version/identity line from the sidebar footer
    # entirely — all three live exclusively in Settings now (theme in
    # General, updates in its own group; the version string is not
    # shown anywhere in chrome any more, only in Settings' tagline
    # context). The elevation-status indicator is the ONLY thing left
    # in the footer, so — unlike the deferred UPDATE_STATE_TEXTS
    # vocabulary (see widgets.py's own note on that one) — it earns a
    # translation now rather than staying a documented gap.
    "footer.elevation.engine_missing_name": {
        "en": "Engine missing",
        "ar": "المحرك غير موجود",
    },
    "footer.elevation.engine_missing_detail": {
        "en": "The PowerShell engine is missing — Pulse can report but "
              "cannot run operations.",
        "ar": "محرك PowerShell غير موجود — يمكن لـPulse الإبلاغ لكن لا "
              "يمكنه تنفيذ العمليات.",
    },
    "footer.elevation.admin_name": {
        "en": "Running as Administrator",
        "ar": "يعمل بصلاحيات المسؤول",
    },
    "footer.elevation.admin_detail": {
        "en": "Running as Administrator — every operation is available.",
        "ar": "يعمل بصلاحيات المسؤول — كل العمليات متاحة.",
    },
    "footer.elevation.not_admin_name": {
        "en": "Not elevated — relaunch as Administrator",
        "ar": "غير مرتفع الصلاحيات — أعد التشغيل كمسؤول",
    },
    "footer.elevation.not_admin_detail": {
        "en": "Not elevated. Some system-level operations need "
              "Administrator rights — click to relaunch (a UAC prompt "
              "will appear).",
        "ar": "غير مرتفع الصلاحيات. بعض عمليات مستوى النظام تحتاج "
              "صلاحيات المسؤول — انقر لإعادة التشغيل (ستظهر نافذة "
              "UAC).",
    },

    # -- shared confirm-dialog chrome -------------------------------------
    # item['title'] / item['desc'] (the operation-specific text) stay
    # English, like the rest of menu_structure.py's catalog — only the
    # dialog's OWN fixed chrome translates.
    "dialog.cancel": {
        "en": "Cancel",
        "ar": "إلغاء",
    },
    "dialog.proceed": {
        "en": "Proceed",
        "ar": "متابعة",
    },
    "dialog.danger_warning": {
        "en": "⚠️  This action changes your system and may be hard to undo.",
        "ar": "⚠️  هذا الإجراء يغيّر نظامك وقد يصعب التراجع عنه.",
    },
}


def tr(key: str, lang: str) -> str:
    """Look up `key` in `STRINGS` for `lang`, falling back to English and
    then to the key itself — the same "degrade, never crash" contract
    theme.glyph() already holds the app to."""
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key
