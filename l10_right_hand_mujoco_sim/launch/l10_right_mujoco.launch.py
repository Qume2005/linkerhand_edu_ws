from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='l10_right_hand_mujoco_sim',
            executable='l10_right_mujoco_node',
            name='l10_right_mujoco_node',
            output='screen',
            parameters=[{
                'topic_hz': 30,
                'is_touch': True,
            }],
        ),
    ])
