"""
Nothing in this app had ever asked Windows whether to animate.

THE SETTING
    Settings > Accessibility > Visual effects > Animation effects, read
    through SPI_GETCLIENTAREAANIMATION. It is Windows' answer to
    prefers-reduced-motion and it is a real accessibility control rather
    than a taste one: it is what someone with a vestibular disorder turns
    off, and it is disabled wholesale by some managed images and
    remote-desktop profiles.

    Every hover ramp, press tint, ripple and glow ran at full length
    regardless. An app that ignores that setting is not polished; it is
    one that has to be endured.

WHY motion_ms RETURNS ZERO RATHER THAN "DO NOT ANIMATE"
    Every animated property here also has a RESTING value that something
    paints — the glow's intensity, the press tint's alpha. An animation
    that is simply never started leaves the widget wherever it was last
    frame, so "skip it" would trade a preference violation for a stuck
    highlight. A zero-length animation still runs, still emits its final
    value and still ends in the right state; it just gets there in one
    frame. That is what makes honouring the preference one call per
    setDuration instead of a branch around every ramp.

THE DURATIONS ARE PINNED HERE for the reason test_motion_vocabulary pins
the curves: a retune should be a decision someone makes on purpose and
sees named in a diff, not something that drifts a call site at a time.
"""
from __future__ import annotations

import sys

import pytest

from frontend import animations as A


class TestTheVocabularyOfDuration:

    def test_hover_and_press_share_one_duration(self):
        """One number for both states is what "hover and pressed
        transitions on one curve" means in practice."""
        assert A.HOVER_MS == 120
        assert A.PRESS_MS == 120

    def test_the_press_ramp_and_its_release_timer_cannot_disagree(self):
        """They were two bare `90`s in different methods of the same
        class, with nothing saying they had to match. An Enter press ramps
        the tint in and schedules its release; if the two ever diverged,
        keyboard activation would feel unlike a click for no reason anyone
        could find."""
        import inspect

        from frontend.widgets import GlassCard

        constructor = inspect.getsource(GlassCard.__init__)
        keypress = inspect.getsource(GlassCard.keyPressEvent)
        assert "motion_ms(PRESS_MS)" in constructor
        assert "singleShot(PRESS_MS" in keypress

    def test_both_ease_out(self):
        """The brief's curve, and the app's default."""
        from PySide6.QtCore import QEasingCurve

        assert A.EASE_OUT == QEasingCurve.Type.OutCubic


class TestTheSystemPreference:

    def test_motion_ms_passes_the_duration_through_when_animation_is_on(self):
        try:
            A.refresh_motion_preference()
            A._MOTION_ALLOWED = True
            assert A.motion_ms(120) == 120
            assert A.motion_ms(320) == 320
        finally:
            A.refresh_motion_preference()

    def test_motion_ms_collapses_to_zero_when_the_user_said_no(self):
        """THE POINT. Zero, not None and not a skipped call — see the
        module docstring."""
        try:
            A._MOTION_ALLOWED = False
            assert A.motion_ms(120) == 0
            assert A.motion_ms(320) == 0
        finally:
            A.refresh_motion_preference()

    def test_every_interaction_ramp_goes_through_it(self):
        """Hover, press and ripple are the three that fire constantly, so
        they are the three where ignoring the preference is most felt."""
        import inspect

        from frontend.widgets import GlassCard

        glow = inspect.getsource(A.GlowController.__init__)
        ripple = inspect.getsource(A.RippleController.__init__)
        press = inspect.getsource(GlassCard.__init__)
        for name, source in (("hover glow", glow), ("ripple", ripple),
                             ("press tint", press)):
            assert "motion_ms(" in source, (
                f"the {name} ramp sets its duration without asking whether "
                "the user wants animation at all")

    @pytest.mark.skipif(sys.platform != "win32",
                        reason="SystemParametersInfoW is Windows-only")
    def test_the_real_setting_is_readable_and_boolean(self):
        """A live read against the actual OS. Not asserted TRUE — the
        developer running this may have animations off, and that is a
        legitimate machine rather than a failing one."""
        A.refresh_motion_preference()
        assert isinstance(A.system_animations_enabled(), bool)

    def test_it_defaults_to_animating_when_it_cannot_tell(self, monkeypatch):
        """The cost of being wrong in this direction is one animation
        somebody did not want. The other direction is an application that
        looks dead."""
        monkeypatch.setattr(A, "_MOTION_ALLOWED", None)
        monkeypatch.setattr(A.sys, "platform", "linux")
        try:
            assert A.system_animations_enabled() is True
        finally:
            A.refresh_motion_preference()
