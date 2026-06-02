"""
真机模式: CAN 硬件驱动 + 网关 + 面板 + 可视化
launch: ros2 launch l10_right_hand_bootstrap real.launch.py
启动顺序: 后端(0s) → 网关(5s) → 可视化+面板(7s)
可选参数:
  can_port  — CAN 接口, 默认 can0
  is_touch  — 触觉传感器, 默认 true
  topic_hz  — 控制频率 (Hz), 同时控制网关插值和驱动发送, 默认 60
"""
import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, RegisterEventHandler, TimerAction
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    viz_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('l10_right_hand_viz'),
            'launch', 'hand_viz.launch.py',
        )),
    )

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
        # 可选参数
        DeclareLaunchArgument('can_port', default_value='can0'),
        DeclareLaunchArgument('is_touch', default_value='true'),
        DeclareLaunchArgument('topic_hz', default_value='60'),

        # 阶段 1: 后端
        driver_node,
        # 驱动退出时只打印警告，不终止其他节点
        RegisterEventHandler(
            OnProcessExit(
                target_action=driver_node,
                on_exit=[
                    LogInfo(msg='L10 驱动节点已退出，其余节点继续运行'),
                ],
            ),
        ),
        # 阶段 2: 网关 (等后端初始化完成)
        TimerAction(
            period=5.0,
            actions=[
                Node(
                    package='l10_hand_gateway',
                    executable='l10_gateway_node',
                    name='l10_hand_gateway',
                    parameters=[{
                        'topic_hz': LaunchConfiguration('topic_hz'),
                    }],
                    output='screen',
                ),
            ],
        ),
        # 阶段 3: 可视化 + 面板 (等网关就绪)
        TimerAction(
            period=7.0,
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
