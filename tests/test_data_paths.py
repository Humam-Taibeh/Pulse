"""
Everything Pulse writes for itself lives under %LOCALAPPDATA%\\PULSE.

WHAT THIS REPLACED. The log moved to LocalAppData in v6.1 for a specific
reason — on a OneDrive-synced Desktop every appended line triggered sync
traffic and the file grew without bound — but the four BACKUP folders were
left behind:

    Desktop\\Pulse_EdgeBackup        Desktop\\Pulse_StartupBackup
    Desktop\\Pulse_OneDriveBackup    Desktop\\Pulse_DriverBackup

Four folders a repair tool scattered across the desktop of someone who came
to it to tidy their machine, on the one surface where clutter is most
visible, and on exactly the folder most likely to be cloud-synced — so a
driver backup could upload itself. The reason the log moved is the reason
all of them should have.

TESTED AT THE SOURCE, not by running the engine. Resolving these for real
means invoking PowerShell, which needs a machine and several seconds; the
invariant worth protecting is that no NEW write target can be added outside
the root, and that is a property of the text. The engine's own resolution is
covered once, live, in test_the_engine_resolves_every_path_under_the_root.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_ROOT, "src", "backend")


def _ps1_files():
    for folder, _dirs, files in os.walk(_BACKEND):
        for name in sorted(files):
            if name.endswith(".ps1"):
                yield os.path.join(folder, name)


def _code_lines(path):
    """Lines with comments and here-string prose stripped — a path named in
    a comment is documentation, not a write."""
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            yield number, line.split("#", 1)[0] if "#" in line else line


# ============================================================
#  NOTHING WRITES TO THE DESKTOP
# ============================================================
#: `$env:USERPROFILE\Desktop\Pulse_Something` — the shape of the four
#: folders this pass moved, and of anything that tries to join them.
_DESKTOP_TARGET = re.compile(
    r"USERPROFILE\\Desktop\\(Pulse|HTCore)[_A-Za-z]*", re.I)

#: THE ONE LEGITIMATE REASON to still name a legacy Desktop folder is to
#: move it INTO the root. Detecting that by keyword ("-From", "$Legacy")
#: was the first attempt and it was wrong twice over: the hashtable form
#: spells it `From = "..."` with no dash, and the foreach form puts the
#: variable on a different LINE from the paths it lists. Both slipped
#: through and the test reported six false offenders.
#:
#: Tracked structurally instead — a line is exempt when it is a `From =`
#: entry, or when it sits inside a list opened by a `$Legacy...` statement.
#: That is what "this path is a migration SOURCE" actually looks like.
def _migration_source_lines(path):
    """Line numbers inside this file that name a legacy home to move FROM."""
    exempt = set()
    depth = 0
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            if depth:
                exempt.add(number)
                depth += line.count("(") - line.count(")")
                if depth <= 0:
                    depth = 0
                continue
            if "From =" in line or "From=" in line:
                exempt.add(number)
                continue
            # `foreach ($Legacy in @(` / `$LegacyHomes = @(`
            if "$Legacy" in line and "@(" in line:
                exempt.add(number)
                depth = line.count("(") - line.count(")")
                if depth < 0:
                    depth = 0
    return exempt


def test_no_backend_file_writes_to_the_desktop():
    offenders = []
    for path in _ps1_files():
        relative = os.path.relpath(path, _ROOT).replace(os.sep, "/")
        exempt = _migration_source_lines(path)
        for number, line in _code_lines(path):
            if number in exempt or not _DESKTOP_TARGET.search(line):
                continue
            offenders.append(f"  {relative}:{number}: {line.strip()[:110]}")
    assert not offenders, (
        "backend file(s) name a Desktop folder outside a migration. Every "
        "write target belongs under Get-PulseDataPath:\n" + "\n".join(offenders))


def test_the_four_backup_folders_are_declared_under_the_root():
    """Each of the four is resolved through Get-PulseDataPath rather than
    joined by hand — which is what stops a fifth being invented."""
    source = "".join(
        open(p, encoding="utf-8-sig", errors="replace").read()
        for p in _ps1_files())
    for var in ("EdgeBackupFolder", "OneDriveBackupFolder",
                "DriverBackupFolder", "StartupBackupFolder"):
        assignment = re.search(
            rf"\$Script:{var}\s*=\s*(.+)", source)
        assert assignment, f"${var} is no longer declared"
        value = assignment.group(1)
        assert "Get-PulseDataPath" in value, (
            f"${var} is assigned {value.strip()[:80]!r} — it must resolve "
            "through Get-PulseDataPath so it lands under the data root")


def test_no_message_sends_the_user_to_the_desktop_for_a_backup():
    """A message naming the wrong folder is as broken as writing to it: the
    user goes to the Desktop, finds nothing, and concludes the backup was
    never taken."""
    offenders = []
    for path in _ps1_files():
        relative = os.path.relpath(path, _ROOT).replace(os.sep, "/")
        exempt = _migration_source_lines(path)
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if number in exempt or line.strip().startswith("#"):
                    continue
                if re.search(r"Desktop\\(Pulse|HTCore)[_A-Za-z]*", line):
                    offenders.append(f"  {relative}:{number}: {line.strip()[:110]}")
    assert not offenders, (
        "message(s) still tell the user their backup is on the Desktop:\n"
        + "\n".join(offenders))


# ============================================================
#  THE TWO SIDES AGREE
# ============================================================
def test_the_gui_and_the_engine_name_the_same_root():
    from utils import resources

    root = resources.data_root()
    assert root.rstrip("\\/").upper().endswith("PULSE")
    assert os.path.dirname(root) == resources.local_appdata()


def test_the_updater_downloads_into_the_same_root():
    """The self-updater predates the root and had already chosen it. This
    is the assertion that it did not drift."""
    from utils import resources, updater

    assert updater.download_dir().lower().startswith(
        resources.data_root().lower())


def test_the_open_backup_action_prefers_the_root(monkeypatch):
    """"Open Backup Folder" must resolve to the new home FIRST, with the
    legacy Desktop folders behind it — a machine whose engine has not yet
    run and migrated still has its backup opened."""
    source = open(os.path.join(_ROOT, "src", "frontend", "main.py"),
                  encoding="utf-8").read()
    # To the end of the TUPLE, not to the first ")" — that one closes the
    # os.path.join on the very first entry, which sliced the legacy
    # fallbacks out of the block being examined and made the test pass or
    # fail on nothing.
    block = source[source.index('"@open_onedrive_backup"'):]
    block = block[:block.index("),\n        }")]
    first = block.index('root, "Backups", "OneDrive"')
    legacy = block.index("Pulse_OneDriveBackup")
    assert first < legacy, (
        "the Desktop fallback is listed before the data root — an upgraded "
        "machine would keep opening the stale copy")


# ============================================================
#  THE ENGINE ITSELF, ONCE
# ============================================================
@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell is Windows-only")
def test_the_engine_resolves_every_path_under_the_root():
    """The live check, run once because it costs a PowerShell start.

    Everything above reads source text, which cannot catch a path that is
    correctly WRITTEN and wrongly RESOLVED — an env var read at the wrong
    time, a Join-Path against an empty segment. This asks the engine.
    """
    from utils import resources

    script = (
        ". './src/backend/modules/00-Foundation.ps1'; "
        ". './src/backend/modules/01-Catalogs.ps1'; "
        "$Script:LogPath; $Script:EdgeBackupFolder; "
        "$Script:OneDriveBackupFolder; $Script:DriverBackupFolder; "
        "$Script:StartupBackupFolder")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, cwd=_ROOT, timeout=180)
    assert result.returncode == 0, result.stderr[:500]

    paths = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    assert len(paths) == 5, f"expected 5 paths, got {paths}"
    root = resources.data_root().lower()
    outside = [p for p in paths if not p.lower().startswith(root)]
    assert not outside, (
        f"the engine resolves {outside} outside {resources.data_root()}")
