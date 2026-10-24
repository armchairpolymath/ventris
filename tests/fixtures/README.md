# Test fixtures

- `prusa_mk4s_cube.bgcode` / `prusa_mk4s_cube_ref.gcode` — from Prusa's libbgcode
  test data (`tests/data/mini_cube_ps2.8.1*`, https://github.com/prusa3d/libbgcode,
  AGPL-3.0). A real PrusaSlicer 2.8.1 MK4S binary G-code file and libbgcode's
  reference ASCII conversion of it. Used to check Ventris's decoder byte-for-byte.
- `kobra3_sample.gcode` — written for Ventris. A two-layer file in the shape Anycubic
  Slicer Next writes for a Kobra 3 (G9111 start line, Klipper object labels,
  speed-mode M73, a filament-swap block), with start/end code taken from the Kobra 3
  printer profile shipped with OrcaSlicer (AGPL-3.0).
- `qidi_xplus4_sample.gcode` — written for Ventris. A two-layer file in the shape
  QIDIStudio writes for a QIDI X-Plus 4 with a QIDI Box (PRINT_START, Klipper layer
  info, a filament change), with start, end and filament-change code taken from the
  X-Plus 4 printer profile shipped with QIDIStudio (AGPL-3.0).
- `k1max_cp4_sample.gcode` — written for Ventris. A two-layer file in the shape
  Creality Print 4.x (Cura-based) writes for a K1 Max: Cura-style ;LAYER:/;TYPE:/;MESH:
  comments, START_PRINT/END_PRINT and Creality's fan numbering, modelled on the sample
  prints in Creality's K1_Series_Klipper repository (GPL-3.0).
