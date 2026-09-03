"""
The release pipeline: spec -> bundle -> installer -> checksums.

None of this runs PyInstaller or Inno Setup — that takes minutes and needs
both installed. What it pins is the set of facts the artifacts depend on,
each of which has a failure that only appears in a shipped build:

    a onefile regression      -> seconds of cold start, engine in %TEMP%
    a changed AppId           -> upgrades install a second copy
    a drifting version        -> the updater compares against the wrong thing
    a renamed installer       -> every release silently has "no installer"
    a dropped SHA256SUMS      -> the updater declines every update
"""
from __future__ import annotations

import os
import re

import pytest

from utils import updater, version

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts: str) -> str:
    with open(os.path.join(_ROOT, *parts), encoding="utf-8-sig") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def spec() -> str:
    return _read("main.spec")


@pytest.fixture(scope="module")
def iss() -> str:
    return _read("installer", "pulse.iss")


@pytest.fixture(scope="module")
def build_script() -> str:
    return _read("tools", "build_release.ps1")


# ============================================================
#  THE SPEC
# ============================================================
def test_the_build_is_onedir_not_onefile(spec):
    """Onefile re-extracts the whole bundle to %TEMP% on EVERY launch, and
    puts the elevated PowerShell engine in a user-writable directory —
    the exact hazard utils/resources.py documents. exclude_binaries=True
    plus COLLECT is what makes it onedir; drop either and it silently
    reverts."""
    assert "COLLECT(" in spec, "the spec no longer collects a onedir bundle"
    assert re.search(r"exclude_binaries\s*=\s*True", spec), (
        "EXE() is embedding the payload again — this is a onefile build")


def test_every_runtime_resource_is_actually_bundled(spec):
    """THE SPEC IS A SECOND LIST OF WHAT THE APP NEEDS, and nothing joined
    it to the first.

    Anything reached through resources.find_resource() / resource_dirs()
    is resolved, in a frozen build, ONLY under _MEIPASS — bundled_roots()
    returns the bundle and nothing else. So a path the code asks for and
    the spec does not carry simply is not there at runtime.

    That is not hypothetical. v10.9.0 — the release whose headline was
    "in the vendors' own colours" — shipped with no `assets/appicons`
    entry, so not one of the 37 brand marks was in the bundle. Every
    catalog row fell through to the neutral grey glyph, on the released
    build only, and the whole suite stayed green: appicons._manifest()
    degrades a missing manifest to "no bundled marks" by design, and every
    icon test reads the SOURCE tree. Nothing anywhere looked in the bundle.

    This joins the two lists. It reads the resource paths out of the code
    that asks for them, so a new one is covered the day it is written
    rather than the day someone remembers to add a test.
    """
    import glob

    sources = {os.path.relpath(p, _ROOT): _read(os.path.relpath(p, _ROOT))
               for p in glob.glob(os.path.join(_ROOT, "src", "**", "*.py"),
                                  recursive=True)}

    # Module-level string constants, so an f-string placeholder resolves to
    # the path it will actually ask for rather than being skipped — the
    # skip is where a blind spot like the appicons one hides.
    constants: dict[str, str] = {}
    for text in sources.values():
        for name, value in re.findall(
                r"""^([A-Z][A-Z0-9_]*)\s*=\s*["']([^"']+)["']""", text, re.M):
            constants.setdefault(name, value)

    def resolve(literal: str) -> str:
        """The path this call asks for, reduced to what can be checked.

        A `{NAME}` placeholder is substituted from the constants above. One
        holding an EXPRESSION (`{entry.get('file', '')}`) cannot be, so the
        literal is cut back to its deepest fixed directory instead — which
        is the right question anyway: code building
        `assets/appicons/<whatever>` needs `assets/appicons` in the bundle
        however the leaf is spelled.
        """
        literal = re.sub(r"\{(\w+)\}",
                         lambda m: constants.get(m.group(1), m.group(0)),
                         literal)
        if "{" in literal:
            literal = literal[:literal.index("{")].rstrip("/")
        return literal

    # ONE GROUP PER CALL SITE, because find_resource takes ALTERNATIVES and
    # returns the first that exists — the core.ps1 lookup names four
    # candidate layouts and the bundle only ever carries one of them.
    # Requiring all four would demand files that must not exist.
    groups: list[tuple[str, list[str]]] = []
    for name, text in sources.items():
        if os.path.basename(name) == "resources.py":
            continue                      # defines the helpers, uses neither
        for pattern in (r"find_resource\((.*?)\)\s*$",
                        r"find_resource\(([^)]*)\)",
                        r"resource_dirs\(([^),]*)"):
            for args in re.findall(pattern, text, re.S | re.M):
                alts = [resolve(lit) for lit in
                        re.findall(r"""["']([^"']+)["']""", args)]
                # Keep only things shaped like a path: the separator inside
                # `entry.get('file', '')` is a string literal too.
                alts = [a for a in alts
                        if a and re.fullmatch(r"[\w./-]+", a)]
                if alts:
                    groups.append((name, alts))
    # PLAYBOOK_DIRNAME reaches resource_dirs as a name, not a literal.
    groups.append(("frontend/playbooks.py",
                   [constants.get("PLAYBOOK_DIRNAME", "playbooks")]))

    assert len(groups) >= 4, (
        f"the scanner found only {groups} — it has stopped matching the "
        "call sites and would pass for the wrong reason")
    assert any("assets/appicons" in alts for _f, alts in groups), (
        "the scanner no longer sees the brand-mark lookup, which is the "
        "case this test was written for")

    # What the spec's datas actually place in the bundle, as source paths.
    # Scoped to the datas=[...] block: the version resource further down is
    # also a list of ('name', 'value') tuples and would otherwise be read
    # as if StringStruct fields were bundled files.
    datas_block = re.search(r"datas\s*=\s*\[(.*?)\n\s*\],", spec, re.S)
    assert datas_block, "main.spec has no datas=[...] block"
    bundled = [src.replace("\\", "/")
               for src, _dest in re.findall(
                   r"\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)",
                   datas_block.group(1))]

    def carried(rel: str) -> bool:
        rel = rel.rstrip("/")
        return any(rel == b.rstrip("/")
                   or rel.startswith(b.rstrip("/") + "/")
                   or os.path.dirname(rel) == b.rstrip("/")
                   for b in bundled)

    missing = [(where, alts) for where, alts in groups
               if not any(carried(a) for a in alts)]
    assert not missing, (
        "code resolves these through resources.find_resource()/"
        "resource_dirs(), but main.spec bundles none of the candidates, so "
        f"they are absent from the frozen build ONLY: {missing}\n"
        f"spec datas: {bundled}")


def test_the_exe_carries_a_version_resource(spec):
    """Without it the Properties tab is blank, AV heuristics have nothing
    to weigh, and the updater has no authoritative installed version."""
    assert "VSVersionInfo(" in spec
    assert re.search(r"version\s*=\s*version_info", spec)


def test_the_version_resource_is_derived_not_typed(spec):
    """Every string is stamped from VERSION. A literal here is a fifth copy
    of the version, and the one nobody thinks to update."""
    assert "open(os.path.join(_here, 'VERSION')" in spec
    assert re.search(r"StringStruct\('FileVersion',\s*APP_VERSION\)", spec)
    assert re.search(r"StringStruct\('ProductVersion',\s*APP_VERSION\)", spec)
    assert not re.search(r"StringStruct\('FileVersion',\s*'[\d.]+'\)", spec), (
        "the version resource carries a hardcoded version")


def test_the_spec_imports_what_it_uses(spec):
    """PyInstaller 6.x does not inject these into the spec namespace; a
    spec that uses them without importing fails with a bare NameError
    several minutes into the build."""
    assert "from PyInstaller.utils.win32.versioninfo import" in spec
    for name in ("VSVersionInfo", "FixedFileInfo", "StringFileInfo",
                 "StringTable", "StringStruct", "VarFileInfo", "VarStruct"):
        assert name in spec, name


def test_upx_stays_disabled(spec):
    """Packed executables are a classic AV false-positive heuristic, and an
    elevated system tool cannot afford that reputation hit."""
    assert not re.search(r"upx\s*=\s*True", spec)


def test_the_app_requires_administrator(spec):
    """v10.7: every launch elevates.

    THIS TEST USED TO ASSERT THE OPPOSITE, and the inversion is the record
    of a decision rather than a bug being fixed. v1.0 removed uac_admin
    because it made the per-task elevation subsystem unreachable and some
    packages un-installable; v10.7 puts it back because ~24 of Pulse's
    tasks write HKLM, services or machine state, and a repair tool that
    prompts separately for each of them interrupts the work it was opened
    to do. Both are true. The second is the one that ships.

    PyInstaller turns uac_admin into
        <requestedExecutionLevel level="requireAdministrator" uiAccess="false"/>
    in the exe's manifest, which is what makes Windows show the UAC prompt
    before the process starts.
    """
    assert re.search(r"uac_admin\s*=\s*True", spec), (
        "uac_admin is not set — the packaged app would launch asInvoked and "
        "every admin-gated task would prompt separately")


def test_no_instruction_tells_the_user_to_run_unelevated(spec):
    """THE CONSEQUENCE THAT HAD TO BE HANDLED, not merely accepted.

    Three backend messages used to tell the user to "use Pulse's GUI
    without elevating" — the documented escape for installers that set
    `elevationProhibited` and hard-refuse under an Administrator token
    (Spotify is the catalogued example; winget reports the family as
    -1978335146 / -1978335107). With requireAdministrator there is no
    unelevated Pulse to fall back to, so that advice became impossible to
    follow, and two more said the same thing about the split-token case.

    Un-installable is a real cost of this flag and it is documented in the
    spec. Advice that cannot be followed is not a cost, it is a bug, and
    this is the guard that keeps the two from being confused.
    """
    import os

    offenders = []
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for folder, _dirs, files in os.walk(os.path.join(root, "src")):
        for name in files:
            if not name.endswith((".ps1", ".py")):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8-sig", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    if "without elevating" in line:
                        offenders.append(
                            f"  {os.path.relpath(path, root)}:{number}")
    assert not offenders, (
        "message(s) still tell the user to run Pulse without elevating, "
        "which requireAdministrator makes impossible:\n" + "\n".join(offenders))


# ============================================================
#  THE INSTALLER
# ============================================================
def test_the_appid_is_stable_and_present(iss):
    """AppId is how Windows recognises an existing installation. Change it
    and every upgrade installs a second copy with its own Start Menu entry
    and an uninstaller that removes half the product."""
    match = re.search(r"^AppId=\{\{([0-9A-Fa-f-]{36})", iss, re.MULTILINE)
    assert match, "AppId is missing or is not a GUID"
    assert match.group(1).upper() == "7B2F4C91-3E8A-4D6B-9F1C-2A5E8D04B7C3", (
        "the AppId changed — every existing install becomes un-upgradeable")


def test_it_installs_to_program_files_by_default(iss):
    """A user-writable install directory means any process running as the
    user could replace PULSE.exe or the engine beside it and wait for the
    next elevated task. Program Files closes that."""
    assert re.search(r"^PrivilegesRequired=admin", iss, re.MULTILINE)
    assert re.search(r"^DefaultDirName=\{autopf\}", iss, re.MULTILINE)


def test_a_per_user_install_is_still_offered(iss):
    """For technicians with no admin rights — but never as the default."""
    assert re.search(r"^PrivilegesRequiredOverridesAllowed=dialog", iss,
                     re.MULTILINE)


def test_it_creates_both_shortcuts(iss):
    assert "{group}\\{#MyAppName}" in iss          # Start Menu
    assert "{autodesktop}\\{#MyAppName}" in iss    # Desktop
    assert re.search(r"^Name:\s*\"desktopicon\"", iss, re.MULTILINE)


def test_it_can_replace_a_running_copy(iss):
    """The updater launches this while Pulse is on screen; without these
    Setup hits a locked exe and fails or demands a reboot."""
    assert re.search(r"^CloseApplications=yes", iss, re.MULTILINE)
    assert re.search(r"^RestartApplications=yes", iss, re.MULTILINE)


def test_the_post_install_launch_cannot_be_blocked_by_app_control(iss):
    """WINDOWS APP CONTROL ERROR 4551, and the two flags that avoid it.

    Setup runs ELEVATED. PULSE.exe's own manifest asks for
    requireAdministrator (see the manifest note in main.spec). So the
    "Launch PULSE" checkbox is an elevated parent spawning an
    elevation-requesting child — exactly the shape a machine with App
    Control / Smart App Control enforcing refuses, and Setup surfaces the
    refusal as 4551 on the very last screen of a successful install.

      * shellexec         goes through ShellExecuteEx, so Windows performs
                          its normal elevation handshake instead of the
                          child inheriting the installer's token;
      * runasoriginaluser runs it as the signed-in user rather than the
                          elevated installer account — which is also what
                          puts %LOCALAPPDATA%\\PULSE, the saved theme, the
                          window geometry and the log under the profile
                          the user will actually come back to.

    Both were reasoned about at length in pulse.iss and neither was
    asserted anywhere, so a tidy-up of the [Run] line would have silently
    reintroduced a launch failure that only appears on machines with App
    Control on — i.e. never on the developer's.
    """
    run = re.search(r"^\[Run\](.*?)(?=^\[|\Z)", iss, re.MULTILINE | re.DOTALL)
    assert run, "pulse.iss has no [Run] section"
    entry = "".join(
        line for line in run.group(1).splitlines()
        if not line.lstrip().startswith(";"))
    assert "postinstall" in entry, "the launch-on-finish checkbox is gone"
    for flag in ("runasoriginaluser", "shellexec"):
        assert flag in entry, (
            f"the post-install launch dropped '{flag}' — it will fail with "
            "error 4551 wherever App Control is enforcing")
    # nowait/skipifsilent keep a silent updater-driven upgrade from
    # blocking on the app it just relaunched.
    assert "nowait" in entry and "skipifsilent" in entry


def test_the_output_name_is_what_the_updater_looks_for(iss):
    """pulse.iss names the artifact and updater._ASSET_RE finds it. If they
    disagree, every release silently has 'no installer' and no user is ever
    offered an update."""
    assert "OutputBaseFilename=PULSE_Setup_v{#MyAppVersion}" in iss
    produced = f"PULSE_Setup_v{version.VERSION}.exe"
    assert updater._ASSET_RE.match(produced), (
        f"the updater would not recognise {produced}")


def test_the_installer_version_comes_from_the_version_file(iss):
    """Hand-compiling pulse.iss must stamp the same version the build
    script would."""
    assert 'FileOpen("..\\VERSION")' in iss
    assert "#define MyAppVersion" in iss


def test_uninstall_asks_before_deleting_preferences(iss):
    """An UPGRADE runs the old uninstaller on some paths; silently wiping a
    user's theme, window placement and task history on a version bump would
    be a bug they could never explain. Hence the UninstallSilent() guard."""
    assert "UninstallSilent()" in iss
    assert "Software\\HumamTaibeh\\Pulse" in iss
    assert "MB_YESNO" in iss


def test_unsigned_by_default_is_explained_in_the_installer_script(iss):
    """pulse.iss itself is not where signing happens (see the build-script
    tests below) — Inno refuses to compile at all if a script declares
    SignTool without a matching /S<name>=... on the command line, which
    would break every ordinary unsigned build rather than just skip signing
    for it. What belongs here is the reader-facing explanation of why an
    unsigned build trips SmartScreen, so a future edit that deletes it
    doesn't also delete the reason nobody "fixed" this with a directive."""
    assert "SMARTSCREEN" in iss
    assert "SignTool" in iss, (
        "the signing section no longer mentions build_release.ps1's "
        "post-build mechanism — see test_signing_is_opt_in_and_off_by_default")


def test_signing_is_opt_in_and_off_by_default(build_script):
    """The actual signing hook: build_release.ps1 -SignThumbprint. Off by
    default (an ordinary `.\\tools\\build_release.ps1` run with no
    certificate configured must produce an unsigned build exactly as it
    always has, not a warning nobody asked for and not a throw) — so the
    default path is pinned as directly as the opt-in one."""
    assert "[string]$SignThumbprint" in build_script
    assert "$env:PULSE_SIGN_THUMBPRINT" in build_script
    assert re.search(r"if\s*\(-not \$SignTool\)\s*\{\s*return\s*\}", build_script), (
        "Sign-Artifact no longer no-ops when signing was never requested")


def test_a_self_signed_certificate_is_flagged_not_trusted(build_script):
    """A self-signed dev certificate (tools/create_dev_signing_cert.ps1)
    produces a mechanically valid signature that satisfies nobody's trust
    chain but the machine that made it — confirmed empirically: signtool
    sign succeeds against one unconditionally, and signtool verify then
    correctly reports the chain as untrusted. The build script has to say
    so where a release engineer would actually see it, not just in the dev
    certificate's own header comment."""
    assert "self-signed" in build_script
    assert "SmartScreen" in build_script and "Smart App Control" in build_script


def test_a_signed_artifact_is_verified_before_it_ships(build_script):
    """signtool sign succeeding is not the same claim as the signature
    being valid — Sign-Artifact must check both, or a certificate/signing
    problem ships silently as a build that merely LOOKS signed."""
    assert "signtool sign failed" in build_script
    assert "signtool verify failed" in build_script
    assert re.search(r"&\s*\$SignTool\s+verify\s+/pa\s+/q", build_script)


# ============================================================
#  THE WIZARD'S APPEARANCE
# ============================================================
def test_the_stock_inno_artwork_is_overridden(iss):
    """THERE WAS NOTHING HERE TO DELETE, WHICH IS WHY IT SHIPPED.

    Inno does not default to "no image": with WizardStyle=modern it
    supplies its own teal abstract graphic, and pulse.iss named no
    replacement, so every installer up to 10.9.1 carried stock Inno
    artwork by omission. The fix is an override, and an override is a line
    that can be deleted again by anyone tidying up — hence this test.
    """
    for directive in ("WizardImageFile", "WizardSmallImageFile"):
        match = re.search(rf"^{directive}=(.+)$", iss, re.MULTILINE)
        assert match, f"{directive} is not set — Setup is back on Inno's stock artwork"
        assert match.group(1).strip(), (
            f"{directive} is blank; the wizard shows no mark at all")
        assert "compiler:" not in match.group(1), (
            f"{directive} points back at a compiler-bundled bitmap")


def test_every_wizard_image_the_installer_names_exists(iss):
    """A missing file here fails the BUILD, not the tests — but it fails it
    minutes in, after PyInstaller has run. Catching it in the suite costs
    nothing and names the file."""
    named = []
    for directive in ("WizardImageFile", "WizardSmallImageFile"):
        match = re.search(rf"^{directive}=(.+)$", iss, re.MULTILINE)
        named += [p.strip() for p in match.group(1).split(",") if p.strip()]
    assert len(named) >= 4, f"only {len(named)} wizard image(s) declared"
    missing = [p for p in named
               if not os.path.isfile(os.path.join(_ROOT, "installer", *p.split("\\")))]
    assert not missing, f"pulse.iss names wizard images that do not exist: {missing}"


def test_the_wizard_art_is_rendered_at_every_dpi_it_claims(iss):
    """ONE FILE PER DPI, and the filenames have to be the sizes.

    Inno picks the nearest entry from the list and scales it; handing it a
    single 164px bitmap on a 200% display is exactly the soft, fringed
    result the modern style exists to avoid. The names encode the size, so
    a file whose CONTENT stopped matching its NAME would send Inno a
    correctly-named wrong-sized image and silently reintroduce the scaling.
    """
    from PIL import Image

    checked = 0
    for directive in ("WizardImageFile", "WizardSmallImageFile"):
        match = re.search(rf"^{directive}=(.+)$", iss, re.MULTILINE)
        paths = [p.strip() for p in match.group(1).split(",") if p.strip()]
        assert len(paths) >= 4, (
            f"{directive} declares {len(paths)} size(s); the HiDPI set is gone")
        for rel in paths:
            full = os.path.join(_ROOT, "installer", *rel.split("\\"))
            claimed = re.search(r"-(\d+)x(\d+)\.(bmp|png)$", rel)
            assert claimed, f"{rel} does not encode its size in its name"
            with Image.open(full) as im:
                assert im.size == (int(claimed.group(1)), int(claimed.group(2))), (
                    f"{rel} is {im.size}, not the size its name claims")
            checked += 1
    assert checked >= 8


def test_the_header_mark_keeps_its_transparency(iss):
    """ONE ASSET, TWO GROUNDS. The small mark sits directly on the wizard
    page, which is off-white under the windows11 style's light half and
    near-black under its dark half. A flattened copy would show as a
    rectangle in whichever one it was not built for."""
    from PIL import Image

    match = re.search(r"^WizardSmallImageFile=(.+)$", iss, re.MULTILINE)
    for rel in [p.strip() for p in match.group(1).split(",") if p.strip()]:
        assert rel.lower().endswith(".png"), (
            f"the header mark {rel} is not a PNG, so it cannot carry alpha")
        with Image.open(os.path.join(_ROOT, "installer", *rel.split("\\"))) as im:
            assert im.mode == "RGBA", f"{rel} has no alpha channel"
            alpha = im.getchannel("A")
            assert alpha.getextrema()[0] == 0, (
                f"{rel} has no fully transparent pixels — it is a plate, not "
                "a mark, and will show as a rectangle on one of the two "
                "backgrounds")


def test_the_wizard_follows_the_users_windows_theme(iss):
    """`dynamic` rather than `dark`. Pulse's own UI defaults to dark and
    offers a toggle; an installer that hard-forced dark would be the one
    surface in the product ignoring the same system preference the app
    respects. `windows11` supplies the light half so both appearances are
    deliberate."""
    match = re.search(r"^WizardStyle=(.+)$", iss, re.MULTILINE)
    assert match, "WizardStyle is not set"
    tokens = match.group(1).lower().split()
    assert "modern" in tokens, "the wizard is back on the classic layout"
    assert "dynamic" in tokens, (
        f"WizardStyle is {tokens} — it no longer follows the system theme")
    assert "dark" not in tokens, (
        "forced dark ignores the user's Windows setting, and skips the "
        "DynamicDark directives entirely")
    assert "windows11" in tokens


def test_the_flow_has_no_page_that_only_recites(iss):
    """The Ready page reads the user's own choices back to them one screen
    after they made them. With a single optional task there is nothing on
    it they have not just seen."""
    assert re.search(r"^DisableReadyPage=yes", iss, re.MULTILINE)
    assert re.search(r"^DisableProgramGroupPage=yes", iss, re.MULTILINE)
    # ...but never the pages that carry a real decision.
    for kept in ("DisableDirPage", "DisableFinishedPage", "DisableWelcomePage"):
        assert not re.search(rf"^{kept}=yes", iss, re.MULTILINE), (
            f"{kept}=yes removes a page the user actually acts on")


def test_no_directive_is_written_twice(iss):
    """A [Setup] key set twice is one edit away from the two copies
    disagreeing, and Inno takes the last one silently."""
    seen: dict[str, int] = {}
    body = iss[iss.index("[Setup]"):]
    body = body[:body.index("\n[")]
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        seen[key] = seen.get(key, 0) + 1
    dupes = {k: n for k, n in seen.items() if n > 1}
    assert not dupes, f"[Setup] directives set more than once: {dupes}"


def test_a_dropped_directive_is_not_resurrected(iss):
    """WizardResizable was dropped in Inno 6.7 — the wizard is no longer
    resizable by anyone — and before that it defaulted to `no`. Writing it
    would be a line that has never once changed a build, and the compiler
    still accepts it, so nothing else would ever say so."""
    assert not re.search(r"^WizardResizable=", iss, re.MULTILINE), (
        "WizardResizable is set; it has been a no-op on every version that "
        "ever read this file")


# ============================================================
#  THE BUILD SCRIPT
# ============================================================
def test_the_build_script_emits_checksums(build_script):
    """updater.verify() refuses any download whose digest is not published,
    so a release built without SHA256SUMS is one the updater declines."""
    assert "SHA256SUMS" in build_script
    assert "Get-FileHash" in build_script
    assert "SHA256" in build_script


def test_the_checksum_format_is_the_one_the_updater_parses(build_script):
    """'<lowercase sha256>  <filename>' — sha256sum's format."""
    assert 'ToLowerInvariant()' in build_script
    assert '"$Hash  $Name"' in build_script
    sample = f"{'a' * 64}  PULSE_Setup_v{version.VERSION}.exe"
    parsed = updater.parse_sums(sample)
    assert parsed.get(f"PULSE_Setup_v{version.VERSION}.exe") == "a" * 64


def test_the_build_script_verifies_the_bundle_layout(build_script):
    """PyInstaller 6.x puts datas under _internal\\, which IS _MEIPASS —
    so core.ps1's '..\\..\\VERSION' resolves there. Correct, but only while
    the tree keeps that shape."""
    assert "_internal\\VERSION" in build_script
    assert "_internal\\src\\backend\\core.ps1" in build_script
    assert "_internal\\src\\backend\\modules" in build_script
    # The brand marks, checked at BUILD time as well as statically above.
    # The two guards catch different mistakes: the spec test catches a
    # datas entry nobody wrote, this catches a bundle that came out wrong
    # anyway (an excluded path, a failed copy). v10.9.0 needed both and
    # had neither.
    assert "_internal\\assets\\appicons\\manifest.json" in build_script
    assert "-Filter *.svg" in build_script, (
        "the build no longer counts the bundled marks — a manifest with no "
        "artwork beside it would pass")


def test_the_build_script_survives_native_stderr(build_script):
    """PyInstaller logs its whole INFO stream to stderr, and Windows
    PowerShell turns that into a terminating error under -ErrorAction Stop
    — so a completely successful build aborted on its first line of
    output. The exit code is the only honest signal for a native command."""
    assert "$ErrorActionPreference = 'Continue'" in build_script
    assert "$LASTEXITCODE" in build_script


def test_the_build_script_refuses_a_ragged_version(build_script):
    """Releases are tagged v<VERSION>, so it must be MAJOR.MINOR.PATCH."""
    assert r"'^\d+\.\d+\.\d+$'" in build_script
