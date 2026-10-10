using UnityEngine;
using UnityEngine.XR;

namespace Understory
{
    /// <summary>
    /// Laser pointer from the right controller onto the tabletop map. Index trigger picks the capture spot
    /// nearest to where the ray hits the table (TabletopMap.TrySelect), or presses a MissionPanel button. Only shown while the table is.
    /// </summary>
    public class ControllerPointer : MonoBehaviour
    {
        [SerializeField] TabletopMap table;
        [SerializeField] MissionPanel panel;
        [SerializeField] BubbleNavigator navigator;
        [SerializeField] IpKeypad keypad;
        [Tooltip("URP/Unlit material for the ray. Auto-assigned when the component is added.")]
        [SerializeField] Material material;
        [SerializeField] OVRInput.Controller controller = OVRInput.Controller.RTouch;
        [SerializeField] float length = 2f;
        [SerializeField] Color color = new Color(0.6f, 0.95f, 1f);

        Transform trackingSpace;
        LineRenderer line;
        Material lineMat;

        void Start()
        {
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (panel == null) panel = FindAnyObjectByType<MissionPanel>();
            if (navigator == null) navigator = FindAnyObjectByType<BubbleNavigator>();
            if (keypad == null) keypad = FindAnyObjectByType<IpKeypad>();
            var rig = FindAnyObjectByType<OVRCameraRig>();
            if (rig != null) trackingSpace = rig.trackingSpace;
            if (material == null) material = WorldUI.FallbackUnlit();

            line = gameObject.AddComponent<LineRenderer>();
            line.positionCount = 2;
            line.useWorldSpace = true;
            line.startWidth = 0.004f;
            line.endWidth = 0.001f;
            line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            line.receiveShadows = false;
            lineMat = WorldUI.Tinted(material, null, color);
            line.sharedMaterial = lineMat;
            line.enabled = false;
        }

        void OnDestroy()
        {
            if (lineMat != null) Destroy(lineMat);
        }

        void Update()
        {
            bool onTable = table != null && table.Visible;
            bool onFloor = navigator != null && navigator.IsShowing;
            bool active = XRSettings.isDeviceActive && trackingSpace != null && (onTable || onFloor)
                          && OVRInput.IsControllerConnected(controller);
            line.enabled = active;
            if (!active) return;

            var origin = trackingSpace.TransformPoint(OVRInput.GetLocalControllerPosition(controller));
            var dir = trackingSpace.rotation * OVRInput.GetLocalControllerRotation(controller) * Vector3.forward;
            line.SetPosition(0, origin);
            line.SetPosition(1, origin + dir * length);

            if (OVRInput.GetDown(OVRInput.Button.PrimaryIndexTrigger, controller))
            {
                var ray = new Ray(origin, dir);
                if (onTable)
                {
                    // keypad, then panel buttons, then pins / capture spots
                    if ((keypad == null || !keypad.TrySelect(ray)) && (panel == null || !panel.TrySelect(ray))) table.TrySelect(ray);
                }
                else navigator.TrySelect(ray); // bubble view: floor arrows to neighboring bubbles
            }
        }

#if UNITY_EDITOR
        void Reset()
        {
            table = FindAnyObjectByType<TabletopMap>();
            material = WorldUI.UnlitMaterialAsset();
        }
#endif
    }
}
