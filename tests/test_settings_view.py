"""
The Settings surface (v10.14): theme choice, system protection, and a
machine's configuration as a portable profile.

WHAT THIS PAGE IS NOT. It is not a task card. Every other operation in
Pulse is a card that dispatches a named task and streams a verdict; this is
the one surface that holds PREFERENCES (which are the app's, not the
machine's) beside two operations that happen to belong next to them. So the
page itself owns no worker thread and runs nothing: it emits what the user
asked for and main.py's existing pipeline answers, which is what keeps the
live console, the concurrency guard and the admin pre-check in one place.

A PROFILE IS A PLAYBOOK, which is why export and import get so little new
code. The file it writes is a playbook document over the live task catalog,
so parse_playbook validates it and PlaybookRunner applies it — an exported
profile can never name an operation the GUI could not already run.
"""
from __future__ import annotations

import json
import os

import pytest
from PySide6.QtCore import Qt

from frontend import theme as TH


# ============================================================
#  THE PAGE
# ============================================================
@pytest.fixture
def settings(window, qapp):
    from frontend.widgets import SettingsView

    view = SettingsView(window.theme.t, is_admin=True)
    view.show()
    qapp.processEvents()
    yield view
    view.deleteLater()
    qapp.processEvents()


class TestTheGroupedPage:

    def test_it_offers_the_four_declared_groups(self, settings, qapp):
        """Windows 11's own settings shape: titled groups of related rows,
        not a flat column of controls."""
        from PySide6.QtWidgets import QLabel

        titles = {label.text() for label in settings.findChildren(QLabel)}
        for group in ("General", "System Protection",
                       "Configuration Management", "Updates"):
            assert group in titles, f"no {group!r} group on the settings page"

    def test_it_owns_no_worker_thread(self, settings):
        """The page asks; main.py runs. A private worker here would bypass
        the console, the single-task queue and the elevation pre-check."""
        from PySide6.QtCore import QThread

        assert not settings.findChildren(QThread)
        assert not [v for v in vars(settings).values() if isinstance(v, QThread)]

    def test_every_group_shares_identical_card_and_title_qss(self, settings):
        """Cheap insurance against a new group (Updates, or whatever comes
        next) quietly drifting from the padding/elevation the others
        already settled on — every card on this page is the SAME object
        (see _group), so a styling difference between them would mean one
        of them stopped going through it."""
        accent = settings._t["accent"]
        expected_card = TH.report_subcard_qss(settings._t, accent)
        expected_title = TH.report_subcard_title_qss(settings._t)
        for card in settings._cards:
            assert card.styleSheet() == expected_card
        for label in settings._group_titles:
            assert label.styleSheet() == expected_title


class TestTheThemeChoice:

    def test_all_three_modes_are_offered(self, settings):
        assert set(settings.theme_modes()) == {"dark", "light", "system"}

    def test_the_active_mode_is_marked(self, settings, qapp):
        settings.set_theme_mode("light")
        qapp.processEvents()
        assert settings.current_mode() == "light"
        settings.set_theme_mode("system")
        qapp.processEvents()
        assert settings.current_mode() == "system"

    def test_choosing_a_mode_only_asks(self, settings, qapp):
        """The page does not re-skin the app itself — main owns the
        ThemeManager, so one place decides and one place persists."""
        asked: list[str] = []
        settings.theme_mode_requested.connect(asked.append)
        settings.choose_theme_mode("system")
        qapp.processEvents()
        assert asked == ["system"]

    def test_system_sync_says_what_it_follows(self, settings):
        """A control named "System" that does not say whose system is a
        control people have to click to find out."""
        hint = settings.theme_hint("system").lower()
        assert "windows" in hint


class TestSystemProtection:

    def test_it_reports_the_newest_checkpoint(self, settings, qapp):
        settings.set_restore_points({
            "available": True, "enabled": True, "count": 3,
            "points": [{"sequence": 42, "description": "Pulse Restore Point",
                        "created": "2026-09-11 14:05", "ageDays": 0.9,
                        "typeLabel": "Manual checkpoint"}],
        })
        qapp.processEvents()
        text = settings.restore_summary()
        assert "2026-09-11 14:05" in text
        assert "Pulse Restore Point" in text

    def test_it_distinguishes_none_yet_from_protection_being_off(self, settings, qapp):
        """"No checkpoints" and "System Restore is not running" are
        different situations, and only one of them is fixed by clicking
        the button above."""
        settings.set_restore_points({"available": True, "enabled": True,
                                     "count": 0, "points": []})
        qapp.processEvents()
        none_yet = settings.restore_summary().lower()

        settings.set_restore_points({"available": False, "enabled": False,
                                     "count": 0, "points": []})
        qapp.processEvents()
        disabled = settings.restore_summary().lower()

        assert none_yet != disabled
        assert "no" in none_yet
        assert "off" in disabled or "not" in disabled

    def test_it_says_so_while_the_checkpoint_list_is_unread(self, settings):
        """Before the probe answers, the row must not claim there are no
        checkpoints — that is a measurement it has not taken."""
        text = settings.restore_summary().lower()
        assert "checking" in text or "…" in text

    def test_the_button_asks_main_to_run_the_task(self, settings, qapp):
        fired: list[bool] = []
        settings.restore_point_requested.connect(lambda: fired.append(True))
        settings._restore_btn.click()
        qapp.processEvents()
        assert fired == [True]

    def test_an_unelevated_session_is_told_before_it_clicks(self, window, qapp):
        from frontend.widgets import SettingsView

        view = SettingsView(window.theme.t, is_admin=False)
        try:
            assert "administrator" in view.restore_note().lower()
        finally:
            view.deleteLater()
            qapp.processEvents()


class TestConfigurationManagement:

    def test_both_actions_ask_main(self, settings, qapp):
        exported: list[bool] = []
        imported: list[bool] = []
        settings.export_requested.connect(lambda: exported.append(True))
        settings.import_requested.connect(lambda: imported.append(True))
        settings._export_btn.click()
        settings._import_btn.click()
        qapp.processEvents()
        assert exported == [True] and imported == [True]

    def test_the_import_button_says_it_runs_things(self, settings):
        """"Import" alone reads like loading a file. This one applies
        tweaks and installs software on the machine it is run on."""
        text = (settings._import_btn.text() + " "
                + settings._import_btn.toolTip()).lower()
        assert "apply" in text or "run" in text


class TestTheUpdatesSection:
    """A second, synced surface onto the SAME update-check pipeline the
    sidebar footer's UpdateBadge already drives — not a private copy of
    it. See tests/test_update_badge.py for the window-level proof that
    main.py keeps both surfaces in agreement; these two are the page's own
    contract in isolation."""

    def test_the_button_asks_main_not_a_private_worker(self, settings, qapp):
        """Same shape as every other action on this page (see
        TestTheGroupedPage.test_it_owns_no_worker_thread for the page-wide
        "no worker thread" guarantee this relies on): a click can only
        ever ASK, never itself perform the check."""
        fired: list[bool] = []
        settings.update_check_requested.connect(lambda: fired.append(True))
        settings._update_btn.click()
        qapp.processEvents()
        assert fired == [True]

    def test_set_update_state_reflects_every_state(self, settings):
        """Reuses UpdateBadge.TEXTS rather than declaring its own
        vocabulary, so the chrome badge and this section cannot drift into
        different words for the same state."""
        from frontend.widgets import UpdateBadge

        for state, text in UpdateBadge.TEXTS.items():
            settings.set_update_state(state)
            assert settings._update_caption.text() == text


# ============================================================
#  THE PROFILE ITSELF  (no Qt — pure schema)
# ============================================================
class TestTheExportedProfile:

    def _state(self):
        return {"DarkMode": "applied", "GameMode": "applied",
                "DisableMouseAccel": "mixed", "MinimalistTaskbar": "default",
                "ClassicContextMenu": None}

    def test_only_applied_tweaks_travel(self):
        """"Mixed" is a half-formed state on THIS machine and "default" is
        the absence of a choice; exporting either would make a profile that
        imposes a mess or un-does settings on the target."""
        from frontend import playbooks

        doc = playbooks.build_setup_profile(self._state(), [])
        tasks = [step["task"] for step in doc["steps"]]
        assert "DarkMode" in tasks and "GameMode" in tasks
        assert "DisableMouseAccel" not in tasks
        assert "MinimalistTaskbar" not in tasks
        assert "ClassicContextMenu" not in tasks

    def test_it_opens_with_a_restore_point(self):
        from frontend import playbooks

        doc = playbooks.build_setup_profile(self._state(), ["Git.Git"])
        assert doc["steps"][0]["task"] == "CreateRestorePoint"

    def test_the_apps_ride_on_one_install_step(self):
        """InstallCatalogApps takes the selection on -AppIds, so a profile
        of twenty apps is one step rather than twenty."""
        from frontend import playbooks

        doc = playbooks.build_setup_profile(
            {}, ["Git.Git", "Valve.Steam", "Git.Git"])
        installs = [s for s in doc["steps"] if s["task"] == "InstallCatalogApps"]
        assert len(installs) == 1
        assert installs[0]["app_ids"] == ["Git.Git", "Valve.Steam"], (
            "duplicates survived, or catalog order was not preserved")

    def test_every_step_but_the_checkpoint_is_optional(self):
        """A profile runs unattended on a machine nobody is watching: one
        unavailable app must not halt the rest of the setup."""
        from frontend import playbooks

        doc = playbooks.build_setup_profile(self._state(), ["Git.Git"])
        for step in doc["steps"][1:]:
            assert step.get("optional") is True, f"{step['task']} halts the run"

    def test_a_probe_key_with_no_card_is_dropped(self):
        """The state map is keyed by task name, but not every key has a
        card behind it — and a step naming one would fail validation."""
        from frontend import playbooks

        doc = playbooks.build_setup_profile({"NotARealTask": "applied"}, [])
        assert [s["task"] for s in doc["steps"]] == ["CreateRestorePoint"]

    def test_it_round_trips_through_the_playbook_loader(self, tmp_path):
        """THE WHOLE REASON THE FORMAT IS A PLAYBOOK. What export writes,
        the existing validated loader reads and the existing runner runs."""
        from frontend import playbooks

        path = str(tmp_path / f"setup{playbooks.SETUP_SUFFIX}")
        doc = playbooks.build_setup_profile(self._state(), ["Git.Git"],
                                            machine="TEST-PC")
        written = playbooks.write_setup_profile(path, doc)
        assert os.path.isfile(path)

        loaded = playbooks.read_setup_profile(path)
        assert loaded.id == written.id
        assert [s.task for s in loaded.steps] == [s["task"] for s in doc["steps"]]
        assert loaded.steps[1].app_ids == ("Git.Git",)
        assert loaded.needs_admin, "a profile taking a restore point needs admin"

    def test_it_is_validated_before_it_is_written(self, tmp_path):
        """A file this app's own loader would reject is one the user finds
        out about on the machine they were setting up."""
        from frontend import playbooks

        path = str(tmp_path / "bad.pulse.json")
        with pytest.raises(playbooks.PlaybookError):
            playbooks.write_setup_profile(path, {
                "id": "x", "name": "Bad", "steps": [{"task": "NoSuchTask"}]})
        assert not os.path.exists(path), "an invalid profile was still written"

    def test_a_hand_edited_profile_cannot_smuggle_in_a_local_action(self, tmp_path):
        """Playbook rules apply because it IS a playbook: a step may only
        name a backend task, never a GUI-local `@` action."""
        from frontend import playbooks

        path = tmp_path / "sneaky.pulse.json"
        path.write_text(json.dumps({
            "id": "sneaky", "name": "Sneaky",
            "steps": [{"task": "@open_log"}]}), encoding="utf-8")
        with pytest.raises(playbooks.PlaybookError):
            playbooks.read_setup_profile(str(path))


# ============================================================
#  THE SHELL WIRING
# ============================================================
class TestTheSidebarEntry:

    def test_settings_opens_its_page(self, window, qapp):
        window._settings_btn.click()
        qapp.processEvents()
        assert window.stack.currentWidget() is window.settings_view
        window.go_home()
        qapp.processEvents()

    def test_opening_it_deselects_every_module(self, window, qapp):
        window.open_category(0)
        qapp.processEvents()
        window.open_settings()
        qapp.processEvents()
        assert not any(btn.property("selected") for btn in window._nav_buttons)
        window.go_home()
        qapp.processEvents()

    def test_going_home_deselects_settings(self, window, qapp):
        window.open_settings()
        qapp.processEvents()
        window.go_home()
        qapp.processEvents()
        assert not window._settings_btn.property("selected")
        assert window.stack.currentWidget() is window.welcome

    def test_the_page_is_re_skinned_with_everything_else(self, window):
        """A view outside _themed_views would sit in the old palette until
        it was rebuilt — the deferral contract only covers what it lists."""
        assert window.settings_view in window._themed_views()

    def test_choosing_a_mode_moves_the_app_and_is_persisted(
            self, window, qapp, monkeypatch):
        from utils import prefs

        stored: list[str] = []
        monkeypatch.setattr(prefs, "set_theme_mode", stored.append)
        before = window.theme.mode
        try:
            window.settings_view.choose_theme_mode("system")
            qapp.processEvents()
            assert window.theme.mode == "system"
            assert stored and stored[-1] == "system", (
                "the CHOICE was not persisted — storing what it resolved to "
                "would turn 'follow Windows' into a fixed palette")
        finally:
            window.theme.set_mode(before)
            qapp.processEvents()

    def test_the_settings_button_is_reskinned_on_a_theme_switch(
            self, window, qapp):
        """_apply_theme's sweep re-skins update_badge, status_rail,
        titlebar and every _nav_buttons entry on a live switch —
        _settings_btn sat outside _nav_buttons (by design, see the comment
        at its construction) and outside the sweep too (not by design), so
        it froze in whatever palette was current at launch. A dark-launched
        session that later chose light mode would show every other row
        repaint while "Settings" kept rendering dark mode's light-toned
        text over the new light panel — faint, low-contrast, exactly the
        "invisible in light mode" symptom this pins against."""
        before = window.theme.mode
        try:
            window.theme.set_mode("dark")
            qapp.processEvents()
            window.theme.set_mode("light")
            qapp.processEvents()
            assert (window._settings_btn.styleSheet()
                    == TH.nav_button_qss(window.theme.t)), (
                "the Settings button did not pick up the new palette")
        finally:
            window.theme.set_mode(before)
            qapp.processEvents()

    def test_settings_sits_between_the_stretch_and_the_footer(
            self, window, qapp):
        """Windows-11/Fluent pattern: Settings pinned to the very bottom of
        the rail, separated from the module list by the stretch, but still
        above the session footer (update badge + status rail) — not mixed
        into it. Also protects test_update_badge.py's own invariant that
        the badge sits with nothing between it and the rail, since a naive
        "pin to the bottom" fix could have inserted Settings AFTER the
        badge instead of before it.

        The stretch is a QSpacerItem, not a widget — side.itemAt(i).widget()
        returns None for it, so a widget-only index comparison cannot tell
        "before the stretch" from "after" it (both leave the same widget
        order). This walks every layout item, spacer included, instead —
        and specifically the VERTICALLY EXPANDING spacer, since the rail
        also carries two fixed addSpacing() gaps (search-to-section,
        section-to-modules) that are spacers too but are not the stretch
        this button needs to land after."""
        side = window._sidebar.layout()
        items = [side.itemAt(i) for i in range(side.count())]
        spacer_index = next(
            i for i, item in enumerate(items)
            if item.spacerItem() is not None
            and item.spacerItem().expandingDirections() & Qt.Orientation.Vertical)
        settings_index = next(
            i for i, item in enumerate(items)
            if item.widget() is window._settings_btn)
        badge_index = next(
            i for i, item in enumerate(items)
            if item.widget() is window.update_badge)
        rail_index = next(
            i for i, item in enumerate(items)
            if item.widget() is window.status_rail)

        assert settings_index > spacer_index, (
            "Settings still sits above the stretch, among the module buttons")
        assert settings_index < badge_index, (
            "Settings is not above the footer")
        assert badge_index + 1 == rail_index, (
            "the update badge is no longer directly above the status rail "
            "it shares a handler with")
