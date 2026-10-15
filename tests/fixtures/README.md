# Test fixtures

- `prusa_mk4s_cube.bgcode` / `prusa_mk4s_cube_ref.gcode` — from Prusa's libbgcode
  test data (`tests/data/mini_cube_ps2.8.1*`, https://github.com/prusa3d/libbgcode,
  AGPL-3.0). A real PrusaSlicer 2.8.1 MK4S binary G-code file and libbgcode's
  reference ASCII conversion of it. Used to check our decoder byte-for-byte.
