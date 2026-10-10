using UnityEngine;
using UnityEngine.XR;

namespace Understory
{
    /// <summary>
    /// Hold the left grip to move the tabletop map: it follows the hand's movement and turns with the hand's
    /// yaw (stays level). The table re-centers in front of you again when you come back from the bubble view.
    /// </summary>
    public class TableGrab : MonoBehaviour
    {
        [SerializeField] TabletopMap table;
        [SerializeField] OVRInput.Controller controller = OVRInput.Controller.LTouch;

        Transform trackingSpace;
        bool grabbing;
        Vector3 startHand, startTable;
        float startHandYaw;
        Quaternion startTableRot;

        void Start()
        {
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            var rig = FindAnyObjectByType<OVRCameraRig>();
            if (rig != null) trackingSpace = rig.trackingSpace;
        }

        void Update()
        {
            if (!XRSettings.isDeviceActive || trackingSpace == null || table == null || table.Root == null || !table.Visible)
            {
                grabbing = false;
                return;
            }

            var hand = trackingSpace.TransformPoint(OVRInput.GetLocalControllerPosition(controller));
            float handYaw = (trackingSpace.rotation * OVRInput.GetLocalControllerRotation(controller)).eulerAngles.y;

            if (OVRInput.GetDown(OVRInput.Button.PrimaryHandTrigger, controller))
            {
                grabbing = true;
                startHand = hand;
                startHandYaw = handYaw;
                startTable = table.Root.position;
                startTableRot = table.Root.rotation;
                Haptics.Buzz(this, 0.2f, 0.04f, controller);
            }
            if (grabbing && !OVRInput.Get(OVRInput.Button.PrimaryHandTrigger, controller)) grabbing = false;
            if (!grabbing) return;

            // Rotate about the hand's start point by the change in hand yaw, then follow the hand.
            var turn = Quaternion.Euler(0f, Mathf.DeltaAngle(startHandYaw, handYaw), 0f);
            table.Root.SetPositionAndRotation(hand + turn * (startTable - startHand), turn * startTableRot);
        }
    }
}
