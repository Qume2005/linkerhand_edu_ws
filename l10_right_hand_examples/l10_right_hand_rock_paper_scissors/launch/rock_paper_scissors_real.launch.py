"""
石头剪刀布真机: CAN 驱动 + 网关 + 面板 + 可视化 + 石头剪刀布游戏
launch: ros2 launch l10_right_hand_rock_paper_scissors rock_paper_scissors_real.launch.py
可选参数:
  camera_id  — 摄像头编号, 默认 0
  can_port   — CAN 接口, 默认 can0
  is_touch   — 触觉传感器, 默认 true
  topic_hz   — 驱动频率, 默认 30
"""
import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            SetEnvironmentVariable, TimerAction)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    fix_qt_plugin = SetEnvironmentVariable(
        'QT_QPA_PLATFORM_PLUGIN_PATH',
        '/usr/lib/x86_64-linux-gnu/qt5/plugins/platforms',
    )

    real_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('l10_right_hand_bootstrap'),
            'launch', 'real.launch.py',
        )),
    )

    game_node = TimerAction(
        period=9.0,
        actions=[
            Node(
                package='l10_right_hand_rock_paper_scissors',
                executable='rock_paper_scissors_node',
                name='rock_paper_scissors_node',
                parameters=[{
                    'camera_id': LaunchConfiguration('camera_id'),
                }],
                output='screen',
            ),
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument('camera_id', default_value='0'),
        fix_qt_plugin,
        real_launch,
        game_node,
    ])
