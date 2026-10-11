Inspiration

Central Florida's conservation land is being overrun by invasive plants such as Brazilian pepper, air potato, and cogongrass. Crews remove them by hand, but checking whether a removal worked means scouting the land, often through thick brush, heat, and mud where most of that land is never re-surveyed.

Our goal was to build a robot that can drive through a habitat, map it, identify the plants with on-device AI, and turn the survey into a place you can walk through in VR. Understory is named after the layer of a forest below the canopy, where these plants spread and where people rarely look.

What it does

Maps the area as it drives: a 2D lidar builds a floor plan live with SLAM, and the robot plans its own survey points on that map.
Captures 360° "bubbles": at each survey point the robot spins in place, stopping every 30° to take 12 photos, each tagged with its heading.
Finds and names plants: an open-vocabulary detector finds plant-like things in the camera feed, and a biology model names the species and flags it as invasive or native.
Pins each plant on the map: the plant's position in the image and the lidar range in that direction place it on the floor plan, with a cropped photo saved for each pin.
Lets you walk through the survey in VR: a Meta Quest app shows a tabletop miniature of the map with the robot, bubbles, and pins on it. Pick a bubble and you are standing inside it, with the plants marked around you.
Compares before and after: survey once, remove the invasives, survey again, and the app shows which plants are gone and which are still there ("7 invasive → 1 remaining").
Takes voice commands: hold a button on the Quest controller and say "start survey", "take a picture", or "come back home". Speech is transcribed on the robot's own network.
Can be driven by hand: the Quest thumbsticks drive and strafe the robot, and one button is an emergency stop that overrides everything else.
Shows the survey on a web dashboard: a live lidar view of the robot and the saved map with its pins, open to any laptop on the robot's network.
Logs every mission to a folder (bubbles, pins, photos, map) that the dashboard and the cloud steps read.
Works with no internet: every model in the live demo runs on our own hardware.

How we built it

Compute: Raspberry Pi 5 on the robot for the lidar, camera, mapping, and navigation; NVIDIA Jetson Orin Nano at the table for the AI and the dashboard; an ESP32 for motor control
Sensing: Slamtec RPLIDAR C1 and a Logitech Brio 101 camera
Motion: mecanum chassis powered by 6× AA cells (7.2 V)
Perception: OWL-ViT for detection, BioCLIP for species ID, Whisper for speech, and OpenCV for panorama stitching, all through PyTorch and Hugging Face Transformers
Acceleration: NanoOWL with TensorRT on the Jetson for detection
Robotics: ROS 2 Jazzy in Docker with slam_toolbox, Nav2, twist_mux, and our own mission manager and survey planner
VR: Unity 6 with the Meta XR SDK and OpenXR on a Meta Quest, talking to ROS through ROS-TCP-Connector
Dashboard: Streamlit, with a WebSocket relay for the live lidar and headset view
Data: mission folders handed off through a private Hugging Face dataset
3D reconstruction: MASt3R and gsplat on an AMD Radeon PRO W7900, with Depth Anything V2 as a fallback
Tooling: Foxglove for debugging; pytest for the geometry, voice, and mission logic

Technical details

Two-stage plant ID. OWL-ViT only answers "is this a plant?" using general prompts like "a plant" or "a leaf". Each box is then cropped from the exact frame it came from and passed to BioCLIP, which picks from a fixed list of five species by scientific name. The list also contains things that are not plants (a wall, a hand, a laptop). If one of those wins, the crop is dropped instead of being forced into a species.

Rejecting things that are not our plants. The species list also holds 20 other living things by scientific name (people, pets, house plants). If one of those wins, the crop is dropped.

TensorRT on the Jetson. The detector runs as a TensorRT engine: 19 ms per frame against 62 ms in PyTorch, which keeps up with the camera at 15 frames a second.

Putting a plant on the map. The box's horizontal position becomes an angle using the camera's field of view. Added to the robot's heading, that gives a direction in the map. The lidar range in that direction gives the distance. Sightings of the same species within 0.5 m merge into one pin, and a pin is only published after 3 sightings.

360° bubbles. The mission manager rotates the robot in 30° steps using the SLAM heading, waits for it to settle, and asks for a frame. The 12 frames are sent to the headset as a ring of curved panels at their recorded headings, so the bubble works even when stitching fails. A stitched panorama follows as an extra when OpenCV can build one.

Who controls the wheels. Three sources can send drive commands, and twist_mux picks one by priority: e-stop, then the Quest thumbsticks, then autonomy. The ESP32 stops the motors if it hears nothing for 300 ms.

Built against fake data first. We agreed on topic names and JSON shapes on Friday night and wrote them down in one file. Every part was then built against a fake mission generator and a mock ROS endpoint, so the Quest app, the navigation, and the perception could each be tested without the robot.

Challenges we ran into

Heat: running both models on the Pi 5 pushed it to 83 °C in five minutes and the firmware throttled the CPU, so the AI moved to the Jetson.
Speed: OWL-ViT takes about 3 seconds per frame on the Pi's CPU, so the detector drops frames it can't keep up with and the species step matches each box back to its original frame by timestamp.
Lookalike plants: in a photo, cogongrass looks like grass and wild coffee looks like leaves. Both scored so low in the detector that we dropped its threshold to 0.05 and relied on BioCLIP to reject the junk.
False positives: a ceiling decoration was confidently named cogongrass until we added the "not a plant" list.
Faces and decorations: the first live pins were a face named Brazilian pepper and an artificial flower garland named air potato. Adding other species by scientific name, not just phrases, fixed it.
Pi power and clock: the Pi lost power and rebooted several times. It has no clock battery and once came back almost six hours slow, which breaks ROS transforms between machines.
USB power: on a power bank the Pi 5 limits its USB ports, so the lidar kept dropping out with over-current errors until we raised the limit in the bootloader.
Hotspot: on 2.4 GHz the phone hotspot could not carry the camera stream between machines. Moving it to 5 GHz took ping from over a second to 5 ms.
Two of everything: more than once, both computers started mapping at the same time, so two mission managers were driving the same wheels until we added a check to the start scripts.
Motor shield: loose I2C wiring made the wheels keep turning after a stop, so the firmware now re-sends stop while idle and recovers the bus.
Humble vs. Jazzy: our navigation code was written for ROS 2 Humble. On Jazzy, slam_toolbox needs lifecycle activation, twist_mux expects a different message type, and Nav2 plugin names changed.
Panoramas with no start angle: OpenCV's stitcher crops its output, so the headset couldn't place pins on it. We switched to always sending the 12 raw frames with their headings.
Boxes off the frame: our detector scaled box heights by the image width, so boxes ran off the bottom of the picture.
Quest build: the first headset build took 13 minutes, and a shader that worked in the editor failed on Android.

Accomplishments that we're proud of

A full chain from camera frame to named, mapped plant, built only from open-source models and running offline
Detection at camera speed (15 frames a second) on an 8 GB Jetson, next to the species model
A VR view where you can stand inside a spot the robot photographed and see what it found there
A before/after comparison that turns two surveys into one number
Two computers, a headset, and a microcontroller sharing one map over a phone hotspot
Four people building in parallel against a shared contract, with a fallback for every fragile part

What we learned

How to split a robot's work across a Pi, a Jetson, and a microcontroller with ROS 2
Chaining a general detector with a specialist classifier, and why a "none of the above" option matters
How much sensor fusion depends on timestamps, clocks, and measured offsets
Building a Unity app against a robot that doesn't exist yet
Thermal and power limits decide where code runs as much as software does

What's next for Understory

An outdoor chassis that can handle real understory terrain
A real before-and-after survey of a habitat, to replace our staged data
A larger species list, including animals
Soil moisture, light, and air quality readings shown as heat maps on the map
Before/after reports and similar-plant search in the dashboard for land managers
Full 3D Gaussian splat reconstructions of each survey site
GPS so surveys line up across weeks and seasons

Built With

adafruit
android
arduino
c#
docker
esp32
hugging-face
jetson
jetson-nano
lidar
metaquest
nav2
opencv
openxr
python
pytorch
raspberry-pi
ros2
slam
streamlit
tensorrt
unity
vr
whisper
