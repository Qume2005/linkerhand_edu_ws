from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'l10_hand_control_panel'

# 收集 URDF 数据文件
urdf_base = os.path.join(package_name, 'urdf', 'linker_hand_l10_right')
urdf_data_files = []
for f in glob(os.path.join(urdf_base, '*')):
    if os.path.isfile(f):
        dest = os.path.join('share', package_name, os.path.relpath(f, package_name))
        # ament_python 安装到 site-packages 内, 用 package_data 替代
        pass

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['build', 'install', 'log']),
    package_data={
        package_name: [
            'urdf/linker_hand_l10_right/*.STL',
            'urdf/linker_hand_l10_right/*.xml',
            'urdf/linker_hand_l10_right/*.urdf',
        ],
    },
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='larkume',
    maintainer_email='larkume@todo.todo',
    description='L10 Hand Control Panel - GUI for controlling 10 DOF',
    license='TODO: Declaration of the license',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'control_panel = l10_hand_control_panel.control_panel:main',
        ],
    },
)
