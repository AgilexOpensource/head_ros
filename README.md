# head_ros

[中文](README.zh-CN.md)

ROS 2 driver for the 2-DOF head (arm protocol) with position or MIT control, built on [agx_motor_sdk](https://github.com/kehuanjack/agx_motor_sdk).

> **Safety:** Default startup configures and enables the motors and accepts commands. Check wiring, node IDs, calibration, limits and mechanical clearance first, and provide an independent emergency stop.

## Requirements

Tested on Ubuntu 22.04 with ROS 2 Humble.

## Install

The SDK compiles a C++ extension during install, so install the build tools first:

```bash
sudo apt install build-essential cmake libasio-dev libyaml-cpp-dev python3-dev
mkdir -p ~/head_ws/src && cd ~/head_ws
git clone https://github.com/AgilexOpensource/head_ros.git src/head_ros
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
```

Install the SDK with system pip and build:

```bash
pip3 install git+https://github.com/kehuanjack/agx_motor_sdk.git
colcon build --packages-select head_ros
source install/setup.bash
```

Or, recommended to keep the system Python clean, a virtual environment that still sees the ROS Python packages:

```bash
python3 -m venv --system-site-packages ~/head_ws/.venv
source ~/head_ws/.venv/bin/activate
pip install git+https://github.com/kehuanjack/agx_motor_sdk.git
python3 -m colcon build --packages-select head_ros
source install/setup.bash
```

Activate the venv in every new terminal before `source install/setup.bash`. `python3 -m colcon` makes the node use the venv Python; plain `colcon` would use the system Python, which cannot import `agx_motor_sdk` from the venv.

## Quick start

Bring up `can0` at 1 Mbit/s and start the driver. Run `ip link set` only while the interface is down and not used by another program.

```bash
sudo ip link set can0 up type can bitrate 1000000
ros2 launch head_ros head.launch.py
```

The node is `/head/head_node` with joints `head_joint1` (pitch) and `head_joint2` (yaw). To check the connection without configuring, enabling or accepting commands:

```bash
ros2 launch head_ros head.launch.py \
  auto_configure:=false auto_enable:=false control_enabled:=false
```

In another terminal, read feedback and send a position target. **Commands move the joints.**

```bash
ros2 topic echo /head/feedback/joint_states
ros2 topic echo /head/feedback/motor_status
ros2 topic pub --once /head/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['head_joint1'], position: [0.0]}"
```

For MIT control, switch the mode, then send position (rad), velocity (rad/s) and effort (N·m). Gains come from the hardware YAML.

```bash
ros2 param set /head/head_node control_mode mit
ros2 topic pub --once /head/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['head_joint1'], position: [0.0], velocity: [0.0], effort: [0.0]}"
```

Close the command gate, then disable the motors:

```bash
ros2 service call /head/control_enable std_srvs/srv/SetBool '{data: false}'
ros2 service call /head/enable std_srvs/srv/SetBool '{data: false}'
```

## Interfaces

Names are relative to the node namespace (default `/head`). Topics use reliable, volatile QoS with depth 10.

| Name | Kind | Type | Description |
|---|---|---|---|
| `control/joint_states` | Subscribed topic | `sensor_msgs/msg/JointState` | Joint targets |
| `feedback/joint_states` | Published topic | `sensor_msgs/msg/JointState` | Joint feedback at `feedback_rate` |
| `feedback/motor_status` | Published topic | `diagnostic_msgs/msg/DiagnosticArray` | One status per joint at `status_rate` |
| `enable` | Service | `std_srvs/srv/SetBool` | Enable or disable the motors |
| `control_enable` | Service | `std_srvs/srv/SetBool` | Open or close the command gate |

Command rules:

- `name` and `position` must be nonempty, the same length and free of duplicates. Subsets are allowed; unknown joints are skipped.
- Used values must be finite; an invalid message is rejected as a whole. A failed write is logged and other joints continue.
- `pos` mode uses `position` only. `mit` mode also uses `velocity` and `effort`; each must be empty (zeros) or match the `name` length.
- Headers are ignored; there is no age check or acknowledgment.

Joints without SDK state are left out of `feedback/joint_states`. The `motor_status` fields are listed in [docs/reference.md](docs/reference.md#diagnostics).

## Configuration

- [config/head.yaml](config/head.yaml): hardware module `head` with `head_joint1` (ID 6) and `head_joint2` (ID 7), polarity, limits, profile, MIT gains and `torque_limit`. See the [SDK YAML reference](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md).
- [config/head_ros.yaml](config/head_ros.yaml): node parameters, listed in [docs/reference.md](docs/reference.md#ros-parameters).

Launch arguments (empty keeps the value from `params_file`):

| Argument | Default | Description |
|---|---|---|
| `namespace` | `head` | Node namespace |
| `params_file` | `config/head_ros.yaml` | Node parameter file |
| `yaml_path` | empty | Hardware YAML path |
| `module_key` | empty | Top-level YAML module |
| `can_channel` | empty | CAN interface override |
| `control_mode` | empty | `pos` or `mit` |
| `control_enabled` | empty | Initial command gate, `true` or `false` |
| `auto_configure`, `auto_enable` | empty | Configure and enable at startup, `true` or `false` |
| `feedback_rate`, `status_rate` | empty | Publish rates, Hz |
| `status_timeout` | empty | Diagnostics freshness bound, s |

`ros2 launch head_ros head.launch.py --show-args` lists them. Hardware YAML lookup, the torque limit and operating boundaries are in [docs/reference.md](docs/reference.md).

## Troubleshooting

- `GitHub release metadata request failed` while installing `agx_motor_sdk`: the SDK downloads protocol libraries from GitHub, and anonymous access allows 60 API requests per hour per IP. Wait for the limit to reset, or set `GITHUB_TOKEN` to a GitHub token and install again.
- `No module named 'agx_motor_sdk'`: activate the venv and rebuild with `python3 -m colcon build`.
- `failed to open CAN: can0`: bring the interface up as in [Quick start](#quick-start) and check `ip -brief link show`.
- `head YAML not found`: pass an absolute `yaml_path`, or a file name installed under `share/head_ros/config`.
- `head configure failed` or `head enable failed`: check power, wiring and node IDs, then run the connection check.
- Log says `External control gate is closed`: call `control_enable` with `{data: true}`.
- Log says `control/joint_states ignored`: fix the message as described in the command rules.
- `motor_status` entries are `STALE`: no fresh feedback within `status_timeout`; check power and CAN.

## License

Apache-2.0, see [LICENSE](LICENSE).
