**New: laser cutters.** Ventris now opens `.rd` job files for **Thunder Laser Nova** and
other **Ruida**-controlled laser cutters. These machines don't use G-code; Ventris
decodes the scrambled binary job into one readable line per command (moves, cuts,
speed, power, layers, air assist) and explains each one, with a laser-specific machine
panel. `.rd` files open read-only.

Also: Windows line endings are preserved on save, and saving Bambu `.gcode.3mf` files
works on Windows.

### Downloads

| System | File |
|---|---|
| Windows 10/11 (64-bit) | `…-windows-x64-setup.exe` (installer) or `…-windows-x64.zip` (portable) |
| macOS, Apple silicon | `…-macos-arm64.dmg` |
| macOS, Intel | `…-macos-x86_64.dmg` |
| Linux x86-64 | `…-linux-x86_64.AppImage` |
| Python (any OS) | `ventris-…-py3-none-any.whl` — `pip install` it |

These builds aren't code-signed, so Windows and macOS warn on first launch. See
[First launch](https://github.com/armchairpolymath/ventris#first-launch-unknown-developer-warnings)
in the README for the one-time steps.
