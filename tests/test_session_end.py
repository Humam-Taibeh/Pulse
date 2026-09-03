"""
Windows could shut down in the middle of an elevated mutation.

THE POLICY ALREADY EXISTED; ONE PATH DID NOT HONOUR IT.
closeEvent refuses to close while the engine is busy, and says why:
"A half-applied MSI install or a half-finished Edge purge is a worse
state than either outcome the user was choosing between." That guard
covers the X button, Alt+F4 and the custom caption's close control.

It does not cover Windows itself ending the session. Shutdown, restart
and log off do not go through closeEvent at all — the OS sends
WM_QUERYENDSESSION, and an app that does not answer it is simply closed.
So the one interruption the app most wanted to prevent was the one it had
nothing to say about, and a machine restarting on a schedule (or on a
Windows Update reboot) could stop the engine mid-write.

WHAT THIS ADDS
    While _busy(), the window answers WM_QUERYENDSESSION with FALSE and
    registers a shutdown block reason so Windows names Pulse and explains
    WHY on the "these apps are preventing shutdown" screen. Idle, it
    answers nothing and Windows closes it normally — an app that blocks
    shutdown when it has no reason to is its own defect.
"""
from __future__ import annotations

import sys

import pytest

WM_QUERYENDSESSION = 0x0011


@pytest.fixture
def watched(window, monkeypatch):
    """The window with its ctypes call intercepted.

    ShutdownBlockReasonCreate/Destroy are isolated behind one method for
    exactly this reason: the behaviour under test is WHEN Pulse claims a
    block, which is a decision, while the Win32 call itself is plumbing
    that cannot be observed from a test.
    """
    calls = []
    monkeypatch.setattr(window, "_set_shutdown_block",
                        lambda reason: calls.append(reason))
    window._shutdown_blocked = False
    window._shutting_down = False
    yield window, calls


class TestTheBlockFollowsBusyState:
    def test_going_busy_claims_a_block_with_a_reason(self, watched,
                                                     monkeypatch):
        window, calls = watched
        monkeypatch.setattr(window, "_busy", lambda: True)
        window._sync_shutdown_block()

        assert calls, "going busy never registered a shutdown block"
        assert isinstance(calls[-1], str) and calls[-1], (
            "the block was registered with no reason — Windows then names "
            "Pulse on the shutdown screen with nothing to explain it")

    def test_going_idle_releases_it(self, watched, monkeypatch):
        window, calls = watched
        monkeypatch.setattr(window, "_busy", lambda: True)
        window._sync_shutdown_block()
        monkeypatch.setattr(window, "_busy", lambda: False)
        window._sync_shutdown_block()

        assert calls[-1] is None, (
            "the block outlived the task; Pulse would go on blocking "
            "shutdown while sitting idle")

    def test_it_does_not_re_register_on_every_status_change(self, watched,
                                                            monkeypatch):
        """_sync_shutdown_block is called from _set_status, which fires
        several times during one task. The Win32 call is idempotent but
        the churn is pointless, and a create-per-status-line would be
        invisible until someone watched the API."""
        window, calls = watched
        monkeypatch.setattr(window, "_busy", lambda: True)
        for _ in range(5):
            window._sync_shutdown_block()

        assert len(calls) == 1, (
            f"{len(calls)} calls for one continuous busy period")


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 message")
class TestTheMessageIsAnswered:
    def _query(self, window):
        """Feed a real WM_QUERYENDSESSION through nativeEvent."""
        import ctypes
        from ctypes import wintypes

        msg = wintypes.MSG()
        msg.hWnd = wintypes.HWND(int(window.winId()))
        msg.message = WM_QUERYENDSESSION
        msg.wParam = 0
        msg.lParam = 0
        return window.nativeEvent(b"windows_generic_MSG",
                                  ctypes.addressof(msg))

    def test_a_busy_window_refuses_the_session_end(self, watched, monkeypatch):
        window, _ = watched
        monkeypatch.setattr(window, "_busy", lambda: True)

        handled, result = self._query(window)

        assert handled, "WM_QUERYENDSESSION was not answered at all"
        assert result == 0, (
            "the window answered TRUE — Windows takes that as consent and "
            "closes Pulse mid-task")

    def test_an_idle_window_consents(self, watched, monkeypatch):
        """Blocking shutdown with nothing in flight is its own defect: the
        user waits on a dialog naming an app that has no reason to object.

        Not intercepting means the message continues into Qt's own
        handler, and Qt rejects the synthetic MSG address this test builds
        — so reaching that ValueError is itself the proof that the block
        branch was not taken. Asserted that way round rather than by
        loosening what the window does, because the alternative (returning
        early for idle) would be inventing behaviour to suit the test.
        """
        window, _ = watched
        monkeypatch.setattr(window, "_busy", lambda: False)

        try:
            handled, _result = self._query(window)
        except ValueError:
            return          # fell through to Qt: not intercepted
        assert not handled, (
            "an idle Pulse still intercepted WM_QUERYENDSESSION instead of "
            "letting Windows close it normally")
