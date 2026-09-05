"""
Preview: the engine can simulate a task, and the CONFIRMATION is not where
that is offered.

THE CAPABILITY IS REAL AND STAYS REACHABLE.
core.ps1 has been fully -WhatIf aware since v6: $Script:DryRun gates every
mutation primitive, Invoke-GuiTask reports a simulated pass as
"##PULSE##SUCCESS|[DRY-RUN] ... (simulated - no changes were made)", and
Invoke-Mutation logs a "[WHATIF] ..." line for each write it did not make.
Terminal mode exposes it (`core.ps1 -WhatIf`), playbooks expose it (the run
dialog's Preview/Run pair), and PowerShellTask appends -WhatIf whenever its
`dry_run` flag is set. _start_task still takes and threads that flag.

WHAT WAS REMOVED, AND WHY IT WAS THE WRONG SURFACE
    ConfirmDialog carried a third button, "Preview", styled as a peer of
    Cancel and Proceed and accepting like Proceed, with a `preview`
    attribute the caller read to decide which kind of run to start.

    A confirmation appears at the moment the user has already decided and
    is being asked to say so. A third control there does not inform that
    decision - it reopens it, and it does so as one of three same-sized
    buttons, two of which accept. The most common instance in the app made
    it plainest: the Update Center's "Some of these apps are running"
    offered to SIMULATE a winget upgrade the user had already queued and
    ticked, which is an answer to a question nobody asked.

    A playbook is the opposite case and keeps its Preview: its whole
    subject is an ordered sequence you would reasonably want to rehearse
    before running, and PlaybookDialog offers it as the safe half of a
    pair rather than as a third wheel on a yes/no.

WHAT THIS FILE PINS NOW
    That the confirmation is a clean binary; that no accepting path can
    silently start a simulation; that the engine plumbing behind the flag
    is intact and still refuses to bank a simulated run as a real
    measurement; and that every dispatch route through request_task still
    reaches _start_task, which is the regression that got past this file
    the last time the flag moved.
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


class TestTheConfirmationIsBinary:
    def test_a_destructive_task_offers_two_answers(self, window, qapp):
        """Cancel and Proceed, in that order - dialog_footer right-aligns
        with the primary last, so the commitment is the final step."""
        dialog = ConfirmDialog(window, DESTRUCTIVE, window.theme.t)
        try:
            labels = [b.text() for b in dialog.findChildren(QPushButton)]
            assert labels == ["Cancel", "Proceed"], labels
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_a_merely_confirmed_task_offers_two_as_well(self, window, qapp):
        """The gate for the third button was `confirm`, a superset of
        `danger`, so this is where most of them appeared."""
        dialog = ConfirmDialog(window, CONFIRMED, window.theme.t)
        try:
            labels = [b.text() for b in dialog.findChildren(QPushButton)]
            assert labels == ["Cancel", "Proceed"], labels
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_running_apps_prompt_is_binary_too(self, window, qapp):
        """THE INSTANCE THE REMOVAL WAS FOR, built the way the Update
        Center builds it: a ConfirmDialog over apps that must be closed
        before they can be replaced. 'Preview' there offered to simulate
        an upgrade the user had already queued and ticked."""
        item = {
            "icon": "\u26a0\ufe0f",
            "title": "Some of these apps are running",
            "desc": ("Visual Studio Code is open right now. Windows cannot "
                     "replace files that are in use, so this app will be "
                     "closed before the update is applied."),
        }
        dialog = ConfirmDialog(window, item, window.theme.t)
        try:
            labels = [b.text() for b in dialog.findChildren(QPushButton)]
            assert labels == ["Cancel", "Proceed"], labels
        finally:
            dialog.deleteLater()
            qapp.processEvents()


class TestNoAcceptingPathSimulates:
    def test_the_dialog_reports_no_preview_outcome(self, window, qapp):
        """`preview` was the attribute request_task read on the line after
        exec() returned. An attribute that lingers at False is an entry
        point waiting to be re-armed by a caller that finds it."""
        dialog = ConfirmDialog(window, DESTRUCTIVE, window.theme.t)
        try:
            assert not hasattr(dialog, "preview"), (
                "the preview outcome survives on the dialog")
            assert not hasattr(dialog, "_choose_preview")
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_proceed_accepts(self, window, qapp):
        dialog = ConfirmDialog(window, DESTRUCTIVE, window.theme.t)
        try:
            _buttons(dialog)["Proceed"].click()
            assert dialog.result() == QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_cancel_rejects(self, window, qapp):
        dialog = ConfirmDialog(window, DESTRUCTIVE, window.theme.t)
        try:
            _buttons(dialog)["Cancel"].click()
            assert dialog.result() == QDialog.DialogCode.Rejected
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_an_accepted_confirmation_starts_a_real_run(self, window,
                                                        monkeypatch):
        """END TO END, and the half a dialog-only assertion cannot reach:
        the dispatch that used to read `dialog.preview` must now start a
        real run whatever the user pressed."""
        started = {}
        monkeypatch.setattr(
            window, "_start_task",
            lambda *a, **k: started.update({"args": a, "kwargs": k}))
        monkeypatch.setattr(
            window, "_exec_dialog", lambda d: QDialog.DialogCode.Accepted)
        monkeypatch.setattr(window, "is_admin", True)
        window.request_task(dict(DESTRUCTIVE), None)
        assert started, "an accepted confirmation started nothing"
        assert started["kwargs"].get("dry_run", False) is False, (
            "the dispatch still asks for a simulated run")


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
        `dry_run` before it was passed. request_task no longer passes the
        argument at all - _start_task's own default is what makes the run
        real - so what is checked is that it did not ask for a simulation,
        by argument or by default."""
        started = self._dispatch(window, monkeypatch, PLAIN)
        assert started, "a plain task never reached _start_task"
        assert started["kwargs"].get("dry_run", False) is False

    def test_a_confirmed_task_dispatches_when_accepted(self, window,
                                                       monkeypatch):
        started = self._dispatch(window, monkeypatch, CONFIRMED,
                                 QDialog.DialogCode.Accepted)
        assert started, "an accepted confirm never reached _start_task"

    def test_a_declined_task_starts_nothing(self, window, monkeypatch):
        started = self._dispatch(window, monkeypatch, CONFIRMED,
                                 QDialog.DialogCode.Rejected)
        assert not started, "Cancel still started the task"
