"""
The Startup Manager and the Update Center had no icon column at all.

WHY THAT MATTERED MOST IN THOSE TWO LISTS
    A startup entry is identified by a REGISTRY VALUE NAME. The rows read
    "MicrosoftEdgeAutoLaunch_1C40B5E8F2...", "RtkAudUService",
    "SecurityHealth" — strings that name the thing exactly and identify it
    to nobody. The Update Center is the same problem from the other end:
    it lists whatever winget reports, so it is not limited to the ~45 apps
    the catalog curates and its rows are winget ids.

    Both lists ask the user to make a decision per row, and in both the
    icon is the only part of the row most people can match against
    something they recognise.

WHY A NEW EXTRACTOR RATHER THAN QFileIconProvider
    appicons' tier 2 could already read an installed app's icon through
    Qt. On Windows that asks the shell for SHGFI_LARGEICON — 32x32 — and
    every mark in this app is drawn into a 36px well, which is 54 device
    pixels at 150%. So the one tier showing the vendor's real artwork was
    the one tier delivering an upscale, and it got worse the better the
    display was. Windows has carried a 256px frame for every well-behaved
    binary since Vista; Qt6 exposes no way to ask for it, because
    QtWinExtras and QtWin::fromHICON went away with Qt5.

WHAT THESE TESTS ARE FOR
    The extractor is ~300 lines of ctypes against four Win32 APIs, and
    ctypes fails in a specific, nasty way: it assumes a 32-bit C int for
    anything undeclared, so a 64-bit handle raises OverflowError for SOME
    inputs and not others depending on where the OS happened to allocate
    it. Measured during development: notepad.exe extracted perfectly while
    explorer.exe, cmd.exe and git.exe all raised, in the same process, on
    the same call path. A test that only checked "notepad works" would
    have shipped that.

    So the size floor and the several-binaries sweep are the two
    assertions that matter, and the handle-leak check is the third:
    leaking one GDI object per row is invisible here and fatal several
    hundred rows later, in an unrelated part of the app.
"""
from __future__ import annotations

import hashlib
import os
import sys

import pytest

from PySide6.QtCore import QBuffer, QByteArray

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="the shell icon APIs are Windows-only")


#: Binaries every Windows install has, chosen to span the ways the shell
#: can answer: a System32 app, the shell itself, and a console host.
_STOCK = [
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                 "System32", "notepad.exe"),
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe"),
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                 "System32", "cmd.exe"),
]


def _present() -> list[str]:
    found = [p for p in _STOCK if os.path.isfile(p)]
    if not found:
        pytest.skip("none of the stock binaries are present")
    return found


def _digest(pixmap) -> str:
    blob = QByteArray()
    buffer = QBuffer(blob)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pixmap.toImage().save(buffer, "PNG")
    buffer.close()
    return hashlib.sha256(bytes(blob)).hexdigest()


class TestTheExtractorItself:

    def test_every_stock_binary_yields_an_icon(self, qapp):
        """THE REGRESSION. Three binaries, not one — the ctypes overflow
        this guards was input-dependent and notepad.exe alone passed
        while the other two raised."""
        from utils import nativeicons

        missing = [p for p in _present() if nativeicons.icon_image(p) is None]
        assert not missing, (
            f"no icon extracted for {[os.path.basename(p) for p in missing]}")

    def test_the_icon_is_bigger_than_qt_could_have_given(self, qapp):
        """THE POINT OF THE EXERCISE. QFileIconProvider tops out at the
        32px shell icon; if this ladder is silently falling through to
        ExtractIconExW for everything, the marks are no crisper than
        before and the module has bought nothing."""
        from utils import nativeicons

        for path in _present():
            image = nativeicons.icon_image(path)
            assert image is not None
            assert image.width() >= 48, (
                f"{os.path.basename(path)} came back at {image.width()}px — "
                "the jumbo and extra-large image lists both failed and this "
                "is the 32px last resort")

    def test_the_icons_are_actually_different_pictures(self, qapp):
        """The shell answers a path it cannot classify with a generic
        document page rather than failing, so "an image came back" is not
        the same as "the app's icon came back". Three stock binaries with
        three visibly different icons must not hash the same."""
        from utils import nativeicons

        paths = _present()
        if len(paths) < 2:
            pytest.skip("need two binaries to compare")
        digests = set()
        for path in paths:
            image = nativeicons.icon_image(path)
            blob = QByteArray()
            buffer = QBuffer(blob)
            buffer.open(QBuffer.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            buffer.close()
            digests.add(hashlib.sha256(bytes(blob)).hexdigest())
        assert len(digests) == len(paths), (
            "two stock binaries produced byte-identical icons — the shell "
            "is handing back its generic placeholder")

    def test_the_icon_is_not_a_transparent_rectangle(self, qapp):
        """The HICON conversion reads a colour plane and a mask. Get the
        alpha handling wrong and it returns a correctly-sized, entirely
        invisible image, which every "did we get something?" check
        passes."""
        from utils import nativeicons

        image = nativeicons.icon_image(_present()[0])
        step = max(1, image.width() // 32)
        opaque = sum(
            1
            for y in range(0, image.height(), step)
            for x in range(0, image.width(), step)
            if (image.pixel(x, y) >> 24) & 0xFF > 8)
        assert opaque > 0, "the extracted icon is fully transparent"

    def test_it_leaks_no_gdi_or_user_handles(self, qapp):
        """EVERY HICON, HBITMAP AND HDC, in a finally block.

        The symptom of getting this wrong does not appear in this file: a
        leak of one object per row is a few hundred per Update Center
        scan, and what fails is the process's ability to create any window
        at all, minutes later, at the 10,000-handle ceiling.
        """
        import ctypes

        from utils import nativeicons

        paths = _present()
        process = ctypes.windll.kernel32.GetCurrentProcess()

        def counts():
            return (ctypes.windll.user32.GetGuiResources(process, 0),
                    ctypes.windll.user32.GetGuiResources(process, 1))

        for path in paths:            # warm any one-time allocation
            nativeicons.icon_image(path)
        before = counts()
        for _ in range(40):
            for path in paths:
                nativeicons.icon_image(path)
        after = counts()
        assert after[0] - before[0] <= 8 and after[1] - before[1] <= 8, (
            f"handles grew from {before} to {after} over "
            f"{40 * len(paths)} extractions")


class TestTheBlankPageGuardStillWorks:
    """appicons rejects the shell's generic document icon rather than
    showing it as an app's own — the defect that put Steam and iTunes into
    a row of real logos as white pages.

    THAT GUARD WAS ABOUT TO LAPSE SILENTLY. It compares raw image bytes
    against QFileIconProvider's File icon, which is only a valid key while
    QFileIconProvider is the thing producing the pixmap. With a second
    extractor answering first, a placeholder arriving through the native
    path would not match Qt's rendering of the same picture and would sail
    past a check that still looked like it was running — the worst
    property a guard can have.
    """

    def test_both_extractors_contribute_a_key(self, qapp):
        from utils import appicons

        keys = appicons._generic_keys(36)
        assert len(keys) >= 2, (
            "only one rendering of the placeholder is known, so a generic "
            "icon from the other extractor would be shown as an app's own")

    def test_the_native_placeholder_is_obtainable_without_a_file(self, qapp):
        """SHGFI_USEFILEATTRIBUTES asks the shell about a NAME rather than
        about the disk, so the key costs no I/O and leaves nothing to
        clean up."""
        from utils import nativeicons

        image = nativeicons.generic_image()
        assert image is not None and not image.isNull()

    def test_a_real_binary_is_not_mistaken_for_the_placeholder(self, qapp):
        """The guard must reject the blank page and nothing else."""
        from utils import appicons

        assert appicons._shell_pixmap(_present()[0], 36) is not None


class TestReadingABinaryOutOfACommandLine:
    """A Run key holds whatever an installer wrote there, and the shapes
    are all different."""

    def test_a_quoted_path_wins_over_its_arguments(self):
        from utils import nativeicons

        target = _present()[0]
        assert nativeicons.executable_from_command(
            f'"{target}" --minimized /background') == target

    def test_an_unquoted_path_with_spaces_still_resolves(self):
        """THE HARD ONE, AND THE COMMON ONE. Splitting on the first space
        turns "C:\\Program Files\\App\\app.exe /q" into "C:\\Program",
        which exists on no machine — so the longest leading run that names
        a real file wins, which is how Windows itself resolves it."""
        from utils import nativeicons

        spaced = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                              "Git", "cmd", "git.exe")
        if not os.path.isfile(spaced):
            pytest.skip("no space-containing install path available here")
        assert nativeicons.executable_from_command(
            f"{spaced} --version") == spaced

    def test_a_bare_path_with_no_arguments_resolves(self):
        from utils import nativeicons

        target = _present()[0]
        assert nativeicons.executable_from_command(target) == target

    def test_a_host_process_resolves_to_the_host(self):
        """rundll32 entries name the host and pass the real payload as an
        argument. The host is the honest answer: it is what actually
        runs, and Pulse has no business rendering a DLL's icon as though
        it were an application."""
        from utils import nativeicons

        host = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                            "System32", "rundll32.exe")
        if not os.path.isfile(host):
            pytest.skip("rundll32 is absent")
        assert nativeicons.executable_from_command(
            rf"{host} C:\path\thing.dll,EntryPoint") == host

    @pytest.mark.parametrize("junk", [
        "", "   ", "nonsense value here", r'"C:\unterminated',
        r"C:\definitely\not\here.exe --x",
    ])
    def test_nothing_resolvable_returns_none(self, junk):
        """None rather than a guess: drawing the WRONG application's icon
        beside a startup entry is worse than drawing the generic one,
        because the user acts on what they recognise."""
        from utils import nativeicons

        assert nativeicons.executable_from_command(junk) is None


class TestTheRowsThatNeededIt:

    def test_binary_icon_always_returns_something(self, qapp):
        """A row that asks for an icon and gets None has to grow a branch
        and a second widget, and every such branch is a chance for the two
        cases to lay out differently — the "awkward blank space" this
        exists to prevent."""
        from frontend import theme as TH
        from utils import appicons

        tokens = TH.tokens("dark")
        for command in ("", "nonsense", _present()[0]):
            pixmap = appicons.binary_icon(command, 36, tokens)
            assert pixmap is not None and not pixmap.isNull()

    def test_the_fallback_is_one_mark_and_the_real_icon_is_not_it(self, qapp):
        from frontend import theme as TH
        from utils import appicons

        tokens = TH.tokens("dark")
        empty = _digest(appicons.binary_icon("", 36, tokens))
        absent = _digest(appicons.binary_icon(r"C:\no\such.exe", 36, tokens))
        real = _digest(appicons.binary_icon(_present()[0], 36, tokens))
        assert empty == absent, (
            "two unresolvable commands drew different fallbacks")
        assert real != empty, (
            "a resolvable binary drew the generic mark — the extractor "
            "is not being reached from binary_icon at all")

    def test_a_startup_row_renders_its_target_icon(self, qapp):
        from frontend import theme as TH
        from frontend.widgets import StartupRow

        tokens = TH.tokens("dark")
        target = _present()[0]
        item = {"Id": "Registry|||HKCU|||Thing", "Name": "Thing",
                "Type": "Registry", "Command": f'"{target}" /x',
                "Enabled": True, "Recommendation": "Review",
                "Impact": "Medium", "Reason": "r", "Protected": False}
        row = StartupRow(item, tokens)
        assert row._icon.pixmap() is not None
        assert not row._icon.pixmap().isNull()

    def test_an_update_row_renders_a_mark(self, qapp):
        from frontend import theme as TH
        from frontend.widgets import UpdateRow

        row = UpdateRow("Git.Git", "Git", "2.40.0", "2.45.0",
                        TH.tokens("dark"))
        assert row._icon.pixmap() is not None
        assert not row._icon.pixmap().isNull()

    def test_both_rows_declare_that_their_mark_is_ratio_baked(self):
        """The pixmaps are rasterised for the screen's device-pixel ratio,
        so PulseDialog.rescale_marks has to redraw them when the window
        moves to a display with different scaling. That is a DECLARED
        flag, not a duck-typed guess — see the note on DevHubRow."""
        from frontend.widgets import StartupRow, UpdateRow

        assert StartupRow.RATIO_BAKED is True
        assert UpdateRow.RATIO_BAKED is True


# ============================================================
#  THE TWO SHAPES THE EXTRACTOR COULD NOT SEE  (v10.12)
# ============================================================
#  A BINARY PATH IS NOT WHAT THE STARTUP MANAGER MOSTLY HOLDS, and that
#  is the gap this section covers. Every entry in the Startup FOLDER is a
#  `.lnk`, and a Store app has no path to point at in the first place —
#  it is addressed by an identifier, and its artwork is a PNG named in
#  AppxManifest.xml rather than a resource inside its .exe.
#
#  Both used to reach the SAME place by different routes: the generic
#  executable mark. A shortcut got the shell's rendering of the shortcut
#  (the target's icon with the "this is a link" arrow stamped on it), and
#  a packaged app got Windows' blank application placeholder, which
#  appicons correctly rejects and then falls back from. So the two lists
#  that most need an icon column were the two most likely not to have one.
def _lnk_bytes(target: str) -> bytes:
    """A minimal, well-formed .lnk naming `target`.

    HAND-BUILT RATHER THAN SHELL-CREATED, on purpose. Asking the shell to
    make the fixture would test the reader against a file written by the
    same component it is about to be read by, which passes even if both
    are wrong about the format — and it would skip on any machine where
    COM is the thing that is broken, which is precisely when the
    fallback parser is what the app is relying on.

    Shapes only the fields MS-SHLLINK requires plus the LinkInfo block
    that carries a local path: a 0x4C header, LinkFlags = HasLinkInfo |
    IsUnicode, a minimal VolumeID, and the ANSI LocalBasePath.
    """
    import struct

    link_clsid = bytes.fromhex("01140200000000000000000000000000")[:4]
    link_clsid = (struct.pack("<IHH", 0x00021401, 0, 0)
                  + bytes((0xC0, 0, 0, 0, 0, 0, 0, 0x46)))
    header = struct.pack("<I", 0x4C) + link_clsid
    header += struct.pack("<I", 0x2 | 0x80)      # HasLinkInfo | IsUnicode
    header += struct.pack("<I", 0x20)            # FileAttributes
    header += b"\x00" * 24                       # three FILETIMEs
    header += struct.pack("<IIIHHII", 0, 0, 1, 0, 0, 0, 0)
    assert len(header) == 0x4C, len(header)

    volume = struct.pack("<IIII", 0x11, 3, 0, 0x10) + b"\x00"
    base = target.encode("mbcs") + b"\x00"
    suffix = b"\x00"
    head_size = 0x1C
    volume_offset = head_size
    path_offset = volume_offset + len(volume)
    suffix_offset = path_offset + len(base)
    total = suffix_offset + len(suffix)
    link_info = struct.pack(
        "<IIIIIII", total, head_size, 0x1, volume_offset, path_offset,
        0, suffix_offset) + volume + base + suffix
    return header + link_info + struct.pack("<I", 0)


class TestFollowingAShortcut:
    """A Startup-folder entry's `Command` IS a .lnk path."""

    def test_the_parser_reads_a_local_target(self, tmp_path):
        """The reader that does not need COM. It is the fallback, and it
        is the one that has to keep working on a machine where the shell
        is the thing that is unwell."""
        from utils import nativeicons

        target = _present()[0]
        link = tmp_path / "thing.lnk"
        link.write_bytes(_lnk_bytes(target))
        assert nativeicons._shortcut_target_parsed(str(link)) == target

    def test_resolve_shortcut_answers_for_that_link(self, tmp_path):
        from utils import nativeicons

        target = _present()[0]
        link = tmp_path / "thing.lnk"
        link.write_bytes(_lnk_bytes(target))
        assert nativeicons.resolve_shortcut(str(link)) == target

    def test_a_command_naming_a_shortcut_resolves_to_the_binary(
            self, tmp_path):
        """THE DEFECT, stated as the row saw it: executable_from_command
        used to return the .lnk itself, because a .lnk IS a file. The
        icon then came back with the shell's shortcut arrow stamped on
        it — a badge that says "this is a link" in a column where that is
        never the interesting fact."""
        from utils import nativeicons

        target = _present()[0]
        link = tmp_path / "spaced name.lnk"
        link.write_bytes(_lnk_bytes(target))
        assert nativeicons.executable_from_command(str(link)) == target
        assert nativeicons.resolve_command(str(link)).binary == target

    def test_a_shortcut_to_a_missing_target_resolves_to_nothing(
            self, tmp_path):
        """The generic mark is CORRECT here, and this pins that it is
        reached for the right reason. A stale Start-menu shortcut naming
        an uninstalled binary must not resolve to something else nearby."""
        from utils import nativeicons

        link = tmp_path / "stale.lnk"
        link.write_bytes(_lnk_bytes(r"C:\definitely\not\here.exe"))
        assert nativeicons.resolve_shortcut(str(link)) is None
        assert nativeicons.executable_from_command(str(link)) is None

    def test_the_real_start_menu_resolves(self):
        """Measured against the machine rather than a fixture, because
        the fixture cannot produce the shapes that actually break a
        reader: ID-list-only links, KNOWNFOLDER indirections, and targets
        written with environment variables in them."""
        import glob

        from utils import nativeicons

        roots = [os.path.join(os.environ.get("ProgramData", ""),
                              r"Microsoft\Windows\Start Menu\Programs"),
                 os.path.join(os.environ.get("APPDATA", ""),
                              r"Microsoft\Windows\Start Menu\Programs")]
        links = []
        for root in roots:
            if root and os.path.isdir(root):
                links += glob.glob(os.path.join(root, "**", "*.lnk"),
                                   recursive=True)
        if len(links) < 5:
            pytest.skip("no Start menu shortcuts to measure against")

        sample = links[:40]
        resolved = [link for link in sample
                    if nativeicons.resolve_shortcut(link)]
        # Not "all of them": a Start menu accumulates shortcuts to
        # software that has been uninstalled, and None is the right
        # answer for those. A majority is what says the reader works.
        assert len(resolved) > len(sample) // 2, (
            f"only {len(resolved)} of {len(sample)} Start-menu shortcuts "
            "resolved — the reader is not working on this machine")

    def test_the_two_readers_never_disagree(self):
        """The fallback must not point at a DIFFERENT file from the one
        the shell names. A parser that is merely incomplete is safe —
        the caller draws a glyph; one that is confidently wrong puts
        another application's icon on the row."""
        import glob

        from utils import nativeicons

        root = os.path.join(os.environ.get("ProgramData", ""),
                            r"Microsoft\Windows\Start Menu\Programs")
        if not root or not os.path.isdir(root):
            pytest.skip("no all-users Start menu here")
        links = glob.glob(os.path.join(root, "**", "*.lnk"), recursive=True)
        if not links:
            pytest.skip("no shortcuts to compare")

        disagreements = []
        for link in links[:60]:
            shell = nativeicons._shortcut_target_com(link)
            parsed = nativeicons._shortcut_target_parsed(link)
            if shell and parsed and os.path.normcase(shell) != os.path.normcase(parsed):
                disagreements.append((link, shell, parsed))
        assert not disagreements, (
            f"the .lnk parser contradicts the shell: {disagreements}")


class TestPackagedApps:
    """A Store app keeps its artwork in AppxManifest.xml, not in its
    .exe. Every rung of the extraction ladder answers for one anyway —
    with Windows' generic application placeholder."""

    @staticmethod
    def _package(tmp_path, declared="Assets\\Square44x44Logo.png",
                 variants=("Square44x44Logo.scale-200.png",
                           "Square44x44Logo.targetsize-256.png",
                           "Square44x44Logo.targetsize-256_altform-unplated.png")):
        from PySide6.QtGui import QColor, QImage

        root = tmp_path / "Fake.Package_1.0.0.0_x64__abcdefghijklm"
        assets = root / "Assets"
        assets.mkdir(parents=True)
        (root / "AppxManifest.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<Package><Properties><DisplayName>Fake</DisplayName>'
            f'<Logo>Assets\\StoreLogo.png</Logo></Properties>'
            f'<Applications><Application><uap:VisualElements '
            f'Square44x44Logo="{declared}" '
            f'Square150x150Logo="Assets\\Square150x150Logo.png"/>'
            '</Application></Applications></Package>',
            encoding="utf-8")
        for name in variants:
            image = QImage(8, 8, QImage.Format.Format_ARGB32)
            image.fill(QColor("#3366cc"))
            image.save(str(assets / name), "PNG")
        return root

    def test_the_manifest_answers_for_a_package_folder(self, tmp_path, qapp):
        from utils import nativeicons

        root = self._package(tmp_path)
        asset = nativeicons.appx_asset_for_root(str(root))
        assert asset is not None, "the manifest's logo was not found"
        assert os.path.isfile(asset)

    def test_the_biggest_plated_variant_wins(self, tmp_path, qapp):
        """THE DECLARED PATH IS OFTEN NOT A FILE — MSIX resolves it
        through resources.pri — so the declaration is a stem and the
        directory is read.

        Biggest wins because this is scaled DOWN into a 20px box.
        PLATED wins over `altform-unplated` because every icon in this
        app sits on a neutral well: the unplated form is the mark with
        its brand background removed, which is what a taskbar wants
        because the taskbar supplies its own.
        """
        from utils import nativeicons

        root = self._package(tmp_path)
        asset = os.path.basename(nativeicons.appx_asset_for_root(str(root)))
        assert asset == "Square44x44Logo.targetsize-256.png", (
            f"picked {asset} — the largest plated variant should win")

    def test_a_binary_inside_the_package_finds_its_own_logo(
            self, tmp_path, qapp):
        from utils import nativeicons

        root = self._package(tmp_path)
        (root / "app.exe").write_bytes(b"MZ")
        asset = nativeicons.appx_asset_for_path(str(root / "app.exe"))
        assert asset is not None and os.path.isfile(asset)

    def test_a_binary_outside_any_package_finds_nothing(self, qapp):
        """The walk is bounded and must not climb out of a package into
        a coincidence."""
        from utils import nativeicons

        assert nativeicons.appx_asset_for_path(_present()[0]) is None

    def test_an_aumid_is_read_out_of_a_command_line(self):
        from utils import nativeicons

        cases = {
            r"shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App":
                "Microsoft.WindowsCalculator_8wekyb3d8bbwe",
            r"C:\Windows\explorer.exe shell:AppsFolder\Microsoft.SkypeApp_kzf8qxf38zg5c!Skype":
                "Microsoft.SkypeApp_kzf8qxf38zg5c",
            r"C:\Windows\System32\notepad.exe": None,
            "": None,
        }
        for command, expected in cases.items():
            assert nativeicons.aumid_from_command(command) == expected, command

    def test_a_real_installed_package_resolves_to_real_artwork(self, qapp):
        """The end-to-end claim, measured against this machine's own
        Store packages rather than a fixture: an app addressed the way
        Windows addresses it must produce the vendor's PNG."""
        import winreg

        from utils import nativeicons

        try:
            packages = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                      nativeicons._APPX_REPOSITORY)
        except OSError:
            pytest.skip("no Appx repository on this machine")

        found = None
        index = 0
        while found is None and index < 4000:
            try:
                full = winreg.EnumKey(packages, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(packages, full) as entry:
                    root = winreg.QueryValueEx(entry, "PackageRootFolder")[0]
            except OSError:
                continue
            if not root or not os.path.isdir(root):
                continue
            if not nativeicons.appx_asset_for_root(root):
                continue
            # <Name>_<Version>_<Arch>_<ResourceId>_<PublisherId>, and the
            # resource id is EMPTY only for the common case — Windows'
            # own in-box packages carry a real one, so the family name is
            # the first segment and the last, never a "__" split.
            parts = full.split("_")
            found = (f"{parts[0]}_{parts[-1]}", root)
        if found is None:
            pytest.skip("no readable packaged app on this machine")

        family, _root = found
        asset = nativeicons.appx_asset_for_family(family)
        assert asset and os.path.isfile(asset), (
            f"{family} is installed but its logo did not resolve")
        target = nativeicons.resolve_command(
            rf"shell:AppsFolder\{family}!App")
        assert target.asset == asset
        assert target.kind == "aumid"

    def test_a_packaged_app_does_not_draw_the_generic_mark(
            self, tmp_path, qapp):
        """THE WHOLE POINT. binary_icon must reach the manifest asset —
        a row for a Store app that renders the same parcel as an
        unresolvable command has learned nothing from any of this."""
        from frontend import theme as TH
        from utils import appicons

        root = self._package(tmp_path)
        (root / "app.exe").write_bytes(b"MZ")
        tokens = TH.tokens("dark")
        packaged = _digest(appicons.binary_icon(
            str(root / "app.exe"), 36, tokens))
        generic = _digest(appicons.binary_icon("", 36, tokens))
        assert packaged != generic, (
            "a packaged app still renders the generic executable mark")


class TestEnvironmentVariablesAndArguments:
    """"Strip the command line down to the binary", pinned on BOTH
    branches.

    NEITHER OF THESE IS A FIX, and saying so is the point of this
    docstring. Environment expansion has always been done on both the
    quoted and the unquoted path; the reason they are pinned now is that
    v10.12 restructured this function — the file-finding half became
    _file_from_command and executable_from_command became the half that
    follows a shortcut — and a refactor is exactly the moment a branch
    quietly loses a call that nothing was asserting on.
    """

    def test_a_quoted_path_expands_its_variables(self):
        r"""`"%LOCALAPPDATA%\App\app.exe" --minimized` is an entirely
        ordinary Run value, and the quoted branch has to expand before it
        tests the file system or it answers no on every machine."""
        from utils import nativeicons

        root = os.environ.get("SystemRoot", r"C:\Windows")
        target = os.path.join(root, "System32", "notepad.exe")
        if not os.path.isfile(target):
            pytest.skip("notepad is absent")
        assert nativeicons.executable_from_command(
            r'"%SystemRoot%\System32\notepad.exe" --minimized') == target

    def test_an_unquoted_path_expands_its_variables(self):
        from utils import nativeicons

        root = os.environ.get("SystemRoot", r"C:\Windows")
        target = os.path.join(root, "System32", "notepad.exe")
        if not os.path.isfile(target):
            pytest.skip("notepad is absent")
        assert nativeicons.executable_from_command(
            r"%SystemRoot%\System32\notepad.exe /background") == target

    def test_resolve_command_reports_which_route_answered(self):
        """`kind` is not decoration: it is how a future reader (and this
        suite) tells "resolved a path" from "followed a shortcut" from
        "read a manifest" without re-deriving any of it."""
        from utils import nativeicons

        assert nativeicons.resolve_command(_present()[0]).kind == "path"
        assert nativeicons.resolve_command("nonsense at all").kind == ""
        assert nativeicons.resolve_command("").kind == ""


# ============================================================
#  SQUIRREL / ELECTRON STUBS  (v10.12.1)
# ============================================================
#  AN ELECTRON APP'S RUN KEY OFTEN NAMES ITS UPDATER, NOT THE APP.
#  Squirrel.Windows installs into %LOCALAPPDATA%\<Product>\ as Update.exe
#  beside app-<version>\App.exe, and registers
#  `Update.exe --processStart App.exe`. Discord ships exactly that on the
#  machine this was measured on.
#
#  WHAT RESOLVING BUYS IS CORRECTNESS RATHER THAN PIXELS, and saying so
#  matters because it is easy to read this as the fix for a blank row:
#  Squirrel STAMPS the app's icon onto Update.exe, so extracting the stub
#  already produced the right artwork. What changes is that the row now
#  names the application instead of its updater.
class TestSquirrelStubs:

    @staticmethod
    def _package(tmp_path, versions=("1.0.9", "1.0.10"), app="App.exe",
                 dead=False):
        """A Squirrel layout: Update.exe beside app-<version> folders."""
        root = tmp_path / "Product"
        root.mkdir()
        (root / "Update.exe").write_bytes(b"MZ")
        for version in versions:
            folder = root / f"app-{version}"
            folder.mkdir()
            if app:
                (folder / app).write_bytes(b"MZ")
        if dead:
            (root / ".dead").write_text("", encoding="utf-8")
        return root

    def test_the_named_target_wins(self, tmp_path):
        """Squirrel puts the answer in its own argument. Guessing when
        the command line has already said is how a row ends up pointing
        at an installer that happens to sit in the same folder."""
        from utils import nativeicons

        root = self._package(tmp_path, app="Discord.exe")
        stub = str(root / "Update.exe")
        found = nativeicons.resolve_squirrel(
            stub, f'"{stub}" --processStart Discord.exe')
        assert found is not None
        assert os.path.basename(found) == "Discord.exe"

    def test_the_newest_version_wins_NUMERICALLY(self, tmp_path):
        """app-1.0.10 is NEWER than app-1.0.9 and sorts BEFORE it as a
        string. A resolver that sorts textually pins itself to whichever
        old build an update happened to leave on disk."""
        from utils import nativeicons

        root = self._package(tmp_path, versions=("1.0.9", "1.0.10"))
        found = nativeicons.resolve_squirrel(str(root / "Update.exe"), "")
        assert found is not None
        assert "app-1.0.10" in found, f"picked {found}"

    def test_a_dead_package_resolves_to_nothing(self, tmp_path):
        """MEASURED, NOT IMAGINED. Squirrel drops a `.dead` marker when
        the product is uninstalled and leaves Update.exe behind; on the
        machine this was written against, SignalRgb's folder held exactly
        that plus an app-2.5.19 with no executable in it. Inventing an
        answer there would put some other program's icon on the row."""
        from utils import nativeicons

        root = self._package(tmp_path, dead=True)
        assert nativeicons.resolve_squirrel(str(root / "Update.exe"), "") is None

    def test_a_version_directory_with_no_executable_resolves_to_nothing(
            self, tmp_path):
        from utils import nativeicons

        root = self._package(tmp_path, app="")
        assert nativeicons.resolve_squirrel(str(root / "Update.exe"), "") is None

    def test_a_lone_update_exe_is_not_treated_as_squirrel(self, tmp_path):
        """BOTH HALVES ARE REQUIRED. "Update.exe" is a common enough
        filename that the name alone would claim every hand-rolled
        updater on the machine; the app-<version> sibling is what makes
        it Squirrel."""
        from utils import nativeicons

        plain = tmp_path / "Other"
        plain.mkdir()
        (plain / "Update.exe").write_bytes(b"MZ")
        assert not nativeicons._is_squirrel_stub(str(plain / "Update.exe"))

        root = self._package(tmp_path)
        assert nativeicons._is_squirrel_stub(str(root / "Update.exe"))

    def test_resolve_command_follows_the_stub_and_says_so(self, tmp_path):
        from utils import nativeicons

        root = self._package(tmp_path, app="Discord.exe")
        stub = str(root / "Update.exe")
        target = nativeicons.resolve_command(
            f'"{stub}" --processStart Discord.exe --process-start-args "--x"')
        assert target.kind == "squirrel"
        assert os.path.basename(target.binary) == "Discord.exe"

    def test_a_dead_stub_keeps_the_stub_rather_than_giving_up(self, tmp_path):
        """PREFERRED, NOT REQUIRED. Squirrel stamps the app's icon onto
        the stub, so a package whose inner executable is gone still has
        artwork worth showing — dropping the whole row to the generic
        parcel would be a downgrade."""
        from utils import nativeicons

        root = self._package(tmp_path, dead=True)
        stub = str(root / "Update.exe")
        target = nativeicons.resolve_command(f'"{stub}" --processStart X.exe')
        assert target.binary == stub
        assert target.kind == "path"


class TestTheStartupRowSaysWhatItIs:
    """The row's two v10.12.1 additions, both of which exist because a
    real machine's list was unreadable without them."""

    @staticmethod
    def _item(**over):
        item = {"Id": "Registry|||HKCU|||electron.app.Notion",
                "Name": "electron.app.Notion", "DisplayName": "Notion",
                "Type": "Registry", "Command": r"C:\gone\Notion.exe",
                "Enabled": True, "Recommendation": "Review",
                "Impact": "Medium", "Reason": "A launcher.",
                "Protected": False, "TargetPresent": True}
        item.update(over)
        return item

    def test_the_row_shows_the_clean_name(self, qapp):
        from frontend import theme as TH
        from frontend.widgets import StartupRow

        row = StartupRow(self._item(), TH.tokens("dark"))
        try:
            assert row._name.fullText() == "Notion"
        finally:
            row.deleteLater()
            qapp.processEvents()

    def test_the_raw_identifier_stays_reachable(self, qapp):
        """It is what somebody would paste into a search, and the only
        thing that tells two entries from the same publisher apart."""
        from frontend import theme as TH
        from frontend.widgets import StartupRow

        row = StartupRow(self._item(), TH.tokens("dark"))
        try:
            assert row._name.toolTip() == "electron.app.Notion"
        finally:
            row.deleteLater()
            qapp.processEvents()

    def test_a_row_with_no_DisplayName_falls_back_to_the_raw_name(self, qapp):
        """A payload from an older backend still renders a coherent row."""
        from frontend import theme as TH
        from frontend.widgets import StartupRow

        item = self._item()
        del item["DisplayName"]
        row = StartupRow(item, TH.tokens("dark"))
        try:
            assert row._name.fullText() == "electron.app.Notion"
        finally:
            row.deleteLater()
            qapp.processEvents()

    def test_a_missing_target_is_captioned_rather_than_left_grey(self, qapp):
        """THE DEFECT THIS PAIR WAS OPENED FOR. Six of fifteen entries on
        the machine measured pointed at binaries that are no longer
        installed. The row asked Windows for an icon, got nothing, and
        drew the neutral parcel — the correct picture, which reads as a
        BROKEN ICON. Six unexplained grey squares look like a defect in
        Pulse; six rows captioned MISSING are six entries worth turning
        off."""
        from frontend import theme as TH
        from frontend.widgets import StartupRow

        row = StartupRow(self._item(TargetPresent=False), TH.tokens("dark"))
        try:
            assert row._missing_badge is not None
            assert row._missing_badge.text() == "MISSING"
            assert "not on this PC" in row._missing_badge.toolTip()
            assert "not installed any more" in row._meta.text()
        finally:
            row.deleteLater()
            qapp.processEvents()

    def test_a_present_target_gets_no_badge(self, qapp):
        from frontend import theme as TH
        from frontend.widgets import StartupRow

        row = StartupRow(self._item(TargetPresent=True), TH.tokens("dark"))
        try:
            assert row._missing_badge is None
            assert "not installed any more" not in row._meta.text()
        finally:
            row.deleteLater()
            qapp.processEvents()

    def test_the_badge_defaults_to_ABSENT_on_an_older_payload(self, qapp):
        """Defaulted to present, so a backend that does not send the
        field renders ordinary rows rather than captioning every entry on
        the machine as broken."""
        from frontend import theme as TH
        from frontend.widgets import StartupRow

        item = self._item()
        del item["TargetPresent"]
        row = StartupRow(item, TH.tokens("dark"))
        try:
            assert row._missing_badge is None
        finally:
            row.deleteLater()
            qapp.processEvents()
