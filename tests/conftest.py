"""
tests/conftest.py

Shared fixtures for the Pulse regression suite.

TWO things here are load-bearing and must not be "tidied away":

1. IMPORT ROOTING. src/frontend/main.py imports its siblings absolutely
   (`from frontend.widgets import ...`) and ships as
   `python src\\frontend\\main.py`, so **src/ is the package root**. A test
   that reaches the app via `import src.frontend.main` loads a SECOND,
   independent copy of every module: `src.frontend.widgets.PulseDialog is
   not frontend.widgets.PulseDialog`. Nothing raises — but every
   isinstance() check silently returns False, so working code (e.g.
   PulseApp.resizeEvent's `isinstance(active, PulseDialog)` guard) looks
   broken. test_imports.py guards this invariant explicitly.

2. PREFERENCE ISOLATION. prefs.py writes to the real user hive
   (HKCU\\Software\\HumamTaibeh\\Pulse): theme, window geometry, recent
   operations. Tests maximize windows and save geometry, so without
   isolation a test run would rewrite the developer's actual settings —
   and the "closed while maximized" regression test would leave the app
   in exactly the state that used to prevent it from starting. The whole
   session is redirected to a throwaway app name and deleted afterwards.
"""
from __future__ import annotations

import os
import sys

import pytest

# --- 1. import rooting: src/ IS the package root (see module docstring) ---
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from PySide6.QtCore import QEvent, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="Win32 window integration is Windows-only")


def is_headless() -> bool:
    """True when Qt is on the offscreen platform plugin, which has no real
    HWND: no non-client area, no DWM, no live Win32 messages."""
    return os.environ.get("QT_QPA_PLATFORM", "") == "offscreen"


def is_elevated() -> bool:
    """Is this pytest session running with Administrator rights?

    Two playbook tests need an UNELEVATED session, because the failure they
    assert on is CreateRestorePoint being REFUSED: unelevated the engine
    returns an ERROR verdict, and that verdict is the only thing that makes
    "a required failure halts the run" observable at all.

    That was guarded by the PULSE_TESTS_ELEVATED environment variable alone
    — a flag a human had to remember to set. GitHub's windows runners
    execute as an administrator and nothing sets it, so the restore point
    SUCCEEDED there and both tests failed asserting on a failure that never
    happened. Asking the OS removes the need for anyone to remember.

    The environment variable survives as an override, for a session that is
    elevated by some route IsUserAnAdmin() cannot see.
    """
    if os.environ.get("PULSE_TESTS_ELEVATED"):
        return True
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (OSError, AttributeError):
        return False


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "native: needs a real (non-offscreen) top-level window")


def pytest_collection_modifyitems(config, items):
    """Enforce what the `native` marker has always CLAIMED.

    The marker and the offscreen check both existed, but nothing ever
    joined them: under QT_QPA_PLATFORM=offscreen the 21 native tests ran
    anyway and failed en masse, because an offscreen window has no
    non-client area to hit-test and no DWM to query. pytest.ini and
    requirements-dev.txt documented them as "skipped headless", so the
    suite's own contract was false — and any CI runner without a desktop
    session would have reported a red build for an entirely healthy tree.
    """
    if not is_headless():
        return
    skip = pytest.mark.skip(
        reason="needs a real top-level window; QT_QPA_PLATFORM=offscreen")
    for item in items:
        if "native" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def _isolate_preferences():
    """Redirect every prefs read/write to a throwaway hive for the run."""
    from utils import prefs
    original = prefs._APP
    prefs._APP = "PulseTestSuite"
    yield
    QSettings(prefs._ORG, prefs._APP).clear()
    prefs._APP = original


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    yield app


@pytest.fixture(scope="session")
def headless() -> bool:
    return is_headless()


def _make_window(normalize: bool = True):
    """`normalize=False` shows the window EXACTLY as main() does, without
    forcing it out of a restored state — required by the tests that assert
    a saved maximized geometry comes back maximized. Calling showNormal()
    there would silently undo the very thing under test."""
    from frontend.main import PulseApp
    win = PulseApp()
    if normalize:
        win.showNormal()
        win.resize(1300, 860)
        win.move(140, 110)
    else:
        win.show()
    return win


@pytest.fixture(scope="session")
def window(qapp):
    """One shared window for the whole session — constructing PulseApp is
    expensive (full UI build + theme pass). Tests that mutate window state
    must restore it; `floating` below does that for you."""
    win = _make_window()
    qapp.processEvents()
    yield win
    win.close()
    qapp.processEvents()


@pytest.fixture
def floating(window, qapp):
    """`window`, guaranteed non-maximized before AND after the test — the
    resize-border hit-tests are only valid on a floating window, and a
    test that leaves it maximized would silently break the next one."""
    _restore(window, qapp)
    yield window
    _restore(window, qapp)


def _restore(win, qapp):
    if win.isMaximized() or win.isMinimized():
        win.showNormal()
        settle(qapp, 250)
    if (win.width(), win.height()) != (1300, 860):
        win.resize(1300, 860)
        settle(qapp, 80)


@pytest.fixture
def fresh_window(qapp):
    """A COLD PulseApp construction, for tests that assert on what happens
    during __init__ itself (the restore-geometry crash regression)."""
    made = []

    def build(normalize: bool = True):
        win = _make_window(normalize)
        made.append(win)
        qapp.processEvents()
        return win

    yield build
    # CLOSED IS NOT DESTROYED, and the difference is fatal at exit.
    #
    # close() hides the window and runs PulseApp.closeEvent, which settles
    # its worker threads — but the QWidget itself stays alive, owned by the
    # Python reference in `made`. Once this fixture returns, that reference
    # is the last one, so the C++ QWidget is destroyed whenever CPython
    # happens to collect the wrapper: potentially during interpreter
    # finalization, after QApplication has already gone. Destroying a
    # QWidget with no living QApplication is undefined behaviour that does
    # not raise — the process dies with 0xC0000409 and no traceback, and a
    # fully green session exits non-zero with its summary line missing.
    #
    # deleteLater() + a drained event loop puts the destruction HERE, while
    # the application is alive and the fixture can still be blamed for it.
    for win in made:
        win.close()
        win.deleteLater()
    made.clear()
    qapp.processEvents()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def settle(qapp, ms: int = 120):
    """Pump the event loop for `ms` — Qt window-state changes and DWM
    transitions are asynchronous, so assertions need a settling window."""
    from PySide6.QtTest import QTest
    qapp.processEvents()
    QTest.qWait(ms)
    qapp.processEvents()


def wait_until(qapp, predicate, timeout_ms: int = 3000, step_ms: int = 20):
    """Pump the loop until `predicate()` is true, or `timeout_ms` elapses.
    Returns its final value, so a caller can assert on it and get a real
    failure rather than a timeout.

    USE THIS INSTEAD OF A FIXED settle() WHENEVER THE ASSERTION IS ABOUT A
    WIDGET BEING VISIBLE. Showing a top-level window is asynchronous: Qt
    asks the platform for a native window and marks the widget visible when
    the platform answers. On an idle machine that is a couple of
    milliseconds and any settle() covers it; inside the full suite, with a
    session-scoped PulseApp and a hundred other widgets alive, it
    occasionally took longer than the 60ms the bloatware tests waited — so
    `dialog._empty.isVisible()` was False, once in roughly ten runs, on a
    dialog that was in every respect correct.

    That is a bad failure to own: it is invisible in isolation (which is
    where anyone investigating runs it), it points at the widget rather
    than at the wait, and the obvious "fix" is to raise the sleep, which
    only moves the threshold. A condition wait removes the race instead of
    re-tuning it, and costs nothing when the condition is already true.
    """
    from PySide6.QtTest import QTest
    waited = 0
    qapp.processEvents()
    while not predicate() and waited < timeout_ms:
        QTest.qWait(step_ms)
        waited += step_ms
    qapp.processEvents()
    return predicate()


def show_dialog(qapp, dialog, timeout_ms: int = 3000, settle_ms: int = 60):
    """show() a dialog, wait until Qt reports it visible, THEN settle.

    Both halves are load-bearing, and dropping either one produces a
    different flaky failure:

      * the WAIT covers native window creation, which is asynchronous and
        occasionally slower than any fixed pause inside the full suite —
        the original defect (see wait_until);

      * the SETTLE covers what PulseDialog.showEvent starts once the window
        exists: refit_dialog gives the panel its real geometry and
        _present_dialog runs the entrance. Returning the instant
        isVisible() flips means the dialog is on screen with its stack
        pages not yet laid out, so a child asked about its own visibility
        immediately afterwards answers False. Waiting on the window and
        then not settling at all simply moved the race.
    """
    dialog.show()
    assert wait_until(qapp, dialog.isVisible, timeout_ms), (
        f"{type(dialog).__name__} was never reported visible within "
        f"{timeout_ms}ms of show()")
    settle(qapp, settle_ms)
    return dialog
