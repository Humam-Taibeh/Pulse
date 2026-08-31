#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
    Pester coverage for the tweak engine's idempotence in BOTH directions
    (Test-TweakInState / Invoke-Tweak in 06-Tweaks.ps1).

.DESCRIPTION
    A Revert* task is Invoke-Tweak with State="Off" — the same function,
    the same catalog entry, the other set of values. Only the "On" side was
    ever asked whether it had anything to do:

        if ($State -eq "On" -and (Test-TweakAlreadyOn ...)) { ... return }

    so re-applying an applied tweak short-circuited with "already applied",
    while re-reverting a reverted one walked the whole write path again and
    reported success. The end state was right either way — the values
    written are the ones already there, and the snapshot layer is
    first-write-wins — so this was never data corruption. It was the half
    of idempotence the user can actually see: a no-op reported as work.

    The same asymmetry made the success line wrong outright. It read
    "$Key applied successfully" for both directions, so reverting Dark Mode
    printed "DarkMode applied successfully" into the live console.

    Everything here runs against a throwaway key under
    HKCU:\Software\PulsePesterTests — never the real tweak paths, which
    are the user's actual settings. Nothing needs elevation.

.NOTES
    Run:  Invoke-Pester -Path tests\backend
#>

BeforeAll {
    $script:RepoRoot  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:ModuleDir = Join-Path $script:RepoRoot "src\backend\modules"
    . (Join-Path $script:ModuleDir "00-Foundation.ps1")
    . (Join-Path $script:ModuleDir "01-Catalogs.ps1")
    . (Join-Path $script:ModuleDir "02-Safety.ps1")
    . (Join-Path $script:ModuleDir "06-Tweaks.ps1")

    $script:SandboxKey = "HKCU:\Software\PulsePesterTests\Tweaks"
    New-Item -Path $script:SandboxKey -Force | Out-Null

    # TWO THINGS INVOKE-TWEAK REACHES FOR THAT A TEST MUST NOT LET IT HAVE.
    #
    # The rollback snapshot defaults to HKCU:\Software\Pulse\TweakBackups —
    # the user's REAL restore data. Writing there from a test could destroy
    # the safety net it is meant to be protecting, so it is redirected into
    # the same throwaway tree as everything else here.
    $script:BackupKey = "HKCU:\Software\PulsePesterTests\TweakBackups"
    $Script:TweaksBackupRegPath = $script:BackupKey

    # And the restore point is a real, slow, machine-wide side effect. It
    # is stubbed rather than mocked so it is impossible for any path
    # through Invoke-Tweak to reach the genuine one.
    function global:New-SystemRestorePoint { }

    # A tweak in the catalog's own shape, pointed at the sandbox.
    $script:Fake = @{
        Key         = "PesterProbe"
        Description = "A tweak that exists only for this test"
        Entries     = @(
            @{ Path = $script:SandboxKey; Name = "Alpha"; OnValue = 1; OffValue = 0; Type = "DWord" },
            @{ Path = $script:SandboxKey; Name = "Beta";  OnValue = 1; OffValue = 0; Type = "DWord" }
        )
    }

    function script:Set-Both([int]$value) {
        foreach ($n in @("Alpha", "Beta")) {
            Set-ItemProperty -Path $script:SandboxKey -Name $n -Value $value -Force
        }
    }
}

AfterAll {
    Remove-Item -Path "HKCU:\Software\PulsePesterTests" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "function:global:New-SystemRestorePoint" -ErrorAction SilentlyContinue
}

Describe "Test-TweakInState" {

    It "sees a fully applied tweak as On and not Off" {
        Set-Both 1
        Test-TweakInState -Tweak $script:Fake -State "On"  | Should -BeTrue
        Test-TweakInState -Tweak $script:Fake -State "Off" | Should -BeFalse
    }

    It "sees a fully reverted tweak as Off and not On" {
        # THE DIRECTION THAT WAS NEVER ASKED.
        Set-Both 0
        Test-TweakInState -Tweak $script:Fake -State "Off" | Should -BeTrue
        Test-TweakInState -Tweak $script:Fake -State "On"  | Should -BeFalse
    }

    It "treats a half-applied tweak as being in neither state" {
        # One entry moved, the other not — which is what a partial failure
        # or an outside edit leaves behind. Reporting that as "already
        # applied" would skip the write that would repair it.
        Set-ItemProperty -Path $script:SandboxKey -Name "Alpha" -Value 1 -Force
        Set-ItemProperty -Path $script:SandboxKey -Name "Beta"  -Value 0 -Force
        Test-TweakInState -Tweak $script:Fake -State "On"  | Should -BeFalse
        Test-TweakInState -Tweak $script:Fake -State "Off" | Should -BeFalse
    }

    It "treats an absent value as not being in either state" {
        Remove-ItemProperty -Path $script:SandboxKey -Name "Alpha" -ErrorAction SilentlyContinue
        Remove-ItemProperty -Path $script:SandboxKey -Name "Beta" -ErrorAction SilentlyContinue
        Test-TweakInState -Tweak $script:Fake -State "On"  | Should -BeFalse
        # A missing value is NOT the same as OffValue=0: Windows may treat
        # absence as the default, but the engine cannot know that for every
        # tweak, and writing the explicit value is the honest repair.
        Test-TweakInState -Tweak $script:Fake -State "Off" | Should -BeFalse
    }

    It "keeps the original single-direction helper working" {
        # The console menus call Test-TweakAlreadyOn by name.
        Set-Both 1
        Test-TweakAlreadyOn -Tweak $script:Fake | Should -BeTrue
        Set-Both 0
        Test-TweakAlreadyOn -Tweak $script:Fake | Should -BeFalse
    }
}

Describe "Invoke-Tweak reports what it actually did" {

    BeforeEach {
        $Script:DryRun = $false
        $Script:NonInteractive = $true
        $Script:SessionFailCount = 0
    }

    It "is a no-op the second time it applies the same tweak" {
        Set-Both 0
        Invoke-Tweak -Tweak $script:Fake -State "On" 6>&1 | Out-Null
        (Get-ItemProperty -Path $script:SandboxKey -Name "Alpha").Alpha | Should -Be 1

        $second = Invoke-Tweak -Tweak $script:Fake -State "On" 6>&1 | Out-String
        $second | Should -BeLike "*already applied*"
        $Script:SessionFailCount | Should -Be 0
    }

    It "is a no-op the second time it reverts the same tweak" {
        # THE REGRESSION. This walked the whole write path and announced
        # success for work it had not done.
        Set-Both 1
        Invoke-Tweak -Tweak $script:Fake -State "Off" 6>&1 | Out-Null
        (Get-ItemProperty -Path $script:SandboxKey -Name "Alpha").Alpha | Should -Be 0

        $second = Invoke-Tweak -Tweak $script:Fake -State "Off" 6>&1 | Out-String
        $second | Should -BeLike "*already reverted*"
        $Script:SessionFailCount | Should -Be 0
    }

    It "does not say 'applied' while reverting" {
        Set-Both 1
        $out = Invoke-Tweak -Tweak $script:Fake -State "Off" 6>&1 | Out-String
        $out | Should -BeLike "*reverted successfully*"
        $out | Should -Not -BeLike "*applied successfully*"
    }

    It "still says 'applied' while applying" {
        Set-Both 0
        $out = Invoke-Tweak -Tweak $script:Fake -State "On" 6>&1 | Out-String
        $out | Should -BeLike "*applied successfully*"
    }

    It "repairs a half-applied tweak rather than skipping it" {
        Set-ItemProperty -Path $script:SandboxKey -Name "Alpha" -Value 1 -Force
        Set-ItemProperty -Path $script:SandboxKey -Name "Beta"  -Value 0 -Force
        Invoke-Tweak -Tweak $script:Fake -State "On" 6>&1 | Out-Null
        (Get-ItemProperty -Path $script:SandboxKey -Name "Beta").Beta | Should -Be 1
    }
}
