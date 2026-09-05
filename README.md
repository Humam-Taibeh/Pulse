[⚡ Back to Main Profile](https://github.com/Humam-Taibeh)

<div align="center">

<img src="assets/pulse.ico" width="88" alt="Pulse" />

# ⚡ PULSE

**A Windows orchestration toolkit — a data-driven PowerShell engine wrapped in a GPU-accelerated, glass-morphism PySide6 command center, with a real-time operations console, declarative playbooks, and a global kill switch.**

> ### 🧪 Beta software
> **Pulse is pre-release software.** It is unsigned, has had no third-party security review, and modifies the registry, services and installed software on the machine it runs on. The safety layers described below are real and tested, but they are not a substitute for your own backup. Run it on a machine you can afford to restore.

[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white)](#-prerequisites)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](#-prerequisites)
[![PowerShell](https://img.shields.io/badge/powershell-5.1%2B-5391FE?logo=powershell&logoColor=white)](#-prerequisites)
[![GUI](https://img.shields.io/badge/GUI-PySide6%20(Qt%206)-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Release](https://img.shields.io/github/v/release/Humam-Taibeh/Pulse?label=release&color=blueviolet&logo=github)](https://github.com/Humam-Taibeh/Pulse/releases/latest)
[![Tests](https://img.shields.io/badge/tests-1%2C303%20pytest%20%2B%20180%20Pester-success)](#-testing--continuous-integration)
[![CI](https://github.com/Humam-Taibeh/Pulse/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/Humam-Taibeh/Pulse/actions/workflows/ci.yml)
[![Release build](https://github.com/Humam-Taibeh/Pulse/actions/workflows/release.yml/badge.svg)](https://github.com/Humam-Taibeh/Pulse/actions/workflows/release.yml)
[![Lint](https://img.shields.io/badge/PSScriptAnalyzer-0%20findings-brightgreen?logo=powershell&logoColor=white)](PSScriptAnalyzerSettings.psd1)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

*Built for power users, IT technicians, and developers who need a repeatable and auditable way to deploy, tune, repair, and report on a Windows machine — from a single launcher.*

[Features](#-key-features) · [Console](#-the-live-operations-console) · [Quick Start](#-quick-start) · [Architecture](#-architecture--tech-stack) · [Structure](#-repository-structure) · [Task API](#-task-api--core-modules) · [Safety](#-safety-model) · [Roadmap](#-roadmap)

</div>

---

## 📖 Overview

Setting up or rescuing a Windows machine is a long tail of manual work: install twenty apps one at a time, hunt registry keys for the same five tweaks, run `sfc`/`DISM` and watch a console, strip telemetry, purge Edge and OneDrive, back up drivers — then do it all again on the next machine, with no record of what changed and no reliable way back.

**Pulse** collapses that into one application. It pairs two layers bound by a single strict contract:

| Layer | Technology | Role |
|---|---|---|
| 🖥️ **Frontend** | Python 3.10+ · PySide6 (Qt 6) | Frameless glass shell, dual themes, static obsidian canvas, real-time streaming console with live phase reporting, global kill switch, command palette, toasts |
| ⚙️ **Backend** | PowerShell 5.1+ — 19 modules, ~10k lines | Data-driven engine for deployment, tweaks, maintenance, privacy, recovery and read-only reporting |

**The GUI never touches the system itself.** Every card dispatches a *named task* to `core.ps1` on a background `QThread`; the engine executes it, streams progress to the UI as it happens, and closes with exactly one machine-parseable verdict line. The same engine also runs **fully standalone** as a self-elevating terminal application with a hierarchical menu — no Python required.

> **Two different "module" counts, both correct.** The release notes describe a **4-module core architecture**; this README counts **19 backend modules**. They are not in conflict — they count different layers. The **4** are the top-level modules a *user* navigates in the sidebar: Software Management, System & Tweaks, Maintenance & Security, and Utilities & Tools (defined as the four top-level entries in [menu_structure.py](src/frontend/menu_structure.py), each with its own semantic accent token). The **19** are the numbered PowerShell engine files under [src/backend/modules/](src/backend/modules/) that those four surfaces dispatch into — `00-Foundation` through `30-GuiDispatcher`. One user-facing module is served by many engine files: *Maintenance & Security*, for instance, draws on `02-Safety`, `07-Maintenance`, `08-Privacy` and `14-Inspectors`.

Every module follows the same lifecycle:

> **preview → confirm → snapshot → apply → log**

### Why it's different

- **Little is guessed.** Card state (`APPLIED` chips, the Health & Drift report) comes from a strictly read-only probe that queries the live system — not a cache the GUI could disagree with reality about.
- **Designed to be recoverable.** A restore point, per-tweak registry snapshots and per-service state snapshots are captured *before* the first mutation of a session. *Reset All Tweaks* restores **your** prior values, not Microsoft's defaults.
- **Nothing is opaque.** Every action streams live, ends with a verdict plus a structured metrics envelope, and is appended to a rotated session log you can open from inside the app.
- **Nothing downloaded is trusted.** The self-updater refuses to execute any installer whose SHA-256 is not published in the release's `SHA256SUMS` — which also means it declines a release that ships without one — as every release before v10.4 did. See [Safety Model](#-safety-model).

> **On authorship.** This project is built through **Advanced GenAI System Orchestration**: every module boundary, thread-safety contract, security anchor and rendering budget below was specified through detailed architectural prompting, then implemented, audited and iterated with AI coding assistants. The architecture discipline — module decomposition, concurrency contracts, event-loop boundaries — is mine; the code generation is delegated and rigorously reviewed. The strict orchestration contract between the Qt event loop and the isolated PowerShell modules — *one dispatch call in, one verdict out, no shared state* — is what keeps both layers decoupled and independently testable.

---

## 🖥️ The Live Operations Console

The execution engine is built for **observability and control**, not fire-and-forget:

- **⏱️ True real-time streaming** — the worker reads the PowerShell pipe in binary chunks through an incremental UTF-8 decoder, so output appears the instant the backend writes it. Every task opens with a timestamped start banner inside the first second.
- **📈 In-place progress** — bare carriage-return rewrites (the progress idiom of `sfc`, `DISM` and `winget`) update a **single console line**, exactly like a real terminal, instead of flooding the log with thousands of percentage lines.
- **🛑 Global kill switch** — a danger-styled **■ Stop Task** button is present for the whole run. One click terminates the entire process tree: the child is assigned to a Windows **Job Object** (`KILL_ON_JOB_CLOSE`) at spawn, with `taskkill /T /F` as the fallback, so even orphaned grandchildren die. It reports a distinct *stopped* outcome — never a fake error.
- **🚦 Execution state pill** — a compact `IDLE / RUNNING / SUCCESS / ERROR / STOPPED` chip mirrors engine state at a glance.
- **📊 Structured verdicts** — each task emits one `##PULSE##META|{…}` envelope (duration, dry-run and elevation flags, succeeded/failed/skipped counts) parsed into `TaskResult.meta`, alongside the human-readable verdict.
- **✅ Visual feedback** — the launching card glows while running, then flashes green or red; glass toasts carry the verdict text.

---

## ✨ Key Features

### 📦 Software Management
- **Curated `winget` catalogs** across four tabs — Browsers & Media, Development & Tools, Gaming Launchers, System Runtimes & Utilities — with a per-app checkbox selector, live search and **authentic full-colour vendor logos** — the real artwork, gradients and all, each centred at 20px in a uniform 36px well. 36 of the 37 bundled marks are full colour (Cursor's own brand cube is monochrome); six catalog apps have no authentic logo in any open licensed set and fall back to the app's own installed binary artwork, then to a neutral "no logo available" glyph. Nothing is ever invented
- **Update Center** — live audit of installed apps with per-app version deltas; update exactly what you tick
- **Microsoft Office Suite** deployment through the official ODT, driven by an in-app wizard
- **Startup Manager** — boot-impact audit with instant per-entry enable/disable
- **PATH Doctor** (`VerifyEnvironment`) — resolves Git, Python, Java, Node, VS Code, GCC and Ollama, repairs missing user-PATH entries from known install roots, and sets `JAVA_HOME` when resolvable — then **scans the whole system PATH** (both scopes, read from the registry) for dead and duplicate entries. Every finding is one scannable `[TAG] name -> path` line; the PATH scan reports and never removes, because a folder that is merely offline looks exactly like a dead one

### ⚡ System & Tweaks
- **Data-driven tweak engine** — every tweak (Dark Mode, Mouse Acceleration, Minimalist Taskbar, Classic Context Menu, Game Mode) is a *declarative catalog entry* processed by one generic function, not bespoke code
- **Pulse Power Plan** — unlocks the hidden Ultimate Performance scheme
- **Network & Ping Optimizer** plus **DNS Profiles** — per-adapter switching to Cloudflare / Quad9 / AdGuard, each with a real way back
- **Right-Click Menu Manager** — prune shell context-menu extensions through Windows' own official block list
- **Edge & OneDrive removal** with automatic pre-removal backups and one-click reinstall/restore. Edge's purge resolves its own versioned `setup.exe`, disables both EdgeUpdate services and unregisters its scheduled tasks before removing the payload — and when a build **refuses** (`setup.exe` exit 93, winget 1603) it escalates rather than retrying: Microsoft's own `AllowUninstall` EdgeUpdate policy, then the DMA-compliant EEA path, then forceful Appx de-registration *and* de-provisioning so it cannot return for the next user. Both the policy and the region are restored in a `finally`. OneDrive's evacuates **every** local sync root — the personal folder, each `OneDrive - <Organisation>` tenant folder, and any root redirected off the profile — into `%LOCALAPPDATA%\PULSE\Backups\OneDrive` before the uninstaller runs, treats "already not installed" as success, and clears the leftover `HKCU\Software\Microsoft\OneDrive` hive plus any folders left **empty** (never one that still holds a file). Each hub offers a third row that opens what was saved

### 🔧 Maintenance & Security
- **SFC + DISM automation** with in-place retry logic and live scan progress
- **Aggressive cache clean**, drive optimization, `Windows.old` removal, hibernation toggle
- **Storage Analyzer** — what is actually filling a drive
- **Driver backup** and missing-driver scan
- **Restore Point Browser** — every System Restore checkpoint on the machine, listed

### 🛡️ Privacy
- Bloatware removal, telemetry shutdown, Advertising ID and Activity History disablement — three granular, individually probeable actions. The old composite "Apply ALL Privacy Settings" card is gone: bundling is the job of the **Playbooks** below, which compose named steps a user can see, reorder and drop

### 📊 Reporting & Automation
- **Health & Drift Report** — read-only snapshot of applied-tweak drift, drives, restore-point status, startup load and system facts, exportable as a **self-contained HTML deliverable** (inline styles, no scripts, opens offline years later) or as diffable JSON
- **Ctrl+K command palette** — fuzzy search over every operation, with typo tolerance (a bounded Damerau-Levenshtein pass, so `cahce` finds Aggressive Cache Clean), **Arabic query support** (`تحديث`, `تنظيف`, `تسريع` reach the operations they name, with the alef/yeh/ta-marbuta forms and harakat normalised away), and English verb matching (`uninstall` finds Remove Bloatware)
- **Playbooks** — declarative machine baselines as JSON (*Gamer Rig Setup*, *Privacy Hardening*, *Post-Install Clean*), validated against the live catalog at load time, previewable under `-WhatIf`, and run one step at a time through the ordinary dispatcher
- **Activation Status** — read-only Windows & Office licence report (state, channel, expiry) in plain English; it reports only, and hands activation itself off to Windows' own settings page
- **Battery & Power Health** — wear level, cycle count, active power plan
- **Session log** at `%LOCALAPPDATA%\Pulse\logs\` (5 MB rotation, 5 archives), viewable in-app

### 🎛️ Experience
- **A static obsidian canvas** — one two-stop gradient (`#101216` → `#090A0B`), and nothing else. v10.5 froze the ambient field; v10.6 deleted it, along with its OpenGL renderer, its capability probe, its frame governor and the occlusion system that existed to make a moving background affordable. An idle window now paints nothing at all
- **Dual themes** (Premium Dark / Clean Light) with semantic per-module accent tokens that resolve differently per theme, so light mode clears its contrast floors
- **`Ctrl+K` command palette** over the whole catalog, plus a full keyboard layer (grid navigation, module jumps, filter, shortcut sheet)
- **Durable preferences** — theme, window geometry and drawer state survive restarts; per-task history powers each card's *"Ran 3d ago · ~2m"* caption and its `ACTION DUE` badge
- **Self-updater** ([utils/updater.py](src/utils/updater.py)) with SHA-256 verification and a silent-on-failure network policy, wired into the GUI via a background check on launch plus the sidebar footer's version label ("Check for updates" on click). Live from v10.4 onward: `tools/build_release.ps1` emits `SHA256SUMS` beside the installer, which is what the updater verifies a download against — see [Safety Model](#-safety-model).

---

## 🏗️ Architecture & Tech Stack

### Stack

| Concern | Choice | Notes |
|---|---|---|
| GUI framework | **PySide6 (Qt 6.6+)** | Frameless window with real DWM rounded corners (`DWMWCP_ROUND`) and native `WS_THICKFRAME` resize |
| GPU layer | **OpenGL 3.3 Core** via `QOpenGLWidget` | Full-screen-triangle shader; capability-probed at startup |
| Win32 integration | **`ctypes`** (no extra dependencies) | `WM_NCCALCSIZE` hit-testing, DWM attributes, Job Objects, registry/kernel32 system facts |
| Concurrency | **`QThread` + Signals** | Qt widgets are touched from the GUI thread only |
| Engine | **PowerShell 5.1+** | 19 numbered modules dot-sourced into one shared script scope |
| Package manager | **`winget`** (lazy-bootstrapped) | Chocolatey fallback inside the software engine |
| Persistence | **`QSettings`** → `HKCU\Software\HumamTaibeh\Pulse` | No file format to corrupt; every getter degrades to a default |
| Packaging | **PyInstaller (onedir)** + **Inno Setup 6** | Installs to Program Files; `uac_admin` on — the manifest requests `requireAdministrator`, so every launch elevates (v10.7). See [Building](#-building). |
| Update channel | **GitHub Releases API** | Digest-verified, unauthenticated, failure-silent; called from `src/frontend/main.py` (background check on launch) and `SelfUpdateDialog` (download/verify/apply). Still needs a release that publishes `SHA256SUMS` to be end-to-end usable. |
| CI | **GitHub Actions** on `windows-latest` | Parse → lint → Pester → pytest |
| Tests | **pytest 8** (840) + **Pester 5+** (126) | 80 tests marked `native` need a real window station |

### Data flow

```
   ┌────────────────────────────────────────────────────────────────┐
   │  GUI THREAD  (PySide6)                                         │
   │    menu_structure.py ──renders──▶ main.py ──▶ GlassCard        │
   │                                      │                         │
   │                                 request_task(name)             │
   └──────────────────────────────────────┼─────────────────────────┘
                                          ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  WORKER QThread  (utils/helpers.PowerShellTask)                │
   │    spawn powershell.exe ──▶ assign to Job Object               │
   │    core.ps1 -Task <name> [-AppIds …] [-WhatIf]                 │
   │    binary pipe read ──▶ incremental UTF-8 ──▶ Signal(line)     │
   └──────────────────────────────────────┼─────────────────────────┘
                                          ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  ENGINE  (src/backend/core.ps1 → 30-GuiDispatcher.ps1)         │
   │    switch ($TaskName) { … } ──▶ module function                │
   │    stdout:  live output                                        │
   │             ##PULSE##DATA|{json}      optional payload         │
   │             ##PULSE##META|{json}      metrics envelope         │
   │             ##PULSE##SUCCESS|message  ── exactly one verdict   │
   │             ##PULSE##ERROR|message   ──┘                       │
   └────────────────────────────────────────────────────────────────┘
```

### Design contracts

These are intended to be enforced by tests rather than by convention — coverage is real but not exhaustive:

- **`menu_structure.py` is the single source of truth.** Adding a button means adding *one dict* — `main.py` renders whatever is defined there, with zero UI code changes.
- **Every GUI task maps 1:1** to a `switch ($TaskName)` case in `Invoke-GuiTask`, which must emit exactly one sentinel-prefixed verdict line. The `##PULSE##` sentinel exists so no external tool's stray output can spoof a result; the frontend scans **backwards** for it.
- **One terminal signal per task.** The worker emits exactly one of `finished` / `failed` / `cancelled`. The kill switch and the timeout watchdog only terminate the process — the read loop owns the verdict, so the UI can never receive conflicting outcomes.
- **Tweaks are data, not code.** Each tweak declares its registry paths, on/off values and description; one generic engine function applies, snapshots and reverses all of them.
- **Read-only means read-only.** `11-StateProbe`, `12-HealthReport`, `13-Activation` and `14-Inspectors` mutate nothing — they run every time a report opens, so a mutating probe would change the very system it claims to describe.
- **The engine is never resolved from a user-writable directory.** `resources.py` splits `bundled_roots()` from `user_roots()`: playbooks are user-extensible, `core.ps1` is not. Elevation anchors (`powershell.exe`, system binaries) are absolute paths, never `$env:PATH` lookups.
- **The shell is unconditionally opaque.** No `WA_TranslucentBackground`, ever; shell gradient tokens must be solid hex. Pinned by pixel-level and Win32-level tests.
- **Frame cost is a budget.** Whole-window render is held under a 12 ms median ceiling by `tests/test_shell_budget.py`.
- **No `QGraphicsEffect` in steady state, no `setStyleSheet()` inside timers.** Glows are painted directly in `paintEvent`; QSS is rebuilt once per theme switch.

---

## 📁 Repository Structure

```
Pulse/
│
├── VERSION                          # 10.3.0 — the ONE version fact everything quotes
├── start.bat                        # Dev launcher: layout check + venv + GUI
├── main.spec                        # PyInstaller recipe (onedir PULSE bundle)
├── pytest.ini                       # Test config and the `native` marker
├── requirements.txt                 # Runtime dependency (PySide6)
├── requirements-dev.txt             # + PyInstaller, pytest
├── PSScriptAnalyzerSettings.psd1    # Lint rule set; every exclusion carries a rationale
│
├── src/
│   ├── backend/
│   │   ├── core.ps1                 # Thin orchestrator: params, elevation, module loader
│   │   └── modules/                 # 19 single-responsibility engine modules
│   │       ├── 00-Foundation.ps1        # logging, console vocabulary, dry-run primitives
│   │       ├── 01-Catalogs.ps1          # ALL data: tweaks, app catalogs, services, bloatware
│   │       ├── 02-Safety.ps1            # restore points, snapshots, backups, rollback
│   │       ├── 03-Environment.ps1       # winget bootstrap, PATH doctor, JAVA_HOME
│   │       ├── 04-SoftwareEngine.ps1    # Smart-Deploy, winget/choco engine, version audit
│   │       ├── 05-Startup.ps1           # startup discovery + per-entry manager
│   │       ├── 06-Tweaks.ps1            # tweak engine, power, network, Edge/OneDrive removal
│   │       ├── 07-Maintenance.ps1       # SFC/DISM, cache clean, disks, services optimizer
│   │       ├── 08-Privacy.ps1           # bloatware, telemetry, ad ID, activity history
│   │       ├── 09-SystemInfo.ps1        # read-only system insight
│   │       ├── 10-Office.ps1            # Office Deployment Tool suite
│   │       ├── 11-StateProbe.ps1        # read-only "is this tweak applied?" probe
│   │       ├── 12-HealthReport.ps1      # read-only health + configuration-drift snapshot
│   │       ├── 13-Activation.ps1        # read-only Windows/Office licence report
│   │       ├── 14-Inspectors.ps1        # power health, restore points, storage scan
│   │       ├── 15-Network.ps1           # per-adapter DNS profile switching
│   │       ├── 16-ContextMenu.ps1       # shell context-menu extension manager
│   │       ├── 20-Menus.ps1             # the full interactive terminal experience
│   │       └── 30-GuiDispatcher.ps1     # Invoke-GuiTask — the GUI task contract
│   │
│   ├── frontend/
│   │   ├── main.py                  # Orchestration ONLY: pages, navigation, task pipeline
│   │   ├── menu_structure.py        # SINGLE SOURCE OF TRUTH for the menu hierarchy
│   │   ├── theme.py                 # Dual-theme tokens, QSS factories, DWM glass
│   │   ├── widgets.py               # TitleBar, GlassCard, LiveConsole, StatePill, dialogs
│   │   ├── animations.py            # Glow, shimmer, cascade, page fade (60 fps doctrine)
│   │   ├── playbooks.py             # Playbook loading, validation and step runner
│   │   └── health_report.py         # Pure HTML/JSON rendering of the drift report
│   │
│   └── utils/
│       ├── helpers.py               # PowerShellTask engine: streaming reader, Job Object
│       ├── resources.py             # Where Pulse's files live (bundled vs user roots)
│       ├── prefs.py                 # QSettings-backed preferences + per-task history
│       ├── updater.py               # Digest-verified self-updater (no Qt, pure logic)
│       ├── appicons.py              # Vendor icon resolution for catalog rows
│       └── version.py               # Reads VERSION; the only version accessor
│
├── playbooks/                       # Shipped JSON baselines (user-extensible)
│   ├── gamer-rig.json
│   ├── privacy-hardening.json
│   └── post-install-clean.json
│
├── assets/
│   ├── pulse.ico                    # App and installer icon
│   └── appicons/                    # Bundled vendor SVG marks
│
├── installer/
│   └── pulse.iss                    # Inno Setup 6 script (stable AppId, Program Files)
│
├── tools/
│   ├── build_release.ps1            # Bundle + Setup + SHA256SUMS in one command
│   └── fetch_app_icons.py           # Build-time vendor icon fetcher
│
├── tests/                           # 1,303 collected pytest tests
│   ├── conftest.py                  # Preference isolation + `native` auto-skip
│   ├── backend/                     # 180 Pester tests (safety, startup, hardening, …)
│   └── test_*.py                    # contract, rendering, updater, playbooks, budgets …
│
└── .github/workflows/
    ├── ci.yml                       # Four gates, ordered cheapest-first
    └── release.yml                  # Tag -> build -> verify -> publish
```

---

## 🔑 Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| **Windows** | 10 / 11, 64-bit | The app and the engine are both Windows-only by design |
| **PowerShell** | 5.1 | Ships with Windows; nothing to install |
| **Python** | 3.10+ | GUI / development mode only — not needed for the installed `.exe` |
| **Administrator** | every launch | The manifest requests `requireAdministrator`, so Windows prompts before Pulse starts; ~24 tasks touch HKLM, services or machine state |
| **Inno Setup 6** | build only | Required by `tools\build_release.ps1` unless `-SkipInstaller` |

---

## ⚙️ Environment & Configuration

**Pulse ships no `.env` file and requires none.** It is a desktop application with no service credentials, no API keys and no database connection string — every runtime path is resolved from the executable's own location or from Windows' own environment (`%LOCALAPPDATA%`, `%SystemRoot%`, `%USERPROFILE%`). Configuration that *is* available comes in two forms.

### Optional environment variables

Set these only to override a decision Pulse makes for itself.

| Variable | Values | Purpose |
|---|---|---|
| `QT_QPA_PLATFORM` | `offscreen` | Standard Qt switch. Under it the 100 `native` tests auto-skip — useful for headless experimentation, **not** supported for CI (see [Testing](#-testing--continuous-integration)). |

```powershell
# Example: force the raster field on a machine with a flaky GL driver
python src\frontend\main.py
```

### Runtime state locations

| What | Where |
|---|---|
| Preferences (theme, geometry, drawer, task history) | `HKCU\Software\HumamTaibeh\Pulse` |
| Tweak & service snapshots (the rollback data) | `HKCU\Software\Pulse` |
| Session log (5 MB rotation, 5 archives) | `%LOCALAPPDATA%\Pulse\logs\Pulse_Log.txt` |
| Edge / OneDrive backups | `%USERPROFILE%\Desktop\Pulse_*Backup` |
| User-supplied playbooks | `playbooks\` beside the executable, or the repo's `playbooks/` |

> **Extending playbooks:** drop `workstation-standard.json` into the `playbooks` folder next to `PULSE.exe`. It is validated against the live task catalog at load time and appears in the Playbooks dialog on the next launch — no rebuild, no Python.

---

## 🚀 Quick Start

### Option A — Install the release *(recommended for use)*

Download the latest `PULSE_Setup_v<version>.exe` and `SHA256SUMS` from
[Releases](https://github.com/Humam-Taibeh/Pulse/releases), verify the installer, then run it.

```powershell
# the digest must match the line in SHA256SUMS for the version you downloaded
Get-FileHash .\PULSE_Setup_v<version>.exe -Algorithm SHA256
Get-Content .\SHA256SUMS
```

> **Pulse is still a beta and its releases are unsigned**, so Windows
> SmartScreen and Smart App Control will flag it — expected, not a defect;
> see [SmartScreen and Smart App Control](#-smartscreen-and-smart-app-control)
> below for what that means and how to get past it safely. A published
> checksum proves the file was not altered in transit; it does not prove
> who built it — that's what code signing (a [roadmap](#-roadmap) item)
> is for.
>
> The release is built by `tools/build_release.ps1` and ships
> `SHA256SUMS`, so the in-app updater can verify a download before
> executing it — a release published without that file is one the
> updater declines, silently and correctly.

### Option B — Run from source *(development)*

**1 · Clone**

```powershell
git clone https://github.com/Humam-Taibeh/Pulse.git
cd Pulse
```

**2 · Create the environment**

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt     # runtime + PyInstaller + pytest
```

For runtime only, `pip install -r requirements.txt` is enough.

**3 · Launch**

```powershell
.\start.bat
```

`start.bat` validates the project layout, activates `.venv`, and opens the GUI. Pick a category in the sidebar, click a card, confirm — progress streams into the live console, and **■ Stop Task** stays one click away for the whole run. Press `Ctrl+K` to search every app, tweak and tool.

Equivalent, without the launcher:

```powershell
python src\frontend\main.py
```

### Option C — Terminal mode *(no Python at all)*

The PowerShell core is a complete application on its own:

```powershell
powershell -ExecutionPolicy Bypass -File src\backend\core.ps1
```

It self-elevates if needed and presents the full hierarchical menu in the terminal. Add `-WhatIf` for a complete dry-run simulation that changes nothing.

---

## 🛡️ SmartScreen and Smart App Control

Pulse's releases are **unsigned** — no certificate chained to a Certificate
Authority in Microsoft's trust program stands behind them yet (tracked in
the [roadmap](#-roadmap): code signing via Azure Trusted Signing). Windows
weighs two things when it decides whether to trust a downloaded executable:
whether it is signed by a CA it recognises, and how much download/run
history that exact file or publisher has built up. An unsigned beta with a
small user base starts at zero on both counts — that is what you are
seeing, not a sign that the download is unsafe. **Verify the checksum
first, regardless of which of the two systems below you're dealing with**
(see [Option A](#-quick-start) above); it is the trust anchor Pulse can
actually offer today.

### Windows SmartScreen ("Windows protected your PC")

The dialog Explorer shows when you double-click a freshly downloaded,
unrecognized `.exe`. It has an override:

1. Click **More info**.
2. Click **Run anyway**.

If your machine doesn't offer that second button, its SmartScreen policy
has been configured to *block* rather than *warn* — common on
managed/corporate devices — and only whoever manages that policy can
change it; there's nothing to click around on the machine itself.

### Smart App Control

A stricter, OS-wide enforcement mode (Windows 11 22H2 and later) — not the
same feature as SmartScreen above, and it behaves very differently:

- **There is no per-app allow-list.** Smart App Control doesn't offer a
  "trust this program" exception the way SmartScreen or Defender's
  exclusion list do. An app it doesn't recognise is blocked, full stop.
- **It is a one-way switch.** Once you turn Smart App Control **Off**, the
  only way to turn it back **On** is a clean install of Windows — this is
  Microsoft's own documented behaviour, not a Pulse limitation. Don't
  disable it on a whim.
- To check its state or turn it off: **Windows Security → App & browser
  control → Smart App Control settings.** A machine that already has it
  **Off** was never going to see this problem, and one running it in
  **Evaluation** mode is still deciding based on the same signing/reputation
  signals described above.

Until Pulse ships signed with a certificate Smart App Control's evaluation
recognises, running it on a machine with Smart App Control **On** means
either turning that setting off (and accepting you can't easily turn it
back on) or waiting for a signed release.

### What "signing infrastructure" in this repo does and does not mean

`tools/build_release.ps1` can Authenticode-sign both release artifacts
(`-SignThumbprint`), and `tools/create_dev_signing_cert.ps1` can generate a
certificate to test that pipeline with. **Using that on a local,
self-signed certificate does not stop these warnings for anyone who
downloads Pulse** — a self-signed certificate chains to nothing Windows
already trusts, so it changes nothing for a machine that hasn't been
individually told to trust that exact certificate. It exists so that the
day a real certificate is available, plugging in its thumbprint is the
only change needed — not so a build can be represented as "signed" when
what backs the signature is a certificate nobody but its own creator has
any reason to trust.

---

## 📦 Building

One command produces all three release artifacts:

```powershell
.venv\Scripts\activate
.\tools\build_release.ps1
```

| Output | Description |
|---|---|
| `dist\PULSE\` | The onedir bundle — portable, no Python required on the target |
| `dist\PULSE_Setup_v<VERSION>.exe` | The Inno Setup wizard |
| `dist\SHA256SUMS` | Digests for both |

**`SHA256SUMS` is not optional.** `verify()` in `src/utils/updater.py` refuses to hand a downloaded installer to the installer step unless its digest appears in this file — that refusal is a loud `UpdateError`, not a silent one. As of v10.3 the GUI does call `check()`/`download()`/`verify()` (see [Safety Model](#-safety-model)), so a release published without `SHA256SUMS` now fails loudly in `SelfUpdateDialog`'s error page — rather than harmlessly, as it did before the GUI had a call site at all. Publish it with every release.

> **v10.4.0 is the first release this pipeline actually produced.** Its assets are `PULSE_Setup_v10.4.0.exe` (~35 MB) and `SHA256SUMS`, both emitted by `tools\build_release.ps1` from the repo's `VERSION` file. Anything published before it — notably v10.3's single ~46 MB `Pulse.exe` — was not built this way and ships no checksum file, so the in-app updater declines it. Older assets remain on [Releases](https://github.com/Humam-Taibeh/Pulse/releases) as history, not as a description of this section.

Everything is stamped from the repo's `VERSION` file: the GUI imports it, PowerShell reads it, the PyInstaller spec writes it into the Windows version resource, Inno Setup preprocesses it into the output filename, and CI tags from it. Nothing computes the version; everything quotes it.

```powershell
.\tools\build_release.ps1 -SkipInstaller   # bundle only (no Inno Setup required)
.\tools\build_release.ps1 -KeepBuild       # skip the clean; faster, riskier
pyinstaller main.spec                      # the bundle step on its own
```

> **Why onedir, and why Program Files.** One-file self-extraction to `%TEMP%` is slower and a well-known AV heuristic (UPX is disabled in the spec for the same reason). Installing to Program Files is a security decision, and it matters *more* now that every launch elevates: if the executable lived in a user-writable directory, any process running as the user could replace it and the next launch would run that code with an Administrator token — a straight privilege-escalation path. Program Files is not writable without elevation, which closes it.

---

## 🧰 Available Scripts & Commands

| Command | What it does |
|---|---|
| `start.bat` | Dev launcher — layout check, venv activation, GUI start |
| `python src\frontend\main.py` | Start the GUI directly |
| `powershell -File src\backend\core.ps1` | Interactive terminal engine (self-elevating) |

### Where Pulse keeps its files

Everything Pulse writes for itself lives under one root, and nothing is
written to the Desktop:

```
%LOCALAPPDATA%\PULSE\
├── Logs\            Pulse_Log.txt + up to 5 rotated archives (5 MB each)
├── Backups\
│   ├── Edge\        version + Preferences/Bookmarks/Favicons before a purge
│   ├── OneDrive\    local files rescued before OneDrive is removed
│   ├── Startup\     shortcuts moved aside by the Startup Manager
│   └── Drivers\     third-party driver packages exported by Driver Backup
└── updates\         installers the self-updater has downloaded
```

Through v10.6 the four backup folders sat on the **Desktop** (`Pulse_EdgeBackup`
and friends) — the log had already moved to LocalAppData in v6.1 because a
OneDrive-synced Desktop turned every appended line into sync traffic, and the
backups had the same problem plus the clutter. The engine **moves** any legacy
folder it finds into the root on start, including the pre-rebrand `HTCore_*`
names, so an upgraded machine keeps its snapshots.

| `powershell -File src\backend\core.ps1 -WhatIf` | Full dry-run of the terminal engine — zero mutations |
| `powershell -File src\backend\core.ps1 -Task <Name>` | Run one task headlessly; emits a single verdict line |
| `python -m pytest tests` | The full 1,303-test regression suite |
| `python -m pytest tests -m native` | Only the tests needing a real window station |
| `python -m pytest tests -m "not native"` | The headless-safe subset |
| `Invoke-Pester -Path tests\backend` | The 101-test Pester suite (backup/restore, startup, hardening) |
| `Invoke-ScriptAnalyzer -Path src\backend -Recurse -Settings .\PSScriptAnalyzerSettings.psd1` | Lint the engine — must report **zero** findings |
| `pyinstaller main.spec` | Build `dist\PULSE\` |
| `.\tools\build_release.ps1` | Build bundle + installer + `SHA256SUMS` |
| `python tools\fetch_app_icons.py` | Refresh the bundled vendor icon marks |
| `iscc installer\pulse.iss` | Compile the installer by hand |

---

## 🔌 Task API & Core Modules

### The dispatch contract

The GUI always invokes `core.ps1` — never a module file directly.

```powershell
core.ps1 -Task <Name>                                    # dispatch one task
core.ps1 -Task InstallCatalogApps -AppIds "Git.Git,Valve.Steam"
core.ps1 -Task StartupDisableItem -StartupItemId "<id>"  # own param: ids may contain commas
core.ps1 -Task InstallOfficeODT -OfficeSetupPath <p> -OfficeConfigPath <p>
core.ps1 -Task StorageScan -ScanPath "D:\"
core.ps1 -Task NetworkProfiles -AdapterName "Ethernet" -DnsProfile cloudflare
core.ps1 -Task <Name> -WhatIf                            # dry-run: report, never mutate
```

**Response protocol** — every task writes free-form output to stdout, then closes with:

| Sentinel line | Cardinality | Meaning |
|---|---|---|
| `##PULSE##SUCCESS\|message` | exactly one of these two | The verdict. Single source of truth for the outcome. |
| `##PULSE##ERROR\|message` | ↑ | |
| `##PULSE##DATA\|{json}` | 0..n *(last wins)* | Structured payload — version audits, reports, scan results |
| `##PULSE##META\|{json}` | exactly one | Metrics envelope: task, duration, dry-run/elevation flags, succeeded/failed/skipped counts. Emitted from `finally`, so every exit path is measured. |

An unknown task name is answered with `##PULSE##ERROR|Unknown task: <name>`. A task requiring elevation in an unelevated session is refused *before* it starts — reachable when the engine is driven directly, since the packaged GUI always runs elevated.

### Task catalog

44 task identifiers are reachable from the UI: 37 dispatch to the engine, and 7 prefixed with `@` are handled locally by the GUI.

| Domain | Tasks |
|---|---|
| **Software** | `InstallCatalogApps` · `InstallOfficeODT` · `UpdateSelectedApps` · `StartupReport` · `VerifyEnvironment` · `RemoveBloatware` · `RemoveEdge` · `RestoreEdge` · `RemoveOneDrive` · `RestoreOneDrive` |
| **Tweaks & UI** | `DarkMode` · `MinimalistTaskbar` · `ClassicContextMenu` · `GameMode` · `DisableMouseAccel` · `UltimatePowerPlan` · `ContextMenuScan` |
| **Network** | `NetworkOptimization` · `NetworkProfiles` |
| **Privacy** | `DisableTelemetry` · `DisableAdvertisingID` · `DisableActivityHistory` |
| **Maintenance** | `RunSFC` · `CleanCache` · `OptimizeDrives` · `RemoveWindowsOld` · `DisableHibernation` · `EnableHibernation` · `DriverBackup` · `DriverScan` |
| **Storage & info** | `DriveSpaceReport` · `StorageScan` · `SystemInfo` |
| **Recovery** | `CreateRestorePoint` · `ResetTweaks` · `RestoreServices` |
| **Local (`@`)** | `@playbooks` · `@health_report` · `@activation` · `@power_health` · `@restore_points` · `@open_log` · `@open_onedrive_backup` · `@open_edge_backup` |

Local `@` actions open a Pulse surface instead of spawning a task through the main pipeline; the dialogs that need engine data (`HealthReport`, `ActivationStatus`, the inspectors) run their own `PowerShellTask`. `tests/test_contract.py` fails if any GUI task lacks a dispatcher case, or if any dispatcher case becomes unreachable without being allow-listed.

### Playbook schema

```jsonc
{
  "id": "gamer-rig",
  "name": "Gamer Rig Setup",
  "icon": "🎮",
  "description": "Latency, power and input tuned for play, with the launchers installed last.",
  "steps": [
    { "task": "CreateRestorePoint", "note": "Always first — everything after this is undoable." },
    { "task": "GameMode",           "note": "Game Mode on, background recording off." },
    { "task": "InstallCatalogApps", "note": "Launchers plus the matching GPU suite.",
      "app_ids": ["Valve.Steam", "EpicGames.EpicGamesLauncher"],
      "optional": true }
  ]
}
```

A step is *just* a task name, dispatched through exactly the same contract a card click uses — so a playbook can never reach anything the GUI could not already reach, and no step needs a dispatcher case of its own. A failed **required** step halts the run; a step marked `"optional": true` records the failure and continues. Every playbook is validated against the live catalog at load time, and an invalid one is *reported*, never silently skipped: a technician who mistyped a task name needs to know before they walk away, not after.

---

## 🔐 Safety Model

Destructive paths are guarded by up to four independent layers:

1. **🛟 System Restore Point** — `Pulse Restore Point`, created automatically before the first system change of any session, across *all* modules.
2. **📸 Registry snapshots** — every tweak captures its original value under `HKCU:\Software\Pulse` before modification, with **first-write-wins** semantics and a `__NOTSET__` sentinel for values that did not previously exist. *Reset All Tweaks* restores your real prior settings, not Microsoft's defaults.
3. **⚙️ Service snapshots** — startup type *and* running state are captured before any service is disabled, restorable via *Restore Services*.
4. **📜 Session log** — every action is appended to `%LOCALAPPDATA%\Pulse\logs\Pulse_Log.txt`, size-rotated, and viewable from inside the app.

Additionally: removing Edge backs up its Preferences/Bookmarks/Favicons first; removing OneDrive offers to back up your local OneDrive folder to the Desktop; every DNS profile ships with its counterpart restore; and `-WhatIf` gives a full simulation across every module — including the external tools (`winget`, `powercfg`, `sfc`, `robocopy`) that PowerShell's own `ShouldProcess` can never reach.

**Kill-switch semantics.** Stopping a task is a *hard* process-tree termination — deliberate, immediate and honest. Interrupted work (a half-finished scan, a partial install batch) is left incomplete but recoverable: re-run the task. Nothing bypasses the snapshot layers above. The success path deliberately **disarms** kill-on-close first, because several tasks end by launching something for the user (`cleanmgr.exe`, a restarted `explorer.exe`).

**Supply-chain posture — as designed.** The updater's `verify()` treats HTTPS as authenticating the *host*, not the *artifact*: it downloads the release's `SHA256SUMS`, looks up the asset by filename, hashes the downloaded file and refuses to hand it to the installer unless the digests match. All three failure modes — no `SHA256SUMS` asset, an unreachable checksum file, an asset absent from the list — raise fatally (a loud `UpdateError`) and delete the download, rather than falling back to "verify what we can". Every *check* failure, by contrast — offline, DNS, timeout, HTTP 403 from GitHub's unauthenticated rate limit, malformed JSON — resolves silently, because Pulse routinely runs on machines that are broken, freshly imaged or deliberately offline, and an update check that demanded a dismissal would be a worse bug than never checking.

> **Wired into the GUI as of v10.3.** `src/frontend/main.py` runs a silent background check (`updater.check()`) shortly after launch, and the sidebar footer's version label is the manual "Check for updates" call site — click it to check on demand, or to reopen a result the background check already found. Either path opens `widgets.SelfUpdateDialog`, which owns `download()` and `verify()` on its own worker thread and hands a verified installer back to `main.py`, which calls `apply()` and quits. The unrelated Update Center still only audits *installed third-party apps* via `winget`, not Pulse itself.
>
> v10.4 closes that gap: the release is built by `tools\build_release.ps1`, which emits `SHA256SUMS` beside the installer, so `verify()` has something to check a download against and the dialog can install rather than erroring. Releases published before v10.4 carry no checksum file, and the updater still refuses them — correctly. See [Roadmap](#-roadmap).

**Upgrading from v5.x** (*Humam Windows Architecture*): Pulse migrates your safety net automatically — legacy registry snapshots are copied to the `HKCU:\Software\Pulse` root on first run, and restores fall back to the old `HTCore_*` artifact names when the new ones do not exist yet.

---

## 🧪 Testing & Continuous Integration

```powershell
python -m pytest tests -v          # 1,303 collected tests
Invoke-Pester -Path tests\backend  # 180 tests
```

The pytest suite covers the engine contract, rendering and paint caches, the frame budget, window state and native Win32 behaviour, dialogs, packaging, the updater, playbooks, history and resources. **80 tests are marked `native`** — they hit-test the non-client area, query DWM and pump real Win32 messages, none of which exist on Qt's offscreen platform. `conftest.py` skips them automatically if the suite ever lands somewhere headless.

The Pester suite does **real registry I/O**, deliberately — mocking the registry would test the mock, and invariants like first-write-wins and the `__NOTSET__` sentinel only bite against a real hive. Everything is confined to a throwaway key and removed in `AfterAll`; nothing needs elevation.

CI runs four gates on `windows-latest`, ordered cheapest-first so an obvious break reports in seconds:

| # | Gate | Budget |
|---|---|---|
| 1 | Every `.ps1` tokenizes | ~10 s |
| 2 | PSScriptAnalyzer — **zero** findings against the tuned rule set | ~40 s |
| 3 | Pester — the backup/restore engine actually executes | ~1 m |
| 4 | pytest — with a **floor assertion** that the native tests really ran | ~3 m |

Gate 4's floor exists because a runner that lost its desktop session would still report green while silently testing a quarter of the suite. It fails loudly instead.

Both workflows run on `windows-latest` and nothing else. There is no Linux
fallback to be had: the GUI tests pump real Win32 messages and the engine
calls DWM, the registry and `winget`.

### Releases are automated

[`release.yml`](.github/workflows/release.yml) is tag-driven. Pushing a
`vX.Y.Z` tag is the entire release procedure:

```powershell
git tag -a v10.10.0 -m "Pulse v10.10.0"
git push origin v10.10.0
```

| Step | What it does |
|---|---|
| **Gates** | Calls `ci.yml` as a reusable workflow — the *same* four gates, not a second copy. A commit CI rejects cannot be released. |
| **Tag ↔ `VERSION`** | Refuses a tag that disagrees with the `VERSION` file. The installer is named from the file and the updater compares against the tag, so a mismatch ships an update that reinstalls itself forever. |
| **Build** | Runs [`tools/build_release.ps1`](tools/build_release.ps1) — the same script a developer runs locally, not a reimplementation of it. |
| **Verify** | Re-hashes the installer and checks `SHA256SUMS` actually lists *that* filename with *that* digest. |
| **Publish** | Creates the GitHub release with the installer and `SHA256SUMS` attached, and the release body taken from this version's `CHANGELOG.md` section. |

The verify step exists because the failure it catches is invisible from the
releases page: `updater.py` declines any download whose digest is not
published in `SHA256SUMS`, so a release missing that file — or carrying one
that names a different filename — looks perfectly fine to a human and reads
as "no update available" on every installed copy. Every release before v10.4
had exactly that defect.

Releases are **never** marked as GitHub prereleases, regardless of the beta
language above: `updater.py` reads `/releases/latest` on its primary path,
and that endpoint excludes prereleases.

`workflow_dispatch` runs the identical build **without** publishing, so the
pipeline can be exercised from a branch before a tag is cut.

### † A note on the GPU measurement

The ambient-field figures this section used to qualify — ~10.9% of one core on the GPU path against 40.2% for raster at 60 fps — described a background that no longer exists. v10.6 deleted the field, both renderers and the occlusion system built to afford them; the canvas is now a static gradient and costs nothing to leave on screen. The numbers are kept in the v10.4.0 changelog entry as the record of why the GPU path was built, not as a claim about anything that ships.

**There is no committed benchmark harness, and these numbers are not reproducible from this repository.** No hardware, OS or driver version was recorded. The performance test that *is* in the suite ([test_shell_budget.py](tests/test_shell_budget.py)) measures per-paint cost in milliseconds against a frame budget — a different metric, which does not corroborate a CPU-percentage claim. Treat the ratio as directionally indicative of the author's hardware, not as a benchmark. The same caveat applies to the "0.000 card repaints per frame" figure in that docstring.

---

## 🗺️ Roadmap

The full phased plan lives in [ROADMAP.md](ROADMAP.md), including *settled decisions* recorded so they are not re-litigated. Highlights:

**Shipped**

- [x] Data-driven tweak engine and `-WhatIf` dry-run across every module
- [x] PySide6 shell with dual themes, opaque canvas, native DWM corners and a full keyboard layer
- [x] Real-time streaming console with in-place progress and a Job-Object-backed kill switch
- [x] Read-only state probe → `APPLIED` chips; per-task history → last-run and duration captions
- [x] Structured `##PULSE##META` verdict payloads
- [x] Playbooks — declarative, validated, previewable machine baselines
- [x] Health & Drift Report with a self-contained HTML export
- [x] Ambient field deleted — the canvas is one static gradient (v10.6)
- [x] Onedir bundle and Inno Setup installer (see [Building](#-building) for a caveat on the current release asset)
- [x] CI: parse, lint at zero, Pester, pytest with a coverage floor
- [x] Self-updater wired into the GUI — background check on launch, sidebar-footer manual check, `SelfUpdateDialog` owning download/verify/apply (still needs `SHA256SUMS` published on a release to be usable end-to-end — see [Safety Model](#-safety-model))
- [x] Elapsed time in the state pill (`RUNNING · 02:41`) and console polish — colorized `SUCCESS` / `ERROR` / `[DRY-RUN]` lines, auto-scroll that pauses while you're scrolled up *(v10.9.4)*
- [x] Sheets follow the window through every state — a minimize no longer strands an open dialog on the desktop, and a scale change re-fits and re-renders it for the display it is actually on *(v10.10.0)*
- [x] Every catalog row carries authentic brand artwork — the icon fetcher was silently pairing a full-colour manifest record with a monochrome silhouette, so eight marks shipped as black blocks *(v10.10.0)*
- [x] Windows Update driver synchronization — the chipset, audio, Wi-Fi and Bluetooth drivers a fresh install leaves as "Unknown device" *(v10.10.0)*

**Planned**

- [ ] **Code signing** via Azure Trusted Signing — the `.exe` *and* the `.ps1` modules, so `AllSigned` execution policies can run the engine. The signing *infrastructure* (`tools/build_release.ps1 -SignThumbprint`) is in place; what's missing is a certificate from a CA Microsoft's trust program recognises — see [SmartScreen and Smart App Control](#-smartscreen-and-smart-app-control)
- [ ] **CI release builds** with published `SHA256SUMS`, a pre-release VirusTotal scan, and proactive AV false-positive submission
- [ ] A *remaining*-time estimate on top of the state pill's elapsed clock, derived from the duration history
- [ ] **Scheduled unattended maintenance** via Task Scheduler, summarized on the next launch
- [ ] **Persistent runspace** — one long-lived PowerShell host fed queued tasks, eliminating the ~400 ms per-step module-load cost a playbook pays today

---

## 🤝 Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, commit conventions, and the architectural contracts you must preserve — particularly the dispatcher contract, the thread-safety rules and the rendering doctrine, which are covered by tests, though not exhaustively.

Security issues go through [SECURITY.md](SECURITY.md), not the public tracker.

---

## ⚠️ Disclaimer

This tool modifies registry keys, services and installed software. While every reversible action is snapshotted and a restore point is created automatically, **always ensure you have an independent backup before running on a production machine.** The software is provided *as is*, without warranty of any kind — see [LICENSE](LICENSE).

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for the full text.

---

<div align="center">

**Crafted with precision by [Humam Taibeh](https://github.com/Humam-Taibeh)**

*If Pulse saved you an afternoon of Windows setup, consider giving it a ⭐*

</div>

---

[⚡ Back to Main Profile](https://github.com/Humam-Taibeh)
