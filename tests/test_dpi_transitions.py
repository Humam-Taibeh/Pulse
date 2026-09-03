"""
Moving the window to a differently-scaled monitor re-renders what was
baked for the old one.

WHAT BAKES A RATIO
    Two things in this app rasterise at the screen's device-pixel ratio and
    then hold the result:

      * the sidebar's search glyph (theme.glyph_icon, v10.9.3), and
      * every catalog row's app icon (appicons.app_icon, v10.9.5).

    Both are regenerated inside PulseApp._apply_theme, because both also
    depend on the palette — which is what makes the fix here cheap: the
    path that redraws them already exists, is already exercised on every
    theme toggle, and needed only to be reachable from a second trigger.

THE GAP THIS CLOSES
    appicons keys its pixmap cache on the ratio, so a fresh LOOKUP after a
    monitor change already renders correctly. What nothing did was ask for
    a fresh lookup: a widget holding a pixmap rasterised at 1.5 goes on
    holding it after the window moves to a 1.0 screen, and Qt rescales it
    to fit — the soft-icon defect v10.9.3 called unacceptable, arriving by
    a different route.

    The honest scope: this is a cosmetic staleness that self-corrects the
    next time the theme is toggled or the owning dialog is reopened. It is
    fixed here because the trigger costs one signal connection.
"""
from __future__ import annotations

import pytest

from utils import appicons


@pytest.fixture
def live_window(window):
    """`window` with the close flag explicitly cleared.

    The window fixture is session-scoped and shared, and the tests that
    exercise the close path legitimately leave `_shutting_down` set on it.
    The screen-change handler refuses to work in that state BY DESIGN (see
    test_it_is_inert_while_shutting_down below), so these tests have to
    state their precondition rather than inherit whatever ran before them
    — the alternative is a suite that passes file-by-file and fails as a
    whole, which is how this was found.
    """
    window._shutting_down = False
    yield window


class TestScreenChangeInvalidation:
    def test_the_window_listens_for_a_screen_change(self, live_window, qapp):
        """The connection is made once the native window exists — before
        that windowHandle() is None and there is no signal to connect."""
        assert live_window.windowHandle() is not None, (
            "no native window; the screenChanged hook cannot exist")
        assert live_window._screen_hooked, (
            "PulseApp never connected windowHandle().screenChanged, so a "
            "move to a differently-scaled monitor leaves every "
            "ratio-baked pixmap rendered for the old screen")

    def test_a_screen_change_drops_the_ratio_baked_icon_cache(
            self, live_window, qapp):
        """The cache is keyed on the ratio, so stale entries are harmless —
        but they are also dead weight after a move, and clearing them is
        what guarantees the re-render below actually re-rasterises rather
        than serving the pre-move pixmap back."""
        theme = {"name": "dark", "dialog_bg": "#16181d"}
        appicons.app_icon("Some App For This Test", 24, theme)
        assert appicons._PIXMAP_CACHE, "nothing cached; test proves nothing"

        live_window._on_screen_changed(None)
        qapp.processEvents()

        assert not appicons._PIXMAP_CACHE, (
            "the icon cache survived a screen change")

    def test_a_screen_change_re_applies_the_theme(self, live_window, qapp,
                                                  monkeypatch):
        """Re-applying the theme is what actually redraws the search glyph
        and every visible icon at the new ratio. Asserted on the call
        rather than on pixels because the ratio cannot be changed from
        inside a test — there is only one screen here."""
        calls = []
        monkeypatch.setattr(live_window, "_apply_theme",
                            lambda t: calls.append(t))

        live_window._on_screen_changed(None)
        qapp.processEvents()

        assert calls, (
            "a screen change did not re-apply the theme, so nothing "
            "re-rasterised for the new ratio")

    def test_it_is_inert_while_shutting_down(self, window, qapp):
        """Same contract every other deferred callback in this window
        honours: a close in progress starts no new work. A screenChanged
        can arrive while the window is being torn down (moving a monitor
        away, or a display waking), and re-skinning a dying window is the
        shape of the RuntimeError _settle_background_threads exists to
        avoid."""
        theme = {"name": "dark", "dialog_bg": "#16181d"}
        appicons.app_icon("Another App For This Test", 24, theme)
        window._shutting_down = True
        try:
            window._on_screen_changed(None)
            qapp.processEvents()
            assert appicons._PIXMAP_CACHE, (
                "a shutting-down window still did the re-skin work")
        finally:
            window._shutting_down = False
            appicons._PIXMAP_CACHE.clear()
