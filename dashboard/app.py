"""Understory survey dashboard.

    streamlit run dashboard/app.py      # from the repo root, so .streamlit/config.toml (the theme) is picked up

Reads from Neon when DATABASE_URL is set (after sync.py), otherwise straight from mission folders
(MISSIONS_DIR, default missions/ then fake_data/missions/). The folder path is the offline fallback:
it needs no internet.
"""
import base64
import io
import math
import os
import sys
import urllib.request
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

# Colors per theme: only the Eucalyptus / Mist / Plaster / Soot / Moss palette (and lighter/darker steps of it).
# Plant markers are told apart by lightness and shape, not hue: invasive = dark Soot ✕, native = Eucalyptus dot,
# removed = Mist dot, new = Moss diamond. Keep in sync with .streamlit/config.toml.
EUCALYPTUS, MIST, PLASTER, SOOT, MOSS = '#98aa9d', '#b3c9d6', '#f2efe2', '#2d3536', '#697c70'
PALETTES = {
    'light': {
        'native': EUCALYPTUS, 'native_line': MOSS, 'invasive': SOOT, 'removed': MIST, 'removed_line': '#6b93b0',
        'new': MOSS, 'text': SOOT, 'muted': '#5b6661', 'faint': '#8a948e', 'border': '#dcd8c8',
        'card': '#faf8f1', 'surface': PLASTER, 'accent': '#55675c',
        'grid': 'rgba(45,53,54,0.08)', 'fill': 'rgba(152,170,157,0.22)', 'line': MOSS,
        'wall': (45, 53, 54, 235), 'floor': (251, 250, 245, 255), 'unknown': (231, 228, 213, 255),
        'seq': ['#e6edf1', '#cbdbe4', '#b3c9d6', '#8fb0c6', '#6b93b0', '#4c7698', '#355a78'],  # Mist ramp
    },
    'dark': {
        'native': EUCALYPTUS, 'native_line': '#c9d6cc', 'invasive': PLASTER, 'removed': MIST, 'removed_line': '#d7e4ec',
        'new': EUCALYPTUS, 'text': PLASTER, 'muted': '#b9c2bb', 'faint': '#8a968f', 'border': '#435051',
        'card': '#343d3e', 'surface': SOOT, 'accent': EUCALYPTUS,
        'grid': 'rgba(242,239,226,0.07)', 'fill': 'rgba(152,170,157,0.16)', 'line': EUCALYPTUS,
        'wall': (230, 226, 210, 230), 'floor': (54, 64, 66, 255), 'unknown': (47, 56, 57, 255),
        'seq': ['#3b4a52', '#3f5a6e', '#4c7698', '#6b93b0', '#8fb0c6', '#b3c9d6', '#d7e4ec'],
    },
}
FONT = 'Inter, -apple-system, "Segoe UI", sans-serif'
DISPLAY = '"Space Grotesk", Inter, -apple-system, sans-serif'
SENSOR_NAMES = {
    'temp_c': 'Temperature (°C)', 'pressure_hpa': 'Pressure (hPa)', 'soil_moisture': 'Soil moisture (raw)',
    'light': 'Light (raw)', 'uv': 'UV index', 'air_quality': 'Air quality (raw)', 'sound': 'Sound (raw)',
}
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

.us-hero {{ background: {MOSS}; border-radius: 28px; padding: 2rem 2.4rem 1.7rem; margin: 0 0 1.4rem 0;
            box-shadow: 0 10px 30px rgba(45,53,54,0.12); }}
.us-eyebrow {{ font-size: .74rem; font-weight: 600; letter-spacing: .22em; text-transform: uppercase;
               color: {PLASTER}; opacity: .85; margin-bottom: .2rem; }}
.us-title {{ font-family: {DISPLAY}; font-size: 2.8rem; font-weight: 600; line-height: 1.05; letter-spacing: -0.03em;
             color: #ffffff; margin: 0; }}
.us-sub {{ color: #ffffff; font-size: 1rem; margin-top: .5rem; max-width: 62ch; opacity: .95; }}
.us-chip {{ display: inline-block; padding: .2rem .8rem; border-radius: 999px; font-size: .74rem; font-weight: 600;
            letter-spacing: .12em; text-transform: uppercase; color: {SOOT}; background: {PLASTER};
            margin: 1rem .4rem 0 0; }}
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

.us-ba {{ display: flex; align-items: center; gap: 1.6rem; padding: 1.5rem 2rem; border-radius: 28px;
          background: {SOOT}; margin: .4rem 0 1.2rem; flex-wrap: wrap; box-shadow: 0 10px 30px rgba(45,53,54,0.15);
          border: 1px solid #435051; }}
.us-ba-num {{ font-family: {DISPLAY}; font-variant-numeric: lining-nums; font-size: 3.4rem; line-height: 1; font-weight: 600; letter-spacing: -0.03em;
              color: {PLASTER}; }}
.us-ba-num.after {{ color: {MIST}; }}
.us-ba-arrow {{ font-size: 2rem; color: {EUCALYPTUS}; }}
.us-ba-cap {{ color: {PLASTER}; opacity: .75; font-size: .7rem; text-transform: uppercase; letter-spacing: .18em;
              font-weight: 600; }}
.us-ba-text {{ margin-left: auto; text-align: right; }}
.us-ba-pct {{ font-family: {DISPLAY}; font-variant-numeric: lining-nums; font-size: 1.9rem; color: {EUCALYPTUS}; font-weight: 600; letter-spacing: -0.02em; }}
.us-ba .us-note {{ color: {PLASTER}; opacity: .75; }}

.us-pill {{ display: inline-block; padding: .08rem .55rem; border-radius: 999px; font-size: .68rem; font-weight: 600;
            letter-spacing: .08em; text-transform: uppercase; }}
.us-pill.inv {{ color: {PLASTER}; background: {SOOT}; }}
.us-pill.nat {{ color: {SOOT}; background: {EUCALYPTUS}; }}
.us-card-title {{ font-family: {DISPLAY}; font-weight: 600; font-size: .98rem; margin-top: .3rem;
                  color: {P['text']}; }}
.us-card-meta {{ color: {P['muted']}; font-size: .78rem; }}

.us-brand {{ font-family: {DISPLAY}; font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em; margin-bottom: .1rem; }}
.us-brand-sub {{ font-size: .7rem; letter-spacing: .16em; text-transform: uppercase; opacity: .75; margin-bottom: 1.2rem; }}
</style>
""", unsafe_allow_html=True)


def section(title, note=None):
    html = f'<div class="us-section">{title}</div>'
    if note:
        html += f'<div class="us-note">{note}</div>'
    st.markdown(html, unsafe_allow_html=True)


def pill(invasive):
    return '<span class="us-pill inv">invasive</span>' if invasive else '<span class="us-pill nat">native</span>'


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


def chart(fig):
    st.plotly_chart(fig, theme=None, width='stretch', config={'displaylogo': False})


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
    return style(fig, height)


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
        x=[b['x'] for b in bubbles], y=[b['y'] for b in bubbles], mode='markers+text', name='360° bubble',
        text=[b['bubble_id'].split('-')[-1] for b in bubbles], textposition='top center',
        textfont=dict(size=11, color=P['muted']),
        marker=dict(symbol='circle-open', size=17, color=P['muted'], line=dict(width=2)),
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


def heat_figure(mission, key, cell_m):
    cells = bin_readings(mission['readings'], key, cell_m)
    fig = map_figure(mission, height=600)
    if cells:
        ixs = [c[0] for c in cells]
        iys = [c[1] for c in cells]
        xs = np.arange(min(ixs), max(ixs) + 1)
        ys = np.arange(min(iys), max(iys) + 1)
        z = np.full((len(ys), len(xs)), np.nan)
        for (ix, iy), v in cells.items():
            z[iy - ys[0], ix - xs[0]] = v
        seq = P['seq']
        fig.add_trace(go.Heatmap(
            x=(xs + 0.5) * cell_m, y=(ys + 0.5) * cell_m, z=z, opacity=0.92, name=SENSOR_NAMES[key],
            colorscale=[[i / (len(seq) - 1), c] for i, c in enumerate(seq)], xgap=3, ygap=3,
            colorbar=dict(title=dict(text=SENSOR_NAMES[key], font=dict(size=12, color=P['muted'])), thickness=10,
                          outlinewidth=0, tickfont=dict(size=11, color=P['faint'])),
            hovertemplate=f'<b>%{{z:.2f}}</b> {SENSOR_NAMES[key]}<br>cell centre (%{{x:.2f}}, %{{y:.2f}}) m<extra></extra>'))
    add_bubbles(fig, mission['bubbles'])
    fig.update_layout(showlegend=False)
    return fig


def fmt_time(t):
    return pd.to_datetime(t, unit='s', utc=True).strftime('%b %d, %Y · %H:%M UTC') if t else '—'


# ---------- pages ----------

def active_pins(mission):
    return [p for p in mission['pins'] if p.get('source', 'live') in st.session_state.sources]


def page_overview(mission):
    pins = active_pins(mission)
    invasive = [p for p in pins if p['invasive']]
    duration = (mission['ended_at'] - mission['started_at']) / 60 if mission['started_at'] else 0
    c = st.columns(5)
    c[0].metric('360° bubbles', len(mission['bubbles']))
    c[1].metric('Plants pinned', len(pins))
    c[2].metric('Invasive', len(invasive))
    c[3].metric('Species', len({p['label'] for p in pins}))
    c[4].metric('Duration', f'{duration:.1f} min')

    left, right = st.columns([3, 2], gap='medium')
    with left, st.container(border=True):
        section('Survey map', 'Each pin is a plant the robot saw, placed on the LiDAR map.')
        fig = map_figure(mission)
        add_path(fig, mission['readings'])
        add_bubbles(fig, mission['bubbles'])
        add_pins(fig, [p for p in pins if not p['invasive']], 'Native', P['native'], 'circle', 14, outline=P['native_line'])
        add_pins(fig, invasive, 'Invasive', P['invasive'], 'x', 14)
        chart(fig)
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
                bar.update_yaxes(automargin=True, ticksuffix='  ')
                bar.update_xaxes(visible=False)
                bar.update_yaxes(tickfont=dict(size=12, color=P['text']), title=None)
                chart(bar)
            else:
                st.caption('No pins in this mission.')
        bubble_ids = [b['bubble_id'] for b in mission['bubbles']]
        if bubble_ids:
            with st.container(border=True):
                section('Inside a bubble')
                bid = st.selectbox('Bubble', bubble_ids, label_visibility='collapsed')
                show_bubble(mission, next(b for b in mission['bubbles'] if b['bubble_id'] == bid))

    section('Pins', 'Every plant pinned in this mission, with the crop it was named from.')
    rows = [{'crop': crop_src(mission, p), 'pin': p['pin_id'], 'species': p['label'],
             'invasive': p['invasive'], 'confidence': p.get('confidence'), 'bubble': p.get('bubble_id'),
             'x (m)': p['x'], 'y (m)': p['y'], 'source': p.get('source', 'live')} for p in pins]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch', row_height=56, column_config={
        'crop': st.column_config.ImageColumn('Crop', width='small'),
        'pin': 'Pin', 'species': 'Species', 'bubble': 'Bubble', 'source': 'Source',
        'invasive': st.column_config.CheckboxColumn('Invasive'),
        'x (m)': st.column_config.NumberColumn('x (m)', format='%.2f'),
        'y (m)': st.column_config.NumberColumn('y (m)', format='%.2f'),
        'confidence': st.column_config.ProgressColumn('Confidence', min_value=0, max_value=1, format='%.2f')})


def show_bubble(mission, bubble):
    bid = bubble['bubble_id']
    pano = image_src(mission, f'frames/{bid}_pano.jpg') if bubble.get('stitched') else None
    if pano:
        st.image(pano, width='stretch')
        st.caption(f'{bid} · stitched 360° panorama')
        return
    frames = sorted(bubble.get('frames', []), key=lambda f: f['index'])
    st.caption(f'{bid} · stitching fell back to the frame ring ({len(frames)} frames)')
    cols = st.columns(4)
    for i, f in enumerate(frames):
        src = image_src(mission, f"frames/{bid}_{f['index']}.jpg")
        if src:
            cols[i % 4].image(src, caption=f"{math.degrees(f['yaw']):.0f}°", width='stretch')


def page_sensors(mission):
    readings = mission['readings']
    present = [k for k in SENSOR_KEYS if any(k in r for r in readings)]
    if not present:
        st.info('This mission has no sensor readings.')
        return
    c1, c2 = st.columns([2, 1], gap='medium')
    key = c1.selectbox('Sensor', present, format_func=SENSOR_NAMES.get)
    cell = c2.select_slider('Cell size (m)', [0.25, 0.5, 1.0], value=0.5)
    vals = [r[key] for r in readings if key in r]
    c = st.columns(4)
    c[0].metric('Readings', f'{len(vals)} of {len(readings)}')
    c[1].metric('Min', f'{min(vals):.2f}')
    c[2].metric('Mean', f'{np.mean(vals):.2f}')
    c[3].metric('Max', f'{max(vals):.2f}')
    with st.container(border=True):
        section(f'{SENSOR_NAMES[key]} across the site', f'Mean of the readings in each {cell} m cell; '
                'darker is higher. Readings without this sensor are skipped.')
        chart(heat_figure(mission, key, cell))
    with st.container(border=True):
        series = pd.DataFrame([{'time': pd.to_datetime(r['t'], unit='s'), key: r[key]} for r in readings if key in r])
        line = go.Figure(go.Scatter(
            x=series['time'], y=series[key], mode='lines', line=dict(color=P['line'], width=2.5, shape='spline'),
            fill='tozeroy', fillcolor=P['fill'],
            hovertemplate='%{x|%H:%M:%S}<br><b>%{y:.2f}</b><extra></extra>'))
        style(line, 260, f'{SENSOR_NAMES[key]} over time')
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.15 or 1
        line.update_yaxes(range=[lo - pad, hi + pad], showgrid=True, gridcolor=P['grid'])
        chart(line)


def page_before_after(load, mission_ids):
    if len(mission_ids) < 2:
        st.info('Needs two missions over the same ground: a "before" and an "after" survey.')
        return
    c1, c2, c3 = st.columns([1, 1, 1], gap='medium')
    before_id = c1.selectbox('Before', mission_ids, index=0)
    after_id = c2.selectbox('After', mission_ids, index=len(mission_ids) - 1)
    with c3:
        st.write('')
        invasive_only = st.toggle('Invasive species only', value=True)
    before, after = load(before_id), load(after_id)
    srcs = st.session_state.sources
    bp = [p for p in before['pins'] if p.get('source', 'live') in srcs]
    ap = [p for p in after['pins'] if p.get('source', 'live') in srcs]
    rows, totals, pairs, removed, new = before_after_summary(bp, ap, invasive_only)

    what = 'invasive plants' if invasive_only else 'plants'
    pct = 100 * totals['removed'] / totals['found'] if totals['found'] else 0
    headline = f"{totals['found']} {what} found → {totals['remaining']} remaining"
    st.markdown(f"""
<div class="us-ba" role="group" aria-label="{headline}">
  <div><div class="us-ba-cap">Found · {before_id}</div><div class="us-ba-num">{totals['found']}</div></div>
  <div class="us-ba-arrow">→</div>
  <div><div class="us-ba-cap">Remaining · {after_id}</div><div class="us-ba-num after">{totals['remaining']}</div></div>
  <div class="us-ba-text"><div class="us-ba-pct">{pct:.0f}% removed</div>
    <div class="us-note">{totals['removed']} {what} gone · {totals['new']} new since {before_id}</div></div>
</div>""", unsafe_allow_html=True)

    left, right = st.columns([3, 2], gap='medium')
    with left, st.container(border=True):
        section('What changed', f'Same species within {MATCH_RADIUS_M} m counts as the same plant.')
        fig = map_figure(after)
        add_bubbles(fig, after['bubbles'])
        add_pins(fig, removed, 'Removed', P['removed'], 'circle', 14, outline=P['removed_line'])
        add_pins(fig, [a for _, a, _ in pairs], 'Still there', P['invasive'], 'x', 14)
        add_pins(fig, new, 'New', P['new'], 'diamond', 14)
        chart(fig)
    with right, st.container(border=True):
        section('By species')
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch', column_config={
            'label': 'Species', 'found': 'Found', 'remaining': 'Remaining', 'removed': 'Removed', 'new': 'New'})


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
    flat = [p for m in all_pins.values() for p in m['pins']]
    results = similar_db(pin['pin_id']) if use_db else similar_local(flat, pin)

    c1, c2 = st.columns([1, 3], gap='medium')
    with c1, st.container(border=True):
        src = crop_src(all_pins[mid], pin)
        if src:
            st.image(src, width='stretch')
        st.markdown(f'<div class="us-card-title">{pin["label"]}</div>'
                    f'<div class="us-card-meta">{pin["pin_id"]} · {pill(pin["invasive"])}</div>',
                    unsafe_allow_html=True)
    with c2:
        if results is None:
            st.info('This pin has no BioCLIP embedding yet, so these are the same species from other surveys. '
                    'Run `sync.py --embed` or the AMD deep pass to search by appearance.', icon='🌱')
            results = [dict(p, distance=None) for p in flat
                       if p['label'] == pin['label'] and p['pin_id'] != pin['pin_id']]
        if not results:
            st.caption('Nothing similar yet.')
            return
        cols = st.columns(4)
        for i, p in enumerate(results[:12]):
            m = all_pins.get(p['mission_id'], all_pins[mid])
            s = p.get('crop_url') or crop_src(m, p)
            dist = f" · d {p['distance']:.3f}" if p.get('distance') is not None else ''
            with cols[i % 4], st.container(border=True):
                if s:
                    st.image(s, width='stretch')
                st.markdown(f'<div class="us-card-title">{p["label"]}</div>'
                            f'<div class="us-card-meta">{p["pin_id"]}{dist} · {pill(p["invasive"])}</div>',
                            unsafe_allow_html=True)


# ---------- main ----------

def main():
    inject_css()
    with st.sidebar:
        st.markdown('<div class="us-brand">🌿 Understory</div>'
                    '<div class="us-brand-sub">Invasive plant survey · Knight Hacks IX</div>', unsafe_allow_html=True)
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
        st.session_state.sources = st.multiselect(
            'Pins from', ['live', 'deep'], default=['live'],
            help='live = the Jetson during the mission; deep = the AMD deep pass afterwards')
        if not use_db:
            st.caption(f'Reading `{Path(root).relative_to(REPO) if Path(root).is_relative_to(REPO) else root}`')

    load = db_mission if use_db else (lambda m: local_mission(root, m))
    mission = load(mid)
    source = 'Neon' if use_db else 'Local folders'
    st.markdown(f"""
<div class="us-hero">
  <div class="us-eyebrow">Mission {mid}</div>
  <div class="us-title">Understory survey</div>
  <div class="us-sub">A ground robot maps the site, names the plants it sees, and counts the invasive ones,
  so a re-survey can show that removal worked.</div>
  <span class="us-chip">{fmt_time(mission['started_at'])}</span><span class="us-chip mist">{source}</span>
</div>""", unsafe_allow_html=True)

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
