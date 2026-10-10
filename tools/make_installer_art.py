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

  * THE HEADER MARK (WizardSmallImageFile) is the opposite: the bare
    mark on TRANSPARENCY, no plate. It sits directly on the wizard page,
    which is off-white under the windows11 style and near-black under the
    dark one, so anything with a background of its own would show as a
    rectangle in one of the two. Transparency is what lets one asset serve
    both, and the mark's cyan-to-indigo sweep clears both grounds on contrast.

THE MARK IS THE BRAND ASSET, NOT A REDRAWING. It is read from
assets/brand/pulse-mark-512.png, which tools/make_brand.py renders from the
same geometry (src/frontend/brand.py) as the .ico and the in-app mark — so
the wizard, the desktop icon and the window are one drawing. The crop
keeps every visible pixel (the live point's glow included — clipping it
leaves a hard edge), but is CENTRED on the solid shape (alpha > 64), so
the glow hanging off the right end does not shove the mark off-centre.

EVERY SIZE IS RENDERED, because Inno picks per-DPI from a comma-separated
list and scaling a 100% bitmap up to 200% is exactly the soft, fringed
result the modern style is meant to avoid.

Run:  python tools/make_brand.py && python tools/make_installer_art.py
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


_MARK = os.path.join(_ROOT, "assets", "brand", "pulse-mark-512.png")

#: Alpha above which a pixel counts as the mark's SOLID CORE, for the
#: purpose of centring it. Not used to modify the image.
_CORE_ALPHA = 64


def brand_glyph() -> Image.Image:
    """The Pulse mark, cropped to its solid extent. See the header."""
    if not os.path.isfile(_MARK):
        raise SystemExit(f"{os.path.relpath(_MARK, _ROOT)} is missing — "
                         "run tools/make_brand.py first.")
    mark_img = Image.open(_MARK).convert("RGBA")
    alpha = mark_img.getchannel("A")
    core = alpha.point(lambda v: 255 if v > _CORE_ALPHA else 0).getbbox()
    full = alpha.point(lambda v: 255 if v > 0 else 0).getbbox()
    if core is None or full is None:
        raise SystemExit("The brand mark is empty — re-run tools/make_brand.py.")
    # Widen the visible box symmetrically about the core's centre.
    cx, cy = (core[0] + core[2]) / 2, (core[1] + core[3]) / 2
    half_w = max(cx - full[0], full[2] - cx)
    half_h = max(cy - full[1], full[3] - cy)
    w, h = int(round(2 * half_w)), int(round(2 * half_h))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(mark_img.crop(full),
                        (int(round(full[0] - (cx - half_w))),
                         int(round(full[1] - (cy - half_h)))))
    return out


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

    mark_w = int(w * 0.74)
    star = glyph.copy()
    star.thumbnail((mark_w, mark_w), Image.LANCZOS)
    sx, sy = (w - star.width) // 2, int(h * 0.30) - star.height // 2

    img.alpha_composite(
        _glow(size, (w // 2, sy + star.height // 2), int(mark_w * 0.80)))
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
    """The bare mark, centred on transparency, with a little breathing room
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
    glyph = brand_glyph()
    print(f"brand mark: {glyph.width}x{glyph.height}")

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
