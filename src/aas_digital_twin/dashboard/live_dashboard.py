"""Matplotlib dashboard subscribing to the gateway's MQTT telemetry topics.

The MQTT message buffering logic (TelemetryBuffer) is pure and unit
testable. The drawing function is shared by two front ends: a live window
(run_live_dashboard) and a recorder that renders the same figure to an MP4
from real MQTT messages (record_dashboard).
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aas_digital_twin.gateway.bridge import (
    MQTT_TOPIC_CONDITION_MONITORING,
    MQTT_TOPIC_OPERATIONAL_STATE,
)

MAX_POINTS = 600
JOINT_COUNT = 7  # Franka Research 3


def _series() -> deque:
    return deque(maxlen=MAX_POINTS)


@dataclass
class TelemetryBuffer:
    """Fixed-length rolling history of operational state and OEE values."""

    timestamps_op: deque = field(default_factory=_series)
    joints: list[deque] = field(default_factory=lambda: [_series() for _ in range(JOINT_COUNT)])
    temperature: deque = field(default_factory=_series)
    states: deque = field(default_factory=_series)

    timestamps_oee: deque = field(default_factory=_series)
    oee: deque = field(default_factory=_series)
    availability: deque = field(default_factory=_series)
    performance: deque = field(default_factory=_series)
    quality: deque = field(default_factory=_series)
    total_cycles: deque = field(default_factory=_series)
    good_cycles: deque = field(default_factory=_series)
    speed_scale: deque = field(default_factory=_series)
    alarm: deque = field(default_factory=_series)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def ingest(self, topic: str, payload: str, timestamp_s: float) -> None:
        """Parse one MQTT message and append its values to the buffers."""
        data = json.loads(payload)
        with self.lock:
            self._ingest_locked(topic, data, timestamp_s)

    def _ingest_locked(self, topic: str, data: dict[str, Any], timestamp_s: float) -> None:
        if topic == MQTT_TOPIC_OPERATIONAL_STATE:
            self.timestamps_op.append(timestamp_s)
            for i, series in enumerate(self.joints, start=1):
                series.append(data.get(f"Joint{i}PositionRad", 0.0))
            self.temperature.append(data.get("TemperatureCelsius", 0.0))
            self.states.append(data.get("CycleState", "IDLE"))
        elif topic == MQTT_TOPIC_CONDITION_MONITORING:
            self.timestamps_oee.append(timestamp_s)
            self.oee.append(data.get("oee", 0.0))
            self.availability.append(data.get("availability", 0.0))
            self.performance.append(data.get("performance", 0.0))
            self.quality.append(data.get("quality", 0.0))
            self.total_cycles.append(data.get("total_cycle_count", 0))
            self.good_cycles.append(data.get("good_cycle_count", 0))
            self.speed_scale.append(data.get("speed_scale", 1.0))
            self.alarm.append(data.get("alarm", "NONE"))


def draw_dashboard(fig: Any, buffer: TelemetryBuffer) -> None:
    """Redraw the three dashboard panels from the buffer."""
    with buffer.lock:
        snap = TelemetryBuffer()
        snap.timestamps_op = deque(buffer.timestamps_op)
        snap.joints = [deque(j) for j in buffer.joints]
        snap.temperature = deque(buffer.temperature)
        snap.states = deque(buffer.states)
        snap.timestamps_oee = deque(buffer.timestamps_oee)
        snap.oee = deque(buffer.oee)
        snap.availability = deque(buffer.availability)
        snap.performance = deque(buffer.performance)
        snap.quality = deque(buffer.quality)
        snap.total_cycles = deque(buffer.total_cycles)
        snap.good_cycles = deque(buffer.good_cycles)
        snap.speed_scale = deque(buffer.speed_scale)
        snap.alarm = deque(buffer.alarm)
    buffer = snap
    fig.clear()
    ax_oee, ax_joints, ax_temp = fig.subplots(3, 1, gridspec_kw={"height_ratios": [3, 2, 1.4]})

    t_oee = list(buffer.timestamps_oee)
    ax_oee.plot(t_oee, list(buffer.oee), color="black", linewidth=2.4, label="OEE")
    ax_oee.plot(t_oee, list(buffer.availability), alpha=0.8, label="Availability")
    ax_oee.plot(t_oee, list(buffer.performance), alpha=0.8, label="Performance")
    ax_oee.plot(t_oee, list(buffer.quality), alpha=0.8, label="Quality")
    ax_oee.set_ylim(0, 1.05)
    ax_oee.legend(loc="lower left", ncol=4, fontsize=8)
    latest = ""
    if buffer.oee:
        latest = (
            f"   OEE {buffer.oee[-1]:.2f}   A {buffer.availability[-1]:.2f}"
            f"   P {buffer.performance[-1]:.2f}   Q {buffer.quality[-1]:.2f}"
            f"   cycles {buffer.total_cycles[-1]}   good {buffer.good_cycles[-1]}"
        )
    ax_oee.set_title("Overall Equipment Effectiveness" + latest, fontsize=10, loc="left")

    t_op = list(buffer.timestamps_op)
    for i, series in enumerate(buffer.joints, start=1):
        ax_joints.plot(t_op, list(series), label=f"J{i}", linewidth=1.2)
    ax_joints.legend(
        loc="lower right", ncol=7, fontsize=7, bbox_to_anchor=(1.0, 1.0), frameon=False
    )
    ax_joints.set_title("FR3 joint positions (rad)", fontsize=10, loc="left")

    # Values at or below 1 C are the "no reading yet" placeholder, not a measurement.
    temp_pairs = [(t, v) for t, v in zip(t_op, buffer.temperature, strict=False) if v > 1.0]
    ax_temp.plot([t for t, _ in temp_pairs], [v for _, v in temp_pairs], color="tab:orange")
    ax_temp.axhline(38.0, color="tab:red", linestyle="--", linewidth=0.8)
    ax_temp.axhline(34.0, color="tab:green", linestyle="--", linewidth=0.8)
    ax_temp.text(0.01, 0.82, "derate at 38", transform=ax_temp.transAxes, fontsize=7)
    states = list(buffer.states)
    start = None
    for ti, st in zip(t_op, states, strict=False):
        if st == "DOWN" and start is None:
            start = ti
        if st != "DOWN" and start is not None:
            ax_temp.axvspan(start, ti, color="tab:red", alpha=0.2)
            start = None
    if start is not None and t_op:
        ax_temp.axvspan(start, t_op[-1], color="tab:red", alpha=0.2)
    now_state = states[-1] if states else "-"
    alarm = buffer.alarm[-1] if buffer.alarm else "-"
    scale = buffer.speed_scale[-1] if buffer.speed_scale else 1.0
    ax_temp.set_title(
        f"Temperature (C), red band = DOWN.  State {now_state}   speed {scale:.1f}   alarm {alarm}",
        fontsize=10,
        loc="left",
    )
    ax_temp.set_xlabel("time (s)")
    fig.tight_layout()


def _subscribe(buffer: TelemetryBuffer, mqtt_host: str, mqtt_port: int) -> Any:
    import paho.mqtt.client as mqtt

    start_time = time.monotonic()

    def on_message(_client: Any, _userdata: Any, msg: Any) -> None:
        buffer.ingest(msg.topic, msg.payload.decode(), time.monotonic() - start_time)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(mqtt_host, mqtt_port)
    client.subscribe(MQTT_TOPIC_OPERATIONAL_STATE)
    client.subscribe(MQTT_TOPIC_CONDITION_MONITORING)
    client.loop_start()
    return client


def run_live_dashboard(mqtt_host: str = "localhost", mqtt_port: int = 1883) -> None:
    """Open a live matplotlib window fed by MQTT."""
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    buffer = TelemetryBuffer()
    client = _subscribe(buffer, mqtt_host, mqtt_port)
    fig = plt.figure(figsize=(10, 7.5))

    def _update(_frame: int) -> list[Any]:
        draw_dashboard(fig, buffer)
        return []

    _anim = FuncAnimation(fig, _update, interval=1000, cache_frame_data=False)
    plt.show()
    client.loop_stop()


def record_dashboard(
    out_mp4: Path,
    out_png: Path,
    duration_s: float,
    fps: int = 4,
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883,
) -> None:
    """Render the dashboard to an MP4 from live MQTT data for duration_s seconds."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FFMpegWriter

    buffer = TelemetryBuffer()
    client = _subscribe(buffer, mqtt_host, mqtt_port)
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
    writer = FFMpegWriter(fps=fps, codec="libx264", extra_args=["-pix_fmt", "yuv420p"])
    t0 = time.monotonic()
    frame = 0
    with writer.saving(fig, str(out_mp4), dpi=100):
        while time.monotonic() - t0 < duration_s:
            draw_dashboard(fig, buffer)
            writer.grab_frame()
            frame += 1
            time.sleep(max(0.0, t0 + frame / fps - time.monotonic()))
    draw_dashboard(fig, buffer)
    fig.savefig(out_png, dpi=100)
    plt.close(fig)
    client.loop_stop()


def render_from_csv(csv_path: Path, out_mp4: Path, out_png: Path, fps: int = 4) -> None:
    """Render the dashboard to an MP4 from a telemetry CSV logged by gateway.run.

    Every CSV row is what the gateway also published to MQTT at that moment,
    so the picture is the same as the live dashboard, with exact timing.
    """
    import csv

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FFMpegWriter

    rows = list(csv.DictReader(csv_path.open()))
    buffer = TelemetryBuffer()
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
    writer = FFMpegWriter(fps=fps, codec="libx264", extra_args=["-pix_fmt", "yuv420p"])
    end = float(rows[-1]["t_s"])
    idx = 0
    n_frames = int(end * fps) + 1
    with writer.saving(fig, str(out_mp4), dpi=100):
        for frame in range(n_frames):
            now = frame / fps
            while idx < len(rows) and float(rows[idx]["t_s"]) <= now:
                r = rows[idx]
                op = {f"Joint{i}PositionRad": float(r[f"joint{i}_rad"]) for i in range(1, 8)}
                op["TemperatureCelsius"] = float(r["temperature_c"])
                op["CycleState"] = r["state"]
                cm = {
                    "oee": float(r["oee"]),
                    "availability": float(r["availability"]),
                    "performance": float(r["performance"]),
                    "quality": float(r["quality"]),
                    "total_cycle_count": int(float(r["total_cycles"])),
                    "good_cycle_count": int(float(r["good_cycles"])),
                    "speed_scale": float(r["speed_scale"]),
                    "alarm": r["alarm"],
                }
                t = float(r["t_s"])
                buffer.ingest(MQTT_TOPIC_OPERATIONAL_STATE, json.dumps(op), t)
                buffer.ingest(MQTT_TOPIC_CONDITION_MONITORING, json.dumps(cm), t)
                idx += 1
            draw_dashboard(fig, buffer)
            writer.grab_frame()
    fig.savefig(out_png, dpi=100)
    plt.close(fig)


def main() -> None:
    """CLI entry point: live window, --record to write an MP4, or --from-csv to replay."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=float, default=0.0, help="seconds to record to MP4")
    parser.add_argument("--from-csv", type=Path, default=None, help="render from a telemetry CSV")
    parser.add_argument("--out-mp4", type=Path, default=Path("docs/media/dashboard_live.mp4"))
    parser.add_argument("--out-png", type=Path, default=Path("docs/media/dashboard_live.png"))
    args = parser.parse_args()
    if args.from_csv is not None:
        render_from_csv(args.from_csv, args.out_mp4, args.out_png)
    elif args.record > 0:
        record_dashboard(args.out_mp4, args.out_png, args.record)
    else:
        run_live_dashboard()


if __name__ == "__main__":
    main()
