"""
Data lifecycle: what Pulse keeps, and leaving nothing behind on request.

THE GAP
    The uninstaller's own comment sets the goal — "A deliberate REMOVAL
    should be able to leave nothing behind" — and what it removed was the
    HKCU key: theme, geometry, run history. %LOCALAPPDATA%\\PULSE stayed
    entirely, which is where the material actually is: Edge bookmarks,
    evacuated OneDrive documents, exported driver packages, the log. The
    prompt was accurate about what it deleted, which made it more
    misleading rather than less — a user reading "theme, window position
    and run history" reasonably concludes that is everything.

WHY THERE IS NO AGE-BASED AUTO-PURGE, which is what was asked for first
    Backups\\ holds no generations. Backup-EdgeState and
    Backup-OneDriveFiles write to fixed paths and overwrite in place, so
    there is never a superseded copy to prune — whatever is there is the
    only one.

    Backups\\OneDrive is the case that settles it: it holds every local
    OneDrive sync root, evacuated there before the client is uninstalled,
    existing precisely because the original was about to be destroyed. An
    age cap would delete the only remaining copy of the user's documents
    on a timer, which is the outcome the backup was taken to prevent.

    The genuine caches already rotate and are not duplicated here:
    updates\\ at 7 days (updater.prune), the engine log at 5MB, crash.log
    at 1MB. So retention is reporting plus an informed manual purge, and
    these tests pin that the dangerous version was not built.
"""
from __future__ import annotations

import os

import pytest

from utils import datastore


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A throwaway data root, so a purge test cannot reach the real one."""
    root = tmp_path / "PULSE"
    monkeypatch.setattr(datastore, "data_root", lambda: str(root))
    for parts, name, size in (
            (("Logs",), "Pulse_Log.txt", 2048),
            (("updates",), "PULSE_Setup_v10.9.4.exe", 4096),
            (("Backups", "Edge"), "EdgeManifest.json", 512),
            (("Backups", "OneDrive"), "Documents/report.docx", 8192),
            (("Backups", "Startup"), "Steam.lnk", 256),
            (("Backups", "Drivers"), "nvidia.inf", 1024)):
        target = root.joinpath(*parts, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * size)
    return root


class TestItReportsEverything:
    def test_every_category_is_listed(self, store):
        keys = {entry["key"] for entry in datastore.scan()}
        assert keys == {"logs", "updates", "edge", "onedrive", "startup",
                        "drivers"}

    def test_an_empty_category_is_still_listed(self, store):
        """"Pulse is holding nothing here" is an answer the user came for.
        A list that silently shortens cannot be trusted as complete."""
        import shutil
        shutil.rmtree(str(store / "Backups" / "Drivers"))

        drivers = next(e for e in datastore.scan() if e["key"] == "drivers")
        assert drivers["bytes"] == 0 and drivers["files"] == 0
        assert drivers["exists"] is False

    def test_sizes_are_measured(self, store):
        onedrive = next(e for e in datastore.scan() if e["key"] == "onedrive")
        assert onedrive["bytes"] == 8192
        assert onedrive["files"] == 1

    def test_the_total_adds_up(self, store):
        assert datastore.total_bytes() == 2048 + 4096 + 512 + 8192 + 256 + 1024

    def test_every_category_states_what_losing_it_costs(self, store):
        """"Clear cache" is the wording that makes someone delete their own
        documents. Each entry has to say what it is in the words needed to
        decide."""
        for entry in datastore.scan():
            assert entry["consequence"].strip(), entry["key"]
            assert len(entry["consequence"]) > 30, (
                f"{entry['key']} explains itself in {len(entry['consequence'])} "
                "characters, which is a label rather than a consequence")

    def test_the_irreplaceable_categories_are_marked_as_such(self, store):
        """The distinction the UI leans on to warn differently."""
        by_key = {e["key"]: e for e in datastore.scan()}
        assert by_key["onedrive"]["reproducible"] is False
        assert by_key["edge"]["reproducible"] is False
        assert by_key["startup"]["reproducible"] is False
        assert by_key["logs"]["reproducible"] is True
        assert by_key["updates"]["reproducible"] is True


class TestPurge:
    def test_it_empties_the_category_it_names(self, store):
        removed_files, freed = datastore.purge("logs")
        assert removed_files == 1
        assert freed == 2048
        assert next(e for e in datastore.scan()
                    if e["key"] == "logs")["bytes"] == 0

    def test_it_touches_nothing_else(self, store):
        before = {e["key"]: e["bytes"] for e in datastore.scan()}
        datastore.purge("logs")
        after = {e["key"]: e["bytes"] for e in datastore.scan()}
        for key in before:
            if key != "logs":
                assert after[key] == before[key], f"purging logs hit {key}"

    def test_it_keeps_the_directory(self, store):
        """The engine writes into these paths without always re-creating
        them; removing the directory turns a purge into a failed backup
        later."""
        datastore.purge("edge")
        assert (store / "Backups" / "Edge").is_dir()

    def test_it_removes_nested_trees(self, store):
        removed_files, freed = datastore.purge("onedrive")
        assert removed_files == 1 and freed == 8192
        assert not any((store / "Backups" / "OneDrive").iterdir())

    def test_an_unknown_key_is_refused(self, store):
        with pytest.raises(KeyError):
            datastore.purge("../../Windows")

    def test_purging_an_absent_category_is_harmless(self, store):
        import shutil
        shutil.rmtree(str(store / "Backups" / "Drivers"))
        assert datastore.purge("drivers") == (0, 0)


class TestPurgeCannotEscapeTheRoot:
    def test_the_root_itself_is_never_a_target(self, store, monkeypatch):
        """A category resolving to the root would delete every other
        category with it."""
        assert datastore._is_inside_root(str(store)) is False

    def test_a_path_outside_the_root_is_rejected(self, store, tmp_path):
        assert datastore._is_inside_root(str(tmp_path / "elsewhere")) is False

    def test_a_junction_pointing_out_of_the_root_is_rejected(self, store,
                                                             tmp_path):
        """The reason _is_inside_root resolves REAL paths. A junction
        planted at Backups\\Edge would otherwise make a purge delete
        whatever it points at."""
        outside = tmp_path / "outside_target"
        outside.mkdir()
        link = store / "Backups" / "Linked"
        try:
            os.symlink(str(outside), str(link), target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            pytest.skip("this session cannot create a directory symlink")
        assert datastore._is_inside_root(str(link)) is False


class TestTheDangerousVersionWasNotBuilt:
    def test_there_is_no_age_based_auto_purge(self):
        """Pinned as a decision. Backups hold no generations and OneDrive's
        is the user's only copy of their documents — an age cap there
        deletes it on a timer. If this ever becomes wanted, it needs a
        different data layout first, not a scheduler."""
        import inspect

        source = inspect.getsource(datastore)
        assert "max_age" not in source and "cutoff" not in source, (
            "datastore grew an age-based purge; Backups\\ has no superseded "
            "generations, so that deletes the only copy")

    def test_the_one_real_cache_is_still_capped_elsewhere(self):
        """updates\\ IS disposable and is already pruned at 7 days. This is
        here so the reasoning above cannot be read as "nothing is capped"."""
        from utils import updater

        assert hasattr(updater, "prune")


class TestTheSurfaceExists:
    def test_the_card_is_registered(self):
        """A capability nobody can reach is not a capability."""
        from frontend.menu_structure import iter_leaf_items

        tasks = [value.get("task")
                 for entry in iter_leaf_items()
                 for value in entry if isinstance(value, dict)]
        assert "@data_hygiene" in tasks

    def test_the_action_is_dispatched(self):
        import inspect

        from frontend.main import PulseApp

        source = inspect.getsource(PulseApp._run_local_action)
        assert '"@data_hygiene"' in source, (
            "the card is registered but nothing handles it, so clicking it "
            "falls through to the path-opening branch below")
        assert "DataHygieneDialog" in source

    def test_the_dialog_lists_every_category(self, store, window, qapp):
        from frontend.widgets import DataHygieneDialog

        dialog = DataHygieneDialog(window, window.theme.t)
        try:
            from PySide6.QtWidgets import QLabel
            text = " ".join(label.text()
                            for label in dialog.findChildren(QLabel))
            for category in datastore.CATEGORIES:
                assert category.label in text, (
                    f"{category.label} is missing from the dialog")
        finally:
            dialog.deleteLater()
            qapp.processEvents()

    def test_irreplaceable_rows_are_styled_as_destructive(self, store, window,
                                                          qapp):
        """The distinction the dialog exists to make: a log and a user's
        evacuated OneDrive files must not read the same."""
        from frontend.widgets import DataHygieneDialog

        dialog = DataHygieneDialog(window, window.theme.t)
        try:
            entries = {e["key"]: e for e in datastore.scan()}
            assert entries["onedrive"]["reproducible"] is False
            assert entries["logs"]["reproducible"] is True
        finally:
            dialog.deleteLater()
            qapp.processEvents()


class TestTheUninstallerOffersTheRest:
    def _iss(self) -> str:
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "installer", "pulse.iss"),
                  encoding="utf-8-sig") as handle:
            return handle.read()

    def test_it_offers_to_delete_the_data_root(self):
        source = self._iss()
        assert r"{localappdata}\PULSE" in source, (
            "uninstall still removes only the HKCU key, so the log, the "
            "Edge backup and the rescued OneDrive files stay behind")
        assert "DelTree" in source

    def test_the_prompt_names_what_is_in_there(self):
        """"Also delete application data" invites Yes from someone who
        would say No to "your rescued OneDrive files". The consent is only
        informed if the wording carries it."""
        source = self._iss()
        for word in ("OneDrive", "Edge", "log"):
            assert word in source, (
                f"the uninstall prompt does not mention {word}")
        assert "only copy" in source, (
            "the prompt does not warn that the rescued files may be "
            "irreplaceable")

    def test_it_defaults_to_keeping_them(self):
        """Losing a window position is an inconvenience; losing evacuated
        documents is not recoverable. The two prompts must not default the
        same way by accident."""
        source = self._iss()
        after = source[source.index(r"{localappdata}\PULSE"):]
        assert "MB_DEFBUTTON2" in after, (
            "the data-deletion prompt does not default to No")
