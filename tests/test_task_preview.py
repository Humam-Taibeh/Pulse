"""
Preview: showing what a destructive task WOULD do, before it does it.

THE CAPABILITY ALREADY EXISTED AND WAS NOT REACHABLE.
core.ps1 has been fully -WhatIf aware since v6: $Script:DryRun gates every
mutation primitive, Invoke-GuiTask reports a simulated pass as
"##PULSE##SUCCESS|[DRY-RUN] ... (simulated - no changes were made)", and
Invoke-Mutation logs a "[WHATIF] ..." line for each write it did not make.
Terminal mode exposes it (`core.ps1 -WhatIf`) and playbooks expose it (the
run dialog's Preview mode). PowerShellTask has taken a `dry_run` flag the
whole time and appends -WhatIf when it is set.

The GUI's individual tasks were the one caller that never passed it.
_start_playbook threaded dry_run through; _start_task did not, so the
operations with the least reversible consequences - Remove Edge, Purge
OneDrive, Remove Windows.old - offered a confirmation that could describe
INTENT and never EFFECT.

WHERE THE ACTION LIVES, AND WHY NOT ON THE CARD
    In the ConfirmDialog, which is already the decision point and already
    exists for exactly this set of tasks. A second button on the card face
    would put a visual exception into a grid whose uniformity GlassCard
    works hard to hold, and would need its own layout-contract carve-out;
    the dialog needs neither and is where the question is actually being
    asked.

WHICH TASKS OFFER IT
    Those carrying `confirm: True` - the app's existing "this warrants a
    decision" marker, which is a superset of `danger: True`. No new
    taxonomy to keep in step: if Pulse already stops to ask, showing what
    the answer commits to is exactly the help that is missing.

WHAT A PREVIEW MUST NOT DO
    Bank history. _finish_common records the run's wall-clock into the
    per-task duration average, and a simulated pass is not a measurement
    of the real thing - it is faster by exactly the work it skipped. The
    same reasoning the cancelled-run path already documents.
"""
from __future__ import annotations

import pytest

from PySide6.QtWidgets import QDialog, QPushButton

from frontend.widgets import ConfirmDialog
from utils.helpers import PowerShellTask


def _buttons(dialog) -> dict:
    return {b.text(): b for b in dialog.findChildren(QPushButton)}


DESTRUCTIVE = {"icon": "🌐", "title": "Remove Microsoft Edge",
               "desc": "Removes Edge and backs up its data first.",
               "task": "RemoveEdge", "confirm": True, "danger": True}
CONFIRMED = {"icon": "📡", "title": "Network & Ping Optimizer",
             "desc": "Applies network tuning.",
             "task": "NetworkOptimization", "confirm": True}
PLAIN = {"icon": "⚡", "title": "Ultimate Power Plan",
         "desc": "Switches the active power scheme.",
         "task": "UltimatePowerPlan"}


class TestTheDialogOffersIt:
    def test_a_destructive_task_offers_preview(self, window, qapp):
        dialog = ConfirmDialog(window, DESTRUCTIVE, window.theme.t)
        try:
            assert "Preview" in _buttons(dialog), (
                "the least reversible task in the app still asks for "
                "confirmation without offering to show what it would do")
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_every_confirmed_task_offers_it(self, window, qapp):
        """The gate is `confirm`, not `danger`: if Pulse already stops to
        ask, the preview is what informs the answer."""
        dialog = ConfirmDialog(window, CONFIRMED, window.theme.t)
        try:
            assert "Preview" in _buttons(dialog)
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_three_buttons_read_in_order(self, window, qapp):
        """Cancel, Preview, Proceed - dialog_footer right-aligns with the
        primary last, so the destructive commitment stays the final step
        rather than sitting between two safe ones."""
        dialog = ConfirmDialog(window, DESTRUCTIVE, window.theme.t)
        try:
            labels = [b.text() for b in dialog.findChildren(QPushButton)]
            assert labels == ["Cancel", "Preview", "Proceed"], labels
        finally:
            dialog.deleteLater()
            qapp.processEvents()


class TestTheDialogReportsWhichWasChosen:
    def test_preview_accepts_and_flags_itself(self, window, qapp):
        dialog = ConfirmDialog(window, DESTRUCTIVE, window.theme.t)
        try:
            assert dialog.preview is False, "preview is set before it is asked for"
            _buttons(dialog)["Preview"].click()
            assert dialog.preview is True
            assert dialog.result() == QDialog.DialogCode.Accepted, (
                "Preview must accept — the caller starts a run either way, "
                "and only `preview` decides which kind")
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_proceed_is_not_a_preview(self, window, qapp):
        dialog = ConfirmDialog(window, DESTRUCTIVE, window.theme.t)
        try:
            _buttons(dialog)["Proceed"].click()
            assert dialog.preview is False, (
                "Proceed flagged itself as a preview — the real run would "
                "silently simulate and change nothing")
            assert dialog.result() == QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_cancel_is_neither(self, window, qapp):
        dialog = ConfirmDialog(window, DESTRUCTIVE, window.theme.t)
        try:
            _buttons(dialog)["Cancel"].click()
            assert dialog.preview is False
            assert dialog.result() == QDialog.DialogCode.Rejected
        finally:
            dialog.deleteLater()
            qapp.processEvents()


class TestTheFlagReachesTheEngine:
    def test_dry_run_puts_whatif_on_the_command_line(self):
        """The end of the chain. -WhatIf is what sets $Script:DryRun, which
        is what every mutation primitive in the engine consults."""
        task = PowerShellTask("core.ps1", "RemoveEdge", dry_run=True)
        assert "-WhatIf" in task._build_argv()

    def test_a_real_run_carries_no_whatif(self):
        task = PowerShellTask("core.ps1", "RemoveEdge", dry_run=False)
        assert "-WhatIf" not in task._build_argv()

    def test_start_task_threads_the_flag_through(self, window, monkeypatch,
                                                 qapp):
        """_start_task is where this was missing; _start_playbook has
        always done it."""
        seen = {}
        real = PowerShellTask

        def _spy(*args, **kwargs):
            seen.update(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr("frontend.main.PowerShellTask", _spy)
        monkeypatch.setattr(window, "_locate_ps1", lambda: window.ps1_path)

        window._start_task(dict(DESTRUCTIVE), None, dry_run=True)
        try:
            assert seen.get("dry_run") is True, (
                "_start_task dropped the preview flag, so Preview would run "
                "the real thing")
        finally:
            if window._worker is not None:
                window._worker.cancel()
            if window._thread is not None:
                window._thread.quit()
                window._thread.wait(5000)
            window._finish_common()
            qapp.processEvents()

    def test_a_normal_start_is_not_a_preview(self, window, monkeypatch, qapp):
        seen = {}
        real = PowerShellTask

        def _spy(*args, **kwargs):
            seen.update(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr("frontend.main.PowerShellTask", _spy)
        window._start_task(dict(DESTRUCTIVE), None)
        try:
            assert seen.get("dry_run") is False
        finally:
            if window._worker is not None:
                window._worker.cancel()
            if window._thread is not None:
                window._thread.quit()
                window._thread.wait(5000)
            window._finish_common()
            qapp.processEvents()


class TestAPreviewIsNotAMeasurement:
    def test_it_is_kept_out_of_the_duration_history(self, window, monkeypatch):
        """A simulated pass is faster than the real one by exactly the work
        it skipped. Averaging it in makes every "typically ~2m" estimate
        lie, and the average is persisted — the same reasoning the
        cancelled-run path already carries."""
        recorded = []
        monkeypatch.setattr("frontend.main.prefs.record_task_run",
                            lambda *a, **k: recorded.append(a))

        window._running_item = dict(DESTRUCTIVE)
        window._run_started_at = 1000.0
        window._running_dry_run = True
        window._finish_common("ok")

        assert not recorded, (
            "a preview was folded into the task's duration history")

    def test_a_real_run_is_still_recorded(self, window, monkeypatch):
        """The guard must not have been bought by disabling history."""
        recorded = []
        monkeypatch.setattr("frontend.main.prefs.record_task_run",
                            lambda *a, **k: recorded.append(a))

        window._running_item = dict(DESTRUCTIVE)
        window._run_started_at = 1000.0
        window._running_dry_run = False
        window._finish_common("ok")

        assert recorded, "a real run stopped being recorded"


class TestTheOutputReadsAsASimulation:
    def test_whatif_lines_are_tinted_amber(self, qapp):
        """The engine writes "   [WHATIF] Would ..." for each write it did
        not make. The console's severity pass already gives DRY-RUN/WHATIF
        the warn tone ahead of SUCCESS, so a simulated verdict cannot read
        as a real one — asserted here end to end for the preview path."""
        from PySide6.QtGui import QColor

        from frontend import theme as TH
        from frontend.widgets import LiveConsole

        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("   [WHATIF] Would remove Microsoft Edge.")
        console.append_line(
            "SUCCESS|[DRY-RUN] Edge removal simulated "
            "(simulated - no changes were made)")

        from PySide6.QtGui import QTextCursor

        def line_color(index):
            block = console.document().findBlockByNumber(index)
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                QTextCursor.MoveMode.KeepAnchor)
            return cursor.charFormat().foreground().color()

        assert line_color(0).name() == QColor(t["warn"]).name()
        assert line_color(1).name() == QColor(t["warn"]).name(), (
            "a simulated verdict is tinted like a real success")


class TestEveryDispatchPathStillWorks:
    """The bug this class exists for got past the tests above.

    Threading the flag added `dry_run=dry_run` to the _start_task call in
    request_task, but bound `dry_run` only inside the `confirm` branch —
    so every OTHER route through that method (a plain task, a bulk deploy,
    the Office wizard) raised NameError before starting anything. Nothing
    caught it, because the tests above call _start_task directly and the
    dispatch method in between was never exercised.
    """

    def _dispatch(self, window, monkeypatch, item, answer=None):
        """Drive request_task with nothing modal and nothing spawned.

        _exec_dialog is stubbed for EVERY case, not just the confirm one:
        an admin-gated task on an unelevated Pulse opens an elevation
        prompt through the same funnel, and a test that left that live
        would exec() a modal with no one to close it.
        """
        started = {}
        monkeypatch.setattr(
            window, "_start_task",
            lambda *a, **k: started.update({"args": a, "kwargs": k}))
        monkeypatch.setattr(
            window, "_exec_dialog",
            lambda d: answer if answer is not None
            else QDialog.DialogCode.Accepted)
        # Elevation is a separate decision from this one; force the
        # "already elevated" path so the dispatch under test is reached.
        monkeypatch.setattr(window, "is_admin", True)
        window.request_task(dict(item), None)
        return started

    def test_an_unconfirmed_task_dispatches(self, window, monkeypatch):
        """The NameError path: no confirm branch runs, so nothing bound
        `dry_run` before it was passed."""
        started = self._dispatch(window, monkeypatch, PLAIN)
        assert started, "a plain task never reached _start_task"
        assert started["kwargs"].get("dry_run") is False

    def test_a_confirmed_task_dispatches_when_accepted(self, window,
                                                       monkeypatch):
        started = self._dispatch(window, monkeypatch, CONFIRMED,
                                 QDialog.DialogCode.Accepted)
        assert started, "an accepted confirm never reached _start_task"

    def test_a_declined_task_starts_nothing(self, window, monkeypatch):
        started = self._dispatch(window, monkeypatch, CONFIRMED,
                                 QDialog.DialogCode.Rejected)
        assert not started, "Cancel still started the task"
