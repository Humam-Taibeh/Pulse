"""
Every PowerShell function in the engine is defined in exactly ONE module.

WHY THIS IS A TEST AND NOT A CONVENTION
    core.ps1 dot-sources every module into one shared scope, in name
    order. A function defined in two modules does not fail: the later
    definition silently REPLACES the earlier one for the whole engine, and
    every Pester suite that dot-sources only the earlier module keeps
    testing a copy the application no longer runs.

    That is not hypothetical. v10.13 moved three resolution helpers
    (Get-CommandTargetPath, Get-ShortcutTargetPath, Get-PulseScheduledTasks)
    into 05-Startup.ps1 so the Startup Manager and the Leftovers Cleaner
    share them - and for one intermediate state both modules carried a
    copy. Two copies of "what file does this command launch?" are two
    chances for the Startup Manager's MISSING badge and the cleaner's
    verdict to disagree about the same entry.

WHAT COUNTS
    A `function Name {` at the start of a line - a top-level definition.
    Names are compared case-insensitively, because PowerShell resolves them
    that way. A definition repeated inside ONE module is reported too: the
    second silently wins there for exactly the same reason.
"""
from __future__ import annotations

import collections
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODULES = os.path.join(_ROOT, "src", "backend", "modules")
_DEFINITION = re.compile(r"^function\s+([A-Za-z][\w-]*)\s*\{", re.MULTILINE)


def _definitions() -> dict[str, list[str]]:
    seen: dict[str, list[str]] = collections.defaultdict(list)
    for name in sorted(os.listdir(_MODULES)):
        if not name.endswith(".ps1"):
            continue
        with open(os.path.join(_MODULES, name), encoding="utf-8-sig") as handle:
            text = handle.read()
        for function in _DEFINITION.findall(text):
            seen[function.lower()].append(name)
    return seen


def test_the_scan_finds_the_engine():
    """A parser that matches nothing makes the real assertion pass for the
    wrong reason."""
    definitions = _definitions()
    assert len(definitions) > 150, (
        f"only {len(definitions)} functions found - the pattern no longer "
        "matches how modules declare them")
    assert "get-startupreportdata" in definitions


def test_no_function_is_defined_twice():
    duplicated = {name: files for name, files in _definitions().items()
                  if len(files) > 1}
    assert not duplicated, (
        "functions defined more than once - the later module silently "
        "replaces the earlier one for the whole engine:\n  "
        + "\n  ".join(f"{name}: {', '.join(files)}"
                      for name, files in sorted(duplicated.items())))
