**New: Anycubic Kobra printers.** Ventris now explains G-code for the whole Kobra line —
Kobra, Kobra Plus, Max and Neo; Kobra 2, 2 Neo, 2 Pro, 2 Plus and 2 Max; Kobra 3, 3 V2
and 3 Max; Kobra S1 and S1 Max; and Kobra X — sliced with Anycubic Slicer Next,
OrcaSlicer or PrusaSlicer. The profile is picked automatically.

- **G9111**, the one-line start routine on the Kobra 3, S1 and X, is explained step by
  step from Anycubic's published Kobra 3 firmware source: heat, home, wipe the nozzle,
  prime. The machine panel picks up the temperatures it sets.
- Klipper commands written for the newer Kobras (`SET_VELOCITY_LIMIT`, cancellable
  objects with `EXCLUDE_OBJECT_*`), Anycubic's progress lines with quiet/sport mode
  times, ACE Pro filament slots and filament-swap blocks are all explained.
- Anycubic doesn't publish a G-code reference, so codes known only from its slicer
  profiles (M991, M73 layer numbers) are marked as community knowledge.

Also: printer detection now reads the end of the file as well as the start, so files
from OrcaSlicer and PrusaSlicer, which name the printer at the end, get the right
profile. Stray text lines that aren't commands are flagged instead of shown as blank.

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
