"""Navigation stack on the Jetson: static TFs, odom, slam_toolbox, Nav2, twist_mux, mission.

Works in Mode A and Mode B unchanged: everything is topics/TF.

  ros2 launch understory_nav nav.launch.py                       # real robot
  ros2 launch understory_nav nav.launch.py odom_source:=external # something else publishes odom->base_link
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, LaunchConfigurationEquals
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory('understory_nav')
    cfg = lambda name: os.path.join(share, 'config', name)  # noqa: E731
    lc = LaunchConfiguration
    nav2_params = cfg('nav2.yaml')
    lifecycle_nodes = ['controller_server', 'planner_server', 'behavior_server', 'bt_navigator']

    args = [
        DeclareLaunchArgument('odom_source', default_value='cmd_vel',
                              description='cmd_vel: dead-reckon from /cmd_vel; external: someone else publishes odom'),
        DeclareLaunchArgument('mission', default_value='true'),
        DeclareLaunchArgument('mission_id', default_value='m1'),
        # LiDAR / camera mounting relative to base_link (meters, radians). Measure on the robot.
        DeclareLaunchArgument('laser_x', default_value='0.0'),
        DeclareLaunchArgument('laser_y', default_value='0.0'),
        DeclareLaunchArgument('laser_z', default_value='0.15'),
        DeclareLaunchArgument('laser_yaw', default_value='0.0'),
        DeclareLaunchArgument('laser_frame', default_value='laser'),
        DeclareLaunchArgument('camera_x', default_value='0.08'),
        DeclareLaunchArgument('camera_z', default_value='0.20'),
        DeclareLaunchArgument('camera_frame', default_value='camera_link'),
    ]

    tf_laser = Node(
        package='tf2_ros', executable='static_transform_publisher', name='tf_laser',
        arguments=['--x', lc('laser_x'), '--y', lc('laser_y'), '--z', lc('laser_z'),
                   '--yaw', lc('laser_yaw'), '--frame-id', 'base_link', '--child-frame-id', lc('laser_frame')])
    tf_camera = Node(
        package='tf2_ros', executable='static_transform_publisher', name='tf_camera',
        arguments=['--x', lc('camera_x'), '--z', lc('camera_z'),
                   '--frame-id', 'base_link', '--child-frame-id', lc('camera_frame')])

    odom = Node(package='understory_nav', executable='cmd_vel_odom', name='cmd_vel_odom',
                condition=LaunchConfigurationEquals('odom_source', 'cmd_vel'))

    slam = Node(package='slam_toolbox', executable='async_slam_toolbox_node', name='slam_toolbox',
                output='screen', parameters=[cfg('slam_toolbox.yaml')])

    to_auto = [('cmd_vel', '/cmd_vel_auto')]
    # respawn: a crashed Nav2 server comes back and the lifecycle manager reconnects to it.
    nav_kw = dict(output='screen', parameters=[nav2_params], respawn=True, respawn_delay=2.0)
    nav2 = [
        Node(package='nav2_controller', executable='controller_server', name='controller_server',
             remappings=to_auto, **nav_kw),
        Node(package='nav2_planner', executable='planner_server', name='planner_server', **nav_kw),
        Node(package='nav2_behaviors', executable='behavior_server', name='behavior_server',
             remappings=to_auto, **nav_kw),
        Node(package='nav2_bt_navigator', executable='bt_navigator', name='bt_navigator', **nav_kw),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager_navigation', output='screen',
             # bond_timeout 10 s (default 4): a busy Jetson CPU shouldn't take Nav2 down.
             parameters=[{'autostart': True, 'node_names': lifecycle_nodes, 'bond_timeout': 10.0}]),
    ]

    mux = Node(package='twist_mux', executable='twist_mux', name='twist_mux', output='screen',
               parameters=[cfg('twist_mux.yaml')], remappings=[('cmd_vel_out', '/cmd_vel')])

    mission = Node(package='understory_nav', executable='mission_manager', name='mission_manager',
                   output='screen', parameters=[cfg('mission.yaml'), {'mission_id': lc('mission_id')}],
                   condition=IfCondition(lc('mission')))

    return LaunchDescription(args + [tf_laser, tf_camera, odom, slam, *nav2, mux, mission])
