using System;
using System.IO;
using System.Net.WebSockets;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;

namespace Understory
{
    /// <summary>
    /// Streams what the headset wearer sees to the laptop dashboard: a mono copy of the main (center eye)
    /// camera, rendered small and slow into a RenderTexture, read back without stalling, JPEG-encoded off the
    /// main thread and sent over a WebSocket to dashboard/live_relay.py (/ws/headset/pub). Newest frame only.
    ///
    /// Creates itself at startup (no scene edit). Off until told where the dashboard is, like ros_ip.txt:
    ///   echo 192.168.x.y > dashboard_ip.txt          (the laptop running live_relay.py; or a full ws:// URL)
    ///   adb push dashboard_ip.txt /sdcard/Android/data/com.knighthacks.understory/files/
    /// then restart the app. In the editor, put the file in Application.persistentDataPath.
    ///
    /// Passthrough is composited by the OS, so it is not in the stream: virtual content shows over the
    /// camera's clear color. If the image arrives upside down, set LIVE_FLIP=1 for the dashboard.
    /// </summary>
    public class HeadsetStreamer : MonoBehaviour
    {
        public const string FileName = "dashboard_ip.txt";
        const int Port = 8770;
        const string PathPub = "/ws/headset/pub";

        [SerializeField] int width = 960;
        [SerializeField] int height = 540;
        [SerializeField] float fps = 8f;
        [SerializeField, Range(30, 90)] int quality = 70;
        // The eye camera is ~100 deg wide: on a flat screen the table and panels came out tiny. Vertical FOV.
        [SerializeField, Range(30, 100)] float fieldOfView = 55f;
        // 0 = follow the head exactly, closer to 1 = steadier but laggier (head jitter is hard to watch).
        [SerializeField, Range(0f, 0.9f)] float smoothing = 0.5f;
        // Table: a fixed camera in front of the table, framing the LiDAR map and the robot camera screen
        // behind it, wherever the wearer looks. Head: what the wearer sees. Table mode shows the head view
        // while the table is hidden (inside a bubble).
        public enum View { Table, Head }
        [SerializeField] View view = View.Table;
        [SerializeField] float tableCamHeight = 0.75f;  // above the slab top (m)
        [SerializeField] float tableCamBack = 0.8f;     // behind the near edge (m)
        TabletopMap table;

        public static HeadsetStreamer Instance { get; private set; }
        /// <summary>"off", "connecting ws://...", "live ws://...".</summary>
        public string Status { get; private set; } = "off";

        Uri uri;
        Camera source, cam;
        RenderTexture rt;
        float nextCapture;
        bool readbackBusy;
        bool posed;                         // stream camera placed at least once (smoothing starts from there)
        byte[] pending;                     // newest encoded JPEG waiting to be sent
        readonly object pendingLock = new object();
        CancellationTokenSource cts;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Boot()
        {
            if (Instance != null) return;
            var go = new GameObject("HeadsetStreamer");
            DontDestroyOnLoad(go);
            go.AddComponent<HeadsetStreamer>();
        }

        void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
            uri = ReadTarget();
            if (uri == null)
            {
                Debug.Log($"[HeadsetStreamer] off: no {FileName} in {Application.persistentDataPath}");
                enabled = false;
                return;
            }
            cts = new CancellationTokenSource();
            _ = SendLoop(cts.Token);
        }

        static Uri ReadTarget()
        {
            try
            {
                string path = Path.Combine(Application.persistentDataPath, FileName);
                if (!File.Exists(path)) return null;
                string s = File.ReadAllText(path).Trim();
                if (s.Length == 0) return null;
                if (!s.StartsWith("ws://") && !s.StartsWith("wss://")) s = $"ws://{s}:{Port}{PathPub}";
                return new Uri(s);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[HeadsetStreamer] bad {FileName}: {e.Message}");
                return null;
            }
        }

        void Update()
        {
            if (Time.unscaledTime < nextCapture || readbackBusy) return;
            if (!EnsureCamera()) return;
            nextCapture = Time.unscaledTime + 1f / Mathf.Max(1f, fps);

            // Follow the eye camera, render once, read back asynchronously (no GPU stall).
            Vector3 pos;
            Quaternion rot;
            if (!TableViewPose(out pos, out rot))
            {
                pos = source.transform.position;
                rot = source.transform.rotation;
            }
            if (!posed)
            {
                cam.transform.SetPositionAndRotation(pos, rot);
                posed = true;
            }
            else
            {
                float t = 1f - smoothing;
                cam.transform.SetPositionAndRotation(Vector3.Lerp(cam.transform.position, pos, t),
                                                     Quaternion.Slerp(cam.transform.rotation, rot, t));
            }
            cam.Render();
            readbackBusy = true;
            AsyncGPUReadback.Request(rt, 0, TextureFormat.RGB24, OnReadback);
        }

        /// <summary>Fixed spectator pose in front of the table (follows it when grabbed / recentered).</summary>
        bool TableViewPose(out Vector3 pos, out Quaternion rot)
        {
            pos = default;
            rot = default;
            if (view != View.Table) return false;
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (table == null || !table.Visible || table.Root == null) return false;
            var root = table.Root;
            float halfDepth = table.HalfExtents.y;
            // Look at a point a bit past the board's center and above it, so the board and the camera
            // screen standing behind its far edge are both in frame.
            pos = root.TransformPoint(new Vector3(0f, tableCamHeight, -halfDepth - tableCamBack));
            var target = root.TransformPoint(new Vector3(0f, 0.15f, halfDepth * 0.35f));
            rot = Quaternion.LookRotation(target - pos, root.up);
            return true;
        }

        bool EnsureCamera()
        {
            if (source == null)
            {
                source = Camera.main;
                if (source == null) return false;
                if (cam != null) Destroy(cam.gameObject);
                cam = null;
            }
            if (cam != null) return true;

            rt = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32) { name = "HeadsetStream" };
            var go = new GameObject("HeadsetStreamCamera");
            go.transform.SetParent(transform, false);
            cam = go.AddComponent<Camera>();
            cam.CopyFrom(source);
            cam.stereoTargetEye = StereoTargetEyeMask.None;  // mono, into our texture, not the headset
            cam.targetTexture = rt;
            cam.fieldOfView = fieldOfView;
            cam.aspect = (float)width / height;
            posed = false;
            cam.enabled = false;                             // rendered by hand at `fps`
            if (cam.clearFlags == CameraClearFlags.Skybox && RenderSettings.skybox == null)
                cam.clearFlags = CameraClearFlags.SolidColor;
            if (cam.clearFlags == CameraClearFlags.SolidColor && cam.backgroundColor.a < 1f)
                cam.backgroundColor = new Color(0.18f, 0.21f, 0.21f, 1f);  // Soot, instead of transparent passthrough
            return true;
        }

        void OnReadback(AsyncGPUReadbackRequest req)
        {
            readbackBusy = false;
            if (req.hasError || cts == null) return;
            byte[] raw = req.GetData<byte>().ToArray();     // only valid inside this callback
            int w = req.width, h = req.height, q = quality;
            Task.Run(() =>
            {
                byte[] jpg = ImageConversion.EncodeArrayToJPG(raw, GraphicsFormat.R8G8B8_UNorm, (uint)w, (uint)h, 0, q);
                lock (pendingLock) pending = jpg;
            });
        }

        async Task SendLoop(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                using (var ws = new ClientWebSocket())
                {
                    try
                    {
                        Status = $"connecting {uri}";
                        await ws.ConnectAsync(uri, ct);
                        Status = $"live {uri}";
                        Debug.Log($"[HeadsetStreamer] streaming to {uri}");
                        while (ws.State == WebSocketState.Open && !ct.IsCancellationRequested)
                        {
                            byte[] frame;
                            lock (pendingLock) { frame = pending; pending = null; }
                            if (frame == null) { await Task.Delay(15, ct); continue; }
                            await ws.SendAsync(new ArraySegment<byte>(frame), WebSocketMessageType.Binary, true, ct);
                        }
                    }
                    catch (OperationCanceledException) { break; }
                    catch (Exception e)
                    {
                        Status = $"connecting {uri} ({e.GetType().Name})";
                    }
                }
                try { await Task.Delay(2000, ct); } catch (OperationCanceledException) { break; }
            }
            Status = "off";
        }

        void OnDestroy()
        {
            if (Instance == this) Instance = null;
            cts?.Cancel();
            cts = null;
            if (cam != null) Destroy(cam.gameObject);
            if (rt != null) { rt.Release(); Destroy(rt); }
        }
    }
}
