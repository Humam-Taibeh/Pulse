"""
A minimized window paints nothing. Pinned, because it holds by accident.

WHAT THIS IS NOT
    Not a fix. The audit that produced this file went looking for animation
    burning CPU behind a minimized window and did not find any, which is
    worth recording as precisely as a defect would have been.

WHY IT LOOKED LIKE A DEFECT
    Every looping animation on the shell gates itself on VISIBILITY —
    BrandMark and StatusDot both stop on hideEvent and start on showEvent
    ("never breathe at an invisible widget"). Minimizing does not make a
    window's children invisible in the sense that reads most naturally:
    `isVisible()` stays True on every child for the whole time the window
    sits in the taskbar. On that reading the breath would keep running at
    ~19 repaints a second, repainting through every transparent ancestor
    (see the v10.9.2 note on BrandMark's quantised breath) for pixels
    nobody can see.

WHAT ACTUALLY HAPPENS
    Qt delivers a real hideEvent to the children of a minimized top-level
    window on Windows, and a showEvent again on restore — even though
    isVisible() reports True throughout. Measured directly before these
    tests were written:

        child isVisible before minimize: True
        events delivered to CHILD on minimize: ['hide']
        child isVisible while minimized: True
        events after restore: ['hide', 'show']

    So the visibility gate already covers minimizing, and the idle cost of
    a minimized Pulse is zero animation frames.

WHY PIN IT ANYWAY
    Because it is true for a reason nobody chose: it rests on Qt's event
    delivery, not on anything this app does deliberately, and the app's own
    gate is written against a DIFFERENT case (page navigation). A future
    change that moves BrandMark off showEvent/hideEvent onto an explicit
    "is the current page" check would be entirely reasonable, would pass
    every existing test, and would silently reintroduce a breathing logo
    behind a minimized window. These tests are what would notice.

`native`: minimizing is a real window-manager operation and the offscreen
platform has no window state to change.
"""
from __future__ import annotations

import pytest

from frontend.widgets import BrandMark, StatusDot

pytestmark = pytest.mark.native


def _brand_marks(window) -> list[BrandMark]:
    return [w for w in window.findChildren(BrandMark) if w._anim is not None]


class TestMinimizedWindowStopsAnimating:
    def test_the_breath_runs_while_the_window_is_up(self, floating, qapp):
        """The precondition. Without it the stop-test below proves nothing:
        an animation that was never running trivially is not running."""
        marks = _brand_marks(floating)
        assert marks, "no breathing brand mark on the shell to measure"
        qapp.processEvents()
        assert any(m._anim.state() == m._anim.State.Running for m in marks), (
            "the masthead's breath is not running on a visible window — "
            "this test can prove nothing about stopping it")

    def test_minimizing_stops_every_looping_animation(self, floating, qapp):
        marks = _brand_marks(floating)
        floating.showMinimized()
        qapp.processEvents()
        try:
            still_running = [m for m in marks
                             if m._anim.state() == m._anim.State.Running]
            assert not still_running, (
                f"{len(still_running)} brand mark(s) still breathing while "
                "the window is minimized — repainting through every "
                "transparent ancestor for pixels in the taskbar")
        finally:
            floating.showNormal()
            qapp.processEvents()

    def test_restoring_starts_them_again(self, floating, qapp):
        """The other half. A gate that suspends and never resumes trades
        idle cost for a dead logo on every restore."""
        marks = _brand_marks(floating)
        floating.showMinimized()
        qapp.processEvents()
        floating.showNormal()
        qapp.processEvents()

        assert any(m._anim.state() == m._anim.State.Running for m in marks), (
            "the breath never came back after restore")

    def test_a_hidden_mark_stays_stopped_after_a_restore(self, floating, qapp):
        """The two conditions compose: restoring the window must not start
        an animation on a widget that is hidden in its own right. Resuming
        everything unconditionally on restore is the obvious wrong fix, and
        this is what would catch it."""
        marks = _brand_marks(floating)
        mark = marks[0]
        mark.hide()
        qapp.processEvents()
        floating.showMinimized()
        qapp.processEvents()
        floating.showNormal()
        qapp.processEvents()
        try:
            assert mark._anim.state() != mark._anim.State.Running, (
                "restoring the window started the breath on a widget that is "
                "still hidden in its own right")
        finally:
            mark.show()
            qapp.processEvents()


class TestStatusDotFollowsTheSameRule:
    def test_a_pulsing_dot_stops_while_minimized(self, floating, qapp):
        """StatusDot pulses only while the engine is busy, so it is the
        animation most likely to be running when someone minimizes the
        window and walks away — the case that actually costs something over
        a long DISM or winget run."""
        dots = floating.findChildren(StatusDot)
        assert dots, "no status dot on the shell"
        dot = dots[0]
        dot.start_pulse()
        qapp.processEvents()
        assert dot._anim.state() == dot._anim.State.Running, (
            "the dot is not pulsing; there is nothing here to suspend")

        floating.showMinimized()
        qapp.processEvents()
        try:
            assert dot._anim.state() != dot._anim.State.Running, (
                "the busy dot kept pulsing while the window was minimized")
        finally:
            floating.showNormal()
            dot.stop_pulse()
            qapp.processEvents()


class TestTheElapsedClockFollowsTheSameRule:
    """The state pill's RUNNING clock (v10.9.4) is a REPEATING 1Hz QTimer,
    and it shipped without the visibility gate its neighbours have.

    Animations were covered by Qt's own hideEvent delivery (see this
    module's header). A QTimer is not: nothing stops it when the widget is
    hidden, so a task left running behind a minimized window kept waking
    the GUI thread once a second to setText() on a label nobody could see —
    and each of those repaints a transparent ancestor chain, which is the
    same cost the brand mark's breath was quantised down to avoid.

    The clock must not LOSE time while paused: elapsed is recomputed from a
    monotonic start, so the pill catches up in one tick on re-show rather
    than resuming from where it stopped.
    """

    def test_the_clock_ticks_while_visible(self, floating, qapp):
        """The drawer is opened FIRST, which is the order _start_task uses
        (set_running(True), then set_state("running")) — and it matters,
        because the pill lives in the drawer's body and the clock gates on
        being on screen."""
        floating.activity.set_running(True)
        qapp.processEvents()
        pill = floating.state_pill
        pill.set_state("running")
        qapp.processEvents()
        try:
            assert pill.isVisible(), "the drawer did not open; nothing to tick"
            assert pill._timer.isActive(), "the clock is not running at all"
        finally:
            pill.set_state("idle")
            floating.activity.set_running(False)
            qapp.processEvents()

    def test_minimizing_stops_the_clock(self, floating, qapp):
        floating.activity.set_running(True)
        qapp.processEvents()
        pill = floating.state_pill
        pill.set_state("running")
        qapp.processEvents()
        floating.showMinimized()
        qapp.processEvents()
        try:
            assert not pill._timer.isActive(), (
                "the elapsed clock kept firing once a second behind a "
                "minimized window")
        finally:
            floating.showNormal()
            qapp.processEvents()
            pill.set_state("idle")
            floating.activity.set_running(False)
            qapp.processEvents()

    def test_restoring_resumes_it_without_losing_time(self, floating, qapp):
        """The clock reads from a monotonic start, so a pause must cost
        nothing: the pill shows the true elapsed time on the first tick
        after it comes back, not the time it had when it stopped."""
        floating.activity.set_running(True)
        qapp.processEvents()
        pill = floating.state_pill
        pill.set_state("running")
        pill._started_at -= 120          # pretend the task has run 2 minutes
        qapp.processEvents()
        floating.showMinimized()
        qapp.processEvents()
        floating.showNormal()
        qapp.processEvents()
        try:
            assert pill._timer.isActive(), "the clock never resumed"
            assert pill.text() == "RUNNING · 02:00", (
                f"the pill reads {pill.text()!r} — it lost the time it "
                "spent minimized instead of recomputing from the start")
        finally:
            pill.set_state("idle")
            floating.activity.set_running(False)
            qapp.processEvents()

    def test_a_finished_task_leaves_the_clock_stopped_on_re_show(
            self, floating, qapp):
        """The two conditions compose, as they do for the brand mark:
        becoming visible again must not restart a clock for a task that
        ended while the window was away."""
        floating.activity.set_running(True)
        qapp.processEvents()
        pill = floating.state_pill
        pill.set_state("running")
        qapp.processEvents()
        floating.showMinimized()
        qapp.processEvents()
        pill.set_state("ok")             # the task finished while minimized
        floating.showNormal()
        qapp.processEvents()

        assert not pill._timer.isActive(), (
            "re-showing restarted the clock for a task that had finished")
        assert pill.text() == "SUCCESS"
        floating.activity.set_running(False)
        qapp.processEvents()
