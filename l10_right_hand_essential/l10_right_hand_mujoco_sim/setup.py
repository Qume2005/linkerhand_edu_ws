import os
from glob import glob
from setuptools import setup, find_packages

package_name = 'l10_right_hand_mujoco_sim'

# 手动收集需要安装的 Python 包（排除 urdf.bak 目录）
py_packages = [p for p in find_packages(exclude=['test'])
               if not p.startswith(package_name + '.urdf.bak')]

setup(
    name=package_name,
    version='0.0.1',
    packages=py_packages,
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        ('share/' + package_name, ['package.xml']),
    ],
    package_data={
        'l10_right_hand_mujoco_sim': [],
    },
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='linkerhand',
    maintainer_email='linkerhand@linkerbot.com',
    description='L10 Right Hand MuJoCo Simulation ROS2 Package',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'l10_right_mujoco_node=l10_right_hand_mujoco_sim.mujoco_node:main'
        ],
    },
)
