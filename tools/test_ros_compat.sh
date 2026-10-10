#!/usr/bin/env bash
# Round-trip check of the ROS wire format between tools/quest_mock_endpoint.py and the Quest app's real
# ROS-TCP-Connector message classes (run outside Unity on Unity's bundled .NET):
#   1. Python (mock encoder) writes String / OccupancyGrid / CompressedImage / PoseWithCovarianceStamped
#   2. C# (Unity's message DLLs) decodes them and serializes Twist / Bool / String / UInt8MultiArray
#   3. Python (mock parsers) decodes those
#
#   bash tools/test_ros_compat.sh
#
# Needs Unity 6000.4.9f1 (Hub default path) and the project opened once (Library/ScriptAssemblies). Windows / Git Bash.
set -euo pipefail
cd "$(dirname "$0")/.."
E="C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Data"
T="${TEMP:-/tmp}/understory_ros_compat"
rm -rf "$T"; mkdir -p "$T"
TW=$(cd "$T" && pwd -W)

python - "$T" <<'PY'
import sys, importlib.util
from pathlib import Path
out = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('mock', 'tools/quest_mock_endpoint.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
(out / 'grid.bin').write_bytes(m.msg_occupancy_grid(m.load_map(m.MISSIONS / 'm1')))
(out / 'state.bin').write_bytes(m.msg_string('SURVEYING'))
(out / 'bubble.bin').write_bytes(m.msg_string((m.MISSIONS / 'm1' / 'bubbles.jsonl').read_text().splitlines()[0]))
(out / 'image.bin').write_bytes(m.msg_compressed_image('m1-b01/3', (m.MISSIONS / 'm1' / 'frames' / 'm1-b01_3.jpg').read_bytes()))
(out / 'pose.bin').write_bytes(m.msg_pose_cov_stamped(1.5, -0.3, 0.7))
PY

for d in Unity.Robotics.ROSTCPConnector.MessageGeneration Unity.Robotics.ROSTCPConnector.Messages; do
  cp "Unity/Library/ScriptAssemblies/$d.dll" "$T/"
done
cp "$E/Managed/UnityEngine/UnityEngine.CoreModule.dll" "$T/"
"$E/NetCoreRuntime/dotnet.exe" "$E/DotNetSdkRoslyn/csc.dll" -nologo -target:exe -nostdlib -out:"$TW/compat.dll" \
  -r:"$E/NetStandard/ref/2.1.0/netstandard.dll" -r:"$TW/Unity.Robotics.ROSTCPConnector.MessageGeneration.dll" \
  -r:"$TW/Unity.Robotics.ROSTCPConnector.Messages.dll" -r:"$TW/UnityEngine.CoreModule.dll" "$(pwd -W)/tools/ros_compat/Program.cs"
echo '{"runtimeOptions":{"tfm":"net8.0","framework":{"name":"Microsoft.NETCore.App","version":"8.0.16"}}}' > "$T/compat.runtimeconfig.json"
"$E/NetCoreRuntime/dotnet.exe" "$TW/compat.dll" "$TW"

python - "$T" <<'PY'
import sys, importlib.util
from pathlib import Path
d = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('mock', 'tools/quest_mock_endpoint.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
assert m.parse_twist((d / 'u_twist.bin').read_bytes()) == (0.25, -0.1, 0.8)
assert m.parse_bool((d / 'u_bool.bin').read_bytes()) is True
assert m.parse_string((d / 'u_string.bin').read_bytes()) == 'capture'
assert m.parse_uint8_multiarray((d / 'u_audio.bin').read_bytes()) == bytes([82, 73, 70, 70, 1, 2, 3])
print('Unity -> mock: Twist, Bool, String, UInt8MultiArray OK')
PY
echo "OK: ROS wire format matches in both directions."
