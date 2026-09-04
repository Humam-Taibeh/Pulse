"""Rendering-artifact bisector: run Pulse with ONE subsystem disabled.

    python tools\\diagnose_edge_bleed.py baseline   # as shipped — confirm it repros
    python tools\\diagnose_edge_bleed.py round      # integer DPI (no fractional scaling)
    python tools\\diagnose_edge_bleed.py raster     # no QOpenGLWidget at all
    python tools\\diagnose_edge_bleed.py noeffects  # no QGraphicsEffect anywhere
    python tools\\diagnose_edge_bleed.py noround    # DWMWCP_DONOTROUND

Use the app normally in each run — switch modules, toggle the theme,
resize, maximize — until the artifact appears or clearly does not. The
FIRST mode where it stops happening names the layer responsible.

WHY THIS IS KEPT. It found the v10.3 fractional-DPI viewport bleed, and it
found it in one pass after a long and unsuccessful attempt to reason the
cause out from geometry measurements alone. Every candidate that was
"obviously" implicated — DWM frame margins, the WM_NCCALCSIZE arithmetic,
the framebuffer's allocated size — measured perfectly clean, because the
defect was in the viewport rectangle drawn INTO a correctly sized surface.
Rendering bugs of that shape are bisected, not deduced; a screenshot of
the real machine plus this script beats any amount of static analysis.

`raster` and `round` both clearing an artifact means the GPU path under
fractional scaling; `raster` alone means the GPU path generally;
`noeffects` alone means an offscreen QGraphicsEffect buffer.
"""
import os
import sys

# Repo-relative: this file lives in tools/, so src/ is one level up.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

MODE = sys.argv[1] if len(sys.argv) > 1 else "baseline"

if MODE == "raster":
    # BEFORE PySide6 IS IMPORTED, which is why this branch sits above
    # the Qt imports rather than beside the other MODE checks: Qt
    # resolves its rendering backend once, at import time, and an
    # environment variable set afterwards is simply ignored.
    #
    # "software" forces the raster paint engine, so no QOpenGLWidget
    # is created anywhere and the GPU path is out of the picture
    # entirely — which is exactly the layer this mode exists to
    # exclude.
    os.environ["QT_OPENGL"] = "software"

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if MODE == "round":
    # Integer scaling. If the artifact vanishes here, the whole fractional
    # high-DPI class is implicated and nothing else needs testing.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.Round)
else:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

app = QApplication(sys.argv[:1])
app.setStyle("Fusion")

import frontend.animations as A  # noqa: E402
import frontend.main as M  # noqa: E402
from frontend import theme as TH  # noqa: E402

if MODE == "noeffects":
    # Every offscreen-buffer path off: page fade, entrance cascade and the
    # theme cross-fade overlay. QGraphicsOpacityEffect on a full-page widget
    # is the classic fractional-DPI displacement source.
    A.PageFader.fade_in = lambda self, page, duration_ms=0, rise_px=0: None
    A.CascadeAnimator.play = lambda self, *a, **k: None
    M.PulseApp._toggle_theme_animated = lambda self: self.theme.toggle()

if MODE == "noround":
    _orig = TH.apply_native_rounding
    TH.apply_native_rounding = lambda hwnd, rounded=True: _orig(hwnd, False)

win = M.PulseApp()
win.show()

print(f"=== MODE: {MODE} ===")
print(f"ambient backend : {type(win._glow).__name__}")
print(f"devicePixelRatio: {win.devicePixelRatioF()}")
print(f"rounding policy : {QApplication.highDpiScaleFactorRoundingPolicy()}")
print("\nExercise the app: switch modules, toggle theme, resize, maximize.")
print("Does the displaced grey surface still appear?  Ctrl+C or close to exit.")
sys.exit(app.exec())
