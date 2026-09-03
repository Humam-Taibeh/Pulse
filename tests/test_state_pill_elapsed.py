"""
StatePill elapsed time: RUNNING carries its own clock.

THE COMPLAINT THIS ANSWERS
    The pill said RUNNING for the full length of an eight-minute install
    with no sense of how long it had already been running. The per-task
    duration history recorded for the card's own "last run" line (v10.1)
    made a *live* elapsed reading possible from data Pulse already
    collects — it just never reached the pill.
"""
from __future__ import annotations

from frontend import theme as TH
from frontend.widgets import StatePill


class TestElapsedClock:
    def test_running_shows_a_zero_clock_immediately(self, qapp):
        pill = StatePill(TH.tokens("dark"))
        pill.set_state("running")
        assert pill.text() == "RUNNING · 00:00"

    def test_the_clock_advances_on_a_tick(self, qapp):
        pill = StatePill(TH.tokens("dark"))
        pill.set_state("running")
        pill._started_at -= 41  # backdate rather than sleep the test
        pill._tick()
        assert pill.text() == "RUNNING · 00:41"

    def test_minutes_roll_over_past_sixty_seconds(self, qapp):
        pill = StatePill(TH.tokens("dark"))
        pill.set_state("running")
        pill._started_at -= 125
        pill._tick()
        assert pill.text() == "RUNNING · 02:05"

    def test_the_timer_is_running_only_in_the_running_state(self, qapp):
        pill = StatePill(TH.tokens("dark"))
        assert not pill._timer.isActive()
        pill.set_state("running")
        assert pill._timer.isActive()

    def test_a_terminal_state_drops_the_clock_and_stops_the_timer(self, qapp):
        pill = StatePill(TH.tokens("dark"))
        pill.set_state("running")
        pill.set_state("ok")
        assert pill.text() == "SUCCESS"
        assert not pill._timer.isActive()

    def test_re_entering_running_resets_the_clock(self, qapp):
        pill = StatePill(TH.tokens("dark"))
        pill.set_state("running")
        pill._started_at -= 90
        pill.set_state("err")
        pill.set_state("running")
        assert pill.text() == "RUNNING · 00:00"

    def test_idle_and_stopped_text_is_unchanged(self, qapp):
        """The clock is additive to RUNNING only — every other label is the
        same literal it always was."""
        pill = StatePill(TH.tokens("dark"))
        assert pill.text() == "IDLE"
        pill.set_state("stopped")
        assert pill.text() == "STOPPED"
