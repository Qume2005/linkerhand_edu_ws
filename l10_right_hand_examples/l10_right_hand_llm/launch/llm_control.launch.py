"""
LLM 手势控制 - 仿真模式: MuJoCo 后端 + 网关 + 可视化 + LLM 控制面板
launch: ros2 launch l10_right_hand_llm llm_control.launch.py
启动顺序: 后端(0s) → 网关(3s) → 可视化(5s) → LLM面板(6s)
"""
import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # 复用 bootstrap 仿真启动 (后端 + 网关 + 可视化)
    sim_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('l10_right_hand_bootstrap'),
            'launch', 'sim.launch.py',
        )),
    )

    return LaunchDescription([
        # 阶段 1-3: MuJoCo 仿真后端 + 网关 + 可视化 (由 bootstrap 启动)
        sim_launch,
        # 阶段 4: LLM 控制面板 (等网关和可视化就绪)
        TimerAction(
            period=6.0,
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
