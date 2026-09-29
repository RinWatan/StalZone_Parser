# Game overlay implementation plan

Goal: compact Windows overlay expanding into the existing application.
Architecture: one Tk root, persistent full and compact frames, shared App
worker and result queue. Separate stalzone_overlay.py owns window state,
local settings and Windows global hotkey polling on the Tk thread.

Constraints: codex/game-overlay only; preserve main and dist/STALZONE.exe;
no credentials in source, commits or executable. Ctrl+Shift+Space toggles
visibility. Settings are local and ignored. No game process integration.

- [x] Add tests/test_overlay.py: real Tk integration with catalog loading
  disabled; compact start, full/compact persistence, worker preservation,
  deal clearing, busy controls, hide/show and settings corruption/clamping.
- [x] Run `python -m unittest discover -s tests -v`, record missing feature.
- [x] Create stalzone_overlay.py with fit_geometry, load_settings,
  GlobalHotkey and Overlay. Keep callbacks on the Tk thread; gracefully
  report hotkey conflicts; unregister on shutdown; atomically save settings.
- [x] Wrap App._build contents in full_frame; initialize Overlay after
  building; forward fill(buys) and _busy to compact controls. Keep original
  analysis methods intact. Compact scan captures buys then restores selector.
- [x] Run tests and fix failures. Review diff for focus, hidden window
  recovery, duplicate workers and secret exposure.
- [x] Add build_overlay.bat producing STALZONE-overlay.exe without packaging
  credentials, plus usage instructions. Build with installed Python313.
- [x] Verify EXE archive has no exbo.json; launch compact EXE and check
  switching, hotkey and window response on Windows. Report game check as
  unverified unless tested in the actual game.

Execution: inline in this chat; user requested no further approval rounds.
