"""
Where is the keyboard? Measured in pixels, not in stylesheets.

WHY PIXELS
    The app indicates focus three different ways on purpose: GlassCard
    PAINTS a 2px accent ring in its own paintEvent, the text fields get a
    QSS `:focus` border, and Qt's own style draws whatever it draws. A test
    that looked for `:focus` in a stylesheet would report the card as
    unfocusable and the painted ring as missing; a test that looked for
    hasFocus() in source would miss the fields. What matters to the person
    pressing Tab is whether the control LOOKS different, so that is what
    this measures: render unfocused, render focused, compare.

WHAT IT FOUND
    NavButton - the four sidebar module entries - had no focus affordance
    of any kind. No focusInEvent, no hasFocus() branch in its paint, and
    zero `:focus` rules in nav_button_qss. They are nonetheless in the tab
    chain, second through fifth (measured: search, four nav entries, the
    content area, the card grid), so tabbing into the sidebar moved focus
    somewhere invisible. The sidebar search button was the same.

    That is the worst version of this defect rather than a cosmetic one: a
    keyboard user cannot see where they are, and the app's whole v10
    keyboard layer routes through those entries.

THE FLOOR
    A 2px ring, per the Windows 11 focus-visual guidance, and it must not
    be the app's hover glow reused - hover and focus mean different things
    and a pointer resting on a different row must not read as "the
    keyboard is here". So the test also requires focus to be visible on a
    control that is ALREADY hovered.
"""
from __future__ import annotations

import pytest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPainter, QPixmap

pytestmark = pytest.mark.native


def _render(widget) -> QPixmap:
    target = QPixmap(widget.size())
    target.fill(Qt.GlobalColor.transparent)
    painter = QPainter(target)
    widget.render(painter, QPoint())
    painter.end()
    return target


def _changed_pixels(before: QPixmap, after: QPixmap) -> int:
    a, b = before.toImage(), after.toImage()
    if a.size() != b.size():
        return -1
    changed = 0
    for y in range(a.height()):
        for x in range(a.width()):
            if a.pixel(x, y) != b.pixel(x, y):
                changed += 1
    return changed


def _focus_delta(widget, qapp) -> int:
    """How many pixels change when this control takes keyboard focus."""
    widget.clearFocus()
    qapp.processEvents()
    before = _render(widget)

    widget.setFocus(Qt.FocusReason.TabFocusReason)
    qapp.processEvents()
    after = _render(widget)

    widget.clearFocus()
    qapp.processEvents()
    return _changed_pixels(before, after)


#: A 2px ring around even a small control changes hundreds of pixels. This
#: floor is low enough to accept a subtle treatment and high enough to
#: reject "nothing visible happened", which is what a suppressed Qt focus
#: rect produces.
_MIN_FOCUS_PIXELS = 60


class TestTheSidebar:
    def test_a_nav_entry_shows_its_focus(self, window, qapp):
        """The defect this file was written for."""
        nav = window._nav_buttons[0]
        delta = _focus_delta(nav, qapp)
        assert delta >= _MIN_FOCUS_PIXELS, (
            f"focusing a sidebar module entry changed {delta} pixels — a "
            "keyboard user tabbing into the sidebar cannot see where they "
            "are")

    def test_every_nav_entry_shows_it(self, window, qapp):
        for index, nav in enumerate(window._nav_buttons):
            delta = _focus_delta(nav, qapp)
            assert delta >= _MIN_FOCUS_PIXELS, (
                f"nav entry {index} changed {delta} pixels on focus")

    def test_the_search_doorway_shows_its_focus(self, window, qapp):
        """First in the tab chain, so the first thing a keyboard user
        lands on and the first chance to lose them."""
        delta = _focus_delta(window._search_btn, qapp)
        assert delta >= _MIN_FOCUS_PIXELS, (
            f"the sidebar search button changed {delta} pixels on focus")


class TestFocusIsNotJustTheHoverGlow:
    def test_a_hovered_nav_entry_still_shows_focus_distinctly(self, window,
                                                              qapp):
        """Hover and focus mean different things. If focus is implemented
        by reusing the hover ramp, then a row the pointer happens to rest
        on is indistinguishable from the row the keyboard is on — and the
        keyboard user is the one who loses.
        """
        nav = window._nav_buttons[0]
        nav.clearFocus()
        # Put the widget into its hovered state without a real pointer.
        nav.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        nav.update()
        qapp.processEvents()
        hovered = _render(nav)

        nav.setFocus(Qt.FocusReason.TabFocusReason)
        qapp.processEvents()
        hovered_and_focused = _render(nav)

        try:
            delta = _changed_pixels(hovered, hovered_and_focused)
            assert delta >= _MIN_FOCUS_PIXELS, (
                f"only {delta} pixels separate hovered from "
                "hovered-and-focused — focus is the hover glow reused, so "
                "the pointer's position masks the keyboard's")
        finally:
            nav.clearFocus()
            nav.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
            nav.update()
            qapp.processEvents()


class TestTheAffordancesThatAlreadyWorked:
    """Pinned so the sweep above cannot be 'satisfied' by regressing them."""

    def test_a_card_still_paints_its_ring(self, window, qapp):
        from frontend.widgets import GlassCard

        cards = window.findChildren(GlassCard)
        assert cards, "no cards on the window"
        delta = _focus_delta(cards[0], qapp)
        assert delta >= _MIN_FOCUS_PIXELS, (
            f"a card changed {delta} pixels on focus — the 2px accent ring "
            "in GlassCard.paintEvent is gone")

    def test_the_ring_is_two_pixels(self, window):
        """The Windows 11 focus-visual guidance figure, and the one the
        card's own comment commits to. Read from the source because a
        pixel count cannot distinguish 2px from 3px reliably on a rounded
        antialiased corner."""
        import inspect

        from frontend.widgets import GlassCard

        source = inspect.getsource(GlassCard.paintEvent)
        assert "hasFocus()" in source, "the card no longer checks focus"
        assert "QPen(ring, 2.0)" in source, (
            "the focus ring is no longer the documented 2px")
