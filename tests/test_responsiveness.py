"""
Two blocking/scaling defects that only appear on a real machine.

1. THE STOP BUTTON FROZE THE WINDOW.
   PowerShellTask.cancel() is called DIRECTLY from the GUI thread — that
   is deliberate and documented (the worker is blocked on its stdout pipe
   and cannot service a queued call). What was not considered is that
   cancel() then runs `taskkill /T /F` through subprocess.run with NO
   timeout, synchronously, on that same GUI thread. The Job Object has
   already terminated the tree by then, so taskkill is the fallback and
   normally returns in well under a second — but "normally" is not a
   bound, and an unbounded wait on the GUI thread is a frozen window with
   the Stop button still reading "Stop Task" (its own "Stopping…" repaint
   cannot land until control returns to the event loop).

   The same call sits in the shutdown path: closeEvent ->
   _settle_background_threads -> cancel(). That path budgets a documented
   3000ms grace for the thread join, and an unbounded taskkill in front of
   it can blow that budget entirely.

2. EVERY VENDOR ICON WAS RASTERISED FOR A 200% DISPLAY.
   appicons rendered marks at exactly px*2 and stamped
   setDevicePixelRatio(2.0), regardless of the screen. On 125/150/175% —
   the common Windows laptop scalings — Qt then resamples 2.0 down to a
   non-integer ratio, which is precisely the softness v10.9.3 called
   unacceptable when it fixed the search glyph ("a 15px pixmap handed to a
   150% display is upscaled by Qt, and a soft magnifier beside crisp text
   is a worse defect than the emoji was"). The marks are SVG, so rendering
   at the screen's real ratio is lossless and costs nothing.
"""
from __future__ import annotations

import subprocess

import pytest

from PySide6.QtGui import QColor

from utils import appicons
from utils.helpers import PowerShellTask


# ============================================================
#  1. THE KILL PATH IS BOUNDED
# ============================================================
class _FakeProcess:
    """Enough of subprocess.Popen for _kill_process_tree."""

    pid = 4242

    def __init__(self):
        self.killed = False

    def poll(self):
        return None       # still running, so the kill path runs in full

    def kill(self):
        self.killed = True


def test_the_taskkill_fallback_is_bounded(monkeypatch):
    """An unbounded subprocess.run here is an unbounded freeze of whichever
    thread called cancel() — and that is always the GUI thread."""
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    task = PowerShellTask("core.ps1", "Noop")
    task._kill_process_tree(_FakeProcess())

    assert "taskkill.exe" in seen["argv"][0].lower()
    assert seen["timeout"] is not None, (
        "taskkill runs with no timeout — a hung kill freezes the GUI thread "
        "for as long as it hangs")
    assert 0 < seen["timeout"] <= 5, (
        f"a {seen['timeout']}s bound is too loose to keep the window "
        "responsive; the Job Object has already terminated the tree")


def test_a_hung_taskkill_does_not_escape_into_the_gui_thread(monkeypatch):
    """Bounding the call introduces TimeoutExpired, which the existing
    handler (OSError only) would not have caught — so the bound alone would
    have converted a freeze into an exception raised inside closeEvent."""
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 1))

    monkeypatch.setattr(subprocess, "run", fake_run)
    task = PowerShellTask("core.ps1", "Noop")
    process = _FakeProcess()

    task._kill_process_tree(process)       # must not raise

    assert process.killed, (
        "when taskkill times out, the direct process.kill() fallback must "
        "still run — otherwise the bound trades a freeze for a survivor")


def test_cancel_survives_a_hung_taskkill(monkeypatch):
    """The whole point, at the layer the GUI actually calls."""
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 1))

    monkeypatch.setattr(subprocess, "run", fake_run)
    task = PowerShellTask("core.ps1", "Noop")
    task._process = _FakeProcess()

    task.cancel()       # must not raise into closeEvent / the Stop button

    assert task._cancel_evt.is_set()


# ============================================================
#  2. ICONS FOLLOW THE SCREEN, NOT A HARDCODED 2.0
# ============================================================
@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 1.75, 2.0, 3.0])
def test_a_mark_is_rasterised_for_the_screen_it_lands_on(qapp, monkeypatch, dpr):
    """The pixmap's own ratio must match the screen's, and its device size
    must follow from it — otherwise Qt resamples every icon in the catalog
    on any display that is not exactly 200%."""
    monkeypatch.setattr(appicons, "_screen_dpr", lambda: dpr)
    pm = appicons._neutral_pixmap(24, QColor("#8a9edb"))

    assert pm.devicePixelRatio() == pytest.approx(dpr), (
        f"the mark claims {pm.devicePixelRatio()} on a {dpr} screen")
    assert pm.width() == round(24 * dpr), (
        f"{pm.width()}px of detail for a {round(24 * dpr)}px slot — Qt has "
        "to resample it")
    # The logical size is what the layout sees, and it must not move.
    assert pm.width() / pm.devicePixelRatio() == pytest.approx(24, abs=1)


def test_the_icon_cache_is_keyed_on_the_ratio(qapp, monkeypatch):
    """A cache keyed on (id, name, px, theme) alone hands a pixmap
    rasterised for the OLD screen back after the window is dragged to a
    monitor with different scaling — the icons go soft and stay soft until
    the app restarts."""
    appicons._PIXMAP_CACHE.clear()
    theme = {"name": "dark", "dialog_bg": "#16181d"}

    monkeypatch.setattr(appicons, "_screen_dpr", lambda: 1.0)
    first = appicons.app_icon("Some Unbundled App", 24, theme)
    monkeypatch.setattr(appicons, "_screen_dpr", lambda: 2.0)
    second = appicons.app_icon("Some Unbundled App", 24, theme)

    assert first.devicePixelRatio() == pytest.approx(1.0)
    assert second.devicePixelRatio() == pytest.approx(2.0), (
        "the second screen got the first screen's pixmap back")


def test_the_generic_shell_key_matches_the_size_it_is_compared_against(
        qapp, monkeypatch):
    """_generic_shell_key caches ONE key for the first px it ever sees, and
    _shell_pixmap compares raw bytes against it. Two different device sizes
    can never compare equal, so the moment the requested size follows the
    screen, Windows' blank-page placeholder stops being rejected and starts
    being shown as though it were the app's own icon."""
    appicons._GENERIC_KEYS.clear()
    small = appicons._generic_shell_key(32)
    large = appicons._generic_shell_key(96)

    if small is None or large is None:
        pytest.skip("no shell icon provider on this machine")
    assert small != large, (
        "the same bytes came back for two different sizes — the key is not "
        "actually per-size")
