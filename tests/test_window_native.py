"""
Native window integration — the contract between Pulse's frameless window
and Windows itself.

Regression origin: every edge and corner answered WM_NCHITTEST correctly
for months, and the window still could not be resized by dragging, because
Qt's FramelessWindowHint builds a bare WS_POPUP with no sizing border and
DefWindowProc simply refuses to run the size loop for one. Hit-test
assertions alone would have stayed green through that entire bug, so
is_sizable() is tested as its own first-class invariant.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint

from conftest import WINDOWS_ONLY, settle
import win32_probe as w32

pytestmark = [WINDOWS_ONLY, pytest.mark.native]


def test_window_has_a_real_sizing_frame(floating):
    """WS_THICKFRAME is what makes the hit-tests below mean anything."""
    hwnd = w32.hwnd_of(floating)
    assert w32.style(hwnd) & w32.WS_THICKFRAME, (
        "WS_THICKFRAME missing — Windows will ignore every resize hit-test")


def test_windows_reports_the_window_as_sizable(floating):
    """The invariant the old bug violated while all hit-tests passed."""
    assert w32.is_sizable(w32.hwnd_of(floating)), (
        "SC_SIZE greyed out — the OS will not start a resize loop")


def test_sizing_frame_is_never_drawn(floating, qapp):
    """WM_NCCALCSIZE must collapse the non-client area: the frame exists
    for the OS, not for the eye. If it were drawn we'd lose a border-and-
    caption strip out of our own chrome."""
    hwnd = w32.hwnd_of(floating)
    rect = w32.window_rect(hwnd)
    assert w32.client_size(hwnd) == (rect.right - rect.left,
                                     rect.bottom - rect.top)


@pytest.mark.parametrize("zone", [
    "LEFT", "RIGHT", "TOP", "BOTTOM",
    "TOPLEFT", "TOPRIGHT", "BOTTOMLEFT", "BOTTOMRIGHT",
])
def test_all_eight_resize_zones_hit_test(floating, zone):
    """All 4 edges and all 4 corners, so a cursor there gets the native
    resize arrow and starts the OS size loop."""
    hwnd = w32.hwnd_of(floating)
    points = w32.edge_points(w32.window_rect(hwnd))
    x, y = points[zone]
    assert w32.hit_name(hwnd, x, y) == zone


def test_titlebar_is_native_caption(floating):
    """HTCAPTION is what gives OS-driven dragging, Aero Snap and
    double-click maximize — and it keeps working while a modal is open."""
    hwnd = w32.hwnd_of(floating)
    points = w32.edge_points(w32.window_rect(hwnd))
    assert w32.hit_name(hwnd, *points["CAPTION"]) == "CAPTION"


def test_body_is_client_area(floating):
    hwnd = w32.hwnd_of(floating)
    points = w32.edge_points(w32.window_rect(hwnd))
    assert w32.hit_name(hwnd, *points["CLIENT"]) == "CLIENT"


@pytest.mark.parametrize("role,expected", [
    ("min", "MINBUTTON"), ("max", "MAXBUTTON"), ("close", "CLOSE"),
])
def test_caption_buttons_are_non_client(floating, role, expected):
    """Windows owns these three; HTMAXBUTTON is also what summons the
    Windows 11 Snap Layouts flyout."""
    hwnd = w32.hwnd_of(floating)
    rect = w32.window_rect(hwnd)
    btn = floating.titlebar.caption_buttons()[role]
    dpr = floating.devicePixelRatioF()
    centre = btn.mapTo(floating, btn.rect().center())
    x = rect.left + round(centre.x() * dpr)
    y = rect.top + round(centre.y() * dpr)
    assert w32.hit_name(hwnd, x, y) == expected


def test_the_caption_strip_has_no_client_holes_left(floating):
    """THIS TEST USED TO ASSERT THE OPPOSITE, and the inversion records a
    decision rather than a fix.

    It shipped as `test_theme_toggle_stays_a_client_hole`: the theme
    toggle was an ordinary Qt button living inside the title bar, so the
    HTCAPTION strip had to leave a hand-measured hole over it or the
    button became dead chrome. That hole was real work —
    `PulseApp._over_theme_button`, DPI-aware physical-pixel mapping that
    had to track the button's geometry — and it was a standing hazard: a
    drag strip with a hole in it develops a dead spot the moment a
    neighbouring control moves and nothing re-measures.

    v15 moved the toggle into the sidebar's status rail (widgets.
    StatusRail) with the rest of the session chrome, so the strip is
    uniform again. What is asserted now is that it STAYS uniform: every
    pixel of the title bar that is not one of the three caption buttons
    answers HTCAPTION, all the way to the brand block on the left.
    """
    hwnd = w32.hwnd_of(floating)
    rect = w32.window_rect(hwnd)
    dpr = floating.devicePixelRatioF()
    titlebar = floating.titlebar
    y = rect.top + round((titlebar.height() // 2) * dpr)
    # sample across the strip, stopping well short of the caption cluster
    left_edge = titlebar.caption_buttons()["min"].mapTo(
        floating, QPoint(0, 0)).x()
    for frac in (0.05, 0.2, 0.4, 0.6, 0.8):
        x = rect.left + round((left_edge * frac) * dpr)
        assert w32.hit_name(hwnd, x, y) == "CAPTION", (
            f"the title-bar strip is not draggable at x={x} — a client "
            "hole has come back")


def test_resize_loop_clamps_to_the_layout_floor(floating):
    """The OS size loop must honour the minimum the grid actually needs,
    or a drag can squeeze cards past their minimum and clip them."""
    hwnd = w32.hwnd_of(floating)
    dpr = floating.devicePixelRatioF()
    track_w, track_h = w32.min_track_size(hwnd)
    assert abs(track_w - round(floating.minimumWidth() * dpr)) <= 2
    assert abs(track_h - round(floating.minimumHeight() * dpr)) <= 2


class TestMaximized:
    """A maximized window must behave exactly like a native one: no resize
    border, content stopping at the work area, and caption zones reaching
    the literal screen corner."""

    @pytest.fixture(autouse=True)
    def maximized(self, floating, qapp):
        floating.showMaximized()
        settle(qapp, 400)
        yield floating

    def test_client_matches_work_area(self, maximized, qapp):
        """A maximized custom-frame window's client area must land exactly
        on the work area — not over the taskbar, not short of it.

        The docstring here used to credit an IsZoomed() test in
        WM_NCCALCSIZE for insetting the frame. That was wrong: traced live,
        IsZoomed() returns False for every NCCALCSIZE of a maximize (the
        message is part of the transition that sets WS_MAXIMIZE), so the
        inset never ran and this passed only because Qt's maximize path
        proposes the work area exactly. The handler now clamps instead —
        see main.clamp_maximized_client — which is a no-op on that path and
        a correction on any path that proposes an oversized rect. The
        assertion is unchanged because the required OUTCOME never was."""
        from PySide6.QtGui import QGuiApplication
        hwnd = w32.hwnd_of(maximized)
        avail = QGuiApplication.primaryScreen().availableGeometry()
        dpr = maximized.devicePixelRatioF()
        cw, ch = w32.client_size(hwnd)
        assert abs(cw - round(avail.width() * dpr)) <= 4
        assert abs(ch - round(avail.height() * dpr)) <= 4

    def test_no_resize_border_when_maximized(self, maximized):
        hwnd = w32.hwnd_of(maximized)
        rect = w32.window_rect(hwnd)
        assert w32.hit_name(hwnd, rect.left + 2,
                            (rect.top + rect.bottom) // 2) != "LEFT"

    def test_corner_slam_closes(self, maximized):
        """Fitts's law: slamming into the top-right screen corner must hit
        Close, which is only true if the caption zone reaches the edge."""
        hwnd = w32.hwnd_of(maximized)
        rect = w32.window_rect(hwnd)
        assert w32.hit_name(hwnd, rect.right - 2, rect.top + 1) == "CLOSE"


def test_resize_borders_return_after_restore(floating, qapp):
    """Round-trip: maximize then restore must give the borders back."""
    floating.showMaximized()
    settle(qapp, 400)
    floating.showNormal()
    settle(qapp, 500)
    hwnd = w32.hwnd_of(floating)
    assert not w32.is_zoomed(hwnd)
    points = w32.edge_points(w32.window_rect(hwnd))
    assert w32.hit_name(hwnd, *points["LEFT"]) == "LEFT"
    assert w32.hit_name(hwnd, *points["BOTTOMRIGHT"]) == "BOTTOMRIGHT"


class TestMaximizedClamp:
    """main.clamp_maximized_client — the WM_NCCALCSIZE geometry rule.

    Unit-tested against a synthetic rect and an injected work area, so it
    runs on any machine: the states that matter (a window Windows oversized
    on maximize, a window dragged off the left edge) are awkward to stage
    against a real desktop and trivial to state directly.
    """

    class _Rect:
        """Stands in for ctypes RECT — the clamp only reads/writes fields."""

        def __init__(self, left, top, right, bottom):
            self.left, self.top = left, top
            self.right, self.bottom = right, bottom

        def astuple(self):
            return (self.left, self.top, self.right, self.bottom)

    WORK = (0, 0, 2560, 1380)      # 2560x1440 monitor, 60px taskbar

    def _clamp(self, rect):
        from frontend.main import clamp_maximized_client
        return clamp_maximized_client(0, rect, work=self.WORK)

    def test_an_oversized_maximized_rect_is_trimmed_to_the_work_area(self):
        """THE CASE THE OLD IsZoomed() BRANCH WAS MEANT TO CATCH. A
        maximized WS_THICKFRAME window is normally oversized by the frame
        on every side; a custom frame keeping client == window then hangs
        content off all four monitor edges and over the taskbar."""
        rect = self._Rect(-9, -9, 2569, 1389)
        assert self._clamp(rect) is True
        assert rect.astuple() == self.WORK, (
            "an oversized maximized rect was not pulled back to the work area")

    def test_a_rect_already_equal_to_the_work_area_is_left_alone(self):
        """Qt's own maximize path proposes exactly this, and the previous
        implementation's blind frame inset would have carved a ~9px gap out
        of a window that was already correct."""
        rect = self._Rect(*self.WORK)
        assert self._clamp(rect) is False
        assert rect.astuple() == self.WORK

    def test_a_floating_window_dragged_off_screen_is_not_clamped(self):
        """The guard: covering the work area on ALL FOUR sides is what
        distinguishes maximized from merely off-screen. Clamping this would
        trap the window on the desktop and squeeze its client area."""
        rect = self._Rect(-200, 100, 900, 800)   # hangs off the left
        assert self._clamp(rect) is False
        assert rect.astuple() == (-200, 100, 900, 800)

    def test_an_ordinary_floating_rect_is_not_clamped(self):
        rect = self._Rect(188, 125, 1693, 1080)
        assert self._clamp(rect) is False
        assert rect.astuple() == (188, 125, 1693, 1080)

    def test_an_unavailable_work_area_does_nothing(self):
        """monitor_work_area returns None off-Windows or on a failed query,
        and 'do nothing' is the only safe reading of that."""
        from frontend.main import clamp_maximized_client

        rect = self._Rect(-9, -9, 2569, 1389)
        assert clamp_maximized_client(0, rect, work=None) is False
        assert rect.astuple() == (-9, -9, 2569, 1389)
