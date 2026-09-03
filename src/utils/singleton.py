"""
src/utils/singleton.py

ONE PULSE PER DESKTOP SESSION.

Two instances of an ordinary app is untidy. Two instances of THIS one is a
correctness problem: Pulse holds an Administrator token by design (see
main.spec's uac_admin) and around two dozen of its tasks write HKLM,
services or machine state. Nothing in the engine coordinates across
processes, so a second copy can disable a service the first is restoring,
or take a "original value" snapshot of a key the first has already
half-written - Backup-OriginalRegValue is first-write-wins WITHIN a
process and has no cross-process lock at all.

TWO MECHANISMS, EACH FOR THE THING IT IS BEST AT

  A NAMED KERNEL MUTEX answers "is one already running", atomically, with
  no window between the check and the claim. Its decisive property here is
  what happens when a process dies badly: the kernel releases the handle
  however the holder exited, so there is no stale lock to clear after a
  crash. A lock file would have to invent that, and would get it wrong the
  first time someone killed Pulse from Task Manager mid-task.

  A QLocalServer (a named pipe on Windows, released on the same terms)
  carries the hand-off. The second instance has to say "come forward" to a
  window in another process, and a pipe it can name is a great deal
  steadier than finding an HWND by its title - a title this app changes as
  the user navigates.

SESSION-SCOPED, NOT GLOBAL. The mutex name carries no "Global\\" prefix,
so the guard covers one desktop session rather than the whole machine.
Two different administrators logged into the same box each get their own
Pulse, which is the ordinary expectation for a desktop app; the alternative
locks out a second signed-in user with a message about someone else's
session, and the concurrency it prevents is far rarer than the confusion
it would cause.
"""
from __future__ import annotations

import ctypes
import sys

#: One name for both the mutex and the pipe. Version-free on purpose: the
#: point is that two Pulses never run together, including one launched
#: from a checkout beside an installed build.
KEY = "HumamTaibeh.Pulse.SingleInstance"

_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """The claim on "I am the running Pulse".

    Held for the life of the process - main() keeps the instance alive
    deliberately, because letting it be garbage collected would close the
    handle and quietly re-open the door this exists to shut.
    """

    def __init__(self, key: str = KEY):
        self._key = key
        self._handle = None
        #: Only the winner may release. A refused instance that closed the
        #: name on its way out would hand it to a third launch while the
        #: first is still running - see the test of the same name.
        self._owned = False

    def acquire(self) -> bool:
        """True if this process is the first. False if one already runs."""
        if sys.platform != "win32":
            # Nothing to coordinate off Windows: the engine this guards
            # does not run there at all.
            self._owned = True
            return True
        try:
            handle = ctypes.windll.kernel32.CreateMutexW(None, False,
                                                         self._key)
            if not handle:
                return True     # cannot create the guard; do not block launch
            if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
                ctypes.windll.kernel32.CloseHandle(handle)
                return False
            self._handle = handle
            self._owned = True
            return True
        except (OSError, AttributeError):
            # A guard that cannot be built must not be a guard that stops
            # the app: the failure mode of refusing to launch is worse
            # than the concurrency this prevents.
            return True

    def release(self) -> None:
        """Drop the claim. Safe to call having never acquired one, which
        is what the second-instance path in main() does on its way out."""
        if not self._owned or self._handle is None:
            self._handle = None
            self._owned = False
            return
        try:
            ctypes.windll.kernel32.ReleaseMutex(self._handle)
            ctypes.windll.kernel32.CloseHandle(self._handle)
        except (OSError, AttributeError):
            pass
        self._handle = None
        self._owned = False


def request_activation(key: str = KEY, timeout_ms: int = 1500) -> bool:
    """Ask the running instance to come forward. True if it was told.

    FALSE IS MEANINGFUL AND IS NOT THE SAME AS "no instance". The mutex
    has already said someone holds the name; a failure here means that
    someone is not answering - starting up, hung, or part-way through
    dying. main() treats that as "carry on and open a window" rather than
    exiting, because the alternative leaves the user with no Pulse at all
    after they asked for one.
    """
    from PySide6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    try:
        socket.connectToServer(key)
        if not socket.waitForConnected(timeout_ms):
            return False
        socket.write(b"raise")
        socket.flush()
        socket.waitForBytesWritten(timeout_ms)
        return True
    except Exception:
        return False
    finally:
        try:
            socket.disconnectFromServer()
        except Exception:
            pass


def listen_for_activation(key: str = KEY, on_activate=None):
    """Serve activation requests for the rest of the process.

    Returns the QLocalServer (which the caller must keep a reference to)
    or None if the listener could not start. None is survivable: the app
    runs, it simply will not be raised by a second launch.
    """
    from PySide6.QtNetwork import QLocalServer

    try:
        # A pipe left behind by a process that died without closing it
        # would otherwise make listen() fail for every future launch, and
        # the guard would degrade to "second instance exits, first never
        # comes forward" - the worst of both.
        QLocalServer.removeServer(key)
        server = QLocalServer()
        if not server.listen(key):
            return None

        def _accept():
            connection = server.nextPendingConnection()
            if connection is None:
                return
            # The payload is not read: the connection IS the message, and
            # waiting on bytes here would block the GUI thread for a
            # sender that has already gone away.
            connection.disconnectFromServer()
            connection.deleteLater()
            if on_activate is not None:
                on_activate()

        server.newConnection.connect(_accept)
        return server
    except Exception:
        return None
