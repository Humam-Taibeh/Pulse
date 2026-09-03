"""
Icon-only controls had nothing to announce.

WHAT A SCREEN READER ACTUALLY GETS
    Qt builds a QPushButton's accessible NAME from its text. For the
    app's icon-only buttons that text is a Segoe Fluent codepoint out of
    the Private Use Area - U+E921 for minimize, U+E8C8 for copy - so the
    name a reader announces is an unassigned character. Depending on the
    reader that is silence, the word "unknown", or the raw codepoint read
    out as a number.

    The tooltip does not rescue it. Qt maps setToolTip to the accessible
    DESCRIPTION (and QAccessible::Help), not to the name, so a button can
    be perfectly self-explanatory on hover and still be unnameable to
    someone who never sees the hover. Every one of these buttons already
    HAS the right string - the factories take `tip` - it simply was not
    being given to the accessibility layer.

WHY A WALKING TEST RATHER THAN A LIST
    A list of the buttons that exist today is a list that is wrong the
    first time someone adds one. This walks the real window, decides what
    counts as icon-only from the rendered text, and requires a name for
    each - so a new icon button arrives already covered or fails here.

FOCUS POLICY IS DELIBERATELY NOT CHANGED. These are NoFocus by design, to
keep the tab chain to the things a keyboard user is actually navigating
between (see the measured chain: search, four nav entries, the content
area, the card grid). A screen reader reaches them through the UIA tree
regardless of focus policy, so naming them is the fix and widening the
tab order is not.
"""
from __future__ import annotations

import pytest

from PySide6.QtWidgets import QPushButton, QToolButton


def _is_icon_only(button) -> bool:
    """True when the visible text carries no word a reader could announce.

    Anything in the Private Use Area (U+E000-U+F8FF) is an icon font
    codepoint; so is an empty label on a button that paints itself. A
    button reading "Close" is fine and is not this test's business.
    """
    text = (button.text() or "").strip()
    if not text:
        return True
    return all(not ch.isalnum() for ch in text)


def _named(button) -> bool:
    return bool((button.accessibleName() or "").strip())


def _offenders(root) -> list[str]:
    out = []
    for kind in (QPushButton, QToolButton):
        for button in root.findChildren(kind):
            if _is_icon_only(button) and not _named(button):
                out.append(
                    f"{type(button).__name__}(text={button.text()!r}, "
                    f"tooltip={button.toolTip()!r})")
    return out


class TestTheShell:
    def test_every_icon_only_button_on_the_window_is_named(self, window):
        """The persistent chrome: caption buttons, the drawer's output
        tools, the drawer chevron, the status rail."""
        offenders = _offenders(window)
        assert not offenders, (
            f"{len(offenders)} icon-only control(s) announce nothing to a "
            "screen reader:\n  " + "\n  ".join(offenders))

    def test_the_caption_buttons_are_named(self, window):
        """Minimize / maximize / close are the three a reader must be able
        to find on any window, and all three are PUA glyphs here."""
        titlebar = window.titlebar
        for attr in ("_btn_min", "btn_max", "_btn_close"):
            button = getattr(titlebar, attr)
            assert _named(button), f"titlebar.{attr} has no accessible name"

    def test_the_maximize_button_renames_itself_with_its_glyph(
            self, floating, qapp):
        """It is Maximize or Restore depending on state, and the glyph
        already tracks that. A name fixed at construction would tell a
        reader "Maximize" while the button restores."""
        titlebar = floating.titlebar
        floating.showNormal()
        qapp.processEvents()
        normal_name = titlebar.btn_max.accessibleName()

        floating.showMaximized()
        qapp.processEvents()
        try:
            maximized_name = titlebar.btn_max.accessibleName()
            assert maximized_name and maximized_name != normal_name, (
                f"the button announces {normal_name!r} in both states, so a "
                "reader is told it maximizes a window that is maximized")
        finally:
            floating.showNormal()
            qapp.processEvents()

    def test_the_output_tools_are_named(self, window):
        """Copy / export / clear / timestamps - four icon-only ghosts in
        the Activity drawer, and the ones most likely to be hunted for."""
        for tool in window.activity._tools:
            assert _named(tool), (
                f"a drawer output tool with tooltip {tool.toolTip()!r} has "
                "no accessible name")

    def test_a_name_is_not_just_the_glyph_repeated(self, window):
        """The obvious wrong fix: setAccessibleName(char), which satisfies
        a presence check and announces exactly what it did before."""
        for kind in (QPushButton, QToolButton):
            for button in window.findChildren(kind):
                name = (button.accessibleName() or "").strip()
                if not name:
                    continue
                assert any(ch.isalnum() for ch in name), (
                    f"accessible name {name!r} carries no word - it is the "
                    "glyph again under a different property")


class TestDialogs:
    def test_the_command_palette_is_named(self, window, qapp):
        """Ctrl+K is the app's main entry point and its own controls are
        icon-only."""
        from frontend.menu_structure import iter_leaf_items
        from frontend.widgets import CommandPalette

        # Built the way _open_command_palette builds it, so this covers
        # the palette the user actually gets rather than an empty one.
        palette = CommandPalette(window, window.theme.t,
                                 list(iter_leaf_items()))
        try:
            offenders = _offenders(palette)
            assert not offenders, (
                "unnamed icon controls in the command palette:\n  "
                + "\n  ".join(offenders))
        finally:
            palette.deleteLater()
            qapp.processEvents()


class TestTheCardsKeepTheirExistingCoverage:
    def test_cards_still_announce_their_title_and_description(self, window):
        """GlassCard has had accessible name/description since v10; this
        is here so the sweep above cannot be 'satisfied' by removing it."""
        from frontend.widgets import GlassCard

        cards = window.findChildren(GlassCard)
        assert cards, "no cards on the window to check"
        named = [c for c in cards if (c.accessibleName() or "").strip()]
        assert len(named) == len(cards), (
            f"{len(cards) - len(named)} card(s) lost their accessible name")
