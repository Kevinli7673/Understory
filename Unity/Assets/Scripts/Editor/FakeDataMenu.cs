using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace Understory.EditorTools
{
    public static class FakeDataMenu
    {
        static string RepoMissions => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "fake_data", "missions"));
        static string StreamingMissions => Path.Combine(Application.streamingAssetsPath, "fake_data", "missions");

        /// <summary>Headset builds can't read the repo, so copy fake missions into StreamingAssets before building.</summary>
        [MenuItem("Understory/Copy Fake Data To StreamingAssets")]
        static void CopyFromMenu()
        {
            if (!CopyToStreamingAssets())
                EditorUtility.DisplayDialog("Fake data missing", $"{RepoMissions} not found.\nRun: python fake_data/generate.py", "OK");
        }

        /// <summary>Returns false if fake_data/missions doesn't exist.</summary>
        public static bool CopyToStreamingAssets()
        {
            if (!Directory.Exists(RepoMissions)) return false;
            if (Directory.Exists(StreamingMissions)) Directory.Delete(StreamingMissions, true);
            foreach (var src in Directory.GetFiles(RepoMissions, "*", SearchOption.AllDirectories))
            {
                var dst = Path.Combine(StreamingMissions, Path.GetRelativePath(RepoMissions, src));
                Directory.CreateDirectory(Path.GetDirectoryName(dst));
                File.Copy(src, dst, true);
            }
            AssetDatabase.Refresh();
            Debug.Log($"[FakeData] Copied {RepoMissions} -> {StreamingMissions}");
            return true;
        }
    }

    /// <summary>Every Android build gets fresh fake missions, so the headset can always replay.</summary>
    class FakeDataBuildStep : IPreprocessBuildWithReport
    {
        public int callbackOrder => 0;

        public void OnPreprocessBuild(BuildReport report)
        {
            if (report.summary.platform != BuildTarget.Android) return;
            if (!FakeDataMenu.CopyToStreamingAssets())
                Debug.LogWarning("[FakeData] fake_data/missions not found; the headset build has no replay data.");
        }
    }
}
