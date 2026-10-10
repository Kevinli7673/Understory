using System.Collections.Generic;
using UnityEngine;

namespace Understory
{
    /// <summary>
    /// "New species" popup in front of the viewer + controller buzz (stronger for invasives), once per label
    /// per mission (SurveyHub.NewSpeciesSeen). Queued so a burst of detections doesn't overlap.
    /// </summary>
    public class SpeciesAlert : MonoBehaviour
    {
        [SerializeField] SurveyHub hub;
        [SerializeField] float showSeconds = 2.5f;
        [SerializeField] int maxQueued = 3;

        readonly Queue<Pin> pending = new Queue<Pin>();
        TextMesh toast;
        float hideAt;

        void Start()
        {
            if (hub == null) hub = SurveyHub.Instance;
            if (hub == null) { enabled = false; return; }
            hub.NewSpeciesSeen += OnNewSpecies;
            hub.Cleared += OnCleared;
            toast = WorldUI.MakeLabel(null, "", Color.white, 0.045f, TextAnchor.MiddleCenter);
            toast.richText = true;
            toast.name = "SpeciesToast";
            toast.gameObject.SetActive(false);
        }

        void OnDestroy()
        {
            if (hub != null)
            {
                hub.NewSpeciesSeen -= OnNewSpecies;
                hub.Cleared -= OnCleared;
            }
            if (toast != null) Destroy(toast.gameObject);
        }

        void OnNewSpecies(Pin p)
        {
            pending.Enqueue(p);
            while (pending.Count > maxQueued) pending.Dequeue();
        }

        void OnCleared()
        {
            pending.Clear();
            if (toast != null) toast.gameObject.SetActive(false);
        }

        void Update()
        {
            if (toast == null) return;
            if (toast.gameObject.activeSelf && Time.unscaledTime < hideAt) return;
            if (pending.Count == 0) { toast.gameObject.SetActive(false); return; }

            var p = pending.Dequeue();
            toast.text = p.Invasive
                ? $"<color=#ff5544>INVASIVE</color>\n{p.Label}\n<size=32>{p.Confidence:P0}</size>"
                : $"<color=#66ee88>New species</color>\n{p.Label}\n<size=32>{p.Confidence:P0}</size>";
            toast.gameObject.SetActive(true);
            hideAt = Time.unscaledTime + showSeconds;
            Haptics.Buzz(this, p.Invasive ? 0.9f : 0.35f, p.Invasive ? 0.25f : 0.1f);
        }

        void LateUpdate()
        {
            if (toast == null || !toast.gameObject.activeSelf || Camera.main == null) return;
            var t = Camera.main.transform;
            toast.transform.SetPositionAndRotation(t.position + t.forward * 1.2f + t.up * 0.2f, Quaternion.LookRotation(t.forward, t.up));
        }
    }
}
