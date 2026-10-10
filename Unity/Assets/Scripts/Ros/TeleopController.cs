using RosMessageTypes.Geometry;
using RosMessageTypes.Std;
using Unity.Robotics.ROSTCPConnector;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Understory
{
    /// <summary>
    /// Drive + e-stop from the Quest (or keyboard in the editor).
    ///  - Left stick: forward/back + strafe (mecanum), right stick X: turn -> /cmd_vel_teleop at 10 Hz,
    ///    only while a stick is held (twist_mux gives control back to autonomy 0.5 s after we go quiet;
    ///    touching the sticks during autonomy switches the mission to MANUAL).
    ///  - B: toggle e-stop -> /estop (twist_mux lock, highest priority). Re-sent at 2 Hz.
    /// Twist values are robot-frame ROS axes (x forward, y left, z up), built directly; no Unity conversion.
    /// Editor: WASD drive/strafe, Q/E turn, Space e-stop.
    /// </summary>
    public class TeleopController : MonoBehaviour
    {
        [Header("Limits (match understory_nav/config/nav2.yaml)")]
        [SerializeField] float maxForward = 0.25f;
        [SerializeField] float maxStrafe = 0.2f;
        [SerializeField] float maxTurn = 0.8f;
        [SerializeField] float deadzone = 0.15f;
        [SerializeField] float rateHz = 10f;
        [SerializeField] bool publish = true;

        public const string TeleopTopic = "/cmd_vel_teleop";
        public const string EStopTopic = "/estop";

        public bool EStopped { get; private set; }
        /// <summary>Last command sent: (linear x, linear y, angular z).</summary>
        public Vector3 LastCommand { get; private set; }
        public bool Driving { get; private set; }

        ROSConnection ros;
        float nextSend, nextEStop;
        TextMesh banner;

        void Start()
        {
            if (publish)
            {
                ros = ROSConnection.GetOrCreateInstance();
                ros.RegisterPublisher<TwistMsg>(TeleopTopic);
                ros.RegisterPublisher<BoolMsg>(EStopTopic);
            }
            banner = WorldUI.MakeLabel(null, "E-STOP\n<size=24>press B to release</size>", new Color(1f, 0.15f, 0.1f), 0.09f,
                TextAnchor.MiddleCenter);
            banner.richText = true;
            banner.name = "EStopBanner";
            banner.gameObject.SetActive(false);
        }

        void OnDestroy()
        {
            if (banner != null) Destroy(banner.gameObject);
        }

        void Update()
        {
            var kb = Keyboard.current;
            if (OVRInput.GetDown(OVRInput.Button.Two) || (kb != null && kb.spaceKey.wasPressedThisFrame))
                SetEStop(!EStopped);

            float now = Time.unscaledTime;
            if (now >= nextEStop)
            {
                Publish(EStopTopic, new BoolMsg(EStopped));
                nextEStop = now + 0.5f;
            }

            // Sticks (+ keyboard for the editor).
            var move = Deadzone(OVRInput.Get(OVRInput.Axis2D.PrimaryThumbstick, OVRInput.Controller.LTouch));
            float turn = Deadzone(OVRInput.Get(OVRInput.Axis2D.PrimaryThumbstick, OVRInput.Controller.RTouch)).x;
            if (kb != null)
            {
                move += new Vector2((kb.dKey.isPressed ? 1 : 0) - (kb.aKey.isPressed ? 1 : 0),
                                    (kb.wKey.isPressed ? 1 : 0) - (kb.sKey.isPressed ? 1 : 0));
                turn += (kb.eKey.isPressed ? 1 : 0) - (kb.qKey.isPressed ? 1 : 0);
                move = Vector2.ClampMagnitude(move, 1f);
                turn = Mathf.Clamp(turn, -1f, 1f);
            }

            bool moving = !EStopped && (move != Vector2.zero || turn != 0f);
            if (moving)
            {
                if (now >= nextSend)
                {
                    // Stick up = forward (+x), stick right = strafe right (-y), stick right = turn right (-z).
                    SendTwist(move.y * maxForward, -move.x * maxStrafe, -turn * maxTurn);
                    nextSend = now + 1f / rateHz;
                }
            }
            else if (Driving)
            {
                SendTwist(0f, 0f, 0f); // one stop, then silent so autonomy can resume
                nextSend = 0f;
            }
            Driving = moving;
        }

        void LateUpdate()
        {
            if (banner == null || !banner.gameObject.activeSelf) return;
            var cam = Camera.main;
            if (cam == null) return;
            var t = cam.transform;
            banner.transform.SetPositionAndRotation(t.position + t.forward * 1.0f - t.up * 0.12f,
                Quaternion.LookRotation(t.forward, t.up));
        }

        public void SetEStop(bool on)
        {
            EStopped = on;
            Publish(EStopTopic, new BoolMsg(on));
            nextEStop = Time.unscaledTime + 0.5f;
            if (on) SendTwist(0f, 0f, 0f);
            Driving = false;
            if (banner != null) banner.gameObject.SetActive(on);
            Haptics.Buzz(this, on ? 1f : 0.4f, on ? 0.35f : 0.12f);
            Debug.Log($"[Teleop] E-STOP {(on ? "ENGAGED" : "released")}");
        }

        void SendTwist(float x, float y, float wz)
        {
            LastCommand = new Vector3(x, y, wz);
            Publish(TeleopTopic, new TwistMsg(new Vector3Msg(x, y, 0), new Vector3Msg(0, 0, wz)));
        }

        void Publish(string topic, Unity.Robotics.ROSTCPConnector.MessageGeneration.Message msg)
        {
            if (ros != null) ros.Publish(topic, msg);
        }

        Vector2 Deadzone(Vector2 v)
        {
            float m = v.magnitude;
            if (m < deadzone) return Vector2.zero;
            return v / m * Mathf.InverseLerp(deadzone, 1f, Mathf.Min(m, 1f)); // rescale so motion starts at 0
        }
    }
}
