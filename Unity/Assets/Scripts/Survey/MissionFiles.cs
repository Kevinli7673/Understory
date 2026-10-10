using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

namespace Understory
{
    /// <summary>
    /// Reading mission folders (missions/&lt;id&gt;/ layout from AGENTS.md). UnityWebRequest so the same code
    /// reads plain files in the editor and Android StreamingAssets (inside the APK) on the Quest.
    /// </summary>
    public static class MissionFiles
    {
        /// <summary>
        /// Editor: &lt;repo&gt;/fake_data/missions/&lt;id&gt;. Builds: StreamingAssets/fake_data/missions/&lt;id&gt;
        /// (copied automatically by the Android build step).
        /// </summary>
        public static string Root(string missionId)
        {
#if UNITY_EDITOR
            return Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "fake_data", "missions", missionId));
#else
            return Application.streamingAssetsPath + "/fake_data/missions/" + missionId;
#endif
        }

        static string ToUri(string root, string rel)
        {
            string path = root.TrimEnd('/', '\\') + "/" + rel;
            return path.Contains("://") ? path : new Uri(path).AbsoluteUri;
        }

        /// <summary>Coroutine: calls done(bytes) on success; logs and skips done on failure.</summary>
        public static IEnumerator LoadBytes(string root, string rel, Action<byte[]> done)
        {
            using (var req = UnityWebRequest.Get(ToUri(root, rel)))
            {
                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success) done(req.downloadHandler.data);
                else Debug.LogWarning($"[MissionFiles] Missing {root}/{rel}: {req.error}");
            }
        }

        public static IEnumerator LoadText(string root, string rel, Action<string> done) =>
            LoadBytes(root, rel, b => done(System.Text.Encoding.UTF8.GetString(b)));
    }
}
