using System.Collections.Generic;
using UnityEngine;

namespace Understory
{
    /// <summary>
    /// A grid of flat, labeled world-space buttons lying in a parent's XZ plane (row 0 farthest from the
    /// viewer), picked by ray. Used by MissionPanel and IpKeypad. Call Tick() every frame for the flash.
    /// </summary>
    public class WorldButtons
    {
        public readonly Transform Root;
        readonly Transform[] buttons;
        readonly Material[] mats;
        readonly Color[] colors;
        readonly float[] flashUntil;
        readonly TextMesh[] labels;

        public int Count => buttons.Length;

        public WorldButtons(Transform parent, string name, Material baseMaterial, IList<(string label, Color color)> specs,
            int columns, Vector2 size, float gap, float labelHeight)
        {
            Root = new GameObject(name).transform;
            Root.SetParent(parent, false);
            int n = specs.Count, rows = (n + columns - 1) / columns;
            buttons = new Transform[n];
            mats = new Material[n];
            colors = new Color[n];
            flashUntil = new float[n];
            labels = new TextMesh[n];
            for (int i = 0; i < n; i++)
            {
                int row = i / columns, col = i % columns;
                var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
                go.name = $"Button {specs[i].label}";
                Object.Destroy(go.GetComponent<Collider>());
                go.transform.SetParent(Root, false);
                go.transform.localScale = new Vector3(size.x, 0.008f, size.y);
                go.transform.localPosition = new Vector3(
                    (col - (columns - 1) / 2f) * (size.x + gap), 0f, ((rows - 1) / 2f - row) * (size.y + gap));
                colors[i] = specs[i].color;
                mats[i] = WorldUI.Tinted(baseMaterial, null, colors[i]);
                WorldUI.Apply(go, mats[i]);
                buttons[i] = go.transform;

                // Label lying on the button, readable from the viewer's side.
                labels[i] = WorldUI.MakeLabel(Root, specs[i].label, Color.white, labelHeight, TextAnchor.MiddleCenter);
                labels[i].transform.localPosition = go.transform.localPosition + Vector3.up * 0.0055f;
                labels[i].transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            }
        }

        /// <summary>Index of the button the ray hits, or -1.</summary>
        public int Hit(Ray ray)
        {
            if (Root == null || !Root.gameObject.activeInHierarchy) return -1;
            for (int i = 0; i < buttons.Length; i++)
            {
                var b = buttons[i];
                var plane = new Plane(b.up, b.position + b.up * 0.005f);
                if (!plane.Raycast(ray, out float d)) continue;
                var local = b.InverseTransformPoint(ray.GetPoint(d)); // unit-cube space
                if (Mathf.Abs(local.x) <= 0.5f && Mathf.Abs(local.z) <= 0.5f) return i;
            }
            return -1;
        }

        public void Flash(int i, float seconds = 0.2f) => flashUntil[i] = Time.unscaledTime + seconds;

        public void SetLabel(int i, string text) => labels[i].text = text;

        public void Tick()
        {
            for (int i = 0; i < mats.Length; i++)
                mats[i].color = Time.unscaledTime < flashUntil[i] ? Color.white : colors[i];
        }

        public void Destroy()
        {
            foreach (var m in mats) if (m != null) Object.Destroy(m);
            if (Root != null) Object.Destroy(Root.gameObject);
        }
    }
}
