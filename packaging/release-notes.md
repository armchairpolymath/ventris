**New: QIDI printers.** Ventris now explains G-code for QIDI's lineup — Q1 Pro, Q2 and Q2C;
X-Max 3, X-Plus 3 and X-Smart 3; X-Plus 4 and X-Max 4; X-Plus 5 and X-Smart 5; and the
older X-Plus, X-Max and X-CF Pro — sliced with QIDIStudio, OrcaSlicer or QIDISlicer. The
profile is picked automatically.

- QIDI's own commands (`PRINT_START`, `MOVE_TO_TRASH`, `M1002`, `M109.1`,
  `SET_PRINT_SUB_STATUS` and more) are explained from the printer configuration QIDI
  publishes for the Q1 Pro, X-Plus 4, X-Max 4 and Q2. The machine panel picks up the
  temperatures from `PRINT_START` and the layer count the slicer sends.
- QIDI fans are numbered from 0 (part fan), with the auxiliary fan on P2, the chamber fan
  on P3 and the X-Max 4/Q2 "Polar cooler" on P4.
- QIDI Box (multi-color) commands such as `CUT_FILAMENT` and `TOOL_CHANGE_START` run from
  code QIDI hasn't published, so they are explained from where QIDI uses them and marked
  as community knowledge.

Also: QIDI files that use `M1002` are no longer mistaken for Bambu files, and `G92_`
is read as its own command instead of as `G92`.

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
