using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR;

namespace Understory
{
    /// <summary>
    /// Type the robot's (Jetson / mock endpoint) IP in VR when the hotspot hands out a new address:
    /// panel "Robot address" opens a keypad left of the table; Connect saves ros_ip.txt and reconnects
    /// (RosSurveySource.SetAddress). No laptop or adb needed.
    /// </summary>
    public class IpKeypad : MonoBehaviour
    {
        [SerializeField] TabletopMap table;
        [SerializeField] MissionPanel panel;
        [SerializeField] RosSurveySource source;

        static readonly Color Key = new Color(0.25f, 0.27f, 0.3f), Ok = new Color(0.15f, 0.55f, 0.25f), Cancel = new Color(0.45f, 0.2f, 0.18f);
        static readonly string[] Keys = { "1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "<" };

        const float KeyW = 0.06f, KeyD = 0.045f, Gap = 0.008f;

        Transform root;
        WorldButtons keys, actions;
        TextMesh display;
        string text = "";
        bool open;

        public bool IsOpen => open;

        void Start()
        {
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (panel == null) panel = FindAnyObjectByType<MissionPanel>();
            if (source == null) source = FindAnyObjectByType<RosSurveySource>();
            if (table == null) { enabled = false; return; }
            if (panel != null) panel.Pressed += OnPanel;
            table.LayoutChanged += Place;
        }

        void OnDestroy()
        {
            if (panel != null) panel.Pressed -= OnPanel;
            if (table != null) table.LayoutChanged -= Place;
            keys?.Destroy();
            actions?.Destroy();
        }

        void OnPanel(string keyword)
        {
            if (keyword == MissionPanel.AddressKeyword) SetOpen(!open);
        }

        public void SetOpen(bool on)
        {
            if (on && root == null) Build();
            open = on;
            if (root != null) root.gameObject.SetActive(on);
            if (on)
            {
                text = source != null ? source.Ip : "";
                Refresh();
            }
        }

        void Update()
        {
            if (!open || root == null) return;
            keys.Tick();
            actions.Tick();
            if (!table.Visible) { SetOpen(false); return; }
            if (XRSettings.isDeviceActive) return;
            var mouse = Mouse.current;
            if (mouse != null && mouse.leftButton.wasPressedThisFrame && Camera.main != null)
                TrySelect(Camera.main.ScreenPointToRay(mouse.position.ReadValue()));
        }

        /// <summary>Press the key the ray hits (ControllerPointer calls this first while open).</summary>
        public bool TrySelect(Ray ray)
        {
            if (!open || root == null) return false;
            int k = keys.Hit(ray);
            if (k >= 0)
            {
                keys.Flash(k, 0.12f);
                var key = Keys[k];
                if (key == "<") { if (text.Length > 0) text = text.Substring(0, text.Length - 1); }
                else if (text.Length < 15) text += key;
                Refresh();
                Haptics.Buzz(this, 0.15f, 0.03f, OVRInput.Controller.RTouch);
                return true;
            }
            int a = actions.Hit(ray);
            if (a < 0) return false;
            actions.Flash(a);
            if (a == 0)
            {
                if (source != null && source.SetAddress(text)) SetOpen(false);
                else { display.text = $"<color=#ff6655>{text}  ?</color>"; Haptics.Buzz(this, 0.6f, 0.15f, OVRInput.Controller.RTouch); }
            }
            else SetOpen(false);
            return true;
        }

        void Refresh() => display.text = text.Length > 0 ? text : "<color=#777777>type the robot's IP</color>";

        void Build()
        {
            root = new GameObject("IpKeypad").transform;
            root.SetParent(table.Root, false);
            var keySpecs = new List<(string, Color)>();
            foreach (var k in Keys) keySpecs.Add((k == "<" ? "del" : k, Key));
            keys = new WorldButtons(root, "Keys", table.BaseMaterial, keySpecs, 3, new Vector2(KeyW, KeyD), Gap, 0.02f);
            actions = new WorldButtons(root, "Actions", table.BaseMaterial,
                new List<(string, Color)> { ("Connect", Ok), ("Cancel", Cancel) }, 2, new Vector2(KeyW * 1.5f + Gap / 2f, KeyD), Gap, 0.016f);
            float keysDepth = 4 * KeyD + 3 * Gap;
            actions.Root.localPosition = new Vector3(0f, 0f, -(keysDepth / 2f + Gap + KeyD / 2f));

            display = WorldUI.MakeLabel(root, "", Color.white, 0.022f, TextAnchor.LowerCenter);
            display.richText = true;
            display.transform.localPosition = new Vector3(0f, 0.005f, keysDepth / 2f + 0.012f);
            display.transform.localRotation = Quaternion.Euler(60f, 0f, 0f);
            Place();
        }

        /// <summary>Left of the board (where the controls card is), tilted toward the viewer.</summary>
        void Place()
        {
            if (root == null) return;
            var half = table.HalfExtents;
            root.localPosition = new Vector3(-half.x - 0.14f, 0.03f, -half.y * 0.2f);
            root.localRotation = Quaternion.Euler(-35f, 20f, 0f);
        }
    }
}
