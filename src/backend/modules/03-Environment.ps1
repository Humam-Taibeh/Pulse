#Requires -Version 5.1
<#
.SYNOPSIS
    03-Environment.ps1 - package-manager provisioning and developer
    PATH / environment-variable management.

.DESCRIPTION
    - Invoke-WingetBootstrap / Ensure-Winget: LAZY winget bootstrap (v3.4
      behavior preserved): startup does a fast offline probe only; the full
      network bootstrap runs on-demand the first time a software operation
      actually needs winget. Registry tweaks, repairs and privacy tasks never
      pay for network round-trips they don't use.
    - Add-ToUserPath / Register-DevPath: PATH registration for freshly
      installed developer tools (data: $Script:DevAppPaths).
    - Test-DevDependencySuggestion: post-install companion offers
      (data: $Script:DevDependencyMap).
    - Verify-Environment (ROADMAP v4.0): automatic PATH / environment
      variable doctor for developer tools, driven entirely by
      $Script:DevToolCatalog in 01-Catalogs.ps1. For every tool it either
      confirms it on PATH, repairs the user PATH from a known install
      location, or reports it missing with the winget id to install it.
      Fully -WhatIf aware.
#>

# ============================================================
#  PRE-FLIGHT WINGET BOOTSTRAP (silent, robust)
# ============================================================
function Invoke-WingetBootstrap {
    Write-Info "Winget not found - launching silent bootstrap from Microsoft CDN..."
    $tempDir = Join-Path $env:TEMP "WingetBootstrap_Pulse"
    New-Item -ItemType Directory -Path $tempDir -Force -ErrorAction SilentlyContinue | Out-Null

    $deps = @(
        @{ Name = "Microsoft.VCLibs.x64.14.00.Desktop.appx"; Url = "https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx" },
        @{ Name = "Microsoft.UI.Xaml.2.8.x64.appx";         Url = "https://aka.ms/Microsoft.UI.Xaml.2.8.x64.appx" }
    )

    foreach ($dep in $deps) {
        $dest = Join-Path $tempDir $dep.Name
        try {
            Write-Info "Downloading $($dep.Name)..."
            Invoke-WebRequest -Uri $dep.Url -OutFile $dest -UseBasicParsing -TimeoutSec 30 -ErrorAction Stop
        } catch {
            Write-Warn "Failed to download $($dep.Name) - bootstrap may fail."
        }
    }

    $latestJson = $null
    try {
        $latestJson = Invoke-RestMethod -Uri "https://api.github.com/repos/microsoft/winget-cli/releases/latest" -TimeoutSec 15 -ErrorAction Stop
    } catch {
        Write-ErrorX "Cannot reach winget-cli GitHub API. Bootstrap aborted."
        return $false
    }

    $asset = $latestJson.assets | Where-Object { $_.name -like "Microsoft.DesktopAppInstaller_*_8wekyb3d8bbwe.msixbundle" } | Select-Object -First 1
    if (-not $asset) {
        Write-ErrorX "MSIX bundle asset not found in latest release."
        return $false
    }

    # Split-Path -Leaf: $asset.name is a remote-supplied string, and the
    # -like mask above still admits separators ("Microsoft.DesktopAppInstaller_
    # ..\..\x_8wekyb3d8bbwe.msixbundle" matches it), so joining it raw would
    # let the response choose a write location outside $tempDir. Taking only
    # the leaf makes the destination structurally ours.
    $bundleName = Split-Path -Path $asset.name -Leaf
    $bundleUrl  = $asset.browser_download_url
    $bundleDest = Join-Path $tempDir $bundleName

    Write-Info "Downloading $bundleName ..."
    try {
        Invoke-WebRequest -Uri $bundleUrl -OutFile $bundleDest -UseBasicParsing -TimeoutSec 60 -ErrorAction Stop
    } catch {
        Write-ErrorX "Download of App Installer bundle failed."
        return $false
    }

    $allPkgs = Get-ChildItem -Path $tempDir -Filter *.appx | Sort-Object Name
    $allPkgs += Get-ChildItem -Path $tempDir -Filter *.msixbundle
    foreach ($pkg in $allPkgs) {
        try {
            Add-AppxPackage -Path $pkg.FullName -ErrorAction Stop
            Write-Success "Installed $($pkg.Name)"
        } catch {
            Write-Warn "Could not install $($pkg.Name) - may already be present."
        }
    }

    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Start-Sleep -Seconds 2

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Success "Winget bootstrapped successfully."
        return $true
    } else {
        Write-ErrorX "Winget still unavailable after bootstrap. Manual install required."
        return $false
    }
}

# LAZY BOOTSTRAP: startup does a fast, offline probe only. The full network
# bootstrap (Invoke-WingetBootstrap - CDN + GitHub downloads) runs on-demand
# via Ensure-Winget, the first time a software operation actually needs it.
$global:WingetAvailable = [bool](Get-Command winget -ErrorAction SilentlyContinue)
$Script:WingetBootstrapTried = $false
$Script:WingetPath = $null

function Get-WingetPath {
    <#
    .SYNOPSIS
        The absolute path to winget.exe, resolved once per process.

    .DESCRIPTION
        winget is the one external tool Pulse drives that is NOT a stock
        System32 binary - it ships as an app-execution alias, so
        Get-SystemBinary (00-Foundation.ps1) cannot anchor it and the
        engine was calling bare `winget` at seven separate sites. Each of
        those was an independent $env:PATH search, performed elevated,
        every time.

        Resolution now happens ONCE and the absolute path is reused, so
        the search cannot be won by something planted between two calls of
        the same operation, and the path Pulse logs is the path Pulse ran.

        HONEST LIMITATION, stated rather than papered over: the alias
        itself lives under %LOCALAPPDATA%\Microsoft\WindowsApps, which the
        unelevated user can write. Pinning the resolved path removes the
        repeated-search and time-of-check/time-of-use windows; it does not
        make a user-writable alias trustworthy. Only the package's real
        home under Program Files\WindowsApps is admin-only, and that
        directory's ACL blocks enumeration even for administrators, so it
        cannot be reliably discovered here. The name is therefore checked
        (it must actually be winget.exe) and the resolved path is logged.

        Returns $null when winget is genuinely absent - callers already
        gate on $global:WingetAvailable.
    #>
    if ($Script:WingetPath) { return $Script:WingetPath }

    $Command = @(Get-Command winget -CommandType Application -ErrorAction SilentlyContinue) |
        Select-Object -First 1
    if (-not $Command) { return $null }

    $Resolved = [string]$Command.Source
    if ([System.IO.Path]::GetFileName($Resolved) -ne 'winget.exe') {
        Write-Log "WARN: 'winget' on PATH resolved to '$Resolved', which is not winget.exe - refusing it."
        return $null
    }

    $Script:WingetPath = $Resolved
    Write-Log "winget resolved to '$Resolved'."
    return $Script:WingetPath
}

function Ensure-Winget {
    if ($global:WingetAvailable) { return $true }
    if ($Script:DryRun) {
        # Never download/install App Installer during a simulation.
        Write-Host "   [WHATIF] winget is missing - a real run would bootstrap 'App Installer' from the Microsoft CDN." -ForegroundColor DarkYellow
        Write-Log "WHATIF: winget missing - bootstrap skipped in dry-run."
        return $false
    }
    if ($Script:WingetBootstrapTried) { return $false }
    $Script:WingetBootstrapTried = $true
    Write-Log "Winget missing - attempting one-time silent bootstrap."
    $global:WingetAvailable = Invoke-WingetBootstrap
    if (-not $global:WingetAvailable) {
        Write-Warn "Winget could not be provisioned. Install 'App Installer' from the Microsoft Store or https://aka.ms/getwinget"
    }
    return $global:WingetAvailable
}

# Chocolatey is a third-party tool, so it gets the same treatment winget
# does (Get-WingetPath) rather than a System32 anchor: RESOLVE IT ONCE to
# an absolute path here, and invoke that path afterwards. Pulse runs
# elevated and a bare `choco` is a $env:PATH search - PATH is assembled
# from HKCU, which the unelevated user can write, so the bare form hands
# an attacker-placed choco.exe an administrator token. Resolving through
# Get-Command still consults PATH, but it does so ONCE, here, at load -
# not at each call site - and records what it found so the deploy path
# cannot be redirected between the check and the use.
$global:ChocolateyAvailable = $false
$global:ChocolateyPath = $null
$ChocoCommand = Get-Command choco -CommandType Application -ErrorAction SilentlyContinue |
                Select-Object -First 1
if ($ChocoCommand -and $ChocoCommand.Source) {
    $global:ChocolateyPath = $ChocoCommand.Source
    $global:ChocolateyAvailable = $true
}

# ============================================================
#  USER PATH MANAGEMENT
# ============================================================
function Add-ToUserPath {
    param([string]$Directory)
    if (-not (Test-Path $Directory)) { return $false }
    $Current = [Environment]::GetEnvironmentVariable("Path", "User")
    $Entries = @($Current -split ";" | Where-Object { $_ -ne "" })
    if ($Entries -contains $Directory) { return $true }
    if (Test-DryRun "Add '$Directory' to the user PATH") { return $true }
    $NewPath = (@($Entries) + $Directory) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    $env:Path = "$env:Path;$Directory"
    return $true
}

function Register-DevPath {
    param($AppId, $AppName)
    $Config = $Script:DevAppPaths[$AppId]
    if (-not $Config) { return }

    Write-Info "Resolving install path for $AppName ..."
    $SearchRoots = @(
        "$env:ProgramFiles", "${env:ProgramFiles(x86)}",
        "$env:LOCALAPPDATA\Programs", "C:\msys64"
    ) | Where-Object { $_ -and (Test-Path $_) }

    $Found = $null
    foreach ($Root in $SearchRoots) {
        $Hit = Get-ChildItem -Path $Root -Filter $Config.ExeName -Recurse -Depth 4 -ErrorAction SilentlyContinue -File | Select-Object -First 1
        if ($Hit) { $Found = $Hit.DirectoryName; break }
    }

    if ($Found) {
        if (Add-ToUserPath -Directory $Found) { Write-Success "$AppName added to PATH -> $Found" }
        if ($AppId -eq "MSYS2.MSYS2") { Add-ToUserPath -Directory "C:\msys64\mingw64\bin" | Out-Null }
    } else {
        Write-Warn "$AppName installed, but its executable could not be auto-resolved for PATH registration."
    }
}

# ============================================================
#  DEV DEPENDENCY SUGGESTIONS (post-install helper)
# ============================================================
function Test-DevDependencySuggestion {
    param([string]$AppId)
    if (-not $Script:DevDependencyMap.ContainsKey($AppId)) { return }
    $Dep = $Script:DevDependencyMap[$AppId]

    try {
        if (Get-Command $Dep.CommandName -ErrorAction SilentlyContinue) { return }
    } catch {
        return
    }

    Write-Host ""
    Write-Warn "$($Dep.FriendlyName) was not found on PATH. It's typically required to run or compile projects with the IDE you just installed."
    if (Ask-User "Install $($Dep.FriendlyName)" "Installs $($Dep.FriendlyName) so your new IDE can build and run code right away.") {
        if ($global:WingetAvailable) {
            $DepResult = Smart-Deploy -AppId $Dep.WingetId -AppName $Dep.FriendlyName -Bulk -BulkMethod 'auto'
            if ($DepResult.Status -ne 'Success') {
                Write-Info "Automatic install of $($Dep.FriendlyName) did not complete. Opening the official manual download page..."
                Open-UrlSafe -Url $Dep.Url
            }
        } else {
            Write-Info "Winget is unavailable. Opening the official manual download page for $($Dep.FriendlyName)..."
            Open-UrlSafe -Url $Dep.Url
        }
    } else {
        Write-Info "You can install $($Dep.FriendlyName) later from: $($Dep.Url)"
    }
}

function Open-UrlSafe {
    <# Opens a URL in the default browser - but NEVER during a GUI task
       (silent run) and never during -WhatIf; logs the link instead. #>
    param([Parameter(Mandatory = $true)][string]$Url)
    if ($Script:NonInteractive -or $Script:DryRun) {
        Write-Log "URL (not opened - silent/dry-run mode): $Url"
        return
    }
    try { Start-Process $Url } catch { Write-Warn "Could not open browser automatically. Visit: $Url" }
}

# ============================================================
#  VERIFY-ENVIRONMENT - the PATH doctor
#  NOTE: 'Verify' is not an approved PowerShell verb; the name is kept
#  because it is the roadmap's contract name (task: VerifyEnvironment).
#
#  IT IS A SCANNER, AND ITS OUTPUT IS THE DELIVERABLE. That is the whole
#  design constraint, and it is what the previous version got wrong in two
#  separate ways.
#
#  1. IT OPENED WITH SIX LINES OF PROSE explaining what PATH is. Those
#     lines were written once, printed on every run, and were the first
#     thing a returning user had to scroll past to reach the findings -
#     on a surface (the live console) whose visible height is about
#     fifteen lines. An explanation that cannot be dismissed is a
#     paragraph the user reads once and then fights forever; the card's
#     own description already says what the tool does, and the findings
#     below say it again in the only form that stays useful on the tenth
#     run.
#
#  2. EVERY FINDING WAS A SENTENCE. "Git: 'git' is ready to use - so any
#     terminal or IDE can run git for you" is friendly and unscannable:
#     thirty of them are a wall, and the two that matter are somewhere in
#     the middle of it. Findings are now [TAG] lines in a fixed column
#     (Write-TaggedLine, 00-Foundation.ps1), so the eye reads the left
#     edge and stops at the first thing that is not [OK].
#
#  AND IT SCANS THE WHOLE PATH, not only the seven catalogued tools. The
#  catalogue answers "can I type `git`?"; the PATH scan answers "is this
#  machine's PATH sane?" - dead folders left by uninstalled software,
#  duplicate entries, and the total length against the limit that
#  silently truncates it. Both questions are asked from the same card
#  because they have the same answer surface and the same audience.
# ============================================================

#: Reporting only, never repair. A dead or duplicated PATH entry is
#: REPORTED and left exactly where it is, and that asymmetry with the
#: tool pass (which does repair, by APPENDING) is deliberate: adding a
#: directory cannot break a machine, and removing one can. A stale-looking
#: entry may belong to software that is merely offline (a network share, an
#: unmounted volume, a tool installed per-user under another profile), and
#: an automatic prune has no way to tell those from real rubbish. So the
#: doctor tells the user what it found and leaves the edit to them.
$Script:PathScanIsReadOnly = $true

#: Where Windows silently truncates a PATH. The registry value type is
#: REG_EXPAND_SZ and the classic limit is 2047 characters for the expanded
#: string; past it, entries at the tail simply stop resolving with nothing
#: anywhere to say why. Worth one line of output on a machine that is
#: close to it, and worth a warning on one that is over.
$Script:PathLengthWarn = 1800

function Get-PathEntryReport {
    <#
    .SYNOPSIS
        Every entry in the machine and user PATH, with what is wrong with it.

    .DESCRIPTION
        Reads BOTH scopes from the registry rather than splitting
        $env:Path, because the process copy is a flattened snapshot taken
        at launch: it cannot tell machine from user, it carries anything a
        parent shell injected, and it does not show a change Pulse itself
        just made. The scopes are what the user can actually edit, so the
        scopes are what gets reported.

        Returns one object per entry: Scope, Raw (as written, variables
        unexpanded), Path (expanded), Exists, Valid, Duplicate.

        Duplicates are judged on the EXPANDED, trailing-slash-normalised
        path, so "%ProgramFiles%\Git\cmd" and "C:\Program Files\Git\cmd\"
        are correctly seen as the same directory - which is the form the
        duplicate almost always takes, since one of the two was written by
        an installer and the other by a person.

        A PATH ENTRY IS NOT A VALIDATED PATH. It is a string some installer
        or some person wrote into a semicolon-separated list, and nothing
        in Windows ever checks it: an entry containing '|', '<' or '>'
        sits there quite happily. Test-Path does check, and on one of those
        it does not return $false - it THROWS ArgumentException("Illegal
        characters in path"). With $ErrorActionPreference = "Stop" set in
        core.ps1 that terminated the whole scan, so the dispatcher's safety
        net reported "Illegal characters in path." as the task's verdict
        and the user got no report at all.

        That is the worst possible failure for this function: a malformed
        PATH entry is EXACTLY what the doctor exists to find, and finding
        one made it crash instead of print the line. So the probe is
        guarded and an entry that cannot even be tested becomes its own
        finding (Valid = $false), which is strictly more useful than the
        dead/duplicate verdict it used to abort before reaching.
    #>
    $Report = New-Object System.Collections.ArrayList
    $Seen   = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)

    foreach ($Scope in @("Machine", "User")) {
        $Value = [Environment]::GetEnvironmentVariable("Path", $Scope)
        if ([string]::IsNullOrWhiteSpace($Value)) { continue }
        foreach ($Raw in ($Value -split ";")) {
            $Trimmed = $Raw.Trim()
            if ([string]::IsNullOrWhiteSpace($Trimmed)) { continue }
            $Expanded = [Environment]::ExpandEnvironmentVariables($Trimmed)
            $Key = $Expanded.TrimEnd('\', '/')
            # See the note above: Test-Path THROWS on an entry Windows was
            # perfectly willing to store, so the probe is guarded and the
            # unparseable entry is reported rather than fatal.
            $Exists = $false
            $Valid  = $true
            try {
                $Exists = Test-Path -LiteralPath $Expanded -PathType Container
            } catch {
                $Valid = $false
            }
            [void]$Report.Add([PSCustomObject]@{
                Scope     = $Scope
                Raw       = $Trimmed
                Path      = $Expanded
                Exists    = $Exists
                Valid     = $Valid
                Duplicate = (-not $Seen.Add($Key))
            })
        }
    }
    return @($Report)
}

#: COMMANDS WORTH REPORTING A SECOND COPY OF.
#:
#: A CURATED LIST RATHER THAN AN ENUMERATION, and the choice is about
#: signal, not about effort. Walking every executable in every PATH
#: directory finds hundreds of "conflicts" that are not conflicts:
#: System32 and SysWOW64 ship the same eighty names on purpose, and every
#: one of them would be reported to a user who cannot act on any of them.
#: What actually bites is a TOOLCHAIN with two copies - two Pythons, two
#: Nodes, a Git-bundled curl in front of the Windows one - because the
#: shadowed copy is invisible from a terminal and the symptom shows up
#: somewhere else entirely, as a version number that does not match the
#: one the user just installed.
#:
#: So: the names where "which one wins?" is a question a person has
#: actually had to debug. Every entry is an interpreter, a package
#: manager, a compiler or a build driver.
$Script:PathConflictCommands = @(
    "python", "python3", "pip", "pip3", "conda",
    "node", "npm", "npx", "yarn", "pnpm",
    "java", "javac", "mvn", "gradle",
    "git", "gcc", "g++", "clang", "make", "cmake",
    "go", "cargo", "rustc", "dotnet", "msbuild",
    "ruby", "perl", "php",
    "curl", "openssl", "ffmpeg", "sqlite3"
)

#: The extensions Windows will actually EXECUTE from a bare command name.
#: Not $env:PATHEXT, deliberately: that list carries .COM, .VBS, .MSC and
#: friends, none of which a toolchain ships its entry point as, and
#: probing for them triples the file-system round trips to find nothing.
$Script:PathExecutableExtensions = @("exe", "cmd", "bat")

function Get-PathCommandConflicts {
    <#
    .SYNOPSIS
        Commands that more than one PATH directory can answer, in the
        order Windows would try them.

    .DESCRIPTION
        THE FIRST DIRECTORY WINS, ALWAYS, and that is the whole reason
        this is worth reporting. A user who installs Python 3.13 and keeps
        getting 3.11 from `python --version` is not looking at a broken
        install; they are looking at an older entry sitting earlier in the
        list. Nothing in Windows tells them so - `where python` would, and
        knowing to type it is the part that is missing.

        Takes the entry report rather than reading the PATH again, so the
        conflicts reported are the ones IN THE REPORT the user is looking
        at. Passing it in also keeps this hermetic under test: a mocked
        entry list produces mocked conflicts, with no probe of the real
        machine (see PathDoctor.Tests.ps1).

        Only entries that EXIST and are VALID can shadow anything - a dead
        or malformed entry answers no command at all - and a duplicate is
        skipped because it is the same directory reported twice, which
        would otherwise report every tool in it as conflicting with
        itself.

        Returns one object per contested command:
        Command, Winner, Shadowed (the rest, in PATH order), Count.

        EVERY PROBE IS GUARDED for the reason Get-PathEntryReport's is: a
        PATH entry is a string, Join-Path and Test-Path can both throw on
        one, and the scan that crashes is the scan that was looking at the
        interesting machine.
    #>
    param([object[]]$Entries)

    if (-not $Entries) { $Entries = @(Get-PathEntryReport) }

    $Dirs = @($Entries |
        Where-Object { $_.Valid -and $_.Exists -and -not $_.Duplicate } |
        ForEach-Object { $_.Path })
    if ($Dirs.Count -lt 2) { return @() }

    $Conflicts = New-Object System.Collections.ArrayList
    foreach ($Command in $Script:PathConflictCommands) {
        $Providers = New-Object System.Collections.ArrayList
        foreach ($Dir in $Dirs) {
            foreach ($Ext in $Script:PathExecutableExtensions) {
                $Hit = $false
                try {
                    $Hit = Test-Path -LiteralPath (Join-Path $Dir "$Command.$Ext") -PathType Leaf
                } catch {
                    $Hit = $false
                }
                if ($Hit) { [void]$Providers.Add($Dir); break }
            }
        }
        if ($Providers.Count -gt 1) {
            [void]$Conflicts.Add([PSCustomObject]@{
                Command  = $Command
                Winner   = $Providers[0]
                Shadowed = @($Providers[1..($Providers.Count - 1)])
                Count    = $Providers.Count
            })
        }
    }
    return @($Conflicts)
}

function Write-PathScanReport {
    <#
    .SYNOPSIS
        The universal half of the doctor: the PATH itself, scanned and
        reported. Returns
        @{Total; Dead; Duplicate; Invalid; Conflict; Length}.

    .DESCRIPTION
        STILL READ-ONLY, and the guarantee is asserted rather than
        promised - PathDoctor.Tests.ps1 reads this function's own source
        and fails if it grows a write. The repair half lives in
        Invoke-PathSanitizer, which the user reaches through a separate
        card, because "found something" and "changed something" are two
        different consents.
    #>
    $Entries = @(Get-PathEntryReport)
    if ($Entries.Count -eq 0) {
        Write-TaggedLine -Tag "WARN" -Text "System PATH is empty or unreadable."
        return @{ Total = 0; Dead = 0; Duplicate = 0; Invalid = 0; Conflict = 0; Length = 0 }
    }

    $Machine = @($Entries | Where-Object { $_.Scope -eq "Machine" }).Count
    $User    = @($Entries | Where-Object { $_.Scope -eq "User" }).Count
    Write-TaggedLine -Tag "SCAN" -Text "PATH -> $($Entries.Count) entries ($Machine machine, $User user)"

    # Malformed entries first, and NOT folded into [DEAD]: "the folder does
    # not exist" invites the user to go and look for it, which is the wrong
    # advice for a string that could never name a folder in the first place.
    $Invalid = @($Entries | Where-Object { -not $_.Valid })
    foreach ($Entry in $Invalid) {
        Write-TaggedLine -Tag "INVALID" -Text "$($Entry.Scope) PATH -> $($Entry.Raw)  (not a usable path - illegal characters; Windows skips this entry)"
    }
    # A malformed entry is already reported above; listing it a second time
    # as dead would be true but useless.
    $Dead = @($Entries | Where-Object { $_.Valid -and -not $_.Exists })
    foreach ($Entry in $Dead) {
        Write-TaggedLine -Tag "DEAD" -Text "$($Entry.Scope) PATH -> $($Entry.Raw)  (folder does not exist)"
    }
    $Dupes = @($Entries | Where-Object { $_.Duplicate })
    foreach ($Entry in $Dupes) {
        Write-TaggedLine -Tag "DUPE" -Text "$($Entry.Scope) PATH -> $($Entry.Raw)  (already listed earlier)"
    }

    # SHADOWED TOOLCHAINS. Reported after the structural findings and
    # before the length warning, because it is the one finding here that
    # is about what the PATH DOES rather than about what is in it: every
    # entry can exist, be unique and be well-formed, and the machine can
    # still run the wrong Python.
    $Conflicts = @(Get-PathCommandConflicts -Entries $Entries)
    foreach ($Conflict in $Conflicts) {
        Write-TaggedLine -Tag "CONFLICT" -Text "$($Conflict.Command) -> $($Conflict.Count) copies on PATH; '$($Conflict.Command)' runs the one in $($Conflict.Winner)"
        foreach ($Loser in $Conflict.Shadowed) {
            Write-TaggedLine -Tag "SHADOWED" -Text "$($Conflict.Command) -> $Loser  (never reached from a bare '$($Conflict.Command)')"
        }
    }

    $Length = ($Entries | ForEach-Object { $_.Raw.Length + 1 } | Measure-Object -Sum).Sum
    if ($Length -ge $Script:PathLengthWarn) {
        Write-TaggedLine -Tag "WARN" -Text "PATH is $Length characters - close to the point where Windows truncates it silently."
    }

    if ($Dead.Count -eq 0 -and $Dupes.Count -eq 0 -and $Invalid.Count -eq 0 -and $Conflicts.Count -eq 0) {
        Write-TaggedLine -Tag "OK" -Text "PATH -> every entry resolves, no duplicates, no shadowed tools"
    } else {
        # See $Script:PathScanIsReadOnly - found and reported HERE, never
        # touched here. The line used to end "Pulse never removes one",
        # which was true of the whole app and is now true only of this
        # function: the sanitizer removes the subset it can prove is safe
        # (see Get-PathPrunePlan) and refuses the rest for exactly the
        # reason that sentence gave.
        Write-TaggedLine -Tag "INFO" -Text "Nothing above was changed. 'Prune Dead & Duplicate Entries' removes the entries that are provably safe to remove, and leaves the rest."
    }
    return @{
        Total     = $Entries.Count
        Dead      = $Dead.Count
        Duplicate = $Dupes.Count
        Invalid   = $Invalid.Count
        Conflict  = $Conflicts.Count
        Length    = $Length
    }
}

# ============================================================
#  THE REPAIR HALF - PRUNE DEAD AND DUPLICATE PATH ENTRIES
#
#  THE SCAN'S OWN DOCTRINE IS WHY THIS IS NOT SIMPLY "DELETE WHAT IS
#  DEAD". $Script:PathScanIsReadOnly says it exactly right: "a
#  stale-looking entry may belong to software that is merely offline (a
#  network share, an unmounted volume, a tool installed per-user under
#  another profile), and an automatic prune has no way to tell those from
#  real rubbish."
#
#  That is an argument against pruning BLINDLY, and it was read as an
#  argument against pruning at all - which left the user with a list of
#  four dead entries and an instruction to go and edit the registry by
#  hand. The middle position is to prune only the entries where the
#  ambiguity does not exist, and to say out loud which ones those were.
#
#  THREE CLASSES ARE PROVABLY SAFE:
#
#    DUPLICATE  The same directory, listed twice. Removing the second
#               occurrence cannot change which directory answers any
#               command, because the first one already answered it. This
#               is safe even when the directory is offline, missing, or
#               on a share - the entry that stays behaves identically.
#
#    MALFORMED  A string Windows cannot parse as a path. It has never
#               resolved to anything and never will; Windows already
#               skips it. There is no state in which removing it changes
#               what a command does.
#
#    DEAD ON A PRESENT FIXED VOLUME  A directory that does not exist, on
#               an internal disk that is mounted right now. This is the
#               one that needs the volume test, and it is the whole
#               reason the doctrine above was right: C:\Tools\Ollama
#               missing from a mounted C: is rubbish an uninstaller left,
#               while D:\Tools missing because D: is a USB stick in a
#               drawer is a working entry with the drive unplugged.
#
#  EVERYTHING ELSE IS KEPT, with its reason printed. A dead UNC path, a
#  dead entry on a removable or network drive, a dead entry on a drive
#  letter that is not currently mounted: all reported, none touched.
# ============================================================

#: Where the pre-prune PATH is written before anything is removed, one
#: value per scope per run. The restore point covers the machine; this
#: covers the ONE STRING a user would actually want back, in a form they
#: can read and paste without booting into recovery.
$Script:PathBackupRegPath = "HKCU:\Software\Pulse\PathBackups"

function Test-PrunablePathVolume {
    <#
    .SYNOPSIS
        Is this dead entry's volume one we can be sure about?

    .DESCRIPTION
        True only for a path rooted on a FIXED drive that is mounted now.

        UNC paths are refused outright: a share that is unreachable is
        indistinguishable from a share that has been deleted, and the
        machine holding the answer is not this one.

        Removable and network drives are refused for the same reason one
        step down - the entry may be perfectly correct with the media
        absent. Only "the disk is bolted inside this computer, it is
        mounted, and the folder is not on it" is a fact that will still
        be true tomorrow.

        Guarded end to end: this is handed raw PATH strings, and
        GetPathRoot throws on the malformed ones. A throw here would kill
        the prune on the machine most in need of it.
    #>
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    if ($Path.StartsWith("\\")) { return $false }   # UNC - not ours to judge

    $Root = $null
    try { $Root = [System.IO.Path]::GetPathRoot($Path) } catch { return $false }
    if ([string]::IsNullOrWhiteSpace($Root)) { return $false }

    try {
        if (-not (Test-Path -LiteralPath $Root)) { return $false }
        $Drive = New-Object System.IO.DriveInfo($Root)
        if (-not $Drive.IsReady) { return $false }
        return ($Drive.DriveType -eq [System.IO.DriveType]::Fixed)
    } catch {
        return $false
    }
}

function Get-PathPrunePlan {
    <#
    .SYNOPSIS
        Every PATH entry with a verdict: Remove (and why) or Keep (and
        why). Read-only - it decides, it does not act.

    .DESCRIPTION
        Separate from Invoke-PathSanitizer so the decision can be tested
        without a machine that has a broken PATH, and so the KEPT lines
        can be printed beside the removals - "we left this one alone,
        here is why" is the half that makes the removals trustworthy.

        Returns the entry objects from Get-PathEntryReport with two
        fields added: Action ("remove"/"keep") and Verdict (the reason,
        as a short phrase that reads as the end of a sentence).
    #>
    param([object[]]$Entries)

    if (-not $Entries) { $Entries = @(Get-PathEntryReport) }

    $Plan = New-Object System.Collections.ArrayList
    foreach ($Entry in $Entries) {
        $Action  = "keep"
        $Verdict = "resolves"

        if ($Entry.Duplicate) {
            $Action  = "remove"
            $Verdict = "already listed earlier - the first copy answers everything this one would"
        } elseif (-not $Entry.Valid) {
            $Action  = "remove"
            $Verdict = "not a usable path - Windows already skips it"
        } elseif (-not $Entry.Exists) {
            if (Test-PrunablePathVolume -Path $Entry.Path) {
                $Action  = "remove"
                $Verdict = "folder does not exist on a mounted internal disk"
            } else {
                $Action  = "keep"
                $Verdict = "folder is missing, but its drive is removable, network or not mounted - it may be correct with the volume present"
            }
        }

        [void]$Plan.Add([PSCustomObject]@{
            Scope     = $Entry.Scope
            Raw       = $Entry.Raw
            Path      = $Entry.Path
            Exists    = $Entry.Exists
            Valid     = $Entry.Valid
            Duplicate = $Entry.Duplicate
            Action    = $Action
            Verdict   = $Verdict
        })
    }
    return @($Plan)
}

function Save-PathBackup {
    <# The scope's PATH exactly as it reads now, into HKCU, stamped.
       Returns $true when the string is safely stored - the caller REFUSES
       TO WRITE without it, because a prune whose backup silently failed
       is the one case where "reversible" would be a lie. #>
    param(
        [Parameter(Mandatory = $true)][string]$Scope,
        [Parameter(Mandatory = $true)][string]$Value
    )
    try {
        $Root = Resolve-UserRegPath $Script:PathBackupRegPath
        if (-not (Test-Path $Root)) { New-Item -Path $Root -Force | Out-Null }
        $Name = "{0}_{1}" -f $Scope, (Get-Date -Format 'yyyyMMdd_HHmmss')
        Set-ItemProperty -Path $Root -Name $Name -Value $Value -Type String -Force
        Write-Log "PATH SANITIZER: backed up $Scope PATH to $Script:PathBackupRegPath\$Name"
        return $true
    } catch {
        Write-ErrorX "Could not back up the $Scope PATH - nothing was changed. ($($_.Exception.Message))"
        return $false
    }
}

function Get-PluralSuffix {
    <# "entry" / "entries" without an inline if-else inside an expanding
       string. PowerShell 5.1 accepts $(if (...) { 'y' } else { 'ies' })
       there, and it is unreadable at the one place a reader is checking
       whether the sentence matches the number. #>
    param([int]$Count, [string]$Singular = "entry", [string]$Plural = "entries")
    if ($Count -eq 1) { return $Singular }
    return $Plural
}

function Invoke-PathSanitizer {
    <#
    .SYNOPSIS
        Removes the PATH entries Get-PathPrunePlan can prove are safe to
        remove, after a restore point and a readable backup of the exact
        string being replaced.

    .DESCRIPTION
        THE MACHINE SCOPE NEEDS ADMINISTRATOR and the user scope does
        not, so an unelevated run cleans what it can and says what it
        could not - rather than refusing the whole operation over the
        half of it that needs rights. On most machines the mess is in the
        user scope anyway: it is the one installers write to without
        asking.

        Order is load-bearing. The restore point comes first, then the
        per-scope backup, and only then the write - so there is no window
        in which the PATH has been changed and nothing has recorded what
        it was.
    #>
    Write-SectionHeader "PATH Sanitizer"

    $Plan = @(Get-PathPrunePlan)
    if ($Plan.Count -eq 0) {
        Write-TaggedLine -Tag "WARN" -Text "System PATH is empty or unreadable - nothing to sanitize."
        return [PSCustomObject]@{ Removed = 0; Kept = 0; Scopes = @() }
    }

    $Doomed = @($Plan | Where-Object { $_.Action -eq "remove" })
    # Only the entries that were SPARED DESPITE being broken. A healthy
    # entry is not "left alone", it is simply fine, and printing thirty of
    # those would bury the handful of real decisions.
    $Spared = @($Plan | Where-Object { $_.Action -eq "keep" -and -not ($_.Exists -and $_.Valid) })

    foreach ($Entry in $Spared) {
        Write-TaggedLine -Tag "KEPT" -Text "$($Entry.Scope) PATH -> $($Entry.Raw)  ($($Entry.Verdict))"
    }

    if ($Doomed.Count -eq 0) {
        Write-TaggedLine -Tag "OK" -Text "PATH -> nothing to prune; every entry either resolves or is one Pulse will not judge."
        return [PSCustomObject]@{ Removed = 0; Kept = $Spared.Count; Scopes = @() }
    }

    foreach ($Entry in $Doomed) {
        Write-TaggedLine -Tag "DEAD" -Text "$($Entry.Scope) PATH -> $($Entry.Raw)  ($($Entry.Verdict))"
    }

    # A PATH edit is a registry edit, and the restore point is what the
    # card promises. Created ONCE per process by New-SystemRestorePoint,
    # which is dry-run aware on its own.
    New-SystemRestorePoint -Action "PathSanitize"

    $Elevated = Test-IsElevatedSession
    $Removed  = 0
    $Touched  = New-Object System.Collections.ArrayList

    foreach ($Scope in @("Machine", "User")) {
        $ScopeDoomed = @($Doomed | Where-Object { $_.Scope -eq $Scope })
        if ($ScopeDoomed.Count -eq 0) { continue }

        if ($Scope -eq "Machine" -and -not $Elevated) {
            $Noun = Get-PluralSuffix -Count $ScopeDoomed.Count
            Write-TaggedLine -Tag "KEPT" -Text "Machine PATH -> $($ScopeDoomed.Count) $Noun left alone (the machine PATH needs Administrator; the user PATH was still cleaned)"
            continue
        }

        $Current = [Environment]::GetEnvironmentVariable("Path", $Scope)
        if ([string]::IsNullOrWhiteSpace($Current)) { continue }

        # REBUILT FROM THE PLAN, NOT BY STRING SURGERY. Removing a
        # substring from the joined value would take the wrong copy when
        # an entry is duplicated - which is precisely the case with the
        # most entries to remove. Walking the split list and dropping by
        # POSITION keeps "remove the second occurrence" meaning that.
        $Raws = @($Current -split ";")
        $Kill = New-Object 'System.Collections.Generic.List[int]'
        foreach ($Entry in $ScopeDoomed) {
            for ($i = 0; $i -lt $Raws.Count; $i++) {
                if ($Kill.Contains($i)) { continue }
                if ($Raws[$i].Trim() -eq $Entry.Raw) { $Kill.Add($i); break }
            }
        }
        if ($Kill.Count -eq 0) { continue }

        $Kept = @()
        for ($i = 0; $i -lt $Raws.Count; $i++) {
            if ($Kill.Contains($i)) { continue }
            if ([string]::IsNullOrWhiteSpace($Raws[$i])) { continue }
            $Kept += $Raws[$i]
        }
        $NewValue = ($Kept -join ";")
        $Noun = Get-PluralSuffix -Count $Kill.Count

        if (Test-DryRun "Remove $($Kill.Count) $Noun from the $Scope PATH") {
            $Removed += $Kill.Count
            [void]$Touched.Add($Scope)
            continue
        }

        if (-not (Save-PathBackup -Scope $Scope -Value $Current)) { continue }

        try {
            [Environment]::SetEnvironmentVariable("Path", $NewValue, $Scope)
            Write-TaggedLine -Tag "PRUNED" -Text "$Scope PATH -> $($Kill.Count) $Noun removed, $($Kept.Count) kept"
            $Removed += $Kill.Count
            [void]$Touched.Add($Scope)
        } catch {
            Write-TaggedLine -Tag "FAIL" -Text "$Scope PATH -> could not be written: $($_.Exception.Message)"
        }
    }

    if ($Removed -gt 0 -and -not $Script:DryRun) {
        # This process's own copy, so anything the session does next sees
        # the cleaned list. Everything already open keeps what it started
        # with - the same caveat Verify-Environment prints after a repair.
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "User")
        Write-TaggedLine -Tag "INFO" -Text "A copy of each PATH as it was before this ran is under HKCU\Software\Pulse\PathBackups, and the restore point above covers it too."
        Write-TaggedLine -Tag "INFO" -Text "The change reaches NEW terminals only - anything already open keeps the PATH it started with."
    }

    Write-Host ""
    Write-TaggedLine -Tag "DONE" -Text "$Removed removed | $($Spared.Count) left alone"

    return [PSCustomObject]@{
        Removed = $Removed
        Kept    = $Spared.Count
        Scopes  = @($Touched | Select-Object -Unique)
    }
}

function Get-CommandDirectory {
    <# The FOLDER a command resolves to on this PATH, or $null.

       The folder, not the file: PATH holds directories, so the directory
       is the thing the report has to name if the line is going to help
       anyone. #>
    param([Parameter(Mandatory = $true)][string]$Command)
    $Resolved = Get-Command $Command -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $Resolved) { return $null }
    $Source = [string]$Resolved.Source
    if ([string]::IsNullOrWhiteSpace($Source)) { return $null }
    return (Split-Path $Source -Parent)
}

function Verify-Environment {
    Write-SectionHeader "PATH Doctor"

    $Ok       = 0
    $Repaired = 0
    $Missing  = New-Object System.Collections.ArrayList

    foreach ($Tool in $Script:DevToolCatalog) {
        $OnPath      = $null -ne (Get-Command $Tool.Command -ErrorAction SilentlyContinue)
        $ResolvedDir = $null

        if (-not $OnPath) {
            # Probe the tool's well-known install locations. Wildcards pick
            # the newest matching directory (e.g. jdk-21 over jdk-17).
            foreach ($Probe in $Tool.Probes) {
                if ($ResolvedDir) { break }
                if ([string]::IsNullOrWhiteSpace($Probe)) { continue }
                $Candidates = @(Get-Item -Path $Probe -ErrorAction SilentlyContinue |
                                Where-Object { $_.PSIsContainer } |
                                Sort-Object FullName -Descending)
                foreach ($Dir in $Candidates) {
                    foreach ($Ext in @("exe", "cmd", "bat")) {
                        if (Test-Path (Join-Path $Dir.FullName "$($Tool.Command).$Ext")) {
                            $ResolvedDir = $Dir.FullName
                            break
                        }
                    }
                    if ($ResolvedDir) { break }
                }
            }
        }

        if ($OnPath) {
            # The DIRECTORY, which is the thing PATH actually holds and the
            # thing the user would have to add by hand. "'git' is ready to
            # use" told them the outcome and withheld the one fact that
            # makes the line verifiable.
            $Dir = Get-CommandDirectory -Command $Tool.Command
            if (-not $Dir) { $Dir = "(resolved on PATH)" }
            Write-TaggedLine -Tag "OK" -Text "$($Tool.Name) -> $Dir"
            $Ok++
        } elseif ($ResolvedDir) {
            if (Add-ToUserPath -Directory $ResolvedDir) {
                Write-TaggedLine -Tag "FIXED" -Text "$($Tool.Name) -> $ResolvedDir  (added to user PATH)"
                $Repaired++
            } else {
                Write-TaggedLine -Tag "FAIL" -Text "$($Tool.Name) -> $ResolvedDir  (could not be added to user PATH)"
            }
        } else {
            Write-TaggedLine -Tag "MISSING" -Text "$($Tool.Name) -> not installed  (winget install --id $($Tool.WingetId))"
            [void]$Missing.Add($Tool.Name)
        }

        # Companion environment variable (e.g. JAVA_HOME for the JDK).
        if ($Tool.EnvVarName) {
            $ExistingVar = [Environment]::GetEnvironmentVariable($Tool.EnvVarName, "User")
            if (-not $ExistingVar) { $ExistingVar = [Environment]::GetEnvironmentVariable($Tool.EnvVarName, "Machine") }
            if ($ExistingVar) {
                Write-TaggedLine -Tag "OK" -Text "$($Tool.EnvVarName) -> $ExistingVar"
            } else {
                # Home dir = parent of the bin directory the command lives in.
                $HomeDir = $null
                if ($ResolvedDir) {
                    $HomeDir = Split-Path $ResolvedDir -Parent
                } elseif ($OnPath) {
                    $Cmd = Get-Command $Tool.Command -ErrorAction SilentlyContinue
                    if ($Cmd -and $Cmd.Source) { $HomeDir = Split-Path (Split-Path $Cmd.Source -Parent) -Parent }
                }
                # Sanity gate: a valid home must itself contain bin\<command>.exe.
                # This rejects PATH shims (e.g. Oracle's javapath symlink dir),
                # whose grandparent is NOT a usable JAVA_HOME.
                if ($HomeDir -and -not (Test-Path (Join-Path $HomeDir "bin\$($Tool.Command).exe"))) {
                    Write-Log "VERIFY-ENV: skipped $($Tool.EnvVarName) - '$HomeDir' is not a valid home (no bin\$($Tool.Command).exe; PATH entry is likely a shim)."
                    $HomeDir = $null
                }
                if ($HomeDir -and (Test-Path $HomeDir)) {
                    if (Test-DryRun "Set user environment variable $($Tool.EnvVarName) = '$HomeDir'") {
                        $Repaired++
                    } else {
                        try {
                            [Environment]::SetEnvironmentVariable($Tool.EnvVarName, $HomeDir, "User")
                            Set-Item -Path "env:$($Tool.EnvVarName)" -Value $HomeDir
                            Write-TaggedLine -Tag "SET" -Text "$($Tool.EnvVarName) -> $HomeDir  (user scope)"
                            $Repaired++
                        } catch {
                            Write-TaggedLine -Tag "FAIL" -Text "$($Tool.EnvVarName) -> could not be set: $($_.Exception.Message)"
                        }
                    }
                }
            }
        }
    }

    # The universal pass. AFTER the tools, deliberately: a repair above
    # changes the user PATH, and a scan that ran first would report the
    # PATH as it was rather than as the user is about to find it.
    Write-Host ""
    $PathScan = Write-PathScanReport

    Write-Host ""
    $DoneParts = @("$Ok ready", "$Repaired fixed", "$($Missing.Count) not installed",
                   "$($PathScan.Dead) dead PATH entries", "$($PathScan.Duplicate) duplicates")
    # Only when there ARE any: a permanent "0 malformed" column would add a
    # number to every run to describe a case almost no machine has. The same
    # rule earns the conflict column its place - most machines have one
    # Python, and a standing "0 shadowed" would be a number about nothing.
    if ([int]$PathScan.Invalid -gt 0)  { $DoneParts += "$($PathScan.Invalid) malformed" }
    if ([int]$PathScan.Conflict -gt 0) { $DoneParts += "$($PathScan.Conflict) shadowed tools" }
    Write-TaggedLine -Tag "DONE" -Text ($DoneParts -join " | ")
    if ($Repaired -gt 0 -and -not $Script:DryRun) {
        Write-TaggedLine -Tag "INFO" -Text "New PATH entries reach NEW terminals only - anything already open keeps the PATH it started with."
    }

    return [PSCustomObject]@{
        OkCount        = $Ok
        RepairedCount  = $Repaired
        MissingCount   = $Missing.Count
        MissingNames   = @($Missing)
        PathEntryCount = $PathScan.Total
        DeadPathCount  = $PathScan.Dead
        DuplicatePathCount = $PathScan.Duplicate
        InvalidPathCount   = $PathScan.Invalid
        ConflictPathCount  = $PathScan.Conflict
    }
}
