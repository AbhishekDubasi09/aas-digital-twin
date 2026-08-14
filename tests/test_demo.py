"""Test that the demo script runs end-to-end and produces real output files."""

from __future__ import annotations

import json

from aas_digital_twin.demo import run_demo


async def test_demo_run_produces_telemetry_log_and_plot(tmp_path) -> None:
    plot_path = await run_demo(duration_s=6.0, output_dir=tmp_path, use_real_mqtt=False)

    assert plot_path.exists()
    assert plot_path.stat().st_size > 1000  # a real PNG, not an empty file

    telemetry_path = tmp_path / "telemetry.jsonl"
    assert telemetry_path.exists()
    lines = telemetry_path.read_text().strip().splitlines()
    assert len(lines) > 0

    records = [json.loads(line) for line in lines]
    topics = {r["topic"] for r in records}
    assert topics == {
        "aas-digital-twin/operational_state",
        "aas-digital-twin/condition_monitoring",
    }

    oee_records = [r for r in records if r["topic"] == "aas-digital-twin/condition_monitoring"]
    assert all(0.0 <= r["payload"]["oee"] <= 1.0 for r in oee_records)
