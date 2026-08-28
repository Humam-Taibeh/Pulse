# -*- mode: python ; coding: utf-8 -*-
#
#  PULSE — PyInstaller build recipe.
#
#  ONEDIR, NOT ONEFILE (v10.3). This used to pass a.binaries/a.datas
#  straight into EXE(), which produces a single self-extracting executable.
#  For an INSTALLED application that is the wrong shape, for two reasons
#  that only appear once it ships:
#
#    1. A onefile build re-extracts the ENTIRE bundle — PySide6, Qt's
#       plugins, the whole PowerShell engine — into %TEMP%\_MEIxxxxxx on
#       every single launch, then deletes it on exit. That is seconds of
#       cold start the user pays each time, for nothing, on a tool whose
#       whole promise is "one launcher".
#
#    2. It puts the engine in a user-writable directory. utils/resources.py
#       documents this exact hazard: with _MEIPASS under %TEMP%, the
#       "bundled" root ladder resolved to %TEMP%, so %TEMP%\src\backend\
#       core.ps1 became a candidate location for the script Pulse runs
#       ELEVATED. Any process running as the user could write it.
#
#  Onedir puts _MEIPASS inside the install directory — which the Inno Setup
#  script installs to Program Files, i.e. somewhere an unelevated process
#  cannot write. Launch is a plain exec with no extraction at all.
#
#  Build:  pyinstaller main.spec      ->  dist/PULSE/PULSE.exe
#  The installer (installer/pulse.iss) packages that directory wholesale.

import os
import re

# PyInstaller 6.x does NOT inject these into the spec namespace the way it
# does Analysis/EXE/COLLECT — a spec that uses them without this import
# fails with a bare NameError several minutes into the build.
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
    VarStruct, VSVersionInfo,
)

# The version resource is stamped from the SAME `VERSION` file the GUI and
# the engine read (see src/utils/version.py). Windows wants a 4-tuple of
# integers, so the three-component release version gains a trailing 0.
_here = os.path.abspath(os.getcwd())
with open(os.path.join(_here, 'VERSION'), encoding='utf-8-sig') as _fh:
    APP_VERSION = _fh.read().strip()
if not re.fullmatch(r'\d+\.\d+\.\d+', APP_VERSION):
    raise SystemExit(f'VERSION is {APP_VERSION!r}; expected MAJOR.MINOR.PATCH')
_v = tuple(int(p) for p in APP_VERSION.split('.')) + (0,)

a = Analysis(
    ['src/frontend/main.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('src/backend/core.ps1', 'src/backend'),
        # core.ps1 is only a thin orchestrator: it dot-sources every module
        # in src/backend/modules/ at startup. Without this entry the bundled
        # exe ships an engine that fails to load on every task.
        ('src/backend/modules', 'src/backend/modules'),
        # window/taskbar icon, loaded at runtime via _locate_icon()
        ('assets/pulse.ico', 'assets'),
        # Shipped playbooks (v10.3). Resolved at runtime by
        # frontend.playbooks.playbook_dirs(), which checks _MEIPASS first;
        # without this the Automation module loads an empty list in the
        # frozen build and the feature silently looks broken. A technician
        # can still drop extra .json files next to the exe — that
        # directory is searched ahead of this one.
        ('playbooks', 'playbooks'),
        # The single version source (utils/version.py reads it, and so does
        # core.ps1 via ..\..\VERSION). It has to land at the BUNDLE ROOT:
        # that is what makes the engine's one relative path resolve in both
        # the checkout and the bundle. Without this entry both fall back to
        # their hardcoded literal and the app silently misreports itself
        # the first time VERSION changes.
        ('VERSION', '.'),
    ],
    hiddenimports=[
        'utils.helpers',
        'utils.version',
        'frontend.theme',
        'frontend.animations',
        'frontend.menu_structure',
        'frontend.widgets',
        'frontend.playbooks',
        'frontend.health_report',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# ============================================================
#  WINDOWS VERSION RESOURCE
# ============================================================
# The exe shipped with NO version resource at all, so its Properties tab
# was blank, SmartScreen and AV heuristics had nothing to weigh, and the
# updater had no authoritative version to compare an installed build
# against. Every string here is derived from `VERSION`; none is a literal.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_v, prodvers=_v,
        mask=0x3F, flags=0x0,
        OS=0x40004,        # VOS_NT_WINDOWS32
        fileType=0x1,      # VFT_APP
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable('040904B0', [      # US English, Unicode
                StringStruct('CompanyName', 'Humam Taibeh'),
                StringStruct('FileDescription',
                             'PULSE — Windows configuration and repair'),
                StringStruct('FileVersion', APP_VERSION),
                StringStruct('InternalName', 'PULSE'),
                StringStruct('LegalCopyright',
                             'Copyright (c) Humam Taibeh. MIT License.'),
                StringStruct('OriginalFilename', 'PULSE.exe'),
                StringStruct('ProductName', 'PULSE'),
                StringStruct('ProductVersion', APP_VERSION),
            ]),
        ]),
        VarFileInfo([VarStruct('Translation', [0x0409, 1200])]),
    ],
)

exe = EXE(
    pyz,
    a.scripts,
    # ONEDIR: the binaries and datas are collected alongside the exe by
    # COLLECT below rather than embedded in it. exclude_binaries=True is
    # what makes that split; without it this silently reverts to onefile.
    exclude_binaries=True,
    name='PULSE',
    version=version_info,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX intentionally disabled (v6.1): packed executables are a classic
    # antivirus false-positive heuristic, and an elevated system tool cannot
    # afford that reputation hit for a few MB of size.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='assets/pulse.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # REQUIRE ADMINISTRATOR (v10.7). This emits
    #     <requestedExecutionLevel level="requireAdministrator" uiAccess="false"/>
    # into the exe's manifest, so Windows shows the UAC prompt before Pulse
    # starts and the process always runs with an Administrator token.
    #
    # THIS REVERSES A v1.0 DECISION, and the reasons that decision was made
    # have not gone away — they are consequences of this setting, not
    # arguments against having chosen it:
    #
    #   1. THE ELEVATION UI IS NOW UNREACHABLE. menu_structure.requires_admin,
    #      ElevatePromptDialog, the sidebar "Run as Administrator" CTA, the
    #      locked-card affordance and the "Not Elevated" hero chip all
    #      describe a state the packaged app can no longer be in. They stay
    #      in the tree because `python src\frontend\main.py` still runs at
    #      the developer's own level and exercises every one of them, and
    #      because the state is one Windows can still produce (an
    #      administrator who declines the prompt gets no process at all, but
    #      a policy-restricted account can be denied the token).
    #
    #   2. SOME PACKAGES BECOME UN-INSTALLABLE THROUGH THE GUI. Installers
    #      that set `elevationProhibited` hard-refuse under an Administrator
    #      token — $Script:KnownElevationProhibitedAppIds in 01-Catalogs.ps1
    #      lists Spotify, and winget reports the family as
    #      -1978335146 / -1978335107. There is no longer an unelevated Pulse
    #      to fall back to, so the advice those errors used to give is now
    #      impossible and their wording had to change with this flag (see
    #      Resolve-WingetExitCode). The honest answer for those packages is
    #      now the vendor's own installer.
    #
    #   3. PER-USER STATE FOLLOWS THE TOKEN. When the elevated session
    #      belongs to a DIFFERENT account than the desktop user, HKCU and
    #      %LOCALAPPDATA% both resolve to the administrator's profile.
    #      Initialize-UserHiveTargeting (00-Foundation.ps1) already detects
    #      that and redirects registry writes to the desktop user's hive, or
    #      refuses them; the data root does NOT redirect, so on such a
    #      machine logs and backups land in the admin's AppData. That is
    #      consistent — the GUI reading them shares the same token — but it
    #      is not where the desktop user will look in Explorer.
    #
    # What it buys is the reason it was asked for: ~24 of Pulse's tasks
    # write HKLM, services or machine state, and a repair tool that prompts
    # separately for each of them is a tool that interrupts the work it was
    # opened to do.
    uac_admin=True,
)

# ============================================================
#  COLLECT — the installable directory
# ============================================================
# Produces dist/PULSE/ containing PULSE.exe plus _internal/ (Qt, PySide6,
# the Python runtime) and the data trees declared above. installer/pulse.iss
# packages this whole directory; nothing else is needed at runtime.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,          # same reasoning as EXE: see the note there
    upx_exclude=[],
    name='PULSE',
)
