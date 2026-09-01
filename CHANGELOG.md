# Changelog

All notable changes to **Pulse** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versioning note: the GUI and the PowerShell core share ONE version, read
from the `VERSION` file at the repo root. `APP_VERSION` in
`src/frontend/main.py` is `version.VERSION` (which reads that file), and
`$Script:ScriptVersion` in `src/backend/core.ps1` is a fallback literal the
same file overrides at startup; the installer and the PyInstaller spec quote
it too. They were genuinely independent once, and this note still said so
long after `VERSION` had become the single source.

---

## [Unreleased]

---

## [10.9.3] — 2026-09-02

The two themes stopped rendering as two different apps.

Everything here came out of reading a light-mode and a dark-mode
screenshot of the dashboard side by side. Three of the four defects are
why the modes did not look like the same product, and none of them raises
— the suite was green through all of them.

### Fixed
- **The sidebar drew four outlined boxes in light mode.** The nav rail was
  the one place in the app painting a theme-agnostic edge: it took the
  bevel painter's own defaults (0.14 white / 0.20 black) instead of the
  theme's, and the two canvases receive that diagonal in opposite
  directions. On obsidian both halves vanish into the panel, so dark got
  the airy "ghost rail" the design specifies; on porcelain both land, so
  every entry wore a closed grey rectangle — an outline around a row whose
  fill is transparent. The weights come from the theme now, and are spent
  only where a row actually has a surface: full when selected, ramping in
  under the pointer.
- **A health tile lost its severity colour on every theme switch.** ACTIONS
  DUE is emerald at zero and amber above it — a state no threshold on the
  number itself would express — but re-theming re-derived the tone from
  the ratio and discarded the override. The same three overdue actions
  therefore read amber in whichever mode the app started in and plain
  indigo in the other. The override is stored as a token name now and
  re-resolved against whichever palette is current.
- **The search box led with a colour emoji**, the last one left in the
  app's persistent chrome, sitting above four monochrome Fluent icons it
  did not match. It is a real line icon now, rendered from the same glyph
  table at the screen's device pixel ratio, with the emoji kept as the
  fallback where Windows has no icon font.
- **The MODULES label sat two pixels left of the column it names.** The
  rail's left rule had three spellings; it has one, and the nav entries
  read it rather than repeating it.

### Changed
- **The label roles are back on the type scale.** Eleven type decisions —
  every card title, every dialog heading, the page header, the wordmark —
  were bare strings outside `TYPE`, invisible to the test that exists to
  catch exactly that. Three sizes that existed nowhere in the scale are
  steps now, added with their reasons rather than snapped onto a
  neighbour. No rendered size moves: verified by generating all 178 QSS
  strings the app can build, in both themes, against the old tables.
- **The icon plaque's retired material is gone.** Six tokens and helpers
  described a halo, an outer hairline, a lit inner rim and an accent wash
  that nothing has painted since 10.6, and the docs still described all of
  it. The module-glyph contrast floor was being computed *through* that
  dead wash — so it measured a surface the product no longer had, and
  would have kept passing if the real well had been taken to an alpha that
  swallowed the glyph. It now measures the neutral the app actually
  paints, across five surfaces where it checked one, worst case 4.12:1
  against a 3:1 floor.

### Internal
- CI's native-suite floor re-measured rather than adjusted: 991 collected,
  80 native, so a desktop-less runner executes 911 and the floor moves
  670 → 950. The native subset has *shrunk* (115 → 80) while the suite
  grew, which the old figures had no way to show.
- pytest 990 passed / 0 failed. Every new guard was confirmed to fail
  against the shipped behaviour before it passed against the fix.

---

## [10.9.2] — 2026-08-31

A modern Setup wizard, and four defects that only a long session would
have shown you.

The installer stopped shipping stock Inno clipart — which it had been
doing by omission rather than by choice, since Inno supplies its own when
you name none. The other four are the kind that pass every test: a state
badge that could report the world as it was before your click, a modal
that was never deleted, a revert that announced it had applied, and an
apply-direction idempotence check that was never asked in reverse.

### Fixed — a card could report the state it had BEFORE the action
- **A state refresh requested while one was already running was dropped,
  not queued.** `_refresh_tweak_state` returned early when a probe was in
  flight, which reads as harmless de-duplication and was not: both callers
  that matter fire 400ms after a task ends, and a probe takes about a
  second (measured: 0.91-0.99s for `GetTweakState`). Any task finishing
  within roughly a second of a previous refresh therefore lost its own
  refresh permanently, and the card kept its pre-action badge until some
  later, unrelated action happened to schedule another probe — "not
  applied" sitting under a tweak that had just succeeded. The likeliest
  ways to hit it were also the most ordinary: two quick tweaks in a row, or
  a first action taken while the startup probe was still running. A
  pending request is now remembered and served when the probe in flight
  finishes.

### Fixed — every modal the shell opened lived until the app quit
- **No modal was ever deleted.** Each one is built as `SomeDialog(self,
  …)` — parented to the window — and dropped when the local goes out of
  scope; the C++ object belongs to `PulseApp` and outlives every one of
  them. Measured: ten Ctrl+K presses left ten live `CommandPalette`s
  holding 120 list rows and 970 child QObjects between them, and all
  twenty-two call sites through `_exec_dialog` had the same shape. The
  funnel now deletes what it showed. Deferred deletion is what makes that
  safe in one place: every caller reads its result (`chosen_item`,
  `selected_ids`) synchronously on the next line, before the event loop
  turns. The playbook's run-mode dialog is deliberately exempt — it calls
  `exec()` itself because its lifetime belongs to the run, not the call.

### Fixed — reverting a tweak announced that it had applied one
- **`Invoke-Tweak` printed "`<Key>` applied successfully" in both
  directions**, so reverting Dark Mode wrote "DarkMode applied
  successfully" into the live console. The message now follows the
  direction.
- **Only the apply direction was asked whether it had anything to do.**
  `Test-TweakAlreadyOn` was consulted for `State="On"` alone, so
  re-reverting an already-reverted tweak walked the whole write path again
  and reported success for a no-op. The end state was never wrong — the
  values written are the ones already there, and the snapshot layer is
  first-write-wins — but it was the half of idempotence a user can see.
  `Test-TweakInState` now answers for either direction; the original
  single-direction helper is kept as a shim for the console menus.

### Changed — the idle brand mark repaints at the rate it needs
- `BrandMark` repainted on every one of Qt's 60Hz animation ticks, which
  also repainted every transparent ancestor between it and the window.
  Quantising the breath to 24 steps takes it to ~19 repaints a second —
  474/s against 640/s across the whole window, a 27% reduction — with no
  visible difference in a 2.6s sine ease. Idle CPU is directionally better
  (median 3.67% of a core against 4.14%, n=5) but that difference sits
  inside this machine's measurement noise, so it is reported as a paint
  reduction rather than a CPU win. See the note in the code: most of the
  remaining idle cost is the 60Hz animation machinery itself, not painting.

### Changed — the Setup wizard stopped looking like 2009
- **The stock Inno artwork was never removed, because there was nothing to
  remove.** `pulse.iss` set neither `WizardImageFile` nor
  `WizardSmallImageFile`, and Inno does not default to "no image" — with
  `WizardStyle=modern` it supplies its own teal abstract graphic. Every
  Pulse installer up to 10.9.1 therefore shipped stock Inno clipart *by
  omission*. Both directives are now set, so the artwork is overridden
  rather than inherited.
- **Real dark mode, following the user's Windows setting.**
  `WizardStyle=modern dynamic windows11`. Inno 6.6 added native dark mode
  and custom styles; 6.7.3 is what this builds against. `dynamic` rather
  than forced `dark` on purpose: Pulse's own UI defaults to dark and offers
  a toggle, so an installer that hard-forced dark would be the one surface
  in the product ignoring the same system preference the app respects.
  `windows11` supplies a deliberate light counterpart, and is what themes
  the controls — the licence memo's border, the tasks checkboxes, the
  buttons.
- **Pulse's own mark, at every DPI.** A dark sidebar banner (star, wordmark,
  accent hairline) and a transparent header mark, rendered at five scales
  each from 100% to 200% so Inno never has to upscale. Generated by the new
  `tools/make_installer_art.py` from `assets/pulse.ico` — the real brand
  asset, matted off its tile, never redrawn. The header mark is PNG with
  alpha precisely so ONE file serves both appearances: it sits directly on
  a page that is off-white in light mode and near-black in dark, and
  anything with a background of its own would show as a rectangle in one of
  them.
- **One page fewer.** `DisableReadyPage=yes`. The Ready page recites the
  user's own choices back one screen after they made them; with a single
  optional task there is nothing on it they have not just seen. The flow is
  now Licence → Destination → Tasks → Install → Finished.
- Verified by compiling throwaway light and dark previews and driving them
  through every page. Not asserted from the source alone: the source says
  what was asked for, and a screenshot says what Windows actually drew.

### Fixed — a build-only dependency that was only ever there by accident
- `Pillow` is now declared in `requirements-dev.txt`. The new wizard-art
  tool needs it, and so do the packaging tests that read each image back to
  check it is the size its name claims and that the header mark still
  carries alpha. It was present on the author's machine only as a
  dependency of an unrelated package — the exact shape of a thing that
  passes locally and fails on a clean runner.

### Added — guards for the wizard's appearance
- The stock artwork cannot come back by deletion: both image directives
  must be set, non-blank, and must not point at a `compiler:` bitmap.
- Every image `pulse.iss` names must exist, and its pixel size must match
  the size in its filename — a correctly-named wrong-sized file would
  silently reintroduce the upscaling the per-DPI set exists to avoid.
- The header mark must be a PNG with genuinely transparent pixels.
- `WizardStyle` must stay `dynamic` (never forced `dark`), no `[Setup]`
  directive may be written twice, and `WizardResizable` — dropped in Inno
  6.7, a no-op on every version before it, and still silently accepted by
  the compiler — must not be resurrected.

---

## [10.9.1] — 2026-08-30

The build that actually contains what 10.9.0 announced.

Five defects, and what they have in common is that every one of them was
invisible from a green test run: a spec omission that only changed the
frozen build, a time budget enforced against a walk that had already
finished, a scan that crashed on the input it existed to diagnose, a path
test that answered about the wrong file, and a success line printed for
work that never happened.

### Fixed — the release build was missing its brand marks
- **No vendor logo shipped in any built copy of v10.9.0.** `main.spec` had
  no `assets/appicons` entry, so none of the 37 marks or their manifest
  reached the bundle: every catalog row fell through to the neutral grey
  glyph, in the released build only. Both halves of the silence were by
  design — `appicons._manifest()` degrades a missing manifest to "no
  bundled marks" so decoration can never stop the installer UI opening, and
  every icon test reads the source tree — so nothing anywhere looked inside
  the bundle. Verified against a real rebuild: 0 marks before, 37 after.
  `tools/build_release.ps1` now fails the build if the marks are absent,
  and a new packaging test derives the required resources from the
  `find_resource()` / `resource_dirs()` call sites so the next one is
  covered the day it is written.

### Fixed — the Storage Analyzer ignored its own time budget
- **A 90-second budget that could run for minutes.** `Measure-DirectorySize`
  assigned a recursive `Get-ChildItem` to a variable, which runs the
  pipeline to completion — so the entire tree was walked before the
  deadline was consulted once, and the accumulator grew an object per file
  on the volume. Measured: a scan of `C:\` was still going after nine
  minutes; the only real bound was the GUI's 900-second timeout, which
  surfaces as a wedged task rather than the partial report intended. The
  walk is now an explicit lazy enumeration with the deadline tested per
  directory and per file. Same scan: 119 seconds, reported as partial.

### Fixed — the PATH Doctor crashed on the entry it existed to find
- **One malformed PATH entry aborted the whole scan.** `Test-Path` does not
  return `$false` for a path containing `|`, `<` or `>` — it throws, and
  `$ErrorActionPreference = "Stop"` turned that into the task's verdict
  (`##PULSE##ERROR|Illegal characters in path.`) with no report at all. The
  probe is guarded, and an unparseable entry is now its own `[INVALID]`
  finding, kept distinct from `[DEAD]` because "the folder does not exist"
  is the wrong advice for a string that could never have named one.

### Fixed — a file the user picked could be reported as missing
- **`[` and `]` are legal in Windows filenames, and `-Path` reads them as a
  character class.** `Invoke-GuiLocalInstall` and the Office ODT flow
  probed picker-supplied paths with `-Path`, so a real `setup [1].exe` —
  what a browser names a second download of the same installer — was
  rejected as "Installer file not found", as was any deployment folder with
  a bracket in its name. Both now use `-LiteralPath`, the idiom
  `Disable-StartupItem` already carried for `Game [2].lnk`.

### Fixed — the purge could claim a removal it had not performed
- **"Removed News" for a package that was already gone.** An empty pipeline
  is not an error in PowerShell: when `Get-AppxPackage` matched nothing,
  `Remove-AppxPackage` was never invoked, no exception was raised, and the
  success line after it ran anyway — counting a removal that never
  happened. The package is now enumerated first, and "already gone by the
  time the purge reached it" is reported as what it is.

### Added — guards for invariants that were only ever comments
- The installer's post-install launch flags (`runasoriginaluser`,
  `shellexec`), which are what keep Windows App Control from refusing the
  "Launch PULSE" checkbox with error 4551.
- Catalog-to-icon coverage in both directions: an app added without a mark
  now fails, and so does a mark left behind for an app the catalog dropped.
- `SEARCH_ALIASES` keys must be stored already normalised — an alias
  written with a hamza'd alef is unreachable for the life of the table, and
  looks exactly like a word nobody added.
- `Esc` closes the Command Palette without launching the highlighted row.

---

## [10.9.0] — 2026-08-30

Silent, resilient, and drawn in the vendors' own colours.

### Fixed — nothing flashes a console any more
- **Two backend launches allocated a console window and threw it over the
  UI.** The bloatware codec uninstaller (`08-Privacy.ps1`) and the
  local-file installer (`04-SoftwareEngine.ps1`) called `Start-Process`
  without `-NoNewWindow`, so a *silent* uninstall showed a black box for as
  long as it ran. Both now share the engine's console, which — because the
  engine is spawned with `CREATE_NO_WINDOW` — is no console at all. The
  Python side was already correct; both halves are now pinned by tests that
  read every launch site individually, because one call carrying the flag
  has never made its neighbour safe.

### Fixed — uninstalls that report the truth
- **OneDrive: "already gone" is a success state.** Exit code
  `-2147219813` (`0x8004069B`) means the product is not registered for this
  user — and since Windows leaves the setup stub in System32 regardless,
  the purge found an uninstaller, ran it, and reported a hard failure for a
  machine already in the state the user asked for. That code, and a missing
  `OneDriveSetup.exe` entirely, now report `AlreadyRemoved` and run the same
  cleanup a live uninstall does.
- **The leftovers are cleared on every path.** `HKCU\Software\Microsoft\
  OneDrive` (the account, tenant and sync-endpoint hive) and the two
  Explorer namespace CLSIDs outlive the client, which is why a "removed"
  OneDrive kept a dead cloud folder in the sidebar. Folders are deleted
  **only when empty** — a sync root can hold the only copy of a file that
  never finished uploading, so the emptiness test recurses and stops at the
  first file found.
- **Edge: exit 93 is a refusal, not a fault.** `setup.exe` returns it for
  `UNINSTALL_NOT_ALLOWED`, and winget's `1603` is the same wall through the
  MSI layer. Retrying reproduces it forever, which is exactly what the
  previous implementation did. Both codes now ESCALATE: Microsoft's own
  `AllowUninstall` EdgeUpdate policy, then the DMA-compliant EEA region
  path, then forceful package deregistration. The policy and the region are
  each restored in a `finally` — GeoID feeds regional defaults well outside
  this app, and a utility that quietly moved a user to another country to
  win an argument with a browser would be doing something they could never
  trace back.
- **Edge is deprovisioned as well as unregistered.** `Remove-AppxPackage`
  unregisters it for the users who have it; only
  `Remove-AppxProvisionedPackage` takes it out of the image, which is what
  stops it returning for the next user to sign in.

### Changed — authentic full-colour brand marks
- **The catalog was 34 recoloured silhouettes to 2 real logos.** Simple
  Icons is a monochrome set, so Chrome was a flat blue disc and Steam a
  flat black one — authentic in shape, and missing the exact thing that
  makes those marks recognisable at 20px. The fetcher now prefers the CC0
  `logos` collection and the MIT `thesvg-color` / `devicon` sets: **36 of
  37 marks are full colour**, including Chrome, Steam, Epic Games,
  Rockstar, Java, .NET and MSI Afterburner. Cursor stays monochrome because
  its own brand cube is.
- **One presentation for every icon**: a 20px mark centred in a 36px well
  at an 8px radius. Brand SVGs disagree about their own internal padding,
  so "as large as fits" produced a column at visibly different optical
  sizes. The well's GEOMETRY is fixed and only its TONE is measured — black
  artwork gets the near-white plate an app store would give it, everything
  else keeps a quiet neutral, and the two fallback tiers sit on the same
  plate so one unknown app never looks broken.
- **Six apps still have no bundled mark, and nothing was invented for
  them.** BlueStacks, DirectX, CPU-Z, GPU-Z, HWMonitor and CrystalDiskInfo
  have no authentic logo in any open licensed set — re-measured across the
  full Simple Icons index, the `logos` collection, both MIT sets and
  Iconify's federated search. The near-misses are traps the search returns
  readily: `campaignmonitor` for HWMonitor, `crystal` (the programming
  language) for CrystalDiskInfo, `unrealengine` for Epic. A wrong logo is
  worse than no logo.

### Fixed — the hover border stopped changing the card's shape
- **Measured before it was touched: a hovered card painted 116 pixels of
  accent ink OUTSIDE its own rounded corners** (alpha up to 58, against 8
  pixels at alpha 13 at rest). The QSS was already geometry-stable in every
  state; the cause was the glow's 5px pen, centred on a path 1px inside the
  boundary, putting 1.5px of itself past the card at the corners. A
  silhouette that changes between two states reads as the box having moved.
  The edge painters now clip to the surface's own path and the halo is
  inset by half its pen width, so the light stops exactly where the card
  does. Inside the boundary nothing changed.

### Added — search that speaks the user's language
- **Arabic queries reach the operations they name.** `تحديث` → Check for
  Updates, `تنظيف` → Aggressive Cache Clean, `تسريع` → Optimize Drives,
  `برامج` → Software Catalog. The query is normalised first: harakat are
  optional, tatweel is decoration, and the alef, yeh and ta-marbuta forms
  depend on the keyboard — so the same word typed four ways folds to one
  string before anything compares it. The query is translated into the
  words the interface already uses; the results stay in the language the
  rest of the app is written in.
- **Typo tolerance**, as a bounded Damerau-Levenshtein pass over title
  WORDS: `cahce` finds Aggressive Cache Clean, `powr` finds the power plan,
  `startap` finds the Startup Manager. Bounded at one edit for short
  queries and two for long ones, and scored below every deliberate match —
  at distance 5 every short word is near every other short word.
- **English verbs**, for the same reason: a user types `uninstall` far more
  often than the noun a card happens to be titled with.
- **Group headings belong to their own rows again** — 12px of air above,
  tight below, and a hairline closing the group before. Bottom-aligned in a
  short box, a heading sat nearly equidistant between two groups and the
  list read as one undifferentiated column.

### Changed — chrome
- **The version appears once.** `v10.8.0` and a `BETA` pill sat immediately
  right of the title-bar wordmark, duplicating the sidebar status rail's
  `PULSE v10.9.0 · BETA` — which is also a button that checks for updates.
  One home, and it is the one that does something.
- **The title-bar brand lockup hides on the dashboard**, which carries its
  own masthead at six times the size forty pixels below it, and returns on
  every other view where it is the only thing naming the app.

### Fixed — packaging
- **Inno Setup's "launch when Setup finishes" no longer trips Windows App
  Control error 4551.** Setup runs elevated, so a direct `CreateProcess` of
  an exe whose own manifest asks for `requireAdministrator` is the shape
  App Control blocks. `shellexec` routes it through `ShellExecuteEx` for a
  normal elevation handshake, and `runasoriginaluser` starts it as the
  signed-in user — which is also what makes the first launch write its
  theme, geometry and log under the profile the user will actually look in.

### Fixed — tests
- **A once-in-ten-runs failure was a race, not a flaky widget.** Two
  bloatware assertions read `isVisible()` after a fixed 60ms settle, and
  showing a top-level window is asynchronous — inside the full suite it
  occasionally took longer. `conftest.wait_until` waits on the condition
  instead, which removes the race rather than re-tuning the sleep.

---

## [10.8.0] — 2026-08-30

Bloatware that stays removed.

### Added — the bloatware purge, in three tiers
- **`Remove-AppxPackage` alone is a temporary fix, and that is why removed
  apps came back.** The purge now runs three tiers, and skipping any one of
  them is a different way for the same app to return:
  1. the INSTALLED package, for every profile;
  2. the PROVISIONED template — the staged copy servicing re-applies, which
     is what puts an app back after a feature update or on a new profile;
  3. the CONTENT DELIVERY subscription that silently reinstalls promotional
     apps and re-pins their tiles on its own schedule
     (`SilentInstalledAppsEnabled`, `SubscribedContent-338388Enabled`,
     `PreInstalledAppsEnabled`, `OemPreInstalledAppsEnabled`,
     `SubscribedContent-338389Enabled`, `ContentDeliveryAllowed`), plus a
     Start-menu tile-cache rebuild so a dead tile stops being a live
     install link.
  Tier 3 is the one that makes the other two permanent. Every value is
  snapshotted through `Backup-OriginalRegValue`, so **Reset All Tweaks**
  puts the user's own settings back like any other policy Pulse writes.
- **A classified catalog replaces the flat name list.** 30 bare package
  names became 48 entries carrying an Id, a display name, a layer and a
  sentence saying what removing it costs — because a user looking at
  `Microsoft.549981C3F5F10` cannot tell it is Cortana, and a user looking
  at `Microsoft.XboxGamingOverlay` cannot tell that removing it takes Game
  Bar's screen capture with it. Four layers: `promo` (Instagram, Prime
  Video, Messenger, TikTok, Facebook, Disney+, the Spotify Store stub, the
  King suite, Sudoku, Solitaire, To Do, OneNote for Windows 10, Paint 3D
  and the rest), `core` (Phone Link and its host, Copilot and its web
  wrapper, Cortana, Mail and Calendar, the four Bing feeds, Maps, Feedback
  Hub, Get Help, Tips, Widgets), `gaming` (the Xbox stack) and `codec`
  (K-Lite, removed through the registry's uninstall string rather than the
  AppX pipeline).
- **The Xbox tier is optional and stays untouched by a bulk purge.** Game
  Bar's overlay is what Win+G opens and what most capture tools hook, and
  Store games sign in through `XboxIdentityProvider`. A control labelled
  "Select All Bloatware" that swept those would be the single most
  damaging click in the app, so `Optional` entries are never ticked by
  Select All and never removed by a headless `-Task RemoveBloatware`.
  **This changes `ApplyAllPrivacy`**, which previously took the whole Xbox
  stack with it.
- **Matching moved to wildcards, and wildcards needed a net.** Publisher
  prefixes and package suffixes move between builds — Phone Link is
  `Microsoft.YourPhone` on one and `WindowsPhoneExperienceHost` on the
  next — so the catalog matches on stable fragments. The cost is that a
  pattern can grow a match nobody intended, and the thing it grows a match
  on might be the shell: every candidate is therefore filtered through
  `$Script:BloatProtected` (the Store, winget, the VCLibs/.NET Native/WinUI
  runtimes, the shell and Start hosts, Search, Windows Security, Settings)
  and a pattern that reaches one of those **fails closed** — recorded as
  blocked, named in the log, never removed.

### Added — the Bloatware Purge selector
- **Scan first, then decide.** The card used to remove whatever the catalog
  listed without ever saying which of those were on the machine. It now
  opens a selector that scans, groups by layer, badges each row
  DETECTED / NOT PRESENT, names the actual package ids, and hands back
  exactly the shape every other selector does — a list on `-AppIds`, so the
  concurrency guard, the live console and the toasts are unchanged.
- **The selector replaces the confirm sheet rather than sitting behind
  one.** It names every package it is about to remove, which is a stronger
  confirmation than a yes/no dialog and a worse experience to click through
  twice.
- **Absent rows are folded away by default.** The catalog is 48 entries and
  a clean machine has one of them; the first build buried that one result
  under forty-seven "NOT PRESENT" rows across three sections. The section
  headers still report "1 of 25 present", and one checkbox unfolds the rest.
- **The scan is unprivileged; the purge is not.** Enumerating packages
  needs no rights, so opening the dialog never raises a UAC prompt. Reading
  the PROVISIONED list does need elevation, and when it fails the dialog
  says so — "clean" and "clean as far as I could see" are different claims,
  and only the second is true unelevated.

### Fixed
- **The applied-state probe would have reported every machine clean.**
  `11-StateProbe.ps1` tested the catalog with `-contains`, which is exact
  equality; against a list that had become wildcards it matches nothing,
  and "nothing remaining" is that probe's definition of APPLIED. It
  survived a live check only because two catalog entries are still literal
  names. Now matched with `-like`.

### Tests
- `tests/backend/Bloatware.Tests.ps1` — 20 Pester cases against a **mocked
  AppX inventory**. `Resolve-BloatwareTargets` takes the installed,
  provisioned and protected lists as arguments precisely so the dangerous
  rules can be exercised without removing anything: a protected package
  caught by a catalog wildcard, an entry that is provisioned but not
  installed, an empty selection meaning "the recommended set" rather than
  "everything", and a deliberately reckless `*Windows*` pattern that must
  fail closed.
- `tests/test_bloatware.py` — 13 cases on the seam between the two halves
  (every catalog group has a section and a plaque glyph, the optional tier
  agrees end to end) and on the safety policy only the GUI enforces
  (Select All never sweeps the optional tier, an absent package can never
  be selected).

---

## [10.7.0] — 2026-08-29

One accent, flat surfaces, and a shell that stops moving underneath you.

### Changed — the semantic palette
- **Seven module colours collapse to one interactive accent**, in both
  themes. The "Spectrum" identity was solved harder than anything else in
  the palette — a contrast floor per colour, peer parity measured
  in-plaque, an OKLCh chroma ceiling, a pairwise ΔE floor so no two
  modules rendered as one colour — and every one of those constraints was
  met while the result stayed the app's loudest problem. A module colour is
  constant INSIDE the module it names and redundant BETWEEN modules (the
  page header, the breadcrumb and the selected nav rail have already said
  where you are), so the hue was never distinguishing anything the user
  was looking at. What it did do was spend the whole chromatic budget on
  decoration, leaving emerald, amber and ruby competing with teal, pink
  and violet for the eye.
- **The brand sweep re-hues violet → magenta to indigo → cyan**, at FIXED
  LUMINANCE. WCAG's ratio is a function of luminance alone, so every
  measured relationship in the app — the beta pill, the update badge's
  tone ordering, the nav indicator, the aurora edge — carries over
  untouched and only the hue moves. Chroma falls 10.79 → 8.53 and
  12.01 → 7.17 as a consequence of the hue, not as a second edit.
- `test_no_two_modules_are_the_same_colour` **inverts** into
  `test_every_module_resolves_to_the_one_interactive_accent`, and a new
  ΔE floor guards the four tones that now do all the work (accent, ok,
  warn, err) — the guarantee it was making matters more with one accent,
  not less.

### Changed — surfaces are flat
- **No surface paints a gradient across its own face.** Every elevated
  surface was a `glass_fill`: a white sheen running down into the base
  over its top 13–20%. Consistent, and still the loudest thing on a
  category page — fourteen cards is fourteen luminance ramps on the exact
  surfaces whose job is to be a calm plate for text. Elevation is bought
  twice over at the EDGE, where it costs the plate nothing: the 1px
  hairline, plus the painted top sheen and multi-layer cast shadow.
- **The dark stack is the two neutrals the design language has**: canvas
  `#090A0B`, elevated surface `#121418`. v14 had spent the elevated value
  on the CONTAINERS, so the sidebar and content frame sat at card
  brightness and cards had to climb above them — three tones, with the
  card in the wrong place.
- **One hover weight, app-wide.** A card lifted toward indigo at 0.085
  while a menu row lifted toward white at 0.06: same pointer, same
  meaning, two colours at two weights depending on what it was over.

### Changed — the shell
- **The dashboard is a System Health & Quick Hub.** Four KPI tiles (CPU,
  memory, system drive, and the count of overdue operations across every
  module) sit above the quick actions, at ~84px against the 210px band the
  v1.0 RC pass deleted. The pending count is computed inside
  `_refresh_card_badges` — the one place the state probe and the run
  history are reconciled — so it cannot drift from the ACTION DUE chips
  the cards themselves are wearing.
- **One status rail closes the sidebar**, replacing four surfaces: the
  title-bar theme toggle, a full-width elevate CTA (or a full-width admin
  chip in its place), and the version line. ~110px becomes 36.
- **The title bar has no client holes left.** The theme toggle was an
  ordinary Qt button inside a strip answered entirely as HTCAPTION, so it
  needed a hand-measured HTCLIENT hole (`_over_theme_button`, DPI-aware
  physical-pixel mapping that had to track the button's geometry) just to
  receive a click. Both are gone;
  `test_the_caption_strip_has_no_client_holes_left` keeps it uniform.
- **The brand mark splits into a hero and a logo.** The title-bar
  instance was a Light-weight glyph at 58% of a 26px box, in the mid-tone
  accent, breathing down to 45% opacity — four choices each costing
  contrast. The static face is DemiBold, 20px in a 30px box (the app's own
  plaque glyph size), full opacity, painted in the brand sweep. The 58px
  dashboard mark still breathes.
- **The machine spec caption is gone** — `Windows 11 Professional · Build
  26200 · 12 Cores · 31.8 GB`, four facts that never change while the app
  is open, three of which the health row now reports live in the units
  that matter.

### Changed — the command palette
- **Results group under module dividers.** Rows were one concatenated
  string (icon, title, category, and the reason a catalog card matched),
  so they had one alignment: the module name was repeated on every row and
  long titles were pushed into an ellipsis by context nobody read twice.
  Rows are widgets now — glyph, title, right-aligned hint — with a `↵`
  keycap on the active row.
- Groups are ordered by their own best-scoring member, so **grouping costs
  no relevance**: the top hit is still the first row, it has simply
  acquired a heading. Arrow keys step over the dividers and wrap.
- **A hint bar states the palette's own bindings** (`↑↓ navigate · ↵ run ·
  esc close`) with a live result count. The app's only keyboard-first
  surface shipped with nothing saying what its keys did.
- The search field became a bordered frame around a chromeless input so it
  can carry a leading search mark; its focus ring moves to a dynamic
  property, because QSS has no parent selector and a `:focus` rule on the
  input would light a border nobody draws.

### Fixed — dialogs stop reserving space for content that is not there
- **`FitScroll` measured its content at the wrong width.**
  `layout.sizeHint()` is measured against the layout's PREFERRED width, and
  every wrapping label in the app prefers a narrower column than an 840px
  selector panel gives it — so the hint described a taller, skinnier
  version of the content than the one that got painted. The dialog sized
  itself to that phantom, the real text wrapped onto fewer lines, and the
  difference became dead space under the last row. Measured on the DNS
  switcher: 45px of void on a 467px dialog, entirely from asking the wrong
  question. Height-for-width is used where the layout has it, and a width
  change now invalidates the hint the same way a row change does.

### Changed — one spacing vocabulary
- **`SPACE` gains `ml` (20)** — the ramp's only 8px gap, and exactly where
  a dialog panel's padding wants to sit. **`PAD` names two of its steps**:
  `surface` (16) for anything with a hairline that sits in the layout,
  `sheet` (20) for a panel that floats. Dialogs drop from an unexplained
  24/24/24/16 to a square 20.
- **Home and a module page share one content column.** Both are swapped
  into the same stack inside the same content frame, and five containers
  had five padding recipes for one question: measured at 1500px wide, the
  dashboard's column started at x=347 and a category page's at x=331, so
  the content jumped sideways on every navigation.
- **One card-grid gutter (16px)** across the health row, the quick actions
  and every module page. Three grids ran at 12, 24 and 16 — and the first
  two sit one above the other on the same screen.
- **The quick actions are a 2×3 block at every width.** v14 allowed six
  columns from ~1440p up; at 2560 maximised that gave a 340px card whose
  own title wrapped, above a void. A capped-and-centred content measure was
  tried as the alternative and removed — it re-introduced the column jump
  at exactly the sizes this app is used at.
- Catalog tabs, the filter field, the page's filter combo, the storage
  drive picker and the Back/Home pills all move onto `CONTROL_H`; the
  control-height exemption list shrinks rather than grows.

### Changed — every launch elevates
- **The manifest now requests `requireAdministrator`** (`uac_admin=True` in
  `main.spec`), so Windows prompts for UAC before Pulse starts and the
  process always holds an Administrator token. ~24 of Pulse's tasks write
  HKLM, services or machine state, and prompting separately for each of
  them interrupts the work the tool was opened to do.
- **This reverses a v1.0 decision, and its consequences are real rather
  than theoretical.** Two are documented in the spec and accepted:
  the per-task elevation UI (`ElevatePromptDialog`, the sidebar CTA, the
  locked-card affordance, the "Not Elevated" chip) is now unreachable in
  the packaged app — it still runs from source; and packages whose
  installers set `elevationProhibited` (Spotify is the catalogued example)
  can no longer be installed through Pulse at all, because there is no
  unelevated mode left to fall back to.
- **Five messages that told the user to "run Pulse without elevating" are
  rewritten**, because that advice became impossible to follow. Being
  un-installable is a cost of this flag; advice that cannot be followed is
  a bug, and `test_packaging` now guards the difference.

### Changed — one place for everything Pulse writes
- **All logs, backups and downloads live under `%LOCALAPPDATA%\PULSE\`**:
  `Logs\`, `Backups\{Edge,OneDrive,Startup,Drivers}\` and `updates\`.
  Resolved through a single `Get-PulseDataPath` helper that creates the
  directory on the way, so a future writer cannot invent a fifth location
  by writing its own `Join-Path`.
- **Nothing is written to the Desktop any more.** Four backup folders were
  still landing there — `Pulse_EdgeBackup`, `Pulse_OneDriveBackup`,
  `Pulse_StartupBackup`, `Pulse_DriverBackup` — on the one surface where
  clutter is most visible, and on exactly the folder most likely to be
  cloud-synced, so a driver backup could upload itself. The log moved off
  the Desktop in v6.1 for that reason; the backups had the same problem
  and were left behind.
- **Legacy folders are MOVED, not read in place**, including the
  pre-rebrand `HTCore_*` names. A backup the user can still find is the
  point of taking one, so leaving the old copy behind would let "Open
  Backup Folder" and the restore path disagree about which snapshot is
  current. The Startup Manager's old code re-pointed its variable at the
  legacy folder instead of moving it, which had exactly that effect.
- The GUI's "Open Backup Folder" action resolves the new home first, with
  every historical location behind it, so a machine whose engine has not
  yet run and migrated still opens the right thing.

### Fixed
- `test_closing_settles_all_three_background_threads` held a Python handle
  on a QThread across the `deleteLater()` its own drain loop delivers, and
  raised `Internal C++ object already deleted` intermittently under load.
  The thread going away is what the loop is waiting for, so that is now
  the success case rather than a failure.
- Seven user-facing messages named a Desktop folder that no longer exists
  — a message pointing at the wrong place is as broken as writing there,
  since the user goes looking, finds nothing, and concludes no backup was
  taken. `tests/test_data_paths.py` guards both halves.
- `Restore-EdgeState`'s v5.x read fallback is gone rather than relocated:
  with the migration moving that folder at start-up, a second read path
  aimed at it could only ever disagree with the first.

---

## [10.6.0] — 2026-08-29

The background is gone, the dialogs fit what is in them, and every leading
icon is the same object.

### Removed — the ambient field, entirely
- **The canvas is one two-stop gradient (`#101216` → `#090A0B`) and
  nothing else.** v10.5 froze the ambient field; this release deletes it —
  five aurora orbs, 126 depth-tiered stars, the raster renderer, the
  OpenGL 3.3 renderer, the capability probe that chose between them, the
  frame governor, the deferral mechanism, and the occlusion system
  (`_sync_ambient_occluders`, `_queue_occluder_sync`, `_viewport_clip`,
  `GlassCard.opaque_core`, `theme.is_opaque`, `theme.opaque_core`) that
  existed only to stop it repainting pixels nobody could see. ~2,600 lines.
  A still field is a picture, and the picture it drew was noise over a
  gradient the shell was already painting underneath it.
- `PULSE_AMBIENT` and the OpenGL 3.3 optional requirement go with it.

### Changed — dialogs fit their content
- **Selectors hug their height.** A selector used to be handed a FIXED
  height derived from the window, so the Update Center holding ONE update
  rendered at the same size as one holding thirty — ~500px of empty black
  under a single row, which is the screenshot this release exists to
  delete. A one-row Update Center is now 255px tall; a 60-row one stops at
  the cap and scrolls inside it.
- Two causes, both fixed. `FitScroll` reports the height its CONTENT wants
  (a plain QScrollArea has no opinion, being a viewport onto something
  arbitrarily large) and subscribes to the content's LayoutRequest, so a
  list that streams rows in after construction re-measures itself.
  `fit_stack` makes a QStackedWidget report the CURRENT page rather than
  its tallest — the Update Center's one-row results page was reserving the
  height of its empty-state page, ~90px of black, forever.
- **Selector width comes down 800–1280 → 760–840**, and the action band
  stays 580–640. Past ~840 a row's text runs beyond the measure at which
  prose stays readable and a two-column row becomes two things separated
  by a void. The documented exception survives: a content floor wider than
  the band still wins, because a ceiling that clipped content would be
  choosing empty margins over legibility.

### Changed — one icon, one well, one row
- **Every leading icon is a 36×36 well, radius 8, filled
  `rgba(255,255,255,0.04)`** (inverted for light). It used to be four
  accent-tinted passes — an ambient halo walking outward through reserved
  padding, a gradient wash, an outer hairline and a lit inner rim — in the
  module's own colour, in both the card grid and the sidebar. Six accents
  across fourteen cards is six competing hues on one screen, and the glyph
  inside each well already carried that colour, so the well was saying it
  twice. The colour stays on the glyph; the well became a surface.
- `IconPlaque._PAD` is 0, so the widget IS the well: a leading icon is
  exactly `PLAQUE_SIZE` square everywhere, which is what made it worth
  standardising. Sidebar selection lifts the same neutral rather than
  colouring it.
- **`row_padding()`**: one 12px/16px inset for all five row types. Three
  had already converged on it; the action row ran 16/12/12/12 and the
  playbook step row 12/8/12/8.

### Fixed
- **A green test run could exit non-zero and abort the process**, with no
  traceback and its summary line missing — first on CI, then reproducibly
  here once deleting the ambient field removed ~150–360ms of deferral from
  every page transition and let dialogs be destroyed sooner. Two distinct
  causes, both real outside the suite:
  - a worker thread emitting a Qt signal whose owner had already been
    destroyed raises `RuntimeError` inside a slot on a non-main thread,
    which PySide6 treats as fatal (0xC0000409). Every emit in
    `PowerShellTask` and both self-update workers now goes through
    `safe_emit`, because a signal exists to tell an owner something and
    there is no owner left to tell.
  - `tests/conftest.py`'s `fresh_window` closed its cold windows but never
    destroyed them, so their C++ objects were freed whenever CPython
    collected the wrapper — potentially after `QApplication` was gone.
- `test_module_navigation_does_not_accumulate` counted every QObject under
  the window, which made it a function of how FAST navigation ran rather
  than of whether it leaked: toasts expire on a wall clock, and a faster
  sweep moved them across the baseline. It now counts pages and cards,
  which is what its docstring always claimed.

### Tests
- 833 pytest (832 passing, 1 environment skip) and 126 Pester. Down from
  893 because the two ambient suites (58 tests) tested a subject that no
  longer exists; the native count falls 119 → 80 for the same reason.
- New: content-hugging guards (a selector grows with its rows, stops at
  the cap, stays inside the width band at three window sizes, its stack
  reports the current page, `FitScroll` follows rows added later), the
  canvas ramp's two ends and neutrality, and an explicit assertion that
  every piece of the ambient field is gone.

---

## [10.5.0] — 2026-08-28

A still background, a compact action dialog, and an updater that says what
it is doing.

### Changed — the background stopped moving
- **The ambient field is static.** Five aurora orbs drifting and breathing
  on independent sine paths, 126 stars rising and twinkling, and a whole
  sheet leaning toward the pointer — all of it gone. The removal is
  implemented by *stopping time* rather than by deleting the field
  (`_AmbientSimulation.STATIC`): every pixel is a pure function of `_t`,
  the seeded scatter and the theme, so pinning `_t` at 0 yields the exact
  frame the animated field rendered at t=0. The constellation is still a
  constellation — each star's brightness comes from its own seeded twinkle
  phase, which is what keeps a motionless field from reading as 126
  identical dots — and every measured quality of the wash (star weight in
  both themes, wash neutrality, paint cost) is unchanged by construction.
- **An idle window now costs nothing at the bottom of its z-order.** The
  timer is built and never started: `_arm()` is the single choke point
  every path re-schedules through, and it refuses. The animated field's
  *cheapest* configuration was a full-window repaint ten times a second,
  and a repaint here is never "repaint the wash" — every surface above it
  is translucent, so Qt re-rasterised the whole stack (18.5ms at 1300x860,
  of which the card grid alone was 10.9ms).
- The pointer lean is neutered at its gain (`_POINTER_GAIN = 0.0`), because
  it is the one piece of motion a frozen clock would *not* have stopped: it
  integrates from `QCursor.pos()`, not from `_t`.
- `suspend()`/`resume()` keep their job — they still freeze the composited
  orb layer across an OS move/resize loop, which is a real cost even for a
  field that does not animate. `defer()` becomes a no-op; its callers are
  asserting "the GUI thread is about to be busy", which stays true.
- The GPU renderer's orb texture is now explicitly invalidated on a theme
  change. It was rebuilt on a cadence measured against `_t`, so against a
  frozen clock a toggle would have baked the previous theme's aurora into
  the texture for the life of the process — a bug that could not exist
  while the field was animating.

### Changed — dialogs
- **A new ACTION band, 580–640px wide, with height that hugs its content.**
  The Microsoft Edge and Microsoft OneDrive hubs offer two actions each and
  were built on the *selector* band, so they opened at up to 1280x900: two
  tiles, stretched and centred, in a panel sized for a fourteen-card page.
  Card-shaped rows made that unfixable — a `GlassCard` caps at 156px and
  cannot absorb a panel's worth of slack, so the surplus fell into the gaps
  whatever the layout did with it. A two-action hub is now a ~320px panel
  holding exactly two actions.
- **`ActionRow`**, the row those hubs are built from: left-aligned icon in
  the shared `PLAQUE_SIZE` well, title over description, and one button at
  the right edge. A column of them has two hard vertical rules, which is
  what makes a list scan as a list rather than as three independent boxes.
- **Destructive rows are a translucent tinted fill plus a hairline**
  (`DANGER_TINT` 0.08, `DANGER_LINE` 0.22), replacing the high-contrast red
  wireframe. A wireframe makes the teardown the loudest thing on a dialog
  whose other option is the safe one — it advertises exactly the action the
  user is least likely to want. Text contrast on the new fill is measured
  and pinned (14.0:1 / 15.8:1 for the title, 8.1:1 / 7.4:1 for the
  description).
- A destructive row is **button-only**: the whole row is clickable
  elsewhere, the way a native settings list behaves, but a stray click on a
  description must never start something irreversible.
- **`dialog_footer` / `size_dialog_button`.** Footer button widths came off
  twelve different literals — 90, 96, 110, 112, 120, 122, 128, 132, 140,
  150, 160, 170, 214 — one per button, for one element. They are now
  `CONTROL_H` tall with a 96px floor and grow to fit their label, which
  also fixes the buttons whose labels are not fixed: the Update Center's
  CTA cycles through "Update Selected", "Update Selected (3)" and "Update
  All (14)" inside what used to be one 160px box.
- The three read-only inspectors' Close buttons were 88px — the one family
  in the app whose Close was visibly narrower than every other dialog's.
- **Dialog panels finally cast both halves of their elevation.** Every
  panel was built without a theme, so it wore an outer shadow with no
  contact edge and no lit top face — a shadow printed behind a flat shape,
  which is the exact failure `DepthCard`'s own docstring calls out. The
  ambient layer moves to `DIALOG_SHADOW` (`0 12px 32px rgba(0,0,0,0.45)`,
  down from a 42px blur at 0.59) and the contact ramp is now painted.

### Changed — menus, dropdowns and icons
- **One shared material for every floating list** (`menu_surface_qss` /
  `menu_item_qss`): 12px surface radius, 10px of vertical lead per row, and
  a *neutral* translucent hover pill. The command palette was hovering on
  `card_hover`, the accent-tinted card lift, so scrubbing the results
  painted an indigo streak down them; the combo popup had no hover rule at
  all and no item padding. New `row_hover` token, inverted rather than
  re-alphaed for light (white at any weight is invisible on porcelain).
- **`TH.ICON`, the fifth scale.** Glyphs shipped at six hand-picked sizes,
  and three of those were the *same element* — a Fluent glyph in a
  `PLAQUE_SIZE` well — drawn at 16px in the sidebar, 21px on a card and
  19px in a dialog row. `PLAQUE_SIZE` exists so that object is one object;
  letting the well agree while the glyph disagreed by five pixels was the
  same defect one level further in. Three tiers (`micro`/`inline`/`plaque`),
  enforced by `test_layout_contract`.

### Added — the live app updater
- **A process termination guard that is not a nine-entry lookup table.**
  Windows will not replace a file that is open for execution, so an update
  applied over a running app either fails outright or half-applies.
  Termination used to be `$Script:LockProcessMap` alone — exactly right for
  its nine apps, and silently absent for the ones most likely to be running
  when the user updates them. The map survives as the authoritative layer;
  under it, an app is now matched by process name, by the executable's
  `ProductName`, or by its install directory.
- **The guard is conservative on purpose.** Terminating the wrong process
  is unsaved work, gone, with no undo and no error message. Every rule is
  an *equality* on a normalised name, never a substring; candidates under
  four characters are refused as coincidences; and a hard denylist (the OS,
  the shell, and Pulse's own process tree) outranks every rule. When
  nothing matches, nothing is killed.
- **Closing is graceful first.** `CloseMainWindow()` sends the same WM_CLOSE
  clicking the X does, so an app with unsaved work shows its own save
  prompt and the user gets to answer it; only what survives six seconds is
  terminated.
- **The Update Center says which apps are running before the button is
  pressed.** The scan reports it per row (a `RUNNING` chip naming the
  processes), and applying a selection that includes one confirms it *by
  name* — "3 apps will be closed" is not something anyone can decide with,
  because the whole question is which ones.
- **The phase channel is wired to the pipeline every operation runs
  through.** `##PULSE##STAGE|` has existed since v10.3 and only the Update
  Center's own scan dialog listened to it, so a task that closed a running
  app, downloaded 90MB and verified the result reported all three as an
  undifferentiated scroll of winget output under a rail that said
  "Executing: Update Selected Apps" for eight minutes. Phases now reach a
  fixed chip in the Activity drawer, the rail (alongside the task name),
  and the console transcript: `[3/14] Mozilla Firefox` → `Closing Mozilla
  Firefox (firefox)...` → `Downloading Mozilla Firefox 145.0 (replacing
  144.0)...` → `Verifying...` → `Verified 144.0 -> 145.0`.
- **Updates are verified against the machine, not against an exit code.**
  After a successful winget run the installed version is re-read and the
  actual `old -> new` transition is reported. Never downgraded to a
  failure: a package whose version winget cannot resolve after a clean
  install is a reporting gap, not a broken install.

### Fixed
- **Phase markers could be eaten by carriage-return progress.** A marker
  appended just before a winget percentage frame became the console's
  newest line, so the frame *rewrote* it and every completed phase vanished
  from the exported log. `LiveConsole.append_marker` makes a marker
  un-overwritable exactly once — a CR rewrite means "replace what I just
  wrote", and a marker is not something the stream wrote.
- **The process guard's match set could silently become substring
  matching.** PowerShell enumerates a collection on return, so a
  `HashSet[string]` holding one key came back as a bare `[string]` and
  `$Keys.Contains($x)` stopped being set membership. Combined with an
  unreadable `ProductName` comparing as `""` (and `"anything".Contains("")`
  being true), the guard matched 107 of 235 processes for an app that does
  not exist. Comparison now goes through `Test-AppKeyMatch`, which
  validates both ends and can only ever test equality.
- **The install-directory rule matched ancestors.** Steam installs every
  game under `Steam\steamapps\common\<game>\`, so "update Steam" resolved
  to the user's running game and offered to close it. Only the leaf
  directory is consulted now, which still catches everything the rule
  exists for.

### Tests
- 893 pytest (up from 838) and 126 Pester (up from 101).
- New: `tests/backend/ProcessGuard.Tests.ps1` (25) covers the guard's
  matching rules, its denylist and its dry-run behaviour against a
  synthetic process table — a real `Get-Process` would make "did this
  match?" mean something different on every machine.
- New: `tests/test_live_updater.py` (19) covers the phase channel end to
  end, marker survival against CR progress, and the running-app
  confirmation.
- `ElidedCaption` gains two: a caption on a padded plate must elide
  inside its contents rect, not clip against its outer width.
- `test_ambient.py`'s motion section is replaced by a stillness section
  that asserts the inverse contract at every layer that could reintroduce
  motion; `TestAmbientDefer` becomes
  `TestAmbientQuietDuringNavigation`, which keeps the guarantee the
  deferral existed to provide now that it is unconditional.

---

## [10.4.0] — 2026-08-28

The v14 surface pass, a decluttered Activity rail, and the first release
whose CI is green end to end.

### Changed — the v14 surface pass
- **Both palettes move to Fluent 2 / macOS container layering.** Canvas →
  raised container → card, each step lighter, with elevation carried by a
  hairline and a cast shadow rather than by tone. Dark runs `#090A0B` /
  `#121417` / `#181A1F` on neutral greys (the old `#14171F` shell top
  carried a visible blue cast); light runs an `#F3F4F6` canvas with pure
  white surfaces. The dark content well **inverts** — it used to recess
  into near-black, which a jet base has nowhere left to do — and light's
  cast shadow rises `0.080 → 0.105` to pay for the tone it gave up.
- **Dark ambient orb peaks come down 40%.** The wash was solved against a
  well that was 45% near-black and *subtracted* from it; on the raised
  container the old peaks took the canvas to `#1A1D25`, the muddy navy the
  obsidian pass exists to remove. `test_ambient`'s wash-neutrality guard
  now covers both modes instead of light alone.
- **The Activity rail carries four controls, not nine.** Everything that
  describes the *output* moved into the drawer body where the output is; a
  "clear the output" button beside a collapsed drawer acts on something the
  user cannot see. The size grip went entirely — the window owns a real
  Win32 sizing frame on every edge. The status line is now an
  `ElidedCaption`, which takes the rail's minimum from 621px to 206px, so
  it finally fits at the window's own minimum width with a task running.
- **The update chip became the sidebar's `UpdateBadge`,** sitting directly
  above the identity line that was already its manual trigger, and shows
  only when it has something actionable to say.
- **Grids and dialogs bound both axes.** Category grids cap at six columns,
  not four — at four a maximised 4K window handed every card ~860px, which
  is not density. Dashboard actions split evenly (1/2/3/6, never an orphan
  row) and their top air is a *bounded* stretch. Responsive dialogs gain a
  height ceiling; on a 2160p display one was opening 1674px tall around
  eight rows of content.
- `PLAQUE_SIZE` and `CONTROL_H` join `SPACE`/`RADIUS`/`TYPE` as named
  scales, both enforced by `test_layout_contract`.

### Fixed — rendering and window behaviour
- **The black edge during a live resize.** The window now paints its own
  canvas with an object-bounding gradient brush — the same ramp the shell
  paints, rescaled to any rect — so the strip Windows reveals mid-drag
  carries the right colours, and `WM_ERASEBKGND` is answered so
  `DefWindowProc` never fills between the two. A flat fill had replaced the
  black tear with a visibly mismatched band.
- **A maximized window showed resize cursors on edges it cannot be resized
  from.** "No resize border while maximized" was only ever expressed by
  *not answering* `WM_NCHITTEST` and trusting `DefWindowProc` to infer it
  from `WS_MAXIMIZE`. On PySide6 6.11.2 that assumption stopped holding —
  same styles, same `-9,-9` rect, `HTLEFT` two pixels inside the left edge.
  The intent is stated outright now.
- **`$profile` was assigned in two scopes in `15-Network.ps1`,** shadowing
  the PowerShell automatic variable. Renamed to `$dnsProfile`.
- **`11-StateProbe.ps1` and `14-Inspectors.ps1` carried non-ASCII with no
  BOM,** so Windows PowerShell 5.1 was *misreading* them at runtime.

### CI — green end to end
- **All four jobs are green for the first time in this history.** The two
  PowerShell jobs had been red on a cause outside the repo: the runner
  writes each `run:` block as BOM-less UTF-8 and `shell: powershell` reads
  it as cp1252, so an em-dash in a message decoded to a smart quote —
  which PowerShell accepts as a *string delimiter* — and the step cascaded
  into parse errors naming unrelated lines.
- **The pytest job's twelve failures were three problems.** The runner's
  desktop was 1024×768, clamping every window (`resize(1150,780)` came back
  `(1044,780)`) and taking seven geometry tests with it; the wall-clock
  render budget was set for a developer box; and two playbook tests guarded
  on `PULSE_TESTS_ELEVATED`, an environment variable nothing set, so they
  asserted on a `CreateRestorePoint` failure that an elevated runner never
  produced. `conftest.is_elevated()` asks the OS instead.
- **The native-suite floor had gone toothless.** Written when 713 tests
  collected and 106 were native, it stayed at 670 while the suite grew to
  838 with 115 native — so a headless runner would have executed ~716,
  cleared the floor, and passed having tested no Win32 behaviour at all.
- `tools/build_release.ps1` finds a `winget`-installed Inno Setup, and no
  longer resolves `$Iscc` to the single character `C` when exactly one
  candidate is found.


### Also in this release

Work that had accumulated under `[Unreleased]` and ships here for the first time.

#### Removed
- **The Software Catalog's quick-select stack chips** — *Java / University
  Stack*, *AI / Python Stack* and *Web Dev Stack*. They were a third way
  to narrow a list that already narrows two ways (tabs by category, field
  by name), they applied to one tab out of five, and they were the only
  control in the dialog that appeared and disappeared as the tab changed.
  The Development & Tools tab answers the same question by being read.
  `CATALOG_BUNDLES` / `CATALOG_BUNDLE_SECTION` and their backend mirror
  `$Script:DevHubBundles` are gone with them (nothing in the backend ever
  read the mirror), and `test_contract.py` now fails if either comes back.

#### Fixed
- **Light mode rendered black chrome on every GPU machine.** The ambient
  field's star pass blended with `glBlendFunc(ZERO, ONE_MINUS_SRC_ALPHA)`
  in light mode — `dst = (1-a)*dst` on colour *and* alpha, applied by every
  fragment a point sprite rasterises, rim fragments included. Across 126
  overlapping sprites the canvas decayed toward black and toward alpha 0,
  and `QOpenGLWidget` composites a transparent pixel to black rather than
  revealing the shell beneath. Measured standalone: 23 of 25 sample points
  fully transparent at 0.09 luminance where the light canvas should be
  0.92. Now a single premultiplied source-over (`ONE,
  ONE_MINUS_SRC_ALPHA`) for both themes — which is what `_STAR_FRAG`
  always emitted — giving 25/25 opaque at 0.93, with dark byte-identical.
- **A displaced grey rectangle hung outside the shell at fractional DPI.**
  `_draw_orbs` restored the viewport with `glViewport(0, 0, w, h)` in
  *logical* pixels after rendering the orb buffer, but `QOpenGLWidget`
  allocates its framebuffer in *device* pixels. At 125% that rasterised
  the blit and every star into the bottom-left 80%×80% of the surface,
  leaving an unpainted band across the top and down the right edge. It
  struck roughly one frame in six — only when the orb buffer rebuilt on
  its 100 ms cadence — which is why it read as a random flicker, and it
  vanished at integer scaling or on the raster path. `gl_PointSize` had
  the same logical/device confusion and drew every star 1/dpr too small.
- **Closing the window during a background check could abort the process.**
  `closeEvent` joined the task thread and neither of the other two. The
  state probe and the self-update check were left running while Qt
  destroyed them, which raises `RuntimeError: Signal source has been
  deleted` at best and qFatals at worst. All three now settle through one
  path: cancel, quit, bounded join, and — only if still running — signals
  severed and the thread un-parented so Qt cannot destroy it mid-run.
- **The maximized `WM_NCCALCSIZE` inset never ran.** It was guarded by
  `IsZoomed()`, which reads the `WS_MAXIMIZE` style that this very message
  is part of setting; traced live it returns `False` for every
  `NCCALCSIZE` of a maximize, so the branch was dead
  (`GetWindowPlacement().showCmd` is stale in exactly the same way).
  Replaced with a state-free clamp to the monitor work area, which is a
  no-op on the path Qt actually takes and a correction on any path that
  proposes an oversized rect. `theme.resize_border_thickness()` went with
  it — that inset was its only caller.

#### Changed
- **Cards now read as surfaces in both themes.** A card measured 1.12:1
  against the content well in light and 1.11:1 in dark — legible text on a
  surface that was itself invisible. Light buys its separation from
  `overlay` (the well behind the cards, which carries no text) rather than
  the canvas, reaching 1.38:1; dark raises the card itself, since near
  black the WCAG `+0.05` floor dominates and darkening the well bought
  only 1.11 → 1.15:1. Both land at a ceiling set by *existing* AA
  contracts, not by preference: the status badge holds dark's card at
  `#22252E`, and the active filter chip — whose knockout text is
  `bg_solid` — is why light's canvas could not move at all. Two new
  guards, `_SURFACE_PAIRS` and `_BORDER_PAIRS`, pin elevation and hairline
  separation, which nothing measured before.

#### Added
- **`tools/diagnose_edge_bleed.py`** — a rendering-artifact bisector that
  runs the app with one subsystem disabled at a time (integer DPI, raster
  ambient, no `QGraphicsEffect`, square corners). It located the
  fractional-DPI viewport bug in one pass after geometry analysis had
  cleared every "obvious" suspect, because the defect was in the viewport
  drawn *into* a correctly sized surface.
- **The self-updater is wired into the GUI.** `src/utils/updater.py`'s
  `check()` / `download()` / `verify()` / `apply()` had no caller anywhere
  in `src/frontend/` before this — the SHA-256 verification described in
  the README's Safety Model ran in no live code path. Three call sites now
  exist: a silent background `check()` ~2.5s after launch (never an error
  dialog — see the module's EVERY NETWORK FAILURE IS SILENT policy), the
  sidebar footer's version label doubling as a manual "Check for updates"
  button, and a new `widgets.SelfUpdateDialog` (notes → progress → ready →
  error) that owns `download()`/`verify()` on its own worker thread —
  following the same `PulseDialog.done()` teardown contract as every other
  worker dialog — before handing a verified installer path back to
  `main.py`, which calls `apply()` and quits. A build that fails
  `updater.can_apply()` (running from source) gets a "View Release" link
  instead of a button that would fail the moment it's clicked. Still moot
  for the live v10.3 release asset, which publishes no `SHA256SUMS`; that
  remains tracked in the Roadmap.
- **A denser, deeper ambient field.** The background wash went from three
  orbs and 42 flat motes to **five orbs and 126 stars in three depth
  tiers** — far stars small, dim and slow; near ones larger, brighter and
  quicker — plus two smaller, dimmer orbs that lean hardest on the pointer
  parallax, so the field has a front and a back instead of reading as one
  sheet. Stars are now cached soft-glow textures blitted at native size
  rather than antialiased ellipses, which is what makes 3x the density
  cost *less* than the old field did (0.26ms per paint for 126, against
  0.17ms for 42); the first cut scaled one texture per star and cost
  1.5ms, which is the difference between a blit and a resample.
  - Density is not intensity: per-star alpha and the light-mode orb peaks
    are unchanged in character, and the light canvas still measures as the
    neutral system grey the palette specifies (mean channel spread 3.9,
    against 10.4 for the peaks that once dyed it lavender). Four new
    ambient contract tests pin the tier structure, the texture cache, that
    wash measurement and the orb layer's 10Hz rebuild budget.
- **Two new spacing steps and a test that enforces the whole scale.**
  `SPACE["xxs"]` (2px, leading inside one text block) and `SPACE["xxl"]`
  (32px, air around an empty state) close the ramp at both ends, and
  `test_layout_contract.py::test_every_layout_measurement_comes_off_the_scale`
  now walks the frontend's AST and fails on any `setSpacing` /
  `addSpacing` / `setContentsMargins` literal that is not a scale step.
  57 calls had drifted back to hand-picked numbers (1, 2, 3, 6, 7, 9, 10,
  14, 18, 20, 28, 30, 34) — every one within 2px of a step it could have
  used, which is precisely the "almost aligned" feel the scale exists to
  prevent. All 57 now come off the scale.
- **A guard against stock platform chrome.** Stacks, scroll areas and
  self-scrolling lists are the only widgets that paint Windows' own
  chrome when left unstyled, and four surfaces were: the Office wizard,
  the Update Center and the Startup Manager each drew a sunken Fusion
  frame around their pages, and the Ctrl+K palette and both card grids
  showed stock scrollbars with arrow buttons. `theme.stack_qss()` is now
  the one place a stack is styled, `command_list_qss` carries the shared
  scrollbar rules, and a new test constructs every dialog and page and
  fails on any unstyled one.
- **Activation Status** — a new read-only card under *Safety & Recovery*
  reporting Windows and Office licence state. It answers the three
  questions a technician actually has about a machine: is it licensed,
  under which channel (retail / OEM / volume-KMS / MAK / subscription),
  and does that licence expire. Each state is shown as a tone-coloured
  verdict pill plus a plain-English sentence explaining what it means —
  `LicenseStatus` is an integer the licensing service never explains, and
  it is now translated in exactly one place (`Get-ActivationStatusDetail`)
  so the GUI, the console view and the log cannot describe the same code
  differently.
  - New backend module `src/backend/modules/13-Activation.ps1`, with a
    HARD READ-ONLY contract inherited from `11-StateProbe.ps1`: it reads
    the Software Licensing WMI providers and formats what they say. It
    does not install a product key, contact a licensing server, or alter
    licence state — pinned by
    `test_contract.py::test_activation_module_is_read_only`, which fails
    on `slmgr`, `ospp`, `ActivateProduct`, `Invoke-CimMethod`,
    `Invoke-Expression`, `Invoke-WebRequest` and `Start-Process` alike.
  - Needs **no elevation**: every property read is available to a standard
    user, so the card answers in full from an unelevated Pulse. The one
    field that genuinely requires admin (the OEM firmware licence) reports
    *unknown* rather than a false "absent".
  - Both Office licensing platforms are queried and merged — modern
    Click-to-Run / Microsoft 365 under `SoftwareLicensingProduct`, and
    Office 2010-era installs under `OfficeSoftwareProtectionProduct` — so
    an absent provider is never mistaken for "Office is unlicensed". A
    separate install probe distinguishes *no Office on this machine* from
    *Office installed but holding no licence*, which are opposite findings
    that both produce an empty licence list.
  - When something needs changing, the dialog hands off to Windows' own
    activation page (`ms-settings:activation`) rather than acting on the
    licence itself.
  - Also reachable from the standalone console app: **Safety & Recovery →
    [5] Activation Status**.
- **Contract tests** for three drift classes that previously had none: a
  GUI-local `@action` with no handler in `main.py` (it used to fail at
  click time with "Unknown local action"), a card `glyph` absent from
  `theme.GLYPHS` (renders a blank icon plaque, silently), and the
  activation module's read-only guarantee.

#### Changed
- `HealthReportDialog`'s private row/note/heading renderers were lifted to
  module-level `report_row` / `report_note` / `report_heading` primitives
  now shared with the activation report. Both surfaces render the same
  shape of content and must colour a tone identically — two private copies
  of that mapping would eventually disagree about what amber means.

#### Fixed
- **The ambient field froze through every tab switch and resumed from a
  stale position** — reported from real-world testing on low-spec hardware
  as the background orbs stopping dead and restarting their path. Nothing
  ever reset them (`_build_particles` runs once, in `__init__`);
  `AmbientGlow._tick` returned *before* integrating while deferred, so a
  page switch cost the field the entire deferral — 150 ms warm, 360 ms the
  first time a module is opened. Measured over a three-lap sweep of all
  four modules: the field advanced **661 ms of a 2695 ms sweep (75%
  frozen)**, in dead stalls of up to **1061 ms**; on a simulated low-spec
  profile, 74.8% frozen with 1194 ms stalls. It now advances **99.9%** of
  wall time, with no stall longer than one tick interval.
  - The deferral itself is unchanged and still does its job: the cost it
    exists to keep out of a transition is the **full-window repaint**
    (18.5 ms, of which 10.9 is the card grid) forced through every
    translucent surface above the glow — not the arithmetic over 126
    particles and five orbs, which is microseconds. The tick now skips the
    paint and keeps the maths.
  - The frame governor no longer reads a **deferred** tick's lateness as
    thread contention. It was ratcheting the field toward its 220 ms
    ceiling on the way through a transition that added no repaint, then
    crawling back at 10% a frame for ~1 s *after* the switch had finished
    — most of "the particles choke when I change tabs" on a slow machine.
  - `test_navigation_perf.py`'s `test_a_deferred_field_does_not_advance`
    asserted on `_t` as a *proxy* for "did not repaint" (sound only while
    the two were the same event). It now asserts the repaint directly, and
    a sibling pins that the field keeps simulating.
- **Destroying a dialog with a live worker thread aborted the process.**
  Seven dialogs run a `PowerShellTask` on a `QThread` parented to
  themselves and cancelled the worker on close — but cancelling only kills
  the backend *process*; the thread lives on while its read loop unwinds,
  and destroying a running `QThread` is `qFatal`, not an exception: no
  traceback, no Qt warning. `main.PulseApp.closeEvent` had always paired
  `cancel()` with `wait(3000)`; the dialogs only ever did the first half.
  `PulseDialog.done()` — the funnel `accept()` and `reject()` share — now
  joins them, discovering threads by scanning `__dict__` so no name list
  can go stale.
  - **Grace before cancel**, not cancel-first: the DNS switcher and
    context-menu manager run tasks that *write* and neither overrides
    `reject()`, so a plain cancel could strand an adapter with its IPv4
    resolvers changed and its IPv6 ones not. A worker gets
    `_WORKER_GRACE_MS` (1200) to finish on its own before it is killed.
    Measured: 0.5 ms for already-cancelled read-only dialogs, ~740 ms for
    a DNS apply that is allowed to complete.
  - Unreachable from the shipped UI by luck rather than design —
    `_exec_dialog` drops its reference but the dialog is parented, so C++
    keeps it alive past the danger. It was reachable from the test suite,
    where it **killed the runner mid-session** instead of failing, which
    is why the leak roster in `test_audit_hardening.py` had stopped at the
    eleven thread-free dialogs. All eighteen are now covered.

---

## [10.0.0] — 2026-07-28

The v10 UX overhaul. The app version was pinned at 6.1 while the
design system moved through v7-v10; this release reconciles them,
so `APP_VERSION`, `$Script:ScriptVersion`, the README badge and
this changelog all read 10.0.

### Added
- **Keyboard access to the operation grid.** `GlassCard` was a `QFrame`
  with mouse handlers only — no focus policy, no key handling — so the
  app's primary surface was unreachable by keyboard and Tab stopped at the
  sidebar. Cards now take `StrongFocus`, activate on Enter/Space with the
  same press + ripple feedback a click gives, traverse with the arrow keys
  across the live (filter-aware) grid, carry accessible names/descriptions,
  and paint a solid 2px accent focus ring — Qt's dotted default is
  invisible against this material.
- **A real shortcut layer**, up from two bindings (Escape, Ctrl+K):
  `Ctrl+1…6` jump to a module, `Ctrl+H` the dashboard, `Ctrl+L` / `Ctrl+F`
  the page filter, `Ctrl+\` the live output, `F1` / `?` a keyboard sheet.
  Bindings and the help sheet are generated from one table
  (`PulseApp.SHORTCUTS`), so a shortcut cannot exist undocumented — which
  is how Ctrl+K stayed undiscoverable for four releases.
- **Category filter rail** — an inline filter field and an operations count
  chip fill the previously empty right two-thirds of every module header.
  The filter matches titles, descriptions *and* a hub's sub-item titles, so
  searching "office" surfaces the hub that contains it instead of hiding a
  real match; the chip switches to "3 OF 12" and takes the module accent
  while a filter is active, and an explicit empty state replaces the blank
  grid when nothing matches.
- **Live output is no longer a dead end** — copy, save-to-file, clear and a
  timestamp toggle in the Activity rail. Copy and export report line counts
  through the app's toast stack, and a failed write is reported as a
  failure rather than silently implying the log was saved.
- **Applied-state badges** — cards for readable tweaks now show a green
  `APPLIED` chip when the setting is currently active on the system, so
  Pulse finally answers "did I already do this?" without re-running an
  operation and reading the log. Backed by a new read-only backend probe
  (`src/backend/modules/11-StateProbe.ps1`, task `GetTweakState`) covering
  Dark Mode, mouse acceleration, Minimalist Taskbar, Classic Context Menu,
  Game Mode, Advertising ID, Activity History, Telemetry, Hibernation and
  the Ultimate Power Plan. The probe runs on its own thread outside the
  single-task pipeline, needs no elevation, writes nothing (verified: its
  output is byte-identical with and without `-WhatIf`), and is never
  cached — settings changed outside Pulse are reflected immediately. An
  unreadable check reports *unknown* and shows no chip rather than
  guessing.
- **Recent Operations panel** in the sidebar — the last three completed
  operations with their module colour and a pass/fail dot, one click to
  re-run. Fills what was ~360px of dead rail. Re-runs resolve back to the
  live catalog entry, so they always use the current definition.
- **Preference persistence** (`src/utils/prefs.py`, QSettings) — theme,
  window geometry, Activity-drawer pin state and the recent-operations
  trail now survive a restart. Previously every session opened dark, at
  the default size, with the drawer unpinned.
- **Windows 11 Snap Layouts on the maximize button** — hovering the
  custom maximize button now summons the native Snap Layouts flyout,
  via the `WM_NCHITTEST → HTMAXBUTTON` contract from Microsoft's
  custom-titlebar guidance: Windows owns the button's mouse events
  (hover is mirrored with a `nchover` property flip, the click is
  re-injected from `WM_NCLBUTTONUP`), and hit-testing is computed
  window-relative in physical pixels so mixed-DPI multi-monitor setups
  can't skew it.
- **Smart Skip, made visible**: `Smart-Deploy` now returns a distinct
  `AlreadyCurrent` flag alongside `Status='Success'` (never renamed
  `Status` itself — several existing call sites checked `-eq 'Success'`
  directly and would have silently broken from a rename). Already-current
  results now print with `Write-AlreadyOK` (green ✓, same color as
  `Write-Success` by design — see the color-scheme note below) and a
  distinct "already up to date - skipped" message, and both
  `Invoke-GuiBulkDeploy` (GUI) and `Process-AppCategory` (console) tally
  them in their own bucket: "3 installed, 2 already up to date" instead of
  the old blended "5 installed or already current."
- **Strict 3-color status scheme, enforced**: `Write-AlreadyOK` used a
  mismatched `DarkCyan` instead of `Write-Success`'s green — a real
  inconsistency in exactly the way the request described. Green (✓) now
  means success or already-current everywhere, uniformly; red (✗) means
  failure; yellow (!) means warning/notice. Session summary
  (`Show-MainMenu`) gained a `$Script:SessionSkipCount` tracked separately
  from successes, shown as "N succeeded / N already up to date / N failed"
  when non-zero.
- **MSYS2 added to `LockProcessMap`** (`mintty`, `bash`, `pacman`) — a
  leftover MSYS2/MinGW terminal holding files open is the most common
  real-world cause of the `SHELLEXEC_INSTALL_FAILED` conflict above;
  closing them before install/upgrade avoids it instead of just reporting
  a cryptic failure afterward.
- **Path Doctor, re-engineered for plain-language clarity**: opens with a
  beginner-friendly explanation of what PATH actually is and why the check
  is harmless (user-scope, no elevation). Each of the 7 tracked tools
  (`$Script:DevToolCatalog`) gained a `Why` field — a one-line "why you'd
  want this" reason surfaced both after "already working" confirmations
  and next to "not installed yet" notices — and the closing summary
  distinguishes "nothing to fix" from "N fixed, N still missing" instead
  of a flat stats line. Mirrored in the GUI's toast message and the
  Software Management card description.
- **Developer & University Hub moved back inside Software Management** —
  it was split out into its own top-level sidebar category last session;
  per this request it's folded back in as two cards (Developer Toolkit,
  PATH Doctor) right after Essential Apps, keeping the sidebar to the
  original six categories. The underlying `DevHubSelectorDialog` /
  `ToolInstallWizardDialog` / catalog data are unchanged — only where the
  entry point lives moved.
- **Developer & University Hub** — a new top-level category, precisely
  separated from every other app list (zero hardware drivers, zero
  general-purpose apps): 16 tools across five sections (Core Runtimes &
  Compilers, IDEs & Editors, AI & Local LLM Stack, Databases & API Tools,
  Containerization), all new to the catalog except the six migrated from
  the retired "Programming & AI Core" card. New entries: IntelliJ IDEA
  Community, Docker Desktop, DBeaver, Postman, Bruno, Open WebUI, Node.js
  and Java JDK promoted from PATH-doctor-only to directly installable,
  Python promoted the same way. Every winget ID was verified live via
  `winget show` before being added — nothing here is guessed.
  - **`DevHubSelectorDialog`** — manual-first (nothing pre-checked), with
    a master Select All/Deselect All, three quick-select bundles (Java/
    University Stack, AI/Python Stack, Web Dev Stack) that tick their
    tools without forcing anything, live dependency hints (checking
    NetBeans/IntelliJ/PyCharm softly highlights its still-unchecked
    runtime — correctly handles two IDEs sharing one runtime, verified
    with an explicit test), and a per-tool "⋯" button.
  - **`ToolInstallWizardDialog`** — the "⋯" button's generic 3-path
    dialog: Path A narrows the normal bulk winget deploy to just that one
    tool (no new backend code — it's the existing selection/deploy
    pipeline with one AppId), Path B opens the vendor's official page,
    Path C hands a picked local installer to the new generic
    `InstallLocalFile` task (`Invoke-GuiLocalInstall` in
    `04-SoftwareEngine.ps1`: msiexec for `.msi`, direct run otherwise, no
    forced elevation — installers that need it self-elevate via their own
    UAC manifest, same as a manual double-click).
  - **PATH Doctor**, promoted to its own prominent card in the new hub
    (moved out of Software Management). Runs at user scope
    (`[Environment]::SetEnvironmentVariable(..., "User")`) — genuinely no
    elevation required for a per-user PATH/JAVA_HOME repair; over-elevating
    a user-scope operation would be a step backward, not a feature.
  - Fixed a real bug caught during verification: `,@("id","name")`, not
    `@(@("id","name"))`, for a single-tool catalog array — PowerShell
    silently flattens the latter (`@( @(x,y) )` unwraps to a flat 2-element
    array when it's the ONLY item), which broke Docker Desktop's entry
    until an explicit array-shape test caught it.
- **Three-path Office wizard** — `OfficeWizardDialog`'s single "locate your
  files" flow is now three up-front paths:
  - **Path A: Automated Cloud Download** (task `InstallOfficeODTAuto`,
    backend `Invoke-GuiOfficeAutoDownload`) — fetches
    `officecdn.microsoft.com/pr/wsus/setup.exe` directly (the same stable
    CDN endpoint winget's own `Microsoft.Office` manifest uses) rather than
    scraping Microsoft's download-center page for the versioned
    `officedeploymenttool_*.exe` link. That file already IS the extracted
    Click-to-Run client, so there's no self-extractor dialog to click
    through at all. Writes a built-in default `configuration.xml`
    (`Get-OfficeDefaultConfigXml`) only if the target folder doesn't
    already have one. The wizard states plainly that this default targets
    Volume License/KMS activation, not a plug-and-play key.
  - **Path B**: unchanged auto-detect / browse / individual-file-pick flow.
  - **Path C: Beginner Guide** — numbered, plain-language walkthrough of
    downloading the ODT and building a configuration.xml via Microsoft's
    own tools (the former single "download" step), feeding into Path B's
    locate flow once the files exist.
  - **Multi-config detection** — `Find-OfficeConfigFile` / the wizard's
    `_find_office_files` now recognize OCT's own export naming
    (`configuration-Office365-x64.xml` etc.) in preference order; if a
    folder has more than one `.xml`, the wizard shows a picker (top match
    marked "recommended") instead of silently grabbing the first one
    alphabetically.
- **Office Deployment Tool wizard** (`widgets.OfficeWizardDialog`, task
  `InstallOfficeODT`) — replaces the winget-based Office install (which
  could only apply Microsoft's stock default configuration) with a
  4-step guided flow that preserves full `configuration.xml` control:
  choose to download the official ODT + Customization Tool (direct
  browser links) or locate files already on disk (auto-detects
  `Desktop\Office`, including the OneDrive-redirected and Public Desktop
  variants, with a folder browser and an individual-file-picker fallback),
  then a confirm step with a prominent amber warning ("don't close the
  setup window") before handing off to the normal task pipeline — same
  live console, Stop button and toast machinery as every other task.
  Backend: `10-Office.ps1`'s new `Invoke-GuiOfficeODTInstall` reuses the
  existing self-extractor/validation helpers but never prompts (the
  wizard already collected consent client-side); gated by
  `AdminRequiredTasks` since `setup.exe /configure` needs elevation.
  `core.ps1` gained `-OfficeSetupPath`/`-OfficeConfigPath` params, threaded
  through `PowerShellTask` from the resolved wizard paths. The
  `$Apps_Office` winget catalog entry for the Office bundle itself is
  removed (Word/Excel/etc. have no per-app winget package, only a
  default-config ODT run); Teams and OneDrive remain on the ordinary
  winget path as `$Apps_OfficeCompanions`, exposed as their own card.
- **Unified glass material system** (`theme.glass_fill`) — cards, Welcome
  insight tiles and dialog panels now share one frosted-glass gradient
  definition instead of three that had quietly drifted apart (card/insight
  sheen stops were 0.12 vs 0.15). Dialogs (`ConfirmDialog`,
  `AppSelectorDialog`, `CommandPalette`) also gained the same painted
  bevel edge (`DepthCard`) cards already had — previously every dialog was
  a flat rectangle while every card had visible glass depth.
- **Brand duotone gradient** (`theme.brand_gradient`) — the violet `accent2`
  color existed only in the shimmer bar; it's now part of a deliberate
  accent→accent2 sweep reused on the primary dialog button, the selected
  sidebar item, and the running-state pill, so the two-tone brand reads as
  one system. Danger confirmations (Purge OneDrive, Remove Edge, etc.)
  deliberately keep a flat solid red — no gradient on a "hard to undo"
  action.
- **Active nav indicator bar** — the selected sidebar item now shows a
  short rounded accent→accent2 bar on its left edge, the same affordance
  Windows 11 Settings uses for its selected nav entry.
- **Horizontal scrollbar styling** — `scroll_area_qss`/`console_qss` only
  styled the vertical scrollbar; any control needing horizontal scroll
  (the card grid or app-selector list at a narrow width) fell back to the
  raw unstyled OS scrollbar. Both now match.
- **Microsoft Office Suite catalog entry** (`$Apps_Office` in
  `01-Catalogs.ps1`, mirrored in `menu_structure.py` as `InstallOfficeApps`)
  — Word, Excel, PowerPoint, Outlook, OneNote, Access and Publisher via the
  `Microsoft.Office` winget package (Microsoft 365 Apps for enterprise,
  silent Click-to-Run default install — no `configuration.xml` needed),
  plus Microsoft Teams and OneDrive as real standalone winget packages.
  Reachable from the GUI's Software Management category and the console's
  App Deployment Hub `[E]`, through the same checkbox multi-selector and
  `Smart-Deploy` pipeline as every other app category. The advanced,
  config.xml-driven ODT flow (`Show-OfficeDeployment`, console-only) is
  unchanged and still covers custom deployments winget's default config
  can't express.
- **Command palette (Ctrl+K)** — fuzzy-search quick launcher over every
  task in `menu_structure.py`. Runs picks through the normal
  `request_task()` pipeline (confirmations, the app selector, and the
  single-task-at-a-time guard all apply, exactly as a card click would).
- **Glass bevel on every surface** (`animations.paint_bevel_frame`) — a
  permanent diagonal-gradient stroke (bright top-left highlight → soft
  bottom-right shadow) on operation cards, sidebar nav buttons, and the
  new `DepthCard` (Welcome insight tiles + status dock). One painted
  stroke, no offscreen shadow buffer, and no Qt corner artifacts (the
  failure mode per-side `border-*-color` QSS rules hit on rounded rects).
- **Click ripple** (`animations.RippleController` /
  `paint_ripple_frame`) — an expanding, fading accent-tinted ripple from
  the click point on cards and nav buttons, clipped to the rounded rect.
- **Icon "pop" on hover** — GlassCard icons grow subtly (28→31px), driven
  by the existing hover-glow intensity via a managed `QFont` (never a
  per-frame stylesheet rebuild).
- **Breathing status dot** — the bottom-bar `●` now pulses softly only
  while a task is actually running (`widgets.StatusDot`, the same
  pure-paint technique as `BreathingIcon`), and goes still the instant
  it's done.
- **Custom console empty state** — `LiveConsole` paints a small on-brand
  "pulse" waveform motif + message in place of the generic placeholder
  text, replaced live the instant real output streams in.

### Changed
- **Design-system foundations** — a single spacing scale (`TH.SPACE`) and
  semantic radius scale (`TH.RADIUS`) replace 13 ad-hoc spacing values and
  17 ad-hoc corner radii; card padding is symmetric.
- **Light-mode ambient wash pulled back** (multiply peaks 0.30→0.16) — the
  v10 canvas deepening made the old strength read as a lavender haze.
- **Modal presentation system** — every dialog now shares one
  construction path (`widgets._dialog_chrome`): frameless panel at its
  exact content width inside a transparent shadow gutter, a soft
  elevation drop shadow, and body-anchored positioning
  (`_present_dialog`) that always places the panel fully below the
  title bar (command palette top-anchored, everything else centered in
  the body; nested wizards climb to the app window). Opening any dialog
  raises a dense theme-aware **scrim** over the app body, so the card
  grid and console are completely masked while a modal is up — and the
  scrim deliberately stops at the title bar, which stays uncovered.
  Dialog action buttons unified at 36px height.
- **Title bar strip is now native HTCAPTION** — dragging, Aero Snap,
  double-click-to-maximize and the right-click system menu are handled
  by Windows itself (only the theme toggle keeps a client hole), which
  also means the strip keeps working while a modal dialog is open.
- **Software Management unified with the Developer Hub pattern** — every
  `apps` catalog card (Essential Apps, Gaming Launchers, Hardware
  Diagnostics, Core API Runtimes, Teams & OneDrive) now opens the same
  elite selector the Dev Hub uses: identical rows (checkbox + per-tool
  "⋯" install-options wizard offering **winget / official website /
  local installer file**), a Select All / Deselect All toolbar with a
  live "n selected" counter, and a "Deploy Selected (n)" primary
  action. Catalog entries gained GUI-only description + official-URL
  metadata (4-tuples, legacy 2-tuples still accepted); the backend
  contract is untouched — core.ps1 still receives only the ticked
  winget IDs, and a wizard's local-file pick routes through the
  existing InstallLocalFile task exactly like the Dev Hub.
- **Responsive card grid** — category pages no longer force 3 columns:
  column count follows the viewport (1 col under ~680px of content
  width, 2 at the default window size, 3 maximized on widescreen), so
  cards keep a ≥340px footprint, descriptions never clip, and the
  default view reads as a spacious 2-column layout instead of three
  cramped slivers. Verified live on the Windows platform at
  1020/1180/1860px → 1/2/3 columns.
- **Breathing-room pass** — body/sidebar/content margins, card padding
  (20×16, min height 132), grid gutters (18px), dialog padding (28×24)
  and the type scale (title 20px, body 13px, desc/tagline 12px) all
  moved one comfortable step up; long card titles now wrap instead of
  clipping.
- **Full dual-theme re-grade (frontend only — zero backend changes).**
  Dark mode moved from saturated navy + neon cyan to a deep
  charcoal/slate register (Linear / GitHub-dark territory): `#0f1115`
  base, elevation via lightness steps, calm azure `#58a6ff` + soft
  violet `#a78bfa` brand pair reserved for interactive states. Light
  mode is no longer blinding: a cool porcelain-gray canvas (`#eceff4`)
  with translucent soft-white cards — pure white never appears as a
  full-page surface. All four text tones re-tuned for WCAG AA on the
  new surfaces.
- **Toast notifications redesigned from scratch** (`utils/helpers.py`):
  now theme-aware (the old toast was a hardcoded dark rectangle that
  looked broken in light mode), anchored bottom-right in the VS Code
  register so they never cover the title bar or caption buttons,
  click-anywhere-to-dismiss, hover pauses the auto-hide countdown,
  duplicate messages extend the live toast instead of stacking, and the
  stack is capped at four with oldest-yields eviction. Status reads as
  a quiet ✓/✕/i chip + colored spine instead of emoji.
- **Title bar rebuilt to native-caption grade**: Segoe Fluent Icons /
  MDL2 caption glyphs (the OS's own minimize/maximize/restore/close
  characters), a solid caption-red close hover exactly like native
  Win11 windows, and the brand block now renders name · version · an
  elegant violet **BETA** channel pill (`APP_CHANNEL` in `main.py`).
- Card/nav spacing tightened for a cleaner rhythm: card description
  spacing 4→6px, category grid gutter 14→16px.
- `ConfirmDialog`'s outer panel margin (26, 24, 26, 22) now matches
  `AppSelectorDialog`'s (24, 22, 24, 20) — the two are the same "panel +
  body + actions" pattern and had drifted to slightly different insets.
- **Faster, snappier motion**: hover glow, page fade, card cascade, dialog
  entrance, theme cross-fade, and toast animations were all retuned into
  the 90–190ms band (from up to 300ms) for a lighter, more immediate feel.
  The shimmer progress sweep (an indeterminate loop, not a transition) is
  unchanged.

---

### Fixed
- **Card descriptions were being silently truncated.** Measured across the
  real catalog at the 3-column grid width, 14 cards had their description
  cut off mid-sentence (worst: PATH Doctor, losing 88px — over half its
  text) and 5 also lost part of their title; nothing warned, the text was
  simply painted outside the card's clip. Cards are rebuilt with a header
  row (icon + title) above a **full-width** description — the description
  column was ~256px and is now ~312px — plus a hard per-block line budget
  (`ClampedLabel`) that elides with the full text in a tooltip. Catalog
  copy was tightened to match. Result: **0 truncated cards** across 540
  instantiations (2 themes × 6 widths × the whole catalog).
- **Window resizing leaked ~12 GB and stuttered.** `AmbientGlow` cached its
  aurora orbs keyed on the window size, so every pixel of a drag-resize
  minted three fresh ~1800×1800 pixmaps and kept them forever: a single
  1000→1440px drag produced **1,323 cached pixmaps totalling 11.9 GB** at
  34.9 ms/frame. Orbs are now rendered once at a fixed texture size and
  scaled on blit — **3 pixmaps, 3.0 MB, 15.3 ms/frame**.
- **Grid reflow could place cards outside their container.** Column counts
  were derived from the page width while cards were laid out inside a
  scroll host whose width settles a layout pass later; when the two
  disagreed the grid overflowed (measured: a 1719px-wide grid inside a
  590px host). Reflow is now driven by the host's own resize
  (`ResponsiveGridHost`), so the width that picks the column count is the
  width the cards are laid out in.
- **Card entrance animation fought the layout.** `CascadeAnimator` drives
  card positions directly; a resize mid-cascade left cards stranded at
  stale coordinates. It now abandons the entrance when the host resizes
  and hands placement back to the layout.
- **Minimum window size is derived, not guessed** — it is computed from the
  chrome plus one minimum-width card, so the window can no longer be
  dragged to a size where the grid cannot lay out. The Welcome page's
  Quick Actions gained a scroll area; without one a short window resolved
  the impossible constraint by crushing cards to as little as 17px.
  Verified across 448 (page × size) combinations.
- **Light mode's colour system failed contrast.** The six module accents
  were single hex literals shared by both themes and tuned for a near-black
  canvas; against the light card they measured **1.86–2.64:1**, far under
  the 3:1 floor for an icon. They are per-theme tokens now
  (`theme.resolve_accent`), re-resolved on every theme switch, and every
  one clears 4.5:1 as text and 3:1 as a glyph in both modes.
- **The text ramp's bottom two steps failed AA.** `text_faint` measured
  3.00:1 and `text_muted` 3.98:1 on a card while carrying 10–13px copy.
  The ramp is rebuilt evenly in CIE L\* with its floor pinned at 4.55:1 —
  four visibly distinct steps, all legible.
- **Elevation was nearly invisible.** Card-vs-content-well separation was
  1.20:1 (dark) / 1.21:1 (light). Depth now comes from recessing the
  content well rather than brightening the card (which would have wrecked
  the text ramp above it): **1.46:1 dark, 1.27:1 light**.
- **Toasts covered the live console.** A fixed bottom margin put the toast
  stack on top of the Activity drawer exactly when a task was running. The
  stack now tracks the drawer's height live.
- **Dialog titles were never actually enlarged** — all 8 built their header
  as `label_qss(t, "card").replace("14px", "16px")`, but the card role has
  been 16px since v7, so the replace matched nothing. Added a real
  `dialog` type role (18px/700).
- **Edge force-removal now resolves `setup.exe` dynamically** — Edge's
  uninstaller lives under a per-version folder
  (`…\Edge\Application\<VERSION>\Installer\setup.exe`) that changes on
  every update; `Remove-MicrosoftEdge` (`06-Tweaks.ps1`) now hunts it
  recursively under both Program Files roots (newest version wins)
  instead of relying on a path that went stale (the cause of setup.exe
  exiting with code 93 / never running). The Appx cleanup pass now
  **excludes `Microsoft.MicrosoftEdgeDevToolsClient`**, a hard-protected
  Windows 11 OS component that always fails `Remove-AppxPackage` with
  `0x80070032` and previously aborted the whole removal into a false
  failure.
- **Window controls blocked while a modal was open (critical)** — the
  old dialogs centered over the whole window, physically covering the
  caption buttons, and Qt's application modality blocked title-bar
  clicks besides. Dialogs are now always positioned below the title
  bar, and because minimize/maximize/close run through the raw
  non-client path (`WM_NCLBUTTONUP` in `nativeEvent`), they bypass
  Qt's modal input blocking entirely — verified live with real window
  messages while a selector was open: hit-testing answered
  HTCLOSEBUTTON and a posted NC click minimized the window with the
  modal still up. Closing during a modal settles open dialogs first
  (reject) so no exec() loop is orphaned.
- **Modal bleed-through, eliminated at the source** — beyond the opaque
  panels, the new body scrim masks *everything* around an open dialog;
  nothing underneath is legible anymore in either theme.
- **Caption-button hitbox (critical)** — closing the window demanded a
  pixel-perfect hit on the 40×30 glyph. WM_NCHITTEST now maps
  generously expanded non-client zones over minimize/maximize/close
  (HTMINBUTTON/HTMAXBUTTON/HTCLOSEBUTTON): the strip from the window's
  top edge to below the buttons, from the minimize button's left edge
  to the window's right edge, split at gap midpoints — so clicking
  anywhere in the top-right corner region registers, exactly like a
  native app, and the literal screen corner closes a maximized window
  (Fitts corner-slam). Clicks are re-injected from WM_NCLBUTTONUP with
  hover mirrored per-button; a swept probe confirmed zero dead pixels
  across the entire strip. Resize borders keep priority while floating,
  matching native ordering.
- **Text bleed-through in overlays** — dialog surfaces were 98–99%
  opaque, so the card grid/console underneath ghosted through as
  overlapping text when selectors and wizards opened. Dialog
  backgrounds are now fully opaque (toasts 99%), and card titles wrap
  rather than overflow.
- **Maximized click-through corners (critical)** — on a frameless
  per-pixel-alpha window, the corner pixels DWM rounds away are alpha-0
  and clicks fell straight through to whatever app sat behind Pulse.
  DWM corner rounding is now explicitly disabled while maximized
  (`DWMWCP_DONOTROUND`) and restored on unmaximize, so a maximized
  Pulse is square, opaque and click-owning edge-to-edge like every
  native Win11 app.
- **Fixed-size first launch overflowed small screens** — the hardcoded
  `1180×740 @ (140, 80)` geometry was taller than a 1366×768 laptop's
  work area (and worse at 125%+ DPI scale). The window now sizes to the
  monitor's available geometry, centers itself, and clamps its minimum
  size so it can never be forced larger than the screen it lives on.
  Fractional DPI scale factors are passed through exactly
  (`HighDpiScaleFactorRoundingPolicy.PassThrough`) for pixel-crisp
  rendering at 125/150/175%.
- **Console UTF-8 output encoding** — `core.ps1`'s interactive console mode
  never set `[Console]::OutputEncoding`, so on the default OEM code page
  (437 on US-English Windows, confirmed live) every box-drawing character
  and status glyph (✓/✗/═/║) rendered as mangled question marks and
  garbage. The GUI's spawned subprocess already had this fix
  (`helpers.PowerShellTask` sets it before invoking `core.ps1`); the
  interactive console never did. This was very likely the actual cause of
  "the UI looks chaotic" — verified before/after with the exact same
  glyphs: garbage without the fix, clean boxes with it.
- **Three winget exit codes were mislabeled** in `Resolve-WingetExitCode`,
  cross-checked against winget-cli's own `AppInstallerErrors.h` (not
  memory or a forum post): `-1978335215` was labeled "no applicable
  upgrade" and treated as a **silent success** — it's actually
  `INSTALLER_HASH_MISMATCH`, a corrupted-or-tampered-download failure that
  was being reported as "completed successfully." `-1978335189` and
  `-1978335153` were labeled "package not found" / "file in use" — both
  are actually "nothing to update" signals and are now correctly treated
  as an already-up-to-date skip instead of a failure. Added the exit code
  from this request, `-1978335226` (`SHELLEXEC_INSTALL_FAILED` — the
  wrapped installer itself failed, the common MSYS2 case), with a
  specific, actionable message instead of a generic "unhandled exit code."
- **`Get-InstalledVersion`'s column parsing was silently broken** for
  every call site: it split `winget list` output on 2+ spaces, but winget
  only pads columns for a real interactive console — the instant Pulse
  captures the output (which is always), padding can collapse to a single
  space and the split always failed, meaning the "already up to date"
  fast-path check *always* fell through to a live `winget upgrade`
  invocation it didn't need to make. Fixed to find the exact-match AppId
  token and read the next token as the version — verified against a real
  installed package (Git) confirming the instant-skip path now actually
  fires, plus a constructed edge case where the display name collides
  with winget's own Name column.
- Retry-with-`--force` no longer fires on an "already current" exit code
  it didn't recognize — the gate checked one hardcoded code, so the two
  newly-recognized "nothing to update" codes would have forced an
  unnecessary reinstall instead of honoring the skip.
- **Maximized/fullscreen layout** — the shell's floating margins no longer
  survive maximize: `body`'s content margins now collapse to a slim
  comfort gap in lock-step with the existing corner/border flush, so a
  maximized window sits truly edge-to-edge instead of floating inside a
  dead-space frame.

### Removed
- Dead code: `total_operations()` (`menu_structure.py`), `HoverGlow` /
  `PulseAnimation` (`helpers.py`, long superseded by `animations.py`), and
  the unused `hero` / `value` / `meta` label roles — all with zero call
  sites. (`category_operations()` was removed as dead and then reinstated
  later in this same release, when the new category count chip gave it a
  real call site.)

- **Dual-theme legibility & finish pass** — light mode's two lower text
  steps deepened (`text_muted` #5d6879 → #4e5a6c ≈ 6:1, `text_faint`
  #8d97a8 → #75808f ≈ 4:1) killing the washed-out body/caption reading,
  and card hairlines strengthened (0.11 → 0.14 alpha) so white-on-porcelain
  cards keep distinct edges; dark mode's `text_faint` lifted one step
  (#5a6272 → #646e80) for 10px captions on dim laptop panels. Grouped hub
  landing screens gained commercial-grade section headers: accent-tinted
  letter-spaced titles finished with a 1px accent rule fading toward the
  panel edge (`hub_group_header_qss` / `hub_group_rule_qss`), with
  proximity-correct rhythm (headers sit tight over their own cards, a
  full step clear of the previous group). Interaction polish: selector
  rows now lift fill *and* border on hover (matching GlassCard),
  checkbox wells pre-tint with the accent on hover and acknowledge the
  cursor when checked, and dialog Cancel/Close buttons match the primary
  button's 600 weight with a firmer hover border.
- **System Tools & Utilities hub is now grouped, not a flat list** — its
  eight sub-actions are split into three scannable sub-groups the
  HubDialog renders under small section headers: **Diagnostics &
  Optimization** (Hardware Diagnostics, PATH Doctor, Startup Manager,
  Check for Updates), **Microsoft Edge** (Remove / Install-Restore), and
  **Microsoft OneDrive** (Purge / Install-Restore) — each app's teardown
  now sits directly beside its restore. Hubs may now carry `groups`
  (titled sections) in place of a flat `items` list; `menu_structure.hub_items()`
  flattens either shape so the command palette, counters and hub
  navigation are unaffected.
- **Browsers & Daily Apps trimmed to three core selections** — Browsers,
  Chat & Media / Microsoft Office Suite / Core API Runtimes. The combined
  "Teams & OneDrive" card was removed; OneDrive's install/restore now
  lives beside Purge OneDrive under System Tools & Utilities
  (`RestoreOneDrive`).
- **Microsoft Teams dropped from the catalog entirely** — purged from
  `$Apps_OfficeCompanions`, the download-URL and lock-process maps
  (`01-Catalogs.ps1`), the retired `InstallOfficeApps` GUI task
  (`30-GuiDispatcher.ps1`) and the console App Deployment Hub
  (`20-Menus.ps1`, now a OneDrive-only category).

---

## [6.1.0] — 2026-07-19

### Added
- **Official application icon** (`assets/pulse.ico`, seven sizes 16–256px):
  the Pulse four-pointed star on a deep-navy plate, shown in the title bar
  and taskbar (with an explicit `AppUserModelID` so source runs don't group
  under python.exe) and embedded into `Pulse.exe` via `main.spec`.
- **Native Windows 11 window behavior**: dragging uses the OS system-move
  loop (real Aero Snap zones, drag-to-top maximize, native
  restore-from-maximized), the outer 8px is a native `WM_NCHITTEST` resize
  border with real cursors, Win+Up/Down work via min/max window hints, and
  a maximized window drops the floating radius/border so corners sit flush.
- **Micro-interactions**: 220ms cross-fade on theme switch, weighted press
  tint on operation cards, `:pressed` states on every button, dialog
  entrance fade, and a settle-upward fade on returning Home.

### Changed
- **Enterprise color grading** for both themes: neutral deep charcoal-navy
  dark mode and cool-gray light mode, calmer Fluent-adjacent accents
  (`#4cc2ff` dark / `#0067c0` light), GitHub-grade status colors replacing
  the neon green/gold/coral, matching category accents and toast colors,
  and the sheen-gradient glass treatment extended to the Welcome insight
  cards for one consistent material.
- **Hardened verdict contract**: the backend's final line is now sentinel-
  prefixed (`##PULSE##SUCCESS|…` / `##PULSE##ERROR|…`) and the GUI scans
  backwards for it, so stray trailing output from a module or external tool
  can never shadow the verdict. Bare `SUCCESS|`/`ERROR|` lines from pre-6.1
  backends still parse via a strict fallback; the console displays the
  verdict without the machine sentinel.
- **Log relocated** from the Desktop to `%LOCALAPPDATA%\Pulse\logs\
  Pulse_Log.txt` with size rotation (5 MB threshold, five archives kept).
  A OneDrive-synced Desktop no longer pays sync traffic per log line. An
  existing v6.0 Desktop log is migrated automatically; the in-app log opener
  falls back to the legacy Desktop locations.
- **UPX disabled** in `main.spec` — packed executables are a classic
  antivirus false-positive heuristic; an elevated system tool cannot afford
  that reputation risk.

### Added
- `ROADMAP.md` — the three-phase plan (v6.1 Trust & Hardening, v6.5
  Resilience & Native Feel, v7.0 Orchestration).

---

## [6.0.0] — 2026-07-19

### Changed — Rebrand to Pulse
- The project, application, window branding, terminal banners, and executable
  are now **Pulse** (`dist\Pulse.exe`).
- Runtime artifacts renamed: session log `Desktop\Pulse_Log.txt`, snapshot
  registry root `HKCU:\Software\Pulse`, Desktop backups
  `Pulse_{Edge,OneDrive,Startup,Driver}Backup`, power scheme
  **Pulse Power Plan**, restore point **Pulse Restore Point**.
- **Migration shims** keep v5.x machines whole: the legacy
  `HKCU:\Software\HTCoreArchitecture` snapshot root is copied once to the
  Pulse root; Edge/startup restores and the in-app log/backup openers fall
  back to the old `HTCore_*` Desktop artifacts; an old-named power plan is
  renamed in place instead of duplicated.

### Added
- **Global kill switch** — a danger-styled *■ Stop Task* button in the console
  header hard-terminates the running task's entire process tree
  (`taskkill /T /F`: PowerShell plus its winget/sfc/DISM children). The engine
  reports a distinct `cancelled` outcome — never a fake error — and the UI
  resets immediately. One terminal signal per task, guaranteed:
  cancel > timeout > contract verdict.
- **True real-time console** — the worker reads the pipe in binary chunks with
  an incremental UTF-8 decoder and understands bare carriage-return rewrites,
  so `sfc` / `DISM` / `winget` progress updates a single console line live;
  per-chunk coalescing keeps the GUI event queue bounded on chatty tools.
- **Execution state pill** (IDLE / RUNNING / SUCCESS / ERROR / STOPPED) beside
  the console header, plus a transient green/red **verdict flash** on the card
  that launched the task.
- Refined frosted-glass theme tokens (stronger borders, card sheen gradient)
  in both dark and light modes.

### Changed
- Complete repository meta-file overhaul: rewritten `README.md`, comprehensive
  `.gitignore`, added `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`,
  `.editorconfig`, `.gitattributes`, and GitHub issue/PR templates.
- `requirements.txt` cleaned up: removed the unused `customtkinter` dependency
  (the GUI is pure PySide6); build tooling moved to `requirements-dev.txt`.
- `main.spec` (PyInstaller build recipe) is now version-controlled.

### Core (PowerShell v4.0 → v6.0)
- Version aligned with the GUI. Every GUI task now opens with a timestamped
  start banner in the live console, and SFC output streams line-by-line while
  it scans (previously buffered until the scan finished).

---

## [5.1] — 2026-07-07

### Added
- **PySide6 (Qt 6) frontend** replacing the earlier CustomTkinter prototype:
  frameless glass-morphism window, dual light/dark themes with live switching,
  60 fps motion system (glow, shimmer, cascade, page fade), live task console,
  and toast notifications.
- **Modular frontend blueprint** — menu data (`menu_structure.py`), design
  tokens (`theme.py`), motion (`animations.py`), components (`widgets.py`),
  and threading utilities (`utils/helpers.py`) fully separated from the
  orchestrator (`main.py`).
- **Per-app checkbox selector** for winget catalogs — install only the apps
  you tick.
- **System insights dashboard** — OS build, CPU, and RAM read via registry
  and kernel32 with zero third-party dependencies.
- **One-file PyInstaller distribution** (`main.spec`) bundling the GUI and
  the PowerShell core into a single elevated, windowed executable.

### Fixed
- Qt thread-safety: PowerShell now runs on a `QThread` and reports back
  exclusively through Qt signals — widgets are never mutated from a
  background thread.
- Non-interactive guard: when dispatched from the GUI, the core never blocks
  on console input or pops browser/Store windows mid-run.

### Core (PowerShell v3.3 → v3.4)
- New **Safety & Recovery** hub: one-click rollback to the session restore
  point, *Reset ALL Tweaks*, *Restore All Services*, and an in-app log viewer.
- Every reversible tweak snapshots its **original** value before changing
  anything, so resets restore your real prior settings.
- Automatic System Restore point before the first system change of any
  session, across all modules.
- Edge removal backs up Preferences/Bookmarks/Favicons; OneDrive removal
  offers a Desktop backup first.
- Failed operations (SFC/DISM, Edge removal/reinstall, restore points) can be
  retried in place.

---

## [1.0] — 2026-07-06

### Added
- Initial release: data-driven PowerShell deployment & optimization framework
  (`core.ps1`) with a self-elevating launcher, hierarchical terminal menu,
  winget-based software deployment, registry tweak engine, SFC/DISM repair
  automation, privacy hardening, and session logging.

[Unreleased]: https://github.com/Humam-Taibeh/Pulse/compare/master...HEAD
