#Requires -Version 5.1
<#
.SYNOPSIS
    PULSE - Modular Enterprise Edition (v6.0)
    Windows Deployment & Optimization Framework - by Humam Taibeh
    -----------------------------------------------------------
    THIS FILE IS A THIN ORCHESTRATOR. All logic lives in the cohesive
    modules under .\modules\, dot-sourced below into ONE shared script
    scope (so every $Script:/$global: variable behaves exactly as it did
    in the pre-4.0 monolith).

    MODULE MAP (load order = numeric prefix):
      00-Foundation.ps1     logging, console UI, prompts, retry, registry
                            read helper, DRY-RUN primitives (-WhatIf engine)
      01-Catalogs.ps1       ALL data: tweaks, app/runtime catalogs, fallback
                            URLs, services, bloatware, dev-tool catalog
      02-Safety.ps1         restore points, tweak/service snapshots,
                            Edge/OneDrive backups, rollback, reset-all
      03-Environment.ps1    winget bootstrap, PATH management,
                            Verify-Environment (dev tools + system PATH scan)
      04-SoftwareEngine.ps1 Smart-Deploy, winget/choco engine, versions,
                            hardware matching, category processor
      05-Startup.ps1        startup program discovery + manager
      06-Tweaks.ps1         data-driven tweak engine + system tweaks,
                            network/power optimization, Edge/OneDrive removal
      07-Maintenance.ps1    SFC/DISM, cache clean, disks, services optimizer
      08-Privacy.ps1        bloatware, telemetry, advertising ID, activity
      09-SystemInfo.ps1     read-only system insight
      10-Office.ps1         Office Deployment Tool suite
      11-StateProbe.ps1     read-only "is this tweak applied?" probe
      12-HealthReport.ps1   read-only health + configuration-drift snapshot
      13-Activation.ps1     read-only Windows/Office licence status report
      20-Menus.ps1          the entire interactive console experience
      30-GuiDispatcher.ps1  Invoke-GuiTask - the PySide6 frontend contract

    INVOCATION MODES:
      core.ps1                      interactive luxury console menu (elevates)
      core.ps1 -Task <name>         GUI task mode: non-interactive, emits one
                                    final ##PULSE##SUCCESS|... or
                                    ##PULSE##ERROR|... verdict line
      core.ps1 -Task <n> -AppIds a,b   narrows a bulk deploy to ticked apps
      core.ps1 -Task StartupDisableItem -StartupItemId <id>
                                     toggles ONE startup entry (its own
                                     parameter, not -AppIds - the id may
                                     legitimately contain commas)
      core.ps1 -Task InstallOfficeODT -OfficeSetupPath <p> -OfficeConfigPath <p>
                                     runs the Office Deployment Tool wizard's
                                     resolved setup.exe / configuration.xml
                                     runs an installer the Tool Install
                                     Wizard's Path C pointed at
      core.ps1 [...] -WhatIf        DRY-RUN: full simulation, zero mutations

    CHANGELOG v4.0 (Modular Architecture Release):
      - Monolith decomposed into 13 single-responsibility modules; core.ps1
        is now only parameters + elevation + module loader + entry routing.
      - NEW Verify-Environment (task: VerifyEnvironment): audits Git, Python,
        Java, VS Code, GCC, Node and Ollama; auto-repairs missing user-PATH
        entries from known install roots and sets JAVA_HOME when resolvable.
        It also SCANS THE WHOLE SYSTEM PATH (both scopes, read from the
        registry) and reports dead and duplicate entries as [TAG] findings -
        reported only, never removed. See the header block in
        03-Environment.ps1 for why the two halves share one card.
      - NEW -WhatIf dry-run mode across every module: registry writes,
        service changes, deletions, installs and external tools are reported
        as "[WHATIF] ..." lines instead of executing; cache clean measures
        the space it would reclaim. GUI tasks report "[DRY-RUN]" results.
      - All v3.3/v3.4 contracts preserved verbatim: Invoke-GuiTask dispatcher
        (SUCCESS|/ERROR| final line), $Script:NonInteractive safety, tweak &
        service snapshotting, lazy winget bootstrap, data-driven catalogs.
#>

# ============================================================
#  PARAMETERS (MUST BE FIRST)
#  NOTE: $WhatIf is a plain switch by design - no [CmdletBinding()] /
#  SupportsShouldProcess, because the dry-run engine (Test-DryRun in
#  00-Foundation.ps1) must also govern external tools (winget, powercfg,
#  sfc, robocopy...) that ShouldProcess can never reach.
# ============================================================
param(
    [string]$Task,
    [string]$AppIds,
    # ONE startup item, verbatim. Deliberately not folded into $AppIds:
    # that parameter is a COMMA-SEPARATED LIST, and a startup id is
    # "Type|||RegPath|||Name" carrying an arbitrary registry value name.
    # Any name containing a comma ("Acme, Inc. Updater") was split into
    # fragments that matched nothing, so the item could not be toggled at
    # all and the GUI reported a stale list instead of the real cause.
    [string]$StartupItemId,
    [string]$OfficeSetupPath,
    [string]$OfficeConfigPath,
    # Storage Analyzer's scan root ("D:\", "C:\Users\me\Downloads"). Its
    # OWN parameter for the same reason $StartupItemId is: $AppIds is a
    # comma-separated LIST, and a Windows path may legitimately contain a
    # comma ("C:\Program Files\Acme, Inc\") which would be split into
    # fragments that match no directory.
    [string]$ScanPath,
    # DNS switcher (15-Network.ps1). The adapter is addressed by NAME, not
    # by interface index: indexes are reassigned as adapters come and go,
    # so a stale one from the GUI could point at a different connection
    # entirely. Its own parameter for the same reason $ScanPath is —
    # an adapter name can contain a comma ("Ethernet 2, vEthernet").
    [string]$AdapterName,
    [string]$DnsProfile,
    [switch]$WhatIf
)

# ============================================================
#  ELEVATION (only runs if $Task is empty - i.e., clicked manually)
# ============================================================
if (-not $Task) {
    if ($MyInvocation.InvocationName -ne '.') {
        if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            $ElevArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
            if ($WhatIf) { $ElevArgs += " -WhatIf" }
            # ABSOLUTE PATH, and the one place in Pulse that cannot use
            # Get-SystemBinary (00-Foundation.ps1): this block re-launches
            # the script ELEVATED, and it runs before the module loader,
            # so the helper does not exist yet. Bare `powershell` here
            # would resolve through $env:PATH - which the unelevated user
            # controls via HKCU - and hand a planted powershell.exe the
            # administrator token the UAC prompt was granting to Pulse.
            # This is the single highest-value path anchor in the codebase
            # and is therefore written out in full rather than shared.
            $PSExe = Join-Path ([System.Environment]::GetFolderPath('System')) `
                'WindowsPowerShell\v1.0\powershell.exe'
            Start-Process -FilePath $PSExe -ArgumentList $ElevArgs -Verb RunAs
            Exit
        }
    }
}

# UTF-8 output, unconditionally: Windows consoles default to the OEM code
# page (437 on US-English installs, others elsewhere), which renders every
# box-drawing character and glyph this file prints (=,|,check,cross - see
# 00-Foundation.ps1's $Script:Box*/Check/Cross) as mangled question marks
# and garbage - not a cosmetic quirk, a genuinely broken-looking console.
# The GUI's spawned subprocess already sets this (helpers.PowerShellTask
# prepends the same line); this covers the interactive console, which
# never got it and was the real "chaotic UI" culprit, not color choices.
# ============================================================
#  EVERY CIM QUERY FAILS RATHER THAN BLOCKS
# ============================================================
# Pulse is a repair tool, so its users are disproportionately on machines
# that are already unwell - and a degraded or corrupt WMI repository is
# one of the commonest ways a Windows box is unwell. Against a sick
# repository Get-CimInstance does not error, it BLOCKS, and every system
# probe in this engine is a Get-CimInstance.
#
# There was never a path to an infinite hang: the GUI's PowerShellTask
# arms a watchdog that kills the whole process tree at the task's
# deadline. But that deadline is 90s for the applied-state probe and 900s
# by default, so on such a machine the user watches a spinner for a
# minute and a half before being told anything - and Get-PulseSystemInfo
# queries CIM at STARTUP, which puts it in front of every task rather
# than only the reporting ones. A per-operation bound turns that into a
# fast failure the surrounding -ErrorAction/try-catch already reports.
#
# ONE DEFAULT RATHER THAN NINETEEN EDITS: this covers every existing call
# and every one added later, which a call-site sweep cannot promise, and
# it cannot mis-edit the several invocations that use backtick
# continuations. $Global: because the modules below are dot-sourced and
# their functions run at whatever depth a task calls them from - a
# script-scoped default would cover this file's own lines and quietly not
# theirs. Set BEFORE the dot-source loop so a query run while a module
# loads is covered too.
#
# 30s is chosen from measurement in both directions: a 1s bound made
# Get-CimInstance Win32_Processor throw CimException on a HEALTHY machine,
# so legitimate queries are not instant and the number has to clear real
# work by a wide margin - while staying far under the smallest task
# watchdog, or it would not be a fail-fast at all. An individual call that
# needs longer can still pass -OperationTimeoutSec explicitly; an explicit
# argument always beats the default.
$Global:PSDefaultParameterValues['Get-CimInstance:OperationTimeoutSec'] = 30

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # Rare, but [Console]::OutputEncoding throws when stdout isn't a real
    # console handle (e.g. certain redirected/piped launch contexts) -
    # box-drawing glyphs render as '?' in that case, but that's cosmetic;
    # crashing the whole script over an encoding preference is not
    # acceptable this early, before any module has even loaded.
}

# Console styling only makes sense when a human is looking at the console.
# In GUI task mode stdout is a pipe and the console is hidden - skip it.
if (-not $Task) {
    $Host.UI.RawUI.BackgroundColor = "Black"
    $Host.UI.RawUI.ForegroundColor = "Gray"
    Clear-Host
}
$ErrorActionPreference = "Stop"

# ============================================================
#  VERSION — read, never declared
# ============================================================
# The one copy lives in `VERSION` at the repo root; the GUI, the installer,
# the PyInstaller spec and the updater all quote the same file. See
# src/utils/version.py for why this stopped being a literal.
#
# ONE RELATIVE PATH COVERS BOTH LAYOUTS. From a checkout this script is
# <repo>/src/backend/core.ps1, so "..\..\VERSION" is <repo>\VERSION; inside
# a PyInstaller bundle it is <_MEIPASS>/src/backend/core.ps1 and the same
# path is <_MEIPASS>\VERSION, which is exactly where main.spec places it.
#
# The fallback is not defensive tidiness: $ErrorActionPreference is "Stop"
# two lines above, so an unreadable file here would abort the engine before
# a single module loaded — over a string used in a banner. Being
# approximately right about a version beats refusing to run.
$Script:ScriptVersion = "10.10.0"
try {
    $VersionFile = Join-Path $PSScriptRoot "..\..\VERSION"
    if (Test-Path -LiteralPath $VersionFile) {
        $VersionText = (Get-Content -LiteralPath $VersionFile -TotalCount 1 -ErrorAction Stop).Trim()
        if ($VersionText) { $Script:ScriptVersion = $VersionText }
    }
} catch {
    # keep the fallback — see above
}

# When invoked with -Task (i.e. from the GUI), there is no console attached
# for Read-Host to block on. Ask-User, Invoke-WithRetry, Smart-Deploy and
# Open-FallbackUrl all check this flag so they never wait on input that can
# never arrive and never pop windows (browser/Store) mid-silent-run.
# Set BEFORE the modules load so even module top-level code is governed.
$Script:NonInteractive = [bool]$Task

# -WhatIf dry-run flag, honored by every mutation primitive in the modules.
$Script:DryRun = [bool]$WhatIf

# ============================================================
#  MODULE LOADER
#  Dot-sourcing (not Import-Module) is deliberate: every module executes
#  in THIS script scope, preserving the monolith's $Script: semantics.
#  Numeric prefixes define a deterministic load order; functions resolve
#  at call time, so only data/top-level statements depend on it.
# ============================================================
$Script:ModuleRoot = Join-Path $PSScriptRoot "modules"
$LoadingModule = "(none)"
$IntegrityError = $null
try {
    $ModuleFiles = @(Get-ChildItem -Path $Script:ModuleRoot -Filter "*.ps1" -File -ErrorAction Stop | Sort-Object Name)
    if ($ModuleFiles.Count -eq 0) { throw "No backend modules found in '$Script:ModuleRoot'." }

    # ============================================================
    #  INTEGRITY GATE — only code the build produced gets executed
    # ============================================================
    # THE LOADER ABOVE TAKES WHATEVER IT FINDS. It globs *.ps1 and
    # dot-sources each one into THIS scope, under an Administrator token
    # (main.spec's uac_admin) with -ExecutionPolicy Bypass. So an attacker
    # never needed to modify a file to get elevated execution here -
    # dropping a new one into the folder was enough, and it would run on
    # the next launch.
    #
    # On an INSTALLED build that is already closed, and deliberately:
    # Program Files is not user-writable, which installer/pulse.iss
    # documents as exactly this defence. The exposure is the other
    # channels - the README's supported "run from source" mode, which
    # lives in a user-writable directory, and the portable ZIP planned as
    # a secondary distribution.
    #
    # THE MANIFEST IS OPTIONAL BY DESIGN. It is a build artifact written
    # by tools/build_release.ps1 and gitignored, so a developer checkout
    # has none and runs unverified. Refusing there would make this a guard
    # people work around rather than one they keep; absence means
    # "unverified", a mismatch means "wrong".
    #
    # THREE FAILURES, and only the first is tampering in the obvious sense:
    #   MODIFIED  a listed module whose bytes changed
    #   ADDED     a .ps1 the manifest does not list - THE ACTUAL ATTACK,
    #             and the reason this checks the directory against the
    #             manifest rather than only walking the manifest
    #   MISSING   a listed module that is absent: a partial install, and
    #             half an engine is no safer to run than a tampered one
    #
    # Cost: 20.2 ms median to hash all 19 modules (599 KB), measured -
    # about 2% of the ~1s spawn this already pays per task.
    $IntegrityError = $null
    $ManifestPath = Join-Path $Script:ModuleRoot "MANIFEST.sha256"
    if (Test-Path -LiteralPath $ManifestPath) {
        $LoadingModule = "MANIFEST.sha256"
        $Expected = @{}
        foreach ($Line in @(Get-Content -LiteralPath $ManifestPath -ErrorAction Stop)) {
            $Trimmed = $Line.Trim()
            if (-not $Trimmed) { continue }
            # "<64 hex>  <filename>" - sha256sum's format, the same one
            # SHA256SUMS uses so there is one shape to recognise.
            if ($Trimmed -notmatch '^([0-9a-fA-F]{64})\s+(.+)$') {
                $IntegrityError = "the module manifest is corrupt (unreadable line: '$Trimmed')."; throw $IntegrityError
            }
            $Expected[$Matches[2].Trim()] = $Matches[1].ToLowerInvariant()
        }
        # A manifest that parses to nothing is corrupt, not permissive: an
        # emptied file must never be a way to switch the gate off.
        if ($Expected.Count -eq 0) {
            $IntegrityError = "the module manifest is present but lists no modules."; throw $IntegrityError
        }

        foreach ($ModuleFile in $ModuleFiles) {
            if (-not $Expected.ContainsKey($ModuleFile.Name)) {
                $IntegrityError = "'$($ModuleFile.Name)' is not in the module manifest. The engine will not load code this build did not produce."; throw $IntegrityError
            }
        }
        # HASHED THROUGH .NET RATHER THAN Get-FileHash, and that is not a
        # style preference. Get-FileHash lives in a module that PowerShell
        # resolves by AUTOLOADING, which walks $env:PSModulePath - so this
        # gate's own hashing primitive was only reachable if an
        # environment variable happened to point somewhere usable. On a
        # GitHub runner it does not: the engine is spawned as a Windows
        # PowerShell 5.1 child of a pwsh step, inherits that step's
        # PSModulePath, and Get-FileHash stops resolving. The gate then
        # refused to start with "Backend module 'MANIFEST.sha256' failed
        # to load: The term 'Get-FileHash' is not recognized" - naming a
        # manifest that was perfectly intact, over modules that were
        # perfectly intact.
        #
        # It failed CLOSED, so nothing was ever bypassable this way. But a
        # security control that any process able to set an environment
        # variable can convert into a hard refusal to start is a denial of
        # service on the app, and it made the check depend on machine
        # state it has no reason to care about. SHA256 comes from
        # mscorlib: no module, no PSModulePath, no autoloader.
        $Sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            foreach ($Name in @($Expected.Keys)) {
                $Candidate = Join-Path $Script:ModuleRoot $Name
                if (-not (Test-Path -LiteralPath $Candidate)) {
                    $IntegrityError = "'$Name' is listed in the module manifest but missing from this install."; throw $IntegrityError
                }
                # Streamed rather than ReadAllBytes: this runs on every task
                # spawn, and there is no reason to hold a module in memory
                # twice to hash it.
                $Stream = [System.IO.File]::OpenRead($Candidate)
                try {
                    $ActualHash = [System.BitConverter]::ToString($Sha256.ComputeHash($Stream)).Replace('-', '').ToLowerInvariant()
                }
                finally {
                    $Stream.Dispose()
                }
                if ($ActualHash -ne $Expected[$Name]) {
                    $IntegrityError = "'$Name' does not match the module manifest - it has been modified since this build was made."; throw $IntegrityError
                }
            }
        }
        finally {
            $Sha256.Dispose()
        }
        $LoadingModule = "(none)"
    }

    foreach ($ModuleFile in $ModuleFiles) {
        $LoadingModule = $ModuleFile.Name
        . $ModuleFile.FullName
    }
} catch {
    # A broken module must never produce silence: honor the GUI contract
    # even when the backend itself cannot come up.
    # An integrity refusal is not a module that failed to EXECUTE, and
    # saying so would send the reader looking for a syntax error in a file
    # that is fine. The distinction is the actionable part: one means
    # "reinstall", the other means "this build is not what it claims".
    if ($IntegrityError) {
        $LoadError = "Engine integrity check failed: $IntegrityError"
    } else {
        $LoadError = "Backend module '$LoadingModule' failed to load: $($_.Exception.Message)"
    }
    if ($Task) {
        Write-Output "##PULSE##ERROR|$LoadError"
    } else {
        Write-Host ""
        Write-Host "   FATAL: $LoadError" -ForegroundColor Red
        Write-Host "   Verify that src\backend\modules\ is complete and intact." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
    Exit 1
}

# Global last-resort trap - installed after the modules so it can use the
# foundation's log path and glyphs.
trap {
    Write-Host ""
    Write-Host "   $Script:Cross  UNEXPECTED ERROR: $($_.Exception.Message)" -ForegroundColor Red
    try {
        Add-Content -Path $Script:LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] UNCAUGHT: $($_.Exception.Message)" -ErrorAction SilentlyContinue
    } catch {}
    Start-Sleep -Seconds 2
    continue
}

# ============================================================
#  TASK ENGINE (GUI mode: executed only if -Task was provided)
# ============================================================
if ($Task) {
    # Belt-and-braces: the flag is already set above, but nothing below may
    # ever block on a console that does not exist.
    $Script:NonInteractive = $true

    if ($Script:DryRun) {
        Write-Host "   [WHATIF] Dry-run mode: simulating '$Task' - no system changes will be made." -ForegroundColor DarkYellow
        Write-Log "WHATIF: GUI task '$Task' started in dry-run mode."
    }

    Invoke-GuiTask -TaskName $Task
    Exit
}

# ============================================================
#  TERMINAL MENU (only if run directly, no params)
# ============================================================
if ($MyInvocation.InvocationName -ne '.') {
    Show-EpicIntro
    do {
        Show-MainMenu
        $Selection = Read-Choice -Prompt "   Select Module [0-6]" -Valid @('0','1','2','3','4','5','6')
        switch ($Selection) {
            "1" { Show-SoftwareManagementMenu }
            "2" { Show-SystemOptimizationMenu }
            "3" { Show-MaintenanceRepairMenu }
            "4" { Show-PrivacySecurityMenu }
            "5" { Show-InformationUtilitiesMenu }
            "6" { Show-SafetyRecoveryMenu }
            "0" {
                if (Ask-User "Exit Pulse" "Closes the tool. Any pending restart will still be offered first.") {
                    Write-Host ""
                    Write-Host "   📊 Session Summary: $($Script:SessionSuccessCount) successes, $($Script:SessionFailCount) failures." -ForegroundColor Cyan
                    Show-RestartReminder
                    Write-Host "   Thank you for using PULSE!" -ForegroundColor Yellow
                    Write-Host "   Exiting in 3 seconds..." -ForegroundColor DarkGray
                    Start-Sleep -Seconds 3
                    Exit
                }
            }
            default {
                Write-Warn "Invalid selection."
                Start-Sleep -Seconds 1
            }
        }
    } while ($true)
}
