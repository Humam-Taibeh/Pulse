"""
The release pipeline's invariants, pinned where CI cannot reach them.

WHY THIS FILE EXISTS AT ALL
    ci.yml is exercised by every push, so a mistake in it is loud. Almost
    none of release.yml is: the publish step runs only on a tag push, and
    a tag is pushed a handful of times a year. Between those, the step is
    ordinary-looking YAML that anyone may tidy, and the first evidence
    that a tidy-up broke it would be a release that half-published.

    So these are the properties whose loss is SILENT, argued for at the
    call site and asserted here. tests/test_ci_guard.py does the same job
    for ci.yml; this is its counterpart.

WHAT IS DELIBERATELY NOT HERE
    Nothing that a run would catch anyway. If the build step breaks, the
    build fails and says so. These tests only cover the things that fail
    quietly, or fail somewhere nobody is looking.
"""
from __future__ import annotations

import os
import re

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RELEASE = os.path.join(_ROOT, ".github", "workflows", "release.yml")


@pytest.fixture(scope="module")
def release() -> str:
    with open(_RELEASE, encoding="utf-8") as handle:
        return handle.read()


def _step(text: str, name: str) -> str:
    """The body of one `- name: <name>` step, up to the next step."""
    start = text.index(f"- name: {name}")
    nxt = text.find("\n      - name: ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


def test_the_publish_step_relaxes_the_error_preference_around_gh(release):
    """THE REGRESSION THIS FILE WAS WRITTEN FOR, and it was measured
    rather than imagined.

    A `shell: powershell` step runs with $ErrorActionPreference = 'Stop'
    prepended by the runner, and in Windows PowerShell that makes ANY
    line a NATIVE command writes to stderr a TERMINATING error. gh writes
    upload progress to stderr, and writes "release not found" to stderr
    for the `gh release view` probe that is SUPPOSED to fail on a first
    publish.

    Run against a stub gh in real Windows PowerShell 5.1, the version
    without this relaxation exited 1 with two NativeCommandErrors and
    never reached the end of the step, while the release it was creating
    had already been created. The version with it exited 0 and completed.

    Removing the two assignments looks like tidying dead ceremony. It is
    the difference between a release publishing and a tag left holding
    whichever assets happened to upload before the step died.
    """
    step = _step(release, "Publish the release")
    assert "$ErrorActionPreference = 'Continue'" in step, (
        "the publish step no longer relaxes $ErrorActionPreference around "
        "gh, so gh's ordinary stderr output will abort it mid-publish")
    assert re.search(r"finally\s*\{\s*\n\s*\$ErrorActionPreference = \$previous",
                     step), (
        "the preference is relaxed but never restored in a finally")
    relax = step.index("$ErrorActionPreference = 'Continue'")
    assert relax < step.index("gh release"), (
        "the first gh call happens before the preference is relaxed")


def test_the_release_is_never_marked_a_prerelease(release):
    """src/utils/updater.py checks /releases/latest on its primary path,
    and that endpoint EXCLUDES prereleases. So `--prerelease` would
    publish a release that every installed copy is structurally unable to
    see - and the README's own "Beta software" banner makes adding it
    look like a correction rather than a break."""
    step = _step(release, "Publish the release")
    # Comments stripped: the header of this workflow DISCUSSES --prerelease
    # at length in order to explain why it is absent, and a naive search
    # matches that explanation rather than the command.
    commands = [line for line in step.splitlines()
                if not line.lstrip().startswith("#")]
    assert not any("--prerelease" in line for line in commands), (
        "releases are being marked as GitHub prereleases, which hides "
        "them from updater.py's /releases/latest check")
    assert any("--latest" in line for line in commands), (
        "the release is no longer flagged --latest, which is what "
        "/releases/latest resolves to")


def test_the_checksums_are_verified_before_anything_is_published(release):
    """Order is the whole guarantee, exactly as it is for the engine's
    integrity gate. updater.py refuses any download whose digest is not
    listed in SHA256SUMS, so a release published before that check is one
    every existing install may silently decline - a failure invisible
    from the releases page."""
    verify = release.index("- name: Verify what is about to be published")
    publish = release.index("- name: Publish the release")
    assert verify < publish, (
        "the release is published before its checksums are verified")


def test_the_tag_is_checked_against_the_version_file(release):
    """The installer is NAMED from VERSION while updater.py compares
    against the TAG, so a mismatch ships an update that offers one
    version and installs another, then offers it again forever."""
    step = _step(release, "Check the tag against VERSION")
    assert 'if ($tag -ne "v$version")' in step, (
        "the tag is no longer compared against the VERSION file")


def test_the_gates_are_ci_yml_rather_than_a_second_copy(release):
    """A release must not be able to pass gates that a push cannot. If
    this workflow grows its own test job, "green" comes to mean two
    different things and the weaker one is the one that ships."""
    assert "uses: ./.github/workflows/ci.yml" in release, (
        "release.yml no longer calls ci.yml, so its gates can drift from "
        "the ones every push has to clear")
    assert re.search(r"needs:\s*verify", release), (
        "the build job no longer depends on the gates")


def test_github_env_is_written_without_a_bom(release):
    """Out-File -Encoding utf8 writes a BOM in Windows PowerShell 5.1.
    Appended to $GITHUB_ENV mid-file, that BOM becomes part of the next
    variable's NAME, so the runner defines "<BOM>PULSE_VERSION" and every
    later step reads an empty version.

    `ascii` looks like the older, worse choice and is the correct one:
    both values are constrained to ASCII by the regex immediately above
    them, and ascii is the one encoding PowerShell 5.1 will not prepend a
    BOM to."""
    for line in release.splitlines():
        if "GITHUB_ENV" in line and "Out-File" in line:
            assert "-Encoding ascii" in line, (
                f"a GITHUB_ENV write no longer pins ascii: {line.strip()!r} "
                "- utf8 writes a BOM in PowerShell 5.1 and corrupts the "
                "variable name that follows it")
