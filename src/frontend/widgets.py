"""
src/frontend/widgets.py

COMPONENT LIBRARY — isolated, theme-aware, effect-free custom widgets.

Every widget here:
    - takes its QSS from theme.py factories (never inline color literals),
    - exposes apply_theme(t) for live re-skinning (ThemeManager.changed),
    - paints its hover glow itself via animations.GlowController +
      paint_glow_frame — zero QGraphicsEffect in steady state.

Import graph: theme.py <- animations.py <- widgets.py <- main.py
"""
from __future__ import annotations

import math
import os
import re
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QDateTime, QEvent, QEventLoop, QPoint, QPointF, QProcess,
    QPropertyAnimation, QRect, QRectF, QSize, Qt, QThread, QTime, QTimer, QUrl,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QDesktopServices, QFont, QFontMetrics, QImage,
    QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
    QTextCharFormat, QTextCursor, QTextLayout, QTextOption,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

from frontend.animations import (
    EASE_BREATHE, EASE_OUT,
    GlowController, RippleController, ShimmerBar, paint_accent_hairline,
    paint_aurora_edge, paint_bevel_frame, paint_drop_shadow, paint_glow_frame,
    paint_nav_indicator, paint_ripple_frame, paint_top_sheen, squircle_path,
)
from frontend import theme as TH
# Data-only module (no widget imports), so this cannot cycle: the command
# palette scores against its structured search fields (see _match_entry).
from frontend import menu_structure as MS
# Update Center / Startup Manager (v6.3) run their own background scans and
# per-item actions independently of main.py's single-task console pipeline
# (both are modal dialogs that fully cover it anyway) - the one deliberate
# exception to this file's "pure component library" rule, since the alter-
# native (threading process ownership through main.py) would either block
# the dialog's own loading UI or duplicate PowerShellTask's cancellation-
# safe process/thread bookkeeping here.
from utils import appicons, resources, updater  # noqa: E402
from utils.helpers import (  # noqa: E402
    PowerShellTask, SelfUpdateInstallWorker, TaskResult,
)


def _alive(widget) -> bool:
    """Is this Python wrapper still backed by a live C++ object?

    Qt deletes a parented dialog out from under its wrapper, and the only
    honest way to ask is to touch it. Used by PulseDialog._OPEN, which
    outlives individual dialogs by construction.
    """
    try:
        widget.isVisible()
        return True
    except RuntimeError:
        return False


class PulseDialog(QDialog):
    """Base for every frameless Pulse modal.

    Unlike a plain QDialog sized to fit its content, THIS window covers
    the app's full body (everything below the title bar) and paints the
    dense scrim backdrop itself, with the frosted content `panel`
    centered (or top-anchored) inside it. Because the backdrop is part of
    the same top-level window as the panel — not a separate widget
    sitting underneath — it keeps receiving mouse events while the dialog
    is modal: clicking anywhere outside `panel` dismisses the dialog
    exactly like pressing Escape or Cancel, the way a native Fluent/macOS
    sheet behaves. Nested wizards (a PulseDialog opened from another
    PulseDialog) get this for free — each paints its own full-body scrim
    on top of whatever is behind it, so stacked modals just work."""

    #: Every PulseDialog currently on screen, oldest first.
    #:
    #: This replaces QApplication.activeModalWidget() as the app's answer to
    #: "is a sheet open, and which one is on top". That call returns None
    #: now (see __init__ on why these are NonModal), and two things were
    #: reading it: main.PulseApp.resizeEvent, to keep an open scrim glued to
    #: the body during a live resize, and the nesting behaviour that stops
    #: an outer sheet reacting to clicks meant for an inner one.
    #:
    #: A list rather than a single reference because sheets nest — a wizard
    #: opened from a wizard — and both of those readers need the whole
    #: stack: the resize has to refit every open scrim, not just the top.
    _OPEN: "list[PulseDialog]" = []

    #: Downscale factor used to blur the captured backdrop. A Gaussian over
    #: a full 1300x800 frame is far too slow to do on a modal's show; a
    #: bilinear round-trip through a 1/N-scale pixmap is the standard cheap
    #: approximation, because what we want IS the low-frequency content.
    #:
    #: 10 -> 6, and the change is what fixes the chunky-square artifact.
    #: The blockiness was never the blur radius, it was the MAGNIFICATION:
    #: a 1/10 source stretched back over the full body is a 10x upscale, and
    #: bilinear over 10x does not hide the source grid — it renders each
    #: source texel as a visibly flat-centred square with a thin ramp at its
    #: border, which is exactly the "chunky pixelation" this looked like. On
    #: a 1.25x display it was worse still: the pixmap carried no device
    #: pixel ratio, so the real magnification was 12.5x (see the DPR note
    #: in _capture_backdrop) — and a NON-INTEGER one, so the tile edges
    #: landed on a half-pixel cadence that never repeated cleanly. That is
    #: why the artifact read as irregular chunky blocks rather than as an
    #: even mosaic.
    #:
    #: 6 keeps the capture cheap (~1/36 of the pixels) while cutting the
    #: upscale enough for the two-stage resample below to dissolve the grid
    #: completely. The lost blur radius is put back by _BLUR_PASSES.
    _BLUR_DOWNSCALE = 6

    #: Box-blur passes applied to the small capture BEFORE it is scaled
    #: back up. Two passes of a separable 3x3 box over a ~220x130 image is
    #: sub-millisecond and approximates a Gaussian well enough that the
    #: result has no directional structure left to magnify — which is what
    #: lets the downscale factor come down without the frost turning back
    #: into a legible screenshot.
    _BLUR_PASSES = 2

    def __init__(self, parent: QWidget | None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # EXPLICITLY NonModal, and this is a fix rather than a relaxation.
        #
        # setModal(True) is Qt::ApplicationModal, which blocks input to
        # every other window in the application — including the host's own
        # top-level window, which is where this app's title bar lives.
        # refit_dialog has always sized the scrim to start BELOW the title
        # bar so close/minimize/maximize stay visible "no matter what is
        # open", and they were: visible, and completely dead. Qt drops
        # spontaneous mouse events for a blocked window before they reach
        # any handler, so the caption buttons and the window drag did
        # nothing while a modal or the command palette was up.
        #
        # Nothing is actually given up by dropping Qt's modality here,
        # because this class never depended on it for what it does. The
        # dialog is a full-body window covering everything the user must
        # not reach, so the BODY is guarded by geometry, not by modality;
        # and the title bar is the one region deliberately left out of that
        # rectangle. What Qt's modality added on top was blocking the strip
        # we had explicitly decided to leave reachable.
        #
        # THIS ALONE IS NOT ENOUGH, and finding that out is why exec() is
        # overridden below. QDialog::exec() sets WA_ShowModal
        # unconditionally, and QWidget::setAttribute promotes a NonModal
        # window back to ApplicationModal the moment that attribute goes
        # on. Setting the modality here without replacing exec() leaves the
        # dialog application-modal exactly as before — measured, not
        # assumed: the first version of this fix did only this half and the
        # title bar stayed dead.
        #
        # What modality WAS doing for free is now done by _OPEN below:
        # ordering, so a nested sheet cannot be dismissed by a click meant
        # for the sheet on top of it.
        self.setWindowModality(Qt.WindowModality.NonModal)
        #: The local loop exec() blocks on, live only while it is running.
        self._loop: QEventLoop | None = None
        self.panel: "DepthCard | None" = None
        self._scrim_color = QColor(5, 7, 10, 195)
        # Square by default, matching the opaque square shell it covers.
        # This is the value the FIRST paint uses — refit_dialog re-asserts
        # it, but a rounded default would flash two lit wedges of shell at
        # the bottom corners on the frame before that lands.
        self._scrim_radius = 0
        #: Blurred snapshot of whatever this modal covers, captured once on
        #: show — see _capture_backdrop. Held at the dialog's own DEVICE
        #: resolution and tagged with the display's pixel ratio, so
        #: paintEvent blits it 1:1 instead of magnifying it every frame.
        self._frost: QPixmap | None = None
        #: Coalesces backdrop re-captures during a live host resize, so a
        #: drag pays for one capture at the end rather than one per step.
        self._refrost = QTimer(self)
        self._refrost.setSingleShot(True)
        self._refrost.setInterval(120)
        self._refrost.timeout.connect(self._capture_backdrop)

    def _set_scrim(self, t: dict, radius: int):
        self._scrim_color = QColor(*t["scrim"])
        self._scrim_radius = radius
        self.update()

    def _capture_backdrop(self):
        """Grab what this modal is about to cover and blur it, so the scrim
        is frosted glass rather than a flat sheet of tint.

        Qt has no backdrop-filter and the DWM route is closed here — the
        module note at the foot of theme.py records why blur-behind was
        removed (it needs the layered/translucent composition path that
        caused the window rendering glitches). But a modal is not a
        separate window over the desktop: it covers the APP, and the app is
        something we can render ourselves. So the blur is computed rather
        than composited, once, at the moment the dialog opens.

        The capture is of the window DIRECTLY beneath — offset to whatever
        region of it this dialog occupies, so the frost stays registered to
        the pixels actually behind it rather than being a stretched
        approximation. Deliberately not _resolve_host_window(), which
        climbs past intermediate dialogs to the QMainWindow: a nested wizard
        sits on top of its parent sheet, so the parent sheet is what it must
        frost. Grabbing the parent renders that dialog's own paintEvent —
        its scrim over its own frost — so stacked sheets compose correctly
        without any special case.

        Failure is silent and total by design: a null grab (no window yet,
        zero size, a platform that will not render offscreen) leaves
        `_frost` as None and paintEvent falls back to the flat scrim, which
        is what shipped for every version before this one.
        """
        self._frost = None
        parent = self.parentWidget()
        host = parent.window() if parent is not None else None
        if host is None or self.width() <= 0 or self.height() <= 0:
            return
        self._refrost.stop()

        # RENDERED STRAIGHT TO BLUR RESOLUTION, never grabbed at full size
        # and scaled down. host.grab() rasterises ~1.8M pixels so that we
        # can average them away to ~18K — measured at 21.8 ms on the exact
        # frame the user is waiting for a modal to open. Rendering through
        # a scaled painter rasterises the tiny target directly, and the
        # downscale IS the blur: a UI drawn at a tenth of its size is a box
        # filter over 10x10 neighbourhoods, which is the whole effect.
        #
        # Retained small, too. Scaling it back up is the painter's job on
        # each repaint, with SmoothPixmapTransform already set — a full-size
        # blurred pixmap here would cost a second smooth scale and an
        # allocation to match, for pixels that carry no extra information.
        # DEVICE PIXELS, NOT LOGICAL ONES. This is half of the chunky-
        # backdrop bug. The capture was sized from self.width(), which is
        # LOGICAL, and the resulting pixmap carried the default device
        # pixel ratio of 1 — so on the 1.25x display this was reported
        # from, paintEvent stretched a 1/10-scale pixmap across a rect that
        # is 1.25x larger in real pixels than Qt thought it was. The
        # effective magnification was 12.5x rather than 10x, and every
        # source texel landed on a 12.5-pixel square with a hard-ish edge.
        # Capturing at device resolution and TAGGING the pixmap with the
        # ratio makes the blit 1:1 on every display scale.
        dpr = self.devicePixelRatioF()
        dev_w = max(1, int(round(self.width() * dpr)))
        dev_h = max(1, int(round(self.height() * dpr)))
        width = max(1, dev_w // self._BLUR_DOWNSCALE)
        height = max(1, dev_h // self._BLUR_DOWNSCALE)

        frost = QPixmap(width, height)
        frost.setDevicePixelRatio(1.0)
        frost.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frost)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # One scale carrying BOTH the downscale and the display ratio, so
        # the small capture stays registered to real pixels.
        scale = dpr / float(self._BLUR_DOWNSCALE)
        painter.scale(scale, scale)
        # Shift the host so the slice sitting behind US lands at the origin.
        offset = host.mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))
        painter.translate(-offset)
        try:
            # targetOffset is required on the painter overload; the shift
            # we actually want is the translate above, which is applied to
            # the painter's transform rather than to the source.
            host.render(painter, QPoint())
        except (RuntimeError, TypeError):
            painter.end()
            return
        painter.end()
        self._frost = self._resolve_frost(frost, dev_w, dev_h, dpr)

    def _resolve_frost(self, small: QPixmap, dev_w: int, dev_h: int,
                       dpr: float) -> QPixmap:
        """Turn the tiny capture into the pixmap paintEvent blits 1:1.

        The old code kept the capture small and let paintEvent magnify it
        on every repaint, on the reasoning that the upscale carries no
        extra information. It carries no extra INFORMATION and it carries a
        very visible ARTIFACT: one bilinear pass over a 10x magnification
        leaves each source texel as a flat square with a one-pixel ramp
        around it, which is a grid of chunky blocks rather than a blur.

        Two things fix it, and both belong here rather than in paintEvent:

          * a box blur on the SMALL image, where it costs microseconds and
            removes the sharp texel-to-texel steps that magnification would
            otherwise turn into visible tile edges;
          * a two-STAGE smooth upscale. Bilinear only interpolates between
            adjacent source texels, so one 6x jump still reproduces the
            grid; going through an intermediate doubles the interpolation
            and dissolves it.

        Resolving once here COSTS a little at steady state rather than
        saving it, which is worth stating because the opposite is the
        intuitive guess. Measured on a 1400x850 sheet at 1.25x: a repaint
        blitting the resolved 1750x1062 pixmap 1:1 runs 3.83 ms against
        3.53 ms for magnifying the tiny one. Drawing 1.9M pixels is simply
        more memory traffic than smoothing 12K up, however many times the
        scaler runs. The pixmap also costs ~1.9 MB for as long as the sheet
        is open.

        Both are paid deliberately: 0.3 ms on a surface that repaints on
        hover, for a backdrop with no visible tiling in it. The capture
        itself went 6.6 -> 12.7 ms for the same reason (a 1/6 render at
        device resolution rasterises more than a 1/10 render at logical
        resolution), and lands on the one frame already hidden behind the
        130 ms entrance fade.
        """
        image = small.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        for _ in range(self._BLUR_PASSES):
            image = self._box_blur(image)
        # Stage one: halfway (geometric) between the capture and the target.
        mid_w = max(1, int((image.width() * dev_w) ** 0.5))
        mid_h = max(1, int((image.height() * dev_h) ** 0.5))
        image = image.scaled(mid_w, mid_h,
                             Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        image = image.scaled(dev_w, dev_h,
                             Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        resolved = QPixmap.fromImage(image)
        resolved.setDevicePixelRatio(dpr)
        return resolved

    @staticmethod
    def _box_blur(image: QImage) -> QImage:
        """One separable 3x3 box pass, done by Qt rather than by hand.

        Scaling an image to half and back with SmoothTransformation IS a
        box filter over 2x2 neighbourhoods followed by a bilinear spread —
        the same thing a hand-written pass would compute, in C++, without
        a Python loop over a quarter of a million pixels. The point of the
        pass is not precision; it is to leave no sharp step for the
        magnification downstream to enlarge.
        """
        half = image.scaled(max(1, image.width() // 2),
                            max(1, image.height() // 2),
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        return half.scaled(image.width(), image.height(),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)

    @classmethod
    def topmost(cls) -> "PulseDialog | None":
        """The sheet the user is actually looking at, or None."""
        for dialog in reversed(cls._OPEN):
            try:
                if dialog.isVisible():
                    return dialog
            except RuntimeError:      # C++ side already gone
                continue
        return None

    @classmethod
    def open_dialogs(cls) -> "list[PulseDialog]":
        """Every live sheet, oldest first. Copied, because callers refit
        and close things while iterating."""
        return [d for d in cls._OPEN if _alive(d)]

    def _register(self):
        if self not in PulseDialog._OPEN:
            PulseDialog._OPEN.append(self)

    def _unregister(self):
        PulseDialog._OPEN[:] = [d for d in PulseDialog._OPEN
                                if d is not self and _alive(d)]

    def showEvent(self, e):
        super().showEvent(e)
        self._register()
        # DELIBERATELY NO CAPTURE HERE — see _present_dialog, which takes it
        # immediately after refit_dialog has set our final geometry.
        #
        # This used to capture synchronously, and it was the modal backdrop
        # artifact: at showEvent time a PulseDialog is still whatever size
        # Qt gave it at construction, and refit_dialog — which expands it to
        # cover the host's whole body — runs AFTERWARDS, from the subclass's
        # own showEvent. So every frost was rendered for the wrong rectangle
        # at the wrong offset and then stretched across the full body by
        # paintEvent, which is what produced the flat hard-edged grey block
        # with smeared content misregistered around it.
        #
        # It self-corrected once the 120ms _refrost timer fired, so it was
        # invisible in a still screenshot taken late and obvious in the
        # entrance itself — and worse the slower the machine, because the
        # broken frame simply stays up longer (it was reported from a VM).
        # Leaving _frost as None here means the pre-capture frame falls back
        # to the flat scrim, which is honest and has no artifact.
        self._frost = None

    def hideEvent(self, e):
        self._unregister()
        super().hideEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # A live host resize moves the modal over different pixels, so the
        # frost does eventually need re-taking — but NOT per resize step.
        # A capture renders the whole host window (~6.6 ms), and a drag
        # emits these continuously; paying it per step would put the
        # backdrop refresh directly in the way of the drag. The retained
        # frost simply stretches in the meantime, which on a 20px blur is
        # invisible, and one capture lands once the drag stops.
        if self.isVisible():
            self._refrost.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        color = self._scrim_color
        if self._scrim_radius:
            # extend the path above the top edge so only the BOTTOM
            # corners round — the top meets the title bar in a flat line
            path = QPainterPath()
            path.addRoundedRect(rect.adjusted(0, -self._scrim_radius, 0, 0),
                                self._scrim_radius, self._scrim_radius)
            p.setClipRect(rect)
            p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        else:
            p.setClipRect(rect)
        if self._frost is not None:
            # Frosted glass is the blur PLUS the tint, in that order: the
            # blur alone is just a smeared screenshot with no sense of a
            # surface in front of it, and the tint alone is the flat sheet
            # this replaced. The scrim's own alpha does the darkening, so
            # the two themes stay exactly as separated as they were.
            p.drawPixmap(self.rect(), self._frost)
        p.fillRect(rect, color)
        p.end()

    def mousePressEvent(self, e):
        # A click that lands on the scrim itself (outside the panel) is
        # the backdrop-dismiss gesture — everything inside the panel is
        # ordinary child-widget input and reaches its own handlers first,
        # so this only ever fires for genuine outside clicks.
        #
        # ONLY FOR THE TOP SHEET. Qt's application modality used to make
        # that automatic: an outer sheet simply never saw the event. These
        # are NonModal now (see __init__), so an outer sheet is a live
        # window sitting behind an inner one and would happily dismiss
        # itself out from under it.
        if not self._is_topmost():
            super().mousePressEvent(e)
            return
        if self.panel is not None and not self.panel.geometry().contains(e.position().toPoint()):
            self.reject()
            return
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        """Escape closes the TOP sheet only, for the same reason a backdrop
        click does. QDialog maps Escape to reject() unconditionally."""
        if (e.key() == Qt.Key.Key_Escape and not self._is_topmost()):
            e.ignore()
            return
        super().keyPressEvent(e)

    def _is_topmost(self) -> bool:
        top = PulseDialog.topmost()
        return top is None or top is self

    # -- worker-thread teardown ---------------------------------------
    #: Bound on how long a closing dialog waits for its own worker thread.
    #: Matches main.PulseApp.closeEvent's 3000ms for the shell's task
    #: thread — same hazard, same budget, and the two must not drift.
    _WORKER_WAIT_MS = 3000
    #: How long a still-running worker is given to finish ON ITS OWN before
    #: it is cancelled. Small, because in the common case it is already
    #: over: five of the seven worker dialogs cancel in their own reject(),
    #: so by the time we get here the backend process is dead and the read
    #: loop unwinds in single-digit milliseconds. It is spent in full only
    #: by the two dialogs that mutate — see _settle_worker_threads.
    _WORKER_GRACE_MS = 1200

    def exec(self) -> int:
        """Show and block, WITHOUT making the application modal.

        QDialog.exec() cannot be configured into doing this. It sets
        Qt::WA_ShowModal unconditionally, and QWidget::setAttribute turns a
        NonModal window back into an ApplicationModal one as soon as that
        attribute is set — so windowModality() is not a lever the caller
        can pull, and the title bar this class deliberately leaves
        uncovered stays unreachable. (Qt::WindowModal is no better here: it
        blocks the modal widget's own window ancestry, and the host window
        IS that ancestry.)

        So the blocking half of exec() is reimplemented and the blocking-
        OTHER-WINDOWS half is dropped. A local QEventLoop gives callers the
        same synchronous `result = dialog.exec()` contract they already
        write against, including for nested wizards — a sheet opened from a
        sheet just nests another loop, which is what Qt does too.

        What is NOT reimplemented is input containment, because this class
        never got that from Qt: the sheet is a full-body window covering
        everything the user must not touch. Geometry is the barrier; the
        title bar is the hole we meant to leave in it.
        """
        if self._loop is not None:          # already running; don't nest
            return self.result()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowModal, False)
        self.setResult(QDialog.DialogCode.Rejected)
        self.show()
        self.raise_()
        self.activateWindow()
        loop = QEventLoop(self)
        self._loop = loop
        try:
            loop.exec()
        finally:
            self._loop = None
        return self.result()

    def done(self, result: int):
        """Close, having first SETTLED any worker thread this dialog owns.

        Seven dialogs (Update Center, Startup Manager, Health Report,
        Activation, the Inspectors, DNS, Context Menu) run a PowerShellTask
        on a QThread parented to themselves. Each already cancels its worker
        in reject() — but cancelling only kills the backend PROCESS. The
        QThread lives on for the moment its read loop needs to unwind, and
        destroying a QThread that is still running is not an exception:
        Qt calls qFatal and the process ABORTS, with no traceback and no
        Qt warning to say why.

        main.PulseApp.closeEvent has always paired cancel() with
        wait(3000) for exactly this reason; the dialogs only ever did the
        first half. It was unreachable from the shipped UI by luck rather
        than design — main._exec_dialog drops its reference but the dialog
        is parented, so C++ keeps it alive past the danger. Anything that
        deletes a worker dialog deliberately (a leak test doing what
        tests/test_audit_hardening.py already does for the other eleven)
        killed the interpreter outright instead of failing.

        done() rather than reject(): it is the single funnel both accept()
        and reject() pass through, so a dialog that closes by ACCEPTING
        with a scan still in flight is covered by the same guard. A no-op
        (two dict scans) for the eleven dialogs that own no thread.
        """
        self._unregister()
        self._settle_worker_threads()
        # Taken BEFORE super().done(), which hides the dialog and can
        # delete it outright under WA_DeleteOnClose — touching self after
        # that point is a use-after-free on the C++ side.
        loop = self._loop
        self._loop = None
        super().done(result)
        if loop is not None:
            loop.quit()

    def _settle_worker_threads(self, timeout_ms: int | None = None):
        """Join every QThread this dialog owns, cancelling only if needed.

        Threads and tasks are discovered by scanning __dict__ rather than
        by naming attributes: the roster uses `_thread`/`_worker` in six
        dialogs and `_scan_thread`/`_toggle_thread` in the Startup Manager,
        and a hand-maintained list of names is exactly the kind of thing
        that goes stale the next time a dialog grows a second worker.

        WHY GRACE BEFORE CANCEL. Cancelling is a process-tree KILL, and
        two of the seven worker dialogs run tasks that WRITE: the DNS
        switcher (SetDnsProfile / RestoreDns) and the context-menu manager
        (ContextMenuToggle / ContextMenuRestore). Neither overrides
        reject(), so dismissing one with Escape or a backdrop click while
        its apply is in flight reaches this method mid-mutation. Killing
        there could strand an adapter with its IPv4 resolvers changed and
        its IPv6 ones not — a worse state than either outcome the user was
        choosing between. Everything these two run finishes well inside
        the grace window, so in practice they complete rather than being
        interrupted.

        The five read-only dialogs pay nothing for it: their reject() has
        already cancelled, so the process is gone and the first wait()
        returns almost immediately.

        ORDER IS LOAD-BEARING on the cancel path. cancel() must come
        before quit(): it terminates the backend process tree, which is
        what unblocks the worker's blocking stdout read. quit() alone
        cannot — the thread's event loop is sitting inside run(), so the
        quit stays queued until run() returns.
        """
        if timeout_ms is None:
            timeout_ms = self._WORKER_WAIT_MS
        held = list(self.__dict__.values())
        threads = [o for o in held if isinstance(o, QThread)]
        tasks = [o for o in held if isinstance(o, PowerShellTask)]

        def running(thread) -> bool:
            try:
                return thread.isRunning()
            except RuntimeError:      # C++ side already gone
                return False

        # 1. let anything still in flight land on its own terms
        for thread in threads:
            if not running(thread):
                continue
            try:
                thread.quit()
                thread.wait(self._WORKER_GRACE_MS)
            except RuntimeError:
                pass

        # 2. anything that outlasted the grace is cancelled and joined —
        #    a dialog must never be destroyed with a live QThread, which
        #    is qFatal (an abort), not an exception.
        if not any(running(thread) for thread in threads):
            return
        for task in tasks:
            try:
                task.cancel()
            except RuntimeError:
                pass
        for thread in threads:
            if not running(thread):
                continue
            try:
                thread.quit()
                thread.wait(timeout_ms)
            except RuntimeError:
                pass


# Every scrollable "row list" selector (App Selector, Dev Hub, Update
# Center, Startup Manager, and a hub's own landing screen) shares this one
# DYNAMIC sizing rule — global theme consistency means these can never
# quietly drift apart the way UpdateCenterDialog (640px) and
# the app selector (560px) once had, and a fixed pixel box can never look
# cramped on a big display or oversized on a small one. Both dimensions
# scale off the HOST WINDOW's *current* size (re-applied live on resize by
# refit_dialog below), landing mid-band of the brief's percentages, with a
# width floor/ceiling so it never goes pocket-sized or absurdly wide on an
# ultrawide monitor. Simple one-off confirmations/wizards (ConfirmDialog,
# CommandPalette, OfficeWizardDialog, ToolInstallWizardDialog) keep their
# own narrower, purpose-built FIXED widths — a two-sentence confirm scaling
# to 1100px on a 4K screen would trade clutter for empty space, not fix it.
#: THE SELECTOR BAND — a scrolling list of rows (Software Catalog, Update
#: Center, Startup Manager, the read-only inspectors).
#:
#: v10.6 NARROWS IT TO 760-840 AND STOPS FIXING ITS HEIGHT, and the second
#: half is the one that fixes the defect. The band used to hand every
#: selector a FIXED height between 460 and 900 derived from the window, on
#: the theory that a list wants a stable viewport. What that produced, on a
#: dialog whose list is short, is the screenshot this pass exists to
#: delete: the Update Center holding ONE update row above ~500px of empty
#: black, and the DNS panel holding ONE adapter card above the same.
#:
#: A stable viewport is worth having when there is enough content to fill
#: it and worthless when there is not, so the height is now the content's,
#: capped. A list of thirty rows still gets a full-height panel and scrolls
#: inside it; a list of one gets a dialog the size of one row.
#:
#: WIDTH COMES DOWN 800-1280 -> 760-840 for the reason the action band is
#: 580-640: past ~840 a row's text runs well beyond the measure at which
#: prose stays readable, and a two-column row (name on the left, version
#: chips on the right) turns into two things separated by a void.
_SELECTOR_WIDTH_FRACTION = 0.55
_SELECTOR_WIDTH_MIN = 760
_SELECTOR_WIDTH_MAX = 840

#: ...and the STARTUP MANAGER's own band, because its row is a different
#: shape from every other selector's and the default band was never sized
#: for it.
#:
#: Every other selector row is [icon | one label | one control]. A startup
#: row is [name | IMPACT badge | recommendation badge | ... | switch] over
#: a second line of type-and-reason prose — four competing elements on one
#: line, three of which are text that cannot shrink. At 840 the badges were
#: being squeezed against StartupRow.SWITCH_COL_W with no gutter, which is
#: the crowding this band exists to fix; the row's own elision (see
#: StartupRow.NAME_MAX_W) handles the name, but elision cannot manufacture
#: room for the two badges, and shrinking THOSE would cost the words that
#: make the audit worth reading.
#:
#: DECLARED, not measured. The dialog used to reach 869 through
#: _content_width_floor — a number nobody chose, which fell out of the
#: widest Run-key name on the developer's machine and would have silently
#: changed the moment the row's elision landed. A band states the intent
#: (880 comfortable, 900 on a wide display) and holds it whatever the
#: content happens to measure.
_STARTUP_WIDTH_MIN = 880
_STARTUP_WIDTH_MAX = 900

#: The tallest a selector may grow before its list starts scrolling inside
#: it. A fraction of the host BODY, so the dialog can never outgrow the
#: window it opens in, and never so tall that a full panel has nowhere to
#: put its footer.
_SELECTOR_HEIGHT_FRACTION = 0.775

#: ...and the floor, which exists for the OPPOSITE reason to the old fixed
#: height: a dialog that is still loading has no content to hug yet, and
#: one that collapsed to a 90px sliver while its scan ran and then jumped
#: to full height would be worse than either size on its own.
_SELECTOR_HEIGHT_MIN = 180

# ------------------------------------------------------------------
#  THE ACTION BAND (v10.5) — the second, deliberately narrow geometry
# ------------------------------------------------------------------
#: A dialog that offers a HANDFUL OF ACTIONS is not a selector, and sizing
#: it like one is what produced the app's worst remaining layout defect.
#:
#: The Microsoft Edge and Microsoft OneDrive hubs offer TWO actions each
#: (remove / reinstall). Built on the selector band they opened at up to
#: 1280 x 900 — a two-row list in a panel sized for a fourteen-card page,
#: with the rows stretched, centred and swimming in several hundred pixels
#: of nothing in every direction. That is the "empty stretched layout"
#: complaint exactly, and it is not fixable by tuning the selector band:
#: the band is CORRECT for a scrolling list of thirty rows, and those two
#: shapes cannot share one number.
#:
#: 580-640 is the width at which a row of [icon | title over description |
#: button] is comfortable and a line of description text lands near the
#: 60-75 character measure that prose is legible at. Past ~640 the
#: description's line length starts to hurt readability rather than help
#: it, which is why this band has a hard ceiling where the selector band
#: has a merely practical one.
#:
#: HEIGHT IS NOT BANDED AT ALL: an action dialog HUGS ITS CONTENT (see
#: _apply_panel_size). A fixed height is what forces a two-row dialog to
#: invent something to put in the space, and there is nothing to put.
_ACTION_WIDTH_MIN = 580
_ACTION_WIDTH_MAX = 640

#: Where inside the band a given window lands. The 60px the band spans is
#: small enough that this is a nicety rather than a layout mechanism — but
#: a dialog pinned to one literal on every display is the thing the app
#: already fixed once for selectors, and re-introducing it here for the
#: sake of a narrower number would be the same mistake at a smaller scale.
#: Measured: 752px (the app minimum) -> 580, 1300 -> 585, 1600 and up -> 640.
_ACTION_WIDTH_FRACTION = 0.45

#: ...but the content it hugs still may not outgrow the window. The panel
#: is capped at this fraction of the host BODY, and anything past it
#: scrolls inside the panel instead of hanging off the app.
_ACTION_HEIGHT_FRACTION = 0.86


def _resolve_host_window(dialog: QDialog) -> QWidget | None:
    """Climb from `dialog` to the real top-level app window — nested
    wizards (a PulseDialog opened from another PulseDialog) are parented
    to the dialog above them, not the app, so this walks up through any
    number of stacked dialogs to the one true QMainWindow."""
    host = dialog.parentWidget()
    if host is None:
        return None
    host = host.window()
    while isinstance(host, QDialog) and host.parentWidget() is not None:
        host = host.parentWidget().window()
    return host


def _content_width_floor(dialog: QDialog) -> int:
    """The width `dialog`'s own content refuses to go below, or 0 before
    that content exists (v1.0).

    A responsive panel is given a FIXED size, so nothing about it yields to
    the layout inside it: when the band's floor lands under what the
    content actually needs, Qt resolves the conflict by shrinking widgets
    below their minimums, and the dialog silently ships with elided labels
    and clipped rows. The Startup Manager was doing exactly that at the
    800px floor — its rows need 869.

    Reading the floor back off the layout keeps that impossible for every
    responsive dialog at once, including ones added later, instead of
    leaving each to be discovered by eye. Returns 0 at construction time
    (no layout yet); refit_dialog re-applies the size from showEvent, by
    which point the content is real and the true floor is known.
    """
    panel = getattr(dialog, "panel", None)
    layout = panel.layout() if panel is not None else None
    return layout.minimumSize().width() if layout is not None else 0


def _selector_panel_width(dialog: QDialog) -> int:
    """Width for a selector panel, derived from the host window's CURRENT
    size — read at construction and again on every host resize
    (refit_dialog), so an open dialog tracks the window rather than
    freezing at its opening size.

    THE CONTENT FLOOR STILL WINS OVER THE CEILING, and that is deliberate
    rather than an oversight in the band. A responsive panel is given a
    fixed width, so nothing about it yields to the layout inside it: when
    the band's ceiling lands under what the content actually needs, Qt
    resolves the conflict by shrinking widgets below their minimums and
    the dialog ships with elided labels and clipped rows. A ceiling that
    clipped content would be choosing empty margins over legibility, which
    is the same trade this whole pass is undoing in the other direction.

    A dialog may also DECLARE its own band via `_selector_width_band`,
    which is the honest version of the same escape hatch. The Startup
    Manager is the one that does (see _STARTUP_WIDTH_MIN): its rows used to
    reach ~869 through the content floor alone — a width nobody chose, which
    fell out of whichever Run key happened to be longest — and a stated band
    survives the row's elision landing, where a measured floor would have
    silently collapsed back to 840 and re-crowded the badges.
    """
    band_min, band_max = getattr(dialog, "_selector_width_band",
                                 (_SELECTOR_WIDTH_MIN, _SELECTOR_WIDTH_MAX))
    floor = max(band_min, _content_width_floor(dialog))
    host = _resolve_host_window(dialog)
    if host is None:
        return floor
    return max(floor, min(band_max,
                          round(host.width() * _SELECTOR_WIDTH_FRACTION)))


def _selector_panel_height_cap(dialog: QDialog) -> int:
    """The tallest a selector may grow before its list scrolls inside it."""
    host = _resolve_host_window(dialog)
    if host is None:
        return _SELECTOR_HEIGHT_MIN * 2
    return max(_SELECTOR_HEIGHT_MIN,
               round(host.height() * _SELECTOR_HEIGHT_FRACTION))


def _action_panel_width(dialog: QDialog) -> int:
    """Width for an ACTION-band panel: inside 580-640, and never under what
    the panel's own content needs.

    The content floor overrides the ceiling for the same reason it does in
    the selector band (see _content_width_floor): a cap that clipped
    content would be choosing empty margins over legibility. In practice it
    never bites here — an ActionRow reports a small minimum by design — but
    a dialog that grew a wide control would widen rather than clip.
    """
    floor = _content_width_floor(dialog)
    host = _resolve_host_window(dialog)
    if host is not None:
        floor = max(floor, round(host.width() * _ACTION_WIDTH_FRACTION))
        # Never wider than the window, whatever the band says. The app's
        # minimum is 752px, so the band fits comfortably — but a dialog is
        # opened INSIDE the window and must stay there at any size.
        floor = min(floor, max(_ACTION_WIDTH_MIN, host.width() - TH.SPACE["xxl"]))
    return max(_ACTION_WIDTH_MIN, min(_ACTION_WIDTH_MAX, floor))


def _apply_panel_size(dialog: QDialog):
    """Size `dialog.panel` for whichever band it declared. Called at
    construction and again from refit_dialog on every host resize, so an
    open dialog tracks the window instead of freezing at its opening size.

    The two bands differ in KIND, not only in numbers:

      "selector"  fixed width AND height, both derived from the host. A
                  scrolling list wants a stable viewport; letting it hug
                  its content would make the panel jump every time a filter
                  changed the row count.

      "action"    fixed width, FREE height. The panel is laid out between
                  two stretches, so a free height resolves to the layout's
                  own sizeHint — the dialog is exactly as tall as the two
                  to four rows it offers, and not one pixel taller. The
                  maximum is the only thing the host contributes.
    """
    band = getattr(dialog, "_responsive_panel", False)
    panel = getattr(dialog, "panel", None)
    if not band or panel is None:
        return
    if band == "action":
        panel.setFixedWidth(_action_panel_width(dialog))
        host = _resolve_host_window(dialog)
        if host is not None:
            panel.setMaximumHeight(
                max(TH.SPACE["xxl"] * 4,
                    round(host.height() * _ACTION_HEIGHT_FRACTION)))
    else:
        # BOTH BANDS HUG THEIR CONTENT NOW. The width is fixed (a list wants
        # a stable column); the height is a MINIMUM plus a cap, so the
        # panel's own layout decides where between them it lands. A
        # one-row Update Center is one row tall; a thirty-row catalog fills
        # the cap and scrolls inside it. See the note on the band.
        panel.setFixedWidth(_selector_panel_width(dialog))
        panel.setMinimumHeight(_SELECTOR_HEIGHT_MIN)
        panel.setMaximumHeight(_selector_panel_height_cap(dialog))


#: The square a catalog row's brand mark is drawn into — the plaque.
#:
#: 28 -> 36, and the argument is legibility rather than presence. Every mark
#: in assets/appicons is the vendor's real artwork (utils/appicons.py has the
#: provenance), and a lot of that artwork is DETAILED: Brave's lion, Discord's
#: face, the VS Code ribbon and Spotify's three arcs all carry internal
#: structure that a 28px box — 10% of which is the optical inset, and more
#: again when the mark sits on a backing plaque — renders as a coloured smudge.
#: Those are the marks a user identifies the row by, so the size that loses
#: them is the size that makes an authentic logo look like an approximation.
#:
#: 36 is not an arbitrary step up: it is TH.CONTROL_H, the height of every
#: operable control in the app, so the icon column lines up with the filter
#: field and the tab pills directly above it instead of floating four pixels
#: shy of them.
APP_ICON_PX = TH.CONTROL_H

#: Height of a pill in a _chip_strip, and of every control that has to line
#: up with one (the catalog's filter field). A named constant because three
#: separate places used to say "30" and a fourth said "34".
#:
#: v15 MAKES IT THE CONTROL HEIGHT, 30 -> 36, and the argument is the one
#: the scale already makes everywhere else: a catalog tab is not a badge,
#: it is a BUTTON — you click it and the list changes — and it shares its
#: row with a text field you type into. Both sat six pixels under every
#: other operable control in the app, on the most-used control row in the
#: biggest dialog, which is precisely where a size that nobody chose is
#: most visible. The pill's ROUNDING still says "chip"; its height now says
#: "control", which is what it is.
_CHIP_H = TH.CONTROL_H

#: Vertical room the strip reserves BELOW its pills for the horizontal
#: scrollbar: a 4px handle with 4px of air above it and 2px below (the
#: bar widget itself is the full 10 — see TH.chip_strip_qss, which must
#: agree with this number). Reserved unconditionally, which is the point:
#: Qt takes the bar out of the viewport only when it is showing, so a
#: strip sized to its pills alone squeezed and clipped them the moment the
#: row overflowed — and the bar then rendered hard against the pill edges,
#: reading as an underline drawn across the tab bar.
#:
#: DERIVED from the scrollbar's own geometry rather than written out, so
#: the lane and the bar are one number by construction — they used to be
#: two literals (10 here, 10 in chip_strip_qss) that agreed only by luck.
_CHIP_LANE = TH.scrollbar_lane()


def _chip_strip(t: dict,
                pill_height: int = _CHIP_H) -> tuple[QScrollArea, QHBoxLayout]:
    """A single-line, horizontally scrolling row of pills — returns the
    (strip, layout) so the caller just addWidget()s its buttons.

    Exists because a responsive selector panel takes its width from a
    content floor that OVERRIDES both the 1100px cap and the host window
    (see _content_width_floor). A plain QHBoxLayout of labelled buttons
    reports the sum of their widths as its minimum, so one row of five
    category tabs silently dragged the whole dialog wider than the window
    containing it. A scroll area reports a small minimum instead, so the
    panel stays inside its band and the overflow becomes scrollable rather
    than clipped.

    Takes the PILL height, not the strip height: the caller sizes the
    thing it can see, and the scrollbar lane is added here so every strip
    reserves it identically. Pills are pinned to the TOP of the strip by a
    stretch UNDER them, so their top edge does not move by half a lane the
    moment the row overflows and the bar takes its space out of the
    viewport. Pinning them with QLayout.setAlignment instead looks
    identical and is a trap: an aligned layout reports its size hint
    rather than its minimum, the scroll area never learns the row is
    wider than the viewport, and the overflowing pills become silently
    unreachable instead of scrollable.
    """
    strip = QScrollArea()
    strip.setWidgetResizable(True)
    strip.setFixedHeight(pill_height + _CHIP_LANE)
    strip.setFrameShape(QFrame.Shape.NoFrame)
    strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    strip.setStyleSheet(TH.chip_strip_qss(t))
    strip.viewport().setStyleSheet("background: transparent;")
    strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    host = QWidget()
    host.setStyleSheet("background: transparent;")
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(0)
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(TH.SPACE["sm"])
    column.addLayout(lay)
    column.addStretch(1)
    strip.setWidget(host)
    return strip, lay


def _dialog_chrome(dialog: PulseDialog, t: dict, accent: str,
                   width: int = 0, radius: int = TH.RADIUS["panel"],
                   anchor: str = "center",
                   responsive: bool | str = False) -> "DepthCard":
    """One shared construction path for every Pulse dialog: the frosted
    DepthCard panel, laid out centered (or top-anchored for the command
    palette) inside the dialog's full-body scrim, plus a soft elevation
    shadow. A drop-shadow QGraphicsEffect is allowed here as the
    deliberate exception to the animations.py doctrine: dialogs are small,
    transient surfaces that repaint a handful of times — not steady-state
    60fps chrome.

    `responsive` picks one of two dynamic geometries, both derived from the
    host window and both re-applied live as it resizes (see
    _apply_panel_size):

        True / "selector"   a scrolling list of rows — fixed width AND
                            height inside the selector band.
        "action"            a handful of offered actions — fixed width in
                            the narrow ACTION band, height hugging content.

    `width` (a fixed pixel value) is used only when `responsive` is False.

    Returns the panel; the caller builds its content layout inside it."""
    # `t` is handed to the DepthCard, which is what lights its top face and
    # paints the CONTACT half of the two-layer elevation (see
    # TH.DIALOG_SHADOW). Every dialog panel had been built without it since
    # the depth tokens landed, so panels were casting an outer shadow with
    # no top face — a shadow printed behind a flat shape, which is the one
    # failure DepthCard's own docstring calls out.
    panel = DepthCard(radius=radius, parent=dialog, t=t)
    dialog._responsive_panel = ("selector" if responsive is True
                               else responsive)
    # Published BEFORE sizing: _apply_panel_size resolves the panel through
    # the dialog (it is also the resize path, which only has the dialog), so
    # it has to be reachable from there by the time it is called.
    dialog.panel = panel
    if responsive:
        _apply_panel_size(dialog)
    else:
        panel.setFixedWidth(width)
    panel.setStyleSheet(TH.dialog_panel_qss(t, accent))

    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    if anchor == "top":
        outer.addSpacing(TH.SPACE["xxl"])
    else:
        outer.addStretch(1)
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(panel)
    row.addStretch(1)
    outer.addLayout(row)
    outer.addStretch(1)

    # The AMBIENT half of the elevation. Values come off TH.DIALOG_SHADOW so
    # the dialog panel, the command palette and any future popup cast the
    # same shadow by construction rather than by three matching literals.
    dx, dy, blur, opacity = TH.DIALOG_SHADOW
    shadow = QGraphicsDropShadowEffect(panel)
    shadow.setBlurRadius(blur)
    shadow.setOffset(dx, dy)
    shadow.setColor(QColor(0, 0, 0, round(255 * opacity)))
    panel.setGraphicsEffect(shadow)
    return panel


def dialog_body(panel: "DepthCard", spacing: str = "md") -> QVBoxLayout:
    """The content layout inside a dialog panel, carrying the ONE padding
    every Pulse dialog uses (v1.0).

    Thirteen dialogs each re-typed `setContentsMargins(28, 24, 28, 22)` by
    hand — an asymmetric quartet that reads as an accident rather than a
    decision, and one a fourteenth dialog would have had to transcribe
    correctly to match. Padding now comes off TH.SPACE like every other
    measurement in the app, so dialogs are consistent by construction.

    `spacing` names the step between the panel's top-level blocks: the
    default "md" suits the usual header / body / action-bar stack, and
    dialogs of dense rows pass "sm".

    v15.1 NAMES THE NUMBER AND SQUARES IT UP. It was 24/24/24/16 — a
    quartet whose asymmetry nothing explained, and whose 24 was a card's
    16 plus half again, so a dialog read visibly looser than the cards it
    was opened from. PAD["sheet"] is the step between (see the note there):
    enough more air than a card that a floating panel feels like one,
    close enough that the two belong to one system. Equal on all four
    sides, because a footer that wants less air below it should say so in
    its own layout rather than by biasing every dialog's padding.
    """
    lay = QVBoxLayout(panel)
    pad = TH.PAD["sheet"]
    lay.setContentsMargins(pad, pad, pad, pad)
    lay.setSpacing(TH.SPACE[spacing])
    return lay


class FitScroll(QScrollArea):
    """A scroll area that reports the height its CONTENT wants, capped.

    A plain QScrollArea reports a fixed, content-independent size hint —
    it is a viewport onto something arbitrarily large, so it has no opinion
    about how tall it should be. That is exactly right when the thing
    holding it has a fixed height to give, and exactly wrong when the
    dialog is trying to hug what is inside: every selector became as tall
    as its band allowed, whether it held thirty rows or one, which is the
    "huge empty black area" this class exists to remove.

    Forwarding the inner widget's hint makes the dialog's own layout able
    to see the content, so a one-row list produces a one-row-tall dialog.
    The cap is what keeps that from inverting the problem: past it the
    hint stops growing and the area goes back to being a viewport, which is
    the correct behaviour for a list that genuinely is long.

    `refresh()` must be called when rows are added or removed. Qt caches a
    child's size hint until something invalidates it, and a list that
    streams rows in (the Update Center's scan) changes height without any
    of the events that would do so on its own.
    """

    #: Sanity bound on the reported hint. The PANEL is what actually caps
    #: a selector's height (_apply_panel_size sets its maximumHeight, and
    #: minimumSizeHint below returns 0 so this area yields to it); this
    #: only stops a pathological list producing an absurd hint on the way
    #: to being clamped.
    HINT_CEILING = 4000

    def __init__(self, parent: QWidget | None = None,
                 max_height: int | None = None):
        super().__init__(parent)
        self._max_height = self.HINT_CEILING if max_height is None else max_height
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)

    def set_max_height(self, height: int):
        if height != self._max_height:
            self._max_height = height
            self.updateGeometry()

    def setWidget(self, widget):    # noqa: N802 - Qt casing
        """Adopt `widget` AND subscribe to its layout changes.

        The subscription is the whole reason this is overridden. Qt caches
        a child's size hint and only re-asks when something invalidates it,
        and a QScrollArea deliberately does not propagate its content's
        hint at all — so a list that gains rows after construction (the
        Update Center streams them in as the scan finds them, the catalog's
        filter hides and shows them) kept reporting the height it had when
        it was empty. Measured before this: a 30-row Update Center produced
        exactly the same panel height as a 1-row one.

        Watching for LayoutRequest catches every one of those paths without
        any of them having to remember to call refresh() — which is the
        same reason PulseApp used to watch scrollbar ranges rather than
        subscribing to each feature that might move a card.
        """
        super().setWidget(widget)
        if widget is not None:
            widget.installEventFilter(self)

    def eventFilter(self, obj, event):   # noqa: N802 - Qt casing
        if (obj is self.widget()
                and event.type() == QEvent.Type.LayoutRequest):
            self.updateGeometry()
        return super().eventFilter(obj, event)

    def refresh(self):
        """Re-ask the content how tall it is.

        Rarely needed — setWidget subscribes to the content's layout
        requests — but a caller that changes a hint WITHOUT a relayout
        (setFixedHeight on a child, say) has no other way to say so.
        """
        inner = self.widget()
        if inner is not None:
            inner.adjustSize()
        self.updateGeometry()

    def _content_height(self) -> int:
        """How tall the content is AT THE WIDTH IT WILL BE LAID OUT AT.

        THE WIDTH IS THE WHOLE POINT, and asking without it is what put
        the black voids back into dialogs that this class was written to
        remove. `layout.sizeHint().height()` is measured against the
        layout's own PREFERRED width, and every wrapping QLabel in the app
        prefers a narrower column than a 840px selector panel actually
        gives it — so the hint describes a taller, skinnier version of the
        content than the one that gets painted. The dialog then sized
        itself to that phantom, the real text wrapped onto fewer lines,
        and the difference showed up as dead space under the last card.

        Measured on the DNS switcher: the host's layout hinted 311px while
        the same content laid out at the panel's real width occupied 266 —
        45px of void, on a 467px dialog, entirely from asking the wrong
        question.

        A QBoxLayout reports hasHeightForWidth() whenever any item in it
        does (a word-wrapping QLabel does), so this costs nothing on the
        layouts that have no such dependency: they answer the same number
        either way.

        The width is taken from the VIEWPORT rather than from self, since
        that is what the inner widget is actually resized to — they differ
        by the frame and, once the list is long enough to scroll, by the
        vertical scrollbar's lane. Before the area has been laid out even
        once, neither is meaningful and the sizeHint is the only answer
        available; that first call is always followed by a real one.
        """
        inner = self.widget()
        if inner is None:
            return 0
        layout = inner.layout()
        if layout is None:
            return inner.sizeHint().height() + 2 * self.frameWidth()
        width = self.viewport().width()
        if layout.hasHeightForWidth() and width > 0:
            hint = layout.heightForWidth(width)
        else:
            hint = layout.sizeHint().height()
        return hint + 2 * self.frameWidth()

    def resizeEvent(self, event):   # noqa: N802 - Qt casing
        """A width change changes the answer (see _content_height), so it
        has to invalidate the hint the same way a row change does.

        Without this the area keeps reporting the height it computed at
        whatever width it happened to have when the content last changed —
        which for a dialog that is sized FROM this hint means the first
        measurement wins permanently, and widening the window leaves the
        void it was supposed to close."""
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self.updateGeometry()

    def sizeHint(self):            # noqa: N802 - Qt casing
        hint = super().sizeHint()
        hint.setHeight(max(0, min(self._content_height(), self._max_height)))
        return hint

    def minimumSizeHint(self):     # noqa: N802 - Qt casing
        """Zero height, so the area is free to be squeezed by a panel that
        has hit its own cap. Without it the content's hint becomes a FLOOR
        the dialog must honour, and a long list would push the panel past
        the window instead of scrolling."""
        hint = super().minimumSizeHint()
        hint.setHeight(0)
        return hint


def fit_stack(stack: QStackedWidget) -> QStackedWidget:
    """Make a page stack report the CURRENT page's height, not the tallest.

    QStackedLayout's size hint is the maximum over every page, because all
    of them keep their geometry so a switch costs no relayout. In a dialog
    that hugs its content that is a permanent tax paid by the shortest
    page: the Update Center's results page holding ONE row still reserved
    the height of its empty-state page (a hero-sized glyph, a centred
    sentence and two stretches), which is ~90px of black under a single
    row and exactly the defect the hugging band was added to remove.

    The fix is the standard one: every page except the current is given an
    IGNORED vertical policy, so it contributes nothing to the hint, and the
    stack re-adjusts whenever the current page changes. Pages still keep
    their geometry, so switching is still free.

    Returns the stack, so it can be used inline.
    """
    def follow(_index: int = 0):
        current = stack.currentWidget()
        for i in range(stack.count()):
            page = stack.widget(i)
            page.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Preferred if page is current
                else QSizePolicy.Policy.Ignored)
        if current is not None:
            current.adjustSize()
        stack.adjustSize()
        stack.updateGeometry()

    stack.currentChanged.connect(follow)
    follow()
    return stack


def row_padding(layout) -> None:
    """The ONE inset every list row uses: 12px vertical, 16px horizontal.

    Five row types carry it — the software catalog's, the Update Center's,
    the Startup Manager's, a hub's ActionRow and a playbook's step row —
    and three of them had already converged on it independently while the
    other two had not: the action row ran 16/12/12/12 (an optical
    correction for the button at its right edge, which is a real effect and
    not worth a second padding rule for), and the step row ran 12/8/12/8.

    Stated once so a sixth row type inherits it instead of picking. The
    vertical step is `md` and the horizontal `lg` because a row is wider
    than it is tall and equal insets read as vertically loose — the same
    reason a card, which is nearly square, uses equal ones.
    """
    layout.setContentsMargins(TH.SPACE["lg"], TH.SPACE["md"],
                              TH.SPACE["lg"], TH.SPACE["md"])


def dialog_footer(lay: QVBoxLayout, *buttons: QPushButton) -> QHBoxLayout:
    """The action bar every dialog closes with: a single step of air, then
    the buttons right-aligned in the order given, primary last.

    THIRTEEN DIALOGS BUILT THIS BY HAND and disagreed about all three of
    its measurements — the gap above it was `addSpacing(TH.SPACE["xs"])`,
    `addSpacing(TH.SPACE["md"])` or nothing at all; the gap between two
    buttons was whatever QHBoxLayout's default happened to be in that
    dialog's font; and the buttons themselves were sized 96x36, 112x26,
    160x36 and 128x36 depending on how long their label was.

    Button PROPORTIONS are settled here too, and that is the half a shared
    helper can actually fix. Every dialog button is TH.CONTROL_H tall (the
    app's one primary-control height, already pinned by
    test_layout_contract) and at least _FOOTER_BTN_W wide, so a "Close"
    and an "Update Selected (14)" sit on one baseline as two members of one
    set rather than as a chip beside a slab. Wider labels still grow — a
    minimum, never a fixed width, because truncating a button's own verb is
    the one thing worse than an uneven row.

    Right-aligned with the primary LAST: the caller passes them in reading
    order and the destructive/secondary/primary ordering falls out of that,
    matching every native Windows and macOS sheet.
    """
    lay.addSpacing(TH.SPACE["xs"])
    row = QHBoxLayout()
    row.setSpacing(TH.SPACE["sm"])
    row.addStretch(1)
    for button in buttons:
        row.addWidget(size_dialog_button(button))
    lay.addLayout(row)
    return row


#: Minimum width of a dialog footer button. 96 is what eleven of the
#: thirteen hand-built footers had already converged on; the two that had
#: not were the ones that looked wrong.
_FOOTER_BTN_W = 96


def size_dialog_button(button: QPushButton) -> QPushButton:
    """Give one dialog action button the app's standard proportions.

    Height is TH.CONTROL_H, the app's single primary-control height, and
    width is a MINIMUM the label may grow past — which is the half that
    actually changed. Every one of these used to be `setFixedSize(N, 36)`
    with N hand-picked per button: 96, 110, 112, 122, 128, 132, 150, 160,
    170, 214. Ten literals for one element.

    A FIXED width is also wrong on its own terms wherever a button's label
    is not fixed, and several are not: the Update Center's CTA cycles
    through "Update Selected", "Update Selected (3)" and "Update All (14)"
    inside one 160px box, so the same button reads cramped at its longest
    label and adrift at its shortest. A floor plus sizeHint is the shape
    that fits both — the row still lines up, because 96 is the floor every
    short label lands on, and a long label is allowed the room it needs
    rather than being elided inside a number chosen for a different string.

    Returns the button so it can be used inline.
    """
    button.setMinimumWidth(_FOOTER_BTN_W)
    button.setFixedHeight(TH.CONTROL_H)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    # A MARK, so "is this a dialog action button?" is answerable from
    # outside. The alternative is inferring it from geometry, and geometry
    # is precisely what the mark exists to police — a test that guessed by
    # height would sweep up icon tools and row controls, and would go quiet
    # about the one button that had drifted, since a drifted button is
    # exactly the one the guess stops recognising.
    button.setProperty("dialogAction", True)
    return button


def scroll_host_layout(host: QWidget, spacing: str = "sm") -> QVBoxLayout:
    """The column inside a dialog's QScrollArea. The right margin is a
    GUTTER for the scrollbar, not decoration — without it the bar overlaps
    the last few pixels of every row — and it was being eyeballed as 4 or 6
    depending on the dialog."""
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, TH.SPACE["sm"], 0)
    lay.setSpacing(TH.SPACE[spacing])
    return lay


def refit_dialog(dialog: PulseDialog):
    """Resize `dialog` to exactly cover its host window's BODY — always
    fully below the title bar, so minimize/maximize/close stay visible
    and reachable no matter what is open — with a square scrim, matching
    the now square-and-opaque shell. Called from showEvent and again whenever the
    host resizes while a dialog is open — which is also what keeps a
    responsive selector panel (see _dialog_chrome) sized to the window
    live, instead of freezing at its opening-time dimensions."""
    host = _resolve_host_window(dialog)
    if host is not None:
        titlebar_h = getattr(getattr(host, "titlebar", None), "height", lambda: 0)()
        body = QRect(0, titlebar_h, host.width(), host.height() - titlebar_h)
        dialog.setGeometry(QRect(host.mapToGlobal(body.topLeft()), body.size()))
        theme_mgr = getattr(host, "theme", None)
        if theme_mgr is not None:
            # Square in both states: the shell it covers is now square in
            # both states too (DWM owns the window's rounding), so a
            # rounded scrim would leave four lit wedges of shell showing.
            dialog._set_scrim(theme_mgr.t, 0)

    # OUTSIDE the host check, deliberately. Panel sizing used to sit inside
    # it, so a dialog with no resolvable host kept whatever size it was
    # given at construction — which is before its content exists, and so
    # before _content_width_floor can know what that content needs. The
    # host governs how the panel scales; it does not govern whether the
    # panel is allowed to fit its own contents.
    _apply_panel_size(dialog)


def _present_dialog(dialog: PulseDialog, duration_ms: int = 130):
    """Fit + entrance for every dialog, called from showEvent. Entrance is
    a quick compositor-side windowOpacity fade — no QGraphicsEffect
    involved in the animation."""
    refit_dialog(dialog)
    # AFTER refit, never before. refit_dialog is what gives the dialog its
    # real geometry (the host's full body), and the frost is registered to
    # the pixels behind that exact rectangle — so capturing any earlier
    # renders the wrong region at the wrong offset and paintEvent stretches
    # the mistake over the whole backdrop. See PulseDialog.showEvent.
    dialog._capture_backdrop()
    dialog.setWindowOpacity(0.0)
    anim = QPropertyAnimation(dialog, b"windowOpacity", dialog)
    anim.setDuration(duration_ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(EASE_OUT)
    anim.start()
    dialog._entrance_anim = anim  # keep alive for the run


# ============================================================
#  TITLE BAR — drag, double-click max, Fluent caption buttons
# ============================================================
def _caption_icon_font() -> QFont | None:
    """Native Windows caption glyphs: Segoe Fluent Icons (Win11), falling
    back to Segoe MDL2 Assets (Win10). None on other platforms / missing
    fonts — the title bar then uses plain text glyphs."""
    if sys.platform != "win32":
        return None
    from PySide6.QtGui import QFontDatabase
    for family in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if family in QFontDatabase.families():
            font = QFont(family)
            # NOT TH.ICON. These are the OS's own minimize / maximize /
            # close glyphs, drawn to Windows' caption-button metrics rather
            # than to this app's icon scale — the point of using Segoe
            # Fluent Icons here at all is that the buttons are
            # indistinguishable from every other window's. A scale defined
            # for Pulse's own chrome has no authority over them.
            font.setPixelSize(13)
            return font
    return None


class TitleBar(QWidget):
    """Frameless-window chrome. Left: brand block (glyph, name, version,
    release-channel pill). Right: the native-styled caption buttons, using
    the OS's own Segoe Fluent icon glyphs.

    v15 REMOVED THE THEME TOGGLE FROM THIS BAR, and the removal is worth
    more than the tidier composition it buys. Every pixel of the title-bar
    strip is answered as HTCAPTION so Windows itself drives the drag (Aero
    Snap, drag-to-top maximize, double-click, the right-click system menu,
    and — because it bypasses Qt's input routing — a strip that stays live
    while a modal dialog is open). A plain Qt button sitting in that strip
    is therefore a contradiction: it needed a hand-measured HTCLIENT hole
    punched through the drag region to receive a click at all
    (`PulseApp._over_theme_button`, ~15 lines of DPI-aware physical-pixel
    mapping that had to stay in sync with the button's geometry). The
    toggle now lives in the sidebar's status rail with the rest of the
    session chrome (widgets.StatusRail), and the hole is gone with it.

    Drag guard: dragging while maximized restores the window first and
    re-anchors it under the cursor proportionally — native Windows feel.

    Snap Layouts contract (Windows 11): main.nativeEvent answers
    WM_NCHITTEST with HTMAXBUTTON over `btn_max`, which makes Windows
    show its Snap Layouts flyout on hover — but also means Qt no longer
    receives mouse events for that button. `set_nc_hover()` mirrors the
    hover visual and the click is re-injected from WM_NCLBUTTONUP.
    """

    # (caption-font glyph, text fallback)
    _ICONS = {
        "min":     ("", "–"),
        "max":     ("", "□"),
        "restore": ("", "❐"),
        "close":   ("", "✕"),
    }

    def __init__(self, window: QMainWindow, t: dict,
                 app_name: str, version: str, channel: str = "",
                 is_admin: bool = True):
        super().__init__(window)
        self._window = window
        self._drag_offset: QPoint | None = None
        self._press_gp: QPoint | None = None
        self._icon_font = _caption_icon_font()
        self.setFixedHeight(50)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(TH.SPACE["xl"], TH.SPACE["sm"],
                               TH.SPACE["md"], TH.SPACE["sm"])
        lay.setSpacing(TH.SPACE["sm"])

        # The STATIC face of the shared brand mark (widgets.BrandMark).
        # The dashboard's 58px masthead instance still breathes; a logo in
        # the chrome does not, and — more to the point — is drawn to be
        # read at 30px rather than scaled down from a hero. See BrandMark
        # for the four things that changed and why each of them was
        # costing this mark its contrast.
        self._glyph = BrandMark("✦", size=36, accent=t["accent"],
                                breathe=False)
        lay.addWidget(self._glyph)
        self._name = QLabel(app_name)
        lay.addWidget(self._name)
        # THE VERSION AND CHANNEL ARE NOT HERE ANY MORE, and `version` /
        # `channel` are still taken so the caller does not have to know
        # that (they are what the tooltip is built from).
        #
        # They were "v10.8.0" and a "BETA" pill sitting immediately right
        # of the wordmark — and the SAME two facts, in the same order,
        # already sit in the sidebar's status rail as "PULSE v10.8.0 ·
        # BETA", where they are also a BUTTON that checks for updates. So
        # the chrome carried the app's version twice, and the copy that
        # could act on it was the one nobody was looking at. One home, and
        # it is the one that does something.
        self.setToolTip(f"{app_name} v{version}"
                        + (f" · {channel.upper()}" if channel else ""))
        # The left cluster is a brand-only block: elevation state, the
        # theme toggle and the update check all live in the sidebar's
        # status rail (widgets.StatusRail), which is the one place in the
        # app that describes the session rather than the work.
        lay.addStretch()

        btns = QHBoxLayout()
        btns.setSpacing(TH.SPACE["xxs"])

        def _mk(icon_key: str, tip: str, slot) -> QPushButton:
            b = QPushButton(self._icon(icon_key))
            b.setFixedSize(40, 30)
            b.setToolTip(tip)
            # The label a screen reader announces. Qt builds a button's
            # accessible NAME from its text, and this button's text is a
            # Private Use Area codepoint - so without this the three
            # controls every window must expose announce an unassigned
            # character. setToolTip maps to the DESCRIPTION, not the name,
            # so it cannot stand in for this.
            b.setAccessibleName(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if self._icon_font is not None:
                b.setFont(self._icon_font)
            b.clicked.connect(slot)
            btns.addWidget(b)
            return b

        self._btn_min = _mk("min", "Minimize", window.showMinimized)
        self.btn_max = _mk("max", "Maximize", self._toggle_max)
        self._btn_close = _mk("close", "Close", window.close)
        lay.addLayout(btns)

        # keep the max/restore glyph honest however the state changes
        window.installEventFilter(self)
        self.apply_theme(t)

    def _icon(self, key: str) -> str:
        fluent, fallback = self._ICONS[key]
        return fluent if self._icon_font is not None else fallback

    # -- the brand lockup, shown only where it is not a duplicate --
    def set_brand_visible(self, on: bool):
        """Show or hide the mark AND the wordmark together.

        THE WHOLE LOCKUP, not just the mark, and that is the point rather
        than an over-reach. On the dashboard the masthead already carries
        ✦ at 58px with PULSE at 34px directly beneath this bar — so the
        title bar's ✦ + PULSE is the same lockup at a sixth of the size,
        forty pixels above the original. Hiding only the mark would leave
        an orphaned "PULSE" above a bigger "PULSE": one duplicate traded
        for a worse one.

        On every other view the masthead is not on screen, and the bar is
        the only thing identifying the app — so the lockup comes back. The
        window is still draggable by the empty strip either way: the whole
        bar answers HTCAPTION, not just the widgets in it (see the class
        docstring), so removing them from view costs no drag surface.
        """
        self._glyph.setVisible(on)
        self._name.setVisible(on)

    # -- theming ----------------------------------------------
    def apply_theme(self, t: dict):
        self._t = t
        self._glyph.apply_theme(t)
        self._name.setStyleSheet(TH.label_qss(t, "brand"))
        for btn in (self._btn_min, self.btn_max):
            btn.setStyleSheet(TH.titlebar_button_qss(t, t["titlebar_hover"]))
        self._btn_close.setStyleSheet(TH.titlebar_close_qss(t))

    # -- non-client caption support (driven by main.nativeEvent) --
    # Windows owns the mouse events for all three caption buttons while
    # WM_NCHITTEST maps their (generously expanded) zones to HTMINBUTTON /
    # HTMAXBUTTON / HTCLOSEBUTTON — that's what makes the top-right corner
    # region clickable like a native app instead of demanding a
    # pixel-perfect hit on the 40×30 glyph. Qt therefore never sees
    # Enter/Leave there; hover visuals are mirrored via property flips.
    def caption_buttons(self) -> dict[str, QPushButton]:
        """The NC-hit-tested caption buttons, keyed by role."""
        return {"min": self._btn_min, "max": self.btn_max,
                "close": self._btn_close}

    def set_nc_hover(self, key: str | None):
        """Highlight exactly the caption button under the non-client
        cursor (`None` clears all). Cheap no-op unless a state flips."""
        for name, btn in self.caption_buttons().items():
            on = (name == key)
            if bool(btn.property("nchover")) != on:
                btn.setProperty("nchover", on)
                btn.style().unpolish(btn)
                btn.style().polish(btn)

    # -- maximize / restore -----------------------------------
    def _toggle_max(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def _sync_max_glyph(self):
        maxed = self._window.isMaximized()
        label = "Restore" if maxed else "Maximize"
        self.btn_max.setText(self._icon("restore" if maxed else "max"))
        self.btn_max.setToolTip(label)
        # Renamed with the glyph, not fixed at construction: a name that
        # said "Maximize" on an already-maximized window would describe
        # the opposite of what pressing it does.
        self.btn_max.setAccessibleName(label)

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() == QEvent.Type.WindowStateChange:
            self._sync_max_glyph()
        return False

    # -- drag to move: NATIVE system move first ----------------
    # startSystemMove() hands the drag to Windows itself, which is what
    # makes Aero Snap zones, drag-to-top maximize, shake-to-minimize and
    # restore-from-maximized behave exactly like a native Win11 app.
    # The move starts on the first real drag (4px threshold), never on
    # press, so double-click-to-maximize still gets its events. The old
    # manual path remains as the fallback for platforms without support.
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_gp = e.globalPosition().toPoint()
            self._drag_offset = (e.globalPosition().toPoint()
                                 - self._window.frameGeometry().topLeft())

    def mouseMoveEvent(self, e):
        if self._drag_offset is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        gp = e.globalPosition().toPoint()
        if self._press_gp is not None:
            if (gp - self._press_gp).manhattanLength() < 4:
                return
            self._press_gp = None
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemMove():
                self._drag_offset = None
                return
        # manual fallback
        if self._window.isMaximized():
            # restore, then re-anchor the (now smaller) window under the
            # cursor at the same horizontal ratio — no visual jump
            ratio = e.position().x() / max(1.0, float(self.width()))
            self._window.showNormal()
            self._drag_offset = QPoint(
                int(self._window.width() * ratio), int(e.position().y()))
        self._window.move(gp - self._drag_offset)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        self._press_gp = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()


# ============================================================
#  NAV BUTTON — sidebar category entry with painted glow
# ============================================================
class NavButton(QPushButton):
    """Sidebar module entry — v7: a painted, accent-tinted icon PLAQUE
    holding one monochrome Fluent glyph, the module title, a left Aurora
    active-rail when selected, and the effect-free painted glow/ripple. The
    glyph comes from theme.GLYPHS via a semantic key, so the whole sidebar
    reads as one coherent line-icon system instead of mismatched emoji."""

    #: Plaque edge, from the app-wide scale — the card's icon well is the
    #: same object at the same size (see theme.PLAQUE_SIZE).
    _PLAQUE = TH.PLAQUE_SIZE
    #: Left inset. Read from the rail's own gutter rather than repeated as a
    #: literal, which is what the comment here used to ask a reader to do by
    #: hand ("must stay in sync with nav_button_qss padding") — and what the
    #: MODULES label above these wells failed to do for four versions.
    _PLAQUE_X = TH.SIDEBAR_GUTTER

    #: What SELECTION does to the icon well: the same neutral, harder.
    #:
    #: Named because it is the one number describing the well that lives
    #: outside theme.py, and because a test has to be able to measure the
    #: lifted well's contrast without re-typing the multiplier (see
    #: test_elevation's glyph-floor sweep, which walks every surface the
    #: well can land on — and the lifted rail well is one of them).
    #:
    #: The well is neutral in both states on purpose: "which module is live"
    #: stays a question of VALUE, which survives at a glance and in both
    #: themes, rather than a question of hue.
    _SELECTED_LIFT = 2.4

    def __init__(self, glyph_key: str, title: str, accent_key: str, t: dict):
        # QPushButton treats a lone "&" as a mnemonic marker (it vanishes
        # and the following character gets an accelerator underline) —
        # category titles like "Maintenance & Repair" need it escaped to
        # "&&" or the button renders "Maintenance _Repair". The icon is now
        # PAINTED (a plaque), so only the title is button text.
        super().__init__(title.replace("&", "&&"))
        self._glyph_key = glyph_key
        # v10: the module's accent KEY, not a frozen hex — re-resolved on
        # every theme switch inside apply_theme (see theme.resolve_accent).
        self._accent_key = accent_key
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", False)
        self._glow = GlowController(self, TH.resolve_accent(t, accent_key))
        self._ripple = RippleController(self)
        self._accent = QColor(TH.resolve_accent(t, accent_key))
        self._accent2 = QColor(t["accent2"])
        self._icon_font: QFont | None = None
        self._well = QColor(255, 255, 255, 10)
        self._light = False
        self._bevel = TH.bevel_alphas(t)
        self.apply_theme(t)

    def apply_theme(self, t: dict):
        self.setStyleSheet(TH.nav_button_qss(t))
        # the module's OWN colour for this theme — the sidebar rail reads as
        # a spectrum, and the glow/plaque follow it (previously the plaque
        # used the module colour while the glow used the generic app accent,
        # so a hovered nav entry lit up in the wrong colour).
        self._accent = QColor(TH.resolve_accent(t, self._accent_key))
        self._glow.set_accent(TH.resolve_accent(t, self._accent_key))
        self._glow.set_alphas(*TH.glow_alphas(t))
        self._accent2 = QColor(t["accent2"])
        self._glyph_char, self._glyph_fluent = TH.glyph(self._glyph_key)
        self._icon_font = TH.icon_font(TH.ICON["plaque"]) if self._glyph_fluent else None
        # v9 "Spectrum": the idle glyph carries its own module accent (was a
        # monochrome text_soft), so all six modules read as a colored rail at
        # rest — matching the newly-colored GlassCard plaques (icon_plaque_qss).
        self._glyph_color_idle = QColor(self._accent)
        # the plaque well, shared with widgets.IconPlaque
        self._well = TH.to_qcolor(t["plaque_well"])
        self._light = t["name"] == "light"
        # the edge weights this mode spends — see paintEvent for why the
        # rail is the one surface that spends them conditionally
        self._bevel = TH.bevel_alphas(t)

    def set_selected(self, on: bool):
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._ripple.trigger(e.position())
        super().mousePressEvent(e)

    # A stylesheet that sets a border suppresses Qt's own focus rect, and
    # with it the repaint Qt would have scheduled to draw one. The ring in
    # paintEvent therefore has to ask for its own frame, or it appears
    # only when something unrelated happens to repaint the row.
    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()

    def _paint_plaque(self, p: QPainter):
        """The rail's icon well — the same micro-surface the cards wear.

        v13 brings it into line with widgets.IconPlaque: a soft accent
        halo outside the well and a lit inner rim inside it. The two
        plaques are the same element in two places, and before this they
        were built by two different pieces of code that agreed on nothing
        but the tint. A sidebar entry and the card it opens now read as one
        object seen twice, which is most of what "cohesion" means here.

        The nav plaque keeps its own SELECTED state (the card has no such
        thing), and its own lighter tint: on the rail's panel tier the
        card's 0.24 wash reads as a solid colour chip.
        """
        selected = bool(self.property("selected"))
        y = (self.height() - self._PLAQUE) / 2.0
        box = QRectF(self._PLAQUE_X, y, self._PLAQUE, self._PLAQUE)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # THE SAME NEUTRAL WELL THE CARDS PAINT (see IconPlaque). This used
        # to be four accent-tinted passes — halo, wash, hairline, lit rim —
        # brightened again when selected, which made the rail its own small
        # design language: six colours down the sidebar, each with a ring
        # around it. The glyph still carries the module's colour and the
        # indicator bar still says which module is live, so the well was
        # the third thing saying it.
        #
        # SELECTION LIFTS THE WELL RATHER THAN COLOURING IT: the same
        # neutral, a little stronger. That keeps "which one is live" a
        # question of value, which survives at a glance and in both themes,
        # instead of a question of hue against five other hues.
        well = QColor(self._well)
        if selected:
            well.setAlphaF(min(1.0, well.alphaF() * self._SELECTED_LIFT))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(well)
        p.drawRoundedRect(box, TH.PLAQUE_RADIUS, TH.PLAQUE_RADIUS)

        # glyph
        p.setPen(self._accent if selected else self._glyph_color_idle)
        if self._icon_font is not None:
            p.setFont(self._icon_font)
        else:
            f = QFont(self.font())
            f.setPixelSize(TH.ICON["inline"])
            p.setFont(f)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, self._glyph_char)

    def paintEvent(self, e):
        super().paintEvent(e)  # QSS background/text first
        p = QPainter(self)
        self._paint_plaque(p)
        radius = TH.RADIUS["plaque"]
        # A BEVEL IS AN EDGE ON A SURFACE, AND AT REST THIS ROW IS NOT ONE.
        #
        # This call used to take paint_bevel_frame's own defaults — 0.14
        # white / 0.20 black — which made the rail the only thing in the app
        # painting a theme-agnostic edge, and the two modes rendered it as
        # two different components. On obsidian a black bottom-right shade
        # is invisible and the white top-left is a whisper, so dark got the
        # "ghost rail" nav_button_qss describes: a bare transparent row
        # carrying only its plaque and its label. On porcelain BOTH halves
        # of that gradient land, so light mode drew a closed grey rectangle
        # around every entry — four outlined boxes down a rail that is
        # supposed to read as light and airy, and an outline around four
        # rows whose QSS background is `transparent`.
        #
        # The weights now come from the theme like every other painted edge
        # (theme.bevel_alphas), and they are spent only where the row
        # actually HAS a surface to bevel: full when selected, ramping in
        # with the pointer otherwise. QUANTIZED through hover_lift for the
        # reason that function documents — paint_bevel_frame caches its
        # stroke keyed on the alpha pair, so a continuously-varying weight
        # would mint a new full-size stroke on every frame of every hover.
        lift = (1.0 if self.property("selected")
                else TH.hover_lift(self._glow.intensity))
        if lift > 0.0:
            lit, shade = self._bevel
            paint_bevel_frame(p, self.rect(), radius, lit * lift, shade * lift)
        paint_ripple_frame(p, self.rect(), radius, self._glow.color,
                           self._ripple.progress, self._ripple.origin)
        paint_glow_frame(p, self.rect(), radius, self._glow.color,
                         self._glow.intensity, self._glow.cursor,
                         halo_alpha=self._glow.halo_alpha,
                         edge_alpha=self._glow.edge_alpha)
        if self.property("selected"):
            paint_nav_indicator(p, self.rect(), self._glow.color, self._accent2)
        # KEYBOARD FOCUS RING. These four rows are second through fifth in
        # the tab chain and had no focus affordance of any kind — no
        # :focus rule in nav_button_qss and no branch here — so tabbing
        # into the sidebar moved focus somewhere invisible. Measured at
        # zero changed pixels before this existed, which is the whole
        # defect: the v10 keyboard layer routes through these entries.
        #
        # Same treatment as GlassCard, deliberately, so one ring means one
        # thing everywhere: a solid 2px accent stroke rather than Qt's
        # dotted default (invisible on this material), painted LAST so it
        # sits above the hover glow and stays unambiguous on a row the
        # pointer is also over — hover and focus mean different things and
        # a pointer resting elsewhere must not mask where the keyboard is.
        #
        # Inset by half the pen so the stroke lands INSIDE the row's own
        # rect: at rect() the outer pixel of a 2px pen straddles the edge
        # and bleeds over the neighbouring row, which on a 4px-spaced rail
        # reads as one thick divider between two entries.
        if self.hasFocus():
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setBrush(Qt.BrushStyle.NoBrush)
            ring = QColor(self._glow.color)
            ring.setAlphaF(0.95)
            p.setPen(QPen(ring, 2.0))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1),
                              radius - 1, radius - 1)
        p.end()


# ============================================================
#  GLASS CARD — one operation, painted glow, live re-skin
# ============================================================
def format_relative_age(timestamp: float, now: float | None = None) -> str:
    """A short, honest "how long ago" for a card caption.

    Deliberately COARSE and rounded down: "3 days ago" is what someone
    wants to know, and a precise "2 days 21 hours ago" reads as noise on a
    card. Rounding down also keeps the label from ever overstating how
    recent a run was, which is the direction that would mislead.
    """
    if not timestamp:
        return ""
    now = time.time() if now is None else now
    seconds = now - timestamp
    if seconds < 0:
        # Clock moved backwards (DST, NTP correction, a restored profile).
        # "Just now" is the only claim still defensible.
        return "just now"
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}m ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    if days < 7:
        return f"{int(days)}d ago"
    weeks = days / 7
    if weeks < 5:
        return f"{int(weeks)}w ago"
    months = days / 30
    if months < 12:
        return f"{int(months)}mo ago"
    return f"{int(days / 365)}y ago"


def format_duration(milliseconds: float) -> str:
    """Compact duration for the "typically ~Ns" hint."""
    if milliseconds <= 0:
        return ""
    seconds = milliseconds / 1000.0
    if seconds < 60:
        return f"{max(1, int(round(seconds)))}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(round(minutes))}m"
    hours = minutes / 60
    if hours < 10:
        # One decimal only where it carries information (1.5h, not 1.0h).
        text = f"{hours:.1f}".rstrip("0").rstrip(".")
        return f"{text}h"
    return f"{int(round(hours))}h"


def format_history_caption(entry: dict | None) -> tuple[str, str]:
    """(pill text, tooltip) for a task's run history — ("", "") when there
    is nothing truthful to say.

    The duration half is withheld until a task has run more than once: a
    single sample is not a "typical" duration, and presenting it as one
    would be a confident-sounding guess drawn from one data point.
    """
    if not entry:
        return "", ""
    age = format_relative_age(entry.get("last_ts", 0.0))
    if not age:
        return "", ""

    runs = int(entry.get("runs", 0))
    duration = format_duration(entry.get("avg_ms", 0.0)) if runs > 1 else ""
    # Terse by design. "Ran 3 days ago" reads better in isolation but this
    # sits in a card footer beside the APPLIED chip, and every character
    # here is width the responsive grid has to find (see ElidedCaption).
    # The full sentence lives in the tooltip.
    text = age + (f" · ~{duration}" if duration else "")

    detail = [f"Last run {age}"]
    last_ms = entry.get("last_ms", 0.0)
    if last_ms:
        detail.append(f"took {format_duration(last_ms)}")
    if runs > 1:
        detail.append(f"{runs} runs recorded, averaging {duration}")
    if entry.get("outcome") == "err":
        detail.append("the last run reported an error")
    return text, " · ".join(detail)


def _derive_card_meta(item: dict) -> list[str]:
    """The count/hint pills a card shows in its v7 meta footer — derived
    from the item's own shape so the footer stays truthful without any
    hand-authored metadata. A hub reports how many options it holds; a
    selector reports its app count; the specialised launchers name their
    action. Plain one-shot actions return [] (no footer, no chevron)."""
    # Explicit override — the Welcome dashboard's module launchpad cards
    # pass their own 'N operations' label so they read as enterable modules
    # (pill + drill-in chevron) without being a hub/selector themselves.
    if item.get("meta_label"):
        return [item["meta_label"]]
    if item.get("hub"):
        subs = item.get("items")
        if not subs and item.get("groups"):
            subs = [s for g in item["groups"] for s in g.get("items", [])]
        n = len(subs or [])
        return [f"{n} options" if n != 1 else "1 option"]
    if item.get("apps"):
        n = len(item["apps"])
        return [f"{n} apps"]
    if item.get("devhub"):
        return ["Pick & deploy"]
    if item.get("update_center"):
        return ["Live scan"]
    if item.get("startup_manager"):
        return ["Audit & toggle"]
    if item.get("wizard"):
        return ["Guided setup"]
    return []


class ResponsiveGridHost(QWidget):
    """The widget a responsive card grid lives inside, which reports its
    own width changes.

    v10: column counts used to be derived from the PAGE's width minus a
    hand-tallied chrome constant, while the cards were actually laid out
    inside this host — whose width is the scroll VIEWPORT's and settles a
    layout pass later. Whenever the two disagreed (every frame of a live
    drag-resize, and on any page not yet shown) the grid was given a
    column count that did not fit the container, and cards were positioned
    past its right edge: measured at 974px window width, a 1719px-wide
    grid inside a 590px host.

    Driving the relayout from the host's OWN resizeEvent removes the
    disagreement by construction — the width used to choose the column
    count is, by definition, the width the cards are laid out in."""

    resized = Signal(int)   # new available content width

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        layout = self.layout()
        margins = layout.contentsMargins() if layout is not None else None
        chrome = (margins.left() + margins.right()) if margins else 0
        self.resized.emit(self.width() - chrome)


class ElidedCaption(QLabel):
    """A single-line caption that NEVER widens its parent.

    ClampedLabel solves the vertical version of this problem; this is the
    horizontal one, and it exists because of a regression measured while
    adding the v10.1 run-history pill: dropping a plain QLabel into the
    card footer took GlassCard.minimumSizeHint() from 184px to 337px once
    both it and the APPLIED chip were visible.

    That is the v9.1 density bug returning by another door. The footer was
    deliberately built so a card's minimum is the MAX of its rows and not
    their SUM — a plain QLabel breaks that, because QHBoxLayout adds every
    child's minimum width together, and the widest caption ("1y ago ·
    ~1.5h") therefore becomes a floor the responsive grid must honour on
    every card forever.

    Two mechanisms keep it honest:
      * a MINIMUM width of zero, so the layout is never obliged to find
        room for the text and the card's floor is unaffected, while the
        size policy stays Preferred so the caption is still granted its
        natural width whenever the row has room, and
      * elision to whatever width it actually receives, so a squeezed
        caption degrades to "1y ago…" rather than being clipped mid-glyph.

    The size policy is deliberately NOT Ignored. Ignored discards the
    sizeHint outright, which — next to the footer's trailing stretch —
    collapsed the caption to zero width and painted nothing at all, while
    still reporting isVisible() as True. That shipped past unit tests
    asserting on visibility and text; only a screenshot showed the cards
    were blank. test_history_pill_is_actually_painted now pins the width.

    The untruncated text always remains in the tooltip.
    """

    #: Default ceiling on the width a caption may ASK for, however long it
    #: gets. Tuned for the card footer this class was built for, where a
    #: run-history pill must never widen the responsive grid's unit.
    MAX_WIDTH = 120

    def __init__(self, parent: QWidget | None = None,
                 max_width: int | None = None,
                 elide: Qt.TextElideMode = Qt.TextElideMode.ElideRight):
        """`max_width` overrides MAX_WIDTH for one instance.

        The hero masthead's tagline is the reason it exists: that line
        genuinely wants ~255px on a wide window and only needs to elide
        when the window is squeezed toward its 980px minimum. Inheriting
        the card footer's 120px ceiling would have "fixed" the clipping by
        truncating the tagline permanently, at every window size — trading
        a bug at one width for a worse one at all of them.

        `elide` picks WHERE the ellipsis lands, and the default stays
        ElideRight because that is right for prose: a caption's meaning is
        front-loaded, so dropping the tail costs the least.

        It is exactly wrong for IDENTIFIERS, which is why the parameter
        exists. A Run-key name distinguishes itself from its neighbours at
        BOTH ends — "MicrosoftEdgeAutoLaunch_9F2A…" and
        "MicrosoftEdgeAutoLaunch_1C40…" are the same string under
        ElideRight — so the Startup Manager passes ElideMiddle and keeps
        the head and the tail, which together are what identify the entry.
        """
        super().__init__(parent)
        self._full = ""
        self._max_width = self.MAX_WIDTH if max_width is None else max_width
        self._elide = elide
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)

    def setFullText(self, text: str):
        self._full = text
        self._apply_elision()
        self.updateGeometry()

    def fullText(self) -> str:
        return self._full

    def sizeHint(self):            # noqa: N802 - Qt casing
        """Measured off the FULL text, never off what is currently painted.

        QLabel.sizeHint() reports the width of its current text, and our
        current text is the ELIDED string — so asking the base class makes
        the hint a function of the elision, and the elision a function of
        the width the hint won. That is a ratchet: the first squeeze elides
        the caption, the shrunken hint then asks for only the elided width,
        and the caption can never come back when the room does.

        Invisible on the card footer this class was written for (a run
        history pill is capped at 120px and sits under constant pressure),
        but immediately obvious on the masthead tagline, which stayed
        truncated at 1400px after one pass through 980px.
        """
        hint = super().sizeHint()
        if self._full:
            # +1 IS LOAD-BEARING, and it is not a fudge factor.
            #
            # This class measures with horizontalAdvance() but ELIDES with
            # elidedText(), and the two disagree by up to a pixel on the
            # trailing glyph — more readily once QSS letter-spacing is in
            # the font, because the spacing after the final character is
            # accumulated by one and rounded away by the other. Asking for
            # exactly the advance therefore wins a width that elidedText
            # then judges insufficient, so the caption elides at EVERY
            # window size and never renders in full.
            #
            # MEASURED, at the masthead's own 12px + 1px letter-spacing:
            #   "Enterprise-Grade Windows Orchestration" -> advance 255,
            #        elidedText(255) returns the full string.
            #   "Windows Orchestration Toolkit"          -> advance 191,
            #        elidedText(191) ELIDES; it needs 192.
            # Which side of the rounding a string lands on is a property of
            # its final glyph, so this was a latent trap that any change of
            # caption text could spring — and did.
            hint.setWidth(self.fontMetrics().horizontalAdvance(self._full) + 1)
        hint.setWidth(min(hint.width(), self._max_width))
        # Plus whatever the stylesheet reserves around the text. QLabel's
        # own hint measures the TEXT, and for every caller until v10.5 the
        # two were the same thing because none of them had padding — the
        # class was written for bare footer captions on a transparent
        # background. The Activity drawer's phase chip is the first one on
        # a PLATE (theme.stage_chip_qss: 8px each side plus a 1px border),
        # and without this the widget asks for exactly the text's width,
        # gets it, and then has 18px less room to draw in than it measured
        # against — so the line clipped mid-glyph instead of eliding.
        hint.setWidth(hint.width() + self._chrome())
        return hint

    def _chrome(self) -> int:
        """Horizontal space the style takes before the text starts.

        Read off contentsRect rather than parsed out of the stylesheet:
        padding, border and frame all land here, and Qt is the only thing
        that knows how a given style resolves them.
        """
        return max(0, self.width() - self.contentsRect().width())

    def minimumSizeHint(self):     # noqa: N802 - Qt casing
        """The whole point: a caption is decoration and may collapse to
        nothing rather than force a card wider."""
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def resizeEvent(self, event):  # noqa: N802 - Qt casing
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self):
        if not self._full:
            super().setText("")
            return
        # THE CONTENTS RECT, NOT width(). They differ by exactly the
        # padding and border the stylesheet reserves, and eliding against
        # the outer width means measuring the text against room the text is
        # not allowed to use: the string "fits", Qt draws it into a
        # narrower rect, and the tail is CLIPPED rather than elided —
        # the one failure mode this class exists to prevent, reintroduced
        # by putting it on a plate.
        available = self.contentsRect().width()
        if available <= 0:
            super().setText(self._full)
            return
        super().setText(
            self.fontMetrics().elidedText(self._full, self._elide, available))


class ClampedLabel(QLabel):
    """A word-wrapped label with a HARD line budget.

    Why this exists: a plain wordWrap QLabel grows without limit, but
    GlassCard caps its own height (setMaximumHeight). The two disagreed
    silently — measured across the real catalog at a 3-column width, 14
    cards had their description cut off mid-sentence and 5 also lost part
    of their title; the worst (PATH Doctor) lost 88px, more than half its
    copy. Nothing warned; the text was simply painted outside the card's
    clip and vanished.

    This label instead lays the text out itself (QTextLayout, the same
    engine QLabel uses), keeps at most `max_lines` of it, elides the last
    kept line with an ellipsis, and puts the FULL text in the tooltip so
    nothing is ever unreachable. Its height is pinned to exactly
    max_lines * lineSpacing, so a card's height is now a deterministic
    function of its line budget rather than of how long someone's
    description happened to be.
    """

    def __init__(self, text: str = "", max_lines: int = 2,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWordWrap(True)
        self._max_lines = max(1, max_lines)
        self._full = text
        self._elided = False
        self._reflowing = False
        #: The (text, width, font, budget) the CURRENT painted string was
        #: laid out for, or None before the first successful reflow. See
        #: _layout_key — this is what makes a theme switch cheap.
        self._reflow_key: tuple | None = None
        super().setText(text)

    # -- public API -------------------------------------------
    def setFullText(self, text: str):
        self._full = text
        self._reflow()

    def fullText(self) -> str:
        return self._full

    # -- layout -----------------------------------------------
    def _pin_height(self, lines: int | None = None):
        """Height = exactly the number of lines actually used, capped at
        the budget.

        The first cut of this reserved max_lines unconditionally, which
        made every short one-line blurb claim three lines of vertical
        space — enough to overflow the Welcome page's shorter Quick Action
        cards. The cap is a CEILING, not a quota: a 1-line description
        should occupy 1 line and let the card breathe."""
        used = self._max_lines if lines is None else max(1, min(lines, self._max_lines))
        target = QFontMetrics(self.font()).lineSpacing() * used
        if self.height() != target or self.minimumHeight() != target:
            self.setFixedHeight(target)

    def changeEvent(self, e):
        # Every label in this app takes its font-size from QSS, and QSS is
        # applied during POLISH — long after setStyleSheet() returns. Pinning
        # the height inside setStyleSheet therefore measured the widget's
        # pre-QSS default font and produced a budget for the wrong type size.
        # FontChange is the event Qt emits once the effective font (QSS
        # included) has actually resolved, so that is where the budget is
        # computed. StyleChange covers a live theme re-skin.
        super().changeEvent(e)
        if e.type() not in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            return
        # ...but a StyleChange is NOT evidence that anything about the text
        # layout moved, and treating it as such is what made a theme switch
        # slow. setStyleSheet() on any ancestor sends StyleChange to every
        # descendant, and _apply_theme sets one on the shell, the content
        # frame, the page, and then on each of ~276 cards — so a single
        # label received the event four or five times per toggle and ran a
        # full QTextLayout for each. Measured on the real window: ~2,700
        # reflows per switch, 35% of the whole cost, all of them producing
        # a string byte-identical to the one already painted, because the
        # two themes share one type scale and change only colour.
        #
        # The key is the COMPLETE set of inputs _reflow_impl reads, so a
        # match means the output is provably unchanged — this is a skip, not
        # a heuristic. A theme that did change a font size would change
        # font().toString() and reflow exactly as before.
        if self._reflow_key is not None and self._layout_key() == self._reflow_key:
            return
        self._pin_height()
        self._reflow()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reflow()

    def _layout_key(self) -> tuple:
        """Everything _reflow_impl's output depends on, and nothing else."""
        return (self._full, self.width() - self.margin() * 2,
                self.font().toString(), self._max_lines)

    def _reflow(self):
        width = self.width() - self.margin() * 2
        if width <= 0 or not self._full:
            return
        if self._reflowing:      # setFixedHeight below re-enters via resizeEvent
            return
        key = self._layout_key()
        if key == self._reflow_key:
            return
        self._reflowing = True
        try:
            self._reflow_impl(width)
            # AFTER the impl, never before: _reflow_impl calls _pin_height,
            # which can re-enter through resizeEvent, and a key recorded up
            # front would let that re-entry believe the new layout was
            # already applied.
            self._reflow_key = key
        finally:
            self._reflowing = False

    def _reflow_impl(self, width: int):
        layout = QTextLayout(self._full, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        starts: list[int] = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            starts.append(line.textStart())
        layout.endLayout()

        # height tracks the lines actually used, capped at the budget
        self._pin_height(len(starts))

        if len(starts) <= self._max_lines:
            if super().text() != self._full:
                super().setText(self._full)
            self._elided = False
            self.setToolTip("")
            return

        # Keep the whole prefix verbatim (so Qt re-wraps it identically),
        # then elide only what would have spilled past the budget.
        cut = starts[self._max_lines - 1]
        fm = QFontMetrics(self.font())
        tail = fm.elidedText(self._full[cut:], Qt.TextElideMode.ElideRight, width)
        super().setText(self._full[:cut] + tail)
        self._elided = True
        self.setToolTip(self._full)


class StatusChip(QLabel):
    """A card's verdict badge (APPLIED / MODIFIED / ACTION DUE / DEFAULT) —
    a frosted pill rather than a filled rectangle with rounded ends.

    Everything about its PLATE is still theme.state_chip_qss, and that is
    deliberate: the plate is the surface the 9px text is solved against,
    and the contrast table in that function is the reason the badge is
    legible on the worst card it can land on. Nothing here touches it.

    What this adds is the one pixel QSS cannot reach — a lit rim along the
    top edge, painted over the chip's own border. It is the same cue the
    cards use two scales up (theme.sheen_alphas) and the icon wells use one
    scale up (IconPlaque), so a badge, a plaque and a card all catch light
    from the same direction. Contrast-neutral by construction: the rim has
    faded out 1.5px in, and the text starts CHIP_PAD_V + 1 px down. See
    theme.chip_sheen.

    Static, like everything else in this file's steady state: one cached
    perimeter blit on a repaint the label was doing anyway.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self._sheen: tuple[int, float] | None = None

    def set_sheen(self, t: dict):
        self._sheen = TH.chip_sheen(t)
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)       # the QSS plate, border and text
        if self._sheen is None:
            return
        peak, depth = self._sheen
        p = QPainter(self)
        paint_top_sheen(p, self.rect(), TH.RADIUS["chip"], strength=1.0,
                        peak=peak, depth=depth)
        p.end()


class IconPlaque(QLabel):
    """A card's icon well — ONE NEUTRAL SURFACE for a glyph to sit on.

    THE SHORT HISTORY, because this class spent three versions being
    something else. Through v12 it was a plain QLabel wearing
    icon_plaque_qss: a flat accent gradient inside a flat 1px accent
    border. v13 handed it to a painter so it could carry an ambient halo
    outside the well, a second hairline inside the first and a lit top rim
    — the material a Linear or Raycast icon chip is built from, and three
    things QSS cannot put on a QLabel.

    v10.6 deleted all of it. That material was solved for a grid whose
    defining cue was COLOUR, and once the palette collapsed to a single
    interactive accent (see the note on theme._DARK["module"]) it read as
    four tinted rings around a glyph. What is left is one rounded rect in
    theme's `plaque_well` — a low-alpha NEUTRAL, lightening on obsidian and
    darkening on porcelain — with the colour where it is not repeated: on
    the glyph.

    THE SAME WELL AT EVERY SCALE. NavButton paints this exact token for the
    sidebar entry that opens the card, so a module is one object seen twice
    rather than two things drawn by two pieces of code (the reason
    theme.PLAQUE_SIZE exists at all). The glyph's contrast against it is
    swept on every surface it can land on — card, rail, and a selected
    rail entry, whose well is the same neutral lifted by
    NavButton._SELECTED_LIFT — by test_elevation's glyph-floor test.

    STATIC. No timer, no animation, no QGraphicsEffect: one fill, repainted
    only when the card repaints anyway. The glyph is still drawn by QLabel
    itself, so the hover "pop" (GlassCard._sync_icon_scale, a setFont on a
    handful of frames) keeps working untouched.
    """

    #: THE WIDGET IS THE WELL. Through v10.5 this reserved 3px on each
    #: side for an ambient halo to bleed into, so a 42px widget painted a
    #: 36px well. The halo is gone with the accent wash that justified it,
    #: and with it the gap between "the plaque" and "the thing you can
    #: measure" — a leading icon is now exactly PLAQUE_SIZE square,
    #: everywhere, which is what made it worth standardising.
    _PAD = 0

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self._well = QColor(255, 255, 255, 10)

    def apply_theme(self, t: dict, accent: str):
        self.setStyleSheet(TH.icon_plaque_qss(t, accent))
        self._well = TH.to_qcolor(t["plaque_well"])
        self.update()

    def paintEvent(self, e):
        """One rounded rect. That is the whole plaque now.

        It used to be four passes — an ambient halo walking outward in
        concentric strokes, an accent-gradient wash, an outer hairline on
        the well's edge and a lit inner rim — every one of them tinted in
        the module's own colour. That material was solved for a card grid
        whose defining cue was colour; on a canvas whose defining cue is
        that there is nothing on it, it reads as four rings around a glyph.

        The glyph keeps the accent (icon_plaque_qss sets its colour). The
        well is a neutral surface for it to sit on.
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._well)
        p.drawRoundedRect(QRectF(self.rect()),
                          TH.PLAQUE_RADIUS, TH.PLAQUE_RADIUS)
        p.end()
        # AFTER the well, never before: QLabel draws the glyph itself, and
        # painting the plate on top of it would hide the thing it is a
        # plate for.
        super().paintEvent(e)


class GlassCard(QFrame):
    clicked = Signal()
    # Arrow-key traversal request: "left" | "right" | "up" | "down". The
    # card knows a key was pressed but not where its neighbours are — the
    # page that owns the grid resolves that (see main._focus_neighbour).
    navigate = Signal(str)

    _ICON_BASE_PX = TH.ICON["plaque"]
    _ICON_GROW_PX = 2   # subtle hover "pop" — see _sync_icon_scale()
    #: Icon plaque FOOTPRINT — the widget, not the well. IconPlaque
    #: reserves _PAD on each side for its halo to bleed into, so the well
    #: it actually paints measures theme.PLAQUE_SIZE, which is what the
    #: sidebar entry for the same module paints too.
    _PLAQUE = TH.PLAQUE_SIZE + 2 * IconPlaque._PAD

    # Height envelope, DERIVED from the card's anatomy rather than guessed.
    # With the v11 SYMMETRIC padding (16 on all four sides — see the layout
    # below) the arithmetic is:
    #   padding 16+16  +  plaque row 42  +  gap 8  +  desc 3x15  = 127
    #   ... plus the optional meta footer (gap 8 + pill 20)       = 155
    # Because ClampedLabel caps each block at an exact line count, 156 is a
    # ceiling the content genuinely cannot exceed — which is what makes a
    # maximum safe at all. (Pre-v10 the cap was 146 and content simply
    # overflowed it invisibly; the minimum was 112, itself below the 119 a
    # three-line description needed, so the minimum could clip too.)
    #
    # Both numbers move with the padding: the whole point of deriving them
    # is that a padding change can't silently start clipping content.
    #
    # v12 TURNS THE ENVELOPE INTO A LADDER, for two reasons found by
    # measuring the running app rather than by reading this comment.
    #
    # First, the floor was not being applied at all. minimumSizeHint()
    # below has clamped to CARD_MIN_H since v10, but a card's rendered
    # height does not come from its minimum: CategoryPage._relayout gives
    # content rows ZERO stretch (so a short page anchors to the top instead
    # of floating in the middle), and an unstretched QGridLayout row takes
    # its height from sizeHint(), which GlassCard did not override. Measured
    # across all 41 cards, 26 rendered BELOW the documented 128px floor and
    # three at 101px. The floor was real in the source and fictional on
    # screen.
    #
    # Second, even honoured, a free-floating height produced seven distinct
    # card heights across four modules — cards that match inside a band and
    # visibly disagree across bands, which is precisely the "almost
    # aligned" quality the SPACE scale was introduced to remove. Heights
    # now snap UP to one of three steps, so a page reads as two or three
    # deliberate sizes instead of a continuum of near-misses.
    #
    # The steps are the anatomy's own breakpoints, not arbitrary thirds:
    # 128 is the floor above, 156 the derived ceiling, and 142 the height
    # of a card carrying a full description without the meta footer.
    CARD_STEPS = (128, 142, 156)
    CARD_MIN_H = CARD_STEPS[0]
    CARD_MAX_H = CARD_STEPS[-1]

    def __init__(self, item: dict, accent: str, t: dict,
                 featured: bool = False, locked: bool = False):
        super().__init__()
        self.item = item
        # v10: `accent` is a module KEY ("software") for category/dashboard
        # cards, or a literal hex when a dialog passes t["accent"] directly.
        # Both are stored unresolved and turned into a real colour inside
        # apply_theme() via theme.resolve_accent, so a card built under one
        # theme repaints correctly under the other.
        self._accent_key = accent
        self._accent = TH.resolve_accent(t, accent)
        self._danger = bool(item.get("danger"))
        self._featured = featured
        # v9.4: `locked` marks an admin-gated action shown on a non-elevated
        # Pulse — a small lock glyph in the head signals "needs Administrator"
        # up front (the click then opens the inline elevate prompt).
        self._locked = locked
        # verdict string ("applied" / "mixed" / "default") or None — see
        # set_applied; legacy booleans are normalised there.
        self._applied: str | None = None
        self._tokens = t
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # v10 ACCESSIBILITY: cards were QFrames with mouse handlers only —
        # no focus policy, no key handling — so the entire operation grid,
        # the app's primary surface, was unreachable by keyboard. Tab
        # stopped at the sidebar. StrongFocus puts every card in the tab
        # order; keyPressEvent below adds Enter/Space activation and arrow
        # traversal, and paintEvent draws a real focus ring.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(item.get("title", ""))
        self.setAccessibleDescription(item.get("desc", ""))
        # v8 proportion fix: a min AND a max so cards never balloon. The
        # equal-row-stretch grid (main.CategoryPage._relayout) still fills the
        # canvas, but a capped card can't grow into a tall, empty slab — it
        # settles at a natural height and the leftover space becomes balanced
        # inter-row breathing room, so a 4- or 5-card page reads evenly
        # distributed instead of either top-anchored-with-a-void or stretched.
        #
        # v8.1: featured and standard cards now share the SAME height bounds.
        # Giving the hero card a taller envelope made its grid row outgrow the
        # rows below it (and the rows of a hub-less category like System
        # Optimization), so transitioning between modules felt subtly off. The
        # featured card keeps its distinction through its squircle body +
        # Aurora edge, not extra size — every card in every section now shares
        # one height envelope, so rows lock to a single rhythm everywhere.
        # v9.1 density pass: a tighter height envelope (was 140/178) so cards
        # stop ballooning into empty slabs — content sits closer together and
        # reads denser, and the equal-row-stretch grid distributes the saved
        # space as clean breathing room between rows.
        # Only a MAXIMUM is set explicitly. An explicit setMinimumHeight
        # OVERRIDES minimumSizeHint(), so a fixed floor below what a
        # particular card's content needs (e.g. 120 on a footer card that
        # needs 147) silently let the layout squeeze it and clip the
        # content again. The floor is applied in minimumSizeHint() instead,
        # where it can be combined with — never override — the layout's own
        # requirement.
        self.setMaximumHeight(self.CARD_MAX_H)
        self.setProperty("running", False)

        glow_color = t["err"] if self._danger else self._accent
        self._glow = GlowController(self, glow_color)
        self._ripple = RippleController(self)

        # "Weighted" press feedback: a painted dark tint that ramps in fast
        # and releases softly. Painted in paintEvent — zero QSS churn, zero
        # QGraphicsEffect, per the animations.py doctrine.
        self._press_tint = 0.0
        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(90)
        self._press_anim.setEasingCurve(EASE_OUT)
        self._press_anim.valueChanged.connect(self._on_press_frame)

        # v10 CARD ANATOMY — a header row (plaque + title) above a
        # FULL-WIDTH description, replacing the old two-column "plaque to
        # the left of everything" arrangement.
        #
        # This is a measurement-driven change, not a restyle. In the old
        # layout the description shared a column with the title, so at the
        # 3-column grid width it was only ~256px wide — narrow enough that a
        # 48-character sentence ("Force the dark theme across Windows and
        # all apps.") already needed FOUR lines and got truncated. Dropping
        # the description onto its own row gives it the card's full inner
        # width (~312px at the same grid width, +22%), which is what finally
        # lets ordinary copy render complete.
        lay = QVBoxLayout(self)
        # v11: TRULY symmetric padding — one scale step on all four sides.
        # v10 already fixed the accidental 15/13/16/13, but it landed on
        # 16/12/16/12, so the horizontal and vertical insets still differed
        # and the content block sat in a subtly wider-than-tall well. At
        # card scale that asymmetry is exactly what reads as "boxy": the
        # glyph and title crowd the top edge while the sides breathe. Equal
        # insets let the content sit centred in its own surface, which is
        # the single cheapest thing that makes a card look considered.
        lay.setContentsMargins(TH.SPACE["lg"], TH.SPACE["lg"],
                               TH.SPACE["lg"], TH.SPACE["lg"])
        lay.setSpacing(TH.SPACE["sm"])

        # -- icon plaque (v7) — a Fluent glyph in an accent-tinted well ----
        char, self._glyph_fluent = (
            TH.glyph(item["glyph"]) if item.get("glyph")
            else (item.get("icon", "•"), False))
        self._icon = IconPlaque(char)
        self._icon.setFixedSize(self._PLAQUE, self._PLAQUE)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Font is managed as a QFont object, not inline QSS: hover "pop" is
        # a handful of setFont() calls per hover-in (one per distinct integer
        # pixel size), never a per-frame setStyleSheet() rebuild — the exact
        # anti-pattern the animations.py doctrine forbids.
        base_font = TH.icon_font(self._ICON_BASE_PX) if self._glyph_fluent else QFont()
        self._icon_font = base_font if base_font is not None else QFont()
        self._icon_font.setPixelSize(self._ICON_BASE_PX)
        self._icon.setFont(self._icon_font)
        self._icon_px = self._ICON_BASE_PX

        # -- header row: plaque + title (+ chevron / lock) -----------------
        head = QHBoxLayout()
        head.setSpacing(TH.SPACE["md"])
        head.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        # v10 line budget: title 2 lines, description 3. Both are
        # ClampedLabels, so a long string elides with its full text in the
        # tooltip instead of being painted outside the card.
        self._title = ClampedLabel(item["title"], max_lines=2)
        head.addWidget(self._title, 1)
        # v9.1 density fix: the note badge ('Windows 11 only') used to sit on
        # the TITLE's row, so a card's minimum width became plaque + title +
        # badge (~416px) — which forced the responsive grid to overflow once
        # cards were narrowed for a denser 3-column layout. Moving the badge
        # into the footer row means the card minimum is the MAX of its rows,
        # not their SUM, so dense columns fit cleanly — and a small pill in
        # the bottom-right reads more premium than a chip crowding the title.
        self._badge: QLabel | None = None
        if item.get("note"):
            self._badge = QLabel(item["note"])
        # Drill-in chevron — shown only for cards that open a further screen
        # (hubs / selectors), i.e. exactly the cards that have a meta footer.
        self._meta_texts = _derive_card_meta(item)
        self._chevron: QLabel | None = None
        if self._meta_texts:
            self._chevron = QLabel(TH.glyph("chevron")[0])
            cf = TH.icon_font(TH.ICON["inline"]) if TH.glyph("chevron")[1] else QFont()
            if cf is not None:
                cf.setPixelSize(TH.ICON["inline"])
                self._chevron.setFont(cf)
            head.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignVCenter)
        # admin-gated lock indicator (v9.4): a quiet warn-tinted lock glyph
        # pinned to the head's right edge when this card needs elevation the
        # current session doesn't have.
        self._lock: QLabel | None = None
        if self._locked:
            lock_char, lock_fluent = TH.glyph("lock")
            self._lock = QLabel(lock_char)
            lf = TH.icon_font(TH.ICON["micro"]) if lock_fluent else QFont()
            if lf is not None:
                lf.setPixelSize(TH.ICON["micro"])
                self._lock.setFont(lf)
            self._lock.setToolTip(
                "Needs Administrator — clicking will offer to relaunch Pulse elevated.")
            head.addWidget(self._lock, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(head)

        # -- description: its own FULL-WIDTH row (the v10 change) ----------
        # A uniform 3-line budget. Combined with the full card width this
        # lets the tightened catalog copy render complete on every card at
        # every column count, with elision left as a pure safety net.
        self._desc = ClampedLabel(item["desc"], max_lines=3)
        lay.addWidget(self._desc)
        lay.addStretch()

        # -- meta footer (v7) — count/hint pills fill the card with signal,
        #    plus the relocated note badge pinned bottom-right (v9.1) --------
        # v10: the footer now ALWAYS exists, because the applied-state chip
        # can appear on any card once the backend probe reports on it. It
        # stays zero-height until something needs it (the chip and badge
        # both start hidden), so a plain action card is unchanged visually.
        self._meta_pills: list[QLabel] = []
        self._applied_chip = StatusChip("APPLIED")
        self._applied_chip.hide()
        # v10.1 run history ("Ran 3d ago · ~2m"). Starts hidden and stays
        # hidden until this task has actually been run, so a fresh install
        # looks exactly as it did before rather than showing a row of
        # empty placeholders.
        self._history_pill = ElidedCaption()
        self._history_pill.hide()
        foot = QHBoxLayout()
        foot.setSpacing(TH.SPACE["sm"])
        for text in self._meta_texts:
            pill = QLabel(text)
            self._meta_pills.append(pill)
            foot.addWidget(pill)
        foot.addWidget(self._applied_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        foot.addWidget(self._history_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        foot.addStretch()
        if self._badge is not None:
            foot.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(foot)

        self.apply_theme(t)
        # Seed the ladder step before the card is ever laid out. Without
        # this the minimum is always one layout pass behind: the grid
        # measures the card, THEN resizeEvent sets the minimum, and nothing
        # re-measures unless something else happens to invalidate the
        # layout. The app hid that (its deferred _remeasure_rows pass
        # supplies the second measurement) but it left the card's height
        # dependent on the order of passes around it, which is not a
        # property worth relying on.
        self._sync_height_step()

    # -- ambient occlusion ------------------------------------
    def apply_theme(self, t: dict):
        # re-resolve first: the module palette differs per theme (v10)
        self._accent = TH.resolve_accent(t, self._accent_key)
        self.setStyleSheet(TH.card_qss(t, self._accent, self._danger, self._featured))
        plaque_accent = t["err"] if self._danger else self._accent
        self._icon.apply_theme(t, plaque_accent)
        self._title.setStyleSheet(TH.label_qss(t, "card"))
        self._desc.setStyleSheet(TH.label_qss(t, "desc"))
        if self._badge is not None:
            self._badge.setStyleSheet(TH.badge_qss(t))
        if self._chevron is not None:
            self._chevron.setStyleSheet(TH.card_chevron_qss(t, self._accent))
        if self._lock is not None:
            self._lock.setStyleSheet(
                f"color: {t['warn']}; background: transparent; border: none;")
        for i, pill in enumerate(self._meta_pills):
            # the lead pill on the featured card carries the accent tint
            tint = plaque_accent if (self._featured and i == 0) else ""
            pill.setStyleSheet(TH.card_meta_pill_qss(t, tint))
        self._tokens = t
        self._applied_chip.setStyleSheet(
            TH.state_chip_qss(t, self._applied or "applied"))
        self._applied_chip.set_sheen(t)
        self._history_pill.setStyleSheet(TH.card_history_pill_qss(t))
        self._glow.set_accent(plaque_accent)
        self._glow.set_alphas(*TH.glow_alphas(t))
        # painted-material state, read in paintEvent
        self._bevel = TH.bevel_alphas(t)
        self._shadow = TH.shadow_alphas(t)
        self._sheen = TH.sheen_alphas(t)
        self._feat_base = TH.to_qcolor(t["card_hi"])
        self._aur1 = QColor(t["accent"])
        self._aur2 = QColor(t["accent2"])
        self._aur3 = QColor(t["accent3"])

    #: Badge text + tooltip per probe verdict. None (unknown) renders
    #: nothing — a card with no badge means "we're not claiming anything",
    #: which is honest, whereas a wrong badge would actively mislead.
    _STATE_BADGES = {
        "applied": ("APPLIED",
                    "This setting is currently active on your system."),
        "mixed": ("MODIFIED",
                  "This setting is partially applied — some of its values "
                  "match, some don't. It may have been changed outside "
                  "Pulse. Click the card to re-apply or revert it."),
        "default": ("DEFAULT",
                    "This setting is at its Windows default. Click the "
                    "card to apply the tweak."),
        # ROUTINE tasks only (menu_structure's `recurring` key). These have
        # no durable state to probe, so they report timing instead: overdue
        # or never run reads ACTION DUE, and the card's own "Ran 3d ago"
        # caption carries the detail.
        "due": ("ACTION DUE",
                "This routine hasn't been run recently. Running it "
                "periodically keeps the system healthy."),
    }

    def set_applied(self, verdict: str | bool | None):
        """Reflect the backend's read-only state probe (v1.0 tri-state).

        `verdict` is "applied" / "mixed" / "default" / None — legacy
        booleans normalise (True→applied, False→None) so pre-v1.0 callers
        and stored data keep meaning what they meant. main._on_tweak_state
        decides WHICH cards get a DEFAULT badge (only the two-way toggle
        set) by passing None for everything else, so this widget stays a
        pure renderer with no policy of its own."""
        if verdict is True:
            verdict = "applied"
        elif verdict is False:
            verdict = None
        self._applied = verdict
        badge = self._STATE_BADGES.get(verdict)
        self._applied_chip.setVisible(badge is not None)
        if badge is not None:
            self._applied_chip.setText(badge[0])
            self._applied_chip.setToolTip(badge[1])
            self._applied_chip.setStyleSheet(
                TH.state_chip_qss(self._tokens, verdict))
        else:
            self._applied_chip.setToolTip("")

    def state(self) -> str:
        """The card's current badge state ("applied" / "mixed" / "default"
        / "due" / ""), read by CategoryPage's status filter so the filter
        and the badge can never disagree about what a card is."""
        return self._applied or ""

    def set_history(self, entry: dict | None):
        """Show this task's last-run caption, or nothing at all.

        Same honesty rule as set_applied(): with no record, the card says
        nothing rather than guessing or showing a "never run" placeholder
        — a card the user ran outside Pulse, or before this feature
        existed, genuinely has no history for us to report.
        """
        text, tooltip = format_history_caption(entry)
        self._history_pill.setFullText(text)
        self._history_pill.setToolTip(tooltip)
        self._history_pill.setVisible(bool(text))

    @classmethod
    def _snap_height(cls, natural: int) -> int:
        """Round a natural content height UP to the next ladder step.

        Upward only, and that direction is the whole safety argument: a
        step can add air to a short card but can never take a pixel away
        from one whose content needs it. A card taller than the last step
        stays at the last step, which is safe because ClampedLabel caps
        every block at an exact line count — see the anatomy note above,
        where 155 is the most the content can add up to."""
        for step in cls.CARD_STEPS:
            if natural <= step:
                return step
        return cls.CARD_STEPS[-1]

    def _sync_height_step(self):
        """Pin this card's minimum height to its ladder step.

        Finding the right lever here took measuring, because the two
        obvious ones do nothing. A card's description wraps, so the card
        reports hasHeightForWidth() == True, and for such an item
        QGridLayout takes the row height from QWidgetItem::heightForWidth
        rather than from sizeHint() or minimumSizeHint() — which is why
        CARD_MIN_H sat in minimumSizeHint() for two versions while 26 of
        41 cards rendered under it, three at 101px. Overriding the card's
        OWN heightForWidth does not help either: QWidgetItem asks the
        widget's LAYOUT (`if (wid->layout()) hfw = wid->layout()->
        totalHeightForWidth(w)`) and never calls the widget's method at
        all when a layout is present, as this one always is.

        What QWidgetItem::heightForWidth does honour is the widget's
        explicit minimumHeight, which it clamps its answer up to. So that
        is the lever, and it is set here from the card's OWN natural
        content height at its CURRENT width — never from a constant. That
        distinction is the whole safety argument, and it is why the
        warning in minimumSizeHint() about setMinimumHeight does not apply:
        the defect that warning describes was a FIXED 120px floor sitting
        below what some cards' content needed, so the layout squeezed and
        clipped them. A value derived per card, per width, and rounded
        only UPWARD cannot be below its own content.
        """
        natural = QFrame.heightForWidth(self, self.width())
        if natural < 0:
            return
        step = self._snap_height(natural)
        if self.minimumHeight() != step:
            self.setMinimumHeight(step)

    def resizeEvent(self, event):  # noqa: N802 - Qt casing
        # Re-derive on every width change: a narrower column wraps the
        # description onto more lines, which can legitimately move a card
        # up a step. Guarded by the equality check in _sync_height_step, so
        # the setMinimumHeight -> relayout -> resizeEvent path settles
        # after one pass instead of oscillating.
        super().resizeEvent(event)
        self._sync_height_step()

    def sizeHint(self):            # noqa: N802 - Qt casing
        """Snapped for consistency with the step above, so a caller that
        asks for the hint directly (a dialog embedding a card outside a
        grid, say) gets the same ladder the grid renders."""
        hint = super().sizeHint()
        hint.setHeight(self._snap_height(hint.height()))
        return hint

    def minimumSizeHint(self):     # noqa: N802 - Qt casing
        """The card's real floor: whatever its content needs, but never
        squatter than CARD_MIN_H. Combining here (rather than via
        setMinimumHeight) means the aesthetic floor can never win over a
        content requirement — it can only raise a short card, never crush
        a tall one.

        Deliberately NOT snapped to the ladder. The minimum is what the
        layout may squeeze a card to when the window is genuinely too
        short; pinning it to the rendered step would turn a rhythm
        preference into a hard constraint and force a scrollbar on a
        window that could otherwise have fitted."""
        hint = super().minimumSizeHint()
        hint.setHeight(max(hint.height(), self.CARD_MIN_H))
        return hint

    # -- state ------------------------------------------------
    def set_running(self, on: bool):
        self.setProperty("running", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def flash(self, kind: str, duration_ms: int = 1400):
        """Transient 'ok' / 'err' verdict tint after a task ends. Same
        dynamic-property mechanic as the running state; the clearing
        timer is bound to this widget as receiver, so a card destroyed
        mid-flash is never touched."""
        self.setProperty("flash", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        QTimer.singleShot(duration_ms, self, self._clear_flash)

    def _clear_flash(self):
        self.setProperty("flash", "")
        self.style().unpolish(self)
        self.style().polish(self)

    # -- interaction / painting --------------------------------
    def _on_press_frame(self, value: float):
        self._press_tint = float(value)
        self.update()

    def _ramp_press(self, target: float):
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_tint)
        self._press_anim.setEndValue(target)
        self._press_anim.start()

    _NAV_KEYS = {
        Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
        Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
    }

    def keyPressEvent(self, e):
        key = e.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            # Same feedback a click gets, so activating from the keyboard
            # feels like the same action rather than a silent shortcut.
            self._ramp_press(1.0)
            self._ripple.trigger(QPointF(self.rect().center()))
            QTimer.singleShot(90, lambda: self._ramp_press(0.0))
            self.clicked.emit()
            return
        direction = self._NAV_KEYS.get(key)
        if direction is not None:
            self.navigate.emit(direction)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        # Keyboard focus lights the same glow the pointer does, so the two
        # input methods produce one consistent "this is active" state.
        self._glow._ramp_to(1.0)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if not self.underMouse():
            self._glow._ramp_to(0.0)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._ramp_press(1.0)
            self._ripple.trigger(e.position())
        super().mousePressEvent(e)

    def leaveEvent(self, e):
        self._ramp_press(0.0)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        self._ramp_press(0.0)
        if (e.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(e.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def _sync_icon_scale(self):
        """Subtle icon 'pop' tied to the existing hover glow intensity —
        no new animation, just reads GlowController's already-running one.
        Guarded so setFont() only fires when the rounded size changes
        (a handful of times per hover ramp, not every frame)."""
        grown = round(self._ICON_BASE_PX + self._ICON_GROW_PX * self._glow.intensity)
        if grown != self._icon_px:
            self._icon_px = grown
            self._icon_font.setPixelSize(grown)
            self._icon.setFont(self._icon_font)

    def _paint_featured(self, p: QPainter):
        """The hero card's fully-painted material: a squircle (continuous-
        corner) glass surface on the top elevation tier, a hover-reactive
        accent wash, and the signature Aurora lit edge.

        A featured card owns its whole background, which means card_qss
        draws nothing for it in ANY state — so the running / flash verdict
        tints have to be painted here or they simply do not appear. That
        was free while the hero could only ever be a hub container (hubs
        open a dialog; they never run a task). The v1.0 RC Software
        Catalog card IS the hero and DOES run a task, so the state is
        painted rather than dropped: without this, clicking the app's most
        prominent card would be the one click in Pulse that gives no
        visual acknowledgement it started or how it ended.
        """
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = squircle_path(self.rect().adjusted(1, 1, -1, -1),
                             TH.RADIUS["panel"])
        # ONE FLAT PLATE on the card_hi tier. This used to be the painted
        # twin of card_qss's glass_fill — a white sheen falling into the
        # base over the top 16% — and it goes for the reason every other
        # one went (see the surface rule in theme.py, above `blend`): the
        # hero is the largest surface on the page, so the smear it carried
        # was the most visible instance of the effect. Its elevation comes
        # from the aurora edge and the contact shadow below, both of which
        # live on the perimeter.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._feat_base)
        p.drawPath(path)
        # hover wash — reuses the already-running glow intensity, no new anim
        if self._glow.intensity > 0.01:
            wash = QColor(self._glow.color)
            wash.setAlphaF(0.07 * self._glow.intensity)
            p.setBrush(wash)
            p.drawPath(path)
        # verdict / busy state, at the same weight card_qss uses for a
        # plain card so the two read as one system
        state = self._featured_state_color()
        if state is not None:
            p.setBrush(state)
            p.drawPath(path)
            pen = QPen(QColor(state.red(), state.green(), state.blue()), 1.6)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            return          # the state edge REPLACES the aurora, not stacks on it
        paint_aurora_edge(p, path, self._aur1, self._aur2, self._aur3,
                          width=1.6, intensity=0.95)

    def _featured_state_color(self) -> QColor | None:
        """The running/flash wash for a featured card, or None when idle.
        Reads the same dynamic properties card_qss's selectors do, so the
        hero can never disagree with an ordinary card about its state."""
        tokens = self._tokens or {}
        if self.property("flash") == "ok":
            key = "ok"
        elif self.property("flash") == "err":
            key = "err"
        elif self.property("running"):
            key = "accent"
        else:
            return None
        color = QColor(tokens.get(key, "#7d9bff"))
        color.setAlphaF(TH.STATE_TINT)
        return color

    def paintEvent(self, e):
        super().paintEvent(e)  # QSS glass background/border first (transparent if featured)
        self._sync_icon_scale()
        p = QPainter(self)
        radius = TH.RADIUS["card"]
        # How far this card has risen toward the pointer, on the quantized
        # elevation ladder — see TH.hover_lift. Read once per paint so the
        # shadow, the sheen and the accent hairline below can never
        # disagree about how lifted the card currently is.
        lift = TH.hover_lift(self._glow.intensity)
        if self._featured:
            self._paint_featured(p)
        else:
            # Shadow FIRST, under the edge treatments: it is the surface's
            # cast, so a bevel highlight or sheen must sit on top of it.
            #
            # Both deepen with `lift`: a hovered card casts harder and
            # catches more light along its top edge, which is the same pair
            # of cues that separates elevation tiers at rest. The card does
            # not move a pixel — see the note on HOVER_LIFT_STEPS.
            shadow_alpha, shadow_spread = self._shadow
            paint_drop_shadow(
                p, self.rect(), radius,
                shadow_alpha * (1.0 + (TH.HOVER_LIFT_SHADOW - 1.0) * lift),
                shadow_spread)
            paint_bevel_frame(p, self.rect(), radius, *self._bevel)
            # The resting strength is a THEME value, not a shared 0.55:
            # light spends nearly its whole budget at rest to erase the
            # top hairline, dark spends it gradually. See
            # theme.sheen_alphas. Clamped because light rests at 0.95 and
            # the hover lift would otherwise ask for 1.25.
            sheen_peak, sheen_depth, sheen_rest = self._sheen
            paint_top_sheen(p, self.rect(), radius,
                            strength=min(1.0, sheen_rest
                                         + TH.HOVER_LIFT_SHEEN * lift),
                            peak=sheen_peak, depth=sheen_depth)
        if self._press_tint > 0.01:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(40 * self._press_tint)))
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1),
                              radius - 1, radius - 1)
        paint_ripple_frame(p, self.rect(), radius, self._glow.color,
                           self._ripple.progress, self._ripple.origin)
        # The even accent perimeter goes UNDER the cursor sweep: the
        # hairline says "this whole card", the sweep puts the bright spot
        # where the pointer is. Skipped on the featured card, which already
        # carries the Aurora lit edge and would end up wearing two borders.
        if not self._featured:
            paint_accent_hairline(p, self.rect(), radius, self._glow.color,
                                  self._glow.intensity)
        paint_glow_frame(p, self.rect(), radius, self._glow.color,
                         self._glow.intensity, self._glow.cursor,
                         halo_alpha=self._glow.halo_alpha,
                         edge_alpha=self._glow.edge_alpha)
        # Keyboard focus ring — painted LAST so it sits above the hover
        # glow and stays unambiguous even on a card the pointer is also
        # over. A solid 2px accent ring rather than Qt's dotted default,
        # which is invisible against this material.
        if self.hasFocus():
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setBrush(Qt.BrushStyle.NoBrush)
            ring = QColor(self._glow.color)
            ring.setAlphaF(0.95)
            p.setPen(QPen(ring, 2.0))
            # radius - 1.5, matching the 1.5 inset: see the concentricity
            # note in animations.paint_accent_hairline. At radius - 1 this
            # ring drifted the same 0.2px at the corners and read as a
            # double edge against the card's own border.
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5),
                              radius - 1.5, radius - 1.5)
        p.end()


# ============================================================
#  BREATHING ICON — pure-paint pulsing brand glyph (no effects)
# ============================================================
class BrandMark(QWidget):
    """The '✦' Pulse mark, painted — a glyph over a soft radial halo, with
    an optional slow breath.

    Doctrine-compliant: NO QGraphicsOpacityEffect. One looping
    QVariantAnimation (0→1→0, InOutSine, ~2.6 s) drives painter opacity
    plus the halo, all inside paintEvent — a repaint costs microseconds.
    The loop suspends automatically while the widget is hidden (category
    pages open), so idle cost off-screen is zero.

    TWO INSTANCES, AND v15.1 SPLITS THEM APART, because they are doing
    different jobs and had been given one treatment:

      the DASHBOARD masthead (58px, breathing) is a hero flourish. It is
        the largest thing on the landing view, it has room, and a slow
        pulse there reads as the app being alive.

      the TITLE BAR (36px, static) is a LOGO. It sits beside the wordmark
        as identity, at a size where the same treatment stopped working:
        a Light-weight glyph at 58% of a 26px box is a 15px hairline
        character, painted in the mid-tone accent, breathing down to 45%
        opacity on a near-black shell. Every one of those choices costs
        contrast, and together they are why it read as a faint smudge
        rather than as a mark.

    So a static mark is not merely "the same thing without the animation".
    It is drawn to be READ at chrome scale:

      * DemiBold rather than Light. At this size a hairline weight has no
        mass left once antialiasing has taken its share.
      * 24px of glyph in a 36px box (STATIC_GLYPH_RATIO). It was 20-in-30,
        matched to ICON["plaque"] so the mark carried the same optical
        weight as every other glyph in the chrome — and that was the
        mistake, restated as a rule: the app's LOGO is not one more chrome
        glyph. It is the only mark in the window that identifies the
        product, it sits in a 50px bar with room to spare, and matching it
        to the nav icons made it the quietest thing in a row of quiet
        things. 36 is the same step the catalog's brand plaques take
        (APP_ICON_PX) and the same as TH.CONTROL_H, so it still lands on
        the scale — one step up it, deliberately.
      * full opacity, always. The breath's floor was the single largest
        contrast loss and it bought nothing on a logo.
      * painted in the BRAND SWEEP (accent → accent2, the indigo-to-cyan
        pair), not a flat accent. A two-stop mark separates from a flat
        accent-coloured UI and is the one place in the app the sweep is
        the subject rather than a surface treatment.
      * a firmer halo, which on obsidian is what gives a small mark an
        edge to sit against.
    """

    MIN_OPACITY = 0.45   # breath floor — glyph never fully fades
    HALO_ALPHA = 0.20    # halo strength at full breath

    #: A STATIC mark's halo. Heavier than the breathing one's peak,
    #: because it is not being animated INTO existence — it has one frame
    #: to say "this is lit", and on the obsidian shell a 0.20 halo under a
    #: 20px glyph is invisible at arm's length.
    STATIC_HALO_ALPHA = 0.30

    #: Glyph size as a fraction of the widget box, per mode. The hero can
    #: afford a delicate 58% because it is 58px across and the negative
    #: space is part of the composition; a chrome mark cannot — at 58% it
    #: is a Light-weight glyph in a box big enough to make it look lost.
    #: 0.68 of the title bar's 36px box lands on 24.
    GLYPH_RATIO = 0.58
    STATIC_GLYPH_RATIO = 0.68

    def __init__(self, glyph: str = "✦", size: int = 110,
                 accent: str = "#00d4ff", parent: QWidget | None = None,
                 breathe: bool = True):
        super().__init__(parent)
        self._glyph = glyph
        self._accent = QColor(accent)
        self._accent2 = QColor(accent)
        self._breathe = breathe
        self._breath = 1.0
        #: The quantised step last painted — see BREATH_STEPS. Starts at a
        #: value no step can equal, so the first frame always paints.
        self._breath_step = -1
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        ratio = self.GLYPH_RATIO if breathe else self.STATIC_GLYPH_RATIO
        self._font = QFont("Segoe UI")
        self._font.setPixelSize(int(size * ratio))
        self._font.setWeight(QFont.Weight.Light if breathe
                             else QFont.Weight.DemiBold)

        self._anim: QVariantAnimation | None = None
        if breathe:
            self._anim = QVariantAnimation(self)
            self._anim.setDuration(2600)
            self._anim.setStartValue(1.0)
            self._anim.setKeyValueAt(0.5, 0.0)   # exhale mid-loop
            self._anim.setEndValue(1.0)
            self._anim.setEasingCurve(EASE_BREATHE)
            self._anim.setLoopCount(-1)
            self._anim.valueChanged.connect(self._on_frame)

    # -- theming ----------------------------------------------
    def apply_theme(self, t: dict):
        self._accent = QColor(t["accent"])
        self._accent2 = QColor(t["accent2"])
        self.update()

    # -- lifecycle: animate only while visible ------------------
    def showEvent(self, e):
        super().showEvent(e)
        if self._anim is not None:
            self._anim.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        if self._anim is not None:
            self._anim.stop()

    #: How many distinct opacities the breath is allowed to paint.
    #:
    #: THE ANIMATION TICKS AT 60Hz; THE MARK DOES NOT NEED TO. Qt drives
    #: every QVariantAnimation off one 60fps timer, and _on_frame used to
    #: repaint on every one of those ticks — 60 radial gradients, 60
    #: antialiased glyphs, and 60 repaints of every transparent ancestor
    #: between this widget and the window, per second, forever, for a
    #: decoration.
    #:
    #: Measured on a settled idle window: 3.26% of a CPU core, all of it
    #: this one widget (pausing it alone took the process to 0.00%, with
    #: the status dot still breathing). The docstring's claim that "a
    #: repaint costs microseconds" was true of THIS widget and missed what
    #: it costs everything underneath it.
    #:
    #: 24 steps over a 2600ms sine loop is ~18 repaints a second at the
    #: fastest part of the curve and fewer at the ends, where the value
    #: barely moves. For a slow opacity ease with no motion in it, that is
    #: indistinguishable from 60 — film runs at 24 — and it is the same
    #: quantisation the hover lift and the paint cache already use rather
    #: than a new idea.
    BREATH_STEPS = 24

    # -- painting ----------------------------------------------
    def _on_frame(self, value: float):
        # Repaint only when the painted result would actually differ.
        # Snapping _breath to the step (rather than keeping the raw value
        # and merely skipping the update) is what makes a frame a pure
        # function of the step — the same input always paints the same
        # pixels, which is what a pixmap cache would need if this ever
        # wants one.
        step = round(float(value) * self.BREATH_STEPS)
        if step == self._breath_step:
            return
        self._breath_step = step
        self._breath = step / self.BREATH_STEPS
        self.update()

    def _pen(self):
        """The mark's ink. A static mark takes the brand sweep across its
        own box; a breathing one stays flat, because a gradient under a
        varying opacity reads as two effects fighting."""
        if self._breathe:
            return QBrush(self._accent)
        grad = QLinearGradient(0.0, 0.0, float(self.width()),
                               float(self.height()))
        grad.setColorAt(0.0, self._accent)
        grad.setColorAt(1.0, self._accent2)
        return QBrush(grad)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        level = (self.MIN_OPACITY + (1.0 - self.MIN_OPACITY) * self._breath
                 if self._breathe else 1.0)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)

        # soft halo — swelling with the breath, or steady on a static mark
        halo = QRadialGradient(center, self.width() / 2.0)
        peak = self.HALO_ALPHA if self._breathe else self.STATIC_HALO_ALPHA
        h0 = QColor(self._accent)
        h0.setAlphaF(peak * level)
        h1 = QColor(self._accent)
        h1.setAlphaF(0.0)
        halo.setColorAt(0.0, h0)
        halo.setColorAt(1.0, h1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(self.rect())

        # the glyph itself
        p.setOpacity(level)
        pen = QPen(self._pen(), 1.0)
        p.setPen(pen)
        p.setFont(self._font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._glyph)
        p.end()


#: The name this class shipped under while both of its instances breathed.
#: Kept as an alias so nothing outside this module has to care that the
#: title-bar mark stopped animating.
BreathingIcon = BrandMark


# ============================================================
#  STATUS RAIL — the sidebar's session footer (v15)
# ============================================================
class StatusRail(QFrame):
    """ONE ROW AT THE BOTTOM OF THE SIDEBAR carrying everything that
    describes the SESSION rather than the work:

        ┌─────────────────────────────────────┐
        │  ☾   PULSE v10.6.0 · BETA       ⛨   │
        └─────────────────────────────────────┘
           theme      version / check     elevation
           toggle     for updates         state

    It is a consolidation, not a new feature. Every one of these controls
    already existed; they were in four places, in four visual registers:

      * the THEME TOGGLE lived in the title bar, as a caption-font button
        that Windows would otherwise have swallowed — the HTCAPTION drag
        strip had to have a client-side hole punched through it to keep
        the button clickable (`PulseApp._over_theme_button`, deleted along
        with the button itself).
      * ELEVATION was a full-width amber call-to-action, or a full-width
        green chip in its place, each with its own stylesheet.
      * the VERSION LINE was a third full-width ghost button under those.
      * and the UPDATE BADGE sat above all of it (it still does — it is
        the one surface here that appears only when it has something to
        say, so it cannot collapse into a permanent row).

    Three stacked full-width surfaces plus a title-bar button is about
    110px of rail and four different answers to "what does chrome look
    like". As one 36px row it costs a third of that, and the sidebar's
    footer finally reads as a status bar instead of a stack of offers.

    THE ELEVATION CONTROL IS A STATE INDICATOR FIRST. The packaged app
    ships `requireAdministrator` (main.spec), so it is emerald and
    disabled on essentially every real launch; it only becomes a button —
    amber, clickable, relaunching through UAC — in the cases that survive
    that manifest: a developer running from source at their own level, or
    a policy-restricted account denied the token.
    """

    theme_toggle_requested = Signal()
    elevate_requested = Signal()
    version_clicked = Signal()

    def __init__(self, t: dict, version: str, channel: str,
                 is_admin: bool, engine_ok: bool = True,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("statusRail")
        self.setFixedHeight(TH.CONTROL_H)
        self._t = t
        self._is_admin = is_admin
        self._engine_ok = engine_ok

        lay = QHBoxLayout(self)
        # TH.RAIL_INSET, not a SPACE step: SPACE measures the gap BETWEEN
        # things, and this is the thickness of a frame around one. It is
        # derived from the two sizes it has to reconcile (see the note on
        # the constant) so the rail cannot drift out of alignment with its
        # own buttons.
        inset = TH.RAIL_INSET
        lay.setContentsMargins(inset, inset, inset, inset)
        lay.setSpacing(TH.SPACE["xxs"])

        self._theme_btn = QPushButton()
        self._theme_btn.setFixedSize(TH.RAIL_BUTTON, TH.RAIL_BUTTON)
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Chrome, not content: the rail must never join a page's tab order
        # or pull focus off a card grid — the same call every other piece
        # of app chrome makes.
        self._theme_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._theme_btn.clicked.connect(self.theme_toggle_requested.emit)
        lay.addWidget(self._theme_btn)

        self._divider = QFrame()
        self._divider.setFixedWidth(1)
        lay.addWidget(self._divider)

        self._version = QPushButton(
            f"PULSE  v{version}  ·  {channel.upper()}" if channel
            else f"PULSE  v{version}")
        self._version.setFlat(True)
        self._version.setCursor(Qt.CursorShape.PointingHandCursor)
        self._version.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._version.setToolTip("Check for updates")
        self._version.clicked.connect(self.version_clicked.emit)
        lay.addWidget(self._version, 1)

        self._state_btn = QPushButton()
        self._state_btn.setFixedSize(TH.RAIL_BUTTON, TH.RAIL_BUTTON)
        self._state_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._state_btn.clicked.connect(self.elevate_requested.emit)
        lay.addWidget(self._state_btn)

        self.apply_theme(t)

    # -- session state -------------------------------------------------
    def set_session(self, is_admin: bool, engine_ok: bool):
        """Re-report the session. Both facts land on ONE control because
        they answer one question — can this app do its job right now — and
        two separate chips saying that is what the masthead used to do."""
        self._is_admin, self._engine_ok = is_admin, engine_ok
        self._sync_state()

    def is_actionable(self) -> bool:
        """True when the state button is a BUTTON rather than a readout —
        i.e. the session is unelevated and relaunching would change it."""
        return bool(self._engine_ok and not self._is_admin)

    def _sync_state(self):
        t = self._t
        ok = self._is_admin and self._engine_ok
        self._state_btn.setStyleSheet(TH.rail_state_qss(t, ok))
        glyph, fallback = TH.glyph("shieldplain")
        font = TH.icon_font(TH.ICON["micro"]) if glyph else None
        if font is not None:
            self._state_btn.setFont(font)
        self._state_btn.setText(glyph or fallback)
        # NAME AND DESCRIPTION SPLIT DELIBERATELY. The tooltip here is a
        # sentence, and a sentence is the wrong thing for a screen reader
        # to announce as a control's NAME — the reader says the name every
        # time focus lands, so "Not elevated. Some system-level operations
        # need Administrator rights - click to relaunch (a UAC prompt will
        # appear)." would be read out in full on every pass. The short
        # label is the name; the sentence stays the description, which a
        # reader offers on request.
        if not self._engine_ok:
            name = "Engine missing"
            detail = ("The PowerShell engine is missing — Pulse can report "
                      "but cannot run operations.")
        elif self._is_admin:
            name = "Running as Administrator"
            detail = "Running as Administrator — every operation is available."
        else:
            name = "Not elevated — relaunch as Administrator"
            detail = ("Not elevated. Some system-level operations need "
                      "Administrator rights — click to relaunch (a UAC "
                      "prompt will appear).")
        self._state_btn.setToolTip(detail)
        self._state_btn.setAccessibleName(name)
        self._state_btn.setAccessibleDescription(detail)
        self._state_btn.setEnabled(self.is_actionable())
        self._state_btn.setCursor(
            Qt.CursorShape.PointingHandCursor if self.is_actionable()
            else Qt.CursorShape.ArrowCursor)

    # -- theming -------------------------------------------------------
    def apply_theme(self, t: dict):
        self._t = t
        self.setStyleSheet(TH.status_rail_qss(t))
        self._theme_btn.setStyleSheet(TH.rail_button_qss(t))
        self._divider.setStyleSheet(TH.rail_divider_qss(t))
        self._version.setStyleSheet(TH.sidebar_version_qss(t))
        # The toggle shows the theme it will switch TO, which is what the
        # title-bar button it replaces did and what every OS control does.
        key = "moon" if t["name"] == "dark" else "sun"
        glyph, fallback = TH.glyph(key)
        font = TH.icon_font(TH.ICON["micro"]) if glyph else None
        if font is not None:
            self._theme_btn.setFont(font)
        self._theme_btn.setText(glyph or fallback)
        theme_label = ("Switch to light theme" if t["name"] == "dark"
                       else "Switch to dark theme")
        self._theme_btn.setToolTip(theme_label)
        # Re-announced per theme, like the maximize button: the control
        # names the theme it switches TO, so a fixed name would be wrong
        # in one of the two states.
        self._theme_btn.setAccessibleName(theme_label)
        self._sync_state()


# ============================================================
#  NAV PILL — Back / Home header buttons
# ============================================================
class NavPill(QPushButton):
    """The page header's Back / Home buttons.

    v15 puts them on the control scale (34 -> TH.CONTROL_H). They are
    ordinary buttons sitting two pixels under every other button in the
    app — the exact "almost aligned" defect the scale exists to remove,
    and the reason 34 was on the exemption list was that the page accent
    rail happens to be 34 too, which is a coincidence rather than a
    reason."""

    def __init__(self, text: str, t: dict, width: int = 92):
        super().__init__(text)
        self.setFixedSize(width, TH.CONTROL_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_theme(t)

    def apply_theme(self, t: dict):
        self.setStyleSheet(TH.nav_pill_qss(t))


# ============================================================
#  DEPTH CARD — non-interactive QFrame with the permanent glass bevel
# ============================================================
class DepthCard(QFrame):
    """A plain QFrame plus the painted glass bevel (see
    animations.paint_bevel_frame) — for surfaces that want the depth cue
    but aren't clickable, so no glow/press/ripple state is needed. Used by
    the Welcome page's system-insight tiles and status dock; QSS selectors
    like `QFrame#insight` still match (Qt resolves by base class + object
    name, and DepthCard IS a QFrame)."""

    def __init__(self, radius: int = TH.RADIUS["panel"],
                 parent: QWidget | None = None,
                 t: dict | None = None):
        super().__init__(parent)
        self._radius = radius
        # v11: these surfaces cast the same shadow the cards do, so the hero
        # banner and status strip sit on the page instead of being drawn on
        # it. `t` is optional because DepthCard predates the depth tokens and
        # some call sites build it before a theme is at hand; without one it
        # falls back to the neutral bevel it has always painted.
        self._bevel: tuple[float, float] | None = None
        self._shadow: tuple[float, int] | None = None
        # v13: the lit top edge is half of the elevation cue (see
        # theme.sheen_alphas). A container that casts a shadow but has no
        # top face reads as a shadow printed behind a flat shape — which is
        # exactly how the hero banner and every dialog panel looked once
        # the cards beside them got theirs.
        self._sheen: tuple[int, float, float] | None = None
        if t is not None:
            self.set_theme(t)

    def set_theme(self, t: dict):
        self._bevel = TH.bevel_alphas(t)
        self._shadow = TH.shadow_alphas(t)
        self._sheen = TH.sheen_alphas(t)
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        if self._shadow is not None:
            paint_drop_shadow(p, self.rect(), self._radius, *self._shadow)
        if self._bevel is not None:
            paint_bevel_frame(p, self.rect(), self._radius, *self._bevel)
        else:
            paint_bevel_frame(p, self.rect(), self._radius)
        if self._sheen is not None:
            peak, depth, rest = self._sheen
            # The resting weight, never a hovered one: these surfaces do
            # not hover, and a container lit harder than the cards sitting
            # on it would invert the elevation order it exists to set up.
            paint_top_sheen(p, self.rect(), self._radius, strength=rest,
                            peak=peak, depth=depth)
        p.end()


# ============================================================
#  HEALTH TILE — one figure in the dashboard's KPI row (v15)
# ============================================================
class HealthTile(DepthCard):
    """ONE NUMBER, ITS LABEL, AND A METER — the form a single current
    value takes when it is not a chart:

        ┌────────────────────┐
        │ 47%                │  the figure, on the text ramp
        │ MEMORY             │  its label
        │ ━━━━━━━━━━━─────── │  a 3px meter, severity-toned
        └────────────────────┘

    Four of these are the dashboard's health row. The composition is the
    standard stat-tile contract — label, value, and (where the value is a
    ratio against a limit) a meter rather than a one-bar bar chart.

    TWO CHANNELS, NEVER ONE. The figure and the caption stay on the text
    ramp in every state; only the METER carries severity (accent -> warn
    -> err, see theme.health_tone). That split is what keeps the row
    readable for someone who cannot separate amber from emerald: the
    number and its label say what it is, and the meter's LENGTH says how
    bad it is before its colour does.

    A tile with no ratio to show (a count, a state) passes fraction=None
    and simply renders no meter — an empty track under a number is a
    promise of a scale that does not exist.

    WHY IT IS A DepthCard: the tile is an elevated surface like every card
    on the page, so it inherits the same cast shadow, hairline and lit top
    edge rather than inventing a fifth way to look raised.
    """

    #: The meter's bar. 3px because it is a MARK, not a control: at 2 it
    #: disappears against the tile's own hairline, and at 4 it starts to
    #: read as a progress bar the user could drag.
    _METER_H = 3

    def __init__(self, caption: str, t: dict, parent: QWidget | None = None):
        super().__init__(radius=TH.RADIUS["card"], parent=parent, t=t)
        self.setObjectName("healthTile")
        self._t = t
        self._fraction: float | None = None
        # The NAME of an overriding tone, or None to derive it from the
        # ratio. Kept as a key rather than as a resolved colour so it can
        # be re-resolved against a new palette — see _sync_tone.
        self._tone_key: str | None = None
        self._tone = QColor(TH.to_qcolor(t["accent"]))

        lay = QVBoxLayout(self)
        # PAD["surface"] horizontally — the same inset a GlassCard uses,
        # which matters because the health row sits DIRECTLY ABOVE the
        # quick-action grid on the same page: a tile insetting its figure
        # by 12 while the card under it insets its title by 16 puts a 4px
        # step in a vertical line the eye follows down the page. Vertical
        # stays a step tighter, the same trade row_padding makes for the
        # same reason: a tile is wider than it is tall.
        pad = TH.PAD["surface"]
        lay.setContentsMargins(pad, TH.SPACE["sm"], pad, TH.SPACE["sm"])
        lay.setSpacing(0)
        lay.addStretch()
        self._value = QLabel("—")
        lay.addWidget(self._value)
        self._caption = QLabel(caption.upper())
        lay.addWidget(self._caption)
        lay.addStretch()
        # room under the caption for the meter, which is painted rather
        # than laid out (a 3px QFrame in the layout would have to fight
        # the stretches for its own height every resize)
        lay.addSpacing(TH.SPACE["sm"])

        self.apply_theme(t)

    def set_value(self, text: str, fraction: float | None = None):
        """Report the tile. `fraction` is the ratio the meter draws, or
        None for a tile that is a count rather than a proportion.

        A fresh ratio DROPS any standing tone override: the number and the
        severity are one report, so a caller that supplies the first
        without the second is asking for the threshold answer.
        """
        self._value.setText(text or "—")
        self._fraction = None if fraction is None else max(0.0, min(1.0, fraction))
        self._tone_key = None
        self._sync_tone()

    def set_tone(self, tone_key: str):
        """Override the meter's tone with a named token — for tiles whose
        severity is not a ratio (a pending-action count is 'ok' at zero
        and 'warn' at anything else, and no threshold on the number itself
        would say that)."""
        self._tone_key = tone_key
        self._sync_tone()

    def _sync_tone(self):
        """Resolve the meter's colour against the CURRENT palette.

        The override has to be re-resolved rather than remembered as a
        colour, and that is the whole reason this is a method. apply_theme
        used to re-derive the tone from the ratio unconditionally, so a
        theme switch silently discarded whatever set_tone had said: the
        dashboard's ACTIONS DUE meter is amber in the mode the app started
        in and reverts to the plain accent in the other one, which turns
        the tile's only severity channel off without anything having
        changed about the machine it is reporting on.
        """
        t = self._t
        self._tone = TH.to_qcolor(
            t.get(self._tone_key, t["accent"]) if self._tone_key
            else TH.health_tone(t, self._fraction))
        self.update()

    def apply_theme(self, t: dict):
        self._t = t
        self.set_theme(t)
        self.setStyleSheet(TH.health_tile_qss(t))
        self._value.setStyleSheet(TH.health_tile_value_qss(t))
        self._caption.setStyleSheet(TH.health_tile_caption_qss(t))
        self._sync_tone()

    def paintEvent(self, e):
        super().paintEvent(e)          # plate, shadow, hairline, top sheen
        if self._fraction is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # the meter starts where the text above it starts — it is painted
        # rather than laid out, so nothing but this line keeps the two
        # agreeing (see the layout's own margins)
        inset = TH.PAD["surface"]
        bottom = self.height() - TH.SPACE["sm"] - self._METER_H
        width = max(0, self.width() - inset * 2)
        radius = self._METER_H / 2.0
        track = QColor(self._tone)
        # The unfilled track is a lighter step of the meter's OWN ramp,
        # not a neutral grey: state then reads across the whole bar
        # instead of only across the filled part of it.
        track.setAlphaF(0.16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(inset, bottom, width, self._METER_H),
                          radius, radius)
        filled = width * self._fraction
        if filled >= self._METER_H:
            p.setBrush(self._tone)
            p.drawRoundedRect(QRectF(inset, bottom, filled, self._METER_H),
                              radius, radius)
        p.end()


# ============================================================
#  ACTION ROW — one offered action, on one row
# ============================================================
class ActionRow(QFrame):
    """ONE OFFERED ACTION, on one row: icon, what it is, and the button
    that does it.

    THE SHAPE, AND WHY IT IS NOT A CARD. A GlassCard is a tile in a grid —
    it competes for attention with thirteen siblings, so it earns a 42px
    plaque, a three-line description, a meta footer, a hover lift and a
    156px height envelope. A hub offers TWO actions. Rendering two of those
    as full cards is what left the Microsoft Edge and Microsoft OneDrive
    dialogs as a pair of tiles adrift in a panel sized for a whole page,
    which is the "empty stretched layout" defect in its purest form.

    Three things read left to right, which is the order the eye wants them:

        [ icon ]  Title                                   [ Action ]
                  One line of description.

    THE ICON IS LEFT-ALIGNED AND THE BUTTON IS RIGHT-ALIGNED, and the text
    between them is the only elastic part. That gives a column of rows two
    hard vertical rules — the glyph edge and the button edge — which is
    what makes a list of them scan as a list rather than as three
    independent boxes. The plaque is the same TH.PLAQUE_SIZE well the cards
    and the sidebar use, so the same module is the same object at every
    scale in the app.

    THE BUTTON IS THE ONLY AFFORDANCE, deliberately. The whole row is
    clickable as a convenience (a native settings list behaves that way),
    but a destructive action must never be something a stray click on a
    description can trigger — so `danger` rows are button-only, and the
    row-wide click is dropped for them.

    DESTRUCTIVE STYLING is a translucent tinted FILL plus a hairline (see
    theme.action_row_qss / DANGER_TINT), replacing the high-contrast red
    wireframe these rows used to wear. A wireframe makes the teardown the
    loudest thing on a dialog whose other option is the safe one — it
    advertises exactly the action the user is least likely to want.
    """

    activated = Signal()

    #: Icon plaque FOOTPRINT — the widget, not the well. Identical to
    #: GlassCard._PLAQUE, and identical for the reason IconPlaque._PAD
    #: exists: the halo bleeds into the padding, so the WELL still measures
    #: TH.PLAQUE_SIZE and a row's glyph is the same object as a card's.
    _PLAQUE = TH.PLAQUE_SIZE + 2 * IconPlaque._PAD
    _ICON_PX = TH.ICON["plaque"]

    def __init__(self, item: dict, t: dict, accent: str,
                 action_label: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("actionRow")
        self.item = item
        self._danger = bool(item.get("danger"))
        self._accent = t["err"] if self._danger else accent

        row = QHBoxLayout(self)
        # Asymmetric on purpose, and it is the one asymmetry in the app's
        # padding that is a decision rather than a leftover: the left inset
        # sits before a 42px plaque and the right inset sits after a 36px
        # button, so equal insets would leave the button visibly closer to
        # the edge than the glyph is. lg/md restores the optical balance.
        row_padding(row)
        row.setSpacing(TH.SPACE["md"])

        char, fluent = (TH.glyph(item["glyph"]) if item.get("glyph")
                        else (item.get("icon", "•"), False))
        self._icon = IconPlaque(char)
        self._icon.setFixedSize(self._PLAQUE, self._PLAQUE)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_font = TH.icon_font(self._ICON_PX) if fluent else QFont()
        if icon_font is None:
            icon_font = QFont()
        icon_font.setPixelSize(self._ICON_PX)
        self._icon.setFont(icon_font)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(TH.SPACE["xxs"])
        self._title = QLabel(item.get("title", ""))
        text.addWidget(self._title)
        # ClampedLabel, not a plain wrapped QLabel: the row's height must be
        # a function of its LINE BUDGET rather than of how long somebody's
        # description happened to be, or one verbose entry silently makes
        # its whole dialog taller than the rest.
        self._desc = ClampedLabel(item.get("desc", ""), max_lines=2)
        text.addWidget(self._desc)
        row.addLayout(text, 1)

        self.button = QPushButton(action_label or self._default_label())
        self.button.setFixedHeight(TH.CONTROL_H)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.activated.emit)
        row.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)

        if not self._danger:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_theme(t, accent)

    def _default_label(self) -> str:
        """The verb, taken from the action itself.

        A generic "Open" on every row would make the list of buttons
        useless as a list — the button is the second place the user reads
        what a row does, so it has to say something different per row.
        `action` lets a caller override; otherwise the destructive tone
        gets the blunt word and everything else gets the neutral one.
        """
        return str(self.item.get("action")
                   or ("Remove" if self._danger else "Run"))

    def apply_theme(self, t: dict, accent: str | None = None):
        if accent is not None:
            self._accent = t["err"] if self._danger else accent
        base = accent if accent is not None else t["accent"]
        self.setStyleSheet(TH.action_row_qss(t, base, self._danger))
        self._icon.apply_theme(t, self._accent)
        self._title.setStyleSheet(TH.label_qss(t, "card"))
        self._desc.setStyleSheet(TH.label_qss(t, "body"))
        self.button.setStyleSheet(
            TH.action_button_qss(t, base, self._danger))

    def mouseReleaseEvent(self, e):
        # Click-anywhere, EXCEPT on a destructive row (see the class note)
        # and except on the button, which emits for itself.
        if (e.button() == Qt.MouseButton.LeftButton and not self._danger
                and self.childAt(e.position().toPoint()) is not self.button):
            self.activated.emit()
        super().mouseReleaseEvent(e)


# ============================================================
#  DIALOGS
# ============================================================
class ConfirmDialog(PulseDialog):
    """"Are you sure?", with the option to be shown rather than told.

    THE PREVIEW BUTTON IS THE POINT OF THIS DIALOG NOW. A confirmation can
    describe INTENT — "Removes Edge and backs up its data first" — and
    cannot describe EFFECT, which for the least reversible operations in
    the app is the half the user actually needs. The engine has been able
    to answer that since v6 ($Script:DryRun gates every mutation primitive
    and Invoke-Mutation logs a "[WHATIF] Would ..." line for each write it
    does not make); nothing in the GUI's single-task path ever asked it.

    Preview ACCEPTS rather than taking a third result code: both buttons
    start a run, and `preview` is what decides which kind. The caller
    reads that attribute on the next line, which is the contract
    _exec_dialog's deleteLater depends on.
    """

    def __init__(self, parent: QWidget, item: dict, t: dict):
        super().__init__(parent)
        #: True when the user asked to SEE the task rather than run it.
        #: Read by main.request_task immediately after exec() returns.
        self.preview = False
        danger = bool(item.get("danger"))
        accent = t["err"] if danger else t["accent"]
        panel = _dialog_chrome(self, t, accent, width=440)

        lay = dialog_body(panel, "sm")

        head = QLabel(f"{item['icon']}  {item['title']}")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        # Wrap, like every other dialog heading in the app. Without it the
        # label's minimum width is its ENTIRE single line, which a fixed
        # 440px panel cannot always satisfy: measured, "⚡  Ultimate Power
        # Plan" at the 18px/700 dialog role needs 444px, so the layout was
        # 4px over-constrained and Qt resolved it by pushing the content
        # past the panel edge. Long operation titles are normal here, so the
        # heading has to adapt to the panel rather than the other way round.
        head.setWordWrap(True)
        lay.addWidget(head)

        body = QLabel(item["desc"])
        body.setWordWrap(True)
        body.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(body)

        if danger:
            warn = QLabel("⚠️  This action changes your system and may be hard to undo.")
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"color: {t['err']}; font-size: {TH.TYPE['caption']}px; font-weight: 500;"
                "background: transparent; border: none;")
            lay.addWidget(warn)

        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)

        go = QPushButton("Proceed")
        go.setStyleSheet(TH.dialog_go_qss(t, accent))
        go.clicked.connect(self.accept)

        # Styled as a SECONDARY action, sharing the cancel treatment: it is
        # the safe choice, and giving it the accent would put two primaries
        # on one row and make the destructive one compete for the eye.
        # dialog_footer right-aligns in the order given with the primary
        # last, so this reads Cancel · Preview · Proceed — the commitment
        # stays the final step rather than sitting between two safe ones.
        preview = QPushButton("Preview")
        preview.setStyleSheet(TH.dialog_cancel_qss(t))
        preview.setToolTip(
            "Run this task in simulation — it reports every change it "
            "would make and makes none of them.")
        preview.setAccessibleName("Preview this task without changing anything")
        preview.clicked.connect(self._choose_preview)

        dialog_footer(lay, cancel, preview, go)

    def _choose_preview(self):
        self.preview = True
        self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


class NoticeDialog(PulseDialog):
    """A one-button "here is a fact" sheet.

    Distinct from ConfirmDialog, which asks a QUESTION and therefore offers
    Cancel/Proceed. Presenting a statement through a confirm dialog invites
    the reader to look for the decision they are being asked to make, and
    there isn't one — so this has a single Close and no accept path at all.

    Used by the Edge/OneDrive install check: when the app is already on the
    machine, the honest response to "Install / Restore" is to say so rather
    than to open an installer wizard that would deploy nothing.
    """

    def __init__(self, parent: QWidget, title: str, body: str, t: dict,
                 icon: str = "ℹ️"):
        super().__init__(parent)
        panel = _dialog_chrome(self, t, t["accent"], width=440)
        lay = dialog_body(panel, "sm")

        head = QLabel(f"{icon}  {title}")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        head.setWordWrap(True)      # see ConfirmDialog — same 440px panel
        lay.addWidget(head)

        text = QLabel(body)
        text.setWordWrap(True)
        text.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(text)

        close = QPushButton("Close")
        close.setStyleSheet(TH.dialog_go_qss(t, t["accent"]))
        close.clicked.connect(self.reject)
        dialog_footer(lay, close)

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


class RevertChoiceDialog(PulseDialog):
    """The two-way toggle's decision point (v1.0). Opened instead of a
    plain confirm when a revertible tweak's card is clicked while the
    probe reports it applied (or modified): the one question a click on
    an already-applied toggle genuinely poses is "re-apply it, or put it
    back?", and neither answer deserves to be the buried option.

    `choice` after Accepted: "apply" or "revert". This dialog REPLACES the
    item's own confirm step for the re-apply path — asking "are you sure?"
    twice for one click is how confirmation fatigue is manufactured."""

    def __init__(self, parent: QWidget, item: dict, t: dict, verdict: str):
        super().__init__(parent)
        self.choice: str | None = None
        accent = t["accent"]
        panel = _dialog_chrome(self, t, accent, width=470)

        lay = dialog_body(panel, "sm")

        head = QLabel(f"{item['icon']}  {item['title']}")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        head.setWordWrap(True)
        lay.addWidget(head)

        if verdict == "mixed":
            status = ("This tweak is PARTIALLY applied — some of its values "
                      "match, some don't (it may have been changed outside "
                      "Pulse).")
        else:
            status = "This tweak is currently applied on your system."
        body = QLabel(
            f"{status}\n\nRe-apply it to enforce Pulse's values again, or "
            "revert it to your original settings (or Windows defaults if no "
            "original was captured).")
        body.setWordWrap(True)
        body.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(body)

        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)

        revert = QPushButton("Revert to Default")
        revert.setStyleSheet(TH.dialog_secondary_go_qss(t, accent))
        revert.clicked.connect(lambda: self._pick("revert"))

        apply_btn = QPushButton("Re-apply")
        apply_btn.setStyleSheet(TH.dialog_go_qss(t, accent))
        apply_btn.clicked.connect(lambda: self._pick("apply"))

        dialog_footer(lay, cancel, revert, apply_btn)

    def _pick(self, choice: str):
        self.choice = choice
        self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


class PlaybookStepRow(QFrame):
    """One step inside PlaybookDialog, with a live status lamp.

    The lamp is text, not colour alone: "colour = state" fails for the
    ~8% of men with a red/green deficiency, and this list is the only
    place the user learns which step of an unattended run went wrong.
    """

    LAMPS = {
        "pending":   ("○", "text_faint"),
        "running":   ("◐", "accent"),
        "ok":        ("✓", "ok"),
        "error":     ("✕", "err"),
        "skipped":   ("–", "text_faint"),
        "cancelled": ("■", "warn"),
    }

    def __init__(self, index: int, step, t: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._t = t
        self._state = "pending"
        self.setObjectName("playbookStep")

        lay = QHBoxLayout(self)
        row_padding(lay)
        lay.setSpacing(TH.SPACE["md"])

        self._lamp = QLabel()
        self._lamp.setFixedWidth(16)
        self._lamp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lamp, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(TH.SPACE["xxs"])
        self._title = QLabel(f"{index + 1}.  {step.title}")
        text_col.addWidget(self._title)
        self._detail = QLabel(step.note or step.task)
        self._detail.setWordWrap(True)
        text_col.addWidget(self._detail)
        lay.addLayout(text_col, 1)

        self._tag = QLabel("optional" if step.optional else "")
        self._tag.setVisible(bool(step.optional))
        lay.addWidget(self._tag, 0, Qt.AlignmentFlag.AlignTop)

        self.apply_theme(t)

    def apply_theme(self, t: dict):
        self._t = t
        self.setStyleSheet(
            f"#playbookStep {{ background: transparent; border: none; "
            f"border-bottom: 1px solid {t['panel_line']}; }}")
        self._title.setStyleSheet(TH.label_qss(t, "card"))
        self._detail.setStyleSheet(TH.label_qss(t, "caption"))
        self._tag.setStyleSheet(TH.card_meta_pill_qss(t))
        self.set_state(self._state, self._detail.text())

    def set_state(self, state: str, detail: str | None = None):
        self._state = state
        glyph, token = self.LAMPS.get(state, self.LAMPS["pending"])
        self._lamp.setText(glyph)
        self._lamp.setStyleSheet(
            f"color: {self._t[token]}; font-size: {TH.TYPE['label']}px; font-weight: 700;"
            "background: transparent; border: none;")
        if detail is not None:
            self._detail.setText(detail)


class PlaybookDialog(PulseDialog):
    """Browse, preview and run declarative playbooks (v10.3).

    ONE dialog with two modes rather than a chooser plus a progress
    window. A playbook run is not a fire-and-forget action — the user
    wants to watch which step is executing and read what happened
    afterwards — so the step list they picked from becomes the step list
    they watch, in place. Nothing moves under the cursor at the moment the
    run starts, which is exactly when it would be most disorienting.

    PREVIEW IS THE DEFAULT-ADJACENT ACTION. Every step runs through the
    engine's -WhatIf path, so "Preview" answers "what would this do to my
    machine" with zero mutations. It is offered first and styled as the
    safe button; Run carries the accent.
    """

    #: Emitted when the user presses Stop during a live run.
    stop_requested = Signal()

    def __init__(self, parent: QWidget, playbooks: list, errors: list[str],
                 t: dict, is_admin: bool = True):
        super().__init__(parent)
        self._t = t
        self._playbooks = playbooks
        self._is_admin = is_admin
        self._rows: list[PlaybookStepRow] = []
        self._current = playbooks[0] if playbooks else None

        #: Set when the user asks to run; read by the caller.
        self.chosen: object | None = None
        self.dry_run = False
        #: True between enter_run_mode and enter_done_mode. While set, the
        #: dialog refuses to be dismissed — see reject().
        self._run_locked = False

        accent = TH.resolve_accent(t, "automation")
        self._accent = accent
        panel = _dialog_chrome(self, t, accent, responsive=True)

        lay = dialog_body(panel, "md")

        head = QLabel("📘  Playbooks")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        lay.addWidget(head)

        blurb = QLabel(
            "Ordered task sequences that run through the normal engine. "
            "Preview simulates every step with -WhatIf and changes nothing.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(blurb)

        if errors:
            # A malformed playbook is reported, never silently dropped —
            # a technician who mistyped a task name must find out now.
            warn = QLabel("⚠️  " + "  ·  ".join(errors[:3]))
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"color: {t['warn']}; font-size: {TH.TYPE['caption']}px; background: transparent;"
                "border: none;")
            lay.addWidget(warn)

        if not playbooks:
            empty = QLabel(
                "No playbooks found. Drop a .json file into the "
                "'playbooks' folder next to Pulse to add one.")
            empty.setWordWrap(True)
            empty.setStyleSheet(TH.label_qss(t, "body"))
            lay.addWidget(empty)
            lay.addStretch()
            self._build_buttons(lay, t, runnable=False)
            return

        # -- playbook picker: a row of pills ---------------------------
        picker = QHBoxLayout()
        picker.setSpacing(TH.SPACE["sm"])
        self._pills: list[QPushButton] = []
        for playbook in playbooks:
            pill = QPushButton(f"{playbook.icon}  {playbook.name}")
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.setCheckable(True)
            pill.clicked.connect(
                lambda _checked, p=playbook: self._select(p))
            self._pills.append(pill)
            picker.addWidget(pill)
        picker.addStretch()
        lay.addLayout(picker)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        lay.addWidget(self._summary)

        # -- step list -------------------------------------------------
        self._scroll = FitScroll()
        self._scroll.setStyleSheet(TH.scroll_area_qss(t))
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self._host_lay = scroll_host_layout(self._host)
        # The one scroll host that stays FLUSH: PlaybookStepRow carries its
        # own framing, and a gap between steps would break the sequence
        # into unrelated rows instead of reading as one ordered list.
        self._host_lay.setSpacing(0)
        self._host_lay.addStretch()
        self._scroll.setWidget(self._host)
        lay.addWidget(self._scroll, 1)

        self._status = QLabel()
        self._status.setWordWrap(True)
        lay.addWidget(self._status)
        self.set_status("")

        self._build_buttons(lay, t, runnable=True)
        self._select(self._current)

    # -- construction helpers ---------------------------------
    def _build_buttons(self, lay: QVBoxLayout, t: dict, runnable: bool):
        row = QHBoxLayout()
        row.addStretch()

        self._close_btn = QPushButton("Close")
        size_dialog_button(self._close_btn)
        self._close_btn.setStyleSheet(TH.dialog_cancel_qss(t))
        self._close_btn.clicked.connect(self.reject)
        row.addWidget(self._close_btn)

        self._preview_btn = QPushButton("Preview")
        size_dialog_button(self._preview_btn)
        self._preview_btn.setStyleSheet(TH.dialog_cancel_qss(t))
        self._preview_btn.setToolTip(
            "Run every step with -WhatIf: reports what would happen and "
            "changes nothing.")
        self._preview_btn.clicked.connect(lambda: self._launch(dry_run=True))
        self._preview_btn.setVisible(runnable)
        row.addWidget(self._preview_btn)

        self._run_btn = QPushButton("Run Playbook")
        size_dialog_button(self._run_btn)
        self._run_btn.setStyleSheet(TH.dialog_go_qss(t, self._accent))
        self._run_btn.clicked.connect(lambda: self._launch(dry_run=False))
        self._run_btn.setVisible(runnable)
        row.addWidget(self._run_btn)

        lay.addLayout(row)

    def _select(self, playbook):
        self._current = playbook
        t = self._t
        for pill, candidate in zip(self._pills, self._playbooks):
            active = candidate is playbook
            pill.setChecked(active)
            pill.setStyleSheet(
                TH.dialog_go_qss(t, self._accent) if active
                else TH.dialog_cancel_qss(t))

        admin_note = ""
        if playbook.needs_admin and not self._is_admin:
            admin_note = ("  ·  ⚠️ needs Administrator — some steps will be "
                          "refused in this session")
        self._summary.setText(
            f"{playbook.description}\n{len(playbook)} steps{admin_note}")
        self._summary.setStyleSheet(TH.label_qss(t, "body"))

        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        for index, step in enumerate(playbook.steps):
            row = PlaybookStepRow(index, step, t)
            self._rows.append(row)
            self._host_lay.insertWidget(self._host_lay.count() - 1, row)
        self._status.setText("")

    def _launch(self, dry_run: bool):
        self.chosen = self._current
        self.dry_run = dry_run
        self.accept()

    # -- live run API (driven by PlaybookRunner) --------------
    def enter_run_mode(self, dry_run: bool):
        """Switch the browse UI into a progress view in place."""
        self._run_locked = True
        for pill in self._pills:
            pill.setEnabled(False)
        self._preview_btn.setEnabled(False)
        self._run_btn.setText("Stop")
        self._run_btn.setStyleSheet(TH.dialog_go_qss(self._t, self._t["err"]))
        try:
            self._run_btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._run_btn.clicked.connect(self.stop_requested.emit)
        self._close_btn.setEnabled(False)
        prefix = "Previewing" if dry_run else "Running"
        self.set_status(f"{prefix} {self._current.name}…")

    def mark_step(self, index: int, state: str, detail: str | None = None):
        if 0 <= index < len(self._rows):
            self._rows[index].set_state(state, detail)

    def set_status(self, text: str, kind: str = "info"):
        colour = {"ok": self._t["ok"], "error": self._t["err"],
                  "warn": self._t["warn"]}.get(kind, self._t["text_muted"])
        self._status.setText(text)
        self._status.setStyleSheet(
            f"color: {colour}; font-size: {TH.TYPE['caption']}px; font-weight: 600;"
            "background: transparent; border: none;")
        # Hidden while empty: the dialog's panel QSS gives a bare QLabel a
        # frame, so an empty status line painted as a stray input box
        # sitting above the buttons.
        self._status.setVisible(bool(text))

    def reject(self):
        """Refuse dismissal while a run is live.

        Disabling the Close BUTTON was never enough: PulseDialog also
        dismisses on Escape (QDialog's default) and on a click anywhere on
        the scrim, and the app's native caption-close path rejects every
        open dialog before closing the window. Any of those detached the
        dialog from a PlaybookRunner that kept going — so a sequence of
        machine-wide changes carried on with its progress view gone and no
        way to reach the Stop button.

        The run is stoppable, not un-abandonable: Stop is right there, and
        the window's own close guard now sees the playbook too.
        """
        if self._run_locked:
            self.set_status(
                "This playbook is still running — press Stop to end it, "
                "or let it finish.", "warn")
            return
        super().reject()

    def force_close(self):
        """Dismiss regardless of the run lock.

        The one legitimate override: the app itself is shutting down and
        has already cancelled the runner, so this dialog's exec() loop has
        to unwind or it would outlive the window it is parented to.
        """
        self._run_locked = False
        super().reject()

    def enter_done_mode(self):
        self._run_locked = False
        self._close_btn.setEnabled(True)
        self._run_btn.setText("Close")
        self._run_btn.setStyleSheet(TH.dialog_go_qss(self._t, self._accent))
        try:
            self._run_btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._run_btn.clicked.connect(self.reject)

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


# ============================================================
#  READ-ONLY REPORT PRIMITIVES
#
#  Shared by the two report surfaces — HealthReportDialog and
#  ActivationStatusDialog. Both render the same shape of content (a titled
#  section, label/value pairs, full-width explanation sentences), and both
#  must colour a "tone" identically: a warning in the health report and a
#  warning in the activation report are the same warning, and two private
#  copies of this mapping would eventually disagree about what amber means.
#
#  `tone` is always a KEY ('ok'/'warn'/'err'), never a colour — the hex is
#  resolved from the CURRENT theme here, so these survive a live theme
#  switch the same way every other widget does.
# ============================================================
def report_tone_color(t: dict, tone: str) -> str:
    """A tone key -> this theme's hex. Anything unrecognised (including
    "") falls back to neutral body text, which is the honest rendering of
    a state we could not determine — not a guess dressed up as a fact."""
    return {"ok": t["ok"], "warn": t["warn"], "err": t["err"]}.get(tone, t["text"])


def report_row(t: dict, label: str, value: str, tone: str = "",
               label_width: int = 210) -> QWidget:
    """One label/value line. `label_width` is a parameter because the two
    reports carry different label vocabularies — the health report's
    "Operating system" needs the wider column that would leave the
    activation report's "Status" stranded in whitespace."""
    holder = QWidget()
    holder.setStyleSheet("background: transparent;")
    line = QHBoxLayout(holder)
    line.setContentsMargins(0, TH.SPACE["xxs"], 0, TH.SPACE["xxs"])
    line.setSpacing(TH.SPACE["md"])
    left = QLabel(label)
    # `text_muted`, not the caption role's `text_faint`. text_faint is
    # pinned at exactly 4.55:1 on the CARD, and a report row renders on the
    # sub-card panel — a brighter surface in light mode, where the same
    # colour measures 4.48:1 and slips under AA. The label column here is
    # content (it names the value beside it), not decoration, so it takes
    # the step above rather than the floor.
    left.setStyleSheet(
        f"color: {t['text_muted']}; font-size: {TH.TYPE['meta']}px; font-weight: 500;"
        "letter-spacing: 1px; background: transparent; border: none;")
    left.setMinimumWidth(label_width)
    line.addWidget(left, 0)
    right = QLabel(value)
    right.setWordWrap(True)
    right.setStyleSheet(
        f"color: {report_tone_color(t, tone)}; font-size: {TH.TYPE['body']}px; font-weight: 600;"
        "background: transparent; border: none;")
    line.addWidget(right, 1)
    return holder


def report_note(t: dict, text: str, tone: str = "") -> QLabel:
    """A FULL-WIDTH line. Findings and explanations are sentences, not
    label/value pairs — running them through report_row indents every one
    of them past an empty label column."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"color: {report_tone_color(t, tone)}; font-size: {TH.TYPE['body']}px; font-weight: 600;"
        "background: transparent; border: none;")
    return label


class ReportSubCard(QFrame):
    """One subject inside a read-only report — a titled, padded block with
    an optional verdict badge on its title row (v1.0).

    Exists because the reports had no structure below the dialog itself:
    Windows, Office and the licensing service were three separate subjects
    rendered as one uninterrupted column of rows, and a reader had to
    reconstruct the boundaries from the headings alone. Each subject now
    owns a surface, so "which of these facts belong together" is answered
    by the layout instead of by careful reading.

    Padding and spacing come from TH.SPACE, and the title row is a header
    (title + badge) sitting ABOVE full-width content — the same anatomy
    GlassCard uses, and for the same reason: a badge beside the content
    steals the width that the explanation sentences need.
    """

    def __init__(self, t: dict, accent: str, title: str,
                 badge: tuple[str, str] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._t = t
        self.setStyleSheet(TH.report_subcard_qss(t, accent))

        outer = QVBoxLayout(self)
        row_padding(outer)
        outer.setSpacing(TH.SPACE["sm"])

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(TH.SPACE["sm"])
        caption = QLabel(title)
        caption.setWordWrap(True)
        caption.setStyleSheet(TH.report_subcard_title_qss(t))
        head.addWidget(caption, 1)
        if badge is not None:
            text, tone = badge
            pill = QLabel(text)
            pill.setStyleSheet(TH.report_badge_qss(t, report_tone_color(t, tone)))
            head.addWidget(pill, 0, Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(head)

        #: Rows go here rather than into `outer`, so the title row keeps its
        #: own breathing room while the body stays tight.
        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(TH.SPACE["xs"])
        outer.addLayout(self._body)

    def add(self, widget: QWidget) -> "ReportSubCard":
        """Returns self so a caller can chain a block of rows in one
        expression — the render methods below then read as a description of
        the card rather than as a sequence of statements."""
        self._body.addWidget(widget)
        return self

    def row(self, label: str, value: str, tone: str = "",
            label_width: int = 150) -> "ReportSubCard":
        return self.add(report_row(self._t, label, value, tone, label_width))

    def note(self, text: str, tone: str = "") -> "ReportSubCard":
        return self.add(report_note(self._t, text, tone))


class HealthReportDialog(PulseDialog):
    """The Health & Drift Report (v10.3): run the probe, read it, export it.

    Runs its own PowerShellTask rather than borrowing the main window's,
    for the same reason StartupManagerDialog and UpdateCenterDialog do —
    it is a self-contained panel that never hands anything back, so
    entangling it with the shell's single-task pipeline would let opening
    a read-only report block a real operation.

    Export writes a self-contained HTML file (client deliverable) or the
    raw JSON (diffable between two runs). Both come from
    frontend.health_report, which is pure and tested separately.
    """

    def __init__(self, parent: QWidget, ps1_path: str, t: dict):
        super().__init__(parent)
        self._t = t
        self._ps1 = ps1_path
        self._report: dict | None = None
        self._thread: QThread | None = None
        self._worker: PowerShellTask | None = None

        accent = TH.resolve_accent(t, "automation")
        self._accent = accent
        panel = _dialog_chrome(self, t, accent, responsive=True)

        lay = dialog_body(panel, "md")

        head = QLabel("🩺  Health & Drift Report")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        lay.addWidget(head)

        self._status = QLabel("Reading system state…")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._status)

        self._scroll = FitScroll()
        self._scroll.setStyleSheet(TH.scroll_area_qss(t))
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self._host_lay = scroll_host_layout(self._host, "md")
        self._host_lay.addStretch()
        self._scroll.setWidget(self._host)
        lay.addWidget(self._scroll, 1)

        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close")
        size_dialog_button(close)
        close.setStyleSheet(TH.dialog_cancel_qss(t))
        close.clicked.connect(self.reject)
        row.addWidget(close)

        self._json_btn = QPushButton("Export JSON")
        size_dialog_button(self._json_btn)
        self._json_btn.setStyleSheet(TH.dialog_cancel_qss(t))
        self._json_btn.setEnabled(False)
        self._json_btn.clicked.connect(lambda: self._export("json"))
        row.addWidget(self._json_btn)

        self._html_btn = QPushButton("Export HTML")
        size_dialog_button(self._html_btn)
        self._html_btn.setStyleSheet(TH.dialog_go_qss(t, accent))
        self._html_btn.setEnabled(False)
        self._html_btn.clicked.connect(lambda: self._export("html"))
        row.addWidget(self._html_btn)
        lay.addLayout(row)

        QTimer.singleShot(0, self._start)

    # -- data -------------------------------------------------
    def _start(self):
        if not self._ps1:
            self._status.setText("Engine unavailable — core.ps1 was not found.")
            return
        thread = QThread(self)
        worker = PowerShellTask(self._ps1, "HealthReport", timeout=180)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_report)
        worker.failed.connect(self._on_failed)
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
        thread.finished.connect(self._cleanup)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_report(self, result: TaskResult):
        if not result.success or not isinstance(result.data, dict):
            self._on_failed(result.message or "The report could not be read.")
            return
        self._report = result.data
        self._render(result.data)
        self._json_btn.setEnabled(True)
        self._html_btn.setEnabled(True)

    def _on_failed(self, message: str):
        self._status.setText(f"Could not generate the report: {message}")

    def _cleanup(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    # -- rendering --------------------------------------------
    #: Wider than the activation report's column: this report's label
    #: vocabulary runs to "Operating system" and "Configuration drift"
    #: entries, which wrap at the narrower width.
    _LABEL_W = 200

    def _card(self, title: str, badge: tuple[str, str] | None = None) -> ReportSubCard:
        card = ReportSubCard(self._t, self._accent, title, badge)
        self._add(card)
        return card

    def _render(self, report: dict):
        from frontend.health_report import findings, tweak_rows

        summary = report.get("tweakSummary") or {}
        self._status.setText(
            f"{report.get('hostname', 'this machine')} · "
            f"{summary.get('applied', 0)} applied · "
            f"{summary.get('notApplied', 0)} not applied · "
            f"{summary.get('unknown', 0)} unknown")

        # Findings lead, and carry the report's verdict in their badge —
        # "is anything wrong here" is the question this dialog is opened
        # to answer, and it is now answerable without reading a line.
        found = findings(report)
        card = self._card(
            "Findings",
            (f"{len(found)} to review", "warn") if found else ("All clear", "ok"))
        if found:
            for line in found:
                card.note(f"•  {line}", "warn")
        else:
            card.note("•  Nothing needing attention.", "ok")

        system = report.get("system") or {}
        if system:
            self._card("System") \
                .row("Operating system",
                     f"{system.get('os')} (build {system.get('build')})",
                     label_width=self._LABEL_W) \
                .row("Processor", str(system.get("cpu")), label_width=self._LABEL_W) \
                .row("Memory",
                     f"{system.get('freeRAMGB')} GB free of "
                     f"{system.get('totalRAMGB')} GB", label_width=self._LABEL_W) \
                .row("Power plan", str(system.get("powerPlan")),
                     label_width=self._LABEL_W)

        drives = report.get("drives") or []
        if drives:
            card = self._card("Storage")
            for drive in drives:
                percent = drive.get("percentFree", 100)
                tone = "err" if isinstance(percent, (int, float)) and percent < 10 else ""
                card.row(f"Drive {drive.get('name')}",
                         f"{drive.get('freeGB')} GB free of "
                         f"{drive.get('totalGB')} GB ({percent}%)",
                         tone, label_width=self._LABEL_W)

        rows = tweak_rows(report)
        applied = sum(1 for _label, state, _task in rows if state == "applied")
        card = self._card("Configuration drift",
                          (f"{applied} of {len(rows)} applied", "") if rows else None)
        for label, state, _task in rows:
            tone = {"applied": "ok", "not-applied": "err"}.get(state, "")
            shown = {"applied": "Applied", "not-applied": "Not applied",
                     "unknown": "Unknown"}[state]
            card.row(label, shown, tone, label_width=self._LABEL_W)

    def _add(self, widget: QWidget):
        self._host_lay.insertWidget(self._host_lay.count() - 1, widget)

    # -- export -----------------------------------------------
    def _export(self, kind: str):
        from frontend.health_report import to_html, to_json

        if not self._report:
            return
        stamp = time.strftime("%Y%m%d_%H%M")
        default = os.path.join(resources.desktop_dir(),
                               f"Pulse_HealthReport_{stamp}.{kind}")
        filters = {"html": "HTML report (*.html)", "json": "JSON data (*.json)"}
        path, _chosen = QFileDialog.getSaveFileName(
            self, f"Export {kind.upper()} report", default, filters[kind])
        if not path:
            return
        try:
            payload = to_html(self._report) if kind == "html" else to_json(self._report)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except OSError as exc:
            self._status.setText(f"Could not write the file: {exc}")
            return
        self._status.setText(f"Exported to {path}")

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)

    def reject(self):
        if self._worker is not None:
            self._worker.cancel()
        super().reject()


class ActivationStatusDialog(PulseDialog):
    """Windows & Office licence status — a read-only report.

    Runs its own PowerShellTask for the same reason HealthReportDialog and
    StartupManagerDialog do: it is a self-contained panel that hands
    nothing back, so entangling it with the shell's single-task pipeline
    would let opening a read-only report block a real operation.

    SCOPE, deliberately: this dialog REPORTS. Neither it nor
    13-Activation.ps1 behind it installs a product key, contacts a
    licensing server, or alters licence state in any way — which is also
    why it needs no elevation and no confirm step. When something does
    need changing it hands off to Windows' own Activation page, where the
    user sees and controls exactly what happens.
    """

    #: Windows' own activation page. A URI scheme, not a process spawn —
    #: the Settings app opens visibly, in front of the user, and Pulse has
    #: no further part in whatever they do there.
    SETTINGS_URI = "ms-settings:activation"

    #: Microsoft's own activation documentation — the single external
    #: reference this dialog offers (v11).
    #:
    #: It replaces two blocks that used to close the report: a set of
    #: copyable `slmgr` commands and three paragraphs of hand-written
    #: activation advice. Both were well-intentioned and both were the wrong
    #: shape for this dialog. The commands invited a reader to open a
    #: terminal to re-read facts the dialog had just shown them, and the
    #: advice was a snapshot of Microsoft's licensing rules maintained here,
    #: in a Windows utility, where it can only drift out of date. One
    #: authoritative link is smaller, always current, and honest about whose
    #: answer it is.
    #:
    #: It points at Microsoft. A licence is bought or already owned and then
    #: applied through Microsoft's surfaces; Pulse reports state and hands
    #: off, and that contract does not survive linking anywhere else.
    DOCS_URL = ("https://support.microsoft.com/windows/"
                "activate-windows-c39005d4-95ee-b91e-b399-2820fda32227")

    def __init__(self, parent: QWidget, ps1_path: str, t: dict):
        super().__init__(parent)
        self._t = t
        self._ps1 = ps1_path
        self._thread: QThread | None = None
        self._worker: PowerShellTask | None = None

        accent = TH.resolve_accent(t, "information")
        self._accent = accent
        panel = _dialog_chrome(self, t, accent, responsive=True)

        lay = dialog_body(panel)

        # The title carries the scope. The dialog covers two products, and
        # a bare "Activation Status" left a reader to discover the Office
        # half by scrolling to it.
        head = QLabel("🔑  Activation Status — Windows & Office")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        head.setWordWrap(True)
        lay.addWidget(head)

        self._status = QLabel("Reading the licensing service…")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._status)

        self._scroll = FitScroll()
        self._scroll.setStyleSheet(TH.scroll_area_qss(t))
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        # Sub-cards are separated blocks, not stacked rows — they take the
        # gutter step, not the row step.
        self._host_lay = scroll_host_layout(self._host, "md")
        self._host_lay.addStretch()
        self._scroll.setWidget(self._host)
        lay.addWidget(self._scroll, 1)

        # -- action bar ---------------------------------------
        # One hand-off, and it changes nothing Pulse controls: this dialog
        # REPORTS, so its only action opens Windows' own Activation page and
        # steps back. The Re-check and Close controls sit beside it.
        row = QHBoxLayout()
        row.setSpacing(TH.SPACE["sm"])
        row.addStretch()
        for widget in self._action_buttons(t, accent):
            row.addWidget(widget)
        lay.addLayout(row)

        QTimer.singleShot(0, self._start)

    def _action_buttons(self, t: dict, accent: str) -> list[QPushButton]:
        """Built in one place so every button in the bar gets the same
        height, cursor and sizing rule. Widths are natural (a minimum plus
        the label) rather than fixed."""
        def button(text: str, style: str, slot, minimum: int) -> QPushButton:
            btn = QPushButton(text)
            btn.setFixedHeight(TH.CONTROL_H)
            btn.setMinimumWidth(minimum)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred,
                              QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(style)
            btn.clicked.connect(slot)
            return btn

        close = button("Close", TH.dialog_cancel_qss(t), self.reject, 88)

        # The one external reference, and a quieter CTA than the Settings
        # hand-off beside it: reading the documentation is the optional step,
        # opening Activation is the one that actually changes anything.
        docs = button("Official Activation Docs",
                      TH.dialog_secondary_go_qss(t, accent), self._open_docs, 190)
        docs.setToolTip(
            "Opens Microsoft's activation documentation in your browser.")

        windows = button("Windows Activation Settings",
                         TH.dialog_go_qss(t, accent), self._open_settings, 200)
        windows.setToolTip(
            "Opens Settings › System › Activation, where Windows licence "
            "state is changed.")

        return [close, docs, windows]

    # -- data -------------------------------------------------
    def _start(self):
        if not self._ps1:
            self._status.setText("Engine unavailable — core.ps1 was not found.")
            return
        if self._worker is not None:      # a read is already in flight
            return
        self._status.setText("Reading the licensing service…")
        thread = QThread(self)
        # 120s: the probe returns in about a second on a healthy machine,
        # but the licensing WMI provider can stall for a long while on one
        # with a misconfigured KMS host — the timeout exists for that, not
        # for the happy path.
        worker = PowerShellTask(self._ps1, "ActivationStatus", timeout=120)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_report)
        worker.failed.connect(self._on_failed)
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
        thread.finished.connect(self._cleanup)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_report(self, result: TaskResult):
        if not result.success or not isinstance(result.data, dict):
            self._on_failed(result.message or "The licence status could not be read.")
            return
        self._render(result.data)

    def _on_failed(self, message: str):
        self._clear()
        self._status.setText(f"Could not read activation status: {message}")

    def _cleanup(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    def _open_settings(self):
        if not QDesktopServices.openUrl(QUrl(self.SETTINGS_URI)):
            self._status.setText(
                "Windows could not open the Activation settings page. "
                "Open Settings › System › Activation manually.")

    def _open_docs(self):
        """Hand the documentation URL to the user's default browser. Same
        posture as the Settings hand-off: Pulse opens it visibly and has no
        further part in it — no embedded browser, nothing fetched here."""
        if not QDesktopServices.openUrl(QUrl(self.DOCS_URL)):
            self._status.setText(
                "Could not open your browser. The activation documentation "
                f"is at {self.DOCS_URL}")

    # -- rendering --------------------------------------------
    def _add(self, widget: QWidget):
        self._host_lay.insertWidget(self._host_lay.count() - 1, widget)

    def _clear(self):
        """Re-check replaces the report rather than appending a second copy
        of it — everything except the trailing stretch goes."""
        while self._host_lay.count() > 1:
            item = self._host_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    #: Label column inside a sub-card. Narrower than the dialog-wide 170px
    #: the flat layout used, because the sub-card's own padding already
    #: indents every row — keeping 170 here pushed values into the right
    #: third of the block and left a visible trough down the middle.
    _LABEL_W = 150

    def _card(self, title: str, badge: tuple[str, str] | None = None) -> ReportSubCard:
        card = ReportSubCard(self._t, self._accent, title, badge)
        self._add(card)
        return card

    def _product_card(self, title: str, product: dict) -> ReportSubCard:
        """One licensed product as a sub-card: the verdict badges the title
        row, the facts behind it fill the body, and the plain-English
        sentence saying what the verdict MEANS closes it."""
        tone = str(product.get("tone") or "")
        card = self._card(title, (str(product.get("status") or "Unknown"), tone))

        card.row("Licence channel", str(product.get("channel") or "Unknown"),
                 label_width=self._LABEL_W)
        partial = str(product.get("partialKey") or "")
        if partial:
            # Windows shows the same five characters in Settings. The full
            # key is never read by the backend, so it cannot be shown here.
            card.row("Product key", f"Ends in {partial}", label_width=self._LABEL_W)
        if product.get("statusCode") == 1:
            card.row("Licence type",
                     "Permanent — does not expire" if product.get("permanent")
                     else "Leased — renews automatically",
                     label_width=self._LABEL_W)
        days = product.get("remainingDays")
        if isinstance(days, int):
            # Same field, two meanings, and the label has to say which:
            # on a licensed lease it counts down to renewal, in any grace
            # state it counts down to features being restricted.
            card.row("Renews in" if product.get("statusCode") == 1
                     else "Grace period left",
                     f"{days} day(s)", label_width=self._LABEL_W)
        explanation = str(product.get("explanation") or "")
        if explanation:
            card.note(explanation, tone)
        return card

    def _render(self, report: dict):
        self._clear()
        host = str(report.get("hostname") or "this machine")
        edition = str(report.get("edition") or "Unknown edition")
        build = report.get("build")
        self._status.setText(
            f"{host} · {edition}" + (f" (build {build})" if build else ""))

        # -- Windows ------------------------------------------
        windows = report.get("windows")
        if isinstance(windows, dict):
            self._product_card("Windows", windows)
        else:
            # Still a sub-card, not a bare sentence: "we could not tell" is
            # a state of the Windows subject, and demoting it to loose text
            # would make the one case a reader most needs to notice the
            # least visible thing in the dialog.
            self._card("Windows", ("Unknown", "warn")).note(
                "The licensing service did not report a Windows licence on "
                "this machine. That is normal on some managed or evaluation "
                "images; Settings › System › Activation is authoritative.",
                "warn")

        # -- Office -------------------------------------------
        office = report.get("office")
        office = office if isinstance(office, list) else []
        install = report.get("officeInstall")
        install = install if isinstance(install, dict) else {}
        if office:
            for product in office:
                if isinstance(product, dict):
                    self._product_card(
                        str(product.get("name") or "Microsoft Office"), product)
        elif install.get("installed"):
            # The actionable case, and the reason officeInstall exists at
            # all: installed-but-unlicensed and not-installed both produce
            # an empty licence list, and they mean opposite things.
            kind = str(install.get("kind") or "")
            version = str(install.get("version") or "")
            detail = " · ".join(part for part in (kind, version) if part)
            card = self._card("Microsoft Office", ("No licence", "warn"))
            if detail:
                card.row("Installation", detail, label_width=self._LABEL_W)
            card.note(
                "Office is installed but reports no licence. An Office "
                "licence is held against the Microsoft account that owns the "
                "subscription — signing into that account in any Office app "
                "restores it. See the guide below.",
                "warn")
        else:
            self._card("Microsoft Office", ("Not installed", "")).note(
                "No Microsoft Office installation was found on this machine.")

        # -- Licensing service --------------------------------
        # Rendered only when it has something to say: on an ordinary
        # consumer PC every field here is empty, and an empty sub-card is
        # louder noise than an empty heading ever was.
        service = report.get("service")
        service = service if isinstance(service, dict) else {}
        kms = str(service.get("kmsHost") or "")
        firmware = service.get("firmwareKeyPresent")
        if kms or firmware is not None:
            card = self._card("Licensing service")
            if kms:
                card.row("KMS host", kms, label_width=self._LABEL_W)
            if firmware is True:
                edition_name = str(service.get("firmwareKeyEdition") or "")
                card.row("OEM firmware licence",
                         f"Present{f' ({edition_name})' if edition_name else ''}",
                         "ok", label_width=self._LABEL_W)
            elif firmware is False:
                card.row("OEM firmware licence", "Not present",
                         label_width=self._LABEL_W)

        # v11: the report ENDS with the facts. The two static blocks that
        # used to trail it — copyable `slmgr` commands and a hand-written
        # explanation of how activation works — are gone, and the reader is
        # pointed at Microsoft's own documentation from the action bar
        # instead (see DOCS_URL). A read-only report should stop when it
        # runs out of things it actually measured.

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)

    def reject(self):
        if self._worker is not None:
            self._worker.cancel()
        super().reject()


# ============================================================
#  READ-ONLY INSPECTORS (v1.0+ Phase 1)
# ============================================================
def _system32(name: str) -> str:
    """Absolute path to a stock Windows tool under System32.

    The Python-side twin of the backend's Get-SystemBinary, and it exists
    for the identical reason: a bare `explorer.exe` handed to QProcess is
    a $env:PATH SEARCH, and PATH is assembled from HKCU, which an
    unelevated user controls. Pulse can be running elevated. Anchoring the
    path removes the hijack; see tests/test_contract.py's PATH contract,
    which guards the PowerShell half of the same rule.
    """
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", name)


class InspectorDialog(PulseDialog):
    """Shared shell for the read-only inspectors — Power Health, Restore
    Points, Storage Analyzer.

    Each runs its OWN PowerShellTask rather than going through main.py's
    single-task pipeline, for the reason ActivationStatusDialog documents:
    a self-contained panel that hands nothing back must not be able to
    block a real operation just by being open.

    WHAT THE BASE PROVIDES is the READ half: run one backend task, take
    its DATA document, render it, and offer a re-check. Subclasses supply
    a task name, a title and a `_render`.

    THE THREE INSPECTORS THEMSELVES ARE READ-ONLY — that is a property of
    Power Health, Restore Points and Storage Analyzer, not of this class.
    Each reads, renders and stops; where an action genuinely belongs
    (open Explorer, run System Restore) they hand off to the Windows
    surface that owns it, visibly, and take no further part.
    tests/test_contract.py asserts that of the modules behind them.

    DnsSwitcherDialog also builds on this, and it DOES mutate. It is not
    a violation of the above: what it inherits is the scan-and-render
    plumbing, and its own changes are elevated, per-adapter and paired
    with a restore. A subclass that mutates owes the user an undo.
    """

    #: Subclasses override. `TASK` must be allow-listed in
    #: tests/test_contract.py::_PROGRAMMATIC (it is reached from here, not
    #: from a card's `task`) unless the card declares it directly.
    TASK = ""
    TITLE = ""
    LOADING = "Reading…"
    ACCENT_KEY = "information"
    TIMEOUT = 120
    _LABEL_W = 150

    def __init__(self, parent: QWidget, ps1_path: str, t: dict):
        super().__init__(parent)
        self._t = t
        self._ps1 = ps1_path
        self._thread: QThread | None = None
        self._worker: PowerShellTask | None = None

        accent = TH.resolve_accent(t, self.ACCENT_KEY)
        self._accent = accent
        panel = _dialog_chrome(self, t, accent, responsive=True)
        lay = dialog_body(panel)

        head = QLabel(self.TITLE)
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        head.setWordWrap(True)
        lay.addWidget(head)

        self._status = QLabel(self.LOADING)
        self._status.setWordWrap(True)
        self._status.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._status)

        self.build_controls(lay, t, accent)

        self._scroll = FitScroll()
        self._scroll.setStyleSheet(TH.scroll_area_qss(t))
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self._host_lay = scroll_host_layout(self._host, "md")
        self._host_lay.addStretch()
        self._scroll.setWidget(self._host)
        lay.addWidget(self._scroll, 1)

        row = QHBoxLayout()
        row.setSpacing(TH.SPACE["sm"])
        row.addStretch()
        for widget in self.action_buttons(t, accent):
            row.addWidget(widget)
        lay.addLayout(row)

        QTimer.singleShot(0, self._start)

    # -- subclass hooks -------------------------------------------
    def build_controls(self, lay: QVBoxLayout, t: dict, accent: str):
        """Optional controls between the status line and the report body
        (the Storage Analyzer's drive picker). Default: nothing."""

    def action_buttons(self, t: dict, accent: str) -> list[QPushButton]:
        return [self._button("Close", TH.dialog_cancel_qss(t), self.reject)]

    def _render(self, report: dict):
        raise NotImplementedError

    def task_arguments(self) -> dict:
        """Extra PowerShellTask kwargs (the Storage Analyzer's scan path)."""
        return {}

    # -- shared plumbing ------------------------------------------
    def _button(self, text: str, style: str, slot) -> QPushButton:
        """An inspector's action button.

        `minimum` used to be a parameter, passed as 88, 110, 120 or 150 at
        fourteen call sites — the same per-button pixel count that
        size_dialog_button deletes everywhere else, carried here through a
        function signature instead of written at each button. 88 also put
        the inspectors' Close buttons under the app's own footer floor, so
        the three read-only panels were the one family whose Close was
        visibly narrower than every other dialog's.
        """
        btn = QPushButton(text)
        size_dialog_button(btn)
        btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(style)
        btn.clicked.connect(slot)
        return btn

    def _start(self):
        if not self._ps1:
            self._status.setText("Engine unavailable — core.ps1 was not found.")
            return
        if self._worker is not None:      # a read is already in flight
            return
        self._status.setText(self.LOADING)
        thread = QThread(self)
        worker = PowerShellTask(self._ps1, self.TASK, timeout=self.TIMEOUT,
                                **self.task_arguments())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_report)
        worker.failed.connect(self._on_failed)
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
        thread.finished.connect(self._cleanup)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_report(self, result: TaskResult):
        if not result.success or not isinstance(result.data, dict):
            self._on_failed(result.message or "The report could not be read.")
            return
        self._clear()
        self._render(result.data)

    def _on_failed(self, message: str):
        self._clear()
        self._status.setText(message)

    def _cleanup(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    def _add(self, widget: QWidget):
        self._host_lay.insertWidget(self._host_lay.count() - 1, widget)

    def _clear(self):
        """A re-read REPLACES the report rather than appending a second
        copy of it — everything except the trailing stretch goes."""
        while self._host_lay.count() > 1:
            item = self._host_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _card(self, title: str, badge: tuple[str, str] | None = None) -> ReportSubCard:
        card = ReportSubCard(self._t, self._accent, title, badge)
        self._add(card)
        return card

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)

    def reject(self):
        # A scan in flight is killed rather than orphaned: the Storage
        # Analyzer can be walking a whole drive, and a closed dialog whose
        # PowerShell keeps churning is a background process the user has
        # no surface left to stop.
        if self._worker is not None:
            self._worker.cancel()
        super().reject()


class PowerHealthDialog(InspectorDialog):
    """F1 — battery wear, cycle count and the active power plan.

    Windows already computes every number here; it buries them in a
    `powercfg /batteryreport` HTML file nobody generates. The practical
    result is that people discover their battery holds 62% of its design
    capacity when it dies, rather than while it is still worth planning
    around. This is that number, on demand, with no file written.
    """

    TASK = "PowerHealth"
    TITLE = "🔋  Battery & Power Health"
    LOADING = "Reading battery and power state…"
    ACCENT_KEY = "information"

    #: Windows' own Power & Sleep page — the hand-off for anything that
    #: needs changing. Same posture as ActivationStatusDialog: report here,
    #: change it in the surface that owns it.
    SETTINGS_URI = "ms-settings:powersleep"

    def action_buttons(self, t: dict, accent: str) -> list[QPushButton]:
        return [
            self._button("Close", TH.dialog_cancel_qss(t), self.reject),
            self._button("Re-check", TH.dialog_secondary_go_qss(t, accent),
                         self._start),
            self._button("Power & Sleep Settings", TH.dialog_go_qss(t, accent),
                         self._open_settings),
        ]

    def _open_settings(self):
        if not QDesktopServices.openUrl(QUrl(self.SETTINGS_URI)):
            self._status.setText(
                "Windows could not open the Power & Sleep page. "
                "Open Settings › System › Power manually.")

    @staticmethod
    def _wear_tone(wear: float) -> str:
        """Wear thresholds, named once. 20% is where a battery's runtime
        drop becomes obvious in daily use; 40% is where most vendors
        consider a cell end-of-life."""
        if wear >= 40:
            return "err"
        if wear >= 20:
            return "warn"
        return "ok"

    def _render(self, report: dict):
        battery = report.get("battery") or {}
        power = report.get("power") or {}

        if not battery.get("installed"):
            self._status.setText(
                "No battery is installed — the power plan section still "
                "applies.")
            card = self._card("Battery")
            card.note(str(battery.get("note")
                          or "No battery detected on this machine."))
        else:
            wear = battery.get("wearPercent")
            if wear is None:
                badge = ("UNKNOWN", "")
                self._status.setText(
                    "A battery is present, but this firmware does not report "
                    "its design capacity, so wear cannot be calculated.")
            else:
                health = round(100 - float(wear), 1)
                badge = (f"{health}% HEALTH", self._wear_tone(float(wear)))
                self._status.setText(
                    f"This battery holds {health}% of the capacity it "
                    f"shipped with ({wear}% wear).")
            card = self._card("Battery", badge)

            design = battery.get("designedCapacity")
            full = battery.get("fullCapacity")
            card.row("Design capacity",
                     f"{int(design):,} mWh" if design else "Not reported",
                     label_width=self._LABEL_W)
            card.row("Full-charge capacity",
                     f"{int(full):,} mWh" if full else "Not reported",
                     label_width=self._LABEL_W)
            cycles = battery.get("cycleCount")
            card.row("Cycle count",
                     str(cycles) if cycles else "Not reported by this firmware",
                     label_width=self._LABEL_W)
            charge = battery.get("chargePercent")
            if charge is not None:
                card.row("Current charge", f"{charge}%", label_width=self._LABEL_W)
            on_ac = battery.get("onAcPower")
            if on_ac is not None:
                card.row("Power source", "AC adapter" if on_ac else "Battery",
                         label_width=self._LABEL_W)
            if cycles is None:
                card.note("Cycle count is optional in the battery firmware "
                          "specification — plenty of otherwise healthy "
                          "laptops simply do not publish it.")

        plan_card = self._card("Power plan")
        if power.get("available"):
            plan_card.row("Active plan", str(power.get("activeName") or "Unknown"),
                          label_width=self._LABEL_W)
            plan_card.row("Plans available", str(power.get("planCount") or 0),
                          label_width=self._LABEL_W)
        else:
            plan_card.note("Windows did not return the power plan list on "
                           "this machine.")
        hibernate = report.get("hibernateEnabled")
        if hibernate is not None:
            plan_card.row("Hibernation", "Enabled" if hibernate else "Disabled",
                          label_width=self._LABEL_W)


class RestorePointDialog(InspectorDialog):
    """F3 — every System Restore checkpoint on this PC.

    Pulse creates restore points and describes them as the safety net its
    destructive actions lean on. It had no way to show that any exist. A
    guarantee with no receipt is not a guarantee; this is the receipt.

    READ-ONLY, and the rollback is deliberately NOT implemented here. A
    System Restore is a reboot-time operation with its own Microsoft-signed
    wizard; reimplementing that inside a third-party utility would be both
    worse and less trustworthy than launching it. Pulse lists what exists
    and opens rstrui.exe.
    """

    TASK = "RestorePoints"
    TITLE = "🛡️  Restore Point Browser"
    LOADING = "Reading System Restore checkpoints…"
    ACCENT_KEY = "maintenance"

    #: Cap on rendered rows. A machine with automatic checkpoints on can
    #: hold dozens; past the newest handful they stop informing the
    #: question this dialog answers ("do I have a recent safety net?").
    MAX_ROWS = 25

    def action_buttons(self, t: dict, accent: str) -> list[QPushButton]:
        return [
            self._button("Close", TH.dialog_cancel_qss(t), self.reject),
            self._button("Re-check", TH.dialog_secondary_go_qss(t, accent),
                         self._start),
            self._button("Open System Restore", TH.dialog_go_qss(t, accent),
                         self._open_restore),
        ]

    def _open_restore(self):
        """Hand off to Windows' own System Restore wizard — anchored, never
        a PATH search (see _system32)."""
        target = _system32("rstrui.exe")
        if not os.path.isfile(target):
            self._status.setText(
                "System Restore (rstrui.exe) was not found on this machine.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(target)):
            self._status.setText(
                "Could not launch System Restore. Open it from Control Panel › "
                "Recovery › Open System Restore.")

    def _render(self, report: dict):
        enabled = report.get("enabled")
        points = report.get("points") or []
        count = int(report.get("count") or 0)

        if not report.get("available") or count == 0:
            # The important case, and the one worth being loud about: the
            # user has been told restore points are their safety net.
            self._status.setText(
                "No restore points were found on this PC.")
            card = self._card("System Restore", ("NO CHECKPOINTS", "warn"))
            if enabled is False:
                card.note("System Restore protection appears to be turned OFF "
                          "for this drive, which is why there are no "
                          "checkpoints. Turn it on in Control Panel › System › "
                          "System Protection.")
            elif enabled is None:
                card.note("Pulse could not read whether System Restore "
                          "protection is enabled — that setting is not "
                          "readable on this machine.")
            else:
                card.note("Protection is enabled but no checkpoint has been "
                          "created yet. Maintenance › Create Restore Point "
                          "makes one now.")
            return

        newest = points[0]
        age = newest.get("ageDays")
        # Stale is worse than absent-looking: a 400-day-old checkpoint that
        # a user believes is current is the failure mode worth flagging.
        tone = "ok" if (age is not None and age <= 30) else "warn"
        self._status.setText(
            f"{count} restore point(s) available. The newest is "
            f"{age} day(s) old." if age is not None
            else f"{count} restore point(s) available.")

        summary = self._card("Summary", (f"{count} CHECKPOINTS", tone))
        summary.row("Newest checkpoint", str(newest.get("description") or "Unknown"),
                    label_width=self._LABEL_W)
        summary.row("Created", str(newest.get("created") or "Unknown"),
                    label_width=self._LABEL_W)
        summary.row("Protection",
                    {True: "Enabled", False: "Disabled"}.get(enabled, "Unknown"),
                    label_width=self._LABEL_W)

        listing = self._card("All checkpoints")
        for point in points[: self.MAX_ROWS]:
            created = str(point.get("created") or "date unknown")
            label = f"{created}  ·  {point.get('typeLabel') or 'Checkpoint'}"
            listing.row(label, str(point.get("description") or ""),
                        label_width=210)
        if count > self.MAX_ROWS:
            listing.note(f"Showing the {self.MAX_ROWS} newest of {count} "
                         "checkpoints.")


class StorageAnalyzerDialog(InspectorDialog):
    """F2 — what is actually filling a drive.

    STRICTLY READ-ONLY, and that is a product decision, not a limitation.
    This finds the space; it does not delete. A bulk file remover driven
    by a size-sorted list is how an irreplaceable folder gets destroyed by
    one mis-click, and Windows already ships a file manager with undo, a
    Recycle Bin and a confirmation step. Every row hands its path to
    Explorer instead. Finding the 40GB nobody could account for is the
    entire value here; the deletion is the easy part and the dangerous one.
    """

    TASK = "StorageScan"
    TITLE = "🔭  Storage Analyzer"
    LOADING = "Scanning… this can take a minute on a large drive."
    ACCENT_KEY = "maintenance"
    #: Generous: the backend's own time budget stops the scan long before
    #: this, so a timeout here would mean something genuinely wedged.
    TIMEOUT = 900

    def __init__(self, parent: QWidget, ps1_path: str, t: dict):
        self._scan_path = os.environ.get("SystemDrive", "C:") + "\\"
        self._roots: list[dict] = []
        super().__init__(parent, ps1_path, t)

    def action_buttons(self, t: dict, accent: str) -> list[QPushButton]:
        return [
            self._button("Close", TH.dialog_cancel_qss(t), self.reject),
            self._button("Scan a Folder…", TH.dialog_secondary_go_qss(t, accent),
                         self._choose_folder),
            self._button("Re-scan", TH.dialog_go_qss(t, accent), self._start),
        ]

    def _choose_folder(self):
        """Scan one folder instead of a whole drive.

        The precision escape hatch for the time budget: a whole-drive walk
        can truncate, but "why is my Downloads folder 90GB" is answerable
        exactly and in seconds. Still read-only — picking a folder chooses
        what to MEASURE, nothing more."""
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose a folder to analyse", self._scan_path)
        if not chosen:
            return
        self._scan_path = os.path.normpath(chosen)
        self._start()

    def build_controls(self, lay: QVBoxLayout, t: dict, accent: str):
        row = QHBoxLayout()
        row.setSpacing(TH.SPACE["sm"])
        label = QLabel("Drive")
        label.setStyleSheet(TH.label_qss(t, "caption"))
        row.addWidget(label)

        self._drive = QComboBox()
        self._drive.setFixedSize(220, TH.CONTROL_H)
        self._drive.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drive.setStyleSheet(TH.filter_combo_qss(t, accent))
        self._drive.addItem(self._scan_path, self._scan_path)
        self._drive.currentIndexChanged.connect(self._on_drive_changed)
        row.addWidget(self._drive)
        row.addStretch()
        lay.addLayout(row)

    def task_arguments(self) -> dict:
        return {"scan_path": self._scan_path}

    def _on_drive_changed(self, _index: int):
        target = self._drive.currentData()
        if not target or target == self._scan_path:
            return
        self._scan_path = target
        # A drive change is a new question, so it re-scans rather than
        # re-filtering a stale result set for a drive the user left.
        self._start()

    @staticmethod
    def _human(size: float) -> str:
        value = float(size or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:,.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{value:,.1f} TB"

    def _reveal(self, path: str):
        """Show a path in Explorer. `/select,` highlights the item inside
        its parent folder rather than opening it, which is what makes this
        safe for a FILE: the user lands on it, sees its neighbours, and
        decides — Pulse never opens or runs anything."""
        target = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows",
                              "explorer.exe")
        try:
            QProcess.startDetached(target, ["/select,", os.path.normpath(path)])
        except Exception:
            self._status.setText(f"Could not open Explorer for {path}")

    def _row_with_reveal(self, card: ReportSubCard, label: str, value: str,
                         path: str):
        line = QWidget()
        line.setStyleSheet("background: transparent;")
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(TH.SPACE["sm"])

        name = ElidedCaption()
        name.setFullText(label)
        name.setStyleSheet(TH.label_qss(self._t, "body"))
        row.addWidget(name, 1)

        size = QLabel(value)
        size.setStyleSheet(TH.label_qss(self._t, "caption"))
        size.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        size.setFixedWidth(96)
        row.addWidget(size)

        reveal = QPushButton("Reveal")
        reveal.setFixedSize(74, 26)
        reveal.setCursor(Qt.CursorShape.PointingHandCursor)
        reveal.setStyleSheet(TH.link_button_qss(self._t, self._accent))
        reveal.setToolTip(f"Show {path} in File Explorer")
        reveal.clicked.connect(lambda _c=False, p=path: self._reveal(p))
        row.addWidget(reveal)

        card.add(line)

    def _sync_drives(self, roots: list[dict]):
        """Populate the picker from the drives the scan actually found —
        once. Rebuilding it on every scan would fire currentIndexChanged
        mid-render and start a second scan."""
        if self._roots or not roots:
            return
        self._roots = roots
        self._drive.blockSignals(True)
        self._drive.clear()
        for root in roots:
            path = str(root.get("path") or "")
            free = self._human(root.get("freeBytes") or 0)
            total = self._human(root.get("totalBytes") or 0)
            label = str(root.get("label") or "").strip()
            text = f"{path}  {label}" if label else path
            self._drive.addItem(f"{text}   ({free} free of {total})", path)
        index = self._drive.findData(self._scan_path)
        self._drive.setCurrentIndex(max(0, index))
        self._drive.blockSignals(False)

    def _render(self, report: dict):
        self._sync_drives(report.get("roots") or [])

        if not report.get("available"):
            self._status.setText(
                f"Could not read {report.get('scanPath')} — it does not exist "
                "or is not readable by this account.")
            return

        total = self._human(report.get("totalBytes") or 0)
        truncated = bool(report.get("truncated"))
        self._status.setText(
            f"{report.get('scanPath')} — {total} accounted for."
            + (" The scan hit its time budget, so this is a partial view of "
               "the largest items found so far." if truncated else ""))

        folders = report.get("folders") or []
        files = report.get("files") or []

        if truncated:
            partial = self._card("Partial scan", ("TIME BUDGET REACHED", "warn"))
            partial.note(
                "Large drives can take longer than the scan's budget allows. "
                "The figures below are real, but smaller items may be "
                "missing — scan a specific folder for an exact picture.")

        folder_card = self._card("Largest folders")
        if folders:
            for entry in folders:
                self._row_with_reveal(
                    folder_card, str(entry.get("name") or entry.get("path")),
                    self._human(entry.get("bytes")), str(entry.get("path") or ""))
        else:
            folder_card.note("No readable subfolders were found here.")

        file_card = self._card("Largest files")
        if files:
            for entry in files:
                modified = entry.get("modified")
                label = str(entry.get("name") or "")
                if modified:
                    label = f"{label}   ·   {modified}"
                self._row_with_reveal(
                    file_card, label, self._human(entry.get("bytes")),
                    str(entry.get("path") or ""))
        else:
            file_card.note("No readable files were found here.")

        note = self._card("About this report")
        note.note(
            "Pulse never deletes anything from this screen. Reveal opens the "
            "item in File Explorer, where Windows' own delete, undo and "
            "Recycle Bin apply.")


class DnsSwitcherDialog(InspectorDialog):
    """F4 — per-adapter DNS profiles, with a one-click way back.

    Pointing a PC at Cloudflare or Quad9 is one of the few single changes
    that improves speed AND privacy at once, and by hand it is five nested
    adapter dialogs. This is that change, scoped to one connection.

    SELF-CONTAINED, like the Startup Manager: it scans, applies and
    re-scans through its own workers rather than handing a selection back
    to main.py's pipeline. A DNS switch is a per-row action on a live
    list, not a batch the shell can queue.

    EVERY PROFILE SITS BESIDE ITS UNDO. 'Automatic (DHCP)' is the first
    option on every adapter, not a footnote — a network tool that can
    strand a machine with no visible way back is a hazard, and the way
    back has to be as reachable as the way in.
    """

    TASK = "NetworkProfiles"
    TITLE = "🛰️  DNS & Network Profiles"
    LOADING = "Reading network adapters…"
    ACCENT_KEY = "optimization"
    TIMEOUT = 120

    #: The restore option, rendered as a profile like any other so it is
    #: never the odd one out at the bottom of a list.
    DHCP_KEY = "dhcp"

    def __init__(self, parent: QWidget, ps1_path: str, t: dict,
                 is_admin: bool = True):
        self._is_admin = is_admin
        self._busy = False
        self._profiles: list[dict] = []
        super().__init__(parent, ps1_path, t)

    def action_buttons(self, t: dict, accent: str) -> list[QPushButton]:
        return [
            self._button("Close", TH.dialog_cancel_qss(t), self.reject),
            self._button("Re-scan", TH.dialog_secondary_go_qss(t, accent),
                         self._start),
        ]

    # -- rendering ------------------------------------------------
    def _render(self, report: dict):
        adapters = report.get("adapters") or []
        self._profiles = report.get("profiles") or []
        doh = bool(report.get("dohSupported"))

        if not adapters:
            self._status.setText("No connected network adapters were found.")
            self._card("Adapters").note(
                "Pulse lists physical adapters that are currently up. A "
                "machine on Wi-Fi with the adapter disabled, or one behind "
                "a virtual switch only, will show nothing here.")
            return

        self._status.setText(
            f"{len(adapters)} connected adapter(s). Changes apply to ONE "
            "adapter at a time and can be undone with Automatic (DHCP)."
            + ("" if doh else
               " This build of Windows cannot encrypt DNS (DoH needs "
               "Windows 11), so profiles are applied unencrypted."))

        if not self._is_admin:
            warn = self._card("Administrator required", ("NOT ELEVATED", "warn"))
            warn.note(
                "DNS lives in the adapter's machine-scope settings, so "
                "changing it needs an elevated Pulse. You can still see "
                "what each adapter is using now.")

        for adapter in adapters:
            self._adapter_card(adapter, doh)

    def _adapter_card(self, adapter: dict, doh: bool):
        name = str(adapter.get("name") or "Adapter")
        active = str(adapter.get("activeKey") or "custom")
        servers = adapter.get("v4") or []

        label = {"dhcp": "AUTOMATIC", "custom": "CUSTOM"}.get(
            active, active.upper())
        tone = "ok" if active not in ("custom",) else ""
        card = self._card(f"{name}", (label, tone))
        card.row("Adapter", str(adapter.get("description") or ""),
                 label_width=self._LABEL_W)
        card.row("Current DNS",
                 ", ".join(servers) if servers
                 else "Automatic (provided by your router)",
                 label_width=self._LABEL_W)

        # One row of choices per adapter. Automatic comes FIRST — see the
        # class docstring; the undo is not a footnote.
        strip, row = _chip_strip(self._t)
        row.addWidget(self._profile_button(
            name, self.DHCP_KEY, "Automatic (DHCP)", active == self.DHCP_KEY))
        for profile in self._profiles:
            key = str(profile.get("key"))
            row.addWidget(self._profile_button(
                name, key, str(profile.get("name") or key), active == key))
        row.addStretch()
        card.add(strip)

        note = next((p.get("note") for p in self._profiles
                     if p.get("key") == active), None)
        if note:
            card.note(str(note))

    def _profile_button(self, adapter: str, key: str, label: str,
                        current: bool) -> QPushButton:
        btn = QPushButton(label.replace("&", "&&"))
        btn.setFixedHeight(_CHIP_H)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(TH.catalog_tab_qss(self._t, self._accent, current))
        # The active profile is shown as the selected pill and does
        # nothing when clicked: re-applying what is already set would run
        # an elevated task to achieve no change.
        btn.setEnabled(self._is_admin and not current and not self._busy)
        if current:
            btn.setToolTip("This adapter is already using this profile.")
        elif not self._is_admin:
            btn.setToolTip("Changing DNS needs an elevated Pulse.")
        btn.clicked.connect(
            lambda _c=False, a=adapter, k=key: self._apply(a, k))
        return btn

    # -- mutation -------------------------------------------------
    def _apply(self, adapter: str, key: str):
        """Apply one profile to one adapter, then re-scan so the card
        reflects what the machine actually reports rather than what was
        requested — the two differ whenever a driver rejects a change."""
        if self._busy or self._worker is not None:
            return
        self._busy = True
        restoring = key == self.DHCP_KEY
        self._status.setText(
            f"Restoring automatic DNS on {adapter}…" if restoring
            else f"Applying {key} to {adapter}…")

        thread = QThread(self)
        worker = PowerShellTask(
            self._ps1, "RestoreDns" if restoring else "SetDnsProfile",
            timeout=120, adapter_name=adapter,
            dns_profile=None if restoring else key)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_applied)
        worker.failed.connect(self._on_apply_failed)
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
        thread.finished.connect(self._cleanup)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_applied(self, result: TaskResult):
        self._busy = False
        self._status.setText(result.message or "DNS updated.")
        # Re-scan on a beat so the worker teardown finishes first.
        QTimer.singleShot(120, self._start)

    def _on_apply_failed(self, message: str):
        self._busy = False
        self._status.setText(f"Could not change DNS: {message}")


class ContextMenuDialog(InspectorDialog):
    """F5 — every right-click entry, with the clutter switchable off.

    Windows ships no UI for this, so menus accumulate an entry from every
    installer that ever ran and there is no way to see what put them
    there. This lists them all with their owner.

    TWO SAFETY PROPERTIES, both visible in the UI rather than merely
    promised in a docstring:

    ONLY CURATED ENTRIES ARE TOGGLABLE. Everything found is listed, but a
    handler Pulse does not recognise renders greyed with its owning module
    and no switch. Shell extensions can be load-bearing — a security
    suite's scan hook, a backup tool's provider — and a manager that
    happily blocks anything it can enumerate is a way to break a machine
    subtly. Seeing the entry is useful; being offered a switch for it is
    not.

    NOTHING IS DELETED. Hiding an entry adds its CLSID to Windows' own
    block list; showing it removes that value. The extension's own
    registration is never touched, which is what makes Restore All
    complete by construction rather than best-effort.
    """

    TASK = "ContextMenuScan"
    # Matches the card's v1.1 title. The dialog and the card that opens it
    # naming the same thing differently is how a user ends up unsure which
    # of the two context-menu cards they actually clicked.
    TITLE = "🧹  Right-Click Menu Entries"
    LOADING = "Reading shell context-menu handlers…"
    ACCENT_KEY = "optimization"
    TIMEOUT = 300

    def __init__(self, parent: QWidget, ps1_path: str, t: dict,
                 is_admin: bool = True):
        self._is_admin = is_admin
        self._busy = False
        self._has_backup = False
        super().__init__(parent, ps1_path, t)

    def action_buttons(self, t: dict, accent: str) -> list[QPushButton]:
        self._restore_btn = self._button(
            "Restore All", TH.dialog_secondary_go_qss(t, accent),
            self._restore)
        self._restore_btn.setToolTip(
            "Put every context-menu entry back exactly as it was before "
            "Pulse changed anything.")
        self._restore_btn.setEnabled(False)
        return [
            self._button("Close", TH.dialog_cancel_qss(t), self.reject),
            self._restore_btn,
            self._button("Re-scan", TH.dialog_go_qss(t, accent), self._start),
        ]

    def _render(self, report: dict):
        items = report.get("items") or []
        managed = [i for i in items if i.get("managed")]
        others = [i for i in items if not i.get("managed")]
        self._has_backup = bool(report.get("hasBackup"))
        self._restore_btn.setEnabled(self._is_admin and self._has_backup)

        hidden = sum(1 for i in items if not i.get("enabled"))
        self._status.setText(
            f"{len(items)} handler(s) registered · {len(managed)} manageable · "
            f"{hidden} currently hidden."
            + ("" if self._is_admin else
               "  Changing entries needs an elevated Pulse."))

        if managed:
            card = self._card("Manageable entries",
                              (f"{len(managed)} ITEMS", ""))
            for item in managed:
                self._toggle_row(card, item)
        else:
            self._card("Manageable entries").note(
                "None of the handlers on this machine are ones Pulse "
                "manages. That is a good sign, not a failure — it means "
                "nothing recognised as safe-to-hide is installed.")

        if others:
            card = self._card("Other handlers", (f"{len(others)} ITEMS", ""))
            card.note(
                "Listed so you can see what is in your menu. Pulse does not "
                "offer to change these: a shell extension can be doing real "
                "work — a scanner hook, a sync provider — and blocking one "
                "blind is how a machine breaks in a way nobody connects "
                "back to a context menu.")
            for item in others[:40]:
                owner = str(item.get("owner") or "unknown module")
                card.row(str(item.get("label") or ""),
                         f"{item.get('scope')} · {os.path.basename(owner) if owner else ''}",
                         label_width=240)
            if len(others) > 40:
                card.note(f"Showing 40 of {len(others)}.")

    def _toggle_row(self, card: ReportSubCard, item: dict):
        line = QWidget()
        line.setStyleSheet("background: transparent;")
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(TH.SPACE["sm"])

        name = ElidedCaption()
        name.setFullText(f"{item.get('label')}   ·   {item.get('scope')}")
        name.setStyleSheet(TH.label_qss(self._t, "body"))
        row.addWidget(name, 1)

        owner = QLabel(str(item.get("owner") or ""))
        owner.setStyleSheet(TH.label_qss(self._t, "caption"))
        owner.setFixedWidth(150)
        row.addWidget(owner)

        enabled = bool(item.get("enabled"))
        btn = QPushButton("Visible" if enabled else "Hidden")
        btn.setFixedSize(88, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(TH.catalog_tab_qss(self._t, self._accent, enabled))
        btn.setEnabled(self._is_admin and not self._busy)
        btn.setToolTip(
            "Hide this entry from right-click menus." if enabled
            else "Bring this entry back.")
        btn.clicked.connect(
            lambda _c=False, c=str(item.get("clsid")), e=enabled:
            self._toggle(c, not e))
        row.addWidget(btn)
        card.add(line)

    # -- mutation -------------------------------------------------
    def _toggle(self, clsid: str, enable: bool):
        if self._busy or self._worker is not None or not clsid:
            return
        self._busy = True
        self._status.setText("Updating the context menu…")
        # "{CLSID}|||on" — the opaque single-item channel; see the
        # ContextMenuToggle dispatcher case for why -AppIds cannot carry it.
        self._run_mutation("ContextMenuToggle",
                           startup_item_id=f"{clsid}|||{'on' if enable else 'off'}")

    def _restore(self):
        if self._busy or self._worker is not None:
            return
        self._busy = True
        self._status.setText("Restoring the context menu…")
        self._run_mutation("ContextMenuRestore")

    def _run_mutation(self, task: str, **kwargs):
        thread = QThread(self)
        worker = PowerShellTask(self._ps1, task, timeout=180, **kwargs)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_changed)
        worker.failed.connect(self._on_change_failed)
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
        thread.finished.connect(self._cleanup)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_changed(self, result: TaskResult):
        self._busy = False
        self._status.setText(result.message or "Context menu updated.")
        # Re-scan so every row reflects the registry, not the request.
        QTimer.singleShot(120, self._start)

    def _on_change_failed(self, message: str):
        self._busy = False
        self._status.setText(f"Could not change the context menu: {message}")


class CloseConfirmDialog(PulseDialog):
    """Shown when the window is closed while a task is still running (v10.2).

    Closing used to cancel the task silently, which is the wrong default
    for this app: the running operation may be halfway through an MSI
    install, a driver export or an Edge purge, and "stopped halfway" is a
    materially worse state than either finished or never started. The
    close is now a question rather than an assumption.

    Deliberately NOT a generic ConfirmDialog: the buttons here are not
    Cancel/Proceed. Both options do something irreversible-ish, so each is
    named for its OUTCOME ("Keep Running" / "Stop & Close") — a user
    hitting Alt+F4 by accident must be able to tell the two apart without
    parsing the sentence above them. The safe choice is the default and
    the destructive one carries the error accent.
    """

    def __init__(self, parent: QWidget, t: dict, task_title: str = ""):
        super().__init__(parent)
        accent = t["warn"]
        # 540, not 460: the three action buttons are named for their
        # OUTCOME rather than "Yes"/"No", and their combined minimum is
        # 516px. At 460 the row was over-constrained, so Qt shrank the
        # labels below their own text and the outcome names — the entire
        # point of the dialog — came out elided.
        panel = _dialog_chrome(self, t, accent, width=540)

        lay = dialog_body(panel, "sm")

        head = QLabel("⚠️  A task is still running")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        lay.addWidget(head)

        running = task_title.strip() or "An operation"
        body = QLabel(
            f"<b>{running}</b> hasn't finished yet. Closing Pulse now stops "
            "it partway through — the change it was making may be left half "
            "applied, and you'll need to run it again.")
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(body)

        # The safe option is the default: Enter and Escape both keep the
        # task alive, so no reflexive keypress can end a long install.
        keep = QPushButton("Keep Running")
        keep.setStyleSheet(TH.dialog_cancel_qss(t))
        keep.setDefault(True)
        keep.setAutoDefault(True)
        keep.clicked.connect(self.reject)

        # "&&" is not a typo: Qt reads a single & in button text as a
        # mnemonic marker, so "Stop & Close" renders as "Stop _Close" with
        # the C underlined, which looks like a broken label. The doubled
        # ampersand is the escape that paints a literal "&".
        stop = QPushButton("Stop && Close")
        stop.setStyleSheet(TH.dialog_go_qss(t, t["err"]))
        stop.setAutoDefault(False)
        stop.clicked.connect(self.accept)

        dialog_footer(lay, keep, stop)

        self._keep_btn = keep
        self._stop_btn = stop

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)
        self._keep_btn.setFocus()


# ============================================================
#  ELEVATE PROMPT — inline "this needs Administrator" gate
# ============================================================
class ElevatePromptDialog(PulseDialog):
    """Shown when a NON-elevated Pulse is asked to run an admin-gated action
    (see menu_structure.requires_admin). Instead of spawning PowerShell only
    to bounce back an access-denied verdict, this offers a one-click UAC
    relaunch up front. Accepted => the caller runs PulseApp._relaunch_as_admin;
    rejected => nothing happens and no task is started. Amber `warn` accent
    to match the status rail's unelevated session shield (StatusRail) — a
    standing requirement, not a red failure.

    IT SURVIVES requireAdministrator ON PURPOSE. The packaged app elevates
    before it starts (main.spec), so a packaged Pulse cannot normally reach
    this dialog — but "cannot normally" is not "cannot": a developer runs
    `python src/frontend/main.py` at their own level, and a policy-
    restricted account can be denied the token outright. v15 removed the
    three REDUNDANT elevation surfaces (a full-width sidebar CTA, a
    full-width admin chip, and a pair of masthead pills, all reporting one
    fact the rail now reports once). This one is not redundant: it is the
    gate that stops an admin-gated task from being launched only to come
    back with an access-denied verdict, and nothing else performs that
    check."""

    def __init__(self, parent: QWidget, item: dict, t: dict):
        super().__init__(parent)
        accent = t["warn"]
        panel = _dialog_chrome(self, t, accent, width=470)

        lay = dialog_body(panel, "sm")

        head = QLabel("🛡  Administrator required")
        head.setStyleSheet(TH.label_qss(t, "card"))
        lay.addWidget(head)

        body = QLabel(
            f"“{item.get('title', 'This action')}” makes system-level changes "
            "that need Administrator rights. Relaunch Pulse elevated to "
            "continue — Windows will show a UAC consent prompt.")
        body.setWordWrap(True)
        body.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(body)

        cancel = QPushButton("Not now")
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)

        go = QPushButton("Relaunch as Administrator")
        go.setStyleSheet(TH.dialog_go_qss(t, accent))
        go.clicked.connect(self.accept)

        dialog_footer(lay, cancel, go)

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


# ============================================================
#  SHORTCUT SHEET — F1 / ? keyboard reference
# ============================================================
class ShortcutSheetDialog(PulseDialog):
    """The keyboard reference (F1 or ?).

    v10 added a real keyboard layer; a shortcut nobody can discover is a
    shortcut that doesn't exist, and Ctrl+K had been undiscoverable for
    exactly that reason. Rows are rendered from PulseApp.SHORTCUTS, so the
    sheet cannot drift out of sync with the bindings actually installed."""

    def __init__(self, parent: QWidget, t: dict, shortcuts: list[tuple[str, str]]):
        super().__init__(parent)
        accent = t["accent"]
        panel = _dialog_chrome(self, t, accent, width=440)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(TH.SPACE["xl"], TH.SPACE["xl"],
                               TH.SPACE["xl"], TH.SPACE["lg"])
        lay.setSpacing(TH.SPACE["md"])

        head = QLabel("Keyboard shortcuts")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        lay.addWidget(head)

        for keys, description in shortcuts:
            row = QHBoxLayout()
            row.setSpacing(TH.SPACE["md"])
            key_label = QLabel(keys)
            key_label.setStyleSheet(TH.keycap_qss(t))
            key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            key_label.setFixedWidth(120)
            row.addWidget(key_label, 0, Qt.AlignmentFlag.AlignVCenter)
            desc = QLabel(description)
            desc.setStyleSheet(TH.label_qss(t, "body"))
            row.addWidget(desc, 1)
            lay.addLayout(row)

        close = QPushButton("Close")
        close.setStyleSheet(TH.dialog_cancel_qss(t))
        close.clicked.connect(self.reject)
        dialog_footer(lay, close)

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


# ============================================================
#  HUB DIALOG — a hub card's landing screen (drill-down navigation)
# ============================================================
class HubDialog(PulseDialog):
    """A primary hub card's landing screen: its sub-actions rendered as a
    short column of ActionRows — icon, title over description, and the one
    button that runs it.

    TWO hubs remain as of v1.1, both in Software Management: Microsoft
    Edge (remove / reinstall) and Microsoft OneDrive (purge / restore /
    open the rescued files). Both exist for the same reason — a teardown
    is only safe to offer BESIDE its counterpart restore — and both are
    the 2-4 sub-action shape this dialog is tuned for.

    THE GEOMETRY IS THE v10.5 FIX. This used to be built on the SELECTOR
    band and rendered each sub-action as a full GlassCard, so a two-action
    hub opened at up to 1280 x 900: two tiles, stretched and centred, in a
    panel sized for a fourteen-card page, with several hundred pixels of
    nothing around them. Card-shaped rows made that unfixable — a GlassCard
    caps at 156px and cannot absorb a panel's worth of slack, so the
    surplus fell into the gaps whatever the layout did with it.

    The dialog now takes the ACTION band (580-640 wide, height hugging its
    content — see _apply_panel_size) and the rows are ActionRows, which
    state the same three things in a third of the height. A two-action hub
    is now a ~300px panel containing exactly two actions and nothing else.

    A hub is NOT a way to thin a busy page; section bands do that without
    costing a click. The v1.1 reorganization deleted the hub that was
    doing it ("System Tools & Utilities", whose name also collided with
    the Utilities & Tools module) and promoted its three tools onto the
    page — see menu_structure's `hub` documentation.

    Picking a sub-action closes this dialog and hands it back via
    `chosen_item`; the caller runs it through the normal request_task()
    pipeline exactly as if the row lived directly on a category page.
    """

    #: Rows past this many get a scroll area instead of growing the panel.
    #: No shipped hub reaches it — it is the ceiling that keeps a
    #: content-hugging dialog from being able to outgrow its window if one
    #: ever does, and _fit_scroll caps the viewport at the same count.
    _SCROLL_AFTER = 5

    def __init__(self, parent: QWidget, hub: dict, t: dict):
        super().__init__(parent)
        self._t = t
        self.chosen_item: dict | None = None
        accent = t["accent"]
        panel = _dialog_chrome(self, t, accent, responsive="action")

        lay = dialog_body(panel, "md")

        head = QLabel(f"{hub['icon']}  {hub['title']}")
        head.setWordWrap(True)
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        lay.addWidget(head)

        sub = QLabel(hub.get("desc", ""))
        sub.setWordWrap(True)
        sub.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(sub)

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host_lay = scroll_host_layout(host, "sm")
        rows = self._build_rows(host_lay, hub, t, accent)
        # ONE BUTTON WIDTH FOR THE WHOLE COLUMN. Each button sizes itself
        # to its own verb, so "Remove" and "Reinstall" came out 78 and 80
        # wide — a two-pixel stagger on the dialog's right edge, which is
        # precisely the "almost aligned" class of defect the layout scales
        # exist to remove. Widened to the widest rather than fixed at a
        # constant, so a long verb still fits instead of being elided.
        if rows:
            widest = max(r.button.sizeHint().width() for r in rows)
            for row in rows:
                row.button.setFixedWidth(widest)

        if len(rows) > self._SCROLL_AFTER:
            # Only a hub that outgrew the band scrolls, and then the panel
            # stops growing rather than the rows getting shorter. Below the
            # threshold the column is added DIRECTLY: a QScrollArea reports
            # a small size hint regardless of what is inside it, so wrapping
            # a two-row list in one would collapse the very content the
            # panel is meant to hug.
            scroll = FitScroll()
            scroll.setStyleSheet(TH.scroll_area_qss(t))
            scroll.setWidget(host)
            scroll.setMinimumHeight(
                host.sizeHint().height() * self._SCROLL_AFTER // len(rows))
            lay.addWidget(scroll, 1)
        else:
            lay.addWidget(host)

        close = QPushButton("Close")
        close.setStyleSheet(TH.dialog_cancel_qss(t))
        close.clicked.connect(self.reject)
        dialog_footer(lay, close)

    def _build_rows(self, host_lay: QVBoxLayout, hub: dict, t: dict,
                    accent: str) -> list["ActionRow"]:
        """Every sub-action as an ActionRow, flat or grouped.

        NO TRAILING STRETCH, and that is the whole difference from the old
        card layout. The panel now hugs its content (the ACTION band), so
        there is no surplus for a stretch to distribute — and adding one
        would hand the panel a reason to grow that its content never gave
        it, which is the defect this dialog was rebuilt to remove.
        """
        rows: list[ActionRow] = []

        def add(item: dict):
            row = ActionRow(item, t, accent, item.get("action", ""))
            row.activated.connect(lambda it=item: self._choose(it))
            host_lay.addWidget(row)
            rows.append(row)

        groups = hub.get("groups")
        if groups:
            # Grouped hub: each group opens with a header ROW — an
            # accent-tinted section title plus a 1px rule fading out to the
            # right — then its rows, tight under it and a full extra step
            # away from the previous group's last row, so the clusters read
            # at a glance.
            #
            # No hub declares `groups` as of the v1.0 RC (System Tools was
            # the last, and lost its headers when Edge and OneDrive moved
            # out to their own cards; the hub itself is gone as of v1.1).
            # The branch stays because the shape is still supported and a
            # hub can grow back into it.
            for index, group in enumerate(groups):
                if index > 0:
                    host_lay.addSpacing(TH.SPACE["md"])
                head_row = QHBoxLayout()
                head_row.setSpacing(TH.SPACE["md"])
                header = QLabel(group["title"])
                header.setStyleSheet(TH.hub_group_header_qss(t, accent))
                head_row.addWidget(header)
                rule = QFrame()
                rule.setFixedHeight(1)
                rule.setStyleSheet(TH.hub_group_rule_qss(t, accent))
                head_row.addWidget(rule, 1)
                host_lay.addLayout(head_row)
                for item in group["items"]:
                    add(item)
        else:
            for item in hub.get("items", []):
                add(item)
        return rows

    def _choose(self, item: dict):
        self.chosen_item = item
        self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


# ============================================================
#  LIVE CONSOLE — streams raw PowerShell stdout in real time
# ============================================================
#: A console line's leading "HH:MM:SS  " gutter (LiveConsole._stamp), so the
#: severity classifier below can see past it to the text the backend wrote.
_TIMESTAMP_PREFIX = re.compile(r"^\d{2}:\d{2}:\d{2}  ")

#: (marker, tone) pairs, checked in order, that recover a line's severity
#: from its TEXT — because Write-Host -ForegroundColor never survives the
#: pipe Popen reads from (see helpers.PowerShellTask._apply), the console
#: has always shown Write-Success/Write-Warn/Write-ErrorX output in one flat
#: colour regardless of what the backend reported. DRY-RUN/WHATIF must be
#: checked before SUCCESS|: a simulated run's own verdict line reads
#: "SUCCESS|[DRY-RUN] ... simulated", and it must not look like a real
#: success in the one place meant to show it wasn't.
_CONSOLE_TONE_MARKERS = (
    ("[DRY-RUN]", "warn"),
    ("[WHATIF]", "warn"),
    ("SUCCESS|", "ok"),
    (chr(0x2713), "ok"),   # Write-Success's check mark ($Script:Check)
    ("ERROR|", "err"),
    (chr(0x2717), "err"),  # Write-ErrorX's cross ($Script:Cross)
)


def _console_line_tone(text: str) -> str | None:
    """Classify one raw console line for LiveConsole's colour pass, or None
    for the console's own default text colour."""
    body = _TIMESTAMP_PREFIX.sub("", text, count=1)
    for marker, tone in _CONSOLE_TONE_MARKERS:
        if marker in body:
            return tone
    if body.strip().startswith("!  "):   # Write-Warn: "   !  $Text"
        return "warn"
    return None


class LiveConsole(QPlainTextEdit):
    """Read-only micro-terminal. `put_line()` is the slot for
    PowerShellTask.output: it appends a line, or — when the backend used a
    bare carriage return — rewrites the newest line in place, so winget
    percentages / SFC progress read exactly like a real console."""

    MAX_LINES = 2000  # bound memory on very long-running tasks (SFC/DISM)
    _EMPTY_MESSAGE = "Idle — output streams here in real time while a task runs."

    def __init__(self, t: dict, parent: QWidget | None = None,
                 timestamps: bool = True):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFont("Cascadia Mono", 9))
        self._timestamps = timestamps
        #: True when the newest line is a MARKER and must survive the next
        #: carriage-return rewrite. See append_marker.
        self._protect_last = False
        # No native placeholder text: the empty state is a custom-painted
        # "pulse" waveform motif + message (see paintEvent), not plain text.
        self.apply_theme(t)

    def apply_theme(self, t: dict):
        self.setStyleSheet(TH.console_qss(t))
        self._empty_accent = QColor(t["accent"])
        self._empty_text = QColor(t["text_faint"])
        self._default_line_color = QColor(t["text_soft"])
        self._tone_colors = {
            "ok": QColor(t["ok"]),
            "err": QColor(t["err"]),
            "warn": QColor(t["warn"]),
        }

    def set_timestamps(self, on: bool):
        """Toggle the HH:MM:SS gutter. Only affects lines written AFTER the
        change — retro-stamping existing output would invent times we never
        observed, and un-stamping would have to parse them back out of text
        that may legitimately contain a similar prefix."""
        self._timestamps = bool(on)

    def _stamp(self, text: str) -> str:
        if not self._timestamps:
            return text
        return f"{QTime.currentTime().toString('HH:mm:ss')}  {text}"

    def put_line(self, text: str, replace_last: bool = False):
        """Slot for PowerShellTask.output(text, replace_last)."""
        if replace_last and not self._protect_last and not self.document().isEmpty():
            self._replace_last_line(text)
        else:
            self.append_line(text)

    def append_marker(self, text: str):
        """Append a line that a carriage-return rewrite may NOT overwrite.

        The problem this solves is specific, and it was silent. Phase
        markers (the drawer's ##PULSE##STAGE| echo) are interleaved with a
        stream that uses bare CRs for in-place progress - winget, sfc,
        DISM. A marker appended just before a progress frame became the
        "newest line", so the frame rewrote it: the transcript held
        "Downloading Firefox 145.0..." for exactly as long as it took the
        next percentage to arrive, and every completed phase vanished from
        the exported log. Reproduced with the real sequence, only the LAST
        marker of each app survived, and only because a plain line happened
        to follow it.

        A CR rewrite means "replace what I just wrote". A marker is not
        something the stream wrote, so the rewrite has nothing here to
        replace and must start a new line instead. The flag clears on the
        next append either way, so a genuine progress sequence still
        collapses to a single line as soon as it is under way.
        """
        self.append_line(text)
        self._protect_last = True

    def append_line(self, text: str):
        self._protect_last = False
        bar = self.verticalScrollBar()
        follow = bar.value() >= bar.maximum()
        self.appendPlainText(self._stamp(text))
        self._tint_last_block(text)
        if self.blockCount() > self.MAX_LINES:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(
                QTextCursor.MoveOperation.Down,
                QTextCursor.MoveMode.KeepAnchor,
                self.blockCount() - self.MAX_LINES,
            )
            cursor.removeSelectedText()
        if follow:
            bar.setValue(bar.maximum())

    def _replace_last_line(self, text: str):
        """In-place rewrite of the newest block — carriage-return progress.
        Never grows blockCount(), so the MAX_LINES trim in append_line()
        is unaffected."""
        bar = self.verticalScrollBar()
        follow = bar.value() >= bar.maximum()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        # re-stamped, not stamp-preserved: a carriage-return progress line is
        # rewritten continuously, so the useful timestamp is the moment of
        # the LATEST update, not of the first one
        cursor.insertText(self._stamp(text))
        self._tint_last_block(text)
        if follow:
            bar.setValue(bar.maximum())

    def _tint_last_block(self, source_text: str):
        """Colour the block just written/rewritten by the severity recovered
        from its raw text (see _console_line_tone) — Write-Host's
        -ForegroundColor never survives the pipe Popen reads from, so this
        is the only place that colour can come from. Always sets an
        explicit format, including the plain default: `_replace_last_line`
        reuses the same block across a whole progress sequence, and a line
        that stops matching a marker must not keep a stale tint from an
        earlier rewrite."""
        tone = _console_line_tone(source_text)
        color = self._tone_colors.get(tone, self._default_line_color)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor.mergeCharFormat(fmt)

    # -- v10 output actions ------------------------------------
    def copy_all(self) -> int:
        """Whole buffer to the clipboard. Returns the line count so the
        caller can confirm what was taken — a silent copy leaves the user
        unsure it worked."""
        text = self.toPlainText()
        QApplication.clipboard().setText(text)
        return len(text.splitlines()) if text else 0

    def export_to(self, path: str) -> int:
        """Write the buffer to `path`, returning the line count. Raises
        OSError on failure — the caller reports it; this must not swallow
        a failed write and imply the log was saved."""
        text = self.toPlainText()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return len(text.splitlines()) if text else 0

    def line_count(self) -> int:
        text = self.toPlainText()
        return len(text.splitlines()) if text else 0

    def clear_console(self):
        self.clear()

    def paintEvent(self, e):
        super().paintEvent(e)
        # document().isEmpty(), NOT toPlainText(). The old test materialised
        # the ENTIRE buffer into a Python str on every repaint just to ask
        # whether it had any text — 216 KB and 236.6 us at the 2000-line
        # ceiling, against 2.6 us for the O(1) question (91x). That cost sat
        # directly in the streaming hot path: the console repaints on every
        # output line, so the most expensive paint was the one during the
        # busiest task. The two agree on every state this branch can see —
        # fresh, filled, and cleared (QTextDocument is "empty" exactly when
        # it holds one empty block, which is what toPlainText() renders "").
        if not self.document().isEmpty():
            return
        # Custom empty state — a small on-brand "pulse" waveform motif in
        # place of the generic gray placeholder text QPlainTextEdit would
        # otherwise render natively.
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.viewport().rect()
        cx, cy = r.center().x(), r.center().y() - 12

        bar_w, gap = 4, 7
        heights = (8, 16, 26, 16, 8)
        total_w = len(heights) * bar_w + (len(heights) - 1) * gap
        x = cx - total_w / 2.0
        accent = QColor(self._empty_accent)
        accent.setAlphaF(0.30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        for h in heights:
            p.drawRoundedRect(QRectF(x, cy - h / 2.0, bar_w, h), 2, 2)
            x += bar_w + gap

        p.setPen(self._empty_text)
        msg_font = QFont(self.font().family(), 9)
        p.setFont(msg_font)
        msg_rect = r.adjusted(24, int(cy - r.top()) + 22, -24, 0)
        p.drawText(msg_rect,
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                   | Qt.TextFlag.TextWordWrap,
                   self._EMPTY_MESSAGE)
        p.end()


# ============================================================
#  STATE PILL — compact execution-state chip (console header)
# ============================================================
class StatePill(QLabel):
    """IDLE / RUNNING / SUCCESS / ERROR / STOPPED indicator.

    Styled entirely by theme.state_pill_qss through the dynamic `state`
    property — the same repolish mechanic NavButton uses for `selected`,
    so state flips never rebuild QSS.

    RUNNING additionally carries a live elapsed clock ("RUNNING · 02:41").
    The per-task duration history recorded for a card's own "last run" line
    (v10.1) made a running total possible from data Pulse already collects;
    until now the pill just said RUNNING for the full length of an
    eight-minute install with no sense of how long it had already run."""

    TEXTS = {
        "idle": "IDLE",
        "running": "RUNNING",
        "ok": "SUCCESS",
        "err": "ERROR",
        "stopped": "STOPPED",
    }

    TICK_MS = 1000

    def __init__(self, t: dict, parent: QWidget | None = None):
        super().__init__(self.TEXTS["idle"], parent)
        self.setObjectName("statePill")
        self.setProperty("state", "idle")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(22)
        self._started_at: float | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.apply_theme(t)

    def apply_theme(self, t: dict):
        self.setStyleSheet(TH.state_pill_qss(t))

    def set_state(self, state: str):
        if state == "running":
            # A fresh clock every time — set_state("running") only ever
            # marks the START of a run, never a mid-run refresh.
            self._started_at = time.monotonic()
        else:
            self._started_at = None
            self.setText(self.TEXTS.get(state, state.upper()))
        self._sync_clock()
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)

    # -- lifecycle: never tick at an invisible pill ---------------
    # The same rule BrandMark and StatusDot follow, and this widget
    # shipped (v10.9.4) without it. Their animations were covered anyway
    # by Qt delivering hideEvent to the children of a minimized window; a
    # QTimer is not, so a task left running behind a minimized window woke
    # the GUI thread once a second to setText() on a label nobody could
    # see — and a repaint here goes through every transparent ancestor up
    # to the window, which is the cost the brand mark's breath was
    # quantised down to avoid in the first place.
    def showEvent(self, e):
        super().showEvent(e)
        self._sync_clock()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def _sync_clock(self):
        """Tick only while a run is in flight AND the pill is on screen.

        isVisible() RATHER THAN A hideEvent FLAG, because the pill spends
        most of its life inside a container that is hidden outright: the
        Activity drawer collapses by hiding its BODY, and this pill lives
        in that body. Measured on a running window with the drawer shut —
        `pill.isVisible()` False, no hideEvent ever delivered to the pill
        itself (its ancestor was the thing hidden), and the clock ticking
        once a second regardless. A flag moved only by this widget's own
        events cannot see that, and would have caught the minimized case
        while missing the far more common one.

        `_started_at` is monotonic and every reading is recomputed from it,
        so stopping the timer pauses the DISPLAY and not the measurement:
        the catch-up call below makes the pill correct the instant it comes
        back — when the drawer opens for a task, or when the window is
        restored — rather than resuming from the time it last showed.
        """
        if self._started_at is None or not self.isVisible():
            self._timer.stop()
            return
        self._update_running_text()
        self._timer.start()

    def _tick(self):
        if self._started_at is not None:
            self._update_running_text()

    def _update_running_text(self):
        elapsed = max(0, int(time.monotonic() - self._started_at))
        minutes, seconds = divmod(elapsed, 60)
        self.setText(f"{self.TEXTS['running']} · {minutes:02d}:{seconds:02d}")


# ============================================================
#  UPDATE BADGE — self-update status chip (sidebar footer)
# ============================================================
class UpdateBadge(QPushButton):
    """CHECKING / UP TO DATE / UPDATE READY — the self-updater's status,
    and its manual entry point.

    A QPushButton because it is CLICKABLE in every state it shows in:
    'available' opens the update dialog, anything else re-checks. Styled
    entirely by theme.update_badge_qss through the dynamic `state`
    property — the same repolish mechanic StatePill uses, so a transition
    never rebuilds QSS and nothing here runs off a timer.

    IT SHOWS ONLY WHEN IT HAS SOMETHING ACTIONABLE TO SAY. v14 moved this
    off the Activity rail (where it was one of seven controls competing
    with the running task the rail exists to report) and into the sidebar
    footer, directly above the identity line that was already the manual
    "check for updates" trigger — so the answer and the control are one
    place instead of two that have to agree.

    The visibility rule is the whole point of the move, and it is a rule
    about WHAT IS WORTH A PERMANENT SURFACE:

      * `available` — shown. This is the app's most actionable
        notification and it must stay findable after its toast has gone.
      * `checking`  — shown only for a check the USER asked for. A silent
        launch check that pops a chip into the rail is the app talking
        about itself for no reason.
      * `current`   — hidden. "Nothing is wrong" is reported by a toast on
        the manual path and by silence otherwise; a chip that permanently
        says nothing is happening is chrome, which is exactly what this
        pass is removing.

    AND IT STANDS DOWN WHILE A TASK RUNS (set_busy, driven by
    main.PulseApp._set_busy_ui). Not for width now that it has left the
    rail, but because it is not actionable mid-run:
    main._open_update_dialog already refuses to start an install while the
    engine is mutating the machine (the _busy() guard) and tells the user
    to wait. Suppressing it removes a control that could not have been
    used anyway.
    """

    #: Terse on purpose. The badge is a full-width chip in a ~200px rail,
    #: so it has room the rail never had — but the sentence-length version
    #: of each answer still lives in the tooltip, which costs no layout.
    TEXTS = {
        "idle":      "—",
        "checking":  "● CHECKING…",
        "current":   "✓ UP TO DATE",
        "available": "↑ UPDATE READY",
    }

    #: The states that earn a permanent surface — see the class docstring.
    #: 'checking' is conditional on the check being user-initiated, which
    #: set_state is told; 'current' never shows.
    _VISIBLE_STATES = ("available", "checking")

    #: Horizontal padding + the 1px ring, both from the QSS, plus 2px of
    #: slack so the last glyph's letter-spacing cannot clip. Derived from
    #: TH.CHIP_PAD_H rather than restating it, so a padding change in
    #: theme.py cannot silently clip the badge.
    _WIDTH_CHROME = 2 * TH.CHIP_PAD_H + 2 * 1 + 2

    def __init__(self, t: dict, parent: QWidget | None = None):
        super().__init__(self.TEXTS["checking"], parent)
        self.setObjectName("updateBadge")
        self.setProperty("state", "checking")
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Chrome, not content: the sidebar's footer controls must not join
        # a page's arrow-key traversal or pull focus off it — the same call
        # the identity line beneath it makes.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._state = "idle"
        self._loud = False       # this state has earned the surface
        self._busy = False       # a task is running; stand down
        self._sheen: tuple[int, float] | None = None
        self.hide()
        self.apply_theme(t)

    def apply_theme(self, t: dict):
        self.setStyleSheet(TH.update_badge_qss(t))
        self._sheen = TH.chip_sheen(t)
        self._lock_width()
        self.update()

    def paintEvent(self, e):
        """The same frosted rim StatusChip wears, for the same reason: this
        badge and a card's verdict badge are one object on two surfaces (see
        update_badge_qss), so they have to catch light identically. Painted
        rather than declared because a QSS border is one flat colour on all
        four sides."""
        super().paintEvent(e)
        if self._sheen is None:
            return
        peak, depth = self._sheen
        p = QPainter(self)
        paint_top_sheen(p, self.rect(), TH.RADIUS["chip"], strength=1.0,
                        peak=peak, depth=depth)
        p.end()

    def _lock_width(self):
        """Pin the MINIMUM width to the widest label, so the three states
        cannot jitter the sidebar's width. ensurePolished() first: the
        font-size lives in the stylesheet, so fontMetrics() reports the
        default UI font until the style has been applied."""
        self.ensurePolished()
        fm = self.fontMetrics()
        widest = max(fm.horizontalAdvance(text) for text in self.TEXTS.values())
        self.setMinimumWidth(widest + self._WIDTH_CHROME)

    def set_state(self, state: str, tooltip: str = "", loud: bool = True):
        """`loud=False` marks a check the user did not ask for — the silent
        launch probe — so a 'checking' it produces stays off screen. The
        answer it eventually reports is judged on its own merits."""
        self.setText(self.TEXTS.get(state, state.upper()))
        self.setProperty("state", state)
        self.setToolTip(tooltip)
        self.style().unpolish(self)
        self.style().polish(self)
        self._state = state
        self._loud = loud or state == "available"
        self._sync_visibility()

    def set_busy(self, busy: bool):
        """Stand down while a task runs — see the class docstring."""
        self._busy = busy
        self._sync_visibility()

    def _sync_visibility(self):
        self.setVisible(self._state in self._VISIBLE_STATES
                        and self._loud and not self._busy)


# ============================================================
#  STATUS DOT — the bottom-bar '●', breathes while busy
# ============================================================
class StatusDot(QLabel):
    """The status-bar glyph, and the app's smallest brand moment: Pulse
    pulses. Pure-paint (BrandMark's technique — no QGraphicsEffect), so
    the whole thing costs one small repaint per frame.

    TWO cadences, because a status light that is either frantic or dead
    tells you less than one that idles:

      * BUSY — a 1 s breath down to 0.35. Unmistakably active; this is the
        app's "loading state" graphic, and it must read as work happening
        from across a desk.
      * READY / OK / ERR — a slow 3.4 s breath that only dips to 0.72. A
        LIVING indicator rather than a printed dot: the difference between
        "the system is ready" and "this label says ready". It is close
        enough to steady that it never pulls the eye, which is the whole
        design constraint on an idle indicator — anything deeper reads as
        a warning blinking at you.

    Amplitude and rate move together on purpose. A slow breath at the busy
    depth reads as something wrong; a fast breath at the idle depth reads
    as a rendering glitch.
    """

    #: (duration_ms, floor_opacity) per mode. The idle pair is deliberately
    #: shallow AND slow — see the class note.
    _BUSY = (1000, 0.35)
    _IDLE = (3400, 0.72)

    def __init__(self, glyph: str = "●", parent: QWidget | None = None):
        super().__init__(glyph, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # THE DOT MUST DECLARE ITS OWN TRANSPARENCY. This was the one QLabel
        # in the app that never received a stylesheet, and that was the bug
        # behind the "box behind the green dot": an ancestor's stylesheet
        # makes QStyleSheetStyle set WA_StyledBackground on every descendant,
        # so Qt fills the widget rect with the palette's Window brush — the
        # `overlay` token, rgba(5, 6, 10, 0.45) — BEFORE paintEvent runs.
        # The label stretches to the full 44px rail height while the glyph is
        # 12px, so that fill rendered as a hard-edged 12x42 slab standing
        # behind the dot. Every other label in the app escapes it through
        # label_qss's `background: transparent; border: none`, so the dot says
        # the same thing here. Set once in __init__, not in apply_theme: the
        # dot's colour is painted by hand in paintEvent (see set_color), so
        # nothing about this rule varies with the theme.
        self.setStyleSheet("background: transparent; border: none;")
        self._color = QColor("#3fb950")
        self._breath = 1.0
        self._busy = False
        self._font = QFont(self.font())
        self._font.setPixelSize(12)

        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(EASE_BREATHE)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_frame)
        self._apply_cadence(*self._IDLE)

    def _apply_cadence(self, duration_ms: int, floor: float):
        """Restart the breath at a new rate/depth. Stopped and restarted
        rather than retuned in place: QVariantAnimation keeps its current
        position when the duration changes, which makes a mid-breath
        switch jump to a different opacity than the one being displayed."""
        running = self._anim.state() == QVariantAnimation.State.Running
        self._anim.stop()
        self._anim.setDuration(duration_ms)
        self._anim.setStartValue(1.0)
        self._anim.setKeyValueAt(0.5, floor)
        self._anim.setEndValue(1.0)
        if running:
            self._anim.start()

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def start_pulse(self):
        """Switch to the BUSY cadence — a task is running."""
        if not self._busy:
            self._busy = True
            self._apply_cadence(*self._BUSY)
        if self._anim.state() != QVariantAnimation.State.Running:
            self._anim.start()

    def stop_pulse(self):
        """Fall back to the slow idle breath. NOT to a static dot: the
        indicator stays alive to say the app is, which is the point of
        having one at all."""
        if self._busy:
            self._busy = False
            self._apply_cadence(*self._IDLE)
        if self._anim.state() != QVariantAnimation.State.Running:
            self._anim.start()

    # -- lifecycle: never breathe at an invisible widget ---------
    def showEvent(self, e):
        super().showEvent(e)
        if self._anim.state() != QVariantAnimation.State.Running:
            self._anim.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._anim.stop()

    def _on_frame(self, value: float):
        self._breath = float(value)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(self._breath)
        p.setPen(self._color)
        p.setFont(self._font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


# ============================================================
#  ACTIVITY DRAWER — auto-collapsing live-output console (v7)
# ============================================================
class ActivityDrawer(QWidget):
    """The v7 replacement for the always-open 170px console block — the
    single biggest spatial win of the redesign.

    A slim 44px 'rail' (status dot · status text · Stop · a pin/expand
    chevron) is always visible; the heavy console + shimmer live
    in a BODY that is collapsed to zero height while idle and animates open
    the instant a task runs (set_running(True)), then animates shut again
    when it finishes — handing ~140px of vertical canvas back to the card
    grid whenever nothing is executing. The chevron lets the user PIN it
    open across tasks.

    Doctrine-compliant: the open/close motion is a QPropertyAnimation on the
    body's maximumHeight — no QGraphicsEffect, no per-frame QSS. main.py
    reaches the console / state pill / stop button / shimmer / status dot as
    plain attributes, so the existing task pipeline wires to them unchanged."""

    #: OPENING HEIGHT OF LAST RESORT. The drawer animates to whatever its
    #: body's own layout asks for (see _body_height); this is only what it
    #: falls back to before that layout has resolved — at construction, for
    #: a drawer restored pinned.
    #:
    #: It used to be the real number, and the v14 declutter is what made
    #: that untenable: moving the console's header row down off the rail
    #: changed the body's true height, and a literal that no longer matches
    #: does not fail, it opens the drawer 18px taller than its contents and
    #: leaves an empty strip under the shimmer — an "empty dead zone" of
    #: exactly the kind this pass exists to remove, produced by the pass
    #: itself. Derived, it cannot drift again.
    BODY_H = 224
    ANIM_MS = 200

    # Emitted on every frame of the open/close animation so anything
    # anchored to the drawer's top edge (the toast stack) tracks it live
    # rather than snapping once the animation has finished.
    height_changed = Signal()

    def __init__(self, t: dict, on_stop=None, parent: QWidget | None = None,
                 pinned: bool = False):
        super().__init__(parent)
        self._pinned = pinned
        self._active = False   # a task is currently running

        # Auto-collapse countdown. A restartable QTimer rather than a chain
        # of QTimer.singleShot calls: the hold now has to be CANCELLABLE
        # (hover) and RE-ARMABLE (leave), and a fired singleShot cannot be
        # taken back — several of them racing each other is how a drawer
        # ends up closing during the grace period it was just granted.
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._collapse_if_idle)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(TH.SPACE["sm"])

        # -- always-visible rail ------------------------------
        # v14 STRIPPED IT TO TWO THINGS. The rail shipped carrying seven
        # controls — status dot, status text, update chip, "LIVE OUTPUT",
        # the state pill, four icon tools, the pin chevron and a size grip
        # — every one of them permanently on screen so that the collapsed
        # drawer, whose entire purpose is handing canvas back to the grid,
        # was itself the busiest strip in the window.
        #
        # What stays is what a COLLAPSED drawer can honestly report: the
        # system's own state, and the way in. Everything that describes the
        # OUTPUT moved into the body (below), where the output is; the
        # update chip moved to the sidebar footer beside the control that
        # triggers it (see UpdateBadge); the size grip went entirely, since
        # the window owns a real Win32 sizing frame on every edge and
        # corner (theme.enable_native_sizing_frame).
        self._rail = QFrame()
        self._rail.setObjectName("activityRail")
        self._rail.setFixedHeight(44)
        rail = QHBoxLayout(self._rail)
        rail.setContentsMargins(TH.SPACE["lg"], 0, TH.SPACE["md"], 0)
        rail.setSpacing(TH.SPACE["sm"])

        self.status_dot = StatusDot("●")
        self.status_dot.setFixedWidth(12)
        rail.addWidget(self.status_dot)
        # The rail's one elastic item, and an ElidedCaption rather than a
        # QLabel for the reason that class exists: a long status line
        # ("Playbook: Full Machine Baseline …") must degrade to an ellipsis
        # in the room it actually has, not become a floor the rail is
        # obliged to honour. A plain QLabel adds its full text width to the
        # rail's minimum, which is half of why the old nine-control rail
        # needed 621px at a window that hands it ~608 — and a QLabel
        # squeezed below its hint does not elide, it CLIPS.
        #
        # The ceiling is generous (this is the widest thing on the rail, not
        # a card-footer pill); main._set_status puts the untruncated line in
        # the tooltip, which is the contract every ElidedCaption caller
        # owes its own text.
        self.status_text = ElidedCaption(max_width=420)
        self.status_text.setFullText("System Ready")
        rail.addWidget(self.status_text, 1)

        self.stop_btn = QPushButton("■  Stop Task")
        self.stop_btn.setFixedSize(112, 26)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setToolTip(
            "Hard-stop the running task (kills the whole process tree)")
        if on_stop is not None:
            self.stop_btn.clicked.connect(on_stop)
        self.stop_btn.hide()
        rail.addWidget(self.stop_btn)

        self._toggle = QPushButton(TH.glyph("chevron")[0])
        self._toggle.setCheckable(True)
        self._toggle.setFixedSize(28, 28)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._toggle.setToolTip("Pin the live output open")
        self._toggle.setAccessibleName("Pin the live output open")
        tf = TH.icon_font(TH.ICON["micro"]) if TH.glyph("chevron")[1] else None
        if tf is not None:
            self._toggle.setFont(tf)
        self._toggle.toggled.connect(self._on_toggle)
        rail.addWidget(self._toggle)
        outer.addWidget(self._rail)

        # -- collapsible body ---------------------------------
        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(TH.SPACE["sm"])

        # Body header: what the output IS, what state it is in, and what
        # can be done with it. All three describe the console, so all three
        # live with the console rather than on the rail that survives it
        # being closed — a "clear the output" button beside a collapsed
        # drawer acts on something the user cannot see.
        head = QHBoxLayout()
        head.setContentsMargins(TH.SPACE["xs"], 0, TH.SPACE["xs"], 0)
        head.setSpacing(TH.SPACE["sm"])
        self._console_label = QLabel("LIVE OUTPUT")
        head.addWidget(self._console_label)
        self.state_pill = StatePill(t)
        head.addWidget(self.state_pill)

        # -- the live phase line (v10.5) ----------------------
        # WHAT THE TASK IS DOING RIGHT NOW, in one fixed place. The console
        # below is the unfiltered stream and stays that way; during a
        # fourteen-app update it also scrolls faster than anyone reads it,
        # so "is this actually downloading something, and what?" is a
        # question the stream answers and cannot be GLANCED at.
        #
        # Fed by the backend's ##PULSE##STAGE| channel (see
        # helpers.PowerShellTask.stage), which already existed for the
        # Update Center's scan and was simply never wired to the task
        # pipeline every other operation runs through.
        #
        # An ElidedCaption rather than a QLabel, for the reason that class
        # exists: a long phase line ("Closing Steam (steam,
        # steamwebhelper)...") must degrade to an ellipsis in the room the
        # header actually has, not become a floor the drawer is obliged to
        # honour - and a QLabel squeezed below its hint CLIPS rather than
        # eliding. The untruncated line goes to the tooltip.
        self.stage_label = ElidedCaption(max_width=320)
        self.stage_label.hide()
        head.addWidget(self.stage_label)
        head.addStretch()

        # -- v10 output actions -------------------------------
        # Live output was previously a dead end: you could watch it scroll
        # past and nothing else. These four turn it into something you can
        # actually take away — copy it into a bug report, save it beside a
        # failed run, clear it before a fresh attempt, or drop the
        # timestamp gutter when pasting somewhere narrow. Icon-only ghost
        # buttons so the header stays quiet.
        self._tools: list[QPushButton] = []

        def tool(glyph_key: str, tip: str, slot, checkable: bool = False):
            char, fluent = TH.glyph(glyph_key)
            btn = QPushButton(char)
            btn.setFixedSize(26, 26)
            btn.setCheckable(checkable)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)     # see TitleBar._mk
            font = TH.icon_font(TH.ICON["micro"]) if fluent else None
            if font is not None:
                btn.setFont(font)
            btn.clicked.connect(slot)
            head.addWidget(btn)
            self._tools.append(btn)
            return btn

        self._btn_stamp = tool("clock", "Show timestamps in the output",
                               self._toggle_timestamps, checkable=True)
        self._btn_stamp.setChecked(True)
        tool("copy", "Copy all output to the clipboard", self._copy_output)
        tool("export", "Save the output to a file…", self._export_output)
        tool("clear", "Clear the output", self._clear_output)
        body.addLayout(head)

        self.console = LiveConsole(t)
        self.console.setFixedHeight(172)
        body.addWidget(self.console)
        self.shimmer = ShimmerBar()
        body.addWidget(self.shimmer)
        outer.addWidget(self._body)

        # Start collapsed (idle) — the whole point of the drawer — unless
        # the user pinned it open in a previous session (v10 persistence).
        self._body.setMaximumHeight(self._body_height() if pinned else 0)
        self._body.setVisible(pinned)
        if pinned:
            self._toggle.setChecked(True)

        self._anim = QPropertyAnimation(self._body, b"maximumHeight", self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(EASE_OUT)
        self._anim.finished.connect(self._on_anim_done)
        self._anim.valueChanged.connect(lambda _v: self.height_changed.emit())

        self.apply_theme(t)

    # -- output actions ---------------------------------------
    # `notify` is supplied by main.py so these report through the app's own
    # ToastManager; the drawer has no business owning notification UI.
    def set_notifier(self, notify):
        self._notify = notify

    def _tell(self, kind: str, message: str):
        notify = getattr(self, "_notify", None)
        if notify is not None:
            notify(kind, message)

    def _toggle_timestamps(self, checked: bool):
        self.console.set_timestamps(checked)
        self._btn_stamp.setToolTip(
            "Hide timestamps in the output" if checked
            else "Show timestamps in the output")

    def _copy_output(self):
        lines = self.console.copy_all()
        if lines:
            self._tell("success", f"Copied {lines} line(s) to the clipboard.")
        else:
            self._tell("info", "There is no output to copy yet.")

    def _clear_output(self):
        if not self.console.line_count():
            self._tell("info", "The output is already empty.")
            return
        self.console.clear_console()
        self._tell("info", "Output cleared.")

    def _export_output(self):
        if not self.console.line_count():
            self._tell("info", "There is no output to save yet.")
            return
        default = os.path.join(
            resources.desktop_dir(),
            f"Pulse_Output_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save live output", default, "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            lines = self.console.export_to(path)
        except OSError as exc:
            # never claim a save that didn't happen
            self._tell("error", f"Could not save the output: {exc}")
            return
        self._tell("success", f"Saved {lines} line(s) to {os.path.basename(path)}")

    # -- theming ----------------------------------------------
    # -- live phase ------------------------------------------
    def set_stage(self, text: str):
        """Show one backend phase line, or hide the chip when `text` is
        empty. Also echoes into the console, deliberately: the STAGE
        channel is a payload channel and helpers.py keeps it OUT of the
        stream, so without this the exported log would carry winget's
        output with no record of which app it belonged to or which phase
        produced it."""
        text = (text or "").strip()
        if not text:
            self.clear_stage()
            return
        self.stage_label.setFullText(text)
        self.stage_label.setToolTip(text)
        self.stage_label.show()
        # append_MARKER, not append_line: the stage echo lands in the
        # middle of a carriage-return progress stream, and a plain
        # append is overwritten by the very next percentage frame.
        self.console.append_marker(f"\u25b8  {text}")

    def clear_stage(self):
        self.stage_label.setFullText("")
        self.stage_label.setToolTip("")
        self.stage_label.hide()

    def apply_theme(self, t: dict):
        self._rail.setStyleSheet(TH.activity_rail_qss(t))
        self._console_label.setStyleSheet(TH.console_header_qss(t))
        self.stage_label.setStyleSheet(TH.stage_chip_qss(t))
        for btn in self._tools:
            btn.setStyleSheet(TH.activity_toggle_qss(t))
        self.status_text.setStyleSheet(TH.label_qss(t, "status"))
        self.state_pill.apply_theme(t)
        self.stop_btn.setStyleSheet(TH.stop_button_qss(t))
        self._toggle.setStyleSheet(TH.activity_toggle_qss(t))
        self.console.apply_theme(t)
        self.shimmer.set_theme(t)

    # -- open / close animation -------------------------------
    def _animate_to(self, target: int):
        self._anim.stop()
        if target > 0:
            self._body.setVisible(True)
        self._anim.setStartValue(self._body.maximumHeight())
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_anim_done(self):
        # fully hide the body once closed so the console stops painting
        if self._body.maximumHeight() == 0:
            self._body.setVisible(False)

    def _body_height(self) -> int:
        """Exactly as tall as the console block wants to be.

        Asked fresh on every open rather than cached: the body's contents
        are fixed-height, but the header row's own hint depends on the
        icon font Qt actually resolved and on the DPI it resolved it at,
        neither of which is known when the class is defined.
        """
        hint = self._body.sizeHint().height()
        return hint if hint > 0 else self.BODY_H

    def _open(self):
        self._animate_to(self._body_height())

    def _close(self):
        self._animate_to(0)

    def _on_toggle(self, checked: bool):
        self._pinned = checked
        label = "Unpin the live output" if checked else "Pin the live output open"
        self._toggle.setToolTip(label)
        self._toggle.setAccessibleName(label)
        if checked:
            self._open()
        elif not self._active:
            self._close()

    # -- public API (called by main.py's task pipeline) --------
    #: Hold after a run that printed essentially nothing — just long enough
    #: to read the one-line verdict before the canvas comes back.
    HOLD_MS = 1500
    #: Hold after a run whose OUTPUT IS THE DELIVERABLE. PATH Doctor is the
    #: clearest case: its whole value is the list of environment entries it
    #: repaired, and at 1.5s the drawer shut before any of it could be read,
    #: so the task appeared to do nothing. SFC/DISM, the driver scan and the
    #: catalog deploys are the same shape. Not "never collapse" — the drawer
    #: handing ~140px back to the grid is the point of it existing.
    HOLD_READABLE_MS = 15000
    #: Above this many console lines a run counts as worth reading.
    READABLE_LINES = 3

    def set_running(self, running: bool):
        """A task started (True) → expand immediately; finished (False) →
        collapse after a hold scaled to how much there is to read, unless
        the user has pinned the drawer open.

        The hold is also CANCELLED WHILE THE POINTER IS OVER THE DRAWER (see
        enterEvent), the same courtesy Toast extends to a notification being
        read — a panel that closes itself out from under the eyes reading it
        is the complaint this whole pairing answers.
        """
        self._active = running
        if running:
            self._open()
            return
        try:
            readable = self.console.line_count() > self.READABLE_LINES
        except (RuntimeError, AttributeError):
            readable = False
        self._schedule_collapse(
            self.HOLD_READABLE_MS if readable else self.HOLD_MS)

    def _schedule_collapse(self, delay_ms: int):
        self._collapse_timer.start(delay_ms)

    def _collapse_if_idle(self):
        # a new task may have started (or the user pinned it) during the hold
        if self._active or self._pinned:
            return
        # …and the pointer may be resting on the drawer, which means someone
        # is reading it. Re-arm rather than close; leaveEvent restarts the
        # countdown from a short grace period once they move away.
        if self.underMouse():
            self._collapse_timer.start(self.HOLD_MS)
            return
        self._close()

    def enterEvent(self, e):
        # Reading. Stop the clock outright — leaveEvent restarts it.
        self._collapse_timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._active and not self._pinned and self._body.isVisible():
            self._collapse_timer.start(self.HOLD_MS)
        super().leaveEvent(e)

    def is_pinned(self) -> bool:
        """Persisted across sessions — see utils.prefs.drawer_pinned."""
        return self._pinned

    def toggle_pinned(self):
        """Ctrl+\\ — flip the pin through the toggle button so the chevron's
        checked state, the tooltip and the drawer stay in one truth."""
        self._toggle.setChecked(not self._toggle.isChecked())


# ============================================================
#  TOGGLE SWITCH — native-feeling animated on/off control
# ============================================================
class ToggleSwitch(QWidget):
    """A macOS/iOS-style pill switch, pure-paint per the animations.py
    doctrine (no QGraphicsEffect, no per-frame QSS rebuild — one looping
    QVariantAnimation drives the thumb slide + track color cross-fade,
    another drives the busy pulse). Used by the Startup Manager for
    instant enable/disable: clicking flips the thumb immediately and
    emits `toggled`; the caller drives `set_busy(True)` while the backend
    call is in flight and `set_checked_silent()` afterwards to reconcile
    the visual state with the real outcome without re-emitting `toggled`."""

    toggled = Signal(bool)

    WIDTH, HEIGHT, PAD = 42, 24, 3

    def __init__(self, t: dict, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked
        self._busy = False
        self._pos = 1.0 if checked else 0.0
        self._on_color = QColor(t["ok"])
        self._off_color = self._track_off(t)
        self._thumb_color = QColor("#ffffff")

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(EASE_OUT)
        self._anim.valueChanged.connect(self._on_frame)

        self._busy_anim = QVariantAnimation(self)
        self._busy_anim.setDuration(900)
        self._busy_anim.setStartValue(0.35)
        self._busy_anim.setKeyValueAt(0.5, 1.0)
        self._busy_anim.setEndValue(0.35)
        self._busy_anim.setEasingCurve(EASE_BREATHE)
        self._busy_anim.setLoopCount(-1)
        self._busy_anim.valueChanged.connect(lambda _v: self.update())

    # -- theming ------------------------------------------------
    @staticmethod
    def _track_off(t: dict) -> QColor:
        """The OFF track, composited to an OPAQUE colour.

        TWO bugs lived in the one line this replaces, `QColor(t["panel_line"])`:

        1. QColor CANNOT PARSE rgba(). panel_line is 'rgba(255, 255, 255,
           0.075)' — QSS notation, which QColor rejects, yielding an INVALID
           QColor that Qt paints as opaque BLACK. Every switch in the Startup
           Manager drew a hard black pill in its off state, in both themes;
           on the light card (#ffffff) that was the most conspicuous surface
           in the app. TH.to_qcolor exists precisely to parse these.
        2. Alpha would have been dropped anyway. paintEvent rebuilds the
           track from .red()/.green()/.blue() to cross-fade toward `ok`, so a
           translucent QColor loses its alpha there and paints at full
           strength — pure white in dark mode.

        So the tint is flattened HERE, against the opaque row surface
        (bg_solid + card), exactly the way TH.blend() and the contrast tests
        composite every other translucent token. Result: #27292e on the dark
        row, #e6e6e7 on the light one — the subtle recessed well the token
        was always naming.
        """
        return TH.to_qcolor(
            TH.blend(TH.blend(t["bg_solid"], t["card"]), t["panel_line"]))

    def apply_theme(self, t: dict):
        self._on_color = QColor(t["ok"])
        self._off_color = self._track_off(t)
        self.update()

    # -- state ----------------------------------------------------
    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        self._set_checked(checked, emit=False)

    def set_checked_silent(self, checked: bool):
        """Reconcile the visual state with a backend result without
        re-triggering `toggled` (avoids feedback loops)."""
        self._set_checked(checked, emit=False)

    def set_busy(self, busy: bool):
        if busy == self._busy:
            return
        self._busy = busy
        self.setDisabled(busy)
        if busy:
            self._busy_anim.start()
        else:
            self._busy_anim.stop()
            self.update()

    def _set_checked(self, checked: bool, emit: bool):
        self._checked = checked
        target = 1.0 if checked else 0.0
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(target)
        self._anim.start()
        if emit:
            self.toggled.emit(checked)

    def _on_frame(self, value):
        self._pos = float(value)
        self.update()

    # -- interaction ----------------------------------------------
    def mouseReleaseEvent(self, e):
        if self._busy:
            return
        if (e.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(e.position().toPoint())):
            self._set_checked(not self._checked, emit=True)
        super().mouseReleaseEvent(e)

    # -- painting ---------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._busy:
            value = self._busy_anim.currentValue()
            p.setOpacity(float(value) if value is not None else 0.6)

        track, on = self._off_color, self._on_color
        mix = QColor(
            int(track.red()   + (on.red()   - track.red())   * self._pos),
            int(track.green() + (on.green() - track.green()) * self._pos),
            int(track.blue()  + (on.blue()  - track.blue())  * self._pos),
        )
        rect = QRectF(0, 0, self.WIDTH, self.HEIGHT)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix)
        p.drawRoundedRect(rect, self.HEIGHT / 2.0, self.HEIGHT / 2.0)

        d = self.HEIGHT - self.PAD * 2
        x = self.PAD + self._pos * (self.WIDTH - self.PAD * 2 - d)
        p.setBrush(self._thumb_color)
        p.drawEllipse(QRectF(x, self.PAD, d, d))
        p.end()


# ============================================================
#  APP SELECTOR DIALOG — unified with the Dev Hub pattern
# ============================================================
class SoftwareCatalogDialog(PulseDialog):
    """THE unified software hub — every installable app Pulse offers, in
    one scrollable list, filtered in place by a sub-category tab bar.

    This replaced AppSelectorDialog and DevHubSelectorDialog, which were
    two dialogs over four separate cards (Essential Apps, Dev Hub, Gaming,
    Diagnostics). That layout meant a user who wanted VLC, Docker and Steam
    ran three deploys from three places, and it gave "where do I get X?"
    four possible answers. One catalog, one deploy, one answer.

    THE TABS FILTER; THEY DO NOT PAGE. Every row is built once and merely
    hidden, so a tick survives a tab change and "Deploy Selected" can span
    sub-categories — which is the entire point of merging. It also means
    the selection counter is global while Select All / Deselect All are
    scoped to what is currently on screen: a "Select All" that silently
    ticked 43 rows across four hidden tabs would be a trap, and one that
    could not tick the 14 rows you are looking at would be useless.

    MANUAL-FIRST, unlike the old per-pack selector. Those dialogs arrived
    pre-checked because a card had already promised "the pack"; a 43-row
    catalog making the same promise would open with 43 apps queued and put
    the user to work untangling it. Nothing here is pre-ticked and the
    deploy button stays inert until something is actually chosen.

TWO NARROWING CONTROLS, ONE EACH TO A ROW. The field narrows by NAME
    and the tabs narrow by CATEGORY; they compose, but they no longer
    share a line. They did, with the field pinned to the right of the
    scrolling tab strip, and that arrangement broke both of them: a scroll
    area takes the width it is given and reports overflow rather than
    asking for more, so the strip simply surrendered the field's 180px and
    put a tab under the scrollbar at every window size — while the field
    itself was 180px wide on a panel five times that. See the row's own
    comment in __init__.

    There is no THIRD control. The dialog used to carry a strip of
    "Java / University Stack" / "AI / Python Stack" / "Web Dev Stack"
    buttons under the tabs; they only applied to one of the five tabs, and
    they answered a question — "which five apps does a Java course need?"
    — that the Development & Tools tab answers by simply being read.
    Removing them also removed the only control in the dialog that
    appeared and disappeared as you changed tabs.

    After Accepted, exactly one of these is populated:
      `selected_ids`     ticked AppIds for the bulk winget deploy
      `local_installer`  (app_name, file_path) from a row wizard's Path C,
                          for a single InstallLocalFile run
    """

    #: The "no sub-category" tab. Empty string so it can be compared with a
    #: section key directly and passed straight to catalog_tools().
    ALL_KEY = ""

    def __init__(self, parent: QWidget, item: dict, t: dict,
                 sections: list[dict]):
        super().__init__(parent)
        self._t = t
        self.selected_ids: list[str] = []
        self.local_installer: tuple[str, str] | None = None
        self._rows: dict[str, DevHubRow] = {}
        self._tool_meta: dict[str, tuple[str, str]] = {}   # id -> (name, url)
        self._row_section: dict[str, str] = {}             # id -> section key
        self._row_haystack: dict[str, str] = {}            # id -> searchable text
        self._dependents: dict[str, list[str]] = {}        # requires_id -> [ids]
        self._headers: list[tuple[QWidget, str, list[str]]] = []  # (w, section, ids)
        self._tab_buttons: dict[str, QPushButton] = {}
        self._active_tab = self.ALL_KEY
        self._query = ""
        accent = t["accent"]

        panel = _dialog_chrome(self, t, accent, responsive=True)
        lay = dialog_body(panel, "sm")

        total = sum(len(tools) for s in sections
                    for _g, tools in s["groups"])

        head = QLabel(f"{item['icon']}  {item['title']}")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        lay.addWidget(head)

        self._blurb = QLabel(
            f"All {total} apps in one place. Nothing is pre-selected — tick "
            "what you want, filter by sub-category, then deploy in one pass.")
        self._blurb.setWordWrap(True)
        self._blurb.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._blurb)

        # -- the filter row, then the tab row --------------------
        # TWO ROWS, and they used to be one. The tabs narrow by CATEGORY,
        # the field narrows by NAME, and they do compose — "development" +
        # "sql" is a question neither answers alone — but composing is not
        # a reason to make them share a line, and sharing one is what broke
        # both of them.
        #
        # The field was a 180px fixed block on the right of a row whose
        # left-hand item is a SCROLLING STRIP. A scroll area takes whatever
        # width it is given and reports overflow rather than asking for
        # more, so the two never competed honestly for space: the strip
        # simply surrendered ~190px of its own to the field and the fifth
        # tab went under the scrollbar at every window size, not only at the
        # narrow ones. Meanwhile the field itself was 180px on a 900px panel
        # — a search box that could show about twenty characters.
        #
        # Split apart, each control gets the full content width: the field
        # spans the panel, and the strip below it gets ~190px back, which is
        # roughly one more tab visible before it has to scroll at all.
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter apps…")
        self._search.setFixedHeight(_CHIP_H)
        self._search.setClearButtonEnabled(True)
        self._search.setStyleSheet(TH.catalog_search_qss(t, accent))
        self._search.textChanged.connect(self._on_query)
        lay.addWidget(self._search)

        # The tabs live in a horizontally scrolling strip, NOT directly in
        # the layout — five labelled pills want ~1300px against a panel that
        # caps at 900, so the strip is what makes the overflow reachable
        # rather than clipped.
        #
        # No emoji on the tabs, deliberately: it buys ~140px across the row
        # (more tabs visible before the strip has to scroll) and loses
        # nothing, because each section's icon still leads its group header
        # a few pixels below, which is where the tab/content association
        # actually gets made.
        tab_strip, tab_lay = _chip_strip(t, _CHIP_H)
        for key, label in ([(self.ALL_KEY, f"All ({total})")] +
                           [(s["key"], f"{s['title']}"
                             f" ({sum(len(x) for _g, x in s['groups'])})")
                            for s in sections]):
            btn = QPushButton(label.replace("&", "&&"))
            btn.setFixedHeight(_CHIP_H)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self._set_tab(k))
            self._tab_buttons[key] = btn
            tab_lay.addWidget(btn)
        tab_lay.addStretch()
        lay.addWidget(tab_strip)

        # -- select-all / select-none + live counter -------------
        toolbar = QHBoxLayout()
        toolbar.setSpacing(TH.SPACE["lg"])
        self._all_btn = QPushButton("Select All")
        self._all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._all_btn.setStyleSheet(TH.link_button_qss(t, accent))
        self._all_btn.clicked.connect(lambda: self._set_visible_checked(True))
        toolbar.addWidget(self._all_btn)

        self._none_btn = QPushButton("Deselect All")
        self._none_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._none_btn.setStyleSheet(TH.link_button_qss(t, accent))
        self._none_btn.clicked.connect(lambda: self._set_visible_checked(False))
        toolbar.addWidget(self._none_btn)
        toolbar.addStretch()

        self._count_label = QLabel("0 selected")
        self._count_label.setStyleSheet(TH.label_qss(t, "caption"))
        toolbar.addWidget(self._count_label)
        lay.addLayout(toolbar)

        # -- the one continuous list ------------------------------
        scroll = FitScroll()
        scroll.setStyleSheet(TH.scroll_area_qss(t))

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host_lay = scroll_host_layout(host, "sm")

        for section in sections:
            for group_title, tools in section["groups"]:
                ids = [tool[0] for tool in tools]
                # A group header is shown when the group names itself;
                # otherwise the SECTION's own title stands in, so the "All"
                # tab never presents a wall of rows with no dividers.
                header = QLabel(group_title or f"{section['icon']}  {section['title']}")
                header.setStyleSheet(TH.label_qss(t, "section"))
                host_lay.addWidget(header)
                self._headers.append((header, section["key"], ids))
                for app_id, name, desc, url, req_id, req_name in tools:
                    row = DevHubRow(app_id, name, desc, req_id, req_name, t)
                    row.checkbox.toggled.connect(
                        lambda checked, aid=app_id: self._on_row_toggled(aid, checked))
                    row.options_requested.connect(self._open_tool_wizard)
                    self._rows[app_id] = row
                    self._tool_meta[app_id] = (name, url)
                    self._row_section[app_id] = section["key"]
                    self._row_haystack[app_id] = f"{name} {desc} {app_id}".lower()
                    if req_id:
                        self._dependents.setdefault(req_id, []).append(app_id)
                    host_lay.addWidget(row)

        # Empty state — a filter that matches nothing must say so, for the
        # same reason CategoryPage carries one: a blank list is
        # indistinguishable from a broken dialog.
        self._empty = QLabel("No apps match that filter.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(TH.empty_state_qss(t))
        self._empty.hide()
        host_lay.addWidget(self._empty)
        host_lay.addStretch()

        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        lay.addSpacing(TH.SPACE["xs"])
        footer = QHBoxLayout()
        footer.addStretch()
        cancel = QPushButton("Cancel")
        size_dialog_button(cancel)
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)

        self._deploy_btn = QPushButton("Deploy Selected")
        size_dialog_button(self._deploy_btn)
        self._deploy_btn.setStyleSheet(TH.dialog_go_qss(t, accent))
        self._deploy_btn.clicked.connect(self._accept_selection)
        footer.addWidget(self._deploy_btn)
        lay.addLayout(footer)

        self._set_tab(self.ALL_KEY)

    # -- tab / search filtering ------------------------------------
    def _set_tab(self, key: str):
        self._active_tab = key
        accent = self._t["accent"]
        for tab_key, btn in self._tab_buttons.items():
            btn.setStyleSheet(
                TH.catalog_tab_qss(self._t, accent, tab_key == key))
        self._apply_filter()

    def _on_query(self, text: str):
        self._query = text.strip().lower()
        self._apply_filter()

    def _row_matches(self, app_id: str) -> bool:
        if self._active_tab and self._row_section.get(app_id) != self._active_tab:
            return False
        return not self._query or self._query in self._row_haystack.get(app_id, "")

    def _apply_filter(self):
        """Show/hide rows and their headers, then sync the affordances that
        describe the visible set."""
        visible = 0
        for app_id, row in self._rows.items():
            shown = self._row_matches(app_id)
            row.setVisible(shown)
            visible += shown
        # A header survives only while at least one of its own rows does —
        # otherwise a filtered list grows orphan titles over empty space.
        for header, _section_key, ids in self._headers:
            header.setVisible(any(self._row_matches(aid) for aid in ids))
        self._empty.setVisible(visible == 0)
        self._all_btn.setEnabled(visible > 0)
        self._none_btn.setEnabled(visible > 0)
        self._sync_count()

    # -- selection state ------------------------------------------
    def _visible_ids(self) -> list[str]:
        return [aid for aid in self._rows if self._row_matches(aid)]

    def _set_visible_checked(self, checked: bool):
        """Scoped to what is on screen — see the class docstring."""
        for app_id in self._visible_ids():
            self._rows[app_id].checkbox.setChecked(checked)

    def _refresh_runtime_suggestion(self, runtime_id: str):
        """Recompute a runtime row's highlight from scratch: on whenever it
        is unchecked AND at least one of its (possibly several — both
        NetBeans and IntelliJ need Java) dependents is checked."""
        runtime_row = self._rows.get(runtime_id)
        if runtime_row is None:
            return
        dependents = self._dependents.get(runtime_id, [])
        needs_it = (not runtime_row.is_checked()) and any(
            self._rows[d].is_checked() for d in dependents if d in self._rows)
        runtime_row.set_suggested(needs_it)

    def _on_row_toggled(self, app_id: str, _checked: bool):
        row = self._rows.get(app_id)
        if row is not None and row.requires_id:
            self._refresh_runtime_suggestion(row.requires_id)
        if app_id in self._dependents:
            self._refresh_runtime_suggestion(app_id)
        self._sync_count()

    def _sync_count(self):
        """The counter is GLOBAL (a tick on a hidden tab still deploys), and
        says so explicitly whenever the visible set is narrower than the
        whole catalog — otherwise '5 selected' on a tab showing four rows
        looks like a bug rather than a feature."""
        count = self.checked_count()
        narrowed = bool(self._active_tab) or bool(self._query)
        self._count_label.setText(
            f"{count} selected across all categories" if count and narrowed
            else f"{count} selected")
        self._deploy_btn.setText(
            f"Deploy Selected ({count})" if count else "Deploy Selected")
        self._deploy_btn.setEnabled(count > 0)

    def checked_count(self) -> int:
        return sum(1 for r in self._rows.values() if r.is_checked())

    def _accept_selection(self):
        # Catalog ORDER, not click order: dict preserves insertion, and the
        # rows were inserted in $Apps_CatalogAll's order, so the deploy log
        # reads down the list the user just looked at.
        self.selected_ids = [aid for aid, row in self._rows.items()
                             if row.is_checked()]
        if not self.selected_ids:
            return
        self.accept()

    # -- per-tool wizard --------------------------------------------
    def _open_tool_wizard(self, app_id: str):
        name, url = self._tool_meta.get(app_id, (app_id, ""))
        desc = self._rows[app_id].checkbox.toolTip()
        wizard = ToolInstallWizardDialog(self, app_id, name, desc, url, self._t)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        if wizard.mode == "winget":
            for row in self._rows.values():
                row.checkbox.setChecked(False)
            self._rows[app_id].checkbox.setChecked(True)
            self._accept_selection()
        elif wizard.mode == "local" and wizard.local_path:
            self.local_installer = (name, wizard.local_path)
            self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)
        self._search.setFocus()


# ============================================================
#  COMMAND PALETTE — Ctrl+K fuzzy quick-launcher
# ============================================================
# ============================================================
#  SEARCH INTELLIGENCE — normalisation, aliases, typo tolerance
# ============================================================
#: Arabic characters that carry no distinguishing meaning for search, or
#: that a user types inconsistently. Normalising them is not a nicety —
#: without it the palette is unusable in Arabic, because the SAME word is
#: routinely written several ways:
#:
#:   * ALEF comes as ا أ إ آ, and which one a keyboard produces depends on
#:     the layout and on whether the writer bothered with the hamza;
#:   * final YEH is ي in Egypt and ى in the Gulf, for the same word;
#:   * TEH MARBUTA (ة) and HEH (ه) are interchanged constantly in typing;
#:   * HARAKAT (the short-vowel marks) are optional and usually absent;
#:   * TATWEEL (ـ) is a decorative stretch with no phonetic value at all.
#:
#: So "تحديثات" typed two ways is two different strings to `in`, and one of
#: them silently matches nothing. Folding them to one form first is what
#: makes an Arabic query behave like an English one.
_AR_DIACRITICS = "".join(chr(c) for c in range(0x064B, 0x0653)) + "\u0640\u0670"
_AR_FOLD = {
    "\u0623": "\u0627", "\u0625": "\u0627", "\u0622": "\u0627",  # أإآ -> ا
    "\u0649": "\u064a",                                          # ى  -> ي
    "\u0629": "\u0647",                                          # ة  -> ه
    "\u0624": "\u0648", "\u0626": "\u064a",                      # ؤئ -> وي
}


def normalise_query(text: str) -> str:
    """Casefold, strip Arabic diacritics, and unify the interchangeable
    Arabic letter forms. Latin text is unaffected beyond lowercasing."""
    out = []
    for ch in text.strip().lower():
        if ch in _AR_DIACRITICS:
            continue
        out.append(_AR_FOLD.get(ch, ch))
    return "".join(out)


#: Query term -> the English words it should ALSO search for.
#:
#: This is the multi-language half, and it is a translation table rather
#: than a translated UI on purpose. Pulse's interface is English: the cards
#: say "Aggressive Cache Clean", and translating those strings is a
#: different, much larger project with its own review burden. What an
#: Arabic-speaking user needs first is not a translated card — it is to be
#: able to FIND it. So the query is translated, once, into the words the
#: interface already uses, and the result list stays in the language the
#: rest of the app is written in.
#:
#: The English entries are here for the same reason: a user types the VERB
#: they want ("uninstall", "speed up") far more often than the noun a card
#: happens to be titled with, and "remove" finding "Purge OneDrive" is the
#: same lookup as "احذف" finding it.
#:
#: Keys are stored already normalised (see normalise_query).
SEARCH_ALIASES: dict[str, tuple[str, ...]] = {
    # -- Arabic: the verbs a user reaches for ----------------------
    "تحديث":   ("update", "upgrade"),
    "تحديثات": ("update", "upgrade"),
    "تسريع":   ("performance", "power", "optimize", "speed"),
    "سرعه":    ("performance", "power", "speed"),
    "تنظيف":   ("clean", "cache", "cleanup"),
    "نظافه":   ("clean", "cache"),
    "حذف":     ("remove", "uninstall", "purge", "delete"),
    "احذف":    ("remove", "uninstall", "purge"),
    "ازاله":   ("remove", "uninstall", "purge"),
    "الغاء":   ("remove", "uninstall", "disable"),
    "تثبيت":   ("install", "deploy"),
    "برامج":   ("software", "apps", "catalog"),
    "تطبيقات": ("software", "apps", "catalog"),
    "خصوصيه":  ("privacy", "telemetry"),
    "امان":    ("security", "defender", "safety"),
    "حمايه":   ("security", "defender", "protection"),
    "شبكه":    ("network", "dns"),
    "انترنت":  ("network", "dns"),
    "قرص":     ("drive", "disk", "storage"),
    "تخزين":   ("storage", "drive", "disk"),
    "ذاكره":   ("memory", "ram"),
    "بدء":     ("startup", "boot"),
    "تشغيل":   ("startup", "boot", "run"),
    "نسخه":    ("backup", "restore", "version"),
    "استعاده": ("restore", "recovery", "restore point"),
    "اصلاح":   ("repair", "fix", "sfc"),
    "سجل":     ("log", "history", "report"),
    "تقرير":   ("report", "health"),
    "مظهر":    ("theme", "dark", "appearance"),
    "لغه":     ("language", "region"),
    "طاقه":    ("power", "battery", "plan"),
    # -- English: the verb a user types, not the noun on the card ---
    "uninstall": ("remove", "purge"),
    "delete":    ("remove", "purge"),
    "speed":     ("performance", "power", "optimize"),
    "faster":    ("performance", "power", "optimize"),
    "cleanup":   ("clean", "cache"),
    "antivirus": ("defender", "security"),
    "wifi":      ("network", "dns"),
    "internet":  ("network", "dns"),
    "ram":       ("memory", "storage"),
    "boot":      ("startup",),
    "bloat":     ("bloatware", "remove"),
}


def _edit_distance_within(a: str, b: str, limit: int) -> int | None:
    """Damerau-Levenshtein distance between `a` and `b`, or None once it is
    provably greater than `limit`.

    BOUNDED, and the bound is what makes it safe to use here. A full
    distance over every title on every keystroke is wasted work, and — far
    worse — an UNBOUNDED distance turns the palette into a random-result
    generator, because at distance 5 every short word is near every other
    short word. The caller allows 1 edit on a short query and 2 on a long
    one, which covers the real cases (a transposed pair, a doubled letter,
    a dropped one) and nothing else.

    Transpositions are counted as ONE edit rather than two, which is the
    Damerau part and the reason it is here: "cahce" for "cache" and
    "sfc"/"scf" are transpositions, and plain Levenshtein scores those the
    same as two unrelated typos.
    """
    if abs(len(a) - len(b)) > limit:
        return None
    previous2: list[int] = []
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(previous[j] + 1,        # deletion
                             current[j - 1] + 1,     # insertion
                             previous[j - 1] + cost)  # substitution
            if (i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb):
                current[j] = min(current[j], previous2[j - 2] + 1)
        if min(current) > limit:
            return None
        previous2, previous = previous, current
    return previous[-1] if previous[-1] <= limit else None


def _typo_hit(query: str, title: str) -> bool:
    """True when `query` is one or two edits from a WORD of `title`.

    Per word, never against the whole title: "dark" is 3 edits from "Global
    Dark Mode" as a whole string and 0 from the word inside it, so matching
    whole titles would need a bound so loose it matched everything.
    """
    if len(query) < 4:
        return False          # under four letters, one edit is another word
    limit = 1 if len(query) <= 6 else 2
    # LOWERCASED HERE, defensively. The query arrives normalised and the
    # title does not, and a capital letter is a substitution: without this,
    # "cahce" was 2 edits from "Cache" (the transposition plus the C) and
    # fell outside a limit of 1 — so the typo tolerance silently did
    # nothing for every title, which is all of them.
    for word in title.lower().replace("-", " ").replace("/", " ").split():
        if _edit_distance_within(query, word, limit) is not None:
            return True
    return False


def _fuzzy_score(needle: str, haystack: str) -> int | None:
    """Subsequence fuzzy match: every needle char must appear in haystack
    in order (case handled by the caller); tighter, earlier matches score
    higher. Returns None when needle is not a subsequence of haystack.

    ONLY EVER APPLIED TO A SHORT FIELD (a title), never to a concatenation
    of everything an item knows about — see _match_entry.
    """
    if not needle:
        return 0
    pos = 0
    score = 0
    streak = 0
    for ch in needle:
        idx = haystack.find(ch, pos)
        if idx == -1:
            return None
        gap = idx - pos
        streak = streak + 1 if gap == 0 else 1
        score += (10 - min(gap, 9)) + streak
        pos = idx + 1
    return score


def _word_start(haystack: str, needle: str) -> bool:
    """True when `needle` begins a word in `haystack` — 'disk' matches
    'CrystalDiskInfo' and 'Drive Space Report', but not 'Rockstar'."""
    idx = haystack.find(needle)
    while idx != -1:
        if idx == 0 or not haystack[idx - 1].isalnum():
            return True
        idx = haystack.find(needle, idx + 1)
    return False


#: Score floors for each way a query can match, most specific first. Gaps
#: are wide enough that a weaker KIND of match can never outrank a stronger
#: one on tie-breaks alone — the defect this table replaced, where a
#: coincidental letter-scatter across a 1500-character blob outranked a
#: literal app-name hit.
_MATCH_EXACT_TITLE = 1000
_MATCH_TITLE_PREFIX = 900
_MATCH_TITLE_WORD = 820
_MATCH_TITLE_SUB = 760
_MATCH_CONTENT_EXACT = 700
_MATCH_CONTENT_WORD = 640
_MATCH_CONTENT_SUB = 580
_MATCH_CATEGORY = 420
_MATCH_DESC_WORD = 360
_MATCH_DESC_SUB = 300
_MATCH_FUZZY_TITLE = 200

#: An ALIAS hit — the query was translated before it matched (Arabic, or an
#: English verb the interface does not use). Scored as its own tier rather
#: than as whatever the translated word scored, so a card that matches the
#: user's LITERAL text always outranks one that needed translating: someone
#: typing "update" gets Check for Updates, and someone typing "تحديث" gets
#: the same card, but "update" never loses to a translated match.
_MATCH_ALIAS = 500

#: ...and a TYPO hit, below every deliberate match. A misspelling is the
#: weakest evidence the palette accepts, so it may only ever fill the list
#: BELOW anything that matched as typed — otherwise "disk" finding
#: "Disable" (one edit) would push a real "Drive Space Report" hit down.
_MATCH_TYPO_TITLE = 150


def _match_entry(query: str, item: dict, category: str) -> tuple[int, str] | None:
    """(score, matched_content) for one palette entry, or None.

    `matched_content` names the CONTAINED thing that matched, when that is
    why the row is in the results — "Software Catalog" surfacing for
    "spotify" has to be able to say *why*, or it reads as a random hit.
    Empty when the item matched on its own title, description or module.

    Structured on purpose. The previous implementation fuzzy-matched one
    concatenated string per item; because that string folds in every app a
    card can install, the Software Catalog's ran ~1500 characters and
    matched almost any query as a subsequence — while scoring lower than
    short unrelated titles that happened to contain the same letters. The
    measured result was that "spotify" ranked Startup Manager first,
    "docker" did not return the catalog at all, and "vlc" led with
    Activation Status. Every one of those is the palette failing the exact
    promise its docstring makes.
    """
    if not query:
        return (0, "")

    title = item.get("title", "").lower()
    desc = item.get("desc", "").lower()
    note = item.get("note", "").lower()
    cat = category.lower()

    # -- the item itself ------------------------------------------
    if title == query:
        return (_MATCH_EXACT_TITLE, "")
    if title.startswith(query):
        return (_MATCH_TITLE_PREFIX - len(title), "")
    if query in title:
        base = _MATCH_TITLE_WORD if _word_start(title, query) else _MATCH_TITLE_SUB
        return (base - len(title), "")

    # -- what it contains -----------------------------------------
    # Best single match wins, so one precise hit is not diluted by 42
    # misses sitting next to it in the same card.
    best: tuple[int, str] | None = None
    for name in MS.search_contents(item):
        low = name.lower()
        if low == query:
            score = _MATCH_CONTENT_EXACT
        elif query in low:
            score = ((_MATCH_CONTENT_WORD if _word_start(low, query)
                      else _MATCH_CONTENT_SUB) - len(low))
        else:
            continue
        if best is None or score > best[0]:
            best = (score, name)
    if best is not None:
        return best

    # -- weaker context -------------------------------------------
    if query in cat:
        return (_MATCH_CATEGORY - len(cat), "")
    if query in desc:
        base = _MATCH_DESC_WORD if _word_start(desc, query) else _MATCH_DESC_SUB
        return (base - len(desc), "")
    if query in note:
        return (_MATCH_DESC_SUB - len(note), "")

    # -- initials / abbreviations, TITLE ONLY ----------------------
    # Keeps "sfc", "odt" and "cdi" style shorthand working without letting
    # a long contents blob match everything.
    fuzzy = _fuzzy_score(query, title)
    if fuzzy is not None:
        return (_MATCH_FUZZY_TITLE + fuzzy - len(title), "")

    # -- the query, translated -------------------------------------
    # Arabic, or an English verb the interface does not happen to use. Each
    # expansion is re-run through this same function, so a translated query
    # gets the full structured treatment (title, contents, description)
    # rather than a second, weaker matcher of its own — which is how
    # "تحديث" reaches Check for Updates by its title and "برامج" reaches
    # the Software Catalog by the apps it contains.
    #
    # RECURSION IS SAFE AND BOUNDED: the expansions are plain English words
    # and none of them is itself a key in SEARCH_ALIASES, so the second
    # call cannot expand again. The guard is explicit rather than trusted,
    # because a future alias pointing at another alias would otherwise
    # recurse until the stack ran out.
    for alias in SEARCH_ALIASES.get(query, ()):
        if alias in SEARCH_ALIASES:
            continue
        hit = _match_entry(alias, item, category)
        if hit is not None:
            # Capped at the alias tier: a translated match is real, and it
            # is still weaker evidence than the user's own words.
            return (min(hit[0], _MATCH_ALIAS) - len(title), hit[1])

    # -- last resort: a misspelling of a word in the title ----------
    if _typo_hit(query, title):
        return (_MATCH_TYPO_TITLE - len(title), "")
    return None


class _PaletteList(QListWidget):
    """A result list that reports the height its ROWS want, capped.

    The same contract FitScroll carries for scroll areas, and it is needed
    here for the same reason: a QListWidget is a viewport onto something
    arbitrarily long, so its size hint is a fixed default that has nothing
    to do with what is in it. The palette's panel takes its height from
    its layout, so an unhinted list gave a four-row panel with a scrollbar
    down the side of an eight-row result set — the surface deciding, on no
    information, that it was too small for its own answer.

    The cap is what stops that inverting: past it the hint stops growing
    and the list goes back to being a viewport, which is the correct
    behaviour for a query that genuinely matched everything.
    """

    def __init__(self, max_height: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._max_height = max_height

    def _content_height(self) -> int:
        total = sum(self.sizeHintForRow(row) for row in range(self.count()))
        return total + 2 * self.frameWidth()

    def sizeHint(self):            # noqa: N802 - Qt casing
        hint = super().sizeHint()
        hint.setHeight(max(0, min(self._content_height(), self._max_height)))
        return hint

    def minimumSizeHint(self):     # noqa: N802 - Qt casing
        """Zero height, so a short window can still squeeze the palette
        rather than being pushed past its own edge by the list."""
        hint = super().minimumSizeHint()
        hint.setHeight(0)
        return hint


class _PaletteRow(QFrame):
    """One result: the operation's own glyph, its title, and a right-
    aligned hint.

    A WIDGET, not a formatted string, and that is the change the palette's
    whole refinement rests on. Rows used to be one QListWidgetItem holding
    `f"{icon}  {title}   ·   {category} · installs {matched}"` — a single
    string, so it had a single alignment, so the CONTEXT (which module a
    result belongs to, why a catalog card matched "spotify") ran on into
    the title and pushed long results into an ellipsis. Splitting it lets
    the title own the left edge and the hint own the right, which is what
    every palette worth copying does and the only layout in which you can
    scan a result list by title alone.
    """

    def __init__(self, glyph_key: str, fallback: str, title: str,
                 hint: str, t: dict, parent: QWidget | None = None):
        super().__init__(parent)
        # WA_TranslucentBackground, not merely a transparent stylesheet:
        # the row sits ON the list's selection pill, and any painted
        # background of its own would mask it.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedHeight(TH.PALETTE_ROW_H)
        self._hint_text = hint

        lay = QHBoxLayout(self)
        lay.setContentsMargins(TH.SPACE["md"], 0, TH.SPACE["md"], 0)
        lay.setSpacing(TH.SPACE["md"])

        self._glyph = QLabel()
        self._glyph.setObjectName("paletteGlyph")
        self._glyph.setFixedWidth(TH.ICON["plaque"])
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        char, is_fluent = TH.glyph(glyph_key) if glyph_key else ("", False)
        if is_fluent:
            font = TH.icon_font(TH.ICON["inline"])
            if font is not None:
                self._glyph.setFont(font)
            self._glyph.setText(char)
        else:
            self._glyph.setText(fallback)
        lay.addWidget(self._glyph)

        self._title = QLabel(title)
        self._title.setObjectName("paletteTitle")
        lay.addWidget(self._title, 1)

        self._hint = QLabel(hint)
        self._hint.setObjectName("paletteHint")
        self._hint.setVisible(bool(hint))
        lay.addWidget(self._hint, 0, Qt.AlignmentFlag.AlignRight
                      | Qt.AlignmentFlag.AlignVCenter)

        # The RUN marker, shown only on the active row. It is the palette
        # saying which key does the thing, on the row that key would do it
        # to — a footer hint says Enter runs something, this says what.
        self._enter = QLabel("↵")
        self._enter.setObjectName("paletteEnter")
        self._enter.setVisible(False)
        # AlignVCenter, or the keycap's own stylesheet background stretches
        # to the full row height and the "key" becomes a 40px slab.
        lay.addWidget(self._enter, 0, Qt.AlignmentFlag.AlignVCenter)

        self.set_selected(False, t)

    def set_selected(self, on: bool, t: dict):
        self.setStyleSheet(TH.palette_row_qss(t, on))
        self._enter.setStyleSheet(TH.palette_keycap_qss(t))
        self._enter.setVisible(on)
        # The hint yields the row to the RUN marker rather than sharing it:
        # at the narrow end of the panel both together push the title into
        # an ellipsis, and on the row you are about to run, "press Enter"
        # outranks "this lives in Maintenance".
        self._hint.setVisible(bool(self._hint_text) and not on)


class CommandPalette(PulseDialog):
    """Ctrl+K quick launcher — fuzzy search over every task defined in
    menu_structure.py, GROUPED BY MODULE:

        ┌────────────────────────────────────────────────┐
        │ ⌕  Search apps, tweaks and tools…              │
        │                                                │
        │ SYSTEM & TWEAKS ───────────────────────────    │
        │  ⚡  Ultimate Power Plan                   ↵   │
        │  🌙  Global Dark Mode                          │
        │ MAINTENANCE & SECURITY ────────────────────    │
        │  🧹  Aggressive Cache Clean                    │
        ├────────────────────────────────────────────────┤
        │ ↑↓ navigate   ↵ run   esc close     3 results  │
        └────────────────────────────────────────────────┘

    Built fresh on each open (like ConfirmDialog / SoftwareCatalogDialog:
    transient, no live re-theme needed) and driven through the same
    accept()/reject() + `chosen_item` pattern, so the caller launches the
    pick through the app's normal request_task() pipeline — confirmations,
    the app selector, and the concurrency guard all apply for free,
    exactly as if a card had been clicked.

    GROUPING DOES NOT COST RELEVANCE, which is the trade a grouped palette
    usually makes and the reason this one does not group naively. Groups
    are ordered by their OWN best-scoring member, and rows inside a group
    by score, so the top result overall is still the first row on screen —
    it has simply acquired a heading. What that buys is the thing a flat
    list could not do: the module name stops being repeated on every row
    as trailing context and becomes a divider you read once.
    """

    #: Results shown, across all groups. Unchanged: the palette is a
    #: launcher, not a browser, and a list you have to scroll has already
    #: failed to answer the query.
    MAX_RESULTS = 8

    #: Tallest the result list may grow before it scrolls. Sized for the
    #: worst real case — MAX_RESULTS rows plus a heading before each of
    #: the four modules — so the common case never scrolls and the
    #: pathological one does rather than pushing the footer off the panel.
    LIST_MAX_H = 8 * (TH.PALETTE_ROW_H + 2) + 4 * TH.PALETTE_ROW_H

    #: Marks a header row's item data, so navigation can skip it and a
    #: click on it cannot launch anything.
    _HEADER = "__section__"

    def __init__(self, parent: QWidget, t: dict, entries: list[tuple[dict, str]]):
        super().__init__(parent)
        self._t = t
        self.chosen_item: dict | None = None
        self._entries = entries  # (item dict, category title) pairs
        self._rows: dict[int, _PaletteRow] = {}   # list row -> widget

        panel = _dialog_chrome(self, t, t["accent"], width=560, anchor="top")

        lay = QVBoxLayout(panel)
        pad = TH.PAD["sheet"]
        lay.setContentsMargins(pad, pad, pad, TH.SPACE["sm"])
        lay.setSpacing(TH.SPACE["md"])

        # -- the field -------------------------------------------------
        self._field = QFrame()
        self._field.setObjectName("paletteField")
        self._field.setFixedHeight(TH.PALETTE_FIELD_H)
        field_lay = QHBoxLayout(self._field)
        field_lay.setContentsMargins(TH.SPACE["md"], 0, TH.SPACE["md"], 0)
        field_lay.setSpacing(TH.SPACE["md"])

        mark = QLabel()
        char, is_fluent = TH.glyph("search")
        if is_fluent:
            font = TH.icon_font(TH.ICON["inline"])
            if font is not None:
                mark.setFont(font)
        mark.setText(char)
        field_lay.addWidget(mark)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search apps, tweaks and tools…")
        self._search.setFrame(False)
        self._search.textChanged.connect(self._refilter)
        self._search.installEventFilter(self)
        field_lay.addWidget(self._search, 1)
        lay.addWidget(self._field)

        # -- results ---------------------------------------------------
        self._list = _PaletteList(self.LIST_MAX_H)
        self._list.setStyleSheet(TH.palette_list_qss(t))
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setUniformItemSizes(False)
        self._list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemClicked.connect(self._activate)
        self._list.itemActivated.connect(self._activate)
        lay.addWidget(self._list)

        # A query that matches nothing used to leave an empty bordered box
        # under the field, which is indistinguishable from the palette
        # having broken. Every other search surface in the app already
        # states its empty result (CategoryPage._empty,
        # SoftwareCatalogDialog._empty); this one is now consistent with
        # them, and the list is HIDDEN rather than left blank so the panel
        # shrinks to the message instead of framing a void.
        self._empty = QLabel("No apps, tweaks or tools match that search.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(TH.empty_state_qss(t))
        self._empty.hide()
        lay.addWidget(self._empty)

        lay.addWidget(self._build_footer(t))

        self._apply_field_focus(False)
        self._refilter("")

    # -- the hint bar --------------------------------------------------
    def _build_footer(self, t: dict) -> QFrame:
        foot = QFrame()
        foot.setObjectName("paletteFooter")
        foot.setStyleSheet(TH.palette_footer_qss(t))
        row = QHBoxLayout(foot)
        row.setContentsMargins(TH.SPACE["xs"], TH.SPACE["sm"],
                               TH.SPACE["xs"], 0)
        row.setSpacing(TH.SPACE["xs"])
        for keys, what in (("↑↓", "navigate"), ("↵", "run"), ("esc", "close")):
            cap = QLabel(keys)
            cap.setStyleSheet(TH.palette_keycap_qss(t))
            row.addWidget(cap)
            label = QLabel(what)
            row.addWidget(label)
            row.addSpacing(TH.SPACE["sm"])
        row.addStretch()
        self._count = QLabel("")
        row.addWidget(self._count)
        return foot

    # -- filtering / grouping ------------------------------------------
    def _refilter(self, text: str):
        self._list.clear()
        self._rows.clear()
        # normalise_query, not .lower(): an Arabic query typed with
        # harakat, or with a different alef, is the same query and has to
        # fold to the same string before anything compares it.
        query = normalise_query(text)

        scored = []
        for item, category in self._entries:
            hit = _match_entry(query, item, category)
            if hit is not None:
                scored.append((hit[0], hit[1], item, category))
        # Sort by score, then by title, so equal scores order predictably
        # instead of by whatever iteration order the catalog happened to
        # have — a result list that reshuffles between identical queries
        # reads as broken.
        scored.sort(key=lambda row: (-row[0], row[2].get("title", "")))
        shown = scored[: self.MAX_RESULTS]

        self._empty.setVisible(bool(query) and not shown)
        self._list.setVisible(bool(shown))
        self._count.setText(
            "" if not shown else
            f"{len(shown)} result{'' if len(shown) == 1 else 's'}")

        # GROUPS ORDERED BY THEIR BEST MEMBER, so the top hit stays the top
        # row. Python's dicts keep insertion order and `shown` is already
        # sorted by score, so the first time a module appears IS its best
        # score — no second sort needed.
        #
        # GROUPED BY MODULE, NOT BY BREADCRUMB. iter_leaf_items() hands
        # back "Software Management › Microsoft Edge" for an action inside
        # a hub, and grouping on that splits one module into as many
        # sections as it has hubs — four results could produce four
        # headers, which is a list of headings with a row under each
        # rather than a grouped list. The module is the group; the hub
        # moves to the row's own right-aligned hint, which is where a
        # detail that locates ONE result belongs.
        groups: dict[str, list] = {}
        for row in shown:
            module, _sep, hub = row[3].partition(" › ")
            groups.setdefault(module, []).append((row, hub))

        for index, (module, rows) in enumerate(groups.items()):
            self._add_header(module, first=(index == 0))
            for (_score, matched, item, _cat), hub in rows:
                self._add_result(item, matched, hub)
        # The row count changed, so the height the list wants changed with
        # it — and Qt caches a child's hint until something invalidates it.
        # Without this the panel keeps whatever height the FIRST query
        # produced, which for the empty opening query is every entry in the
        # app and for the next one is four.
        self._list.updateGeometry()
        self._select_first()

    def _add_header(self, title: str, first: bool = False):
        """A group heading: a hairline closing the previous group, then the
        module name with its air ABOVE it.

        A WIDGET rather than a bare QLabel, and the reason is the same one
        that made the result rows widgets: a single label has a single box,
        so the only lever it offered was where the text sat inside it —
        which is how the heading ended up bottom-aligned in a short box,
        floating almost equidistant between the group it named and the one
        above. Padding groups the heading with its rows; the rule tells the
        previous group it has ended. Those are two jobs and they need two
        things drawn.

        `first` suppresses the rule on the topmost group, where there is
        nothing above to separate from and a rule would just be a line
        under the search field.
        """
        head = QListWidgetItem()
        head.setFlags(Qt.ItemFlag.NoItemFlags)
        head.setData(Qt.ItemDataRole.UserRole, self._HEADER)

        cell = QWidget()
        cell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        cell.setFixedHeight(TH.PALETTE_SECTION_H)
        column = QVBoxLayout(cell)
        column.setContentsMargins(TH.SPACE["md"], 0, TH.SPACE["md"], 0)
        column.setSpacing(0)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(TH.palette_section_rule_qss(self._t))
        rule.setVisible(not first)
        column.addWidget(rule)
        # The rule occupies the first pixel of the top pad rather than
        # adding to it, so a group with a rule and the first group without
        # one are exactly the same height and the rows below them line up.
        column.addSpacing(TH.PALETTE_SECTION_PAD_TOP - 1)

        label = QLabel(title.upper())
        label.setStyleSheet(TH.palette_section_qss(self._t))
        label.setFixedHeight(TH.PALETTE_SECTION_TEXT_H)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(label)
        column.addSpacing(TH.PALETTE_SECTION_PAD_BOTTOM)

        # An EXPLICIT hint, not the widget's own: a QListWidget sizes an
        # item widget from the hint the ITEM carries, and a QLabel asked
        # for its hint before Qt has polished its stylesheet answers for
        # the default font rather than for the 10px letterspaced caption
        # it is about to become. The rows then overlap their headers.
        head.setSizeHint(QSize(0, TH.PALETTE_SECTION_H))
        self._list.addItem(head)
        self._list.setItemWidget(head, cell)

    def _add_result(self, item: dict, matched: str, hub: str):
        # THE HINT NAMES WHY THIS ROW IS HERE, when that is not obvious.
        # Two things can make it non-obvious, and they do not co-occur
        # often enough to need both on one row:
        #   * the hit came from something the card CONTAINS ("Software
        #     Catalog" for "spotify" is correct and reads as random
        #     without the reason attached), or
        #   * the action lives inside a HUB, so its title alone does not
        #     say where it is — and the group header above it names only
        #     the module, deliberately (see _refilter).
        # The content match wins: it answers a question the user is
        # actively asking, where the hub is background.
        hint = f"installs {matched}" if matched else hub
        row = _PaletteRow(item.get("glyph", ""), item.get("icon", ""),
                          item.get("title", ""), hint, self._t)
        cell = QListWidgetItem()
        cell.setData(Qt.ItemDataRole.UserRole, item)
        cell.setSizeHint(QSize(0, TH.PALETTE_ROW_H))
        self._list.addItem(cell)
        self._list.setItemWidget(cell, row)
        self._rows[self._list.row(cell)] = row

    # -- selection ------------------------------------------------------
    def _is_result(self, row: int) -> bool:
        item = self._list.item(row)
        return (item is not None
                and item.data(Qt.ItemDataRole.UserRole) != self._HEADER)

    def _select_first(self):
        for row in range(self._list.count()):
            if self._is_result(row):
                self._list.setCurrentRow(row)
                return

    def _on_row_changed(self, row: int):
        """Repaint the run marker. Only the ACTIVE row carries it, so both
        the row gaining it and the row losing it have to be told."""
        for index, widget in self._rows.items():
            widget.set_selected(index == row, self._t)

    def _move_selection(self, delta: int):
        """Step to the next RESULT, skipping section headers and wrapping.

        Headers are items in the same list — that is what lets the divider
        scroll with the group it names — so navigation has to step over
        them rather than assume every index is selectable. Wrapping is the
        palette convention: Down on the last result returns to the first
        rather than dead-ending, because the list is short by construction
        and a keyboard-first surface should never have a key that does
        nothing.
        """
        count = self._list.count()
        if count == 0:
            return
        row = self._list.currentRow()
        if row < 0:
            row = -1 if delta > 0 else count
        for _ in range(count):
            row = (row + delta) % count
            if self._is_result(row):
                self._list.setCurrentRow(row)
                self._list.scrollToItem(self._list.item(row))
                return

    def _activate(self, list_item: QListWidgetItem):
        data = list_item.data(Qt.ItemDataRole.UserRole)
        if data == self._HEADER or data is None:
            return
        self.chosen_item = data
        self.accept()

    # -- keyboard: the QLineEdit owns focus, so Up/Down/Enter/Escape are
    # intercepted here and forwarded to the result list -----------------
    def eventFilter(self, obj, event):
        if obj is self._search:
            if event.type() == QEvent.Type.FocusIn:
                self._apply_field_focus(True)
            elif event.type() == QEvent.Type.FocusOut:
                self._apply_field_focus(False)
            elif event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key == Qt.Key.Key_Down:
                    self._move_selection(1)
                    return True
                if key == Qt.Key.Key_Up:
                    self._move_selection(-1)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    current = self._list.currentItem()
                    if current is not None:
                        self._activate(current)
                    return True
                if key == Qt.Key.Key_Escape:
                    self.reject()
                    return True
        return super().eventFilter(obj, event)

    def _apply_field_focus(self, on: bool):
        """The field's focus ring lives on its CONTAINER, because the
        QLineEdit inside it is chromeless (see theme.palette_field_qss) —
        a :focus rule on the input would light a border that is not
        drawn."""
        self._field.setProperty("focused", on)
        self._field.setStyleSheet(TH.palette_field_qss(self._t))

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self, duration_ms=130)
        self._search.setFocus()


# ============================================================
#  OFFICE WIZARD — step-by-step Office Deployment Tool flow
# ============================================================
class OfficeWizardDialog(PulseDialog):
    """Multi-path Office Deployment Tool (ODT) wizard.

    Office ships as one Click-to-Run bundle with no per-app silent
    installer, so unlike every other catalog item this can't be a single
    winget call. Three paths, chosen up front:

      A. Automated Cloud Download — Pulse fetches the Click-to-Run client
         itself and applies a built-in standard configuration. No files to
         find, no folders to browse. Sets `task_override` so the caller
         runs -Task InstallOfficeODTAuto instead of the per-file task.
      B. "I already have my files" — auto-detects Desktop\\Office (and the
         OneDrive-redirected / Public Desktop variants), with a folder
         browser and an individual-file-picker as fallbacks.
      C. Beginner Guide — a plain-language walkthrough for downloading the
         ODT and building a configuration.xml by hand via Microsoft's own
         tools, which then feeds into the same locate flow as B.

    All of this is client-side (file-system checks, QFileDialog, browser
    links — no PowerShell spawned yet). After Accepted, the caller reads
    either `task_override` (path A) or `setup_path`/`config_path` (path
    B/C) and runs it through the normal task pipeline — same live console,
    Stop button and toast machinery as every other task.
    """

    ODT_URL = "https://www.microsoft.com/en-us/download/details.aspx?id=49117"
    OCT_URL = "https://config.office.com/deploymentsettings"

    _SETUP_NAMES = ("setup.exe", "Setup.exe", "setup.exe.exe", "Setup.exe.exe")
    # Preference order: known Office Customization Tool export names first
    # (kept in sync with 10-Office.ps1's Find-OfficeConfigFile) — used both
    # to auto-pick when there's exactly one match and to mark the top pick
    # "(recommended)" when several configs sit in the same folder.
    _CONFIG_NAMES = (
        "configuration.xml", "Configuration.xml",
        "configuration.xml.xml", "Configuration.xml.xml",
        "configuration-Office365-x64.xml", "configuration-Office365-x86.xml",
    )

    _SUBTITLES = {
        "choice": "Choose how you'd like to proceed",
        "auto_confirm": "Automated Cloud Download",
        "guide": "Beginner Guide — get the official tools",
        "locate": "Locate your Office files",
        "confirm": "Confirm & Install",
    }

    def __init__(self, parent: QWidget, t: dict):
        super().__init__(parent)
        self._t = t
        self.setup_path: str | None = None
        self.config_path: str | None = None
        self.task_override: str | None = None
        # Where "Back" from the locate step should return to — "choice" if
        # Path B was picked directly, "guide" if arriving via Path C.
        self._locate_origin = "choice"

        # 620: the locate step's path row (label + elided path + Browse)
        # needs 588px before anything is squeezed.
        panel = _dialog_chrome(self, t, t["accent"], width=620)

        lay = dialog_body(panel, "md")

        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(TH.SPACE["xxs"])
        title = QLabel("📄  Microsoft Office Deployment")
        title.setStyleSheet(TH.label_qss(t, "dialog"))
        title_col.addWidget(title)
        self._step_label = QLabel("")
        self._step_label.setStyleSheet(TH.label_qss(t, "caption"))
        title_col.addWidget(self._step_label)
        head.addLayout(title_col)
        head.addStretch()
        lay.addLayout(head)

        self._pages: dict[str, int] = {}
        self._stack = fit_stack(QStackedWidget())
        self._stack.setStyleSheet(TH.stack_qss())
        for name, builder in (
            ("choice", self._build_choice_page),
            ("auto_confirm", self._build_auto_page),
            ("guide", self._build_guide_page),
            ("locate", self._build_locate_page),
            ("confirm", self._build_confirm_page),
        ):
            self._pages[name] = self._stack.count()
            self._stack.addWidget(builder())
        lay.addWidget(self._stack)

        self._goto("choice")

    # -- small shared button factories --------------------------
    def _back_button(self, slot) -> QPushButton:
        b = QPushButton("‹  Back")
        size_dialog_button(b)
        b.setStyleSheet(TH.dialog_cancel_qss(self._t))
        b.clicked.connect(slot)
        return b

    def _primary_button(self, text: str, slot) -> QPushButton:
        """The wizard's CTA. `width` used to be a parameter, defaulting to
        130 and overridden to 190 at one call site — a per-button pixel
        count carried through a function signature, which is the same
        hand-picked width size_dialog_button exists to delete."""
        b = QPushButton(text)
        size_dialog_button(b)
        b.setStyleSheet(TH.dialog_go_qss(self._t, self._t["accent"]))
        b.clicked.connect(slot)
        return b

    def _link_row_button(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setFixedHeight(50)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(TH.wizard_link_qss(self._t, self._t["accent"]))
        b.clicked.connect(slot)
        return b

    @staticmethod
    def _clear_layout(lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                OfficeWizardDialog._clear_layout(sub)

    # -- navigation -----------------------------------------------
    def _goto(self, step: str):
        self._step_label.setText(self._SUBTITLES[step])
        self._stack.setCurrentIndex(self._pages[step])
        if step == "locate":
            self._run_autodetect()
        elif step == "confirm":
            self._render_confirm()

    # -- step: choice (3 paths) --------------------------------------
    def _build_choice_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(TH.SPACE["md"])

        intro = QLabel(
            "Office ships as one bundle through Microsoft's official "
            "Deployment Tool (ODT) — there's no per-app silent installer. "
            "Choose how you'd like to proceed.")
        intro.setWordWrap(True)
        intro.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(intro)

        opt_a = GlassCard({
            "icon": "🚀", "title": "Automated Cloud Download",
            "desc": "Pulse downloads the Deployment Tool and applies a standard configuration for you.",
        }, t["accent"], t)
        opt_a.setMinimumHeight(88)
        opt_a.clicked.connect(lambda: self._goto("auto_confirm"))
        lay.addWidget(opt_a)

        opt_b = GlassCard({
            "icon": "📁", "title": "I already have my Office folder ready",
            "desc": "Auto-detect the Office folder on your Desktop, or browse to it.",
        }, t["accent"], t)
        opt_b.setMinimumHeight(88)
        opt_b.clicked.connect(self._enter_locate_from_choice)
        lay.addWidget(opt_b)

        opt_c = GlassCard({
            "icon": "📘", "title": "Step-by-Step Beginner Guide",
            "desc": "New to this? A plain-language walkthrough of the official Microsoft tools.",
        }, t["accent"], t)
        opt_c.setMinimumHeight(88)
        opt_c.clicked.connect(lambda: self._goto("guide"))
        lay.addWidget(opt_c)

        lay.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        size_dialog_button(cancel)
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)
        return page

    def _enter_locate_from_choice(self):
        self._locate_origin = "choice"
        self._goto("locate")

    # -- Path A: automated cloud download ----------------------------
    def _build_auto_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(TH.SPACE["lg"])

        info = QLabel(
            "Pulse will download the official Office Click-to-Run client "
            "and write a standard configuration to <b>Desktop\\Office</b> "
            "— Word, Excel, PowerPoint and Outlook in English and Arabic. "
            "No files to find, nothing to configure by hand.")
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)
        info.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(info)

        note = QLabel(
            "ℹ️  This standard configuration targets Volume License "
            "activation (no product key baked in). If your network has a "
            "KMS host it activates automatically; otherwise Office installs "
            "but stays unactivated until a key is added. Prefer a "
            "subscription install with your own settings? Use one of the "
            "other two paths instead.")
        note.setWordWrap(True)
        note.setStyleSheet(TH.label_qss(t, "caption"))
        lay.addWidget(note)

        warn = QLabel(
            "⚠️  IMPORTANT: When the Microsoft Setup window appears, DO NOT "
            "close it or open any other apps until it reaches 100%.")
        warn.setWordWrap(True)
        warn.setStyleSheet(TH.warning_banner_qss(t))
        lay.addWidget(warn)
        lay.addStretch()

        row = QHBoxLayout()
        row.addWidget(self._back_button(lambda: self._goto("choice")))
        row.addStretch()
        row.addWidget(self._primary_button(
            "Download && Install Now", self._accept_auto))
        lay.addLayout(row)
        return page

    def _accept_auto(self):
        self.task_override = "InstallOfficeODTAuto"
        self.accept()

    # -- Path C: beginner guide ---------------------------------------
    def _build_guide_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(TH.SPACE["md"])

        steps = [
            ("1", "Open the Deployment Tool below, run it, and extract it "
                  "into a folder named <b>Office</b> on your Desktop."),
            ("2", "Open the Customization Tool below, choose your apps, "
                  "languages and channel, then download the resulting "
                  "<b>configuration.xml</b> into that same Office folder."),
            ("3", "Come back here and continue — Pulse will pick up both "
                  "files automatically."),
        ]
        for num, text in steps:
            row = QHBoxLayout()
            row.setSpacing(TH.SPACE["md"])
            badge = QLabel(num)
            badge_px = 22
            badge.setFixedSize(badge_px, badge_px)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                f"color: {t['accent']}; background: {TH.alpha(t['accent'], 0.14)};"
                f"border: 1px solid {TH.alpha(t['accent'], 0.40)};"
                f" border-radius: {badge_px // 2}px;"
                f"font-size: {TH.TYPE['caption']}px; font-weight: {TH.WEIGHT['bold']};")
            row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            label = QLabel(text)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            label.setStyleSheet(TH.label_qss(t, "body"))
            row.addWidget(label, 1)
            lay.addLayout(row)

        lay.addWidget(self._link_row_button(
            "🌐  Open Office Deployment Tool   ↗",
            lambda: QDesktopServices.openUrl(QUrl(self.ODT_URL))))
        lay.addWidget(self._link_row_button(
            "⚙️  Open Office Customization Tool   ↗",
            lambda: QDesktopServices.openUrl(QUrl(self.OCT_URL))))

        lay.addStretch()
        row = QHBoxLayout()
        row.addWidget(self._back_button(lambda: self._goto("choice")))
        row.addStretch()
        row.addWidget(self._primary_button(
            "I have the files now  ›", self._enter_locate_from_guide))
        lay.addLayout(row)
        return page

    def _enter_locate_from_guide(self):
        self._locate_origin = "guide"
        self._goto("locate")

    # -- Path B (direct, or continuing from C): locate files ----------
    def _build_locate_page(self) -> QWidget:
        page = QWidget()
        self._locate_lay = QVBoxLayout(page)
        self._locate_lay.setContentsMargins(0, 0, 0, 0)
        self._locate_lay.setSpacing(TH.SPACE["md"])
        return page

    def _locate_back(self):
        self._goto(self._locate_origin)

    def _run_autodetect(self):
        self._clear_layout(self._locate_lay)
        folder, setup, configs = self._detect_office_folder()
        if setup and configs:
            self._render_locate_found(folder, setup, configs)
        else:
            self._render_locate_missing(folder)

    def _render_locate_found(self, folder: str, setup: Path, configs: list[Path]):
        t = self._t
        lay = self._locate_lay

        ok = QLabel(f"✅  Found in <b>{folder}</b>")
        ok.setTextFormat(Qt.TextFormat.RichText)
        ok.setWordWrap(True)
        ok.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(ok)

        setup_row = QLabel(f"<b>Setup:</b> {setup}")
        setup_row.setTextFormat(Qt.TextFormat.RichText)
        setup_row.setWordWrap(True)
        setup_row.setStyleSheet(TH.label_qss(t, "caption"))
        lay.addWidget(setup_row)

        if len(configs) == 1:
            config_row = QLabel(f"<b>Config:</b> {configs[0]}")
            config_row.setTextFormat(Qt.TextFormat.RichText)
            config_row.setWordWrap(True)
            config_row.setStyleSheet(TH.label_qss(t, "caption"))
            lay.addWidget(config_row)
        else:
            picker_label = QLabel(
                f"Found {len(configs)} configuration files — which one should Pulse use?")
            picker_label.setWordWrap(True)
            picker_label.setStyleSheet(TH.label_qss(t, "body"))
            lay.addWidget(picker_label)
            for i, cfg in enumerate(configs):
                tag = "  (recommended)" if i == 0 else ""
                btn = self._link_row_button(
                    f"📝  {cfg.name}{tag}",
                    lambda checked=False, c=cfg: self._on_files_chosen(str(setup), str(c)))
                lay.addWidget(btn)

        browse = QPushButton("📂  Browse for a different folder…")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.setStyleSheet(TH.link_button_qss(t, t["accent"]))
        browse.clicked.connect(self._browse_folder)
        lay.addWidget(browse)
        lay.addStretch()

        row2 = QHBoxLayout()
        row2.addWidget(self._back_button(self._locate_back))
        row2.addStretch()
        if len(configs) == 1:
            row2.addWidget(self._primary_button(
                "Continue  ›", lambda: self._on_files_chosen(str(setup), str(configs[0]))))
        lay.addLayout(row2)

    def _render_locate_missing(self, folder: str):
        t = self._t
        lay = self._locate_lay

        warn = QLabel(
            f"⚠️  No Office folder with both setup.exe and a configuration "
            f"file was found automatically (checked <b>{folder}</b>).")
        warn.setTextFormat(Qt.TextFormat.RichText)
        warn.setWordWrap(True)
        warn.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(warn)

        lay.addWidget(self._link_row_button(
            "📂  Browse for the Office folder…", self._browse_folder))
        lay.addWidget(self._link_row_button(
            "🗂️  Pick setup.exe and configuration.xml individually…",
            self._pick_files_individually))
        lay.addStretch()

        row = QHBoxLayout()
        row.addWidget(self._back_button(self._locate_back))
        row.addStretch()
        retry = QPushButton("Retry auto-detect")
        retry.setCursor(Qt.CursorShape.PointingHandCursor)
        retry.setStyleSheet(TH.link_button_qss(t, t["accent"]))
        retry.clicked.connect(self._run_autodetect)
        row.addWidget(retry)
        lay.addLayout(row)

    def _render_browse_incomplete(self, folder: str, setup: Path | None, configs: list[Path]):
        t = self._t
        lay = self._locate_lay
        missing = []
        if not setup:
            missing.append("setup.exe (or the ODT self-extractor)")
        if not configs:
            missing.append("a configuration .xml file")

        msg = QLabel(f"❌  <b>{folder}</b> is missing: " + ", ".join(missing))
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"color: {t['err']}; font-size: {TH.TYPE['body']}px; font-weight: 500;"
            "background: transparent; border: none;")
        lay.addWidget(msg)

        lay.addWidget(self._link_row_button(
            "🗂️  Pick the files individually…", self._pick_files_individually))
        lay.addStretch()

        row = QHBoxLayout()
        row.addWidget(self._back_button(self._locate_back))
        row.addStretch()
        retry = QPushButton("Browse again")
        retry.setCursor(Qt.CursorShape.PointingHandCursor)
        retry.setStyleSheet(TH.link_button_qss(t, t["accent"]))
        retry.clicked.connect(self._browse_folder)
        row.addWidget(retry)
        lay.addLayout(row)

    def _browse_folder(self):
        start = str(Path.home() / "Desktop")
        folder = QFileDialog.getExistingDirectory(
            self, "Select the folder with setup.exe and configuration.xml", start)
        if not folder:
            return
        setup, configs = self._find_office_files(Path(folder))
        self._clear_layout(self._locate_lay)
        if setup and configs:
            self._render_locate_found(folder, setup, configs)
        else:
            self._render_browse_incomplete(folder, setup, configs)

    def _pick_files_individually(self):
        start = str(Path.home() / "Desktop")
        setup, _ = QFileDialog.getOpenFileName(
            self, "Select the Office Deployment Tool (setup.exe)", start,
            "Executable files (*.exe)")
        if not setup:
            return
        config, _ = QFileDialog.getOpenFileName(
            self, "Select configuration.xml", str(Path(setup).parent),
            "XML files (*.xml)")
        if not config:
            return
        self._clear_layout(self._locate_lay)
        self._render_locate_found(str(Path(setup).parent), Path(setup), [Path(config)])

    def _on_files_chosen(self, setup: str, config: str):
        self.setup_path = setup
        self.config_path = config
        self._goto("confirm")

    # -- Path B/C tail: confirm + the "don't close it" warning --------
    def _build_confirm_page(self) -> QWidget:
        page = QWidget()
        self._confirm_lay = QVBoxLayout(page)
        self._confirm_lay.setContentsMargins(0, 0, 0, 0)
        self._confirm_lay.setSpacing(TH.SPACE["lg"])
        return page

    def _render_confirm(self):
        self._clear_layout(self._confirm_lay)
        t = self._t
        lay = self._confirm_lay

        summary = QLabel(
            f"<b>Setup:</b> {self.setup_path}<br><b>Config:</b> {self.config_path}")
        summary.setTextFormat(Qt.TextFormat.RichText)
        summary.setWordWrap(True)
        summary.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(summary)

        warn = QLabel(
            "⚠️  IMPORTANT: When the Microsoft Setup window appears, DO NOT "
            "close it or open any other apps until it reaches 100%.")
        warn.setWordWrap(True)
        warn.setStyleSheet(TH.warning_banner_qss(t))
        lay.addWidget(warn)
        lay.addStretch()

        row = QHBoxLayout()
        row.addWidget(self._back_button(lambda: self._goto("locate")))
        row.addStretch()
        row.addWidget(self._primary_button("Install Now", self.accept))
        lay.addLayout(row)

    # -- file-system detection (client-side, no PowerShell spawned) --
    @classmethod
    def _find_office_files(cls, folder: Path) -> tuple[Path | None, list[Path]]:
        if not folder.is_dir():
            return None, []

        setup: Path | None = None
        for name in cls._SETUP_NAMES:
            cand = folder / name
            if cand.is_file():
                setup = cand
                break
        if setup is None:
            matches = sorted(folder.glob("officedeploymenttool*.exe"))
            if matches:
                setup = matches[0]
        if setup is None:
            exes = sorted(folder.glob("*.exe"))
            if exes:
                setup = exes[0]

        # Every .xml in the folder, known names first (preference order),
        # then whatever else is left over, alphabetically — so a folder
        # with several exports still surfaces a sane "recommended" pick
        # instead of an arbitrary one.
        seen: set[Path] = set()
        configs: list[Path] = []
        for name in cls._CONFIG_NAMES:
            cand = folder / name
            if cand.is_file() and cand not in seen:
                configs.append(cand)
                seen.add(cand)
        for xml in sorted(folder.glob("*.xml")):
            if xml not in seen:
                configs.append(xml)
                seen.add(xml)

        return setup, configs

    def _detect_office_folder(self) -> tuple[str, Path | None, list[Path]]:
        home = Path.home()
        userprofile = os.environ.get("USERPROFILE", str(home))
        public = os.environ.get("PUBLIC", "")
        candidates = [
            home / "Desktop" / "Office",
            Path(userprofile) / "OneDrive" / "Desktop" / "Office",
        ]
        if public:
            candidates.append(Path(public) / "Desktop" / "Office")

        for folder in candidates:
            setup, configs = self._find_office_files(folder)
            if setup and configs:
                return str(folder), setup, configs

        first_existing = next((f for f in candidates if f.is_dir()), candidates[0])
        return str(first_existing), None, []

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


# ============================================================
#  TOOL INSTALL WIZARD — generic 3-path single-tool dialog
# ============================================================
class ToolInstallWizardDialog(PulseDialog):
    """Path A / B / C for exactly one tool. Unlike OfficeWizardDialog (which
    branches because Office genuinely has no per-app winget installer),
    every tool this dialog is used for already has a working winget
    package — Path A here just narrows the caller's normal bulk-deploy
    selection down to this one AppId, reusing 100% of the existing
    Smart-Deploy pipeline. Path B opens the vendor's official page and
    closes (nothing left for Pulse to do). Path C hands back a picked
    installer file for the generic InstallLocalFile task.

    Three flat, terminal choices — no sub-navigation needed, unlike the
    Office wizard's multi-step flow.

    After exec():
      Accepted + mode == "winget" -> caller should deploy just this AppId.
      Accepted + mode == "local"  -> `local_path` holds the picked installer.
      Rejected                    -> nothing to do (Cancel, or Path B was
                                      opened in the browser and that's it).
    """

    def __init__(self, parent: QWidget, app_id: str, app_name: str,
                 desc: str, url: str, t: dict):
        super().__init__(parent)
        self.app_id = app_id
        self.mode: str | None = None
        self.local_path: str | None = None

        panel = _dialog_chrome(self, t, t["accent"], width=470)

        lay = dialog_body(panel, "md")

        head = QLabel(f"⚙️  {app_name}")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        lay.addWidget(head)

        if desc:
            sub = QLabel(desc)
            sub.setWordWrap(True)
            sub.setStyleSheet(TH.label_qss(t, "body"))
            lay.addWidget(sub)

        path_a = GlassCard({
            "icon": "🚀", "title": "One-Click Automated Install",
            "desc": "Silently installs via winget — the same reliable path Pulse uses everywhere.",
        }, t["accent"], t)
        path_a.setMinimumHeight(84)
        path_a.clicked.connect(self._choose_winget)
        lay.addWidget(path_a)

        path_b = GlassCard({
            "icon": "🌐", "title": "Official Download Link",
            "desc": f"Opens {app_name}'s official website in your browser." if url
                    else "Opens a web search for the official download page.",
        }, t["accent"], t)
        path_b.setMinimumHeight(84)
        path_b.clicked.connect(lambda: self._choose_url(url, app_name))
        lay.addWidget(path_b)

        path_c = GlassCard({
            "icon": "📁", "title": "Local File / Manual Selection",
            "desc": "Already downloaded the installer? Pick the file and Pulse will run it.",
        }, t["accent"], t)
        path_c.setMinimumHeight(84)
        path_c.clicked.connect(self._choose_local)
        lay.addWidget(path_c)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        size_dialog_button(cancel)
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _choose_winget(self):
        self.mode = "winget"
        self.accept()

    def _choose_url(self, url: str, app_name: str):
        target = url or f"https://www.google.com/search?q={app_name} download"
        QDesktopServices.openUrl(QUrl(target))
        self.reject()

    def _choose_local(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the installer", str(Path.home() / "Desktop"),
            "Installers (*.exe *.msi)")
        if not path:
            return
        self.mode = "local"
        self.local_path = path
        self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


# ============================================================
#  DEV HUB ROW — checkbox + dependency hint + per-tool "..." wizard
# ============================================================
class DevHubRow(QFrame):
    """One app row inside SoftwareCatalogDialog. Manual-first: unchecked by
    default. `requires_name`, when given, renders a small "needs X" caption
    — a passive hint, never an auto-check. The "⋯" button opens
    ToolInstallWizardDialog for just this tool, independent of the
    checkbox — picking Path A there short-circuits straight to "select
    only this row and deploy" (see
    SoftwareCatalogDialog._open_tool_wizard), Path C hands back a local
    installer instead.

    Still named for the Dev Hub that introduced it: the catalog absorbed
    that hub, and this row is the one selector row shape the whole app
    uses (Update Center's UpdateRow is deliberately built to match)."""

    options_requested = Signal(str)  # app_id

    def __init__(self, app_id: str, app_name: str, desc: str,
                 requires_id: str | None, requires_name: str | None, t: dict,
                 checked: bool = False):
        super().__init__()
        self.app_id = app_id
        self.requires_id = requires_id
        self._app_name = app_name

        outer = QVBoxLayout(self)
        row_padding(outer)
        outer.setSpacing(TH.SPACE["xxs"])

        row = QHBoxLayout()
        row.setSpacing(TH.SPACE["md"])
        # Instant visual recognition: the app's own icon when it is
        # installed here, its official brand mark from the bundled asset
        # set otherwise. The app_id is what keys the brand lookup, so it
        # rides along with the name (see utils.appicons).
        self._icon = QLabel()
        self._icon.setFixedSize(APP_ICON_PX, APP_ICON_PX)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("background: transparent; border: none;")
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.checkbox = QCheckBox(app_name)
        self.checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        # Dev Hub is manual-first (False); curated app packs arrive
        # pre-selected (True) — the card already promised "the pack".
        self.checkbox.setChecked(checked)
        if desc:
            self.checkbox.setToolTip(desc)
        row.addWidget(self.checkbox)
        row.addStretch()

        self.options_btn = QPushButton("⋯")
        self.options_btn.setFixedSize(28, 24)
        self.options_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.options_btn.setToolTip("Install options for this tool (winget / official link / local file)")
        self.options_btn.clicked.connect(lambda: self.options_requested.emit(self.app_id))
        row.addWidget(self.options_btn)
        outer.addLayout(row)

        self._hint_label: QLabel | None = None
        if requires_name:
            hint = QLabel(f"↳ needs {requires_name}")
            outer.addWidget(hint)
            self._hint_label = hint

        self.apply_theme(t)

    def apply_theme(self, t: dict):
        self.setStyleSheet(TH.dev_hub_row_qss(t))
        self.checkbox.setStyleSheet(TH.checkbox_qss(t, t["accent"]))
        self.options_btn.setStyleSheet(TH.icon_ghost_button_qss(t, t["accent"]))
        # brand marks are recoloured per theme (appicons' contrast guard);
        # shell icons are theme-independent and come straight from cache
        self._icon.setPixmap(
            appicons.app_icon(self._app_name, APP_ICON_PX, t,
                              app_id=self.app_id))
        if self._hint_label is not None:
            self._hint_label.setStyleSheet(TH.label_qss(t, "caption"))

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_suggested(self, on: bool):
        """Soft amber nudge: a checked-off tool elsewhere needs this one."""
        self.setProperty("suggested", on)
        self.style().unpolish(self)
        self.style().polish(self)


# ============================================================
#  UPDATE ROW — one winget upgrade candidate (current -> available)
# ============================================================
class UpdateRow(QFrame):
    """One update candidate, built on the EXACT same structure as
    DevHubRow (checkbox carries its own label, a '⋯' wizard button sits at
    the row's right edge, a muted caption line underneath) — so an Update
    Center row and an Essential Apps / Dev Hub row read as one family, not
    two different products with different padding and chrome. Pre-checked,
    same 'curated pack' contract every other selector uses — the scan
    already promised these are real, available upgrades.

    The whole row is clickable (not just the checkbox) — ticking a box or
    tapping anywhere on the row does the same thing, matching how a native
    settings list behaves. The '⋯' opens the identical
    ToolInstallWizardDialog every other app row uses (Path A silent winget
    / Path B official link / Path C local file); Path A there just narrows
    the caller's selection down to this one AppId."""

    options_requested = Signal(str)  # app_id

    def __init__(self, app_id: str, name: str, current: str, available: str,
                 t: dict, running: list[str] | None = None):
        super().__init__()
        self.app_id = app_id
        self.app_name = name
        self.current_version = current
        self.available_version = available
        #: Process names the backend found running for this app at scan
        #: time (see Resolve-AppProcesses). Empty is the normal case.
        self.running_processes = list(running or [])
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        outer = QVBoxLayout(self)
        row_padding(outer)
        outer.setSpacing(TH.SPACE["xxs"])

        row = QHBoxLayout()
        row.setSpacing(TH.SPACE["md"])
        self.checkbox = QCheckBox(name)
        self.checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkbox.setChecked(True)
        row.addWidget(self.checkbox)

        # -- the running flag (v10.5) -------------------------
        # SAID BEFORE THE BUTTON IS PRESSED, which is the only time it is
        # actionable. Windows cannot replace a file that is open for
        # execution, so the engine closes a running target before updating
        # it - gracefully first, then by force. That is the right behaviour
        # and it is still a surprise if the first the user hears of it is
        # their editor disappearing. A row that says so up front turns it
        # into a decision: untick this one, or go and save your work.
        self._running_chip: QLabel | None = None
        if self.running_processes:
            self._running_chip = QLabel("RUNNING")
            self._running_chip.setToolTip(
                "This app is running and will be closed before it is "
                "updated.\nProcesses: "
                + ", ".join(self.running_processes))
            row.addWidget(self._running_chip)

        row.addStretch()

        self._current = QLabel(current or "—")
        row.addWidget(self._current)
        self._arrow = QLabel("→")
        row.addWidget(self._arrow)
        self._available = QLabel(available or "—")
        row.addWidget(self._available)

        self.options_btn = QPushButton("⋯")
        self.options_btn.setFixedSize(28, 24)
        self.options_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.options_btn.setToolTip(
            "Install options for this app (winget / official link / local file)")
        self.options_btn.clicked.connect(lambda: self.options_requested.emit(self.app_id))
        row.addWidget(self.options_btn)
        outer.addLayout(row)

        self._id_label = QLabel(app_id)
        outer.addWidget(self._id_label)

        self.apply_theme(t)

    def apply_theme(self, t: dict):
        self.setStyleSheet(TH.dev_hub_row_qss(t))
        self.checkbox.setStyleSheet(TH.checkbox_qss(t, t["accent"]))
        self._current.setStyleSheet(TH.version_chip_qss(t, accent=False))
        self._available.setStyleSheet(TH.version_chip_qss(t, accent=True))
        self._arrow.setStyleSheet(TH.label_qss(t, "faint"))
        self.options_btn.setStyleSheet(TH.icon_ghost_button_qss(t, t["accent"]))
        self._id_label.setStyleSheet(TH.label_qss(t, "caption"))
        if self._running_chip is not None:
            # WARN, not ERR. A running app is a heads-up the user acts on,
            # not the failure of anything — the same distinction the status
            # rail's unelevated session shield makes (see StatusRail, and
            # theme.rail_state_qss for the tone pair).
            self._running_chip.setStyleSheet(TH.micro_chip_qss(t, "warn"))

    def is_running(self) -> bool:
        return bool(self.running_processes)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def mouseReleaseEvent(self, e):
        # Click-anywhere-toggles, except on controls that already own
        # their own click (the checkbox itself, the '⋯' wizard button).
        if e.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(e.position().toPoint())
            if child not in (self.checkbox, self.options_btn):
                self.checkbox.setChecked(not self.checkbox.isChecked())
        super().mouseReleaseEvent(e)


# ============================================================
#  UPDATE CENTER — live winget scan + selective / bulk apply
# ============================================================
class UpdateCenterDialog(PulseDialog):
    """'Check for Updates': runs a live background winget scan (task
    ScanForUpdates), then presents a version audit (current vs. available)
    per app in the exact same panel geometry, row styling and action-row
    layout as SoftwareCatalogDialog — same width, same padding, same single
    primary CTA — so the two feel like the same screen with different
    data, not two different dialogs. It never installs anything itself.

    After exec():
      Accepted + selected_ids non-empty -> caller runs task
      'UpdateSelectedApps' with those AppIds through the app's normal
      request_task()/_start_task() pipeline — the same live console, Stop
      button and toast machinery as every other bulk deploy.
      Accepted + local_installer set -> caller runs task InstallLocalFile,
      exactly like SoftwareCatalogDialog's row wizards.
      Rejected -> nothing to do.
    """

    def __init__(self, parent: QWidget, ps1_path: str, t: dict):
        super().__init__(parent)
        self._t = t
        self._ps1_path = ps1_path
        self.selected_ids: list[str] = []
        self.local_installer: tuple[str, str] | None = None
        self._rows: dict[str, UpdateRow] = {}
        self._thread: QThread | None = None
        self._worker: PowerShellTask | None = None
        # True once a streamed result has flipped the dialog onto the results
        # page — decides whether a phase line belongs on the loading page or
        # in the subtitle (see _on_stage).
        self._streaming = False
        accent = t["accent"]

        panel = _dialog_chrome(self, t, accent, responsive=True)
        lay = dialog_body(panel, "md")

        head = QLabel("🔄  Update Center")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        lay.addWidget(head)

        self._subtitle = QLabel("Scanning installed apps against winget…")
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._subtitle)

        self._stack = fit_stack(QStackedWidget())
        self._stack.setStyleSheet(TH.stack_qss())
        lay.addWidget(self._stack, 1)
        self._loading_page = self._build_loading_page()
        self._stack.addWidget(self._loading_page)
        self._empty_page = self._build_empty_page()
        self._stack.addWidget(self._empty_page)
        self._error_page = self._build_error_page()
        self._stack.addWidget(self._error_page)
        self._results_page = self._build_results_page()
        self._stack.addWidget(self._results_page)
        self._stack.setCurrentWidget(self._loading_page)

        self._start_scan()

    # -- page builders ----------------------------------------------
    def _build_loading_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["lg"])
        lay.addStretch()
        self._shimmer = ShimmerBar(height=6)
        self._shimmer.set_theme(t)
        lay.addWidget(self._shimmer)
        # Kept as an attribute so the backend's live ##PULSE##STAGE| lines can
        # replace it. A shimmer bar over a fixed sentence cannot distinguish a
        # scan that is working from one that has hung, which is exactly what
        # made a 30s scan feel broken; naming the current phase can.
        self._loading_label = QLabel("Reading your installed programs…")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setWordWrap(True)
        self._loading_label.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._loading_label)
        lay.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)
        dialog_footer(lay, cancel)
        return page

    def _build_empty_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["md"])
        lay.addStretch()
        icon = QLabel("✅")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: {TH.TYPE['hero']}px; background: transparent; border: none;")
        lay.addWidget(icon)
        msg = QLabel("You're all caught up — every installed app is at its latest version.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        msg.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(msg)
        lay.addStretch()
        rescan = QPushButton("Rescan")
        rescan.setStyleSheet(TH.dialog_cancel_qss(t))
        rescan.clicked.connect(self._start_scan)
        close = QPushButton("Close")
        close.setStyleSheet(TH.dialog_go_qss(t, t["accent"]))
        close.clicked.connect(self.reject)
        dialog_footer(lay, rescan, close)
        return page

    def _build_error_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["md"])
        lay.addStretch()
        icon = QLabel("⚠️")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: {TH.TYPE['hero']}px; background: transparent; border: none;")
        lay.addWidget(icon)
        self._error_label = QLabel("")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._error_label)
        lay.addStretch()
        close = QPushButton("Close")
        close.setStyleSheet(TH.dialog_cancel_qss(t))
        close.clicked.connect(self.reject)
        retry = QPushButton("Retry")
        retry.setStyleSheet(TH.dialog_go_qss(t, t["accent"]))
        retry.clicked.connect(self._start_scan)
        dialog_footer(lay, close, retry)
        return page

    def _build_results_page(self) -> QWidget:
        """Deliberately mirrors SoftwareCatalogDialog's results layout line for
        line: Select All / Deselect All / stretch / count on the left
        toolbar (Rescan joins the left cluster so the right edge stays
        exactly the count label, like every other selector), the same
        360px scroll cap, and a Cancel + single primary-CTA bottom row —
        same sizes, same QSS factories."""
        t = self._t
        accent = t["accent"]
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(TH.SPACE["md"])

        toolbar = QHBoxLayout()
        toolbar.setSpacing(TH.SPACE["lg"])
        all_btn = QPushButton("Select All")
        all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        all_btn.setStyleSheet(TH.link_button_qss(t, accent))
        all_btn.clicked.connect(lambda: self._set_all(True))
        toolbar.addWidget(all_btn)
        none_btn = QPushButton("Deselect All")
        none_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        none_btn.setStyleSheet(TH.link_button_qss(t, accent))
        none_btn.clicked.connect(lambda: self._set_all(False))
        toolbar.addWidget(none_btn)
        rescan_btn = QPushButton("Rescan")
        rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan_btn.setStyleSheet(TH.link_button_qss(t, accent))
        rescan_btn.clicked.connect(self._start_scan)
        toolbar.addWidget(rescan_btn)
        toolbar.addStretch()
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(TH.label_qss(t, "caption"))
        toolbar.addWidget(self._count_label)
        lay.addLayout(toolbar)

        scroll = FitScroll()
        scroll.setStyleSheet(TH.scroll_area_qss(t))
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self._host_lay = scroll_host_layout(self._host, "sm")
        self._host_lay.addStretch()
        scroll.setWidget(self._host)
        lay.addWidget(scroll, 1)

        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)

        self._deploy_btn = QPushButton("Update Selected")
        self._deploy_btn.setStyleSheet(TH.dialog_go_qss(t, accent))
        self._deploy_btn.clicked.connect(self._accept_selection)

        dialog_footer(lay, cancel, self._deploy_btn)
        return page

    # -- scan lifecycle -----------------------------------------------
    def _start_scan(self):
        if self._thread is not None:
            return  # a scan is already in flight
        self._subtitle.setText("Scanning installed apps against winget…")
        self._clear_rows()
        self._streaming = False
        self._loading_label.setText("Reading your installed programs…")
        self._stack.setCurrentWidget(self._loading_page)
        self._shimmer.start()

        thread = QThread(self)
        # 240s, not 90s. The deep scan reads both registry architectures, both
        # hives and the Appx catalogue before winget's network pass even
        # starts, and the old 90s ceiling was already close on a machine with
        # a few hundred installed programs and a cold winget source cache.
        # Killing a scan that is visibly streaming results would be the worst
        # possible outcome of a change made to stop it looking hung.
        worker = PowerShellTask(self._ps1_path, "ScanForUpdates", timeout=240)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # Streamed preview (v10.3): rows land as the backend finds them, so
        # the first real results are on screen about a second in instead of
        # after the whole scan. `finished` still reconciles against the
        # authoritative payload — see _on_scan_finished.
        worker.item.connect(self._on_item_streamed)
        worker.stage.connect(self._on_stage)
        worker.finished.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    # -- streaming ----------------------------------------------------
    def _on_stage(self, text: str):
        """One backend phase line. Shown wherever the user is currently
        looking: the loading page while it is still empty, the subtitle once
        results have started arriving."""
        if not text:
            return
        if self._streaming:
            self._subtitle.setText(text)
        else:
            self._loading_label.setText(text)

    def _on_item_streamed(self, entry: object):
        """One update, the moment the backend found it.

        The FIRST item is what flips the dialog off the loading page — not a
        timer and not the scan finishing — so the list starts filling at the
        earliest moment there is anything true to show. Duplicate ids are
        ignored: the backend already de-duplicates across its scan phases,
        and this is the second line of defence that keeps a streamed row from
        ever appearing twice."""
        row = self._make_row(entry)
        if row is None:
            return
        if not self._streaming:
            self._streaming = True
            self._stack.setCurrentWidget(self._results_page)
        self._update_count()

    def _on_thread_finished(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    def _on_scan_failed(self, message: str):
        self._show_error(message or "The update scan failed to run.")

    def _on_scan_finished(self, result: TaskResult):
        self._shimmer.stop()
        if not result.success:
            self._show_error(result.message)
            return
        updates = result.data if isinstance(result.data, list) else []
        if not updates:
            # No authoritative results. Any rows streamed in must go: a
            # preview that the final document does not confirm was wrong, and
            # leaving it on screen would offer an update that isn't there.
            self._clear_rows()
            self._subtitle.setText("Every installed app is up to date.")
            self._stack.setCurrentWidget(self._empty_page)
            return
        self._reconcile_rows(updates)
        self._stack.setCurrentWidget(self._results_page)

    def _show_error(self, message: str):
        self._shimmer.stop()
        self._error_label.setText(message or "The update scan failed.")
        self._subtitle.setText("Scan failed.")
        self._stack.setCurrentWidget(self._error_page)

    # -- row management -------------------------------------------------
    def _clear_rows(self):
        # setParent(None) before deleteLater for the reason spelled out on
        # StartupManagerDialog._clear_rows: a deferred delete leaves the row
        # in the widget tree, and a rescan that streams new rows in
        # immediately would stack them on top of the outgoing ones.
        self._rows.clear()
        while self._host_lay.count() > 1:   # keep the trailing stretch
            item = self._host_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _make_row(self, entry: object) -> UpdateRow | None:
        """Build and append one UpdateRow, or None if `entry` is unusable or
        already on screen. The single place a row is created, shared by the
        streamed path and the final reconciliation, so a row can never differ
        depending on which one produced it."""
        if not isinstance(entry, dict):
            return None
        app_id = str(entry.get("Id", "")).strip()
        if not app_id or app_id in self._rows:
            return None
        name = str(entry.get("Name") or app_id)
        current = str(entry.get("CurrentVersion") or "—")
        available = str(entry.get("AvailableVersion") or "—")
        # Present on BOTH the streamed preview rows and the final DATA
        # payload (see Invoke-DeepUpdateScan's $Collect), so the flag does
        # not flicker off when the authoritative document lands. Defensive
        # about shape: a backend that predates the field simply reports
        # nothing running, which is the correct degradation.
        running = entry.get("RunningProcesses")
        running = [str(n) for n in running] if isinstance(running, list) else []
        if entry.get("Running") and not running:
            running = ["(unknown)"]
        row = UpdateRow(app_id, name, current, available, self._t, running)
        row.checkbox.toggled.connect(self._update_count)
        row.options_requested.connect(self._open_tool_wizard)
        self._rows[app_id] = row
        self._host_lay.insertWidget(self._host_lay.count() - 1, row)
        return row

    def _reconcile_rows(self, updates: list):
        """Settle the streamed preview against the authoritative payload.

        Rows are ADDED for anything the stream missed and REMOVED for
        anything the final document does not contain — a preview row that the
        backend did not confirm must not survive, or the dialog would offer an
        update that no longer exists. Rows already on screen are left in place
        rather than rebuilt, so a checkbox the user has already unticked keeps
        its state instead of silently re-arming itself when the scan lands."""
        confirmed: list[str] = []
        for entry in updates:
            if not isinstance(entry, dict):
                continue
            app_id = str(entry.get("Id", "")).strip()
            if not app_id:
                continue
            confirmed.append(app_id)
            self._make_row(entry)

        for app_id in [a for a in self._rows if a not in confirmed]:
            row = self._rows.pop(app_id)
            self._host_lay.removeWidget(row)
            row.setParent(None)
            row.deleteLater()

        # Same sentence shape SoftwareCatalogDialog uses for its selection —
        # one consistent voice across every selector in the app.
        self._subtitle.setText(
            f"All {len(self._rows)} updates are pre-selected — untick anything you don't "
            "want, or use a row's ⋯ for more install options.")
        self._update_count()

    def _set_all(self, checked: bool):
        for row in self._rows.values():
            row.checkbox.setChecked(checked)

    def _update_count(self, _checked: bool = False):
        count = sum(1 for r in self._rows.values() if r.is_checked())
        self._count_label.setText(f"{count} selected")
        total = len(self._rows)
        if count and count == total:
            self._deploy_btn.setText(f"Update All ({count})")
        else:
            self._deploy_btn.setText(f"Update Selected ({count})" if count else "Update Selected")
        self._deploy_btn.setEnabled(count > 0)

    # -- acceptance -------------------------------------------------
    def _accept_selection(self):
        self.selected_ids = [aid for aid, row in self._rows.items() if row.is_checked()]
        if not self.selected_ids:
            return
        if not self._confirm_running_apps():
            return
        self.accept()

    def _confirm_running_apps(self) -> bool:
        """Ask before anything gets closed. True to proceed.

        THE POINT IS THE TIMING, not the dialog. The engine closes a
        running target before replacing it (Stop-AppProcesses) because
        Windows will not overwrite a file that is open for execution -
        gracefully first, by force after six seconds. That is correct, and
        it is still a nasty surprise if the first the user hears of it is
        their editor vanishing mid-sentence.

        Said here, it is a decision instead: proceed, or cancel and untick
        the row. The apps are NAMED rather than counted, because "3 apps
        will be closed" is not enough to decide with - the whole question
        is WHICH ones.

        Silent when nothing selected is running, which is the common case:
        a confirmation that always appears is one nobody reads.
        """
        running = [row for aid, row in self._rows.items()
                   if row.is_checked() and row.is_running()]
        if not running:
            return True
        names = ", ".join(sorted(r.app_name for r in running))
        confirm = ConfirmDialog(self, {
            "icon": "\u26a0\ufe0f",
            "title": "Some of these apps are running",
            "desc": (
                f"{names} {'is' if len(running) == 1 else 'are'} open right "
                "now. Windows cannot replace files that are in use, so "
                f"{'this app' if len(running) == 1 else 'these apps'} will "
                "be closed before the update is applied — you will be asked "
                "to save any unsaved work first.\n\n"
                "Cancel if you would rather untick "
                f"{'it' if len(running) == 1 else 'them'} and update the "
                "rest."),
        }, self._t)
        return confirm.exec() == QDialog.DialogCode.Accepted

    # -- per-app wizard ("⋯") --------------------------------------------
    def _open_tool_wizard(self, app_id: str):
        row = self._rows.get(app_id)
        if row is None:
            return
        desc = f"Update available: {row.current_version} → {row.available_version}"
        wizard = ToolInstallWizardDialog(self, app_id, row.app_name, desc, "", self._t)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        if wizard.mode == "winget":
            self._set_all(False)
            row.checkbox.setChecked(True)
            self._accept_selection()
        elif wizard.mode == "local" and wizard.local_path:
            self.local_installer = (row.app_name, wizard.local_path)
            self.accept()

    def reject(self):
        if self._worker is not None:
            self._worker.cancel()
        super().reject()

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


# ============================================================
#  SELF-UPDATE — Pulse updating Pulse (utils/updater.py's GUI call site)
# ============================================================
class SelfUpdateDialog(PulseDialog):
    """One release, from announcement to hand-off. NOT UpdateCenterDialog's
    list-of-rows shape: a self-update is a single artifact, so this is a
    small page stack (notes -> progress -> ready -> error) rather than a
    selector.

    Constructed with an Update already in hand (main.py's background/manual
    check calls utils.updater.check() first) — this dialog owns only the
    download() + verify() half of the pipeline, on its own worker/thread
    exactly like UpdateCenterDialog owns its scan. apply() deliberately
    stays out: it quits the app, which is the caller's call to make, not a
    dialog's. After exec():

      Accepted + installer_path set -> caller calls updater.apply(path)
                                        and quits.
      Rejected -> nothing to do; a partial download (if any) is left for
                  prune() to clean up later.
    """

    def __init__(self, parent: QWidget, t: dict, update: "updater.Update"):
        super().__init__(parent)
        self._t = t
        self._update = update
        self._thread: QThread | None = None
        self._worker: SelfUpdateInstallWorker | None = None
        self._user_cancelled = False
        self.installer_path: str | None = None
        can_apply, self._apply_reason = updater.can_apply()
        self._can_apply = can_apply
        accent = t["accent"]

        panel = _dialog_chrome(self, t, accent, width=480)
        lay = dialog_body(panel, "md")

        head = QLabel(f"🚀  Pulse v{update.version} is available")
        head.setStyleSheet(TH.label_qss(t, "dialog"))
        head.setWordWrap(True)
        lay.addWidget(head)

        meta_bits = [f"{update.size_mb:.1f} MB"]
        if update.prerelease:
            meta_bits.append("pre-release")
        self._meta = QLabel("  ·  ".join(meta_bits))
        self._meta.setStyleSheet(TH.label_qss(t, "caption"))
        lay.addWidget(self._meta)

        self._stack = fit_stack(QStackedWidget())
        self._stack.setStyleSheet(TH.stack_qss())
        lay.addWidget(self._stack, 1)
        self._notes_page = self._build_notes_page()
        self._stack.addWidget(self._notes_page)
        self._progress_page = self._build_progress_page()
        self._stack.addWidget(self._progress_page)
        self._ready_page = self._build_ready_page()
        self._stack.addWidget(self._ready_page)
        self._error_page = self._build_error_page()
        self._stack.addWidget(self._error_page)
        self._stack.setCurrentWidget(self._notes_page)

    # -- page builders ----------------------------------------------
    def _build_notes_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(TH.SPACE["md"])

        scroll = FitScroll()
        scroll.setFixedHeight(200)
        scroll.setStyleSheet(TH.scroll_area_qss(t))
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host_lay = scroll_host_layout(host, "sm")
        notes = QLabel(self._update.notes or "No release notes were published.")
        notes.setWordWrap(True)
        notes.setStyleSheet(TH.label_qss(t, "body"))
        host_lay.addWidget(notes)
        host_lay.addStretch()
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        if not self._can_apply:
            # Running from source, or some other build this updater refuses
            # to hand an installer to (see updater.can_apply). The honest
            # move is to say so and offer the release page, not a Download
            # & Install button that would fail the moment it's clicked.
            reason = QLabel(f"ℹ️  {self._apply_reason}")
            reason.setWordWrap(True)
            reason.setStyleSheet(TH.label_qss(t, "caption"))
            lay.addWidget(reason)

        lay.addSpacing(TH.SPACE["xs"])
        row = QHBoxLayout()
        row.addStretch()
        later = QPushButton("Later")
        size_dialog_button(later)
        later.setStyleSheet(TH.dialog_cancel_qss(t))
        later.clicked.connect(self.reject)
        row.addWidget(later)

        if self._can_apply:
            go = QPushButton("Download && Install")
            size_dialog_button(go)
            go.clicked.connect(self._start_download)
        else:
            go = QPushButton("View Release")
            size_dialog_button(go)
            go.clicked.connect(self._open_release_page)
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.setStyleSheet(TH.dialog_go_qss(t, t["accent"]))
        row.addWidget(go)
        lay.addLayout(row)
        return page

    def _build_progress_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["lg"])
        lay.addStretch()
        self._shimmer = ShimmerBar(height=6)
        self._shimmer.set_theme(t)
        lay.addWidget(self._shimmer)
        self._progress_label = QLabel("Downloading…")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_label.setWordWrap(True)
        self._progress_label.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._progress_label)
        lay.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        size_dialog_button(cancel)
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)
        return page

    def _build_ready_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["md"])
        lay.addStretch()
        icon = QLabel("✅")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: {TH.TYPE['hero']}px; background: transparent; border: none;")
        lay.addWidget(icon)
        msg = QLabel(
            f"Verified — v{self._update.version}'s SHA-256 matches the "
            "published digest. Pulse will close and Setup will take over.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        msg.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(msg)
        lay.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        later = QPushButton("Later")
        size_dialog_button(later)
        later.setStyleSheet(TH.dialog_cancel_qss(t))
        later.clicked.connect(self.reject)
        row.addWidget(later)
        go = QPushButton("Restart && Update")
        size_dialog_button(go)
        go.setStyleSheet(TH.dialog_go_qss(t, t["accent"]))
        go.clicked.connect(self.accept)
        row.addWidget(go)
        lay.addLayout(row)
        return page

    def _build_error_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["md"])
        lay.addStretch()
        icon = QLabel("⚠️")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: {TH.TYPE['hero']}px; background: transparent; border: none;")
        lay.addWidget(icon)
        self._error_label = QLabel("")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._error_label)
        lay.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close")
        size_dialog_button(close)
        close.setStyleSheet(TH.dialog_cancel_qss(t))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        retry = QPushButton("Retry")
        size_dialog_button(retry)
        retry.setStyleSheet(TH.dialog_go_qss(t, t["accent"]))
        retry.clicked.connect(self._start_download)
        row.addWidget(retry)
        lay.addLayout(row)
        return page

    # -- release page (dev builds, and the error page's escape hatch) ----
    def _open_release_page(self):
        url = f"https://github.com/{updater.REPO}/releases/tag/{self._update.tag}"
        QDesktopServices.openUrl(QUrl(url))

    # -- download / verify --------------------------------------------
    def _start_download(self):
        if self._thread is not None:
            return
        self._user_cancelled = False
        self._progress_label.setText("Downloading…")
        self._shimmer.start()
        self._stack.setCurrentWidget(self._progress_page)

        thread = QThread(self)
        worker = SelfUpdateInstallWorker(self._update)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.verifying.connect(self._on_verifying)
        worker.finished.connect(self._on_install_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_progress(self, received: int, total: int):
        mb = received / (1024 * 1024)
        total_mb = (total / (1024 * 1024)) if total else self._update.size_mb
        self._progress_label.setText(f"Downloading… {mb:.1f} / {total_mb:.1f} MB")

    def _on_verifying(self):
        self._progress_label.setText("Verifying SHA-256…")

    def _on_install_finished(self, ok: bool, payload: str):
        self._shimmer.stop()
        if self._user_cancelled:
            # reject() already fired (it's what set this flag) and the
            # dialog is on its way down — nothing left to show.
            return
        if ok:
            self.installer_path = payload
            self._stack.setCurrentWidget(self._ready_page)
        else:
            self._error_label.setText(payload or "The update could not be installed.")
            self._stack.setCurrentWidget(self._error_page)

    def _on_thread_finished(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    def reject(self):
        # Set BEFORE cancelling: worker.finished can be delivered the
        # instant cancel() unblocks the download loop, and _on_install_
        # finished must already see this dialog as closing rather than
        # switch it to the error page for a download that only stopped
        # because the user closed it.
        self._user_cancelled = True
        if self._worker is not None:
            self._worker.cancel()
        super().reject()

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)


# ============================================================
#  STARTUP ROW — one startup entry with a live enable/disable switch
# ============================================================
class BloatRow(QFrame):
    """One catalogued package: its plaque, its name, whether it is actually
    on this machine, and the sentence explaining what removing it costs.

    THE NOTE IS NOT DECORATION. Every other selector in the app offers
    things the user is choosing to ADD, where a description is a nicety.
    This one removes software, and half the catalog has a consequence
    worth knowing before the box is ticked — removing Phone Link ends
    notification mirroring, removing the Gaming Overlay takes Game Bar's
    screen capture with it, "Paint 3D" is not the Paint most people mean.
    So the note rides on the row itself rather than in a tooltip nobody
    hovers.

    A row for a package that is NOT installed still renders, greyed and
    unticked. Hiding them would leave the user unable to tell "Pulse does
    not remove this" from "this is already gone", which is the difference
    between a clean machine and an incomplete catalog.
    """

    #: The plaque glyph per catalog group. One mark per LAYER rather than
    #: per app: fifty distinct icons would be a spectrum, which is exactly
    #: what the palette pass removed from the rest of the app.
    _GLYPHS = {
        "promo":  "delete",
        "core":   "layers",
        "gaming": "game",
        "codec":  "disk",
    }

    def __init__(self, entry: dict, t: dict):
        super().__init__()
        self.entry_id = str(entry.get("Id") or "")
        self.group = str(entry.get("Group") or "promo")
        self.detected = bool(entry.get("Detected"))
        self.optional = bool(entry.get("Optional"))
        self._name = str(entry.get("Name") or self.entry_id)

        outer = QHBoxLayout(self)
        row_padding(outer)
        outer.setSpacing(TH.SPACE["md"])

        # THE SHARED 36px WELL, the same object a card and a nav entry
        # wear (see theme.PLAQUE_SIZE) rather than this dialog's own idea
        # of an icon.
        self.plaque = IconPlaque("")
        self.plaque.setFixedSize(TH.PLAQUE_SIZE, TH.PLAQUE_SIZE)
        glyph_key = self._GLYPHS.get(self.group, "delete")
        char, is_fluent = TH.glyph(glyph_key)
        self._plaque_font = TH.icon_font(TH.ICON["plaque"]) if is_fluent else None
        self.plaque.setText(char)
        outer.addWidget(self.plaque, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(TH.SPACE["xxs"])

        name_row = QHBoxLayout()
        name_row.setSpacing(TH.SPACE["sm"])
        self.checkbox = QCheckBox(self._name)
        self.checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkbox.setEnabled(self.detected)
        name_row.addWidget(self.checkbox)

        self._badge = QLabel("DETECTED" if self.detected else "NOT PRESENT")
        name_row.addWidget(self._badge)

        self._optional_badge: QLabel | None = None
        if self.optional:
            self._optional_badge = QLabel("OPTIONAL")
            self._optional_badge.setToolTip(
                "Left unticked by a Select All. Removing the Xbox stack can "
                "break Game Bar's screen capture and Store game sign-in.")
            name_row.addWidget(self._optional_badge)
        name_row.addStretch()
        col.addLayout(name_row)

        note = str(entry.get("Note") or "")
        packages = list(entry.get("Installed") or []) + list(entry.get("Provisioned") or [])
        if packages:
            # The real package names, once, at caption weight. A purge is
            # the one operation where "what exactly are you about to
            # delete" is a fair question, and the answer is not the
            # friendly name.
            shown = ", ".join(sorted(set(packages))[:3])
            if len(set(packages)) > 3:
                shown += ", …"
            note = f"{note}  ·  {shown}" if note else shown
        self._note = QLabel(note)
        self._note.setWordWrap(True)
        col.addWidget(self._note)
        outer.addLayout(col, 1)

        self.apply_theme(t)

    def set_checked(self, on: bool):
        """Tick only what is actually here. A Select All that ticked
        absent packages would report a purge of things that were never
        installed."""
        if self.detected:
            self.checkbox.setChecked(on)

    def is_selected(self) -> bool:
        return bool(self.detected and self.checkbox.isChecked())

    def apply_theme(self, t: dict):
        self.setProperty("disabled_item", not self.detected)
        self.setStyleSheet(TH.startup_row_qss(t))
        accent = t["accent"] if self.detected else t["text_faint"]
        self.plaque.apply_theme(t, accent)
        if self._plaque_font is not None:
            self.plaque.setFont(self._plaque_font)
        self.checkbox.setStyleSheet(TH.checkbox_qss(t, t["accent"]))
        self._badge.setStyleSheet(
            TH.micro_chip_qss(t, "warn" if self.detected else "neutral"))
        if self._optional_badge is not None:
            self._optional_badge.setStyleSheet(TH.micro_chip_qss(t, "accent"))
        self._note.setStyleSheet(TH.label_qss(t, "caption"))
        self.style().unpolish(self)
        self.style().polish(self)


# ============================================================
#  BLOATWARE PURGE — scan, classify, remove permanently
# ============================================================
class BloatwarePurgeDialog(PulseDialog):
    """Scans the machine against the bloatware catalog and hands back the
    Ids to purge.

    IT DECIDES, IT DOES NOT DO. Unlike the Startup Manager — which owns its
    own toggles and closes having already changed the machine — this dialog
    returns `selected_ids` and lets main.py run RemoveBloatware through the
    ordinary task pipeline. That is deliberate: a purge takes a restore
    point, writes policy keys and can run for minutes, and every one of
    those wants the app's live console, its concurrency guard and its
    single-task queue rather than a private worker inside a modal.

    THE SCAN IS UNPRIVILEGED, THE PURGE IS NOT. Enumerating packages needs
    no rights, so opening this dialog never raises a UAC prompt; the task
    it hands back is admin-gated like every other machine-scope operation.

    Two sections, because the catalog has two kinds of entry and they are
    not the same decision:

        RECOMMENDED   promo stubs, redundant Microsoft apps, codec
                      leftovers. Ticked by Select All.
        OPTIONAL      the Xbox stack. Never ticked by Select All, because
                      Game Bar's overlay is load-bearing for screen
                      capture and Store games sign in through the identity
                      provider.
    """

    #: Section order and copy. `optional` decides which side of the Select
    #: All line a group sits on, so a new catalog group joins the right
    #: half by declaring itself here rather than by editing the CTA.
    SECTIONS = [
        ("promo",  "Pre-installed stubs and promotions", False),
        ("core",   "Redundant Windows apps", False),
        ("codec",  "Third-party leftovers", False),
        ("gaming", "Xbox and gaming (optional)", True),
    ]

    def __init__(self, parent: QWidget, ps1_path: str, t: dict):
        super().__init__(parent)
        self._t = t
        self._ps1_path = ps1_path
        self.selected_ids: list[str] = []
        self._caveat = ""
        self._rows: dict[str, BloatRow] = {}
        #: (header label, its rows, how many of them are present) — the
        #: grouping _sync_visibility folds and unfolds.
        self._sections: list[tuple[QLabel, list, int]] = []
        self._thread: QThread | None = None
        self._worker: PowerShellTask | None = None

        accent = t["accent"]
        panel = _dialog_chrome(self, t, accent, responsive=True)
        lay = dialog_body(panel, "sm")

        title_col = QVBoxLayout()
        title_col.setSpacing(TH.SPACE["xxs"])
        title = QLabel("🧹  Bloatware Purge")
        title.setStyleSheet(TH.label_qss(t, "dialog"))
        title_col.addWidget(title)
        self._subtitle = QLabel("Scanning installed and staged packages…")
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(TH.label_qss(t, "body"))
        title_col.addWidget(self._subtitle)
        lay.addLayout(title_col)

        self._stack = fit_stack(QStackedWidget())
        self._stack.setStyleSheet(TH.stack_qss())
        lay.addWidget(self._stack, 1)
        self._loading_page = self._build_loading_page()
        self._stack.addWidget(self._loading_page)
        self._error_page = self._build_error_page()
        self._stack.addWidget(self._error_page)
        self._results_page = self._build_results_page()
        self._stack.addWidget(self._results_page)
        self._stack.setCurrentWidget(self._loading_page)

        self._footer = dialog_footer(lay, self._cancel_btn, self._purge_btn)
        self._start_scan()

    # -- pages ---------------------------------------------------------
    def _build_loading_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["lg"])
        lay.addStretch()
        self._shimmer = ShimmerBar(height=6)
        self._shimmer.set_theme(t)
        lay.addWidget(self._shimmer)
        self._loading_label = QLabel(
            "Reading installed packages, staged provisioning templates and "
            "the uninstall registry…")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setWordWrap(True)
        self._loading_label.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._loading_label)
        lay.addStretch()
        return page

    def _build_error_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["md"])
        lay.addStretch()
        icon = QLabel("⚠️")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"font-size: {TH.TYPE['hero']}px; background: transparent; border: none;")
        lay.addWidget(icon)
        self._error_label = QLabel("")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._error_label)
        lay.addStretch()
        return page

    def _build_results_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(TH.SPACE["sm"])

        bar = QHBoxLayout()
        bar.setSpacing(TH.SPACE["lg"])
        self._all_btn = QPushButton("Select All Bloatware")
        self._all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._all_btn.setToolTip(
            "Ticks every DETECTED package outside the optional Xbox section.")
        self._all_btn.setStyleSheet(TH.link_button_qss(t, t["accent"]))
        self._all_btn.clicked.connect(lambda: self._select_all(True))
        bar.addWidget(self._all_btn)
        self._none_btn = QPushButton("Deselect All")
        self._none_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._none_btn.setStyleSheet(TH.link_button_qss(t, t["accent"]))
        self._none_btn.clicked.connect(lambda: self._select_all(False))
        bar.addWidget(self._none_btn)
        bar.addStretch()
        # THE CATALOG IS 48 ENTRIES AND A CLEAN MACHINE HAS ONE OF THEM.
        # Rendering every row unconditionally was the first build's
        # behaviour and it buried the only result that mattered under
        # forty-seven "NOT PRESENT" rows in three sections the user had to
        # scroll past. Hiding them is not hiding information — the section
        # header still reports "1 of 25 present", so the catalog's size and
        # this machine's score are both on screen — it is putting the
        # answer above the evidence.
        #
        # The toggle exists because the evidence is a fair question: "does
        # Pulse know about TikTok?" is answerable in one click rather than
        # by reading the source.
        self._show_absent = QCheckBox("Show packages that aren't installed")
        self._show_absent.setCursor(Qt.CursorShape.PointingHandCursor)
        self._show_absent.setStyleSheet(TH.checkbox_qss(t, t["accent"]))
        self._show_absent.toggled.connect(self._sync_visibility)
        bar.addWidget(self._show_absent)
        self._count = QLabel("0 selected")
        self._count.setStyleSheet(TH.label_qss(t, "caption"))
        bar.addWidget(self._count)
        lay.addLayout(bar)

        self._scroll = FitScroll()
        self._scroll.setStyleSheet(TH.scroll_area_qss(t))
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self._host_lay = scroll_host_layout(host, "sm")
        self._host_lay.addStretch()
        self._scroll.setWidget(host)
        lay.addWidget(self._scroll, 1)

        self._empty = QLabel("Nothing catalogued is installed — this system is clean.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(TH.empty_state_qss(t))
        self._empty.hide()
        lay.addWidget(self._empty)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet(TH.dialog_cancel_qss(t))
        self._cancel_btn.clicked.connect(self.reject)
        self._purge_btn = QPushButton("Safe Purge")
        self._purge_btn.setStyleSheet(TH.dialog_go_qss(t, t["err"]))
        self._purge_btn.setEnabled(False)
        self._purge_btn.clicked.connect(self._accept_selection)
        return page

    # -- scan ----------------------------------------------------------
    def _start_scan(self):
        if self._thread is not None:
            return
        self._shimmer.start()
        thread = QThread(self)
        worker = PowerShellTask(self._ps1_path, "BloatwareScan", timeout=180)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
        thread.finished.connect(self._cleanup)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_scan_finished(self, result: TaskResult):
        self._shimmer.stop()
        message = str(result.message or "")
        marker = "Staged packages could not be read"
        self._caveat = message[message.index(marker):] if marker in message else ""
        entries = result.data if isinstance(result.data, list) else None
        if not result.success or entries is None:
            self._on_scan_failed(result.message or "The package scan returned nothing.")
            return
        self._render(entries)

    def _on_scan_failed(self, message: str):
        self._shimmer.stop()
        self._error_label.setText(
            f"{message}\n\nNothing was changed. Close this and try again, or "
            "run the purge without a selection to remove the recommended set.")
        self._stack.setCurrentWidget(self._error_page)
        self._purge_btn.setEnabled(False)

    def _cleanup(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    # -- rendering ------------------------------------------------------
    def _render(self, entries: list):
        t = self._t
        by_group: dict[str, list] = {}
        for entry in entries:
            if isinstance(entry, dict):
                by_group.setdefault(str(entry.get("Group") or "promo"), []).append(entry)

        detected = 0
        for key, title, _optional in self.SECTIONS:
            rows = by_group.get(key) or []
            # Detected first inside a section, then alphabetically. A user
            # opening this wants to see what is actually there, and a list
            # that leads with fourteen "NOT PRESENT" rows buries it.
            rows.sort(key=lambda e: (not e.get("Detected"), str(e.get("Name") or "")))
            if not rows:
                continue
            present = sum(1 for e in rows if e.get("Detected"))
            detected += present
            header = self._add_header(f"{title}  ·  {present} of {len(rows)} present")
            built = []
            for entry in rows:
                row = BloatRow(entry, t)
                row.checkbox.toggled.connect(self._sync_count)
                self._rows[row.entry_id] = row
                self._insert(row)
                built.append(row)
            # The header travels WITH its rows: a section whose every entry
            # is hidden must not leave a heading floating over the next
            # section's contents.
            self._sections.append((header, built, present))

        self._empty.setVisible(detected == 0)
        self._scroll.setVisible(detected > 0 or bool(self._rows))
        summary = (
            "Nothing catalogued is installed on this machine."
            if detected == 0 else
            f"{detected} catalogued package(s) found. Ticked packages are "
            "removed for every profile, deprovisioned so they cannot return "
            "after a Windows update, and their Start menu promotions "
            "disabled.")
        # The backend appends a caveat when it could not read the staged
        # packages (that read needs elevation). Passing it through matters:
        # "clean" and "clean as far as I could see" are different claims,
        # and the second one is what an unelevated scan can make.
        if self._caveat:
            summary = f"{summary}  {self._caveat}"
        self._subtitle.setText(summary)
        # PRE-TICKED, and only the recommended half. The catalog's whole
        # premise is that these should not be here; making the user tick
        # thirty boxes to agree would be theatre. The optional section is
        # the exception and stays untouched.
        self._select_all(True)
        if detected == 0:
            # Nothing to fold away, and nothing to fold it behind.
            self._show_absent.setChecked(True)
            self._show_absent.setEnabled(False)
        self._sync_visibility()
        self._stack.setCurrentWidget(self._results_page)
        self._scroll.refresh()

    def _add_header(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setStyleSheet(TH.label_qss(self._t, "section"))
        label.setContentsMargins(TH.SPACE["xs"], TH.SPACE["sm"],
                                 TH.SPACE["xs"], 0)
        self._insert(label)
        return label

    def _sync_visibility(self):
        """Show what is here; show the rest only when asked.

        On a machine where NOTHING was detected the toggle is forced on
        and disabled: an empty list under a "1 of 25 present" header would
        read as the dialog having failed to load, and there is nothing to
        bury it under anyway."""
        show_all = self._show_absent.isChecked() or not self._any_detected()
        for header, rows, present in self._sections:
            for row in rows:
                row.setVisible(show_all or row.detected)
            header.setVisible(show_all or present > 0)
        self._scroll.refresh()

    def _any_detected(self) -> bool:
        return any(row.detected for row in self._rows.values())

    def _insert(self, widget: QWidget):
        self._host_lay.insertWidget(self._host_lay.count() - 1, widget)

    # -- selection -------------------------------------------------------
    def _select_all(self, on: bool):
        """Select All means the RECOMMENDED set, never the optional one.

        A control labelled "Select All Bloatware" that silently ticked the
        Xbox stack would be the single most damaging click in the app: Game
        Bar's overlay is what Win+G opens and what most capture tools hook,
        and removing the identity provider can lock a user out of games
        they already own. Deselect All is unconditional — turning
        everything off is never the dangerous direction."""
        optional_groups = {key for key, _title, opt in self.SECTIONS if opt}
        for row in self._rows.values():
            if on and row.group in optional_groups:
                continue
            row.set_checked(on)
        self._sync_count()

    def _sync_count(self):
        chosen = [r for r in self._rows.values() if r.is_selected()]
        self._count.setText(f"{len(chosen)} selected")
        self._purge_btn.setEnabled(bool(chosen))
        self._purge_btn.setText(
            "Safe Purge" if not chosen else f"Safe Purge ({len(chosen)})")

    def _accept_selection(self):
        self.selected_ids = [r.entry_id for r in self._rows.values() if r.is_selected()]
        if not self.selected_ids:
            return
        self.accept()

    # -- lifecycle -------------------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)

    def done(self, code: int):
        """Settle the scan before the wrapper goes away — the same guard
        every dialog that owns a worker thread carries (see
        PulseDialog.done)."""
        if self._worker is not None:
            self._worker.cancel()
        super().done(code)


class StartupRow(QFrame):
    """One startup entry: name, boot-impact badge, recommendation tag and
    the backend's plain-language reason, plus a ToggleSwitch that fires
    the disable/enable task the instant it flips — no separate 'Apply'
    step, per the brief's 'fluid, native toggle switches ... instantly'."""

    _REC_LABELS = {"Disable": "Recommended to Disable", "Keep": "Safe to Keep", "Review": "Worth Reviewing"}

    #: The row's fixed right-hand column, and the switch lives in it alone.
    #:
    #: A ToggleSwitch is 42px wide and was being added straight into the
    #: row's own QHBoxLayout, so the column it occupied was whatever was
    #: left after the name and its two badges had taken theirs. That is the
    #: crowding defect: a long Run-key name widened the text block, the
    #: badges slid right, and on the longest names they arrived hard against
    #: the switch with no gutter between the last badge and a control the
    #: user is about to click.
    #:
    #: A FIXED cell makes the switch's position a property of the row rather
    #: than of the entry's name — every switch in the list lines up on one
    #: axis, at one x, however long the name beside it is. 80px is the 42px
    #: control plus enough air either side that the badge before it and the
    #: card edge after it both keep a real margin.
    SWITCH_COL_W = 80

    #: What the NAME may ask for. It is an ElidedCaption, so this caps the
    #: request rather than the grant: the label takes what the row can spare
    #: up to here, elides in the MIDDLE past it (see the note on the caption
    #: below), and reports a minimum of zero — which is what actually stops
    #: it pushing anything.
    NAME_MAX_W = 380

    toggle_requested = Signal(str, bool)   # (encoded_id, want_enabled)

    def __init__(self, item: dict, t: dict):
        super().__init__()
        self.item_id = str(item["Id"])
        self._enabled = bool(item["Enabled"])
        self._impact = str(item.get("Impact") or "Medium")
        self._recommendation = str(item.get("Recommendation") or "Review")
        # A protected component (audio stack, security agent, input driver —
        # see StartupProtectedRules in 05-Startup.ps1). It reads as an
        # ordinary "Safe to Keep" otherwise, which understates it: the row
        # still toggles, but the user should know this one is load-bearing
        # before they flip it.
        self._protected = bool(item.get("Protected"))

        outer = QHBoxLayout(self)
        row_padding(outer)
        outer.setSpacing(TH.SPACE["md"])

        col = QVBoxLayout()
        col.setSpacing(TH.SPACE["xs"])
        name_row = QHBoxLayout()
        name_row.setSpacing(TH.SPACE["sm"])
        # MIDDLE elision, and a zero minimum. A Run key can be named
        # "MicrosoftEdgeAutoLaunch_1C40B5E8F2..." — long enough that a plain
        # QLabel's minimum width became a floor the whole row had to honour,
        # which is what drove the badges into the switch. ElideMiddle keeps
        # both ends of the identifier, which is where two entries from the
        # same publisher actually differ; ElideRight would render every
        # Edge auto-launch key as the same string.
        self._name = ElidedCaption(max_width=self.NAME_MAX_W,
                                   elide=Qt.TextElideMode.ElideMiddle)
        self._name.setFullText(str(item.get("Name", "")))
        self._name.setToolTip(str(item.get("Name", "")))
        name_row.addWidget(self._name)
        self._impact_badge = QLabel(f"{self._impact.upper()} IMPACT")
        name_row.addWidget(self._impact_badge)
        self._rec_badge = QLabel(
            "System Critical" if self._protected
            else self._REC_LABELS.get(self._recommendation, self._recommendation))
        name_row.addWidget(self._rec_badge)
        name_row.addStretch()
        if self._protected:
            self.setToolTip(
                "Pulse never recommends disabling this one, and “Optimize "
                "Startup” will not touch it. You can still toggle it by hand.")
        col.addLayout(name_row)

        type_label = "Registry (Run key)" if item.get("Type") == "Registry" else "Startup folder shortcut"
        reason = str(item.get("Reason") or "")
        self._meta = QLabel(f"{type_label}  ·  {reason}")
        self._meta.setWordWrap(True)
        col.addWidget(self._meta)
        outer.addLayout(col, 1)

        # The switch's own column — see SWITCH_COL_W. The cell is what is
        # added to the row; the switch is centred inside it, so the control
        # sits at the same x on every row regardless of what precedes it.
        self.switch = ToggleSwitch(t, checked=self._enabled)
        self.switch.toggled.connect(self._on_switch)
        switch_cell = QWidget()
        switch_cell.setFixedWidth(self.SWITCH_COL_W)
        switch_cell.setStyleSheet("background: transparent; border: none;")
        cell_lay = QHBoxLayout(switch_cell)
        cell_lay.setContentsMargins(0, 0, 0, 0)
        cell_lay.addStretch()
        cell_lay.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
        cell_lay.addStretch()
        outer.addWidget(switch_cell, 0, Qt.AlignmentFlag.AlignVCenter)

        self.apply_theme(t)
        self._sync_disabled_prop()

    def _on_switch(self, checked: bool):
        self.toggle_requested.emit(self.item_id, checked)

    def set_enabled_state(self, enabled: bool):
        self._enabled = enabled
        self.switch.set_checked_silent(enabled)
        self._sync_disabled_prop()

    def set_busy(self, busy: bool):
        self.switch.set_busy(busy)

    def _sync_disabled_prop(self):
        self.setProperty("disabled_item", not self._enabled)
        self.style().unpolish(self)
        self.style().polish(self)

    def apply_theme(self, t: dict):
        self.setStyleSheet(TH.startup_row_qss(t))
        self._name.setStyleSheet(TH.label_qss(t, "card"))
        # The stylesheet changes the metrics the elision was measured
        # against, so re-run it against the new font rather than leaving
        # the row showing a string elided for the previous theme's.
        self._name.setFullText(self._name.fullText())
        self._impact_badge.setStyleSheet(TH.impact_badge_qss(t, self._impact))
        self._rec_badge.setStyleSheet(
            TH.recommendation_badge_qss(t, self._recommendation, self._protected))
        self._meta.setStyleSheet(TH.label_qss(t, "caption"))
        self.switch.apply_theme(t)


# ============================================================
#  STARTUP MANAGER — intelligent optimization hub
# ============================================================
class StartupManagerDialog(PulseDialog):
    """Startup Report, overhauled into an optimization hub: scans Run keys
    + Startup folders (task StartupReport, JSON payload), groups every
    entry under the backend's recommendation, and lets the user flip each
    one live via ToggleSwitch — every click round-trips through its own
    worker immediately. Nothing is handed back to the caller: this dialog
    is fully self-contained (unlike SoftwareCatalogDialog/UpdateCenterDialog,
    which only decide what a *later* task should run), so main.py just
    opens it and moves on when it closes."""

    def __init__(self, parent: QWidget, ps1_path: str, t: dict):
        super().__init__(parent)
        self._t = t
        self._ps1_path = ps1_path
        self._rows: dict[str, StartupRow] = {}
        self._items: dict[str, dict] = {}

        self._scan_thread: QThread | None = None
        self._scan_worker: PowerShellTask | None = None
        self._toggle_thread: QThread | None = None
        self._toggle_worker: PowerShellTask | None = None
        self._toggle_queue: list[tuple[str, bool]] = []
        self._active_toggle_id: str | None = None
        self._active_want_enabled: bool = False

        accent = t["accent"]
        # BEFORE _dialog_chrome, which sizes the panel on the way out —
        # declared afterwards, the first layout pass would use the default
        # band and the dialog would open narrow and jump on its first refit.
        self._selector_width_band = (_STARTUP_WIDTH_MIN, _STARTUP_WIDTH_MAX)
        panel = _dialog_chrome(self, t, accent, responsive=True)
        lay = dialog_body(panel, "md")

        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(TH.SPACE["xxs"])
        title = QLabel("🚀  Startup Manager")
        title.setStyleSheet(TH.label_qss(t, "dialog"))
        title_col.addWidget(title)
        self._subtitle = QLabel("Auditing Run keys and Startup folders…")
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(TH.label_qss(t, "body"))
        title_col.addWidget(self._subtitle)
        head.addLayout(title_col)
        head.addStretch()
        lay.addLayout(head)

        self._stack = fit_stack(QStackedWidget())
        self._stack.setStyleSheet(TH.stack_qss())
        lay.addWidget(self._stack, 1)
        self._loading_page = self._build_loading_page()
        self._stack.addWidget(self._loading_page)
        self._error_page = self._build_error_page()
        self._stack.addWidget(self._error_page)
        self._results_page = self._build_results_page()
        self._stack.addWidget(self._results_page)
        self._stack.setCurrentWidget(self._loading_page)

        self._status_strip = QLabel("")
        self._status_strip.setWordWrap(True)
        self._status_strip.hide()
        lay.addWidget(self._status_strip)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._status_strip.hide)

        self._start_scan()

    # -- page builders ----------------------------------------------
    def _build_loading_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["lg"])
        lay.addStretch()
        self._shimmer = ShimmerBar(height=6)
        self._shimmer.set_theme(t)
        lay.addWidget(self._shimmer)
        label = QLabel("Reading Run keys, the Startup folders, and scoring boot impact…")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(label)
        lay.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        size_dialog_button(cancel)
        cancel.setStyleSheet(TH.dialog_cancel_qss(t))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)
        return page

    def _build_error_page(self) -> QWidget:
        t = self._t
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, TH.SPACE["xxl"], 0, TH.SPACE["xl"])
        lay.setSpacing(TH.SPACE["md"])
        lay.addStretch()
        icon = QLabel("⚠️")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: {TH.TYPE['hero']}px; background: transparent; border: none;")
        lay.addWidget(icon)
        self._error_label = QLabel("")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(TH.label_qss(t, "body"))
        lay.addWidget(self._error_label)
        lay.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close")
        size_dialog_button(close)
        close.setStyleSheet(TH.dialog_cancel_qss(t))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        retry = QPushButton("Retry")
        size_dialog_button(retry)
        retry.setStyleSheet(TH.dialog_go_qss(t, t["accent"]))
        retry.clicked.connect(self._start_scan)
        row.addWidget(retry)
        lay.addLayout(row)
        return page

    def _build_results_page(self) -> QWidget:
        t = self._t
        accent = t["accent"]
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(TH.SPACE["md"])

        # The summary strip IS the filter control (v10.3). These three read
        # as counts, so they were being clicked as filters; they are now
        # exactly that. Clicking one isolates the matching items, clicking it
        # again (or "All") clears back to the full list — a filter you cannot
        # switch off is a trap, so the reset is always one click away and
        # always visible.
        summary = QHBoxLayout()
        summary.setSpacing(TH.SPACE["sm"])
        self._filter = "all"
        self._chips: dict[str, tuple[QPushButton, str]] = {}

        def chip(key: str, tone: str, tip: str) -> QPushButton:
            btn = QPushButton("")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            btn.clicked.connect(lambda _=False, k=key: self._toggle_filter(k))
            self._chips[key] = (btn, tone)
            summary.addWidget(btn)
            return btn

        self._chip_all = chip(
            "all", "accent", "Show every startup item")
        self._chip_enabled = chip(
            "enabled", "neutral", "Show only the items that launch at sign-in")
        self._chip_disabled = chip(
            "disabled", "neutral", "Show only the items you have already disabled")
        self._chip_recommended = chip(
            "recommended", "warn",
            "Show only the enabled items this audit recommends disabling")
        summary.addStretch()
        lay.addLayout(summary)

        # Says what the current filter is hiding. Empty (and hidden) on the
        # unfiltered list, so it costs nothing until it has something to say.
        self._filter_note = QLabel("")
        self._filter_note.setStyleSheet(TH.label_qss(t, "caption"))
        self._filter_note.hide()
        lay.addWidget(self._filter_note)

        self._optimize_btn = QPushButton("⚡  Optimize Startup")
        self._optimize_btn.setFixedHeight(TH.CONTROL_H)
        self._optimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._optimize_btn.setStyleSheet(TH.dialog_go_qss(t, accent))
        self._optimize_btn.setToolTip(
            "Disables every currently-enabled item the audit recommends disabling, one by one.")
        self._optimize_btn.clicked.connect(self._start_optimize)
        lay.addWidget(self._optimize_btn)

        scroll = FitScroll()
        scroll.setStyleSheet(TH.scroll_area_qss(t))
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self._host_lay = scroll_host_layout(self._host, "sm")
        self._host_lay.addStretch()
        scroll.setWidget(self._host)
        lay.addWidget(scroll, 1)

        row = QHBoxLayout()
        rescan = QPushButton("Rescan")
        rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan.setStyleSheet(TH.link_button_qss(t, accent))
        rescan.clicked.connect(self._start_scan)
        row.addWidget(rescan)
        row.addStretch()
        close = QPushButton("Close")
        size_dialog_button(close)
        close.setStyleSheet(TH.dialog_secondary_go_qss(t, accent))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        return page

    # -- scan lifecycle -----------------------------------------------
    def _start_scan(self):
        if self._scan_thread is not None:
            return
        self._subtitle.setText("Auditing Run keys and Startup folders…")
        self._clear_rows()
        # Back to the full list for a fresh scan. Carrying a filter across a
        # rescan can land the user on an empty list whose emptiness is the
        # filter's doing, not the machine's — and "my startup items vanished"
        # is not a thing this dialog should ever be able to suggest.
        self._filter = "all"
        self._filter_note.hide()
        self._stack.setCurrentWidget(self._loading_page)
        self._shimmer.start()

        thread = QThread(self)
        # 90s, not 60s: the scan itself is fast (pure registry reads + in-
        # memory regex scoring — see 05-Startup.ps1), but cold PowerShell
        # process start-up (module dot-sourcing, AV real-time scanning) is
        # environment-dependent and deserves real margin, not a hair-trigger
        # timeout — same generous window ScanForUpdates already uses.
        worker = PowerShellTask(self._ps1_path, "StartupReport", timeout=90)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_scan_thread_finished)
        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    def _on_scan_thread_finished(self):
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
            self._scan_worker = None
        if self._scan_thread is not None:
            self._scan_thread.deleteLater()
            self._scan_thread = None

    def _on_scan_failed(self, message: str):
        self._show_error(message or "The startup audit failed to run.")

    def _on_scan_finished(self, result: TaskResult):
        self._shimmer.stop()
        if not result.success:
            self._show_error(result.message)
            return
        items = result.data if isinstance(result.data, list) else []
        items = [it for it in items if isinstance(it, dict) and it.get("Id")]
        if not items:
            self._show_error("No startup items were found to audit.")
            return
        self._populate_rows(items)
        self._subtitle.setText("Toggle any item to change it instantly — changes are reversible.")
        self._stack.setCurrentWidget(self._results_page)

    def _show_error(self, message: str):
        self._shimmer.stop()
        self._error_label.setText(message or "The startup audit failed.")
        self._subtitle.setText("Audit failed.")
        self._stack.setCurrentWidget(self._error_page)

    # -- row management -------------------------------------------------
    def _clear_rows(self):
        """Empty the list, NOW.

        setParent(None) before deleteLater(), because deleteLater alone is
        not immediate: it posts a DeferredDelete that a plain
        processEvents() does not even deliver. takeAt() only unhooks the
        widget from the LAYOUT — it stays a child of the host and keeps
        painting at its last geometry until the deletion actually lands.
        That was survivable when this ran once per scan; it is not now that
        every filter click rebuilds the list, because the old rows would
        linger over the new ones for a frame. Re-parenting to None removes
        it from the widget tree synchronously; deleteLater still frees it."""
        self._rows.clear()
        while self._host_lay.count() > 1:   # keep the trailing stretch
            item = self._host_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    #: Which items each filter admits. One predicate per chip, so the chip's
    #: COUNT and the rows it isolates are computed from the same rule and
    #: cannot disagree — a filter pill that says "13 disabled" and then shows
    #: eleven rows is worse than no filter at all.
    _FILTERS = {
        "all":         lambda it: True,
        "enabled":     lambda it: bool(it.get("Enabled")),
        "disabled":    lambda it: not it.get("Enabled"),
        "recommended": lambda it: bool(it.get("Enabled")) and it.get("Recommendation") == "Disable",
    }

    def _toggle_filter(self, key: str):
        """Apply a filter, or clear it when the active chip is re-clicked."""
        self._filter = "all" if (key == self._filter and key != "all") else key
        self._render_rows()
        self._update_summary()

    def _populate_rows(self, items: list[dict]):
        self._items = {str(it["Id"]): it for it in items}
        self._render_rows()
        self._update_summary()

    def _render_rows(self):
        """Rebuild the list for the current filter.

        Rebuilt rather than show/hide-ing existing rows: the section headers
        carry per-section COUNTS, so hiding rows underneath them would leave
        "Recommended to Disable · 7" sitting above three visible items. Fully
        re-rendering keeps every number on screen true to what is on screen.
        Startup lists are tens of items, not thousands, so this is cheap."""
        self._clear_rows()
        keep = self._FILTERS.get(self._filter, self._FILTERS["all"])
        items = [it for it in self._items.values() if keep(it)]

        buckets: dict[str, list[dict]] = {"Disable": [], "Review": [], "Keep": [], "_off": []}
        for it in items:
            if not it.get("Enabled"):
                buckets["_off"].append(it)
            else:
                buckets.setdefault(it.get("Recommendation", "Review"), []).append(it)

        sections = [
            ("⚠️  Recommended to Disable", buckets["Disable"]),
            ("🔎  Worth Reviewing", buckets["Review"]),
            ("✅  Safe to Keep", buckets["Keep"]),
            ("⏸️  Currently Disabled", buckets["_off"]),
        ]
        for label, rows in sections:
            if not rows:
                continue
            header = QLabel(f"{label}   ·   {len(rows)}")
            header.setStyleSheet(TH.label_qss(self._t, "section"))
            self._host_lay.insertWidget(self._host_lay.count() - 1, header)
            for it in rows:
                row = StartupRow(it, self._t)
                row.toggle_requested.connect(self._on_toggle_requested)
                self._rows[str(it["Id"])] = row
                self._host_lay.insertWidget(self._host_lay.count() - 1, row)

        if self._filter == "all":
            self._filter_note.hide()
        else:
            hidden = len(self._items) - len(items)
            self._filter_note.setText(
                f"Filtered — {len(items)} of {len(self._items)} items shown "
                f"({hidden} hidden). Click the highlighted pill again, or “All”, "
                "to show everything.")
            self._filter_note.show()

    def _update_summary(self):
        items = list(self._items.values())
        counts = {key: sum(1 for it in items if pred(it))
                  for key, pred in self._FILTERS.items()}
        labels = {
            "all":         f"All {counts['all']}",
            "enabled":     f"{counts['enabled']} enabled",
            "disabled":    f"{counts['disabled']} disabled",
            "recommended": f"{counts['recommended']} recommended to disable",
        }
        for key, (btn, tone) in self._chips.items():
            btn.setText(labels[key])
            btn.setStyleSheet(TH.filter_chip_qss(self._t, tone, active=(self._filter == key)))
            # An empty bucket is not a filter worth offering — clicking it
            # would blank the list with no way to tell that from a bug. "All"
            # stays live regardless, because it is the way back.
            btn.setEnabled(key == "all" or counts[key] > 0)

        recommended = counts["recommended"]
        self._optimize_btn.setEnabled(recommended > 0)
        self._optimize_btn.setText(
            f"⚡  Optimize Startup ({recommended})" if recommended else "⚡  Optimize Startup — all clear")

    # -- toggle queue (sequential — one PowerShell process at a time) --
    def _on_toggle_requested(self, item_id: str, want_enabled: bool):
        self._toggle_queue.append((item_id, want_enabled))
        self._pump_toggle_queue()

    def _start_optimize(self):
        # `not Protected` is belt-and-braces over the backend's tier order:
        # StartupProtectedRules already returns 'Keep' for anything critical,
        # so a protected item cannot reach this list. It is asserted here
        # anyway because this is the ONE control that disables things in bulk
        # without the user seeing each one, and a future rule that widened a
        # Disable pattern must not be able to sweep the audio stack into it.
        recommended_ids = [
            it["Id"] for it in self._items.values()
            if it.get("Enabled") and it.get("Recommendation") == "Disable"
            and not it.get("Protected")
        ]
        if not recommended_ids:
            return
        self._show_status("info", f"Disabling {len(recommended_ids)} recommended item(s)…")
        for item_id in recommended_ids:
            row = self._rows.get(item_id)
            if row is not None:
                row.set_busy(True)
            self._toggle_queue.append((item_id, False))
        self._pump_toggle_queue()

    def _pump_toggle_queue(self):
        if self._toggle_worker is not None or not self._toggle_queue:
            return
        item_id, want_enabled = self._toggle_queue.pop(0)
        row = self._rows.get(item_id)
        if row is not None:
            row.set_busy(True)
        self._active_toggle_id = item_id
        self._active_want_enabled = want_enabled

        task_name = "StartupEnableItem" if want_enabled else "StartupDisableItem"
        thread = QThread(self)
        worker = PowerShellTask(self._ps1_path, task_name, timeout=60,
                                startup_item_id=item_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_toggle_finished)
        worker.failed.connect(self._on_toggle_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_toggle_thread_finished)
        self._toggle_thread = thread
        self._toggle_worker = worker
        thread.start()

    def _on_toggle_thread_finished(self):
        if self._toggle_worker is not None:
            self._toggle_worker.deleteLater()
            self._toggle_worker = None
        if self._toggle_thread is not None:
            self._toggle_thread.deleteLater()
            self._toggle_thread = None
        QTimer.singleShot(0, self._pump_toggle_queue)

    def _on_toggle_finished(self, result: TaskResult):
        item_id, want_enabled = self._active_toggle_id, self._active_want_enabled
        row = self._rows.get(item_id)
        if row is not None:
            row.set_busy(False)
        if result.success:
            if item_id in self._items:
                self._items[item_id]["Enabled"] = want_enabled
            if row is not None:
                row.set_enabled_state(want_enabled)
            self._show_status("ok", f"✓  {result.message}")
        else:
            if row is not None:
                row.set_enabled_state(not want_enabled)   # snap back
            self._show_status("err", f"✕  {result.message}")
        self._update_summary()

    def _on_toggle_failed(self, message: str):
        item_id = self._active_toggle_id
        row = self._rows.get(item_id)
        if row is not None:
            row.set_busy(False)
            row.set_enabled_state(not self._active_want_enabled)
        self._show_status("err", f"✕  {message}")
        self._update_summary()

    def _show_status(self, tone: str, message: str):
        self._status_strip.setText(message)
        self._status_strip.setStyleSheet(TH.inline_status_qss(self._t, tone))
        self._status_strip.show()
        self._status_timer.start(4000)

    # -- lifecycle --------------------------------------------------
    def _cancel_workers(self):
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        if self._toggle_worker is not None:
            self._toggle_worker.cancel()
        self._toggle_queue.clear()

    def reject(self):
        self._cancel_workers()
        super().reject()

    def accept(self):
        self._cancel_workers()
        super().accept()

    def showEvent(self, e):
        super().showEvent(e)
        _present_dialog(self)
