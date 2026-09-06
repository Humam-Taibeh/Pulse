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
