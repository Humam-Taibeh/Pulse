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
    """One conflict with three copies: the machine-scope winner, a
    user-scope copy that CANNOT be promoted past it, and a second
    machine-scope copy that can."""
    report = {
        "entries": 24,
        "elevated": True,
        "conflicts": [{
            "command": "python",
            "winner": r"C:\Python311",
            "count": 3,
            "options": [
                {"path": r"C:\Python311", "scope": "Machine",
                 "version": "3.11.9", "winner": True,
                 "action": "none", "reason": "already runs this one"},
                {"path": r"C:\Python313", "scope": "Machine",
                 "version": "3.13.1", "winner": False,
                 "action": "reorder", "reason": "moves to the front"},
                {"path": r"C:\Users\me\AppData\Local\Programs\Python\Python312",
                 "scope": "User", "version": "3.12.4", "winner": False,
                 "action": "blocked",
                 "reason": "Windows always searches the system PATH first, "
                           "so no reordering of your user PATH can put this "
                           "copy in front."},
            ],
        }],
    }
    report.update(overrides)
    return report


def _buttons(dialog):
    from PySide6.QtWidgets import QPushButton

    footer = {"Close", "Re-scan"}
    return [b for b in dialog.findChildren(QPushButton)
            if b.text() not in footer]


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

    def test_it_renders_one_card_per_conflict(self, window, qapp):
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            labels = [b.text() for b in _buttons(dialog)]
            # Labelled by VERSION here: all three options carry one
            # and they are distinct, which is the fact the user is
            # choosing between. See _option_labels.
            assert labels == ["3.11.9", "3.13.1", "3.12.4"]
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
            winner = next(b for b in _buttons(dialog)
                          if b.text() == "3.11.9")
            assert not winner.isEnabled()
            assert "already runs" in winner.toolTip()
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_an_option_the_backend_refused_is_not_offered(
            self, window, qapp):
        """THE ASSERTION THIS FILE EXISTS FOR.

        Windows composes the search path as machine-then-user, so a
        user-scope folder can never overtake a machine-scope one. The
        backend marks that option `blocked`; a dialog that drew a live
        button anyway would let the user click it, see a toast, and still
        have the same problem — which is strictly worse than offering
        nothing, because now they believe it is fixed.
        """
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            blocked = next(b for b in _buttons(dialog)
                           if b.text() == "3.12.4")
            assert not blocked.isEnabled()
            assert "system PATH first" in blocked.toolTip()
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_reason_a_fix_is_impossible_is_printed(self, window, qapp):
        """A greyed-out button with no explanation is what makes an
        interface feel broken. The reason rides on the card, not only in
        a tooltip nobody hovers."""
        from PySide6.QtWidgets import QLabel

        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render(_report())
            text = " ".join(label.text()
                            for label in dialog.findChildren(QLabel))
            assert "system PATH first" in text
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_an_unelevated_session_still_sees_the_findings(
            self, window, qapp):
        """A user who cannot fix it can still find out what is wrong —
        the same shape the DNS switcher takes. Only the buttons that would
        WRITE are disabled."""
        dialog = PathConflictDialog(window, "", window.theme.t,
                                    is_admin=False)
        try:
            dialog._render(_report())
            labels = [b.text() for b in _buttons(dialog)]
            assert "3.13.1" in labels, "the findings were hidden entirely"
            promote = next(b for b in _buttons(dialog)
                           if b.text() == "3.13.1")
            assert not promote.isEnabled()
            assert "elevated" in promote.toolTip()
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
                           if b.text() == "3.13.1")
            assert not promote.isEnabled()
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_chips_for_one_command_are_never_identical(self, window, qapp):
        """MEASURED ON A REAL MACHINE, and it is why the leaf folder name
        is not the label. Three Python installations put `pip` in three
        directories all called "Scripts", so the card drew three
        indistinguishable buttons — the same defect the purge dialog's
        icons were fixed for, in a new place."""
        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render({
                "entries": 9, "elevated": True,
                "conflicts": [{
                    "command": "pip", "winner": r"C:\Python314\Scripts",
                    "count": 3,
                    "options": [
                        {"path": r"C:\Python314\Scripts", "scope": "Machine",
                         "version": "", "winner": True, "action": "none",
                         "reason": ""},
                        {"path": r"C:\Users\me\AppData\Local\Programs\Python\Python312\Scripts",
                         "scope": "User", "version": "", "winner": False,
                         "action": "reorder", "reason": ""},
                        {"path": r"C:\Users\me\AppData\Roaming\Python\Python314\Scripts",
                         "scope": "User", "version": "", "winner": False,
                         "action": "reorder", "reason": ""},
                    ],
                }],
            })
            labels = [b.text() for b in _buttons(dialog)]
            assert len(labels) == 3
            assert len(set(labels)) == 3, f"identical chips: {labels}"
            assert all("Scripts" in label for label in labels), (
                "the label stopped naming the directory at all")
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_version_labels_the_chips_when_it_tells_them_apart(self):
        """Two JDKs differ in the fact the user is choosing between, and
        "21.0.12.1" against "26.0.2.0" answers the question without
        anybody parsing a path. Used ONLY when every option has a version
        and they are all distinct, so a card never mixes two kinds of
        label."""
        both = [{"path": r"C:\Program Files\Eclipse Adoptium\jdk-21\bin",
                 "version": "21.0.12.1"},
                {"path": r"C:\Program Files\Common Files\Oracle\Java\javapath",
                 "version": "26.0.2.0"}]
        assert PathConflictDialog._option_labels(both) == ["21.0.12.1",
                                                           "26.0.2.0"]

        # One option with no version drops the whole card back to paths,
        # rather than rendering one version chip beside two path chips.
        mixed = [dict(both[0]), dict(both[1], version="")]
        labels = PathConflictDialog._option_labels(mixed)
        assert "21.0.12.1" not in labels
        assert len(set(labels)) == 2

    def test_a_clean_path_says_so_rather_than_showing_an_empty_panel(
            self, window, qapp):
        from PySide6.QtWidgets import QLabel

        dialog = PathConflictDialog(window, "", window.theme.t)
        try:
            dialog._render({"conflicts": [], "entries": 31, "elevated": True})
            text = " ".join(label.text()
                            for label in dialog.findChildren(QLabel))
            assert "Nothing is shadowed" in text
            assert "31" in text
            assert not _buttons(dialog)
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

    def test_a_promotion_sends_the_command_and_the_folder(
            self, window, qapp, monkeypatch):
        """The click has to reach the backend carrying BOTH halves — a
        directory with no command promotes nothing, and a command with no
        directory has nothing to promote."""
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
                           if b.text() == "3.13.1")
            promote.click()
            qapp.processEvents()
            assert sent.get("task") == "PathPrioritize"
            assert sent.get("path_command") == "python"
            assert sent.get("path_directory") == r"C:\Python313"
        finally:
            # THE THREAD IS REAL even though the worker is not, and a
            # QThread destroyed while running is a qFatal abort rather
            # than a test failure — the crash lands after the run has
            # already reported green, which is the worst place for it. So
            # it is settled here the way the app settles it, rather than
            # detached by nulling the attributes.
            thread = dialog._thread
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            qapp.processEvents()
            dialog.deleteLater()
            qapp.processEvents()
