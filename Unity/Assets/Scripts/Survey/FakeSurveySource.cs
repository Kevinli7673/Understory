using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Networking;

namespace Understory
{
    /// <summary>
    /// Replays a mission folder (fake_data/missions/&lt;id&gt; or a real logger output) into SurveyHub
    /// as if it were arriving live over ROS. Disable this and enable the ROS subscribers for the real thing.
    ///
    /// Editor: reads &lt;repo&gt;/fake_data/missions/&lt;missionId&gt; directly.
    /// Quest build: reads StreamingAssets/fake_data/missions/&lt;missionId&gt;
    /// (Understory → Copy Fake Data To StreamingAssets).
    /// </summary>
    public class FakeSurveySource : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [SerializeField] string missionId = "m1";
        [Tooltip("Optional absolute folder; overrides the default fake_data location.")]
        [SerializeField] string missionFolderOverride = "";
        [Tooltip("Playback speed vs. the recorded timestamps.")]
        [SerializeField] float speed = 10f;
        [Tooltip("Longest wait between two events, seconds (real time).")]
        [SerializeField] float maxGap = 1.5f;
        [SerializeField] bool playOnStart = true;
        [SerializeField] bool loop;

        // Matches fake_data/generate.py: 12 frames x 2 s per capture.
        const double CaptureSeconds = 24.0;

        Coroutine playback;

        public bool IsPlaying => playback != null;

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (hub == null) { Debug.LogError("[FakeSurveySource] No SurveyHub in scene."); return; }
            if (playOnStart) Play();
        }

        [ContextMenu("Play (restart)")]
        public void Play()
        {
            Stop();
            playback = StartCoroutine(Run());
        }

        [ContextMenu("Stop")]
        public void Stop()
        {
            if (playback != null) StopCoroutine(playback);
            playback = null;
        }

        public string MissionRoot()
        {
            if (!string.IsNullOrEmpty(missionFolderOverride)) return missionFolderOverride;
#if UNITY_EDITOR
            return Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "fake_data", "missions", missionId));
#else
            return Application.streamingAssetsPath + "/fake_data/missions/" + missionId;
#endif
        }

        IEnumerator Run()
        {
            do
            {
                hub.Clear();
                string root = MissionRoot();
                Debug.Log($"[FakeSurveySource] Replaying {root}");

                string bubblesText = null, pinsText = null, readingsText = null, yaml = null;
                byte[] pgm = null;
                yield return LoadText(root, "bubbles.jsonl", s => bubblesText = s);
                yield return LoadText(root, "pins.jsonl", s => pinsText = s);
                yield return LoadText(root, "readings.jsonl", s => readingsText = s);
                yield return LoadText(root, "map.yaml", s => yaml = s);
                yield return LoadBytes(root, "map.pgm", b => pgm = b);

                if (bubblesText == null)
                {
                    Debug.LogError($"[FakeSurveySource] No bubbles.jsonl in {root}. Run: python fake_data/generate.py");
                    break;
                }

                var events = BuildTimeline(
                    SurveyJson.ParseLines<Bubble>(bubblesText),
                    SurveyJson.ParseLines<Pin>(pinsText ?? ""),
                    SurveyJson.ParseLines<Reading>(readingsText ?? ""));

                if (pgm != null && yaml != null)
                {
                    try { hub.HandleMap(MapGrid.FromPgm(pgm, yaml)); }
                    catch (Exception e) { Debug.LogWarning($"[FakeSurveySource] Bad map: {e.Message}"); }
                }

                double prevT = events.Count > 0 ? events[0].T : 0;
                foreach (var ev in events)
                {
                    float wait = Mathf.Min((float)(ev.T - prevT) / Mathf.Max(speed, 0.01f), maxGap);
                    if (wait > 0f) yield return new WaitForSeconds(wait);
                    prevT = ev.T;

                    switch (ev.Kind)
                    {
                        case Kind.State: hub.HandleMissionState(ev.State); break;
                        case Kind.Reading: hub.HandleReading(ev.Reading); break;
                        case Kind.Pin: hub.HandlePin(ev.Pin); break;
                        case Kind.Bubble:
                            // JSON first, then images trickle in, so views must handle a bubble before its images.
                            hub.HandleBubble(ev.Bubble);
                            yield return SendBubbleImages(root, ev.Bubble);
                            break;
                    }
                }
                Debug.Log("[FakeSurveySource] Replay finished.");
                if (loop) yield return new WaitForSeconds(3f);
            } while (loop);
            playback = null;
        }

        IEnumerator SendBubbleImages(string root, Bubble b)
        {
            foreach (var f in b.Frames)
            {
                byte[] jpg = null;
                yield return LoadBytes(root, $"frames/{b.BubbleId}_{f.Index}.jpg", x => jpg = x);
                if (jpg != null) hub.HandleBubbleImage(f.ImageFrameId(b.BubbleId), jpg);
            }
            if (b.Stitched)
            {
                byte[] jpg = null;
                yield return LoadBytes(root, $"frames/{b.BubbleId}_pano.jpg", x => jpg = x);
                if (jpg != null) hub.HandleBubbleImage($"{b.BubbleId}/pano", jpg);
            }
        }

        // ---- timeline ----

        enum Kind { State, Reading, Bubble, Pin }

        struct Event
        {
            public double T;
            public Kind Kind;
            public string State;
            public Reading Reading;
            public Bubble Bubble;
            public Pin Pin;
        }

        /// <summary>
        /// Pins have no timestamp in the contract, so they're placed just after their bubble.
        /// Mission states are synthesized: SURVEYING, CAPTURING/NEXT_POINT around each bubble, RETURNING, IDLE.
        /// </summary>
        static List<Event> BuildTimeline(List<Bubble> bubbles, List<Pin> pins, List<Reading> readings)
        {
            var ev = new List<Event>();
            double t0 = bubbles.Count > 0 ? bubbles.Min(b => b.T) - CaptureSeconds : 0;
            if (readings.Count > 0) t0 = Math.Min(t0, readings.Min(r => r.T));
            double tEnd = t0;

            ev.Add(new Event { T = t0 - 0.5, Kind = Kind.State, State = "SURVEYING" });
            foreach (var r in readings)
            {
                ev.Add(new Event { T = r.T, Kind = Kind.Reading, Reading = r });
                tEnd = Math.Max(tEnd, r.T);
            }
            foreach (var b in bubbles)
            {
                ev.Add(new Event { T = b.T - CaptureSeconds, Kind = Kind.State, State = "CAPTURING" });
                ev.Add(new Event { T = b.T, Kind = Kind.Bubble, Bubble = b });
                int k = 0;
                foreach (var p in pins.Where(p => p.BubbleId == b.BubbleId))
                    ev.Add(new Event { T = b.T + 0.5 + 0.5 * k++, Kind = Kind.Pin, Pin = p });
                ev.Add(new Event { T = b.T + 0.5 + 0.5 * k, Kind = Kind.State, State = "NEXT_POINT" });
                tEnd = Math.Max(tEnd, b.T + 1 + 0.5 * k);
            }
            // Pins whose bubble never showed up still get delivered.
            var known = new HashSet<string>(bubbles.Select(b => b.BubbleId));
            foreach (var p in pins.Where(p => !known.Contains(p.BubbleId)))
                ev.Add(new Event { T = tEnd, Kind = Kind.Pin, Pin = p });

            ev.Add(new Event { T = tEnd + 1, Kind = Kind.State, State = "RETURNING" });
            ev.Add(new Event { T = tEnd + 6, Kind = Kind.State, State = "IDLE" });
            // Stable sort: equal timestamps keep insertion order.
            return ev.Select((e, i) => (e, i)).OrderBy(x => x.e.T).ThenBy(x => x.i).Select(x => x.e).ToList();
        }

        // ---- file loading (UnityWebRequest so the same code reads Android StreamingAssets) ----

        static string ToUri(string root, string rel)
        {
            string path = root.TrimEnd('/', '\\') + "/" + rel;
            return path.Contains("://") ? path : new Uri(path).AbsoluteUri;
        }

        static IEnumerator LoadBytes(string root, string rel, Action<byte[]> done)
        {
            using (var req = UnityWebRequest.Get(ToUri(root, rel)))
            {
                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success) done(req.downloadHandler.data);
                else Debug.LogWarning($"[FakeSurveySource] Missing {rel}: {req.error}");
            }
        }

        static IEnumerator LoadText(string root, string rel, Action<string> done) =>
            LoadBytes(root, rel, b => done(System.Text.Encoding.UTF8.GetString(b)));
    }
}
