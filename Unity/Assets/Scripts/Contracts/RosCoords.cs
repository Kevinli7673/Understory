using UnityEngine;

namespace Understory
{
    /// <summary>
    /// The ONLY place ROS <-> Unity coordinate conversion happens. Never convert ad hoc.
    ///
    /// ROS (map frame, REP-103): x forward, y left, z up, right-handed, yaw CCW from +x (radians).
    /// Unity: x right, y up, z forward, left-handed, yaw CW from +z (degrees).
    /// </summary>
    public static class RosCoords
    {
        /// <summary>ROS position (meters) -> Unity position (meters).</summary>
        public static Vector3 ToUnity(float x, float y, float z = 0f) => new Vector3(-y, z, x);

        /// <summary>Unity position -> ROS (x, y, z).</summary>
        public static Vector3 ToRos(Vector3 unity) => new Vector3(unity.z, -unity.x, unity.y);

        /// <summary>ROS yaw (rad, CCW) -> Unity yaw (deg, CW about +y).</summary>
        public static float ToUnityYaw(float rosYaw) => -rosYaw * Mathf.Rad2Deg;

        /// <summary>Unity yaw (deg) -> ROS yaw (rad), wrapped to [-pi, pi].</summary>
        public static float ToRosYaw(float unityYawDeg)
        {
            float rad = -unityYawDeg * Mathf.Deg2Rad;
            return Mathf.Atan2(Mathf.Sin(rad), Mathf.Cos(rad));
        }

        /// <summary>ROS yaw -> Unity rotation facing that heading.</summary>
        public static Quaternion ToUnityRotation(float rosYaw) => Quaternion.Euler(0f, ToUnityYaw(rosYaw), 0f);

        /// <summary>Unit direction in Unity space for a ROS yaw (e.g. a pin bearing).</summary>
        public static Vector3 ToUnityDirection(float rosYaw) => ToUnityRotation(rosYaw) * Vector3.forward;
    }
}
