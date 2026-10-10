using UnityEngine;

namespace Understory
{
    /// <summary>
    /// Pick a plant pin on the tabletop -> a card floats above it with the bubble photo that saw it
    /// (the frame whose yaw is closest to the pin's bearing, or the pano), a marker line at the detection's
    /// bearing, and label / confidence / ids. Pick the same pin again to open its bubble.
    /// Uses bubble images from SurveyHub, so it works with live ROS data (crop files aren't published).
    /// </summary>
    public class PinCard : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [SerializeField] TabletopMap table;
        [SerializeField] float photoWidth = 0.26f;

        Transform card, photo, marker;
        Material photoMat, markerMat, backMat;
        TextMesh title;
        string shownPin;

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (hub == null || table == null) { enabled = false; return; }
            table.PinSelected += OnPinSelected;
            table.BubbleSelected += _ => Hide();
            hub.Cleared += Hide;
        }

        void OnDestroy()
        {
            if (table != null) table.PinSelected -= OnPinSelected;
            if (hub != null) hub.Cleared -= Hide;
            foreach (var m in new[] { photoMat, markerMat, backMat }) if (m != null) Destroy(m);
        }

        void Update()
        {
            // Hide when the table goes away (bubble view); it re-opens on the next pick.
            if (card != null && card.gameObject.activeSelf && !table.Visible) Hide();
        }

        void OnPinSelected(string pinId)
        {
            if (!hub.Pins.TryGetValue(pinId, out var pin)) return;
            if (shownPin == pinId)
            {
                Hide();
                table.Select(pin.BubbleId); // second pick: go stand there
                return;
            }
            Show(pin);
        }

        void Hide()
        {
            shownPin = null;
            if (card != null) card.gameObject.SetActive(false);
        }

        void Show(Pin pin)
        {
            if (card == null) Build();
            shownPin = pin.PinId;
            card.gameObject.SetActive(true);

            // Float above the pin, facing the viewer like the board does.
            var pinPos = table.MapRoot.TransformPoint(table.BoardPosition(pin.X, pin.Y));
            card.SetPositionAndRotation(pinPos + table.Root.up * 0.2f, table.Root.rotation * Quaternion.Euler(-10f, 0f, 0f));

            var (tex, u) = FindPhoto(pin);
            float aspect = tex != null ? tex.height / (float)tex.width : 0.75f;
            photo.localScale = new Vector3(photoWidth, photoWidth * aspect, 1f);
            photoMat.mainTexture = tex;
            photoMat.color = tex != null ? Color.white : new Color(0.15f, 0.15f, 0.17f);
            marker.gameObject.SetActive(tex != null && u >= 0f && u <= 1f);
            marker.localPosition = new Vector3((u - 0.5f) * photoWidth, 0f, -0.001f);
            marker.localScale = new Vector3(0.004f, photoWidth * aspect, 1f);
            markerMat.color = pin.Invasive ? new Color(1f, 0.25f, 0.2f) : new Color(0.3f, 0.95f, 0.45f);

            string tag = pin.Invasive ? "<color=#ff5544>INVASIVE</color>" : "<color=#66ee88>native</color>";
            title.text = $"{pin.Label}  {tag}\n<size=30>{pin.Confidence:P0} · {pin.PinId} · from {pin.BubbleId}" +
                         $"{(tex == null ? " · no photo yet" : "")}\npick again to stand there</size>";
            title.transform.localPosition = new Vector3(0f, photoWidth * aspect / 2f + 0.01f, -0.001f);
        }

        /// <summary>The bubble frame looking most directly at the pin, and the pin's horizontal position in it.</summary>
        (Texture2D tex, float u) FindPhoto(Pin pin)
        {
            if (!hub.Bubbles.TryGetValue(pin.BubbleId, out var b)) return (null, -1f);
            BubbleFrame best = null;
            float bestD = float.MaxValue;
            foreach (var f in b.Frames)
            {
                if (!hub.BubbleImages.ContainsKey(f.ImageFrameId(b.BubbleId))) continue;
                float d = Mathf.Abs(Mathf.DeltaAngle(f.Yaw * Mathf.Rad2Deg, pin.Yaw * Mathf.Rad2Deg));
                if (d < bestD) { bestD = d; best = f; }
            }
            if (best != null)
            {
                float hfov = b.Hfov > 0.01f ? b.Hfov : 1.22f;
                float d = Mathf.DeltaAngle(best.Yaw * Mathf.Rad2Deg, pin.Yaw * Mathf.Rad2Deg) * Mathf.Deg2Rad;
                float u = 0.5f - Mathf.Tan(d) / (2f * Mathf.Tan(hfov / 2f)); // larger yaw = further left
                return (hub.BubbleImages[best.ImageFrameId(b.BubbleId)], u);
            }
            if (hub.BubbleImages.TryGetValue($"{b.BubbleId}/pano", out var pano))
            {
                // Pano yaw convention is unconfirmed for real stitcher output (see AGENTS.md); fakes use this.
                float yaw = Mathf.Atan2(Mathf.Sin(pin.Yaw), Mathf.Cos(pin.Yaw));
                return (pano, (Mathf.PI - yaw) / (2f * Mathf.PI));
            }
            return (null, -1f);
        }

        void Build()
        {
            card = new GameObject("PinCard").transform;
            card.SetParent(table.Root, false);

            var back = GameObject.CreatePrimitive(PrimitiveType.Quad);
            back.name = "Back";
            Destroy(back.GetComponent<Collider>());
            back.transform.SetParent(card, false);
            back.transform.localPosition = new Vector3(0f, 0.025f, 0.002f);
            back.transform.localScale = new Vector3(photoWidth + 0.02f, photoWidth * 0.75f + 0.08f, 1f);
            backMat = WorldUI.Tinted(table.BaseMaterial, null, new Color(0.08f, 0.09f, 0.1f));
            WorldUI.Apply(back, backMat);

            var p = GameObject.CreatePrimitive(PrimitiveType.Quad);
            p.name = "Photo";
            Destroy(p.GetComponent<Collider>());
            photo = p.transform;
            photo.SetParent(card, false);
            photoMat = WorldUI.Tinted(table.BaseMaterial, null, Color.white);
            WorldUI.Apply(p, photoMat);

            var m = GameObject.CreatePrimitive(PrimitiveType.Quad);
            m.name = "Marker";
            Destroy(m.GetComponent<Collider>());
            marker = m.transform;
            marker.SetParent(photo.parent, false);
            markerMat = WorldUI.Tinted(table.BaseMaterial, null, Color.red);
            WorldUI.Apply(m, markerMat);

            title = WorldUI.MakeLabel(card, "", Color.white, 0.016f, TextAnchor.LowerCenter);
            title.richText = true;
            card.gameObject.SetActive(false);
        }
    }
}
