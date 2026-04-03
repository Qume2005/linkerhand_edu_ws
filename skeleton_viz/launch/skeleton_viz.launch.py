from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import ExecuteProcess
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    pkg_share = get_package_share_directory('skeleton_viz')
    rviz_config = os.path.join(pkg_share, 'config', 'skeleton.rviz')

    return LaunchDescription([
        # 启动骨骼可视化节点
        Node(
            package='skeleton_viz',
            executable='skeleton_viz_node',
            name='skeleton_viz_node',
            output='screen',
        ),
        # 启动 RViz2 并自动加载配置
        ExecuteProcess(
            cmd=['rviz2', '-d', rviz_config],
            output='screen',
        ),
    ])