using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.XR;

namespace Understory
{
    /// <summary>
    /// Editor/desktop testing without a headset: hold right mouse and drag to look around.
    /// Does nothing while an XR device is active. Put it on the Main Camera.
    /// </summary>
    public class DesktopLook : MonoBehaviour
    {
        [SerializeField] float sensitivity = 0.15f;

        float yaw, pitch;

        void Start()
        {
            var e = transform.eulerAngles;
            yaw = e.y;
            pitch = e.x > 180f ? e.x - 360f : e.x;
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
