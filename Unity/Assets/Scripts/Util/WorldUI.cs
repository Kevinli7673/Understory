using UnityEngine;

namespace Understory
{
    /// <summary>Small helpers for world-space labels and tinted material instances (ring + tabletop).</summary>
    public static class WorldUI
    {
        const int FontSize = 48;
        // Measured in the editor: one 48 pt TextMesh line at scale 1 is ~6.8 m tall.
        const float LineHeightAtScale1 = 6.8f;

        /// <summary>
        /// TextMesh label under <paramref name="parent"/>. <paramref name="lineHeight"/> is the world height of
        /// one line in meters, independent of the parent's scale. Readable when viewed along the label's +z.
        /// </summary>
        public static TextMesh MakeLabel(Transform parent, string text, Color color, float lineHeight,
            TextAnchor anchor = TextAnchor.LowerCenter)
        {
            var go = new GameObject("Label");
            go.transform.SetParent(parent, false);
            float parentScale = parent != null ? parent.lossyScale.x : 1f;
            go.transform.localScale = Vector3.one * (lineHeight / LineHeightAtScale1 / Mathf.Max(parentScale, 1e-6f));
            var tm = go.AddComponent<TextMesh>();
            tm.text = text;
            tm.anchor = anchor;
            tm.alignment = TextAlignment.Center;
            tm.fontSize = FontSize;
            tm.color = color;
            tm.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            go.GetComponent<MeshRenderer>().sharedMaterial = tm.font.material;
            return tm;
        }

        /// <summary>New instance of <paramref name="baseMat"/> with texture + color. Caller owns (and destroys) it.</summary>
        public static Material Tinted(Material baseMat, Texture tex, Color color)
        {
            var mat = new Material(baseMat) { mainTexture = tex, color = color };
            return mat;
        }

        /// <summary>Apply a material and turn off shadows (everything here is unlit).</summary>
        public static void Apply(GameObject go, Material mat)
        {
            var mr = go.GetComponent<MeshRenderer>();
            mr.sharedMaterial = mat;
            mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            mr.receiveShadows = false;
        }

#if UNITY_EDITOR
        /// <summary>
        /// Editor-only: the shared URP/Unlit (Render Face: Both) material asset. Referencing an asset (not
        /// Shader.Find) keeps the shader in Quest builds.
        /// </summary>
        public static Material UnlitMaterialAsset()
        {
            const string path = "Assets/Materials/BubblePanel.mat";
            var mat = UnityEditor.AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat != null) return mat;
            mat = new Material(Shader.Find("Universal Render Pipeline/Unlit")) { name = "BubblePanel" };
            mat.SetFloat("_Cull", 0f);
            if (!UnityEditor.AssetDatabase.IsValidFolder("Assets/Materials")) UnityEditor.AssetDatabase.CreateFolder("Assets", "Materials");
            UnityEditor.AssetDatabase.CreateAsset(mat, path);
            UnityEditor.AssetDatabase.SaveAssets();
            return mat;
        }
#endif

        /// <summary>Runtime fallback when no material was assigned (may be stripped in builds).</summary>
        public static Material FallbackUnlit()
        {
            var mat = new Material(Shader.Find("Universal Render Pipeline/Unlit"));
            mat.SetFloat("_Cull", 0f);
            return mat;
        }
    }
}
