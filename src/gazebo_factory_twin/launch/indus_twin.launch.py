from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([

        # --------------------------------------------------------
        # FACTORY DIGITAL TWIN
        # --------------------------------------------------------
        Node(
            package='gazebo_factory_twin',
            executable='factory_twin_node',
            name='factory_twin',
            output='screen',
        ),

        # --------------------------------------------------------
        # DATA LOGGERS
        # --------------------------------------------------------
        Node(
            package='gazebo_factory_twin',
            executable='telemetry_logger',
            name='telemetry_logger',
            output='screen',
        ),

        Node(
            package='gazebo_factory_twin',
            executable='production_logger',
            name='production_logger',
            output='screen',
        ),

        Node(
            package='gazebo_factory_twin',
            executable='grid_logger',
            name='grid_logger',
            output='screen',
        ),

        # --------------------------------------------------------
        # SCENARIO MANAGER
        # --------------------------------------------------------
        Node(
            package='gazebo_factory_twin',
            executable='scenario_manager',
            name='scenario_manager',
            output='screen',
        ),

        # --------------------------------------------------------
        # AI ENGINE
        # --------------------------------------------------------
        Node(
            package='gazebo_factory_twin',
            executable='ai_engine',
            name='ai_engine',
            output='screen',
        ),
    ])
