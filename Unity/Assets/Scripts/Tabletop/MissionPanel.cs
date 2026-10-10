using System;
using System.Linq;
using RosMessageTypes.Std;
using Unity.Robotics.ROSTCPConnector;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR;

namespace Understory
{
    /// <summary>
    /// Mission buttons on a small console to the right of the tabletop map. Each press publishes the keyword
    /// the mission manager already understands on /voice/text (understory_nav README: start / stop / return /
    /// manual / capture / resume), so buttons and voice share one path. "Stop" ends the mission; the
    /// e-stop is B. Buttons starting with '#' are local (raised on Pressed, never published).
    /// Pick with the controller ray (ControllerPointer) or a mouse click in the editor.
    /// </summary>
    public class MissionPanel : MonoBehaviour
    {
        [SerializeField] TabletopMap table;

        public const string Topic = "/voice/text";
        public const string CompareKeyword = "#compare";
        public const string SensorsKeyword = "#sensors";
        public const string ModelKeyword = "#model";
        public const string AddressKeyword = "#address";

        static readonly Color Go = new Color(0.15f, 0.55f, 0.25f), Blue = new Color(0.15f, 0.4f, 0.6f),
            Amber = new Color(0.45f, 0.4f, 0.15f), Red = new Color(0.6f, 0.2f, 0.15f), Purple = new Color(0.4f, 0.25f, 0.55f),
            Gray = new Color(0.3f, 0.32f, 0.35f);

        static readonly (string label, string keyword, Color color)[] Buttons =
        {
            ("Start survey", "start", Go), ("Capture here", "capture", Blue),
            ("Resume", "resume", Blue), ("Manual", "manual", Amber),
            ("Return home", "return", Amber), ("Stop mission", "stop", Red),
            ("Compare before", CompareKeyword, Purple), ("Sensor map", SensorsKeyword, Purple),
            ("3D model", ModelKeyword, Purple), ("Robot address", AddressKeyword, Gray),
        };

        const float ButtonW = 0.12f, ButtonD = 0.045f, Gap = 0.01f, Tilt = 35f;
        const int Columns = 2;

        /// <summary>Fires with the keyword after it's published (or attempted).</summary>
        public event Action<string> Pressed;

        WorldButtons grid;
        ROSConnection ros;
        const float RepeatGuard = 2f;
        string lastCommand;
        float lastCommandTime = -100f;

        void Start()
        {
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            var source = FindAnyObjectByType<RosSurveySource>();
            if (source != null && source.RosEnabled)
            {
                ros = ROSConnection.GetOrCreateInstance();
                ros.RegisterPublisher<StringMsg>(Topic);
            }
            if (table != null) table.LayoutChanged += Place;
        }

        void OnDestroy()
        {
            if (table != null) table.LayoutChanged -= Place;
            grid?.Destroy();
        }

        void Update()
        {
            if (grid == null && table != null && table.Root != null)
            {
                grid = new WorldButtons(table.Root, "MissionPanel", table.BaseMaterial,
                    Buttons.Select(b => (b.label, b.color)).ToList(), Columns, new Vector2(ButtonW, ButtonD), Gap, 0.015f);
                Place();
            }
            if (grid == null) return;
            grid.Tick();

            if (XRSettings.isDeviceActive || !table.Visible) return;
            var mouse = Mouse.current;
            if (mouse != null && mouse.leftButton.wasPressedThisFrame && Camera.main != null)
                TrySelect(Camera.main.ScreenPointToRay(mouse.position.ReadValue()));
        }

        /// <summary>Press the button the ray hits, if any.</summary>
        public bool TrySelect(Ray ray)
        {
            if (grid == null || !table.Visible) return false;
            int i = grid.Hit(ray);
            if (i < 0) return false;
            Press(i);
            return true;
        }

        void Press(int i)
        {
            var keyword = Buttons[i].keyword;
            grid.Flash(i);
            bool local = keyword.StartsWith("#");
            Haptics.Buzz(this, 0.3f, 0.06f, OVRInput.Controller.RTouch);
            // Robot commands: ignore a repeat of the same command within RepeatGuard seconds (e.g. "Capture here"
            // mashed 5x would queue 5 full spins on the real robot). The flash + buzz still confirm the press.
            if (!local && keyword == lastCommand && Time.unscaledTime - lastCommandTime < RepeatGuard)
            {
                Debug.Log($"[MissionPanel] {Buttons[i].label}: repeat within {RepeatGuard}s ignored");
                return;
            }
            if (!local)
            {
                lastCommand = keyword;
                lastCommandTime = Time.unscaledTime;
                if (ros != null) ros.Publish(Topic, new StringMsg(keyword));
            }
            if (local) Debug.Log($"[MissionPanel] {Buttons[i].label}");
            else Debug.Log($"[MissionPanel] {Buttons[i].label} -> {Topic} '{keyword}'{(ros == null ? " (ROS off, not sent)" : "")}");
            Pressed?.Invoke(keyword);
        }

        /// <summary>Console just right of the board, tilted up toward the viewer.</summary>
        void Place()
        {
            if (grid == null) return;
            var half = table.HalfExtents;
            float width = Columns * ButtonW + (Columns - 1) * Gap;
            grid.Root.localPosition = new Vector3(half.x + width / 2f + 0.05f, 0.02f, -half.y * 0.25f);
            grid.Root.localRotation = Quaternion.Euler(-Tilt, -20f, 0f);
        }
    }
}
