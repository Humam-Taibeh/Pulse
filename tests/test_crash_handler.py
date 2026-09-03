"""
The app could vanish without saying anything, and did.

WHAT WAS MISSING
    Nothing anywhere installed a sys.excepthook, and main() ran
    `PulseApp()` and `app.exec()` bare. Both halves of that matter more in
    the SHIPPED build than they do from a terminal, because PyInstaller's
    spec sets console=False: there is no stderr attached to a windowed
    build, so the default excepthook's traceback goes nowhere at all.

    The two failure windows it leaves:

      * STARTUP. An exception out of PulseApp() means no window ever
        appears and the process ends. From the user's side the icon
        bounces and nothing happens — no message, no log, nothing to
        report. This is not hypothetical for this codebase: the
        changeEvent guard's own comment records a launch crash that made
        "closed while maximized" mean "never starts again".

      * RUNTIME. An exception inside a slot reaches sys.excepthook, whose
        default prints to that same dead stderr. The app then continues in
        whatever state the half-finished slot left it, with the user
        having been told nothing.

WHAT IT MUST NOT DO
    A crash handler runs when the app is already broken, so it may not
    depend on anything that could be the broken thing — no theme, no
    custom dialogs, no app singleton state. It must also never raise: an
    exception inside the excepthook replaces a diagnosable crash with an
    undiagnosable one.
"""
from __future__ import annotations

import os
import sys

import pytest

from utils import crashlog


@pytest.fixture(autouse=True)
def _restore_hook():
    """Never leave the suite's own excepthook replaced."""
    original = sys.excepthook
    yield
    sys.excepthook = original


class TestInstallation:
    def test_installing_replaces_the_excepthook(self):
        assert sys.excepthook is sys.__excepthook__ or True  # any starting state
        crashlog.install(notify=False)
        assert sys.excepthook is not sys.__excepthook__, (
            "sys.excepthook was never replaced, so an unhandled exception "
            "still goes to a stderr the windowed build does not have")

    def test_installing_twice_is_harmless(self):
        crashlog.install(notify=False)
        first = sys.excepthook
        crashlog.install(notify=False)
        assert sys.excepthook is not sys.__excepthook__
        assert first is not None


class TestItRecordsTheCrash:
    def test_a_traceback_reaches_the_log(self, tmp_path, monkeypatch):
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(tmp_path))
        try:
            raise ValueError("a distinctive failure")
        except ValueError:
            crashlog.handle(*sys.exc_info(), notify=False)

        path = os.path.join(str(tmp_path), crashlog.CRASH_LOG)
        assert os.path.isfile(path), "no crash log was written"
        text = open(path, encoding="utf-8").read()
        assert "a distinctive failure" in text
        assert "ValueError" in text
        assert "Traceback" in text, "the log records the exception but not where"

    def test_repeated_crashes_append_rather_than_replace(
            self, tmp_path, monkeypatch):
        """The first crash is usually the interesting one; a handler that
        truncates keeps only the last."""
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(tmp_path))
        for message in ("first failure", "second failure"):
            try:
                raise RuntimeError(message)
            except RuntimeError:
                crashlog.handle(*sys.exc_info(), notify=False)

        text = open(os.path.join(str(tmp_path), crashlog.CRASH_LOG),
                    encoding="utf-8").read()
        assert "first failure" in text and "second failure" in text


class TestItNeverMakesThingsWorse:
    def test_an_unwritable_log_directory_does_not_raise(self, monkeypatch):
        """The handler's own failure must not replace a diagnosable crash
        with an undiagnosable one."""
        monkeypatch.setattr(
            crashlog, "_log_dir",
            lambda: "\\\\?\\Z:\\definitely\\not\\a\\writable\\place")
        try:
            raise ValueError("boom")
        except ValueError:
            crashlog.handle(*sys.exc_info(), notify=False)   # must not raise

    def test_a_broken_notifier_does_not_raise(self, tmp_path, monkeypatch):
        """Showing the message box is the part most likely to fail, since
        it needs a working GUI — which is exactly what may have broken."""
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(tmp_path))
        monkeypatch.setattr(
            crashlog, "_show_dialog",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no GUI")))
        try:
            raise ValueError("boom")
        except ValueError:
            crashlog.handle(*sys.exc_info(), notify=True)    # must not raise

    def test_keyboard_interrupt_is_left_to_the_default_hook(
            self, tmp_path, monkeypatch):
        """Ctrl+C is a deliberate stop, not a crash. Swallowing it into a
        crash log would make an interrupted run look like a defect, and
        would stop the interpreter exiting the way the user asked."""
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(tmp_path))
        seen = []
        monkeypatch.setattr(sys, "__excepthook__",
                            lambda *a: seen.append(a[0]))

        crashlog.handle(KeyboardInterrupt, KeyboardInterrupt(), None,
                        notify=False)

        assert seen and seen[0] is KeyboardInterrupt, (
            "KeyboardInterrupt was captured instead of being passed through")
        assert not os.path.isfile(
            os.path.join(str(tmp_path), crashlog.CRASH_LOG)), (
            "Ctrl+C was written to the crash log as though it were a defect")

    def test_system_exit_is_left_to_the_default_hook(self, tmp_path,
                                                     monkeypatch):
        """sys.exit() is the app ending on purpose."""
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(tmp_path))
        seen = []
        monkeypatch.setattr(sys, "__excepthook__",
                            lambda *a: seen.append(a[0]))

        crashlog.handle(SystemExit, SystemExit(0), None, notify=False)

        assert seen and seen[0] is SystemExit
        assert not os.path.isfile(
            os.path.join(str(tmp_path), crashlog.CRASH_LOG))


class TestTheLogLivesWithEverythingElsePulseWrites:
    def test_the_directory_is_under_the_one_data_root(self):
        """v10.7 put everything Pulse writes under %LOCALAPPDATA%\\PULSE;
        a crash log dropped somewhere else would be the one file nobody
        thinks to collect."""
        from utils import resources
        assert crashlog._log_dir().lower().startswith(
            resources.data_root().lower()), (
            f"crash logs go to {crashlog._log_dir()}, outside "
            f"{resources.data_root()}")
