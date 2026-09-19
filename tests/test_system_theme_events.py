"""
What an OS theme change does to Pulse — which, as of v10.14, depends on
what the user asked for.

THE ORIGINAL CONTRACT, AND WHY IT CHANGED. Through v10.13 the answer was
"nothing, on purpose": Pulse consumed no system colour at all, so there was
nothing for a Windows theme change to invalidate, and this file pinned that
immunity. It also said what taking the other road would cost:

    "That is a reasonable thing to want, but it inherits the invalidation
     problem this file documents: the app must then re-resolve its tokens
     when the OS changes, and these tests no longer describe what happens."

v10.14 takes that road — the Settings page offers Dark / Light / **System
Sync** — so this file now describes what happens, and the obligation that
sentence named is the first thing below: in system mode the app re-resolves
on the OS event rather than going stale until restart.

WHAT DID NOT CHANGE, AND IS THE WHOLE POINT. What is read from Windows is a
PREFERENCE — light or dark — never a colour. Every token still comes from
theme.tokens(); there is no DwmGetColorizationColor call, no sampled
QPalette, no system accent. So "the app owns its colours" is still true and
still pinned; what moved is only WHICH of the app's own two palettes a
standing choice resolves to.

AN EXPLICIT CHOICE IS STILL ABSOLUTE. Someone who picked light is never
moved to dark because Windows was. That was the original promise and it
survives intact — it is now a promise about modes "dark" and "light"
specifically, rather than about the app as a whole.

WHAT IS DELIBERATELY STILL NOT DONE
    Adopting the Windows ACCENT colour. v10.7 settled on one accent as a
    design decision and following the OS accent would undo it. Reading a
    light/dark preference does not open that door — it is a different fact,
    and the scan below keeps the colour readers out.

    High-contrast mode remains the known gap: closing it honestly means a
    third palette and re-measuring every contrast pair in the suite.
"""
from __future__ import annotations

import pytest

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QGuiApplication, QPalette

from frontend import theme as TH

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


class TestAnOsThemeChangeLeavesAnExplicitChoiceAlone:
    """The original guarantee, now scoped to the two explicit modes."""

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

    def test_a_chosen_theme_is_not_moved_by_the_os(self, window, qapp, monkeypatch):
        """Someone who picked light must not be moved to dark because
        Windows was. The window's own mode is explicit, so even with the OS
        reporting the opposite scheme the tokens must not budge."""
        assert window.theme.mode in ("dark", "light"), (
            "the shared window should be on an explicit mode for this test")
        chosen = window.theme.t["name"]
        opposite = "light" if chosen == "dark" else "dark"
        monkeypatch.setattr(TH, "system_scheme", lambda: opposite)
        _deliver_os_theme_change(qapp, window)
        assert window.theme.t["name"] == chosen


class TestSystemModeFollowsTheOs:
    """The new mode, and the obligation the old file named."""

    def test_it_resolves_to_the_os_preference(self, qapp, monkeypatch):
        manager = TH.ThemeManager("system")
        monkeypatch.setattr(TH, "system_scheme", lambda: "light")
        assert manager.resolved == "light"
        assert manager.t["name"] == "light"
        monkeypatch.setattr(TH, "system_scheme", lambda: "dark")
        assert manager.resolved == "dark"
        assert manager.t["name"] == "dark"

    def test_the_stored_choice_stays_system(self, qapp, monkeypatch):
        """THE REASON `mode` AND `resolved` ARE DIFFERENT PROPERTIES.
        Persisting what system mode resolved to would turn "follow Windows"
        into "light" the first time a light Windows answered it."""
        manager = TH.ThemeManager("system")
        monkeypatch.setattr(TH, "system_scheme", lambda: "light")
        assert manager.t["name"] == "light"
        assert manager.mode == "system"

    def test_an_os_change_re_resolves_instead_of_going_stale(self, qapp, monkeypatch):
        """The invalidation problem the previous contract warned about: the
        app must re-emit its tokens when Windows changes its mind."""
        manager = TH.ThemeManager("system")
        seen: list[str] = []
        manager.changed.connect(lambda t: seen.append(t["name"]))
        monkeypatch.setattr(TH, "system_scheme", lambda: "light")
        manager._on_system_scheme()
        assert seen == ["light"], (
            "system mode did not re-resolve on an OS scheme change — the "
            "window would sit in the old palette until restart")

    def test_an_explicit_mode_ignores_the_same_event(self, qapp, monkeypatch):
        manager = TH.ThemeManager("dark")
        seen: list[str] = []
        manager.changed.connect(lambda t: seen.append(t["name"]))
        monkeypatch.setattr(TH, "system_scheme", lambda: "light")
        manager._on_system_scheme()
        assert seen == [], "an explicit choice was moved by the OS"

    def test_toggling_out_of_system_pins_an_explicit_choice(self, qapp, monkeypatch):
        """A manual toggle is an override. Leaving the mode on "system"
        would let Windows undo the user's click at any moment."""
        manager = TH.ThemeManager("system")
        monkeypatch.setattr(TH, "system_scheme", lambda: "dark")
        manager.toggle()
        assert manager.mode == "light"
        assert manager.t["name"] == "light"

    def test_the_mode_change_is_announced_even_when_the_palette_does_not(
            self, qapp, monkeypatch):
        """Choosing System on a machine that is already dark repaints
        nothing — but preferences still have to record the choice, which is
        why the two signals are separate."""
        monkeypatch.setattr(TH, "system_scheme", lambda: "dark")
        manager = TH.ThemeManager("dark")
        modes: list[str] = []
        repaints: list[str] = []
        manager.mode_changed.connect(modes.append)
        manager.changed.connect(lambda t: repaints.append(t["name"]))
        manager.set_mode("system")
        assert modes == ["system"]
        assert repaints == [], "re-skinned the whole UI for an invisible switch"

    def test_prefs_accepts_the_new_mode(self):
        from utils import prefs

        assert "system" in prefs.THEME_MODES
        assert set(prefs.THEME_MODES) == set(TH.ThemeManager.MODES), (
            "the stored modes and the manager's modes have drifted")

    @pytest.mark.parametrize("scheme,expected", [
        (Qt.ColorScheme.Light, "light"),
        (Qt.ColorScheme.Dark, "dark"),
        (Qt.ColorScheme.Unknown, "dark"),
    ])
    def test_every_qt_scheme_maps_to_one_of_the_apps_palettes(
            self, qapp, monkeypatch, scheme, expected):
        """Unknown resolves to the app's own default rather than to a third
        look — there are two palettes and there is no other answer."""
        hints = QGuiApplication.instance().styleHints()
        monkeypatch.setattr(type(hints), "colorScheme", lambda self: scheme)
        assert TH.system_scheme() == expected


class TestTheAppOwnsItsColours:
    """The structural reason the guarantees above hold."""

    #: Readers that would sample an actual COLOUR from the system. None of
    #: these may appear anywhere in the frontend — reading a light/dark
    #: preference is a different fact from adopting Windows' palette.
    _COLOUR_READERS = ("DwmGetColorizationColor", "systemPalette",
                       "QPalette.Window", "standardPalette")

    #: Reading the PREFERENCE is permitted, in one file and one place: see
    #: theme.system_scheme, which is why it imports QGuiApplication locally
    #: rather than at module scope.
    #:
    #: NOT `QGuiApplication` itself, which is a general Qt class the app
    #: uses for screens, clipboards and DPI — and which main.py's own
    #: DPI-watcher docstring discusses in prose. The appearance API is the
    #: thing that must not spread; naming the whole class caught a comment.
    _PREFERENCE_READERS = ("colorScheme", "QStyleHints")

    _FRONTEND = ("main.py", "widgets.py", "theme.py", "animations.py")

    @staticmethod
    def _scan(name: str, needles) -> list[str]:
        import os

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "src", "frontend", name)
        hits = []
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if line.lstrip().startswith("#"):
                    continue
                for needle in needles:
                    if needle in line:
                        hits.append(f"{name}:{number}: {needle}")
        return hits

    def test_no_system_colour_is_sampled_anywhere_in_the_frontend(self):
        """The original guard, and it is unchanged in substance: the app
        must keep owning every colour it paints."""
        offenders = []
        for name in self._FRONTEND:
            offenders += self._scan(name, self._COLOUR_READERS)
        assert not offenders, (
            "the frontend now samples a system COLOUR:\n  "
            + "\n  ".join(offenders)
            + "\nSystem Sync reads a light/dark PREFERENCE only; adopting "
              "Windows' own colours would undo the single-accent decision "
              "v10.7 settled on.")

    def test_only_the_theme_module_reads_the_os_preference(self):
        """One call site, so "does Pulse look at the OS?" has one answer.
        A colorScheme() read inside a widget would re-introduce exactly the
        staleness this file exists to prevent, because only ThemeManager is
        wired to re-emit."""
        offenders = []
        for name in self._FRONTEND:
            if name == "theme.py":
                continue
            offenders += self._scan(name, self._PREFERENCE_READERS)
        assert not offenders, (
            "the OS appearance preference is read outside theme.py:\n  "
            + "\n  ".join(offenders)
            + "\nRoute it through theme.system_scheme() / ThemeManager, "
              "which re-resolves and re-emits when Windows changes.")

    def test_both_palettes_come_from_the_apps_own_tokens(self):
        for mode in ("dark", "light"):
            tokens = TH.tokens(mode)
            assert tokens["accent"].startswith("#"), (
                f"{mode} accent is not a literal the app owns")

    @pytest.mark.parametrize("mode", ["dark", "light"])
    def test_the_accent_is_the_one_v10_7_settled_on(self, mode):
        """Not a colour test - a decision test. If the accent ever becomes
        something read from the OS, this is where that shows up."""
        accent = TH.tokens(mode)["accent"]
        assert len(accent) == 7 and accent[0] == "#", (
            f"{mode} accent {accent!r} is not a fixed literal")
