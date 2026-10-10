#!/usr/bin/env bash
# Unit tests for the Quest app's pure logic (JSON contracts on every fake mission line, map loading,
# before/after rule, RosCoords), compiled from the real Unity source files and run on Unity's bundled .NET
# outside the editor. See tools/unity_logic_test/Program.cs.
#
#   bash tools/test_unity_logic.sh
set -euo pipefail
cd "$(dirname "$0")/.."
E="C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Data"
T="${TEMP:-/tmp}/understory_logic_test"
rm -rf "$T"; mkdir -p "$T"
TW=$(cd "$T" && pwd -W)
R=$(pwd -W)
NJ=$(ls Unity/Library/PackageCache/com.unity.nuget.newtonsoft-json@*/Runtime/Newtonsoft.Json.dll | head -1)
cp "$NJ" "$T/"
cp "$E"/Managed/UnityEngine/*.dll "$T/"   # metadata for reflection (attributes); native calls are avoided
"$E/NetCoreRuntime/dotnet.exe" "$E/DotNetSdkRoslyn/csc.dll" -nologo -target:exe -nostdlib -nowarn:0649 -out:"$TW/logic.dll" \
  -r:"$E/NetStandard/ref/2.1.0/netstandard.dll" -r:"$TW/UnityEngine.CoreModule.dll" -r:"$TW/Newtonsoft.Json.dll" \
  "$R/tools/unity_logic_test/Program.cs" \
  "$R/Unity/Assets/Scripts/Contracts/SurveyContracts.cs" \
  "$R/Unity/Assets/Scripts/Contracts/RosCoords.cs" \
  "$R/Unity/Assets/Scripts/Survey/MapGrid.cs"
echo '{"runtimeOptions":{"tfm":"net8.0","framework":{"name":"Microsoft.NETCore.App","version":"8.0.16"}}}' > "$T/logic.runtimeconfig.json"
"$E/NetCoreRuntime/dotnet.exe" "$TW/logic.dll" "$R/fake_data/missions"
