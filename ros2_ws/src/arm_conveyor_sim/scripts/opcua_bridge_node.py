#!/usr/bin/env python3
"""Bridge ROS2 asset telemetry topics into the OPC UA server.

Runs an rclpy node in a background thread and an asyncio event loop
(hosting the asyncua server) on the main thread. ROS2 subscription
callbacks schedule address-space updates onto the asyncio loop via
run_coroutine_threadsafe, since asyncua is not thread-safe.
"""

from __future__ import annotations

import asyncio
import threading

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32, Int32, String

from aas_digital_twin.opcua.server import AssetOpcUaServer

ARM_JOINT_NAMES = [f"fr3_joint{i}" for i in range(1, 8)]


class OpcUaBridgeNode(Node):
    """Subscribes to /arm_conveyor telemetry and forwards it to OPC UA."""

    def __init__(self, opcua_server: AssetOpcUaServer, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__("opcua_bridge")
        self._opcua = opcua_server
        self._loop = loop
        self._cycle_count = 0
        self._good_count = 0

        self.create_subscription(
            JointState, "/arm_conveyor/joint_states", self._on_joint_states, 10
        )
        self.create_subscription(
            Float32, "/arm_conveyor/telemetry/conveyor_speed", self._on_conveyor_speed, 10
        )
        self.create_subscription(
            Float32, "/arm_conveyor/telemetry/temperature", self._on_temperature, 10
        )
        self.create_subscription(String, "/arm_conveyor/telemetry/state", self._on_state, 10)
        self.create_subscription(
            Int32, "/arm_conveyor/telemetry/cycle_count", self._on_cycle_count, 10
        )
        self.create_subscription(
            Int32, "/arm_conveyor/telemetry/good_count", self._on_good_count, 10
        )

    def _schedule(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _on_joint_states(self, msg: JointState) -> None:
        by_name = dict(zip(msg.name, msg.position, strict=False))
        positions = [by_name.get(name, 0.0) for name in ARM_JOINT_NAMES]
        if all(name in by_name for name in ARM_JOINT_NAMES):
            self._schedule(self._opcua.update_joint_positions(positions))

    def _on_conveyor_speed(self, msg: Float32) -> None:
        self._schedule(self._opcua.update_conveyor_speed(msg.data))

    def _on_temperature(self, msg: Float32) -> None:
        self._schedule(self._opcua.update_temperature(msg.data))

    def _on_state(self, msg: String) -> None:
        self._schedule(self._opcua.update_cycle_state(msg.data))

    def _on_cycle_count(self, msg: Int32) -> None:
        self._cycle_count = msg.data
        self._schedule(self._opcua.update_counts(self._cycle_count, self._good_count))

    def _on_good_count(self, msg: Int32) -> None:
        self._good_count = msg.data
        self._schedule(self._opcua.update_counts(self._cycle_count, self._good_count))


def _spin_ros(node: Node) -> None:
    rclpy.spin(node)


def main() -> None:
    """Start the OPC UA server and the ROS2 bridge node together."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    opcua_server = AssetOpcUaServer()

    rclpy.init()

    async def _run() -> None:
        await opcua_server.start()
        node = OpcUaBridgeNode(opcua_server, loop)
        ros_thread = threading.Thread(target=_spin_ros, args=(node,), daemon=True)
        ros_thread.start()
        try:
            while ros_thread.is_alive():
                await asyncio.sleep(0.5)
        finally:
            await opcua_server.stop()
            node.destroy_node()
            rclpy.shutdown()

    try:
        loop.run_until_complete(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
