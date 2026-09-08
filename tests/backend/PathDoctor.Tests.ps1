#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
    Pester coverage for the PATH scan (03-Environment.ps1):
    Get-PathEntryReport and Write-PathScanReport.

.DESCRIPTION
    THE DOCTOR MUST SURVIVE ITS OWN PATIENT. A PATH entry is not a
    validated path — it is a string an installer or a person wrote into a
    semicolon-separated list, and Windows stores whatever it is given. An
    entry containing '|', '<' or '>' is therefore perfectly possible, and
    Test-Path does not return $false for one: it THROWS
    ArgumentException("Illegal characters in path").

    core.ps1 sets $ErrorActionPreference = "Stop", so that exception used
    to unwind the entire task. The GUI's verdict became
    "##PULSE##ERROR|Illegal characters in path." and the user got no report
    at all — the scan crashed on precisely the entry it exists to find, and
    the one line that would have explained the machine's PATH was the line
    that killed it.

    That is the defect these tests pin, and it is invisible on a healthy
    machine: every developer box has a well-formed PATH, so the crash only
    ever reached the users who most needed the report.

    Nothing here writes to the PATH, to the registry or to the environment
    — Get-PathEntryReport is read-only by construction, and the malformed
    entry is injected by mocking Test-Path rather than by editing a real
    hive (see the note in "survives an entry Test-Path refuses to parse").

.NOTES
    Run:  Invoke-Pester -Path tests\backend
#>

BeforeAll {
    $script:RepoRoot  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:ModuleDir = Join-Path $script:RepoRoot "src\backend\modules"
    . (Join-Path $script:ModuleDir "00-Foundation.ps1")
    # 02-Safety supplies New-SystemRestorePoint, which the sanitizer calls
    # before it writes. Pester's Mock refuses to replace a command that
    # does not exist, so the module has to be loaded even though every
    # test here mocks it out.
    . (Join-Path $script:ModuleDir "02-Safety.ps1")
    . (Join-Path $script:ModuleDir "03-Environment.ps1")

    # The scan writes findings through Write-TaggedLine. Capturing them is
    # the only way to assert on how an entry is CLASSIFIED, which is the
    # half of the contract the returned counts do not carry.
    function script:Capture-Scan {
        param([scriptblock]$Body)
        $lines = & $Body 6>&1 | Out-String -Stream
        return @($lines | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
}

Describe "Get-PathEntryReport" {

    It "reads the real PATH without throwing" {
        # The baseline the crash used to break: on a well-formed machine
        # this always passed, which is exactly why the defect shipped.
        { Get-PathEntryReport } | Should -Not -Throw
    }

    It "reports every entry with the full classification shape" {
        $entries = @(Get-PathEntryReport)
        $entries.Count | Should -BeGreaterThan 0 -Because "this machine has a PATH"
        foreach ($entry in $entries) {
            $entry.PSObject.Properties.Name | Should -Contain 'Scope'
            $entry.PSObject.Properties.Name | Should -Contain 'Raw'
            $entry.PSObject.Properties.Name | Should -Contain 'Path'
            $entry.PSObject.Properties.Name | Should -Contain 'Exists'
            $entry.PSObject.Properties.Name | Should -Contain 'Valid'
            $entry.PSObject.Properties.Name | Should -Contain 'Duplicate'
            $entry.Scope | Should -BeIn @('Machine', 'User')
        }
    }

    It "reads BOTH scopes from the registry, not the flattened process copy" {
        # $env:Path cannot tell machine from user and carries anything a
        # parent shell injected, so a report built from it describes this
        # process rather than the machine the user can edit.
        $scopes = @(Get-PathEntryReport | Select-Object -ExpandProperty Scope -Unique)
        $scopes | Should -Contain 'Machine'
    }

    It "survives an entry Test-Path refuses to parse, and marks it invalid" {
        # THE REGRESSION. Injected by mocking Test-Path rather than by
        # writing a malformed entry into the real user PATH: the defect is
        # "the probe threw", and a mock reproduces that exactly while
        # leaving the developer's environment untouched.
        #
        # The throw is aimed by CALL COUNT, not by -ParameterFilter. A
        # filter is the obvious way to write this and it silently does not
        # work: Pester evaluates the filter scriptblock in its own scope,
        # so the $victim captured from here is not the $victim it tests,
        # and the mock fired for all twenty-nine entries instead of one —
        # a green-looking mock that tested nothing it claimed to.
        #
        # One throw, on the first probe, leaves the remaining entries to
        # be reported normally, which is what makes "a single bad entry
        # does not cost the other twenty-eight" an assertable claim.
        $all = @(Get-PathEntryReport)
        $all.Count | Should -BeGreaterThan 1 -Because "the test needs a survivor to check"
        $victim = $all[0].Path

        $script:probes = 0
        Mock Test-Path {
            $script:probes++
            if ($script:probes -eq 1) {
                throw [System.ArgumentException]::new("Illegal characters in path.")
            }
            return $true
        }

        $script:report = $null
        { $script:report = @(Get-PathEntryReport) } | Should -Not -Throw `
            -Because "a malformed entry is the doctor's subject, not its cause of death"

        $report = @($script:report)
        $report.Count | Should -Be $all.Count -Because "one bad entry must not truncate the report"

        $bad = @($report | Where-Object { -not $_.Valid })
        $bad.Count | Should -Be 1
        $bad[0].Path   | Should -Be $victim
        $bad[0].Exists | Should -BeFalse -Because "a path that cannot be parsed cannot be confirmed to exist"

        $survivors = @($report | Where-Object { $_.Valid })
        $survivors.Count | Should -Be ($all.Count - 1)
    }
}

Describe "Write-PathScanReport" {

    It "counts a malformed entry separately from a dead one" {
        Mock Get-PathEntryReport {
            @(
                [PSCustomObject]@{ Scope='Machine'; Raw='C:\Windows\System32'; Path='C:\Windows\System32'; Exists=$true;  Valid=$true;  Duplicate=$false }
                [PSCustomObject]@{ Scope='Machine'; Raw='C:\gone';             Path='C:\gone';             Exists=$false; Valid=$true;  Duplicate=$false }
                [PSCustomObject]@{ Scope='User';    Raw='C:\bad|entry';        Path='C:\bad|entry';        Exists=$false; Valid=$false; Duplicate=$false }
                [PSCustomObject]@{ Scope='User';    Raw='C:\Windows\System32'; Path='C:\Windows\System32'; Exists=$true;  Valid=$true;  Duplicate=$true }
            )
        }
        $result = Write-PathScanReport
        $result.Total     | Should -Be 4
        $result.Dead      | Should -Be 1 -Because "the malformed entry must not also be counted as dead"
        $result.Invalid   | Should -Be 1
        $result.Duplicate | Should -Be 1
    }

    It "tags a malformed entry [INVALID], not [DEAD]" {
        # "the folder does not exist" invites the user to go looking for a
        # folder. That is the wrong advice for a string which could never
        # have named one, so the two findings stay distinct.
        Mock Get-PathEntryReport {
            @([PSCustomObject]@{ Scope='User'; Raw='C:\bad|entry'; Path='C:\bad|entry'; Exists=$false; Valid=$false; Duplicate=$false })
        }
        $lines = Capture-Scan { Write-PathScanReport | Out-Null }
        ($lines | Where-Object { $_ -like '`[INVALID`]*' }).Count | Should -Be 1
        ($lines | Where-Object { $_ -like '`[DEAD`]*' }).Count    | Should -Be 0
        ($lines -join "`n") | Should -Match 'bad\|entry'
    }

    It "still reports a wholly clean PATH as clean" {
        Mock Get-PathEntryReport {
            @([PSCustomObject]@{ Scope='Machine'; Raw='C:\Windows\System32'; Path='C:\Windows\System32'; Exists=$true; Valid=$true; Duplicate=$false })
        }
        $lines = Capture-Scan { Write-PathScanReport | Out-Null }
        ($lines | Where-Object { $_ -like '`[OK`]*every entry resolves*' }).Count | Should -Be 1
    }

    It "never mutates the PATH it is reporting on" {
        # A folder that is merely offline - a network share, an unmounted
        # volume - looks exactly like a dead one, so the scan reports and
        # leaves the edit to the user. Asserted against the source because
        # the guarantee is the ABSENCE of a call.
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "03-Environment.ps1") -Raw
        $scan = $source.Substring($source.IndexOf("function Write-PathScanReport"))
        $scan = $scan.Substring(0, $scan.IndexOf("`nfunction "))
        foreach ($mutation in @('SetEnvironmentVariable("Path"', 'Remove-ItemProperty', 'Set-ItemProperty')) {
            $scan | Should -Not -BeLike "*$mutation*" -Because "the PATH scan is read-only"
        }
    }
}

Describe "Get-PathCommandConflicts" {

    It "says nothing about a PATH where every tool appears once" {
        $entries = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Windows\System32'; Path='C:\Windows\System32'; Exists=$true; Valid=$true; Duplicate=$false }
        )
        # One directory cannot shadow anything, so this must be empty
        # WITHOUT probing the disk at all.
        @(Get-PathCommandConflicts -Entries $entries).Count | Should -Be 0
    }

    It "reports the winner and the shadowed copy, in PATH order" {
        # THE DEFECT THIS EXISTS FOR: two Pythons, and `python --version`
        # answers with the FIRST one. Nothing in Windows says so, and the
        # user reads it as a broken install of the one they just put on.
        Mock Test-Path {
            param($LiteralPath)
            return ($LiteralPath -like '*python.exe')
        }
        $entries = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Python311'; Path='C:\Python311'; Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='User';    Raw='C:\Python313'; Path='C:\Python313'; Exists=$true; Valid=$true; Duplicate=$false }
        )
        $conflicts = @(Get-PathCommandConflicts -Entries $entries)
        $python = @($conflicts | Where-Object { $_.Command -eq 'python' })
        $python.Count      | Should -Be 1
        $python[0].Winner  | Should -Be 'C:\Python311' -Because "the earliest entry wins, and that is the whole finding"
        $python[0].Count   | Should -Be 2
        @($python[0].Shadowed)[0] | Should -Be 'C:\Python313'
    }

    It "ignores dead, malformed and duplicate entries" {
        # None of the three can answer a command: a dead folder has no
        # files, a malformed string is skipped by Windows, and a duplicate
        # is the same directory already counted. Counting any of them
        # would report a conflict between a directory and itself.
        Mock Test-Path { return $true }
        $entries = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Live';  Path='C:\Live';  Exists=$true;  Valid=$true;  Duplicate=$false }
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Gone';  Path='C:\Gone';  Exists=$false; Valid=$true;  Duplicate=$false }
            [PSCustomObject]@{ Scope='User';    Raw='C:\Bad|x'; Path='C:\Bad|x'; Exists=$false; Valid=$false; Duplicate=$false }
            [PSCustomObject]@{ Scope='User';    Raw='C:\Live';  Path='C:\Live';  Exists=$true;  Valid=$true;  Duplicate=$true }
        )
        # One usable directory remains, so nothing can be shadowed.
        @(Get-PathCommandConflicts -Entries $entries).Count | Should -Be 0
    }

    It "survives a probe that throws, the way the rest of the doctor does" {
        # Same doctrine as Get-PathEntryReport: the entry that breaks the
        # probe is the entry the report exists to describe.
        Mock Test-Path { throw [System.ArgumentException]::new("Illegal characters in path.") }
        $entries = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\A'; Path='C:\A'; Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='User';    Raw='C:\B'; Path='C:\B'; Exists=$true; Valid=$true; Duplicate=$false }
        )
        { Get-PathCommandConflicts -Entries $entries } | Should -Not -Throw
    }
}

Describe "Write-PathScanReport reports a shadowed toolchain" {

    It "tags the winner [CONFLICT] and each loser [SHADOWED]" {
        Mock Get-PathEntryReport {
            @(
                [PSCustomObject]@{ Scope='Machine'; Raw='C:\Python311'; Path='C:\Python311'; Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User';    Raw='C:\Python313'; Path='C:\Python313'; Exists=$true; Valid=$true; Duplicate=$false }
            )
        }
        Mock Get-PathCommandConflicts {
            @([PSCustomObject]@{ Command='python'; Winner='C:\Python311'
                                 Shadowed=@('C:\Python313'); Count=2 })
        }
        $lines = Capture-Scan { Write-PathScanReport | Out-Null }
        ($lines | Where-Object { $_ -like '`[CONFLICT`]*python*' }).Count | Should -Be 1
        ($lines | Where-Object { $_ -like '`[SHADOWED`]*Python313*' }).Count | Should -Be 1
        # A clean structural PATH must NOT then be summarised as clean.
        ($lines | Where-Object { $_ -like '`[OK`]*every entry resolves*' }).Count | Should -Be 0
    }

    It "counts conflicts in the returned summary" {
        Mock Get-PathEntryReport {
            @([PSCustomObject]@{ Scope='Machine'; Raw='C:\A'; Path='C:\A'; Exists=$true; Valid=$true; Duplicate=$false })
        }
        Mock Get-PathCommandConflicts {
            @([PSCustomObject]@{ Command='node'; Winner='C:\A'; Shadowed=@('C:\B'); Count=2 })
        }
        (Write-PathScanReport).Conflict | Should -Be 1
    }
}

Describe "Get-PathPrunePlan" {
    <#
        THE PLAN IS THE SAFETY ARGUMENT, so it is tested on its own rather
        than through the function that applies it. Every case below is a
        decision the sanitizer makes about somebody's real PATH, and the
        expensive direction of being wrong is always the same one:
        removing an entry that was doing its job.
    #>

    It "removes a duplicate, whatever else is true of it" {
        # Safe unconditionally: the first copy already answers everything
        # the second would, so dropping it cannot change what any command
        # resolves to - even for a directory that is offline or missing.
        $plan = @(Get-PathPrunePlan -Entries @(
            [PSCustomObject]@{ Scope='User'; Raw='C:\Tools'; Path='C:\Tools'; Exists=$false; Valid=$true; Duplicate=$true }
        ))
        $plan[0].Action | Should -Be 'remove'
        $plan[0].Verdict | Should -BeLike '*already listed earlier*'
    }

    It "removes a malformed entry, because it has never resolved to anything" {
        $plan = @(Get-PathPrunePlan -Entries @(
            [PSCustomObject]@{ Scope='User'; Raw='C:\bad|entry'; Path='C:\bad|entry'; Exists=$false; Valid=$false; Duplicate=$false }
        ))
        $plan[0].Action | Should -Be 'remove'
    }

    It "KEEPS a dead entry whose volume is not a mounted internal disk" {
        # THE DOCTRINE, PINNED. A folder missing from a drive that is not
        # here looks exactly like rubbish and is not: the entry may be
        # perfectly correct with the volume present. This is the assertion
        # that stops a future "simplify the pruner" from deleting somebody's
        # network toolchain.
        Mock Test-PrunablePathVolume { return $false }
        $plan = @(Get-PathPrunePlan -Entries @(
            [PSCustomObject]@{ Scope='User'; Raw='Z:\Tools'; Path='Z:\Tools'; Exists=$false; Valid=$true; Duplicate=$false }
        ))
        $plan[0].Action  | Should -Be 'keep'
        $plan[0].Verdict | Should -BeLike '*removable, network or not mounted*'
    }

    It "removes a dead entry on a mounted internal disk" {
        Mock Test-PrunablePathVolume { return $true }
        $plan = @(Get-PathPrunePlan -Entries @(
            [PSCustomObject]@{ Scope='User'; Raw='C:\Gone'; Path='C:\Gone'; Exists=$false; Valid=$true; Duplicate=$false }
        ))
        $plan[0].Action | Should -Be 'remove'
    }

    It "never removes an entry that resolves" {
        Mock Test-PrunablePathVolume { return $true }
        $plan = @(Get-PathPrunePlan -Entries @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Windows\System32'; Path='C:\Windows\System32'; Exists=$true; Valid=$true; Duplicate=$false }
        ))
        $plan[0].Action | Should -Be 'keep'
    }

    It "reports EVERY entry, so the kept ones can be shown beside the removed" {
        Mock Test-PrunablePathVolume { return $true }
        $entries = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Windows'; Path='C:\Windows'; Exists=$true;  Valid=$true;  Duplicate=$false }
            [PSCustomObject]@{ Scope='User';    Raw='C:\Gone';    Path='C:\Gone';    Exists=$false; Valid=$true;  Duplicate=$false }
        )
        @(Get-PathPrunePlan -Entries $entries).Count | Should -Be 2
    }
}

Describe "Test-PrunablePathVolume" {

    It "refuses a UNC path outright" {
        # An unreachable share is indistinguishable from a deleted one,
        # and the machine holding the answer is not this one.
        Test-PrunablePathVolume -Path '\\server\share\tools' | Should -BeFalse
    }

    It "refuses a drive letter that is not mounted" {
        # A letter nothing is mounted on. Picked from the end of the
        # alphabet rather than assumed free: the test asserts on a drive
        # this machine genuinely does not have.
        $free = 90..67 | ForEach-Object { [char]$_ } |
                Where-Object { -not (Test-Path "$($_):\") } | Select-Object -First 1
        $free | Should -Not -BeNullOrEmpty -Because "the test needs one absent drive letter"
        Test-PrunablePathVolume -Path "$($free):\Tools" | Should -BeFalse
    }

    It "accepts a folder on the system drive" {
        Test-PrunablePathVolume -Path (Join-Path $env:SystemDrive 'DefinitelyNotHere') | Should -BeTrue
    }

    It "survives a string that is not a path at all" {
        # Handed raw PATH entries, and GetPathRoot throws on some of them.
        { Test-PrunablePathVolume -Path 'C:\bad|entry' } | Should -Not -Throw
    }
}

Describe "Invoke-PathSanitizer" {

    It "changes nothing under -WhatIf" {
        <#
            The strongest form of the guarantee: assert on the ABSENCE of
            a write, by counting the calls that would have made one.

            THE DOOMED ENTRY IS A REAL ONE, taken from this machine's own
            user PATH, and that detail is load-bearing rather than
            convenient. Invoke-PathSanitizer does not trust the plan to
            describe the PATH - it re-reads the live value and drops
            entries BY POSITION, so a plan naming a string the PATH does
            not contain removes nothing and reports zero. A first draft of
            this test mocked the plan with 'C:\Gone', got Removed = 0, and
            would have passed happily against a sanitizer that had stopped
            working entirely.

            Nothing is written: -WhatIf returns before the backup and
            before the write, which is what the two Should -Invoke counts
            below actually prove.
        #>
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        $victim = @($userPath -split ";" | Where-Object { $_.Trim() } |
                    Select-Object -First 1)[0].Trim()
        $victim | Should -Not -BeNullOrEmpty -Because "the test needs one real user PATH entry"

        Mock Get-PathPrunePlan {
            @([PSCustomObject]@{ Scope='User'; Raw=$victim; Path=$victim
                                 Exists=$false; Valid=$true; Duplicate=$false
                                 Action='remove'; Verdict='gone' })
        }
        Mock New-SystemRestorePoint { }
        Mock Save-PathBackup { return $true }
        Mock Test-IsElevatedSession { return $true }

        $Script:DryRun = $true
        try {
            $result = Invoke-PathSanitizer
            Should -Invoke Save-PathBackup -Times 0 -Because "a dry run must not even write the backup"
            $result.Removed | Should -Be 1 -Because "the simulation still reports what it would have done"
        } finally {
            $Script:DryRun = $false
        }
        # AND THE PATH IS UNTOUCHED. The counts above prove the code did
        # not take the write branch; this proves the variable itself.
        [Environment]::GetEnvironmentVariable("Path", "User") | Should -Be $userPath
    }

    It "matches an entry by position, so a duplicate loses only its second copy" {
        # The reason the write is rebuilt from a split list rather than by
        # removing a substring: with two identical entries, string surgery
        # takes whichever it finds first and can take both.
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "03-Environment.ps1") -Raw
        $body = $source.Substring($source.IndexOf("function Invoke-PathSanitizer"))
        $body | Should -BeLike '*$Kill.Contains($i)*' -Because "positions already claimed must be skipped"
        $body | Should -Not -BeLike '*-replace*' -Because "the PATH is rebuilt, never string-edited"
    }

    It "refuses to write when the backup could not be saved" {
        # "Reversible" is the whole promise of the card. A prune whose
        # backup silently failed is the one case where that promise would
        # be a lie, so the write is abandoned instead.
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "03-Environment.ps1") -Raw
        $body = $source.Substring($source.IndexOf("function Invoke-PathSanitizer"))
        $body | Should -BeLike '*if (-not (Save-PathBackup*) { continue }*'
    }

    It "takes the restore point BEFORE it writes" {
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "03-Environment.ps1") -Raw
        $body = $source.Substring($source.IndexOf("function Invoke-PathSanitizer"))
        $restore = $body.IndexOf("New-SystemRestorePoint")
        $write   = $body.IndexOf("SetEnvironmentVariable")
        $restore | Should -BeGreaterThan 0
        $write   | Should -BeGreaterThan 0
        $restore | Should -BeLessThan $write -Because "a checkpoint taken after the change protects nothing"
    }

    It "leaves the machine PATH alone when the session is not elevated" {
        Mock Get-PathPrunePlan {
            @([PSCustomObject]@{ Scope='Machine'; Raw='C:\Gone'; Path='C:\Gone'
                                 Exists=$false; Valid=$true; Duplicate=$false
                                 Action='remove'; Verdict='gone' })
        }
        Mock New-SystemRestorePoint { }
        Mock Test-IsElevatedSession { return $false }
        Mock Save-PathBackup { return $true }

        $result = Invoke-PathSanitizer
        $result.Removed | Should -Be 0
        Should -Invoke Save-PathBackup -Times 0 -Because "nothing was written, so nothing needed backing up"
    }

    It "reports a clean PATH without taking a restore point" {
        # Nothing to undo means nothing to checkpoint. A restore point per
        # click on a machine with a healthy PATH is noise in the one list
        # a user goes to when something has gone badly wrong.
        Mock Get-PathPrunePlan {
            @([PSCustomObject]@{ Scope='User'; Raw='C:\Windows'; Path='C:\Windows'
                                 Exists=$true; Valid=$true; Duplicate=$false
                                 Action='keep'; Verdict='resolves' })
        }
        Mock New-SystemRestorePoint { }
        $result = Invoke-PathSanitizer
        $result.Removed | Should -Be 0
        Should -Invoke New-SystemRestorePoint -Times 0
    }
}


# ============================================================
#  THE PRIORITY FIX  (v10.12)
#
#  THE SCAN HAS ALWAYS BEEN ABLE TO SAY "you have two Pythons and this is
#  the one that runs". What it could not do was change the answer, so the
#  advice ended at "go and edit an environment variable by hand" - which
#  is the same place the user was before they opened the tool.
#
#  WHAT MAKES THIS SAFE IS THAT IT IS A PERMUTATION. Nothing is removed:
#  the scope's entry list comes out carrying exactly the strings it went
#  in with, in a different order, so every binary that answered a command
#  before still answers it and the worst outcome of a wrong choice is one
#  click to change it back. That property is asserted directly below
#  rather than inferred from the absence of a Remove call.
#
#  AND THE CASE IT REFUSES IS THE INTERESTING ONE. Windows composes the
#  search path as machine-then-user, so a user-scope folder can never
#  overtake a machine-scope one however the user list is sorted. A tool
#  that offered the button anyway would appear to succeed and change
#  nothing, which is worse than not offering it.
# ============================================================
Describe "PathConflictCommands covers the modern toolchains" {

    It "includes the package managers and runtimes people actually double up" {
        # An entry here costs one Test-Path per PATH directory and prints
        # NOTHING unless a second copy exists - which is why this list can
        # grow where $Script:DevToolCatalog cannot. See the note above it.
        foreach ($command in @('pwsh', 'docker', 'bun', 'uv', 'uvx',
                               'pnpm', 'cargo', 'rustup', 'go', 'gofmt', 'deno')) {
            $Script:PathConflictCommands | Should -Contain $command
        }
    }

    It "still carries every command it carried before" {
        # The additions must not have displaced anything: a name dropped
        # from this list is a conflict that silently stops being reported.
        foreach ($command in @('python', 'node', 'npm', 'java', 'javac',
                               'git', 'gcc', 'clang', 'cmake', 'dotnet',
                               'ruby', 'perl', 'php', 'curl', 'ffmpeg')) {
            $Script:PathConflictCommands | Should -Contain $command
        }
    }

    It "names each command once" {
        $unique = @($Script:PathConflictCommands | Select-Object -Unique)
        $unique.Count | Should -Be $Script:PathConflictCommands.Count
    }
}

Describe "Get-PathCommandConflicts reports the scope of each copy" {

    It "carries a Providers list with the scope every copy sits in" {
        # THE FIELD THE PRIORITY FIX IS BUILT ON. Winner/Shadowed are
        # bare strings because the report prints them; the scope is what
        # decides whether a conflict can be fixed by reordering at all.
        Mock Test-Path {
            param($LiteralPath)
            return ($LiteralPath -like '*python.exe')
        }
        $entries = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py311'; Path='C:\Py311'; Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='User';    Raw='C:\Py313'; Path='C:\Py313'; Exists=$true; Valid=$true; Duplicate=$false }
        )
        $python = @(Get-PathCommandConflicts -Entries $entries |
            Where-Object { $_.Command -eq 'python' })[0]
        @($python.Providers).Count | Should -Be 2
        @($python.Providers)[0].Scope | Should -Be 'Machine'
        @($python.Providers)[1].Scope | Should -Be 'User'
        # And the old shape is untouched, because the report still reads it.
        $python.Winner | Should -Be 'C:\Py311'
        @($python.Shadowed)[0] | Should -Be 'C:\Py313'
    }
}

Describe "Get-BinaryVersionLabel" {

    It "reads a version out of a real binary without running it" {
        $exe = Join-Path $env:SystemRoot "System32\notepad.exe"
        if (-not (Test-Path -LiteralPath $exe)) { Set-ItResult -Skipped -Because "notepad is absent" ; return }
        (Get-BinaryVersionLabel -Path $exe) | Should -Not -BeNullOrEmpty
    }

    It "returns an empty string for anything it cannot read" {
        (Get-BinaryVersionLabel -Path 'C:\no\such\file.exe') | Should -Be ''
        (Get-BinaryVersionLabel -Path '') | Should -Be ''
    }

    It "never EXECUTES the file it is labelling" {
        # THE POINT OF THE FUNCTION. The obvious way to tell two Pythons
        # apart is `--version`, and that is the one thing a PATH
        # diagnostic must never do: the binaries it is looking at are, by
        # definition, ones the user did not choose and may not know
        # about. Asserted against the source, because the guarantee is
        # the ABSENCE of a call.
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "03-Environment.ps1") -Raw
        $body = $source.Substring($source.IndexOf("function Get-BinaryVersionLabel"))
        $body = $body.Substring(0, $body.IndexOf("`nfunction "))
        foreach ($execution in @('Start-Process', 'Invoke-Expression', '& $', '&$')) {
            $body | Should -Not -BeLike "*$execution*" -Because "a PATH diagnostic must not run the binaries it finds"
        }
    }
}

Describe "Get-PathToolFamily" {

    It "folds a runtime's commands into one family" {
        # THE WHOLE POINT: python, pip and pip3 are one installed Python,
        # not three findings.
        foreach ($command in @('python', 'python3', 'pip', 'pip3')) {
            (Get-PathToolFamily -Command $command).Key | Should -Be 'python'
        }
        (Get-PathToolFamily -Command 'npm').Key   | Should -Be 'node'
        (Get-PathToolFamily -Command 'javac').Key | Should -Be 'java'
    }

    It "gives anything unlisted a family of its own" {
        # So the list can stay short: a command earns an entry only where
        # its product spreads across more than one PATH directory.
        $family = Get-PathToolFamily -Command 'ffmpeg'
        $family.Key      | Should -Be 'ffmpeg'
        @($family.Commands).Count | Should -Be 1
    }
}

Describe "Test-PathIsInside" {

    It "recognises a directory inside another" {
        Test-PathIsInside -Parent 'C:\Python314' -Child 'C:\Python314\Scripts' | Should -BeTrue
        Test-PathIsInside -Parent 'C:\Python314\' -Child 'C:\Python314\Scripts\' | Should -BeTrue
        Test-PathIsInside -Parent 'C:\Python314' -Child 'C:\Python314' | Should -BeTrue
    }

    It "does NOT let a prefix claim a sibling" {
        # THE BUG THE SEPARATOR PREVENTS, and it is not hypothetical on a
        # machine with two Pythons: without forcing a trailing "\" onto
        # the parent, "C:\Python31" claims "C:\Python314" as its child and
        # two unrelated installations are merged into one option.
        Test-PathIsInside -Parent 'C:\Python31' -Child 'C:\Python314' | Should -BeFalse
        Test-PathIsInside -Parent 'C:\Py' -Child 'C:\Python314' | Should -BeFalse
    }

    It "survives empty input" {
        Test-PathIsInside -Parent '' -Child 'C:\A' | Should -BeFalse
        Test-PathIsInside -Parent 'C:\A' -Child '' | Should -BeFalse
    }
}

Describe "Get-PathInstallations" {

    BeforeAll {
        # TWO PYTHONS, each a root plus a Scripts directory, in the order
        # a real installer writes them (Scripts first - measured on the
        # maintainer's machine, where the machine PATH reads
        # "C:\Python314\Scripts\" then "C:\Python314\").
        function script:TwoPythons {
            @(
                [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314\Scripts'; Path='C:\Py314\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314';         Path='C:\Py314';         Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User';    Raw='C:\Py312\Scripts'; Path='C:\Py312\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User';    Raw='C:\Py312';         Path='C:\Py312';         Exists=$true; Valid=$true; Duplicate=$false }
            )
        }
        #: python.exe in a root, pip.exe in a Scripts - the real layout.
        function script:MockPythonLayout {
            Mock Test-Path {
                param($LiteralPath)
                if ($LiteralPath -like '*\Scripts\pip.exe')  { return $true }
                if ($LiteralPath -like '*\Scripts\pip3.exe') { return $true }
                if ($LiteralPath -like '*\Scripts\*')        { return $false }
                return ($LiteralPath -like '*python.exe')
            }
        }
    }

    It "reports ONE installation per product, not one per command" {
        MockPythonLayout
        $installs = @(Get-PathInstallations -Entries (TwoPythons))
        @($installs).Count | Should -Be 1 -Because "python, pip and pip3 are one family"
        $python = $installs[0]
        $python.Key | Should -Be 'python'
        @($python.Options).Count | Should -Be 2 -Because "there are two Pythons, not four directories"
    }

    It "clusters a root with its Scripts directory" {
        MockPythonLayout
        $python = @(Get-PathInstallations -Entries (TwoPythons))[0]
        $first = @($python.Options)[0]
        @($first.Dirs).Count | Should -Be 2
        @($first.Dirs) | Should -Contain 'C:\Py314'
        @($first.Dirs) | Should -Contain 'C:\Py314\Scripts'
    }

    It "keeps the cluster in PATH order, so a promotion preserves it" {
        MockPythonLayout
        $python = @(Get-PathInstallations -Entries (TwoPythons))[0]
        # Scripts is FIRST in the fixture's PATH, and must stay first.
        @(@($python.Options)[0].Dirs)[0] | Should -Be 'C:\Py314\Scripts'
    }

    It "records every command an installation answers" {
        MockPythonLayout
        $python = @(Get-PathInstallations -Entries (TwoPythons))[0]
        $commands = @(@($python.Options)[0].Commands)
        $commands | Should -Contain 'python'
        $commands | Should -Contain 'pip'
    }

    It "says nothing when a family has only ONE installation" {
        <#
            THE NOISE THIS EXISTS TO REMOVE. C:\Python314 and
            C:\Python314\Scripts are not two Pythons competing - they are
            one Python spread over two directories the way every Python
            is - so a machine with a single install must produce no
            finding at all, even though the command-shaped scan sees
            python in one directory and pip in another.
        #>
        MockPythonLayout
        $single = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314\Scripts'; Path='C:\Py314\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314';         Path='C:\Py314';         Exists=$true; Valid=$true; Duplicate=$false }
        )
        @(Get-PathInstallations -Entries $single).Count | Should -Be 0
    }

    It "keeps a Scripts directory whose parent is NOT on the PATH separate" {
        <#
            A `pip --user` install lands in Roaming\Python\PythonXY\Scripts
            and its parent is not a PATH entry at all, so it provides pip
            and no python and is nobody's subdirectory. Folding it into
            the installation that happens to share its version NUMBER
            would be a guess, and it would be wrong - they are different
            installations.
        #>
        MockPythonLayout
        $entries = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314';           Path='C:\Py314';           Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314\Scripts';   Path='C:\Py314\Scripts';   Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='User';    Raw='C:\Roam\Py314\Scripts'; Path='C:\Roam\Py314\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
        )
        $python = @(Get-PathInstallations -Entries $entries)[0]
        @($python.Options).Count | Should -Be 2
        $orphan = @($python.Options | Where-Object { $_.Root -eq 'C:\Roam\Py314\Scripts' })
        $orphan.Count | Should -Be 1
        @($orphan[0].Dirs).Count | Should -Be 1 -Because "it owns no other directory"
    }
}

Describe "Get-PathInstallPlan" {

    BeforeAll {
        function script:FourDirs {
            @(
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py314\Scripts'; Path='C:\Py314\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py314';         Path='C:\Py314';         Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py312\Scripts'; Path='C:\Py312\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py312';         Path='C:\Py312';         Exists=$true; Valid=$true; Duplicate=$false }
            )
        }
        function script:MockLayout {
            Mock Test-Path {
                param($LiteralPath)
                if ($LiteralPath -like '*\Scripts\pip.exe')  { return $true }
                if ($LiteralPath -like '*\Scripts\pip3.exe') { return $true }
                if ($LiteralPath -like '*\Scripts\*')        { return $false }
                return ($LiteralPath -like '*python.exe')
            }
        }
    }

    It "moves the WHOLE installation, not just the directory named" {
        <#
            THE FAILURE THIS PREVENTS, and the reason the unit is an
            installation: promoting 3.12's python without its Scripts
            leaves `pip` answering from 3.14, which is a machine where
            `pip install` puts packages somewhere `python` cannot import
            them.
        #>
        MockLayout
        $plan = Get-PathInstallPlan -Family 'python' -Directory 'C:\Py312' -Entries (FourDirs)
        $plan.Action | Should -Be 'reorder'
        @($plan.Dirs).Count | Should -Be 2
        # Both of 3.12's directories are now ahead of both of 3.14's.
        $order = @($plan.Order)
        $order[0] | Should -Be 'C:\Py312\Scripts'
        $order[1] | Should -Be 'C:\Py312'
    }

    It "produces a PERMUTATION - every entry survives, none is added" {
        MockLayout
        $entries = FourDirs
        $plan = Get-PathInstallPlan -Family 'python' -Directory 'C:\Py312' -Entries $entries
        $before = @($entries | ForEach-Object { $_.Raw } | Sort-Object)
        $after  = @(@($plan.Order) | Sort-Object)
        $after.Count | Should -Be $before.Count
        (Compare-Object -ReferenceObject $before -DifferenceObject $after -SyncWindow 0) | Should -BeNullOrEmpty
    }

    It "carries a SHORT verdict the GUI can put on the button" {
        # The long reason belongs in a tooltip; the control itself has to
        # say what it will do in two or three words.
        MockLayout
        (Get-PathInstallPlan -Family 'python' -Directory 'C:\Py312' -Entries (FourDirs)).Short |
            Should -Be 'Use this one'
        (Get-PathInstallPlan -Family 'python' -Directory 'C:\Py314' -Entries (FourDirs)).Short |
            Should -Be 'In use'
    }

    It "says there is nothing to do when the installation already wins" {
        MockLayout
        $plan = Get-PathInstallPlan -Family 'python' -Directory 'C:\Py314' -Entries (FourDirs)
        $plan.Action | Should -Be 'none'
        @($plan.Order).Count | Should -Be 0
    }

    It "refuses a directory that is not one of the installations" {
        MockLayout
        $plan = Get-PathInstallPlan -Family 'python' -Directory 'C:\Nowhere' -Entries (FourDirs)
        $plan.Action | Should -Be 'blocked'
    }

    It "REFUSES to promote a user installation over a system one, and says why" {
        <#
            THE CASE REORDERING CANNOT REACH. Windows searches the machine
            PATH before the user PATH, so no ordering of the user list
            will put a user-scope installation in front of a machine-scope
            one. A tool that offered the button anyway would write a
            change, report success, and leave `python --version`
            answering exactly as before.
        #>
        MockLayout
        $entries = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314'; Path='C:\Py314'; Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='User';    Raw='C:\Py312'; Path='C:\Py312'; Exists=$true; Valid=$true; Duplicate=$false }
        )
        $plan = Get-PathInstallPlan -Family 'python' -Directory 'C:\Py312' -Entries $entries
        $plan.Action | Should -Be 'blocked'
        $plan.Short  | Should -Be 'Needs administrator'
        $plan.Reason | Should -BeLike '*system PATH before your user PATH*'
    }

    It "refuses an installation split across BOTH scopes" {
        # No single reorder can move directories that live in two
        # different variables, and splitting an installation between them
        # is not something Pulse will do on the user's behalf.
        #
        # THE SPLIT ONE IS THE CHALLENGER, not the winner, and that
        # detail is the test: an installation that already wins returns
        # "none" before any feasibility question is asked, so pointing
        # this at the leading cluster would pass without ever reaching
        # the branch under test.
        MockLayout
        $entries = @(
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314';         Path='C:\Py314';         Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314\Scripts'; Path='C:\Py314\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py312';         Path='C:\Py312';         Exists=$true; Valid=$true; Duplicate=$false }
            [PSCustomObject]@{ Scope='User';    Raw='C:\Py312\Scripts'; Path='C:\Py312\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
        )
        $plan = Get-PathInstallPlan -Family 'python' -Directory 'C:\Py312' -Entries $entries
        $plan.Action | Should -Be 'blocked'
        $plan.Short  | Should -Be 'Split across scopes'
    }
}

Describe "Set-PathToolPriority" {

    It "changes nothing under -WhatIf" {
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        Mock Get-PathInstallPlan {
            [PSCustomObject]@{ Family='python'; Directory='C:\Py313'
                               Action='reorder'; Scope='User'; Reason='r'; Short='Use this one'
                               Order=@(@($userPath -split ";" | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() }))
                               Dirs=@('C:\Py313') }
        }
        Mock New-SystemRestorePoint { }
        Mock Save-PathBackup { return $true }
        Mock Test-IsElevatedSession { return $true }

        $Script:DryRun = $true
        try {
            $result = Set-PathToolPriority -Family 'python' -Directory 'C:\Py313'
            $result.Changed | Should -Be $true -Because "the simulation still reports what it would have done"
            Should -Invoke Save-PathBackup -Times 0 -Because "a dry run must not even write the backup"
        } finally {
            $Script:DryRun = $false
        }
        [Environment]::GetEnvironmentVariable("Path", "User") | Should -Be $userPath
    }

    It "refuses a plan that is not a permutation of the live PATH" {
        <#
            THE CHECK THAT MAKES "removes nothing" TRUE RATHER THAN
            INTENDED. The live value is re-read and compared against the
            plan as SORTED MULTISETS before anything is written, so a plan
            that has dropped an entry - because the PATH changed under it,
            or because a future edit to the planner introduced a bug - is
            refused instead of applied.
        #>
        Mock Get-PathInstallPlan {
            [PSCustomObject]@{ Family='python'; Directory='C:\Py313'
                               Action='reorder'; Scope='User'; Reason='r'; Short='Use this one'
                               Order=@('C:\OnlyThis'); Dirs=@('C:\Py313') }
        }
        Mock New-SystemRestorePoint { }
        Mock Save-PathBackup { return $true }
        Mock Test-IsElevatedSession { return $true }

        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        $result = Set-PathToolPriority -Family 'python' -Directory 'C:\Py313'
        $result.Changed | Should -Be $false
        $result.Reason  | Should -BeLike '*nothing was written*'
        Should -Invoke Save-PathBackup -Times 0
        [Environment]::GetEnvironmentVariable("Path", "User") | Should -Be $userPath
    }

    It "leaves the machine PATH alone when the session is not elevated" {
        Mock Get-PathInstallPlan {
            [PSCustomObject]@{ Family='python'; Directory='C:\Py313'
                               Action='reorder'; Scope='Machine'; Reason='r'; Short='Use this one'
                               Order=@('C:\Py313'); Dirs=@('C:\Py313') }
        }
        Mock New-SystemRestorePoint { }
        Mock Save-PathBackup { return $true }
        Mock Test-IsElevatedSession { return $false }

        $result = Set-PathToolPriority -Family 'python' -Directory 'C:\Py313'
        $result.Changed | Should -Be $false
        $result.Reason  | Should -BeLike '*needs Administrator*'
        Should -Invoke Save-PathBackup -Times 0
    }

    It "does nothing at all when the installation already wins" {
        Mock Get-PathInstallPlan {
            [PSCustomObject]@{ Family='python'; Directory='C:\Py314'
                               Action='none'; Scope='User'; Short='In use'
                               Reason="Python already runs from C:\Py314."
                               Order=@(); Dirs=@() }
        }
        Mock New-SystemRestorePoint { }
        Mock Save-PathBackup { return $true }

        $result = Set-PathToolPriority -Family 'python' -Directory 'C:\Py314'
        $result.Changed | Should -Be $false
        Should -Invoke New-SystemRestorePoint -Times 0 -Because "a checkpoint for a no-op is noise in the list a user reaches when something has gone wrong"
    }

    It "takes the restore point BEFORE it writes, and backs up before that" {
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "03-Environment.ps1") -Raw
        $body = $source.Substring($source.IndexOf("function Set-PathToolPriority"))
        $body = $body.Substring(0, $body.IndexOf("`n# ============"))
        $restore = $body.IndexOf("New-SystemRestorePoint")
        $backup  = $body.IndexOf("Save-PathBackup")
        $write   = $body.IndexOf("SetEnvironmentVariable")
        $restore | Should -BeGreaterThan 0
        $restore | Should -BeLessThan $backup -Because "the checkpoint is the outer safety net"
        $backup  | Should -BeLessThan $write  -Because "a write with no saved copy of the old value is not reversible"
    }

    It "never removes an entry" {
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "03-Environment.ps1") -Raw
        $body = $source.Substring($source.IndexOf("function Set-PathToolPriority"))
        $body = $body.Substring(0, $body.IndexOf("`n# ============"))
        $body | Should -Not -BeLike '*Remove-ItemProperty*'
        $body | Should -BeLike '*Compare-Object*' -Because "the permutation check is what makes this safe"
    }
}

Describe "Get-PathConflictReport" {

    It "sends ONE entry per toolchain, carrying every command it covers" {
        Mock Test-Path {
            param($LiteralPath)
            if ($LiteralPath -like '*\Scripts\pip.exe')  { return $true }
            if ($LiteralPath -like '*\Scripts\pip3.exe') { return $true }
            if ($LiteralPath -like '*\Scripts\*')        { return $false }
            return ($LiteralPath -like '*python.exe')
        }
        Mock Get-PathEntryReport {
            @(
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py314\Scripts'; Path='C:\Py314\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py314';         Path='C:\Py314';         Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py312\Scripts'; Path='C:\Py312\Scripts'; Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py312';         Path='C:\Py312';         Exists=$true; Valid=$true; Duplicate=$false }
            )
        }
        $report = Get-PathConflictReport
        @($report.conflicts).Count | Should -Be 1 -Because "python/pip/pip3 are one toolchain"
        $python = @($report.conflicts)[0]
        $python.key | Should -Be 'python'
        @($python.commands) | Should -Contain 'pip'
        @($python.options).Count | Should -Be 2
        @($python.options | Where-Object { $_.winner }).Count | Should -Be 1
    }

    It "carries the short verdict and the folder list for every option" {
        Mock Test-Path { param($LiteralPath) return ($LiteralPath -like '*python.exe') }
        Mock Get-PathEntryReport {
            @(
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py314'; Path='C:\Py314'; Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User'; Raw='C:\Py312'; Path='C:\Py312'; Exists=$true; Valid=$true; Duplicate=$false }
            )
        }
        $python = @((Get-PathConflictReport).conflicts)[0]
        $second = @($python.options | Where-Object { -not $_.winner })[0]
        $second.short  | Should -Be 'Use this one'
        $second.action | Should -Be 'reorder'
        @($second.dirs).Count | Should -BeGreaterThan 0
    }

    It "computes fixability in the BACKEND, so the GUI cannot offer a refused button" {
        Mock Test-Path { param($LiteralPath) return ($LiteralPath -like '*python.exe') }
        Mock Get-PathEntryReport {
            @(
                [PSCustomObject]@{ Scope='Machine'; Raw='C:\Py314'; Path='C:\Py314'; Exists=$true; Valid=$true; Duplicate=$false }
                [PSCustomObject]@{ Scope='User';    Raw='C:\Py312'; Path='C:\Py312'; Exists=$true; Valid=$true; Duplicate=$false }
            )
        }
        $python = @((Get-PathConflictReport).conflicts)[0]
        $user = @($python.options | Where-Object { $_.path -eq 'C:\Py312' })[0]
        $user.action | Should -Be 'blocked'
        $user.short  | Should -Be 'Needs administrator'
    }

    It "reports an empty conflict list without throwing on a clean PATH" {
        Mock Test-Path { return $false }
        Mock Get-PathEntryReport {
            @([PSCustomObject]@{ Scope='Machine'; Raw='C:\Windows'; Path='C:\Windows'; Exists=$true; Valid=$true; Duplicate=$false })
        }
        $report = Get-PathConflictReport
        @($report.conflicts).Count | Should -Be 0
        $report.entries | Should -Be 1
    }
}
