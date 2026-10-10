using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR;

namespace Understory
{
    /// <summary>
    /// Street-View-style hops between bubbles: in the bubble view, an arrow on the floor points toward each
    /// nearby capture spot (true bearing in the map frame, labeled with id + distance). Pick one with the
    /// controller ray (ControllerPointer) or a mouse click in the editor to jump there.
    /// </summary>
    public class BubbleNavigator : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [SerializeField] BubbleRingBuilder ring;
        [SerializeField] Material material;
        [Tooltip("Only neighbors closer than this (map meters) get an arrow.")]
        [SerializeField] float maxDistance = 6f;
        [SerializeField] float arrowRadius = 1.1f;
        [Tooltip("How far below the eyes the floor arrows sit.")]
        [SerializeField] float floorDrop = 1.25f;
        [SerializeField] float pickRadius = 0.25f;
        [Tooltip("Street View style: only the nearest spot per direction; a farther spot within this many degrees is " +
                 "reached through the nearer one (otherwise their arrows and labels overlap).")]
        [SerializeField] float minSeparationDeg = 20f;

        static readonly Color ArrowColor = new Color(0.3f, 0.9f, 1f);

        Transform root;
        string builtFor;
        int builtCount;
        readonly List<(Transform t, string id)> arrows = new List<(Transform, string)>();
        Material arrowMat;

        bool Showing => ring != null && ring.Visible && ring.CurrentBubbleId != null;
        public bool IsShowing => Showing;

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (ring == null) ring = FindAnyObjectByType<BubbleRingBuilder>();
            if (material == null) material = WorldUI.FallbackUnlit();
            arrowMat = WorldUI.Tinted(material, null, ArrowColor);
            root = new GameObject("BubbleNavigator").transform;
            if (hub != null) hub.Cleared += Clear;
        }

        void OnDestroy()
        {
            if (hub != null) hub.Cleared -= Clear;
            if (arrowMat != null) Destroy(arrowMat);
            if (root != null) Destroy(root.gameObject);
        }

        void LateUpdate()
        {
            if (hub == null || ring == null) return;
            bool show = Showing;
            root.gameObject.SetActive(show);
            if (!show) return;

            // Rebuild when the bubble changes or new bubbles arrive.
            if (builtFor != ring.CurrentBubbleId || builtCount != hub.Bubbles.Count) Build();

            var cam = Camera.main;
            if (cam != null) root.SetPositionAndRotation(cam.transform.position, Quaternion.identity); // map-aligned, like the ring

            if (XRSettings.isDeviceActive) return;
            var mouse = Mouse.current;
            if (mouse != null && mouse.leftButton.wasPressedThisFrame && cam != null)
                TrySelect(cam.ScreenPointToRay(mouse.position.ReadValue()));
        }

        /// <summary>Jump to the bubble whose arrow the ray points at (on the arrows' floor plane).</summary>
        public bool TrySelect(Ray ray)
        {
            if (!Showing || arrows.Count == 0) return false;
            var plane = new Plane(Vector3.up, root.position + Vector3.down * floorDrop);
            if (!plane.Raycast(ray, out float d)) return false;
            var hit = ray.GetPoint(d);
            string best = null;
            float bestD = pickRadius;
            foreach (var (t, id) in arrows)
            {
                float dist = Vector3.Distance(t.position, hit);
                if (dist < bestD) { bestD = dist; best = id; }
            }
            if (best == null) return false;
            Debug.Log($"[Navigator] {ring.CurrentBubbleId} -> {best}");
            ring.Show(best);
            Haptics.Buzz(this, 0.25f, 0.05f, OVRInput.Controller.RTouch);
            return true;
        }

        void Clear()
        {
            foreach (var (t, _) in arrows) if (t != null) Destroy(t.gameObject);
            arrows.Clear();
            builtFor = null;
            builtCount = 0;
        }

        void Build()
        {
            Clear();
            builtFor = ring.CurrentBubbleId;
            builtCount = hub.Bubbles.Count;
            if (!hub.Bubbles.TryGetValue(builtFor, out var here)) return;

            // Nearest first, so a nearer spot claims its direction before a farther one behind it.
            var neighbors = new List<(Bubble b, float dist, float bearing)>();
            foreach (var other in hub.Bubbles.Values)
            {
                if (other.BubbleId == here.BubbleId) continue;
                float ox = other.X - here.X, oy = other.Y - here.Y;
                float d = Mathf.Sqrt(ox * ox + oy * oy);
                if (d <= maxDistance && d >= 0.05f) neighbors.Add((other, d, Mathf.Atan2(oy, ox)));
            }
            neighbors.Sort((a, c) => a.dist.CompareTo(c.dist));
            var taken = new List<float>();

            foreach (var (other, dist, bearing) in neighbors)
            {
                bool crowded = false;
                foreach (var t in taken)
                    if (Mathf.Abs(Mathf.DeltaAngle(t * Mathf.Rad2Deg, bearing * Mathf.Rad2Deg)) < minSeparationDeg) crowded = true;
                if (crowded) continue;
                taken.Add(bearing);
                var dir = RosCoords.ToUnityDirection(bearing);

                var arrow = new GameObject($"To {other.BubbleId}").transform;
                arrow.SetParent(root, false);
                arrow.localPosition = dir * arrowRadius + Vector3.down * floorDrop;
                arrow.localRotation = RosCoords.ToUnityRotation(bearing); // +z points toward the neighbor

                // Chevron: two bars in a V pointing along +z.
                for (int side = -1; side <= 1; side += 2)
                {
                    var bar = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    Destroy(bar.GetComponent<Collider>());
                    bar.transform.SetParent(arrow, false);
                    bar.transform.localScale = new Vector3(0.04f, 0.01f, 0.22f);
                    bar.transform.localPosition = new Vector3(side * 0.06f, 0f, 0f);
                    bar.transform.localRotation = Quaternion.Euler(0f, -side * 35f, 0f);
                    WorldUI.Apply(bar, arrowMat);
                }

                var label = WorldUI.MakeLabel(root, $"{other.BubbleId}\n<size=32>{dist:F1} m</size>", ArrowColor, 0.06f).transform;
                label.GetComponent<TextMesh>().richText = true;
                label.position = arrow.position + Vector3.up * 0.12f;
                label.rotation = Quaternion.LookRotation(dir); // readable from the center
                label.SetParent(arrow, true);

                arrows.Add((arrow, other.BubbleId));
            }
        }

#if UNITY_EDITOR
        void Reset()
        {
            hub = FindAnyObjectByType<SurveyHub>();
            ring = FindAnyObjectByType<BubbleRingBuilder>();
            material = WorldUI.UnlitMaterialAsset();
        }
#endif
    }
}
