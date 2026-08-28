#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
    Pester coverage for the v10.5 process termination guard
    (04-SoftwareEngine.ps1).

.DESCRIPTION
    WHY THIS SUITE EXISTS AT ALL. Windows will not replace a file that is
    open for execution, so an update applied over a running application
    either fails outright or half-applies. Detecting and closing the target
    app first is therefore a correctness measure. But the mechanism that
    fixes that problem is one that TERMINATES PROCESSES, and a termination
    guard that matches too eagerly does not produce a wrong answer - it
    produces the user's unsaved work, gone, with no undo and no error.

    So every test below is about the SAME question from a different angle:
    does this match exactly the app it was asked about, and nothing else?

    THE BUG THAT MOTIVATED MOST OF THEM, reproduced in
    "a single match key must not degrade into substring matching". The
    first cut built the app's names into a HashSet[string] and returned it.
    PowerShell ENUMERATES a collection on return, so a set holding ONE key
    came back as a bare [string] - and the caller's `$Keys.Contains($x)`
    silently stopped being set membership and became String.Contains.
    Substring matching, plus the fact that an unreadable ProductName
    compares as "" and "anything".Contains("") is True, meant the guard
    matched 107 of the 235 processes on the development machine for an app
    that does not exist. Nothing threw. The dry-run transcript was the only
    thing that revealed it.

    Two structural lessons are pinned here so it cannot come back:
      * comparison goes through Test-AppKeyMatch, which validates BOTH ends
        and can only ever test equality; and
      * an empty or too-short candidate is never a match, at any layer.

.NOTES
    Run:  Invoke-Pester -Path tests\backend
#>

BeforeAll {
    $script:RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:ModuleDir = Join-Path $script:RepoRoot "src\backend\modules"

    . (Join-Path $script:ModuleDir "00-Foundation.ps1")
    . (Join-Path $script:ModuleDir "01-Catalogs.ps1")
    . (Join-Path $script:ModuleDir "04-SoftwareEngine.ps1")

    # A synthetic process table. Real Get-Process output is a property of
    # whatever happens to be running on the machine, which is the one thing
    # a regression suite must not depend on - the development machine had
    # Steam and VS Code open, the CI runner has neither, and "did this
    # match?" would then mean something different in each place.
    #
    # Shapes chosen to cover every rule and every trap:
    #   firefox         install-directory match, nothing else lines up
    #   Code            ProductName match ("Visual Studio Code")
    #   steamwebhelper  curated LockProcessMap match, name resembles nothing
    #   wallpaper64     lives UNDER Steam's root but is not Steam
    #   explorer        matches by name and is denylisted
    #   svchost         no readable metadata at all - the "" trap
    #   notepad         matches nothing, and must stay that way
    function New-FakeProc {
        param($Name, $Id, $Path = "", $Product = "", $Company = "")
        return [PSCustomObject]@{
            Name = $Name; Id = $Id; Path = $Path
            Product = $Product; Company = $Company; Process = $null
        }
    }

    $script:Snapshot = @(
        New-FakeProc 'firefox' 1001 'C:\Program Files\Mozilla Firefox\firefox.exe' '' 'Mozilla'
        New-FakeProc 'Code' 1002 'C:\Users\x\AppData\Local\Programs\Microsoft VS Code\Code.exe' 'Visual Studio Code' 'Microsoft Corporation'
        New-FakeProc 'steam' 1003 'C:\Program Files (x86)\Steam\steam.exe' 'Steam' 'Valve Corporation'
        New-FakeProc 'steamwebhelper' 1004 'C:\Program Files (x86)\Steam\bin\cef\steamwebhelper.exe' '' 'Valve Corporation'
        New-FakeProc 'wallpaper64' 1005 'C:\Program Files (x86)\Steam\steamapps\common\wallpaper_engine\wallpaper64.exe' 'Wallpaper Engine' 'Kristjan Skutta'
        New-FakeProc 'explorer' 1006 'C:\Windows\explorer.exe' 'Windows Explorer' 'Microsoft Corporation'
        New-FakeProc 'svchost' 1007 '' '' ''
        New-FakeProc 'notepad' 1008 'C:\Windows\System32\notepad.exe' 'Notepad' 'Microsoft Corporation'
    )

    function Get-MatchNames {
        param($AppId, $AppName)
        return @(Resolve-AppProcesses -AppId $AppId -AppName $AppName `
                    -Snapshot $script:Snapshot |
                 ForEach-Object { $_.Name } | Sort-Object)
    }
}

Describe "ConvertTo-ProcessMatchKey" {
    It "reduces the three spellings of one app to one key" {
        # The winget id, the ARP display name and the executable's
        # ProductName differ in PUNCTUATION and case, which is exactly what
        # a raw string comparison would be answering questions about.
        $keys = @('Visual Studio Code', 'visual-studio-code',
                  'VisualStudioCode', 'Visual  Studio  Code') |
                ForEach-Object { ConvertTo-ProcessMatchKey $_ }
        ($keys | Select-Object -Unique).Count | Should -Be 1
        $keys[0] | Should -Be 'visualstudiocode'
    }

    It "maps blank input to a blank key rather than throwing" {
        foreach ($blank in @($null, '', '   ', '---')) {
            ConvertTo-ProcessMatchKey $blank | Should -Be ''
        }
    }
}

Describe "Get-AppProcessMatchKeys" {
    It "offers the display name, the id, and the id's product segment" {
        $keys = Get-AppProcessMatchKeys -AppId 'Mozilla.Firefox' -AppName 'Mozilla Firefox'
        $keys | Should -Contain 'mozillafirefox'
        $keys | Should -Contain 'firefox'
    }

    It "never offers the publisher segment on its own" {
        # "Mozilla" would match Thunderbird; "Microsoft" would match a
        # third of the machine.
        $keys = Get-AppProcessMatchKeys -AppId 'Mozilla.Firefox' -AppName 'Mozilla Firefox'
        $keys | Should -Not -Contain 'mozilla'
    }

    It "drops candidates too short to be anything but a coincidence" {
        # Git.Git -> "git" is the process name of every embedded git helper
        # any application ships.
        $keys = Get-AppProcessMatchKeys -AppId 'Git.Git' -AppName 'Git'
        $keys | Should -Not -Contain 'git'
    }

    It "survives PowerShell's return-value enumeration as an array" {
        # THE REGRESSION. A single-key collection returned from a function
        # is unrolled by PowerShell; if that unrolling reaches the caller,
        # membership silently becomes String.Contains. Asserting on the
        # returned TYPE is what pins the `, ([string[]]...)` idiom in place.
        $single = Get-AppProcessMatchKeys -AppId 'NoSuch.App' -AppName 'No Such App'
        $single.Count | Should -Be 1
        $single -is [array] | Should -BeTrue
    }
}

Describe "Test-AppKeyMatch" {
    It "matches only on equality, never on containment" {
        $keys = @('visualstudiocode')
        Test-AppKeyMatch -Keys $keys -Candidate 'Visual Studio Code' | Should -BeTrue
        # A substring rule would match all three of these, and killing
        # "VS Code Installer Helper" while updating VS Code is precisely
        # the mistake this guard cannot afford.
        Test-AppKeyMatch -Keys $keys -Candidate 'Visual Studio Code Installer Helper' | Should -BeFalse
        Test-AppKeyMatch -Keys $keys -Candidate 'code' | Should -BeFalse
        Test-AppKeyMatch -Keys $keys -Candidate 'studio' | Should -BeFalse
    }

    It "never matches an empty candidate" {
        # An unreadable ProductName IS the empty string, and roughly half
        # the process table has one.
        foreach ($blank in @($null, '', '   ')) {
            Test-AppKeyMatch -Keys @('firefox') -Candidate $blank | Should -BeFalse
        }
    }

    It "never matches against an empty key set" {
        Test-AppKeyMatch -Keys @() -Candidate 'firefox' | Should -BeFalse
        Test-AppKeyMatch -Keys $null -Candidate 'firefox' | Should -BeFalse
    }
}

Describe "Resolve-AppProcesses" {
    It "finds an app by its install directory" {
        Get-MatchNames 'Mozilla.Firefox' 'Mozilla Firefox' | Should -Be @('firefox')
    }

    It "finds an app by its executable's ProductName" {
        # The process is named "Code"; nothing about the winget id or the
        # display name equals that, so ProductName is the only rule that
        # can see it.
        Get-MatchNames 'Microsoft.VisualStudioCode' 'Microsoft Visual Studio Code' |
            Should -Be @('Code')
    }

    It "honours the curated LockProcessMap for names that resemble nothing" {
        # steamwebhelper is not derivable from "Valve.Steam" or "Steam" by
        # any rule - a human wrote it down, and that is the layer's job.
        Get-MatchNames 'Valve.Steam' 'Steam' | Should -Be @('steam', 'steamwebhelper')
    }

    It "does not claim a third-party app that merely lives under the target's root" {
        # Steam installs every game under Steam\steamapps\common\<game>\.
        # An ancestor-folder rule made "update Steam" resolve to the user's
        # RUNNING GAME; only the LEAF directory is consulted.
        Get-MatchNames 'Valve.Steam' 'Steam' | Should -Not -Contain 'wallpaper64'
    }

    It "returns nothing at all for an app that is not running" {
        Get-MatchNames 'NoSuch.App' 'No Such App' | Should -BeNullOrEmpty
        Get-MatchNames 'Some.Application' 'Some Application' | Should -BeNullOrEmpty
    }

    It "never returns a process with no readable metadata" {
        # svchost has no path, no product and no company - every field it
        # would be compared on is "". Before Test-AppKeyMatch it matched
        # everything.
        foreach ($id in @('NoSuch.App', 'Mozilla.Firefox', 'Valve.Steam')) {
            Get-MatchNames $id 'Whatever' | Should -Not -Contain 'svchost'
        }
    }

    It "refuses a denylisted process even when a rule matched it" {
        # "Explorer.Explorer" resolves to the key "explorer", which is the
        # process's actual name - the match is real and the refusal is the
        # denylist doing its job.
        Get-MatchNames 'Explorer.Explorer' 'Explorer' | Should -BeNullOrEmpty
    }
}

Describe "Test-ProcessIsProtected" {
    It "protects the OS, the shell, and Pulse's own process tree" {
        foreach ($name in @('svchost', 'csrss', 'lsass', 'explorer',
                            'python', 'powershell', 'pwsh', 'winget')) {
            Test-ProcessIsProtected $name | Should -BeTrue -Because "$name must never be terminated"
        }
    }

    It "treats an empty process name as protected" {
        # Fail closed: a process this guard cannot name is one it cannot
        # justify killing.
        Test-ProcessIsProtected '' | Should -BeTrue
    }

    It "compares on the normalised name, so punctuation cannot slip past" {
        Test-ProcessIsProtected 'Explorer' | Should -BeTrue
        Test-ProcessIsProtected 'EXPLORER' | Should -BeTrue
    }

    It "leaves ordinary applications alone" {
        foreach ($name in @('firefox', 'Code', 'steam', 'notepad')) {
            Test-ProcessIsProtected $name | Should -BeFalse
        }
    }
}

Describe "Stop-AppProcesses" {
    It "does nothing, and says nothing, when the app is not running" {
        Stop-AppProcesses -AppId 'NoSuch.App' -AppName 'No Such App' `
            -Snapshot $script:Snapshot | Should -Be 0
    }

    It "reports how many processes it acted on" {
        $Script:DryRun = $true
        try {
            Stop-AppProcesses -AppId 'Valve.Steam' -AppName 'Steam' `
                -Snapshot $script:Snapshot | Should -Be 2
        } finally {
            $Script:DryRun = $false
        }
    }

    It "changes nothing in dry-run mode" {
        # Invoke-Mutation logs [WHATIF] and returns without acting, and the
        # settle delay - which exists to let a REAL kill release its file
        # lock - must be skipped with it.
        $Script:DryRun = $true
        try {
            $before = (Get-Process -Id $PID).Id
            [void](Stop-AppProcesses -AppId 'Valve.Steam' -AppName 'Steam' `
                    -Snapshot $script:Snapshot)
            (Get-Process -Id $before -ErrorAction SilentlyContinue) |
                Should -Not -BeNullOrEmpty
        } finally {
            $Script:DryRun = $false
        }
    }
}

Describe "Get-RunningProcessSnapshot" {
    It "reads the real process table without throwing" {
        # Path and MainModule are unreadable for protected and cross-bitness
        # processes, and the property access THROWS rather than returning
        # null. One inaccessible process must degrade to a name-only entry,
        # never abort the snapshot and leave the guard blind.
        $snap = @(Get-RunningProcessSnapshot)
        $snap.Count | Should -BeGreaterThan 0
        ($snap | Where-Object { -not $_.Name }).Count | Should -Be 0
    }

    It "always finds the process running this test" {
        $me = (Get-Process -Id $PID).ProcessName
        @(Get-RunningProcessSnapshot | Where-Object { $_.Name -eq $me }).Count |
            Should -BeGreaterThan 0
    }
}
