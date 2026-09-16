from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():

    package_share = get_package_share_directory(
        "gazebo_factory_twin"
    )

    factory_launch = os.path.join(
        package_share,
        "launch",
        "factory_twin.launch.py"
    )

    return LaunchDescription([

        # ====================================================
        # FACTORY TWIN / GAZEBO
        # ====================================================

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                factory_launch
            )
        ),

        # ====================================================
        # TELEMETRY LOGGER
        # ====================================================

        Node(
            package="gazebo_factory_twin",
            executable="telemetry_logger",
            name="telemetry_logger",
            output="screen"
        ),

        # ====================================================
        # PRODUCTION LOGGER
        # ====================================================

        Node(
            package="gazebo_factory_twin",
            executable="production_logger",
            name="production_logger",
            output="screen"
        ),

        # ====================================================
        # SCENARIO MANAGER
        # ====================================================

        Node(
            package="gazebo_factory_twin",
            executable="scenario_manager",
            name="scenario_manager",
            output="screen"
        ),

        # ====================================================
        # GRID LOGGER
        # ====================================================

        Node(
            package="gazebo_factory_twin",
            executable="grid_logger",
            name="grid_logger",
            output="screen"
        ),

        # ====================================================
        # LIVE AI ENGINE
        # ====================================================

        Node(
            package="gazebo_factory_twin",
            executable="ai_engine",
            name="ai_engine",
            output="screen"
        ),
    ])