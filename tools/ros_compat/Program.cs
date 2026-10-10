using System;
using System.IO;
using System.Linq;
using RosMessageTypes.Geometry;
using RosMessageTypes.Nav;
using RosMessageTypes.Sensor;
using RosMessageTypes.Std;
using Unity.Robotics.ROSTCPConnector.MessageGeneration;

static class Program
{
    static MessageDeserializer D(string file) { var d = new MessageDeserializer(); d.InitWithBuffer(File.ReadAllBytes(Path.Combine(Dir, file))); return d; }
    static string Dir;

    static int Main(string[] args)
    {
        Dir = args[0];
        // Mock (Python) -> Unity: decode with Unity's real message classes.
        var state = StringMsg.Deserialize(D("state.bin"));
        Console.WriteLine($"String         data='{state.data}'");
        var bubble = StringMsg.Deserialize(D("bubble.bin"));
        Console.WriteLine($"String(json)   {bubble.data.Substring(0, 60)}...");
        var grid = OccupancyGridMsg.Deserialize(D("grid.bin"));
        Console.WriteLine($"OccupancyGrid  frame={grid.header.frame_id} {grid.info.width}x{grid.info.height} res={grid.info.resolution} " +
                          $"origin=({grid.info.origin.position.x},{grid.info.origin.position.y}) cells={grid.data.Length} occupied={grid.data.Count(v => v == 100)}");
        var img = CompressedImageMsg.Deserialize(D("image.bin"));
        Console.WriteLine($"CompressedImage frame_id={img.header.frame_id} format={img.format} bytes={img.data.Length} jpegMagic={img.data[0]:X2}{img.data[1]:X2}");
        var pose = PoseWithCovarianceStampedMsg.Deserialize(D("pose.bin"));
        var q = pose.pose.pose.orientation;
        double yaw = Math.Atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z));
        Console.WriteLine($"PoseWithCov    x={pose.pose.pose.position.x} y={pose.pose.pose.position.y} yaw={yaw:F3} cov={pose.pose.covariance.Length}");

        void Check(bool ok, string what) { if (!ok) throw new Exception("MISMATCH: " + what); }
        Check(state.data == "SURVEYING", "String");
        Check(bubble.data.StartsWith("{\"bubble_id\": \"m1-b01\""), "String(json)");
        Check(grid.info.width == 180 && grid.info.height == 140 && Math.Abs(grid.info.resolution - 0.05f) < 1e-6
              && grid.data.Length == 25200 && grid.header.frame_id == "map", "OccupancyGrid");
        Check(img.header.frame_id == "m1-b01/3" && img.data[0] == 0xFF && img.data[1] == 0xD8, "CompressedImage");
        Check(Math.Abs(pose.pose.pose.position.x - 1.5) < 1e-9 && Math.Abs(yaw - 0.7) < 1e-6 && pose.pose.covariance.Length == 36, "Pose");
        Console.WriteLine("mock -> Unity: String, OccupancyGrid, CompressedImage, PoseWithCovarianceStamped OK");

        // Unity -> mock: serialize what the app publishes, exactly as TopicMessageSender does.
        void Save(string name, Message msg) { var s = new MessageSerializer(); s.SerializeMessage(msg); File.WriteAllBytes(Path.Combine(Dir, name), s.GetBytes()); }
        Save("u_twist.bin", new TwistMsg(new Vector3Msg(0.25, -0.1, 0), new Vector3Msg(0, 0, 0.8)));
        Save("u_bool.bin", new BoolMsg(true));
        Save("u_string.bin", new StringMsg("capture"));
        Save("u_audio.bin", new UInt8MultiArrayMsg(new MultiArrayLayoutMsg(), new byte[] { 82, 73, 70, 70, 1, 2, 3 }));
        Console.WriteLine("wrote u_*.bin");
        return 0;
    }
}
