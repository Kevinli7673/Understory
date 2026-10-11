"""Upload a mission folder to the cloud: images to an HF Hub dataset, rows to Neon. Safe to re-run (upserts).

    python dashboard/sync.py missions/m1 [missions/m2 ...] [--no-hf] [--public] [--embed] [--dry-run]

Env (.env at the repo root): DATABASE_URL (Neon), HF_TOKEN, HF_DATASET_REPO (e.g. "knight-hacks/understory").
Without DATABASE_URL only the Hugging Face upload runs; the dashboard's "Hugging Face" data source reads it.
--no-hf skips the upload; crop/map URLs are then left null and the dashboard can only show images
when it runs next to the mission folders.
The dataset is created private unless --public is given: frames show whoever stood near the robot. Image
URLs stored in Neon only open in a browser when the dataset is public.
--embed fills missing pin embeddings with BioCLIP on crops/<pin_id>.jpg (needs open_clip_torch).
"""
import argparse
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mission_io import SENSOR_KEYS, load_mission  # noqa: E402

SCHEMA = Path(__file__).resolve().parent / 'schema.sql'
HF_PATTERNS = ['frames/*', 'crops/*', 'crops_deep/*', '*.jsonl', 'map.yaml', 'map.pgm', 'deep_report.json']


def ts(t):
    return datetime.fromtimestamp(t, tz=timezone.utc) if t is not None else None


def vector_literal(embedding):
    return '[' + ','.join(f'{v:.6g}' for v in embedding) + ']' if embedding else None


def map_png_bytes(mission):
    from PIL import Image
    with Image.open(mission['dir'] / mission['map']['image']) as img:
        buf = io.BytesIO()
        img.convert('L').save(buf, format='PNG')
    return buf.getvalue()


def upload_to_hf(mission, repo, public=False):
    from huggingface_hub import HfApi
    api = HfApi(token=os.environ.get('HF_TOKEN'))
    api.create_repo(repo, repo_type='dataset', exist_ok=True, private=not public)
    mid = mission['mission_id']
    api.upload_folder(repo_id=repo, repo_type='dataset', folder_path=str(mission['dir']),
                      path_in_repo=mid, allow_patterns=HF_PATTERNS,
                      commit_message=f'sync {mid}')
    if mission['map']:
        api.upload_file(repo_id=repo, repo_type='dataset', path_or_fileobj=map_png_bytes(mission),
                        path_in_repo=f'{mid}/map.png', commit_message=f'sync {mid} map.png')
    return f'https://huggingface.co/datasets/{repo}/resolve/main/{mid}/'


class Embedder:
    """BioCLIP image encoder, loaded once."""

    def __init__(self):
        import open_clip
        import torch
        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms('hf-hub:imageomics/bioclip')
        self.model.eval()

    def __call__(self, path):
        from PIL import Image
        with Image.open(path) as img:
            x = self.preprocess(img.convert('RGB')).unsqueeze(0)
        with self.torch.no_grad():
            emb = self.model.encode_image(x).float()
        emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb[0].tolist()


def fill_embeddings(mission, embedder):
    for pin in mission['pins']:
        if pin.get('embedding'):
            continue
        crop_dir = 'crops_deep' if pin['source'] == 'deep' else 'crops'
        path = mission['dir'] / crop_dir / pin.get('crop', f"{pin['pin_id']}.jpg")
        if path.exists():
            pin['embedding'] = embedder(path)


def upsert(conn, mission, base_url):
    mid, m = mission['mission_id'], mission['map'] or {}
    with conn.cursor() as cur:
        cur.execute(SCHEMA.read_text())
        cur.execute(
            """insert into missions (mission_id, started_at, ended_at, asset_base_url, map_url, map_resolution,
                   map_origin_x, map_origin_y, map_width, map_height, synced_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
               on conflict (mission_id) do update set
                   started_at = excluded.started_at, ended_at = excluded.ended_at,
                   asset_base_url = excluded.asset_base_url, map_url = excluded.map_url,
                   map_resolution = excluded.map_resolution, map_origin_x = excluded.map_origin_x,
                   map_origin_y = excluded.map_origin_y, map_width = excluded.map_width,
                   map_height = excluded.map_height, synced_at = now()""",
            (mid, ts(mission['started_at']), ts(mission['ended_at']), base_url,
             base_url + 'map.png' if base_url and m else None, m.get('resolution'),
             m.get('origin_x'), m.get('origin_y'), m.get('width'), m.get('height')))

        cur.executemany(
            """insert into bubbles (bubble_id, mission_id, t, x, y, stitched, hfov, frames)
               values (%s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (bubble_id) do update set
                   t = excluded.t, x = excluded.x, y = excluded.y, stitched = excluded.stitched,
                   hfov = excluded.hfov, frames = excluded.frames""",
            [(b['bubble_id'], mid, ts(b.get('t')), b.get('x'), b.get('y'), b.get('stitched'), b.get('hfov'),
              json.dumps(b.get('frames', []))) for b in mission['bubbles']])

        def crop_url(p):
            if not base_url:
                return None
            crop_dir = 'crops_deep' if p['source'] == 'deep' else 'crops'
            return f"{base_url}{crop_dir}/{p.get('crop', p['pin_id'] + '.jpg')}"

        cur.executemany(
            """insert into pins (pin_id, mission_id, bubble_id, source, label, invasive, confidence, yaw, x, y,
                   crop_url, embedding)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
               on conflict (pin_id) do update set
                   bubble_id = excluded.bubble_id, source = excluded.source, label = excluded.label,
                   invasive = excluded.invasive, confidence = excluded.confidence, yaw = excluded.yaw,
                   x = excluded.x, y = excluded.y, crop_url = coalesce(excluded.crop_url, pins.crop_url),
                   embedding = coalesce(excluded.embedding, pins.embedding)""",
            [(p['pin_id'], mid, p.get('bubble_id'), p['source'], p['label'], bool(p.get('invasive')),
              p.get('confidence'), p.get('yaw'), p.get('x'), p.get('y'), crop_url(p),
              vector_literal(p.get('embedding'))) for p in mission['pins']])

        cols = ['mission_id', 't', 'x', 'y'] + SENSOR_KEYS
        updates = ', '.join(f'{c} = excluded.{c}' for c in cols[2:])
        cur.executemany(
            f"""insert into readings ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})
                on conflict (mission_id, t) do update set {updates}""",
            [(mid, ts(r['t']), r.get('x'), r.get('y'), *[r.get(k) for k in SENSOR_KEYS])
             for r in mission['readings']])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('missions', nargs='+', type=Path)
    parser.add_argument('--no-hf', action='store_true', help='skip the HF Hub upload')
    parser.add_argument('--public', action='store_true', help='create the HF dataset public (default private)')
    parser.add_argument('--embed', action='store_true', help='BioCLIP embeddings for pins that lack one')
    parser.add_argument('--dry-run', action='store_true', help='read and summarize, write nothing')
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    db_url = os.environ.get('DATABASE_URL')
    repo = os.environ.get('HF_DATASET_REPO')
    if not args.dry_run and not args.no_hf and not repo:
        sys.exit('HF_DATASET_REPO is not set; set it in .env or pass --no-hf')
    if not args.dry_run and not db_url:
        if args.no_hf:
            sys.exit('DATABASE_URL is not set (put it in .env) and --no-hf was given: nothing to do')
        print('DATABASE_URL is not set: uploading to Hugging Face only, nothing goes to Neon')

    embedder = Embedder() if args.embed else None
    conn = None
    if not args.dry_run and db_url:
        import psycopg
        conn = psycopg.connect(db_url)

    for mission_dir in args.missions:
        mission = load_mission(mission_dir)
        mid = mission['mission_id']
        if embedder:
            fill_embeddings(mission, embedder)
        n_emb = sum(bool(p.get('embedding')) for p in mission['pins'])
        print(f"{mid}: {len(mission['bubbles'])} bubbles, {len(mission['pins'])} pins "
              f"({n_emb} with embeddings), {len(mission['readings'])} readings, "
              f"map={'yes' if mission['map'] else 'no'}")
        if args.dry_run:
            continue
        base_url = None if args.no_hf else upload_to_hf(mission, repo, args.public)
        if base_url:
            print(f'  uploaded to {base_url}')
        if conn:
            upsert(conn, mission, base_url)
            print('  upserted into Neon')

    if conn:
        conn.close()


if __name__ == '__main__':
    main()
