"""Launch the Franka Research 3 pick-and-place cell in Gazebo Classic.

The FR3 description comes from the franka_description package (xacro). A
world link, a joint-state publisher and a joint-trajectory plugin are added
to the generated URDF before it is given to Gazebo.
"""

import os

import xacro
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

ARM_JOINTS = [f"fr3_joint{i}" for i in range(1, 8)]
FINGER_JOINTS = ["fr3_finger_joint1", "fr3_finger_joint2"]
ARM_LINKS = [f"fr3_link{i}" for i in range(0, 8)] + [
    "fr3_hand",
    "fr3_leftfinger",
    "fr3_rightfinger",
]


def _robot_description() -> str:
    franka_share = get_package_share_directory("franka_description")
    xacro_file = os.path.join(franka_share, "robots", "fr3", "fr3.urdf.xacro")
    urdf = xacro.process_file(
        xacro_file, mappings={"hand": "true", "ee_id": "franka_hand"}
    ).toxml()

    joint_names = "".join(f"<joint_name>{n}</joint_name>" for n in ARM_JOINTS + FINGER_JOINTS)
    no_gravity = "".join(
        f'<gazebo reference="{n}"><gravity>false</gravity></gazebo>' for n in ARM_LINKS
    )
    extra = f"""
  <link name="world"/>
  <joint name="world_to_base" type="fixed">
    <parent link="world"/><child link="base"/>
    <origin xyz="0 0 0.0" rpy="0 0 0"/>
  </joint>
  {no_gravity}
  <gazebo>
    <plugin name="fr3_joint_states" filename="libgazebo_ros_joint_state_publisher.so">
      <ros><namespace>/arm_conveyor</namespace></ros>
      <update_rate>30</update_rate>
      {joint_names}
    </plugin>
    <plugin name="fr3_joint_trajectory" filename="libgazebo_ros_joint_pose_trajectory.so">
      <ros><namespace>/arm_conveyor</namespace></ros>
      <update_rate>30</update_rate>
    </plugin>
  </gazebo>
"""
    return urdf.replace("</robot>", extra + "</robot>")


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("arm_conveyor_sim")
    gazebo_ros_share = get_package_share_directory("gazebo_ros")
    world_path = os.path.join(pkg_share, "worlds", "factory_cell.world")
    robot_description = _robot_description()

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(gazebo_ros_share, "launch", "gazebo.launch.py")),
        launch_arguments={"world": world_path}.items(),
    )

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[{"robot_description": robot_description}],
    )

    spawn_entity = Node(
        package="gazebo_ros",
        executable="spawn_entity.py",
        arguments=[
            "-topic", "robot_description",
            "-entity", "fr3",
            "-spawn_service_timeout", "60.0",
        ],
        output="screen",
    )

    cycle_manager = Node(
        package="arm_conveyor_sim",
        executable="cycle_manager.py",
        output="screen",
    )

    return LaunchDescription(
        [
            # Lets Gazebo resolve package://franka_description/... mesh URIs.
            SetEnvironmentVariable(
                "GAZEBO_MODEL_PATH",
                "/opt/ros/humble/share:" + os.environ.get("GAZEBO_MODEL_PATH", ""),
            ),
            gazebo,
            robot_state_publisher,
            spawn_entity,
            cycle_manager,
        ]
    )
