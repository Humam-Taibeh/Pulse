"""
The paths Pulse writes to, on machines that are not the developer's.

WHAT MAKES THIS AREA DIFFERENT
    Every path here comes from the environment rather than from the app:
    %LOCALAPPDATA% under a user profile named in any script Windows
    supports, on a machine where a third-party antivirus may hold a handle
    open on the very file being appended to. None of it reproduces on a
    developer box called C:\\Users\\dev.

    Two of the three are structural and were already right - Python 3
    carries paths as str and hands Windows the wide API, so spaces and
    non-ASCII need no quoting, and every subprocess spawn in the app
    passes argv as a LIST rather than a command string, so nothing has to
    be escaped. The one exception is the elevation relaunch, which needs a
    string because ShellExecute takes one, and it builds that string with
    subprocess.list2cmdline - the function whose whole job is this.

THE GAP THIS PASS FOUND
    crash.log appended forever. The engine has rotated its own log at 5MB
    since v6.1 (00-Foundation.ps1), and the crash log added last pass -
    mine - had no cap at all. An exception inside a repainting slot is the
    realistic case: it recurs every frame, and the handler that exists to
    make a crash diagnosable would write until the disk filled.
"""
from __future__ import annotations

import os

import pytest

from utils import crashlog, resources


class TestTheCrashLogIsBounded:
    def test_it_does_not_grow_without_limit(self, tmp_path, monkeypatch):
        """The defect: an exception recurring once per frame writes until
        the disk is full, and the file that was meant to explain a crash
        becomes a second incident."""
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(tmp_path))
        path = os.path.join(str(tmp_path), crashlog.CRASH_LOG)

        for index in range(400):
            try:
                raise RuntimeError(f"recurring failure {index} " + "x" * 400)
            except RuntimeError:
                crashlog.handle(*__import__("sys").exc_info(), notify=False)

        size = os.path.getsize(path)
        assert size <= crashlog.MAX_LOG_BYTES * 2, (
            f"crash.log reached {size} bytes against a "
            f"{crashlog.MAX_LOG_BYTES}-byte cap")

    def test_the_cap_keeps_the_most_recent_crash(self, tmp_path, monkeypatch):
        """Rotation must not lose the crash the user is asking about. The
        newest entry is the one they just saw."""
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(tmp_path))
        for index in range(300):
            try:
                raise RuntimeError(f"failure number {index} " + "y" * 400)
            except RuntimeError:
                crashlog.handle(*__import__("sys").exc_info(), notify=False)

        text = open(os.path.join(str(tmp_path), crashlog.CRASH_LOG),
                    encoding="utf-8", errors="replace").read()
        assert "failure number 299" in text, (
            "the newest crash was rotated away, which is the one entry "
            "that must survive")

    def test_the_cap_is_in_the_same_order_as_the_engines(self):
        """The engine rotates its log at 5MB. A crash log with a wildly
        different budget is a surprise for whoever collects both."""
        assert 256 * 1024 <= crashlog.MAX_LOG_BYTES <= 10 * 1024 * 1024


class TestAwkwardPaths:
    def test_a_directory_with_spaces_and_non_ascii_works(self, tmp_path,
                                                          monkeypatch):
        """A real profile: "C:\\Users\\Ahmet Öztürk\\AppData\\Local". Python
        hands Windows the wide API, so this needs no quoting - asserted
        because the failure mode would be a crash log that silently never
        appears on exactly the machines least able to spare it."""
        awkward = tmp_path / "Ahmet Öztürk" / "Local AppData" / "PULSE Logs"
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(awkward))
        try:
            raise ValueError("a failure on an awkward path")
        except ValueError:
            crashlog.handle(*__import__("sys").exc_info(), notify=False)

        written = awkward / crashlog.CRASH_LOG
        assert written.is_file(), f"nothing written to {awkward}"
        assert "a failure on an awkward path" in written.read_text(
            encoding="utf-8")

    def test_a_locked_log_file_does_not_raise(self, tmp_path, monkeypatch):
        """An antivirus scanner holding the file open is the case that
        cannot be reproduced on demand, so the closest honest test is an
        exclusive handle of our own. The handler must degrade to "no log"
        rather than becoming a second exception on top of the first."""
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(tmp_path))
        path = tmp_path / crashlog.CRASH_LOG
        path.write_text("existing\n", encoding="utf-8")

        import msvcrt

        with open(path, "a", encoding="utf-8") as holder:
            try:
                msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                pytest.skip("could not take an exclusive lock on this volume")
            try:
                try:
                    raise ValueError("crash while the log is locked")
                except ValueError:
                    # Must not raise, and must not hang.
                    crashlog.handle(*__import__("sys").exc_info(),
                                    notify=False)
            finally:
                msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)

    def test_the_log_directory_is_created_when_absent(self, tmp_path,
                                                       monkeypatch):
        """First crash on a fresh install: %LOCALAPPDATA%\\PULSE\\Logs does
        not exist yet, because the engine creates it and the engine may
        never have run."""
        fresh = tmp_path / "never" / "existed" / "Logs"
        monkeypatch.setattr(crashlog, "_log_dir", lambda: str(fresh))
        try:
            raise ValueError("first crash on a fresh install")
        except ValueError:
            crashlog.handle(*__import__("sys").exc_info(), notify=False)
        assert (fresh / crashlog.CRASH_LOG).is_file()


class TestTheDataRoot:
    def test_it_survives_a_missing_localappdata(self, monkeypatch):
        """Service accounts and some sandboxes have no %LOCALAPPDATA%.
        resources.local_appdata falls back to the profile rather than
        building a path beginning with "None"."""
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        root = resources.data_root()
        assert root and "None" not in root
        assert os.path.isabs(root), f"{root} is not absolute"

    def test_it_is_absolute_and_normalised(self):
        root = resources.data_root()
        assert os.path.isabs(root)
        assert ".." not in root, (
            "a traversal segment in the data root would resolve outside "
            "the directory every other Pulse path is anchored to")


class TestElevationRelaunchQuoting:
    def test_the_relaunch_arguments_go_through_list2cmdline(self):
        """The one place the app must hand Windows a command STRING rather
        than argv, because ShellExecute takes one. Hand-quoting is where a
        path like "C:\\Program Files\\PULSE\\PULSE.exe" gets split in two -
        list2cmdline is the stdlib function whose entire purpose is
        producing what the Windows parser will read back correctly."""
        import inspect

        from frontend.main import PulseApp

        source = inspect.getsource(PulseApp._relaunch_as_admin)
        assert "list2cmdline" in source, (
            "the elevation relaunch builds its argument string by hand; a "
            "path with a space will be parsed as two arguments")

    def test_list2cmdline_round_trips_an_awkward_install_path(self):
        """Proving the function does what the call site relies on."""
        import subprocess

        argv = [r"C:\Program Files\PULSE\PULSE.exe",
                r"C:\Users\Ahmet Öztürk\config.json"]
        quoted = subprocess.list2cmdline(argv)
        assert quoted.count('"') >= 4, (
            f"{quoted!r} leaves a spaced path unquoted")
