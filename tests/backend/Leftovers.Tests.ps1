#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
<#
.SYNOPSIS
    Pester coverage for the Leftovers Cleaner (17-Leftovers.ps1).

.DESCRIPTION
    THIS MODULE DELETES THINGS, so the suite is organised around the two
    ways it could do harm rather than around its functions:

      * FLAGGING SOMETHING THAT IS NOT A LEFTOVER. Every scanner is tested
        against the traps measured on a real machine: a bare "cmd.exe" in
        a command, a target under C:\Windows, a directory Test-Path cannot
        see into, a task with one live action, a folder that merely looks
        abandoned.

      * REMOVING WITHOUT A WAY BACK. The purge is tested for its order
        (checkpoint, backup, removal), for refusing when a backup fails,
        for re-scanning so a reinstalled app is spared, and every kind of
        item is taken all the way through purge AND restore.

    ISOLATION: nothing here reads or writes a real Run key, Startup folder,
    scheduled task, CLSID or shell verb. Every location the module uses is
    redirected into HKCU:\Software\PulsePesterLeftovers and a temp
    directory, and scheduled tasks are served by a mock - the suite cannot
    unregister a task the developer's machine depends on.

.NOTES
    Run:  Invoke-Pester -Path tests\backend\Leftovers.Tests.ps1
#>

BeforeAll {
    $script:RepoRoot  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script:ModuleDir = Join-Path $script:RepoRoot "src\backend\modules"
    . (Join-Path $script:ModuleDir "00-Foundation.ps1")
    . (Join-Path $script:ModuleDir "01-Catalogs.ps1")
    . (Join-Path $script:ModuleDir "02-Safety.ps1")
    . (Join-Path $script:ModuleDir "03-Environment.ps1")
    . (Join-Path $script:ModuleDir "05-Startup.ps1")
    . (Join-Path $script:ModuleDir "16-ContextMenu.ps1")
    . (Join-Path $script:ModuleDir "17-Leftovers.ps1")

    # --- isolation ---------------------------------------------------
    $script:TestRoot    = "HKCU:\Software\PulsePesterLeftovers"
    $script:TestRootRaw = "Registry::HKEY_CURRENT_USER\Software\PulsePesterLeftovers"
    $script:TempBase    = Join-Path ([System.IO.Path]::GetTempPath()) "PulsePesterLeftovers"
    $script:ProgramsRoot = Join-Path $script:TempBase "Programs"
    $script:ResidueRoot  = Join-Path $script:TempBase "AppData"

    $Script:StartupRunKeyPaths     = @("$script:TestRoot\Run_User", "$script:TestRoot\Run_Machine")
    $Script:StartupFolderPaths     = @((Join-Path $script:TempBase "Startup_User"),
                                       (Join-Path $script:TempBase "Startup_Machine"))
    $Script:StartupDisabledRegPath = "$script:TestRoot\DisabledStartup"
    $Script:StartupOriginRegPath   = "$Script:StartupDisabledRegPath\_Origins"
    $Script:StartupBackupFolder    = Join-Path $script:TempBase "StartupBackup"

    $Script:LeftoverBackupRegRoot    = "$script:TestRoot\Backups"
    $Script:LeftoverBackupFolderRoot = Join-Path $script:TempBase "Backups"
    $Script:LeftoverResidueRoots     = @($script:ResidueRoot)
    $Script:LeftoverClsidRoot        = "$script:TestRootRaw\CLSID"
    $Script:ContextMenuRoots         = @(@{ Path = "$script:TestRootRaw\Handlers"; Scope = "Test files" })
    $Script:LeftoverVerbRoots        = @("$script:TestRootRaw\Verbs")

    $Script:LogPath = Join-Path ([System.IO.Path]::GetTempPath()) "PulsePesterLeftovers.log"
    $Script:DryRun = $false

    function script:Reset-LeftoverFixtures {
        if (Test-Path $script:TestRoot) {
            Remove-Item -Path $script:TestRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $script:TempBase) {
            Remove-Item -LiteralPath $script:TempBase -Recurse -Force -ErrorAction SilentlyContinue
        }
        foreach ($Key in @($Script:StartupRunKeyPaths) + @("$script:TestRoot\CLSID",
                          "$script:TestRoot\Handlers", "$script:TestRoot\Verbs")) {
            New-Item -Path $Key -Force | Out-Null
        }
        foreach ($Dir in @($Script:StartupFolderPaths) + @($Script:StartupBackupFolder,
                          $script:ProgramsRoot, $script:ResidueRoot)) {
            New-Item -Path $Dir -ItemType Directory -Force | Out-Null
        }
        $Script:DryRun = $false
    }

    function script:New-FixtureFile([string]$Relative, [int]$Bytes = 16) {
        $Path = Join-Path $script:ProgramsRoot $Relative
        New-Item -Path (Split-Path $Path -Parent) -ItemType Directory -Force | Out-Null
        [System.IO.File]::WriteAllBytes($Path, (New-Object byte[] $Bytes))
        return $Path
    }

    #: A path under the fixture tree that is never created.
    function script:Get-GonePath([string]$Relative) {
        return (Join-Path $script:ProgramsRoot $Relative)
    }

    function script:Add-RunValue([string]$Name, [string]$Command, [int]$Index = 0,
                                 [string]$Kind = 'String') {
        New-ItemProperty -Path $Script:StartupRunKeyPaths[$Index] -Name $Name -Value $Command `
            -PropertyType $Kind -Force | Out-Null
    }

    function script:Get-RunValueNames([int]$Index = 0) {
        $Key = Get-Item -Path $Script:StartupRunKeyPaths[$Index]
        return @($Key.GetValueNames())
    }

    function script:New-Shortcut([string]$Lnk, [string]$Target) {
        $Shell = New-Object -ComObject WScript.Shell
        $Link = $Shell.CreateShortcut($Lnk)
        $Link.TargetPath = $Target
        $Link.Save()
    }

    function script:New-ExecAction([string]$Execute) {
        [PSCustomObject]@{
            CimClass  = [PSCustomObject]@{ CimClassName = 'MSFT_TaskExecAction' }
            Execute   = $Execute
            Arguments = ''
        }
    }

    function script:New-ComAction {
        [PSCustomObject]@{ CimClass = [PSCustomObject]@{ CimClassName = 'MSFT_TaskComHandlerAction' } }
    }

    function script:New-FakeTask([string]$Path, [string]$Name, [object[]]$Actions) {
        [PSCustomObject]@{ TaskPath = $Path; TaskName = $Name; State = 'Ready'
                           Triggers = @(); Actions = $Actions }
    }

    function script:Add-Handler([string]$Name, [string]$Module) {
        $Clsid = "{" + [guid]::NewGuid().ToString().ToUpperInvariant() + "}"
        $Inproc = "$script:TestRoot\CLSID\$Clsid\InprocServer32"
        New-Item -Path $Inproc -Force | Out-Null
        Set-ItemProperty -Path $Inproc -Name '(default)' -Value $Module
        $Handler = "$script:TestRoot\Handlers\$Name"
        New-Item -Path $Handler -Force | Out-Null
        Set-ItemProperty -Path $Handler -Name '(default)' -Value $Clsid
        return $Clsid
    }

    function script:Add-Verb([string]$Name, [string]$Command) {
        $CommandKey = "$script:TestRoot\Verbs\$Name\command"
        New-Item -Path $CommandKey -Force | Out-Null
        Set-ItemProperty -Path $CommandKey -Name '(default)' -Value $Command
    }

    function script:New-DeadSquirrel([string]$Name, [switch]$NoDead, [switch]$NoStub,
                                     [switch]$DeadIsDirectory) {
        $Root = Join-Path $script:ResidueRoot $Name
        New-Item -Path (Join-Path $Root "app-1.0.0") -ItemType Directory -Force | Out-Null
        [System.IO.File]::WriteAllBytes((Join-Path $Root "app-1.0.0\resources.bin"), (New-Object byte[] 2048))
        if (-not $NoStub) {
            [System.IO.File]::WriteAllBytes((Join-Path $Root "Update.exe"), (New-Object byte[] 64))
        }
        if ($DeadIsDirectory) {
            New-Item -Path (Join-Path $Root ".dead") -ItemType Directory -Force | Out-Null
        } elseif (-not $NoDead) {
            [System.IO.File]::WriteAllText((Join-Path $Root ".dead"), "")
        }
        return $Root
    }
}

AfterAll {
    if (Test-Path $script:TestRoot) {
        Remove-Item -Path $script:TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $script:TempBase) {
        Remove-Item -LiteralPath $script:TempBase -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($Script:LogPath -and (Test-Path -LiteralPath $Script:LogPath)) {
        Remove-Item -LiteralPath $Script:LogPath -Force -ErrorAction SilentlyContinue
    }
}

Describe "Test isolation" {
    It "never points at a real Run key, Startup folder, CLSID root or backup root" {
        # If this fails, STOP: the suite is about to remove things the
        # developer's machine actually uses.
        foreach ($Path in @($Script:StartupRunKeyPaths) + @($Script:LeftoverBackupRegRoot)) {
            $Path | Should -BeLike 'HKCU:\Software\PulsePesterLeftovers*'
        }
        $Script:LeftoverClsidRoot | Should -BeLike '*PulsePesterLeftovers*'
        foreach ($Root in @($Script:ContextMenuRoots)) { $Root.Path | Should -BeLike '*PulsePesterLeftovers*' }
        foreach ($Root in @($Script:LeftoverVerbRoots)) { $Root | Should -BeLike '*PulsePesterLeftovers*' }
        foreach ($Dir in @($Script:StartupFolderPaths) + @($Script:LeftoverResidueRoots, $Script:LeftoverBackupFolderRoot)) {
            $Dir | Should -BeLike "$script:TempBase*"
        }
    }
}

# ============================================================
#  THE PREDICATE
# ============================================================
Describe "Test-PathProvablyAbsent" {

    BeforeEach { Reset-LeftoverFixtures }

    It "is false for a file that exists" {
        $Path = New-FixtureFile 'Live\app.exe'
        Test-PathProvablyAbsent -Path $Path | Should -BeFalse
    }

    It "is true for a missing file inside a folder it can read" {
        $null = New-FixtureFile 'Vendor\other.exe'
        Test-PathProvablyAbsent -Path (Get-GonePath 'Vendor\gone.exe') | Should -BeTrue
    }

    It "is true when the whole folder tree is gone, as uninstallers leave it" {
        Test-PathProvablyAbsent -Path (Get-GonePath 'Uninstalled Vendor\Sub\app.exe') | Should -BeTrue
    }

    It "refuses a bare or relative name, which resolves through a search path" {
        Test-PathProvablyAbsent -Path 'shell32.dll' | Should -BeFalse
        Test-PathProvablyAbsent -Path 'cmd.exe' | Should -BeFalse
        Test-PathProvablyAbsent -Path 'Vendor\app.exe' | Should -BeFalse
    }

    It "refuses a UNC path, whose answer lives on another machine" {
        Test-PathProvablyAbsent -Path '\\pulse-no-such-server\share\app.exe' | Should -BeFalse
    }

    It "refuses anything under the Windows directory" {
        # A missing file under C:\Windows is more likely a 32-bit
        # registration read from 64-bit code than it is residue.
        Test-PathProvablyAbsent -Path (Join-Path $env:SystemRoot 'System32\pulse-not-a-real-file.exe') | Should -BeFalse
    }

    It "refuses WindowsApps, where Test-Path cannot see files that are there" {
        $Path = Join-Path $env:ProgramFiles 'WindowsApps\Pulse.Fake_1.0.0.0_x64__abcdefghijklm\app.exe'
        Test-PathProvablyAbsent -Path $Path | Should -BeFalse
    }

    It "refuses a path on a drive letter that is not mounted" {
        $Free = @([char[]](68..90) | Where-Object { -not (Test-Path "$($_):\") })
        if ($Free.Count -eq 0) { Set-ItResult -Skipped -Because "every drive letter is in use"; return }
        Test-PathProvablyAbsent -Path "$($Free[-1]):\Vendor\app.exe" | Should -BeFalse
    }

    It "refuses a malformed path without throwing" {
        { Test-PathProvablyAbsent -Path 'C:\bad|name\app.exe' } | Should -Not -Throw
        Test-PathProvablyAbsent -Path 'C:\bad|name\app.exe' | Should -BeFalse
        Test-PathProvablyAbsent -Path '' | Should -BeFalse
        Test-PathProvablyAbsent -Path '   ' | Should -BeFalse
    }

    It "is FALSE when the nearest existing folder cannot be listed" {
        <#
            THE CHECK THAT LOOKS UNNECESSARY. %ProgramFiles%\WindowsApps
            refuses a listing to everything but TrustedInstaller, so
            Test-Path answers $false for files sitting right there. "I
            could not see it" is not "it is not there".
        #>
        $script:LockedDir = Join-Path $script:ProgramsRoot 'Locked'
        New-Item -Path $script:LockedDir -ItemType Directory -Force | Out-Null
        Mock Get-ChildItem { throw [System.UnauthorizedAccessException]::new('Access to the path is denied.') } `
            -ParameterFilter { @($LiteralPath) -contains $script:LockedDir }
        Test-PathProvablyAbsent -Path (Join-Path $script:LockedDir 'app.exe') | Should -BeFalse
    }
}

Describe "Get-LeftoverProtectedRoots" {

    It "covers the Windows directory and WindowsApps" {
        $Roots = @(Get-LeftoverProtectedRoots)
        $Roots | Should -Contain $env:SystemRoot
        ($Roots -join '|') | Should -BeLike '*WindowsApps*'
    }

    It "protects the Program Files 'Windows *' family by name" {
        Test-LeftoverProtectedPath -Path (Join-Path $env:ProgramFiles 'Windows Defender\MsMpEng.exe') | Should -BeTrue
    }

    It "does not let a prefix claim a sibling folder" {
        # "C:\Windows" must protect C:\Windows\... and not C:\WindowsTools.
        Test-LeftoverProtectedPath -Path ($env:SystemRoot.TrimEnd('\') + 'Tools\app.exe') | Should -BeFalse
    }
}

Describe "Get-CommandTargetPath" {

    BeforeEach { Reset-LeftoverFixtures }

    It "takes the quoted run, even when that file is gone" {
        Get-CommandTargetPath -Command '"C:\Program Files\Gone Vendor\gone.exe" --minimized' |
            Should -Be 'C:\Program Files\Gone Vendor\gone.exe'
    }

    It "expands environment variables" {
        Get-CommandTargetPath -Command '"%SystemRoot%\System32\notepad.exe" /A' |
            Should -Be (Join-Path $env:SystemRoot 'System32\notepad.exe')
    }

    It "finds an existing unquoted path with spaces by the longest leading run" {
        $Path = New-FixtureFile 'Space Dir\tool.exe'
        Get-CommandTargetPath -Command "$Path --flag /q" | Should -Be $Path
    }

    It "ends a MISSING unquoted path at its executable extension" {
        # There is no file left to find, so the extension is the only thing
        # that says where the path stops.
        $Gone = Get-GonePath 'Gone Dir\app.exe'
        Get-CommandTargetPath -Command "$Gone --background" | Should -Be $Gone
    }

    It "returns a host process as the bare name it is" {
        Get-CommandTargetPath -Command 'rundll32.exe C:\gone\thing.dll,Entry' | Should -Be 'rundll32.exe'
    }

    It "returns nothing when there is no path to find" {
        Get-CommandTargetPath -Command 'nonsense words here' | Should -BeNullOrEmpty
        Get-CommandTargetPath -Command '' | Should -BeNullOrEmpty
    }
}

# ============================================================
#  SCANNERS
# ============================================================
Describe "Get-LeftoverStartupEntries" {

    BeforeEach { Reset-LeftoverFixtures }

    It "flags a Run value whose program is gone" {
        Add-RunValue -Name 'GoneApp' -Command ('"' + (Get-GonePath 'GoneApp\app.exe') + '" --autostart')
        $Items = @(Get-LeftoverStartupEntries)
        $Items.Count | Should -Be 1
        $Items[0].kind | Should -Be 'startup-run'
        $Items[0].valueName | Should -Be 'GoneApp'
        $Items[0].target | Should -Be (Get-GonePath 'GoneApp\app.exe')
    }

    It "leaves a Run value alone when its program is there" {
        $Path = New-FixtureFile 'LiveApp\app.exe'
        Add-RunValue -Name 'LiveApp' -Command "`"$Path`" --autostart"
        @(Get-LeftoverStartupEntries).Count | Should -Be 0
    }

    It "never flags a host process, whose real payload is an argument" {
        Add-RunValue -Name 'HostedGone' -Command 'rundll32.exe C:\gone\thing.dll,Entry'
        Add-RunValue -Name 'CmdGone' -Command 'cmd.exe /c C:\gone\run.bat'
        @(Get-LeftoverStartupEntries).Count | Should -Be 0
    }

    It "never flags a target under the Windows directory" {
        Add-RunValue -Name 'WinGone' -Command (Join-Path $env:SystemRoot 'System32\pulse-not-a-real-file.exe')
        @(Get-LeftoverStartupEntries).Count | Should -Be 0
    }

    It "uses the cleaned display name and marks the all-users key as needing admin" {
        Add-RunValue -Name 'electron.app.GoneMachineApp' -Command ('"' + (Get-GonePath 'M\app.exe') + '"') -Index 1
        $Item = @(Get-LeftoverStartupEntries)[0]
        $Item.name | Should -Be 'GoneMachineApp'
        $Item.needsAdmin | Should -BeTrue
    }

    It "flags a record Pulse DISABLED once its program is uninstalled" {
        <#
            MEASURED, AND IT REVERSED THE FIRST DESIGN. That exclusion read a
            disabled record as the user's way back. On the machine this was
            built on, all six orphaned entries had already been disabled in
            the Startup Manager - which then showed six MISSING rows while
            the cleaner reported nothing. A way back to an uninstalled
            program leads nowhere.
        #>
        New-Item -Path $Script:StartupDisabledRegPath -Force | Out-Null
        New-ItemProperty -Path $Script:StartupDisabledRegPath -Name 'DisabledGone' `
            -Value ('"' + (Get-GonePath 'D\app.exe') + '"') -PropertyType String -Force | Out-Null
        $Items = @(Get-LeftoverStartupEntries)
        $Items.Count | Should -Be 1
        $Items[0].valueName | Should -Be 'DisabledGone'
        $Items[0].location | Should -Be $Script:StartupDisabledRegPath
        $Items[0].reason | Should -BeLike 'Disabled in Pulse*'
        $Items[0].needsAdmin | Should -BeFalse
    }

    It "spares a DISABLED record whose program is still installed - that one is a way back" {
        New-Item -Path $Script:StartupDisabledRegPath -Force | Out-Null
        New-ItemProperty -Path $Script:StartupDisabledRegPath -Name 'DisabledLive' `
            -Value ('"' + (New-FixtureFile 'DLive\app.exe') + '"') -PropertyType String -Force | Out-Null
        @(Get-LeftoverStartupEntries).Count | Should -Be 0
    }

    It "purges and restores a disabled record" {
        New-Item -Path $Script:StartupDisabledRegPath -Force | Out-Null
        New-ItemProperty -Path $Script:StartupDisabledRegPath -Name 'DisabledCycle' `
            -Value ('"' + (Get-GonePath 'DC\app.exe') + '"') -PropertyType String -Force | Out-Null
        Mock New-SystemRestorePoint { }
        $Item = @(Get-LeftoverStartupEntries)[0]
        (Invoke-LeftoversPurge -SelectedIds @($Item.id)).Removed | Should -Be 1
        @((Get-Item -Path $Script:StartupDisabledRegPath).GetValueNames()) | Should -Not -Contain 'DisabledCycle'
        (Restore-LeftoversBackup).Restored | Should -Be 1
        @((Get-Item -Path $Script:StartupDisabledRegPath).GetValueNames()) | Should -Contain 'DisabledCycle'
    }

    It "flags a Startup-folder shortcut whose target is gone, and spares one that works" {
        $Live = New-FixtureFile 'ShortcutLive\app.exe'
        New-Shortcut -Lnk (Join-Path $Script:StartupFolderPaths[0] 'Live.lnk') -Target $Live
        $Doomed = New-FixtureFile 'ShortcutGone\app.exe'
        New-Shortcut -Lnk (Join-Path $Script:StartupFolderPaths[0] 'Gone.lnk') -Target $Doomed
        Remove-Item -LiteralPath (Split-Path $Doomed -Parent) -Recurse -Force

        $Items = @(Get-LeftoverStartupEntries)
        $Items.Count | Should -Be 1
        $Items[0].kind | Should -Be 'startup-folder'
        $Items[0].name | Should -Be 'Gone'
    }
}

Describe "Get-LeftoverScheduledTasks" {

    BeforeEach {
        Reset-LeftoverFixtures
        $script:FakeTasks = @()
        Mock Get-PulseScheduledTasks { $script:FakeTasks }
    }

    It "flags a third-party task whose program is gone" {
        $Gone = Get-GonePath 'Adobe\Creative Cloud.exe'
        $script:FakeTasks = @(New-FakeTask -Path '\' -Name 'Adobe Uninstaller' -Actions @(New-ExecAction "`"$Gone`""))
        $Items = @(Get-LeftoverScheduledTasks)
        $Items.Count | Should -Be 1
        $Items[0].kind | Should -Be 'task'
        $Items[0].location | Should -Be '\Adobe Uninstaller'
        $Items[0].needsAdmin | Should -BeTrue
    }

    It "never examines \Microsoft\Windows\" {
        $Gone = Get-GonePath 'Anything\gone.exe'
        $script:FakeTasks = @(New-FakeTask -Path '\Microsoft\Windows\Maintenance\' -Name 'Thing' -Actions @(New-ExecAction $Gone))
        @(Get-LeftoverScheduledTasks).Count | Should -Be 0
    }

    It "never flags a task that launches something under the Windows directory" {
        # Measured: \CreateExplorerShellUnelevatedTask sits at the ROOT of
        # the library, outside \Microsoft\Windows\, and runs explorer.exe.
        $script:FakeTasks = @(New-FakeTask -Path '\' -Name 'RootWinTask' -Actions @(
            New-ExecAction (Join-Path $env:SystemRoot 'pulse-not-a-real-file.exe')))
        @(Get-LeftoverScheduledTasks).Count | Should -Be 0
    }

    It "never flags a COM-handler task, which has no path to check" {
        $script:FakeTasks = @(New-FakeTask -Path '\SoftLanding\' -Name 'ComTask' -Actions @(New-ComAction))
        @(Get-LeftoverScheduledTasks).Count | Should -Be 0
    }

    It "spares a task while ANY of its actions still has a program" {
        $Live = New-FixtureFile 'TwoActions\live.exe'
        $Gone = Get-GonePath 'TwoActions\gone.exe'
        $script:FakeTasks = @(New-FakeTask -Path '\' -Name 'Mixed' -Actions @(
            (New-ExecAction $Gone), (New-ExecAction $Live)))
        @(Get-LeftoverScheduledTasks).Count | Should -Be 0
    }

    It "spares a task whose program is a bare name" {
        $script:FakeTasks = @(New-FakeTask -Path '\' -Name 'Bare' -Actions @(New-ExecAction 'powershell.exe'))
        @(Get-LeftoverScheduledTasks).Count | Should -Be 0
    }
}

Describe "Get-LeftoverAppResidue" {

    BeforeEach { Reset-LeftoverFixtures }

    It "flags a Squirrel package its own uninstaller marked dead" {
        $Root = New-DeadSquirrel -Name 'VortxEngine'
        $Items = @(Get-LeftoverAppResidue)
        $Items.Count | Should -Be 1
        $Items[0].kind | Should -Be 'residue'
        $Items[0].location | Should -Be $Root
        $Items[0].sizeBytes | Should -BeGreaterThan 2000
    }

    It "requires BOTH markers - .dead alone is just a filename" {
        $null = New-DeadSquirrel -Name 'OnlyDead' -NoStub
        $null = New-DeadSquirrel -Name 'OnlyStub' -NoDead
        $null = New-DeadSquirrel -Name 'DeadIsAFolder' -DeadIsDirectory
        @(Get-LeftoverAppResidue).Count | Should -Be 0
    }

    It "never flags a folder a running process was launched from" {
        $null = New-DeadSquirrel -Name 'StillRunning'
        Mock Test-FolderInUse { $true }
        @(Get-LeftoverAppResidue).Count | Should -Be 0
    }

    It "never flags the folders Windows and Pulse keep there" {
        foreach ($Name in @('Microsoft', 'Packages', 'Temp', 'PULSE')) {
            $null = New-DeadSquirrel -Name $Name
        }
        @(Get-LeftoverAppResidue).Count | Should -Be 0
    }
}

Describe "Get-LeftoverShellHooks" {

    BeforeEach { Reset-LeftoverFixtures }

    It "flags a context-menu handler whose DLL is gone" {
        $null = Add-Handler -Name 'GoneExtension' -Module (Get-GonePath 'ShellVendor\ext64.dll')
        $Items = @(Get-LeftoverShellHooks)
        $Items.Count | Should -Be 1
        $Items[0].kind | Should -Be 'shell-handler'
        $Items[0].target | Should -Be (Get-GonePath 'ShellVendor\ext64.dll')
    }

    It "spares a handler whose DLL is there, or is named only by a bare module name" {
        $null = Add-Handler -Name 'LiveExtension' -Module (New-FixtureFile 'Live\ext.dll')
        $null = Add-Handler -Name 'SystemExtension' -Module 'shell32.dll'
        @(Get-LeftoverShellHooks).Count | Should -Be 0
    }

    It "spares a handler registered by name rather than by CLSID" {
        $Key = "$script:TestRoot\Handlers\ByName"
        New-Item -Path $Key -Force | Out-Null
        Set-ItemProperty -Path $Key -Name '(default)' -Value 'NotAClsid'
        @(Get-LeftoverShellHooks).Count | Should -Be 0
    }

    It "flags a shell verb whose program is gone, and spares cmd.exe and a live one" {
        Add-Verb -Name 'OpenWithGone' -Command ('"' + (Get-GonePath 'VerbVendor\open.exe') + '" "%1"')
        Add-Verb -Name 'cmd' -Command 'cmd.exe /s /k pushd "%V"'
        Add-Verb -Name 'OpenWithLive' -Command ('"' + (New-FixtureFile 'VerbLive\open.exe') + '" "%1"')
        $Items = @(Get-LeftoverShellHooks)
        $Items.Count | Should -Be 1
        $Items[0].kind | Should -Be 'shell-verb'
        $Items[0].name | Should -Be 'OpenWithGone'
    }
}

Describe "Leftover ids and the combined scan" {

    BeforeEach {
        Reset-LeftoverFixtures
        $script:FakeTasks = @()
        Mock Get-PulseScheduledTasks { $script:FakeTasks }
    }

    It "gives the same item the same id on every scan" {
        Add-RunValue -Name 'GoneStable' -Command ('"' + (Get-GonePath 'S\app.exe') + '"')
        $First  = @(Get-LeftoverStartupEntries)[0].id
        $Second = @(Get-LeftoverStartupEntries)[0].id
        $First | Should -Be $Second
    }

    It "makes ids comma-free, because they travel on a comma-separated parameter" {
        Add-RunValue -Name 'Acme, Inc. Updater' -Command ('"' + (Get-GonePath 'Acme\up.exe') + '"')
        Add-RunValue -Name 'Other' -Command ('"' + (Get-GonePath 'Other\up.exe') + '"')
        $Ids = @(Get-LeftoverStartupEntries | ForEach-Object { $_.id })
        $Ids.Count | Should -Be 2
        foreach ($Id in $Ids) { $Id | Should -Match '^[0-9a-f]{16}$' }
        $Ids[0] | Should -Not -Be $Ids[1]
    }

    It "keeps reporting the other categories when one scanner throws" {
        Add-RunValue -Name 'GoneStillFound' -Command ('"' + (Get-GonePath 'F\app.exe') + '"')
        Mock Get-LeftoverAppResidue { throw 'scanner exploded' }
        @(Get-LeftoverItems | Where-Object { $_.kind -eq 'startup-run' }).Count | Should -Be 1
    }

    It "reports items, total size and backup state" {
        $null = New-DeadSquirrel -Name 'SizedApp'
        Add-RunValue -Name 'GoneSized' -Command ('"' + (Get-GonePath 'Z\app.exe') + '"')
        $Report = Get-LeftoversReport
        @($Report.items).Count | Should -Be 2
        $Report.totalBytes | Should -BeGreaterThan 2000
        $Report.hasBackup | Should -BeFalse
    }
}

# ============================================================
#  PURGE AND RESTORE
# ============================================================
Describe "Invoke-LeftoversPurge" {

    BeforeEach {
        Reset-LeftoverFixtures
        $script:FakeTasks = @()
        Mock Get-PulseScheduledTasks { $script:FakeTasks }
        Mock New-SystemRestorePoint { }
        $Script:SessionFailCount = 0
    }

    It "removes NOTHING when nothing is selected" {
        # The opposite of the bloatware purge, deliberately: there is no
        # curated catalog to fall back on, only what a scan found.
        Add-RunValue -Name 'GoneUntouched' -Command ('"' + (Get-GonePath 'U\app.exe') + '"')
        $Result = Invoke-LeftoversPurge -SelectedIds @()
        $Result.Removed | Should -Be 0
        Get-RunValueNames | Should -Contain 'GoneUntouched'
        Test-Path $Script:LeftoverBackupRegRoot | Should -BeFalse
        Should -Invoke New-SystemRestorePoint -Times 0
    }

    It "removes only what was selected" {
        Add-RunValue -Name 'GoneOne' -Command ('"' + (Get-GonePath 'One\app.exe') + '"')
        Add-RunValue -Name 'GoneTwo' -Command ('"' + (Get-GonePath 'Two\app.exe') + '"')
        $One = @(Get-LeftoverStartupEntries | Where-Object { $_.valueName -eq 'GoneOne' })[0]
        (Invoke-LeftoversPurge -SelectedIds @($One.id)).Removed | Should -Be 1
        Get-RunValueNames | Should -Not -Contain 'GoneOne'
        Get-RunValueNames | Should -Contain 'GoneTwo'
    }

    It "takes the restore point, then the backup set, then backs up before it removes" {
        $Source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "17-Leftovers.ps1") -Raw
        $Body = $Source.Substring($Source.IndexOf("function Invoke-LeftoversPurge"))
        $Body = $Body.Substring(0, $Body.IndexOf("`nfunction "))
        $Restore = $Body.IndexOf("New-SystemRestorePoint")
        $Set     = $Body.IndexOf("New-LeftoversBackupSet")
        $Backup  = $Body.IndexOf("Backup-LeftoverItem")
        $Remove  = $Body.IndexOf("Remove-LeftoverItem")
        $Restore | Should -BeGreaterThan 0
        $Restore | Should -BeLessThan $Set
        $Set     | Should -BeLessThan $Backup
        $Backup  | Should -BeLessThan $Remove
    }

    It "does not remove an item whose backup failed" {
        Add-RunValue -Name 'GoneRefused' -Command ('"' + (Get-GonePath 'R\app.exe') + '"')
        $Item = @(Get-LeftoverStartupEntries)[0]
        Mock Backup-LeftoverItem { return $null }
        $Result = Invoke-LeftoversPurge -SelectedIds @($Item.id)
        $Result.Removed | Should -Be 0
        $Result.Failed | Should -Be 1
        Get-RunValueNames | Should -Contain 'GoneRefused'
    }

    It "spares an item that stopped being a leftover after the scan" {
        <#
            THE PURGE RE-SCANS. The user looked at a list, then reinstalled
            the app, then clicked purge - and the new installation's
            startup entry must survive that.
        #>
        $Gone = Get-GonePath 'Reinstalled\app.exe'
        Add-RunValue -Name 'Reinstalled' -Command "`"$Gone`""
        $Item = @(Get-LeftoverStartupEntries)[0]
        $null = New-FixtureFile 'Reinstalled\app.exe'
        $Result = Invoke-LeftoversPurge -SelectedIds @($Item.id)
        $Result.Removed | Should -Be 0
        $Result.Gone | Should -Be 1
        Get-RunValueNames | Should -Contain 'Reinstalled'
    }

    It "changes nothing under -WhatIf" {
        Add-RunValue -Name 'GoneDryRun' -Command ('"' + (Get-GonePath 'W\app.exe') + '"')
        $Item = @(Get-LeftoverStartupEntries)[0]
        $Script:DryRun = $true
        try {
            $null = Invoke-LeftoversPurge -SelectedIds @($Item.id)
        } finally {
            $Script:DryRun = $false
        }
        Should -Invoke New-SystemRestorePoint -Times 0
        Get-RunValueNames | Should -Contain 'GoneDryRun'
        Test-Path $Script:LeftoverBackupRegRoot | Should -BeFalse
    }

    It "MOVES a dead package into the backup set rather than deleting it" {
        $Root = New-DeadSquirrel -Name 'DeadVendor'
        $Item = @(Get-LeftoverAppResidue)[0]
        (Invoke-LeftoversPurge -SelectedIds @($Item.id)).Removed | Should -Be 1
        Test-Path -LiteralPath $Root | Should -BeFalse
        @(Get-ChildItem -LiteralPath $Script:LeftoverBackupFolderRoot -Recurse -Filter 'resources.bin').Count | Should -Be 1
    }

    It "never deletes a folder or a file - only registry keys are removed outright" {
        $Source = Get-Content -LiteralPath (Join-Path $script:ModuleDir "17-Leftovers.ps1") -Raw
        $Body = $Source.Substring($Source.IndexOf("function Remove-LeftoverItem"))
        $Body = $Body.Substring(0, $Body.IndexOf("`nfunction "))
        ([regex]::Matches($Body, 'Remove-Item ')).Count | Should -Be 1 -Because "the only Remove-Item is for shell registry keys"
        $Body | Should -BeLike '*Remove-Item -LiteralPath $Export.key*'
    }

    It "exports a task definition BEFORE unregistering it" {
        $Gone = Get-GonePath 'TaskVendor\updater.exe'
        $script:FakeTasks = @(New-FakeTask -Path '\TaskVendor\' -Name 'Updater' -Actions @(New-ExecAction "`"$Gone`""))
        $script:Calls = New-Object System.Collections.ArrayList
        Mock Export-PulseScheduledTask { [void]$script:Calls.Add('export'); return '<Task version="1.2" />' }
        Mock Unregister-PulseScheduledTask { [void]$script:Calls.Add('unregister') }
        $Item = @(Get-LeftoverScheduledTasks)[0]
        (Invoke-LeftoversPurge -SelectedIds @($Item.id)).Removed | Should -Be 1
        @($script:Calls) | Should -Be @('export', 'unregister')
    }

    It "leaves a task in place when its definition cannot be exported" {
        $Gone = Get-GonePath 'NoExport\updater.exe'
        $script:FakeTasks = @(New-FakeTask -Path '\' -Name 'NoExport' -Actions @(New-ExecAction "`"$Gone`""))
        Mock Export-PulseScheduledTask { return '' }
        Mock Unregister-PulseScheduledTask { }
        $Item = @(Get-LeftoverScheduledTasks)[0]
        (Invoke-LeftoversPurge -SelectedIds @($Item.id)).Removed | Should -Be 0
        Should -Invoke Unregister-PulseScheduledTask -Times 0
    }
}

Describe "Restore-LeftoversBackup" {

    BeforeEach {
        Reset-LeftoverFixtures
        $script:FakeTasks = @()
        Mock Get-PulseScheduledTasks { $script:FakeTasks }
        Mock New-SystemRestorePoint { }
        $Script:SessionFailCount = 0
    }

    It "says so when there is nothing to restore" {
        $Result = Restore-LeftoversBackup
        $Result.Restored | Should -Be 0
        $Result.Failed | Should -Be 0
    }

    It "puts a Run value back EXACTLY, including an unexpanded REG_EXPAND_SZ" {
        <#
            A backup that read the value normally would have stored the
            EXPANDED path as a plain REG_SZ, and a restore would put back
            something that looks right and has quietly stopped following
            the variable.
        #>
        $Raw = '%TEMP%\PulsePesterLeftovers\Programs\Expand\gone.exe'
        Add-RunValue -Name 'GoneExpand' -Command "`"$Raw`"" -Kind 'ExpandString'
        $Item = @(Get-LeftoverStartupEntries)[0]
        (Invoke-LeftoversPurge -SelectedIds @($Item.id)).Removed | Should -Be 1
        Get-RunValueNames | Should -Not -Contain 'GoneExpand'

        (Restore-LeftoversBackup).Restored | Should -Be 1
        $Key = Get-Item -Path $Script:StartupRunKeyPaths[0]
        $Key.GetValue('GoneExpand', $null, 'DoNotExpandEnvironmentNames') | Should -Be "`"$Raw`""
        [string]$Key.GetValueKind('GoneExpand') | Should -Be 'ExpandString'
    }

    It "moves a dead package back where it was" {
        $Root = New-DeadSquirrel -Name 'ComeBack'
        $Item = @(Get-LeftoverAppResidue)[0]
        $null = Invoke-LeftoversPurge -SelectedIds @($Item.id)
        (Restore-LeftoversBackup).Restored | Should -Be 1
        Test-Path -LiteralPath (Join-Path $Root 'app-1.0.0\resources.bin') | Should -BeTrue
    }

    It "moves a Startup shortcut back" {
        $Doomed = New-FixtureFile 'LnkBack\app.exe'
        $Lnk = Join-Path $Script:StartupFolderPaths[0] 'LnkBack.lnk'
        New-Shortcut -Lnk $Lnk -Target $Doomed
        Remove-Item -LiteralPath (Split-Path $Doomed -Parent) -Recurse -Force
        $Item = @(Get-LeftoverStartupEntries)[0]
        $null = Invoke-LeftoversPurge -SelectedIds @($Item.id)
        Test-Path -LiteralPath $Lnk | Should -BeFalse
        (Restore-LeftoversBackup).Restored | Should -Be 1
        Test-Path -LiteralPath $Lnk | Should -BeTrue
    }

    It "re-registers a task from the XML it exported" {
        $Gone = Get-GonePath 'TaskBack\updater.exe'
        $script:FakeTasks = @(New-FakeTask -Path '\TaskBack\' -Name 'Updater' -Actions @(New-ExecAction "`"$Gone`""))
        Mock Export-PulseScheduledTask { return '<Task version="1.2" />' }
        Mock Unregister-PulseScheduledTask { }
        Mock Register-PulseScheduledTask { $script:Registered = "$TaskPath|$TaskName|$Xml" }
        $Item = @(Get-LeftoverScheduledTasks)[0]
        $null = Invoke-LeftoversPurge -SelectedIds @($Item.id)
        (Restore-LeftoversBackup).Restored | Should -Be 1
        $script:Registered | Should -Be '\TaskBack\|Updater|<Task version="1.2" />'
    }

    It "restores a shell verb under ErrorActionPreference Stop, the way core.ps1 runs" {
        <#
            THE BUG THIS PINS IS INVISIBLE UNDER PESTER. reg.exe import
            reports SUCCESS on stderr. core.ps1 sets
            $ErrorActionPreference = "Stop", and under that preference a
            native command's stderr line becomes a terminating error - so
            a restore that WORKED threw, was caught, and was reported as a
            failure. Pester runs with "Continue", where the same code
            passes. This test sets the production preference explicitly.
        #>
        Add-Verb -Name 'OpenWithGone' -Command ('"' + (Get-GonePath 'VerbBack\open.exe') + '" "%1"')
        $Item = @(Get-LeftoverShellHooks)[0]
        $Previous = $ErrorActionPreference
        $ErrorActionPreference = 'Stop'
        try {
            (Invoke-LeftoversPurge -SelectedIds @($Item.id)).Removed | Should -Be 1
            Test-Path "$script:TestRoot\Verbs\OpenWithGone" | Should -BeFalse
            $Result = Restore-LeftoversBackup
        } finally {
            $ErrorActionPreference = $Previous
        }
        $Result.Failed | Should -Be 0
        $Result.Restored | Should -Be 1
        (Get-ItemProperty -Path "$script:TestRoot\Verbs\OpenWithGone\command").'(default)' |
            Should -BeLike '*VerbBack\open.exe*'
    }

    It "restores a context-menu handler key from its export" {
        $null = Add-Handler -Name 'HandlerBack' -Module (Get-GonePath 'HB\ext.dll')
        $Item = @(Get-LeftoverShellHooks)[0]
        $null = Invoke-LeftoversPurge -SelectedIds @($Item.id)
        Test-Path "$script:TestRoot\Handlers\HandlerBack" | Should -BeFalse
        (Restore-LeftoversBackup).Restored | Should -Be 1
        Test-Path "$script:TestRoot\Handlers\HandlerBack" | Should -BeTrue
    }

    It "marks a set restored, so a second restore does nothing" {
        Add-RunValue -Name 'GoneOnce' -Command ('"' + (Get-GonePath 'O\app.exe') + '"')
        $Item = @(Get-LeftoverStartupEntries)[0]
        $null = Invoke-LeftoversPurge -SelectedIds @($Item.id)
        (Restore-LeftoversBackup).Restored | Should -Be 1
        (Restore-LeftoversBackup).Restored | Should -Be 0
        (Get-LeftoversReport).hasBackup | Should -BeFalse
    }

    It "leaves a set UNRESTORED when a record cannot come back, so it can be retried" {
        $Root = New-DeadSquirrel -Name 'Occupied'
        $Item = @(Get-LeftoverAppResidue)[0]
        $null = Invoke-LeftoversPurge -SelectedIds @($Item.id)
        New-Item -Path $Root -ItemType Directory -Force | Out-Null
        $Result = Restore-LeftoversBackup
        $Result.Failed | Should -Be 1
        Get-LatestLeftoversBackup | Should -Not -BeNullOrEmpty
    }
}
