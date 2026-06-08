"""
石头剪刀布仿真: MuJoCo 仿真后端 + 网关 + 石头剪刀布游戏
launch: ros2 launch l10_right_hand_rock_paper_scissors rock_paper_scissors_sim.launch.py
可选参数:
  camera_id  — 摄像头编号, 默认 0
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
    # 修复 OpenCV (cv2) 自带 Qt 插件与系统 Qt5 冲突
    fix_qt_plugin = SetEnvironmentVariable(
        'QT_QPA_PLATFORM_PLUGIN_PATH',
        '/usr/lib/x86_64-linux-gnu/qt5/plugins/platforms',
    )

    sim_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('l10_right_hand_bootstrap'),
            'launch', 'sim.launch.py',
        )),
    )

    game_node = TimerAction(
        period=6.0,
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
        sim_launch,
        game_node,
    ])
