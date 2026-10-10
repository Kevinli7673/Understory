using UnityEngine;
using UnityEngine.InputSystem;

namespace Understory
{
    /// <summary>
    /// Tabletop map twin vs. immersive bubble view (only one at a time: the bubble's backdrop would
    /// swallow the table). A button (right controller) or Tab toggles; picking a bubble on the table opens it.
    /// B is reserved for e-stop.
    /// </summary>
    public class ViewSwitcher : MonoBehaviour
    {
        public enum Mode { Tabletop, Bubble }

        [SerializeField] TabletopMap table;
        [SerializeField] BubbleRingBuilder ring;
        [SerializeField] Mode startMode = Mode.Tabletop;

        public Mode Current { get; private set; }

        void Start()
        {
            if (table == null) table = FindAnyObjectByType<TabletopMap>();
            if (ring == null) ring = FindAnyObjectByType<BubbleRingBuilder>();
            if (table != null) table.BubbleSelected += OpenBubble;
            Set(startMode);
        }

        void OnDestroy()
        {
            if (table != null) table.BubbleSelected -= OpenBubble;
        }

        void Update()
        {
            var kb = Keyboard.current;
            bool toggle = (kb != null && kb.tabKey.wasPressedThisFrame) || OVRInput.GetDown(OVRInput.Button.One);
            if (!toggle) return;
            if (Current == Mode.Tabletop)
            {
                if (ring != null) ring.FollowLatest(); // button = live view; picking a disc = that bubble
                Set(Mode.Bubble);
            }
            else Set(Mode.Tabletop);
        }

        /// <summary>Open one bubble and stay on it (new bubbles don't take over).</summary>
        public void OpenBubble(string bubbleId)
        {
            if (ring != null) ring.Show(bubbleId);
            Set(Mode.Bubble);
        }

        public void Set(Mode mode)
        {
            Current = mode;
            if (table != null)
            {
                table.Visible = mode == Mode.Tabletop;
                if (mode == Mode.Tabletop) table.Recenter();
            }
            if (ring != null) ring.Visible = mode == Mode.Bubble;
        }
    }
}
