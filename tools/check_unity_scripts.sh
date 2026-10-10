#!/usr/bin/env bash
# Compile every script in Unity/Assets/Scripts with Unity's own Roslyn, against the engine + package DLLs,
# without opening (or focusing) the editor. Catches compile errors in seconds.
#
#   bash tools/check_unity_scripts.sh
#
# Needs: Unity 6000.4.9f1 installed via Hub (default path) and the project opened once
# (Library/ScriptAssemblies + Library/PackageCache must exist). Windows / Git Bash.
set -euo pipefail

UNITY_VERSION=6000.4.9f1
E="C:/Program Files/Unity/Hub/Editor/$UNITY_VERSION/Editor/Data"
cd "$(dirname "$0")/../Unity"
OUT="${TEMP:-/tmp}/understory_csc_check"
mkdir -p "$OUT"
RSP="$OUT/check.rsp"

NEWTONSOFT=$(ls Library/PackageCache/com.unity.nuget.newtonsoft-json@*/Runtime/Newtonsoft.Json.dll | head -1)
{
  echo "-nologo -target:library -out:\"$OUT/check.dll\" -nostdlib -langversion:9 -nowarn:1701,1702,0649,0618"
  echo "-define:UNITY_EDITOR;ROS2;UNITY_6000_0_OR_NEWER"
  echo "-r:\"$E/NetStandard/ref/2.1.0/netstandard.dll\""
  for d in "$E"/Managed/UnityEngine/*.dll; do echo "-r:\"$d\""; done
  for d in Library/ScriptAssemblies/Oculus.VR.dll \
           Library/ScriptAssemblies/Unity.InputSystem.dll \
           Library/ScriptAssemblies/Unity.Robotics.ROSTCPConnector.dll \
           Library/ScriptAssemblies/Unity.Robotics.ROSTCPConnector.MessageGeneration.dll \
           Library/ScriptAssemblies/Unity.Robotics.ROSTCPConnector.Messages.dll \
           "$NEWTONSOFT"; do
    echo "-r:\"$(pwd -W)/$d\""
  done
  find Assets/Scripts -name "*.cs" | while read -r f; do echo "\"$(pwd -W)/$f\""; done
} > "$RSP"

"$E/NetCoreRuntime/dotnet.exe" "$E/DotNetSdkRoslyn/csc.dll" "@$RSP"
echo "OK: Assets/Scripts compiles."
