"""
Every finished task gave back the handles it took.

WHAT WAS LEAKING
    PowerShellTask.run() stored the Popen on self._process and never
    cleared it, and nothing ever closed the stdout pipe. Cleanup was
    therefore left to garbage collection of the worker - which is not
    deterministic, and which does not happen at all while anything still
    holds the worker. main.py holds exactly that: self._worker stays set
    until the NEXT task replaces it.

    Measured with GetProcessHandleCount across five real engine runs:

        baseline 278
        run 1    280   (+2)
        run 2    282   (+4)
        run 3    284   (+6)
        run 4    286   (+8)
        run 5    288  (+10)
        after dropping every reference and gc.collect(): still 288

    Two handles per task - the process handle and the read end of the
    stdout pipe - and they did not come back. Not a fast leak, and Pulse
    is not a long-running service, but it is unbounded in the one session
    where it matters most: a technician working through a machine, task
    after task, which is the whole workflow the app exists for.

WHY MEASURE HANDLES RATHER THAN OBJECTS
    A Python-side test (weakref to the Popen, say) proves something
    narrower and more fragile than the thing anyone cares about. The OS
    handle count is the number Task Manager shows and the number that runs
    out; it also catches a leak that a Python-level assertion would miss
    entirely, such as a duplicated kernel handle nobody wrapped.

    THAT ARGUMENT SURVIVES, WITH ONE MEASURED LIMIT ADDED LATER. The count
    is process-wide, so on a machine this suite does not own it also sums
    whatever else allocated handles during the run. A GitHub runner
    measured +11 across four healthy runs - 2.75/run, against the 2/run
    the leak itself produced. An OS-level count therefore still catches a
    GROSS leak that no Python assertion would see, and that is what it is
    now asked to do; resolving two handles per run is below its noise
    floor anywhere but a quiet desktop. The precise per-run property is
    asserted directly instead. See
    TestHandlesComeBack.test_repeated_tasks_do_not_accumulate_handles.
"""
from __future__ import annotations

import ctypes
import gc
import os
import sys
from ctypes import wintypes

import pytest

from PySide6.QtCore import QEventLoop, QThread

from utils.helpers import PowerShellTask

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="Win32 handle accounting")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENGINE = os.path.join(_ROOT, "src", "backend", "core.ps1")


def _handle_count() -> int:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE,
                                          ctypes.POINTER(wintypes.DWORD)]
    k32.GetProcessHandleCount.restype = wintypes.BOOL
    count = wintypes.DWORD(0)
    if not k32.GetProcessHandleCount(k32.GetCurrentProcess(),
                                     ctypes.byref(count)):
        raise OSError(f"GetProcessHandleCount failed: "
                      f"{ctypes.get_last_error()}")
    return count.value


def _run_task(qapp, keep: list) -> PowerShellTask:
    """One real engine run, torn down the way main.py tears one down."""
    thread = QThread()
    worker = PowerShellTask(_ENGINE, "GetTweakState", timeout=90)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    loop = QEventLoop()
    for signal in (worker.finished, worker.failed, worker.cancelled):
        signal.connect(lambda *_a: loop.quit())
    thread.start()
    loop.exec()
    thread.quit()
    thread.wait(10000)
    worker.deleteLater()
    thread.deleteLater()
    qapp.processEvents()
    gc.collect()
    qapp.processEvents()
    # Held on purpose: main.py keeps _worker alive until the next task
    # replaces it, so a test that dropped it would measure a lifetime the
    # app never has.
    keep.append(worker)
    return worker


class TestHandlesComeBack:
    def test_repeated_tasks_do_not_accumulate_handles(self, qapp):
        """The measurement that found it, retargeted onto what it can
        actually prove on a machine it does not own.

        THE ORIGINAL ASSERTION WAS `growth < runs` ON A WHOLE-PROCESS
        COUNT, and it did not survive contact with CI.
        GetProcessHandleCount reports every handle the *pytest process*
        owns, so it also counts whatever Qt, the CRT, Defender and the
        runner's own tooling opened while four real engine spawns were in
        flight. On the box this was written on that ambient churn is
        approximately zero and the leak's +2/run stood out cleanly. On a
        GitHub runner the same healthy code measured +11 across 4 runs and
        failed the build for a leak that was not there - every worker had
        released its Popen, and the two tests below passed in the same run.

        RAISING THE NUMBER UNTIL THAT STOPPED WOULD BE THE EXACT FAILURE
        tests/test_ci_guard.py EXISTS TO PREVENT, so the instrument
        changed instead of the threshold. The retention being guarded is
        per-run and deterministic - run() must clear _process and close
        the pipe on EVERY run, not merely on the single run each test
        below inspects - and that property is what the +2/run leak
        violated. Checked across the batch here, it cannot be perturbed by
        anything else running on the machine.

        The handle count is still measured, and still asserted, but as the
        coarse backstop it can honestly be rather than as the primary
        guard. This file's header argues that an OS-level count catches
        what a Python-level assertion misses - a duplicated kernel handle
        nobody wrapped - and that is still true and still worth keeping.
        What is no longer true is that it can resolve two handles per run:
        the noise floor on a shared runner (2.75/run, measured) is above
        the signal the original number was set to detect. So the ceiling
        is set where it separates cleanly from that floor and catches a
        gross leak, and the per-run assertion above it catches the precise
        one. Neither is a relaxation of the other; they detect different
        magnitudes, and the docstring says which is which so nobody
        re-tightens the ceiling into flakiness again.
        """
        held: list = []
        _run_task(qapp, held)          # warm up: first run loads the engine
        held.clear()
        gc.collect()
        qapp.processEvents()
        baseline = _handle_count()

        runs = 4
        for index in range(runs):
            worker = _run_task(qapp, held)
            assert worker._process is None, (
                f"run {index + 1} of {runs} finished still holding its "
                "Popen, which keeps the process handle AND the read end "
                "of the stdout pipe alive for as long as the worker "
                "lives - and main.py keeps it until the next task "
                "replaces it. That is the retention that leaked two "
                "handles per task")

        growth = _handle_count() - baseline
        print(f"handle growth across {runs} runs: {growth:+d} "
              f"({growth / runs:+.2f}/run)")
        assert growth < runs * 8, (
            f"{growth} handles retained across {runs} tasks "
            f"({growth / runs:.1f}/run) - far above anything ambient "
            "activity on a busy runner accounts for, so something is "
            "leaking kernel handles wholesale")

    def test_the_popen_reference_is_released(self, qapp):
        """The retention path itself. Holding the Popen keeps the process
        handle AND the pipe alive for as long as the worker lives, which
        is until the next task replaces it."""
        held: list = []
        worker = _run_task(qapp, held)
        assert worker._process is None, (
            "the worker still holds its Popen after the task finished")

    def test_the_stdout_pipe_is_closed(self, qapp, monkeypatch):
        """Closed explicitly rather than left to the Popen's own
        finalizer, because that finalizer only runs once the worker is
        collected and the app deliberately keeps the worker alive.

        The pipe is captured by spying on Popen from the TEST side rather
        than by having the worker keep a reference for inspection: a
        test-only attribute on production code would be a second thing to
        maintain, and one that quietly re-creates the very retention this
        is checking has gone.
        """
        import subprocess as sp

        created = []
        real_popen = sp.Popen

        class _SpyPopen(real_popen):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

        monkeypatch.setattr(sp, "Popen", _SpyPopen)

        held: list = []
        _run_task(qapp, held)

        assert created, "no process was spawned; the spy caught nothing"
        pipe = created[0].stdout
        assert pipe is not None and pipe.closed, (
            "the stdout pipe is still open after the task finished")


class TestTeardownStillBehaves:
    """The cleanup must not have been bought by breaking the result."""

    def test_a_task_still_reports_its_verdict(self, qapp):
        held: list = []
        results = []
        thread = QThread()
        worker = PowerShellTask(_ENGINE, "GetTweakState", timeout=90)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        loop = QEventLoop()
        worker.finished.connect(lambda r: (results.append(r), loop.quit()))
        worker.failed.connect(lambda m: (results.append(m), loop.quit()))
        thread.start()
        loop.exec()
        thread.quit()
        thread.wait(10000)
        held.append(worker)

        assert results, "the task produced no terminal signal at all"
        result = results[0]
        assert getattr(result, "success", False), (
            f"the read-only probe stopped succeeding: {result}")

    def test_cancel_after_completion_is_harmless(self, qapp):
        """main.py can call cancel() on a worker whose task has already
        settled — closeEvent does exactly that. With _process cleared it
        must take the no-op path rather than touching a released object."""
        held: list = []
        worker = _run_task(qapp, held)
        worker.cancel()          # must not raise
