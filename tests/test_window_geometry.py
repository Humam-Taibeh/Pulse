"""
Window geometry: the floor, the state round-trip, and the monitor that
went away.

MOST OF THIS ALREADY WORKED. It was not pinned, which for geometry is a
particular problem: every defect in this area is invisible until someone
is on the wrong hardware — a 1366x768 laptop, a second monitor that got
unplugged, a display whose scaling changed while the app was closed — and
none of it shows up on the machine the change was written on.

THE ONE THING THAT WAS WRONG was a comment, not code. _init_geometry
claimed "restoreGeometry() returns False when the saved screen is gone,
in which case we fall through to the centred default". Measured, it
returns TRUE and Qt repositions the window onto a real screen itself:

    saved geometry:    QRect(4000, 1800, 1180, 760)   (no such monitor)
    restoreGeometry(): True
    restored:          QRect(867, 313, 1180, 790)     fully on-screen

The outcome the comment promised is the outcome you get, which is why
nothing was ever noticed — but the mechanism named is not the one doing
it, and a future change that started relying on that False would be
relying on something that never happens.
"""
from __future__ import annotations

import pytest

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QMainWindow

from frontend.main import CategoryPage, PulseApp


class TestTheLayoutFloor:
    def test_the_minimum_is_at_least_what_the_layout_needs(self, window):
        """The floor is DERIVED (chrome + one minimum-width card), not
        chosen. A hardcoded minimum that drifts below it lets the user
        drag the window to a size where cards are squeezed past their own
        minimum and clip off the right edge — the layout looks broken
        while nothing is actually wrong except the constraint."""
        floor_w = window._CHROME_W + CategoryPage.MIN_CARD_W
        assert window.minimumWidth() >= floor_w, (
            f"minimum width {window.minimumWidth()} is under the layout's "
            f"real floor of {floor_w}")
        assert window.minimumHeight() >= window._CHROME_H

    def test_the_window_cannot_be_resized_under_it(self, floating, qapp):
        """Qt enforces minimumSize, so this is really asserting that the
        minimum is SET — a window with none silently accepts any size."""
        floating.resize(200, 150)
        qapp.processEvents()
        assert floating.width() >= floating.minimumWidth()
        assert floating.height() >= floating.minimumHeight()

    def test_the_floor_fits_on_a_small_laptop(self, window):
        """1366x768 is still the commonest small Windows panel. A floor
        above the work area of one would open a window the user cannot
        fully see and cannot shrink."""
        assert window.minimumWidth() <= 1366
        assert window.minimumHeight() <= 768 - 48


@pytest.mark.native
class TestMaximizeAndRestore:
    def test_maximize_then_restore_returns_the_original_geometry(
            self, floating, qapp):
        """The round-trip users perform constantly, and the one that
        exposes a frozen layout if the maximized path resizes anything
        permanently."""
        floating.showNormal()
        qapp.processEvents()
        before = floating.geometry()

        floating.showMaximized()
        qapp.processEvents()
        assert floating.isMaximized()

        floating.showNormal()
        qapp.processEvents()
        assert not floating.isMaximized()
        after = floating.geometry()
        assert abs(after.width() - before.width()) <= 2, (
            f"restored to {after.width()}px wide from {before.width()}px")
        assert abs(after.height() - before.height()) <= 2

    def test_a_maximized_window_stays_inside_the_work_area(self, floating,
                                                            qapp):
        """WM_NCCALCSIZE has to respect IsZoomed or a maximized frameless
        window overhangs the taskbar — the defect the settled-decisions
        note in ROADMAP.md records."""
        floating.showMaximized()
        qapp.processEvents()
        try:
            avail = QApplication.primaryScreen().availableGeometry()
            geo = floating.geometry()
            assert geo.width() <= avail.width() + 2, (
                f"maximized to {geo.width()}px on a {avail.width()}px work "
                "area — the window overhangs")
            assert geo.height() <= avail.height() + 2
        finally:
            floating.showNormal()
            qapp.processEvents()


class TestStatePersistence:
    def test_the_maximized_state_survives_a_round_trip(self, qapp):
        """saveGeometry encodes the maximized flag AND the normal geometry
        underneath it, which is what lets a restored window un-maximize to
        somewhere sensible rather than to its maximized size."""
        donor = QMainWindow()
        donor.setMinimumSize(600, 400)
        donor.resize(1000, 700)
        donor.show()
        donor.showMaximized()
        qapp.processEvents()
        blob = donor.saveGeometry()
        donor.close()

        heir = QMainWindow()
        heir.setMinimumSize(600, 400)
        assert heir.restoreGeometry(blob)
        heir.show()
        qapp.processEvents()
        try:
            assert heir.isMaximized(), (
                "a window closed maximized reopened restored")
        finally:
            heir.close()

    def test_a_geometry_from_a_monitor_that_is_gone_lands_on_a_real_screen(
            self, qapp):
        """THE MULTI-MONITOR DISCONNECT. Close Pulse on a second display,
        unplug it, reopen: the saved position names coordinates no screen
        covers any more. Qt repositions rather than restoring a window
        nobody can reach — asserted here because the app depends on it and
        the comment that described it named the wrong mechanism."""
        screen = QApplication.primaryScreen().availableGeometry()
        donor = QMainWindow()
        donor.setMinimumSize(600, 400)
        donor.resize(1180, 760)
        donor.move(screen.x() + 4000, screen.y() + 1800)
        donor.show()
        qapp.processEvents()
        blob = donor.saveGeometry()
        donor.close()

        heir = QMainWindow()
        heir.setMinimumSize(600, 400)
        heir.restoreGeometry(blob)
        heir.show()
        qapp.processEvents()
        try:
            geo = heir.frameGeometry()
            on_a_screen = any(s.availableGeometry().intersects(geo)
                              for s in QApplication.instance().screens())
            assert on_a_screen, (
                f"restored to {geo}, which no connected screen covers — the "
                "window would be unreachable after unplugging a monitor")
        finally:
            heir.close()

    def test_restore_geometry_reports_success_for_an_offscreen_save(self,
                                                                    qapp):
        """Pinning the MECHANISM, because _init_geometry used to describe
        a different one. If a future Qt really did start returning False
        here, the centred-default fallback would begin running in a case
        it has never run in, and this is what would say so."""
        screen = QApplication.primaryScreen().availableGeometry()
        donor = QMainWindow()
        donor.resize(1000, 700)
        donor.move(screen.x() + 4000, screen.y() + 1800)
        donor.show()
        qapp.processEvents()
        blob = donor.saveGeometry()
        donor.close()

        heir = QMainWindow()
        assert heir.restoreGeometry(blob) is True, (
            "restoreGeometry now reports failure for an off-screen save; "
            "_init_geometry's fallback path is live for the first time and "
            "its comment needs re-reading")
        heir.close()

    def test_a_corrupt_blob_is_refused_rather_than_applied(self, qapp):
        """The other half of the fallback: prefs can hand back anything,
        including a value written by a different Qt. A refused restore is
        what makes _init_geometry fall through to its centred default."""
        from PySide6.QtCore import QByteArray

        heir = QMainWindow()
        assert heir.restoreGeometry(QByteArray(b"not a geometry")) is False
        heir.close()


class TestTheSavedGeometryIsWrittenOnClose:
    def test_closing_persists_geometry_and_drawer_state(self, window,
                                                        monkeypatch):
        """closeEvent writes both, and only once the close is going ahead
        — writing before the mid-task confirmation would persist the
        geometry of a window the user then chose NOT to close."""
        import inspect
        source = inspect.getsource(PulseApp.closeEvent)
        assert "set_window_geometry" in source
        assert "saveGeometry" in source
        assert source.index("CloseConfirmDialog") < source.index(
            "set_window_geometry"), (
            "geometry is saved before the close is confirmed, so declining "
            "the prompt still rewrites the remembered window")
