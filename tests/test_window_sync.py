"""
tests/test_window_sync.py

THE SHELL AND ITS SHEETS ARE ONE FRAME.

Every Pulse modal — the Ctrl+K command palette, the Software Catalog, a
wizard — is a frameless TOP-LEVEL window positioned in SCREEN coordinates,
not a child widget of the shell. That is a deliberate design (see
widgets.PulseDialog): a top-level sheet can paint its own scrim across the
body while leaving the title bar live underneath, which a child widget
covering the same pixels could not do.

The cost is that nothing in Qt moves a second top-level window when the
first one moves. PulseApp.resizeEvent has re-anchored open sheets for as
long as sheets have existed, and there was no moveEvent at all — so
dragging the shell left every open sheet nailed to the coordinates it
opened at, visibly sliding out of the application and over the desktop.
The palette showed it worst because it is the surface most likely to be
open while the window is being placed, but it was never palette-specific.

These tests assert the whole contract in both directions: a sheet tracks
the window through a MOVE and through a RESIZE, every open sheet tracks it
rather than only the topmost, and a move does not pay for the resize work.
"""
from __future__ import annotations

import pytest

from conftest import settle, show_dialog


def _open_palette(window, qapp):
    """A real CommandPalette on the shared window — the surface the defect
    was reported against."""
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
def palette(floating, qapp):
    sheet = _open_palette(floating, qapp)
    yield sheet
    sheet.reject()
    sheet.deleteLater()
    settle(qapp, 40)


class TestSheetsFollowTheWindow:

    def test_a_sheet_is_anchored_to_the_body_when_it_opens(
            self, floating, qapp, palette):
        """The baseline the move has to preserve. If this is wrong, every
        assertion below is measuring the wrong thing."""
        assert palette.pos() == _body_origin(floating)

    def test_a_sheet_follows_the_window_when_it_moves(
            self, floating, qapp, palette):
        """THE DEFECT. Drag the shell; the sheet stayed where it opened.

        Asserted as a DELTA as well as an absolute position: a sheet that
        happened to be re-anchored by some unrelated refit would pass the
        absolute check while still lagging a drag."""
        before = palette.pos()
        start = floating.pos()

        floating.move(start.x() + 90, start.y() + 70)
        settle(qapp, 60)

        moved = palette.pos() - before
        assert (moved.x(), moved.y()) == (90, 70), (
            f"the window moved by (90, 70) and the sheet moved by "
            f"({moved.x()}, {moved.y()}) — it is not tracking the shell")
        assert palette.pos() == _body_origin(floating)

    def test_a_move_does_not_resize_the_sheet(
            self, floating, qapp, palette):
        """A translation changes no dimension, and reanchor_dialog exists
        precisely so a drag does not pay for the panel re-measurement a
        refit performs on every step."""
        size = palette.size()
        panel = palette.panel.size()
        start = floating.pos()

        floating.move(start.x() + 55, start.y() - 35)
        settle(qapp, 60)

        assert palette.size() == size
        assert palette.panel.size() == panel

    def test_the_sheet_still_follows_a_resize(self, floating, qapp, palette):
        """The half that already worked. Kept beside the new one so a
        future tidy-up cannot delete the resize path while 'simplifying'
        the move path into it."""
        floating.resize(1180, 780)
        settle(qapp, 80)

        assert palette.pos() == _body_origin(floating)
        assert palette.width() == floating.width()
        assert palette.height() == (
            floating.height() - floating.titlebar.height())

    def test_every_open_sheet_follows_not_only_the_topmost(
            self, floating, qapp):
        """Sheets nest — a wizard opened from a wizard — and each paints
        its own full-body scrim. Re-anchoring only the top one would leave
        the sheet behind it hanging off the window, visible around the
        edges of the one in front."""
        from frontend.widgets import ConfirmDialog

        outer = _open_palette(floating, qapp)
        inner = ConfirmDialog(
            floating,
            {"icon": "🧪", "title": "Nested",
             "desc": "Second sheet, on top."},
            floating.theme.t)
        show_dialog(qapp, inner)
        try:
            start = floating.pos()
            floating.move(start.x() + 64, start.y() + 48)
            settle(qapp, 60)

            anchor = _body_origin(floating)
            assert inner.pos() == anchor, "the topmost sheet did not follow"
            assert outer.pos() == anchor, (
                "the sheet UNDERNEATH stayed behind — open_dialogs() is "
                "being narrowed to the top of the stack somewhere")
        finally:
            inner.reject()
            outer.reject()
            inner.deleteLater()
            outer.deleteLater()
            settle(qapp, 40)


def test_the_window_reanchors_through_the_shared_helper(floating, qapp,
                                                        monkeypatch):
    """moveEvent must go through widgets.reanchor_dialog rather than
    re-deriving the anchor inline.

    The anchor is computed from the host's title-bar height, and the app
    has had two copies of that arithmetic drift apart before. This pins
    that the move path and the fit path read the same helper."""
    from frontend import main as M

    calls = []
    monkeypatch.setattr(M, "reanchor_dialog", lambda sheet: calls.append(sheet))

    sheet = _open_palette(floating, qapp)
    try:
        start = floating.pos()
        floating.move(start.x() + 25, start.y() + 25)
        settle(qapp, 60)
        assert sheet in calls, (
            "PulseApp.moveEvent did not route the open sheet through "
            "reanchor_dialog")
    finally:
        sheet.reject()
        sheet.deleteLater()
        settle(qapp, 40)


def test_no_open_sheet_means_a_move_is_free(floating, qapp):
    """A window with nothing open must not fault, allocate a sheet list it
    then throws away, or otherwise make a plain drag expensive."""
    start = floating.pos()
    floating.move(start.x() + 12, start.y() + 12)
    settle(qapp, 40)
    assert floating.pos().x() == start.x() + 12
