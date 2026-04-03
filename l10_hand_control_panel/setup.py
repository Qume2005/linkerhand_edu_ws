from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'l10_hand_control_panel'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['build', 'install', 'log']),
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
