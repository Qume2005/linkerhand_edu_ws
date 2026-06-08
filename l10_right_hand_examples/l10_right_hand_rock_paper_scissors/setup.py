from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'l10_right_hand_rock_paper_scissors'

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
    package_data={
        'l10_right_hand_rock_paper_scissors': ['../sounds/*.wav'],
    },
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='larkume',
    maintainer_email='larkume@todo.todo',
    description='Rock-Paper-Scissors game demo for L10 robotic hand',
    license='TODO: Declaration of the license',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'rock_paper_scissors_node = l10_right_hand_rock_paper_scissors.rock_paper_scissors_node:main',
        ],
    },
)
