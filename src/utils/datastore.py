"""
src/utils/datastore.py

WHAT PULSE IS HOLDING, AND WHAT IT COSTS TO DELETE IT.

The uninstaller's own comment states the goal — "A deliberate REMOVAL
should be able to leave nothing behind" — and what it removed was the
HKCU key: theme, window geometry, run history. Everything under
%LOCALAPPDATA%\\PULSE stayed, and that is where the material actually
lives: the user's Edge bookmarks, their evacuated OneDrive documents,
exported driver packages, the operation log.

WHY THERE IS NO AGE-BASED AUTO-PURGE HERE, which is the first thing this
module was asked for and the wrong thing to build:

    Backups\\ is not a cache. Every category under it is written ONCE and
    overwritten in place — there are no timestamped generations, so there
    is no superseded copy to prune. Whatever is there is the only copy.

    Backups\\OneDrive is the extreme case: Backup-OneDriveFiles evacuates
    EVERY local OneDrive sync root there before the client is uninstalled.
    It exists precisely because the original is about to be destroyed. An
    age cap on that folder would, on a schedule, silently delete the only
    remaining copy of the user's documents — the exact outcome the backup
    was taken to prevent.

    So retention here is REPORTING plus a deliberate, informed purge. The
    genuine caches already rotate on their own and are not duplicated:
    updates\\ is pruned at 7 days by updater.prune, the engine's log
    rotates at 5MB, and crash.log rotates at 1MB.

Every category therefore carries the CONSEQUENCE of removing it, in the
words a user needs to make the decision — not "clear cache".
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass

from utils import resources


@dataclass(frozen=True)
class Category:
    """One thing Pulse keeps on disk, and what losing it means."""

    key: str
    label: str
    #: Path segments below the data root. Kept as segments rather than a
    #: joined string so purge() can rebuild the path itself and never take
    #: one from a caller — see _resolve.
    parts: tuple[str, ...]
    consequence: str
    #: True when the data is reproducible by re-running something. False
    #: means this is the only copy and deleting it is a one-way door.
    reproducible: bool


CATEGORIES: tuple[Category, ...] = (
    Category(
        key="logs", label="Operation logs", parts=("Logs",),
        consequence="Diagnostic history only. Pulse writes a new log on the "
                    "next run.",
        reproducible=True),
    Category(
        key="updates", label="Downloaded installers", parts=("updates",),
        consequence="Update downloads Pulse can fetch again. Already pruned "
                    "automatically after 7 days.",
        reproducible=True),
    Category(
        key="edge", label="Edge backup", parts=("Backups", "Edge"),
        consequence="Your Edge bookmarks, favourites and preferences, saved "
                    "before Edge was removed. Deleting this means Restore "
                    "Edge can no longer bring them back.",
        reproducible=False),
    Category(
        key="onedrive", label="Rescued OneDrive files",
        parts=("Backups", "OneDrive"),
        consequence="Your own files, copied out of OneDrive before the "
                    "client was uninstalled. For anything that was not "
                    "synced elsewhere, this is the only copy.",
        reproducible=False),
    Category(
        key="startup", label="Startup item backups",
        parts=("Backups", "Startup"),
        consequence="Shortcuts moved aside by the Startup Manager. Deleting "
                    "this means they cannot be put back.",
        reproducible=False),
    Category(
        key="drivers", label="Driver backups", parts=("Backups", "Drivers"),
        consequence="Third-party driver packages exported by Driver Backup. "
                    "Re-exportable while the drivers are still installed.",
        reproducible=True),
)


def data_root() -> str:
    return resources.data_root()


def _resolve(category: Category) -> str:
    """The absolute path for a category, built here rather than accepted.

    purge() deletes a directory tree, so the path it acts on must never be
    something a caller can influence. Callers pass a KEY; this turns it
    into a path under the data root, and _is_inside_root re-checks the
    result before anything is removed.
    """
    return os.path.join(data_root(), *category.parts)


def _is_inside_root(path: str) -> bool:
    """True only when `path` really sits under the data root.

    Belt and braces against a resolved path escaping — a symlink or
    junction planted at %LOCALAPPDATA%\\PULSE\\Backups\\Edge would
    otherwise make a purge delete whatever it points at. commonpath on the
    REAL paths is what closes that: it follows the link first.
    """
    try:
        root = os.path.realpath(data_root())
        target = os.path.realpath(path)
    except OSError:
        return False
    if os.path.normcase(target) == os.path.normcase(root):
        return False        # never the root itself
    try:
        return os.path.normcase(os.path.commonpath([root, target])) == \
            os.path.normcase(root)
    except ValueError:
        return False        # different drives


def _measure(path: str) -> tuple[int, int, float]:
    """(bytes, files, newest mtime) for a tree. Missing reads as empty.

    Errors are swallowed per entry rather than per scan: one unreadable
    file — an antivirus handle, a permission oddity — must cost that file
    and not the whole figure.
    """
    total = files = 0
    newest = 0.0
    for base, _dirs, names in os.walk(path, onerror=lambda _e: None):
        for name in names:
            try:
                stat = os.stat(os.path.join(base, name))
            except OSError:
                continue
            total += stat.st_size
            files += 1
            newest = max(newest, stat.st_mtime)
    return total, files, newest


def scan() -> list[dict]:
    """Every category, measured. Always returns all of them.

    An empty category is reported as empty rather than omitted: "Pulse is
    holding nothing here" is an answer the user came for, and a list that
    silently shortens is one they cannot trust as complete.
    """
    out = []
    for category in CATEGORIES:
        path = _resolve(category)
        size, files, newest = _measure(path)
        out.append({
            "key": category.key,
            "label": category.label,
            "path": path,
            "bytes": size,
            "files": files,
            "newest": newest,
            "age_days": ((time.time() - newest) / 86400.0) if newest else None,
            "consequence": category.consequence,
            "reproducible": category.reproducible,
            "exists": os.path.isdir(path),
        })
    return out


def total_bytes() -> int:
    return sum(entry["bytes"] for entry in scan())


def purge(key: str) -> tuple[int, int]:
    """Delete one category's contents. Returns (files removed, bytes freed).

    The CONTENTS, not the directory: the engine writes into these paths
    without always re-creating them, and removing the directory itself
    would turn a purge into a failed backup later.
    """
    category = next((c for c in CATEGORIES if c.key == key), None)
    if category is None:
        raise KeyError(f"unknown data category: {key!r}")

    path = _resolve(category)
    if not os.path.isdir(path) or not _is_inside_root(path):
        return (0, 0)

    size, files, _newest = _measure(path)
    removed_any = False
    for name in os.listdir(path):
        target = os.path.join(path, name)
        try:
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target, ignore_errors=True)
            else:
                os.remove(target)
            removed_any = True
        except OSError:
            # A locked file — an open log, an antivirus handle — costs
            # itself and not the rest of the purge.
            continue

    if not removed_any:
        return (0, 0)
    after_size, after_files, _ = _measure(path)
    return (max(0, files - after_files), max(0, size - after_size))
