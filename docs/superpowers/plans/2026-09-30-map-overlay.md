# Map overlay implementation plan

**Goal:** merge the colleague's Leaflet map into the compact/full STALZONE HUD on branch codex/map-overlay.
**Architecture:** one pywebview page retains market tables, workers and Leaflet instance. A toolkit-independent HUD controller serializes Win32 operations; the JS bridge queues commands and exposes snapshots. No browser embedded into Tk.
**Tech stack:** Python 3.13, pywebview 6.2, Windows WebView2, Win32, Leaflet 1.9.4.

**Constraints:** preserve main/old EXEs; do not bundle, stage or upload exbo.json. Map and API need network. The HUD uses the existing EXBO window detector and borderless game mode.

- [x] Replace Tk controller tests with native-interface tests, observe failing import.
- [x] Refactor GameWindow to use an HWND getter; implement controller and standalone hotkey.
- [x] Add compact HTML UI and bridge HUD commands; keep map/tab/worker state on mode switches.
- [x] Verify controller tests, bridge persistence and actual WebView2 rendering/map loading.
- [x] Update build instructions, package a separate EXE, smoke-test it.
- [x] Review changes, scan staged content for local credential values and finish merge commit.

Validation: 20 unit tests pass. Actual WebView2 loaded South Zone tiles and
621 map points, retained Leaflet instance/zoom/tab, rejected a superseded
map response and saved a temporary personal mark. Packaged EXE detected the
EXBO game, toggled passive/edit styles and exited cleanly with hotkey freed.
An official API smoke check returned 20 history entries and 195 active lots
for anomalous dust. Reviewer findings (queued activation, unavailable hotkey,
map response order) were fixed and re-reviewed. Old STALZONE.exe is preserved.
