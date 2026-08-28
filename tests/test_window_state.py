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


def test_minimize_leaves_the_ambient_loop_parked(floating, qapp):
    """hideEvent does not fire on minimize, so a repainting field would
    otherwise keep running behind an invisible window.

    As of v10.5 there is no loop to park (widgets._AmbientSimulation.
    STATIC), and the assertion is the stronger one for it: the timer is
    stopped on minimize AND stays stopped on restore. The old test asserted
    it came BACK, which was the correct contract for an animated wash and
    is now precisely the regression to catch — a restore that started the
    timer would put an idle app back to repainting its whole translucent
    widget stack ten times a second.
    """
    floating.showMinimized()
    settle(qapp, 300)
    assert not floating._glow._timer.isActive()
    floating.showNormal()
    settle(qapp, 400)
    assert not floating._glow._timer.isActive(), (
        "restoring the window started the ambient timer — the field is "
        "meant to be static")


class TestSizeMoveParking:
    """suspend()/resume() around the OS move/size loop.

    The parking took mean drag tracking lag from 3.6px to 0.3px, and it
    still earns its place with a static field: what it parks now is not a
    timer but the COMPOSITED ORB LAYER. A drag hands the widget a different
    size on every step, and rebuilding a full-window pixmap per step is the
    most expensive thing that could happen mid-drag; while frozen the last
    good layer is simply stretched, which is visually free on a soft
    gradient. The rebuild happens once, on thaw, at the final size.
    """

    def test_enter_size_move_freezes_the_layer(self, floating):
        glow = floating._glow
        floating._in_size_move = True
        glow.suspend()
        try:
            assert glow._frozen is True
            assert not glow._timer.isActive()
        finally:
            floating._in_size_move = False
            glow.resume()

    def test_a_frozen_layer_is_stretched_rather_than_rebuilt(self, floating, qapp):
        glow = floating._glow
        glow.repaint()
        original = glow._layer
        assert original is not None
        floating._in_size_move = True
        glow.suspend()
        try:
            floating.resize(1180, 800)
            glow.repaint()
            assert glow._layer is original, (
                "the orb layer was re-rasterised mid-drag — a full-window "
                "pixmap per drag step is exactly what parking prevents")
        finally:
            floating._in_size_move = False
            glow.resume()
            settle(qapp, 120)

    def test_state_change_mid_drag_does_not_unpark(self, floating):
        """Aero-snapping changes window state INSIDE the move loop; if
        _sync_window_state resumed there it would undo the parking."""
        glow = floating._glow
        floating._in_size_move = True
        glow.suspend()
        try:
            floating._sync_window_state()
            assert glow._frozen is True
            assert not glow._timer.isActive()
        finally:
            floating._in_size_move = False
            glow.resume()

    def test_exit_size_move_rebuilds_once_at_the_final_size(self, floating, qapp):
        glow = floating._glow
        floating._in_size_move = True
        glow.suspend()
        floating._in_size_move = False
        glow.resume()
        assert glow._frozen is False
        assert glow._layer is None, "thaw did not drop the stretched layer"
        assert not glow._timer.isActive(), "resume() started the frozen timer"
        glow.repaint()
        settle(qapp, 60)
        assert glow._layer_size == (glow.width(), glow.height())


def test_minimum_size_respects_the_layout_floor(window):
    """Below chrome + one minimum-width card the grid physically cannot
    lay out, so the minimum must never be set under that floor."""
    from frontend.main import CategoryPage
    floor = window._CHROME_W + CategoryPage.MIN_CARD_W
    assert window.minimumWidth() >= floor
