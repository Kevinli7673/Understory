FROM fetch-ros
RUN apt-get update && apt-get install -y \
    ros-jazzy-slam-toolbox ros-jazzy-twist-mux ros-jazzy-teleop-twist-keyboard \
    ros-jazzy-foxglove-bridge ros-jazzy-nav2-map-server \
    python3-serial v4l-utils tmux git \
    && rm -rf /var/lib/apt/lists/*
# Nav2 pieces used by understory_nav (nav.launch.py). Separate layer so the one above stays cached.
RUN apt-get update && apt-get install -y \
    ros-jazzy-nav2-controller ros-jazzy-nav2-planner ros-jazzy-nav2-behaviors \
    ros-jazzy-nav2-bt-navigator ros-jazzy-nav2-lifecycle-manager \
    ros-jazzy-nav2-navfn-planner ros-jazzy-nav2-dwb-controller \
    && rm -rf /var/lib/apt/lists/*
