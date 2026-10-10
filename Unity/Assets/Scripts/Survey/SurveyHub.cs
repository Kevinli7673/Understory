using System;
using System.Collections.Generic;
using UnityEngine;

namespace Understory
{
    /// <summary>
    /// Single entry point for survey data. ROS subscribers and FakeSurveySource both call the
    /// Handle* methods with the raw message payloads; everything else (map twin, bubbles, pins,
    /// haptics) listens to the events or reads the stored state. Swapping fake for real = swapping
    /// which component calls Handle*, nothing downstream changes.
    /// </summary>
    public class SurveyHub : MonoBehaviour
    {
        public static SurveyHub Instance { get; private set; }

        [SerializeField] bool logEvents = true;

        /// <summary>Fires on every /survey/bubbles message (a bubble can be re-sent, e.g. once stitched).</summary>
        public event Action<Bubble> BubbleReceived;
        /// <summary>(frame_id, texture) for each /survey/bubble_images message, e.g. ("m1-b03/4", tex) or ("m1-b03/pano", tex).</summary>
        public event Action<string, Texture2D> BubbleImageReceived;
        /// <summary>Fires once per new pin_id.</summary>
        public event Action<Pin> PinAdded;
        /// <summary>Fires the first time a label is seen this mission (haptic buzz hook).</summary>
        public event Action<Pin> NewSpeciesSeen;
        public event Action<Reading> ReadingReceived;
        public event Action<MissionState> MissionStateChanged;
        public event Action<MapGrid> MapUpdated;
        /// <summary>Robot pose in the ROS map frame (x, y meters, yaw radians), e.g. from slam_toolbox /pose.</summary>
        public event Action<Vector3> RobotPoseUpdated;
        /// <summary>Fires when Clear() wipes state, so views can tear down.</summary>
        public event Action Cleared;

        public readonly Dictionary<string, Bubble> Bubbles = new Dictionary<string, Bubble>();
        public readonly Dictionary<string, Texture2D> BubbleImages = new Dictionary<string, Texture2D>();
        public readonly Dictionary<string, Pin> Pins = new Dictionary<string, Pin>();
        public readonly List<Reading> Readings = new List<Reading>();
        public readonly HashSet<string> SpeciesSeen = new HashSet<string>();
        public MapGrid Map { get; private set; }
        public MissionState State { get; private set; } = MissionState.Unknown;
        /// <summary>Latest (x, y, yaw) from HandleRobotPose; null until one arrives.</summary>
        public Vector3? RobotPose { get; private set; }
        /// <summary>mission_id of the data currently in the hub (from the first bubble/pin/reading).</summary>
        public string MissionId { get; private set; }
        /// <summary>The mission before this one in this session (archived on a mission_id change), or null.</summary>
        public string PreviousMissionId { get; private set; }
        public List<Pin> PreviousMissionPins { get; private set; }
        /// <summary>Fires when data for a new mission_id starts arriving (after any archive + clear).</summary>
        public event Action<string> MissionStarted;

        void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Debug.LogWarning("[SurveyHub] Duplicate hub, destroying this one.");
                Destroy(this);
                return;
            }
            Instance = this;
        }

        void OnDestroy()
        {
            if (Instance == this) Instance = null;
            foreach (var tex in BubbleImages.Values) Destroy(tex);
        }

        // ---- handlers (call these from ROS callbacks or fake sources) ----

        public void HandleBubbleJson(string json) => HandleBubble(Bubble.FromJson(json));

        public void HandleBubble(Bubble b)
        {
            if (b == null || string.IsNullOrEmpty(b.BubbleId)) return;
            CheckMission(b.MissionId);
            Bubbles[b.BubbleId] = b;
            Log($"bubble {b.BubbleId} at ({b.X:F2}, {b.Y:F2}) stitched={b.Stitched} frames={b.Frames.Count}");
            BubbleReceived?.Invoke(b);
        }

        /// <summary>frameId is the CompressedImage header.frame_id ("&lt;bubble_id&gt;/&lt;index&gt;" or "&lt;bubble_id&gt;/pano").</summary>
        public void HandleBubbleImage(string frameId, byte[] jpgOrPng)
        {
            if (string.IsNullOrEmpty(frameId) || jpgOrPng == null) return;
            var tex = new Texture2D(2, 2, TextureFormat.RGB24, false) { name = frameId, wrapMode = TextureWrapMode.Clamp };
            if (!tex.LoadImage(jpgOrPng, markNonReadable: true))
            {
                Debug.LogWarning($"[SurveyHub] Could not decode image {frameId}");
                Destroy(tex);
                return;
            }
            if (BubbleImages.TryGetValue(frameId, out var old)) Destroy(old);
            BubbleImages[frameId] = tex;
            BubbleImageReceived?.Invoke(frameId, tex);
        }

        public void HandlePinJson(string json) => HandlePin(Pin.FromJson(json));

        public void HandlePin(Pin p)
        {
            if (p == null || string.IsNullOrEmpty(p.PinId)) return;
            CheckMission(p.MissionId);
            bool isNew = !Pins.ContainsKey(p.PinId);
            Pins[p.PinId] = p;
            if (!isNew) return;
            Log($"pin {p.PinId} {p.Label}{(p.Invasive ? " (INVASIVE)" : "")} {p.Confidence:P0} at ({p.X:F2}, {p.Y:F2})");
            PinAdded?.Invoke(p);
            if (!string.IsNullOrEmpty(p.Label) && SpeciesSeen.Add(p.Label))
                NewSpeciesSeen?.Invoke(p);
        }

        public void HandleReadingJson(string json) => HandleReading(Reading.FromJson(json));

        public void HandleReading(Reading r)
        {
            if (r == null) return;
            CheckMission(r.MissionId);
            Readings.Add(r);
            ReadingReceived?.Invoke(r);
        }

        /// <summary>/mission/state payload, e.g. "SURVEYING".</summary>
        public void HandleMissionState(string state)
        {
            var s = MissionStates.Parse(state);
            if (s == State) return;
            Log($"mission state {State} -> {s}");
            State = s;
            MissionStateChanged?.Invoke(s);
        }

        public void HandleMap(MapGrid map)
        {
            if (map == null) return;
            Map = map;
            Log($"map {map.Width}x{map.Height} @ {map.Resolution} m, origin ({map.OriginX}, {map.OriginY})");
            MapUpdated?.Invoke(map);
        }

        /// <summary>
        /// A new mission_id (e.g. the "after" re-survey) archives the current mission's pins in
        /// PreviousMissionPins and starts clean, keeping the map, mission state and robot pose (same place).
        /// </summary>
        void CheckMission(string missionId)
        {
            if (string.IsNullOrEmpty(missionId) || missionId == MissionId) return;
            if (MissionId != null)
            {
                PreviousMissionId = MissionId;
                PreviousMissionPins = new List<Pin>(Pins.Values);
                Log($"new mission {missionId}; archived {PreviousMissionId} ({PreviousMissionPins.Count} pins)");
                var map = Map;
                var state = State;
                var pose = RobotPose;
                Clear();
                if (map != null) HandleMap(map);
                if (state != MissionState.Unknown) { State = state; MissionStateChanged?.Invoke(state); }
                if (pose.HasValue) HandleRobotPose(pose.Value.x, pose.Value.y, pose.Value.z);
            }
            MissionId = missionId;
            MissionStarted?.Invoke(missionId);
        }

        /// <summary>Robot pose, ROS map frame. Not logged (arrives many times a second).</summary>
        public void HandleRobotPose(float x, float y, float yaw)
        {
            var pose = new Vector3(x, y, yaw);
            RobotPose = pose;
            RobotPoseUpdated?.Invoke(pose);
        }

        /// <summary>Wipe all state (new mission / restarting fake playback).</summary>
        public void Clear()
        {
            foreach (var tex in BubbleImages.Values) Destroy(tex);
            Bubbles.Clear();
            BubbleImages.Clear();
            Pins.Clear();
            Readings.Clear();
            SpeciesSeen.Clear();
            Map = null;
            State = MissionState.Unknown;
            RobotPose = null;
            MissionId = null; // the archive (PreviousMission*) survives an explicit Clear
            Cleared?.Invoke();
        }

        void Log(string msg)
        {
            if (logEvents) Debug.Log($"[SurveyHub] {msg}");
        }

        // Scene-view sanity check: bubbles (cyan), pins (red invasive / green native) with a line from the
        // bubble, plus a yellow ray along the pin's yaw. The ray should lie on the line, or the yaw math is off.
        void OnDrawGizmos()
        {
            foreach (var b in Bubbles.Values)
            {
                Gizmos.color = Color.cyan;
                Gizmos.DrawWireSphere(transform.TransformPoint(b.UnityPosition), 0.25f);
            }
            foreach (var p in Pins.Values)
            {
                Gizmos.color = p.Invasive ? Color.red : Color.green;
                var pos = transform.TransformPoint(p.UnityPosition);
                Gizmos.DrawSphere(pos, 0.1f);
                if (!Bubbles.TryGetValue(p.BubbleId, out var b)) continue;
                var from = transform.TransformPoint(b.UnityPosition);
                Gizmos.DrawLine(from, pos);
                Gizmos.color = Color.yellow;
                Gizmos.DrawRay(from + Vector3.up * 0.05f, transform.TransformDirection(p.UnityDirection) * 0.6f);
            }
        }
    }
}
