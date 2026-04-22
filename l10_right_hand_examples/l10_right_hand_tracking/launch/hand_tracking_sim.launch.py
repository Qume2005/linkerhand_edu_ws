"""
手势跟随仿真: MuJoCo 仿真后端 + 网关 + 摄像头手势跟踪
launch: ros2 launch l10_right_hand_tracking hand_tracking_sim.launch.py
可选参数:
  camera_id  — 摄像头编号, 默认 0
  publish_hz — 发布频率, 默认 30
"""
import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # 启动仿真后端 + 网关
    sim_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('l10_right_hand_bootstrap'),
            'launch', 'sim.launch.py',
        )),
    )

    # 手势跟踪节点 (等网关就绪后启动)
    tracking_node = TimerAction(
        period=5.0,
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
        sim_launch,
        tracking_node,
    ])
