# Dockle

A floating app launcher that sits on your desktop and stays out of the way until you need it. Hover the handle to pop it open, click a tile to launch.

Built with PySide6 as a single script — no installer, just run it.

![platform](https://img.shields.io/badge/platform-Windows-blue)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

## Setup

```bash
pip install pyside6
python dockle.pyw
```

Config saves automatically next to the script as `dockle_config.json`.

Optionally install `psutil` for CPU percentage in the System Info tile:

```bash
pip install psutil
```

## What it does

- Up to 8 dock groups, each with their own accent colour and animated connector line
- App tiles — drag-and-drop files/shortcuts, or use the + menu to add URLs
- Right-click tile — swap icon, pin to top, open file location, remove
- Middle-click tile — quick remove
- Drag to reorder tiles within a dock (enable Edit mode from the tray)
- Collapse individual docks with the − button
- Widget tiles: Clock, System Info (CPU/RAM), Volume, Now Playing, Note, Clipboard history, Stopwatch
- Now Playing shows the current track from Spotify or any browser tab, with media controls (⏮ ⏸ ⏭)
- Clipboard history shows the last 5 entries — click any to paste
- Dock only shows when you're on the desktop — hides automatically over fullscreen apps
- Disappear delay and connector style are configurable in settings

## Controls

- **Hover handle** — show dock
- **Win+`** — toggle all docks on/off
- **Right-click tile** — options menu
- **Middle-click tile** — quick remove
- **Right-click handle** — edit mode / settings

## License

MIT
