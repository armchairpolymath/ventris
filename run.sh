#!/usr/bin/env bash
# Launch Ventris. Usage: ./run.sh [file.gcode | file.gcode.3mf | file.bgcode]
# Uses the project's .venv (see README) when present.
cd "$(dirname "$0")" || exit 1
python=python3
[ -x .venv/bin/python ] && python=.venv/bin/python
exec "$python" -m ventris "$@"
