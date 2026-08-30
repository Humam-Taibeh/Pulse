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
