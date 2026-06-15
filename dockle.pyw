#!/usr/bin/env python3
"""
Dockle — floating desktop app launcher for Windows.
Run:  pip install pyside6 && python dockle.pyw
"""

import os, sys, json, subprocess, ctypes, ctypes.wintypes, time, random
from datetime import datetime

from PySide6.QtCore import (
    Qt, QTimer, QFileInfo, QSize, QPoint, QPointF, QRect,
    QPropertyAnimation, QEasingCurve, QAbstractNativeEventFilter,
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QFont, QFontMetrics, QCursor, QGuiApplication,
    QAction, QPen, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QToolButton, QFrame, QFileDialog, QMenu, QSystemTrayIcon, QDialog,
    QSpinBox, QLineEdit, QPushButton, QGraphicsDropShadowEffect, QCheckBox,
    QTextEdit,
)

try:
    from PySide6.QtGui import QFileIconProvider
except ImportError:
    from PySide6.QtWidgets import QFileIconProvider


CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dockle_config.json"
)

_HOTKEY_ID = 1
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000
_VK_BACKTICK = 0xC0

DEFAULTS = {
    "groups": [
        {
            "handle_pos": None,
            "accent": "#FF7A59",
            "docks": [
                {"name": "Dock 1", "apps": [], "pos": None},
                {"name": "Dock 2", "apps": [], "pos": None},
                {"name": "Dock 3", "apps": [], "pos": None},
            ],
        },
        {
            "handle_pos": None,
            "accent": "#285E9B",
            "docks": [
                {"name": "Dock 4", "apps": [], "pos": None},
                {"name": "Dock 5", "apps": [], "pos": None},
                {"name": "Dock 6", "apps": [], "pos": None},
            ],
        },
        {
            "handle_pos": None,
            "accent": "#E96363",
            "docks": [
                {"name": "Dock 7", "apps": [], "pos": None},
                {"name": "Dock 8", "apps": [], "pos": None},
            ],
        },
    ],
    "columns": 3,
    "icon_size": 56,
    "accent": "#FF7A59",
    "handle_locked": False,
    "connector_style": "straight",
    "connector_thickness": 2,
    "hide_delay": 1,
    "notes": {},
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # migrate old single-group format
        if "docks" in data and "groups" not in data:
            data["groups"] = [{
                "handle_pos": data.pop("handle_pos", None),
                "accent": data.pop("accent", DEFAULTS["accent"]),
                "docks": data.pop("docks"),
            }]
            data.pop("handle_locked", None)

        if "groups" in data:
            dg = DEFAULTS["groups"]
            # ensure we have all 3 groups
            while len(data["groups"]) < len(dg):
                n = len(data["groups"])
                data["groups"].append(dict(dg[n]))
            for gi, grp in enumerate(data["groups"]):
                grp.setdefault("docks", [])
                grp.setdefault("accent", DEFAULTS["accent"])
                min_docks = len(dg[gi]["docks"]) if gi < len(dg) else 2
                while len(grp["docks"]) < min_docks:
                    k = len(grp["docks"]) + 1
                    grp["docks"].append({"name": f"DOCK {k}", "apps": [], "pos": None})
                for dock in grp["docks"]:
                    dock.setdefault("apps", [])
                    dock.setdefault("pos", None)
                    dock.pop("columns", None)

        cfg.update(data)
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print("config save failed:", e)


def _open_file_location(path: str) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])


def launch(path: str) -> None:
    if path.startswith("__widget:"):
        return
    try:
        if path.startswith(("http://", "https://")):
            import webbrowser
            webbrowser.open(path)
            return
        _open = {
            "win32":  lambda: os.startfile(path),           # type: ignore[attr-defined]
            "darwin": lambda: subprocess.Popen(["open", path]),
        }.get(sys.platform, lambda: subprocess.Popen(["xdg-open", path]))
        _open()
    except Exception as exc:
        print("launch failed:", path, exc)


_lnk_cache: dict[str, str] = {}

def _resolve_lnk(path: str) -> str:
    """Resolve a .lnk shortcut to its target so the icon has no arrow overlay."""
    if sys.platform != "win32" or not path.lower().endswith(".lnk"):
        return path
    if path in _lnk_cache:
        return _lnk_cache[path]
    target = _parse_lnk_binary(path)
    _lnk_cache[path] = target
    return target

def _parse_lnk_binary(path: str) -> str:
    """Read the Windows Shell Link binary to extract the local target path."""
    import struct
    try:
        with open(path, "rb") as f:
            data = f.read(8192)
        if len(data) < 76:
            return path
        hdr_size = struct.unpack_from("<I", data, 0)[0]
        if hdr_size != 0x4C:
            return path
        link_flags = struct.unpack_from("<I", data, 20)[0]
        has_id_list  = bool(link_flags & 0x01)
        has_link_info = bool(link_flags & 0x02)
        offset = 76
        if has_id_list:
            idl_size = struct.unpack_from("<H", data, offset)[0]
            offset += 2 + idl_size
        if has_link_info and offset + 28 <= len(data):
            li_base = offset
            local_base_off = struct.unpack_from("<I", data, li_base + 16)[0]
            p_start = li_base + local_base_off
            p_end = data.index(b"\x00", p_start)
            local = data[p_start:p_end].decode("mbcs", errors="replace")
            if local and os.path.exists(local):
                return local
    except Exception:
        pass
    return path

def file_icon(path: str) -> QIcon:
    resolved = _resolve_lnk(path)
    icon = QFileIconProvider().icon(QFileInfo(resolved))
    if icon.isNull():
        return QApplication.style().standardIcon(
            QApplication.style().StandardPixmap.SP_FileIcon
        )
    return icon


def display_name(path: str) -> str:
    base = os.path.basename(path)
    return os.path.splitext(base)[0] or base


def make_glyph_icon(accent: str, size: int = 64) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(14, 17, 22, 235))
    p.setPen(Qt.NoPen)
    p.drawRect(4, 4, size - 8, size - 8)
    f = QFont("Segoe UI Symbol")
    f.setPixelSize(int(size * 0.46))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(accent))
    p.drawText(pm.rect(), Qt.AlignCenter, "⊞")
    p.end()
    return pm


_STARTUP_REG = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_KEY = "Dockle"

def _startup_cmd() -> str:
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return f'"{pythonw}" "{os.path.abspath(__file__)}"'

def _is_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG) as k:
            winreg.QueryValueEx(k, _STARTUP_KEY)
            return True
    except Exception:
        return False

def _set_startup(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, _STARTUP_KEY, 0, winreg.REG_SZ, _startup_cmd())
            else:
                try:
                    winreg.DeleteValue(k, _STARTUP_KEY)
                except FileNotFoundError:
                    pass
    except Exception as e:
        print("startup registry failed:", e)


def is_desktop_active() -> bool:
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd == 0:
            return True
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value in ("Progman", "WorkerW", "Shell_TrayWnd", "")
    except Exception:
        return True


def is_fullscreen_foreign() -> bool:
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return False
        cls = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in ('Progman', 'WorkerW', 'Shell_TrayWnd', 'DV2ControlHost'):
            return False
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        return rect.left <= 0 and rect.top <= 0 and rect.right >= sw and rect.bottom >= sh
    except Exception:
        return False


_DOCK_M = 24  # outer shadow margin; card is inset by this within the dock window

def _closest_edge(rect, target: QPoint):
    """Returns (edge_name, midpoint) for the rect edge nearest to target."""
    cx, cy = rect.center().x(), rect.center().y()
    tx, ty = target.x(), target.y()
    options = [
        ('top',    QPoint(cx, rect.top())),
        ('bottom', QPoint(cx, rect.bottom())),
        ('left',   QPoint(rect.left(), cy)),
        ('right',  QPoint(rect.right(), cy)),
    ]
    return min(options, key=lambda e: (e[1].x() - tx) ** 2 + (e[1].y() - ty) ** 2)

def _closest_edge_mid(rect, target: QPoint) -> QPoint:
    return _closest_edge(rect, target)[1]

def _card_rect(dock) -> QRect:
    """Screen-space rect of the visible card area (excluding shadow margin)."""
    return dock.geometry().adjusted(_DOCK_M, _DOCK_M, -_DOCK_M, -_DOCK_M)

def _resolve_overlaps(rects: list, margin: int = 10) -> list:
    """Push window rects apart so no two cards overlap. Returns list of QRect."""
    rects = [QRect(r) for r in rects]
    avail = QGuiApplication.primaryScreen().availableGeometry()
    for _ in range(40):
        moved = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ri, rj = rects[i], rects[j]
                need_x = (ri.width() + rj.width()) // 2 + margin
                need_y = (ri.height() + rj.height()) // 2 + margin
                dx = ri.center().x() - rj.center().x()
                dy = ri.center().y() - rj.center().y()
                ox, oy = need_x - abs(dx), need_y - abs(dy)
                if ox > 0 and oy > 0:
                    push = (min(ox, oy) + 1) // 2
                    if ox <= oy:
                        sign = 1 if dx >= 0 else -1
                        rects[i] = rects[i].translated(sign * push, 0)
                        rects[j] = rects[j].translated(-sign * push, 0)
                    else:
                        sign = 1 if dy >= 0 else -1
                        rects[i] = rects[i].translated(0, sign * push)
                        rects[j] = rects[j].translated(0, -sign * push)
                    moved = True
        if not moved:
            break
    for i, r in enumerate(rects):
        x = max(avail.left(), min(r.x(), avail.right() - r.width()))
        y = max(avail.top(), min(r.y(), avail.bottom() - r.height()))
        rects[i] = QRect(x, y, r.width(), r.height())
    return rects


class EditableLabel(QLabel):
    """QLabel that switches to an inline QLineEdit on double-click."""

    def __init__(self, text: str, on_rename, *args, **kwargs):
        super().__init__(text, *args, **kwargs)
        self._on_rename = on_rename

    def mouseDoubleClickEvent(self, _):
        ed = QLineEdit(self.text(), self.parent())
        ed.setGeometry(self.geometry())
        ed.setStyleSheet(
            "background: rgba(255,255,255,18); color: #EEF2F8;"
            "border: 1px solid rgba(255,122,89,200);"
            "font: bold 9px 'Segoe UI'; letter-spacing: 2px; padding: 0 2px;"
        )
        ed.selectAll()
        ed.show()
        ed.setFocus()
        self.hide()
        cb = self._on_rename

        def finish():
            text = ed.text().strip()
            if text:
                self.setText(text)
                cb(text)
            ed.hide()
            ed.deleteLater()
            self.show()

        ed.editingFinished.connect(finish)


class DarkDialog(QDialog):
    """Frameless dark dialog that matches the dock aesthetic."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._drag_offset = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("dlg_card")
        root.addWidget(self._card)

        card_body = QVBoxLayout(self._card)
        card_body.setContentsMargins(0, 0, 0, 0)
        card_body.setSpacing(0)

        strip = QWidget(self._card)
        strip.setObjectName("dlg_strip")
        strip.setFixedHeight(6)
        strip.mousePressEvent   = self._strip_press
        strip.mouseMoveEvent    = self._strip_move
        strip.mouseReleaseEvent = lambda _: setattr(self, "_drag_offset", None)
        card_body.addWidget(strip)

        self.content = QVBoxLayout()
        self.content.setContentsMargins(18, 14, 18, 18)
        self.content.setSpacing(10)
        card_body.addLayout(self.content)

        self._apply_style()

    def _apply_style(self):
        groups = self._cfg.get("groups", [])
        accent = groups[0].get("accent", DEFAULTS["accent"]) if groups else DEFAULTS["accent"]
        ac = QColor(accent)
        bc = QColor(accent); bc.setAlpha(60)
        border = f"rgba({bc.red()},{bc.green()},{bc.blue()},{bc.alpha()})"
        strip_c = f"rgba({ac.red()},{ac.green()},{ac.blue()},100)"
        self.setStyleSheet(f"""
            #dlg_card {{
                background: rgb(14,17,22);
                border: 1px solid {border};
            }}
            #dlg_strip {{ background: {strip_c}; }}
            QLabel         {{ color: #EEF2F8; font: 10px 'Segoe UI'; }}
            QLabel#dlg_hdr {{ color: #7C8696; font: bold 9px 'Segoe UI'; letter-spacing: 2px; }}
            QLineEdit, QSpinBox {{
                background: rgba(255,255,255,14); color: #EEF2F8;
                border: 1px solid rgba(255,255,255,22); border-radius: 0;
                padding: 5px 8px; font: 10px 'Segoe UI';
                selection-background-color: {accent};
            }}
            QLineEdit:focus, QSpinBox:focus {{ border-color: {accent}; }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 18px; background: rgba(255,255,255,10); border: none;
            }}
            QPushButton {{
                background: rgba(255,255,255,14); color: #EEF2F8;
                border: 1px solid rgba(255,255,255,22); border-radius: 0;
                padding: 5px 20px; font: 9px 'Segoe UI'; min-width: 64px;
            }}
            QPushButton:hover {{ background: rgba(255,255,255,28); }}
            QPushButton#dlg_ok {{
                background: {accent}; border-color: {accent}; color: #fff;
            }}
            QPushButton#dlg_ok:hover {{ background: rgba(255,122,89,200); }}
        """)

    def _strip_press(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _strip_move(self, e):
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def _add_header(self, text: str):
        lbl = QLabel(text.upper())
        lbl.setObjectName("dlg_hdr")
        self.content.addWidget(lbl)

    def _add_field(self, label: str, widget: QWidget):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(120)
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        self.content.addLayout(row)

    def _add_buttons(self, ok_text: str = "Save"):
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton(ok_text)
        ok.setObjectName("dlg_ok")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        self.content.addLayout(row)


class SettingsDialog(DarkDialog):
    """Global settings: layout, icon size, and per-handle accent colours."""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.setWindowTitle("Dockle — settings")

        self._add_header("Global settings")
        self.content.addSpacing(2)

        self.cols = QSpinBox()
        self.cols.setRange(1, 8)
        self.cols.setValue(int(cfg["columns"]))
        self._add_field("Default columns", self.cols)

        self.size = QSpinBox()
        self.size.setRange(32, 128)
        self.size.setValue(int(cfg["icon_size"]))
        self._add_field("Icon size (px)", self.size)

        self.content.addSpacing(6)
        self._add_header("Connector style")
        self.content.addSpacing(2)
        self._crooked_cb = QCheckBox("Crooked (L-shaped) lines")
        self._crooked_cb.setChecked(cfg.get("connector_style", "straight") == "crooked")
        self._crooked_cb.setStyleSheet("color: #EEF2F8; font: 10px 'Segoe UI';")
        self.content.addWidget(self._crooked_cb)

        self._thickness_spin = QSpinBox()
        self._thickness_spin.setRange(1, 5)
        self._thickness_spin.setValue(int(cfg.get("connector_thickness", 2)))
        self._add_field("Line thickness", self._thickness_spin)

        self.content.addSpacing(6)
        self._add_header("Behaviour")
        self.content.addSpacing(2)

        self._hide_delay_spin = QSpinBox()
        self._hide_delay_spin.setRange(1, 10)
        self._hide_delay_spin.setSuffix(" s")
        self._hide_delay_spin.setValue(int(cfg.get("hide_delay", 1)))
        self._add_field("Disappear delay", self._hide_delay_spin)

        self.content.addSpacing(6)
        self._add_header("Handles")
        self.content.addSpacing(2)

        self.handle_count = QSpinBox()
        self.handle_count.setRange(1, 8)
        self.handle_count.setValue(len(cfg.get("groups", [])))
        self._add_field("Number of handles", self.handle_count)

        self.content.addSpacing(4)
        self._add_header("Per-handle settings")
        self.content.addSpacing(2)

        groups = cfg.get("groups", [])
        self._accent_fields: list[QLineEdit] = []
        self._dock_count_fields: list[QSpinBox] = []
        for i, g in enumerate(groups):
            color = g.get("accent", DEFAULTS["accent"])
            field = QLineEdit(color)
            field.setPlaceholderText("#FF7A59")
            self._accent_fields.append(field)
            self._add_field(f"Handle {i+1} colour", field)
            sp = QSpinBox()
            sp.setRange(1, 6)
            sp.setValue(len(g.get("docks", [])) or 1)
            self._dock_count_fields.append(sp)
            self._add_field(f"Handle {i+1} docks", sp)

        self.content.addSpacing(4)
        self._add_buttons()

    def values(self) -> dict:
        accents = []
        for field in self._accent_fields:
            a = field.text().strip()
            if not a.startswith("#"):
                a = "#" + a
            if not QColor(a).isValid():
                a = DEFAULTS["accent"]
            accents.append(a)
        return {
            "columns":          self.cols.value(),
            "icon_size":        self.size.value(),
            "group_accents":    accents,
            "dock_counts":      [sp.value() for sp in self._dock_count_fields],
            "handle_count":     self.handle_count.value(),
            "connector_style":  "crooked" if self._crooked_cb.isChecked() else "straight",
            "connector_thickness": self._thickness_spin.value(),
            "hide_delay":       self._hide_delay_spin.value(),
        }


class URLDialog(DarkDialog):
    """Small dialog to add a web URL as a dock tile."""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.setWindowTitle("Add URL")
        self._add_header("Add URL")
        self.content.addSpacing(2)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://open.spotify.com")
        self._add_field("URL", self.url_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("display name (optional)")
        self._add_field("Name", self.name_edit)

        self.content.addSpacing(4)
        self._add_buttons("Add")

    def values(self) -> dict:
        url = self.url_edit.text().strip()
        if url and "://" not in url:
            url = "https://" + url
        name = self.name_edit.text().strip()
        if not name and url:
            try:
                from urllib.parse import urlparse
                host = urlparse(url).netloc
                name = host.replace("www.", "") or url
            except Exception:
                name = url
        return {"url": url, "name": name or url}


class DragBar(QWidget):
    """Coloured grip strip at the top of a dock — drag to reposition."""

    def __init__(self, dock: "GridDock"):
        super().__init__(dock.card)
        self.dock = dock
        self._offset = None

    def paintEvent(self, _):
        p = QPainter(self)
        c = QColor(self.dock.group.accent)
        c.setAlpha(100)
        p.fillRect(self.rect(), c)
        gx = self.width() // 2 - 6
        gy = self.height() // 2 - 1
        for dx in (0, 5, 10):
            p.fillRect(gx + dx, gy, 3, 3, QColor(255, 255, 255, 80))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._offset = e.globalPosition().toPoint() - self.dock.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._offset is not None:
            self.dock.move(e.globalPosition().toPoint() - self._offset)
            self.dock.group._update_connector()

    def mouseReleaseEvent(self, _):
        if self._offset is not None:
            pos = self.dock.frameGeometry().topLeft()
            docks = self.dock.group.group_cfg.get("docks", [])
            if self.dock.dock_index < len(docks):
                docks[self.dock.dock_index]["pos"] = [pos.x(), pos.y()]
            save_config(self.dock.group.controller.cfg)
            self._offset = None


class Handle(QWidget):
    """Activation zone — invisible normally, square indicator in edit mode."""

    def __init__(self, group: "DockGroup"):
        super().__init__(None)
        self.group = group
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(180, 180)
        self.setCursor(Qt.SizeAllCursor)
        self._drag_offset = None
        self._moved = False
        self._flash = 0.0
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(20)
        self._flash_timer.timeout.connect(self._fade_flash)

    def _fade_flash(self):
        self._flash = max(0.0, self._flash - 0.06)
        self.update()
        if self._flash <= 0:
            self._flash_timer.stop()

    def paintEvent(self, _):
        edit = self.group.controller.edit_mode
        if not edit and self._flash <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        accent = QColor(self.group.accent)
        r = self.rect().adjusted(10, 10, -10, -10)
        if edit:
            p.fillRect(r, QColor(14, 17, 22, 210))
            bc = QColor(accent); bc.setAlpha(220)
            p.setPen(QPen(bc, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            cx, cy = self.width() // 2, self.height() // 2
            p.setPen(QPen(QColor(accent), 1))
            p.drawLine(cx - 7, cy, cx + 7, cy)
            p.drawLine(cx, cy - 7, cx, cy + 7)
        else:
            alpha = int(self._flash * 200)
            p.fillRect(r, QColor(14, 17, 22, int(self._flash * 180)))
            bc = QColor(accent.red(), accent.green(), accent.blue(), alpha)
            p.setPen(QPen(bc, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        p.end()

    def enterEvent(self, _):
        self.group.connector.set_hovered(True)
        if not self.group.controller.edit_mode and is_desktop_active():
            self._flash = 1.0
            self._flash_timer.stop()
            self.update()
            self.group.show_grid()
            QTimer.singleShot(500, lambda: self._flash_timer.start())

    def leaveEvent(self, _):
        self.group.connector.set_hovered(False)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.group.controller.cfg["handle_locked"]:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            self._moved = True
            self.group._update_connector()

    def mouseReleaseEvent(self, _):
        if self._drag_offset is not None and self._moved:
            pos = self.frameGeometry().topLeft()
            self.group.group_cfg["handle_pos"] = [pos.x(), pos.y()]
            save_config(self.group.controller.cfg)
        self._drag_offset = None

    def contextMenuEvent(self, e):
        self.group.controller.tray_menu().exec(e.globalPos())


class LineConnector(QWidget):
    """Transparent overlay — lines from handle to docks, square endpoints."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._handle_local = QPoint()
        self._dock_local: list[QPoint] = []
        self._accent = "#FF7A59"
        self._style = "straight"
        self._thickness = 2
        self._progress = 1.0
        self._grow_timer = QTimer(self)
        self._grow_timer.setInterval(16)
        self._grow_timer.timeout.connect(self._grow_step)
        self._shrink_timer = QTimer(self)
        self._shrink_timer.setInterval(16)
        self._shrink_timer.timeout.connect(self._shrink_step)
        self._hovered = False

    def _grow_step(self):
        self._progress = min(1.0, self._progress + 0.04)
        self.update()
        if self._progress >= 1.0:
            self._grow_timer.stop()

    def _shrink_step(self):
        self._progress = max(0.0, self._progress - 0.06)
        self.update()
        if self._progress <= 0.0:
            self._shrink_timer.stop()
            self.hide()

    def start_grow(self):
        self._shrink_timer.stop()
        self._progress = 0.0
        self._grow_timer.start()

    def start_shrink(self):
        if not self.isVisible():
            return
        self._grow_timer.stop()
        self._shrink_timer.start()

    def set_style(self, style: str):
        self._style = style

    def set_thickness(self, n: int):
        self._thickness = max(1, min(5, int(n)))

    def set_hovered(self, h: bool):
        if h != self._hovered:
            self._hovered = h
            self.update()

    def set_connections(self, handle_center: QPoint, dock_pts: list[QPoint], accent: str):
        self._accent = accent
        if not dock_pts:
            self.hide(); return
        all_pts = dock_pts + [handle_center]
        all_x = [p.x() for p in all_pts]
        all_y = [p.y() for p in all_pts]
        m = 20
        ox, oy = min(all_x) - m, min(all_y) - m
        w = max(max(all_x) - min(all_x) + m * 2, 1)
        h = max(max(all_y) - min(all_y) + m * 2, 1)
        self.setGeometry(ox, oy, w, h)
        self._handle_local = QPoint(handle_center.x() - ox, handle_center.y() - oy)
        self._dock_local = [QPoint(p.x() - ox, p.y() - oy) for p in dock_pts]
        self.update()

    def _draw_lines(self, p: QPainter, pen: QPen, prog: float):
        """Draw all connector segments with the given pen. Returns list of tip points."""
        p.setPen(pen)
        hl = self._handle_local
        tips = []
        for dp in self._dock_local:
            if self._style == "crooked":
                dx = dp.x() - hl.x(); dy = dp.y() - hl.y()
                adx, ady = abs(dx), abs(dy)
                sx = 1 if dx >= 0 else -1
                sy = 1 if dy >= 0 else -1
                if adx >= ady:
                    bend = QPoint(hl.x() + sx * ady, dp.y())
                else:
                    bend = QPoint(dp.x(), hl.y() + sy * adx)
                bx = bend.x() - hl.x(); by = bend.y() - hl.y()
                ex = dp.x() - bend.x(); ey = dp.y() - bend.y()
                d1 = (bx ** 2 + by ** 2) ** 0.5
                d2 = (ex ** 2 + ey ** 2) ** 0.5
                total = d1 + d2 or 1.0
                f1 = d1 / total
                if prog <= f1:
                    t = prog / f1 if f1 else 1.0
                    tip = QPoint(int(hl.x() + bx * t), int(hl.y() + by * t))
                    p.drawLine(hl, tip)
                else:
                    p.drawLine(hl, bend)
                    t2 = (prog - f1) / (1.0 - f1) if (1.0 - f1) else 1.0
                    tip = QPoint(int(bend.x() + ex * t2), int(bend.y() + ey * t2))
                    p.drawLine(bend, tip)
            else:
                tip = QPoint(
                    int(hl.x() + (dp.x() - hl.x()) * prog),
                    int(hl.y() + (dp.y() - hl.y()) * prog),
                )
                p.drawLine(hl, tip)
            tips.append(tip)
        return tips

    def paintEvent(self, _):
        if not self._dock_local:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        accent = QColor(self._accent)
        hl = self._handle_local
        prog = self._progress

        # glow pass when handle is hovered
        if self._hovered and prog > 0:
            gc = QColor(accent); gc.setAlpha(int(50 * prog))
            glow_pen = QPen(gc, self._thickness + 6)
            glow_pen.setCapStyle(Qt.RoundCap)
            self._draw_lines(p, glow_pen, prog)

        # normal lines
        c = QColor(accent); c.setAlpha(140)
        pen = QPen(c, self._thickness)
        tips = self._draw_lines(p, pen, prog)

        # endpoint dots
        if prog > 0.85:
            dot_alpha = int(140 * min(1.0, (prog - 0.85) / 0.15))
            dc = QColor(accent); dc.setAlpha(dot_alpha)
            for tip in tips:
                p.setBrush(dc); p.setPen(Qt.NoPen)
                p.drawRect(tip.x() - 3, tip.y() - 3, 6, 6)

        # origin box — filled inner square
        oc = QColor(accent); oc.setAlpha(int(160 * min(1.0, prog * 6)))
        p.setPen(Qt.NoPen); p.setBrush(oc)
        p.drawRect(hl.x() - 5, hl.y() - 5, 10, 10)
        # outer border ring
        oc2 = QColor(accent); oc2.setAlpha(int(80 * min(1.0, prog * 6)))
        p.setPen(QPen(oc2, 1)); p.setBrush(Qt.NoBrush)
        p.drawRect(hl.x() - 10, hl.y() - 10, 20, 20)
        p.end()


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def nativeEventFilter(self, event_type, message):
        class MSG(ctypes.Structure):
            _fields_ = [
                ('hwnd',    ctypes.c_size_t),
                ('message', ctypes.c_uint),
                ('wParam',  ctypes.c_size_t),
                ('lParam',  ctypes.c_size_t),
                ('time',    ctypes.c_ulong),
                ('pt_x',    ctypes.c_long),
                ('pt_y',    ctypes.c_long),
            ]
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
            if msg.message == 0x0312:  # WM_HOTKEY
                self._cb()
        except Exception:
            pass
        return False, 0


_WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

def _scan_now_playing():
    # --- Spotify: query by window class so both old and new title formats work ---
    spotify_hwnd = ctypes.windll.user32.FindWindowW("SpotifyMainWindow", None)
    if spotify_hwnd and ctypes.windll.user32.IsWindowVisible(spotify_hwnd):
        length = ctypes.windll.user32.GetWindowTextLengthW(spotify_hwnd)
        if length > 2:
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(spotify_hwnd, buf, length + 1)
            title = buf.value.strip()
            # idle/paused titles to ignore
            if title and title not in ("Spotify", "Spotify Premium", "Spotify Free"):
                if title.endswith(" - Spotify"):
                    title = title[:-10]
                parts = title.rsplit(" - ", 1)
                return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else "Spotify")

    # --- Browser-based media: scan all windows ---
    found = []

    def _cb(hwnd, _):
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length < 3:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        # YouTube Music — pipe separator (Firefox/Zen) or dash separator (Chrome/Edge)
        if "YouTube Music" in title:
            if " | YouTube Music" in title:
                track = title.split(" | YouTube Music")[0].strip()
                found.append((track, "YouTube Music"))
            elif " - YouTube Music" in title:
                track = title.split(" - YouTube Music")[0].strip()
                parts = track.rsplit(" - ", 1)
                found.append((parts[0].strip(), parts[1].strip() if len(parts) > 1 else "YouTube Music"))
        # Regular YouTube — pipe or dash separator
        elif " | YouTube" in title:
            track = title.split(" | YouTube")[0].strip()
            if len(track) > 2:
                found.append((track, "YouTube"))
        elif " - YouTube" in title:
            track = title.split(" - YouTube")[0].strip()
            if len(track) > 2:
                found.append((track, "YouTube"))
        return True

    proc = _WNDENUMPROC(_cb)  # hold ref so GC doesn't collect mid-scan
    try:
        ctypes.windll.user32.EnumWindows(proc, 0)
    except Exception:
        pass
    return found[0] if found else ("", "")


_PSUTIL_OK = False
try:
    import psutil as _psutil
    _PSUTIL_OK = True
except ImportError:
    pass


class ClockTile(QWidget):
    """Live clock widget tile that fits in a dock grid cell."""

    def __init__(self, accent: str, size: int, on_remove, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._sz = size
        self._on_remove = on_remove
        tile = size + 12
        self.setFixedSize(tile, tile)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(1000)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor(14, 17, 22, 220))
        ac = self._accent
        border = QColor(ac.red(), ac.green(), ac.blue(), 80)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        sec_str  = now.strftime(":%S")
        date_str = now.strftime("%a %d")
        # time
        tf = QFont("Consolas", max(9, self._sz // 6) + 1)
        tf.setBold(True)
        p.setFont(tf)
        p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 220))
        tm = p.fontMetrics()
        ty = r.height() // 2 - tm.height() // 2 + tm.ascent() - 6
        tw = tm.horizontalAdvance(time_str)
        p.drawText(r.center().x() - (tw + p.fontMetrics().horizontalAdvance(sec_str)) // 2, ty, time_str)
        # seconds
        sf = QFont("Consolas", max(7, self._sz // 8))
        p.setFont(sf)
        p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 120))
        sw = p.fontMetrics().horizontalAdvance(sec_str)
        p.drawText(r.center().x() - (tw + sw) // 2 + tw, ty, sec_str)
        # date
        df = QFont("Segoe UI", max(6, self._sz // 10))
        p.setFont(df)
        p.setPen(QColor(200, 205, 215, 90))
        dm = p.fontMetrics()
        dy = ty + tm.height() - 2
        p.drawText(r.center().x() - dm.horizontalAdvance(date_str) // 2, dy, date_str)
        p.end()

    def _ctx(self, pos):
        m = QMenu(self)
        m.setStyleSheet("""
            QMenu { background: rgb(14,17,22); border: 1px solid rgba(255,255,255,28);
                    color: #EEF2F8; font: 10px 'Segoe UI'; padding: 2px; }
            QMenu::item { padding: 5px 18px; }
            QMenu::item:selected { background: rgba(255,255,255,18); }
        """)
        a = QAction("Remove", m)
        a.triggered.connect(lambda _: self._on_remove())
        m.addAction(a)
        m.exec(self.mapToGlobal(pos))


class SysInfoTile(QWidget):
    """Live CPU / RAM tile that fits in a dock grid cell."""

    def __init__(self, accent: str, size: int, on_remove, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._sz = size
        self._on_remove = on_remove
        tile = size + 12
        self.setFixedSize(tile, tile)
        self._cpu = 0.0
        self._ram = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(2000)
        self._tick()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

    def _tick(self):
        if _PSUTIL_OK:
            self._cpu = _psutil.cpu_percent(interval=None)
            self._ram = _psutil.virtual_memory().percent
        else:
            try:
                class _MS(ctypes.Structure):
                    _fields_ = [("dwLength", ctypes.c_ulong),
                                 ("dwMemoryLoad", ctypes.c_ulong),
                                 ("ullTotalPhys", ctypes.c_ulonglong),
                                 ("ullAvailPhys", ctypes.c_ulonglong),
                                 ("ullTotalPageFile", ctypes.c_ulonglong),
                                 ("ullAvailPageFile", ctypes.c_ulonglong),
                                 ("ullTotalVirtual", ctypes.c_ulonglong),
                                 ("ullAvailVirtual", ctypes.c_ulonglong),
                                 ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
                ms = _MS()
                ms.dwLength = ctypes.sizeof(ms)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
                self._ram = float(ms.dwMemoryLoad)
            except Exception:
                self._ram = 0.0
            self._cpu = 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor(14, 17, 22, 220))
        ac = self._accent
        border = QColor(ac.red(), ac.green(), ac.blue(), 80)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))

        pad = 6
        bx = r.x() + pad
        bw = r.width() - pad * 2
        lf = QFont("Segoe UI", max(6, self._sz // 10))
        p.setFont(lf)
        lm = p.fontMetrics()
        lh = lm.height()
        bar_h = 4
        gap = 3

        def draw_row(label_str: str, pct: float, y: int):
            p.setPen(QColor(200, 205, 215, 130))
            p.drawText(bx, y + lm.ascent(), label_str)
            by = y + lh + gap
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(40, 45, 55))
            p.drawRect(bx, by, bw, bar_h)
            fill = int(bw * max(0.0, min(1.0, pct / 100.0)))
            if fill > 0:
                p.setBrush(QColor(ac.red(), ac.green(), ac.blue(), 200))
                p.drawRect(bx, by, fill, bar_h)
            pct_str = f"{pct:.0f}%"
            p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 180))
            p.drawText(r.right() - pad - lm.horizontalAdvance(pct_str),
                       y + lm.ascent(), pct_str)
            return by + bar_h + gap * 2

        row_h = lh + bar_h + gap * 3
        total_h = row_h * 2
        start_y = r.center().y() - total_h // 2

        y = draw_row("CPU", self._cpu, start_y)
        draw_row("RAM", self._ram, y)
        p.end()

    def _ctx(self, pos):
        m = QMenu(self)
        m.setStyleSheet("""
            QMenu { background: rgb(14,17,22); border: 1px solid rgba(255,255,255,28);
                    color: #EEF2F8; font: 10px 'Segoe UI'; padding: 2px; }
            QMenu::item { padding: 5px 18px; }
            QMenu::item:selected { background: rgba(255,255,255,18); }
        """)
        a = QAction("Remove", m)
        a.triggered.connect(lambda _: self._on_remove())
        m.addAction(a)
        m.exec(self.mapToGlobal(pos))


class VolumeTile(QWidget):
    """WASAPI master-volume tile — scroll wheel to adjust, painted bar."""

    _MENU_SS = """
        QMenu { background: rgb(14,17,22); border: 1px solid rgba(255,255,255,28);
                color: #EEF2F8; font: 10px 'Segoe UI'; padding: 2px; }
        QMenu::item { padding: 5px 18px; }
        QMenu::item:selected { background: rgba(255,255,255,18); }
    """

    def __init__(self, accent: str, size: int, on_remove, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._sz = size
        self._on_remove = on_remove
        tile = size + 12
        self.setFixedSize(tile, tile)
        self._vol = 0.5
        self._vol_ptr = None
        self._init_com()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)
        self._refresh()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

    # minimal COM vtable calls — no pycaw needed
    def _init_com(self):
        try:
            def _guid(s):
                import uuid
                b = uuid.UUID(s).bytes_le
                class GUID(ctypes.Structure):
                    _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                                 ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]
                g = GUID()
                ctypes.memmove(ctypes.byref(g), b, 16)
                return g

            CLSCTX_ALL = 23
            DEVICE_DEFAULT = 0
            ECONSOLE = 0

            ctypes.windll.ole32.CoInitializeEx(None, 0)

            IMMDevEnum_CLSID = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
            IMMDevEnum_IID   = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
            IAudioEP_IID     = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")

            enumerator = ctypes.c_void_p()
            hr = ctypes.windll.ole32.CoCreateInstance(
                ctypes.byref(IMMDevEnum_CLSID), None, CLSCTX_ALL,
                ctypes.byref(IMMDevEnum_IID), ctypes.byref(enumerator))
            if hr != 0 or not enumerator.value:
                return

            # GetDefaultAudioEndpoint vtable index 4
            vtbl = ctypes.cast(enumerator, ctypes.POINTER(ctypes.c_void_p)).contents.value
            fn_get = ctypes.cast(
                ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[4],
                ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int,
                                   ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)))
            device = ctypes.c_void_p()
            hr = fn_get(enumerator.value, DEVICE_DEFAULT, ECONSOLE, ctypes.byref(device))
            if hr != 0 or not device.value:
                return

            # IMMDevice::Activate vtable index 3
            vtbl2 = ctypes.cast(device, ctypes.POINTER(ctypes.c_void_p)).contents.value
            fn_act = ctypes.cast(
                ctypes.cast(vtbl2, ctypes.POINTER(ctypes.c_void_p))[3],
                ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                   ctypes.POINTER(type(IAudioEP_IID)),
                                   ctypes.c_uint, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p)))
            ep = ctypes.c_void_p()
            hr = fn_act(device.value, ctypes.byref(IAudioEP_IID),
                        CLSCTX_ALL, None, ctypes.byref(ep))
            if hr != 0 or not ep.value:
                return
            self._vol_ptr = ep.value
        except Exception:
            self._vol_ptr = None

    def get_volume(self) -> float:
        if self._vol_ptr is None:
            return 0.5
        try:
            vtbl = ctypes.cast(self._vol_ptr, ctypes.POINTER(ctypes.c_void_p)).contents.value
            fn = ctypes.cast(
                ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[9],
                ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_float)))
            v = ctypes.c_float()
            fn(self._vol_ptr, ctypes.byref(v))
            return max(0.0, min(1.0, float(v.value)))
        except Exception:
            return 0.5

    def set_volume(self, v: float):
        if self._vol_ptr is None:
            return
        try:
            v = max(0.0, min(1.0, v))
            vtbl = ctypes.cast(self._vol_ptr, ctypes.POINTER(ctypes.c_void_p)).contents.value
            fn = ctypes.cast(
                ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[7],
                ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                   ctypes.c_float, ctypes.c_void_p))
            fn(self._vol_ptr, ctypes.c_float(v), None)
        except Exception:
            pass

    def _refresh(self):
        self._vol = self.get_volume()
        self.update()

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        self.set_volume(self._vol + (0.05 if delta > 0 else -0.05))
        self._refresh()

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(14, 17, 22, 220))
        ac = self._accent
        border = QColor(ac.red(), ac.green(), ac.blue(), 80)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))

        pad = 8
        bar_w = max(4, (r.width() - pad * 2) // 3)
        bar_x = r.center().x() - bar_w // 2
        bar_bot = r.bottom() - pad - 14
        bar_top = r.top() + pad + 14
        bar_h = bar_bot - bar_top
        fill_h = int(bar_h * self._vol)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(40, 45, 55))
        p.drawRect(bar_x, bar_top, bar_w, bar_h)
        if fill_h > 0:
            p.setBrush(QColor(ac.red(), ac.green(), ac.blue(), 200))
            p.drawRect(bar_x, bar_bot - fill_h, bar_w, fill_h)

        lf = QFont("Segoe UI", max(6, self._sz // 10))
        lf.setBold(True)
        p.setFont(lf)
        p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 200))
        lbl = "VOL"
        lm = p.fontMetrics()
        p.drawText(r.center().x() - lm.horizontalAdvance(lbl) // 2, r.top() + pad + lm.ascent(), lbl)
        pct = f"{int(self._vol * 100)}%"
        p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 160))
        p.drawText(r.center().x() - lm.horizontalAdvance(pct) // 2, r.bottom() - pad, pct)
        p.end()

    def _ctx(self, pos):
        m = QMenu(self)
        m.setStyleSheet(self._MENU_SS)
        a = QAction("Remove", m)
        a.triggered.connect(lambda _: self._on_remove())
        m.addAction(a)
        m.exec(self.mapToGlobal(pos))


class NowPlayingTile(QWidget):
    """Scrolling now-playing tile — 2 columns wide."""

    _MENU_SS = """
        QMenu { background: rgb(14,17,22); border: 1px solid rgba(255,255,255,28);
                color: #EEF2F8; font: 10px 'Segoe UI'; padding: 2px; }
        QMenu::item { padding: 5px 18px; }
        QMenu::item:selected { background: rgba(255,255,255,18); }
    """

    _VK_PREV  = 0xB1
    _VK_PAUSE = 0xB3
    _VK_NEXT  = 0xB0

    def __init__(self, accent: str, size: int, on_remove, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._sz = size
        self._on_remove = on_remove
        tile = size + 12
        self.setFixedSize(tile * 2, tile)
        self._title = ""
        self._artist = ""
        self._scroll_offset = 0
        self._scroll_dir = 1
        self._paused = False
        self._hover_btn = -1          # -1 none, 0 prev, 1 pause, 2 next
        self._btn_zone = 54           # px reserved on right for the 3 buttons

        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._scan)
        self._scan_timer.start(3000)
        self._smtc_thread = None
        self._scan()

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._anim_step)
        self._anim_timer.start(50)

        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

    def _set_track(self, title: str, artist: str):
        if title != self._title or artist != self._artist:
            self._title = title
            self._artist = artist
            self._scroll_offset = 0
            self._scroll_dir = 1
            self.update()

    def _scan(self):
        # Fast path: window title scan (instant, works for Spotify + active browser tab)
        title, artist = _scan_now_playing()
        if title:
            self._set_track(title, artist)
            return
        # Slow path: Windows SMTC via PowerShell — detects any browser tab playing audio
        if self._smtc_thread is None or not self._smtc_thread.is_alive():
            import threading
            self._smtc_thread = threading.Thread(target=self._smtc_scan, daemon=True)
            self._smtc_thread.start()

    def _smtc_scan(self):
        """Query Windows SMTC — iterates ALL sessions so background tabs are found."""
        # Iterate every registered media session, return first with a non-empty title.
        _ps = (
            '$m=[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,'
            'Windows.Media.Control,ContentType=WindowsRuntime]'
            '::RequestAsync().GetAwaiter().GetResult();'
            'foreach($s in $m.GetSessions()){'
            'try{'
            '$p=$s.TryGetMediaPropertiesAsync().GetAwaiter().GetResult();'
            'if($p -and $p.Title -ne ""){'
            'Write-Output "$($p.Title)|$($p.Artist)";break'
            '}}catch{}}'
        )
        try:
            r = subprocess.run(
                ['powershell', '-NoP', '-NonI', '-WindowStyle', 'Hidden', '-Command', _ps],
                capture_output=True, text=True, timeout=8,
                creationflags=0x08000000,
            )
            out = r.stdout.strip()
            if out and '|' in out:
                title, _, artist = out.partition('|')
                title, artist = title.strip(), artist.strip()
                QTimer.singleShot(0, lambda t=title, a=artist: self._set_track(t, a))
            else:
                QTimer.singleShot(0, lambda: self._set_track("", ""))
        except Exception:
            pass

    def _anim_step(self):
        if not self._title:
            return
        tf = QFont("Segoe UI", max(8, self._sz // 8))
        tf.setBold(True)
        fm = QFontMetrics(tf)
        text_w = fm.horizontalAdvance(self._title)
        avail = self.width() - 20 - self._btn_zone
        if text_w <= avail:
            self._scroll_offset = 0
            return
        max_scroll = text_w - avail
        self._scroll_offset += self._scroll_dir * 1
        if self._scroll_offset >= max_scroll:
            self._scroll_offset = max_scroll
            self._scroll_dir = -1
        elif self._scroll_offset <= 0:
            self._scroll_offset = 0
            self._scroll_dir = 1
        self.update()

    def _hit_button(self, pos):
        bz = self._btn_zone
        if pos.x() < self.width() - bz:
            return -1
        zone_w = bz // 3
        idx = (pos.x() - (self.width() - bz)) // zone_w
        return min(idx, 2)

    def _draw_btn_icon(self, p, cx, cy, kind, hover):
        ac = self._accent
        c = QColor(ac.red(), ac.green(), ac.blue(), 230 if hover else 110)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        bar_h = 9
        if kind == 0:  # prev  ◀|
            p.drawRect(cx - 7, cy - bar_h // 2, 3, bar_h)
            pts = QPolygonF([QPointF(cx - 3, cy), QPointF(cx + 4, cy - 5), QPointF(cx + 4, cy + 5)])
            p.drawPolygon(pts)
        elif kind == 1:  # pause ⏸ / play ▶
            if self._paused:
                pts = QPolygonF([QPointF(cx - 4, cy - 5), QPointF(cx - 4, cy + 5), QPointF(cx + 5, cy)])
                p.drawPolygon(pts)
            else:
                p.drawRect(cx - 5, cy - bar_h // 2, 3, bar_h)
                p.drawRect(cx + 2, cy - bar_h // 2, 3, bar_h)
        else:  # next  |▶
            pts = QPolygonF([QPointF(cx - 4, cy - 5), QPointF(cx - 4, cy + 5), QPointF(cx + 3, cy)])
            p.drawPolygon(pts)
            p.drawRect(cx + 4, cy - bar_h // 2, 3, bar_h)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            btn = self._hit_button(e.pos())
            if btn == 0:
                ctypes.windll.user32.keybd_event(self._VK_PREV, 0, 0, 0)
                ctypes.windll.user32.keybd_event(self._VK_PREV, 0, 2, 0)
            elif btn == 1:
                ctypes.windll.user32.keybd_event(self._VK_PAUSE, 0, 0, 0)
                ctypes.windll.user32.keybd_event(self._VK_PAUSE, 0, 2, 0)
                self._paused = not self._paused
                self.update()
            elif btn == 2:
                ctypes.windll.user32.keybd_event(self._VK_NEXT, 0, 0, 0)
                ctypes.windll.user32.keybd_event(self._VK_NEXT, 0, 2, 0)

    def mouseMoveEvent(self, e):
        new_hover = self._hit_button(e.pos())
        if new_hover != self._hover_btn:
            self._hover_btn = new_hover
            self.setCursor(Qt.PointingHandCursor if new_hover >= 0 else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        if self._hover_btn != -1:
            self._hover_btn = -1
            self.setCursor(Qt.ArrowCursor)
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(14, 17, 22, 220))
        ac = self._accent
        border = QColor(ac.red(), ac.green(), ac.blue(), 80)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))

        bz = self._btn_zone
        btn_x = r.width() - bz
        zone_w = bz // 3
        cy = r.height() // 2
        pad = 8

        # button zone hover bg
        if self._hover_btn >= 0:
            hbg = QColor(ac.red(), ac.green(), ac.blue(), 28)
            p.fillRect(btn_x + zone_w * self._hover_btn, 1, zone_w, r.height() - 2, hbg)

        # separator
        p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), 35), 1))
        p.drawLine(btn_x, 5, btn_x, r.height() - 5)

        # draw the 3 icons
        for i in range(3):
            cx = btn_x + zone_w * i + zone_w // 2
            self._draw_btn_icon(p, cx, cy, i, self._hover_btn == i)

        if not self._title:
            f = QFont("Segoe UI", max(7, self._sz // 10))
            p.setFont(f)
            p.setPen(QColor(100, 110, 130, 130))
            text_r = QRect(0, 0, btn_x, r.height())
            p.drawText(text_r, Qt.AlignCenter, "Now Playing")
            p.end()
            return

        # title (scrolling, clipped to text zone)
        tf = QFont("Segoe UI", max(8, self._sz // 8))
        tf.setBold(True)
        p.setFont(tf)
        p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 220))
        tm = p.fontMetrics()
        ty = r.center().y() - tm.height() // 2 + tm.ascent() - 8
        clip_rect = QRect(pad, ty - tm.ascent(), btn_x - pad * 2, tm.height() + 4)
        p.setClipRect(clip_rect)
        p.drawText(pad - self._scroll_offset, ty, self._title)
        p.setClipping(False)

        # artist
        af = QFont("Segoe UI", max(6, self._sz // 11))
        p.setFont(af)
        p.setPen(QColor(160, 170, 185, 140))
        tm2 = p.fontMetrics()
        ay = ty + tm.height() - 2
        artist_text = tm2.elidedText(self._artist or "", Qt.ElideRight, btn_x - pad * 2)
        p.drawText(pad, ay, artist_text)
        p.end()

    def _ctx(self, pos):
        m = QMenu(self)
        m.setStyleSheet(self._MENU_SS)
        a = QAction("Remove", m)
        a.triggered.connect(lambda _: self._on_remove())
        m.addAction(a)
        m.exec(self.mapToGlobal(pos))


class NotePopup(QWidget):
    """Frameless floating note editor."""

    def __init__(self, accent: str, cfg: dict, note_key: str, on_close=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._accent = QColor(accent)
        self._cfg = cfg
        self._note_key = note_key
        self._on_close = on_close

        self.setFixedSize(300, 220)

        ac = self._accent
        border_c = f"rgba({ac.red()},{ac.green()},{ac.blue()},100)"
        self.setStyleSheet(f"""
            QWidget#note_card {{
                background: rgb(14,17,22);
                border: 1px solid {border_c};
            }}
            QTextEdit {{
                background: transparent; color: rgba({ac.red()},{ac.green()},{ac.blue()},220);
                border: none; font: 10px 'Segoe UI';
                selection-background-color: rgba({ac.red()},{ac.green()},{ac.blue()},80);
            }}
            QPushButton#note_close {{
                background: transparent; color: #7C8696;
                border: none; font: bold 12px 'Segoe UI'; padding: 0;
            }}
            QPushButton#note_close:hover {{ color: #EEF2F8; }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget(self)
        card.setObjectName("note_card")
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        hdr = QLabel("NOTE")
        hdr.setStyleSheet(f"color: rgba({ac.red()},{ac.green()},{ac.blue()},160); font: bold 8px 'Segoe UI'; letter-spacing: 2px; border: none;")
        top_row.addWidget(hdr)
        top_row.addStretch()
        close_btn = QPushButton("×")
        close_btn.setObjectName("note_close")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self.close)
        top_row.addWidget(close_btn)
        layout.addLayout(top_row)

        self._edit = QTextEdit()
        cfg.setdefault("notes", {})
        self._edit.setPlainText(cfg["notes"].get(note_key, ""))
        layout.addWidget(self._edit)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save)
        self._edit.textChanged.connect(lambda: self._save_timer.start())

    def _save(self):
        self._cfg.setdefault("notes", {})
        self._cfg["notes"][self._note_key] = self._edit.toPlainText()
        save_config(self._cfg)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        self._save()
        if self._on_close:
            self._on_close()
        super().closeEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)


class QuickNoteTile(QWidget):
    """Sticky note tile."""

    _MENU_SS = """
        QMenu { background: rgb(14,17,22); border: 1px solid rgba(255,255,255,28);
                color: #EEF2F8; font: 10px 'Segoe UI'; padding: 2px; }
        QMenu::item { padding: 5px 18px; }
        QMenu::item:selected { background: rgba(255,255,255,18); }
    """

    def __init__(self, accent: str, size: int, note_key: str, on_remove, cfg: dict, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._sz = size
        self._note_key = note_key
        self._on_remove = on_remove
        self._cfg = cfg
        self._popup = None
        cfg.setdefault("notes", {})
        tile = size + 12
        self.setFixedSize(tile, tile)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._toggle_popup()

    def _toggle_popup(self):
        if self._popup and self._popup.isVisible():
            self._popup.close()
            self._popup = None
            return
        self._popup = NotePopup(
            f"#{self._accent.red():02x}{self._accent.green():02x}{self._accent.blue():02x}",
            self._cfg, self._note_key,
            on_close=lambda: setattr(self, '_popup', None)
        )
        gp = self.mapToGlobal(QPoint(self.width() + 4, 0))
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = gp.x()
        y = gp.y()
        if x + 300 > screen.right():
            x = self.mapToGlobal(QPoint(-304, 0)).x()
        if y + 220 > screen.bottom():
            y = screen.bottom() - 224
        self._popup.move(x, y)
        self._popup.show()
        self._popup.raise_()
        self._popup._edit.setFocus()

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(14, 17, 22, 220))
        ac = self._accent
        border = QColor(ac.red(), ac.green(), ac.blue(), 80)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))

        # pencil icon lines
        px, py = r.right() - 14, r.top() + 8
        pen_c = QColor(ac.red(), ac.green(), ac.blue(), 120)
        p.setPen(QPen(pen_c, 1))
        p.drawLine(px, py + 8, px + 6, py)
        p.drawLine(px + 6, py, px + 8, py + 2)
        p.drawLine(px + 8, py + 2, px + 2, py + 10)
        p.drawLine(px + 2, py + 10, px, py + 8)
        p.drawLine(px, py + 8, px + 1, py + 11)
        p.drawLine(px + 1, py + 11, px + 2, py + 10)

        # note text preview
        text = self._cfg["notes"].get(self._note_key, "")
        if text:
            tf = QFont("Segoe UI", max(6, self._sz // 11))
            p.setFont(tf)
            p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 180))
            clip = r.adjusted(6, 6, -6, -6)
            p.setClipRect(clip)
            tm = p.fontMetrics()
            lines = text.splitlines()
            y_off = clip.top() + tm.ascent()
            for line in lines[:4]:
                if y_off > clip.bottom():
                    break
                p.drawText(clip.left(), y_off, line)
                y_off += tm.height() + 1
            p.setClipping(False)
        else:
            lf = QFont("Segoe UI", max(6, self._sz // 10))
            p.setFont(lf)
            p.setPen(QColor(100, 110, 130, 100))
            p.drawText(r, Qt.AlignCenter, "note")
        p.end()

    def _ctx(self, pos):
        m = QMenu(self)
        m.setStyleSheet(self._MENU_SS)
        a = QAction("Remove", m)
        a.triggered.connect(lambda _: self._on_remove())
        m.addAction(a)
        m.exec(self.mapToGlobal(pos))


class DraggableTile(QToolButton):
    """QToolButton that supports drag-to-reorder within a dock."""

    def __init__(self, dock: "GridDock", dock_index: int, app_index: int, parent=None):
        super().__init__(parent)
        self._dock = dock
        self._dock_index = dock_index
        self._app_index = app_index
        self._drag_start = None
        self._ghost = None
        self._is_pinned = False

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start = e.globalPosition().toPoint()
        elif e.button() == Qt.MiddleButton and getattr(self, '_on_remove', None):
            self._on_remove()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_start is None:
            return
        delta = e.globalPosition().toPoint() - self._drag_start
        if delta.manhattanLength() > 8:
            if self._ghost is None:
                self._start_ghost()
        if self._ghost:
            self._ghost.move(e.globalPosition().toPoint() - QPoint(self._ghost.width() // 2,
                                                                    self._ghost.height() // 2))

    def mouseReleaseEvent(self, e):
        if self._ghost:
            self._ghost.hide()
            self._ghost.deleteLater()
            self._ghost = None
            # find target tile under cursor
            gpos = e.globalPosition().toPoint()
            self._try_swap(gpos)
            self._drag_start = None
            return
        self._drag_start = None
        super().mouseReleaseEvent(e)

    def _start_ghost(self):
        pm = self.grab()
        ghost = QLabel(None)
        ghost.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        ghost.setAttribute(Qt.WA_TranslucentBackground)
        ghost.setAttribute(Qt.WA_ShowWithoutActivating)
        # 50% opacity via pixmap
        faded = QPixmap(pm.size())
        faded.fill(Qt.transparent)
        pp = QPainter(faded)
        pp.setOpacity(0.5)
        pp.drawPixmap(0, 0, pm)
        pp.end()
        ghost.setPixmap(faded)
        ghost.setFixedSize(pm.size())
        ghost.show()
        self._ghost = ghost

    def _try_swap(self, gpos: QPoint):
        dock = self._dock
        grid = dock.grid
        for i in range(grid.count()):
            w = grid.itemAt(i).widget()
            if w is None or w is self:
                continue
            if isinstance(w, DraggableTile) and w.geometry().translated(
                    dock.grid_holder.mapToGlobal(QPoint(0, 0))).contains(gpos):
                target_idx = w._app_index
                self._swap(self._app_index, target_idx)
                return
            # also check via global geometry of the widget
            wg = w.mapToGlobal(QPoint(0, 0))
            wr = QRect(wg.x(), wg.y(), w.width(), w.height())
            if wr.contains(gpos) and isinstance(w, DraggableTile):
                self._swap(self._app_index, w._app_index)
                return

    def _do_flash(self):
        ac = QColor(self._dock.group.accent)
        self.setStyleSheet(
            f"QToolButton {{ background: rgba({ac.red()},{ac.green()},{ac.blue()},100); }}"
        )
        QTimer.singleShot(150, lambda: self.setStyleSheet(""))

    def set_pinned(self, pinned: bool):
        self._is_pinned = pinned

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._is_pinned:
            p = QPainter(self)
            ac = QColor(self._dock.group.accent)
            ac.setAlpha(220)
            p.fillRect(0, 0, 5, 5, ac)
            p.end()

    def _swap(self, i: int, j: int):
        if i == j:
            return
        dock = self._dock
        docks = dock.group.group_cfg.get("docks", [])
        if self._dock_index >= len(docks):
            return
        apps = docks[self._dock_index].get("apps", [])
        if i >= len(apps) or j >= len(apps):
            return
        apps[i], apps[j] = apps[j], apps[i]
        save_config(dock.group.controller.cfg)
        dock.rebuild()


# Feature: Clipboard history tile
class ClipboardTile(QWidget):
    """Last 5 clipboard entries — click any to paste."""

    _MENU_SS = """
        QMenu { background: rgb(14,17,22); border: 1px solid rgba(255,255,255,28);
                color: #EEF2F8; font: 10px 'Segoe UI'; padding: 2px; }
        QMenu::item { padding: 5px 18px; }
        QMenu::item:selected { background: rgba(255,255,255,18); }
        QMenu::separator { height: 1px; background: rgba(255,255,255,15); margin: 3px 0; }
    """

    def __init__(self, accent: str, size: int, on_remove, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._sz = size
        self._on_remove = on_remove
        tile = size + 12
        self.setFixedSize(tile * 2, tile)
        self._entries: list[str] = []
        self._hover_idx = -1
        self._last_text = ""

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check)
        self._poll.start(700)

        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

    def _check(self):
        text = QApplication.clipboard().text().strip()
        if text and text != self._last_text:
            self._last_text = text
            if text in self._entries:
                self._entries.remove(text)
            self._entries.insert(0, text)
            if len(self._entries) > 5:
                self._entries.pop()
            self.update()

    def _row_rects(self):
        r = self.rect()
        n = len(self._entries)
        if not n:
            return []
        rh = r.height() // n
        return [QRect(0, i * rh, r.width(), rh) for i in range(n)]

    def _hit(self, pos):
        for i, rr in enumerate(self._row_rects()):
            if rr.contains(pos):
                return i
        return -1

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            idx = self._hit(e.pos())
            if 0 <= idx < len(self._entries):
                QApplication.clipboard().setText(self._entries[idx])
                def _paste():
                    ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0x56, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0x56, 0, 2, 0)
                    ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)
                QTimer.singleShot(200, _paste)

    def mouseMoveEvent(self, e):
        h = self._hit(e.pos())
        if h != self._hover_idx:
            self._hover_idx = h
            self.update()

    def leaveEvent(self, e):
        if self._hover_idx != -1:
            self._hover_idx = -1
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect()
        ac = self._accent
        p.fillRect(r, QColor(14, 17, 22, 220))
        p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), 80), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))

        if not self._entries:
            p.setFont(QFont("Segoe UI", max(7, self._sz // 10)))
            p.setPen(QColor(100, 110, 130, 130))
            p.drawText(r, Qt.AlignCenter, "clipboard")
            p.end(); return

        tf = QFont("Segoe UI", max(8, self._sz // 12))
        p.setFont(tf)
        fm = p.fontMetrics()
        pad = 7
        rows = self._row_rects()
        for i, (text, rr) in enumerate(zip(self._entries, rows)):
            if i == self._hover_idx:
                p.fillRect(rr.adjusted(1, 0, -1, 0), QColor(ac.red(), ac.green(), ac.blue(), 28))
            if i > 0:
                p.setPen(QPen(QColor(255, 255, 255, 12), 1))
                p.drawLine(rr.left() + pad, rr.top(), rr.right() - pad, rr.top())
            alpha = 200 if i == self._hover_idx else max(70, 170 - i * 30)
            p.setPen(QColor(ac.red(), ac.green(), ac.blue(), alpha) if i == 0
                     else QColor(190, 200, 215, alpha))
            elided = fm.elidedText(text.replace('\n', ' '), Qt.ElideRight, r.width() - pad * 2)
            ty = rr.top() + (rr.height() + fm.ascent() - fm.descent()) // 2
            p.drawText(pad, ty, elided)
        p.end()

    def _ctx(self, pos):
        m = QMenu(self)
        m.setStyleSheet(self._MENU_SS)
        a = QAction("Clear history", m)
        a.triggered.connect(lambda: (self._entries.clear(), self.update()))
        m.addAction(a)
        m.addSeparator()
        r = QAction("Remove tile", m)
        r.triggered.connect(lambda _: self._on_remove())
        m.addAction(r)
        m.exec(self.mapToGlobal(pos))


# Feature: Stopwatch tile
class StopwatchTile(QWidget):
    """Tap to start/stop; right-click to reset."""

    _MENU_SS = ClipboardTile._MENU_SS

    def __init__(self, accent: str, size: int, on_remove, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._sz = size
        self._on_remove = on_remove
        tile = size + 12
        self.setFixedSize(tile, tile)
        self._elapsed = 0.0
        self._running = False
        self._last_t = 0.0

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._update)
        self._tick.start(80)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

    def _update(self):
        if self._running:
            now = time.monotonic()
            self._elapsed += now - self._last_t
            self._last_t = now
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._running = not self._running
            self._last_t = time.monotonic()
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect()
        ac = self._accent
        p.fillRect(r, QColor(14, 17, 22, 220))
        p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), 80), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))

        total = int(self._elapsed)
        mins, secs = total // 60, total % 60
        hrs = mins // 60; mins %= 60
        ts = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins:02d}:{secs:02d}"
        tenth = int((self._elapsed % 1) * 10)
        sub = f".{tenth}"

        tf = QFont("Segoe UI", max(13, self._sz // 5))
        tf.setBold(True)
        sf = QFont("Segoe UI", max(9, self._sz // 7))
        tfm = QFontMetrics(tf)
        sfm = QFontMetrics(sf)

        main_w = tfm.horizontalAdvance(ts)
        sub_w  = sfm.horizontalAdvance(sub)
        start_x = r.center().x() - (main_w + sub_w) // 2
        baseline_y = r.center().y() + tfm.ascent() // 2 - 1

        p.setFont(tf)
        p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 220))
        p.drawText(start_x, baseline_y, ts)

        p.setFont(sf)
        p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 120))
        p.drawText(start_x + main_w, baseline_y, sub)

        # running indicator dot
        dot_c = QColor(ac.red(), ac.green(), ac.blue(), 180 if self._running else 50)
        p.setPen(Qt.NoPen); p.setBrush(dot_c)
        p.drawRect(r.right() - 7, r.top() + 4, 4, 4)
        p.end()

    def _ctx(self, pos):
        m = QMenu(self)
        m.setStyleSheet(self._MENU_SS)
        a = QAction("Reset", m)
        a.triggered.connect(lambda: (setattr(self, '_elapsed', 0.0),
                                     setattr(self, '_running', False),
                                     self.update()))
        m.addAction(a)
        m.addSeparator()
        r = QAction("Remove tile", m)
        r.triggered.connect(lambda _: self._on_remove())
        m.addAction(r)
        m.exec(self.mapToGlobal(pos))


class GlitchCard(QFrame):
    """QFrame that can paint faint glitch bars over its normal content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars: list = []

    def set_bars(self, bars):
        self._bars = bars
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._bars:
            p = QPainter(self)
            for y, h, alpha in self._bars:
                p.fillRect(0, y, self.width(), h, QColor(255, 255, 255, alpha))
            p.end()


class GridDock(QWidget):
    """Single translucent dock panel."""

    def __init__(self, group: "DockGroup", dock_index: int):
        super().__init__(None)
        self.group = group
        self.dock_index = dock_index
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # show: TV scan-line expand from connected edge
        self._show_anim = QPropertyAnimation(self, b"geometry", self)
        self._show_anim.setDuration(260)
        self._show_anim.setEasingCurve(QEasingCurve.OutCubic)

        # hide: reverse TV shrink back to connected edge
        self._hide_shrink = QPropertyAnimation(self, b"geometry", self)
        self._hide_shrink.setDuration(220)
        self._hide_shrink.setEasingCurve(QEasingCurve.InCubic)
        self._hide_shrink.finished.connect(self._on_hide_done)
        self._hiding = False
        self._last_edge = 'bottom'
        self._last_target = QPoint()

        self._glitch_timer = QTimer(self)
        self._glitch_timer.setInterval(40)
        self._glitch_timer.timeout.connect(self._glitch_tick)
        self._glitch_ticks = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_DOCK_M, _DOCK_M, _DOCK_M, _DOCK_M)
        outer.setSpacing(0)

        self.card = GlitchCard(self)
        self.card.setObjectName("card")
        self._shadow = QGraphicsDropShadowEffect(self.card)
        self._shadow.setBlurRadius(18)
        self._shadow.setOffset(0, 2)
        self._shadow.setColor(QColor(0, 0, 0, 160))
        self.card.setGraphicsEffect(self._shadow)
        outer.addWidget(self.card)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.drag_bar = DragBar(self)
        self.drag_bar.setFixedHeight(7)
        self.drag_bar.hide()
        body.addWidget(self.drag_bar)

        inner = QVBoxLayout()
        inner.setContentsMargins(14, 10, 14, 12)
        inner.setSpacing(8)

        # title row: label | stretch | +
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        self.title = EditableLabel(self._dock_name(), self._rename_dock)
        self.title.setObjectName("title")
        title_row.addWidget(self.title)
        title_row.addStretch()
        self.add_btn = QToolButton(self.card)
        self.add_btn.setObjectName("add_inline")
        self.add_btn.setText("+")
        self.add_btn.setFixedSize(18, 16)
        self.add_btn.setPopupMode(QToolButton.InstantPopup)

        _ctrl = self.group.controller
        _add_menu = QMenu(self.add_btn)
        _add_menu.setStyleSheet("""
            QMenu {
                background: rgb(14,17,22);
                border: 1px solid rgba(255,255,255,28);
                color: #EEF2F8; font: 10px 'Segoe UI'; padding: 2px;
            }
            QMenu::item { padding: 5px 18px; }
            QMenu::item:selected { background: rgba(255,255,255,18); }
        """)
        _triggered = [False]

        def _on_show():
            _ctrl._dialog_open = True
            _triggered[0] = False

        def _on_hide():
            if not _triggered[0]:
                _ctrl._dialog_open = False

        _add_menu.aboutToShow.connect(_on_show)
        _add_menu.aboutToHide.connect(_on_hide)

        def _do_file():
            _triggered[0] = True
            self.group.add_app(self.dock_index)

        def _do_url():
            _triggered[0] = True
            self._add_url()

        def _do_widget(kind):
            _triggered[0] = True
            self._add_widget(kind)

        act_file = QAction("Add file…", _add_menu)
        act_file.triggered.connect(lambda _: _do_file())
        act_url_item = QAction("Add URL…", _add_menu)
        act_url_item.triggered.connect(lambda _: _do_url())
        _add_menu.addAction(act_file)
        _add_menu.addAction(act_url_item)
        _add_menu.addSeparator()
        act_clock = QAction("Add clock", _add_menu)
        act_clock.triggered.connect(lambda _: _do_widget("clock"))
        _add_menu.addAction(act_clock)
        act_sysinfo = QAction("Add system info", _add_menu)
        act_sysinfo.triggered.connect(lambda _: _do_widget("sysinfo"))
        _add_menu.addAction(act_sysinfo)
        act_volume = QAction("Add volume", _add_menu)
        act_volume.triggered.connect(lambda _: _do_widget("volume"))
        _add_menu.addAction(act_volume)
        act_nowplaying = QAction("Add now playing", _add_menu)
        act_nowplaying.triggered.connect(lambda _: _do_widget("nowplaying"))
        _add_menu.addAction(act_nowplaying)
        act_note = QAction("Add note", _add_menu)
        act_note.triggered.connect(lambda _: _do_widget("note"))
        _add_menu.addAction(act_note)
        act_clip = QAction("Add clipboard", _add_menu)
        act_clip.triggered.connect(lambda _: _do_widget("clipboard"))
        _add_menu.addAction(act_clip)
        act_sw = QAction("Add stopwatch", _add_menu)
        act_sw.triggered.connect(lambda _: _do_widget("stopwatch"))
        _add_menu.addAction(act_sw)
        self.add_btn.setMenu(_add_menu)
        title_row.addWidget(self.add_btn)

        self._collapsed = False
        self._collapse_btn = QToolButton(self.card)
        self._collapse_btn.setObjectName("add_inline")
        self._collapse_btn.setText("−")
        self._collapse_btn.setFixedSize(14, 16)
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        title_row.addWidget(self._collapse_btn)

        inner.addLayout(title_row)

        self.grid_holder = QWidget(self.card)
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        inner.addWidget(self.grid_holder)

        body.addLayout(inner)
        self.apply_theme()

    # ------------------------------------------------------------------
    def _pin_app(self, app_idx: int):
        apps = self._dock_apps()
        if app_idx >= len(apps):
            return
        app = apps[app_idx]
        currently_pinned = app.get("pinned", False)
        app["pinned"] = not currently_pinned
        if app["pinned"]:
            # Move to front so it stays at position 0
            apps.insert(0, apps.pop(app_idx))
        save_config(self.group.controller.cfg)
        self.rebuild()

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self.grid_holder.setVisible(not self._collapsed)
        self._collapse_btn.setText("+" if self._collapsed else "−")
        self.card.adjustSize()
        self.adjustSize()

    def _dock_name(self) -> str:
        docks = self.group.group_cfg.get("docks", [])
        if self.dock_index < len(docks):
            return docks[self.dock_index].get("name", f"DOCK {self.dock_index + 1}")
        return f"DOCK {self.dock_index + 1}"

    def _dock_apps(self) -> list:
        docks = self.group.group_cfg.get("docks", [])
        if self.dock_index < len(docks):
            return docks[self.dock_index].get("apps", [])
        return []

    def _tile_icon(self, app: dict) -> QIcon:
        path = app.get("path", "")
        if path.startswith("__widget:"):
            return QIcon()
        custom = app.get("icon")
        if custom and os.path.exists(custom):
            icon = QIcon(custom)
            if not icon.isNull():
                return icon
        if path.startswith(("http://", "https://")):
            return QApplication.style().standardIcon(
                QApplication.style().StandardPixmap.SP_DriveNetIcon
            )
        return file_icon(path)

    def _rename_dock(self, name: str):
        docks = self.group.group_cfg.get("docks", [])
        if self.dock_index < len(docks):
            docks[self.dock_index]["name"] = name
        save_config(self.group.controller.cfg)

    def _start_glitch(self):
        self._glitch_ticks = 0
        self._glitch_timer.start()

    def _glitch_tick(self):
        self._glitch_ticks += 1
        if self._glitch_ticks > 6:
            self._glitch_timer.stop()
            self.card.set_bars([])
            return
        ch = self.card.height()
        if ch < 4:
            return
        bars = []
        for _ in range(random.randint(1, 3)):
            y = random.randint(0, max(1, ch - 3))
            h = random.randint(1, 3)
            alpha = random.randint(10, 38)
            bars.append((y, h, alpha))
        self.card.set_bars(bars)

    def show_animated(self, target: QPoint, edge: str = 'bottom'):
        self._hide_shrink.stop()
        self._hiding = False
        self.setWindowOpacity(1.0)
        self._last_edge = edge
        self._last_target = target
        w, h = self.width(), self.height()
        M = _DOCK_M
        ch, cw = h - 2 * M, w - 2 * M
        if edge == 'top':
            thin = QRect(target.x(), target.y(), w, 2 + 2 * M)
        elif edge == 'bottom':
            thin = QRect(target.x(), target.y() + ch - 2, w, 2 + 2 * M)
        elif edge == 'left':
            thin = QRect(target.x(), target.y(), 2 + 2 * M, h)
        elif edge == 'right':
            thin = QRect(target.x() + cw - 2, target.y(), 2 + 2 * M, h)
        else:
            thin = QRect(target.x(), target.y() + ch // 2 - 1, w, 2 + 2 * M)
        full = QRect(target.x(), target.y(), w, h)
        self.setGeometry(thin)
        self.show()
        self._show_anim.setStartValue(thin)
        self._show_anim.setEndValue(full)
        self._show_anim.start()
        self._start_glitch()

    def hide_animated(self):
        if not self.isVisible():
            return
        self._show_anim.stop()
        self._hiding = True
        tgt = self._last_target
        edge = self._last_edge
        w, h = self.width(), self.height()
        M = _DOCK_M
        ch, cw = h - 2 * M, w - 2 * M
        if edge == 'top':
            thin = QRect(tgt.x(), tgt.y(), w, 2 + 2 * M)
        elif edge == 'bottom':
            thin = QRect(tgt.x(), tgt.y() + ch - 2, w, 2 + 2 * M)
        elif edge == 'left':
            thin = QRect(tgt.x(), tgt.y(), 2 + 2 * M, h)
        elif edge == 'right':
            thin = QRect(tgt.x() + cw - 2, tgt.y(), 2 + 2 * M, h)
        else:
            thin = QRect(tgt.x(), tgt.y() + ch // 2 - 1, w, 2 + 2 * M)
        self._hide_shrink.setStartValue(self.geometry())
        self._hide_shrink.setEndValue(thin)
        self._hide_shrink.start()
        self._start_glitch()

    def _on_hide_done(self):
        if self._hiding:
            self.hide()
            self._hiding = False
            self.group._on_dock_hidden()

    def update_edit_mode(self):
        em = self.group.controller.edit_mode
        self.drag_bar.setFixedHeight(7 if em else 0)
        self.drag_bar.setVisible(em)
        self.card.adjustSize()
        self.adjustSize()

    def apply_theme(self):
        accent = self.group.accent
        bc = QColor(accent); bc.setAlpha(55)
        border = f"rgba({bc.red()},{bc.green()},{bc.blue()},{bc.alpha()})"
        self.setStyleSheet(f"""
            #card {{
                background-color: rgba(14,17,22,236);
                border-radius: 0px;
                border: 1px solid {border};
            }}
            #title {{ color: #7C8696; font: bold 9px 'Segoe UI'; letter-spacing: 2px; }}
            #add_inline {{
                background: transparent; color: {accent};
                border: none; font: bold 14px 'Segoe UI'; padding: 0px;
            }}
            #add_inline:hover {{ background: rgba(255,255,255,20); }}
            QToolButton {{
                background: transparent; color: #EEF2F8;
                border: none; border-radius: 0px;
                padding: 8px; font: 9px 'Segoe UI';
            }}
            QToolButton:hover {{ background: rgba(255,255,255,20); }}
        """)

    def _clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _tile(self, name, icon, on_click, on_change_icon=None, on_remove=None, app_index=0, file_path="", is_pinned=False, on_pin=None):
        btn = DraggableTile(self, self.dock_index, app_index, self.grid_holder)
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        sz = self.group.controller.cfg["icon_size"]
        btn.setIcon(icon)
        btn.setIconSize(QSize(sz, sz))
        btn.setToolTip(name)
        btn.setFixedSize(sz + 12, sz + 12)
        btn.set_pinned(is_pinned)
        btn._on_remove = on_remove

        def _clicked_with_flash(_=False, _b=btn, _cb=on_click):
            _b._do_flash()
            QTimer.singleShot(110, _cb)
        btn.clicked.connect(_clicked_with_flash)

        btn.setContextMenuPolicy(Qt.CustomContextMenu)
        ctrl = self.group.controller
        def show_menu(pos, b=btn, fp=file_path, pinned=is_pinned):
            ctrl._dialog_open = True
            m = QMenu(b)
            m.setStyleSheet("""
                QMenu {
                    background: rgb(14,17,22);
                    border: 1px solid rgba(255,255,255,28);
                    color: #EEF2F8; font: 10px 'Segoe UI'; padding: 2px;
                }
                QMenu::item { padding: 5px 18px; }
                QMenu::item:selected { background: rgba(255,255,255,18); }
                QMenu::separator { height: 1px; background: rgba(255,255,255,15); margin: 3px 0; }
            """)
            if on_pin:
                pin_label = "Unpin" if pinned else "Pin to top"
                a_pin = QAction(pin_label, m)
                a_pin.triggered.connect(lambda _: on_pin())
                m.addAction(a_pin)
                m.addSeparator()
            if fp and not fp.startswith(("http://", "https://")):
                a_loc = QAction("Open file location", m)
                a_loc.triggered.connect(lambda _, p=fp: _open_file_location(p))
                m.addAction(a_loc)
                m.addSeparator()
            if on_change_icon:
                a = QAction("Change icon…", m)
                a.triggered.connect(lambda _: on_change_icon())
                m.addAction(a)
                m.addSeparator()
            if on_remove:
                a = QAction("Remove", m)
                a.triggered.connect(lambda _: on_remove())
                m.addAction(a)
            m.exec(b.mapToGlobal(pos))
            ctrl._dialog_open = False
        btn.customContextMenuRequested.connect(show_menu)
        return btn

    def rebuild(self):
        self._clear_grid()
        cols = max(1, int(self.group.controller.cfg["columns"]))
        sz = self.group.controller.cfg["icon_size"]
        cfg = self.group.controller.cfg
        apps = self._dock_apps()
        # track grid position manually (needed for NowPlaying 1x2 span)
        row, col = 0, 0
        for app_idx, app in enumerate(apps):
            path = app.get("path", "")
            if path == "__widget:clock__":
                tile = ClockTile(
                    self.group.accent, sz,
                    lambda p=path: self.group.remove_app(self.dock_index, p),
                    self.grid_holder,
                )
                self.grid.addWidget(tile, row, col)
                col += 1
                if col >= cols:
                    col = 0; row += 1
            elif path == "__widget:sysinfo__":
                tile = SysInfoTile(
                    self.group.accent, sz,
                    lambda p=path: self.group.remove_app(self.dock_index, p),
                    self.grid_holder,
                )
                self.grid.addWidget(tile, row, col)
                col += 1
                if col >= cols:
                    col = 0; row += 1
            elif path == "__widget:volume__":
                tile = VolumeTile(
                    self.group.accent, sz,
                    lambda p=path: self.group.remove_app(self.dock_index, p),
                    self.grid_holder,
                )
                self.grid.addWidget(tile, row, col)
                col += 1
                if col >= cols:
                    col = 0; row += 1
            elif path == "__widget:nowplaying__":
                tile = NowPlayingTile(
                    self.group.accent, sz,
                    lambda p=path: self.group.remove_app(self.dock_index, p),
                    self.grid_holder,
                )
                span = min(2, cols - col)
                self.grid.addWidget(tile, row, col, 1, max(1, span))
                col += 2
                if col >= cols:
                    col = 0; row += 1
            elif path == "__widget:note__":
                note_key = f"{self._dock_name()}_{app_idx}"
                tile = QuickNoteTile(
                    self.group.accent, sz, note_key,
                    lambda p=path: self.group.remove_app(self.dock_index, p),
                    cfg,
                    self.grid_holder,
                )
                self.grid.addWidget(tile, row, col)
                col += 1
                if col >= cols:
                    col = 0; row += 1
            elif path == "__widget:clipboard__":
                tile = ClipboardTile(
                    self.group.accent, sz,
                    lambda p=path: self.group.remove_app(self.dock_index, p),
                    self.grid_holder,
                )
                span = min(2, cols - col)
                self.grid.addWidget(tile, row, col, 1, max(1, span))
                col += 2
                if col >= cols:
                    col = 0; row += 1
            elif path == "__widget:stopwatch__":
                tile = StopwatchTile(
                    self.group.accent, sz,
                    lambda p=path: self.group.remove_app(self.dock_index, p),
                    self.grid_holder,
                )
                self.grid.addWidget(tile, row, col)
                col += 1
                if col >= cols:
                    col = 0; row += 1
            else:
                app_name = app.get("name") or display_name(path)
                tile = self._tile(
                    app_name,
                    self._tile_icon(app),
                    lambda _=False, p=path: self.group.launch_and_hide(p),
                    on_change_icon=lambda a=app: self._change_icon(a),
                    on_remove=lambda p=path: self.group.remove_app(self.dock_index, p),
                    app_index=app_idx,
                    file_path=path,
                    is_pinned=app.get("pinned", False),
                    on_pin=lambda idx=app_idx: self._pin_app(idx),
                )
                self.grid.addWidget(tile, row, col)
                col += 1
                if col >= cols:
                    col = 0; row += 1
        self.title.setText(self._dock_name())
        self.card.adjustSize()
        self.adjustSize()

    def _add_app(self):
        self.group.add_app(self.dock_index)

    def _add_url(self):
        ctrl = self.group.controller
        ctrl._dialog_open = True
        dlg = URLDialog(ctrl.cfg)
        dlg.adjustSize()
        avail = QGuiApplication.primaryScreen().availableGeometry()
        geo = self.frameGeometry()
        x = geo.right() + 8
        y = geo.top()
        if x + dlg.width() > avail.right():
            x = geo.left() - dlg.width() - 8
        dlg.move(max(avail.left() + 4, x), max(avail.top() + 4, y))
        result = dlg.exec()
        ctrl._dialog_open = False
        if result == QDialog.Accepted:
            vals = dlg.values()
            if vals["url"]:
                docks = self.group.group_cfg.setdefault("docks", [])
                while len(docks) <= self.dock_index:
                    docks.append({"name": f"DOCK {len(docks)+1}", "apps": [], "pos": None})
                docks[self.dock_index]["apps"].append({
                    "name": vals["name"],
                    "path": vals["url"],
                })
                save_config(ctrl.cfg)
                self.rebuild()

    def _add_widget(self, kind: str):
        docks = self.group.group_cfg.setdefault("docks", [])
        while len(docks) <= self.dock_index:
            docks.append({"name": f"DOCK {len(docks)+1}", "apps": [], "pos": None})
        names = {"clock": "Clock", "sysinfo": "System Info",
                 "volume": "Volume", "nowplaying": "Now Playing", "note": "Note",
                 "clipboard": "Clipboard", "stopwatch": "Stopwatch"}
        docks[self.dock_index]["apps"].append({
            "name": names.get(kind, kind),
            "path": f"__widget:{kind}__",
        })
        save_config(self.group.controller.cfg)
        self.rebuild()

    def _change_icon(self, app: dict):
        self.group.controller._dialog_open = True
        path, _ = QFileDialog.getOpenFileName(
            None, "Choose icon", "",
            "Images & icons (*.png *.ico *.jpg *.jpeg *.bmp);;All files (*.*)",
        )
        self.group.controller._dialog_open = False
        if path:
            app["icon"] = path
            save_config(self.group.controller.cfg)
            self.rebuild()


class DockGroup:
    """One independent activation handle + N docks + connector line."""

    def __init__(self, controller: "Controller", group_index: int):
        self.controller = controller
        self.group_index = group_index
        self._leave_time: float | None = None

        n = len(self.group_cfg.get("docks", []))
        self.handle = Handle(self)
        self.docks = [GridDock(self, i) for i in range(n)]
        self.connector = LineConnector()

        self._place_handle()
        self.handle.show()

    @property
    def group_cfg(self) -> dict:
        return self.controller.cfg["groups"][self.group_index]

    @property
    def accent(self) -> str:
        return self.group_cfg.get("accent", self.controller.cfg.get("accent", DEFAULTS["accent"]))

    # --- placement ---
    def _place_handle(self):
        avail = QGuiApplication.primaryScreen().availableGeometry()
        pos = self.group_cfg.get("handle_pos")
        if not pos:
            n_groups = len(self.controller.cfg.get("groups", [1]))
            frac = (self.group_index + 1) / (n_groups + 1)
            x = int(avail.left() + avail.width() * frac) - 35
            pos = [x, avail.bottom() - 90]
        self.handle.move(int(pos[0]), int(pos[1]))

    def _dock_default_pos(self, dock_index: int) -> QPoint:
        avail = QGuiApplication.primaryScreen().availableGeometry()
        h = self.handle.frameGeometry()
        gap = 12
        total_w = sum(d.width() for d in self.docks) + gap * max(len(self.docks) - 1, 0)
        sx = h.center().x() - total_w // 2
        sx = max(avail.left() + 6, min(sx, avail.right() - total_w - 6))
        x = sx + sum(self.docks[i].width() + gap for i in range(dock_index))
        y = h.top() - self.docks[dock_index].height() - 14
        if y < avail.top():
            y = h.bottom() + 14
        return QPoint(x, y)

    def _get_dock_pos(self, dock_index: int) -> QPoint:
        docks = self.group_cfg.get("docks", [])
        if dock_index < len(docks):
            pos = docks[dock_index].get("pos")
            if pos:
                return QPoint(int(pos[0]), int(pos[1]))
        return self._dock_default_pos(dock_index)

    # --- show / hide ---
    def _show_all_docks(self, animated: bool = True):
        for dock in self.docks:
            dock.rebuild()
            dock.update_edit_mode()

        card_hints = [dock.card.sizeHint() for dock in self.docks]
        targets = [self._get_dock_pos(i) for i in range(len(self.docks))]

        # Pre-position docks so connector endpoints are accurate before animation starts
        for dock, target in zip(self.docks, targets):
            dock.move(target)

        h_center = self.handle.frameGeometry().center()
        style = self.controller.cfg.get("connector_style", "straight")
        self.connector.set_style(style)
        self.connector.set_thickness(self.controller.cfg.get("connector_thickness", 2))
        edges_pts = [
            _closest_edge(
                QRect(t.x() + _DOCK_M, t.y() + _DOCK_M, cs.width(), cs.height()),
                h_center
            )
            for t, cs in zip(targets, card_hints)
        ]
        edges = [e for e, _ in edges_pts]
        pts = [pt for _, pt in edges_pts]
        self.connector.set_connections(h_center, pts, self.accent)
        self.connector.show()
        if animated:
            self.connector.start_grow()

        for dock, target, edge in zip(self.docks, targets, edges):
            if animated:
                dock.show_animated(target, edge)
            else:
                dock.show()

    def show_grid(self):
        hiding = [d for d in self.docks if d._hiding]
        for d in hiding:
            d._hide_shrink.stop()
            d._hiding = False
        if any(d.isVisible() and not d._hiding for d in self.docks) and not hiding:
            return

        # Phase 1 — rebuild docks so sizes are correct, compute positions, resolve overlaps
        for dock in self.docks:
            dock.rebuild()
            dock.update_edit_mode()
        # card.sizeHint() is reliable for child widgets even when the parent window is hidden
        card_hints = [dock.card.sizeHint() for dock in self.docks]
        raw = [self._get_dock_pos(i) for i in range(len(self.docks))]
        input_rects = [
            QRect(p.x(), p.y(), cs.width() + 2*_DOCK_M, cs.height() + 2*_DOCK_M)
            for p, cs in zip(raw, card_hints)
        ]
        resolved = _resolve_overlaps(input_rects, margin=12)
        positions = [r.topLeft() for r in resolved]
        for dock, pos in zip(self.docks, positions):
            dock.move(pos)

        # Phase 2 — grow connector lines using explicit card rects (reliable for hidden windows)
        h_center = self.handle.frameGeometry().center()
        style = self.controller.cfg.get("connector_style", "straight")
        self.connector.set_style(style)
        self.connector.set_thickness(self.controller.cfg.get("connector_thickness", 2))
        edges_pts = [
            _closest_edge(
                QRect(pos.x() + _DOCK_M, pos.y() + _DOCK_M, cs.width(), cs.height()),
                h_center
            )
            for pos, cs in zip(positions, card_hints)
        ]
        edges = [e for e, _ in edges_pts]
        pts   = [pt for _, pt in edges_pts]
        self.connector.set_connections(h_center, pts, self.accent)
        self.connector.show()
        self.connector.start_grow()

        # Phase 3 — TV-effect reveal each dock from its connected edge outward
        def _reveal():
            for dock, pos, edge in zip(self.docks, positions, edges):
                dock.show_animated(pos, edge)
        QTimer.singleShot(220, _reveal)

    def _update_connector(self):
        visible = [d for d in self.docks if d.isVisible()]
        if not visible:
            self.connector.hide(); return
        h_center = self.handle.frameGeometry().center()
        style = self.controller.cfg.get("connector_style", "straight")
        self.connector.set_style(style)
        self.connector.set_thickness(self.controller.cfg.get("connector_thickness", 2))
        pts = [_closest_edge_mid(_card_rect(d), h_center) for d in visible]
        self.connector.set_connections(h_center, pts, self.accent)
        self.connector.show()

    def _all_visible(self) -> bool:
        return any(d.isVisible() for d in self.docks)

    def _hide_all(self):
        self._leave_time = None
        for dock in self.docks:
            dock.hide_animated()
        # let docks shrink first, then retract the connector lines back to handle
        QTimer.singleShot(120, self.connector.start_shrink)

    def _on_dock_hidden(self):
        pass  # connector retracts on its own via start_shrink in _hide_all

    # --- tick ---
    def tick(self):
        if self.controller._dialog_open:
            return
        if self.controller.edit_mode:
            if not self._all_visible():
                self._show_all_docks(animated=True)
            return
        # Always hide during a true fullscreen app
        if is_fullscreen_foreign():
            if self._all_visible():
                self._hide_all()
            return
        pos = QCursor.pos()
        over_handle = self.handle.frameGeometry().adjusted(-10, -10, 10, 10).contains(pos)
        over_dock   = any(
            d.isVisible() and d.frameGeometry().adjusted(-10, -10, 10, 10).contains(pos)
            for d in self.docks
        )
        delay = float(self.controller.cfg.get("hide_delay", 1))
        if over_handle or over_dock:
            self._leave_time = None
            if not self._all_visible():
                if over_dock or is_desktop_active():
                    self.show_grid()
        elif self._all_visible():
            if self._leave_time is None:
                self._leave_time = time.monotonic()
            elif time.monotonic() - self._leave_time >= delay:
                self._leave_time = None
                self._hide_all()

    # --- actions ---
    def launch_and_hide(self, path: str):
        if not self.controller.edit_mode:
            self._hide_all()
        launch(path)

    def add_app(self, dock_index: int = 0):
        self.controller._dialog_open = True
        start_dir = os.path.expandvars(
            r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"
        )
        if not os.path.isdir(start_dir):
            start_dir = os.path.expanduser("~")
        files, _ = QFileDialog.getOpenFileNames(
            None, "Add apps", start_dir,
            "Programs & shortcuts (*.exe *.lnk *.bat *.url);;All files (*.*)",
        )
        self.controller._dialog_open = False
        if not files:
            return
        docks = self.group_cfg.setdefault("docks", [])
        while len(docks) <= dock_index:
            docks.append({"name": f"DOCK {len(docks)+1}", "apps": [], "pos": None})
        for path in files:
            docks[dock_index]["apps"].append({"name": display_name(path), "path": path})
        save_config(self.controller.cfg)
        for dock in self.docks:
            dock.rebuild()

    def remove_app(self, dock_index: int, path: str):
        docks = self.group_cfg.get("docks", [])
        if dock_index < len(docks):
            docks[dock_index]["apps"] = [
                a for a in docks[dock_index]["apps"] if a["path"] != path
            ]
        save_config(self.controller.cfg)
        for dock in self.docks:
            dock.rebuild()


class Controller:
    def __init__(self, app: QApplication):
        self.app = app
        self.cfg = load_config()
        self.edit_mode = False
        self._dialog_open = False

        self.groups = [DockGroup(self, i) for i in range(len(self.cfg["groups"]))]

        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(120)

        self._build_tray()

        # Feature 3: global hotkey Win+`
        self._hotkey_filter = None
        try:
            ok = ctypes.windll.user32.RegisterHotKey(
                None, _HOTKEY_ID, _MOD_WIN | _MOD_NOREPEAT, _VK_BACKTICK)
            if ok:
                self._hotkey_filter = HotkeyFilter(self._toggle_all_visibility)
                self.app.installNativeEventFilter(self._hotkey_filter)
        except Exception as e:
            print("hotkey register failed:", e)
        self.app.aboutToQuit.connect(self._cleanup)

    def _tick(self):
        for group in self.groups:
            group.tick()

    def _toggle_all_visibility(self):
        any_visible = any(
            any(d.isVisible() for d in g.docks) for g in self.groups
        )
        if any_visible:
            for g in self.groups:
                g._hide_all()
        else:
            for g in self.groups:
                g.show_grid()

    def _cleanup(self):
        try:
            ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID)
        except Exception:
            pass

    # --- edit mode ---
    def toggle_edit_mode(self, active: bool):
        self.edit_mode = active
        for group in self.groups:
            group.handle.update()
            if active:
                if not group._all_visible():
                    group._show_all_docks(animated=True)
                else:
                    for dock in group.docks:
                        dock.update_edit_mode()
            else:
                group._hide_all()

    def toggle_lock(self, checked: bool):
        self.cfg["handle_locked"] = bool(checked)
        save_config(self.cfg)

    # --- settings ---
    def open_settings(self):
        self._dialog_open = True
        dlg = SettingsDialog(self.cfg)
        result = dlg.exec()
        self._dialog_open = False
        if result == QDialog.Accepted:
            vals = dlg.values()
            self.cfg["columns"]              = vals["columns"]
            self.cfg["icon_size"]            = vals["icon_size"]
            self.cfg["connector_style"]      = vals["connector_style"]
            self.cfg["connector_thickness"]  = vals["connector_thickness"]
            self.cfg["hide_delay"]           = vals["hide_delay"]
            for i, accent in enumerate(vals["group_accents"]):
                if i < len(self.cfg["groups"]):
                    self.cfg["groups"][i]["accent"] = accent
            # apply dock count changes per existing group
            for group, new_count in zip(self.groups, vals.get("dock_counts", [])):
                cur = len(group.docks)
                if new_count > cur:
                    for j in range(cur, new_count):
                        group.group_cfg["docks"].append({
                            "name": f"DOCK {j + 1}", "apps": [], "pos": None,
                        })
                        group.docks.append(GridDock(group, j))
                elif new_count < cur:
                    for _ in range(cur - new_count):
                        old = group.docks.pop()
                        old.hide(); old.deleteLater()
                    group.group_cfg["docks"] = group.group_cfg["docks"][:new_count]
            # add / remove entire handles
            new_handle_count = vals.get("handle_count", len(self.groups))
            while len(self.groups) < new_handle_count:
                i = len(self.groups)
                gc = {"handle_pos": None, "accent": "#7A7AFF",
                      "docks": [{"name": "DOCK 1", "apps": [], "pos": None}]}
                self.cfg["groups"].append(gc)
                ng = DockGroup(self, i)
                self.groups.append(ng)
                ng.handle.show()
            while len(self.groups) > max(1, new_handle_count):
                grp = self.groups.pop()
                grp.connector.hide(); grp.connector.deleteLater()
                for d in grp.docks:
                    d.hide(); d.deleteLater()
                grp.handle.hide(); grp.handle.deleteLater()
                self.cfg["groups"].pop()
            save_config(self.cfg)
            for group in self.groups:
                group.handle.update()
                for dock in group.docks:
                    dock.apply_theme()
                    dock.rebuild()
                group._update_connector()
            self._refresh_tray_icon()

    # --- tray ---
    def _build_tray(self):
        self.tray = QSystemTrayIcon()
        self._refresh_tray_icon()
        self.tray.setToolTip("Dockle")
        self._tray_menu = self._make_tray_menu()
        self._tray_menu.aboutToShow.connect(self._sync_tray_menu)
        self.tray.setContextMenu(self._tray_menu)
        self.tray.show()

    def _refresh_tray_icon(self):
        accent = self.cfg["groups"][0].get("accent", DEFAULTS["accent"])
        self.tray.setIcon(QIcon(make_glyph_icon(accent)))

    def _sync_tray_menu(self):
        if hasattr(self, "_act_edit"):
            self._act_edit.blockSignals(True)
            self._act_edit.setChecked(self.edit_mode)
            self._act_edit.blockSignals(False)
        if hasattr(self, "_act_lock"):
            self._act_lock.blockSignals(True)
            self._act_lock.setChecked(self.cfg["handle_locked"])
            self._act_lock.blockSignals(False)
        if hasattr(self, "_act_startup"):
            self._act_startup.blockSignals(True)
            self._act_startup.setChecked(_is_startup_enabled())
            self._act_startup.blockSignals(False)

    def _make_tray_menu(self) -> QMenu:
        m = QMenu()
        self._act_edit = QAction("Show handles", m)
        self._act_edit.setCheckable(True)
        self._act_edit.setChecked(self.edit_mode)
        self._act_edit.toggled.connect(self.toggle_edit_mode)
        m.addAction(self._act_edit)
        m.addSeparator()
        a_set = QAction("Settings…", m)
        a_set.triggered.connect(self.open_settings)
        m.addAction(a_set)
        m.addSeparator()
        self._act_lock = QAction("Lock handle positions", m)
        self._act_lock.setCheckable(True)
        self._act_lock.setChecked(self.cfg["handle_locked"])
        self._act_lock.toggled.connect(self.toggle_lock)
        m.addAction(self._act_lock)
        self._act_startup = QAction("Run on startup", m)
        self._act_startup.setCheckable(True)
        self._act_startup.setChecked(_is_startup_enabled())
        self._act_startup.toggled.connect(_set_startup)
        m.addAction(self._act_startup)
        m.addSeparator()
        a_quit = QAction("Quit", m)
        a_quit.triggered.connect(self.app.quit)
        m.addAction(a_quit)
        return m

    def tray_menu(self) -> QMenu:
        self._sync_tray_menu()
        return self._tray_menu


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("No system tray available.")
    Controller(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
