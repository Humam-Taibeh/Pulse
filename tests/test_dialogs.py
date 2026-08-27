"""
Modal dialog scrim geometry and compositing isolation.

PulseDialog is the ONE place translucency is still legitimate: it is a
separate top-level window that must be layered to dim the shell behind it.
These tests pin that it stays contained — the host must never become
layered — and that the scrim is square, since it now covers a square
opaque shell (a rounded scrim leaves lit wedges of shell at the corners).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication

from conftest import WINDOWS_ONLY, settle
import win32_probe as w32

pytestmark = pytest.mark.native


def _open(dialog, inspect, qapp):
    """exec() the modal and run `inspect` inside its event loop."""
    captured = {}

    def run():
        try:
            captured["result"] = inspect()
        except BaseException as exc:      # surface it after exec() unwinds
            captured["error"] = exc
        finally:
            dialog.reject()

    QTimer.singleShot(250, run)
    dialog.exec()
    qapp.processEvents()
    if "error" in captured:
        raise captured["error"]
    return captured.get("result")


@pytest.fixture
def sheet(floating):
    from frontend import widgets as W
    return W.ShortcutSheetDialog(floating, floating.theme.t, floating.SHORTCUTS)


def test_scrim_is_square_by_default(sheet):
    """The value the FIRST paint uses — refit_dialog re-asserts it, but a
    rounded default flashes two lit wedges of shell on the opening frame."""
    assert sheet._scrim_radius == 0


def test_scrim_covers_exactly_the_host_body(floating, sheet, qapp):
    def check():
        titlebar_h = floating.titlebar.height()
        origin = floating.mapToGlobal(QPoint(0, titlebar_h))
        geo = sheet.geometry()
        assert abs(geo.x() - origin.x()) <= 1
        assert abs(geo.y() - origin.y()) <= 1
        assert geo.width() == floating.width()
        assert geo.height() == floating.height() - titlebar_h

    _open(sheet, check, qapp)


def test_caption_buttons_stay_reachable_behind_a_modal(floating, sheet, qapp):
    """The scrim starts below the title bar so minimize/maximize/close
    remain visible and clickable no matter what is open."""
    def check():
        assert sheet.geometry().y() >= floating.mapToGlobal(
            QPoint(0, floating.titlebar.height())).y()

    _open(sheet, check, qapp)


def test_a_sheet_does_not_block_the_window_it_sits_on(floating, sheet, qapp):
    """VISIBLE IS NOT REACHABLE, and for two years it was only visible.

    The test above pins that the scrim starts below the title bar, which
    is what the geometry has always done — but PulseDialog also called
    setModal(True), i.e. Qt::ApplicationModal, which blocks input to every
    OTHER window in the application. The host's top-level window is one of
    those, and the title bar lives in it. Close, minimize, maximize and the
    window drag were all fully painted, hover-lit by nothing, and
    completely dead while any sheet or the command palette was open.

    Modality is the whole mechanism — Qt discards spontaneous mouse events
    for a blocked window inside QApplication::notify, before any handler
    runs — so it is also the whole test. A synthetic QTest click would not
    catch this: QTest posts non-spontaneous events, which bypass the modal
    block and "pass" against the exact bug.
    """
    def check():
        assert QApplication.activeModalWidget() is None, (
            "a sheet is application-modal again — the host's title bar is "
            "painted but cannot receive input")
        assert not sheet.isModal()
        assert floating.isEnabled(), "the host window was disabled"

    _open(sheet, check, qapp)


def test_exec_does_not_re_arm_modality(floating, sheet, qapp):
    """QDialog::exec() forces ApplicationModal unless WA_SetWindowModality
    is set, which is why the fix has to be an explicit setWindowModality()
    call and not just dropping setModal(True)."""
    from PySide6.QtCore import Qt
    seen = {}

    def check():
        seen["modality"] = sheet.windowModality()

    _open(sheet, check, qapp)
    assert seen["modality"] == Qt.WindowModality.NonModal


@WINDOWS_ONLY
def test_host_never_becomes_layered(floating, sheet, qapp):
    """The dialog is layered; that must not leak onto the main window."""
    host = w32.hwnd_of(floating)
    assert not w32.is_layered(host)

    def check():
        assert w32.is_layered(w32.hwnd_of(sheet)), (
            "the scrim needs alpha to dim — it should be layered")
        assert not w32.is_layered(host), "layering leaked onto the host"

    _open(sheet, check, qapp)
    assert not w32.is_layered(host)


@WINDOWS_ONLY
def test_scrim_has_no_sizing_frame(floating, sheet, qapp):
    """Only the main window gets WS_THICKFRAME; a resizable/snappable
    scrim would be nonsense."""
    def check():
        assert not (w32.style(w32.hwnd_of(sheet)) & w32.WS_THICKFRAME)

    _open(sheet, check, qapp)


def test_scrim_refits_when_the_host_resizes(floating, sheet, qapp):
    """PulseApp.resizeEvent -> refit_dialog keeps an open modal glued to
    the body. This depends on isinstance(active, PulseDialog) matching,
    which silently fails if the module tree is imported twice."""
    def check():
        floating.resize(1500, 950)
        settle(qapp, 200)
        geo = sheet.geometry()
        assert geo.width() == floating.width()
        assert geo.height() == floating.height() - floating.titlebar.height()
        assert sheet._scrim_radius == 0

    _open(sheet, check, qapp)


def test_stacked_modals_unwind_cleanly(floating, qapp):
    """Nested wizards each paint their own scrim over whatever is behind."""
    from frontend import widgets as W
    outer = W.ShortcutSheetDialog(floating, floating.theme.t, floating.SHORTCUTS)
    seen = {}

    def open_inner():
        inner = W.ShortcutSheetDialog(floating, floating.theme.t,
                                      floating.SHORTCUTS)

        def check_inner():
            seen["both_visible"] = inner.isVisible() and outer.isVisible()
            seen["both_square"] = (inner._scrim_radius == 0
                                   and outer._scrim_radius == 0)

        _open(inner, check_inner, qapp)
        outer.reject()

    QTimer.singleShot(250, open_inner)
    outer.exec()
    qapp.processEvents()

    assert seen.get("both_visible") is True
    assert seen.get("both_square") is True
    # Was `activeModalWidget() is None`, which is now trivially true for
    # every state including a leak — sheets are NonModal. The open-sheet
    # stack is what tracks them now, so that is what has to come back empty.
    from frontend.widgets import PulseDialog
    assert PulseDialog.open_dialogs() == [], (
        f"{len(PulseDialog.open_dialogs())} sheet(s) left registered after "
        "both were dismissed — the stack leaks, and main.resizeEvent will "
        "refit dead dialogs forever")


def test_only_the_top_sheet_answers_a_dismiss(floating, qapp):
    """Qt's modality used to make this automatic: an outer sheet simply
    never saw the event. NonModal sheets are live windows stacked on each
    other, so the ordering has to be explicit — otherwise a click or an
    Escape meant for the inner wizard dismisses the one underneath it.
    """
    from frontend import widgets as W
    outer = W.ShortcutSheetDialog(floating, floating.theme.t, floating.SHORTCUTS)
    seen = {}

    def open_inner():
        inner = W.ShortcutSheetDialog(floating, floating.theme.t,
                                      floating.SHORTCUTS)

        def check_inner():
            seen["top_is_inner"] = W.PulseDialog.topmost() is inner
            seen["outer_yields"] = not outer._is_topmost()
            seen["inner_owns"] = inner._is_topmost()

        _open(inner, check_inner, qapp)
        seen["outer_survived"] = outer.isVisible()
        outer.reject()

    QTimer.singleShot(250, open_inner)
    outer.exec()
    qapp.processEvents()

    assert seen.get("top_is_inner") is True
    assert seen.get("outer_yields") is True
    assert seen.get("inner_owns") is True
    assert seen.get("outer_survived") is True, (
        "the outer sheet closed while the inner one was up")


# ============================================================
#  THE FROSTED BACKDROP
# ============================================================
# The scrim's blur was rendered into a pixmap sized in LOGICAL pixels and
# left untagged, then magnified to fill the body on every repaint. Two
# separate defects compounded: on a 1.25x display the pixmap covered only
# 1/1.25 of the real pixels it was stretched over, and one bilinear pass
# across a 12.5x non-integer magnification reproduces the source grid as
# flat squares with hard-ish edges. That is the "chunky backdrop".
def test_the_frost_is_captured_in_device_pixels(floating, sheet, qapp):
    """THE DPR HALF. The capture must cover the real pixels it will be
    drawn over, not the logical ones — otherwise it is short by exactly the
    display's scale factor and gets stretched to cover the difference."""
    def check():
        frost = sheet._frost
        assert frost is not None, "no backdrop was captured at all"
        dpr = sheet.devicePixelRatioF()
        assert frost.width() == pytest.approx(sheet.width() * dpr, abs=2), (
            f"frost is {frost.width()}px wide for a {sheet.width()}px sheet "
            f"at {dpr}x — it was sized in logical pixels")
        assert frost.height() == pytest.approx(sheet.height() * dpr, abs=2)

    _open(sheet, check, qapp)


def test_the_frost_carries_the_display_scale(floating, sheet, qapp):
    """An untagged pixmap is treated as 1x whatever its real resolution,
    so a correctly-sized capture still gets magnified without this."""
    def check():
        assert sheet._frost.devicePixelRatio() == pytest.approx(
            sheet.devicePixelRatioF()), (
            "the frost is untagged — paintEvent will stretch it by the "
            "display's scale factor")

    _open(sheet, check, qapp)


def test_the_backdrop_is_never_magnified_at_paint_time(floating, sheet, qapp):
    """THE BLOCKINESS HALF, tested at its cause.

    A blur is allowed to be low-resolution; what it cannot be is
    low-resolution AND magnified in one bilinear pass, which is what
    renders each source texel as a visible flat tile. The resolved frost's
    LOGICAL size must equal the rect it is drawn into, so the blit is 1:1
    and there is no grid left to enlarge.

    Pinned as a ratio rather than by inspecting pixels: the tile period was
    12.5px — non-integer — so no fixed-stride image statistic samples it
    reliably, and a metric that cannot see the bug is worse than none.
    """
    def check():
        frost = sheet._frost
        logical_w = frost.width() / frost.devicePixelRatio()
        logical_h = frost.height() / frost.devicePixelRatio()
        assert logical_w == pytest.approx(sheet.width(), abs=2), (
            f"the backdrop is magnified {sheet.width() / logical_w:.2f}x at "
            "paint time — that magnification IS the chunky-tile artifact")
        assert logical_h == pytest.approx(sheet.height(), abs=2)

    _open(sheet, check, qapp)


def test_a_failed_capture_still_falls_back_to_the_flat_scrim(floating, sheet, qapp):
    """Failure stays silent and total — the flat scrim is what shipped
    before there was a blur at all, and it has no artifact."""
    def check():
        sheet._frost = None
        sheet.repaint()          # must not raise

    _open(sheet, check, qapp)


def test_host_still_interactive_after_modals(floating, sheet, qapp):
    _open(sheet, lambda: None, qapp)
    floating.open_category(0)
    qapp.processEvents()
    assert floating.stack.currentIndex() == 1
    floating.go_home()
    qapp.processEvents()
