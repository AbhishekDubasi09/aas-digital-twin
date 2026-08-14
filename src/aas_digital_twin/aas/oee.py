"""OEE (Overall Equipment Effectiveness) calculation from real duty-cycle data.

OEE = Availability x Performance x Quality, computed from actual measured
uptime/downtime, cycle counts, and scrap counts. No component is hardcoded:
every input is a measured or configured quantity from the running asset.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OeeResult:
    """The three OEE components and their product, all in [0, 1]."""

    availability: float
    performance: float
    quality: float

    @property
    def oee(self) -> float:
        """Overall Equipment Effectiveness: availability x performance x quality."""
        return self.availability * self.performance * self.quality


def compute_oee(
    planned_production_time_s: float,
    downtime_s: float,
    ideal_cycle_time_s: float,
    total_cycle_count: int,
    good_cycle_count: int,
) -> OeeResult:
    """Compute OEE from measured production data.

    Args:
        planned_production_time_s: total scheduled run time, in seconds.
        downtime_s: measured unplanned downtime within that window, in seconds.
        ideal_cycle_time_s: theoretical best time per cycle, in seconds.
        total_cycle_count: number of cycles actually attempted.
        good_cycle_count: number of cycles that produced a good part.

    Returns:
        An OeeResult with availability, performance, and quality each in [0, 1].

    Raises:
        ValueError: if downtime exceeds planned time, or good count exceeds total.
    """
    if planned_production_time_s <= 0:
        raise ValueError("planned_production_time_s must be positive")
    if downtime_s < 0 or downtime_s > planned_production_time_s:
        raise ValueError("downtime_s must be within [0, planned_production_time_s]")
    if total_cycle_count < 0 or good_cycle_count < 0:
        raise ValueError("cycle counts must be non-negative")
    if good_cycle_count > total_cycle_count:
        raise ValueError("good_cycle_count cannot exceed total_cycle_count")

    run_time_s = planned_production_time_s - downtime_s
    availability = run_time_s / planned_production_time_s

    if run_time_s <= 0 or total_cycle_count == 0:
        performance = 0.0
    else:
        performance = min(1.0, (ideal_cycle_time_s * total_cycle_count) / run_time_s)

    quality = 0.0 if total_cycle_count == 0 else good_cycle_count / total_cycle_count

    return OeeResult(availability=availability, performance=performance, quality=quality)
