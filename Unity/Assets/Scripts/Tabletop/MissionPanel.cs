using System;
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
    /// e-stop is B.
    /// Pick with the controller ray (ControllerPointer) or a mouse click in the editor.
    /// </summary>
    public class MissionPanel : MonoBehaviour
    {
        [SerializeField] TabletopMap table;

        public const string Topic = "/voice/text";
        /// <summary>Local-only buttons start with '#': raised on Pressed, never published.</summary>
        public const string CompareKeyword = "#compare";
        public const string SensorsKeyword = "#sensors";
        public const string ModelKeyword = "#model";

        static readonly (string label, string keyword, Color color)[] Buttons =
        {
            ("Start survey", "start", new Color(0.15f, 0.55f, 0.25f)),
            ("Capture here", "capture", new Color(0.15f, 0.4f, 0.6f)),
            ("Resume", "resume", new Color(0.15f, 0.4f, 0.6f)),
            ("Manual", "manual", new Color(0.45f, 0.4f, 0.15f)),
            ("Return home", "return", new Color(0.45f, 0.4f, 0.15f)),
            ("Stop mission", "stop", new Color(0.6f, 0.2f, 0.15f)),
            ("Compare before", CompareKeyword, new Color(0.4f, 0.25f, 0.55f)),
            ("Sensor map", SensorsKeyword, new Color(0.4f, 0.25f, 0.55f)),
            ("3D model", ModelKeyword, new Color(0.4f, 0.25f, 0.55f)),
        };

        const float ButtonW = 0.13f, ButtonD = 0.045f, Gap = 0.012f, Tilt = 35f;

        /// <summary>Fires with the keyword after it's published (or attempted).</summary>
        public event Action<string> Pressed;

        Transform console;
        readonly Transform[] buttons = new Transform[Buttons.Length];
        readonly Material[] mats = new Material[Buttons.Length];
        readonly float[] flashUntil = new float[Buttons.Length];
        ROSConnection ros;

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
            foreach (var m in mats) if (m != null) Destroy(m);
        }

        void Update()
        {
            if (console == null && table != null && table.Root != null) Build();
            if (console == null) return;

            for (int i = 0; i < buttons.Length; i++)
                mats[i].color = Time.unscaledTime < flashUntil[i] ? Color.white : Buttons[i].color;

            if (XRSettings.isDeviceActive || !table.Visible) return;
            var mouse = Mouse.current;
            if (mouse != null && mouse.leftButton.wasPressedThisFrame && Camera.main != null)
                TrySelect(Camera.main.ScreenPointToRay(mouse.position.ReadValue()));
        }

        /// <summary>Press the button the ray hits, if any.</summary>
        public bool TrySelect(Ray ray)
        {
            if (console == null || !table.Visible) return false;
            for (int i = 0; i < buttons.Length; i++)
            {
                var b = buttons[i];
                var plane = new Plane(b.up, b.position + b.up * 0.005f);
                if (!plane.Raycast(ray, out float d)) continue;
                var local = b.InverseTransformPoint(ray.GetPoint(d)); // unit cube space
                if (Mathf.Abs(local.x) <= 0.5f && Mathf.Abs(local.z) <= 0.5f)
                {
                    Press(i);
                    return true;
                }
            }
            return false;
        }

        void Press(int i)
        {
            var keyword = Buttons[i].keyword;
            flashUntil[i] = Time.unscaledTime + 0.2f;
            bool local = keyword.StartsWith("#");
            if (!local && ros != null) ros.Publish(Topic, new StringMsg(keyword));
            Haptics.Buzz(this, 0.3f, 0.06f, OVRInput.Controller.RTouch);
            if (local) Debug.Log($"[MissionPanel] {Buttons[i].label}");
            else Debug.Log($"[MissionPanel] {Buttons[i].label} -> {Topic} '{keyword}'{(ros == null ? " (ROS off, not sent)" : "")}");
            Pressed?.Invoke(keyword);
        }

        void Build()
        {
            console = new GameObject("MissionPanel").transform;
            console.SetParent(table.Root, false);
            for (int i = 0; i < Buttons.Length; i++)
            {
                var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
                go.name = $"Button {Buttons[i].keyword}";
                Destroy(go.GetComponent<Collider>());
                go.transform.SetParent(console, false);
                go.transform.localScale = new Vector3(ButtonW, 0.008f, ButtonD);
                go.transform.localPosition = new Vector3(0f, 0f, (Buttons.Length / 2f - i - 0.5f) * (ButtonD + Gap));
                mats[i] = WorldUI.Tinted(table.BaseMaterial, null, Buttons[i].color);
                WorldUI.Apply(go, mats[i]);
                buttons[i] = go.transform;

                // Label lying on the button, readable from the viewer's side.
                var label = WorldUI.MakeLabel(console, Buttons[i].label, Color.white, 0.016f, TextAnchor.MiddleCenter).transform;
                label.localPosition = go.transform.localPosition + Vector3.up * 0.0055f;
                label.localRotation = Quaternion.Euler(90f, 0f, 0f);
            }
            Place();
        }

        /// <summary>Console just right of the board, tilted up toward the viewer.</summary>
        void Place()
        {
            if (console == null) return;
            var half = table.HalfExtents;
            console.localPosition = new Vector3(half.x + ButtonW / 2f + 0.05f, 0.02f, -half.y * 0.25f);
            console.localRotation = Quaternion.Euler(-Tilt, -20f, 0f);
        }
    }
}
