"""
The elevated engine only runs code the build produced.

THE GAP THIS CLOSES
    core.ps1 loaded its engine by GLOB:

        $ModuleFiles = @(Get-ChildItem -Path $ModuleRoot -Filter "*.ps1" -File
                         | Sort-Object Name)
        foreach ($ModuleFile in $ModuleFiles) { . $ModuleFile.FullName }

    Every .ps1 it finds, dot-sourced into script scope, under
    requireAdministrator, with -ExecutionPolicy Bypass. No allowlist, no
    integrity check. An attacker does not need to modify a file to get
    elevated execution - dropping a new one into that folder is enough,
    and it runs on the next launch.

    On the INSTALLED build this is already closed, deliberately: Program
    Files is not user-writable, which pulse.iss documents as exactly this
    defence. The exposure is the other channels - the README's supported
    "run from source" mode, which lives in a user-writable directory, and
    the portable ZIP the roadmap plans as a secondary distribution.

WHY A MANIFEST RATHER THAN SIGNATURES
    Authenticode on each .ps1 is the stronger answer and is already on the
    roadmap, but it needs a certificate from a CA - which is the thing
    Pulse does not have and cannot self-issue meaningfully (see
    tools/create_dev_signing_cert.ps1's header). A manifest needs nothing
    external, ships inside the bundle the modules already ship in, and
    answers the question that actually matters here: is this the code the
    build produced. The two compose - signing proves WHO, the manifest
    proves WHAT.

THE THREE FAILURES IT HAS TO CATCH, and only one of them is "tampering"
in the obvious sense:

    MODIFIED   a listed module whose bytes changed
    ADDED      a .ps1 on disk that the manifest does not list  <- the
               actual attack; verifying only listed files would miss it
               entirely
    MISSING    a listed module that is not on disk, which is a broken or
               partial install rather than an attack, and is equally
               unsafe to run half of

PERMISSIVE WITHOUT A MANIFEST, on purpose. A developer checkout has none
(it is a build artifact and gitignored), and refusing to run there would
make the guard something people work around rather than something they
keep. Absence means "unverified", mismatch means "wrong".

COST: 20.2 ms median to hash all 19 modules (599 KB), measured on this
machine. That is paid on every task spawn, against a ~1s PowerShell start
and the ~400ms module load the roadmap already measures - about 2%.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="runs the PowerShell engine")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_ROOT, "src", "backend")
MANIFEST_NAME = "MANIFEST.sha256"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture
def engine(tmp_path):
    """A throwaway copy of the engine, so a test can tamper with it."""
    root = tmp_path / "backend"
    shutil.copytree(_BACKEND, str(root))
    shutil.copy2(os.path.join(_ROOT, "VERSION"), str(tmp_path / "VERSION"))
    return root


def _write_manifest(engine_root) -> None:
    modules = engine_root / "modules"
    lines = []
    for name in sorted(os.listdir(str(modules))):
        if name.lower().endswith(".ps1"):
            lines.append(f"{_sha256(str(modules / name))}  {name}")
    (modules / MANIFEST_NAME).write_text("\n".join(lines) + "\n",
                                         encoding="utf-8")


def _run(engine_root, task: str = "GetTweakState"):
    """Run one read-only task and return (returncode, combined output)."""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass",
         "-File", str(engine_root / "core.ps1"), "-Task", task],
        capture_output=True, text=True, timeout=180,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result.returncode, (result.stdout or "") + (result.stderr or "")


class TestAVerifiedEngineRuns:
    def test_a_matching_manifest_does_not_get_in_the_way(self, engine):
        """The false-positive case, and the one that matters most: a
        guard that blocks a legitimate build is worse than no guard,
        because it gets removed."""
        _write_manifest(engine)
        code, output = _run(engine)
        assert "##PULSE##SUCCESS|" in output, (
            f"a correctly verified engine refused to run:\n{output[:600]}")

    def test_a_checkout_without_a_manifest_still_runs(self, engine):
        """Developer mode. The manifest is a build artifact; a source tree
        has none, and refusing there would make this a guard people work
        around instead of keep."""
        manifest = engine / "modules" / MANIFEST_NAME
        assert not manifest.exists()
        code, output = _run(engine)
        assert "##PULSE##SUCCESS|" in output, (
            f"an unmanifested checkout refused to run:\n{output[:600]}")


class TestItFailsClosed:
    def test_a_modified_module_is_refused(self, engine):
        _write_manifest(engine)
        target = engine / "modules" / "09-SystemInfo.ps1"
        target.write_text(target.read_text(encoding="utf-8-sig")
                          + "\n# appended after the manifest was written\n",
                          encoding="utf-8")

        code, output = _run(engine)
        assert "##PULSE##ERROR|" in output, (
            f"a modified module was loaded anyway:\n{output[:600]}")
        assert "09-SystemInfo.ps1" in output, (
            "the refusal does not name the file that failed, which is the "
            "only thing that makes it actionable")

    def test_an_added_module_is_refused(self, engine):
        """THE ACTUAL ATTACK. Verifying only the files the manifest lists
        would let this through completely - no listed file changed."""
        _write_manifest(engine)
        (engine / "modules" / "99-Injected.ps1").write_text(
            "Write-Output 'this should never execute'\n", encoding="utf-8")

        code, output = _run(engine)
        assert "##PULSE##ERROR|" in output, (
            f"an unlisted module was dot-sourced into the elevated "
            f"engine:\n{output[:600]}")
        assert "99-Injected.ps1" in output
        assert "this should never execute" not in output, (
            "the injected module RAN before the check refused it — the "
            "verification happens too late to matter")

    def test_a_missing_module_is_refused(self, engine):
        """Not an attack, but equally unsafe: half an engine."""
        _write_manifest(engine)
        os.remove(str(engine / "modules" / "09-SystemInfo.ps1"))

        code, output = _run(engine)
        assert "##PULSE##ERROR|" in output, (
            f"a partial install ran anyway:\n{output[:600]}")
        assert "09-SystemInfo.ps1" in output

    def test_a_corrupt_manifest_is_refused_rather_than_ignored(self, engine):
        """A manifest that cannot be parsed must not silently degrade to
        the permissive path — that would turn the guard off for anyone who
        could damage one line of it."""
        _write_manifest(engine)
        (engine / "modules" / MANIFEST_NAME).write_text(
            "this is not a manifest\n", encoding="utf-8")

        code, output = _run(engine)
        assert "##PULSE##ERROR|" in output, (
            f"a corrupt manifest was treated as no manifest:\n{output[:600]}")


class TestTheBuildProducesIt:
    def test_the_build_script_writes_a_manifest(self):
        with open(os.path.join(_ROOT, "tools", "build_release.ps1"),
                  encoding="utf-8-sig") as handle:
            source = handle.read()
        assert MANIFEST_NAME in source, (
            "build_release.ps1 does not generate the module manifest, so "
            "every shipped build would run unverified")

    def test_it_is_written_before_pyinstaller_bundles_the_tree(self):
        """The manifest ships because it sits inside src/backend/modules,
        which main.spec already copies wholesale. That only works if it
        exists before PyInstaller runs."""
        with open(os.path.join(_ROOT, "tools", "build_release.ps1"),
                  encoding="utf-8-sig") as handle:
            source = handle.read()
        manifest_at = source.index(MANIFEST_NAME)
        pyinstaller_at = source.index("python -m PyInstaller")
        assert manifest_at < pyinstaller_at, (
            "the manifest is generated after the bundle is built, so the "
            "shipped copy would be stale or absent")

    def test_the_engine_verifies_before_it_dot_sources(self):
        """Order is the whole guarantee: a check that runs after the loop
        has already executed the injected file."""
        with open(os.path.join(_BACKEND, "core.ps1"),
                  encoding="utf-8-sig") as handle:
            source = handle.read()
        verify_at = source.index(MANIFEST_NAME)
        loader = re.search(r"foreach\s*\(\s*\$ModuleFile\s+in\s+\$ModuleFiles",
                           source)
        assert loader, "the module loader loop was renamed"
        assert verify_at < loader.start(), (
            "modules are dot-sourced before the manifest is checked")

    def test_the_manifest_is_not_committed(self):
        """It is a build artifact. Committing it would make every source
        edit a manifest mismatch, and the first fix anyone reached for
        would be to delete the check."""
        with open(os.path.join(_ROOT, ".gitignore"), encoding="utf-8") as fh:
            assert MANIFEST_NAME in fh.read(), (
                f"{MANIFEST_NAME} is not gitignored")
