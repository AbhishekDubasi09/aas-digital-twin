"""Tests for the OPC UA asset server: start it and exercise it via a real client."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncua import Client

from aas_digital_twin.opcua.server import AssetOpcUaServer

TEST_ENDPOINT = "opc.tcp://127.0.0.1:48401/aas-twin-test/"


@pytest.fixture
async def running_server() -> AsyncIterator[AssetOpcUaServer]:
    server = AssetOpcUaServer(endpoint=TEST_ENDPOINT)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


async def test_server_exposes_initial_zero_state(running_server: AssetOpcUaServer) -> None:
    state = await running_server.read_all()
    assert state["joint_positions"] == [0.0] * 7
    assert state["conveyor_speed"] == 0.0
    assert state["cycle_state"] == "IDLE"
    assert state["cycle_count"] == 0


async def test_update_joint_positions_is_readable_back(
    running_server: AssetOpcUaServer,
) -> None:
    pose = [0.5, -0.3, 1.1, -2.0, 0.1, 1.9, 0.8]
    await running_server.update_joint_positions(pose)
    state = await running_server.read_all()
    assert state["joint_positions"] == pytest.approx(pose)


async def test_update_cycle_state_and_counts(running_server: AssetOpcUaServer) -> None:
    await running_server.update_cycle_state("RUNNING")
    await running_server.update_counts(cycle_count=10, good_count=9)
    state = await running_server.read_all()
    assert state["cycle_state"] == "RUNNING"
    assert state["cycle_count"] == 10
    assert state["good_count"] == 9


async def test_real_opcua_client_can_connect_and_read(
    running_server: AssetOpcUaServer,
) -> None:
    """End-to-end check: a real asyncua Client over TCP, not just the server API."""
    await running_server.update_temperature(42.5)
    async with Client(url=TEST_ENDPOINT) as client:
        objects = client.nodes.objects
        children = await objects.get_children()
        asset_cell = None
        for c in children:
            if (await c.read_browse_name()).Name == "AssetCell":
                asset_cell = c
                break
        assert asset_cell is not None
        cell_children = await asset_cell.get_children()
        temp_node = None
        for c in cell_children:
            if (await c.read_browse_name()).Name == "Temperature":
                temp_node = c
                break
        assert temp_node is not None
        value = await temp_node.read_value()
    assert value == pytest.approx(42.5)
