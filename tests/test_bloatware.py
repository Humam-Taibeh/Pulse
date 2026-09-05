"""
tests/test_bloatware.py

The bloatware purge's FRONTEND half, and the seams between it and the
catalog it renders.

The matching and classification rules live in PowerShell and are covered
against a mocked AppX inventory by tests/backend/Bloatware.Tests.ps1 —
that is where "does '*Messenger*' claim the shell?" is answered. What
cannot be answered there is whether the two halves still agree: the
dialog declares its own section order, its own optional tier and its own
Select All policy, all of which are restatements of facts the catalog
owns. Every one of those is a place the two can drift apart silently,
because a mismatch renders as a missing section rather than as an error.

The other half is the safety policy the GUI is solely responsible for:

  * "Select All Bloatware" must never sweep the optional Xbox tier. The
    identity provider signs Store games in and the gaming overlay is what
    Win+G opens; a control that took those without being asked is the
    single most damaging click in the app.
  * A package that is not installed must never be selectable, or the
    purge reports removing things that were never there.
"""
from __future__ import annotations

import os
import re

import pytest

from conftest import settle, show_dialog, wait_until
from frontend import menu_structure as MS
from frontend import theme as TH
from frontend.widgets import BloatRow, BloatwarePurgeDialog

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CATALOG = os.path.join(_ROOT, "src", "backend", "modules", "01-Catalogs.ps1")


def _catalog_source() -> str:
    return open(_CATALOG, encoding="utf-8-sig").read()


def _catalog_entries() -> list[dict]:
    """The `$Script:BloatCatalog` rows, read off the PowerShell literal.

    Parsed rather than imported for the reason every other backend mirror
    in this suite is parsed: the catalog is PowerShell, pytest is Python,
    and shelling out to read a data table would make a fast test slow and
    a Windows-only test Windows-only for no gain.
    """
    source = _catalog_source()
    start = source.index("$Script:BloatCatalog = @(")
    end = source.index("$Script:BloatProtected", start)
    rows = []
    for line in source[start:end].splitlines():
        line = line.strip()
        if not line.startswith("@{"):
            continue
        entry = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', line))
        entry["Optional"] = "Optional = $true" in line
        rows.append(entry)
    return rows


def _protected_patterns() -> list[str]:
    """The wildcards no catalog pattern may claim, off the same literal.

    Sliced line-by-line rather than to the next ")": the block's own
    comments contain parentheses, so an index search finds the wrong one
    and silently returns nothing — which is exactly the "passes while
    testing air" failure the guard above exists to catch.
    """
    source = _catalog_source()
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.startswith("$Script:BloatProtected = @("))
    end = next(i for i in range(start + 1, len(lines))
               if lines[i].rstrip() == ")")
    return re.findall(r'"([^"]+)"', chr(10).join(lines[start:end]))


# ============================================================
#  1. THE CATALOG MIRROR
# ============================================================
def test_the_catalog_was_actually_parsed():
    """Guards every assertion below: a parser that silently matched
    nothing would make the whole file pass while testing air."""
    entries = _catalog_entries()
    assert len(entries) >= 40, f"only parsed {len(entries)} catalog entries"
    assert _protected_patterns(), "no protected patterns parsed"


def test_the_dialog_renders_a_section_for_every_catalog_group():
    """A group the dialog does not declare is a group whose packages never
    appear — and the failure renders as a shorter list, not as an error.

    This is the one seam where the backend can grow something the
    frontend silently drops on the floor.
    """
    declared = {key for key, _title, _optional in BloatwarePurgeDialog.SECTIONS}
    in_catalog = {e["Group"] for e in _catalog_entries()}
    missing = in_catalog - declared
    assert not missing, (
        f"catalog groups with no section in the dialog: {sorted(missing)}")
    unused = declared - in_catalog
    assert not unused, (
        f"the dialog renders sections nothing lands in: {sorted(unused)}")


def test_the_optional_tier_agrees_end_to_end():
    """`Optional` is declared TWICE — once per catalog entry, and once as
    the third element of a dialog section. They have to mean the same
    thing, because Select All reads the dialog's copy while the headless
    purge reads the catalog's, and a disagreement means the two paths
    remove different sets from the same machine."""
    optional_groups = {key for key, _t, opt in BloatwarePurgeDialog.SECTIONS if opt}
    for entry in _catalog_entries():
        if entry["Group"] in optional_groups:
            assert entry["Optional"], (
                f"{entry['Id']} sits in an optional section but is not "
                "flagged Optional, so a headless purge would remove it")
        else:
            assert not entry["Optional"], (
                f"{entry['Id']} is flagged Optional but sits in a section "
                "Select All ticks")


def test_every_group_the_row_can_render_has_a_glyph():
    """BloatRow picks its plaque glyph by group. A group with no entry
    falls back silently, which is how one section ends up wearing another
    section's icon."""
    for group in {e["Group"] for e in _catalog_entries()}:
        assert group in BloatRow._GLYPHS, f"no plaque glyph for group {group!r}"
    for glyph_key in BloatRow._GLYPHS.values():
        assert glyph_key in TH.GLYPHS, f"{glyph_key!r} is not in theme.GLYPHS"


# ============================================================
#  2. THE TASK WIRING
# ============================================================
def test_the_card_opens_the_selector_instead_of_a_confirm_sheet():
    """The dialog names every package it is about to remove, which is a
    stronger confirmation than a yes/no sheet — and a worse experience to
    sit behind one. `bloatware` therefore REPLACES `confirm`."""
    item = MS.find_action_anywhere("RemoveBloatware")[0]
    assert item is not None, "the Remove Bloatware card has gone"
    assert item.get("bloatware"), "the card no longer opens the purge selector"
    assert not item.get("confirm"), (
        "the card carries both a selector and a confirm sheet — two modals "
        "for one decision is what people learn to click through")


def test_the_scan_is_unprivileged_and_the_purge_is_not():
    """Enumerating packages needs no rights, so opening the dialog must
    never raise a UAC prompt. Removing them writes machine state, so the
    task behind it must."""
    assert "RemoveBloatware" in MS.ADMIN_REQUIRED_TASKS
    assert "BloatwareScan" not in MS.ADMIN_REQUIRED_TASKS, (
        "gating the scan would prompt for elevation just to look at what "
        "is installed")


# ============================================================
#  3. THE SELECTION POLICY (the part only the GUI enforces)
# ============================================================
_ENTRIES = [
    {"Id": "BingNews", "Name": "News", "Group": "core", "Note": "n",
     "Detected": True, "Optional": False, "Installed": ["Microsoft.BingNews"],
     "Provisioned": [], "Desktop": []},
    {"Id": "TikTok", "Name": "TikTok", "Group": "promo", "Note": "n",
     "Detected": False, "Optional": False, "Installed": [],
     "Provisioned": [], "Desktop": []},
    {"Id": "XboxGamingOverlay", "Name": "Xbox Gaming Overlay",
     "Group": "gaming", "Note": "n", "Detected": True, "Optional": True,
     "Installed": ["Microsoft.XboxGamingOverlay"], "Provisioned": [],
     "Desktop": []},
    {"Id": "KLiteCodec", "Name": "K-Lite Codec Pack", "Group": "codec",
     "Note": "n", "Detected": True, "Optional": False, "Installed": [],
     "Provisioned": [], "Desktop": ["K-Lite Codec Pack 18.0.5"]},
]


@pytest.fixture
def no_live_scan(monkeypatch):
    """Construct the purge dialog WITHOUT letting it scan.

    The fixtures below have always CLAIMED "no backend, no thread", but
    nothing made it true: BloatwarePurgeDialog.__init__ calls _start_scan()
    unconditionally, which puts a real PowerShellTask on a real QThread and
    spawns powershell.exe against the empty ps1 path these tests pass. That
    scan fails within ~10ms and _on_scan_failed switches the stack to the
    error page — CLOBBERING the results page the test just rendered by
    hand. Every assertion that reads a child's isVisible() then answers
    False about a dialog that is in every respect correct.

    It is the same hazard TestRunningApps.no_live_scan documents for the
    Update Center, and it has the same fix: do not start the thread, rather
    than race its teardown. The settle path keeps its own coverage in
    tests/test_audit_hardening.py, where the worker IS the subject.
    """
    monkeypatch.setattr(BloatwarePurgeDialog, "_start_scan",
                        lambda self: None)


@pytest.fixture
def purge(window, qapp, no_live_scan):
    """A rendered dialog with a fixed inventory — no backend, no thread.

    The scan is bypassed on purpose: what is under test here is what the
    dialog DOES with an inventory, and driving that through a live
    PowerShell scan would make the assertions depend on which packages
    happen to be installed on the machine running the suite.
    """
    dialog = BloatwarePurgeDialog(window, "", window.theme.t)
    # show_dialog, not show()+settle(60): every assertion below reads
    # isVisible() on a child, and showing a top-level window is
    # asynchronous — see conftest.wait_until for the once-in-ten-runs
    # failure the fixed wait produced inside the full suite.
    show_dialog(qapp, dialog)
    dialog._render(list(_ENTRIES))
    settle(qapp, 60)
    yield dialog
    dialog.reject()
    dialog.deleteLater()
    qapp.processEvents()


def test_select_all_never_sweeps_the_optional_tier(purge):
    """THE MOST DAMAGING CLICK IN THE APP, if it were wrong. Removing the
    gaming overlay takes Game Bar's screen capture; removing the identity
    provider can lock a user out of games they already own. Neither is
    something a control labelled "Select All Bloatware" may decide."""
    purge._select_all(True)
    swept = [r.entry_id for r in purge._rows.values() if r.is_selected() and r.optional]
    assert not swept, f"Select All ticked the optional tier: {swept}"
    assert purge._rows["BingNews"].is_selected(), (
        "Select All did not tick a detected, non-optional package")


def test_the_optional_tier_can_still_be_chosen_by_hand(purge):
    """Excluded from the bulk control, never removed from the dialog: a
    user who wants the Xbox stack gone must be able to say so."""
    row = purge._rows["XboxGamingOverlay"]
    assert row.checkbox.isEnabled()
    row.set_checked(True)
    assert row.is_selected()
    purge._accept_selection()
    assert "XboxGamingOverlay" in purge.selected_ids


def test_an_absent_package_can_never_be_selected(purge):
    """A purge that reported removing things which were never installed
    would be lying in the direction users trust."""
    row = purge._rows["TikTok"]
    assert not row.checkbox.isEnabled()
    row.set_checked(True)                 # the bulk path
    row.checkbox.setChecked(True)         # and a direct one
    assert not row.is_selected()
    purge._select_all(True)
    assert "TikTok" not in [
        r.entry_id for r in purge._rows.values() if r.is_selected()]


def test_a_desktop_leftover_is_selectable_without_an_appx_identity(purge):
    """K-Lite has no package name at all — it is found through the
    uninstall hive. `Detected` has to be what drives the row, not the
    presence of an AppX match, or the whole codec tier is unreachable."""
    row = purge._rows["KLiteCodec"]
    assert row.detected and row.checkbox.isEnabled()
    assert row.is_selected(), "the recommended pre-tick skipped a desktop entry"


def test_absent_rows_are_folded_away_until_asked_for(purge, qapp):
    """48 entries and a clean machine has one of them. The first build
    rendered every row and buried the single result under forty-seven
    'NOT PRESENT' ones."""
    assert not purge._show_absent.isChecked()
    # wait_until, not a bare read: the row's visibility is settled by the
    # dialog's own layout pass, which the fixture has started but Qt may
    # not have delivered yet on a loaded machine.
    assert wait_until(qapp, purge._rows["BingNews"].isVisible)
    assert not purge._rows["TikTok"].isVisible()
    purge._show_absent.setChecked(True)
    assert purge._rows["TikTok"].isVisible(), (
        "the catalog cannot be inspected even on request")


@pytest.fixture
def clean(window, qapp, no_live_scan):
    """A machine with nothing catalogued on it."""
    dialog = BloatwarePurgeDialog(window, "", window.theme.t)
    show_dialog(qapp, dialog)          # see the note in the purge fixture
    dialog._render([{**e, "Detected": False, "Presence": "absent",
                     "Installed": [], "Provisioned": [], "Desktop": [],
                     "Startup": []} for e in _ENTRIES])
    settle(qapp, 60)
    yield dialog
    dialog.reject()
    dialog.deleteLater()
    qapp.processEvents()


class TestTheCleanMachine:
    """THE ANSWER GOES ABOVE THE EVIDENCE, and it used to go below it.

    With nothing detected the dialog forced "show packages that aren't
    installed" ON, DISABLED the toggle so it could not be turned off, and
    rendered all forty-eight rows — every one greyed, unticked and
    captioned NOT PRESENT — with a one-line "this system is clean" label
    underneath them. The good news was therefore the smallest text on
    screen, at the bottom, under three sections of evidence against it,
    and the one control that could have hidden that evidence had been
    switched off and locked.

    That lock is also the whole of the "the toggle does nothing" report:
    a user pressing a disabled checkbox gets exactly what a broken one
    gives them.
    """

    def test_it_shows_a_clean_state_rather_than_the_catalog(self, clean, qapp):
        assert wait_until(qapp, clean._clean_page.isVisible)
        assert not clean._results_page.isVisible(), (
            "forty-eight NOT PRESENT rows are still on screen")

    def test_the_headline_is_the_loudest_thing_on_it(self, clean, qapp):
        from PySide6.QtWidgets import QLabel
        headline = next(
            l for l in clean._clean_page.findChildren(QLabel)
            if l.text() == "Your system is clean")
        assert headline.isVisible()
        assert headline.styleSheet() == TH.label_qss(clean._t, "dialog"), (
            "the clean verdict is not rendered at the dialog-title weight")

    def test_it_says_what_was_checked_and_in_which_senses(self, clean, qapp):
        """"Clean" is a claim about a search, and a claim about a search
        that does not say what it searched is worth very little."""
        note = clean._clean_note.text()
        assert str(len(clean._rows)) in note, (
            f"the clean state does not say how many packages were checked: "
            f"{note!r}")
        for sense in ("installed", "staged", "pinned"):
            assert sense in note.lower(), (
                f"the clean state does not mention {sense}: {note!r}")

    def test_the_toggle_is_live_rather_than_locked_on(self, clean):
        """THE DEFECT, stated as the property that made it one."""
        assert clean._show_absent.isEnabled(), (
            "the toggle is disabled, so pressing it does nothing")
        assert not clean._show_absent.isChecked()

    def test_turning_it_on_reveals_the_catalog(self, clean, qapp):
        clean._show_absent.setChecked(True)
        assert wait_until(qapp, clean._results_page.isVisible)
        assert wait_until(qapp, clean._rows["TikTok"].isVisible), (
            "the catalog cannot be inspected even on request")

    def test_and_turning_it_off_goes_back(self, clean, qapp):
        """A filter you cannot switch off is a trap; so is one you cannot
        switch back."""
        clean._show_absent.setChecked(True)
        settle(qapp, 40)
        clean._show_absent.setChecked(False)
        assert wait_until(qapp, clean._clean_page.isVisible)

    def test_the_inspect_link_is_the_same_switch(self, clean, qapp):
        """One state, one control. A link that had its own way of showing
        the catalog would leave the checkbox disagreeing with the page."""
        clean._inspect_btn.click()
        settle(qapp, 40)
        assert clean._show_absent.isChecked()
        assert wait_until(qapp, clean._results_page.isVisible)

    def test_nothing_can_be_purged_from_it(self, clean):
        assert not clean._purge_btn.isEnabled()

    def test_the_redundant_bottom_label_is_gone(self, clean, qapp):
        """It said what the subtitle and the clean page both say, in the
        one position where the good news is least likely to be read."""
        from PySide6.QtWidgets import QLabel
        texts = [l.text().lower() for l in clean.findChildren(QLabel)
                 if l.isVisible()]
        assert not any("nothing catalogued is installed" in t for t in texts), (
            "the old static empty label is still rendered")


def test_the_purge_button_reports_what_it_will_do(purge):
    """A destructive CTA that does not say how many is one people press to
    find out."""
    purge._select_all(False)
    assert not purge._purge_btn.isEnabled()
    purge._select_all(True)
    assert purge._purge_btn.isEnabled()
    assert re.search(r"\(\d+\)", purge._purge_btn.text()), (
        f"the CTA reads {purge._purge_btn.text()!r} with a selection made")


# ============================================================
#  6. EVERY ROW LOOKS LIKE ITSELF  (v16)
# ============================================================
class TestRowIdentity:
    """THE DEFECT, stated as what the user saw: every row wore the same
    mark. The plaque glyph was chosen per catalog GROUP, so the twenty-five
    rows in "Pre-installed stubs and promotions" were twenty-five identical
    trash cans, and telling Clipchamp from Candy Crush meant reading every
    label — in the one dialog whose whole job is deciding about apps ONE AT
    A TIME.

    THREE TIERS, THE SAME ORDER THE REST OF THE APP USES: the vendor's own
    mark where one exists and survives 20px, this app's Fluent pictogram
    where it does not, and the catalog group's glyph as the floor. Disney+
    and Prime Video are deliberately on tier two — every published mark for
    either is a WORDMARK, which is four illegible letterforms in a 20px
    square — and nothing is invented for them.
    """

    def test_the_mark_ids_are_namespaced_away_from_winget(self):
        """`Bloat.Skype` and a hypothetical winget `Skype` must never be
        able to answer for one another in one manifest."""
        row = BloatRow(dict(_ENTRIES[0]), TH.tokens("dark"))
        try:
            assert row._mark_id == "Bloat." + row.entry_id
        finally:
            row.deleteLater()

    def test_a_branded_row_renders_its_brand_mark(self, window, qapp):
        from utils import appicons
        entry = {"Id": "Instagram", "Name": "Instagram", "Group": "promo",
                 "Note": "n", "Detected": True, "Presence": "installed",
                 "Optional": False, "Installed": ["Instagram"],
                 "Provisioned": [], "Desktop": [], "Startup": []}
        row = BloatRow(entry, window.theme.t)
        try:
            assert "Bloat.Instagram" in appicons.manifest_ids()
            assert row._mark is not None, "the row fell back to a glyph"
            assert row.plaque is None
            assert not row._mark.pixmap().isNull()
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_an_unbranded_row_gets_its_own_pictogram_not_the_group_one(
            self, window, qapp):
        """Groove Music has no mark in any open set and must still not
        look like Candy Crush."""
        made = {}
        for entry_id, name in (("ZuneMusic", "Groove Music"),
                               ("KingGames", "Candy Crush")):
            entry = {"Id": entry_id, "Name": name, "Group": "promo",
                     "Note": "n", "Detected": True, "Presence": "installed",
                     "Optional": False, "Installed": [name],
                     "Provisioned": [], "Desktop": [], "Startup": []}
            row = BloatRow(entry, window.theme.t)
            made[entry_id] = row
        try:
            for row in made.values():
                assert row.plaque is not None and row.plaque.text()
            assert made["ZuneMusic"].plaque.text() != made["KingGames"].plaque.text(), (
                "two unrelated promo apps still wear the same mark")
        finally:
            for row in made.values():
                row.deleteLater()
            qapp.processEvents()

    def test_every_declared_pictogram_is_a_real_glyph(self):
        """A key with no GLYPHS entry renders as an empty string, which is
        an invisible icon rather than an error."""
        keys = set(BloatRow._APP_GLYPHS.values()) | set(BloatRow._GLYPHS.values())
        missing = sorted(k for k in keys if k not in TH.GLYPHS)
        assert not missing, f"pictogram keys absent from theme.GLYPHS: {missing}"

    def test_every_pictogram_names_a_real_catalog_entry(self):
        """A typo'd Id is a pictogram nothing will ever render."""
        from conftest import bloat_catalog_ids
        stray = sorted(set(BloatRow._APP_GLYPHS) - bloat_catalog_ids())
        assert not stray, f"pictograms for entries the catalog lacks: {stray}"

    def test_no_catalogued_row_is_left_on_the_group_fallback(self):
        """The floor must stay a floor. Every entry should be answered by
        a brand mark or by its own pictogram; a row still falling through
        to "one glyph per layer" is one this pass missed."""
        from conftest import bloat_catalog_ids
        from utils import appicons
        branded = {a[len("Bloat."):] for a in appicons.manifest_ids()
                   if a.startswith("Bloat.")}
        covered = branded | set(BloatRow._APP_GLYPHS)
        uncovered = sorted(bloat_catalog_ids() - covered)
        assert not uncovered, (
            f"rows with neither a mark nor a pictogram: {uncovered}")


# ============================================================
#  7. THE BADGE REPORTS WHICH SENSE OF "HERE"  (v16)
# ============================================================
class TestPresence:
    """A package can be on this machine in four different senses and the
    row used to report two. The one that was missing is the one that made
    the dialog wrong out loud: a Start-menu PINNED stub is visibly on the
    machine and was captioned NOT PRESENT.
    """

    def _row(self, presence, **extra):
        entry = {"Id": "DisneyPlus", "Name": "Disney+", "Group": "promo",
                 "Note": "n", "Optional": False, "Installed": [],
                 "Provisioned": [], "Desktop": [], "Startup": [],
                 "Detected": presence != "absent", "Presence": presence}
        entry.update(extra)
        return BloatRow(entry, TH.tokens("dark"))

    @pytest.mark.parametrize("presence,text", [
        ("installed", "INSTALLED"),
        ("staged", "STAGED"),
        ("pinned", "PINNED"),
        ("absent", "NOT PRESENT"),
    ])
    def test_each_sense_reads_as_itself(self, presence, text):
        row = self._row(presence)
        try:
            assert row._badge.text() == text
            assert row._badge.toolTip(), (
                "a one-word chip with no explanation is a decoration")
        finally:
            row.deleteLater()

    def test_a_pinned_stub_is_selectable(self):
        """It is on the machine, so the purge must be able to take it —
        which is the whole point of detecting it."""
        row = self._row("pinned", Startup=["DisneyPlus"])
        try:
            assert row.detected and row.checkbox.isEnabled()
            row.set_checked(True)
            assert row.is_selected()
        finally:
            row.deleteLater()

    def test_a_pinned_stub_names_the_package_it_would_remove(self):
        """The Startup tier carries a real package name, and this is the
        row where "what am I actually removing?" is hardest to answer from
        the friendly name."""
        row = self._row("pinned", Startup=["Disney.37853FC22B2CE"])
        try:
            assert "Disney.37853FC22B2CE" in row._note.text()
        finally:
            row.deleteLater()

    def test_an_old_payload_without_the_field_still_renders(self):
        """Defensive about shape, like the Update Center's running flag:
        a backend that predates `Presence` must produce a coherent row
        rather than a blank badge."""
        entry = {"Id": "TikTok", "Name": "TikTok", "Group": "promo",
                 "Note": "n", "Detected": True, "Optional": False,
                 "Installed": ["TikTok"], "Provisioned": [], "Desktop": []}
        row = BloatRow(entry, TH.tokens("dark"))
        try:
            assert row._badge.text() == "INSTALLED"
        finally:
            row.deleteLater()

    def test_an_unknown_value_falls_back_rather_than_blanking(self):
        row = self._row("something-new")
        try:
            assert row._badge.text() in ("INSTALLED", "NOT PRESENT")
        finally:
            row.deleteLater()
