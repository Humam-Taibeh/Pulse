<#
.SYNOPSIS
    Build PULSE's release artifacts: the onedir bundle, the Setup wizard
    and the checksum file the updater verifies against.

.DESCRIPTION
    One command, three outputs:

        dist\PULSE\                      the installable directory
        dist\PULSE_Setup_v<VERSION>.exe  the Setup wizard
        dist\SHA256SUMS                  digests for both

    SHA256SUMS IS NOT OPTIONAL. src/utils/updater.py refuses to execute a
    downloaded installer whose digest does not appear in it, so a release
    published without this file is a release the updater will decline —
    silently and correctly. It is produced here rather than by CI so that
    a locally built installer can be verified the same way.

    Everything is stamped from the repo's VERSION file. Nothing in this
    script names a version.

.PARAMETER SkipInstaller
    Build only the PyInstaller bundle. For iterating on the app without
    Inno Setup installed.

.PARAMETER KeepBuild
    Leave build\ in place. The default is a clean build, because a stale
    build\ is the usual cause of "the fix isn't in the exe".

.EXAMPLE
    .\tools\build_release.ps1
    .\tools\build_release.ps1 -SkipInstaller
#>
[CmdletBinding()]
param(
    [switch]$SkipInstaller,
    [switch]$KeepBuild,
    # Authenticode-signs PULSE.exe and the compiled installer when set. A
    # THUMBPRINT, not a PFX path/password: signtool looks the certificate up
    # in the Windows certificate store, so no private-key material ever
    # passes through this script's arguments, environment, or a build log.
    # Defaults to $env:PULSE_SIGN_THUMBPRINT so CI can configure it without
    # a script change. See tools/create_dev_signing_cert.ps1 for a TEST-ONLY
    # certificate to exercise this path — it does not make a signed build
    # trusted by anyone but the machine that made it; only a certificate
    # chained to a CA in Microsoft's trust program does that (ROADMAP.md,
    # "Code signing via Azure Trusted Signing").
    [string]$SignThumbprint = $env:PULSE_SIGN_THUMBPRINT
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $RepoRoot 'dist'
$BuildDir = Join-Path $RepoRoot 'build'
$BundleDir = Join-Path $DistDir 'PULSE'

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Detail([string]$Text) {
    Write-Host "    $Text" -ForegroundColor DarkGray
}

# ============================================================
#  PREFLIGHT
# ============================================================
# Checked up front, together, so a missing tool costs seconds rather than
# surfacing four minutes into a PyInstaller run.
Write-Step 'Preflight'

$VersionFile = Join-Path $RepoRoot 'VERSION'
if (-not (Test-Path -LiteralPath $VersionFile)) {
    throw "VERSION not found at $VersionFile — it is the single source every artifact is stamped from."
}
$Version = (Get-Content -LiteralPath $VersionFile -TotalCount 1).Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "VERSION is '$Version'; releases are tagged v<VERSION> so it must be MAJOR.MINOR.PATCH."
}
Write-Detail "version         $Version"

# The GUI and the engine read VERSION at runtime, so a mismatch here means
# the shipped app would disagree with its own installer. test_contract.py
# pins the same thing; this repeats it because a release must never depend
# on someone having run the suite first.
$MainPy = Get-Content -LiteralPath (Join-Path $RepoRoot 'src\frontend\main.py') -Raw
if ($MainPy -notmatch 'APP_VERSION\s*=\s*version\.VERSION') {
    throw 'src/frontend/main.py no longer reads its version from utils.version — the artifacts would be stamped inconsistently.'
}
$CorePs1 = Get-Content -LiteralPath (Join-Path $RepoRoot 'src\backend\core.ps1') -Raw
if ($CorePs1 -match '\$Script:ScriptVersion\s*=\s*"([^"]+)"') {
    $Fallback = $Matches[1]
    if ($Fallback -ne $Version) {
        throw "core.ps1's fallback version is '$Fallback' but VERSION is '$Version'."
    }
    Write-Detail "core.ps1 fallback matches"
}

$Python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Python) { throw 'python is not on PATH.' }
Write-Detail "python          $($Python.Source)"

& python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller is not installed. Run: pip install -r requirements-dev.txt'
}
Write-Detail 'PyInstaller     present'

$Iscc = $null
if (-not $SkipInstaller) {
    # The per-user path is FIRST-CLASS, not a fallback: `winget install
    # JRSoftware.InnoSetup` installs to %LOCALAPPDATA%\Programs by default,
    # which is where anyone following the README's own suggestion ends up.
    # The two Program Files paths only cover the machine-wide installer, so
    # a winget install produced "ISCC.exe was not found" on a machine that
    # had just installed it successfully.
    # THE OUTER @() IS LOAD-BEARING. `@(...) | Where-Object` returns a
    # SCALAR when exactly one candidate survives, and $Candidates[0] on a
    # scalar string is its first CHARACTER — so a machine with exactly one
    # Inno Setup install resolved $Iscc to "C" and the preflight printed
    # `iscc  C` before failing several minutes later at the invocation.
    # Two installs hid it; one is the normal case.
    $Candidates = @(@(
        (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) })
    if (-not $Candidates) {
        throw 'Inno Setup 6 (ISCC.exe) was not found. Install it from https://jrsoftware.org/isdl.php, or pass -SkipInstaller.'
    }
    $Iscc = $Candidates[0]
    Write-Detail "iscc            $Iscc"
}

# SIGNING IS OPT-IN AND OFF BY DEFAULT. No certificate is configured for
# most runs of this script, and that must produce an ordinary unsigned
# build exactly as it always has — not a warning nobody asked for, and
# not a throw. It becomes mandatory-and-loud only once a caller HAS asked
# for it: passing -SignThumbprint and then silently shipping unsigned
# because signtool was missing would be worse than not offering signing
# at all, because a "signed" build claim in the CI log would be a lie.
$SignTool = $null
$SigningCert = $null
if ($SignThumbprint) {
    # Same @() scalar hazard as the ISCC lookup above (Where-Object
    # collapses a single surviving candidate to a bare string).
    $SignToolCandidates = @(@(
        (Get-Command signtool.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        # Windows Kits ships one signtool.exe per SDK version per
        # architecture; take the newest SDK's x64 build. A hand-picked
        # single path would break on the next SDK update.
        (Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin" `
            -Filter 'signtool.exe' -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -like '*\x64\*' } |
                Sort-Object FullName -Descending |
                Select-Object -First 1 -ExpandProperty FullName)
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) })
    if (-not $SignToolCandidates) {
        throw 'signtool.exe was not found. Install the Windows SDK (or Visual Studio''s "Windows 10/11 SDK" component), or omit -SignThumbprint to build unsigned.'
    }
    $SignTool = $SignToolCandidates[0]
    Write-Detail "signtool        $SignTool"

    # Fail before spending four minutes in PyInstaller, not after: a typo'd
    # thumbprint or an expired dev cert should be a ten-second preflight
    # error, not a surprise at the signing step with a finished bundle
    # sitting there unsigned.
    $SigningCert = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -ErrorAction SilentlyContinue |
        Where-Object { $_.Thumbprint -eq $SignThumbprint } | Select-Object -First 1
    if (-not $SigningCert) {
        throw "No certificate with thumbprint $SignThumbprint was found in CurrentUser\My or LocalMachine\My. Run tools\create_dev_signing_cert.ps1 for a test certificate, or check the thumbprint against your real one."
    }
    if ($SigningCert.NotAfter -lt (Get-Date)) {
        throw "The certificate $SignThumbprint expired on $($SigningCert.NotAfter.ToString('yyyy-MM-dd'))."
    }
    Write-Detail "sign cert       $($SigningCert.Subject) (expires $($SigningCert.NotAfter.ToString('yyyy-MM-dd')))"
    # A self-signed dev certificate builds a mechanically valid signature
    # that satisfies nobody's trust chain but this machine's. Said loudly
    # here, not just in create_dev_signing_cert.ps1's header, because this
    # is the point in the log a CI run or a teammate would actually see it.
    if ($SigningCert.Issuer -eq $SigningCert.Subject) {
        Write-Warning "Certificate $SignThumbprint is self-signed. The resulting build will NOT be trusted by SmartScreen or Smart App Control on any machine but this one — this proves the signing pipeline works, it does not ship a trusted release."
    }
}
else {
    Write-Detail 'signing         skipped (no -SignThumbprint / $env:PULSE_SIGN_THUMBPRINT)'
}

function Sign-Artifact([string]$Path) {
    # No-op when signing was never requested — every call site calls this
    # unconditionally so the "did we sign it" decision lives in ONE place.
    if (-not $SignTool) { return }
    Write-Detail "signing $(Split-Path -Leaf $Path)"
    $Previous = $ErrorActionPreference     # see the PyInstaller/ISCC calls
    $ErrorActionPreference = 'Continue'
    try {
        # RFC3161 timestamping (/tr + /td), not the legacy /t: a timestamped
        # signature stays valid after the certificate itself expires, which
        # matters most for exactly the 3-year dev certificate this script
        # is likeliest to be pointed at. DigiCert's responder is public and
        # free to query regardless of who issued the signing certificate.
        & $SignTool sign /sha1 $SignThumbprint /fd sha256 `
            /tr 'http://timestamp.digicert.com' /td sha256 `
            /d 'PULSE' $Path
    }
    finally {
        $ErrorActionPreference = $Previous
    }
    if ($LASTEXITCODE -ne 0) { throw "signtool sign failed ($LASTEXITCODE) on $Path." }

    # Trust the exit code, not the eye: verify the signature signtool just
    # produced actually validates before this artifact ships as "signed".
    # Confirmed empirically: signtool sign succeeds unconditionally, even
    # with a self-signed certificate nobody trusts — verify is the step
    # that actually distinguishes "mechanically signed" from "trusted".
    & $SignTool verify /pa /q $Path
    if ($LASTEXITCODE -ne 0) {
        $Hint = if ($SigningCert.Issuer -eq $SigningCert.Subject) {
            ' This is the expected result for a self-signed certificate this ' +
            'machine has not been told to trust — re-run ' +
            'tools\create_dev_signing_cert.ps1 with -TrustLocally to make this ' +
            'machine''s own verification pass, or treat this as confirmation ' +
            'that the pipeline works rather than a build to ship.'
        } else { '' }
        throw "signtool verify failed on $Path — the signature it just wrote does not validate.$Hint"
    }
}

# A dirty tree is not fatal — a technician may be testing an unreleased fix
# — but a release built from uncommitted code that nobody can reproduce is
# worth one line of warning.
$GitStatus = & git -C $RepoRoot status --porcelain 2>$null
if ($LASTEXITCODE -eq 0 -and $GitStatus) {
    Write-Warning "Working tree has uncommitted changes; this build will not be reproducible from a tag."
}

# ============================================================
#  CLEAN
# ============================================================
Write-Step 'Clean'
# A locked artifact is NOT fatal. Anything holding a handle on dist\PULSE —
# the app still running, Explorer sitting in the folder, a shell whose
# working directory is inside it — would otherwise abort a build that
# PyInstaller's --noconfirm is perfectly able to finish by overwriting in
# place. Warn, and let the payload verification below decide whether the
# result is actually sound.
foreach ($Path in @($BundleDir, (Join-Path $DistDir "PULSE_Setup_v$Version.exe"), (Join-Path $DistDir 'SHA256SUMS'))) {
    if (Test-Path -LiteralPath $Path) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            Write-Detail "removed $(Split-Path -Leaf $Path)"
        }
        catch {
            Write-Warning "Could not remove $(Split-Path -Leaf $Path) (in use); it will be overwritten in place."
        }
    }
}
if (-not $KeepBuild -and (Test-Path -LiteralPath $BuildDir)) {
    Remove-Item -LiteralPath $BuildDir -Recurse -Force
    Write-Detail 'removed build\'
}

# ============================================================
#  MODULE MANIFEST
# ============================================================
# WRITTEN BEFORE PYINSTALLER, and that ordering is the whole delivery
# mechanism: main.spec copies src/backend/modules wholesale, so a manifest
# sitting inside that directory ships with the tree it describes and needs
# no spec entry of its own. A separate datas line would be one more thing
# to forget - which this project has done before, and shipped v10.9.0 with
# no vendor artwork because of it.
#
# core.ps1 verifies against this before dot-sourcing anything (see its
# INTEGRITY GATE): the loader globs *.ps1 and executes what it finds under
# an Administrator token, so on any deployment where that folder is
# user-writable - a source checkout, the planned portable ZIP - dropping a
# file in was enough to get elevated execution.
#
# Regenerated every build rather than updated: it describes THIS bundle,
# and a stale entry is indistinguishable from a tampered file to the check
# that reads it.
Write-Step 'Module manifest'
$ModulesDir = Join-Path $RepoRoot 'src\backend\modules'
$ManifestPath = Join-Path $ModulesDir 'MANIFEST.sha256'
if (Test-Path -LiteralPath $ManifestPath) { Remove-Item -LiteralPath $ManifestPath -Force }
$ManifestLines = @()
foreach ($Module in (Get-ChildItem -LiteralPath $ModulesDir -Filter '*.ps1' -File | Sort-Object Name)) {
    $Hash = (Get-FileHash -LiteralPath $Module.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $ManifestLines += "$Hash  $($Module.Name)"
}
if ($ManifestLines.Count -eq 0) {
    throw "No backend modules found in $ModulesDir - the manifest would disable the integrity gate it exists to arm."
}
# Same "<lowercase sha256>  <filename>" shape as SHA256SUMS, so there is
# one format to recognise. UTF8 without BOM: core.ps1 reads it back with
# Get-Content and a BOM would corrupt the first digest.
[System.IO.File]::WriteAllLines($ManifestPath, $ManifestLines, (New-Object System.Text.UTF8Encoding($false)))
Write-Detail "manifest        $($ManifestLines.Count) modules hashed"

# ============================================================
#  BUNDLE
# ============================================================
Write-Step 'PyInstaller (onedir)'
Push-Location $RepoRoot
try {
    # $ErrorActionPreference is 'Stop' for this script, and in Windows
    # PowerShell that makes ANY line a native executable writes to stderr a
    # terminating error. PyInstaller logs its entire INFO stream there, so
    # a completely successful build would abort on its first line of
    # output. The exit code is the only honest success signal for a native
    # command; relax the preference around the call and test that instead.
    $Previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & python -m PyInstaller --noconfirm main.spec
    }
    finally {
        $ErrorActionPreference = $Previous
    }
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}

$ExePath = Join-Path $BundleDir 'PULSE.exe'
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Expected $ExePath — the spec's COLLECT name or EXE name changed."
}

# The version resource is what Windows shows in Properties and what the
# updater compares an installed build against. Its absence was invisible
# before precisely because nothing ever looked.
$Stamped = (Get-Item -LiteralPath $ExePath).VersionInfo.FileVersion
if (-not $Stamped) {
    throw 'PULSE.exe carries no version resource — the spec is not passing version_info to EXE().'
}
Write-Detail "PULSE.exe       FileVersion $Stamped"
if ($Stamped.Split('.')[0..2] -join '.' -ne $Version) {
    throw "PULSE.exe reports '$Stamped' but VERSION is '$Version'."
}

# Signed before the payload checks below, not after: if signing corrupts
# the binary somehow, the checks that follow are the ones that would
# actually notice, rather than shipping a broken exe that merely LOOKS
# signed.
Sign-Artifact $ExePath

# Onedir means the payload is real files rather than an embedded archive.
# PyInstaller 6.x puts all of it under _internal\, which IS _MEIPASS — so
# resources.bundled_roots() resolves there, and core.ps1's "..\..\VERSION"
# (from _internal\src\backend\) lands on _internal\VERSION. Both correct,
# but only because the tree keeps this exact shape: verify it rather than
# discover a broken engine after shipping.
foreach ($Rel in @('_internal',
                   '_internal\VERSION',
                   '_internal\src\backend\core.ps1',
                   '_internal\src\backend\modules',
                   '_internal\playbooks',
                   '_internal\assets\pulse.ico',
                   # The brand marks and their manifest. THIS LINE WAS NOT
                   # HERE, and this list is the last thing standing between
                   # a spec omission and a shipped build: v10.9.0 went out
                   # with no 'assets/appicons' entry in main.spec, so every
                   # catalog row fell back to the neutral grey glyph in the
                   # released build only. The check above passed because it
                   # only ever asked about pulse.ico.
                   '_internal\assets\appicons\manifest.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $BundleDir $Rel))) {
        throw "The bundle is missing '$Rel' — check the spec's datas."
    }
}
# The manifest is only an index; a bundle carrying it with no artwork
# beside it would pass the check above and still paint nothing.
$MarkCount = @(Get-ChildItem -LiteralPath (Join-Path $BundleDir '_internal\assets\appicons') `
    -Filter *.svg -File -ErrorAction SilentlyContinue).Count
if ($MarkCount -lt 1) {
    throw 'The bundle carries no brand marks — check the spec''s datas.'
}
Write-Detail "brand marks     $MarkCount bundled"
# The engine's one relative path, resolved exactly as core.ps1 resolves it.
$EngineVersionPath = Join-Path $BundleDir '_internal\src\backend\..\..\VERSION'
if (-not (Test-Path -LiteralPath $EngineVersionPath)) {
    throw 'core.ps1 would not find VERSION in this bundle layout.'
}
$BundledVersion = (Get-Content -LiteralPath $EngineVersionPath -TotalCount 1).Trim()
if ($BundledVersion -ne $Version) {
    throw "The bundled VERSION says '$BundledVersion' but this build is '$Version'."
}
Write-Detail 'bundle payload  complete'

$BundleSize = (Get-ChildItem -LiteralPath $BundleDir -Recurse -File |
    Measure-Object -Property Length -Sum).Sum / 1MB
Write-Detail ("bundle size     {0:N1} MB" -f $BundleSize)

# ============================================================
#  INSTALLER
# ============================================================
$SetupPath = Join-Path $DistDir "PULSE_Setup_v$Version.exe"
if (-not $SkipInstaller) {
    Write-Step 'Inno Setup'
    $Previous = $ErrorActionPreference     # see the note on the PyInstaller call
    $ErrorActionPreference = 'Continue'
    try {
        & $Iscc "/DMyAppVersion=$Version" (Join-Path $RepoRoot 'installer\pulse.iss')
    }
    finally {
        $ErrorActionPreference = $Previous
    }
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE." }
    if (-not (Test-Path -LiteralPath $SetupPath)) {
        throw "Expected $SetupPath — OutputBaseFilename in pulse.iss no longer matches."
    }
    # Signed before the size is reported, so the number printed is the one
    # that actually ships — an Authenticode signature adds a few KB.
    Sign-Artifact $SetupPath
    Write-Detail ("setup size      {0:N1} MB" -f ((Get-Item -LiteralPath $SetupPath).Length / 1MB))
}

# ============================================================
#  CHECKSUMS
# ============================================================
# Format: "<lowercase sha256>  <filename>", i.e. sha256sum's. The updater
# parses exactly this, and publishing it as a release asset is what lets a
# download be verified before it is executed.
Write-Step 'SHA256SUMS'
$SumsPath = Join-Path $DistDir 'SHA256SUMS'
$Lines = @()
foreach ($Target in @($SetupPath)) {
    if (Test-Path -LiteralPath $Target) {
        $Hash = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant()
        $Name = Split-Path -Leaf $Target
        $Lines += "$Hash  $Name"
        Write-Detail "$Hash  $Name"
    }
}
if ($Lines.Count -eq 0) {
    Write-Warning 'Nothing to checksum (installer was skipped); SHA256SUMS not written.'
}
else {
    # UTF8 without BOM: the updater and sha256sum both read this as ASCII,
    # and a BOM would corrupt the first digest.
    [System.IO.File]::WriteAllLines($SumsPath, $Lines, (New-Object System.Text.UTF8Encoding($false)))
}

# ============================================================
#  DONE
# ============================================================
Write-Step 'Done'
Write-Host "    PULSE $Version" -ForegroundColor Green
if ($SignTool) {
    $Tone = if ($SigningCert.Issuer -eq $SigningCert.Subject) { 'Yellow' } else { 'Green' }
    $Note = if ($SigningCert.Issuer -eq $SigningCert.Subject) { ' (self-signed — see the preflight warning above)' } else { '' }
    Write-Host "    signed    yes, by $($SigningCert.Subject)$Note" -ForegroundColor $Tone
}
else {
    Write-Host "    signed    no — pass -SignThumbprint to sign this build" -ForegroundColor DarkGray
}
Write-Host "    bundle    $BundleDir"
if (-not $SkipInstaller) {
    Write-Host "    installer $SetupPath"
    Write-Host "    checksums $SumsPath"
    Write-Host ''
    Write-Host '    Next:' -ForegroundColor Yellow
    Write-Host "      git tag -a v$Version -m 'PULSE v$Version'  &&  git push origin v$Version"
    Write-Host '      Attach the installer AND SHA256SUMS to the GitHub release —'
    Write-Host '      the updater declines any download it cannot verify.'
}
