"""
src/utils/crashlog.py

THE APP MUST NOT VANISH WITHOUT SAYING ANYTHING.

Nothing installed a sys.excepthook, and main() ran PulseApp() and
app.exec() bare. That is survivable from a terminal and not survivable in
the build people actually run: main.spec sets console=False, so a windowed
Pulse has no stderr at all and the default excepthook's traceback is
written to a handle that goes nowhere.

Two windows were open as a result:

  STARTUP - an exception out of PulseApp() ends the process before a
  window exists. The icon bounces, nothing appears, and there is nothing
  for the user to report. Not hypothetical here: PulseApp.changeEvent
  carries a comment about a launch crash that made "closed while
  maximized" mean "never starts again".

  RUNTIME - an exception inside a slot reaches sys.excepthook, prints to
  that same dead stderr, and the app carries on in whatever state the
  half-finished slot left it, having told the user nothing.

DESIGN RULE: THIS RUNS WHEN THE APP IS ALREADY BROKEN.
So it depends on as little of the app as possible - no theme, no custom
dialogs, no window state - and every step is individually guarded. A
handler that raises replaces a diagnosable crash with an undiagnosable
one, which is strictly worse than the silence it was written to fix.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime

from utils import resources

#: Appended to within one file, and rotated rather than truncated. The
#: FIRST crash in a session is usually the one that explains the rest, so
#: a handler that started a fresh file per crash would keep only the last
#: one - the least informative of the set.
CRASH_LOG = "crash.log"

#: The previous generation, kept so a rotation cannot throw away the run
#: that led up to the current one.
CRASH_LOG_PREVIOUS = "crash.log.1"

#: Rotate past this. THE UNBOUNDED VERSION WAS A REAL HAZARD, not a tidy-
#: up: the realistic recurring exception is one inside a repainting slot,
#: which fires every frame, and a handler written to make a crash
#: diagnosable would have written tracebacks until the disk filled -
#: turning one incident into two, the second worse than the first.
#:
#: 1MB against the engine's own 5MB log (00-Foundation.ps1 has rotated at
#: that since v6.1). Deliberately the same order rather than the same
#: number: this file holds tracebacks, not a transcript, and 1MB is
#: several hundred of them - far more history than any diagnosis uses.
MAX_LOG_BYTES = 1024 * 1024

#: Pass-through, not crashes. Ctrl+C and sys.exit() are the program ending
#: because it was asked to; recording them as defects would make an
#: interrupted run look like a bug report, and swallowing SystemExit would
#: stop the interpreter exiting the way the caller intended.
_NOT_A_CRASH = (KeyboardInterrupt, SystemExit)

#: Set by install() so the log can say which build produced the trace.
_version = "unknown"


def _log_dir() -> str:
    """Beside everything else Pulse writes.

    v10.7 collapsed the app's output to one root; a crash log written
    somewhere else would be the single file nobody thinks to collect when
    asking "what happened". Monkeypatched in the tests, which is why it is
    a function rather than a constant.
    """
    return os.path.join(resources.data_root(), "Logs")


def _rotate_if_full(path: str) -> None:
    """Move the log aside once it passes MAX_LOG_BYTES.

    os.replace rather than os.rename: the destination usually exists by
    the second rotation, and rename refuses that on Windows while replace
    is atomic and overwrites.

    NEVER RAISES, for the same reason nothing else here does - and the
    likeliest failure is specific: an antivirus scanner holding a handle
    on the file makes the replace fail with PermissionError. Letting the
    log grow past its cap is the right answer to that, because the
    alternative is losing the crash report entirely over a housekeeping
    step.
    """
    try:
        if os.path.getsize(path) < MAX_LOG_BYTES:
            return
    except OSError:
        return          # no file yet, or it cannot be measured
    try:
        os.replace(path, os.path.join(os.path.dirname(path),
                                      CRASH_LOG_PREVIOUS))
    except OSError:
        pass


def _write(exc_type, exc_value, exc_tb) -> str | None:
    """Append one formatted crash. Returns the path, or None if it could
    not be written - a read-only profile, a full disk, a redirected
    LOCALAPPDATA - none of which may be allowed to raise from here."""
    try:
        directory = _log_dir()
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, CRASH_LOG)
        _rotate_if_full(path)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(
                f"\n{'=' * 70}\n"
                f"Pulse {_version} - unhandled exception at {stamp}\n"
                f"{'=' * 70}\n{body}")
        return path
    except Exception:
        return None


def _show_dialog(exc_value, path: str | None) -> None:
    """Tell the user, in the plainest widget Qt has.

    QMessageBox rather than the app's own dialogs on purpose: PulseDialog
    reaches into the theme, paints a backdrop by grabbing the window, and
    parents itself to a shell that may be exactly what just broke. The
    point here is to say something, not to say it beautifully.
    """
    from PySide6.QtWidgets import QApplication, QMessageBox
    if QApplication.instance() is None:
        return
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("Pulse - unexpected error")
    box.setText("Pulse hit an unexpected error and may not behave "
                "correctly until it is restarted.")
    detail = f"{type(exc_value).__name__}: {exc_value}"
    if path:
        detail += f"\n\nThe full details were written to:\n{path}"
    box.setInformativeText(detail)
    box.exec()


def handle(exc_type, exc_value, exc_tb, notify: bool = True) -> None:
    """The excepthook itself. Never raises, by construction."""
    if isinstance(exc_value, _NOT_A_CRASH) or (
            isinstance(exc_type, type) and issubclass(exc_type, _NOT_A_CRASH)):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    path = _write(exc_type, exc_value, exc_tb)

    # Still send it to the original hook: from a terminal that is the
    # traceback a developer expects to see, and it costs nothing in the
    # windowed build where it goes nowhere anyway.
    try:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    except Exception:
        pass

    if notify:
        try:
            _show_dialog(exc_value, path)
        except Exception:
            # A GUI that cannot open a message box is precisely the case
            # this must not turn into a second crash. The log is already
            # written by now, which was the part that mattered.
            pass


def install(version: str = "unknown", notify: bool = True) -> None:
    """Route unhandled exceptions here for the rest of the process."""
    global _version
    _version = version or "unknown"
    sys.excepthook = lambda t, v, tb: handle(t, v, tb, notify=notify)
