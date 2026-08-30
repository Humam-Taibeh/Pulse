#Requires -Version 5.1
<#
.SYNOPSIS
    06-Tweaks.ps1 - the data-driven tweak engine plus every system tweak
    and optimization that mutates registry / power / network state.

.DESCRIPTION
    - Invoke-Tweak consumes $Script:TweakCatalog entries (01-Catalogs.ps1):
      a tweak is DATA (registry entries with On/Off values), never a bespoke
      function. Adding a tweak = adding a catalog entry.
    - Every change snapshots the original value first (02-Safety.ps1) and
      creates the once-per-session restore point.
    - All mutations flow through the dry-run primitives, so -WhatIf walks
      the exact same code paths and reports every write it would perform.
#>

# ============================================================
#  DATA-DRIVEN TWEAK ENGINE
# ============================================================
function Test-TweakAlreadyOn {
    param([hashtable]$Tweak)
    foreach ($E in $Tweak.Entries) {
        $Current = Get-RegValue -Path $E.Path -Name $E.Name
        if ("$Current" -ne "$($E.OnValue)") { return $false }
    }
    return $true
}

function Invoke-Tweak {
    param(
        [Parameter(Mandatory)][hashtable]$Tweak,
        [ValidateSet("On","Off")][string]$State = "On"
    )

    Write-SectionHeader $Tweak.Description

    if ($State -eq "On" -and (Test-TweakAlreadyOn -Tweak $Tweak)) {
        Write-AlreadyOK "$($Tweak.Key) is already applied."
        return
    }

    New-SystemRestorePoint

    Invoke-WithRetry -OperationName "Tweak: $($Tweak.Key)" -Action {
        foreach ($E in $Tweak.Entries) {
            Backup-OriginalRegValue -TweakKey $Tweak.Key -Path $E.Path -Name $E.Name
            $Value = if ($State -eq "On") { $E.OnValue } else { $E.OffValue }
            Set-RegValue -Path $E.Path -Name $E.Name -Value $Value -Type $E.Type
        }
        Write-Success "$($Tweak.Key) applied successfully."
    } | Out-Null

    # Theme-affecting tweaks (Dark/Light) need the shell nudged or the change
    # doesn't repaint until sign-out - see Invoke-ShellThemeRefresh.
    if ($Tweak.RefreshShell) { Invoke-ShellThemeRefresh }
}

function Restart-ExplorerShell {
    <#
    .SYNOPSIS
        Cycles explorer.exe so File Explorer, the taskbar and the context
        menus rebuild against the current theme instead of the one they
        cached at sign-in. Returns $true when a live shell is running again.

    .DESCRIPTION
        THE SINGLE-INSTANCE TRAP, and why this is not just
        `Stop-Process -Name explorer -Force; Start-Process explorer`.
        Windows usually relaunches the shell by itself a moment after
        explorer.exe dies (that is what makes the desktop come back on its
        own). explorer.exe is also single-instance AS A SHELL: run it while a
        shell already owns the desktop and it does not become a second shell,
        it opens a FILE EXPLORER WINDOW. So the naive pair races - when the
        auto-restart wins, the user is left staring at a stray window of their
        Documents folder that they never asked for.

        So: kill, wait for the auto-restart, and only start a shell ourselves
        if none came back. That covers both machines - the ones that relaunch
        and the ones configured not to - and leaves no stray window on either.

        The relaunch is ANCHORED through Get-SystemBinary: this can run
        elevated, and a planted explorer.exe earlier in PATH would otherwise
        inherit that token. Same reasoning as Enable-ClassicContextMenu.
    #>
    if (Test-DryRun "Restart explorer.exe so File Explorer, the taskbar and context menus pick up the theme immediately") { return $false }

    try {
        Stop-Process -Name explorer -Force -ErrorAction Stop
    } catch {
        # No explorer running (a kiosk/alternate shell, or it already died) is
        # not a failure - there is simply nothing to cycle.
        Write-Log "ExplorerRestart: could not stop explorer.exe - $($_.Exception.Message)"
    }

    # Give Windows its own chance to bring the shell back before we do.
    # ~3s in 250ms steps: long enough for the usual auto-restart, short
    # enough that a machine which will NOT auto-restart is not left without
    # a desktop while we wait.
    $Shell = $null
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Milliseconds 250
        $Shell = Get-Process -Name explorer -ErrorAction SilentlyContinue
        if ($Shell) { break }
    }

    if (-not $Shell) {
        try {
            Start-Process -FilePath (Get-SystemBinary "explorer") -ErrorAction Stop
            Start-Sleep -Milliseconds 500
            $Shell = Get-Process -Name explorer -ErrorAction SilentlyContinue
        } catch {
            Write-Log "ExplorerRestart: relaunch failed - $($_.Exception.Message)"
        }
    }

    if ($Shell) {
        Write-Success "Windows Explorer restarted - the taskbar, File Explorer and context menus now match the new theme."
        return $true
    }
    Write-Warn "Windows Explorer did not come back automatically. Press Ctrl+Shift+Esc and run 'explorer.exe' from File > Run new task if your desktop is missing."
    return $false
}

function Invoke-ShellThemeRefresh {
    <# Applies a just-written theme change (Dark/Light) to the RUNNING shell so
       the taskbar and open surfaces repaint immediately instead of glitching
       until the next sign-in. Three steps, in order of blast radius:
         1. Broadcast WM_SETTINGCHANGE('ImmersiveColorSet') so every top-level
            window re-reads the theme. This is what updates non-shell apps,
            which an Explorer restart does NOT touch - so it stays, and it
            goes first.
         2. ie4uinit.exe -show to refresh the shell's icon/theme caches.
         3. Restart explorer.exe (v10.3). Steps 1-2 alone were the previous
            behaviour, and they left real stale surfaces behind: the taskbar
            keeps its old acrylic tint, and Explorer's ribbon/nav pane and the
            Win11 context menus stay on the theme they were built with, because
            those surfaces resolve their brushes once at shell start and ignore
            ImmersiveColorSet. Cycling the shell is the only thing that clears
            them. It costs the user their open File Explorer windows, which is
            a real cost - hence Restart-ExplorerShell's care not to ALSO leave
            a stray window behind (see its note on the single-instance trap).
       Best-effort: any step failing is logged, never fatal - worst case the
       theme still applies on next sign-in. #>
    if (Test-DryRun "Refresh the Windows shell so the theme change applies immediately (WM_SETTINGCHANGE broadcast + ie4uinit -show + explorer.exe restart)") { return }

    try {
        if (-not ([System.Management.Automation.PSTypeName]'Pulse.ShellNative').Type) {
            Add-Type -Namespace Pulse -Name ShellNative -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError=true, CharSet=System.Runtime.InteropServices.CharSet.Auto)]
public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint Msg, System.UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out System.UIntPtr lpdwResult);
'@ -ErrorAction Stop
        }
        $HWND_BROADCAST   = [System.IntPtr]0xffff
        $WM_SETTINGCHANGE = 0x001A
        $SMTO_ABORTIFHUNG = 0x0002
        $out = [System.UIntPtr]::Zero
        foreach ($section in @('ImmersiveColorSet', 'WindowsThemeElement', 'Policy')) {
            [void][Pulse.ShellNative]::SendMessageTimeout($HWND_BROADCAST, $WM_SETTINGCHANGE, [System.UIntPtr]::Zero, $section, $SMTO_ABORTIFHUNG, 200, [ref]$out)
        }
    } catch {
        Write-Log "ShellThemeRefresh: WM_SETTINGCHANGE broadcast failed - $($_.Exception.Message)"
    }

    try {
        Start-Process -FilePath (Get-SystemBinary "ie4uinit") -ArgumentList "-show" -WindowStyle Hidden -ErrorAction Stop
    } catch {
        Write-Log "ShellThemeRefresh: ie4uinit -show failed - $($_.Exception.Message)"
    }

    # Step 3 - the one that clears the cached taskbar/Explorer/context-menu
    # surfaces. Writes its own success/warning line, so this function's
    # closing line below stays about the broadcast half.
    [void](Restart-ExplorerShell)

    Write-Success "Windows shell refreshed - the theme change is visible immediately."
}

# ============================================================
#  WINDOWS 11 CLASSIC CONTEXT MENU
# ============================================================
function Enable-ClassicContextMenu {
    Write-SectionHeader "Windows 11 Classic Right-Click Menu"
    if (-not (Test-OSSupport -FeatureName "Classic Right-Click Menu" -MinBuild 22000)) { return }
    New-SystemRestorePoint

    $path = "HKCU:\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"
    $CurrentDefault = Get-RegValue -Path $path -Name "(default)"
    if ((Test-Path $path) -and ($CurrentDefault -eq "")) {
        Write-AlreadyOK "Classic context menu is already active."
        return
    }

    try {
        Set-RegValue -Path $path -Name "(default)" -Value "" -Type String
        Write-Success "Classic context menu restored."

        if (Ask-User "Restart Windows Explorer" "Applies the classic menu immediately by restarting explorer.exe.") {
            # Shared with the theme refresh (v10.3). This used to kill and
            # relaunch inline, which raced Windows' own auto-restart and could
            # leave a stray File Explorer window open on top of the desktop -
            # see Restart-ExplorerShell's note on the single-instance trap.
            [void](Restart-ExplorerShell)
        } else {
            Write-Info "Change will take effect after you sign out or restart Explorer manually."
        }
    } catch {
        Write-ErrorX "Failed to restore classic context menu: $($_.Exception.Message)"
    }
}

# ============================================================
#  SMART SYSTEM TWEAKS
# ============================================================
function Set-LiveMouseCurve {
    <#
    .SYNOPSIS
        Pushes the mouse acceleration triple into the RUNNING user session via
        SystemParametersInfo, so a pointer-precision change is felt on the very
        next mouse movement instead of at the next sign-in.

    .DESCRIPTION
        WHY THE REGISTRY IS NOT ENOUGH. HKCU:\Control Panel\Mouse is where
        Windows PERSISTS the pointer ballistics, but win32k reads that hive
        once, when the user session's input state is initialised. Writing the
        three values changed the stored setting and nothing about the live
        pointer, which is exactly the "it only applies after a reboot" report:
        the tweak was never wrong, it just was not being told to take effect.

        SPI_SETMOUSE is the one that matters. Its pvParam is an array of THREE
        ints - {xThreshold, yThreshold, acceleration} - which map to
        MouseThreshold1 / MouseThreshold2 / MouseSpeed respectively, and all
        zeroes is the documented "1:1, no ballistics" curve.

        SPI_SETMOUSESPEED is deliberately used to RE-STAMP the speed the user
        already has, read back through SPI_GETMOUSESPEED first, never to set a
        value of our own. Pointer SPEED (1-20) is a different setting from
        pointer ACCELERATION, and silently moving a user's sensitivity while
        they asked to disable acceleration would be a change they never
        requested. Re-applying the current value is still worth doing: it
        forces the ballistics table to be rebuilt, which is what makes some
        vendor mouse filter drivers honour the new curve without a re-plug.

        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE persists the change through
        Windows' own path and broadcasts WM_SETTINGCHANGE, so Settings and
        Control Panel show the new state instead of a stale cached one.

        Best-effort by contract: returns $true/$false and never throws. The
        registry write is the durable half and has already happened by the time
        this runs, so a failure here costs the user immediacy, not the tweak.
    #>
    param(
        [int]$Threshold1 = 0,
        [int]$Threshold2 = 0,
        [int]$Acceleration = 0
    )
    try {
        if (-not ([System.Management.Automation.PSTypeName]'Pulse.MouseNative').Type) {
            Add-Type -Namespace Pulse -Name MouseNative -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError=true)]
public static extern bool SystemParametersInfo(uint uiAction, uint uiParam, int[] pvParam, uint fWinIni);

[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError=true)]
public static extern bool SystemParametersInfo(uint uiAction, uint uiParam, ref int pvParam, uint fWinIni);

[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError=true)]
public static extern bool SystemParametersInfo(uint uiAction, uint uiParam, System.IntPtr pvParam, uint fWinIni);
'@ -ErrorAction Stop
        }
    } catch {
        Write-Log "LiveMouseCurve: could not load user32 SystemParametersInfo - $($_.Exception.Message)"
        return $false
    }

    $SPI_SETMOUSE      = 0x0004
    $SPI_GETMOUSESPEED = 0x0070
    $SPI_SETMOUSESPEED = 0x0071
    $SPIF_UPDATEINIFILE = 0x01
    $SPIF_SENDCHANGE    = 0x02
    $Flags = $SPIF_UPDATEINIFILE -bor $SPIF_SENDCHANGE

    $Ok = $true
    try {
        # The acceleration curve itself. Order is {x, y, accel} - NOT the
        # registry's MouseSpeed-first ordering.
        $Curve = [int[]]@($Threshold1, $Threshold2, $Acceleration)
        if (-not [Pulse.MouseNative]::SystemParametersInfo($SPI_SETMOUSE, 0, $Curve, $Flags)) {
            Write-Log "LiveMouseCurve: SPI_SETMOUSE failed (win32 error $([System.Runtime.InteropServices.Marshal]::GetLastWin32Error()))."
            $Ok = $false
        }
    } catch {
        Write-Log "LiveMouseCurve: SPI_SETMOUSE threw - $($_.Exception.Message)"
        $Ok = $false
    }

    try {
        # Read the user's CURRENT sensitivity and write the same number back -
        # see the note above on why this never invents a value.
        $Speed = 0
        if ([Pulse.MouseNative]::SystemParametersInfo($SPI_GETMOUSESPEED, 0, [ref]$Speed, 0) -and $Speed -gt 0) {
            [void][Pulse.MouseNative]::SystemParametersInfo($SPI_SETMOUSESPEED, 0, [System.IntPtr]$Speed, $Flags)
        }
    } catch {
        # Non-fatal even within the best-effort contract: the curve above is
        # what actually disables acceleration, this only nudges the driver.
        Write-Log "LiveMouseCurve: SPI_SETMOUSESPEED re-stamp skipped - $($_.Exception.Message)"
    }

    return $Ok
}

function Disable-MouseAcceleration {
    New-SystemRestorePoint
    $Path = "HKCU:\Control Panel\Mouse"
    $Speed = Get-RegValue -Path $Path -Name "MouseSpeed"
    $Thr1  = Get-RegValue -Path $Path -Name "MouseThreshold1"
    $Thr2  = Get-RegValue -Path $Path -Name "MouseThreshold2"
    if ($Speed -eq "0" -and $Thr1 -eq "0" -and $Thr2 -eq "0") {
        # The registry already says "off" - but that is a claim about what is
        # STORED, and this tweak's whole failure mode was a stored value the
        # live session had never picked up. Re-assert the curve so an
        # already-applied tweak still guarantees a 1:1 pointer right now,
        # rather than reporting success on a session that is still accelerating.
        if (-not (Test-DryRun "Re-apply the raw pointer curve to the live session (SystemParametersInfo SPI_SETMOUSE)")) {
            [void](Set-LiveMouseCurve)
        }
        Write-AlreadyOK "Mouse acceleration is already disabled."
        return
    }
    Backup-OriginalRegValue -TweakKey "MouseAccel" -Path $Path -Name "MouseSpeed"
    Backup-OriginalRegValue -TweakKey "MouseAccel" -Path $Path -Name "MouseThreshold1"
    Backup-OriginalRegValue -TweakKey "MouseAccel" -Path $Path -Name "MouseThreshold2"
    try {
        Set-RegValue -Path $Path -Name "MouseSpeed" -Value "0"
        Set-RegValue -Path $Path -Name "MouseThreshold1" -Value "0"
        Set-RegValue -Path $Path -Name "MouseThreshold2" -Value "0"
        # Live half. Runs AFTER the writes on purpose: Set-RegValue's
        # Assert-UserRegPathTargetable throws when Pulse is elevated as a
        # different account than the signed-in user, and in that case this
        # process's session is the wrong one to be reprogramming anyway.
        if (Test-DryRun "Apply the raw pointer curve to the live session (SystemParametersInfo SPI_SETMOUSE, thresholds and acceleration = 0)") {
            return
        }
        if (Set-LiveMouseCurve) {
            Write-Success "Raw pointer precision applied (mouse acceleration fully disabled, active immediately - no reboot needed)."
        } else {
            # The durable half succeeded, so this is not a task failure - but
            # it must not claim immediacy it did not deliver.
            Write-Warn "Mouse acceleration disabled in the registry, but the live session could not be updated - it will take effect at your next sign-in."
        }
    } catch {
        # A real failure (registry keys restricted by policy) - Write-ErrorX,
        # not Write-Warn, so Complete-GuiTask's fail counter (30-GuiDispatcher.ps1)
        # actually reflects it instead of reporting "Mouse acceleration disabled"
        # to the GUI when it wasn't.
        Write-ErrorX "Could not disable mouse acceleration: $($_.Exception.Message)"
    }
}

function Enable-MinimalistTaskbar {
    if (-not (Test-OSSupport -FeatureName "Windows 11 Minimalist Taskbar" -MinBuild 22000)) { return }
    New-SystemRestorePoint
    $Path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
    if ((Get-RegValue -Path $Path -Name "TaskbarAl") -eq 0 -and (Get-RegValue -Path $Path -Name "TaskbarDa") -eq 0) {
        Write-AlreadyOK "Minimalist taskbar layout is already applied."
        return
    }
    Backup-OriginalRegValue -TweakKey "Taskbar" -Path $Path -Name "TaskbarAl"
    Backup-OriginalRegValue -TweakKey "Taskbar" -Path $Path -Name "TaskbarDa"
    Backup-OriginalRegValue -TweakKey "Taskbar" -Path $Path -Name "TaskbarMn"
    try {
        Set-RegValue -Path $Path -Name "TaskbarAl" -Value 0
        Set-RegValue -Path $Path -Name "TaskbarDa" -Value 0
        Set-RegValue -Path $Path -Name "TaskbarMn" -Value 0
        Write-Success "Taskbar alignments updated."
    } catch {
        # Real failure, not an informational skip - see the same note on
        # Disable-MouseAcceleration above.
        Write-ErrorX "Could not update taskbar layout: $($_.Exception.Message)"
    }
}

# ============================================================
#  ONEDRIVE REMOVAL / RESTORE
# ============================================================
function Test-OneDriveInstalled {
    <# Explicit pre-flight state check, shared by Remove-OneDrivePackage and
       whatever wants to know up front - true if either the per-user
       install folder or a live OneDrive.exe process is present. #>
    $ODInstallFolder = "$env:LOCALAPPDATA\Microsoft\OneDrive"
    if (Test-Path $ODInstallFolder) { return $true }
    if (Get-Process -Name "OneDrive" -ErrorAction SilentlyContinue) { return $true }
    return $false
}

function Get-OneDriveUserSetupPath {
    <# The uninstaller OneDrive ships INTO THE USER PROFILE, newest first,
       or $null.

       %LOCALAPPDATA%\Microsoft\OneDrive\<version>\OneDriveSetup.exe. It is
       split out of Get-OneDriveSetupPath rather than inlined there because
       the two halves answer different questions - "what did Windows ship?"
       and "what did the client install for itself?" - and because this half
       reads exactly one environment variable, which makes it the half that
       can actually be tested. Faking %SystemRoot% to reach it through the
       composed function is not possible: PowerShell resolves the CLR
       through that variable and refuses to start without a real one.

       Version folders are compared as [version], not as text, so
       "24.201.1005.0004" beats "9.9.9.9" - the same trap
       Get-EdgeUninstallerPath documents. A stray OneDriveSetup.exe sitting
       directly in the install root (some builds leave one there) is taken
       last, after every versioned payload. #>
    if (-not $env:LOCALAPPDATA) { return $null }
    $UserRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\OneDrive'
    if (-not (Test-Path -LiteralPath $UserRoot)) { return $null }

    $Versioned = @(Get-ChildItem -LiteralPath $UserRoot -Directory -ErrorAction SilentlyContinue |
        ForEach-Object {
            $Parsed = [version]"0.0.0.0"
            [void][version]::TryParse($_.Name, [ref]$Parsed)
            [PSCustomObject]@{ Dir = $_; Version = $Parsed }
        } | Sort-Object Version -Descending)
    foreach ($Entry in $Versioned) {
        $Path = Join-Path $Entry.Dir.FullName 'OneDriveSetup.exe'
        if (Test-Path -LiteralPath $Path -PathType Leaf) { return $Path }
    }
    $RootStub = Join-Path $UserRoot 'OneDriveSetup.exe'
    if (Test-Path -LiteralPath $RootStub -PathType Leaf) { return $RootStub }
    return $null
}

function Get-OneDriveSetupPath {
    <# OneDriveSetup.exe, wherever this machine keeps it.

       THREE homes, in order of how authoritative each one is.

       The two SYSTEM stubs come first. The 32-bit one lives in SysWOW64 on
       a 64-bit Windows, but a 64-bit OneDrive install (now the default on
       current builds) and every 32-bit Windows put it in System32 instead
       - and this used to look ONLY in SysWOW64, so on those machines the
       purge fell straight through to "OneDrive standalone installer
       payload not found" and reported Failed without ever attempting the
       uninstall.

       The PER-USER copy is the third (Get-OneDriveUserSetupPath), and it
       is the one that matters on a machine where OneDrive updated itself
       past the inbox stub: on a Windows build that never carried a system
       stub at all - or one where a previous partial removal deleted it -
       that copy is the ONLY uninstaller present. Without it the purge
       reported Failed on exactly the machines whose OneDrive was most
       current. #>
    $Candidates = @(
        (Join-Path $env:SystemRoot 'SysWOW64\OneDriveSetup.exe'),
        (Join-Path $env:SystemRoot 'System32\OneDriveSetup.exe')
    )
    foreach ($Path in $Candidates) {
        if (Test-Path -LiteralPath $Path -PathType Leaf) { return $Path }
    }

    return (Get-OneDriveUserSetupPath)
}

function Stop-OneDriveProcesses {
    <# OneDrive.exe is not the only thing holding the install open.
       FileCoAuth.exe (the Office co-authoring broker) and FileSyncHelper
       load out of the same per-user folder, and either one still running
       makes the uninstaller leave the directory behind. #>
    foreach ($Name in @("OneDrive", "OneDriveSetup", "FileCoAuth", "FileSyncHelper")) {
        Invoke-Mutation -Description "Terminate $Name.exe" -Action {
            Get-Process -Name $Name -ErrorAction SilentlyContinue |
                Stop-Process -Force -ErrorAction SilentlyContinue
        } | Out-Null
    }
    if (-not $Script:DryRun) { Start-Sleep -Milliseconds 800 }
}

function Stop-OneDriveServices {
    <# OneDrive's own updater service only.

       DELIBERATELY NOT OneSyncSvc: despite the name that is Windows' Sync
       Host, which also carries Mail, Calendar, People and contacts sync.
       Disabling it to remove OneDrive would break unrelated first-party
       apps for a user who asked about a file-sync client - a side effect
       they would never connect back to this action. #>
    foreach ($Svc in @("OneDrive Updater Service")) {
        $Service = Get-Service -Name $Svc -ErrorAction SilentlyContinue
        if (-not $Service) { continue }
        Invoke-Mutation -Description "Stop and disable the '$Svc' service" -Action {
            Stop-Service -Name $Svc -Force -ErrorAction SilentlyContinue
            Set-Service -Name $Svc -StartupType Disabled -ErrorAction SilentlyContinue
        } | Out-Null
    }
}

function Clear-OneDriveStartupEntries {
    <# The Run keys that relaunch OneDrive (or re-run its setup stub) at the
       next sign-in. Left behind, the uninstall looks like it worked until
       the user reboots and OneDrive is back. #>
    $Targets = @(
        @{ Path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"; Name = "OneDrive" },
        @{ Path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"; Name = "OneDriveSetup" },
        @{ Path = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; Name = "OneDrive" }
    )
    foreach ($Target in $Targets) {
        if ($null -eq (Get-RegValue -Path $Target.Path -Name $Target.Name)) { continue }
        try {
            Remove-RegValue -Path $Target.Path -Name $Target.Name
            Write-Info "Cleared startup entry '$($Target.Name)'."
        } catch {
            Write-Warn "Could not clear startup entry '$($Target.Name)': $($_.Exception.Message)"
        }
    }
}

#: OneDriveSetup.exe exit codes that mean "there was nothing here to
#: uninstall", not "the uninstall failed".
#:
#: 0x8004069B (-2147219813) is the one this table exists for. It is what
#: the setup stub returns when it is asked to uninstall a build that is
#: not registered for this user - a machine where OneDrive was removed by
#: hand, removed by a previous Pulse run, or never provisioned past the
#: inbox stub in the first place. The stub itself is still sitting in
#: System32 (Windows ships it there regardless), so the purge found an
#: uninstaller, ran it, got a non-zero code and reported a hard failure
#: for a machine that was already in the state the user asked for.
#:
#: That is the worst kind of wrong answer: the operation SUCCEEDED by any
#: definition the user cares about, and Pulse said it failed.
$Script:OneDriveAlreadyGoneCodes = @(
    -2147219813,   # 0x8004069B - not installed for this user
    -2147219814,   # 0x8004069A - no such product registration
    1605           # ERROR_UNKNOWN_PRODUCT, the MSI spelling of the same
)

function Clear-OneDriveRegistryStubs {
    <# The per-user keys OneDrive leaves behind, which its own uninstaller
       does not take with it.

       HKCU\Software\Microsoft\OneDrive is the account/telemetry hive: sync
       endpoints, the tenant id, the last-signed-in account, the update
       ring. A machine that has "removed OneDrive" and still carries it is
       one Windows feature update away from being re-onboarded from its own
       leftovers, and in the meantime the data is simply still there.

       The two Explorer namespace keys are what put the OneDrive entry in
       the navigation pane. They are the visible half: a sidebar still
       offering a cloud folder that no longer syncs is the thing users
       report as "it did not actually uninstall".

       Best-effort and individually guarded - a policy-locked key must not
       abort a removal that has already succeeded. #>
    $Keys = @(
        "HKCU:\Software\Microsoft\OneDrive",
        "HKCU:\Software\Classes\CLSID\{018D5C66-4533-4307-9B53-224DE2ED1FE6}",
        "HKCU:\Software\Classes\WOW6432Node\CLSID\{018D5C66-4533-4307-9B53-224DE2ED1FE6}"
    )
    foreach ($Key in $Keys) {
        if (-not (Test-Path -LiteralPath $Key)) { continue }
        if (Test-DryRun "Remove leftover registry key '$Key'") { continue }
        try {
            Remove-Item -LiteralPath $Key -Recurse -Force -ErrorAction Stop
            Write-Info "Removed leftover registry key '$Key'."
        } catch {
            Write-Warn "Could not remove '$Key': $($_.Exception.Message)"
        }
    }
}

function Remove-EmptyOneDriveFolders {
    <# Deletes the OneDrive install and sync folders ONLY WHEN THEY ARE
       EMPTY.

       THE EMPTINESS TEST IS THE WHOLE SAFETY PROPERTY, and it is why this
       is a separate function with its own name rather than three lines
       inside the purge. A sync root can hold files that exist NOWHERE ELSE
       - anything the user created locally and that never finished
       uploading, plus every file in a folder that was never selected for
       sync on another device. Deleting a non-empty one to tidy up an
       uninstall would be the most destructive thing this application
       could do, and it would look like housekeeping in the diff.

       So: recurse, count anything at all, and stop at the first file
       found. An empty tree is the leftover scaffolding of a client that
       has already handed its contents back (Windows relocates them to the
       profile on unlink); a non-empty one is the user's data and is left
       exactly where it is, with a line in the log saying so. #>
    $Candidates = New-Object System.Collections.ArrayList
    [void]$Candidates.Add((Join-Path $env:LOCALAPPDATA 'Microsoft\OneDrive'))
    foreach ($Root in @(Get-OneDriveSyncRoots)) { [void]$Candidates.Add($Root) }

    foreach ($Path in $Candidates) {
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) { continue }
        $Contents = @(Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue)
        if ($Contents.Count -gt 0) {
            Write-Info "Left '$Path' in place - it still contains $($Contents.Count) file(s)."
            continue
        }
        if (Test-DryRun "Remove the now-empty folder '$Path'") { continue }
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            Write-Info "Removed the empty folder '$Path'."
        } catch {
            Write-Warn "Could not remove '$Path': $($_.Exception.Message)"
        }
    }
}

function Complete-OneDriveRemoval {
    <# The cleanup every successful path shares: startup entries, registry
       stubs, and empty folders. Factored out because "already gone" and
       "just uninstalled" need exactly the same tidy-up, and running it in
       one branch only is how a machine ends up half-cleaned. #>
    Clear-OneDriveStartupEntries
    Clear-OneDriveRegistryStubs
    Remove-EmptyOneDriveFolders
}

function Remove-OneDrivePackage {
    <#
    .SYNOPSIS
        Removes OneDrive after an explicit pre-flight state check - callers
        get a hashtable @{Status; Message} back (Status is one of
        AlreadyRemoved / DryRun / Success / Failed) so the GUI dispatcher
        can show the right verdict instead of a generic "removed" message
        even when nothing needed doing.

    .DESCRIPTION
        THE MISSING-UNINSTALLER AND ALREADY-GONE CASES ARE SUCCESS STATES,
        not failures, and treating them as failures was the defect this
        function was rewritten around. Both were reported as hard errors:

          * no OneDriveSetup.exe anywhere -> "Failed: payload not found",
            on a machine whose OneDrive had already been removed;
          * the stub present but the product not registered -> the
            uninstaller returns 0x8004069B (-2147219813) and Pulse
            reported the raw exit code, again on a machine already in the
            state the user asked for.

        In both cases the user's goal - no OneDrive - is already met, and
        there is still real work to do: the registry stubs and the empty
        folders outlive the client and are what make a "removed" OneDrive
        look half-removed. So both now run the same cleanup as a live
        uninstall and report AlreadyRemoved.
    #>
    Write-SectionHeader "Purge Microsoft OneDrive"

    if (-not (Test-OneDriveInstalled)) {
        Write-AlreadyOK "OneDrive is already removed from this system."
        # NOT a bare return: a machine can pass Test-OneDriveInstalled and
        # still be carrying the account hive and a dead Explorer entry.
        Complete-OneDriveRemoval
        return @{ Status = 'AlreadyRemoved'; Message = 'OneDrive was already removed; leftover registry entries and empty folders were cleaned up.' }
    }

    New-SystemRestorePoint
    $ODSetup = Get-OneDriveSetupPath

    if (-not (Backup-OneDriveFiles)) {
        Write-ErrorX "Aborting OneDrive removal: the backup did not complete successfully. Resolve the issue above and try again."
        return @{ Status = 'Failed'; Message = 'OneDrive removal was aborted because the pre-removal backup did not complete successfully.' }
    }
    try {
        Stop-OneDriveProcesses
        Stop-OneDriveServices

        if (-not $ODSetup) {
            # No uninstaller ANYWHERE - including the per-user copy. There
            # is nothing left to run, which means there is nothing left to
            # uninstall; the remaining traces are ours to clear.
            if (Test-DryRun "Clean up OneDrive registry stubs and empty folders (no uninstaller present)") {
                return @{ Status = 'DryRun'; Message = '[DRY-RUN] OneDrive cleanup simulated (no uninstaller is present on this machine).' }
            }
            Write-AlreadyOK "No OneDrive uninstaller is present - the client is already gone."
            Complete-OneDriveRemoval
            return @{ Status = 'AlreadyRemoved'; Message = 'OneDrive''s uninstaller was not present, so the client was already gone; leftover registry entries and empty folders were cleaned up.' }
        }

        if (Test-DryRun "Run OneDriveSetup.exe /uninstall, then clear its registry stubs and empty folders") {
            return @{ Status = 'DryRun'; Message = '[DRY-RUN] OneDrive removal simulated (backup + uninstall were reported, not executed).' }
        }
        # -PassThru + exit-code check: without it, Write-Success fired
        # unconditionally regardless of whether the uninstaller actually
        # succeeded (Start-Process doesn't throw on a non-zero exit code).
        $Proc = Start-Process $ODSetup -ArgumentList "/uninstall" -Wait -NoNewWindow -PassThru
        $Code = $Proc.ExitCode

        if ($Code -eq 0) {
            # AFTER the uninstaller, not before: it rewrites its own Run
            # entry as part of shutting down, so clearing these first
            # just means clearing them twice and missing the one that
            # matters.
            Complete-OneDriveRemoval
            Write-Success "OneDrive uninstall sequence executed."
            return @{ Status = 'Success'; Message = "OneDrive removed. Local files were backed up to $Script:OneDriveBackupFolder first." }
        }
        if ($Script:OneDriveAlreadyGoneCodes -contains $Code) {
            Write-AlreadyOK "OneDrive's uninstaller reported it was not installed for this user (code $Code) - nothing to remove."
            Complete-OneDriveRemoval
            return @{ Status = 'AlreadyRemoved'; Message = "OneDrive was not registered for this user, so there was nothing to uninstall; leftover registry entries and empty folders were cleaned up." }
        }
        Write-ErrorX "OneDrive's uninstaller exited with code $Code."
        return @{ Status = 'Failed'; Message = "OneDrive's uninstaller exited with code $Code." }
    } catch {
        Write-ErrorX "OneDrive removal failed: $($_.Exception.Message)"
        return @{ Status = 'Failed'; Message = "OneDrive removal failed: $($_.Exception.Message)" }
    }
}

function Restore-OneDrivePackage {
    Write-SectionHeader "Restore Microsoft OneDrive"
    if (Ensure-Winget) {
        Write-Info "Reinstalling Microsoft OneDrive via winget..."
        $Result = Smart-Deploy "Microsoft.OneDrive" "Microsoft OneDrive"
        if ($Result.Status -eq 'Success' -and (Test-Path $Script:OneDriveBackupFolder)) {
            Write-Info "Your pre-removal files are still backed up at $Script:OneDriveBackupFolder - copy them back into your OneDrive folder once it finishes syncing."
        }
    } elseif ($Script:DryRun) {
        Write-Info "[WHATIF] Would reinstall Microsoft OneDrive via winget."
    } else {
        Write-Warn "Winget unavailable. Opening official download page for a manual install..."
        Open-UrlSafe -Url "https://www.microsoft.com/en-us/microsoft-365/onedrive/download"
    }
}

# ============================================================
#  MICROSOFT EDGE REMOVAL / REINSTALL
# ============================================================
function Get-EdgeUninstallRegistryKeys {
    <# Every hive/bitness combination Edge's Uninstall entry can land under -
       shared by Test-MicrosoftEdgeInstalled and Clear-EdgeNoRemoveFlags so
       both check exactly the same set. #>
    @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Microsoft Edge"
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Microsoft Edge"
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Microsoft Edge"
    )
}

function Test-MicrosoftEdgeInstalled {
    <# Explicit pre-flight state check - Edge counts as "present" if either
       its binary (either Program Files bitness) or its Uninstall registry
       entry (either hive/bitness) still exists, so a stale leftover of
       just one still routes through the real removal path instead of
       silently no-oping, while a machine where NONE of them exist (truly
       already removed) short-circuits instead of re-running the whole
       force-purge sequence for nothing. #>
    $BinaryPaths = @(
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
    )
    foreach ($Path in $BinaryPaths) {
        if (Test-Path $Path) { return $true }
    }
    foreach ($Key in (Get-EdgeUninstallRegistryKeys)) {
        if (Test-Path $Key) { return $true }
    }
    return $false
}

function Clear-EdgeNoRemoveFlags {
    <# Best-effort: Windows/Edge can set a NoRemove=1 flag on the Uninstall
       registry key, which hides/disables the Control Panel uninstall
       button. It doesn't block setup.exe directly, but forcefully clearing
       it up front removes one more thing standing between "Windows thinks
       this is protected" and a clean uninstall. Failures here are logged
       and swallowed - this is a defensive extra step, not the primary
       removal mechanism, so it never aborts the overall purge. #>
    foreach ($Key in (Get-EdgeUninstallRegistryKeys)) {
        if (-not (Test-Path $Key)) { continue }
        $Current = Get-RegValue -Path $Key -Name "NoRemove"
        if ($null -eq $Current -or "$Current" -eq "0") { continue }
        try {
            Set-RegValue -Path $Key -Name "NoRemove" -Value 0 -Type DWord
            Write-Info "Cleared NoRemove protection flag on '$Key'."
        } catch {
            Write-Warn "Could not clear NoRemove flag on '$Key': $($_.Exception.Message)"
        }
    }
}

function Disable-EdgeDefaultBrowserPrompt {
    <# Stop Edge nagging to be the default browser.

       HKLM\SOFTWARE\Policies\Microsoft\Edge!DefaultBrowserSettingEnabled=0
       is Edge's own documented policy for this. It is set as part of the
       purge because a removal that Windows later reverses (Edge is an
       inbox component on many builds and comes back with a feature update)
       otherwise returns WITH the prompt, which is the thing users actually
       notice. Machine-scope HKLM, so it needs the elevation RemoveEdge
       already requires.

       Best-effort: a managed device can have this key locked by real Group
       Policy, and failing the whole purge over a nag-screen preference
       would be the wrong trade. #>
    $PolicyKey = "HKLM:\SOFTWARE\Policies\Microsoft\Edge"
    try {
        Set-RegValue -Path $PolicyKey -Name "DefaultBrowserSettingEnabled" -Value 0 -Type DWord
        # Set-RegValue returns cleanly in dry-run WITHOUT writing (it logs its
        # own [WHATIF] line), so an unconditional Write-Success here would
        # claim a change that did not happen AND bump the session success
        # counter that Complete-GuiTask reads. Announce only a real write.
        if (-not $Script:DryRun) {
            Write-Success "Edge's 'make me the default browser' prompt disabled by policy."
        }
        return $true
    } catch {
        Write-Warn "Could not set the Edge default-browser policy: $($_.Exception.Message)"
        return $false
    }
}

function Stop-EdgeUpdateServices {
    <# EdgeUpdate ships TWO services - 'edgeupdate' (the on-demand core)
       and 'edgeupdatem' (the per-machine maintenance sibling) - and either
       one left running and set to Automatic is enough to pull the browser
       back down the next time it wakes. Killing MicrosoftEdgeUpdate.exe
       only closes the CURRENT process; the SCM restarts it on the service's
       own trigger, which is why a purge that stopped at the process kill
       could reverse itself hours later with nothing in the log to explain
       it.

       Stopped AND disabled, for the same reason Clear-EdgeNoRemoveFlags
       clears NoRemove up front: a stopped-but-Automatic service is one
       reboot away from being a running service again.

       Best-effort throughout. A machine with neither service present is
       the ordinary outcome once the payload is gone, not a failure, and a
       policy-locked SCM refusing the change must never abort the purge
       that is already under way. #>
    foreach ($Name in @("edgeupdate", "edgeupdatem")) {
        $Service = Get-Service -Name $Name -ErrorAction SilentlyContinue
        if (-not $Service) { continue }
        Invoke-Mutation -Description "Stop and disable the '$Name' service" -Action {
            try {
                Stop-Service -Name $Name -Force -ErrorAction SilentlyContinue
                Set-Service -Name $Name -StartupType Disabled -ErrorAction Stop
                Write-Info "Stopped and disabled the '$Name' service."
            } catch {
                Write-Warn "Could not disable the '$Name' service: $($_.Exception.Message)"
            }
        } | Out-Null
    }
}

function Remove-EdgeScheduledTasks {
    <# Last-mile cleanup: the Edge/EdgeUpdate scheduled tasks keep
       reinstalling or re-registering Edge components in the background
       even after the browser payload itself is gone. Best-effort - a
       machine with none of these left is the success case, not a failure.

       BOTH task families, not just one. "MicrosoftEdgeUpdate*" catches the
       updater's own Core/UA pair; "MicrosoftEdge*" catches the browser
       stubs Windows registers beside them (the update-broker and
       PWA-refresh entries), which survived every earlier pass and are the
       stub tasks that put Edge back. #>
    try {
        $Tasks = @(Get-ScheduledTask -TaskName "MicrosoftEdge*" -ErrorAction SilentlyContinue)
        foreach ($Task in $Tasks) {
            try {
                Unregister-ScheduledTask -TaskName $Task.TaskName -TaskPath $Task.TaskPath -Confirm:$false -ErrorAction Stop
                Write-Info "Removed leftover scheduled task '$($Task.TaskName)'."
            } catch {
                Write-Warn "Could not remove scheduled task '$($Task.TaskName)': $($_.Exception.Message)"
            }
        }
    } catch {
        # Get-ScheduledTask itself can throw on a locked-down Task Scheduler
        # service - never let that abort the rest of the purge.
    }
}

function Get-EdgeUninstallerPath {
    <#
    .SYNOPSIS
        Edge's own setup.exe, newest version first, or $null.

    .DESCRIPTION
        setup.exe's location is DYNAMIC: it lives under a per-version folder
        ("...\Edge\Application\<VERSION>\Installer\setup.exe") whose name
        changes with every Edge update, so a hard-coded path is stale the
        moment Edge patches itself - the original cause of setup.exe never
        being invoked, or of a stale copy exiting with code 93. It is
        resolved at run time instead, under BOTH Program Files roots:
        64-bit Edge normally lands in Program Files, but the Installer
        payload some builds ship still sits under Program Files (x86), which
        is the layout the brief names.

        ORDERED BY VERSION, NOT BY PATH STRING, and that distinction is the
        whole reason this is a function rather than a Sort-Object in-line.
        Edge version folders are dotted quads ("141.0.3537.85"), and sorting
        those as TEXT descending puts "99.0.4844.51" above "141.0.3537.85" -
        so a machine that had ever run a 9x build kept a leftover folder
        that won the sort, and the purge drove a years-old uninstaller
        against a current install. Parsing each folder name as [version]
        makes the newest payload win by construction. A folder whose name is
        not a version (Edge does ship non-version siblings next to them)
        sorts last rather than throwing.

        Returns the FileInfo, so the caller keeps .FullName for logging.
    #>
    $EdgeAppRoots = @(
        "$env:ProgramFiles\Microsoft\Edge\Application"
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application"
    )
    $Candidates = New-Object System.Collections.ArrayList
    foreach ($Root in $EdgeAppRoots) {
        if (-not (Test-Path -LiteralPath $Root)) { continue }
        foreach ($Found in @(Get-ChildItem -Path $Root -Filter "setup.exe" -Recurse -File -ErrorAction SilentlyContinue)) {
            # ...\Application\<VERSION>\Installer\setup.exe - the version is
            # the grandparent of the file, i.e. the parent of "Installer".
            $VersionDir = Split-Path (Split-Path $Found.FullName -Parent) -Leaf
            $Parsed = [version]"0.0.0.0"
            [void][version]::TryParse($VersionDir, [ref]$Parsed)
            [void]$Candidates.Add([PSCustomObject]@{ File = $Found; Version = $Parsed })
        }
    }
    if ($Candidates.Count -eq 0) { return $null }
    return ($Candidates | Sort-Object Version -Descending | Select-Object -First 1).File
}

#: setup.exe exit codes that mean "Windows refused", not "it broke".
#:
#: 93 is the one that made the force-purge look like it did nothing. Edge's
#: installer returns it for UNINSTALL_NOT_ALLOWED: the payload is fine, the
#: command line is fine, and the product simply declines to remove itself
#: because this build treats Edge as a non-removable system component.
#: Retrying it - which is what Invoke-WithRetry did - reproduces it exactly,
#: forever.
#:
#: 1603 is winget's spelling of the same wall (ERROR_INSTALL_FAILURE from
#: the MSI layer, which is what winget reports when the Edge bundle refuses
#: the uninstall). Both are BLOCKS, and a block is escalated rather than
#: retried.
$Script:EdgeUninstallBlockedCodes = @(93, 1603)

#: The EEA/DMA member-state GeoID used while asking Edge to uninstall.
#: 68 is Ireland. Any EEA nation works; the number itself carries no
#: meaning beyond membership.
$Script:EdgeDmaGeoId = 68

function Set-EdgeUninstallPolicy {
    <# EdgeUpdate's own documented switch for "the Uninstall button is
       allowed to exist".

       Microsoft publishes this as an EdgeUpdate policy, and on a machine
       where Edge was installed by a channel that sets it to 0 the
       uninstaller refuses before it starts. Writing it is therefore not a
       trick - it is the supported way to ask for what this task exists to
       do - and it is the first thing to try when setup.exe answers 93.

       Returns a restore token: the previous values, so the caller can put
       the machine back exactly as it found it. Best-effort; a locked key
       yields $null for that path and the caller carries on. #>
    $Paths = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate"
    )
    $Previous = @{}
    foreach ($Path in $Paths) {
        $Previous[$Path] = Get-RegValue -Path $Path -Name "AllowUninstall"
        try {
            Set-RegValue -Path $Path -Name "AllowUninstall" -Value 1 -Type DWord
        } catch {
            Write-Warn "Could not set AllowUninstall on '$Path': $($_.Exception.Message)"
        }
    }
    return $Previous
}

function Restore-EdgeUninstallPolicy {
    <# Puts AllowUninstall back to whatever it was, including removing it
       again where it did not exist. The purge is allowed to change this
       machine's Edge policy for the duration of the purge; it is not
       allowed to leave it changed. #>
    param([hashtable]$Previous)
    if (-not $Previous) { return }
    foreach ($Path in $Previous.Keys) {
        $Value = $Previous[$Path]
        try {
            if ($null -eq $Value) {
                Remove-RegValue -Path $Path -Name "AllowUninstall"
            } else {
                Set-RegValue -Path $Path -Name "AllowUninstall" -Value ([int]$Value) -Type DWord
            }
        } catch {
            Write-Warn "Could not restore AllowUninstall on '$Path': $($_.Exception.Message)"
        }
    }
}

function Invoke-EdgeSetupUninstall {
    <# One attempt at Edge's own uninstaller. Returns the exit code, or
       $null when the process could not be started at all.

       Deliberately NOT wrapped in Invoke-WithRetry. That helper exists for
       operations that can succeed on a second try - a locked file, a busy
       service - and Edge's refusal is not one of them: a build that
       answers 93 answers 93 every time, so retrying it just spends the
       user's time reproducing the same block. The caller escalates
       instead. #>
    param([Parameter(Mandatory = $true)][string]$SetupPath)
    try {
        $Proc = Start-Process -FilePath $SetupPath `
            -ArgumentList "--uninstall --system-level --verbose-logging --force-uninstall" `
            -Wait -NoNewWindow -PassThru -ErrorAction Stop
        return $Proc.ExitCode
    } catch {
        Write-Warn "Edge's uninstaller could not be started: $($_.Exception.Message)"
        return $null
    }
}

function Invoke-EdgeUninstallUnderDmaRegion {
    <# Re-runs Edge's uninstaller with the machine reporting an EEA region,
       then puts the region back.

       WHY THIS EXISTS. Under the Digital Markets Act, Microsoft ships a
       build of Edge that CAN be uninstalled - and gates that behaviour on
       the user's reported region. Outside the EEA the same binary answers
       93 and stops. So on a blocked machine the difference between "Edge
       cannot be removed" and "Edge removes cleanly" is one integer in
       HKCU\Control Panel\International\Geo\Nation.

       THE REGION IS RESTORED IN A `finally`, unconditionally. GeoID is not
       ours: it feeds regional defaults well outside this app, and a
       utility that quietly moved a user to Ireland to win an argument with
       a browser would be doing something the user could never trace back.
       It is changed for the seconds the uninstaller runs, it is announced
       in the log, and it goes back even if the uninstaller throws.

       Returns the exit code, or $null if the region could not be read or
       set - in which case nothing was changed and the caller falls through
       to the next tier. #>
    param([Parameter(Mandatory = $true)][string]$SetupPath)

    $GeoPath = "HKCU:\Control Panel\International\Geo"
    $Original = Get-RegValue -Path $GeoPath -Name "Nation"
    if ($null -eq $Original) {
        Write-Info "Could not read this machine's region - skipping the DMA uninstall path."
        return $null
    }

    Write-Info "Edge refused the uninstall on this build. Retrying under an EEA region (the DMA-compliant path), then restoring region '$Original'."
    try {
        Set-RegValue -Path $GeoPath -Name "Nation" -Value ([string]$Script:EdgeDmaGeoId) -Type String
    } catch {
        Write-Warn "Could not set the region for the DMA uninstall path: $($_.Exception.Message)"
        return $null
    }
    try {
        return (Invoke-EdgeSetupUninstall -SetupPath $SetupPath)
    } finally {
        try {
            Set-RegValue -Path $GeoPath -Name "Nation" -Value ([string]$Original) -Type String
            Write-Info "Region restored to '$Original'."
        } catch {
            Write-ErrorX "COULD NOT RESTORE THE REGION to '$Original'. Set Settings > Time & language > Region > Country or region back by hand."
        }
    }
}

function Remove-EdgeAppxRegistrations {
    <# Forceful package deregistration: the installed Appx packages AND the
       provisioned ones.

       Two different things, and removing only the first is why Edge came
       back. Remove-AppxPackage unregisters it for the users who have it;
       Remove-AppxProvisionedPackage takes it out of the IMAGE, which is
       what stops Windows re-installing it for the next user to sign in and
       after the next feature update.

       Microsoft.MicrosoftEdgeDevToolsClient is deliberately EXCLUDED: on
       Windows 11 it is a hard-protected OS component and Remove-AppxPackage
       always fails it with 0x80070032 (ERROR_NOT_SUPPORTED). Left in the
       pipeline it throws mid-loop, aborting the removal of the stubs that
       ARE removable and turning a real success into a false failure - so we
       filter it out up front rather than fighting a block Windows will
       never lift.

       Returns $true if anything was actually removed. Finding nothing is
       the ordinary outcome on a clean machine and is NOT a failure. #>
    $Cleared = $false
    try {
        $Packages = @(Get-AppxPackage -AllUsers -Name "*MicrosoftEdge*" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notlike "*MicrosoftEdgeDevToolsClient*" })
        foreach ($Package in $Packages) {
            # Per-package, so one OS-protected stub cannot abort the
            # removal of the others.
            try {
                Remove-AppxPackage -Package $Package.PackageFullName -AllUsers -ErrorAction Stop
                Write-Info "Unregistered Edge Appx package '$($Package.Name)'."
                $Cleared = $true
            } catch {
                Write-Warn "Could not unregister '$($Package.Name)': $($_.Exception.Message)"
            }
        }
        if ($Packages.Count -eq 0) {
            Write-Info "No removable Edge Appx registration present (DevToolsClient is OS-protected and skipped)."
        }
    } catch {
        Write-Warn "Edge Appx cleanup could not run: $($_.Exception.Message)"
    }

    # The provisioned copy - the one that reinstalls itself for a new user.
    try {
        $Provisioned = @(Get-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like "*MicrosoftEdge*" -and
                           $_.DisplayName -notlike "*DevToolsClient*" })
        foreach ($Entry in $Provisioned) {
            try {
                Remove-AppxProvisionedPackage -Online -PackageName $Entry.PackageName -ErrorAction Stop | Out-Null
                Write-Info "Deprovisioned '$($Entry.DisplayName)' so it cannot return for a new user."
                $Cleared = $true
            } catch {
                Write-Warn "Could not deprovision '$($Entry.DisplayName)': $($_.Exception.Message)"
            }
        }
    } catch {
        # Get-AppxProvisionedPackage needs elevation and a serviceable
        # image; neither is worth failing an otherwise clean purge over.
        Write-Warn "Edge deprovisioning could not run: $($_.Exception.Message)"
    }
    return $Cleared
}

function Remove-MicrosoftEdge {
    <#
    .SYNOPSIS
        Explicit pre-flight state check, then an aggressive multi-tier
        force-purge: kill every locking/identity process, stop and disable
        the two EdgeUpdate services, forcefully clear the NoRemove registry
        protection flag, run Edge's own setup.exe with --force-uninstall,
        fall back to a winget uninstall, then a final Appx + EdgeUpdate
        scheduled-task cleanup pass - each tier only runs if
        the one before it wasn't available or failed, and each is a real
        removal attempt in its own right rather than a last-resort no-op.
        Returns a hashtable @{Status; Message} (Status is one of
        AlreadyRemoved / DryRun / Success / Failed) so the GUI dispatcher
        can show the right verdict instead of re-deriving it from a second,
        separate filesystem probe.
    #>
    Write-SectionHeader "Remove Microsoft Edge"

    if (-not (Test-MicrosoftEdgeInstalled)) {
        Write-AlreadyOK "Microsoft Edge is already removed from this system."
        return @{ Status = 'AlreadyRemoved'; Message = 'Microsoft Edge is already removed from this system.' }
    }

    New-SystemRestorePoint
    Backup-EdgeState

    if (Test-DryRun "Force-purge Microsoft Edge (kill processes, stop and disable the edgeupdate/edgeupdatem services, clear NoRemove flags, setup.exe --uninstall --system-level --verbose-logging --force-uninstall, falling back to winget/Appx/scheduled-task cleanup if needed)") {
        return @{ Status = 'DryRun'; Message = '[DRY-RUN] Edge removal simulated (backup + uninstall were reported, not executed).' }
    }

    # msedge.exe/msedgewebview2.exe/identity_helper.exe hold their own
    # binaries open - every removal path below fails or silently no-ops if
    # any of them is still running. MicrosoftEdgeUpdate is in the list for a
    # different reason: it is the updater, and left alive it can reinstall
    # what the purge below removes, so a "successful" removal reverses
    # itself minutes later.
    Get-Process -Name "msedge", "msedgewebview2", "identity_helper", "MicrosoftEdgeUpdate" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800

    # BEFORE the removal tiers, not after: the process kill above closes
    # only the running updater, and the SCM restarts it on its own trigger
    # while setup.exe is still working. Disabling the two services first is
    # what stops the purge racing the thing that undoes it.
    Stop-EdgeUpdateServices

    Clear-EdgeNoRemoveFlags
    Disable-EdgeDefaultBrowserPrompt | Out-Null

    $Removed = $false

    $UninstallPath = Get-EdgeUninstallerPath

    # TIER 1: Edge's own uninstaller, escalating rather than retrying.
    #
    # Three attempts at most, and each one changes something material
    # rather than hoping for a different answer to the same question:
    #   plain          -> the normal case, and the only one most machines
    #                     ever reach;
    #   + AllowUninstall -> Microsoft's own EdgeUpdate policy for "the
    #                     uninstall is permitted", for a channel that set
    #                     it to 0;
    #   + EEA region   -> the DMA-compliant build's own removable path.
    # See $Script:EdgeUninstallBlockedCodes for why a 93 is escalated and
    # never retried.
    if ($UninstallPath) {
        Write-Info "Located Edge uninstaller at: $($UninstallPath.FullName)"
        $SetupPath = $UninstallPath.FullName
        $Code = Invoke-EdgeSetupUninstall -SetupPath $SetupPath

        if ($null -ne $Code -and $Code -ne 0 -and
            ($Script:EdgeUninstallBlockedCodes -contains $Code)) {
            Write-Warn "Edge's uninstaller refused with code $Code - this build treats Edge as non-removable. Escalating."
            $PolicyToken = Set-EdgeUninstallPolicy
            try {
                $Code = Invoke-EdgeSetupUninstall -SetupPath $SetupPath
                if ($null -ne $Code -and $Code -ne 0 -and
                    ($Script:EdgeUninstallBlockedCodes -contains $Code)) {
                    $DmaCode = Invoke-EdgeUninstallUnderDmaRegion -SetupPath $SetupPath
                    if ($null -ne $DmaCode) { $Code = $DmaCode }
                }
            } finally {
                Restore-EdgeUninstallPolicy -Previous $PolicyToken
            }
        }

        if ($Code -eq 0) {
            $Removed = $true
            Write-Success "Edge's own uninstaller completed."
        } elseif ($null -ne $Code) {
            Write-Warn "Edge's uninstaller exited with code $Code - falling back to winget/Appx removal."
        }
    } else {
        Write-Info "Edge's own setup.exe was not found under either Program Files Application root - falling back to winget/Appx cleanup."
    }

    # TIER 2: winget. setup.exe is absent entirely on builds that register
    # Edge as a protected inbox component with no standalone Installer
    # folder - winget still knows how to remove the Win32 package cleanly
    # on those, so this is a real second line of defense, not a last
    # resort.
    #
    # A 1603 here is the SAME BLOCK tier 1 hit, arriving through the MSI
    # layer, so it is reported once and passed over rather than retried.
    if (-not $Removed) {
        Ensure-Winget | Out-Null
        if ($global:WingetAvailable) {
            $Code = Invoke-Winget -ArgList @("uninstall", "--id", "Microsoft.Edge", "--exact", "--silent", "--force", "--accept-source-agreements", "--disable-interactivity")
            if ($Code -eq 0) {
                $Removed = $true
                Write-Success "winget removed the Microsoft Edge package."
            } elseif ($Script:EdgeUninstallBlockedCodes -contains $Code) {
                Write-Warn "winget was blocked from uninstalling Edge (code $Code) - Windows is protecting the package. Falling through to package deregistration."
            } else {
                Write-Warn "winget's Edge uninstall exited with code $Code."
            }
        }
    }

    # TIER 3: forceful package deregistration, ALWAYS - not only when the
    # tiers above failed. These registrations are what makes Windows keep
    # reporting Edge as installed after the Win32 payload is gone, so
    # leaving them behind on the SUCCESS path was how a purge that "worked"
    # still showed Edge present. See Remove-EdgeAppxRegistrations, which
    # also takes the PROVISIONED copy so it cannot return for a new user.
    $AppxCleared = Remove-EdgeAppxRegistrations
    if (-not $Removed) { $Removed = $AppxCleared }

    Remove-EdgeScheduledTasks

    # Final verification against real system state - not just whichever
    # tier reported success - so a partial removal (e.g. the Win32 payload
    # is gone but Windows still shows it "protected") is caught here
    # instead of reporting a clean success that isn't true.
    if ($Removed -or -not (Test-MicrosoftEdgeInstalled)) {
        Write-Success "Microsoft Edge has been uninstalled (a system restart is recommended). A version/settings backup was saved to $Script:EdgeBackupFolder."
        $Script:PendingRestart = $true
        return @{ Status = 'Success'; Message = "Microsoft Edge uninstalled. Settings backup saved to $Script:EdgeBackupFolder. Restart recommended." }
    } else {
        Write-Warn "Edge is either a built-in component and cannot be fully removed, or it is not installed as a standalone. You may reset Edge instead."
        return @{ Status = 'Failed'; Message = 'Windows protected Edge from removal on this build (it is an OS component here). A backup of its settings was still saved.' }
    }
}

function Install-MicrosoftEdge {
    Write-SectionHeader "Install Microsoft Edge"
    if (Ensure-Winget) {
        Write-Info "Installing Microsoft Edge via winget..."
        $Result = Smart-Deploy "Microsoft.Edge" "Microsoft Edge"
        if ($Result.Status -eq 'Success') {
            Restore-EdgeState
        }
    } elseif ($Script:DryRun) {
        Write-Info "[WHATIF] Would install Microsoft Edge via winget and restore backed-up settings."
    } else {
        Write-Warn "Winget unavailable. Opening official download page for a manual install..."
        Write-Info "Manual install steps: download the installer from the page that opens, run it, then use this menu's [6] Reinstall Edge option again if you want your backed-up settings restored."
        Open-UrlSafe -Url "https://www.microsoft.com/en-us/edge/download"
    }
}

# ============================================================
#  BACKWARD-COMPATIBILITY STUB
#  "Restore Windows Default Settings" lives in 02-Safety.ps1 as
#  Reset-AllTweaksToDefaults (restores YOUR original captured values).
#  This stub keeps the old name working for anything that calls it.
# ============================================================
function Reset-WindowsDefaultSettings {
    Reset-AllTweaksToDefaults
}

# ============================================================
#  PERFORMANCE & GAMING OPTIMIZATION
# ============================================================
function Invoke-NetworkOptimization {
    Write-SectionHeader "Network & Ping Optimizer"
    New-SystemRestorePoint
    if (Test-DryRun "Flush DNS, reset Winsock and the IP stack") { return }
    Write-Info "Flushing DNS cache and resetting network stack..."
    # Deliberately NO ipconfig /release + /renew: dropping the DHCP lease
    # mid-task can leave the machine offline if the renew fails (VPNs,
    # static configs, flaky Wi-Fi drivers), and the Winsock/IP-stack reset
    # below requires a reboot to apply anyway.
    $IpconfigExe = Get-SystemBinary 'ipconfig'
    $NetshExe    = Get-SystemBinary 'netsh'
    & $IpconfigExe /flushdns
    $DnsOk = ($LASTEXITCODE -eq 0)
    & $NetshExe winsock reset
    $WinsockOk = ($LASTEXITCODE -eq 0)
    & $NetshExe int ip reset
    $IpOk = ($LASTEXITCODE -eq 0)
    if ($DnsOk -and $WinsockOk -and $IpOk) {
        Write-Success "Network stack reset and DNS flushed. Ping latency should improve."
    } else {
        Write-ErrorX "One or more network reset commands failed (flushdns=$DnsOk, winsock=$WinsockOk, ip=$IpOk) - see the operation log."
    }
    Write-Warn "A restart is recommended for the Winsock/IP reset to fully apply."
    $Script:PendingRestart = $true
}

function Set-PulsePowerPlanTimeouts {
    <#
        .SYNOPSIS
        Pin the display and sleep timeouts to Never on AC power.

        .DESCRIPTION
        The Ultimate/Pulse plan removes the CPU's power ceiling, but Windows
        still blanks the display and drops the machine to standby on the
        plan's inherited timeouts - so a workstation left to run a long
        build, render or transfer stalls anyway. Setting both to 0 (Never)
        is what makes the plan mean what its name promises.

        AC ONLY, deliberately. The -dc counterparts are left untouched: a
        machine on battery that never sleeps is a flat battery (and, in a
        bag, a hot one), which is also why the GUI marks this operation
        Desktop-PCs-only. Anything running on mains keeps its behaviour on
        mains and its safe defaults off it.

        Failures here are reported but NOT fatal to the caller: the power
        scheme itself is already active by this point, and a policy-managed
        machine can refuse the timeout change while allowing the plan.
    #>
    if (Test-DryRun "Set display and sleep timeouts to Never on AC power") { return }

    $Settings = @(
        @{ Label = "Display timeout (AC)"; Arg = "monitor-timeout-ac" },
        @{ Label = "Sleep timeout (AC)";   Arg = "standby-timeout-ac" }
    )
    $PowercfgExe = Get-SystemBinary 'powercfg'
    foreach ($Setting in $Settings) {
        try {
            & $PowercfgExe /change $Setting.Arg 0 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Success "$($Setting.Label) set to Never."
            } else {
                Write-Warn "Could not set $($Setting.Label) - powercfg exited $LASTEXITCODE."
            }
        } catch {
            Write-Warn "Could not set $($Setting.Label): $($_.Exception.Message)"
        }
    }
}

function Enable-UltimatePerformancePowerPlan {
    Write-SectionHeader "Pulse Power Plan"
    New-SystemRestorePoint
    $PlanName   = "Pulse Power Plan"
    $LegacyName = "Humam Ultimate Power Plan"   # pre-rebrand (v5.x) scheme name
    $GuidRegex  = '([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})'
    $PowercfgExe = Get-SystemBinary 'powercfg'
    $Existing = & $PowercfgExe /list | Out-String
    if ($Existing -match [regex]::Escape($PlanName) -and $Existing -match '\*') {
        $ActiveLine = ($Existing -split "`n") | Where-Object { $_ -match [regex]::Escape($PlanName) -and $_ -match '\*' }
        if ($ActiveLine) {
            Write-AlreadyOK "$PlanName is already active."
            # Re-assert the timeouts even on the no-op path. The plan being
            # active does NOT imply its timeouts are still Never - Windows
            # Update, a docking profile or the Settings app can and does
            # reset them under an unchanged scheme, and a user re-running
            # this action to fix exactly that would otherwise be told
            # everything was fine and given nothing.
            Set-PulsePowerPlanTimeouts
            return
        }
    }
    if (Test-DryRun "Duplicate the hidden Ultimate Performance scheme, rename it '$PlanName' and set it active") { return }
    try {
        # A plan created under either name gets reused (the legacy one is
        # renamed in place) - duplicating again would leave two identical
        # schemes cluttering powercfg /list.
        foreach ($Name in @($PlanName, $LegacyName)) {
            $pattern = $GuidRegex + '.*' + [regex]::Escape($Name)
            if ($Existing -match $pattern) {
                $guid = $matches[1]
                if ($Name -ne $PlanName) { & $PowercfgExe /changename $guid $PlanName > $null }
                & $PowercfgExe /setactive $guid > $null
                # powercfg /setactive can exit 0 without actually switching
                # (e.g. a policy-restricted machine) - verify against the
                # ACTUAL active scheme instead of trusting the exit code.
                if ((& $PowercfgExe /getactivescheme | Out-String) -match [regex]::Escape($guid)) {
                    Write-Success "$PlanName activated (existing profile)."
                    Set-PulsePowerPlanTimeouts
                } else {
                    Write-ErrorX "Could not activate $PlanName - the scheme switch did not take effect (policy restriction?)."
                }
                return
            }
        }

        $sourceGuid = "e9a42b02-d5df-448d-aa00-03f14749eb61"
        # Out-String flattens the line array: -match on an array filters
        # elements WITHOUT populating $matches, which broke GUID extraction.
        $dupOutput = & $PowercfgExe /duplicatescheme $sourceGuid 2>&1 | Out-String
        $newGuid = $null
        if ($dupOutput -match $GuidRegex) {
            $newGuid = $matches[1]
        }

        if ($newGuid) {
            & $PowercfgExe /changename $newGuid $PlanName > $null
            & $PowercfgExe /setactive $newGuid > $null
            if ((& $PowercfgExe /getactivescheme | Out-String) -match [regex]::Escape($newGuid)) {
                Write-Success "$PlanName activated successfully."
                Set-PulsePowerPlanTimeouts
            } else {
                Write-ErrorX "Could not activate $PlanName - the scheme switch did not take effect (policy restriction?)."
            }
        } else {
            Write-ErrorX "Could not create or activate $PlanName."
        }
    } catch {
        Write-ErrorX "Could not activate ${PlanName}: $($_.Exception.Message)"
    }
}
