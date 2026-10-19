# Contributing to NIC Switcher

Thank you for your interest in contributing! Here is how you can help.

## 🐛 Reporting Bugs

Open an issue on the [Issues tab](../../issues) and include:

- Your operating system and version (e.g., Windows 11 23H2, Ubuntu 24.04, macOS 14)
- Whether you run the `.exe` / binary or the Python script (and your Python version)
- Steps to reproduce the bug
- What you expected vs. what actually happened
- The lines from the app's **📝 Operation Log** page around the problem (use **Copy**)
- The output of **ℹ️ About → Copy diagnostics**
- The type of network adapters involved (Ethernet, Wi-Fi, USB, VPN/virtual) — no need to share IP or MAC addresses

## 💡 Suggesting Features

Open an issue describing:
- What the new feature does
- Why it would be useful to users
- A rough idea of how it would work in the UI

## 🔧 Pull Requests

1. Click **Fork** at the top of the repository page
2. Make your changes in your fork
3. Test on your platform: enable / disable an adapter, **⚡ Only this one**, apply a profile, run a speed test, and check the Operation Log shows each step
   - After disabling and re-enabling an adapter, the Monitor page's usage totals must keep growing and never drop
4. Open a **Pull Request** back to this repository
5. Describe your changes clearly

### Code Style
- Keep the single-file structure for small changes
- Use type hints and docstrings consistent with the existing code
- Every user-visible string goes through `tr("English text")`, and **every new string needs a Persian entry** in the `FA` table at the bottom of the file
- Record what the app does with `OPLOG.info()`, `OPLOG.ok()`, `OPLOG.warn()` or `OPLOG.error()` so it appears in the Operation Log
- Never add anything that sends data to the internet without a clear setting to control it
- Test both the light and the dark theme, and both English and Persian (RTL) layouts

## 🌍 Translations

The app already supports English and Persian (Farsi). If you can translate the README into Arabic, Russian, Chinese, Turkish or any other language, please contribute a file named `README.fa.md`, `README.ar.md`, etc.

## 📬 Contact

- Telegram: [@Sparky2273](https://t.me/Sparky2273)
- Email: mhashemi6699@gmail.com
