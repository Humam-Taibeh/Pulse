"""
The Leftovers Cleaner's GUI, and the Startup Manager's two v10.13 changes:
scheduled tasks and measured boot delays.

WHAT THE PESTER SUITE ALREADY PROVES, and what is left for this file.
tests/backend/Leftovers.Tests.ps1 covers every way the ENGINE could flag the
wrong thing or remove without a way back. What it cannot see is the half a
person meets: which card opens the dialog, whether the dialog shows the
evidence for every verdict, whether "Safe Purge (N)" counts what is actually
ticked, and whether a Startup Manager row distinguishes a measured delay from
an estimate.

The fixtures are shaped from a REAL scan of the machine this was built on -
the SignalRgb record Pulse had disabled, the two Adobe ghost tasks, and the
454 MB VortxEngine package its own uninstaller marked dead.
"""
from __future__ import annotations

import pytest

from frontend import menu_structure as MS
from utils.helpers import TaskResult


_ITEMS = [
    {"id": "a1b2c3d4e5f60718", "kind": "startup-run", "group": "startup",
     "name": "SignalRgb",
     "location": r"HKCU:\Software\Pulse\DisabledStartup",
     "valueName": "SignalRgb",
     "target": r"C:\Users\me\AppData\Local\VortxEngine\SignalRgbLauncher.exe",
     "reason": "Disabled in Pulse, and the program it pointed at has since been uninstalled.",
     "sizeBytes": 0, "needsAdmin": False},
    {"id": "0011223344556677", "kind": "task", "group": "tasks",
     "name": "Adobe Uninstaller", "location": r"\Adobe Uninstaller",
     "valueName": "\\",
     "target": r"C:\Program Files (x86)\Adobe\Adobe Creative Cloud\ACC\Creative Cloud.exe",
     "reason": "Scheduled to run a program that is not on this PC.",
     "sizeBytes": 0, "needsAdmin": True},
    {"id": "8899aabbccddeeff", "kind": "residue", "group": "residue",
     "name": "VortxEngine", "location": r"C:\Users\me\AppData\Local\VortxEngine",
     "valueName": "",
     "target": r"C:\Users\me\AppData\Local\VortxEngine\Update.exe",
     "reason": "An uninstalled app's files, left behind - its own uninstaller marked this folder dead.",
     "sizeBytes": 476_263_219, "needsAdmin": False},
]


def _report(items=None, elevated=True):
    items = list(_ITEMS if items is None else items)
    return {"items": items, "elevated": elevated, "hasBackup": False,
            "totalBytes": sum(int(i.get("sizeBytes") or 0) for i in items)}


def _find_card(task: str):
    for category in MS.CATEGORIES:
        for item in MS.category_items(category):
            children = MS.hub_items(item) if item.get("hub") else []
            for child in children:
                if child.get("task") == task:
                    return item, child
    return None, None


# ============================================================
#  THE CARD
# ============================================================
class TestTheCard:

    def test_the_cleaner_is_a_hub_of_purge_restore_and_backup_folder(self):
        """Remove only BESIDE its undo - the Edge and OneDrive teardowns'
        pattern, for their reason."""
        hub, purge = _find_card("LeftoversPurge")
        assert hub is not None, "no card runs LeftoversPurge"
        assert hub["title"] == "Leftovers Cleaner"
        tasks = [child.get("task") for child in MS.hub_items(hub)]
        assert tasks == ["LeftoversPurge", "LeftoversRestore", "@open_leftovers_backup"]

    def test_the_purge_card_opens_the_selector_instead_of_a_yes_no_sheet(self):
        _hub, purge = _find_card("LeftoversPurge")
        assert purge.get("leftovers") is True
        assert not purge.get("confirm"), (
            "the selector names every item it removes; a confirm sheet on "
            "top of it is the double prompt people learn to click through")

    def test_the_writes_are_admin_gated_and_the_scan_is_not(self):
        assert MS.requires_admin("LeftoversPurge")
        assert MS.requires_admin("LeftoversRestore")
        assert not MS.requires_admin("LeftoversScan")


# ============================================================
#  THE DIALOG
# ============================================================
@pytest.fixture
def cleaner(window, qapp, monkeypatch):
    from frontend.widgets import LeftoversDialog
    # No live scan, for the reason every selector fixture documents: the
    # real worker against an empty engine path fails in milliseconds and
    # swaps the stack to the error page under the assertions.
    monkeypatch.setattr(LeftoversDialog, "_start_scan", lambda self: None)
    dialog = LeftoversDialog(window, "", window.theme.t)
    dialog.show()
    qapp.processEvents()
    yield dialog
    dialog.reject()
    dialog.deleteLater()
    qapp.processEvents()


class TestTheDialog:

    def test_every_finding_is_listed_and_pre_ticked(self, cleaner, qapp):
        cleaner._on_scan_finished(TaskResult(success=True, message="ok", data=_report()))
        qapp.processEvents()
        assert len(cleaner._rows) == 3
        assert all(row.is_selected() for row in cleaner._rows.values())
        assert cleaner._stack.currentWidget() is cleaner._results_page

    def test_the_button_counts_what_is_actually_ticked(self, cleaner, qapp):
        cleaner._on_scan_finished(TaskResult(success=True, message="ok", data=_report()))
        qapp.processEvents()
        assert cleaner._purge_btn.text() == "Safe Purge (3)"
        cleaner._rows["0011223344556677"].set_checked(False)
        qapp.processEvents()
        assert cleaner._purge_btn.text() == "Safe Purge (2)"
        cleaner._select_all(False)
        assert cleaner._purge_btn.text() == "Safe Purge"
        assert not cleaner._purge_btn.isEnabled()

    def test_the_selection_it_hands_back_is_exactly_the_ticked_ids(self, cleaner, qapp):
        cleaner._on_scan_finished(TaskResult(success=True, message="ok", data=_report()))
        qapp.processEvents()
        cleaner._rows["a1b2c3d4e5f60718"].set_checked(False)
        cleaner._accept_selection()
        assert sorted(cleaner.selected_ids) == ["0011223344556677", "8899aabbccddeeff"]
        assert all("," not in item_id for item_id in cleaner.selected_ids), (
            "ids ride on -AppIds, which is a comma-separated list")

    def test_every_row_shows_its_evidence(self, cleaner, qapp):
        """The target is ON the row. A cleaner that asked for trust without
        showing what the verdict was based on would be asking for exactly
        the blind deletion it exists to avoid."""
        cleaner._on_scan_finished(TaskResult(success=True, message="ok", data=_report()))
        qapp.processEvents()
        for item in _ITEMS:
            row = cleaner._rows[item["id"]]
            assert row._note.text() == item["reason"]
            assert row._target.fullText() == item["target"]
            assert not row._target.isHidden()

    def test_a_long_path_cannot_widen_the_dialog(self, window, qapp):
        """A path has no spaces to wrap at. As a word-wrapped QLabel its whole
        length became the row's minimum width, so one deep AppData path
        would have widened the dialog for every row."""
        from frontend.widgets import LeftoverRow
        deep = "C:\\Users\\me\\AppData\\Local\\" + "\\".join(["Subfolder"] * 40) + "\\app.exe"
        row = LeftoverRow({**_ITEMS[0], "target": deep}, window.theme.t)
        try:
            assert row.minimumSizeHint().width() < 600, (
                f"the row demands {row.minimumSizeHint().width()}px for its path")
            assert row._target.fullText() == deep
        finally:
            row.deleteLater()
            qapp.processEvents()

    def test_it_groups_by_kind_with_counts(self, cleaner, qapp):
        from PySide6.QtWidgets import QLabel
        cleaner._on_scan_finished(TaskResult(success=True, message="ok", data=_report()))
        qapp.processEvents()
        headers = {label.text() for label in cleaner.findChildren(QLabel)}
        assert "STARTUP ENTRIES  ·  1" in headers
        assert "SCHEDULED TASKS  ·  1" in headers
        assert "ABANDONED APP FOLDERS  ·  1" in headers

    def test_it_reports_the_space_a_dead_package_holds(self, cleaner, qapp):
        cleaner._on_scan_finished(TaskResult(success=True, message="ok", data=_report()))
        qapp.processEvents()
        row = cleaner._rows["8899aabbccddeeff"]
        assert row._size_badge is not None
        assert row._size_badge.text() == "454.2 MB"
        assert "454.2 MB" in cleaner._subtitle.text()

    def test_it_says_when_removal_will_need_administrator(self, cleaner, qapp):
        cleaner._on_scan_finished(TaskResult(success=True, message="ok",
                                             data=_report(elevated=False)))
        qapp.processEvents()
        assert "needs administrator" in cleaner._subtitle.text()

    def test_a_clean_machine_gets_the_clean_page_and_no_purge_button(self, cleaner, qapp):
        cleaner._on_scan_finished(TaskResult(success=True, message="ok",
                                             data=_report(items=[])))
        qapp.processEvents()
        assert cleaner._stack.currentWidget() is cleaner._clean_page
        assert cleaner._purge_btn.isHidden()
        assert cleaner._cancel_btn.text() == "Close"

    def test_a_failed_scan_changes_nothing_and_offers_nothing(self, cleaner, qapp):
        cleaner._on_scan_finished(TaskResult(success=False, message="engine exploded", data=None))
        qapp.processEvents()
        assert cleaner._stack.currentWidget() is cleaner._error_page
        assert not cleaner._purge_btn.isEnabled()
        assert "Nothing was changed" in cleaner._error_label.text()

    def test_an_ampersand_in_a_name_is_not_eaten_as_a_mnemonic(self, window, qapp):
        from frontend.widgets import LeftoverRow
        row = LeftoverRow({**_ITEMS[0], "name": "Movies & TV"}, window.theme.t)
        try:
            assert row.checkbox.text() == "Movies && TV"
        finally:
            row.deleteLater()
            qapp.processEvents()


# ============================================================
#  THE STARTUP MANAGER
# ============================================================
def _startup_item(**over):
    item = {"Id": "Registry|||HKCU|||Steam", "Name": "Steam", "DisplayName": "Steam",
            "Type": "Registry", "Command": r'"C:\Program Files (x86)\Steam\steam.exe" -silent',
            "Enabled": True, "Recommendation": "Disable", "Impact": "High",
            "Reason": "Game launcher.", "Protected": False, "TargetPresent": True}
    item.update(over)
    return item


class TestStartupRows:

    def test_a_measured_delay_is_the_badge(self, window, qapp):
        """"HIGH IMPACT" came from a rules table and read exactly like a
        measurement. Where Windows recorded the delay, the badge carries it."""
        from frontend.widgets import StartupRow
        row = StartupRow(_startup_item(ImpactMeasured=True, BootDelayMs=3800,
                                       BootDelayMaxMs=4400, BootDelaySamples=2),
                         window.theme.t)
        try:
            assert row._impact_badge.text() == "DELAYS BOOT 3.8s"
            tip = row._impact_badge.toolTip()
            assert "Measured by Windows" in tip
            assert "2 recent boots" in tip
            assert "4.4s at worst" in tip
        finally:
            row.deleteLater()
            qapp.processEvents()

    def test_an_estimate_says_it_is_one(self, window, qapp):
        from frontend.widgets import StartupRow
        row = StartupRow(_startup_item(), window.theme.t)
        try:
            assert row._impact_badge.text() == "HIGH IMPACT"
            assert "Estimated" in row._impact_badge.toolTip()
            assert "not a measurement" in row._impact_badge.toolTip()
        finally:
            row.deleteLater()
            qapp.processEvents()

    def test_a_scheduled_task_row_says_what_triggers_it(self, window, qapp):
        from frontend.widgets import StartupRow
        row = StartupRow(_startup_item(Id=r"Task|||\|||GCC", Name="GCC", DisplayName="GCC",
                                       Type="Task", Trigger="at sign-in",
                                       Command=r'"C:\Program Files\GIGABYTE\Control Center\GCC.exe" -b'),
                         window.theme.t)
        try:
            assert "Scheduled task (at sign-in)" in row._meta.text()
        finally:
            row.deleteLater()
            qapp.processEvents()


@pytest.fixture
def manager(window, qapp, monkeypatch):
    from frontend.widgets import StartupManagerDialog
    monkeypatch.setattr(StartupManagerDialog, "_start_scan", lambda self: None)
    dialog = StartupManagerDialog(window, "", window.theme.t)
    dialog.show()
    qapp.processEvents()
    yield dialog
    dialog.reject()
    dialog.deleteLater()
    qapp.processEvents()


class TestStartupPayload:

    def test_the_new_object_payload_renders(self, manager, qapp):
        payload = {"items": [_startup_item()],
                   "boot": {"available": True, "reason": "ok", "lastBootMs": 42000,
                            "averageBootMs": 40000, "boots": 7, "measuredApps": 1}}
        manager._on_scan_finished(TaskResult(success=True, message="ok", data=payload))
        qapp.processEvents()
        assert "Registry|||HKCU|||Steam" in manager._rows
        assert manager._stack.currentWidget() is manager._results_page

    def test_an_older_engines_bare_array_still_renders(self, manager, qapp):
        """The updater can install a GUI before the engine it talks to."""
        manager._on_scan_finished(TaskResult(success=True, message="ok",
                                             data=[_startup_item()]))
        qapp.processEvents()
        assert "Registry|||HKCU|||Steam" in manager._rows

    def test_the_subtitle_reports_the_last_boot_when_windows_measured_it(self, manager, qapp):
        payload = {"items": [_startup_item(ImpactMeasured=True, BootDelayMs=3800)],
                   "boot": {"available": True, "reason": "ok", "lastBootMs": 42000,
                            "averageBootMs": 40000, "boots": 7}}
        manager._on_scan_finished(TaskResult(success=True, message="ok", data=payload))
        qapp.processEvents()
        text = manager._subtitle.text()
        assert "Last boot took 42.0s" in text
        assert "average 40.0s over 7 boots" in text
        assert "1 entry was measured" in text

    def test_a_long_subtitle_spans_the_dialog_instead_of_a_narrow_column(self, manager, qapp):
        """The header row set the title column beside a stretch, so a
        word-wrapped subtitle was squeezed to its narrowest wrap. The old
        one-sentence subtitle hid that; the estimate notice is three
        sentences, and it rendered as a ~300px column five lines deep."""
        payload = {"items": [_startup_item()],
                   "boot": {"available": False, "reason": "needs-admin"}}
        manager._on_scan_finished(TaskResult(success=True, message="ok", data=payload))
        for _ in range(3):
            qapp.processEvents()
        assert manager._subtitle.width() >= 0.8 * manager._stack.width(), (
            f"the subtitle is {manager._subtitle.width()}px wide in a "
            f"{manager._stack.width()}px dialog")

    def test_the_subtitle_says_why_badges_are_estimates(self, manager, qapp):
        """An estimate must never pass for a measurement silently."""
        payload = {"items": [_startup_item()],
                   "boot": {"available": False, "reason": "needs-admin"}}
        manager._on_scan_finished(TaskResult(success=True, message="ok", data=payload))
        qapp.processEvents()
        assert "estimates" in manager._subtitle.text()
        assert "needs administrator" in manager._subtitle.text()
