"""
Volumes that do not answer normally: locked, mapped, unreadable.

WHAT A DIFFICULT VOLUME ACTUALLY LOOKS LIKE
    The awkward cases converge on the same two shapes rather than on
    anything filesystem-specific:

      * A BitLocker-locked drive is present and enumerable, and reports
        its size and free space as NULL.
      * A disconnected mapped drive, an offline volume, or one the
        process cannot open reports null or raises, and a share that
        answers can report a total of ZERO.

    That is why the engine's guards are shaped as null-and-zero checks
    rather than as drive-type tests: they hold for BitLocker, for a dead
    UNC path and for exFAT or ReFS equally, because none of them depend
    on knowing which case occurred. The audit that produced this file
    found all four enumeration sites already guarded that way -

        07-Maintenance    null filter, then `if ($TotalGB -gt 0)`
        12-HealthReport   null filter, then `if ($total -le 0) { continue }`
        14-Inspectors     DriveType=3 filter, no division at all
        30-GuiDispatcher  null filter AND `(Used + Free) -gt 0`

    - so nothing here is a fix. What was missing is that none of it was
      pinned, and a percent-free line is exactly the sort of thing a later
      change adds without re-deriving why the divisor was checked.

WHAT IS TESTED WHERE
    The engine's guards are asserted against its source, because a
    BitLocker-locked volume cannot be conjured on a CI runner. The
    PRESENTATION side is exercised for real, by feeding it the payload
    shapes those volumes produce - null sizes, zero totals, missing keys -
    and requiring it to render rather than raise.
"""
from __future__ import annotations

import os
import re

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _module(name: str) -> str:
    with open(os.path.join(_ROOT, "src", "backend", "modules", name),
              encoding="utf-8-sig") as handle:
        return handle.read()


class TestTheEngineGuardsItsDivisors:
    def test_the_health_report_skips_a_zero_total(self):
        """A locked volume that slips past the null filter would otherwise
        divide by zero building percentFree."""
        source = _module("12-HealthReport.ps1")
        assert re.search(r"if\s*\(\s*\$total\s+-le\s+0\s*\)\s*\{\s*continue",
                         source), (
            "the health report divides by a drive total it has not checked")

    def test_the_health_report_drops_drives_with_no_numbers(self):
        source = _module("12-HealthReport.ps1")
        assert "$null -ne $_.Used -and $null -ne $_.Free" in source, (
            "a BitLocker-locked drive reports null Used/Free and would now "
            "reach the arithmetic below")

    def test_the_drive_space_report_checks_both_null_and_zero(self):
        """The dispatcher's is the strictest of the four, and the one the
        GUI's own drive report calls."""
        source = _module("30-GuiDispatcher.ps1")
        assert re.search(
            r"\$null -ne \$_\.Used -and \$null -ne \$_\.Free -and "
            r"\(\(\$_\.Used \+ \$_\.Free\) -gt 0\)", source), (
            "DriveSpaceReport no longer rejects null-or-zero volumes")

    def test_maintenance_guards_its_percentage(self):
        source = _module("07-Maintenance.ps1")
        assert re.search(r"if\s*\(\s*\$TotalGB\s+-gt\s+0\s*\)", source), (
            "the maintenance drive line computes a percentage without "
            "checking the total")

    def test_the_inspector_asks_for_local_disks_only(self):
        """DriveType 3 is Local Disk. It excludes network (4) and
        removable (2), which is what keeps a dead mapped drive out of a
        storage scan that would otherwise block on it."""
        source = _module("14-Inspectors.ps1")
        assert "'DriveType = 3'" in source


class TestThePresentationSurvivesTheShapes:
    """Fed the payloads those volumes actually produce."""

    @pytest.fixture
    def locked_drive_report(self) -> dict:
        """A health report whose drive list came back degraded: one good
        volume, one that answered with nothing."""
        return {
            "drives": [
                {"name": "C", "totalGB": 476.0, "freeGB": 92.5,
                 "percentFree": 19},
                {"name": "E", "totalGB": None, "freeGB": None,
                 "percentFree": None},
            ],
        }

    def test_the_low_disk_finding_tolerates_a_null_percentage(
            self, locked_drive_report):
        """findings() decides whether to warn with
        `float(drive.get("percentFree", 100)) < LOW_DISK_PERCENT`, and the
        default there is a trap worth pinning: .get returns None when the
        key EXISTS holding None, so the 100 never applies to a locked
        drive and float(None) is a TypeError rather than a False. It is
        caught - `except (TypeError, ValueError): continue` - and this
        asserts that catch stays, because removing it looks like removing
        dead defensive code."""
        from frontend import health_report

        result = health_report.findings(locked_drive_report)

        assert isinstance(result, list), (
            "findings() did not survive a drive with a null percentFree")
        assert not any("None" in line for line in result), (
            f"a locked drive was reported as a low-disk finding: {result}")

    def test_a_healthy_drive_is_still_reported_beside_a_locked_one(self):
        """The failure that would hide behind the tolerance above: a
        degraded volume must not suppress the warning about a real one."""
        from frontend import health_report

        result = health_report.findings({"drives": [
            {"name": "E", "totalGB": None, "freeGB": None,
             "percentFree": None},
            {"name": "C", "totalGB": 476.0, "freeGB": 4.0,
             "percentFree": 1},
        ]})
        assert any("Drive C" in line for line in result), (
            f"the low-disk warning for C was lost: {result}")

    def test_the_json_export_survives_a_degraded_drive(self,
                                                       locked_drive_report):
        """The diffable half of the same deliverable."""
        from frontend import health_report

        assert health_report.to_json(locked_drive_report)

    def test_the_html_export_renders_a_degraded_drive(self,
                                                      locked_drive_report):
        """The export is a deliverable a technician hands to someone else,
        so a locked drive must appear as a row with blanks rather than
        taking the report down."""
        from frontend import health_report

        html = health_report.to_html(locked_drive_report)
        assert "<" in html and "C" in html, (
            "the HTML export dropped the healthy drive along with the "
            "degraded one")

    @pytest.mark.parametrize("payload", [
        {"totalBytes": 0, "freeBytes": 0},
        {"totalBytes": None, "freeBytes": None},
        {},
    ])
    def test_the_storage_analyzer_formats_a_dead_volume(self, payload, qapp):
        """StorageAnalyzerDialog._human is what every byte figure in that
        dialog goes through, including a volume that reported nothing."""
        from frontend.widgets import StorageAnalyzerDialog

        rendered = StorageAnalyzerDialog._human(payload.get("totalBytes") or 0)
        assert isinstance(rendered, str) and rendered, (
            f"a volume reporting {payload} produced no readable size")

    def test_the_byte_formatter_never_divides_by_zero(self):
        from frontend.widgets import StorageAnalyzerDialog

        for value in (0, None, 0.0, -1):
            assert StorageAnalyzerDialog._human(value)
