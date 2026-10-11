"""Move a mission between machines through the Hugging Face dataset that dashboard/sync.py fills.

The W7900 box then needs no route to the Jetson:

    python amd/hub.py upload missions/m1          # on the Jetson: the whole mission folder -> dataset
    python amd/hub.py pull m1                     # dataset -> missions/m1 (frames, map, bubbles, live pins)
    python amd/deep_pass.py missions/m1
    bash splat/run.sh missions/m1
    python amd/hub.py push missions/m1            # deep pins, deep crops, the report and the splat -> dataset

Settings, from the environment or from .env at the repo root: HF_DATASET_REPO (for example
"your-name/understory-missions") and HF_TOKEN. A public dataset can be pulled without a token; push needs
one with write access. `--repo` overrides HF_DATASET_REPO.

`upload` sends the same files to the same place as dashboard/sync.py, without needing Neon. It creates the
dataset if it does not exist, PRIVATE unless --public is given: frames show whoever stood near the robot.
"""
import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# what the deep pass and the splat read: everything dashboard/sync.py uploads for a mission
PULL = ['frames/*', 'crops/*', '*.jsonl', 'map.yaml', 'map.pgm']
# what this box adds. The live pins.jsonl and crops/ are never sent back
PUSH = ['pins_deep.jsonl', 'deep_report.json', 'crops_deep/*']
SPLAT_FILES = ['scene.splat', 'scene.ply']


def read_env(path):
    """KEY=value lines of a .env file. Quotes around the value are dropped; comments and blanks are skipped."""
    values = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return values


def setting(name, env_file=None):
    return os.environ.get(name) or read_env(env_file or REPO_ROOT / '.env').get(name)


def pull_patterns(mission_id):
    return [f'{mission_id}/{p}' for p in PULL]


def splat_uploads(mission_id, splat_dir):
    """(local path, path in the dataset) for each splat output that exists."""
    found = []
    for name in SPLAT_FILES:
        path = Path(splat_dir) / name
        if path.is_file():
            found.append((path, f'{mission_id}/{name}'))
    return found


def upload(folder, repo, token, public):
    from huggingface_hub import HfApi
    folder = Path(folder)
    mission_id = folder.name
    if not (folder / 'bubbles.jsonl').is_file():
        sys.exit(f'{folder}/bubbles.jsonl is missing: no bubble was captured in this mission')
    api = HfApi(token=token)
    api.create_repo(repo, repo_type='dataset', exist_ok=True, private=not public)
    api.upload_folder(repo_id=repo, repo_type='dataset', folder_path=str(folder), path_in_repo=mission_id,
                      allow_patterns=PULL + PUSH, commit_message=f'mission {mission_id}')
    print(f'https://huggingface.co/datasets/{repo}/tree/main/{mission_id}')


def pull(mission_id, repo, token, dest):
    from huggingface_hub import snapshot_download
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=repo, repo_type='dataset', token=token, local_dir=str(dest),
                      allow_patterns=pull_patterns(mission_id))
    folder = dest / mission_id
    frames = len(list((folder / 'frames').glob('*.jpg'))) if (folder / 'frames').is_dir() else 0
    if not folder.is_dir():
        sys.exit(f'{repo} has no folder {mission_id}/. Upload it first: python dashboard/sync.py missions/{mission_id}')
    print(f'{folder}: {frames} frames, map {"yes" if (folder / "map.pgm").is_file() else "MISSING"}, '
          f'bubbles {"yes" if (folder / "bubbles.jsonl").is_file() else "MISSING"}')
    return folder


def push(folder, repo, token, splat_dir):
    from huggingface_hub import HfApi
    folder = Path(folder)
    mission_id = folder.name
    if not (folder / 'pins_deep.jsonl').is_file():
        sys.exit(f'{folder}/pins_deep.jsonl is missing. Run: python amd/deep_pass.py {folder}')
    api = HfApi(token=token)
    api.upload_folder(repo_id=repo, repo_type='dataset', folder_path=str(folder), path_in_repo=mission_id,
                      allow_patterns=PUSH, commit_message=f'deep pass {mission_id}')
    sent = splat_uploads(mission_id, splat_dir)
    for path, target in sent:
        api.upload_file(repo_id=repo, repo_type='dataset', path_or_fileobj=str(path), path_in_repo=target,
                        commit_message=f'splat {target}')
    print(f'https://huggingface.co/datasets/{repo}/tree/main/{mission_id}  '
          f'(deep pass sent; splat files: {[t for _, t in sent] or "none found in " + str(splat_dir)})')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', choices=['upload', 'pull', 'push'])
    ap.add_argument('mission', help='pull: the mission id (m1). upload and push: the mission folder (missions/m1)')
    ap.add_argument('--repo', help='dataset repo; default HF_DATASET_REPO')
    ap.add_argument('--dest', default='missions', help='pull: where mission folders go (default missions/)')
    ap.add_argument('--public', action='store_true', help='upload: create the dataset public (default private)')
    ap.add_argument('--splat-dir', help='push: folder with scene.splat (default splat/out/<id>)')
    args = ap.parse_args()
    repo = args.repo or setting('HF_DATASET_REPO')
    if not repo:
        sys.exit('No dataset repo. Put HF_DATASET_REPO=<name>/understory-missions in .env or pass --repo')
    token = setting('HF_TOKEN')
    if args.action == 'pull':
        pull(args.mission, repo, token, args.dest)
        return
    if not token:
        sys.exit(f'{args.action} needs HF_TOKEN (write access) in the environment or in .env')
    if args.action == 'upload':
        upload(args.mission, repo, token, args.public)
    else:
        mission_id = Path(args.mission).name
        push(args.mission, repo, token, args.splat_dir or REPO_ROOT / 'splat' / 'out' / mission_id)


if __name__ == '__main__':
    main()
