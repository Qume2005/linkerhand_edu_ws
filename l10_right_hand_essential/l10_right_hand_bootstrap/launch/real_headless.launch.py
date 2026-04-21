"""
真机无头模式: CAN 硬件驱动 + 网关 (无可视化/面板)
launch: ros2 launch l10_right_hand_bootstrap real_headless.launch.py
可选参数:
  can_port  — CAN 接口, 默认 can0
  is_touch  — 触觉传感器, 默认 true
  topic_hz  — 驱动频率, 默认 30
"""
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument, LogInfo, RegisterEventHandler, TimerAction
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    driver_node = Node(
        package='l10_right_hand_driver',
        executable='l10_right_hand_driver',
        name='l10_right_hand_driver',
        parameters=[{
            'can_port': LaunchConfiguration('can_port'),
            'is_touch': LaunchConfiguration('is_touch'),
            'topic_hz': LaunchConfiguration('topic_hz'),
        }],
        output='screen',
    )

    return LaunchDescription([
        DeclareLaunchArgument('can_port', default_value='can0'),
        DeclareLaunchArgument('is_touch', default_value='true'),
        DeclareLaunchArgument('topic_hz', default_value='30'),

        # 阶段 1: 后端
        driver_node,
        RegisterEventHandler(
            OnProcessExit(
                target_action=driver_node,
                on_exit=[
                    LogInfo(msg='L10 驱动节点已退出，其余节点继续运行'),
                ],
            ),
        ),
        # 阶段 2: 网关
        TimerAction(
            period=5.0,
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
