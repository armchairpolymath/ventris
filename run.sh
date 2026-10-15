#!/usr/bin/env bash
# Launch G-code Analyzer. Usage: ./run.sh [file.gcode | file.gcode.3mf]
cd "$(dirname "$(readlink -f "$0")")" && exec python3 -m gcode_analyzer "$@"
