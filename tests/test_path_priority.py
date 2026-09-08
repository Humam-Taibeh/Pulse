"""
THE PATH DOCTOR'S THIRD CARD: which copy of a tool your terminal runs.

WHAT THE SCAN COULD ALREADY DO, and where it stopped. Write-PathScanReport
has printed [SHADOWED] lines since v10.10 — "you have two Pythons, and
this is the one that answers" — and then ended. The only fix on offer was
for the user to go and reorder an environment variable by hand, which is
exactly where they were before they opened the tool: the finding was
correct, complete, and not actionable.

WHY THE FIX IS A REORDER AND NOT A REMOVAL. Every copy that answered a
command before still answers it afterwards; one of them simply answers
first. That is what lets this card be un-confirmed and un-red beside a
prune that is both — and it is a property, not an intention, so
PathDoctor.Tests.ps1 asserts the permutation directly and these tests
assert that the GUI cannot ask for anything else.

WHAT THESE TESTS COVER that the Pester suite cannot: the argv the dialog
builds, the buttons it draws for options the backend has already refused,
and the card's place in the hub.
"""
from __future__ import annotations

import os

import pytest

from frontend import menu_structure as MS
from frontend import theme as TH
from frontend.widgets import PathConflictDialog
from utils.helpers import PowerShellTask

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORE = os.path.join(_ROOT, "src", "backend", "core.ps1")


def _report(**overrides) -> dict:
    """One TOOLCHAIN with three installations — the shape the backend
    sends since v10.12.1.

    Deliberately covers all three verdicts at once: the machine-scope
    installation that currently wins, a second machine-scope one that CAN
    be promoted, and a user-scope one that cannot be promoted past either
    of them however the user PATH is sorted.
    """
    report = {
        "entries": 24,
        "elevated": True,
        "conflicts": [{
            "key": "python",
            "command": "Python",
            "commands": ["pip", "pip3", "python"],
            "winner": r"C:\Python311",
            "count": 3,
            "options": [
                {"path": r"C:\Python311",
                 "dirs": [r"C:\Python311\Scripts", r"C:\Python311"],
                 "scope": "Machine", "version": "3.11.9",
                 "commands": ["pip", "pip3", "python"], "winner": True,
                 "action": "none", "short": "In use",
                 "reason": "Python already runs from C:\\Python311."},
                {"path": r"C:\Python313",
                 "dirs": [r"C:\Python313\Scripts", r"C:\Python313"],
                 "scope": "Machine", "version": "3.13.1",
                 "commands": ["pip", "pip3", "python"], "winner": False,
                 "action": "reorder", "short": "Use this one",
                 "reason": "moves 2 folders to the front of the Machine "
                           "PATH; nothing is removed."},
                {"path": r"C:\Users\me\AppData\Local\Programs\Python\Python312",
                 "dirs": [r"C:\Users\me\AppData\Local\Programs\Python\Python312"],
                 "scope": "User", "version": "3.12.4",
                 "commands": ["python"], "winner": False,
                 "action": "blocked", "short": "Needs administrator",
                 "reason": "Windows always searches the system PATH before "
                           "your user PATH, so this copy cannot be moved in "
                           "front of the system one in C:\\Python311. Run "
                           "Pulse as administrator to promote the system "
                           "installation instead."},
            ],
        }],
    }
    report.update(overrides)
    return report


def _buttons(dialog):
    """Every button the REPORT drew — the dialog's own footer controls
    are excluded by name so a new one cannot silently join the set."""
    from PySide6.QtWidgets import QPushButton

    footer = {"Close", "Re-scan", "Restart as administrator"}
    return [b for b in dialog.findChildren(QPushButton)
            if b.text() not in footer]


def _labels(dialog) -> str:
    from PySide6.QtWidgets import QLabel

    return " ".join(label.text() for label in dialog.findChildren(QLabel))


# ============================================================
#  THE ARGV
# ============================================================
class TestTheCommandLine:
    """A PATH entry is a Windows directory, and a Windows directory may
    contain a comma."""

    def test_both_values_ride_their_own_parameters(self):
        """NOT -AppIds, which is a comma-separated LIST. "C:\\Program
        Files\\Acme, Inc\\bin" is a legal directory name, and split on its
        comma it becomes two fragments matching nothing — so the promotion
        would be refused for a folder the user could see was valid."""
        directory = r"C:\Program Files\Acme, Inc\bin"
        argv = PowerShellTask(_CORE, "PathPrioritize",
                              path_command="python",
                              path_directory=directory)._build_argv()
        assert argv[argv.index("-PathCommand") + 1] == "python"
        assert argv[argv.index("-PathDirectory") + 1] == directory
        assert "-AppIds" not in argv

    def test_a_quote_character_survives_verbatim(self):
        """The same property every other user-supplied value has: it
        reaches argv unchanged, and nothing downstream re-parses it."""
        directory = "C:\\Users\\Sam\\O\u2019Brien\u2019s tools"
        argv = PowerShellTask(_CORE, "PathPrioritize",
                              path_command="node",
                              path_directory=directory)._build_argv()
        assert argv[argv.index("-PathDirectory") + 1] == directory

    def test_the_parameters_are_absent_when_unused(self):
        """Every other task must not grow two empty parameters."""
        argv = PowerShellTask(_CORE, "SystemInfo")._build_argv()
        assert "-PathCommand" not in argv
        assert "-PathDirectory" not in argv

    def test_core_declares_both_parameters(self):
        """argv is only half the contract — the engine has to bind them."""
        source = open(_CORE, encoding="utf-8-sig").read()
        header = source[:source.index("# ============", source.index("param("))]
        assert "$PathCommand" in header
        assert "$PathDirectory" in header


# ============================================================
#  THE CARD
# ============================================================
class TestTheCard:

    def test_it_lives_in_the_path_doctor_hub(self):
        """Beside the scan that finds the problem, not on the dashboard.
        A user who has never looked at their PATH should not be offered a
        button that reorders it."""
        found = None
        for category in MS.CATEGORIES:
            for item in MS.category_items(category):
                if not item.get("hub"):
                    continue
                for child in MS.hub_items(item):
                    if child.get("task") == "PathConflictReport":
                        found = (item, child)
        assert found is not None, (
            "the shadowed-tools card is not inside any hub")
        hub, card = found
        assert "PATH Doctor" in hub["title"]
        assert card.get("path_conflicts") is True

    def test_it_is_neither_red_nor_confirmed(self):
        """DELIBERATE, beside a prune that is both. This card REORDERS —
        every copy stays on the PATH and a wrong choice costs one click to
        undo. Dressing a reversible reorder in the same red as an
        irreversible delete teaches the user that the red means nothing.
        """
        card = next(c for cat in MS.CATEGORIES
                    for item in MS.category_items(cat) if item.get("hub")
                    for c in MS.hub_items(item)
                    if c.get("task") == "PathConflictReport")
        assert not card.get("danger")
        assert not card.get("confirm")

    def test_the_read_is_unelevated_and_the_write_is_not(self):
        """Listing which tools are shadowed needs no rights, and gating it
        would raise a UAC prompt to LOOK at the problem. Reordering writes
        a PATH and opens with a restore point, so it is gated exactly like
        the prune."""
        assert not MS.requires_admin("PathConflictReport")
        assert MS.requires_admin("PathPrioritize")


# ============================================================
#  THE DIALOG
# ============================================================
class TestTheDialog:

    def test_one_card_per_toolchain_not_per_command(self, window, qapp):
        """THE CONSOLIDATION, stated as what it removes.

        The scan is command-shaped, so the first cut of this dialog drew
        a card for `python`, another for `pip` and a third for `pip3` —
        three cards asking one question three times about the same two
        installed Pythons. Worse, they were three INDEPENDENT questions:
        nothing stopped a user promoting 3.14's python and 3.12's pip,
        which is a machine where `pip install` puts packages somewhere
        `python` cannot import them.
        """
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            text = _labels(dialog)
            # One card, and it names the toolchain rather than a command.
            assert "Python" in text
            assert "3 INSTALLATIONS" in text
            # The commands it covers are stated once, on that one card.
            assert "pip, pip3, python" in text
            # Three installations, so three action buttons — not nine.
            assert len(_buttons(dialog)) == 3
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_a_button_says_the_verdict_never_a_path(self, window, qapp):
        """THE TRUNCATION FIX, and it is a change of ROLE rather than of
        formatting.

        The buttons used to carry the option's identity as an elided path
        — "…\\Python\\Python312\\Scripts" — so the control the user
        clicks was a cut-off string and the reason it was disabled was a
        paragraph underneath it. The identity moved to the row; the
        button now carries the backend's own short verdict.
        """
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            texts = [b.text() for b in _buttons(dialog)]
            assert texts == ["In use", "Use this one", "Needs administrator"]
            for text in texts:
                assert "\\" not in text, f"a path leaked onto a button: {text}"
                assert "…" not in text, f"a truncated string on a button: {text}"
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_row_carries_the_identity_the_button_no_longer_does(
            self, window, qapp):
        """Version, scope and path all have to be somewhere, and that
        somewhere is the row."""
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            text = _labels(dialog)
            for version in ("3.11.9", "3.13.1", "3.12.4"):
                assert version in text, f"{version} is not on any row"
            assert "System PATH" in text and "Your PATH" in text
            assert r"C:\Python313" in text
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_an_installation_says_how_many_folders_move_with_it(
            self, window, qapp):
        """A Python is a root AND a Scripts directory, and promoting one
        without the other is the failure this feature exists to prevent.
        The row says so before the user clicks."""
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            assert "+1 more folder" in _labels(dialog)
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_current_winner_is_shown_selected_and_inert(
            self, window, qapp):
        """Re-applying what is already set would run an elevated task to
        achieve no change."""
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            winner = next(b for b in _buttons(dialog) if b.text() == "In use")
            assert not winner.isEnabled()
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_an_option_the_backend_refused_is_not_offered(
            self, window, qapp):
        """THE ASSERTION THIS FILE EXISTS FOR.

        Windows composes the search path as machine-then-user, so a
        user-scope installation can never overtake a machine-scope one.
        The backend marks that option `blocked`; a dialog that drew a
        live button anyway would let the user click it, see a toast, and
        still have the same problem — strictly worse than offering
        nothing, because now they believe it is fixed.
        """
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            blocked = next(b for b in _buttons(dialog)
                           if b.text() == "Needs administrator")
            assert not blocked.isEnabled()
            # The long form is still reachable — in the place a long form
            # belongs, rather than as a paragraph on the card.
            assert "system PATH" in blocked.toolTip()
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_no_paragraph_of_excuses_is_printed_on_the_card(
            self, window, qapp):
        """The reason a control is unavailable belongs ON the control.
        Printing it as body text put three sentences of PATH-composition
        theory in the middle of a list the user is trying to scan."""
        text = None
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            text = _labels(dialog)
        finally:
            dialog.deleteLater()
            qapp.processEvents()
        assert "Run Pulse as administrator to promote" not in text, (
            "the blocked reason is being dumped onto the card again")

    def test_the_shield_appears_only_when_rights_are_the_blocker(
            self, window, qapp):
        """SEAMLESS, BUT NOT DECORATIVE. An unelevated Pulse looking at a
        machine whose only conflict is inside the user PATH needs no
        shield, and offering one there teaches the user that the button
        means nothing."""
        blocked = PathConflictDialog(window, "", window.theme.t,
                                     is_admin=False)
        try:
            blocked._render(_report(elevated=False))
            # isHidden(), not isVisible(): a child of a dialog that
            # has not been shown is never "visible" whatever its own
            # state, so isVisible() here would be False for both
            # halves of this test and prove nothing. isHidden()
            # reports the explicit show/hide the dialog performed.
            assert not blocked._elevate_btn.isHidden()
        finally:
            blocked.deleteLater()
            qapp.processEvents()

        # Same session, a report where nothing needs rights.
        easy = _report(elevated=False)
        for option in easy["conflicts"][0]["options"]:
            if option["short"] == "Needs administrator":
                option["short"] = "Nothing to reorder"
                option["action"] = "blocked"
        quiet = PathConflictDialog(window, "", window.theme.t, is_admin=False)
        try:
            quiet._render(easy)
            assert quiet._elevate_btn.isHidden()
        finally:
            quiet.deleteLater()
            qapp.processEvents()

    def test_the_shield_goes_through_the_one_relaunch_path(
            self, window, qapp):
        """The dialog asks; main.py elevates. Re-implementing
        ShellExecute("runas") behind a card would be a second UAC path to
        keep correct."""
        seen = []
        dialog = PathConflictDialog(window, "", window.theme.t,
                                    is_admin=False)
        dialog.elevate_requested.connect(lambda: seen.append(True))
        try:
            dialog._render(_report(elevated=False))
            dialog._elevate_btn.click()
            qapp.processEvents()
            assert seen == [True]
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_backends_own_elevation_reading_wins(self, window, qapp):
        """`is_admin` is what the GUI believes about itself; `elevated` is
        what the process that would perform the write measured about the
        token it actually holds. Where they disagree the child is right,
        and trusting the parent means offering a button whose task comes
        back refused."""
        dialog = PathConflictDialog(window, "", window.theme.t,
                                    is_admin=True)
        try:
            dialog._render(_report(elevated=False))
            promote = next(b for b in _buttons(dialog)
                           if b.text() == "Use this one")
            assert not promote.isEnabled()
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_an_unelevated_session_still_sees_the_findings(
            self, window, qapp):
        """A user who cannot fix it can still find out what is wrong."""
        dialog = PathConflictDialog(window, "", window.theme.t,
                                    is_admin=False)
        try:
            dialog._render(_report())
            assert len(_buttons(dialog)) == 3, "the findings were hidden"
            assert "3.13.1" in _labels(dialog)
            promote = next(b for b in _buttons(dialog)
                           if b.text() == "Use this one")
            assert not promote.isEnabled()
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_a_clean_path_says_so_rather_than_showing_an_empty_panel(
            self, window, qapp):
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render({"conflicts": [], "entries": 31, "elevated": True})
            text = _labels(dialog)
            assert "Nothing is shadowed" in text
            assert "31" in text
            assert not _buttons(dialog)
            assert dialog._elevate_btn.isHidden()
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_status_line_says_nothing_is_removed(self, window, qapp):
        """The single most important sentence on this surface, and the
        reason the card needs no confirmation."""
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            assert "nothing is removed" in dialog._status.text().lower()
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_a_promotion_sends_the_FAMILY_key_and_the_root(
            self, window, qapp, monkeypatch):
        """The family key, not a command name: `python` covers pip and
        pip3, and the backend re-derives the whole installation from the
        root so a stale scan cannot ask for a directory set that no
        longer describes the machine."""
        sent = {}

        class _Signal:
            def connect(self, *_a, **_k):
                pass

        class _Fake:
            #: The three real signals, declared rather than served by
            #: __getattr__: `run` has to stay a genuine callable, because
            #: QThread.started.connect refuses anything that is not one
            #: and the failure surfaces as a paintEvent error three frames
            #: away from the cause.
            finished = _Signal()
            failed = _Signal()
            cancelled = _Signal()

            def __init__(self, ps1, task, **kwargs):
                sent["task"] = task
                sent.update(kwargs)

            def moveToThread(self, _thread):
                pass

            def run(self):
                pass

            def deleteLater(self):
                #: InspectorDialog._cleanup calls this on thread.finished.
                pass

        import frontend.widgets as W
        monkeypatch.setattr(W, "PowerShellTask", _Fake)

        dialog = PathConflictDialog(window, "engine.ps1", window.theme.t)
        try:
            dialog._render(_report())
            promote = next(b for b in _buttons(dialog)
                           if b.text() == "Use this one")
            promote.click()
            qapp.processEvents()
            assert sent.get("task") == "PathPrioritize"
            assert sent.get("path_command") == "python"
            assert sent.get("path_directory") == r"C:\Python313"
        finally:
            # THE THREAD IS REAL even though the worker is not, and a
            # QThread destroyed while running is a qFatal abort rather
            # than a test failure — the crash lands after the run has
            # already reported green, which is the worst place for it.
            thread = dialog._thread
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            qapp.processEvents()
            dialog.deleteLater()
            qapp.processEvents()


class TestTheOptionLabels:
    """One short, distinct identity per installation."""

    def test_the_version_labels_them_when_it_tells_them_apart(self):
        """Two JDKs differ in the fact the user is choosing between, and
        "21.0.12.1" against "26.0.2.0" answers the question without
        anybody parsing a path."""
        both = [{"path": r"C:\Program Files\Eclipse Adoptium\jdk-21\bin",
                 "version": "21.0.12.1"},
                {"path": r"C:\Program Files\Common Files\Oracle\Java\javapath",
                 "version": "26.0.2.0"}]
        assert PathConflictDialog._option_labels(both) == ["21.0.12.1",
                                                           "26.0.2.0"]

    def test_a_missing_version_drops_the_whole_card_back_to_paths(self):
        """A card never mixes two kinds of label — one version chip beside
        two path chips reads as three unrelated things."""
        options = [{"path": r"C:\Python314", "version": "3.14.7"},
                   {"path": r"C:\Users\me\AppData\Local\Microsoft\WindowsApps",
                    "version": ""}]
        labels = PathConflictDialog._option_labels(options)
        assert "3.14.7" not in labels
        assert len(set(labels)) == 2

    def test_a_bare_container_name_is_qualified_even_when_unique(self):
        """UNIQUE IS NOT THE SAME AS INFORMATIVE, and this was visible on
        a real machine: a `pip --user` install under
        Roaming\\Python\\Python314\\Scripts was the only option ending in
        "Scripts", so the shortest unique label was "…\\Scripts" — which
        tells the reader nothing about WHICH Python it belongs to."""
        options = [
            {"path": r"C:\Python314", "version": ""},
            {"path": r"C:\Users\me\AppData\Local\Microsoft\WindowsApps",
             "version": ""},
            {"path": r"C:\Users\me\AppData\Roaming\Python\Python314\Scripts",
             "version": ""},
        ]
        labels = PathConflictDialog._option_labels(options)
        assert len(set(labels)) == 3
        scripts = [label for label in labels if "Scripts" in label][0]
        assert scripts.endswith(r"Python314\Scripts"), (
            f"a bare container name was left unqualified: {scripts}")

    def test_identical_leaf_folders_are_disambiguated(self):
        """MEASURED ON A REAL MACHINE. Three Python installations put pip
        in three directories all called "Scripts", so the leaf folder
        alone drew three indistinguishable labels."""
        options = [
            {"path": r"C:\Python314\Scripts", "version": ""},
            {"path": r"C:\Users\me\AppData\Local\Programs\Python\Python312\Scripts",
             "version": ""},
            {"path": r"C:\Users\me\AppData\Roaming\Python\Python314\Scripts",
             "version": ""},
        ]
        labels = PathConflictDialog._option_labels(options)
        assert len(set(labels)) == 3, f"identical labels: {labels}"
        assert all("Scripts" in label for label in labels)
