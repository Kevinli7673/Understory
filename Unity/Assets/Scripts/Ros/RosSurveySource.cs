using System;
using System.IO;
using System.Net;
using RosMessageTypes.Geometry;
using RosMessageTypes.Nav;
using RosMessageTypes.Sensor;
using RosMessageTypes.Std;
using Unity.Robotics.ROSTCPConnector;
using UnityEngine;

namespace Understory
{
    /// <summary>
    /// Real survey data from ROS (via ros_tcp_endpoint on the Jetson) into SurveyHub, through the same
    /// Handle* methods FakeSurveySource uses. The fake replay runs until the first real message arrives,
    /// then stops and the hub is cleared once, so a dead link still leaves something to show.
    ///
    /// Jetson IP: Application.persistentDataPath/ros_ip.txt if present, else the default below. On the Quest:
    ///   echo 192.168.x.y > ros_ip.txt
    ///   adb push ros_ip.txt /sdcard/Android/data/com.knighthacks.understory/files/
    /// then restart the app (no rebuild).
    /// </summary>
    public class RosSurveySource : MonoBehaviour
    {
        public enum Link { Off, Connecting, Unreachable, Live }

        [SerializeField] SurveyHub hub;
        [SerializeField] FakeSurveySource fake;
        [Tooltip("Used when there's no ros_ip.txt override.")]
        [SerializeField] string defaultIp = "127.0.0.1";
        [SerializeField] int port = 10000;
        [Tooltip("Off = never touch ROS (pure fake replay).")]
        [SerializeField] bool connect = true;
        [Tooltip("Seconds without any message before the status says the data stopped.")]
        [SerializeField] float staleAfter = 5f;

        public const string IpFileName = "ros_ip.txt";

        public string Ip { get; private set; }
        public bool IsLive { get; private set; }
        /// <summary>False when "connect" is off: other components shouldn't create a ROS connection either.</summary>
        public bool RosEnabled => connect;

        ROSConnection ros;

        public Link Status
        {
            get
            {
                if (ros == null) return Link.Off;
                if (IsLive) return Link.Live;
                return ros.HasConnectionError ? Link.Unreachable : Link.Connecting;
            }
        }

        /// <summary>One line for the table: "LIVE 10.0.0.5", "FAKE · connecting 10.0.0.5", ...</summary>
        public string StatusText
        {
            get
            {
                switch (Status)
                {
                    case Link.Live:
                        float age = Time.realtimeSinceStartup - ros.LastMessageReceivedRealtime;
                        return age > staleAfter ? $"LIVE {Ip} · no data {age:F0}s" : $"LIVE {Ip}";
                    case Link.Connecting: return $"FAKE · connecting {Ip}";
                    case Link.Unreachable: return $"FAKE · ROS {Ip} unreachable";
                    default: return "FAKE";
                }
            }
        }

        void Awake()
        {
            Ip = ReadIpOverride() ?? defaultIp;
            if (!connect) return;
            // Set the address before ROSConnection.Start connects (prefab has ConnectOnStart).
            ros = ROSConnection.GetOrCreateInstance();
            ros.RosIPAddress = Ip;
            ros.RosPort = port;
            if (!ros.ConnectOnStart) ros.Connect();
            Debug.Log($"[RosSource] ROS endpoint {Ip}:{port}");
        }

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (fake == null) fake = FindAnyObjectByType<FakeSurveySource>();
            if (ros == null || hub == null) return;

            ros.Subscribe<StringMsg>("/survey/bubbles", m => { GoLive(); hub.HandleBubbleJson(m.data); });
            ros.Subscribe<StringMsg>("/survey/pins", m => { GoLive(); hub.HandlePinJson(m.data); });
            ros.Subscribe<StringMsg>("/survey/readings", m => { GoLive(); hub.HandleReadingJson(m.data); });
            ros.Subscribe<CompressedImageMsg>("/survey/bubble_images", m => { GoLive(); hub.HandleBubbleImage(m.header.frame_id, m.data); });
            ros.Subscribe<StringMsg>("/mission/state", m => { GoLive(); hub.HandleMissionState(m.data); });
            ros.Subscribe<OccupancyGridMsg>("/map", OnMap);
            ros.Subscribe<PoseWithCovarianceStampedMsg>("/pose", OnPose);
        }

        void OnMap(OccupancyGridMsg m)
        {
            GoLive();
            try
            {
                var o = m.info.origin.position; // origin yaw assumed 0 (slam_toolbox / map_server default)
                hub.HandleMap(MapGrid.FromOccupancyGrid((int)m.info.width, (int)m.info.height, m.info.resolution,
                    (float)o.x, (float)o.y, m.data));
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[RosSource] Bad /map: {e.Message}");
            }
        }

        void OnPose(PoseWithCovarianceStampedMsg m)
        {
            GoLive();
            var p = m.pose.pose.position;
            var q = m.pose.pose.orientation;
            // Yaw about ROS z (map frame); stays in ROS axes, the views convert via RosCoords.
            float yaw = (float)Math.Atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z));
            hub.HandleRobotPose((float)p.x, (float)p.y, yaw);
        }

        /// <summary>
        /// Switch the endpoint at runtime (in-VR keypad): saves ros_ip.txt so it sticks across restarts and
        /// reconnects now. Subscriptions/publishers re-register automatically on the new connection.
        /// </summary>
        public bool SetAddress(string ip)
        {
            if (!IPAddress.TryParse(ip, out _)) return false;
            try { File.WriteAllText(Path.Combine(Application.persistentDataPath, IpFileName), ip); }
            catch (Exception e) { Debug.LogWarning($"[RosSource] Couldn't save {IpFileName}: {e.Message}"); }
            Ip = ip;
            if (ros != null)
            {
                ros.Disconnect();
                ros.Connect(ip, port);
            }
            Debug.Log($"[RosSource] endpoint -> {ip}:{port}");
            return true;
        }

        /// <summary>First real message: stop the fake replay and wipe its data, once.</summary>
        void GoLive()
        {
            if (IsLive) return;
            IsLive = true;
            if (fake != null) fake.Stop();
            hub.Clear();
            Debug.Log($"[RosSource] LIVE from {Ip}; fake replay stopped.");
        }

        static string ReadIpOverride()
        {
            try
            {
                var path = Path.Combine(Application.persistentDataPath, IpFileName);
                if (!File.Exists(path)) return null;
                var ip = File.ReadAllText(path).Trim();
                if (IPAddress.TryParse(ip, out _)) return ip;
                Debug.LogWarning($"[RosSource] Ignoring {path}: '{ip}' is not an IP address");
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[RosSource] Couldn't read {IpFileName}: {e.Message}");
            }
            return null;
        }
    }
}
