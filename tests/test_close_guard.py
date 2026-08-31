"""
Confirm-on-close while a task is running (v10.2).

Closing mid-task used to cancel silently. For this app that is the wrong
default: the running operation may be halfway through an MSI install, a
driver export or an Edge purge, and "stopped halfway" is a materially
worse state than either finished or never started.

The interesting cases are the NEGATIVE ones — declining must leave the
window open AND the task untouched — because a half-honoured "no" is
worse than no prompt at all: the user would keep a window whose task had
already been killed.
"""
from __future__ import annotations

import pytest

from conftest import settle
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog

from frontend.widgets import CloseConfirmDialog


class _FakeThread:
    """Stands in for the QThread a live task owns. Constructing a real one
    would mean spawning real PowerShell for a UI-decision test.

    Implements the whole slice of QThread that
    main.PulseApp._settle_background_threads actually calls — isRunning,
    quit, wait — and a successful `wait` STOPS it, the way joining a real
    thread does. A double that stayed "running" forever would drive the
    settle path into its last-resort branch (disconnect + un-parent), which
    is not the behaviour these tests are about.
    """

    def __init__(self, running: bool):
        self._running = running
        self.waited = False
        self.quit_called = False

    def isRunning(self):        # noqa: N802 - Qt casing
        return self._running

    def quit(self):
        self.quit_called = True

    def wait(self, _ms=0):
        self.waited = True
        self._running = False   # joined
        return True


class _FakeWorker:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def armed(window, monkeypatch):
    """`window` with a fake running task installed, restored afterwards."""
    original = (window._thread, window._worker, window._running_item)
    thread, worker = _FakeThread(True), _FakeWorker()
    window._thread = thread
    window._worker = worker
    window._running_item = {"title": "Software Catalog", "task": "InstallCatalogApps"}
    yield window, thread, worker
    window._thread, window._worker, window._running_item = original


def _close(window) -> QCloseEvent:
    event = QCloseEvent()
    window.closeEvent(event)
    return event


class TestPromptAppears:
    def test_declining_keeps_the_window_open(self, armed, monkeypatch):
        window, thread, worker = armed
        monkeypatch.setattr(window, "_exec_dialog",
                            lambda _d: QDialog.DialogCode.Rejected)
        event = _close(window)
        assert not event.isAccepted(), "the window closed despite 'Keep Running'"

    def test_declining_does_not_touch_the_task(self, armed, monkeypatch):
        """The half-honoured 'no' — window stays, task dies anyway."""
        window, thread, worker = armed
        monkeypatch.setattr(window, "_exec_dialog",
                            lambda _d: QDialog.DialogCode.Rejected)
        _close(window)
        assert not worker.cancelled, (
            "the running task was cancelled even though the user chose to "
            "keep it running")
        assert not thread.waited

    def test_accepting_cancels_the_task(self, armed, monkeypatch):
        window, thread, worker = armed
        monkeypatch.setattr(window, "_exec_dialog",
                            lambda _d: QDialog.DialogCode.Accepted)
        _close(window)
        assert worker.cancelled, "'Stop & Close' did not stop the task"
        assert thread.waited, (
            "the window did not wait for the process-tree kill to land — "
            "children can outlive the GUI")

    def test_the_prompt_names_the_running_task(self, armed, monkeypatch):
        """A bare 'a task is running' is not actionable; the user needs to
        know WHICH one before deciding to kill it."""
        window, _thread, _worker = armed
        seen = {}

        def capture(dialog):
            seen["dialog"] = dialog
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(window, "_exec_dialog", capture)
        _close(window)

        from PySide6.QtWidgets import QLabel

        dialog = seen.get("dialog")
        assert isinstance(dialog, CloseConfirmDialog)
        labels = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
        assert "Software Catalog" in labels, (
            f"the prompt did not name the running task; labels were: {labels!r}")

    def test_declining_does_not_persist_geometry(self, armed, monkeypatch):
        """Geometry belongs to a window the user actually closed."""
        window, _thread, _worker = armed
        monkeypatch.setattr(window, "_exec_dialog",
                            lambda _d: QDialog.DialogCode.Rejected)
        writes = []
        from utils import prefs
        monkeypatch.setattr(prefs, "set_window_geometry",
                            lambda blob: writes.append(blob))
        _close(window)
        assert not writes, "geometry was saved for a close that never happened"


class TestNoPromptWhenIdle:
    def test_closing_while_idle_does_not_prompt(self, window, monkeypatch):
        original = (window._thread, window._worker)
        window._thread, window._worker = _FakeThread(False), _FakeWorker()
        prompted = []
        monkeypatch.setattr(window, "_exec_dialog",
                            lambda _d: prompted.append(_d) or QDialog.DialogCode.Rejected)
        try:
            event = _close(window)
            assert not prompted, (
                "closing an idle Pulse asked for confirmation — the prompt "
                "must only appear when something is actually running")
            assert event.isAccepted()
        finally:
            window._thread, window._worker = original

    def test_idle_close_still_persists_geometry(self, window, monkeypatch):
        original = (window._thread, window._worker)
        window._thread, window._worker = _FakeThread(False), _FakeWorker()
        writes = []
        from utils import prefs
        monkeypatch.setattr(prefs, "set_window_geometry",
                            lambda blob: writes.append(blob))
        try:
            _close(window)
            assert writes, "an ordinary close stopped saving window geometry"
        finally:
            window._thread, window._worker = original


class TestDialogItself:
    def test_the_safe_choice_is_the_default(self, window, qapp):
        """Enter on a reflexive Alt+F4 must not end a long install."""
        dialog = CloseConfirmDialog(window, window.theme.t, "Install Runtimes")
        try:
            assert dialog._keep_btn.isDefault(), (
                "'Stop & Close' is the default button — a stray Enter would "
                "kill the running task")
            assert not dialog._stop_btn.isDefault()
        finally:
            dialog.deleteLater()

    def test_the_stop_button_label_is_not_eaten_by_a_mnemonic(self, window, qapp):
        """A single '&' in Qt button text is a mnemonic marker: "Stop &
        Close" paints as "Stop _Close" with the C underlined, which reads
        as a broken label. Caught by screenshot, pinned here."""
        dialog = CloseConfirmDialog(window, window.theme.t, "Install Runtimes")
        try:
            raw = dialog._stop_btn.text()
            assert "&&" in raw or "&" not in raw, (
                f"button text {raw!r} contains an unescaped '&' — Qt will "
                "swallow it as a mnemonic and underline the next letter")
        finally:
            dialog.deleteLater()

    def test_escape_keeps_the_task_running(self, window, qapp):
        """PulseDialog rejects on Escape; reject must mean 'keep running'."""
        dialog = CloseConfirmDialog(window, window.theme.t, "Install Runtimes")
        try:
            dialog.reject()
            assert dialog.result() == QDialog.DialogCode.Rejected
        finally:
            dialog.deleteLater()

    def test_it_survives_an_unnamed_task(self, window, qapp):
        """_running_item can legitimately be None by the time the close
        lands (the task settled between the check and the prompt)."""
        dialog = CloseConfirmDialog(window, window.theme.t, "")
        try:
            from PySide6.QtWidgets import QLabel
            labels = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
            assert "An operation" in labels
        finally:
            dialog.deleteLater()

# ============================================================
#  CLOSING WINDOWS START NOTHING  (v10.6)
# ============================================================
class TestNothingStartsAfterClose:
    """A window closed shortly after launch must not start background work.

    THE CRASH THIS PINS. Two QTimers are armed during __init__ — the
    applied-state probe at 600ms and the self-update check at 2500ms — and
    both call back into the window to START A QTHREAD. Close the window
    before either fires (launching Pulse and closing it because it opened
    on the wrong monitor is an ordinary thing to do) and the timer lands on
    a window whose closeEvent has already settled its threads. The new
    thread then belongs to an object about to be destroyed, and destroying
    a QWidget with a running QThread child is qFatal: the process aborts
    with 0xC0000409, no traceback and no Qt warning.

    It reached CI as a fully green pytest run that exited non-zero with its
    summary line missing, and reproduced here only once the ambient field's
    deletion removed ~150-360ms of deferral from page transitions and let
    windows be destroyed sooner. Measured against the real sequence: one
    live thread survived the probe window without the guard, zero with it.
    """

    def test_the_flag_is_clear_while_the_window_is_alive(self, fresh_window):
        """On a FRESH window, not the session one: other tests in this file
        deliberately close the shared window, and the flag is a record of
        "a close is in progress" rather than of the window's whole life."""
        assert fresh_window()._shutting_down is False

    def test_showing_a_closed_window_makes_it_live_again(self, fresh_window, qapp):
        """Qt lets a closed window be shown again. One that came back on
        screen having quietly stopped refreshing its badges and checking
        for updates would be a worse bug than the abort the flag prevents."""
        win = fresh_window()
        win.close()
        qapp.processEvents()
        assert win._shutting_down is True
        win.showNormal()
        qapp.processEvents()
        assert win._shutting_down is False

    def test_closing_sets_it_before_anything_is_torn_down(self, fresh_window, qapp):
        win = fresh_window()
        assert win._shutting_down is False
        win.close()
        qapp.processEvents()
        assert win._shutting_down is True

    def test_a_closed_window_refuses_to_start_the_state_probe(
            self, fresh_window, qapp):
        win = fresh_window()
        win.close()
        qapp.processEvents()
        win._refresh_tweak_state()          # what the 600ms timer does
        qapp.processEvents()
        assert win._probe_thread is None, (
            "a closed window started the applied-state probe — the thread "
            "outlives the window and aborts the process when it is deleted")

    def test_a_refresh_asked_for_mid_probe_is_served_not_dropped(
            self, fresh_window, qapp, monkeypatch):
        """A BADGE THAT REPORTS THE STATE BEFORE THE ACTION.

        Two call sites schedule a state refresh 400ms after a task ends,
        and the probe itself takes about a second (measured: 0.91-0.99s for
        GetTweakState). The guard that skipped a refresh while one was
        already in flight therefore did not de-duplicate anything — it
        DROPPED the refresh belonging to any task that finished within
        roughly a second of a previous one, and nothing re-ran it.

        The card then kept its pre-action badge until some later, unrelated
        action happened to schedule another probe: "not applied" sitting
        under a tweak that had just succeeded. The likeliest way to hit it
        was also the most ordinary — two quick tweaks in a row, or a first
        action taken while the startup probe was still running.
        """
        from PySide6.QtCore import QThread
        from frontend import main as M

        launched: list[str] = []

        class CountingTask(M.PowerShellTask):
            def __init__(self, *a, **kw):
                launched.append(a[1] if len(a) > 1 else kw.get("task"))
                super().__init__(*a, **kw)

            def run(self):               # never spawn a real powershell
                pass

        monkeypatch.setattr(M, "PowerShellTask", CountingTask)
        win = fresh_window()

        # A PROBE IN FLIGHT, WITHOUT ONE ACTUALLY RUNNING. The guard reads
        # the handle, so an unstarted QThread is a faithful stand-in — and
        # starting a real one is a trap: the stub worker above never emits
        # finished/failed/cancelled, so nothing ever calls thread.quit()
        # and the thread's event loop runs forever. That does not fail this
        # test; it hangs the NEXT one, at teardown, when the window waits
        # for a thread that will never stop.
        sentinel = QThread(win)
        win._probe_thread = sentinel
        win._probe_worker = None
        win._probe_pending = False
        launched.clear()

        try:
            # The refresh a finishing task schedules, arriving mid-probe.
            win._refresh_tweak_state()
            qapp.processEvents()
            assert not launched, "a second probe ran concurrently"
            assert win._probe_pending, (
                "the refresh was discarded rather than remembered")

            # ...and now the in-flight probe finishes.
            win._probe_thread = None      # what the real handler sees
            win._on_probe_thread_finished()
            settle(qapp, 60)
            assert len(launched) == 1, (
                "the pending refresh never ran — the badge keeps its "
                "pre-action value indefinitely")
        finally:
            # Settle whatever the re-armed refresh started, for the same
            # reason the sentinel exists.
            for thread in (win._probe_thread, sentinel):
                if thread is not None:
                    thread.quit()
                    thread.wait(3000)
            win._probe_thread = None
            win._probe_worker = None
            win._probe_pending = False

    def test_a_pending_refresh_dies_with_the_window(self, fresh_window, qapp):
        """The coalescing must not become a way to start a probe on a
        window that is closing: _on_probe_thread_finished fires during
        teardown, which is exactly when the pending flag is most likely
        set."""
        win = fresh_window()
        win._probe_pending = True
        win.close()
        qapp.processEvents()
        win._on_probe_thread_finished()
        settle(qapp, 60)
        assert win._probe_thread is None, (
            "a closing window started the probe its pending flag had "
            "queued — the thread outlives the window")

    def test_a_closed_window_refuses_to_start_the_update_check(
            self, fresh_window, qapp):
        win = fresh_window()
        win.close()
        qapp.processEvents()
        win._check_for_updates(silent=True)   # what the 2500ms timer does
        qapp.processEvents()
        assert win._update_check_thread is None

    def test_a_late_update_result_is_dropped_rather_than_painted(
            self, fresh_window, qapp):
        """The check is a urllib GET with a 5s connect + 10s read timeout,
        so it routinely outlives a window closed just after launch. Its
        result slot touches the badge on its first line."""
        win = fresh_window()
        win.close()
        qapp.processEvents()
        win._on_update_checked(None)          # must not touch any widget
        qapp.processEvents()

    def test_no_thread_survives_a_close_and_its_timer_windows(
            self, fresh_window, qapp):
        """End to end, at the exact shape the runner hit: construct, close
        immediately, then pump the loop past BOTH timers."""
        from PySide6.QtCore import QThread

        win = fresh_window()
        win.close()
        settle(qapp, 800)                     # past the 600ms probe
        alive = [t for t in win.findChildren(QThread) if t.isRunning()]
        assert not alive, (
            f"{len(alive)} thread(s) still running after close — deleting "
            "this window would abort the process")


# ============================================================
#  MODAL LIFETIME — every dialog the shell opens, and lets go
# ============================================================
class TestModalsAreReleased:
    """A PARENTED QDialog THAT NOBODY DELETES LIVES AS LONG AS THE WINDOW.

    Every modal in the app is built as `SomeDialog(self, ...)` and dropped
    on the floor once exec() returns. The Python reference goes; the C++
    object does not, because it is a child of PulseApp. Measured before the
    fix: ten Ctrl+K presses left ten live CommandPalettes holding 120 list
    rows and 970 child QObjects between them, and all twenty-two call sites
    through _exec_dialog had the same shape.

    It is a leak of exactly the kind that never shows up in a test run and
    only bites the user who keeps the app open all afternoon — which, for a
    tool whose whole premise is running a sequence of maintenance tasks, is
    the normal way to use it.
    """

    @staticmethod
    def _probe_dialog(window):
        """A dialog whose exec() returns without a nested event loop.

        Patching QDialog.exec globally instead deadlocks the suite: the
        shell opens dialogs during construction and teardown, and a
        show/reject stand-in re-enters them.
        """
        from PySide6.QtWidgets import QDialog

        class Probe(QDialog):
            def exec(self):
                return QDialog.DialogCode.Rejected

        return Probe(window)

    @staticmethod
    def _drain(qapp):
        from PySide6.QtCore import QEvent
        for _ in range(3):
            qapp.processEvents()
            qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qapp.processEvents()

    def test_exec_dialog_destroys_what_it_showed(self, window, qapp):
        import shiboken6

        dialog = self._probe_dialog(window)
        assert shiboken6.isValid(dialog)
        window._exec_dialog(dialog)
        self._drain(qapp)
        assert not shiboken6.isValid(dialog), (
            "the modal outlived its own exec() — it is parented to the "
            "window and nothing deletes it, so it lives until the app quits")

    def test_the_caller_can_still_read_the_result(self, window, qapp):
        """deleteLater is DEFERRED, and the callers depend on that: they
        read `palette.chosen_item` / `dialog.selected_ids` on the line
        after _exec_dialog returns. A direct delete here would turn every
        one of those into a use-after-free."""
        import shiboken6

        dialog = self._probe_dialog(window)
        dialog.chosen_item = {"title": "still here"}
        window._exec_dialog(dialog)
        # Exactly what a caller does: read before yielding to the loop.
        assert shiboken6.isValid(dialog), (
            "the dialog was destroyed synchronously; every call site that "
            "reads a result off it is now a use-after-free")
        assert dialog.chosen_item["title"] == "still here"

    def test_repeated_opens_do_not_accumulate(self, window, qapp):
        """The shape the leak actually took: the palette is the app's
        primary navigation surface, so it is opened over and over."""
        import gc

        from frontend import widgets as W

        def live():
            out = 0
            for obj in gc.get_objects():
                if isinstance(obj, W.CommandPalette):
                    try:
                        obj.objectName()
                        out += 1
                    except RuntimeError:
                        pass
            return out

        from PySide6.QtWidgets import QDialog

        class _NonBlocking(W.CommandPalette):
            """exec() without the nested event loop.

            The real one blocks until the dialog closes, and nothing in a
            headless test ever closes it — an earlier version of this test
            called it and hung the whole suite, which is a far worse defect
            than the leak it was written to catch. Subclassed rather than
            monkeypatched on QDialog: the shell opens dialogs of its own
            during teardown and a global stand-in re-enters them.
            """

            def exec(self):     # noqa: A003 - Qt's name
                return QDialog.DialogCode.Rejected

        self._drain(qapp)
        before = live()
        for _ in range(5):
            window._exec_dialog(_NonBlocking(window, window.theme.t, []))
            self._drain(qapp)
        after = live()
        assert after <= before, (
            f"{after - before} CommandPalette(s) survived five open/close "
            "cycles")
