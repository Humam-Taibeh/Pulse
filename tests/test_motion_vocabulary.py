"""
The app's motion curves are a vocabulary, and most of it was spelled out
longhand instead.

animations.py declares EASE_OUT and EASE_INOUT — two named curves, sitting
beside the named durations (HOVER_MS, PAGE_FADE_MS, CASCADE_MS...) that
every timing decision does go through. The curves did not get the same
treatment: eight call sites in widgets.py and main.py wrote
`QEasingCurve.Type.OutCubic` / `.InOutQuad` / `.InOutSine` directly.

That is the type-scale defect of v10.9.3 one layer over. Two consequences,
both invisible until someone tries to change the app's motion:

  1. A curve that IS in the vocabulary was still spelled longhand in five
     places, so "retune the app's easing" means editing two constants and
     then finding eight literals that silently keep the old feel.
  2. InOutSine — used for the brand mark's breath, the drawer's slide and
     the busy pulse — was in the app but not in the vocabulary at all, so
     nothing could see the app actually has THREE curves. It is the right
     curve for those three (all of them oscillate or reverse, which is
     what sine is for); it was simply never declared.

Nothing about the rendered motion changes here. The curves are identical
values under names, which is what makes the swap provable rather than
merely plausible — see test_no_rendered_curve_moves.
"""
from __future__ import annotations

import inspect
import re

from PySide6.QtCore import QEasingCurve

from frontend import animations as A
from frontend import main as M
from frontend import widgets as W


def test_the_vocabulary_covers_every_curve_the_app_uses():
    """Three curves ship; three are named."""
    assert A.EASE_OUT == QEasingCurve.Type.OutCubic
    assert A.EASE_INOUT == QEasingCurve.Type.InOutQuad
    assert A.EASE_BREATHE == QEasingCurve.Type.InOutSine, (
        "the oscillating curve (brand breath, drawer slide, busy pulse) is "
        "still not in the vocabulary")


def test_no_rendered_curve_moves():
    """The whole point of the swap: names for the values already in use,
    not a retune smuggled in under a refactor. If a future change means to
    move a curve, it edits the constant and this test says so out loud."""
    assert (A.EASE_OUT, A.EASE_INOUT, A.EASE_BREATHE) == (
        QEasingCurve.Type.OutCubic,
        QEasingCurve.Type.InOutQuad,
        QEasingCurve.Type.InOutSine,
    )


def _bare_curve_literals(module) -> list[str]:
    """Every `QEasingCurve.Type.X` written outside animations.py."""
    source = inspect.getsource(module)
    hits = []
    for line in source.splitlines():
        if line.lstrip().startswith("#"):
            continue        # a comment naming a curve is documentation
        for match in re.finditer(r"QEasingCurve\.Type\.(\w+)", line):
            hits.append(f"{match.group(1)}: {line.strip()[:70]}")
    return hits


def test_widgets_spells_no_curve_longhand():
    """widgets.py held five of the eight."""
    bare = _bare_curve_literals(W)
    assert not bare, (
        "widgets.py names Qt's curve enum directly instead of the "
        f"vocabulary: {bare}")


def test_main_spells_no_curve_longhand():
    """main.py's theme-crossfade was the odd one — the only place using the
    in-out curve, written longhand, so the app's one EASE_INOUT call site
    was invisible to a search for it."""
    bare = _bare_curve_literals(M)
    assert not bare, (
        f"main.py names Qt's curve enum directly: {bare}")


def test_animations_is_where_the_enum_is_allowed():
    """The vocabulary has to spell the enum somewhere — this pins WHERE, so
    the rule above reads as "one place" rather than "nowhere"."""
    bare = _bare_curve_literals(A)
    assert bare, "animations.py no longer defines the curves it exports"
    assert len(bare) == 3, (
        f"animations.py spells {len(bare)} curve literals; the vocabulary "
        "is three constants and each should be the only mention of its own "
        f"enum: {bare}")
