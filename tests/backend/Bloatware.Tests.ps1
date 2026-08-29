#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
    Pester coverage for the bloatware purge's classification and matching
    (08-Privacy.ps1 / 01-Catalogs.ps1).

.DESCRIPTION
    THE DANGEROUS PART OF THIS FEATURE IS A WILDCARD. The catalog matches
    on fragments - "*Messenger*", "*YourPhone*", "king.com.*" - because
    publisher prefixes and package suffixes move between Windows builds and
    an exact name stops matching the moment Microsoft renames a package.
    The cost of that flexibility is that a pattern can grow a match nobody
    intended, and the thing it grows a match on might be the shell.

    None of that can be exercised against a real machine: the only way to
    find out whether "*Tips*" also claims a system package is to remove it.
    So Resolve-BloatwareTargets takes its world as ARGUMENTS - the
    installed list, the provisioned list, the protected list - and every
    rule below runs against a mocked inventory, including the cases that
    never occur locally:

      * a protected package caught by a catalog wildcard;
      * an entry that is provisioned but not installed (the case that makes
        an app come back after a feature update);
      * an empty selection, which means "the recommended set" and NOT
        "everything";
      * the optional Xbox tier, which a bulk purge must never sweep up.

.NOTES
    Run:  Invoke-Pester -Path tests\backend
#>

BeforeAll {
    $script:RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:ModuleDir = Join-Path $script:RepoRoot "src\backend\modules"

    # 01-Catalogs.ps1 ends with data-path bootstrapping that needs
    # 00-Foundation; the catalog itself is pure data and loads before it.
    # Both are dot-sourced with errors suppressed for exactly that reason -
    # the assertions below only ever read $Script:BloatCatalog and
    # $Script:BloatProtected.
    . (Join-Path $script:ModuleDir "00-Foundation.ps1")
    . (Join-Path $script:ModuleDir "01-Catalogs.ps1")

    # Only the PURE half of 08-Privacy is loaded. Dot-sourcing the whole
    # module would define Remove-Bloatware, and a test file that can call
    # it is a test file one typo away from purging the machine it runs on.
    $script:PrivacySrc = Get-Content (Join-Path $script:ModuleDir "08-Privacy.ps1") -Raw
    $ast = [System.Management.Automation.Language.Parser]::ParseInput(
        $script:PrivacySrc, [ref]$null, [ref]$null)
    $pure = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -in @('Resolve-BloatwareTargets', 'Test-ProtectedPackage')
    }, $true)
    foreach ($fn in $pure) { . ([scriptblock]::Create($fn.Extent.Text)) }

    # A machine with one of everything: promo stubs, a core app, the
    # optional Xbox tier, a desktop leftover - and three packages that must
    # survive whatever the catalog matches.
    $script:Installed = @(
        'Microsoft.BingNews'
        'Microsoft.YourPhone'
        'Microsoft.549981C3F5F10'          # Cortana
        'king.com.CandyCrushSaga'
        'SpotifyAB.SpotifyMusic'
        'Microsoft.XboxGamingOverlay'      # optional tier
        'Microsoft.WindowsStore'           # protected
        'Microsoft.VCLibs.140.00'          # protected
        'Microsoft.WindowsNotepad'         # not catalogued at all
    )
    $script:Provisioned = @(
        'Microsoft.BingNews'
        'Microsoft.WindowsMaps'            # staged but NOT installed
        'Microsoft.WindowsStore'           # protected
    )
    $script:Desktop = @(
        'K-Lite Codec Pack 18.0.5 Standard'
        'Mozilla Firefox (x64 en-US)'
    )

    function script:Resolve {
        param([string[]]$SelectedIds = @())
        return @(Resolve-BloatwareTargets -Catalog $Script:BloatCatalog `
            -Installed $script:Installed -Provisioned $script:Provisioned `
            -Desktop $script:Desktop -SelectedIds $SelectedIds `
            -Protected $Script:BloatProtected)
    }

    function script:Ids {
        param($Rows)
        return @($Rows | ForEach-Object { $_.Id })
    }
}

Describe "The catalog itself" {

    It "classifies every entry into a known layer" {
        $known = @('promo', 'core', 'gaming', 'codec')
        foreach ($entry in $Script:BloatCatalog) {
            $entry.Group | Should -BeIn $known -Because `
                "$($entry.Id) must belong to a layer the GUI renders a section for"
        }
    }

    It "gives every entry a stable Id, a human name and a consequence" {
        foreach ($entry in $Script:BloatCatalog) {
            $entry.Id   | Should -Not -BeNullOrEmpty
            $entry.Name | Should -Not -BeNullOrEmpty
            $entry.Note | Should -Not -BeNullOrEmpty -Because `
                "the user is agreeing to DELETE $($entry.Id); the row has to say what that costs"
        }
    }

    It "has no duplicate Ids" {
        $ids = @($Script:BloatCatalog | ForEach-Object { $_.Id })
        $dupes = @($ids | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name })
        $dupes | Should -BeNullOrEmpty
    }

    It "declares the whole Xbox tier optional" {
        $xbox = @($Script:BloatCatalog | Where-Object { $_.Group -eq 'gaming' })
        $xbox.Count | Should -BeGreaterThan 0
        foreach ($entry in $xbox) {
            $entry.Optional | Should -BeTrue -Because `
                "removing Game Bar's overlay or the identity provider breaks things the user did not ask about"
        }
    }

    It "gives every entry exactly one removal mechanism" {
        foreach ($entry in $Script:BloatCatalog) {
            $hasAppx = $entry.ContainsKey('Match')
            $hasDesktop = $entry.ContainsKey('Desktop')
            ($hasAppx -or $hasDesktop) | Should -BeTrue -Because `
                "$($entry.Id) declares no way to find itself"
            ($hasAppx -and $hasDesktop) | Should -BeFalse -Because `
                "$($entry.Id) would be removed twice by two different pipelines"
        }
    }

    It "never lets a catalog pattern claim a protected package" {
        # THE ONE THAT MATTERS. Every catalog wildcard is run against the
        # protected list itself: if a pattern matches one of these, the
        # purge would target the shell, the Store or a runtime, and the
        # only reason it does not today is Test-ProtectedPackage. This
        # asserts the catalog is safe BEFORE that net catches it.
        $shellPackages = @(
            'Microsoft.WindowsStore'
            'Microsoft.DesktopAppInstaller'
            'Microsoft.VCLibs.140.00'
            'Microsoft.NET.Native.Framework.2.2'
            'Microsoft.UI.Xaml.2.8'
            'Microsoft.Windows.ShellExperienceHost'
            'Microsoft.Windows.StartMenuExperienceHost'
            'Microsoft.Windows.Search'
            'Microsoft.SecHealthUI'
            'Microsoft.Windows.ImmersiveControlPanel'
        )
        foreach ($package in $shellPackages) {
            Test-ProtectedPackage -Name $package -Protected $Script:BloatProtected |
                Should -BeTrue -Because "$package must never be removable"
        }
    }
}

Describe "Resolve-BloatwareTargets (pure, against a mocked inventory)" {

    It "detects an installed package" {
        $row = @(script:Resolve | Where-Object { $_.Id -eq 'BingNews' })[0]
        $row.Detected | Should -BeTrue
        $row.Installed | Should -Contain 'Microsoft.BingNews'
    }

    It "detects a package that is only PROVISIONED" {
        # The case that makes an app return after a feature update: nothing
        # is installed right now, but a staged template is waiting.
        $row = @(script:Resolve | Where-Object { $_.Id -eq 'Maps' })[0]
        $row.Detected | Should -BeTrue
        $row.Installed | Should -BeNullOrEmpty
        $row.Provisioned | Should -Contain 'Microsoft.WindowsMaps'
    }

    It "reports an absent package as a row rather than dropping it" {
        $row = @(script:Resolve | Where-Object { $_.Id -eq 'TikTok' })[0]
        $row | Should -Not -BeNullOrEmpty -Because `
            "the GUI shows 'not present' rows so the user can tell a clean machine from a short catalog"
        $row.Detected | Should -BeFalse
    }

    It "matches a wildcard family through one entry" {
        $row = @(script:Resolve | Where-Object { $_.Id -eq 'KingGames' })[0]
        $row.Installed | Should -Contain 'king.com.CandyCrushSaga'
    }

    It "finds a desktop leftover through the uninstall hive, not AppX" {
        $row = @(script:Resolve | Where-Object { $_.Id -eq 'KLiteCodec' })[0]
        $row.Detected | Should -BeTrue
        $row.Desktop | Should -Contain 'K-Lite Codec Pack 18.0.5 Standard'
        $row.Installed | Should -BeNullOrEmpty
    }

    It "leaves an unrelated desktop program alone" {
        $rows = @(script:Resolve | Where-Object { $_.Desktop -contains 'Mozilla Firefox (x64 en-US)' })
        $rows | Should -BeNullOrEmpty
    }

    It "never targets a protected package, however it was matched" {
        foreach ($row in script:Resolve) {
            $row.Installed   | Should -Not -Contain 'Microsoft.WindowsStore'
            $row.Installed   | Should -Not -Contain 'Microsoft.VCLibs.140.00'
            $row.Provisioned | Should -Not -Contain 'Microsoft.WindowsStore'
        }
    }

    It "leaves packages the catalog says nothing about alone" {
        foreach ($row in script:Resolve) {
            $row.Installed | Should -Not -Contain 'Microsoft.WindowsNotepad'
        }
    }
}

Describe "Selection policy" {

    It "treats an EMPTY selection as the recommended set, not everything" {
        $selected = @(script:Resolve | Where-Object { $_.Selected })
        $optional = @($selected | Where-Object { $_.Optional })
        $optional | Should -BeNullOrEmpty -Because `
            "a headless purge must not take Game Bar with it"
        $selected.Count | Should -BeGreaterThan 0
    }

    It "selects the optional tier only when it is asked for by name" {
        $rows = script:Resolve -SelectedIds @('XboxGamingOverlay')
        $selected = @($rows | Where-Object { $_.Selected } | ForEach-Object { $_.Id })
        $selected | Should -Be @('XboxGamingOverlay')
    }

    It "honours an explicit selection exactly, ignoring the optional default" {
        $rows = script:Resolve -SelectedIds @('BingNews', 'Cortana')
        $selected = @($rows | Where-Object { $_.Selected } | ForEach-Object { $_.Id } | Sort-Object)
        $selected | Should -Be @('BingNews', 'Cortana')
    }

    It "can select something that is not installed without inventing a target" {
        # The GUI disables absent rows, but the backend contract has to hold
        # on its own: a stale id from an old scan must resolve to a selected
        # row with nothing to remove, not to an error.
        $row = @(script:Resolve -SelectedIds @('TikTok') | Where-Object { $_.Id -eq 'TikTok' })[0]
        $row.Selected | Should -BeTrue
        $row.Detected | Should -BeFalse
        $row.Installed | Should -BeNullOrEmpty
    }
}

Describe "A machine with nothing on it" {

    It "reports every entry as a row, none detected, none blocked" {
        $rows = @(Resolve-BloatwareTargets -Catalog $Script:BloatCatalog `
            -Installed @() -Provisioned @() -Desktop @() `
            -Protected $Script:BloatProtected)
        $rows.Count | Should -Be $Script:BloatCatalog.Count
        @($rows | Where-Object { $_.Detected }) | Should -BeNullOrEmpty
        @($rows | Where-Object { $_.Blocked.Count -gt 0 }) | Should -BeNullOrEmpty
    }
}

Describe "A catalog pattern that grows a match on the shell" {

    It "records it as blocked instead of targeting it" {
        # A deliberately reckless catalog, standing in for the future build
        # where a real pattern starts matching something it did not before.
        # The purge must fail CLOSED: the package appears in Blocked (so the
        # log can name it) and in no removal list.
        $reckless = @(
            @{ Id = "Reckless"; Name = "Reckless"; Group = "promo"; Match = "*Windows*"; Note = "n/a" }
        )
        $rows = @(Resolve-BloatwareTargets -Catalog $reckless `
            -Installed @('Microsoft.WindowsStore', 'Microsoft.WindowsNotepad') `
            -Protected $Script:BloatProtected)

        $rows[0].Blocked   | Should -Contain 'Microsoft.WindowsStore'
        $rows[0].Installed | Should -Not -Contain 'Microsoft.WindowsStore'
        $rows[0].Installed | Should -Contain 'Microsoft.WindowsNotepad' -Because `
            "only the protected package is withheld; the rest of the match still resolves"
    }
}
