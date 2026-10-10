using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.Rendering;

namespace Understory
{
    /// <summary>
    /// The AMD splat / point cloud (splat/README.md: scene.splat, ROS map frame) as a 3D miniature of the
    /// surveyed place on the tabletop, drawn with the SplatBillboard shader (camera-facing discs, no sorting).
    ///
    /// File lookup for the current mission (hub.MissionId, else fallbackMissionId):
    ///   editor: &lt;repo&gt;/splat/out/&lt;id&gt;/scene.splat, then the mission folder's scene.splat
    ///   Quest:  StreamingAssets/splat/&lt;id&gt;/scene.splat, then the mission folder's (copied by the build step)
    /// Toggle: panel "3D model" or M in the editor.
    /// </summary>
    public class SplatView : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [SerializeField] TabletopMap table;
        [SerializeField] MissionPanel panel;
        [Tooltip("Understory/SplatBillboard material. Auto-created when the component is added.")]
        [SerializeField] Material material;
        [SerializeField] string fallbackMissionId = "m1";
        [SerializeField] int maxSplats = 150000;
        [SerializeField] float minAlpha = 0.3f;
        [SerializeField] float maxRadius = 0.08f;

        const int BytesPerSplat = 32;

        GameObject model;
        Mesh mesh;
        string loadedFor, status;
        bool shown, loading;

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (panel == null) panel = FindAnyObjectByType<MissionPanel>();
            if (table == null) { enabled = false; return; }
            if (material == null)
            {
                var shader = Shader.Find("Understory/SplatBillboard");
                if (shader != null) material = new Material(shader);
                Debug.LogWarning("[SplatView] No material assigned; created one at runtime (may be stripped in builds).");
            }
            if (panel != null) panel.Pressed += OnPanel;
            table.LayoutChanged += Place;
            table.StatusProviders.Add(Summary);
        }

        void OnDestroy()
        {
            if (panel != null) panel.Pressed -= OnPanel;
            if (table != null) { table.LayoutChanged -= Place; table.StatusProviders.Remove(Summary); }
            if (mesh != null) Destroy(mesh);
        }

        void Update()
        {
            var kb = Keyboard.current;
            if (kb != null && kb.mKey.wasPressedThisFrame) Toggle();
        }

        void OnPanel(string keyword)
        {
            if (keyword == MissionPanel.ModelKeyword) Toggle();
        }

        public void Toggle()
        {
            shown = !shown;
            string id = hub != null && !string.IsNullOrEmpty(hub.MissionId) ? hub.MissionId : fallbackMissionId;
            if (shown && loadedFor != id && !loading) StartCoroutine(Load(id));
            if (model != null) model.SetActive(shown);
        }

        IEnumerator Load(string missionId)
        {
            loading = true;
            status = "loading...";
            byte[] bytes = null;
            foreach (var (root, rel) in Candidates(missionId))
            {
                yield return MissionFiles.LoadBytes(root, rel, b => bytes = b);
                if (bytes != null) break;
            }
            loading = false;
            loadedFor = missionId;
            if (bytes == null)
            {
                status = $"none for {missionId} (splat/run.sh, or tools/fake_splat.py)";
                yield break;
            }
            Build(bytes);
            status = $"{mesh.vertexCount / 4:N0} splats ({missionId})";
            Debug.Log($"[SplatView] {status}");
        }

        static IEnumerable<(string root, string rel)> Candidates(string id)
        {
#if UNITY_EDITOR
            yield return (System.IO.Path.GetFullPath(System.IO.Path.Combine(Application.dataPath, "..", "..", "splat", "out", id)), "scene.splat");
#else
            yield return (Application.streamingAssetsPath + "/splat/" + id, "scene.splat");
#endif
            yield return (MissionFiles.Root(id), "scene.splat");
        }

        void Build(byte[] bytes)
        {
            int n = Math.Min(bytes.Length / BytesPerSplat, maxSplats);
            var verts = new List<Vector3>(n * 4);
            var colors = new List<Color32>(n * 4);
            var corners = new List<Vector2>(n * 4);
            var radii = new List<Vector2>(n * 4);
            var tris = new List<int>(n * 6);
            var cornerSet = new[] { new Vector2(-1, -1), new Vector2(1, -1), new Vector2(1, 1), new Vector2(-1, 1) };

            for (int i = 0; i < n; i++)
            {
                int o = i * BytesPerSplat;
                byte a = bytes[o + 27];
                if (a < minAlpha * 255) continue;
                // ROS map frame -> Unity, through the one conversion.
                var center = RosCoords.ToUnity(BitConverter.ToSingle(bytes, o), BitConverter.ToSingle(bytes, o + 4), BitConverter.ToSingle(bytes, o + 8));
                float sx = BitConverter.ToSingle(bytes, o + 12), sy = BitConverter.ToSingle(bytes, o + 16), sz = BitConverter.ToSingle(bytes, o + 20);
                // Discs ignore orientation: use the middle of the three axes so needle-like splats don't balloon.
                float r = Mathf.Min(Median(sx, sy, sz) * 2f, maxRadius);
                var c = new Color32(bytes[o + 24], bytes[o + 25], bytes[o + 26], 255);

                int baseIndex = verts.Count;
                for (int k = 0; k < 4; k++)
                {
                    verts.Add(center);
                    colors.Add(c);
                    corners.Add(cornerSet[k]);
                    radii.Add(new Vector2(r, 0f));
                }
                tris.Add(baseIndex); tris.Add(baseIndex + 1); tris.Add(baseIndex + 2);
                tris.Add(baseIndex); tris.Add(baseIndex + 2); tris.Add(baseIndex + 3);
            }

            if (mesh != null) Destroy(mesh);
            mesh = new Mesh { name = "Splats", indexFormat = IndexFormat.UInt32 };
            mesh.SetVertices(verts);
            mesh.SetColors(colors);
            mesh.SetUVs(0, corners);
            mesh.SetUVs(1, radii);
            mesh.SetTriangles(tris, 0);
            mesh.RecalculateBounds();
            var b = mesh.bounds;
            b.Expand(maxRadius * 4f); // vertices sit at centers; discs extend past them
            mesh.bounds = b;

            if (model == null)
            {
                model = new GameObject("SplatModel");
                model.AddComponent<MeshFilter>();
                var mr = model.AddComponent<MeshRenderer>();
                mr.shadowCastingMode = ShadowCastingMode.Off;
                mr.receiveShadows = false;
            }
            model.GetComponent<MeshFilter>().sharedMesh = mesh;
            model.GetComponent<MeshRenderer>().sharedMaterial = material;
            model.SetActive(shown);
            Place();
        }

        /// <summary>Same transform as the tabletop markers: map meters -> board via offset + scale.</summary>
        void Place()
        {
            if (model == null || table.MapRoot == null) return;
            model.transform.SetParent(table.MapRoot, false);
            model.transform.localPosition = table.BoardPosition(0f, 0f);
            model.transform.localRotation = Quaternion.identity;
            model.transform.localScale = Vector3.one * table.Scale;
        }

        static float Median(float a, float b, float c) => Mathf.Max(Mathf.Min(a, b), Mathf.Min(Mathf.Max(a, b), c));

        string Summary() => shown ? $"3D model: {status}" : null;

#if UNITY_EDITOR
        void Reset()
        {
            hub = FindAnyObjectByType<SurveyHub>();
            table = FindAnyObjectByType<TabletopMap>();
            const string path = "Assets/Materials/SplatBillboard.mat";
            material = UnityEditor.AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material != null) return;
            var shader = Shader.Find("Understory/SplatBillboard");
            if (shader == null) { Debug.LogWarning("[SplatView] Understory/SplatBillboard shader not found (not imported yet?)."); return; }
            material = new Material(shader) { name = "SplatBillboard" };
            if (!UnityEditor.AssetDatabase.IsValidFolder("Assets/Materials")) UnityEditor.AssetDatabase.CreateFolder("Assets", "Materials");
            UnityEditor.AssetDatabase.CreateAsset(material, path);
            UnityEditor.AssetDatabase.SaveAssets();
        }
#endif
    }
}
