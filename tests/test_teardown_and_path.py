"""
The teardown pair (Edge / OneDrive), the PATH doctor, and the two layout
defects that shipped beside them.

Everything here corresponds to a defect that was REPRODUCED first, and each
one had the same shape: code that looked right, produced no error, and
silently did the wrong thing on a machine that differed from the developer's.

  * Edge's uninstaller lives under a per-version folder and was chosen by
    sorting the PATH STRING descending. Version folders are dotted quads,
    so "99.0.4844.51" sorted ABOVE "141.0.3537.85" — on any machine that
    had ever kept a 9x build, the purge drove a years-old setup.exe against
    a current install.

  * OneDrive's uninstaller was looked for in System32 and SysWOW64 only. A
    client that has updated itself past the inbox stub ships its own copy
    under %LOCALAPPDATA%\\Microsoft\\OneDrive\\<version>\\, and on a build
    with no system stub that copy is the ONLY uninstaller present — so the
    purge reported Failed on exactly the machines whose OneDrive was most
    current.

  * The pre-removal evacuation copied %USERPROFILE%\\OneDrive and nothing
    else. A work or school tenant syncs to "OneDrive - <Org>" beside it,
    and a redirected root is not under the profile at all: the backup
    reported success having rescued none of the files that mattered.

  * PATH Doctor opened with six lines of prose explaining what PATH is, on
    a console about fifteen lines tall, and reported every finding as a
    sentence.

  * A Startup Manager row let a long Run-key name push its two badges into
    the toggle switch.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TWEAKS = os.path.join(_ROOT, "src/backend/modules/06-Tweaks.ps1")
_SAFETY = os.path.join(_ROOT, "src/backend/modules/02-Safety.ps1")

_WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="PowerShell is Windows-only")


def _source(path: str) -> str:
    return open(path, encoding="utf-8-sig").read()


def _powershell(script: str, env_extra: dict | None = None) -> str:
    env = dict(os.environ)
    env.update(env_extra or {})
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, cwd=_ROOT, timeout=300, env=env)
    assert result.returncode == 0, result.stderr[:1000]
    return result.stdout


#: Dot-sources the two modules every helper below needs. 00-Foundation
#: first (it defines the logging and dry-run primitives the rest call),
#: then 01-Catalogs for the data 06-Tweaks closes over.
_PRELUDE = (". './src/backend/modules/00-Foundation.ps1'; "
            ". './src/backend/modules/01-Catalogs.ps1'; "
            ". './src/backend/modules/02-Safety.ps1'; "
            ". './src/backend/modules/06-Tweaks.ps1'; ")


# ============================================================
#  MICROSOFT EDGE
# ============================================================
class TestEdgePurge:
    def test_the_uninstaller_is_chosen_by_version_not_by_path_text(self):
        """The regression in one line: `Sort-Object FullName -Descending`
        on names that are dotted quads."""
        source = _source(_TWEAKS)
        body = source[source.index("function Get-EdgeUninstallerPath"):]
        body = body[:body.index("\nfunction ")]
        assert "Sort-Object Version -Descending" in body, (
            "the Edge uninstaller is no longer ordered by parsed version")
        assert "Sort-Object FullName" not in body, (
            "path-text ordering is back — '99.0.4844.51' sorts above "
            "'141.0.3537.85' and the purge picks a years-old setup.exe")

    @_WINDOWS_ONLY
    def test_a_dotted_quad_really_does_sort_wrong_as_text(self):
        """Pins the PREMISE, not our code. If PowerShell ever changed how
        it compares these, the test above would be guarding nothing."""
        out = _powershell(
            '@("99.0.4844.51","141.0.3537.85") | Sort-Object -Descending | '
            'Select-Object -First 1; '
            '@("99.0.4844.51","141.0.3537.85") | '
            'Sort-Object { [version]$_ } -Descending | Select-Object -First 1')
        as_text, as_version = [ln.strip() for ln in out.split() if ln.strip()]
        assert as_text == "99.0.4844.51"
        assert as_version == "141.0.3537.85"

    def test_the_update_services_are_stopped_before_the_removal_tiers(self):
        """Killing MicrosoftEdgeUpdate.exe closes the CURRENT process; the
        SCM restarts it on the service's own trigger while setup.exe is
        still working. Order is the whole point of the fix, so order is
        what is asserted."""
        source = _source(_TWEAKS)
        purge = source[source.index("function Remove-MicrosoftEdge"):]
        stop = purge.index("Stop-EdgeUpdateServices")
        setup = purge.index("Get-EdgeUninstallerPath")
        assert stop < setup, (
            "the EdgeUpdate services are taken down after the uninstaller "
            "runs — the purge races the thing that undoes it")

    def test_both_update_services_are_named(self):
        source = _source(_TWEAKS)
        body = source[source.index("function Stop-EdgeUpdateServices"):]
        body = body[:body.index("\nfunction ")]
        for name in ("edgeupdate", "edgeupdatem"):
            assert f'"{name}"' in body, f"the '{name}' service is not handled"
        assert "Disabled" in body, (
            "a stopped-but-Automatic service is one reboot from running again")

    def test_the_stub_tasks_are_caught_as_well_as_the_updater_ones(self):
        body = _source(_TWEAKS)
        body = body[body.index("function Remove-EdgeScheduledTasks"):]
        body = body[:body.index("\nfunction ")]
        assert '"MicrosoftEdge*"' in body, (
            "only the MicrosoftEdgeUpdate* tasks are unregistered — the "
            "browser's own stub tasks survive and put Edge back")


# ============================================================
#  MICROSOFT ONEDRIVE
# ============================================================
class TestOneDrivePurge:
    @_WINDOWS_ONLY
    def test_the_per_user_uninstaller_is_found_and_is_the_newest(self, tmp_path):
        """Both halves of the fix at once: the %LOCALAPPDATA% payload is
        consulted at all, and its version folders are compared as versions.

        Get-OneDriveUserSetupPath is called directly rather than through
        Get-OneDriveSetupPath, because reaching this branch through the
        composed function means making the two system stubs miss, and the
        only way to do that is to fake %SystemRoot% — which PowerShell
        resolves the CLR through and refuses to start without.
        """
        od = tmp_path / "local" / "Microsoft" / "OneDrive"
        for version in ("9.9.9.9", "24.201.1005.0004", "23.100.1.1"):
            (od / version).mkdir(parents=True)
            (od / version / "OneDriveSetup.exe").write_bytes(b"")

        out = _powershell(_PRELUDE + "Get-OneDriveUserSetupPath",
                          {"LOCALAPPDATA": str(tmp_path / "local")})
        found = out.strip()
        assert found, "the per-user OneDriveSetup.exe was not found at all"
        assert "24.201.1005.0004" in found, (
            f"picked {found} — version folders are being compared as text, "
            "so 9.9.9.9 wins over 24.201.1005.0004")

    @_WINDOWS_ONLY
    def test_the_system_stubs_are_still_tried_first(self):
        """The per-user payload is a FALLBACK. Windows' own stub is the
        authoritative uninstaller where it exists, and reordering these
        would change which one a normal machine runs."""
        source = _source(_TWEAKS)
        body = source[source.index("function Get-OneDriveSetupPath"):]
        body = body[:body.index("\nfunction ")]
        assert body.index("SysWOW64") < body.index("Get-OneDriveUserSetupPath")

    @_WINDOWS_ONLY
    def test_a_business_sync_root_is_evacuated_too(self, tmp_path):
        """`%USERPROFILE%\\OneDrive` is not the only one. A tenant folder
        beside it was silently left out of the pre-removal backup."""
        profile = tmp_path / "profile"
        for name in ("OneDrive", "OneDrive - Contoso", "Documents"):
            (profile / name).mkdir(parents=True)

        out = _powershell(_PRELUDE + "Get-OneDriveSyncRoots",
                          {"USERPROFILE": str(profile)})
        # Filtered to the fixture: the env-var half of the function falls
        # back to the USER scope by design (it is what catches a stale
        # process environment under elevation), so a real machine's own
        # OneDrive legitimately appears in this list too.
        leaves = sorted(os.path.basename(r.strip())
                        for r in out.splitlines()
                        if r.strip().lower().startswith(str(profile).lower()))
        assert leaves == ["OneDrive", "OneDrive - Contoso"], (
            f"got {leaves} — a tenant folder is missed, or an unrelated "
            "profile folder is being copied")

    @_WINDOWS_ONLY
    def test_a_redirected_root_outside_the_profile_is_found(self, tmp_path):
        """The client's own env vars are what catch a sync root that was
        moved off the profile — the case the profile-relative guess reports
        as 'nothing to back up' while several hundred GB sit elsewhere."""
        profile = tmp_path / "profile"
        profile.mkdir()
        redirected = tmp_path / "D_Drive" / "CloudFiles"
        redirected.mkdir(parents=True)

        out = _powershell(_PRELUDE + "Get-OneDriveSyncRoots",
                          {"USERPROFILE": str(profile),
                           "OneDrive": str(redirected)})
        roots = [ln.strip().lower() for ln in out.splitlines() if ln.strip()]
        assert str(redirected).lower() in roots, (
            f"got {roots} — a redirected sync root is invisible to the backup")

    @_WINDOWS_ONLY
    def test_one_root_named_by_both_sources_is_copied_once(self, tmp_path):
        profile = tmp_path / "profile"
        (profile / "OneDrive").mkdir(parents=True)
        out = _powershell(_PRELUDE + "Get-OneDriveSyncRoots",
                          {"USERPROFILE": str(profile),
                           # same folder, spelled with a trailing separator
                           "OneDrive": str(profile / "OneDrive") + "\\"})
        mine = [r.strip() for r in out.splitlines()
                if r.strip().lower().startswith(str(profile).lower())]
        assert len(mine) == 1, (
            f"the same root is listed twice: {mine} — the same gigabytes "
            "would be robocopied twice")

    def test_each_root_is_backed_up_into_its_own_subfolder(self):
        """Two tenants flattened into one destination merge two different
        "Documents" trees, and nothing afterwards can say which file came
        from where."""
        body = _source(_SAFETY)
        body = body[body.index("function Backup-OneDriveFiles"):]
        body = body[:body.index("\n# =")]
        assert "Join-Path $Script:OneDriveBackupFolder $Leaf" in body, (
            "every sync root is robocopied into the same destination")

    def test_a_failed_root_aborts_the_removal(self):
        """The caller's next act removes the client for every root at once,
        so a partial evacuation is where 'the backup worked' is the most
        dangerous thing to say."""
        body = _source(_SAFETY)
        body = body[body.index("function Backup-OneDriveFiles"):]
        body = body[:body.index("\n# =")]
        assert "$AllOk = $false" in body and "return $AllOk" in body


# ============================================================
#  PATH DOCTOR
# ============================================================
@_WINDOWS_ONLY
class TestPathDoctor:
    """Run once — it costs a PowerShell start — and asserted from one
    capture, because every property here is about the SHAPE of the output
    and they all read the same lines."""

    @pytest.fixture(scope="class")
    @classmethod
    def output(cls):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", "src/backend/core.ps1",
             "-Task", "VerifyEnvironment", "-WhatIf"],
            capture_output=True, text=True, cwd=_ROOT, timeout=300)
        assert result.returncode == 0, result.stderr[:1000]
        return result.stdout

    @staticmethod
    def _findings(output: str) -> list[str]:
        return [ln.strip() for ln in output.splitlines()
                if ln.strip().startswith("[")
                and not ln.strip().startswith("[WHATIF]")]

    def test_the_run_produced_findings(self, output):
        """Guard the parser: an empty list would pass everything below."""
        assert len(self._findings(output)) >= 5, output[:800]

    def test_every_finding_is_a_tagged_line(self, output):
        malformed = [ln for ln in self._findings(output)
                     if not re.match(r"^\[[A-Z]+\]\s", ln)]
        assert not malformed, f"untagged finding(s): {malformed}"

    def test_a_tool_that_resolves_names_the_directory(self, output):
        """'git is ready to use' told the user the outcome and withheld the
        one fact that makes the line verifiable."""
        ok = [ln for ln in self._findings(output) if ln.startswith("[OK]")]
        assert ok, "nothing resolved at all on this machine"
        assert any("->" in ln for ln in ok), (
            f"no [OK] line names where the tool resolved to: {ok}")

    def test_the_explanatory_paragraph_is_gone(self, output):
        """Six lines of prose about what PATH is, printed on every run, at
        the top of a fifteen-line console."""
        for phrase in ("In plain English",
                       "system list called PATH",
                       "nothing scary"):
            assert phrase not in output, (
                f"the PATH explainer is back: {phrase!r}")

    def test_it_scans_the_whole_path_not_only_the_catalogue(self, output):
        assert any(ln.startswith("[SCAN]") and "PATH ->" in ln
                   for ln in self._findings(output)), (
            "no PATH scan line — the doctor still only knows about the "
            "seven catalogued tools")

    def test_the_scan_never_removes_an_entry(self, output):
        """A folder that is merely offline — a network share, an unmounted
        volume — looks exactly like a dead one, so the scan reports and
        leaves the edit to the user."""
        source = _source(os.path.join(
            _ROOT, "src/backend/modules/03-Environment.ps1"))
        scan = source[source.index("function Write-PathScanReport"):]
        scan = scan[:scan.index("\nfunction ")]
        for mutation in ('SetEnvironmentVariable("Path"', "Remove-ItemProperty"):
            assert mutation not in scan, (
                f"the PATH scan mutates the PATH ({mutation})")

    def test_the_verdict_reports_what_the_scan_found(self, output):
        """The toast is all a user sees of a task they ran and looked away
        from. 'Everything's wired up correctly' over a console listing four
        dead entries is the one sentence this task must never say."""
        verdict = next(ln for ln in output.splitlines()
                       if "##PULSE##SUCCESS|" in ln)
        dead = [ln for ln in self._findings(output) if ln.startswith("[DEAD]")]
        if dead:
            assert "PATH scan" in verdict, (
                f"{len(dead)} dead entries were listed and the verdict does "
                f"not mention them: {verdict}")
        else:
            assert "PATH entries resolve" in verdict or "PATH scan" in verdict


# ============================================================
#  STARTUP MANAGER — the crowding fix
# ============================================================
class TestStartupRowLayout:
    """StartupRow is built directly rather than through the dialog: the
    dialog runs a real PowerShell scan on construction, and none of these
    properties depend on what it finds."""

    #: Long enough to have pushed the badges into the switch. This is the
    #: real shape of the entry the defect was reported against.
    _LONG = "MicrosoftEdgeAutoLaunch_9F2A4C118D6E3B75A0C4F821E9"

    @staticmethod
    def _row(window, name: str):
        from frontend.widgets import StartupRow
        return StartupRow({
            "Id": f"reg|HKCU|{name}", "Name": name, "Enabled": True,
            "Impact": "Medium", "Recommendation": "Disable",
            "Type": "Registry", "Reason": "Edge's background updater.",
        }, window.theme.t)

    def test_a_long_name_elides_in_the_middle(self, window, qapp):
        """HEAD AND TAIL BOTH SURVIVE — stated structurally, not as a
        character count.

        The property that matters is that the ellipsis lands in the MIDDLE:
        an Edge auto-launch key is identified at both ends, so an ElideRight
        caption renders "MicrosoftEdgeAutoLaunch_9F2A…" and
        "MicrosoftEdgeAutoLaunch_1C40…" as the same string.

        HOW MANY characters survive is font metrics, and asserting on it
        makes this a test of the machine. The name column takes what the
        row can spare after two unelided badges, so under the offscreen
        platform's fallback face (Sans Serif 16px, where the badges measure
        157px and 252px against Segoe UI's 110px and 148px) the caption
        gets 149px instead of 300px and keeps four leading characters
        instead of sixteen. Both are correct middle elisions of the same
        string; only a literal "Micro" prefix could tell them apart, and it
        failed headless while the widget was behaving perfectly.

        Checking the head and tail against the real name is also strictly
        stronger than the prefix it replaces: it catches a caption that
        elides correctly but paints the WRONG string.
        """
        row = self._row(window, self._LONG)
        row.setFixedWidth(700)
        row.show()
        qapp.processEvents()
        painted = row._name.text().rstrip()
        assert painted != self._LONG, "the name is not eliding at all"
        head, ellipsis, tail = painted.partition("…")
        assert ellipsis, (
            f"{painted!r} carries no ellipsis — the name is being clipped "
            "rather than elided")
        assert head and self._LONG.startswith(head), (
            f"the head of the identifier was dropped: {painted!r}")
        assert tail and self._LONG.endswith(tail), (
            f"{painted!r} elides at the END — two Edge auto-launch keys "
            "would render as the same string")
        assert row.toolTip() or row._name.toolTip(), (
            "the full name is unreachable once elided")
        row.deleteLater()

    def test_a_long_name_costs_the_row_no_minimum_width(self, window, qapp):
        """The mechanism, not the appearance: a caption that reports a
        minimum is a floor the whole row has to honour, and that floor was
        what drove the badges rightward."""
        short = self._row(window, "Steam")
        long_ = self._row(window, self._LONG)
        assert long_._name.minimumSizeHint().width() == 0
        assert (long_.minimumSizeHint().width()
                == short.minimumSizeHint().width()), (
            "a long name still widens the row's minimum")
        short.deleteLater()
        long_.deleteLater()

    def test_the_switch_sits_in_a_fixed_column(self, window, qapp):
        """Same x on every row, whatever precedes it — which is what puts a
        real gutter between the last badge and a control about to be
        clicked."""
        from frontend.widgets import StartupRow
        rows = [self._row(window, self._LONG), self._row(window, "Steam")]
        offsets = []
        for row in rows:
            row.setFixedWidth(700)
            row.show()
            qapp.processEvents()
            cell = row.switch.parentWidget()
            assert cell.width() == StartupRow.SWITCH_COL_W
            offsets.append(row.width() - cell.mapTo(row, cell.rect().topRight()).x())
        assert offsets[0] == offsets[1], (
            f"the switch column moves between rows: {offsets}")
        for row in rows:
            row.deleteLater()

    def test_the_badges_clear_the_switch_column(self, window, qapp):
        row = self._row(window, self._LONG)
        row.setFixedWidth(700)
        row.show()
        qapp.processEvents()
        cell = row.switch.parentWidget()
        badge_right = row._rec_badge.mapTo(
            row, row._rec_badge.rect().topRight()).x()
        cell_left = cell.mapTo(row, cell.rect().topLeft()).x()
        assert badge_right < cell_left, (
            f"the recommendation badge ends at x={badge_right} and the "
            f"switch column starts at x={cell_left} — they overlap")
        row.deleteLater()


def test_the_startup_manager_declares_its_own_width_band():
    """It used to reach ~869px through _content_width_floor — a number
    nobody chose, which fell out of whichever Run key happened to be
    longest on the developer's machine, and which the row's new elision
    would have silently collapsed back to the 840 ceiling."""
    from frontend import widgets as W

    assert (W._STARTUP_WIDTH_MIN, W._STARTUP_WIDTH_MAX) == (880, 900)
    assert W._STARTUP_WIDTH_MIN > W._SELECTOR_WIDTH_MAX, (
        "the Startup Manager band no longer sits above the default one — "
        "declaring it buys nothing")


# ============================================================
#  THEME SWITCH — the three things that made it slow
# ============================================================
class TestThemeSwitchCost:
    """A theme toggle re-skinned the whole app, every time, at ~294ms.

    None of the three causes below is visible in a diff, and all three are
    the kind of thing a later "simplification" restores by accident — so
    each is pinned as a MECHANISM rather than as a duration. A timing
    assertion would be flaky on a loaded CI box and would not say what
    broke; these say exactly what broke.
    """

    #: Tokens are compared by VALUE, never by identity, and that is not
    #: fussiness. ThemeManager.changed is a `Signal(dict)`, so PySide6
    #: marshals the token map through a QVariantMap and every handler
    #: receives a fresh, alphabetically-ordered COPY — `t is TH.tokens(mode)`
    #: is False inside _apply_theme and always has been.
    @staticmethod
    def _is(tokens, mode: str) -> bool:
        from frontend import theme as TH
        return tokens == TH.tokens(mode)

    def test_hidden_pages_are_deferred_rather_than_re_skinned(
            self, window, qapp):
        """Exactly one of the five views is on screen. Re-skinning the other
        four was four fifths of the switch, and nobody could see any of it.
        """
        window.theme.set_mode("dark")
        window.go_home()
        qapp.processEvents()
        calls = []
        for page in window.pages:
            page.apply_theme = (          # type: ignore[method-assign]
                lambda t, p=page: calls.append(p))
        try:
            window.theme.toggle()
            qapp.processEvents()
            assert not calls, (
                f"{len(calls)} hidden page(s) were re-skinned while the "
                "dashboard was the visible view")
            for page in window.pages:
                assert self._is(page._pending_theme, "light"), (
                    "a hidden page was skipped WITHOUT recording what it "
                    "owes — it would stay in the old theme forever")
        finally:
            for page in window.pages:
                del page.apply_theme
            window.theme.set_mode("dark")
            qapp.processEvents()

    def test_a_deferred_page_settles_up_before_it_is_painted(
            self, window, qapp):
        """The other half, and the one that matters for correctness: a page
        hidden through a switch must come back in the CURRENT theme, not the
        one it was last re-skinned for."""
        window.theme.set_mode("dark")
        window.go_home()
        qapp.processEvents()
        page = window.pages[0]
        try:
            window.theme.set_mode("light")
            qapp.processEvents()
            assert self._is(page._pending_theme, "light"), (
                "nothing was deferred, so there is nothing to settle")

            window.open_category(0)
            qapp.processEvents()
            assert page._pending_theme is None, "the debt was never settled"
            assert self._is(page._t, "light"), (
                "the page was shown still carrying the previous theme")
        finally:
            window.go_home()
            window.theme.set_mode("dark")
            qapp.processEvents()

    def test_the_three_container_surfaces_are_one_stylesheet(
            self, window, qapp):
        """setStyleSheet repolishes every descendant unconditionally, so
        three sheets on three NESTED containers walked the same ~500-widget
        tree three times to describe three rectangles."""
        from frontend import theme as TH

        sheets = []
        for widget in (window._shell, window._sidebar, window._content):
            widget.setStyleSheet = (      # type: ignore[method-assign]
                lambda qss, w=widget: sheets.append(w))
        try:
            window._apply_theme(dict(window.theme.t))
            assert sheets == [window._shell], (
                f"{len(sheets)} container sheets were set — the sidebar and "
                "content surfaces are back on their own widgets")
        finally:
            for widget in (window._shell, window._sidebar, window._content):
                del widget.setStyleSheet

        # ...which only works while the two inner rules are ID-scoped, and
        # only while the widgets carry those ids.
        assert window._sidebar.objectName() == "sidebar"
        assert window._content.objectName() == "content"
        chrome = TH.chrome_qss(window.theme.t)
        assert "#sidebar" in chrome and "#content" in chrome
        for rule in chrome.split("}"):
            selector = rule.split("{")[0].strip()
            assert not selector.startswith("QFrame"), (
                f"the chrome sheet carries a bare {selector!r} rule — on the "
                "shell that selects every frame in the app")

    def test_a_style_change_alone_does_not_relayout_a_clamped_label(
            self, window, qapp):
        """A StyleChange is not evidence that the TEXT LAYOUT moved.

        setStyleSheet on any ancestor sends one to every descendant, and a
        switch sets several — so each label ran a full QTextLayout four or
        five times per toggle to produce a byte-identical string, because
        the two themes share one type scale and differ only in colour.
        Measured before the fix: ~2,700 reflows per switch, 35% of the cost.
        """
        from PySide6.QtCore import QEvent
        from frontend.widgets import ClampedLabel

        label = ClampedLabel("A description long enough to need two lines of "
                             "wrapping inside a card of ordinary width.", 2)
        label.setFixedWidth(260)
        label.show()
        qapp.processEvents()
        assert label._reflow_key is not None, "the first layout never ran"

        reflows = []
        original = label._reflow_impl
        label._reflow_impl = (            # type: ignore[method-assign]
            lambda width: (reflows.append(width), original(width))[1])
        try:
            label.setStyleSheet("color: #ff0000;")
            qapp.processEvents()
            assert not reflows, (
                "a colour-only restyle re-laid-out the text")

            # ...and the cache is a skip, not a freeze: a real change still
            # reflows.
            label.setFullText("Something else entirely, of a different "
                              "length, which must be laid out afresh.")
            qapp.processEvents()
            assert reflows, "the text changed and nothing was re-laid-out"
        finally:
            del label._reflow_impl
            label.deleteLater()


# ============================================================
#  THE BRAND BLOCK
# ============================================================
def test_the_title_bar_mark_and_wordmark_carry_the_chrome(window):
    """Icon, label, label — three sizes of quiet. The mark was 20px of
    glyph matched to the nav icons, and the wordmark was an 11px muted
    caption at the same size as the version line it shared the chrome
    with."""
    from frontend import theme as TH
    from frontend import widgets as W

    bar = window.titlebar
    assert bar._glyph.width() == 36, "the title-bar mark is back to chrome size"
    assert bar._glyph._font.pixelSize() == int(36 * W.BrandMark.STATIC_GLYPH_RATIO) == 24
    assert bar._glyph._font.weight() == W.QFont.Weight.DemiBold

    brand = TH.label_qss(window.theme.t, "brand")
    assert "font-size: 14px" in brand
    assert f"color: {window.theme.t['text']};" in brand, (
        "the wordmark is still painted in a secondary tone")
    # THE VERSION LINE, READ WHERE IT ACTUALLY RENDERS. This used to read
    # a `version` LABEL ROLE — 11px/500/text_faint — which nothing in the
    # app had styled anything with since v15 moved the line into the
    # sidebar's status rail. So the assertion passed by measuring a
    # constant, and would have kept passing if the real line had moved to
    # 20px. sidebar_version_qss is the thing that renders it (deriving its
    # size from the `caption` role rather than declaring one), and the
    # dead role went with this change.
    version = TH.sidebar_version_qss(window.theme.t)
    assert f"font-size: {TH.TYPE['meta']}px" in version, (
        "the version line changed too — the point was to separate them")
    assert TH.TYPE["meta"] < TH.TYPE["brand"], (
        "the wordmark no longer outsizes the version line beside it, which "
        "is the separation this whole test exists to hold")


# ============================================================
#  ZERO CONSOLE WINDOWS
# ============================================================
def _brackets_open(text: str) -> bool:
    """True while `text` has an unclosed ( or @( — i.e. PowerShell would
    read the next line as a continuation of this statement.

    Quote-aware, because an argument list is full of strings and a lone
    "(" inside one would otherwise wedge the scan open to end of file.
    Comments are not stripped: a # inside these calls only ever appears
    inside a quoted path, which the quote tracking already covers.
    """
    depth = 0
    quote = ""
    for ch in text:
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
    return depth > 0


class TestSilentExecution:
    """Pulse spawns PowerShell for every task, and PowerShell is a CONSOLE
    program. Windows gives a console program a console window unless it is
    told not to — so every launch site in the app is one flag away from
    flashing a black box over the UI, and the flag is invisible in review
    because leaving it out is not an error, only a difference.

    Two halves, and both are needed:

      the BINARY   `console=False` in the PyInstaller spec, or the packaged
                   app owns a console of its own for its whole life and
                   every child quietly inherits it — at which point the
                   per-call flags below stop mattering, because the window
                   is already there.

      each LAUNCH  CREATE_NO_WINDOW (or a hidden STARTUPINFO) on every
                   subprocess, or that child allocates its own.
    """

    _LAUNCHERS = ("subprocess.Popen(", "subprocess.run(",
                  "subprocess.call(", "subprocess.check_output(",
                  "subprocess.check_call(")

    #: Flags that stop a console window appearing. DETACHED_PROCESS is here
    #: because it also suppresses one, and it is the correct choice for the
    #: single call that uses it (launching the updater's own installer,
    #: which must outlive Pulse) — CREATE_NO_WINDOW cannot be combined with
    #: it, so requiring that specific flag everywhere would be wrong.
    _SUPPRESSORS = ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "SW_HIDE")

    @staticmethod
    def _sources():
        for folder in ("src/frontend", "src/utils"):
            base = os.path.join(_ROOT, folder)
            for name in sorted(os.listdir(base)):
                if name.endswith(".py"):
                    path = os.path.join(base, name)
                    yield path, open(path, encoding="utf-8").read()

    def test_the_packaged_binary_owns_no_console(self):
        spec = open(os.path.join(_ROOT, "main.spec"), encoding="utf-8").read()
        assert "console=False" in spec, (
            "main.spec no longer builds a windowed binary — the packaged "
            "app would show a console behind the UI for its whole life")
        assert "console=True" not in spec

    def test_the_launcher_scan_found_call_sites(self):
        """Guard the scanner: an empty set passes the real check below for
        the wrong reason."""
        found = sum(src.count(fn) for _p, src in self._sources()
                    for fn in self._LAUNCHERS)
        assert found >= 3, f"only {found} subprocess launches found"

    def test_every_subprocess_launch_suppresses_its_console(self):
        """Read per CALL, not per file: one call carrying the flag has
        never made its neighbour safe."""
        naked = []
        for path, src in self._sources():
            for fn in self._LAUNCHERS:
                start = 0
                while (idx := src.find(fn, start)) != -1:
                    start = idx + len(fn)
                    # The call's own argument list, to its closing paren.
                    depth, end = 1, start
                    while end < len(src) and depth:
                        if src[end] == "(":
                            depth += 1
                        elif src[end] == ")":
                            depth -= 1
                        end += 1
                    call = src[idx:end]
                    if any(flag in call for flag in self._SUPPRESSORS):
                        continue
                    # A call that forwards a prepared kwargs mapping carries
                    # its flags there; require the mapping to be built in
                    # the same file with a suppressor in it.
                    if "**" in call and any(f in src for f in self._SUPPRESSORS):
                        continue
                    line = src[:idx].count("\n") + 1
                    naked.append(f"{os.path.relpath(path, _ROOT)}:{line}")
        assert not naked, (
            "subprocess launch(es) with no console-suppressing flag — each "
            f"one flashes a window over the UI: {naked}")

    #: Backend Start-Process targets that are GUI programs or shell
    #: verbs. None of them can be given a console, so none of them can
    #: flash one, and -NoNewWindow on a ShellExecute verb is an error.
    #: Named individually rather than exempting whole files, because the
    #: files they live in also launch the uninstallers that DO need it.
    _NO_CONSOLE_TARGETS = (
        "explorer",     # restarting the shell after a taskbar tweak
        "taskmgr",      # opened because the user asked for Task Manager
        "cleanmgr",     # a GUI applet
        "notepad",      # the log, from console mode
        "ie4uinit",     # already -WindowStyle Hidden
    )

    #: ...and the one call that must keep its console: console mode
    #: re-launching itself elevated. -Verb RunAs is ShellExecute.
    _ELEVATION_VERB = "-Verb RunAs"

    @staticmethod
    def _ps_calls(src: str):
        """(line, text) for every Start-Process in `src`, with PowerShell's
        backtick line-continuations folded in.

        Written as a scan rather than a regex because the continuation is
        exactly what a regex gets wrong here: the backtick sits at the end
        of the line, so any `[^\n]*` written to grab the first line eats it
        and the continuation can never match — which silently turned three
        correctly-silenced calls into failures on the first attempt.
        """
        lines = src.splitlines()
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#") or "Start-Process" not in line:
                continue
            call, cursor = line, index
            # TWO WAYS A POWERSHELL CALL CONTINUES, and folding only the
            # first left a hole this guard could be walked straight
            # through. A trailing backtick is the explicit continuation;
            # an UNCLOSED BRACKET is the implicit one, and an argument
            # list written as
            #
            #     Start-Process -FilePath x `
            #         -ArgumentList @("a",
            #                         "b") `
            #         -NoNewWindow
            #
            # stops the backtick-only scan dead at the comma on line 2 —
            # so every switch after it, -NoNewWindow included, was
            # invisible. The call read as unsilenced when it was silenced,
            # which is the harmless direction; the same blind spot hides a
            # genuinely unsilenced call written the same way, which is not.
            while cursor + 1 < len(lines) and (
                    call.rstrip().endswith("`")
                    or _brackets_open(call)):
                cursor += 1
                call += " " + lines[cursor].strip()
            yield index + 1, call

    def test_the_backend_launch_scan_found_call_sites(self):
        found = sum(1 for _f, _l, _c in self._backend_calls())
        assert found >= 10, f"only {found} backend Start-Process calls found"

    @classmethod
    def _backend_calls(cls):
        backend = os.path.join(_ROOT, "src/backend")
        for folder, _dirs, files in os.walk(backend):
            for fname in sorted(f for f in files if f.endswith(".ps1")):
                path = os.path.join(folder, fname)
                for line, call in cls._ps_calls(_source(path)):
                    yield fname, line, call

    def test_every_backend_launch_of_a_console_tool_is_silenced(self):
        """The PowerShell half of the same contract, and the half that
        actually shipped broken.

        A GUI task's engine runs with no console of its own, but
        Start-Process ALLOCATES one for a console child unless told
        otherwise — so the bloatware codec uninstaller and the local-file
        installer each threw a black box over the UI for as long as they
        ran, despite both being silent operations. `-NoNewWindow` makes the
        child share the parent's console, which here is no console at all.

        Only calls naming a -FilePath are checked. `Start-Process <url>`
        and `Start-Process ms-windows-store://...` are ShellExecute on a
        protocol handler and never get a console.
        """
        offenders = []
        for fname, line, call in self._backend_calls():
            if "-FilePath" not in call:
                continue                       # a URL or a protocol verb
            if "-NoNewWindow" in call or "-WindowStyle Hidden" in call:
                continue
            if self._ELEVATION_VERB in call:
                continue
            if any(f'"{name}"' in call or f"'{name}'" in call
                   or f"{name}.exe" in call
                   for name in self._NO_CONSOLE_TARGETS):
                continue
            offenders.append(f"{fname}:{line}  {call.strip()[:100]}")
        assert not offenders, (
            "backend Start-Process call(s) that will flash a console "
            "window over the UI:\n  " + "\n  ".join(offenders))

    def test_the_powershell_engine_hides_its_window_two_ways(self):
        """The engine is the one launched on every single task, so it wears
        belt and braces: CREATE_NO_WINDOW stops the console being allocated,
        and a hidden STARTUPINFO covers the case where something in the
        chain re-associates one anyway."""
        src = open(os.path.join(_ROOT, "src/utils/helpers.py"),
                   encoding="utf-8").read()
        block = src[src.index("popen_kwargs = dict("):src.index("job.assign(process)")]
        for needed in ("CREATE_NO_WINDOW", "STARTF_USESHOWWINDOW", "SW_HIDE"):
            assert needed in block, (
                f"PowerShellTask no longer sets {needed} before Popen")


# ============================================================
#  UNINSTALLER RESILIENCY
# ============================================================
class TestOneDriveResiliency:
    """"Already gone" is a SUCCESS state. Reporting it as a failure was the
    defect: on a machine whose OneDrive had already been removed, the stub
    Windows leaves in System32 was still found, still run, still returned
    0x8004069B - and Pulse reported a hard error for a machine that was
    already in exactly the state the user asked for.
    """

    def test_the_not_installed_exit_code_is_treated_as_already_gone(self):
        body = _source(_TWEAKS)
        table = body[body.index("$Script:OneDriveAlreadyGoneCodes"):]
        table = table[:table.index(")")]
        assert "-2147219813" in table, (
            "0x8004069B is no longer classified as 'already gone' — the "
            "purge reports a crash on a machine with no OneDrive")

    def test_a_missing_uninstaller_is_not_a_failure(self):
        """There is nothing left to run because there is nothing left to
        uninstall. The traces are still ours to clear."""
        body = _source(_TWEAKS)
        purge = body[body.index("function Remove-OneDrivePackage"):]
        purge = purge[:purge.index("\nfunction ")]
        branch = purge[purge.index("if (-not $ODSetup)"):]
        branch = branch[:branch.index("if (Test-DryRun \"Run OneDriveSetup")]
        assert "'Failed'" not in branch, (
            "a missing OneDriveSetup.exe still reports Failed")
        assert "AlreadyRemoved" in branch
        assert "Complete-OneDriveRemoval" in branch, (
            "the already-gone path skips the registry/folder cleanup, so a "
            "machine keeps its OneDrive stubs forever")

    def test_every_success_path_runs_the_same_cleanup(self):
        """Three ways to arrive at 'OneDrive is not here any more', and all
        three leave the same traces behind. Cleaning up on one branch only
        is how a machine ends up half-removed."""
        body = _source(_TWEAKS)
        purge = body[body.index("function Remove-OneDrivePackage"):]
        purge = purge[:purge.index("\nfunction ")]
        assert purge.count("Complete-OneDriveRemoval") == 4, (
            "expected the shared cleanup on the pre-flight, no-uninstaller, "
            "clean-exit and already-gone paths")

    def test_the_telemetry_hive_is_purged(self):
        body = _source(_TWEAKS)
        stubs = body[body.index("function Clear-OneDriveRegistryStubs"):]
        stubs = stubs[:stubs.index("\nfunction ")]
        assert "HKCU:\\Software\\Microsoft\\OneDrive" in stubs

    def test_a_folder_with_files_in_it_is_never_deleted(self):
        """THE SAFETY PROPERTY OF THIS WHOLE FEATURE, asserted at the source
        because the live version of this test would have to create a folder
        it is willing to lose.

        A sync root can hold the only copy of a file — anything created
        locally that never finished uploading, plus every folder that was
        never selected for sync on another device. The emptiness test is
        what stands between an uninstall tidy-up and deleting that."""
        body = _source(_SAFETY + "")   # keep the import used
        del body
        tweaks = _source(_TWEAKS)
        fn = tweaks[tweaks.index("function Remove-EmptyOneDriveFolders"):]
        fn = fn[:fn.index("\nfunction ")]
        assert "-File -ErrorAction SilentlyContinue" in fn and "-Recurse" in fn, (
            "the emptiness test no longer recurses — a folder whose files "
            "are all in subdirectories would read as empty and be deleted")
        guard = fn.index("$Contents.Count -gt 0")
        remove = fn.index("Remove-Item")
        assert guard < remove, (
            "the delete is no longer behind the emptiness guard")


class TestEdgeForcePurge:
    """Exit 93 is a REFUSAL, not a fault, and retrying it reproduces it
    forever — which is what the previous implementation did, three times,
    before reporting failure."""

    def test_the_blocked_codes_are_classified(self):
        body = _source(_TWEAKS)
        table = body[body.index("$Script:EdgeUninstallBlockedCodes"):]
        table = table[:table.index(")")]
        assert "93" in table, "setup.exe's UNINSTALL_NOT_ALLOWED is unhandled"
        assert "1603" in table, "winget's block code is unhandled"

    def test_a_block_escalates_instead_of_retrying(self):
        body = _source(_TWEAKS)
        purge = body[body.index("function Remove-MicrosoftEdge"):]
        assert "Invoke-WithRetry -OperationName \"Remove Microsoft Edge" not in purge, (
            "the uninstaller is back on the retry helper — a build that "
            "answers 93 answers 93 every time")
        first = purge.index("Invoke-EdgeSetupUninstall")
        policy = purge.index("Set-EdgeUninstallPolicy")
        dma = purge.index("Invoke-EdgeUninstallUnderDmaRegion")
        assert first < policy < dma, (
            "the escalation ladder is out of order: plain attempt, then "
            "Microsoft's own AllowUninstall policy, then the DMA region")

    def test_the_region_is_always_put_back(self):
        """GeoID is not ours. It feeds regional defaults well outside this
        app, so it is borrowed for the seconds the uninstaller runs and
        restored even if that throws."""
        body = _source(_TWEAKS)
        fn = body[body.index("function Invoke-EdgeUninstallUnderDmaRegion"):]
        fn = fn[:fn.index("\nfunction ")]
        assert "} finally {" in fn, (
            "the region restore is not in a finally — an uninstaller that "
            "throws would leave the machine in another country")
        # "} finally {" and not the bare word: the docstring above says
        # the word too, and matching that would pass on a function whose
        # code had no finally at all.
        restore = fn.index("} finally {")
        assert fn.index("return (Invoke-EdgeSetupUninstall") < restore, (
            "the uninstall does not run inside the try whose finally "
            "restores the region")
        assert "Set-RegValue" in fn[restore:], (
            "the finally does not write the region back")

    def test_the_uninstall_policy_is_always_put_back(self):
        body = _source(_TWEAKS)
        purge = body[body.index("function Remove-MicrosoftEdge"):]
        block = purge[purge.index("Set-EdgeUninstallPolicy"):]
        block = block[:block.index("if ($Code -eq 0)")]
        assert "finally" in block and "Restore-EdgeUninstallPolicy" in block, (
            "AllowUninstall is left switched on after the purge")

    def test_provisioned_packages_are_deregistered_too(self):
        """Remove-AppxPackage unregisters Edge for the users who have it;
        only Remove-AppxProvisionedPackage takes it out of the IMAGE, which
        is what stops it returning for the next user to sign in."""
        body = _source(_TWEAKS)
        fn = body[body.index("function Remove-EdgeAppxRegistrations"):]
        fn = fn[:fn.index("\nfunction ")]
        assert "Remove-AppxPackage" in fn
        assert "Remove-AppxProvisionedPackage" in fn, (
            "Edge is unregistered but not deprovisioned — it comes back")
        assert "DevToolsClient" in fn, (
            "the OS-protected stub is no longer filtered out; it throws "
            "mid-loop and aborts the removals that would have worked")


# ============================================================
#  BRAND MARKS — authentic, full colour, one presentation
# ============================================================
class TestBrandMarks:
    """Every catalog row used to show a RECOLOURED SILHOUETTE: Simple Icons
    is a monochrome set, so Chrome was a flat blue disc, Steam a flat black
    one, and the four-colour wheel that makes Chrome recognisable simply
    was not there. Only Edge and VS Code carried real artwork.
    """

    @staticmethod
    def _manifest():
        import json
        with open(os.path.join(_ROOT, "assets/appicons/manifest.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    #: Marks that are legitimately MONOCHROME, with the reason each one is.
    #: A silhouette is authentic in shape and wrong in every other respect,
    #: so the bar for staying on this list is that no colour artwork exists
    #: — not that none was looked for.
    MONOCHROME_BY_DESIGN = {
        # Cursor's own brand cube IS monochrome; a "colour" version would
        # be an invention.
        "Anysphere.Cursor",
        # Antigravity's arch is likewise drawn in one ink. The colour
        # renditions on offer are Google's four-colour blobs, which are the
        # COMPANY's mark rather than this product's.
        "Google.Antigravity",
        # NVIDIA's eye, from Simple Icons, carrying the brand green
        # (#76B900) through the contrast guard. The full-colour `logos`
        # entry is the eye PLUS the wordmark at a 512x98 viewBox, which
        # letterboxes into a 20px square about four pixels tall — so the
        # square silhouette is genuinely the better artwork here.
        "XP8CLZL93F5Z4P",
    }

    def test_almost_every_bundled_mark_is_full_colour(self):
        """A recoloured silhouette is the fallback, not the target — see
        the module note in src/utils/appicons.py on why the split used to
        run 34:2 the wrong way."""
        manifest = self._manifest()
        mono = {k for k, v in manifest.items() if not v.get("color")}
        assert mono == self.MONOCHROME_BY_DESIGN, (
            "monochrome mark set changed.\n"
            f"  newly monochrome (is there really no colour artwork?): "
            f"{sorted(mono - self.MONOCHROME_BY_DESIGN)}\n"
            f"  no longer monochrome (update MONOCHROME_BY_DESIGN): "
            f"{sorted(self.MONOCHROME_BY_DESIGN - mono)}")

    def test_a_monochrome_mark_renders_as_its_shape_not_a_block(self, qapp):
        """THE BUG THIS CATCHES SHIPPED. The recolour composited SourceIn
        straight onto the icon, and SourceIn keeps the DESTINATION's alpha
        — which under the mark is the WELL, and the well is opaque. So
        every monochrome mark painted a solid tinted SQUARE instead of its
        own silhouette. Cursor shipped that way; measured at 95% of the
        pixmap near-opaque, against ~23% for a real full-colour logo.

        Asserted by COUNTING PIXELS rather than by reading the code,
        because the code looked right: the clip that was supposed to
        contain the fill was clipping to exactly the region the well
        fills."""
        from frontend import theme as TH
        from utils import appicons

        for mode in ("dark", "light"):
            t = TH.tokens(mode)
            for app_id in sorted(self.MONOCHROME_BY_DESIGN):
                appicons.invalidate_cache()
                pixmap = appicons.app_icon(app_id, 44, t, app_id)
                image = pixmap.toImage()
                side = image.width()
                opaque = sum(
                    1
                    for y in range(side)
                    for x in range(side)
                    if image.pixelColor(x, y).alpha() > 200)
                filled = opaque / float(side * side)
                assert filled < 0.5, (
                    f"{app_id} ({mode}) fills {filled:.0%} of its box — it is "
                    "painting a solid block, not a silhouette")

    def test_the_named_brands_carry_their_real_artwork(self):
        """The specific ones the sprint called out, each checked by AppId
        so a renamed catalog entry fails loudly rather than silently
        dropping back to a silhouette."""
        manifest = self._manifest()
        for app_id in ("Google.Chrome", "Valve.Steam",
                       "EpicGames.EpicGamesLauncher",
                       "RockstarGames.Launcher",
                       # Temurin replaced Oracle's JRE in the catalog, and
                       # its mark was WRONG rather than missing: it pointed
                       # at logos:eclipse-icon, the Eclipse IDE's circle —
                       # a different product from the same foundation.
                       "EclipseAdoptium.Temurin.21.JDK",
                       # Likewise MSYS2, which carried the GNU project's
                       # gnu head: 18KB of line art that resolved to a grey
                       # smudge at 20px.
                       "MSYS2.MSYS2",
                       "Microsoft.DotNet.DesktopRuntime.8",
                       "Guru3D.Afterburner"):
            entry = manifest.get(app_id)
            assert entry and entry.get("color"), (
                f"{app_id} is not a full-colour mark: {entry}")

    def test_no_mark_uses_currentcolor(self):
        """`color: true` means "render as drawn". A file that is actually a
        currentColor silhouette flagged that way paints black-on-black."""
        import json
        manifest = self._manifest()
        wrong = []
        for app_id, entry in sorted(manifest.items()):
            if not entry.get("color"):
                continue
            path = os.path.join(_ROOT, "assets/appicons", entry["file"])
            if "currentColor" in open(path, encoding="utf-8").read():
                wrong.append(app_id)
        assert not wrong, f"flagged full-colour but drawn as silhouettes: {wrong}"

    #: Catalog rows with NO BUNDLED MARK AT ALL, and the reason each is a
    #: gap. A CLOSED list, so the two tests below can fail in BOTH
    #: directions rather than only the one anyone thought of.
    #:
    #: THIS USED TO HOLD EIGHT ENTRIES and now holds two, because the six
    #: that were gaps for a "no mark exists anywhere" reason — BlueStacks,
    #: DirectX, CPU-Z, GPU-Z, HWMonitor, CrystalDiskInfo — now carry
    #: PULSE-DRAWN marks. Nothing was found for them; the search was
    #: re-run across every collection Iconify aggregates and still returns
    #: zero. What changed is the decision, not the availability: nine grey
    #: parcels in a nine-row group read as a broken list rather than as an
    #: honest fallback, so the marks are drawn and LABELLED as drawn. See
    #: test_contract.py::test_no_mark_is_a_lookalike, which is the guard
    #: that keeps that exception narrow, and DRAWN_MAP in
    #: tools/fetch_app_icons.py for the full reasoning.
    #:
    #: The two that remain are here for reasons a drawn mark does not
    #: answer, and both could still close properly:
    #:
    #:   THE MARK EXISTS BUT THE LICENCE DOES NOT FIT — WinRAR. Its real
    #:   stacked-books logo is in OpenMoji (CC BY-SA 4.0); taking it would
    #:   put a copyleft obligation on an MIT app for one row. The only
    #:   permissive "winrar" is a generic archive pictogram wearing the
    #:   name, which is a lookalike and still forbidden.
    #:
    #:   THE MARK EXISTS BUT THE GEOMETRY DOES NOT — OpenAL. Every
    #:   published mark is a WORDMARK at roughly 128x24; the runtime draws
    #:   into a 20px square (see appicons._MARK_RATIO), where a wordmark
    #:   is an illegible smear. This one closes the day a square mark
    #:   exists, and is worth distinguishing from "none exists" for that
    #:   reason.
    NO_AUTHENTIC_MARK = frozenset({
        "RARLab.WinRAR", "CreativeTechnology.OpenAL",
    })

    def test_every_catalog_app_has_a_mark_or_is_a_known_exception(self):
        """THE DIRECTION NOTHING CHECKED. The manifest was verified against
        the files it names, and the six unmarked apps were pinned as
        absent — but nothing ever asked whether the OTHER catalog rows had
        marks at all.

        So adding an app to SOFTWARE_CATALOG and forgetting its SVG was
        silent: the row rendered the neutral package glyph, which is a
        legitimate tier-3 result and therefore looks deliberate. In a
        column of thirty-seven real logos the odd grey parcel reads as the
        scavenged look this whole system exists to remove, and the only
        way to notice was to scroll the list and count.
        """
        from frontend.menu_structure import catalog_app_ids
        manifest = self._manifest()
        unmarked = {app_id for app_id in catalog_app_ids()
                    if app_id not in manifest}
        assert unmarked == set(self.NO_AUTHENTIC_MARK), (
            "catalog apps with no bundled mark changed.\n"
            f"  newly unmarked (add the SVG, or document it): "
            f"{sorted(unmarked - self.NO_AUTHENTIC_MARK)}\n"
            f"  no longer unmarked (update NO_AUTHENTIC_MARK): "
            f"{sorted(self.NO_AUTHENTIC_MARK - unmarked)}")

    def test_no_bundled_mark_outlives_the_app_it_was_fetched_for(self):
        """The other half: an SVG for an app the catalog has since dropped
        is dead weight in the bundle and a logo Pulse ships for software it
        no longer offers."""
        from frontend.menu_structure import catalog_app_ids
        orphans = sorted(set(self._manifest()) - set(catalog_app_ids()))
        assert not orphans, (
            f"bundled marks for apps not in the catalog: {orphans}")

    def test_nothing_was_taken_for_the_brands_with_no_mark(self):
        """WinRAR and OpenAL still have no bundled mark, and each must stay
        absent for its OWN reason rather than acquiring a convenient one.

        The failure this guards is not carelessness, it is convenience: a
        keyword search offers a plausible-looking file for both (a generic
        archive pictogram for WinRAR, a wordmark for OpenAL), and either
        would silently close the gap with something that is not the
        vendor's mark or is not legible at 20px.

        A DRAWN mark would not be an acceptable answer here either, which
        is why this survived the change that emptied most of this set: the
        nine drawn marks exist because nothing at all was available, while
        for these two something exists and is merely unusable — a licence
        to respect and a geometry to fix, not a hole to paper over.
        """
        manifest = self._manifest()
        for app_id in sorted(self.NO_AUTHENTIC_MARK):
            assert app_id not in manifest, (
                f"{app_id} acquired a mark — check it is really that "
                "vendor's logo and not a keyword lookalike, that its "
                "licence is CC0/MIT rather than copyleft, and that it is "
                "square enough to read at 20px")

    def test_every_icon_is_one_size_in_one_well(self, window, qapp):
        """Uniform GEOMETRY is what makes a column of logos read as a set.
        Brand SVGs disagree wildly about their own internal padding, so
        "as large as fits" produced marks at visibly different optical
        sizes — the thing that reads as scavenged however authentic each
        one is."""
        from utils import appicons
        from frontend import widgets as W

        assert W.APP_ICON_PX == 36
        assert round(appicons._MARK_RATIO * W.APP_ICON_PX) == 20, (
            "the mark is no longer 20px inside a 36px well")
        assert round(appicons._WELL_RADIUS_RATIO * W.APP_ICON_PX) == 8

        t = window.theme.t
        # The rasterisation ratio follows the SCREEN as of v10.9.5 (it was a
        # hardcoded 2.0, which resampled on every display that was not
        # exactly 200%). Uniformity is therefore asserted on the LOGICAL
        # size — the one the layout lays out and the eye compares — with
        # crispness asserted as "at least the logical size, at the screen's
        # own ratio" rather than as one fixed multiple of it.
        dpr = appicons._screen_dpr()
        logical_sizes = set()
        for app_id, name in (("Google.Chrome", "Google Chrome"),
                             ("Valve.Steam", "Steam"),
                             ("NotAnApp.AtAll", "Nothing Like This")):
            pm = appicons.app_icon(name, W.APP_ICON_PX, t, app_id=app_id)
            assert not pm.isNull()
            assert pm.devicePixelRatio() == pytest.approx(dpr), (
                f"{app_id} was rasterised for a {pm.devicePixelRatio()} "
                f"screen on a {dpr} one — Qt has to resample it")
            assert pm.size().width() == round(W.APP_ICON_PX * dpr), (
                "the pixmap no longer carries the screen's worth of detail")
            logical_sizes.add(round(pm.size().width() / pm.devicePixelRatio()))
        assert logical_sizes == {W.APP_ICON_PX}, (
            f"the column renders at {logical_sizes} logical px — uniform "
            "geometry is what makes a row of logos read as a set")

    def test_a_black_mark_is_rescued_on_the_dark_canvas(self, window, qapp):
        """Steam, Epic, Notion, Ollama and 7-Zip are all essentially
        #000000 artwork. On obsidian they get the near-white plate an app
        store would give them; everything else keeps the quiet neutral.
        Measured, not listed — see appicons._rescue_well."""
        from PySide6.QtGui import QColor
        from PySide6.QtSvg import QSvgRenderer
        from utils import appicons
        from frontend import theme as TH

        dark_surface = appicons._parse_color(TH.tokens("dark")["dialog_bg"],
                                             "#16181d")
        resting = appicons._well_color(dark_surface, True)

        def well_for(app_id):
            entry = appicons._manifest()[app_id]
            path = os.path.join(_ROOT, "assets/appicons", entry["file"])
            renderer = QSvgRenderer(path)
            return appicons._rescue_well(renderer, 72, dark_surface, True)

        assert well_for("EpicGames.EpicGamesLauncher") != resting, (
            "Epic's black mark is left on the quiet well — invisible")
        assert well_for("Google.Chrome") == resting, (
            "a vivid mark was given a rescue plate it does not need")

        # STEAM IS THE THIRD CASE, and it is here because it MOVED. It was
        # the example this test opened with: `logos:steam` is a single
        # #1a1918 silhouette, so Steam needed the white plate for exactly
        # the same reason Epic does. Its mark is now the authentic
        # blue-gradient disc, which carries its own colour and reads on
        # obsidian unaided — so the rescue is no longer applied, and that
        # is the observable signature of the artwork fix rather than a
        # weakening of the guard. If this flips back, Steam has quietly
        # returned to a flat dark silhouette.
        assert well_for("Valve.Steam") == resting, (
            "Steam is being rescued again — its mark has gone back to a "
            "flat near-black silhouette")


# ============================================================
#  SEARCH — typos, translation, and a readable result list
# ============================================================
class TestPaletteSearch:
    @staticmethod
    def _top(query, limit=3):
        from frontend import widgets as W
        from frontend import menu_structure as MS
        normalised = W.normalise_query(query)
        rows = []
        for item, category in MS.iter_leaf_items():
            hit = W._match_entry(normalised, item, category)
            if hit is not None:
                rows.append((hit[0], item.get("title", "")))
        rows.sort(key=lambda r: (-r[0], r[1]))
        return [title for _score, title in rows[:limit]]

    def test_arabic_is_normalised_before_anything_compares_it(self, qapp):
        """The same word, typed four ways, has to fold to one string:
        harakat are optional, tatweel is decoration, and the alef and yeh
        forms depend on the keyboard."""
        from frontend import widgets as W
        base = W.normalise_query("\u0627\u062d\u0630\u0641")          # احذف
        for variant in ("\u0623\u062d\u0630\u0641",                   # أحذف
                        "\u0627\u064e\u062d\u0652\u0630\u0650\u0641",  # with harakat
                        "\u0627\u0640\u062d\u0630\u0641"):           # with tatweel
            assert W.normalise_query(variant) == base, (
                f"{variant!r} does not fold to {base!r}")

    def test_every_alias_key_is_stored_already_normalised(self, qapp):
        """A DEAD ENTRY IN THE TRANSLATION TABLE LOOKS EXACTLY LIKE A
        MISSING ONE.

        The lookup is `SEARCH_ALIASES.get(normalise_query(text))`, so a key
        written in any form normalise_query would fold — a hamza'd alef, a
        final ى, a ة, a stray harakat — can never be produced by that call
        and is therefore unreachable for the life of the table. Nothing
        raises; the query simply finds nothing, which is indistinguishable
        from the word not being in the table at all.

        SEARCH_ALIASES' own comment states the rule ("Keys are stored
        already normalised"), and a rule stated only in a comment is one
        the next entry gets to break. Every key is currently correct; this
        keeps it that way.
        """
        from frontend import widgets as W
        unreachable = {k: W.normalise_query(k) for k in W.SEARCH_ALIASES
                       if W.normalise_query(k) != k}
        assert not unreachable, (
            "alias key(s) not stored in normalised form, so no query can "
            f"ever reach them: {unreachable}")

    def test_escape_closes_the_palette_without_choosing(self, window, qapp):
        """Esc is the one binding the palette's own footer advertises that
        had no test. It has to REJECT — closing with a selection still
        armed would run whatever happened to be highlighted."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from frontend import menu_structure as MS
        from frontend import widgets as W
        from conftest import show_dialog

        palette = W.CommandPalette(window, window.theme.t,
                                   list(MS.iter_leaf_items()))
        show_dialog(qapp, palette)
        try:
            palette._search.setText("remove")
            qapp.processEvents()
            assert palette._list.currentRow() >= 0, "nothing was selected"
            qapp.sendEvent(palette._search, QKeyEvent(
                QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                Qt.KeyboardModifier.NoModifier))
            qapp.processEvents()
            assert not palette.isVisible(), "Esc did not close the palette"
            assert palette.chosen_item is None, (
                "Esc closed the palette WITH a chosen item — it dismissed "
                "and launched at the same time")
        finally:
            palette.reject()
            palette.deleteLater()
            qapp.processEvents()

    def test_arabic_queries_reach_the_right_operations(self, qapp):
        cases = {
            "\u062a\u062d\u062f\u064a\u062b": "Check for Updates",     # تحديث
            "\u062a\u0646\u0638\u064a\u0641": "Aggressive Cache Clean",  # تنظيف
            "\u0628\u0631\u0627\u0645\u062c": "Essential Daily Software",      # برامج
        }
        for query, expected in cases.items():
            top = self._top(query)
            assert top and top[0] == expected, (
                f"{query!r} ranked {top} — expected {expected!r} first")

    def test_an_english_verb_finds_the_card_it_describes(self, qapp):
        """A user types the verb they want far more often than the noun a
        card happens to be titled with."""
        assert "Remove Bloatware" in self._top("uninstall", 4)
        assert "Optimize All Drives" in self._top("speed", 4)

    def test_a_typo_still_finds_the_operation(self, qapp):
        for typo, expected in (("cahce", "Aggressive Cache Clean"),
                               ("powr", "Ultimate Power Plan"),
                               ("startap", "Startup Manager")):
            top = self._top(typo, 3)
            assert expected in top, f"{typo!r} ranked {top}"

    def test_a_typo_never_outranks_a_real_match(self, qapp):
        """A misspelling is the weakest evidence the palette accepts. If it
        could outscore a literal hit, one near-miss would displace the
        answer the user actually typed."""
        from frontend import widgets as W
        assert W._MATCH_TYPO_TITLE < W._MATCH_FUZZY_TITLE < W._MATCH_ALIAS
        assert W._MATCH_ALIAS < W._MATCH_CONTENT_EXACT

    def test_an_app_name_finds_the_pillar_that_installs_it(self, qapp):
        """The structured matcher's own regression cases, re-run — and
        TIGHTENED by the pillar split.

        These used to assert that an app name reached "Software Catalog",
        the single card that installed everything. With three catalog
        cards the question gets a sharper answer: the top hit has to be
        the pillar that ACTUALLY CONTAINS the app, because the other two
        cannot install it.

        That is not automatic, and the split broke it first. Every catalog
        card carried the whole catalog in its search contents, so all three
        scored identically on "spotify" and the alphabetical tiebreak put
        Developer first — a card that does not install Spotify. See
        menu_structure.search_contents.
        """
        assert self._top("spotify", 1) == ["Essential Daily Software"]
        assert self._top("winrar", 1) == ["Essential Daily Software"]
        assert self._top("docker", 1) == ["Developer, AI & Engineering"]
        assert self._top("antigravity", 1) == ["Developer, AI & Engineering"]
        assert self._top("directx", 1) == ["Runtimes & Hardware Drivers"]
        assert self._top("crystaldiskinfo", 1) == ["Runtimes & Hardware Drivers"]

    def test_no_pillar_claims_an_app_it_cannot_install(self, qapp):
        """The general form of the case above, over every catalog row.

        A pillar that lists an app it does not contain sends the user to a
        surface where the app is not there — and the palette gives no hint
        that the list it opened was the wrong one."""
        from frontend import menu_structure as MS
        wrong = []
        for category in MS.CATEGORIES:
            for item in MS.category_items(category):
                key = item.get("catalog_section")
                if not item.get("catalog") or not key:
                    continue
                own = {tool[1] for tool in MS.catalog_tools(key)}
                claimed = set(MS.search_contents(item))
                titles = {section["title"] for section in MS.SOFTWARE_CATALOG}
                stray = claimed - own - titles - {MS.catalog_section(key)["title"]}
                if stray:
                    wrong.append(f"{item['title']} also claims {sorted(stray)[:4]}")
        assert not wrong, (
            "catalog card(s) naming apps they do not open:\n  "
            + "\n  ".join(wrong))

    def test_a_group_heading_is_grouped_with_its_own_rows(self, qapp):
        """Padding above, tight below — the heading has to belong to what
        is UNDER it. At the old spacing it sat nearly equidistant between
        two groups and the list read as one undifferentiated column."""
        from frontend import theme as TH
        assert TH.PALETTE_SECTION_PAD_TOP == 12
        assert TH.PALETTE_SECTION_PAD_TOP > TH.PALETTE_SECTION_PAD_BOTTOM
        assert TH.PALETTE_SECTION_H == (TH.PALETTE_SECTION_PAD_TOP
                                        + TH.PALETTE_SECTION_TEXT_H
                                        + TH.PALETTE_SECTION_PAD_BOTTOM)

    def test_groups_are_separated_by_a_rule_except_the_first(self, window, qapp):
        from PySide6.QtWidgets import QFrame
        from frontend import widgets as W
        from frontend import menu_structure as MS
        from conftest import show_dialog

        palette = W.CommandPalette(window, window.theme.t,
                                   list(MS.iter_leaf_items()))
        show_dialog(qapp, palette)
        try:
            palette._search.setText("remove")
            qapp.processEvents()
            headers = [palette._list.itemWidget(palette._list.item(row))
                       for row in range(palette._list.count())
                       if not palette._is_result(row)]
            assert len(headers) >= 2, "not enough groups to test separation"
            rules = [h.findChild(QFrame) for h in headers]
            assert rules[0] is not None and not rules[0].isVisible(), (
                "the first group carries a rule — a line directly under "
                "the search field, separating nothing")
            assert all(r is not None and r.isVisible() for r in rules[1:]), (
                "a group after the first has no separating rule")
        finally:
            palette.reject()
            palette.deleteLater()
            qapp.processEvents()
