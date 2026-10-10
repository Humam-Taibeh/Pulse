#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
    Pester coverage for the nine v1.1 Start Menu / File Explorer tweaks
    (StartHideRecommended, StartDisableWebSearch,
    StartDisableRecentTracking, StartDisableSuggestions,
    ExplorerLaunchToThisPC, ExplorerShowFileExt, ExplorerShowHidden,
    ExplorerShowProtected, ExplorerHideRecommended).

.DESCRIPTION
    NEVER TOUCHES THE REAL REGISTRY PATHS. All nine catalog entries
    (01-Catalogs.ps1) hardcode real per-user paths under
    Explorer\Advanced / Search / ContentDeliveryManager /
    Policies\...\Explorer — unlike TweakIdempotence.Tests.ps1's synthetic
    fake, calling Invoke-Tweak directly against these would overwrite the
    machine's own settings. Every apply/revert test here instead runs
    against a SANDBOXED CLONE of the real entry: Name/OnValue/OffValue/
    Type taken verbatim from the catalog, Path swapped to
    HKCU:\Software\PulsePesterTests. That still exercises the real data
    through the real engine (Invoke-Tweak / Restore-OriginalRegValue) —
    a wrong On/Off value is still caught — it just never writes anywhere
    that matters.

    Get-PulseTweakState (11-StateProbe.ps1) IS called for real, because
    its own hard contract is read-only (see that module's header) — a
    probe that can't mutate anything is safe to run against the real
    registry, and this is the only way to confirm all nine keys actually
    surface through it.

.NOTES
    Run:  Invoke-Pester -Path tests\backend
#>

# TOP-LEVEL, NOT INSIDE BeforeAll: Pester's -ForEach needs this array at
# DISCOVERY time (when the file's own top-level code runs to enumerate
# tests), which is BEFORE any BeforeAll block executes. A first version of
# this file defined it inside BeforeAll and every -ForEach It below
# discovered zero tests as a result.
$script:Keys = @(
    "StartHideRecommended", "StartDisableWebSearch",
    "StartDisableRecentTracking", "StartDisableSuggestions",
    "ExplorerLaunchToThisPC", "ExplorerShowFileExt",
    "ExplorerShowHidden", "ExplorerShowProtected",
    "ExplorerHideRecommended"
)

BeforeAll {
    $script:RepoRoot  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:ModuleDir = Join-Path $script:RepoRoot "src\backend\modules"
    . (Join-Path $script:ModuleDir "00-Foundation.ps1")
    . (Join-Path $script:ModuleDir "01-Catalogs.ps1")
    . (Join-Path $script:ModuleDir "02-Safety.ps1")
    . (Join-Path $script:ModuleDir "06-Tweaks.ps1")
    . (Join-Path $script:ModuleDir "11-StateProbe.ps1")
    . (Join-Path $script:ModuleDir "30-GuiDispatcher.ps1")   # Get-TweakByKey

    $script:SandboxKey = "HKCU:\Software\PulsePesterTests\Tweaks"
    $script:BackupKey  = "HKCU:\Software\PulsePesterTests\TweakBackups"
    New-Item -Path $script:SandboxKey -Force | Out-Null
    $Script:TweaksBackupRegPath = $script:BackupKey
    function global:New-SystemRestorePoint { }

    # A faithful sandboxed CLONE: every field but Path copied verbatim
    # from the real catalog entry.
    function script:Get-SandboxedTweak([string]$Key) {
        $Real = Get-TweakByKey $Key
        $Clone = @{ Key = $Real.Key; Description = $Real.Description; Entries = @() }
        foreach ($E in $Real.Entries) {
            $Clone.Entries += @{
                Path = $script:SandboxKey; Name = $E.Name
                OnValue = $E.OnValue; OffValue = $E.OffValue; Type = $E.Type
            }
        }
        return $Clone
    }
}

AfterAll {
    Remove-Item -Path "HKCU:\Software\PulsePesterTests" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "function:global:New-SystemRestorePoint" -ErrorAction SilentlyContinue
}

Describe "Start Menu / File Explorer catalog shape" {
    It "<_> exists in the catalog with at least one entry" -ForEach $script:Keys {
        $Tweak = Get-TweakByKey $_
        $Tweak | Should -Not -BeNullOrEmpty
        $Tweak.Entries.Count | Should -BeGreaterThan 0
    }

    It "<_> writes only HKCU values — no admin should ever be needed" -ForEach $script:Keys {
        $Tweak = Get-TweakByKey $_
        foreach ($E in $Tweak.Entries) {
            $E.Path | Should -Match '^HKCU:'
        }
    }

    It "<_> has a matching Restore-*Tweak function" -ForEach $script:Keys {
        Get-Command "Restore-$($_)Tweak" -ErrorAction SilentlyContinue |
            Should -Not -BeNullOrEmpty
    }

    It "<_> is surfaced by the read-only state probe" -ForEach $script:Keys {
        $State = Get-PulseTweakState
        $State.Contains($_) | Should -BeTrue
    }
}

Describe "Start Menu / File Explorer tweaks apply and revert idempotently" {
    BeforeEach {
        $Script:DryRun = $false
        $Script:NonInteractive = $true
        $Script:SessionFailCount = 0
        Remove-Item -Path $script:SandboxKey -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -Path $script:SandboxKey -Force | Out-Null
        Remove-Item -Path $script:BackupKey -Recurse -Force -ErrorAction SilentlyContinue
    }

    It "<_> applies its On values and is a no-op the second time" -ForEach $script:Keys {
        $Sandboxed = Get-SandboxedTweak $_
        Invoke-Tweak -Tweak $Sandboxed -State "On" 6>&1 | Out-Null
        foreach ($E in $Sandboxed.Entries) {
            (Get-ItemProperty -Path $script:SandboxKey -Name $E.Name).($E.Name) |
                Should -Be $E.OnValue
        }
        $second = Invoke-Tweak -Tweak $Sandboxed -State "On" 6>&1 | Out-String
        $second | Should -BeLike "*already applied*"
        $Script:SessionFailCount | Should -Be 0
    }

    It "<_> restores the ORIGINAL value it overwrote, not a canned default" -ForEach $script:Keys {
        # Same reasoning Restore-OriginalRegValue itself documents: a
        # snapshot may hold whatever non-default value the user actually
        # had, and revert must bring that back — not a hardcoded default.
        $Sandboxed = Get-SandboxedTweak $_
        $Original = 77
        foreach ($E in $Sandboxed.Entries) {
            Set-ItemProperty -Path $script:SandboxKey -Name $E.Name -Value $Original -Force -Type DWord
        }
        Invoke-Tweak -Tweak $Sandboxed -State "On" 6>&1 | Out-Null
        foreach ($E in $Sandboxed.Entries) {
            (Get-ItemProperty -Path $script:SandboxKey -Name $E.Name).($E.Name) |
                Should -Be $E.OnValue
        }
        foreach ($E in $Sandboxed.Entries) {
            $Ok = Restore-OriginalRegValue -TweakKey $Sandboxed.Key -Path $E.Path -Name $E.Name `
                -DefaultIfMissing "0" -Type $E.Type
            $Ok | Should -BeTrue
            (Get-ItemProperty -Path $script:SandboxKey -Name $E.Name).($E.Name) |
                Should -Be $Original
        }
    }
}
