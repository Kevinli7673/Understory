using UnityEngine;
using UnityEngine.XR;

namespace Understory
{
    /// <summary>
    /// Controls cheat sheet standing at the left edge of the tabletop, for anyone trying the headset at the
    /// demo table. Shows the desktop keys instead when no headset is active.
    /// </summary>
    public class ControlsHint : MonoBehaviour
    {
        [SerializeField] TabletopMap table;

        const string Quest =
            "<b>CONTROLS</b>\n" +
            "R trigger   select spot / pin / button\n" +
            "A           table  <->  bubble view\n" +
            "<color=#ff5544>B           E-STOP (again to release)</color>\n" +
            "L stick     drive + strafe\n" +
            "R stick     turn\n" +
            "L grip      move the table\n" +
            "X (hold)    talk to the robot";

        const string Desktop =
            "<b>CONTROLS (editor)</b>\n" +
            "click       select spot / pin / button\n" +
            "Tab         table <-> bubble view\n" +
            "<color=#ff5544>Space       E-STOP</color>\n" +
            "WASD / QE   drive / turn\n" +
            "right-drag  look around\n" +
            "T (hold)    talk   ·   C recenter\n" +
            "V compare · H sensors · M 3D model\n" +
            "[ ] bubbles · R pano";

        TextMesh text;
        bool lastXr;
        IpKeypad keypad;

        void Start()
        {
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (table == null) { enabled = false; return; }
            keypad = FindAnyObjectByType<IpKeypad>();
            table.LayoutChanged += Place;
        }

        void OnDestroy()
        {
            if (table != null) table.LayoutChanged -= Place;
        }

        void Update()
        {
            if (text == null && table.Root != null)
            {
                text = WorldUI.MakeLabel(table.Root, "", new Color(0.85f, 0.88f, 0.9f), 0.014f, TextAnchor.LowerLeft);
                text.name = "ControlsHint";
                text.richText = true;
                text.alignment = TextAlignment.Left;
                lastXr = !XRSettings.isDeviceActive; // force the first refresh
                Place();
            }
            if (text == null) return;
            // The robot-address keypad opens in the same spot.
            text.gameObject.SetActive(keypad == null || !keypad.IsOpen);
            bool xr = XRSettings.isDeviceActive;
            if (xr != lastXr) { text.text = xr ? Quest : Desktop; lastXr = xr; }
        }

        /// <summary>Left of the board, near the viewer, leaning back.</summary>
        void Place()
        {
            if (text == null) return;
            var half = table.HalfExtents;
            text.transform.localPosition = new Vector3(-half.x - 0.32f, 0.02f, -half.y * 0.6f);
            text.transform.localRotation = Quaternion.Euler(-35f, 20f, 0f);
        }
    }
}
