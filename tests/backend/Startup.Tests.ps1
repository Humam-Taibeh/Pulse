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
