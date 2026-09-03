"""
Two elevated copies of Pulse could mutate the same machine at once.

WHY THIS MATTERS MORE HERE THAN FOR AN ORDINARY APP
    Pulse runs with an Administrator token by design (main.spec's
    uac_admin) and ~24 of its tasks write HKLM, services or machine state.
    Two instances is therefore not the usual "two windows, mildly untidy"
    problem: it is two elevated engines able to run conflicting tasks
    against one machine with no knowledge of each other. Both purging
    Edge, one restoring a service the other just disabled, two
    Restore-OriginalRegValue snapshots racing for the same key — the
    backup layer is first-write-wins per process and has no cross-process
    lock, so the second writer's "original" value can be the first
    writer's half-applied one.

THE MECHANISM, AND WHY A MUTEX
    A named kernel mutex is the authoritative answer to "is one already
    running", and the kernel releases it when the holder dies however it
    dies — no stale lock to clear after a crash, which is the failure mode
    a lock FILE would add. The activation hand-off rides on a QLocalServer
    (a named pipe on Windows, released by the kernel on the same terms),
    because the second instance needs to say "come forward" to a window it
    cannot otherwise address.

WHAT THE SECOND LAUNCH MUST DO
    Not "refuse to start" with an error — the user asked for Pulse, and
    the honest response is the window they meant. It signals the running
    instance to restore and take focus, then exits 0.
"""
from __future__ import annotations

import sys

import pytest

from utils import singleton

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="named-mutex guard is Win32")

KEY = "PulseTestSuite.SingleInstance"


@pytest.fixture
def key():
    """A unique name per test, so a leaked handle in one cannot decide the
    result of another."""
    import uuid
    return f"{KEY}.{uuid.uuid4().hex[:12]}"


class TestTheGuard:
    def test_the_first_acquire_succeeds(self, key):
        guard = singleton.SingleInstance(key)
        try:
            assert guard.acquire() is True
        finally:
            guard.release()

    def test_a_second_acquire_is_refused(self, key):
        first = singleton.SingleInstance(key)
        second = singleton.SingleInstance(key)
        try:
            assert first.acquire() is True
            assert second.acquire() is False, (
                "a second instance was allowed to start — two elevated "
                "engines can now run conflicting tasks on one machine")
        finally:
            first.release()
            second.release()

    def test_releasing_frees_the_name(self, key):
        """The kernel frees the mutex when a process dies; release() is
        the same thing for an orderly exit. Without it a restart within
        the same test session — or a relaunch after elevation — would be
        refused by a name nobody holds any more."""
        first = singleton.SingleInstance(key)
        assert first.acquire() is True
        first.release()

        second = singleton.SingleInstance(key)
        try:
            assert second.acquire() is True, (
                "the name stayed claimed after release; a relaunch would "
                "be locked out by a dead instance")
        finally:
            second.release()

    def test_release_is_safe_without_acquire(self, key):
        """main() calls release() on the way out regardless of which path
        it took, including the second-instance path that never acquired."""
        singleton.SingleInstance(key).release()      # must not raise

    def test_a_refused_guard_does_not_hold_the_name(self, key):
        """The loser must not release the WINNER's mutex when it exits —
        that would hand the name to a third launch while the first is
        still running."""
        first = singleton.SingleInstance(key)
        second = singleton.SingleInstance(key)
        try:
            assert first.acquire() is True
            assert second.acquire() is False
            second.release()                 # the loser goes away

            third = singleton.SingleInstance(key)
            assert third.acquire() is False, (
                "the losing instance released the winner's claim on its "
                "way out")
            third.release()
        finally:
            first.release()


class TestTheActivationHandoff:
    def test_a_request_with_nobody_listening_reports_failure(self, key, qapp):
        """It must be distinguishable, because it is the one case where
        the second instance should keep going rather than exit: the mutex
        said someone holds it, but nothing answers — a hung or dying
        predecessor. Silently exiting there leaves the user with no Pulse
        at all after asking for one."""
        assert singleton.request_activation(key, timeout_ms=300) is False

    def test_a_listener_receives_the_request(self, key, qapp):
        seen = []
        server = singleton.listen_for_activation(key, lambda: seen.append(1))
        assert server is not None, "the activation listener never started"
        try:
            assert singleton.request_activation(key, timeout_ms=2000) is True
            for _ in range(50):
                qapp.processEvents()
                if seen:
                    break
            assert seen, (
                "the running instance was signalled but never raised its "
                "window")
        finally:
            server.close()

    def test_a_second_request_is_also_delivered(self, key, qapp):
        """A user who double-clicks the icon repeatedly must keep getting
        the window, not just the first time."""
        seen = []
        server = singleton.listen_for_activation(key, lambda: seen.append(1))
        try:
            for _ in range(2):
                singleton.request_activation(key, timeout_ms=2000)
                for _ in range(50):
                    qapp.processEvents()
            assert len(seen) >= 2, f"only {len(seen)} of 2 requests arrived"
        finally:
            server.close()


class TestTheWindowComesForward:
    def test_raise_to_front_restores_a_minimized_window(self, floating, qapp):
        """The point of the hand-off. A user who relaunches Pulse while it
        sits minimized is asking for the window, and a raise that leaves
        it in the taskbar has answered nothing."""
        floating.showMinimized()
        qapp.processEvents()
        assert floating.isMinimized()

        floating.raise_to_front()
        qapp.processEvents()

        assert not floating.isMinimized(), (
            "the window stayed minimized after an activation request")
        assert floating.isVisible()

    def test_raise_to_front_is_safe_on_an_already_visible_window(
            self, floating, qapp):
        floating.showNormal()
        qapp.processEvents()
        floating.raise_to_front()        # must not raise or hide it
        qapp.processEvents()
        assert floating.isVisible()
