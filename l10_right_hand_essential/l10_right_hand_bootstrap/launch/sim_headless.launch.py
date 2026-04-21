"""
仿真无头模式: MuJoCo 仿真后端 + 网关 (无可视化/面板)
launch: ros2 launch l10_right_hand_bootstrap sim_headless.launch.py
"""
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import TimerAction


def generate_launch_description():
    return LaunchDescription([
        # 阶段 1: 后端
        Node(
            package='l10_right_hand_mujoco_sim',
            executable='l10_right_mujoco_node',
            name='l10_right_mujoco_node',
            parameters=[{'topic_hz': 30, 'is_touch': True}],
            output='screen',
        ),
        # 阶段 2: 网关
        TimerAction(
            period=3.0,
            actions=[
                Node(
                    package='l10_hand_gateway',
                    executable='l10_gateway_node',
                    name='l10_hand_gateway',
                    output='screen',
                ),
            ],
        ),
    ])
