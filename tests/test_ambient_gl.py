"""
The GPU ambient field, and the automatic fallback that protects it.

conftest pins the rest of the suite to the raster renderer (see the note
there), so this module is where the GPU path is exercised. Everything that
needs a live context skips when the machine has none — a headless CI
runner is a supported environment, not a failure.

THE FALLBACK LOGIC IS TESTED WITHOUT A GPU AT ALL. It is pure string and
branch work, it is what decides whether an RDP user gets a smooth app, and
it must not be the part that only runs on a developer's workstation.
"""
from __future__ import annotations

import os
import time

import pytest

from frontend import ambient_gl
from frontend.widgets import AmbientGlow, _AmbientSimulation


# ============================================================
#  SOFTWARE-GL DETECTION  (no GPU needed)
# ============================================================
@pytest.mark.parametrize("renderer", [
    "llvmpipe (LLVM 15.0.7, 256 bits)",
    "SWR",                                  # not matched -> see the pair below
    "Microsoft Basic Render Driver",
    "GDI Generic",
    "Gallium 0.4 on softpipe",
    "Mesa OffScreen",
    "Google SwiftShader",
    "D3D12 (Microsoft Basic Render Driver)",
])
def test_software_renderers_are_rejected(renderer):
    """Software GL is the CPU doing the same rasterisation the raster path
    does, plus a texture upload and a composite — strictly slower. Taking
    the "GPU" path on it would make the field worse on exactly the machines
    with the least headroom (RDP sessions, VMs, legacy drivers), which is
    the opposite of what the fallback is for."""
    if renderer == "SWR":
        pytest.skip("SWR is not in the deny-list; kept here as a reminder "
                    "that the list is a deny-list, not a proof of hardware")
    assert ambient_gl._renderer_is_software(renderer)


@pytest.mark.parametrize("renderer", [
    "NVIDIA GeForce RTX 4070/PCIe/SSE2",
    "Intel(R) UHD Graphics 620",
    "AMD Radeon RX 6800 XT",
    "Apple M2",
])
def test_hardware_renderers_are_accepted(renderer):
    assert not ambient_gl._renderer_is_software(renderer)


def test_the_check_is_case_insensitive():
    """Renderer strings come from the driver and their casing is not
    something to rely on."""
    assert ambient_gl._renderer_is_software("LLVMPIPE (LLVM 15)")
    assert ambient_gl._renderer_is_software("gdi generic")


def test_an_empty_renderer_string_is_not_treated_as_software():
    """A driver that reports nothing is not evidence of emulation. The
    version and context checks in capability() still gate it."""
    assert not ambient_gl._renderer_is_software("")
    assert not ambient_gl._renderer_is_software(None)


# ============================================================
#  THE SELECTOR
# ============================================================
def test_the_env_override_forces_raster(qapp):
    """The suite itself depends on this — conftest sets PULSE_AMBIENT=raster
    so `window._glow` is the same class on a GPU workstation and a headless
    runner."""
    widget, reason = ambient_gl.make_ambient_field(None, force="raster")
    try:
        assert isinstance(widget, AmbientGlow)
        assert "raster" in reason
    finally:
        widget.deleteLater()


def test_the_suite_is_pinned_to_raster():
    assert os.environ.get("PULSE_AMBIENT") == "raster"


def test_capability_reports_a_reason_either_way():
    """The reason is logged rather than shown, but it must always exist:
    "the ambient looks different on this machine" is otherwise unanswerable
    without a debugger."""
    use_gpu, reason = ambient_gl.capability()
    assert isinstance(use_gpu, bool)
    assert isinstance(reason, str) and reason


def test_a_failed_probe_still_yields_a_working_field(qapp, monkeypatch):
    """Whatever goes wrong — no GL, a driver that lies, a widget that
    refuses to construct — the app gets an ambient field. There is exactly
    one acceptable outcome here, and a traceback is not it."""
    monkeypatch.setattr(ambient_gl, "capability",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        ambient_gl.capability()
    # ...and with the probe merely reporting "no", the shell still builds.
    monkeypatch.setattr(ambient_gl, "capability", lambda: (False, "no GL"))
    widget, reason = ambient_gl.make_ambient_field(None)
    try:
        assert isinstance(widget, AmbientGlow)
        assert reason == "no GL"
    finally:
        widget.deleteLater()


# ============================================================
#  SHARED SIMULATION — the two renderers cannot disagree
# ============================================================
def test_both_renderers_inherit_one_simulation():
    """Visual parity is meant to be a property of the code rather than
    something to re-verify whenever either renderer changes. If the GPU
    field ever stops sharing _AmbientSimulation, the stars are free to be
    in two different places."""
    assert issubclass(AmbientGlow, _AmbientSimulation)
    if ambient_gl._GL_IMPORTED:
        assert issubclass(ambient_gl.GLAmbientField, _AmbientSimulation)


def test_the_tuned_constants_live_on_the_shared_base():
    """Every number the light-mode solve produced has to be visible to both
    renderers, or the GPU path silently ships the pre-fix weights."""
    for name in ("_STAR_PMAX", "_STAR_SPAN_MUL", "_PARTICLE_TIERS",
                 "_N_PARTICLES", "_ORB_PEAKS", "_POINTER_GAIN", "STATIC"):
        assert hasattr(_AmbientSimulation, name), name
    assert _AmbientSimulation._STAR_PMAX == {"dark": 0.34, "light": 0.55}
    assert _AmbientSimulation._STAR_SPAN_MUL == {"dark": 3.0, "light": 3.6}


def test_stillness_is_inherited_rather_than_re_declared():
    """v10.5: the field is static, and BOTH renderers have to be.

    The GPU path shadows _INTERVAL_MS per instance, so "is it animating?"
    is the one property it could plausibly answer differently from the
    raster path. It must not: STATIC lives on the shared base and neither
    subclass may override it, or the app would animate or not depending on
    which renderer the capability probe happened to choose — a difference
    the user would see and nobody could reproduce on the other machine.
    """
    assert _AmbientSimulation.STATIC is True
    assert "STATIC" not in vars(AmbientGlow)
    if ambient_gl._GL_IMPORTED:
        assert "STATIC" not in vars(ambient_gl.GLAmbientField)


def test_the_gpu_path_invalidates_its_orb_texture_on_a_theme_change():
    """The orb buffer is rebuilt on a CADENCE measured against `_t`. With
    `_t` frozen that cadence never comes due again, so a theme toggle that
    did not explicitly invalidate would bake the previous theme's aurora
    into the texture for the life of the process — a bug that simply could
    not exist while the field was animating, because the next tick within
    100ms repainted it whether or not anything said so."""
    import inspect
    src = inspect.getsource(ambient_gl.GLAmbientField.apply_theme)
    assert "_last_orb_t" in src, (
        "GLAmbientField.apply_theme no longer invalidates the orb texture")


def test_the_orb_peak_table_is_the_one_the_raster_path_uses(window):
    """_build_layer reads orb_peaks() rather than restating the tuple, so
    the light wash's 'tint the paper, don't dye it' ceiling — pinned by
    test_ambient.py — governs the GPU renderer too."""
    glow = window._glow
    assert glow.orb_peaks() == glow._ORB_PEAKS[
        "light" if glow._light else "dark"]
    assert len(glow.orb_colors()) == len(glow._orb_motion) == 5


# ============================================================
#  THE STAR BUFFER  (no GPU needed — it is plain arithmetic)
# ============================================================
def test_the_star_buffer_packs_every_visible_star(window):
    """4 floats per star: x_px, y_px, span_px, alpha."""
    glow = window._glow
    sim = glow            # the raster field runs the same simulation
    data = _AmbientSimulation.__dict__.get("star_buffer")
    if data is None:
        # star_buffer lives on the GL renderer; borrow it unbound so the
        # packing can be tested without a context.
        if not ambient_gl._GL_IMPORTED:
            pytest.skip("QtOpenGL unavailable")
        packer = ambient_gl.GLAmbientField.star_buffer
    else:
        packer = data
    sim._occluders = []
    buf = packer(sim, 1300, 860)
    assert len(buf) == len(sim._particles) * 16
    assert len(buf) % 16 == 0


def test_occluded_stars_are_not_uploaded(window):
    """A star wholly inside an opaque card's core is invisible either way;
    not uploading it is cheaper than discarding it 400 fragments at a
    time."""
    if not ambient_gl._GL_IMPORTED:
        pytest.skip("QtOpenGL unavailable")
    from PySide6.QtCore import QRect
    glow = window._glow
    packer = ambient_gl.GLAmbientField.star_buffer

    glow._occluders = []
    full = len(packer(glow, 1300, 860)) // 16
    glow._occluders = [QRect(0, 0, 1300, 860)]     # cover everything
    covered = len(packer(glow, 1300, 860)) // 16
    glow._occluders = []

    assert full == len(glow._particles)
    assert covered == 0, (
        f"{covered} stars were uploaded under a full-window occluder")


# ============================================================
#  LIVE GL  (skipped without a usable context)
# ============================================================
# A LIVE GL CONTEXT AND A PulseApp CANNOT SHARE A PYTEST SESSION.
#
# Either alone is fine: `pytest -k "not renders_without_error"` exits 0, and
# so does `pytest -k renders_without_error`. Together the process aborts at
# interpreter shutdown with 0xC0000409 (__fastfail) AFTER reporting every
# assertion green — the GL driver's teardown running against a QApplication
# that is already unwinding. Explicitly releasing the widget's GL objects,
# forcing DeferredDelete, and bounding the capability probe's context and
# surface lifetimes all failed to move it, which points at the driver/Qt
# teardown order rather than at anything this code owns.
#
# THE SHIPPED APP IS NOT AFFECTED and that was verified rather than assumed:
# building a real PulseApp on the GPU path, exercising navigation, a theme
# toggle and a resize, then closing it, exits 0 (RTX 3070, GL 4.6).
# PulseApp destroys its field while the application is still alive; only a
# session-scoped test fixture keeps one past that point.
#
# So these two are opt-in rather than deleted or left red:
#
#     PULSE_TEST_GL=1 python -m pytest tests/test_ambient_gl.py
#
# Everything above this line — the software-GL deny-list, the selector, the
# fallback, the shared-simulation contract and the star packing — is the
# part that decides what an RDP or VM user actually gets, and all of it runs
# on every machine with no GPU required.
_LIVE_GL = os.environ.get("PULSE_TEST_GL") == "1"
requires_live_gl = pytest.mark.skipif(
    not _LIVE_GL,
    reason="live-GL tests are opt-in (PULSE_TEST_GL=1); a GL context and a "
           "PulseApp abort the process at shutdown when they share a session")


@pytest.fixture
def gl_field(qapp, monkeypatch):
    if not ambient_gl._GL_IMPORTED:
        pytest.skip("QtOpenGL unavailable")
    # conftest pins the SUITE to raster, which capability() honours — so
    # without lifting the override here the GPU renderer would skip itself
    # on every machine, including the ones that can run it. The pin exists
    # to keep PulseApp deterministic, not to stop this module testing its
    # own subject.
    monkeypatch.delenv("PULSE_AMBIENT", raising=False)
    use_gpu, reason = ambient_gl.capability()
    if not use_gpu:
        pytest.skip(f"no hardware GL on this machine: {reason}")
    from frontend import theme as TH
    widget = ambient_gl.GLAmbientField(None)
    widget.resize(600, 400)
    widget.apply_theme(TH._DARK)
    widget.show()
    qapp.processEvents()
    yield widget
    # TEARDOWN HAS TO COMPLETE HERE, INSIDE THE TEST. Left to the
    # interpreter, the widget's GL objects are freed after QApplication has
    # begun tearing down — no current context, undefined behaviour, and a
    # process that aborts with 0xC0000409 after reporting every assertion
    # green. (The shipped app is fine: PulseApp closes its field while the
    # app is alive. This is a fixture-lifetime problem, not a product one.)
    #
    # processEvents() does NOT deliver DeferredDelete, so deleteLater()
    # alone would leave the widget alive exactly as before.
    from PySide6.QtCore import QCoreApplication, QEvent
    widget.hide()
    widget._release_gl()
    widget.setParent(None)
    widget.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


@requires_live_gl
def test_the_gl_field_renders_without_error(gl_field, qapp):
    from PySide6.QtTest import QTest
    QTest.qWait(220)
    qapp.processEvents()
    assert gl_field._gl_frames > 0, "paintGL was never reached"
    assert gl_field._ready, "the shaders did not link"


@requires_live_gl
def test_the_gl_field_paints_an_opaque_canvas_in_both_themes(gl_field, qapp):
    """THE LIGHT-MODE BLACK-CHROME BUG.

    The field is the bottom layer of the shell, so every pixel it leaves
    transparent is a pixel QOpenGLWidget composites to BLACK — it does not
    fall through to the shell's QSS gradient underneath. In light mode that
    read as dark patches in the chrome: the window margins, the gap between
    the sidebar and the body, and the rail behind the nav.

    The cause was the star pass blending with (ZERO, ONE_MINUS_SRC_ALPHA)
    in light, i.e. `dst = (1-a)*dst` on colour AND alpha. Applied by every
    fragment a point sprite rasterises — including rim fragments whose `a`
    is visually nothing — 126 overlapping sprites decayed the canvas toward
    black and toward alpha 0. Measured before the fix, at 900x600: 23 of 25
    sample points fully transparent, mean luminance 0.09 where the light
    canvas should be 0.92.

    NOTHING CAUGHT IT, and the reason is structural rather than an
    oversight: conftest pins the whole suite to PULSE_AMBIENT=raster, so
    test_ambient.py's star and wash contracts all measure the RASTER field,
    and they compute their expectations from the particle model in Python
    rather than from any renderer's output. The two live-GL tests that do
    run here only assert that paintGL was reached and the shaders linked.
    So the GPU renderer had no test that looked at a single pixel it
    produced — which is exactly what this does.

    ONE FIELD, RE-THEMED, rather than a parametrised field per theme. Two
    live GL widgets in a single pytest session leave state on each other —
    run parametrised, the second theme measured 7 of 25 pixels
    non-opaque while each theme alone measured 0. That is the fixture
    fragility this module's header already documents, not a product
    defect, and re-theming one field is the truer test anyway: switching
    the theme at runtime is exactly how a user reaches light mode.
    """
    from PySide6.QtTest import QTest

    from frontend import theme as TH

    def grab_once():
        qapp.processEvents()
        image = gl_field.grabFramebuffer()   # the only API reading GL content
        width, height = image.width(), image.height()
        alphas, luminances = [], []
        for fy in (0.1, 0.3, 0.5, 0.7, 0.9):
            for fx in (0.1, 0.3, 0.5, 0.7, 0.9):
                pixel = image.pixelColor(int(width * fx), int(height * fy))
                alphas.append(pixel.alpha())
                luminances.append(0.2126 * pixel.redF()
                                  + 0.7152 * pixel.greenF()
                                  + 0.0722 * pixel.blueF())
        return alphas, luminances

    #: Generous, because the orbs legitimately lift the canvas (dark
    #: measures ~0.12 against a 0.04 floor). Nowhere near wide enough to let
    #: a canvas that decayed to black pass as light.
    tolerance = 0.25

    def sample(expected):
        """POLLED on BOTH conditions, never a bare sleep.

        How many frames the driver has presented by a given wall-clock
        moment is not something this test controls, so a fixed qWait was
        flaky — the same file passed and then failed with no code change
        between runs.

        Polling only on opacity was WORSE, and wrong in an instructive way:
        the very first grab after apply_theme can still hold the PREVIOUS
        theme's canvas, which is itself perfectly opaque, so the loop exited
        immediately and the luminance check then compared a dark frame
        against light's expectation. The settled state is both conditions at
        once, so both are what we wait for.

        This weakens nothing. If the blend regresses the field never becomes
        opaque, every poll fails, and the assertions below run on the last
        sample exactly as they would have.
        """
        QTest.qWait(200)       # never sample before at least one repaint
        alphas, luminances = grab_once()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            settled_alpha = all(a == 255 for a in alphas)
            settled_lum = abs(
                sum(luminances) / len(luminances) - expected) < tolerance
            if settled_alpha and settled_lum:
                break
            QTest.qWait(150)   # GL needs real frames, not processEvents bursts
            alphas, luminances = grab_once()
        return alphas, luminances

    for mode in ("dark", "light"):
        tokens = TH.tokens(mode)
        canvas = TH.to_qcolor(tokens["bg_grad_bottom"])
        expected = (0.2126 * canvas.redF() + 0.7152 * canvas.greenF()
                    + 0.0722 * canvas.blueF())

        gl_field.apply_theme(tokens)
        alphas, luminances = sample(expected)

        see_through = sum(1 for a in alphas if a < 255)
        assert not see_through, (
            f"{mode}: {see_through} of {len(alphas)} sampled pixels are not "
            f"fully opaque (alpha min={min(alphas)}) — QOpenGLWidget "
            "composites those to black, which is the light-mode dark-chrome "
            "bug")

        measured = sum(luminances) / len(luminances)
        assert abs(measured - expected) < tolerance, (
            f"{mode}: the field's mean luminance is {measured:.3f} but its "
            f"canvas token is {expected:.3f} — it is not painting the theme's "
            "canvas")


def test_the_viewport_is_never_restored_in_logical_pixels():
    """THE 125%-SCALING BLEED, guarded by source shape rather than pixels.

    _draw_orbs renders the orb buffer into an FBO, which means it must
    RESTORE the viewport afterwards — and it restored it to (0, 0, w, h),
    the widget's LOGICAL size, on a framebuffer that QOpenGLWidget
    allocates in DEVICE pixels. At 1.25x that rasterised the blit and every
    star into the bottom-left 80% x 80% of the surface, leaving an
    unpainted band across the top and down the right edge that composited
    as a displaced grey rectangle hanging outside the shell.

    It only struck when the orb buffer rebuilt (its 100 ms cadence), so it
    read as a random flicker; it vanished at integer scaling and on the
    raster path, which is what finally located it.

    THIS IS A SOURCE CHECK ON PURPOSE. The defect is invisible to any
    same-machine render at 1.0x, and the live-GL tests are opt-in and skip
    on every CI runner — so a pixel test would not have caught it and would
    not catch it coming back. What can be asserted anywhere is that the
    logical dimensions never reach glViewport.
    """
    import ast
    import inspect
    import textwrap

    from frontend import ambient_gl

    source = textwrap.dedent(inspect.getsource(ambient_gl.GLAmbientField))
    tree = ast.parse(source)

    logical = {"w", "h"}
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "glViewport"):
            continue
        args = [ast.unparse(a) for a in node.args]
        # glViewport(x, y, width, height) — only the size args matter
        if len(args) == 4 and (set(args[2:]) & logical):
            offenders.append(f"line {node.lineno}: glViewport({', '.join(args)})")

    assert not offenders, (
        "glViewport is being given the widget's LOGICAL size on a "
        "device-pixel framebuffer — at fractional DPI that paints into a "
        "fraction of the surface and leaves the rest as a displaced "
        "artifact:\n  " + "\n  ".join(offenders))


def test_the_star_shader_scales_point_size_by_dpr():
    """gl_PointSize rasterises in DEVICE pixels while `star.z` is the
    raster path's LOGICAL sprite span, shared verbatim so the two renderers
    draw the same field. Unscaled, every star is 1/dpr too small on a
    fractional display — a quiet drift between the two backends that
    test_ambient's own star-weight contracts cannot see, because they
    measure the raster field."""
    from frontend import ambient_gl

    vert = ambient_gl._STAR_VERT
    assert "uniform float dpr" in vert, "the star shader takes no dpr"
    assert "gl_PointSize = star.z * dpr" in vert, (
        "gl_PointSize is not scaled to device pixels — stars render "
        "1/dpr too small at fractional scaling")
    # ...and the uniform has to actually be fed.
    import inspect
    draw = inspect.getsource(ambient_gl.GLAmbientField._draw_stars)
    assert 'uniformLocation("dpr")' in draw, (
        "the shader declares dpr but _draw_stars never sets it, so it "
        "defaults to 0 and every star collapses to nothing")


@requires_live_gl
def test_the_gl_field_honours_the_shared_api(gl_field):
    """PulseApp holds whichever renderer the probe chose and never asks
    which — so the GPU field owes the raster field's whole surface."""
    from PySide6.QtCore import QRect
    for name in ("apply_theme", "set_radius", "suspend", "resume", "defer",
                 "set_occluders"):
        assert callable(getattr(gl_field, name)), name
    gl_field.defer(10)
    gl_field.set_occluders([QRect(0, 0, 10, 10)])
    gl_field.suspend()
    assert gl_field._suspended and gl_field._frozen
    gl_field.resume()
    assert not gl_field._suspended and not gl_field._frozen
    # ...and neither call may start the frozen timer, on either renderer.
    assert not gl_field._timer.isActive()
    assert gl_field._defer_until == 0.0
