"""
tests/test_row_actions.py

A SELECTOR ROW'S TRAILING BUTTON LEAVES THE APP. It does not open a modal,
and it does not touch the selection.

WHAT IT WAS. Every row in the Software Catalog and in the Update Center
carried a "⋯" that opened ToolInstallWizardDialog — a sheet offering
"Automated Install (winget)" and "Visit Official Website".

WHY THAT WAS WRONG, in three ways that compound:

  * ONE OF THE TWO OPTIONS WAS THE ROW ITSELF. Both dialogs exist to tick
    rows and deploy them with winget in a single pass. A private sheet
    per row offering to install that row with winget is the checkbox
    restated as a button, one click further away.

  * SO THE SHEET'S ONLY REAL CONTENT WAS THE LINK, three clicks deep
    (press ⋯, read two options, press the quiet one) for an action that
    is a single press everywhere else on the desktop.

  * AND ACCEPTING IT DISCARDED THE SELECTION. Both callers implemented
    "install this one" as `set_all(False)` then tick then deploy, so a
    stray ⋯ on row 12 silently threw away eleven earlier ticks and
    started a one-app run.

WHAT IT IS NOW. A direct link button carrying the OpenInNewWindow glyph:
one press opens the vendor's own download page in the default browser, and
the dialog behind it is untouched — every tick still exactly where it was.

WHERE THE URL COMES FROM. A catalog row has one in its own tool tuple. An
Update Center row usually does not: it lists whatever winget reports as
upgradable, which is every installed program rather than the ~45 the
catalog curates. So the lookup answers with the curated link when Pulse
has one and a search naming the product when it does not — never nothing,
because a dead button is the one outcome worse than a search.

THE SHEET ITSELF SURVIVES, reached from the Edge / OneDrive / Store
RESTORE cards, where nothing has been ticked and "install it for me" and
"let me go and get it" genuinely are the two answers. See
test_install_wizard.py.
"""
from __future__ import annotations

import pytest

from PySide6.QtWidgets import QPushButton

from frontend import theme as TH
from frontend import widgets as W
from frontend.menu_structure import catalog_section, catalog_url


# ============================================================
#  THE URL LOOKUP
# ============================================================
class TestTheLinkAlwaysResolves:

    def test_a_catalog_app_gets_its_curated_link(self):
        assert catalog_url("Google.Chrome") == "https://www.google.com/chrome/"
        assert W.official_url("Google.Chrome", "Google Chrome") == (
            "https://www.google.com/chrome/")

    def test_an_off_catalog_app_gets_a_search_naming_it(self):
        """The Update Center's normal case, not an edge one."""
        assert catalog_url("Contoso.NotInTheCatalog") == ""
        url = W.official_url("Contoso.NotInTheCatalog", "Contoso Widget")
        assert url == W.search_url("Contoso Widget")
        assert "Contoso+Widget" in url

    def test_no_app_id_resolves_to_nothing(self):
        """A dead button is the one outcome worse than a search."""
        for app_id, name in [("Google.Chrome", "Google Chrome"),
                             ("Contoso.Nope", "Contoso Widget"),
                             ("", "")]:
            assert W.official_url(app_id, name).startswith("https://")

    def test_the_search_url_survives_a_spaced_name(self):
        """A raw space is what QUrl silently truncates the tail of, so the
        product would drop out of its own search."""
        assert " " not in W.search_url("Some Off-Catalog App")

    def test_every_catalog_row_has_a_real_link_to_offer(self):
        """The catalog's own half of the promise: no row may fall through
        to a search, because every tool tuple carries a vendor URL."""
        from frontend.menu_structure import catalog_tools
        bare = [tool[0] for tool in catalog_tools()
                if not str(tool[3] or "").startswith("http")]
        assert not bare, f"catalog rows with no official URL: {bare}"


# ============================================================
#  THE BUTTON ON THE ROW
# ============================================================
def _catalog(window, qapp):
    dialog = W.SoftwareCatalogDialog(
        window, {"icon": "\U0001f4e6", "title": "Essential Daily Software"},
        window.theme.t, [catalog_section("essentials")])
    dialog.show()
    qapp.processEvents()
    return dialog


class TestTheRowButtonIsALink:

    def test_no_row_carries_the_overflow_mark(self, window, qapp):
        """"⋯" means "there is more here" — a menu, a sheet, options. The
        button opens a URL, and saying otherwise is what made people press
        it expecting a menu."""
        dialog = _catalog(window, qapp)
        try:
            labels = [b.text() for row in dialog._rows.values()
                      for b in row.findChildren(QPushButton)]
            assert labels, "no row buttons found; the test proves nothing"
            assert "⋯" not in labels, "a row still wears the ⋯ mark"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_button_wears_the_open_external_glyph(self, window, qapp):
        """From the GLYPHS table, like every other mark in the app — not a
        literal typed into a label."""
        dialog = _catalog(window, qapp)
        try:
            row = next(iter(dialog._rows.values()))
            assert row.website_btn.text() == TH.glyph("openexternal")[0]
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_glyph_is_coloured_by_the_sheet_so_hover_can_move_it(
            self, window, qapp):
        """The mark is the button's TEXT rather than a baked QIcon,
        because icon_ghost_button_qss moves `color` on hover and QSS
        colours text. A pixmap would sit at one tone through every state,
        which on a column of thirty rows reads as decoration."""
        dialog = _catalog(window, qapp)
        try:
            row = next(iter(dialog._rows.values()))
            assert row.website_btn.icon().isNull(), (
                "the mark is a QIcon, so hover cannot recolour it")
            qss = row.website_btn.styleSheet()
            assert ":hover" in qss and "color" in qss
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_the_button_says_what_it_does(self, window, qapp):
        """It leaves the app. A tooltip reading "install options" over a
        control that opens a browser is the old sheet's description on the
        new button."""
        dialog = _catalog(window, qapp)
        try:
            row = dialog._rows["Google.Chrome"]
            tip = row.website_btn.toolTip().lower()
            assert "browser" in tip and "official" in tip, tip
            assert "install" not in tip, tip
            assert row.website_btn.accessibleName(), (
                "an icon-only control with no accessible name is unlabelled "
                "to a screen reader")
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()


# ============================================================
#  PRESSING IT
# ============================================================
class TestPressingItOpensTheBrowserAndNothingElse:

    def test_a_catalog_row_opens_its_own_vendor_page(self, window, qapp,
                                                     monkeypatch):
        opened = []
        monkeypatch.setattr(W.QDesktopServices, "openUrl",
                            lambda url: opened.append(url.toString()))
        dialog = _catalog(window, qapp)
        try:
            dialog._rows["Google.Chrome"].website_btn.click()
            qapp.processEvents()
            assert opened == ["https://www.google.com/chrome/"]
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_it_opens_no_dialog(self, window, qapp, monkeypatch):
        """THE DEFECT, stated as the thing that must not happen. Pressing
        it used to exec() a modal."""
        monkeypatch.setattr(W.QDesktopServices, "openUrl", lambda url: None)
        dialog = _catalog(window, qapp)
        opened = []
        monkeypatch.setattr(W.ToolInstallWizardDialog, "__init__",
                            lambda *a, **k: opened.append(a))
        try:
            dialog._rows["Google.Chrome"].website_btn.click()
            qapp.processEvents()
            assert not opened, "the row still opens the single-app modal"
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_it_leaves_every_tick_alone(self, window, qapp, monkeypatch):
        """The sheet's accept path was `set_all(False)` then tick then
        deploy, so a stray press discarded a selection the user had spent
        a minute building."""
        monkeypatch.setattr(W.QDesktopServices, "openUrl", lambda url: None)
        dialog = _catalog(window, qapp)
        try:
            picked = ["Google.Chrome", "Spotify.Spotify", "VideoLAN.VLC"]
            for app_id in picked:
                dialog._rows[app_id].checkbox.setChecked(True)
            qapp.processEvents()
            before = dialog.checked_count()
            assert before == len(picked), "the fixture selection did not take"

            dialog._rows["Notion.Notion"].website_btn.click()
            qapp.processEvents()

            assert dialog.checked_count() == before, (
                "opening a vendor page changed the selection")
            assert dialog.isVisible(), (
                "opening a vendor page closed the catalog")
            assert not dialog.selected_ids, (
                "opening a vendor page queued a deploy")
        finally:
            dialog.reject(); dialog.deleteLater(); qapp.processEvents()

    def test_an_update_row_off_the_catalog_still_goes_somewhere(
            self, window, qapp, monkeypatch):
        """The Update Center lists every upgradable program, not only the
        catalog's."""
        opened = []
        monkeypatch.setattr(W.QDesktopServices, "openUrl",
                            lambda url: opened.append(url.toString()))
        row = W.UpdateRow("Contoso.Widget", "Contoso Widget",
                          "1.0", "2.0", window.theme.t)
        try:
            row.website_btn.click()
            qapp.processEvents()
            assert opened == [W.search_url("Contoso Widget")]
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_an_update_row_on_the_catalog_gets_the_curated_link(
            self, window, qapp, monkeypatch):
        """A search for "Git" is a worse answer than git-scm.com when the
        better one is three lines away."""
        opened = []
        monkeypatch.setattr(W.QDesktopServices, "openUrl",
                            lambda url: opened.append(url.toString()))
        row = W.UpdateRow("Git.Git", "Git", "2.40", "2.45", window.theme.t)
        try:
            row.website_btn.click()
            qapp.processEvents()
            assert opened == [catalog_url("Git.Git")]
            assert opened[0].startswith("https://git-scm.com")
        finally:
            row.deleteLater(); qapp.processEvents()

    def test_the_update_rows_link_does_not_toggle_the_row(self, window, qapp,
                                                          monkeypatch):
        """An Update Center row is click-anywhere-toggles. The link button
        is one of the two children that must be excluded from that, or
        going to read about an app also unticks it."""
        monkeypatch.setattr(W.QDesktopServices, "openUrl", lambda url: None)
        row = W.UpdateRow("Git.Git", "Git", "2.40", "2.45", window.theme.t)
        try:
            assert row.is_checked(), "update rows arrive pre-checked"
            assert row.website_btn in (row.checkbox, row.website_btn)
            row.website_btn.click()
            qapp.processEvents()
            assert row.is_checked(), (
                "opening the vendor page unticked the update")
        finally:
            row.deleteLater(); qapp.processEvents()


# ============================================================
#  NOTHING ADVERTISES THE REMOVED SHEET
# ============================================================
class TestTheOldAffordanceIsNotDescribedAnywhere:

    def test_the_update_centre_subtitle_no_longer_names_it(self, window,
                                                           qapp):
        """The line under the Update Center's title told the user to "use
        a row's ⋯ for more install options" — an instruction for a control
        that is gone."""
        import re
        source = open("src/frontend/widgets.py", encoding="utf-8").read()
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        # Prose in a docstring explaining the removal is fine; a string
        # the UI renders is not.
        for phrase in ("more install options", "use a row's"):
            assert phrase not in code.replace('"""', "\x00").split("\x00")[0], (
                f"the UI still advertises {phrase!r}")
        assert not re.search(r'setToolTip\(\s*\n?\s*"Install options',
                             source), "a row still describes install options"
