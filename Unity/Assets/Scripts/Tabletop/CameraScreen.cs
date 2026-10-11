using RosMessageTypes.Sensor;
using Unity.Robotics.ROSTCPConnector;
using UnityEngine;

namespace Understory
{
    /// <summary>
    /// Live robot camera (/camera/image/compressed) on a screen standing behind the tabletop map.
    /// Only the newest frame is kept and decoded at most maxFps, so a fast stream can't back up.
    /// If video lags over the hotspot (AGENTS.md fallback), lower maxFps or the camera's publish rate/res.
    /// </summary>
    public class CameraScreen : MonoBehaviour
    {
        [SerializeField] TabletopMap table;
        [SerializeField] string topic = "/camera/image/compressed";
        [SerializeField] float maxFps = 15f;
        // renamed from "width" (scene had 0.5 saved): 0.85 m wide, readable from the table and on the dashboard
        [SerializeField] float screenWidth = 0.85f;
        [SerializeField] float offlineAfter = 3f;

        Transform screen;
        Material mat;
        Texture2D tex;
        TextMesh offline;
        byte[] pendingFrame;
        float nextDecode, lastFrame = -100f, aspect = 0.75f;
        bool rosOn;

        void Start()
        {
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            var source = FindAnyObjectByType<RosSurveySource>();
            rosOn = source != null && source.RosEnabled;
            if (rosOn) ROSConnection.GetOrCreateInstance().Subscribe<CompressedImageMsg>(topic, m => pendingFrame = m.data);
            if (table != null) table.LayoutChanged += Place;
            tex = new Texture2D(2, 2, TextureFormat.RGB24, false) { name = "RobotCamera", wrapMode = TextureWrapMode.Clamp };
            tex.SetPixels(new[] { Color.black, Color.black, Color.black, Color.black });
            tex.Apply();
        }

        void OnDestroy()
        {
            if (table != null) table.LayoutChanged -= Place;
            if (mat != null) Destroy(mat);
            if (tex != null) Destroy(tex);
        }

        void Update()
        {
            if (screen == null && table != null && table.Root != null) Build();
            if (screen == null) return;

            if (pendingFrame != null && Time.unscaledTime >= nextDecode)
            {
                if (tex.LoadImage(pendingFrame))
                {
                    lastFrame = Time.unscaledTime;
                    float a = tex.height / (float)tex.width;
                    if (!Mathf.Approximately(a, aspect)) { aspect = a; Place(); }
                }
                pendingFrame = null;
                nextDecode = Time.unscaledTime + 1f / Mathf.Max(1f, maxFps);
            }

            bool live = Time.unscaledTime - lastFrame < offlineAfter;
            if (offline.gameObject.activeSelf == live)
            {
                offline.gameObject.SetActive(!live);
                mat.color = live ? Color.white : new Color(0.15f, 0.15f, 0.17f);
            }
            if (!live) offline.text = rosOn ? "robot camera\n<size=28>no video</size>" : "robot camera\n<size=28>ROS off</size>";
        }

        void Build()
        {
            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = "CameraScreen";
            Destroy(quad.GetComponent<Collider>());
            screen = quad.transform;
            screen.SetParent(table.Root, false);
            mat = WorldUI.Tinted(table.BaseMaterial, tex, new Color(0.15f, 0.15f, 0.17f));
            WorldUI.Apply(quad, mat);

            offline = WorldUI.MakeLabel(table.Root, "", new Color(0.7f, 0.7f, 0.75f), 0.03f, TextAnchor.MiddleCenter);
            offline.richText = true;
            Place();
        }

        /// <summary>Standing just behind the far edge of the board, bottom edge a little above the table.</summary>
        void Place()
        {
            if (screen == null) return;
            float h = screenWidth * aspect;
            var pos = new Vector3(0f, h / 2f + 0.06f, table.HalfExtents.y + 0.05f);
            screen.localPosition = pos;
            screen.localRotation = Quaternion.Euler(-8f, 0f, 0f); // lean back slightly
            screen.localScale = new Vector3(screenWidth, h, 1f);
            offline.transform.localPosition = pos - Vector3.forward * 0.005f;
            offline.transform.localRotation = screen.localRotation;
        }
    }
}
