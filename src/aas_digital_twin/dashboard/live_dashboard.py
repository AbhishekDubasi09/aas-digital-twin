"""Matplotlib dashboard subscribing to the gateway's MQTT telemetry topics.

The MQTT message buffering logic (TelemetryBuffer) is pure and unit
testable. The matplotlib animation loop around it is a thin, untested
wrapper, since it requires a display and a live broker to exercise.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from aas_digital_twin.gateway.bridge import (
    MQTT_TOPIC_CONDITION_MONITORING,
    MQTT_TOPIC_OPERATIONAL_STATE,
)

MAX_POINTS = 300
JOINT_COUNT = 7  # Franka Research 3


@dataclass
class TelemetryBuffer:
    """Fixed-length rolling history of operational state and OEE values."""

    timestamps_op: deque = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    joints: list[deque] = field(
        default_factory=lambda: [deque(maxlen=MAX_POINTS) for _ in range(JOINT_COUNT)]
    )
    temperature: deque = field(default_factory=lambda: deque(maxlen=MAX_POINTS))

    timestamps_oee: deque = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    oee: deque = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    availability: deque = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    performance: deque = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    quality: deque = field(default_factory=lambda: deque(maxlen=MAX_POINTS))

    def ingest(self, topic: str, payload: str, timestamp_s: float) -> None:
        """Parse one MQTT message and append its values to the buffers."""
        data = json.loads(payload)
        if topic == MQTT_TOPIC_OPERATIONAL_STATE:
            self.timestamps_op.append(timestamp_s)
            for i, series in enumerate(self.joints, start=1):
                series.append(data.get(f"Joint{i}PositionRad", 0.0))
            self.temperature.append(data.get("TemperatureCelsius", 0.0))
        elif topic == MQTT_TOPIC_CONDITION_MONITORING:
            self.timestamps_oee.append(timestamp_s)
            self.oee.append(data.get("oee", 0.0))
            self.availability.append(data.get("availability", 0.0))
            self.performance.append(data.get("performance", 0.0))
            self.quality.append(data.get("quality", 0.0))


def run_live_dashboard(mqtt_host: str = "localhost", mqtt_port: int = 1883) -> None:
    """Open a live matplotlib window plotting joint positions and OEE over MQTT."""
    import time

    import matplotlib.pyplot as plt
    import paho.mqtt.client as mqtt
    from matplotlib.animation import FuncAnimation

    buffer = TelemetryBuffer()
    start_time = time.monotonic()

    def on_message(_client: Any, _userdata: Any, msg: Any) -> None:
        buffer.ingest(msg.topic, msg.payload.decode(), time.monotonic() - start_time)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(mqtt_host, mqtt_port)
    client.subscribe(MQTT_TOPIC_OPERATIONAL_STATE)
    client.subscribe(MQTT_TOPIC_CONDITION_MONITORING)
    client.loop_start()

    fig, (ax_joints, ax_oee) = plt.subplots(2, 1, figsize=(9, 7))

    def update(_frame: int) -> Sequence:
        ax_joints.clear()
        ax_joints.set_title("Joint positions (rad)")
        for i, series in enumerate(buffer.joints, start=1):
            ax_joints.plot(buffer.timestamps_op, series, label=f"J{i}")
        ax_joints.legend(loc="upper right", ncol=7, fontsize=8)
        ax_joints.set_xlabel("time (s)")

        ax_oee.clear()
        ax_oee.set_title("OEE and components")
        ax_oee.plot(buffer.timestamps_oee, buffer.oee, label="OEE", linewidth=2)
        ax_oee.plot(buffer.timestamps_oee, buffer.availability, label="Availability", alpha=0.6)
        ax_oee.plot(buffer.timestamps_oee, buffer.performance, label="Performance", alpha=0.6)
        ax_oee.plot(buffer.timestamps_oee, buffer.quality, label="Quality", alpha=0.6)
        ax_oee.set_ylim(0, 1.05)
        ax_oee.legend(loc="lower right")
        ax_oee.set_xlabel("time (s)")

        fig.tight_layout()
        return ()

    _anim = FuncAnimation(fig, update, interval=1000, cache_frame_data=False)
    plt.show()
    client.loop_stop()


if __name__ == "__main__":
    run_live_dashboard()
