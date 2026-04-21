"""
仿真模式: MuJoCo 仿真后端 + 网关 + 面板 + 可视化
launch: ros2 launch l10_right_hand_bootstrap sim.launch.py
启动顺序: 后端(0s) → 网关(3s) → 可视化+面板(5s)
"""
import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    viz_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('l10_right_hand_viz'),
            'launch', 'hand_viz.launch.py',
        )),
    )

    return LaunchDescription([
        # 阶段 1: 后端
        Node(
            package='l10_right_hand_mujoco_sim',
            executable='l10_right_mujoco_node',
            name='l10_right_mujoco_node',
            parameters=[{'topic_hz': 30, 'is_touch': True}],
            output='screen',
        ),
        # 阶段 2: 网关 (等后端初始化)
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
        # 阶段 3: 可视化 + 面板 (等网关就绪)
        TimerAction(
            period=5.0,
            actions=[
                viz_launch,
                Node(
                    package='l10_hand_control_panel',
                    executable='control_panel',
                    name='control_panel',
                    output='screen',
                ),
            ],
        ),
    ])
