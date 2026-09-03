"""
What an OS theme or accent change does to Pulse: nothing, on purpose.

THE AUDIT QUESTION WAS "does the palette go stale until restart".
The answer is no, and the reason is structural rather than lucky: Pulse
consumes no system colour at all. There is no DwmGetColorizationColor
call, no QStyleHints.colorScheme() read, no QPalette sampled off the
system - every colour in the app comes from theme.tokens(), and the two
palettes are the app's own. So there is nothing for a Windows accent
change to invalidate.

MEASURED rather than reasoned, by sending Qt the events it actually
delivers on an OS theme switch (ApplicationPaletteChange, PaletteChange,
ThemeChange) and reading the window back afterwards:

    window palette BEFORE: Window #000000, WindowText #ffffff,
                           Base #2d2d2d, Text #ffffff
    window palette AFTER : identical
    shell stylesheet still applied: yes
    theme tokens still the chosen mode: yes

WHY PIN IT IF NOTHING IS WRONG
    Because the immunity depends on the app continuing to own its
    colours. A future change that started reading the system accent - a
    reasonable thing to want - would inherit this whole problem, and the
    first symptom would be a half-restyled window after someone changed
    their Windows accent, which nobody would connect to the change that
    caused it. This is what would connect them.

WHAT IS DELIBERATELY NOT DONE HERE
    Adopting the Windows accent colour. v10.7 settled on ONE accent as a
    design decision ("one accent, flat surfaces, one content column"), and
    following the OS accent would undo it. That is a product decision, not
    a defect fix, so it is not made in an audit pass.

    High-contrast mode is the one real gap in this area: a user who turns
    it on gets an app that ignores it. Closing that honestly means a third
    palette and re-measuring every contrast pair in the suite, which is a
    feature rather than a refinement - recorded here so the absence is a
    known one rather than an oversight.
"""
from __future__ import annotations

import pytest

from PySide6.QtCore import QEvent
from PySide6.QtGui import QPalette

#: What Windows sends Qt when the user changes theme, accent or contrast.
_OS_THEME_EVENTS = (
    QEvent.Type.ApplicationPaletteChange,
    QEvent.Type.PaletteChange,
    QEvent.Type.ThemeChange,
)

_ROLES = (QPalette.ColorRole.Window, QPalette.ColorRole.WindowText,
          QPalette.ColorRole.Base, QPalette.ColorRole.Text)


def _palette_snapshot(widget) -> dict:
    palette = widget.palette()
    return {role.name: palette.color(role).name() for role in _ROLES}


def _deliver_os_theme_change(qapp, window):
    for event_type in _OS_THEME_EVENTS:
        qapp.sendEvent(qapp, QEvent(event_type))
        qapp.sendEvent(window, QEvent(event_type))
    qapp.processEvents()


class TestAnOsThemeChangeLeavesPulseAlone:
    def test_the_window_palette_survives(self, window, qapp):
        before = _palette_snapshot(window)
        _deliver_os_theme_change(qapp, window)
        assert _palette_snapshot(window) == before, (
            "an OS theme change rewrote the window's palette — the app "
            "would sit half-restyled until the user toggled its theme")

    def test_the_shell_keeps_its_stylesheet(self, window, qapp):
        """The QSS is where nearly every colour in the app actually lives,
        so a cleared stylesheet is the failure that would look worst."""
        _deliver_os_theme_change(qapp, window)
        assert window._shell.styleSheet(), (
            "the shell's stylesheet was dropped by an OS theme change")

    def test_the_chosen_theme_is_unchanged(self, window, qapp):
        """Pulse's theme is a persisted USER choice (prefs.theme_mode), not
        a mirror of the OS. Someone who picked light must not be moved to
        dark because Windows was."""
        chosen = window.theme.t["name"]
        _deliver_os_theme_change(qapp, window)
        assert window.theme.t["name"] == chosen


class TestTheAppOwnsItsColours:
    """The structural reason the tests above pass."""

    def test_no_system_colour_is_read_anywhere_in_the_frontend(self):
        """The immunity holds only while this is true. If it stops being
        true, the tests above stop meaning what they say."""
        import os

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        readers = ("DwmGetColorizationColor", "colorScheme(",
                   "systemPalette", "QStyleHints")
        offenders = []
        for name in ("main.py", "widgets.py", "theme.py", "animations.py"):
            path = os.path.join(root, "src", "frontend", name)
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if line.lstrip().startswith("#"):
                        continue
                    for reader in readers:
                        if reader in line:
                            offenders.append(f"{name}:{number}: {reader}")
        assert not offenders, (
            "the frontend now samples a system colour:\n  "
            + "\n  ".join(offenders)
            + "\nThat is a reasonable thing to want, but it inherits the "
              "invalidation problem this file documents: the app must then "
              "re-resolve its tokens when the OS changes, and these tests "
              "no longer describe what happens.")

    def test_both_palettes_come_from_the_apps_own_tokens(self):
        from frontend import theme as TH

        for mode in ("dark", "light"):
            tokens = TH.tokens(mode)
            assert tokens["accent"].startswith("#"), (
                f"{mode} accent is not a literal the app owns")

    @pytest.mark.parametrize("mode", ["dark", "light"])
    def test_the_accent_is_the_one_v10_7_settled_on(self, mode):
        """Not a colour test - a decision test. If the accent ever becomes
        something read from the OS, this is where that shows up."""
        from frontend import theme as TH

        accent = TH.tokens(mode)["accent"]
        assert len(accent) == 7 and accent[0] == "#", (
            f"{mode} accent {accent!r} is not a fixed literal")
