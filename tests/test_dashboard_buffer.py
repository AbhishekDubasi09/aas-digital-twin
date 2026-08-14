"""Unit tests for the dashboard's MQTT telemetry buffer."""

from __future__ import annotations

import json

import pytest

from aas_digital_twin.dashboard.live_dashboard import TelemetryBuffer
from aas_digital_twin.gateway.bridge import (
    MQTT_TOPIC_CONDITION_MONITORING,
    MQTT_TOPIC_OPERATIONAL_STATE,
)


def test_ingest_operational_state_appends_joint_and_temperature_values() -> None:
    buffer = TelemetryBuffer()
    payload = json.dumps(
        {
            "Joint1PositionRad": 0.1,
            "Joint2PositionRad": 0.2,
            "Joint3PositionRad": 0.3,
            "TemperatureCelsius": 36.5,
            "ConveyorSpeedMPerS": 0.15,
            "CycleState": "RUNNING",
        }
    )
    buffer.ingest(MQTT_TOPIC_OPERATIONAL_STATE, payload, timestamp_s=1.0)

    assert list(buffer.timestamps_op) == [1.0]
    assert list(buffer.joint1) == [0.1]
    assert list(buffer.joint2) == [0.2]
    assert list(buffer.joint3) == [0.3]
    assert list(buffer.temperature) == [36.5]


def test_ingest_condition_monitoring_appends_oee_components() -> None:
    buffer = TelemetryBuffer()
    payload = json.dumps(
        {
            "availability": 0.9,
            "performance": 0.8,
            "quality": 0.95,
            "oee": 0.9 * 0.8 * 0.95,
            "total_cycle_count": 10,
            "good_cycle_count": 9,
        }
    )
    buffer.ingest(MQTT_TOPIC_CONDITION_MONITORING, payload, timestamp_s=2.0)

    assert list(buffer.timestamps_oee) == [2.0]
    assert list(buffer.availability) == [0.9]
    assert list(buffer.performance) == [0.8]
    assert list(buffer.quality) == [0.95]
    assert buffer.oee[0] == pytest.approx(0.684, abs=1e-3)


def test_ingest_ignores_unknown_topics() -> None:
    buffer = TelemetryBuffer()
    buffer.ingest("some/other/topic", "{}", timestamp_s=1.0)
    assert len(buffer.timestamps_op) == 0
    assert len(buffer.timestamps_oee) == 0


def test_buffer_is_bounded_at_max_points() -> None:
    buffer = TelemetryBuffer()
    for i in range(400):
        buffer.ingest(
            MQTT_TOPIC_OPERATIONAL_STATE,
            json.dumps({"Joint1PositionRad": float(i)}),
            timestamp_s=float(i),
        )
    assert len(buffer.timestamps_op) == 300
    assert buffer.joint1[-1] == 399.0
