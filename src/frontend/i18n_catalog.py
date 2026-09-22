"""
src/frontend/i18n_catalog.py

ARABIC FOR THE TASK CATALOG (v16) — menu_structure.py's category titles/
taglines, band/group headers and every card's title+description, plus
SOFTWARE_CATALOG's tool names+blurbs. Kept apart from i18n.py's STRINGS
on size alone: this table is an order of magnitude larger, and mixing
"UI chrome, looked up by a stable key" with "catalog copy, looked up by
its own English text" into one file would make both harder to audit.

LOOKUP IS BY ENGLISH TEXT, NOT A KEY, because the catalog itself is the
one source of truth for what a card IS — menu_structure.py's `task`
field is what the engine dispatches on and what prefs/history key
against, and duplicating that as a second, i18n-only identifier per
card would be one more place for the two to quietly drift. The English
string a card already carries is unique enough in practice (nothing
in this catalog repeats a title or a full sentence-length description),
and a translation that goes stale because the English text changed
degrades to showing that English text — the same "never crash, never
block on a missing entry" contract i18n.py's own tr() holds.

SOFTWARE_CATALOG IS COVERED — pillar title/blurb, every group name, and
every tool's `WhyYouNeedIt` line, all wired through SoftwareCatalogDialog
below. The tool's own DisplayName ("Google Chrome", "Docker Desktop") is
deliberately absent from TITLES: brand/product names pass through
unchanged, matching how Arabic Windows itself keeps trademarked names in
Latin script. Technical terms inside a `why` translation (file names,
API/library names, version numbers) are likewise kept in Latin script —
translating "MSVCR100.dll" or "DirectX 12" would make the sentence LESS
precise, not more accessible.

TWO BACKEND-AUTHORED DATA TABLES ARE COVERED TOO (v16.1), on the same
"this is Pulse's own copy, not a live system's" reasoning as
`WhyYouNeedIt` above: BloatwarePurgeDialog's BloatRow reads its `Note`
field from src/backend/modules/01-Catalogs.ps1's $Script:BloatCatalog
(48 entries), and StartupManagerDialog's StartupRow reads its `Reason`
field from src/backend/modules/05-Startup.ps1's rule tables (43
entries) — both looked up here by the same English text the PowerShell
literal carries, so a backend edit that changes the wording degrades to
showing that new English text rather than silently going stale. Every
package/app/program NAME in both dialogs (BloatRow's catalog Name,
StartupRow's DisplayName) stays English, same convention as a tool's
DisplayName.

OFFICEWIZARDDIALOG'S THREE CHOICE-PAGE CARDS ARE COVERED TOO (v10.17.1),
in TITLES/DESCRIPTIONS rather than i18n.py's key-based STRINGS — they
are GlassCards like any other, and GlassCard only knows how to
translate through this lookup-by-English-text mechanism, even though
they are wizard-authored copy rather than a menu_structure.py catalog
entry. The rest of OfficeWizardDialog's own chrome, and all of
ToolInstallWizardDialog, live in i18n.py's STRINGS instead (they are
QLabels/QPushButtons this module has no reason to touch).

HUBDIALOG'S OWN SUB-ACTION ROWS ARE COVERED TOO (v10.17.2): a hub
CARD's title/desc already lived here (a hub is a GlassCard like any
other), but the DIALOG it opens read every ActionRow's item['title']/
item['desc'] as raw English until this pass — the exact inconsistency
this closes, across all five shipped hubs (PATH Doctor, Leftovers
Cleaner, Microsoft Edge, Microsoft OneDrive, Network & Connectivity).
PathConflictDialog's verdict buttons ("Use this one", "In use",
"Needs administrator", …) and LeftoverRow's own "reason" line join the
backend-authored-data-table precedent above, on the same reasoning —
see widgets.py's own notes on each for exactly which backend module and
field they were read off.

TWO MORE FINITE STRING SETS JOIN THE SAME LOOKUP (v10.17.3):
utils.updater.can_apply()'s one non-empty refusal reason (SelfUpdate-
Dialog's notes page, shown when the running build cannot hand off to an
installer) and PulseApp.SHORTCUTS' nine row descriptions (Shortcut-
SheetDialog) — the app's own fixed, non-interpolated copy, not a
catalog entry, but the exact-text lookup fits it exactly the same way.

TWO NEW BANDS, NINE NEW CARDS (v1.1): "START MENU" and "FILE EXPLORER"
(menu_structure.py, System & Tweaks) — ordinary catalog cards, covered
the same way every other card in this file is. Their `note` field
("Windows 11 only" etc.) is NOT covered: GlassCard renders that field
raw (widgets.py never routes it through this module), the same
pre-existing gap every other note-bearing card already has — fixing
that is a shared-component change out of scope for adding two bands.

WHAT THIS DOES NOT COVER, on purpose (see i18n.py's own scope note and
ROADMAP.md): dialogs opened FROM a card that are not one of the ones
covered above — the Restore Point Browser and the Health Report — stay
English in this pass.

ONE NEW BAND, FIVE NEW CARDS (v1.2): "TASKBAR" (menu_structure.py,
System & Tweaks, right after INTERFACE) — the granular taskbar toggles
(compact search, End Task, Copilot, Task View, transparency), covered
the same way as the v1.1 bands above, including the same `note`-field
gap for the two OS-version-gated cards.
"""
from __future__ import annotations

#: English title (a card's "title", a category's "title", or a
#: menu_structure.py group's "title") -> Arabic.
TITLES: dict[str, str] = {
    # -- the four categories --------------------------------------------
    "Software Management": "إدارة البرامج",
    "System & Tweaks": "النظام والتعديلات",
    "Maintenance & Security": "الصيانة والأمان",
    "Utilities & Tools": "الأدوات والمرافق",

    # -- the fifteen band/group headers (menu_structure.py "groups") ----
    "INSTALL": "تثبيت",
    "MANAGE INSTALLED": "إدارة المثبت",
    "PREINSTALLED & BUNDLED": "مثبت مسبقًا ومرفق",
    "PERFORMANCE & POWER": "الأداء والطاقة",
    "NETWORK": "الشبكة",
    "INTERFACE": "الواجهة",
    # v1.2 — granular taskbar toggles.
    "TASKBAR": "شريط المهام",
    # v1.1 — Start Menu customization / File Explorer behavior.
    "START MENU": "قائمة ابدأ",
    "FILE EXPLORER": "مستكشف الملفات",
    "PRIVACY": "الخصوصية",
    "ROUTINE UPKEEP": "الصيانة الدورية",
    "DISK & SPACE": "القرص والمساحة",
    "RECOVERY & ROLLBACK": "الاسترداد والتراجع",
    "REPORTS & INSPECTION": "التقارير والفحص",
    "NETWORK & CONNECTIVITY": "الشبكة والاتصال",
    "AUTOMATION & LOGS": "الأتمتة والسجلات",

    # -- every remaining card/hub title across the four categories ------
    # Pure product/brand names (Microsoft Edge, Microsoft OneDrive) are
    # deliberately absent: they pass through unchanged, matching how
    # Arabic Windows itself keeps trademarked product names in Latin
    # script rather than transliterating them.
    "Activation Status": "حالة التفعيل",
    "Aggressive Cache Clean": "تنظيف شامل للذاكرة المؤقتة",
    "Battery & Power Health": "صحة البطارية والطاقة",
    "Check for Updates": "التحقق من التحديثات",
    "Classic Context Menu": "قائمة السياق الكلاسيكية",
    "Create Restore Point": "إنشاء نقطة استعادة",
    "DNS & Network Profiles": "DNS وملفات تعريف الشبكة",
    "Data & Storage": "البيانات والتخزين",
    "Developer, AI & Engineering": "التطوير والذكاء الاصطناعي والهندسة",
    "Disable Activity History": "تعطيل سجل النشاط",
    "Disable Advertising ID": "تعطيل معرّف الإعلانات",
    "Disable Hibernation": "تعطيل الإسبات",
    "Disable Mouse Acceleration": "تعطيل تسريع الفأرة",
    "Disable Telemetry": "تعطيل القياس عن بُعد",
    "Drive Space Report": "تقرير مساحة الأقراص",
    "Driver Backup": "نسخ احتياطي لبرامج التشغيل",
    "Edge Backup Folder": "مجلد النسخ الاحتياطي لـEdge",
    "Enable Hibernation": "تفعيل الإسبات",
    "Essential Daily Software": "البرامج الأساسية اليومية",
    "Ethernet & Wi-Fi Driver Check": "فحص برامج تشغيل الإيثرنت والواي فاي",
    "Fix Shadowed Tools": "إصلاح تعارض الأدوات",
    "Game Mode & Game Bar": "وضع الألعاب وشريط الألعاب",
    "Global Dark Mode": "الوضع الداكن الشامل",
    "Health & Drift Report": "تقرير الحالة والانحراف",
    "Install / Restore OneDrive": "تثبيت / استعادة OneDrive",
    "Leftovers Backup Folder": "مجلد النسخ الاحتياطي للمخلّفات",
    "Leftovers Cleaner": "منظّف المخلّفات",
    "Microsoft Office Suite": "حزمة Microsoft Office",
    "Minimalist Taskbar": "شريط مهام بسيط",
    "Missing Driver Scan": "فحص برامج التشغيل المفقودة",
    "Network & Connectivity": "الشبكة والاتصال",
    "Network & Ping Optimizer": "محسِّن الشبكة والبينغ",
    "Network Adapter Diagnostics": "تشخيص محوّلات الشبكة",
    "OneDrive Backup Folder": "مجلد النسخ الاحتياطي لـOneDrive",
    "Optimize All Drives": "تحسين جميع الأقراص",
    "PATH Doctor": "طبيب PATH",
    "Playbooks": "كتيّبات التشغيل",
    "Prune Dead & Duplicate Entries": "تقليم الإدخالات الميتة والمكرَّرة",
    "Purge OneDrive": "إزالة OneDrive نهائيًا",
    "Reinstall Microsoft Edge": "إعادة تثبيت Microsoft Edge",
    "Remove Bloatware": "إزالة البرامج غير المرغوبة",
    "Remove Microsoft Edge": "إزالة Microsoft Edge",
    "Remove Windows.old": "إزالة مجلد Windows.old",
    "Reset All Tweaks": "إعادة ضبط كل التعديلات",
    "Reset Network Stack": "إعادة ضبط مكدّس الشبكة",
    "Restore Last Purge": "استرجاع آخر عملية حذف",
    "Restore Point Browser": "متصفّح نقاط الاستعادة",
    "Restore Services": "استعادة الخدمات",
    "Right-Click Menu Entries": "عناصر قائمة النقر بالزر الأيمن",
    "Runtimes & Hardware Drivers": "بيئات التشغيل وبرامج تشغيل العتاد",

    # -- v1.1 Start Menu customization / File Explorer behavior ---------
    "Remove Start Recommendations": "إزالة توصيات قائمة ابدأ",
    "Disable Start Web Search": "تعطيل بحث الويب في قائمة ابدأ",
    "Disable Recent-Item Tracking": "تعطيل تتبع العناصر الأخيرة",
    "Disable Start Suggestions": "تعطيل اقتراحات قائمة ابدأ",
    "Launch to This PC": "الانتقال إلى هذا الجهاز",
    "Always Show File Extensions": "إظهار امتدادات الملفات دائمًا",
    "Show Hidden Files": "إظهار الملفات المخفية",
    "Show Protected System Files": "إظهار ملفات النظام المحمية",
    "Remove Explorer Recommendations": "إزالة توصيات مستكشف الملفات",

    # -- v1.2 granular taskbar toggles ------------------------------------
    "Compact Search Box": "مربع بحث مضغوط",
    "Enable Taskbar End Task": "تفعيل ‘إنهاء المهمة’ في شريط المهام",
    "Hide Copilot Button": "إخفاء زر Copilot",
    "Hide Task View Button": "إخفاء زر عرض المهام",
    "Disable Transparency Effects": "تعطيل تأثيرات الشفافية",

    "Scan & Purge Leftovers": "فحص المخلّفات وإزالتها",
    "Scan PATH & Environment": "فحص PATH ومتغيرات البيئة",
    "Startup Manager": "مدير بدء التشغيل",
    "Storage Analyzer": "محلِّل التخزين",
    "System Info Snapshot": "لقطة معلومات النظام",
    "System Repair (SFC + DISM)": "إصلاح النظام (SFC + DISM)",
    "Ultimate Power Plan": "خطة الطاقة القصوى",
    "View Operation Log": "عرض سجل العمليات",

    # -- SOFTWARE_CATALOG's own group names (with their emoji prefix,
    # exact string match required — see SoftwareCatalogDialog) -----------
    "🌐 Browsers & Communication": "🌐 المتصفحات والتواصل",
    "🎬 Media & Productivity": "🎬 الوسائط والإنتاجية",
    "🧰 Utilities & Virtualization": "🧰 الأدوات والمحاكاة الافتراضية",
    "🎮 Gaming Launchers": "🎮 مشغّلات الألعاب",
    "🧩 Languages & Compilers": "🧩 اللغات والمترجمات",
    "🛠️ IDEs & Code Editors": "🛠️ بيئات التطوير ومحررات الأكواد",
    "🧠 AI, Containers & APIs": "🧠 الذكاء الاصطناعي والحاويات وواجهات API",
    "⚙️ Core Runtimes & Dependencies": "⚙️ بيئات التشغيل الأساسية والتبعيات",
    "🎛️ Hardware & GPU Management": "🎛️ إدارة العتاد وكرت الرسومات",
    "🔬 Hardware Diagnostics": "🔬 تشخيص العتاد",

    # -- SOFTWARE_CATALOG's one bulk-action label (runtimes pillar) ------
    "Install All Essential Dependencies": "تثبيت كل التبعيات الأساسية",

    # -- OfficeWizardDialog's own choice-page cards (v10.17.1) — these
    # three GlassCards are wizard-authored, not menu_structure.py catalog
    # items, but GlassCard only knows how to translate through this
    # lookup-by-English-text table, so they live here rather than in
    # i18n.py's key-based STRINGS. "Automated Cloud Download" doubles as
    # OfficeWizardDialog._SUBTITLES["auto_confirm"] (an i18n.py key) —
    # same visible string, two lookup systems, same duplication the
    # sidebar module labels/category titles already carry.
    "Automated Cloud Download": "تنزيل سحابي تلقائي",
    "I already have my Office folder ready": "لدي مجلد Office جاهز بالفعل",
    "Step-by-Step Beginner Guide": "دليل تفصيلي للمبتدئين",

    # -- HubDialog's own sub-action rows (v10.17.2) — the hub CARD's own
    # title/desc (e.g. "PATH Doctor", "Microsoft Edge") already lived here
    # from the v16 card pass; only the rows INSIDE the dialog those cards
    # open were still missing, since HubDialog never routed item['title']/
    # item['desc'] through this lookup at all. Every item below is one of
    # ActionRow's rows, never a card of its own. Product names inside a
    # sentence (Chromium Edge, OneDrive, Winsock, TCP/IP, Intel/Realtek)
    # stay in Latin script, same convention as everywhere else.
    "Scan PATH & Environment": "فحص PATH والبيئة",
    "Fix Shadowed Tools": "إصلاح الأدوات المتراكبة",
    "Prune Dead & Duplicate Entries": "تقليم الإدخالات الميتة والمكرَّرة",
    "Scan & Purge Leftovers": "فحص وإزالة المخلّفات",
    "Restore Last Purge": "استعادة آخر إزالة",
    "Leftovers Backup Folder": "مجلد نسخ المخلّفات الاحتياطية",
    "Remove Microsoft Edge": "إزالة Microsoft Edge",
    "Reinstall Microsoft Edge": "إعادة تثبيت Microsoft Edge",
    "Edge Backup Folder": "مجلد نسخ Edge الاحتياطية",
    "Purge OneDrive": "إزالة OneDrive",
    "Install / Restore OneDrive": "تثبيت / استعادة OneDrive",
    "OneDrive Backup Folder": "مجلد نسخ OneDrive الاحتياطية",
    "Network Adapter Diagnostics": "تشخيص محوّل الشبكة",
    "Ethernet & Wi-Fi Driver Check": "فحص برامج تشغيل الإيثرنت والواي فاي",
    "Reset Network Stack": "إعادة ضبط مكدّس الشبكة",

    # -- PathConflictDialog's own verdict buttons (v10.17.2) — Pulse's
    # own copy, computed by src/backend/modules/03-Environment.ps1's
    # Get-PathPriorityPlan/Get-PathInstallPlan (the exhaustive list of
    # every `Short` value either function returns), on the same "this is
    # Pulse's own deterministic string, not live system output"
    # reasoning that already covers BloatRow's Note and StartupRow's
    # Reason fields.
    "Use this one": "استخدام هذه",
    "In use": "قيد الاستخدام",
    "Needs administrator": "يتطلب صلاحيات المسؤول",
    "Nothing to reorder": "لا شيء لإعادة ترتيبه",
    "Not on this PATH": "غير موجود في PATH هذا",
    "Split across scopes": "مقسَّم بين النطاقين",
    "Re-scan needed": "يلزم إعادة الفحص",

    # -- DataHygieneDialog's own rows (v10.17.3) — utils.datastore.
    # CATEGORIES' own label/consequence pairs, Pulse's own Python-authored
    # copy (not PowerShell this time, but the same "this is Pulse's own
    # copy, not live system output" reasoning).
    "Operation logs": "سجلات العمليات",
    "Downloaded installers": "المثبِّتات المنزَّلة",
    "Edge backup": "نسخة Edge الاحتياطية",
    "Rescued OneDrive files": "ملفات OneDrive المنقذة",
    "Startup item backups": "نسخ عناصر بدء التشغيل الاحتياطية",
    "Driver backups": "نسخ برامج التشغيل الاحتياطية",
}

#: English tagline/desc (a card's "desc", a category's "tagline") ->
#: Arabic.
DESCRIPTIONS: dict[str, str] = {
    # -- the four categories --------------------------------------------
    "Install, update and remove software": "تثبيت البرامج وتحديثها وإزالتها",
    "Performance, network, interface and privacy": "الأداء والشبكة والواجهة والخصوصية",
    "Routines, disk space, drivers and rollback": "الصيانة الدورية ومساحة القرص وبرامج التشغيل والتراجع",
    "Reports, licence state and playbooks": "التقارير وحالة الترخيص وكتيبات التشغيل",

    # -- WelcomePage.ACTION_BLURBS: dashboard-only quick-action one-liners,
    # distinct English text from the same task's category-page desc --------
    "Scan installed apps and update your picks.": "فحص التطبيقات المثبتة وتحديث اختياراتك.",
    "Desktop PCs only — not for laptops/mobile.": "لأجهزة سطح المكتب فقط — غير مخصص للحواسيب المحمولة/الجوال.",
    "Wipe temp, Update and system caches.": "مسح الملفات المؤقتة وذاكرة التحديث والنظام المخبأة.",
    "Stop diagnostic data collection.": "إيقاف جمع بيانات التشخيص.",
    "Hardware, uptime and disk snapshot.": "لمحة عن العتاد ومدة التشغيل والقرص.",
    "A safety checkpoint before big changes.": "نقطة أمان قبل إجراء تغييرات كبيرة.",

    # -- every remaining card description across the four categories ----
    "Back up local files, then uninstall OneDrive.":
        "نسخ الملفات المحلية احتياطيًا، ثم إلغاء تثبيت OneDrive.",
    "Battery wear, cycle count and the active power plan — read-only.":
        "تآكل البطارية وعدد دورات الشحن وخطة الطاقة الحالية — للعرض فقط.",
    "Boot-impact audit with instant enable/disable toggles.":
        "تدقيق أثر برامج بدء التشغيل مع مفاتيح تفعيل/تعطيل فورية.",
    "Bring hibernation (and hiberfil.sys) back.":
        "إعادة تفعيل الإسبات (وملف hiberfil.sys).",
    "Browsers, chat, media, utilities and game launchers — what a fresh "
    "machine needs to be usable.":
        "متصفحات ومحادثات ووسائط وأدوات ومشغّلات ألعاب — كل ما يحتاجه "
        "جهاز جديد ليصبح جاهزًا للاستخدام.",
    "Check Windows Update for drivers you're missing.":
        "التحقق من Windows Update بحثًا عن برامج التشغيل الناقصة.",
    "Dead folders, duplicates, malformed entries and shadowed "
    "toolchains — reported, nothing changed.":
        "مجلدات ميتة وإدخالات مكرَّرة وتالفة وأدوات متعارضة — تُعرض "
        "فقط، دون أي تغيير.",
    "Delete hiberfil.sys and free disk space.":
        "حذف ملف hiberfil.sys وتحرير مساحة القرص.",
    "Diagnose adapters, check Ethernet and Wi-Fi drivers, or rebuild "
    "the network stack when nothing else works.":
        "تشخيص المحوّلات، وفحص برامج تشغيل الإيثرنت والواي فاي، أو "
        "إعادة بناء مكدّس الشبكة عندما لا يُجدي شيء آخر.",
    "Enable Game Mode, kill background recording.":
        "تفعيل وضع الألعاب، وإيقاف التسجيل في الخلفية.",
    "Every System Restore checkpoint on this PC — verify your safety "
    "net, read-only.":
        "كل نقطة استعادة للنظام على هذا الجهاز — تحقّق من شبكة الأمان "
        "الخاصة بك، للعرض فقط.",
    "Export every current hardware driver to your Desktop.":
        "تصدير كل برامج تشغيل العتاد الحالية إلى سطح المكتب.",
    "Find what Windows cannot run by name — and clean the dead and "
    "duplicate entries out of your PATH.":
        "معرفة ما لا يستطيع ويندوز تشغيله بالاسم — وتنظيف الإدخالات "
        "الميتة والمكرَّرة من PATH.",
    "Find what is actually filling a drive — largest folders and "
    "files, read-only.":
        "معرفة ما يملأ القرص فعليًا — أكبر المجلدات والملفات، للعرض فقط.",
    "Find what uninstalled software left behind — dead startup "
    "entries, ghost scheduled tasks, abandoned app folders — and "
    "remove it safely.":
        "معرفة ما خلّفته البرامج التي أُزيلت — إدخالات بدء تشغيل "
        "ميتة، ومهام مجدولة شبحية، ومجلدات تطبيقات مهجورة — وإزالتها "
        "بأمان.",
    "Flags only what points at files that are provably gone. "
    "Everything removed is backed up first, behind a restore point.":
        "لا يُعلَّم إلا ما يشير إلى ملفات ثبت زوالها فعليًا. كل ما "
        "تتم إزالته يُنسخ احتياطيًا أولًا، خلف نقطة استعادة.",
    "Flush DNS and reset Winsock for lower latency.":
        "تفريغ ذاكرة DNS المؤقتة وإعادة ضبط Winsock لخفض زمن الاستجابة.",
    "Force the dark theme across Windows and all apps.":
        "فرض المظهر الداكن على ويندوز وكل التطبيقات.",
    "Force-purge Chromium Edge, with a backup kept.":
        "إزالة Chromium Edge إزالة قسرية، مع الاحتفاظ بنسخة احتياطية.",
    "Free / used space snapshot for every fixed drive.":
        "لقطة للمساحة الحرة/المستخدمة لكل قرص ثابت.",
    "Hardware, uptime and drive space — written to the log.":
        "العتاد ومدة التشغيل ومساحة الأقراص — تُكتب في السجل.",
    "How old each network driver is, and the official Intel / Realtek "
    "page to get a newer one.":
        "عمر كل برنامج تشغيل شبكة، وصفحة Intel / Realtek الرسمية "
        "للحصول على إصدار أحدث.",
    "Languages, compilers, IDEs and the local AI stack — everything "
    "needed to build software here.":
        "لغات ومترجمات وبيئات تطوير متكاملة وحزمة الذكاء الاصطناعي "
        "المحلية — كل ما يلزم لبناء البرامج هنا.",
    "Left-aligned, widget-free, chat-free taskbar.":
        "شريط مهام محاذًى لليسار، بلا ودجات وبلا محادثة.",
    "Link state, speed, addresses, gateway and driver for every "
    "adapter — read-only.":
        "حالة الاتصال والسرعة والعناوين والبوابة وبرنامج التشغيل لكل "
        "محوّل — للعرض فقط.",
    "Live scan of installed apps — update exactly what you pick.":
        "فحص مباشر للتطبيقات المثبَّتة — حدِّث ما تختاره بالضبط.",
    "Manual System Restore checkpoint — your safety net before big "
    "changes.":
        "نقطة استعادة يدوية للنظام — شبكة أمانك قبل إجراء تغييرات كبيرة.",
    "Open files rescued before OneDrive removal.":
        "فتح الملفات التي أُنقذت قبل إزالة OneDrive.",
    "Open the full Pulse operation log.":
        "فتح سجل عمليات Pulse كاملًا.",
    "Open the registry exports, task definitions and folders a purge "
    "set aside.":
        "فتح تصديرات السجل وتعريفات المهام والمجلدات التي نحّتها "
        "عملية حذف جانبًا.",
    "Open the settings and profile data saved before removal.":
        "فتح الإعدادات وبيانات الملف الشخصي المحفوظة قبل الإزالة.",
    "Purge Chromium Edge from Windows — or put it back. A backup is "
    "kept either way, so the removal is reversible.":
        "إزالة Chromium Edge من ويندوز — أو إعادته. يُحتفظ بنسخة "
        "احتياطية في كل الحالات، فالإزالة قابلة للتراجع.",
    "Put back everything the most recent purge removed.":
        "إعادة كل ما أزالته آخر عملية حذف.",
    "Raw pointer precision — no speed curves or thresholds.":
        "دقة مؤشر خام — بلا منحنيات سرعة أو عتبات.",
    "Re-enable Windows services disabled by the optimizer.":
        "إعادة تفعيل خدمات ويندوز التي عطّلها المحسِّن.",
    "Rebuild Winsock and TCP/IP, then renew the lease. Requires a "
    "restart to finish.":
        "إعادة بناء Winsock وTCP/IP، ثم تجديد عقد الإيجار. يتطلب "
        "إعادة التشغيل للإكمال.",
    "Reclaim gigabytes from a previous Windows install.":
        "استعادة غيغابايتات من تثبيت ويندوز سابق.",
    "Reinstall Edge and restore your backed-up settings.":
        "إعادة تثبيت Edge واستعادة إعداداتك المحفوظة.",
    "Reinstall OneDrive so it's back and syncing.":
        "إعادة تثبيت OneDrive ليعود ويستأنف المزامنة.",
    "Remove the per-user identifier that ad networks track.":
        "إزالة المعرِّف الخاص بكل مستخدم الذي تتعقّبه شبكات الإعلانات.",
    "Removes only what is provably safe: duplicates, unparseable "
    "entries, and folders missing from a mounted internal disk. A "
    "restore point and a copy of your current PATH are saved first.":
        "لا يُزيل إلا ما ثبتت سلامته: الإدخالات المكرَّرة، وغير "
        "القابلة للتحليل، والمجلدات المفقودة من قرص داخلي متصل. "
        "تُحفظ نقطة استعادة ونسخة من PATH الحالي أولًا.",
    "Repair protected system files and the component store.":
        "إصلاح ملفات النظام المحمية ومخزن المكوّنات.",
    "Restore the full Windows 10 right-click menu.":
        "استعادة قائمة النقر بالزر الأيمن الكاملة من ويندوز 10.",
    "Revert every registry tweak to your backed-up values.":
        "التراجع عن كل تعديل في السجل إلى قيمك المحفوظة احتياطيًا.",
    "Run a saved sequence of tasks — preview it first with a dry run.":
        "تشغيل سلسلة محفوظة من المهام — عايِنها أولًا بتشغيل تجريبي.",
    "Scan for pre-installed stubs, promo apps and redundant Microsoft "
    "apps — then purge the ones you pick, permanently.":
        "فحص التطبيقات التجريبية المثبَّتة مسبقًا والترويجية وتطبيقات "
        "Microsoft الزائدة — ثم إزالة ما تختاره نهائيًا.",
    "See every right-click entry and hide the ones you don't use — "
    "fully reversible.":
        "عرض كل عنصر في قائمة النقر بالزر الأيمن وإخفاء ما لا "
        "تستخدمه — قابل للتراجع بالكامل.",

    # -- v1.1 Start Menu customization / File Explorer behavior ---------
    "Hide the Recommended section (recent files, suggested apps) from "
    "the Start Menu.":
        "إخفاء قسم التوصيات (الملفات الأخيرة والتطبيقات المقترحة) "
        "من قائمة ابدأ.",
    "Keep Start Menu search local-only — no Bing web results mixed in.":
        "إبقاء بحث قائمة ابدأ محليًا فقط — دون مزج نتائج بحث Bing.",
    "Stop Windows tracking recently opened items in Start, Jump Lists "
    "and File Explorer.":
        "إيقاف تتبّع ويندوز للعناصر المفتوحة مؤخرًا في قائمة ابدأ "
        "وقوائم القفز ومستكشف الملفات.",
    "Stop new promotional tiles and suggested-app pins from being "
    "added to Start.":
        "إيقاف إضافة مربعات ترويجية جديدة وتثبيتات تطبيقات مقترحة "
        "إلى قائمة ابدأ.",
    "Open File Explorer to This PC instead of Home / Quick access.":
        "فتح مستكشف الملفات على هذا الجهاز بدلًا من الرئيسية / "
        "الوصول السريع.",
    "Stop Windows from hiding extensions for known file types.":
        "إيقاف إخفاء ويندوز لامتدادات أنواع الملفات المعروفة.",
    "Show hidden files, folders and drives in File Explorer.":
        "إظهار الملفات والمجلدات ومحركات الأقراص المخفية في "
        "مستكشف الملفات.",
    "Show protected operating system files Windows hides by default. "
    "Pulse only reveals them here — it never touches them.":
        "إظهار ملفات نظام التشغيل المحمية التي يخفيها ويندوز "
        "افتراضيًا. يكتفي Pulse بإظهارها هنا — ولا يمسّها أبدًا.",
    "Hide the Recommended section from File Explorer's Home view.":
        "إخفاء قسم التوصيات من الصفحة الرئيسية لمستكشف الملفات.",

    # -- v1.2 granular taskbar toggles ------------------------------------
    "Show the taskbar search as a compact icon instead of the full search box.":
        "عرض بحث شريط المهام كأيقونة مضغوطة بدلًا من مربع البحث الكامل.",
    "Add 'End Task' to the right-click menu on taskbar app icons.":
        "إضافة ‘إنهاء المهمة’ إلى قائمة النقر بالزر الأيمن على "
        "أيقونات شريط المهام.",
    "Hide the Copilot button from the taskbar, on builds that show one.":
        "إخفاء زر Copilot من شريط المهام، في الإصدارات التي تعرضه.",
    "Hide the Task View button from the taskbar.":
        "إخفاء زر عرض المهام من شريط المهام.",
    "Turn off Windows' transparency/blur effects on the taskbar, Start "
    "menu and Action Center for a solid look.":
        "إيقاف تأثيرات الشفافية والتمويه في شريط المهام وقائمة ابدأ "
        "ومركز الإجراءات للحصول على مظهر صلب.",

    "See what Pulse keeps on this PC — logs, backups and rescued "
    "files — and remove any of it.":
        "عرض ما يحتفظ به Pulse على هذا الجهاز — سجلات ونسخ احتياطية "
        "وملفات منقذة — وإزالة أي منها.",
    "Snapshot applied tweaks, drives and startup load; export HTML "
    "or JSON.":
        "لقطة للتعديلات المطبَّقة والأقراص وحمل بدء التشغيل؛ تصدير "
        "بصيغة HTML أو JSON.",
    "Stop Timeline activity sync to Microsoft servers.":
        "إيقاف مزامنة سجل الأنشطة (Timeline) مع خوادم Microsoft.",
    "Stop diagnostic data collection and scheduled tasks.":
        "إيقاف جمع بيانات التشخيص والمهام المجدولة.",
    "Switch a connection to Cloudflare, Quad9 or AdGuard — with a "
    "one-click way back.":
        "تبديل اتصال إلى Cloudflare أو Quad9 أو AdGuard — مع طريقة "
        "عودة بنقرة واحدة.",
    "TRIM SSDs and defragment HDDs — drive by drive.":
        "تنفيذ TRIM لأقراص SSD وإلغاء تجزئة أقراص HDD — قرصًا قرصًا.",
    "Two Pythons, two Nodes, two Javas — see which copy your terminal "
    "actually runs, and promote the one you want. Reorders your "
    "PATH; removes nothing.":
        "نسختا Python، ونسختا Node، ونسختا Java — اعرف أي نسخة "
        "يشغّلها الطرفية فعليًا، ورقِّ النسخة التي تريدها. يعيد ترتيب "
        "PATH؛ لا يزيل شيئًا.",
    "Uninstall OneDrive with your local files rescued first — or "
    "reinstall it and pick syncing back up.":
        "إلغاء تثبيت OneDrive بعد إنقاذ ملفاتك المحلية أولًا — أو "
        "إعادة تثبيته واستئناف المزامنة.",
    "Unlock the hidden high-performance scheme. Designed strictly "
    "for Desktop PCs. Not recommended for laptops/mobile devices — "
    "also disables display and sleep timeouts while on AC power.":
        "إطلاق مخطط الأداء العالي المخفي. مصمَّم حصرًا لأجهزة سطح "
        "المكتب. غير موصى به لأجهزة الحاسوب المحمولة — كما يعطّل "
        "مهلات إيقاف الشاشة والسكون أثناء العمل على الكهرباء.",
    "Visual C++, DirectX, .NET and OpenAL, plus GPU management and "
    "hardware diagnostics.":
        "Visual C++ وDirectX و‎.NET وOpenAL، إضافة إلى إدارة كرت "
        "الرسومات وتشخيص العتاد.",
    "Windows and Office licence state, channel and expiry — "
    "read-only.":
        "حالة ترخيص ويندوز وOffice، وقناة التحديث، وتاريخ الانتهاء "
        "— للعرض فقط.",
    "Wipe temp, Windows Update and system caches.":
        "مسح الملفات المؤقتة وذاكرة Windows Update والنظام المخبأة.",
    "Word, Excel, PowerPoint and Outlook via the official ODT.":
        "Word وExcel وPowerPoint وOutlook عبر أداة ODT الرسمية.",

    # -- SOFTWARE_CATALOG's own pillar blurbs — distinct English text
    # from the matching card's "desc" above, so each needs its own entry
    "Everything a fresh machine needs to be usable — browsers, chat, "
    "media, utilities and the game launchers.":
        "كل ما يحتاجه جهاز جديد ليصبح جاهزًا للاستخدام — متصفحات "
        "ومحادثات ووسائط وأدوات ومشغّلات ألعاب.",
    "Languages, compilers, IDEs and the local AI stack — everything "
    "needed to build software on this machine.":
        "لغات ومترجمات وبيئات تطوير متكاملة وحزمة الذكاء الاصطناعي "
        "المحلية — كل ما يلزم لبناء البرامج على هذا الجهاز.",
    "The foundational dependencies other software fails without — "
    "plus GPU management and hardware diagnostics.":
        "التبعيات الأساسية التي تفشل البرامج الأخرى دونها — إضافة "
        "إلى إدارة كرت الرسومات وتشخيص العتاد.",

    # -- the runtimes pillar's one footnote + bulk-action hint -----------
    "OpenGL and Vulkan are not listed because they are not separate "
    "downloads — both are provided natively by your GPU's display "
    "driver, so installing the NVIDIA App (or your vendor's "
    "equivalent) is what keeps them current.":
        "لا يظهر OpenGL وVulkan في القائمة لأنهما ليسا تنزيلَين "
        "منفصلَين — كلاهما يوفَّر أصلًا عبر برنامج تشغيل كرت "
        "الرسومات، فتثبيت تطبيق NVIDIA (أو ما يعادله من الشركة "
        "المصنِّعة لديك) هو ما يبقيهما محدَّثَين.",
    "Ticks every core runtime below — Visual C++, DirectX, .NET and "
    "OpenAL — in one pass.":
        "يحدِّد كل بيئات التشغيل الأساسية أدناه — Visual C++ وDirectX "
        "و‎.NET وOpenAL — دفعة واحدة.",

    # -- SOFTWARE_CATALOG's 46 tool WhyYouNeedIt lines -------------------
    # Product/brand/file/API names stay in Latin script inline — see the
    # module docstring. Tool DisplayNames themselves are not translated
    # (no TITLES entry), matching how Arabic Windows keeps trademarks.
    "Fast, secure web browser from Google.":
        "متصفح ويب سريع وآمن من Google.",
    "Privacy-first Chromium browser with built-in ad blocking.":
        "متصفح Chromium يركّز على الخصوصية، مع حظر إعلانات مدمج.",
    "Fast, secure cloud-based messaging.":
        "تراسل سحابي سريع وآمن.",
    "Official WhatsApp messenger for the desktop.":
        "تطبيق WhatsApp الرسمي لسطح المكتب.",
    "Voice, video and text chat for friends and communities.":
        "محادثة صوتية ومرئية ونصية للأصدقاء والمجتمعات.",
    "Music and podcast streaming client.":
        "عميل بث الموسيقى والبودكاست.",
    "Plays practically every audio and video format ever made.":
        "يشغّل تقريبًا كل صيغة صوت وفيديو مصنوعة على الإطلاق.",
    "All-in-one notes, docs and project workspace.":
        "مساحة عمل شاملة للملاحظات والمستندات والمشاريع.",
    "Open-source archiver with best-in-class compression.":
        "أداة أرشفة مفتوحة المصدر بأفضل ضغط في فئتها.",
    "Opens RAR archives natively — the format 7-Zip can read but not "
    "create.":
        "يفتح أرشيفات RAR أصليًا — الصيغة التي يقرأها 7-Zip لكن لا "
        "ينشئها.",
    "Lightweight remote desktop — reach this PC, or help someone "
    "with theirs.":
        "سطح مكتب بعيد خفيف — للوصول إلى هذا الجهاز، أو مساعدة أحدهم "
        "في جهازه.",
    "Run whole operating systems in a window — test software without "
    "touching this install.":
        "تشغيل أنظمة تشغيل كاملة داخل نافذة — لاختبار البرامج دون "
        "المساس بهذا التثبيت.",
    "Media library and Apple device sync.":
        "مكتبة وسائط ومزامنة أجهزة Apple.",
    "The largest PC game store and launcher.":
        "أكبر متجر ومشغّل ألعاب حاسوب.",
    "Epic's store and launcher — free weekly games included.":
        "متجر ومشغّل Epic — يشمل ألعابًا أسبوعية مجانية.",
    "Rockstar's launcher for GTA, Red Dead and more.":
        "مشغّل Rockstar لسلسلة GTA وRed Dead وغيرها.",
    "Android app player — run mobile games and apps on Windows.":
        "مشغّل تطبيقات أندرويد — لتشغيل ألعاب وتطبيقات الجوال على "
        "ويندوز.",
    "General-purpose language for scripting, data science and AI/ML "
    "projects.":
        "لغة عامة الغرض للبرمجة النصية وعلم البيانات ومشاريع الذكاء "
        "الاصطناعي/التعلم الآلي.",
    "The Java Development Kit — compiles and runs Java, and includes "
    "the runtime, so no separate JRE is needed.":
        "حزمة تطوير جافا — تترجم جافا وتشغّلها، وتتضمن بيئة التشغيل، "
        "فلا حاجة إلى JRE منفصلة.",
    "JavaScript runtime for web backends, build tools and npm "
    "packages.":
        "بيئة تشغيل جافاسكريبت للخوادم الخلفية وأدوات البناء وحزم npm.",
    "C/C++ compiler toolchain for native Windows builds.":
        "سلسلة أدوات مترجم C/C++ لبناء تطبيقات ويندوز الأصلية.",
    "Version control — track changes and collaborate on any "
    "codebase.":
        "نظام تحكم بالإصدارات — لتتبع التغييرات والتعاون على أي "
        "قاعدة أكواد.",
    "Lightweight, extensible code editor — the daily driver for "
    "most languages.":
        "محرر أكواد خفيف وقابل للتوسيع — الخيار اليومي لمعظم اللغات.",
    "AI-native code editor built on VS Code, with built-in AI pair "
    "programming.":
        "محرر أكواد مبني على VS Code مع ذكاء اصطناعي مدمج للبرمجة "
        "الثنائية.",
    "Google's agent-first development environment, built around an "
    "AI that plans and edits across your whole project.":
        "بيئة تطوير من Google تعتمد على وكيل ذكاء اصطناعي يخطط "
        "ويعدّل عبر مشروعك بأكمله.",
    "Java IDE popular in university courses — project templates and "
    "a visual GUI builder.":
        "بيئة تطوير جافا شائعة في المقررات الجامعية — قوالب مشاريع "
        "وأداة بناء واجهات مرئية.",
    "Full-featured Python IDE with debugging, refactoring and test "
    "tools.":
        "بيئة تطوير بايثون متكاملة مع أدوات تصحيح وإعادة هيكلة "
        "واختبار.",
    "Full-featured Java IDE with deep code intelligence and "
    "refactoring.":
        "بيئة تطوير جافا متكاملة بذكاء برمجي عميق وإعادة هيكلة.",
    "Run open-source LLMs (Llama, Mistral, etc.) locally — no cloud "
    "required.":
        "تشغيل نماذج لغوية مفتوحة المصدر (Llama وMistral وغيرها) "
        "محليًا — دون الحاجة إلى سحابة.",
    "A ChatGPT-style web interface for models running in Ollama.":
        "واجهة ويب بأسلوب ChatGPT للنماذج العاملة في Ollama.",
    "Build and run containers — package an app with everything it "
    "needs to run anywhere.":
        "بناء الحاويات وتشغيلها — لتغليف تطبيق مع كل ما يحتاجه للعمل "
        "في أي مكان.",
    "Build, test and document REST/GraphQL APIs.":
        "بناء واجهات REST/GraphQL واختبارها وتوثيقها.",
    "Every Visual C++ redistributable from 2005 to 2015–2022, both "
    "architectures — this is what fixes “MSVCR100.dll is "
    "missing” and its relatives.":
        "كل حزم Visual C++ القابلة للتوزيع من 2005 إلى 2015–2022، "
        "بمعماريتَي x86 وx64 — هذا ما يصلح رسالة “MSVCR100.dll "
        "is missing” وأخواتها.",
    "The June 2010 cumulative package — the D3DX9/10/11 and XInput "
    "libraries older games still ask for. Windows 11's own DirectX "
    "12 is untouched.":
        "الحزمة التراكمية لشهر يونيو 2010 — مكتبات D3DX9/10/11 "
        "وXInput التي لا تزال الألعاب القديمة تطلبها. DirectX 12 "
        "الخاص بويندوز 11 لا يتأثر.",
    "Runs modern .NET desktop applications.":
        "لتشغيل تطبيقات سطح المكتب الحديثة المبنية على .NET.",
    "Enabled as a Windows feature rather than downloaded — needed by "
    "a great deal of older business and game software. Requires "
    "Administrator.":
        "يُفعَّل كميزة من ميزات ويندوز بدلًا من تنزيله — يحتاجه "
        "كثير من برامج الأعمال والألعاب القديمة. يتطلب صلاحيات "
        "المسؤول.",
    "Positional 3D audio used by many older and cross-platform "
    "games.":
        "صوت ثلاثي الأبعاد موضعي تستخدمه كثير من الألعاب القديمة "
        "والمتعددة المنصات.",
    "NVIDIA's current driver and display-settings app — the "
    "replacement for GeForce Experience. Also how OpenGL and Vulkan "
    "stay up to date.":
        "تطبيق NVIDIA الحالي لبرامج التشغيل وإعدادات العرض — بديل "
        "GeForce Experience. كما أنه الطريقة التي يبقى بها OpenGL "
        "وVulkan محدَّثين.",
    "GPU overclocking, fan curves and on-screen performance "
    "monitoring.":
        "رفع تردد كرت الرسومات، ومنحنيات المراوح، ومراقبة الأداء "
        "على الشاشة.",
    "CPU, motherboard and memory identification tool.":
        "أداة للتعرّف على المعالج ولوحة الأم والذاكرة.",
    "Graphics card information, sensors and BIOS tools.":
        "معلومات كرت الرسومات وحساساته وأدوات BIOS.",
    "Drive health and S.M.A.R.T. monitoring.":
        "مراقبة صحة الأقراص وبيانات S.M.A.R.T.",
    "Live voltages, temperatures and fan speeds.":
        "قراءات مباشرة للجهد والحرارة وسرعات المراوح.",
    "Every hardware sensor on this machine in one tree — "
    "temperatures, clocks, voltages and fan speeds, with logging.":
        "كل حساسات عتاد هذا الجهاز في شجرة واحدة — الحرارة "
        "والترددات والجهد وسرعات المراوح، مع تسجيل البيانات.",
    "GPU stress test — pushes the card to its thermal limit to "
    "prove stability, or to find the crash before a game does.":
        "اختبار إجهاد لكرت الرسومات — يدفع الكرت إلى حده الحراري "
        "لإثبات ثباته، أو لاكتشاف العطل قبل أن تفعله لعبة.",
    "CPU rendering benchmark — a repeatable score for comparing "
    "this machine against the same chip elsewhere.":
        "اختبار أداء لتصيير المعالج — نتيجة قابلة للتكرار لمقارنة "
        "هذا الجهاز بالمعالج نفسه في مكان آخر.",

    # -- BloatwarePurgeDialog: src/backend/modules/01-Catalogs.ps1's
    # $Script:BloatCatalog "Note" field (48 entries) — Pulse's own
    # authored copy explaining what removing each package costs, same
    # category as SOFTWARE_CATALOG's "why" field above. The catalog's
    # "Name" field (Instagram, TikTok, Xbox app, …) is NOT translated —
    # brand/product names and Windows' own official app names, same
    # convention as every tool DisplayName elsewhere in this module.
    "Store stub that opens the web app. Nothing depends on it.":
        "امتداد من المتجر يفتح تطبيق الويب. لا شيء يعتمد عليه.",
    "Amazon's pre-installed player stub.":
        "امتداد مشغّل Amazon المثبَّت مسبقًا.",
    "Facebook Messenger stub.":
        "امتداد Facebook Messenger.",
    "Pre-installed on many OEM images.":
        "مثبَّت مسبقًا على كثير من نسخ الشركات المصنِّعة.",
    "Store stub that opens the web app.":
        "امتداد من المتجر يفتح تطبيق الويب.",
    "Pre-installed streaming stub.":
        "امتداد بث مثبَّت مسبقًا.",
    "The Store build. Removing it does NOT touch a desktop Spotify "
    "install.":
        "إصدار المتجر. إزالته لا تمسّ تثبيت Spotify على سطح المكتب.",
    "Candy Crush, Bubble Witch, Farm Heroes and the rest of the King "
    "suite.":
        "Candy Crush وBubble Witch وFarm Heroes وبقية ألعاب King.",
    "Gameloft promotional install.":
        "تثبيت ترويجي من Gameloft.",
    "Casual game, ad-supported.":
        "لعبة ترفيهية مدعومة بالإعلانات.",
    "Task app. Removing it does not affect Outlook tasks.":
        "تطبيق مهام. إزالته لا تؤثر في مهام Outlook.",
    "The retired Store OneNote, superseded by OneNote in Microsoft "
    "365.":
        "إصدار OneNote القديم من المتجر، حلّ محله OneNote في "
        "Microsoft 365.",
    "Paint 3D only. Classic Paint (mspaint.exe) is a separate app "
    "and is untouched.":
        "Paint 3D فقط. برنامج الرسام الكلاسيكي (mspaint.exe) تطبيق "
        "منفصل ولا يتأثر.",
    "Windows Mixed Reality, retired by Microsoft.":
        "الواقع المختلط لويندوز، أوقفته Microsoft.",
    "Retired 3D modelling app.":
        "تطبيق نمذجة ثلاثية الأبعاد متوقف.",
    "Consumer Skype stub.":
        "امتداد Skype للمستهلكين.",
    "Store wrapper around the website.":
        "غلاف من المتجر حول الموقع.",
    "Pre-installed video editor.":
        "محرر فيديو مثبَّت مسبقًا.",
    "Notes app. Existing notes sync to OneNote and survive removal.":
        "تطبيق ملاحظات. الملاحظات الحالية تُزامَن مع OneNote وتبقى "
        "بعد الإزالة.",
    "The 'Office' launcher tile, not Office itself.":
        "لبنة مشغّل 'Office'، وليست Office نفسه.",
    "The consumer Teams that ships with Windows 11. Work/school "
    "Teams is a separate install.":
        "نسخة Teams للمستهلكين المرفقة مع ويندوز 11. نسخة العمل/"
        "التعليم منفصلة.",
    "The web-wrapper Outlook Microsoft pre-installs.":
        "نسخة Outlook (غلاف ويب) التي تثبّتها Microsoft مسبقًا.",
    "Legacy Groove/Media Player entry.":
        "إدخال قديم لـGroove/مشغّل الوسائط.",
    "Legacy video player.":
        "مشغّل فيديو قديم.",
    "The Phone Link app itself - texts, calls and notification "
    "mirroring from an Android or iPhone. Removing it does not "
    "touch the Mobile devices settings page.":
        "تطبيق Phone Link نفسه - الرسائل والمكالمات ومزامنة "
        "الإشعارات من هاتف أندرويد أو آيفون. إزالته لا تمسّ صفحة "
        "إعدادات الأجهزة المحمولة.",
    "The system component behind Settings > Bluetooth & devices > "
    "Mobile devices: phone photos in File Explorer, and using a "
    "phone as a connected camera. Not the Phone Link app - removing "
    "this leaves that page with nothing to configure.":
        "المكوّن النظامي خلف الإعدادات > البلوتوث والأجهزة > الأجهزة "
        "المحمولة: صور الهاتف في مستكشف الملفات، واستخدام الهاتف "
        "كاميرا متصلة. ليس تطبيق Phone Link - إزالة هذا يترك تلك "
        "الصفحة بلا شيء لضبطه.",
    "Phone Link's background host. Remove alongside Phone Link "
    "(app).":
        "المضيف الخلفي لـPhone Link. أزِله مع تطبيق Phone Link.",
    "The Copilot app. The taskbar button is a separate tweak.":
        "تطبيق Copilot. زر شريط المهام تعديل منفصل.",
    "The Store wrapper build shipped on newer 11 images.":
        "إصدار غلاف المتجر المرفق بنسخ 11 الأحدث.",
    "Retired assistant. Windows Search is unaffected.":
        "مساعد متوقف. بحث ويندوز لا يتأثر.",
    "The classic Mail/Calendar pair, retired in favour of new "
    "Outlook.":
        "ثنائي البريد/التقويم الكلاسيكي، أوقف لصالح Outlook الجديد.",
    "Also feeds the taskbar weather widget.":
        "يغذّي أيضًا أداة الطقس في شريط المهام.",
    "MSN news feed.":
        "خلاصة أخبار MSN.",
    "MSN money feed.":
        "خلاصة مال MSN.",
    "MSN sports feed.":
        "خلاصة رياضة MSN.",
    "Offline maps app, retired by Microsoft.":
        "تطبيق خرائط دون اتصال، أوقفته Microsoft.",
    "Sends diagnostics and feedback to Microsoft.":
        "يرسل بيانات التشخيص والملاحظات إلى Microsoft.",
    "Support-contact app.":
        "تطبيق التواصل مع الدعم.",
    "The 'Get Started' / Tips promo app.":
        "تطبيق 'ابدأ الآن' / النصائح الترويجي.",
    "Contacts app used by the retired Mail client.":
        "تطبيق جهات اتصال يستخدمه عميل البريد المتوقف.",
    "The Widgets board and its MSN feed.":
        "لوحة الودجات وخلاصة MSN الخاصة بها.",
    "Xbox in-game UI framework. Some Store games need it to sign in.":
        "إطار واجهة Xbox داخل اللعبة. بعض ألعاب المتجر تحتاجه "
        "لتسجيل الدخول.",
    "The Win+G overlay surface.":
        "سطح تراكب Win+G.",
    "Game Bar itself, including its screen capture.":
        "شريط الألعاب نفسه، بما في ذلك تسجيل الشاشة.",
    "Live captions inside Xbox games.":
        "ترجمة مباشرة داخل ألعاب Xbox.",
    "Store game sign-in. Removing it can lock you out of installed "
    "games.":
        "تسجيل الدخول لألعاب المتجر. إزالته قد تمنعك من الدخول إلى "
        "الألعاب المثبَّتة.",
    "The Xbox console companion - Microsoft.GamingApp on Windows 11, "
    "Microsoft.XboxApp on 10.":
        "تطبيق مرافقة أجهزة Xbox - Microsoft.GamingApp على ويندوز "
        "11، وMicrosoft.XboxApp على 10.",
    "Bundled codec pack. Windows plays every mainstream format "
    "without it.":
        "حزمة ترميز مرفقة. يشغّل ويندوز كل الصيغ الشائعة دونها.",

    # -- StartupManagerDialog: src/backend/modules/05-Startup.ps1's rule
    # tables (StartupProtectedRules/StartupDisableRules/StartupKeepRules
    # + the Review-tier default) — 43 Reason strings, same
    # "Pulse's-own-authored-copy" category as the two catalogs above.
    "Windows Security component — disabling it weakens malware "
    "protection.":
        "مكوّن أمان ويندوز — تعطيله يُضعف الحماية من البرمجيات "
        "الخبيثة.",
    "Security / endpoint-protection agent — must keep running from "
    "boot to protect the machine.":
        "وكيل أمان / حماية النقاط الطرفية — يجب أن يبقى يعمل من "
        "الإقلاع لحماية الجهاز.",
    "Audio driver / sound-device helper — jack detection, device "
    "switching and effects depend on it.":
        "مساعد برنامج تشغيل الصوت / جهاز الصوت — يعتمد عليه كشف "
        "المنفذ وتبديل الأجهزة والمؤثرات.",
    "Windows text-input / IME subsystem — required for keyboard "
    "layout and language switching.":
        "نظام إدخال النص / IME في ويندوز — مطلوب لتخطيط لوحة "
        "المفاتيح وتبديل اللغة.",
    "Touchpad / pointing-device driver — gestures, scrolling and "
    "its settings page depend on it.":
        "برنامج تشغيل لوحة اللمس / جهاز التأشير — تعتمد عليه "
        "الإيماءات والتمرير وصفحة إعداداته.",
    "Graphics tablet driver — pen input stops working the moment "
    "it is not running.":
        "برنامج تشغيل لوحة الرسم — يتوقف إدخال القلم فور توقف "
        "تشغيله.",
    "Accessibility tool — for some users this is how the machine "
    "is operated at all.":
        "أداة إتاحة — هي الطريقة الوحيدة لتشغيل الجهاز لدى بعض "
        "المستخدمين.",
    "Storage / RAID controller helper — monitors the array your "
    "drives depend on.":
        "مساعد وحدة تحكم التخزين / RAID — يراقب المصفوفة التي "
        "تعتمد عليها أقراصك.",
    "Bluetooth stack component — paired keyboards, mice and "
    "headsets depend on it at sign-in.":
        "مكوّن مكدّس البلوتوث — تعتمد عليه لوحات المفاتيح والفأرات "
        "وسماعات الرأس المقترنة عند تسجيل الدخول.",
    "Vendor power / thermal manager — battery life and fan "
    "behaviour are controlled here.":
        "مدير الطاقة / الحرارة من الشركة المصنِّعة — يتحكم هنا في "
        "عمر البطارية وسلوك المراوح.",
    "Cloud sync — keeps syncing in the background; launch it "
    "manually or sign in to files.com when you actually need it.":
        "مزامنة سحابية — تستمر بالمزامنة في الخلفية؛ شغّلها يدويًا "
        "أو سجّل الدخول عند الحاجة الفعلية.",
    "Cloud sync client — adds boot time for a service you can "
    "start on demand.":
        "عميل مزامنة سحابية — يضيف وقتًا للإقلاع لخدمة يمكنك "
        "تشغيلها عند الطلب.",
    "Game launcher with background update checks — a common "
    "multi-second boot delay.":
        "مشغّل ألعاب يتحقق من التحديثات في الخلفية — سبب شائع "
        "لتأخير الإقلاع بضع ثوانٍ.",
    "Game launcher — heavy background process not needed until "
    "you actually play.":
        "مشغّل ألعاب — عملية خلفية ثقيلة لا حاجة إليها حتى تبدأ "
        "اللعب فعليًا.",
    "Game launcher with an always-on updater service.":
        "مشغّل ألعاب بخدمة تحديث تعمل دائمًا.",
    "Game launcher — safe to start manually instead of at every "
    "boot.":
        "مشغّل ألعاب — آمن لتشغيله يدويًا بدل كل إقلاع.",
    "Game launcher background updater.":
        "محدِّث خلفي لمشغّل الألعاب.",
    "Chat client — convenient always-on, but it's pure boot-time "
    "overhead if you open it manually anyway.":
        "عميل محادثة — مريح دائم التشغيل، لكنه عبء إقلاع صرف إن "
        "كنت ستفتحه يدويًا على أي حال.",
    "Music client — no reason to launch before you're ready to "
    "listen.":
        "عميل موسيقى — لا داعي لتشغيله قبل استعدادك للاستماع.",
    "Chat client that rarely needs to be running before sign-in "
    "finishes.":
        "عميل محادثة نادرًا ما يحتاج للعمل قبل اكتمال تسجيل الدخول.",
    "Electron-based chat app — one of the heaviest common "
    "boot-time offenders.":
        "تطبيق محادثة مبني على Electron — من أثقل أسباب تأخير "
        "الإقلاع الشائعة.",
    "Electron-based chat app — noticeable boot-time cost for a "
    "background presence.":
        "تطبيق محادثة مبني على Electron — تكلفة إقلاع ملحوظة مقابل "
        "وجود خلفي.",
    "Meeting client — only needed right before a call.":
        "عميل اجتماعات — لا حاجة إليه إلا قبيل المكالمة مباشرة.",
    "Adobe's background updater — checks for updates you can "
    "trigger manually instead.":
        "محدِّث Adobe الخلفي — يتحقق من تحديثات يمكنك تشغيلها يدويًا "
        "بدلًا من ذلك.",
    "Apple device helper — only useful while an iPhone/iPad is "
    "actually connected.":
        "مساعد أجهزة Apple — مفيد فقط أثناء اتصال آيفون/آيباد فعليًا.",
    "Legacy media helper rarely needed by modern apps.":
        "مساعد وسائط قديم نادرًا ما تحتاجه التطبيقات الحديثة.",
    "Chrome's background updater — Chrome updates itself fine "
    "when it launches.":
        "محدِّث Chrome الخلفي — يحدِّث Chrome نفسه جيدًا عند تشغيله.",
    "Edge's background updater — Edge updates itself fine when it "
    "launches.":
        "محدِّث Edge الخلفي — يحدِّث Edge نفسه جيدًا عند تشغيله.",
    "Legacy Cortana shell integration — safe to disable on most "
    "modern setups.":
        "تكامل Cortana القديم مع الواجهة — آمن تعطيله في معظم "
        "الإعدادات الحديثة.",
    "Phone Link — only useful if you actively use phone/PC linking.":
        "Phone Link — مفيد فقط إن كنت تستخدم ربط الهاتف بالحاسوب "
        "فعليًا.",
    "Adobe Creative Cloud desktop — one of the heaviest known "
    "startup offenders.":
        "تطبيق Adobe Creative Cloud لسطح المكتب — من أثقل أسباب "
        "بطء الإقلاع المعروفة.",
    "Java's background updater — safe to check manually instead.":
        "محدِّث Java الخلفي — آمن التحقق منه يدويًا بدلًا من ذلك.",
    "NVIDIA telemetry helper — the display driver itself does not "
    "need it at boot.":
        "مساعد قياس بيانات NVIDIA — برنامج تشغيل العرض نفسه لا "
        "يحتاجه عند الإقلاع.",
    "Audio driver tray helper — needed for sound device "
    "switching/effects to work correctly.":
        "مساعد درج برنامج تشغيل الصوت — مطلوب ليعمل تبديل جهاز "
        "الصوت/المؤثرات بشكل صحيح.",
    "Touchpad/precision-input driver — gestures and settings "
    "depend on it.":
        "برنامج تشغيل لوحة اللمس/الإدخال الدقيق — تعتمد عليه "
        "الإيماءات والإعدادات.",
    "GPU control panel tray — lightweight and needed for "
    "display/overlay settings.":
        "درج لوحة تحكم كرت الرسومات — خفيف ومطلوب لإعدادات "
        "العرض/التراكب.",
    "Windows input/IME subsystem — required for text input "
    "switching.":
        "نظام إدخال ويندوز/IME — مطلوب لتبديل إدخال النص.",
    "Security/endpoint-protection agent — should stay running "
    "from boot.":
        "وكيل أمان/حماية النقاط الطرفية — يجب أن يبقى يعمل من "
        "الإقلاع.",
    "Graphics tablet driver — needed immediately for pen input to "
    "work.":
        "برنامج تشغيل لوحة الرسم — مطلوب فورًا ليعمل إدخال القلم.",
    "Microsoft Office's own updater — turning it off stops Office "
    "receiving security fixes.":
        "محدِّث Microsoft Office نفسه — إيقافه يمنع Office من تلقّي "
        "إصلاحات الأمان.",
    "Windows Security — disabling weakens malware protection.":
        "أمان ويندوز — تعطيله يُضعف الحماية من البرمجيات الخبيثة.",
    "Not a recognized publisher — check what it is before "
    "disabling it.":
        "ناشر غير معروف — تحقق مما هو قبل تعطيله.",

    # -- OfficeWizardDialog's own choice-page cards (v10.17.1) — see the
    # matching note in TITLES above.
    "Pulse fetches Microsoft's Deployment Tool and applies a "
    "standard configuration for you. Nothing to find, nothing to "
    "browse to.":
        "يجلب Pulse أداة النشر من Microsoft ويطبِّق تكوينًا قياسيًا "
        "نيابةً عنك. لا شيء لإيجاده، ولا شيء لتصفحه.",
    "Auto-detect the Office folder on your Desktop, or browse to "
    "wherever you saved it.":
        "اكتشاف مجلد Office على سطح مكتبك تلقائيًا، أو تصفّح إلى "
        "المكان الذي حفظته فيه.",
    "New to this? A plain-language walkthrough of Microsoft's own "
    "tools, which then hands off to the step above.":
        "جديد على هذا؟ شرح مبسّط لأدوات Microsoft نفسها، يُسلِّمك "
        "بعدها إلى الخطوة أعلاه.",

    # -- HubDialog's own sub-action rows (v10.17.2) — see the matching
    # note in TITLES above.
    "Dead folders, duplicates, malformed entries and shadowed "
    "toolchains — reported, nothing changed.":
        "مجلدات ميتة، وتكرارات، وإدخالات غير سليمة، وسلاسل أدوات "
        "متراكبة — تُبلَّغ دون تغيير أي شيء.",
    "Two Pythons, two Nodes, two Javas — see which copy your "
    "terminal actually runs, and promote the one you want. "
    "Reorders your PATH; removes nothing.":
        "نسختا Python، ونسختا Node، ونسختا Java — اعرف أي نسخة "
        "يشغّلها الطرفية فعليًا، ورقِّ التي تريدها. يعيد ترتيب "
        "PATH؛ لا يزيل شيئًا.",
    "Removes only what is provably safe: duplicates, unparseable "
    "entries, and folders missing from a mounted internal disk. A "
    "restore point and a copy of your current PATH are saved "
    "first.":
        "يزيل فقط ما يثبت أنه آمن: التكرارات، والإدخالات غير "
        "القابلة للتحليل، والمجلدات المفقودة من قرص داخلي مثبَّت. "
        "تُحفظ نقطة استعادة ونسخة من PATH الحالي أولًا.",
    "Flags only what points at files that are provably gone. "
    "Everything removed is backed up first, behind a restore "
    "point.":
        "يُعلِّم فقط ما يشير إلى ملفات يثبت أنها اختفت. كل ما "
        "يُزال يُنسخ احتياطيًا أولًا خلف نقطة استعادة.",
    "Put back everything the most recent purge removed.":
        "إعادة كل ما أزالته آخر عملية إزالة.",
    "Open the registry exports, task definitions and folders a "
    "purge set aside.":
        "فتح تصديرات السجل وتعريفات المهام والمجلدات التي جنَّبتها "
        "عملية الإزالة.",
    "Force-purge Chromium Edge, with a backup kept.":
        "إزالة Chromium Edge قسرًا، مع الاحتفاظ بنسخة احتياطية.",
    "Reinstall Edge and restore your backed-up settings.":
        "إعادة تثبيت Edge واستعادة إعداداتك المحفوظة احتياطيًا.",
    "Open the settings and profile data saved before removal.":
        "فتح الإعدادات وبيانات الملف الشخصي المحفوظة قبل الإزالة.",
    "Back up local files, then uninstall OneDrive.":
        "نسخ الملفات المحلية احتياطيًا، ثم إلغاء تثبيت OneDrive.",
    "Reinstall OneDrive so it's back and syncing.":
        "إعادة تثبيت OneDrive ليعود ويُزامن من جديد.",
    "Open files rescued before OneDrive removal.":
        "فتح الملفات المنقذة قبل إزالة OneDrive.",
    "Link state, speed, addresses, gateway and driver for every "
    "adapter — read-only.":
        "حالة الاتصال والسرعة والعناوين والبوابة وبرنامج التشغيل "
        "لكل محوّل — للعرض فقط.",
    "How old each network driver is, and the official Intel / "
    "Realtek page to get a newer one.":
        "عمر كل برنامج تشغيل شبكة، وصفحة Intel / Realtek الرسمية "
        "للحصول على إصدار أحدث.",
    "Rebuild Winsock and TCP/IP, then renew the lease. Requires a "
    "restart to finish.":
        "إعادة بناء Winsock وTCP/IP، ثم تجديد عقد الإيجار. يتطلب "
        "إعادة التشغيل لإتمام العملية.",

    # -- LeftoverRow's own "reason" field (v10.17.2) — Pulse's own
    # deterministic copy, exhaustively read off
    # src/backend/modules/17-Leftovers.ps1's own `-Reason` literals,
    # translated on the same "this is Pulse's copy, not live system
    # output" reasoning as BloatRow's Note/StartupRow's Reason.
    "Disabled in Pulse, and the program it pointed at has since "
    "been uninstalled.":
        "معطَّل في Pulse، والبرنامج الذي كان يشير إليه أُزيل منذ ذلك "
        "الحين.",
    "Launches at sign-in, and the program it points at is not on "
    "this PC.":
        "يُشغَّل عند تسجيل الدخول، والبرنامج الذي يشير إليه غير "
        "موجود على هذا الجهاز.",
    "A shortcut Pulse disabled, to a program that has since been "
    "uninstalled.":
        "اختصار عطّله Pulse، لبرنامج أُزيل منذ ذلك الحين.",
    "A Startup-folder shortcut to a program that is not on this PC.":
        "اختصار في مجلد بدء التشغيل لبرنامج غير موجود على هذا "
        "الجهاز.",
    "Scheduled to run a program that is not on this PC.":
        "مجدولة لتشغيل برنامج غير موجود على هذا الجهاز.",
    "An uninstalled app's files, left behind - its own uninstaller "
    "marked this folder dead.":
        "ملفات تطبيق أُزيل، تُركت خلفًا - أداة إزالة التثبيت نفسها "
        "وسمت هذا المجلد بأنه ميت.",
    "A right-click menu extension whose DLL is not on this PC.":
        "امتداد في قائمة النقر بالزر الأيمن ملف DLL الخاص به غير "
        "موجود على هذا الجهاز.",
    "A right-click menu entry that launches a program that is not "
    "on this PC.":
        "إدخال في قائمة النقر بالزر الأيمن يشغِّل برنامجًا غير "
        "موجود على هذا الجهاز.",

    # -- DataHygieneDialog's own rows (v10.17.3) — see the matching
    # note in TITLES above.
    "Diagnostic history only. Pulse writes a new log on the next "
    "run.":
        "سجل تشخيصي فقط. يكتب Pulse سجلًا جديدًا في المرة القادمة.",
    "Update downloads Pulse can fetch again. Already pruned "
    "automatically after 7 days.":
        "تنزيلات تحديث يمكن لـPulse جلبها مجددًا. تُقلَّم تلقائيًا "
        "بعد 7 أيام أصلًا.",
    "Your Edge bookmarks, favourites and preferences, saved before "
    "Edge was removed. Deleting this means Restore Edge can no "
    "longer bring them back.":
        "إشارات Edge المرجعية والمفضلة والتفضيلات، محفوظة قبل إزالة "
        "Edge. حذف هذا يعني أن استعادة Edge لن تتمكن من إعادتها.",
    "Your own files, copied out of OneDrive before the client was "
    "uninstalled. For anything that was not synced elsewhere, this "
    "is the only copy.":
        "ملفاتك الخاصة، نُسخت من OneDrive قبل إلغاء تثبيت العميل. "
        "لأي شيء لم يُزامَن في مكان آخر، هذه هي النسخة الوحيدة.",
    "Shortcuts moved aside by the Startup Manager. Deleting this "
    "means they cannot be put back.":
        "اختصارات نحّاها مدير بدء التشغيل جانبًا. حذف هذا يعني أنه "
        "لا يمكن إعادتها.",
    "Third-party driver packages exported by Driver Backup. "
    "Re-exportable while the drivers are still installed.":
        "حزم برامج تشغيل خارجية صدَّرتها النسخة الاحتياطية لبرامج "
        "التشغيل. يمكن إعادة تصديرها ما دامت برامج التشغيل مثبَّتة.",

    # -- PulseApp.SHORTCUTS row descriptions (v10.17.3). Fixed, non-
    # interpolated strings owned by the app itself — same exact-text
    # lookup as everything else in this dict.
    "Search everything":
        "البحث في كل شيء",
    "Filter this module by status":
        "تصفية هذه الوحدة بالحالة",
    "Go to the dashboard":
        "الانتقال إلى لوحة المعلومات",
    "Jump to a module":
        "الانتقال إلى وحدة",
    "Show / hide live output":
        "إظهار / إخفاء الإخراج المباشر",
    "Move between sections — search, sidebar, cards":
        "التنقل بين الأقسام — البحث، الشريط الجانبي، البطاقات",
    "Move between cards in the grid":
        "التنقل بين البطاقات في الشبكة",
    "Run the focused card":
        "تشغيل البطاقة المُركَّز عليها",
    "Back to the dashboard":
        "العودة إلى لوحة المعلومات",
    "This shortcut sheet":
        "ورقة الاختصارات هذه",

    # -- utils.updater.can_apply's one non-empty reason (v10.17.3). Finite,
    # non-interpolated backend text — same exact-text lookup as the rest
    # of this dict.
    "Pulse is running from source; update it with git "
    "rather than an installer.":
        "يعمل Pulse من الشيفرة المصدرية؛ حدِّثه باستخدام git "
        "بدلًا من مُثبِّت.",
}


def tr_title(text: str, lang: str) -> str:
    """Looks up a catalog TITLE. English text passes through unchanged
    (both as the default language and as the safe fallback for a title
    with no Arabic entry yet)."""
    if lang != "ar":
        return text
    return TITLES.get(text, text)


def tr_desc(text: str, lang: str) -> str:
    """Looks up a catalog DESCRIPTION/tagline. Same fallback contract as
    tr_title."""
    if lang != "ar":
        return text
    return DESCRIPTIONS.get(text, text)
