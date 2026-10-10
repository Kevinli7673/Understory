using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using UnityEngine;

// C# mirrors of the JSON contracts in AGENTS.md ("Data contracts").
// Keys must match exactly; change only with team agreement.
namespace Understory
{
    /// <summary>/survey/bubbles — one 360° capture.</summary>
    [Serializable]
    public class Bubble
    {
        [JsonProperty("bubble_id")] public string BubbleId;
        [JsonProperty("mission_id")] public string MissionId;
        [JsonProperty("t")] public double T;
        [JsonProperty("x")] public float X;
        [JsonProperty("y")] public float Y;
        /// <summary>True: use "&lt;bubble_id&gt;/pano" cylinder. False: unstitched ring of frames.</summary>
        [JsonProperty("stitched")] public bool Stitched;
        [JsonProperty("frames")] public List<BubbleFrame> Frames = new List<BubbleFrame>();
        /// <summary>Horizontal field of view of each frame, radians.</summary>
        [JsonProperty("hfov")] public float Hfov;

        [JsonIgnore] public Vector3 UnityPosition => RosCoords.ToUnity(X, Y);

        public static Bubble FromJson(string json) => SurveyJson.Parse<Bubble>(json);
        public string ToJson() => SurveyJson.Write(this);
    }

    [Serializable]
    public class BubbleFrame
    {
        [JsonProperty("index")] public int Index;
        /// <summary>ROS yaw, radians, map frame.</summary>
        [JsonProperty("yaw")] public float Yaw;

        /// <summary>frame_id of the matching /survey/bubble_images message.</summary>
        public string ImageFrameId(string bubbleId) => $"{bubbleId}/{Index}";
    }

    /// <summary>/survey/pins — one detected species.</summary>
    [Serializable]
    public class Pin
    {
        [JsonProperty("pin_id")] public string PinId;
        [JsonProperty("mission_id")] public string MissionId;
        [JsonProperty("bubble_id")] public string BubbleId;
        [JsonProperty("label")] public string Label;
        [JsonProperty("invasive")] public bool Invasive;
        [JsonProperty("confidence")] public float Confidence;
        /// <summary>Bearing from the bubble center, ROS yaw radians.</summary>
        [JsonProperty("yaw")] public float Yaw;
        [JsonProperty("x")] public float X;
        [JsonProperty("y")] public float Y;
        /// <summary>Crop filename, e.g. "m1-p07.jpg" (missions/&lt;id&gt;/crops/).</summary>
        [JsonProperty("crop")] public string Crop;

        [JsonIgnore] public Vector3 UnityPosition => RosCoords.ToUnity(X, Y);
        [JsonIgnore] public Vector3 UnityDirection => RosCoords.ToUnityDirection(Yaw);

        public static Pin FromJson(string json) => SurveyJson.Parse<Pin>(json);
        public string ToJson() => SurveyJson.Write(this);
    }

    /// <summary>/survey/readings — missing sensors are omitted (null here), never 0.</summary>
    [Serializable]
    public class Reading
    {
        [JsonProperty("mission_id")] public string MissionId;
        [JsonProperty("t")] public double T;
        [JsonProperty("x")] public float X;
        [JsonProperty("y")] public float Y;
        [JsonProperty("temp_c")] public float? TempC;
        [JsonProperty("pressure_hpa")] public float? PressureHpa;
        [JsonProperty("soil_moisture")] public float? SoilMoisture;
        [JsonProperty("light")] public float? Light;
        [JsonProperty("uv")] public float? Uv;
        [JsonProperty("air_quality")] public float? AirQuality;
        [JsonProperty("sound")] public float? Sound;

        [JsonIgnore] public Vector3 UnityPosition => RosCoords.ToUnity(X, Y);

        public static Reading FromJson(string json) => SurveyJson.Parse<Reading>(json);
        public string ToJson() => SurveyJson.Write(this);
    }

    /// <summary>/mission/state values (plain string on the wire).</summary>
    public enum MissionState { Unknown, IDLE, SURVEYING, CAPTURING, NEXT_POINT, RETURNING, MANUAL, STOPPED }

    public static class MissionStates
    {
        public static MissionState Parse(string s) =>
            Enum.TryParse(s?.Trim(), out MissionState state) ? state : MissionState.Unknown;
    }

    public static class SurveyJson
    {
        static readonly JsonSerializerSettings Settings = new JsonSerializerSettings
        {
            NullValueHandling = NullValueHandling.Ignore,     // omit missing sensors, per contract
            MissingMemberHandling = MissingMemberHandling.Ignore,
        };

        /// <summary>Returns null (and logs) on bad JSON instead of throwing into a ROS callback.</summary>
        public static T Parse<T>(string json) where T : class
        {
            try { return JsonConvert.DeserializeObject<T>(json, Settings); }
            catch (JsonException e)
            {
                Debug.LogWarning($"[SurveyJson] Bad {typeof(T).Name} JSON: {e.Message}\n{json}");
                return null;
            }
        }

        public static string Write(object o) => JsonConvert.SerializeObject(o, Settings);

        /// <summary>Parse a .jsonl file's contents (mission folder / fake_data), skipping blank and bad lines.</summary>
        public static List<T> ParseLines<T>(string jsonl) where T : class
        {
            var list = new List<T>();
            foreach (var line in jsonl.Split('\n'))
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                var item = Parse<T>(line);
                if (item != null) list.Add(item);
            }
            return list;
        }
    }
}
