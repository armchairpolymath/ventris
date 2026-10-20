# Test fixtures

- `prusa_mk4s_cube.bgcode` / `prusa_mk4s_cube_ref.gcode` — from Prusa's libbgcode
  test data (`tests/data/mini_cube_ps2.8.1*`, https://github.com/prusa3d/libbgcode,
  AGPL-3.0). A real PrusaSlicer 2.8.1 MK4S binary G-code file and libbgcode's
  reference ASCII conversion of it. Used to check Ventris's decoder byte-for-byte.
- `kobra3_sample.gcode` — written for Ventris. A two-layer file in the shape Anycubic
  Slicer Next writes for a Kobra 3 (G9111 start line, Klipper object labels,
  speed-mode M73, a filament-swap block), with start/end code taken from the Kobra 3
  printer profile shipped with OrcaSlicer (AGPL-3.0).
