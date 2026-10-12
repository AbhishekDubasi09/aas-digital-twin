#!/usr/bin/env python3
"""Run the pick-and-place duty cycle of the Franka Research 3 cell.

This node is the ground truth for the asset. It moves the FR3 through a
real pick, carry and place path (joint targets from asset/fr3_kinematics.py),
feeds parts along the conveyor, and publishes the telemetry that the OPC UA,
AAS and OEE layers consume.

Duty cycle: two states, RUNNING and DOWN. After every finished cycle the
node rolls a fault with DOWN_PROBABILITY_PER_CYCLE. A DOWN period lasts a
random time in DOWN_DURATION_RANGE_S, during which the arm holds still and
the belt stops. Each cycle is scrap with SCRAP_PROBABILITY_PER_CYCLE. Scrap
parts go to the red bin, good parts to the green bin.
"""

from __future__ import annotations

import math
import random
import time

import numpy as np
import rclpy
from gazebo_msgs.srv import SetEntityState
from rclpy.node import Node
from std_msgs.msg import Float32, Int32, String
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from aas_digital_twin.asset import fr3_kinematics as kin

DOWN_PROBABILITY_PER_CYCLE = 0.08
DOWN_DURATION_RANGE_S = (3.0, 10.0)
SCRAP_PROBABILITY_PER_CYCLE = 0.05
CONVEYOR_SPEED_MPS = 0.15

# Seconds per leg: ready->hover, descend, grasp, lift, carry, descend,
# release, retreat, home. The sum is the real cycle time of the cell.
SEGMENT_DURATIONS_S = [0.7, 0.4, 0.25, 0.4, 0.9, 0.4, 0.25, 0.4, 0.7]

TICK_S = 1.0 / 30.0
PART_COUNT = 6
BELT_X = kin.PICK_XY[0]
BELT_START_Y = -0.75
PART_GAP_M = 0.09
PICK_Y = kin.PICK_XY[1]
BIN_DWELL_S = 1.2
ARM_NS = "/arm_conveyor"
PART_REST_Z = kin.BELT_TOP_Z + kin.PART_SIZE_M / 2


def _smooth(u: float) -> float:
    return u * u * (3.0 - 2.0 * u)


class CycleManager(Node):
    """Runs the FR3 duty cycle and publishes real telemetry."""

    def __init__(self) -> None:
        super().__init__("cycle_manager")
        self.declare_parameter("down_probability", DOWN_PROBABILITY_PER_CYCLE)
        self._down_p = float(self.get_parameter("down_probability").value)

        self._traj_pub = self.create_publisher(
            JointTrajectory, f"{ARM_NS}/set_joint_trajectory", 10
        )
        self._state_pub = self.create_publisher(String, f"{ARM_NS}/telemetry/state", 10)
        self._temp_pub = self.create_publisher(Float32, f"{ARM_NS}/telemetry/temperature", 10)
        self._speed_pub = self.create_publisher(Float32, f"{ARM_NS}/telemetry/conveyor_speed", 10)
        self._cycle_pub = self.create_publisher(Int32, f"{ARM_NS}/telemetry/cycle_count", 10)
        self._good_pub = self.create_publisher(Int32, f"{ARM_NS}/telemetry/good_count", 10)
        self._set_state = self.create_client(SetEntityState, "/gz/set_entity_state")

        self._state = "RUNNING"
        self._down_until = 0.0
        self._cycle_count = 0
        self._good_count = 0
        self._start = time.monotonic()

        # Part bookkeeping. y is the position along the belt.
        self._part_y = [BELT_START_Y - 0.12 * i for i in range(PART_COUNT)]
        self._part_mode = ["belt"] * PART_COUNT  # belt | held | binned
        self._part_timer = [0.0] * PART_COUNT
        self._held: int | None = None
        self._last_pose: dict[int, tuple[float, float, float]] = {}

        # Current cycle plan.
        self._plan: list[tuple[str, np.ndarray, float]] | None = None
        self._seg = 0
        self._seg_t = 0.0
        self._scrap = False
        self._q = kin.READY_POSE.copy()
        self._finger = kin.FINGER_OPEN_M

        self.create_timer(1.0, self._publish_temperature)
        self.create_timer(TICK_S, self._tick)
        self.get_logger().info(
            f"cycle_manager started, fault probability per cycle {self._down_p:.2f}"
        )

    # ---- telemetry ------------------------------------------------------
    def _publish_temperature(self) -> None:
        elapsed = time.monotonic() - self._start
        base = 35.0 if self._state == "RUNNING" else 28.0
        value = base + 3.0 * math.sin(elapsed / 20.0) + random.uniform(-0.4, 0.4)
        self._temp_pub.publish(Float32(data=value))

    # ---- Gazebo helpers -------------------------------------------------
    def _place_part(self, idx: int, x: float, y: float, z: float) -> None:
        pose = (round(x, 4), round(y, 4), round(z, 4))
        if self._last_pose.get(idx) == pose or not self._set_state.service_is_ready():
            return
        self._last_pose[idx] = pose
        req = SetEntityState.Request()
        req.state.name = f"part_{idx}"
        req.state.pose.position.x, req.state.pose.position.y, req.state.pose.position.z = pose
        req.state.pose.orientation.w = 1.0
        req.state.reference_frame = "world"
        self._set_state.call_async(req)

    def _send_joints(self) -> None:
        traj = JointTrajectory()
        traj.header.frame_id = "base"
        traj.joint_names = kin.JOINT_NAMES + kin.FINGER_JOINT_NAMES
        point = JointTrajectoryPoint()
        point.positions = [*map(float, self._q), self._finger, self._finger]
        point.time_from_start.nanosec = int(0.06e9)
        traj.points.append(point)
        self._traj_pub.publish(traj)

    # ---- belt -----------------------------------------------------------
    def _advance_belt(self, dt: float) -> bool:
        """Move belt parts toward the stopper. Return True if any part moved."""
        moving = False
        belt = sorted(
            (i for i in range(PART_COUNT) if self._part_mode[i] == "belt"),
            key=lambda i: -self._part_y[i],
        )
        limit = PICK_Y
        for i in belt:
            new_y = min(self._part_y[i] + CONVEYOR_SPEED_MPS * dt, limit)
            if new_y > self._part_y[i] + 1e-6:
                moving = True
            self._part_y[i] = new_y
            limit = new_y - PART_GAP_M
            self._place_part(i, BELT_X, new_y, PART_REST_Z)
        return moving

    def _front_part(self) -> int | None:
        belt = [i for i in range(PART_COUNT) if self._part_mode[i] == "belt"]
        if not belt:
            return None
        front = max(belt, key=lambda i: self._part_y[i])
        return front if abs(self._part_y[front] - PICK_Y) < 0.003 else None

    def _recycle_parts(self, dt: float) -> None:
        for i in range(PART_COUNT):
            if self._part_mode[i] != "binned":
                continue
            self._part_timer[i] -= dt
            if self._part_timer[i] > 0:
                continue
            on_belt = [self._part_y[j] for j in range(PART_COUNT) if self._part_mode[j] == "belt"]
            if not on_belt or min(on_belt) > BELT_START_Y + PART_GAP_M:
                self._part_mode[i] = "belt"
                self._part_y[i] = BELT_START_Y
                self._place_part(i, BELT_X, BELT_START_Y, PART_REST_Z)

    # ---- main loop --------------------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()
        self._recycle_parts(TICK_S)

        if self._state == "DOWN":
            self._state_pub.publish(String(data="DOWN"))
            self._speed_pub.publish(Float32(data=0.0))
            if now >= self._down_until:
                self._state = "RUNNING"
                self.get_logger().info("recovered, DOWN -> RUNNING")
            self._send_joints()
            return

        moving = self._advance_belt(TICK_S)
        self._speed_pub.publish(Float32(data=CONVEYOR_SPEED_MPS if moving else 0.0))
        self._state_pub.publish(String(data="RUNNING"))

        if self._plan is None:
            self._send_joints()
            front = self._front_part()
            if front is None:
                return
            self._scrap = random.random() < SCRAP_PROBABILITY_PER_CYCLE
            self._plan = kin.pick_and_place_waypoints(self._scrap)
            self._seg, self._seg_t = 0, 0.0
            self._held = front
            return

        self._advance_arm(TICK_S)

    def _advance_arm(self, dt: float) -> None:
        assert self._plan is not None
        self._seg_t += dt
        u = min(self._seg_t / SEGMENT_DURATIONS_S[self._seg], 1.0)
        _, q0, f0 = self._plan[self._seg]
        label1, q1, f1 = self._plan[self._seg + 1]
        s = _smooth(u)
        self._q = q0 + (q1 - q0) * s
        self._finger = f0 + (f1 - f0) * s
        self._send_joints()

        if self._held is not None and self._part_mode[self._held] == "held":
            tcp = kin.tcp_position(self._q)
            self._place_part(self._held, float(tcp[0]), float(tcp[1]), float(tcp[2]))

        if u < 1.0:
            return
        self._seg += 1
        self._seg_t = 0.0
        if label1 == "grasp" and self._held is not None:
            self._part_mode[self._held] = "held"
        if label1 == "release" and self._held is not None:
            drop = kin.REJECT_BIN_XY if self._scrap else kin.GOOD_BIN_XY
            self._part_mode[self._held] = "binned"
            self._part_timer[self._held] = BIN_DWELL_S
            self._place_part(self._held, drop[0], drop[1], 0.05)
            self._held = None
        if self._seg >= len(self._plan) - 1:
            self._finish_cycle()

    def _finish_cycle(self) -> None:
        self._plan = None
        self._cycle_count += 1
        if not self._scrap:
            self._good_count += 1
        self._cycle_pub.publish(Int32(data=self._cycle_count))
        self._good_pub.publish(Int32(data=self._good_count))
        if random.random() < self._down_p:
            duration = random.uniform(*DOWN_DURATION_RANGE_S)
            self._state = "DOWN"
            self._down_until = time.monotonic() + duration
            self.get_logger().info(f"fault, DOWN for {duration:.1f}s")


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
