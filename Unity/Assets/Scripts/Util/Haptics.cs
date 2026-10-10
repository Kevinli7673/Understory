using System.Collections;
using UnityEngine;

namespace Understory
{
    /// <summary>Short controller buzzes. A newer buzz on the same host replaces the running one.</summary>
    public static class Haptics
    {
        static Coroutine running;
        static MonoBehaviour runningHost;

        public static void Buzz(MonoBehaviour host, float amplitude, float seconds,
            OVRInput.Controller controller = OVRInput.Controller.Touch)
        {
            if (host == null || !host.isActiveAndEnabled) return;
            if (running != null && runningHost != null) runningHost.StopCoroutine(running);
            runningHost = host;
            running = host.StartCoroutine(Routine(amplitude, seconds, controller));
        }

        static IEnumerator Routine(float amplitude, float seconds, OVRInput.Controller controller)
        {
            OVRInput.SetControllerVibration(1f, Mathf.Clamp01(amplitude), controller);
            yield return new WaitForSecondsRealtime(seconds);
            OVRInput.SetControllerVibration(0f, 0f, controller);
            running = null;
            runningHost = null;
        }
    }
}
