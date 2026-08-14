"""Unit tests for the OEE calculation."""

from __future__ import annotations

import pytest

from aas_digital_twin.aas.oee import compute_oee


def test_perfect_run_gives_oee_of_one() -> None:
    result = compute_oee(
        planned_production_time_s=100.0,
        downtime_s=0.0,
        ideal_cycle_time_s=1.0,
        total_cycle_count=100,
        good_cycle_count=100,
    )
    assert result.availability == pytest.approx(1.0)
    assert result.performance == pytest.approx(1.0)
    assert result.quality == pytest.approx(1.0)
    assert result.oee == pytest.approx(1.0)


def test_downtime_reduces_availability_only() -> None:
    result = compute_oee(
        planned_production_time_s=100.0,
        downtime_s=20.0,
        ideal_cycle_time_s=1.0,
        total_cycle_count=80,
        good_cycle_count=80,
    )
    assert result.availability == pytest.approx(0.8)
    assert result.performance == pytest.approx(1.0)
    assert result.quality == pytest.approx(1.0)
    assert result.oee == pytest.approx(0.8)


def test_scrap_reduces_quality_only() -> None:
    result = compute_oee(
        planned_production_time_s=100.0,
        downtime_s=0.0,
        ideal_cycle_time_s=1.0,
        total_cycle_count=100,
        good_cycle_count=90,
    )
    assert result.quality == pytest.approx(0.9)
    assert result.oee == pytest.approx(0.9)


def test_slow_cycles_reduce_performance_only() -> None:
    result = compute_oee(
        planned_production_time_s=100.0,
        downtime_s=0.0,
        ideal_cycle_time_s=0.5,
        total_cycle_count=100,
        good_cycle_count=100,
    )
    assert result.performance == pytest.approx(0.5)
    assert result.oee == pytest.approx(0.5)


def test_zero_cycles_gives_zero_performance_and_quality() -> None:
    result = compute_oee(
        planned_production_time_s=100.0,
        downtime_s=0.0,
        ideal_cycle_time_s=1.0,
        total_cycle_count=0,
        good_cycle_count=0,
    )
    assert result.performance == 0.0
    assert result.quality == 0.0
    assert result.oee == 0.0


def test_full_downtime_gives_zero_availability_and_oee() -> None:
    result = compute_oee(
        planned_production_time_s=100.0,
        downtime_s=100.0,
        ideal_cycle_time_s=1.0,
        total_cycle_count=0,
        good_cycle_count=0,
    )
    assert result.availability == 0.0
    assert result.oee == 0.0


def test_performance_is_capped_at_one_even_if_faster_than_ideal() -> None:
    result = compute_oee(
        planned_production_time_s=100.0,
        downtime_s=0.0,
        ideal_cycle_time_s=2.0,
        total_cycle_count=100,
        good_cycle_count=100,
    )
    assert result.performance == pytest.approx(1.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "planned_production_time_s": 0.0,
            "downtime_s": 0.0,
            "ideal_cycle_time_s": 1.0,
            "total_cycle_count": 1,
            "good_cycle_count": 1,
        },
        {
            "planned_production_time_s": 100.0,
            "downtime_s": 150.0,
            "ideal_cycle_time_s": 1.0,
            "total_cycle_count": 1,
            "good_cycle_count": 1,
        },
        {
            "planned_production_time_s": 100.0,
            "downtime_s": 0.0,
            "ideal_cycle_time_s": 1.0,
            "total_cycle_count": 5,
            "good_cycle_count": 10,
        },
        {
            "planned_production_time_s": 100.0,
            "downtime_s": 0.0,
            "ideal_cycle_time_s": 1.0,
            "total_cycle_count": -1,
            "good_cycle_count": 0,
        },
    ],
)
def test_invalid_inputs_raise_value_error(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        compute_oee(**kwargs)
