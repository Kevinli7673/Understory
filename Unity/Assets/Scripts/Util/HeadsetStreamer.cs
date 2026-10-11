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

        [SerializeField] int width = 640;
        [SerializeField] int height = 360;
        [SerializeField] float fps = 8f;
        [SerializeField, Range(30, 90)] int quality = 60;

        public static HeadsetStreamer Instance { get; private set; }
        /// <summary>"off", "connecting ws://...", "live ws://...".</summary>
        public string Status { get; private set; } = "off";

        Uri uri;
        Camera source, cam;
        RenderTexture rt;
        float nextCapture;
        bool readbackBusy;
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
            cam.transform.SetPositionAndRotation(source.transform.position, source.transform.rotation);
            cam.Render();
            readbackBusy = true;
            AsyncGPUReadback.Request(rt, 0, TextureFormat.RGB24, OnReadback);
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
            cam.enabled = false;                              // rendered by hand at `fps`
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
