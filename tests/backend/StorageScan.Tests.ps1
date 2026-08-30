#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
    Pester coverage for the Storage Analyzer's time budget
    (Measure-DirectorySize / Get-PulseStorageScan in 14-Inspectors.ps1).

.DESCRIPTION
    THE BUDGET IS THE FEATURE. 30-GuiDispatcher.ps1's StorageScan case
    states the contract outright — "time-budgeted inside
    Get-PulseStorageScan and reports `truncated` rather than running past
    it, so this case cannot become the task that never returns" — and the
    dialog's loading copy promises "this can take a minute on a large
    drive".

    One line of PowerShell made all of that untrue:

        $items = Get-ChildItem -LiteralPath $Path -Recurse -File
        foreach ($item in $items) { if ((Get-Date) -gt $Deadline) { break } ... }

    Assigning a pipeline to a variable runs it to completion. The whole
    recursive walk therefore finished BEFORE the deadline was consulted
    once, and the `break` then fired correctly and far too late. Measured
    against the 90-second budget: a scan of C:\ was still going after nine
    minutes, having meanwhile grown one accumulator object per file on the
    volume. The only real bound was the GUI's 900-second timeout, which
    surfaces as a wedged task rather than the partial report intended.

    That failure is invisible to every ordinary test: the numbers it
    returns are all correct, and `truncated` is even set honestly. Only
    the CLOCK is wrong, so the clock is what these assert on.

.NOTES
    Run:  Invoke-Pester -Path tests\backend
#>

BeforeAll {
    $script:RepoRoot  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:ModuleDir = Join-Path $script:RepoRoot "src\backend\modules"
    . (Join-Path $script:ModuleDir "00-Foundation.ps1")
    . (Join-Path $script:ModuleDir "14-Inspectors.ps1")

    # A small tree with a known total, for the correctness half.
    $script:Sandbox = Join-Path ([System.IO.Path]::GetTempPath()) "PulseStorageScan"
    Remove-Item -LiteralPath $script:Sandbox -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $script:Sandbox -Force | Out-Null
    $script:ExpectedBytes = 0
    foreach ($sub in @('a', 'b', 'b\deep', 'b\deep\deeper')) {
        New-Item -ItemType Directory -Path (Join-Path $script:Sandbox $sub) -Force | Out-Null
    }
    foreach ($rel in @('root.bin', 'a\one.bin', 'b\two.bin',
                       'b\deep\three.bin', 'b\deep\deeper\four.bin')) {
        $bytes = [byte[]]::new(1024)
        [System.IO.File]::WriteAllBytes((Join-Path $script:Sandbox $rel), $bytes)
        $script:ExpectedBytes += 1024
    }

    #: THE WHOLE SYSTEM DRIVE, and the size is the point.
    #:
    #: An earlier draft used System32, which was not big enough to detect
    #: anything: the pre-fix implementation walked it in 751ms on a warm
    #: cache, so every timing assertion passed against the very defect they
    #: were written for. Only the source-shape test failed. A guard that
    #: cannot fail against the bug is not a guard.
    #:
    #: The drive root is hundreds of thousands of files, so a full
    #: enumeration takes minutes while a correctly-abandoned walk takes
    #: milliseconds — a gap no cache state can close. It costs nothing when
    #: the code is right, which is the case that runs in CI every time.
    $script:BigTree = $env:SystemDrive + "\"

    #: A moderate tree for the partway-through case, where the walk is
    #: MEANT to do real work before the budget expires.
    $script:MidTree = Join-Path $env:WinDir 'System32'
}

AfterAll {
    if ($script:Sandbox) {
        Remove-Item -LiteralPath $script:Sandbox -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Describe "Measure-DirectorySize" {

    It "totals every file beneath the path, at any depth" {
        $files = New-Object System.Collections.ArrayList
        $total = Measure-DirectorySize -Path $script:Sandbox `
            -Deadline (Get-Date).AddMinutes(5) -FileAccumulator ([ref]$files)
        $total | Should -Be $script:ExpectedBytes
        $files.Count | Should -Be 5 -Because "five files were written, at four depths"
    }

    It "stops the WALK when the deadline has passed, not merely the arithmetic" {
        # THE REGRESSION, stated as a clock, against the whole system
        # drive. An expired deadline must make this return essentially
        # instantly; the previous implementation enumerated the entire tree
        # first and only then noticed, which on a drive root is minutes.
        # See $script:BigTree for why the tree has to be this big.
        $files = New-Object System.Collections.ArrayList
        $elapsed = Measure-Command {
            Measure-DirectorySize -Path $script:BigTree `
                -Deadline (Get-Date).AddSeconds(-1) `
                -FileAccumulator ([ref]$files) | Out-Null
        }
        $elapsed.TotalSeconds | Should -BeLessThan 3 `
            -Because "an expired budget must abandon the walk, not complete it first"
        $files.Count | Should -Be 0
    }

    It "honours a deadline that expires PARTWAY through a large tree" {
        # The realistic case: the budget runs out mid-walk. It must return
        # near the deadline rather than at the end of the enumeration.
        $files = New-Object System.Collections.ArrayList
        $budget = 2
        $elapsed = Measure-Command {
            Measure-DirectorySize -Path $script:MidTree `
                -Deadline (Get-Date).AddSeconds($budget) `
                -FileAccumulator ([ref]$files) | Out-Null
        }
        $elapsed.TotalSeconds | Should -BeLessThan ($budget + 8) `
            -Because "the walk must end near its budget, not run the tree out"
    }

    It "does not follow reparse points" {
        # A junction's target is counted under its real parent; following it
        # here would double-count at best and loop at worst.
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "14-Inspectors.ps1") -Raw
        $body = $source.Substring($source.IndexOf("function Measure-DirectorySize"))
        $body = $body.Substring(0, $body.IndexOf("`nfunction "))
        $body | Should -BeLike "*ReparsePoint*"
    }

    It "lets one unreadable folder cost only that folder" {
        # Enumerating a directory at a time is what keeps an access denial
        # local. A path that cannot be opened at all returns zero rather
        # than throwing into the caller's report.
        { Measure-DirectorySize -Path (Join-Path $script:Sandbox "no such folder") `
            -Deadline (Get-Date).AddMinutes(1) -FileAccumulator ([ref](New-Object System.Collections.ArrayList)) } |
            Should -Not -Throw
    }

    It "streams its enumeration rather than materialising it" {
        # The defect in one grep: a pipeline assigned to a variable runs to
        # completion, so the deadline below it can only ever fire late.
        #
        # The COMMENT BLOCK IS STRIPPED FIRST, and that is not tidiness:
        # the function's own docstring quotes the broken line verbatim to
        # explain what went wrong, so a naive match finds the defect in the
        # explanation of the defect and fails on correct code.
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "14-Inspectors.ps1") -Raw
        $body = $source.Substring($source.IndexOf("function Measure-DirectorySize"))
        $body = $body.Substring(0, $body.IndexOf("`nfunction "))
        $code = [regex]::Replace($body, '<#.*?#>', '', 'Singleline')
        $code = [regex]::Replace($code, '(?m)^\s*#.*$', '')
        $code | Should -Not -Match '\$items\s*=\s*Get-ChildItem[^\r\n]*-Recurse' `
            -Because "assigning a recursive Get-ChildItem enumerates the whole tree before the deadline is read"
        $code | Should -BeLike "*EnumerateFiles*"
    }
}

Describe "Get-PulseStorageScan" {

    It "reports a missing root as unavailable rather than throwing" {
        $report = Get-PulseStorageScan -ScanPath (Join-Path $script:Sandbox "nowhere") -MaxSeconds 5
        $report.available | Should -BeFalse
        $report.truncated | Should -BeFalse
    }

    It "reports a scan it could not finish as truncated" {
        # -MaxSeconds 0 expires the deadline before the first directory, so
        # the flag is exercised without betting on how long a real tree
        # takes. An earlier draft of this test asserted that three seconds
        # "cannot have covered System32" and then failed, because the tests
        # above had just walked System32 twice and left the filesystem
        # cache warm — a timing guess dressed up as an invariant, which is
        # the exact species of flake this suite is meant not to have.
        $report = Get-PulseStorageScan -ScanPath $script:MidTree -MaxSeconds 0
        $report.available | Should -BeTrue
        $report.truncated | Should -BeTrue
    }

    It "returns near its budget rather than running the volume out" {
        # The end-to-end clock, stated with a ceiling far enough above the
        # budget to survive a cold cache and far enough below the GUI's
        # 900-second timeout to mean something. The pre-fix implementation
        # blew through this by minutes on a real volume.
        $budget = 5
        $elapsed = Measure-Command {
            Get-PulseStorageScan -ScanPath $script:MidTree -MaxSeconds $budget | Out-Null
        }
        $elapsed.TotalSeconds | Should -BeLessThan 90 `
            -Because "a $budget-second budget must not become a minutes-long scan"
    }

    It "marks a scan that finished inside its budget as complete" {
        $report = Get-PulseStorageScan -ScanPath $script:Sandbox -MaxSeconds 60
        $report.available | Should -BeTrue
        $report.truncated | Should -BeFalse
        $report.totalBytes | Should -Be $script:ExpectedBytes
    }
}
