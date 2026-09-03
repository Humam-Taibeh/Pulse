; ============================================================
;  PULSE — Windows Setup (Inno Setup 6)
; ============================================================
;  Builds PULSE_Setup_v<VERSION>.exe from the onedir PyInstaller output
;  in dist\PULSE\.
;
;  Not invoked directly — tools\build_release.ps1 defines MyAppVersion
;  from the repo's VERSION file and calls iscc. Compiling this by hand
;  works too; it just falls back to reading VERSION itself.
;
;  Build:  iscc installer\pulse.iss
;  Out:    dist\PULSE_Setup_v<VERSION>.exe   (<VERSION> = the VERSION file;
;          written as a placeholder rather than a literal, which is what
;          left this line advertising v10.4.0 five releases later.)

#ifndef MyAppVersion
  ; Read the same VERSION file the GUI, the engine and the spec read, so a
  ; hand-run compile cannot stamp a different version than the build script
  ; would have. #include is the only way to get a file's contents into a
  ; preprocessor variable, hence the temporary define.
  #define FileHandle FileOpen("..\VERSION")
  #define MyAppVersion Trim(FileRead(FileHandle))
  #expr FileClose(FileHandle)
#endif

#define MyAppName      "PULSE"
#define MyAppPublisher "Humam Taibeh"
#define MyAppURL       "https://github.com/Humam-Taibeh/Humam-Windows-Architecture"
#define MyAppExeName   "PULSE.exe"
#define SourceDir      "..\dist\PULSE"

[Setup]
; ------------------------------------------------------------
;  IDENTITY
; ------------------------------------------------------------
; AppId is a STABLE GUID and must never change. It is the key Windows uses
; to recognise an existing installation: change it and every upgrade
; installs a second copy alongside the first, with two Start Menu entries
; and an uninstaller that only removes half of it.
AppId={{7B2F4C91-3E8A-4D6B-9F1C-2A5E8D04B7C3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases

; ------------------------------------------------------------
;  INSTALL LOCATION AND PRIVILEGE
; ------------------------------------------------------------
; ADMIN / PROGRAM FILES BY DEFAULT, and this is a security decision rather
; than a convention. PULSE runs asInvoked and elevates per task (~24 of
; them touch HKLM, services or machine state). If the application lived in
; a user-writable directory, any process running as the user could replace
; PULSE.exe or the PowerShell engine beside it and wait for the next
; elevated task to run it — a straight privilege-escalation path. Program
; Files is not writable without elevation, which closes it.
;
; This is the same boundary src/utils/resources.py defends when it refuses
; to resolve core.ps1 from the executable's own directory, and the reason
; the PyInstaller spec moved off onefile (%TEMP% extraction).
;
; A per-user install remains available for machines where the technician
; has no admin rights — Inno offers the choice when this override is set —
; but it is not the default, and the elevated-task caveat above applies to
; anyone who picks it.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}

; ------------------------------------------------------------
;  WIZARD — appearance
; ------------------------------------------------------------
; MODERN, DYNAMIC, WINDOWS 11. Three tokens, three separate decisions:
;
;   modern     the flat Inno 6 layout rather than the 1990s classic one.
;   dynamic    follow the user's Windows light/dark setting instead of
;              forcing either. Pulse's own UI defaults to dark and offers
;              a toggle; an installer that hard-forced dark would be the
;              one surface in the product that ignores the same system
;              preference the app respects.
;   windows11  the built-in custom style whose light half is a proper
;              counterpart to the built-in dark one, so BOTH appearances
;              are deliberate rather than "dark, plus whatever light used
;              to look like". This is what themes the controls — the
;              license memo's border, the tasks checkboxes, the buttons.
;
; Requires Inno Setup 6.6+ (dark mode and custom styles landed there).
; Built and verified against 6.7.3.
;
; NOT SET: WizardResizable. It was dropped in 6.7 — the main wizard window
; is no longer resizable by anyone — and before that it defaulted to `no`
; anyway. Writing it would be a line that has never changed a build.
WizardStyle=modern dynamic windows11

; THE STOCK ARTWORK IS AN OVERRIDE, NOT A DELETION, and that distinction is
; the whole reason these two lines exist. Inno does not ship "no image" as
; a default: with WizardStyle=modern it supplies its own teal abstract
; graphic, and because this file never named a replacement, every Pulse
; installer up to 10.9.1 carried it. There was nothing here to remove.
;
; ONE FILE PER DPI, because Inno picks the nearest from the list and
; upscaling a 164px bitmap to a 200% display is exactly the soft, fringed
; result the modern style exists to avoid. Generated by
; tools/make_installer_art.py from assets/pulse.ico — the real brand mark,
; matted off its tile, never redrawn.
;
; BOTH ARE PNG, for two different reasons. The mark NEEDS the format: it
; sits directly on the page, which is off-white under windows11's light
; half and near black under its dark half, so its transparency is what
; lets one asset serve both grounds. The banner merely benefits from it —
; it is an opaque panel and BMP would render identically, at 1.8MB against
; 100KB for the same five images. (The usual case for BMP is that every
; Inno build reads it; that does not apply to a file which already needs
; 6.6+ for its dark mode and cannot compile on an older one at all.)
;
; Neither needs a DynamicDark twin: the banner is a deliberate brand
; surface in both appearances, and the mark adapts by being transparent.
WizardImageFile=..\assets\installer\wizard-banner-164x314.png,..\assets\installer\wizard-banner-205x393.png,..\assets\installer\wizard-banner-246x471.png,..\assets\installer\wizard-banner-287x550.png,..\assets\installer\wizard-banner-328x628.png
WizardSmallImageFile=..\assets\installer\wizard-mark-55x58.png,..\assets\installer\wizard-mark-69x73.png,..\assets\installer\wizard-mark-83x87.png,..\assets\installer\wizard-mark-97x102.png,..\assets\installer\wizard-mark-110x116.png

; ------------------------------------------------------------
;  WIZARD — flow
; ------------------------------------------------------------
; FOUR DECISIONS THE USER ACTUALLY HAS, and nothing else between them and
; a working install: the licence, where it goes, whether they want a
; desktop icon, and whether to launch it afterwards.
;
; The Ready page is the one that earns its removal. It exists to recite
; choices back before committing — worth it for an installer with
; components, optional features and a dozen branches. Pulse has one
; optional task, and it is a checkbox the user ticked on the page
; immediately before. Reading "Destination: C:\Program Files\PULSE" back
; to someone who has just typed it is a page they click Next on without
; reading, which is the definition of one too many.
;
; The Welcome page is already absent: Inno's modern style omits it by
; default, which is where the large banner's real home became the Finished
; page.
DisableReadyPage=yes
DisableProgramGroupPage=yes

SetupIconFile=..\assets\pulse.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
OutputDir=..\dist
OutputBaseFilename=PULSE_Setup_v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes

; 64-bit only: the engine calls into 64-bit WMI/registry views and the
; PySide6 build is amd64. "compatible" keeps this correct on ARM64 too.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; ------------------------------------------------------------
;  IN-PLACE UPGRADE
; ------------------------------------------------------------
; The auto-updater (src/utils/updater.py) downloads this installer and runs
; it while PULSE is on screen. Without these two, Setup would hit a locked
; PULSE.exe and either fail or demand a reboot; with them it closes the
; running copy, replaces it, and starts it again afterwards.
CloseApplications=yes
RestartApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.ps1

; ------------------------------------------------------------
;  SIGNING
; ------------------------------------------------------------
; UNSIGNED BUILDS WILL TRIP SMARTSCREEN on every download — that is
; expected, not a defect, until a real certificate (chained to a CA in
; Microsoft's trust program — see ROADMAP.md, "Code signing via Azure
; Trusted Signing") exists.
;
; Signing itself is NOT done here. tools\build_release.ps1's -SignThumbprint
; runs signtool against PULSE.exe and the compiled Setup.exe as a POST-BUILD
; step, rather than through this file's own SignTool directive — Inno
; refuses to compile at all if a script declares SignTool without the
; matching /S<name>=... on the command line, which would break every
; ordinary unsigned build (i.e. everyone, today) rather than just skip
; signing for them. A post-build pass keeps "no certificate configured" the
; default, working, silent case.
;
; NOT COVERED BY THIS: the generated uninstaller (unins000.exe) — it is
; written to the install directory at INSTALL time, carries no
; Mark-of-the-Web, and was never the thing tripping a download-time
; SmartScreen warning. Inno's own SignTool=/SignedUninstaller=yes directives
; remain the way to sign it too, if that ever matters enough to solve the
; ISCC /S argument problem above.
;
; The updater's Authenticode check (see updater.authenticode_publisher)
; stays advisory until a real certificate's publisher name is worth
; requiring a match against — a self-signed one proves nothing a match
; check could act on.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The whole onedir output: PULSE.exe, _internal\ (Qt + the Python runtime),
; src\backend\ (the PowerShell engine), playbooks\, assets\ and VERSION.
; recursesubdirs+createallsubdirs keeps the layout byte-for-byte, which
; matters because resources.py resolves everything relative to it.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; nowait + skipifsilent: a silent upgrade driven by the updater must not
; block waiting for the app it just relaunched.
;
; shellexec + runasoriginaluser are the fix for Windows App Control error
; 4551 on the "launch when Setup finishes" checkbox. Setup runs ELEVATED,
; so without these it starts PULSE.exe as a direct CreateProcess child of
; an elevated installer - and PULSE.exe's own manifest already asks for
; requireAdministrator (see the manifest note in main.spec). On a machine
; with App Control / Smart App Control enforcing, an elevated parent
; spawning an elevation-requesting child is exactly the shape that gets
; blocked, and Setup surfaces it as 4551.
;
;   shellexec          launches through ShellExecuteEx rather than
;                      CreateProcess, so Windows performs its normal
;                      elevation handshake instead of inheriting one.
;   runasoriginaluser  runs it as the user who started Setup rather than
;                      as the elevated installer account. That is also
;                      what makes the app come up owning the right
;                      profile - %LOCALAPPDATA%\PULSE, the saved theme,
;                      the window geometry and the log all live under the
;                      SIGNED-IN user, and a first launch under the
;                      installer's account would write them somewhere the
;                      user never sees again.
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: runasoriginaluser shellexec postinstall nowait skipifsilent

[UninstallDelete]
; PyInstaller writes nothing here at runtime, but a user dropping extra
; playbooks beside the app (a supported workflow — see resources.user_roots)
; leaves files Setup never installed and therefore never tracks.
Type: filesandordirs; Name: "{app}\playbooks"
Type: dirifempty; Name: "{app}"

[Code]
{ ------------------------------------------------------------
  Uninstall: offer to remove preferences, never assume.

  prefs.py stores theme, window geometry and per-task run history under
  HKCU\Software\HumamTaibeh\Pulse. Two things must both stay true:

    * An UPGRADE must never touch it. Inno runs the old uninstaller during
      some upgrade paths, and silently wiping a user's history and window
      placement on a version bump would be a bug they could not explain.
      Hence UninstallSilent() — an upgrade-driven uninstall is silent, an
      interactive one is not.

    * A deliberate REMOVAL should be able to leave nothing behind, but that
      is the user's call. Someone uninstalling to reinstall a fixed build
      does not want to lose a year of task history.
  ------------------------------------------------------------ }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Key: String;
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if UninstallSilent() then
      Exit;
    Key := 'Software\HumamTaibeh\Pulse';
    if RegKeyExists(HKEY_CURRENT_USER, Key) then
    begin
      if MsgBox('Also remove PULSE''s saved settings?' + #13#10#13#10 +
                'This deletes your theme, window position and per-task run ' +
                'history. Choose No if you plan to reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER, Key);
    end;

    { ------------------------------------------------------------
      THE SECOND HALF, WHICH WAS MISSING. The prompt above is accurate
      about what it deletes and for that reason was the more misleading
      for it: a user reading "theme, window position and run history"
      reasonably concludes that is everything, while %LOCALAPPDATA%\PULSE
      stayed untouched — and that is where the material actually is.

      NAMED, NOT SUMMARISED. "Also delete application data" invites Yes
      from someone who would say No to "your rescued OneDrive files",
      which is what is actually in there: Backup-OneDriveFiles evacuates
      every local sync root before the client is uninstalled, so for
      anything not synced elsewhere this folder is the only copy. The
      wording has to carry that or the consent is not informed.

      DEFAULT IS NO, and separate from the settings question above,
      because the two have very different costs to get wrong: losing a
      window position is an inconvenience and losing evacuated documents
      is not recoverable.
      ------------------------------------------------------------ }
    DataDir := ExpandConstant('{localappdata}\PULSE');
    if DirExists(DataDir) then
    begin
      if MsgBox('Also delete the files PULSE saved on this PC?' + #13#10#13#10 +
                DataDir + #13#10#13#10 +
                'This includes the operation log, your Edge bookmark backup, ' +
                'any files rescued from OneDrive before it was removed, and ' +
                'exported driver backups.' + #13#10#13#10 +
                'For files rescued from OneDrive this may be the only copy. ' +
                'Choose No to keep them.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
