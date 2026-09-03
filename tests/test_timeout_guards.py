"""
Nothing the engine calls may hang forever.

THE BACKSTOP THAT ALREADY EXISTED
    Every PowerShell invocation in the app goes through
    helpers.PowerShellTask, and every call site passes a timeout - 90s for
    the applied-state probe, 120s for activation, 180s for the health
    report, per-task values from menu_structure, and DEFAULT_TIMEOUT (900)
    for the rest. A watchdog thread kills the whole process tree at the
    deadline and the run is reported as a failure. So there was never a
    path to an INFINITE hang; the audit confirmed that rather than
    assuming it.

WHAT THE BACKSTOP DOES NOT DO IS FAIL FAST
    Pulse is a repair tool, so its users are disproportionately on
    machines that are already unwell - and a degraded or corrupt WMI
    repository is one of the commonest ways a Windows box is unwell. Every
    system probe here is a Get-CimInstance, and against a sick repository
    those do not error, they block. With only the outer watchdog, a
    machine in that state shows a spinner for 90 seconds (or 15 minutes on
    a default-timeout task) before saying anything at all - and
    Get-PulseSystemInfo runs a CIM query at engine STARTUP, so it is in
    front of every task, not just the reporting ones.

    A per-operation CIM timeout turns that into a bounded failure the
    surrounding -ErrorAction/try-catch already knows how to report.

WHY A SESSION DEFAULT RATHER THAN 19 EDITS
    $PSDefaultParameterValues applies the bound to every Get-CimInstance
    in the session from one line, including any added later - which is the
    part a call-site sweep cannot promise. It also cannot break a call
    site by mis-editing a backtick continuation, and several of these
    calls have them.

MEASURED WHILE CHOOSING THE VALUE: a 1-second bound made
Get-CimInstance Win32_Processor throw CimException on a HEALTHY machine.
Legitimate queries are not instant, so the number has to clear real work
by a wide margin while staying far under the smallest task timeout.
"""
from __future__ import annotations

import os
import re

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts: str) -> str:
    with open(os.path.join(_ROOT, *parts), encoding="utf-8-sig") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def core() -> str:
    return _read("src", "backend", "core.ps1")


class TestTheCimBoundExists:
    def test_a_session_wide_cim_timeout_is_registered(self, core):
        assert re.search(
            r"PSDefaultParameterValues\[\s*['\"]Get-CimInstance:"
            r"OperationTimeoutSec['\"]\s*\]", core), (
            "no session-wide CIM timeout — a degraded WMI repository "
            "blocks every system probe until the task watchdog fires")

    def test_it_is_global_so_every_module_inherits_it(self, core):
        """The modules are dot-sourced and their functions run at whatever
        depth a task calls them from. A script-scoped default would apply
        to core.ps1's own lines and quietly not to theirs."""
        assert re.search(
            r"\$Global:PSDefaultParameterValues\[\s*['\"]Get-CimInstance:",
            core), (
            "the CIM default is not Global, so dot-sourced module "
            "functions do not inherit it")

    def test_the_bound_clears_real_work_but_beats_every_task_timeout(self,
                                                                     core):
        """Both directions matter. Too low and healthy-but-slow machines
        get spurious failures (measured: a 1s bound throws on this one).
        Too high and it stops being a fail-fast at all, since the task
        watchdog was already going to kill the tree."""
        match = re.search(
            r"PSDefaultParameterValues\[\s*['\"]Get-CimInstance:"
            r"OperationTimeoutSec['\"]\s*\]\s*=\s*(\d+)", core)
        assert match, "the CIM timeout is not a plain literal any more"
        seconds = int(match.group(1))
        assert seconds >= 15, (
            f"{seconds}s is close enough to real query times to fail on a "
            "healthy but loaded machine")
        assert seconds <= 60, (
            f"{seconds}s is not a fail-fast; the 90s probe watchdog would "
            "have caught it anyway")

    def test_it_is_set_before_the_modules_are_loaded(self, core):
        """A default registered after the dot-source still covers later
        CALLS, but not any query a module runs while loading."""
        default_at = core.index("Get-CimInstance:OperationTimeoutSec")
        # The dot-source loop that pulls in src/backend/modules.
        loader = re.search(r"foreach\s*\(\s*\$\w+\s+in\s+.*[Mm]odule", core)
        if loader is None:
            pytest.skip("module loader loop not recognised in core.ps1")
        assert default_at < loader.start(), (
            "the CIM bound is registered after modules load")


class TestEveryPowerShellSpawnIsBounded:
    """The backstop itself, pinned so it cannot quietly go missing."""

    def test_the_task_runner_arms_a_watchdog(self):
        import inspect
        from utils.helpers import PowerShellTask

        source = inspect.getsource(PowerShellTask.run)
        assert "threading.Timer" in source, (
            "PowerShellTask no longer arms a watchdog — a hung child is "
            "now an unbounded hang")
        assert "_kill_process_tree" in source

    def test_every_frontend_spawn_passes_a_timeout(self):
        """A PowerShellTask constructed without one falls back to
        DEFAULT_TIMEOUT, which is correct — this asserts the call sites
        that need a TIGHTER bound still declare one, so a read-only probe
        cannot silently inherit the 15-minute default."""
        import re as _re

        for module in ("main.py", "widgets.py", "playbooks.py"):
            source = _read("src", "frontend", module)
            for call in _re.finditer(r"PowerShellTask\((.{0,220})", source,
                                     _re.S):
                body = call.group(1)
                assert "timeout" in body, (
                    f"a PowerShellTask in {module} declares no timeout:\n"
                    f"  {body[:120]}")

    def test_the_taskkill_fallback_stays_bounded(self):
        """Added in the responsiveness pass; re-asserted here because it
        is the one bounded call that runs on the GUI thread."""
        from utils.helpers import PowerShellTask

        assert 0 < PowerShellTask.TASKKILL_TIMEOUT <= 5


class TestNetworkCallsInTheEngine:
    def test_no_web_request_is_unbounded(self):
        """The winget bootstrap downloads from the Microsoft CDN and from
        GitHub; either can stall on a captive portal or a dead mirror."""
        offenders = []
        modules = os.path.join(_ROOT, "src", "backend", "modules")
        for name in sorted(os.listdir(modules)):
            if not name.endswith(".ps1"):
                continue
            for number, line in enumerate(
                    _read("src", "backend", "modules", name).splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if ("Invoke-WebRequest" in stripped
                        or "Invoke-RestMethod" in stripped):
                    if "-TimeoutSec" not in stripped:
                        offenders.append(f"{name}:{number}: {stripped[:70]}")
        assert not offenders, (
            "network calls with no -TimeoutSec:\n  " + "\n  ".join(offenders))
