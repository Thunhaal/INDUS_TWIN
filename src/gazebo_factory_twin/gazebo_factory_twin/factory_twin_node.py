from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64, String


@dataclass
class Machine:
    machine_id: str
    nominal_kw: float
    min_kw: float
    production_rate: float
    criticality: str
    temperature: float
    vibration: float
    rpm: int
    normal_load_percent: float

    energy_kwh: float = 0.0
    reduction_kw: float = 0.0
    reduce_until: float = 0.0

    forced_load_percent: Optional[float] = None
    forced_temperature_offset: float = 0.0
    forced_vibration_offset: float = 0.0
    anomaly_started_at: float = 0.0
    anomaly_type: str = "NORMAL"
    anomaly_severity: str = "NONE"
    anomaly_source: str = "NONE"

    anomaly_history: list[bool] = field(default_factory=list)
    persistence_count: int = 0
    persistence_escalated: bool = False
    maintenance_required: bool = False
    escalation_state: str = "NORMAL"
    manual_anomaly_active: bool = False

    maintenance_mode: bool = False
    maintenance_started_at: float = 0.0

    # State captured when maintenance starts so an operator can move
    # ONGOING -> SUBMITTED without falsely marking the machine RUNNING.
    maintenance_previous_state: str = "RUNNING"
    maintenance_previous_faulted: bool = False
    maintenance_previous_fault_reason: str = ""
    maintenance_previous_fault_timestamp: float = 0.0
    maintenance_previous_damage_level: float = 0.0
    maintenance_previous_anomaly_type: str = "NORMAL"
    maintenance_previous_anomaly_severity: str = "NONE"
    maintenance_previous_escalation_state: str = "NORMAL"

    faulted: bool = False
    fault_reason: str = ""
    fault_timestamp: float = 0.0
    damage_level: float = 0.0


class FactoryTwinNode(Node):
    """Seven-machine ROS2 factory twin with 6/8 anomaly persistence."""

    ANOMALY_WINDOW_SIZE = 8
    ANOMALY_PERSISTENCE_THRESHOLD = 6
    ANOMALY_TRIP_LOAD_PERCENT = 112.0

    ANOMALY_PROFILES = {
        "HIGH_LOAD": {
            "load_percent": 120.0,
            "temperature_offset_c": 30.0,
            "vibration_offset_mm_s": 4.5,
        },
        "THERMAL_OVERLOAD": {
            "load_percent": 105.0,
            "temperature_offset_c": 60.0,
            "vibration_offset_mm_s": 0.8,
        },
        "VIBRATION_SPIKE": {
            "load_percent": 105.0,
            "temperature_offset_c": 12.0,
            "vibration_offset_mm_s": 5.0,
        },
        "POWER_SURGE": {
            "load_percent": 125.0,
            "temperature_offset_c": 25.0,
            "vibration_offset_mm_s": 2.5,
        },
    }

    def __init__(self) -> None:
        super().__init__("factory_twin")

        self.state_pub = self.create_publisher(
            String,
            "/factory/machine_state",
            20,
        )

        self.total_power_pub = self.create_publisher(
            Float64,
            "/factory/total_power_kw",
            10,
        )

        self.event_pub = self.create_publisher(
            String,
            "/factory/events",
            10,
        )

        self.create_subscription(
            String,
            "/factory/control_command",
            self.on_command,
            20,
        )

        self.create_subscription(
            Float64,
            "/factory/grid_stress_kw",
            self.on_grid_stress,
            10,
        )

        self.create_subscription(
            String,
            "/factory/scenario",
            self.on_scenario,
            20,
        )

        self.timer = self.create_timer(
            1.0,
            self.publish_snapshot,
        )

        self.step = 0
        self.last_time = time.time()
        self.grid_stress_kw = 0.0

        self.active_scenario_id = "NORMAL"
        self.active_scenario_type = "NORMAL"
        self.active_scenario_name = "Normal Operation"

        self.scenario_multiplier = 1.0
        self.scenario_required_reduction_kw = 0.0

        self.machines = [
            Machine(
                "CNC_01",
                30.0,
                20.0,
                22.0,
                "HIGH",
                49.0,
                0.15,
                2400,
                90.0,
            ),
            Machine(
                "CNC_02",
                30.0,
                20.0,
                23.0,
                "HIGH",
                51.0,
                0.16,
                2350,
                90.0,
            ),
            Machine(
                "CNC_03",
                30.0,
                20.0,
                21.0,
                "HIGH",
                48.0,
                0.14,
                2450,
                88.0,
            ),
            Machine(
                "COMP_01",
                37.0,
                20.0,
                18.0,
                "MEDIUM",
                65.0,
                0.30,
                1450,
                85.0,
            ),
            Machine(
                "PUMP_01",
                15.0,
                8.0,
                12.0,
                "MEDIUM",
                50.0,
                0.19,
                1800,
                82.0,
            ),
            Machine(
                "HVAC_01",
                22.0,
                8.0,
                0.0,
                "LOW",
                24.0,
                0.04,
                900,
                76.0,
            ),
            Machine(
                "FURNACE_01",
                75.0,
                70.0,
                16.0,
                "HIGH",
                820.0,
                0.11,
                1200,
                93.0,
            ),
        ]

        self.emit_event(
            "Factory digital twin online: "
            "seven machines initialized in NORMAL mode"
        )

    # ========================================================
    # HELPERS
    # ========================================================

    def find_machine(
        self,
        machine_id: str,
    ) -> Optional[Machine]:

        mid = str(machine_id).strip()

        for machine in self.machines:

            if machine.machine_id == mid:
                return machine

        return None

    def emit_event(
        self,
        text: str,
    ) -> None:

        message = String()

        message.data = json.dumps(
            {
                "timestamp": int(time.time()),
                "event": text,
            }
        )

        self.event_pub.publish(
            message
        )

        self.get_logger().info(
            text
        )

    # ========================================================
    # GRID
    # ========================================================

    def on_grid_stress(
        self,
        message: Float64,
    ) -> None:

        self.grid_stress_kw = max(
            0.0,
            float(message.data),
        )

    # ========================================================
    # SCENARIO
    # ========================================================

    def default_scenario_multiplier(
        self,
        scenario_id: str,
    ) -> float:

        return {
            "NORMAL": 1.00,
            "GRID_STRESS": 1.02,
            "PEAK_DEMAND": 1.05,
            "LOW_RENEWABLE": 1.00,
            "CRITICAL_GRID": 1.06,
            "EQUIPMENT_ANOMALY": 1.00,
        }.get(
            str(scenario_id).upper(),
            1.00,
        )

    def on_scenario(
        self,
        message: String,
    ) -> None:

        try:

            data = json.loads(
                message.data
            )

            scenario_id = str(
                data.get(
                    "scenario_id",
                    "NORMAL",
                )
            ).upper()

            status = str(
                data.get(
                    "status",
                    "ACTIVE",
                )
            ).upper()

            self.active_scenario_id = (
                scenario_id
            )

            self.active_scenario_type = str(
                data.get(
                    "scenario_type",
                    scenario_id,
                )
            )

            self.active_scenario_name = str(
                data.get(
                    "scenario_name",
                    scenario_id,
                )
            )

            self.scenario_multiplier = float(
                data.get(
                    "demand_multiplier",
                    self.default_scenario_multiplier(
                        scenario_id
                    ),
                )
            )

            self.scenario_required_reduction_kw = max(
                0.0,
                float(
                    data.get(
                        "required_reduction_kw",
                        0.0,
                    )
                ),
            )

            if (
                status == "COMPLETED"
                or scenario_id == "NORMAL"
            ):

                self.clear_scenario_effects()

                self.active_scenario_id = (
                    "NORMAL"
                )

                self.active_scenario_type = (
                    "NORMAL"
                )

                self.active_scenario_name = (
                    "Normal Operation"
                )

                self.scenario_multiplier = (
                    1.0
                )

                if status == "COMPLETED":
                    self.scenario_required_reduction_kw = (
                        0.0
                    )

                self.grid_stress_kw = (
                    self.scenario_required_reduction_kw
                )

                return

            if scenario_id == "EQUIPMENT_ANOMALY":

                self.activate_equipment_anomaly(
                    data
                )

            else:

                self.clear_transient_scenario_anomalies()

            self.grid_stress_kw = (
                self.scenario_required_reduction_kw
            )

            self.emit_event(
                f"SCENARIO_ACTIVE: "
                f"{scenario_id} | "
                f"{self.active_scenario_name} | "
                f"demand multiplier="
                f"{self.scenario_multiplier:.2f}"
            )

        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as error:

            self.emit_event(
                f"SCENARIO_REJECTED: {error}"
            )

    # ========================================================
    # ANOMALY PROFILES
    # ========================================================

    def get_anomaly_profile(
        self,
        anomaly_type: str,
        severity: str,
    ) -> dict:

        profile = dict(
            self.ANOMALY_PROFILES.get(
                str(anomaly_type).upper(),
                self.ANOMALY_PROFILES[
                    "HIGH_LOAD"
                ],
            )
        )

        severity = str(
            severity
        ).upper()

        if severity == "LOW":

            profile[
                "load_percent"
            ] -= 8.0

            profile[
                "temperature_offset_c"
            ] *= 0.45

            profile[
                "vibration_offset_mm_s"
            ] *= 0.45

        elif severity == "MEDIUM":

            profile[
                "load_percent"
            ] -= 3.0

            profile[
                "temperature_offset_c"
            ] *= 0.70

            profile[
                "vibration_offset_mm_s"
            ] *= 0.70

        elif severity == "CRITICAL":

            profile[
                "load_percent"
            ] += 3.0

            profile[
                "temperature_offset_c"
            ] *= 1.20

            profile[
                "vibration_offset_mm_s"
            ] *= 1.20

        profile["load_percent"] = max(
            0.0,
            min(
                130.0,
                profile["load_percent"],
            ),
        )

        return profile

    # ========================================================
    # SCENARIO EQUIPMENT ANOMALY
    # ========================================================

    def activate_equipment_anomaly(
        self,
        scenario: dict,
    ) -> None:

        machine_id = str(
            scenario.get(
                "anomaly_machine_id",
                "CNC_03",
            )
        )

        anomaly_type = str(
            scenario.get(
                "anomaly_type",
                "HIGH_LOAD",
            )
        ).upper()

        severity = str(
            scenario.get(
                "anomaly_severity",
                "CRITICAL",
            )
        ).upper()

        profile = self.get_anomaly_profile(
            anomaly_type,
            severity,
        )

        self.inject_anomaly(
            machine_id=machine_id,
            anomaly_type=anomaly_type,
            severity=severity,
            load_percent=float(
                scenario.get(
                    "anomaly_load_percent",
                    profile["load_percent"],
                )
            ),
            temperature_offset=float(
                scenario.get(
                    "anomaly_temperature_offset_c",
                    profile[
                        "temperature_offset_c"
                    ],
                )
            ),
            vibration_offset=float(
                scenario.get(
                    "anomaly_vibration_offset_mm_s",
                    profile[
                        "vibration_offset_mm_s"
                    ],
                )
            ),
            duration_sec=max(
                1.0,
                float(
                    scenario.get(
                        "duration_min",
                        5.0,
                    )
                ) * 60.0,
            ),
            source="SCENARIO",
        )

    # ========================================================
    # INJECT ANOMALY
    # ========================================================

    def inject_anomaly(
        self,
        machine_id: str,
        anomaly_type: str,
        severity: str,
        load_percent: float,
        temperature_offset: float,
        vibration_offset: float,
        duration_sec: float,
        source: str = "MANUAL",
    ) -> bool:

        machine = self.find_machine(
            machine_id
        )

        if machine is None:

            self.emit_event(
                "ANOMALY_INJECTION_REJECTED: "
                f"unknown machine {machine_id}"
            )

            return False

        if machine.maintenance_mode:

            self.emit_event(
                "ANOMALY_INJECTION_REJECTED: "
                f"{machine.machine_id} "
                f"is in maintenance"
            )

            return False

        if (
            machine.faulted
            or machine.maintenance_required
        ):

            self.emit_event(
                "ANOMALY_INJECTION_REJECTED: "
                f"{machine.machine_id} "
                f"requires maintenance"
            )

            return False

        machine.forced_load_percent = max(
            0.0,
            min(
                130.0,
                float(load_percent),
            ),
        )

        machine.forced_temperature_offset = float(
            temperature_offset
        )

        machine.forced_vibration_offset = max(
            0.0,
            float(vibration_offset),
        )

        machine.reduction_kw = 0.0

        machine.reduce_until = (
            time.time()
            + max(
                1.0,
                float(duration_sec),
            )
        )

        machine.anomaly_started_at = (
            time.time()
        )

        machine.anomaly_type = str(
            anomaly_type
        ).upper()

        machine.anomaly_severity = str(
            severity
        ).upper()

        machine.anomaly_source = str(
            source
        ).upper()

        machine.manual_anomaly_active = (
            machine.anomaly_source
            == "MANUAL"
        )

        # New injection starts a fresh evidence window.
        machine.anomaly_history.clear()

        machine.persistence_count = 0

        machine.persistence_escalated = (
            False
        )

        machine.maintenance_required = (
            False
        )

        machine.escalation_state = (
            "ANOMALY"
        )

        machine.damage_level = 0.0

        self.emit_event(
            f"ANOMALY_INJECTED: "
            f"{machine.machine_id} | "
            f"type={machine.anomaly_type} | "
            f"severity={machine.anomaly_severity} | "
            f"load={machine.forced_load_percent:.1f}% | "
            f"temp_offset=+"
            f"{machine.forced_temperature_offset:.1f} C | "
            f"vibration_offset=+"
            f"{machine.forced_vibration_offset:.2f} mm/s | "
            f"duration="
            f"{float(duration_sec):.0f}s"
        )

        return True

    # ========================================================
    # 6 / 8 PERSISTENCE
    # ========================================================

    def record_anomaly_reading(
        self,
        machine: Machine,
        abnormal: bool,
    ) -> None:

        machine.anomaly_history.append(
            bool(abnormal)
        )

        if (
            len(machine.anomaly_history)
            > self.ANOMALY_WINDOW_SIZE
        ):

            machine.anomaly_history = (
                machine.anomaly_history[
                    -self.ANOMALY_WINDOW_SIZE:
                ]
            )

        machine.persistence_count = sum(
            machine.anomaly_history
        )

        if (
            machine.maintenance_mode
            or machine.faulted
        ):

            return

        # Escalate as soon as six abnormal readings
        # exist within the latest eight readings.
        if (
            machine.persistence_count
            >= self.ANOMALY_PERSISTENCE_THRESHOLD
        ):

            machine.maintenance_required = (
                True
            )

            if not machine.persistence_escalated:

                machine.persistence_escalated = (
                    True
                )

                self.escalate_persistent_anomaly(
                    machine
                )

        elif abnormal:

            machine.escalation_state = (
                "ANOMALY"
            )

    def escalate_persistent_anomaly(
        self,
        machine: Machine,
    ) -> None:

        severity = str(
            machine.anomaly_severity
        ).upper()

        count = (
            machine.persistence_count
        )

        # High/Critical = FAULT.
        if severity in {
            "HIGH",
            "CRITICAL",
        }:

            self.trip_machine(
                machine,
                reason="PERSISTENT_ANOMALY",
            )

            self.emit_event(
                f"PERSISTENT_ANOMALY_ESCALATED: "
                f"{machine.machine_id} | "
                f"{count}/"
                f"{self.ANOMALY_WINDOW_SIZE} "
                f"abnormal readings | "
                f"severity={severity} | "
                f"state=FAULT | "
                f"maintenance ticket required"
            )

            return

        # Low/Medium = IDLE + maintenance required.
        machine.escalation_state = (
            "IDLE"
        )

        machine.maintenance_required = (
            True
        )

        machine.forced_load_percent = (
            None
        )

        machine.forced_temperature_offset = (
            0.0
        )

        machine.forced_vibration_offset = (
            0.0
        )

        machine.reduction_kw = 0.0
        machine.reduce_until = 0.0
        machine.anomaly_started_at = 0.0

        machine.anomaly_type = (
            "MAINTENANCE_REQUIRED"
        )

        machine.anomaly_source = (
            "NONE"
        )

        machine.manual_anomaly_active = (
            False
        )

        self.emit_event(
            f"PERSISTENT_ANOMALY_ESCALATED: "
            f"{machine.machine_id} | "
            f"{count}/"
            f"{self.ANOMALY_WINDOW_SIZE} "
            f"abnormal readings | "
            f"severity={severity} | "
            f"state=IDLE | "
            f"maintenance ticket required"
        )

    # ========================================================
    # CLEARING
    # ========================================================

    def clear_transient_scenario_anomalies(
        self,
    ) -> None:

        for machine in self.machines:

            if (
                machine.anomaly_source
                == "SCENARIO"
                and not machine.faulted
                and not machine.maintenance_mode
                and not machine.persistence_escalated
            ):

                self.clear_anomaly(
                    machine,
                    emit=False,
                )

    def clear_scenario_effects(
        self,
    ) -> None:

        self.clear_transient_scenario_anomalies()

        for machine in self.machines:

            if (
                not machine.faulted
                and not machine.maintenance_mode
                and not machine.manual_anomaly_active
                and not machine.persistence_escalated
            ):

                machine.reduction_kw = 0.0
                machine.reduce_until = 0.0

    def clear_anomaly(
        self,
        machine: Machine,
        emit: bool = True,
    ) -> bool:

        if (
            machine.faulted
            or machine.maintenance_mode
            or machine.maintenance_required
        ):

            if emit:

                self.emit_event(
                    f"ANOMALY_CLEAR_REJECTED: "
                    f"{machine.machine_id} | "
                    f"maintenance required"
                )

            return False

        machine.forced_load_percent = (
            None
        )

        machine.forced_temperature_offset = (
            0.0
        )

        machine.forced_vibration_offset = (
            0.0
        )

        machine.anomaly_started_at = 0.0
        machine.anomaly_type = "NORMAL"
        machine.anomaly_severity = "NONE"
        machine.anomaly_source = "NONE"
        machine.manual_anomaly_active = False

        machine.anomaly_history.clear()
        machine.persistence_count = 0
        machine.persistence_escalated = False
        machine.maintenance_required = False
        machine.escalation_state = "NORMAL"
        machine.damage_level = 0.0

        machine.reduce_until = 0.0
        machine.reduction_kw = 0.0

        if emit:

            self.emit_event(
                f"ANOMALY_STOPPED: "
                f"{machine.machine_id} | "
                f"persistence window cleared"
            )

        return True

    # ========================================================
    # MAINTENANCE
    # ========================================================

    def start_maintenance(
        self,
        machine: Machine,
    ) -> None:

        if machine.maintenance_mode:

            return

        # Capture the machine condition before entering maintenance.
        # This lets SUBMITTED (reopened ticket) restore FAULT/IDLE instead
        # of incorrectly leaving the machine in RUNNING.
        if machine.faulted or str(machine.escalation_state).upper() == "FAULT":
            machine.maintenance_previous_state = "FAULT"
        elif str(machine.escalation_state).upper() == "IDLE":
            machine.maintenance_previous_state = "IDLE"
        else:
            machine.maintenance_previous_state = "RUNNING"

        machine.maintenance_previous_faulted = machine.faulted
        machine.maintenance_previous_fault_reason = machine.fault_reason
        machine.maintenance_previous_fault_timestamp = machine.fault_timestamp
        machine.maintenance_previous_damage_level = machine.damage_level
        machine.maintenance_previous_anomaly_type = machine.anomaly_type
        machine.maintenance_previous_anomaly_severity = machine.anomaly_severity
        machine.maintenance_previous_escalation_state = machine.escalation_state

        machine.maintenance_mode = True
        machine.maintenance_started_at = (
            time.time()
        )

        machine.reduction_kw = 0.0
        machine.reduce_until = 0.0

        machine.forced_load_percent = (
            None
        )

        machine.forced_temperature_offset = (
            0.0
        )

        machine.forced_vibration_offset = (
            0.0
        )

        machine.anomaly_started_at = 0.0
        machine.anomaly_source = "NONE"
        machine.manual_anomaly_active = False

        machine.anomaly_type = (
            "MAINTENANCE"
        )

        machine.anomaly_severity = (
            "NONE"
        )

        machine.maintenance_required = (
            True
        )

        machine.escalation_state = (
            "MAINTENANCE"
        )

        self.emit_event(
            f"MAINTENANCE_STARTED: "
            f"{machine.machine_id} | "
            f"machine state=MAINTENANCE | "
            f"production stopped"
        )

    def reopen_maintenance(
        self,
        machine: Machine,
    ) -> None:

        if not machine.maintenance_mode:

            self.emit_event(
                f"MAINTENANCE_REOPEN_NOOP: "
                f"{machine.machine_id} not in maintenance"
            )

            return

        previous_state = (
            str(
                machine.maintenance_previous_state
            ).upper()
        )

        machine.maintenance_mode = False
        machine.maintenance_started_at = 0.0

        machine.reduction_kw = 0.0
        machine.reduce_until = 0.0
        machine.forced_load_percent = None
        machine.forced_temperature_offset = 0.0
        machine.forced_vibration_offset = 0.0
        machine.anomaly_started_at = 0.0
        machine.anomaly_history.clear()
        machine.persistence_count = 0
        machine.persistence_escalated = True
        machine.manual_anomaly_active = False
        machine.anomaly_source = "NONE"

        if previous_state == "FAULT":
            machine.faulted = True
            machine.fault_reason = (
                machine.maintenance_previous_fault_reason
                or "MAINTENANCE_REQUIRED"
            )
            machine.fault_timestamp = (
                machine.maintenance_previous_fault_timestamp
                or time.time()
            )
            machine.damage_level = (
                machine.maintenance_previous_damage_level
            )
            machine.maintenance_required = True
            machine.escalation_state = "FAULT"
            machine.anomaly_type = "EQUIPMENT_FAILURE"
            machine.anomaly_severity = "CRITICAL"

        elif previous_state == "IDLE":
            machine.faulted = False
            machine.fault_reason = ""
            machine.fault_timestamp = 0.0
            machine.damage_level = (
                machine.maintenance_previous_damage_level
            )
            machine.maintenance_required = True
            machine.escalation_state = "IDLE"
            machine.anomaly_type = (
                machine.maintenance_previous_anomaly_type
                if machine.maintenance_previous_anomaly_type
                not in {"", "NORMAL", "MAINTENANCE"}
                else "MAINTENANCE_REQUIRED"
            )
            machine.anomaly_severity = (
                machine.maintenance_previous_anomaly_severity
                if machine.maintenance_previous_anomaly_severity
                not in {"", "NONE"}
                else "MEDIUM"
            )

        else:
            machine.faulted = False
            machine.fault_reason = ""
            machine.fault_timestamp = 0.0
            machine.damage_level = 0.0
            machine.maintenance_required = False
            machine.persistence_escalated = False
            machine.escalation_state = "NORMAL"
            machine.anomaly_type = "NORMAL"
            machine.anomaly_severity = "NONE"
            machine.anomaly_source = "NONE"

        self.emit_event(
            f"MAINTENANCE_REOPENED: "
            f"{machine.machine_id} | "
            f"machine state={previous_state} | "
            f"maintenance paused | "
            f"ticket returned to SUBMITTED"
        )

    def complete_maintenance(
        self,
        machine: Machine,
    ) -> None:

        was_faulted = machine.faulted
        previous_damage = (
            machine.damage_level
        )

        machine.maintenance_mode = False
        machine.maintenance_started_at = (
            0.0
        )

        machine.faulted = False
        machine.fault_reason = ""
        machine.fault_timestamp = 0.0
        machine.damage_level = 0.0

        machine.reduction_kw = 0.0
        machine.reduce_until = 0.0

        machine.forced_load_percent = (
            None
        )

        machine.forced_temperature_offset = (
            0.0
        )

        machine.forced_vibration_offset = (
            0.0
        )

        machine.anomaly_started_at = 0.0
        machine.anomaly_type = "NORMAL"
        machine.anomaly_severity = "NONE"
        machine.anomaly_source = "NONE"
        machine.manual_anomaly_active = False

        machine.anomaly_history.clear()
        machine.persistence_count = 0
        machine.persistence_escalated = False
        machine.maintenance_required = False
        machine.escalation_state = "NORMAL"

        self.emit_event(
            f"MAINTENANCE_COMPLETED: "
            f"{machine.machine_id} | "
            f"fault_repaired="
            f"{str(was_faulted).lower()} | "
            f"previous_damage="
            f"{previous_damage:.0%} | "
            f"machine restored"
        )

    # ========================================================
    # FAULT
    # ========================================================

    def trip_machine(
        self,
        machine: Machine,
        reason: str = "SUSTAINED_OVERLOAD",
    ) -> None:

        if machine.faulted:

            return

        load = float(
            machine.forced_load_percent
            or 100.0
        )

        factor = max(
            0.0,
            min(
                1.0,
                (
                    load
                    - self.ANOMALY_TRIP_LOAD_PERCENT
                ) / 18.0,
            ),
        )

        machine.damage_level = max(
            machine.damage_level,
            min(
                1.0,
                0.35
                + 0.65 * factor,
            ),
        )

        machine.faulted = True

        machine.fault_reason = str(
            reason
        ).upper()

        machine.fault_timestamp = (
            time.time()
        )

        machine.maintenance_required = (
            True
        )

        machine.escalation_state = (
            "FAULT"
        )

        machine.forced_load_percent = (
            None
        )

        machine.forced_temperature_offset = (
            0.0
        )

        machine.forced_vibration_offset = (
            0.0
        )

        machine.reduction_kw = 0.0
        machine.reduce_until = 0.0
        machine.anomaly_started_at = 0.0
        machine.anomaly_source = "NONE"
        machine.manual_anomaly_active = False

        machine.anomaly_type = (
            "EQUIPMENT_FAILURE"
        )

        machine.anomaly_severity = (
            "CRITICAL"
        )

        self.emit_event(
            f"MACHINE_TRIP: "
            f"{machine.machine_id} | "
            f"reason={machine.fault_reason} | "
            f"overload={load:.1f}% | "
            f"simulated_damage="
            f"{machine.damage_level:.0%} | "
            f"production stopped"
        )

    # ========================================================
    # COMMAND INTERFACE
    # ========================================================

    def on_command(
        self,
        message: String,
    ) -> None:

        try:

            command = json.loads(
                message.data
            )

            command_type = str(
                command.get(
                    "command",
                    command.get(
                        "action",
                        "",
                    ),
                )
            ).upper().strip()

            # ------------------------------------------------
            # RESET_ALL
            # ------------------------------------------------

            if command_type == "RESET_ALL":

                for machine in self.machines:

                    if (
                        machine.maintenance_mode
                        or machine.faulted
                    ):

                        continue

                    self.clear_anomaly(
                        machine,
                        emit=False,
                    )

                self.emit_event(
                    "RESET_ALL: "
                    "transient machine controls cleared"
                )

                return

            machine_id = command.get(
                "machine_id"
            )

            if machine_id is None:

                raise ValueError(
                    "machine_id is required"
                )

            machine = self.find_machine(
                machine_id
            )

            if machine is None:

                raise ValueError(
                    f"Unknown machine "
                    f"{machine_id}"
                )

            # ------------------------------------------------
            # MAINTENANCE START
            # ------------------------------------------------

            if command_type in {
                "MAINTENANCE_START",
                "SET_MAINTENANCE_IDLE",
            }:

                self.start_maintenance(
                    machine
                )

                return

            # ------------------------------------------------
            # MAINTENANCE REOPEN / PAUSE
            # ------------------------------------------------

            if command_type in {
                "MAINTENANCE_REOPEN",
                "MAINTENANCE_PAUSE",
            }:

                self.reopen_maintenance(
                    machine
                )

                return

            # ------------------------------------------------
            # MAINTENANCE COMPLETE
            # ------------------------------------------------

            if command_type in {
                "MAINTENANCE_COMPLETE",
                "RELEASE_MAINTENANCE",
            }:

                if not machine.maintenance_mode:

                    self.emit_event(
                        f"MAINTENANCE_COMPLETE_NOOP: "
                        f"{machine.machine_id} "
                        f"not in maintenance"
                    )

                    return

                self.complete_maintenance(
                    machine
                )

                return

            # ------------------------------------------------
            # RESET_FAULT
            # ------------------------------------------------

            if command_type == "RESET_FAULT":

                if not machine.maintenance_mode:

                    self.emit_event(
                        f"RESET_FAULT_REJECTED: "
                        f"{machine.machine_id} "
                        f"must be in maintenance"
                    )

                    return

                machine.faulted = False
                machine.fault_reason = ""
                machine.fault_timestamp = 0.0
                machine.damage_level = 0.0

                self.emit_event(
                    f"FAULT_RESET: "
                    f"{machine.machine_id}"
                )

                return

            # No control is allowed during maintenance.
            if machine.maintenance_mode:

                self.emit_event(
                    f"CONTROL_REJECTED: "
                    f"{machine.machine_id} "
                    f"is in maintenance"
                )

                return

            # Faulted machines must go through maintenance.
            if machine.faulted:

                self.emit_event(
                    f"CONTROL_REJECTED: "
                    f"{machine.machine_id} "
                    f"is faulted; maintenance required"
                )

                return

            # ------------------------------------------------
            # REDUCE_LOAD
            # ------------------------------------------------

            if command_type == "REDUCE_LOAD":

                target = max(
                    machine.min_kw,
                    min(
                        machine.nominal_kw,
                        float(
                            command["target_kw"]
                        ),
                    ),
                )

                normal_power = (
                    machine.nominal_kw
                    * machine.normal_load_percent
                    / 100.0
                )

                machine.reduction_kw = max(
                    0.0,
                    normal_power - target,
                )

                machine.reduce_until = (
                    time.time()
                    + max(
                        1.0,
                        float(
                            command.get(
                                "duration_sec",
                                900,
                            )
                        ),
                    )
                )

                machine.forced_load_percent = (
                    None
                )

                machine.anomaly_type = (
                    "NORMAL"
                )

                machine.anomaly_severity = (
                    "NONE"
                )

                machine.anomaly_source = (
                    "NONE"
                )

                machine.manual_anomaly_active = (
                    False
                )

                machine.escalation_state = (
                    "REDUCED"
                )

                self.emit_event(
                    f"CONTROL_APPLIED: "
                    f"{machine.machine_id} | "
                    f"target={target:.2f} kW | "
                    f"reduction="
                    f"{machine.reduction_kw:.2f} kW"
                )

                return

            # ------------------------------------------------
            # ANOMALY_INJECT / SET_LOAD
            # ------------------------------------------------

            if command_type in {
                "ANOMALY_INJECT",
                "SET_LOAD",
            }:

                anomaly_type = str(
                    command.get(
                        "anomaly_type",
                        "HIGH_LOAD",
                    )
                ).upper()

                severity = str(
                    command.get(
                        "severity",
                        command.get(
                            "anomaly_severity",
                            "HIGH",
                        ),
                    )
                ).upper()

                profile = self.get_anomaly_profile(
                    anomaly_type,
                    severity,
                )

                self.inject_anomaly(
                    machine_id=machine.machine_id,
                    anomaly_type=anomaly_type,
                    severity=severity,
                    load_percent=float(
                        command.get(
                            "load_percent",
                            profile[
                                "load_percent"
                            ],
                        )
                    ),
                    temperature_offset=float(
                        command.get(
                            "temperature_offset_c",
                            profile[
                                "temperature_offset_c"
                            ],
                        )
                    ),
                    vibration_offset=float(
                        command.get(
                            "vibration_offset_mm_s",
                            profile[
                                "vibration_offset_mm_s"
                            ],
                        )
                    ),
                    duration_sec=float(
                        command.get(
                            "duration_sec",
                            60.0,
                        )
                    ),
                    source="MANUAL",
                )

                return

            # ------------------------------------------------
            # STOP / CLEAR ANOMALY
            # ------------------------------------------------

            if command_type in {
                "STOP_ANOMALY",
                "CLEAR_ANOMALY",
            }:

                self.clear_anomaly(
                    machine
                )

                return

            # ------------------------------------------------
            # RESTORE_NORMAL
            # ------------------------------------------------

            if command_type == "RESTORE_NORMAL":

                if (
                    machine.faulted
                    or machine.maintenance_required
                ):

                    self.emit_event(
                        f"RESTORE_REJECTED: "
                        f"{machine.machine_id} "
                        f"requires maintenance"
                    )

                    return

                self.clear_anomaly(
                    machine
                )

                self.emit_event(
                    f"MACHINE_RESTORED: "
                    f"{machine.machine_id} | "
                    f"transient controls cleared"
                )

                return

            raise ValueError(
                f"Unsupported command: "
                f"{command_type}"
            )

        except (
            KeyError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as error:

            self.emit_event(
                f"CONTROL_REJECTED: "
                f"{error}"
            )

    # ========================================================
    # SNAPSHOT
    # ========================================================

    def publish_snapshot(
        self,
    ) -> None:

        now = time.time()

        elapsed = max(
            0.1,
            min(
                5.0,
                now - self.last_time,
            ),
        )

        self.last_time = now
        self.step += 1

        total_power = 0.0

        general_wave = math.sin(
            self.step / 3.5
        )

        for index, machine in enumerate(
            self.machines
        ):

            # ------------------------------------------------
            # EXPIRY
            # ------------------------------------------------

            if (
                machine.reduce_until > 0.0
                and machine.reduce_until <= now
            ):

                if (
                    machine.forced_load_percent
                    is not None
                    and not machine.faulted
                ):

                    machine.forced_load_percent = (
                        None
                    )

                    machine.forced_temperature_offset = (
                        0.0
                    )

                    machine.forced_vibration_offset = (
                        0.0
                    )

                    machine.anomaly_started_at = (
                        0.0
                    )

                    machine.reduce_until = (
                        0.0
                    )

                    # An escalated condition is latched.
                    if not machine.persistence_escalated:

                        machine.anomaly_type = (
                            "NORMAL"
                        )

                        machine.anomaly_severity = (
                            "NONE"
                        )

                        machine.anomaly_source = (
                            "NONE"
                        )

                        machine.manual_anomaly_active = (
                            False
                        )

                        machine.damage_level = (
                            0.0
                        )

                        machine.anomaly_history.clear()

                        machine.persistence_count = (
                            0
                        )

                        machine.maintenance_required = (
                            False
                        )

                        machine.escalation_state = (
                            "NORMAL"
                        )

                        self.emit_event(
                            f"ANOMALY_EXPIRED: "
                            f"{machine.machine_id}"
                        )

                    else:

                        self.emit_event(
                            f"ANOMALY_EXPIRED: "
                            f"{machine.machine_id} | "
                            f"persistent maintenance "
                            f"state retained"
                        )

                else:

                    machine.reduction_kw = (
                        0.0
                    )

                    machine.reduce_until = (
                        0.0
                    )

            # ------------------------------------------------
            # SMALL MACHINE FLUCTUATION
            # ------------------------------------------------

            machine_wave = math.sin(
                (
                    self.step
                    + index * 2.5
                ) / 4.0
            )

            wave_kw = (
                machine_wave
                * (
                    0.30
                    if machine.machine_id
                    == "FURNACE_01"
                    else 0.55
                )
            )

            state = "RUNNING"
            power = 0.0
            production_rate = 0.0
            load_percent = 0.0

            temperature = (
                machine.temperature
            )

            vibration = (
                machine.vibration
            )

            # ------------------------------------------------
            # MAINTENANCE
            # ------------------------------------------------

            if machine.maintenance_mode:

                state = "MAINTENANCE"

                power = 0.0

                production_rate = 0.0

                load_percent = 0.0

                temperature = max(
                    20.0,
                    machine.temperature
                    - 0.05 * elapsed,
                )

                vibration = max(
                    0.0,
                    machine.vibration
                    - 0.002 * elapsed,
                )

            # ------------------------------------------------
            # FAULT
            # ------------------------------------------------

            elif machine.faulted:

                state = "FAULT"

                power = 0.0

                production_rate = 0.0

                load_percent = 0.0

                temperature = max(
                    20.0,
                    machine.temperature
                    - 0.10 * elapsed,
                )

                vibration = max(
                    0.0,
                    machine.vibration
                    - 0.003 * elapsed,
                )

            # ------------------------------------------------
            # PERSISTENT NON-CRITICAL ANOMALY
            # ------------------------------------------------

            elif (
                machine.persistence_escalated
                and machine.maintenance_required
            ):

                state = "IDLE"

                power = 0.0

                production_rate = 0.0

                load_percent = 0.0

                temperature = max(
                    20.0,
                    machine.temperature
                    - 0.05 * elapsed,
                )

                vibration = max(
                    0.0,
                    machine.vibration
                    - 0.002 * elapsed,
                )

            else:

                # ------------------------------------------------
                # BASE POWER
                # ------------------------------------------------

                if (
                    machine.forced_load_percent
                    is not None
                ):

                    power = (
                        machine.nominal_kw
                        * machine.forced_load_percent
                        / 100.0
                    )

                else:

                    target_percent = min(
                        99.0,
                        machine.normal_load_percent
                        * self.scenario_multiplier,
                    )

                    power = (
                        machine.nominal_kw
                        * target_percent
                        / 100.0
                    )

                power += wave_kw

                # ------------------------------------------------
                # ENERGY CONTROL
                # ------------------------------------------------

                if machine.reduction_kw > 0.0:

                    power = max(
                        machine.min_kw,
                        power
                        - machine.reduction_kw,
                    )

                else:

                    power = max(
                        0.0,
                        power,
                    )

                load_percent = (
                    power
                    / max(
                        machine.nominal_kw,
                        0.1,
                    )
                    * 100.0
                )

                # ------------------------------------------------
                # ACTIVE ANOMALY
                # ------------------------------------------------

                if (
                    machine.forced_load_percent
                    is not None
                ):

                    state = "ANOMALY"

                    anomaly_load = float(
                        machine.forced_load_percent
                    )

                    # Exactly one reading is added
                    # every telemetry cycle.
                    self.record_anomaly_reading(
                        machine,
                        True,
                    )

                    overload_ratio = max(
                        0.0,
                        anomaly_load
                        - 100.0,
                    ) / 100.0

                    sensor_stress = min(
                        0.50,
                        max(
                            0.0,
                            machine.forced_temperature_offset
                            / 150.0,
                        )
                        + min(
                            0.25,
                            machine.forced_vibration_offset
                            / 20.0,
                        ),
                    )

                    if (
                        anomaly_load
                        >= self.ANOMALY_TRIP_LOAD_PERCENT
                    ):

                        machine.damage_level = min(
                            0.35,
                            machine.damage_level
                            + 0.04,
                        )

                    health = max(
                        0.0,
                        1.0
                        - overload_ratio * 0.35
                        - sensor_stress * 0.20
                        - machine.damage_level * 0.15,
                    )

                    production_rate = (
                        machine.production_rate
                        * health
                    )

                    load_stress = max(
                        0.0,
                        load_percent
                        - machine.normal_load_percent,
                    ) / 100.0

                    temperature = (
                        machine.temperature
                        + general_wave * 0.20
                        + machine_wave * 0.12
                        + load_stress * 8.0
                        + machine.forced_temperature_offset
                        + machine.damage_level * 8.0
                    )

                    vibration = (
                        machine.vibration
                        + abs(machine_wave)
                        * 0.003
                        + load_stress * 0.12
                        + machine.forced_vibration_offset
                        + machine.damage_level * 0.60
                    )

                    # Same-cycle state update after 6/8.
                    if machine.faulted:

                        state = "FAULT"

                        power = 0.0
                        production_rate = 0.0
                        load_percent = 0.0

                        temperature = max(
                            20.0,
                            machine.temperature
                            - 0.10 * elapsed,
                        )

                        vibration = max(
                            0.0,
                            machine.vibration
                            - 0.003 * elapsed,
                        )

                    elif (
                        machine.persistence_escalated
                        and machine.maintenance_required
                    ):

                        state = "IDLE"

                        power = 0.0
                        production_rate = 0.0
                        load_percent = 0.0

                        temperature = max(
                            20.0,
                            machine.temperature
                            - 0.05 * elapsed,
                        )

                        vibration = max(
                            0.0,
                            machine.vibration
                            - 0.002 * elapsed,
                        )

                # ------------------------------------------------
                # REDUCED
                # ------------------------------------------------

                elif (
                    machine.reduction_kw
                    > 0.0
                ):

                    state = "REDUCED"

                    reduction_fraction = (
                        machine.reduction_kw
                        / max(
                            machine.nominal_kw,
                            1.0,
                        )
                    )

                    production_rate = (
                        machine.production_rate
                        * max(
                            0.0,
                            1.0
                            - reduction_fraction
                            * 0.25,
                        )
                    )

                    load_stress = max(
                        0.0,
                        load_percent
                        - machine.normal_load_percent,
                    ) / 100.0

                    temperature = (
                        machine.temperature
                        + general_wave
                        * 0.20
                        + machine_wave
                        * 0.12
                        + load_stress * 8.0
                    )

                    vibration = (
                        machine.vibration
                        + abs(machine_wave)
                        * 0.003
                        + load_stress * 0.12
                    )

                # ------------------------------------------------
                # NORMAL
                # ------------------------------------------------

                else:

                    state = "RUNNING"

                    production_rate = (
                        machine.production_rate
                    )

                    # Normal observation enters rolling window.
                    self.record_anomaly_reading(
                        machine,
                        False,
                    )

                    load_stress = max(
                        0.0,
                        load_percent
                        - machine.normal_load_percent,
                    ) / 100.0

                    temperature = (
                        machine.temperature
                        + general_wave * 0.20
                        + machine_wave * 0.12
                        + load_stress * 8.0
                    )

                    vibration = (
                        machine.vibration
                        + abs(machine_wave)
                        * 0.003
                        + load_stress * 0.12
                    )

            # ------------------------------------------------
            # ENERGY
            # ------------------------------------------------

            machine.energy_kwh += (
                power
                * elapsed
                / 3600.0
            )

            total_power += power

            # ------------------------------------------------
            # PRODUCTION
            # ------------------------------------------------

            units_produced = (
                production_rate
                * elapsed
                / 3600.0
            )

            # Active stimulus vs latched maintenance/fault.
            anomaly_active = (
                machine.forced_load_percent
                is not None
                and not machine.faulted
                and not machine.maintenance_mode
                and not machine.maintenance_required
            )

            fault_code = (
                machine.fault_reason
                if machine.faulted
                else "NONE"
            )

            # ------------------------------------------------
            # TELEMETRY
            # ------------------------------------------------

            row = {

                "timestamp":
                    int(now),

                "machine_id":
                    machine.machine_id,

                "power_kw":
                    round(
                        power,
                        2,
                    ),

                "energy_kwh":
                    round(
                        machine.energy_kwh,
                        3,
                    ),

                "load_percent":
                    round(
                        load_percent,
                        2,
                    ),

                "temperature":
                    round(
                        temperature,
                        2,
                    ),

                "vibration":
                    round(
                        vibration,
                        3,
                    ),

                "rpm":
                    machine.rpm,

                "production_rate":
                    round(
                        production_rate,
                        2,
                    ),

                "units_produced":
                    round(
                        units_produced,
                        4,
                    ),

                "state":
                    state,

                "criticality":
                    machine.criticality,

                "grid_stress_kw":
                    round(
                        self.grid_stress_kw,
                        2,
                    ),

                # Maintenance.
                "maintenance_mode":
                    machine.maintenance_mode,

                "maintenance_started_at":
                    round(
                        machine.maintenance_started_at,
                        3,
                    ),

                # Fault.
                "faulted":
                    machine.faulted,

                "fault_code":
                    fault_code,

                "fault_reason":
                    machine.fault_reason,

                "fault_timestamp":
                    round(
                        machine.fault_timestamp,
                        3,
                    ),

                "damage_level":
                    round(
                        machine.damage_level,
                        3,
                    ),

                # Maintenance requirement.
                "maintenance_required":
                    machine.maintenance_required,

                # 6/8 persistence telemetry.
                "persistence_count":
                    machine.persistence_count,

                "persistence_window":
                    self.ANOMALY_WINDOW_SIZE,

                "persistence_threshold":
                    self.ANOMALY_PERSISTENCE_THRESHOLD,

                "persistence_ratio":
                    round(
                        machine.persistence_count
                        / self.ANOMALY_WINDOW_SIZE,
                        3,
                    ),

                "persistence_escalated":
                    machine.persistence_escalated,

                "escalation_state":
                    machine.escalation_state,

                # Anomaly.
                "anomaly":
                    anomaly_active,

                "anomaly_type":
                    machine.anomaly_type,

                "anomaly_severity":
                    machine.anomaly_severity,

                "anomaly_started_at":
                    round(
                        machine.anomaly_started_at,
                        3,
                    ),

                "anomaly_source":
                    machine.anomaly_source,

                "manual_anomaly_active":
                    machine.manual_anomaly_active,

                # Scenario.
                "scenario_id":
                    self.active_scenario_id,

                "scenario_type":
                    self.active_scenario_type,
            }

            message = String()

            message.data = json.dumps(
                row
            )

            self.state_pub.publish(
                message
            )

        # ----------------------------------------------------
        # TOTAL FACTORY POWER
        # ----------------------------------------------------

        total_message = Float64()

        total_message.data = float(
            total_power
        )

        self.total_power_pub.publish(
            total_message
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    rclpy.init()

    node = FactoryTwinNode()

    try:

        rclpy.spin(
            node
        )

    except KeyboardInterrupt:

        pass

    finally:

        node.destroy_node()

        if rclpy.ok():

            rclpy.shutdown()


if __name__ == "__main__":

    main()
