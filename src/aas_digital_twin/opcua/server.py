"""OPC UA server exposing asset telemetry (IEC 62541).

Implements the shop-floor protocol layer: joint positions, conveyor speed,
temperature, and duty-cycle state are exposed as OPC UA variables under a
single AssetCell object. The server is independent of any particular data
source (ROS2, a mock feed, etc.) so it can be driven directly in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from asyncua import Server, ua
from asyncua.common.node import Node

NAMESPACE_URI = "http://aas-digital-twin/opcua/"
JOINT_COUNT = 7  # Franka Research 3


@dataclass
class AssetCellNodes:
    """Handles to the OPC UA variable nodes for the asset cell."""

    joint_positions: list[Node] = field(default_factory=list)
    conveyor_speed: Node | None = None
    temperature: Node | None = None
    cycle_state: Node | None = None
    cycle_count: Node | None = None
    good_count: Node | None = None
    speed_scale: Node | None = None


class AssetOpcUaServer:
    """OPC UA server for the simulated Franka Research 3 arm + conveyor cell.

    Usage:
        server = AssetOpcUaServer(endpoint="opc.tcp://0.0.0.0:4840/aas-twin/")
        await server.start()
        await server.update_joint_positions([0.0] * JOINT_COUNT)
        ...
        await server.stop()
    """

    def __init__(self, endpoint: str = "opc.tcp://0.0.0.0:4840/aas-twin/") -> None:
        """Create a server bound to the given OPC UA endpoint URL."""
        self._endpoint = endpoint
        self._server = Server()
        self._nodes = AssetCellNodes()
        self._started = False

    async def start(self) -> None:
        """Initialize the address space and start listening for clients."""
        await self._server.init()
        self._server.set_endpoint(self._endpoint)
        idx = await self._server.register_namespace(NAMESPACE_URI)

        objects = self._server.nodes.objects
        asset_cell = await objects.add_object(idx, "AssetCell")

        for i in range(1, JOINT_COUNT + 1):
            node = await asset_cell.add_variable(idx, f"Joint{i}Position", 0.0)
            await node.set_writable()
            self._nodes.joint_positions.append(node)

        self._nodes.conveyor_speed = await asset_cell.add_variable(idx, "ConveyorSpeed", 0.0)
        self._nodes.temperature = await asset_cell.add_variable(idx, "Temperature", 0.0)
        self._nodes.cycle_state = await asset_cell.add_variable(idx, "CycleState", "IDLE")
        self._nodes.cycle_count = await asset_cell.add_variable(
            idx, "CycleCount", ua.Variant(0, ua.VariantType.Int32)
        )
        self._nodes.good_count = await asset_cell.add_variable(
            idx, "GoodCount", ua.Variant(0, ua.VariantType.Int32)
        )
        # Written by the gateway (derating command), read by the asset side.
        self._nodes.speed_scale = await asset_cell.add_variable(idx, "SpeedScale", 1.0)
        for node in (
            self._nodes.speed_scale,
            self._nodes.conveyor_speed,
            self._nodes.temperature,
            self._nodes.cycle_state,
            self._nodes.cycle_count,
            self._nodes.good_count,
        ):
            await node.set_writable()

        await self._server.start()
        self._started = True

    async def stop(self) -> None:
        """Stop the server and release the listening socket."""
        if self._started:
            await self._server.stop()
            self._started = False

    async def update_joint_positions(self, positions: list[float]) -> None:
        """Write the current joint positions (radians) to the address space."""
        for node, value in zip(self._nodes.joint_positions, positions, strict=False):
            await node.write_value(float(value))

    async def update_conveyor_speed(self, speed_mps: float) -> None:
        """Write the current conveyor belt speed in meters per second."""
        assert self._nodes.conveyor_speed is not None
        await self._nodes.conveyor_speed.write_value(float(speed_mps))

    async def update_temperature(self, temperature_c: float) -> None:
        """Write the current simulated temperature reading in Celsius."""
        assert self._nodes.temperature is not None
        await self._nodes.temperature.write_value(float(temperature_c))

    async def update_cycle_state(self, state: str) -> None:
        """Write the current duty-cycle state (RUNNING, DOWN, or IDLE)."""
        assert self._nodes.cycle_state is not None
        await self._nodes.cycle_state.write_value(state)

    async def read_speed_scale(self) -> float:
        """Read the speed scale command (1.0 = full speed)."""
        assert self._nodes.speed_scale is not None
        return float(await self._nodes.speed_scale.read_value())

    async def update_counts(self, cycle_count: int, good_count: int) -> None:
        """Write the cumulative attempted and good production counts."""
        assert self._nodes.cycle_count is not None
        assert self._nodes.good_count is not None
        await self._nodes.cycle_count.write_value(ua.Variant(cycle_count, ua.VariantType.Int32))
        await self._nodes.good_count.write_value(ua.Variant(good_count, ua.VariantType.Int32))

    async def read_all(self) -> dict[str, object]:
        """Read back the full current state, mainly for tests/diagnostics."""
        assert self._nodes.conveyor_speed is not None
        assert self._nodes.temperature is not None
        assert self._nodes.cycle_state is not None
        assert self._nodes.cycle_count is not None
        assert self._nodes.good_count is not None
        return {
            "joint_positions": [await n.read_value() for n in self._nodes.joint_positions],
            "conveyor_speed": await self._nodes.conveyor_speed.read_value(),
            "temperature": await self._nodes.temperature.read_value(),
            "cycle_state": await self._nodes.cycle_state.read_value(),
            "cycle_count": await self._nodes.cycle_count.read_value(),
            "good_count": await self._nodes.good_count.read_value(),
            "speed_scale": await self.read_speed_scale(),
        }
