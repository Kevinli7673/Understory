#!/usr/bin/env python3
"""Mock ROS-TCP-Endpoint: test the Quest app's ROS side on a laptop with no ROS and no robot.

Speaks the same wire protocol as `ros2 run ros_tcp_endpoint default_server_endpoint` (v0.7, ROS2 mode)
and plays a fake_data mission as if the robot were live, plus a tiny robot sim that obeys the Quest:

    python tools/quest_mock_endpoint.py                  # mission m1, port 10000
    python tools/quest_mock_endpoint.py --missions m1,m2 --speed 4   # before, then the re-survey

Publishes (to the Quest):  /mission/state  /map  /pose  /survey/bubbles  /survey/bubble_images
                           /survey/pins  /survey/readings  /camera/image/compressed
Prints (from the Quest):   /cmd_vel_teleop  /estop  /voice/text  /voice/audio (saved as WAV; transcribed
                           as a voice command if openai-whisper or faster-whisper is installed)

Behaviour (mirrors the nav team's mission manager closely enough to test the UI):
  - "start" / "resume" on /voice/text -> SURVEYING, the mission replays; "stop" -> IDLE;
    "return" -> RETURNING then IDLE; "manual" -> MANUAL; "capture" -> CAPTURING briefly.
  - Teleop while surveying -> MANUAL (like twist_mux + mission manager); the sim robot drives with it.
  - /estop true -> STOPPED, robot frozen until false + "resume".
  - /camera/image/compressed shows the stored frame of the nearest bubble facing the robot's heading.

Point the app at it: the editor uses 127.0.0.1 by default (RosSurveySource); on the Quest, push this
laptop's IP (printed at startup) as ros_ip.txt (see AGENTS.md) and be on the same Wi-Fi. Stdlib only.
"""
import argparse
import functools
import json
import math
import socket
import struct
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MISSIONS = ROOT / 'fake_data' / 'missions'
print = functools.partial(print, flush=True)  # show logs live even when piped
CDR_HEADER = b'\x00\x01\x00\x00'  # little-endian CDR encapsulation, same as Unity's k_Ros2Header


# ---------------------------------------------------------------- CDR (ROS 2 serialization) writer

class Cdr:
    """Minimal CDR writer; alignment is relative to the start after the 4-byte header."""

    def __init__(self):
        self.b = bytearray()

    def align(self, n):
        self.b += b'\x00' * ((-len(self.b)) % n)

    def u8(self, v): self.b += struct.pack('<B', v)
    def i32(self, v): self.align(4); self.b += struct.pack('<i', v)
    def u32(self, v): self.align(4); self.b += struct.pack('<I', v)
    def f32(self, v): self.align(4); self.b += struct.pack('<f', v)
    def f64(self, v): self.align(8); self.b += struct.pack('<d', v)

    def string(self, s):
        data = s.encode('utf-8')
        self.u32(len(data) + 1)
        self.b += data + b'\x00'

    def u8_seq(self, data):
        self.u32(len(data))
        self.b += data

    def i8_seq(self, values):
        self.u32(len(values))
        self.b += struct.pack(f'<{len(values)}b', *values)

    def header(self, frame_id, t=None):
        t = time.time() if t is None else t
        self.i32(int(t))
        self.u32(int((t % 1) * 1e9))
        self.string(frame_id)

    def pose(self, x, y, yaw):
        for v in (x, y, 0.0):
            self.f64(v)
        for v in (0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2)):  # quaternion x, y, z, w
            self.f64(v)

    def bytes(self):
        return CDR_HEADER + bytes(self.b)


def msg_string(s):
    c = Cdr(); c.string(s); return c.bytes()


def msg_compressed_image(frame_id, jpg):
    c = Cdr(); c.header(frame_id); c.string('jpeg'); c.u8_seq(jpg); return c.bytes()


def msg_pose_cov_stamped(x, y, yaw):
    c = Cdr(); c.header('map'); c.pose(x, y, yaw)
    for _ in range(36):
        c.f64(0.0)
    return c.bytes()


def msg_occupancy_grid(grid):
    c = Cdr(); c.header('map')
    c.i32(0); c.u32(0)                      # info.map_load_time
    c.f32(grid['resolution']); c.u32(grid['width']); c.u32(grid['height'])
    c.pose(grid['origin'][0], grid['origin'][1], 0.0)
    c.i8_seq(grid['data'])
    return c.bytes()


# ---------------------------------------------------------------- reading what the Quest sends

def parse_twist(payload):
    body = payload[4:]
    lx, ly, lz, ax, ay, az = struct.unpack_from('<6d', body, 0)
    return lx, ly, az


def parse_bool(payload):
    return payload[4] != 0


def parse_uint8_multiarray(payload):
    """std_msgs/UInt8MultiArray -> data bytes (layout skipped)."""
    body = payload[4:]
    off = 0
    dims = struct.unpack_from('<I', body, off)[0]; off += 4
    for _ in range(dims):
        n = struct.unpack_from('<I', body, off)[0]; off += 4 + n   # label
        off += (-off) % 4
        off += 8                                                    # size, stride
    off += 4                                                        # data_offset
    n = struct.unpack_from('<I', body, off)[0]; off += 4
    return body[off:off + n]


_whisper = None


def transcribe(wav_path):
    """Best effort: faster-whisper or openai-whisper if installed, else None."""
    global _whisper
    try:
        if _whisper is None:
            try:
                from faster_whisper import WhisperModel
                _whisper = ('faster', WhisperModel('small.en', compute_type='int8'))
            except ImportError:
                import whisper
                _whisper = ('openai', whisper.load_model('small.en'))
        kind, model = _whisper
        if kind == 'faster':
            segments, _ = model.transcribe(str(wav_path))
            return ' '.join(seg.text for seg in segments).strip()
        return model.transcribe(str(wav_path))['text'].strip()
    except ImportError:
        return None
    except Exception as e:  # model download failure etc.
        print(f'[mock] whisper failed: {e}')
        return None


def parse_string(payload):
    n = struct.unpack_from('<I', payload, 4)[0]
    return payload[8:8 + n - 1].decode('utf-8', 'replace')


# ---------------------------------------------------------------- framing

def frame(topic, payload):
    t = topic.encode('ascii')
    return struct.pack('<I', len(t)) + t + struct.pack('<I', len(payload)) + payload


def read_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('closed')
        buf += chunk
    return bytes(buf)


def read_frame(sock):
    n = struct.unpack('<I', read_exact(sock, 4))[0]
    topic = read_exact(sock, n).rstrip(b'\x00').decode('ascii', 'replace')
    m = struct.unpack('<I', read_exact(sock, 4))[0]
    return topic, read_exact(sock, m)


# ---------------------------------------------------------------- mission data

def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def load_map(folder):
    """map.pgm (P5) + map.yaml -> OccupancyGrid fields (row 0 = bottom)."""
    yaml = {}
    for line in (folder / 'map.yaml').read_text().splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            yaml[k.strip()] = v.strip()
    raw = (folder / 'map.pgm').read_bytes()
    tokens, pos = [], 0
    while len(tokens) < 4:
        while raw[pos:pos + 1].isspace():
            pos += 1
        if raw[pos:pos + 1] == b'#':
            pos = raw.index(b'\n', pos)
            continue
        start = pos
        while not raw[pos:pos + 1].isspace():
            pos += 1
        tokens.append(raw[start:pos])
    pos += 1
    w, h, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
    occ, free = float(yaml.get('occupied_thresh', 0.65)), float(yaml.get('free_thresh', 0.25))
    data = []
    for r in range(h - 1, -1, -1):
        for c in range(w):
            p = 1.0 - raw[pos + r * w + c] / maxval
            data.append(100 if p > occ else 0 if p < free else -1)
    origin = [float(v) for v in yaml['origin'].strip('[]').split(',')]
    return {'resolution': float(yaml['resolution']), 'width': w, 'height': h, 'origin': origin, 'data': data}


# ---------------------------------------------------------------- the mock robot + mission

class MockRobot:
    def __init__(self, missions, speed):
        self.missions = missions
        self.mission_index = -1
        self.speed = speed
        self.state = 'IDLE'
        self.x = self.y = self.yaw = 0.0
        self.estop = False
        self.teleop = (0.0, 0.0, 0.0)
        self.teleop_t = 0.0
        self.lock = threading.Lock()
        self.load_next_mission()

    def load_next_mission(self):
        """Advance to the next mission in --missions (e.g. m1 then the m2 re-survey)."""
        self.mission_index += 1
        mission = self.missions[self.mission_index]
        self.folder = MISSIONS / mission
        if not self.folder.exists():
            raise SystemExit(f'{self.folder} not found. Run: python fake_data/generate.py')
        self.bubbles = load_jsonl(self.folder / 'bubbles.jsonl')
        self.pins = load_jsonl(self.folder / 'pins.jsonl')
        self.readings = load_jsonl(self.folder / 'readings.jsonl')
        self.grid = load_map(self.folder)
        self.events = self.build_timeline()
        self.cursor = 0
        self.mission_clock = 0.0
        more = len(self.missions) - self.mission_index - 1
        print(f'[mock] mission {mission}: {len(self.bubbles)} bubbles, {len(self.pins)} pins, '
              f'{len(self.readings)} readings' + (f'; {more} more queued (press Start after this one)' if more else ''))

    @property
    def finished(self):
        return self.cursor >= len(self.events)

    def build_timeline(self):
        ev = [(r['t'], 'reading', r) for r in self.readings]
        for b in self.bubbles:
            ev.append((b['t'] - 24, 'state', 'CAPTURING'))
            ev.append((b['t'], 'bubble', b))
            for k, p in enumerate(q for q in self.pins if q['bubble_id'] == b['bubble_id']):
                ev.append((b['t'] + 0.5 + 0.5 * k, 'pin', p))
            ev.append((b['t'] + 3, 'state', 'NEXT_POINT'))
        ev.sort(key=lambda e: e[0])
        t0 = ev[0][0] if ev else 0
        return [(t - t0, kind, data) for t, kind, data in ev]

    # --- commands from the Quest
    def on_voice(self, text):
        word = text.strip().lower()
        with self.lock:
            if word in ('start', 'resume') and not self.estop:
                if word == 'start' and self.finished and self.mission_index + 1 < len(self.missions):
                    self.load_next_mission()
                self.state = 'SURVEYING'
            elif word == 'stop':
                self.state = 'IDLE'
            elif word in ('return', 'come back', 'go home'):
                self.state = 'RETURNING'
            elif word == 'manual':
                self.state = 'MANUAL'
            elif word == 'capture':
                self.state = 'CAPTURING'
        print(f'[mock] /voice/text "{text}" -> {self.state}')

    def on_estop(self, on):
        with self.lock:
            changed = on != self.estop
            self.estop = on
            if on:
                self.state = 'STOPPED'
        if changed:
            print(f'[mock] /estop {on} -> {self.state}')

    def on_teleop(self, vx, vy, wz):
        with self.lock:
            self.teleop = (vx, vy, wz)
            self.teleop_t = time.time()
            if self.state in ('SURVEYING', 'CAPTURING', 'NEXT_POINT', 'RETURNING') and any(abs(v) > 1e-3 for v in self.teleop):
                self.state = 'MANUAL'
                print('[mock] teleop during autonomy -> MANUAL')

    # --- sim step; returns messages to publish
    def step(self, dt):
        out = []
        with self.lock:
            teleop_live = time.time() - self.teleop_t < 0.5 and not self.estop
            if teleop_live:
                vx, vy, wz = self.teleop
                c, s = math.cos(self.yaw), math.sin(self.yaw)
                self.x += (vx * c - vy * s) * dt
                self.y += (vx * s + vy * c) * dt
                self.yaw = math.atan2(math.sin(self.yaw + wz * dt), math.cos(self.yaw + wz * dt))
            if self.state in ('SURVEYING', 'CAPTURING', 'NEXT_POINT'):
                self.mission_clock += dt * self.speed
                while self.cursor < len(self.events) and self.events[self.cursor][0] <= self.mission_clock:
                    _, kind, data = self.events[self.cursor]
                    self.cursor += 1
                    out.extend(self.emit(kind, data))
                if self.cursor >= len(self.events):
                    self.state = 'RETURNING'
                    self.return_t = time.time()
            elif self.state == 'RETURNING':
                d = math.hypot(self.x, self.y)
                if d < 0.05 or time.time() - getattr(self, 'return_t', 0) > 8:
                    self.state = 'IDLE'
                else:
                    k = min(1.0, 0.25 * dt / d)
                    self.x -= self.x * k
                    self.y -= self.y * k
        return out

    def emit(self, kind, data):
        if kind == 'state':
            self.state = data
            return []
        if kind == 'reading':
            if time.time() - self.teleop_t > 0.5:  # follow the recorded path unless someone is driving
                dx, dy = data['x'] - self.x, data['y'] - self.y
                if math.hypot(dx, dy) > 0.02:
                    self.yaw = math.atan2(dy, dx)
                self.x, self.y = data['x'], data['y']
            return [frame('/survey/readings', msg_string(json.dumps(data)))]
        if kind == 'bubble':
            self.state = 'CAPTURING'
            out = []
            for f in data['frames']:
                jpg = self.folder / 'frames' / f"{data['bubble_id']}_{f['index']}.jpg"
                if jpg.exists():
                    out.append(frame('/survey/bubble_images', msg_compressed_image(f"{data['bubble_id']}/{f['index']}", jpg.read_bytes())))
            pano = self.folder / 'frames' / f"{data['bubble_id']}_pano.jpg"
            if data.get('stitched') and pano.exists():
                out.append(frame('/survey/bubble_images', msg_compressed_image(f"{data['bubble_id']}/pano", pano.read_bytes())))
            out.append(frame('/survey/bubbles', msg_string(json.dumps(data))))  # like panorama_node: images first
            print(f"[mock] bubble {data['bubble_id']}")
            return out
        if kind == 'pin':
            print(f"[mock] pin {data['pin_id']} {data['label']}")
            return [frame('/survey/pins', msg_string(json.dumps(data)))]
        return []

    def camera_frame(self):
        """Stored frame of the nearest bubble whose yaw is closest to the robot's heading."""
        with self.lock:
            if not self.bubbles:
                return None
            b = min(self.bubbles, key=lambda q: math.hypot(q['x'] - self.x, q['y'] - self.y))
            f = min(b['frames'], key=lambda q: abs(math.atan2(math.sin(q['yaw'] - self.yaw), math.cos(q['yaw'] - self.yaw))))
        jpg = self.folder / 'frames' / f"{b['bubble_id']}_{f['index']}.jpg"
        return jpg.read_bytes() if jpg.exists() else None


# ---------------------------------------------------------------- server

def serve_client(conn, addr, robot, args):
    print(f'[mock] Quest connected from {addr[0]}')
    send_lock = threading.Lock()

    def send(data):
        with send_lock:
            conn.sendall(data)

    handshake = json.dumps({'version': 'v0.7.0', 'metadata': json.dumps({'protocol': 'ROS2'})})
    send(frame('__handshake', handshake.encode('utf-8')))
    alive = [True]

    def reader():
        try:
            while alive[0]:
                topic, payload = read_frame(conn)
                if not topic or topic.startswith('__'):
                    continue  # keepalives, __subscribe / __publish registrations
                if topic == '/cmd_vel_teleop':
                    robot.on_teleop(*parse_twist(payload))
                elif topic == '/estop':
                    robot.on_estop(parse_bool(payload))
                elif topic == '/voice/text':
                    robot.on_voice(parse_string(payload))
                elif topic == '/voice/audio':
                    wav = parse_uint8_multiarray(payload)
                    path = Path(tempfile.gettempdir()) / 'understory_voice_last.wav'
                    path.write_bytes(wav)
                    seconds = (len(wav) - 44) / (16000 * 2)
                    print(f'[mock] /voice/audio {seconds:.1f}s -> {path}')
                    text = transcribe(path)
                    if text is None:
                        print('[mock]   (install faster-whisper or openai-whisper to transcribe; '
                              'the real pipeline: Whisper on the Jetson -> /voice/text)')
                    else:
                        print(f'[mock]   whisper: "{text}"')
                        for word in ('start', 'stop', 'return', 'come back', 'go home', 'manual', 'capture', 'resume'):
                            if word in text.lower():
                                robot.on_voice(word)
                                break
                else:
                    print(f'[mock] (ignored) {topic} {len(payload)} bytes')
        except (ConnectionError, OSError):
            pass
        finally:
            alive[0] = False

    threading.Thread(target=reader, daemon=True).start()
    start = time.time()
    last = time.time()
    next_state = next_pose = next_cam = next_map = 0.0
    try:
        while alive[0]:
            now = time.time()
            if robot.state == 'IDLE' and robot.mission_index == 0 and robot.cursor == 0 and args.autostart and now - start > 3:
                robot.on_voice('start')
            for data in robot.step(now - last):
                send(data)
            last = now
            if now >= next_map:
                send(frame('/map', msg_occupancy_grid(robot.grid)))
                next_map = now + 5.0
            if now >= next_state:
                send(frame('/mission/state', msg_string(robot.state)))
                next_state = now + 1.0
            if now >= next_pose:
                send(frame('/pose', msg_pose_cov_stamped(robot.x, robot.y, robot.yaw)))
                next_pose = now + 0.1
            if args.camera_fps > 0 and now >= next_cam:
                jpg = robot.camera_frame()
                if jpg:
                    send(frame('/camera/image/compressed', msg_compressed_image('camera', jpg)))
                next_cam = now + 1.0 / args.camera_fps
            time.sleep(0.02)
    except (ConnectionError, OSError):
        pass
    alive[0] = False
    conn.close()
    print('[mock] Quest disconnected')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--missions', default='m1',
                    help='comma-separated, played in order; Start after one finishes begins the next (e.g. m1,m2)')
    ap.add_argument('--port', type=int, default=10000)
    ap.add_argument('--speed', type=float, default=3.0, help='mission replay speed vs. recorded time')
    ap.add_argument('--camera-fps', type=float, default=5.0)
    ap.add_argument('--no-autostart', dest='autostart', action='store_false',
                    help='wait for "Start survey" from the app instead of starting after 3 s')
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', args.port))
    srv.listen(1)
    ips = sorted({i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})
    print(f'[mock] ROS-TCP mock endpoint on port {args.port}; this machine: {", ".join(ips)}')
    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Fresh mission per connection, so reconnecting the app restarts the demo.
        robot = MockRobot([m.strip() for m in args.missions.split(',') if m.strip()], args.speed)
        serve_client(conn, addr, robot, args)


if __name__ == '__main__':
    main()
