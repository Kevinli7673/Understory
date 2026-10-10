using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR;

namespace Understory
{
    /// <summary>
    /// Editor/desktop testing without a headset: hold right mouse and drag to look around.
    /// Does nothing while an XR device is active. Put it on the camera, or on the OVRCameraRig root
    /// (tracking overwrites the eye camera's own rotation).
    /// </summary>
    public class DesktopLook : MonoBehaviour
    {
        [SerializeField] float sensitivity = 0.15f;
        [Tooltip("Without a headset a floor-level rig has its eyes on the floor; lift it this much (meters).")]
        [SerializeField] float desktopEyeHeight;

        float yaw, pitch;

        void Start()
        {
            var e = transform.eulerAngles;
            yaw = e.y;
            pitch = e.x > 180f ? e.x - 360f : e.x;
            if (!XRSettings.isDeviceActive && desktopEyeHeight > 0f) transform.position += Vector3.up * desktopEyeHeight;
        }

        void Update()
        {
            if (XRSettings.isDeviceActive) return;
            var mouse = Mouse.current;
            if (mouse == null || !mouse.rightButton.isPressed) return;
            var d = mouse.delta.ReadValue() * sensitivity;
            yaw += d.x;
            pitch = Mathf.Clamp(pitch - d.y, -85f, 85f);
            transform.rotation = Quaternion.Euler(pitch, yaw, 0f);
        }
    }
}
