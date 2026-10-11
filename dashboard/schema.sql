-- Neon (Postgres + pgvector). sync.py runs this on every sync; every statement is safe to re-run.
create extension if not exists vector;

create table if not exists missions (
    mission_id     text primary key,
    started_at     timestamptz,
    ended_at       timestamptz,
    asset_base_url text,              -- HF dataset folder for this mission; images live under it
    map_url        text,              -- map.png (converted from map.pgm)
    map_resolution double precision,  -- meters per pixel, from map.yaml
    map_origin_x   double precision,  -- map frame position of the image's bottom-left pixel
    map_origin_y   double precision,
    map_width      integer,           -- pixels
    map_height     integer,
    synced_at      timestamptz not null default now()
);

create table if not exists bubbles (
    bubble_id  text primary key,
    mission_id text not null references missions on delete cascade,
    t          timestamptz,
    x          double precision,
    y          double precision,
    stitched   boolean,
    hfov       double precision,
    frames     jsonb                  -- [{"index": 0, "yaw": 0.0}, ...]
);

create table if not exists pins (
    pin_id     text primary key,
    mission_id text not null references missions on delete cascade,
    bubble_id  text,
    source     text not null default 'live',  -- 'live' (Jetson) or 'deep' (AMD deep pass)
    label      text not null,
    invasive   boolean not null,
    confidence double precision,
    yaw        double precision,
    x          double precision,
    y          double precision,
    crop_url   text,
    embedding  vector(512)            -- BioCLIP image embedding; null when the pin was synced without one
);
create index if not exists pins_mission_idx on pins (mission_id);

create table if not exists readings (
    mission_id    text not null references missions on delete cascade,
    t             timestamptz not null,
    x             double precision,
    y             double precision,
    temp_c        double precision,
    pressure_hpa  double precision,
    soil_moisture double precision,
    light         double precision,
    uv            double precision,
    air_quality   double precision,
    sound         double precision,
    primary key (mission_id, t)
);
