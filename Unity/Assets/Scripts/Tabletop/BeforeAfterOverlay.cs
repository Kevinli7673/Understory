using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Understory
{
    /// <summary>
    /// Before/after on the tabletop: loads an earlier mission's pins.jsonl and marks each of its invasives as
    /// "removed" (green disc) or "still here" (red disc) against the current survey. Same matching rule as the
    /// dashboard: same label within matchRadius meters. Summary goes on the table's status line,
    /// e.g. "before m1: 7 invasive -> 1 remaining (86% removed)".
    /// Toggle: the "Compare" button on the mission panel, or V in the editor.
    /// </summary>
    public class BeforeAfterOverlay : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [SerializeField] TabletopMap table;
        [SerializeField] MissionPanel panel;
        [Tooltip("Mission folder with the earlier survey (fake_data/missions/<id>, StreamingAssets on the Quest).")]
        [SerializeField] string beforeMissionId = "m1";
        [SerializeField] float matchRadius = 0.5f;
        [SerializeField] bool showOnStart;

        static readonly Color Removed = new Color(0.3f, 0.95f, 0.45f);
        static readonly Color Remaining = new Color(1f, 0.25f, 0.2f);

        List<Pin> before;
        bool loading, shown;
        Transform layer;
        readonly List<(Transform t, Pin p)> markers = new List<(Transform, Pin)>();
        readonly List<Material> mats = new List<Material>();
        bool dirty;

        public bool Shown => shown;

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (panel == null) panel = FindAnyObjectByType<MissionPanel>();
            if (hub == null || table == null) { enabled = false; return; }
            hub.PinAdded += OnPinsChanged;
            hub.Cleared += OnCleared;
            table.LayoutChanged += Place;
            if (panel != null) panel.Pressed += OnPanel;
            table.StatusProviders.Add(Summary);
            if (showOnStart) SetShown(true);
        }

        void OnDestroy()
        {
            if (hub != null) { hub.PinAdded -= OnPinsChanged; hub.Cleared -= OnCleared; }
            if (table != null)
            {
                table.LayoutChanged -= Place;
                table.StatusProviders.Remove(Summary);
            }
            if (panel != null) panel.Pressed -= OnPanel;
            foreach (var m in mats) if (m != null) Destroy(m);
        }

        void Update()
        {
            var kb = Keyboard.current;
            if (kb != null && kb.vKey.wasPressedThisFrame) SetShown(!shown);
            if (dirty) { dirty = false; Recolor(); }
        }

        void OnPanel(string keyword)
        {
            if (keyword == MissionPanel.CompareKeyword) SetShown(!shown);
        }

        public void SetShown(bool on)
        {
            shown = on;
            if (on && before == null && !loading) StartCoroutine(Load());
            if (layer != null) layer.gameObject.SetActive(on);
            Debug.Log($"[BeforeAfter] {(on ? "showing" : "hiding")} comparison with {beforeMissionId}");
        }

        System.Collections.IEnumerator Load()
        {
            loading = true;
            string text = null;
            yield return MissionFiles.LoadText(MissionFiles.Root(beforeMissionId), "pins.jsonl", t => text = t);
            before = text != null ? SurveyJson.ParseLines<Pin>(text).Where(p => p.Invasive).ToList() : new List<Pin>();
            loading = false;
            Build();
        }

        void Build()
        {
            if (table.MapRoot == null) return;
            layer = new GameObject($"Before {beforeMissionId}").transform;
            layer.SetParent(table.MapRoot, false);
            foreach (var p in before)
            {
                var disc = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                disc.name = $"Before {p.PinId}";
                Destroy(disc.GetComponent<Collider>());
                disc.transform.SetParent(layer, false);
                disc.transform.localScale = new Vector3(0.028f, 0.0012f, 0.028f);
                var mat = WorldUI.Tinted(table.BaseMaterial, null, Remaining);
                mats.Add(mat);
                WorldUI.Apply(disc, mat);
                markers.Add((disc.transform, p));
            }
            layer.gameObject.SetActive(shown);
            Place();
            Recolor();
        }

        void Place()
        {
            foreach (var (t, p) in markers)
                if (t != null) t.localPosition = table.BoardPosition(p.X, p.Y) + Vector3.up * 0.0015f;
        }

        void OnPinsChanged(Pin _) => dirty = true;
        void OnCleared() => dirty = true;

        bool StillThere(Pin old) =>
            hub.Pins.Values.Any(p => p.Invasive && p.Label == old.Label &&
                                     new Vector2(p.X - old.X, p.Y - old.Y).sqrMagnitude <= matchRadius * matchRadius);

        void Recolor()
        {
            foreach (var (t, p) in markers)
                if (t != null) t.GetComponent<MeshRenderer>().sharedMaterial.color = StillThere(p) ? Remaining : Removed;
        }

        /// <summary>Status line text while shown, e.g. "before m1: 7 invasive -> 1 remaining (86% removed)".</summary>
        string Summary()
        {
            if (!shown) return null;
            if (before == null) return $"before {beforeMissionId}: loading...";
            int total = before.Count;
            if (hub.Pins.Count == 0) return $"before {beforeMissionId}: {total} invasive  ·  waiting for this survey";
            int remaining = before.Count(StillThere);
            int pct = total > 0 ? Mathf.RoundToInt(100f * (total - remaining) / total) : 0;
            return $"before {beforeMissionId}: {total} invasive  ->  {remaining} remaining  ({pct}% removed)";
        }
    }
}
