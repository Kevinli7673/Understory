from glob import glob

from setuptools import setup

package_name = 'understory_nav'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='mizbahh',
    maintainer_email='mizbahateeq@gmail.com',
    description='Understory navigation + mission manager',
    license='MIT',
    entry_points={
        'console_scripts': [
            'mission_manager = understory_nav.mission_manager:main',
            'cmd_vel_odom = understory_nav.cmd_vel_odom:main',
            'fake_world = understory_nav.fake_world:main',
            'fake_panorama = understory_nav.fake_panorama:main',
        ],
    },
)
