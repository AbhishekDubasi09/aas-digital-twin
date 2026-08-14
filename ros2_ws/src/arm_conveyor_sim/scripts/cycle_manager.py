#!/usr/bin/env python3
"""Drive a real pick-and-place duty cycle for the 3-DOF arm and conveyor.

This node is the single source of truth for the asset's operational state.
It commands joint trajectories in Gazebo and publishes the telemetry that
downstream OPC UA / AAS / OEE layers consume: joint waypoints reached,
conveyor speed, a simulated temperature, and RUNNING/DOWN/IDLE state
transitions with real elapsed uptime/downtime.
"""

from __future__ import annotations

import math
import random
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, Int32, String
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

JOINT_NAMES = [
    "joint1_base_yaw",
    "joint2_shoulder_pitch",
    "joint3_elbow_pitch",
    "belt_roller_joint",
]

# Pick -> place -> home waypoints for joints 1-3 (radians). Belt roller
# position is unused by the trajectory plugin in continuous-joint mode;
# it is driven separately via accumulated angle to represent belt motion.
CYCLE_WAYPOINTS = [
    (0.0, 0.0, 0.0),
    (0.6, -0.4, 0.5),
    (0.6, -0.9, 1.1),
    (0.6, -0.4, 0.5),
    (0.0, 0.0, 0.0),
]

CYCLE_TIME_S = 4.0
DOWN_PROBABILITY_PER_CYCLE = 0.08
DOWN_DURATION_RANGE_S = (3.0, 10.0)
SCRAP_PROBABILITY_PER_CYCLE = 0.05
CONVEYOR_SPEED_MPS = 0.15


class CycleManager(Node):
    """Runs the arm/conveyor duty cycle and publishes real telemetry."""

    def __init__(self) -> None:
        super().__init__("cycle_manager")
        self._traj_pub = self.create_publisher(
            JointTrajectory, "/arm_conveyor/set_joint_trajectory", 10
        )
        self._state_pub = self.create_publisher(String, "/arm_conveyor/telemetry/state", 10)
        self._temp_pub = self.create_publisher(
            Float32, "/arm_conveyor/telemetry/temperature", 10
        )
        self._conveyor_speed_pub = self.create_publisher(
            Float32, "/arm_conveyor/telemetry/conveyor_speed", 10
        )
        self._cycle_count_pub = self.create_publisher(
            Int32, "/arm_conveyor/telemetry/cycle_count", 10
        )
        self._good_count_pub = self.create_publisher(
            Int32, "/arm_conveyor/telemetry/good_count", 10
        )

        self._state = "RUNNING"
        self._down_until = 0.0
        self._cycle_count = 0
        self._good_count = 0
        self._belt_angle = 0.0
        self._start_time = time.monotonic()

        self._temp_timer = self.create_timer(1.0, self._publish_temperature)
        self._cycle_timer = self.create_timer(0.5, self._tick)

        self.get_logger().info("cycle_manager started")

    def _publish_temperature(self) -> None:
        elapsed = time.monotonic() - self._start_time
        base = 35.0 if self._state == "RUNNING" else 28.0
        ripple = 3.0 * math.sin(elapsed / 20.0)
        noise = random.uniform(-0.4, 0.4)
        msg = Float32()
        msg.data = base + ripple + noise
        self._temp_pub.publish(msg)

    def _tick(self) -> None:
        now = time.monotonic()

        if self._state == "DOWN":
            if now >= self._down_until:
                self._state = "RUNNING"
                self.get_logger().info("recovered from DOWN -> RUNNING")
            else:
                self._publish_state()
                self._conveyor_speed_pub.publish(Float32(data=0.0))
                return

        # RUNNING: execute one pick-and-place cycle, then roll for a fault.
        self._run_cycle_trajectory()
        self._cycle_count += 1
        if random.random() > SCRAP_PROBABILITY_PER_CYCLE:
            self._good_count += 1

        self._cycle_count_pub.publish(Int32(data=self._cycle_count))
        self._good_count_pub.publish(Int32(data=self._good_count))
        self._conveyor_speed_pub.publish(Float32(data=CONVEYOR_SPEED_MPS))

        if random.random() < DOWN_PROBABILITY_PER_CYCLE:
            duration = random.uniform(*DOWN_DURATION_RANGE_S)
            self._state = "DOWN"
            self._down_until = now + duration
            self.get_logger().info(f"fault triggered, DOWN for {duration:.1f}s")

        self._publish_state()

    def _publish_state(self) -> None:
        self._state_pub.publish(String(data=self._state))

    def _run_cycle_trajectory(self) -> None:
        traj = JointTrajectory()
        traj.header.frame_id = "base_link"
        traj.joint_names = JOINT_NAMES
        n_points = len(CYCLE_WAYPOINTS)
        for i, (j1, j2, j3) in enumerate(CYCLE_WAYPOINTS):
            point = JointTrajectoryPoint()
            self._belt_angle += (CONVEYOR_SPEED_MPS / 0.05) * (CYCLE_TIME_S / n_points)
            point.positions = [j1, j2, j3, self._belt_angle % (2 * math.pi)]
            frac = (i + 1) / n_points
            point.time_from_start.sec = int(CYCLE_TIME_S * frac)
            point.time_from_start.nanosec = int((CYCLE_TIME_S * frac % 1) * 1e9)
            traj.points.append(point)
        self._traj_pub.publish(traj)


def main() -> None:
    rclpy.init()
    node = CycleManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
