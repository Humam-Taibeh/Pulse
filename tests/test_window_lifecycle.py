"""
tests/test_window_lifecycle.py

THE SHEETS FOLLOW THE WINDOW THROUGH EVERY STATE, not just through a
drag.

tests/test_window_sync.py pinned the MOVE and the RESIZE: a Pulse sheet is
a frameless top-level window positioned in screen coordinates, nothing in
Qt moves a second top-level window when the first one moves, and so
PulseApp has to re-anchor its open sheets by hand. This file is the rest
of that family — the state changes and the display changes that the same
architecture leaves equally unhandled.

TWO DEFECTS, both measured against the shipped code before anything was
written to fix them:

  MINIMIZE ORPHANS THE SHEET. `window.showMinimized()` with the catalog
  open left the sheet `isVisible() == True` at its original coordinates.
  The app vanished from the screen and a lone frosted panel stayed behind,
  floating over the desktop with no title bar, no taskbar entry and
  nothing underneath it. Qt does not minimize a second top-level window
  with the first, and FramelessWindowHint means Windows draws no owner
  relationship that would do it either.

  A SCALE CHANGE LEAVES THE SHEET RENDERED FOR THE OLD DISPLAY. The
  screen-change handler dropped the icon cache and re-applied the theme,
  which covers the pages — and a sheet is not on a page. Its geometry, its
  frost (a pixmap captured at the old device-pixel ratio) and its row
  marks were all left as they were. Worse, the handler was reachable only
  from `screenChanged`, so changing the scaling of the monitor Pulse was
  ALREADY on — the case a user produces deliberately, in Settings —
  emitted `logicalDotsPerInchChanged` and nothing was listening.

WHAT IS DELIBERATELY NOT HERE: Aero Snap. Snapping changes the window
state inside Windows' move/size loop, but it also changes the GEOMETRY, so
resizeEvent fires and refits every open sheet through the path
test_window_sync.py already pins. The state change only needs its own
handling when it crosses into or out of minimized, which is what
_sync_sheet_visibility reads.
"""
from __future__ import annotations

import pytest

from conftest import settle, show_dialog


def _open_palette(window, qapp):
    from frontend.menu_structure import iter_leaf_items
    from frontend.widgets import CommandPalette

    palette = CommandPalette(window, window.theme.t, list(iter_leaf_items()))
    show_dialog(qapp, palette)
    return palette


def _body_origin(window):
    """Where a correctly-anchored sheet's top-left belongs, in screen
    coordinates — the same answer widgets._host_body_rect gives."""
    from PySide6.QtCore import QPoint
    return window.mapToGlobal(QPoint(0, window.titlebar.height()))


@pytest.fixture
def sheet(floating, qapp):
    palette = _open_palette(floating, qapp)
    yield palette
    # Un-park before closing: a parked sheet is hidden and still
    # registered, and leaving one behind would follow the session-scoped
    # window into the next test.
    palette._parked = False
    palette.reject()
    palette.deleteLater()
    settle(qapp, 40)


# ============================================================
#  MINIMIZE / RESTORE
# ============================================================
class TestSheetsFollowTheWindowDown:

    def test_minimizing_the_window_takes_the_sheet_with_it(
            self, floating, qapp, sheet):
        """THE DEFECT. The sheet stayed on screen over the desktop."""
        assert sheet.isVisible(), "precondition: the sheet is up"

        floating.showMinimized()
        settle(qapp, 300)

        assert not sheet.isVisible(), (
            "the shell minimized and the sheet stayed on screen — an "
            "orphan frosted panel floating over the desktop with no "
            "window behind it")

    def test_restoring_the_window_brings_the_sheet_back(
            self, floating, qapp, sheet):
        """The other half, and the half that makes parking safe: a sheet
        that went down must come back, or the user has lost a wizard they
        never cancelled — with its exec() loop still running."""
        floating.showMinimized()
        settle(qapp, 300)
        floating.showNormal()
        settle(qapp, 300)

        assert sheet.isVisible(), "the sheet did not come back with the window"
        assert sheet.pos() == _body_origin(floating), (
            "the sheet came back at stale coordinates")

    def test_a_parked_sheet_is_still_an_open_sheet(
            self, floating, qapp, sheet):
        """`_OPEN` answers "what is open", and a wizard whose window was
        minimized is still open — nothing was cancelled. Deregistering it
        would drop the only reference that can restore it."""
        floating.showMinimized()
        settle(qapp, 300)
        try:
            from frontend.widgets import PulseDialog
            assert sheet in PulseDialog.open_dialogs(), (
                "hideEvent deregistered a merely-parked sheet, so nothing "
                "can bring it back")
            assert sheet.is_parked()
            assert sheet in PulseDialog.parked_dialogs()
        finally:
            floating.showNormal()
            settle(qapp, 300)

    def test_a_closed_sheet_does_not_come_back_on_restore(
            self, floating, qapp):
        """The failure mode parking could introduce: a sheet the user
        actually dismissed must stay dismissed, rather than being
        resurrected by the next minimize/restore cycle."""
        from frontend.widgets import PulseDialog

        palette = _open_palette(floating, qapp)
        palette.reject()
        settle(qapp, 60)
        assert palette not in PulseDialog.open_dialogs()

        floating.showMinimized()
        settle(qapp, 250)
        floating.showNormal()
        settle(qapp, 250)

        assert not palette.isVisible(), (
            "a dismissed sheet was restored — reject() is being treated "
            "as a park")
        palette.deleteLater()
        settle(qapp, 40)

    def test_every_open_sheet_parks_not_only_the_topmost(
            self, floating, qapp):
        """Sheets nest, and each paints its own full-body scrim. Parking
        only the top one would leave the sheet behind it on the desktop —
        the same orphan, one layer down."""
        from frontend.widgets import ConfirmDialog

        outer = _open_palette(floating, qapp)
        inner = ConfirmDialog(
            floating,
            {"icon": "🧪", "title": "Nested", "desc": "Second sheet."},
            floating.theme.t)
        show_dialog(qapp, inner)
        try:
            floating.showMinimized()
            settle(qapp, 300)
            assert not inner.isVisible(), "the topmost sheet stayed up"
            assert not outer.isVisible(), (
                "the sheet UNDERNEATH stayed on the desktop — open_dialogs() "
                "is being narrowed to the top of the stack somewhere")

            floating.showNormal()
            settle(qapp, 300)
            assert inner.isVisible() and outer.isVisible(), (
                "both sheets must come back, not just one")
        finally:
            for dialog in (inner, outer):
                dialog._parked = False
                dialog.reject()
                dialog.deleteLater()
            settle(qapp, 40)

    def test_parking_is_idempotent(self, floating, qapp, sheet):
        """Windows emits more than one WindowStateChange for a single
        minimize on some machines, and `showMinimized()` on an already
        minimized window emits another. A second park must not hide a
        sheet the first one already hid and lose the flag."""
        floating.showMinimized()
        settle(qapp, 250)
        sheet.park()          # the extra event, delivered by hand
        sheet.park()
        try:
            assert sheet.is_parked()
        finally:
            floating.showNormal()
            settle(qapp, 250)
        assert sheet.isVisible()
        assert not sheet.is_parked()


# ============================================================
#  DPI / MULTI-MONITOR
# ============================================================
class TestSheetsSurviveAScaleChange:

    def test_the_window_listens_for_a_scale_change_on_its_own_screen(
            self, floating, qapp):
        """screenChanged fires when the window MOVES to another monitor. It
        does not fire when the monitor Pulse is already on is rescaled in
        Settings — that is logicalDotsPerInchChanged, on the QScreen, and
        nothing was subscribed to it."""
        assert floating.windowHandle() is not None
        assert floating._dpi_screen is not None, (
            "PulseApp never subscribed to any screen's "
            "logicalDotsPerInchChanged, so re-scaling the display Pulse is "
            "sitting on leaves every ratio-baked pixmap rendered for the "
            "old scale")
        assert floating._dpi_screen is floating.windowHandle().screen(), (
            "the DPI subscription is on a different screen from the one "
            "the window is on")

    def test_the_dpi_subscription_moves_with_the_window(
            self, floating, qapp):
        """logicalDotsPerInchChanged belongs to a QScreen, not to the
        application. Staying subscribed to the old monitor after a move
        reports changes to a display Pulse is not on and misses changes to
        the one it is."""
        original = floating._dpi_screen
        floating._dpi_screen = None          # pretend we were on nothing
        floating._watch_screen_dpi()
        assert floating._dpi_screen is floating.windowHandle().screen()
        assert floating._dpi_screen is original

    def test_a_scale_change_refits_every_open_sheet(
            self, floating, qapp, sheet):
        """A sheet is a separate top-level window that _apply_theme does
        not walk, so nothing re-fitted it to the host's body after the
        logical size of that body changed."""
        # Move the sheet somewhere wrong, then prove the handler puts it
        # back — the same technique test_window_sync uses for the drag.
        sheet.move(sheet.x() + 140, sheet.y() + 90)
        sheet.resize(320, 240)
        settle(qapp, 40)

        floating._on_screen_changed(None)
        settle(qapp, 120)

        assert sheet.pos() == _body_origin(floating), (
            "the open sheet was not re-anchored after a scale change")
        assert sheet.width() == floating.width()
        assert sheet.height() == (
            floating.height() - floating.titlebar.height())

    def test_a_scale_change_recaptures_the_sheet_backdrop(
            self, floating, qapp, sheet):
        """The frost is a pixmap captured at the OLD device-pixel ratio and
        blitted 1:1. Left alone across a scale change, Qt resamples it —
        the soft-backdrop defect, arriving by a different route."""
        stale = object()
        sheet._frost = stale

        floating._on_screen_changed(None)
        settle(qapp, 150)

        assert sheet._frost is not stale, (
            "the sheet kept a backdrop captured for the previous display")

    def test_a_scale_change_redraws_the_ratio_baked_row_marks(
            self, floating, qapp):
        """appicons.app_icon rasterises at the screen's ratio and the row
        holds the result. A fresh LOOKUP after a scale change is already
        correct; nothing was asking for one."""
        from frontend import menu_structure as MS
        from frontend.widgets import DevHubRow, SoftwareCatalogDialog

        section = MS.catalog_section("runtimes")
        item = {"icon": "🧱", "title": "Runtimes & Hardware Drivers"}
        catalog = SoftwareCatalogDialog(
            floating, item, floating.theme.t, [section])
        show_dialog(qapp, catalog)
        try:
            rows = catalog.findChildren(DevHubRow)
            assert rows, "no rows to check"
            assert all(getattr(r, "RATIO_BAKED", False) for r in rows), (
                "DevHubRow stopped declaring RATIO_BAKED, so "
                "PulseDialog.rescale_marks can no longer find the marks "
                "it exists to redraw")

            redrawn = []
            for row in rows:
                row.apply_theme = (
                    lambda t, _r=row: redrawn.append(_r))   # type: ignore[method-assign]

            floating._on_screen_changed(None)
            settle(qapp, 150)

            assert len(redrawn) == len(rows), (
                f"{len(redrawn)} of {len(rows)} row marks were re-rasterised "
                "— the rest are still drawn for the previous display")
        finally:
            catalog._parked = False
            catalog.reject()
            catalog.deleteLater()
            settle(qapp, 60)

    def test_a_scale_change_still_drops_the_icon_cache(
            self, floating, qapp):
        """The behaviour that already worked, kept beside the new one so a
        later tidy-up cannot drop it while moving the handler around. The
        cache is keyed on the ratio, so a stale entry is harmless — but
        without the clear, moving back and forth finds the pre-move entry
        valid and skips the re-render."""
        from utils import appicons

        appicons.app_icon("Some App For This Test", 24,
                          {"name": "dark", "dialog_bg": "#16181d"})
        assert appicons._PIXMAP_CACHE, "nothing cached; test proves nothing"

        floating._on_screen_changed(None)
        settle(qapp, 120)

        assert not appicons._PIXMAP_CACHE, (
            "the icon cache survived a scale change")

    def test_it_is_inert_while_shutting_down(self, floating, qapp):
        """A screen change during teardown must not re-apply a theme to
        widgets that are being destroyed."""
        floating._shutting_down = True
        try:
            floating._on_screen_changed(None)   # must not raise
        finally:
            floating._shutting_down = False
