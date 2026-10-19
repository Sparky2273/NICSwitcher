<div align="center">

<h1>🔌 NIC Switcher</h1>

<p><strong>A free, open-source network adapter manager and internet toolbox for desktop computers — enable, disable or switch between Ethernet, Wi-Fi, hotspot and VPN adapters in one click, test every connection separately, track your total internet usage without it ever resetting, and keep a log of everything that happened.</strong></p>

<p>
  <img src="https://img.shields.io/badge/version-1.0.0-blue?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10%2B-yellow?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/GUI-PyQt6-purple?style=flat-square" alt="PyQt6">
  <img src="https://img.shields.io/badge/languages-English%20%7C%20%D9%81%D8%A7%D8%B1%D8%B3%DB%8C-orange?style=flat-square" alt="Languages">
  <img src="https://img.shields.io/badge/telemetry-none-brightgreen?style=flat-square" alt="No telemetry">
</p>

<p>
  <a href="#-quick-start-windows-exe">⚡ Quick Start (EXE)</a> ·
  <a href="#-features">Features</a> ·
  <a href="#-run-from-source">Run from Source</a> ·
  <a href="#-how-to-use">How to Use</a> ·
  <a href="#-operation-log">Operation Log</a> ·
  <a href="#-troubleshooting">Troubleshooting</a> ·
  <a href="#-contact--support">Support</a>
</p>

</div>

---

## 📖 Table of Contents

- [What Is This?](#-what-is-this)
- [Features](#-features)
- [Quick Start — Windows EXE](#-quick-start-windows-exe)
- [Run from Source](#-run-from-source)
- [How to Use](#-how-to-use)
  - [Switching Adapters](#switching-adapters)
  - [Testing Your Internet](#testing-your-internet)
  - [Total Internet Usage](#total-internet-usage)
  - [DNS, IP and Priority](#dns-ip-and-priority)
  - [Profiles](#profiles)
  - [Speed Test and Toolbox](#speed-test-and-toolbox)
- [Guide to the Pages](#-guide-to-the-pages)
- [Operation Log](#-operation-log)
- [Settings](#-settings)
- [Platform Notes](#-platform-notes)
- [Build the EXE Yourself](#-build-the-exe-yourself)
- [Troubleshooting](#-troubleshooting)
- [FAQ](#-faq)
- [Privacy and Security Notes](#-privacy-and-security-notes)
- [Contact & Support](#-contact--support)
- [License](#-license)

---

## 🔍 What Is This?

**NIC Switcher** is a desktop application that manages the **network adapters (NICs)** of your computer. Many desktop PCs can reach the internet in more than one way — a cable, a Wi-Fi card, a USB tethered phone, a VPN adapter — and switching between them normally means digging through Windows network settings again and again. NIC Switcher puts all of them on one screen:

- see every adapter with its status, IP, gateway, MAC address and **live speed**
- **enable, disable or switch** with one click (or keep *only* one adapter active)
- find out which adapter really gives you internet, and what **public IP** it has
- fix common network problems with a built-in toolbox
- see what the app did in a clear **Operation Log**

**Who is this for?**
- Desktop users with Ethernet + Wi-Fi + phone hotspot who want to pick the connection that works best
- People who use a VPN or proxy adapter and want to turn it on / off quickly
- Anyone who needs a quick network toolbox (ping, traceroute, DNS, ports, speed test) in one place
- Users in countries with unstable internet who constantly compare connections

The interface is available in **English** and **فارسی (Persian, right-to-left)** and switches instantly.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🔌 **One-click adapter control** | Enable, disable or switch adapters. **⚡ Only this one** keeps one adapter and disables the rest |
| 📊 **Live traffic** | Per-adapter download / upload speed graphs and total usage |
| 📊 **Total internet usage** | Download + upload since the app started, plus a saved all-time total — **never resets** when adapters are disabled, re-enabled or restarted |
| 🌍 **Per-adapter internet test** | Measures latency and the public IP **through that adapter only** |
| 🧭 **Public IP & location** | Shows your public IP, country, city and provider (with several fallback services) |
| 🚀 **Speed test** | Ping, jitter, download, upload — can be bound to one specific adapter |
| 🧰 **Network toolbox** | Ping, traceroute, DNS lookup, port check, IP lookup, DNS benchmark, active connections, system info, one-click repair |
| 🌐 **DNS / IP / priority** | Change DNS (Cloudflare, Google, Quad9, OpenDNS, custom), static IP or DHCP, renew IP, set the preferred adapter |
| 📁 **Profiles** | Save a combination of enabled adapters and apply it later (from the app or the tray) |
| 📝 **Operation Log** | Timestamped history of everything the app did, with filter, copy, save and optional log file |
| 🛡️ **Virtual / VPN adapters** | Shown by default — hide them with one checkbox if you prefer |
| 🏷️ **Display names & hiding** | Give adapters friendly names, hide the ones you never use |
| 🔔 **System tray** | Switch adapters and run tools from the tray icon; start minimized; start with the system |
| 🎨 **Light / Dark theme** | Light theme by default, six accent colors, optional animations |
| 🌐 **English + Persian (RTL)** | Full translation including the built-in guide |
| ℹ️ **Built-in guide** | The About page has a quick-start guide, FAQ and direct support contact |
| 💾 **Export / import settings** | Back up names, hidden adapters, profiles and preferences |
| 📦 **Single file** | The entire app is one Python file — easy to audit and share |

---

## ⚡ Quick Start (Windows EXE)

No Python needed.

1. Go to the [**Releases**](../../releases) page of this repository.
2. Download `NICSwitcher.exe`.
3. Double-click it and accept the **Administrator (UAC)** prompt — Windows requires admin rights to enable or disable adapters.
4. Pick an adapter card and use its switch, or press **⚡ Only this one (disable others)**.

> The app is fully portable — copy it to any folder or USB drive and run it from there.
>
> **Windows SmartScreen / antivirus warning?** The program is new and not code-signed. Click **More info → Run anyway**. All of the source code is in this repository so you can read it or build the EXE yourself.

---

## 🐍 Run from Source

### Requirements

- Python 3.10 or newer — [https://www.python.org/downloads/](https://www.python.org/downloads/)
  - Windows: tick ✅ **"Add Python to PATH"** during installation
- Dependency: `PyQt6` (everything else is part of Python)

### Step 1 — Get the Script

Download `NICSwitcher_V1.py` from this repository, or clone:

```bash
git clone https://github.com/Sparky2273/NICSwitcher.git
cd NICSwitcher
```

### Step 2 — Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Run

```bash
python NICSwitcher_V1.py
```

On Windows the app restarts itself with Administrator rights (UAC prompt). On Linux and macOS it asks for your password only when a change needs it.

Command-line flags:

| Flag | What it does |
|---|---|
| `--minimized` | Start hidden in the system tray |
| `--build` | Build a standalone executable with PyInstaller |
| `--version` | Print the version and exit |

---

## 📖 How to Use

### Switching Adapters

1. Open the **🔌 Adapters** page. Each adapter is a card showing its status, IP address, gateway, MAC address, speed and live traffic.
2. Use the **switch** on a card to enable or disable that adapter.
3. Press **⚡ Only this one (disable others)** to keep that adapter and disable all the others. This is the fastest way to change which connection you use.
4. Wait for the progress window. NIC Switcher waits until the adapter is really ready, then refreshes your public IP.

> ⚠️ Enabling or disabling adapters needs **Administrator rights**. Without them the app still works as a viewer and shows a red banner.

> 💡 Tick **Ask for confirmation before "Only this one"** if you want a safety prompt.

### Testing Your Internet

- Press **🌍 Test internet** on a card to measure latency and the **public IP that adapter really uses**.
- Press **Test all** to test every connected adapter at once and compare them.
- The **IP bar** at the top shows your public IP, country, city and provider for the main internet route. Use **Check again** to refresh it.

### Total Internet Usage

Open the **📈 Monitor** page to see how much internet you have used:

- **📊 Internet used since the app started** — total download ↓ and upload ↑ (and their sum) across all your adapters
- **💾 Total usage (saved)** — an all-time total that is kept when you close and reopen the app, with the date it started counting
- A per-adapter table with each adapter's session download / upload

**Why you can trust the number:** network adapters keep their own byte counters, and Windows resets them to zero whenever an adapter is disabled and enabled again (or its driver restarts). NIC Switcher watches for exactly that: when a counter restarts it keeps everything counted so far and continues adding on top. The total can only grow — it never drops to 0 and never shows a wrong or negative value, no matter how often you switch adapters with **⚡ Only this one**.

Good to know:
- Counting continues while the window is hidden in the system tray (keep **Live traffic monitoring** on in Settings).
- Only traffic that happens **after the app has started** is counted; what your PC used before is not included.
- **VPN / virtual adapters are not added by default**, because their traffic is already counted on the physical adapter that carries it. Tick **Include virtual / VPN adapters** if you want them added too.
- The saved total is stored every 30 seconds and when the app closes. Press **🗑 Reset saved total** to start a new count (the "since app started" number is not affected).
- Counter restarts are written to the **📝 Operation Log**, so you can see when it happened.

### DNS, IP and Priority

Open the **More** menu on an adapter card:

- **Change DNS** — Automatic (DHCP), Cloudflare, Google, Quad9, OpenDNS or custom addresses
- **IP configuration** — switch between DHCP and a static IP / prefix / gateway / DNS
- **Renew IP (DHCP)** — request a fresh address
- **Internet priority** — make this adapter the preferred one for internet, or reset to automatic
- **Rename / hide** — friendly display name (stays in the app) or rename in the operating system; hide adapters from the list and from group actions
- **Copy IP / MAC / all details**

### Profiles

1. Set up the adapters the way you like (for example only Wi-Fi enabled).
2. Click **📁 Profiles → Save current state as profile …** and give it a name such as *Home internet* or *Phone hotspot*.
3. Apply it later from **📁 Profiles** or directly from the **tray icon**.

### Speed Test and Toolbox

- **🚀 Speed test** measures ping, jitter, download and upload using Cloudflare's public speed servers (a test transfers roughly 50–150 MB). Choose an adapter in the drop-down to test one connection specifically; results are kept in a history table.
- **🧰 Toolbox** has these tabs: **Ping**, **Traceroute**, **DNS lookup**, **Port check**, **IP lookup**, **DNS benchmark** (with *Apply fastest to adapter*), **Connections**, **System info** and **Repair**.

---

## 🧭 Guide to the Pages

| Page | Shortcut | What it is for |
|---|---|---|
| 🔌 **Adapters** | `Ctrl+1` | Enable / disable / switch adapters, profiles, DNS, IP, priority |
| 📈 **Monitor** | `Ctrl+2` | Live speed graphs and **total internet usage** (session + saved all-time) |
| 🚀 **Speed test** | `Ctrl+3` | Ping, jitter, download, upload — optionally through one adapter |
| 🧰 **Toolbox** | `Ctrl+4` | Network diagnostics and repair tools |
| 📝 **Operation Log** | `Ctrl+5` | Timeline of everything the app did |
| ⚙️ **Settings** | `Ctrl+6` | Language, theme, behavior, data |
| ℹ️ **About** | `Ctrl+7` | Quick-start guide, FAQ, support contact, diagnostics, update check |

Other shortcuts: `F5` refresh · `Ctrl+F` search adapters by name, IP or MAC.

---

## 📝 Operation Log

The **Operation Log** page records what NIC Switcher did and what happened, so you can always check whether a change worked.

What is recorded:
- app start, administrator status, number of adapters found
- every enable / disable / switch / profile action — **which adapters** were turned on or off, and whether it succeeded
- DNS, static IP, DHCP renew and priority changes
- public IP lookups and per-adapter internet tests (latency and IP)
- when an adapter's traffic counters restart (usage totals are kept) and the usage summary when the app closes
- speed test start, result and failures
- toolbox and repair actions
- setting changes (theme, language, virtual adapters, and so on) and update checks
- every **error**, with the message returned by the system

Each line has a timestamp and a colored level: **INFO**, **SUCCESS**, **WARNING** or **ERROR**.

You can:
- **Filter** by level (All / Info / Success / Warnings / Errors)
- **📋 Copy** the visible lines to the clipboard (handy for bug reports)
- **💾 Save as …** a text file
- **🗑 Clear** the log
- Turn on **Save log to file** to also write every entry to `nicswitcher.log` — next to the program (or in the settings folder if that location is read-only). The file is rotated at about 1 MB. File logging is **off by default**.

The newest 2,000 entries are kept in the window for the current session.

---

## ⚙️ Settings

| Setting | Default | Description |
|---|---|---|
| Language | English | English or فارسی — switches instantly |
| Theme | **Light** | Light or dark |
| Accent color | Blue | Six colors |
| Animations | On | Turn off on slow computers |
| Adapter refresh interval | 5 s | 3, 5, 10 or 30 seconds |
| Live traffic monitoring | On | Per-second graphs and usage counting, also while the window is hidden in the tray |
| Include virtual / VPN adapters in usage (Monitor page) | Off | Add VPN / virtual traffic to the totals (off to avoid counting it twice) |
| Check public IP automatically | On | At startup and whenever the internet route changes |
| Tray notifications | On | Balloon when a change completes |
| Close button minimizes to tray | On | Keeps the app running in the tray |
| Save operation log to a file | Off | Writes `nicswitcher.log` |
| Start at system startup | Off | Starts minimized to the tray when you sign in |
| Virtual / VPN adapters (Adapters page) | **Shown** | Untick to see only physical adapters |

**Data:** export / import settings (names, hidden adapters, profiles, preferences), un-hide all adapters, or reset everything.

---

## 🖥️ Platform Notes

| | Windows | Linux | macOS |
|---|---|---|---|
| Adapter control | PowerShell (`Get-NetAdapter`) | `iproute2` + NetworkManager (`nmcli`) | `networksetup` |
| Admin rights | UAC prompt at start | `pkexec` (polkit) or root | Password prompt when needed |
| Start with system | Task Scheduler / Run key | XDG autostart entry | Launch agent |
| Standalone binary | ✅ `NICSwitcher.exe` | build with `--build` | build with `--build` |

Windows 10 / 11 is the primary target and the one the release EXE is built for.

---

## 🔨 Build the EXE Yourself

```bash
pip install -r requirements.txt pyinstaller
python NICSwitcher_V1.py --build
```

This runs PyInstaller with the right options (single file, no console window, UAC admin manifest, the repository `icon.ico`, version information). The result is `dist/NICSwitcher.exe`.

---

## 🔧 Troubleshooting

**"No module named PyQt6"**
→ Run `pip install -r requirements.txt` and try again.

**The switches are disabled and a red banner is shown**
→ The app has no Administrator rights. Close it and start it again as Administrator (on Linux, install `polkit` / `pkexec` or run as root).

**An adapter was enabled but has no internet**
→ Give it a few seconds to get an IP address, then press **Test internet**. If it still fails, try **Toolbox → Repair → Flush DNS cache** (or *Renew all IP addresses*), and read the **Operation Log** for the error.

**Windows SmartScreen or my antivirus warns about the .exe**
→ The program is not code-signed. Choose **More info → Run anyway**, or build the EXE yourself from the source.

**The app says it is already running**
→ Only one copy can run at a time. Look for the icon in the system tray (near the clock) and click it.

**My public IP shows another country**
→ This is expected when a VPN or proxy is active — the IP shown is the one websites see.

**Persian text looks odd**
→ Install a Persian-friendly font such as *Vazirmatn*; the app falls back to Segoe UI / Tahoma otherwise.

**Something else went wrong**
→ Open **📝 Operation Log**, press **Copy**, press **ℹ️ About → Copy diagnostics**, and send both to the support contact below.

---

## ❓ FAQ

**Q: Does the usage total reset when I disable and enable an adapter?**
A: No. When an adapter's counters restart, NIC Switcher keeps the total and continues adding. The number only grows. The since-start total resets only when you close the app; the saved all-time total resets only when you press **Reset saved total**.

**Q: Does it count data used while the app is minimized to the tray?**
A: Yes, as long as **Live traffic monitoring** is on (default). Nothing is counted while the app is not running.

**Q: Does it include what my PC used before I started the app?**
A: No — only traffic after the app has started.

**Q: Does it work with VPN and virtual adapters?**
A: Yes. They are shown by default (untick *Virtual / VPN adapters* on the Adapters page to hide them) and can be enabled, disabled and tested like any other adapter.

**Q: What does "Only this one" do exactly?**
A: It enables the chosen adapter (if needed) and disables every other adapter that is currently listed. Adapters you have hidden are not touched.

**Q: Can I lock myself out of the internet?**
A: Disabling all adapters removes your connection, but you can always re-enable them from the app (**Tools → Enable all adapters**), from the tray menu, or from Windows network settings.

**Q: Where are my settings stored?**
A: In the operating system's per-user settings store (on Windows: the registry under `HKEY_CURRENT_USER\Software\NicSwitcher`). Use **Settings → Data → Export settings** to make a backup file.

**Q: Does the app send any data to the internet?**
A: No telemetry, no accounts, no analytics. See [Privacy and Security Notes](#-privacy-and-security-notes) for the few requests it makes on purpose.

**Q: How do I update?**
A: Press **About → Check for updates**, or download the newest `NICSwitcher.exe` from the Releases page.

**Q: Can I get the log of what the app did yesterday?**
A: Turn on **Save log to file** in Settings (or on the Operation Log page). From then on every entry is also written to `nicswitcher.log`.

---

## 🔒 Privacy and Security Notes

- **No telemetry.** NIC Switcher has no analytics, no tracking and no accounts.
- **Network requests the app makes (all optional / on demand):**
  - public IP and location lookup (ipwho.is, ipapi.co, ipinfo.io, Cloudflare, ipify) — turn off *Check public IP automatically* to make this manual
  - the speed test (Cloudflare speed servers) — only when you press **Start test**
  - the update check (GitHub API) — only when you press **Check for updates**
- **Administrator rights** are used only to enable / disable adapters and to change network settings you ask for. The code that does this is plain PowerShell / shell commands you can read in the source.
- Settings (including the saved usage total — just a few numbers) are stored per user; the optional log file is a plain text file next to the program.
- The log may contain adapter names and public IP addresses — review it before sharing it publicly.

---

## 📬 Contact & Support

Questions, bugs or ideas? **Send me a direct message on Telegram.**

- **Telegram:** [@Sparky2273](https://t.me/Sparky2273)
- **Email:** mhashemi6699@gmail.com
- **Bug Reports & Feature Requests:** [Open a GitHub Issue](../../issues)

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Made with ❤️ by SPARKS**

*One click. Any connection.*

</div>
