import os
import sys

# Let `pytest ros2_ws/src/understory_nav/test` work from anywhere without colcon.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
