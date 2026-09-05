"""
The self-updater (v10.3).

This module downloads an executable and launches it on a machine where
Pulse can elevate, so its rules are security rules and they are tested as
such. NOTHING HERE TOUCHES THE NETWORK: every response is a fixture, which
is what lets the failure paths — rate limits, tampering, truncation,
malformed JSON — be exercised at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

from utils import updater, version


# ============================================================
#  FIXTURES
# ============================================================
def _release(tag="v10.4.0", *, assets=True, sums=True, prerelease=False,
             body="Fixed things.", size=1024, draft=False):
    payload = {
        "tag_name": tag,
        "body": body,
        "prerelease": prerelease,
        "draft": draft,
        "published_at": "2026-08-01T10:00:00Z",
        "assets": [],
    }
    stem = tag.lstrip("vV")
    if assets:
        payload["assets"].append({
            "name": f"PULSE_Setup_v{stem}.exe",
            "size": size,
            "browser_download_url":
                f"https://example.invalid/PULSE_Setup_v{stem}.exe",
        })
    if sums:
        payload["assets"].append({
            "name": "SHA256SUMS",
            "size": 96,
            "browser_download_url": "https://example.invalid/SHA256SUMS",
        })
    return payload


@pytest.fixture
def net(monkeypatch):
    """Replaces every HTTP GET with a lookup table."""
    table: dict[str, bytes | None] = {}

    def fake_get(url, timeout=None):
        return table.get(url, table.get("*"))

    monkeypatch.setattr(updater, "_get", fake_get)
    return table


def _json(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


# ============================================================
#  CHECK — the happy path and every way it must stay quiet
# ============================================================
def test_a_newer_release_is_offered(net):
    net["*"] = _json(_release("v10.4.0"))
    found = updater.check(current="10.3.0", channel="stable")
    assert found is not None
    assert found.version == "10.4.0"
    assert found.tag == "v10.4.0"
    assert found.asset_name == "PULSE_Setup_v10.4.0.exe"
    assert found.sums_url


@pytest.mark.parametrize("tag", ["v10.3.0", "10.3", "v10.2.9", "v9.9.9"])
def test_the_running_build_and_older_ones_are_not_offered(net, tag):
    """Re-offering the current build is an update loop the user cannot
    escape by updating; offering an older one is a downgrade."""
    net["*"] = _json(_release(tag))
    assert updater.check(current="10.3.0", channel="stable") is None


@pytest.mark.parametrize("body", [
    b"", b"not json at all", b"{", b'{"tag_name": }', b"null", b"[]",
])
def test_malformed_payloads_are_silent(net, body):
    net["*"] = body
    assert updater.check(current="10.3.0", channel="stable") is None


def test_a_network_failure_is_silent(net):
    """Offline, DNS failure, timeout, a captive portal, HTTP 403 from the
    unauthenticated rate limit — _get returns None for all of them, and
    Pulse routinely runs on machines in exactly those states."""
    net["*"] = None
    assert updater.check(current="10.3.0", channel="stable") is None


def test_a_release_without_an_installer_is_not_offered(net):
    """A release with notes but no asset is mid-publication, or was built
    without the release script. Offering it sends the user to a download
    that does not exist."""
    net["*"] = _json(_release("v10.4.0", assets=False))
    assert updater.check(current="10.3.0", channel="stable") is None


def test_a_draft_release_is_not_offered(net):
    net["*"] = _json([_release("v10.5.0", draft=True), _release("v10.4.0")])
    found = updater.check(current="10.3.0", channel="beta")
    assert found is not None and found.version == "10.4.0"


def test_an_absurd_asset_size_is_rejected(net):
    net["*"] = _json(_release("v10.4.0", size=updater._MAX_ASSET_BYTES + 1))
    assert updater.check(current="10.3.0", channel="stable") is None
    net["*"] = _json(_release("v10.4.0", size=0))
    assert updater.check(current="10.3.0", channel="stable") is None


# ============================================================
#  CHANNELS
# ============================================================
def test_a_stable_build_is_never_offered_a_prerelease(net):
    net["*"] = _json([_release("v11.0.0", prerelease=True),
                      _release("v10.4.0")])
    found = updater.check(current="10.3.0", channel="stable")
    assert found is not None
    assert found.version == "10.4.0", "a stable build was offered a prerelease"


def test_a_beta_build_may_take_a_prerelease(net):
    net["*"] = _json([_release("v11.0.0", prerelease=True),
                      _release("v10.4.0")])
    found = updater.check(current="10.3.0", channel="beta")
    assert found is not None and found.version == "11.0.0"


def test_the_newest_wins_regardless_of_list_order(net):
    """GitHub orders by creation date, which is not version order once a
    patch for an older line is published after a newer release."""
    net["*"] = _json([_release("v10.4.0"), _release("v10.10.0"),
                      _release("v10.9.0")])
    found = updater.check(current="10.3.0", channel="beta")
    assert found is not None and found.version == "10.10.0"


# ============================================================
#  RELEASE NOTES — attacker-influenced content
# ============================================================
def test_notes_are_reduced_to_plain_text():
    """Whoever publishes a release chooses this string. Rendered as rich
    text it could load remote images (a read receipt) and follow links."""
    notes = updater._clean_notes(
        "## Heading\n"
        "**bold** and *italic* and `code`\n"
        "![img](https://tracker.invalid/pixel.png)\n"
        "[click me](https://evil.invalid)\n"
        "<img src='https://tracker.invalid/x.png'>\n"
        "<script>alert(1)</script>")
    assert "##" not in notes
    assert "**" not in notes
    assert "<img" not in notes and "<script" not in notes
    assert "tracker.invalid" not in notes
    assert "evil.invalid" not in notes
    assert "Heading" in notes and "bold" in notes and "click me" in notes


def test_notes_are_bounded():
    """An unbounded body is a dialog that cannot be closed and, at the
    extreme, a memory problem."""
    notes = updater._clean_notes("A" * 50_000)
    assert len(notes) < 9_000


# ============================================================
#  VERIFY — the rule the whole module exists for
# ============================================================
def _make_installer(tmp_path, content=b"installer bytes"):
    path = tmp_path / "PULSE_Setup_v10.4.0.exe"
    path.write_bytes(content)
    return str(path), hashlib.sha256(content).hexdigest()


def _update(sums_url="https://example.invalid/SHA256SUMS"):
    return updater.Update(
        version="10.4.0", tag="v10.4.0", notes="", size=15,
        url="https://example.invalid/PULSE_Setup_v10.4.0.exe",
        sums_url=sums_url, asset_name="PULSE_Setup_v10.4.0.exe",
        prerelease=False)


def test_a_matching_digest_verifies(tmp_path, net):
    path, digest = _make_installer(tmp_path)
    net["https://example.invalid/SHA256SUMS"] = \
        f"{digest}  PULSE_Setup_v10.4.0.exe\n".encode()
    updater.verify(path, _update())        # must not raise


def test_a_tampered_download_is_refused(tmp_path, net):
    """The core promise: an executable this tool would launch on a machine
    where it can elevate is never run unless it is byte-for-byte the
    published artifact."""
    path, _ = _make_installer(tmp_path, b"malicious payload")
    net["https://example.invalid/SHA256SUMS"] = \
        (f"{'0' * 64}  PULSE_Setup_v10.4.0.exe\n").encode()
    with pytest.raises(updater.UpdateError, match="does not match"):
        updater.verify(path, _update())


def test_a_release_without_checksums_is_refused(tmp_path, net):
    """Not 'verify what we can' — an unverifiable executable is refused."""
    path, _ = _make_installer(tmp_path)
    with pytest.raises(updater.UpdateError, match="no SHA256SUMS"):
        updater.verify(path, _update(sums_url=None))


def test_an_unreachable_checksum_file_is_refused(tmp_path, net):
    path, _ = _make_installer(tmp_path)
    net["https://example.invalid/SHA256SUMS"] = None
    with pytest.raises(updater.UpdateError, match="could not be downloaded"):
        updater.verify(path, _update())


def test_checksums_that_omit_our_file_are_refused(tmp_path, net):
    path, _ = _make_installer(tmp_path)
    net["https://example.invalid/SHA256SUMS"] = \
        f"{'a' * 64}  something-else.exe\n".encode()
    with pytest.raises(updater.UpdateError, match="does not list"):
        updater.verify(path, _update())


def test_sums_parsing_handles_the_real_format():
    parsed = updater.parse_sums(
        "abc123  file-one.exe\n"
        f"{'b' * 64} *binary-mode.exe\n"
        f"{'c' * 64}  dist/nested/path.exe\n"
        "garbage line\n"
        "\n"
        f"{'D' * 64}  UPPERCASE.EXE\n")
    assert parsed[f"binary-mode.exe"] == "b" * 64
    assert parsed["path.exe"] == "c" * 64          # basename only
    assert parsed["UPPERCASE.EXE"] == "d" * 64     # digest lowercased
    assert "file-one.exe" not in parsed            # 6 chars is not a digest


# ============================================================
#  APPLY — the guards around handing over
# ============================================================
def test_a_source_checkout_is_never_updated():
    """Running Setup over a developer's working tree would install a
    release build beside it and do nothing to the code actually running."""
    assert not getattr(__import__("sys"), "frozen", False)
    ok, why = updater.can_apply()
    assert ok is False
    assert "source" in why.lower()


def test_apply_refuses_from_source(tmp_path):
    path = tmp_path / "PULSE_Setup_v10.4.0.exe"
    path.write_bytes(b"x")
    with pytest.raises(updater.UpdateError, match="source"):
        updater.apply(str(path))


def test_apply_refuses_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "can_apply", lambda: (True, ""))
    with pytest.raises(updater.UpdateError, match="no longer on disk"):
        updater.apply(str(tmp_path / "gone.exe"))


# ============================================================
#  HOUSEKEEPING
# ============================================================
def test_downloads_land_outside_the_install_directory(monkeypatch, tmp_path):
    """Program Files is not writable without elevation — which is the point
    of installing there — so downloads go to %LOCALAPPDATA%."""
    monkeypatch.setattr(updater.resources, "local_appdata", lambda: str(tmp_path))
    path = updater.download_dir()
    assert os.path.isdir(path)
    assert "PULSE" in path and "updates" in path


def test_stale_downloads_are_pruned(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.resources, "local_appdata", lambda: str(tmp_path))
    folder = updater.download_dir()
    old = os.path.join(folder, "PULSE_Setup_v10.1.0.exe")
    new = os.path.join(folder, "PULSE_Setup_v10.4.0.exe")
    for path in (old, new):
        with open(path, "wb") as handle:
            handle.write(b"x")
    os.utime(old, (0, 0))                       # ancient
    assert updater.prune(keep=new) == 1
    assert not os.path.exists(old) and os.path.exists(new)


def test_the_kept_file_survives_even_when_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.resources, "local_appdata", lambda: str(tmp_path))
    folder = updater.download_dir()
    path = os.path.join(folder, "PULSE_Setup_v10.4.0.exe")
    with open(path, "wb") as handle:
        handle.write(b"x")
    os.utime(path, (0, 0))
    assert updater.prune(keep=path) == 0
    assert os.path.exists(path)


# ============================================================
#  WIRING
# ============================================================
def test_the_repo_matches_the_git_remote():
    """A typo here points the updater at somebody else's releases."""
    assert updater.REPO == "Humam-Taibeh/Pulse"
    assert updater.REPO in updater._API_LATEST
    assert updater._API_LATEST.startswith("https://api.github.com/")


def test_the_asset_pattern_matches_what_the_build_script_emits():
    """tools/build_release.ps1 names the installer from VERSION; if these
    two ever disagree, every release silently has 'no installer'."""
    assert updater._ASSET_RE.match(f"PULSE_Setup_v{version.VERSION}.exe")
    assert not updater._ASSET_RE.match("PULSE_Setup.exe")
    assert not updater._ASSET_RE.match("PULSE_Setup_v10.3.exe")
    assert not updater._ASSET_RE.match("evil.exe")


def test_the_bare_release_asset_name_is_also_recognised():
    """The v10.3 beta shipped as `Pulse.exe`, which the versioned pattern
    does not match. That made _find_assets return no installer, so check()
    returned None and the updater silently reported 'up to date' for a
    release that existed."""
    assert updater._ASSET_FALLBACK_RE.match("Pulse.exe")
    assert updater._ASSET_FALLBACK_RE.match("PULSE.EXE")
    assert not updater._ASSET_FALLBACK_RE.match("evil.exe")
    assert not updater._ASSET_FALLBACK_RE.match("Pulse.exe.bak")
    assert not updater._ASSET_FALLBACK_RE.match("NotPulse.exe")


def test_the_versioned_installer_wins_over_the_bare_name():
    """Order-independently: the versioned name survives leaving the
    download folder, the bare one does not."""
    bare = {"name": "Pulse.exe", "browser_download_url": "https://x/i", "size": 1}
    versioned = {"name": "PULSE_Setup_v10.4.0.exe",
                 "browser_download_url": "https://x/v", "size": 1}

    for assets in ([bare, versioned], [versioned, bare]):
        installer, _ = updater._find_assets({"assets": assets})
        assert installer is versioned

    installer, _ = updater._find_assets({"assets": [bare]})
    assert installer is bare


def test_requests_are_identified_and_versioned():
    """GitHub 403s an anonymous request with no User-Agent."""
    assert "PULSE" in updater._USER_AGENT
    assert version.VERSION in updater._USER_AGENT


# ============================================================
#  APPLICATION CONTROL (Inno Setup Error 4551)
# ============================================================
# "Unable to execute file in the temporary directory ... Error 4551: An
# Application Control policy has blocked this file" names the helper
# SetupLdr unpacks into is-XXXXXXXX.tmp and runs, not the setup executable
# the user launched. Two mitigations, and the tests below are careful to
# claim only what each one does.
class TestTheInstallerIsHandedOverCleanly:

    @pytest.fixture
    def staged(self, monkeypatch, tmp_path):
        """A verified installer sitting where download() would leave it."""
        monkeypatch.setattr(updater.resources, "local_appdata",
                            lambda: str(tmp_path))
        monkeypatch.setattr(updater, "can_apply", lambda: (True, ""))
        path = os.path.join(updater.download_dir(),
                            "PULSE_Setup_v10.10.0.exe")
        with open(path, "wb") as handle:
            handle.write(b"MZ")
        return path

    @pytest.fixture
    def launched(self, monkeypatch):
        """Capture the Popen call instead of starting an installer."""
        seen = {}

        def fake_popen(args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            return object()

        monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
        return seen

    @pytest.mark.skipif(sys.platform != "win32",
                        reason="NTFS alternate data streams")
    def test_the_mark_of_the_web_is_gone_before_setup_runs(
            self, staged, launched):
        """An Application Control policy can refuse a file carrying a
        Zone.Identifier, and apply() is reached from the browser download
        as well as from download() - only one of which sets one."""
        stream = staged + ":Zone.Identifier"
        with open(stream, "w") as handle:
            handle.write("[ZoneTransfer]\nZoneId=3\n")
        updater.apply(staged)
        with pytest.raises(OSError):
            open(stream).read()
        assert launched["args"][0] == staged, "setup was not launched"

    def test_setup_unpacks_into_our_own_directory_not_shared_temp(
            self, staged, launched):
        r"""SetupLdr chooses where to unpack with GetTempPath, which reads
        TMP then TEMP. Both are pointed at a directory this application
        owns, so the extraction leaves the world-writable %TEMP% that
        path-based AppLocker and WDAC rules most often deny.

        Measured against a real Inno installer before this was written:
        an inherited environment unpacked to %TEMP%\is-EPUUEV6AK4.tmp, a
        redirected one to <staging>\is-TB01777L46.tmp.
        """
        updater.apply(staged)
        env = launched["kwargs"]["env"]
        expected = updater.installer_temp_dir()
        assert env["TMP"] == expected and env["TEMP"] == expected
        assert os.path.normcase(expected).startswith(
            os.path.normcase(updater.download_dir()))
        assert os.path.isdir(expected), "the staging directory was not created"

    def test_the_installer_still_gets_a_whole_environment(
            self, staged, launched, monkeypatch):
        """The redirect must be an OVERRIDE, not a replacement. Handing
        Setup a two-variable environment would strip PATH, SystemRoot and
        the rest, and it would fail in ways that look nothing like this."""
        monkeypatch.setenv("PULSE_ENV_CANARY", "present")
        updater.apply(staged)
        env = launched["kwargs"]["env"]
        assert env.get("PULSE_ENV_CANARY") == "present"
        assert len(env) > 3

    def test_a_file_with_no_stream_is_left_alone(self, tmp_path):
        """The common case, and it must not raise: nothing this updater
        downloads carries a Mark of the Web in the first place."""
        path = os.path.join(str(tmp_path), "plain.exe")
        with open(path, "wb") as handle:
            handle.write(b"MZ")
        assert updater.strip_mark_of_the_web(path) is False
        with open(path, "rb") as handle:
            assert handle.read() == b"MZ"


def test_blocked_setup_leftovers_are_pruned(monkeypatch, tmp_path):
    """Inno removes its own is-*.tmp on a clean exit. A REFUSED setup is
    exactly the case where it does not - so without this, the directory
    added for 4551 would accumulate one carcass per blocked update and
    quietly fill the disk of the machine that already could not update."""
    monkeypatch.setattr(updater.resources, "local_appdata", lambda: str(tmp_path))
    staging = updater.installer_temp_dir()
    stale = os.path.join(staging, "is-DEADBEEF.tmp")
    fresh = os.path.join(staging, "is-CAFEBABE.tmp")
    for path in (stale, fresh):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "helper.exe"), "wb") as handle:
            handle.write(b"MZ")
    os.utime(stale, (0, 0))
    assert updater.prune() == 1
    assert not os.path.exists(stale)
    assert os.path.isdir(fresh), "a live unpack directory was deleted"
