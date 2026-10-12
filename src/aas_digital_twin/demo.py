"""Fixed-duration demo: asset sim -> OPC UA -> AAS -> MQTT -> logged OEE plot.

Runs a lightweight in-process duty-cycle simulator that replays the real FR3
pick-and-place joint path (the same RUNNING/DOWN
fault-cycling logic as the ROS2 cycle_manager node, see
ros2_ws/src/arm_conveyor_sim/scripts/cycle_manager.py) writing into a real
OPC UA server, polls it through the real Gateway into AAS submodels and
MQTT, and at the end plots the OEE series actually produced by that run.

The full ROS2 + Gazebo asset layer is verified separately (see README);
this script keeps the demo runnable without a WSL/ROS2 environment while
exercising the identical OPC UA / AAS / gateway / MQTT code paths.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import time
from pathlib import Path

from asyncua import Client

from aas_digital_twin.aas.api import build_object_store
from aas_digital_twin.asset.fr3_kinematics import pick_and_place_waypoints
from aas_digital_twin.gateway.bridge import Gateway, make_paho_publisher
from aas_digital_twin.opcua.server import AssetOpcUaServer

DEMO_ENDPOINT = "opc.tcp://127.0.0.1:48440/aas-twin-demo/"
CYCLE_TIME_S = 4.0
DOWN_PROBABILITY_PER_CYCLE = 0.08
DOWN_DURATION_RANGE_S = (3.0, 8.0)
SCRAP_PROBABILITY_PER_CYCLE = 0.05
CONVEYOR_SPEED_MPS = 0.15


async def _run_asset_simulator(server: AssetOpcUaServer, stop_event: asyncio.Event) -> None:
    """Drive the same duty-cycle logic as the ROS2 cycle_manager, in-process."""
    start = time.monotonic()
    cycle_count = 0
    good_count = 0
    state = "RUNNING"
    down_until = 0.0

    while not stop_event.is_set():
        now = time.monotonic()
        elapsed = now - start
        await server.update_temperature(
            35.0 + 3.0 * math.sin(elapsed / 20.0) + random.uniform(-0.4, 0.4)
        )

        if state == "DOWN":
            if now >= down_until:
                state = "RUNNING"
            else:
                await server.update_cycle_state("DOWN")
                await server.update_conveyor_speed(0.0)
                await asyncio.sleep(0.5)
                continue

        scrap = random.random() < SCRAP_PROBABILITY_PER_CYCLE
        plan = pick_and_place_waypoints(scrap)
        for _, q, _ in plan[1:]:
            await server.update_joint_positions([float(v) for v in q])
            await asyncio.sleep(CYCLE_TIME_S / len(plan) / 4)  # sped up for a short demo
        cycle_count += 1
        if not scrap:
            good_count += 1
        await server.update_counts(cycle_count, good_count)
        await server.update_conveyor_speed(CONVEYOR_SPEED_MPS)
        await server.update_cycle_state(state)

        if random.random() < DOWN_PROBABILITY_PER_CYCLE:
            state = "DOWN"
            down_until = now + random.uniform(*DOWN_DURATION_RANGE_S)


async def run_demo(
    duration_s: float = 45.0,
    output_dir: Path | None = None,
    use_real_mqtt: bool = True,
) -> Path:
    """Run the full stack for a fixed duration and write telemetry + a plot.

    Args:
        duration_s: how long to run the demo for.
        output_dir: where to write telemetry.jsonl and oee_over_time.png.
        use_real_mqtt: publish to a real Mosquitto broker on localhost:1883
            if True; otherwise use a no-op publisher (useful without a broker).

    Returns:
        Path to the generated OEE-over-time plot.
    """
    output_dir = output_dir or Path("docs/run_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    server = AssetOpcUaServer(endpoint=DEMO_ENDPOINT)
    await server.start()

    stop_event = asyncio.Event()
    sim_task = asyncio.create_task(_run_asset_simulator(server, stop_event))

    store = build_object_store()
    if use_real_mqtt:
        publish = make_paho_publisher(host="localhost", port=1883)
    else:
        publish = lambda topic, payload: None  # noqa: E731

    telemetry_log: list[dict] = []
    oee_series: list[tuple[float, float, float, float, float]] = []

    original_publish = publish

    def logging_publish(topic: str, payload: str) -> None:
        record = {"t": time.monotonic(), "topic": topic, "payload": json.loads(payload)}
        telemetry_log.append(record)
        if topic == "aas-digital-twin/condition_monitoring":
            d = record["payload"]
            oee_series.append(
                (record["t"], d["oee"], d["availability"], d["performance"], d["quality"])
            )
        original_publish(topic, payload)

    gateway = Gateway(opcua_endpoint=DEMO_ENDPOINT, object_store=store, publish=logging_publish)

    start_time = time.monotonic()
    async with Client(url=DEMO_ENDPOINT) as opcua_client:
        while time.monotonic() - start_time < duration_s:
            await gateway.poll_once(opcua_client)
            await asyncio.sleep(1.0)

    stop_event.set()
    await sim_task
    await server.stop()

    telemetry_path = output_dir / "telemetry.jsonl"
    with telemetry_path.open("w") as f:
        for record in telemetry_log:
            f.write(json.dumps(record) + "\n")

    plot_path = output_dir / "oee_over_time.png"
    _plot_oee_series(oee_series, plot_path)
    return plot_path


def _plot_oee_series(
    series: list[tuple[float, float, float, float, float]], out_path: Path
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not series:
        raise RuntimeError("no OEE data was collected during the demo run")

    t0 = series[0][0]
    times = [s[0] - t0 for s in series]
    oee = [s[1] for s in series]
    availability = [s[2] for s in series]
    performance = [s[3] for s in series]
    quality = [s[4] for s in series]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(times, oee, label="OEE", linewidth=2, color="black")
    ax.plot(times, availability, label="Availability", alpha=0.7)
    ax.plot(times, performance, label="Performance", alpha=0.7)
    ax.plot(times, quality, label="Quality", alpha=0.7)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("fraction (0-1)")
    ax.set_title("OEE and components over a live demo run (real simulated data)")
    ax.set_ylim(0, 1.05)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    """CLI entrypoint: run a 45s demo and print where the outputs landed."""
    plot_path = asyncio.run(run_demo())
    print(f"Demo complete. OEE plot written to: {plot_path}")


if __name__ == "__main__":
    main()
