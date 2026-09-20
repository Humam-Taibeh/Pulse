"""
src/frontend/i18n.py

DISPLAY LANGUAGE (v10.15, extended v16) — a manual English/Arabic
choice, not "follow Windows".

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
Windows-assigned description) do not. A key with no entry in STRINGS
degrades to the key itself — visible-but-safe, matching theme.glyph()'s
"a missing table entry degrades, never crashes" posture — rather than
raising, so a half-translated surface never becomes a broken one.

WHAT STILL STAYS ENGLISH, on purpose (see ROADMAP.md for the tracked
follow-up): the live PowerShell console log, playbooks, the Health
Report, and dialogs reached FROM a card rather than shown directly — the
Restore Point Browser, Startup Manager, Bloatware Purge internals,
Update Center, the Office setup wizard, per-app install-option pickers.
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
}


def tr(key: str, lang: str) -> str:
    """Look up `key` in `STRINGS` for `lang`, falling back to English and
    then to the key itself — the same "degrade, never crash" contract
    theme.glyph() already holds the app to."""
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key
