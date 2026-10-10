## Inspiration
Central Florida's conservation land is being overrun by invasive plants such as Brazilian pepper, air potato, and cogongrass. Crews remove them by hand, but checking whether a removal worked means walking the same ground again and counting, often through thick brush, heat, and mud. Most of that land is never re-surveyed.

Our goal was a robot that can **drive through a habitat, map it, identify the plants with on-device AI, and turn the survey into a place you can walk through in VR**. Understory is named after the layer of a forest below the canopy, where these plants spread and where people rarely look.

For the hackathon, an indoor mecanum robot driving through a staged habitat on the venue floor stands in for the field.

## What it does
- **Maps the area as it drives**: a 2D lidar builds a floor plan live with SLAM, and the robot plans its own survey points on that map.
- **Captures 360° "bubbles"**: at each survey point the robot spins in place, stopping every 30° to take 12 photos, each tagged with its heading.
- **Finds and names plants**: an open-vocabulary detector finds plant-like things in the camera feed, and a biology model names the species and flags it as invasive or native.
- **Pins each plant on the map**: the plant's position in the image and the lidar range in that direction place it on the floor plan, with a cropped photo saved for each pin.
- **Lets you walk through the survey in VR**: a Meta Quest app shows a tabletop miniature of the map with the robot, bubbles, and pins on it. Pick a bubble and you are standing inside it, with the plants marked around you.
- **Compares before and after**: survey once, remove the invasives, survey again, and the app shows which plants are gone and which are still there (_"7 invasive → 1 remaining"_).
- **Takes voice commands**: hold a button on the Quest controller and say _"start survey"_, _"take a picture"_, or _"come back home"_. Speech is transcribed on the robot's own network.
- **Can be driven by hand**: the Quest thumbsticks drive and strafe the robot, and one button is an emergency stop that overrides everything else.
- **Works with no internet**: every model in the live demo runs on our own hardware.

## How we built it
- **Compute**: Raspberry Pi 5 on the robot for the lidar and camera; NVIDIA Jetson Orin Nano at the table for mapping, navigation, and AI; an ESP32 for motor control
- **Sensing**: Slamtec RPLIDAR C1 and a Logitech Brio 101 camera
- **Motion**: mecanum chassis powered by 6× AA cells (7.2 V)
- **Perception**: OWL-ViT for detection, BioCLIP for species ID, Whisper for speech, and OpenCV for panorama stitching, all through PyTorch and Hugging Face Transformers
- **Robotics**: ROS 2 Jazzy in Docker with slam_toolbox, Nav2, twist_mux, and our own mission manager and survey planner
- **VR**: Unity 6 with the Meta XR SDK and OpenXR on a Meta Quest, talking to ROS through ROS-TCP-Connector
- **3D reconstruction**: MASt3R and gsplat on an AMD Radeon PRO W7900, with Depth Anything V2 as a fallback
- **Tooling**: Foxglove for debugging; pytest for the geometry, voice, and mission logic

## Technical details
**Two-stage plant ID.** OWL-ViT only answers "is this a plant?" using general prompts like "a plant" or "a leaf". Each box is then cropped from the exact frame it came from and passed to BioCLIP, which picks from a fixed list of five species by scientific name. The list also contains things that are not plants (a wall, a hand, a laptop). If one of those wins, the crop is dropped instead of being forced into a species.

**Putting a plant on the map.** The box's horizontal position becomes an angle using the camera's field of view. Added to the robot's heading, that gives a direction in the map. The lidar range in that direction gives the distance. Sightings of the same species within 0.5 m merge into one pin, and a pin is only published after 3 sightings.

**360° bubbles.** The mission manager rotates the robot in 30° steps using the SLAM heading, waits for it to settle, and asks for a frame. The 12 frames are sent to the headset as a ring of curved panels at their recorded headings, so the bubble works even when stitching fails. A stitched panorama follows as an extra when OpenCV can build one.

**Who controls the wheels.** Three sources can send drive commands, and twist_mux picks one by priority: e-stop, then the Quest thumbsticks, then autonomy. The ESP32 stops the motors if it hears nothing for 300 ms.

**Built against fake data first.** We agreed on topic names and JSON shapes on Friday night and wrote them down in one file. Every part was then built against a fake mission generator and a mock ROS endpoint, so the Quest app, the navigation, and the perception could each be tested without the robot.

## Challenges we ran into
- **Heat**: running both models on the Pi 5 pushed it to 83 °C in five minutes and the firmware throttled the CPU, so the AI moved to the Jetson.
- **Speed**: OWL-ViT takes about 3 seconds per frame on the Pi's CPU, so the detector drops frames it can't keep up with and the species step matches each box back to its original frame by timestamp.
- **Lookalike plants**: in a photo, cogongrass looks like grass and wild coffee looks like leaves. Both scored so low in the detector that we dropped its threshold to 0.05 and relied on BioCLIP to reject the junk.
- **False positives**: a ceiling decoration was confidently named cogongrass until we added the "not a plant" list.
- **Pi power and clock**: the Pi lost power and rebooted several times. It has no clock battery and once came back almost six hours slow, which breaks ROS transforms between machines.
- **Humble vs. Jazzy**: our navigation code was written for ROS 2 Humble. On Jazzy, slam_toolbox needs lifecycle activation, twist_mux expects a different message type, and Nav2 plugin names changed.
- **Panoramas with no start angle**: OpenCV's stitcher crops its output, so the headset couldn't place pins on it. We switched to always sending the 12 raw frames with their headings.
- **Boxes off the frame**: our detector scaled box heights by the image width, so boxes ran off the bottom of the picture.
- **Quest build**: the first headset build took 13 minutes, and a shader that worked in the editor failed on Android.

## Accomplishments that we're proud of
- A full chain from camera frame to named, mapped plant, built only from open-source models and running offline
- A VR view where you can stand inside a spot the robot photographed and see what it found there
- A before/after comparison that turns two surveys into one number
- Two computers, a headset, and a microcontroller sharing one map over a phone hotspot
- Five people building in parallel against a shared contract, with a fallback for every fragile part

## What we learned
- How to split a robot's work across a Pi, a Jetson, and a microcontroller with ROS 2
- Chaining a general detector with a specialist classifier, and why a "none of the above" option matters
- How much sensor fusion depends on timestamps, clocks, and measured offsets
- Building a Unity app against a robot that doesn't exist yet
- Thermal and power limits decide where code runs as much as software does

## What's next for Understory
- An outdoor chassis that can handle real understory terrain
- TensorRT-optimized detection (NanoOWL) for real-time speed on the Jetson
- A larger species list, including animals
- Soil moisture, light, and air quality readings shown as heat maps on the map
- A cloud dashboard with before/after reports and similar-plant search for land managers
- Full 3D Gaussian splat reconstructions of each survey site
- GPS so surveys line up across weeks and seasons

## Built With
android, bioclip, c#, docker, esp32, foxglove, gsplat, huggingface, jetson, lidar, meta-quest, nav2, opencv, openxr, owl-vit, python, pytorch, raspberry-pi, ros2, slam, transformers, unity, whisper
