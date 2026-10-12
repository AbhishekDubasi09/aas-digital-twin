"""Integration test: gateway running end-to-end against a mock OPC UA server."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from aas_digital_twin.aas.api import build_object_store
from aas_digital_twin.gateway.bridge import Gateway
from aas_digital_twin.opcua.server import AssetOpcUaServer

TEST_ENDPOINT = "opc.tcp://127.0.0.1:48402/aas-twin-gateway-test/"


@pytest.fixture
async def mock_asset_server() -> AsyncIterator[AssetOpcUaServer]:
    server = AssetOpcUaServer(endpoint=TEST_ENDPOINT)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


async def test_gateway_propagates_opcua_values_into_aas_and_mqtt(
    mock_asset_server: AssetOpcUaServer,
) -> None:
    await mock_asset_server.update_joint_positions([0.2, -0.4, 0.9, -2.1, 0.0, 1.8, 0.7])
    await mock_asset_server.update_conveyor_speed(0.15)
    await mock_asset_server.update_temperature(38.2)
    await mock_asset_server.update_cycle_state("RUNNING")
    await mock_asset_server.update_counts(cycle_count=20, good_count=19)

    store = build_object_store()
    published: list[tuple[str, str]] = []

    def fake_publish(topic: str, payload: str) -> None:
        published.append((topic, payload))

    gateway = Gateway(opcua_endpoint=TEST_ENDPOINT, object_store=store, publish=fake_publish)
    await gateway.run(poll_interval_s=0.0, max_iterations=1)

    operational_state = next(sm for sm in store if sm.id_short == "OperationalState")
    assert operational_state.get_referable("Joint1PositionRad").value == pytest.approx(0.2)
    assert operational_state.get_referable("Joint2PositionRad").value == pytest.approx(-0.4)
    assert operational_state.get_referable("Joint3PositionRad").value == pytest.approx(0.9)
    assert operational_state.get_referable("Joint7PositionRad").value == pytest.approx(0.7)
    assert operational_state.get_referable("ConveyorSpeedMPerS").value == pytest.approx(0.15)
    assert operational_state.get_referable("TemperatureCelsius").value == pytest.approx(38.2)
    assert operational_state.get_referable("CycleState").value == "RUNNING"

    condition_monitoring = next(sm for sm in store if sm.id_short == "ConditionMonitoring")
    assert condition_monitoring.get_referable("TotalCycleCount").value == 20
    assert condition_monitoring.get_referable("GoodCycleCount").value == 19
    assert condition_monitoring.get_referable("Quality").value == pytest.approx(19 / 20)

    assert len(published) == 2
    topics = {t for t, _ in published}
    assert topics == {
        "aas-digital-twin/operational_state",
        "aas-digital-twin/condition_monitoring",
    }
    op_state_payload = json.loads(next(p for t, p in published if "operational_state" in t))
    assert op_state_payload["Joint1PositionRad"] == pytest.approx(0.2)


async def test_gateway_tracks_real_downtime_across_polls(
    mock_asset_server: AssetOpcUaServer,
) -> None:
    """Downtime accumulated across polls should reduce availability, not be fabricated."""
    store = build_object_store()
    published: list[tuple[str, str]] = []
    gateway = Gateway(
        opcua_endpoint=TEST_ENDPOINT,
        object_store=store,
        publish=lambda t, p: published.append((t, p)),
    )

    await mock_asset_server.update_cycle_state("DOWN")
    await mock_asset_server.update_counts(cycle_count=0, good_count=0)

    from asyncua import Client

    async with Client(url=TEST_ENDPOINT) as client:
        await gateway.poll_once(client)
        gateway._last_poll_time -= 5.0  # simulate 5s elapsed since previous poll
        await gateway.poll_once(client)

    condition_monitoring = next(sm for sm in store if sm.id_short == "ConditionMonitoring")
    assert gateway._downtime_accum_s >= 5.0
    assert condition_monitoring.get_referable("Availability").value < 1.0
