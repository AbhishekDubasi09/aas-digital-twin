"""Tests for the thermal-overload model and the derating rule."""

from __future__ import annotations

import statistics

import pytest

from aas_digital_twin.asset import thermal_model as tm


def test_temperature_rises_while_running_and_falls_while_stopped() -> None:
    hot = tm.step_temperature(30.0, 1.0, running=True, dt_s=1.0)
    assert hot > 30.0
    cooled = tm.step_temperature(45.0, 1.0, running=False, dt_s=1.0)
    assert cooled < 45.0


def test_slower_speed_heats_less() -> None:
    full = tm.step_temperature(35.0, 1.0, running=True, dt_s=1.0)
    slow = tm.step_temperature(35.0, 0.8, running=True, dt_s=1.0)
    assert slow < full


def test_trip_probability_is_zero_below_onset_and_capped_above() -> None:
    assert tm.thermal_trip_probability(39.9) == 0.0
    assert tm.thermal_trip_probability(45.0) == pytest.approx(0.3)
    assert tm.thermal_trip_probability(80.0) == tm.TRIP_MAX_PROBABILITY_PER_CYCLE


def test_derating_has_hysteresis() -> None:
    assert tm.next_speed_scale(38.5, 1.0) == tm.DERATE_SPEED_SCALE
    assert tm.next_speed_scale(36.0, tm.DERATE_SPEED_SCALE) == tm.DERATE_SPEED_SCALE
    assert tm.next_speed_scale(36.0, 1.0) == 1.0
    assert tm.next_speed_scale(33.0, tm.DERATE_SPEED_SCALE) == 1.0


def test_derating_improves_mean_oee_and_cuts_thermal_stops() -> None:
    seeds = range(150)
    base = [tm.simulate_cell(False, 150.0, s) for s in seeds]
    mitigated = [tm.simulate_cell(True, 150.0, s) for s in seeds]
    assert statistics.mean(r.oee for r in mitigated) > statistics.mean(r.oee for r in base)
    assert statistics.mean(r.thermal_stops for r in mitigated) < statistics.mean(
        r.thermal_stops for r in base
    )
    assert statistics.mean(r.availability for r in mitigated) > statistics.mean(
        r.availability for r in base
    )
