"""Understory survey dashboard.

    streamlit run dashboard/app.py

Reads from Neon when DATABASE_URL is set (after sync.py), otherwise straight from mission folders
(MISSIONS_DIR, default missions/ then fake_data/missions/). The folder path is the offline fallback:
it needs no internet. With HF_DATASET_REPO set, "Hugging Face" downloads the dataset that sync.py and
amd/hub.py fill and reads it the same way as local folders (the last download is kept for offline use).
"""
import base64
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mission_io import (MATCH_RADIUS_M, SENSOR_KEYS, before_after_summary, bin_readings,  # noqa: E402
                        load_mission, map_extent)

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / '.env')

# Reference palette (dataviz skill): categorical slots 1-3, sequential blue, recessive gray.
BLUE, ORANGE, AQUA, GRAY = '#2a78d6', '#eb6834', '#1baf7a', '#8a8984'
SEQ_BLUE = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']
SENSOR_NAMES = {
    'temp_c': 'Temperature (°C)', 'pressure_hpa': 'Pressure (hPa)', 'soil_moisture': 'Soil moisture (raw)',
    'light': 'Light (raw)', 'uv': 'UV index', 'air_quality': 'Air quality (raw)', 'sound': 'Sound (raw)',
}

st.set_page_config(page_title='Understory survey', page_icon='🌿', layout='wide')


# ---------- data sources ----------

def local_root():
    if os.environ.get('MISSIONS_DIR'):
        return Path(os.environ['MISSIONS_DIR'])
    for candidate in (REPO / 'missions', REPO / 'fake_data' / 'missions'):
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    return REPO / 'missions'


@st.cache_data(ttl=30)
def local_mission_ids(root):
    return sorted(p.name for p in Path(root).iterdir() if (p / 'pins.jsonl').exists() or (p / 'bubbles.jsonl').exists())


@st.cache_data(ttl=30)
def local_mission(root, mid):
    m = load_mission(Path(root) / mid)
    m['dir'] = str(m['dir'])
    m['map_source'] = str(Path(m['dir']) / m['map']['image']) if m['map'] else None
    m['asset_base'] = m['dir'] + '/'
    return m


def hf_cache_dir(repo):
    base = os.environ.get('HF_MISSIONS_CACHE') or Path.home() / '.cache' / 'understory' / 'hf_missions'
    return Path(base) / repo.replace('/', '__')


@st.cache_data(ttl=300)
def hf_root(repo):
    """Download the dataset (only files that changed) and return the folder. A private dataset needs HF_TOKEN."""
    from huggingface_hub import snapshot_download
    dest = hf_cache_dir(repo)
    snapshot_download(repo_id=repo, repo_type='dataset', token=os.environ.get('HF_TOKEN') or None,
                      local_dir=str(dest), ignore_patterns=['*.splat', '*.ply'])
    return str(dest)


def db_connect():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)


@st.cache_data(ttl=30)
def db_mission_ids():
    with db_connect() as conn:
        return [r['mission_id'] for r in conn.execute('select mission_id from missions order by mission_id')]


@st.cache_data(ttl=30)
def db_mission(mid):
    with db_connect() as conn:
        mrow = conn.execute('select * from missions where mission_id = %s', (mid,)).fetchone()
        bubbles = conn.execute('select bubble_id, mission_id, extract(epoch from t) as t, x, y, stitched, hfov, '
                               'frames from bubbles where mission_id = %s order by bubble_id', (mid,)).fetchall()
        pins = conn.execute('select pin_id, mission_id, bubble_id, source, label, invasive, confidence, yaw, x, y, '
                            'crop_url, embedding is not null as has_embedding from pins where mission_id = %s '
                            'order by pin_id', (mid,)).fetchall()
        readings = conn.execute(f"select extract(epoch from t) as t, x, y, {', '.join(SENSOR_KEYS)} from readings "
                                'where mission_id = %s order by t', (mid,)).fetchall()
    readings = [{k: (float(v) if v is not None else None) for k, v in r.items()} for r in readings]
    readings = [{k: v for k, v in r.items() if v is not None} for r in readings]  # omitted, not null
    for b in bubbles:
        b['t'] = float(b['t']) if b['t'] is not None else None
    meta = None
    if mrow['map_resolution'] is not None:
        meta = {'resolution': mrow['map_resolution'], 'origin_x': mrow['map_origin_x'],
                'origin_y': mrow['map_origin_y'], 'width': mrow['map_width'], 'height': mrow['map_height']}
    times = [x['t'] for x in bubbles + readings if x.get('t') is not None]
    return {'mission_id': mid, 'bubbles': bubbles, 'pins': pins, 'readings': readings, 'map': meta,
            'map_source': mrow['map_url'], 'asset_base': mrow['asset_base_url'],
            'started_at': min(times) if times else None, 'ended_at': max(times) if times else None}


def image_src(mission, rel_path):
    """A path st.image / st.dataframe can show: a URL from HF, or a data URI for a local file."""
    base = mission.get('asset_base')
    if not base:
        return None
    if base.startswith('http'):
        return base + rel_path
    path = Path(base) / rel_path
    if not path.exists():
        return None
    return 'data:image/jpeg;base64,' + base64.b64encode(path.read_bytes()).decode()


def crop_src(mission, pin):
    if pin.get('crop_url'):
        return pin['crop_url']
    crop_dir = 'crops_deep' if pin.get('source') == 'deep' else 'crops'
    return image_src(mission, f"{crop_dir}/{pin.get('crop', pin['pin_id'] + '.jpg')}")


# ---------- figures ----------

def map_figure(mission, height=560):
    fig = go.Figure()
    meta = mission['map']
    if meta:
        x0, x1, y0, y1 = map_extent(meta)
        source = mission['map_source']
        if source and not str(source).startswith('http'):
            from PIL import Image
            source = Image.open(source).convert('L')
        fig.add_layout_image(source=source, xref='x', yref='y', x=x0, y=y1, sizex=x1 - x0, sizey=y1 - y0,
                             sizing='stretch', opacity=0.55, layer='below')
        fig.update_xaxes(range=[x0, x1])
        fig.update_yaxes(range=[y0, y1])
    fig.update_xaxes(title='x (m)', showgrid=False, zeroline=False)
    fig.update_yaxes(title='y (m)', showgrid=False, zeroline=False, scaleanchor='x', scaleratio=1)
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation='h', yanchor='bottom', y=1.01, x=0))
    return fig


def add_path(fig, readings):
    pts = [(r['x'], r['y']) for r in readings if 'x' in r and 'y' in r]
    if pts:
        xs, ys = zip(*pts)
        fig.add_trace(go.Scatter(x=xs, y=ys, mode='lines', name='Robot path',
                                 line=dict(color=GRAY, width=2, dash='dot'), hoverinfo='skip'))


def add_bubbles(fig, bubbles):
    if not bubbles:
        return
    fig.add_trace(go.Scatter(
        x=[b['x'] for b in bubbles], y=[b['y'] for b in bubbles], mode='markers+text', name='360° bubble',
        text=[b['bubble_id'].split('-')[-1] for b in bubbles], textposition='top center',
        marker=dict(symbol='circle-open', size=16, color=GRAY, line=dict(width=2)),
        customdata=[[b['bubble_id'], 'stitched' if b.get('stitched') else 'ring'] for b in bubbles],
        hovertemplate='%{customdata[0]}<br>%{customdata[1]}<br>(%{x:.2f}, %{y:.2f}) m<extra></extra>'))


def add_pins(fig, pins, name, color, symbol, size=13):
    if not pins:
        return
    fig.add_trace(go.Scatter(
        x=[p['x'] for p in pins], y=[p['y'] for p in pins], mode='markers', name=name,
        marker=dict(symbol=symbol, size=size, color=color, line=dict(width=2, color='white')),
        customdata=[[p['pin_id'], p['label'], p.get('confidence') or 0] for p in pins],
        hovertemplate='%{customdata[1]}<br>%{customdata[0]} · conf %{customdata[2]:.2f}'
                      '<br>(%{x:.2f}, %{y:.2f}) m<extra></extra>'))


def heat_figure(mission, key, cell_m):
    cells = bin_readings(mission['readings'], key, cell_m)
    fig = map_figure(mission)
    if cells:
        ixs = [c[0] for c in cells]
        iys = [c[1] for c in cells]
        xs = np.arange(min(ixs), max(ixs) + 1)
        ys = np.arange(min(iys), max(iys) + 1)
        z = np.full((len(ys), len(xs)), np.nan)
        for (ix, iy), v in cells.items():
            z[iy - ys[0], ix - xs[0]] = v
        fig.add_trace(go.Heatmap(
            x=(xs + 0.5) * cell_m, y=(ys + 0.5) * cell_m, z=z, opacity=0.8, name=SENSOR_NAMES[key],
            colorscale=[[i / (len(SEQ_BLUE) - 1), c] for i, c in enumerate(SEQ_BLUE)],
            colorbar=dict(title=SENSOR_NAMES[key], thickness=12), xgap=2, ygap=2,
            hovertemplate=f'{SENSOR_NAMES[key]}: %{{z:.2f}}<br>cell centre (%{{x:.2f}}, %{{y:.2f}}) m<extra></extra>'))
    add_bubbles(fig, mission['bubbles'])
    return fig


def fmt_time(t):
    return pd.to_datetime(t, unit='s', utc=True).strftime('%Y-%m-%d %H:%M UTC') if t else '—'


# ---------- pages ----------

def page_overview(mission):
    pins = [p for p in mission['pins'] if p.get('source', 'live') in st.session_state.sources]
    invasive = [p for p in pins if p['invasive']]
    duration = (mission['ended_at'] - mission['started_at']) / 60 if mission['started_at'] else 0
    c = st.columns(5)
    c[0].metric('360° bubbles', len(mission['bubbles']))
    c[1].metric('Plants pinned', len(pins))
    c[2].metric('Invasive', len(invasive))
    c[3].metric('Species', len({p['label'] for p in pins}))
    c[4].metric('Duration', f'{duration:.1f} min')
    st.caption(f"Mission {mission['mission_id']} · started {fmt_time(mission['started_at'])}")

    left, right = st.columns([3, 2])
    with left:
        fig = map_figure(mission)
        add_path(fig, mission['readings'])
        add_bubbles(fig, mission['bubbles'])
        add_pins(fig, [p for p in pins if not p['invasive']], 'Native', BLUE, 'circle')
        add_pins(fig, invasive, 'Invasive', ORANGE, 'x')
        st.plotly_chart(fig, width='stretch')
    with right:
        counts = (pd.DataFrame(pins or [{'label': '', 'invasive': False}])
                  .groupby(['label', 'invasive']).size().reset_index(name='count')
                  .sort_values('count'))
        if pins:
            bar = go.Figure(go.Bar(
                x=counts['count'], y=counts['label'], orientation='h',
                marker=dict(color=[ORANGE if inv else BLUE for inv in counts['invasive']],
                            line=dict(width=2, color='rgba(0,0,0,0)')),
                text=[f"{n}{' · invasive' if inv else ''}" for n, inv in zip(counts['count'], counts['invasive'])],
                textposition='outside', cliponaxis=False, hovertemplate='%{y}: %{x}<extra></extra>'))
            bar.update_layout(height=300, margin=dict(l=10, r=90, t=30, b=10), title='Pins per species',
                              xaxis=dict(showgrid=False, visible=False), bargap=0.35)
            st.plotly_chart(bar, width='stretch')
        bubble_ids = [b['bubble_id'] for b in mission['bubbles']]
        if bubble_ids:
            bid = st.selectbox('Look inside a bubble', bubble_ids)
            show_bubble(mission, next(b for b in mission['bubbles'] if b['bubble_id'] == bid))

    st.subheader('Pins')
    rows = [{'crop': crop_src(mission, p), 'pin': p['pin_id'], 'species': p['label'],
             'invasive': p['invasive'], 'confidence': p.get('confidence'), 'bubble': p.get('bubble_id'),
             'x (m)': p['x'], 'y (m)': p['y'], 'source': p.get('source', 'live')} for p in pins]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch', column_config={
        'crop': st.column_config.ImageColumn('crop', width='small'),
        'confidence': st.column_config.ProgressColumn('confidence', min_value=0, max_value=1, format='%.2f')})


def show_bubble(mission, bubble):
    mid_bubble = bubble['bubble_id']
    pano = image_src(mission, f'frames/{mid_bubble}_pano.jpg') if bubble.get('stitched') else None
    if pano:
        st.image(pano, caption=f'{mid_bubble} · stitched panorama', width='stretch')
        return
    frames = sorted(bubble.get('frames', []), key=lambda f: f['index'])
    st.caption(f'{mid_bubble} · unstitched ring, {len(frames)} frames')
    cols = st.columns(4)
    for i, f in enumerate(frames):
        src = image_src(mission, f"frames/{mid_bubble}_{f['index']}.jpg")
        if src:
            cols[i % 4].image(src, caption=f"{math.degrees(f['yaw']):.0f}°", width='stretch')


def page_sensors(mission):
    readings = mission['readings']
    present = [k for k in SENSOR_KEYS if any(k in r for r in readings)]
    if not present:
        st.info('This mission has no sensor readings.')
        return
    c1, c2 = st.columns([2, 1])
    key = c1.selectbox('Sensor', present, format_func=SENSOR_NAMES.get)
    cell = c2.select_slider('Cell size (m)', [0.25, 0.5, 1.0], value=0.5)
    vals = [r[key] for r in readings if key in r]
    c = st.columns(4)
    c[0].metric('Readings', f'{len(vals)} of {len(readings)}')
    c[1].metric('Min', f'{min(vals):.2f}')
    c[2].metric('Mean', f'{np.mean(vals):.2f}')
    c[3].metric('Max', f'{max(vals):.2f}')
    st.plotly_chart(heat_figure(mission, key, cell), width='stretch')
    series = pd.DataFrame([{'time': pd.to_datetime(r['t'], unit='s'), key: r[key]} for r in readings if key in r])
    line = go.Figure(go.Scatter(x=series['time'], y=series[key], mode='lines', line=dict(color=BLUE, width=2),
                                hovertemplate='%{x|%H:%M:%S}<br>%{y:.2f}<extra></extra>'))
    line.update_layout(height=240, margin=dict(l=10, r=10, t=30, b=10), title=f'{SENSOR_NAMES[key]} over time',
                       xaxis=dict(showgrid=False), yaxis=dict(gridcolor='rgba(128,128,128,0.15)'))
    st.plotly_chart(line, width='stretch')


def page_before_after(load, mission_ids):
    if len(mission_ids) < 2:
        st.info('Needs two missions over the same ground: a "before" and an "after" survey.')
        return
    c1, c2, c3 = st.columns([1, 1, 1])
    before_id = c1.selectbox('Before', mission_ids, index=0)
    after_id = c2.selectbox('After', mission_ids, index=len(mission_ids) - 1)
    invasive_only = c3.toggle('Invasive species only', value=True)
    before, after = load(before_id), load(after_id)
    srcs = st.session_state.sources
    bp = [p for p in before['pins'] if p.get('source', 'live') in srcs]
    ap = [p for p in after['pins'] if p.get('source', 'live') in srcs]
    rows, totals, pairs, removed, new = before_after_summary(bp, ap, invasive_only)

    what = 'invasive plants' if invasive_only else 'plants'
    st.markdown(f"## {totals['found']} {what} found → {totals['remaining']} remaining")
    pct = 100 * totals['removed'] / totals['found'] if totals['found'] else 0
    c = st.columns(4)
    c[0].metric('Found before', totals['found'])
    c[1].metric('Removed', totals['removed'], f'{pct:.0f}%' if totals['found'] else None)
    c[2].metric('Still there', totals['remaining'])
    c[3].metric('New in after', totals['new'], delta_color='inverse')
    st.caption(f'Same species within {MATCH_RADIUS_M} m counts as the same plant.')

    left, right = st.columns([3, 2])
    with left:
        fig = map_figure(after)
        add_bubbles(fig, after['bubbles'])
        add_pins(fig, removed, 'Removed', AQUA, 'circle-open', 15)
        add_pins(fig, [a for _, a, _ in pairs], 'Still there', ORANGE, 'x')
        add_pins(fig, new, 'New', BLUE, 'diamond')
        st.plotly_chart(fig, width='stretch')
    with right:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')


def similar_local(all_pins, pin, k=12):
    target = pin.get('embedding')
    if not target:
        return None
    others = [p for p in all_pins if p.get('embedding') and p['pin_id'] != pin['pin_id']]
    if not others:
        return []
    m = np.array([p['embedding'] for p in others])
    d = np.linalg.norm(m - np.array(target), axis=1)
    return [dict(others[i], distance=float(d[i])) for i in np.argsort(d)[:k]]


def similar_db(pin_id, k=12):
    with db_connect() as conn:
        has = conn.execute('select embedding is not null as e from pins where pin_id = %s', (pin_id,)).fetchone()
        if not has or not has['e']:
            return None
        return conn.execute(
            'select pin_id, mission_id, label, invasive, confidence, x, y, crop_url, source, '
            'embedding <-> (select embedding from pins where pin_id = %s) as distance '
            'from pins where pin_id <> %s and embedding is not null order by distance limit %s',
            (pin_id, pin_id, k)).fetchall()


def page_similar(load, mission_ids, use_db):
    all_pins = {mid: load(mid) for mid in mission_ids}
    options = [(mid, p) for mid, m in all_pins.items() for p in m['pins']]
    if not options:
        st.info('No pins yet.')
        return
    idx = st.selectbox('Plant', range(len(options)),
                       format_func=lambda i: f"{options[i][1]['pin_id']} · {options[i][1]['label']}")
    mid, pin = options[idx]
    c1, c2 = st.columns([1, 3])
    src = crop_src(all_pins[mid], pin)
    if src:
        c1.image(src, caption=f"{pin['pin_id']} · {pin['label']}", width='stretch')
    flat = [p for m in all_pins.values() for p in m['pins']]
    results = similar_db(pin['pin_id']) if use_db else similar_local(flat, pin)
    with c2:
        if results is None:
            st.warning('This pin has no BioCLIP embedding, so showing the same species instead. '
                       'Run `sync.py --embed` or the AMD deep pass to add embeddings.')
            results = [dict(p, distance=None) for p in flat if p['label'] == pin['label'] and p['pin_id'] != pin['pin_id']]
        if not results:
            st.info('Nothing similar yet.')
            return
        cols = st.columns(4)
        for i, p in enumerate(results[:12]):
            m = all_pins.get(p['mission_id'], all_pins[mid])
            s = p.get('crop_url') or crop_src(m, p)
            dist = f" · d={p['distance']:.3f}" if p.get('distance') is not None else ''
            tag = ' · invasive' if p['invasive'] else ''
            if s:
                cols[i % 4].image(s, width='stretch')
            cols[i % 4].caption(f"{p['pin_id']} · {p['label']}{tag}{dist}")


# ---------- main ----------

def main():
    st.title('Understory survey')
    with st.sidebar:
        has_db = bool(os.environ.get('DATABASE_URL'))
        hf_repo = os.environ.get('HF_DATASET_REPO')
        choice = st.radio('Data source',
                          (['Neon'] if has_db else []) + ['Mission folders'] + (['Hugging Face'] if hf_repo else []),
                          help='Mission folders work offline (pre-synced fallback). '
                               'Hugging Face is the dataset sync.py uploads to.')
        use_db = choice == 'Neon'
        root = None
        if choice == 'Hugging Face':
            st.caption(f'Dataset: [{hf_repo}](https://huggingface.co/datasets/{hf_repo})')
            if st.button('Download again'):
                hf_root.clear()
                local_mission_ids.clear()
                local_mission.clear()
            try:
                with st.spinner('Downloading from Hugging Face...'):
                    root = hf_root(hf_repo)
            except Exception as e:  # venue internet is not guaranteed
                if hf_cache_dir(hf_repo).is_dir():
                    st.warning(f'Hugging Face unreachable, showing the last download. ({e.__class__.__name__})')
                    root = str(hf_cache_dir(hf_repo))
                else:
                    st.error(f'Hugging Face unreachable, using mission folders. ({e.__class__.__name__})')
        if use_db:
            try:
                mission_ids = db_mission_ids()
            except Exception as e:  # venue internet is not guaranteed
                st.error(f'Neon unreachable, using mission folders. ({e.__class__.__name__})')
                use_db = False
        if not use_db:
            if root is None:
                root = str(local_root())
                st.caption(f'Folder: `{root}`')
            mission_ids = local_mission_ids(root) if Path(root).is_dir() else []
        if not mission_ids:
            st.warning('No missions found.')
            return
        mid = st.selectbox('Mission', mission_ids, index=0)
        st.session_state.sources = st.multiselect(
            'Pins from', ['live', 'deep'], default=['live'],
            help='live = the Jetson during the mission; deep = the AMD deep pass afterwards')

    load = db_mission if use_db else (lambda m: local_mission(root, m))
    mission = load(mid)
    tabs = st.tabs(['Survey', 'Sensors', 'Before / after', 'Similar plants'])
    with tabs[0]:
        page_overview(mission)
    with tabs[1]:
        page_sensors(mission)
    with tabs[2]:
        page_before_after(load, mission_ids)
    with tabs[3]:
        page_similar(load, mission_ids, use_db)


main()
