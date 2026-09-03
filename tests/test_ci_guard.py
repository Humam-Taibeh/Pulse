"""
The CI guard that keeps going blind, pinned so it cannot go blind again.

WHAT THE GUARD IS FOR
    80 tests in this suite are marked `native`: they hit-test the
    non-client area, query DWM and pump real Win32 messages, none of which
    exist on Qt's offscreen platform. conftest skips them automatically
    when QT_QPA_PLATFORM=offscreen. That is correct behaviour locally and
    a silent catastrophe on CI — a runner that lost its desktop session
    would report a green build having tested none of the Win32 behaviour
    the guard exists to protect.

WHY IT KEPT FAILING AT THAT JOB
    It asserted a floor on the number of tests EXECUTED (`ran >= N`).
    That is a function of the whole suite's size, so every time the suite
    grew, a headless run executed more tests and drifted up toward the
    floor. Measured twice, stale twice:

        written  at  713 collected, floor 670
        re-measured  991 collected, floor 950
        by          1031 collected, a headless run executes 949

    — one test from clearing its own floor. The number was always going
    to be overtaken by the suite it was measured against.

WHAT REPLACED IT
    The SKIPPED count. A headless runner skips the native subset wholesale
    (82 measured, including the environment cases); a healthy one skips
    only those environment cases (1 measured here, 3 on an elevated CI
    runner). Unlike the execution floor, that separation WIDENS as the
    suite grows — more native tests means a larger headless skip count,
    further from the threshold, while the healthy figure stays put.

    Verified against a real offscreen run before it was adopted:

        healthy   collected=1031 ran=1030 skipped=1
        headless  collected=1031 ran=949  skipped=82
"""
from __future__ import annotations

import os
import re

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CI = os.path.join(_ROOT, ".github", "workflows", "ci.yml")

#: The threshold in ci.yml. Duplicated here deliberately — a test that
#: read it out of the file could not notice the file changing it to
#: something useless, which is the whole failure mode being guarded.
_SKIP_THRESHOLD = 20


@pytest.fixture(scope="module")
def ci() -> str:
    with open(_CI, encoding="utf-8") as handle:
        return handle.read()


def test_the_guard_keys_on_skips_not_on_an_execution_floor(ci):
    """The specific regression: reverting to `ran -lt N` reintroduces a
    threshold that the suite's own growth eventually satisfies."""
    assert re.search(r"\$skipped\s+-gt\s+\d+", ci), (
        "the native-suite guard no longer keys on the skipped count")
    assert not re.search(r"\$ran\s+-lt\s+\d+", ci), (
        "the guard is back to a floor on tests EXECUTED — that is the "
        "design that went stale twice, because a growing suite eventually "
        "clears any fixed execution floor without running the native tests")


def test_the_skip_threshold_is_the_one_this_suite_was_measured_against(ci):
    """A threshold raised to quiet a red build is the failure this guard
    exists to prevent, and it would be invisible in review."""
    match = re.search(r"\$skipped\s+-gt\s+(\d+)", ci)
    assert match, "the skipped-count comparison is gone"
    assert int(match.group(1)) == _SKIP_THRESHOLD, (
        f"ci.yml now tolerates {match.group(1)} skips against the "
        f"{_SKIP_THRESHOLD} this suite was measured for — raise it only "
        "alongside a real increase in environment-conditional skips")


def test_a_headless_run_still_trips_the_threshold_by_a_wide_margin():
    """The guard only works while the native subset is much larger than
    the threshold. If native coverage were deleted down toward 20 tests, a
    headless runner would stop tripping it and the guard would go quiet —
    the same silent failure in a new form.

    Counted by real collection rather than from a comment, and in a
    SUBPROCESS rather than off this session's item list: the live session
    only holds what the current invocation selected, so reading it would
    report 0 whenever this file is run on its own and quietly pass. This
    is the same `pytest --collect-only -m native` the ci.yml comment
    documents as the measurement method.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
         "-m", "native"],
        cwd=_ROOT, capture_output=True, text=True, timeout=300)
    native = sum(int(m) for m in re.findall(r":\s*(\d+)\s*$",
                                            result.stdout, re.MULTILINE))

    assert native > _SKIP_THRESHOLD * 2, (
        f"only {native} native tests remain against a {_SKIP_THRESHOLD}-skip "
        "threshold — a headless runner would no longer reliably trip the "
        "guard, so either native coverage has been gutted or the threshold "
        "needs re-measuring against it")


def test_the_collected_floor_is_a_real_floor(ci):
    """The second check in that step, and it is safe as a literal in a way
    the execution floor was not: collection only grows, so a count falling
    under it is a genuine failure (an import error takes a whole module's
    tests with it silently). It just must not be set ABOVE the suite, or
    it fails every healthy build."""
    match = re.search(r"\$total\s+-lt\s+(\d+)", ci)
    assert match, "the collection-integrity floor is gone"
    floor = int(match.group(1))
    assert floor < 1031, (
        f"the collected floor is {floor}, at or above the current suite "
        "size — every healthy build would fail")
