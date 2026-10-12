"""Franka Research 3 (FR3) kinematics and the pick-and-place path of the cell.

Pure numpy, no ROS. Both the Gazebo cycle_manager node and the in-process
demo import this module, so the arm moves along the same joint path in both.

Forward kinematics uses the published FR3 Denavit-Hartenberg parameters
(Craig convention). Inverse kinematics is a damped least squares solver on
tool position plus a "tool points down" constraint, seeded from the ready
pose. The joint path is solved once per target and then interpolated.
"""

from __future__ import annotations

import math

import numpy as np

JOINT_NAMES = [f"fr3_joint{i}" for i in range(1, 8)]
FINGER_JOINT_NAMES = ["fr3_finger_joint1", "fr3_finger_joint2"]

JOINT_LOWER = np.array([-2.7437, -1.7837, -2.9007, -3.0718, -2.8065, 0.5445, -3.0159])
JOINT_UPPER = np.array([2.7437, 1.7837, 2.9007, -0.1518, 2.8065, 4.5169, 3.0159])

READY_POSE = np.array([0.0, -math.pi / 4, 0.0, -3 * math.pi / 4, 0.0, math.pi / 2, math.pi / 4])

# (a, d, alpha) per joint, modified DH. Then flange offset and hand TCP offset.
_DH = [
    (0.0, 0.333, 0.0),
    (0.0, 0.0, -math.pi / 2),
    (0.0, 0.316, math.pi / 2),
    (0.0825, 0.0, math.pi / 2),
    (-0.0825, 0.384, -math.pi / 2),
    (0.0, 0.0, math.pi / 2),
    (0.088, 0.0, math.pi / 2),
]
_FLANGE_D = 0.107
TCP_OFFSET_M = 0.1034

FINGER_OPEN_M = 0.04
FINGER_HOLD_M = 0.02


def _craig(a: float, d: float, alpha: float, theta: float) -> np.ndarray:
    ca, sa = math.cos(alpha), math.sin(alpha)
    ct, st = math.cos(theta), math.sin(theta)
    return np.array(
        [
            [ct, -st, 0.0, a],
            [st * ca, ct * ca, -sa, -d * sa],
            [st * sa, ct * sa, ca, d * ca],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )


def forward_kinematics(q: np.ndarray, with_tcp: bool = True) -> np.ndarray:
    """Return the 4x4 pose of the flange (or hand TCP) in the arm base frame."""
    t = np.eye(4)
    for (a, d, alpha), theta in zip(_DH, q, strict=True):
        t = t @ _craig(a, d, alpha, float(theta))
    t = t @ _craig(0.0, _FLANGE_D + (TCP_OFFSET_M if with_tcp else 0.0), 0.0, 0.0)
    return t


def tcp_position(q: np.ndarray) -> np.ndarray:
    """Hand TCP position in the arm base frame, metres."""
    return forward_kinematics(q)[:3, 3]


def solve_ik(
    target_xyz: tuple[float, float, float],
    seed: np.ndarray | None = None,
    iterations: int = 200,
) -> np.ndarray:
    """Find joints that put the TCP at target_xyz with the tool pointing down."""
    q = (READY_POSE if seed is None else seed).astype(float).copy()
    target = np.asarray(target_xyz, dtype=float)
    down = np.array([0.0, 0.0, -1.0])
    damping = 0.05
    for _ in range(iterations):
        t = forward_kinematics(q)
        err_pos = target - t[:3, 3]
        err_rot = np.cross(t[:3, 2], down)
        err = np.concatenate([err_pos, -0.5 * err_rot])
        if np.linalg.norm(err_pos) < 1e-4 and np.linalg.norm(err_rot) < 1e-3:
            break
        jac = np.zeros((6, 7))
        for i in range(7):
            dq = q.copy()
            dq[i] += 1e-6
            td = forward_kinematics(dq)
            jac[:3, i] = (td[:3, 3] - t[:3, 3]) / 1e-6
            jac[3:, i] = 0.5 * (np.cross(td[:3, 2], down) - err_rot) / 1e-6
        jjt = jac @ jac.T + (damping**2) * np.eye(6)
        q = q + jac.T @ np.linalg.solve(jjt, err)
        q = np.clip(q, JOINT_LOWER, JOINT_UPPER)
    return q


# Cell layout in the arm base frame, metres. The same numbers are used in
# worlds/factory_cell.world so the parts and bins line up with the arm.
PICK_XY = (0.50, 0.0)
GOOD_BIN_XY = (0.0, 0.50)
REJECT_BIN_XY = (0.0, -0.50)
BELT_TOP_Z = 0.12
PART_SIZE_M = 0.04
GRASP_Z = BELT_TOP_Z + PART_SIZE_M / 2
HOVER_Z = 0.32
BIN_DROP_Z = 0.22


def pick_and_place_waypoints(scrap: bool) -> list[tuple[str, np.ndarray, float]]:
    """Return (label, joints, finger_opening) waypoints for one cycle.

    Starts and ends at the ready pose. The label marks where the part is
    grasped ("grasp") and released ("release") so the caller can attach the
    part to the TCP between those two waypoints.
    """
    drop_xy = REJECT_BIN_XY if scrap else GOOD_BIN_XY
    stages = [
        ("hover_pick", (*PICK_XY, HOVER_Z), FINGER_OPEN_M),
        ("descend_pick", (*PICK_XY, GRASP_Z), FINGER_OPEN_M),
        ("grasp", (*PICK_XY, GRASP_Z), FINGER_HOLD_M),
        ("lift", (*PICK_XY, HOVER_Z), FINGER_HOLD_M),
        ("hover_drop", (*drop_xy, HOVER_Z), FINGER_HOLD_M),
        ("descend_drop", (*drop_xy, BIN_DROP_Z), FINGER_HOLD_M),
        ("release", (*drop_xy, BIN_DROP_Z), FINGER_OPEN_M),
        ("retreat", (*drop_xy, HOVER_Z), FINGER_OPEN_M),
    ]
    out: list[tuple[str, np.ndarray, float]] = [("ready", READY_POSE.copy(), FINGER_OPEN_M)]
    seed = READY_POSE
    for label, xyz, finger in stages:
        q = solve_ik(xyz, seed=seed)
        out.append((label, q, finger))
        seed = q
    out.append(("home", READY_POSE.copy(), FINGER_OPEN_M))
    return out
