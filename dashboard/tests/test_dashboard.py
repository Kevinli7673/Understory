import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from mission_io import before_after_summary, bin_readings, load_mission, map_extent, match_pins  # noqa: E402

FAKE = HERE.parent.parent / 'fake_data' / 'missions'


def pin(pid, label, x, y, invasive=True):
    return {'pin_id': pid, 'label': label, 'x': x, 'y': y, 'invasive': invasive}


def test_match_same_label_within_radius():
    before = [pin('a', 'Cogongrass', 0, 0), pin('b', 'Air potato', 1, 1)]
    after = [pin('c', 'Cogongrass', 0.3, 0.3), pin('d', 'Air potato', 2, 2)]
    pairs, removed, new = match_pins(before, after)
    assert [(b['pin_id'], a['pin_id']) for b, a, _ in pairs] == [('a', 'c')]
    assert [p['pin_id'] for p in removed] == ['b']
    assert [p['pin_id'] for p in new] == ['d']


def test_match_ignores_other_labels_and_is_one_to_one():
    before = [pin('a', 'Cogongrass', 0, 0)]
    after = [pin('c', 'Air potato', 0, 0), pin('d', 'Cogongrass', 0.1, 0), pin('e', 'Cogongrass', 0.2, 0)]
    pairs, removed, new = match_pins(before, after)
    assert [(b['pin_id'], a['pin_id']) for b, a, _ in pairs] == [('a', 'd')]
    assert {p['pin_id'] for p in new} == {'c', 'e'}


def test_fake_before_after_headline():
    m1, m2 = load_mission(FAKE / 'm1'), load_mission(FAKE / 'm2')
    _, totals, *_ = before_after_summary(m1['pins'], m2['pins'])
    assert (totals['found'], totals['remaining'], totals['new']) == (7, 1, 0)


def test_fake_mission_loads_with_map():
    m = load_mission(FAKE / 'm1')
    assert len(m['bubbles']) == 5 and len(m['pins']) == 11
    x0, x1, y0, y1 = map_extent(m['map'])
    assert x0 == pytest.approx(-2.5) and y0 == pytest.approx(-2.5) and x1 > x0 and y1 > y0
    for p in m['pins']:
        assert x0 <= p['x'] <= x1 and y0 <= p['y'] <= y1


def test_bin_readings_skips_missing_keys():
    readings = [{'x': 0.1, 'y': 0.1, 'uv': 1.0}, {'x': 0.2, 'y': 0.2, 'uv': 3.0}, {'x': 0.3, 'y': 0.3}]
    assert bin_readings(readings, 'uv') == {(0, 0): 2.0}


def test_app_renders_on_fake_data(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('MISSIONS_DIR', str(FAKE))
    monkeypatch.setenv('LIVE_RELAY_URL', 'http://127.0.0.1:9')  # nothing listens: live panels show offline
    at = AppTest.from_file(str(HERE.parent / 'app.py'), default_timeout=60).run()
    assert not at.exception, at.exception
    assert len(at.tabs) == 0  # one page: no Sensors / Before-after / Similar tabs
    assert [m.label for m in at.metric][:4] == ['Plants pinned', 'Invasive', 'Species', 'Duration']
    assert any('LiDAR offline' in m.value for m in at.markdown)  # no relay running in tests
    assert any('Live stream view of the headset' in m.value for m in at.markdown)


def test_app_reads_the_hugging_face_dataset(monkeypatch, tmp_path):
    """The Hugging Face source downloads the dataset and reads it like mission folders. No network here."""
    import shutil

    import huggingface_hub
    from streamlit.testing.v1 import AppTest
    calls = []

    def fake_download(repo_id, local_dir, **kwargs):
        calls.append((repo_id, kwargs.get('repo_type')))
        shutil.copytree(FAKE, local_dir, dirs_exist_ok=True)
        return local_dir

    monkeypatch.setattr(huggingface_hub, 'snapshot_download', fake_download)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('MISSIONS_DIR', str(tmp_path / 'empty'))
    monkeypatch.setenv('HF_DATASET_REPO', 'someone/understory-missions')
    monkeypatch.setenv('HF_MISSIONS_CACHE', str(tmp_path / 'cache'))
    monkeypatch.setenv('LIVE_RELAY_URL', 'http://127.0.0.1:9')
    at = AppTest.from_file(str(HERE.parent / 'app.py'), default_timeout=60).run()
    at.sidebar.radio[0].set_value('Hugging Face').run()
    assert not at.exception, at.exception
    assert calls == [('someone/understory-missions', 'dataset')]
    assert at.sidebar.selectbox[0].options == ['m1', 'm2']
    assert [m.value for m in at.metric][:2] == ['11', '7']
    assert any('Hugging Face</span>' in m.value for m in at.markdown)


def test_sync_without_neon_uploads_to_hugging_face_only(monkeypatch, capsys):
    import sync
    uploaded = []
    monkeypatch.setattr(sync, 'load_dotenv', lambda *a, **k: None)
    monkeypatch.setattr(sync, 'upload_to_hf', lambda mission, repo, public=False: uploaded.append(
        (mission['mission_id'], repo, public)) or 'https://example.invalid/m1/')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('HF_DATASET_REPO', 'someone/understory-missions')
    monkeypatch.setattr(sys, 'argv', ['sync.py', str(FAKE / 'm1')])
    sync.main()
    assert uploaded == [('m1', 'someone/understory-missions', False)]
    assert 'nothing goes to Neon' in capsys.readouterr().out
