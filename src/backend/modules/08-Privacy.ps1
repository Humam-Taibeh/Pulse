#Requires -Version 5.1
<#
.SYNOPSIS
    08-Privacy.ps1 - debloat, telemetry, advertising ID and activity history.

.DESCRIPTION
    Data-driven: the bloatware list ($Script:BloatApps) and the telemetry
    scheduled-task list ($Script:TelemetryTasks) live in 01-Catalogs.ps1.
    Every registry policy value is snapshotted first so "Reset All Tweaks"
    restores the user's original settings; every service change is
    snapshotted so "Restore Services" can undo it. Fully -WhatIf aware.
#>

# ============================================================
#  BLOATWARE REMOVAL
# ============================================================
#  THE PURGE IS THREE TIERS, and skipping any one of them is why a
#  "removed" app comes back:
#
#    1. the INSTALLED package, per user profile. Remove only this and the
#       app is gone until the next feature update.
#    2. the PROVISIONED package - the copy staged for future users and
#       re-applied by servicing. Remove only tiers 1+2 and the app stays
#       gone, but the Start menu keeps promoting it.
#    3. the CONTENT DELIVERY policy that reinstalls promotional apps and
#       pins their tiles on its own schedule. This is the tier that makes
#       the other two permanent.
#
#  Tier 3 is not a per-app operation, so it runs once at the end of a
#  purge rather than inside the per-package loop.

function Resolve-BloatwareTargets {
    <#
    .SYNOPSIS
        Decide what a purge would touch. PURE - no registry, no AppX, no
        side effects.

    .DESCRIPTION
        THE WHOLE POINT OF THIS FUNCTION IS THAT IT TAKES ITS WORLD AS
        ARGUMENTS. The matching rules here are the dangerous part of the
        feature - wildcards against live package names, with a protected
        list standing between a typo and an unbootable shell - and none of
        that can be exercised on a developer's machine without actually
        removing their software. Handed the package lists instead, every
        rule is testable against a mocked inventory
        (tests/backend/Bloatware.Tests.ps1 does exactly that), including
        the cases that never occur locally: a pattern that grows a second
        match on a future build, a protected package caught by a catalog
        wildcard, an entry that is provisioned but not installed.

        Returns one record per catalog entry, whether or not it matched, so
        the GUI can render "not detected" rows rather than silently
        shortening its own list.

    .PARAMETER SelectedIds
        Exactly the entries to act on. EMPTY MEANS "every non-optional
        entry", which is what a headless `-Task RemoveBloatware` does; it
        does not mean "everything", because the optional tier exists
        precisely so that a purge nobody supervised does not take Game Bar
        with it.
    #>
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Catalog,
        [string[]]$Installed = @(),
        [string[]]$Provisioned = @(),
        [string[]]$Desktop = @(),
        [string[]]$SelectedIds = @(),
        [string[]]$Protected = @()
    )

    $Explicit = @($SelectedIds | Where-Object { $_ })
    $Results = @()

    foreach ($Entry in $Catalog) {
        $Match = if ($Entry.ContainsKey("Match")) { [string]$Entry.Match } else { "" }
        $DesktopName = if ($Entry.ContainsKey("Desktop")) { [string]$Entry.Desktop } else { "" }
        $Optional = [bool]($Entry.ContainsKey("Optional") -and $Entry.Optional)

        $HitInstalled = @()
        $HitProvisioned = @()
        $HitDesktop = @()
        $Blocked = @()

        if ($Match) {
            # A candidate is anything the catalog pattern matches; a TARGET
            # is a candidate no protected pattern claims. Splitting the two
            # is what lets the caller report "skipped, protected" instead
            # of silently doing nothing.
            foreach ($Name in @($Installed | Where-Object { $_ -like $Match })) {
                if (Test-ProtectedPackage -Name $Name -Protected $Protected) { $Blocked += $Name }
                else { $HitInstalled += $Name }
            }
            foreach ($Name in @($Provisioned | Where-Object { $_ -like $Match })) {
                if (Test-ProtectedPackage -Name $Name -Protected $Protected) { $Blocked += $Name }
                else { $HitProvisioned += $Name }
            }
        }
        if ($DesktopName) {
            $HitDesktop = @($Desktop | Where-Object { $_ -like $DesktopName })
        }

        $Detected = ($HitInstalled.Count + $HitProvisioned.Count + $HitDesktop.Count) -gt 0
        $Selected = if ($Explicit.Count -gt 0) { $Explicit -contains $Entry.Id } else { -not $Optional }

        $Results += [pscustomobject]@{
            Id          = [string]$Entry.Id
            Name        = [string]$Entry.Name
            Group       = [string]$Entry.Group
            Note        = if ($Entry.ContainsKey("Note")) { [string]$Entry.Note } else { "" }
            Optional    = $Optional
            Match       = $Match
            Installed   = @($HitInstalled | Sort-Object -Unique)
            Provisioned = @($HitProvisioned | Sort-Object -Unique)
            Desktop     = @($HitDesktop | Sort-Object -Unique)
            Blocked     = @($Blocked | Sort-Object -Unique)
            Detected    = $Detected
            Selected    = [bool]$Selected
        }
    }
    return $Results
}

function Test-ProtectedPackage {
    <# Is this package one no catalog wildcard may ever claim? See
       $Script:BloatProtected for why the list exists. Defaults to that
       list so callers cannot forget to pass it; the parameter is there so
       the rule itself stays testable. #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [string[]]$Protected
    )
    if ($null -eq $Protected) { $Protected = @($Script:BloatProtected) }
    foreach ($Pattern in $Protected) {
        if ($Pattern -and $Name -like $Pattern) { return $true }
    }
    return $false
}

function Get-InstalledDesktopBloat {
    <# DisplayName + UninstallString for every entry under the three
       Uninstall hives. Read-only; the 32-bit hive and HKCU are included
       because a codec pack lands in whichever one its installer chose. #>
    $Paths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $Found = @()
    foreach ($Path in $Paths) {
        $Keys = @()
        try { $Keys = @(Get-ItemProperty -Path $Path -ErrorAction Stop) }
        catch { continue }        # a hive that does not exist is not a failure
        foreach ($Key in $Keys) {
            $Name = [string]$Key.DisplayName
            if (-not $Name) { continue }
            $Found += [pscustomobject]@{
                DisplayName     = $Name
                UninstallString = [string]$Key.UninstallString
                QuietUninstall  = [string]$Key.QuietUninstallString
            }
        }
    }
    return $Found
}

function Get-BloatwareInventory {
    <# The catalog, resolved against what is actually on this machine.
       One AppX enumeration for the whole scan rather than one per entry:
       Get-AppxPackage -AllUsers is the most expensive call in the purge
       and the catalog has ~50 entries. #>
    param([string[]]$SelectedIds = @())

    $Installed = @()
    try {
        $Installed = @(Get-AppxPackage -AllUsers -ErrorAction Stop |
                       ForEach-Object { $_.Name })
    } catch {
        # -AllUsers needs elevation; an unelevated scan still has something
        # useful to say about the current profile, so fall back rather than
        # report an empty machine.
        Write-Log "Get-BloatwareInventory: -AllUsers enumeration failed ($($_.Exception.Message)); falling back to this profile."
        try { $Installed = @(Get-AppxPackage -ErrorAction Stop | ForEach-Object { $_.Name }) }
        catch { Write-Log "Get-BloatwareInventory: could not enumerate installed packages - $($_.Exception.Message)" }
    }

    # THE STAGED READ NEEDS ELEVATION, AND ITS ABSENCE IS NOT NOTHING.
    # A scan that cannot see provisioned packages cannot see the ones that
    # are staged but not installed - which is precisely the class that
    # reappears after a feature update, and precisely what tier 2 exists
    # to remove. Reporting "clean" on that evidence would be a lie of
    # omission, so the flag rides out to the dispatcher and the user is
    # told the scan was partial (see the BloatwareScan case).
    $Script:BloatProvisionedReadable = $true
    $Provisioned = @()
    try {
        $Provisioned = @(Get-AppxProvisionedPackage -Online -ErrorAction Stop |
                         ForEach-Object { $_.DisplayName })
    } catch {
        $Script:BloatProvisionedReadable = $false
        Write-Log "Get-BloatwareInventory: could not enumerate provisioned packages - $($_.Exception.Message)"
    }

    $Desktop = @()
    try { $Desktop = @(Get-InstalledDesktopBloat | ForEach-Object { $_.DisplayName }) }
    catch { Write-Log "Get-BloatwareInventory: could not read the uninstall hives - $($_.Exception.Message)" }

    return @(Resolve-BloatwareTargets -Catalog $Script:BloatCatalog `
                -Installed $Installed -Provisioned $Provisioned -Desktop $Desktop `
                -SelectedIds $SelectedIds -Protected $Script:BloatProtected)
}

function Disable-ConsumerPromotions {
    <#
    .SYNOPSIS
        Tier 3 - stop Windows re-installing and re-pinning promotional apps.

    .DESCRIPTION
        WITHOUT THIS, TIERS 1 AND 2 ARE TEMPORARY. Content Delivery Manager
        installs promotional apps silently, on its own schedule, into
        profiles that never asked for them - which is how Candy Crush
        arrives on a machine that was purged last week. Removing the app
        does not remove the subscription that put it there.

        Both values are snapshotted through Backup-OriginalRegValue, so
        "Reset All Tweaks" puts the user's own settings back exactly as it
        does for every other policy Pulse writes.

        HKCU, NOT HKLM, and that is a real limitation rather than an
        oversight: Content Delivery Manager is a per-user subscription and
        has no machine-wide equivalent that is not a licensed-edition group
        policy. A purge run by an administrator hardens the administrator's
        own profile; other profiles keep their subscriptions until Pulse
        runs there too.
    #>
    $Path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
    $Values = @(
        @{ Name = "SilentInstalledAppsEnabled";      Why = "silent promotional app installs" }
        @{ Name = "SubscribedContent-338388Enabled"; Why = "suggested apps on the Start menu" }
        @{ Name = "PreInstalledAppsEnabled";         Why = "the OEM preinstall subscription" }
        @{ Name = "OemPreInstalledAppsEnabled";      Why = "OEM-supplied promotional apps" }
        @{ Name = "SubscribedContent-338389Enabled"; Why = "tips and suggestions" }
        @{ Name = "ContentDeliveryAllowed";          Why = "content delivery as a whole" }
    )

    $Changed = $false
    foreach ($Value in $Values) {
        if ((Get-RegValue -Path $Path -Name $Value.Name) -eq 0) { continue }
        Backup-OriginalRegValue -TweakKey "ConsumerPromotions" -Path $Path -Name $Value.Name
        try {
            Set-RegValue -Path $Path -Name $Value.Name -Value 0 -Type DWord
            Write-Log "Disabled $($Value.Why) ($($Value.Name))."
            $Changed = $true
        } catch {
            # A promo key that will not take is worth saying out loud and
            # is NOT worth failing the purge over - the apps are still gone.
            Write-Warn "Could not disable $($Value.Why): $($_.Exception.Message)"
        }
    }
    if ($Changed) { Write-Success "Start menu promotions and silent app installs disabled." }
    else { Write-AlreadyOK "Start menu promotions were already disabled." }
    return $Changed
}

function Clear-DeadStartTiles {
    <#
    .SYNOPSIS
        Tier 3, second half - drop Start menu tiles whose app is gone.

    .DESCRIPTION
        A removed promotional app leaves its TILE behind, and a dead tile
        is not inert: it is a live install link, so clicking it fetches the
        app back from the Store. Clearing the layout cache is what turns
        "uninstalled" into "gone from the Start menu" - the state the user
        actually asked for.

        Windows rebuilds the cache from the packages that remain, so this
        is a REGENERATION and not a deletion of the user's own pins. It is
        also why it runs last: rebuilding before the packages are gone
        would just re-cache them.
    #>
    $Roots = @(
        "$env:LOCALAPPDATA\Microsoft\Windows\Caches"
        "$env:LOCALAPPDATA\Packages\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\LocalState"
    )
    $Cleared = 0
    foreach ($Root in $Roots) {
        if (-not (Test-Path -LiteralPath $Root)) { continue }
        $Files = @()
        try {
            $Files = @(Get-ChildItem -LiteralPath $Root -Filter "*.bin" -File -Recurse -ErrorAction Stop)
        } catch { continue }
        foreach ($File in $Files) {
            if (Test-DryRun "Clear Start menu tile cache '$($File.Name)'") { $Cleared++; continue }
            try {
                Remove-Item -LiteralPath $File.FullName -Force -ErrorAction Stop
                $Cleared++
            } catch {
                # The shell holds these open while it is running. That is
                # normal, not a failure: the cache is rebuilt at the next
                # sign-in either way.
                Write-Log "Start tile cache '$($File.Name)' is in use; it will be rebuilt at next sign-in."
            }
        }
    }
    if ($Cleared -gt 0) { Write-Log "Cleared $Cleared Start menu tile cache file(s)." }
    return $Cleared
}

function Uninstall-DesktopBloat {
    <#
    .SYNOPSIS
        Remove a classic MSI/EXE leftover found through the registry.

    .DESCRIPTION
        K-Lite is the catalogued case. It has no AppX identity, so the
        whole three-tier pipeline is inapplicable: what exists is an
        Uninstall key with a command line in it.

        QuietUninstallString IS PREFERRED OVER UninstallString, and the
        difference matters here more than it usually does. Pulse's engine
        runs $Script:NonInteractive for the whole session and the GUI shows
        no window for it - so an uninstaller that opens a wizard is one
        nobody can click, on a task the user believes is running. Where
        only UninstallString exists, the known silent switches for that
        installer family are appended rather than guessed at globally.
    #>
    param(
        [Parameter(Mandatory)][string]$DisplayPattern,
        [Parameter(Mandatory)][string]$Label
    )
    $Entries = @(Get-InstalledDesktopBloat | Where-Object { $_.DisplayName -like $DisplayPattern })
    if ($Entries.Count -eq 0) { return $false }

    $Removed = $false
    foreach ($Entry in $Entries) {
        $Command = $Entry.QuietUninstall
        $Silent = ""
        if (-not $Command) {
            $Command = $Entry.UninstallString
            # /VERYSILENT is Inno Setup's, /S is NSIS's. K-Lite ships an
            # Inno uninstaller; both are appended because the pack has
            # shipped under both engines across its history and an
            # unrecognised switch is ignored rather than fatal.
            $Silent = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
        }
        if (-not $Command) {
            Write-Warn "$Label is installed but records no uninstall command; remove it from Settings > Apps."
            continue
        }
        if (Test-DryRun "Uninstall '$($Entry.DisplayName)' silently") { $Removed = $true; continue }

        try {
            $Exe = $Command
            $Switches = $Silent
            if ($Command -match '^\s*"([^"]+)"\s*(.*)$') {
                $Exe = $Matches[1]
                $Switches = (($Matches[2] + " " + $Silent).Trim())
            } elseif ($Command -match '^\s*(\S+\.exe)\s*(.*)$') {
                $Exe = $Matches[1]
                $Switches = (($Matches[2] + " " + $Silent).Trim())
            }
            $Proc = if ($Switches) {
                Start-Process -FilePath $Exe -ArgumentList $Switches -Wait -PassThru -ErrorAction Stop
            } else {
                Start-Process -FilePath $Exe -Wait -PassThru -ErrorAction Stop
            }
            if ($Proc.ExitCode -eq 0) {
                Write-Success "Removed $Label."
                $Removed = $true
            } else {
                Write-Warn "$Label's uninstaller exited with code $($Proc.ExitCode)."
            }
        } catch {
            Write-Warn "Could not run $Label's uninstaller: $($_.Exception.Message)"
        }
    }
    return $Removed
}

function Remove-Bloatware {
    <#
    .SYNOPSIS
        The purge. Three tiers, one restore point, nothing fatal.

    .PARAMETER SelectedIds
        Catalog Ids to remove. Empty runs every NON-OPTIONAL entry, which
        is what a headless run does - see Resolve-BloatwareTargets.

    .DESCRIPTION
        NOTHING IN HERE MAY HALT THE QUEUE. A package the platform refuses
        to remove is the normal case on a managed machine, not an
        exception: Windows protects framework packages, an in-use app
        cannot be unstaged, and some editions pin Xbox and Widgets by
        policy. Every removal is therefore individually trapped and the
        loop continues; the run's verdict comes from whether any package
        the user selected was still there at the end, not from whether
        every call returned cleanly.

        The one thing that IS reported as a failure is a selected package
        that neither removed nor was protected - because that is the case
        where the user asked for something and did not get it.
    #>
    param([string[]]$SelectedIds = @())

    Write-SectionHeader "Bloatware Removal"
    New-SystemRestorePoint

    $Targets = @(Get-BloatwareInventory -SelectedIds $SelectedIds)
    $Chosen = @($Targets | Where-Object { $_.Selected -and $_.Detected })

    if ($Chosen.Count -eq 0) {
        $AnyDetected = @($Targets | Where-Object { $_.Detected }).Count
        if ($AnyDetected -eq 0) {
            Write-AlreadyOK "No catalogued bloatware found - this system is already clean."
        } else {
            Write-AlreadyOK "Nothing selected was installed - $AnyDetected other package(s) remain, unselected."
        }
        Disable-ConsumerPromotions | Out-Null
        Write-Info "Bloatware sweep complete."
        return
    }

    $RemovedAny = $false
    $Protected = 0
    $Index = 0
    foreach ($Target in $Chosen) {
        $Index++
        Write-GuiStage "[$Index/$($Chosen.Count)] $($Target.Name)"

        if ($Target.Blocked.Count -gt 0) {
            # The catalog's wildcard reached something on the protected
            # list. Say so rather than passing over it silently: a pattern
            # that has started matching the shell is a catalog bug, and the
            # log is where it becomes visible.
            Write-Log "SKIP (protected): $($Target.Name) matched $($Target.Blocked -join ', ')"
            $Protected += $Target.Blocked.Count
        }

        # -- tier 1: the installed package, every profile ----------------
        foreach ($Name in $Target.Installed) {
            if (Test-DryRun "Remove Store app '$Name' for all users") { $RemovedAny = $true; continue }
            try {
                Get-AppxPackage -Name $Name -AllUsers -ErrorAction Stop |
                    Remove-AppxPackage -AllUsers -ErrorAction Stop
                Write-Success "Removed $($Target.Name)"
                $RemovedAny = $true
            } catch {
                Write-ErrorX "Could not remove $($Target.Name) (may be protected by policy): $($_.Exception.Message)"
            }
        }

        # -- tier 2: the staged template, so it cannot come back ---------
        foreach ($Name in $Target.Provisioned) {
            if (Test-DryRun "Deprovision staged package '$Name' so it will not reinstall") { $RemovedAny = $true; continue }
            try {
                $Staged = @(Get-AppxProvisionedPackage -Online -ErrorAction Stop |
                            Where-Object { $_.DisplayName -eq $Name })
                foreach ($Package in $Staged) {
                    Remove-AppxProvisionedPackage -Online -PackageName $Package.PackageName -ErrorAction Stop | Out-Null
                    Write-Success "Deprovisioned $($Target.Name) (will not return after a feature update)"
                    $RemovedAny = $true
                }
            } catch {
                # A deprovision failure is a WARNING, not an error: tier 1
                # is the authoritative signal, and many staged packages are
                # simply not present to unstage.
                Write-Warn "Could not deprovision $($Target.Name): $($_.Exception.Message)"
            }
        }

        # -- desktop leftovers (K-Lite and friends) ----------------------
        if ($Target.Desktop.Count -gt 0) {
            $Entry = @($Script:BloatCatalog | Where-Object { $_.Id -eq $Target.Id })[0]
            if ($Entry -and $Entry.ContainsKey("Desktop")) {
                if (Uninstall-DesktopBloat -DisplayPattern $Entry.Desktop -Label $Target.Name) { $RemovedAny = $true }
            }
        }
    }

    # -- tier 3: stop the promotions that put them there -----------------
    Disable-ConsumerPromotions | Out-Null
    Clear-DeadStartTiles | Out-Null

    if (-not $RemovedAny) {
        Write-AlreadyOK "No listed bloatware packages found - system is already clean."
    }
    if ($Protected -gt 0) {
        Write-Info "$Protected system-critical package(s) were skipped - see the log."
    }
    Write-Info "Bloatware sweep complete."
}

# ============================================================
#  TELEMETRY & DIAGNOSTICS
# ============================================================
function Disable-Telemetry {
    Write-SectionHeader "Telemetry & Diagnostics"
    New-SystemRestorePoint
    $Path = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection"
    $AlreadySet = (Get-RegValue -Path $Path -Name "AllowTelemetry") -eq 0
    $DiagTrackSvc = Get-Service -Name "DiagTrack" -ErrorAction SilentlyContinue
    $AlreadyStopped = (-not $DiagTrackSvc) -or ($DiagTrackSvc.Status -eq "Stopped" -and $DiagTrackSvc.StartType -eq "Disabled")

    if ($AlreadySet -and $AlreadyStopped) {
        Write-AlreadyOK "Telemetry is already disabled."
        return
    }

    Backup-OriginalRegValue -TweakKey "Telemetry" -Path $Path -Name "AllowTelemetry"
    Backup-ServiceState -Name "DiagTrack"
    Backup-ServiceState -Name "dmwappushservice"

    try {
        Set-RegValue -Path $Path -Name "AllowTelemetry" -Value 0 -Type DWord

        Invoke-Mutation -Description "Disable and stop the DiagTrack + dmwappushservice services" -Action {
            Set-Service -Name "DiagTrack" -StartupType Disabled -ErrorAction SilentlyContinue
            Stop-Service -Name "DiagTrack" -Force -ErrorAction SilentlyContinue
            Set-Service -Name "dmwappushservice" -StartupType Disabled -ErrorAction SilentlyContinue
        } | Out-Null

        foreach ($Task in $Script:TelemetryTasks) {
            Invoke-Mutation -Description "Disable scheduled task '$($Task.Path)$($Task.Name)'" -Action {
                Disable-ScheduledTask -TaskPath $Task.Path -TaskName $Task.Name -ErrorAction SilentlyContinue | Out-Null
            } | Out-Null
        }
        Write-Success "Telemetry services and scheduled diagnostics disabled."
    } catch {
        Write-ErrorX "Telemetry hardening encountered an issue: $($_.Exception.Message)"
    }
}

# ============================================================
#  ADVERTISING ID
# ============================================================
function Disable-AdvertisingID {
    New-SystemRestorePoint
    $Path = "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\AdvertisingInfo"
    if ((Get-RegValue -Path $Path -Name "Enabled") -eq 0) {
        Write-AlreadyOK "Advertising ID is already disabled."
        return
    }
    Backup-OriginalRegValue -TweakKey "AdvertisingID" -Path $Path -Name "Enabled"
    try {
        Set-RegValue -Path $Path -Name "Enabled" -Value 0 -Type DWord
        Write-Success "Advertising ID disabled."
    } catch {
        Write-ErrorX "Failed to disable Advertising ID: $($_.Exception.Message)"
    }
}

# ============================================================
#  ACTIVITY HISTORY
# ============================================================
function Disable-ActivityHistory {
    New-SystemRestorePoint
    $Path = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\System"
    if ((Get-RegValue -Path $Path -Name "EnableActivityFeed") -eq 0) {
        Write-AlreadyOK "Activity History sync is already disabled."
        return
    }
    Backup-OriginalRegValue -TweakKey "ActivityHistory" -Path $Path -Name "EnableActivityFeed"
    Backup-OriginalRegValue -TweakKey "ActivityHistory" -Path $Path -Name "PublishUserActivities"
    Backup-OriginalRegValue -TweakKey "ActivityHistory" -Path $Path -Name "UploadUserActivities"
    try {
        Set-RegValue -Path $Path -Name "EnableActivityFeed" -Value 0 -Type DWord
        Set-RegValue -Path $Path -Name "PublishUserActivities" -Value 0 -Type DWord
        Set-RegValue -Path $Path -Name "UploadUserActivities" -Value 0 -Type DWord
        Write-Success "Activity History sync disabled."
    } catch {
        Write-ErrorX "Failed to disable Activity History: $($_.Exception.Message)"
    }
}
