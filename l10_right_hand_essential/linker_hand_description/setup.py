from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'linker_hand_description'

# 收集 URDF + STL + XML 文件安装到 share 目录
model_dir = os.path.join(package_name, 'urdf', 'L10', 'linker_hand_l10_right')
model_files = (
    glob(os.path.join(model_dir, 'meshes', '*.STL'))
    + glob(os.path.join(model_dir, '*.urdf'))
    + glob(os.path.join(model_dir, '*.xml'))
)

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    package_data={
        package_name: [
            'urdf/L10/linker_hand_l10_right/meshes/*.STL',
            'urdf/L10/linker_hand_l10_right/*.urdf',
            'urdf/L10/linker_hand_l10_right/*.xml',
        ],
    },
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # 安装 URDF/XML 到 share/<pkg>/urdf/L10/linker_hand_l10_right/
        (os.path.join('share', package_name, 'urdf', 'L10', 'linker_hand_l10_right'),
            glob(os.path.join(model_dir, '*.urdf'))
            + glob(os.path.join(model_dir, '*.xml'))),
        # 安装 STL 到 share/<pkg>/urdf/L10/linker_hand_l10_right/meshes/
        (os.path.join('share', package_name, 'urdf', 'L10', 'linker_hand_l10_right', 'meshes'),
            glob(os.path.join(model_dir, 'meshes', '*.STL'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='linkerhand',
    maintainer_email='linkerhand@linkerbot.com',
    description='L10 Linker Hand URDF/MuJoCo model description package',
    license='Apache-2.0',
    tests_require=['pytest'],
)