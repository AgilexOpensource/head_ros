# head_ros 参考

[English](reference.md)

`head_node` 的参数、硬件 YAML、诊断和运行边界。入门请先看 [README](../README.zh-CN.md)。

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
| `status_rate` | `2.0` | 诊断频率，Hz |
| `status_timeout` | `2.0` | 诊断新鲜度上限，s |
| `enable_interval` | `0.1` | 逐关节使能或失能帧之间的间隔，s |

- 频率和 `status_timeout` 必须有限且大于 0；`enable_interval` 必须有限且不小于 0。
- 除 `control_mode` 外，所有参数在启动后只读。
- `control_enabled` 保持启动值；`control_enable` 服务修改实际门控。
- `enable_interval` 没有对应的启动参数，请在参数文件中设置。

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

## 运行边界

- 关闭指令门控不会失能电机，也不会取消已发送的目标。
- 诊断过期不会停止指令，也不会清除缓存的关节反馈。
- 节点退出时关闭 SDK 连接，但不失能电机。
- `enable` 服务返回 SDK 的结果；硬件实际状态请看 `motor_status`。
- 看门狗、轨迹执行和故障恢复应由本驱动的上层负责。
