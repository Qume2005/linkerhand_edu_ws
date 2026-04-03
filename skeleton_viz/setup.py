from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'skeleton_viz'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index_packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.rviz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='linkerhand',
    maintainer_email='linkerhand@linkerbot.com',
    description='Skeleton Visualization for L10 Right Hand',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'skeleton_viz_node = skeleton_viz.skeleton_viz_node:main',
        ],
    },
)