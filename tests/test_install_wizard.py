"""
tests/test_install_wizard.py

THE SINGLE-APP MODAL OFFERS ONE ACTION AND ONE ESCAPE HATCH.

ToolInstallWizardDialog is what a catalog row's "⋯", an Update Center
row's "⋯" and the Edge/OneDrive restore flow all open. It used to present
three equal GlassCards — "One-Click Automated Install", "Official Download
Link", "Local File / Manual Selection" — and the shape was the problem.

Every tool this dialog opens for HAS a working winget package: that is the
entry condition, since it is only ever reached from a catalog row, an
update row, or a bundled-app restore. So the automated install is the
right answer in every case, and presenting it as one of three peers made a
solved problem look like an open question. Path C was worse than redundant:
it was the only route in the app that ran an arbitrary executable the
engine had never seen, offered to a user who would first have had to find,
download and remember the location of an installer the dialog was about to
fetch for them.

So the dialog is now a primary BUTTON and a secondary LINK, and the
local-file path is gone end to end — the card, `mode == "local"`, the
`local_installer` outcome on both selector dialogs, main.py's plumbing,
PowerShellTask's `-LocalInstallerPath`, core.ps1's parameter, the
InstallLocalFile dispatcher case and Invoke-GuiLocalInstall. Nothing else
reached any of it.

These tests pin both halves: what the dialog now presents, and that the
removed path did not survive anywhere as an unreachable entry point.
"""
from __future__ import annotations

import os
import re

import pytest

from conftest import show_dialog, settle

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8-sig") as handle:
        return handle.read()


@pytest.fixture
def wizard(floating, qapp):
    from frontend.widgets import ToolInstallWizardDialog

    dialog = ToolInstallWizardDialog(
        floating, "Valve.Steam", "Steam",
        "The largest PC game store and launcher.",
        "https://store.steampowered.com/about/", floating.theme.t)
    show_dialog(qapp, dialog)
    yield dialog
    dialog._parked = False
    dialog.reject()
    dialog.deleteLater()
    settle(qapp, 40)


# ============================================================
#  WHAT THE DIALOG PRESENTS
# ============================================================
class TestTwoOptions:

    def test_the_local_file_card_is_gone(self, wizard, qapp):
        """THE DEFECT, stated as the text a user would read."""
        from PySide6.QtWidgets import QLabel

        text = " ".join(label.text() for label in wizard.findChildren(QLabel))
        for phrase in ("Local File", "Manual Selection",
                       "Already downloaded the installer"):
            assert phrase not in text, (
                f"the wizard still offers {phrase!r}")

    def test_there_are_no_glasscards_left(self, wizard, qapp):
        """The three-card layout is what made the three routes read as
        peers. A single remaining card would be the same mistake with one
        fewer option."""
        from frontend.widgets import GlassCard
        cards = wizard.findChildren(GlassCard)
        assert not cards, (
            f"{len(cards)} GlassCard(s) survive — the wizard is meant to be "
            "a primary button and a secondary link")

    def test_the_install_is_the_elevated_primary(self, wizard, qapp):
        """It carries the same accent treatment as every other dialog's
        confirming action, so "the thing this sheet is for" looks the same
        here as it does in the catalog behind it."""
        from frontend import theme as TH

        t = wizard.parent().theme.t
        assert wizard.install_btn.text() == "Automated Install (winget)"
        assert wizard.install_btn.isDefault(), (
            "the install is not the default action, so Enter does nothing")
        assert wizard.install_btn.styleSheet() == TH.dialog_go_qss(
            t, t["accent"])

    def test_the_website_is_a_secondary_link(self, wizard, qapp):
        """It does not install anything — it opens a browser and closes
        this sheet. Giving it button weight is what made the old Path B
        card read as a second way to install, which it never was."""
        from frontend import theme as TH

        assert wizard.website_btn.text() == "Visit Official Website"
        t = wizard.parent().theme.t
        assert wizard.website_btn.styleSheet() == TH.link_button_qss(
            t, t["accent"])
        assert wizard.website_btn.styleSheet() != wizard.install_btn.styleSheet()

    def test_accepting_can_only_mean_install(self, wizard, qapp):
        """Every caller now reads Accepted as "deploy this one AppId". A
        second accepting outcome would silently deploy on a path that
        meant something else."""
        wizard._choose_winget()
        assert wizard.mode == "winget"
        assert wizard.result() == wizard.DialogCode.Accepted

    def test_the_website_hands_off_and_rejects(self, wizard, qapp,
                                               monkeypatch):
        """Opening the browser is the whole errand — there is nothing left
        for Pulse to do, so it must not also queue an install."""
        from frontend import widgets as W

        opened = []
        monkeypatch.setattr(W.QDesktopServices, "openUrl",
                            lambda url: opened.append(url.toString()))
        wizard._choose_url("https://example.invalid/download", "Steam")

        assert opened == ["https://example.invalid/download"]
        assert wizard.mode is None, "the hand-off also armed an install"
        assert wizard.result() == wizard.DialogCode.Rejected

    def test_a_missing_url_falls_back_to_a_search(self, wizard, qapp,
                                                  monkeypatch):
        """The Update Center passes "" — it lists whatever winget reports
        as upgradable, which is not limited to the catalog and so has no
        curated URL."""
        from frontend import widgets as W

        opened = []
        monkeypatch.setattr(W.QDesktopServices, "openUrl",
                            lambda url: opened.append(url.toString()))
        wizard._choose_url("", "Some Off-Catalog App")
        assert opened and "Some Off-Catalog App" in opened[0]

    def test_no_file_picker_can_be_reached(self, wizard, qapp):
        """The behaviour behind the removed card, not just its label."""
        assert not hasattr(wizard, "_choose_local")
        assert not hasattr(wizard, "local_path")


# ============================================================
#  THE REMOVED PATH, END TO END
# ============================================================
class TestTheLocalPathIsGone:
    """A half-removed feature is worse than either state: an entry point
    nothing can reach still runs an arbitrary executable if something
    finds it."""

    def test_no_selector_hands_back_a_local_installer(self):
        widgets = _read("src", "frontend", "widgets.py")
        code = "\n".join(line for line in widgets.splitlines()
                         if not line.strip().startswith("#"))
        # Prose in a docstring explaining the removal is fine; an
        # assignment is not.
        assert not re.search(r"self\.local_installer\s*=", code)
        assert not re.search(r'mode\s*==\s*"local"', code)

    def test_the_task_pipeline_no_longer_carries_one(self):
        for module in ("main.py",):
            source = _read("src", "frontend", module)
            assert "local_installer_path" not in source
        helpers = _read("src", "utils", "helpers.py")
        assert "local_installer_path" not in helpers
        assert "-LocalInstallerPath" not in helpers

    def test_the_backend_parameter_and_case_are_gone(self):
        core = _read("src", "backend", "core.ps1")
        assert "LocalInstallerPath" not in core
        dispatcher = _read("src", "backend", "modules", "30-GuiDispatcher.ps1")
        assert '"InstallLocalFile" {' not in dispatcher
        engine = _read("src", "backend", "modules", "04-SoftwareEngine.ps1")
        assert "function Invoke-GuiLocalInstall" not in engine

    def test_nothing_still_advertises_the_task(self):
        """The dispatcher's `default` branch answers an unknown task with a
        clean ERROR, so a stale reference would not crash — it would just
        report a failure the user cannot act on."""
        for module in ("main.py", "widgets.py", "menu_structure.py"):
            source = _read("src", "frontend", module)
            code = "\n".join(line for line in source.splitlines()
                             if not line.strip().startswith("#"))
            assert '"InstallLocalFile"' not in code, (
                f"{module} still names the removed task")
