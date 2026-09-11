#Requires -Version 5.1
<#
.SYNOPSIS
    17-Leftovers.ps1 - find, back up and remove the traces uninstalled
    software leaves behind: orphaned startup entries, ghost scheduled
    tasks, dead Squirrel packages and context-menu hooks pointing at files
    that no longer exist.

.DESCRIPTION
    THE WHOLE MODULE STANDS ON ONE WORD: PROVABLY. Uninstallers on Windows
    are not transactional, and what they leave behind is real - measured
    on one ordinary machine, six of fifteen startup entries, two scheduled
    tasks and a 454 MB Squirrel package all pointed at software that was
    gone. Cleaning that up is worth doing. Getting it wrong is not a
    cosmetic bug: it deletes something a working program needs.

    So nothing is flagged on RESEMBLANCE. An item is a leftover only when
    it POINTS AT A PATH and that path is provably absent (see
    Test-PathProvablyAbsent), or when the vendor's own uninstaller has
    marked it dead. Those are the two kinds of evidence that do not
    require guessing what a folder or a key "belongs to".

    WHAT IS DELIBERATELY NOT HERE, and it was asked for and measured
    before it was declined: "AppData folders whose application is gone".
    A folder does not name its application, so that question can only be
    answered by matching NAMES, and the measurement is the argument. Of the
    thirteen folders under %LOCALAPPDATA%\Packages with no matching
    installed package on the machine this was built on, TWELVE WERE LIVE:
    nine Chrome sandbox AppContainer profiles, Internet Explorer's
    protected-mode container, and two other system containers. A name
    heuristic would have offered to delete Chrome's working sandbox. The
    one AppData category that IS provable - a Squirrel package carrying
    its own ".dead" marker - is here.

    EVERY REMOVAL IS REVERSIBLE, and the order is the safety property:
    restore point, then a backup of THAT item, then the removal - and an
    item whose backup failed is not removed. Registry values and task
    definitions are recorded under HKCU\Software\Pulse\Backups\Leftovers;
    keys are exported with reg.exe; files and folders are MOVED into the
    backup set rather than deleted. Restore-LeftoversBackup reverses a set.

    THE PURGE RE-SCANS. The GUI hands over ids from a scan the user looked
    at; the purge re-derives the list and removes only ids that are STILL
    leftovers. Reinstalling an app between the scan and the click takes
    its entries off the list rather than deleting the new installation's.
#>

# ============================================================
#  LOCATIONS (redirected by tests/backend/Leftovers.Tests.ps1)
# ============================================================

#: Where a purge records what it removed, one sub-key per run.
$Script:LeftoverBackupRegRoot = "HKCU:\Software\Pulse\Backups\Leftovers"

#: Where a purge puts the FILES it backs up: .reg exports, task XML, and
#: the moved shortcuts and folders themselves.
$Script:LeftoverBackupFolderRoot = Join-Path (Get-PulseDataPath "Backups") "Leftovers"

#: The roots a dead Squirrel package can sit under, one level deep.
$Script:LeftoverResidueRoots = @($env:LOCALAPPDATA, $env:APPDATA, $env:ProgramData)

#: Where CLSIDs are registered. Redirectable so a test can build a fake
#: handler without writing to HKEY_CLASSES_ROOT.
$Script:LeftoverClsidRoot = 'Registry::HKEY_CLASSES_ROOT\CLSID'

#: Static shell verbs ("Open with X") live under these, one key per verb,
#: each with a `command` sub-key whose default value is a command line.
$Script:LeftoverVerbRoots = @(
    'Registry::HKEY_CLASSES_ROOT\*\shell'
    'Registry::HKEY_CLASSES_ROOT\AllFilesystemObjects\shell'
    'Registry::HKEY_CLASSES_ROOT\Directory\shell'
    'Registry::HKEY_CLASSES_ROOT\Directory\Background\shell'
    'Registry::HKEY_CLASSES_ROOT\Drive\shell'
    'Registry::HKEY_CLASSES_ROOT\Folder\shell'
)

# ============================================================
#  THE PROTECTED SET
#
#  Paths under these are NEVER leftovers, whatever else is true. A missing
#  file under C:\Windows is far more likely to be a 32-bit registration
#  read from 64-bit code (System32 vs SysWOW64), a feature on demand that
#  is not installed yet, or servicing in progress than it is residue -
#  and the cost of being wrong is the operating system.
# ============================================================
function Get-LeftoverProtectedRoots {
    $Roots = New-Object System.Collections.ArrayList
    foreach ($Base in @($env:SystemRoot)) {
        if ($Base) { [void]$Roots.Add($Base) }
    }
    foreach ($ProgramRoot in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432)) {
        if ([string]::IsNullOrWhiteSpace($ProgramRoot)) { continue }
        foreach ($Sub in @("WindowsApps", "WindowsPowerShell", "Microsoft",
                           "Common Files\Microsoft Shared")) {
            [void]$Roots.Add((Join-Path $ProgramRoot $Sub))
        }
    }
    if ($env:ProgramData) { [void]$Roots.Add((Join-Path $env:ProgramData "Microsoft")) }
    return @($Roots | Select-Object -Unique)
}

function Test-LeftoverProtectedPath {
    <# Is $Path inside the operating system's own territory?

       Prefix-matched with a separator forced on, so "C:\Windows" protects
       "C:\Windows\System32" and not "C:\WindowsTools". The Program Files
       "Windows *" family (Windows Defender, Windows NT, Windows Mail...)
       is matched by name because it is a family rather than a fixed
       list. #>
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $true }
    $Normal = $Path.TrimEnd('\')
    foreach ($Root in (Get-LeftoverProtectedRoots)) {
        $R = $Root.TrimEnd('\')
        if ($Normal -ieq $R -or
            $Normal.StartsWith($R + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    foreach ($ProgramRoot in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432)) {
        if ([string]::IsNullOrWhiteSpace($ProgramRoot)) { continue }
        $P = $ProgramRoot.TrimEnd('\') + '\'
        if ($Normal.StartsWith($P, [System.StringComparison]::OrdinalIgnoreCase)) {
            $First = ($Normal.Substring($P.Length) -split '\\')[0]
            if ($First -like 'Windows *') { return $true }
        }
    }
    return $false
}

# ============================================================
#  THE PREDICATE EVERYTHING ELSE STANDS ON
# ============================================================
function Test-PathProvablyAbsent {
    <#
    .SYNOPSIS
        Is it CERTAIN that nothing exists at $Path - not merely that
        Test-Path said no?

    .DESCRIPTION
        "Test-Path returned $false" and "the file is gone" are different
        claims, and every trap in this module lives in the gap between
        them. $true only when ALL of these hold:

          ABSOLUTE AND DRIVE-ROOTED. A bare "shell32.dll" or "cmd.exe" is
          resolved through a search path Pulse cannot replay; a UNC path's
          answer lives on another machine.

          NOT PROTECTED. See Test-LeftoverProtectedPath.

          ON A FIXED, MOUNTED VOLUME. A path on D: with D: unplugged is a
          working entry with the drive in a drawer - the same rule the
          PATH prune enforces, via the same function.

          ABSENT, with the probe guarded. Test-Path THROWS on a path
          containing '|' or '<', and whether that reaches a catch depends
          on the ambient error preference unless it is made explicit.

          ITS NEAREST EXISTING ANCESTOR IS READABLE. This is the check
          that matters most and looks least necessary.
          %ProgramFiles%\WindowsApps refuses a directory listing to
          everything but TrustedInstaller, so Test-Path answers $false for
          files that are sitting right there. "I could not see it" is not
          "it is not there"; if the parent cannot be listed, nothing about
          its contents is proven.
    #>
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    $Candidate = $null
    try {
        $Candidate = [System.Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
    } catch {
        return $false
    }
    if ($Candidate.StartsWith('\\')) { return $false }
    if ($Candidate -notmatch '^[A-Za-z]:\\') { return $false }
    if ($Candidate.IndexOfAny([System.IO.Path]::GetInvalidPathChars()) -ge 0) { return $false }
    if ($Candidate -match '[\*\?\|<>"]') { return $false }
    if (Test-LeftoverProtectedPath -Path $Candidate) { return $false }
    if (-not (Test-PrunablePathVolume -Path $Candidate)) { return $false }

    try {
        if (Test-Path -LiteralPath $Candidate -ErrorAction Stop) { return $false }
    } catch {
        return $false
    }

    $Current = $Candidate
    for ($Depth = 0; $Depth -lt 64; $Depth++) {
        $Parent = $null
        try { $Parent = [System.IO.Path]::GetDirectoryName($Current) } catch { return $false }
        if ([string]::IsNullOrEmpty($Parent)) { return $false }
        $Current = $Parent
        $Exists = $false
        try {
            $Exists = Test-Path -LiteralPath $Current -PathType Container -ErrorAction Stop
        } catch {
            return $false
        }
        if (-not $Exists) { continue }
        try {
            $null = @(Get-ChildItem -LiteralPath $Current -Force -ErrorAction Stop |
                Select-Object -First 1)
            return $true
        } catch {
            return $false
        }
    }
    return $false
}

# Get-CommandTargetPath, Get-ShortcutTargetPath and Get-PulseScheduledTasks
# live in 05-Startup.ps1, which loads first and is their other consumer.
# One copy is the point: the Startup Manager's MISSING badge and this
# module's verdict must never be two different answers about one entry.
# tests/test_backend_function_uniqueness.py fails if a second copy appears.

function Get-LeftoverId {
    <# A stable, comma-free identifier for one leftover.

       A HASH, NOT THE LOCATION. The id rides to the backend on -AppIds,
       which is a comma-separated LIST, and a registry path or a task name
       can contain a comma. It is also derived rather than stored, so the
       purge can recompute it from a fresh scan and match only the items
       that are STILL leftovers. #>
    param([Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][string[]]$Parts)

    $Sha = [System.Security.Cryptography.SHA1]::Create()
    try {
        $Bytes = [System.Text.Encoding]::UTF8.GetBytes(($Parts -join '|').ToLowerInvariant())
        $Hash = $Sha.ComputeHash($Bytes)
        return (-join ($Hash[0..7] | ForEach-Object { $_.ToString('x2') }))
    } finally {
        $Sha.Dispose()
    }
}

function New-LeftoverItem {
    param(
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][string]$Group,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Location,
        [string]$Target = "",
        [string]$ValueName = "",
        [string]$Reason = "",
        [long]$SizeBytes = 0,
        [bool]$NeedsAdmin = $false
    )
    return [PSCustomObject]@{
        id         = (Get-LeftoverId -Parts @($Kind, $Location, $ValueName, $Name))
        kind       = $Kind
        group      = $Group
        name       = $Name
        location   = $Location
        valueName  = $ValueName
        target     = $Target
        reason     = $Reason
        sizeBytes  = $SizeBytes
        needsAdmin = $NeedsAdmin
    }
}

# ============================================================
#  SCANNERS - each returns leftover items and changes nothing
# ============================================================
function Get-LeftoverStartupEntries {
    <#
    .SYNOPSIS
        Startup entries whose program is provably absent - enabled ones,
        and the ones Pulse has DISABLED.

    .DESCRIPTION
        DISABLED RECORDS WERE EXCLUDED AT FIRST, and the measurement is why
        they are not now. The reasoning was that a record in Pulse's own
        disabled store is the user's way back to something they chose to
        turn off. On the machine this was built on, all six orphaned startup
        entries had already been disabled through the Startup Manager - so
        the Startup Manager showed six rows captioned MISSING while this
        cleaner, asked the same question, reported nothing at all.

        A way back to an uninstalled program leads nowhere: re-enabling it
        only recreates a Run key that launches nothing, and reinstalling the
        software writes its own. A disabled record whose program is STILL
        installed is untouched - that one really is a way back.
    #>
    $Items = New-Object System.Collections.ArrayList
    $Sources = @(
        @{ Entries = @(@(Get-StartupRunKeyItems) + @(Get-StartupFolderItems)); Disabled = $false }
        @{ Entries = @(Get-DisabledStartupItems); Disabled = $true }
    )
    foreach ($Source in $Sources) {
        foreach ($Entry in @($Source.Entries)) {
            if (-not $Entry) { continue }
            $Label = Get-StartupDisplayName -Name $Entry.Name
            if ($Entry.Type -eq "Registry") {
                $Target = Get-CommandTargetPath -Command ([string]$Entry.Command)
                if (-not $Target -or -not (Test-PathProvablyAbsent -Path $Target)) { continue }
                # The disabled store is read through Resolve-UserRegPath (see
                # Get-DisabledStartupItems) while the item carries the
                # UNRESOLVED path, so the location used for the backup and
                # the removal is resolved here to name the key that was read.
                $Location = if ($Source.Disabled) { Resolve-UserRegPath $Entry.RegPath } else { $Entry.RegPath }
                $Reason = if ($Source.Disabled) {
                    "Disabled in Pulse, and the program it pointed at has since been uninstalled."
                } else {
                    "Launches at sign-in, and the program it points at is not on this PC."
                }
                [void]$Items.Add((New-LeftoverItem -Kind "startup-run" -Group "startup" `
                    -Name $Label -Location $Location -ValueName $Entry.Name -Target $Target `
                    -Reason $Reason -NeedsAdmin ((-not $Source.Disabled) -and $Entry.Hive -eq "HKLM")))
            } elseif ($Entry.Type -eq "Folder") {
                $Target = Get-ShortcutTargetPath -Path ([string]$Entry.Command)
                if (-not $Target -or -not (Test-PathProvablyAbsent -Path $Target)) { continue }
                $AllUsers = $false
                if (-not $Source.Disabled -and $Script:StartupFolderPaths.Count -gt 1) {
                    $AllUsers = ((Split-Path -Path $Entry.Command -Parent) -ieq $Script:StartupFolderPaths[1])
                }
                $Reason = if ($Source.Disabled) {
                    "A shortcut Pulse disabled, to a program that has since been uninstalled."
                } else {
                    "A Startup-folder shortcut to a program that is not on this PC."
                }
                [void]$Items.Add((New-LeftoverItem -Kind "startup-folder" -Group "startup" `
                    -Name $Label -Location ([string]$Entry.Command) -Target $Target `
                    -Reason $Reason -NeedsAdmin $AllUsers))
            }
        }
    }
    return @($Items)
}

function Get-TaskExecTargets {
    <# The executable path of every Exec action on a task, or an empty list
       when any action is not a file launch (a COM handler has no path to
       prove absent, so a task carrying one is never a leftover). #>
    param($Task)

    $Targets = New-Object System.Collections.ArrayList
    foreach ($Action in @($Task.Actions)) {
        $ClassName = ""
        try { $ClassName = [string]$Action.CimClass.CimClassName } catch { }
        if ($ClassName -ne 'MSFT_TaskExecAction') { return @() }
        $Execute = [string]$Action.Execute
        if ([string]::IsNullOrWhiteSpace($Execute)) { return @() }
        $Path = Get-CommandTargetPath -Command $Execute
        if (-not $Path) { return @() }
        [void]$Targets.Add($Path)
    }
    return @($Targets)
}

function Get-LeftoverScheduledTasks {
    <# Tasks whose EVERY action launches a file that is provably absent.

       Every action, not any: a task with one live action still does
       something, and removing it would stop that. \Microsoft\Windows\ is
       never even examined - that tree is the operating system's own
       maintenance, and the protected-path rule would refuse its targets
       anyway. #>
    $Items = New-Object System.Collections.ArrayList
    foreach ($Task in (Get-PulseScheduledTasks)) {
        $TaskPath = [string]$Task.TaskPath
        if ($TaskPath -like '\Microsoft\Windows\*') { continue }
        $Targets = @(Get-TaskExecTargets -Task $Task)
        if ($Targets.Count -eq 0) { continue }
        $AllGone = $true
        foreach ($Target in $Targets) {
            if (-not (Test-PathProvablyAbsent -Path $Target)) { $AllGone = $false; break }
        }
        if (-not $AllGone) { continue }
        [void]$Items.Add((New-LeftoverItem -Kind "task" -Group "tasks" `
            -Name ([string]$Task.TaskName) -Location ($TaskPath + [string]$Task.TaskName) `
            -ValueName $TaskPath -Target $Targets[0] `
            -Reason "Scheduled to run a program that is not on this PC." `
            -NeedsAdmin $true))
    }
    return @($Items)
}

function Get-FolderSizeBytes {
    param([string]$Path)
    try {
        $Sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        if ($Sum) { return [long]$Sum }
    } catch { }
    return [long]0
}

function Test-FolderInUse {
    <# Is any running process launched from inside $Path? A folder a
       process is running from is not dead, whatever its marker says. #>
    param([string]$Path)
    $Prefix = $Path.TrimEnd('\') + '\'
    foreach ($Process in @(Get-Process -ErrorAction SilentlyContinue)) {
        $Image = $null
        try { $Image = $Process.Path } catch { continue }
        if ($Image -and $Image.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Get-LeftoverAppResidue {
    <#
    .SYNOPSIS
        Squirrel packages their own uninstaller has marked dead.

    .DESCRIPTION
        TWO MARKERS, BOTH REQUIRED. Squirrel.Windows installs an app as
        Update.exe beside versioned app-<version> directories, and when the
        app is uninstalled while files are still in use it cannot finish
        deleting them - so it drops a `.dead` file into the package root
        and leaves the rest for a cleanup that, measured, often never
        happens. On the machine this was built on that was 454 MB.

        `.dead` alone is a filename anything could create. `.dead` beside
        Update.exe is Squirrel's own statement that this package is
        uninstalled, which is evidence rather than inference - the one kind
        of AppData leftover this module accepts. See the module header for
        the kind it declines, and the measurement that decided it.
    #>
    $Items = New-Object System.Collections.ArrayList
    foreach ($Root in @($Script:LeftoverResidueRoots)) {
        if ([string]::IsNullOrWhiteSpace($Root)) { continue }
        $Children = @()
        try {
            $Children = @(Get-ChildItem -LiteralPath $Root -Directory -Force -ErrorAction Stop)
        } catch {
            continue
        }
        foreach ($Folder in $Children) {
            if ($Folder.Name -in @("Microsoft", "Packages", "Temp", "PULSE", "Pulse")) { continue }
            if (Test-LeftoverProtectedPath -Path $Folder.FullName) { continue }
            $Dead = Join-Path $Folder.FullName ".dead"
            $Stub = Join-Path $Folder.FullName "Update.exe"
            $IsDead = $false
            try {
                $IsDead = (Test-Path -LiteralPath $Dead -PathType Leaf -ErrorAction Stop) -and
                          (Test-Path -LiteralPath $Stub -PathType Leaf -ErrorAction Stop)
            } catch {
                $IsDead = $false
            }
            if (-not $IsDead) { continue }
            if (Test-FolderInUse -Path $Folder.FullName) { continue }
            $ProgramData = $env:ProgramData
            $MachineScope = $ProgramData -and
                $Folder.FullName.StartsWith($ProgramData.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)
            [void]$Items.Add((New-LeftoverItem -Kind "residue" -Group "residue" `
                -Name $Folder.Name -Location $Folder.FullName -Target $Stub `
                -Reason "An uninstalled app's files, left behind - its own uninstaller marked this folder dead." `
                -SizeBytes (Get-FolderSizeBytes -Path $Folder.FullName) `
                -NeedsAdmin ([bool]$MachineScope)))
        }
    }
    return @($Items)
}

function Get-ClsidModulePath {
    <# The DLL a CLSID's in-process server loads, or "". #>
    param([string]$Clsid)
    try {
        $Key = Join-Path $Script:LeftoverClsidRoot "$Clsid\InprocServer32"
        $Value = Get-ItemProperty -LiteralPath $Key -Name '(default)' -ErrorAction Stop
        return [string]$Value.'(default)'
    } catch {
        return ""
    }
}

function Test-LeftoverMachineKey {
    param([string]$Location)
    return ($Location -match '^(Registry::)?(HKEY_LOCAL_MACHINE|HKLM)' -or
            $Location -like 'HKLM:*' -or
            $Location -match 'HKEY_CLASSES_ROOT')
}

function Get-LeftoverShellHooks {
    <# Context-menu handlers whose DLL is provably absent, and static shell
       verbs whose command launches a file that is provably absent.

       A BARE MODULE NAME IS NEVER A LEFTOVER. "shell32.dll" or "cmd.exe"
       resolves through a search path, so its absence cannot be proven -
       measured on the machine this was built on, those are most of the
       verbs Windows itself registers. Handlers identified by name rather
       than CLSID are skipped for the same reason: there is no module path
       to check. #>
    $Items = New-Object System.Collections.ArrayList
    $Seen = @{}

    foreach ($Root in @($Script:ContextMenuRoots)) {
        $Children = @()
        try {
            $Children = @(Get-ChildItem -LiteralPath $Root.Path -ErrorAction Stop)
        } catch {
            continue
        }
        foreach ($Child in $Children) {
            $Clsid = ""
            try {
                $Clsid = ([string](Get-ItemProperty -LiteralPath $Child.PSPath -Name '(default)' -ErrorAction Stop).'(default)').Trim()
            } catch { continue }
            if ($Clsid -notmatch '^\{[0-9A-Fa-f\-]{36}\}$') { continue }
            $Module = Get-ClsidModulePath -Clsid $Clsid
            if ([string]::IsNullOrWhiteSpace($Module)) { continue }
            $ModulePath = [System.Environment]::ExpandEnvironmentVariables($Module.Trim().Trim('"'))
            if (-not (Test-PathProvablyAbsent -Path $ModulePath)) { continue }
            $Location = [string]$Child.PSPath
            if ($Seen.ContainsKey($Location)) { continue }
            $Seen[$Location] = $true
            [void]$Items.Add((New-LeftoverItem -Kind "shell-handler" -Group "shell" `
                -Name ("$($Child.PSChildName) ($($Root.Scope))") -Location $Location `
                -Target $ModulePath `
                -Reason "A right-click menu extension whose DLL is not on this PC." `
                -NeedsAdmin (Test-LeftoverMachineKey -Location $Location)))
        }
    }

    foreach ($VerbRoot in @($Script:LeftoverVerbRoots)) {
        $Verbs = @()
        try {
            $Verbs = @(Get-ChildItem -LiteralPath $VerbRoot -ErrorAction Stop)
        } catch {
            continue
        }
        foreach ($Verb in $Verbs) {
            $Command = ""
            try {
                $CommandKey = Join-Path $Verb.PSPath "command"
                $Command = [string](Get-ItemProperty -LiteralPath $CommandKey -Name '(default)' -ErrorAction Stop).'(default)'
            } catch { continue }
            $Target = Get-CommandTargetPath -Command $Command
            if (-not $Target -or -not (Test-PathProvablyAbsent -Path $Target)) { continue }
            $Location = [string]$Verb.PSPath
            if ($Seen.ContainsKey($Location)) { continue }
            $Seen[$Location] = $true
            [void]$Items.Add((New-LeftoverItem -Kind "shell-verb" -Group "shell" `
                -Name $Verb.PSChildName -Location $Location -Target $Target `
                -Reason "A right-click menu entry that launches a program that is not on this PC." `
                -NeedsAdmin (Test-LeftoverMachineKey -Location $Location)))
        }
    }
    return @($Items)
}

function Get-LeftoverItems {
    <# Every leftover, from every scanner. Each scanner is isolated: one
       that throws costs its own category, never the whole report. #>
    $All = New-Object System.Collections.ArrayList
    foreach ($Scanner in @("Get-LeftoverStartupEntries", "Get-LeftoverScheduledTasks",
                           "Get-LeftoverAppResidue", "Get-LeftoverShellHooks")) {
        try {
            foreach ($Item in @(& $Scanner)) { if ($Item) { [void]$All.Add($Item) } }
        } catch {
            Write-Log "LEFTOVERS: $Scanner failed: $($_.Exception.Message)"
        }
    }
    return @($All)
}

function Get-LeftoversReport {
    <# The scan, shaped for the GUI. READ-ONLY. #>
    $Items = @(Get-LeftoverItems)
    $Total = [long]0
    foreach ($Item in $Items) { $Total += [long]$Item.sizeBytes }
    return [PSCustomObject]@{
        generatedAt    = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        items          = $Items
        totalBytes     = $Total
        elevated       = [bool](Test-IsElevatedSession)
        hasBackup      = [bool](Get-LatestLeftoversBackup)
    }
}

# ============================================================
#  BACKUP / REMOVE / RESTORE
# ============================================================
function ConvertTo-NativeRegPath {
    <# A PowerShell registry path in the form reg.exe accepts. #>
    param([Parameter(Mandatory = $true)][string]$Path)
    $P = $Path -replace '^Microsoft\.PowerShell\.Core\\Registry::', '' -replace '^Registry::', ''
    $P = $P -replace '^HKCU:\\?', 'HKCU\' -replace '^HKLM:\\?', 'HKLM\'
    $P = $P -replace '^HKEY_CURRENT_USER', 'HKCU' -replace '^HKEY_LOCAL_MACHINE', 'HKLM'
    $P = $P -replace '^HKEY_USERS', 'HKU' -replace '^HKEY_CLASSES_ROOT', 'HKCR'
    return $P.TrimEnd('\')
}

function Get-RegExe {
    <# reg.exe by ABSOLUTE path. Bare `reg` would resolve through a PATH
       the unelevated user controls, from a process holding the
       administrator token - the same reason core.ps1 anchors its own
       relaunch of powershell.exe. #>
    return (Join-Path ([System.Environment]::GetFolderPath('System')) 'reg.exe')
}

function Invoke-RegExe {
    <#
    .SYNOPSIS
        Run reg.exe and judge it by its EXIT CODE.

    .DESCRIPTION
        `reg import` WRITES ITS SUCCESS MESSAGE TO STDERR. core.ps1 runs
        with $ErrorActionPreference = "Stop", and under that preference
        Windows PowerShell turns any native stderr line redirected with
        2>&1 into a terminating NativeCommandError. So a restore that
        worked threw, was caught, and was reported as a failure - while
        the same line passed under Pester, whose preference is Continue.
        The preference is scoped to this call and the verdict comes from
        $LASTEXITCODE, which is the only thing reg.exe actually promises.
    #>
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $Previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $Output = @(& (Get-RegExe) @Arguments 2>&1 | ForEach-Object { [string]$_ })
        return [PSCustomObject]@{ ExitCode = $LASTEXITCODE; Output = ($Output -join ' ') }
    } finally {
        $ErrorActionPreference = $Previous
    }
}

function Resolve-ClassesKeyHive {
    <# The concrete key behind a HKEY_CLASSES_ROOT path.

       HKCR is a MERGED view of HKCU\Software\Classes over
       HKLM\SOFTWARE\Classes, so deleting through it deletes from whichever
       hive happens to hold the key - and a backup exported through it
       cannot say which hive to put it back into. Every key operation here
       resolves to the real hive first. A path that is not under HKCR (a
       test hive) is returned as it is. #>
    param([Parameter(Mandatory = $true)][string]$Location)

    $Plain = $Location -replace '^Microsoft\.PowerShell\.Core\\Registry::', 'Registry::'
    if ($Plain -notmatch '^Registry::HKEY_CLASSES_ROOT\\(.+)$') { return @($Plain) }
    $Sub = $Matches[1]
    $Found = New-Object System.Collections.ArrayList
    foreach ($Hive in @("Registry::HKEY_CURRENT_USER\Software\Classes", "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Classes")) {
        $Candidate = "$Hive\$Sub"
        try {
            if (Test-Path -LiteralPath $Candidate -ErrorAction Stop) { [void]$Found.Add($Candidate) }
        } catch { }
    }
    return @($Found)
}

function New-LeftoversBackupSet {
    <# A fresh backup set: a registry key for the records and a folder for
       the files. Returns $null when either cannot be created - the caller
       refuses to remove anything without one. #>
    $Stamp = (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
    try {
        $RegRoot = Resolve-UserRegPath $Script:LeftoverBackupRegRoot
        $RegKey = Join-Path $RegRoot $Stamp
        New-Item -Path $RegKey -Force -ErrorAction Stop | Out-Null
        Set-ItemProperty -Path $RegKey -Name "_CreatedAt" -Value (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') -Type String -Force -ErrorAction Stop
        Set-ItemProperty -Path $RegKey -Name "_Restored" -Value 0 -Type DWord -Force -ErrorAction Stop
        $Folder = Join-Path $Script:LeftoverBackupFolderRoot $Stamp
        New-Item -Path $Folder -ItemType Directory -Force -ErrorAction Stop | Out-Null
        return [PSCustomObject]@{ Stamp = $Stamp; RegKey = $RegKey; Folder = $Folder; Seq = 0 }
    } catch {
        Write-ErrorX "Could not create a leftovers backup set - nothing was removed. ($($_.Exception.Message))"
        return $null
    }
}

function Save-LeftoverRecord {
    param(
        [Parameter(Mandatory = $true)]$Set,
        [Parameter(Mandatory = $true)][hashtable]$Record
    )
    $Set.Seq++
    $Name = "{0:D4}_{1}" -f $Set.Seq, $Record.kind
    $Json = ($Record | ConvertTo-Json -Compress -Depth 4)
    Set-ItemProperty -Path $Set.RegKey -Name $Name -Value $Json -Type String -Force -ErrorAction Stop
    return $Name
}

function Backup-LeftoverItem {
    <#
    .SYNOPSIS
        Back up ONE leftover into $Set. Returns the record, or $null.

    .DESCRIPTION
        $null means DO NOT REMOVE. Invoke-LeftoversPurge treats a failed
        backup as a refusal, because a removal whose backup silently failed
        is the one case where "reversible" would be a lie.

        Files and folders are not backed up here - they are MOVED by the
        removal, into this set's folder, which is both the backup and the
        removal in one operation that cannot half-succeed.
    #>
    param(
        [Parameter(Mandatory = $true)]$Set,
        [Parameter(Mandatory = $true)]$Item
    )
    try {
        switch ($Item.kind) {
            "startup-run" {
                $Key = Get-Item -LiteralPath $Item.location -ErrorAction Stop
                $Data = $Key.GetValue($Item.valueName, $null, 'DoNotExpandEnvironmentNames')
                if ($null -eq $Data) { throw "value '$($Item.valueName)' is no longer present" }
                $ValueKind = [string]$Key.GetValueKind($Item.valueName)
                $Record = @{ kind = $Item.kind; location = $Item.location; valueName = $Item.valueName
                             data = [string]$Data; valueKind = $ValueKind; name = $Item.name }
                $RegFile = Join-Path $Set.Folder ("{0:D4}_run.reg" -f ($Set.Seq + 1))
                $Export = Invoke-RegExe -Arguments @("export", (ConvertTo-NativeRegPath $Item.location), $RegFile, "/y")
                if ($Export.ExitCode -eq 0 -and (Test-Path -LiteralPath $RegFile)) { $Record.regFile = $RegFile }
                [void](Save-LeftoverRecord -Set $Set -Record $Record)
                return $Record
            }
            "startup-folder" {
                $Dest = Join-Path $Set.Folder ("{0:D4}_{1}" -f ($Set.Seq + 1), (Split-Path $Item.location -Leaf))
                $Record = @{ kind = $Item.kind; original = $Item.location; backup = $Dest; name = $Item.name }
                [void](Save-LeftoverRecord -Set $Set -Record $Record)
                return $Record
            }
            "residue" {
                $Dest = Join-Path $Set.Folder ("{0:D4}_{1}" -f ($Set.Seq + 1), (Split-Path $Item.location -Leaf))
                $Record = @{ kind = $Item.kind; original = $Item.location; backup = $Dest; name = $Item.name }
                [void](Save-LeftoverRecord -Set $Set -Record $Record)
                return $Record
            }
            "task" {
                $Xml = Export-PulseScheduledTask -TaskPath $Item.valueName -TaskName $Item.name
                if ([string]::IsNullOrWhiteSpace($Xml)) { throw "the task definition could not be exported" }
                $XmlFile = Join-Path $Set.Folder ("{0:D4}_task.xml" -f ($Set.Seq + 1))
                [System.IO.File]::WriteAllText($XmlFile, $Xml, [System.Text.Encoding]::Unicode)
                $Record = @{ kind = $Item.kind; taskPath = $Item.valueName; taskName = $Item.name; xmlFile = $XmlFile; name = $Item.name }
                [void](Save-LeftoverRecord -Set $Set -Record $Record)
                return $Record
            }
            { $_ -in @("shell-handler", "shell-verb") } {
                $Keys = @(Resolve-ClassesKeyHive -Location $Item.location)
                if ($Keys.Count -eq 0) { throw "the key is no longer present" }
                $Exports = New-Object System.Collections.ArrayList
                $Index = 0
                foreach ($Key in $Keys) {
                    $Index++
                    $RegFile = Join-Path $Set.Folder ("{0:D4}_{1}_{2}.reg" -f ($Set.Seq + 1), $Item.kind, $Index)
                    $Result = Invoke-RegExe -Arguments @("export", (ConvertTo-NativeRegPath $Key), $RegFile, "/y")
                    if ($Result.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $RegFile)) {
                        throw "reg.exe could not export $Key ($($Result.Output))"
                    }
                    [void]$Exports.Add(@{ key = $Key; regFile = $RegFile })
                }
                $Record = @{ kind = $Item.kind; exports = @($Exports); name = $Item.name }
                [void](Save-LeftoverRecord -Set $Set -Record $Record)
                return $Record
            }
            default { throw "unknown leftover kind '$($Item.kind)'" }
        }
    } catch {
        Write-ErrorX "Could not back up '$($Item.name)' - it was left in place. ($($_.Exception.Message))"
        return $null
    }
}

function Export-PulseScheduledTask {
    <# The task's XML definition. Wrapped so tests never export a real task. #>
    param([string]$TaskPath, [string]$TaskName)
    return [string](Export-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction Stop)
}

function Unregister-PulseScheduledTask {
    param([string]$TaskPath, [string]$TaskName)
    Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false -ErrorAction Stop
}

function Register-PulseScheduledTask {
    param([string]$TaskPath, [string]$TaskName, [string]$Xml)
    Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Xml $Xml -Force -ErrorAction Stop | Out-Null
}

function Remove-LeftoverItem {
    <# Remove ONE leftover whose backup $Record has already been written.
       Returns $true on success. #>
    param(
        [Parameter(Mandatory = $true)]$Item,
        [Parameter(Mandatory = $true)]$Record
    )
    try {
        switch ($Item.kind) {
            "startup-run" {
                Remove-ItemProperty -LiteralPath $Item.location `
                    -Name (ConvertTo-LiteralPropertyName $Item.valueName) -ErrorAction Stop
            }
            "startup-folder" {
                Move-Item -LiteralPath $Item.location -Destination $Record.backup -Force -ErrorAction Stop
            }
            "residue" {
                Move-Item -LiteralPath $Item.location -Destination $Record.backup -Force -ErrorAction Stop
            }
            "task" {
                Unregister-PulseScheduledTask -TaskPath $Item.valueName -TaskName $Item.name
            }
            { $_ -in @("shell-handler", "shell-verb") } {
                foreach ($Export in @($Record.exports)) {
                    Remove-Item -LiteralPath $Export.key -Recurse -Force -ErrorAction Stop
                }
            }
            default { throw "unknown leftover kind '$($Item.kind)'" }
        }
        return $true
    } catch {
        Write-ErrorX "Could not remove '$($Item.name)': $($_.Exception.Message)"
        return $false
    }
}

function Invoke-LeftoversPurge {
    <#
    .SYNOPSIS
        Remove the selected leftovers - and only the ones that are STILL
        leftovers. Everything removed is backed up first.

    .PARAMETER SelectedIds
        Ids from Get-LeftoversReport. EMPTY REMOVES NOTHING, which is the
        opposite of the bloatware purge and deliberately so: that one has a
        curated catalog to fall back on, and this one has only whatever a
        scan of this machine found. Removing it without the user having
        looked at the list is not a default this should have.
    #>
    param([string[]]$SelectedIds = @())

    Write-SectionHeader "Leftovers Cleaner"

    $Wanted = @($SelectedIds | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_.Trim().ToLowerInvariant() })
    if ($Wanted.Count -eq 0) {
        Write-TaggedLine -Tag "OK" -Text "Nothing was selected, so nothing was removed."
        return [PSCustomObject]@{ Removed = 0; Failed = 0; Gone = 0; Stamp = "" }
    }

    $Current = @(Get-LeftoverItems)
    $Chosen = @($Current | Where-Object { $Wanted -contains $_.id })
    $Gone = $Wanted.Count - $Chosen.Count
    if ($Gone -gt 0) {
        Write-TaggedLine -Tag "KEPT" -Text "$Gone selected item(s) are no longer leftovers - reinstalled or already removed - and were left alone."
    }
    if ($Chosen.Count -eq 0) {
        Write-TaggedLine -Tag "OK" -Text "None of the selected items is still a leftover. Nothing was removed."
        return [PSCustomObject]@{ Removed = 0; Failed = 0; Gone = $Gone; Stamp = "" }
    }

    foreach ($Item in $Chosen) {
        Write-TaggedLine -Tag "FOUND" -Text "$($Item.name)  ->  $($Item.target)"
    }

    if (Test-DryRun "Back up and remove $($Chosen.Count) leftover item(s)") {
        return [PSCustomObject]@{ Removed = $Chosen.Count; Failed = 0; Gone = $Gone; Stamp = "" }
    }

    # THE ORDER IS THE SAFETY PROPERTY: checkpoint, backup set, then per
    # item backup-before-remove.
    New-SystemRestorePoint -Action "Leftovers"
    $Set = New-LeftoversBackupSet
    if (-not $Set) {
        return [PSCustomObject]@{ Removed = 0; Failed = $Chosen.Count; Gone = $Gone; Stamp = "" }
    }

    $Removed = 0
    $Failed = 0
    $Index = 0
    foreach ($Item in $Chosen) {
        $Index++
        Write-GuiStage "[$Index/$($Chosen.Count)] $($Item.name)"
        $Record = Backup-LeftoverItem -Set $Set -Item $Item
        if (-not $Record) { $Failed++; continue }
        if (Remove-LeftoverItem -Item $Item -Record $Record) {
            Write-TaggedLine -Tag "REMOVED" -Text "$($Item.name)  (backed up)"
            $Removed++
        } else {
            $Failed++
        }
    }

    Write-TaggedLine -Tag "INFO" -Text "Backups: $($Set.Folder)  and  $($Script:LeftoverBackupRegRoot)\$($Set.Stamp)"
    Write-TaggedLine -Tag "DONE" -Text "$Removed removed | $Failed not removed | $Gone no longer leftovers"
    return [PSCustomObject]@{ Removed = $Removed; Failed = $Failed; Gone = $Gone; Stamp = $Set.Stamp }
}

function Get-LeftoversBackupSets {
    <# Every backup set, newest first. #>
    $Root = $null
    try { $Root = Resolve-UserRegPath $Script:LeftoverBackupRegRoot } catch { return @() }
    if (-not (Test-Path -LiteralPath $Root)) { return @() }
    return @(Get-ChildItem -LiteralPath $Root -ErrorAction SilentlyContinue |
        Sort-Object PSChildName -Descending)
}

function Get-LatestLeftoversBackup {
    <# The newest set that has not been restored yet, or $null. #>
    foreach ($Set in (Get-LeftoversBackupSets)) {
        $Restored = 0
        try { $Restored = [int](Get-ItemProperty -LiteralPath $Set.PSPath -Name "_Restored" -ErrorAction Stop)._Restored } catch { }
        if ($Restored -eq 0) { return $Set }
    }
    return $null
}

function Restore-LeftoversBackup {
    <#
    .SYNOPSIS
        Put back everything the most recent un-restored purge removed.

    .DESCRIPTION
        Records are replayed in REVERSE order, and each is independent: a
        task whose definition Windows will not re-register (one that ran
        with a stored password it cannot re-supply) is reported and
        skipped rather than stopping the rest. The set is marked restored
        only when every record came back, so a partial restore can be
        retried.
    #>
    Write-SectionHeader "Restore Leftovers"

    $SetKey = Get-LatestLeftoversBackup
    if (-not $SetKey) {
        Write-TaggedLine -Tag "OK" -Text "There is no cleanup to restore."
        return [PSCustomObject]@{ Restored = 0; Failed = 0; Stamp = "" }
    }

    $Props = Get-ItemProperty -LiteralPath $SetKey.PSPath -ErrorAction Stop
    $Names = @($Props.PSObject.Properties |
        Where-Object { $_.Name -match '^\d{4}_' } |
        ForEach-Object { $_.Name } | Sort-Object -Descending)

    if (Test-DryRun "Restore $($Names.Count) leftover item(s) from $($SetKey.PSChildName)") {
        return [PSCustomObject]@{ Restored = $Names.Count; Failed = 0; Stamp = $SetKey.PSChildName }
    }

    $Restored = 0
    $Failed = 0
    foreach ($Name in $Names) {
        $Record = $null
        try { $Record = [string]$Props.$Name | ConvertFrom-Json } catch { }
        if (-not $Record) { $Failed++; continue }
        try {
            switch ($Record.kind) {
                "startup-run" {
                    if (-not (Test-Path -LiteralPath $Record.location)) {
                        New-Item -Path $Record.location -Force -ErrorAction Stop | Out-Null
                    }
                    $Type = if ($Record.valueKind -eq 'ExpandString') { 'ExpandString' } else { 'String' }
                    New-ItemProperty -LiteralPath $Record.location -Name $Record.valueName `
                        -Value $Record.data -PropertyType $Type -Force -ErrorAction Stop | Out-Null
                }
                { $_ -in @("startup-folder", "residue") } {
                    if (Test-Path -LiteralPath $Record.original) {
                        throw "something already exists at $($Record.original)"
                    }
                    $Parent = Split-Path -Path $Record.original -Parent
                    if (-not (Test-Path -LiteralPath $Parent)) {
                        New-Item -Path $Parent -ItemType Directory -Force -ErrorAction Stop | Out-Null
                    }
                    Move-Item -LiteralPath $Record.backup -Destination $Record.original -Force -ErrorAction Stop
                }
                "task" {
                    $Xml = [System.IO.File]::ReadAllText($Record.xmlFile, [System.Text.Encoding]::Unicode)
                    Register-PulseScheduledTask -TaskPath $Record.taskPath -TaskName $Record.taskName -Xml $Xml
                }
                { $_ -in @("shell-handler", "shell-verb") } {
                    foreach ($Export in @($Record.exports)) {
                        $Import = Invoke-RegExe -Arguments @("import", $Export.regFile)
                        if ($Import.ExitCode -ne 0) { throw "reg.exe import failed: $($Import.Output)" }
                    }
                }
                default { throw "unknown record kind '$($Record.kind)'" }
            }
            Write-TaggedLine -Tag "RESTORED" -Text $Record.name
            $Restored++
        } catch {
            Write-ErrorX "Could not restore '$($Record.name)': $($_.Exception.Message)"
            $Failed++
        }
    }

    if ($Failed -eq 0) {
        Set-ItemProperty -LiteralPath $SetKey.PSPath -Name "_Restored" -Value 1 -Type DWord -Force
    }
    Write-TaggedLine -Tag "DONE" -Text "$Restored restored | $Failed could not be restored"
    return [PSCustomObject]@{ Restored = $Restored; Failed = $Failed; Stamp = $SetKey.PSChildName }
}
