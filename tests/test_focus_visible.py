"""
The focus ring belonged to whoever touched the app first.

WHAT WAS REPORTED
    "The active card border permanently clings to the first card even
    after clicking elsewhere."

WHAT IT ACTUALLY WAS
    Two separate facts that only bite together.

    GlassCard.mousePressEvent calls setFocus(MouseFocusReason), so a
    clicked card takes keyboard focus. Both painted rings — GlassCard's
    and NavButton's — were then drawn on `hasFocus()` alone, which cannot
    tell a Tab from a click.

    And clicking the page BACKGROUND moves focus nowhere: a QWidget with
    no focus policy is not a focus candidate, so Qt leaves the previous
    holder exactly where it was. There is no "click away to deselect" in
    Qt the way there is in a browser.

    Together: click a card, and a 2px accent ring is welded to it for the
    rest of the session, on a window nobody has pressed a key on. Clicking
    a DIFFERENT card only moves the weld.

THE FIX, AND WHY IT IS NOT "CLEAR FOCUS ON BACKGROUND CLICK"
    Dropping focus when the user clicks the background would trade a
    visible bug for an invisible one: the keyboard user's place in the
    grid would silently reset every time a pointer landed on empty
    canvas. The ring is not really about who HAS focus — it is about
    whether the person needs to be told. So it follows the focus REASON,
    which is what `:focus-visible` settled on for the same reason.

    widgets.focus_ring_visible owns that decision; these tests own the
    behaviour it produces.

MEASURED IN PIXELS, like test_focus_visuals, and for the same reason: the
ring is painted in paintEvent, so nothing about a stylesheet or a
property proves it is on screen. Rendering twice and diffing is the only
assertion that cannot pass while the user still sees a ring.
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


def _settle_paint(qapp) -> None:
    """Let the glow animation finish so a comparison sees a stable frame."""
    from PySide6.QtTest import QTest
    qapp.processEvents()
    QTest.qWait(260)
    qapp.processEvents()


def _delta_for(widget, qapp, reason) -> int:
    """Pixels the RING adds when `widget` takes focus for `reason`.

    THE GLOW HAS TO BE HELD CONSTANT OR THIS MEASURES THE WRONG THING.
    GlassCard.focusInEvent ramps the hover glow whatever the reason —
    deliberately, because "this card is live" is true however it was
    reached — and that ramp repaints the card's whole perimeter. Measured:
    a plain unfocused-versus-focused diff on a card that paints NO ring
    still reports 6,598 changed pixels, two orders of magnitude above the
    ring's own floor. Any assertion built on that number is reading the
    glow and calling it a ring.

    WA_UnderMouse IS NOT ENOUGH to hold it. That attribute is a hit-test
    flag; the glow is driven by GlowController's own event filter on
    Enter/Leave, so setting the attribute leaves the intensity at 0 and
    the focus ramp still runs. (test_focus_visuals sets it for a
    different purpose — proving focus and hover DIFFER — where any delta
    at all is the pass condition, so the distinction never mattered
    there.)

    The controller is therefore driven directly to full BEFORE the
    baseline is captured. focusInEvent then asks it to ramp to a value it
    is already at, which is a no-op on screen, and the only thing left
    that focus can add is the ring.
    """
    widget.clearFocus()
    widget._glow._ramp_to(1.0)
    _settle_paint(qapp)
    try:
        before = _render(widget)
        widget.setFocus(reason)
        _settle_paint(qapp)
        after = _render(widget)
        return _changed_pixels(before, after)
    finally:
        widget.clearFocus()
        widget._glow._ramp_to(0.0)
        _settle_paint(qapp)


#: Same floor as test_focus_visuals: a 2px ring around even a small
#: control changes hundreds of pixels, and anything under this is
#: "nothing visible happened".
_MIN_RING_PIXELS = 60

#: What counts as "no ring". Not zero — the glow settles to a stable
#: frame but antialiasing on the accent hairline can still differ by a
#: handful of pixels between two renders of a focused and unfocused
#: card. An order of magnitude below the ring's own floor is the gap that
#: separates "a border appeared" from "the edge dithered".
_MAX_QUIET_PIXELS = 8


class TestTheReportedDefect:
    def test_a_mouse_focused_card_paints_no_ring(self, window, qapp):
        """THE BUG. Before the fix this changed ~700 pixels — the ring —
        and those pixels then stayed on screen for the whole session."""
        from frontend.widgets import GlassCard

        card = next(c for c in window.findChildren(GlassCard)
                    if c.isVisible())
        delta = _delta_for(card, qapp, Qt.FocusReason.MouseFocusReason)
        assert delta <= _MAX_QUIET_PIXELS, (
            f"clicking a card changed {delta} pixels — it is still being "
            "given the keyboard's focus ring, which then clings to it "
            "because clicking the background moves focus nowhere")

    def test_a_mouse_focused_nav_entry_paints_no_ring(self, window, qapp):
        nav = window._nav_buttons[0]
        delta = _delta_for(nav, qapp, Qt.FocusReason.MouseFocusReason)
        assert delta <= _MAX_QUIET_PIXELS, (
            f"clicking a sidebar entry changed {delta} pixels")

    def test_a_keyboard_ring_is_dropped_when_the_pointer_takes_over(
            self, window, qapp):
        """The transition the user actually performs: tab to a card, then
        reach for the mouse. The ring must not survive the click."""
        from frontend.widgets import GlassCard

        card = next(c for c in window.findChildren(GlassCard)
                    if c.isVisible())
        # Glow held at full throughout, so the diff is the ring and not
        # the focus ramp — see _delta_for.
        card._glow._ramp_to(1.0)
        _settle_paint(qapp)
        try:
            card.setFocus(Qt.FocusReason.TabFocusReason)
            _settle_paint(qapp)
            assert card._focus_ring, "the keyboard never got its ring"
            with_ring = _render(card)

            # FOCUS NEVER LEAVES THE CARD HERE, and that is the whole
            # point of the test. This is one widget being re-focused by a
            # click — precisely what GlassCard.mousePressEvent does — and
            # Qt delivers NO focusInEvent for it, because focus did not
            # change. A fix that lived only in focusInEvent would leave
            # the ring on and this measured at zero changed pixels.
            card._focus_ring = False
            card.setFocus(Qt.FocusReason.MouseFocusReason)
            card.update()
            _settle_paint(qapp)
            after_click = _render(card)

            delta = _changed_pixels(with_ring, after_click)
            assert delta >= _MIN_RING_PIXELS, (
                f"only {delta} pixels changed when the pointer took a "
                "keyboard-focused card — the ring is still there")
        finally:
            card.clearFocus()
            card._glow._ramp_to(0.0)
            _settle_paint(qapp)

    def test_no_card_wears_a_ring_on_a_freshly_shown_window(
            self, fresh_window, qapp):
        """A COLD window, because this is the state the report opens in:
        the app has just started, nobody has pressed a key, and Qt has
        already handed focus to the first widget in the tab chain."""
        from frontend.widgets import GlassCard

        win = fresh_window()
        _settle_paint(qapp)
        ringed = [c.accessibleName()
                  for c in win.findChildren(GlassCard)
                  if c.isVisible() and c.hasFocus() and c._focus_ring]
        assert not ringed, (
            f"{ringed} wears a focus ring on a window nobody has typed "
            "into yet")


class TestTheKeyboardStillGetsItsRing:
    """The whole point of suppressing the ring for the pointer is that it
    stays unambiguous for the keyboard. If these fail, the fix has simply
    deleted the affordance."""

    @pytest.mark.parametrize("reason", [
        Qt.FocusReason.TabFocusReason,
        Qt.FocusReason.BacktabFocusReason,
        # main._focus_neighbour moves arrow-key focus with this one, so it
        # is a keyboard reason in this app whatever its name suggests.
        Qt.FocusReason.OtherFocusReason,
    ])
    def test_a_card_rings_for_every_keyboard_reason(self, window, qapp,
                                                    reason):
        from frontend.widgets import GlassCard

        card = next(c for c in window.findChildren(GlassCard)
                    if c.isVisible())
        delta = _delta_for(card, qapp, reason)
        assert delta >= _MIN_RING_PIXELS, (
            f"focusing a card with {reason} changed {delta} pixels — a "
            "keyboard user cannot see where they are")

    def test_every_nav_entry_still_rings_on_tab(self, window, qapp):
        for index, nav in enumerate(window._nav_buttons):
            delta = _delta_for(nav, qapp, Qt.FocusReason.TabFocusReason)
            assert delta >= _MIN_RING_PIXELS, (
                f"nav entry {index} changed {delta} pixels on Tab")

    def test_arrow_traversal_lights_the_card_it_lands_on(self, window,
                                                         qapp):
        """END TO END through the app's own traversal helper, rather than
        through a setFocus this test chose the reason for."""
        from frontend.main import _focus_neighbour
        from frontend.widgets import GlassCard

        cards = [c for c in window.findChildren(GlassCard) if c.isVisible()]
        if len(cards) < 2:
            pytest.skip("this page has one card; nowhere to traverse to")
        cards[0].setFocus(Qt.FocusReason.TabFocusReason)
        qapp.processEvents()
        assert _focus_neighbour(cards, len(cards), cards[0], "right"), (
            "traversal refused to move")
        qapp.processEvents()
        landed = next(c for c in cards if c.hasFocus())
        assert landed._focus_ring, (
            "an arrow keypress moved focus without lighting the ring")
        landed.clearFocus()
        qapp.processEvents()


class TestTheDecisionItself:
    """focus_ring_visible in isolation — no window, no paint. These are
    the cases the pixel tests above cannot reach cheaply."""

    def test_the_pointer_reasons_are_refused(self):
        from frontend.widgets import focus_ring_visible

        for reason in (Qt.FocusReason.MouseFocusReason,
                       Qt.FocusReason.PopupFocusReason):
            assert focus_ring_visible(reason, previous=True) is False
            assert focus_ring_visible(reason, previous=False) is False

    def test_reactivating_the_window_changes_nothing(self):
        """Alt-tab away and back. It must neither invent a ring on a
        mouse-focused control nor erase one a keyboard user was relying
        on, because it is not a navigation event either way."""
        from frontend.widgets import focus_ring_visible

        reason = Qt.FocusReason.ActiveWindowFocusReason
        assert focus_ring_visible(reason, previous=False) is False
        assert focus_ring_visible(reason, previous=True) is True

    def test_the_keyboard_reasons_are_accepted(self):
        from frontend.widgets import focus_ring_visible

        for reason in (Qt.FocusReason.TabFocusReason,
                       Qt.FocusReason.BacktabFocusReason,
                       Qt.FocusReason.ShortcutFocusReason,
                       Qt.FocusReason.MenuBarFocusReason,
                       Qt.FocusReason.OtherFocusReason):
            assert focus_ring_visible(reason, previous=False) is True
