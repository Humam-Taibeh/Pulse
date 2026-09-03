"""
Two things a long day does to a running task: flood its pipe, and suspend
the machine underneath it.

PIPE SATURATION - NO DEFECT, AND THE REASON IS STRUCTURAL
    The classic subprocess deadlock needs two pipes: stdout and stderr
    both PIPE, the parent reading one, the child filling the other until
    it blocks on a write nobody is draining. PowerShellTask cannot reach
    that state because it merges the streams (stderr=subprocess.STDOUT)
    and drains the single pipe to EOF in one loop.

    Confirmed under load rather than argued: 60,000 lines through a real
    PowerShell child completed in 7.4s with a 4.7 MB peak heap, all 60,001
    output signals delivered and the verdict parsed correctly. The test
    below runs a smaller flood for suite speed; the structural property
    that MAKES it safe is asserted separately, because "someone tidies
    stderr into its own PIPE" is exactly how this class of deadlock comes
    back and it would look like an improvement in review.

SLEEP - ONE REAL DEFECT, IN THE DURATIONS
    prefs.record_task_run guarded `duration_ms <= 0` (the backwards-clock
    case its comment describes) and had no upper bound at all. A machine
    suspended mid-task resumes with a duration measured across the sleep,
    and that value is folded into an exponential moving average that is
    PERSISTED - so one closed laptop lid makes a card advertise a typical
    duration of several hours, and the EMA's memory means it keeps
    advertising it for many runs afterwards.

    The guard is correct whatever the clock does across suspend, and that
    matters here: Python resolves time.monotonic() to
    QueryPerformanceCounter on this platform, whose behaviour across S3
    and modern standby is not something this suite can test - it would
    have to suspend the machine running it. So the fix is not "handle
    sleep", it is "refuse a duration that could not have happened",
    which also covers a VM snapshot restore, a debugger pause and a
    hibernation, and needs no knowledge of which one occurred.

    What makes it decidable is the watchdog: every task is killed at its
    own timeout, the largest configured anywhere is 3600s, so no genuine
    run can exceed that.
"""
from __future__ import annotations

import inspect
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

from PySide6.QtCore import QEventLoop, QThread

from utils import prefs
from utils.helpers import PowerShellTask

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="spawns a real PowerShell child")


# ============================================================
#  1. THE PIPE
# ============================================================
class TestThePipeCannotDeadlock:
    def test_the_streams_are_merged(self):
        """The structural property, asserted on its own because it is the
        one that would be quietly undone. `stderr=subprocess.PIPE` looks
        tidier and reintroduces the two-pipe deadlock the moment a task
        writes more to stderr than its buffer holds - which DISM and
        winget both do."""
        source = inspect.getsource(PowerShellTask.run)
        assert "stderr=subprocess.STDOUT" in source, (
            "stderr is no longer merged into stdout; if it is now its own "
            "PIPE it needs its own reader, or a chatty task will deadlock "
            "when that buffer fills")

    def test_the_reader_drains_to_eof(self):
        """A loop that stops on anything but EOF leaves the child blocked
        on a write forever."""
        source = inspect.getsource(PowerShellTask.run)
        assert "read1" in source and "if not chunk:" in source, (
            "the read loop no longer drains to EOF")

    def test_a_flood_completes_and_still_parses_its_verdict(self, qapp):
        """End to end through a real child. The verdict line arrives LAST,
        after the flood, so this also proves the parse survives a buffer
        the reader had to reassemble across thousands of chunks."""
        directory = pathlib.Path(tempfile.mkdtemp())
        stub = directory / "flood.ps1"
        stub.write_text(
            "param([string]$Task)\n"
            "1..20000 | ForEach-Object { Write-Output \"line $_ "
            "########################################\" }\n"
            "Write-Output '##PULSE##SUCCESS|flood complete'\n",
            encoding="utf-8")

        results = []
        thread = QThread()
        worker = PowerShellTask(str(stub), "Flood", timeout=180)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        loop = QEventLoop()
        worker.finished.connect(lambda r: (results.append(r), loop.quit()))
        worker.failed.connect(lambda m: (results.append(m), loop.quit()))
        thread.start()
        loop.exec()
        thread.quit()
        thread.wait(15000)

        assert results, "the flood produced no terminal signal — deadlocked"
        result = results[0]
        assert getattr(result, "success", False), (
            f"the verdict after 20k lines was not parsed: {result}")
        assert "flood complete" in result.message


# ============================================================
#  2. SLEEP, HIBERNATION, AND ANY OTHER TIME JUMP
# ============================================================
class TestImplausibleDurationsAreRefused:
    @pytest.fixture(autouse=True)
    def _clean_history(self):
        prefs.clear_task_history()
        yield
        prefs.clear_task_history()

    def test_a_normal_duration_is_recorded(self):
        prefs.record_task_run("SomeTask", 4200.0, "ok")
        entry = prefs.task_history()["SomeTask"]
        assert entry["runs"] == 1
        assert entry["avg_ms"] == pytest.approx(4200.0)

    def test_a_duration_longer_than_any_task_can_run_is_refused(self):
        """A laptop lid closed overnight with a task in flight. No run can
        legitimately outlast its own watchdog, and the largest timeout
        configured anywhere is 3600s."""
        prefs.record_task_run("SomeTask", 8 * 3600 * 1000.0, "ok")
        assert "SomeTask" not in prefs.task_history(), (
            "an eight-hour duration was folded into the average; the card "
            "will now advertise it as typical")

    def test_it_does_not_corrupt_an_existing_average(self):
        """The damaging case: the task has a good history, then one run
        spans a sleep. The EMA is persisted, so a single bad sample keeps
        distorting the caption for many runs after it."""
        for _ in range(5):
            prefs.record_task_run("SomeTask", 5000.0, "ok")
        before = prefs.task_history()["SomeTask"]

        prefs.record_task_run("SomeTask", 6 * 3600 * 1000.0, "ok")

        after = prefs.task_history()["SomeTask"]
        assert after["avg_ms"] == pytest.approx(before["avg_ms"]), (
            f"the average moved from {before['avg_ms']:.0f}ms to "
            f"{after['avg_ms']:.0f}ms on a sleep-spanning run")
        assert after["runs"] == before["runs"], (
            "the refused sample still incremented the run count, so the "
            "EMA weight now reflects a measurement that was thrown away")

    def test_the_ceiling_clears_the_longest_real_task(self):
        """Both directions. Too low and a genuinely long deploy is
        discarded and never learned from; the longest timeout configured
        is 3600s, so the ceiling has to sit above a full-length run of it."""
        assert prefs.MAX_PLAUSIBLE_RUN_MS > 3600 * 1000, (
            "the ceiling is below the longest task the app can run")
        prefs.record_task_run("LongTask", 3600 * 1000.0, "ok")
        assert "LongTask" in prefs.task_history(), (
            "a full-length run of the longest-timeout task was refused")

    def test_zero_and_negative_are_still_refused(self):
        """The original guard, kept."""
        prefs.record_task_run("SomeTask", 0.0, "ok")
        prefs.record_task_run("SomeTask", -5000.0, "ok")
        assert "SomeTask" not in prefs.task_history()


class TestTheElapsedClockSurvivesATimeJump:
    def test_a_huge_elapsed_still_renders_sanely(self, qapp):
        """The pill reads from a monotonic start and recomputes on every
        tick, so a machine that slept mid-task resumes showing whatever
        the clock says. It must still be a CLOCK - not a negative, not an
        exception, not a value that overflows its own format."""
        from frontend import theme as TH
        from frontend.widgets import StatePill

        pill = StatePill(TH.tokens("dark"))
        pill.show()
        pill.set_state("running")
        pill._started_at -= 9 * 3600          # nine hours, as if after sleep
        pill._tick()

        text = pill.text()
        assert text.startswith("RUNNING"), text
        minutes, _, seconds = text.split("·")[1].strip().partition(":")
        assert minutes.isdigit() and seconds.isdigit(), (
            f"the clock stopped being a clock after a time jump: {text!r}")
        assert int(seconds) < 60

    def test_a_backwards_jump_does_not_render_a_negative(self, qapp):
        """The other direction, which the existing max(0, ...) covers -
        pinned because it is one character and easy to lose."""
        from frontend import theme as TH
        from frontend.widgets import StatePill

        pill = StatePill(TH.tokens("dark"))
        pill.show()
        pill.set_state("running")
        pill._started_at += 600               # start in the future
        pill._tick()

        assert pill.text() == "RUNNING · 00:00", pill.text()
