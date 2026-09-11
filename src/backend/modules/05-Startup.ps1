#Requires -Version 5.1
<#
.SYNOPSIS
    05-Startup.ps1 - startup program discovery, disable/re-enable and the
    interactive Startup Program Manager.

.DESCRIPTION
    Sources audited: HKCU/HKLM Run keys and the per-user/all-users Startup
    folders. Disabling is always reversible: registry entries are copied to
    HKCU:\Software\Pulse\DisabledStartup before removal, and
    shortcuts are MOVED to %LOCALAPPDATA%\PULSE\Backups\Startup, never deleted.
    Locations are defined in 01-Catalogs.ps1.
#>

# ============================================================
#  LITERAL-NAME HELPER
# ============================================================
function ConvertTo-LiteralPropertyName {
    <# Escapes a registry VALUE NAME so the *-ItemProperty cmdlets match it
       literally.

       Remove-ItemProperty -Name accepts wildcards and has no -LiteralName
       counterpart the way -Path has -LiteralPath. Startup value names come
       from whatever an installer wrote, so a perfectly ordinary entry named
       "Acme Update [x64]" or "Sync*" would match — and DELETE — its
       siblings in the same Run key. Escaping is the only available fix. #>
    param([Parameter(Mandatory = $true)][string]$Name)
    return [System.Management.Automation.WildcardPattern]::Escape($Name)
}

# ============================================================
#  STARTUP ITEM DISCOVERY
# ============================================================
# ============================================================
#  ORIGIN LEDGER (v1.0)
#  Remembers which hive / folder a disabled item was removed from, so
#  re-enabling puts it back where it was instead of defaulting to the
#  current user. See $Script:StartupOriginRegPath in 01-Catalogs.ps1 for
#  why this lives in a sub-key rather than beside the disabled entries.
# ============================================================
function Get-StartupOriginName {
    param(
        [Parameter(Mandatory = $true)][string]$Type,
        [Parameter(Mandatory = $true)][string]$Name
    )
    return "$Type|||$Name"
}

function Save-StartupOrigin {
    <# Best-effort: losing the origin record degrades a later re-enable to
       the old per-user default, which is worse than it could be but far
       better than failing the disable the user actually asked for. #>
    param(
        [Parameter(Mandatory = $true)][string]$Type,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Origin
    )
    try {
        $Path = Resolve-UserRegPath $Script:StartupOriginRegPath
        if (-not (Test-Path $Path)) { New-Item -Path $Path -Force | Out-Null }
        Set-ItemProperty -Path $Path -Name (Get-StartupOriginName -Type $Type -Name $Name) `
            -Value $Origin -Type String -Force -ErrorAction Stop
    } catch {
        Write-Log "Could not record the origin of startup item '$Name' ($Type): $($_.Exception.Message). A later re-enable will fall back to the current user."
    }
}

function Get-StartupOrigin {
    <# The recorded origin, or $null when there is none - an item disabled by
       a pre-1.0 Pulse, or one whose record could not be written. Callers
       must treat $null as "fall back to the per-user location". #>
    param(
        [Parameter(Mandatory = $true)][string]$Type,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $Value = Get-RegValue -Path $Script:StartupOriginRegPath `
        -Name (Get-StartupOriginName -Type $Type -Name $Name)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    return [string]$Value
}

function Remove-StartupOrigin {
    param(
        [Parameter(Mandatory = $true)][string]$Type,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $Path = Resolve-UserRegPath $Script:StartupOriginRegPath
    if (-not (Test-Path $Path)) { return }
    Remove-ItemProperty -Path $Path `
        -Name (ConvertTo-LiteralPropertyName (Get-StartupOriginName -Type $Type -Name $Name)) `
        -ErrorAction SilentlyContinue
}

function Resolve-StartupRestoreTarget {
    <# Where an item should be put back.

       A recorded origin is only honoured if it is one of the KNOWN startup
       locations ($Script:StartupRunKeyPaths / $Script:StartupFolderPaths).
       The record lives in a user-writable hive, and this value is fed
       straight to Set-ItemProperty / Move-Item, so an allow-list is what
       keeps a tampered record from redirecting a write somewhere arbitrary.
       An unrecognised or missing origin falls back to the per-user location,
       which is exactly the pre-1.0 behaviour. #>
    param(
        [Parameter(Mandatory = $true)][string]$Type,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $Known = if ($Type -eq "Registry") { $Script:StartupRunKeyPaths } else { $Script:StartupFolderPaths }
    $Fallback = $Known[0]        # per-user is always the first entry
    $Origin = Get-StartupOrigin -Type $Type -Name $Name
    if (-not $Origin) { return $Fallback }
    foreach ($Candidate in $Known) {
        if ($Origin -eq $Candidate) { return $Candidate }
    }
    Write-Log "Startup item '$Name' ($Type) recorded an unrecognised origin '$Origin' - restoring to '$Fallback' instead."
    return $Fallback
}

function Get-StartupRunKeyItems {
    $Keys = @(
        @{ Hive = "HKCU"; Path = $Script:StartupRunKeyPaths[0] },
        @{ Hive = "HKLM"; Path = $Script:StartupRunKeyPaths[1] }
    )
    $Items = @()
    foreach ($Key in $Keys) {
        if (-not (Test-Path $Key.Path)) { continue }
        $Props = Get-ItemProperty -Path $Key.Path -ErrorAction SilentlyContinue
        if (-not $Props) { continue }
        foreach ($Prop in $Props.PSObject.Properties) {
            # Skip ALL of Get-ItemProperty's synthetic PS* members. Missing
            # 'Drive' here was a real bug: the PSDrive member is a rich
            # PSDriveInfo object (with circular refs), so it both leaked a
            # bogus "PSDrive" startup item AND made ConvertTo-Json -Depth 8 in
            # Write-GuiData recurse forever — hanging the Startup Manager.
            if ($Prop.Name -match '^PS(Path|ParentPath|ChildName|Provider|Drive)$') { continue }
            $Items += [PSCustomObject]@{
                Type    = "Registry"
                Hive    = $Key.Hive
                RegPath = $Key.Path
                Name    = $Prop.Name
                Command = $Prop.Value
                Enabled = $true
            }
        }
    }
    return $Items
}

function Get-StartupFolderItems {
    $Folders = @($Script:StartupFolderPaths)
    $Items = @()
    foreach ($Folder in $Folders) {
        if (-not (Test-Path $Folder)) { continue }
        Get-ChildItem -Path $Folder -File -ErrorAction SilentlyContinue | ForEach-Object {
            $Items += [PSCustomObject]@{
                Type    = "Folder"
                Hive    = ""
                RegPath = $Folder
                Name    = $_.Name
                Command = $_.FullName
                Enabled = $true
            }
        }
    }
    return $Items
}

function Get-DisabledStartupItems {
    $Items = @()
    $DisabledPath = Resolve-UserRegPath $Script:StartupDisabledRegPath
    if (Test-Path $DisabledPath) {
        $Props = Get-ItemProperty -Path $DisabledPath -ErrorAction SilentlyContinue
        if ($Props) {
            foreach ($Prop in $Props.PSObject.Properties) {
                # Skip ALL of Get-ItemProperty's synthetic PS* members. Missing
            # 'Drive' here was a real bug: the PSDrive member is a rich
            # PSDriveInfo object (with circular refs), so it both leaked a
            # bogus "PSDrive" startup item AND made ConvertTo-Json -Depth 8 in
            # Write-GuiData recurse forever — hanging the Startup Manager.
            if ($Prop.Name -match '^PS(Path|ParentPath|ChildName|Provider|Drive)$') { continue }
                $Items += [PSCustomObject]@{
                    Type    = "Registry"
                    Hive    = "HKCU"
                    RegPath = $Script:StartupDisabledRegPath
                    Name    = $Prop.Name
                    Command = $Prop.Value
                    Enabled = $false
                }
            }
        }
    }
    if (Test-Path $Script:StartupBackupFolder) {
        Get-ChildItem -Path $Script:StartupBackupFolder -File -ErrorAction SilentlyContinue | ForEach-Object {
            $Items += [PSCustomObject]@{
                Type    = "Folder"
                Hive    = ""
                RegPath = $Script:StartupBackupFolder
                Name    = $_.Name
                Command = $_.FullName
                Enabled = $false
            }
        }
    }
    return $Items
}

# ============================================================
#  SHARED RESOLUTION HELPERS  (v10.13)
#
#  Declared HERE, in the first module that loads and needs them, and
#  consumed by 17-Leftovers.ps1. The Startup Manager and the Leftovers
#  Cleaner ask the same questions of the same kind of string - "what file
#  does this command launch?", "where does this shortcut point?", "which
#  tasks exist?" - and two copies of that parsing would eventually give a
#  row and its leftover two different answers about the same entry.
# ============================================================
function Get-CommandTargetPath {
    <#
    .SYNOPSIS
        The file a command line names - including one that no longer
        exists.

    .DESCRIPTION
        Two different questions share this function and need different
        answers for an unquoted path with spaces:

          THE FILE EXISTS. The longest leading run that names a real file
          wins, which is how Windows itself resolves
          "C:\Program Files\App\app.exe /q".

          THE FILE DOES NOT. There is no longer a file to find, so the walk
          above finds nothing - and "where does the path end?" can only be
          answered by the executable extension. The leading run through the
          first token ending in .exe / .dll / .lnk and friends is the path;
          a command with no such token is not provable and returns $null.

        Quoted runs, environment variables and trailing arguments are all
        handled. Returns $null rather than guessing.
    #>
    param([string]$Command)

    if ([string]::IsNullOrWhiteSpace($Command)) { return $null }
    $Text = $Command.Trim()

    if ($Text.StartsWith('"')) {
        $End = $Text.IndexOf('"', 1)
        if ($End -le 1) { return $null }
        try {
            return [System.Environment]::ExpandEnvironmentVariables($Text.Substring(1, $End - 1)).Trim()
        } catch {
            return $null
        }
    }

    $Expanded = $Text
    try { $Expanded = [System.Environment]::ExpandEnvironmentVariables($Text) } catch { return $null }

    $Parts = @($Expanded -split ' ')
    for ($Count = $Parts.Count; $Count -ge 1; $Count--) {
        $Candidate = ($Parts[0..($Count - 1)] -join ' ').Trim()
        if ([string]::IsNullOrWhiteSpace($Candidate)) { continue }
        try {
            if (Test-Path -LiteralPath $Candidate -PathType Leaf -ErrorAction Stop) { return $Candidate }
        } catch {
            continue
        }
    }

    $Match = [System.Text.RegularExpressions.Regex]::Match(
        $Expanded, '^(.+?\.(?:exe|dll|com|bat|cmd|lnk|ps1|vbs|js|msi|scr))(?:\s|,|$)',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if ($Match.Success) { return $Match.Groups[1].Value.Trim() }
    return $null
}

function Get-ShortcutTargetPath {
    <# A .lnk file's target path, or $null.

       $null for a shortcut with no FILE target - a Store app addressed by
       identity, a Control Panel item - which is the honest answer: there
       is no path to prove absent, so such a shortcut is never a leftover. #>
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    $Shell = $null
    try {
        $Shell = New-Object -ComObject WScript.Shell
        $Target = [string]$Shell.CreateShortcut($Path).TargetPath
        if ([string]::IsNullOrWhiteSpace($Target)) { return $null }
        return [System.Environment]::ExpandEnvironmentVariables($Target)
    } catch {
        return $null
    } finally {
        if ($Shell) {
            try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($Shell) } catch { }
        }
    }
}

function Get-PulseScheduledTasks {
    <# Every scheduled task this session can see, or nothing.

       A WRAPPER, for two reasons. The Task Scheduler service can be
       disabled by policy, and Get-ScheduledTask throws rather than
       returning nothing - neither the Startup Manager nor a leftovers scan
       may die on that. And it is the seam the tests mock, so no test ever
       enumerates or touches a real task. #>
    try {
        return @(Get-ScheduledTask -ErrorAction Stop)
    } catch {
        Write-Log "Scheduled tasks could not be enumerated: $($_.Exception.Message)"
        return @()
    }
}

function Set-PulseScheduledTaskState {
    <# Enable or disable ONE task. Wrapped so tests mock this rather than
       ever toggling a real task. #>
    param(
        [Parameter(Mandatory = $true)][string]$TaskPath,
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][bool]$Enabled
    )
    if ($Enabled) {
        Enable-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction Stop | Out-Null
    } else {
        Disable-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction Stop | Out-Null
    }
}

# ============================================================
#  SCHEDULED TASKS THAT START AT SIGN-IN OR AT BOOT  (v10.13)
#
#  THE STARTUP MANAGER WAS AUDITING HALF OF STARTUP. Run keys and the
#  Startup folders are where software USED to register itself; a large
#  share of modern third-party autostart is a Task Scheduler entry with a
#  logon trigger instead - measured on one machine, GIGABYTE's control
#  centre registers two of them and Office registers another, and none of
#  the three appeared anywhere in the list that claimed to be auditing boot.
#
#  ONLY LOGON AND BOOT TRIGGERS. A daily updater, a task that fires on
#  unlock or on an event is scheduled work, not startup, and listing it
#  here would make "startup" mean "anything that ever runs".
#
#  \Microsoft\Windows\ IS NEVER LISTED. That tree is the operating
#  system's own maintenance, and a toggle next to it is an invitation to
#  break servicing. A task OUTSIDE that folder that launches something
#  under the Windows directory is excluded too, for the reason the
#  measurement gave: \CreateExplorerShellUnelevatedTask sits at the ROOT
#  of the task library and runs explorer.exe.
#
#  DISABLING IS INHERENTLY REVERSIBLE. Disable-ScheduledTask leaves the
#  definition registered, so unlike a Run value there is nothing to back
#  up and nothing to put back - re-enabling restores it exactly.
# ============================================================
$Script:StartupTaskTriggers = @{
    'MSFT_TaskLogonTrigger' = 'at sign-in'
    'MSFT_TaskBootTrigger'  = 'at boot'
}

function Get-StartupTaskItems {
    <# Third-party tasks triggered at sign-in or boot, shaped like every
       other startup item. RegPath carries the task FOLDER, so the
       "Type|||RegPath|||Name" identity the toggles re-locate items by
       works for tasks unchanged. #>
    $Items = @()
    $SystemRoot = [string]$env:SystemRoot
    foreach ($Task in @(Get-PulseScheduledTasks)) {
        $TaskPath = [string]$Task.TaskPath
        if ($TaskPath -like '\Microsoft\Windows\*') { continue }

        $When = ""
        foreach ($Trigger in @($Task.Triggers)) {
            $Class = ""
            try { $Class = [string]$Trigger.CimClass.CimClassName } catch { }
            if ($Script:StartupTaskTriggers.ContainsKey($Class)) {
                $When = $Script:StartupTaskTriggers[$Class]
                break
            }
        }
        if (-not $When) { continue }

        $Exec = $null
        foreach ($Action in @($Task.Actions)) {
            $Class = ""
            try { $Class = [string]$Action.CimClass.CimClassName } catch { }
            if ($Class -eq 'MSFT_TaskExecAction' -and -not [string]::IsNullOrWhiteSpace([string]$Action.Execute)) {
                $Exec = $Action
                break
            }
        }
        # A task with no program to launch (a COM handler) cannot be named
        # to the user or given an icon, and is not what a person means by
        # "something that starts with Windows".
        if (-not $Exec) { continue }

        $Execute = ([string]$Exec.Execute).Trim()
        $Target = Get-CommandTargetPath -Command $Execute
        if ($Target -and $SystemRoot -and
            $Target.StartsWith($SystemRoot.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $Quoted = if ($Execute.StartsWith('"')) { $Execute } else { '"' + $Execute + '"' }
        $Arguments = [string]$Exec.Arguments
        $Command = if ([string]::IsNullOrWhiteSpace($Arguments)) { $Quoted } else { "$Quoted $Arguments" }

        $Items += [PSCustomObject]@{
            Type    = "Task"
            Hive    = ""
            RegPath = $TaskPath
            Name    = [string]$Task.TaskName
            Command = $Command
            Enabled = ([string]$Task.State -ne 'Disabled')
            Trigger = $When
        }
    }
    return $Items
}

function Get-AllStartupItems {
    return @(Get-StartupRunKeyItems) + @(Get-StartupFolderItems) + @(Get-DisabledStartupItems) +
           @(Get-StartupTaskItems)
}

# ============================================================
#  MEASURED BOOT DELAYS  (v10.13)
#
#  "HIGH IMPACT" WAS A GUESS WEARING A MEASUREMENT'S CLOTHES. The badge
#  came from a rules table - Steam is High because Steam is usually heavy
#  - and it read exactly like a number Pulse had taken. Windows DOES take
#  the number: the Diagnostics-Performance log records every boot's
#  duration (event 100, BootTime in ms) and, for each application that
#  made a boot measurably slower, how much slower (event 101,
#  DegradationTime in ms, with the application's full Path). The field
#  names used here were read from this machine's provider manifest, not
#  recalled.
#
#  WHERE THE LOG ANSWERS, THE BADGE SAYS WHAT IT MEASURED; where it does
#  not, the heuristic stays and says nothing more than it did. Two limits
#  are stated rather than hidden:
#
#    THE LOG NEEDS ADMINISTRATOR. Unelevated, even listing it is refused.
#    Measured: querying it anyway does NOT fail - it answers "no events
#    were found", which is indistinguishable from a healthy machine. So
#    access is established FIRST, with the listing that does refuse, and
#    an unreadable log is reported as unreadable rather than as clean.
#
#    WINDOWS ONLY RECORDS OFFENDERS. Event 101 fires for an app that
#    crossed a degradation threshold. An app with no event is not proven
#    fast, so it keeps its heuristic badge instead of being awarded "0s".
# ============================================================
$Script:BootPerfLogName      = 'Microsoft-Windows-Diagnostics-Performance/Operational'
$Script:BootPerfLookbackDays = 60

#: Host and stub executables that many unrelated programs share. Matching
#: a boot event to a startup entry by FILENAME is only safe when the name
#: identifies one program; two different Update.exe files must never
#: answer for each other.
$Script:BootGenericImageNames = @(
    'update.exe', 'updater.exe', 'setup.exe', 'launcher.exe', 'rundll32.exe',
    'cmd.exe', 'powershell.exe', 'pwsh.exe', 'wscript.exe', 'cscript.exe',
    'msiexec.exe', 'svchost.exe', 'conhost.exe', 'explorer.exe', 'java.exe',
    'javaw.exe', 'node.exe', 'python.exe', 'pythonw.exe', 'electron.exe'
)

function Get-BootPerformanceLogState {
    <# 'ok', 'disabled', 'needs-admin' or 'unavailable'. See the header for
       why this is asked BEFORE the events are queried. #>
    try {
        $Log = Get-WinEvent -ListLog $Script:BootPerfLogName -ErrorAction Stop
        if (-not $Log.IsEnabled) { return 'disabled' }
        return 'ok'
    } catch {
        $Message = [string]$_.Exception.Message
        if ($_.Exception -is [System.UnauthorizedAccessException] -or
            $Message -match 'unauthori[sz]ed|access is denied') {
            return 'needs-admin'
        }
        return 'unavailable'
    }
}

function Read-BootPerformanceEvents {
    <# Boot (100) and application-delay (101) events since $Since, as
       plain objects. The seam the tests mock. #>
    param([datetime]$Since, [int]$MaxEvents = 400)
    $Filter = @{ LogName = $Script:BootPerfLogName; Id = @(100, 101); StartTime = $Since }
    try {
        return @(Get-WinEvent -FilterHashtable $Filter -MaxEvents $MaxEvents -ErrorAction Stop |
            ForEach-Object { [PSCustomObject]@{ Id = [int]$_.Id; TimeCreated = $_.TimeCreated; Xml = $_.ToXml() } })
    } catch {
        if ([string]$_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { return @() }
        throw
    }
}

function ConvertFrom-BootEventXml {
    <# One event's EventData as a name -> value table. Read by the Name
       ATTRIBUTE, never by position: the schema is versioned, and a field
       added in a later build must not shift every value after it. #>
    param([string]$Xml)
    $Data = @{}
    if ([string]::IsNullOrWhiteSpace($Xml)) { return $Data }
    try {
        $Doc = [xml]$Xml
        foreach ($Node in @($Doc.Event.EventData.Data)) {
            if ($Node -isnot [System.Xml.XmlElement]) { continue }
            $Name = $Node.GetAttribute('Name')
            if ($Name) { $Data[$Name] = [string]$Node.InnerText }
        }
    } catch {
        return @{}
    }
    return $Data
}

function ConvertTo-BootPathKey {
    <# A path reduced to what two spellings of the same file share: no
       drive letter, no \Device\HarddiskVolumeN prefix, lower case. #>
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    $P = $Path.Trim().Trim('"')
    $P = $P -replace '^\\\\\?\\', ''
    $P = $P -replace '^\\Device\\HarddiskVolume\d+', ''
    $P = $P -replace '^[A-Za-z]:', ''
    return $P.ToLowerInvariant()
}

function Get-BootPerformanceData {
    <#
    .SYNOPSIS
        What Windows measured about recent boots. READ-ONLY.

    .DESCRIPTION
        Returns Available, Reason ('ok' / 'disabled' / 'needs-admin' /
        'unavailable'), LastBootMs, AverageBootMs (the newest ten), Boots,
        and Apps - one entry per application event 101 named, with Count,
        AverageDelayMs, MaxDelayMs and LastSeen.
    #>
    $Result = [PSCustomObject]@{
        Available = $false; Reason = ""; LastBootMs = $null; AverageBootMs = $null
        Boots = 0; Apps = @()
    }
    $State = Get-BootPerformanceLogState
    $Result.Reason = $State
    if ($State -ne 'ok') { return $Result }

    $Events = @()
    try {
        $Events = @(Read-BootPerformanceEvents -Since (Get-Date).AddDays(-$Script:BootPerfLookbackDays))
    } catch {
        $Result.Reason = 'unavailable'
        return $Result
    }

    $Boots = New-Object System.Collections.ArrayList
    $Apps = @{}
    foreach ($BootEvent in $Events) {
        $Data = ConvertFrom-BootEventXml -Xml ([string]$BootEvent.Xml)
        if ([int]$BootEvent.Id -eq 100) {
            $Ms = 0
            if ([int]::TryParse([string]$Data['BootTime'], [ref]$Ms) -and $Ms -gt 0) {
                [void]$Boots.Add([PSCustomObject]@{ When = $BootEvent.TimeCreated; Ms = $Ms })
            }
        } elseif ([int]$BootEvent.Id -eq 101) {
            $Delay = 0
            [void][int]::TryParse([string]$Data['DegradationTime'], [ref]$Delay)
            $Path = [string]$Data['Path']
            $Name = [string]$Data['Name']
            $Key = ConvertTo-BootPathKey -Path $Path
            if (-not $Key) { $Key = "name:" + $Name.ToLowerInvariant() }
            if (-not $Apps.ContainsKey($Key)) {
                $Apps[$Key] = [PSCustomObject]@{
                    Path = $Path; Name = $Name; FriendlyName = [string]$Data['FriendlyName']
                    Delays = (New-Object System.Collections.ArrayList); LastSeen = $BootEvent.TimeCreated
                }
            }
            [void]$Apps[$Key].Delays.Add($Delay)
            if ($BootEvent.TimeCreated -gt $Apps[$Key].LastSeen) { $Apps[$Key].LastSeen = $BootEvent.TimeCreated }
        }
    }

    $Ordered = @($Boots | Sort-Object When -Descending)
    if ($Ordered.Count -gt 0) {
        $Result.LastBootMs = [int]$Ordered[0].Ms
        $Recent = @($Ordered | Select-Object -First 10)
        $Result.AverageBootMs = [int][Math]::Round((($Recent | Measure-Object Ms -Average).Average))
    }
    $Result.Boots = $Ordered.Count
    $Result.Apps = @($Apps.Values | ForEach-Object {
        $Stats = $_.Delays | Measure-Object -Average -Maximum
        [PSCustomObject]@{
            Path           = $_.Path
            Name           = $_.Name
            FriendlyName   = $_.FriendlyName
            Count          = [int]$Stats.Count
            AverageDelayMs = [int][Math]::Round($Stats.Average)
            MaxDelayMs     = [int]$Stats.Maximum
            LastSeen       = $_.LastSeen
        }
    })
    $Result.Available = $true
    return $Result
}

function Find-StartupBootDelay {
    <# The measured delay for one startup item, or $null.

       BY PATH FIRST, and a device-path spelling of the same file counts.
       BY FILENAME only when exactly one measured application has that name
       and the name is not a shared host or stub - see
       $Script:BootGenericImageNames. A bare command ("rundll32.exe ...")
       never matches: its real payload is an argument. #>
    param($Item, [object[]]$Apps)

    if (-not $Apps -or @($Apps).Count -eq 0) { return $null }
    $Target = $null
    if ($Item.Type -eq 'Folder') {
        $Target = Get-ShortcutTargetPath -Path ([string]$Item.Command)
    } else {
        $Target = Get-CommandTargetPath -Command ([string]$Item.Command)
    }
    if ([string]::IsNullOrWhiteSpace($Target) -or $Target -notmatch '^[A-Za-z]:\\') { return $null }

    $Key = ConvertTo-BootPathKey -Path $Target
    foreach ($App in @($Apps)) {
        if ((ConvertTo-BootPathKey -Path ([string]$App.Path)) -eq $Key) { return $App }
    }

    $Leaf = [System.IO.Path]::GetFileName($Target).ToLowerInvariant()
    if ($Script:BootGenericImageNames -contains $Leaf) { return $null }
    $ByName = @($Apps | Where-Object { $_.Name -and ([string]$_.Name).ToLowerInvariant() -eq $Leaf })
    if ($ByName.Count -eq 1) { return $ByName[0] }
    return $null
}

function Get-MeasuredBootImpact {
    <# A measured delay on the same three-step scale the heuristic uses, so
       sorting and badge colours mean the same thing for both. #>
    param([int]$DelayMs)
    if ($DelayMs -ge 3000) { return 'High' }
    if ($DelayMs -ge 1000) { return 'Medium' }
    return 'Low'
}

function Get-BootSummary {
    <# The report-level half of Get-BootPerformanceData, for the GUI. #>
    param($Boot)
    if (-not $Boot) { $Boot = Get-BootPerformanceData }
    return [PSCustomObject]@{
        available     = [bool]$Boot.Available
        reason        = [string]$Boot.Reason
        lastBootMs    = $Boot.LastBootMs
        averageBootMs = $Boot.AverageBootMs
        boots         = [int]$Boot.Boots
        measuredApps  = @($Boot.Apps).Count
    }
}

# ============================================================
#  STARTUP OPTIMIZER — recommendation engine (v6.3, safety-tiered in v10.3)
#
#  THREE TIERS, EVALUATED IN THIS ORDER:
#    1. PROTECTED  never recommended for disabling, whatever else matches
#    2. Disable    known boot-time offenders
#    3. Keep       recognised-but-harmless publishers
#  Anything unmatched falls through to 'Review'.
#
#  WHY A THIRD TIER EXISTS. Until v10.3 there were only two lists and the
#  DISABLE list was checked first, on the reasoning that a known heavy app
#  should not be shadowed by a coincidental keep-pattern match. That
#  ordering is right for the Disable-vs-Keep question and wrong for safety:
#  it means any pattern that accidentally matches a sound driver, an input
#  helper or a security agent recommends disabling it, and the keep rule
#  written specifically to protect that component never gets consulted. The
#  cost of the two mistakes is not symmetric — over-recommending a game
#  launcher wastes nothing, while telling a user to disable their audio
#  stack or their antivirus breaks the machine and can't be spotted from
#  the row's own wording. So the protected tier goes FIRST and is absolute,
#  and the Disable-before-Keep precedence is preserved below it, unchanged.
# ============================================================

# Components that must never be recommended for disabling. Deliberately
# broader than the old keep list: it now covers the whole audio stack
# (every common vendor HDA helper, not just Realtek), input and IME,
# pointing devices, accessibility, storage/RAID drivers and endpoint
# security. These still appear in the manager and can still be toggled by
# hand — this governs what Pulse RECOMMENDS and what "Optimize Startup"
# will touch in bulk, which is the part the user is trusting.
$Script:StartupProtectedRules = @(
    @{ Pattern = 'defender|windowssecurity|securityhealth|msmpeng|msascui|smartscreen';
       Reason = "Windows Security component — disabling it weakens malware protection." }
    @{ Pattern = 'securityagent|antivirus|endpoint protection|crowdstrike|sentinelone|malwarebytes|sophos|eset|kaspersky|bitdefender|mcafee|norton|trendmicro|carbonblack';
       Reason = "Security / endpoint-protection agent — must keep running from boot to protect the machine." }
    # The audio stack, in full. A missing tray helper here does not merely
    # lose an equaliser: on many laptops it is what performs jack-detection
    # and output switching, so disabling it can leave the machine silent.
    @{ Pattern = 'realtek|rtkaud|rthdvcpl|ravcpl|rtkngui|audiodg|hdaudio|hd audio|audio.*(service|manager|control|effects)|nahimic|waves.*(maxx|audio)|maxxaudio|dolby|dtsapo|dts.*audio|sonic.*(studio|suite)|smartaudio|conexant|cxuiusvc|idt.*audio|sttray|cirrus|creative.*audio|sound.*(blaster|research)|asio';
       Reason = "Audio driver / sound-device helper — jack detection, device switching and effects depend on it." }
    @{ Pattern = 'ctfmon|tabtip|imecmnt|ime\b|inputpersonalization|textinputhost';
       Reason = "Windows text-input / IME subsystem — required for keyboard layout and language switching." }
    @{ Pattern = 'synaptics|syntpenh|elan|etdctrl|alps.*point|touchpad|precision touchpad|trackpoint';
       Reason = "Touchpad / pointing-device driver — gestures, scrolling and its settings page depend on it." }
    @{ Pattern = 'wacom|huion|xp-?pen|tablet.*(driver|service)';
       Reason = "Graphics tablet driver — pen input stops working the moment it is not running." }
    @{ Pattern = 'narrator|magnify|osk\.exe|on-?screen keyboard|accessibility|assistive';
       Reason = "Accessibility tool — for some users this is how the machine is operated at all." }
    @{ Pattern = 'iastor|rapidstorage|intel.*rapid|raid.*(monitor|service)|amd.*raid';
       Reason = "Storage / RAID controller helper — monitors the array your drives depend on." }
    @{ Pattern = 'bthserv|bluetooth.*(service|stack)|widcomm|intel.*bluetooth';
       Reason = "Bluetooth stack component — paired keyboards, mice and headsets depend on it at sign-in." }
    @{ Pattern = 'lenovo.*(power|battery)|dell.*(power|battery)|hp.*(power|battery)|power.*manager|thermal.*(manager|framework)';
       Reason = "Vendor power / thermal manager — battery life and fan behaviour are controlled here." }
)

$Script:StartupDisableRules = @(
    @{ Pattern = 'onedrive';                              Impact = 'Medium'; Reason = "Cloud sync — keeps syncing in the background; launch it manually or sign in to files.com when you actually need it." }
    @{ Pattern = 'dropbox';                                Impact = 'Medium'; Reason = "Cloud sync client — adds boot time for a service you can start on demand." }
    @{ Pattern = 'steam';                                  Impact = 'High';   Reason = "Game launcher with background update checks — a common multi-second boot delay." }
    @{ Pattern = 'epicgameslauncher|epic games';           Impact = 'High';   Reason = "Game launcher — heavy background process not needed until you actually play." }
    @{ Pattern = 'battle\.net|blizzard';                   Impact = 'High';   Reason = "Game launcher with an always-on updater service." }
    @{ Pattern = 'origin|ea desktop|eadesktop';            Impact = 'High';   Reason = "Game launcher — safe to start manually instead of at every boot." }
    @{ Pattern = 'riot client|riotclient';                 Impact = 'Medium'; Reason = "Game launcher background updater." }
    @{ Pattern = 'ubisoft connect|uplay';                  Impact = 'Medium'; Reason = "Game launcher background updater." }
    @{ Pattern = 'discord';                                Impact = 'Medium'; Reason = "Chat client — convenient always-on, but it's pure boot-time overhead if you open it manually anyway." }
    @{ Pattern = 'spotify';                                Impact = 'Medium'; Reason = "Music client — no reason to launch before you're ready to listen." }
    @{ Pattern = 'skype';                                  Impact = 'Medium'; Reason = "Chat client that rarely needs to be running before sign-in finishes." }
    @{ Pattern = 'teams|squirrel\.exe.*teams';             Impact = 'High';   Reason = "Electron-based chat app — one of the heaviest common boot-time offenders." }
    @{ Pattern = 'slack';                                  Impact = 'Medium'; Reason = "Electron-based chat app — noticeable boot-time cost for a background presence." }
    @{ Pattern = 'zoom';                                   Impact = 'Low';    Reason = "Meeting client — only needed right before a call." }
    @{ Pattern = 'adobe.*(updater|arm\.exe|armsvc)|adobearm'; Impact = 'Low'; Reason = "Adobe's background updater — checks for updates you can trigger manually instead." }
    @{ Pattern = 'itunes|applemobiledevicehelper|ituneshelper'; Impact = 'Medium'; Reason = "Apple device helper — only useful while an iPhone/iPad is actually connected." }
    @{ Pattern = 'quicktime';                               Impact = 'Low';    Reason = "Legacy media helper rarely needed by modern apps." }
    @{ Pattern = 'googleupdate|googlechromeautolaunch|gupdate'; Impact = 'Low'; Reason = "Chrome's background updater — Chrome updates itself fine when it launches." }
    @{ Pattern = 'msedgeupdate|microsoftedgeupdate';        Impact = 'Low';    Reason = "Edge's background updater — Edge updates itself fine when it launches." }
    @{ Pattern = 'cortana';                                 Impact = 'Low';    Reason = "Legacy Cortana shell integration — safe to disable on most modern setups." }
    @{ Pattern = 'yourphone|phonelink';                     Impact = 'Low';    Reason = "Phone Link — only useful if you actively use phone/PC linking." }
    @{ Pattern = 'creativecloud|cc[_ ]?library|coreSync';   Impact = 'High';   Reason = "Adobe Creative Cloud desktop — one of the heaviest known startup offenders." }
    @{ Pattern = 'javaupdater|jusched';                      Impact = 'Low';    Reason = "Java's background updater — safe to check manually instead." }
    # Telemetry only. `nvcontainer` was dropped from this pattern in v10.3:
    # NVIDIA Display Container LS is what backs the control panel and the
    # driver's own settings, so recommending it for disabling was advice that
    # broke display configuration to save a few megabytes.
    @{ Pattern = 'nvidia.*telemetry|nvtelemetry';            Impact = 'Low';  Reason = "NVIDIA telemetry helper — the display driver itself does not need it at boot." }
)

$Script:StartupKeepRules = @(
    @{ Pattern = 'defender|windowssecurity|securityhealth|msmpeng'; Reason = "Windows Security — disabling weakens malware protection." }
    @{ Pattern = 'realtek|rtkaud|audio.*service|nahimic';           Reason = "Audio driver tray helper — needed for sound device switching/effects to work correctly." }
    @{ Pattern = 'synaptics|elan|touchpad|precision touchpad';       Reason = "Touchpad/precision-input driver — gestures and settings depend on it." }
    @{ Pattern = 'nvidia.*(tray|settings)|nvtray|nvidia share';      Reason = "GPU control panel tray — lightweight and needed for display/overlay settings." }
    @{ Pattern = 'radeon software|amd.*(tray|external)';             Reason = "GPU control panel tray — lightweight and needed for display/overlay settings." }
    @{ Pattern = 'ctfmon';                                            Reason = "Windows input/IME subsystem — required for text input switching." }
    @{ Pattern = 'securityagent|antivirus|endpoint protection|crowdstrike|sentinelone|malwarebytes'; Reason = "Security/endpoint-protection agent — should stay running from boot." }
    @{ Pattern = 'wacom|huion';                                       Reason = "Graphics tablet driver — needed immediately for pen input to work." }
    # v10.13: the Startup Manager lists sign-in TASKS now, and Office's two
    # live under \Microsoft\Office\ - outside the protected Windows tree.
    # Matched by BINARY rather than by the word "Office", which any
    # third-party tool may carry in its name.
    @{ Pattern = 'officec2rclient\.exe|sdxhelper\.exe';               Reason = "Microsoft Office's own updater — turning it off stops Office receiving security fixes." }
)

# Pre-compiled once at module load, not re-compiled on every -match call
# against every item - cheap either way at typical startup-list sizes, but
# this is the correct pattern for "fast lookups, never heavy work per item"
# and keeps Get-StartupRecommendation's per-item cost to pure in-memory
# regex evaluation with zero I/O.
$Script:_RegexOpts = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase -bor `
    [System.Text.RegularExpressions.RegexOptions]::Compiled
foreach ($Rule in $Script:StartupProtectedRules) { $Rule.Regex = [regex]::new($Rule.Pattern, $Script:_RegexOpts) }
foreach ($Rule in $Script:StartupDisableRules)   { $Rule.Regex = [regex]::new($Rule.Pattern, $Script:_RegexOpts) }
foreach ($Rule in $Script:StartupKeepRules)      { $Rule.Regex = [regex]::new($Rule.Pattern, $Script:_RegexOpts) }

function Get-StartupRecommendation {
    <# Returns @{ Recommendation='Disable'|'Keep'|'Review'; Impact='High'|
       'Medium'|'Low'; Reason=<string>; Protected=<bool> } for one
       Get-AllStartupItems entry. Pure in-memory string/regex work - no
       registry, filesystem or network access, so this is intentionally
       cheap no matter how many startup items are being scored.

       Tier order is the safety contract - see the note above the rule
       lists. Protected wins over everything, absolutely; below it, Disable
       still beats Keep exactly as before. #>
    param($Item)
    $Hay = "$($Item.Name) $($Item.Command)"
    foreach ($Rule in $Script:StartupProtectedRules) {
        if ($Rule.Regex.IsMatch($Hay)) {
            return @{ Recommendation = 'Keep'; Impact = 'Low'; Reason = $Rule.Reason; Protected = $true }
        }
    }
    foreach ($Rule in $Script:StartupDisableRules) {
        if ($Rule.Regex.IsMatch($Hay)) {
            return @{ Recommendation = 'Disable'; Impact = $Rule.Impact; Reason = $Rule.Reason; Protected = $false }
        }
    }
    foreach ($Rule in $Script:StartupKeepRules) {
        if ($Rule.Regex.IsMatch($Hay)) {
            return @{ Recommendation = 'Keep'; Impact = 'Low'; Reason = $Rule.Reason; Protected = $false }
        }
    }
    return @{
        Recommendation = 'Review'
        Impact         = 'Medium'
        Reason         = "Not a recognized publisher — check what it is before disabling it."
        Protected      = $false
    }
}

$Script:StartupImpactRank = @{ High = 0; Medium = 1; Low = 2 }

function Get-StartupReportData {
    <# The Startup Manager's full dataset: every discovered item plus its
       recommendation, sorted enabled-first then by impact severity - the
       items most worth acting on land at the top of the GUI's list. Each
       item carries a stable `Id` ("Type|||RegPath|||Name") that
       Resolve-StartupItemByEncodedId uses to re-locate the exact same item
       on a later toggle call (a fresh process, with no memory of this
       scan). #>
    param($Boot = $null)

    # Read ONCE per report, not once per row. -Boot lets the dispatcher
    # share one read between this and the report-level summary.
    if ($null -eq $Boot) { $Boot = Get-BootPerformanceData }
    $Result = @()
    foreach ($It in @(Get-AllStartupItems)) {
        $Rec = Get-StartupRecommendation -Item $It
        $Impact = $Rec.Impact
        $DelayMs = $null
        $DelayMaxMs = $null
        $DelaySamples = 0
        $Delay = $null
        if ($Boot -and $Boot.Available) { $Delay = Find-StartupBootDelay -Item $It -Apps $Boot.Apps }
        if ($Delay) {
            $DelayMs = [int]$Delay.AverageDelayMs
            $DelayMaxMs = [int]$Delay.MaxDelayMs
            $DelaySamples = [int]$Delay.Count
            $Impact = Get-MeasuredBootImpact -DelayMs $DelayMs
        }
        $Result += [PSCustomObject]@{
            Id              = "$($It.Type)|||$($It.RegPath)|||$($It.Name)"
            Name            = $It.Name
            # The label, beside the identifier rather than instead of it -
            # see Get-StartupDisplayName. `Id` is built from `Name`, so
            # rewriting that field would break every toggle.
            DisplayName     = (Get-StartupDisplayName -Name $It.Name)
            # Whether the program this entry launches is still installed.
            # Six of fifteen were not, on the machine this was measured
            # on; see Test-StartupTargetPresent.
            TargetPresent   = (Test-StartupTargetPresent -Command $It.Command)
            Type            = $It.Type
            Command         = $It.Command
            Enabled         = [bool]$It.Enabled
            Recommendation  = $Rec.Recommendation
            Impact          = $Impact
            # MEASURED where Windows recorded this entry slowing a boot
            # (see Get-BootPerformanceData), the heuristic otherwise.
            ImpactMeasured  = [bool]$Delay
            BootDelayMs     = $DelayMs
            BootDelayMaxMs  = $DelayMaxMs
            BootDelaySamples = $DelaySamples
            Trigger         = [string]$It.Trigger
            Reason          = $Rec.Reason
            # Surfaced to the GUI so a protected component can be labelled as
            # such in its row, rather than looking like an ordinary "Safe to
            # Keep" suggestion the user might reasonably overrule.
            Protected       = [bool]$Rec.Protected
        }
    }
    return $Result | Sort-Object `
        @{ Expression = { if ($_.Enabled) { 0 } else { 1 } } }, `
        @{ Expression = { $Script:StartupImpactRank[$_.Impact] } }, `
        Name
}

function Resolve-StartupItemByEncodedId {
    <# Reverses Get-StartupReportData's Id back into the live item object
       Disable-StartupItem/Enable-StartupItem expect, by re-scanning and
       matching on (Type, RegPath, Name) - the same identity triple, never
       a stale snapshot from a previous process. #>
    param([string]$EncodedId)
    $Parts = $EncodedId -split '\|\|\|', 3
    if ($Parts.Count -lt 3) { return $null }
    $Type, $RegPath, $Name = $Parts
    return (Get-AllStartupItems | Where-Object {
        $_.Type -eq $Type -and $_.RegPath -eq $RegPath -and $_.Name -eq $Name
    } | Select-Object -First 1)
}

# ============================================================
#  WHAT THE ROW IS CALLED, AS OPPOSED TO WHAT IT IS KEYED BY
#
#  A STARTUP ENTRY'S NAME IS AN IDENTIFIER, NOT A LABEL. It is whatever
#  string an installer wrote into a Run key, and installers write what is
#  convenient for them: Electron's builder writes "electron.app.Notion",
#  Edge writes "MicrosoftEdgeAutoLaunch_" plus a 32-character machine
#  hash, and a Startup-folder entry is named by its file, ".lnk" and all.
#  Measured on one ordinary machine, three of fifteen rows read as
#  internal plumbing.
#
#  That matters more here than it would in most lists, because the name is
#  the ONLY part of a startup row a person can match against something
#  they recognise - the command is a path and the type is a category. A
#  row reading "electron.app.Notion" is asking the user to decide about
#  software it has declined to name.
#
#  THE NAME ITSELF IS NEVER TOUCHED. `Id` is "Type|||RegPath|||Name" and
#  Resolve-StartupItemByEncodedId re-locates the item by that exact
#  triple, so rewriting Name would break every toggle. This produces a
#  SEPARATE DisplayName; the raw one still travels, and the GUI shows it
#  in the row's tooltip so nothing is hidden.
#
#  THREE GENERIC RULES AND ONE SMALL MAP, and the split is deliberate.
#  The generic rules are mechanical and safe - drop a shortcut extension,
#  drop a launcher-framework prefix, drop a trailing hash. What they
#  cannot do is separate words in a CamelCase identifier, and a blanket
#  case-split is actively harmful on this evidence: it turns
#  "RtkAudUService" into "Rtk Aud U Service", "SignalRgb" into "Signal
#  Rgb" and "iTunesHelper" into "i Tunes Helper". So the handful of
#  well-known machine-generated names get a curated entry instead, which
#  is the same reasoning tools/fetch_app_icons.py records for preferring a
#  hand-written map over fuzzy matching.
# ============================================================

#: Prefixes packaging frameworks put in front of an app's own name.
$Script:StartupNamePrefixes = @("electron.app.", "com.squirrel.")

#: Machine-generated Run key names -> what the product is actually called.
#: Keyed on the stem AFTER the generic rules have run, so the Edge entry
#: is matched once its hash has been dropped rather than per machine.
$Script:StartupNameMap = @{
    "MicrosoftEdgeAutoLaunch" = "Microsoft Edge AutoLaunch"
    "MicrosoftEdgeUpdateTaskMachineCore" = "Microsoft Edge Update"
    "OneDriveSetup"           = "OneDrive Setup"
    "GoogleDriveFS"           = "Google Drive"
    "com.mysql.installer"     = "MySQL Installer"
}

function Get-StartupDisplayName {
    <#
    .SYNOPSIS
        A startup entry's raw Name, cleaned up for a human to read.

    .DESCRIPTION
        Returns the original string unchanged when none of the rules
        apply, which is the common case: most installers do write a
        product name. Never returns empty - a row with no label at all is
        worse than one with an ugly label.
    #>
    param([string]$Name)

    if ([string]::IsNullOrWhiteSpace($Name)) { return $Name }
    $Clean = $Name.Trim()

    # 1. A Startup FOLDER entry is named by its file. The extension is
    #    file-system detail, not part of what the program is called.
    foreach ($Extension in @(".lnk", ".url", ".bat", ".cmd", ".exe")) {
        if ($Clean.EndsWith($Extension, [System.StringComparison]::OrdinalIgnoreCase)) {
            $Clean = $Clean.Substring(0, $Clean.Length - $Extension.Length)
            break
        }
    }

    # 2. A packaging framework's namespace prefix.
    foreach ($Prefix in $Script:StartupNamePrefixes) {
        if ($Clean.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $Clean = $Clean.Substring($Prefix.Length)
            break
        }
    }

    # 3. A TRAILING MACHINE HASH. Twelve hex characters is the floor, and
    #    it is chosen to be safely above real words: "DEADBEEF" is eight,
    #    and no product name this has to survive is twelve hex characters
    #    long. Anchored to the end after an underscore or a dash, so a
    #    name that merely CONTAINS hex ("Direct3D") is untouched.
    $Clean = [System.Text.RegularExpressions.Regex]::Replace(
        $Clean, '[_\-][0-9A-Fa-f]{12,}$', '')

    if ([string]::IsNullOrWhiteSpace($Clean)) { return $Name }

    # 4. The curated map, for the identifiers no mechanical rule can space
    #    out correctly. Case-insensitive so a build that changes the
    #    capitalisation still matches.
    foreach ($Key in $Script:StartupNameMap.Keys) {
        if ($Clean -eq $Key -or $Clean -ieq $Key) {
            return $Script:StartupNameMap[$Key]
        }
    }
    return $Clean
}

function Test-StartupTargetPresent {
    <#
    .SYNOPSIS
        Does this entry's command still name a program that exists?

    .DESCRIPTION
        THE ANSWER IS "NO" MORE OFTEN THAN ANYONE EXPECTS, and that is the
        finding rather than an edge case. Uninstalling software on Windows
        does not reliably remove its Run key: measured on one ordinary
        machine, SIX of fifteen startup entries pointed at binaries that
        are no longer on the disk - Adobe, iTunes, BlueStacks, Riot,
        Sideloadly and a Squirrel package carrying its own ".dead"
        uninstall marker. Windows tries to launch all six at every boot.

        The GUI could not say so. Its icon column asked Windows for the
        artwork, got nothing, and drew the neutral executable mark - which
        is the correct picture and reads as a BROKEN ICON rather than as
        "this points at software you have removed". Six unexplained grey
        boxes look like a defect in the tool; six rows captioned
        "target missing" are six entries worth turning off.

        Resolution is deliberately SHALLOW here and does not follow
        shortcuts or Squirrel stubs - that ladder lives in
        utils/nativeicons.py, where the icon comes from, and duplicating
        it in PowerShell would give the badge and the artwork two
        different opinions about the same row. This answers the cheap
        question the badge needs: is there a file at the path this command
        names? A `.lnk` is a file, so a Startup-folder row is present
        whenever its shortcut is.
    #>
    param([string]$Command)

    if ([string]::IsNullOrWhiteSpace($Command)) { return $false }
    $Text = $Command.Trim()

    $Candidates = New-Object System.Collections.ArrayList
    if ($Text.StartsWith('"')) {
        $End = $Text.IndexOf('"', 1)
        if ($End -gt 1) { [void]$Candidates.Add($Text.Substring(1, $End - 1)) }
    } else {
        # The longest LEADING run that names a real file wins - the same
        # walk nativeicons does, and for the same reason: splitting on the
        # first space turns "C:\Program Files\App\app.exe /q" into
        # "C:\Program", which exists on no machine.
        [void]$Candidates.Add($Text)
        $Parts = $Text -split " "
        for ($i = $Parts.Count; $i -ge 1; $i--) {
            [void]$Candidates.Add(($Parts[0..($i - 1)] -join " "))
        }
    }

    foreach ($Candidate in $Candidates) {
        $Path = $Candidate.Trim()
        if ([string]::IsNullOrWhiteSpace($Path)) { continue }
        try {
            $Expanded = [System.Environment]::ExpandEnvironmentVariables($Path)
            # -ErrorAction Stop, EXPLICITLY. Test-Path does not return
            # $false for a string containing '|', '<' or '>' - it THROWS
            # ArgumentException("Illegal characters in path") - and
            # whether that reaches this catch depends on the ambient
            # $ErrorActionPreference. It is "Stop" inside core.ps1 and
            # "Continue" under Pester, so without this the guard is
            # correct in production and silently inert in the tests,
            # which is the worst arrangement available.
            if (Test-Path -LiteralPath $Expanded -PathType Leaf -ErrorAction Stop) {
                return $true
            }
        } catch {
            continue        # a malformed path is not a present one
        }
    }
    return $false
}

function Show-StartupItemsList {
    param([array]$Items)
    if ($Items.Count -eq 0) {
        Write-Info "No startup items found."
        return
    }
    for ($i = 0; $i -lt $Items.Count; $i++) {
        $it = $Items[$i]
        $StatusTag = if ($it.Enabled) { "ENABLED " } else { "DISABLED" }
        $Color = if ($it.Enabled) { "Green" } else { "DarkGray" }
        # The CLEANED name here too, so the console and the GUI call the
        # same row the same thing. The list is a picker - the number is
        # what the user types - so the identifier it was keyed by is not
        # information this line has to carry.
        $Label = Get-StartupDisplayName -Name $it.Name
        $Missing = if (Test-StartupTargetPresent -Command $it.Command) { "" } else { "  [target missing]" }
        Write-Host ("   [{0,2}] [{1}] {2}  ({3}){4}" -f ($i + 1), $StatusTag, $Label, $it.Type, $Missing) -ForegroundColor $Color
    }
}

# ============================================================
#  DISABLE / RE-ENABLE (reversible, dry-run aware)
# ============================================================
function Disable-StartupItem {
    param($Item)
    if (Test-DryRun "Disable startup item '$($Item.Name)' ($($Item.Type)) - backed up for re-enable") { return }
    try {
        # FIRST, and returning. A task must never reach the branches below:
        # the Folder branch MOVES $Item.Command, and a task's Command is a
        # command line rather than a file.
        if ($Item.Type -eq "Task") {
            Set-PulseScheduledTaskState -TaskPath $Item.RegPath -TaskName $Item.Name -Enabled $false
            Write-Success "Disabled scheduled task '$($Item.Name)' - it stays registered, so re-enabling puts it back exactly."
            return
        }
        if ($Item.Type -eq "Registry") {
            $DisabledPath = Resolve-UserRegPath $Script:StartupDisabledRegPath
            if (-not (Test-Path $DisabledPath)) {
                New-Item -Path $DisabledPath -Force | Out-Null
            }
            Set-ItemProperty -Path $DisabledPath -Name $Item.Name -Value $Item.Command -Force
            # Record the hive BEFORE the removal: $Item.RegPath is the only
            # place that knowledge exists, and after the delete there is no
            # way to recover whether this was an all-users (HKLM) entry.
            Save-StartupOrigin -Type "Registry" -Name $Item.Name -Origin $Item.RegPath
            Remove-ItemProperty -Path $Item.RegPath `
                -Name (ConvertTo-LiteralPropertyName $Item.Name) -ErrorAction Stop
            $Scope = if ($Item.Hive -eq "HKLM") { " (all users)" } else { "" }
            Write-Success "Disabled startup entry '$($Item.Name)'$Scope - backed up for re-enable."
        } else {
            if (-not (Test-Path $Script:StartupBackupFolder)) {
                New-Item -Path $Script:StartupBackupFolder -ItemType Directory -Force | Out-Null
            }
            # Same reasoning as the registry branch: the containing folder is
            # what distinguishes a per-user shortcut from an all-users one,
            # and moving the file destroys that evidence.
            Save-StartupOrigin -Type "Folder" -Name $Item.Name `
                -Origin (Split-Path -Path $Item.Command -Parent)
            # -LiteralPath: a shortcut called "Game [2].lnk" is an ordinary
            # filename, but -Path would read the brackets as a character class
            # and move nothing.
            Move-Item -LiteralPath $Item.Command -Destination $Script:StartupBackupFolder -Force -ErrorAction Stop
            Write-Success "Disabled startup shortcut '$($Item.Name)' (moved to backup folder)."
        }
    } catch {
        Write-ErrorX "Could not disable '$($Item.Name)': $($_.Exception.Message)"
    }
}

function Enable-StartupItem {
    <# Restores an item to the location it was DISABLED FROM, not to the
       current user. Before v1.0 both branches hard-coded the per-user
       target, so an all-users entry (HKLM Run, or a ProgramData shortcut)
       came back as a current-user-only entry: it still launched for whoever
       clicked re-enable, and silently stopped launching for every other
       account on the machine. Nothing reported that, because the operation
       itself succeeded.

       Restoring to HKLM / ProgramData needs elevation, which the dispatcher
       already requires for StartupEnableItem
       ($Script:AdminRequiredTasks, 01-Catalogs.ps1). #>
    param($Item)
    if (Test-DryRun "Re-enable startup item '$($Item.Name)' ($($Item.Type)) at its original location") { return }
    try {
        # Before Resolve-StartupRestoreTarget, which knows only Run keys
        # and Startup folders - see the matching note in Disable-StartupItem.
        if ($Item.Type -eq "Task") {
            Set-PulseScheduledTaskState -TaskPath $Item.RegPath -TaskName $Item.Name -Enabled $true
            Write-Success "Re-enabled scheduled task '$($Item.Name)'."
            return
        }
        $Target = Resolve-StartupRestoreTarget -Type $Item.Type -Name $Item.Name
        if ($Item.Type -eq "Registry") {
            if (-not (Test-Path $Target)) { New-Item -Path $Target -Force | Out-Null }
            Set-ItemProperty -Path $Target -Name $Item.Name -Value $Item.Command -Force
            Remove-ItemProperty -Path (Resolve-UserRegPath $Script:StartupDisabledRegPath) `
                -Name (ConvertTo-LiteralPropertyName $Item.Name) -ErrorAction Stop
            $Scope = if ($Target -like "HKLM:*") { " for all users" } else { "" }
            Write-Success "Re-enabled startup entry '$($Item.Name)'$Scope."
        } else {
            # A recorded origin folder that has since been deleted would make
            # Move-Item fail; recreate it rather than silently relocating the
            # shortcut to a different scope than it came from.
            if (-not (Test-Path $Target)) {
                New-Item -Path $Target -ItemType Directory -Force | Out-Null
            }
            Move-Item -LiteralPath $Item.Command -Destination $Target -Force -ErrorAction Stop
            $Scope = if ($Target -eq $Script:StartupFolderPaths[1]) { " for all users" } else { "" }
            Write-Success "Re-enabled startup shortcut '$($Item.Name)'$Scope."
        }
        # Only once the restore actually succeeded - a stale origin record is
        # harmless, but dropping it before a failed move would lose the scope
        # for good on the retry.
        Remove-StartupOrigin -Type $Item.Type -Name $Item.Name
    } catch {
        Write-ErrorX "Could not re-enable '$($Item.Name)': $($_.Exception.Message)"
    }
}

# ============================================================
#  INTERACTIVE STARTUP PROGRAM MANAGER (console mode only)
# ============================================================
function Show-StartupProgramManager {
    do {
        Write-Banner "STARTUP PROGRAM MANAGER"
        $AllItems      = Get-AllStartupItems
        $EnabledCount  = ($AllItems | Where-Object { $_.Enabled }).Count
        $DisabledCount = ($AllItems | Where-Object { -not $_.Enabled }).Count
        Write-Info "$EnabledCount enabled / $DisabledCount disabled startup item(s) detected."
        Write-Host ""
        Show-StartupItemsList -Items $AllItems
        Write-Divider
        Write-Host "   [D]  Disable an item" -ForegroundColor White
        Write-Host "   [E]  Re-enable a disabled item" -ForegroundColor White
        Write-Host "   [T]  Open Task Manager (Startup tab)" -ForegroundColor White
        Write-Host "   [R]  Refresh list" -ForegroundColor DarkGray
        Write-Host "   [X]  Back to Main Menu" -ForegroundColor DarkGray
        Write-Divider
        $Choice = Read-Choice -Prompt "   Select an action" -Valid @('d','e','t','r','x')

        switch ($Choice) {
            'd' {
                if (($AllItems | Where-Object { $_.Enabled }).Count -eq 0) {
                    Write-Warn "No enabled items to disable."; Start-Sleep -Seconds 1; continue
                }
                $Idx = Read-NumericChoice -Prompt "   Enter item number to disable (list above)" -Max $AllItems.Count
                if ($null -ne $Idx) {
                    $Target = $AllItems[$Idx - 1]
                    if ($Target.Enabled) {
                        if (Ask-User "Disable '$($Target.Name)'" "Prevents this program from launching at sign-in. A backup is kept so it can be re-enabled.") {
                            Disable-StartupItem -Item $Target
                        }
                    } else {
                        Write-AlreadyOK "'$($Target.Name)' is already disabled."
                    }
                } else {
                    Write-Warn "Invalid item number."
                }
                Start-Sleep -Seconds 1
            }
            'e' {
                if (($AllItems | Where-Object { -not $_.Enabled }).Count -eq 0) {
                    Write-Warn "No disabled items to re-enable."; Start-Sleep -Seconds 1; continue
                }
                $Idx = Read-NumericChoice -Prompt "   Enter item number to re-enable (list above)" -Max $AllItems.Count
                if ($null -ne $Idx) {
                    $Target = $AllItems[$Idx - 1]
                    if (-not $Target.Enabled) {
                        Enable-StartupItem -Item $Target
                    } else {
                        Write-AlreadyOK "'$($Target.Name)' is already enabled."
                    }
                } else {
                    Write-Warn "Invalid item number."
                }
                Start-Sleep -Seconds 1
            }
            't' {
                Write-Info "Opening Task Manager..."
                Start-Process -FilePath (Get-SystemBinary "taskmgr") -ArgumentList "/7" -ErrorAction SilentlyContinue
            }
            'r' { }
            'x' { return }
        }
    } while ($true)
}
