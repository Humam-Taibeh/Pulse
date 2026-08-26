[⚡ Back to Main Profile](https://github.com/Humam-Taibeh)

<div align="center">

<img src="assets/pulse.ico" width="88" alt="Pulse" />

# ⚡ PULSE

**A Windows orchestration toolkit — a data-driven PowerShell engine wrapped in a GPU-accelerated, glass-morphism PySide6 command center, with a real-time operations console, declarative playbooks, and a global kill switch.**

> ### 🧪 Beta software
> **v10.3 is a pre-release.** It is unsigned, has had no third-party security review, and modifies the registry, services and installed software on the machine it runs on. The safety layers described below are real and tested, but they are not a substitute for your own backup. Run it on a machine you can afford to restore.

[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white)](#-prerequisites)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](#-prerequisites)
[![PowerShell](https://img.shields.io/badge/powershell-5.1%2B-5391FE?logo=powershell&logoColor=white)](#-prerequisites)
[![GUI](https://img.shields.io/badge/GUI-PySide6%20(Qt%206)-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Release](https://img.shields.io/badge/release-v10.3%20beta-blueviolet)](CHANGELOG.md)
[![Tests](https://img.shields.io/badge/tests-713%20pytest%20%2B%20101%20Pester-success)](#-testing--continuous-integration)
[![CI](https://img.shields.io/badge/CI-windows--latest-2088FF?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
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
| 🖥️ **Frontend** | Python 3.10+ · PySide6 (Qt 6) · OpenGL 3.3 | Frameless glass shell, dual themes, 60 fps ambient field, real-time streaming console, global kill switch, command palette, toasts |
| ⚙️ **Backend** | PowerShell 5.1+ — 19 modules, ~10k lines | Data-driven engine for deployment, tweaks, maintenance, privacy, recovery and read-only reporting |

**The GUI never touches the system itself.** Every card dispatches a *named task* to `core.ps1` on a background `QThread`; the engine executes it, streams progress to the UI as it happens, and closes with exactly one machine-parseable verdict line. The same engine also runs **fully standalone** as a self-elevating terminal application with a hierarchical menu — no Python required.

> **Two different "module" counts, both correct.** The release notes describe a **4-module core architecture**; this README counts **19 backend modules**. They are not in conflict — they count different layers. The **4** are the top-level modules a *user* navigates in the sidebar: Software Management, System & Tweaks, Maintenance & Security, and Utilities & Tools (defined as the four top-level entries in [menu_structure.py](src/frontend/menu_structure.py), each with its own semantic accent token). The **19** are the numbered PowerShell engine files under [src/backend/modules/](src/backend/modules/) that those four surfaces dispatch into — `00-Foundation` through `30-GuiDispatcher`. One user-facing module is served by many engine files: *Maintenance & Security*, for instance, draws on `02-Safety`, `07-Maintenance`, `08-Privacy` and `14-Inspectors`.

Every module follows the same lifecycle:

> **preview → confirm → snapshot → apply → log**

### Why it's different

- **Little is guessed.** Card state (`APPLIED` chips, the Health & Drift report) comes from a strictly read-only probe that queries the live system — not a cache the GUI could disagree with reality about.
- **Designed to be recoverable.** A restore point, per-tweak registry snapshots and per-service state snapshots are captured *before* the first mutation of a session. *Reset All Tweaks* restores **your** prior values, not Microsoft's defaults.
- **Nothing is opaque.** Every action streams live, ends with a verdict plus a structured metrics envelope, and is appended to a rotated session log you can open from inside the app.
- **Nothing downloaded is trusted.** The self-updater refuses to execute any installer whose SHA-256 is not published in the release's `SHA256SUMS` — which also means it declines a release that ships without one, as the v10.3 beta does. See [Safety Model](#-safety-model).

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
- **Curated `winget` catalogs** across four tabs — Browsers & Media, Development & Tools, Gaming Launchers, System Runtimes & Utilities — with a per-app checkbox selector, live search and **authentic vendor icons** (bundled SVG marks, falling back to the app's own installed binary artwork)
- **Update Center** — live audit of installed apps with per-app version deltas; update exactly what you tick
- **Microsoft Office Suite** deployment through the official ODT, driven by an in-app wizard
- **Startup Manager** — boot-impact audit with instant per-entry enable/disable
- **PATH Doctor** (`VerifyEnvironment`) — audits Git, Python, Java, Node, VS Code, GCC and Ollama, repairs missing user-PATH entries from known install roots, and sets `JAVA_HOME` when resolvable

### ⚡ System & Tweaks
- **Data-driven tweak engine** — every tweak (Dark Mode, Mouse Acceleration, Minimalist Taskbar, Classic Context Menu, Game Mode) is a *declarative catalog entry* processed by one generic function, not bespoke code
- **Pulse Power Plan** — unlocks the hidden Ultimate Performance scheme
- **Network & Ping Optimizer** plus **DNS Profiles** — per-adapter switching to Cloudflare / Quad9 / AdGuard, each with a real way back
- **Right-Click Menu Manager** — prune shell context-menu extensions through Windows' own official block list
- **Edge & OneDrive removal** with automatic pre-removal backups and one-click reinstall/restore

### 🔧 Maintenance & Security
- **SFC + DISM automation** with in-place retry logic and live scan progress
- **Aggressive cache clean**, drive optimization, `Windows.old` removal, hibernation toggle
- **Storage Analyzer** — what is actually filling a drive
- **Driver backup** and missing-driver scan
- **Restore Point Browser** — every System Restore checkpoint on the machine, listed

### 🛡️ Privacy
- Bloatware removal, telemetry shutdown, Advertising ID and Activity History disablement
- **One-click "Apply ALL Privacy Settings"** composite action

### 📊 Reporting & Automation
- **Health & Drift Report** — read-only snapshot of applied-tweak drift, drives, restore-point status, startup load and system facts, exportable as a **self-contained HTML deliverable** (inline styles, no scripts, opens offline years later) or as diffable JSON
- **Playbooks** — declarative machine baselines as JSON (*Gamer Rig Setup*, *Privacy Hardening*, *Post-Install Clean*), validated against the live catalog at load time, previewable under `-WhatIf`, and run one step at a time through the ordinary dispatcher
- **Activation Status** — read-only Windows & Office licence report (state, channel, expiry) in plain English; it reports only, and hands activation itself off to Windows' own settings page
- **Battery & Power Health** — wear level, cycle count, active power plan
- **Session log** at `%LOCALAPPDATA%\Pulse\logs\` (5 MB rotation, 5 archives), viewable in-app

### 🎛️ Experience
- **GPU-accelerated ambient field** — five parallax orbs and 126 depth-tiered stars rendered by an OpenGL 3.3 shader at 60 fps, measured at ~10.9% of one core against 40.2% for the equivalent raster path;<sup>[†](#-a-note-on-the-gpu-measurement)</sup> falls back to raster automatically on software-emulated GL
- **Dual themes** (Premium Dark / Clean Light) with semantic per-module accent tokens that resolve differently per theme, so light mode clears its contrast floors
- **`Ctrl+K` command palette** over the whole catalog, plus a full keyboard layer (grid navigation, module jumps, filter, shortcut sheet)
- **Durable preferences** — theme, window geometry and drawer state survive restarts; per-task history powers each card's *"Ran 3d ago · ~2m"* caption and its `ACTION DUE` badge
- **Self-updater** ([utils/updater.py](src/utils/updater.py)) with SHA-256 verification and a silent-on-failure network policy, wired into the GUI via a background check on launch plus the sidebar footer's version label ("Check for updates" on click). Still moot for the shipped v10.3 asset, since it publishes no `SHA256SUMS` — see [Safety Model](#-safety-model).

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
| Packaging | **PyInstaller (onedir)** + **Inno Setup 6** | Installs to Program Files; `uac_admin` deliberately off — elevation is per task. The current v10.3 release asset was **not** built by this pipeline — see [Building](#-building). |
| Update channel | **GitHub Releases API** | Digest-verified, unauthenticated, failure-silent; called from `src/frontend/main.py` (background check on launch) and `SelfUpdateDialog` (download/verify/apply). Still needs a release that publishes `SHA256SUMS` to be end-to-end usable. |
| CI | **GitHub Actions** on `windows-latest` | Parse → lint → Pester → pytest |
| Tests | **pytest 8** (713) + **Pester 5+** (101) | 100 tests marked `native` need a real window station |

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
│   │   ├── ambient_gl.py            # OpenGL 3.3 ambient field + capability probe
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
├── tests/                           # 713 collected pytest tests
│   ├── conftest.py                  # Preference isolation + `native` auto-skip
│   ├── backend/                     # 101 Pester tests (safety, startup, hardening, …)
│   └── test_*.py                    # contract, rendering, updater, playbooks, budgets …
│
└── .github/workflows/ci.yml         # Four gates, ordered cheapest-first
```

---

## 🔑 Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| **Windows** | 10 / 11, 64-bit | The app and the engine are both Windows-only by design |
| **PowerShell** | 5.1 | Ships with Windows; nothing to install |
| **Python** | 3.10+ | GUI / development mode only — not needed for the installed `.exe` |
| **GPU** | OpenGL 3.3 *(optional)* | Falls back to the raster ambient field automatically |
| **Administrator** | per task | Requested on demand; ~24 tasks touch HKLM, services or machine state |
| **Inno Setup 6** | build only | Required by `tools\build_release.ps1` unless `-SkipInstaller` |

---

## ⚙️ Environment & Configuration

**Pulse ships no `.env` file and requires none.** It is a desktop application with no service credentials, no API keys and no database connection string — every runtime path is resolved from the executable's own location or from Windows' own environment (`%LOCALAPPDATA%`, `%SystemRoot%`, `%USERPROFILE%`). Configuration that *is* available comes in two forms.

### Optional environment variables

Set these only to override a decision Pulse makes for itself.

| Variable | Values | Purpose |
|---|---|---|
| `PULSE_AMBIENT` | `auto` *(default)* · `gl` · `raster` | Forces the ambient field's render path. `raster` never uses the GPU; `gl` uses it even when the renderer looks software-emulated; `auto` lets the capability probe decide. |
| `QT_QPA_PLATFORM` | `offscreen` | Standard Qt switch. Under it the 100 `native` tests auto-skip — useful for headless experimentation, **not** supported for CI (see [Testing](#-testing--continuous-integration)). |

```powershell
# Example: force the raster field on a machine with a flaky GL driver
$env:PULSE_AMBIENT = 'raster'
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

Download `Pulse.exe` from [Releases](https://github.com/Humam-Taibeh/Pulse/releases) and run it.

> **v10.3 is a pre-release beta.** It ships as a single unsigned `Pulse.exe` with no checksum file and no code signature, so there is nothing to verify it against and SmartScreen will warn on first run. Record the digest yourself if you plan to redistribute it or check it later:
>
> ```powershell
> Get-FileHash .\Pulse.exe -Algorithm SHA256
> ```
>
> Signed builds and a published `SHA256SUMS` are [roadmap](#-roadmap) items, not current guarantees.

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

> **The live v10.3 release asset does not match this pipeline.** `Pulse.exe`, the file currently published on [Releases](https://github.com/Humam-Taibeh/Pulse/releases), is a single ~46 MB executable — not the onedir bundle plus Inno Setup wizard this section documents. Whatever produced it was not `tools\build_release.ps1`. Treat the instructions below as the intended, tested pipeline, not as a description of what shipped in v10.3.

Everything is stamped from the repo's `VERSION` file: the GUI imports it, PowerShell reads it, the PyInstaller spec writes it into the Windows version resource, Inno Setup preprocesses it into the output filename, and CI tags from it. Nothing computes the version; everything quotes it.

```powershell
.\tools\build_release.ps1 -SkipInstaller   # bundle only (no Inno Setup required)
.\tools\build_release.ps1 -KeepBuild       # skip the clean; faster, riskier
pyinstaller main.spec                      # the bundle step on its own
```

> **Why onedir, and why Program Files.** One-file self-extraction to `%TEMP%` is slower and a well-known AV heuristic (UPX is disabled in the spec for the same reason). Installing to Program Files is a security decision: Pulse elevates per task, so if the executable lived in a user-writable directory, any process running as the user could replace it and wait for the next elevated run — a straight privilege-escalation path.

---

## 🧰 Available Scripts & Commands

| Command | What it does |
|---|---|
| `start.bat` | Dev launcher — layout check, venv activation, GUI start |
| `python src\frontend\main.py` | Start the GUI directly |
| `powershell -File src\backend\core.ps1` | Interactive terminal engine (self-elevating) |
| `powershell -File src\backend\core.ps1 -WhatIf` | Full dry-run of the terminal engine — zero mutations |
| `powershell -File src\backend\core.ps1 -Task <Name>` | Run one task headlessly; emits a single verdict line |
| `python -m pytest tests` | The full 713-test regression suite |
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

An unknown task name is answered with `##PULSE##ERROR|Unknown task: <name>`. A task requiring elevation in an unelevated session is refused *before* it starts, with instructions for relaunching.

### Task catalog

44 task identifiers are reachable from the UI: 37 dispatch to the engine, and 7 prefixed with `@` are handled locally by the GUI.

| Domain | Tasks |
|---|---|
| **Software** | `InstallCatalogApps` · `InstallOfficeODT` · `UpdateSelectedApps` · `StartupReport` · `VerifyEnvironment` · `RemoveBloatware` · `RemoveEdge` · `RestoreEdge` · `RemoveOneDrive` · `RestoreOneDrive` |
| **Tweaks & UI** | `DarkMode` · `MinimalistTaskbar` · `ClassicContextMenu` · `GameMode` · `DisableMouseAccel` · `UltimatePowerPlan` · `ContextMenuScan` |
| **Network** | `NetworkOptimization` · `NetworkProfiles` |
| **Privacy** | `DisableTelemetry` · `DisableAdvertisingID` · `DisableActivityHistory` · `ApplyAllPrivacy` |
| **Maintenance** | `RunSFC` · `CleanCache` · `OptimizeDrives` · `RemoveWindowsOld` · `DisableHibernation` · `EnableHibernation` · `DriverBackup` · `DriverScan` |
| **Storage & info** | `DriveSpaceReport` · `StorageScan` · `SystemInfo` |
| **Recovery** | `CreateRestorePoint` · `ResetTweaks` · `RestoreServices` |
| **Local (`@`)** | `@playbooks` · `@health_report` · `@activation` · `@power_health` · `@restore_points` · `@open_log` · `@open_onedrive_backup` |

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
> This still does not make in-app updating usable end-to-end for the current release: the live v10.3 asset publishes no `SHA256SUMS` (see the note above), so `verify()` refuses it and the dialog surfaces a loud error rather than installing anything. Publishing `SHA256SUMS` with the next release is what closes that last gap. See [Roadmap](#-roadmap).

**Upgrading from v5.x** (*Humam Windows Architecture*): Pulse migrates your safety net automatically — legacy registry snapshots are copied to the `HKCU:\Software\Pulse` root on first run, and restores fall back to the old `HTCore_*` artifact names when the new ones do not exist yet.

---

## 🧪 Testing & Continuous Integration

```powershell
python -m pytest tests -v          # 713 collected tests
Invoke-Pester -Path tests\backend  # 101 tests
```

The pytest suite covers the engine contract, rendering and paint caches, the frame budget, window state and native Win32 behaviour, dialogs, packaging, the updater, playbooks, history, resources and the ambient field. **100 tests are marked `native`** — they hit-test the non-client area, query DWM and pump real Win32 messages, none of which exist on Qt's offscreen platform. `conftest.py` skips them automatically if the suite ever lands somewhere headless.

The Pester suite does **real registry I/O**, deliberately — mocking the registry would test the mock, and invariants like first-write-wins and the `__NOTSET__` sentinel only bite against a real hive. Everything is confined to a throwaway key and removed in `AfterAll`; nothing needs elevation.

CI runs four gates on `windows-latest`, ordered cheapest-first so an obvious break reports in seconds:

| # | Gate | Budget |
|---|---|---|
| 1 | Every `.ps1` tokenizes | ~10 s |
| 2 | PSScriptAnalyzer — **zero** findings against the tuned rule set | ~40 s |
| 3 | Pester — the backup/restore engine actually executes | ~1 m |
| 4 | pytest — with a **floor assertion** that the native tests really ran | ~3 m |

Gate 4's floor exists because a runner that lost its desktop session would still report green while silently testing a quarter of the suite. It fails loudly instead.

### † A note on the GPU measurement

The ambient-field figures quoted above — ~10.9% of one core on the GPU path against 40.2% for raster at 60 fps — are **a one-off measurement taken by the author on a single personal reference machine**, at 1300×860, in a real event loop with real idle between frames. They are recorded in the [ambient_gl.py](src/frontend/ambient_gl.py) module docstring, which also documents the discarded first attempt: a tight `update`/`processEvents` loop returned exactly 5.556 ms for every arm, i.e. it measured the vsync swap interval rather than any actual work.

**There is no committed benchmark harness, and these numbers are not reproducible from this repository.** No hardware, OS or driver version was recorded. The performance tests that *are* in the suite ([test_ambient.py](tests/test_ambient.py), [test_shell_budget.py](tests/test_shell_budget.py)) measure per-paint cost in milliseconds against a frame budget — a different metric, which does not corroborate a CPU-percentage claim. Treat the ratio as directionally indicative of the author's hardware, not as a benchmark. The same caveat applies to the "0.000 card repaints per frame" figure in that docstring.

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
- [x] GPU ambient field — 60 fps at a quarter of the raster cost
- [x] Onedir bundle and Inno Setup installer (see [Building](#-building) for a caveat on the current release asset)
- [x] CI: parse, lint at zero, Pester, pytest with a coverage floor
- [x] Self-updater wired into the GUI — background check on launch, sidebar-footer manual check, `SelfUpdateDialog` owning download/verify/apply (still needs `SHA256SUMS` published on a release to be usable end-to-end — see [Safety Model](#-safety-model))

**Planned**

- [ ] **Code signing** via Azure Trusted Signing — the `.exe` *and* the `.ps1` modules, so `AllSigned` execution policies can run the engine
- [ ] **CI release builds** with published `SHA256SUMS`, a pre-release VirusTotal scan, and proactive AV false-positive submission
- [ ] **Elapsed & remaining time in the state pill** (`RUNNING · 02:41`), derived from the duration history
- [ ] **Console polish** — colorized `SUCCESS` / `ERROR` / `[DRY-RUN]` lines, and auto-scroll that pauses while you are scrolled up
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
