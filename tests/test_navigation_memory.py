"""
Heavy navigation does not accumulate objects — and the measurement that
says so has a trap in it.

THE TRAP, BECAUSE IT PRODUCED A FALSE POSITIVE FIRST
    The obvious way to measure this is: snapshot findChildren(), navigate
    a few hundred times calling processEvents() as you go, snapshot again.
    Done that way the window appears to leak steadily:

        after  50 navigations: children +31,  QObjects +129
        after 125 navigations: children +105, QObjects +203
        after 250 navigations: children +247, QObjects +346

    and a breakdown blames QPropertyAnimation (+84) and
    QParallelAnimationGroup (+40), whose parent chains lead straight to
    PageFader and CascadeAnimator.

    All of that is an artifact of the measurement. QCoreApplication's
    processEvents() does NOT deliver DeferredDelete events - only a return
    to the top level of a real event loop does - so every object the app
    correctly deleteLater()'d was still counted as live. Draining them the
    way the running app does:

        after  50 navigations: animations +0, children +1
        after 150 navigations: animations +0, children +0
        after 300 navigations: animations +0, children -8

    Flat. The baseline child count also falls from 1228 to 1023 once the
    pending deletes are drained, which is the same fact from the other
    side: those 200 objects were queued for deletion, not leaked.

WHAT THIS FILE IS FOR
    Both halves. The no-accumulation property is worth pinning because
    v10.9.2 fixed a real version of it (every modal the shell opened lived
    until the app quit), so the failure mode is not hypothetical here. And
    the drain is worth encoding because the next person to measure this
    will otherwise rediscover the phantom and "fix" animations that were
    never leaking.
"""
from __future__ import annotations

import gc

import pytest

from PySide6.QtCore import (QCoreApplication, QEvent, QObject,
                            QPropertyAnimation)


def _drain(qapp) -> None:
    """Do what a top-level event loop does, which processEvents() alone
    does not: deliver the DeferredDelete events that deleteLater() posts.

    Three passes because a deferred delete can post another one - a group
    deleting its children, a widget deleting its effect.
    """
    for _ in range(3):
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def _navigate(window, qapp, laps: int) -> None:
    for _ in range(laps):
        for index in range(4):
            window.open_category(index)
            qapp.processEvents()
        window.go_home()
        qapp.processEvents()


@pytest.fixture
def settled(window, qapp):
    """The window with every page built and every pending delete drained,
    so the baseline is a real steady state rather than a first-visit one."""
    _navigate(window, qapp, 1)
    _drain(qapp)
    yield window
    window.go_home()
    _drain(qapp)


class TestRapidNavigation:
    def test_animations_do_not_accumulate(self, settled, qapp):
        """The class the false positive blamed, measured properly."""
        before = len(settled.findChildren(QPropertyAnimation))
        _navigate(settled, qapp, 30)
        _drain(qapp)
        after = len(settled.findChildren(QPropertyAnimation))

        assert after <= before + 4, (
            f"{after - before} animations retained across 150 navigations "
            f"({before} -> {after}) — the page fade or the card cascade is "
            "no longer releasing its groups")

    def test_the_child_count_is_flat(self, settled, qapp):
        """Everything, not just animations: transient labels, layouts,
        effects, toasts."""
        before = len(settled.findChildren(QObject))
        _navigate(settled, qapp, 30)
        _drain(qapp)
        after = len(settled.findChildren(QObject))

        assert after <= before + 20, (
            f"{after - before} objects retained across 150 navigations "
            f"({before} -> {after})")

    def test_it_stays_flat_as_the_session_gets_longer(self, settled, qapp):
        """Growth that is bounded looks the same as growth that is slow
        over one short run. Two windows of the same size, compared: a real
        leak grows with the second as much as with the first."""
        _navigate(settled, qapp, 20)
        _drain(qapp)
        first = len(settled.findChildren(QObject))

        _navigate(settled, qapp, 20)
        _drain(qapp)
        second = len(settled.findChildren(QObject))

        assert second <= first + 12, (
            f"the second 100 navigations added {second - first} objects on "
            f"top of the first ({first} -> {second}) — the growth is "
            "per-navigation, not a one-off settling cost")


class TestTheDrainItself:
    def test_processevents_alone_does_not_deliver_deferred_deletes(self,
                                                                   qapp):
        """The trap, pinned as a fact rather than left in a comment. If a
        future Qt changes this, the tests above become weaker than they
        read and someone should be told."""
        holder = QObject()
        child = QObject(holder)
        child.deleteLater()

        qapp.processEvents()
        assert holder.findChildren(QObject), (
            "processEvents() now delivers DeferredDelete; the _drain helper "
            "in this file is redundant and the phantom-leak warning in its "
            "docstring no longer applies")

        _drain(qapp)
        assert not holder.findChildren(QObject), (
            "the deferred delete never arrived even after an explicit "
            "sendPostedEvents — the measurements here cannot be trusted")
