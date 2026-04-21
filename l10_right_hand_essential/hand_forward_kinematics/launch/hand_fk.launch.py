from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='hand_forward_kinematics',
            executable='hand_fk_node',
            name='hand_fk_node',
            output='screen',
        ),
    ])
