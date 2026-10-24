**New: Creality K1 printers.** Ventris now explains G-code for the Creality K1, K1C, K1 Max
and K1 SE, with or without a CFS, sliced with Creality Print (4.x and later) or OrcaSlicer.
The profile is picked automatically.

- `START_PRINT` and `END_PRINT` are explained step by step from the K1 Klipper source and
  configuration Creality publishes: homing with a warm nozzle, wiping the nozzle on the bed,
  precise Z homing with the pressure sensors under the bed, checking the bed map, and the
  priming line.
- The K1's fans are numbered differently: P0 is the part fan, P1 the chamber fan at the
  back, P2 the side fan. The machine panel now follows each printer's own fan numbering.
- `M141` on a K1 doesn't heat — there is no chamber heater — it sets how warm the chamber
  may get before the back fan runs. Ventris says so.
- Creality Print 4.x files (Cura-style `;LAYER:`, `;TYPE:WALL-OUTER`, `;MESH:` comments)
  are explained, and the layer count follows them.
- Filament changes on a K1 with a CFS are marked as community knowledge: Creality hasn't
  published that code.

Also: printer detection now looks past the preview images at the start of a file, which
hid Creality Print 4's header. Files from other Creality printers (Ender-3 V3, K2) open
with the K1 profile as the closest match but aren't fully covered.

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
