"""
src/frontend/i18n.py

DISPLAY LANGUAGE (v10.15, extended v16, v16.1, v10.17.1, v10.17.2,
v10.17.3) — a manual English/Arabic choice, not "follow Windows".

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

v10.17.1 closes two more gaps. The bottom status strip (widgets.
ActivityDrawer's always-visible rail — CHANGELOG.md's own "bottom status
bar" note) now translates its canonical states ("System Ready",
"Administrator rights required", "Stopping task…", the Stop button and
its tooltip, the pin chevron): a DYNAMIC status (a live backend phase
line, a catalog item's own title baked into "Executing: X…") stays
English along with the console it echoes into, exactly like everywhere
else — main.PulseApp tracks which kind is currently showing via
_status_key/_set_canonical_status, since only it knows. The
OfficeWizardDialog wizard and ToolInstallWizardDialog's install-option
picker — named explicitly, in every release note through v10.17.0, as
the last still-English "dialogs reached from a card" — now translate in
full too; both are built fresh on every open, like Update Center/
Bloatware Purge/Startup Manager, so `lang` is read once at construction.

v10.17.2 closes the "any remaining tool dialogs" gap for the two
surfaces named explicitly: PATH Doctor and Leftovers Cleaner, end to
end — HubDialog/ActionRow (the shell both of them, and every other hub
card — Microsoft Edge, Microsoft OneDrive, Network & Connectivity —
open into), PathConflictDialog ("Fix Shadowed Tools") and its
widgets.InspectorDialog base shell, and LeftoversDialog/LeftoverRow
("Scan & Purge Leftovers"). InspectorDialog's TITLE/LOADING gained
opt-in TITLE_KEY/LOADING_KEY counterparts, so a subclass that wants
translation adds two class attributes rather than the base class
forcing it on every subclass. Several backend-authored data points
translate on the established "Pulse's own deterministic copy, not live
system output" reasoning BloatRow's Note/StartupRow's Reason already
set: PathConflictDialog's verdict buttons ("Use this one"/"In use"/
"Needs administrator"/…, the exhaustive `Short` values 03-Environment.
ps1's Get-PathPriorityPlan/Get-PathInstallPlan return) and LeftoverRow's
own reason line (17-Leftovers.ps1's `-Reason` literals) — both routed
through i18n_catalog.

v10.17.3 closes the rest of the inspector/action-dialog roster named
explicitly in that pass: PowerHealthDialog/StorageAnalyzerDialog/
DnsSwitcherDialog/ContextMenuDialog (InspectorDialog's other three
subclasses, opting into TITLE_KEY/LOADING_KEY the same way
PathConflictDialog does) and the smaller one-off dialogs — NoticeDialog,
RevertChoiceDialog, PlaybookDialog, ActivationStatusDialog,
CloseConfirmDialog, ElevatePromptDialog, ShortcutSheetDialog,
SelfUpdateDialog, DataHygieneDialog. Two more finite, non-interpolated
string sets joined the i18n_catalog exact-text roster: utils.updater.
can_apply()'s one refusal reason (SelfUpdateDialog's notes page) and
PulseApp.SHORTCUTS' nine row descriptions (ShortcutSheetDialog).
ActivationStatusDialog's own product `status`/`channel`/`explanation`
fields stay English on purpose — most of 13-Activation.ps1's explanation
variants interpolate a live day-count, so an exact-text lookup cannot
carry them; this is the same "dynamic content stays English" boundary
PathConflictDialog's `reason` tooltip already sits on, not an oversight.
Every dialog this pass touched is either InspectorDialog's own opt-in
mechanism or built fresh on every open, so none of them needed a
retranslate() path.

WHAT STILL STAYS ENGLISH, on purpose (see ROADMAP.md for the tracked
follow-up): the live PowerShell console log (including any TaskResult
message reported at runtime — a toggle's own success/failure line, a
scan's caveat, its Trigger value, PathConflictDialog's own long-form
`reason` tooltip), playbooks, the Health Report, and the Restore Point
Browser (widgets.RestorePointDialog deliberately does not opt into
InspectorDialog's TITLE_KEY/LOADING_KEY). SettingsView's own
UPDATE_STATE_TEXTS vocabulary (IDLE/CHECKING/UP TO DATE/UPDATE READY)
stays deferred too — see widgets.py's own note on it. The elevation
state's own text (now Settings' Session group, formerly the sidebar's
widgets.StatusRail) and the activity drawer's own canonical states are
NOT on this list — see the "settings: Session" and "activity drawer"
sections below.

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

    # -- settings: Session (v10.17.2) --------------------------------------
    # v16 ("ultra-clean footer") had already removed the theme toggle, the
    # update badge and the version/identity line from the sidebar footer,
    # leaving only the elevation/engine indicator (widgets.StatusRail) as
    # a standalone shield button there. v10.17.2 removes that too: a
    # control glanced at maybe once a session does not earn a permanent
    # icon-only seat in the busiest real estate in the window, and every
    # other "how this session is set up" fact already lives in Settings —
    # so this one now does too, as a plain captioned row (General's theme
    # picker, this group's session state) rather than a painted icon.
    "settings.group.session": {
        "en": "Session",
        "ar": "الجلسة",
    },
    "settings.session.engine_missing_detail": {
        "en": "The PowerShell engine is missing — Pulse can report but "
              "cannot run operations.",
        "ar": "محرك PowerShell غير موجود — يمكن لـPulse الإبلاغ لكن لا "
              "يمكنه تنفيذ العمليات.",
    },
    "settings.session.admin_detail": {
        "en": "Running as Administrator — every operation is available.",
        "ar": "يعمل بصلاحيات المسؤول — كل العمليات متاحة.",
    },
    "settings.session.not_admin_detail": {
        "en": "Not elevated. Some system-level operations need "
              "Administrator rights — click to relaunch (a UAC prompt "
              "will appear).",
        "ar": "غير مرتفع الصلاحيات. بعض عمليات مستوى النظام تحتاج "
              "صلاحيات المسؤول — انقر لإعادة التشغيل (ستظهر نافذة "
              "UAC).",
    },
    "settings.session.relaunch_btn": {
        "en": "Relaunch as Administrator",
        "ar": "إعادة التشغيل كمسؤول",
    },

    # -- activity drawer / status strip (v10.17.1) -------------------------
    # The always-visible 44px rail (status dot, status text, Stop button,
    # pin chevron) — CHANGELOG.md's "bottom status bar", the last chrome
    # surface still hardcoded English. Only the rail's own canonical
    # states are covered here: a dynamic phase line (main._set_status fed
    # a live backend stage or a catalog item's title, e.g. "Downloading
    # Firefox 145.0…") stays English along with the live console it
    # echoes into, same boundary as everywhere else — see main.py's own
    # _status_key/_set_canonical_status split.
    "activity.status.ready": {
        "en": "System Ready",
        "ar": "النظام جاهز",
    },
    "activity.status.admin_required": {
        "en": "Administrator rights required",
        "ar": "صلاحيات المسؤول مطلوبة",
    },
    "activity.status.stopping": {
        "en": "Stopping task…",
        "ar": "جارٍ إيقاف المهمة…",
    },
    "activity.stop_btn": {
        "en": "■  Stop Task",
        "ar": "■  إيقاف المهمة",
    },
    "activity.stop_btn.stopping": {
        "en": "Stopping…",
        "ar": "جارٍ الإيقاف…",
    },
    "activity.stop_btn_tooltip": {
        "en": "Hard-stop the running task (kills the whole process tree)",
        "ar": "إيقاف قسري للمهمة الجارية (يُنهي شجرة العمليات بأكملها)",
    },
    "activity.pin.open_tooltip": {
        "en": "Pin the live output open",
        "ar": "تثبيت الإخراج المباشر مفتوحًا",
    },
    "activity.pin.unpin_tooltip": {
        "en": "Unpin the live output",
        "ar": "إلغاء تثبيت الإخراج المباشر",
    },
    "activity.engine_ready_toast": {
        "en": "Engine ready — all modules loaded.",
        "ar": "المحرك جاهز — تم تحميل كل الوحدات.",
    },
    "activity.engine_missing_toast": {
        "en": "{filename} not found next to the app.",
        "ar": "لم يُعثر على {filename} بجانب التطبيق.",
    },
    "activity.not_admin_toast": {
        "en": "Not running as Administrator — system tasks will prompt to "
              "relaunch elevated. Settings' Session group does it in one "
              "click.",
        "ar": "لا يعمل بصلاحيات المسؤول — ستطلب مهام النظام إعادة التشغيل "
              "بصلاحيات مرتفعة. مجموعة الجلسة في الإعدادات تقوم بذلك "
              "بنقرة واحدة.",
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

    # ============================================================
    #  OFFICE DEPLOYMENT WIZARD (v10.17.1)
    # ============================================================
    # OfficeWizardDialog's own chrome — built fresh on every open, same
    # shape as CommandPalette/SoftwareCatalogDialog: `lang` is read once
    # at construction, no retranslate() needed. The choice page's three
    # GlassCards route through i18n_catalog instead (see its own note),
    # since GlassCard only knows that lookup; everything else here is
    # this dialog's own static chrome or a format template it fills with
    # a live file path — never translated content of its own.
    "office_wizard.title": {
        "en": "📄  Microsoft Office Deployment",
        "ar": "📄  نشر Microsoft Office",
    },
    "office_wizard.step.choice": {
        "en": "Choose how you'd like to proceed",
        "ar": "اختر كيف تريد المتابعة",
    },
    "office_wizard.step.auto_confirm": {
        "en": "Automated Cloud Download",
        "ar": "تنزيل سحابي تلقائي",
    },
    "office_wizard.step.guide": {
        "en": "Beginner Guide — get the official tools",
        "ar": "دليل المبتدئين — احصل على الأدوات الرسمية",
    },
    "office_wizard.step.locate": {
        "en": "Locate your Office files",
        "ar": "حدد موقع ملفات Office الخاصة بك",
    },
    "office_wizard.step.confirm": {
        "en": "Confirm & Install",
        "ar": "تأكيد وتثبيت",
    },
    "office_wizard.back": {
        "en": "‹  Back",
        "ar": "‹  رجوع",
    },
    "office_wizard.choice.intro": {
        "en": "Office ships as one bundle through Microsoft's official "
              "Deployment Tool (ODT) — there's no per-app silent "
              "installer. Choose how you'd like to proceed.",
        "ar": "يُشحن Office كحزمة واحدة عبر أداة النشر الرسمية من "
              "Microsoft (ODT) — لا يوجد مثبِّت صامت لكل تطبيق على حدة. "
              "اختر كيف تريد المتابعة.",
    },
    "office_wizard.auto.info": {
        "en": "Pulse will download the official Office Click-to-Run "
              "client and write a standard configuration to "
              "<b>Desktop\\Office</b> — Word, Excel, PowerPoint and "
              "Outlook in English and Arabic. No files to find, nothing "
              "to configure by hand.",
        "ar": "سيُنزِّل Pulse عميل Office Click-to-Run الرسمي ويكتب "
              "تكوينًا قياسيًا إلى <b>سطح المكتب\\Office</b> — Word "
              "وExcel وPowerPoint وOutlook بالإنجليزية والعربية. لا "
              "ملفات لإيجادها، ولا شيء لضبطه يدويًا.",
    },
    "office_wizard.auto.note": {
        "en": "ℹ️  This standard configuration targets Volume License "
              "activation (no product key baked in). If your network "
              "has a KMS host it activates automatically; otherwise "
              "Office installs but stays unactivated until a key is "
              "added. Prefer a subscription install with your own "
              "settings? Use one of the other two paths instead.",
        "ar": "ℹ️  يستهدف هذا التكوين القياسي تفعيل ترخيص الحجم "
              "(Volume License) دون مفتاح منتج مضمَّن. إن كانت شبكتك "
              "تضم مضيف KMS فسيُفعَّل تلقائيًا؛ وإلا فسيُثبَّت Office "
              "لكنه يبقى غير مفعَّل حتى تُضاف مفتاح. تفضّل تثبيت اشتراك "
              "بإعداداتك الخاصة؟ استخدم أحد المسارين الآخرين بدلًا من "
              "ذلك.",
    },
    "office_wizard.warn_dont_close": {
        "en": "⚠️  IMPORTANT: When the Microsoft Setup window appears, "
              "DO NOT close it or open any other apps until it reaches "
              "100%.",
        "ar": "⚠️  مهم: عند ظهور نافذة إعداد Microsoft، لا تُغلقها ولا "
              "تفتح أي تطبيقات أخرى حتى تصل إلى 100%.",
    },
    "office_wizard.auto.install_btn": {
        "en": "Download && Install Now",
        "ar": "تنزيل && تثبيت الآن",
    },
    "office_wizard.guide.step1": {
        "en": "Open the Deployment Tool below, run it, and extract it "
              "into a folder named <b>Office</b> on your Desktop.",
        "ar": "افتح أداة النشر أدناه، شغِّلها، واستخرجها إلى مجلد باسم "
              "<b>Office</b> على سطح مكتبك.",
    },
    "office_wizard.guide.step2": {
        "en": "Open the Customization Tool below, choose your apps, "
              "languages and channel, then download the resulting "
              "<b>configuration.xml</b> into that same Office folder.",
        "ar": "افتح أداة التخصيص أدناه، اختر تطبيقاتك ولغاتك وقناتك، ثم "
              "نزِّل ملف <b>configuration.xml</b> الناتج إلى مجلد "
              "Office نفسه.",
    },
    "office_wizard.guide.step3": {
        "en": "Come back here and continue — Pulse will pick up both "
              "files automatically.",
        "ar": "عد إلى هنا وتابع — سيلتقط Pulse كلا الملفين تلقائيًا.",
    },
    "office_wizard.guide.odt_link": {
        "en": "🌐  Open Office Deployment Tool   ↗",
        "ar": "🌐  فتح أداة نشر Office   ↗",
    },
    "office_wizard.guide.oct_link": {
        "en": "⚙️  Open Office Customization Tool   ↗",
        "ar": "⚙️  فتح أداة تخصيص Office   ↗",
    },
    "office_wizard.guide.continue_btn": {
        "en": "I have the files now  ›",
        "ar": "لدي الملفات الآن  ›",
    },
    "office_wizard.locate.found": {
        "en": "✅  Found in <b>{folder}</b>",
        "ar": "✅  وُجد في <b>{folder}</b>",
    },
    "office_wizard.locate.setup_label": {
        "en": "<b>Setup:</b> {path}",
        "ar": "<b>الإعداد:</b> {path}",
    },
    "office_wizard.locate.config_label": {
        "en": "<b>Config:</b> {path}",
        "ar": "<b>التكوين:</b> {path}",
    },
    "office_wizard.locate.pick_config": {
        "en": "Found {n} configuration files — which one should Pulse "
              "use?",
        "ar": "عُثر على {n} ملفات تكوين — أيها يجب أن يستخدم Pulse؟",
    },
    "office_wizard.locate.recommended_tag": {
        "en": "  (recommended)",
        "ar": "  (موصى به)",
    },
    "office_wizard.locate.browse_other": {
        "en": "📂  Browse for a different folder…",
        "ar": "📂  تصفّح مجلدًا آخر…",
    },
    "office_wizard.locate.continue_btn": {
        "en": "Continue  ›",
        "ar": "متابعة  ›",
    },
    "office_wizard.locate.missing": {
        "en": "⚠️  No Office folder with both setup.exe and a "
              "configuration file was found automatically (checked "
              "<b>{folder}</b>).",
        "ar": "⚠️  لم يُعثر تلقائيًا على مجلد Office يحوي كلًا من "
              "setup.exe وملف تكوين (تم التحقق من <b>{folder}</b>).",
    },
    "office_wizard.locate.browse_folder": {
        "en": "📂  Browse for the Office folder…",
        "ar": "📂  تصفّح مجلد Office…",
    },
    "office_wizard.locate.pick_individually": {
        "en": "🗂️  Pick setup.exe and configuration.xml individually…",
        "ar": "🗂️  اختر setup.exe وconfiguration.xml كلًا على حدة…",
    },
    "office_wizard.locate.retry": {
        "en": "Retry auto-detect",
        "ar": "إعادة محاولة الاكتشاف التلقائي",
    },
    "office_wizard.locate.missing_setup": {
        "en": "setup.exe (or the ODT self-extractor)",
        "ar": "setup.exe (أو المستخرج الذاتي لـODT)",
    },
    "office_wizard.locate.missing_config": {
        "en": "a configuration .xml file",
        "ar": "ملف تكوين .xml",
    },
    "office_wizard.locate.incomplete": {
        "en": "❌  <b>{folder}</b> is missing: {missing}",
        "ar": "❌  <b>{folder}</b> ينقصه: {missing}",
    },
    "office_wizard.locate.pick_individually_short": {
        "en": "🗂️  Pick the files individually…",
        "ar": "🗂️  اختر الملفات كلًا على حدة…",
    },
    "office_wizard.locate.browse_again": {
        "en": "Browse again",
        "ar": "تصفّح مجددًا",
    },
    "office_wizard.locate.browse_dialog_title": {
        "en": "Select the folder with setup.exe and configuration.xml",
        "ar": "حدد المجلد الذي يحوي setup.exe وconfiguration.xml",
    },
    "office_wizard.locate.pick_setup_dialog_title": {
        "en": "Select the Office Deployment Tool (setup.exe)",
        "ar": "حدد أداة نشر Office (setup.exe)",
    },
    "office_wizard.locate.pick_setup_filter": {
        "en": "Executable files (*.exe)",
        "ar": "الملفات التنفيذية (*.exe)",
    },
    "office_wizard.locate.pick_config_dialog_title": {
        "en": "Select configuration.xml",
        "ar": "حدد configuration.xml",
    },
    "office_wizard.locate.pick_config_filter": {
        "en": "XML files (*.xml)",
        "ar": "ملفات XML (*.xml)",
    },
    "office_wizard.confirm.summary": {
        "en": "<b>Setup:</b> {setup}<br><b>Config:</b> {config}",
        "ar": "<b>الإعداد:</b> {setup}<br><b>التكوين:</b> {config}",
    },
    "office_wizard.confirm.install_btn": {
        "en": "Install Now",
        "ar": "تثبيت الآن",
    },

    # ============================================================
    #  TOOL INSTALL WIZARD — per-app winget option picker (v10.17.1)
    # ============================================================
    "tool_install.note": {
        "en": "Pulse installs this silently with winget — the same path "
              "it uses everywhere else.",
        "ar": "يثبِّت Pulse هذا بصمت عبر winget — نفس المسار الذي "
              "يستخدمه في كل مكان آخر.",
    },
    "tool_install.install_btn": {
        "en": "Automated Install (winget)",
        "ar": "تثبيت تلقائي (winget)",
    },
    "tool_install.website_btn": {
        "en": "Visit Official Website",
        "ar": "زيارة الموقع الرسمي",
    },
    "tool_install.website_tooltip_named": {
        "en": "Opens {name}'s official download page in your browser.",
        "ar": "يفتح صفحة تنزيل {name} الرسمية في متصفحك.",
    },
    "tool_install.website_tooltip_generic": {
        "en": "Opens a web search for the official download page.",
        "ar": "يفتح بحثًا على الويب عن صفحة التنزيل الرسمية.",
    },
    # The one caller-supplied `desc` this dialog is opened with today
    # (PulseApp's bundled-app restore flow, _RESTORE_TARGETS) — kept here
    # rather than inline so the sentence a user sees INSIDE a now-Arabic
    # dialog isn't the one part of it still hardcoded English.
    "tool_install.not_installed_desc": {
        "en": "{name} is not currently installed. Choose how to put it "
              "back.",
        "ar": "{name} غير مثبَّت حاليًا. اختر كيف تريد إعادته.",
    },

    # ============================================================
    #  HUB DIALOG — PATH Doctor, Leftovers Cleaner, Edge, OneDrive,
    #  Network & Connectivity (v10.17.2)
    # ============================================================
    # HubDialog itself is built fresh on every open (no retranslate()
    # needed, same shape as CommandPalette/SoftwareCatalogDialog). Its
    # hub['title']/hub['desc'] and every ActionRow's item['title']/
    # item['desc'] already have entries in i18n_catalog (the hub is also
    # a card, translated there since v16); only these action VERBS are
    # new — short, reused across every hub, so they read as chrome
    # vocabulary (i18n.py) rather than catalog copy (i18n_catalog.py).
    "hub.action.scan": {"en": "Scan", "ar": "فحص"},
    "hub.action.fix": {"en": "Fix", "ar": "إصلاح"},
    "hub.action.prune": {"en": "Prune", "ar": "تقليم"},
    "hub.action.restore": {"en": "Restore", "ar": "استعادة"},
    "hub.action.open": {"en": "Open", "ar": "فتح"},
    "hub.action.remove": {"en": "Remove", "ar": "إزالة"},
    "hub.action.reinstall": {"en": "Reinstall", "ar": "إعادة تثبيت"},
    "hub.action.install": {"en": "Install", "ar": "تثبيت"},
    "hub.action.run": {"en": "Run", "ar": "تشغيل"},
    "hub.action.check": {"en": "Check", "ar": "فحص"},
    "hub.action.reset": {"en": "Reset", "ar": "إعادة ضبط"},

    # ============================================================
    #  INSPECTOR DIALOGS — shared shell (v10.17.2)
    # ============================================================
    # widgets.InspectorDialog's own chrome: TITLE/LOADING move from class-
    # level literals to class-level i18n KEYS (TITLE_KEY/LOADING_KEY) so
    # each subclass still owns its own text without hardcoding English.
    # RestorePointDialog is the one subclass that does NOT opt in — the
    # Restore Point Browser stays English on purpose, same documented
    # boundary as the Health Report (see i18n.py's own module docstring).
    "inspector.close": {
        "en": "Close",
        "ar": "إغلاق",
    },
    "inspector.rescan": {
        "en": "Re-scan",
        "ar": "إعادة الفحص",
    },
    "inspector.recheck": {
        "en": "Re-check",
        "ar": "إعادة التحقق",
    },
    "inspector.unknown": {
        "en": "Unknown",
        "ar": "غير معروف",
    },
    "inspector.not_reported": {
        "en": "Not reported",
        "ar": "غير مُبلَّغ عنه",
    },
    "inspector.enabled": {
        "en": "Enabled",
        "ar": "مفعَّل",
    },
    "inspector.disabled": {
        "en": "Disabled",
        "ar": "معطَّل",
    },
    "inspector.loading": {
        "en": "Reading…",
        "ar": "جارٍ القراءة…",
    },
    "inspector.engine_unavailable": {
        "en": "Engine unavailable — core.ps1 was not found.",
        "ar": "المحرك غير متاح — لم يُعثر على core.ps1.",
    },
    "inspector.report_unreadable": {
        "en": "The report could not be read.",
        "ar": "تعذّرت قراءة التقرير.",
    },

    # ============================================================
    #  PATH CONFLICT DIALOG — PATH Doctor's "Fix Shadowed Tools" (v10.17.2)
    # ============================================================
    "path_conflict.title": {
        "en": "🧭  Shadowed Tools",
        "ar": "🧭  الأدوات المتراكبة",
    },
    "path_conflict.loading": {
        "en": "Scanning your PATH for tools with more than one copy…",
        "ar": "جارٍ فحص PATH بحثًا عن أدوات لها أكثر من نسخة…",
    },
    "path_conflict.elevate_btn": {
        "en": "Restart as administrator",
        "ar": "إعادة التشغيل كمسؤول",
    },
    "path_conflict.elevate_tooltip": {
        "en": "Reordering the system PATH needs an elevated Pulse. This "
              "closes Pulse and reopens it with administrator rights; "
              "Windows will ask you to confirm.",
        "ar": "إعادة ترتيب PATH النظام يتطلب صلاحيات مرتفعة لـPulse. "
              "سيُغلق هذا Pulse ويعيد فتحه بصلاحيات المسؤول؛ سيطلب "
              "ويندوز تأكيدك.",
    },
    "path_conflict.nothing_shadowed": {
        "en": "Nothing is shadowed. Across {entries} PATH entries, "
              "every tool Pulse checks is answered by exactly one "
              "installation.",
        "ar": "لا شيء متراكب. عبر {entries} إدخالًا في PATH، تُجيب "
              "تثبيتة واحدة فقط عن كل أداة يتحقق منها Pulse.",
    },
    "path_conflict.nothing_to_fix_title": {
        "en": "Nothing to fix",
        "ar": "لا شيء لإصلاحه",
    },
    "path_conflict.nothing_to_fix_note": {
        "en": "Pulse looks for a second copy of the tools where "
              "“which one wins?” is a question people actually "
              "have to debug — interpreters, package managers, "
              "compilers and build drivers. A machine with one of each "
              "has nothing to show here, which is the healthy result.",
        "ar": "يبحث Pulse عن نسخة ثانية للأدوات التي يُضطر الناس فعليًا "
              "لتشخيص سؤال «أيّها يفوز؟» بشأنها — المفسِّرات، ومديرو "
              "الحزم، والمترجمات، وأدوات البناء. جهاز يملك نسخة واحدة "
              "من كل منها لا يُظهر شيئًا هنا، وهذه هي النتيجة السليمة.",
    },
    "path_conflict.status_singular": {
        "en": "1 toolchain has more than one installation on this "
              "PATH, across {entries} entries. Choosing one REORDERS "
              "your PATH so it is found first — nothing is removed, "
              "and an installation's folders always move together.",
        "ar": "سلسلة أدوات واحدة لها أكثر من تثبيتة على PATH هذا، عبر "
              "{entries} إدخالًا. اختيار واحدة يُعيد ترتيب PATH ليُعثر "
              "عليها أولًا — لا يُزال شيء، ومجلدات كل تثبيتة تنتقل معًا "
              "دائمًا.",
    },
    "path_conflict.status_plural": {
        "en": "{count} toolchains have more than one installation on "
              "this PATH, across {entries} entries. Choosing one "
              "REORDERS your PATH so it is found first — nothing is "
              "removed, and an installation's folders always move "
              "together.",
        "ar": "{count} سلاسل أدوات لها أكثر من تثبيتة على PATH هذا، "
              "عبر {entries} إدخالًا. اختيار واحدة يُعيد ترتيب PATH "
              "ليُعثر عليها أولًا — لا يُزال شيء، ومجلدات كل تثبيتة "
              "تنتقل معًا دائمًا.",
    },
    "path_conflict.installation_singular": {
        "en": "{count} INSTALLATION",
        "ar": "تثبيتة واحدة",
    },
    "path_conflict.installation_plural": {
        "en": "{count} INSTALLATIONS",
        "ar": "{count} تثبيتات",
    },
    "path_conflict.commands_label": {
        "en": "Commands",
        "ar": "الأوامر",
    },
    "path_conflict.system_path": {
        "en": "System PATH",
        "ar": "PATH النظام",
    },
    "path_conflict.user_path": {
        "en": "Your PATH",
        "ar": "PATH الخاص بك",
    },
    "path_conflict.more_folder_singular": {
        "en": "   (+{n} more folder)",
        "ar": "   (+{n} مجلد إضافي)",
    },
    "path_conflict.more_folder_plural": {
        "en": "   (+{n} more folders)",
        "ar": "   (+{n} مجلدات إضافية)",
    },
    "path_conflict.applying_status": {
        "en": "Making {directory} the installation in use…",
        "ar": "جارٍ جعل {directory} التثبيتة المستخدَمة…",
    },
    "path_conflict.applied_fallback": {
        "en": "PATH updated.",
        "ar": "تم تحديث PATH.",
    },
    "path_conflict.apply_failed": {
        "en": "The PATH was not changed: {message}",
        "ar": "لم يتغيّر PATH: {message}",
    },

    # ============================================================
    #  LEFTOVERS CLEANER (v10.17.2)
    # ============================================================
    # Built fresh on every open (no retranslate() needed, same shape as
    # the other scan-and-select dialogs). Select All/Deselect All, the
    # count chip and the Safe Purge button reuse the exact same English
    # text the Bloatware Purge/Software Catalog dialogs already use
    # (catalog.select_all/deselect_all, bloatware.count.selected,
    # bloatware.purge_btn/purge_btn_count) — one key each, not
    # duplicated here.
    "leftovers.title": {
        "en": "🧽  Leftovers Cleaner",
        "ar": "🧽  منظّف المخلّفات",
    },
    "leftovers.subtitle.scanning": {
        "en": "Looking for what uninstalled software left behind…",
        "ar": "جارٍ البحث عمّا خلّفته البرامج التي أُزيلت…",
    },
    "leftovers.loading": {
        "en": "Checking startup entries, scheduled tasks, app folders "
              "and the right-click menu for anything pointing at "
              "software that is gone…",
        "ar": "جارٍ فحص إدخالات بدء التشغيل والمهام المجدولة ومجلدات "
              "التطبيقات وقائمة النقر بالزر الأيمن بحثًا عمّا يشير إلى "
              "برامج لم تعد موجودة…",
    },
    "leftovers.error.scan_failed": {
        "en": "The leftovers scan returned nothing.",
        "ar": "لم يعد فحص المخلّفات بأي نتيجة.",
    },
    "leftovers.error.suffix": {
        "en": "\n\nNothing was changed.",
        "ar": "\n\nلم يتغيّر شيء.",
    },
    "leftovers.clean.headline": {
        "en": "Nothing left behind",
        "ar": "لا شيء متروك خلفًا",
    },
    "leftovers.clean.note": {
        "en": "No startup entry, scheduled task, app folder or "
              "right-click entry on this PC points at software that "
              "has been removed.",
        "ar": "لا يوجد إدخال بدء تشغيل، أو مهمة مجدولة، أو مجلد "
              "تطبيق، أو إدخال نقر بزر أيمن على هذا الجهاز يشير إلى "
              "برنامج أُزيل.",
    },
    "leftovers.clean.checked_subtitle": {
        "en": "Checked startup entries, scheduled tasks, app folders "
              "and the right-click menu.",
        "ar": "تم فحص إدخالات بدء التشغيل والمهام المجدولة ومجلدات "
              "التطبيقات وقائمة النقر بالزر الأيمن.",
    },
    "leftovers.section.startup": {
        "en": "Startup entries",
        "ar": "إدخالات بدء التشغيل",
    },
    "leftovers.section.tasks": {
        "en": "Scheduled tasks",
        "ar": "المهام المجدولة",
    },
    "leftovers.section.residue": {
        "en": "Abandoned app folders",
        "ar": "مجلدات تطبيقات مهجورة",
    },
    "leftovers.section.shell": {
        "en": "Right-click menu",
        "ar": "قائمة النقر بالزر الأيمن",
    },
    "leftovers.section.other": {
        "en": "Other",
        "ar": "أخرى",
    },
    "leftovers.section_header": {
        "en": "{title}  ·  {count}",
        "ar": "{title}  ·  {count}",
    },
    "leftovers.summary.singular": {
        "en": "1 item points at software that is no longer installed",
        "ar": "عنصر واحد يشير إلى برنامج لم يعد مثبَّتًا",
    },
    "leftovers.summary.plural": {
        "en": "{count} items point at software that is no longer "
              "installed",
        "ar": "{count} عناصر تشير إلى برامج لم تعد مثبَّتة",
    },
    "leftovers.summary.holding_suffix": {
        "en": ", holding {size}",
        "ar": "، تشغل {size}",
    },
    "leftovers.summary.backup_note": {
        "en": ". Everything you purge is backed up first — Restore "
              "Last Purge puts it back.",
        "ar": ". كل ما تزيله يُنسخ احتياطيًا أولًا — استعادة آخر إزالة "
              "تعيده.",
    },
    "leftovers.summary.needs_admin_suffix": {
        "en": " Removing some of these needs administrator; Pulse "
              "will ask.",
        "ar": " إزالة بعض هذه العناصر يتطلب صلاحيات المسؤول؛ سيطلبها "
              "Pulse.",
    },
    "leftovers.kind.startup_run": {
        "en": "Startup entry",
        "ar": "إدخال بدء تشغيل",
    },
    "leftovers.kind.startup_folder": {
        "en": "Startup shortcut",
        "ar": "اختصار بدء تشغيل",
    },
    "leftovers.kind.task": {
        "en": "Scheduled task",
        "ar": "مهمة مجدولة",
    },
    "leftovers.kind.residue": {
        "en": "App folder",
        "ar": "مجلد تطبيق",
    },
    "leftovers.kind.shell_handler": {
        "en": "Right-click extension",
        "ar": "امتداد نقر بزر أيمن",
    },
    "leftovers.kind.shell_verb": {
        "en": "Right-click entry",
        "ar": "إدخال نقر بزر أيمن",
    },
    "leftovers.size_tooltip": {
        "en": "Disk space this frees once the cleanup's backup folder "
              "is emptied — a purge moves folders aside rather than "
              "deleting them, so it can be undone.",
        "ar": "مساحة القرص التي يحررها هذا بعد إفراغ مجلد النسخ "
              "الاحتياطي الخاص بالتنظيف — الإزالة تنقل المجلدات "
              "جانبًا بدلًا من حذفها، حتى يمكن التراجع عنها.",
    },

    # ============================================================
    #  DATA & STORAGE — DataHygieneDialog (v10.17.3)
    # ============================================================
    # Built fresh on every open, no retranslate() needed. Row label/
    # consequence text lives in i18n_catalog (utils.datastore.CATEGORIES
    # is Pulse's own Python-authored data, looked up the same way
    # BloatRow's Note/StartupRow's Reason already are).
    "data_hygiene.title": {
        "en": "🗂️  Data Pulse keeps on this PC",
        "ar": "🗂️  بيانات يحتفظ بها Pulse على هذا الجهاز",
    },
    "data_hygiene.summary": {
        "en": "{size} in total, across {count} categories. Nothing "
              "here is removed automatically except downloaded "
              "installers.",
        "ar": "{size} إجمالًا، عبر {count} فئات. لا شيء هنا يُزال "
              "تلقائيًا باستثناء المثبِّتات المنزَّلة.",
    },
    "data_hygiene.remove_btn": {
        "en": "Remove",
        "ar": "إزالة",
    },
    "data_hygiene.remove_accessible": {
        "en": "Remove {label}",
        "ar": "إزالة {label}",
    },
    "data_hygiene.row_title": {
        "en": "{label} — {size}",
        "ar": "{label} — {size}",
    },
    "data_hygiene.confirm_title": {
        "en": "Remove {label}?",
        "ar": "إزالة {label}؟",
    },
    "data_hygiene.cannot_undo_suffix": {
        "en": "  This cannot be undone.",
        "ar": "  لا يمكن التراجع عن هذا.",
    },
    "data_hygiene.removed_toast": {
        "en": "Removed {files} item(s) — {size} freed.",
        "ar": "أُزيل {files} عنصر — تحرَّرت {size}.",
    },
    "data_hygiene.nothing_removed_toast": {
        "en": "Nothing was removed from {label} — the files may be "
              "in use.",
        "ar": "لم تتم إزالة شيء من {label} — قد تكون الملفات قيد "
              "الاستخدام.",
    },

    # ============================================================
    #  NOTICE DIALOG (v10.17.3)
    # ============================================================
    # NoticeDialog's title/body are always caller-supplied (there is no
    # content of its own besides Close) — the one caller today is
    # PulseApp's bundled-app restore flow, same as
    # tool_install.not_installed_desc.
    "notice.already_installed_title": {
        "en": "{name} is already installed",
        "ar": "{name} مثبَّت بالفعل",
    },
    "notice.already_installed_body": {
        "en": "{name} is already on this PC, so there is nothing to "
              "restore. Use the removal action in this hub first if "
              "you meant to take it off, or close this and carry on.",
        "ar": "{name} موجود بالفعل على هذا الجهاز، فلا شيء لاستعادته. "
              "استخدم إجراء الإزالة في هذا المركز أولًا إن كنت تقصد "
              "إزالته، أو أغلق هذا وتابع.",
    },

    # ============================================================
    #  REVERT CHOICE DIALOG — the two-way toggle's decision (v10.17.3)
    # ============================================================
    "revert_choice.mixed_status": {
        "en": "This tweak is PARTIALLY applied — some of its values "
              "match, some don't (it may have been changed outside "
              "Pulse).",
        "ar": "هذا التعديل مُطبَّق جزئيًا — بعض قيمه مطابقة وبعضها لا "
              "(قد يكون تغيّر خارج Pulse).",
    },
    "revert_choice.applied_status": {
        "en": "This tweak is currently applied on your system.",
        "ar": "هذا التعديل مُطبَّق حاليًا على نظامك.",
    },
    "revert_choice.body_suffix": {
        "en": "\n\nRe-apply it to enforce Pulse's values again, or "
              "revert it to your original settings (or Windows "
              "defaults if no original was captured).",
        "ar": "\n\nأعد تطبيقه لفرض قيم Pulse مجددًا، أو ارجع إلى "
              "إعداداتك الأصلية (أو افتراضيات ويندوز إن لم تُلتقط "
              "قيم أصلية).",
    },
    "revert_choice.revert_btn": {
        "en": "Revert to Default",
        "ar": "الرجوع إلى الافتراضي",
    },
    "revert_choice.reapply_btn": {
        "en": "Re-apply",
        "ar": "إعادة التطبيق",
    },

    # ============================================================
    #  PLAYBOOK DIALOG (v10.17.3)
    # ============================================================
    # A playbook's own name/description/step titles are USER-AUTHORED
    # content (a .json file dropped into the playbooks folder) — Pulse
    # did not write them and cannot translate them, so only this
    # dialog's OWN chrome is covered here. Malformed-playbook error text
    # (playbooks.py's own parse errors) stays English too, the same
    # "live/dynamic diagnostic" boundary the console log sits on.
    "playbook.title": {
        "en": "📘  Playbooks",
        "ar": "📘  كتيّبات التشغيل",
    },
    "playbook.blurb": {
        "en": "Ordered task sequences that run through the normal "
              "engine. Preview simulates every step with -WhatIf and "
              "changes nothing.",
        "ar": "تسلسلات مهام مرتَّبة تُشغَّل عبر المحرك المعتاد. "
              "المعاينة تحاكي كل خطوة بوضع -WhatIf ولا تغيّر شيئًا.",
    },
    "playbook.empty": {
        "en": "No playbooks found. Drop a .json file into the "
              "'playbooks' folder next to Pulse to add one.",
        "ar": "لم يُعثر على كتيّبات تشغيل. ضع ملف .json في مجلد "
              "'playbooks' بجانب Pulse لإضافة واحد.",
    },
    "playbook.preview_btn": {
        "en": "Preview",
        "ar": "معاينة",
    },
    "playbook.preview_tooltip": {
        "en": "Run every step with -WhatIf: reports what would happen "
              "and changes nothing.",
        "ar": "تشغيل كل خطوة بوضع -WhatIf: يُبلِّغ عمّا سيحدث دون "
              "تغيير أي شيء.",
    },
    "playbook.run_btn": {
        "en": "Run Playbook",
        "ar": "تشغيل الكتيّب",
    },
    "playbook.stop_btn": {
        "en": "Stop",
        "ar": "إيقاف",
    },
    "playbook.admin_note": {
        "en": "  ·  ⚠️ needs Administrator — some steps will be "
              "refused in this session",
        "ar": "  ·  ⚠️ يتطلب صلاحيات المسؤول — سترفض بعض الخطوات في "
              "هذه الجلسة",
    },
    "playbook.steps_count_singular": {
        "en": "1 step",
        "ar": "خطوة واحدة",
    },
    "playbook.steps_count_plural": {
        "en": "{count} steps",
        "ar": "{count} خطوات",
    },
    "playbook.previewing_status": {
        "en": "Previewing {name}…",
        "ar": "جارٍ معاينة {name}…",
    },
    "playbook.running_status": {
        "en": "Running {name}…",
        "ar": "جارٍ تشغيل {name}…",
    },
    "playbook.still_running_warning": {
        "en": "This playbook is still running — press Stop to end it, "
              "or let it finish.",
        "ar": "لا يزال هذا الكتيّب قيد التشغيل — اضغط إيقاف لإنهائه، "
              "أو دعه يكتمل.",
    },
    "playbook.optional_tag": {
        "en": "optional",
        "ar": "اختياري",
    },
    "playbook.needs_admin_desc": {
        "en": "This playbook changes machine-wide settings, so Pulse "
              "needs to run elevated. Preview still works without "
              "elevation.",
        "ar": "يغيّر هذا الكتيّب إعدادات على مستوى الجهاز، لذا يحتاج "
              "Pulse إلى العمل بصلاحيات مرتفعة. المعاينة تعمل دون "
              "صلاحيات مرتفعة.",
    },

    # ============================================================
    #  ACTIVATION STATUS DIALOG (v10.17.3)
    # ============================================================
    # This dialog's OWN chrome only. The report's status/channel labels
    # (product.get("status")/product.get("channel")) are the one
    # backend-authored data point in this pass left untranslated on
    # purpose: 13-Activation.ps1's Get-ActivationStatusDetail interpolates
    # a dynamic day-count into 4 of its 7 explanation sentences, which
    # cannot be matched by i18n_catalog's exact-text lookup the way a
    # fixed sentence (BloatRow's Note, PathConflictDialog's verdicts) can
    # — see i18n_catalog.py's own note if this gets revisited.
    "activation.title": {
        "en": "🔑  Activation Status — Windows & Office",
        "ar": "🔑  حالة التفعيل — ويندوز وOffice",
    },
    "activation.loading": {
        "en": "Reading the licensing service…",
        "ar": "جارٍ قراءة خدمة الترخيص…",
    },
    "activation.docs_btn": {
        "en": "Official Activation Docs",
        "ar": "وثائق التفعيل الرسمية",
    },
    "activation.docs_tooltip": {
        "en": "Opens Microsoft's activation documentation in your browser.",
        "ar": "يفتح وثائق التفعيل من Microsoft في متصفحك.",
    },
    "activation.settings_btn": {
        "en": "Windows Activation Settings",
        "ar": "إعدادات تفعيل ويندوز",
    },
    "activation.settings_tooltip": {
        "en": "Opens Settings › System › Activation, where Windows "
              "licence state is changed.",
        "ar": "يفتح الإعدادات › النظام › التفعيل، حيث تُغيَّر حالة "
              "ترخيص ويندوز.",
    },
    "activation.report_unreadable_fallback": {
        "en": "The licence status could not be read.",
        "ar": "تعذّرت قراءة حالة الترخيص.",
    },
    "activation.failed_prefix": {
        "en": "Could not read activation status: {message}",
        "ar": "تعذّرت قراءة حالة التفعيل: {message}",
    },
    "activation.settings_open_failed": {
        "en": "Windows could not open the Activation settings page. "
              "Open Settings › System › Activation manually.",
        "ar": "تعذّر على ويندوز فتح صفحة إعدادات التفعيل. افتح "
              "الإعدادات › النظام › التفعيل يدويًا.",
    },
    "activation.docs_open_failed": {
        "en": "Could not open your browser. The activation "
              "documentation is at {url}",
        "ar": "تعذّر فتح متصفحك. وثائق التفعيل على {url}",
    },
    "activation.status_line": {
        "en": "{host} · {edition}",
        "ar": "{host} · {edition}",
    },
    "activation.status_line_build_suffix": {
        "en": " (build {build})",
        "ar": " (الإصدار {build})",
    },
    "activation.default_hostname": {
        "en": "this machine",
        "ar": "هذا الجهاز",
    },
    "activation.default_edition": {
        "en": "Unknown edition",
        "ar": "إصدار غير معروف",
    },
    "activation.card_windows": {
        "en": "Windows",
        "ar": "ويندوز",
    },
    "activation.windows_unknown_note": {
        "en": "The licensing service did not report a Windows licence "
              "on this machine. That is normal on some managed or "
              "evaluation images; Settings › System › Activation is "
              "authoritative.",
        "ar": "لم تُبلِّغ خدمة الترخيص عن ترخيص ويندوز على هذا الجهاز. "
              "هذا طبيعي في بعض الصور المُدارة أو التجريبية؛ الإعدادات "
              "› النظام › التفعيل هي المرجع الموثوق.",
    },
    "activation.badge_unknown": {
        "en": "Unknown",
        "ar": "غير معروف",
    },
    "activation.row_channel": {
        "en": "Licence channel",
        "ar": "قناة الترخيص",
    },
    "activation.row_product_key": {
        "en": "Product key",
        "ar": "مفتاح المنتج",
    },
    "activation.product_key_value": {
        "en": "Ends in {partial}",
        "ar": "ينتهي بـ{partial}",
    },
    "activation.row_licence_type": {
        "en": "Licence type",
        "ar": "نوع الترخيص",
    },
    "activation.licence_permanent": {
        "en": "Permanent — does not expire",
        "ar": "دائم — لا ينتهي",
    },
    "activation.licence_leased": {
        "en": "Leased — renews automatically",
        "ar": "مؤجَّر — يتجدد تلقائيًا",
    },
    "activation.row_renews_in": {
        "en": "Renews in",
        "ar": "يتجدد خلال",
    },
    "activation.row_grace_left": {
        "en": "Grace period left",
        "ar": "الفترة المتبقية للسماح",
    },
    "activation.days_value": {
        "en": "{days} day(s)",
        "ar": "{days} يوم/أيام",
    },
    "activation.office_default_name": {
        "en": "Microsoft Office",
        "ar": "Microsoft Office",
    },
    "activation.badge_no_licence": {
        "en": "No licence",
        "ar": "لا ترخيص",
    },
    "activation.row_installation": {
        "en": "Installation",
        "ar": "التثبيت",
    },
    "activation.office_unlicensed_note": {
        "en": "Office is installed but reports no licence. An Office "
              "licence is held against the Microsoft account that "
              "owns the subscription — signing into that account in "
              "any Office app restores it. See the guide below.",
        "ar": "Office مثبَّت لكنه لا يُبلِّغ عن ترخيص. يُحفظ ترخيص "
              "Office مقابل حساب Microsoft المالك للاشتراك — تسجيل "
              "الدخول بذلك الحساب في أي تطبيق Office يستعيده. راجع "
              "الدليل أدناه.",
    },
    "activation.badge_not_installed": {
        "en": "Not installed",
        "ar": "غير مثبَّت",
    },
    "activation.office_not_installed_note": {
        "en": "No Microsoft Office installation was found on this "
              "machine.",
        "ar": "لم يُعثر على تثبيت Microsoft Office على هذا الجهاز.",
    },
    "activation.card_licensing_service": {
        "en": "Licensing service",
        "ar": "خدمة الترخيص",
    },
    "activation.row_kms_host": {
        "en": "KMS host",
        "ar": "مضيف KMS",
    },
    "activation.row_oem_firmware": {
        "en": "OEM firmware licence",
        "ar": "ترخيص البرنامج الثابت من الشركة المصنِّعة",
    },
    "activation.oem_present": {
        "en": "Present",
        "ar": "موجود",
    },
    "activation.oem_present_with_edition": {
        "en": "Present ({edition})",
        "ar": "موجود ({edition})",
    },
    "activation.oem_not_present": {
        "en": "Not present",
        "ar": "غير موجود",
    },

    # ============================================================
    #  POWER HEALTH DIALOG (v10.17.3)
    # ============================================================
    "power_health.title": {
        "en": "🔋  Battery & Power Health",
        "ar": "🔋  صحة البطارية والطاقة",
    },
    "power_health.loading": {
        "en": "Reading battery and power state…",
        "ar": "جارٍ قراءة حالة البطارية والطاقة…",
    },
    "power_health.settings_btn": {
        "en": "Power & Sleep Settings",
        "ar": "إعدادات الطاقة والسكون",
    },
    "power_health.settings_open_failed": {
        "en": "Windows could not open the Power & Sleep page. Open "
              "Settings › System › Power manually.",
        "ar": "تعذّر على ويندوز فتح صفحة الطاقة والسكون. افتح "
              "الإعدادات › النظام › الطاقة يدويًا.",
    },
    "power_health.no_battery_status": {
        "en": "No battery is installed — the power plan section "
              "still applies.",
        "ar": "لا توجد بطارية مثبَّتة — قسم خطة الطاقة ما زال ينطبق.",
    },
    "power_health.card_battery": {
        "en": "Battery",
        "ar": "البطارية",
    },
    "power_health.no_battery_default_note": {
        "en": "No battery detected on this machine.",
        "ar": "لم تُكتشف بطارية على هذا الجهاز.",
    },
    "power_health.badge_unknown": {
        "en": "UNKNOWN",
        "ar": "غير معروف",
    },
    "power_health.unknown_wear_status": {
        "en": "A battery is present, but this firmware does not "
              "report its design capacity, so wear cannot be "
              "calculated.",
        "ar": "توجد بطارية، لكن هذا البرنامج الثابت لا يُبلِّغ عن "
              "سعتها التصميمية، فلا يمكن حساب التآكل.",
    },
    "power_health.badge_health": {
        "en": "{health}% HEALTH",
        "ar": "{health}% صحة",
    },
    "power_health.health_status": {
        "en": "This battery holds {health}% of the capacity it "
              "shipped with ({wear}% wear).",
        "ar": "تحتفظ هذه البطارية بـ{health}% من السعة التي شُحنت "
              "بها (تآكل {wear}%).",
    },
    "power_health.row_design_capacity": {
        "en": "Design capacity",
        "ar": "السعة التصميمية",
    },
    "power_health.capacity_value": {
        "en": "{value} mWh",
        "ar": "{value} mWh",
    },
    "power_health.row_full_capacity": {
        "en": "Full-charge capacity",
        "ar": "سعة الشحن الكامل",
    },
    "power_health.row_cycle_count": {
        "en": "Cycle count",
        "ar": "عدد دورات الشحن",
    },
    "power_health.not_reported_by_firmware": {
        "en": "Not reported by this firmware",
        "ar": "لا يُبلِّغ عنه هذا البرنامج الثابت",
    },
    "power_health.row_current_charge": {
        "en": "Current charge",
        "ar": "الشحن الحالي",
    },
    "power_health.row_power_source": {
        "en": "Power source",
        "ar": "مصدر الطاقة",
    },
    "power_health.ac_adapter": {
        "en": "AC adapter",
        "ar": "مهبط تيار متردد",
    },
    "power_health.power_source_battery": {
        "en": "Battery",
        "ar": "البطارية",
    },
    "power_health.cycle_count_optional_note": {
        "en": "Cycle count is optional in the battery firmware "
              "specification — plenty of otherwise healthy laptops "
              "simply do not publish it.",
        "ar": "عدد دورات الشحن اختياري في مواصفات البرنامج الثابت "
              "للبطارية — كثير من أجهزة الحاسوب المحمولة السليمة لا "
              "تنشره ببساطة.",
    },
    "power_health.card_power_plan": {
        "en": "Power plan",
        "ar": "خطة الطاقة",
    },
    "power_health.row_active_plan": {
        "en": "Active plan",
        "ar": "الخطة النشطة",
    },
    "power_health.row_plans_available": {
        "en": "Plans available",
        "ar": "الخطط المتاحة",
    },
    "power_health.power_plan_not_returned_note": {
        "en": "Windows did not return the power plan list on this "
              "machine.",
        "ar": "لم يُعِد ويندوز قائمة خطط الطاقة على هذا الجهاز.",
    },
    "power_health.row_hibernation": {
        "en": "Hibernation",
        "ar": "الإسبات",
    },

    # ============================================================
    #  STORAGE ANALYZER DIALOG (v10.17.3)
    # ============================================================
    "storage_analyzer.title": {
        "en": "🔭  Storage Analyzer",
        "ar": "🔭  محلِّل التخزين",
    },
    "storage_analyzer.loading": {
        "en": "Scanning… this can take a minute on a large drive.",
        "ar": "جارٍ الفحص… قد يستغرق دقيقة على قرص كبير.",
    },
    "storage_analyzer.scan_folder_btn": {
        "en": "Scan a Folder…",
        "ar": "فحص مجلد…",
    },
    "storage_analyzer.choose_folder_dialog_title": {
        "en": "Choose a folder to analyse",
        "ar": "اختر مجلدًا لتحليله",
    },
    "storage_analyzer.drive_label": {
        "en": "Drive",
        "ar": "القرص",
    },
    "storage_analyzer.reveal_failed": {
        "en": "Could not open Explorer for {path}",
        "ar": "تعذّر فتح مستكشف الملفات لـ{path}",
    },
    "storage_analyzer.reveal_btn": {
        "en": "Reveal",
        "ar": "إظهار",
    },
    "storage_analyzer.reveal_tooltip": {
        "en": "Show {path} in File Explorer",
        "ar": "إظهار {path} في مستكشف الملفات",
    },
    "storage_analyzer.drive_free_of": {
        "en": "{free} free of {total}",
        "ar": "{free} خالية من {total}",
    },
    "storage_analyzer.could_not_read": {
        "en": "Could not read {path} — it does not exist or is not "
              "readable by this account.",
        "ar": "تعذّرت قراءة {path} — غير موجود أو غير قابل للقراءة "
              "بهذا الحساب.",
    },
    "storage_analyzer.accounted_for": {
        "en": "{path} — {total} accounted for.",
        "ar": "{path} — {total} محسوبة.",
    },
    "storage_analyzer.truncated_suffix": {
        "en": " The scan hit its time budget, so this is a partial "
              "view of the largest items found so far.",
        "ar": " بلغ الفحص حد وقته المخصَّص، فهذا عرض جزئي لأكبر "
              "العناصر التي عُثر عليها حتى الآن.",
    },
    "storage_analyzer.partial_scan_title": {
        "en": "Partial scan",
        "ar": "فحص جزئي",
    },
    "storage_analyzer.time_budget_badge": {
        "en": "TIME BUDGET REACHED",
        "ar": "بُلغ حد الوقت",
    },
    "storage_analyzer.partial_note": {
        "en": "Large drives can take longer than the scan's budget "
              "allows. The figures below are real, but smaller items "
              "may be missing — scan a specific folder for an exact "
              "picture.",
        "ar": "قد تستغرق الأقراص الكبيرة أطول مما يسمح به وقت الفحص. "
              "الأرقام أدناه حقيقية، لكن قد تُفقد عناصر أصغر — افحص "
              "مجلدًا محددًا للحصول على صورة دقيقة.",
    },
    "storage_analyzer.largest_folders": {
        "en": "Largest folders",
        "ar": "أكبر المجلدات",
    },
    "storage_analyzer.no_subfolders": {
        "en": "No readable subfolders were found here.",
        "ar": "لم تُوجد مجلدات فرعية قابلة للقراءة هنا.",
    },
    "storage_analyzer.largest_files": {
        "en": "Largest files",
        "ar": "أكبر الملفات",
    },
    "storage_analyzer.no_files": {
        "en": "No readable files were found here.",
        "ar": "لم تُوجد ملفات قابلة للقراءة هنا.",
    },
    "storage_analyzer.about_title": {
        "en": "About this report",
        "ar": "عن هذا التقرير",
    },
    "storage_analyzer.about_note": {
        "en": "Pulse never deletes anything from this screen. Reveal "
              "opens the item in File Explorer, where Windows' own "
              "delete, undo and Recycle Bin apply.",
        "ar": "لا يحذف Pulse أي شيء من هذه الشاشة أبدًا. يفتح الإظهار "
              "العنصر في مستكشف الملفات، حيث تنطبق أدوات ويندوز "
              "الخاصة بالحذف والتراجع وسلة المحذوفات.",
    },
    "dns_switcher.title": {
        "en": "🛰️  DNS & Network Profiles",
        "ar": "🛰️  ملفات DNS والشبكة",
    },
    "dns_switcher.loading": {
        "en": "Reading network adapters…",
        "ar": "جارٍ قراءة مهيّئات الشبكة…",
    },
    "dns_switcher.no_adapters": {
        "en": "No connected network adapters were found.",
        "ar": "لم يُعثر على أي مهيّئ شبكة متصل.",
    },
    "dns_switcher.adapters_title": {
        "en": "Adapters",
        "ar": "المهيّئات",
    },
    "dns_switcher.no_adapters_note": {
        "en": "Pulse lists physical adapters that are currently up. A "
              "machine on Wi-Fi with the adapter disabled, or one behind "
              "a virtual switch only, will show nothing here.",
        "ar": "يسرد Pulse المهيّئات الفعلية العاملة حاليًا. الجهاز الذي "
              "يعمل عبر Wi-Fi مع تعطيل المهيّئ، أو الموجود خلف مبدّل "
              "افتراضي فقط، لن يُظهر شيئًا هنا.",
    },
    "dns_switcher.status": {
        "en": "{count} connected adapter(s). Changes apply to ONE "
              "adapter at a time and can be undone with Automatic (DHCP).",
        "ar": "{count} مهيّئ(ات) متصل(ة). تُطبَّق التغييرات على مهيّئ "
              "واحد في كل مرة ويمكن التراجع عنها باستخدام التلقائي (DHCP).",
    },
    "dns_switcher.status_no_doh": {
        "en": " This build of Windows cannot encrypt DNS (DoH needs "
              "Windows 11), so profiles are applied unencrypted.",
        "ar": " لا يمكن لهذا الإصدار من ويندوز تشفير DNS (يتطلب DoH "
              "ويندوز 11)، لذا تُطبَّق الملفات بلا تشفير.",
    },
    "dns_switcher.admin_required_title": {
        "en": "Administrator required",
        "ar": "يتطلب صلاحيات المسؤول",
    },
    "dns_switcher.not_elevated_badge": {
        "en": "NOT ELEVATED",
        "ar": "غير مرتفع الصلاحية",
    },
    "dns_switcher.admin_required_note": {
        "en": "DNS lives in the adapter's machine-scope settings, so "
              "changing it needs an elevated Pulse. You can still see "
              "what each adapter is using now.",
        "ar": "يقع DNS ضمن إعدادات الجهاز على مستوى النظام، لذا يتطلب "
              "تغييره تشغيل Pulse بصلاحيات مرتفعة. يمكنك مع ذلك رؤية ما "
              "يستخدمه كل مهيّئ حاليًا.",
    },
    "dns_switcher.adapter_label": {
        "en": "Adapter",
        "ar": "المهيّئ",
    },
    "dns_switcher.current_dns_label": {
        "en": "Current DNS",
        "ar": "DNS الحالي",
    },
    "dns_switcher.automatic_router": {
        "en": "Automatic (provided by your router)",
        "ar": "تلقائي (من جهاز التوجيه)",
    },
    "dns_switcher.automatic_badge": {
        "en": "AUTOMATIC",
        "ar": "تلقائي",
    },
    "dns_switcher.custom_badge": {
        "en": "CUSTOM",
        "ar": "مخصّص",
    },
    "dns_switcher.automatic_dhcp": {
        "en": "Automatic (DHCP)",
        "ar": "تلقائي (DHCP)",
    },
    "dns_switcher.already_active_tooltip": {
        "en": "This adapter is already using this profile.",
        "ar": "يستخدم هذا المهيّئ هذا الملف الشخصي بالفعل.",
    },
    "dns_switcher.needs_admin_tooltip": {
        "en": "Changing DNS needs an elevated Pulse.",
        "ar": "يتطلب تغيير DNS تشغيل Pulse بصلاحيات مرتفعة.",
    },
    "dns_switcher.restoring_status": {
        "en": "Restoring automatic DNS on {adapter}…",
        "ar": "جارٍ استرجاع DNS التلقائي على {adapter}…",
    },
    "dns_switcher.applying_status": {
        "en": "Applying {profile} to {adapter}…",
        "ar": "جارٍ تطبيق {profile} على {adapter}…",
    },
    "dns_switcher.updated": {
        "en": "DNS updated.",
        "ar": "تم تحديث DNS.",
    },
    "dns_switcher.change_failed": {
        "en": "Could not change DNS: {message}",
        "ar": "تعذّر تغيير DNS: {message}",
    },
    "context_menu.title": {
        "en": "🧹  Right-Click Menu Entries",
        "ar": "🧹  عناصر قائمة النقر بالزر الأيمن",
    },
    "context_menu.loading": {
        "en": "Reading shell context-menu handlers…",
        "ar": "جارٍ قراءة معالِجات قائمة السياق…",
    },
    "context_menu.restore_all_btn": {
        "en": "Restore All",
        "ar": "استرجاع الكل",
    },
    "context_menu.restore_all_tooltip": {
        "en": "Put every context-menu entry back exactly as it was before "
              "Pulse changed anything.",
        "ar": "إرجاع كل عنصر في قائمة السياق إلى حالته كما كانت قبل أي "
              "تغيير من Pulse.",
    },
    "context_menu.status": {
        "en": "{total} handler(s) registered · {managed} manageable · "
              "{hidden} currently hidden.",
        "ar": "{total} معالِج(ات) مسجَّل(ة) · {managed} قابل(ة) للإدارة · "
              "{hidden} مخفي(ة) حاليًا.",
    },
    "context_menu.needs_admin_suffix": {
        "en": "  Changing entries needs an elevated Pulse.",
        "ar": "  يتطلب تغيير العناصر تشغيل Pulse بصلاحيات مرتفعة.",
    },
    "context_menu.manageable_title": {
        "en": "Manageable entries",
        "ar": "العناصر القابلة للإدارة",
    },
    "context_menu.items_badge": {
        "en": "{count} ITEMS",
        "ar": "{count} عنصر",
    },
    "context_menu.no_managed_note": {
        "en": "None of the handlers on this machine are ones Pulse "
              "manages. That is a good sign, not a failure — it means "
              "nothing recognised as safe-to-hide is installed.",
        "ar": "لا يُدير Pulse أيًّا من المعالِجات الموجودة على هذا الجهاز. "
              "هذه علامة جيدة لا فشل — تعني عدم وجود أي عنصر معروف بأنه "
              "آمن للإخفاء مثبَّت.",
    },
    "context_menu.other_handlers_title": {
        "en": "Other handlers",
        "ar": "معالِجات أخرى",
    },
    "context_menu.other_handlers_note": {
        "en": "Listed so you can see what is in your menu. Pulse does not "
              "offer to change these: a shell extension can be doing real "
              "work — a scanner hook, a sync provider — and blocking one "
              "blind is how a machine breaks in a way nobody connects "
              "back to a context menu.",
        "ar": "مسرودة لتتمكن من رؤية ما في قائمتك. لا يعرض Pulse تغيير "
              "هذه العناصر: قد يقوم امتداد النظام بعمل حقيقي — نقطة "
              "ربط لفاحص، أو مزوّد مزامنة — وحظر أحدها دون معرفة هو ما "
              "يجعل الجهاز يتعطل بطريقة لا يربطها أحد بقائمة السياق.",
    },
    "context_menu.showing_n_of": {
        "en": "Showing 40 of {count}.",
        "ar": "يُعرض 40 من {count}.",
    },
    "context_menu.visible_btn": {
        "en": "Visible",
        "ar": "ظاهر",
    },
    "context_menu.hidden_btn": {
        "en": "Hidden",
        "ar": "مخفي",
    },
    "context_menu.hide_tooltip": {
        "en": "Hide this entry from right-click menus.",
        "ar": "إخفاء هذا العنصر من قوائم النقر بالزر الأيمن.",
    },
    "context_menu.show_tooltip": {
        "en": "Bring this entry back.",
        "ar": "إرجاع هذا العنصر.",
    },
    "context_menu.updating_status": {
        "en": "Updating the context menu…",
        "ar": "جارٍ تحديث قائمة السياق…",
    },
    "context_menu.restoring_status": {
        "en": "Restoring the context menu…",
        "ar": "جارٍ استرجاع قائمة السياق…",
    },
    "context_menu.updated": {
        "en": "Context menu updated.",
        "ar": "تم تحديث قائمة السياق.",
    },
    "context_menu.change_failed": {
        "en": "Could not change the context menu: {message}",
        "ar": "تعذّر تغيير قائمة السياق: {message}",
    },
    "close_confirm.head": {
        "en": "⚠️  A task is still running",
        "ar": "⚠️  لا تزال مهمة قيد التشغيل",
    },
    "close_confirm.body": {
        "en": "<b>{running}</b> hasn't finished yet. Closing Pulse now stops "
              "it partway through — the change it was making may be left "
              "half applied, and you'll need to run it again.",
        "ar": "لم تنتهِ <b>{running}</b> بعد. إغلاق Pulse الآن يوقفها في "
              "منتصف الطريق — قد يبقى التغيير الذي كانت تجريه مطبَّقًا "
              "جزئيًا، وستحتاج إلى تشغيلها مرة أخرى.",
    },
    "close_confirm.default_task": {
        "en": "An operation",
        "ar": "عملية ما",
    },
    "close_confirm.keep_running_btn": {
        "en": "Keep Running",
        "ar": "متابعة التشغيل",
    },
    "close_confirm.stop_close_btn": {
        "en": "Stop && Close",
        "ar": "إيقاف && إغلاق",
    },
    "elevate_prompt.head": {
        "en": "🛡  Administrator required",
        "ar": "🛡  يتطلب صلاحيات المسؤول",
    },
    "elevate_prompt.body": {
        "en": "“{title}” makes system-level changes that need Administrator "
              "rights. Relaunch Pulse elevated to continue — Windows will "
              "show a UAC consent prompt.",
        "ar": "يجري “{title}” تغييرات على مستوى النظام تتطلب صلاحيات "
              "المسؤول. أعد تشغيل Pulse بصلاحيات مرتفعة للمتابعة — "
              "سيعرض ويندوز مطالبة موافقة UAC.",
    },
    "elevate_prompt.default_title": {
        "en": "This action",
        "ar": "هذا الإجراء",
    },
    "elevate_prompt.not_now_btn": {
        "en": "Not now",
        "ar": "ليس الآن",
    },
    "elevate_prompt.relaunch_btn": {
        "en": "Relaunch as Administrator",
        "ar": "إعادة التشغيل كمسؤول",
    },
    "shortcut_sheet.head": {
        "en": "Keyboard shortcuts",
        "ar": "اختصارات لوحة المفاتيح",
    },
    "shortcut_sheet.close_btn": {
        "en": "Close",
        "ar": "إغلاق",
    },
    "self_update.head": {
        "en": "🚀  Pulse v{version} is available",
        "ar": "🚀  الإصدار v{version} من Pulse متاح",
    },
    "self_update.prerelease_tag": {
        "en": "pre-release",
        "ar": "إصدار تجريبي",
    },
    "self_update.no_notes": {
        "en": "No release notes were published.",
        "ar": "لم تُنشر ملاحظات إصدار.",
    },
    "self_update.later_btn": {
        "en": "Later",
        "ar": "لاحقًا",
    },
    "self_update.download_install_btn": {
        "en": "Download && Install",
        "ar": "تنزيل && تثبيت",
    },
    "self_update.view_release_btn": {
        "en": "View Release",
        "ar": "عرض الإصدار",
    },
    "self_update.downloading": {
        "en": "Downloading…",
        "ar": "جارٍ التنزيل…",
    },
    "self_update.downloading_progress": {
        "en": "Downloading… {mb:.1f} / {total_mb:.1f} MB",
        "ar": "جارٍ التنزيل… {mb:.1f} / {total_mb:.1f} MB",
    },
    "self_update.verifying": {
        "en": "Verifying SHA-256…",
        "ar": "جارٍ التحقق من SHA-256…",
    },
    "self_update.cancel_btn": {
        "en": "Cancel",
        "ar": "إلغاء",
    },
    "self_update.verified_msg": {
        "en": "Verified — v{version}'s SHA-256 matches the published "
              "digest. Pulse will close and Setup will take over.",
        "ar": "تم التحقق — يطابق SHA-256 للإصدار v{version} البصمة "
              "المنشورة. سيُغلق Pulse ويتولى المُثبِّت الأمر.",
    },
    "self_update.restart_update_btn": {
        "en": "Restart && Update",
        "ar": "إعادة التشغيل && التحديث",
    },
    "self_update.retry_btn": {
        "en": "Retry",
        "ar": "إعادة المحاولة",
    },
    "self_update.install_failed": {
        "en": "The update could not be installed.",
        "ar": "تعذّر تثبيت التحديث.",
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
