using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Understory
{
    /// <summary>
    /// Immersive 360° bubble view. Wraps one bubble around the viewer:
    ///  - default: each frame as a curved panel at its yaw (reprojected pinhole -> cylinder), so pins line up, or
    ///  - the stitched pano ("&lt;bubble_id&gt;/pano") as one cylinder when no frames arrived (or preferPano).
    /// It's a band, not a sphere; a dark gradient sphere fills above and below.
    /// Pins for the bubble float at their bearing.
    ///
    /// Editor keys: [ / ] previous/next bubble, R toggle preferPano.
    /// </summary>
    public class BubbleRingBuilder : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [Tooltip("URP/Unlit, Render Face = Both. Auto-created when the component is added.")]
        [SerializeField] Material panelMaterial;
        [Tooltip("Ring center follows this position (not rotation). Defaults to the main camera.")]
        [SerializeField] Transform follow;
        [SerializeField] float radius = 3f;
        [Tooltip("Switch to each new bubble as it arrives (live mode).")]
        [SerializeField] bool autoShowLatest = true;
        [Tooltip("Show the stitched pano even when frames exist. Off by default: frames carry exact yaws, " +
                 "while stitcher output has no known start heading, so pins can't be placed on it reliably.")]
        [SerializeField] bool preferPano;
        [Tooltip("Only show the middle of each frame (one yaw step wide) so panels don't overlap.")]
        [SerializeField] bool cropToSpacing = true;
        [SerializeField] bool showPins = true;
        [SerializeField] int columnsPerPanel = 8;
        [SerializeField] int panoColumns = 96;
        [SerializeField] Color placeholderColor = new Color(0.12f, 0.12f, 0.14f);

        // Assumed until the real image arrives (640x480).
        const float DefaultAspect = 0.75f;
        // Detections aren't localized vertically in the contract; float pins just below eye level.
        const float PinElevationDeg = -8f;

        public string CurrentBubbleId { get; private set; }

        bool visible = true;
        /// <summary>Hidden still tracks bubbles/images, so showing it again is instant.</summary>
        public bool Visible
        {
            get => visible;
            set { visible = value; if (content != null) content.SetActive(value); }
        }

        GameObject content;
        readonly Dictionary<int, GameObject> panels = new Dictionary<int, GameObject>();
        readonly List<Object> owned = new List<Object>(); // runtime meshes/materials to destroy
        Texture2D gradient;

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (follow == null && Camera.main != null) follow = Camera.main.transform;
            if (panelMaterial == null)
            {
                panelMaterial = WorldUI.FallbackUnlit();
                Debug.LogWarning("[BubbleRing] No panel material assigned; created one at runtime (may be stripped in builds).");
            }
            if (hub == null) { Debug.LogError("[BubbleRing] No SurveyHub in scene."); enabled = false; return; }

            hub.BubbleReceived += OnBubble;
            hub.BubbleImageReceived += OnImage;
            hub.PinAdded += OnPin;
            hub.Cleared += OnCleared;
        }

        void OnDestroy()
        {
            if (hub != null)
            {
                hub.BubbleReceived -= OnBubble;
                hub.BubbleImageReceived -= OnImage;
                hub.PinAdded -= OnPin;
                hub.Cleared -= OnCleared;
            }
            ClearContent();
            if (gradient != null) Destroy(gradient);
        }

        void LateUpdate()
        {
            // Content is a scene root: only it moves, so components sharing this GameObject stay put.
            if (content != null)
            {
                content.transform.position = follow != null ? follow.position : transform.position;
                content.transform.rotation = Quaternion.identity; // stay aligned with the map frame
            }

            var kb = Keyboard.current;
            if (kb == null) return;
            if (kb.rightBracketKey.wasPressedThisFrame) Step(+1);
            if (kb.leftBracketKey.wasPressedThisFrame) Step(-1);
            if (kb.rKey.wasPressedThisFrame) { preferPano = !preferPano; Rebuild(); }
        }

        // ---- public API (controllers / map twin call these) ----

        public void Show(string bubbleId)
        {
            CurrentBubbleId = bubbleId;
            Rebuild();
        }

        public void Hide()
        {
            CurrentBubbleId = null;
            ClearContent();
        }

        public void Step(int dir)
        {
            if (hub.Bubbles.Count == 0) return;
            var ids = new List<string>(hub.Bubbles.Keys);
            ids.Sort(System.StringComparer.Ordinal);
            int i = CurrentBubbleId == null ? -1 : ids.IndexOf(CurrentBubbleId);
            i = ((i + dir) % ids.Count + ids.Count) % ids.Count;
            Show(ids[i]);
        }

        // ---- hub events ----

        void OnBubble(Bubble b)
        {
            if (autoShowLatest || CurrentBubbleId == null || b.BubbleId == CurrentBubbleId) Show(b.BubbleId);
        }

        void OnImage(string frameId, Texture2D tex)
        {
            if (CurrentBubbleId == null || !frameId.StartsWith(CurrentBubbleId + "/")) return;
            string suffix = frameId.Substring(CurrentBubbleId.Length + 1);
            var b = hub.Bubbles[CurrentBubbleId];
            if (suffix == "pano")
            {
                if (UsePano(b)) Rebuild();
                return;
            }
            if (!int.TryParse(suffix, out int index)) return;
            if (!panels.ContainsKey(index))
            {
                if (!UsePano(b)) Rebuild(); // first frame after showing the pano: switch to the ring
                return;
            }
            var frame = b.Frames.Find(f => f.Index == index);
            if (frame == null) return;
            Destroy(panels[index]);
            panels[index] = BuildPanel(b, frame, tex);
        }

        void OnPin(Pin p)
        {
            if (showPins && content != null && p.BubbleId == CurrentBubbleId) BuildPinMarker(p);
        }

        void OnCleared()
        {
            CurrentBubbleId = null;
            ClearContent();
        }

        // ---- building ----

        void Rebuild()
        {
            ClearContent();
            if (CurrentBubbleId == null || !hub.Bubbles.TryGetValue(CurrentBubbleId, out var b)) return;

            content = new GameObject($"Bubble {b.BubbleId}");
            content.SetActive(visible);
            content.transform.SetPositionAndRotation(follow != null ? follow.position : transform.position, Quaternion.identity);
            BuildBackdrop();

            if (UsePano(b))
                BuildPano(hub.BubbleImages[$"{b.BubbleId}/pano"]);
            else
                foreach (var f in b.Frames)
                {
                    hub.BubbleImages.TryGetValue(f.ImageFrameId(b.BubbleId), out var tex);
                    panels[f.Index] = BuildPanel(b, f, tex);
                }

            if (showPins)
                foreach (var p in hub.Pins.Values)
                    if (p.BubbleId == b.BubbleId) BuildPinMarker(p);
        }

        /// <summary>Frame ring by default (exact yaws); the pano only if asked for or no frame images arrived.</summary>
        bool UsePano(Bubble b)
        {
            if (!hub.BubbleImages.ContainsKey($"{b.BubbleId}/pano")) return false;
            if (preferPano) return true;
            foreach (var f in b.Frames)
                if (hub.BubbleImages.ContainsKey(f.ImageFrameId(b.BubbleId))) return false;
            return true;
        }

        void ClearContent()
        {
            panels.Clear();
            foreach (var o in owned) if (o != null) Destroy(o);
            owned.Clear();
            if (content != null) Destroy(content);
            content = null;
        }

        /// <summary>
        /// One frame as a cylinder segment. Each vertex at angle d from the frame's center gets the exact
        /// pinhole texture coordinate, so straight-on content isn't stretched. Larger ROS yaw = further left.
        /// </summary>
        GameObject BuildPanel(Bubble b, BubbleFrame f, Texture2D tex)
        {
            float hfov = b.Hfov > 0.01f ? b.Hfov : 1.22f;
            float aspect = tex != null ? tex.height / (float)tex.width : DefaultAspect;
            float tanH = Mathf.Tan(hfov / 2f), tanV = tanH * aspect;
            float halfSpan = hfov / 2f;
            if (cropToSpacing && b.Frames.Count > 1)
                halfSpan = Mathf.Min(halfSpan, Mathf.PI / b.Frames.Count * 1.02f); // tiny overlap hides seams

            int cols = Mathf.Max(2, columnsPerPanel);
            var verts = new Vector3[(cols + 1) * 2];
            var uvs = new Vector2[verts.Length];
            for (int i = 0; i <= cols; i++)
            {
                float d = -halfSpan + 2f * halfSpan * i / cols;
                var dir = RosCoords.ToUnityDirection(f.Yaw + d) * radius;
                float h = radius * Mathf.Cos(d) * tanV; // keeps the image's top/bottom edges exact
                float u = 0.5f - Mathf.Tan(d) / (2f * tanH);
                verts[2 * i] = dir + Vector3.down * h;
                verts[2 * i + 1] = dir + Vector3.up * h;
                uvs[2 * i] = new Vector2(u, 0f);
                uvs[2 * i + 1] = new Vector2(u, 1f);
            }
            var go = MakeMeshObject($"Frame {f.Index}", verts, uvs, BandTriangles(cols));
            SetLook(go, tex, tex == null ? placeholderColor : Color.white);
            return go;
        }

        /// <summary>Full 360° cylinder. Pano convention (fake_data/README.md): u = (pi - yaw) / 2pi.</summary>
        void BuildPano(Texture2D pano)
        {
            int cols = Mathf.Max(12, panoColumns);
            float half = Mathf.PI * radius * pano.height / pano.width; // arc length 2*pi*r maps to width
            var verts = new Vector3[(cols + 1) * 2];
            var uvs = new Vector2[verts.Length];
            for (int i = 0; i <= cols; i++)
            {
                float yaw = -Mathf.PI + 2f * Mathf.PI * i / cols;
                var dir = RosCoords.ToUnityDirection(yaw) * radius;
                float u = (Mathf.PI - yaw) / (2f * Mathf.PI);
                verts[2 * i] = dir + Vector3.down * half;
                verts[2 * i + 1] = dir + Vector3.up * half;
                uvs[2 * i] = new Vector2(u, 0f);
                uvs[2 * i + 1] = new Vector2(u, 1f);
            }
            SetLook(MakeMeshObject("Pano", verts, uvs, BandTriangles(cols)), pano, Color.white);
        }

        /// <summary>Columns ordered by increasing ROS yaw (right to left as seen from the center), facing inward.</summary>
        static int[] BandTriangles(int cols)
        {
            var tris = new int[cols * 6];
            for (int i = 0; i < cols; i++)
            {
                int bl = 2 * i, tl = bl + 1, bl2 = bl + 2, tl2 = bl + 3;
                tris[6 * i + 0] = tl2; tris[6 * i + 1] = tl; tris[6 * i + 2] = bl;
                tris[6 * i + 3] = tl2; tris[6 * i + 4] = bl; tris[6 * i + 5] = bl2;
            }
            return tris;
        }

        /// <summary>Inward lat-long sphere with a dark vertical gradient behind the band.</summary>
        void BuildBackdrop()
        {
            const int lat = 16, lon = 32;
            float r = radius * 1.5f;
            var verts = new List<Vector3>();
            var uvs = new List<Vector2>();
            for (int j = 0; j <= lat; j++)
            {
                float phi = Mathf.PI * j / lat - Mathf.PI / 2f;
                for (int i = 0; i <= lon; i++)
                {
                    float th = 2f * Mathf.PI * i / lon;
                    verts.Add(new Vector3(Mathf.Cos(phi) * Mathf.Sin(th), Mathf.Sin(phi), Mathf.Cos(phi) * Mathf.Cos(th)) * r);
                    uvs.Add(new Vector2(i / (float)lon, j / (float)lat));
                }
            }
            var tris = new List<int>();
            for (int j = 0; j < lat; j++)
            for (int i = 0; i < lon; i++)
            {
                int a = j * (lon + 1) + i, c = a + lon + 1;
                tris.AddRange(new[] { a, c, a + 1, a + 1, c, c + 1 });
            }
            var go = MakeMeshObject("Backdrop", verts.ToArray(), uvs.ToArray(), tris.ToArray());
            SetLook(go, Gradient(), Color.white);
        }

        Texture2D Gradient()
        {
            if (gradient != null) return gradient;
            const int n = 64;
            gradient = new Texture2D(1, n, TextureFormat.RGBA32, false) { wrapMode = TextureWrapMode.Clamp, name = "BubbleGradient" };
            var floor = new Color(0.06f, 0.05f, 0.04f);
            var horizon = new Color(0.16f, 0.18f, 0.17f);
            var sky = new Color(0.03f, 0.04f, 0.07f);
            for (int j = 0; j < n; j++)
            {
                float v = j / (n - 1f);
                gradient.SetPixel(0, j, v < 0.5f ? Color.Lerp(floor, horizon, v * 2f) : Color.Lerp(horizon, sky, (v - 0.5f) * 2f));
            }
            gradient.Apply();
            return gradient;
        }

        void BuildPinMarker(Pin p)
        {
            float rr = radius * 0.92f;
            var dir = RosCoords.ToUnityDirection(p.Yaw);
            var pos = dir * rr + Vector3.up * (rr * Mathf.Tan(PinElevationDeg * Mathf.Deg2Rad));
            var color = p.Invasive ? new Color(0.95f, 0.2f, 0.2f) : new Color(0.25f, 0.9f, 0.35f);

            var marker = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            marker.name = $"Pin {p.PinId}";
            Destroy(marker.GetComponent<Collider>());
            marker.transform.SetParent(content.transform, false);
            marker.transform.localPosition = pos;
            marker.transform.localScale = Vector3.one * 0.08f;
            SetLook(marker, null, color);

            var label = WorldUI.MakeLabel(marker.transform, $"{p.Label}\n{p.Confidence:P0}", color, 0.17f).transform;
            label.position = marker.transform.position + Vector3.up * 0.12f;
            label.rotation = Quaternion.LookRotation(dir); // readable from the center
        }

        GameObject MakeMeshObject(string name, Vector3[] verts, Vector2[] uvs, int[] tris)
        {
            var mesh = new Mesh { name = name, vertices = verts, uv = uvs, triangles = tris };
            mesh.RecalculateBounds();
            owned.Add(mesh);
            var go = new GameObject(name);
            go.transform.SetParent(content.transform, false);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            go.AddComponent<MeshRenderer>();
            return go;
        }

        void SetLook(GameObject go, Texture tex, Color color)
        {
            var mat = WorldUI.Tinted(panelMaterial, tex, color);
            owned.Add(mat);
            WorldUI.Apply(go, mat);
        }

#if UNITY_EDITOR
        // Runs when the component is added: wire the hub and create a real material asset so the
        // shader is included in Quest builds (Shader.Find alone can get stripped).
        void Reset()
        {
            hub = FindAnyObjectByType<SurveyHub>();
            panelMaterial = WorldUI.UnlitMaterialAsset();
        }
#endif
    }
}
