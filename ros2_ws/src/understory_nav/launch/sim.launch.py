"""Full nav + mission stack against a fake robot, LiDAR and panorama. No hardware.

  ros2 launch understory_nav sim.launch.py
  ros2 topic pub --once /voice/text std_msgs/String "data: start survey"
  ros2 topic echo /mission/state
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory('understory_nav')
    nav = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(share, 'launch', 'nav.launch.py')),
        launch_arguments={'odom_source': 'external', 'laser_z': '0.0', 'mission_id': 'm0'}.items())
    return LaunchDescription([
        Node(package='understory_nav', executable='fake_world', name='fake_world', output='screen'),
        Node(package='understory_nav', executable='fake_panorama', name='fake_panorama', output='screen'),
        nav,
    ])
