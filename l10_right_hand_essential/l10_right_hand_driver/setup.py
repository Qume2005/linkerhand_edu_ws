from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'l10_right_hand_driver'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['build', 'install', 'log']),
    package_data={
        package_name: [
            'linkerhand/*.yaml',
        ],
    },
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='larkume',
    maintainer_email='larkume@todo.todo',
    description='L10 Right Hand Hardware Driver - CAN bus direct',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'l10_right_hand_driver = l10_right_hand_driver.hand_driver_node:main',
        ],
    },
)
