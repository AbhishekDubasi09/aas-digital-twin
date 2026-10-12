"""Compare the baseline and the derated run from their logged CSV files.

Reads docs/run_output/baseline/telemetry.csv and docs/run_output/mitigated/telemetry.csv,
writes docs/run_output/ab_comparison.png and ab_summary.json. The Monte Carlo
numbers come from the same thermal model, run for many seeds, so a single
Gazebo run is not mistaken for a statistical result.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from aas_digital_twin.asset import thermal_model as tm


def load(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open()))


def downtime_episodes(rows: list[dict[str, str]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    start = None
    for r in rows:
        t = float(r["t_s"])
        if r["state"] == "DOWN" and start is None:
            start = t
        if r["state"] != "DOWN" and start is not None:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, float(rows[-1]["t_s"])))
    return out


def summarize(rows: list[dict[str, str]]) -> dict[str, float]:
    last = rows[-1]
    return {
        "duration_s": float(last["t_s"]),
        "oee": float(last["oee"]),
        "availability": float(last["availability"]),
        "performance": float(last["performance"]),
        "quality": float(last["quality"]),
        "cycles": int(float(last["total_cycles"])),
        "good_cycles": int(float(last["good_cycles"])),
        "max_temperature_c": max(float(r["temperature_c"]) for r in rows),
        "down_episodes": len(downtime_episodes(rows)),
        "down_seconds": round(sum(b - a for a, b in downtime_episodes(rows)), 1),
    }


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/run_output")
    base = load(root / "baseline" / "telemetry.csv")
    mit = load(root / "mitigated" / "telemetry.csv")
    s_base, s_mit = summarize(base), summarize(mit)

    horizon = min(s_base["duration_s"], s_mit["duration_s"])
    seeds = range(300)
    mc = {}
    for name, flag in (("baseline", False), ("mitigated", True)):
        runs = [tm.simulate_cell(flag, horizon, s) for s in seeds]
        mc[name] = {
            "oee_mean": round(statistics.mean(r.oee for r in runs), 3),
            "oee_stdev": round(statistics.pstdev(r.oee for r in runs), 3),
            "availability_mean": round(statistics.mean(r.availability for r in runs), 3),
            "performance_mean": round(statistics.mean(r.performance for r in runs), 3),
            "thermal_stops_mean": round(statistics.mean(r.thermal_stops for r in runs), 2),
        }

    summary = {"gazebo_runs": {"baseline": s_base, "mitigated": s_mit}, "monte_carlo_300": mc}
    (root / "ab_summary.json").write_text(json.dumps(summary, indent=2))

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for ax, rows, title in (
        (axes[0], base, "Baseline: no derating"),
        (axes[1], mit, "With gateway derating (speed 0.8 above 38 C)"),
    ):
        t = [float(r["t_s"]) for r in rows]
        ax.plot(t, [float(r["oee"]) for r in rows], color="black", linewidth=2.2, label="OEE")
        ax.plot(t, [float(r["availability"]) for r in rows], alpha=0.7, label="Availability")
        ax.plot(t, [float(r["performance"]) for r in rows], alpha=0.7, label="Performance")
        for a, b in downtime_episodes(rows):
            ax.axvspan(a, b, color="tab:red", alpha=0.15)
        ax.set_ylim(0, 1.05)
        ax.set_title(title, loc="left", fontsize=10)
        ax.legend(loc="lower right", ncol=3, fontsize=8)
    axes[1].set_xlabel("time (s), red = DOWN")
    fig.tight_layout()
    fig.savefig(root / "ab_comparison.png", dpi=150)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
