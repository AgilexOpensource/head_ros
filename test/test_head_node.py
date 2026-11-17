import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


class DiagnosticArray:
    def __init__(self):
        self.header = SimpleNamespace(stamp=None)
        self.status = []


class DiagnosticStatus:
    OK = 0
    ERROR = 2
    STALE = 3


@pytest.fixture
def head_node(monkeypatch):
    class StubNode:
        parameter_overrides = {}

        def __init__(self, name):
            self.parameters = {}
            self.descriptors = {}
            self.timers = []

        def declare_parameter(self, name, default, descriptor=None):
            self.parameters[name] = self.parameter_overrides.get(name, default)
            self.descriptors[name] = descriptor

        def get_parameter(self, name):
            return SimpleNamespace(value=self.parameters[name])

        def create_publisher(self, *args):
            return SimpleNamespace(publish=lambda message: None)

        def create_subscription(self, *args):
            return SimpleNamespace()

        def create_service(self, *args):
            return SimpleNamespace()

        def add_on_set_parameters_callback(self, callback):
            self.parameter_callback = callback

        def create_timer(self, period, callback):
            self.timers.append((period, callback))
            return SimpleNamespace()

        def get_logger(self):
            return SimpleNamespace(info=lambda message: None, warn=lambda message: None)

    module_attributes = {
        "rclpy": {},
        "rclpy.node": {"Node": StubNode},
        "ament_index_python": {},
        "ament_index_python.packages": {
            "get_package_share_directory": lambda name: "unused"
        },
        "diagnostic_msgs": {},
        "diagnostic_msgs.msg": {
            "DiagnosticArray": DiagnosticArray,
            "DiagnosticStatus": DiagnosticStatus,
            "KeyValue": SimpleNamespace,
        },
        "rcl_interfaces": {},
        "rcl_interfaces.msg": {
            "SetParametersResult": SimpleNamespace,
            "ParameterDescriptor": SimpleNamespace,
        },
        "sensor_msgs": {},
        "sensor_msgs.msg": {"JointState": SimpleNamespace},
        "std_srvs": {},
        "std_srvs.srv": {
            "SetBool": SimpleNamespace(Request=object, Response=object)
        },
        "agx_motor_sdk": {},
        "agx_motor_sdk.mechanism": {
            "JointGroup": SimpleNamespace(INVALID_JOINT_INDEX=-1)
        },
    }
    for name, attributes in module_attributes.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).parents[1] / "head_ros" / "head_node.py"
    spec = importlib.util.spec_from_file_location("motor_status_test_node", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "time_ns", lambda: 10_000_000_000)
    return module


def make_feedback(enabled, timestamp_ns):
    return SimpleNamespace(
        status=SimpleNamespace(
            enabled=enabled, undervoltage=False, motor_overtemp=False,
            driver_overcurrent=False, driver_overtemp=False, collision_tripped=False,
            driver_error=False, stall_tripped=False,
        ),
        timestamp_ns=timestamp_ns, bus_voltage_v=48.0, driver_temp_deg=35,
        motor_temp_deg=40, bus_current=1.2, status_raw=64 if enabled else 0,
    )


def publish_status(module, feedbacks):
    motors = [
        SimpleNamespace(
            can_channel="can%d" % index,
            node_id=index + 1,
            get_low_speed_feedback=(
                feedback if callable(feedback) else (lambda feedback=feedback: feedback)
            ),
        )
        for index, feedback in enumerate(feedbacks)
    ]
    published = []
    node = module.HeadRosNode.__new__(module.HeadRosNode)
    node._group = SimpleNamespace(joint_count=len(motors), motor=motors.__getitem__)
    node._joint_names = ["joint%d" % (index + 1) for index in range(len(motors))]
    node._status_timeout = 2.0
    node._control_mode = "pos"
    node._status_pub = SimpleNamespace(publish=published.append)
    node.get_clock = lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(to_msg=lambda: "ros_stamp")
    )
    node._publish_status()
    assert len(published) == 1
    assert published[0].header.stamp == "ros_stamp"
    return published[0].status


def test_all_motors_included_with_actual_enable_state(head_node):
    statuses = publish_status(
        head_node,
        [make_feedback(True, 9_000_000_000), make_feedback(False, 9_000_000_000), None],
    )
    assert [status.name for status in statuses] == ["joint1", "joint2", "joint3"]
    assert [status.hardware_id for status in statuses] == ["can0:1", "can1:2", "can2:3"]
    assert [status.level for status in statuses] == [0, 0, 3]
    assert [status.values[0].key for status in statuses] == ["enabled"] * 3
    assert [status.values[0].value for status in statuses] == ["true", "false", "unknown"]
    assert [status.message for status in statuses[:2]] == ["enabled", "disabled"]


@pytest.mark.parametrize("timestamp_ns", [0, -1, 7_999_999_999, 10_000_000_001])
def test_expired_or_invalid_feedback_is_unknown(head_node, timestamp_ns):
    status = publish_status(head_node, [make_feedback(True, timestamp_ns)])[0]
    assert status.level == DiagnosticStatus.STALE
    assert status.values[0].value == "unknown"


def test_timeout_boundary_is_valid(head_node):
    status = publish_status(head_node, [make_feedback(False, 8_000_000_000)])[0]
    assert status.level == DiagnosticStatus.OK
    assert status.values[0].value == "false"


def test_frame_cached_during_publish_is_fresh(head_node, monkeypatch):
    clock = [10_000_000_000]
    monkeypatch.setattr(head_node.time, "time_ns", lambda: clock[0])

    def receive_then_read():
        clock[0] += 1_000
        return make_feedback(True, clock[0])

    statuses = publish_status(head_node, [receive_then_read, receive_then_read])
    assert [status.level for status in statuses] == [DiagnosticStatus.OK] * 2


def test_empty_module_still_publishes(head_node):
    assert publish_status(head_node, []) == []


@pytest.mark.parametrize("timestamp_ns", [9_000_000_000, 7_000_000_000, None])
def test_low_speed_fields_and_control_mode_published(head_node, timestamp_ns):
    feedback = None if timestamp_ns is None else make_feedback(True, timestamp_ns)
    status = publish_status(head_node, [feedback])[0]
    values = {entry.key: entry.value for entry in status.values}
    assert set(values) == {
        "enabled", "undervoltage", "motor_overtemp", "driver_overcurrent",
        "driver_overtemp", "collision_tripped", "driver_error", "stall_tripped",
        "bus_voltage_v", "driver_temp_deg", "motor_temp_deg", "bus_current",
        "status_raw", "control_mode",
    }
    assert values["control_mode"] == "pos"
    if timestamp_ns == 9_000_000_000:
        assert values["bus_voltage_v"] == "48.0"
        assert values["driver_temp_deg"] == "35"
        assert values["motor_temp_deg"] == "40"
        assert values["bus_current"] == "1.2"
        assert values["status_raw"] == "64"
    else:
        assert status.level == DiagnosticStatus.STALE
        assert all(value == "unknown" for key, value in values.items() if key != "control_mode")


@pytest.mark.parametrize("fault", [
    "undervoltage", "motor_overtemp", "driver_overcurrent", "driver_overtemp",
    "collision_tripped", "driver_error", "stall_tripped",
])
def test_fresh_hardware_fault_reports_error(head_node, fault):
    feedback = make_feedback(True, 9_000_000_000)
    setattr(feedback.status, fault, True)
    status = publish_status(head_node, [feedback])[0]
    assert status.level == DiagnosticStatus.ERROR
    assert fault in status.message
    assert {entry.key: entry.value for entry in status.values}[fault] == "true"


def test_expired_fault_and_numeric_fields_are_unknown(head_node):
    feedback = make_feedback(True, 7_000_000_000)
    feedback.status.driver_error = True
    status = publish_status(head_node, [feedback])[0]
    values = {entry.key: entry.value for entry in status.values}
    assert status.level == DiagnosticStatus.STALE
    for name in ("enabled", "driver_error", "bus_voltage_v", "motor_temp_deg"):
        assert values[name] == "unknown"


def make_control_node(module, mode="pos", enabled=True, motors_enabled=None):
    """``enabled``: command gate; ``motors_enabled``: joint index -> motor enabled (default all)."""
    commands = []
    warnings = []
    motors_enabled = {0: True, 1: True} if motors_enabled is None else motors_enabled
    node = module.HeadRosNode.__new__(module.HeadRosNode)
    node._control_mode = mode
    node._control_enabled = enabled
    node._control_gate_block_logged = False
    node._disabled_logged = set()
    node._status_timeout = 2.0
    node._joint_by_name = {"joint1": 0, "joint2": 1}

    def motor(index):
        feedback = make_feedback(motors_enabled[index], 9_000_000_000)   # 1 s old at the fixture clock
        return SimpleNamespace(get_low_speed_feedback=lambda: feedback)

    node._group = SimpleNamespace(
        set_target_position=lambda *args: commands.append(("pos", args)) or True,
        set_mit=lambda *args: commands.append(("mit", args)) or True,
        motor=motor,
    )
    node.get_logger = lambda: SimpleNamespace(
        warn=warnings.append, debug=lambda message: None, info=lambda message: None
    )
    return node, commands, warnings


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("mode", ["pos", "mit"])
def test_nonfinite_position_rejects_entire_packet(head_node, invalid, mode):
    node, commands, warnings = make_control_node(head_node, mode)
    node._on_control(SimpleNamespace(
        name=["joint1", "joint2"], position=[0.1, invalid], velocity=[], effort=[]
    ))
    assert commands == []
    assert "non-finite" in warnings[0]


@pytest.mark.parametrize("field", ["velocity", "effort"])
@pytest.mark.parametrize("values", [[0.1], [0.1, float("nan")], [0.1, float("inf")]])
def test_invalid_mit_fields_reject_entire_packet(head_node, field, values):
    node, commands, warnings = make_control_node(head_node, "mit")
    msg = SimpleNamespace(
        name=["joint1", "joint2"], position=[0.1, 0.2], velocity=[], effort=[]
    )
    setattr(msg, field, values)
    node._on_control(msg)
    assert commands == []
    assert warnings


def test_duplicate_joint_names_rejected(head_node):
    node, commands, warnings = make_control_node(head_node)
    node._on_control(SimpleNamespace(
        name=["joint1", "joint1"], position=[0.1, 0.2], velocity=[], effort=[]
    ))
    assert commands == []
    assert "duplicate" in warnings[0]


@pytest.mark.parametrize("mode", ["pos", "mit"])
def test_partial_named_command_and_unknown_joint(head_node, mode):
    node, commands, warnings = make_control_node(head_node, mode)
    node._on_control(SimpleNamespace(
        name=["unknown", "joint2"], position=[0.1, 0.2], velocity=[], effort=[]
    ))
    expected = ("pos", (1, 0.2)) if mode == "pos" else ("mit", (1, 0.2, 0.0, 0.0))
    assert commands == [expected]
    assert warnings == []


def test_mit_velocity_and_torque_forwarded(head_node):
    node, commands, warnings = make_control_node(head_node, "mit")
    node._on_control(SimpleNamespace(
        name=["joint2"], position=[0.2], velocity=[0.3], effort=[0.4]
    ))
    assert commands == [("mit", (1, 0.2, 0.3, 0.4))]
    assert warnings == []


@pytest.mark.parametrize("mode", ["pos", "mit"])
def test_disabled_motor_command_dropped_until_enabled(head_node, mode):
    motors_enabled = {0: False, 1: True}
    node, commands, warnings = make_control_node(head_node, mode, motors_enabled=motors_enabled)
    for position in (0.1, 0.2):
        node._on_control(SimpleNamespace(
            name=["joint1", "joint2"], position=[position, position], velocity=[], effort=[]
        ))
    assert [args[0] for _, args in commands] == [1, 1]
    assert len(warnings) == 1 and "joint1" in warnings[0]   # warned once
    motors_enabled[0] = True
    node._on_control(SimpleNamespace(name=["joint1"], position=[0.3], velocity=[], effort=[]))
    assert commands[-1][1][:2] == (0, 0.3)


def test_stale_feedback_counts_as_disabled(head_node, monkeypatch):
    node, commands, warnings = make_control_node(head_node)
    monkeypatch.setattr(head_node.time, "time_ns", lambda: 11_500_000_000)   # feedback 2.5 s old
    node._on_control(SimpleNamespace(name=["joint1"], position=[0.1], velocity=[], effort=[]))
    assert commands == []


def test_closed_gate_drops_commands(head_node):
    node, commands, warnings = make_control_node(head_node, enabled=False)
    node._on_control(SimpleNamespace(
        name=["joint1"], position=[0.1], velocity=[], effort=[]
    ))
    assert commands == []


def test_mode_update_validates_before_mutating(head_node):
    node, commands, warnings = make_control_node(head_node)
    result = node._on_set_parameters([
        SimpleNamespace(name="control_mode", value="mit"),
        SimpleNamespace(name="control_mode", value="invalid"),
    ])
    assert not result.successful
    assert node._control_mode == "pos"
    result = node._on_set_parameters([SimpleNamespace(name="control_mode", value="mit")])
    assert result.successful
    assert node._control_mode == "mit"


def prepare_startup(module, monkeypatch, overrides=None, fail_at=None):
    calls = []

    def operation(name):
        calls.append(name)
        return name != fail_at

    module.Node.parameter_overrides = overrides or {}
    group = SimpleNamespace(
        joint_names=["joint1"], index_of=lambda name: 0, can_channel="can_test",
        connect=lambda: operation("connect"), configure=lambda: operation("configure"),
        enable=lambda interval=0.0: operation("enable:%s" % interval), close=lambda: operation("close"),
    )
    monkeypatch.setattr(module.JointGroup, "from_yaml", lambda *args: group, raising=False)
    monkeypatch.setattr(module, "resolve_yaml_path", lambda value: Path("head.yaml"))
    monkeypatch.setattr(module, "load_torque_limit_by_joint", lambda *args: {})
    return calls


def test_startup_defaults_timers_and_readonly_contract(head_node, monkeypatch):
    calls = prepare_startup(head_node, monkeypatch)
    node = head_node.HeadRosNode()
    assert calls == ["connect", "configure", "enable:0.1"]
    assert [period for period, callback in node.timers] == [0.01, 1.0 / 30.0]
    for name in (
        "yaml_path", "module_key", "can_channel", "auto_configure", "auto_enable",
        "feedback_rate", "status_rate", "status_timeout", "control_enabled",
        "enable_interval", "feedback_timeout",
    ):
        assert node.descriptors[name].read_only
    assert node.descriptors["control_mode"] is None


@pytest.mark.parametrize("name", ["feedback_rate", "status_rate", "status_timeout"])
@pytest.mark.parametrize("invalid", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_timing_rejected_before_can(head_node, monkeypatch, name, invalid):
    calls = prepare_startup(head_node, monkeypatch, {name: invalid})
    with pytest.raises(ValueError, match=name):
        head_node.HeadRosNode()
    assert calls == []


def test_enable_interval_override_used_at_startup(head_node, monkeypatch):
    calls = prepare_startup(head_node, monkeypatch, {"enable_interval": 0.0})
    head_node.HeadRosNode()
    assert calls == ["connect", "configure", "enable:0.0"]


@pytest.mark.parametrize("invalid", [-0.1, float("nan"), float("inf")])
def test_invalid_feedback_timeout_rejected_before_can(head_node, monkeypatch, invalid):
    calls = prepare_startup(head_node, monkeypatch, {"feedback_timeout": invalid})
    with pytest.raises(ValueError, match="feedback_timeout"):
        head_node.HeadRosNode()
    assert calls == []


@pytest.mark.parametrize("invalid", [-0.1, float("nan"), float("inf")])
def test_invalid_enable_interval_rejected_before_can(head_node, monkeypatch, invalid):
    calls = prepare_startup(head_node, monkeypatch, {"enable_interval": invalid})
    with pytest.raises(ValueError, match="enable_interval"):
        head_node.HeadRosNode()
    assert calls == []


def test_monitor_startup_does_not_configure_or_enable(head_node, monkeypatch):
    calls = prepare_startup(head_node, monkeypatch, {
        "auto_configure": False, "auto_enable": False, "control_enabled": False,
    })
    node = head_node.HeadRosNode()
    assert calls == ["connect"]
    assert not node._control_enabled


@pytest.mark.parametrize("fail_at", ["connect", "configure", "enable:0.1"])
def test_startup_failure_closes_sdk(head_node, monkeypatch, fail_at):
    calls = prepare_startup(head_node, monkeypatch, fail_at=fail_at)
    with pytest.raises(RuntimeError):
        head_node.HeadRosNode()
    assert calls[-1] == "close"


@pytest.mark.parametrize("limit", [-1.0, float("nan"), float("inf")])
def test_invalid_torque_limit_rejected(head_node, limit):
    with pytest.raises(ValueError, match="torque_limit"):
        head_node.torque_limit_to_current_a(limit, 1.0, 2.0)


@pytest.mark.parametrize("scale", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_torque_scale_rejected(head_node, scale):
    with pytest.raises(ValueError, match="torque_k"):
        head_node.torque_limit_to_current_a(2.0, scale, 1.0)


def test_torque_limit_conversion(head_node):
    assert head_node.torque_limit_to_current_a(6.0, 2.0, 3.0) == 1.0
    assert head_node.torque_limit_to_current_a(0.0, 2.0, 3.0) == 0.0


@pytest.fixture
def head_launch(monkeypatch):
    attributes = {
        "ament_index_python": {},
        "ament_index_python.packages": {
            "get_package_share_directory": lambda name: "/unused/head_ros"
        },
        "launch": {"LaunchDescription": lambda actions: actions},
        "launch.actions": {
            "DeclareLaunchArgument": lambda name, **kwargs: SimpleNamespace(name=name, **kwargs),
            "OpaqueFunction": lambda **kwargs: SimpleNamespace(**kwargs),
        },
        "launch.substitutions": {
            "LaunchConfiguration": lambda name: SimpleNamespace(perform=lambda context: context[name])
        },
        "launch_ros": {},
        "launch_ros.actions": {"Node": lambda **kwargs: SimpleNamespace(**kwargs)},
    }
    for name, values in attributes.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).parents[1] / "launch" / "head.launch.py"
    spec = importlib.util.spec_from_file_location("head_launch_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launch_mode_and_typed_overrides(head_launch):
    actions = head_launch.generate_launch_description()
    context = {action.name: action.default_value for action in actions if hasattr(action, "name")}
    context.update({
        "yaml_path": "head.yaml", "control_mode": "mit", "auto_enable": "false",
        "auto_configure": "false", "control_enabled": "false", "feedback_rate": "50",
        "status_rate": "3", "status_timeout": "1.5",
    })
    node = head_launch._launch_setup(context)[0]
    assert node.parameters[1] == {
        "yaml_path": "head.yaml", "control_mode": "mit",
        "auto_enable": False, "auto_configure": False, "control_enabled": False,
        "feedback_rate": 50.0, "status_rate": 3.0, "status_timeout": 1.5,
    }
    mode_argument = next(action for action in actions if getattr(action, "name", None) == "control_mode")
    assert mode_argument.choices == ["", "pos", "mit"]


def test_launch_default_preserves_parameter_file(head_launch):
    actions = head_launch.generate_launch_description()
    context = {action.name: action.default_value for action in actions if hasattr(action, "name")}
    node = head_launch._launch_setup(context)[0]
    assert node.parameters == ["/unused/head_ros/config/head_ros.yaml"]


@pytest.mark.parametrize("constructor_fails", [True, False])
def test_main_failure_shuts_down_context(head_node, monkeypatch, constructor_fails):
    calls = []

    def make_node():
        if constructor_fails:
            raise RuntimeError("startup failed")
        return SimpleNamespace(destroy_node=lambda: calls.append("destroy"))

    def spin(node):
        calls.append("spin")
        raise RuntimeError("spin failed")

    monkeypatch.setattr(head_node, "HeadRosNode", make_node)
    monkeypatch.setattr(head_node.rclpy, "init", lambda **kwargs: calls.append("init"), raising=False)
    monkeypatch.setattr(head_node.rclpy, "spin", spin, raising=False)
    monkeypatch.setattr(head_node.rclpy, "ok", lambda: True, raising=False)
    monkeypatch.setattr(head_node.rclpy, "shutdown", lambda: calls.append("shutdown"), raising=False)
    with pytest.raises(RuntimeError):
        head_node.main()
    expected = ["init", "shutdown"] if constructor_fails else ["init", "spin", "destroy", "shutdown"]
    assert calls == expected


def test_gate_service_changes_internal_state_not_startup_parameter(head_node):
    node, commands, warnings = make_control_node(head_node, enabled=False)
    result = node._on_control_enable(SimpleNamespace(data=True), SimpleNamespace())
    assert result.success
    assert node._control_enabled
    node._on_control(SimpleNamespace(name=["joint1"], position=[0.2], velocity=[], effort=[]))
    assert commands == [("pos", (0, 0.2))]
    result = node._on_control_enable(SimpleNamespace(data=False), SimpleNamespace())
    assert result.success
    assert not node._control_enabled


@pytest.mark.parametrize("enable", [True, False])
def test_enable_service_reports_sdk_failure(head_node, enable):
    node, commands, warnings = make_control_node(head_node)
    node._enable_interval = 0.1
    calls = []
    node._group.enable = lambda interval: calls.append(("enable", interval)) or False
    node._group.disable = lambda interval: calls.append(("disable", interval)) or False
    result = node._on_enable(SimpleNamespace(data=enable), SimpleNamespace())
    assert not result.success
    assert "failed" in result.message
    assert calls == [("enable" if enable else "disable", 0.1)]
    assert node._control_enabled


def test_pos_ignores_velocity_and_effort(head_node):
    node, commands, warnings = make_control_node(head_node)
    node._on_control(SimpleNamespace(
        name=["joint1"], position=[0.2], velocity=[float("nan")], effort=[float("inf")]
    ))
    assert commands == [("pos", (0, 0.2))]


def test_overflowing_current_conversion_rejected(head_node):
    with pytest.raises(ValueError, match="converted current"):
        head_node.torque_limit_to_current_a(1e308, 1e-308, 1.0)


def make_feedback_node(module, cls, stamps, timeout=0.5):
    """Node with one joint per entry in ``stamps`` (high-speed feedback timestamp, ns)."""
    module.JointState = lambda: SimpleNamespace(header=SimpleNamespace())
    node = cls.__new__(cls)
    node._feedback_timeout = timeout
    node._stale_joints = set()
    node._joint_names = ["joint%d" % i for i in range(len(stamps))]
    published, logs = [], []
    node._feedback_pub = SimpleNamespace(publish=published.append)
    node.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: None))
    node.get_logger = lambda: SimpleNamespace(warn=logs.append, info=logs.append)

    def motor(index):
        stamp = stamps[index]
        feedback = None if stamp is None else SimpleNamespace(timestamp_ns=stamp)
        return SimpleNamespace(get_high_speed_feedback=lambda: feedback)

    def get_state(index):
        return SimpleNamespace(position_rad=0.1 * index, velocity_rad_s=0.0, torque_nm=0.0)

    node._group = SimpleNamespace(joint_count=len(stamps), motor=motor, get_state=get_state)
    return node, published, logs


def test_feedback_older_than_timeout_is_not_published(head_node):
    # time_ns is 10 s; joint1 is 0.6 s old; joint2 and joint3 have no usable stamp, so cannot be judged
    stamps = [9_600_000_000, 9_400_000_000, 0, None]
    node, published, logs = make_feedback_node(head_node, head_node.HeadRosNode, stamps)
    node._publish_feedback()
    assert published[-1].name == ["joint0", "joint2", "joint3"]
    assert logs == ["joint1 feedback older than 0.50 s, not published"]
    node._publish_feedback()
    assert len(logs) == 1


def test_feedback_timeout_zero_publishes_cached_samples(head_node):
    node, published, _ = make_feedback_node(head_node, head_node.HeadRosNode, [1, 1], timeout=0.0)
    node._publish_feedback()
    assert published[-1].name == ["joint0", "joint1"]


def test_stale_joint_is_published_again_once_fresh(head_node):
    stamps = [9_000_000_000]
    node, published, logs = make_feedback_node(head_node, head_node.HeadRosNode, stamps)
    node._publish_feedback()
    assert published == []
    stamps[0] = 10_000_000_000
    node._publish_feedback()
    assert published[-1].name == ["joint0"]
    assert logs[-1] == "joint0 feedback recovered"
