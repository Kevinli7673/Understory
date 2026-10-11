"""Mapping + navigation + mission + panorama on ROS 2 Jazzy (the scout-ros Docker image).

    ros2 launch /fetch_ws/src/Understory/pi/scout_nav.launch.py [mission_id:=m1] [nav2:=false]

Uses the understory_nav configs unchanged. It exists because understory_nav's own nav.launch.py
targets Humble and does not come up on Jazzy. Differences:
  - slam_toolbox is started through its own launch file, which configures + activates it
    (on Jazzy it is a lifecycle node and does nothing until activated);
  - twist_mux is forced to plain Twist (Jazzy defaults to TwistStamped, which nothing else uses);
  - Nav2 plugin names are overridden with the Jazzy spelling ("pkg::Class", Humble used "pkg/Class");
  - nav2 defaults to true only if Nav2 is installed. Without it "start survey" drops the mission
    to MANUAL: drive with the sticks and say "capture" for a bubble (the fallback in AGENTS.md);
  - no static TFs here; scout_bringup.launch.py publishes base_link -> laser / camera;
  - also starts scout_perception's panorama_node, which answers /survey/capture;
  - also starts scout_perception's logger_node, which writes missions/<mission_id>/ to disk;
  - also starts pi/scripts/pose_from_tf.py: /pose from TF map -> base_link at 10 Hz. slam_toolbox only
    publishes /pose after a scan update, so a robot standing still had no position in the Quest app.
Run it on ONE machine only (Pi or Jetson), never both.
"""
import os

from ament_index_python.packages import PackageNotFoundError, get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition, LaunchConfigurationEquals
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def nav2_installed():
    try:
        get_package_share_directory('nav2_controller')
        return True
    except PackageNotFoundError:
        return False


def generate_launch_description():
    cfg = os.path.join(get_package_share_directory('understory_nav'), 'config')
    nav2_params = os.path.join(cfg, 'nav2.yaml')

    args = [
        DeclareLaunchArgument('mission_id', default_value='m1'),
        DeclareLaunchArgument('nav2', default_value='true' if nav2_installed() else 'false'),
        # cmd_vel: dead-reckon odom from /cmd_vel; external: something else publishes odom -> base_link
        DeclareLaunchArgument('odom_source', default_value='cmd_vel'),
        DeclareLaunchArgument('panorama', default_value='true'),
        DeclareLaunchArgument('pose', default_value='true'),
        DeclareLaunchArgument('logger', default_value='true'),
        # cmd_vel_odom calibration: real speed / commanded speed (drive straight / spin in place and measure)
        DeclareLaunchArgument('linear_scale', default_value='1.0'),
        DeclareLaunchArgument('angular_scale', default_value='1.0'),
    ]

    # pi/slam_toolbox_pi.yaml: understory_nav's config + trust the LiDAR more than the dead-reckoned odom
    here = os.path.dirname(os.path.realpath(__file__))
    slam = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('slam_toolbox'), 'launch', 'online_async_launch.py')),
        launch_arguments={'slam_params_file': os.path.join(here, 'slam_toolbox_pi.yaml'),
                          'use_sim_time': 'false'}.items())

    odom = Node(package='understory_nav', executable='cmd_vel_odom', name='cmd_vel_odom',
                parameters=[{'linear_scale': ParameterValue(LaunchConfiguration('linear_scale'), value_type=float),
                             'angular_scale': ParameterValue(LaunchConfiguration('angular_scale'), value_type=float)}],
                condition=LaunchConfigurationEquals('odom_source', 'cmd_vel'))

    # e-stop > /cmd_vel_teleop > /cmd_vel_auto  ->  /cmd_vel
    mux = Node(package='twist_mux', executable='twist_mux', name='twist_mux',
               parameters=[os.path.join(cfg, 'twist_mux.yaml'), {'use_stamped': False}],
               remappings=[('cmd_vel_out', '/cmd_vel')])

    # Same four Nav2 servers as nav.launch.py, publishing to /cmd_vel_auto for twist_mux.
    to_auto = [('cmd_vel', '/cmd_vel_auto')]
    nav2 = GroupAction(condition=IfCondition(LaunchConfiguration('nav2')), actions=[
        Node(package='nav2_controller', executable='controller_server', name='controller_server',
             parameters=[nav2_params], remappings=to_auto),
        Node(package='nav2_planner', executable='planner_server', name='planner_server',
             parameters=[nav2_params, {'GridBased.plugin': 'nav2_navfn_planner::NavfnPlanner'}]),
        Node(package='nav2_behaviors', executable='behavior_server', name='behavior_server',
             parameters=[nav2_params, {'spin.plugin': 'nav2_behaviors::Spin',
                                       'backup.plugin': 'nav2_behaviors::BackUp',
                                       'drive_on_heading.plugin': 'nav2_behaviors::DriveOnHeading',
                                       'wait.plugin': 'nav2_behaviors::Wait'}],
             remappings=to_auto),
        Node(package='nav2_bt_navigator', executable='bt_navigator', name='bt_navigator',
             parameters=[nav2_params]),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager_navigation',
             parameters=[{'autostart': True, 'node_names': [
                 'controller_server', 'planner_server', 'behavior_server', 'bt_navigator']}]),
    ])

    mission = Node(package='understory_nav', executable='mission_manager', name='mission_manager',
                   parameters=[os.path.join(cfg, 'mission.yaml'),
                               {'mission_id': LaunchConfiguration('mission_id')}])

    panorama = Node(package='scout_perception', executable='panorama_node', name='panorama_node',
                    condition=IfCondition(LaunchConfiguration('panorama')))

    logger = Node(package='scout_perception', executable='logger_node', name='logger_node',
                  condition=IfCondition(LaunchConfiguration('logger')))

    pose = ExecuteProcess(
        cmd=['python3', os.path.join(os.path.dirname(os.path.realpath(__file__)), 'scripts', 'pose_from_tf.py')],
        condition=IfCondition(LaunchConfiguration('pose')), output='screen')

    return LaunchDescription(args + [slam, odom, mux, nav2, mission, panorama, logger, pose])
