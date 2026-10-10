// Unit tests for the Quest app's pure logic, compiled from the real source files and run on Unity's
// bundled .NET outside the editor (bash tools/test_unity_logic.sh). Only managed UnityEngine code paths
// are exercised (Vector3 math, Mathf constants); anything native (Quaternion.Euler, Texture2D) is avoided.
using System;
using System.IO;
using System.Linq;
using Understory;
using UnityEngine;

static class Program
{
    static int failures;

    static void Check(bool ok, string what)
    {
        Console.WriteLine($"{(ok ? "ok  " : "FAIL")}  {what}");
        if (!ok) failures++;
    }

    static int Main(string[] args)
    {
        string missions = args[0];

        // --- JSON contracts against every fake mission line
        foreach (var id in new[] { "m1", "m2" })
        {
            string dir = Path.Combine(missions, id);
            var bubbles = SurveyJson.ParseLines<Bubble>(File.ReadAllText(Path.Combine(dir, "bubbles.jsonl")));
            var pins = SurveyJson.ParseLines<Pin>(File.ReadAllText(Path.Combine(dir, "pins.jsonl")));
            var readings = SurveyJson.ParseLines<Reading>(File.ReadAllText(Path.Combine(dir, "readings.jsonl")));
            Check(bubbles.Count == 5 && bubbles.All(b => b.Frames.Count == 12 && b.MissionId == id), $"{id}: 5 bubbles x 12 frames");
            Check(pins.All(p => p.PinId.StartsWith(id + "-p") && p.BubbleId.StartsWith(id + "-b") && p.Crop == p.PinId + ".jpg"), $"{id}: pin ids / crops");
            Check(readings.Count == 77, $"{id}: 77 readings");
            Check(readings.Any(r => r.Uv == null) && readings.Any(r => r.Uv != null), $"{id}: omitted uv stays null (not 0)");
            Check(readings.All(r => r.SoilMoisture != null && r.TempC != null), $"{id}: soil/temperature present");
        }
        var m1pins = SurveyJson.ParseLines<Pin>(File.ReadAllText(Path.Combine(missions, "m1", "pins.jsonl")));
        var m2pins = SurveyJson.ParseLines<Pin>(File.ReadAllText(Path.Combine(missions, "m2", "pins.jsonl")));
        Check(m1pins.Count(p => p.Invasive) == 7 && m2pins.Count(p => p.Invasive) == 1, "invasives: m1 7, m2 1");

        // Before/after rule (same label within 0.5 m), as BeforeAfterOverlay applies it.
        int remaining = m1pins.Where(p => p.Invasive).Count(old => m2pins.Any(p => p.Invasive && p.Label == old.Label &&
            (p.X - old.X) * (p.X - old.X) + (p.Y - old.Y) * (p.Y - old.Y) <= 0.25f));
        Check(remaining == 1, $"before/after: 7 -> {remaining} remaining");

        // Round trip: missing sensors are omitted when written back.
        var r0 = new Reading { MissionId = "m1", T = 1, X = 1, Y = 2, TempC = 24.5f };
        string json = r0.ToJson();
        Check(json.Contains("\"temp_c\"") && !json.Contains("uv") && !json.Contains("null"), "Reading.ToJson omits missing sensors");
        Check(SurveyJson.Parse<Bubble>("{\"bubble_id\":\"m1-b09\",\"extra_key\":5}")?.BubbleId == "m1-b09", "unknown JSON keys ignored");

        Check(MissionStates.Parse("SURVEYING") == MissionState.SURVEYING && MissionStates.Parse(" NEXT_POINT ") == MissionState.NEXT_POINT
              && MissionStates.Parse("bogus") == MissionState.Unknown, "mission state parsing");

        // --- MapGrid from map_saver output (same numbers the mock sends as /map)
        var grid = MapGrid.FromPgm(File.ReadAllBytes(Path.Combine(missions, "m1", "map.pgm")),
                                   File.ReadAllText(Path.Combine(missions, "m1", "map.yaml")));
        Check(grid.Width == 180 && grid.Height == 140 && Math.Abs(grid.Resolution - 0.05f) < 1e-6, "map 180x140 @ 0.05");
        Check(Math.Abs(grid.OriginX + 2.5f) < 1e-6 && Math.Abs(grid.OriginY + 2.5f) < 1e-6, "map origin (-2.5, -2.5)");
        Check(grid.Cells.Count(c => c == 100) == 1536, "1536 occupied cells (matches the mock's /map)");
        Check(CellAt(grid, 0f, 0f) == 0, "robot start (0,0) is free");
        Check(CellAt(grid, 6.0f, 1.0f) == 100, "wall at x=6 (room edge) is occupied");
        Check(CellAt(grid, 1.5f, 1.3f) == -1, "inside a plant bed is unknown");
        var copy = MapGrid.FromOccupancyGrid(grid.Width, grid.Height, grid.Resolution, grid.OriginX, grid.OriginY, grid.Cells);
        Check(copy.CenterRos == grid.CenterRos, "FromOccupancyGrid keeps layout");

        // --- RosCoords: x forward, y left, z up -> Unity x right, y up, z forward
        Check(RosCoords.ToUnity(1, 2, 3) == new Vector3(-2, 3, 1), "ToUnity(1,2,3) = (-2,3,1)");
        Check(RosCoords.ToRos(RosCoords.ToUnity(1.5f, -0.3f, 0.2f)) == new Vector3(1.5f, -0.3f, 0.2f), "ToRos inverts ToUnity");
        Check(Math.Abs(RosCoords.ToUnityYaw(Mathf.PI / 2) + 90f) < 1e-4, "ROS yaw +90 (left) -> Unity -90");

        Console.WriteLine(failures == 0 ? "ALL PASSED" : $"{failures} FAILED");
        return failures == 0 ? 0 : 1;
    }

    static sbyte CellAt(MapGrid g, float x, float y) =>
        g[(int)((x - g.OriginX) / g.Resolution), (int)((y - g.OriginY) / g.Resolution)];
}
