"""Thermal-overload model of the pick-and-place cell and the derating rule.

The scenario: the arm heats up while it works. Above about 40 C the drive
protection can trip, which stops the cell for 20 to 40 s (a thermal
protective stop with cool-down). The gateway watches the temperature and
slows the cell down before the trip zone, which trades some speed for far
fewer long stops.

Everything here is a model, not a measurement of a real robot. The constants
are chosen to be plausible and are documented so they can be challenged.
The same functions are used by the Gazebo cycle_manager node, the gateway,
the in-process demo and the tests.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

AMBIENT_C = 25.0
START_TEMP_C = 30.0
HEAT_RATE_C_PER_S = 0.45  # heating at full speed, scales with speed_scale squared
COOL_RATE_PER_S = 0.02  # first-order cooling toward ambient while running
COOL_RATE_STOPPED_PER_S = 0.05  # faster cooling while the cell is stopped

TRIP_ONSET_C = 40.0
TRIP_FULL_C = 50.0
TRIP_MAX_PROBABILITY_PER_CYCLE = 0.6
THERMAL_STOP_RANGE_S = (20.0, 40.0)

RANDOM_FAULT_PROBABILITY_PER_CYCLE = 0.03
RANDOM_STOP_RANGE_S = (3.0, 10.0)
SCRAP_PROBABILITY_PER_CYCLE = 0.05

BASE_CYCLE_TIME_S = 4.4  # real cycle time of the FR3 pick-and-place path
IDEAL_CYCLE_TIME_S = 4.0

DERATE_WARN_C = 38.0
DERATE_RESUME_C = 34.0
DERATE_SPEED_SCALE = 0.8


def step_temperature(temp_c: float, speed_scale: float, running: bool, dt_s: float) -> float:
    """Advance the temperature by dt_s seconds."""
    if running:
        d = HEAT_RATE_C_PER_S * speed_scale**2 - COOL_RATE_PER_S * (temp_c - AMBIENT_C)
    else:
        d = -COOL_RATE_STOPPED_PER_S * (temp_c - AMBIENT_C)
    return temp_c + d * dt_s


def thermal_trip_probability(temp_c: float) -> float:
    """Probability that a finished cycle ends in a thermal protective stop."""
    x = (temp_c - TRIP_ONSET_C) / (TRIP_FULL_C - TRIP_ONSET_C)
    return TRIP_MAX_PROBABILITY_PER_CYCLE * min(max(x, 0.0), 1.0)


def next_speed_scale(temp_c: float, current_scale: float) -> float:
    """Derating rule with hysteresis. Used by the gateway."""
    if temp_c >= DERATE_WARN_C:
        return DERATE_SPEED_SCALE
    if temp_c <= DERATE_RESUME_C:
        return 1.0
    return current_scale


@dataclass
class CellRun:
    """Result of one abstract (no Gazebo) run of the cell model."""

    oee: float
    availability: float
    performance: float
    quality: float
    thermal_stops: int
    cycles: int


def simulate_cell(mitigate: bool, horizon_s: float, seed: int) -> CellRun:
    """Run the duty cycle model in pure Python and return the OEE factors.

    Used for the A/B comparison across many seeds. OEE is computed the same
    way as the gateway: A = up/(up+down), P = cycles*ideal/up (capped at 1),
    Q = good/total.
    """
    rnd = random.Random(seed)
    temp = START_TEMP_C
    scale = 1.0
    t = up = down = 0.0
    cycles = good = thermal_stops = 0
    while t < horizon_s:
        if mitigate:
            scale = next_speed_scale(temp, scale)
        dur = BASE_CYCLE_TIME_S / scale
        for _ in range(int(dur * 10)):
            temp = step_temperature(temp, scale, True, 0.1)
        t += dur
        up += dur
        cycles += 1
        if rnd.random() >= SCRAP_PROBABILITY_PER_CYCLE:
            good += 1
        stop = 0.0
        if rnd.random() < thermal_trip_probability(temp):
            stop = rnd.uniform(*THERMAL_STOP_RANGE_S)
            thermal_stops += 1
        elif rnd.random() < RANDOM_FAULT_PROBABILITY_PER_CYCLE:
            stop = rnd.uniform(*RANDOM_STOP_RANGE_S)
        if stop:
            for _ in range(int(stop * 10)):
                temp = step_temperature(temp, scale, False, 0.1)
            t += stop
            down += stop
    availability = up / (up + down)
    performance = min(cycles * IDEAL_CYCLE_TIME_S / up, 1.0)
    quality = good / cycles
    return CellRun(
        oee=availability * performance * quality,
        availability=availability,
        performance=performance,
        quality=quality,
        thermal_stops=thermal_stops,
        cycles=cycles,
    )
