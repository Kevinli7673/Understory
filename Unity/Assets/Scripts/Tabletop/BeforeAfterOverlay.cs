using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Understory
{
    /// <summary>
    /// Before/after on the tabletop: each invasive from an earlier survey is marked "removed" (green disc) or
    /// "still here" (red disc) against the current survey. Same matching rule as the dashboard: same label
    /// within matchRadius meters. Summary on the table's status line,
    /// e.g. "before m1: 7 invasive -> 1 remaining (86% removed)".
    ///
    /// "Before" = the previous mission seen live this session (SurveyHub archives it when a new mission_id
    /// arrives), else the mission folder beforeMissionId (fake_data / StreamingAssets).
    /// Toggle: the "Compare before" panel button, or V in the editor.
    /// </summary>
    public class BeforeAfterOverlay : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [SerializeField] TabletopMap table;
        [SerializeField] MissionPanel panel;
        [Tooltip("Fallback 'before' mission folder when no earlier mission was seen live.")]
        [SerializeField] string beforeMissionId = "m1";
        [SerializeField] float matchRadius = 0.5f;
        [SerializeField] bool showOnStart;

        static readonly Color Removed = new Color(0.3f, 0.95f, 0.45f);
        static readonly Color Remaining = new Color(1f, 0.25f, 0.2f);

        List<Pin> before;     // invasives only
        string beforeLabel;
        bool loading, shown, dirty;
        Transform layer;
        readonly List<(Transform t, Pin p)> markers = new List<(Transform, Pin)>();
        readonly List<Material> mats = new List<Material>();

        public bool Shown => shown;

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (panel == null) panel = FindAnyObjectByType<MissionPanel>();
            if (hub == null || table == null) { enabled = false; return; }
            hub.PinAdded += OnPinsChanged;
            hub.Cleared += OnCleared;
            hub.MissionStarted += OnMissionStarted;
            table.LayoutChanged += Place;
            if (panel != null) panel.Pressed += OnPanel;
            table.StatusProviders.Add(Summary);
            if (showOnStart) SetShown(true);
        }

        void OnDestroy()
        {
            if (hub != null)
            {
                hub.PinAdded -= OnPinsChanged;
                hub.Cleared -= OnCleared;
                hub.MissionStarted -= OnMissionStarted;
            }
            if (table != null)
            {
                table.LayoutChanged -= Place;
                table.StatusProviders.Remove(Summary);
            }
            if (panel != null) panel.Pressed -= OnPanel;
            DestroyMarkers();
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
            if (on) ResolveBefore();
            if (layer != null) layer.gameObject.SetActive(on);
            Debug.Log($"[BeforeAfter] {(on ? "showing" : "hiding")} comparison" + (beforeLabel != null ? $" with {beforeLabel}" : ""));
        }

        /// <summary>Live archive wins; otherwise load the fallback folder once.</summary>
        void ResolveBefore()
        {
            if (hub.PreviousMissionPins != null)
            {
                string label = $"{hub.PreviousMissionId} (live)";
                if (beforeLabel != label) Use(hub.PreviousMissionPins, label);
            }
            else if (before == null && !loading) StartCoroutine(LoadFallback());
        }

        void OnMissionStarted(string _)
        {
            if (hub.PreviousMissionPins != null) Use(hub.PreviousMissionPins, $"{hub.PreviousMissionId} (live)");
        }

        IEnumerator LoadFallback()
        {
            loading = true;
            string text = null;
            yield return MissionFiles.LoadText(MissionFiles.Root(beforeMissionId), "pins.jsonl", t => text = t);
            loading = false;
            if (hub.PreviousMissionPins != null) yield break; // a live archive showed up meanwhile
            Use(text != null ? SurveyJson.ParseLines<Pin>(text) : new List<Pin>(), beforeMissionId);
        }

        void Use(List<Pin> pins, string label)
        {
            DestroyMarkers();
            before = pins.Where(p => p.Invasive).ToList();
            beforeLabel = label;
            if (table.MapRoot == null) return;

            layer = new GameObject($"Before {label}").transform;
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

        void DestroyMarkers()
        {
            if (layer != null) Destroy(layer.gameObject);
            layer = null;
            markers.Clear();
            foreach (var m in mats) if (m != null) Destroy(m);
            mats.Clear();
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
            for (int i = 0; i < markers.Count; i++)
                if (markers[i].t != null) mats[i].color = StillThere(markers[i].p) ? Remaining : Removed;
        }

        /// <summary>Status line while shown, e.g. "before m1: 7 invasive -> 1 remaining (86% removed)".</summary>
        string Summary()
        {
            if (!shown) return null;
            if (before == null) return "before: loading...";
            int total = before.Count;
            if (hub.Pins.Count == 0) return $"before {beforeLabel}: {total} invasive  ·  waiting for this survey";
            int remaining = before.Count(StillThere);
            int pct = total > 0 ? Mathf.RoundToInt(100f * (total - remaining) / total) : 0;
            return $"before {beforeLabel}: {total} invasive  ->  {remaining} remaining  ({pct}% removed)";
        }
    }
}
