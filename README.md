# head_ros

ROS 2 support for the 2-DOF head, reusing `motor_ros`.

See [motor_ros](https://github.com/AgilexOpensource/motor_ros#readme) for
prerequisites, CAN setup, controls, feedback, parameters, and safety precautions.
This page covers head-specific setup only.

## Installation

Follow the motor_ros installation guide, then add this package to that workspace:

```bash
cd ~/motor_ws
git clone https://github.com/AgilexOpensource/head_ros.git src/head_ros
colcon build --packages-up-to head_ros
source install/setup.bash
```

## Launch

```bash
ros2 launch head_ros head.launch.py
```

Use `/head` instead of `/motor` in the motor_ros topic and service examples,
with joint names `head_joint1` and `head_joint2`.

## Head Configuration

- [head.yaml](config/head.yaml): module `head`, pitch `head_joint1` (ID 6),
  yaw `head_joint2` (ID 7), limits, polarity, calibration, and MIT gains.
- [head_ros.yaml](config/head_ros.yaml): head launch defaults, using `can0`.

## License

Apache-2.0; see `LICENSE`.
