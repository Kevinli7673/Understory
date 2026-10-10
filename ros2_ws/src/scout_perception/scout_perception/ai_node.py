"""ai_node: detector_node and species_node in one process, for a GPU with little memory.

    ros2 run scout_perception ai_node --ros-args -p detector_node:backend:=owlvit_torch \
        -p detector_node:score_threshold:=0.05 -p species_node:backend:=bioclip

Each process that uses the GPU loads its own copy of the CUDA libraries (over 1 GB). Run this way the
two models share one copy, and they take turns on the GPU instead of peaking together. Topics and
parameters are the same as the separate nodes; give each parameter its node's name as above.
"""
import rclpy
from rclpy.executors import SingleThreadedExecutor

from scout_perception.detector_node import DetectorNode
from scout_perception.species_node import SpeciesNode


def main():
    rclpy.init()
    executor = SingleThreadedExecutor()
    executor.add_node(DetectorNode())
    executor.add_node(SpeciesNode())
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
