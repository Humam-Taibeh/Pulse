#Requires -Version 5.1
<#
.SYNOPSIS
    07-Maintenance.ps1 - system repair (SFC/DISM), cache cleanup, disk
    management and the services optimizer.

.DESCRIPTION
    All destructive operations are dry-run aware:
      - Clear-SystemCaches under -WhatIf measures reclaimable space without
        deleting a single file.
      - Remove-WindowsOldFolder reports the folder size it would reclaim.
      - Service changes are snapshotted first (02-Safety.ps1) so "Restore
        All Services" can put them back exactly as they were.
    The optional-services list is data ($Script:OptionalServices).
#>

# ============================================================
#  ADVANCED REPAIR (SFC + DISM)
# ============================================================
function Invoke-SystemRepair {
    New-SystemRestorePoint
    if (Test-DryRun "Run 'sfc /scannow' followed by 'DISM /Online /Cleanup-Image /RestoreHealth'") { return $true }

    Write-SectionHeader "System File Checker (SFC)"
    Write-Info "Running sfc /scannow -- live output below. This can take several minutes."
    $SfcOk = Invoke-WithRetry -OperationName "SFC Scan" -Action {
        # sfc.exe emits UTF-16: read through a redirected pipe, every other
        # byte is a NUL, which breaks both the display and — critically —
        # the "unable to fix" text match below. Strip NULs before use.
        # Stream-while-accumulating (v6): each line is echoed the moment
        # sfc produces it, so "Verification x% complete." rewrites reach
        # the GUI live instead of arriving in one block after the scan.
        $OutputLines = New-Object System.Collections.Generic.List[string]
        & (Get-SystemBinary 'sfc') /scannow 2>&1 | ForEach-Object {
            $Clean = ([string]$_ -replace "`0", "")
            [void]$OutputLines.Add($Clean)
            if ($Clean.Trim()) { Write-Host $Clean }
        }
        $SfcExit = $LASTEXITCODE
        $OutputText = $OutputLines -join [Environment]::NewLine

        if ($SfcExit -ne 0) {
            throw "sfc /scannow exited with code $SfcExit."
        }

        # sfc's exit code alone is not trustworthy: on several Windows builds
        # it still returns 0 even when it explicitly says it could not fix
        # everything it found. That text is the real signal, so treat it as
        # a failure regardless of exit code.
        # NOTE: this match is English-only - sfc's message is localized on
        # non-English Windows installs, so this check is a best-effort net,
        # not a guarantee, on those systems.
        if ($OutputText -match "unable to fix some of them") {
            throw "sfc /scannow found corrupt files it could not fully repair. See CBS.log for details."
        }
    }

    Write-SectionHeader "DISM Image Health Restore"
    Write-Info "Running DISM /Online /Cleanup-Image /RestoreHealth -- live output below."
    $DismOk = Invoke-WithRetry -OperationName "DISM RestoreHealth" -Action {
        # Pipe through Write-Host so the progress streams to the caller
        # instead of being captured into Invoke-WithRetry's return value
        # (which silently hid all DISM output and polluted $DismOk).
        & (Get-SystemBinary 'dism') /Online /Cleanup-Image /RestoreHealth | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) { throw "DISM exited with code $LASTEXITCODE." }
    }

    return ($SfcOk -and $DismOk)
}

# ============================================================
#  AGGRESSIVE CACHE CLEAN
# ============================================================
function Clear-SystemCaches {
    Write-SectionHeader "Temporary File, Prefetch & Windows Update Cleanup"
    $Targets = @(
        $env:TEMP,
        "$env:SystemRoot\Temp",
        "$env:SystemRoot\Prefetch",
        "$env:SystemRoot\SoftwareDistribution\Download"
    ) | Select-Object -Unique

    $TotalFreedBytes = 0
    $LockedCount     = 0
    foreach ($Target in $Targets) {
        if (-not (Test-Path $Target)) { continue }
        if ($Script:DryRun) { Write-Info "[WHATIF] Measuring (not deleting) $Target ..." }
        else                { Write-Info "Cleaning $Target ..." }
        # Top-level entries only: a -Recurse enumeration followed by a
        # per-item -Recurse delete visits every descendant twice - once as
        # its own list entry, once again as part of its parent's recursive
        # delete. The second visit hits a path that's already gone, throws,
        # and both falsely inflates $LockedCount and undercounts freed
        # bytes (a whole subtree's size, minus whatever leaf happened to
        # be enumerated last). Deleting only the top-level item per target
        # removes its entire subtree in one filesystem operation, so no
        # child is ever independently visited after its parent is gone.
        Get-ChildItem -Path $Target -Force -ErrorAction SilentlyContinue | ForEach-Object {
            $Item = $_
            $Size = 0
            if ($Item.PSIsContainer) {
                $Sum = (Get-ChildItem -Path $Item.FullName -Recurse -Force -ErrorAction SilentlyContinue |
                        Where-Object { -not $_.PSIsContainer } |
                        Measure-Object -Property Length -Sum).Sum
                if ($Sum) { $Size = $Sum }
            } else {
                $Size = $Item.Length
            }
            if ($Script:DryRun) {
                # Dry-run: tally what a real pass would reclaim, delete nothing.
                $TotalFreedBytes += $Size
                return
            }
            try {
                Remove-Item -Path $Item.FullName -Recurse -Force -ErrorAction Stop
                $TotalFreedBytes += $Size
            } catch {
                $LockedCount++
            }
        }
    }

    if (-not (Test-DryRun "Empty the Recycle Bin")) {
        try {
            Write-Info "Emptying Recycle Bin..."
            Clear-RecycleBin -Force -ErrorAction SilentlyContinue
        } catch {}
    }

    $FreedMB = [math]::Round($TotalFreedBytes / 1MB, 2)
    if ($Script:DryRun) {
        Write-Success "Dry-run complete. A real cleanup pass would reclaim approximately $FreedMB MB."
    } else {
        Write-Success "Cache cleanup complete. Approximately $FreedMB MB reclaimed."
    }
    if ($LockedCount -gt 0) {
        Write-Warn "$LockedCount item(s) were skipped because they were locked/in use (normal for active update/prefetch files)."
    }
}

# ============================================================
#  WINDOWS UPDATE DRIVER SYNCHRONISATION
# ============================================================
function Invoke-PulseDriverSync {
    <#
    .SYNOPSIS
        Ask Windows Update to go and find this board's missing drivers.

    .DESCRIPTION
        THE PROBLEM THIS SOLVES IS A FRESH INSTALL. Windows ships with
        generic in-box drivers for most devices and OEM-specific ones for
        almost none, so a newly-imaged machine sits with a working screen
        and no Bluetooth, mono audio through a Realtek codec running the
        HD Audio stub, an Intel Wi-Fi card on a 2019 driver, and one or
        two "Unknown device" entries that are the chipset. Every one of
        those drivers IS available - through Windows Update's driver
        channel, published by the vendor, under names nobody would search
        for. What is missing is the ASKING.

        Nothing in Pulse asked. DriverScan (30-GuiDispatcher.ps1) READS the
        update agent's current answer, and on a fresh install that answer
        is "nothing pending", because no scan has run yet. So the module
        that exists to make a new machine complete reported a clean bill
        of health on exactly the machine that needed the most work.

        THE TWO HALVES, and both are needed:

          1. USOClient StartScan - tells the Update Orchestrator to run a
             scan NOW rather than at whatever hour it had planned. This is
             the one that reaches the driver channel the way Windows
             itself does, including the OEM-targeted publications a manual
             COM search does not see by default.

          2. A COM search for uninstalled drivers, which is what turns an
             asynchronous request into something we can REPORT. StartScan
             returns immediately and prints nothing - on its own it would
             leave the task saying "done" with no evidence anything
             happened.

        USOClient IS UNDOCUMENTED, and is treated accordingly: its absence
        or refusal is a WARNING, not a failure, and the COM search still
        runs. Windows Server and some managed builds do not ship it, and
        a machine whose drivers are governed by WSUS policy will decline
        the request outright. Neither is Pulse malfunctioning, and neither
        should paint the card red.

        NOT ELEVATION-GATED. The scan is performed by the Update
        Orchestrator, which runs as SYSTEM; the client only posts the
        request. An unelevated Pulse gets exactly the same scan an
        elevated one does, so gating this would raise a UAC prompt that
        buys the user nothing.

        NOTHING IS INSTALLED HERE. Requesting a scan is what makes Windows
        download and stage what it finds, on its own schedule and with its
        own rollback - which is the correct owner for a driver install.
        Pulse forcing a driver package onto a device is how a machine ends
        up with no display output.
    #>
    if (Test-DryRun "Ask Windows Update to scan for missing hardware drivers") { return $true }

    Write-Info "Asking Windows Update to scan for hardware drivers..."
    $Requested = $false
    try {
        $Uso = Get-SystemBinary 'usoclient'
        if (Test-Path -LiteralPath $Uso -PathType Leaf) {
            # -NoNewWindow suppresses the console box; the orchestrator
            # does the work out of process, so this returns at once and
            # the -Wait is only to collect the exit code.
            $Proc = Start-Process -FilePath $Uso -ArgumentList "StartScan" `
                -Wait -NoNewWindow -PassThru -ErrorAction Stop
            if ($Proc.ExitCode -eq 0) {
                $Requested = $true
                Write-Success "Windows Update scan requested (Update Orchestrator)."
            } else {
                Write-Warn "The Update Orchestrator declined the scan request (exit code $($Proc.ExitCode)) - Windows Update may be managed by policy."
            }
        } else {
            Write-Warn "UsoClient.exe is not present on this build of Windows - falling back to a direct driver search."
        }
    } catch {
        Write-Warn "Could not signal the Update Orchestrator: $($_.Exception.Message). Falling back to a direct driver search."
    }

    # THE REPORT, and it runs whether or not the request above landed:
    # a machine that already scanned recently has the answer waiting, and
    # a machine where USOClient is absent still deserves to be told what
    # its update agent knows.
    #
    # ServerSelection = 3 ("Others") with the Microsoft Update service id
    # is what widens the search past the Windows-only default to the
    # driver publications vendors actually ship through. It is set only
    # when that service is registered; on a machine where it is not, the
    # searcher keeps its default rather than being pointed at a service
    # id that does not resolve.
    try {
        $Session  = New-Object -ComObject Microsoft.Update.Session
        $Searcher = $Session.CreateUpdateSearcher()
        try {
            $ServiceManager = New-Object -ComObject Microsoft.Update.ServiceManager
            $MicrosoftUpdate = "7971f918-a847-4430-9279-4a52d1efe18d"
            if (@($ServiceManager.Services) | Where-Object { $_.ServiceID -eq $MicrosoftUpdate }) {
                $Searcher.ServerSelection = 3
                $Searcher.ServiceID = $MicrosoftUpdate
            }
        } catch {
            Write-Log "DRIVERSYNC: Microsoft Update service not usable ($($_.Exception.Message)); using the default source."
        }
        $Found = $Searcher.Search("IsInstalled=0 and Type='Driver'")
        $Count = @($Found.Updates).Count
        if ($Count -gt 0) {
            foreach ($Update in $Found.Updates) { Write-Log "DRIVERSYNC PENDING: $($Update.Title)" }
            Write-Success "$Count driver update(s) are available for this machine - names are in the log."
        } elseif ($Requested) {
            Write-Info "No driver updates are pending yet. The scan runs in the background; check Settings > Windows Update in a few minutes."
        } else {
            Write-Info "No driver updates are pending - every device on this machine is already covered."
        }
        return $true
    } catch {
        # ONLY here does the task fail. Being unable to ASK is a warning
        # (the orchestrator is undocumented and may be policy-managed);
        # being unable to reach the update agent at all means the service
        # is stopped or broken, which is a real finding the card should
        # show in red.
        Write-ErrorX "Could not query Windows Update for drivers: $($_.Exception.Message)"
        return $false
    }
}

# ============================================================
#  DISK CLEANUP & OPTIMIZATION
# ============================================================
function Show-DriveSpaceReport {
    Write-SectionHeader "Drive Space Report"
    # $null on the LEFT: PowerShell's comparison operators filter arrays
    # element-wise when the left operand is a collection, so the reversed
    # form is the only one that reliably means "is this value null?".
    $Drives = Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue | Where-Object { $null -ne $_.Used -and $null -ne $_.Free }
    foreach ($Drive in $Drives) {
        $TotalGB   = [math]::Round(($Drive.Used + $Drive.Free) / 1GB, 1)
        $FreeGB    = [math]::Round($Drive.Free / 1GB, 1)
        $PercentFree = if ($TotalGB -gt 0) { [math]::Round(($FreeGB / $TotalGB) * 100, 0) } else { 0 }
        $Color = if ($PercentFree -lt 10) { "Red" } elseif ($PercentFree -lt 20) { "Yellow" } else { "Green" }
        Write-Host ("   {0}:\  {1,6} GB free of {2,6} GB  ({3}% free)" -f $Drive.Name, $FreeGB, $TotalGB, $PercentFree) -ForegroundColor $Color
    }
}

function Remove-WindowsOldFolder {
    $Path = "$env:SystemDrive\Windows.old"
    if (-not (Test-Path $Path)) {
        Write-AlreadyOK "No Windows.old folder present - nothing to remove."
        return
    }
    try {
        $SizeGB = [math]::Round(((Get-ChildItem -Path $Path -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum) / 1GB, 2)
        Write-Info "Windows.old is approximately $SizeGB GB."
        if (Test-DryRun "Delete $Path (reclaims ~$SizeGB GB)") { return }
        Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
        Write-Success "Windows.old removed, reclaiming approximately $SizeGB GB."
    } catch {
        Write-ErrorX "Could not fully remove Windows.old: $($_.Exception.Message). Try Disk Cleanup's 'Previous Windows installations' option instead."
    }
}

function Set-HibernationState {
    param([bool]$Enable)
    $HiberFile = "$env:SystemDrive\hiberfil.sys"
    $CurrentlyEnabled = Test-Path $HiberFile
    if ($Enable -eq $CurrentlyEnabled) {
        $StateWord = if ($Enable) { "enabled" } else { "disabled" }
        Write-AlreadyOK "Hibernation is already $StateWord."
        return
    }
    $TargetWord = if ($Enable) { "on" } else { "off" }
    if (Test-DryRun "Run 'powercfg /hibernate $TargetWord'") { return }
    try {
        if ($Enable) {
            & (Get-SystemBinary 'powercfg') /hibernate on | Out-Null
            Write-Success "Hibernation enabled."
        } else {
            & (Get-SystemBinary 'powercfg') /hibernate off | Out-Null
            Write-Success "Hibernation disabled (hiberfil.sys removed, frees disk space equal to a portion of installed RAM)."
        }
    } catch {
        Write-ErrorX "Could not change hibernation state: $($_.Exception.Message)"
    }
}

function Optimize-AllDrives {
    Write-SectionHeader "Drive Optimization (TRIM / Defrag)"
    $Volumes = Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' }
    if (-not $Volumes) {
        Write-Warn "No fixed volumes detected to optimize."
        return
    }
    foreach ($Vol in $Volumes) {
        if (Test-DryRun "Optimize drive $($Vol.DriveLetter): (TRIM for SSD / defrag for HDD)") { continue }
        try {
            Write-Info "Optimizing $($Vol.DriveLetter): ..."
            Optimize-Volume -DriveLetter $Vol.DriveLetter -ErrorAction Stop
            Write-Success "$($Vol.DriveLetter): optimized (TRIM for SSD / defrag for HDD, auto-detected)."
        } catch {
            # A real per-drive failure (active VSS snapshot, BitLocker,
            # network mount are all plausible) - Write-ErrorX, not Write-Warn,
            # so "OptimizeDrives" doesn't report full success when a drive
            # was actually skipped due to an error.
            Write-ErrorX "Could not optimize $($Vol.DriveLetter): $($_.Exception.Message)"
        }
    }
}

function Invoke-DiskCleanupUtility {
    if (Test-DryRun "Launch the native Disk Cleanup utility (cleanmgr.exe)") { return }
    Write-Info "Launching the native Disk Cleanup utility (cleanmgr.exe)..."
    try {
        Start-Process (Get-SystemBinary 'cleanmgr') -ErrorAction Stop
        Write-Success "Disk Cleanup launched. Follow its on-screen prompts."
    } catch {
        Write-ErrorX "Could not launch Disk Cleanup: $($_.Exception.Message)"
    }
}

function Show-DiskCleanupModule {
    Show-DriveSpaceReport

    if (Ask-User "Remove Windows.old" "Deletes the previous Windows installation backup folder (if present) to reclaim significant disk space.") {
        Remove-WindowsOldFolder
    }

    if (Ask-User "Toggle Hibernation" "Enables hibernation if currently off, or disables it (and removes hiberfil.sys) if currently on.") {
        $CurrentlyEnabled = Test-Path "$env:SystemDrive\hiberfil.sys"
        Set-HibernationState -Enable (-not $CurrentlyEnabled)
    }

    if (Ask-User "Optimize All Fixed Drives" "Runs TRIM on SSDs and defragmentation on HDDs automatically (Windows auto-detects drive type).") {
        Optimize-AllDrives
    }

    if (Ask-User "Open Native Disk Cleanup Utility" "Launches cleanmgr.exe for a full interactive cleanup pass, including system file cleanup.") {
        Invoke-DiskCleanupUtility
    }
}

# ============================================================
#  SERVICES OPTIMIZER
# ============================================================
function Get-ServiceState {
    param([string]$Name)
    $Svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $Svc) {
        return [PSCustomObject]@{ Exists = $false; Status = "N/A"; StartType = "N/A" }
    }
    # ESCAPED: $Name is interpolated into a WQL string literal, and WQL
    # quotes with ' and escapes with \. A service name carrying either ends
    # the literal early and the remainder is parsed as QUERY - the WMI
    # equivalent of SQL injection. Service names reach here from the
    # catalog and, on the Restore-Services path, from the machine's own
    # service list, so this is not a value the caller fully controls.
    $Filter = "Name='{0}'" -f (ConvertTo-WqlLiteral $Name)
    $StartType = (Get-CimInstance Win32_Service -Filter $Filter -ErrorAction SilentlyContinue).StartMode
    return [PSCustomObject]@{ Exists = $true; Status = $Svc.Status; StartType = $StartType }
}

function Disable-OptionalService {
    param([string]$Name, [string]$Label)
    New-SystemRestorePoint
    $State = Get-ServiceState -Name $Name
    if (-not $State.Exists) {
        Write-Warn "Skipped '$Label': service not present on this system/edition."
        return
    }
    if ($State.StartType -eq "Disabled" -and $State.Status -eq "Stopped") {
        Write-AlreadyOK "'$Label' is already disabled."
        return
    }
    Backup-ServiceState -Name $Name
    if (Test-DryRun "Stop and disable service '$Name' ($Label)") { return }
    try {
        if ($State.Status -eq "Running") { Stop-Service -Name $Name -Force -ErrorAction Stop }
        Set-Service -Name $Name -StartupType Disabled -ErrorAction Stop
        Write-Success "'$Label' stopped and disabled."
    } catch {
        Write-ErrorX "Could not disable '$Label': $($_.Exception.Message) (may be protected by policy)."
    }
}

function Enable-OptionalService {
    param([string]$Name, [string]$Label)
    $State = Get-ServiceState -Name $Name
    if (-not $State.Exists) {
        Write-Warn "Skipped '$Label': service not present on this system/edition."
        return
    }
    if ($State.StartType -ne "Disabled") {
        Write-AlreadyOK "'$Label' is already enabled (startup type: $($State.StartType))."
        return
    }
    if (Test-DryRun "Re-enable service '$Name' ($Label) with startup type Manual") { return }
    try {
        Set-Service -Name $Name -StartupType Manual -ErrorAction Stop
        Start-Service -Name $Name -ErrorAction SilentlyContinue
        Write-Success "'$Label' re-enabled (startup type: Manual)."
    } catch {
        Write-ErrorX "Could not re-enable '$Label': $($_.Exception.Message)"
    }
}

function Show-ServicesOptimizer {
    do {
        Write-Banner "SERVICES OPTIMIZER"
        for ($i = 0; $i -lt $Script:OptionalServices.Count; $i++) {
            $Svc   = $Script:OptionalServices[$i]
            $State = Get-ServiceState -Name $Svc.Name
            $Tag   = if (-not $State.Exists) { "N/A     " }
                     elseif ($State.StartType -eq "Disabled") { "DISABLED" }
                     else { "ENABLED " }
            $Color = if (-not $State.Exists) { "DarkGray" } elseif ($Tag -eq "DISABLED") { "DarkGray" } else { "Green" }
            Write-Host ("   [{0,2}] [{1}] {2}" -f ($i + 1), $Tag, $Svc.Label) -ForegroundColor $Color
        }
        Write-Divider
        Write-Host "   [D]  Disable a service" -ForegroundColor White
        Write-Host "   [E]  Re-enable a service" -ForegroundColor White
        Write-Host "   [A]  Disable ALL recommended (bulk)" -ForegroundColor Magenta
        Write-Host "   [I]  Show info note for a service" -ForegroundColor DarkGray
        Write-Host "   [X]  Back to Main Menu" -ForegroundColor DarkGray
        Write-Divider
        $Choice = Read-Choice -Prompt "   Select an action" -Valid @('d','e','a','i','x')

        switch ($Choice) {
            'd' {
                $Idx = Read-NumericChoice -Prompt "   Enter service number to disable" -Max $Script:OptionalServices.Count
                if ($null -ne $Idx) {
                    $Svc = $Script:OptionalServices[$Idx - 1]
                    if (Ask-User "Disable '$($Svc.Label)'" $Svc.Note) {
                        Disable-OptionalService -Name $Svc.Name -Label $Svc.Label
                    }
                } else { Write-Warn "Invalid service number." }
                Start-Sleep -Seconds 1
            }
            'e' {
                $Idx = Read-NumericChoice -Prompt "   Enter service number to re-enable" -Max $Script:OptionalServices.Count
                if ($null -ne $Idx) {
                    $Svc = $Script:OptionalServices[$Idx - 1]
                    Enable-OptionalService -Name $Svc.Name -Label $Svc.Label
                } else { Write-Warn "Invalid service number." }
                Start-Sleep -Seconds 1
            }
            'a' {
                if (Ask-User "Disable ALL Recommended Services" "Disables every service listed above in one pass. Already-disabled services are reported and skipped.") {
                    foreach ($Svc in $Script:OptionalServices) {
                        Disable-OptionalService -Name $Svc.Name -Label $Svc.Label
                    }
                }
                Read-Host "   Press Enter to continue"
            }
            'i' {
                $Idx = Read-NumericChoice -Prompt "   Enter service number to view info" -Max $Script:OptionalServices.Count
                if ($null -ne $Idx) {
                    $Svc = $Script:OptionalServices[$Idx - 1]
                    Write-StatusPanel -Label $Svc.Label -Text $Svc.Note
                } else { Write-Warn "Invalid service number." }
                Read-Host "   Press Enter to continue"
            }
            'x' { return }
        }
    } while ($true)
}
