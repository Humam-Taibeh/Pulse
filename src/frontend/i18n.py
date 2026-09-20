"""
src/frontend/i18n.py

DISPLAY LANGUAGE (v10.15, extended v16, extended v16.1) — a manual
English/Arabic choice, not "follow Windows".

WHAT THIS COVERS. v10.15 shipped the foundation and the surfaces a user
reaches before choosing what to do: the sidebar rail, the Settings page
itself (where the language picker lives), the footer's tooltips, and the
confirm-dialog chrome every destructive action shares. v16 extends it to
the dashboard, every module's own page chrome, card status badges/meta
pills, and — via the separate, much larger frontend.i18n_catalog module
— every task-card's title and description across the full catalog and
the sidebar's four module labels, which is what closes v10.15's own
"translating only the button would read as broken" gap. v16 also closes
the two data-driven strings the user named explicitly as still-visible
English: every card's relative-timestamp caption ("3d ago · ~2m" — see
widgets.format_relative_age/format_duration/format_history_caption) and
the restore-point summary sentence in Settings (see
SettingsView._sync_restore_summary) — in both cases the SENTENCE
translates while values Pulse did not author (a checkpoint's own
Windows-assigned description) do not. v16.1 closes the three dialogs
named explicitly as a "noticeable disconnect": Update Center, Bloatware
Purge and Startup Manager now translate in full — every static chrome
string plus two backend-authored data tables that are Pulse's own copy
(BloatRow's Note field and StartupRow's Reason field, both routed
through i18n_catalog exactly like SOFTWARE_CATALOG's "why" field). A key
with no entry in STRINGS degrades to the key itself — visible-but-safe,
matching theme.glyph()'s "a missing table entry degrades, never
crashes" posture — rather than raising, so a half-translated surface
never becomes a broken one.

WHAT STILL STAYS ENGLISH, on purpose (see ROADMAP.md for the tracked
follow-up): the live PowerShell console log (including any TaskResult
message reported at runtime — a toggle's own success/failure line, a
scan's caveat, its Trigger value), playbooks, the Health Report, the
Restore Point Browser, the Office setup wizard, and
ToolInstallWizardDialog's own per-app install-option picker.
SettingsView's own UPDATE_STATE_TEXTS vocabulary (IDLE/CHECKING/UP TO
DATE/UPDATE READY) stays deferred too — see widgets.py's own note on it.
StatusRail's elevation text is NOT on this list — see the "footer
chrome" section below, where it earns a translation rather than staying
a gap, now that it is the only control still living in the footer.

NOT "FOLLOW WINDOWS". Unlike theme.py's system-sync mode, this reads no
OS locale API at all: a user picks English or Arabic, and that choice is
what set_language persists. There is nothing here for
tests/test_system_theme_events.py's exclusive-OS-read guard to cover,
because there is no OS read to guard.

RTL IS A LAYOUT DIRECTION, NOT A TRANSLATION DETAIL. is_rtl(lang) is the
one place that decision is made; callers ask it rather than comparing
against "ar" directly, so a third RTL language later needs one line
changed here instead of an audit of every call site.

LIVE PAGES NEED TELLING, NOT JUST BUILDING RIGHT. WelcomePage and every
CategoryPage are constructed once and kept alive for the app's lifetime
(PulseApp._build_ui), so passing `lang` at construction only covers a
fresh launch — a language switch mid-session needs every already-built
widget walked explicitly. See GlassCard.retranslate, WelcomePage.
retranslate and CategoryPage.retranslate in main.py/widgets.py, which
exist entirely for this.
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
    # "sidebar.module.*" now exists (v16) — see the dedicated section
    # further down, added together with the destination pages that used
    # to be the reason these stayed English (v10.15's own note on that
    # boundary, now closed).
    "sidebar.settings": {
        "en": "Settings",
        "ar": "الإعدادات",
    },
    "sidebar.collapse_tooltip": {
        "en": "Collapse sidebar",
        "ar": "طي الشريط الجانبي",
    },
    "sidebar.expand_tooltip": {
        "en": "Expand sidebar",
        "ar": "توسيع الشريط الجانبي",
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
    # The restore-point SUMMARY line itself is data-driven (Windows' own
    # checkpoint date and description are never translated — they are a
    # name Windows assigned, not app copy) but its surrounding sentence
    # and the four state messages below are — see
    # SettingsView._sync_restore_summary.
    "settings.restore.summary.checking": {
        "en": "Checking this PC's restore points…",
        "ar": "جارٍ التحقق من نقاط استعادة هذا الجهاز…",
    },
    "settings.restore.summary.unavailable": {
        "en": "System Restore appears to be turned off for this PC, so no "
              "checkpoints can be taken. Turn on protection for the "
              "system drive in Windows to enable it.",
        "ar": "يبدو أن استعادة النظام معطَّلة على هذا الجهاز، لذا لا يمكن "
              "أخذ أي نقطة استعادة. فعِّل الحماية لقرص النظام من إعدادات "
              "ويندوز لتمكينها.",
    },
    "settings.restore.summary.empty": {
        "en": "No restore points on this PC yet. Pulse takes one before "
              "the first system change of a session.",
        "ar": "لا توجد نقاط استعادة على هذا الجهاز بعد. يأخذ Pulse نقطة "
              "استعادة قبل أول تغيير في النظام خلال الجلسة.",
    },
    # {created}/{description} are Windows' own values, untranslated by
    # design (see the comment above); {age} is "" or the rendered
    # age_suffix key below; {count} is the rendered count_singular/plural
    # key below.
    "settings.restore.summary.newest": {
        "en": "Newest checkpoint: {created} — “{description}”"
              "{age}. {count}",
        "ar": "أحدث نقطة استعادة: {created} — «{description}»"
              "{age}. {count}",
    },
    "settings.restore.summary.age_suffix": {
        "en": ", {days:.1f} day(s) ago",
        "ar": "، قبل {days:.1f} يوم",
    },
    "settings.restore.summary.count_singular": {
        "en": "1 checkpoint on this PC.",
        "ar": "نقطة استعادة واحدة على هذا الجهاز.",
    },
    "settings.restore.summary.count_plural": {
        "en": "{n} checkpoints on this PC.",
        "ar": "{n} نقاط استعادة على هذا الجهاز.",
    },

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
    # item['title'] / item['desc'] now route through i18n_catalog's own
    # lookup-by-English-text (v16 extends translation to the catalog) —
    # this table only ever held the dialog's OWN fixed chrome.
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
    # Shared across UpdateCenterDialog/BloatwarePurgeDialog/
    # StartupManagerDialog's own loading/error/results pages (v16.1).
    "dialog.close": {
        "en": "Close",
        "ar": "إغلاق",
    },
    "dialog.retry": {
        "en": "Retry",
        "ar": "إعادة المحاولة",
    },
    "dialog.rescan": {
        "en": "Rescan",
        "ar": "إعادة الفحص",
    },

    # -- sidebar module labels (v16) --------------------------------------
    # Reintroduced: v10.15 deliberately left these English because their
    # destination pages (CategoryPage's header/tagline/filter/cards) were
    # still all-English, and translating only the button would have read
    # as broken. v16 translates the destination too, so the boundary that
    # justified the gap no longer applies.
    "sidebar.module.software": {
        "en": "Software Management",
        "ar": "إدارة البرامج",
    },
    "sidebar.module.system": {
        "en": "System & Tweaks",
        "ar": "النظام والتعديلات",
    },
    "sidebar.module.maintenance": {
        "en": "Maintenance & Security",
        "ar": "الصيانة والأمان",
    },
    "sidebar.module.utilities": {
        "en": "Utilities & Tools",
        "ar": "الأدوات والمرافق",
    },

    # -- dashboard (WelcomePage) -------------------------------------------
    "dashboard.tagline": {
        "en": "Windows Orchestration Toolkit",
        "ar": "أداة تنسيق ويندوز",
    },
    "dashboard.system_health": {
        "en": "SYSTEM HEALTH",
        "ar": "حالة النظام",
    },
    "dashboard.quick_actions": {
        "en": "QUICK ACTIONS",
        "ar": "إجراءات سريعة",
    },
    "dashboard.tile.cpu": {
        "en": "CPU load",
        "ar": "حمل المعالج",
    },
    "dashboard.tile.memory": {
        "en": "Memory",
        "ar": "الذاكرة",
    },
    "dashboard.tile.storage": {
        "en": "System drive",
        "ar": "قرص النظام",
    },
    "dashboard.tile.due": {
        "en": "Actions due",
        "ar": "إجراءات مستحقة",
    },
    "dashboard.tile.memory_tooltip": {
        "en": "{mem_text} in use",
        "ar": "{mem_text} قيد الاستخدام",
    },
    # The tile's headline VALUE (main.py's WelcomePage._tick_pulse) and
    # its tooltip both format the same raw disk_free_gb float — kept as
    # two separate keys rather than composing one into the other, which
    # is what produced a real "394 GB free free on the system drive"
    # bug (English "free" baked into the value, then the tooltip
    # template appended its own "free" after it) caught in the v16
    # Arabic smoke test.
    "dashboard.tile.storage_value": {
        "en": "{gb:.0f} GB free",
        "ar": "{gb:.0f} GB خالية",
    },
    "dashboard.tile.storage_tooltip": {
        "en": "{gb:.0f} GB free on the system drive",
        "ar": "{gb:.0f} GB خالية على قرص النظام",
    },
    "dashboard.tile.due_none": {
        "en": "Nothing is overdue.",
        "ar": "لا شيء متأخر.",
    },
    "dashboard.tile.due_some": {
        "en": "{due} of {total} operations are due to be run again.",
        "ar": "{due} من أصل {total} عملية مستحقة التشغيل مجددًا.",
    },
    "dashboard.session.admin": {
        "en": "Administrator",
        "ar": "مسؤول",
    },
    "dashboard.session.not_admin": {
        "en": "Not elevated",
        "ar": "غير مرتفع الصلاحيات",
    },
    "dashboard.session.engine_ok": {
        "en": "Engine ready",
        "ar": "المحرك جاهز",
    },
    "dashboard.session.engine_missing": {
        "en": "Engine missing",
        "ar": "المحرك غير موجود",
    },
    # ACTION_BLURBS — the six dashboard-only quick-action descriptions
    # (a terser stand-in for the category page's own, longer desc for
    # the same task) — go through i18n_catalog's DESCRIPTIONS instead of
    # here: they are catalog-shaped content (looked up by English text,
    # sourced from main.WelcomePage.ACTION_BLURBS), not UI chrome.

    # -- category page chrome ----------------------------------------------
    "category.home": {
        "en": "Home",
        "ar": "الرئيسية",
    },
    "category.home_tooltip": {
        "en": "Back to the welcome screen",
        "ar": "العودة إلى شاشة الترحيب",
    },
    "category.filter.all": {
        "en": "All operations",
        "ar": "كل العمليات",
    },
    "category.filter.applied": {
        "en": "Applied",
        "ar": "مُطبَّق",
    },
    "category.filter.not_applied": {
        "en": "Not applied",
        "ar": "غير مُطبَّق",
    },
    "category.filter.modified": {
        "en": "Modified",
        "ar": "مُعدَّل",
    },
    "category.filter.action_due": {
        "en": "Action due",
        "ar": "إجراء مستحق",
    },
    "category.count.plural": {
        "en": "{total} OPERATIONS",
        "ar": "{total} عملية",
    },
    "category.count.singular": {
        "en": "{total} OPERATION",
        "ar": "عملية واحدة",
    },
    "category.count.filtered": {
        "en": "{visible} OF {total}",
        "ar": "{visible} من {total}",
    },
    "category.applied_ratio": {
        "en": "{applied} OF {probed} APPLIED",
        "ar": "{applied} من {probed} مُطبَّق",
    },
    "category.applied_ratio_tooltip": {
        "en": "{probed} operation(s) in this module report a readable "
              "setting; {applied} are currently applied. Routines and "
              "reports have no such state and are not counted.",
        "ar": "{probed} عملية في هذه الوحدة تُبلغ عن حالة قابلة للقراءة؛ "
              "{applied} منها مُطبَّقة حاليًا. الروتينات والتقارير لا "
              "تملك مثل هذه الحالة ولا تُحتسب.",
    },
    "category.empty_unfiltered": {
        "en": "No operations match that filter.",
        "ar": "لا توجد عمليات تطابق هذا الفلتر.",
    },
    "category.empty_filtered": {
        "en": "No operations in this module are {filter}.",
        "ar": "لا توجد عمليات في هذه الوحدة {filter}.",
    },

    # -- card status badges (GlassCard._STATE_BADGES) ----------------------
    "badge.applied": {
        "en": "APPLIED",
        "ar": "مُطبَّق",
    },
    "badge.applied_tooltip": {
        "en": "This setting is currently active on your system.",
        "ar": "هذا الإعداد مُفعَّل حاليًا على نظامك.",
    },
    "badge.mixed": {
        "en": "MODIFIED",
        "ar": "مُعدَّل",
    },
    "badge.mixed_tooltip": {
        "en": "This setting is partially applied — some of its values "
              "match, some don't. It may have been changed outside Pulse. "
              "Click the card to re-apply or revert it.",
        "ar": "هذا الإعداد مُطبَّق جزئيًا — بعض قيمه مطابقة وبعضها لا. قد "
              "يكون تغيّر خارج Pulse. انقر البطاقة لإعادة التطبيق أو "
              "التراجع.",
    },
    "badge.default": {
        "en": "DEFAULT",
        "ar": "افتراضي",
    },
    "badge.default_tooltip": {
        "en": "This setting is at its Windows default. Click the card to "
              "apply the tweak.",
        "ar": "هذا الإعداد على وضعه الافتراضي في ويندوز. انقر البطاقة "
              "لتطبيق التعديل.",
    },
    "badge.due": {
        "en": "ACTION DUE",
        "ar": "إجراء مستحق",
    },
    "badge.due_tooltip": {
        "en": "This routine hasn't been run recently. Running it "
              "periodically keeps the system healthy.",
        "ar": "لم يتم تشغيل هذا الروتين مؤخرًا. تشغيله دوريًا يحافظ على "
              "سلامة النظام.",
    },

    # -- card meta-footer pills (widgets._derive_card_meta) -----------------
    # Only the four LIVE branches (the "apps"/"devhub" cases have no
    # caller left in menu_structure.py — see widgets._derive_card_meta's
    # own note) — not translated for the same reason dead code isn't
    # exercised by anything else either.
    "meta.options_plural": {
        "en": "{n} options",
        "ar": "{n} خيارات",
    },
    "meta.options_singular": {
        "en": "1 option",
        "ar": "خيار واحد",
    },
    "meta.live_scan": {
        "en": "Live scan",
        "ar": "فحص مباشر",
    },
    "meta.audit_toggle": {
        "en": "Audit & toggle",
        "ar": "تدقيق وتبديل",
    },
    "meta.guided_setup": {
        "en": "Guided setup",
        "ar": "إعداد موجّه",
    },
    "card.lock_tooltip": {
        "en": "Needs Administrator — clicking will offer to relaunch "
              "Pulse elevated.",
        "ar": "يحتاج صلاحيات المسؤول — النقر سيعرض إعادة تشغيل Pulse "
              "بصلاحيات مرتفعة.",
    },

    # -- relative timestamps (widgets.format_relative_age) ------------------
    # English stays letter-terse (m/h/d/w/mo/y ago) because that width was
    # measured against the card grid — see format_relative_age's own
    # docstring. Arabic has no equivalent one-letter convention, so these
    # read as short words instead; the count is still coarse/rounded-down,
    # matching the English behaviour exactly, only the phrasing is native.
    "time.just_now": {
        "en": "just now",
        "ar": "الآن",
    },
    "time.minutes_ago": {
        "en": "{n}m ago",
        "ar": "قبل {n} د",
    },
    "time.hours_ago": {
        "en": "{n}h ago",
        "ar": "قبل {n} س",
    },
    "time.days_ago": {
        "en": "{n}d ago",
        "ar": "قبل {n} يوم",
    },
    "time.weeks_ago": {
        "en": "{n}w ago",
        "ar": "قبل {n} أ",
    },
    "time.months_ago": {
        "en": "{n}mo ago",
        "ar": "قبل {n} ش",
    },
    "time.years_ago": {
        "en": "{n}y ago",
        "ar": "قبل {n} سنة",
    },

    # -- durations (widgets.format_duration) ---------------------------------
    "time.duration.seconds": {
        "en": "{n}s",
        "ar": "{n} ث",
    },
    "time.duration.minutes": {
        "en": "{n}m",
        "ar": "{n} د",
    },
    "time.duration.hours": {
        "en": "{n}h",
        "ar": "{n} س",
    },

    # -- run-history tooltip sentence (widgets.format_history_caption) ------
    "time.detail.last_run": {
        "en": "Last run {age}",
        "ar": "آخر تشغيل {age}",
    },
    "time.detail.took": {
        "en": "took {duration}",
        "ar": "استغرق {duration}",
    },
    "time.detail.runs_recorded": {
        "en": "{runs} runs recorded, averaging {duration}",
        "ar": "سُجِّلت {runs} عملية تشغيل، بمتوسط {duration}",
    },
    "time.detail.error": {
        "en": "the last run reported an error",
        "ar": "أبلغ آخر تشغيل عن خطأ",
    },

    # -- command palette (Ctrl+K) ---------------------------------------
    # Built fresh on each open, like ConfirmDialog/SoftwareCatalogDialog —
    # `lang` is read once at construction, no retranslate() needed. Result
    # ROW text (item titles, hub names) routes through i18n_catalog, not
    # here; these are only the palette's own chrome.
    "palette.placeholder": {
        "en": "Search apps, tweaks and tools…",
        "ar": "ابحث في التطبيقات والتعديلات والأدوات…",
    },
    "palette.empty": {
        "en": "No apps, tweaks or tools match that search.",
        "ar": "لا توجد تطبيقات أو تعديلات أو أدوات مطابقة لهذا البحث.",
    },
    "palette.hint.navigate": {
        "en": "navigate",
        "ar": "تنقّل",
    },
    "palette.hint.run": {
        "en": "run",
        "ar": "تشغيل",
    },
    "palette.hint.close": {
        "en": "close",
        "ar": "إغلاق",
    },
    # {matched} names a caught app/tool name (search_contents) and is
    # never translated — see _add_result's own note.
    "palette.hint.installs": {
        "en": "installs {matched}",
        "ar": "يثبِّت {matched}",
    },
    "palette.result_singular": {
        "en": "1 result",
        "ar": "نتيجة واحدة",
    },
    "palette.result_plural": {
        "en": "{n} results",
        "ar": "{n} نتائج",
    },

    # -- SoftwareCatalogDialog chrome (v16) ------------------------------
    # Built fresh on each open, like CommandPalette — `lang` is read once
    # at construction. Pillar/group/tool CONTENT routes through
    # i18n_catalog, not here; these are only the dialog's own controls.
    "catalog.blurb.scoped": {
        "en": "{blurb} Nothing is pre-selected — tick what you want, "
              "then deploy all {total} in one pass.",
        "ar": "{blurb} لا شيء محدَّد مسبقًا — اختر ما تريده، ثم انشر "
              "الكل ({total}) دفعة واحدة.",
    },
    "catalog.blurb.combined": {
        "en": "All {total} apps in one place. Nothing is pre-selected — "
              "tick what you want, filter by sub-category, then deploy "
              "in one pass.",
        "ar": "كل التطبيقات ({total}) في مكان واحد. لا شيء محدَّد "
              "مسبقًا — اختر ما تريده، صفِّ حسب الفئة الفرعية، ثم انشر "
              "دفعة واحدة.",
    },
    "catalog.tab.all": {
        "en": "All",
        "ar": "الكل",
    },
    "catalog.select_all": {
        "en": "Select All",
        "ar": "تحديد الكل",
    },
    "catalog.deselect_all": {
        "en": "Deselect All",
        "ar": "إلغاء تحديد الكل",
    },
    "catalog.count.selected": {
        "en": "{count} selected",
        "ar": "{count} محدَّد",
    },
    "catalog.count.selected_narrowed": {
        "en": "{count} selected across all categories",
        "ar": "{count} محدَّد عبر كل الفئات",
    },
    "catalog.deploy": {
        "en": "Deploy Selected",
        "ar": "نشر المحدَّد",
    },
    "catalog.deploy_count": {
        "en": "Deploy Selected ({count})",
        "ar": "نشر المحدَّد ({count})",
    },
    "catalog.empty": {
        "en": "No apps in this category.",
        "ar": "لا توجد تطبيقات في هذه الفئة.",
    },
    # {name} is the tool's own DisplayName, never translated — see
    # i18n_catalog's module docstring.
    "catalog.row.website_tooltip": {
        "en": "Open {name}'s official download page in your browser",
        "ar": "فتح صفحة تنزيل {name} الرسمية في متصفحك",
    },
    "catalog.row.website_accessible": {
        "en": "Open the official {name} download page",
        "ar": "فتح صفحة تنزيل {name} الرسمية",
    },
    "catalog.row.requires": {
        "en": "↳ needs {name}",
        "ar": "↳ يحتاج {name}",
    },

    # ============================================================
    #  UPDATE CENTER (v16.1)
    # ============================================================
    "update_center.row.running_badge": {
        "en": "RUNNING",
        "ar": "قيد التشغيل",
    },
    "update_center.row.running_tooltip": {
        "en": "This app is running and will be closed before it is "
              "updated.\nProcesses: {processes}",
        "ar": "هذا التطبيق قيد التشغيل وسيُغلق قبل تحديثه.\n"
              "العمليات: {processes}",
    },
    "update_center.title": {
        "en": "🔄  Update Center",
        "ar": "🔄  مركز التحديثات",
    },
    "update_center.subtitle.scanning": {
        "en": "Scanning installed apps against winget…",
        "ar": "جارٍ فحص التطبيقات المثبَّتة عبر winget…",
    },
    "update_center.loading": {
        "en": "Reading your installed programs…",
        "ar": "جارٍ قراءة برامجك المثبَّتة…",
    },
    "update_center.empty.message": {
        "en": "You're all caught up — every installed app is at its "
              "latest version.",
        "ar": "كل شيء محدَّث — كل التطبيقات المثبَّتة عند أحدث إصدار لها.",
    },
    "update_center.error.scan_failed_to_run": {
        "en": "The update scan failed to run.",
        "ar": "تعذّر تشغيل فحص التحديثات.",
    },
    "update_center.error.scan_failed": {
        "en": "The update scan failed.",
        "ar": "فشل فحص التحديثات.",
    },
    "update_center.error.scan_failed_short": {
        "en": "Scan failed.",
        "ar": "فشل الفحص.",
    },
    "update_center.empty_after_scan": {
        "en": "Every installed app is up to date.",
        "ar": "كل التطبيقات المثبَّتة محدَّثة.",
    },
    "update_center.reconcile_subtitle": {
        "en": "All {total} updates are pre-selected — untick anything "
              "you don't want, or open a row's link to fetch it from "
              "the vendor yourself.",
        "ar": "كل التحديثات ({total}) محدَّدة مسبقًا — ألغِ تحديد ما لا "
              "تريده، أو افتح رابط أي صف لجلبه من الشركة المصنِّعة بنفسك.",
    },
    "update_center.count_selected": {
        "en": "{count} selected",
        "ar": "{count} محدَّد",
    },
    "update_center.update_selected": {
        "en": "Update Selected",
        "ar": "تحديث المحدَّد",
    },
    "update_center.update_selected_count": {
        "en": "Update Selected ({count})",
        "ar": "تحديث المحدَّد ({count})",
    },
    "update_center.update_all_count": {
        "en": "Update All ({count})",
        "ar": "تحديث الكل ({count})",
    },
    "update_center.confirm_running.title": {
        "en": "Some of these apps are running",
        "ar": "بعض هذه التطبيقات قيد التشغيل",
    },
    # Two full sentences rather than one gendered/pluralised template —
    # the English original branches on count via inline conditionals
    # ("is"/"are", "this app"/"these apps", "it"/"them"); Arabic grammar
    # does not map onto the same branch points, so each count gets its
    # own natural, complete sentence instead of a parametrised patchwork.
    "update_center.confirm_running.desc_singular": {
        "en": "{names} is open right now. Windows cannot replace files "
              "that are in use, so this app will be closed before the "
              "update is applied — you will be asked to save any "
              "unsaved work first.\n\nCancel if you would rather "
              "untick it and update the rest.",
        "ar": "{names} مفتوح الآن. لا يستطيع ويندوز استبدال الملفات "
              "قيد الاستخدام، لذا سيُغلق هذا التطبيق قبل تطبيق "
              "التحديث — سيُطلب منك حفظ أي عمل غير محفوظ أولًا.\n\n"
              "ألغِ الأمر إن كنت تفضّل إلغاء تحديده وتحديث البقية.",
    },
    "update_center.confirm_running.desc_plural": {
        "en": "{names} are open right now. Windows cannot replace "
              "files that are in use, so these apps will be closed "
              "before the update is applied — you will be asked to "
              "save any unsaved work first.\n\nCancel if you would "
              "rather untick them and update the rest.",
        "ar": "{names} مفتوحة الآن. لا يستطيع ويندوز استبدال الملفات "
              "قيد الاستخدام، لذا ستُغلق هذه التطبيقات قبل تطبيق "
              "التحديث — سيُطلب منك حفظ أي عمل غير محفوظ أولًا.\n\n"
              "ألغِ الأمر إن كنت تفضّل إلغاء تحديدها وتحديث البقية.",
    },

    # ============================================================
    #  BLOATWARE PURGE (v16.1)
    # ============================================================
    "bloatware.title": {
        "en": "🧹  Bloatware Purge",
        "ar": "🧹  إزالة البرامج غير المرغوبة",
    },
    "bloatware.subtitle.scanning": {
        "en": "Scanning installed and staged packages…",
        "ar": "جارٍ فحص الحزم المثبَّتة والمهيَّأة…",
    },
    "bloatware.loading": {
        "en": "Reading installed packages, staged provisioning "
              "templates and the uninstall registry…",
        "ar": "جارٍ قراءة الحزم المثبَّتة وقوالب التهيئة المرحلية "
              "وسجل إلغاء التثبيت…",
    },
    "bloatware.error.scan_returned_nothing": {
        "en": "The package scan returned nothing.",
        "ar": "لم يعد فحص الحزم بأي نتيجة.",
    },
    "bloatware.error.suffix": {
        "en": "\n\nNothing was changed. Close this and try again, or "
              "run the purge without a selection to remove the "
              "recommended set.",
        "ar": "\n\nلم يتغيّر شيء. أغلق هذا وحاول مجددًا، أو شغّل "
              "الإزالة دون تحديد لإزالة المجموعة الموصى بها.",
    },
    "bloatware.clean.headline": {
        "en": "Your system is clean",
        "ar": "نظامك نظيف",
    },
    "bloatware.clean.note": {
        "en": "None of the {catalogued} packages Pulse checks for is "
              "installed, staged for future profiles, or pinned to "
              "your Start menu.",
        "ar": "لا شيء من الحزم الـ{catalogued} التي يتحقق منها Pulse "
              "مثبَّت، أو مهيَّأ لملفات تعريف مستقبلية، أو مثبَّت على "
              "قائمة ابدأ.",
    },
    "bloatware.clean.inspect_btn": {
        "en": "Show all {catalogued} packages Pulse checks for",
        "ar": "عرض كل الحزم الـ{catalogued} التي يتحقق منها Pulse",
    },
    "bloatware.clean.inspect_tooltip": {
        "en": "Show every package Pulse checks for, including the "
              "ones that are not on this machine.",
        "ar": "عرض كل حزمة يتحقق منها Pulse، بما فيها غير الموجودة "
              "على هذا الجهاز.",
    },
    "bloatware.select_all_installed": {
        "en": "Select All Installed",
        "ar": "تحديد كل المثبَّت",
    },
    "bloatware.select_all_installed_tooltip": {
        "en": "Ticks every package REGISTERED on this PC that is "
              "currently shown, outside the optional Xbox section.",
        "ar": "يحدِّد كل حزمة مسجَّلة على هذا الجهاز ومعروضة حاليًا، "
              "باستثناء قسم Xbox الاختياري.",
    },
    "bloatware.select_all_stubs": {
        "en": "Select All Stubs",
        "ar": "تحديد كل الامتدادات",
    },
    "bloatware.select_all_stubs_tooltip": {
        "en": "Ticks the Start-menu tiles and staged packages "
              "currently shown — the ones that come back after a "
              "Windows feature update.",
        "ar": "يحدِّد لبنات قائمة ابدأ والحزم المهيَّأة المعروضة "
              "حاليًا — تلك التي تعود بعد تحديث ميزات ويندوز.",
    },
    "bloatware.show_absent": {
        "en": "Show packages that aren't installed",
        "ar": "عرض الحزم غير المثبَّتة",
    },
    "bloatware.filter_placeholder": {
        "en": "Filter by name or package ID…",
        "ar": "تصفية بالاسم أو معرّف الحزمة…",
    },
    "bloatware.no_match": {
        "en": "Nothing installed matches “{query}”.",
        "ar": "لا يوجد مثبَّت يطابق “{query}”.",
    },
    "bloatware.no_match.hidden_suffix": {
        "en": "  {hidden} catalogued package(s) match but are not on "
              "this PC — tick “Show packages that aren't "
              "installed” to see them.",
        "ar": "  هناك {hidden} حزمة مطابقة في الفهرس لكنها غير "
              "موجودة على هذا الجهاز — فعِّل “عرض الحزم غير "
              "المثبَّتة” لرؤيتها.",
    },
    "bloatware.purge_btn": {
        "en": "Safe Purge",
        "ar": "إزالة آمنة",
    },
    "bloatware.purge_btn_count": {
        "en": "Safe Purge ({count})",
        "ar": "إزالة آمنة ({count})",
    },
    "bloatware.count.selected": {
        "en": "{count} selected",
        "ar": "{count} محدَّد",
    },
    "bloatware.count.selected_shown": {
        "en": "{count} selected  ·  {shown} of {eligible} shown",
        "ar": "{count} محدَّد  ·  {shown} من {eligible} معروض",
    },
    "bloatware.summary.clean_scan": {
        "en": "Checked every installed, staged and Start-menu "
              "package against the Pulse catalog.",
        "ar": "تحقق Pulse من كل حزمة مثبَّتة أو مهيَّأة أو على قائمة "
              "ابدأ مقابل فهرسه.",
    },
    "bloatware.summary.detected": {
        "en": "{detected} catalogued package(s) found. Ticked "
              "packages are removed for every profile, deprovisioned "
              "so they cannot return after a Windows update, and "
              "their Start menu promotions disabled.",
        "ar": "عُثر على {detected} حزمة من الفهرس. الحزم المحدَّدة "
              "تُزال لكل الملفات الشخصية، وتُلغى تهيئتها فلا تعود بعد "
              "تحديث ويندوز، وتُعطَّل ترويجاتها في قائمة ابدأ.",
    },
    # -- BloatwarePurgeDialog.SECTIONS' own titles -----------------------
    "bloatware.section.promo": {
        "en": "Pre-installed stubs and promotions",
        "ar": "امتدادات وترويجات مثبَّتة مسبقًا",
    },
    "bloatware.section.core": {
        "en": "Redundant Windows apps",
        "ar": "تطبيقات ويندوز الزائدة",
    },
    "bloatware.section.codec": {
        "en": "Third-party leftovers",
        "ar": "مخلّفات برامج خارجية",
    },
    "bloatware.section.gaming": {
        "en": "Xbox and gaming (optional)",
        "ar": "Xbox والألعاب (اختياري)",
    },
    "bloatware.section_header": {
        "en": "{title}  ·  {present} of {total} present",
        "ar": "{title}  ·  {present} من {total} موجود",
    },
    # -- BloatRow's own badges -------------------------------------------
    "bloatware.presence.installed": {
        "en": "INSTALLED",
        "ar": "مثبَّت",
    },
    "bloatware.presence.installed_hint": {
        "en": "Registered on this machine and running when opened.",
        "ar": "مسجَّل على هذا الجهاز ويعمل عند فتحه.",
    },
    "bloatware.presence.staged": {
        "en": "STAGED",
        "ar": "مهيَّأ",
    },
    "bloatware.presence.staged_hint": {
        "en": "Not installed for you, but staged for new profiles — "
              "this is the copy that returns after a Windows update.",
        "ar": "غير مثبَّت لك، لكنه مهيَّأ لملفات تعريف جديدة — هذه هي "
              "النسخة التي تعود بعد تحديث ويندوز.",
    },
    "bloatware.presence.pinned": {
        "en": "PINNED",
        "ar": "مثبَّت على القائمة",
    },
    "bloatware.presence.pinned_hint": {
        "en": "Offered on the Start menu without being installed yet. "
              "Windows downloads it the first time anyone opens the "
              "tile; removing it takes the tile away too.",
        "ar": "معروض على قائمة ابدأ دون أن يُثبَّت بعد. يحمّله ويندوز "
              "أول مرة يفتح فيها أحد اللبنة؛ إزالته تزيل اللبنة أيضًا.",
    },
    "bloatware.presence.absent": {
        "en": "NOT PRESENT",
        "ar": "غير موجود",
    },
    "bloatware.presence.absent_hint": {
        "en": "Pulse checks for this one and did not find it here.",
        "ar": "يتحقق Pulse من وجوده ولم يجده هنا.",
    },
    "bloatware.optional_badge": {
        "en": "OPTIONAL",
        "ar": "اختياري",
    },
    "bloatware.optional_badge_hint": {
        "en": "Left unticked by a Select All. Removing the Xbox stack "
              "can break Game Bar's screen capture and Store game "
              "sign-in.",
        "ar": "يبقى غير محدَّد عند تحديد الكل. إزالة حزمة Xbox قد "
              "تعطّل تسجيل شاشة Game Bar وتسجيل الدخول لألعاب المتجر.",
    },

    # ============================================================
    #  STARTUP MANAGER (v16.1)
    # ============================================================
    "startup.title": {
        "en": "🚀  Startup Manager",
        "ar": "🚀  مدير بدء التشغيل",
    },
    "startup.subtitle.scanning": {
        "en": "Auditing Run keys, Startup folders and sign-in tasks…",
        "ar": "جارٍ تدقيق مفاتيح Run ومجلدات بدء التشغيل ومهام تسجيل "
              "الدخول…",
    },
    "startup.loading": {
        "en": "Reading Run keys, Startup folders and sign-in tasks, "
              "and what Windows measured about recent boots…",
        "ar": "جارٍ قراءة مفاتيح Run ومجلدات بدء التشغيل ومهام تسجيل "
              "الدخول، وما قاسه ويندوز عن الإقلاعات الأخيرة…",
    },
    "startup.error.audit_failed_to_run": {
        "en": "The startup audit failed to run.",
        "ar": "تعذّر تشغيل تدقيق بدء التشغيل.",
    },
    "startup.error.audit_failed": {
        "en": "The startup audit failed.",
        "ar": "فشل تدقيق بدء التشغيل.",
    },
    "startup.error.audit_failed_short": {
        "en": "Audit failed.",
        "ar": "فشل التدقيق.",
    },
    "startup.error.no_items": {
        "en": "No startup items were found to audit.",
        "ar": "لم توجد عناصر بدء تشغيل لتدقيقها.",
    },
    "startup.filter.all": {
        "en": "All {count}",
        "ar": "الكل {count}",
    },
    "startup.filter.enabled": {
        "en": "{count} enabled",
        "ar": "{count} مفعَّل",
    },
    "startup.filter.disabled": {
        "en": "{count} disabled",
        "ar": "{count} معطَّل",
    },
    "startup.filter.recommended": {
        "en": "{count} recommended to disable",
        "ar": "{count} يُنصح بتعطيله",
    },
    "startup.filter.all_tooltip": {
        "en": "Show every startup item",
        "ar": "عرض كل عناصر بدء التشغيل",
    },
    "startup.filter.enabled_tooltip": {
        "en": "Show only the items that launch at sign-in",
        "ar": "عرض العناصر التي تُشغَّل عند تسجيل الدخول فقط",
    },
    "startup.filter.disabled_tooltip": {
        "en": "Show only the items you have already disabled",
        "ar": "عرض العناصر التي عطّلتها بالفعل فقط",
    },
    "startup.filter.recommended_tooltip": {
        "en": "Show only the enabled items this audit recommends "
              "disabling",
        "ar": "عرض العناصر المفعَّلة التي ينصح هذا التدقيق بتعطيلها "
              "فقط",
    },
    "startup.optimize_btn": {
        "en": "Optimize Startup",
        "ar": "تحسين بدء التشغيل",
    },
    "startup.optimize_btn_count": {
        "en": "Optimize Startup ({count})",
        "ar": "تحسين بدء التشغيل ({count})",
    },
    "startup.optimize_tooltip": {
        "en": "Disables every currently-enabled item the audit "
              "recommends disabling, one by one. Never touches a "
              "System Critical item.",
        "ar": "يعطّل كل عنصر مفعَّل حاليًا ينصح التدقيق بتعطيله، "
              "واحدًا تلو الآخر. لا يمسّ أي عنصر حرج للنظام أبدًا.",
    },
    "startup.rescan_tooltip": {
        "en": "Re-read the Run keys, Startup folders and sign-in "
              "tasks.",
        "ar": "إعادة قراءة مفاتيح Run ومجلدات بدء التشغيل ومهام "
              "تسجيل الدخول.",
    },
    "startup.filter_note": {
        "en": "Filtered — {shown} of {total} items shown ({hidden} "
              "hidden). Click the highlighted pill again, or "
              "“All”, to show everything.",
        "ar": "مُصفًّى — يُعرض {shown} من {total} عنصرًا ({hidden} "
              "مخفي). انقر الشارة المميَّزة مجددًا، أو “الكل"
              "”، لعرض كل شيء.",
    },
    "startup.section.disable": {
        "en": "⚠️  Recommended to Disable",
        "ar": "⚠️  يُنصح بتعطيله",
    },
    "startup.section.review": {
        "en": "🔎  Worth Reviewing",
        "ar": "🔎  يستحق المراجعة",
    },
    "startup.section.keep": {
        "en": "✅  Safe to Keep",
        "ar": "✅  آمن الإبقاء عليه",
    },
    "startup.section.off": {
        "en": "⏸️  Currently Disabled",
        "ar": "⏸️  معطَّل حاليًا",
    },
    "startup.section_header": {
        "en": "{label}   ·   {count}",
        "ar": "{label}   ·   {count}",
    },
    "startup.boot_summary.base": {
        "en": "Toggle any item to change it instantly — changes are "
              "reversible.",
        "ar": "بدِّل أي عنصر لتغييره فورًا — التغييرات قابلة للتراجع.",
    },
    "startup.boot_summary.last_boot": {
        "en": "Last boot took {seconds}s",
        "ar": "استغرق آخر إقلاع {seconds} ثانية",
    },
    "startup.boot_summary.average_suffix": {
        "en": " (average {avg}s over {boots} boots)",
        "ar": " (بمتوسط {avg} ثانية على مدى {boots} إقلاعًا)",
    },
    "startup.boot_summary.measured_singular": {
        "en": "{measured} entry was measured slowing it down. ",
        "ar": "قِيس عنصر واحد يبطئه. ",
    },
    "startup.boot_summary.measured_plural": {
        "en": "{measured} entries were measured slowing it down. ",
        "ar": "قِيست {measured} عناصر تبطئه. ",
    },
    "startup.boot_summary.needs_admin": {
        "en": "Impact badges are estimates — Windows records real "
              "boot delays, but reading them needs administrator. ",
        "ar": "شارات الأثر تقديرية — يسجّل ويندوز تأخيرات الإقلاع "
              "الحقيقية، لكن قراءتها تتطلب صلاحيات المسؤول. ",
    },
    "startup.boot_summary.log_disabled": {
        "en": "Impact badges are estimates — this PC's "
              "boot-performance log is turned off. ",
        "ar": "شارات الأثر تقديرية — سجل أداء الإقلاع على هذا الجهاز "
              "معطَّل. ",
    },
    "startup.status.disabling": {
        "en": "Disabling {count} recommended item(s)…",
        "ar": "جارٍ تعطيل {count} عنصر موصى به…",
    },
    # -- StartupRow's own badges/tooltips ---------------------------------
    "startup.rec.disable": {
        "en": "Recommended to Disable",
        "ar": "يُنصح بتعطيله",
    },
    "startup.rec.keep": {
        "en": "Safe to Keep",
        "ar": "آمن الإبقاء عليه",
    },
    "startup.rec.review": {
        "en": "Worth Reviewing",
        "ar": "يستحق المراجعة",
    },
    "startup.rec.critical": {
        "en": "System Critical",
        "ar": "حرج للنظام",
    },
    "startup.missing_badge": {
        "en": "MISSING",
        "ar": "مفقود",
    },
    "startup.missing_tooltip": {
        "en": "This entry points at a program that is not on this PC "
              "any more — usually software that was uninstalled "
              "without its startup entry being removed. Windows "
              "still tries to launch it at every boot. Turning it "
              "off is safe.",
        "ar": "يشير هذا العنصر إلى برنامج لم يعد على هذا الجهاز — "
              "غالبًا برنامج أُزيل دون إزالة عنصر بدء تشغيله. لا "
              "يزال ويندوز يحاول تشغيله كل إقلاع. تعطيله آمن.",
    },
    "startup.protected_tooltip": {
        "en": "Pulse never recommends disabling this one, and "
              "“Optimize Startup” will not touch it. You "
              "can still toggle it by hand.",
        "ar": "لا يوصي Pulse أبدًا بتعطيل هذا العنصر، ولن يمسّه "
              "“تحسين بدء التشغيل”. يمكنك مع ذلك تبديله "
              "يدويًا.",
    },
    "startup.no_target_tooltip": {
        "en": "This entry names no target.",
        "ar": "هذا العنصر لا يسمّي هدفًا.",
    },
    "startup.impact.measured": {
        "en": "DELAYS BOOT {seconds}s",
        "ar": "يؤخر الإقلاع {seconds} ث",
    },
    "startup.impact.measured_tooltip_singular": {
        "en": "Measured by Windows: this entry slowed {samples} "
              "recent boot by {seconds}s on average",
        "ar": "قاسه ويندوز: أبطأ هذا العنصر إقلاعًا واحدًا حديثًا "
              "بمعدل {seconds} ثانية",
    },
    "startup.impact.measured_tooltip_plural": {
        "en": "Measured by Windows: this entry slowed {samples} "
              "recent boots by {seconds}s on average",
        "ar": "قاسه ويندوز: أبطأ هذا العنصر {samples} إقلاعات "
              "حديثة بمعدل {seconds} ثانية",
    },
    "startup.impact.measured_worst_suffix": {
        "en": ", {worst}s at worst",
        "ar": "، وحتى {worst} ثانية في أسوأ حال",
    },
    "startup.impact.estimated_tooltip": {
        "en": "Estimated from what this kind of program usually "
              "costs at startup — not a measurement taken on this "
              "PC.",
        "ar": "تقدير مبني على التكلفة المعتادة لهذا النوع من "
              "البرامج عند بدء التشغيل — وليس قياسًا فعليًا على هذا "
              "الجهاز.",
    },
    "startup.impact.high": {
        "en": "HIGH",
        "ar": "عالي",
    },
    "startup.impact.medium": {
        "en": "MEDIUM",
        "ar": "متوسط",
    },
    "startup.impact.low": {
        "en": "LOW",
        "ar": "منخفض",
    },
    "startup.impact.suffix": {
        "en": "{impact} IMPACT",
        "ar": "أثر {impact}",
    },
    "startup.type.registry": {
        "en": "Registry (Run key)",
        "ar": "السجل (مفتاح Run)",
    },
    "startup.type.task": {
        "en": "Scheduled task ({trigger})",
        "ar": "مهمة مجدولة ({trigger})",
    },
    "startup.type.task_default_trigger": {
        "en": "at sign-in",
        "ar": "عند تسجيل الدخول",
    },
    "startup.type.folder": {
        "en": "Startup folder shortcut",
        "ar": "اختصار في مجلد بدء التشغيل",
    },
    "startup.missing_reason": {
        "en": "The program this points at is not installed any "
              "more. Windows tries to start it at every boot and "
              "fails; turning it off is safe.",
        "ar": "البرنامج الذي يشير إليه هذا العنصر لم يعد مثبَّتًا. "
              "يحاول ويندوز تشغيله كل إقلاع ويفشل؛ تعطيله آمن.",
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
