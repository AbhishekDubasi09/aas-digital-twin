"""Tests for the FR3 kinematics and the pick-and-place path."""

from __future__ import annotations

import numpy as np
import pytest

from aas_digital_twin.asset import fr3_kinematics as kin


def test_ready_pose_tcp_is_in_front_of_the_base_pointing_down() -> None:
    t = kin.forward_kinematics(kin.READY_POSE)
    assert t[0, 3] == pytest.approx(0.307, abs=0.01)
    assert t[1, 3] == pytest.approx(0.0, abs=1e-6)
    assert t[:3, 2] == pytest.approx([0.0, 0.0, -1.0], abs=1e-6)


def test_ik_reaches_target_with_tool_pointing_down() -> None:
    q = kin.solve_ik((0.45, 0.1, 0.25))
    t = kin.forward_kinematics(q)
    assert t[:3, 3] == pytest.approx([0.45, 0.1, 0.25], abs=1e-3)
    assert t[:3, 2] == pytest.approx([0.0, 0.0, -1.0], abs=0.02)


@pytest.mark.parametrize("scrap", [False, True])
def test_waypoints_respect_joint_limits_and_reach_the_bins(scrap: bool) -> None:
    plan = kin.pick_and_place_waypoints(scrap)
    labels = [label for label, _, _ in plan]
    assert labels[0] == "ready"
    assert labels[-1] == "home"
    assert "grasp" in labels
    assert "release" in labels
    for _, q, _ in plan:
        assert np.all(q >= kin.JOINT_LOWER - 1e-6)
        assert np.all(q <= kin.JOINT_UPPER + 1e-6)
    release = next(q for label, q, _ in plan if label == "release")
    bin_xy = kin.REJECT_BIN_XY if scrap else kin.GOOD_BIN_XY
    assert kin.tcp_position(release)[:2] == pytest.approx(bin_xy, abs=2e-3)
