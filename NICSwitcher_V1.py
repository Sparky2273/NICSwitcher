#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
NIC Switcher — Network adapter manager & network toolbox for Windows, Linux and macOS.

A single-file PyQt6 application:
  * Enable / disable / switch between network adapters in one click
  * Live traffic monitor, per-adapter internet test, public IP & geolocation
  * Speed test (bindable to a specific adapter), DNS benchmark, ping, traceroute,
    port check, IP lookup, active connections, network repair tools
  * English (default) and Persian (RTL) interface, dark / light themes
  * Cross-platform: Windows (PowerShell), Linux (iproute2 / NetworkManager) and macOS (networksetup)
  * Optional "start at system startup" on every platform (off by default)
  * System-tray control, profiles, display names, static IP / DHCP / DNS / metric
  * Operation Log page (what happened, when) with optional timestamped file logging
  * Total internet usage (download + upload) since the app started and an all-time saved total;
    both survive adapters being disabled, re-enabled or having their counters reset
  * About / Guide page with a quick-start guide, FAQ and support contact

Run from source:
    pip install -r requirements.txt
    python NICSwitcher_V1.py

Build a standalone single-file executable (needs:  pip install pyinstaller):
    python NICSwitcher_V1.py --build
which is equivalent to
    pyinstaller --noconsole --onefile --uac-admin --name NICSwitcher NICSwitcher_V1.py

Command-line flags:
    --minimized   start hidden in the system tray
    --build       build NICSwitcher.exe with PyInstaller
    --version     print the version

Everything (code, translations, icons) lives in this one file; nothing else is
needed at runtime.

MIT License — see the README for the full text.
"""
from __future__ import annotations

import base64
import ctypes
import http.client
import ipaddress
import json
import os
import plistlib
import random
import re
import shlex
import shutil
import socket
import ssl
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from collections import deque
from dataclasses import dataclass, field
from html import escape as html_escape
from string import Template

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QLockFile,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QRunnable,
    QSequentialAnimationGroup,
    QSettings,
    QSize,
    Qt,
    QThread,
    QThreadPool,
    QTimer,
    QUrl,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
    PYQT_VERSION_STR,
    QT_VERSION_STR,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# ----------------------------------------------------------------------------
# Application metadata — edit these before publishing
# ----------------------------------------------------------------------------
APP_NAME = "NIC Switcher"
APP_ID = "NICSwitcher"
APP_VERSION = "1.0.0"
DEVELOPER_NAME = "Sparky"          # <-- shown in the footer and the About page
GITHUB_REPO = "Sparky2273/NICSwitcher"                      # <-- e.g. "yourname/nic-switcher" (enables links & update check)
LICENSE_NAME = "MIT License"
STARTUP_TASK = "NICSwitcherAutostart"
TELEGRAM_USER = "Sparky2273"                                # <-- shown in the About / Guide page
TELEGRAM_URL = f"https://t.me/{TELEGRAM_USER}"
CONTACT_EMAIL = "mhashemi6699@gmail.com"
LOG_FILE_NAME = "nicswitcher.log"                           # optional file log (Settings / Operation Log page)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
SUPPORTED = IS_WINDOWS or IS_MAC or IS_LINUX
FROZEN = bool(getattr(sys, "frozen", False))
GITHUB_URL = f"https://github.com/{GITHUB_REPO}" if GITHUB_REPO else ""


# ----------------------------------------------------------------------------
# Preferences
# ----------------------------------------------------------------------------
class Prefs:
    DEFAULTS: dict = {
        "lang": "en", "theme": "light", "accent": "#5b8cff",
        "confirm_exclusive": False, "show_virtual": True, "show_hidden": False,
        "refresh_sec": 5, "close_to_tray": True, "notifications": True,
        "live_stats": True, "animations": True, "auto_public_ip": True,
        "file_logging": False, "usage_include_virtual": False,
    }

    def __init__(self) -> None:
        self._s = QSettings("NicSwitcher", "NicSwitcher")

    def get(self, key: str):
        default = self.DEFAULTS[key]
        value = self._s.value(key, default)
        if isinstance(default, bool):
            return value in (True, "true", "True", 1, "1")
        if isinstance(default, int):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        return str(value)

    def set(self, key: str, value) -> None:
        self._s.setValue(key, value)

    def get_json(self, key: str, default):
        try:
            data = json.loads(self._s.value(key, "null"))
            return default if data is None else data
        except (TypeError, ValueError):
            return default

    def set_json(self, key: str, data) -> None:
        self._s.setValue(key, json.dumps(data, ensure_ascii=False))

    def export_all(self) -> dict:
        return {k: self._s.value(k) for k in self._s.allKeys()}

    def import_all(self, data: dict) -> None:
        for k, v in data.items():
            self._s.setValue(k, v)

    def reset(self) -> None:
        self._s.clear()


PREFS = Prefs()


# ----------------------------------------------------------------------------
# Operation log (shown on the "Operation Log" page, optionally mirrored to a file)
# ----------------------------------------------------------------------------
class OperationLog(QObject):
    """Keeps a timestamped history of everything the app does.

    Entries live in memory (newest 2000) and are shown on the Operation Log page.
    When "Save log to file" is on, every entry is also appended to ``nicswitcher.log``
    (next to the program, or in the settings folder if that location is read-only).
    Call it from the GUI thread.
    """
    entryAdded = pyqtSignal(str, str, str)      # "YYYY-MM-DD HH:MM:SS", level, message
    cleared = pyqtSignal()
    fileLoggingChanged = pyqtSignal(bool)
    LEVELS = ("INFO", "SUCCESS", "WARNING", "ERROR")
    MAX_ENTRIES = 2000
    MAX_FILE_BYTES = 1_000_000
    MAX_MESSAGE = 700

    def __init__(self) -> None:
        super().__init__()
        self.entries: deque = deque(maxlen=self.MAX_ENTRIES)
        self._lock = threading.Lock()
        self._path = ""

    # -- recording
    def log(self, message, level: str = "INFO") -> None:
        level = level if level in self.LEVELS else "INFO"
        text = " ".join(str(message).split())           # one line per entry
        if len(text) > self.MAX_MESSAGE:
            text = text[: self.MAX_MESSAGE - 1] + "…"
        if not text:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self.entries.append((stamp, level, text))
        self.entryAdded.emit(stamp, level, text)
        if PREFS.get("file_logging"):
            self._write_file(stamp, level, text)

    def info(self, message) -> None:
        self.log(message, "INFO")

    def ok(self, message) -> None:
        self.log(message, "SUCCESS")

    def warn(self, message) -> None:
        self.log(message, "WARNING")

    def error(self, message) -> None:
        self.log(message, "ERROR")

    def snapshot(self) -> list[tuple[str, str, str]]:
        with self._lock:
            return list(self.entries)

    def clear(self) -> None:
        with self._lock:
            self.entries.clear()
        self.cleared.emit()

    def as_text(self, levels: tuple[str, ...] | None = None) -> str:
        return "\n".join(f"{t}  [{lv}]  {m}" for t, lv, m in self.snapshot() if levels is None or lv in levels)

    # -- file logging
    def path(self) -> str:
        if self._path:
            return self._path
        base = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
        for folder in (base, config_dir()):
            try:
                os.makedirs(folder, exist_ok=True)
                probe = os.path.join(folder, LOG_FILE_NAME)
                with open(probe, "a", encoding="utf-8"):
                    pass
                self._path = probe
                return probe
            except OSError:
                continue
        self._path = os.path.join(tempfile.gettempdir(), LOG_FILE_NAME)
        return self._path

    def set_file_logging(self, enabled: bool) -> None:
        PREFS.set("file_logging", enabled)
        if enabled:
            self.info(tr("File logging enabled → {p}", p=self.path()))
        else:
            self.info(tr("File logging disabled."))
        self.fileLoggingChanged.emit(enabled)

    def _write_file(self, stamp: str, level: str, text: str) -> None:
        try:
            path = self.path()
            if os.path.exists(path) and os.path.getsize(path) > self.MAX_FILE_BYTES:
                os.replace(path, path + ".1")             # keep one previous file
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"{stamp}  [{level}]  {text}\n")
        except OSError as e:
            PREFS.set("file_logging", False)              # do not fail again on every entry
            self.fileLoggingChanged.emit(False)
            self.log(tr("Could not write the log file: {e}", e=e), "ERROR")


OPLOG = OperationLog()


class UsageTracker:
    """Adds up network traffic from the *cumulative* byte counters of the adapters without losing data.

    An adapter's counters restart from zero when it is disabled and enabled again, reset, or its driver
    reloads. Every new sample is compared with the previous one of the same adapter:
      * bigger or equal  -> the difference is new traffic;
      * smaller          -> the counter was restarted, so the new value itself is the traffic since the restart.
    Totals only ever grow, so they never drop to 0 and never show a wrong (negative / huge) number.
    The first sample of an adapter is only a starting point (traffic before the app started is not counted).
    """

    def __init__(self) -> None:
        self._last: dict[str, tuple[int, int]] = {}
        self.session: dict[str, list[int]] = {}        # key -> [download bytes, upload bytes] since the app started

    def update(self, key: str, rx, tx) -> tuple[int, int, bool]:
        """Feed one sample; returns (new download bytes, new upload bytes, counters_were_restarted)."""
        try:
            rx, tx = max(0, int(rx)), max(0, int(tx))
        except (TypeError, ValueError):
            return 0, 0, False
        prev = self._last.get(key)
        self._last[key] = (rx, tx)
        tot = self.session.setdefault(key, [0, 0])
        if prev is None:
            return 0, 0, False
        d_rx = rx if rx < prev[0] else rx - prev[0]
        d_tx = tx if tx < prev[1] else tx - prev[1]
        tot[0] += d_rx
        tot[1] += d_tx
        return d_rx, d_tx, (rx < prev[0] or tx < prev[1])

# ----------------------------------------------------------------------------
# Internationalisation (English is the source language, Persian is a table)
# ----------------------------------------------------------------------------
LANG = "en"
LANGS = {"en": "English", "fa": "فارسی"}
FA: dict[str, str] = {}   # filled at the bottom of this file


def tr(text: str, **kw) -> str:
    out = FA.get(text, text) if LANG == "fa" else text
    return out.format(**kw) if kw else out


def ltr(text: str) -> str:
    """Force left-to-right rendering for IPs / MACs inside an RTL interface."""
    return f"\u202a{text}\u202c" if text else "—"


# ----------------------------------------------------------------------------
# Themes
# ----------------------------------------------------------------------------
THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0e1320", "surface": "#161c2c", "surface_off": "#121827",
        "border": "#252e46", "text": "#e8ecf6", "muted": "#8a94b0",
        "accent": "#5b8cff", "ok": "#34d399", "warn": "#fbbf24",
        "danger": "#f87171", "input": "#1c2438", "hover": "#243049",
        "toggle_off": "#3a4563", "console": "#0a0e18",
    },
    "light": {
        "bg": "#f2f5fb", "surface": "#ffffff", "surface_off": "#f7f8fc",
        "border": "#dde3ef", "text": "#1a2136", "muted": "#68728b",
        "accent": "#2f6bff", "ok": "#0f9d6b", "warn": "#b7791f",
        "danger": "#d64545", "input": "#edf0f8", "hover": "#e3e9f6",
        "toggle_off": "#b9c2d6", "console": "#f7f9fd",
    },
}
ACCENTS = ["#5b8cff", "#8b5cf6", "#22d3ee", "#34d399", "#f59e0b", "#f472b6"]
THEME: dict[str, str] = dict(THEMES["light"])

QSS = Template(
    """
QWidget { color: $text; font-size: 13px; }
QMainWindow, QWidget#Root { background: $bg; }
QDialog { background: $surface; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QLabel { background: transparent; }
QLabel#Title { font-size: 22px; font-weight: 800; }
QLabel#Muted { color: $muted; }
QLabel#Link { color: $accent; font-weight: 600; }
QLabel#CardTitle { font-size: 15px; font-weight: 700; }
QLabel#SectionTitle { font-size: 15px; font-weight: 800; }
QLabel#FieldKey { color: $muted; font-size: 11px; }
QLabel#FieldVal { font-size: 13px; font-weight: 600; }
QLabel#IpValue { font-size: 19px; font-weight: 800; }
QLabel#TileValue { font-size: 22px; font-weight: 800; }
QLabel#Banner {
    background: rgba(248,113,113,0.14); color: $danger;
    border: 1px solid $danger; border-radius: 10px; padding: 8px 12px;
}
QFrame#Sidebar { background: $surface; border: none; }
QFrame#NavPill { background: $accent_soft; border: 1px solid $accent_line; border-radius: 11px; }
QFrame#Footer { background: $surface; border: none; }
QFrame#Card, QFrame#IpBar, QFrame#Panel, QFrame#Tile {
    background: $surface; border: 1px solid $border; border-radius: 14px;
}
QFrame#Card:hover, QFrame#Panel:hover { border-color: $accent_line; }
QFrame#Card[off="true"] { background: $surface_off; }
QFrame#Tile { border-radius: 12px; }
QFrame#Tile:hover { border-color: $accent_line; }
QPushButton {
    background: $input; border: 1px solid $border; border-radius: 9px;
    padding: 7px 14px; font-weight: 600;
}
QPushButton:hover { background: $hover; border-color: $accent_line; }
QPushButton:pressed { background: $accent_soft; }
QPushButton:disabled { color: $muted; }
QPushButton::menu-indicator { width: 0; }
QPushButton#Primary { background: $accent; border-color: $accent; color: white; }
QPushButton#Primary:hover { background: $accent; border-color: $text; }
QPushButton#Primary:disabled { background: $input; border-color: $border; color: $muted; }
QPushButton#Danger { background: rgba(248,113,113,0.16); border-color: $danger; color: $danger; }
QPushButton#Ghost { padding: 7px 10px; }
QPushButton#IconBtn { background: transparent; border: none; padding: 0; font-size: 14px; border-radius: 8px; }
QPushButton#IconBtn:hover { background: $hover; }
QLineEdit, QSpinBox, QComboBox {
    background: $input; border: 1px solid $border; border-radius: 9px;
    padding: 7px 12px; selection-background-color: $accent; min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit#NameEdit { font-size: 15px; font-weight: 700; padding: 4px 10px; border: 1px solid $accent; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $border; selection-background-color: $hover;
    selection-color: $text; outline: 0; padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }
QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 18px; height: 18px; border: 1px solid $border; background: $input;
}
QCheckBox::indicator { border-radius: 5px; }
QRadioButton::indicator { border-radius: 10px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: $accent; border-color: $accent; }
QMenu { background: $surface; border: 1px solid $border; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 20px; border-radius: 6px; }
QMenu::item:selected { background: $hover; }
QMenu::item:disabled { color: $muted; }
QMenu::separator { height: 1px; background: $border; margin: 5px 8px; }
QPlainTextEdit#Console {
    background: $console; border: 1px solid $border; border-radius: 10px; padding: 8px;
    font-family: "Cascadia Mono", Consolas, Menlo, "DejaVu Sans Mono", "Liberation Mono", monospace; font-size: 12px;
    selection-background-color: $accent;
}
QTableWidget {
    background: transparent; border: 1px solid $border; border-radius: 10px;
    gridline-color: transparent; alternate-background-color: $surface_off;
}
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected { background: $hover; color: $text; }
QHeaderView::section { background: $input; color: $muted; border: none; padding: 7px 10px; font-weight: 700; }
QTableCornerButton::section { background: $input; border: none; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: $muted; padding: 8px 11px; margin: 0 1px; border-radius: 9px; font-weight: 700; }
QTabBar::tab:selected { background: $accent_soft; color: $text; }
QTabBar::tab:hover:!selected { background: $hover; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMessageBox { background: $surface; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 4px; }
"""
)


def rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def fmt_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_rate(n: float) -> str:
    return f"{fmt_bytes(n)}/s"


def natural_key(text: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text.lower())]


def open_url(url: str) -> None:
    if url:
        QDesktopServices.openUrl(QUrl(url))


# ----------------------------------------------------------------------------
# Icon (drawn in code — no external assets are needed)
# ----------------------------------------------------------------------------
def make_icon(dot: str | None = None) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = float(size)
        grad = QLinearGradient(0, 0, s, s)
        grad.setColorAt(0, QColor("#5b8cff"))
        grad.setColorAt(1, QColor("#7c4dff"))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)
        pen = QPen(QColor("white"), max(1.0, s * 0.06))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        top, bl, br = QPointF(s * .5, s * .27), QPointF(s * .27, s * .70), QPointF(s * .73, s * .70)
        p.drawLine(top, bl)
        p.drawLine(top, br)
        p.drawLine(bl, br)
        p.setBrush(QColor("white"))
        r = s * 0.11
        for pt in (top, bl, br):
            p.drawEllipse(pt, r, r)
        if dot:
            p.setPen(QPen(QColor("#0e1320"), max(1.0, s * 0.04)))
            p.setBrush(QColor(dot))
            p.drawEllipse(QPointF(s * .80, s * .80), s * .17, s * .17)
        p.end()
        icon.addPixmap(pm)
    return icon


# ----------------------------------------------------------------------------
# System layer (PowerShell / sockets)
# ----------------------------------------------------------------------------
_PS_PREFIX = (
    "$ProgressPreference='SilentlyContinue';"
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;\n"
)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_FETCH_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$adapters = @(Get-NetAdapter)
$ips  = @(Get-NetIPAddress)
$cfgs = @(Get-NetIPConfiguration -All)
$ifs  = @(Get-NetIPInterface -AddressFamily IPv4)
$st   = @(Get-NetAdapterStatistics)

$result = @(foreach ($a in $adapters) {
    $idx = [int]$a.ifIndex
    $v4 = @($ips | Where-Object { $_.InterfaceIndex -eq $idx -and $_.AddressFamily -eq 'IPv4' } |
           ForEach-Object { "$($_.IPAddress)/$($_.PrefixLength)" })
    $v6 = @($ips | Where-Object { $_.InterfaceIndex -eq $idx -and $_.AddressFamily -eq 'IPv6' -and $_.IPAddress -notlike 'fe80*' } |
           ForEach-Object { "$($_.IPAddress)" })
    $c = $cfgs | Where-Object { $_.InterfaceIndex -eq $idx } | Select-Object -First 1
    $gw  = @($c.IPv4DefaultGateway | ForEach-Object { $_.NextHop } | Where-Object { $_ })
    $dns = @($c.DNSServer | ForEach-Object { $_.ServerAddresses } | Where-Object { $_ -and $_ -notmatch ':' })
    $m = $ifs | Where-Object { $_.InterfaceIndex -eq $idx } | Select-Object -First 1
    $s = $st  | Where-Object { $_.Name -eq $a.Name } | Select-Object -First 1
    [pscustomobject]@{
        Name        = [string]$a.Name
        Description = [string]$a.InterfaceDescription
        Index       = $idx
        Status      = [string]$a.Status
        Mac         = [string]$a.MacAddress
        Speed       = [string]$a.LinkSpeed
        Media       = [string]$a.PhysicalMediaType
        PnP         = [string]$a.PnPDeviceID
        Virtual     = [bool]$a.Virtual
        Hardware    = [bool]$a.HardwareInterface
        Metric      = [string]$m.InterfaceMetric
        AutoMetric  = [string]$m.AutomaticMetric
        Dhcp        = [string]$m.Dhcp
        Rx          = [int64]$s.ReceivedBytes
        Tx          = [int64]$s.SentBytes
        IPv4        = $v4
        IPv6        = $v6
        Gateway     = $gw
        DNS         = $dns
    }
})

# Adapters disabled before a reboot are no longer returned by Get-NetAdapter, but they still exist
# as PnP devices (problem code 22 = disabled). List them from there so they stay manageable.
$known = @{}
foreach ($a in $adapters) {
    if ([string]$a.Status -ne 'Not Present' -and $a.PnPDeviceID) { $known[([string]$a.PnPDeviceID).ToUpper()] = 1 }
}
$extra = @(foreach ($d in @(Get-PnpDevice -Class Net -PresentOnly)) {
    if ([int]$d.ConfigManagerErrorCode -ne 22) { continue }
    $iid = [string]$d.InstanceId
    if ($known.ContainsKey($iid.ToUpper())) { continue }
    $conn = ''
    try {
        $drv  = [string](Get-PnpDeviceProperty -InstanceId $iid -KeyName 'DEVPKEY_Device_Driver' -ErrorAction Stop).Data
        $guid = [string](Get-ItemProperty -Path ('HKLM:\SYSTEM\CurrentControlSet\Control\Class\' + $drv) -ErrorAction Stop).NetCfgInstanceId
        if ($guid) {
            $conn = [string](Get-ItemProperty -Path ('HKLM:\SYSTEM\CurrentControlSet\Control\Network\{4d36e972-e325-11ce-bfc1-08002be10318}\' + $guid + '\Connection') -ErrorAction Stop).Name
        }
    } catch { }
    $fn = [string]$d.FriendlyName
    if (-not $conn) { $conn = $fn }
    [pscustomobject]@{
        Name = $conn; Description = $fn; Index = 0; Status = 'Disabled'; Mac = ''; Speed = ''; Media = '';
        PnP = $iid; Virtual = $false; Hardware = $false; Metric = ''; AutoMetric = ''; Dhcp = '';
        Rx = 0; Tx = 0; IPv4 = @(); IPv6 = @(); Gateway = @(); DNS = @()
    }
})
$result = @($result) + @($extra)
ConvertTo-Json -InputObject @($result) -Depth 4 -Compress
"""

_CHANGE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$en  = @(($env:NA_ENABLE  -split ',') | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ })
$dis = @(($env:NA_DISABLE -split ',') | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ })
$errs = @()
$pnp = @(($env:NA_ENABLE_PNP -split '\|') | Where-Object { $_ })
foreach ($id in $pnp) {
    try { Enable-PnpDevice -InstanceId $id -Confirm:$false -ErrorAction Stop }
    catch { $errs += "[$id] $($_.Exception.Message)" }
}
foreach ($i in $en) {
    try {
        $a = Get-NetAdapter -InterfaceIndex $i -ErrorAction Stop
        if ($a.Status -eq 'Disabled') { Enable-NetAdapter -InputObject $a -Confirm:$false -ErrorAction Stop }
    } catch { $errs += "[$i] $($_.Exception.Message)" }
}
foreach ($i in $dis) {
    try {
        $a = Get-NetAdapter -InterfaceIndex $i -ErrorAction Stop
        if ($a.Status -ne 'Disabled') { Disable-NetAdapter -InputObject $a -Confirm:$false -ErrorAction Stop }
    } catch { $errs += "[$i] $($_.Exception.Message)" }
}
if ($errs.Count -gt 0) { Write-Output ($errs -join "`n"); exit 1 }
"""

_DNS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
    $i = [int]$env:NA_INDEX
    if ($env:NA_DNS -eq 'auto') { Set-DnsClientServerAddress -InterfaceIndex $i -ResetServerAddresses }
    else { Set-DnsClientServerAddress -InterfaceIndex $i -ServerAddresses ($env:NA_DNS -split ',') }
    Clear-DnsClientCache
} catch { Write-Output $_.Exception.Message; exit 1 }
"""

_RENEW_SCRIPT = r"""
$ErrorActionPreference = 'Continue'
$out = & ipconfig /renew "$env:NA_NAME" 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { Write-Output $out; exit 1 }
"""

_FLUSH_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try { Clear-DnsClientCache } catch { Write-Output $_.Exception.Message; exit 1 }
"""

_RENAME_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
    Get-NetAdapter -InterfaceIndex ([int]$env:NA_INDEX) | Rename-NetAdapter -NewName $env:NA_NEW
} catch { Write-Output $_.Exception.Message; exit 1 }
"""

_METRIC_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
    $i = [int]$env:NA_INDEX
    if ($env:NA_METRIC -eq 'auto') {
        Set-NetIPInterface -InterfaceIndex $i -AddressFamily IPv4 -AutomaticMetric Enabled
        Set-NetIPInterface -InterfaceIndex $i -AddressFamily IPv6 -AutomaticMetric Enabled -ErrorAction SilentlyContinue
    } else {
        $m = [int]$env:NA_METRIC
        Set-NetIPInterface -InterfaceIndex $i -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric $m
        Set-NetIPInterface -InterfaceIndex $i -AddressFamily IPv6 -AutomaticMetric Disabled -InterfaceMetric $m -ErrorAction SilentlyContinue
    }
} catch { Write-Output $_.Exception.Message; exit 1 }
"""

_STATIC_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
    $i = [int]$env:NA_INDEX
    Set-NetIPInterface -InterfaceIndex $i -Dhcp Disabled
    Get-NetRoute -InterfaceIndex $i -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
    Get-NetIPAddress -InterfaceIndex $i -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
    if ($env:NA_GW) {
        New-NetIPAddress -InterfaceIndex $i -IPAddress $env:NA_IP -PrefixLength ([int]$env:NA_PREFIX) -DefaultGateway $env:NA_GW | Out-Null
    } else {
        New-NetIPAddress -InterfaceIndex $i -IPAddress $env:NA_IP -PrefixLength ([int]$env:NA_PREFIX) | Out-Null
    }
    if ($env:NA_DNS) { Set-DnsClientServerAddress -InterfaceIndex $i -ServerAddresses ($env:NA_DNS -split ',') }
    Clear-DnsClientCache
} catch { Write-Output $_.Exception.Message; exit 1 }
"""

_DHCP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
    $i = [int]$env:NA_INDEX
    Set-NetIPInterface -InterfaceIndex $i -Dhcp Enabled
    Get-NetRoute -InterfaceIndex $i -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
    Set-DnsClientServerAddress -InterfaceIndex $i -ResetServerAddresses
    Clear-DnsClientCache
} catch { Write-Output $_.Exception.Message; exit 1 }
"""

_CONNECTIONS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$names = @{}
Get-Process | ForEach-Object { $names[[int]$_.Id] = $_.ProcessName }
$want = $env:NA_STATES -split ','
$rows = @(Get-NetTCPConnection | Where-Object { $want -contains [string]$_.State } | ForEach-Object {
    [pscustomobject]@{
        P = [string]$names[[int]$_.OwningProcess]
        Pid = [int]$_.OwningProcess
        L = "$($_.LocalAddress):$($_.LocalPort)"
        R = "$($_.RemoteAddress):$($_.RemotePort)"
        S = [string]$_.State
    }
})
ConvertTo-Json -InputObject @($rows) -Compress
"""

_STATS_LOOP = r"""
$ErrorActionPreference = 'SilentlyContinue'
while ($true) {
    $s = @(Get-NetAdapterStatistics | ForEach-Object {
        [pscustomobject]@{ N = [string]$_.Name; R = [int64]$_.ReceivedBytes; S = [int64]$_.SentBytes } })
    ConvertTo-Json -InputObject @($s) -Compress
    Start-Sleep -Milliseconds 800
}
"""

_STARTUP_ON = r"""
$ErrorActionPreference = 'Stop'
try {
    $a = New-ScheduledTaskAction -Execute $env:NA_EXE -Argument $env:NA_ARGS
    $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $env:NA_TASK -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null
} catch { Write-Output $_.Exception.Message; exit 1 }
"""
_STARTUP_OFF = r"""
$ErrorActionPreference = 'Stop'
try { Unregister-ScheduledTask -TaskName $env:NA_TASK -Confirm:$false }
catch { Write-Output $_.Exception.Message; exit 1 }
"""
_STARTUP_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
if (Get-ScheduledTask -TaskName $env:NA_TASK) { Write-Output 'yes' } else { Write-Output 'no' }
"""


def _encode(script: str) -> str:
    return base64.b64encode((_PS_PREFIX + script).encode("utf-16-le")).decode()


def _ps_args(script: str) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-OutputFormat", "Text", "-EncodedCommand", _encode(script)]


def run_powershell(script: str, env_extra: dict[str, str] | None = None,
                   timeout: int = 90) -> tuple[int, str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(_ps_args(script), capture_output=True, timeout=timeout, env=env,
                          creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)
    out = proc.stdout.decode("utf-8-sig", errors="replace").strip()
    if not out and proc.stderr:
        out = proc.stderr.decode("utf-8", errors="replace").strip()
    return proc.returncode, out


def oem_encoding() -> str:
    try:
        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except Exception:
        return "utf-8"


_VIRTUAL_NAME_RE = re.compile(
    r"virtual|vpn|\btap\b|tap-|wintun|loopback|miniport|vmware|virtualbox|hyper-v|vethernet|wireguard|tunnel|pseudo|teredo|isatap",
    re.I)


def classify_disabled(d: dict) -> tuple[bool, bool]:
    """Return (hardware, virtual) for a *disabled* Windows adapter.

    Windows often reports HardwareInterface = False for disabled adapters (their driver is not loaded),
    which would make a real network card look virtual and hide it from the list. The PnP bus prefix
    is reliable: PCI / USB / ACPI / BTH ... = physical hardware, ROOT / SWD = software device."""
    hw, virt = bool(d.get("Hardware", True)), bool(d.get("Virtual"))
    pnp = str(d.get("PnP") or "").upper()
    if re.match(r"^(ROOT|SWD)\\", pnp):
        return False, True
    if re.match(r"^(PCI|USB|ACPI|BTH|BTHENUM|SD|PCMCIA)\\", pnp) and not virt:
        return True, False
    if _VIRTUAL_NAME_RE.search(str(d.get("Description") or "")):
        return False, True
    return hw, virt


@dataclass(slots=True)
class Adapter:
    name: str
    description: str
    index: int
    status: str
    device: str = ""
    mac: str = ""
    speed: str = ""
    media: str = ""
    pnp: str = ""
    virtual: bool = False
    hardware: bool = True
    metric: str = ""
    auto_metric: str = ""
    dhcp: str = ""
    rx: int = 0
    tx: int = 0
    rx_rate: float = 0.0
    tx_rate: float = 0.0
    ipv4: list[str] = field(default_factory=list)
    ipv6: list[str] = field(default_factory=list)
    gateway: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.status.lower() != "disabled"

    @property
    def is_up(self) -> bool:
        return self.status.lower() == "up"

    @property
    def primary_ip(self) -> str:
        for x in self.ipv4:
            ip = x.split("/")[0]
            if not ip.startswith("169.254."):
                return ip
        return ""

    @property
    def prefix(self) -> int:
        for x in self.ipv4:
            if "/" in x and not x.startswith("169.254."):
                try:
                    return int(x.split("/")[1])
                except ValueError:
                    pass
        return 24

    @staticmethod
    def _as_list(v) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v else []
        return [str(x) for x in v if x]

    @classmethod
    def from_dict(cls, d: dict) -> "Adapter":
        hardware, virtual = bool(d.get("Hardware", True)), bool(d.get("Virtual"))
        if str(d.get("Status", "")).lower() == "disabled":
            hardware, virtual = classify_disabled(d)
        return cls(
            name=d.get("Name", ""), device=d.get("Device") or d.get("Name", ""), description=d.get("Description", ""),
            index=int(d.get("Index", 0)), status=d.get("Status", ""),
            mac=d.get("Mac", ""), speed=d.get("Speed", ""), media=d.get("Media", ""), pnp=d.get("PnP") or "",
            virtual=virtual, hardware=hardware,
            metric=d.get("Metric", ""), auto_metric=d.get("AutoMetric", ""), dhcp=d.get("Dhcp", ""),
            rx=int(d.get("Rx") or 0), tx=int(d.get("Tx") or 0),
            ipv4=cls._as_list(d.get("IPv4")), ipv6=cls._as_list(d.get("IPv6")),
            gateway=cls._as_list(d.get("Gateway")), dns=cls._as_list(d.get("DNS")),
        )

    @property
    def icon(self) -> str:
        blob = f"{self.name} {self.description} {self.media}".lower()
        if "bluetooth" in blob:
            return "🔷"
        if any(k in blob for k in ("wi-fi", "wifi", "wireless", "wlan", "802.11")):
            return "📶"
        if not self.hardware or self.virtual:
            return "🧩"
        return "🔌"


PNP_INDEX_BASE = 1_000_000   # pseudo interface index for adapters Windows no longer lists (disabled PnP devices)


def win_fetch_adapters() -> list[Adapter]:
    rc, out = run_powershell(_FETCH_SCRIPT)
    if rc != 0 and not out.startswith(("[", "{")):
        raise RuntimeError(out or f"PowerShell exit code {rc}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid PowerShell output: {e}") from e
    if isinstance(data, dict):
        data = [data]
    adapters = [Adapter.from_dict(d) for d in data]
    for a in adapters:
        a.device = a.name
        if a.index <= 0 and a.pnp:      # disabled adapter known only from PnP: give it a stable pseudo index
            a.index = PNP_INDEX_BASE + zlib.crc32(a.pnp.upper().encode()) % 900_000
    return [a for a in adapters if a.status.lower() != "not present"]


def win_change_adapters(enable: list[int], disable: list[int]) -> tuple[int, str]:
    # Enable first, then disable, so connectivity is never lost in between.
    pnp = [_REG[i].pnp for i in enable if i >= PNP_INDEX_BASE and i in _REG and _REG[i].pnp]
    enable = [i for i in enable if i < PNP_INDEX_BASE]
    disable = [i for i in disable if i < PNP_INDEX_BASE]
    return run_powershell(_CHANGE_SCRIPT, env_extra={
        "NA_ENABLE_PNP": "|".join(pnp),
        "NA_ENABLE": ",".join(str(int(i)) for i in enable),
        "NA_DISABLE": ",".join(str(int(i)) for i in disable)})


def win_set_dns(index: int, servers: str) -> tuple[int, str]:
    return run_powershell(_DNS_SCRIPT, {"NA_INDEX": str(int(index)), "NA_DNS": servers})


def win_renew_dhcp(name: str) -> tuple[int, str]:
    return run_powershell(_RENEW_SCRIPT, {"NA_NAME": name}, timeout=120)


def win_flush_dns() -> tuple[int, str]:
    return run_powershell(_FLUSH_SCRIPT)


def win_rename_adapter(index: int, new_name: str) -> tuple[int, str]:
    return run_powershell(_RENAME_SCRIPT, {"NA_INDEX": str(int(index)), "NA_NEW": new_name})


def win_set_metric(index: int, metric: str) -> tuple[int, str]:
    return run_powershell(_METRIC_SCRIPT, {"NA_INDEX": str(int(index)), "NA_METRIC": metric})


def win_set_static_ip(index: int, ip: str, prefix: int, gw: str, dns: str) -> tuple[int, str]:
    return run_powershell(_STATIC_SCRIPT, {"NA_INDEX": str(int(index)), "NA_IP": ip,
                                           "NA_PREFIX": str(int(prefix)), "NA_GW": gw, "NA_DNS": dns})


def win_set_dhcp(index: int) -> tuple[int, str]:
    return run_powershell(_DHCP_SCRIPT, {"NA_INDEX": str(int(index))})


def win_fetch_connections(states: str) -> list[dict]:
    rc, out = run_powershell(_CONNECTIONS_SCRIPT, {"NA_STATES": states})
    if not out.startswith(("[", "{")):
        raise RuntimeError(out or f"PowerShell exit code {rc}")
    data = json.loads(out)
    return [data] if isinstance(data, dict) else data


def startup_command() -> tuple[str, str]:
    """(executable, arguments) used by the Windows autostart entries."""
    if FROZEN:
        return sys.executable, "--minimized"
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return exe, f'"{os.path.abspath(sys.argv[0])}" --minimized'


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _win_run_exists() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_ID)
        return True
    except (OSError, ImportError):
        return False


def _win_run_set(enable: bool, cmdline: str = "") -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_ALL_ACCESS) as k:
        if enable:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, cmdline)
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except FileNotFoundError:
                pass


def _win_task_exists() -> bool:
    _, out = run_powershell(_STARTUP_QUERY, {"NA_TASK": STARTUP_TASK})
    return out.strip().lower() == "yes"


def win_startup_enabled() -> bool:
    return _win_run_exists() or _win_task_exists()


def win_set_startup(enable: bool) -> tuple[int, str]:
    """Administrator: scheduled task (silent, elevated). Standard user: HKCU Run key."""
    try:
        if enable:
            exe, args = startup_command()
            if is_admin():
                rc, out = run_powershell(_STARTUP_ON, {"NA_TASK": STARTUP_TASK, "NA_EXE": exe, "NA_ARGS": args})
                if rc != 0:
                    return rc, out
                _win_run_set(False)
            else:
                _win_run_set(True, f'"{exe}" {args}')
            return 0, ""
        if _win_task_exists():
            rc, out = run_powershell(_STARTUP_OFF, {"NA_TASK": STARTUP_TASK})
            if rc != 0:
                return rc, out
        _win_run_set(False)
        return 0, ""
    except (OSError, ImportError) as e:
        return 1, str(e)


def relaunch_as_admin() -> bool:
    """Restart this program elevated (UAC). Returns True if the new process started."""
    try:
        if FROZEN:
            exe = sys.executable
            params = subprocess.list2cmdline([*sys.argv[1:], "--elevated"])
        else:
            exe = sys.executable
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if exe.lower().endswith("python.exe") and os.path.exists(pyw):
                exe = pyw
            params = subprocess.list2cmdline([os.path.abspath(sys.argv[0]), *sys.argv[1:], "--elevated"])
        return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Public IP / geolocation (free, key-less services with automatic fallback)
# ----------------------------------------------------------------------------
USER_AGENT = f"NICSwitcher/{APP_VERSION}"


def _split_src(src) -> tuple[str | None, str | None]:
    """`src` is None, an IP string, or an (ip, device) tuple → (ip, device)."""
    if not src:
        return None, None
    if isinstance(src, (tuple, list)):
        return (src[0] or None), (src[1] if len(src) > 1 else None) or None
    return src, None


def bind_device(sock: socket.socket, device: str | None) -> None:
    """Force a socket out of one interface (best effort; Windows relies on the source IP)."""
    if not device:
        return
    try:
        if IS_LINUX:
            sock.setsockopt(socket.SOL_SOCKET, 25, device.encode() + b"\0")        # SO_BINDTODEVICE
        elif IS_MAC:
            sock.setsockopt(socket.IPPROTO_IP, 25, socket.if_nametoindex(device))  # IP_BOUND_IF
    except OSError:
        pass


def _connect_via(host: str, port: int, timeout: float, src) -> socket.socket:
    ip, device = _split_src(src)
    last: Exception | None = None
    for fam, kind, proto, _c, addr in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        s = socket.socket(fam, kind, proto)
        s.settimeout(timeout)
        try:
            bind_device(s, device)
            if ip:
                s.bind((ip, 0))
            s.connect(addr)
            return s
        except OSError as e:
            last = e
            s.close()
    raise last or OSError("connection failed")


def _make_https(host: str, src, timeout: float) -> http.client.HTTPSConnection:
    conn = http.client.HTTPSConnection(host, timeout=timeout, context=ssl.create_default_context())
    ip, device = _split_src(src)
    if ip or device:
        conn._create_connection = lambda address, tmo=None, source_address=None: _connect_via(
            address[0], address[1], tmo or timeout, (ip, device))
    return conn


def _https_get(host: str, path: str, src_ip=None, timeout: float = 5.0) -> str:
    conn = _make_https(host, src_ip, timeout)
    try:
        conn.request("GET", path, headers={"User-Agent": USER_AGENT,
                                           "Accept": "application/json,text/plain,*/*"})
        resp = conn.getresponse()
        body = resp.read(65536).decode("utf-8", "replace")
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        return body
    finally:
        conn.close()


def _blank(**kw) -> dict:
    base = {"ip": "", "country": "", "cc": "", "city": "", "region": "", "isp": "", "asn": "", "tz": ""}
    base.update(kw)
    return base


def _parse_ipwho(body: str) -> dict:
    d = json.loads(body)
    if d.get("success") is False:
        raise RuntimeError(d.get("message", "ipwho.is error"))
    c = d.get("connection") or {}
    return _blank(ip=d["ip"], country=d.get("country", ""), cc=d.get("country_code", ""),
                  city=d.get("city", ""), region=d.get("region", ""),
                  isp=c.get("isp") or c.get("org", ""), asn=str(c.get("asn", "") or ""),
                  tz=(d.get("timezone") or {}).get("id", ""))


def _parse_ipapi(body: str) -> dict:
    d = json.loads(body)
    if d.get("error"):
        raise RuntimeError(str(d.get("reason", "ipapi.co error")))
    return _blank(ip=d["ip"], country=d.get("country_name", ""), cc=d.get("country_code", ""),
                  city=d.get("city", ""), region=d.get("region", ""), isp=d.get("org", ""),
                  asn=str(d.get("asn", "") or ""), tz=d.get("timezone", ""))


def _parse_ipinfo(body: str) -> dict:
    d = json.loads(body)
    org = d.get("org", "") or ""
    asn, _, name = org.partition(" ")
    return _blank(ip=d["ip"], cc=d.get("country", ""), city=d.get("city", ""), region=d.get("region", ""),
                  isp=name or org, asn=asn if asn.upper().startswith("AS") else "", tz=d.get("timezone", ""))


def _parse_cloudflare(body: str) -> dict:
    kv = dict(line.split("=", 1) for line in body.splitlines() if "=" in line)
    return _blank(ip=kv["ip"], cc=kv.get("loc", ""))


def _parse_ipify(body: str) -> dict:
    return _blank(ip=json.loads(body)["ip"])


# (name, host, path(query), parser, supports lookup of arbitrary IPs)
PUBLIC_IP_PROVIDERS = [
    ("ipwho.is", "ipwho.is", lambda q: f"/{q}", _parse_ipwho, True),
    ("ipapi.co", "ipapi.co", lambda q: f"/{q}/json/" if q else "/json/", _parse_ipapi, True),
    ("ipinfo.io", "ipinfo.io", lambda q: f"/{q}/json" if q else "/json", _parse_ipinfo, True),
    ("Cloudflare", "www.cloudflare.com", lambda q: "/cdn-cgi/trace", _parse_cloudflare, False),
    ("ipify", "api.ipify.org", lambda q: "/?format=json", _parse_ipify, False),
]


def fetch_public_ip(src_ip: str | None = None, query: str = "") -> dict:
    """Public IP + geolocation. With `src_ip` the request leaves through that adapter."""
    errors = []
    for name, host, path, parser, lookup in PUBLIC_IP_PROVIDERS:
        if query and not lookup:
            continue
        try:
            info = parser(_https_get(host, path(query), src_ip))
            info["provider"] = name
            return info
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    raise RuntimeError("No IP service responded.\n" + "\n".join(errors))


def tcp_latency(src_ip, tries: int = 3) -> float | None:
    for host in ("1.1.1.1", "8.8.8.8", "9.9.9.9"):
        samples: list[float] = []
        for _ in range(tries):
            t0 = time.perf_counter()
            try:
                s = _connect_via(host, 443, 2.5, src_ip)
                samples.append((time.perf_counter() - t0) * 1000)
                s.close()
            except OSError:
                break
        if samples:
            return statistics.median(samples)
    return None


def probe_adapter(src_ip) -> dict:
    res: dict = {"src": _split_src(src_ip)[0], "latency": None, "pub": None, "error": ""}
    res["latency"] = tcp_latency(src_ip)
    if res["latency"] is None:
        res["error"] = "No internet"
        return res
    try:
        res["pub"] = fetch_public_ip(src_ip)
    except Exception as e:  # noqa: BLE001
        res["error"] = str(e)
    return res


def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


def check_update() -> dict:
    if not GITHUB_REPO:
        raise RuntimeError("GITHUB_REPO is not configured.")
    d = json.loads(_https_get("api.github.com", f"/repos/{GITHUB_REPO}/releases/latest", timeout=8))
    tag = str(d.get("tag_name", "")).lstrip("vV")
    return {"latest": tag, "url": d.get("html_url", GITHUB_URL), "newer": _vtuple(tag) > _vtuple(APP_VERSION)}


# ----------------------------------------------------------------------------
# Threads
# ----------------------------------------------------------------------------
class WorkerSignals(QObject):
    done = pyqtSignal(object, object, bool, object)  # worker, callback, ok, payload


class Worker(QRunnable):
    """Short one-shot job executed in the global thread pool."""

    def __init__(self, fn, callback, *args):
        super().__init__()
        self.fn, self.callback, self.args = fn, callback, args
        self.signals = WorkerSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            self.signals.done.emit(self, self.callback, True, self.fn(*self.args))
        except Exception as e:  # noqa: BLE001
            self.signals.done.emit(self, self.callback, False, str(e))


class Task(QThread):
    """Long-running / streaming job. The job receives the task: t.emit(), t.stopped(), t.proc."""
    message = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self._job = job
        self._stop = False
        self.proc: subprocess.Popen | None = None

    def emit(self, payload) -> None:
        self.message.emit(payload)

    def stopped(self) -> bool:
        return self._stop

    def stop(self) -> None:
        self._stop = True
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def run(self) -> None:
        try:
            self._job(self)
        except Exception as e:  # noqa: BLE001
            if not self._stop:
                self.failed.emit(str(e))


def _stream_pty(t: Task, args: list[str]) -> int:
    """POSIX: run on a pseudo-terminal so tools like ping flush every line immediately."""
    import pty
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave, close_fds=True)
    finally:
        os.close(slave)
    t.proc = proc
    buf = b""
    try:
        while not t.stopped():
            try:
                chunk = os.read(master, 4096)
            except OSError:      # EIO: the child closed the terminal
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                t.emit(line.decode("utf-8", "replace").rstrip("\r"))
        if buf.strip():
            t.emit(buf.decode("utf-8", "replace").rstrip("\r\n"))
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        os.close(master)
    return proc.returncode


def stream_command(t: Task, args: list[str]) -> int:
    """Run a console program and emit every output line."""
    if not IS_WINDOWS:
        return _stream_pty(t, args)
    return _stream_pipe(t, args)


def _stream_pipe(t: Task, args: list[str]) -> int:
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    t.proc = proc
    enc = oem_encoding()
    try:
        for raw in iter(proc.stdout.readline, b""):
            if t.stopped():
                break
            t.emit(raw.decode(enc, errors="replace").rstrip("\r\n"))
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    return proc.returncode


def win_stats_job(t: Task) -> None:
    """Once-a-second per-adapter byte counters from one long-lived PowerShell process."""
    proc = subprocess.Popen(_ps_args(_STATS_LOOP), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    t.proc = proc
    try:
        for raw in iter(proc.stdout.readline, b""):
            if t.stopped():
                break
            line = raw.decode("utf-8-sig", errors="replace").strip()
            if not line.startswith(("[", "{")):
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            t.emit(("stats", [data] if isinstance(data, dict) else data, time.monotonic()))
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


# ----------------------------------------------------------------------------
# Cross-platform backends (Windows / Linux / macOS)
# ----------------------------------------------------------------------------
_REG: dict[int, Adapter] = {}      # last known adapters by index (used by backends)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _euid0() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def sh_capture(argv: list[str], timeout: int = 20) -> str:
    """stdout of a command, or '' on any failure."""
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.decode("utf-8", "replace")


def sh_run(argv: list[str], timeout: int = 90) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=_NO_WINDOW)
    except FileNotFoundError:
        return 127, f"{argv[0]}: command not found"
    except subprocess.TimeoutExpired:
        return 124, "The command timed out."
    except OSError as e:
        return 126, str(e)
    text = (p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")).strip()
    return p.returncode, text


def priv_wrap(argv: list[str]) -> list[str]:
    """Prefix a command so that it runs with administrator rights (no-op on Windows / root)."""
    if IS_WINDOWS or _euid0():
        return list(argv)
    if IS_MAC:
        cmd = shlex.join(argv).replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", f'do shell script "{cmd}" with administrator privileges']
    if have("pkexec"):
        return ["pkexec", *argv]
    if have("sudo"):
        return ["sudo", "-n", *argv]
    raise RuntimeError("Administrator rights are needed. Install polkit (pkexec) or run the app as root.")


def run_root(script: str, timeout: int = 180) -> tuple[int, str]:
    """Run a /bin/sh script as administrator (one password prompt for the whole script)."""
    try:
        argv = priv_wrap(["sh", "-c", script])
    except RuntimeError as e:
        return 1, str(e)
    return sh_run(argv, timeout)


def is_admin() -> bool:
    if IS_WINDOWS:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return _euid0()


def can_change_system() -> bool:
    """True if the app is elevated or can ask for elevation when needed."""
    if IS_WINDOWS:
        return is_admin()
    return _euid0() or IS_MAC or have("pkexec") or have("sudo")


def config_dir() -> str:
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_ID)
    if IS_MAC:
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_ID)
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "nic-switcher")


def ensure_icon_file() -> str:
    """Write the app icon as PNG (used by the Linux autostart entry). Call from the GUI thread."""
    try:
        os.makedirs(config_dir(), exist_ok=True)
        path = os.path.join(config_dir(), "nic-switcher.png")
        make_icon().pixmap(256, 256).save(path, "PNG")
        return path
    except Exception:
        return ""


def startup_argv() -> list[str]:
    """Command line used to start this program at login (minimized to the tray)."""
    if FROZEN:
        return [sys.executable, "--minimized"]
    exe = sys.executable
    if IS_WINDOWS:
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        exe = pyw if os.path.exists(pyw) else exe
    return [exe, os.path.abspath(sys.argv[0]), "--minimized"]


def poll_stats_job(t: "Task", reader) -> None:
    """Once-a-second byte counters for platforms where reading them is cheap."""
    while not t.stopped():
        try:
            data = reader()
        except Exception:  # noqa: BLE001
            data = []
        if data:
            t.emit(("stats", data, time.monotonic()))
        for _ in range(9):
            if t.stopped():
                return
            time.sleep(0.1)


def _need(argv: list[str]) -> list[str]:
    if not have(argv[0]):
        raise RuntimeError(f"Command not found: {argv[0]}")
    return argv


# ---- parsers (pure functions, unit-testable) --------------------------------
def fmt_mbps(n: int) -> str:
    if n <= 0:
        return ""
    return f"{n / 1000:g} Gbps" if n >= 1000 else f"{n} Mbps"


def prefix_from_netmask(mask: str) -> int:
    try:
        if mask.lower().startswith("0x"):
            return bin(int(mask, 16)).count("1")
        return sum(bin(int(x)).count("1") for x in mask.split("."))
    except ValueError:
        return 24


def netmask_from_prefix(prefix: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{int(prefix)}").netmask)


def parse_ip_json(addr_json: str, route_json: str, dns_map: dict[str, list[str]],
                  reader=None) -> list[Adapter]:
    """Build adapters from `ip -j addr` and `ip -j route` (Linux). `reader(dev, field)` reads /sys."""
    links = json.loads(addr_json or "[]")
    routes = json.loads(route_json or "[]")
    defaults: dict[str, tuple[str, int, str]] = {}
    for r in routes:
        if r.get("dst") == "default" and r.get("dev"):
            cur = defaults.get(r["dev"])
            metric = int(r.get("metric", 0))
            if cur is None or metric < cur[1]:
                defaults[r["dev"]] = (r.get("gateway", ""), metric, r.get("protocol", ""))
    rd = reader or (lambda dev, field: "")
    out: list[Adapter] = []
    for l in links:
        dev = l.get("ifname")
        if not dev or dev == "lo":
            continue
        flags = l.get("flags", [])
        oper = str(l.get("operstate", "UNKNOWN")).lower()
        if "UP" not in flags:
            status = "Disabled"
        elif oper == "up" or (oper == "unknown" and "LOWER_UP" in flags):
            status = "Up"
        else:
            status = "Disconnected"
        v4, v6, dyn = [], [], False
        for ai in l.get("addr_info", []):
            if ai.get("family") == "inet":
                v4.append(f"{ai.get('local')}/{ai.get('prefixlen', 24)}")
                dyn = dyn or bool(ai.get("dynamic"))
            elif ai.get("family") == "inet6" and ai.get("scope") == "global":
                v6.append(ai.get("local", ""))
        gw, metric, proto = defaults.get(dev, ("", 0, ""))
        dhcp = ""
        if v4:
            dhcp = "Enabled" if (proto == "dhcp" or dyn) else "Disabled"
        try:
            speed = fmt_mbps(int(rd(dev, "speed") or 0))
        except ValueError:
            speed = ""
        virtual = rd(dev, "virtual") == "1"
        hardware = rd(dev, "hardware") == "1" and not virtual
        media = "802.11" if rd(dev, "wireless") == "1" else ("802.3" if l.get("link_type") == "ether" else "")
        desc = rd(dev, "description") or l.get("link_type", "") or dev
        rx, tx = 0, 0
        try:
            rx, tx = int(rd(dev, "rx") or 0), int(rd(dev, "tx") or 0)
        except ValueError:
            pass
        out.append(Adapter(
            name=dev, device=dev, description=desc, index=int(l.get("ifindex", 0)), status=status,
            mac=str(l.get("address", "")).upper().replace(":", "-") if l.get("address") else "",
            speed=speed, media=media, virtual=virtual, hardware=hardware,
            metric=str(metric) if metric else "", auto_metric="", dhcp=dhcp, rx=rx, tx=tx,
            ipv4=v4, ipv6=v6, gateway=[gw] if gw else [], dns=dns_map.get(dev, [])))
    return out


def parse_mac_service_order(text: str) -> list[dict]:
    """Parse `networksetup -listnetworkserviceorder` → [{service, device, port, disabled, order}]."""
    res: list[dict] = []
    cur: dict | None = None
    order = 0
    for line in text.splitlines():
        m = re.match(r"^\((\d+|\*)\)\s*(.+)$", line.strip())
        if m:
            order += 1
            cur = {"service": m.group(2).strip(), "disabled": m.group(1) == "*", "order": order,
                   "device": "", "port": ""}
            res.append(cur)
            continue
        m = re.match(r"^\(Hardware Port:\s*(.*?),\s*Device:\s*(.*?)\)$", line.strip())
        if m and cur is not None:
            cur["port"], cur["device"] = m.group(1), m.group(2)
    return [r for r in res if r["device"]]


def parse_ifconfig(text: str) -> dict:
    d = {"up": False, "active": None, "mac": "", "v4": [], "v6": [], "media": ""}
    for raw in text.splitlines():
        line = raw.strip()
        if "flags=" in line and "<" in line:
            d["up"] = "UP" in line.split("<", 1)[1].split(">", 1)[0].split(",")
        elif line.startswith("ether "):
            d["mac"] = line.split()[1].upper().replace(":", "-")
        elif line.startswith("inet "):
            p = line.split()
            mask = p[p.index("netmask") + 1] if "netmask" in p else "0xffffff00"
            d["v4"].append(f"{p[1]}/{prefix_from_netmask(mask)}")
        elif line.startswith("inet6 "):
            ip = line.split()[1].split("%")[0]
            if not ip.lower().startswith("fe80"):
                d["v6"].append(ip)
        elif line.startswith("media:"):
            d["media"] = line[6:].strip()
        elif line.startswith("status:"):
            d["active"] = line.split(":", 1)[1].strip() == "active"
    return d


def parse_scutil_dns(text: str) -> dict[str, list[str]]:
    res: dict[str, list[str]] = {}
    servers: list[str] = []
    iface = ""

    def flush() -> None:
        if iface and servers:
            cur = res.setdefault(iface, [])
            for s in servers:
                if s not in cur:
                    cur.append(s)

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("resolver #"):
            flush()
            servers, iface = [], ""
        m = re.match(r"nameserver\[\d+\]\s*:\s*(\S+)", line)
        if m and ":" not in m.group(1):
            servers.append(m.group(1))
        m = re.match(r"if_index\s*:\s*\d+\s*\((\S+)\)", line)
        if m:
            iface = m.group(1)
    flush()
    return res


def parse_mac_getinfo(text: str) -> dict:
    d = {"dhcp": "", "router": ""}
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    if first.startswith(("DHCP", "BOOTP")):
        d["dhcp"] = "Enabled"
    elif first.startswith("Manual"):
        d["dhcp"] = "Disabled"
    m = re.search(r"^Router:\s*(\S+)", text, re.M)
    if m and re.match(r"\d+\.\d+\.\d+\.\d+$", m.group(1)):
        d["router"] = m.group(1)
    return d


def parse_netstat_ib(text: str) -> list[dict]:
    out, seen = [], set()
    for line in text.splitlines():
        p = line.split()
        if len(p) < 8 or not p[2].startswith("<Link#") or p[0] in seen:
            continue
        try:
            rx, tx = int(p[-5]), int(p[-2])
        except ValueError:
            continue
        seen.add(p[0])
        out.append({"N": p[0], "R": rx, "S": tx})
    return out


def parse_ss(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        p = line.split(None, 5)
        if len(p) < 5:
            continue
        state = {"ESTAB": "Established", "LISTEN": "Listen"}.get(p[0], p[0].title())
        proc, pid = "", 0
        if len(p) > 5:
            m = re.search(r'\("([^"]+)",pid=(\d+)', p[5])
            if m:
                proc, pid = m.group(1), int(m.group(2))
        rows.append({"P": proc, "Pid": pid, "L": p[3], "R": p[4], "S": state})
    return rows


def parse_lsof_fields(text: str) -> list[dict]:
    rows: list[dict] = []
    pid, cmd = 0, ""
    cur: dict | None = None

    def flush() -> None:
        nonlocal cur
        if cur and cur.get("L"):
            rows.append(cur)
        cur = None

    for line in text.splitlines():
        if not line:
            continue
        tag, val = line[0], line[1:]
        if tag == "p":
            flush()
            pid = int(val) if val.isdigit() else 0
        elif tag == "c":
            cmd = val
        elif tag == "f":
            flush()
            cur = {"P": cmd, "Pid": pid, "L": "", "R": "", "S": ""}
        elif tag == "n" and cur is not None:
            local, _, remote = val.partition("->")
            cur["L"], cur["R"] = local, remote or "*:*"
        elif tag == "T" and cur is not None and val.startswith("ST="):
            cur["S"] = {"ESTABLISHED": "Established", "LISTEN": "Listen"}.get(val[3:], val[3:].title())
    flush()
    return rows


def _filter_connections(rows: list[dict], key: str) -> list[dict]:
    if key == "est":
        return [r for r in rows if r["S"] == "Established"]
    if key == "listen":
        return [r for r in rows if r["S"] == "Listen"]
    return rows


# ---- backends ------------------------------------------------------------------
class WindowsBackend:
    name = "Windows"
    caps = {"rename": True}

    def fetch_adapters(self): return win_fetch_adapters()
    def change(self, en, dis): return win_change_adapters(en, dis)
    def set_dns(self, i, s): return win_set_dns(i, s)
    def renew(self, i): return win_renew_dhcp(_REG[int(i)].name)
    def flush_dns(self): return win_flush_dns()
    def rename(self, i, n): return win_rename_adapter(i, n)
    def set_metric(self, i, m): return win_set_metric(i, m)
    def set_static(self, i, ip, p, gw, dns): return win_set_static_ip(i, ip, p, gw, dns)
    def set_dhcp(self, i): return win_set_dhcp(i)
    def stats_job(self, t): return win_stats_job(t)
    def startup_enabled(self): return win_startup_enabled()
    def set_startup(self, enable, icon=""): return win_set_startup(enable)

    def connections(self, key: str) -> list[dict]:
        states = {"est": "Established", "listen": "Listen",
                  "all": "Established,Listen,TimeWait,CloseWait,SynSent,SynReceived,FinWait1,FinWait2,LastAck,Closing"}
        return win_fetch_connections(states.get(key, "Established"))

    def ping_cmd(self, host, count): return ["ping", "-n", str(count), host] if count > 0 else ["ping", "-t", host]
    def trace_cmd(self, host): return ["tracert", "-d", "-h", "30", host]
    def nslookup_cmd(self, host, server): return ["nslookup", host] + ([server] if server else [])

    def quick_commands(self):
        return [
            ("ipconfig /all", ["ipconfig", "/all"]), ("route print", ["route", "print"]),
            ("arp -a", ["arp", "-a"]), ("netstat -rn", ["netstat", "-rn"]), ("getmac /v", ["getmac", "/v"]),
            ("netsh interface ip show config", ["netsh", "interface", "ip", "show", "config"]),
            ("netsh wlan show interfaces", ["netsh", "wlan", "show", "interfaces"]),
            ("netsh wlan show networks mode=bssid", ["netsh", "wlan", "show", "networks", "mode=bssid"]),
            ("netsh advfirewall show allprofiles state", ["netsh", "advfirewall", "show", "allprofiles", "state"])]

    def repair_actions(self):
        return [
            ("🧹", "Flush DNS cache", "Clears the local DNS resolver cache.", ["ipconfig", "/flushdns"], False),
            ("🔁", "Renew all IP addresses", "Requests fresh DHCP leases on every adapter.", ["ipconfig", "/renew"], False),
            ("📝", "Re-register DNS", "Refreshes DNS registrations and DHCP leases.", ["ipconfig", "/registerdns"], False),
            ("🧽", "Clear ARP cache", "Removes stale neighbour (ARP) entries.", ["netsh", "interface", "ip", "delete", "arpcache"], False),
            ("🔌", "Reset Winsock", "Resets the Windows sockets catalog (restart required).", ["netsh", "winsock", "reset"], True),
            ("♻️", "Reset TCP/IP stack", "Rewrites TCP/IP settings to defaults (restart required).", ["netsh", "int", "ip", "reset"], True)]

    def open_settings(self):
        os.startfile("ncpa.cpl")  # type: ignore[attr-defined]


class LinuxBackend:
    name = "Linux"
    caps = {"rename": False}

    # -- helpers
    @staticmethod
    def _nm_conn(dev: str) -> str:
        if not have("nmcli"):
            return ""
        out = sh_capture(["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", dev]).strip()
        return "" if out in ("", "--") else out

    @staticmethod
    def _nm(steps: list[list[str]]) -> tuple[int, str]:
        """Run nmcli steps as the user; if that is not permitted, repeat them as administrator."""
        rc, out = 0, ""
        for s in steps:
            rc, out = sh_run(["nmcli", *s], timeout=60)
            if rc != 0:
                return run_root(" && ".join(shlex.join(["nmcli", *x]) for x in steps))
        return rc, out

    @staticmethod
    def _sys(dev: str, field: str) -> str:
        base = f"/sys/class/net/{dev}"
        try:
            if field in ("speed", "address"):
                return open(f"{base}/{field}").read().strip()
            if field == "rx":
                return open(f"{base}/statistics/rx_bytes").read().strip()
            if field == "tx":
                return open(f"{base}/statistics/tx_bytes").read().strip()
        except OSError:
            return ""
        if field == "virtual":
            return "1" if os.path.exists(f"/sys/devices/virtual/net/{dev}") else "0"
        if field == "hardware":
            return "1" if os.path.exists(f"{base}/device") else "0"
        if field == "wireless":
            return "1" if os.path.exists(f"{base}/wireless") or os.path.exists(f"{base}/phy80211") else "0"
        if field == "description":
            props = sh_capture(["udevadm", "info", "--query=property", f"--path={base}"]) if have("udevadm") else ""
            kv = dict(l.split("=", 1) for l in props.splitlines() if "=" in l)
            name = " ".join(x for x in (kv.get("ID_VENDOR_FROM_DATABASE"), kv.get("ID_MODEL_FROM_DATABASE")) if x)
            return name or kv.get("ID_NET_DRIVER", "") or kv.get("ID_NET_NAME_PATH", "")
        return ""

    def _dns_map(self) -> dict[str, list[str]]:
        m: dict[str, list[str]] = {}
        if have("resolvectl"):
            for line in sh_capture(["resolvectl", "dns"]).splitlines():
                mm = re.match(r"Link\s+\d+\s+\((\S+)\):\s*(.*)", line)
                if mm:
                    m[mm.group(1)] = [x for x in mm.group(2).split() if re.match(r"^\d+\.\d+\.\d+\.\d+$", x)]
        return m

    # -- API
    def fetch_adapters(self) -> list[Adapter]:
        raw = sh_capture(["ip", "-j", "addr", "show"])
        if not raw.strip():
            raise RuntimeError("The `ip` command (iproute2) is required but could not be run.")
        adapters = parse_ip_json(raw, sh_capture(["ip", "-j", "route", "show"]), self._dns_map(), self._sys)
        # DNS fallback: /etc/resolv.conf (skip the local stub resolver)
        try:
            ns = [l.split()[1] for l in open("/etc/resolv.conf") if l.startswith("nameserver") and ":" not in l]
        except (OSError, IndexError):
            ns = []
        ns = [x for x in ns if not x.startswith("127.")]
        for a in adapters:
            if not a.dns and a.gateway and ns:
                a.dns = list(ns)
        return adapters

    def change(self, enable, disable):
        lines = ["errs=0"]
        for i in enable:
            dev = shlex.quote(_REG[int(i)].device)
            lines += [f"ip link set dev {dev} up || errs=1",
                      f"command -v nmcli >/dev/null 2>&1 && nmcli device connect {dev} >/dev/null 2>&1 || true"]
        for i in disable:
            dev = shlex.quote(_REG[int(i)].device)
            lines += [f"command -v nmcli >/dev/null 2>&1 && nmcli device disconnect {dev} >/dev/null 2>&1 || true",
                      f"ip link set dev {dev} down || errs=1"]
        lines.append("exit $errs")
        return run_root("\n".join(lines))

    def set_dns(self, index, servers):
        dev = _REG[int(index)].device
        conn = self._nm_conn(dev)
        if conn:
            if servers == "auto":
                mods = ["ipv4.dns", "", "ipv4.ignore-auto-dns", "no"]
            else:
                mods = ["ipv4.dns", servers, "ipv4.ignore-auto-dns", "yes"]
            return self._nm([["connection", "modify", conn, *mods], ["connection", "up", "id", conn]])
        if have("resolvectl"):
            if servers == "auto":
                return run_root(f"resolvectl revert {shlex.quote(dev)}")
            return run_root(f"resolvectl dns {shlex.quote(dev)} {' '.join(shlex.quote(s) for s in servers.split(','))}")
        return 1, "No supported DNS backend found (NetworkManager or systemd-resolved)."

    def renew(self, index):
        dev = _REG[int(index)].device
        conn = self._nm_conn(dev)
        if conn:
            return self._nm([["connection", "up", "id", conn]])
        if have("networkctl"):
            return run_root(f"networkctl renew {shlex.quote(dev)}")
        if have("dhclient"):
            q = shlex.quote(dev)
            return run_root(f"dhclient -r {q}; dhclient {q}")
        return 1, "No supported DHCP client found (NetworkManager, systemd-networkd or dhclient)."

    def flush_dns(self):
        return run_root("if command -v resolvectl >/dev/null 2>&1; then resolvectl flush-caches; "
                        "elif command -v systemd-resolve >/dev/null 2>&1; then systemd-resolve --flush-caches; "
                        "elif command -v nscd >/dev/null 2>&1; then nscd -i hosts; "
                        "else echo 'No DNS cache service found.'; fi")

    def rename(self, index, new):
        return 1, "Renaming is not supported on this platform. Use a display name instead."

    def set_metric(self, index, metric):
        a = _REG[int(index)]
        conn = self._nm_conn(a.device)
        value = "-1" if metric == "auto" else metric
        if conn:
            return self._nm([["connection", "modify", conn, "ipv4.route-metric", value,
                              "ipv6.route-metric", value], ["connection", "up", "id", conn]])
        if metric == "auto":
            return 1, "Automatic priority needs NetworkManager."
        if not a.gateway:
            return 1, "This adapter has no default gateway."
        return run_root(f"ip route replace default via {shlex.quote(a.gateway[0])} dev {shlex.quote(a.device)} metric {int(metric)}")

    def set_static(self, index, ip, prefix, gw, dns):
        a = _REG[int(index)]
        conn = self._nm_conn(a.device)
        if conn:
            mods = ["ipv4.method", "manual", "ipv4.addresses", f"{ip}/{prefix}", "ipv4.gateway", gw or "",
                    "ipv4.dns", dns or "", "ipv4.ignore-auto-dns", "yes" if dns else "no"]
            return self._nm([["connection", "modify", conn, *mods], ["connection", "up", "id", conn]])
        dev = shlex.quote(a.device)
        script = f"ip addr flush dev {dev}; ip addr add {shlex.quote(f'{ip}/{prefix}')} dev {dev}"
        if gw:
            script += f"; ip route replace default via {shlex.quote(gw)} dev {dev}"
        if dns and have("resolvectl"):
            script += f"; resolvectl dns {dev} {' '.join(shlex.quote(s) for s in dns.split(','))}"
        return run_root(script)

    def set_dhcp(self, index):
        a = _REG[int(index)]
        conn = self._nm_conn(a.device)
        if conn:
            mods = ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", "",
                    "ipv4.ignore-auto-dns", "no"]
            return self._nm([["connection", "modify", conn, *mods], ["connection", "up", "id", conn]])
        if have("dhclient"):
            q = shlex.quote(a.device)
            return run_root(f"ip addr flush dev {q}; dhclient {q}")
        return 1, "Switching to DHCP needs NetworkManager or dhclient."

    def connections(self, key):
        if not have("ss"):
            raise RuntimeError("Command not found: ss (install iproute2).")
        return _filter_connections(parse_ss(sh_capture(["ss", "-H", "-tanp"], 30)), key)

    def stats_job(self, t):
        def reader():
            out = []
            for dev in os.listdir("/sys/class/net"):
                try:
                    rx = int(open(f"/sys/class/net/{dev}/statistics/rx_bytes").read())
                    tx = int(open(f"/sys/class/net/{dev}/statistics/tx_bytes").read())
                except (OSError, ValueError):
                    continue
                out.append({"N": dev, "R": rx, "S": tx})
            return out
        poll_stats_job(t, reader)

    # -- autostart (XDG)
    @staticmethod
    def _autostart_path() -> str:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return os.path.join(base, "autostart", f"{APP_ID.lower()}.desktop")

    def startup_enabled(self):
        return os.path.exists(self._autostart_path())

    def set_startup(self, enable, icon=""):
        path = self._autostart_path()
        try:
            if enable:
                def q(s: str) -> str:
                    return s if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", s) else '"' + re.sub(r'(["`$\\])', r"\\\1", s) + '"'
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("[Desktop Entry]\nType=Application\nVersion=1.0\n"
                             f"Name={APP_NAME}\nComment=Network adapter manager and toolbox\n"
                             f"Exec={' '.join(q(a) for a in startup_argv())}\n"
                             f"Icon={icon if icon and os.path.exists(icon) else 'network-wired'}\n"
                             "Terminal=false\nCategories=Network;Utility;\nStartupNotify=false\n"
                             "X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\n")
            elif os.path.exists(path):
                os.remove(path)
            return 0, ""
        except OSError as e:
            return 1, str(e)

    # -- toolbox
    def ping_cmd(self, host, count): return ["ping", "-c", str(count), host] if count > 0 else ["ping", host]
    def trace_cmd(self, host):
        return ["traceroute", "-n", "-m", "30", host] if have("traceroute") else ["tracepath", "-n", host]
    def nslookup_cmd(self, host, server):
        if have("nslookup"):
            return ["nslookup", host] + ([server] if server else [])
        if have("dig"):
            return ["dig", host] + ([f"@{server}"] if server else [])
        if have("host"):
            return ["host", host] + ([server] if server else [])
        return []

    def quick_commands(self):
        cmds = [("ip addr", ["ip", "addr"]), ("ip route", ["ip", "route"]), ("ip neigh (ARP)", ["ip", "neigh"]),
                ("ip -s link", ["ip", "-s", "link"]), ("resolvectl status", ["resolvectl", "status"]),
                ("cat /etc/resolv.conf", ["cat", "/etc/resolv.conf"]),
                ("nmcli device status", ["nmcli", "device", "status"]),
                ("nmcli device wifi list", ["nmcli", "device", "wifi", "list"]),
                ("iw dev", ["iw", "dev"]), ("ss -tulpn", ["ss", "-tulpn"])]
        return [c for c in cmds if have(c[1][0])]

    def repair_actions(self):
        return [
            ("🧹", "Flush DNS cache", "Clears the local DNS resolver cache.",
             ["sh", "-c", "resolvectl flush-caches || systemd-resolve --flush-caches || nscd -i hosts"], False),
            ("🔁", "Renew all IP addresses", "Requests fresh DHCP leases on every adapter.",
             ["sh", "-c", "nmcli -t -f NAME connection show --active | while IFS= read -r c; do nmcli connection up id \"$c\"; done"], False),
            ("🧽", "Clear ARP cache", "Removes stale neighbour (ARP) entries.", ["ip", "neigh", "flush", "all"], False),
            ("🌐", "Restart DNS resolver", "Restarts systemd-resolved.", ["systemctl", "restart", "systemd-resolved"], False),
            ("🔌", "Restart NetworkManager", "Restarts the network service; connections drop briefly.",
             ["systemctl", "restart", "NetworkManager"], True),
            ("♻️", "Toggle networking off and on", "Turns all managed networking off and back on.",
             ["sh", "-c", "nmcli networking off; sleep 2; nmcli networking on"], True)]

    def open_settings(self):
        for cmd in (["nm-connection-editor"], ["gnome-control-center", "network"], ["systemsettings", "kcm_networkmanagement"],
                    ["kcmshell6", "kcm_networkmanagement"], ["kcmshell5", "kcm_networkmanagement"],
                    ["cinnamon-settings", "network"], ["unity-control-center", "network"],
                    ["xfce4-settings-manager"], ["mate-network-properties"]):
            if have(cmd[0]):
                subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
        raise RuntimeError("No network settings application was found.")


class MacBackend:
    name = "macOS"
    caps = {"rename": True}

    def fetch_adapters(self) -> list[Adapter]:
        order = parse_mac_service_order(sh_capture(["networksetup", "-listnetworkserviceorder"]))
        dns_map = parse_scutil_dns(sh_capture(["scutil", "--dns"]))
        stats = {r["N"]: r for r in parse_netstat_ib(sh_capture(["netstat", "-ib"]))}
        out: list[Adapter] = []
        for s in order:
            dev = s["device"]
            try:
                index = socket.if_nametoindex(dev)
            except OSError:
                continue
            ifc = parse_ifconfig(sh_capture(["ifconfig", dev]))
            info = parse_mac_getinfo(sh_capture(["networksetup", "-getinfo", s["service"]]))
            if s["disabled"]:
                status = "Disabled"
            elif ifc["active"] or (ifc["active"] is None and ifc["up"] and ifc["v4"]):
                status = "Up"
            else:
                status = "Disconnected"
            mm = re.search(r"\((\d+)(G?)base", ifc["media"])
            mbps = int(mm.group(1)) * (1000 if mm.group(2) else 1) if mm else 0
            st = stats.get(dev, {})
            hardware = dev.startswith("en") and "Thunderbolt Bridge" not in s["service"]
            dns = dns_map.get(dev, [])
            if not dns:
                raw = sh_capture(["networksetup", "-getdnsservers", s["service"]])
                dns = [x for x in raw.split() if re.match(r"^\d+\.\d+\.\d+\.\d+$", x)]
            out.append(Adapter(
                name=s["service"], device=dev, description=f"{s['port']} ({dev})", index=index, status=status,
                mac=ifc["mac"], speed=fmt_mbps(mbps), media="802.11" if "wi-fi" in s["port"].lower() or "airport" in s["port"].lower() else "802.3",
                virtual=not hardware, hardware=hardware, metric=str(s["order"]), auto_metric="", dhcp=info["dhcp"],
                rx=int(st.get("R", 0)), tx=int(st.get("S", 0)), ipv4=ifc["v4"], ipv6=ifc["v6"],
                gateway=[info["router"]] if info["router"] else [], dns=dns))
        return out

    @staticmethod
    def _svc(index: int) -> str:
        return _REG[int(index)].name

    def change(self, enable, disable):
        lines = ["errs=0"]
        for i in enable:
            lines.append(f"networksetup -setnetworkserviceenabled {shlex.quote(self._svc(i))} on || errs=1")
        for i in disable:
            lines.append(f"networksetup -setnetworkserviceenabled {shlex.quote(self._svc(i))} off || errs=1")
        lines.append("exit $errs")
        return run_root("\n".join(lines))

    def set_dns(self, index, servers):
        svc = shlex.quote(self._svc(index))
        arg = "empty" if servers == "auto" else " ".join(shlex.quote(s) for s in servers.split(","))
        return run_root(f"networksetup -setdnsservers {svc} {arg} && (dscacheutil -flushcache; killall -HUP mDNSResponder; true)")

    def renew(self, index):
        return run_root(f"ipconfig set {shlex.quote(_REG[int(index)].device)} DHCP")

    def flush_dns(self):
        return run_root("dscacheutil -flushcache; killall -HUP mDNSResponder; true")

    def rename(self, index, new):
        return run_root(f"networksetup -renamenetworkservice {shlex.quote(self._svc(index))} {shlex.quote(new)}")

    def set_metric(self, index, metric):
        if metric == "auto":
            return 1, "macOS uses the service order; reorder services in System Settings → Network."
        names = [a.name for a in sorted(_REG.values(), key=lambda a: int(a.metric or 99))]
        target = self._svc(index)
        names = [target] + [n for n in names if n != target]
        return run_root("networksetup -ordernetworkservices " + " ".join(shlex.quote(n) for n in names))

    def set_static(self, index, ip, prefix, gw, dns):
        svc = shlex.quote(self._svc(index))
        script = f"networksetup -setmanual {svc} {shlex.quote(ip)} {netmask_from_prefix(prefix)} {shlex.quote(gw or ip)}"
        if dns:
            script += f" && networksetup -setdnsservers {svc} " + " ".join(shlex.quote(s) for s in dns.split(","))
        return run_root(script)

    def set_dhcp(self, index):
        svc = shlex.quote(self._svc(index))
        return run_root(f"networksetup -setdhcp {svc} && networksetup -setdnsservers {svc} empty")

    def connections(self, key):
        if not have("lsof"):
            raise RuntimeError("Command not found: lsof")
        rows = parse_lsof_fields(sh_capture(["lsof", "-nP", "-iTCP", "-F", "pcnT"], 30))
        return _filter_connections(rows, key)

    def stats_job(self, t):
        poll_stats_job(t, lambda: parse_netstat_ib(sh_capture(["netstat", "-ib"])))

    # -- autostart (LaunchAgent)
    @staticmethod
    def _plist_path() -> str:
        return os.path.expanduser(f"~/Library/LaunchAgents/com.{APP_ID.lower()}.app.plist")

    def startup_enabled(self):
        return os.path.exists(self._plist_path())

    def set_startup(self, enable, icon=""):
        path = self._plist_path()
        try:
            if enable:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as fh:
                    plistlib.dump({"Label": f"com.{APP_ID.lower()}.app", "ProgramArguments": startup_argv(),
                                   "RunAtLoad": True, "ProcessType": "Interactive",
                                   "LimitLoadToSessionType": "Aqua"}, fh)
            elif os.path.exists(path):
                os.remove(path)    # takes effect at the next login (we do not unload the running copy)
            return 0, ""
        except OSError as e:
            return 1, str(e)

    def ping_cmd(self, host, count): return ["ping", "-c", str(count), host] if count > 0 else ["ping", host]
    def trace_cmd(self, host): return ["traceroute", "-n", "-m", "30", host]
    def nslookup_cmd(self, host, server): return ["nslookup", host] + ([server] if server else [])

    def quick_commands(self):
        return [("ifconfig", ["ifconfig"]), ("netstat -rn", ["netstat", "-rn"]), ("arp -a", ["arp", "-a"]),
                ("networksetup -listallhardwareports", ["networksetup", "-listallhardwareports"]),
                ("networksetup -listnetworkserviceorder", ["networksetup", "-listnetworkserviceorder"]),
                ("scutil --dns", ["scutil", "--dns"]),
                ("system_profiler SPNetworkDataType", ["system_profiler", "SPNetworkDataType"])]

    def repair_actions(self):
        return [
            ("🧹", "Flush DNS cache", "Clears the local DNS resolver cache.",
             ["sh", "-c", "dscacheutil -flushcache; killall -HUP mDNSResponder"], False),
            ("🔁", "Renew all IP addresses", "Requests fresh DHCP leases on every adapter.",
             ["sh", "-c", "for d in $(ifconfig -lu); do case $d in en*) ipconfig set $d DHCP;; esac; done"], False),
            ("🧽", "Clear ARP cache", "Removes stale neighbour (ARP) entries.", ["arp", "-a", "-d"], False),
            ("📶", "Restart Wi-Fi", "Turns the Wi-Fi radio off and on again.",
             ["sh", "-c", "d=$(networksetup -listallhardwareports | awk '/Wi-Fi|AirPort/{getline; print $2}'); "
                          "networksetup -setairportpower $d off; sleep 2; networksetup -setairportpower $d on"], True)]

    def open_settings(self):
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.Network-Settings.extension"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


BACKEND = WindowsBackend() if IS_WINDOWS else MacBackend() if IS_MAC else LinuxBackend()
CAPS = BACKEND.caps
QUICK_COMMANDS = BACKEND.quick_commands()


# Public API used by the GUI (thin wrappers so that they can be replaced in tests)
def fetch_adapters() -> list[Adapter]:
    adapters = BACKEND.fetch_adapters()
    _REG.clear()
    _REG.update({a.index: a for a in adapters})
    return adapters


def change_adapters(enable: list[int], disable: list[int]) -> tuple[int, str]:
    return BACKEND.change(enable, disable)


def set_dns(index: int, servers: str) -> tuple[int, str]:
    return BACKEND.set_dns(index, servers)


def renew_dhcp(index: int) -> tuple[int, str]:
    return BACKEND.renew(index)


def flush_dns() -> tuple[int, str]:
    return BACKEND.flush_dns()


def rename_adapter(index: int, new_name: str) -> tuple[int, str]:
    return BACKEND.rename(index, new_name)


def set_metric(index: int, metric: str) -> tuple[int, str]:
    return BACKEND.set_metric(index, metric)


def set_static_ip(index: int, ip: str, prefix: int, gw: str, dns: str) -> tuple[int, str]:
    return BACKEND.set_static(index, ip, prefix, gw, dns)


def set_dhcp(index: int) -> tuple[int, str]:
    return BACKEND.set_dhcp(index)


def fetch_connections(key: str) -> list[dict]:
    return BACKEND.connections(key)


def stats_stream_job(t: "Task") -> None:
    BACKEND.stats_job(t)


def startup_enabled() -> bool:
    return bool(BACKEND.startup_enabled())


def set_startup(enable: bool, icon: str = "") -> tuple[int, str]:
    return BACKEND.set_startup(enable, icon)


def open_os_network_settings() -> None:
    BACKEND.open_settings()



# ----------------------------------------------------------------------------
# Toolbox jobs
# ----------------------------------------------------------------------------
_HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]{1,253}$")


def check_host(text: str) -> str:
    host = text.strip()
    if not host or host.startswith("-") or not _HOST_RE.match(host):
        raise ValueError(tr("Invalid host name or IP address."))
    return host


def parse_ports(text: str) -> list[int]:
    ports: list[int] = []
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            if lo > hi:
                lo, hi = hi, lo
            ports.extend(range(lo, hi + 1))
        else:
            ports.append(int(part))
    ports = [p for p in dict.fromkeys(ports) if 0 < p < 65536]
    if not ports or len(ports) > 1024:
        raise ValueError(tr("Enter between 1 and 1024 valid ports (e.g. 80,443,8000-8010)."))
    return ports


def _stream_checked(t: Task, argv: list[str]) -> None:
    if not argv or not have(argv[0]):
        t.emit(tr("Command not found: {c}. Install it with your package manager.", c=argv[0] if argv else "?"))
        return
    stream_command(t, argv)


def job_ping(t: Task, v: dict) -> None:
    host, count = check_host(v["host"]), int(v["count"])
    _stream_checked(t, BACKEND.ping_cmd(host, count))


def job_tracert(t: Task, v: dict) -> None:
    _stream_checked(t, BACKEND.trace_cmd(check_host(v["host"])))


def job_nslookup(t: Task, v: dict) -> None:
    host = check_host(v["host"])
    server = v.get("server", "").strip()
    if server:
        server = check_host(server)
    args = BACKEND.nslookup_cmd(host, server)
    if args and have(args[0]):
        stream_command(t, args)
        return
    t.emit(tr("(nslookup is not installed — using the system resolver)"))
    seen: list[str] = []
    for *_x, sa in socket.getaddrinfo(host, None):
        if sa[0] not in seen:
            seen.append(sa[0])
            t.emit(f"  {sa[0]}")


def job_ports(t: Task, v: dict) -> None:
    host, ports = check_host(v["host"]), parse_ports(v["ports"])
    t.emit(tr("Scanning {host} …", host=host))
    open_count = 0
    for port in ports:
        if t.stopped():
            return
        t0 = time.perf_counter()
        try:
            s = socket.create_connection((host, port), timeout=2.0)
            s.close()
            open_count += 1
            t.emit(f"  ✔  {port:<6} {tr('open')}   ({(time.perf_counter() - t0) * 1000:.0f} ms)")
        except OSError:
            t.emit(f"  ✘  {port:<6} {tr('closed / filtered')}")
    t.emit(tr("Done — {n} open of {total} checked.", n=open_count, total=len(ports)))


def job_iplookup(t: Task, v: dict) -> None:
    q = v["query"].strip()
    if q:
        q = check_host(q)
        try:
            ipaddress.ip_address(q)
        except ValueError:
            t.emit(tr("Resolving {host} …", host=q))
            q = socket.gethostbyname(q)
            t.emit(f"  → {q}")
    info = fetch_public_ip(None, q)
    rows = [("IP", info["ip"]), (tr("Country"), f"{info['country']} ({info['cc']})".strip(" ()")),
            (tr("Region"), info["region"]), (tr("City"), info["city"]), ("ISP", info["isp"]),
            ("ASN", info["asn"]), (tr("Time zone"), info["tz"]), (tr("Source"), info["provider"])]
    for k, val in rows:
        if val:
            t.emit(f"  {k:<14}: {val}")


def job_quick(t: Task, v: dict) -> None:
    stream_command(t, QUICK_COMMANDS[int(v["cmd"])][1])


DNS_BENCH_SERVERS = [
    ("Cloudflare", "1.1.1.1"), ("Google", "8.8.8.8"), ("Quad9", "9.9.9.9"),
    ("OpenDNS", "208.67.222.222"), ("AdGuard", "94.140.14.14"), ("CleanBrowsing", "185.228.168.9"),
]
DNS_BENCH_NAMES = ["google.com", "cloudflare.com", "wikipedia.org", "github.com", "microsoft.com"]


def dns_query_ms(server: str, name: str, timeout: float = 2.0) -> float | None:
    tid = os.urandom(2)
    question = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00\x00\x01\x00\x01"
    packet = tid + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + question
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t0 = time.perf_counter()
        s.sendto(packet, (server, 53))
        data, _ = s.recvfrom(2048)
        ms = (time.perf_counter() - t0) * 1000
        return ms if data[:2] == tid and (data[3] & 0x0F) == 0 else None
    except OSError:
        return None
    finally:
        s.close()


def job_dns_bench(t: Task, extra: list[tuple[str, str]]) -> None:
    servers = list(extra) + DNS_BENCH_SERVERS
    seen: set[str] = set()
    for label, ip in servers:
        if ip in seen:
            continue
        seen.add(ip)
        if t.stopped():
            return
        samples: list[float] = []
        fails = 0
        for name in DNS_BENCH_NAMES:
            for _ in range(2):
                ms = dns_query_ms(ip, name)
                if ms is None:
                    fails += 1
                else:
                    samples.append(ms)
            if fails >= 3 and not samples:
                break
        total = len(DNS_BENCH_NAMES) * 2
        t.emit(("row", {"label": label, "ip": ip,
                        "median": statistics.median(samples) if samples else None,
                        "ok": len(samples), "total": total}))


# ---- speed test (Cloudflare edge; download falls back to OVH) ----------------
SPEED_HOST = "speed.cloudflare.com"
_SPEED_HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*"}


class _Abort(Exception):
    pass


def _speed_conn(host: str, src_ip):
    return _make_https(host, src_ip, 8)


def _dl_worker(host, path, src_ip, add, stop_at, stopped, errors) -> None:
    try:
        c = _speed_conn(host, src_ip)
        while time.monotonic() < stop_at and not stopped():
            c.request("GET", path, headers=_SPEED_HEADERS)
            r = c.getresponse()
            if r.status != 200:
                raise RuntimeError(f"HTTP {r.status}")
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                add(len(chunk))
                if time.monotonic() >= stop_at or stopped():
                    c.close()
                    return
        c.close()
    except Exception as e:  # noqa: BLE001
        errors.append(str(e))


class _CountingBody:
    def __init__(self, size, payload, add, stop_at, stopped):
        self.left, self.payload, self.add, self.stop_at, self.stopped = size, payload, add, stop_at, stopped

    def read(self, n: int = 8192) -> bytes:
        if time.monotonic() >= self.stop_at or self.stopped():
            raise _Abort()
        n = min(n, self.left)
        if n <= 0:
            return b""
        self.left -= n
        self.add(n)
        return self.payload[:n]


def _ul_worker(host, src_ip, add, stop_at, stopped, errors) -> None:
    size = 4 * 1024 * 1024
    payload = b"\x5a" * 65536
    try:
        c = _speed_conn(host, src_ip)
        while time.monotonic() < stop_at and not stopped():
            body = _CountingBody(size, payload, add, stop_at, stopped)
            c.request("POST", "/__up", body=body,
                      headers={**_SPEED_HEADERS, "Content-Type": "application/octet-stream",
                               "Content-Length": str(size)})
            c.getresponse().read()
        c.close()
    except _Abort:
        return
    except Exception as e:  # noqa: BLE001
        errors.append(str(e))


def _run_transfer(t: Task, target, args_fn, duration: float, threads: int) -> float:
    counter = [0]
    lock = threading.Lock()
    errors: list[str] = []

    def add(n: int) -> None:
        with lock:
            counter[0] += n

    start = time.monotonic()
    stop_at = start + duration
    workers = [threading.Thread(target=target, args=args_fn(add, stop_at, errors), daemon=True)
               for _ in range(threads)]
    for w in workers:
        w.start()
    last_b, last_t, ema = 0, start, 0.0
    mark: tuple[int, float] | None = None
    while any(w.is_alive() for w in workers) and not t.stopped():
        time.sleep(0.12)
        now, b = time.monotonic(), counter[0]
        inst = (b - last_b) * 8 / max(now - last_t, 1e-3) / 1e6
        ema = inst if ema == 0 else 0.65 * ema + 0.35 * inst
        last_b, last_t = b, now
        if mark is None and now - start >= 1.0:
            mark = (b, now)
        t.emit(("value", ema))
    if t.stopped():
        raise _Abort()
    if counter[0] == 0:
        raise RuntimeError(errors[0] if errors else "No data transferred")
    now = time.monotonic()
    if mark and now - mark[1] > 0.5:
        return (counter[0] - mark[0]) * 8 / (now - mark[1]) / 1e6
    return counter[0] * 8 / max(now - start, 1e-3) / 1e6


def speed_test_job(t: Task, src_ip: str | None) -> None:
    result = {"ping": None, "jitter": None, "down": None, "up": None}
    try:
        t.emit(("phase", "ping"))
        c = _speed_conn(SPEED_HOST, src_ip)
        times: list[float] = []
        for _ in range(8):
            if t.stopped():
                return
            t0 = time.perf_counter()
            c.request("GET", "/__down?bytes=0", headers=_SPEED_HEADERS)
            c.getresponse().read()
            times.append((time.perf_counter() - t0) * 1000)
        c.close()
        times = times[1:]
        result["ping"] = min(times)
        result["jitter"] = statistics.mean(abs(a - b) for a, b in zip(times, times[1:]))
        t.emit(("ping", result["ping"], result["jitter"]))

        t.emit(("phase", "download"))
        sources = [(SPEED_HOST, "/__down?bytes=50000000"), ("proof.ovh.net", "/files/100Mb.dat")]
        last_err = None
        for host, path in sources:
            try:
                result["down"] = _run_transfer(
                    t, _dl_worker, lambda add, stop_at, errors, h=host, p=path:
                    (h, p, src_ip, add, stop_at, t.stopped, errors), 8.0, 4)
                break
            except _Abort:
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
        if result["down"] is None:
            raise RuntimeError(str(last_err))
        t.emit(("value_done", result["down"]))

        t.emit(("phase", "upload"))
        try:
            result["up"] = _run_transfer(
                t, _ul_worker, lambda add, stop_at, errors: (SPEED_HOST, src_ip, add, stop_at, t.stopped, errors),
                7.0, 3)
        except _Abort:
            return
        except Exception:  # noqa: BLE001
            result["up"] = None
        t.emit(("value_done", result["up"] or 0.0))
        t.emit(("result", result))
    except _Abort:
        return


# ----------------------------------------------------------------------------
# Animation helpers & custom widgets
# ----------------------------------------------------------------------------
def fade_in(widget: QWidget, duration: int = 260, delay: int = 0) -> None:
    """Fade a widget in (optionally after `delay` ms). Disabled by the Animations setting."""
    if not PREFS.get("animations"):
        return
    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)
    fade = QPropertyAnimation(eff, b"opacity", widget)
    fade.setDuration(duration)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(QEasingCurve.Type.OutCubic)
    group = QSequentialAnimationGroup(widget)
    if delay:
        group.addPause(delay)
    group.addAnimation(fade)
    group.finished.connect(lambda w=widget: w.setGraphicsEffect(None))
    group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


class ToggleSwitch(QAbstractButton):
    """iOS-style animated switch."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(50, 28)
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(50, 28)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, v: float) -> None:
        self._offset = v
        self.update()

    offset = pyqtProperty(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

    def set_state(self, value: bool) -> None:
        """Silent update (no signals) — used to mirror the real system state."""
        self.blockSignals(True)
        self.setChecked(value)
        self.blockSignals(False)
        self._anim.stop()
        self._set_offset(1.0 if value else 0.0)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off, on = QColor(THEME["toggle_off"]), QColor(THEME["ok"])
        t = self._offset
        color = QColor(int(off.red() + (on.red() - off.red()) * t),
                       int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            p.setOpacity(0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        w, h = self.width(), self.height()
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        d = h - 8
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(4 + (w - 8 - d) * t, 4, d, d))
        p.end()


class BusyOverlay(QWidget):
    """Full-window loading layer; nothing underneath can be clicked while it is visible."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.BusyCursor)
        self._title = ""
        self._sub = ""
        self._angle = 0
        self._fade = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._fade_anim = QPropertyAnimation(self, b"fade", self)
        self._fade_anim.setDuration(200)
        self.hide()

    def _get_fade(self) -> float:
        return self._fade

    def _set_fade(self, v: float) -> None:
        self._fade = v
        self.update()

    fade = pyqtProperty(float, _get_fade, _set_fade)

    def _tick(self) -> None:
        self._angle = (self._angle + 7) % 360
        self.update()

    def show_busy(self, title: str, sub: str = "") -> None:
        self._title, self._sub = title, sub
        parent = self.parentWidget()
        if parent:
            self.setGeometry(parent.rect())
        if PREFS.get("animations"):
            self._fade = 0.0
            self._fade_anim.stop()
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()
        else:
            self._fade = 1.0
        self.raise_()
        self.show()
        self.setFocus()
        self._timer.start()

    def set_text(self, title: str | None = None, sub: str | None = None) -> None:
        if title is not None:
            self._title = title
        if sub is not None:
            self._sub = sub
        self.update()

    def hide_busy(self) -> None:
        self._timer.stop()
        self.hide()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setOpacity(self._fade)
        scrim = QColor(THEME["bg"])
        scrim.setAlpha(205)
        p.fillRect(self.rect(), scrim)
        pw, ph = 440.0, 220.0
        panel = QRectF((self.width() - pw) / 2, (self.height() - ph) / 2 + (1 - self._fade) * 14, pw, ph)
        p.setPen(QPen(QColor(THEME["border"]), 1))
        p.setBrush(QColor(THEME["surface"]))
        p.drawRoundedRect(panel, 18, 18)
        cx, cy, r = panel.center().x(), panel.top() + 62, 24.0
        ring = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.setPen(QPen(QColor(THEME["border"]), 5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring)
        pen = QPen(QColor(THEME["accent"]), 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(ring, int(-self._angle * 16), 110 * 16)
        opt = QTextOption(Qt.AlignmentFlag.AlignCenter)
        f = QFont(self.font())
        f.setPointSize(12)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(THEME["text"]))
        p.drawText(QRectF(panel.left() + 16, cy + r + 14, pw - 32, 30), self._title, opt)
        f.setPointSize(10)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(THEME["muted"]))
        p.drawText(QRectF(panel.left() + 20, cy + r + 46, pw - 40, 44), self._sub, opt)
        f.setPointSize(9)
        p.setFont(f)
        p.drawText(QRectF(panel.left() + 16, panel.bottom() - 30, pw - 32, 22), tr("Please wait …"), opt)
        p.end()


class RootWidget(QWidget):
    overlay: BusyOverlay | None = None

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.overlay is not None:
            self.overlay.setGeometry(self.rect())


def _series_path(values, w: float, h: float, maxv: float, x0: float = 0.0, y0: float = 0.0,
                 slots: int | None = None) -> QPainterPath:
    path = QPainterPath()
    n = slots or max(len(values), 2)
    step = w / (n - 1)
    off = n - len(values)
    for i, v in enumerate(values):
        x = x0 + (off + i) * step
        y = y0 + h - (min(v, maxv) / maxv) * h
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    return path


class Sparkline(QWidget):
    """Tiny live download/upload graph shown in each adapter card."""

    def __init__(self, parent: QWidget | None = None, size: int = 60):
        super().__init__(parent)
        self.setFixedSize(112, 34)
        self.down: deque[float] = deque(maxlen=size)
        self.up: deque[float] = deque(maxlen=size)
        self._slots = size

    def push(self, d: float, u: float) -> None:
        self.down.append(d)
        self.up.append(u)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if len(self.down) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        mx = max(max(self.down), max(self.up), 2048.0)
        w, h = self.width() - 2.0, self.height() - 4.0
        line = _series_path(list(self.down), w, h, mx, 1, 2, self._slots)
        fill = QPainterPath(line)
        n = self._slots
        fill.lineTo(1 + w, 2 + h)
        fill.lineTo(1 + (n - len(self.down)) * w / (n - 1), 2 + h)
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, self.height())
        c = QColor(THEME["accent"])
        c.setAlpha(110)
        grad.setColorAt(0, c)
        c.setAlpha(0)
        grad.setColorAt(1, c)
        p.fillPath(fill, QBrush(grad))
        p.setPen(QPen(QColor(THEME["accent"]), 1.6))
        p.drawPath(line)
        p.setPen(QPen(QColor(THEME["ok"]), 1.3))
        p.drawPath(_series_path(list(self.up), w, h, mx, 1, 2, self._slots))
        p.end()


def nice_max(v: float) -> float:
    import math
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


class BandwidthChart(QWidget):
    """Large live chart (download = accent, upload = green) with grid and axis labels."""

    def __init__(self, slots: int = 120, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.slots = slots
        self.down: list[float] = []
        self.up: list[float] = []

    def set_data(self, down: list[float], up: list[float]) -> None:
        self.down, self.up = down[-self.slots:], up[-self.slots:]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        left, right, top, bottom = 78.0, 14.0, 12.0, 24.0
        w, h = self.width() - left - right, self.height() - top - bottom
        mx = nice_max(max([*self.down, *self.up, 10240.0]))
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        for i in range(5):
            y = top + h * i / 4
            p.setPen(QPen(QColor(THEME["border"]), 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(left, y), QPointF(left + w, y))
            p.setPen(QColor(THEME["muted"]))
            p.drawText(QRectF(0, y - 9, left - 8, 18), fmt_rate(mx * (1 - i / 4)),
                       QTextOption(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        p.setPen(QColor(THEME["muted"]))
        p.drawText(QRectF(left, self.height() - 20, 100, 16), tr("{n} s ago", n=self.slots),
                   QTextOption(Qt.AlignmentFlag.AlignLeft))
        p.drawText(QRectF(left + w - 100, self.height() - 20, 100, 16), tr("now"),
                   QTextOption(Qt.AlignmentFlag.AlignRight))
        if len(self.down) >= 2:
            line = _series_path(self.down, w, h, mx, left, top, self.slots)
            fill = QPainterPath(line)
            off = self.slots - len(self.down)
            fill.lineTo(left + w, top + h)
            fill.lineTo(left + off * w / (self.slots - 1), top + h)
            fill.closeSubpath()
            grad = QLinearGradient(0, top, 0, top + h)
            c = QColor(THEME["accent"])
            c.setAlpha(120)
            grad.setColorAt(0, c)
            c.setAlpha(0)
            grad.setColorAt(1, c)
            p.fillPath(fill, QBrush(grad))
            p.setPen(QPen(QColor(THEME["accent"]), 2.0))
            p.drawPath(line)
            p.setPen(QPen(QColor(THEME["ok"]), 1.8))
            p.drawPath(_series_path(self.up, w, h, mx, left, top, self.slots))
        p.end()


class GaugeWidget(QWidget):
    """Animated arc gauge used by the speed test."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(320, 270)
        self._value = 0.0
        self._max = 100.0
        self._caption = ""
        self._unit = "Mbps"
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_value(self) -> float:
        return self._value

    def _set_value(self, v: float) -> None:
        self._value = v
        self.update()

    value = pyqtProperty(float, _get_value, _set_value)

    @staticmethod
    def _scale(v: float) -> float:
        for m in (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000):
            if v <= m * 0.92:
                return float(m)
        return 10000.0

    def reset(self) -> None:
        self._anim.stop()
        self._max = 100.0
        self._set_value(0.0)

    def set_value(self, v: float) -> None:
        self._max = max(self._max, self._scale(v))
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(float(v))
        self._anim.start()

    def set_caption(self, text: str) -> None:
        self._caption = text
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        side = min(self.width(), self.height() - 10) - 30.0
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2 - 6, side, side)
        pen = QPen(QColor(THEME["border"]), 16)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 225 * 16, -270 * 16)
        frac = max(0.0, min(1.0, self._value / self._max))
        if frac > 0:
            pen = QPen(QColor(THEME["accent"]), 16)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 225 * 16, int(-270 * 16 * frac))
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)
        p.setPen(QColor(THEME["muted"]))
        p.drawText(QRectF(rect.left() - 4, rect.bottom() - 14, 50, 18), "0", QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.drawText(QRectF(rect.right() - 46, rect.bottom() - 14, 50, 18), f"{self._max:.0f}",
                   QTextOption(Qt.AlignmentFlag.AlignCenter))
        big = QFont(self.font())
        big.setPointSize(30)
        big.setBold(True)
        p.setFont(big)
        p.setPen(QColor(THEME["text"]))
        p.drawText(QRectF(rect.left(), rect.center().y() - 40, side, 56), f"{self._value:.1f}",
                   QTextOption(Qt.AlignmentFlag.AlignCenter))
        small.setPointSize(11)
        p.setFont(small)
        p.setPen(QColor(THEME["muted"]))
        p.drawText(QRectF(rect.left(), rect.center().y() + 14, side, 22), self._unit,
                   QTextOption(Qt.AlignmentFlag.AlignCenter))
        small.setBold(True)
        p.setFont(small)
        p.setPen(QColor(THEME["accent"]))
        p.drawText(QRectF(rect.left(), rect.center().y() + 40, side, 22), self._caption,
                   QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


class NavButton(QPushButton):
    """Sidebar entry drawn in code (direction aware, with hover highlight)."""

    def __init__(self, glyph: str, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.glyph, self.label = glyph, text
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self._hover = False

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self._hover and not self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(THEME["hover"]))
            p.drawRoundedRect(QRectF(self.rect()), 11, 11)
        rtl = self.isRightToLeft()
        w = self.width()
        icon_rect = QRectF(w - 46 if rtl else 6, 0, 40, self.height())
        text_rect = QRectF(10 if rtl else 50, 0, w - 62, self.height())
        f = QFont(self.font())
        f.setPointSize(13)
        p.setFont(f)
        p.setPen(QColor(THEME["text"]))
        p.drawText(icon_rect, self.glyph, QTextOption(Qt.AlignmentFlag.AlignCenter))
        f.setPointSize(10)
        f.setBold(self.isChecked())
        p.setFont(f)
        p.setPen(QColor(THEME["text"] if self.isChecked() or self._hover else THEME["muted"]))
        align = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)
        p.drawText(text_rect, self.label, QTextOption(align))
        p.end()


class ClickableLabel(QLabel):
    doubleClicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.doubleClicked.emit()


class NameEdit(QLineEdit):
    cancelled = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class Tile(QFrame):
    """Small statistic tile: caption + large value."""

    def __init__(self, caption: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        self.cap = QLabel(caption)
        self.cap.setObjectName("FieldKey")
        self.value = QLabel("—")
        self.value.setObjectName("TileValue")
        self.sub = QLabel("")
        self.sub.setObjectName("Muted")
        self.sub.hide()
        lay.addWidget(self.cap)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, text: str, color: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"color:{color};" if color else "")

    def set_caption(self, text: str) -> None:
        self.cap.setText(text)

    def set_sub(self, text: str) -> None:
        self.sub.setText(text)
        self.sub.setVisible(bool(text))


def page_header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("Title")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("Muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


def panel(layout_cls=QVBoxLayout, margins=(18, 14, 18, 14), spacing=10) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("Panel")
    lay = layout_cls(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


STATUS_MAP = {
    "up": ("Connected", "ok"),
    "disconnected": ("Disconnected", "warn"),
    "disabled": ("Disabled", "danger"),
    "not present": ("Unknown", "muted"),
}


class IpBar(QFrame):
    """Public IP banner (main internet route)."""

    refreshRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("IpBar")
        self._ip = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(14)
        icon = QLabel("🌍")
        icon.setStyleSheet("font-size: 26px;")
        col = QVBoxLayout()
        col.setSpacing(1)
        cap = QLabel(tr("Your public IP (main internet route)"))
        cap.setObjectName("Muted")
        self.value = QLabel("—")
        self.value.setObjectName("IpValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail = QLabel("")
        self.detail.setObjectName("Muted")
        self.detail.setWordWrap(True)
        col.addWidget(cap)
        col.addWidget(self.value)
        col.addWidget(self.detail)
        self.btn_copy = QPushButton("📋 " + tr("Copy"))
        self.btn_copy.clicked.connect(self._copy)
        self.btn_refresh = QPushButton("🔄 " + tr("Check again"))
        self.btn_refresh.clicked.connect(self.refreshRequested.emit)
        lay.addWidget(icon)
        lay.addLayout(col, 1)
        lay.addWidget(self.btn_copy)
        lay.addWidget(self.btn_refresh)
        self.set_error(tr("Not checked yet"))

    def _copy(self) -> None:
        if self._ip:
            QApplication.clipboard().setText(self._ip)
            self.btn_copy.setText("✅ " + tr("Copied"))
            QTimer.singleShot(1200, lambda: self.btn_copy.setText("📋 " + tr("Copy")))

    def set_loading(self) -> None:
        self.btn_refresh.setEnabled(False)
        self.value.setText(tr("Checking …"))
        self.detail.setText("⏳ " + tr("Contacting IP lookup services"))

    def set_info(self, info: dict) -> None:
        self.btn_refresh.setEnabled(True)
        self._ip = info["ip"]
        self.btn_copy.setEnabled(True)
        self.value.setText(ltr(info["ip"]))
        country, cc = info.get("country") or "", info.get("cc") or ""
        place = f"{country} ({cc})" if country and cc else (country or cc)
        parts = [place, info.get("city", ""), info.get("isp", ""), info.get("asn", "")]
        self.detail.setText("  •  ".join(p for p in parts if p) or "—")
        self.setToolTip(tr("Source: {p}   |   Time zone: {tz}", p=info.get("provider", "?"), tz=info.get("tz") or "—"))

    def set_error(self, msg: str) -> None:
        self.btn_refresh.setEnabled(True)
        self._ip = ""
        self.btn_copy.setEnabled(False)
        self.value.setText("—")
        self.detail.setText(f"❌ {msg}")
        self.setToolTip("")


DNS_PRESETS = [
    ("auto", "Automatic (DHCP)"),
    ("1.1.1.1,1.0.0.1", "Cloudflare — 1.1.1.1"),
    ("8.8.8.8,8.8.4.4", "Google — 8.8.8.8"),
    ("9.9.9.9,149.112.112.112", "Quad9 — 9.9.9.9"),
    ("208.67.222.222,208.67.220.220", "OpenDNS — 208.67.222.222"),
]


class IpConfigDialog(QDialog):
    """Static IP / DHCP editor for one adapter."""

    def __init__(self, adapter: Adapter, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("IP configuration — {name}", name=adapter.name))
        self.setMinimumWidth(460)
        self.result_cfg: dict | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)
        self.rb_dhcp = QRadioButton(tr("Obtain IP address and DNS automatically (DHCP)"))
        self.rb_static = QRadioButton(tr("Use a static IP address"))
        (self.rb_dhcp if adapter.dhcp == "Enabled" else self.rb_static).setChecked(True)
        lay.addWidget(self.rb_dhcp)
        lay.addWidget(self.rb_static)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.ip = QLineEdit(adapter.primary_ip)
        self.prefix = QSpinBox()
        self.prefix.setRange(1, 32)
        self.prefix.setValue(adapter.prefix)
        self.gw = QLineEdit(adapter.gateway[0] if adapter.gateway else "")
        self.dns = QLineEdit(", ".join(adapter.dns))
        rows = [(tr("IP address"), self.ip), (tr("Prefix length"), self.prefix),
                (tr("Gateway"), self.gw), (tr("DNS servers (comma separated)"), self.dns)]
        for i, (label, widget) in enumerate(rows):
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(widget, i, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self.err = QLabel("")
        self.err.setStyleSheet(f"color:{THEME['danger']};")
        lay.addWidget(self.err)
        btns = QHBoxLayout()
        btns.addStretch(1)
        ok = QPushButton(tr("Apply"))
        ok.setObjectName("Primary")
        cancel = QPushButton(tr("Cancel"))
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)
        for w in (self.ip, self.gw, self.dns):
            w.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.rb_dhcp.toggled.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        for w in (self.ip, self.prefix, self.gw):
            w.setEnabled(self.rb_static.isChecked())
        self.dns.setEnabled(self.rb_static.isChecked())

    def _accept(self) -> None:
        if self.rb_dhcp.isChecked():
            self.result_cfg = {"mode": "dhcp"}
            self.accept()
            return
        try:
            ip = str(ipaddress.IPv4Address(self.ip.text().strip()))
            gw = self.gw.text().strip()
            if gw:
                gw = str(ipaddress.IPv4Address(gw))
            dns = [str(ipaddress.IPv4Address(x)) for x in re.split(r"[,\s]+", self.dns.text().strip()) if x]
        except ValueError:
            self.err.setText(tr("One of the addresses is not valid."))
            return
        self.result_cfg = {"mode": "static", "ip": ip, "prefix": self.prefix.value(), "gw": gw,
                           "dns": ",".join(dns)}
        self.accept()


class AdapterCard(QFrame):
    toggleRequested = pyqtSignal(int, bool)
    exclusiveRequested = pyqtSignal(int)
    probeRequested = pyqtSignal(int)
    dnsRequested = pyqtSignal(int, str)
    renewRequested = pyqtSignal(int)
    renameRequested = pyqtSignal(int, str)
    winRenameRequested = pyqtSignal(int)
    hideRequested = pyqtSignal(int)
    ipConfigRequested = pyqtSignal(int)
    metricRequested = pyqtSignal(int, str)

    def __init__(self, adapter: Adapter, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.adapter = adapter
        self._probe: dict | None = None
        self._testing = False
        self._nick = ""
        self._hidden = False
        self._editing = False
        fields = (
            ("ipv4", "IPv4"), ("gateway", tr("Gateway")), ("dns", "DNS"), ("mac", tr("MAC address")),
            ("speed", tr("Link speed")), ("traffic", tr("Live traffic")), ("total", tr("Total usage")),
            ("dhcp", "DHCP"), ("public", tr("Public IP of this adapter")), ("latency", tr("Latency")),
            ("metric", tr("Metric")), ("ipv6", "IPv6"))

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.icon = QLabel()
        self.icon.setStyleSheet("font-size: 24px;")
        self.icon.setFixedWidth(34)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.title = ClickableLabel()
        self.title.setObjectName("CardTitle")
        self.title.setToolTip(tr("Double-click to rename"))
        self.title.doubleClicked.connect(self.start_edit)
        self.btn_edit = QPushButton("✏️")
        self.btn_edit.setObjectName("IconBtn")
        self.btn_edit.setFixedSize(28, 28)
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.setToolTip(tr("Change display name"))
        self.btn_edit.clicked.connect(self.start_edit)
        self.name_edit = NameEdit()
        self.name_edit.setObjectName("NameEdit")
        self.name_edit.setMaxLength(60)
        self.name_edit.setMinimumWidth(280)
        self.name_edit.hide()
        self.name_edit.editingFinished.connect(lambda: self._finish_edit(True))
        self.name_edit.cancelled.connect(lambda: self._finish_edit(False))
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(self.title)
        title_row.addWidget(self.btn_edit)
        title_row.addWidget(self.name_edit)
        title_row.addStretch(1)
        self.desc = QLabel()
        self.desc.setObjectName("Muted")
        self.desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        titles.addLayout(title_row)
        titles.addWidget(self.desc)
        self.spark = Sparkline()
        self.spark.setToolTip(tr("Live traffic — blue: download, green: upload"))
        self.badge = QLabel()
        self.toggle = ToggleSwitch()
        self.toggle.clicked.connect(lambda checked: self.toggleRequested.emit(self.adapter.index, checked))
        head.addWidget(self.icon)
        head.addLayout(titles, 1)
        head.addWidget(self.spark)
        head.addWidget(self.badge)
        head.addWidget(self.toggle)
        root.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        self.values: dict[str, QLabel] = {}
        for i, (key, label) in enumerate(fields):
            cell = QVBoxLayout()
            cell.setSpacing(1)
            k = QLabel(label)
            k.setObjectName("FieldKey")
            v = QLabel("—")
            v.setObjectName("FieldVal")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            cell.addWidget(k)
            cell.addWidget(v)
            self.values[key] = v
            grid.addLayout(cell, i // 4, i % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        root.addLayout(grid)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_only = QPushButton("⚡ " + tr("Only this one (disable others)"))
        self.btn_only.setObjectName("Primary")
        self.btn_only.clicked.connect(lambda: self.exclusiveRequested.emit(self.adapter.index))
        self.btn_probe = QPushButton("🌍 " + tr("Test internet"))
        self.btn_probe.setToolTip(tr("Measures latency and public IP through this adapter only"))
        self.btn_probe.clicked.connect(lambda: self.probeRequested.emit(self.adapter.index))
        self.btn_copy = QPushButton("📋 " + tr("Copy IP"))
        self.btn_copy.clicked.connect(self._copy_ip)
        self.btn_more = QPushButton("⋯ " + tr("More"))
        self.btn_more.setMenu(self._build_menu())
        for b in (self.btn_only, self.btn_probe, self.btn_copy, self.btn_more):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            actions.addWidget(b)
        actions.addStretch(1)
        root.addLayout(actions)
        self.update_from(adapter)

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        dns_menu = menu.addMenu("🧭 " + tr("Change DNS"))
        for key, label in DNS_PRESETS:
            dns_menu.addAction(tr(label)).triggered.connect(
                lambda _=False, k=key: self.dnsRequested.emit(self.adapter.index, k))
        dns_menu.addSeparator()
        dns_menu.addAction(tr("Custom …")).triggered.connect(
            lambda: self.dnsRequested.emit(self.adapter.index, "custom"))
        menu.addAction("🛠 " + tr("IP configuration (DHCP / static) …")).triggered.connect(
            lambda: self.ipConfigRequested.emit(self.adapter.index))
        self.act_renew = menu.addAction("🔁 " + tr("Renew IP (DHCP)"))
        self.act_renew.triggered.connect(lambda: self.renewRequested.emit(self.adapter.index))
        prio = menu.addMenu("⭐ " + tr("Internet priority"))
        prio.addAction(tr("Make this the preferred adapter")).triggered.connect(
            lambda: self.metricRequested.emit(self.adapter.index, "5"))
        prio.addAction(tr("Reset priority to automatic")).triggered.connect(
            lambda: self.metricRequested.emit(self.adapter.index, "auto"))
        menu.addSeparator()
        menu.addAction("✏️ " + tr("Change display name")).triggered.connect(self.start_edit)
        self.act_reset_nick = menu.addAction("↺ " + tr("Reset display name"))
        self.act_reset_nick.triggered.connect(lambda: self.renameRequested.emit(self.adapter.index, ""))
        act_os_rename = menu.addAction("🏷 " + tr("Rename in the system …"))
        act_os_rename.triggered.connect(lambda: self.winRenameRequested.emit(self.adapter.index))
        act_os_rename.setVisible(CAPS["rename"])
        self.act_hide = menu.addAction("👁 " + tr("Hide from list"))
        self.act_hide.triggered.connect(lambda: self.hideRequested.emit(self.adapter.index))
        menu.addSeparator()
        menu.addAction(tr("Copy MAC address")).triggered.connect(
            lambda: QApplication.clipboard().setText(self.adapter.mac))
        menu.addAction(tr("Copy all details")).triggered.connect(self._copy_all)
        return menu

    def _copy_ip(self) -> None:
        ip = self.adapter.primary_ip
        if ip:
            QApplication.clipboard().setText(ip)
            self.btn_copy.setText("✅ " + tr("Copied"))
            QTimer.singleShot(1200, lambda: self.btn_copy.setText("📋 " + tr("Copy IP")))

    def _copy_all(self) -> None:
        a = self.adapter
        lines = [f"Name: {a.name}", f"Description: {a.description}", f"Status: {a.status}",
                 f"MAC: {a.mac}", f"IPv4: {', '.join(a.ipv4)}", f"IPv6: {', '.join(a.ipv6)}",
                 f"Gateway: {', '.join(a.gateway)}", f"DNS: {', '.join(a.dns)}",
                 f"Link speed: {a.speed}", f"Metric: {a.metric}", f"DHCP: {a.dhcp}"]
        QApplication.clipboard().setText("\n".join(lines))

    # -- inline rename --
    def start_edit(self) -> None:
        if self._editing:
            return
        self._editing = True
        self.name_edit.setText(self._nick or self.adapter.name)
        self.name_edit.setPlaceholderText(tr("Original name: {n}", n=self.adapter.name))
        self.name_edit.setToolTip(tr("Enter = save   |   Esc = cancel   |   empty = original name"))
        self.title.hide()
        self.btn_edit.hide()
        self.name_edit.show()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _finish_edit(self, commit: bool) -> None:
        if not self._editing:
            return
        self._editing = False
        text = self.name_edit.text().strip()
        self.name_edit.hide()
        self.title.show()
        self.btn_edit.show()
        if commit:
            if text == self.adapter.name:
                text = ""
            if text != self._nick:
                self.renameRequested.emit(self.adapter.index, text)

    # -- data --
    def refresh_view(self) -> None:
        self.update_from(self.adapter, self._probe, self._testing, self._nick, self._hidden)

    def set_probe_state(self, probe: dict | None, testing: bool) -> None:
        self.update_from(self.adapter, probe, testing, self._nick, self._hidden)

    def set_rates(self, d: float, u: float) -> None:
        self.spark.push(d, u)
        if self.adapter.is_up:
            self.values["traffic"].setText(ltr(f"↓ {fmt_rate(d)}   ↑ {fmt_rate(u)}"))

    def update_from(self, a: Adapter, probe: dict | None = None, testing: bool = False,
                    nick: str = "", hidden: bool = False) -> None:
        self.adapter, self._probe, self._testing = a, probe, testing
        self._nick, self._hidden = nick, hidden
        self.icon.setText(a.icon)
        self.title.setText(nick or a.name)
        desc = f"{a.name}   •   {a.description}" if nick else a.description
        self.desc.setText(desc)
        self.desc.setToolTip(desc)
        self.act_reset_nick.setEnabled(bool(nick))
        self.act_hide.setText("👁 " + (tr("Show in list again") if hidden else tr("Hide from list")))

        label, kind = STATUS_MAP.get(a.status.lower(), (a.status, "muted"))
        c = THEME[kind]
        self.badge.setText(f"●  {tr(label)}")
        self.badge.setStyleSheet(f"background:{rgba(c, 0.16)}; color:{c}; border-radius:12px;"
                                 "padding:4px 12px; font-weight:700;")
        self.toggle.set_state(a.enabled)
        self.spark.setVisible(a.is_up)

        def join(items: list[str], limit: int = 2) -> str:
            shown = ", ".join(items[:limit])
            if len(items) > limit:
                shown += f" (+{len(items) - limit})"
            return ltr(shown)

        v = self.values
        v["ipv4"].setText(join(a.ipv4))
        v["ipv6"].setText(join(a.ipv6, 1))
        v["gateway"].setText(join(a.gateway))
        v["dns"].setText(join(a.dns, 3))
        v["mac"].setText(ltr(a.mac))
        v["speed"].setText(ltr(a.speed))
        auto = (tr("auto") if a.auto_metric == "Enabled" else tr("manual")) if a.auto_metric else ""
        v["metric"].setText(ltr(a.metric) + (f"  ({auto})" if a.metric and auto else ""))
        v["dhcp"].setText({"Enabled": tr("Enabled"), "Disabled": tr("Disabled")}.get(a.dhcp, "—"))
        if not a.is_up:
            v["traffic"].setText("—")
        v["total"].setText(ltr(f"↓ {fmt_bytes(a.rx)}   ↑ {fmt_bytes(a.tx)}") if (a.rx or a.tx) else "—")

        lat, pub = v["latency"], v["public"]
        lat.setStyleSheet("")
        pub.setStyleSheet("")
        pub.setToolTip("")
        if testing:
            pub.setText("⏳ " + tr("Testing …"))
            lat.setText("⏳")
        elif probe and probe.get("latency") is not None:
            ms = probe["latency"]
            col = THEME["ok"] if ms < 60 else THEME["warn"] if ms < 150 else THEME["danger"]
            lat.setText(ltr(f"{ms:.0f} ms"))
            lat.setStyleSheet(f"color:{col}; font-weight:700;")
            info = probe.get("pub")
            if info:
                cc = f" • {info['cc']}" if info.get("cc") else ""
                pub.setText(ltr(f"{info['ip']}{cc}"))
                pub.setToolTip("  •  ".join(x for x in (info.get("country"), info.get("city"), info.get("isp")) if x))
            else:
                pub.setText(tr("Unknown"))
        elif probe:
            pub.setText("❌ " + tr("No internet"))
            pub.setStyleSheet(f"color:{THEME['danger']}; font-weight:700;")
            lat.setText("—")
        else:
            pub.setText("—")
            lat.setText("—")

        self.btn_probe.setEnabled(a.is_up and bool(a.primary_ip) and not testing)
        self.btn_copy.setEnabled(bool(a.primary_ip))
        self.act_renew.setEnabled(a.enabled and a.dhcp == "Enabled")
        self.setEnabled(not testing)
        off = not a.enabled
        if self.property("off") != off:
            self.setProperty("off", off)
            self.style().unpolish(self)
            self.style().polish(self)

    def matches(self, query: str) -> bool:
        a = self.adapter
        blob = " ".join([self._nick, a.name, a.description, a.mac, *a.ipv4, *a.gateway, *a.dns]).lower()
        return query.lower() in blob


# ----------------------------------------------------------------------------
# Pages: Toolbox
# ----------------------------------------------------------------------------
def make_table(headers: list[str], fit: bool = True) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    if fit:   # small tables: columns share the width evenly
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    else:     # long tables: size to content, last column fills the rest
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    t.setLayoutDirection(Qt.LayoutDirection.LeftToRight if LANG == "en" else Qt.LayoutDirection.RightToLeft)
    return t


def set_cell(table: QTableWidget, row: int, col: int, text: str, color: str | None = None) -> None:
    item = table.item(row, col)
    if item is None:
        item = QTableWidgetItem()
        table.setItem(row, col, item)
    item.setText(text)
    item.setForeground(QColor(color) if color else QColor(THEME["text"]))


class ConsoleView(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Console")
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setMinimumHeight(220)


class ToolTab(QWidget):
    """Generic tool: a few input fields, Run/Stop, and a console with streamed output."""

    def __init__(self, win, description: str, fields: list[dict], job, parent: QWidget | None = None):
        super().__init__(parent)
        self.win, self.job = win, job
        self.task: Task | None = None
        self.log_name = "Tool"          # set by ToolboxPage (used in the Operation Log)
        self._failed = False
        self.inputs: dict[str, QWidget] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        d = QLabel(description)
        d.setObjectName("Muted")
        d.setWordWrap(True)
        lay.addWidget(d)
        row = QHBoxLayout()
        row.setSpacing(10)
        for f in fields:
            box = QVBoxLayout()
            box.setSpacing(3)
            cap = QLabel(f["label"])
            cap.setObjectName("FieldKey")
            kind = f.get("kind", "text")
            if kind == "int":
                w = QSpinBox()
                w.setRange(f.get("min", 0), f.get("max", 9999))
                w.setValue(f.get("default", 0))
                if f.get("special"):
                    w.setSpecialValueText(f["special"])
                w.setFixedWidth(110)
            elif kind == "combo":
                w = QComboBox()
                w.addItems(f["options"])
                w.setMinimumWidth(320)
            else:
                w = QLineEdit(f.get("default", ""))
                w.setPlaceholderText(f.get("placeholder", ""))
                w.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                w.setMinimumWidth(f.get("width", 240))
                w.returnPressed.connect(self.toggle)
            self.inputs[f["key"]] = w
            box.addWidget(cap)
            box.addWidget(w)
            row.addLayout(box)
        self.btn_run = QPushButton("▶ " + tr("Run"))
        self.btn_run.setObjectName("Primary")
        self.btn_run.clicked.connect(self.toggle)
        self.btn_copy = QPushButton(tr("Copy output"))
        self.btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.console.toPlainText()))
        self.btn_clear = QPushButton(tr("Clear"))
        self.btn_clear.clicked.connect(lambda: self.console.clear())
        row.addStretch(1)
        btn_col = QVBoxLayout()
        btn_col.addStretch(1)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_run)
        btns.addWidget(self.btn_copy)
        btns.addWidget(self.btn_clear)
        btn_col.addLayout(btns)
        row.addLayout(btn_col)
        lay.addLayout(row)
        self.console = ConsoleView()
        lay.addWidget(self.console, 1)

    def values(self) -> dict:
        out = {}
        for k, w in self.inputs.items():
            if isinstance(w, QLineEdit):
                out[k] = w.text()
            elif isinstance(w, QSpinBox):
                out[k] = w.value()
            elif isinstance(w, QComboBox):
                out[k] = w.currentIndex()
        return out

    def toggle(self) -> None:
        if self.task and self.task.isRunning():
            self.task.stop()
            return
        self.start()

    def start(self) -> None:
        vals = self.values()
        self.console.clear()
        self._failed = False
        detail = ", ".join(str(v) for v in vals.values() if isinstance(v, str) and v.strip())
        OPLOG.info(tr("Toolbox · {t}: started", t=tr(self.log_name)) + (f" ({detail})" if detail else ""))
        self.task = Task(lambda t, v=vals: self.job(t, v), self)
        self.task.message.connect(self._on_msg)
        self.task.failed.connect(self._on_failed)
        self.task.finished.connect(self._on_finished)
        self.btn_run.setText("■ " + tr("Stop"))
        self.btn_run.setObjectName("Danger")
        self.btn_run.style().unpolish(self.btn_run)
        self.btn_run.style().polish(self.btn_run)
        self.task.start()

    def _on_msg(self, payload) -> None:
        if isinstance(payload, str):
            self.console.appendPlainText(payload)

    def _on_failed(self, msg: str) -> None:
        self._failed = True
        self.console.appendPlainText("✘ " + msg)
        OPLOG.error(tr("Toolbox · {t}: {e}", t=tr(self.log_name), e=msg))

    def _on_finished(self) -> None:
        self.btn_run.setText("▶ " + tr("Run"))
        self.btn_run.setObjectName("Primary")
        self.btn_run.style().unpolish(self.btn_run)
        self.btn_run.style().polish(self.btn_run)
        if self._failed:
            return
        if self.task is not None and self.task.stopped():
            OPLOG.warn(tr("Toolbox · {t}: stopped by user.", t=tr(self.log_name)))
        else:
            OPLOG.ok(tr("Toolbox · {t}: finished.", t=tr(self.log_name)))

    def shutdown(self) -> None:
        if self.task and self.task.isRunning():
            self.task.stop()
            self.task.wait(1500)


class RepairTab(QWidget):
    """One-click network repair commands with a live console."""

    ACTIONS = BACKEND.repair_actions()

    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        self.task: Task | None = None
        self._failed, self._title = False, ""
        self.log_name = "Repair"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        d = QLabel(tr("Fix common network problems. Reset actions need a restart to take full effect."))
        d.setObjectName("Muted")
        d.setWordWrap(True)
        lay.addWidget(d)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.buttons: list[QPushButton] = []
        for i, (glyph, title, desc, cmd, danger) in enumerate(self.ACTIONS):
            b = QPushButton(f"{glyph}  {tr(title)}")
            b.setToolTip(tr(desc))
            b.setMinimumHeight(40)
            if danger:
                b.setObjectName("Danger")
            b.clicked.connect(lambda _=False, c=cmd, t=title, dg=danger: self.run(c, t, dg))
            grid.addWidget(b, i // 3, i % 3)
            self.buttons.append(b)
        lay.addLayout(grid)
        self.console = ConsoleView()
        lay.addWidget(self.console, 1)

    def run(self, cmd: list[str], title: str, danger: bool) -> None:
        if self.task and self.task.isRunning():
            return
        if not self.win.admin:
            self.win._info(tr("Administrator rights are required for this action."))
            return
        if danger and not self.win._confirm(tr("“{t}” changes core network settings and needs a restart. Continue?", t=tr(title))):
            return
        self.console.clear()
        self.console.appendPlainText("> " + " ".join(cmd))
        self._failed, self._title = False, tr(title)
        OPLOG.info(tr("Repair · {t}: started", t=self._title))
        self.task = Task(lambda t, c=cmd: stream_command(t, priv_wrap(c)), self)
        self.task.message.connect(self._on_msg)
        self.task.failed.connect(self._on_failed)
        self.task.finished.connect(self._done)
        for b in self.buttons:
            b.setEnabled(False)
        self.task.start()

    def _on_msg(self, payload) -> None:
        if isinstance(payload, str):
            self.console.appendPlainText(payload)

    def _on_failed(self, msg: str) -> None:
        self._failed = True
        self.console.appendPlainText("✘ " + msg)
        OPLOG.error(tr("Repair · {t}: {e}", t=self._title, e=msg))

    def _done(self) -> None:
        for b in self.buttons:
            b.setEnabled(True)
        self.console.appendPlainText("✔ " + tr("Finished."))
        if not self._failed:
            OPLOG.ok(tr("Repair · {t}: finished.", t=self._title))

    def shutdown(self) -> None:
        if self.task and self.task.isRunning():
            self.task.stop()
            self.task.wait(1500)


class DnsBenchTab(QWidget):
    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        self.task: Task | None = None
        self.rows: list[dict] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        d = QLabel(tr("Measures how fast popular DNS servers (and your current ones) answer. "
                      "Lower is better. Results reflect cached answers, which is what you feel day to day."))
        d.setObjectName("Muted")
        d.setWordWrap(True)
        lay.addWidget(d)
        row = QHBoxLayout()
        self.btn_run = QPushButton("▶ " + tr("Run benchmark"))
        self.btn_run.setObjectName("Primary")
        self.btn_run.clicked.connect(self.toggle)
        self.progress = QLabel("")
        self.progress.setObjectName("Muted")
        row.addWidget(self.btn_run)
        row.addWidget(self.progress, 1)
        self.target = QComboBox()
        self.target.setMinimumWidth(220)
        self.btn_apply = QPushButton("⚡ " + tr("Apply fastest to adapter"))
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.apply_fastest)
        row.addWidget(self.target)
        row.addWidget(self.btn_apply)
        lay.addLayout(row)
        self.table = make_table([tr("Server"), tr("Address"), tr("Median"), tr("Replies"), ""])
        lay.addWidget(self.table, 1)

    def refresh_targets(self) -> None:
        cur = self.target.currentData()
        self.target.clear()
        for a in self.win.adapters:
            if a.enabled and self.win._is_listed(a):
                self.target.addItem(self.win.display_name(a), a.index)
        i = self.target.findData(cur)
        if i >= 0:
            self.target.setCurrentIndex(i)

    def toggle(self) -> None:
        if self.task and self.task.isRunning():
            self.task.stop()
            return
        extra = []
        for a in self.win.adapters:
            if a.is_up:
                for ip in a.dns:
                    extra.append((tr("Current ({n})", n=self.win.display_name(a)), ip))
        self.rows.clear()
        self._render()
        self.refresh_targets()
        self.btn_apply.setEnabled(False)
        self.progress.setText("⏳ " + tr("Testing …"))
        OPLOG.info(tr("Toolbox · {t}: started", t=tr("DNS benchmark")))
        self.task = Task(lambda t, e=extra: job_dns_bench(t, e), self)
        self.task.message.connect(self._on_msg)
        self.task.failed.connect(lambda m: self.progress.setText("✘ " + m))
        self.task.finished.connect(self._done)
        self.btn_run.setText("■ " + tr("Stop"))
        self.task.start()

    def _on_msg(self, payload) -> None:
        if isinstance(payload, tuple) and payload[0] == "row":
            self.rows.append(payload[1])
            self._render()

    def _done(self) -> None:
        self.btn_run.setText("▶ " + tr("Run benchmark"))
        good = [r for r in self.rows if r["median"] is not None]
        if good:
            best = min(good, key=lambda r: r["median"])
            self.progress.setText("🏆 " + tr("Fastest: {n} ({ip}) — {ms:.0f} ms", n=best["label"], ip=best["ip"], ms=best["median"]))
            self.btn_apply.setEnabled(self.target.count() > 0 and self.win.admin)
            OPLOG.ok(tr("Fastest: {n} ({ip}) — {ms:.0f} ms", n=best["label"], ip=best["ip"], ms=best["median"]))
        else:
            self.progress.setText("❌ " + tr("No DNS server answered."))
            OPLOG.warn(tr("No DNS server answered."))

    def _render(self) -> None:
        rows = sorted(self.rows, key=lambda r: (r["median"] is None, r["median"] or 0))
        good = [r["median"] for r in rows if r["median"] is not None]
        worst = max(good) if good else 1
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            m = r["median"]
            col = None if m is None else THEME["ok"] if m < 40 else THEME["warn"] if m < 100 else THEME["danger"]
            set_cell(self.table, i, 0, r["label"])
            set_cell(self.table, i, 1, r["ip"])
            set_cell(self.table, i, 2, "—" if m is None else f"{m:.0f} ms", col)
            set_cell(self.table, i, 3, f"{r['ok']}/{r['total']}")
            bar = "" if m is None else "█" * max(1, int(18 * (1 - m / (worst * 1.15))) + 1)
            set_cell(self.table, i, 4, bar, col)

    def apply_fastest(self) -> None:
        good = [r for r in self.rows if r["median"] is not None]
        idx = self.target.currentData()
        if not good or idx is None:
            return
        best = min(good, key=lambda r: r["median"])
        servers = best["ip"]
        for key, _label in DNS_PRESETS:
            if key.split(",")[0] == best["ip"]:
                servers = key
                break
        self.win.on_dns(idx, servers)

    def shutdown(self) -> None:
        if self.task and self.task.isRunning():
            self.task.stop()
            self.task.wait(1500)


class ConnectionsTab(QWidget):
    STATES = [("Established", "est"), ("Listening", "listen"), ("All", "all")]

    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        self.data: list[dict] = []
        self._loaded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        d = QLabel(tr("Active TCP connections and the programs that own them. Right-click a row to look up the remote IP."))
        d.setObjectName("Muted")
        d.setWordWrap(True)
        lay.addWidget(d)
        row = QHBoxLayout()
        self.state = QComboBox()
        for label, _ in self.STATES:
            self.state.addItem(tr(label))
        self.state.currentIndexChanged.connect(self.load)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("🔍 " + tr("Filter by program, port or address …"))
        self.filter.textChanged.connect(self._render)
        self.btn = QPushButton("🔄 " + tr("Refresh"))
        self.btn.clicked.connect(self.load)
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        row.addWidget(self.state)
        row.addWidget(self.filter, 1)
        row.addWidget(self.count)
        row.addWidget(self.btn)
        lay.addLayout(row)
        self.table = make_table([tr("Program"), "PID", tr("Local address"), tr("Remote address"), tr("State")], fit=False)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.load()

    def load(self) -> None:
        self.btn.setEnabled(False)
        self.count.setText("⏳")
        states = self.STATES[self.state.currentIndex()][1]
        self.win._run(fetch_connections, self._on_data, states)

    def _on_data(self, ok: bool, payload) -> None:
        self.btn.setEnabled(True)
        if not ok:
            self.count.setText("❌")
            self.win.set_status("❌ " + str(payload))
            return
        self.data = payload
        self._render()

    def _render(self) -> None:
        q = self.filter.text().strip().lower()
        rows = [r for r in self.data if not q or q in f"{r.get('P','')} {r.get('Pid','')} {r.get('L','')} {r.get('R','')} {r.get('S','')}".lower()]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            set_cell(self.table, i, 0, str(r.get("P") or "?"))
            item = QTableWidgetItem()
            item.setData(Qt.ItemDataRole.DisplayRole, int(r.get("Pid", 0)))
            self.table.setItem(i, 1, item)
            set_cell(self.table, i, 2, str(r.get("L", "")))
            set_cell(self.table, i, 3, str(r.get("R", "")))
            set_cell(self.table, i, 4, str(r.get("S", "")))
        self.table.setSortingEnabled(True)
        self.count.setText(tr("{n} connections", n=len(rows)))

    def _menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        remote = self.table.item(row, 3).text()
        host = remote.rsplit(":", 1)[0]
        m = QMenu(self)
        a1 = m.addAction(tr("Copy remote address"))
        a2 = m.addAction("🔎 " + tr("Look up remote IP"))
        a2.setEnabled(host not in ("0.0.0.0", "::", "127.0.0.1", "::1", ""))
        chosen = m.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is a1:
            QApplication.clipboard().setText(remote)
        elif chosen is a2:
            self.win.page_tools.lookup_ip(host)


class ToolboxPage(QWidget):
    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(page_header("🧰 " + tr("Network toolbox"),
                                  tr("Diagnostics and repair tools — everything you need in one place.")))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.t_ping = ToolTab(win, tr("Sends echo requests to a host and shows the round-trip time. Set count to ∞ for continuous ping."),
                              [{"key": "host", "label": tr("Host or IP"), "default": "1.1.1.1"},
                               {"key": "count", "label": tr("Count"), "kind": "int", "default": 4, "min": 0, "max": 1000, "special": "∞"}],
                              job_ping)
        self.t_trace = ToolTab(win, tr("Shows every router between you and the destination."),
                               [{"key": "host", "label": tr("Host or IP"), "default": "google.com"}], job_tracert)
        self.t_dns = ToolTab(win, tr("Resolves a name using the system resolver or a DNS server of your choice."),
                             [{"key": "host", "label": tr("Domain name"), "default": "github.com"},
                              {"key": "server", "label": tr("DNS server (optional)"), "default": "", "placeholder": "1.1.1.1", "width": 180}],
                             job_nslookup)
        self.t_ports = ToolTab(win, tr("Checks whether TCP ports are reachable. Use commas and ranges, e.g. 22,80,443,8000-8010."),
                               [{"key": "host", "label": tr("Host or IP"), "default": "example.com"},
                                {"key": "ports", "label": tr("Ports"), "default": "80,443", "width": 220}], job_ports)
        self.t_ip = ToolTab(win, tr("Looks up country, city and provider for any IP address or domain. Leave empty for your own IP."),
                            [{"key": "query", "label": tr("IP or domain (optional)"), "default": "", "placeholder": "8.8.8.8"}],
                            job_iplookup)
        self.t_dnsb = DnsBenchTab(win)
        self.t_conn = ConnectionsTab(win)
        self.t_quick = ToolTab(win, tr("Runs a built-in diagnostic command of your operating system and shows its output."),
                               [{"key": "cmd", "label": tr("Command"), "kind": "combo", "options": [c[0] for c in QUICK_COMMANDS]}],
                               job_quick)
        self.t_repair = RepairTab(win)
        for w, name in ((self.t_ping, "Ping"), (self.t_trace, "Traceroute"), (self.t_dns, "DNS lookup"),
                        (self.t_ports, "Port check"), (self.t_ip, "IP lookup"), (self.t_dnsb, "DNS benchmark"),
                        (self.t_conn, "Connections"), (self.t_quick, "System info"), (self.t_repair, "Repair")):
            w.log_name = name
            self.tabs.addTab(w, tr(name))
        lay.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(lambda _: fade_in(self.tabs.currentWidget(), 200))

    def lookup_ip(self, ip: str) -> None:
        self.tabs.setCurrentWidget(self.t_ip)
        self.t_ip.inputs["query"].setText(ip)
        self.t_ip.start()

    def on_adapters_changed(self) -> None:
        self.t_dnsb.refresh_targets()

    def shutdown(self) -> None:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "shutdown"):
                w.shutdown()


# ----------------------------------------------------------------------------
# Pages: Monitor, Speed test
# ----------------------------------------------------------------------------
class MonitorPage(QWidget):
    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        self._sig: tuple = ()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        top = QHBoxLayout()
        top.addWidget(page_header("📈 " + tr("Live traffic monitor"),
                                  tr("Real-time download and upload speed of every adapter.")), 1)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        self.combo.currentIndexChanged.connect(self.tick)
        top.addWidget(self.combo)
        lay.addLayout(top)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.t_down = Tile("↓ " + tr("Download"))
        self.t_up = Tile("↑ " + tr("Upload"))
        self.t_peak = Tile(tr("Peak download (last {n} s)", n=120))
        for t in (self.t_down, self.t_up, self.t_peak):
            tiles.addWidget(t, 1)
        lay.addLayout(tiles)

        # total internet usage (survives adapters being disabled / re-enabled / reset)
        usage = QHBoxLayout()
        usage.setSpacing(12)
        self.u_session = Tile("📊 " + tr("Internet used since the app started"))
        self.u_all = Tile("💾 " + tr("Total usage (saved)"))
        usage.addWidget(self.u_session, 1)
        usage.addWidget(self.u_all, 1)
        ctl, cl = panel(margins=(14, 10, 14, 10), spacing=6)
        self.chk_virt = QCheckBox(tr("Include virtual / VPN adapters"))
        self.chk_virt.setToolTip(tr("VPN traffic is already counted on the physical adapter that carries it, "
                                    "so this is off by default to avoid counting it twice."))
        self.chk_virt.setChecked(PREFS.get("usage_include_virtual"))
        self.chk_virt.toggled.connect(win.on_usage_virtual)
        self.btn_reset_usage = QPushButton("🗑 " + tr("Reset saved total"))
        self.btn_reset_usage.setObjectName("Danger")
        self.btn_reset_usage.clicked.connect(win.reset_usage_total)
        cl.addWidget(self.chk_virt)
        cl.addWidget(self.btn_reset_usage)
        usage.addWidget(ctl)
        lay.addLayout(usage)
        f, fl = panel(margins=(14, 14, 14, 10))
        legend = QLabel(f"<span style='color:{THEME['accent']}'>●</span> {tr('Download')}  &nbsp;&nbsp; "
                        f"<span style='color:{THEME['ok']}'>●</span> {tr('Upload')}")
        legend.setObjectName("Muted")
        legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend = legend
        fl.addWidget(legend)
        self.chart = BandwidthChart(120)
        fl.addWidget(self.chart, 1)
        lay.addWidget(f, 1)
        self.table = make_table([tr("Adapter"), "↓ " + tr("Download"), "↑ " + tr("Upload"),
                                 tr("Session") + " ↓", tr("Session") + " ↑"])
        self.table.setMaximumHeight(190)
        lay.addWidget(self.table)

    def update_usage(self) -> None:
        n = self.win.usage_numbers()
        self.u_session.set(f"↓ {fmt_bytes(n['s_rx'])}   ↑ {fmt_bytes(n['s_tx'])}")
        self.u_session.set_sub(tr("Total: {t}", t=ltr(fmt_bytes(n["s_rx"] + n["s_tx"]))))
        self.u_all.set(f"↓ {fmt_bytes(n['a_rx'])}   ↑ {fmt_bytes(n['a_tx'])}")
        self.u_all.set_caption("💾 " + tr("Total usage since {d}", d=ltr(n["since"])))
        self.u_all.set_sub(tr("Total: {t}", t=ltr(fmt_bytes(n["a_rx"] + n["a_tx"]))))

    def refresh_combo(self) -> None:
        names = tuple((a.index, self.win.display_name(a)) for a in self.win.adapters)
        if names == self._sig:
            return
        self._sig = names
        cur = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(tr("All adapters"), -1)
        for idx, name in names:
            self.combo.addItem(name, idx)
        i = self.combo.findData(cur)
        self.combo.setCurrentIndex(i if i >= 0 else 0)
        self.combo.blockSignals(False)

    def tick(self, *_a) -> None:
        w = self.win
        sel = self.combo.currentData()
        sel = -1 if sel is None else sel
        hist = list(w.total_hist) if sel == -1 else list(w.hist.get(sel, []))
        down, up = [h[0] for h in hist], [h[1] for h in hist]
        self.chart.set_data(down, up)
        cd, cu = (down[-1], up[-1]) if hist else (0.0, 0.0)
        self.t_down.set(fmt_rate(cd), THEME["accent"])
        self.t_up.set(fmt_rate(cu), THEME["ok"])
        self.t_peak.set(fmt_rate(max(down)) if down else "—")
        self.update_usage()
        ups = [a for a in w.adapters if a.is_up]
        self.table.setRowCount(len(ups))
        for i, a in enumerate(ups):
            d, u = w.rates.get(a.index, (0.0, 0.0))
            s = w.session.get(a.index, (0, 0))
            set_cell(self.table, i, 0, w.display_name(a))
            set_cell(self.table, i, 1, fmt_rate(d), THEME["accent"])
            set_cell(self.table, i, 2, fmt_rate(u), THEME["ok"])
            set_cell(self.table, i, 3, fmt_bytes(s[0]))
            set_cell(self.table, i, 4, fmt_bytes(s[1]))


class SpeedPage(QWidget):
    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        self.task: Task | None = None
        self.phase = ""
        self._sig: tuple = ()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(page_header("🚀 " + tr("Speed test"),
                                  tr("Measures latency, download and upload — optionally through one specific adapter.")))
        mid = QHBoxLayout()
        mid.setSpacing(14)
        f, fl = panel(margins=(18, 16, 18, 16), spacing=12)
        self.gauge = GaugeWidget()
        fl.addWidget(self.gauge, 1)
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        row.addWidget(self.combo, 1)
        self.btn = QPushButton("▶ " + tr("Start test"))
        self.btn.setObjectName("Primary")
        self.btn.setMinimumWidth(140)
        self.btn.clicked.connect(self.toggle)
        row.addWidget(self.btn)
        fl.addLayout(row)
        mid.addWidget(f, 3)
        right = QVBoxLayout()
        right.setSpacing(12)
        self.t_ping = Tile(tr("Ping"))
        self.t_jit = Tile(tr("Jitter"))
        self.t_down = Tile("↓ " + tr("Download"))
        self.t_up = Tile("↑ " + tr("Upload"))
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, t in enumerate((self.t_ping, self.t_jit, self.t_down, self.t_up)):
            grid.addWidget(t, i // 2, i % 2)
        right.addLayout(grid)
        self.note = QLabel(tr("Uses Cloudflare's public speed endpoints. A test transfers roughly 50–150 MB."))
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        right.addWidget(self.note)
        right.addStretch(1)
        mid.addLayout(right, 2)
        lay.addLayout(mid, 1)
        lay.addWidget(QLabel(tr("History")))
        self.table = make_table([tr("Time"), tr("Adapter"), tr("Ping"), "↓ " + tr("Download"), "↑ " + tr("Upload")])
        self.table.setMaximumHeight(170)
        lay.addWidget(self.table)
        self.gauge.set_caption(tr("Ready"))
        self._load_history()

    def refresh_adapters(self) -> None:
        ups = [a for a in self.win.adapters if a.is_up and a.primary_ip]
        sig = tuple((a.index, a.primary_ip, self.win.display_name(a)) for a in ups)
        if sig == self._sig:
            return
        self._sig = sig
        cur = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("🌐 " + tr("Automatic (system default route)"), "")
        for a in ups:
            self.combo.addItem(f"{a.icon} {self.win.display_name(a)} — {a.primary_ip}", f"{a.primary_ip}|{a.device}")
        i = self.combo.findData(cur)
        self.combo.setCurrentIndex(i if i >= 0 else 0)
        self.combo.blockSignals(False)

    def toggle(self) -> None:
        if self.task and self.task.isRunning():
            self.task.stop()
            return
        data = self.combo.currentData() or ""
        src = tuple(data.split("|", 1)) if data else None
        self.gauge.reset()
        for t in (self.t_ping, self.t_jit, self.t_down, self.t_up):
            t.set("—")
        self.task = Task(lambda t, s=src: speed_test_job(t, s), self)
        self.task.message.connect(self._on_msg)
        self.task.failed.connect(self._on_failed)
        self.task.finished.connect(self._done)
        self.btn.setText("■ " + tr("Stop"))
        self.btn.setObjectName("Danger")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)
        self.combo.setEnabled(False)
        self._src_label = self.combo.currentText()
        OPLOG.info(tr("Speed test started ({a}).", a=self._src_label.replace("🌐 ", "")))
        self.task.start()

    def _on_msg(self, p) -> None:
        if not isinstance(p, tuple):
            return
        kind = p[0]
        if kind == "phase":
            self.phase = p[1]
            self.gauge.reset()
            self.gauge.set_caption({"ping": tr("Measuring latency …"), "download": tr("Download"),
                                    "upload": tr("Upload")}[p[1]])
        elif kind == "ping":
            self.t_ping.set(f"{p[1]:.0f} ms", THEME["ok"] if p[1] < 60 else THEME["warn"])
            self.t_jit.set(f"{p[2]:.1f} ms")
        elif kind == "value":
            self.gauge.set_value(p[1])
        elif kind == "value_done":
            tile = self.t_down if self.phase == "download" else self.t_up
            tile.set(f"{p[1]:.1f} Mbps", THEME["accent"] if self.phase == "download" else THEME["ok"])
            self.gauge.set_value(p[1])
        elif kind == "result":
            self.gauge.set_caption("✔ " + tr("Done"))
            self._save_history(p[1])
            r = p[1]
            OPLOG.ok(tr("Speed test finished: ping {p} ms · download {d} Mbps · upload {u} Mbps",
                        p=f"{r['ping']:.0f}" if r.get("ping") is not None else "—",
                        d=f"{r['down']:.1f}" if r.get("down") is not None else "—",
                        u=f"{r['up']:.1f}" if r.get("up") else "—"))

    def _on_failed(self, msg: str) -> None:
        self.gauge.set_caption("✘ " + tr("Failed"))
        self.win.set_status("❌ " + tr("Speed test failed: {e}", e=msg))

    def _done(self) -> None:
        self.btn.setText("▶ " + tr("Start test"))
        self.btn.setObjectName("Primary")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)
        self.combo.setEnabled(True)
        if self.gauge._caption not in ("✔ " + tr("Done"), "✘ " + tr("Failed")):
            self.gauge.set_caption(tr("Stopped"))
            OPLOG.warn(tr("Speed test stopped."))

    def _save_history(self, r: dict) -> None:
        hist = PREFS.get_json("speed_history", [])
        hist.insert(0, {"t": time.strftime("%Y-%m-%d %H:%M"), "a": getattr(self, "_src_label", ""),
                        "ping": r.get("ping"), "down": r.get("down"), "up": r.get("up")})
        PREFS.set_json("speed_history", hist[:12])
        self._load_history()

    def _load_history(self) -> None:
        hist = PREFS.get_json("speed_history", [])
        self.table.setRowCount(len(hist))
        for i, h in enumerate(hist):
            set_cell(self.table, i, 0, h.get("t", ""))
            set_cell(self.table, i, 1, h.get("a", ""))
            set_cell(self.table, i, 2, "—" if h.get("ping") is None else f"{h['ping']:.0f} ms")
            set_cell(self.table, i, 3, "—" if h.get("down") is None else f"{h['down']:.1f} Mbps", THEME["accent"])
            set_cell(self.table, i, 4, "—" if not h.get("up") else f"{h['up']:.1f} Mbps", THEME["ok"])

    def shutdown(self) -> None:
        if self.task and self.task.isRunning():
            self.task.stop()
            self.task.wait(2000)


# ----------------------------------------------------------------------------
# Page: Operation Log
# ----------------------------------------------------------------------------
class LogPage(QWidget):
    """Timeline of everything the app did and what happened, with filter / copy / save / clear
    and an optional timestamped log file."""
    FILTERS = (("All", None), ("Info", ("INFO",)), ("Success", ("SUCCESS",)),
               ("Warnings", ("WARNING",)), ("Errors", ("ERROR",)))
    TAGS = {"INFO": "INFO&nbsp;&nbsp;&nbsp;", "SUCCESS": "SUCCESS", "WARNING": "WARNING", "ERROR": "ERROR&nbsp;&nbsp;"}

    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        self._shown = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(page_header("📝 " + tr("Operation Log"),
                                  tr("A timeline of everything NIC Switcher did and what happened.")))

        bar, bl = panel(QHBoxLayout, margins=(14, 10, 14, 10), spacing=8)
        self.filter = QComboBox()
        for name, _levels in self.FILTERS:
            self.filter.addItem(tr(name))
        self.filter.activated.connect(lambda _=0: self._render())
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        bl.addWidget(self.filter)
        bl.addWidget(self.count, 1)
        for text, fn, name in (("📋 " + tr("Copy"), self.copy_all, ""),
                               ("💾 " + tr("Save as …"), self.save_as, ""),
                               ("🗑 " + tr("Clear"), self.clear_log, "Danger")):
            b = QPushButton(text)
            if name:
                b.setObjectName(name)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            bl.addWidget(b)
        lay.addWidget(bar)

        self.view = QPlainTextEdit()
        self.view.setObjectName("Console")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(OperationLog.MAX_ENTRIES)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.view.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        lay.addWidget(self.view, 1)

        foot, fl = panel(QHBoxLayout, margins=(14, 10, 14, 10), spacing=12)
        self.file_switch = ToggleSwitch()
        self.file_switch.set_state(PREFS.get("file_logging"))
        self.file_switch.toggled.connect(OPLOG.set_file_logging)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(tr("Save log to file"))
        t.setObjectName("CardTitle")
        self.file_hint = QLabel("")
        self.file_hint.setObjectName("Muted")
        self.file_hint.setWordWrap(True)
        self.file_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(t)
        col.addWidget(self.file_hint)
        self.btn_folder = QPushButton("📂 " + tr("Open log folder"))
        self.btn_folder.clicked.connect(self.open_folder)
        fl.addWidget(self.file_switch)
        fl.addLayout(col, 1)
        fl.addWidget(self.btn_folder)
        lay.addWidget(foot)

        OPLOG.entryAdded.connect(self._on_entry)
        OPLOG.cleared.connect(self._render)
        OPLOG.fileLoggingChanged.connect(self._sync_file)
        self._sync_file(PREFS.get("file_logging"))
        self._render()

    # -- helpers
    def _levels(self):
        return self.FILTERS[max(0, self.filter.currentIndex())][1]

    def _line(self, stamp: str, level: str, msg: str) -> str:
        colors = {"INFO": THEME["muted"], "SUCCESS": THEME["ok"], "WARNING": THEME["warn"], "ERROR": THEME["danger"]}
        c = colors.get(level, THEME["muted"])
        line = (f"<span style='color:{THEME['muted']}'>{stamp[11:]}</span>&nbsp;&nbsp;"
                f"<b style='color:{c}'>{self.TAGS.get(level, level)}</b>&nbsp;&nbsp;"
                f"<span style='color:{THEME['text']}'>{html_escape(msg)}</span>")
        return f"<div dir='rtl'>{line}</div>" if LANG == "fa" else line

    def _update_count(self, shown: int) -> None:
        total = len(OPLOG.entries)
        self.count.setText(tr("{n} entries", n=total) if shown == total else tr("{n} of {t} entries", n=shown, t=total))

    def _render(self) -> None:
        levels = self._levels()
        self.view.setUpdatesEnabled(False)
        self.view.clear()
        shown = 0
        for stamp, level, msg in OPLOG.snapshot():
            if levels is None or level in levels:
                self.view.appendHtml(self._line(stamp, level, msg))
                shown += 1
        self.view.setUpdatesEnabled(True)
        self._shown = shown
        self._update_count(shown)
        self.scroll_end()

    def _on_entry(self, stamp: str, level: str, msg: str) -> None:
        levels = self._levels()
        if levels is None or level in levels:
            self.view.appendHtml(self._line(stamp, level, msg))
            self.scroll_end()
        self._shown += 1
        self._update_count(self._shown)

    def scroll_end(self) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _sync_file(self, enabled: bool) -> None:
        self.file_switch.set_state(enabled)
        self.btn_folder.setEnabled(enabled)
        self.file_hint.setText(ltr(OPLOG.path()) if enabled else
                               tr("Off — entries are kept for this session only. Turn on to keep a permanent timestamped log file."))

    # -- actions
    def copy_all(self) -> None:
        QApplication.clipboard().setText(OPLOG.as_text(self._levels()))
        self.win.set_status("✅ " + tr("Log copied to clipboard."), log=False)

    def save_as(self) -> None:
        default = f"nicswitcher-log-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, tr("Save as …"), default, "Text (*.txt);;Log (*.log)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(OPLOG.as_text(self._levels()) + "\n")
        except OSError as e:
            OPLOG.error(tr("Could not write the log file: {e}", e=e))
            self.win._info(str(e), QMessageBox.Icon.Critical)
            return
        OPLOG.ok(tr("Log saved to {p}", p=path))

    def clear_log(self) -> None:
        OPLOG.clear()
        OPLOG.info(tr("Log cleared."))

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(OPLOG.path())))

    def retheme(self) -> None:
        self._render()


# ----------------------------------------------------------------------------
# Pages: Settings, About
# ----------------------------------------------------------------------------
def separator() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{THEME['border']}; border:none;")
    return f


class SettingsPage(QWidget):
    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        self.swatches: list[QPushButton] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        outer.addWidget(page_header("⚙️ " + tr("Settings"), tr("Customize the look and behavior of the app.")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 4, 8, 4)
        il.setSpacing(14)

        # --- appearance
        box, bl = panel()
        bl.addWidget(self._title("🎨 " + tr("Appearance")))
        self.lang = QComboBox()
        for code, name in LANGS.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(self.lang.findData(LANG))
        self.lang.activated.connect(lambda: win.on_language(self.lang.currentData()))
        self._row(bl, tr("Language"), tr("The interface switches instantly."), self.lang)
        self.theme = QComboBox()
        self.theme.addItem(tr("Dark"), "dark")
        self.theme.addItem(tr("Light"), "light")
        self.theme.setCurrentIndex(self.theme.findData(PREFS.get("theme")))
        self.theme.activated.connect(lambda: win.on_theme(self.theme.currentData()))
        self._row(bl, tr("Theme"), "", self.theme)
        sw_box = QWidget()
        sw = QHBoxLayout(sw_box)
        sw.setContentsMargins(0, 0, 0, 0)
        sw.setSpacing(8)
        for color in ACCENTS:
            b = QPushButton()
            b.setFixedSize(28, 28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=color: win.on_accent(c))
            sw.addWidget(b)
            self.swatches.append(b)
        self._row(bl, tr("Accent color"), "", sw_box)
        self._row(bl, tr("Animations"), tr("Smooth transitions and effects. Turn off on slow computers."),
                  self._switch("animations"), last=True)
        il.addWidget(box)

        # --- behavior
        box, bl = panel()
        bl.addWidget(self._title("🧩 " + tr("Behavior")))
        self.interval = QComboBox()
        for s in (3, 5, 10, 30):
            self.interval.addItem(tr("{n} seconds", n=s), s)
        self.interval.setCurrentIndex(max(0, self.interval.findData(PREFS.get("refresh_sec"))))
        self.interval.activated.connect(lambda: win.on_interval(self.interval.currentData()))
        self._row(bl, tr("Adapter refresh interval"), tr("How often adapter status is re-read from the system."), self.interval)
        self._row(bl, tr("Live traffic monitoring"), tr("Per-second speed graphs (runs only while the window is visible)."),
                  self._switch("live_stats"))
        self._row(bl, tr("Check public IP automatically"), tr("At startup and whenever the internet route changes."),
                  self._switch("auto_public_ip"))
        self._row(bl, tr("Tray notifications"), tr("Show a balloon when a change completes."), self._switch("notifications"))
        self._row(bl, tr("Close button minimizes to tray"), tr("Keeps the app running in the system tray."),
                  self._switch("close_to_tray"))
        self.file_log = ToggleSwitch()
        self.file_log.set_state(PREFS.get("file_logging"))
        self.file_log.toggled.connect(OPLOG.set_file_logging)
        OPLOG.fileLoggingChanged.connect(self.file_log.set_state)
        self._row(bl, tr("Save operation log to a file"),
                  tr("Writes every log entry with a timestamp to a text file (nicswitcher.log) so you keep a permanent record."),
                  self.file_log)
        self.startup = ToggleSwitch()
        self.startup.setEnabled(False)
        self.startup.toggled.connect(win.on_startup)
        self._row(bl, tr("Start at system startup"), tr("Launches the app automatically (minimized to the tray) every time you sign in."),
                  self.startup, last=True)
        il.addWidget(box)

        # --- data
        box, bl = panel()
        bl.addWidget(self._title("💾 " + tr("Data")))
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, fn, name in (("📤 " + tr("Export settings"), win.export_settings, ""),
                               ("📥 " + tr("Import settings"), win.import_settings, ""),
                               ("👁 " + tr("Unhide all adapters"), win.unhide_all, ""),
                               ("↺ " + tr("Reset everything"), win.reset_settings, "Danger")):
            b = QPushButton(text)
            if name:
                b.setObjectName(name)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        bl.addLayout(row)
        hint = QLabel(tr("Exports include display names, hidden adapters, profiles and preferences."))
        hint.setObjectName("Muted")
        bl.addWidget(hint)
        il.addWidget(box)
        il.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.retheme()

    @staticmethod
    def _title(text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("SectionTitle")
        return l

    def _switch(self, key: str) -> ToggleSwitch:
        sw = ToggleSwitch()
        sw.set_state(PREFS.get(key))
        sw.toggled.connect(lambda v, k=key: self.win.on_pref_changed(k, v))
        return sw

    def _row(self, lay: QVBoxLayout, title: str, desc: str, widget: QWidget, last: bool = False) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        col.addWidget(t)
        if desc:
            d = QLabel(desc)
            d.setObjectName("Muted")
            d.setWordWrap(True)
            col.addWidget(d)
        row.addLayout(col, 1)
        row.addWidget(widget)
        lay.addLayout(row)
        if not last:
            lay.addWidget(separator())

    def retheme(self) -> None:
        cur = PREFS.get("accent")
        for b, color in zip(self.swatches, ACCENTS):
            ring = THEME["text"] if color.lower() == cur.lower() else "transparent"
            b.setStyleSheet(f"QPushButton{{background:{color}; border:3px solid {ring}; border-radius:14px; padding:0;}}"
                            f"QPushButton:hover{{border-color:{THEME['muted']};}}")
            b.setText("✓" if color.lower() == cur.lower() else "")


class AboutPage(QWidget):
    """About + built-in user guide + support contact."""

    def __init__(self, win, parent: QWidget | None = None):
        super().__init__(parent)
        self.win = win
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(10)
        page.addWidget(page_header("ℹ️ " + tr("About"), tr("Guide, support and information about NIC Switcher.")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 4, 8, 4)
        outer.setSpacing(14)

        # ---- hero
        hero, hl = panel(margins=(24, 22, 24, 22), spacing=6)
        logo = QLabel()
        logo.setPixmap(make_icon().pixmap(96, 96))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = QLabel(APP_NAME)
        name.setObjectName("Title")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver = QLabel(f"{tr('Version')} {APP_VERSION}")
        ver.setObjectName("Muted")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag = QLabel(tr("Network adapter manager & toolbox"))
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (logo, name, ver, tag):
            hl.addWidget(w)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        btns2 = QHBoxLayout()
        btns2.setSpacing(8)
        btns2.addStretch(1)
        b = QPushButton("💬 " + tr("Telegram support"))
        b.setObjectName("Primary")
        b.setToolTip(TELEGRAM_URL)
        b.clicked.connect(lambda: open_url(TELEGRAM_URL))
        btns.addWidget(b)
        b = QPushButton("✉️ " + tr("Email"))
        b.clicked.connect(lambda: open_url(f"mailto:{CONTACT_EMAIL}"))
        btns.addWidget(b)
        if GITHUB_URL:
            b = QPushButton("⭐ GitHub")
            b.clicked.connect(lambda: open_url(GITHUB_URL))
            btns.addWidget(b)
            b = QPushButton("🐞 " + tr("Report an issue"))
            b.clicked.connect(lambda: open_url(GITHUB_URL + "/issues"))
            btns2.addWidget(b)
            self.btn_update = QPushButton("🔄 " + tr("Check for updates"))
            self.btn_update.clicked.connect(self.check_updates)
            btns2.addWidget(self.btn_update)
        b = QPushButton("📋 " + tr("Copy diagnostics"))
        b.clicked.connect(self.copy_diag)
        btns2.addWidget(b)
        btns.addStretch(1)
        btns2.addStretch(1)
        hl.addSpacing(8)
        hl.addLayout(btns)
        hl.addLayout(btns2)
        self.update_label = QLabel("")
        self.update_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_label.setObjectName("Muted")
        hl.addWidget(self.update_label)
        outer.addWidget(hero)

        # ---- guide sections
        tg = f"<a href='{TELEGRAM_URL}' style='color:{THEME['accent']}; text-decoration:none'><b>@{TELEGRAM_USER}</b></a>"
        self._section(outer, "📖 " + tr("What is NIC Switcher?"), [
            tr("<b>NIC Switcher</b> is a free, open-source network adapter manager and toolbox for Windows, Linux and macOS. "
               "With one click you can enable, disable or switch between your network adapters (Ethernet, Wi-Fi, hotspot, virtual / VPN adapters), "
               "see which one really carries your internet traffic, and repair common connection problems — without digging through system menus."),
            tr("It is made for desktop computers that have more than one way to reach the internet. Everything runs on your computer; "
               "the only network requests are the public-IP lookup, the speed test and the update check, and you control all of them."),
        ])
        self._section(outer, "🚀 " + tr("Quick start"), [
            tr("<b>1.</b>  Open the <b>Adapters</b> page. Every network adapter is shown as a card with its status, IP address, gateway, MAC address and live speed."),
            tr("<b>2.</b>  Use the switch on a card to enable or disable that adapter. Press <b>⚡ Only this one (disable others)</b> to keep that adapter and disable all the others — the fastest way to change your internet source."),
            tr("<b>3.</b>  Wait for the progress window. The app waits until the adapter is ready, then refreshes your public IP automatically."),
            tr("<b>4.</b>  Press <b>🌍 Test internet</b> on a card (or <b>Test all</b>) to measure the latency and the public IP that adapter really uses."),
            tr("<b>5.</b>  Open the <b>Operation Log</b> page at any time to see what was done and whether it worked."),
            tr("<b>Note:</b> enabling or disabling adapters needs Administrator rights. On Windows the app asks for them when it starts."),
        ])
        self._section(outer, "🧭 " + tr("Guide to the pages"), [
            tr("<b>🔌 Adapters</b> — enable / disable / switch adapters, profiles, DNS, static IP or DHCP, internet priority, display names, hide adapters you never use."),
            tr("<b>📈 Monitor</b> — live download and upload graphs, plus your <b>total internet usage</b> (download + upload) since the app started and a saved all-time total. The totals never reset when an adapter is disabled, re-enabled or restarted."),
            tr("<b>🚀 Speed test</b> — ping, jitter, download and upload; you can run it through one specific adapter to compare connections."),
            tr("<b>🧰 Toolbox</b> — ping, traceroute, DNS lookup, port check, IP lookup, DNS benchmark, active connections, system info and one-click network repair."),
            tr("<b>📝 Operation Log</b> — a timeline of everything the app did. Filter by level, copy or save it, and optionally keep a permanent log file."),
            tr("<b>⚙️ Settings</b> — language (English / فارسی), light / dark theme, accent color, refresh interval, tray, start with the system, export / import settings."),
        ])
        self._section(outer, "💡 " + tr("Tips"), [
            tr("• <b>Virtual / VPN adapters</b> are shown by default. Untick the box on the Adapters page if you only want to see physical adapters."),
            tr("• Save your favourite setups as <b>Profiles</b> (for example “Home internet” or “Phone hotspot”) and apply them from the app or from the tray icon."),
            tr("• Right-click the tray icon to switch adapters, run a speed test or quit without opening the window."),
            tr("• Shortcuts: <b>F5</b> refresh, <b>Ctrl+F</b> search adapters, <b>Ctrl+1 … Ctrl+7</b> jump between pages."),
        ])
        self._section(outer, "🔧 " + tr("Troubleshooting & FAQ"), [
            tr("<b>The switches are disabled and a red banner is shown.</b><br>The app has no Administrator rights. Close it and start it again as Administrator (on Linux / macOS you may be asked for your password)."),
            tr("<b>An adapter was enabled but has no internet.</b><br>Give it a few seconds to receive an IP address, then press <b>Test internet</b>. If it still fails, try <b>Toolbox → Repair → Flush DNS cache</b> and read the Operation Log for errors."),
            tr("<b>Windows SmartScreen or my antivirus warns about the .exe.</b><br>The program is new and not code-signed, so Windows may show a warning. Choose <b>More info → Run anyway</b>. The full source code is on GitHub so you can check or build it yourself."),
            tr("<b>Does the usage total reset when I disable or enable an adapter?</b><br>No. NIC Switcher notices when an adapter's counters restart and keeps adding to the same total, so the number only grows. It keeps counting while the window is hidden in the tray; the saved all-time total survives restarts (reset it with <b>Reset saved total</b> on the Monitor page)."),
            tr("<b>My public IP shows another country.</b><br>That is expected when a VPN or proxy is active — the IP shown is the one websites see."),
            tr("<b>Where are my settings stored?</b><br>In the operating system's settings store for the current user. Use <b>Settings → Data → Export settings</b> to back them up."),
        ])
        self._section(outer, "💬 " + tr("Support & contact"), [
            tr("Found a bug, have an idea or need help? Send me a direct message on Telegram: {tg}. You can also email {mail} or open an issue on GitHub.", tg=tg, mail=CONTACT_EMAIL),
            tr("When you report a problem, please press <b>Copy diagnostics</b> above and, from the <b>Operation Log</b> page, copy the log lines around the problem."),
        ])

        # ---- technical info
        info, il = panel(QGridLayout, spacing=8)
        import platform
        rows = [(tr("Developer"), DEVELOPER_NAME), (tr("License"), LICENSE_NAME),
                (tr("Python"), platform.python_version()), ("Qt / PyQt", f"{QT_VERSION_STR} / {PYQT_VERSION_STR}"),
                (tr("System"), platform.platform()),
                (tr("Privileges"), privilege_info(win.admin)[0].split(" ", 1)[1]),
                (tr("Mode"), tr("Standalone executable") if FROZEN else tr("Python script"))]
        for i, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setObjectName("FieldKey")
            vl = QLabel(v)
            vl.setObjectName("FieldVal")
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            il.addWidget(kl, i, 0)
            il.addWidget(vl, i, 1)
        il.setColumnStretch(1, 1)
        outer.addWidget(info)
        credits = QLabel(tr("Built with Python and PyQt6. Public IP data: ipwho.is, ipapi.co, ipinfo.io, Cloudflare, ipify. "
                            "Speed test: Cloudflare. Free and open source."))
        credits.setObjectName("Muted")
        credits.setWordWrap(True)
        outer.addWidget(credits)
        outer.addStretch(1)
        scroll.setWidget(inner)
        page.addWidget(scroll, 1)

    @staticmethod
    def _section(layout: QVBoxLayout, title: str, paragraphs: list[str]) -> None:
        box, bl = panel(margins=(22, 16, 22, 16), spacing=8)
        t = QLabel(title)
        t.setObjectName("SectionTitle")
        bl.addWidget(t)
        for text in paragraphs:
            if LANG == "fa":      # paragraphs that begin with an English word must still flow right-to-left
                text = f"<div dir='rtl'>{text}</div>"
            lbl = QLabel(text)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setOpenExternalLinks(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            bl.addWidget(lbl)
        layout.addWidget(box)

    def diagnostics(self) -> str:
        import platform
        return (f"{APP_NAME} {APP_VERSION}\nPython {platform.python_version()} | PyQt {PYQT_VERSION_STR} | Qt {QT_VERSION_STR}\n"
                f"{platform.platform()}\nAdmin: {self.win.admin} | Frozen: {FROZEN} | Language: {LANG}\n"
                f"Adapters: {len(self.win.adapters)}")

    def copy_diag(self) -> None:
        QApplication.clipboard().setText(self.diagnostics())
        self.win.set_status("✅ " + tr("Diagnostics copied to clipboard."))

    def check_updates(self) -> None:
        self.btn_update.setEnabled(False)
        self.update_label.setText("⏳ " + tr("Checking …"))
        self.win._run(lambda: check_update(), self._on_update)

    def _on_update(self, ok: bool, payload) -> None:
        self.btn_update.setEnabled(True)
        if not ok:
            self.update_label.setText("❌ " + tr("Could not check for updates."))
            OPLOG.warn(tr("Could not check for updates."))
        elif payload["newer"]:
            self.update_label.setText("🎉 " + tr("Version {v} is available.", v=payload["latest"]))
            OPLOG.ok(tr("Version {v} is available.", v=payload["latest"]))
            open_url(payload["url"])
        else:
            self.update_label.setText("✅ " + tr("You are up to date."))
            OPLOG.info(tr("You are up to date."))


class NavBox(QWidget):
    resized = pyqtSignal()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit()


def privilege_info(can_change: bool) -> tuple[str, str]:
    """(label, theme colour key) describing the current privilege level."""
    if is_admin():
        return "🛡 " + tr("Administrator"), "ok"
    if can_change:
        return "🔑 " + tr("Standard user"), "warn"
    return "⚠️ " + tr("Limited mode"), "danger"


def apply_language(code: str) -> None:
    """Switch language, layout direction and fonts application-wide."""
    global LANG
    LANG = code if code in LANGS else "en"
    app = QApplication.instance()
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if LANG == "fa" else Qt.LayoutDirection.LeftToRight)
    font = QFont(app.font())
    font.setFamilies(["Vazirmatn", "Segoe UI", "Tahoma", "Noto Sans Arabic", "DejaVu Sans", "Helvetica Neue"] if LANG == "fa"
                     else ["Segoe UI Variable Text", "Segoe UI", "SF Pro Text", ".AppleSystemUIFont", "Inter",
                           "Noto Sans", "Ubuntu", "Cantarell", "DejaVu Sans", "Arial"])
    font.setPointSize(10)
    app.setFont(font)


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------
class MainWindow(QMainWindow):
    NAV = [("🔌", "Adapters"), ("📈", "Monitor"), ("🚀", "Speed test"),
           ("🧰", "Toolbox"), ("📝", "Operation Log"), ("⚙️", "Settings"), ("ℹ️", "About")]

    def __init__(self, admin: bool, start_hidden: bool = False):
        super().__init__()
        self.admin = admin
        self.start_hidden = start_hidden
        self.cards: dict[int, AdapterCard] = {}
        self.adapters: list[Adapter] = []
        self.probes: dict[int, dict] = {}
        self.testing: set[int] = set()
        self.public: dict | None = None
        self.nicks: dict[str, str] = PREFS.get_json("nicknames", {})
        self.hidden_keys: set[str] = set(PREFS.get_json("hidden", []))
        self.class_cache: dict[str, list[int]] = PREFS.get_json("adapter_class", {})   # description -> [hardware, virtual]
        self.mac_alias: dict[str, str] = PREFS.get_json("mac_alias", {})                # description -> MAC
        # live statistics
        self.hist: dict[int, deque] = {}
        self.total_hist: deque = deque(maxlen=120)
        self.session: dict[int, tuple[int, int]] = {}
        self.rates: dict[int, tuple[float, float]] = {}
        self._stat_prev: dict[str, tuple[float, int, int]] = {}
        self._stat_base: dict[str, tuple[int, int]] = {}
        self.usage = UsageTracker()                       # traffic since the app started (reset-proof)
        self._usage_kind: dict[str, str] = {}             # adapter key -> "phys" | "virt"
        self.usage_all = self._load_usage()               # saved all-time totals
        self._usage_timer = QTimer(self)
        self._usage_timer.timeout.connect(self._save_usage)
        self._usage_timer.start(30_000)
        self._fb_prev: dict[int, tuple[float, int, int]] = {}
        self._last_stat = 0.0
        self.stats_task: Task | None = None
        # state
        self._pub_loading = False
        self._last_read_error = ""
        self._first_read_logged = False
        self.startup_state: bool | None = None
        self._net_sig: tuple | None = None
        self._pending: dict | None = None
        self._workers: set[Worker] = set()
        self._busy = False
        self._refreshing = False
        self._quitting = False
        self._tray_hint_shown = False
        self._tray_dot: str | None = None
        self.tray: QSystemTrayIcon | None = None
        self.pages: list[QWidget] = []

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_icon())
        self.setMinimumSize(1060, 700)
        self.resize(1240, 840)

        self.apply_theme(PREFS.get("theme"), rebuild=False)
        self._build_ui()
        self._build_tray()

        QShortcut(QKeySequence("F5"), self).activated.connect(self.refresh)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._focus_search)
        for i in range(len(self.NAV)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self).activated.connect(lambda i=i: self._goto(i))

        self.timer = QTimer(self)
        self.timer.setInterval(PREFS.get("refresh_sec") * 1000)
        self.timer.timeout.connect(self._auto_refresh)
        self.timer.start()
        QTimer.singleShot(0, self.refresh)
        self._run(startup_enabled, self._on_startup_state)
        QTimer.singleShot(0, self.start_stats)
        import platform
        OPLOG.info(tr("{a} {v} started on {p}.", a=APP_NAME, v=APP_VERSION, p=f"{platform.system()} {platform.release()}"))
        if self.admin:
            OPLOG.ok(tr("Running with administrator rights."))
        else:
            OPLOG.warn(tr("Running without administrator rights — adapters can be viewed but not changed."))
        if PREFS.get("auto_public_ip"):
            QTimer.singleShot(900, self.fetch_public)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = RootWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.sidebar = self._build_sidebar()
        outer.addWidget(self.sidebar)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.content = QWidget()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(26, 20, 26, 10)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack)
        rl.addWidget(self.content, 1)
        rl.addWidget(self._build_footer())
        outer.addWidget(right, 1)

        self.page_adapters = self._build_adapters_page()
        self.page_monitor = MonitorPage(self)
        self.page_speed = SpeedPage(self)
        self.page_tools = ToolboxPage(self)
        self.page_log = LogPage(self)
        self.page_settings = SettingsPage(self)
        self.page_about = AboutPage(self)
        self.pages = [self.page_adapters, self.page_monitor, self.page_speed,
                      self.page_tools, self.page_log, self.page_settings, self.page_about]
        for p in self.pages:
            self.stack.addWidget(p)

        self.overlay = BusyOverlay(root)
        root.overlay = self.overlay
        self._apply_startup_ui()
        self._goto(0, animate=False)
        QTimer.singleShot(0, lambda: self._move_pill(False))

    def _build_sidebar(self) -> QFrame:
        sb = QFrame()
        sb.setObjectName("Sidebar")
        sb.setFixedWidth(228)
        lay = QVBoxLayout(sb)
        lay.setContentsMargins(14, 20, 14, 14)
        lay.setSpacing(6)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(make_icon().pixmap(40, 40))
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(APP_NAME)
        t.setStyleSheet("font-size: 16px; font-weight: 800;")
        v = QLabel(f"v{APP_VERSION}")
        v.setObjectName("Muted")
        col.addWidget(t)
        col.addWidget(v)
        brand.addWidget(logo)
        brand.addLayout(col, 1)
        lay.addLayout(brand)
        lay.addSpacing(16)

        self.nav_box = NavBox()
        nl = QVBoxLayout(self.nav_box)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(4)
        self.pill = QFrame(self.nav_box)
        self.pill.setObjectName("NavPill")
        self.nav_buttons: list[NavButton] = []
        for i, (glyph, label) in enumerate(self.NAV):
            b = NavButton(glyph, tr(label))
            b.setToolTip(f"Ctrl+{i + 1}")
            b.clicked.connect(lambda _=False, i=i: self._goto(i))
            nl.addWidget(b)
            self.nav_buttons.append(b)
        nl.addStretch(1)
        self.pill.lower()
        self.nav_box.resized.connect(lambda: self._move_pill(False))
        lay.addWidget(self.nav_box, 1)

        badge_text, badge_kind = privilege_info(self.admin)
        badge = QLabel(badge_text)
        c = THEME[badge_kind]
        badge.setStyleSheet(f"background:{rgba(c, 0.15)}; color:{c}; border-radius:10px; padding:6px 10px; font-weight:700;")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(badge)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_lang = QPushButton("🌐 " + LANGS["fa" if LANG == "en" else "en"])
        self.btn_lang.clicked.connect(lambda: self.on_language("fa" if LANG == "en" else "en"))
        self.btn_theme = QPushButton("☀️" if PREFS.get("theme") == "dark" else "🌙")
        self.btn_theme.setObjectName("Ghost")
        self.btn_theme.setToolTip(tr("Toggle dark / light theme"))
        self.btn_theme.clicked.connect(lambda: self.on_theme("light" if PREFS.get("theme") == "dark" else "dark"))
        row.addWidget(self.btn_lang, 1)
        row.addWidget(self.btn_theme)
        lay.addLayout(row)
        return sb

    def _build_footer(self) -> QFrame:
        f = QFrame()
        f.setObjectName("Footer")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(26, 8, 26, 8)
        self.status_msg = QLabel("")
        self.status_msg.setObjectName("Muted")
        self.dev_label = QLabel()
        self.dev_label.setTextFormat(Qt.TextFormat.RichText)
        self.dev_label.setOpenExternalLinks(True)
        self.dev_label.setObjectName("Muted")
        lay.addWidget(self.status_msg, 1)
        lay.addWidget(self.dev_label)
        self._update_footer()
        return f

    def _update_footer(self) -> None:
        text = (f"{APP_NAME} v{APP_VERSION} &nbsp;•&nbsp; {tr('Developed by')} "
                f"<b style='color:{THEME['text']}'>{DEVELOPER_NAME}</b>")
        if GITHUB_URL:
            text += f" &nbsp;•&nbsp; <a href='{GITHUB_URL}' style='color:{THEME['accent']}; text-decoration:none'>GitHub</a>"
        self.dev_label.setText(text)

    def _move_pill(self, animate: bool = True) -> None:
        cur = self.stack.currentIndex()
        if not (0 <= cur < len(self.nav_buttons)):
            return
        target = self.nav_buttons[cur].geometry()
        if animate and PREFS.get("animations") and self.pill.isVisible():
            anim = QPropertyAnimation(self.pill, b"geometry", self.pill)
            anim.setDuration(260)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(self.pill.geometry())
            anim.setEndValue(target)
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        else:
            self.pill.setGeometry(target)
        self.pill.show()

    def _goto(self, index: int, animate: bool = True) -> None:
        self.stack.setCurrentIndex(index)
        for j, b in enumerate(self.nav_buttons):
            b.setChecked(j == index)
        page = self.pages[index]
        if animate:
            fade_in(page, 240)
        self._move_pill(animate)
        if page is self.page_monitor:
            self.page_monitor.refresh_combo()
            self.page_monitor.tick()
        elif page is self.page_speed:
            self.page_speed.refresh_adapters()
        elif page is self.page_tools:
            self.page_tools.on_adapters_changed()
        elif page is self.page_log:
            self.page_log.scroll_end()

    def _focus_search(self) -> None:
        self._goto(0)
        self.search.setFocus()

    def _build_adapters_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(page_header("🔌 " + tr("Network adapters")), 0)
        self.summary = QLabel(tr("Loading …"))
        self.summary.setObjectName("Muted")
        head.addWidget(self.summary, 1)
        lay.addLayout(head)

        if not self.admin:
            banner = QLabel("⚠️ " + tr("The app has no administrator rights, so enabling or disabling adapters is not possible. "
                                       "You can still view everything.")
                            + ("" if IS_WINDOWS else " " + tr("Install polkit (pkexec) or run the app as root.")))
            banner.setObjectName("Banner")
            banner.setWordWrap(True)
            lay.addWidget(banner)

        self.ipbar = IpBar()
        self.ipbar.refreshRequested.connect(self.fetch_public)
        lay.addWidget(self.ipbar)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 " + tr("Search by name, IP or MAC …   (Ctrl+F)"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        self.btn_refresh = QPushButton("🔄 " + tr("Refresh"))
        self.btn_refresh.setToolTip("F5")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_probe_all = QPushButton("🌍 " + tr("Test all"))
        self.btn_probe_all.setToolTip(tr("Measures latency and public IP of every connected adapter separately"))
        self.btn_probe_all.clicked.connect(self.probe_all)
        self.btn_profiles = QPushButton("📁 " + tr("Profiles"))
        self.profile_menu = QMenu(self)
        self.profile_menu.aboutToShow.connect(lambda: self._fill_profile_menu(self.profile_menu, True))
        self.btn_profiles.setMenu(self.profile_menu)
        self.btn_tools = QPushButton("🛠 " + tr("Tools"))
        tools = QMenu(self)
        tools.addAction(tr("Enable all adapters")).triggered.connect(self.enable_all)
        tools.addAction(tr("Flush DNS cache")).triggered.connect(self.do_flush_dns)
        self.act_show_hidden = tools.addAction(tr("Show hidden adapters"))
        self.act_show_hidden.setCheckable(True)
        self.act_show_hidden.setChecked(PREFS.get("show_hidden"))
        self.act_show_hidden.toggled.connect(self._on_show_hidden)
        tools.addSeparator()
        tools.addAction(tr("Open the system network settings")).triggered.connect(self._open_ncpa)
        self.btn_tools.setMenu(tools)
        bar.addWidget(self.search, 1)
        for b in (self.btn_refresh, self.btn_probe_all, self.btn_profiles, self.btn_tools):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            bar.addWidget(b)
        lay.addLayout(bar)

        opts = QHBoxLayout()
        opts.setSpacing(22)
        self.chk_virtual = QCheckBox(tr("Virtual / VPN adapters"))
        self.chk_virtual.setChecked(PREFS.get("show_virtual"))
        self.chk_virtual.toggled.connect(self._on_virtual_toggled)
        self.chk_confirm = QCheckBox(tr("Ask for confirmation before “Only this one”"))
        self.chk_confirm.setChecked(PREFS.get("confirm_exclusive"))
        self.chk_confirm.toggled.connect(lambda v: PREFS.set("confirm_exclusive", v))
        self.chk_startup = QCheckBox(tr("Start at system startup"))
        self.chk_startup.setToolTip(tr("Launches the app automatically (minimized to the tray) every time you sign in."))
        self.chk_startup.setEnabled(False)
        self.chk_startup.toggled.connect(self.on_startup)
        opts.addWidget(self.chk_virtual)
        opts.addWidget(self.chk_confirm)
        opts.addWidget(self.chk_startup)
        opts.addStretch(1)
        lay.addLayout(opts)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        self.cards_layout = QVBoxLayout(holder)
        self.cards_layout.setContentsMargins(0, 0, 6, 0)
        self.cards_layout.setSpacing(12)
        self.empty = QLabel(tr("No adapters to show."))
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.hide()
        self.cards_layout.addWidget(self.empty)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(holder)
        lay.addWidget(self.scroll, 1)
        return page

    def _rebuild_ui(self) -> None:
        """Rebuild all widgets (language change) while keeping application state."""
        cur = self.stack.currentIndex() if hasattr(self, "stack") else 0
        self._shutdown_pages()
        self.cards.clear()
        self._build_ui()
        self._goto(cur, animate=False)
        QTimer.singleShot(0, lambda: self._move_pill(False))
        if self.adapters:
            self._sync_cards(self.adapters)
        if self.public:
            self.ipbar.set_info(self.public)

    def _shutdown_pages(self) -> None:
        for p in self.pages:
            if hasattr(p, "shutdown"):
                p.shutdown()

    # ----------------------------------------------------------- theming etc.
    def apply_theme(self, name: str, rebuild: bool = True) -> None:
        name = name if name in THEMES else "light"
        THEME.clear()
        THEME.update(THEMES[name])
        accent = PREFS.get("accent")
        THEME["accent"] = accent
        THEME["accent_soft"] = rgba(accent, 0.16)
        THEME["accent_line"] = rgba(accent, 0.55)
        QApplication.instance().setStyleSheet(QSS.safe_substitute(THEME))
        if not rebuild or not hasattr(self, "stack"):
            return
        self.btn_theme.setText("☀️" if name == "dark" else "🌙")
        self._update_footer()
        for card in self.cards.values():
            card.refresh_view()
        self.page_settings.retheme()
        self.page_log.retheme()
        self.page_monitor.legend.setText(
            f"<span style='color:{THEME['accent']}'>●</span> {tr('Download')}  &nbsp;&nbsp; "
            f"<span style='color:{THEME['ok']}'>●</span> {tr('Upload')}")
        for w in self.findChildren((ToggleSwitch, Sparkline, BandwidthChart, GaugeWidget, NavButton, BusyOverlay)):
            w.update()
        self._update_tray_state(force=True)

    def on_theme(self, name: str) -> None:
        PREFS.set("theme", name)
        self.apply_theme(name)
        OPLOG.info(tr("Theme changed to {t}.", t=tr("Dark") if name == "dark" else tr("Light")))

    def on_accent(self, color: str) -> None:
        PREFS.set("accent", color)
        self.apply_theme(PREFS.get("theme"))
        OPLOG.info(tr("Accent color changed to {c}.", c=color))

    def on_language(self, code: str) -> None:
        if code == LANG or code not in LANGS:
            return
        PREFS.set("lang", code)
        apply_language(code)
        OPLOG.info(tr("Language changed to {l}.", l=LANGS[code]))
        QTimer.singleShot(0, self._rebuild_ui)

    PREF_LABELS = {"animations": "Animations", "live_stats": "Live traffic monitoring",
                   "auto_public_ip": "Check public IP automatically", "notifications": "Tray notifications",
                   "close_to_tray": "Close button minimizes to tray"}

    def on_pref_changed(self, key: str, value: bool) -> None:
        PREFS.set(key, value)
        if key in self.PREF_LABELS:
            OPLOG.info(tr("Setting changed: {k} → {v}", k=tr(self.PREF_LABELS[key]), v=tr("On") if value else tr("Off")))
        if key == "live_stats":
            self.start_stats() if value else self.stop_stats()

    def on_interval(self, sec: int) -> None:
        PREFS.set("refresh_sec", sec)
        self.timer.setInterval(sec * 1000)

    def _on_startup_state(self, ok: bool, payload) -> None:
        if ok:
            self.startup_state = bool(payload)
        self._apply_startup_ui()

    def _apply_startup_ui(self) -> None:
        """Mirror the real autostart state into both controls (Adapters page checkbox + Settings switch)."""
        known = self.startup_state is not None
        state = bool(self.startup_state)
        self.chk_startup.blockSignals(True)
        self.chk_startup.setChecked(state)
        self.chk_startup.setEnabled(known)
        self.chk_startup.blockSignals(False)
        self.page_settings.startup.set_state(state)
        self.page_settings.startup.setEnabled(known)

    def on_startup(self, enable: bool) -> None:
        def done(ok: bool, payload) -> None:
            err = str(payload) if not ok else (payload[1] if payload[0] != 0 else "")
            if err:
                OPLOG.error(tr("Error:\n\n{e}", e=err))
                self._info(tr("Error:\n\n{e}", e=err), QMessageBox.Icon.Critical)
                self.startup_state = not enable
            else:
                self.startup_state = enable
                self.set_status("✅ " + (tr("The app will start automatically at startup.") if enable else tr("Autostart removed.")))
            self._apply_startup_ui()
        icon = ensure_icon_file() if (IS_LINUX and enable) else ""     # created here: GUI thread
        self._run(set_startup, done, enable, icon)

    def set_status(self, text: str, log: bool = True) -> None:
        """Show a message in the footer and record it in the Operation Log (emoji prefix = level)."""
        self.status_msg.setText(text)
        if not log:
            return
        level, clean = "INFO", text
        for prefix, lv in (("✅", "SUCCESS"), ("❌", "ERROR"), ("⚠️", "WARNING"), ("⚠", "WARNING")):
            if text.startswith(prefix):
                level, clean = lv, text[len(prefix):].lstrip("\ufe0f ")
                break
        OPLOG.log(clean, level)

    # ----------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip(APP_NAME)
        self.tray_menu = QMenu()
        self.tray_menu.aboutToShow.connect(self._rebuild_tray_menu)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _rebuild_tray_menu(self) -> None:
        m = self.tray_menu
        m.clear()
        m.addAction(self.summary.text()).setEnabled(False)
        if self.public:
            cc = f" ({self.public['cc']})" if self.public.get("cc") else ""
            m.addAction(f"🌍 {self.public['ip']}{cc}").setEnabled(False)
        m.addSeparator()
        scope = self._scope_adapters()
        can = not self._busy and self.admin
        for a in scope:
            ip = f"   —   {a.primary_ip}" if a.primary_ip else ""
            act = m.addAction(f"{a.icon}  {self.display_name(a)}{ip}")
            act.setCheckable(True)
            act.setChecked(a.enabled)
            act.setEnabled(can)
            act.triggered.connect(lambda checked, i=a.index: self.on_toggle(i, checked))
        if scope:
            only = m.addMenu("⚡ " + tr("Only this one"))
            only.setEnabled(can)
            for a in scope:
                only.addAction(f"{a.icon}  {self.display_name(a)}").triggered.connect(
                    lambda _=False, i=a.index: self.on_exclusive(i, ask=False))
        prof = m.addMenu("📁 " + tr("Profiles"))
        self._fill_profile_menu(prof, False)
        m.addSeparator()
        m.addAction("🚀 " + tr("Speed test")).triggered.connect(lambda: (self.show_window(), self._goto(2)))
        m.addAction("🌍 " + tr("Check public IP")).triggered.connect(self.fetch_public)
        m.addAction("🔄 " + tr("Refresh")).triggered.connect(self.refresh)
        m.addAction("🪟 " + tr("Show window")).triggered.connect(self.show_window)
        m.addSeparator()
        m.addAction("❌ " + tr("Quit")).triggered.connect(self.quit_app)

    def _notify(self, title: str, msg: str) -> None:
        if PREFS.get("notifications") and self.tray and self.tray.isVisible():
            self.tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 4000)

    def _update_tray_state(self, force: bool = False) -> None:
        if not self.tray:
            return
        ups = [a for a in self.adapters if a.is_up]
        dot = "#34d399" if any(a.gateway for a in ups) else "#fbbf24" if ups else "#f87171"
        if dot != self._tray_dot or force:
            self._tray_dot = dot
            self.tray.setIcon(make_icon(dot))
        self.tray.setToolTip(f"{APP_NAME}\n{self.summary.text()}")

    # -------------------------------------------------------------- workers
    def _run(self, fn, callback, *args) -> None:
        w = Worker(fn, callback, *args)
        self._workers.add(w)
        w.signals.done.connect(self._worker_done)
        QThreadPool.globalInstance().start(w)

    @pyqtSlot(object, object, bool, object)
    def _worker_done(self, worker, callback, ok, payload) -> None:
        self._workers.discard(worker)
        callback(ok, payload)

    def _begin_busy(self, title: str, sub: str = "") -> None:
        self._busy = True
        self.sidebar.setEnabled(False)
        self.content.setEnabled(False)
        self.overlay.show_busy(title, sub)

    def _end_busy(self) -> None:
        self._busy = False
        self.overlay.hide_busy()
        self.sidebar.setEnabled(True)
        self.content.setEnabled(True)

    # ------------------------------------------------- internet usage totals
    @staticmethod
    def _new_usage_store() -> dict:
        return {"phys": [0, 0], "virt": [0, 0], "since": time.strftime("%Y-%m-%d")}

    def _load_usage(self) -> dict:
        store = self._new_usage_store()
        data = PREFS.get_json("usage_alltime", {})
        try:
            for kind in ("phys", "virt"):
                rx, tx = data[kind]
                store[kind] = [max(0, int(rx)), max(0, int(tx))]
            if isinstance(data.get("since"), str) and data["since"]:
                store["since"] = data["since"]
        except (KeyError, TypeError, ValueError):
            pass
        return store

    def _save_usage(self) -> None:
        PREFS.set_json("usage_alltime", self.usage_all)

    def _feed_usage(self, a: Adapter, name: str, rx, tx) -> None:
        d_rx, d_tx, restarted = self.usage.update(name, rx, tx)
        kind = "virt" if a.virtual else "phys"
        self._usage_kind[name] = kind
        if d_rx or d_tx:
            self.usage_all[kind][0] += d_rx
            self.usage_all[kind][1] += d_tx
        if restarted:
            OPLOG.info(tr("Traffic counters of “{n}” restarted (adapter was reset or re-enabled) — usage totals are kept.",
                          n=self.display_name(a)))

    def usage_numbers(self) -> dict:
        """Session and saved totals; virtual / VPN adapters count only when the user ticks the option
        (their traffic is already counted on the physical adapter that carries it)."""
        kinds = ("phys", "virt") if PREFS.get("usage_include_virtual") else ("phys",)
        s_rx = sum(v[0] for k, v in self.usage.session.items() if self._usage_kind.get(k, "phys") in kinds)
        s_tx = sum(v[1] for k, v in self.usage.session.items() if self._usage_kind.get(k, "phys") in kinds)
        return {"s_rx": s_rx, "s_tx": s_tx,
                "a_rx": sum(self.usage_all[k][0] for k in kinds), "a_tx": sum(self.usage_all[k][1] for k in kinds),
                "since": self.usage_all.get("since", "")}

    def on_usage_virtual(self, checked: bool) -> None:
        PREFS.set("usage_include_virtual", checked)
        OPLOG.info(tr("Usage totals now {s} virtual / VPN adapters.", s=tr("include") if checked else tr("exclude")))
        self.page_monitor.update_usage()

    def reset_usage_total(self) -> None:
        if not self._confirm(tr("Reset the saved total usage to zero? The usage since the app started is not affected.")):
            return
        self.usage_all = self._new_usage_store()
        self._save_usage()
        OPLOG.info(tr("Saved total usage was reset."))
        self.page_monitor.update_usage()

    # ------------------------------------------------- live traffic stream
    def start_stats(self) -> None:
        if not PREFS.get("live_stats"):
            return
        if self.stats_task and self.stats_task.isRunning():
            return
        t = Task(stats_stream_job, self)
        t.message.connect(self._on_stats)
        t.finished.connect(self._stats_finished)
        self.stats_task = t
        t.start()

    def stop_stats(self) -> None:
        t, self.stats_task = self.stats_task, None
        if t and t.isRunning():
            t.stop()
            t.wait(1200)

    def _stats_finished(self) -> None:
        if self.stats_task is not None and PREFS.get("live_stats") and not self._quitting:
            QTimer.singleShot(3000, self.start_stats)

    def _on_stats(self, payload) -> None:
        if not (isinstance(payload, tuple) and payload[0] == "stats"):
            return
        _, data, ts = payload
        by_name = {a.device or a.name: a for a in self.adapters}
        tot_d = tot_u = 0.0
        for row in data:
            a = by_name.get(row.get("N"))
            if a is None:
                continue
            name, r, s = a.device or a.name, int(row.get("R", 0)), int(row.get("S", 0))
            self._feed_usage(a, name, r, s)
            sess = self.usage.session.get(name, [0, 0])
            self.session[a.index] = (sess[0], sess[1])
            prev = self._stat_prev.get(name)
            d = u = 0.0
            if prev and ts - prev[0] > 0.2 and r >= prev[1] and s >= prev[2]:
                dt = ts - prev[0]
                d, u = (r - prev[1]) / dt, (s - prev[2]) / dt
            self._stat_prev[name] = (ts, r, s)
            self.rates[a.index] = (d, u)
            self.hist.setdefault(a.index, deque(maxlen=120)).append((d, u))
            tot_d += d
            tot_u += u
            card = self.cards.get(a.index)
            if card:
                card.set_rates(d, u)
        self.total_hist.append((tot_d, tot_u))
        self._last_stat = time.monotonic()
        if self.stack.currentWidget() is self.page_monitor:
            self.page_monitor.tick()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.start_stats()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)       # the stream keeps running in the tray so usage is counted while hidden

    # ----------------------------------------------------- reading adapters
    def _auto_refresh(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.refresh()

    def refresh(self) -> None:
        if self._refreshing or self._busy:
            return
        self._refreshing = True
        self._run(fetch_adapters, self._on_fetched)

    def _on_fetched(self, ok: bool, payload) -> None:
        self._refreshing = False
        if self._busy:
            return
        if not ok:
            msg = tr("Could not read adapters: {e}", e=payload)
            self.set_status("❌ " + msg, log=(msg != self._last_read_error))   # do not repeat the same error every refresh
            self._last_read_error = msg
            return
        self._last_read_error = ""
        self._sync_cards(payload)
        self.set_status(tr("Last updated: {t}", t=time.strftime("%H:%M:%S")), log=False)
        if not self._first_read_logged:
            self._first_read_logged = True
            up = sum(1 for a in self.adapters if a.is_up)
            OPLOG.info(tr("Adapters detected: {n} ({up} connected).", n=len(self.adapters), up=up))

    def _nick_key(self, a: Adapter) -> str:
        """Stable identity: the MAC address (remembered per device, because a disabled adapter may not report it)."""
        return a.mac or self.mac_alias.get(a.pnp.upper() or a.description, "") or a.description

    def _remember_adapters(self, adapters: list[Adapter]) -> None:
        """Learn what each adapter is while it is enabled; reuse that once it is disabled (e.g. after a reboot)."""
        changed = False
        for a in adapters:
            k = a.pnp.upper() or a.description
            if a.mac and self.mac_alias.get(k) != a.mac:
                self.mac_alias[k] = a.mac
                changed = True
            elif not a.mac and k in self.mac_alias:
                a.mac = self.mac_alias[k]           # a disabled adapter does not report its MAC: use the remembered one
        if changed:
            PREFS.set_json("mac_alias", self.mac_alias)
        changed = False
        for a in adapters:
            k = a.pnp.upper() or a.description
            if a.enabled:
                value = [int(a.hardware), int(a.virtual)]
                if self.class_cache.get(k) != value:
                    self.class_cache[k] = value
                    changed = True
            elif k in self.class_cache:
                a.hardware, a.virtual = (bool(x) for x in self.class_cache[k])
        if changed:
            PREFS.set_json("adapter_class", self.class_cache)

    def display_name(self, a: Adapter) -> str:
        return self.nicks.get(self._nick_key(a), "") or a.name

    def _is_listed(self, a: Adapter) -> bool:
        # A disabled adapter stays listed unless it is known to be virtual - it must remain manageable.
        physical = (a.hardware and not a.virtual) or (not a.enabled and not a.virtual)
        if not (self.chk_virtual.isChecked() or physical):
            return False
        return PREFS.get("show_hidden") or self._nick_key(a) not in self.hidden_keys

    def _scope_adapters(self) -> list[Adapter]:
        """Adapters affected by group actions (independent of the search text)."""
        return [a for a in self.adapters if self._is_listed(a)]

    def _make_card(self, a: Adapter) -> AdapterCard:
        card = AdapterCard(a)
        card.toggleRequested.connect(self.on_toggle)
        card.exclusiveRequested.connect(self.on_exclusive)
        card.probeRequested.connect(self.probe)
        card.dnsRequested.connect(self.on_dns)
        card.renewRequested.connect(self.on_renew)
        card.renameRequested.connect(self.on_rename)
        card.winRenameRequested.connect(self.on_win_rename)
        card.hideRequested.connect(self.on_hide)
        card.ipConfigRequested.connect(self.on_ip_config)
        card.metricRequested.connect(self.on_metric)
        return card

    def _sync_cards(self, adapters: list[Adapter]) -> None:
        self._remember_adapters(adapters)
        now = time.monotonic()
        stream_alive = now - self._last_stat < 4
        # fallback speed estimate when the live stream is not running
        for a in adapters:
            if not stream_alive:          # keep the usage totals going from the periodic read (cumulative counters)
                key = a.device or a.name
                self._feed_usage(a, key, a.rx, a.tx)
                sess = self.usage.session.get(key, [0, 0])
                self.session[a.index] = (sess[0], sess[1])
            prev = self._fb_prev.get(a.index)
            if not stream_alive and prev and now - prev[0] >= 0.8 and a.rx >= prev[1] and a.tx >= prev[2]:
                dt = now - prev[0]
                self.rates[a.index] = ((a.rx - prev[1]) / dt, (a.tx - prev[2]) / dt)
            if prev is None or now - prev[0] >= 0.8:
                self._fb_prev[a.index] = (now, a.rx, a.tx)

        self.adapters = sorted(adapters, key=lambda a: natural_key(a.name))   # fixed order
        seen: set[int] = set()
        fresh = 0
        for pos, a in enumerate(self.adapters):
            seen.add(a.index)
            probe = self.probes.get(a.index)
            if probe and (not a.is_up or probe.get("src") != a.primary_ip):
                self.probes.pop(a.index, None)
                probe = None
            card = self.cards.get(a.index)
            is_new = card is None
            if is_new:
                card = self._make_card(a)
                self.cards[a.index] = card
            key = self._nick_key(a)
            card.update_from(a, probe, a.index in self.testing, self.nicks.get(key, ""), key in self.hidden_keys)
            if self.cards_layout.indexOf(card) != pos + 1:
                self.cards_layout.insertWidget(pos + 1, card)
            if is_new:
                fade_in(card, 320, delay=min(fresh * 80, 480))
                fresh += 1
            if not stream_alive and a.is_up:
                d, u = self.rates.get(a.index, (0.0, 0.0))
                card.set_rates(d, u)
        for idx in [i for i in self.cards if i not in seen]:
            self.cards.pop(idx).deleteLater()
            self.probes.pop(idx, None)
        self.apply_filter()
        self._update_summary()

        sig = tuple(sorted(a.index for a in self.adapters if a.is_up and a.gateway))
        if self._net_sig is not None and sig != self._net_sig and not self._busy and PREFS.get("auto_public_ip"):
            QTimer.singleShot(2500, self.fetch_public)
        self._net_sig = sig

        self.page_monitor.refresh_combo()
        self.page_monitor.update_usage()
        self.page_speed.refresh_adapters()
        self.page_tools.on_adapters_changed()

    def _update_summary(self) -> None:
        up = sum(1 for a in self.adapters if a.is_up)
        off = sum(1 for a in self.adapters if not a.enabled)
        hidden = len(self.adapters) - len(self._scope_adapters())
        self.summary.setText(tr("{n} adapters  •  {up} connected  •  {off} disabled",
                                n=len(self.adapters), up=up, off=off)
                             + (("  •  " + tr("(+{k} hidden by filters)", k=hidden)) if hidden > 0 else ""))
        self._update_tray_state()

    # ---------------------------------------------------------------- filters
    def _on_virtual_toggled(self, checked: bool) -> None:
        PREFS.set("show_virtual", checked)
        OPLOG.info(tr("Virtual / VPN adapters are now {s}.", s=tr("shown") if checked else tr("hidden")))
        self.apply_filter()
        self._update_summary()

    def _on_show_hidden(self, checked: bool) -> None:
        PREFS.set("show_hidden", checked)
        OPLOG.info(tr("Hidden adapters are now {s}.", s=tr("shown") if checked else tr("hidden")))
        self.apply_filter()
        self._update_summary()

    def apply_filter(self) -> None:
        q = self.search.text().strip()
        shown = 0
        for card in self.cards.values():
            visible = self._is_listed(card.adapter) and (not q or card.matches(q))
            card.setVisible(visible)
            shown += visible
        self.empty.setVisible(shown == 0)

    # --------------------------------------------------------------- dialogs
    def _confirm(self, text: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("Confirm"))
        box.setText(text)
        yes = box.addButton(tr("Yes, continue"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _info(self, text: str, icon=QMessageBox.Icon.Warning) -> None:
        if not self.isVisible():
            self.show_window()
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(APP_NAME)
        box.setText(text)
        box.addButton(tr("OK"), QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def _ask_text(self, title: str, label: str, text: str = "") -> str | None:
        dlg = QInputDialog(self)
        dlg.setWindowTitle(title)
        dlg.setLabelText(label)
        dlg.setTextValue(text)
        dlg.setOkButtonText(tr("OK"))
        dlg.setCancelButtonText(tr("Cancel"))
        dlg.resize(440, 140)
        return dlg.textValue().strip() if dlg.exec() else None

    def _need_admin(self) -> bool:
        if self.admin:
            return False
        OPLOG.warn(tr("Administrator rights are required for this action."))
        self._info(tr("Administrator rights are required for this action."))
        return True

    # -------------------------------------------------- enabling / disabling
    def _apply(self, enable: list[int], disable: list[int], title: str) -> None:
        if self._busy:
            return
        if self._need_admin():
            self.refresh()
            return
        if not enable and not disable:
            self.set_status(tr("Nothing to change."))
            self.refresh()
            return
        self._pending = {"enable": enable, "disable": disable, "title": title, "error": "", "t_wait": 0.0,
                         "pnp": {a.index: a.pnp for a in self.adapters if a.pnp}}

        def names(idx: list[int]) -> str:
            return ", ".join(self.display_name(a) for a in self.adapters if a.index in idx) or "—"
        parts = ([tr("Enable: {n}", n=names(enable))] if enable else []) + \
                ([tr("Disable: {n}", n=names(disable))] if disable else [])
        OPLOG.info(f"{title} — " + "  |  ".join(parts))
        self._begin_busy(title, tr("Sending the command to the system …"))
        self._run(change_adapters, self._on_changed, enable, disable)

    def _on_changed(self, ok: bool, payload) -> None:
        p = self._pending
        if p is None:
            self._end_busy()
            return
        if not ok:
            p["error"] = str(payload)
        elif payload[0] != 0:
            p["error"] = payload[1]
        p["t_wait"] = time.monotonic()
        self.overlay.set_text(sub=tr("Waiting for the adapters to become ready …"))
        self._run(fetch_adapters, self._on_poll)

    def _pending_state(self, adapters: list[Adapter]) -> tuple[bool, str]:
        by_idx = {a.index: a for a in adapters}
        by_pnp = {a.pnp.upper(): a for a in adapters if a.pnp}
        for i in self._pending["enable"]:
            a = by_idx.get(i)
            if a is None and i >= PNP_INDEX_BASE:      # re-enabled adapter gets its real interface index
                a = by_pnp.get(self._pending["pnp"].get(i, "").upper())
            if a is None or not a.enabled:
                return False, tr("“{n}” to be enabled", n=self.display_name(a) if a else i)
            # physical adapters get up to 12 s to receive an IP; virtual / address-less ones are not awaited
            if (a.is_up and a.hardware and not a.virtual and not a.primary_ip
                    and time.monotonic() - self._pending["t_wait"] < 12):
                return False, tr("“{n}” to get an IP address", n=self.display_name(a))
        for i in self._pending["disable"]:
            a = by_idx.get(i)
            if a is not None and a.enabled:
                return False, tr("“{n}” to be disabled", n=self.display_name(a))
        return True, ""

    def _on_poll(self, ok: bool, payload) -> None:
        p = self._pending
        if p is None:
            self._end_busy()
            return
        ready, waiting = False, ""
        if ok:
            self._sync_cards(payload)
            ready, waiting = self._pending_state(payload)
        elapsed = time.monotonic() - p["t_wait"]
        if ready or p["error"] or elapsed > 20:
            self._finish_pending(ready)
            return
        self.overlay.set_text(sub=tr("Waiting for {w} … ({s} s)", w=waiting, s=int(elapsed)))
        QTimer.singleShot(900, lambda: self._run(fetch_adapters, self._on_poll))

    def _finish_pending(self, ready: bool) -> None:
        p, self._pending = self._pending, None
        for i in (*p["enable"], *p["disable"]):
            self.probes.pop(i, None)
        self._end_busy()
        for card in self.cards.values():
            card.refresh_view()
        if p["error"]:
            OPLOG.error(tr("Error while applying changes:\n\n{e}", e=p["error"]))
            self.set_status("❌ " + tr("Some changes could not be applied."))
            self._info(tr("Error while applying changes:\n\n{e}", e=p["error"]), QMessageBox.Icon.Critical)
        elif ready:
            self.set_status("✅ " + tr("Changes applied successfully."))
            self._notify(APP_NAME, "✅ " + tr("Adapter changes applied."))
        else:
            self.set_status("⚠️ " + tr("Command sent, but the adapter is not fully ready yet."))
        self._net_sig = None
        if PREFS.get("auto_public_ip"):
            QTimer.singleShot(1200, self.fetch_public)

    def on_toggle(self, index: int, enable: bool) -> None:
        a = next((x for x in self.adapters if x.index == index), None)
        name = self.display_name(a) if a else str(index)
        if enable:
            self._apply([index], [], tr("Enabling “{n}”", n=name))
        else:
            self._apply([], [index], tr("Disabling “{n}”", n=name))

    def on_exclusive(self, index: int, ask: bool | None = None) -> None:
        if self._busy:
            return
        target = next((x for x in self.adapters if x.index == index), None)
        if target is None:
            return
        others = [a for a in self._scope_adapters() if a.index != index and a.enabled]
        if ask is None:
            ask = self.chk_confirm.isChecked()
        tname = self.display_name(target)
        if ask and not self._confirm(tr("Keep only “{n}” enabled and disable {k} other adapter(s)?", n=tname, k=len(others))):
            OPLOG.info(tr("Cancelled by user."))
            self.refresh()
            return
        self._apply([index] if not target.enabled else [], [a.index for a in others],
                    tr("Switching to “{n}”", n=tname))

    def enable_all(self) -> None:
        self._apply([a.index for a in self._scope_adapters() if not a.enabled], [], tr("Enabling all adapters"))

    # --------------------------------------------------------------- profiles
    def _profiles(self) -> dict[str, dict[str, bool]]:
        return PREFS.get_json("profiles", {})

    def _fill_profile_menu(self, menu: QMenu, manage: bool) -> None:
        menu.clear()
        profiles = self._profiles()
        if manage:
            menu.addAction("💾 " + tr("Save current state as profile …")).triggered.connect(self.save_profile)
            menu.addSeparator()
        if not profiles:
            menu.addAction(tr("(no saved profiles)")).setEnabled(False)
        for name in profiles:
            if manage:
                sub = menu.addMenu(f"📁 {name}")
                sub.addAction(tr("Apply")).triggered.connect(lambda _=False, n=name: self.apply_profile(n))
                sub.addAction(tr("Delete")).triggered.connect(lambda _=False, n=name: self.delete_profile(n))
            else:
                act = menu.addAction(f"📁 {name}")
                act.setEnabled(not self._busy and self.admin)
                act.triggered.connect(lambda _=False, n=name: self.apply_profile(n))

    def save_profile(self) -> None:
        name = self._ask_text(tr("Save profile"), tr("Profile name (e.g. “Home internet”):"))
        if not name:
            return
        profiles = self._profiles()
        profiles[name] = {a.name: a.enabled for a in self._scope_adapters()}
        PREFS.set_json("profiles", profiles)
        self.set_status("✅ " + tr("Profile “{n}” saved.", n=name))

    def delete_profile(self, name: str) -> None:
        profiles = self._profiles()
        if profiles.pop(name, None) is not None:
            PREFS.set_json("profiles", profiles)
            self.set_status(tr("Profile “{n}” deleted.", n=name))

    def apply_profile(self, name: str) -> None:
        prof = self._profiles().get(name)
        if not prof:
            return
        by_name = {a.name: a for a in self.adapters}
        enable, disable = [], []
        for n, want in prof.items():
            a = by_name.get(n)
            if a is None:
                continue
            if want and not a.enabled:
                enable.append(a.index)
            elif not want and a.enabled:
                disable.append(a.index)
        self._apply(enable, disable, tr("Applying profile “{n}”", n=name))

    # ---------------------------------------------- display names / hiding
    def _card_refresh(self, a: Adapter) -> None:
        card = self.cards.get(a.index)
        if card:
            key = self._nick_key(a)
            card.update_from(a, self.probes.get(a.index), a.index in self.testing,
                             self.nicks.get(key, ""), key in self.hidden_keys)

    def on_rename(self, index: int, text: str) -> None:
        a = next((x for x in self.adapters if x.index == index), None)
        if a is None:
            return
        key = self._nick_key(a)
        if text:
            self.nicks[key] = text
            self.set_status("✅ " + tr("Display name of “{o}” is now “{n}”.", o=a.name, n=text))
        else:
            self.nicks.pop(key, None)
            self.set_status(tr("Display name removed; “{o}” is shown again.", o=a.name))
        PREFS.set_json("nicknames", self.nicks)
        self._card_refresh(a)
        self.page_monitor.refresh_combo()
        self.page_speed.refresh_adapters()

    def on_win_rename(self, index: int) -> None:
        a = next((x for x in self.adapters if x.index == index), None)
        if a is None:
            return
        new = self._ask_text(tr("Rename in the system"), tr("New adapter name (it changes in the system too):"), a.name)
        if not new or new == a.name:
            return
        if re.search(r'[\\/:*?"<>|]', new):
            self._info(tr('The name must not contain any of these characters:  \\ / : * ? " < > |'))
            return
        old = a.name
        self._task(tr("Renaming “{n}”", n=old), tr("New name: {n}", n=new), rename_adapter, (index, new),
                   tr("Adapter renamed to “{n}” in the system.", n=new), after=lambda: self._remap_profiles(old, new))

    def _remap_profiles(self, old: str, new: str) -> None:
        profiles = self._profiles()
        changed = False
        for prof in profiles.values():
            if old in prof:
                prof[new] = prof.pop(old)
                changed = True
        if changed:
            PREFS.set_json("profiles", profiles)

    def on_hide(self, index: int) -> None:
        a = next((x for x in self.adapters if x.index == index), None)
        if a is None:
            return
        key = self._nick_key(a)
        name = self.display_name(a)
        if key in self.hidden_keys:
            self.hidden_keys.discard(key)
            self.set_status(tr("“{n}” is shown in the list again.", n=name))
        else:
            self.hidden_keys.add(key)
            self.set_status(tr("“{n}” was hidden from the list and from group actions (Tools → Show hidden adapters).", n=name))
        PREFS.set_json("hidden", sorted(self.hidden_keys))
        self._card_refresh(a)
        self.apply_filter()

    def unhide_all(self) -> None:
        self.hidden_keys.clear()
        PREFS.set_json("hidden", [])
        for a in self.adapters:
            self._card_refresh(a)
        self.apply_filter()
        self.set_status("✅ " + tr("All adapters are visible again."))

    # ------------------------------------------- DNS / DHCP / IP / priority
    def _task(self, title: str, sub: str, fn, args: tuple, success: str, after=None) -> None:
        if self._busy or self._need_admin():
            return
        OPLOG.info(title + (f" — {sub}" if sub else ""))
        self._begin_busy(title, sub)
        self._run(fn, lambda ok, p: self._on_task_done(ok, p, success, after), *args)

    def _on_task_done(self, ok: bool, payload, success: str, after=None) -> None:
        self._end_busy()
        err = str(payload) if not ok else (payload[1] if payload[0] != 0 else "")
        if err:
            OPLOG.error(tr("Error:\n\n{e}", e=err))
            self.set_status("❌ " + tr("The operation failed."))
            self._info(tr("Error:\n\n{e}", e=err), QMessageBox.Icon.Critical)
        else:
            if after:
                after()
            self.set_status(f"✅ {success}")
            self._notify(APP_NAME, f"✅ {success}")
        QTimer.singleShot(600, self.refresh)

    def on_dns(self, index: int, key: str) -> None:
        a = next((x for x in self.adapters if x.index == index), None)
        if a is None:
            return
        servers = key
        if key == "custom":
            text = self._ask_text(tr("Custom DNS"), tr("DNS addresses (separate several with commas):"), ", ".join(a.dns))
            if not text:
                return
            parts = [x.strip() for x in re.split(r"[,\s]+", text) if x.strip()]
            try:
                for x in parts:
                    ipaddress.ip_address(x)
            except ValueError:
                self._info(tr("One of the addresses is not valid."))
                return
            servers = ",".join(parts)
        label = tr("Automatic") if servers == "auto" else servers
        dn = self.display_name(a)
        self._task(tr("Setting DNS of “{n}”", n=dn), f"DNS ← {label}", set_dns, (index, servers),
                   tr("DNS of “{n}” was updated.", n=dn))

    def on_renew(self, index: int) -> None:
        a = next((x for x in self.adapters if x.index == index), None)
        if a:
            dn = self.display_name(a)
            self._task(tr("Renewing IP of “{n}”", n=dn), tr("Requesting a new address from DHCP …"),
                       renew_dhcp, (index,), tr("IP of “{n}” was renewed.", n=dn))

    def on_metric(self, index: int, metric: str) -> None:
        a = next((x for x in self.adapters if x.index == index), None)
        if a is None:
            return
        dn = self.display_name(a)
        if metric == "auto":
            self._task(tr("Resetting priority of “{n}”", n=dn), "", set_metric, (index, "auto"),
                       tr("Priority of “{n}” is automatic again.", n=dn))
        else:
            self._task(tr("Setting “{n}” as preferred", n=dn), tr("Lowering its interface metric …"),
                       set_metric, (index, metric), tr("“{n}” is now the preferred adapter for internet.", n=dn))

    def on_ip_config(self, index: int) -> None:
        a = next((x for x in self.adapters if x.index == index), None)
        if a is None or self._busy:
            return
        dlg = IpConfigDialog(a, self)
        if not dlg.exec() or not dlg.result_cfg:
            return
        cfg, dn = dlg.result_cfg, self.display_name(a)
        if cfg["mode"] == "dhcp":
            self._task(tr("Switching “{n}” to DHCP", n=dn), "", set_dhcp, (index,), tr("“{n}” now uses DHCP.", n=dn))
        else:
            self._task(tr("Applying static IP to “{n}”", n=dn), cfg["ip"], set_static_ip,
                       (index, cfg["ip"], cfg["prefix"], cfg["gw"], cfg["dns"]), tr("Static IP applied to “{n}”.", n=dn))

    def do_flush_dns(self) -> None:
        self._task(tr("Flushing DNS cache"), tr("Please wait …"), flush_dns, (), tr("DNS cache cleared."))

    # ----------------------------------------------- public IP & internet test
    def fetch_public(self) -> None:
        if self._pub_loading:
            return
        self._pub_loading = True
        self.ipbar.set_loading()
        self._run(fetch_public_ip, self._on_public)

    def _on_public(self, ok: bool, payload) -> None:
        self._pub_loading = False
        if ok:
            self.public = payload
            self.ipbar.set_info(payload)
            where = " · ".join(x for x in (payload.get("country"), payload.get("city"), payload.get("isp")) if x)
            OPLOG.ok(tr("Public IP: {ip}", ip=payload.get("ip", "?")) + (f"  ({where})" if where else ""))
        else:
            self.public = None
            self.ipbar.set_error(tr("No internet, or the IP lookup services did not respond."))
            self.ipbar.setToolTip(str(payload))
            OPLOG.warn(tr("No internet, or the IP lookup services did not respond."))

    def probe(self, index: int) -> None:
        if index in self.testing or self._busy:
            return
        a = next((x for x in self.adapters if x.index == index), None)
        if a is None or not a.primary_ip:
            return
        self.testing.add(index)
        card = self.cards.get(index)
        if card:
            card.set_probe_state(self.probes.get(index), True)
        self._run(probe_adapter, lambda ok, p, i=index: self._on_probe(i, ok, p), (a.primary_ip, a.device))

    def _on_probe(self, index: int, ok: bool, payload) -> None:
        self.testing.discard(index)
        a = next((x for x in self.adapters if x.index == index), None)
        if a is None:
            return
        self.probes[index] = payload if ok else {"src": a.primary_ip, "latency": None, "pub": None, "error": str(payload)}
        pr, dn = self.probes[index], self.display_name(a)
        if pr.get("latency") is None:
            OPLOG.warn(tr("Internet test via “{n}”: {e}", n=dn, e=tr("No internet") if pr.get("error") in ("", "No internet", None) else pr["error"]))
        else:
            pub = (pr.get("pub") or {}).get("ip", "—")
            OPLOG.ok(tr("Internet test via “{n}”: {ms:.0f} ms, public IP {ip}", n=dn, ms=pr["latency"], ip=pub))
        card = self.cards.get(index)
        if card:
            card.set_probe_state(self.probes[index], False)

    def probe_all(self) -> None:
        targets = [a for a in self._scope_adapters() if a.is_up and a.primary_ip]
        if not targets:
            self.set_status(tr("There is no connected adapter to test."))
            return
        self.set_status(tr("Testing the internet on {n} adapter(s) …", n=len(targets)))
        for a in targets:
            self.probe(a.index)

    # -------------------------------------------------------- settings data
    def export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("Export settings"), "nic-switcher-settings.json", "JSON (*.json)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(PREFS.export_all(), fh, ensure_ascii=False, indent=2, default=str)
                self.set_status("✅ " + tr("Settings exported."))
            except OSError as e:
                self._info(str(e), QMessageBox.Icon.Critical)

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Import settings"), "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("bad file")
            PREFS.import_all(data)
        except (OSError, ValueError) as e:
            OPLOG.error(tr("The file could not be imported: {e}", e=e))
            self._info(tr("The file could not be imported: {e}", e=e), QMessageBox.Icon.Critical)
            return
        self._reload_after_prefs_change()
        self.set_status("✅ " + tr("Settings imported."))

    def reset_settings(self) -> None:
        if not self._confirm(tr("Reset all settings, profiles, names and history to defaults?")):
            return
        PREFS.reset()
        self._reload_after_prefs_change()
        self.set_status("✅ " + tr("Settings were reset."))

    def _reload_after_prefs_change(self) -> None:
        self.nicks = PREFS.get_json("nicknames", {})
        self.hidden_keys = set(PREFS.get_json("hidden", []))
        self.usage_all = self._load_usage()
        apply_language(PREFS.get("lang"))
        self.apply_theme(PREFS.get("theme"), rebuild=False)
        self.timer.setInterval(PREFS.get("refresh_sec") * 1000)
        QTimer.singleShot(0, self._rebuild_ui)

    def _open_ncpa(self) -> None:
        try:
            open_os_network_settings()
        except Exception as e:  # noqa: BLE001
            self._info(tr("Could not open the settings: {e}", e=e))

    # ----------------------------------------------------------------- exit
    def quit_app(self) -> None:
        OPLOG.info(tr("{a} is closing.", a=APP_NAME))
        self._quitting = True
        self.timer.stop()
        self._shutdown_pages()
        self.stop_stats()
        self._save_usage()
        n = self.usage_numbers()
        OPLOG.info(tr("Usage this session: ↓ {d} ↑ {u}", d=fmt_bytes(n["s_rx"]), u=fmt_bytes(n["s_tx"])))
        if self.tray:
            self.tray.hide()
        QThreadPool.globalInstance().waitForDone(2500)
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._quitting and PREFS.get("close_to_tray") and self.tray and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self._notify(APP_NAME, tr("The app keeps running in the system tray. Right-click the icon to quit."))
            return
        self.quit_app()
        event.accept()


# ----------------------------------------------------------------------------
# Build helper:  python nic_switcher.py --build
# ----------------------------------------------------------------------------
def build_executable() -> int:
    """Create a standalone executable with PyInstaller (Windows/Linux: one file, macOS: .app bundle)."""
    if FROZEN:
        print("Run --build from the Python source, not from the compiled program.")
        return 1
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed.  Run:  pip install pyinstaller")
        return 1
    app = QApplication.instance() or QApplication(sys.argv[:1])
    tmp = tempfile.mkdtemp(prefix="nicswitcher_build_")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", APP_ID,
           "--exclude-module", "tkinter", "--exclude-module", "unittest", "--exclude-module", "pydoc"]
    if IS_WINDOWS:
        ico = os.path.join(tmp, "app.ico")
        v = (list(_vtuple(APP_VERSION)) + [0, 0, 0, 0])[:4]
        ver_file = os.path.join(tmp, "version.txt")
        with open(ver_file, "w", encoding="utf-8") as fh:
            fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v[0]}, {v[1]}, {v[2]}, {v[3]}), prodvers=({v[0]}, {v[1]}, {v[2]}, {v[3]}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{DEVELOPER_NAME}'),
      StringStruct('FileDescription', '{APP_NAME} - network adapter manager and toolbox'),
      StringStruct('FileVersion', '{APP_VERSION}'),
      StringStruct('InternalName', '{APP_ID}'),
      StringStruct('LegalCopyright', 'MIT License - {DEVELOPER_NAME}'),
      StringStruct('OriginalFilename', '{APP_ID}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{APP_VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
""")
        repo_ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")   # multi-size icon from the repository
        if os.path.exists(repo_ico):
            icon_args = ["--icon", repo_ico]
        else:
            icon_args = ["--icon", ico] if make_icon().pixmap(256, 256).save(ico, "ICO") else []
        cmd += ["--onefile", "--noconsole", "--uac-admin", *icon_args, "--version-file", ver_file]
        result = f"dist{os.sep}{APP_ID}.exe"
    elif IS_MAC:
        cmd += ["--windowed", "--osx-bundle-identifier", f"com.{APP_ID.lower()}.app"]
        result = f"dist/{APP_ID}.app"
    else:
        cmd += ["--onefile"]
        result = f"dist/{APP_ID}"
    cmd.append(os.path.abspath(__file__))
    print(" ".join(cmd))
    rc = subprocess.call(cmd)
    if rc == 0:
        print(f"\nDone → {result}")
    del app
    return rc


def main() -> int:
    if "--version" in sys.argv:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if "--build" in sys.argv:
        return build_executable()
    if not SUPPORTED:
        print(f"{APP_NAME} supports Windows, Linux and macOS only.")
        return 1

    if IS_WINDOWS:
        if not is_admin() and "--elevated" not in sys.argv and relaunch_as_admin():
            return 0  # the elevated copy is now running
        try:  # own taskbar identity (correct icon grouping)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.App")
        except Exception:
            pass
    admin = can_change_system()   # Windows: elevated · Linux/macOS: root or able to ask for a password

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setWindowIcon(make_icon())
    apply_language(PREFS.get("lang"))
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())

    lock = QLockFile(os.path.join(tempfile.gettempdir(), f"{APP_ID}.lock"))   # single instance
    if not lock.tryLock(300):
        QMessageBox.information(None, APP_NAME, tr("The app is already running. Look for its icon in the system tray."))
        return 0

    hidden = "--minimized" in sys.argv
    win = MainWindow(admin, start_hidden=hidden)
    if not (hidden and win.tray):
        win.show()
    return app.exec()


# ----------------------------------------------------------------------------
# Persian translation table (English text is the key)
# ----------------------------------------------------------------------------
FA.update({
    # navigation / pages
    "Adapters": "آداپتورها", "Monitor": "مانیتور", "Speed test": "تست سرعت", "Toolbox": "جعبه‌ابزار",
    "Settings": "تنظیمات", "About": "درباره",
    "Network adapters": "آداپتورهای شبکه", "Network toolbox": "جعبه‌ابزار شبکه",
    "Live traffic monitor": "مانیتور زندهٔ ترافیک",
    "Real-time download and upload speed of every adapter.": "سرعت لحظه‌ای دانلود و آپلود هر آداپتور.",
    "Diagnostics and repair tools — everything you need in one place.": "ابزارهای عیب‌یابی و تعمیر شبکه — همه‌چیز در یک‌جا.",
    "Customize the look and behavior of the app.": "ظاهر و رفتار برنامه را شخصی‌سازی کنید.",
    "Measures latency, download and upload — optionally through one specific adapter.":
        "تأخیر، سرعت دانلود و آپلود را می‌سنجد — در صورت تمایل از طریق یک آداپتور مشخص.",
    "Network adapter manager & toolbox": "مدیریت آداپتورهای شبکه و جعبه‌ابزار اینترنت",
    "Administrator": "مدیر سیستم", "Limited mode": "حالت محدود", "Limited": "محدود",
    "Toggle dark / light theme": "تغییر تم تاریک / روشن",
    "Loading …": "در حال بارگذاری …",
    # status
    "Connected": "متصل", "Disconnected": "قطع‌شده", "Disabled": "غیرفعال", "Unknown": "نامشخص",
    "Enabled": "فعال", "auto": "خودکار", "manual": "دستی",
    "{n} adapters  •  {up} connected  •  {off} disabled": "{n} آداپتور  •  {up} متصل  •  {off} غیرفعال",
    "Last updated: {t}": "آخرین به‌روزرسانی: {t}",
    "Could not read adapters: {e}": "خواندن آداپتورها ممکن نشد: {e}",
    "The app has no administrator rights, so enabling or disabling adapters is not possible. You can still view everything.":
        "برنامه دسترسی مدیر ندارد، پس فعال/غیرفعال کردن آداپتورها ممکن نیست. همه‌چیز را می‌توانید ببینید.",
    # IP bar
    "Your public IP (main internet route)": "IP عمومی شما (مسیر اصلی اینترنت)",
    "Copy": "کپی", "Copied": "کپی شد", "Check again": "بررسی دوباره", "Not checked yet": "هنوز بررسی نشده",
    "Checking …": "در حال بررسی …", "Contacting IP lookup services": "ارتباط با سرویس‌های تشخیص IP",
    "Source: {p}   |   Time zone: {tz}": "منبع: {p}   |   منطقهٔ زمانی: {tz}",
    "No internet, or the IP lookup services did not respond.": "اینترنت در دسترس نیست یا سرویس‌های تشخیص IP پاسخ ندادند.",
    "Check public IP": "بررسی IP عمومی", "Check public IP automatically": "بررسی خودکار IP عمومی",
    # adapters page
    "Search by name, IP or MAC …   (Ctrl+F)": "جستجو بر اساس نام، IP یا MAC …   (Ctrl+F)",
    "Refresh": "تازه‌سازی", "Test all": "تست همه", "Profiles": "پروفایل‌ها", "Tools": "ابزارها",
    "Measures latency and public IP of every connected adapter separately": "تأخیر و IP عمومی هر آداپتور متصل را جداگانه می‌سنجد",
    "Enable all adapters": "فعال‌سازی همهٔ آداپتورها", "Flush DNS cache": "پاک کردن کش DNS",
    "Show hidden adapters": "نمایش آداپتورهای مخفی‌شده",
    "Open the system network settings": "باز کردن تنظیمات شبکهٔ سیستم‌عامل",
    "Virtual / VPN adapters": "آداپتورهای مجازی / VPN",
    "Ask for confirmation before “Only this one”": "پرسیدن تأیید قبل از «فقط این را فعال کن»",
    "No adapters to show.": "هیچ آداپتوری برای نمایش وجود ندارد.",
    # card
    "Gateway": "گیت‌وی (Gateway)", "MAC address": "آدرس MAC", "Link speed": "سرعت لینک", "Live traffic": "ترافیک لحظه‌ای",
    "Total usage": "مجموع مصرف", "Public IP of this adapter": "IP عمومی این آداپتور", "Latency": "تأخیر", "Metric": "Metric",
    "Double-click to rename": "برای تغییر نام دوبار کلیک کنید", "Change display name": "تغییر نام نمایشی",
    "Enter = save   |   Esc = cancel   |   empty = original name": "Enter = ذخیره   |   Esc = انصراف   |   خالی = نام اصلی",
    "Original name: {n}": "نام اصلی: {n}",
    "Live traffic — blue: download, green: upload": "ترافیک لحظه‌ای — آبی: دانلود، سبز: آپلود",
    "Only this one (disable others)": "فقط این را فعال کن (بقیه غیرفعال)", "Only this one": "فقط این را فعال کن",
    "Test internet": "تست اینترنت", "Measures latency and public IP through this adapter only": "تأخیر و IP عمومی را فقط از مسیر همین آداپتور می‌سنجد",
    "Copy IP": "کپی IP", "More": "بیشتر", "Change DNS": "تغییر DNS", "Custom …": "سفارشی …",
    "Automatic (DHCP)": "خودکار (DHCP)", "IP configuration (DHCP / static) …": "تنظیم IP (DHCP / ثابت) …",
    "Renew IP (DHCP)": "تمدید IP (DHCP)", "Internet priority": "اولویت اینترنت",
    "Make this the preferred adapter": "این آداپتور را اولویت اول کن", "Reset priority to automatic": "بازنشانی اولویت به حالت خودکار",
    "Reset display name": "بازنشانی نام نمایشی", "Rename in the system …": "تغییر نام در خود سیستم‌عامل …",
    "Hide from list": "مخفی کردن از لیست", "Show in list again": "نمایش دوباره در لیست",
    "Copy MAC address": "کپی آدرس MAC", "Copy all details": "کپی همهٔ اطلاعات",
    "Testing …": "در حال تست …", "No internet": "بدون اینترنت",
    # IP config dialog
    "IP configuration — {name}": "تنظیمات IP — {name}",
    "Obtain IP address and DNS automatically (DHCP)": "دریافت خودکار IP و DNS (DHCP)",
    "Use a static IP address": "استفاده از IP ثابت", "IP address": "آدرس IP", "Prefix length": "طول پیشوند (Prefix)",
    "DNS servers (comma separated)": "سرورهای DNS (با ویرگول جدا کنید)", "Apply": "اعمال", "Cancel": "انصراف",
    "One of the addresses is not valid.": "یکی از آدرس‌ها نامعتبر است.",
    # busy / operations
    "Please wait …": "لطفاً تا پایان عملیات صبر کنید …",
    "Sending the command to the system …": "در حال ارسال دستور به سیستم‌عامل …",
    "Waiting for the adapters to become ready …": "در انتظار آماده شدن آداپتورها …",
    "Waiting for {w} … ({s} s)": "در انتظار {w} … ({s} ثانیه)",
    "“{n}” to be enabled": "فعال شدن «{n}»", "“{n}” to be disabled": "غیرفعال شدن «{n}»",
    "“{n}” to get an IP address": "دریافت IP برای «{n}»",
    "Enabling “{n}”": "در حال فعال‌سازی «{n}»", "Disabling “{n}”": "در حال غیرفعال‌سازی «{n}»",
    "Switching to “{n}”": "در حال سوییچ به «{n}»", "Enabling all adapters": "در حال فعال‌سازی همهٔ آداپتورها",
    "Applying profile “{n}”": "در حال اعمال پروفایل «{n}»", "Nothing to change.": "تغییری لازم نیست.",
    "Keep only “{n}” enabled and disable {k} other adapter(s)?": "فقط «{n}» فعال بماند و {k} آداپتور دیگر غیرفعال شوند؟",
    "Changes applied successfully.": "تغییرات با موفقیت اعمال شد.", "Adapter changes applied.": "تغییرات آداپتورها اعمال شد.",
    "Some changes could not be applied.": "بعضی تغییرات انجام نشد.",
    "Command sent, but the adapter is not fully ready yet.": "دستور ارسال شد اما آداپتور هنوز کاملاً آماده نیست.",
    "Error while applying changes:\n\n{e}": "خطا در اعمال تغییرات:\n\n{e}", "Error:\n\n{e}": "خطا:\n\n{e}",
    "The operation failed.": "عملیات ناموفق بود.",
    "Administrator rights are required for this action.": "برای این کار باید برنامه را با دسترسی Administrator اجرا کنید.",
    "Confirm": "تأیید عملیات", "Yes, continue": "بله، ادامه بده", "OK": "باشه",
    # profiles / names
    "Save current state as profile …": "ذخیرهٔ وضعیت فعلی به‌عنوان پروفایل …", "(no saved profiles)": "(پروفایلی ذخیره نشده)",
    "Delete": "حذف", "Save profile": "ذخیرهٔ پروفایل", "Profile name (e.g. “Home internet”):": "نام پروفایل (مثلاً «اینترنت خانه»):",
    "Profile “{n}” saved.": "پروفایل «{n}» ذخیره شد.", "Profile “{n}” deleted.": "پروفایل «{n}» حذف شد.",
    "Display name of “{o}” is now “{n}”.": "نام نمایشی «{o}» به «{n}» تغییر کرد.",
    "Display name removed; “{o}” is shown again.": "نام نمایشی حذف شد؛ «{o}» دوباره نمایش داده می‌شود.",
    "Rename in the system": "تغییر نام در سیستم‌عامل", "New adapter name (it changes in the system too):": "نام جدید آداپتور (در خود سیستم‌عامل هم تغییر می‌کند):",
    "The name must not contain any of these characters:  \\ / : * ? \" < > |": "نام نباید شامل این نویسه‌ها باشد:  \\ / : * ? \" < > |",
    "Renaming “{n}”": "در حال تغییر نام «{n}»", "New name: {n}": "نام جدید: {n}",
    "Adapter renamed to “{n}” in the system.": "نام آداپتور در سیستم‌عامل به «{n}» تغییر کرد.",
    "“{n}” is shown in the list again.": "«{n}» دوباره در لیست نمایش داده می‌شود.",
    "“{n}” was hidden from the list and from group actions (Tools → Show hidden adapters).":
        "«{n}» از لیست و عملیات گروهی مخفی شد (از منوی ابزارها می‌توانید مخفی‌ها را ببینید).",
    "All adapters are visible again.": "همهٔ آداپتورها دوباره نمایش داده می‌شوند.",
    # dns / ip / priority
    "Custom DNS": "DNS سفارشی", "DNS addresses (separate several with commas):": "آدرس DNS (چند آدرس را با ویرگول جدا کنید):",
    "Automatic": "خودکار", "Setting DNS of “{n}”": "در حال تنظیم DNS «{n}»", "DNS of “{n}” was updated.": "DNS آداپتور «{n}» تنظیم شد.",
    "Renewing IP of “{n}”": "در حال تمدید IP «{n}»", "Requesting a new address from DHCP …": "درخواست IP جدید از DHCP …",
    "IP of “{n}” was renewed.": "IP آداپتور «{n}» تمدید شد.",
    "Resetting priority of “{n}”": "در حال بازنشانی اولویت «{n}»", "Priority of “{n}” is automatic again.": "اولویت «{n}» دوباره خودکار شد.",
    "Setting “{n}” as preferred": "در حال اولویت‌دهی به «{n}»", "Lowering its interface metric …": "کاهش Metric رابط …",
    "“{n}” is now the preferred adapter for internet.": "«{n}» اکنون آداپتور اصلی اینترنت است.",
    "Switching “{n}” to DHCP": "در حال تغییر «{n}» به DHCP", "“{n}” now uses DHCP.": "«{n}» اکنون از DHCP استفاده می‌کند.",
    "Applying static IP to “{n}”": "در حال اعمال IP ثابت روی «{n}»", "Static IP applied to “{n}”.": "IP ثابت روی «{n}» اعمال شد.",
    "Flushing DNS cache": "در حال پاک کردن کش DNS", "DNS cache cleared.": "کش DNS پاک شد.",
    "Testing the internet on {n} adapter(s) …": "در حال تست اینترنت {n} آداپتور …",
    "There is no connected adapter to test.": "هیچ آداپتور متصلی برای تست وجود ندارد.",
    # settings
    "Appearance": "ظاهر", "Language": "زبان", "The interface switches instantly.": "رابط کاربری بلافاصله عوض می‌شود.",
    "Theme": "تم", "Dark": "تاریک", "Light": "روشن", "Accent color": "رنگ اصلی",
    "Animations": "انیمیشن‌ها", "Smooth transitions and effects. Turn off on slow computers.": "جلوه‌ها و انتقال‌های نرم. روی سیستم‌های ضعیف خاموش کنید.",
    "Behavior": "رفتار برنامه", "Adapter refresh interval": "فاصلهٔ به‌روزرسانی آداپتورها",
    "{n} seconds": "{n} ثانیه", "How often adapter status is re-read from the system.": "هر چند وقت یک‌بار وضعیت آداپتورها از سیستم‌عامل خوانده شود.",
    "Live traffic monitoring": "پایش زندهٔ ترافیک", "Per-second speed graphs (runs only while the window is visible).": "نمودار سرعت هر ثانیه (فقط وقتی پنجره دیده می‌شود).",
    "At startup and whenever the internet route changes.": "هنگام شروع و هر بار که مسیر اینترنت عوض شود.",
    "Tray notifications": "اعلان‌های سیستم‌تری", "Show a balloon when a change completes.": "پس از اتمام هر تغییر یک اعلان نشان بده.",
    "Close button minimizes to tray": "دکمهٔ بستن به سیستم‌تری می‌رود", "Keeps the app running in the system tray.": "برنامه در سیستم‌تری در حال اجرا می‌ماند.",
    "Start at system startup": "اجرا هنگام روشن شدن سیستم",
    "Launches the app automatically (minimized to the tray) every time you sign in.": "برنامه هر بار که وارد سیستم می‌شوید خودکار (بی‌صدا و در سیستم‌تری) اجرا می‌شود.",
    "Data": "داده‌ها", "Export settings": "خروجی گرفتن از تنظیمات", "Import settings": "وارد کردن تنظیمات",
    "Unhide all adapters": "نمایش همهٔ آداپتورهای مخفی", "Reset everything": "بازنشانی همه‌چیز",
    "Exports include display names, hidden adapters, profiles and preferences.": "شامل نام‌های نمایشی، آداپتورهای مخفی، پروفایل‌ها و ترجیحات است.",
    "The app will start automatically at startup.": "برنامه هنگام روشن شدن سیستم خودکار اجرا خواهد شد.", "Autostart removed.": "اجرای خودکار حذف شد.",
    "Settings exported.": "تنظیمات ذخیره شد.", "Settings imported.": "تنظیمات وارد شد.", "Settings were reset.": "تنظیمات بازنشانی شد.",
    "The file could not be imported: {e}": "وارد کردن فایل ممکن نشد: {e}",
    "Reset all settings, profiles, names and history to defaults?": "همهٔ تنظیمات، پروفایل‌ها، نام‌ها و تاریخچه به حالت پیش‌فرض برگردد؟",
    "Could not open the settings: {e}": "باز کردن تنظیمات ممکن نشد: {e}",
    # about
    "Version": "نسخه", "Developer": "توسعه‌دهنده", "License": "مجوز", "Python": "پایتون", "System": "سیستم", "Privileges": "سطح دسترسی",
    "Mode": "حالت اجرا", "Standalone executable": "فایل اجرایی مستقل", "Python script": "اسکریپت پایتون",
    "Report an issue": "گزارش مشکل", "Check for updates": "بررسی به‌روزرسانی", "Copy diagnostics": "کپی اطلاعات عیب‌یابی",
    "Diagnostics copied to clipboard.": "اطلاعات عیب‌یابی کپی شد.", "Could not check for updates.": "بررسی به‌روزرسانی ممکن نشد.",
    "Version {v} is available.": "نسخهٔ {v} منتشر شده است.", "You are up to date.": "برنامه به‌روز است.",
    "Built with Python and PyQt6. Public IP data: ipwho.is, ipapi.co, ipinfo.io, Cloudflare, ipify. Speed test: Cloudflare. Free and open source.":
        "ساخته‌شده با پایتون و PyQt6. داده‌های IP عمومی: ipwho.is، ipapi.co، ipinfo.io، Cloudflare و ipify. تست سرعت: Cloudflare. رایگان و متن‌باز.",
    "Developed by": "توسعه‌دهنده:",
    # tray / misc
    "Show window": "نمایش پنجره", "Quit": "خروج",
    "The app keeps running in the system tray. Right-click the icon to quit.": "برنامه در سیستم‌تری در حال اجراست. برای خروج روی آیکون راست‌کلیک کنید.",
    "The app is already running. Look for its icon in the system tray.": "برنامه از قبل در حال اجراست. آیکون آن را در سیستم‌تری (کنار ساعت) ببینید.",
    # monitor
    "All adapters": "همهٔ آداپتورها", "Download": "دانلود", "Upload": "آپلود",
    "Peak download (last {n} s)": "اوج دانلود ({n} ثانیهٔ اخیر)", "Transferred this session": "مصرف این نشست",
    "Adapter": "آداپتور", "Session": "نشست", "{n} s ago": "{n} ثانیه پیش", "now": "اکنون",
    # speed test
    "Ping": "پینگ", "Jitter": "جیتر", "Start test": "شروع تست", "Stop": "توقف",
    "Automatic (system default route)": "خودکار (مسیر پیش‌فرض سیستم)", "Measuring latency …": "در حال سنجش تأخیر …",
    "Uses Cloudflare's public speed endpoints. A test transfers roughly 50–150 MB.": "از سرورهای عمومی Cloudflare استفاده می‌کند. هر تست حدود ۵۰ تا ۱۵۰ مگابایت داده مصرف می‌کند.",
    "History": "تاریخچه", "Time": "زمان", "Ready": "آماده", "Done": "انجام شد", "Failed": "ناموفق", "Stopped": "متوقف شد",
    # toolbox
    "DNS lookup": "جستجوی DNS", "Traceroute": "ردیابی مسیر", "Port check": "بررسی پورت", "IP lookup": "جستجوی IP",
    "DNS benchmark": "بنچمارک DNS", "Connections": "اتصالات", "System info": "اطلاعات سیستم", "Repair": "تعمیر شبکه",
    "Run": "اجرا", "Copy output": "کپی خروجی", "Clear": "پاک کردن", "Host or IP": "میزبان یا IP", "Count": "تعداد",
    "Domain name": "نام دامنه", "DNS server (optional)": "سرور DNS (اختیاری)", "Ports": "پورت‌ها", "IP or domain (optional)": "IP یا دامنه (اختیاری)",
    "Command": "دستور",
    "Sends echo requests to a host and shows the round-trip time. Set count to ∞ for continuous ping.": "درخواست echo به یک میزبان می‌فرستد و زمان رفت‌وبرگشت را نشان می‌دهد. برای پینگ پیوسته تعداد را ∞ بگذارید.",
    "Shows every router between you and the destination.": "همهٔ روترهای بین شما و مقصد را نشان می‌دهد.",
    "Resolves a name using the system resolver or a DNS server of your choice.": "یک نام را با DNS سیستم یا سرور دلخواه شما به IP تبدیل می‌کند.",
    "Checks whether TCP ports are reachable. Use commas and ranges, e.g. 22,80,443,8000-8010.": "بررسی می‌کند پورت‌های TCP در دسترس هستند یا نه. با ویرگول و بازه مثل 22,80,443,8000-8010.",
    "Looks up country, city and provider for any IP address or domain. Leave empty for your own IP.": "کشور، شهر و ارائه‌دهندهٔ هر IP یا دامنه را پیدا می‌کند. برای IP خودتان خالی بگذارید.",
    "Runs a built-in diagnostic command of your operating system and shows its output.": "یکی از دستورهای عیب‌یابی داخلی سیستم‌عامل شما را اجرا و خروجی آن را نشان می‌دهد.",
    "Invalid host name or IP address.": "نام میزبان یا آدرس IP نامعتبر است.",
    "Enter between 1 and 1024 valid ports (e.g. 80,443,8000-8010).": "بین ۱ تا ۱۰۲۴ پورت معتبر وارد کنید (مثلاً 80,443,8000-8010).",
    "Scanning {host} …": "در حال بررسی {host} …", "open": "باز", "closed / filtered": "بسته / فیلتر شده",
    "Done — {n} open of {total} checked.": "پایان — {n} پورت باز از {total} پورت بررسی‌شده.",
    "Resolving {host} …": "در حال تبدیل {host} …", "Country": "کشور", "Region": "منطقه", "City": "شهر", "Time zone": "منطقهٔ زمانی", "Source": "منبع",
    # dns benchmark / connections / repair
    "Measures how fast popular DNS servers (and your current ones) answer. Lower is better. Results reflect cached answers, which is what you feel day to day.":
        "سرعت پاسخ‌گویی DNS های معروف (و DNS فعلی شما) را می‌سنجد. عدد کمتر بهتر است. نتیجه بر پایهٔ پاسخ‌های کش‌شده است که در استفادهٔ روزمره حس می‌کنید.",
    "Run benchmark": "اجرای بنچمارک", "Apply fastest to adapter": "اعمال سریع‌ترین روی آداپتور", "Server": "سرور", "Address": "آدرس", "Median": "میانه", "Replies": "پاسخ‌ها",
    "Current ({n})": "فعلی ({n})", "Fastest: {n} ({ip}) — {ms:.0f} ms": "سریع‌ترین: {n} ({ip}) — {ms:.0f} میلی‌ثانیه", "No DNS server answered.": "هیچ سرور DNS پاسخ نداد.",
    "Active TCP connections and the programs that own them. Right-click a row to look up the remote IP.": "اتصالات فعال TCP و برنامه‌های صاحب آن‌ها. برای جستجوی IP مقصد روی یک ردیف راست‌کلیک کنید.",
    "Filter by program, port or address …": "فیلتر بر اساس برنامه، پورت یا آدرس …", "Program": "برنامه", "Local address": "آدرس محلی", "Remote address": "آدرس مقصد", "State": "وضعیت",
    "Established": "برقرار", "Listening": "در حال گوش دادن", "All": "همه", "{n} connections": "{n} اتصال", "Copy remote address": "کپی آدرس مقصد", "Look up remote IP": "جستجوی IP مقصد",
    "Fix common network problems. Reset actions need a restart to take full effect.": "رفع مشکلات رایج شبکه. اقدام‌های بازنشانی برای اثر کامل به ری‌استارت نیاز دارند.",
    "Flush DNS cache": "پاک کردن کش DNS", "Renew all IP addresses": "تمدید همهٔ IP ها", "Re-register DNS": "ثبت مجدد DNS", "Clear ARP cache": "پاک کردن کش ARP",
    "Reset Winsock": "بازنشانی Winsock", "Reset TCP/IP stack": "بازنشانی پشتهٔ TCP/IP",
    "Clears the local DNS resolver cache.": "کش DNS محلی را پاک می‌کند.", "Requests fresh DHCP leases on every adapter.": "برای همهٔ آداپتورها IP تازه از DHCP می‌گیرد.",
    "Refreshes DNS registrations and DHCP leases.": "ثبت‌های DNS و اجارهٔ DHCP را تازه می‌کند.", "Removes stale neighbour (ARP) entries.": "ورودی‌های قدیمی ARP را حذف می‌کند.",
    "Resets the Windows sockets catalog (restart required).": "کاتالوگ سوکت‌های ویندوز را بازنشانی می‌کند (نیاز به ری‌استارت).",
    "Rewrites TCP/IP settings to defaults (restart required).": "تنظیمات TCP/IP را به پیش‌فرض برمی‌گرداند (نیاز به ری‌استارت).",
    "“{t}” changes core network settings and needs a restart. Continue?": "«{t}» تنظیمات اصلی شبکه را تغییر می‌دهد و به ری‌استارت نیاز دارد. ادامه می‌دهید؟",
    "Finished.": "پایان.",
})


FA.update({
    "(+{k} hidden by filters)": "(+{k} مخفی با فیلتر)",
    "Standard user": "کاربر عادی (رمز در صورت نیاز)",
    "Install polkit (pkexec) or run the app as root.": "polkit (pkexec) را نصب کنید یا برنامه را با root اجرا کنید.",
    "Start at system startup": "اجرا هنگام روشن شدن سیستم",
    "Command not found: {c}. Install it with your package manager.": "دستور {c} پیدا نشد. آن را با مدیر بسته‌های سیستم نصب کنید.",
    "(nslookup is not installed — using the system resolver)": "(nslookup نصب نیست — از DNS خود سیستم استفاده می‌شود)",
    "Restart DNS resolver": "راه‌اندازی مجدد DNS", "Restarts systemd-resolved.": "سرویس systemd-resolved را دوباره اجرا می‌کند.",
    "Restart NetworkManager": "راه‌اندازی مجدد NetworkManager",
    "Restarts the network service; connections drop briefly.": "سرویس شبکه را دوباره اجرا می‌کند؛ اتصال‌ها لحظه‌ای قطع می‌شوند.",
    "Toggle networking off and on": "خاموش و روشن کردن شبکه", "Turns all managed networking off and back on.": "کل شبکه را خاموش و دوباره روشن می‌کند.",
    "Restart Wi-Fi": "راه‌اندازی مجدد Wi-Fi", "Turns the Wi-Fi radio off and on again.": "Wi-Fi را خاموش و دوباره روشن می‌کند.",
})


# ----------------------------------------------------------------------------
# Persian strings for the Operation Log page and the About / Guide page
# ----------------------------------------------------------------------------
FA.update({
    # internet usage totals
    "Internet used since the app started": "مصرف اینترنت از زمان اجرای برنامه",
    "Total usage (saved)": "مصرف کل (ذخیره‌شده)",
    "Total usage since {d}": "مصرف کل از {d}",
    "Total: {t}": "جمع: {t}",
    "Include virtual / VPN adapters": "احتساب آداپتورهای مجازی / VPN",
    "VPN traffic is already counted on the physical adapter that carries it, so this is off by default to avoid counting it twice.":
        "ترافیک VPN قبلاً روی آداپتور فیزیکی که آن را حمل می‌کند شمرده می‌شود؛ برای جلوگیری از شمارش دوباره، این گزینه به‌طور پیش‌فرض خاموش است.",
    "Reset saved total": "صفر کردن مصرف کل",
    "Reset the saved total usage to zero? The usage since the app started is not affected.":
        "مصرف کل ذخیره‌شده صفر شود؟ مصرف از زمان اجرای برنامه تغییری نمی‌کند.",
    "Saved total usage was reset.": "مصرف کل ذخیره‌شده صفر شد.",
    "Usage totals now {s} virtual / VPN adapters.": "مصرف کل اکنون آداپتورهای مجازی / VPN را {s}.",
    "include": "شامل می‌شود", "exclude": "شامل نمی‌شود",
    "Traffic counters of “{n}” restarted (adapter was reset or re-enabled) — usage totals are kept.":
        "شمارندهٔ ترافیک «{n}» از نو شروع شد (آداپتور ریست یا دوباره فعال شد) — مصرف کل حفظ شد.",
    "Usage this session: ↓ {d} ↑ {u}": "مصرف در این اجرا: ↓ {d} ↑ {u}",
    # operation log
    "Operation Log": "لاگ عملیات",
    "A timeline of everything NIC Switcher did and what happened.": "خط زمانی همهٔ کارهایی که NIC Switcher انجام داده و نتیجهٔ آن‌ها.",
    "Info": "اطلاعات", "Success": "موفق", "Warnings": "هشدارها", "Errors": "خطاها",
    "Save as …": "ذخیره به‌عنوان …", "Open log folder": "باز کردن پوشهٔ لاگ",
    "Save log to file": "ذخیرهٔ لاگ در فایل",
    "Off — entries are kept for this session only. Turn on to keep a permanent timestamped log file.":
        "خاموش — رویدادها فقط تا پایان این اجرا نگه داشته می‌شوند. برای داشتن فایل لاگ دائمی (همراه با زمان) آن را روشن کنید.",
    "Save operation log to a file": "ذخیرهٔ لاگ عملیات در فایل",
    "Writes every log entry with a timestamp to a text file (nicswitcher.log) so you keep a permanent record.":
        "هر رویداد را همراه با زمان در یک فایل متنی (nicswitcher.log) می‌نویسد تا سابقهٔ دائمی داشته باشید.",
    "{n} entries": "{n} رویداد", "{n} of {t} entries": "{n} از {t} رویداد",
    "Log copied to clipboard.": "لاگ کپی شد.", "Log saved to {p}": "لاگ در {p} ذخیره شد", "Log cleared.": "لاگ پاک شد.",
    "Could not write the log file: {e}": "نوشتن فایل لاگ ممکن نشد: {e}",
    "File logging enabled → {p}": "ذخیرهٔ لاگ در فایل فعال شد → {p}",
    "File logging disabled.": "ذخیرهٔ لاگ در فایل غیرفعال شد.",
    "On": "روشن", "Off": "خاموش", "shown": "نمایش داده می‌شوند", "hidden": "مخفی هستند",
    # log messages
    "{a} {v} started on {p}.": "{a} نسخهٔ {v} روی {p} اجرا شد.",
    "Running with administrator rights.": "با دسترسی Administrator اجرا شد.",
    "Running without administrator rights — adapters can be viewed but not changed.":
        "بدون دسترسی Administrator اجرا شد — آداپتورها فقط قابل مشاهده‌اند و تغییر نمی‌کنند.",
    "Adapters detected: {n} ({up} connected).": "آداپتورهای شناسایی‌شده: {n} ({up} متصل).",
    "{a} is closing.": "{a} در حال بسته شدن است.",
    "Theme changed to {t}.": "تم به «{t}» تغییر کرد.", "Accent color changed to {c}.": "رنگ اصلی به {c} تغییر کرد.",
    "Language changed to {l}.": "زبان به «{l}» تغییر کرد.",
    "Setting changed: {k} → {v}": "تنظیم تغییر کرد: {k} = {v}",
    "Virtual / VPN adapters are now {s}.": "آداپتورهای مجازی / VPN اکنون {s}.",
    "Hidden adapters are now {s}.": "آداپتورهای مخفی‌شده اکنون {s}.",
    "Enable: {n}": "فعال‌سازی: {n}", "Disable: {n}": "غیرفعال‌سازی: {n}",
    "Cancelled by user.": "توسط کاربر لغو شد.",
    "Public IP: {ip}": "IP عمومی: {ip}",
    "Internet test via “{n}”: {e}": "تست اینترنت از «{n}»: {e}",
    "Internet test via “{n}”: {ms:.0f} ms, public IP {ip}": "تست اینترنت از «{n}»: {ms:.0f} میلی‌ثانیه، IP عمومی {ip}",
    "Speed test started ({a}).": "تست سرعت شروع شد ({a}).",
    "Speed test finished: ping {p} ms · download {d} Mbps · upload {u} Mbps":
        "تست سرعت پایان یافت: پینگ {p} میلی‌ثانیه · دانلود {d} مگابیت‌بر‌ثانیه · آپلود {u} مگابیت‌بر‌ثانیه",
    "Speed test failed: {e}": "تست سرعت ناموفق بود: {e}", "Speed test stopped.": "تست سرعت متوقف شد.",
    "Toolbox · {t}: started": "جعبه‌ابزار · {t}: شروع شد",
    "Toolbox · {t}: finished.": "جعبه‌ابزار · {t}: پایان یافت.",
    "Toolbox · {t}: stopped by user.": "جعبه‌ابزار · {t}: توسط کاربر متوقف شد.",
    "Toolbox · {t}: {e}": "جعبه‌ابزار · {t}: {e}",
    "Repair · {t}: started": "تعمیر · {t}: شروع شد",
    "Repair · {t}: finished.": "تعمیر · {t}: پایان یافت.",
    "Repair · {t}: {e}": "تعمیر · {t}: {e}",
    # about / guide
    "Guide, support and information about NIC Switcher.": "راهنما، پشتیبانی و اطلاعات دربارهٔ NIC Switcher.",
    "Telegram support": "پشتیبانی در تلگرام", "Email": "ایمیل",
    "What is NIC Switcher?": "NIC Switcher چیست؟",
    "<b>NIC Switcher</b> is a free, open-source network adapter manager and toolbox for Windows, Linux and macOS. "
    "With one click you can enable, disable or switch between your network adapters (Ethernet, Wi-Fi, hotspot, virtual / VPN adapters), "
    "see which one really carries your internet traffic, and repair common connection problems — without digging through system menus.":
        "<b>NIC Switcher</b> یک مدیر آداپتور شبکه و جعبه‌ابزار اینترنت رایگان و متن‌باز برای ویندوز، لینوکس و macOS است. "
        "با یک کلیک می‌توانید آداپتورهای شبکه (اترنت، Wi-Fi، هات‌اسپات، آداپتورهای مجازی / VPN) را فعال، غیرفعال یا جابه‌جا کنید، "
        "ببینید ترافیک اینترنت شما واقعاً از کدام مسیر می‌گذرد و مشکلات رایج اتصال را بدون گشتن در منوهای سیستم رفع کنید.",
    "It is made for desktop computers that have more than one way to reach the internet. Everything runs on your computer; "
    "the only network requests are the public-IP lookup, the speed test and the update check, and you control all of them.":
        "برای کامپیوترهای رومیزی ساخته شده که بیش از یک راه برای اتصال به اینترنت دارند. همه‌چیز روی کامپیوتر خودتان اجرا می‌شود؛ "
        "تنها درخواست‌های شبکه‌ای برنامه، بررسی IP عمومی، تست سرعت و بررسی به‌روزرسانی است و کنترل همهٔ آن‌ها دست شماست.",
    "Quick start": "شروع سریع",
    "<b>1.</b>  Open the <b>Adapters</b> page. Every network adapter is shown as a card with its status, IP address, gateway, MAC address and live speed.":
        "<b>۱.</b>  صفحهٔ <b>آداپتورها</b> را باز کنید. هر آداپتور شبکه به‌صورت یک کارت با وضعیت، آدرس IP، گیت‌وی، آدرس MAC و سرعت لحظه‌ای نمایش داده می‌شود.",
    "<b>2.</b>  Use the switch on a card to enable or disable that adapter. Press <b>⚡ Only this one (disable others)</b> to keep that adapter and disable all the others — the fastest way to change your internet source.":
        "<b>۲.</b>  با کلید روی کارت، آداپتور را فعال یا غیرفعال کنید. دکمهٔ <b>⚡ فقط این را فعال کن (بقیه غیرفعال)</b> فقط همان آداپتور را نگه می‌دارد و بقیه را غیرفعال می‌کند — سریع‌ترین راه برای عوض کردن منبع اینترنت.",
    "<b>3.</b>  Wait for the progress window. The app waits until the adapter is ready, then refreshes your public IP automatically.":
        "<b>۳.</b>  تا پایان پنجرهٔ پیشرفت صبر کنید. برنامه منتظر آماده شدن آداپتور می‌ماند و سپس IP عمومی شما را خودکار به‌روز می‌کند.",
    "<b>4.</b>  Press <b>🌍 Test internet</b> on a card (or <b>Test all</b>) to measure the latency and the public IP that adapter really uses.":
        "<b>۴.</b>  روی <b>🌍 تست اینترنت</b> در کارت (یا <b>تست همه</b>) بزنید تا تأخیر و IP عمومی‌ای که آن آداپتور واقعاً استفاده می‌کند سنجیده شود.",
    "<b>5.</b>  Open the <b>Operation Log</b> page at any time to see what was done and whether it worked.":
        "<b>۵.</b>  هر زمان صفحهٔ <b>لاگ عملیات</b> را باز کنید تا ببینید چه کاری انجام شده و موفق بوده یا نه.",
    "<b>Note:</b> enabling or disabling adapters needs Administrator rights. On Windows the app asks for them when it starts.":
        "<b>نکته:</b> فعال یا غیرفعال کردن آداپتورها به دسترسی Administrator نیاز دارد. در ویندوز برنامه هنگام شروع آن را درخواست می‌کند.",
    "Guide to the pages": "راهنمای صفحه‌ها",
    "<b>🔌 Adapters</b> — enable / disable / switch adapters, profiles, DNS, static IP or DHCP, internet priority, display names, hide adapters you never use.":
        "<b>🔌 آداپتورها</b> — فعال / غیرفعال / جابه‌جایی آداپتورها، پروفایل‌ها، DNS، IP ثابت یا DHCP، اولویت اینترنت، نام نمایشی و مخفی کردن آداپتورهایی که به آن‌ها نیاز ندارید.",
    "<b>📈 Monitor</b> — live download and upload graphs, plus your <b>total internet usage</b> (download + upload) since the app started and a saved all-time total. The totals never reset when an adapter is disabled, re-enabled or restarted.":
        "<b>📈 مانیتور</b> — نمودار زندهٔ دانلود و آپلود، به‌علاوهٔ <b>مصرف کل اینترنت</b> (دانلود + آپلود) از زمان اجرای برنامه و یک مجموع کل ذخیره‌شده. با غیرفعال، دوباره فعال یا ریست شدن آداپتور، این مجموع‌ها هرگز صفر نمی‌شوند.",
    "<b>Does the usage total reset when I disable or enable an adapter?</b><br>No. NIC Switcher notices when an adapter's counters restart and keeps adding to the same total, so the number only grows. It keeps counting while the window is hidden in the tray; the saved all-time total survives restarts (reset it with <b>Reset saved total</b> on the Monitor page).":
        "<b>آیا با غیرفعال یا فعال کردن آداپتور، مصرف کل صفر می‌شود؟</b><br>خیر. NIC Switcher متوجه شروع دوبارهٔ شمارنده‌های آداپتور می‌شود و به همان مجموع اضافه می‌کند، پس عدد فقط بالا می‌رود. حتی وقتی پنجره در سیستم‌تری مخفی است هم می‌شمارد؛ مجموع کل ذخیره‌شده با بستن و باز کردن برنامه حفظ می‌شود (با <b>صفر کردن مصرف کل</b> در صفحهٔ مانیتور صفرش کنید).",
    "<b>🚀 Speed test</b> — ping, jitter, download and upload; you can run it through one specific adapter to compare connections.":
        "<b>🚀 تست سرعت</b> — پینگ، جیتر، دانلود و آپلود؛ می‌توانید تست را از مسیر یک آداپتور مشخص اجرا کنید تا اتصال‌ها را مقایسه کنید.",
    "<b>🧰 Toolbox</b> — ping, traceroute, DNS lookup, port check, IP lookup, DNS benchmark, active connections, system info and one-click network repair.":
        "<b>🧰 جعبه‌ابزار</b> — پینگ، ردیابی مسیر، جستجوی DNS، بررسی پورت، جستجوی IP، بنچمارک DNS، اتصالات فعال، اطلاعات سیستم و تعمیر شبکه با یک کلیک.",
    "<b>📝 Operation Log</b> — a timeline of everything the app did. Filter by level, copy or save it, and optionally keep a permanent log file.":
        "<b>📝 لاگ عملیات</b> — خط زمانی همهٔ کارهای برنامه. بر اساس سطح فیلتر کنید، کپی یا ذخیره کنید و در صورت تمایل فایل لاگ دائمی نگه دارید.",
    "<b>⚙️ Settings</b> — language (English / فارسی), light / dark theme, accent color, refresh interval, tray, start with the system, export / import settings.":
        "<b>⚙️ تنظیمات</b> — زبان (English / فارسی)، تم روشن / تاریک، رنگ اصلی، فاصلهٔ به‌روزرسانی، سیستم‌تری، اجرا همراه سیستم، خروجی / ورودی تنظیمات.",
    "Tips": "نکته‌ها",
    "• <b>Virtual / VPN adapters</b> are shown by default. Untick the box on the Adapters page if you only want to see physical adapters.":
        "• آداپتورهای <b>مجازی / VPN</b> به‌طور پیش‌فرض نمایش داده می‌شوند. اگر فقط آداپتورهای فیزیکی را می‌خواهید، تیک آن را در صفحهٔ آداپتورها بردارید.",
    "• Save your favourite setups as <b>Profiles</b> (for example “Home internet” or “Phone hotspot”) and apply them from the app or from the tray icon.":
        "• تنظیم‌های مورد علاقه‌تان را به‌صورت <b>پروفایل</b> ذخیره کنید (مثلاً «اینترنت خانه» یا «هات‌اسپات گوشی») و از داخل برنامه یا از آیکون سیستم‌تری اعمال کنید.",
    "• Right-click the tray icon to switch adapters, run a speed test or quit without opening the window.":
        "• روی آیکون سیستم‌تری راست‌کلیک کنید تا بدون باز کردن پنجره آداپتورها را عوض کنید، تست سرعت بگیرید یا خارج شوید.",
    "• Shortcuts: <b>F5</b> refresh, <b>Ctrl+F</b> search adapters, <b>Ctrl+1 … Ctrl+7</b> jump between pages.":
        "• میان‌برها: <b>F5</b> تازه‌سازی، <b>Ctrl+F</b> جستجوی آداپتور، <b>Ctrl+1 … Ctrl+7</b> رفتن بین صفحه‌ها.",
    "Troubleshooting & FAQ": "عیب‌یابی و پرسش‌های متداول",
    "<b>The switches are disabled and a red banner is shown.</b><br>The app has no Administrator rights. Close it and start it again as Administrator (on Linux / macOS you may be asked for your password).":
        "<b>کلیدها غیرفعال‌اند و یک نوار قرمز نمایش داده می‌شود.</b><br>برنامه دسترسی Administrator ندارد. آن را ببندید و دوباره با دسترسی مدیر اجرا کنید (در لینوکس / macOS ممکن است رمز عبور بخواهد).",
    "<b>An adapter was enabled but has no internet.</b><br>Give it a few seconds to receive an IP address, then press <b>Test internet</b>. If it still fails, try <b>Toolbox → Repair → Flush DNS cache</b> and read the Operation Log for errors.":
        "<b>آداپتور فعال شد ولی اینترنت ندارد.</b><br>چند ثانیه صبر کنید تا IP بگیرد، سپس <b>تست اینترنت</b> را بزنید. اگر باز هم کار نکرد، <b>جعبه‌ابزار ← تعمیر شبکه ← پاک کردن کش DNS</b> را امتحان کنید و خطاها را در لاگ عملیات ببینید.",
    "<b>Windows SmartScreen or my antivirus warns about the .exe.</b><br>The program is new and not code-signed, so Windows may show a warning. Choose <b>More info → Run anyway</b>. The full source code is on GitHub so you can check or build it yourself.":
        "<b>ویندوز (SmartScreen) یا آنتی‌ویروس دربارهٔ فایل .exe هشدار می‌دهد.</b><br>برنامه جدید است و امضای دیجیتال ندارد، برای همین ویندوز ممکن است هشدار بدهد. گزینهٔ <b>More info ← Run anyway</b> را بزنید. کد کامل برنامه در گیت‌هاب است و می‌توانید خودتان آن را بررسی یا بیلد کنید.",
    "<b>My public IP shows another country.</b><br>That is expected when a VPN or proxy is active — the IP shown is the one websites see.":
        "<b>IP عمومی من کشور دیگری را نشان می‌دهد.</b><br>وقتی VPN یا پروکسی فعال باشد طبیعی است — IP نمایش‌داده‌شده همان است که وب‌سایت‌ها می‌بینند.",
    "<b>Where are my settings stored?</b><br>In the operating system's settings store for the current user. Use <b>Settings → Data → Export settings</b> to back them up.":
        "<b>تنظیمات من کجا ذخیره می‌شود؟</b><br>در محل ذخیرهٔ تنظیمات سیستم‌عامل برای کاربر فعلی. برای پشتیبان‌گیری از <b>تنظیمات ← داده‌ها ← خروجی گرفتن از تنظیمات</b> را بزنید.",
    "Support & contact": "پشتیبانی و ارتباط",
    "Found a bug, have an idea or need help? Send me a direct message on Telegram: {tg}. You can also email {mail} or open an issue on GitHub.":
        "باگ پیدا کردید، ایده‌ای دارید یا کمک می‌خواهید؟ در تلگرام برایم پیام مستقیم بفرستید: {tg}. می‌توانید به {mail} ایمیل بزنید یا در گیت‌هاب یک Issue باز کنید.",
    "When you report a problem, please press <b>Copy diagnostics</b> above and, from the <b>Operation Log</b> page, copy the log lines around the problem.":
        "هنگام گزارش مشکل، لطفاً دکمهٔ <b>کپی اطلاعات عیب‌یابی</b> را در بالا بزنید و از صفحهٔ <b>لاگ عملیات</b> خط‌های لاگ مربوط به مشکل را کپی کنید.",
})


if __name__ == "__main__":
    sys.exit(main())
