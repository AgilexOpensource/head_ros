# head_ros

[English](README.md)

2 自由度头部（arm 协议）的 ROS 2 驱动，支持位置控制和 MIT 控制，基于 [agx_motor_sdk](https://github.com/kehuanjack/agx_motor_sdk)。

> **Safety:** 默认启动会配置并使能电机，并接受控制指令。启动前请检查接线、节点 ID、标定、限位和机械空间，并准备独立的急停装置。

## 环境要求

已在 Ubuntu 22.04 + ROS 2 Humble 上测试。

## 安装

SDK 安装时会编译 C++ 扩展，需先安装构建工具：

```bash
sudo apt install build-essential cmake libasio-dev libyaml-cpp-dev python3-dev
mkdir -p ~/head_ws/src && cd ~/head_ws
git clone https://github.com/AgilexOpensource/head_ros.git src/head_ros
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
```

用系统 pip 安装 SDK 并构建：

```bash
pip3 install git+https://github.com/kehuanjack/agx_motor_sdk.git
colcon build --packages-select head_ros
source install/setup.bash
```

或者，推荐使用虚拟环境，避免改动系统 Python。该虚拟环境仍可访问 ROS 的 Python 包：

```bash
python3 -m venv --system-site-packages ~/head_ws/.venv
source ~/head_ws/.venv/bin/activate
pip install git+https://github.com/kehuanjack/agx_motor_sdk.git
python3 -m colcon build --packages-select head_ros
source install/setup.bash
```

每个新终端都要先激活虚拟环境，再执行 `source install/setup.bash`。`python3 -m colcon` 让节点使用虚拟环境中的 Python；直接用 `colcon` 会使用系统 Python，无法导入虚拟环境中的 `agx_motor_sdk`。

## 快速开始

以 1 Mbit/s 启用 `can0` 并启动驱动。仅在接口处于关闭状态且未被其他程序使用时执行 `ip link set`。

```bash
sudo ip link set can0 up type can bitrate 1000000
ros2 launch head_ros head.launch.py
```

节点为 `/head/head_node`，关节为 `head_joint1`（俯仰）和 `head_joint2`（偏航）。只检查连接、不配置、不使能、不接受指令：

```bash
ros2 launch head_ros head.launch.py \
  auto_configure:=false auto_enable:=false control_enabled:=false
```

在另一个终端读取反馈并发送位置目标。**指令会让关节运动。**

```bash
ros2 topic echo /head/feedback/joint_states
ros2 topic echo /head/feedback/motor_status
ros2 topic pub --once /head/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['head_joint1'], position: [0.0]}"
```

MIT 控制：先切换模式，再发送位置（rad）、速度（rad/s）和力矩（N·m）。增益来自硬件 YAML。

```bash
ros2 param set /head/head_node control_mode mit
ros2 topic pub --once /head/control/joint_states sensor_msgs/msg/JointState \
  "{name: ['head_joint1'], position: [0.0], velocity: [0.0], effort: [0.0]}"
```

关闭指令门控，再失能电机：

```bash
ros2 service call /head/control_enable std_srvs/srv/SetBool '{data: false}'
ros2 service call /head/enable std_srvs/srv/SetBool '{data: false}'
```

## 接口

名称相对于节点命名空间（默认 `/head`）。话题使用 reliable、volatile QoS，深度 10。

| 名称 | 类别 | 类型 | 说明 |
|---|---|---|---|
| `control/joint_states` | 订阅话题 | `sensor_msgs/msg/JointState` | 关节目标 |
| `feedback/joint_states` | 发布话题 | `sensor_msgs/msg/JointState` | 按 `feedback_rate` 发布的关节反馈 |
| `feedback/motor_status` | 发布话题 | `diagnostic_msgs/msg/DiagnosticArray` | 按 `status_rate` 发布，每关节一条状态 |
| `enable` | 服务 | `std_srvs/srv/SetBool` | 使能或失能电机 |
| `control_enable` | 服务 | `std_srvs/srv/SetBool` | 打开或关闭指令门控 |

指令规则：

- `name` 和 `position` 必须非空、长度相同且无重复。可以只发部分关节；未知关节会被跳过。
- 用到的值必须有限；无效消息整条拒绝。单个关节写入失败会记录日志，其他关节继续执行。
- `pos` 模式只用 `position`。`mit` 模式还用 `velocity` 和 `effort`；二者各自为空（按 0 处理）或与 `name` 等长。
- 忽略消息头；不检查时效，也没有应答。

没有 SDK 状态的关节不出现在 `feedback/joint_states` 中。`motor_status` 字段见 [docs/reference.zh-CN.md](docs/reference.zh-CN.md#诊断)。

## 配置

- [config/head.yaml](config/head.yaml)：硬件模块 `head`，包含 `head_joint1`（ID 6）和 `head_joint2`（ID 7）、极性、限位、运动曲线、MIT 增益和 `torque_limit`。字段见 [SDK YAML 参考](https://github.com/kehuanjack/agx_motor_sdk/blob/main/YAML_CONFIG.md)。
- [config/head_ros.yaml](config/head_ros.yaml)：节点参数，见 [docs/reference.zh-CN.md](docs/reference.zh-CN.md#ros-参数)。

启动参数（留空则使用 `params_file` 中的值）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `namespace` | `head` | 节点命名空间 |
| `params_file` | `config/head_ros.yaml` | 节点参数文件 |
| `yaml_path` | 空 | 硬件 YAML 路径 |
| `module_key` | 空 | YAML 顶层模块名 |
| `can_channel` | 空 | 覆盖 CAN 接口 |
| `control_mode` | 空 | `pos` 或 `mit` |
| `control_enabled` | 空 | 初始指令门控，`true` 或 `false` |
| `auto_configure`, `auto_enable` | 空 | 启动时配置和使能，`true` 或 `false` |
| `feedback_rate`, `status_rate` | 空 | 发布频率，Hz |
| `status_timeout` | 空 | 诊断新鲜度上限，s |

`ros2 launch head_ros head.launch.py --show-args` 可列出全部参数。硬件 YAML 查找、力矩限制和运行边界见 [docs/reference.zh-CN.md](docs/reference.zh-CN.md)。

## 常见问题

- `No module named 'agx_motor_sdk'`：激活虚拟环境，并用 `python3 -m colcon build` 重新构建。
- `failed to open CAN: can0`：按[快速开始](#快速开始)启用接口，并用 `ip -brief link show` 检查。
- `head YAML not found`：传入绝对路径的 `yaml_path`，或安装在 `share/head_ros/config` 下的文件名。
- `head configure failed` 或 `head enable failed`：检查供电、接线和节点 ID，再运行连接检查。
- 日志显示 `External control gate is closed`：调用 `control_enable`，参数为 `{data: true}`。
- 日志显示 `control/joint_states ignored`：按指令规则修正消息。
- `motor_status` 条目为 `STALE`：`status_timeout` 内没有新的反馈；检查供电和 CAN。

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。
