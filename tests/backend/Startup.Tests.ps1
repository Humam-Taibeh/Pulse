#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
    Pester coverage for startup-item scope preservation (05-Startup.ps1) and
    the health report's startup roll-up (12-HealthReport.ps1).

.DESCRIPTION
    Both invariants here failed SILENTLY before v1.0 — the operation the user
    asked for reported success, and the damage was only visible later, from a
    different account or not at all:

      * SCOPE PRESERVATION — Enable-StartupItem hard-coded the per-user Run
        key and the per-user Startup folder. Disabling an all-users entry
        (HKLM Run, or a shortcut in ProgramData) and re-enabling it therefore
        narrowed it to ONE profile: it still launched for whoever clicked
        re-enable, and stopped launching for every other user on the machine.
        Nothing reported that, because writing to HKCU genuinely succeeded.

      * THE RECOMMENDATION ROLL-UP — Get-StartupRecommendation returns a
        hashtable, and the health report compared it to a string. That is
        always $false, so recommendedDisable was hard-wired to 0 and the
        report's "N startup items recommended for disabling" finding could
        never fire on any machine.

    ISOLATION: nothing here touches a real Run key or a real Startup folder.
    $Script:StartupRunKeyPaths / StartupFolderPaths / StartupDisabledRegPath /
    StartupOriginRegPath / StartupBackupFolder are all redirected into
    HKCU:\Software\PulsePesterTests and a temp directory, so the suite cannot
    disable a program the developer actually relies on at sign-in. The "HKLM"
    stand-in is a second key under the test hive rather than the real HKLM,
    which keeps the whole suite unelevated — what is under test is that the
    RECORDED ORIGIN is honoured, and that logic is hive-agnostic.

.NOTES
    Run:  Invoke-Pester -Path tests\backend
#>

BeforeAll {
    $script:RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:ModuleDir = Join-Path $script:RepoRoot "src\backend\modules"

    # Dot-source order mirrors core.ps1's sorted load. 05 needs 00's
    # Resolve-UserRegPath / Test-DryRun / Write-* vocabulary; 12 needs 05's
    # Get-AllStartupItems and Get-StartupRecommendation.
    . (Join-Path $script:ModuleDir "00-Foundation.ps1")
    . (Join-Path $script:ModuleDir "01-Catalogs.ps1")
    . (Join-Path $script:ModuleDir "05-Startup.ps1")
    . (Join-Path $script:ModuleDir "09-SystemInfo.ps1")
    . (Join-Path $script:ModuleDir "11-StateProbe.ps1")
    . (Join-Path $script:ModuleDir "12-HealthReport.ps1")

    # HERMETIC SINCE v10.13. Get-AllStartupItems now reads Task Scheduler
    # and Get-StartupReportData reads the boot-performance log. Left real,
    # every count-based test below would change with whatever tasks the
    # developer's machine happens to have registered - GIGABYTE's two logon
    # tasks alone would break "reports totals consistent". Mocked at the
    # root, so every Describe inherits them; the Describes that are about
    # tasks or boot timings override them.
    Mock Get-PulseScheduledTasks { @() }
    Mock Get-BootPerformanceLogState { 'needs-admin' }

    # --- isolation ---------------------------------------------------
    $script:TestRoot = "HKCU:\Software\PulsePesterTests"
    $script:UserRunKey = "$script:TestRoot\Run_User"
    $script:MachineRunKey = "$script:TestRoot\Run_Machine"
    $script:TempBase = Join-Path ([System.IO.Path]::GetTempPath()) "PulsePesterStartup"

    $Script:StartupDisabledRegPath = "$script:TestRoot\DisabledStartup"
    $Script:StartupOriginRegPath = "$Script:StartupDisabledRegPath\_Origins"
    $Script:StartupRunKeyPaths = @($script:UserRunKey, $script:MachineRunKey)
    $Script:StartupFolderPaths = @(
        (Join-Path $script:TempBase "Startup_User"),
        (Join-Path $script:TempBase "Startup_Machine")
    )
    $Script:StartupBackupFolder = Join-Path $script:TempBase "Backup"

    $Script:LogPath = Join-Path ([System.IO.Path]::GetTempPath()) "PulsePesterStartup.log"
    $Script:DryRun = $false

    function Reset-TestState {
        if (Test-Path $script:TestRoot) {
            Remove-Item -Path $script:TestRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        New-Item -Path $script:UserRunKey -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -Path $script:MachineRunKey -Force -ErrorAction SilentlyContinue | Out-Null

        if (Test-Path $script:TempBase) {
            Remove-Item -Path $script:TempBase -Recurse -Force -ErrorAction SilentlyContinue
        }
        foreach ($dir in (@($Script:StartupFolderPaths) + $Script:StartupBackupFolder)) {
            New-Item -Path $dir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null
        }
    }
}

AfterAll {
    if (Test-Path $script:TestRoot) {
        Remove-Item -Path $script:TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $script:TempBase) {
        Remove-Item -Path $script:TempBase -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($Script:LogPath -and (Test-Path $Script:LogPath)) {
        Remove-Item -Path $Script:LogPath -Force -ErrorAction SilentlyContinue
    }
}

Describe "Startup item scope preservation (05-Startup.ps1)" {

    BeforeEach {
        Reset-TestState
        $Script:DryRun = $false
        $Script:SessionFailCount = 0
        $Script:SessionSuccessCount = 0
    }

    Context "Test isolation" {
        It "never points at a real Run key or Startup folder" {
            # If this fails, STOP: the suite is about to disable programs the
            # developer actually depends on at sign-in.
            $Script:StartupRunKeyPaths[0] | Should -BeLike "*PulsePesterTests*"
            $Script:StartupRunKeyPaths[1] | Should -BeLike "*PulsePesterTests*"
            $Script:StartupDisabledRegPath | Should -Not -Be "HKCU:\Software\Pulse\DisabledStartup"
            foreach ($folder in $Script:StartupFolderPaths) {
                $folder | Should -Not -BeLike "*Start Menu*"
            }
        }
    }

    Context "The origin ledger" {
        It "records the hive an entry was disabled from" {
            Set-ItemProperty -Path $script:MachineRunKey -Name "AcmeUpdater" -Value "C:\acme.exe" -Force
            $item = [PSCustomObject]@{
                Type = "Registry"; Hive = "HKLM"; RegPath = $script:MachineRunKey
                Name = "AcmeUpdater"; Command = "C:\acme.exe"; Enabled = $true
            }
            Disable-StartupItem -Item $item

            Get-StartupOrigin -Type "Registry" -Name "AcmeUpdater" |
                Should -Be $script:MachineRunKey
        }

        It "keeps the ledger out of the disabled-items list" {
            # The origin record lives in a SUB-KEY precisely so it cannot
            # surface as a phantom startup entry in the GUI.
            Set-ItemProperty -Path $script:MachineRunKey -Name "AcmeUpdater" -Value "C:\acme.exe" -Force
            Disable-StartupItem -Item ([PSCustomObject]@{
                Type = "Registry"; Hive = "HKLM"; RegPath = $script:MachineRunKey
                Name = "AcmeUpdater"; Command = "C:\acme.exe"; Enabled = $true })

            $names = @(Get-DisabledStartupItems | Select-Object -ExpandProperty Name)
            $names | Should -Contain "AcmeUpdater"
            $names | Should -Not -Contain "_Origins"
            $names | Should -Not -Contain "Registry|||AcmeUpdater"
        }

        It "returns null for an entry disabled by a pre-1.0 Pulse" {
            # Legacy rows have no record; callers must fall back, not throw.
            New-Item -Path $Script:StartupDisabledRegPath -Force | Out-Null
            Set-ItemProperty -Path $Script:StartupDisabledRegPath -Name "Legacy" -Value "C:\old.exe" -Force

            Get-StartupOrigin -Type "Registry" -Name "Legacy" | Should -BeNullOrEmpty
        }
    }

    Context "Registry entries restore to their original hive" {
        It "returns an all-users entry to the machine key, not the user key" {
            # THE regression. Before v1.0 this landed in the per-user Run key
            # and silently stopped launching for every other account.
            Set-ItemProperty -Path $script:MachineRunKey -Name "AcmeUpdater" -Value "C:\acme.exe" -Force
            $item = [PSCustomObject]@{
                Type = "Registry"; Hive = "HKLM"; RegPath = $script:MachineRunKey
                Name = "AcmeUpdater"; Command = "C:\acme.exe"; Enabled = $true
            }
            Disable-StartupItem -Item $item
            (Get-Item $script:MachineRunKey).Property | Should -Not -Contain "AcmeUpdater"

            $disabled = Get-DisabledStartupItems |
                Where-Object { $_.Name -eq "AcmeUpdater" } | Select-Object -First 1
            Enable-StartupItem -Item $disabled

            (Get-RegValue -Path $script:MachineRunKey -Name "AcmeUpdater") |
                Should -Be "C:\acme.exe" -Because "an all-users entry must come back for all users"
            (Get-Item $script:UserRunKey).Property |
                Should -Not -Contain "AcmeUpdater" -Because "restoring it per-user is the bug under test"
        }

        It "returns a per-user entry to the user key" {
            Set-ItemProperty -Path $script:UserRunKey -Name "MyApp" -Value "C:\mine.exe" -Force
            $item = [PSCustomObject]@{
                Type = "Registry"; Hive = "HKCU"; RegPath = $script:UserRunKey
                Name = "MyApp"; Command = "C:\mine.exe"; Enabled = $true
            }
            Disable-StartupItem -Item $item
            $disabled = Get-DisabledStartupItems |
                Where-Object { $_.Name -eq "MyApp" } | Select-Object -First 1
            Enable-StartupItem -Item $disabled

            (Get-RegValue -Path $script:UserRunKey -Name "MyApp") | Should -Be "C:\mine.exe"
            (Get-Item $script:MachineRunKey).Property | Should -Not -Contain "MyApp"
        }

        It "clears the origin record once the restore succeeded" {
            Set-ItemProperty -Path $script:MachineRunKey -Name "AcmeUpdater" -Value "C:\acme.exe" -Force
            Disable-StartupItem -Item ([PSCustomObject]@{
                Type = "Registry"; Hive = "HKLM"; RegPath = $script:MachineRunKey
                Name = "AcmeUpdater"; Command = "C:\acme.exe"; Enabled = $true })
            $disabled = Get-DisabledStartupItems |
                Where-Object { $_.Name -eq "AcmeUpdater" } | Select-Object -First 1
            Enable-StartupItem -Item $disabled

            Get-StartupOrigin -Type "Registry" -Name "AcmeUpdater" | Should -BeNullOrEmpty
        }

        It "falls back to the user key for a legacy entry with no record" {
            New-Item -Path $Script:StartupDisabledRegPath -Force | Out-Null
            Set-ItemProperty -Path $Script:StartupDisabledRegPath -Name "Legacy" -Value "C:\old.exe" -Force
            $disabled = Get-DisabledStartupItems |
                Where-Object { $_.Name -eq "Legacy" } | Select-Object -First 1

            Enable-StartupItem -Item $disabled

            (Get-RegValue -Path $script:UserRunKey -Name "Legacy") |
                Should -Be "C:\old.exe" -Because "no record means the pre-1.0 per-user default"
        }

        It "refuses an origin outside the known startup locations" {
            # The ledger is in a user-writable hive and its value is fed to
            # Set-ItemProperty, so a tampered record must not redirect a write.
            $hijack = "$script:TestRoot\Hijacked"
            New-Item -Path $hijack -Force | Out-Null
            # PARENT FIRST. New-Item -Force on an existing registry key
            # RECREATES it, so creating _Origins and then its parent silently
            # deleted the record this test depends on — the assertion below
            # then passed for the wrong reason (no record at all, rather than
            # a rejected one), which is exactly the false green a tampered
            # ledger would hide behind.
            New-Item -Path $Script:StartupDisabledRegPath -Force | Out-Null
            New-Item -Path $Script:StartupOriginRegPath -Force | Out-Null
            Set-ItemProperty -Path $Script:StartupDisabledRegPath -Name "Evil" -Value "C:\evil.exe" -Force
            Set-ItemProperty -Path $Script:StartupOriginRegPath -Name "Registry|||Evil" -Value $hijack -Force

            # Guard the guard: prove the tampered record is actually readable,
            # or the fallback assertion proves nothing.
            Get-StartupOrigin -Type "Registry" -Name "Evil" |
                Should -Be $hijack -Because "the test must actually plant a record to reject"

            Resolve-StartupRestoreTarget -Type "Registry" -Name "Evil" |
                Should -Be $script:UserRunKey -Because "an unrecognised origin must fall back, never be honoured"

            $disabled = Get-DisabledStartupItems |
                Where-Object { $_.Name -eq "Evil" } | Select-Object -First 1
            Enable-StartupItem -Item $disabled
            (Get-Item $hijack).Property | Should -Not -Contain "Evil"
        }

        It "writes nothing under -WhatIf" {
            Set-ItemProperty -Path $script:MachineRunKey -Name "AcmeUpdater" -Value "C:\acme.exe" -Force
            $Script:DryRun = $true
            Disable-StartupItem -Item ([PSCustomObject]@{
                Type = "Registry"; Hive = "HKLM"; RegPath = $script:MachineRunKey
                Name = "AcmeUpdater"; Command = "C:\acme.exe"; Enabled = $true })

            (Get-Item $script:MachineRunKey).Property |
                Should -Contain "AcmeUpdater" -Because "a dry run must not disable anything"
            Get-StartupOrigin -Type "Registry" -Name "AcmeUpdater" |
                Should -BeNullOrEmpty -Because "and must not write an origin record either"
        }
    }

    Context "Startup-folder shortcuts restore to their original folder" {
        It "returns an all-users shortcut to the machine folder" {
            $machineFolder = $Script:StartupFolderPaths[1]
            $shortcut = Join-Path $machineFolder "AcmeAll.lnk"
            Set-Content -LiteralPath $shortcut -Value "stub" -Encoding ASCII

            $item = [PSCustomObject]@{
                Type = "Folder"; Hive = ""; RegPath = $machineFolder
                Name = "AcmeAll.lnk"; Command = $shortcut; Enabled = $true
            }
            Disable-StartupItem -Item $item
            Test-Path -LiteralPath $shortcut | Should -BeFalse

            $disabled = Get-DisabledStartupItems |
                Where-Object { $_.Name -eq "AcmeAll.lnk" } | Select-Object -First 1
            Enable-StartupItem -Item $disabled

            Test-Path -LiteralPath $shortcut |
                Should -BeTrue -Because "an all-users shortcut must return to the all-users folder"
            Test-Path -LiteralPath (Join-Path $Script:StartupFolderPaths[0] "AcmeAll.lnk") |
                Should -BeFalse
        }

        It "returns a per-user shortcut to the user folder" {
            $userFolder = $Script:StartupFolderPaths[0]
            $shortcut = Join-Path $userFolder "Mine.lnk"
            Set-Content -LiteralPath $shortcut -Value "stub" -Encoding ASCII

            Disable-StartupItem -Item ([PSCustomObject]@{
                Type = "Folder"; Hive = ""; RegPath = $userFolder
                Name = "Mine.lnk"; Command = $shortcut; Enabled = $true })
            $disabled = Get-DisabledStartupItems |
                Where-Object { $_.Name -eq "Mine.lnk" } | Select-Object -First 1
            Enable-StartupItem -Item $disabled

            Test-Path -LiteralPath $shortcut | Should -BeTrue
            Test-Path -LiteralPath (Join-Path $Script:StartupFolderPaths[1] "Mine.lnk") | Should -BeFalse
        }

        It "handles a bracketed filename literally" {
            # "Game [2].lnk" is an ordinary filename; -Path would read the
            # brackets as a character class and move nothing.
            $userFolder = $Script:StartupFolderPaths[0]
            $shortcut = Join-Path $userFolder "Game [2].lnk"
            Set-Content -LiteralPath $shortcut -Value "stub" -Encoding ASCII

            Disable-StartupItem -Item ([PSCustomObject]@{
                Type = "Folder"; Hive = ""; RegPath = $userFolder
                Name = "Game [2].lnk"; Command = $shortcut; Enabled = $true })

            Test-Path -LiteralPath $shortcut | Should -BeFalse
            Test-Path -LiteralPath (Join-Path $Script:StartupBackupFolder "Game [2].lnk") | Should -BeTrue
        }
    }
}

Describe "Health report startup roll-up (12-HealthReport.ps1)" {

    BeforeEach {
        Reset-TestState
        $Script:DryRun = $false
    }

    It "counts items the recommendation engine flags for disabling" {
        # The bug: Get-StartupRecommendation returns a HASHTABLE, and the
        # report compared it to the string 'Disable'. Always false, so this
        # count was 0 on every machine and the report's corresponding finding
        # could never fire. Steam is a High-impact entry in
        # $Script:StartupDisableRules.
        Set-ItemProperty -Path $script:UserRunKey -Name "Steam" -Value "C:\steam.exe" -Force

        $report = Get-HealthStartupReport

        $report | Should -Not -BeNullOrEmpty
        $report.recommendedDisable |
            Should -BeGreaterThan 0 -Because "a flagged launcher must be counted, not silently dropped"
    }

    It "does not flag an item the keep rules protect" {
        Set-ItemProperty -Path $script:UserRunKey -Name "SecurityHealth" -Value "C:\Windows\System32\SecurityHealthSystray.exe" -Force

        (Get-HealthStartupReport).recommendedDisable | Should -Be 0
    }

    It "reports totals consistent with the discovered items" {
        Set-ItemProperty -Path $script:UserRunKey -Name "Steam" -Value "C:\steam.exe" -Force
        Set-ItemProperty -Path $script:UserRunKey -Name "SecurityHealth" -Value "C:\sh.exe" -Force

        $report = Get-HealthStartupReport

        $report.total | Should -Be 2
        $report.enabled | Should -Be 2
        $report.recommendedDisable | Should -BeLessOrEqual $report.total
    }
}


# ============================================================
#  WHAT THE ROW IS CALLED  (v10.12.1)
#
#  A STARTUP ENTRY'S NAME IS AN IDENTIFIER, NOT A LABEL - it is whatever
#  an installer wrote into a Run key. Measured on one ordinary machine,
#  three of fifteen rows read as internal plumbing: "electron.app.Notion",
#  "electron.app.BlueStacks Services", and "MicrosoftEdgeAutoLaunch_"
#  followed by a 32-character hash.
#
#  Every case below is a string taken from that machine rather than
#  invented, which is why the "leaves it alone" test matters as much as
#  the others: the same list contains RtkAudUService, SignalRgb and
#  iTunesHelper, and a blanket CamelCase split would turn those into
#  "Rtk Aud U Service", "Signal Rgb" and "i Tunes Helper".
# ============================================================
Describe "Get-StartupDisplayName" {

    It "strips a packaging framework's namespace" {
        Get-StartupDisplayName -Name 'electron.app.Notion' | Should -Be 'Notion'
        Get-StartupDisplayName -Name 'electron.app.BlueStacks Services' |
            Should -Be 'BlueStacks Services'
    }

    It "strips a trailing machine hash and names the product" {
        Get-StartupDisplayName -Name 'MicrosoftEdgeAutoLaunch_2B610651ED2659F79480D73FD06733E7' |
            Should -Be 'Microsoft Edge AutoLaunch'
    }

    It "drops a shortcut's file extension" {
        Get-StartupDisplayName -Name 'AnyDesk.lnk' | Should -Be 'AnyDesk'
    }

    It "LEAVES AN ORDINARY NAME ALONE" {
        <#
            The half that stops this being a net loss. A blanket
            CamelCase split would "fix" three names and mangle the other
            twelve, so the mechanical rules only remove things that are
            demonstrably not part of a product name, and the identifiers
            no rule can space out correctly get a curated entry instead.
        #>
        foreach ($name in @('RtkAudUService', 'SecurityHealth', 'Steam',
                            'iTunesHelper', 'SignalRgb', 'RiotClient',
                            'Adobe Acrobat Synchronizer', 'CNAP3 Launcher',
                            'Sideloadly Daemon')) {
            Get-StartupDisplayName -Name $name | Should -Be $name
        }
    }

    It "does not mistake a short hex run inside a name for a hash" {
        # Twelve hex characters is the floor, and it is chosen to be
        # safely above real words - "DEADBEEF" is eight.
        Get-StartupDisplayName -Name 'Thing_DEADBEEF' | Should -Be 'Thing_DEADBEEF'
        Get-StartupDisplayName -Name 'Direct3D' | Should -Be 'Direct3D'
    }

    It "never returns nothing" {
        # A row with no label at all is worse than one with an ugly label.
        Get-StartupDisplayName -Name 'electron.app.' | Should -Be 'electron.app.'
        Get-StartupDisplayName -Name '' | Should -Be ''
    }
}

# ============================================================
#  WHETHER THE PROGRAM IS STILL THERE  (v10.12.1)
#
#  UNINSTALLING SOFTWARE ON WINDOWS DOES NOT RELIABLY REMOVE ITS RUN KEY.
#  Measured on one ordinary machine, SIX of fifteen startup entries
#  pointed at binaries that are no longer on disk - Adobe, iTunes,
#  BlueStacks, Riot, Sideloadly, and a Squirrel package carrying its own
#  ".dead" uninstall marker. Windows tries to launch all six every boot.
#
#  The GUI could not say so: it asked Windows for an icon, got nothing,
#  and drew the neutral executable mark - which is the correct picture
#  and reads as a BROKEN ICON. Six unexplained grey boxes look like a
#  defect in the tool; six rows captioned MISSING are six entries worth
#  turning off.
# ============================================================
Describe "Test-StartupTargetPresent" {

    It "finds a bare path" {
        $exe = Join-Path $env:SystemRoot "System32\notepad.exe"
        Test-StartupTargetPresent -Command $exe | Should -BeTrue
    }

    It "finds a QUOTED path with arguments" {
        $exe = Join-Path $env:SystemRoot "System32\notepad.exe"
        Test-StartupTargetPresent -Command "`"$exe`" -background" | Should -BeTrue
    }

    It "finds an UNQUOTED path with spaces and arguments" {
        # THE HARD ONE, and the common one: splitting on the first space
        # turns "C:\Program Files\App\app.exe /q" into "C:\Program".
        $exe = Join-Path $env:SystemRoot "System32\notepad.exe"
        Test-StartupTargetPresent -Command "$exe --minimized /background" | Should -BeTrue
    }

    It "expands environment variables" {
        Test-StartupTargetPresent -Command '%SystemRoot%\System32\notepad.exe' | Should -BeTrue
        Test-StartupTargetPresent -Command '"%SystemRoot%\System32\notepad.exe" --x' | Should -BeTrue
    }

    It "reports an uninstalled program as ABSENT" {
        # Every one of these shapes was a real orphaned Run key.
        Test-StartupTargetPresent -Command '"C:\Program Files\iTunes\iTunesHelper.exe"' | Should -BeFalse
        Test-StartupTargetPresent -Command 'C:\Riot Games\Riot Client\RiotClientServices.exe --launch-background-mode' | Should -BeFalse
        Test-StartupTargetPresent -Command 'C:\Users\Nobody\AppData\Local\Gone\gone.exe' | Should -BeFalse
    }

    It "survives a command that is not a path at all" {
        Test-StartupTargetPresent -Command '' | Should -BeFalse
        Test-StartupTargetPresent -Command 'nonsense value here' | Should -BeFalse
        Test-StartupTargetPresent -Command 'C:\bad|entry\x.exe' | Should -BeFalse
    }
}

Describe "Get-StartupReportData carries the label and the presence" {

    It "sends DisplayName BESIDE Name, never instead of it" {
        <#
            `Id` is "Type|||RegPath|||Name" and
            Resolve-StartupItemByEncodedId re-locates the item by that
            exact triple, so rewriting Name in place would break every
            toggle. The raw identifier has to survive.
        #>
        Set-ItemProperty -Path $script:UserRunKey -Name "electron.app.Notion" `
            -Value "C:\Users\Nobody\AppData\Local\Programs\Notion\Notion.exe --open-at-login" -Force
        $row = @(Get-StartupReportData | Where-Object { $_.Name -eq 'electron.app.Notion' })[0]
        $row | Should -Not -BeNullOrEmpty
        $row.Name        | Should -Be 'electron.app.Notion'
        $row.DisplayName | Should -Be 'Notion'
        $row.Id          | Should -BeLike '*|||electron.app.Notion'
        $row.TargetPresent | Should -BeFalse -Because "that path is not on this machine"
    }

    It "reports a present target as present" {
        $exe = Join-Path $env:SystemRoot "System32\notepad.exe"
        Set-ItemProperty -Path $script:UserRunKey -Name "PulseProbe" -Value "`"$exe`" -x" -Force
        $row = @(Get-StartupReportData | Where-Object { $_.Name -eq 'PulseProbe' })[0]
        $row.TargetPresent | Should -BeTrue
    }
}


# ============================================================
#  OFFICE'S OWN UPDATERS READ "SAFE TO KEEP"  (v10.13)
#
#  Listing sign-in tasks put two of Office's, under \Microsoft\Office\, in
#  front of the user. That is outside the protected \Microsoft\Windows\
#  tree and no rule matched them, so they read "Worth Reviewing" - an
#  invitation to switch off Office security fixes. The commands are the
#  ones measured on the machine this was built on.
# ============================================================
Describe "Get-StartupRecommendation for Office's own updaters" {

    It "keeps <Name>" -ForEach @(
        @{ Name    = 'Office Automatic Updates 2.0'
           Command = '"C:\Program Files\Common Files\Microsoft Shared\ClickToRun\OfficeC2RClient.exe" /frequentupdate SCHEDULEDTASK displaylevel=False' }
        @{ Name    = 'Office Feature Updates Logon'
           Command = '"C:\Program Files\Microsoft Office\root\Office16\sdxhelper.exe" /onlogon' }
    ) {
        $Rec = Get-StartupRecommendation -Item ([PSCustomObject]@{ Type = 'Task'; Name = $Name; Command = $Command })
        $Rec.Recommendation | Should -Be 'Keep'
        # KEPT, not PROTECTED: an updater is not a system component, so it
        # does not wear "System Critical", and it can still be turned off
        # by hand.
        $Rec.Protected | Should -BeFalse
    }

    It "does not keep a program just because its name says Office" {
        $Rec = Get-StartupRecommendation -Item ([PSCustomObject]@{
            Type = 'Registry'; Name = 'OfficeTimeTracker'; Command = 'C:\Tools\officetimetracker.exe' })
        $Rec.Recommendation | Should -Be 'Review'
    }
}


# ============================================================
#  SCHEDULED TASKS IN THE STARTUP MANAGER  (v10.13)
#
#  The Startup Manager audited Run keys and Startup folders only, and a
#  large share of modern autostart is a Task Scheduler entry with a logon
#  trigger instead. Every task here is a mock - nothing in this file can
#  enable or disable a real task.
# ============================================================
Describe "Get-StartupTaskItems" {

    BeforeAll {
        function script:New-Trigger([string]$Class) {
            [PSCustomObject]@{ CimClass = [PSCustomObject]@{ CimClassName = $Class } }
        }
        function script:New-Exec([string]$Execute, [string]$Arguments = '') {
            [PSCustomObject]@{ CimClass = [PSCustomObject]@{ CimClassName = 'MSFT_TaskExecAction' }
                               Execute = $Execute; Arguments = $Arguments }
        }
        function script:New-Task([string]$Path, [string]$Name, [object[]]$Triggers, [object[]]$Actions,
                                 [string]$State = 'Ready') {
            [PSCustomObject]@{ TaskPath = $Path; TaskName = $Name; State = $State
                               Triggers = $Triggers; Actions = $Actions }
        }
    }

    BeforeEach {
        Reset-TestState
        $script:FakeTasks = @()
        Mock Get-PulseScheduledTasks { $script:FakeTasks }
    }

    It "lists a third-party task that runs at sign-in" {
        $script:FakeTasks = @(New-Task -Path '\' -Name 'GCC' `
            -Triggers @(New-Trigger 'MSFT_TaskLogonTrigger') `
            -Actions @(New-Exec '"C:\Program Files\GIGABYTE\Control Center\GCC.exe"' '-b'))
        $Items = @(Get-StartupTaskItems)
        $Items.Count | Should -Be 1
        $Items[0].Type | Should -Be 'Task'
        $Items[0].RegPath | Should -Be '\'
        $Items[0].Name | Should -Be 'GCC'
        $Items[0].Command | Should -Be '"C:\Program Files\GIGABYTE\Control Center\GCC.exe" -b'
        $Items[0].Enabled | Should -BeTrue
        $Items[0].Trigger | Should -Be 'at sign-in'
    }

    It "lists a boot-triggered task, and reports a disabled one as disabled" {
        $script:FakeTasks = @(New-Task -Path '\Vendor\' -Name 'AtBoot' -State 'Disabled' `
            -Triggers @(New-Trigger 'MSFT_TaskBootTrigger') -Actions @(New-Exec 'C:\Vendor\boot.exe'))
        $Item = @(Get-StartupTaskItems)[0]
        $Item.Trigger | Should -Be 'at boot'
        $Item.Enabled | Should -BeFalse
    }

    It "does not treat scheduled work as startup" {
        # A daily updater or an on-unlock helper runs, but not at startup.
        $script:FakeTasks = @(
            (New-Task -Path '\' -Name 'Daily' -Triggers @(New-Trigger 'MSFT_TaskDailyTrigger') -Actions @(New-Exec 'C:\V\d.exe')),
            (New-Task -Path '\' -Name 'Unlock' -Triggers @(New-Trigger 'MSFT_TaskSessionStateChangeTrigger') -Actions @(New-Exec 'C:\V\u.exe'))
        )
        @(Get-StartupTaskItems).Count | Should -Be 0
    }

    It "never lists the operating system's own tasks" {
        $script:FakeTasks = @(
            (New-Task -Path '\Microsoft\Windows\Shell\' -Name 'OsTask' -Triggers @(New-Trigger 'MSFT_TaskLogonTrigger') -Actions @(New-Exec 'C:\V\x.exe')),
            (New-Task -Path '\' -Name 'CreateExplorerShellUnelevatedTask' -Triggers @(New-Trigger 'MSFT_TaskLogonTrigger') `
                -Actions @(New-Exec (Join-Path $env:SystemRoot 'explorer.exe') '/NoUACCheck'))
        )
        @(Get-StartupTaskItems).Count | Should -Be 0
    }

    It "skips a task with no program to launch" {
        $Com = [PSCustomObject]@{ CimClass = [PSCustomObject]@{ CimClassName = 'MSFT_TaskComHandlerAction' } }
        $script:FakeTasks = @(New-Task -Path '\' -Name 'ComOnly' -Triggers @(New-Trigger 'MSFT_TaskLogonTrigger') -Actions @($Com))
        @(Get-StartupTaskItems).Count | Should -Be 0
    }

    It "flows into Get-AllStartupItems and the report, with its MISSING state" {
        $script:FakeTasks = @(New-Task -Path '\GoneVendor\' -Name 'Helper' `
            -Triggers @(New-Trigger 'MSFT_TaskLogonTrigger') -Actions @(New-Exec 'C:\PulseNoSuchVendor\helper.exe'))
        @(Get-AllStartupItems | Where-Object { $_.Type -eq 'Task' }).Count | Should -Be 1
        $Row = @(Get-StartupReportData | Where-Object { $_.Type -eq 'Task' })[0]
        $Row.Id | Should -Be 'Task|||\GoneVendor\|||Helper'
        $Row.TargetPresent | Should -BeFalse
    }

    It "is found again by its encoded id, which is how a toggle locates it" {
        $script:FakeTasks = @(New-Task -Path '\Vendor\' -Name 'Helper' `
            -Triggers @(New-Trigger 'MSFT_TaskLogonTrigger') -Actions @(New-Exec 'C:\V\h.exe'))
        $Found = Resolve-StartupItemByEncodedId -EncodedId 'Task|||\Vendor\|||Helper'
        $Found | Should -Not -BeNullOrEmpty
        $Found.Type | Should -Be 'Task'
    }
}

Describe "Disabling and enabling a startup task" {

    BeforeEach {
        Reset-TestState
        $script:Calls = New-Object System.Collections.ArrayList
        Mock Set-PulseScheduledTaskState { [void]$script:Calls.Add("$TaskPath|$TaskName|$Enabled") }
        Mock Move-Item { }
        Mock Remove-ItemProperty { }
    }

    It "disables through Task Scheduler, never through the Run-key or folder branches" {
        <#
            THE BRANCH ORDER IS THE SAFETY PROPERTY. The folder branch
            MOVES $Item.Command, and a task's Command is a command line. A
            task that fell through to it would try to move a string.
        #>
        $Task = [PSCustomObject]@{ Type = 'Task'; Hive = ''; RegPath = '\Vendor\'; Name = 'Helper'
                                   Command = '"C:\V\h.exe"'; Enabled = $true }
        Disable-StartupItem -Item $Task
        @($script:Calls) | Should -Be @('\Vendor\|Helper|False')
        Should -Invoke Move-Item -Times 0
        Should -Invoke Remove-ItemProperty -Times 0
    }

    It "enables through Task Scheduler, never through the restore-target logic" {
        $Task = [PSCustomObject]@{ Type = 'Task'; Hive = ''; RegPath = '\Vendor\'; Name = 'Helper'
                                   Command = '"C:\V\h.exe"'; Enabled = $false }
        Enable-StartupItem -Item $Task
        @($script:Calls) | Should -Be @('\Vendor\|Helper|True')
        Should -Invoke Move-Item -Times 0
    }

    It "changes nothing under -WhatIf" {
        $Task = [PSCustomObject]@{ Type = 'Task'; Hive = ''; RegPath = '\Vendor\'; Name = 'Helper'
                                   Command = '"C:\V\h.exe"'; Enabled = $true }
        $Script:DryRun = $true
        try { Disable-StartupItem -Item $Task } finally { $Script:DryRun = $false }
        @($script:Calls).Count | Should -Be 0
    }
}

# ============================================================
#  MEASURED BOOT DELAYS  (v10.13)
#
#  The field names in these fixtures - BootTime, DegradationTime, Path,
#  Name - were read from the Microsoft-Windows-Diagnostics-Performance
#  provider manifest on a real machine. The log itself needs
#  administrator to read, so the events are fixtures; the SCHEMA is not
#  invented.
# ============================================================
Describe "Boot performance data" {

    BeforeAll {
        function script:New-BootEventXml([hashtable]$Data) {
            $Fields = ($Data.GetEnumerator() | ForEach-Object {
                "<Data Name='$($_.Key)'>$([System.Security.SecurityElement]::Escape([string]$_.Value))</Data>"
            }) -join ''
            return "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><EventID>0</EventID></System><EventData>$Fields</EventData></Event>"
        }
        function script:New-BootEvent([int]$Id, [datetime]$When, [hashtable]$Data) {
            [PSCustomObject]@{ Id = $Id; TimeCreated = $When; Xml = (New-BootEventXml $Data) }
        }
    }

    BeforeEach {
        Reset-TestState
        $script:FakeBootEvents = @()
        Mock Read-BootPerformanceEvents { $script:FakeBootEvents }
    }

    It "reads EventData by NAME, so a reordered schema cannot shift the values" {
        $Data = ConvertFrom-BootEventXml -Xml (New-BootEventXml @{ DegradationTime = '3200'; Path = 'C:\V\a.exe'; Name = 'a.exe' })
        $Data['DegradationTime'] | Should -Be '3200'
        $Data['Path'] | Should -Be 'C:\V\a.exe'
    }

    It "survives XML that is not an event at all" {
        { ConvertFrom-BootEventXml -Xml 'not xml <' } | Should -Not -Throw
        (ConvertFrom-BootEventXml -Xml 'not xml <').Count | Should -Be 0
    }

    It "reports an unreadable log as UNREADABLE, and never queries it" {
        <#
            MEASURED: unelevated, querying this log does not fail - it
            answers "no events were found", which is indistinguishable from
            a healthy machine. So access is established first, and the query
            is not even attempted without it.
        #>
        Mock Get-BootPerformanceLogState { 'needs-admin' }
        $Boot = Get-BootPerformanceData
        $Boot.Available | Should -BeFalse
        $Boot.Reason | Should -Be 'needs-admin'
        Should -Invoke Read-BootPerformanceEvents -Times 0
    }

    It "reports a disabled log as disabled" {
        Mock Get-BootPerformanceLogState { 'disabled' }
        (Get-BootPerformanceData).Reason | Should -Be 'disabled'
    }

    It "summarises boots and per-application delays" {
        Mock Get-BootPerformanceLogState { 'ok' }
        $Now = Get-Date
        $script:FakeBootEvents = @(
            (New-BootEvent 100 $Now.AddDays(-1) @{ BootTime = '42000' }),
            (New-BootEvent 100 $Now.AddDays(-3) @{ BootTime = '38000' }),
            (New-BootEvent 101 $Now.AddDays(-1) @{ Name = 'Steam.exe'; Path = 'C:\Program Files (x86)\Steam\steam.exe'; DegradationTime = '3200'; TotalTime = '5100' }),
            (New-BootEvent 101 $Now.AddDays(-3) @{ Name = 'Steam.exe'; Path = 'C:\Program Files (x86)\Steam\steam.exe'; DegradationTime = '4400'; TotalTime = '6000' })
        )
        $Boot = Get-BootPerformanceData
        $Boot.Available | Should -BeTrue
        $Boot.LastBootMs | Should -Be 42000
        $Boot.AverageBootMs | Should -Be 40000
        $Boot.Boots | Should -Be 2
        @($Boot.Apps).Count | Should -Be 1
        $Boot.Apps[0].AverageDelayMs | Should -Be 3800
        $Boot.Apps[0].MaxDelayMs | Should -Be 4400
        $Boot.Apps[0].Count | Should -Be 2
    }
}

Describe "Matching a boot delay to a startup entry" {

    BeforeEach { Reset-TestState }

    It "matches by path" {
        $Apps = @([PSCustomObject]@{ Path = 'C:\Program Files (x86)\Steam\steam.exe'; Name = 'steam.exe'; AverageDelayMs = 3800 })
        $Item = [PSCustomObject]@{ Type = 'Registry'; Command = '"C:\Program Files (x86)\Steam\steam.exe" -silent' }
        (Find-StartupBootDelay -Item $Item -Apps $Apps).AverageDelayMs | Should -Be 3800
    }

    It "matches a device-path spelling of the same file" {
        $Apps = @([PSCustomObject]@{ Path = '\Device\HarddiskVolume3\Program Files\Vendor\app.exe'; Name = 'app.exe'; AverageDelayMs = 1200 })
        $Item = [PSCustomObject]@{ Type = 'Registry'; Command = '"C:\Program Files\Vendor\app.exe"' }
        Find-StartupBootDelay -Item $Item -Apps $Apps | Should -Not -BeNullOrEmpty
    }

    It "falls back to the filename only when exactly one application has it" {
        $One = @([PSCustomObject]@{ Path = ''; Name = 'uniqueapp.exe'; AverageDelayMs = 900 })
        $Item = [PSCustomObject]@{ Type = 'Registry'; Command = 'C:\Somewhere\UniqueApp.exe' }
        Find-StartupBootDelay -Item $Item -Apps $One | Should -Not -BeNullOrEmpty

        $Two = @(
            [PSCustomObject]@{ Path = ''; Name = 'uniqueapp.exe'; AverageDelayMs = 900 },
            [PSCustomObject]@{ Path = ''; Name = 'uniqueapp.exe'; AverageDelayMs = 100 }
        )
        Find-StartupBootDelay -Item $Item -Apps $Two | Should -BeNullOrEmpty
    }

    It "never lets two different Update.exe files answer for each other" {
        $Apps = @([PSCustomObject]@{ Path = 'C:\Users\x\AppData\Local\Slack\Update.exe'; Name = 'Update.exe'; AverageDelayMs = 5000 })
        $Item = [PSCustomObject]@{ Type = 'Registry'; Command = '"C:\Users\x\AppData\Local\Discord\Update.exe" --processStart Discord.exe' }
        Find-StartupBootDelay -Item $Item -Apps $Apps | Should -BeNullOrEmpty
    }

    It "never matches a bare host command" {
        $Apps = @([PSCustomObject]@{ Path = ''; Name = 'rundll32.exe'; AverageDelayMs = 5000 })
        $Item = [PSCustomObject]@{ Type = 'Registry'; Command = 'rundll32.exe C:\V\thing.dll,Entry' }
        Find-StartupBootDelay -Item $Item -Apps $Apps | Should -BeNullOrEmpty
    }

    It "maps a measured delay onto the badge scale" {
        Get-MeasuredBootImpact -DelayMs 3000 | Should -Be 'High'
        Get-MeasuredBootImpact -DelayMs 2999 | Should -Be 'Medium'
        Get-MeasuredBootImpact -DelayMs 1000 | Should -Be 'Medium'
        Get-MeasuredBootImpact -DelayMs 999 | Should -Be 'Low'
    }
}

Describe "Get-StartupReportData carries the measurement" {

    BeforeEach { Reset-TestState }

    It "replaces the heuristic impact with the measured one, and says so" {
        Set-ItemProperty -Path $script:UserRunKey -Name "Steam" -Value '"C:\Program Files (x86)\Steam\steam.exe" -silent' -Force
        Set-ItemProperty -Path $script:UserRunKey -Name "Unmeasured" -Value '"C:\Vendor\quiet.exe"' -Force
        $Boot = [PSCustomObject]@{
            Available = $true; Reason = 'ok'; LastBootMs = 42000; AverageBootMs = 40000; Boots = 2
            Apps = @([PSCustomObject]@{ Path = 'C:\Program Files (x86)\Steam\steam.exe'; Name = 'steam.exe'
                                        Count = 2; AverageDelayMs = 3800; MaxDelayMs = 4400 })
        }
        $Rows = @(Get-StartupReportData -Boot $Boot)
        $Steam = @($Rows | Where-Object { $_.Name -eq 'Steam' })[0]
        $Steam.ImpactMeasured | Should -BeTrue
        $Steam.BootDelayMs | Should -Be 3800
        $Steam.BootDelayMaxMs | Should -Be 4400
        $Steam.BootDelaySamples | Should -Be 2
        $Steam.Impact | Should -Be 'High'

        $Quiet = @($Rows | Where-Object { $_.Name -eq 'Unmeasured' })[0]
        $Quiet.ImpactMeasured | Should -BeFalse
        $Quiet.BootDelayMs | Should -BeNullOrEmpty
    }

    It "keeps every heuristic badge when the log could not be read" {
        Set-ItemProperty -Path $script:UserRunKey -Name "Steam" -Value '"C:\Program Files (x86)\Steam\steam.exe" -silent' -Force
        $Boot = [PSCustomObject]@{ Available = $false; Reason = 'needs-admin'; Apps = @() }
        $Steam = @(Get-StartupReportData -Boot $Boot | Where-Object { $_.Name -eq 'Steam' })[0]
        $Steam.ImpactMeasured | Should -BeFalse
        $Steam.Impact | Should -Be 'High' -Because "that is the rules table's answer for Steam"
    }
}
