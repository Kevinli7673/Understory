# Understory Quest app

Unity 6 (`6000.4.9f1`, URP) app for Quest 3: a tabletop twin of the surveyed place, 360° bubbles you can
stand in, robot driving + e-stop, and before/after of invasive removal. Contracts and topics: `../AGENTS.md`.

## Data flow

```
ROS (Jetson, ros_tcp_endpoint :10000) ─┐
   RosSurveySource                     ├─► SurveyHub ─► TabletopMap, BubbleRingBuilder, PinCard,
fake_data/missions/<id> ───────────────┘   (Handle*)     BeforeAfterOverlay, SensorHeatmap, SplatView,
   FakeSurveySource (until ROS goes live)                SpeciesAlert, CameraScreen, BubbleNavigator

Quest ─► TeleopController (/cmd_vel_teleop, /estop) · MissionPanel (/voice/text) · PushToTalk (/voice/audio)
```

- Every ROS ↔ Unity coordinate conversion goes through `Scripts/Contracts/RosCoords.cs`.
- The fake replay and ROS call the **same** `SurveyHub.Handle*` methods; views only listen to the hub.
- A new `mission_id` archives the previous mission's pins (`SurveyHub.PreviousMissionPins`) for before/after.

## First-time setup

1. Package Manager: `com.unity.xr.openxr`. Project Settings → XR Plug-in Management → **Android**: OpenXR +
   **Meta Quest** feature group; OpenXR → Android → Interaction Profiles: **Oculus Touch Controller**.
2. Meta → Tools → Project Setup Tool → Fix All (twice).
3. **Understory → Set Up Quest Rig and Player Settings** (adds OVRCameraRig + every component, sets the
   package id `com.knighthacks.understory`, saves the scene). Safe to run again.
4. Build Profiles → Android → Run Device: Quest 3 → Build And Run. Fake missions (and any
   `splat/out/*/scene.splat`) are copied into the APK automatically.

## Controls

| Quest | Editor | Action |
| --- | --- | --- |
| R trigger | left click | select capture spot / plant pin / panel button / floor arrow |
| A | Tab | tabletop ↔ bubble view |
| **B** | **Space** | **e-stop** toggle |
| L stick / R stick | WASD / QE | drive + strafe / turn |
| L grip | | move the table |
| X (hold) | T (hold) | push-to-talk |
| | right-drag | look around |
| | C · V · H · M | recenter · compare before · sensor map · 3D model |
| | [ ] · R | previous/next bubble · prefer pano |

Panel buttons (right of the table): Start survey, Capture here, Resume, Manual, Return home, Stop mission
(sent to the mission manager on `/voice/text`), Compare before, Sensor map, 3D model (local).

## Testing without the robot

- **Editor / headset, no network:** m1 replays on launch; *Start survey* after it finishes plays m2
  (re-survey); *Compare before* → "7 invasive → 1 remaining".
- **ROS path on a laptop:** `python tools/quest_mock_endpoint.py --missions m1,m2` (stdlib only) speaks the
  ros_tcp_endpoint protocol, simulates the robot and prints what the app sends. Editor connects to
  127.0.0.1; on the Quest push the laptop IP (below).
- **Compile check without focusing Unity:** `bash tools/check_unity_scripts.sh` (editor + Android passes).
- **Logic unit tests:** `bash tools/test_unity_logic.sh` (JSON contracts on every fake mission line, map loading,
  before/after rule, RosCoords; real source files on Unity's .NET).
- **ROS wire format:** `bash tools/test_ros_compat.sh` round-trips messages between the mock and the real
  ROS-TCP-Connector message classes (Unity's .NET, no editor).
- **Jetson / mock IP on the headset:** in VR, panel **Robot address** → keypad → Connect (saved + reconnects). Or
  `echo 192.168.x.y > ros_ip.txt && adb push ros_ip.txt /sdcard/Android/data/com.knighthacks.understory/files/`,
  then restart the app. The table's status line shows `LIVE <ip>` or `FAKE · connecting <ip>`.

## Scripts

| Folder | What |
| --- | --- |
| `Contracts/` | JSON contract classes, `RosCoords` |
| `Survey/` | `SurveyHub`, `FakeSurveySource`, `MissionFiles`, `MapGrid` |
| `Ros/` | `RosSurveySource`, `TeleopController`, `PushToTalk` |
| `Tabletop/` | `TabletopMap`, `MissionPanel`, `PinCard`, `BeforeAfterOverlay`, `SensorHeatmap`, `SplatView`, `CameraScreen`, `ControlsHint` |
| `Bubbles/` | `BubbleRingBuilder` (frame ring by default, pano fallback), `BubbleNavigator` |
| `Views/` | `ViewSwitcher`, `ControllerPointer`, `TableGrab`, `SpeciesAlert` |
| `Util/` | `WorldUI`, `Haptics`, `DesktopLook` |
| `Editor/` | `QuestSetupMenu`, `FakeDataMenu` (+ Android build step) |
| `../Shaders/` | `SplatBillboard` (splat / point cloud discs, multiview-safe) |
