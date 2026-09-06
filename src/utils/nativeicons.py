"""
src/utils/nativeicons.py

THE APPLICATION'S OWN ICON, READ OUT OF ITS OWN BINARY.

WHY THIS EXISTS RATHER THAN QFileIconProvider
    appicons.py's tier 2 has always been able to read an installed app's
    icon, through QFileIconProvider. That is the right idea and the wrong
    resolution: on Windows it asks the shell for the SHGFI_LARGEICON
    variant, which is 32x32, and every row in this app draws its mark
    into a 36px well — on a 150% display, 54 device pixels. So the one
    tier that shows the VENDOR'S REAL ARTWORK was the one tier delivering
    a blurry upscale, and it got worse the better the user's monitor was.

    Windows has carried a 256x256 icon for every well-behaved binary
    since Vista. It is simply not reachable through Qt: the shell exposes
    it through IImageList (SHIL_JUMBO), which Qt6 does not wrap at all —
    QtWinExtras and its QtWin::fromHICON went away with Qt5.

    So this module goes and gets it: SHGetFileInfoW for the system image
    list index, SHGetImageList for the jumbo list, and a hand-rolled
    HICON -> QImage conversion because there is no longer a supported one
    in the framework.

THE FALLBACK LADDER, and every rung is load-bearing:

    1. SHIL_JUMBO (256px)      the real artwork, for anything modern
    2. SHIL_EXTRALARGE (48px)  older binaries with no 256px frame
    3. ExtractIconExW (32px)   binaries the shell will not index at all,
                               which includes paths on a drive the shell
                               has no association handler for
    4. None                    the caller draws its own glyph

    Rung 3 matters more than its size suggests. SHGetFileInfoW consults
    the shell's association layer, and that layer answers for FILE TYPES
    — hand it a path it cannot classify and it returns the generic
    document page rather than failing. ExtractIconExW does not ask the
    shell anything; it opens the file and reads its RT_GROUP_ICON
    resource, so it still answers for a binary the shell has given up on.

WHAT IS DELIBERATELY NOT HERE
    Any judgement about whether the icon is GOOD. The generic-placeholder
    rejection lives in appicons.py, where the comparison key already
    exists and where the decision belongs — this module's job is to
    return the best pixels Windows will give up for a path, and nothing
    else. It has no opinion about theming, wells, or which tier should
    win.

HANDLE HYGIENE IS THE WHOLE RISK. Every HICON, HBITMAP and HDC created
here is destroyed in a finally block. An icon extractor that leaks one
GDI object per row leaks a few hundred per Update Center scan, and the
symptom is not a crash in this file — it is the whole process failing to
create any window at all, several minutes later, at the 10,000-handle
per-process GDI ceiling.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtGui import QImage, QPixmap

#: Set once, on the first call, to the reason this module cannot work —
#: or to "" when it can. Read by the diagnostics in tests; nothing in the
#: app branches on it, because every entry point already returns None.
UNAVAILABLE_REASON: str | None = None

_WIN = sys.platform == "win32"

# --- shell constants -------------------------------------------------
_SHGFI_ICON = 0x000000100
_SHGFI_SYSICONINDEX = 0x000004000
_SHGFI_LARGEICON = 0x000000000
_SHGFI_USEFILEATTRIBUTES = 0x000000010

#: The system image lists, largest first. SHIL_JUMBO is 256px on every
#: build that has it; SHIL_EXTRALARGE is 48px and is what a binary
#: carrying only the classic frames resolves to.
_SHIL_EXTRALARGE = 0x2
_SHIL_JUMBO = 0x4

_ILD_TRANSPARENT = 0x00000001

#: IImageList. The GUID is the one SHGetImageList expects; it is not
#: derivable from anything and is written out here rather than being
#: fetched from a wrapper that no longer ships.
_IID_IImageList = "{46EB5926-582E-4017-9FDF-E8998DAA0950}"

_BI_RGB = 0
_DIB_RGB_COLORS = 0


#: Guards _declare_signatures, which is idempotent but not free.
_SIGNATURES_DECLARED = False


def _declare_signatures(ctypes, wintypes) -> None:
    """Pin argtypes/restypes on every Win32 function this module calls.

    NOT OPTIONAL, AND NOT MERELY TIDY. ctypes assumes a 32-bit C int for
    every undeclared argument and return value. On 64-bit Windows a GDI
    or icon HANDLE read back out of a structure is a Python int wider
    than that, so passing one to an undeclared function raises

        ArgumentError: argument 1: OverflowError: int too long to convert

    ...for SOME handles and not others, because whether a given handle
    happens to fit in 32 bits is luck. Measured: notepad.exe extracted
    perfectly while explorer.exe, cmd.exe and git.exe all raised, in the
    same process, on the same call path. That is the worst shape a bug
    can have — it looks like "those binaries have no icon" and it moves
    between runs.

    The same applies to returns: SHGetFileInfoW hands back a DWORD_PTR
    and an undeclared HRESULT loses the high bit that distinguishes
    failure from success.

    Struct pointers are declared as c_void_p rather than as
    POINTER(<struct>) because the structures are defined inside the
    functions that use them; byref() satisfies c_void_p, and the
    alternative is hoisting four structure definitions to module scope
    to buy nothing.
    """
    global _SIGNATURES_DECLARED
    if _SIGNATURES_DECLARED:
        return
    from ctypes import POINTER, c_int, c_void_p

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32 = ctypes.windll.shell32

    user32.GetIconInfo.restype = wintypes.BOOL
    user32.GetIconInfo.argtypes = [wintypes.HICON, c_void_p]
    user32.DestroyIcon.restype = wintypes.BOOL
    user32.DestroyIcon.argtypes = [wintypes.HICON]

    gdi32.GetObjectW.restype = c_int
    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, c_int, c_void_p]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.GetDIBits.restype = c_int
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                                wintypes.UINT, c_void_p, c_void_p,
                                wintypes.UINT]

    shell32.ExtractIconExW.restype = wintypes.UINT
    shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, c_int,
                                       POINTER(wintypes.HICON),
                                       POINTER(wintypes.HICON), wintypes.UINT]
    shell32.SHGetFileInfoW.restype = ctypes.c_size_t
    shell32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                       c_void_p, wintypes.UINT, wintypes.UINT]
    shell32.SHGetImageList.restype = ctypes.HRESULT
    shell32.SHGetImageList.argtypes = [c_int, c_void_p, POINTER(c_void_p)]
    ctypes.windll.ole32.CLSIDFromString.restype = ctypes.HRESULT
    ctypes.windll.ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR,
                                                    c_void_p]
    _SIGNATURES_DECLARED = True


def _fail(reason: str) -> None:
    global UNAVAILABLE_REASON
    if UNAVAILABLE_REASON is None:
        UNAVAILABLE_REASON = reason


def _available() -> bool:
    if not _WIN:
        _fail("not Windows")
        return False
    return True


def executable_from_command(command: str) -> str | None:
    """The binary out of a Windows command line, or None.

    A startup entry's `Command` is not a path — it is whatever an
    installer wrote into a Run key, and the shapes are all different:

        "C:\\Program Files\\App\\app.exe" --minimized
        C:\\Windows\\System32\\rundll32.exe C:\\path\\thing.dll,Entry
        C:\\Program Files\\App\\app.exe /background

    THE UNQUOTED FORM WITH SPACES IS THE HARD ONE, and it is also the
    common one: splitting on the first space turns "C:\\Program
    Files\\App\\app.exe /background" into "C:\\Program", which exists on
    no machine. So an unquoted string is walked token by token and the
    longest LEADING run that names a real file wins — which is exactly
    how Windows itself resolves these, and the reason a malicious
    C:\\Program.exe is a classic privilege-escalation trick.

    Returns None rather than guessing when nothing resolves; the caller
    then draws its fallback glyph, which is a better outcome than
    extracting the icon of the wrong file.
    """
    if not command:
        return None
    text = command.strip()
    if not text:
        return None

    # Quoted: the first quoted run IS the path, whatever follows it.
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 1:
            candidate = os.path.expandvars(text[1:end])
            return candidate if os.path.isfile(candidate) else None
        return None

    expanded = os.path.expandvars(text)
    # The whole string first — a bare path with no arguments is the
    # commonest case and needs no walking.
    if os.path.isfile(expanded):
        return expanded

    parts = expanded.split(" ")
    for count in range(len(parts), 0, -1):
        candidate = " ".join(parts[:count]).strip()
        if not candidate:
            continue
        if os.path.isfile(candidate):
            return candidate
        # ".exe" written without its extension, which some Run keys do.
        if not os.path.splitext(candidate)[1] and os.path.isfile(candidate + ".exe"):
            return candidate + ".exe"
    return None


def _hicon_to_image(hicon, ctypes, wintypes) -> QImage | None:
    """One HICON -> a QImage, at the icon's own size.

    Windows hands back TWO bitmaps in an ICONINFO: the colour plane and a
    1-bit mask. A modern 32bpp icon carries its transparency in the
    colour plane's alpha channel and the mask is redundant; a classic
    icon has no alpha at all, and its colour plane comes back fully
    opaque with the shape living entirely in the mask. Reading only the
    colour plane therefore renders a pre-Vista icon as a correct picture
    inside an opaque black rectangle — which is worse than no icon,
    because it looks deliberate.

    So the alpha channel is INSPECTED, and the mask is applied only when
    it turns out to be empty.
    """
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL),
                    ("xHotspot", wintypes.DWORD),
                    ("yHotspot", wintypes.DWORD),
                    ("hbmMask", wintypes.HBITMAP),
                    ("hbmColor", wintypes.HBITMAP)]

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", wintypes.LONG),
                    ("bmWidth", wintypes.LONG),
                    ("bmHeight", wintypes.LONG),
                    ("bmWidthBytes", wintypes.LONG),
                    ("bmPlanes", wintypes.WORD),
                    ("bmBitsPixel", wintypes.WORD),
                    ("bmBits", ctypes.c_void_p)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                    ("bmiColors", wintypes.DWORD * 3)]

    info = ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(info)):
        return None

    hdc = None
    try:
        source = info.hbmColor or info.hbmMask
        if not source:
            return None
        bitmap = BITMAP()
        if not gdi32.GetObjectW(source, ctypes.sizeof(BITMAP),
                                ctypes.byref(bitmap)):
            return None
        width = int(bitmap.bmWidth)
        # A mask-only (monochrome) icon stores the AND and XOR planes
        # stacked, so its bitmap is twice the icon's real height.
        height = int(bitmap.bmHeight if info.hbmColor else bitmap.bmHeight // 2)
        if width <= 0 or height <= 0:
            return None

        hdc = gdi32.CreateCompatibleDC(None)
        if not hdc:
            return None

        header = BITMAPINFO()
        header.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.bmiHeader.biWidth = width
        # NEGATIVE height asks GDI for a TOP-DOWN buffer. A DIB is
        # bottom-up by default and QImage is not, so without this every
        # icon arrives vertically mirrored.
        header.bmiHeader.biHeight = -height
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = _BI_RGB

        stride = width * 4
        buffer = ctypes.create_string_buffer(stride * height)
        if not gdi32.GetDIBits(hdc, source, 0, height, buffer,
                               ctypes.byref(header), _DIB_RGB_COLORS):
            return None

        pixels = bytearray(buffer.raw)
        if info.hbmColor and not any(pixels[3::4]):
            # Fully transparent colour plane = a classic icon with no
            # alpha. Recover the shape from the mask, where a SET bit
            # means "leave the background alone" — i.e. transparent.
            mask_buffer = ctypes.create_string_buffer(stride * height)
            if info.hbmMask and gdi32.GetDIBits(
                    hdc, info.hbmMask, 0, height, mask_buffer,
                    ctypes.byref(header), _DIB_RGB_COLORS):
                mask = mask_buffer.raw
                for i in range(0, len(pixels), 4):
                    pixels[i + 3] = 0 if mask[i] else 255
            else:
                for i in range(3, len(pixels), 4):
                    pixels[i] = 255

        # .copy() because QImage would otherwise reference the bytes
        # object for its whole life, and this one is a local.
        image = QImage(bytes(pixels), width, height, stride,
                       QImage.Format.Format_ARGB32).copy()
        return image if not image.isNull() else None
    finally:
        if hdc:
            gdi32.DeleteDC(hdc)
        if info.hbmColor:
            gdi32.DeleteObject(info.hbmColor)
        if info.hbmMask:
            gdi32.DeleteObject(info.hbmMask)


def _image_list_icon(path: str, shil: int, ctypes, wintypes) -> QImage | None:
    """The shell's own icon for `path` out of one system image list."""
    from ctypes import POINTER, byref, c_int, c_void_p, sizeof

    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
    ole32 = ctypes.windll.ole32

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [("hIcon", wintypes.HICON),
                    ("iIcon", c_int),
                    ("dwAttributes", wintypes.DWORD),
                    ("szDisplayName", wintypes.WCHAR * 260),
                    ("szTypeName", wintypes.WCHAR * 80)]

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_byte * 8)]

    info = SHFILEINFOW()
    if not shell32.SHGetFileInfoW(path, 0, byref(info), sizeof(info),
                                  _SHGFI_SYSICONINDEX):
        return None

    guid = GUID()
    if ole32.CLSIDFromString(_IID_IImageList, byref(guid)) != 0:
        return None

    image_list = c_void_p()
    if shell32.SHGetImageList(shil, byref(guid), byref(image_list)) != 0:
        return None
    if not image_list:
        return None

    hicon = wintypes.HICON()
    try:
        # IImageList::GetIcon IS VTABLE SLOT 10, and getting this wrong is
        # not a failed call — it is a DIFFERENT call. IImageList derives
        # from IUnknown, so slots 0-2 are QueryInterface/AddRef/Release
        # and the interface's own methods start at 3: Add, ReplaceIcon,
        # SetOverlayImage, Replace, AddMasked, Draw, Remove, GetIcon.
        #
        # Slot 9 is Remove(int i). Calling it with GetIcon's three
        # arguments is how this was first written, and Windows answered
        # E_INVALIDARG — which is the good outcome. The bad one was
        # available: Remove's signature is satisfied by the first
        # argument alone, and the object it removes from is the SHELL'S
        # OWN system image list, shared by every process on the desktop.
        #
        # Called through the vtable because Qt6 ships no IImageList
        # wrapper and comtypes would be a dependency for one method.
        vtable = ctypes.cast(image_list,
                             POINTER(POINTER(c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, c_void_p, c_int, wintypes.UINT,
            POINTER(wintypes.HICON))
        get_icon = prototype(vtable[10])
        if get_icon(image_list, info.iIcon, _ILD_TRANSPARENT,
                    byref(hicon)) != 0:
            return None
        if not hicon:
            return None
        return _hicon_to_image(hicon, ctypes, wintypes)
    finally:
        if hicon:
            user32.DestroyIcon(hicon)
        # IUnknown::Release is vtable slot 2.
        try:
            vtable = ctypes.cast(image_list,
                                 POINTER(POINTER(c_void_p))).contents
            release = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)(vtable[2])
            release(image_list)
        except Exception:
            pass


def _extracted_icon(path: str, ctypes, wintypes) -> QImage | None:
    """ExtractIconExW — the rung that does not ask the shell anything.

    Reads the binary's own RT_GROUP_ICON resource, so it still answers
    for a file the association layer has no handler for. 32x32 is all it
    offers, which is why it is last.
    """
    from ctypes import byref

    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32

    large = wintypes.HICON()
    small = wintypes.HICON()
    count = shell32.ExtractIconExW(path, 0, byref(large), byref(small), 1)
    if count < 1:
        return None
    try:
        handle = large or small
        if not handle:
            return None
        return _hicon_to_image(handle, ctypes, wintypes)
    finally:
        if large:
            user32.DestroyIcon(large)
        if small:
            user32.DestroyIcon(small)


def generic_image() -> QImage | None:
    """Windows' icon for a file type it does not recognise.

    THE COMPARISON KEY FOR A GUARD THAT WOULD OTHERWISE HAVE LAPSED.
    appicons rejects the shell's blank-page placeholder rather than
    showing it as though it were an app's own icon — the defect that put
    Steam and iTunes into a row of real logos as white pages. That guard
    compares raw image bytes against QFileIconProvider's File icon, which
    only works while QFileIconProvider is the thing producing the pixmap.
    Once this module answers first, a generic icon that came back through
    THIS path would not match Qt's rendering of the same idea, and would
    sail past a check that looks like it is still running.

    SHGFI_USEFILEATTRIBUTES is what makes this answerable without a file:
    the shell is asked about a NAME and an attribute set rather than
    about the disk, so a made-up extension nothing claims returns the
    generic document icon with no I/O and nothing to clean up.
    """
    if not _available():
        return None

    import ctypes
    from ctypes import wintypes

    try:
        _declare_signatures(ctypes, wintypes)
    except Exception:                # pragma: no cover - defensive
        return None

    from ctypes import POINTER, byref, c_int, c_void_p, sizeof

    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [("hIcon", wintypes.HICON),
                    ("iIcon", c_int),
                    ("dwAttributes", wintypes.DWORD),
                    ("szDisplayName", wintypes.WCHAR * 260),
                    ("szTypeName", wintypes.WCHAR * 80)]

    _FILE_ATTRIBUTE_NORMAL = 0x80
    info = SHFILEINFOW()
    hicon = None
    try:
        if not shell32.SHGetFileInfoW(
                "pulse-icon-probe.pulseunknowntype", _FILE_ATTRIBUTE_NORMAL,
                byref(info), sizeof(info),
                _SHGFI_ICON | _SHGFI_LARGEICON | _SHGFI_USEFILEATTRIBUTES):
            return None
        hicon = info.hIcon
        if not hicon:
            return None
        return _hicon_to_image(hicon, ctypes, wintypes)
    except Exception:
        return None
    finally:
        if hicon:
            user32.DestroyIcon(hicon)


def icon_image(path: str) -> QImage | None:
    """The best icon Windows will give up for `path`, or None.

    Returned at the icon's OWN size — 256, 48 or 32 — so the caller can
    scale once, to the device size it actually needs, instead of
    inheriting whatever this happened to find.

    EVERY FAILURE IS None. There is no error path a row can act on: a
    missing icon means "draw the glyph instead", and that is true whether
    the file is gone, the shell refused it, or the COM call failed.
    """
    if not _available():
        return None
    if not path or not os.path.isfile(path):
        return None

    import ctypes
    from ctypes import wintypes

    try:
        _declare_signatures(ctypes, wintypes)
    except Exception as exc:            # pragma: no cover - defensive
        _fail(f"signature declaration failed: {exc}")
        return None

    for shil in (_SHIL_JUMBO, _SHIL_EXTRALARGE):
        try:
            image = _image_list_icon(path, shil, ctypes, wintypes)
        except Exception:
            image = None
        if image is not None and not image.isNull():
            return image
    try:
        return _extracted_icon(path, ctypes, wintypes)
    except Exception:
        return None


def icon_pixmap(path: str, device_px: int) -> QPixmap | None:
    """`icon_image`, scaled to `device_px` square.

    Scaled DOWN from the largest frame Windows has rather than up from a
    32px one, which is the entire reason this module exists. The caller
    passes DEVICE pixels — the logical size times the screen's ratio —
    and owns setting devicePixelRatio on the result.
    """
    from PySide6.QtCore import Qt

    image = icon_image(path)
    if image is None or image.isNull():
        return None
    if image.width() != device_px or image.height() != device_px:
        image = image.scaled(
            device_px, device_px,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
    pixmap = QPixmap.fromImage(image)
    return pixmap if not pixmap.isNull() else None
