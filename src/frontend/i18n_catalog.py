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

WHAT THIS DOES NOT COVER, on purpose (see i18n.py's own scope note and
ROADMAP.md): dialogs opened FROM a card that are not the catalog itself —
the Restore Point Browser, Startup Manager, Bloatware Purge internals,
Health Report, Update Center, the Office setup wizard, and
ToolInstallWizardDialog's own per-app install-option picker — stay
English in this pass.
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

    # -- the thirteen band/group headers (menu_structure.py "groups") ---
    "INSTALL": "تثبيت",
    "MANAGE INSTALLED": "إدارة المثبت",
    "PREINSTALLED & BUNDLED": "مثبت مسبقًا ومرفق",
    "PERFORMANCE & POWER": "الأداء والطاقة",
    "NETWORK": "الشبكة",
    "INTERFACE": "الواجهة",
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
