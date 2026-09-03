"""
Regressions found by the v10.3 deep architectural audit.

Four defects, each with the guard that would have caught it and the
generalised guard for its whole class:

1. PAINTED TOKENS THAT QColor CANNOT PARSE. Half the palette is written in
   QSS's rgba() notation. QColor does not understand rgba() — it returns an
   INVALID colour, which Qt paints as opaque black. ToggleSwitch fed
   `panel_line` straight to QColor and drew a hard black pill in place of
   its off-track, in both themes. theme.to_qcolor() exists to parse these;
   nothing enforced its use.

2. A JOB OBJECT LEAKED ON EVERY FAILED SPAWN. PowerShellTask.run() created
   the Windows Job Object before Popen but only published it to self._job
   after, so the `finally` that closes it saw None whenever Popen raised.
   Measured at exactly one leaked kernel handle per failed spawn.

3. THE CONSOLE MATERIALISED ITS WHOLE BUFFER ON EVERY REPAINT.
   LiveConsole.paintEvent asked `if self.toPlainText():` purely to decide
   whether to draw the empty state — 216 KB and 236 us at the 2000-line
   ceiling, on the widget that repaints once per streamed output line.

4. NOTHING PINNED THE "no leaks" CLAIM. Modal opens and module navigation
   are the two loops a user runs hundreds of times per session.
"""
from __future__ import annotations

import ast
import gc
import subprocess
import threading
import time
import weakref
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap

from frontend import theme as TH

_SRC = Path(__file__).resolve().parent.parent / "src"


def _both_themes(qapp) -> dict[str, dict]:
    """{'dark': tokens, 'light': tokens} — the manager owns the switch, so
    toggle it rather than reaching for a private per-mode table."""
    manager = TH.ThemeManager()
    out = {}
    for _ in range(2):
        out[manager.t["name"]] = dict(manager.t)
        manager.toggle()
    assert set(out) == {"dark", "light"}, "theme manager stopped round-tripping"
    return out


def _drain(qapp, rounds: int = 4):
    """Settle the way a real event loop does — INCLUDING deferred deletes.

    processEvents() alone does NOT dispatch DeferredDelete events posted
    from the main thread. A leak check built on it reports every correctly
    deleted widget as a leak, which is exactly how this file's first draft
    'found' ten leaks that did not exist.
    """
    for _ in range(rounds):
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


# ============================================================
#  1. PAINTED COLOUR TOKENS
# ============================================================
#: Names a token dict travels under at a paint site.
_TOKEN_DICTS = {"t", "tokens"}


def _token_arg(node) -> str | None:
    """`t["key"]` or `t.get("key", ...)` -> "key"; anything else -> None."""
    if isinstance(node, ast.Subscript):
        if (isinstance(node.value, ast.Name) and node.value.id in _TOKEN_DICTS
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            return node.slice.value
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in _TOKEN_DICTS
            and node.args and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)):
        return node.args[0].value
    return None


def _painted_token_sites() -> list[tuple[str, int, str]]:
    """Every `QColor(<token>)` in the frontend, parsed from the AST.

    AST, not a regex over the source text: a regex also matches the token
    named inside a DOCSTRING — including the one in ToggleSwitch._track_off
    that documents this very bug — and a guard that fails on its own
    explanatory prose gets deleted rather than fixed.
    """
    sites = []
    for path in sorted((_SRC / "frontend").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "QColor" and node.args):
                continue
            token = _token_arg(node.args[0])
            if token is not None:
                sites.append((path.name, node.lineno, token))
    return sites


def test_the_painted_token_scan_found_sites():
    """A regex that silently matches nothing would make the guard below a
    no-op that passes forever."""
    assert _painted_token_sites(), (
        "no QColor(t[...]) sites found — the scan pattern has gone stale")


def test_every_painted_token_is_qcolor_parsable(qapp):
    """THE guard for the ToggleSwitch black-pill bug.

    A token handed to QColor must be something QColor can actually read.
    rgba() tokens are legal in QSS and invalid here, and the failure is
    silent: QColor(invalid) is opaque black, so the widget paints a solid
    black shape instead of a subtle tint and nothing raises. Reach for
    TH.to_qcolor() (and TH.blend() if the tint must land on a surface).
    """
    themes = _both_themes(qapp)
    failures = []
    for filename, line, token in _painted_token_sites():
        for mode, tokens in themes.items():
            if token not in tokens:
                continue    # a .get() default for an optional key
            value = tokens[token]
            if not isinstance(value, str):
                continue
            if not QColor(value).isValid():
                failures.append(
                    f"{filename}:{line} paints t[{token!r}] = {value!r} "
                    f"({mode}) — QColor cannot parse it and renders it BLACK; "
                    "use TH.to_qcolor()")
    assert not failures, "unparsable painted tokens:\n  " + "\n  ".join(failures)


def test_the_toggle_off_track_is_neither_black_nor_transparent(qapp):
    """The specific regression: the Startup Manager's switches.

    The off track must be an opaque colour that is visibly NOT the black
    QColor('rgba(...)') used to produce, and must differ from the on track
    so the two states never collapse into one another.
    """
    from frontend.widgets import ToggleSwitch

    for mode, tokens in _both_themes(qapp).items():
        switch = ToggleSwitch(tokens)
        off = switch._off_color
        assert off.isValid(), f"{mode}: off track is an invalid QColor"
        assert off.alpha() == 255, (
            f"{mode}: off track is translucent ({off.alpha()}) — paintEvent "
            "rebuilds the track from RGB and would drop the alpha")
        assert (off.red(), off.green(), off.blue()) != (0, 0, 0), (
            f"{mode}: off track is pure black — the rgba() parse regressed")
        assert off != switch._on_color, f"{mode}: on and off tracks are equal"


def test_the_toggle_track_tracks_the_theme(qapp):
    """apply_theme must re-derive the track, or a live theme switch leaves
    the dark well sitting on the light row."""
    from frontend.widgets import ToggleSwitch

    themes = _both_themes(qapp)
    switch = ToggleSwitch(themes["dark"])
    dark_off = QColor(switch._off_color)
    switch.apply_theme(themes["light"])
    assert switch._off_color != dark_off, (
        "apply_theme did not re-derive the off track for the new theme")


# ============================================================
#  2. JOB OBJECT LIFECYCLE
# ============================================================
def test_a_failed_spawn_still_closes_its_job_object(monkeypatch, tmp_path):
    """The job is created BEFORE Popen so the child can be assigned to it
    the instant it exists. That ordering is correct — but it means a Popen
    that raises leaves a live kernel handle unless the job is published to
    self._job first, which is what the `finally` closes.
    """
    from utils import helpers

    created = []
    real_job = helpers.ProcessJob

    class RecordingJob(real_job):
        def __init__(self):
            super().__init__()
            created.append(self)

        @property
        def closed(self) -> bool:
            return self._handle is None

    def exploding_popen(*args, **kwargs):
        raise FileNotFoundError("simulated: powershell.exe is missing")

    monkeypatch.setattr(helpers, "ProcessJob", RecordingJob)
    monkeypatch.setattr(subprocess, "Popen", exploding_popen)

    ps1 = tmp_path / "core.ps1"
    ps1.write_text("# stub", encoding="utf-8")
    task = helpers.PowerShellTask(str(ps1), "SystemInfo")

    reported = []
    task.failed.connect(reported.append)
    task.run()

    assert reported, "a failed spawn must still report through `failed`"
    assert created, "the task never armed a ProcessJob"
    for job in created:
        if job.available or job._handle is not None:
            assert job.closed, (
                "the Job Object survived a failed spawn — one kernel handle "
                "leaks per attempt for the life of the GUI process")


def test_a_successful_run_also_releases_the_job(monkeypatch, tmp_path):
    """The counterpart: the ordinary path must not start leaking either,
    and must still DETACH (kill-on-close off) so anything the task
    deliberately left running survives."""
    from utils import helpers

    created = []
    real_job = helpers.ProcessJob

    class RecordingJob(real_job):
        def __init__(self):
            super().__init__()
            self.detached = False
            created.append(self)

        def detach(self):
            self.detached = True
            super().detach()

    class FakeProcess:
        pid = 4242

        def __init__(self):
            self.stdout = self
            self._chunks = [b"##PULSE##SUCCESS|done\r\n"]

        def read1(self, _n):
            return self._chunks.pop(0) if self._chunks else b""

        def poll(self):
            return 0

        # Faithful to subprocess.Popen's real signatures, because the
        # teardown under test calls both: wait() takes a timeout, and the
        # stdout pipe is closed explicitly so its handle is given back
        # rather than left to garbage collection of the worker (which the
        # app deliberately keeps alive until the next task).
        def wait(self, timeout=None):
            return 0

        def close(self):
            self.closed = True

    monkeypatch.setattr(helpers, "ProcessJob", RecordingJob)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: FakeProcess())

    ps1 = tmp_path / "core.ps1"
    ps1.write_text("# stub", encoding="utf-8")
    task = helpers.PowerShellTask(str(ps1), "SystemInfo")
    results = []
    task.finished.connect(results.append)
    task.run()

    assert results and results[0].success, "clean SUCCESS verdict was not parsed"
    assert created, "the task never armed a ProcessJob"
    for job in created:
        assert job._handle is None, "the Job Object handle was not released"
        if job.available or job.detached:
            assert job.detached, (
                "kill-on-close was never disarmed — a task that deliberately "
                "leaves a window open would have it killed")


# ============================================================
#  3. CONSOLE REPAINT COST
# ============================================================
def test_the_console_empty_state_never_materialises_the_buffer(qapp):
    """paintEvent must ask the DOCUMENT whether it is empty, not build the
    whole buffer into a Python str to test its truthiness.

    Pinned by making toPlainText() fail loudly: it is a perfectly good API
    for copy/export (which genuinely need the text) and a 216 KB allocation
    in a paint path that runs once per streamed line.
    """
    from frontend.widgets import LiveConsole

    console = LiveConsole(TH.ThemeManager().t)
    console.resize(600, 200)
    for i in range(200):
        console.append_line(f"[{i:04d}] streaming output line")

    calls = []
    original = type(console).toPlainText

    def spy(self):
        calls.append(1)
        return original(self)

    # render() into a pixmap, NOT repaint(): Qt skips painting entirely for
    # a widget that was never shown, so a repaint()-driven version of this
    # test passes whatever paintEvent does. render() invokes paintEvent
    # directly and needs no visible window.
    target = QPixmap(console.size())
    target.fill(Qt.GlobalColor.transparent)
    try:
        type(console).toPlainText = spy
        painter = QPainter(target)
        console.render(painter, QPoint())
        painter.end()
        qapp.processEvents()
    finally:
        type(console).toPlainText = original

    assert console.blockCount() > 1, "the console under test was left empty"

    assert not calls, (
        f"paintEvent called toPlainText() {len(calls)}x — that materialises "
        "the entire console buffer on every repaint; use "
        "document().isEmpty()")


@pytest.mark.parametrize("state", ["fresh", "filled", "cleared"])
def test_the_empty_state_decision_is_unchanged(qapp, state):
    """document().isEmpty() must agree with the old truthiness test in
    every state the console can be in, or the fix traded cost for a
    missing (or a spurious) empty-state graphic."""
    from frontend.widgets import LiveConsole

    console = LiveConsole(TH.ThemeManager().t)
    if state == "filled":
        console.append_line("something")
    elif state == "cleared":
        console.append_line("something")
        console.clear_console()

    assert console.document().isEmpty() == (not console.toPlainText()), (
        f"{state}: the O(1) emptiness test disagrees with the old one")


# ============================================================
#  4. LEAK REGRESSIONS
# ============================================================
def _dialog_builders(window):
    from frontend import menu_structure as MS
    from frontend import widgets as W

    t = window.theme.t
    item = {"icon": "📦", "title": "Demo", "desc": "Demo card.",
            "task": "SystemInfo"}
    hub = {"icon": "🛠️", "title": "Hub", "desc": "Hub.", "hub": True,
           "items": [item]}
    return [
        ("ConfirmDialog", lambda: W.ConfirmDialog(window, item, t)),
        ("HubDialog", lambda: W.HubDialog(window, hub, t)),
        ("SoftwareCatalogDialog", lambda: W.SoftwareCatalogDialog(
            window, item, t, MS.SOFTWARE_CATALOG)),
        ("CommandPalette", lambda: W.CommandPalette(
            window, t, list(MS.iter_leaf_items()))),
        ("StorageAnalyzerDialog", lambda: W.StorageAnalyzerDialog(window, "", t)),
    ]


@pytest.mark.parametrize("name", [
    "ConfirmDialog", "HubDialog", "SoftwareCatalogDialog",
    "CommandPalette", "StorageAnalyzerDialog",
])
def test_repeated_modal_opens_do_not_accumulate(window, qapp, name):
    """Open/close is the loop a user runs hardest. A dialog that outlives
    its close keeps its whole widget tree — and its frost pixmap — parented
    to the window forever.
    """
    from frontend.widgets import PulseDialog

    build = dict(_dialog_builders(window))[name]
    counts = []
    for _ in range(3):
        dialog = build()
        dialog.show()
        _drain(qapp, 2)
        dialog.reject()
        dialog.deleteLater()
        del dialog
        _drain(qapp)
        gc.collect()
        counts.append(len(window.findChildren(PulseDialog)))

    assert counts[0] == counts[-1], (
        f"{name}: live dialog count climbed {counts} across three "
        "open/close cycles")


def test_a_closed_dialog_is_actually_destroyed(window, qapp):
    """The strongest form: nothing — not Qt, not a Python closure — still
    holds the dialog once it has been closed and deleted."""
    from frontend import widgets as W

    t = window.theme.t
    dialog = W.ConfirmDialog(
        window, {"icon": "📦", "title": "Demo", "desc": "d.",
                 "task": "SystemInfo"}, t)
    dialog.show()
    _drain(qapp, 2)
    ref = weakref.ref(dialog)
    dialog.reject()
    dialog.deleteLater()
    del dialog
    _drain(qapp)
    gc.collect()

    assert ref() is None, (
        "the dialog's Python wrapper outlived its deletion — something is "
        "still holding a reference (a lambda captured in a connect(), a "
        "module-level list, or a signal never disconnected)")


def test_module_navigation_does_not_accumulate(window, qapp):
    """Every page is built once, lazily, then reused. Sweeping all modules
    repeatedly must not rebuild them - the 31ms navigation budget depends
    on reuse.

    MEASURED ON THE PAGES AND THEIR CARDS, not on findChildren(object).
    The old form counted every QObject under the window and compared the
    totals, which made it a function of whatever transient machinery
    happened to be alive at each sample: a toast's dismiss timer and its
    ~8 children (wall-clock lifetimes of 2.5s and 8s from launch), the
    PageFader's animation group (replaced per fade), the read-only state
    probe's QThread (started and joined on its own schedule). None of
    those is navigation rebuilding a page, and all of them move.

    It surfaced when the ambient field was deleted: that removed a
    150-360ms deferral from every module switch, so the sweep finished
    sooner, and toasts which used to expire before the baseline now
    expired after it. The test reported "pages are being rebuilt" on a
    change whose entire content was deleting objects.

    Pages and cards are what the docstring is actually about, they are
    created exactly once, and nothing else in the app creates them - so
    counting them says the thing this test exists to say, and says it the
    same way on a fast machine and a slow one.
    """
    from frontend.main import CategoryPage
    from frontend.widgets import GlassCard

    for index in range(len(window.pages)):     # warm every lazy page first
        window.open_category(index)
        _drain(qapp, 2)
    window.go_home()
    _drain(qapp, 2)

    def census():
        return (len(window.findChildren(CategoryPage)),
                len(window.findChildren(GlassCard)),
                len(_navigation_timers(window)))

    base = census()

    for _ in range(3):
        for index in range(len(window.pages)):
            window.open_category(index)
            _drain(qapp, 2)
        window.go_home()
        _drain(qapp, 2)

    pages, cards, timers = census()
    assert (pages, cards) == base[:2], (
        f"module navigation rebuilt pages/cards: {base[:2]} -> "
        f"{(pages, cards)} - pages are meant to be built once and reused")
    assert timers == base[2], (
        "module navigation is adding timers - a per-visit QTimer that is "
        "never stopped keeps firing for the life of the session")


def _navigation_timers(window):
    """Every QTimer under `window` that a toast does not own.

    A toast's dismiss timer is a child of the window and its lifetime is
    wall-clock, so counting it would couple this assertion to how fast the
    sweep ran rather than to whether navigation leaks. See the note on the
    test above.
    """
    from utils.helpers import Toast

    def owned_by_toast(obj):
        node = obj.parent()
        while node is not None:
            if isinstance(node, Toast):
                return True
            node = node.parent()
        return False

    return [t for t in window.findChildren(QTimer) if not owned_by_toast(t)]




# ============================================================
#  5. WORKER-DIALOG TEARDOWN  (v10.3 final pass)
# ============================================================
# Seven dialogs run a PowerShellTask on a QThread parented to themselves.
# Each cancelled its worker in reject() — but cancelling only kills the
# backend PROCESS; the QThread lives on for the moment its read loop needs
# to unwind. Destroying a QThread that is still running is not an
# exception, it is qFatal: the process ABORTS, with no traceback, no Qt
# warning, and an exit code that says nothing.
#
# main.PulseApp.closeEvent has always paired cancel() with wait(3000) for
# the shell's own task thread. The dialogs only ever did the first half.
# Nothing caught it because the leak roster above deliberately stopped at
# the eleven thread-free dialogs — and extending it was not a "add three
# more names" change, it KILLED THE TEST RUNNER mid-session rather than
# reporting a failure, which is precisely why the gap survived this long.
_WORKER_DIALOGS = [
    "HealthReportDialog", "ActivationStatusDialog", "InspectorDialog",
    "StorageAnalyzerDialog", "UpdateCenterDialog", "StartupManagerDialog",
    # v10.8: the bloatware purge runs a read-only inventory scan on its
    # own thread before the user chooses anything, so it needs the same
    # settle-on-close guard as every other scanning dialog.
    "BloatwarePurgeDialog",
]


def _worker_dialog_builders(window):
    from frontend import widgets as W

    t = window.theme.t
    # Empty ps1_path: the dialogs still build their thread and worker, so
    # the teardown path under test is exercised in full, but the spawn
    # fails immediately instead of running a real backend scan in a test.
    return {name: (lambda n=name: getattr(W, n)(window, "", t))
            for name in _WORKER_DIALOGS}


def test_the_worker_dialog_roster_is_complete():
    """A hand-written list of class names is exactly the thing that goes
    stale. Parse widgets.py and assert nothing grew a QThread without
    being added here."""
    tree = ast.parse((_SRC / "frontend" / "widgets.py").read_text(
        encoding="utf-8"))
    threaded = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and "QThread(" in ast.unparse(node)
    }
    # DnsSwitcherDialog / ContextMenuDialog also own threads but are
    # constructed with extra arguments; they inherit the same guard.
    # SelfUpdateDialog likewise: its constructor takes an updater.Update,
    # not a ps1_path, AND its thread only starts on a user click rather
    # than at construction — see test_self_update_dialog_settles_its_
    # thread below for its own version of this guard.
    missing = threaded - set(_WORKER_DIALOGS) - {
        "DnsSwitcherDialog", "ContextMenuDialog", "SelfUpdateDialog"}
    assert not missing, (
        f"these dialogs grew a QThread and are not covered: {sorted(missing)}")


@pytest.mark.parametrize("name", _WORKER_DIALOGS)
def test_closing_a_worker_dialog_settles_its_thread(window, qapp, name):
    """After close, NO QThread the dialog owns may still be running.

    This is the assertion that stands between the app and a qFatal abort:
    anything that destroys the dialog after this point — Qt tearing down
    the parent window, a test calling deleteLater — is only safe because
    the thread is already joined.
    """
    from PySide6.QtCore import QThread

    dialog = _worker_dialog_builders(window)[name]()
    dialog.show()
    _drain(qapp, 2)
    dialog.reject()
    _drain(qapp, 2)

    running = [obj for obj in vars(dialog).values()
               if isinstance(obj, QThread) and obj.isRunning()]
    assert not running, (
        f"{name}: {len(running)} worker thread(s) still running after close — "
        "destroying the dialog now would abort the process (qFatal), not "
        "raise. PulseDialog.done() must cancel and join them.")
    dialog.deleteLater()
    _drain(qapp)


@pytest.mark.parametrize("name", _WORKER_DIALOGS)
def test_repeated_worker_dialog_opens_do_not_accumulate(window, qapp, name):
    """The leak loop the roster above could not safely run until the
    teardown guard existed."""
    from frontend.widgets import PulseDialog

    build = _worker_dialog_builders(window)[name]
    counts = []
    for _ in range(3):
        dialog = build()
        dialog.show()
        _drain(qapp, 2)
        dialog.reject()
        dialog.deleteLater()
        del dialog
        _drain(qapp)
        gc.collect()
        counts.append(len(window.findChildren(PulseDialog)))

    assert counts[0] == counts[-1], (
        f"{name}: live dialog count climbed {counts} across three cycles")


def test_the_dialog_wait_budget_matches_the_shell():
    """Same hazard, same budget. If main.py's wait is retuned and the
    dialogs' is not, the two disagree about how long a backend kill is
    allowed to take to land.

    Compares the two CONSTANTS. This used to grep main.py for the literal
    `wait(3000)`, which stopped meaning anything the moment the shell's
    budget became a named constant of its own — the string vanished while
    the invariant it stood for was intact. Reading both numbers tests the
    thing the string was only ever a proxy for.
    """
    from frontend.main import PulseApp
    from frontend.widgets import PulseDialog

    assert PulseApp._THREAD_WAIT_MS == PulseDialog._WORKER_WAIT_MS, (
        f"the shell waits {PulseApp._THREAD_WAIT_MS}ms for a background "
        f"thread but its dialogs wait {PulseDialog._WORKER_WAIT_MS}ms — the "
        "two must give a cancelled backend the same grace")


def test_grace_precedes_cancel_and_is_shorter_than_the_join():
    """The two budgets have different jobs and must not be transposed.

    GRACE is how long a worker gets to finish ON ITS OWN before it is
    killed; JOIN is how long the already-killed thread gets to unwind.
    Grace exists because two of the seven worker dialogs — the DNS
    switcher and the context-menu manager — run tasks that WRITE, and
    neither overrides reject(), so closing one mid-apply lands in this
    guard. A grace of 0 would turn 'user dismissed the sheet' into a
    process kill between the IPv4 and IPv6 resolver writes.
    """
    from frontend.widgets import PulseDialog

    assert 0 < PulseDialog._WORKER_GRACE_MS < PulseDialog._WORKER_WAIT_MS, (
        f"grace ({PulseDialog._WORKER_GRACE_MS}ms) must be a positive window "
        f"SHORTER than the post-cancel join ({PulseDialog._WORKER_WAIT_MS}ms)")


def test_an_already_cancelled_worker_costs_no_grace(window, qapp):
    """The five read-only dialogs cancel in their own reject(), so the
    backend process is already dead when the guard runs and the grace
    wait must return at once. If cancel and grace were ever reordered,
    every one of them would stall the full grace window on close —
    measured at 0.5ms today against a 1200ms budget.
    """
    dialog = _worker_dialog_builders(window)["UpdateCenterDialog"]()
    dialog.show()
    _drain(qapp, 2)
    if dialog._worker is not None:
        dialog._worker.cancel()

    start = time.perf_counter()
    dialog._settle_worker_threads()
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert elapsed_ms < 500.0, (
        f"settling an already-cancelled worker blocked for {elapsed_ms:.0f} ms "
        "— the grace wait is being spent on a thread that was already done")
    dialog.reject()
    dialog.deleteLater()
    _drain(qapp)


def _dummy_update():
    from utils import updater
    return updater.Update(
        version="99.0.0", tag="v99.0.0", notes="Test release notes.",
        url="https://example.invalid/PULSE_Setup_v99.0.0.exe",
        size=1024, sums_url="https://example.invalid/SHA256SUMS",
        asset_name="PULSE_Setup_v99.0.0.exe", prerelease=False)


def test_self_update_dialog_settles_its_thread_after_close(window, qapp, monkeypatch):
    """SelfUpdateDialog's own version of test_closing_a_worker_dialog_
    settles_its_thread — it is exempted from the generic roster above
    (different constructor, and the thread only starts on a user click,
    not at construction) but owns the exact same PulseDialog.done()-
    funnelled QThread and needs the exact same guard.

    updater.download is monkeypatched to block until released rather than
    hit the network — this test is about the Qt teardown machinery, not
    about updater.py's own download loop (see test_updater.py for that).
    """
    from PySide6.QtCore import QThread
    from frontend.widgets import SelfUpdateDialog
    from utils import updater as U

    release_evt = threading.Event()

    def fake_download(update, progress=None, cancel=None):
        while not release_evt.is_set():
            if cancel is not None and cancel():
                raise U.UpdateError("cancelled")
            release_evt.wait(0.02)
        return "C:\\fake\\PULSE_Setup_v99.0.0.exe"

    monkeypatch.setattr(U, "download", fake_download)
    monkeypatch.setattr(U, "verify", lambda path, update: None)

    dialog = SelfUpdateDialog(window, window.theme.t, _dummy_update())
    dialog.show()
    _drain(qapp, 2)
    dialog._start_download()
    _drain(qapp, 2)
    assert dialog._thread is not None and dialog._thread.isRunning(), (
        "the fake download should still be blocking at this point")

    dialog.reject()          # cancels the worker, then PulseDialog.done()
    release_evt.set()        # let the (already-cancelling) fake loop exit
    _drain(qapp, 3)

    running = [obj for obj in vars(dialog).values()
               if isinstance(obj, QThread) and obj.isRunning()]
    assert not running, (
        "SelfUpdateDialog: worker thread still running after close — "
        "destroying the dialog now would abort the process (qFatal)")
    dialog.deleteLater()
    _drain(qapp)


# ============================================================
#  WORKER SIGNALS MUST REACH THE GUI THREAD
# ============================================================
# THE FREEZE. PulseApp._check_for_updates connected its result slot as a
# bare `lambda upd: self._on_update_checked(upd, silent)`, purely to
# smuggle the extra `silent` flag through.
#
# A signal connected to a lambda gives Qt no QObject receiver to resolve a
# thread affinity from, so PySide falls back to the SENDER's thread and
# invokes it DIRECTLY. The sender was moveToThread()'d, so the slot ran on
# the worker thread — where it mutated the footer label, built a Toast
# (whose timers then had worker-thread affinity and no loop to drive them,
# which is why "Checking for updates…" sat frozen in the corner) and
# constructed + exec()'d a modal whose backdrop capture calls
# QWidget.grab(). Rendering from a non-GUI thread deadlocks against the GUI
# thread: Windows reported "Python is not responding".
#
# Every other worker in this app connects a BOUND METHOD, which resolves to
# the GUI thread and queues correctly. Two guards below: the behaviour, and
# the syntax that broke it.
def _relocated_lambda_connections(source: str, label: str = "<src>") -> list[str]:
    """Every `X.<signal>.connect(lambda ...)` where X was moveToThread()'d.

    Scoped to the enclosing function, which is how these are always
    written: `worker = ...; worker.moveToThread(thread); worker.sig...`.

    NARROW ON PURPOSE. A lambda on the signal of a GUI-RESIDENT object is
    perfectly safe — PlaybookRunner lives in the GUI thread (parented, never
    relocated) and emits from GUI-thread slots, so its lambdas run there
    too. The hazard is specifically a lambda on the signal of an object
    whose affinity has been moved off the GUI thread.
    """
    hits: list[str] = []
    tree = ast.parse(source, filename=label)
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        relocated = {
            ast.unparse(node.func.value)
            for node in ast.walk(scope)
            if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "moveToThread")
        }
        if not relocated:
            continue
        for node in ast.walk(scope):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"
                    and node.args
                    and isinstance(node.args[0], ast.Lambda)):
                continue
            signal = node.func.value
            if (isinstance(signal, ast.Attribute)
                    and ast.unparse(signal.value) in relocated):
                hits.append(f"{label}:{node.lineno} -> "
                            f"{ast.unparse(signal)}.connect(lambda ...)")
    return hits


def test_the_relocated_lambda_scanner_actually_catches_the_bug():
    """Guard the guard. A scanner that silently matches nothing would pass
    the test below forever — this is the exact code shape that froze the
    app, and it must be detected."""
    bad = _relocated_lambda_connections(
        "def _check(self, silent):\n"
        "    thread = QThread(self)\n"
        "    worker = SelfUpdateCheckWorker()\n"
        "    worker.moveToThread(thread)\n"
        "    worker.finished.connect(lambda u: self._done(u, silent))\n",
        "sample")
    assert len(bad) == 1, f"the scanner missed the known-bad shape: {bad}"

    good = _relocated_lambda_connections(
        "def _check(self, silent):\n"
        "    thread = QThread(self)\n"
        "    worker = SelfUpdateCheckWorker()\n"
        "    worker.moveToThread(thread)\n"
        "    worker.finished.connect(self._done)\n"
        "    runner.finished.connect(lambda r: self._other(r))\n",
        "sample")
    assert not good, f"the scanner flagged safe connections: {good}"


def test_no_relocated_worker_signal_is_connected_to_a_lambda():
    """The generalised guard for the freeze above.

    A lambda has no QObject receiver, so Qt cannot queue it onto the GUI
    thread — it runs wherever the sender lives, and the sender here has
    been moved OFF the GUI thread. Connect a BOUND METHOD of a GUI-thread
    QObject and carry any extra arguments as state (see
    PulseApp._update_check_silent), or emit them through the signal.
    """
    hits: list[str] = []
    paths = sorted((_SRC / "frontend").glob("*.py")) + [_SRC / "utils" / "helpers.py"]
    for path in paths:
        hits += _relocated_lambda_connections(
            path.read_text(encoding="utf-8"), path.name)
    assert not hits, (
        "these signals belong to moveToThread()'d workers but are connected to "
        "lambdas, which PySide runs on the SENDER's thread — off the GUI "
        "thread, where touching a widget is undefined behaviour and rendering "
        "one deadlocks:\n  " + "\n  ".join(hits))


def _settle_update_check(window, qapp, budget_s: float = 20.0):
    """Wait out any check already in flight (the app fires one ~2.5s after
    launch, and `window` is session-scoped, so it may still be running)."""
    deadline = time.time() + budget_s
    while window._update_check_thread is not None and time.time() < deadline:
        _drain(qapp, 1)
    return window._update_check_thread is None


def test_the_update_check_result_lands_on_the_gui_thread(window, qapp, monkeypatch):
    """The freeze itself, pinned as behaviour rather than as syntax.

    Asserts the thread `_on_update_checked` actually runs on, so this still
    fails if the connection is broken some other way than a lambda.
    `toasts.show` is the probe because the slot calls it and monkeypatching
    it cannot disturb the connection under test — patching the slot itself
    would REPLACE a bound method with a plain function and manufacture the
    very bug being measured.
    """
    from PySide6.QtCore import QThread
    from utils import updater as U

    assert _settle_update_check(window, qapp), "a prior check never settled"

    gui_thread = QThread.currentThread()
    seen: list = []

    # SelfUpdateCheckWorker.run looks `check` up on the module at call
    # time, so patching the attribute is enough to keep this off the wire.
    monkeypatch.setattr(U, "check", lambda current=None, channel=None: None)
    monkeypatch.setattr(window.toasts, "show",
                        lambda *a, **k: seen.append(QThread.currentThread()))

    window._check_for_updates(silent=False)     # silent=False -> slot toasts
    deadline = time.time() + 10.0
    while not seen and time.time() < deadline:
        _drain(qapp, 1)

    assert seen, "the update check never delivered a result"
    assert seen[0] is gui_thread, (
        "_on_update_checked ran on a worker thread. It mutates widgets and can "
        "exec() a modal whose backdrop capture renders — off the GUI thread "
        "that is the 'Python is not responding' deadlock, not an exception.")
    assert _settle_update_check(window, qapp), "the check thread never settled"


def test_closing_settles_all_three_background_threads(window, qapp, monkeypatch):
    """The shell owns THREE background threads, and closeEvent used to join
    exactly one of them.

    The task thread was always cancelled and joined; the applied-state probe
    and the self-update check were not. Closing while either was in flight
    destroyed a running QThread (qFatal) and let its worker emit into a
    deleted receiver — reproduced as `RuntimeError: Signal source has been
    deleted` out of SelfUpdateCheckWorker.run.

    Driven through _settle_background_threads rather than a real close: the
    `window` fixture is session-scoped and shared, so actually closing it
    would take every later test down with it.
    """
    from PySide6.QtCore import QThread
    from utils import updater as U

    assert _settle_update_check(window, qapp), "a prior check never settled"

    started = threading.Event()
    release = threading.Event()

    def slow_check(current=None, channel=None):
        started.set()
        release.wait(8.0)          # bounded, so a bug cannot hang the suite
        return None

    monkeypatch.setattr(U, "check", slow_check)
    window._check_for_updates(silent=True)

    deadline = time.time() + 5.0
    while not started.is_set() and time.time() < deadline:
        _drain(qapp, 1)
    assert started.is_set(), "the check worker never started"

    thread = window._update_check_thread
    assert thread is not None and thread.isRunning()

    # The window would be destroyed right after this returns, so nothing it
    # owns may still be attached to a live thread.
    window._settle_background_threads()
    release.set()

    still_parented = [
        t for t in (window._thread, window._probe_thread,
                    window._update_check_thread)
        if isinstance(t, QThread) and t.isRunning() and t.parent() is window]
    assert not still_parented, (
        f"{len(still_parented)} running thread(s) are still parented to the "
        "window after settling — Qt would destroy them mid-run, which is "
        "qFatal (an abort), not an exception")

    # DRAINING UNTIL IT STOPS, WITHOUT ASSUMING THE WRAPPER SURVIVES.
    # `thread` is a Python handle on an object the app owns and is in the
    # middle of tearing down: settling schedules its deleteLater, and the
    # very drain loop below is what delivers it. Asking a dangling wrapper
    # `isRunning()` then raises "Internal C++ object already deleted" — the
    # thread having gone away IS the condition this loop is waiting for,
    # so the exception is the success case arriving early rather than a
    # failure. Observed as an intermittent RuntimeError here under load.
    deadline = time.time() + 10.0
    while time.time() < deadline:
        try:
            if not thread.isRunning():
                break
        except RuntimeError:
            break          # deleted out from under us: settled, and gone
        _drain(qapp, 1)
    _drain(qapp, 2)


def test_done_is_the_guard_point_not_reject():
    """reject() is not the only way out: a dialog that closes by ACCEPTING
    with a scan still in flight is the same hazard. done() is the funnel
    both paths pass through, so the guard belongs there."""
    from frontend.widgets import PulseDialog

    assert "done" in vars(PulseDialog), (
        "PulseDialog.done() is where the worker-thread join lives — moving "
        "it to reject() would leave accept() unguarded")
