using System;
using System.IO;
using RosMessageTypes.Std;
using Unity.Robotics.ROSTCPConnector;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Understory
{
    /// <summary>
    /// Push-to-talk: hold X (left controller) or T in the editor, speak, release -> the clip goes to Whisper
    /// on the Jetson as /voice/audio. Whisper's text comes back on /voice/text for the mission manager.
    ///
    /// Proposed contract (AGENTS.md "Open"): /voice/audio is std_msgs/UInt8MultiArray whose data is a
    /// complete WAV file, 16 kHz, mono, 16-bit PCM. Whisper / soundfile / wave can read it directly.
    /// </summary>
    public class PushToTalk : MonoBehaviour
    {
        [SerializeField] int sampleRate = 16000;
        [SerializeField] int maxSeconds = 8;
        [SerializeField] float minSeconds = 0.3f;

        public const string Topic = "/voice/audio";

        /// <summary>Fires with the WAV bytes after each clip (for logging / testing without ROS).</summary>
        public event Action<byte[]> ClipReady;

        public bool Recording { get; private set; }

        ROSConnection ros;
        AudioClip clip;
        float startTime;
        TextMesh indicator;

        void Start()
        {
            var source = FindAnyObjectByType<RosSurveySource>();
            if (source != null && source.RosEnabled)
            {
                ros = ROSConnection.GetOrCreateInstance();
                ros.RegisterPublisher<UInt8MultiArrayMsg>(Topic);
            }
#if UNITY_ANDROID && !UNITY_EDITOR
            if (!UnityEngine.Android.Permission.HasUserAuthorizedPermission(UnityEngine.Android.Permission.Microphone))
                UnityEngine.Android.Permission.RequestUserPermission(UnityEngine.Android.Permission.Microphone);
#endif
            indicator = WorldUI.MakeLabel(null, "● listening", new Color(1f, 0.35f, 0.3f), 0.035f, TextAnchor.MiddleCenter);
            indicator.name = "PushToTalkIndicator";
            indicator.gameObject.SetActive(false);
        }

        void OnDestroy()
        {
            if (Recording) Microphone.End(null);
            if (indicator != null) Destroy(indicator.gameObject);
        }

        void Update()
        {
            var kb = Keyboard.current;
            bool held = OVRInput.Get(OVRInput.Button.Three) || (kb != null && kb.tKey.isPressed);
            if (held && !Recording) Begin();
            else if (Recording && (!held || Time.unscaledTime - startTime >= maxSeconds)) End();
        }

        void LateUpdate()
        {
            if (indicator == null || !indicator.gameObject.activeSelf || Camera.main == null) return;
            var t = Camera.main.transform;
            indicator.transform.SetPositionAndRotation(t.position + t.forward * 1.1f - t.up * 0.3f, Quaternion.LookRotation(t.forward, t.up));
        }

        void Begin()
        {
            if (Microphone.devices.Length == 0)
            {
                Debug.LogWarning("[PushToTalk] No microphone.");
                return;
            }
            clip = Microphone.Start(null, false, maxSeconds, sampleRate);
            startTime = Time.unscaledTime;
            Recording = true;
            indicator.gameObject.SetActive(true);
            Haptics.Buzz(this, 0.2f, 0.04f, OVRInput.Controller.LTouch);
        }

        void End()
        {
            int samples = Microphone.GetPosition(null); // read before End(), which resets it
            Microphone.End(null);
            Recording = false;
            indicator.gameObject.SetActive(false);
            if (clip == null) return;

            float seconds = samples / (float)clip.frequency;
            if (seconds < minSeconds)
            {
                Debug.Log($"[PushToTalk] {seconds:F2}s is too short, ignored.");
                return;
            }
            var data = new float[samples * clip.channels];
            clip.GetData(data, 0);
            var mono = ToMono16k(data, clip.channels, clip.frequency, sampleRate);
            var wav = Wav(mono, sampleRate);

            if (ros != null) ros.Publish(Topic, new UInt8MultiArrayMsg(new MultiArrayLayoutMsg(), wav));
            Debug.Log($"[PushToTalk] {seconds:F1}s clip, {wav.Length / 1024} KB -> {Topic}{(ros == null ? " (ROS off, not sent)" : "")}");
            Haptics.Buzz(this, 0.3f, 0.06f, OVRInput.Controller.LTouch);
            ClipReady?.Invoke(wav);
        }

        /// <summary>Downmix to mono and linearly resample to the target rate (mics often run at 44.1/48 kHz).</summary>
        static float[] ToMono16k(float[] interleaved, int channels, int fromRate, int toRate)
        {
            int frames = interleaved.Length / Math.Max(1, channels);
            var mono = new float[frames];
            for (int i = 0; i < frames; i++)
            {
                float sum = 0f;
                for (int c = 0; c < channels; c++) sum += interleaved[i * channels + c];
                mono[i] = sum / channels;
            }
            if (fromRate == toRate) return mono;
            int outLen = (int)((long)frames * toRate / fromRate);
            var res = new float[outLen];
            for (int i = 0; i < outLen; i++)
            {
                float src = i * (float)fromRate / toRate;
                int a = Mathf.Min((int)src, frames - 1), b = Mathf.Min(a + 1, frames - 1);
                res[i] = Mathf.Lerp(mono[a], mono[b], src - a);
            }
            return res;
        }

        /// <summary>16-bit PCM mono WAV file bytes.</summary>
        static byte[] Wav(float[] samples, int rate)
        {
            using (var ms = new MemoryStream(44 + samples.Length * 2))
            using (var w = new BinaryWriter(ms))
            {
                int dataBytes = samples.Length * 2;
                w.Write(new[] { 'R', 'I', 'F', 'F' });
                w.Write(36 + dataBytes);
                w.Write(new[] { 'W', 'A', 'V', 'E', 'f', 'm', 't', ' ' });
                w.Write(16);              // fmt chunk size
                w.Write((short)1);        // PCM
                w.Write((short)1);        // mono
                w.Write(rate);
                w.Write(rate * 2);        // byte rate
                w.Write((short)2);        // block align
                w.Write((short)16);       // bits per sample
                w.Write(new[] { 'd', 'a', 't', 'a' });
                w.Write(dataBytes);
                foreach (var s in samples) w.Write((short)(Mathf.Clamp(s, -1f, 1f) * short.MaxValue));
                return ms.ToArray();
            }
        }
    }
}
