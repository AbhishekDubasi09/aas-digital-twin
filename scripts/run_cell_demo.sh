#!/usr/bin/env bash
# Full-stack run: Gazebo FR3 cell -> cycle_manager -> OPC UA -> gateway (AAS REST + MQTT + CSV).
# Records the Gazebo window and the dashboard from the same run.
#
# Needs WSL2 Ubuntu 22.04 with ROS 2 Humble, Gazebo Classic 11, Mosquitto, ffmpeg,
# ImageMagick (import) and a display (WSLg). Build the ROS package first:
#   colcon build --packages-select arm_conveyor_sim   (inside ~/aas_ros2_ws)
#
# Variables: DURATION (s, default 150), MITIGATION (1 or 0), TAG, PYTHON, ROS_WS.
set -o pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
DURATION="${DURATION:-150}"
MITIGATION="${MITIGATION:-1}"
TAG="${TAG:-mitigated}"
OUT="${OUT:-$REPO/docs/run_output/$TAG}"
MEDIA="${MEDIA:-$REPO/docs/media}"
WS="${ROS_WS:-$HOME/aas_ros2_ws}"
export DISPLAY="${DISPLAY:-:0}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-7}"

# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
# shellcheck disable=SC1091
source "$WS/install/setup.bash"
export PYTHONPATH="$REPO/src:${PYTHONPATH:-}"

mkdir -p "$OUT" "$MEDIA"
FRAMES="$(mktemp -d)"
PIDS=()
cleanup() {
  for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
  pkill -f gzserver 2>/dev/null; pkill -f gzclient 2>/dev/null
  rm -rf "$FRAMES"
}
trap cleanup EXIT

# Remove leftovers from earlier runs, otherwise duplicate nodes publish duplicate counts.
for name in gzserver gzclient cycle_manager.py opcua_bridge_node.py robot_state_publisher   factory_cell.launch gateway.run live_dashboard; do
  pkill -9 -f "$name" 2>/dev/null
done
sleep 3
pgrep mosquitto >/dev/null || mosquitto -d
sleep 1

echo "[1/6] Gazebo + FR3 cell"
ros2 launch arm_conveyor_sim factory_cell.launch.py run_cycle_manager:=false \
  > "$OUT/gazebo.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 120); do
  grep -q "Successfully spawned entity" "$OUT/gazebo.log" && break
  sleep 1
done
grep -q "Successfully spawned entity" "$OUT/gazebo.log" || { echo "spawn failed"; exit 1; }
sleep 3

# Put the arm in the ready pose so the recording does not start from the all-zero pose.
ros2 topic pub --times 15 -r 10 /arm_conveyor/set_joint_trajectory trajectory_msgs/msg/JointTrajectory   "{joint_names: [fr3_joint1, fr3_joint2, fr3_joint3, fr3_joint4, fr3_joint5, fr3_joint6, fr3_joint7, fr3_finger_joint1, fr3_finger_joint2], points: [{positions: [0.0, -0.7854, 0.0, -2.3562, 0.0, 1.5708, 0.7854, 0.04, 0.04], time_from_start: {sec: 0, nanosec: 60000000}}]}"   > /dev/null 2>&1

echo "[2/6] OPC UA server and ROS bridge"
"$PY" "$WS/install/arm_conveyor_sim/lib/arm_conveyor_sim/opcua_bridge_node.py" \
  > "$OUT/opcua_bridge.log" 2>&1 &
PIDS+=($!)

echo "[3/6] gateway, AAS REST API, MQTT, CSV"
GW_FLAGS=()
[ "$MITIGATION" = "0" ] && GW_FLAGS+=(--no-mitigation)
"$PY" -m aas_digital_twin.gateway.run --duration "$DURATION" --out "$OUT" "${GW_FLAGS[@]}" \
  > "$OUT/gateway.log" 2>&1 &
GW_PID=$!
PIDS+=($GW_PID)
for _ in $(seq 1 90); do
  [ -s "$OUT/telemetry.csv" ] && break
  sleep 1
done

echo "[4/6] cycle_manager and dashboard recorder"
ros2 run arm_conveyor_sim cycle_manager.py > "$OUT/cycle_manager.log" 2>&1 &
PIDS+=($!)
"$PY" -m aas_digital_twin.dashboard.live_dashboard --record "$DURATION" \
  --out-mp4 "$MEDIA/dashboard_${TAG}.mp4" --out-png "$MEDIA/dashboard_${TAG}.png" \
  > "$OUT/dashboard.log" 2>&1 &
PIDS+=($!)

# AAS REST evidence, taken near the end while the gateway still serves it.
(
  sleep $((DURATION - 8))
  curl -s "http://127.0.0.1:8080/api/v3.0/shells" > "$OUT/aas_shells.json"
  curl -s "http://127.0.0.1:8080/api/v3.0/submodels" > "$OUT/aas_submodels.json"
) &

echo "[5/6] capturing the Gazebo window for ${DURATION}s"
WID="$(xwininfo -root -tree | grep '"Gazebo"' | head -n 1 | awk '{print $1}')"
if [ -z "$WID" ]; then echo "no Gazebo window found, no video will be made"; fi
# Wait until the window is fully drawn: wide enough and a test frame is not near-empty.
for _ in $(seq 1 40); do
  W="$(xwininfo -id "$WID" 2>/dev/null | awk '/Width:/ {print $2}')"
  import -window "$WID" -quality 85 "$FRAMES/probe.jpg" 2>/dev/null
  SZ="$(stat -c %s "$FRAMES/probe.jpg" 2>/dev/null || echo 0)"
  [ "${W:-0}" -ge 1500 ] && [ "$SZ" -gt 60000 ] && break
  sleep 1
done
rm -f "$FRAMES/probe.jpg"
START=$(date +%s.%N)
END_NS=$(echo "($START + $DURATION) * 1000000000 / 1" | bc)
capture_worker() {
  while [ "$(date +%s%N)" -lt "$END_NS" ]; do
    import -window "$WID" -quality 85 "$FRAMES/$(date +%s%N).jpg" 2>/dev/null
  done
}
# Several workers in parallel, because one window grab is slow on WSLg.
CAP_PIDS=()
for _ in 1 2 3; do
  capture_worker &
  CAP_PIDS+=($!)
done
wait "${CAP_PIDS[@]}"
N=$(ls "$FRAMES" | wc -l)
FPS=$(echo "scale=3; $N / $DURATION" | bc)
echo "captured $N frames over ${DURATION}s (${FPS} fps)"

wait "$GW_PID"

echo "[6/6] encoding"
ffmpeg -y -loglevel error -framerate "$FPS" -pattern_type glob -i "$FRAMES/*.jpg" \
  -vf "crop=1544:868:300:72,scale=1280:720" -c:v libx264 -pix_fmt yuv420p -crf 20 -r 15 \
  "$MEDIA/gazebo_${TAG}.mp4"
# Still from about a quarter of the way in.
cp "$(ls "$FRAMES"/*.jpg | sed -n "$((N / 4))p")" "$MEDIA/gazebo_scene_${TAG}.jpg"
echo "done: $OUT and $MEDIA"
