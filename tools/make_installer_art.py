"""
tools/make_installer_art.py

Generates the Setup wizard's branding images into assets/installer/.

WHY THESE EXIST AT ALL. Inno Setup does not ship "no image" as a default —
it ships ITS OWN, and with WizardStyle=modern that is the stock teal
abstract graphic every Inno installer since 2018 has carried. pulse.iss
never set WizardImageFile or WizardSmallImageFile, so Pulse was shipping
that stock artwork by omission: there was nothing to delete, only something
to override. These are the override.

TWO IMAGES, TWO DIFFERENT JOBS, AND THEY ARE BUILT DIFFERENTLY:

  * THE SIDEBAR BANNER (WizardImageFile) is a self-contained dark panel —
    background, glow, mark and wordmark, all its own. It is deliberately
    dark in BOTH light and dark wizard appearances, because it is a brand
    surface rather than a page element: the same way a dark app tile reads
    as intentional on a light desktop. That is also why it needs no
    DynamicDark twin.

  * THE HEADER MARK (WizardSmallImageFile) is the opposite: the bare star
    glyph on TRANSPARENCY, no plate. It sits directly on the wizard page,
    which is off-white under the windows11 style and near-black under the
    dark one, so anything with a background of its own would show as a
    rectangle in one of the two. Transparency is what lets one asset serve
    both, and the glyph's blue clears both grounds on contrast.

THE GLYPH IS EXTRACTED, NOT REDRAWN. assets/pulse.ico is the brand asset;
hand-drawing "a four-pointed star that looks like Pulse's" would be an
invented mark sitting where the real one belongs — the same rule
src/utils/appicons.py applies to third-party logos, turned on ourselves.

THE MATTE AND THE CROP ANSWER TWO DIFFERENT QUESTIONS, and conflating them
is what made the first attempt look cheap. Measured on the 256px layer the
tile runs 22-31 and the star 184-224, so a wide luminance ramp separates
them with room to spare — but the tile's ROUNDED CORNERS antialias against
transparency and leave ~1,100 pixels of near-invisible fringe out at the
edges. Those pixels are far too faint to see and quite enough to define a
bounding box, so cropping to "any non-zero alpha" returned the whole
236px tile and the mark came out padded and undersized.

So the crop is measured against the SOLID CORE (alpha > 64), which finds
the star's true 154px extent, while the pixels kept inside it carry the
FULL alpha ramp. Tightening the ramp instead would have worked on the
fringe and cost the glyph its antialiasing: at a narrow 110-160 the edge
went visibly stippled against an off-white page.

EVERY SIZE IS RENDERED, because Inno picks per-DPI from a comma-separated
list and scaling a 100% bitmap up to 200% is exactly the soft, fringed
result the modern style is meant to avoid.

Run:  python tools/make_installer_art.py
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ICON = os.path.join(_ROOT, "assets", "pulse.ico")
_OUT = os.path.join(_ROOT, "assets", "installer")

#: Pulse's own dark palette, quoted from src/frontend/theme.py so the Setup
#: wizard and the app it installs are demonstrably the same product.
BG_TOP = (11, 13, 16)          # near bg_solid #090a0b, lifted slightly
BG_BOTTOM = (21, 24, 30)       # near card #121418
ACCENT = (138, 158, 219)       # accent #8a9edb
TEXT = (238, 241, 246)         # text #eef1f6

#: Inno's own recommended sizes. 100% first — that one is the fallback for
#: any DPI the list does not cover.
BANNER_SIZES = [(164, 314), (205, 393), (246, 471), (287, 550), (328, 628)]
MARK_SIZES = [(55, 58), (69, 73), (83, 87), (97, 102), (110, 116)]

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\seguisb.ttf",     # Segoe UI Semibold
    r"C:\Windows\Fonts\segoeui.ttf",     # Segoe UI
    r"C:\Windows\Fonts\arial.ttf",
]


def _font(px: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, px)
    raise SystemExit(
        "No usable TrueType font found. This tool runs on Windows, where "
        "Segoe UI is always present; add a path to _FONT_CANDIDATES if you "
        "are running it somewhere else.")


#: The luminance ramp that separates the star from its tile. Wide on
#: purpose — see the header: a narrow ramp stipples the glyph's edge, and
#: the corner fringe it would otherwise exclude is handled by the crop
#: instead.
_MATTE_LO, _MATTE_HI = 60, 190

#: Alpha above which a pixel counts as the glyph's SOLID CORE, for the
#: purpose of finding its extent. Not used to modify the image.
_CORE_ALPHA = 64


def star_glyph() -> Image.Image:
    """The four-pointed mark, alpha-matted off its tile. See the header."""
    icon = Image.open(_ICON)
    icon.size = (256, 256)               # the largest layer in the .ico
    icon = icon.convert("RGBA")
    r, g, b, a = icon.split()
    lum = Image.merge("RGB", (r, g, b)).convert("L")
    span = _MATTE_HI - _MATTE_LO
    matte = lum.point(
        lambda v: 0 if v <= _MATTE_LO else
        (255 if v >= _MATTE_HI else int(255 * (v - _MATTE_LO) / span)))
    alpha = ImageChops.multiply(matte, a)

    # The box comes from the core; the pixels keep the whole ramp.
    core = alpha.point(lambda v: 255 if v > _CORE_ALPHA else 0)
    bbox = core.getbbox()
    if bbox is None:
        raise SystemExit("The glyph matte came out empty — pulse.ico changed shape.")
    if (bbox[2] - bbox[0]) > 200:
        raise SystemExit(
            f"The glyph matte is {bbox[2] - bbox[0]}px wide of a 256px icon — "
            "it has caught the tile as well as the star, and every image "
            "below would come out padded and undersized.")
    return Image.merge("RGBA", (r, g, b, alpha)).crop(bbox)


def _gradient(size: tuple[int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (1, h))
    draw = ImageDraw.Draw(base)
    for y in range(h):
        t = y / max(1, h - 1)
        draw.point((0, y), tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)))
    return base.resize(size, Image.BILINEAR).convert("RGBA")


def _glow(size: tuple[int, int], centre: tuple[int, int], radius: int) -> Image.Image:
    """A soft accent bloom behind the mark, drawn at 4x and blurred down so
    the falloff has no banding at 100% scale."""
    w, h = size
    layer = Image.new("L", (w * 2, h * 2), 0)
    d = ImageDraw.Draw(layer)
    cx, cy, rr = centre[0] * 2, centre[1] * 2, radius * 2
    steps = 42
    for i in range(steps):
        t = i / steps
        d.ellipse([cx - rr * (1 - t), cy - rr * (1 - t),
                   cx + rr * (1 - t), cy + rr * (1 - t)], fill=int(70 * t))
    layer = layer.filter(ImageFilter.GaussianBlur(rr * 0.18)).resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", size, ACCENT + (0,))
    out.putalpha(layer)
    return out


def banner(size: tuple[int, int], glyph: Image.Image) -> Image.Image:
    w, h = size
    img = _gradient(size)

    star_w = int(w * 0.46)
    star = glyph.copy()
    star.thumbnail((star_w, star_w), Image.LANCZOS)
    sx, sy = (w - star.width) // 2, int(h * 0.30) - star.height // 2

    img.alpha_composite(
        _glow(size, (w // 2, sy + star.height // 2), int(star_w * 0.95)))
    img.alpha_composite(star, (sx, sy))

    draw = ImageDraw.Draw(img)
    # Letterspaced wordmark, drawn glyph by glyph: PIL has no tracking, and
    # an untracked "PULSE" under a symmetrical mark reads cramped.
    text = "PULSE"
    fs = max(11, int(w * 0.135))
    font = _font(fs)
    track = max(1, int(fs * 0.18))
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + track * (len(text) - 1)
    x = (w - total) / 2
    y = sy + star.height + int(h * 0.045)
    for ch, cw in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=TEXT)
        x += cw + track

    # A hairline in the accent, at the wordmark's width — the same "one
    # accent, flat surfaces" rule the app's own chrome follows.
    rule_y = int(y + fs * 1.75)
    rule_w = int(total * 0.86)
    draw.rectangle([(w - rule_w) // 2, rule_y, (w + rule_w) // 2, rule_y],
                   fill=ACCENT + (150,))
    return img.convert("RGB")     # opaque panel: no alpha wanted here


def mark(size: tuple[int, int], glyph: Image.Image) -> Image.Image:
    """The bare glyph, centred on transparency, with a little breathing room
    so it never touches the header's edge."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    inner = int(min(w, h) * 0.84)
    star = glyph.copy()
    star.thumbnail((inner, inner), Image.LANCZOS)
    img.alpha_composite(star, ((w - star.width) // 2, (h - star.height) // 2))
    return img


def main() -> int:
    os.makedirs(_OUT, exist_ok=True)
    glyph = star_glyph()
    print(f"glyph matted from pulse.ico: {glyph.width}x{glyph.height}")

    written = []
    for size in BANNER_SIZES:
        name = f"wizard-banner-{size[0]}x{size[1]}.png"
        # PNG, not BMP. The panel is opaque and has no alpha to preserve, so
        # BMP would render identically — and cost 1.8MB against 100KB for
        # the same five images, on every regeneration, forever. The usual
        # argument for BMP is that every Inno build reads it; that does not
        # apply here, because this artwork is only referenced by a .iss that
        # already requires 6.6+ for its dark mode and would not compile on
        # an older one anyway.
        banner(size, glyph).save(os.path.join(_OUT, name), optimize=True)
        written.append(name)
    for size in MARK_SIZES:
        name = f"wizard-mark-{size[0]}x{size[1]}.png"
        # PNG for the mark: the transparency IS the feature (see the header).
        mark(size, glyph).save(os.path.join(_OUT, name), optimize=True)
        written.append(name)

    for name in written:
        path = os.path.join(_OUT, name)
        print(f"  {name:34} {os.path.getsize(path):>8,} bytes")
    print(f"\n{len(written)} file(s) -> {os.path.relpath(_OUT, _ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
