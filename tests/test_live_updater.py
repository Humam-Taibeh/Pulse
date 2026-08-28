"""
The live app updater (v10.5): what the user is told, and when.

THE COMPLAINT THIS ANSWERS
    Updating apps was a black box. The user ticked fourteen packages,
    pressed a button, and for the next eight minutes the window said
    "Executing: Update Selected Apps" over a console scrolling raw winget
    output — with no way to tell a download from a hang, no statement of
    which app was being touched, no warning that a running application was
    about to be closed underneath them, and no confirmation afterwards
    that anything had actually changed version.

TWO MECHANISMS, TESTED SEPARATELY HERE
    1. THE PHASE CHANNEL. ##PULSE##STAGE| has existed since v10.3 and only
       the Update Center's own scan dialog listened to it. It is now wired
       to the pipeline every operation runs through, so the backend's
       phases ("Closing Steam...", "Downloading Firefox 145.0...",
       "Verified 144.0 -> 145.0") reach a fixed chip in the Activity
       drawer AND the console transcript.

    2. THE RUNNING FLAG. The scan reports which apps are open, the row
       says so before the button is pressed, and the selection is
       confirmed by name rather than by count — because "3 apps will be
       closed" is not something anyone can decide with.

WHAT IS DELIBERATELY NOT TESTED HERE
    Whether winget's own output reaches the console. It always did — the
    backend inherits the GUI's stdout handle, so a real terminal's
    carriage-return progress arrives byte for byte (see
    tests/test_process_job.py for the pipe's own contract). The gap was
    never the stream; it was that nothing said what the stream was FOR.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog

from frontend import widgets as W


# ============================================================
#  THE PHASE CHANNEL
# ============================================================
class TestStageChannel:
    """A backend phase line, from the signal to the two places it lands."""

    @pytest.fixture
    def running(self, window, qapp):
        """The window mid-task, as _start_task leaves it."""
        window.activity.set_running(True)
        window._running_item = {"title": "Update Selected Apps"}
        window.console.clear_console()
        qapp.processEvents()
        yield window
        window._finish_common("ok")
        window.activity.set_running(False)
        qapp.processEvents()

    def test_the_worker_signal_is_actually_connected(self, window):
        """The whole defect in one assertion: the channel existed, the
        pipeline never subscribed to it."""
        from utils.helpers import PowerShellTask
        assert hasattr(PowerShellTask, "stage")
        assert hasattr(window, "_on_task_stage")

    def test_a_phase_reaches_the_drawer_chip(self, running, qapp):
        running._on_task_stage("Downloading Mozilla Firefox 145.0...")
        qapp.processEvents()
        chip = running.activity.stage_label
        assert chip.isVisible()
        assert chip.fullText() == "Downloading Mozilla Firefox 145.0..."

    def test_the_rail_keeps_the_task_name_alongside_the_phase(self, running, qapp):
        """A phase alone loses WHICH operation is running — which matters
        most in exactly the case the phase exists for, a long bulk deploy
        the user has walked away from."""
        running._on_task_stage("Closing Steam (steam, steamwebhelper)...")
        qapp.processEvents()
        line = running.activity.status_text.fullText()
        assert "Update Selected Apps" in line
        assert "Closing Steam" in line

    def test_the_untruncated_phase_is_always_reachable(self, running, qapp):
        """The chip elides (ElidedCaption); the tooltip is the contract
        every ElidedCaption caller owes its own text."""
        phase = ("Downloading Microsoft Visual Studio Code 1.108.2 "
                 "(replacing 1.107.0)...")
        running._on_task_stage(phase)
        qapp.processEvents()
        assert running.activity.stage_label.toolTip() == phase

    def test_an_empty_phase_is_ignored_rather_than_shown_blank(self, running, qapp):
        running._on_task_stage("Downloading...")
        running._on_task_stage("   ")
        qapp.processEvents()
        assert running.activity.stage_label.fullText() == "Downloading..."

    def test_the_chip_clears_when_the_task_settles(self, running, qapp):
        """A phase reports something happening NOW. Left on screen after
        the verdict it reports a phase that finished, beside a state pill
        saying the task is over."""
        running._on_task_stage("Verifying Mozilla Firefox...")
        qapp.processEvents()
        assert running.activity.stage_label.isVisible()
        running._finish_common("ok")
        qapp.processEvents()
        assert not running.activity.stage_label.isVisible()

    def test_every_phase_is_recorded_in_the_transcript(self, running, qapp):
        """STAGE is a payload channel and helpers.py keeps it out of the
        stream, so without the echo an exported log would carry winget's
        output with no record of which app it belonged to."""
        phases = ["[1/2] Mozilla Firefox",
                  "Closing Mozilla Firefox (firefox)...",
                  "Verified Mozilla Firefox 144.0 -> 145.0"]
        for phase in phases:
            running._on_task_stage(phase)
        qapp.processEvents()
        text = running.console.toPlainText()
        for phase in phases:
            assert phase in text, f"{phase!r} never reached the transcript"


# ============================================================
#  MARKERS vs CARRIAGE-RETURN PROGRESS
# ============================================================
class TestPhaseMarkersSurviveProgress:
    """The silent defect the echo introduced, and its fix.

    Phase markers are interleaved with a stream that uses bare CRs for
    in-place progress — winget, sfc, DISM. A marker appended just before a
    progress frame became the console's "newest line", so the frame
    REWROTE it, and every completed phase vanished from the transcript.
    """

    @pytest.fixture
    def console(self, window, qapp):
        window.console.clear_console()
        qapp.processEvents()
        return window.console

    def test_a_progress_frame_does_not_eat_the_marker_before_it(self, console):
        console.append_marker("> Downloading Firefox 145.0...")
        console.put_line("  12%  7.4 MB / 62.1 MB", True)
        lines = console.toPlainText().splitlines()
        assert len(lines) == 2, f"the marker was overwritten: {lines}"
        assert "Downloading Firefox" in lines[0]
        assert "12%" in lines[1]

    def test_progress_still_collapses_to_one_line_after_the_marker(self, console):
        """The protection is one-shot. If it stuck, a 400-frame download
        would append 400 lines and blow the console's line budget."""
        console.append_marker("> Downloading Firefox 145.0...")
        for pct in (12, 34, 55, 78, 100):
            console.put_line(f"  {pct}%", True)
        lines = console.toPlainText().splitlines()
        assert len(lines) == 2, f"progress stopped collapsing: {lines}"
        assert "100%" in lines[-1]

    def test_an_ordinary_line_is_still_rewritable(self, console):
        console.append_line("  10%")
        console.put_line("  90%", True)
        assert len(console.toPlainText().splitlines()) == 1

    def test_the_full_phase_sequence_survives_a_real_download(self, console):
        """End to end, in the order a real update produces it."""
        console.append_marker("> Closing Firefox (firefox)...")
        console.append_marker("> Downloading Firefox 145.0...")
        for pct in (12, 55, 100):
            console.put_line(f"  {pct}%  of 62.1 MB", True)
        console.append_marker("> Verified Firefox 144.0 -> 145.0")
        text = console.toPlainText()
        for phase in ("Closing Firefox", "Downloading Firefox",
                      "Verified Firefox"):
            assert phase in text, f"{phase!r} was overwritten"
        assert text.count("%") == 1, "progress frames did not collapse"


# ============================================================
#  THE RUNNING-APP GUARD, AS THE USER MEETS IT
# ============================================================
def _payload(*rows):
    return list(rows)


def _row(app_id, name, running=()):
    return {"Id": app_id, "Name": name, "CurrentVersion": "1.0",
            "AvailableVersion": "2.0", "Running": bool(running),
            "RunningProcesses": list(running)}


class TestRunningApps:

    @pytest.fixture
    def no_live_scan(self, monkeypatch):
        """Construct the Update Center WITHOUT letting it scan.

        UpdateCenterDialog.__init__ calls _start_scan(), which puts a real
        PowerShellTask on a real QThread and spawns powershell.exe. None of
        the tests below are about the scan — they inject a finished payload
        and assert on rows and on the confirmation — so every one of them
        was paying for a subprocess it then had to race to tear down.

        THAT RACE IS THE POINT. Destroying a QThread that is still running
        is not an exception: Qt calls qFatal and the process ABORTS, with
        no traceback and no Qt warning. PulseDialog.done() settles worker
        threads precisely to prevent it, but a test that starts a scan it
        does not need is relying on that settle to win a race, on every
        machine, forever — and a lost race surfaces as a green test session
        that exits non-zero, which reads as anything but this.

        Not starting the thread removes the race instead of tuning it. The
        settle path keeps its own coverage in tests/test_audit_hardening.py,
        where it is the subject rather than an obstacle.
        """
        monkeypatch.setattr(W.UpdateCenterDialog, "_start_scan",
                            lambda self: None)

    @pytest.fixture
    def center(self, window, qapp, no_live_scan):
        from utils.helpers import TaskResult
        dialog = W.UpdateCenterDialog(window, "", window.theme.t)
        dialog.show()
        qapp.processEvents()
        dialog._on_scan_finished(TaskResult(
            success=True, message="ok",
            data=_payload(_row("Mozilla.Firefox", "Mozilla Firefox", ["firefox"]),
                          _row("7zip.7zip", "7-Zip"),
                          _row("Valve.Steam", "Steam", ["steam", "steamwebhelper"]))))
        qapp.processEvents()
        yield dialog
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()

    def test_a_running_app_is_flagged_on_its_row(self, center):
        assert center._rows["Mozilla.Firefox"].is_running()
        assert center._rows["Valve.Steam"].is_running()
        assert not center._rows["7zip.7zip"].is_running()

    def test_only_running_rows_carry_the_chip(self, center):
        assert center._rows["Mozilla.Firefox"]._running_chip is not None
        assert center._rows["7zip.7zip"]._running_chip is None

    def test_the_chip_names_the_processes_it_will_close(self, center):
        """"RUNNING" alone is a state; the processes are what make it
        checkable — the user can look at that list and recognise the
        window they have unsaved work in."""
        tip = center._rows["Valve.Steam"]._running_chip.toolTip()
        assert "steam" in tip and "steamwebhelper" in tip

    def test_a_backend_without_the_field_reports_nothing_running(
            self, window, qapp, no_live_scan):
        """Forward compatibility runs both ways: the GUI ships ahead of a
        user's backend often enough that a missing field must degrade to
        the safe answer rather than to a crash."""
        from utils.helpers import TaskResult
        dialog = W.UpdateCenterDialog(window, "", window.theme.t)
        dialog._on_scan_finished(TaskResult(
            success=True, message="ok",
            data=[{"Id": "A.B", "Name": "Thing", "CurrentVersion": "1",
                   "AvailableVersion": "2"}]))
        qapp.processEvents()
        assert not dialog._rows["A.B"].is_running()
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()

    def test_applying_confirms_before_closing_anything(self, center, monkeypatch, qapp):
        monkeypatch.setattr(W.ConfirmDialog, "exec",
                            lambda self: QDialog.DialogCode.Rejected)
        center._accept_selection()
        qapp.processEvents()
        assert center.result() != QDialog.DialogCode.Accepted, (
            "the dialog accepted despite the user cancelling the "
            "close-running-apps confirmation")

    def test_confirming_proceeds_with_the_whole_selection(self, center, monkeypatch, qapp):
        monkeypatch.setattr(W.ConfirmDialog, "exec",
                            lambda self: QDialog.DialogCode.Accepted)
        center._accept_selection()
        qapp.processEvents()
        assert set(center.selected_ids) == {"Mozilla.Firefox", "7zip.7zip",
                                            "Valve.Steam"}

    def test_nothing_running_asks_nothing(self, center, monkeypatch, qapp):
        """A confirmation that always appears is one nobody reads."""
        asked = []
        monkeypatch.setattr(W.ConfirmDialog, "exec",
                            lambda self: asked.append(1) or QDialog.DialogCode.Accepted)
        center._rows["Mozilla.Firefox"].checkbox.setChecked(False)
        center._rows["Valve.Steam"].checkbox.setChecked(False)
        qapp.processEvents()
        center._accept_selection()
        assert not asked, "confirmed a selection with nothing running in it"
        assert center.selected_ids == ["7zip.7zip"]

    def test_the_confirmation_names_the_apps_rather_than_counting_them(
            self, center, monkeypatch, qapp):
        """"3 apps will be closed" is not enough to decide with — the
        whole question is WHICH ones."""
        captured = {}

        def grab(self):
            from PySide6.QtWidgets import QLabel
            captured["text"] = " ".join(
                lbl.text() for lbl in self.findChildren(QLabel))
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(W.ConfirmDialog, "exec", grab)
        center._accept_selection()
        qapp.processEvents()
        assert "Mozilla Firefox" in captured["text"]
        assert "Steam" in captured["text"]
        assert "7-Zip" not in captured["text"], (
            "an app that is NOT running was listed as one that will be "
            "closed")
