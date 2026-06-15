# Dockle

A floating app launcher that sits on your desktop and stays out of the way until you need it. Hover the handle to pop it open, click a tile to launch.

Built with PySide6 as a single script - no installer, just run it.

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

## Description
Built with my wish for a more interesting app docking system (not the ugly windows looking ones). Watch my Youtube video for demostration.
(I also do minecraft contents)

## Controls
- **Hover handle** - show dock
- **Win+`** - toggle all docks on/off
- **Right-click tile** - options menu
- **Middle-click tile** - quick remove
- **Right-click handle** - edit mode / settings

## License
MIT
