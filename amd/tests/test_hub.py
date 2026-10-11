"""Tests for the plain parts of hub.py (no network, no huggingface_hub).  python -m pytest amd/tests"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from hub import PUSH, pull_patterns, read_env, setting, splat_uploads  # noqa: E402


def test_read_env(tmp_path):
    env = tmp_path / '.env'
    env.write_text('# cloud\nHF_TOKEN="hf_abc"\n\nHF_DATASET_REPO = someone/understory-missions\nnot a setting\n'
                   "DATABASE_URL='postgresql://u:p@host/db?sslmode=require'\n")
    assert read_env(env) == {'HF_TOKEN': 'hf_abc', 'HF_DATASET_REPO': 'someone/understory-missions',
                             'DATABASE_URL': 'postgresql://u:p@host/db?sslmode=require'}
    assert read_env(tmp_path / 'missing') == {}


def test_environment_wins_over_the_file(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('HF_DATASET_REPO=from/file\n')
    monkeypatch.delenv('HF_DATASET_REPO', raising=False)
    assert setting('HF_DATASET_REPO', env) == 'from/file'
    monkeypatch.setenv('HF_DATASET_REPO', 'from/environment')
    assert setting('HF_DATASET_REPO', env) == 'from/environment'


def test_pull_takes_what_the_deep_pass_reads_and_only_that_mission():
    patterns = pull_patterns('m1')
    assert 'm1/frames/*' in patterns and 'm1/map.pgm' in patterns and 'm1/*.jsonl' in patterns
    assert all(p.startswith('m1/') for p in patterns)


def test_push_never_sends_the_live_pins_back():
    assert 'pins.jsonl' not in PUSH and '*.jsonl' not in PUSH and 'crops/*' not in PUSH
    assert 'pins_deep.jsonl' in PUSH and 'deep_report.json' in PUSH


def test_splat_uploads_lists_only_files_that_exist(tmp_path):
    assert splat_uploads('m1', tmp_path) == []
    (tmp_path / 'scene.splat').write_bytes(b'x')
    assert splat_uploads('m1', tmp_path) == [(tmp_path / 'scene.splat', 'm1/scene.splat')]
