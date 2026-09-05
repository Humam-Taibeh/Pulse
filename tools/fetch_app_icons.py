#!/usr/bin/env python3
"""
tools/fetch_app_icons.py

BUILD-TIME asset fetcher for Software Management's brand logos.

Run this once (or when the catalog changes) to populate
assets/appicons/. Pulse itself NEVER touches the network: the app reads
only the files this script leaves behind, which is what keeps an
elevated, privacy-focused Windows utility from phoning out to draw its
own UI. See src/utils/appicons.py for the runtime half.

    python tools/fetch_app_icons.py            # fetch missing only
    python tools/fetch_app_icons.py --force    # re-fetch everything

SOURCE: Simple Icons (https://simpleicons.org), the standard brand-mark
set for exactly this problem. The SVG files are CC0; the marks themselves
remain their owners' trademarks and are used here nominatively — to
identify the software a row installs, which is the same basis every
package manager and app store relies on.

WHY A HAND-WRITTEN MAP AND NOT FUZZY MATCHING: a wrong logo is worse than
no logo. "Cursor" fuzzy-matches a mouse-cursor icon; "MSI" matches both
the hardware brand and the installer format. Every pairing below was
checked by eye against the Simple Icons index, and anything without an
authentic mark is mapped to None rather than to something that merely
looks close.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(ROOT, "assets", "appicons")
MANIFEST = os.path.join(ASSET_DIR, "manifest.json")
INDEX_URL = "https://cdn.jsdelivr.net/npm/simple-icons@13/_data/simple-icons.json"
ICON_URL = "https://cdn.jsdelivr.net/npm/simple-icons@13/icons/{slug}.svg"

#: winget AppId -> Simple Icons slug, or None when this set has no
#: authentic mark. The None entries are documented, not forgotten; three
#: of them are picked up from a brand-logo set by LOGO_MAP below, and the
#: rest genuinely have no open-licensed logo anywhere:
#:
#:   Microsoft.VisualStudioCode / Microsoft.Edge / Microsoft.DirectX
#:       Simple Icons REMOVED every Microsoft product mark under
#:       Microsoft's trademark policy. Substituting VSCodium's logo for VS
#:       Code (a different product) or a generic Microsoft mark would be
#:       inaccurate.
#:   Anysphere.Cursor / BlueStack.BlueStacks / OpenWebUI.OpenWebUI
#:       Not in the Simple Icons set at all.
#:   CPUID.* / CrystalDewWorld.* / TechPowerUp.GPU-Z
#:       Small hardware utilities with no published brand mark in any
#:       open set. (Note the trap: the index DOES contain a "crystal"
#:       slug — it is the Crystal programming language, nothing to do with
#:       CrystalDiskInfo. Exactly the mismatch this hand-written map
#:       exists to prevent.)
#:
#: Drop an <AppId>.svg into assets/appicons/ by hand to cover any of these
#: — the loader prefers a file on disk over everything except a locally
#: installed app's own icon.
#:
#: NOTE: nearly every entry here is now OVERRIDDEN by LOGO_MAP below,
#: which pulls the same brand's full-colour artwork. This map remains the
#: fallback for anything with no colour source, and the record of which
#: Simple Icons slug was verified for each app.
ICON_MAP: dict[str, str | None] = {
    # -- PILLAR 1: essential daily & system software ----------------
    "Google.Chrome": "googlechrome",
    "Brave.Brave": "brave",
    "Telegram.TelegramDesktop": "telegram",
    "9NKSQCEZVDDB": "whatsapp",
    "Discord.Discord": "discord",
    "Spotify.Spotify": "spotify",
    "VideoLAN.VLC": "vlcmediaplayer",
    "Notion.Notion": "notion",
    "7zip.7zip": "7zip",
    # WinRAR's own mark (the stacked books) exists ONLY in sets Pulse
    # cannot take it from. "reicon:winrar" is a generic archive pictogram
    # wearing the name - the "mark that describes software is still not
    # that software's logo" case - and the one faithful rendition is in
    # OpenMoji, which is CC BY-SA 4.0: a copyleft obligation this MIT app
    # is not going to acquire for one row.
    "RARLab.WinRAR": None,
    "AnyDesk.AnyDesk": "anydesk",
    "Oracle.VirtualBox": "virtualbox",
    "Apple.iTunes": "itunes",
    "Valve.Steam": "steam",
    # Corrected id - winget has no "BlueStacks.BlueStacks"; the real
    # package is "BlueStack.BlueStacks". Simple Icons has no mark for
    # it either way, so it is covered by DRAWN_MAP below.
    "BlueStack.BlueStacks": None,
    "EpicGames.EpicGamesLauncher": "epicgames",
    "RockstarGames.Launcher": "rockstargames",
    # -- PILLAR 2: developer, AI & engineering ----------------------
    "Python.Python.3.12": "python",
    "EclipseAdoptium.Temurin.21.JDK": "eclipseadoptium",
    "OpenJS.NodeJS.LTS": "nodedotjs",
    "MSYS2.MSYS2": "mingww64",          # the toolchain's own mark
    "Git.Git": "git",
    "Microsoft.VisualStudioCode": None,
    "Anysphere.Cursor": None,
    # Antigravity shipped in late 2025; Simple Icons has no entry, and its
    # arch mark is picked up from BoxIcons Logos by LOGO_MAP below.
    "Google.Antigravity": None,
    "Apache.NetBeans": "apachenetbeanside",
    "JetBrains.PyCharm.Community": "pycharm",
    "JetBrains.IntelliJIDEA.Community": "intellijidea",
    "Ollama.Ollama": "ollama",
    "OpenWebUI.OpenWebUI": None,
    "Docker.DockerDesktop": "docker",
    "Postman.Postman": "postman",
    # -- PILLAR 3: runtimes, drivers & diagnostics ------------------
    # The C++ language mark, not a Microsoft one - accurate for a C++
    # redistributable set and unencumbered.
    "Pulse.VCRedistAIO": "cplusplus",
    "Microsoft.DirectX": None,
    "Microsoft.DotNet.DesktopRuntime.8": "dotnet",
    "Pulse.DotNetFx35": "dotnet",
    # OpenAL publishes only WORDMARKS - "OpenAL" beside a speaker, at a
    # 128x24-ish aspect. Every mark here is drawn into a 20px SQUARE box,
    # where a wordmark is an illegible smear. A gap for a GEOMETRY reason
    # rather than a licensing one, which is worth distinguishing: a square
    # OpenAL mark would be usable the day one exists.
    "CreativeTechnology.OpenAL": None,
    # NVIDIA's eye, square and CC0. Deliberately NOT "logos:nvidia", which
    # is the eye PLUS the wordmark at a 512x98 viewBox - letterboxed into
    # a 20px square that renders about four pixels tall.
    "XP8CLZL93F5Z4P": "nvidia",
    "Guru3D.Afterburner": "msi",        # MSI Afterburner is MSI's product
    "CPUID.CPU-Z": None,
    "TechPowerUp.GPU-Z": None,
    "CrystalDewWorld.CrystalDiskInfo": None,
    "CPUID.HWMonitor": None,
    # The three benchmarking/telemetry tools added alongside the four
    # above. Searched before they were listed, with the same result:
    # "hwinfo", "furmark", "cinebench" and "maxon" return NOTHING
    # across every collection Iconify aggregates. Covered by
    # DRAWN_MAP, and labelled there as drawn rather than fetched.
    "REALiX.HWiNFO": None,
    "Geeks3D.FurMark.2": None,
    "Maxon.CinebenchR23": None,
}


# ============================================================
#  SECOND SOURCE: FULL-COLOUR OFFICIAL BRAND LOGOS
# ============================================================
#: winget AppId -> an Iconify icon id from a BRAND-LOGO collection.
#:
#: Simple Icons (above) is a monochrome SILHOUETTE set — one flat path per
#: brand, recoloured at paint time. It is excellent, and it is also why
#: Microsoft's marks are absent: Simple Icons removed every Microsoft
#: product logo under Microsoft's trademark policy.
#:
#: This map is the answer to that gap. It pulls from Iconify's brand-logo
#: collections — principally `logos` (SVG Logos by Gil Barbara, CC0, ~1861
#: marks) — which carry the REAL, FULL-COLOUR artwork: VS Code's blue
#: ribbon with its actual gradient, Edge's actual swirl. These are the
#: vendors' own marks, not renditions, and they render in their true
#: colours rather than as a recoloured silhouette (see `color: true` in
#: the manifest and _brand_pixmap in src/utils/appicons.py).
#:
#: THREE COLLECTIONS, all permissively licensed, tried in this order by
#: hand rather than by search:
#:
#:   logos          CC0-1.0, 1880 marks (Gil Barbara's SVG Logos)
#:   thesvg-color   MIT, 4847 marks (thesvg.org)
#:   devicon        MIT, 1036 marks
#:
#: The map below is what MOVED THE CATALOG from 2 real logos and 34
#: recoloured silhouettes to 36 real logos and 1 silhouette. A silhouette
#: is authentic in shape and wrong in everything else — Chrome as a flat
#: blue disc is not the mark anyone recognises — so a colour source is
#: preferred wherever one genuinely exists.
#:
#: WHAT IS STILL MISSING, and why nothing is invented to cover it:
#: BlueStacks, DirectX, CPU-Z, GPU-Z, HWMonitor and CrystalDiskInfo have
#: NO authentic mark in any open, licensed icon set. That was not assumed
#: — it was measured against the full Simple Icons index (~3300 marks),
#: the whole `logos` collection (1880), the two MIT sets above, and
#: Iconify's federated search across every collection it aggregates. Those
#: six fall through to the runtime's next tier: the app's OWN icon, read
#: from its own installed binary, which is the vendor's genuine artwork
#: and needs no redistribution at all. When the app is not installed they
#: reach the neutral glyph, which says "no logo available" honestly.
#:
#: THE TRAPS ARE CLOSE AND THE SEARCH FINDS THEM: "hwmonitor" returns
#: `campaignmonitor`, "crystaldiskinfo" returns `crystal` (the programming
#: language) and "epic games" returns `unrealengine` — a different Epic
#: product. Every pairing below was checked by eye for that reason.
#:
#: THE RULE THIS FILE IS BUILT ON, restated because it was tested: a WRONG
#: logo is worse than no logo, and an INVENTED one is worse than both. No
#: entry in THIS map is ever a lookalike picked by keyword.
#:
#: DRAWN_MAP below is the one, labelled exception to the second half of
#: that rule, and it is deliberately a separate map rather than a few
#: quiet entries in this one: nine products that have no artwork anywhere
#: now carry a Pulse-drawn pictogram in their own colour, recorded in the
#: manifest as `drawn: true` so nothing can mistake one for a vendor's
#: logo. Read its note before adding to it. The first half of the rule is
#: untouched — a lookalike is still worse than nothing, and there are
#: still none here.
LOGO_MAP: dict[str, str] = {
    # -- PILLAR 1: essential daily & system software ----------------
    "Google.Chrome": "logos:chrome",
    "Brave.Brave": "logos:brave",
    "Telegram.TelegramDesktop": "logos:telegram",
    "9NKSQCEZVDDB": "logos:whatsapp-icon",
    "Discord.Discord": "logos:discord-icon",
    "Spotify.Spotify": "logos:spotify-icon",
    "VideoLAN.VLC": "thesvg-color:vlc-media-player",
    "Notion.Notion": "logos:notion-icon",
    "7zip.7zip": "thesvg-color:7zip",
    "AnyDesk.AnyDesk": "thesvg-color:anydesk",
    "Oracle.VirtualBox": "thesvg-color:virtualbox",
    "Apple.iTunes": "thesvg-color:itunes",
    # THE COLOUR MARK, not the flat one. "logos:steam" is a single
    # #1a1918 silhouette — Steam as a near-black disc, which is the
    # "monochrome block" complaint in its purest form. thesvg-color's copy
    # is the authentic brand artwork: the blue gradient disc with the
    # white piston. It is packaged as a <symbol> + <use>, which Qt draws
    # as a blank white circle, so it is normalised on the way in — see
    # _flatten_symbols, which rewrites the container and touches no
    # geometry or colour.
    "Valve.Steam": "thesvg-color:steam",
    # "-light" is the DARK-INK variant (the one drawn for light
    # backgrounds), which is the better of the two here: on the light
    # theme it needs no help at all, and on obsidian the runtime's
    # measured contrast guard gives it the same white tile an app store
    # would (see _backing_plaque in src/utils/appicons.py).
    "EpicGames.EpicGamesLauncher": "thesvg-color:epic-games-light",
    "RockstarGames.Launcher": "thesvg-color:rockstar-games",
    # -- PILLAR 2: developer, AI & engineering ----------------------
    "Python.Python.3.12": "logos:python",
    # ADOPTIUM'S OWN MARK, and this is a CORRECTION. It was
    # "logos:eclipse-icon" - the Eclipse IDE's purple circle, a different
    # product from the same foundation. A Java JDK row showing the logo of
    # an IDE nobody is installing is exactly the "wrong logo" this file's
    # own rule forbids, and it was reported as a placeholder because in
    # context it was unrecognisable.
    "EclipseAdoptium.Temurin.21.JDK": "thesvg-color:eclipse-adoptium",
    "OpenJS.NodeJS.LTS": "logos:nodejs-icon",
    # ALSO A CORRECTION. This was "logos:gnu" - the GNU project's gnu
    # head, defensible for a GCC toolchain and 18KB of detailed line art
    # that resolves to a grey smudge at 20px. MinGW-w64 publishes its own
    # mark; it names the toolchain actually being installed, and it
    # survives being small.
    "MSYS2.MSYS2": "thesvg-color:mingw-w64",
    "Git.Git": "logos:git-icon",
    "Microsoft.VisualStudioCode": "logos:visual-studio-code",
    # BoxIcons Logos' rendition of Cursor's cube mark - a curated
    # brand-logo set, not a lookalike picked by keyword. STILL THE
    # MONOCHROME ONE: Cursor's mark has no full-colour version in any
    # permissive set, and its own brand cube is monochrome anyway.
    "Anysphere.Cursor": "bxl:cursor-ai",
    # Antigravity's arch, from the same MIT collection, and monochrome for
    # a related reason: the colour renditions on offer are Google's
    # four-colour blobs, which are the COMPANY's mark rather than this
    # product's.
    "Google.Antigravity": "bxl:google-antigravity",
    # THE APACHE CUBE, and this is a CORRECTION of the kind this file's
    # own rule exists to catch. It was "logos:netbeans" — the RETIRED
    # NetBeans mark, a red wireframe mesh from the Sun/Oracle era, which
    # renders at 20px as a tangle of hairlines in a colour the project no
    # longer uses. Apache NetBeans' current mark is a solid three-quarter
    # cube in blue, green and magenta; devicon carries it (MIT), it is
    # built from filled faces rather than strokes, and it survives being
    # small — which the wireframe never could.
    "Apache.NetBeans": "devicon:netbeans",
    "JetBrains.PyCharm.Community": "logos:pycharm",
    "JetBrains.IntelliJIDEA.Community": "logos:intellij-idea",
    "Ollama.Ollama": "devicon:ollama",
    "OpenWebUI.OpenWebUI": "thesvg-color:openwebui",
    "Docker.DockerDesktop": "logos:docker-icon",
    "Postman.Postman": "logos:postman-icon",
    # -- PILLAR 3: runtimes, drivers & diagnostics ------------------
    # VISUAL STUDIO'S OWN MARK, in Microsoft's purple, rather than the
    # generic C++ hex. What this row installs is the "Microsoft Visual C++
    # Redistributable" — a Visual Studio component, shipped by Microsoft,
    # named after Visual Studio — so the VS infinity mark identifies the
    # actual product where the language logo only identifies the language
    # it was written in. (The C++ hex was a deliberate choice once, for
    # being unencumbered; `logos:visual-studio` is CC0 too, so that
    # reasoning no longer costs anything.)
    "Pulse.VCRedistAIO": "logos:visual-studio",
    "Microsoft.DotNet.DesktopRuntime.8": "logos:dotnet",
    "Pulse.DotNetFx35": "logos:dotnet",
    # MSI Afterburner is MSI's product, so MSI's mark identifies it
    "Guru3D.Afterburner": "thesvg-color:msi",
}

ICONIFY_SVG = "https://api.iconify.design/{prefix}/{name}.svg"


# ============================================================
#  THIRD SOURCE: PULSE-DRAWN MARKS  (NOT vendor logos)
# ============================================================
#: winget AppId -> a mark COMMITTED BY HAND to assets/appicons/, for the
#: products that have no artwork in any open, licensed set.
#:
#: READ THIS BEFORE ADDING TO IT. Every entry here is a departure from the
#: rule the rest of this file is built on - "a wrong logo is worse than no
#: logo, and an invented one is worse than both" - and the departure is
#: deliberate, bounded, and LABELLED rather than quietly taken.
#:
#: WHAT THESE ARE: Pulse-drawn pictograms of what each tool measures,
#: carrying that product's own established colour. A CPU die for CPU-Z, a
#: thermometer for HWMonitor, a card and fan for GPU-Z, a platter and
#: needle for CrystalDiskInfo, a sensor trace for HWiNFO64, a flame for
#: FurMark, a render cube for Cinebench. DirectX gets the X-cross its mark
#: has always been, and BlueStacks the layered green stack.
#:
#: WHAT THESE ARE NOT: the vendors' logos. They are not renditions of
#: them, they do not claim to be, and nothing downstream should treat them
#: as such. The manifest records `drawn: true` and `source: "pulse-drawn"`
#: for exactly this reason - so a later reader diffing the asset folder
#: can tell in ONE FIELD which marks came from a vendor and which came
#: from here, without having to know this comment exists.
#:
#: WHY AT ALL, given the rule. The alternative was measured rather than
#: assumed: those nine rows rendered the neutral "no logo available"
#: parcel, and nine grey parcels in a group of nine is not an honest
#: fallback any more - it is a Hardware Diagnostics list with no icons in
#: it, sitting beside two pillars where every row has one. The gap was
#: also re-checked before it was filled rather than taken on trust from
#: the last time: Iconify's federated search across every collection it
#: aggregates returns ZERO results for bluestacks, directx, cpu-z, gpu-z,
#: crystaldiskinfo, hwmonitor, hwinfo, furmark and cinebench. There is
#: nothing to fetch, and there will not be tomorrow.
#:
#: THE DAY REAL ARTWORK APPEARS, delete the entry here and add one to
#: LOGO_MAP: the fetched mark then wins, because this pass runs last only
#: so that it cannot be clobbered by a download that does not exist.
#:
#: RARLab.WinRAR and CreativeTechnology.OpenAL are deliberately NOT here.
#: Their gaps have different causes - a copyleft licence, and a wordmark
#: geometry that cannot survive a 20px square - both of which could close
#: properly, and neither is worth spending this exception on.
DRAWN_MAP: dict[str, tuple[str, str]] = {
    # AppId: (title, the product's own established colour)
    "Microsoft.DirectX": ("DirectX", "#0f7bd4"),
    "BlueStack.BlueStacks": ("BlueStacks", "#8bc53f"),
    "CPUID.CPU-Z": ("CPU-Z", "#3f51b5"),
    "CPUID.HWMonitor": ("HWMonitor", "#f09e1a"),
    "TechPowerUp.GPU-Z": ("GPU-Z", "#2e9e4f"),
    "CrystalDewWorld.CrystalDiskInfo": ("CrystalDiskInfo", "#2aa9e0"),
    "REALiX.HWiNFO": ("HWiNFO64", "#1e62a8"),
    "Geeks3D.FurMark.2": ("FurMark", "#e8452c"),
    "Maxon.CinebenchR23": ("Cinebench", "#8e44ad"),
}

#: Brand hex for LOGO_MAP entries that turn out to be SILHOUETTES (drawn
#: with `currentColor`) rather than full-colour artwork. These take the
#: Simple Icons treatment — recoloured through the contrast guard — so
#: they need the brand's own colour the same way those do.
MONOCHROME_LOGO_HEX: dict[str, str] = {
    # Cursor's mark is a monochrome cube; black is its own brand colour,
    # and the guard lifts it off obsidian exactly as it does for Steam,
    # Notion and 7-Zip, which are all #000000 too.
    "Anysphere.Cursor": "#000000",
    # ANTIGRAVITY'S OWN BLUE, and #000000 was the bug. The reasoning for
    # black was that the contrast guard would carry it to white on
    # obsidian — but the guard stops at the readability floor rather than
    # going all the way, so what it actually produced was a DIM GREY arch
    # on dark and a flat black one on light. Read as a shape with no
    # brand in it, which is exactly how it was reported.
    #
    # #3186ff is not a colour chosen for this file: it is lifted from
    # Antigravity's own full-colour artwork (thesvg-color:antigravity-
    # google), whose palette is #3186ff / #00b95c / #fbbc04 / #fc413d.
    # That artwork cannot be used directly — it is a masked composition,
    # and Qt's SVG Tiny renderer has no <mask>, so it draws either blank
    # or as blobs spilling outside their own viewBox. The arch geometry
    # here is the vendor's; so now is the ink.
    "Google.Antigravity": "#3186ff",
}


_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"


def _flatten_symbols(data: bytes) -> bytes:
    """Inline `<symbol>` + `<use>` so Qt can draw the mark.

    QSvgRenderer implements SVG Tiny 1.2, which has no `<symbol>` and no
    `<use>` that resolves to one. Qt does not error on those elements — it
    silently draws nothing for them, and whatever container fill was in
    scope paints instead. `thesvg-color:steam` is a `<symbol>` holding the
    valve mark, `<use>`d inside a `<g fill="#fff">`: rendered by Qt it came
    out as a FLAT WHITE DISC, which is indistinguishable from a broken
    asset and was rejected as one before this existed.

    That mattered because the same artwork is what the catalog wants.
    Steam's authentic mark is the blue-gradient disc with the white
    piston, `thesvg-color:steam` is the MIT-licensed copy of it, and the
    only thing standing between the two was a container element. So the
    artwork is left ALONE and its packaging is rewritten: every `<use>` of
    a symbol becomes a `<g>` carrying the same translate, holding the
    symbol's own children verbatim. No geometry moves, no colour changes,
    nothing is redrawn — this is a format transform, not a rendition.

    A file with no `<symbol>` is returned byte-for-byte unchanged, which
    is every other mark in the set. That is deliberate: this runs over
    thirty working assets, and a normaliser that reserialises them all
    would rewrite files it has no business touching and produce a diff
    nobody can review.
    """
    if b"<symbol" not in data:
        return data
    import xml.etree.ElementTree as ET

    ET.register_namespace("", _SVG_NS)
    ET.register_namespace("xlink", _XLINK_NS)
    root = ET.fromstring(data.decode("utf-8"))

    symbols: dict[str, ET.Element] = {}
    for element in root.iter(f"{{{_SVG_NS}}}symbol"):
        ident = element.get("id")
        if ident:
            symbols[ident] = element
    if not symbols:
        return data

    def _target(use: ET.Element) -> str:
        ref = use.get("href") or use.get(f"{{{_XLINK_NS}}}href") or ""
        return ref[1:] if ref.startswith("#") else ""

    # Parents are walked explicitly because ElementTree gives a child no
    # link back to its parent, and both edits below are structural.
    for parent in root.iter():
        for index, child in reversed(list(enumerate(parent))):
            if child.tag == f"{{{_SVG_NS}}}symbol":
                del parent[index]
                continue
            if child.tag != f"{{{_SVG_NS}}}use":
                continue
            symbol = symbols.get(_target(child))
            if symbol is None:
                continue
            group = ET.Element(f"{{{_SVG_NS}}}g")
            # `x`/`y` on a <use> are a translation of its content. Carried
            # over as a transform so the half-pixel insets these sets use
            # to centre a mark inside its viewBox are preserved exactly.
            dx, dy = child.get("x", "0"), child.get("y", "0")
            if (dx, dy) != ("0", "0"):
                group.set("transform", f"translate({dx},{dy})")
            for attribute, value in child.attrib.items():
                if attribute not in ("x", "y", "href", "width", "height",
                                     f"{{{_XLINK_NS}}}href"):
                    group.set(attribute, value)
            group.extend(list(symbol))
            parent[index] = group

    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pulse-icon-fetch"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def _slugify(title: str) -> str:
    out = title.lower().replace("+", "plus").replace(".", "dot").replace("&", "and")
    return "".join(ch for ch in out if ch.isalnum())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="re-download icons that are already present")
    args = parser.parse_args()

    os.makedirs(ASSET_DIR, exist_ok=True)
    print(f"index  <- {INDEX_URL}")
    raw = json.loads(_get(INDEX_URL).decode("utf-8"))
    entries = raw["icons"] if isinstance(raw, dict) else raw
    # the published index leaves `slug` blank for most entries, so derive
    # it the same way Simple Icons does and key on that
    index = {(e.get("slug") or _slugify(e.get("title", ""))): e for e in entries}
    print(f"       {len(index)} brand marks available")

    manifest: dict[str, dict] = {}
    fetched = skipped = 0
    unmapped: list[str] = []

    for app_id, slug in sorted(ICON_MAP.items()):
        if slug is None:
            unmapped.append(app_id)
            continue
        entry = index.get(slug)
        if entry is None:
            print(f"  !! {app_id}: slug {slug!r} is not in the index")
            unmapped.append(app_id)
            continue
        # File name is the APP ID, not the slug: the runtime looks up by
        # the id it already has, and a hand-supplied override drops in at
        # the same path with no manifest edit.
        safe = app_id.replace("/", "_").replace("\\", "_")
        path = os.path.join(ASSET_DIR, f"{safe}.svg")
        if args.force or not os.path.isfile(path):
            data = _get(ICON_URL.format(slug=slug))
            if b"<svg" not in data[:400]:
                print(f"  !! {app_id}: {slug}.svg was not an SVG, skipped")
                unmapped.append(app_id)
                continue
            with open(path, "wb") as handle:
                handle.write(data)
            fetched += 1
        else:
            skipped += 1
        manifest[app_id] = {
            "file": f"{safe}.svg",
            "hex": "#" + str(entry.get("hex", "000000")).lstrip("#"),
            "title": entry.get("title", ""),
        }

    # -- second pass: full-colour official logos ------------------
    # Written AFTER the Simple Icons pass so a LOGO_MAP entry wins for any
    # app that somehow appears in both: the vendor's real colour artwork is
    # a better answer than a recoloured silhouette of it.
    colour_failures: list[str] = []
    for app_id, icon_id in sorted(LOGO_MAP.items()):
        prefix, _, name = icon_id.partition(":")
        if not prefix or not name:
            colour_failures.append(f"{app_id}: malformed icon id {icon_id!r}")
            continue
        safe = app_id.replace("/", "_").replace("\\", "_")
        path = os.path.join(ASSET_DIR, f"{safe}.svg")
        # ALWAYS DOWNLOADED, never skipped for an existing file — and this
        # is the fix for the defect that made seven marks render as solid
        # black blocks.
        #
        # The guard here used to be the same `if args.force or not
        # os.path.isfile(path)` the Simple Icons pass above uses, which is
        # correct THERE and wrong here, because the two passes write THE
        # SAME PATH. Pass one had just created <AppId>.svg from Simple
        # Icons; pass two then found the file present, skipped its own
        # download — and went on to write a manifest record naming the
        # LOGO_MAP source and flagging `color: true`.
        #
        # So the manifest said "this is thesvg-color:anydesk, full-colour
        # vendor artwork, render it as drawn" over a Simple Icons
        # SILHOUETTE. A silhouette has no fill of its own and defaults to
        # black, and the render-as-drawn path deliberately does not touch
        # colours — so the row painted a solid black shape on a rescue
        # plate, which is exactly the "flattened to a monochrome block"
        # report. It never reached the contrast guard that exists to
        # prevent precisely that, because the manifest had told the
        # runtime it was not a silhouette.
        #
        # The `color` flag was not lying about the FILE, either, which is
        # why the classification test could not see it: that check reads
        # the artwork for `currentColor`, and a Simple Icons path carries
        # no fill attribute at all rather than `currentColor`. Both halves
        # looked locally consistent; only the pairing was wrong.
        #
        # Overwriting unconditionally is right rather than merely
        # sufficient: reaching this loop at all means LOGO_MAP names a
        # better source for this app, and the file at that path was
        # written seconds ago by the pass this one exists to supersede.
        # `skipped` therefore only ever counts pass one now.
        try:
            data = _get(ICONIFY_SVG.format(prefix=prefix, name=name))
        except Exception as exc:                    # noqa: BLE001
            colour_failures.append(f"{app_id}: {icon_id} fetch failed ({exc})")
            continue
        if b"<svg" not in data[:400]:
            colour_failures.append(f"{app_id}: {icon_id} was not an SVG")
            continue
        data = _flatten_symbols(data)
        with open(path, "wb") as handle:
            handle.write(data)
        fetched += 1
        # DETECTED, not assumed. Some brand-logo sets publish a mark as a
        # single path filled with `currentColor` — a SILHOUETTE wearing a
        # colour set's prefix. Flagging one of those `color: true` would
        # send it down the render-as-drawn path, where "currentColor"
        # resolves to black and the mark disappears into a dark canvas
        # with a rescue plaque bolted behind it. Reading the file decides
        # correctly for every entry, including ones added later.
        with open(path, "rb") as handle:
            body = handle.read().decode("utf-8", "ignore")
        monochrome = "currentColor" in body
        record = {
            "file": f"{safe}.svg",
            "source": icon_id,
            "title": name.replace("-", " ").title(),
        }
        if monochrome:
            # Same treatment as a Simple Icons mark: a brand hex plus the
            # runtime's contrast guard, which is what keeps a near-black
            # silhouette readable on obsidian.
            record["hex"] = MONOCHROME_LOGO_HEX.get(app_id, "#000000")
        else:
            # `color` is the flag the runtime reads to render the mark AS
            # DRAWN instead of recolouring it to a single tone. A full
            # colour logo pushed through the silhouette path would come out
            # as a flat blue blob — accurate artwork, destroyed on paint.
            record["color"] = True
        manifest[app_id] = record
        unmapped = [a for a in unmapped if a != app_id]

    # -- third pass: the hand-committed marks ---------------------
    # RECORDED, NEVER DOWNLOADED. These files are in the repository; this
    # loop exists to put them in the manifest (so the runtime looks them
    # up at all) and to stamp them `drawn` (so nothing downstream mistakes
    # one for vendor artwork). Running last means a LOGO_MAP entry added
    # later for the same app silently wins, which is the outcome we want
    # the day one of these brands publishes a real mark.
    drawn_missing: list[str] = []
    for app_id, (title, hex_colour) in sorted(DRAWN_MAP.items()):
        safe = app_id.replace("/", "_").replace("\\", "_")
        path = os.path.join(ASSET_DIR, f"{safe}.svg")
        if not os.path.isfile(path):
            drawn_missing.append(f"{app_id}: {safe}.svg is not in assets/appicons/")
            continue
        manifest[app_id] = {
            "color": True,
            "drawn": True,
            "file": f"{safe}.svg",
            "hex": hex_colour,
            "source": "pulse-drawn",
            "title": title,
        }
        unmapped = [a for a in unmapped if a != app_id]

    # newline="\n": .gitattributes pins *.json to LF, and text mode
    # on Windows would write CRLF for every line of a file the repo
    # tracks. THE ESCAPES ARE LOAD-BEARING and were literal newlines
    # here until v1.1: the file was a syntax error, so the fetcher
    # could not run at all. Nothing imports a tool, so nothing noticed
    # — see tests/test_packaging.py::test_every_repo_tool_is_valid_python.
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)
        handle.write("\n")

    colour = sum(1 for entry in manifest.values() if entry.get("color"))
    print(f"\nfetched {fetched}, already present {skipped}")
    print(f"manifest -> {os.path.relpath(MANIFEST, ROOT)} "
          f"({len(manifest)} marks: {len(manifest) - colour} monochrome, "
          f"{colour} full-colour)")
    if unmapped:
        print(f"\nno authentic brand mark exists in any open set "
              f"({len(unmapped)}) — these fall through to the app's OWN "
              "installed icon, then to the neutral glyph:")
        for app_id in unmapped:
            print(f"    {app_id}")
        print("  (drop a genuine <AppId>.svg into assets/appicons/ and add "
              "it to LOGO_MAP to bundle one. No lookalike is ever taken; "
              "for the one labelled exception, see DRAWN_MAP.)")
    drawn = sum(1 for entry in manifest.values() if entry.get("drawn"))
    if drawn:
        print(f"\n{drawn} Pulse-DRAWN mark(s) recorded (source: pulse-drawn) "
              "- pictograms in the product's own colour, NOT the vendors' "
              "logos. See DRAWN_MAP.")
    if drawn_missing:
        print("\n!! DRAWN_MAP entries with no file committed:")
        for failure in drawn_missing:
            print(f"    {failure}")
        return 1
    if colour_failures:
        print("\n!! LOGO_MAP entries that did not resolve:")
        for failure in colour_failures:
            print(f"    {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
