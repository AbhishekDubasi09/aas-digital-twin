"""Run the edge gateway against a live OPC UA server.

One process does three jobs:
  1. serves the AAS REST API v3.0 (BaSyx WSGI app) from the object store,
  2. polls OPC UA through the gateway, which updates that same object store
     and publishes JSON snapshots to MQTT,
  3. logs every poll to a CSV file so a plot can be made from real data.

Usage:
    python -m aas_digital_twin.gateway.run --duration 90 --out docs/run_output
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import threading
import time
from pathlib import Path
from typing import Any

from asyncua import Client

from aas_digital_twin.aas.api import build_object_store, build_wsgi_app
from aas_digital_twin.gateway.bridge import Gateway, make_paho_publisher
from aas_digital_twin.opcua.server import JOINT_COUNT

CSV_FIELDS = [
    "t_s",
    "state",
    "temperature_c",
    "conveyor_speed_mps",
    "availability",
    "performance",
    "quality",
    "oee",
    "speed_scale",
    "alarm",
    "total_cycles",
    "good_cycles",
    *[f"joint{i}_rad" for i in range(1, JOINT_COUNT + 1)],
]


async def _connect(endpoint: str, timeout_s: float = 90.0) -> Client:
    """Wait until the OPC UA server accepts a connection."""
    deadline = time.monotonic() + timeout_s
    while True:
        client = Client(url=endpoint)
        try:
            await client.connect()
            return client
        except Exception:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(1.0)


async def run(
    duration_s: float,
    out_dir: Path,
    opcua_endpoint: str = "opc.tcp://127.0.0.1:4840/aas-twin/",
    rest_host: str = "127.0.0.1",
    rest_port: int = 8080,
    mqtt_host: str = "localhost",
    poll_interval_s: float = 0.5,
    mitigation: bool = True,
) -> Path:
    """Run the gateway for duration_s seconds and return the CSV path."""
    from werkzeug.serving import make_server

    out_dir.mkdir(parents=True, exist_ok=True)
    store = build_object_store()
    server = make_server(rest_host, rest_port, build_wsgi_app(store), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    publish = make_paho_publisher(host=mqtt_host)
    op = next(sm for sm in store if sm.id_short == "OperationalState")
    cm = next(sm for sm in store if sm.id_short == "ConditionMonitoring")

    csv_path = out_dir / "telemetry.csv"
    client = await _connect(opcua_endpoint)
    # Built after the connection so the uptime clock starts when data starts.
    gateway = Gateway(
        opcua_endpoint=opcua_endpoint,
        object_store=store,
        publish=publish,
        mitigation=mitigation,
    )
    try:
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            t0 = time.monotonic()
            while time.monotonic() - t0 < duration_s:
                await gateway.poll_once(client)
                row: dict[str, Any] = {
                    "t_s": round(time.monotonic() - t0, 3),
                    "state": op.get_referable("CycleState").value,
                    "temperature_c": op.get_referable("TemperatureCelsius").value,
                    "conveyor_speed_mps": op.get_referable("ConveyorSpeedMPerS").value,
                    "availability": cm.get_referable("Availability").value,
                    "performance": cm.get_referable("Performance").value,
                    "quality": cm.get_referable("Quality").value,
                    "oee": cm.get_referable("OEE").value,
                    "speed_scale": cm.get_referable("SpeedScale").value,
                    "alarm": cm.get_referable("ActiveAlarm").value,
                    "total_cycles": cm.get_referable("TotalCycleCount").value,
                    "good_cycles": cm.get_referable("GoodCycleCount").value,
                }
                for i in range(1, JOINT_COUNT + 1):
                    row[f"joint{i}_rad"] = op.get_referable(f"Joint{i}PositionRad").value
                writer.writerow(row)
                f.flush()
                await asyncio.sleep(poll_interval_s)
    finally:
        await client.disconnect()
        server.shutdown()
    return csv_path


def plot_oee(csv_path: Path, out_path: Path) -> None:
    """Plot OEE and its factors from the logged CSV, shading DOWN periods."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = list(csv.DictReader(csv_path.open()))
    if not rows:
        raise RuntimeError("no telemetry rows to plot")
    t = [float(r["t_s"]) for r in rows]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(t, [float(r["oee"]) for r in rows], color="black", linewidth=2.2, label="OEE")
    for key, label in (
        ("availability", "Availability"),
        ("performance", "Performance"),
        ("quality", "Quality"),
    ):
        ax.plot(t, [float(r[key]) for r in rows], alpha=0.75, label=label)
    start = None
    for r, ti in zip(rows, t, strict=True):
        if r["state"] == "DOWN" and start is None:
            start = ti
        if r["state"] != "DOWN" and start is not None:
            ax.axvspan(start, ti, color="tab:red", alpha=0.12)
            start = None
    if start is not None:
        ax.axvspan(start, t[-1], color="tab:red", alpha=0.12)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("fraction (0 to 1)")
    ax.set_ylim(0, 1.05)
    ax.set_title("OEE and its factors from a live Gazebo run (red = DOWN)")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--out", type=Path, default=Path("docs/run_output"))
    parser.add_argument("--opcua", default="opc.tcp://127.0.0.1:4840/aas-twin/")
    parser.add_argument("--no-mitigation", action="store_true", help="baseline run, no derating")
    args = parser.parse_args()
    csv_path = asyncio.run(
        run(args.duration, args.out, opcua_endpoint=args.opcua, mitigation=not args.no_mitigation)
    )
    plot_oee(csv_path, args.out / "oee_over_time.png")
    print(f"wrote {csv_path} and {args.out / 'oee_over_time.png'}")


if __name__ == "__main__":
    main()
