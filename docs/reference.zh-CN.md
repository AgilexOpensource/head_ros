# head_ros 参考

[English](reference.md)

`head_node` 的参数、启动参数、指令规则、硬件 YAML、诊断、运行边界和常见问题。入门请先看 [README](../README.zh-CN.md)。

## ROS 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `yaml_path` | 空 | 硬件 YAML；[head_ros.yaml](../config/head_ros.yaml) 设为 `head.yaml` |
| `module_key` | 空 | YAML 顶层模块名；为空时用文件名主干 |
| `can_channel` | 空 | 覆盖 CAN 接口；[head_ros.yaml](../config/head_ros.yaml) 设为 `can0` |
| `auto_configure` | `true` | 启动时配置关节组 |
| `auto_enable` | `true` | 启动时使能电机 |
| `control_enabled` | `true` | 初始指令门控 |
| `control_mode` | `pos` | `pos` 或 `mit`；可在运行时修改 |
| `feedback_rate` | `100.0` | 关节反馈频率，Hz |
| `status_rate` | `30.0` | 诊断频率，Hz |
| `status_timeout` | `2.0` | 诊断新鲜度上限，s |
| `enable_interval` | `0.1` | 逐关节使能或失能帧之间的间隔，s |

- 频率和 `status_timeout` 必须有限且大于 0；`enable_interval` 必须有限且不小于 0。
- 除 `control_mode` 外，所有参数在启动后只读。
- `control_enabled` 保持启动值；`control_enable` 服务修改实际门控。

## 启动参数

`head.launch.py` 为上表中除 `enable_interval` 外的每个参数提供同名启动参数，另有：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `namespace` | `head` | 节点命名空间 |
| `params_file` | `config/head_ros.yaml` | 节点参数文件 |

- 参数类启动参数默认为空，留空则使用 `params_file` 中的值。
- `control_enabled`、`auto_configure` 和 `auto_enable` 取 `true` 或 `false`；`control_mode` 取 `pos` 或 `mit`。

## 指令与反馈

`control/joint_states` 消息的规则：

- `name` 和 `position` 必须非空、长度相同且无重复。可以只发部分关节；未知关节会被跳过。
- 用到的值必须有限；无效消息整条拒绝。单个关节写入失败会记录日志，其他关节继续执行。
- `pos` 模式只用 `position`。`mit` 模式还用 `velocity` 和 `effort`；二者各自为空（按 0 处理）或与 `name` 等长。
- 忽略消息头；不检查时效，也没有应答。
- 只有新鲜的低速反馈（`status_timeout` 内）显示电机已使能时才下发该关节；否则丢弃目标并只告警一次，直到重新使能。

没有 SDK 状态的关节不出现在 `feedback/joint_states` 中。

MIT 控制：先切换模式，再发送位置（rad）、速度（rad/s）和力矩（N·m）。增益来自硬件 YAML。

```bash
ros2 param set /head/head_node control_mode mit
ros2 topic pub --once /head/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['head_joint1'], position: [0.0], velocity: [0.0], effort: [0.0]}"
```

## 硬件 YAML

- 相对的 `yaml_path` 在安装后的 `share/head_ros/config` 下查找。其他文件请用绝对路径；不支持 `package://` URL。
- `yaml_path` 为空时依次使用环境变量 `HEAD_ROS_CONFIG` 和 `head.yaml`。
- `module_key` 为空时用文件名主干，因此 `head.yaml` 对应模块 `head`。
- `can_channel` 会替换模块默认接口，以及所有与之相同的关节接口。

字段含义见 [SDK YAML 参考](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md)。

## 力矩限制

开启 `auto_configure` 时，每个关节的 `torque_limit`（N·m）会设为驱动器电流限制：

```text
current_a = torque_limit / (torque_k * torque_b)
```

这是通过标定系数换算的电流限制，不保证实测力矩。未设置 `torque_limit` 的关节保持驱动器原有设置。

## 诊断

`feedback/motor_status` 每次发布一个 `DiagnosticArray`，每个关节一条 `DiagnosticStatus`。`name` 为关节名，`hardware_id` 为 `<can_channel>:<node_id>`，所有值均为字符串。

| 键 | 说明 |
|---|---|
| `enabled` | 硬件使能位 |
| `undervoltage`, `motor_overtemp`, `driver_overcurrent`, `driver_overtemp` | 故障位 |
| `collision_tripped`, `driver_error`, `stall_tripped` | 保护和错误位 |
| `bus_voltage_v`, `bus_current` | 母线电压（V）和母线电流 |
| `driver_temp_deg`, `motor_temp_deg` | 温度，°C |
| `status_raw` | 固件原始状态字节，十进制 |
| `control_mode` | 软件控制模式 |

- 任一故障或保护位置位时为 `ERROR`，消息中列出这些位。
- 新鲜且无故障时为 `OK`，消息为 `enabled` 或 `disabled`。
- 时间戳缺失、非正、在未来或已过期时为 `STALE`，值为 `unknown`。新鲜指按主机挂钟时间 `0 <= age <= status_timeout`。

30 Hz 诊断仅重复发布缓存的低速反馈，不会产生新的硬件采样或改变固件 CAN 发送频率。新鲜度仍按源时间戳判断，默认 2 秒超时保持不变。

## 运行边界

- 关闭指令门控不会失能电机，也不会取消已发送的目标。
- 诊断过期不会停止指令，也不会清除缓存的关节反馈。
- 节点退出时关闭 SDK 连接，但不失能电机。
- `enable` 服务返回 SDK 的结果；硬件实际状态请看 `motor_status`。
- 看门狗、轨迹执行和故障恢复应由本驱动的上层负责。

## 常见问题

- `head YAML not found`：传入绝对路径的 `yaml_path`，或安装在 `share/head_ros/config` 下的文件名。
- `head configure failed` 或 `head enable failed`：检查供电、接线和节点 ID，再运行[连接检查](../README.zh-CN.md#快速开始)。
- 日志显示 `control/joint_states ignored`：按[指令与反馈](#指令与反馈)中的规则修正消息。
- `motor_status` 条目为 `STALE`：`status_timeout` 内没有新的反馈；检查供电和 CAN。
