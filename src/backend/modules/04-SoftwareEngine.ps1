#Requires -Version 5.1
<#
.SYNOPSIS
    04-SoftwareEngine.ps1 - the winget/Chocolatey deployment engine.

.DESCRIPTION
    Smart-Deploy is the single entry point for installing/upgrading any app.
    It is fed exclusively by the catalogs in 01-Catalogs.ps1 (data-driven:
    no per-app functions), and it honors three global modes:
      - $Script:NonInteractive : GUI task mode - never prompts, never pops
        browsers or the Microsoft Store mid-silent-run.
      - $Script:DryRun (-WhatIf): reports what WOULD be installed/upgraded
        and returns Status='Success' without touching the system.
      - Bulk/BulkMethod: category-wide auto or manual handling.

    Also: version probing, store-app detection, hardware matching (GPU /
    motherboard vendor apps) and the interactive category processor.
#>

# ============================================================
#  STORE APP DETECTION
# ============================================================
function Is-StoreApp {
    param([string]$AppId)
    return $AppId -match '^\w{12}$'
}

# ============================================================
#  INSTALLED / LATEST VERSION DETECTION
# ============================================================
# Bulk-batch cache (Id/Name -> {Installed, Available}) populated once per
# batch by Initialize-WingetBatchCache (see Process-AppCategory below) from
# a single `winget list` call. $null outside an active batch, so single
# (non-bulk) probes keep querying winget live as before - only Process-
# AppCategory's bulk loops set/clear it, so staleness can never leak into
# an unrelated individual install later in the same session.
$Script:WingetBatchCache = $null

function Initialize-WingetBatchCache {
    <#
    .SYNOPSIS
        Builds the one-shot Id/Name -> {Installed, Available} lookup used
        by Get-InstalledVersion/Get-LatestVersion during a bulk deployment,
        from a single `winget list` call instead of one winget process per
        app. `winget list`'s column layout (Name/Id/Version/Available/
        Source) is identical to `winget upgrade`'s, so the existing
        ConvertFrom-WingetUpgradeTable parser is reused as-is.
    #>
    $Script:WingetBatchCache = @{ ById = @{}; ByName = @{} }
    if (-not $global:WingetAvailable) { return }
    try {
        $Raw = & (Get-WingetPath) list --accept-source-agreements --disable-interactivity 2>$null
        foreach ($Item in (ConvertFrom-WingetUpgradeTable -Raw $Raw)) {
            $Entry = @{ Installed = $Item.CurrentVersion; Available = $Item.AvailableVersion }
            $Script:WingetBatchCache.ById[$Item.Id]     = $Entry
            $Script:WingetBatchCache.ByName[$Item.Name] = $Entry
        }
    } catch {
        Write-Log "Winget batch cache build failed: $($_.Exception.Message)"
    }
}

function Get-InstalledVersion {
    param([string]$AppId, [string]$AppName)

    if (Is-StoreApp $AppId) {
        try {
            $pkg = Get-AppxPackage -Name $AppId -ErrorAction SilentlyContinue
            if ($pkg) { return $pkg.Version }
        } catch {}
        return $null
    }

    if (-not $global:WingetAvailable) { return $null }  # no winget -> no probe

    if ($Script:WingetBatchCache) {
        # Active bulk batch: the one-shot `winget list` cache is
        # authoritative - querying it instead of spawning a fresh winget
        # process per app is the entire point of the batch cache.
        if ($Script:WingetBatchCache.ById.ContainsKey($AppId)) { return $Script:WingetBatchCache.ById[$AppId].Installed }
        if ($Script:WingetBatchCache.ByName.ContainsKey($AppName)) { return $Script:WingetBatchCache.ByName[$AppName].Installed }
        return $null
    }

    $Lines = & (Get-WingetPath) list --id $AppId --exact --accept-source-agreements --disable-interactivity 2>$null
    if (-not $Lines) {
        $Lines = & (Get-WingetPath) list --query $AppName --exact --accept-source-agreements --disable-interactivity 2>$null
    }
    if (-not $Lines) { return $null }

    foreach ($Line in $Lines) {
        $Trimmed = $Line.Trim()
        if ([string]::IsNullOrWhiteSpace($Trimmed)) { continue }
        # NOT a `\s{2,}` column split: winget only right-pads columns to
        # align them for a real interactive console. The instant Pulse
        # captures its output (every call site here does), that alignment
        # can collapse to single spaces, so a 2+-space split silently
        # merges the Id/Version/Source columns into the Name column and
        # this always returned null - the "instant skip" fast path quietly
        # never firing, every deploy falling through to a live winget
        # upgrade call it didn't need to make. IDs and versions never
        # contain spaces, so instead: split on ANY whitespace and read the
        # token AFTER an exact AppId match as the version.
        $Tokens = [regex]::Split($Trimmed, '\s+')
        # AppId match takes strict priority and is checked in its own pass:
        # winget package IDs (e.g. "Git.Git") never collide with a Name
        # column value, whereas Pulse's own catalog display name
        # occasionally could (e.g. "7-Zip") if it's a single word AND
        # happens to precede the real Id token - checking AppId first,
        # fully, before ever falling back to AppName avoids that.
        for ($i = 0; $i -lt $Tokens.Count - 1; $i++) {
            if ($Tokens[$i] -eq $AppId) { return $Tokens[$i + 1] }
        }
        for ($i = 0; $i -lt $Tokens.Count - 1; $i++) {
            if ($Tokens[$i] -eq $AppName) { return $Tokens[$i + 1] }
        }
    }
    return $null
}

function Get-LatestVersion {
    param([string]$AppId)
    if (Is-StoreApp $AppId) {
        # "Store" (not "Unknown") is the deliberate sentinel meaning "can't
        # probe a real version, treat any installed copy as current" -
        # Smart-Deploy's store-app branch reads it exactly that way.
        # winget's msstore source, when reachable, gives a real version to
        # compare against Get-AppxPackage's installed version instead.
        if (-not $global:WingetAvailable) { return "Store" }
        $Lines = & (Get-WingetPath) show --id $AppId --exact --source msstore --accept-source-agreements --disable-interactivity 2>$null
        if (-not $Lines) { return "Store" }
        foreach ($Line in $Lines) {
            if ($Line -match '^\s*Version:\s*(\S+)') { return $Matches[1] }
        }
        return "Store"
    }
    if (-not $global:WingetAvailable) { return "Unknown" }  # no winget -> no probe

    if ($Script:WingetBatchCache) {
        if ($Script:WingetBatchCache.ById.ContainsKey($AppId)) {
            $Entry = $Script:WingetBatchCache.ById[$AppId]
            if (-not [string]::IsNullOrWhiteSpace($Entry.Available)) { return $Entry.Available }
            return $Entry.Installed   # blank Available in `winget list` -> no pending upgrade, already latest
        }
        return "Unknown"   # not installed - the batch cache has no manifest data to probe for uninstalled apps
    }

    $Lines = & (Get-WingetPath) show --id $AppId --exact --accept-source-agreements --disable-interactivity 2>$null
    if (-not $Lines) { return "Unknown" }
    foreach ($Line in $Lines) {
        if ($Line -match '^\s*Version:\s*(\S+)') { return $Matches[1] }
    }
    return "Unknown"
}

# ============================================================
#  UPDATE CENTER — winget upgrade scan (v6.3)
# ============================================================
function ConvertFrom-WingetUpgradeTable {
    <#
    .SYNOPSIS
        Parses `winget upgrade`'s aligned text table into an array of
        PSCustomObject { Id, Name, CurrentVersion, AvailableVersion }.
        Source-agnostic - used for both the default multi-source scan and
        the msstore-scoped one below, since the column layout is identical.

    .DESCRIPTION
        `winget upgrade` has no --output json in the stable CLI, so this
        parses its aligned text table the same way every serious community
        tool does: read the column START OFFSETS from the header row itself
        (Name / Id / Version / Available[/ Source]), then slice each data
        row by those offsets - never by splitting on whitespace, which
        breaks the instant an app name contains a space (most of them do).
        Malformed/unrecognized rows are skipped individually rather than
        aborting the whole scan - a partial result beats a hard failure.

        TWO TABLES, NOT ONE (v10.3). `winget upgrade` prints a SECOND table
        after the first, introduced by "The following packages have an
        upgrade available, but require explicit targeting for upgrade:" -
        and that table has its OWN column widths, because winget re-measures
        them per table. This used to lock onto the first header and slice
        every later line at those offsets, which had two consequences:
        the packages in the second table (Discord, on the machine this was
        found on) were mangled or lost, and the introducing SENTENCE was
        itself sliced into a phantom package that reached the Update Center
        as a row reading "The following packages have an upgrade avail" ->
        "r upgrade:". Headers are therefore re-detected as they appear and
        the offsets re-read from each one.

        REJECTING PROSE. That phantom row is why a data row now has to prove
        it is one: in an aligned table every column starts after padding, so
        the character immediately before each column offset is a space. Prose
        that happens to be long enough to reach those offsets is not aligned
        to them and fails the check. This is a structural test rather than a
        blacklist of winget's current sentences, which would need updating
        every time the CLI reworded one.
    #>
    param([string[]]$Raw)

    if (-not $Raw) { return @() }
    $Lines = @($Raw | Where-Object { $_ -and $_.Trim() -ne '' })

    $NameStart = -1; $IdStart = -1; $VersionStart = -1; $AvailableStart = -1; $SourceStart = -1
    $HaveHeader = $false
    $Items = @()

    foreach ($Line in $Lines) {
        # A new header resets the column geometry for everything after it.
        if ($Line -match '^Name\s+Id\s+Version\s+Available') {
            $NameStart      = $Line.IndexOf("Name")
            $IdStart        = $Line.IndexOf("Id")
            $VersionStart   = $Line.IndexOf("Version")
            $AvailableStart = $Line.IndexOf("Available")
            $SourceStart    = $Line.IndexOf("Source")   # may be -1 (msstore-only listings omit it)
            $HaveHeader = $true
            continue
        }
        # Nothing before the first header is data ("No installed package
        # found...", source-agreement banners, progress residue).
        if (-not $HaveHeader) { continue }
        if ($Line -match '^-+$') { continue }                      # the ---- rule under a header
        if ($Line -match '^\d+\s+upgrades?\s+available') { continue }
        if ($Line -match '^\d+\s+package\(s\)') { continue }
        if ($Line.Length -le $IdStart) { continue }

        # Column-alignment proof - see REJECTING PROSE above.
        $Aligned = $true
        foreach ($Boundary in @($IdStart, $VersionStart, $AvailableStart, $SourceStart)) {
            if ($Boundary -le 0 -or $Boundary -ge $Line.Length) { continue }
            if ($Line[$Boundary - 1] -ne ' ') { $Aligned = $false; break }
        }
        if (-not $Aligned) { continue }

        try {
            $AvailEnd = if ($SourceStart -gt $AvailableStart) { $SourceStart } else { $Line.Length }
            $Name = $Line.Substring($NameStart, [Math]::Min($IdStart, $Line.Length) - $NameStart).Trim()
            $Id   = $Line.Substring($IdStart, [Math]::Min($VersionStart, $Line.Length) - $IdStart).Trim()
            $Ver  = $Line.Substring($VersionStart, [Math]::Min($AvailableStart, $Line.Length) - $VersionStart).Trim()
            $Avail = $Line.Substring($AvailableStart, [Math]::Min($AvailEnd, $Line.Length) - $AvailableStart).Trim()
            if ([string]::IsNullOrWhiteSpace($Id) -or [string]::IsNullOrWhiteSpace($Name)) { continue }
            # "have an upgrade available but require explicit targeting" -
            # winget still lists them with a version of "Unknown"; keep them
            # (--include-unknown asked for exactly this) but the frontend
            # audit reads better with the raw values, so pass through as-is.
            $Items += [PSCustomObject]@{
                Id              = $Id
                Name            = $Name
                CurrentVersion  = $Ver
                AvailableVersion = $Avail
            }
        } catch {
            continue   # one unparsable row never aborts the whole scan
        }
    }
    return $Items
}

# ============================================================
#  DEEP INSTALLED-PROGRAM INVENTORY (v10.3)
# ============================================================
# Registry Uninstall keys, all four of them, plus the Appx catalogue. This
# is the SAME set Windows' own "Installed apps" page shows, which is the
# bar: an updater that only knows what winget's default listing knows is
# blind to everything installed by an MSI or a bundled setup that never
# registered with a package source.
#
# The four hives are not interchangeable and all four are required:
#   HKLM ...\Uninstall                      64-bit machine-wide installs
#   HKLM ...\WOW6432Node\...\Uninstall      32-bit machine-wide installs
#   HKCU ...\Uninstall                      per-user installs (Chrome, Teams,
#                                           anything installed without admin)
#   HKCU ...\WOW6432Node\...\Uninstall      per-user 32-bit; rare but real
# A 32-bit PowerShell would see the WOW6432Node view AS the plain path and
# silently enumerate it twice while missing the 64-bit set entirely, so both
# paths are always listed explicitly and the results de-duplicated by key.
$Script:UninstallKeyPaths = @(
    @{ Path = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall";              Scope = "Machine"; Arch = "X64" }
    @{ Path = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall";  Scope = "Machine"; Arch = "X86" }
    @{ Path = "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall";              Scope = "User";    Arch = "X64" }
    @{ Path = "HKCU:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall";  Scope = "User";    Arch = "X86" }
)

function Get-InstalledProgramInventory {
    <#
    .SYNOPSIS
        Every program installed on this machine, from the registry Uninstall
        keys (32-bit and 64-bit, machine and user) plus Windows Apps.

    .DESCRIPTION
        ARP VISIBILITY RULES ARE APPLIED, not skipped. A raw enumeration of
        these keys is not an app list - roughly a third of the entries are
        things Windows deliberately hides: MSI patch/hotfix records, driver
        payloads, and components marked SystemComponent. Listing them would
        not be "more thorough", it would bury the user's actual software in
        several hundred rows of noise and inflate every count in the report.
        The filter below is the same one the Settings app applies:
          - a DisplayName is required (nameless keys are bookkeeping)
          - SystemComponent = 1 is hidden by definition
          - an entry with a ParentKeyName / ParentDisplayName is a component
            of another product, already represented by its parent
          - ReleaseType of Update/Hotfix/Security Update is a patch record

        THE `WingetKey` FIELD is the join that makes the whole deep scan
        work. winget synthesises an id for anything it finds in ARP but
        cannot match to a package - `ARP\Machine\X64\<registry key name>` -
        and for Store packages `MSIX\<PackageFullName>`. Building the same
        string here means the inventory can be correlated against winget's
        own listing EXACTLY, by identity rather than by fuzzy name matching,
        so "is this program known to a package source?" is answered
        precisely instead of guessed.

        Read-only throughout: no key is opened for write, nothing is
        mutated, and every access is -ErrorAction SilentlyContinue because a
        single ACL-protected vendor key must not abort the inventory.
    #>
    $Items = @()
    $Seen = @{}

    foreach ($Key in $Script:UninstallKeyPaths) {
        if (-not (Test-Path $Key.Path)) { continue }
        $Children = @(Get-ChildItem -Path $Key.Path -ErrorAction SilentlyContinue)
        foreach ($Child in $Children) {
            $P = $null
            try { $P = Get-ItemProperty -Path $Child.PSPath -ErrorAction Stop } catch { continue }
            if (-not $P) { continue }

            $Name = "$($P.DisplayName)".Trim()
            if ([string]::IsNullOrWhiteSpace($Name)) { continue }
            if ("$($P.SystemComponent)" -eq "1") { continue }
            if (-not [string]::IsNullOrWhiteSpace("$($P.ParentKeyName)")) { continue }
            if (-not [string]::IsNullOrWhiteSpace("$($P.ParentDisplayName)")) { continue }
            if ("$($P.ReleaseType)" -match '^(Update|Hotfix|Security Update|ServicePack)$') { continue }

            $WingetKey = "ARP\$($Key.Scope)\$($Key.Arch)\$($Child.PSChildName)"
            if ($Seen.ContainsKey($WingetKey)) { continue }
            $Seen[$WingetKey] = $true

            $Items += [PSCustomObject]@{
                Name       = $Name
                Version    = "$($P.DisplayVersion)".Trim()
                Publisher  = "$($P.Publisher)".Trim()
                Source     = "Registry"
                Scope      = $Key.Scope
                Arch       = $Key.Arch
                WingetKey  = $WingetKey
            }
        }
    }

    # Windows Apps. -PackageTypeFilter Main excludes framework/resource
    # packages, which are dependencies rather than things a user installed;
    # NonRemovable/system packages are left in because they DO appear in the
    # Store's update list and genuinely can have updates.
    try {
        foreach ($Pkg in @(Get-AppxPackage -PackageTypeFilter Main -ErrorAction SilentlyContinue)) {
            if ($Pkg.IsFramework) { continue }
            $Display = "$($Pkg.Name)".Trim()
            if ([string]::IsNullOrWhiteSpace($Display)) { continue }
            $WingetKey = "MSIX\$($Pkg.PackageFullName)"
            if ($Seen.ContainsKey($WingetKey)) { continue }
            $Seen[$WingetKey] = $true
            $Items += [PSCustomObject]@{
                Name       = $Display
                Version    = "$($Pkg.Version)".Trim()
                Publisher  = "$($Pkg.Publisher)".Trim()
                Source     = "Store"
                Scope      = "User"
                Arch       = "$($Pkg.Architecture)"
                WingetKey  = $WingetKey
            }
        }
    } catch {
        # Appx is unavailable in some constrained/Server SKUs. The registry
        # half of the inventory is still perfectly valid, so degrade rather
        # than fail the whole scan.
        Write-Log "Deep inventory: Get-AppxPackage unavailable - $($_.Exception.Message)"
    }

    return $Items
}

function Get-WingetPackageIndex {
    <#
    .SYNOPSIS
        ONE `winget list` call, turned into an Id -> {Name, Installed,
        Available} lookup covering every package winget can see.

    .DESCRIPTION
        This is the fast half of the update scan and the reason it no longer
        feels frozen. `winget list` resolves against winget's LOCAL source
        cache - it measured 0.9s here against 13s for `winget upgrade`,
        which pays for a network manifest round trip - and it already
        populates the Available column for anything with a pending upgrade.
        So the first wave of real results can be on screen in about a
        second, and the slow authoritative pass becomes a top-up rather than
        the thing the user waits on.

        Parsed with ConvertFrom-WingetUpgradeTable because `winget list` and
        `winget upgrade` share one column layout - which is exactly why that
        parser was written source-agnostic.
    #>
    $Index = @{}
    if (-not $global:WingetAvailable) { return $Index }
    try {
        $Raw = & (Get-WingetPath) list --accept-source-agreements --disable-interactivity 2>$null
        foreach ($Item in (ConvertFrom-WingetUpgradeTable -Raw $Raw)) {
            if ([string]::IsNullOrWhiteSpace($Item.Id)) { continue }
            $Index[$Item.Id] = $Item
        }
    } catch {
        Write-Log "winget package index build failed: $($_.Exception.Message)"
    }
    return $Index
}

function Test-RealUpgradeAvailable {
    <# True when an `Available` column value represents a genuine pending
       upgrade. winget prints a literal "Unknown" for packages whose
       installed version it cannot determine, and an empty cell for
       already-current ones; treating either as an update would fill the
       Update Center with rows that upgrade to nothing. #>
    param([string]$Current, [string]$Available)
    if ([string]::IsNullOrWhiteSpace($Available)) { return $false }
    if ($Available -eq "Unknown") { return $false }
    if ($Available -eq $Current) { return $false }
    return $true
}

function Invoke-DeepUpdateScan {
    <#
    .SYNOPSIS
        The Update Center's scan: a complete installed-program inventory,
        matched against every update source, streamed to the caller as
        results are found rather than delivered in one lump at the end.

    .DESCRIPTION
        FOUR PHASES, ORDERED BY LATENCY - fastest first, so the list starts
        filling immediately instead of after the slowest call returns. The
        old scan ran the 13-second `winget upgrade` first and showed nothing
        until it finished, which is the entire "feels broken" complaint:

          1. Deep inventory      ~0.3s  every installed program (both
                                        registry architectures, both hives,
                                        plus Windows Apps)
          2. winget list         ~0.9s  local correlation; every package with
                                        a pending upgrade is streamed here,
                                        so real rows appear ~1s in
          3. winget upgrade      ~13s   the authoritative network pass, with
                                        --include-unknown; tops up anything
                                        phase 2 could not resolve
          4. winget upgrade
             --source msstore    ~0.6s  Store packages, which are dropped
                                        from the unscoped listing unless the
                                        msstore source agreement is accepted
                                        in a scoped call (see the note that
                                        was on Get-WingetUpgradeList)

        De-duplicated by Id across all phases, first writer winning, so a
        row streamed early is never contradicted by a later phase - the
        frontend can render on arrival without rows shuffling underneath the
        user's cursor.

        -OnItem / -OnStage are optional. Called with one argument each, they
        let the GUI dispatcher stream without this function knowing anything
        about the ##PULSE## wire format; the console menu passes neither and
        gets the same return value.

        Returns @{ Updates; Inventory; MatchedCount; UnmatchedCount } - the
        counts are what let the caller report honestly on coverage instead
        of implying that everything without an update has an update source.
    #>
    param(
        [scriptblock]$OnItem,
        [scriptblock]$OnStage
    )

    # ArrayList, not a PowerShell array: the collector below is a closure
    # over it, and `$arr += x` inside a scriptblock rebinds a COPY in the
    # scriptblock's own scope rather than appending to the caller's - the
    # classic silent "nothing accumulated" bug. .Add() mutates the one
    # instance, so there is only ever one list.
    $Collected = [System.Collections.ArrayList]::new()
    $SeenIds = @{}

    $Stage = {
        param([string]$Text)
        if ($OnStage) { & $OnStage $Text }
    }
    # ONE process snapshot for the whole scan, taken before the first row
    # streams. Every collected update is annotated with whether the app is
    # RUNNING RIGHT NOW, because that is the single fact that decides
    # whether applying it will succeed cleanly or fight a file lock - and
    # it is a fact the user can act on (save your work) only if they are
    # told it BEFORE they press the button, not in the log afterwards.
    #
    # Taken once rather than per row: enumerating processes is the
    # expensive half of the question, and asking it 40 times would add
    # visible seconds to a scan whose whole design is about latency.
    $ProcSnapshot = @()

    $Collect = {
        param($Item)
        if (-not $Item -or [string]::IsNullOrWhiteSpace($Item.Id)) { return }
        if ($SeenIds.ContainsKey($Item.Id)) { return }
        $SeenIds[$Item.Id] = $true
        $Running = @(Resolve-AppProcesses -AppId $Item.Id -AppName $Item.Name -Snapshot $ProcSnapshot)
        # Added to the object rather than replacing it, so the field is
        # present on every streamed row AND on the final DATA payload the
        # frontend reconciles against - a flag that appeared on only one of
        # the two would flicker off when the scan landed.
        Add-Member -InputObject $Item -NotePropertyName 'Running' -NotePropertyValue ($Running.Count -gt 0) -Force
        Add-Member -InputObject $Item -NotePropertyName 'RunningProcesses' -NotePropertyValue (@($Running | ForEach-Object { $_.Name } | Sort-Object -Unique)) -Force
        [void]$Collected.Add($Item)
        if ($OnItem) { & $OnItem $Item }
    }

    # -- phase 1: the inventory ----------------------------------
    & $Stage "Reading installed programs (registry, 32-bit and 64-bit, plus Windows Apps)…"
    $Inventory = @(Get-InstalledProgramInventory)
    $ProcSnapshot = @(Get-RunningProcessSnapshot)
    & $Stage "Found $($Inventory.Count) installed programs. Matching them against update sources…"

    if (-not $global:WingetAvailable) {
        # No package manager: the inventory is still real and worth
        # reporting, there is simply nothing to match it against.
        return @{
            Updates        = @()
            Inventory      = $Inventory
            MatchedCount   = 0
            UnmatchedCount = $Inventory.Count
        }
    }

    # -- phase 2: the fast local pass ----------------------------
    $Index = Get-WingetPackageIndex
    # Sorted, so the rows that stream in during phase 2 arrive in a stable,
    # readable order instead of hashtable order - the user is watching this
    # list build itself, and a random order looks like a glitch.
    foreach ($Entry in ($Index.Values | Sort-Object Name)) {
        if (Test-RealUpgradeAvailable -Current $Entry.CurrentVersion -Available $Entry.AvailableVersion) {
            & $Collect ([PSCustomObject]@{
                Id               = $Entry.Id
                Name             = $Entry.Name
                CurrentVersion   = $Entry.CurrentVersion
                AvailableVersion = $Entry.AvailableVersion
                Source           = "winget"
            })
        }
    }
    if ($Collected.Count -gt 0) {
        & $Stage "$($Collected.Count) update(s) so far — checking the full catalog for the rest…"
    } else {
        & $Stage "Checking the full winget catalog (this is the slow part)…"
    }

    # -- phase 3: the authoritative pass -------------------------
    try {
        $Raw = & (Get-WingetPath) upgrade --include-unknown --accept-source-agreements --disable-interactivity 2>$null
        foreach ($Item in (ConvertFrom-WingetUpgradeTable -Raw $Raw)) {
            & $Collect ([PSCustomObject]@{
                Id               = $Item.Id
                Name             = $Item.Name
                CurrentVersion   = $Item.CurrentVersion
                AvailableVersion = $Item.AvailableVersion
                Source           = "winget"
            })
        }
    } catch {
        Write-Log "Deep scan: default winget upgrade pass failed - $($_.Exception.Message)"
    }

    # -- phase 4: the Store pass ---------------------------------
    & $Stage "Checking Microsoft Store apps…"
    try {
        $StoreRaw = & (Get-WingetPath) upgrade --include-unknown --source msstore --accept-source-agreements --disable-interactivity 2>$null
        foreach ($Item in (ConvertFrom-WingetUpgradeTable -Raw $StoreRaw)) {
            & $Collect ([PSCustomObject]@{
                Id               = $Item.Id
                Name             = $Item.Name
                CurrentVersion   = $Item.CurrentVersion
                AvailableVersion = $Item.AvailableVersion
                Source           = "msstore"
            })
        }
    } catch {
        Write-Log "Deep scan: msstore upgrade pass failed - $($_.Exception.Message)"
    }

    # Coverage, measured by IDENTITY rather than by name similarity - see the
    # WingetKey note on Get-InstalledProgramInventory. winget enumerates the
    # same ARP hives this inventory does and lists each entry either under a
    # real package id or under its `ARP\...` / `MSIX\...` fallback id. So an
    # inventory entry whose WingetKey turns up IN the index is one winget
    # could not match to any package: installed software with no automated
    # update path, which the summary reports rather than quietly implying
    # every program was covered.
    $NoSource = 0
    foreach ($Prog in $Inventory) {
        if ($Index.ContainsKey($Prog.WingetKey)) { $NoSource++ }
    }

    return @{
        Updates        = @($Collected.ToArray())
        Inventory      = $Inventory
        MatchedCount   = ($Inventory.Count - $NoSource)
        UnmatchedCount = $NoSource
    }
}

function Get-WingetUpgradeList {
    <#
    .SYNOPSIS
        Returns every app winget reports as upgradable - Win32 packages AND
        Microsoft Store apps - as an array of PSCustomObject { Id, Name,
        CurrentVersion, AvailableVersion }, so Update Center's "Update All"
        can process both kinds in one unified batch.

    .DESCRIPTION
        The default (source-less) `winget upgrade` call is expected to
        cover every configured source including msstore, but in practice
        Microsoft Store packages carry their own per-source terms-of-
        transaction agreement - a source that hasn't separately accepted it
        gets silently dropped from the unscoped listing even with
        --accept-source-agreements. Explicitly scanning `--source msstore`
        (which DOES accept that source's agreement when scoped to it) is
        what reliably surfaces Store app updates, so both scans always run
        and are merged, de-duplicated by Id (the default scan winning any
        overlap since it's the richer/authoritative pass).
    #>
    if (-not $global:WingetAvailable) { return @() }

    $WingetRaw = & (Get-WingetPath) upgrade --include-unknown --accept-source-agreements --disable-interactivity 2>$null
    $WingetItems = @(ConvertFrom-WingetUpgradeTable -Raw $WingetRaw)

    $StoreItems = @()
    try {
        $StoreRaw = & (Get-WingetPath) upgrade --include-unknown --source msstore --accept-source-agreements --disable-interactivity 2>$null
        $StoreItems = @(ConvertFrom-WingetUpgradeTable -Raw $StoreRaw)
    } catch {
        Write-Log "msstore upgrade scan failed: $($_.Exception.Message)"
    }

    $SeenIds = @{}
    $Items = @()
    foreach ($Item in ($WingetItems + $StoreItems)) {
        if ($SeenIds.ContainsKey($Item.Id)) { continue }
        $SeenIds[$Item.Id] = $true
        $Items += $Item
    }
    return $Items
}

# ============================================================
#  WINGET / CHOCOLATEY EXECUTION
# ============================================================
# ============================================================
#  PROCESS TERMINATION GUARD  (v10.5)
# ============================================================
#  WHY AN UPDATE NEEDS ONE AT ALL. Windows will not replace a file that is
#  open for execution. An installer that finds its own binaries locked
#  either fails outright (winget -1978335226 / SHELLEXEC_INSTALL_FAILED),
#  or - far worse - half-applies: some files replaced, some not, and an
#  application left in a state neither version can run. "Close the app
#  first" is therefore not politeness, it is the difference between an
#  update and a corrupted install.
#
#  WHAT THIS REPLACES. Termination used to be $Script:LockProcessMap alone:
#  nine hand-written AppId -> process-name entries. That is exactly right
#  for the nine, and silently absent for every other app in the catalog -
#  and the apps most likely to be RUNNING while the user updates them
#  (their browser, their editor, their music player) are precisely the ones
#  nobody thought to add. The map survives as the AUTHORITATIVE layer;
#  everything below it is the general answer for the rest.
#
#  THE SAFETY POSITION, WHICH IS THE WHOLE DESIGN. Terminating the wrong
#  process is the single most destructive thing this file can do - it is
#  unsaved work, gone, with no undo and no error message. So matching is
#  deliberately CONSERVATIVE and the confidence of a match is explicit:
#
#    * Every rule is an EQUALITY on a normalised name, never a substring.
#      "Code" must not match "VS Code Installer Helper"; a substring rule
#      would kill both.
#    * Every candidate name must be at least $Script:MinProcessMatchLength
#      characters. Short ids ("7zip" -> "zip", "Git" -> "git") produce
#      matches that are coincidences.
#    * A hard denylist ($Script:NeverStopProcesses) outranks every rule.
#      It holds the OS's own critical processes, the shell, and Pulse's own
#      process tree - a "successful" update that killed the GUI running it
#      would leave the machine mid-write with nothing watching.
#    * When nothing matches, NOTHING IS KILLED. A missed process costs a
#      retry with a clear error; a wrong kill costs the user's work.

#: Never terminated, whatever matches. Lowercase, no extension.
#:
#: THREE GROUPS, and the third is the one that is easy to forget. The OS
#: group is self-evident (killing csrss or wininit bugchecks the machine).
#: The shell group is explorer, whose death takes the taskbar and every
#: open File Explorer window with it - some installers do want it closed,
#: and that is a decision for a dedicated task with its own confirmation,
#: never a side effect of "update my apps". The third is PULSE ITSELF: the
#: GUI, the PowerShell host running this file, and the Python interpreter
#: hosting the GUI. An app whose name normalised to any of these would
#: otherwise have the engine terminate the process executing it, mid-write.
$Script:NeverStopProcesses = @(
    # --- the OS ---
    'system', 'idle', 'registry', 'memcompression', 'smss', 'csrss',
    'wininit', 'winlogon', 'services', 'lsass', 'lsaiso', 'svchost',
    'dwm', 'fontdrvhost', 'sihost', 'ctfmon', 'audiodg', 'spoolsv',
    'runtimebroker', 'searchhost', 'searchindexer', 'startmenuexperiencehost',
    'shellexperiencehost', 'textinputhost', 'applicationframehost',
    'trustedinstaller', 'tiworker', 'wudfhost', 'conhost', 'msiexec',
    # --- the shell ---
    'explorer',
    # --- Pulse's own tree ---
    'pulse', 'python', 'pythonw', 'powershell', 'pwsh', 'windowsterminal',
    'winget'
)

#: Below this, a normalised name is too generic to match on. Measured
#: against the real catalog: at 3 the id "Git.Git" yields the candidate
#: "git", which equals the process name of every embedded git helper any
#: application ships; at 4 the shortest surviving candidate is "curl".
$Script:MinProcessMatchLength = 4

#: How long a closed application is given to shut down on its own before it
#: is terminated. An editor with unsaved changes puts up a prompt in that
#: window and the user can answer it; past this the file lock is what the
#: update is blocked on and force is the only remaining move.
$Script:GracefulCloseWaitMs = 6000

function ConvertTo-ProcessMatchKey {
    <#
    .SYNOPSIS
        A name reduced to the form two names are COMPARED in.

    .DESCRIPTION
        Lowercase, with every non-alphanumeric character removed, so that
        "Visual Studio Code", "visual-studio-code" and "VisualStudioCode"
        are one key. Punctuation is exactly what differs between the three
        places an app's name is written - the winget id, the ARP display
        name, and the executable's ProductName - so comparing raw strings
        answers "were these typed by the same person", not "are these the
        same application".
    #>
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return "" }
    return (($Text -replace '[^A-Za-z0-9]', '').ToLowerInvariant())
}

function Get-AppProcessMatchKeys {
    <#
    .SYNOPSIS
        Every name that legitimately identifies one app, as match keys.

    .DESCRIPTION
        An app is known by two strings and neither is reliably the one a
        running process reports: the winget Id ("Mozilla.Firefox") and the
        display name ("Mozilla Firefox"). Both are offered, plus the Id's
        LAST SEGMENT on its own - because a winget id is
        Publisher.Product and the process is named after the product, so
        "Mozilla.Firefox" has to be able to match a process called
        "firefox" without the publisher.

        The publisher segment is deliberately NOT offered on its own.
        "Mozilla" would match Thunderbird, and "Microsoft" would match a
        third of the machine.
    #>
    param([string]$AppId, [string]$AppName)
    # A PLAIN STRING ARRAY, and never a HashSet, however natural a set is
    # for "the distinct names of one app".
    #
    # PowerShell ENUMERATES a collection on return. A HashSet holding one
    # key therefore comes back as a bare [string] - at which point the
    # caller's `$Keys.Contains($x)` silently stops being set membership and
    # becomes String.Contains, i.e. SUBSTRING matching, and
    # "nosuchapp".Contains("") is True. Measured before this was fixed: an
    # app whose keys collapsed to one string matched 107 of the 235
    # processes on the test machine, including every process whose
    # ProductName was unreadable and therefore compared as "". On a guard
    # whose job is to terminate processes, that is not a wrong answer, it
    # is data loss.
    #
    # Comparison lives in Test-AppKeyMatch, which cannot degrade into
    # containment whatever shape this returns.
    $Keys = @()
    foreach ($Candidate in @(
        $AppName,
        $AppId,
        (($AppId -split '\.') | Select-Object -Last 1)
    )) {
        $Key = ConvertTo-ProcessMatchKey $Candidate
        if ($Key.Length -ge $Script:MinProcessMatchLength -and $Keys -notcontains $Key) {
            $Keys += $Key
        }
    }
    return ,([string[]]$Keys)
}

function Test-AppKeyMatch {
    <#
    .SYNOPSIS
        Does $Candidate name the app whose match keys these are?

    .DESCRIPTION
        EQUALITY, EXPLICITLY. This is a function rather than an operator at
        each call site because every cheaper spelling has a silent failure
        mode:

          $Keys.Contains($x)   degrades to SUBSTRING matching the moment
                               $Keys collapses to a single string - see
                               Get-AppProcessMatchKeys.
          $Keys -contains $x   is correct, but says nothing about $x being
                               empty, and an unreadable ProductName IS the
                               empty string. It must never match.
          $x -in $Keys         same.

        So both ends are validated here, once: the candidate is normalised,
        rejected when blank, rejected when shorter than
        $Script:MinProcessMatchLength, and only then compared for equality
        against keys held to the same floor when they were built.
    #>
    param([string[]]$Keys, [string]$Candidate)
    if (-not $Keys -or $Keys.Count -eq 0) { return $false }
    $Key = ConvertTo-ProcessMatchKey $Candidate
    if ($Key.Length -lt $Script:MinProcessMatchLength) { return $false }
    foreach ($Known in $Keys) {
        if ($Known -eq $Key) { return $true }
    }
    return $false
}

function Get-RunningProcessSnapshot {
    <#
    .SYNOPSIS
        One pass over the running process table, as plain objects.

    .DESCRIPTION
        Taken ONCE and passed around, rather than re-enumerated per app: a
        bulk update walks every selected package, and Get-Process is the
        expensive part of asking "is this one running?".

        EVERY FIELD IS BEST-EFFORT. Path and the version-info fields come
        from the executable's own metadata, which is unreadable for a
        process owned by another user or protected by the system - the
        property access THROWS rather than returning null. Each is
        therefore guarded on its own, so one inaccessible process degrades
        to a name-only entry instead of aborting the snapshot and leaving
        the guard blind.
    #>
    # Property access on a process object cannot take -ErrorAction: the
    # failures below come from ScriptProperty getters (Path, MainModule),
    # which report through the error stream regardless of the try/catch
    # that handles them. On a machine with a few hundred processes that is
    # a wall of red in the live console for a snapshot that worked. The
    # preference is restored in `finally` so a caller's setting survives.
    $PreviousEap = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
    $Snapshot = @()
    foreach ($Proc in @(Get-Process -ErrorAction SilentlyContinue)) {
        $Path = ""
        $Product = ""
        $Company = ""
        try { $Path = "$($Proc.Path)" } catch { $Path = "" }
        try {
            $Info = $Proc.MainModule.FileVersionInfo
            if ($Info) {
                $Product = "$($Info.ProductName)"
                $Company = "$($Info.CompanyName)"
            }
        } catch {
            # Access denied / 32-vs-64-bit mismatch / the process exited
            # between enumeration and this read. All three are ordinary.
        }
        $Snapshot += [PSCustomObject]@{
            Name    = "$($Proc.ProcessName)"
            Id      = $Proc.Id
            Path    = $Path
            Product = $Product
            Company = $Company
            Process = $Proc
        }
    }
    return $Snapshot
    } finally {
        $ErrorActionPreference = $PreviousEap
    }
}

function Test-ProcessIsProtected {
    <# True when this process must never be terminated, whatever matched
       it. Compared on the NORMALISED name so a denylist entry cannot be
       side-stepped by punctuation. #>
    param([string]$ProcessName)
    $Key = ConvertTo-ProcessMatchKey $ProcessName
    if (-not $Key) { return $true }
    foreach ($Blocked in $Script:NeverStopProcesses) {
        if ($Key -eq (ConvertTo-ProcessMatchKey $Blocked)) { return $true }
    }
    return $false
}

function Resolve-AppProcesses {
    <#
    .SYNOPSIS
        The processes that belong to one app and are running right now.

    .DESCRIPTION
        FOUR RULES, all equalities, in descending order of how directly
        they identify the application:

          1. $Script:LockProcessMap - a human wrote down that this AppId is
             held open by these process names. Authoritative, and the only
             rule that can name a process whose name resembles nothing
             about the app ("steamwebhelper" for Valve.Steam).
          2. The process's own NAME equals one of the app's match keys.
          3. The executable's ProductName equals one of them. This is the
             field an installer stamps into its own binaries, so it catches
             the common case where the process is named after the
             executable rather than the product ("Code" -> "Visual Studio
             Code").
          4. A FOLDER on the process's path equals one of them - an app
             installed to "...\\Mozilla Firefox\\firefox.exe" is identified
             by its install directory even when nothing else lines up.

        Rules 2-4 are equality against a normalised key, never substring
        containment: "Code" must not match "VS Code Installer Helper", and
        a substring rule would kill both. The denylist is applied AFTER
        matching rather than before, so a protected process that a rule
        did match is dropped deliberately instead of by accident.

        Returns the snapshot entries, de-duplicated by process id.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$AppId,
        [string]$AppName = "",
        $Snapshot = $null
    )
    if ($null -eq $Snapshot) { $Snapshot = Get-RunningProcessSnapshot }
    $Keys = Get-AppProcessMatchKeys -AppId $AppId -AppName $AppName

    # The curated map is held to a LOWER floor than the derived keys: a
    # human wrote these down against a specific AppId, so "code" and "bash"
    # are deliberate answers rather than coincidences, and the length rule -
    # which exists to stop a short DERIVED key matching by accident - has
    # nothing to protect against here.
    $MappedKeys = @()
    if ($Script:LockProcessMap.ContainsKey($AppId)) {
        foreach ($Name in $Script:LockProcessMap[$AppId]) {
            $Key = ConvertTo-ProcessMatchKey $Name
            if ($Key) { $MappedKeys += $Key }
        }
    }

    $Matched = @()
    $SeenIds = @{}
    foreach ($Entry in $Snapshot) {
        $NameKey = ConvertTo-ProcessMatchKey $Entry.Name
        $Hit = $false

        if ($NameKey -and $MappedKeys -contains $NameKey) { $Hit = $true }
        elseif (Test-AppKeyMatch -Keys $Keys -Candidate $Entry.Name) { $Hit = $true }
        elseif (Test-AppKeyMatch -Keys $Keys -Candidate $Entry.Product) { $Hit = $true }
        elseif ($Entry.Path) {
            # THE DIRECTORY THE EXECUTABLE IS IN, not any folder on its
            # path. An ancestor match reads "somewhere under a folder named
            # after this app", which is a different and much weaker claim:
            # Steam installs every game under Steam\steamapps\common\<game>\,
            # so an ancestor rule made "update Steam" resolve to the user's
            # RUNNING GAME and offer to close it. Measured on the test
            # machine, Valve.Steam matched steam, steamwebhelper AND
            # wallpaper64 - a third-party application that merely lives
            # under Steam's root.
            #
            # The leaf folder still catches everything the rule exists for
            # ("Mozilla Firefox\firefox.exe", "Steam\steam.exe"), because an
            # application's own executable sits in its own directory.
            $Leaf = ""
            try {
                $Leaf = Split-Path -Path (Split-Path -Path $Entry.Path -Parent) -Leaf
            } catch {
                $Leaf = ""
            }
            if (Test-AppKeyMatch -Keys $Keys -Candidate $Leaf) { $Hit = $true }
        }

        if (-not $Hit) { continue }
        if (Test-ProcessIsProtected $Entry.Name) {
            Write-Log "Process guard: '$($Entry.Name)' matched $AppId but is protected - not touching it."
            continue
        }
        if ($SeenIds.ContainsKey($Entry.Id)) { continue }
        $SeenIds[$Entry.Id] = $true
        $Matched += $Entry
    }
    return $Matched
}

function Stop-AppProcesses {
    <#
    .SYNOPSIS
        Close every running instance of one app, gracefully first.

    .DESCRIPTION
        TWO STAGES, AND THE FIRST ONE IS THE POINT. CloseMainWindow() sends
        WM_CLOSE - the same thing clicking the X does - so an application
        with unsaved work shows its own "save before closing?" prompt and
        the user gets to answer it. Only what is still alive after
        $Script:GracefulCloseWaitMs is terminated outright, because past
        that the file lock is the thing blocking the update and there is no
        gentler move left.
        A process with no main window (a background updater, a tray helper)
        has nothing to send WM_CLOSE to and goes straight to the second
        stage - which is correct: there is no unsaved work behind a window
        that does not exist.

        ONE WAIT FOR ALL OF THEM, not one per process. Sleeping after each
        kill serialised the wait across every match (N processes = N x the
        delay) for no benefit, since nothing reads process state between
        one Stop-Process and the next.

        Dry-run safe: Invoke-Mutation logs [WHATIF] and returns without
        touching anything, and the settle delay - which exists to let a
        REAL kill release its file lock - is skipped with it.

        Returns the number of processes it acted on, so the caller can say
        so rather than guess.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$AppId,
        [string]$AppName = "",
        $Snapshot = $null
    )
    $Targets = @(Resolve-AppProcesses -AppId $AppId -AppName $AppName -Snapshot $Snapshot)
    if ($Targets.Count -eq 0) { return 0 }

    $Label = if ($AppName) { $AppName } else { $AppId }
    $Names = @($Targets | ForEach-Object { $_.Name } | Sort-Object -Unique)
    Write-GuiStage "Closing $Label ($($Names -join ', '))..."
    Write-Warn "$Label is running - closing $($Targets.Count) process(es): $($Names -join ', ')"

    # -- stage 1: ask -------------------------------------------
    $Asked = @()
    foreach ($Entry in $Targets) {
        $Result = Invoke-Mutation -Description "Close '$($Entry.Name)' (PID $($Entry.Id)), which locks the $Label installer" -Action {
            try {
                if ($Entry.Process.MainWindowHandle -ne 0) {
                    [void]$Entry.Process.CloseMainWindow()
                    return $true
                }
            } catch {
                # Exited between the snapshot and now: already closed, which
                # is the outcome this was asking for.
            }
            return $false
        }
        if ($Result) { $Asked += $Entry }
    }
    if ($Script:DryRun) { return $Targets.Count }

    if ($Asked.Count -gt 0) {
        Start-Sleep -Milliseconds $Script:GracefulCloseWaitMs
    }

    # -- stage 2: insist ----------------------------------------
    $Forced = 0
    foreach ($Entry in $Targets) {
        $Alive = $null
        try { $Alive = Get-Process -Id $Entry.Id -ErrorAction SilentlyContinue } catch { $Alive = $null }
        if (-not $Alive) { continue }
        Write-Warn "'$($Entry.Name)' did not close on request - terminating it."
        try {
            Stop-Process -Id $Entry.Id -Force -ErrorAction SilentlyContinue
            $Forced++
        } catch {
            Write-Log "Process guard: could not terminate '$($Entry.Name)' (PID $($Entry.Id)): $($_.Exception.Message)"
        }
    }
    if ($Forced -gt 0) {
        # A terminated process releases its handles asynchronously; the
        # installer that runs next needs them actually released, not merely
        # scheduled for release.
        Start-Sleep -Milliseconds 800
    }
    Write-Info "$Label closed - proceeding with the update."
    return $Targets.Count
}

function Stop-LockingProcesses {
    <# BACK-COMPATIBLE ENTRY POINT. This was the whole guard through v10.4:
       $Script:LockProcessMap lookups and an unconditional force-kill. It
       now delegates to Stop-AppProcesses, which still consults that map as
       its authoritative first rule but also finds the apps nobody wrote
       down, and asks before it insists. #>
    param($AppId, [string]$AppName = "")
    return (Stop-AppProcesses -AppId $AppId -AppName $AppName)
}

function Invoke-Winget {
    param([string[]]$ArgList)
    $Proc = Start-Process -FilePath (Get-WingetPath) -ArgumentList $ArgList -NoNewWindow -Wait -PassThru
    return $Proc.ExitCode
}

function Invoke-Chocolatey {
    <# Install one package through Chocolatey, returning its EXIT CODE.

       THE EXIT CODE IS THE POINT. This used to `return 0` on any run that
       did not throw - but a native executable exiting non-zero does not
       throw in PowerShell, so every Chocolatey failure that wrote no
       terminating error was reported as a success: the caller logged
       "installed via Chocolatey", returned Status='Success', and the app
       counted toward the GUI's "N installed" summary without ever having
       been installed. The catch only ever caught "choco is not a command".

       Chocolatey documents 1641 and 3010 as success-with-reboot, so both
       are folded into 0 rather than being reported as failures. #>
    param([string]$AppId)
    if (-not $global:ChocolateyPath) { return 1 }
    try {
        & $global:ChocolateyPath install $AppId -y --limit-output | Out-Null
        $Code = $LASTEXITCODE
        if ($Code -eq 1641 -or $Code -eq 3010) {
            $Script:PendingRestart = $true
            return 0
        }
        return $Code
    } catch {
        Write-Log "Chocolatey install of '$AppId' threw: $($_.Exception.Message)"
        return 1
    }
}

# Winget exit codes that mean "nothing needed to change" - all three
# resolve to Success + AlreadyCurrent below. Kept as one list so the
# pre-retry gate in Smart-Deploy (never force-retry a no-op result) and
# Resolve-WingetExitCode read from the same source of truth.
$Script:WingetAlreadyCurrentCodes = @(-1978335212, -1978335153, -1978335189)

# Winget exit codes that mean "this process's CURRENT elevation state is
# categorically wrong for this operation" - retrying with --force changes
# nothing (it's not a lock/transient failure, it's a hard refusal baked
# into the installer manifest or into winget itself), so these share the
# same no-retry gate as WingetAlreadyCurrentCodes below. Resolve-WingetExitCode
# flags them with ElevationConflict = $true so Smart-Deploy reports them as
# Skipped (with a "relaunch at the other elevation level" instruction)
# instead of Failed.
$Script:WingetElevationConflictCodes = @(-1978335146, -1978335107, -1978335207)

function Resolve-WingetExitCode {
    <#
    .SYNOPSIS
        Translates a winget process exit code into Success/AlreadyCurrent/
        Message. Every non-generic code below was cross-checked against
        winget-cli's own AppInstallerErrors.h (FACILITY_WINGET, 0x8A15xxxx)
        - a prior version of this function had three of these mapped to the
        wrong meaning (copied from an unverified forum post, near as we can
        tell), including treating an installer HASH MISMATCH as a silent
        success. That is a security-relevant bug (a corrupted or tampered
        download reported as "completed successfully"), not just a wording
        nitpick, so it's called out explicitly rather than folded in quietly.
    #>
    param([int]$Code)
    switch ($Code) {
        0            { return @{ Success = $true;  AlreadyCurrent = $false; Message = "Completed successfully." } }
        3010         { return @{ Success = $true;  AlreadyCurrent = $false; Message = "Completed successfully. A reboot is recommended." } }
        # 0x8A150014 NO_APPLICATIONS_FOUND - `winget upgrade --id X --exact`
        # searches the AVAILABLE-UPGRADES list; an up-to-date package isn't
        # in it, so the id lookup finds nothing. The common real-world
        # "already current" signal for upgrades.
        -1978335212  { return @{ Success = $true;  AlreadyCurrent = $true;  Message = "Already up to date." } }
        # 0x8A15004F UPGRADE_VERSION_NOT_NEWER - resolved candidate isn't
        # newer than what's installed. Also "already current", not a file
        # lock (that was this code's previous, incorrect label).
        -1978335153  { return @{ Success = $true;  AlreadyCurrent = $true;  Message = "Already up to date." } }
        # 0x8A15002B UPDATE_NOT_APPLICABLE - same "nothing to do" family.
        # Also not "package not found" (that was this code's previous,
        # incorrect label).
        -1978335189  { return @{ Success = $true;  AlreadyCurrent = $true;  Message = "Already up to date." } }
        # 0x8A150011 INSTALLER_HASH_MISMATCH - the downloaded installer's
        # hash didn't match the manifest. A real failure (possible
        # corruption or tampering) - previously mislabeled "no applicable
        # upgrade" and treated as a silent success.
        -1978335215  { return @{ Success = $false; AlreadyCurrent = $false; Message = "Installer hash didn't match the expected value (corrupted or tampered download). Try again." } }
        # 0x8A150006 SHELLEXEC_INSTALL_FAILED - winget launched the
        # installer, but the installer itself exited non-zero. Common with
        # MSYS2 when a previous MSYS2/MinGW terminal is still open (locked
        # files) - Stop-LockingProcesses now covers it (see LockProcessMap).
        -1978335226  { return @{ Success = $false; AlreadyCurrent = $false; Message = "The installer itself reported a failure - often caused by a previous install still open (close any MSYS2/MinGW terminals for GCC, for example) or a locked file. Try again after closing related apps." } }
        # 0x8A150056 INSTALLER_PROHIBITS_ELEVATION - the installer's own
        # manifest refuses to run under an Administrator token (Spotify is
        # the well-known example). Not fixable with --scope or --force;
        # the only fix is running winget at the OTHER elevation level.
        -1978335146  { return @{ Success = $false; AlreadyCurrent = $false; ElevationConflict = $true; Message = "This app's installer refuses to run under an Administrator token, and Pulse always runs elevated (see the manifest note in main.spec), so it cannot install this one at all. Install it from the vendor's own installer instead - Pulse's fallback link for it is in the operation log." } }
        # 0x8A15007D ADMIN_CONTEXT_REPAIR_PROHIBITED - same family as
        # above, scoped to a repair/modify path specifically.
        -1978335107  { return @{ Success = $false; AlreadyCurrent = $false; ElevationConflict = $true; Message = "This app's repair/modify path is blocked under an Administrator token, and Pulse always runs elevated, so it cannot be repaired from here. Use the app's own repair option, or Windows' Installed apps > Modify." } }
        # 0x8A150019 COMMAND_REQUIRES_ADMIN - the reverse case: this
        # operation genuinely needs elevation and Pulse doesn't have it.
        -1978335207  { return @{ Success = $false; AlreadyCurrent = $false; ElevationConflict = $true; Message = "This app requires Administrator rights to install. Click 'Run as Administrator' in the Pulse sidebar to relaunch elevated, then retry." } }
        1602         { return @{ Success = $false; AlreadyCurrent = $false; Message = "Installer was cancelled." } }
        1            { return @{ Success = $false; AlreadyCurrent = $false; Message = "Generic failure (Exit Code 1)." } }
        default      { return @{ Success = $false; AlreadyCurrent = $false; Message = "Unhandled exit code ($Code)." } }
    }
}

function Open-FallbackUrl {
    param($AppId, $AppName)
    $url = $Script:DownloadUrls[$AppId]
    if ($Script:NonInteractive -or $Script:DryRun) {
        # GUI task / dry-run: NEVER pop a browser mid-silent-run. Log the
        # link so the user can find it in the operation log instead.
        if ($url) { Write-Log "FALLBACK-URL for ${AppName}: $url" }
        else      { Write-Log "FALLBACK-URL for ${AppName}: no official URL mapped." }
        return
    }
    if ($url) {
        # Test-SafeWebUrl (00-Foundation.ps1) before handing anything to
        # Start-Process: that call is ShellExecute, so a catalog entry that
        # was not actually a web address - a local path, a UNC share, a
        # file:// URI - would be EXECUTED rather than browsed to.
        if (-not (Test-SafeWebUrl $url)) {
            Write-Warn "The download URL mapped for $AppName is not a web address - not opening it."
            Write-Log "FALLBACK-URL for ${AppName}: refused non-http(s) URL '$url'."
            return
        }
        Write-Info "Opening official download page: $url"
        Start-Process $url
    } else {
        # URL-ENCODED. $AppName reaches this from the app catalog and can
        # carry spaces, '&', '#' and '+' - all of which are QUERY SYNTAX
        # once they land in a query string. Unencoded, "Notepad++" searched
        # for "Notepad  " (the '+'s decoding back to spaces), and a name
        # containing '&' silently truncated the search and appended
        # whatever followed as a second parameter.
        $Query = [System.Uri]::EscapeDataString("$AppName download")
        Write-Info "No official URL mapped. Opening search..."
        Start-Process "https://www.google.com/search?q=$Query"
    }
}

# ============================================================
#  LOCAL INSTALLER RUNNER (Path C of the generic Tool Install Wizard)
# ============================================================
function Invoke-GuiLocalInstall {
    <#
    .SYNOPSIS
        Runs an installer file the user already downloaded and picked
        through widgets.ToolInstallWizardDialog's Path C (task
        InstallLocalFile). Generic by design - unlike Office's ODT flow,
        "run this installer the user pointed at" needs no tool-specific
        knowledge: .msi goes through msiexec /i, everything else runs
        directly. Most installers self-elevate via their own manifest if
        they need to (Windows shows that UAC prompt regardless of this
        hidden/no-window parent process), so this never forces elevation
        itself - exactly like a user double-clicking the file manually.
    #>
    param([Parameter(Mandatory = $true)][string]$FilePath)

    if (-not (Test-Path -Path $FilePath -PathType Leaf)) {
        Write-ErrorX "Installer file not found: $FilePath"
        return $false
    }

    if (Test-DryRun "Run local installer '$FilePath'") { return $true }

    Write-Info "Running installer: $FilePath"
    try {
        $Ext = [System.IO.Path]::GetExtension($FilePath).ToLowerInvariant()
        # -WorkingDirectory: the installer's OWN folder, which is what
        # double-clicking it gives and what a bundled setup expects when it
        # looks for its payload alongside itself. Without it the child
        # inherits Pulse's working directory instead, which is neither the
        # installer's folder nor anything the installer knows about.
        $WorkDir = Split-Path -Path $FilePath -Parent
        # -NoNewWindow on both branches. It suppresses a CONSOLE, not a
        # window: a GUI installer still shows its own UI exactly as it does
        # on a double-click, while a console-mode one stops flashing a
        # black box over Pulse. Without it, msiexec and every NSIS/Inno
        # stub allocated one.
        if ($Ext -eq ".msi") {
            $Proc = Start-Process -FilePath (Get-SystemBinary "msiexec") -ArgumentList @("/i", ('"' + $FilePath + '"')) `
                -WorkingDirectory $WorkDir -Wait -NoNewWindow -PassThru
        } else {
            $Proc = Start-Process -FilePath $FilePath -WorkingDirectory $WorkDir -Wait -NoNewWindow -PassThru
        }
        if ($Proc.ExitCode -eq 0 -or $Proc.ExitCode -eq 3010) {
            Write-Success "Installer finished (exit code $($Proc.ExitCode))."
            return $true
        } else {
            Write-ErrorX "Installer exited with code $($Proc.ExitCode)."
            return $false
        }
    } catch {
        Write-ErrorX "Could not run the installer: $($_.Exception.Message)"
        return $false
    }
}

# ============================================================
#  SMART DEPLOY (the one true install path)
# ============================================================
function Smart-Deploy {
    param(
        [string]$AppId,
        [string]$AppName,
        [switch]$Bulk,
        [ValidateSet('auto','manual')]
        [string]$BulkMethod
    )

    if ([string]::IsNullOrWhiteSpace($AppId)) { return @{Status='Skipped'; Message='Empty AppId'} }

    # Lazy winget bootstrap: only software deployment pays for it. Skipped in
    # dry-run - Ensure-Winget itself refuses to download during -WhatIf.
    if (-not (Is-StoreApp $AppId)) { Ensure-Winget | Out-Null }

    if (Is-StoreApp $AppId) {
        Write-Host ""
        Write-StatusPanel -Label "STORE APP" -Text $AppName

        $InstalledVer = Get-InstalledVersion -AppId $AppId -AppName $AppName
        $LatestVer    = Get-LatestVersion -AppId $AppId

        if ($InstalledVer -and ($InstalledVer -eq $LatestVer -or $LatestVer -eq "Store")) {
            Write-AlreadyOK "$AppName -> already installed (v$InstalledVer) - skipped."
            return @{Status='Success'; AlreadyCurrent=$true; Message='Already installed'}
        }

        if ($Script:DryRun) {
            if ($InstalledVer) {
                if (Test-DryRun "winget upgrade --id $AppId ($AppName) via --source msstore, silent") { }
            } else {
                Write-Info "[WHATIF] $AppName is a Microsoft Store app - a real run would require the Store (skipped)."
            }
            return @{Status='Success'; Message='Dry-run (no change)'}
        }

        if ($InstalledVer) {
            # An update IS available (the AlreadyCurrent short-circuit above
            # only returns when there ISN'T one) - unlike a brand-new Store
            # install, updating an app already on the machine needs no
            # first-run Store consent UI, so this can run through winget's
            # msstore source exactly like a normal silent upgrade - the
            # same single unified pass Update Center uses for Win32 apps.
            Write-Warn "$AppName update available (Store): $InstalledVer -> $LatestVer"
            if ($Bulk) {
                if ($BulkMethod -eq 'manual') {
                    Write-Info "Opening Store page for $AppName..."
                    Start-Process "ms-windows-store://pdp/?ProductId=$AppId"
                    return @{Status='Success'; Message='Store opened'}
                }
                # 'auto' falls through to the silent winget update below.
            } elseif ($Script:NonInteractive) {
                Write-Info "GUI mode: proceeding with silent winget update (msstore source)."
            } else {
                Write-Host "   y = Update via winget (silent, msstore source)" -ForegroundColor Yellow
                Write-Host "   n = Skip this app only" -ForegroundColor Yellow
                Write-Host "   b = Back to category" -ForegroundColor Yellow
                Write-Host "   q = Quit to main menu" -ForegroundColor Yellow
                $choice = Read-Choice -Prompt "   Choose (y/n/b/q)" -Valid @('y','n','b','q')
                switch ($choice) {
                    'q' { return @{Status='Quit'; Message='User quit to main menu'} }
                    'b' { return @{Status='Back'; Message='User returned to category'} }
                    'n' { Write-Info "Bypassed $AppName."; return @{Status='Skipped'; Message='User skipped'} }
                    'y' { }
                }
            }

            Ensure-Winget | Out-Null
            if (-not $global:WingetAvailable) {
                Write-ErrorX "$AppName failed: winget is unavailable, so this Microsoft Store update can't be applied."
                return @{Status='Failed'; Message='winget unavailable'}
            }

            # A Store app is replaced on disk exactly like a Win32 one, so
            # it needs the same guard: a running packaged app holds its own
            # payload open and the update fails or half-applies.
            [void](Stop-AppProcesses -AppId $AppId -AppName $AppName)
            Write-GuiStage "Downloading $AppName $LatestVersion (Microsoft Store)..."
            Write-Info "Updating $AppName via winget (Microsoft Store source)..."
            $Code = Invoke-Winget -ArgList @("upgrade", "--id", $AppId, "--exact", "--source", "msstore", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity")
            $Result = Resolve-WingetExitCode -Code $Code
            if ($Result.Success) {
                if ($Result.AlreadyCurrent) {
                    Write-AlreadyOK "$AppName -> $($Result.Message) - skipped."
                } else {
                    Write-GuiStage "Verifying $AppName..."
                    $NewVersion = Get-InstalledVersion -AppId $AppId -AppName $AppName
                    if ($NewVersion -and $NewVersion -ne $InstalledVer) {
                        Write-GuiStage "Verified $AppName $InstalledVer -> $NewVersion"
                        Write-Success "$AppName -> updated $InstalledVer -> $NewVersion (verified)."
                        $Result.Message = "Updated $InstalledVer -> $NewVersion."
                    } else {
                        Write-GuiStage "Verified $AppName"
                        Write-Success "$AppName -> $($Result.Message)"
                    }
                }
                return @{Status='Success'; AlreadyCurrent=$Result.AlreadyCurrent; Message=$Result.Message}
            } else {
                Write-ErrorX "$AppName failed: $($Result.Message)"
                return @{Status='Failed'; Message=$Result.Message}
            }
        }

        if ($Bulk) {
            if ($BulkMethod -eq 'manual') {
                Write-Info "Opening Store page for $AppName..."
                Start-Process "ms-windows-store://pdp/?ProductId=$AppId"
                return @{Status='Success'; Message='Store opened'}
            } else {
                Write-Warn "$AppName is a Store app and cannot be installed via winget. Skipping."
                return @{Status='Skipped'; Message='Store app'}
            }
        }

        if ($Script:NonInteractive) {
            # GUI task: no console to prompt on and no silent install path
            # for Store apps - skip cleanly instead of hanging on Read-Choice.
            Write-Warn "$AppName is a Microsoft Store app - skipped in GUI mode."
            return @{Status='Skipped'; Message='Store app (GUI)'}
        }

        Write-Host "   m = Open Microsoft Store page" -ForegroundColor Yellow
        Write-Host "   n = Skip this app only" -ForegroundColor Yellow
        Write-Host "   b = Back to category" -ForegroundColor Yellow
        Write-Host "   q = Quit to main menu" -ForegroundColor Yellow
        $choice = Read-Choice -Prompt "   Choose (m/n/b/q)" -Valid @('m','n','b','q')
        switch ($choice) {
            'q' { return @{Status='Quit'; Message='User quit to main menu'} }
            'b' { return @{Status='Back'; Message='User returned to category'} }
            'm' {
                Write-Info "Launching Microsoft Store..."
                Start-Process "ms-windows-store://pdp/?ProductId=$AppId"
                Write-Success "Store page opened."
                return @{Status='Success'; Message='Store opened'}
            }
            default { return @{Status='Skipped'; Message='Skipped'} }
        }
    }

    Write-Host ""
    Write-StatusPanel -Label "TARGET" -Text $AppName
    Write-GuiStage "Checking $AppName..."

    $CurrentVersion = Get-InstalledVersion -AppId $AppId -AppName $AppName
    $LatestVersion  = Get-LatestVersion -AppId $AppId
    # See $Script:AlwaysForceReinstallAppIds in 01-Catalogs.ps1: some
    # AppIds (Microsoft.Edge) can report a "current" version through this
    # exact same version probe even when the payload Pulse actually cares
    # about was just removed - the fast-path skip below has to be bypassed
    # for them, or a reinstall silently does nothing.
    $ForceReinstall = $Script:AlwaysForceReinstallAppIds -contains $AppId

    if ($CurrentVersion) {
        if (($CurrentVersion -eq $LatestVersion -or $LatestVersion -eq "Unknown") -and -not $ForceReinstall) {
            Write-AlreadyOK "$AppName -> already up to date (v$CurrentVersion) - skipped."
            return @{Status='Success'; AlreadyCurrent=$true; Message='Already up to date'}
        }
        if ($ForceReinstall -and ($CurrentVersion -eq $LatestVersion -or $LatestVersion -eq "Unknown")) {
            Write-Warn "$AppName reports as already current, but always gets a forced reinstall (see AlwaysForceReinstallAppIds)."
        } else {
            Write-Warn "$AppName update available: $CurrentVersion -> $LatestVersion"
        }
    } else {
        Write-Warn "$AppName is not installed. (Latest: $LatestVersion)"
    }

    # -WhatIf: report the exact action a real run would take, then stop.
    if ($Script:DryRun) {
        $Verb = if ($CurrentVersion) { "upgrade" } else { "install" }
        if (Test-DryRun "winget $Verb --id $AppId ($AppName), silent, with agreements accepted") { }
        return @{Status='Success'; Message='Dry-run (no change)'}
    }

    if ($Bulk) {
        if ($BulkMethod -eq 'manual') {
            Open-FallbackUrl $AppId $AppName
            return @{Status='Success'; Message='Manual URL (bulk)'}
        }
    } elseif ($Script:NonInteractive) {
        # GUI task: the card click IS the confirmation - fall through to
        # the silent winget deployment without prompting.
        Write-Info "GUI mode: proceeding with silent winget deployment."
    } else {
        Write-Host "   y = Auto install via winget (silent)" -ForegroundColor Yellow
        Write-Host "   m = Open official website (manual download)" -ForegroundColor Yellow
        Write-Host "   n = Skip this app only" -ForegroundColor Yellow
        Write-Host "   b = Back to category" -ForegroundColor Yellow
        Write-Host "   q = Quit to main menu" -ForegroundColor Yellow
        $choice = Read-Choice -Prompt "   Choose (y/m/n/b/q)" -Valid @('y','m','n','b','q')
        switch ($choice) {
            'q' { return @{Status='Quit'; Message='User quit to main menu'} }
            'b' { return @{Status='Back'; Message='User returned to category'} }
            'n' { Write-Info "Bypassed $AppName."; return @{Status='Skipped'; Message='User skipped'} }
            'm' { Open-FallbackUrl $AppId $AppName; return @{Status='Success'; Message='Manual URL'} }
            'y' { }
        }
    }

    if (-not $global:WingetAvailable) {
        if ($global:ChocolateyAvailable) {
            Write-Info "Installing via Chocolatey..."
            $code = Invoke-Chocolatey $AppId
            if ($code -eq 0) { Write-Success "$AppName installed via Chocolatey."; return @{Status='Success'; Message='Chocolatey'} }
            else { Write-ErrorX "Chocolatey failed."; return @{Status='Failed'; Message='Chocolatey failed'} }
        } else {
            Write-ErrorX "No package manager available."
            Open-FallbackUrl $AppId $AppName
            return @{Status='Failed'; Message='No package manager'}
        }
    }

    # Known elevation-prohibited apps (Spotify et al - see
    # $Script:KnownElevationProhibitedAppIds) are a guaranteed
    # INSTALLER_PROHIBITS_ELEVATION failure while Pulse runs elevated.
    # Skip the doomed winget call entirely instead of burning an attempt +
    # a force retry that would only reproduce the identical failure.
    if ($Script:IsAdminSession -and $Script:KnownElevationProhibitedAppIds -contains $AppId) {
        $Message = "This app's installer refuses to run under an Administrator token, and Pulse always runs elevated (see the manifest note in main.spec), so it cannot install this one at all. Install it from the vendor's own installer instead - Pulse's fallback link for it is in the operation log."
        Write-Warn "$AppName skipped: $Message"
        return @{Status='Skipped'; Message=$Message}
    }

    # -- the process termination guard --------------------------
    # BEFORE the installer, never after: Windows will not replace a file
    # that is open for execution, and an installer that discovers the lock
    # itself either fails outright or half-applies. See the guard's own
    # section header for why this is a correctness measure and not a
    # courtesy.
    [void](Stop-AppProcesses -AppId $AppId -AppName $AppName)

    # -- what is about to happen, said out loud ------------------
    # The GUI shows the live winget stream underneath this, but a stream is
    # something to READ and a stage line is something to GLANCE at. This is
    # the line the drawer's status rail carries while the download runs, so
    # it names the app AND the version being applied - "Downloading" alone
    # is what a generic spinner already said.
    $TargetVersion = if ($LatestVersion -and $LatestVersion -ne "Unknown") { " $LatestVersion" } else { "" }
    if ($CurrentVersion) {
        Write-GuiStage "Downloading $AppName$TargetVersion (replacing $CurrentVersion)..."
    } else {
        Write-GuiStage "Downloading $AppName$TargetVersion..."
    }
    Write-Info "Running winget - live progress:"
    if ($ForceReinstall) {
        # AlwaysForceReinstallAppIds bypass "upgrade" entirely - an upgrade
        # call has nothing to do against a version winget considers already
        # current, which is exactly the broken state this list exists to
        # route around. A forced install reliably re-lays the package
        # either way.
        $Code = Invoke-Winget -ArgList @("install", "--id", $AppId, "--exact", "--accept-source-agreements", "--accept-package-agreements", "--force", "--disable-interactivity")
    } elseif ($CurrentVersion) {
        $Code = Invoke-Winget -ArgList @("upgrade", "--id", $AppId, "--exact", "--include-unknown", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity")
    } else {
        $Code = Invoke-Winget -ArgList @("install", "--id", $AppId, "--exact", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity")
    }

    if ($Code -ne 0 -and $Script:WingetAlreadyCurrentCodes -notcontains $Code -and $Script:WingetElevationConflictCodes -notcontains $Code) {
        # Never force-retry a code that means "nothing to do" or "the
        # elevation state itself is wrong" - force changes neither, so it
        # would either force an unnecessary reinstall or just reproduce
        # the identical elevation failure a second time.
        Write-GuiStage "Retrying $AppName with force flags..."
        Write-Warn "First attempt failed. Retrying with force flags..."
        Start-Sleep -Seconds 3
        if ($CurrentVersion -and -not $ForceReinstall) {
            $Code = Invoke-Winget -ArgList @("upgrade", "--id", $AppId, "--exact", "--include-unknown", "--accept-source-agreements", "--accept-package-agreements", "--force", "--disable-interactivity")
        } else {
            $Code = Invoke-Winget -ArgList @("install", "--id", $AppId, "--exact", "--accept-source-agreements", "--accept-package-agreements", "--force", "--disable-interactivity")
        }
    }

    $Result = Resolve-WingetExitCode -Code $Code

    if ($Result.Success) {
        if ($Result.AlreadyCurrent) {
            Write-AlreadyOK "$AppName -> $($Result.Message) - skipped."
        } else {
            # -- verification -------------------------------------
            # AN EXIT CODE IS THE INSTALLER'S OPINION OF ITSELF. Asking the
            # machine what is actually installed now is the only statement
            # worth making to a user who was told a version number a minute
            # ago, and it is cheap: Get-InstalledVersion reads the same ARP
            # entry the scan did. Reported either way, and never downgraded
            # to a failure - a package whose version winget cannot resolve
            # after a clean install is a reporting gap, not a broken
            # install, and calling it one would fail runs that worked.
            Write-GuiStage "Verifying $AppName..."
            $NewVersion = Get-InstalledVersion -AppId $AppId -AppName $AppName
            if ($NewVersion -and $CurrentVersion -and $NewVersion -ne $CurrentVersion) {
                Write-GuiStage "Verified $AppName $CurrentVersion -> $NewVersion"
                Write-Success "$AppName -> updated $CurrentVersion -> $NewVersion (verified)."
                $Result.Message = "Updated $CurrentVersion -> $NewVersion."
            } elseif ($NewVersion) {
                Write-GuiStage "Verified $AppName $NewVersion"
                Write-Success "$AppName -> $($Result.Message) (now v$NewVersion)"
            } else {
                Write-GuiStage "$AppName installed"
                Write-Success "$AppName -> $($Result.Message)"
            }
        }
        if ($Script:DevAppPaths.ContainsKey($AppId)) { Register-DevPath -AppId $AppId -AppName $AppName }
        if (-not $Result.AlreadyCurrent) {
            Test-DevDependencySuggestion -AppId $AppId
        }
        return @{Status='Success'; AlreadyCurrent=$Result.AlreadyCurrent; Message=$Result.Message}
    } elseif ($Result.ElevationConflict) {
        # Not a real failure - Pulse's CURRENT elevation state is simply
        # wrong for this one app. Write-Warn (not Write-ErrorX) so this
        # never bumps $Script:SessionFailCount and flips an otherwise
        # clean bulk run to an ERROR verdict (see Complete-GuiTask).
        Write-Warn "$AppName skipped: $($Result.Message)"
        return @{Status='Skipped'; Message=$Result.Message}
    } else {
        Write-ErrorX "$AppName failed: $($Result.Message)"
        if (-not $Bulk -and -not $Script:NonInteractive) {
            $openFallback = Read-Choice -Prompt "   Auto install failed. Open official website? (y/n)" -Valid @('y','n')
            if ($openFallback -eq 'y') { Open-FallbackUrl $AppId $AppName }
        } else {
            # Bulk/GUI: Open-FallbackUrl is itself NonInteractive-aware
            # (logs the URL instead of opening a browser in GUI mode).
            Open-FallbackUrl $AppId $AppName
        }
        return @{Status='Failed'; Message=$Result.Message}
    }
}

# ============================================================
#  HARDWARE MATCHING (GPU / motherboard vendor apps)
# ============================================================
function Hardware-Check {
    $GPU = Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name | Select-Object -First 1
    $GPUApp = if ($GPU -match "NVIDIA") { "Nvidia.GeForceExperience" }
              elseif ($GPU -match "AMD|Radeon") { "AdvancedMicroDevices.Adrenalin" }
              elseif ($GPU -match "Intel") { "Intel.IntelGraphicsCommandCenter" } else { "" }

    $Mobo = Get-CimInstance Win32_BaseBoard | Select-Object -ExpandProperty Manufacturer
    $MoboApp = if ($Mobo -match "ASUS") { "Asus.ArmouryCrate" }
               elseif ($Mobo -match "Micro-Star|MSI") { "Micro-Star.MSICenter" }
               elseif ($Mobo -match "Gigabyte") { "Gigabyte.ControlCenter" }
               elseif ($Mobo -match "ASRock") { "ASRock.AppShop" } else { "" }

    return @{ GPUApp = $GPUApp; MoboApp = $MoboApp; MoboName = $Mobo; GPUName = $GPU }
}

function Get-DisplayRefreshRate {
    try {
        $Rates = Get-CimInstance Win32_VideoController -ErrorAction Stop |
                 Where-Object { $_.CurrentRefreshRate -gt 0 } |
                 Select-Object -ExpandProperty CurrentRefreshRate
        return $Rates
    } catch {
        return $null
    }
}

# ============================================================
#  CATEGORY PROCESSOR (interactive console flow)
# ============================================================
function Process-AppCategory {
    param($AppList, $CategoryName)

    Write-SectionHeader $CategoryName

    if ($Script:LastBulkChoice) {
        Write-Host "   Last bulk choice: $($Script:LastBulkChoice.Method). Reuse it for this category?" -ForegroundColor Yellow
        if (Ask-User "Reuse Last Bulk Mode" "Applies the '$($Script:LastBulkChoice.Method)' method to every app in '$CategoryName' without asking again.") {
            Initialize-WingetBatchCache
            try {
                foreach ($App in $AppList) {
                    $res = Smart-Deploy -AppId $App[0] -AppName $App[1] -Bulk -BulkMethod $Script:LastBulkChoice.Method
                    if ($res.Status -eq 'Quit') { break }
                }
            } finally {
                $Script:WingetBatchCache = $null
            }
            return "OK"
        }
    }

    Write-Host "   y = Bulk auto (winget install all silently)" -ForegroundColor Yellow
    Write-Host "   m = Bulk manual (open official websites for all)" -ForegroundColor Yellow
    Write-Host "   n = Choose individually" -ForegroundColor Yellow
    Write-Host "   b = Back to previous menu" -ForegroundColor Yellow
    Write-Host "   q = Quit to main menu" -ForegroundColor Yellow
    $bulkChoice = Read-Choice -Prompt "   Choose (y/m/n/b/q)" -Valid @('y','m','n','b','q')
    if ($bulkChoice -eq 'q') { return "QUIT" }
    if ($bulkChoice -eq 'b') { return "BACK" }

    if ($bulkChoice -eq 'y' -or $bulkChoice -eq 'm') {
        $method = if ($bulkChoice -eq 'y') { 'auto' } else { 'manual' }
        $Script:LastBulkChoice = @{Method=$method}

        $results = @{}
        Initialize-WingetBatchCache
        try {
            foreach ($App in $AppList) {
                $res = Smart-Deploy -AppId $App[0] -AppName $App[1] -Bulk -BulkMethod $method
                if ($res.Status -eq 'Quit') { break }
                $results[$App[1]] = $res
            }
        } finally {
            $Script:WingetBatchCache = $null
        }

        Write-Divider
        $success = ($results.GetEnumerator() | Where-Object { $_.Value.Status -eq 'Success' -and -not $_.Value.AlreadyCurrent }).Count
        $current = ($results.GetEnumerator() | Where-Object { $_.Value.Status -eq 'Success' -and $_.Value.AlreadyCurrent }).Count
        $failed  = ($results.GetEnumerator() | Where-Object { $_.Value.Status -eq 'Failed' }).Count
        $skipped = ($results.GetEnumerator() | Where-Object { $_.Value.Status -eq 'Skipped' }).Count
        Write-Info "Bulk summary for '$CategoryName': $success installed, $current already up to date, $failed failed, $skipped skipped."
        return "OK"
    }

    foreach ($App in $AppList) {
        $result = Smart-Deploy $App[0] $App[1]
        if ($result.Status -eq 'Quit') {
            Write-Warn "Exiting '$CategoryName' and returning to main menu."
            return "QUIT"
        }
        if ($result.Status -eq 'Back') {
            Write-Warn "Returning to category selection."
            return "BACK"
        }
    }
    return "OK"
}
