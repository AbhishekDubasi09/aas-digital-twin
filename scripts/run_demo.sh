#!/usr/bin/env bash
# Runs the 45 s end-to-end demo and writes telemetry.jsonl and oee_over_time.png
# into docs/run_output/. Needs a Mosquitto broker on localhost:1883.
# This runs the in-process asset simulator, not Gazebo.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! (exec 3<>/dev/tcp/127.0.0.1/1883) 2>/dev/null; then
  echo "No MQTT broker on localhost:1883. Start one with: mosquitto -d" >&2
  exit 1
fi
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
[ -x .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe
"$PY" -m aas_digital_twin.demo
echo "Wrote docs/run_output/telemetry.jsonl and docs/run_output/oee_over_time.png"
