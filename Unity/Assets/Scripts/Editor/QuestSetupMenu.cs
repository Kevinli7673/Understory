using System.Linq;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Understory.EditorTools
{
    /// <summary>
    /// One click to make the open scene + project headset-ready. Safe to run again.
    ///  - OVRCameraRig (floor-level tracking) replaces the plain Main Camera; DesktopLook moves to the rig root.
    ///  - ControllerPointer (right-hand laser onto the table).
    ///  - RosSurveySource, TeleopController, MissionPanel, SpeciesAlert, CameraScreen on the SurveyHub object.
    ///  - Player settings: name, package id, internet permission (ROS-TCP).
    /// XR itself (OpenXR + Meta Quest feature on Android) is enabled in Project Settings, not here.
    /// </summary>
    public static class QuestSetupMenu
    {
        const string PackageId = "com.knighthacks.understory";

        [MenuItem("Understory/Set Up Quest Rig and Player Settings")]
        static void Setup()
        {
            var scene = EditorSceneManager.GetActiveScene();

            // --- camera rig ---
            var rig = Object.FindAnyObjectByType<OVRCameraRig>();
            Transform oldCam = null;
            if (rig == null)
            {
                var path = AssetDatabase.FindAssets("OVRCameraRig t:Prefab")
                    .Select(AssetDatabase.GUIDToAssetPath)
                    .FirstOrDefault(p => p.StartsWith("Packages/com.meta.xr.sdk.core/") && p.EndsWith("/OVRCameraRig.prefab"));
                if (path == null)
                {
                    EditorUtility.DisplayDialog("OVRCameraRig not found", "Couldn't find OVRCameraRig.prefab in com.meta.xr.sdk.core.", "OK");
                    return;
                }
                var go = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(path), scene);
                Undo.RegisterCreatedObjectUndo(go, "Add OVRCameraRig");
                rig = go.GetComponent<OVRCameraRig>();
            }

            // Remove cameras outside the rig, keeping the first one's spot (on the floor) for the rig.
            foreach (var cam in Object.FindObjectsByType<Camera>())
            {
                if (cam.transform.IsChildOf(rig.transform)) continue;
                if (oldCam == null)
                {
                    oldCam = cam.transform;
                    rig.transform.SetPositionAndRotation(new Vector3(oldCam.position.x, 0f, oldCam.position.z),
                        Quaternion.Euler(0f, oldCam.eulerAngles.y, 0f));
                }
                Undo.DestroyObjectImmediate(cam.gameObject);
            }

            var manager = rig.GetComponent<OVRManager>();
            if (manager != null) manager.trackingOriginType = OVRManager.TrackingOrigin.FloorLevel;

            var look = rig.GetComponent<DesktopLook>(); // no ?? : Unity's fake-null breaks it
            if (look == null) look = Undo.AddComponent<DesktopLook>(rig.gameObject);
            var so = new SerializedObject(look);
            so.FindProperty("desktopEyeHeight").floatValue = 1.6f;
            so.ApplyModifiedPropertiesWithoutUndo();

            // --- controller pointer ---
            if (Object.FindAnyObjectByType<ControllerPointer>() == null)
            {
                var pointer = new GameObject("ControllerPointer");
                Undo.RegisterCreatedObjectUndo(pointer, "Add ControllerPointer");
                Undo.AddComponent<ControllerPointer>(pointer);
            }

            // --- ROS: real data + drive/e-stop, next to the hub ---
            var hub = Object.FindAnyObjectByType<SurveyHub>();
            if (hub != null)
            {
                if (hub.GetComponent<RosSurveySource>() == null) Undo.AddComponent<RosSurveySource>(hub.gameObject);
                if (hub.GetComponent<TeleopController>() == null) Undo.AddComponent<TeleopController>(hub.gameObject);
                if (hub.GetComponent<MissionPanel>() == null) Undo.AddComponent<MissionPanel>(hub.gameObject);
                if (hub.GetComponent<SpeciesAlert>() == null) Undo.AddComponent<SpeciesAlert>(hub.gameObject);
                if (hub.GetComponent<CameraScreen>() == null) Undo.AddComponent<CameraScreen>(hub.gameObject);
            }
            else Debug.LogWarning("[QuestSetup] No SurveyHub in the scene; ROS components not added.");

            // --- player settings ---
            PlayerSettings.productName = "Understory";
            PlayerSettings.companyName = "Knight Hacks";
            PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Android, PackageId);
            PlayerSettings.Android.forceInternetPermission = true;

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            AssetDatabase.SaveAssets();
            Debug.Log($"[QuestSetup] Rig ready (floor level), pointer added, package id {PackageId}. Scene saved.");
        }
    }
}
