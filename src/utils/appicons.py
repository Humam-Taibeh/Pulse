"""
src/utils/appicons.py

APP ICON RESOLUTION for Software Management rows.

Every catalog row (SoftwareCatalogDialog, Update Center) shows the app's
mark on a square plaque beside its name — widgets.APP_ICON_PX, currently
36px, which is TH.CONTROL_H so the icon column lines up with the filter
field and the tab pills above it. Three sources, tried in order:

  1. A BUNDLED VECTOR MARK — assets/appicons/<AppId>.svg, fetched at BUILD
     time by tools/fetch_app_icons.py and rendered here as vector so it
     stays crisp at any size or DPI. EVERY ONE IS THE VENDOR'S GENUINE
     MARK; Pulse ships no hand-drawn stand-ins. Two kinds live here, and
     the manifest's "color" flag distinguishes them:

       - FULL COLOUR — the real artwork including gradients: Chrome's
         four-colour wheel, Firefox's fox, Edge's swirl. Rendered exactly
         as drawn; legibility is handled by the WELL underneath rather
         than by altering the colours, because recolouring real vendor
         artwork is what would make it inauthentic. This is now all but
         one of them.

       - MONOCHROME — a single-path silhouette with a brand hex,
         recoloured at paint time subject to the contrast guard below.
         ONE MARK still takes this path (Cursor), because Cursor's own
         brand cube IS monochrome; a "colour" version would be invented.

     THAT SPLIT USED TO RUN THE OTHER WAY — 34 silhouettes to 2 real
     logos, because Simple Icons is a monochrome set. A recoloured
     silhouette is authentic in SHAPE and wrong in every other respect:
     Chrome was a flat blue disc, Steam a flat black one, and the thing
     that makes those marks recognisable at 20px is precisely the colour
     that had been taken out of them. The fetcher now prefers the CC0
     `logos` collection and the MIT `thesvg-color` / `devicon` sets, and
     falls back to a silhouette only where no colour artwork exists.

     SIX CATALOG APPS HAVE NO BUNDLED MARK AT ALL, and that is a finding,
     not an omission: BlueStacks, DirectX, CPU-Z, GPU-Z, HWMonitor and
     CrystalDiskInfo have no authentic logo in ANY open, licensed set.
     That was measured, twice — the full Simple Icons index (~3300 marks),
     the whole `logos` collection (1880), and Iconify's federated search
     across every collection it aggregates. They fall to tier 2, where the
     vendor's own artwork is read out of their own installed binary, and
     to tier 3 when the app is not present. An invented pictogram in that
     gap was tried and REMOVED: a mark that describes software is still
     not that software's logo, and the rule here is that a wrong logo is
     worse than no logo. The traps are real and close — the index offers
     `campaignmonitor` for HWMonitor and `crystal` (the programming
     language) for CrystalDiskInfo.

     THIS OUTRANKS THE INSTALLED APP'S OWN ICON, which is not the obvious
     ordering and was arrived at by looking at the result. Windows' icon
     extraction is best-effort: it resolves a DisplayIcon path, and when
     that path is stale, points into a container it cannot read, or names
     a file type with no embedded icon, it hands back a GENERIC document
     glyph rather than failing. Measured on a real machine, Steam and
     iTunes — both installed — came back as blank white pages sitting in a
     row of real logos. A curated mark is guaranteed to be the right
     artwork for the right product, and a list where every row is drawn
     from one source reads as designed rather than as scavenged.

  2. THE INSTALLED APP'S OWN ICON — for software with no bundled mark
     that is already on this machine. Full colour, drawn by the vendor,
     read out of the app's own binary.

     THIS TIER IS LOAD-BEARING, and an earlier draft of this docstring
     said the opposite ("every catalog app now has a bundled mark, so this
     tier no longer fires for them") four paragraphs after correctly
     listing the six that do not. It is the only thing standing between
     those six and the neutral glyph, so reading that sentence as licence
     to delete it would have quietly downgraded CPU-Z, GPU-Z, HWMonitor,
     CrystalDiskInfo, BlueStacks and DirectX to grey parcels.

     It also covers the Update Center, which lists whatever winget reports
     as upgradable and is therefore not limited to the catalog at all.

     The count is pinned by
     TestBrandMarks.test_every_catalog_app_has_a_mark_or_is_a_known_exception,
     so this paragraph cannot drift from the tree again.

  ALL THREE TIERS ARE PRESENTED IDENTICALLY: a 20px mark centred in a
  36px well with an 8px radius (see _MARK_RATIO and _paint_well). Brand
  SVGs disagree about their own internal padding, so drawing each "as
  large as fits" produced a column of marks at visibly different optical
  sizes — which reads as scavenged however genuine each one is. Fixing the
  INNER box is what makes them a set, and putting tiers 2 and 3 on the
  same plate is what stops the one unknown app in a list looking broken.

  3. A NEUTRAL GLYPH — a soft rounded "package" mark in the theme's muted
     tone. This replaced the LETTER MONOGRAM plaques, which put a bare
     "E", "R" or "B" where the Epic, Rockstar and BlueStacks logos
     belonged and read as an unfinished placeholder. A neutral mark that
     is identical for every unknown app says "no logo available"
     honestly; an invented letter tile pretends to be branding.

     No catalog row reaches this any more (tests/test_contract.py pins
     that), but it stays as the honest floor for the Update Center's
     off-catalog entries.

PULSE NEVER FETCHES ANYTHING. Step 2 reads files committed to the repo;
the network lives entirely in the build-time tool. An elevated
privacy-focused utility must not phone out to draw its own interface, and
this also makes the icons work on an air-gapped machine.

THE CONTRAST GUARD (the reason brand hex alone is not enough): a brand
colour is chosen against the vendor's own backdrop, usually white. Steam,
Notion, Ollama, IntelliJ, PyCharm and 7-Zip are all #000000; Epic Games
is #313131. Painted as-is those are invisible on the obsidian canvas —
the exact "unpolished" failure this module exists to fix, just in a new
form. Each mark is therefore measured against the surface it will sit on
and, when it cannot clear the readability floor, lightened (dark theme)
or darkened (light theme) along its own hue until it does. A monochrome
mark has no hue to preserve, so it simply becomes near-white on obsidian
— which is what those brands' own dark-mode guidelines specify anyway.
"""
from __future__ import annotations

import json
import os
import re
import sys

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from utils import resources

# name-normalisation strips everything but letters/digits so catalog names
# ("VLC Media Player") can meet registry names ("VLC media player 3.0.20")
_NORM_RE = re.compile(r"[^a-z0-9]+")

# lazy singletons — see the per-function notes
_ICON_INDEX: dict[str, str] | None = None
_MANIFEST: dict[str, dict] | None = None
_PIXMAP_CACHE: dict[tuple, QPixmap] = {}
_PROVIDER = None
_UNSET = object()          # "not resolved yet", distinct from "resolved to None"

#: Windows' generic document-icon bytes, PER DEVICE SIZE.
#:
#: One cached key for the first size ever asked for was survivable only
#: while every caller asked for the same one. _shell_pixmap compares raw
#: image bytes against this to reject the blank-page placeholder, and two
#: different sizes can never compare equal — so a single shared key means
#: the rejection silently stops working the moment a second size appears,
#: and Windows' placeholder gets shown as though it were the app's own
#: icon. Rendering at the screen's ratio introduces exactly that second
#: size, so the key has to be per-size to keep the guard honest.
_GENERIC_KEYS: dict[int, bytes | None] = {}

_UNINSTALL_ROOTS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)

#: Minimum contrast ratio a brand mark must reach against the surface
#: behind it. Below the 3:1 the theme's own icon floor uses, because a
#: logo is a large solid shape rather than a thin glyph — but far enough
#: above 1:1 that a black mark on obsidian can never ship.
_MIN_CONTRAST = 2.6


def _norm(name: str) -> str:
    return _NORM_RE.sub("", name.lower())


# ============================================================
#  1. THE INSTALLED APP'S OWN ICON
# ============================================================
def _build_icon_index() -> dict[str, str]:
    """normalised DisplayName -> DisplayIcon path, from every Uninstall
    hive a standard user can read. Every failure is skipped: a single
    unreadable key must never cost the whole index."""
    index: dict[str, str] = {}
    if sys.platform != "win32":
        return index
    import winreg

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for root in _UNINSTALL_ROOTS:
            try:
                key = winreg.OpenKey(hive, root)
            except OSError:
                continue
            try:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    except OSError:
                        continue
                    try:
                        name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                        icon = str(winreg.QueryValueEx(sub, "DisplayIcon")[0])
                    except OSError:
                        continue
                    finally:
                        sub.Close()
                    path = _clean_icon_path(icon)
                    if name and path:
                        index.setdefault(_norm(name), path)
            finally:
                key.Close()
    return index


def _clean_icon_path(display_icon: str) -> str | None:
    """`"C:\\...\\app.exe",0` -> a bare, env-expanded file path. The
    trailing `,index` selects an icon WITHIN the file; QFileIconProvider
    always takes the file's primary icon, which for real apps is the
    brand mark — the distinction only matters for icon libraries."""
    path = display_icon.strip().strip('"')
    if "," in path:
        head, _, tail = path.rpartition(",")
        if tail.lstrip("-").isdigit():
            path = head.strip().strip('"')
    path = os.path.expandvars(path)
    return path if path.lower().endswith((".exe", ".ico", ".dll")) else None


def _installed_icon_path(app_name: str) -> str | None:
    """Exact normalised match first, then containment either way (min 5
    chars, so 'Git' can't claim 'GitHub Desktop'-adjacent noise)."""
    global _ICON_INDEX
    if _ICON_INDEX is None:
        try:
            _ICON_INDEX = _build_icon_index()
        except Exception:
            _ICON_INDEX = {}
    needle = _norm(app_name)
    if not needle:
        return None
    hit = _ICON_INDEX.get(needle)
    if hit:
        return hit
    if len(needle) >= 5:
        for key, path in _ICON_INDEX.items():
            if needle in key or (len(key) >= 5 and key in needle):
                return path
    return None


def _generic_shell_key(device_px: int) -> bytes | None:
    """The raw bytes of Windows' GENERIC document icon at `device_px`.

    Windows' icon extraction never fails loudly: hand it a stale path, a
    container it cannot open, or a file type with nothing embedded, and it
    returns the blank-page placeholder as though that were the app's icon.
    Rendered into a row of real logos that reads as a broken image, so the
    placeholder is identified and rejected rather than shown. Comparing
    against the provider's own File icon is exact and needs no heuristics.

    Takes the resolved DEVICE size, not the logical one, because the bytes
    it returns are only comparable against a pixmap requested at the same
    size — see _GENERIC_KEYS.
    """
    if device_px in _GENERIC_KEYS:
        return _GENERIC_KEYS[device_px]
    key: bytes | None = None
    try:
        from PySide6.QtWidgets import QFileIconProvider
        provider = _icon_provider()
        pm = provider.icon(QFileIconProvider.IconType.File).pixmap(
            QSize(device_px, device_px))
        if not pm.isNull():
            image = pm.toImage()
            key = bytes(image.constBits())
    except Exception:
        key = None
    _GENERIC_KEYS[device_px] = key
    return key


def invalidate_cache() -> None:
    """Drop every rendered mark and shell-icon key.

    Called when the window moves to a screen with a different ratio (see
    PulseApp._on_screen_changed). The pixmap cache is keyed on the ratio,
    so stale entries can never be SERVED to the new screen — but they are
    dead weight for a ratio that may never come back, and clearing them is
    what makes the re-skin that follows actually re-rasterise instead of
    finding its own pre-move entry still valid.

    _GENERIC_KEYS goes too: its keys are device sizes, which are a
    function of the ratio, so the same reasoning applies.
    """
    _PIXMAP_CACHE.clear()
    _GENERIC_KEYS.clear()


def _screen_dpr() -> float:
    """The primary screen's device-pixel ratio, floored at 1.0.

    Every mark here used to be rasterised at exactly px*2 and stamped
    setDevicePixelRatio(2.0) regardless of the display. That is pixel-exact
    on a 200% screen and resampled on every other one — including 125%,
    150% and 175%, which is most Windows laptops. The marks are SVG, so
    rendering at the real ratio is lossless and costs nothing; the fixed
    2.0 was only ever a guess at the display.

    theme.icon_pixmap already does exactly this for the search glyph (see
    its "RENDERED AT THE SCREEN'S DEVICE PIXEL RATIO" note, v10.9.3). This
    is the same fix for the 37 vendor marks the catalog draws.

    Floored at 1.0 because a ratio below 1 would rasterise BELOW the
    logical size and hand Qt an upscale — the one outcome worse than the
    fixed 2.0 it replaces. None-safe for a headless/pre-QGuiApplication
    call, which the icon tests make directly.
    """
    try:
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
    except Exception:
        return 1.0
    if screen is None:
        return 1.0
    try:
        return max(1.0, float(screen.devicePixelRatio()))
    except (TypeError, ValueError):
        return 1.0


def _device_px(px: int) -> tuple[int, float]:
    """(device pixels, ratio) for a logical size — the pair every renderer
    below needs, resolved once so they cannot disagree."""
    dpr = _screen_dpr()
    return max(1, round(px * dpr)), dpr


def _icon_provider():
    global _PROVIDER
    if _PROVIDER is None:
        from PySide6.QtWidgets import QFileIconProvider
        _PROVIDER = QFileIconProvider()
    return _PROVIDER


def _in_well(mark: QPixmap, px: int, tone: QColor) -> QPixmap:
    """Present an already-rendered mark on the standard well.

    Tier 2 and tier 3 go through this so a row whose icon came from the
    installed binary, or from the neutral fallback, still lines up with the
    bundled marks beside it. A column where two of thirty icons sit on a
    different plate at a different size is the same "scavenged" reading the
    well exists to fix, and it is MORE obvious for the odd one out.
    """
    size, dpr = _device_px(px)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    _paint_well(p, size, tone)
    p.drawPixmap(_mark_rect(size).toRect(), mark)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _shell_pixmap(path: str, px: int) -> QPixmap | None:
    """The file's own shell icon, rasterised for the screen it will land on
    so it stays crisp at any scaling. Returns None when the extractor
    handed back its generic placeholder — see _generic_shell_key."""
    if not os.path.isfile(path):
        return None
    try:
        size, dpr = _device_px(px)
        if path.lower().endswith(".ico"):
            from PySide6.QtGui import QIcon
            icon = QIcon(path)
        else:
            icon = _icon_provider().icon(QFileInfo(path))
        if icon.isNull():
            return None
        pm = icon.pixmap(QSize(size, size))
        if pm.isNull():
            return None
        # Compared against a placeholder requested at the SAME device size:
        # these are raw image bytes, so a mismatched size never compares
        # equal and the guard would silently pass everything through.
        generic = _generic_shell_key(size)
        if generic is not None:
            try:
                if bytes(pm.toImage().constBits()) == generic:
                    return None       # the blank-page placeholder
            except Exception:
                pass
        pm.setDevicePixelRatio(dpr)
        return pm
    except Exception:
        return None


# ============================================================
#  2. THE BUNDLED BRAND MARK
# ============================================================
def _manifest() -> dict[str, dict]:
    """assets/appicons/manifest.json, written by tools/fetch_app_icons.py.
    A missing or unreadable manifest degrades to "no bundled marks" rather
    than raising — icons are decoration, and decoration must never be able
    to stop the installer UI from opening."""
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = {}
        path = resources.find_resource("assets/appicons/manifest.json")
        if path:
            try:
                with open(path, encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    _MANIFEST = loaded
            except (OSError, ValueError):
                _MANIFEST = {}
    return _MANIFEST


_RGBA_RE = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", re.I)


def _parse_color(value: str, fallback: str) -> QColor:
    """A theme colour token as a QColor, accepting BOTH "#rrggbb" and the
    CSS "rgba(r, g, b, a)" form the palette actually stores.

    Qt does not parse rgba() strings, and — the part that made this a real
    bug rather than a missing feature — QColor("rgba(...)") comes back
    INVALID while still reporting alpha() == 255. The guard here used to be
    `if surface.alpha() == 0`, which therefore never fired: every surface
    handed to the contrast guard was an invalid QColor, which behaves as
    pure black. Both themes were being solved against black, so the light
    theme's readability was decided from the wrong backdrop entirely.

    Parsed locally rather than by importing frontend.theme's to_qcolor:
    utils/ sits BELOW frontend/ in the import graph (theme <- animations <-
    widgets <- main), and reaching upward from here would invert it.
    """
    text = (value or "").strip()
    match = _RGBA_RE.fullmatch(text)
    if match:
        r, g, b, a = match.groups()
        color = QColor(int(r), int(g), int(b))
        if a is not None:
            color.setAlphaF(max(0.0, min(1.0, float(a))))
        return color
    color = QColor(text)
    return color if color.isValid() else QColor(fallback)


def _luminance(color: QColor) -> float:
    """WCAG relative luminance."""
    channels = []
    for raw in (color.redF(), color.greenF(), color.blueF()):
        channels.append(raw / 12.92 if raw <= 0.03928
                        else ((raw + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: QColor, b: QColor) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _readable_brand_color(brand: QColor, surface: QColor, dark: bool) -> QColor:
    """`brand`, walked along its own hue until it clears _MIN_CONTRAST
    against `surface` — see the module docstring's contrast-guard note.

    Lightness is stepped rather than solved analytically because HSL
    lightness and WCAG luminance are not the same curve; twenty small
    steps land within a hundredth of the floor and cost microseconds once
    per (app, theme) thanks to the pixmap cache.
    """
    if _contrast(brand, surface) >= _MIN_CONTRAST:
        return brand
    h, s, lightness, a = brand.getHslF()
    if h < 0:
        h = 0.0            # achromatic: getHslF reports hue -1
    for step in range(1, 21):
        moved = lightness + (0.05 * step if dark else -0.05 * step)
        candidate = QColor.fromHslF(h, s, max(0.0, min(1.0, moved)), a)
        if _contrast(candidate, surface) >= _MIN_CONTRAST:
            return candidate
    return QColor("#f2f4f8") if dark else QColor("#12151b")


# ============================================================
#  THE WELL — one plate every mark is presented on
# ============================================================
#: The mark's size inside the plaque, as a fraction of it. 20 in 36.
#:
#: EVERY MARK GETS THE SAME BOX, and that uniformity is the point rather
#: than a constraint. Brand SVGs do not agree on their own padding: some
#: are drawn edge-to-edge in their viewBox, some carry 15% of built-in air,
#: and a few are wordmark-shaped rather than square. Rendered "as large as
#: fits", the column came out as a row of marks at visibly different
#: optical sizes — which is the thing that reads as "these were scavenged"
#: however authentic each one is individually.
#:
#: Fixing the INNER box instead of the outer one is what makes them a set.
_MARK_RATIO = 20.0 / 36.0


def _keep_aspect(renderer: QSvgRenderer) -> None:
    """Letterbox a mark inside its box instead of stretching it to fill.

    QSvgRenderer.render(painter, rect) defaults to Qt.IgnoreAspectRatio: it
    scales the viewBox to the rect on each axis INDEPENDENTLY. Every box
    this module draws into is square (_mark_rect), and brand artwork is
    not — so a mark whose viewBox is not 1:1 was being DISTORTED, silently,
    on every paint.

    Measured across the bundled set, seven marks were arriving deformed:
    Java's cup at a 0.74 viewBox came out 35% too wide, Docker's whale at
    1.38 came out 38% too tall, and Node, the C++ hexagon, Brave's lion,
    Discord and Epic were all visibly off. That is the module's own rule —
    a wrong logo is worse than no logo — being broken by the renderer
    rather than by the source: the artwork committed to the repo is
    correct, and only the drawing of it was not.

    Setting the mode once here fixes every mark at once, including any
    added later, and costs nothing: a square mark is unaffected, because
    KeepAspectRatio and IgnoreAspectRatio agree when the ratios already
    match.
    """
    try:
        renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
    except AttributeError:
        # Older Qt without the setter — stretching is what it did before,
        # and a missing nicety must never stop the catalog from drawing.
        pass

#: Corner radius of the well, same fraction (8 in 36) — the squircle every
#: app store and both desktop platforms present an app icon in.
_WELL_RADIUS_RATIO = 8.0 / 36.0


def _well_color(surface: QColor | None, dark: bool) -> QColor:
    """The plate a mark sits on: a quiet neutral lift off the row.

    Dark mode lifts with white, light mode settles with black, and both at
    a weight low enough that the plate reads as a recess in the row rather
    than as a tile stuck on top of it. This is the RESTING tone — see
    _rescue_well, which brightens it for the marks that would otherwise
    disappear into it.
    """
    if dark:
        return QColor(255, 255, 255, 18)
    return QColor(0, 0, 0, 12)


def _rescue_well(renderer: QSvgRenderer, size: int,
                 surface: QColor | None, dark: bool) -> QColor:
    """The well tone for one mark, brightened when the mark needs it.

    THE GEOMETRY IS ALWAYS THE SAME AND ONLY THE TONE MOVES, which is the
    resolution of two requirements that look opposed: every icon should be
    presented identically, AND a near-black mark has to stay visible on a
    near-black canvas. Making the plate appear only for the marks that need
    rescuing (what this module did before) satisfies the second and breaks
    the first — the column ends up with tiles under some logos and not
    others, at different sizes, which is exactly the inconsistency the
    uniform well exists to remove.

    So the plate is unconditional and its COLOUR is measured. Ollama,
    Notion, Steam, 7-Zip and Epic are all essentially #000000 artwork; on
    obsidian they get the near-white plate an app store would give them,
    and every other mark keeps the quiet neutral.

    Near-white rather than pure: a hard #ffffff tile on the light theme's
    porcelain canvas reads as a hole punched in the row.
    """
    resting = _well_color(surface, dark)
    if surface is None:
        return resting
    luminance = _mark_luminance(renderer, size)
    if luminance is None:
        return resting
    # Measured against what the mark will ACTUALLY sit on: the resting
    # well composited over the row, not the row alone.
    plate = _composite(resting, surface)
    hi, lo = max(luminance, _luminance(plate)), min(luminance, _luminance(plate))
    if (hi + 0.05) / (lo + 0.05) >= _MIN_CONTRAST:
        return resting
    rescue = QColor("#f7f8fa")
    rescue.setAlphaF(0.96)
    return rescue


def _composite(over: QColor, under: QColor) -> QColor:
    """`over` blended onto opaque `under` — what the eye actually sees."""
    a = over.alphaF()
    return QColor(
        int(round(over.red() * a + under.red() * (1 - a))),
        int(round(over.green() * a + under.green() * (1 - a))),
        int(round(over.blue() * a + under.blue() * (1 - a))))


def _paint_well(p: QPainter, size: int, tone: QColor) -> None:
    """Fill the plate. `size` is in DEVICE pixels."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(tone)
    radius = size * _WELL_RADIUS_RATIO
    p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)


def _mark_rect(size: int) -> QRectF:
    """The centred box a mark is drawn into. `size` is in DEVICE pixels."""
    inner = size * _MARK_RATIO
    offset = (size - inner) / 2.0
    return QRectF(offset, offset, inner, inner)


def _tinted_mark(renderer: QSvgRenderer, size: int, tone: QColor) -> QPixmap:
    """A monochrome silhouette rendered and recoloured to `tone`, ON ITS
    OWN transparent pixmap.

    THE SEPARATE PIXMAP IS THE WHOLE POINT. CompositionMode_SourceIn keeps
    the DESTINATION's alpha and takes the source's colour — so a fill
    composited straight onto the icon painted the WELL as well, because the
    well is opaque everywhere under the mark's box. Every monochrome mark
    therefore rendered as a solid tinted SQUARE rather than as its own
    shape: Cursor shipped that way, and it is exactly the "generic
    placeholder" reading this module exists to prevent.

    Clipping to the mark's box does not help and was what the code tried:
    the box is precisely the region the well fills. Recolouring somewhere
    the well has not been drawn does help, and costs one small pixmap.

    `size` is in DEVICE pixels; the returned pixmap is the mark's INNER box
    (see _MARK_RATIO), ready to be drawn into _mark_rect.
    """
    box = _mark_rect(size).toRect()
    mark = QPixmap(max(1, box.width()), max(1, box.height()))
    mark.fill(Qt.GlobalColor.transparent)
    painter = QPainter(mark)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, mark.width(), mark.height()))
    # Now the only non-transparent pixels ARE the silhouette, so SourceIn
    # tints the shape and nothing else.
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(mark.rect(), tone)
    painter.end()
    return mark


def _brand_pixmap(app_id: str, px: int, tone: QColor,
                  surface: QColor | None = None,
                  dark: bool = True) -> QPixmap | None:
    """Render the bundled SVG at 2x.

    TWO KINDS OF MARK live in assets/appicons/, and the manifest's `color`
    flag says which this is:

      MONOCHROME (Simple Icons) — a single-path silhouette carrying no
      colour of its own. Recoloured to `tone` with a flat SourceIn
      composite over the rendered alpha: no per-path editing, identical
      handling for every mark, and it is what lets the contrast guard
      move a #000000 brand off a near-black canvas.

      FULL COLOUR (the `logos` / brand-logo sets) — the vendor's REAL
      artwork, gradients and all: VS Code's blue ribbon, Edge's swirl.
      Rendered exactly as drawn. Pushing one of these through the
      silhouette path would flatten a multi-stop gradient into a single
      blob — authentic artwork, destroyed on paint — so `color` marks skip
      the recolour entirely, and their legibility is solved by the backing
      plaque below instead of by rewriting their colours.
    """
    entry = _manifest().get(app_id)
    if not entry:
        return None
    path = resources.find_resource(f"assets/appicons/{entry.get('file', '')}")
    if not path or not os.path.isfile(path):
        return None
    try:
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            return None
        _keep_aspect(renderer)
        # DEVICE pixels while painting; the device-pixel-ratio is attached
        # only AFTER the last stroke. Setting it first would divide the
        # painter's logical coordinate space, so every rect below — sized
        # in device pixels — would overflow it and the mark would be
        # clipped to its top-left corner.
        size, dpr = _device_px(px)
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        full_colour = bool(entry.get("color"))
        # THE WELL IS UNCONDITIONAL and the mark's box is fixed — see
        # _rescue_well and _MARK_RATIO for why uniform geometry with a
        # measured TONE is the only arrangement that satisfies both
        # "present every icon identically" and "a black mark must stay
        # visible on a black canvas".
        #
        # WHICH well depends on which kind of mark, and the two must not be
        # swapped. Full-colour artwork keeps its own colours, so the SURFACE
        # has to move to rescue it (_rescue_well measures whether it needs
        # to). A monochrome silhouette is recoloured through the contrast
        # guard instead, which has ALREADY solved it against the resting
        # well — handing that one a rescue plate would put a near-white
        # mark on a near-white tile.
        if full_colour:
            _paint_well(p, size, _rescue_well(renderer, size, surface, dark))
            renderer.render(p, _mark_rect(size))
        else:
            _paint_well(p, size, _well_color(surface, dark))
            p.drawPixmap(_mark_rect(size).toRect(),
                         _tinted_mark(renderer, size, tone))
        p.end()
        pm.setDevicePixelRatio(dpr)
        return pm
    except Exception:
        return None


def _mark_luminance(renderer: QSvgRenderer, size: int) -> float | None:
    """Mean WCAG luminance of a rendered mark's OPAQUE pixels, or None.

    Measured rather than declared. The alternative — a per-brand "darkest
    tone" hint in the manifest — is a second set of colour data to keep in
    step with artwork that is fetched automatically, and it would be wrong
    the first time a vendor refreshed their logo. Rendering the real thing
    and reading it back is always current.

    Transparent pixels are excluded: a mark is mostly empty space inside
    its own bounding box, and averaging that in drags every logo toward
    the same middling number and defeats the test.
    """
    try:
        probe = QPixmap(size, size)
        probe.fill(Qt.GlobalColor.transparent)
        painter = QPainter(probe)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        image = probe.toImage()
    except Exception:
        return None

    total = 0.0
    counted = 0
    step = max(1, size // 24)          # ~24x24 samples is plenty for a mean
    for y in range(0, size, step):
        for x in range(0, size, step):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() < 128:
                continue
            total += _luminance(pixel)
            counted += 1
    if counted == 0:
        return None
    return total / counted


def _backing_plaque(renderer: QSvgRenderer, size: int,
                    surface: QColor | None) -> QColor | None:
    """A soft neutral plaque to sit a full-colour logo on, or None when the
    logo already reads against `surface`.

    The trick that rescues a monochrome silhouette cannot be used here:
    walking a brand's hue until it clears the floor is exactly what makes
    a recoloured silhouette legible, and exactly what would make real
    vendor artwork inauthentic. So the mark is left alone and the SURFACE
    moves instead — what macOS and every app store do when they sit an app
    icon on a light tile.

    Applied only when measurement says it is needed, so a vivid mark like
    Edge's swirl keeps the clean plaque-free look it already has on
    obsidian, while VS Code's ribbon — whose dark strokes vanish into the
    canvas — gets its tile.
    """
    if surface is None:
        return None
    luminance = _mark_luminance(renderer, size)
    if luminance is None:
        return None
    surface_luminance = _luminance(surface)
    hi, lo = max(luminance, surface_luminance), min(luminance, surface_luminance)
    if (hi + 0.05) / (lo + 0.05) >= _MIN_CONTRAST:
        return None
    # Near-white rather than pure: a hard #ffffff tile on the light theme's
    # porcelain canvas reads as a hole punched in the row.
    plaque = QColor("#f7f8fa")
    plaque.setAlphaF(0.96)
    return plaque


# ============================================================
#  3. THE NEUTRAL GLYPH
# ============================================================
def _neutral_pixmap(px: int, tone: QColor) -> QPixmap:
    """A soft rounded package mark — the honest "no logo available"
    state. Identical for every app that reaches it, deliberately: a mark
    that varies per app (the old letter monogram) reads as branding and
    invites the question "why is Epic Games a letter E?"."""
    # device pixels first, DPR attached last — see _brand_pixmap's note
    size, dpr = _device_px(px)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    body = QColor(tone)
    body.setAlphaF(0.55)
    pen_w = max(2.0, size * 0.055)
    from PySide6.QtGui import QPen
    p.setPen(QPen(body, pen_w))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # The same centred box every bundled mark is drawn into, shrunk by the
    # pen so the stroke stays inside it.
    box = _mark_rect(size).adjusted(pen_w / 2, pen_w / 2,
                                    -pen_w / 2, -pen_w / 2)
    p.drawRoundedRect(box, size * 0.10, size * 0.10)
    # a single horizontal seam — reads as a parcel, not as a blank frame
    p.drawLine(int(box.left()), int(box.center().y()),
               int(box.right()), int(box.center().y()))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


# ============================================================
#  PUBLIC ENTRY POINT
# ============================================================
def app_icon(app_name: str, px: int, t: dict, app_id: str = "") -> QPixmap:
    """The row icon for `app_name` (and `app_id`, when the caller has it).

    Cached per (id, name, size, theme, ratio). The theme is part of the key
    because both the brand recolour and the neutral glyph are solved
    against the current surface — see the contrast-guard note above.

    THE RATIO IS PART OF IT for the same reason the marks now follow the
    screen at all: a key without it hands a pixmap rasterised for the
    previous monitor straight back after the window is dragged to one with
    different scaling, and the whole catalog stays soft until the app is
    restarted. Cheap to key on and impossible to notice when wrong, which
    is the combination that argues for keying on it.
    """
    dark = t.get("name", "dark") == "dark"
    surface = _parse_color(t.get("dialog_bg", ""),
                           "#16181d" if dark else "#ffffff")
    key = (app_id, app_name, px, "d" if dark else "l", _screen_dpr())
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached

    pm = None
    entry = _manifest().get(app_id) if app_id else None
    if entry:
        if entry.get("color"):
            # Real vendor artwork: rendered as drawn. `tone` is unused on
            # this path, so the contrast guard is skipped here and the
            # WELL does the legibility work instead — moving the surface,
            # never the brand's own colours.
            pm = _brand_pixmap(app_id, px, QColor("#000000"), surface, dark)
        else:
            brand = QColor(entry.get("hex", "#000000"))
            if not brand.isValid():
                brand = QColor("#888888")
            pm = _brand_pixmap(app_id, px,
                               _readable_brand_color(brand, surface, dark),
                               surface, dark)
    if pm is None:
        path = _installed_icon_path(app_name)
        if path:
            shell = _shell_pixmap(path, px)
            if shell is not None:
                pm = _in_well(shell, px, _well_color(surface, dark))
    if pm is None:
        pm = _neutral_pixmap(px, QColor(t.get("text_faint", "#858d9d")))
        pm = _in_well(pm, px, _well_color(surface, dark))

    _PIXMAP_CACHE[key] = pm
    return pm
