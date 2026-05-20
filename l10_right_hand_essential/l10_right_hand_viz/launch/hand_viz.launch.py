"""RViz2 手部可视化启动文件。

启动 4 个节点实现 L10 灵巧手的三维可视化：

1. **static_transform_publisher** — 发布 world → base_link 静态坐标变换（单位变换）
2. **robot_state_publisher** — 加载 URDF 模型并根据关节数据发布 TF 树
3. **hand_viz_node** — 订阅 gateway 状态话题，将 DOF 值转换为 URDF 关节状态
4. **rviz2** — 启动 RViz2 可视化界面，加载 hand_viz.rviz 配置文件

RViz 配置文件位于 l10_right_hand_viz 包的 config/hand_viz.rviz，
URDF 模型通过 linker_hand_description 包定位。

使用示例
--------
::

    ros2 launch l10_right_hand_viz hand_viz.launch.py
"""
import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from ament_index_python.packages import get_package_share_directory
from linker_hand_description import get_model_dir


def generate_launch_description():
    pkg_dir = get_package_share_directory('l10_right_hand_viz')
    rviz_config = os.path.join(pkg_dir, 'config', 'hand_viz.rviz')

    # URDF 路径 (Python package 内)
    urdf_path = os.path.join(get_model_dir(), 'linker_hand_l10_right.urdf')

    with open(urdf_path, 'r') as f:
        urdf_content = f.read()

    return LaunchDescription([
        # world -> base_link 静态变换
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            arguments=['0', '0', '0', '0', '0', '0', 'world', 'base_link'],
        ),
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            parameters=[{'robot_description': urdf_content}],
            output='screen',
        ),
        Node(
            package='l10_right_hand_viz',
            executable='hand_viz_node',
            name='hand_viz_node',
            output='screen',
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            arguments=['-d', rviz_config],
            output='screen',
            sigterm_timeout='2',
            sigkill_timeout='2',
        ),
    ])