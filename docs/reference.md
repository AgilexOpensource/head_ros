# head_ros reference

[中文](reference.zh-CN.md)

Parameters, launch arguments, command rules, hardware YAML, diagnostics, operating boundaries and troubleshooting of `head_node`. Start with the [README](../README.md).

## ROS parameters

| Parameter | Default | Description |
|---|---|---|
| `yaml_path` | empty | Hardware YAML; [head_ros.yaml](../config/head_ros.yaml) sets `head.yaml` |
| `module_key` | empty | Top-level YAML module; empty uses the file stem |
| `can_channel` | empty | CAN interface override; [head_ros.yaml](../config/head_ros.yaml) sets `can0` |
| `auto_configure` | `true` | Configure the joint group at startup |
| `auto_enable` | `true` | Enable the motors at startup |
| `control_enabled` | `true` | Initial command gate |
| `control_mode` | `pos` | `pos` or `mit`; can be changed at runtime |
| `feedback_rate` | `100.0` | Joint feedback rate, Hz |
| `status_rate` | `30.0` | Diagnostics rate, Hz |
| `status_timeout` | `2.0` | Diagnostics freshness bound, s |
| `enable_interval` | `0.1` | Delay between per-joint enable or disable frames, s |

- Rates and `status_timeout` must be finite and greater than 0; `enable_interval` must be finite and at least 0.
- All parameters except `control_mode` are read-only after startup.
- `control_enabled` keeps its startup value; the `control_enable` service changes the live gate.

## Launch arguments

`head.launch.py` takes each parameter above except `enable_interval` as a launch argument of the same name, plus:

| Argument | Default | Description |
|---|---|---|
| `namespace` | `head` | Node namespace |
| `params_file` | `config/head_ros.yaml` | Node parameter file |

- Parameter arguments default to empty, which keeps the value from `params_file`.
- `control_enabled`, `auto_configure` and `auto_enable` take `true` or `false`; `control_mode` takes `pos` or `mit`.

## Commands and feedback

Rules for messages on `control/joint_states`:

- `name` and `position` must be nonempty, the same length and free of duplicates. Subsets are allowed; unknown joints are skipped.
- Used values must be finite; an invalid message is rejected as a whole. A failed write is logged and other joints continue.
- `pos` mode uses `position` only. `mit` mode also uses `velocity` and `effort`; each must be empty (zeros) or match the `name` length.
- Headers are ignored; there is no age check or acknowledgment.

Joints without SDK state are left out of `feedback/joint_states`.

For MIT control, switch the mode, then send position (rad), velocity (rad/s) and effort (N·m). Gains come from the hardware YAML.

```bash
ros2 param set /head/head_node control_mode mit
ros2 topic pub --once /head/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['head_joint1'], position: [0.0], velocity: [0.0], effort: [0.0]}"
```

## Hardware YAML

- A relative `yaml_path` is looked up under the installed `share/head_ros/config`. Use an absolute path for other files; `package://` URLs are not supported.
- An empty `yaml_path` uses the `HEAD_ROS_CONFIG` environment variable, then `head.yaml`.
- An empty `module_key` uses the file stem, so `head.yaml` maps to module `head`.
- `can_channel` replaces the module default and every joint channel equal to it.

Field meanings are in the [SDK YAML reference](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md).

## Torque limit

With `auto_configure`, each joint's `torque_limit` (N·m) is set as a driver current limit:

```text
current_a = torque_limit / (torque_k * torque_b)
```

This limits current through a calibrated factor and does not guarantee measured torque. Joints without `torque_limit` keep the driver setting.

## Diagnostics

`feedback/motor_status` publishes one `DiagnosticArray` with one `DiagnosticStatus` per joint. `name` is the joint name, `hardware_id` is `<can_channel>:<node_id>` and all values are strings.

| Key | Description |
|---|---|
| `enabled` | Hardware enable bit |
| `undervoltage`, `motor_overtemp`, `driver_overcurrent`, `driver_overtemp` | Fault bits |
| `collision_tripped`, `driver_error`, `stall_tripped` | Protection and error bits |
| `bus_voltage_v`, `bus_current` | Bus voltage (V) and bus current |
| `driver_temp_deg`, `motor_temp_deg` | Temperatures, °C |
| `status_raw` | Raw firmware status byte, decimal |
| `control_mode` | Software control mode |

- Any active fault or protection bit gives `ERROR` and lists the bits in the message.
- Fresh, fault-free status is `OK` with message `enabled` or `disabled`.
- Missing, nonpositive, future or expired timestamps give `STALE` with values `unknown`. Fresh means `0 <= age <= status_timeout` on the host wall clock.

30 Hz diagnostics republish cached low-speed feedback; they do not create new hardware samples or change firmware CAN emission rates. Freshness still uses the source timestamp and the unchanged 2-second default timeout.

## Operating boundaries

- Closing the command gate does not disable the motors or cancel targets already sent.
- Stale diagnostics do not stop commands or clear cached joint feedback.
- Node exit closes the SDK connection without disabling the motors.
- The `enable` service reports the SDK result; read `motor_status` for the hardware state.
- Watchdogs, trajectory execution and fault recovery belong upstream of this driver.

## Troubleshooting

- `head YAML not found`: pass an absolute `yaml_path`, or a file name installed under `share/head_ros/config`.
- `head configure failed` or `head enable failed`: check power, wiring and node IDs, then run the [connection check](../README.md#quick-start).
- Log says `control/joint_states ignored`: fix the message as described in [Commands and feedback](#commands-and-feedback).
- `motor_status` entries are `STALE`: no fresh feedback within `status_timeout`; check power and CAN.
