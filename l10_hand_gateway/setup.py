from setuptools import setup, find_packages

package_name = 'l10_hand_gateway'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['build', 'install', 'log']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='larkume',
    maintainer_email='larkume@todo.todo',
    description='L10 Hand Gateway - control topic reverse proxy and state proxy',
    license='TODO: Declaration of the license',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'l10_gateway_node = l10_hand_gateway.gateway_node:main',
        ],
    },
)
