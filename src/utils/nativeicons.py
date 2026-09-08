"""
src/utils/nativeicons.py

THE APPLICATION'S OWN ICON — AND, FIRST, WHICH APPLICATION THAT IS.

TWO HALVES, AND THE SECOND ONE CAME LATER (v10.12). This module began as
an icon EXTRACTOR: hand it the path of a binary and it returns the best
pixels Windows will give up for it. That is still the bottom half of the
file and it is unchanged.

What it could not do was answer the question the callers actually have,
which is not "what is this .exe's icon" but "what does this STARTUP ENTRY
look like". Those are the same question only for a Run key naming a
binary, and that is not most of the list:

    A STARTUP-FOLDER ENTRY IS A SHORTCUT. Its `Command` is the path of a
    `.lnk`, which is a file, so the old resolver returned it happily and
    the extractor obliged — with the shell's rendering of a SHORTCUT,
    which is the target's artwork carrying the little arrow overlay. A
    column of those says "these are links" in a list where that is never
    the interesting fact, and for a link to something uninstalled it says
    it over a blank page.

    A STORE APP HAS NO BINARY TO POINT AT. It is addressed as
    `shell:AppsFolder\\<family>!<app>`, and even when a Run key does name
    the .exe inside %ProgramFiles%\\WindowsApps, that binary usually
    carries no icon resource at all — a packaged app declares its artwork
    as PNG files in AppxManifest.xml. So every rung of the ladder below
    succeeded and returned Windows' generic application placeholder.

So the top half of this file resolves, and the bottom half extracts. See
resolve_command for the order and CommandTarget for what comes back.

THE EXTRACTOR: WHY IT EXISTS RATHER THAN QFileIconProvider
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
import re
import sys
from typing import NamedTuple

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

# --- shell link (.lnk) -----------------------------------------------
#: CLSID_ShellLink and the two interfaces needed to read one. Written out
#: for the same reason _IID_IImageList is: they are not derivable, and
#: the wrapper that used to supply them does not ship any more.
_CLSID_ShellLink = "{00021401-0000-0000-C000-000000000046}"
_IID_IShellLinkW = "{000214F9-0000-0000-C000-000000000046}"
_IID_IPersistFile = "{0000010B-0000-0000-C000-000000000046}"

_CLSCTX_INPROC_SERVER = 0x1
_COINIT_APARTMENTTHREADED = 0x2
#: CoInitializeEx when COM is already up in the OTHER threading model.
#: Not a failure for an in-proc server, and NOT balanced by a
#: CoUninitialize — see _com_scope.
_RPC_E_CHANGED_MODE = -2147417850          # 0x80010106
_STGM_READ = 0x0

#: IShellLinkW::GetPath flags. 0 is the resolved long path, which is what
#: an icon extractor wants; SLGP_RAWPATH is the string as stored, still
#: carrying %ENVIRONMENT% variables, and is the fallback for a link whose
#: target the shell declines to resolve.
_SLGP_RAWPATH = 0x4

#: Vtable slots. IUnknown owns 0-2 in every interface.
_VT_IShellLinkW_GetPath = 3
_VT_IPersistFile_Load = 5

#: Where Windows records every installed package and, crucially, its
#: PackageRootFolder. READABLE WITHOUT ELEVATION, which is the whole
#: reason the lookup goes through the registry rather than through the
#: file system: %ProgramFiles%\WindowsApps refuses a directory listing to
#: everything but TrustedInstaller, so globbing for a package folder
#: fails on exactly the machines this feature is for. Traversing INTO a
#: known package folder is allowed, so once the registry has named one,
#: its manifest and its assets read normally.
_APPX_REPOSITORY = (r"Software\Classes\Local Settings\Software\Microsoft"
                    r"\Windows\CurrentVersion\AppModel\Repository\Packages")

#: The logo attributes an AppxManifest can declare, best first.
#:
#: Square44x44Logo IS THE APP LIST ICON — the artwork Windows itself puts
#: beside the app in Start and on the taskbar — so it is the right answer
#: for a row that is trying to look like the Start menu. The others are
#: the tile and Store artwork, taken only when the first is absent.
_APPX_LOGO_ATTRS = ("Square44x44Logo", "Logo", "Square150x150Logo",
                    "Square71x71Logo", "StoreLogo")

_APPX_LOGO_RE = re.compile(
    r'\b(' + "|".join(_APPX_LOGO_ATTRS) + r')\s*=\s*"([^"]+)"')

#: `Square44x44Logo.targetsize-256_altform-unplated.png` -> 256.
#: `Square44x44Logo.scale-400.png` -> 44 * 4.
_APPX_TARGETSIZE_RE = re.compile(r"\.targetsize-(\d+)")
_APPX_SCALE_RE = re.compile(r"\.scale-(\d+)")

#: `shell:AppsFolder\<PackageFamilyName>!<AppId>` — how Windows addresses
#: a Store app that has no path on disk to point at.
_AUMID_RE = re.compile(
    r"(?:shell:AppsFolder\\)?([A-Za-z0-9][\w.\-]*_[a-z0-9]{13})!(\S+)")


class CommandTarget(NamedTuple):
    """What a startup entry's command line actually names.

    THREE FIELDS BECAUSE THERE ARE THREE ANSWERS, and collapsing them
    into one path was what limited this to Win32 desktop apps. A Run key
    can name a binary, a Startup-folder shortcut points at one
    indirectly, and a Store app is addressed by an identifier that is not
    a file at all — the last of which has no icon anywhere on the path a
    binary extractor walks.

      binary  the .exe that runs, when there is one on disk
      asset   a ready-made image file (an Appx logo), when the package
              declares one — already the vendor's own colour artwork, so
              it needs no extraction
      kind    which of the above answered, for diagnostics and tests
    """
    binary: str | None
    asset: str | None
    kind: str


#: Guards _declare_signatures, which is idempotent but not free.
_SIGNATURES_DECLARED = False
_COM_SIGNATURES_DECLARED = False


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


def _file_from_command(command: str) -> str | None:
    """The FILE a command line names, before any shortcut is followed.

    A startup entry's `Command` is not a path — it is whatever an
    installer wrote into a Run key, and the shapes are all different:

        "C:\\Program Files\\App\\app.exe" --minimized
        C:\\Windows\\System32\\rundll32.exe C:\\path\\thing.dll,Entry
        %LOCALAPPDATA%\\App\\app.exe /background

    THE UNQUOTED FORM WITH SPACES IS THE HARD ONE, and it is also the
    common one: splitting on the first space turns "C:\\Program
    Files\\App\\app.exe /background" into "C:\\Program", which exists on
    no machine. So an unquoted string is walked token by token and the
    longest LEADING run that names a real file wins — which is exactly
    how Windows itself resolves these, and the reason a malicious
    C:\\Program.exe is a classic privilege-escalation trick.

    EVERY BRANCH EXPANDS ENVIRONMENT VARIABLES FIRST, including the
    quoted one. `"%LOCALAPPDATA%\\Discord\\Update.exe" --processStart` is
    an ordinary Run value, and testing the unexpanded string against the
    file system answers no on every machine.
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
            candidate = os.path.expandvars(text[1:end]).strip()
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


def executable_from_command(command: str) -> str | None:
    """The binary a Windows command line launches, or None.

    _file_from_command finds the file; this follows a SHORTCUT to the
    thing it points at. Both halves are needed and neither is enough:
    every entry in the Startup FOLDER is a `.lnk`, so without the second
    half half the Startup Manager's rows were extracting the icon of a
    shortcut rather than of an application — which Windows answers by
    stamping its little arrow overlay onto the target's artwork, so the
    column carried a badge that means "this is a shortcut" beside rows
    where that is not the interesting fact.

    Returns None rather than guessing when nothing resolves; the caller
    then draws its fallback glyph, which is a better outcome than
    extracting the icon of the wrong file. A shortcut that resolves to
    NOTHING — a Store app addressed by identifier, a target that has been
    uninstalled — also returns None here; resolve_command is the entry
    point that can still answer for the first of those.
    """
    path = _file_from_command(command)
    if path is None:
        return None
    if path.lower().endswith(".lnk"):
        return resolve_shortcut(path)
    return path


# ============================================================
#  SHORTCUTS
# ============================================================
def _declare_com_signatures(ctypes, wintypes) -> None:
    """argtypes/restypes for the COM entry points, for the reason
    _declare_signatures exists: an undeclared HRESULT is read as a 32-bit
    int and loses the high bit that distinguishes failure from success,
    so a failed CoCreateInstance reads as S_OK and the next call is made
    through a null pointer."""
    global _COM_SIGNATURES_DECLARED
    if _COM_SIGNATURES_DECLARED:
        return
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p]
    ole32.CoCreateInstance.restype = ctypes.HRESULT
    ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    ole32.CLSIDFromString.restype = ctypes.HRESULT
    _COM_SIGNATURES_DECLARED = True


def _guid(ctypes, text: str):
    """A GUID string -> the 16-byte structure COM wants."""
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong),
                    ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8)]

    out = GUID()
    if ctypes.windll.ole32.CLSIDFromString(text, ctypes.byref(out)) != 0:
        raise OSError(f"CLSIDFromString refused {text}")
    return out


def _vcall(ctypes, pointer, slot: int, restype, argtypes, *args):
    """One virtual call on a COM interface pointer.

    ctypes has no COM client of its own, so the vtable is walked by hand:
    the interface pointer points at the vtable pointer, and the vtable is
    an array of function pointers in declaration order with IUnknown's
    three at the front.
    """
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0]
    slot_ptr = ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p))[slot]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(slot_ptr)(pointer, *args)


def _release(ctypes, pointer) -> None:
    if pointer:
        try:
            _vcall(ctypes, pointer, 2, ctypes.c_ulong, [])
        except Exception:                   # pragma: no cover - defensive
            pass


def _shortcut_target_com(path: str) -> str | None:
    """`path`'s target, asked of the shell itself.

    IPersistFile::Load WITHOUT a following Resolve(), deliberately.
    Resolve is the call that goes looking for a moved target — it walks
    the volume, and for a link onto a share it waits on the network. In a
    list that resolves thirty entries while the user watches, that is a
    UI freeze bought to improve the icon on a broken shortcut.

    EVERY INTERFACE IS RELEASED IN A finally, the same discipline the
    GDI half of this module keeps and for a worse failure if it lapses:
    a leaked in-proc COM object pins the DLL for the life of the process.
    """
    import ctypes
    from ctypes import wintypes

    try:
        _declare_com_signatures(ctypes, wintypes)
    except Exception as exc:                # pragma: no cover - defensive
        _fail(f"COM signature declaration failed: {exc}")
        return None

    ole32 = ctypes.windll.ole32
    hr = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    # S_OK and S_FALSE both mean "this call must be balanced"; only
    # RPC_E_CHANGED_MODE means COM is up in the other model and this call
    # took no reference. Getting that wrong either leaks an
    # initialisation or tears down the GUI thread's own apartment.
    balanced = hr in (0, 1)
    if hr < 0 and hr != _RPC_E_CHANGED_MODE:
        return None

    link = ctypes.c_void_p()
    persist = ctypes.c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(_guid(ctypes, _CLSID_ShellLink)), None,
            _CLSCTX_INPROC_SERVER,
            ctypes.byref(_guid(ctypes, _IID_IShellLinkW)),
            ctypes.byref(link))
        if hr < 0 or not link:
            return None
        hr = _vcall(ctypes, link, 0, ctypes.HRESULT,
                    [ctypes.c_void_p, ctypes.c_void_p],
                    ctypes.byref(_guid(ctypes, _IID_IPersistFile)),
                    ctypes.byref(persist))
        if hr < 0 or not persist:
            return None
        hr = _vcall(ctypes, persist, _VT_IPersistFile_Load, ctypes.HRESULT,
                    [wintypes.LPCWSTR, wintypes.DWORD], path, _STGM_READ)
        if hr < 0:
            return None

        buffer = ctypes.create_unicode_buffer(32768)
        for flags in (0, _SLGP_RAWPATH):
            hr = _vcall(ctypes, link, _VT_IShellLinkW_GetPath, ctypes.HRESULT,
                        [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                         wintypes.DWORD],
                        buffer, len(buffer), None, flags)
            if hr < 0:
                continue
            target = os.path.expandvars(buffer.value or "").strip()
            if target and os.path.isfile(target):
                return target
        return None
    except Exception:
        return None
    finally:
        _release(ctypes, persist)
        _release(ctypes, link)
        if balanced:
            try:
                ole32.CoUninitialize()
            except Exception:               # pragma: no cover - defensive
                pass


def _shortcut_target_parsed(path: str) -> str | None:
    """`path`'s target, read straight out of the .lnk file.

    THE FALLBACK, AND IT IS NOT REDUNDANT. The COM path needs a working
    apartment and an in-proc shell that will hand out CLSID_ShellLink,
    and both of those are things a locked-down or mid-servicing machine
    can refuse — on a surface whose entire job is to be readable when the
    machine is unwell. This reads the two fields of MS-SHLLINK that carry
    a path in plain text, which covers an ordinary Startup-folder
    shortcut without asking the shell for anything.

    Deliberately partial: no ID-list parsing, no network relative links.
    Those are the shapes the COM path handles and this one honestly
    cannot, and half a parser that guesses is how you point a row at the
    wrong application.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read(0x10000)
    except OSError:
        return None
    if len(data) < 0x4C or data[:4] != b"\x4c\x00\x00\x00":
        return None

    import struct

    flags = struct.unpack_from("<I", data, 0x14)[0]
    has_id_list = bool(flags & 0x1)
    has_link_info = bool(flags & 0x2)
    unicode_strings = bool(flags & 0x80)

    offset = 0x4C
    if has_id_list:
        if offset + 2 > len(data):
            return None
        offset += 2 + struct.unpack_from("<H", data, offset)[0]

    def _string_at(start: int, wide: bool) -> str:
        if wide:
            end = start
            while end + 1 < len(data) and data[end:end + 2] != b"\x00\x00":
                end += 2
            return data[start:end].decode("utf-16-le", "ignore")
        end = data.find(b"\x00", start)
        return data[start:end if end != -1 else len(data)].decode(
            "mbcs" if _WIN else "latin-1", "ignore")

    if has_link_info and offset + 0x20 <= len(data):
        base = offset
        info_size, header_size, info_flags = struct.unpack_from(
            "<III", data, base)
        offset = base + info_size
        # Bit 0: the link carries a VolumeID and a LocalBasePath, which
        # together are an ordinary local path.
        if info_flags & 0x1:
            local, suffix = None, ""
            # The UNICODE pair is optional and only present on a header of
            # 0x24 bytes or more — LocalBasePathOffsetUnicode at 0x1C and
            # CommonPathSuffixOffsetUnicode at 0x20. Preferred when there,
            # because the ANSI pair beside it is lossy for any path the
            # active code page cannot express.
            if header_size >= 0x24 and base + 0x24 <= len(data):
                wide_path, wide_suffix = struct.unpack_from(
                    "<II", data, base + 0x1C)
                if wide_path:
                    local = _string_at(base + wide_path, True)
                    suffix = (_string_at(base + wide_suffix, True)
                              if wide_suffix else "")
            if local is None:
                path_offset = struct.unpack_from("<I", data, base + 0x10)[0]
                suffix_offset = struct.unpack_from("<I", data, base + 0x18)[0]
                if path_offset:
                    local = _string_at(base + path_offset, False)
                    suffix = (_string_at(base + suffix_offset, False)
                              if suffix_offset else "")
            if local:
                target = os.path.expandvars(local + suffix)
                if os.path.isfile(target):
                    return target

    # StringData, in the fixed order the format defines. Only
    # RELATIVE_PATH is wanted, and it is relative to the .lnk's own
    # directory — which is what makes a portable shortcut portable.
    for index, present in enumerate((flags & 0x4, flags & 0x8, flags & 0x10,
                                     flags & 0x20, flags & 0x40)):
        if not present:
            continue
        if offset + 2 > len(data):
            return None
        count = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        raw = data[offset:offset + (count * 2 if unicode_strings else count)]
        offset += count * 2 if unicode_strings else count
        if index != 1:                      # 1 == RELATIVE_PATH
            continue
        relative = (raw.decode("utf-16-le", "ignore") if unicode_strings
                    else raw.decode("mbcs" if _WIN else "latin-1", "ignore"))
        if not relative:
            continue
        target = os.path.normpath(
            os.path.join(os.path.dirname(path), relative))
        if os.path.isfile(target):
            return target
    return None


def resolve_shortcut(path: str) -> str | None:
    """The file a `.lnk` points at, or None.

    The shell first, this module's own reader second. Order matters: the
    shell resolves ID-list-only links, per-user redirections and the
    KNOWNFOLDER indirections that a hand parser would have to reimplement
    badly, so it is the answer wherever it is available.
    """
    if not _available():
        return None
    if not path or not os.path.isfile(path):
        return None
    target = _shortcut_target_com(path)
    if target:
        return target
    return _shortcut_target_parsed(path)


# ============================================================
#  STORE (APPX / MSIX) PACKAGES
# ============================================================
#  A STORE APP'S ICON IS NOT IN ITS BINARY, and that single fact is why
#  this section exists. A packaged app ships its artwork as PNG files
#  beside the executable and NAMES them in AppxManifest.xml; the .exe
#  itself frequently carries no RT_GROUP_ICON at all. Run the whole
#  fallback ladder at the top of this module against one and every rung
#  answers honestly and uselessly — the shell hands back its generic
#  application placeholder, which appicons then rejects, which lands the
#  row on the neutral glyph.
#
#  So the manifest is read instead, and what comes back is better than
#  anything extraction could have produced: the vendor's own full-colour
#  artwork at up to 256px, which is the exact asset Windows itself puts
#  beside the app in the Start menu.
def _package_root_from_registry(family: str) -> str | None:
    """The install folder of the package whose FAMILY name is `family`.

    A family name is `<Name>_<PublisherId>`; the repository is keyed by
    FULL names, which additionally carry a version, an architecture and a
    RESOURCE ID: `<Name>_<Version>_<Arch>_<ResourceId>_<PublisherId>`.

    THE RESOURCE ID IS USUALLY EMPTY, which is what produces the doubled
    underscore everybody recognises — and matching on that `__` was the
    first thing tried here and is wrong. Windows' own in-box packages
    carry a real resource id (`..._neutral_neutral_cw5n1h2txyewy`), so a
    `__<publisher>` suffix test finds nothing for exactly the apps the
    purge and startup lists are full of.

    So the match is: the name is the leading segment, and the publisher
    id is the trailing one — which holds whatever sits between them.

    TWO TIE-BREAKS, in this order. An EMPTY resource id wins, because a
    non-empty one names a resource package (a language or scale
    satellite) whose manifest carries no application at all; then the
    highest version, which is the copy Windows would launch.
    """
    if not _WIN or "_" not in family:
        return None
    name, _, publisher = family.rpartition("_")
    if not name or not publisher:
        return None

    import winreg

    prefix = name.lower() + "_"
    publisher = publisher.lower()
    best: tuple[tuple, str] | None = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            _APPX_REPOSITORY) as packages:
            index = 0
            while True:
                try:
                    full = winreg.EnumKey(packages, index)
                except OSError:
                    break
                index += 1
                low = full.lower()
                if not low.startswith(prefix):
                    continue
                parts = low.split("_")
                if len(parts) < 3 or parts[-1] != publisher:
                    continue
                try:
                    with winreg.OpenKey(packages, full) as entry:
                        root, _ = winreg.QueryValueEx(entry,
                                                      "PackageRootFolder")
                except OSError:
                    continue
                if not root or not os.path.isdir(root):
                    continue
                main = 1 if parts[-2] == "" else 0
                version = tuple(int(part) if part.isdigit() else 0
                                for part in parts[-4].split(".")) \
                    if len(parts) >= 4 else ()
                key = (main, version)
                if best is None or key > best[0]:
                    best = (key, root)
    except OSError:
        return None
    return best[1] if best else None


def _best_asset_variant(declared: str) -> str | None:
    """The largest real file behind a manifest's logo declaration.

    THE DECLARED PATH IS OFTEN NOT A FILE. A manifest says
    `Assets\\Square44x44Logo.png` and what is on disk is
    `Square44x44Logo.targetsize-256.png`,
    `Square44x44Logo.scale-200.png` and half a dozen more: MSIX resolves
    those through resources.pri at runtime, and an app built with only
    the scaled variants has no file at the name it declares.

    So the declaration is treated as a STEM and the directory is read.
    Biggest wins, because this is scaled DOWN into a 20px box and a
    256px source is the difference between artwork and mush —
    `targetsize-N` is already the pixel size, `scale-N` is a percentage
    of the nominal 44px.

    PLATED BEATS UNPLATED. `altform-unplated` is the mark with its brand
    background removed, which is what a taskbar wants because the
    taskbar supplies its own. Every icon here is drawn into a neutral
    well instead, so the plated artwork is the one carrying the
    product's colour — an unplated Store logo on this surface is a white
    glyph on a near-white plate.
    """
    folder = os.path.dirname(declared)
    stem, ext = os.path.splitext(os.path.basename(declared))
    if not stem:
        return None
    try:
        names = os.listdir(folder) if os.path.isdir(folder) else []
    except OSError:
        names = []

    best: tuple[int, int, str] | None = None
    for name in names:
        base, extension = os.path.splitext(name)
        if extension.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        if not base.lower().startswith(stem.lower()):
            continue
        target = _APPX_TARGETSIZE_RE.search(base)
        scale = _APPX_SCALE_RE.search(base)
        if target:
            size = int(target.group(1))
        elif scale:
            size = int(44 * int(scale.group(1)) / 100)
        else:
            size = 44
        plated = 0 if "altform-unplated" in base.lower() else 1
        candidate = (plated, size, os.path.join(folder, name))
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is not None:
        return best[2]
    return declared if os.path.isfile(declared) else None


def appx_asset_for_root(root: str) -> str | None:
    """The best logo file in an installed package folder, or None.

    The manifest is parsed with a REGEX rather than an XML parser, and
    that is a deliberate narrowing rather than laziness: an AppxManifest
    carries a dozen namespaces and its logo attributes appear on
    <Properties>, on every <Application>, and on visual-element
    extensions, so a correct DOM walk needs the schema. All this needs is
    "which files does this package call its logo", the attribute names
    are fixed, and a miss costs a fallback rather than a wrong icon.
    """
    if not root:
        return None
    manifest = os.path.join(root, "AppxManifest.xml")
    if not os.path.isfile(manifest):
        return None
    try:
        with open(manifest, encoding="utf-8-sig", errors="ignore") as handle:
            source = handle.read()
    except OSError:
        return None

    declared: dict[str, str] = {}
    for match in _APPX_LOGO_RE.finditer(source):
        declared.setdefault(match.group(1), match.group(2))
    for attribute in _APPX_LOGO_ATTRS:
        value = declared.get(attribute)
        if not value:
            continue
        asset = _best_asset_variant(
            os.path.join(root, value.replace("/", os.sep)))
        if asset and os.path.isfile(asset):
            return asset
    return None


def appx_asset_for_path(path: str) -> str | None:
    """The package logo for a binary that lives inside one, or None.

    Walks UP from the executable looking for an AppxManifest.xml, which
    covers both places Windows keeps packaged apps —
    %ProgramFiles%\\WindowsApps for Store installs and
    %SystemRoot%\\SystemApps for the in-box ones — without either being
    named here, and without needing to list a directory whose ACL
    forbids it.

    Bounded at eight levels: a package root is one or two directories
    above its binary, and an unbounded walk on a path that is not in a
    package would climb to the drive root touching the file system at
    every step, once per row.
    """
    if not path:
        return None
    folder = os.path.dirname(os.path.abspath(path))
    for _ in range(8):
        if os.path.isfile(os.path.join(folder, "AppxManifest.xml")):
            return appx_asset_for_root(folder)
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return None


def appx_asset_for_family(family: str) -> str | None:
    """The package logo for a package family name, or None."""
    root = _package_root_from_registry(family)
    return appx_asset_for_root(root) if root else None


def aumid_from_command(command: str) -> str | None:
    """The package family name out of an Application User Model ID.

    `shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App` is
    how Windows addresses a packaged app that has no path to point at,
    and it is what a Start-menu shortcut to one resolves to. The family
    name is the half before the `!`; the AppId after it selects which
    entry point within the package, which is not something an icon
    lookup needs.
    """
    if not command:
        return None
    match = _AUMID_RE.search(command)
    return match.group(1) if match else None


def resolve_command(command: str) -> CommandTarget:
    """Everything a startup entry's command line can be resolved to.

    THE ORDER IS THE POINT, and each step exists because the one before
    it returns nothing for a whole class of entry:

      1. THE FILE, with %ENVIRONMENT% expanded and arguments stripped.
      2. THE SHORTCUT'S TARGET, when that file is a .lnk — which every
         entry in the Startup folder is.
      3. THE PACKAGE'S OWN LOGO, when the target lives inside an
         installed Store or in-box package. Preferred OVER extracting
         the binary, because a packaged app's artwork is in its manifest
         and frequently not in its .exe at all.
      4. THE SQUIRREL STUB'S APPLICATION, when the resolved binary is an
         Electron updater sitting beside an app-<version> directory.
      5. THE PACKAGE, ADDRESSED BY IDENTITY, when there is no file
         anywhere in the command — `shell:AppsFolder\\<family>!<app>`.

    Always returns a CommandTarget; `kind` is "" when nothing resolved,
    which is the caller's cue to draw the generic executable mark.
    """
    binary = _file_from_command(command)
    kind = "path"
    if binary and binary.lower().endswith(".lnk"):
        resolved = resolve_shortcut(binary)
        if resolved:
            binary, kind = resolved, "shortcut"
        else:
            # A shortcut that points at no file is usually a Store app,
            # and the identity is in the command line often enough to be
            # worth the look before giving up on the row.
            binary, kind = None, ""
    if binary and _is_squirrel_stub(binary):
        # PREFERRED, NOT REQUIRED. Squirrel stamps the app's icon onto
        # the stub, so failing to resolve costs correctness rather than
        # artwork — which is why the stub is kept when the package turns
        # out to be dead rather than the whole row being given up on.
        inner = resolve_squirrel(binary, command)
        if inner:
            binary, kind = inner, "squirrel"
    if binary:
        asset = appx_asset_for_path(binary)
        if asset:
            return CommandTarget(binary, asset, "appx")
        return CommandTarget(binary, None, kind)

    family = aumid_from_command(command)
    if family:
        asset = appx_asset_for_family(family)
        if asset:
            return CommandTarget(None, asset, "aumid")
    return CommandTarget(None, None, "")


# ============================================================
#  SQUIRREL / ELECTRON STUBS
# ============================================================
#  AN ELECTRON APP'S RUN KEY OFTEN NAMES ITS UPDATER, NOT THE APP.
#  Squirrel.Windows installs into %LOCALAPPDATA%\<Product>\ as
#
#      Update.exe            the stub, and what the Run key points at
#      app-1.2.3\App.exe     the actual application, versioned
#      packages\             the update cache
#
#  and registers `Update.exe --processStart App.exe`. Discord, and
#  historically Slack, Teams, WhatsApp and Notion, all ship this way.
#
#  RESOLVING IT MATTERS LESS THAN IT LOOKS, AND THAT IS WORTH SAYING
#  before this is read as the fix for a blank row: Squirrel STAMPS the
#  app's own icon onto Update.exe, so extracting the stub already
#  produces the right artwork most of the time. What resolving buys is
#  correctness rather than pixels — the row's tooltip and any future
#  "open file location" name the application instead of its updater, and
#  a stub whose icon resource is missing or stale stops mattering.
#
#  THE VERSION DIRECTORIES ARE SORTED NUMERICALLY, not as strings. A
#  string sort puts app-1.0.10 before app-1.0.9, which is how a resolver
#  ends up pinned to an old build that a later update left on disk.
_SQUIRREL_STUBS = ("update.exe", "squirrel.exe")
_SQUIRREL_APP_DIR = re.compile(r"^app-(\d+(?:\.\d+)*)", re.I)

#: Squirrel drops this marker into the package root when the product is
#: uninstalled, leaving Update.exe and an emptied app- directory behind.
#: Measured on one machine: SignalRgb's folder still held Update.exe and
#: an app-2.5.19 containing no executable at all, beside a `.dead` file.
_SQUIRREL_DEAD = ".dead"


def _squirrel_versions(root: str) -> list[str]:
    """`root`'s app-<version> directories, newest first."""
    try:
        names = os.listdir(root)
    except OSError:
        return []
    found: list[tuple[tuple[int, ...], str]] = []
    for name in names:
        match = _SQUIRREL_APP_DIR.match(name)
        if not match or not os.path.isdir(os.path.join(root, name)):
            continue
        version = tuple(int(part) for part in match.group(1).split("."))
        found.append((version, os.path.join(root, name)))
    return [path for _version, path in sorted(found, reverse=True)]


def resolve_squirrel(path: str, command: str = "") -> str | None:
    """The real application behind a Squirrel stub, or None.

    Takes the COMMAND as well as the path because Squirrel names the
    target in its own argument — `--processStart Discord.exe` — and that
    is a better answer than guessing which executable in the versioned
    directory is the interesting one.

    Returns None when the package is dead (a `.dead` marker, or a
    version directory with no executable in it), which is the honest
    answer: there is no application there any more, and inventing one
    would put another program's icon on the row.
    """
    if not path:
        return None
    root = os.path.dirname(path)
    if not root or os.path.isfile(os.path.join(root, _SQUIRREL_DEAD)):
        return None

    wanted = ""
    match = re.search(r"--process-?start(?:-and-wait)?[=\s]+\"?([^\"\s]+)",
                      command or "", re.I)
    if match:
        wanted = os.path.basename(match.group(1)).lower()

    for version_dir in _squirrel_versions(root):
        try:
            names = [n for n in os.listdir(version_dir)
                     if n.lower().endswith(".exe")]
        except OSError:
            continue
        if wanted:
            for name in names:
                if name.lower() == wanted:
                    return os.path.join(version_dir, name)
        # No --processStart, or it named something this version does not
        # have: fall back to the executable that is not another stub.
        for name in names:
            if name.lower() not in _SQUIRREL_STUBS:
                return os.path.join(version_dir, name)
    return None


def _is_squirrel_stub(path: str) -> bool:
    """Is `path` a Squirrel updater sitting beside a versioned app?

    BOTH HALVES ARE REQUIRED. "Update.exe" is a common enough filename
    that the name alone would claim every hand-rolled updater on the
    machine; the app-<version> sibling is what makes it Squirrel.
    """
    if not path or os.path.basename(path).lower() not in _SQUIRREL_STUBS:
        return False
    return bool(_squirrel_versions(os.path.dirname(path)))


def asset_image(path: str) -> QImage | None:
    """A package's own logo file, loaded as an image.

    Its own entry point rather than a branch inside icon_image, because
    the two are different operations wearing the same shape: this reads a
    PNG the vendor shipped, and icon_image asks Windows to extract a
    resource out of a binary. Handing this path to the extractor gets the
    shell's icon for the PNG FILE TYPE, which is a picture of a picture.
    """
    if not path or not os.path.isfile(path):
        return None
    image = QImage(path)
    return image if not image.isNull() else None


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

    A PACKAGED BINARY IS ANSWERED FROM ITS MANIFEST, before the ladder
    runs at all. A Store or in-box app keeps its artwork in PNG files
    named by AppxManifest.xml and often carries no icon resource in the
    .exe whatsoever, so every rung below would succeed at returning
    Windows' generic application placeholder. See appx_asset_for_path.
    """
    if not _available():
        return None
    if not path or not os.path.isfile(path):
        return None

    asset = appx_asset_for_path(path)
    if asset:
        image = asset_image(asset)
        if image is not None:
            return image

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
