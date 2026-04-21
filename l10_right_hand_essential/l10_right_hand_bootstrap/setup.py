import os
from glob import glob
from setuptools import setup, find_packages

package_name = 'l10_right_hand_bootstrap'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['build', 'install', 'log']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='larkume',
    maintainer_email='larkume@todo.todo',
    description='Launch files for L10 right hand (sim / real hardware)',
    license='Apache-2.0',
    tests_require=['pytest'],
)
