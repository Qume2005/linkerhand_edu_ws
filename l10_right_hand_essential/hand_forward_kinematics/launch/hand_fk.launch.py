"""正运动学 (FK) 计算节点启动文件。

启动 hand_fk_node，订阅后端发布的手部状态话题（/cb_right_hand_state），
通过正运动学计算将 10-DOF 关节值转换为 21 个体位姿（skeleton）和 5 个
指尖 3D 控制点（control_points），并通过 gateway 话题发布。

该节点是 hand_forward_kinematics 库的 ROS 封装，提供了无 MuJoCo 运行时
依赖的纯 Python FK 计算能力。

使用示例
--------
::

    ros2 launch hand_forward_kinematics hand_fk.launch.py
"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='hand_forward_kinematics',
            executable='hand_fk_node',
            name='hand_fk_node',
            output='screen',
        ),
    ])
