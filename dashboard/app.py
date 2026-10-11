"""Understory dashboard.

    streamlit run dashboard/app.py      # from the repo root, so .streamlit/config.toml (the theme) is picked up

Reads from Neon when DATABASE_URL is set (after sync.py), otherwise straight from mission folders
(MISSIONS_DIR, default missions/ then fake_data/missions/). The folder path is the offline fallback:
it needs no internet.
"""
import base64
import io
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mission_io import SENSOR_KEYS, load_mission, map_extent  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / '.env')

# Colors per theme: only the Eucalyptus / Mist / Plaster / Soot / Moss palette (and lighter/darker steps of it).
# Plant markers are told apart by lightness and shape, not hue: invasive = dark Soot ✕, native = Eucalyptus dot.
# Keep in sync with .streamlit/config.toml.
EUCALYPTUS, MIST, PLASTER, SOOT, MOSS = '#98aa9d', '#b3c9d6', '#f2efe2', '#2d3536', '#697c70'
PALETTES = {
    'light': {
        'native': EUCALYPTUS, 'native_line': MOSS, 'invasive': SOOT,
        'lidar': '#4c7698', 'lidar_fill': 'rgba(179,201,214,0.35)', 'robot': SOOT,
        'side_text': SOOT, 'side_card': 'rgba(242,239,226,0.55)', 'side_tag': (SOOT, PLASTER),
        'text': SOOT, 'muted': '#5b6661', 'faint': '#8a948e', 'border': '#dcd8c8',
        'card': '#faf8f1', 'surface': PLASTER, 'accent': '#55675c',
        'wall': (45, 53, 54, 235), 'floor': (251, 250, 245, 255), 'unknown': (231, 228, 213, 255),
    },
    'dark': {
        'native': EUCALYPTUS, 'native_line': '#c9d6cc', 'invasive': PLASTER,
        'lidar': MIST, 'lidar_fill': 'rgba(179,201,214,0.16)', 'robot': PLASTER,
        'side_text': PLASTER, 'side_card': 'rgba(242,239,226,0.06)', 'side_tag': (EUCALYPTUS, SOOT),
        'text': PLASTER, 'muted': '#b9c2bb', 'faint': '#8a968f', 'border': '#435051',
        'card': '#343d3e', 'surface': SOOT, 'accent': EUCALYPTUS,
        'wall': (230, 226, 210, 230), 'floor': (54, 64, 66, 255), 'unknown': (47, 56, 57, 255),
    },
}
FONT = 'Inter, -apple-system, "Segoe UI", sans-serif'
DISPLAY = '"Space Grotesk", Inter, -apple-system, sans-serif'
# Live feeds come through dashboard/live_relay.py. The dashboard server polls it for the newest LiDAR scan; the
# viewer's browser opens the headset WebSocket itself (default: same host as this page, port 8770).
RELAY_HTTP = os.environ.get('LIVE_RELAY_URL', 'http://localhost:8770').rstrip('/')
RELAY_WS = os.environ.get('LIVE_RELAY_WS', '')
LIVE_FLIP = os.environ.get('LIVE_FLIP') == '1'
SCAN_STALE_S = 3.0

# Metric cards cycle through the palette like swatches: (background, text).
SWATCHES = [(EUCALYPTUS, SOOT), (MIST, SOOT), ('#faf8f1', SOOT), (SOOT, PLASTER), (MOSS, '#ffffff')]

st.set_page_config(page_title='Understory', page_icon='🌿', layout='wide')


def theme_name():
    try:
        return 'dark' if st.context.theme.type == 'dark' else 'light'
    except Exception:
        return 'light'


P = PALETTES[theme_name()]


def inject_css():
    swatch_css = '\n'.join(
        f'[data-testid="stColumn"]:nth-child({len(SWATCHES)}n+{i + 1}) [data-testid="stMetric"] '
        f'{{ background: {bg}; color: {fg}; }}\n'
        f'[data-testid="stColumn"]:nth-child({len(SWATCHES)}n+{i + 1}) [data-testid="stMetric"] * {{ color: {fg} !important; }}'
        for i, (bg, fg) in enumerate(SWATCHES))
    st.markdown(f"""
<style>
.block-container {{ padding-top: 2rem; max-width: 1380px; }}
[data-testid="stDecoration"] {{ display: none; }}

.us-hero {{ background: {MOSS}; border-radius: 28px; padding: 1.6rem 2.4rem; margin: 0 0 1rem 0;
            box-shadow: 0 10px 30px rgba(45,53,54,0.12); }}
.us-title {{ font-family: {DISPLAY}; font-size: 2.8rem; font-weight: 600; line-height: 1.05; letter-spacing: -0.03em;
             color: #ffffff; margin: 0; }}
.us-desc {{ margin: .2rem 0 1.2rem; }}
.us-chip {{ display: inline-block; padding: .2rem .8rem; border-radius: 999px; font-size: .74rem; font-weight: 600;
            letter-spacing: .12em; text-transform: uppercase; color: {SOOT}; background: {PLASTER};
            margin: .8rem .4rem 0 0; }}
.us-chip.soot {{ background: {SOOT}; color: {PLASTER}; }}
.us-desc .us-chip:not(.soot):not(.mist) {{ background: {P['card']}; color: {P['text']}; border: 1px solid {P['border']}; }}
.us-chip.soot {{ border: 1px solid {P['border']}; }}
.us-chip.mist {{ background: {MIST}; }}

[data-testid="stMetric"] {{ border-radius: 22px; padding: 18px 22px 16px; border: 1px solid rgba(45,53,54,0.08);
                           box-shadow: 0 6px 18px rgba(45,53,54,0.07); }}
[data-testid="stMetricLabel"] p {{ font-size: .7rem; font-weight: 600; letter-spacing: .18em; text-transform: uppercase;
                                   opacity: .8; }}
[data-testid="stMetricValue"] {{ font-family: {DISPLAY}; font-weight: 600; font-size: 2.2rem; letter-spacing: -0.02em;
                           font-variant-numeric: lining-nums; }}
{swatch_css}

[data-baseweb="tab-list"] {{ gap: .3rem; }}
[data-baseweb="tab"] p {{ font-weight: 500; font-size: .95rem; letter-spacing: .02em; }}

.us-section {{ font-family: {DISPLAY}; font-size: 1.3rem; font-weight: 600; letter-spacing: -0.01em; color: {P['text']};
               margin: .2rem 0 0; line-height: 1.2; }}
.us-note {{ color: {P['muted']}; font-size: .85rem; }}

.us-live {{ display: inline-flex; align-items: center; gap: .4rem; padding: .15rem .65rem; border-radius: 999px;
            font-size: .68rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase;
            background: {P['card']}; color: {P['muted']}; border: 1px solid {P['border']}; }}
.us-live.on {{ background: {SOOT}; color: {PLASTER}; border-color: {SOOT}; }}
.us-live .dot {{ width: 7px; height: 7px; border-radius: 50%; background: {P['faint']}; }}
.us-live.on .dot {{ background: {EUCALYPTUS}; box-shadow: 0 0 0 3px rgba(152,170,157,0.35); }}
.us-card-title {{ font-family: {DISPLAY}; font-weight: 600; font-size: .98rem; margin-top: .3rem;
                  color: {P['text']}; }}
.us-card-meta {{ color: {P['muted']}; font-size: .78rem; }}

.us-brand {{ font-family: {DISPLAY}; font-size: 2.7rem; font-weight: 700; letter-spacing: -0.04em; line-height: 1;
              color: {P['side_text']}; margin: .2rem 0 .5rem; }}
.us-brand-sub {{ display: inline-block; font-size: .68rem; font-weight: 600; letter-spacing: .16em; text-transform: uppercase;
                 color: {P['side_tag'][1]}; background: {P['side_tag'][0]}; padding: .2rem .7rem; border-radius: 999px; margin-bottom: 1.1rem; }}
.us-side-desc {{ font-size: .95rem; line-height: 1.55; color: {P['side_text']}; margin-bottom: .9rem; }}
.us-side-steps {{ margin: 0 0 1.2rem; }}
.us-side-steps .step {{ font-size: .85rem; line-height: 1.45; color: {P['side_text']}; padding: .55rem .8rem; margin-bottom: .4rem;
                     background: {P['side_card']}; border-radius: 14px; }}
.us-side-steps b {{ font-family: {DISPLAY}; font-weight: 600; }}
.us-side-rule {{ border: 0; border-top: 1px solid rgba(45,53,54,0.18); margin: .2rem 0 1rem; }}
</style>
""", unsafe_allow_html=True)


def section(title, note=None):
    html = f'<div class="us-section">{title}</div>'
    if note:
        html += f'<div class="us-note">{note}</div>'
    st.markdown(html, unsafe_allow_html=True)


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

@st.cache_data(ttl=300)
def tinted_map(source, theme):
    """The occupancy grid recolored for the theme: walls, free floor, unknown."""
    from PIL import Image
    if str(source).startswith('http'):
        with urllib.request.urlopen(source, timeout=10) as r:
            img = Image.open(io.BytesIO(r.read()))
    else:
        img = Image.open(source)
    g = np.asarray(img.convert('L'))
    pal = PALETTES[theme]
    out = np.empty(g.shape + (4,), dtype=np.uint8)
    out[:] = pal['unknown']
    out[g >= 250] = pal['floor']
    out[g <= 100] = pal['wall']
    return Image.fromarray(out, 'RGBA')


def style(fig, height, title=None):
    axis = dict(showgrid=False, zeroline=False, color=P['faint'], tickfont=dict(size=11, color=P['faint']),
                title_font=dict(size=12, color=P['muted']), linecolor=P['border'])
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    fig.update_layout(
        height=height, margin=dict(l=56, r=8, t=48 if title else 8, b=8),
        title=dict(text=title, font=dict(family=DISPLAY, size=17, color=P['text']), x=0, xanchor='left') if title else None,
        font=dict(family=FONT, color=P['text'], size=13),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        hoverlabel=dict(bgcolor=P['card'], bordercolor=P['border'], font=dict(family=FONT, size=12, color=P['text'])),
        legend=dict(orientation='h', yanchor='bottom', y=1.0, x=0, font=dict(size=12, color=P['muted']),
                    bgcolor='rgba(0,0,0,0)'),
    )
    return fig


def chart(fig, key=None):
    st.plotly_chart(fig, theme=None, width='stretch', config={'displaylogo': False}, key=key)


def map_figure(mission, height=560):
    fig = go.Figure()
    meta = mission['map']
    if meta:
        x0, x1, y0, y1 = map_extent(meta)
        if mission['map_source']:
            fig.add_layout_image(source=tinted_map(mission['map_source'], theme_name()), xref='x', yref='y',
                                 x=x0, y=y1, sizex=x1 - x0, sizey=y1 - y0, sizing='stretch', layer='below')
        fig.update_xaxes(range=[x0, x1])
        fig.update_yaxes(range=[y0, y1])
    fig.update_xaxes(title='x (m)')
    fig.update_yaxes(title='y (m)', scaleanchor='x', scaleratio=1)
    style(fig, height)
    fig.update_layout(margin=dict(l=56, r=8, t=8, b=44))  # room for the x-axis numbers
    return fig


def add_path(fig, readings):
    pts = [(r['x'], r['y']) for r in readings if 'x' in r and 'y' in r]
    if pts:
        xs, ys = zip(*pts)
        fig.add_trace(go.Scatter(x=xs, y=ys, mode='lines', name='Robot path',
                                 line=dict(color=P['faint'], width=2, dash='dot'), hoverinfo='skip'))


def add_bubbles(fig, bubbles):
    if not bubbles:
        return
    fig.add_trace(go.Scatter(
        x=[b['x'] for b in bubbles], y=[b['y'] for b in bubbles], mode='markers', name='360° bubble',
        marker=dict(symbol='circle-open', size=15, color=P['muted'], line=dict(width=2)),
        customdata=[[b['bubble_id'], 'stitched panorama' if b.get('stitched') else 'frame ring'] for b in bubbles],
        hovertemplate='<b>%{customdata[0]}</b><br>%{customdata[1]}<br>(%{x:.2f}, %{y:.2f}) m<extra></extra>'))


def add_pins(fig, pins, name, color, symbol, size=13, outline=None):
    if not pins:
        return
    fig.add_trace(go.Scatter(
        x=[p['x'] for p in pins], y=[p['y'] for p in pins], mode='markers', name=name,
        marker=dict(symbol=symbol, size=size, color=color, line=dict(width=2, color=outline or P['surface'])),
        customdata=[[p['pin_id'], p['label'], p.get('confidence') or 0] for p in pins],
        hovertemplate='<b>%{customdata[1]}</b><br>%{customdata[0]} · confidence %{customdata[2]:.2f}'
                      '<br>(%{x:.2f}, %{y:.2f}) m<extra></extra>'))


def fmt_time(t):
    return pd.to_datetime(t, unit='s', utc=True).strftime('%b %d, %Y · %H:%M UTC') if t else '—'


# ---------- live (dashboard/live_relay.py) ----------

def relay_up():
    try:
        with urllib.request.urlopen(RELAY_HTTP + '/health', timeout=0.3) as r:
            return r.status == 200
    except Exception:
        return False


def fetch_scan():
    """Newest LiDAR scan from the relay, or None when there is none or it is stale."""
    try:
        with urllib.request.urlopen(RELAY_HTTP + '/scan', timeout=0.3) as r:
            if r.status != 200:
                return None
            scan = json.loads(r.read())
    except Exception:
        return None
    return scan if scan.get('age', 1e9) <= SCAN_STALE_S else None


def add_scan(fig, scan):
    pts = scan.get('points') or []
    if pts:
        xs, ys = zip(*pts)
        # the area the LiDAR sees right now (beams are in angle order), then the hits themselves
        fig.add_trace(go.Scatter(x=xs + xs[:1], y=ys + ys[:1], mode='lines', fill='toself', hoverinfo='skip',
                                 fillcolor=P['lidar_fill'], line=dict(width=0), showlegend=False))
        fig.add_trace(go.Scatter(x=xs, y=ys, mode='markers', name='LiDAR (live)', hoverinfo='skip',
                                 marker=dict(size=4, color=P['lidar'], opacity=0.9)))
    pose = scan.get('pose')
    if pose:
        fig.add_trace(go.Scatter(
            x=[pose['x']], y=[pose['y']], mode='markers', name='Robot',
            marker=dict(symbol='triangle-up', size=18, color=P['robot'], angle=90 - math.degrees(pose.get('yaw', 0)),
                        line=dict(width=2, color=P['surface'])),
            hovertemplate='<b>Robot</b><br>(%{x:.2f}, %{y:.2f}) m<extra></extra>'))


def survey_map(mission, pins):
    scan = fetch_scan()
    if scan:
        st.markdown(f'<span class="us-live on"><span class="dot"></span>LiDAR live · {len(scan["points"])} points'
                    '</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="us-live"><span class="dot"></span>LiDAR offline</span>', unsafe_allow_html=True)
    fig = map_figure(mission)
    add_path(fig, mission['readings'])
    add_bubbles(fig, mission['bubbles'])
    add_pins(fig, [p for p in pins if not p['invasive']], 'Native', P['native'], 'circle', 14, outline=P['native_line'])
    add_pins(fig, [p for p in pins if p['invasive']], 'Invasive', P['invasive'], 'x', 14)
    if scan:
        add_scan(fig, scan)
    fig.update_layout(uirevision='survey-map')  # keep zoom/pan across live refreshes
    chart(fig, key='survey-map')


def live_camera(height=300):
    """Headset view: the browser opens the relay WebSocket and shows each JPEG frame as it arrives."""
    components.html(f"""
<style>
  html, body {{ margin: 0; background: transparent; font-family: Inter, -apple-system, 'Segoe UI', sans-serif; }}
  #wrap {{ position: relative; height: {height - 8}px; border-radius: 18px; overflow: hidden; background: {SOOT}; }}
  #v {{ width: 100%; height: 100%; object-fit: contain; display: none; {'transform: scaleY(-1);' if LIVE_FLIP else ''} }}
  #ph {{ position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
         color: {PLASTER}; gap: .35rem; text-align: center; padding: 0 1.5rem; }}
  #ph b {{ font-size: .95rem; font-weight: 600; }}
  #ph span {{ font-size: .78rem; opacity: .7; }}
  #badge {{ position: absolute; top: 12px; left: 12px; display: inline-flex; align-items: center; gap: .4rem;
            padding: .2rem .65rem; border-radius: 999px; font-size: .66rem; font-weight: 600; letter-spacing: .14em;
            text-transform: uppercase; background: {PLASTER}; color: {SOOT}; }}
  #badge i {{ width: 7px; height: 7px; border-radius: 50%; background: #8a948e; }}
  #badge.on i {{ background: {MOSS}; box-shadow: 0 0 0 3px rgba(105,124,112,.35); }}
</style>
<div id="wrap">
  <img id="v" alt="Headset view">
  <div id="ph"><b>Waiting for the headset</b><span>Start dashboard/live_relay.py and push dashboard_ip.txt to the Quest.</span></div>
  <div id="badge"><i></i><span id="bt">offline</span></div>
</div>
<script>
(() => {{
  let host = 'localhost';
  try {{ host = window.parent.location.hostname || host; }} catch (e) {{}}
  const url = {json.dumps(RELAY_WS)} || `ws://${{host}}:8770/ws/headset`;
  const img = document.getElementById('v'), ph = document.getElementById('ph');
  const badge = document.getElementById('badge'), bt = document.getElementById('bt');
  let last = 0, frames = [], prevUrl = null;
  function setLive(on) {{
    badge.classList.toggle('on', on); img.style.display = on ? 'block' : 'none'; ph.style.display = on ? 'none' : 'flex';
    if (!on) bt.textContent = 'offline';
  }}
  function connect() {{
    const ws = new WebSocket(url);
    ws.binaryType = 'blob';
    ws.onmessage = (ev) => {{
      const u = URL.createObjectURL(ev.data);
      img.onload = () => {{ if (prevUrl) URL.revokeObjectURL(prevUrl); prevUrl = u; }};
      img.src = u;
      const now = performance.now(); last = now;
      frames.push(now); frames = frames.filter(t => now - t < 2000);
      bt.textContent = `live · ${{(frames.length / 2).toFixed(0)}} fps`;
      setLive(true);
    }};
    ws.onclose = () => {{ setLive(false); setTimeout(connect, 2000); }};
    ws.onerror = () => ws.close();
  }}
  setInterval(() => {{ if (last && performance.now() - last > 3000) setLive(false); }}, 1000);
  connect();
}})();
</script>
""", height=height)


# ---------- pages ----------

def active_pins(mission):
    return [p for p in mission['pins'] if p.get('source', 'live') in st.session_state.sources]


def page_overview(mission):
    pins = active_pins(mission)
    invasive = [p for p in pins if p['invasive']]
    duration = (mission['ended_at'] - mission['started_at']) / 60 if mission['started_at'] else 0
    c = st.columns(4)
    c[0].metric('Plants pinned', len(pins))
    c[1].metric('Invasive', len(invasive))
    c[2].metric('Species', len({p['label'] for p in pins}))
    c[3].metric('Duration', f'{duration:.1f} min')

    left, right = st.columns([3, 2], gap='medium')
    with left, st.container(border=True):
        section('Survey map', 'Plants the robot saw on the LiDAR map, plus the live scan.')
        live = relay_up()
        st.fragment(run_every=1.0 if live else 5.0)(survey_map)(mission, pins)
    with right:
        with st.container(border=True):
            section('Pins per species')
            if pins:
                counts = (pd.DataFrame(pins).groupby(['label', 'invasive']).size()
                          .reset_index(name='count').sort_values(['count', 'label']))
                bar = go.Figure(go.Bar(
                    x=counts['count'], y=counts['label'], orientation='h', width=0.62,
                    marker=dict(color=[P['invasive'] if inv else P['native'] for inv in counts['invasive']],
                                cornerradius=4),
                    text=[f"{n}{'  · invasive' if inv else ''}" for n, inv in zip(counts['count'], counts['invasive'])],
                    textposition='outside', cliponaxis=False, textfont=dict(color=P['muted'], size=12),
                    hovertemplate='<b>%{y}</b>: %{x}<extra></extra>'))
                style(bar, 34 * len(counts) + 30)
                bar.update_layout(margin=dict(l=int(7.6 * counts['label'].str.len().max()) + 16, r=96, t=8, b=8))
                bar.update_yaxes(automargin=True, ticksuffix='  ', tickfont=dict(size=12, color=P['text']), title=None)
                bar.update_xaxes(visible=False)
                chart(bar)
            else:
                st.caption('No pins in this mission.')

    section('Pins')
    rows = [{'crop': crop_src(mission, p), 'species': p['label'], 'invasive': p['invasive'],
             'confidence': p.get('confidence')} for p in pins]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch', row_height=56, column_config={
        'crop': st.column_config.ImageColumn('Crop', width='small'),
        'species': 'Species',
        'invasive': st.column_config.CheckboxColumn('Invasive'),
        'confidence': st.column_config.ProgressColumn('Confidence', min_value=0, max_value=1, format='%.2f')})


# ---------- main ----------

def main():
    inject_css()
    with st.sidebar:
        st.markdown(
            '<div class="us-brand">Understory</div>'
            '<div class="us-brand-sub">Invasive plant survey</div>'
            '<div class="us-side-desc">A ground robot surveys places people can\'t easily reach, names the plants it '
            'sees with open-source AI, and counts the invasive ones, so a re-survey can show that removal worked.</div>'
            '<div class="us-side-steps">'
            '<div class="step"><b>Map</b> · LiDAR builds the floor plan as the robot drives.</div>'
            '<div class="step"><b>Identify</b> · the camera and AI pin each plant, invasive or native.</div>'
            '<div class="step"><b>Walk through</b> · the Quest headset puts you inside the survey.</div>'
            '</div><hr class="us-side-rule">', unsafe_allow_html=True)
        has_db = bool(os.environ.get('DATABASE_URL'))
        choice = st.radio('Data source', ['Neon', 'Mission folders'] if has_db else ['Mission folders'],
                          help='Mission folders work offline (pre-synced fallback).')
        use_db = choice == 'Neon'
        if use_db:
            try:
                mission_ids = db_mission_ids()
            except Exception as e:  # venue internet is not guaranteed
                st.error(f'Neon unreachable, using mission folders. ({e.__class__.__name__})')
                use_db = False
        if not use_db:
            root = str(local_root())
            mission_ids = local_mission_ids(root) if Path(root).is_dir() else []
        if not mission_ids:
            st.warning('No missions found.')
            return
        mid = st.selectbox('Mission', mission_ids, index=0)
        st.session_state.sources = ['live']
        if not use_db:
            st.caption(f'Reading `{Path(root).relative_to(REPO) if Path(root).is_relative_to(REPO) else root}`')

    load = db_mission if use_db else (lambda m: local_mission(root, m))
    mission = load(mid)
    if any(p.get('source') == 'deep' for p in mission['pins']):
        with st.sidebar:
            st.session_state.sources = st.multiselect(
                'Pins from', ['live', 'deep'], default=['live'],
                help='live = the Jetson during the mission; deep = the AMD deep pass afterwards')
    source = 'Neon' if use_db else 'Local folders'
    st.markdown('<div class="us-hero"><div class="us-title">Live stream view of the headset</div></div>',
                unsafe_allow_html=True)
    live_camera(height=560)  # the headset wearer's view, full width

    st.markdown(f"""
<div class="us-desc">
  <span class="us-chip soot">Mission {mid}</span><span class="us-chip">{fmt_time(mission['started_at'])}</span><span class="us-chip mist">{source}</span>
</div>""", unsafe_allow_html=True)

    page_overview(mission)


main()
