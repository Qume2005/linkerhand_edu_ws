"""
LLM 手势控制 - 真机模式: CAN 驱动 + 网关 + 可视化 + LLM 控制面板
launch: ros2 launch l10_right_hand_llm llm_control_real.launch.py
启动顺序: 后端(0s) → 网关(5s) → 可视化(7s) → LLM面板(8s)
可选参数:
  can_port  — CAN 接口, 默认 can0
  is_touch  — 触觉传感器, 默认 true
  topic_hz  — 驱动频率, 默认 30
"""
import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # 复用 bootstrap 真机启动 (驱动 + 网关 + 可视化)
    real_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('l10_right_hand_bootstrap'),
            'launch', 'real.launch.py',
        )),
        launch_arguments={
            'can_port': LaunchConfiguration('can_port'),
            'is_touch': LaunchConfiguration('is_touch'),
            'topic_hz': LaunchConfiguration('topic_hz'),
        },
    )

    return LaunchDescription([
        # 可选参数
        DeclareLaunchArgument('can_port', default_value='can0'),
        DeclareLaunchArgument('is_touch', default_value='true'),
        DeclareLaunchArgument('topic_hz', default_value='30'),

        # 阶段 1-3: CAN 驱动 + 网关 + 可视化 (由 bootstrap 启动)
        real_launch,
        # 阶段 4: LLM 控制面板 (等网关和可视化就绪)
        TimerAction(
            period=8.0,
            actions=[
                Node(
                    package='l10_right_hand_llm',
                    executable='llm_control_node',
                    name='hand_llm_control',
                    output='screen',
                ),
            ],
        ),
    ])
