"""
手势跟随真机: CAN 驱动 + 网关 + 面板 + 可视化 + 摄像头手势跟踪
launch: ros2 launch l10_right_hand_tracking hand_tracking_real.launch.py
可选参数:
  camera_id  — 摄像头编号, 默认 0
  publish_hz — 发布频率, 默认 30
  can_port   — CAN 接口, 默认 can0
  is_touch   — 触觉传感器, 默认 true
  topic_hz   — 驱动频率, 默认 30
"""
import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # 启动真机后端 + 网关 + 面板 + 可视化
    real_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('l10_right_hand_bootstrap'),
            'launch', 'real.launch.py',
        )),
    )

    # 手势跟踪节点 (等网关就绪后启动)
    tracking_node = TimerAction(
        period=9.0,
        actions=[
            Node(
                package='l10_right_hand_tracking',
                executable='hand_tracking_node',
                name='hand_tracking_node',
                parameters=[{
                    'camera_id': LaunchConfiguration('camera_id'),
                    'publish_hz': LaunchConfiguration('publish_hz'),
                }],
                output='screen',
            ),
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument('camera_id', default_value='0'),
        DeclareLaunchArgument('publish_hz', default_value='30'),
        real_launch,
        tracking_node,
    ])
