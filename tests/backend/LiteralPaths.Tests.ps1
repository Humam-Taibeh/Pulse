#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
    Pester coverage for the paths Pulse receives from a FILE PICKER rather
    than builds itself: Invoke-GuiLocalInstall (04-SoftwareEngine.ps1) and
    the Office Deployment Tool finders (10-Office.ps1).

.DESCRIPTION
    '[' AND ']' ARE LEGAL IN A WINDOWS FILENAME, and PowerShell's -Path
    parameter reads them as a character class. So `Test-Path -Path
    "C:\Downloads\setup [1].exe"` is not asking whether that file exists —
    it is asking whether any file called "setup 1.exe" does. The answer is
    False, and the file it was actually asked about is sitting right there.

    That filename is not exotic. It is what a browser names the second
    download of the same installer, and what the IE/WinINet cache has
    always produced. The user picked the file, Pulse showed them the path
    it was about to run, and then reported "Installer file not found" —
    a message that is not merely unhelpful but false.

    The same read affects the Office wizard, where the bracket can sit in
    the FOLDER instead: an "Office [old]" deployment folder made
    Find-OfficeSetupFile report no setup.exe in a folder containing one.

    The engine already knew this idiom — Disable-StartupItem's Move-Item
    carries a comment naming "Game [2].lnk", and Startup.Tests.ps1 covers
    it — so these tests pin the same rule on the paths that had not
    adopted it.

    Everything here runs under $Script:DryRun, so no installer is ever
    launched; the assertions are about which files the engine AGREES to
    run, which is the half that was wrong.

.NOTES
    Run:  Invoke-Pester -Path tests\backend
#>

BeforeAll {
    $script:RepoRoot  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:ModuleDir = Join-Path $script:RepoRoot "src\backend\modules"
    . (Join-Path $script:ModuleDir "00-Foundation.ps1")
    . (Join-Path $script:ModuleDir "01-Catalogs.ps1")
    . (Join-Path $script:ModuleDir "03-Environment.ps1")
    . (Join-Path $script:ModuleDir "04-SoftwareEngine.ps1")
    . (Join-Path $script:ModuleDir "10-Office.ps1")

    # Nothing may prompt, and nothing may actually install: the contract
    # under test is which paths are ACCEPTED, not what running one does.
    $Script:NonInteractive = $true
    $Script:DryRun         = $true

    # A sandbox whose own name carries a bracket, so the folder-level read
    # is exercised at the same time as the filename-level one.
    $script:Sandbox = Join-Path ([System.IO.Path]::GetTempPath()) "PulsePester [lit]"
    New-Item -ItemType Directory -Path $script:Sandbox -Force | Out-Null
}

AfterAll {
    if ($script:Sandbox -and (Test-Path -LiteralPath $script:Sandbox)) {
        Remove-Item -LiteralPath $script:Sandbox -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Describe "Invoke-GuiLocalInstall accepts the file the user actually picked" {

    BeforeAll {
        $script:Bracketed = Join-Path $script:Sandbox "setup [1].exe"
        $script:Plain     = Join-Path $script:Sandbox "normal.exe"
        Set-Content -LiteralPath $script:Bracketed -Value "stub" -Encoding Ascii
        Set-Content -LiteralPath $script:Plain     -Value "stub" -Encoding Ascii
    }

    It "runs an installer whose name contains brackets" {
        # THE REGRESSION. Under -Path this returned $false with
        # "Installer file not found" for a file that exists.
        Invoke-GuiLocalInstall -FilePath $script:Bracketed | Should -BeTrue `
            -Because "'setup [1].exe' is an ordinary filename, not a pattern"
    }

    It "still runs an installer with an ordinary name" {
        Invoke-GuiLocalInstall -FilePath $script:Plain | Should -BeTrue
    }

    It "still refuses a file that genuinely is not there" {
        # The guard must not have been widened into no guard at all.
        $missing = Join-Path $script:Sandbox "does not exist [9].exe"
        Invoke-GuiLocalInstall -FilePath $missing | Should -BeFalse
    }

    It "does not treat a wildcard as a match for some other file" {
        # "*.exe" is not a file. Under -Path it would have RESOLVED, and
        # the engine would have run whichever installer happened to sort
        # first - a path from a text box to an arbitrary execution.
        Invoke-GuiLocalInstall -FilePath (Join-Path $script:Sandbox "*.exe") | Should -BeFalse `
            -Because "a pattern must never resolve to some file the user did not pick"
    }
}

Describe "The Office finders read a bracketed folder" {

    BeforeAll {
        # A complete, valid ODT folder whose NAME contains brackets.
        $script:OfficeDir = Join-Path $script:Sandbox "Office [old]"
        New-Item -ItemType Directory -Path $script:OfficeDir -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:OfficeDir "setup.exe") -Value "stub" -Encoding Ascii
        Set-Content -LiteralPath (Join-Path $script:OfficeDir "configuration.xml") -Value "<Configuration />" -Encoding Ascii
    }

    It "finds setup.exe inside it" {
        $found = Find-OfficeSetupFile -Folder $script:OfficeDir
        $found | Should -Not -BeNullOrEmpty `
            -Because "the folder contains a setup.exe; only the bracket hid it"
        (Split-Path $found -Leaf) | Should -Be "setup.exe"
    }

    It "finds configuration.xml inside it" {
        $found = Find-OfficeConfigFile -Folder $script:OfficeDir
        $found | Should -Not -BeNullOrEmpty
        (Split-Path $found -Leaf) | Should -Be "configuration.xml"
    }

    It "accepts it as a valid deployment folder" {
        Test-OfficeFolderValid -Folder $script:OfficeDir | Should -BeTrue
    }

    It "still rejects a folder that has neither file" {
        $empty = Join-Path $script:Sandbox "Empty [1]"
        New-Item -ItemType Directory -Path $empty -Force | Out-Null
        Test-OfficeFolderValid -Folder $empty | Should -BeFalse
    }

    It "still returns null for a folder that does not exist" {
        Find-OfficeSetupFile -Folder (Join-Path $script:Sandbox "no such [2]") | Should -BeNullOrEmpty
        Find-OfficeConfigFile -Folder (Join-Path $script:Sandbox "no such [2]") | Should -BeNullOrEmpty
    }
}

Describe "The picker-fed paths use -LiteralPath by construction" {
    # A source-level backstop for the two call sites, so a future edit that
    # reintroduces -Path fails here even if no fixture happens to carry a
    # bracket. Stated narrowly - the existence probe on the picked file -
    # rather than as a blanket ban on -Path, which has legitimate uses.
    It "Invoke-GuiLocalInstall probes its FilePath literally" {
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "04-SoftwareEngine.ps1") -Raw
        $source | Should -Match 'Test-Path -LiteralPath \$FilePath -PathType Leaf'
        $source | Should -Not -Match 'Test-Path -Path \$FilePath'
    }

    It "Invoke-GuiOfficeODTInstall probes both of its paths literally" {
        $source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "10-Office.ps1") -Raw
        $source | Should -Match 'Test-Path -LiteralPath \$SetupPath -PathType Leaf'
        $source | Should -Match 'Test-Path -LiteralPath \$ConfigPath -PathType Leaf'
        $source | Should -Not -Match 'Test-Path -Path \$SetupPath'
        $source | Should -Not -Match 'Test-Path -Path \$ConfigPath'
    }
}
