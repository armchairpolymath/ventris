# G-code Analyzer

A Fedora (GTK4 / libadwaita) desktop app that explains G-code line by line.
G-code on the left; on the right, a plain-English explanation of the line under
the cursor and a snapshot of the machine's state at that point.

Supported printers (picked automatically from the file; change it in the header bar):

- **Bambu Lab** — X1 / P1 / A1 (Bambu Studio `.gcode` and `.gcode.3mf`)
- **Prusa** — CORE One, MK4/MK4S, MK3.5, MINI, XL, MK3/MK3S (PrusaSlicer `.gcode`
  and binary `.bgcode`)

## Run

```bash
./run.sh                                 # empty window, then Open…
./run.sh ~/Downloads/part.gcode          # open a file directly
./run.sh ~/Downloads/part.gcode.3mf      # Bambu "plate sliced file"
./run.sh ~/Downloads/part.bgcode         # Prusa binary G-code
./install-desktop.sh                     # optional: add to the app menu
```

Needs only what Fedora Workstation ships: `python3`, `python3-gobject`, `gtk4`,
`libadwaita`, `gtksourceview5`.

## Using it

- Click any line (or use arrow keys) — the right pane updates.
- **Ctrl+L** jumps to a line number. **Ctrl+O** open, **Ctrl+S** save,
  **Ctrl+Shift+S** save as.
- The pill next to each command says where the explanation comes from:
  - **Standard G-code** — behaves like the Marlin standard.
  - **Prusa-specific · documented by Prusa** — from Prusa's published G-code
    docs and the comments in PrusaSlicer's printer profiles.
  - **Bambu-specific · community knowledge** — Bambu doesn't publish docs for
    these; text is based on Bambu's own comments and community research.
  - Anything still uncertain says "believed" or "purpose isn't public".
- Highlighted rows in *Machine state* were changed by the current line.
- Editing: type in the left pane. Saving a `.gcode.3mf` rewrites the plate's
  G-code *and* its `.md5` checksum so the printer accepts the file.
- A `.bgcode` file opens as readable text, but can't be written back as binary:
  Save asks for a `.gcode` name instead (Prusa printers print plain `.gcode` too).

## Layout

```
gcode_analyzer/
  parser.py          text line -> ParsedLine
  state.py           MachineState + StateTracker (checkpointed replay)
  reference.py       Profile / CommandInfo types
  explain.py         ParsedLine + state + Profile -> Explanation
  fileio.py          .gcode / .gcode.3mf / .bgcode load and save
  bgcode.py          Prusa binary G-code reader (heatshrink + MeatPack)
  dialects/common.py standard Marlin commands shared by all profiles
  dialects/bambu.py  the Bambu Lab command reference
  dialects/prusa.py  the Prusa command reference
  ui/                GTK window, explanation pane, CSS, G-code highlighting
tests/               python3 -m unittest
docs/specs/          design spec
```

## Adding a machine type

Create `gcode_analyzer/dialects/<machine>.py` that builds a `Profile`
(see `prusa.py`): start from `common.marlin_commands(...)` and add or override
entries, then add it to the list in `dialects/__init__.py`. It shows up
in the header-bar dropdown, and `detect()` lets it be picked automatically.

## Tests

```bash
python3 -m unittest
```

## Known limitations (v0.1)

- Only the first plate of a multi-plate `.3mf` is opened.
- Syntax coloring on very large files (500k+ lines) fills in from the top in the
  background; lines far down may appear uncolored for a while.
- Machine state is a simulation from the file alone — e.g. position after G28 is
  shown as "unknown (homed)" because Bambu's home position isn't in the file.
