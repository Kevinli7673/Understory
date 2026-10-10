using System.IO;
using UnityEditor;
using UnityEngine;

namespace Understory.EditorTools
{
    public static class FakeDataMenu
    {
        static string RepoMissions => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "fake_data", "missions"));
        static string StreamingMissions => Path.Combine(Application.streamingAssetsPath, "fake_data", "missions");

        /// <summary>Headset builds can't read the repo, so copy fake missions into StreamingAssets before building.</summary>
        [MenuItem("Understory/Copy Fake Data To StreamingAssets")]
        static void CopyToStreamingAssets()
        {
            if (!Directory.Exists(RepoMissions))
            {
                EditorUtility.DisplayDialog("Fake data missing", $"{RepoMissions} not found.\nRun: python fake_data/generate.py", "OK");
                return;
            }
            if (Directory.Exists(StreamingMissions)) Directory.Delete(StreamingMissions, true);
            foreach (var src in Directory.GetFiles(RepoMissions, "*", SearchOption.AllDirectories))
            {
                var dst = Path.Combine(StreamingMissions, Path.GetRelativePath(RepoMissions, src));
                Directory.CreateDirectory(Path.GetDirectoryName(dst));
                File.Copy(src, dst, true);
            }
            AssetDatabase.Refresh();
            Debug.Log($"[FakeData] Copied {RepoMissions} -> {StreamingMissions}");
        }
    }
}
