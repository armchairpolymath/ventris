# G-code Analyzer — Design (v0.1 prototype)

## Purpose
A Fedora desktop app that helps a G-code beginner understand a print file line by line.
G-code on the left; on the right, a plain-English explanation of the line under the
cursor plus a snapshot of what the machine is doing at that point.

Audience: Patrick, assumed to know very little G-code. Explanations are written for a
beginner first, with technical detail available underneath.

## Scope

In v0.1:
- Native GTK4 + libadwaita app, Python, using GtkSourceView 5 for the editor.
- One machine profile: **Bambu Lab** printers (X1/P1/A1 family; Marlin-derived firmware
  plus Bambu's own M-codes).
- Open `.gcode` and Bambu `.gcode.3mf` (zip containing `Metadata/plate_N.gcode`).
- Edit the G-code; Save / Save As. Saving a `.3mf` rewrites the plate G-code and its
  `.md5` sidecar so the printer accepts it.
- Right pane: explanation of the current line + machine state panel.
- Explanations for slicer comments (`; FEATURE: Outer wall`, `; CHANGE_LAYER`, …).

Not in v0.1 (YAGNI): toolpath preview, other machine types, sending to printers,
multi-plate selection UI (first plate is opened; choice deferred), syntax-error linting.

## Architecture

```
gcode_analyzer/
  parser.py          parse_line(text) -> ParsedLine            (pure, no GTK)
  reference.py       CommandInfo / ParamInfo dataclasses, Profile base class
  dialects/bambu.py  Bambu profile: command reference + comment markers
  explain.py         explain(parsed, state, profile) -> Explanation
  state.py           MachineState + StateTracker (checkpointed replay)
  fileio.py          load(path) -> Document ; save(document, text, path)
  ui/window.py       main window, paned layout, header bar
  ui/explain_view.py right-hand pane widgets
  ui/gcode.lang      GtkSourceView highlighting for G-code
  app.py / __main__  Adw.Application entry point
```

Everything except `ui/` is GTK-free and unit-tested with stdlib `unittest`.

### Parser
`ParsedLine(raw, code, params, comment)`. `code` is normalised (`g01` → `G1`,
`G29.1` kept). `params` is an ordered dict of letter → string value (string, because
Bambu uses flags like `M1002 judge_flag` and `M622 J1`). Command words that are not
standard letter+number (e.g. `M1002 gcode_claim_action : 2`) keep their remainder in
`params["_args"]`. Blank and comment-only lines have `code=None`.

### Profiles (extensibility point)
A `Profile` has `name`, `commands: dict[str, CommandInfo]`, `comment_markers`
(prefix → explanation), and `detect(text) -> score`. Adding a machine later = adding
one module in `dialects/` and registering it. The header bar shows a profile dropdown
(one entry for now).

`CommandInfo`: `name`, `summary` (one beginner sentence), `details` (deeper text),
`params: dict[letter, ParamInfo]`, `source` (`documented` | `community`), and an
optional `describe(parsed, state) -> str` that builds a line-specific sentence
("Move the nozzle to X 120 mm, Y 80 mm while pushing out 0.4 mm of filament").

### Machine state
`MachineState` fields: units, positioning (abs/rel), extruder mode (abs/rel), X/Y/Z/E,
feed rate, hotend target, bed target, chamber target, part/aux/chamber fan %, current
layer and Z height (from comments / `M73 L`), feature type, active filament slot,
print progress %. `apply(parsed)` returns the next state and the set of changed fields
(the UI highlights them).

`StateTracker` stores a full snapshot every 500 lines; the state at line *n* is
computed by replaying from the nearest checkpoint. An edit to line *k* drops
checkpoints after *k*. This keeps memory flat for 500k+-line Bambu files.

### Data flow
Open → `fileio.load` → text into buffer → tracker built from lines.
Cursor moves (debounced) → parse line → `state_at(line)` → `explain()` → right pane.
Buffer edit → tracker invalidated from edited line → right pane refreshed.

### Error handling
- Unknown command: explanation says it is not in the Bambu reference and may be a
  typo or an undocumented command; state is unchanged.
- Malformed parameter values: shown as-is, state ignores them.
- Unreadable file / bad 3mf: Adw toast/dialog with the reason; no crash.
- Unsaved changes on close or open: confirm dialog.

## Testing
`python3 -m unittest` covers parser, state replay (incl. checkpoint invalidation),
explanation text for representative commands, and 3mf round-trip with md5 check.
UI verified manually by launching the app against a sample Bambu file.

## Run
`./run.sh` (or `python3 -m gcode_analyzer [file]`). Optional `install-desktop.sh`
adds an app-menu entry.
