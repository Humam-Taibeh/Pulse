"""
Window state machine — including the launch-blocking crash.

Regression origin: _init_geometry() runs during __init__ and calls
restoreGeometry(), which re-applies a saved MAXIMIZED state synchronously.
That fired changeEvent before _build_ui() had created _glow/_shell/_body,
so the handler raised AttributeError and took the process down. Effect:
close Pulse while maximized and it never starts again. It reached a real
user hive. This file is the guard.
"""
from __future__ import annotations

import pytest

from conftest import settle

pytestmark = pytest.mark.native


def test_cold_start_with_no_saved_geometry(fresh_window):
    """First-ever launch: _init_geometry falls through to the centred
    default and calls resize()/move() before the UI exists."""
    from utils import prefs
    from PySide6.QtCore import QSettings
    QSettings(prefs._ORG, prefs._APP).remove("ui/geometry")
    win = fresh_window()
    assert win.isVisible()
    assert win.width() > 0 and win.height() > 0


def test_restoring_a_maximized_geometry_does_not_crash(fresh_window, qapp):
    """THE regression: 'closed while maximized' must still start."""
    from utils import prefs
    first = fresh_window()
    first.showMaximized()
    settle(qapp, 300)
    assert first.isMaximized()
    prefs.set_window_geometry(first.saveGeometry())
    first.hide()

    second = fresh_window(normalize=False)   # must not raise
    assert second.isMaximized(), "the saved maximized state should restore"


def test_restored_maximized_window_looks_flush(fresh_window, qapp):
    """The state change is dropped while the UI is still being built, so
    __init__ must replay it — otherwise a restored-maximized window comes
    up wearing the floating look (margins that don't reach the edges)."""
    from utils import prefs
    first = fresh_window()
    first.showMaximized()
    settle(qapp, 300)
    prefs.set_window_geometry(first.saveGeometry())
    first.hide()

    second = fresh_window(normalize=False)
    settle(qapp, 200)
    assert second._shell.property("flush") is True
    from frontend.main import _FLUSH_MARGINS
    got = second._body.getContentsMargins()
    assert got == _FLUSH_MARGINS


def test_ui_ready_guard_exists(window):
    """changeEvent must stay guarded; without the flag the crash returns."""
    assert window._ui_ready is True


def test_maximize_restore_round_trip(floating, qapp):
    floating.showMaximized()
    settle(qapp, 300)
    assert floating._shell.property("flush") is True
    floating.showNormal()
    settle(qapp, 300)
    assert floating._shell.property("flush") is False


class TestSizeMoveTracking:
    """`_in_size_move` records that Windows' modal move/size loop is running.

    THIS CLASS USED TO BE TestSizeMoveParking, and what it parked is gone.
    The flag existed to suspend the ambient background for the duration of
    a drag: that background was a full-window repaint competing with the
    move loop on the same thread, and parking it took mean drag-tracking
    lag from 3.6px to 0.3px. With the field deleted there is no repaint
    left to park.

    The FLAG still earns its place, and that is what is asserted here. It
    is the only thing that can distinguish an Aero-snap performed inside a
    drag from a maximize performed outside one, which `_sync_window_state`
    reads to decide whether a state change is the user's or the loop's.
    A flag that silently stopped tracking would leave that decision being
    made on stale information, and nothing else would notice.
    """

    def test_the_flag_is_clear_on_a_settled_window(self, floating):
        assert floating._in_size_move is False

    def test_a_state_sync_mid_drag_leaves_the_flag_set(self, floating):
        """Aero-snapping changes window state INSIDE the move loop, so
        _sync_window_state runs while the drag is still in flight. It must
        observe the drag rather than clear it."""
        floating._in_size_move = True
        try:
            floating._sync_window_state()
            assert floating._in_size_move is True
        finally:
            floating._in_size_move = False

    def test_the_window_survives_a_full_enter_exit_cycle(self, floating, qapp):
        """The handlers are two lines each now; this is the guard that
        they still leave the window in a coherent state rather than that
        they park anything."""
        floating._in_size_move = True
        floating._sync_window_state()
        floating._in_size_move = False
        floating._sync_window_state()
        settle(qapp, 120)
        assert floating._in_size_move is False
        assert floating.isVisible()


def test_minimum_size_respects_the_layout_floor(window):
    """Below chrome + one minimum-width card the grid physically cannot
    lay out, so the minimum must never be set under that floor."""
    from frontend.main import CategoryPage
    floor = window._CHROME_W + CategoryPage.MIN_CARD_W
    assert window.minimumWidth() >= floor
