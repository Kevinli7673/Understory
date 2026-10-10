using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR;

namespace Understory
{
    /// <summary>
    /// Miniature "map twin" on a virtual table: floor plan, capture spots (bubbles), plant pins and the robot,
    /// filling in live from SurveyHub. Robot-forward (ROS +x) points away from the viewer.
    ///
    /// Every marker position goes through BoardPos() -> RosCoords.ToUnity, so the table always agrees with
    /// the bubble view and the data. When /map (re)arrives only the scale/offset changes and markers re-place.
    ///
    /// Editor: left-click near a bubble disc to open it, C to re-center the table in front of you.
    /// </summary>
    public class TabletopMap : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [Tooltip("URP/Unlit, Render Face = Both. Auto-assigned when the component is added.")]
        [SerializeField] Material material;
        [Tooltip("Table is placed in front of this (usually the head/camera).")]
        [SerializeField] Transform viewer;
        [Tooltip("Longest side of the map on the table, meters.")]
        [SerializeField] float boardSize = 1.0f;
        [SerializeField] float distance = 0.75f;
        [SerializeField] float belowEye = 0.5f;
        [SerializeField] bool labelNatives;

        /// <summary>A bubble disc was picked (editor click now, controller ray later).</summary>
        public event Action<string> BubbleSelected;
        /// <summary>Board resized (map arrived/changed). Attachments (buttons, camera screen) re-place.</summary>
        public event Action LayoutChanged;

        /// <summary>Table root: +z points away from the viewer, slab top at local y = 0. Null until Start.</summary>
        public Transform Root => root;
        /// <summary>Half width (x) and half depth (y) of the slab top, root-local meters.</summary>
        public Vector2 HalfExtents { get; private set; }
        public Material BaseMaterial => material;
        /// <summary>Parent for anything placed in map coordinates (local positions from BoardPosition).</summary>
        public Transform MapRoot => mapRoot;
        /// <summary>Extra status lines from attachments (before/after, sensor map); null/empty = no line.</summary>
        public readonly List<Func<string>> StatusProviders = new List<Func<string>>();
        /// <summary>Board meters per map meter.</summary>
        public float Scale => scale;

        /// <summary>ROS map-frame (x, y) -> MapRoot-local position on the board. Changes on LayoutChanged.</summary>
        public Vector3 BoardPosition(float x, float y) => BoardPos(x, y);

        static readonly Color SlabColor = new Color(0.10f, 0.11f, 0.12f);
        static readonly Color BubbleColor = new Color(0.2f, 0.85f, 0.95f);
        static readonly Color Invasive = new Color(0.95f, 0.2f, 0.2f);
        static readonly Color Native = new Color(0.25f, 0.9f, 0.35f);
        static readonly Color RobotColor = new Color(1f, 0.8f, 0.2f);
        const float SlabThickness = 0.03f;
        const float Margin = 0.04f;
        const float DefaultSpan = 10f; // meters shown before the first /map
        const float SelectRadius = 0.06f; // on the board, meters

        Transform root, mapRoot;
        GameObject slab, floor, robot;
        TextMesh status;
        Texture2D floorTex;
        MapGrid map;
        float scale = 1f;
        Vector2 center; // ROS map-frame point shown at the board center

        // Every marker remembers its ROS position so Relayout() can re-place it.
        readonly List<(Transform t, Vector2 ros)> placed = new List<(Transform, Vector2)>();
        readonly Dictionary<string, GameObject> bubbles = new Dictionary<string, GameObject>();
        readonly Dictionary<string, GameObject> pins = new Dictionary<string, GameObject>();
        readonly List<UnityEngine.Object> owned = new List<UnityEngine.Object>();
        Vector2? robotPos;
        float lastRealPose = -100f;
        float nextStatus;
        RosSurveySource rosSource;
        TeleopController teleop;
        float robotYaw;

        bool visible = true;
        public bool Visible
        {
            get => visible;
            set { visible = value; if (root != null) root.gameObject.SetActive(value); }
        }

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (viewer == null && Camera.main != null) viewer = Camera.main.transform;
            if (material == null) material = WorldUI.FallbackUnlit();
            if (hub == null) { Debug.LogError("[Tabletop] No SurveyHub in scene."); enabled = false; return; }

            BuildStatic();
            Recenter();
            Invoke(nameof(Recenter), 0.5f); // headset pose is often not valid on the first frame

            hub.MapUpdated += OnMap;
            hub.BubbleReceived += OnBubble;
            hub.PinAdded += OnPin;
            hub.ReadingReceived += OnReading;
            hub.RobotPoseUpdated += OnRobotPose;
            rosSource = FindAnyObjectByType<RosSurveySource>();
            teleop = FindAnyObjectByType<TeleopController>();
            hub.MissionStateChanged += OnState;
            hub.Cleared += OnCleared;

            // Catch up on anything that arrived before we subscribed.
            if (hub.Map != null) OnMap(hub.Map);
            foreach (var b in hub.Bubbles.Values) OnBubble(b);
            foreach (var p in hub.Pins.Values) OnPin(p);
        }

        void OnDestroy()
        {
            if (hub != null)
            {
                hub.MapUpdated -= OnMap;
                hub.BubbleReceived -= OnBubble;
                hub.PinAdded -= OnPin;
                hub.ReadingReceived -= OnReading;
                hub.RobotPoseUpdated -= OnRobotPose;
                hub.MissionStateChanged -= OnState;
                hub.Cleared -= OnCleared;
            }
            foreach (var o in owned) if (o != null) Destroy(o);
            if (floorTex != null) Destroy(floorTex);
            if (root != null) Destroy(root.gameObject);
        }

        void Update()
        {
            // Link status / e-stop change without hub events, so refresh the status line twice a second.
            if (Time.unscaledTime >= nextStatus)
            {
                UpdateStatus();
                nextStatus = Time.unscaledTime + 0.5f;
            }

            if (XRSettings.isDeviceActive) return;
            var kb = Keyboard.current;
            if (kb != null && kb.cKey.wasPressedThisFrame) Recenter();

            var mouse = Mouse.current;
            if (!visible || mouse == null || !mouse.leftButton.wasPressedThisFrame || Camera.main == null) return;
            var ray = Camera.main.ScreenPointToRay(mouse.position.ReadValue());
            if (!TrySelect(ray)) Debug.Log("[Tabletop] click: no capture spot within reach");
        }

        // ---- public API ----

        /// <summary>Place the table in front of the viewer, level, facing them.</summary>
        public void Recenter()
        {
            if (root == null || viewer == null) return;
            var fwd = Vector3.ProjectOnPlane(viewer.forward, Vector3.up);
            if (fwd.sqrMagnitude < 1e-4f) fwd = Vector3.forward;
            fwd.Normalize();
            root.SetPositionAndRotation(viewer.position + fwd * distance + Vector3.down * belowEye, Quaternion.LookRotation(fwd));
        }

        /// <summary>
        /// Pick the capture spot nearest to where <paramref name="ray"/> hits the table surface (within
        /// SelectRadius). No colliders: the discs are tiny, so this is far easier to hit. Mouse now,
        /// controller ray later.
        /// </summary>
        public bool TrySelect(Ray ray)
        {
            if (!visible || root == null) return false;
            var plane = new Plane(root.up, mapRoot.position);
            if (!plane.Raycast(ray, out float dist)) return false;
            var hit = mapRoot.InverseTransformPoint(ray.GetPoint(dist));
            string best = null;
            float bestD = SelectRadius;
            foreach (var kv in bubbles)
            {
                var d = kv.Value.transform.localPosition - hit;
                d.y = 0f;
                if (d.magnitude < bestD) { bestD = d.magnitude; best = kv.Key; }
            }
            if (best == null) return false;
            Select(best);
            return true;
        }

        public void Select(string bubbleId)
        {
            Debug.Log($"[Tabletop] selected {bubbleId}");
            BubbleSelected?.Invoke(bubbleId);
        }

        /// <summary>Robot pose in the ROS map frame. Fed from readings for now; the ROS step feeds real TF.</summary>
        public void SetRobotPose(float x, float y, float yaw)
        {
            robotPos = new Vector2(x, y);
            robotYaw = yaw;
            robot.SetActive(true);
            robot.transform.localPosition = BoardPos(x, y);
            robot.transform.localRotation = RosCoords.ToUnityRotation(yaw);
            AddTrailPoint(x, y);
        }

        // ---- hub events ----

        void OnMap(MapGrid m)
        {
            map = m;
            if (floorTex != null) Destroy(floorTex);
            floorTex = m.ToTexture(unknown: new Color32(45, 47, 52, 255)); // opaque: Unlit ignores alpha
            floorTex.filterMode = FilterMode.Bilinear;
            floor.GetComponent<MeshRenderer>().sharedMaterial.mainTexture = floorTex;
            Relayout();
        }

        void OnBubble(Bubble b)
        {
            if (bubbles.ContainsKey(b.BubbleId)) { Move(bubbles[b.BubbleId].transform, b.X, b.Y); return; }
            var disc = Primitive(PrimitiveType.Cylinder, $"Bubble {b.BubbleId}", BubbleColor);
            disc.transform.localScale = new Vector3(0.035f, 0.002f, 0.035f);
            bubbles[b.BubbleId] = disc;
            Track(disc.transform, b.X, b.Y);
            StartCoroutine(Pop(disc.transform));
        }

        void OnPin(Pin p)
        {
            if (pins.ContainsKey(p.PinId)) return;
            var color = p.Invasive ? Invasive : Native;
            var pin = new GameObject($"Pin {p.PinId}").transform;
            pin.SetParent(mapRoot, false);

            float h = p.Invasive ? 0.045f : 0.03f;
            var stalk = Primitive(PrimitiveType.Cylinder, "Stalk", color * 0.7f, parent: pin);
            stalk.transform.localScale = new Vector3(0.003f, h / 2f, 0.003f); // cylinder is 2 units tall
            stalk.transform.localPosition = Vector3.up * (h / 2f);
            var head = Primitive(PrimitiveType.Sphere, "Head", color, parent: pin);
            head.transform.localScale = Vector3.one * (p.Invasive ? 0.016f : 0.011f);
            head.transform.localPosition = Vector3.up * h;

            if (p.Invasive || labelNatives)
            {
                var label = WorldUI.MakeLabel(pin, p.Label, color, 0.012f).transform;
                label.localPosition = Vector3.up * (h + 0.012f);
                label.localRotation = Quaternion.identity; // faces the viewer, like the board
            }

            pins[p.PinId] = pin.gameObject;
            Track(pin, p.X, p.Y);
            StartCoroutine(Pop(pin));
            UpdateStatus();
        }

        void OnRobotPose(Vector3 pose)
        {
            lastRealPose = Time.unscaledTime;
            SetRobotPose(pose.x, pose.y, pose.z);
        }

        void OnReading(Reading r)
        {
            // Readings are stamped with the robot's position: a fallback when no real /pose is coming in.
            if (Time.unscaledTime - lastRealPose < 2f) return;
            float yaw = robotYaw;
            if (robotPos.HasValue)
            {
                var d = new Vector2(r.X, r.Y) - robotPos.Value;
                if (d.sqrMagnitude > 0.02f * 0.02f) yaw = Mathf.Atan2(d.y, d.x);
            }
            SetRobotPose(r.X, r.Y, yaw);
        }

        void OnState(MissionState _) => UpdateStatus();

        void OnCleared()
        {
            foreach (var go in bubbles.Values) Destroy(go);
            foreach (var go in pins.Values) Destroy(go);
            bubbles.Clear();
            pins.Clear();
            placed.Clear();
            robotPos = null;
            robot.SetActive(false);
            trailRos.Clear();
            RedrawTrail();
            map = null;
            Relayout();
            UpdateStatus();
        }

        // ---- layout ----

        // ---- robot trail (where the robot has driven this mission) ----

        const float TrailStep = 0.05f; // map meters between recorded points
        const int TrailMax = 2000;
        readonly List<Vector2> trailRos = new List<Vector2>();
        LineRenderer trail;

        void AddTrailPoint(float x, float y)
        {
            var p = new Vector2(x, y);
            if (trailRos.Count > 0 && (trailRos[trailRos.Count - 1] - p).sqrMagnitude < TrailStep * TrailStep) return;
            trailRos.Add(p);
            if (trailRos.Count > TrailMax) trailRos.RemoveRange(0, trailRos.Count - TrailMax);
            RedrawTrail();
        }

        void RedrawTrail()
        {
            if (trail == null) return;
            trail.positionCount = trailRos.Count;
            for (int i = 0; i < trailRos.Count; i++)
                trail.SetPosition(i, BoardPos(trailRos[i].x, trailRos[i].y) + Vector3.up * 0.002f);
        }

        Vector3 BoardPos(float x, float y) =>
            (RosCoords.ToUnity(x, y) - RosCoords.ToUnity(center.x, center.y)) * scale;

        void Track(Transform t, float x, float y)
        {
            placed.Add((t, new Vector2(x, y)));
            t.localPosition = BoardPos(x, y);
        }

        void Move(Transform t, float x, float y)
        {
            int i = placed.FindIndex(e => e.t == t);
            if (i >= 0) placed[i] = (t, new Vector2(x, y));
            t.localPosition = BoardPos(x, y);
        }

        /// <summary>Recompute scale/center from the map, resize the slab and floor, re-place every marker.</summary>
        void Relayout()
        {
            float spanX = map != null ? map.WidthMeters : DefaultSpan;   // along ROS x
            float spanY = map != null ? map.HeightMeters : DefaultSpan;  // along ROS y
            center = map != null ? map.CenterRos : Vector2.zero;
            scale = boardSize / Mathf.Max(spanX, spanY);

            // ROS x -> Unity z (depth), ROS y -> Unity x (width).
            slab.transform.localScale = new Vector3(spanY * scale + 2 * Margin, SlabThickness, spanX * scale + 2 * Margin);
            slab.transform.localPosition = Vector3.down * (SlabThickness / 2f);
            HalfExtents = new Vector2(slab.transform.localScale.x / 2f, slab.transform.localScale.z / 2f);
            LayoutChanged?.Invoke();

            floor.SetActive(map != null);
            if (map != null)
            {
                var mf = floor.GetComponent<MeshFilter>();
                if (mf.sharedMesh != null) { owned.Remove(mf.sharedMesh); Destroy(mf.sharedMesh); }
                mf.sharedMesh = FloorMesh();
            }

            placed.RemoveAll(e => e.t == null);
            foreach (var (t, ros) in placed) t.localPosition = BoardPos(ros.x, ros.y);
            if (robotPos.HasValue) robot.transform.localPosition = BoardPos(robotPos.Value.x, robotPos.Value.y);
            RedrawTrail();

            status.transform.localPosition = new Vector3(0f, 0.005f, -(spanX * scale / 2f + Margin + 0.01f));
        }

        /// <summary>Quad whose corners are the map's ROS corners, so texel (col, row) lands exactly on its cell.</summary>
        Mesh FloorMesh()
        {
            float x0 = map.OriginX, y0 = map.OriginY, x1 = x0 + map.WidthMeters, y1 = y0 + map.HeightMeters;
            var lift = Vector3.up * 0.001f;
            var mesh = new Mesh
            {
                name = "Floor",
                vertices = new[] { BoardPos(x0, y0) + lift, BoardPos(x1, y0) + lift, BoardPos(x1, y1) + lift, BoardPos(x0, y1) + lift },
                uv = new[] { new Vector2(0, 0), new Vector2(1, 0), new Vector2(1, 1), new Vector2(0, 1) },
                triangles = new[] { 0, 1, 2, 0, 2, 3 }, // material renders both faces
            };
            mesh.RecalculateBounds();
            owned.Add(mesh);
            return mesh;
        }

        // ---- building ----

        void BuildStatic()
        {
            root = new GameObject("Tabletop").transform; // scene root: moved by Recenter, not by this GameObject
            root.gameObject.SetActive(visible);
            mapRoot = new GameObject("Map").transform;
            mapRoot.SetParent(root, false);

            slab = Primitive(PrimitiveType.Cube, "Slab", SlabColor, parent: root);

            floor = new GameObject("Floor");
            floor.transform.SetParent(mapRoot, false);
            floor.AddComponent<MeshFilter>();
            floor.AddComponent<MeshRenderer>();
            var floorMat = WorldUI.Tinted(material, null, Color.white);
            owned.Add(floorMat);
            WorldUI.Apply(floor, floorMat);

            robot = new GameObject("Robot");
            robot.transform.SetParent(mapRoot, false);
            var body = Primitive(PrimitiveType.Cube, "Body", RobotColor, parent: robot.transform);
            body.transform.localScale = new Vector3(0.025f, 0.012f, 0.03f);
            body.transform.localPosition = Vector3.up * 0.006f;
            var nose = Primitive(PrimitiveType.Cube, "Nose", Color.white, parent: robot.transform);
            nose.transform.localScale = new Vector3(0.008f, 0.014f, 0.01f);
            nose.transform.localPosition = new Vector3(0f, 0.007f, 0.016f); // +z = robot forward
            robot.SetActive(false);

            var trailGo = new GameObject("Trail");
            trailGo.transform.SetParent(mapRoot, false);
            trail = trailGo.AddComponent<LineRenderer>();
            trail.useWorldSpace = false; // MapRoot-local, like the markers
            trail.widthMultiplier = 0.003f;
            trail.numCornerVertices = 2;
            trail.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            trail.receiveShadows = false;
            var trailMat = WorldUI.Tinted(material, null, new Color(1f, 0.75f, 0.2f));
            owned.Add(trailMat);
            trail.sharedMaterial = trailMat;
            trail.positionCount = 0;

            status = WorldUI.MakeLabel(root, "", Color.white, 0.025f, TextAnchor.UpperCenter);
            status.transform.localRotation = Quaternion.Euler(60f, 0f, 0f); // lie back toward the viewer

            Relayout();
            UpdateStatus();
        }

        void UpdateStatus()
        {
            if (status == null) return;
            int invasive = hub.Pins.Values.Count(p => p.Invasive);
            int total = hub.Pins.Count;
            string state = hub.State == MissionState.Unknown ? "WAITING" : hub.State.ToString();
            string line1 = $"{state}   ·   invasives {invasive}   ·   plants {total}   ·   spots {hub.Bubbles.Count}";
            string link = rosSource != null ? rosSource.StatusText : "FAKE";
            string estop = teleop != null && teleop.EStopped ? "   ·   <color=#ff4433>E-STOP</color>" : "";
            var text = $"{line1}\n<size=36>{link}{estop}</size>";
            foreach (var provider in StatusProviders)
            {
                string extra = provider();
                if (!string.IsNullOrEmpty(extra)) text += $"\n<size=36>{extra}</size>";
            }
            status.text = text;
        }

        GameObject Primitive(PrimitiveType type, string name, Color color, Transform parent = null)
        {
            var go = GameObject.CreatePrimitive(type);
            go.name = name;
            Destroy(go.GetComponent<Collider>());
            go.transform.SetParent(parent != null ? parent : mapRoot, false);
            var mat = WorldUI.Tinted(material, null, color);
            owned.Add(mat);
            WorldUI.Apply(go, mat);
            return go;
        }

        IEnumerator Pop(Transform t)
        {
            var target = t.localScale;
            for (float k = 0f; k < 1f; k += Time.deltaTime / 0.3f)
            {
                if (t == null) yield break;
                float e = 1f + 2.2f * Mathf.Pow(k - 1f, 3) + 1.2f * Mathf.Pow(k - 1f, 2); // ease-out-back
                t.localScale = target * e;
                yield return null;
            }
            if (t != null) t.localScale = target;
        }

#if UNITY_EDITOR
        void Reset()
        {
            hub = FindAnyObjectByType<SurveyHub>();
            material = WorldUI.UnlitMaterialAsset();
        }
#endif
    }
}
