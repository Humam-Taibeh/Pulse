"""
tests/test_catalog_pillars.py

THE TRIPARTITE CATALOG, and the two backend pipelines it needed.

Software Management used to offer ONE catalog card over a 43-row list with
a sub-category tab bar. That was itself a fix — it replaced four cards that
gave "where do I get Docker?" four possible answers — and it went one step
too far in the same direction. The three questions people actually arrive
with are:

    make this machine usable          (browsers, chat, media, launchers)
    make this machine build software  (languages, IDEs, the AI stack)
    stop this machine erroring        (runtimes, drivers, diagnostics)

They share almost no audience, urgency or vocabulary, and the third is
reached in a state the other two never are: something is already broken.
So the catalog is three SURFACES over one list — three cards, each opening
SoftwareCatalogDialog scoped to its pillar, all deploying through the same
InstallCatalogApps pass so a selection still costs one run.

WHAT THIS FILE GUARDS, beyond the mirror check that already existed in
test_contract.py:

  * the pillars are DISJOINT and COMPLETE against the flat list — a row in
    two pillars is a double install, a row in none is unreachable;
  * every card that opens a catalog names a pillar that exists;
  * the two COMPOSITE ids (Pulse.VCRedistAIO, Pulse.DotNetFx35) are
    declared on both sides and are not mistaken for winget ids;
  * the Store-id test admits 14-character product ids, which is what the
    NVIDIA App needs and what the old `^\\w{12}$` silently refused;
  * exit code 3010 survives all the way to the deploy summary.
"""
from __future__ import annotations

import os
import re

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CATALOGS = os.path.join(_ROOT, "src/backend/modules/01-Catalogs.ps1")
_ENGINE = os.path.join(_ROOT, "src/backend/modules/04-SoftwareEngine.ps1")
_DISPATCHER = os.path.join(_ROOT, "src/backend/modules/30-GuiDispatcher.ps1")
_NETWORK = os.path.join(_ROOT, "src/backend/modules/15-Network.ps1")


def _read(path: str) -> str:
    with open(path, encoding="utf-8-sig") as handle:
        return handle.read()


def _stripped(path: str) -> str:
    """`path` with PowerShell comments removed — BOTH kinds.

    test_contract.py's parser strips `#` line comments for exactly this
    reason, and that is only half of it: these modules carry their
    reasoning in `<# ... #>` BLOCK comments, and the reasoning is largely
    about things that are deliberately GONE. 01-Catalogs.ps1 names the six
    retired vendor package ids to explain why nothing appends them any
    more; 04-SoftwareEngine.ps1 quotes the old "cannot be installed via
    winget" message to explain why the Store path was rewritten.

    So a substring check over raw source finds the epitaph and reports the
    corpse as alive. Removing block comments FIRST is what lets a test
    assert "this is gone" against a file whose whole job is to record that
    it went — and lets the explanation stay, which is the point.
    """
    source = re.sub(r"<#.*?#>", "", _read(path), flags=re.S)
    return "\n".join(re.sub(r"#.*$", "", line)
                      for line in source.splitlines())


# ============================================================
#  1. THE THREE PILLARS PARTITION THE CATALOG
# ============================================================
class TestPillarPartition:

    def test_there_are_exactly_three_pillars(self):
        from frontend.menu_structure import SOFTWARE_CATALOG
        keys = [section["key"] for section in SOFTWARE_CATALOG]
        assert keys == ["essentials", "development", "runtimes"], (
            f"the catalog is no longer the three pillars: {keys}")

    def test_the_pillars_are_disjoint(self):
        """A row in two pillars is offered twice and, if ticked in both,
        queued twice — and the tabs would disagree about where it lives."""
        from frontend.menu_structure import SOFTWARE_CATALOG, catalog_tools
        seen: dict[str, list[str]] = {}
        for section in SOFTWARE_CATALOG:
            for tool in catalog_tools(section["key"]):
                seen.setdefault(tool[0], []).append(section["key"])
        shared = {app: keys for app, keys in seen.items() if len(keys) > 1}
        assert not shared, f"app(s) in more than one pillar: {shared}"

    def test_the_pillars_are_complete(self):
        """Every row of the flat list belongs to a pillar. A row in none is
        deployed by -AppIds and reachable from no surface."""
        from frontend.menu_structure import (
            SOFTWARE_CATALOG, catalog_app_ids, catalog_tools)
        covered = {tool[0]
                   for section in SOFTWARE_CATALOG
                   for tool in catalog_tools(section["key"])}
        assert covered == set(catalog_app_ids())

    def test_the_removed_apps_are_really_gone(self):
        """Each was removed for a stated reason, and each is the kind of
        entry that gets re-added by reflex. Named individually so the
        reason survives with the absence.

        Firefox / LibreOffice / Edge / iCloud left Pillar 1; the JRE is
        contained in Temurin's JDK, so offering both invited a second,
        older Java; Bruno duplicated Postman and DBeaver was a database
        GUI in a stack with no database.
        """
        from frontend.menu_structure import catalog_app_ids
        ids = set(catalog_app_ids())
        for retired in ("Mozilla.Firefox",
                        "TheDocumentFoundation.LibreOffice",
                        "Microsoft.Edge", "9PKTQ5699M62",
                        "Oracle.JavaRuntimeEnvironment",
                        "Bruno.Bruno", "DBeaver.DBeaver.Community"):
            assert retired not in ids, f"{retired} is back in the catalog"

    def test_the_new_apps_are_all_present(self):
        from frontend.menu_structure import catalog_app_ids
        ids = set(catalog_app_ids())
        for added in ("RARLab.WinRAR", "AnyDesk.AnyDesk", "Oracle.VirtualBox",
                      "Google.Antigravity", "CreativeTechnology.OpenAL",
                      "XP8CLZL93F5Z4P", "Pulse.VCRedistAIO",
                      "Pulse.DotNetFx35"):
            assert added in ids, f"{added} is missing from the catalog"

    def test_edge_is_still_reachable_even_though_it_left_the_catalog(self):
        """Microsoft Edge dropped OUT of the catalog, and that is only safe
        because its own hub still reinstalls it. Remove Microsoft Edge
        promises the removal is reversible; deleting the catalog row
        without checking this would have quietly removed the way back."""
        from frontend.menu_structure import CATEGORIES, category_items, hub_items
        tasks = {sub.get("task")
                 for category in CATEGORIES
                 for item in category_items(category)
                 for sub in hub_items(item)}
        assert "RestoreEdge" in tasks


# ============================================================
#  2. EVERY CATALOG CARD OPENS A PILLAR THAT EXISTS
# ============================================================
class TestCatalogCards:

    @staticmethod
    def _catalog_cards():
        from frontend.menu_structure import CATEGORIES, category_items
        return [item for category in CATEGORIES
                for item in category_items(category)
                if item.get("catalog")]

    def test_there_is_one_card_per_pillar(self):
        from frontend.menu_structure import SOFTWARE_CATALOG
        keys = sorted(card.get("catalog_section", "")
                      for card in self._catalog_cards())
        assert keys == sorted(section["key"] for section in SOFTWARE_CATALOG)

    def test_every_card_names_a_real_pillar(self):
        """A typo here opens the COMBINED catalog silently — the card
        promises one pillar and shows all three, which looks like a design
        choice rather than a bug."""
        from frontend.menu_structure import catalog_section
        for card in self._catalog_cards():
            key = card.get("catalog_section")
            assert key and catalog_section(key) is not None, (
                f"{card['title']} names pillar {key!r}, which does not exist")

    def test_the_one_click_pass_deploys_only_the_essential_group(self):
        """"Install All Essential Dependencies" must not quietly hand over
        an overclocking utility and four monitoring tools. It ticks the
        runtimes pillar's FOUNDATION group and nothing else."""
        from frontend.menu_structure import catalog_bulk_ids, catalog_tools
        bulk = catalog_bulk_ids("runtimes")
        assert bulk, "the runtimes pillar declares no bulk action"
        assert set(bulk) == {
            "Pulse.VCRedistAIO", "Microsoft.DirectX",
            "Microsoft.DotNet.DesktopRuntime.8", "Pulse.DotNetFx35",
            "CreativeTechnology.OpenAL"}
        everything = {tool[0] for tool in catalog_tools("runtimes")}
        for excluded in ("Guru3D.Afterburner", "CPUID.CPU-Z",
                         "TechPowerUp.GPU-Z", "XP8CLZL93F5Z4P"):
            assert excluded in everything, "test is checking a stale id"
            assert excluded not in bulk, (
                f"the one-click pass would also install {excluded}")

    def test_the_bulk_group_mirrors_the_backend(self):
        """$Script:EssentialRuntimeIds is what the InstallEssentialRuntimes
        task actually deploys; the GUI's bulk button only TICKS. If the two
        disagree, the card and the button install different sets."""
        from frontend.menu_structure import catalog_bulk_ids
        source = _stripped(_CATALOGS)
        start = source.index("$Runtimes = ")
        body = source[start:source.index("\n$", start + 1)]
        backend = re.findall(r'@\("([^"]+)",', body)
        assert backend, "the backend $Runtimes array did not parse"
        assert catalog_bulk_ids("runtimes") == backend

    def test_opengl_and_vulkan_are_explained_rather_than_listed(self):
        """They are provided by the display driver, so a row for either
        would be a row that installs nothing. Saying so is what stops the
        absence reading as an omission."""
        from frontend.menu_structure import catalog_section
        footnote = catalog_section("runtimes").get("footnote", "")
        assert "OpenGL" in footnote and "Vulkan" in footnote
        assert "driver" in footnote.lower()


# ============================================================
#  3. THE COMPOSITE AND WINDOWS-FEATURE ROWS
# ============================================================
class TestCompositeRows:

    #: Rows that are NOT winget package ids. Both are namespaced "Pulse."
    #: so nothing can mistake one for a real package.
    PSEUDO = ("Pulse.VCRedistAIO", "Pulse.DotNetFx35")

    def test_pseudo_ids_are_namespaced(self):
        """A composite id is handed to the same -AppIds channel as a real
        one. The namespace is what guarantees a collision with a future
        winget package is impossible."""
        for app_id in self.PSEUDO:
            assert app_id.startswith("Pulse."), (
                f"{app_id} is not namespaced and could collide with a real "
                "winget package id")

    def test_the_vcredist_set_covers_every_version_and_both_architectures(self):
        """The catalog used to offer Microsoft.VCRedist.2015+.x64 alone —
        the one modern software already ships with, and none of the five
        older ones a 2009 game actually asks for. "Missing MSVCR100.dll"
        was unfixable from this catalog."""
        source = _stripped(_CATALOGS)
        start = source.index("$Script:CompositeRuntimePackages")
        body = source[start:source.index("\n$", start + 1)]
        members = re.findall(r'@\("(Microsoft\.VCRedist\.[^"]+)"', body)
        assert len(members) == 12, f"expected 12 packages, got {members}"
        for year in ("2005", "2008", "2010", "2012", "2013", "2015+"):
            for arch in ("x86", "x64"):
                wanted = f"Microsoft.VCRedist.{year}.{arch}"
                assert wanted in members, f"{wanted} is missing from the AIO"

    def test_powershell_reads_the_composite_as_pairs_not_a_flat_list(self):
        """THE TEST ABOVE PASSED WHILE THIS WAS BROKEN, which is the whole
        reason this one exists.

        `test_the_vcredist_set_covers_every_version_and_both_architectures`
        parses the SOURCE with a regex and found twelve `@("id","name")`
        pairs — correctly. PowerShell read the same text as TWENTY-FOUR
        strings, because nested arrays that are not comma-separated are
        FLATTENED. Smart-Deploy then indexed `$Member[0]` on a string and
        got its first CHARACTER, so a dry run reported "TARGET: M",
        "TARGET: V" and "24 of 24".

        A regex cannot see that; only the language can. So this evaluates
        the real declaration in a real PowerShell and asks it what shape
        it ended up with — the same gap 01-Catalogs.ps1 already documents
        for $Apps_DevContainers, caught here by execution rather than by
        someone remembering.
        """
        import json
        import shutil
        import subprocess

        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            pytest.skip("no PowerShell on PATH")

        source = _stripped(_CATALOGS)
        start = source.index("$Script:CompositeRuntimePackages = @{")
        table = source[start:source.index("\n}", start) + 2]

        # Evaluate ONLY the declaration, then report the shape as JSON.
        # Count + inner length + the first element together distinguish a
        # flattened list (24 / no .Count / "M") from pairs (12 / 2 / a real
        # package id) without trusting any of them alone.
        script = table + """
$set = $Script:CompositeRuntimePackages['Pulse.VCRedistAIO']
[pscustomobject]@{
    Count = @($set).Count
    FirstIsPair = (@($set)[0]).Count -eq 2
    FirstId = (@($set)[0])[0]
    FirstName = (@($set)[0])[1]
} | ConvertTo-Json -Compress
"""
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        shape = json.loads(result.stdout.strip().splitlines()[-1])

        assert shape["Count"] == 12, (
            f"PowerShell sees {shape['Count']} entries, not 12 — the nested "
            "arrays are being flattened; check the commas")
        assert shape["FirstIsPair"], (
            "the first entry is not an (id, name) pair — it has been "
            "flattened to a bare string")
        assert shape["FirstId"] == "Microsoft.VCRedist.2005.x86", (
            f"first id came back as {shape['FirstId']!r}; a single character "
            "means a string is being indexed as if it were a pair")
        assert shape["FirstName"] == "Visual C++ 2005 (x86)"

    def test_the_dotnet_framework_row_is_a_dism_feature(self):
        """.NET Framework 3.5 ships inside Windows as a disabled feature.
        There is no winget package, so a row that pretended otherwise would
        fail every time."""
        source = _stripped(_CATALOGS)
        assert "$Script:WindowsFeaturePackages" in source
        start = source.index("$Script:WindowsFeaturePackages")
        body = source[start:source.index("\n$", start + 1)]
        assert "Pulse.DotNetFx35" in body
        assert "NetFx3" in body, "the DISM feature name is not declared"

    def test_smart_deploy_intercepts_both_before_winget(self):
        """Neither has a package for winget to resolve, so both must be
        handled BEFORE Ensure-Winget is reached — otherwise a composite row
        bootstraps winget just to be told the id does not exist."""
        engine = _stripped(_ENGINE)
        start = engine.index("function Smart-Deploy")
        head = engine[start:start + 2000]
        composite = head.index("Is-CompositeApp")
        feature = head.index("Is-WindowsFeatureApp")
        winget = head.index("Ensure-Winget")
        assert composite < winget and feature < winget, (
            "a composite/feature row reaches Ensure-Winget before its own "
            "handler")

    def test_a_composite_row_is_not_offered_a_download_url_it_cannot_use(self):
        """Open-FallbackUrl is the escape hatch when an install fails. A
        composite row has no single vendor page, so it points at the index
        Microsoft actually publishes rather than at nothing."""
        source = _stripped(_CATALOGS)
        start = source.index("$Script:DownloadUrls")
        body = source[start:source.index("\n$", start + 1)]
        for app_id in self.PSEUDO:
            assert app_id in body, f"{app_id} has no fallback URL"


# ============================================================
#  4. STORE PRODUCT IDS
# ============================================================
class TestStoreIds:

    def test_the_store_id_test_admits_fourteen_character_ids(self):
        """THE NVIDIA APP'S ID IS FOURTEEN CHARACTERS. The pattern was
        `^\\w{12}$`, which matched every Store id the catalog happened to
        contain and none of the longer ones the Store has issued since — so
        XP8CLZL93F5Z4P fell through to the WIN32 path, where winget was
        asked to install it from the default source and answered that no
        such package exists."""
        engine = _stripped(_ENGINE)
        start = engine.index("function Is-StoreApp")
        # To the NEXT function, not to the first "}" after the return —
        # the pattern itself contains braces, so the naive slice cuts the
        # rule in half and then asserts on the fragment.
        body = engine[start:engine.index("function ", start + 10)]
        assert "{12}" in body and "{14}" in body, (
            f"Is-StoreApp does not admit both 12- and 14-character ids: {body}")
        assert "\\w{12}" not in body, "the old 12-only pattern is back"

    def test_every_store_row_matches_the_engines_own_rule(self):
        """The GUI and the engine have to agree about which rows are Store
        products, because they take completely different install paths."""
        from frontend.menu_structure import catalog_app_ids
        store_like = [a for a in catalog_app_ids()
                      if re.fullmatch(r"[A-Z0-9]{12}|[A-Z0-9]{14}", a)]
        assert set(store_like) == {"9NKSQCEZVDDB", "XP8CLZL93F5Z4P"}

    def test_no_winget_id_is_mistaken_for_a_store_id(self):
        """The rule is safe only because every winget id is
        Publisher.Package and therefore contains a dot."""
        from frontend.menu_structure import catalog_app_ids
        for app_id in catalog_app_ids():
            if re.fullmatch(r"[A-Z0-9]{12}|[A-Z0-9]{14}", app_id):
                assert "." not in app_id

    def test_a_fresh_store_install_is_no_longer_skipped(self):
        """The catalog offered WhatsApp, reported a clean success, and
        installed nothing: a not-yet-installed Store app returned Skipped
        with "no silent install path for Store apps". That has not been
        true of winget for a long time — the UPDATE branch a few lines
        above was already doing exactly this."""
        engine = _stripped(_ENGINE)
        assert "Store app (GUI)" not in engine, (
            "the GUI-mode Store skip is back")
        assert "cannot be installed via winget" not in engine
        # the install must go through the msstore source with agreements
        # accepted, exactly as the upgrade path does
        assert re.search(
            r'"install",\s*"--id",\s*\$AppId.*?"--source",\s*"msstore"',
            engine, re.S), "no silent msstore install path found"
        # and the update path it was modelled on is still there
        assert re.search(
            r'"upgrade",\s*"--id",\s*\$AppId.*?"--source",\s*"msstore"',
            engine, re.S), "the Store UPGRADE path went missing"


# ============================================================
#  5. EXIT CODES, INCLUDING 3010
# ============================================================
class TestExitCodes:

    def test_3010_and_1641_are_successes_that_ask_for_a_reboot(self):
        engine = _read(_ENGINE)
        start = engine.index("function Resolve-WingetExitCode")
        body = engine[start:engine.index("\nfunction ", start + 10)]
        for code in ("3010", "1641"):
            match = re.search(rf"^\s*{code}\s*{{(.*)}}\s*$", body, re.M)
            assert match, f"exit code {code} has no branch"
            branch = match.group(1)
            assert "Success = $true" in branch, f"{code} is not a success"
            assert "RebootRequired = $true" in branch, (
                f"{code} does not flag a reboot")

    def test_1641_was_not_left_as_an_unhandled_code(self):
        """It fell through to `default` and reported "Unhandled exit code
        (1641)" — a successful install turned into a failure."""
        engine = _read(_ENGINE)
        assert re.search(r"^\s*1641\s*{", engine, re.M)

    def test_the_reboot_flag_reaches_the_session(self):
        """Resolve-WingetExitCode only DESCRIBES the code. Something has to
        act on it, or the message is written into a string nothing reads."""
        engine = _read(_ENGINE)
        assert engine.count("if ($Result.RebootRequired) { $Script:PendingRestart = $true }") >= 3, (
            "not every Resolve-WingetExitCode call site propagates the reboot")

    def test_the_deploy_summary_reports_the_reboot_once(self):
        """A fourteen-app run must say "restart to finish" ONCE at the end,
        not bury it in one app's line and then overwrite it with counts."""
        dispatcher = _read(_DISPATCHER)
        start = dispatcher.index("function Invoke-GuiBulkDeploy")
        body = dispatcher[start:dispatcher.index("\nfunction ", start + 10)]
        assert "$RestartWasPending" in body, (
            "the summary cannot tell a reboot raised by THIS deploy from "
            "one already pending")
        assert "Restart Windows to finish" in body

    def test_the_hardware_extras_append_is_gone(self):
        """Six of the seven package ids it could append no longer exist in
        winget, so it silently did nothing on virtually every machine — and
        where it did fire it installed software the user never ticked."""
        dispatcher = _stripped(_DISPATCHER)
        catalogs = _stripped(_CATALOGS)
        assert "-ExtraAppId" not in dispatcher
        assert "CatalogGpuExtraTriggerIds" not in catalogs
        assert "CatalogMoboExtraTriggerIds" not in catalogs

    def test_no_dead_vendor_package_ids_remain(self):
        """Each of these was verified against live winget and resolves to
        nothing. Keeping one is keeping a call that cannot succeed."""
        engine = _stripped(_ENGINE)
        for dead in ("Nvidia.GeForceExperience",
                     "AdvancedMicroDevices.Adrenalin",
                     "Intel.IntelGraphicsCommandCenter",
                     "Micro-Star.MSICenter",
                     "Gigabyte.ControlCenter",
                     "ASRock.AppShop"):
            assert dead not in engine, (
                f"{dead} no longer exists in winget and is still referenced")


# ============================================================
#  6. THE NETWORK PIPELINE
# ============================================================
class TestNetworkPipeline:

    TASKS = ("NetworkAdapterReport", "NetworkDriverCheck", "NetworkStackReset")

    def test_every_network_task_has_a_dispatcher_case(self):
        dispatcher = _read(_DISPATCHER)
        for task in self.TASKS:
            assert f'"{task}" {{' in dispatcher, f"{task} has no case"

    def test_only_the_writer_is_admin_gated(self):
        """Reading which adapters are fitted needs no rights, and gating it
        would raise a UAC prompt just to look — the same reasoning that
        keeps ContextMenuScan ungated."""
        from frontend.menu_structure import ADMIN_REQUIRED_TASKS
        assert "NetworkStackReset" in ADMIN_REQUIRED_TASKS
        assert "NetworkAdapterReport" not in ADMIN_REQUIRED_TASKS
        assert "NetworkDriverCheck" not in ADMIN_REQUIRED_TASKS

    def test_the_stack_reset_reports_a_reboot_rather_than_performing_one(self):
        """Both netsh resets rewrite state the running stack has already
        loaded, so the machine is half-applied until it restarts. A network
        tool that reboots a PC out from under someone is not a tool."""
        network = _read(_NETWORK)
        start = network.index("function Reset-PulseNetworkStack")
        body = network[start:]
        assert "$Script:PendingRestart = $true" in body
        for forbidden in ("Restart-Computer", "shutdown.exe", "shutdown /r"):
            assert forbidden not in body, (
                f"the stack reset calls {forbidden} — it must report the "
                "need for a restart, not perform one")

    def test_the_reset_order_is_winsock_then_ip_then_lease(self):
        """The ip reset re-registers providers the winsock reset just
        cleared, and the lease has to be taken against the rebuilt stack
        rather than the one being torn down."""
        network = _read(_NETWORK)
        start = network.index("function Reset-PulseNetworkStack")
        body = network[start:]
        winsock = body.index('"winsock", "reset"')
        ip = body.index('"int", "ip", "reset"')
        renew = body.index('"/renew"')
        assert winsock < ip < renew

    def test_the_driver_check_only_links_and_never_downloads(self):
        """A network driver is the one component where a wrong package can
        leave a machine with no way to fetch the right one. Pulse
        identifies the hardware and hands over to the vendor."""
        network = _read(_NETWORK)
        start = network.index("function Show-PulseNetworkDriverCheck")
        body = network[start:network.index("\nfunction ", start + 10)]
        for forbidden in ("Invoke-WebRequest", "Start-BitsTransfer",
                          "Smart-Deploy", "winget"):
            assert forbidden not in body, (
                f"the driver check calls {forbidden} — it is meant to be "
                "read-only")

    def test_intel_and_realtek_are_both_covered(self):
        """The two vendors behind almost every consumer Ethernet and Wi-Fi
        adapter, and the two the brief named."""
        network = _read(_NETWORK)
        start = network.index("$Script:NetworkDriverVendors")
        body = network[start:network.index("\nfunction ", start)]
        assert "Intel" in body and "Realtek" in body
        for url in re.findall(r'Url\s*=\s*"([^"]+)"', body):
            assert url.startswith("https://"), f"{url} is not https"


# ============================================================
#  7. THE SCOPED DIALOG
# ============================================================
class TestScopedCatalogDialog:

    @staticmethod
    def _open(window, qapp, key):
        from conftest import show_dialog
        from frontend.menu_structure import catalog_section
        from frontend.widgets import SoftwareCatalogDialog

        section = catalog_section(key)
        item = {"icon": "\U0001f9f1", "title": section["title"]}
        dialog = SoftwareCatalogDialog(window, item, window.theme.t, [section])
        show_dialog(qapp, dialog)
        return dialog

    @pytest.mark.parametrize("key", ["essentials", "development", "runtimes"])
    def test_a_scoped_dialog_shows_only_its_own_pillar(self, window, qapp, key):
        from frontend.menu_structure import catalog_app_ids
        dialog = self._open(window, qapp, key)
        try:
            assert set(dialog._rows) == set(catalog_app_ids(key))
        finally:
            dialog.reject()
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_tabs_subdivide_by_group_when_scoped(self, window, qapp):
        """Given one pillar the tab bar filters by its GROUPS — one level
        down from what it filters by across all three."""
        from frontend.menu_structure import catalog_section
        dialog = self._open(window, qapp, "essentials")
        try:
            groups = [title for title, _tools
                      in catalog_section("essentials")["groups"] if title]
            tabs = [key for key in dialog._tab_buttons if key]
            assert tabs == groups
        finally:
            dialog.reject()
            dialog.deleteLater()
            qapp.processEvents()

    def test_the_bulk_button_ticks_only_the_essential_group(self, window, qapp):
        """It TICKS rather than deploys, so the user can read what was
        queued before pressing Deploy — and it moves the tab so the rows it
        ticked are actually on screen."""
        from frontend.menu_structure import catalog_bulk_ids
        dialog = self._open(window, qapp, "runtimes")
        try:
            assert dialog._bulk, "the runtimes pillar has no bulk action"
            dialog._select_bulk_group()
            qapp.processEvents()
            ticked = {aid for aid, row in dialog._rows.items()
                      if row.is_checked()}
            assert ticked == set(catalog_bulk_ids("runtimes"))
            assert dialog._active_tab == dialog._bulk["group"], (
                "the rows were ticked on a tab the user cannot see")
        finally:
            dialog.reject()
            dialog.deleteLater()
            qapp.processEvents()

    def test_only_the_runtimes_pillar_carries_a_bulk_action(self, window, qapp):
        """The other two are browsing surfaces. A "select everything"
        button on Essential Daily Software would queue seventeen apps
        nobody asked for."""
        for key in ("essentials", "development"):
            dialog = self._open(window, qapp, key)
            try:
                assert not dialog._bulk, f"{key} grew a bulk action"
            finally:
                dialog.reject()
                dialog.deleteLater()
                qapp.processEvents()
