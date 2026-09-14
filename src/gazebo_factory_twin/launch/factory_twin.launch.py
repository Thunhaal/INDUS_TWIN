from launch import LaunchDescription
from launch.actions import ExecuteProcess, SetEnvironmentVariable
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    share = get_package_share_directory("gazebo_factory_twin")
    world = os.path.join(share, "worlds", "factory_floor.sdf")
    resource_path = os.path.join(share, "worlds")
    old_path = os.environ.get("GZ_SIM_RESOURCE_PATH", "")
    return LaunchDescription([
        SetEnvironmentVariable("GZ_SIM_RESOURCE_PATH", resource_path + (":" + old_path if old_path else "")),
        ExecuteProcess(cmd=["gz", "sim", "-r", world], output="screen"),
        Node(package="gazebo_factory_twin", executable="factory_twin_node", output="screen"),
    ])
