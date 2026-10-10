using System;
using System.Globalization;
using System.Text;
using UnityEngine;

namespace Understory
{
    /// <summary>
    /// Occupancy grid in the same layout as nav_msgs/OccupancyGrid: row-major, row 0 = lowest ROS y,
    /// column 0 = lowest ROS x. Cells: -1 unknown, 0 free, 100 occupied.
    /// Built from /map (ROS) or map.pgm + map.yaml (mission folder / fake_data).
    /// </summary>
    public class MapGrid
    {
        public int Width, Height;
        public float Resolution;       // meters per cell
        public float OriginX, OriginY; // ROS map-frame position of cell (0, 0)'s corner
        public sbyte[] Cells;

        public float WidthMeters => Width * Resolution;
        public float HeightMeters => Height * Resolution;

        public sbyte this[int col, int row] => Cells[row * Width + col];

        /// <summary>ROS map-frame position of a cell's center.</summary>
        public Vector2 CellCenterRos(int col, int row) =>
            new Vector2(OriginX + (col + 0.5f) * Resolution, OriginY + (row + 0.5f) * Resolution);

        /// <summary>ROS map-frame center of the whole grid.</summary>
        public Vector2 CenterRos => new Vector2(OriginX + WidthMeters / 2f, OriginY + HeightMeters / 2f);

        /// <summary>
        /// Texture with texel (u, v) = cell (col, row), so texture u runs along ROS +x and v along ROS +y.
        /// Note ROS +y is Unity -x: place the quad via RosCoords, don't assume texture u = Unity x.
        /// </summary>
        public Texture2D ToTexture(Color32? free = null, Color32? occupied = null, Color32? unknown = null)
        {
            var f = free ?? new Color32(235, 235, 225, 255);
            var o = occupied ?? new Color32(30, 30, 30, 255);
            var u = unknown ?? new Color32(0, 0, 0, 0);
            var px = new Color32[Cells.Length];
            for (int i = 0; i < Cells.Length; i++)
                px[i] = Cells[i] < 0 ? u : Cells[i] >= 50 ? o : f;
            var tex = new Texture2D(Width, Height, TextureFormat.RGBA32, false) { filterMode = FilterMode.Point, wrapMode = TextureWrapMode.Clamp };
            tex.SetPixels32(px);
            tex.Apply(false, true);
            return tex;
        }

        /// <summary>Parse map_saver_cli output (binary P5 .pgm + .yaml).</summary>
        public static MapGrid FromPgm(byte[] pgm, string yaml)
        {
            float resolution = 0.05f, occThresh = 0.65f, freeThresh = 0.25f;
            float ox = 0f, oy = 0f;
            bool negate = false;
            foreach (var raw in yaml.Split('\n'))
            {
                int colon = raw.IndexOf(':');
                if (colon < 0) continue;
                string key = raw.Substring(0, colon).Trim(), val = raw.Substring(colon + 1).Trim();
                switch (key)
                {
                    case "resolution": resolution = ParseF(val); break;
                    case "occupied_thresh": occThresh = ParseF(val); break;
                    case "free_thresh": freeThresh = ParseF(val); break;
                    case "negate": negate = val == "1" || val.ToLowerInvariant() == "true"; break;
                    case "origin":
                        var parts = val.Trim('[', ']').Split(',');
                        ox = ParseF(parts[0]);
                        oy = ParseF(parts[1]);
                        break;
                }
            }

            int pos = 0;
            string magic = NextToken(pgm, ref pos);
            if (magic != "P5") throw new FormatException($"Expected binary PGM (P5), got '{magic}'");
            int w = int.Parse(NextToken(pgm, ref pos)), h = int.Parse(NextToken(pgm, ref pos));
            int maxVal = int.Parse(NextToken(pgm, ref pos));
            pos++; // single whitespace byte before pixel data
            if (maxVal > 255) throw new FormatException("16-bit PGM not supported");

            var cells = new sbyte[w * h];
            for (int r = 0; r < h; r++)
            for (int c = 0; c < w; c++)
            {
                float v = pgm[pos + r * w + c] / (float)maxVal;
                float p = negate ? v : 1f - v; // probability occupied
                sbyte cell = p > occThresh ? (sbyte)100 : p < freeThresh ? (sbyte)0 : (sbyte)-1;
                cells[(h - 1 - r) * w + c] = cell; // PGM row 0 is the top (max y)
            }

            return new MapGrid { Width = w, Height = h, Resolution = resolution, OriginX = ox, OriginY = oy, Cells = cells };
        }

        static float ParseF(string s) => float.Parse(s.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture);

        static string NextToken(byte[] b, ref int pos)
        {
            while (pos < b.Length)
            {
                if (b[pos] == '#') { while (pos < b.Length && b[pos] != '\n') pos++; }
                else if (char.IsWhiteSpace((char)b[pos])) pos++;
                else break;
            }
            int start = pos;
            while (pos < b.Length && !char.IsWhiteSpace((char)b[pos])) pos++;
            return Encoding.ASCII.GetString(b, start, pos - start);
        }
    }
}
