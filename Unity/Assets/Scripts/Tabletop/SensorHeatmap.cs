using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Understory
{
    /// <summary>
    /// Sensor readings as a heat map on the tabletop: readings averaged into cellSize-meter cells, colored
    /// low (blue) -> high (yellow) for one sensor at a time. Cycle with the panel's "Sensor map" button or
    /// H in the editor: off -> soil moisture -> temperature -> light -> air quality -> off.
    /// Colors use a few shared materials (no transparency) so nothing depends on extra shader variants.
    /// </summary>
    public class SensorHeatmap : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [SerializeField] TabletopMap table;
        [SerializeField] MissionPanel panel;
        [SerializeField] float cellSize = 0.25f;

        static readonly (string name, string unit, Func<Reading, float?> get)[] Sensors =
        {
            ("soil moisture", "", r => r.SoilMoisture),
            ("temperature", " °C", r => r.TempC),
            ("light", "", r => r.Light),
            ("air quality", "", r => r.AirQuality),
        };

        const int Buckets = 8;
        static readonly Color Low = new Color(0.15f, 0.3f, 0.85f), Mid = new Color(0.2f, 0.75f, 0.55f), High = new Color(1f, 0.85f, 0.15f);

        int mode = -1; // -1 = off, else index into Sensors
        Transform layer;
        Material[] mats;
        readonly List<GameObject> cells = new List<GameObject>();
        bool dirty;
        float nextRebuild;
        float lo, hi;

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (panel == null) panel = FindAnyObjectByType<MissionPanel>();
            if (hub == null || table == null) { enabled = false; return; }
            hub.ReadingReceived += OnReading;
            hub.Cleared += OnChanged;
            table.LayoutChanged += OnChanged;
            if (panel != null) panel.Pressed += OnPanel;
            table.StatusProviders.Add(Summary);
        }

        void OnDestroy()
        {
            if (hub != null) { hub.ReadingReceived -= OnReading; hub.Cleared -= OnChanged; }
            if (table != null) { table.LayoutChanged -= OnChanged; table.StatusProviders.Remove(Summary); }
            if (panel != null) panel.Pressed -= OnPanel;
            if (mats != null) foreach (var m in mats) if (m != null) Destroy(m);
        }

        void OnReading(Reading _) => dirty = true;
        void OnChanged() => dirty = true;

        void OnPanel(string keyword)
        {
            if (keyword == MissionPanel.SensorsKeyword) Cycle();
        }

        public void Cycle()
        {
            mode = mode + 1 >= Sensors.Length ? -1 : mode + 1;
            dirty = true;
            nextRebuild = 0f;
            Debug.Log($"[SensorHeatmap] {(mode < 0 ? "off" : Sensors[mode].name)}");
        }

        void Update()
        {
            var kb = Keyboard.current;
            if (kb != null && kb.hKey.wasPressedThisFrame) Cycle();
            // Readings can arrive at 1+ Hz for a long mission: rebuild at most twice a second.
            if (dirty && Time.unscaledTime >= nextRebuild)
            {
                dirty = false;
                nextRebuild = Time.unscaledTime + 0.5f;
                Rebuild();
            }
        }

        void Rebuild()
        {
            foreach (var c in cells) Destroy(c);
            cells.Clear();
            if (mode < 0 || table.MapRoot == null) return;

            if (layer == null)
            {
                layer = new GameObject("SensorHeatmap").transform;
                layer.SetParent(table.MapRoot, false);
            }
            if (mats == null)
            {
                mats = new Material[Buckets];
                for (int i = 0; i < Buckets; i++) mats[i] = WorldUI.Tinted(table.BaseMaterial, null, Ramp(i / (Buckets - 1f)));
            }

            // Average per cell.
            var get = Sensors[mode].get;
            var sums = new Dictionary<Vector2Int, (float sum, int n)>();
            foreach (var r in hub.Readings)
            {
                var v = get(r);
                if (!v.HasValue) continue; // missing sensors are omitted, not zero
                var key = new Vector2Int(Mathf.FloorToInt(r.X / cellSize), Mathf.FloorToInt(r.Y / cellSize));
                sums.TryGetValue(key, out var acc);
                sums[key] = (acc.sum + v.Value, acc.n + 1);
            }
            if (sums.Count == 0) { lo = hi = 0f; return; }

            lo = float.MaxValue; hi = float.MinValue;
            foreach (var kv in sums)
            {
                float avg = kv.Value.sum / kv.Value.n;
                lo = Mathf.Min(lo, avg);
                hi = Mathf.Max(hi, avg);
            }

            float size = cellSize * table.Scale * 0.92f; // small gap between cells
            foreach (var kv in sums)
            {
                float avg = kv.Value.sum / kv.Value.n;
                float k = hi > lo ? (avg - lo) / (hi - lo) : 0.5f;
                var cell = GameObject.CreatePrimitive(PrimitiveType.Cube);
                cell.name = "Cell";
                Destroy(cell.GetComponent<Collider>());
                cell.transform.SetParent(layer, false);
                float cx = (kv.Key.x + 0.5f) * cellSize, cy = (kv.Key.y + 0.5f) * cellSize;
                cell.transform.localPosition = table.BoardPosition(cx, cy) + Vector3.up * 0.0012f;
                cell.transform.localScale = new Vector3(size, 0.0008f, size);
                WorldUI.Apply(cell, mats[Mathf.Clamp(Mathf.RoundToInt(k * (Buckets - 1)), 0, Buckets - 1)]);
                cells.Add(cell);
            }
        }

        static Color Ramp(float k) => k < 0.5f ? Color.Lerp(Low, Mid, k * 2f) : Color.Lerp(Mid, High, (k - 0.5f) * 2f);

        string Summary()
        {
            if (mode < 0) return null;
            var s = Sensors[mode];
            if (cells.Count == 0) return $"sensor map: {s.name} · no readings yet";
            return $"sensor map: {s.name}  <color=#4d66d9>{lo:0.#}{s.unit}</color> → <color=#ffd926>{hi:0.#}{s.unit}</color>";
        }
    }
}
