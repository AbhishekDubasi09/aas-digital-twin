"""Launch the arm+conveyor Gazebo simulation and cycle manager node."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("arm_conveyor_sim")
    gazebo_ros_share = get_package_share_directory("gazebo_ros")
    world_path = os.path.join(pkg_share, "worlds", "factory_cell.world")
    urdf_path = os.path.join(pkg_share, "urdf", "arm_conveyor.urdf")

    with open(urdf_path) as f:
        robot_description = f.read()

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(gazebo_ros_share, "launch", "gazebo.launch.py")
        ),
        launch_arguments={"world": world_path}.items(),
    )

    spawn_entity = Node(
        package="gazebo_ros",
        executable="spawn_entity.py",
        arguments=[
            "-topic",
            "robot_description",
            "-entity",
            "arm_conveyor",
            "-spawn_service_timeout",
            "60.0",
        ],
        output="screen",
    )

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[{"robot_description": robot_description}],
    )

    cycle_manager = Node(
        package="arm_conveyor_sim",
        executable="cycle_manager.py",
        output="screen",
    )

    return LaunchDescription(
        [gazebo, robot_state_publisher, spawn_entity, cycle_manager]
    )
