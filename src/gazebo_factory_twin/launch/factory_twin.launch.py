from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='gazebo_factory_twin',
            executable='factory_twin_node',
            name='factory_twin',
            output='screen',
        ),
    ])
