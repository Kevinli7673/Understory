import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

LIDAR_PORT = '/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_5839a1d8ce6ff01187f694301045c30f-if00-port0'
# usb_cam mangles by-id symlinks into /dev/../../video0, so resolve to /dev/videoN first
CAMERA_DEV = os.path.realpath('/dev/v4l/by-id/usb-046d_Brio_101_2444APDA1MB8-video-index0')

def generate_launch_description():
    lidar = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('rplidar_ros'), 'launch', 'rplidar_c1_launch.py')),
        launch_arguments={'serial_port': LIDAR_PORT, 'frame_id': 'laser'}.items())

    camera = Node(
        package='usb_cam', executable='usb_cam_node_exe', name='camera',
        parameters=[{'video_device': CAMERA_DEV, 'pixel_format': 'mjpeg2rgb',
                     'image_width': 640, 'image_height': 480,
                     'framerate': 15.0, 'frame_id': 'camera',
                     'brightness': 128}],  # usb_cam defaults to 50 (dark); 128 is the Brio's default
        remappings=[('image_raw', '/camera/image'),
                    ('image_raw/compressed', '/camera/image/compressed'),
                    ('camera_info', '/camera/camera_info')],
        # usb_cam aborts on a bad first frame ("Invalid v4l2 format"), e.g. after the camera resets on USB: retry
        respawn=True, respawn_delay=2.0)

    # understory_nav's nav.launch.py publishes these same two TFs (with measured offsets).
    # When it is running anywhere on the network, start bringup with publish_tf:=false
    # so there is only one source for base_link -> laser / camera.
    publish_tf = DeclareLaunchArgument('publish_tf', default_value='true')
    tf_on = IfCondition(LaunchConfiguration('publish_tf'))
    tf_laser = Node(package='tf2_ros', executable='static_transform_publisher', condition=tf_on,
        arguments=['--x', '0.0', '--z', '0.15',
                   '--frame-id', 'base_link', '--child-frame-id', 'laser'])
    tf_camera = Node(package='tf2_ros', executable='static_transform_publisher', condition=tf_on,
        arguments=['--x', '0.08', '--z', '0.10',
                   '--frame-id', 'base_link', '--child-frame-id', 'camera'])

    foxglove = Node(package='foxglove_bridge', executable='foxglove_bridge',
        parameters=[{'port': 8765}])

    return LaunchDescription([publish_tf, lidar, camera, tf_laser, tf_camera, foxglove])
