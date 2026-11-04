# head_ros

ROS 2 driver for the 2-DOF head (arm protocol) with position or MIT control.

> **Safety:** Default startup configures and enables the motors and accepts
> commands. Check wiring, node IDs, calibration, limits and mechanical clearance
> first, and provide an independent emergency stop.

## Installation

Use a terminal with your ROS 2 environment active, colcon, and Python pip.

```bash
python3 -m pip install git+https://github.com/kehuanjack/agx_motor_sdk.git
mkdir -p ~/head_ws/src
cd ~/head_ws
git clone https://github.com/AgilexOpensource/head_ros.git src/head_ros
colcon build --packages-select head_ros
source install/setup.bash
```

## Launch

The default configuration uses `can0` at 1 Mbit/s. Activate it with the
interface down; do not reconfigure an adapter in use.

```bash
sudo ip link set can0 up type can bitrate 1000000
ros2 launch head_ros head.launch.py
```

The node is `/head/head_node` with joints `head_joint1` (pitch) and `head_joint2` (yaw). For a connection check
without configure, enable or external commands:

```bash
ros2 launch head_ros head.launch.py \
  auto_configure:=false auto_enable:=false control_enabled:=false
```

## Control and Feedback

Run commands in another terminal with ROS 2 and the workspace loaded.
**Commands can move the joints.** The examples command `head_joint1` to 0.

```bash
ros2 topic echo /head/feedback/joint_states
ros2 topic echo /head/feedback/motor_status
ros2 topic pub --once /head/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['head_joint1'], position: [0.0]}"
```

MIT control: switch the mode, then send position (rad), velocity (rad/s) and
effort (N*m). MIT gains and torque calibration come from the head YAML.

```bash
ros2 param set /head/head_node control_mode mit
ros2 topic pub --once /head/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['head_joint1'], position: [0.0], velocity: [0.0], effort: [0.0]}"
```

`enable` switches motor enable; `control_enable` opens or closes the software
command gate:

```bash
ros2 service call /head/enable std_srvs/srv/SetBool '{data: true}'
ros2 service call /head/control_enable std_srvs/srv/SetBool '{data: true}'
ros2 service call /head/control_enable std_srvs/srv/SetBool '{data: false}'
ros2 service call /head/enable std_srvs/srv/SetBool '{data: false}'
```

Names below are relative to the namespace (default `/head`). Topics use
reliable, volatile QoS with depth 10.

| Direction | Name | Type |
|---|---|---|
| Subscribe | `control/joint_states` | `sensor_msgs/JointState` |
| Publish | `feedback/joint_states` | `sensor_msgs/JointState` |
| Publish | `feedback/motor_status` | `diagnostic_msgs/DiagnosticArray` |
| Service | `enable` | `std_srvs/SetBool` |
| Service | `control_enable` | `std_srvs/SetBool` |

Command rules:

- `name` and `position` must be nonempty, equal length, with no duplicate names.
  Subsets are allowed; unknown joints are skipped.
- `pos` ignores velocity/effort. `mit` uses velocity (rad/s) and effort (N*m);
  each array must be empty (zeros) or match `name` length.
- Used values must be finite; an invalid packet is rejected before sending.
  Writes are per joint; a failed write is logged and other joints continue.
- Command headers are ignored; there is no age check or acknowledgment.

Joint feedback is published from cached SDK snapshots at `feedback_rate`.
Missing joints are omitted.

## Configuration

- [head.yaml](config/head.yaml): module `head`, pitch `head_joint1` (ID 6),
  yaw `head_joint2` (ID 7), limits, polarity, calibration, MIT gains and
  `torque_limit`.
- [head_ros.yaml](config/head_ros.yaml): startup parameters.

### Hardware YAML

Relative `yaml_path` values resolve under the installed `share/head_ros/config`;
use absolute paths for external files (`package://` is not supported). An empty
`yaml_path` checks `HEAD_ROS_CONFIG`, then `head.yaml`. The module key defaults to the file stem (`head`). See the
[SDK YAML reference](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md).

With `auto_configure`, each joint's `torque_limit` (N*m) becomes a driver
current limit: `current_a = torque_limit / (torque_k * torque_b)`. This is a
calibrated current limit, not a measured-torque guarantee.

### ROS parameters

| Parameter | Node default | Meaning |
|---|---|---|
| `yaml_path` | empty | Hardware YAML; `head_ros.yaml` sets `head.yaml` |
| `module_key` | empty | Top-level YAML module; inferred from the file stem when empty |
| `can_channel` | empty | Override the YAML CAN interface |
| `auto_configure` | `true` | Configure the joint group at startup |
| `auto_enable` | `true` | Enable motors at startup |
| `control_enabled` | `true` | Initial software command gate |
| `control_mode` | `pos` | `pos` or `mit`; changeable at runtime |
| `feedback_rate` | `100.0` | Joint feedback rate, Hz |
| `status_rate` | `2.0` | Diagnostics rate, Hz |
| `status_timeout` | `2.0` | Low-speed feedback freshness bound, s |
| `enable_interval` | `0.1` | Delay between per-joint enable/disable frames, s (`>= 0`) |

Rates and timeout must be finite and positive. All parameters except `control_mode` are read-only after startup.
The gate parameter keeps its startup value; `control_enable` changes the live gate.
Launch accepts these overrides plus `namespace` and `params_file`; empty values
keep the parameter file. List them with
`ros2 launch head_ros head.launch.py --show-args`.

### Diagnostics

`/head/feedback/motor_status` is one `DiagnosticArray` per publish with one
`DiagnosticStatus` per joint: `name` is the joint name and `hardware_id` is
`<can_channel>:<node_id>`. Values are strings.

Arm-protocol joints publish:

| Fields | Meaning |
|---|---|
| `enabled` | Hardware enable bit: `true`, `false`, `unknown` |
| `undervoltage`, `motor_overtemp`, `driver_overcurrent`, `driver_overtemp` | Fault bits |
| `collision_tripped`, `driver_error`, `stall_tripped` | Protection/error bits |
| `bus_voltage_v`, `bus_current` | Bus voltage (V), bus current |
| `driver_temp_deg`, `motor_temp_deg` | Temperatures (degrees C) |
| `status_raw` | Raw firmware status byte, decimal |
| `control_mode` | Software control mode |

Any fault bit gives `ERROR`.

Fresh, fault-free status is `OK`, even when disabled. Missing, nonpositive,
future or expired timestamps give `STALE` with values `unknown`. Freshness is
`0 <= age <= status_timeout` on host wall-clock time.

### Operating boundaries

- Closing the command gate does not disable motors or cancel sent targets.
- Stale diagnostics do not stop commands or expire cached joint feedback.
- Node exit closes the SDK connection without explicitly disabling motors.
- The enable service reports the SDK result; check diagnostics for hardware state.
- Provide watchdogs, trajectory execution and recovery upstream.

## License

Apache-2.0; see `LICENSE`.
