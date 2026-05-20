"""MuJoCo 仿真后端启动文件。

启动 l10_right_hand_mujoco_sim 仿真节点，提供 L10 灵巧手在 MuJoCo 物理引擎中的
仿真后端。该节点发布 /cb_right_hand_state 话题（10-DOF 关节状态）并订阅
/cb_right_hand_control_cmd 话题接收控制命令。

ROS 参数
--------
- ``topic_hz`` (int, 默认 30): 状态发布频率 (Hz)
- ``is_touch`` (bool, 默认 True): 是否启用触觉传感器仿真

使用示例
--------
::

    ros2 launch l10_right_hand_mujoco_sim l10_right_mujoco.launch.py
    ros2 launch l10_right_hand_mujoco_sim l10_right_mujoco.launch.py topic_hz:=50 is_touch:=false
"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='l10_right_hand_mujoco_sim',
            executable='l10_right_mujoco_node',
            name='l10_right_mujoco_node',
            output='screen',
            parameters=[{
                'topic_hz': 30,
                'is_touch': True,
            }],
        ),
    ])
