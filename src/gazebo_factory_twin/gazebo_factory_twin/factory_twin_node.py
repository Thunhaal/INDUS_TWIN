from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass

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
    energy_kwh: float = 0.0
    reduction_kw: float = 0.0
    load_adjustment_kw: float = 0.0
    reduce_until: float = 0.0


class FactoryTwinNode(Node):

    def __init__(self) -> None:
        super().__init__("factory_twin")

        self.state_pub = self.create_publisher(
            String,
            "/factory/machine_state",
            20
        )

        self.total_power_pub = self.create_publisher(
            Float64,
            "/factory/total_power_kw",
            10
        )

        self.event_pub = self.create_publisher(
            String,
            "/factory/events",
            10
        )

        self.create_subscription(
            String,
            "/factory/control_command",
            self.on_command,
            20
        )

        self.create_subscription(
            Float64,
            "/factory/grid_stress_kw",
            self.on_grid_stress,
            10
        )

        self.timer = self.create_timer(
            1.0,
            self.publish_snapshot
        )

        self.step = 0
        self.grid_stress_kw = 0.0
        self.last_time = time.time()

        self.machines = [
            Machine(
                "CNC_01",
                28,
                20,
                22,
                "HIGH",
                49,
                0.15,
                2400
            ),
            Machine(
                "CNC_02",
                30,
                20,
                23,
                "HIGH",
                51,
                0.16,
                2350
            ),
            Machine(
                "CNC_03",
                26,
                19,
                21,
                "MEDIUM",
                48,
                0.14,
                2450
            ),
            Machine(
                "COMP_01",
                50,
                35,
                18,
                "MEDIUM",
                71,
                0.32,
                1450
            ),
            Machine(
                "PUMP_01",
                18,
                13,
                12,
                "LOW",
                53,
                0.20,
                1800
            ),
            Machine(
                "HVAC_01",
                35,
                27,
                0,
                "LOW",
                24,
                0.04,
                900
            ),
            Machine(
                "FURNACE_01",
                78,
                78,
                16,
                "CRITICAL",
                840,
                0.11,
                1200
            )
        ]

        self.emit_event(
            "Factory digital twin online: publishing seven machines"
        )

    def emit_event(self, text: str) -> None:
        message = String()

        message.data = json.dumps({
            "timestamp": int(time.time()),
            "event": text
        })

        self.event_pub.publish(message)
        self.get_logger().info(text)

    def on_grid_stress(self, message: Float64) -> None:
        self.grid_stress_kw = max(
            0.0,
            message.data
        )

        self.emit_event(
            f"GRID_STRESS: requested "
            f"{self.grid_stress_kw:.1f} kW reduction"
        )

    def on_command(self, message: String) -> None:

        try:
            command = json.loads(message.data)

            machine = next(
                m for m in self.machines
                if m.machine_id == command["machine_id"]
            )

            command_type = command.get("command")

            # --------------------------------------------------
            # REDUCE_LOAD
            # Used later by the optimization/control layer.
            # --------------------------------------------------
            if command_type == "REDUCE_LOAD":

                target = float(
                    command["target_kw"]
                )

                target = max(
                    machine.min_kw,
                    min(machine.nominal_kw, target)
                )

                machine.reduction_kw = (
                    machine.nominal_kw - target
                )

                machine.load_adjustment_kw = 0.0

                machine.reduce_until = (
                    time.time()
                    + max(
                        1,
                        int(
                            command.get(
                                "duration_sec",
                                900
                            )
                        )
                    )
                )

                self.emit_event(
                    f"CONTROL_APPLIED: "
                    f"{machine.machine_id} "
                    f"reduced by "
                    f"{machine.reduction_kw:.1f} kW"
                )

            # --------------------------------------------------
            # SET_LOAD
            # Used by the anomaly injector.
            # --------------------------------------------------
            elif command_type == "SET_LOAD":

                load_percent = float(
                    command["load_percent"]
                )

                load_percent = max(
                    0.0,
                    min(130.0, load_percent)
                )

                target_kw = (
                    machine.nominal_kw
                    * load_percent
                    / 100.0
                )

                machine.reduction_kw = 0.0

                machine.load_adjustment_kw = (
                    target_kw
                    - machine.nominal_kw
                )

                machine.reduce_until = (
                    time.time()
                    + max(
                        1,
                        int(
                            command.get(
                                "duration_sec",
                                60
                            )
                        )
                    )
                )

                self.emit_event(
                    f"ANOMALY_INJECTED: "
                    f"{machine.machine_id} "
                    f"set to "
                    f"{load_percent:.1f}% load"
                )

            # --------------------------------------------------
            # RESTORE_NORMAL
            # --------------------------------------------------
            elif command_type == "RESTORE_NORMAL":

                machine.reduction_kw = 0.0
                machine.load_adjustment_kw = 0.0
                machine.reduce_until = 0.0

                self.emit_event(
                    f"MACHINE_RESTORED: "
                    f"{machine.machine_id}"
                )

            else:

                raise ValueError(
                    f"Unsupported command: "
                    f"{command_type}"
                )

        except (
            KeyError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            StopIteration
        ) as error:

            self.emit_event(
                f"CONTROL_REJECTED: {error}"
            )

    def publish_snapshot(self) -> None:

        now = time.time()

        elapsed = (
            now - self.last_time
        )

        self.last_time = now
        self.step += 1

        total = 0.0

        for index, machine in enumerate(self.machines):

            # --------------------------------------------------
            # Restore machine after temporary command expires.
            # --------------------------------------------------
            if (
                machine.reduce_until > 0.0
                and machine.reduce_until <= now
            ):

                machine.reduction_kw = 0.0
                machine.load_adjustment_kw = 0.0
                machine.reduce_until = 0.0

                self.emit_event(
                    f"CONTROL_EXPIRED: "
                    f"{machine.machine_id}"
                )

            # --------------------------------------------------
            # Normal operating fluctuation.
            # --------------------------------------------------
            wave = math.sin(
                (self.step + index * 3) / 3.0
            ) * (
                1.8
                if machine.machine_id != "FURNACE_01"
                else 0.6
            )

            # --------------------------------------------------
            # Simulated compressor inefficiency event.
            # --------------------------------------------------
            inefficient = 0.0

            if (
                machine.machine_id == "COMP_01"
                and self.step % 45 in range(30, 37)
            ):
                inefficient = 7.0

            # --------------------------------------------------
            # Base machine power.
            # --------------------------------------------------
            power = (
                machine.nominal_kw
                + wave
                + inefficient
            )

            # --------------------------------------------------
            # Apply anomaly load adjustment.
            # Example:
            # 50 kW nominal machine at 110%
            # → +5 kW adjustment.
            # --------------------------------------------------
            power += machine.load_adjustment_kw

            # --------------------------------------------------
            # Apply load reduction.
            # --------------------------------------------------
            if machine.reduction_kw > 0.0:

                power -= machine.reduction_kw

                power = max(
                    machine.min_kw,
                    power
                )

            else:

                power = max(
                    0.0,
                    power
                )

            # --------------------------------------------------
            # Energy accumulation.
            # --------------------------------------------------
            machine.energy_kwh += (
                power
                * elapsed
                / 3600.0
            )

            # --------------------------------------------------
            # Load percentage.
            # --------------------------------------------------
            load_percent = (
                power
                / machine.nominal_kw
            ) * 100.0

            # --------------------------------------------------
            # Production impact.
            #
            # Overload itself does not immediately reduce
            # production. Reduced load does.
            # --------------------------------------------------
            production_rate = machine.production_rate

            if machine.reduction_kw > 0.0:

                production_rate *= (
                    1.0
                    - (
                        machine.reduction_kw
                        / max(
                            machine.nominal_kw,
                            1.0
                        )
                    )
                    * 0.25
                )

            # --------------------------------------------------
            # Units produced during this telemetry interval.
            # --------------------------------------------------
            units_produced = (
                production_rate
                * elapsed
                / 3600.0
            )

            # --------------------------------------------------
            # Simulated sensor response.
            # An overload increases temperature/vibration.
            # --------------------------------------------------
            overload_ratio = max(
                0.0,
                load_percent - 100.0
            ) / 100.0

            temperature = (
                machine.temperature
                + wave * 0.4
                + inefficient * 0.25
                + overload_ratio * 8.0
            )

            vibration = (
                machine.vibration
                + abs(wave) * 0.006
                + inefficient * 0.012
                + overload_ratio * 0.20
            )

            # --------------------------------------------------
            # Machine state.
            # --------------------------------------------------
            if machine.reduction_kw > 0.0:

                state = "REDUCED"

            elif machine.load_adjustment_kw > 0.0:

                state = "ANOMALY"

            else:

                state = "RUNNING"

            # --------------------------------------------------
            # Telemetry packet.
            # --------------------------------------------------
            row = {
                "timestamp": int(now),
                "machine_id": machine.machine_id,
                "power_kw": round(
                    power,
                    2
                ),
                "energy_kwh": round(
                    machine.energy_kwh,
                    3
                ),
                "load_percent": round(
                    load_percent,
                    2
                ),
                "temperature": round(
                    temperature,
                    2
                ),
                "vibration": round(
                    vibration,
                    3
                ),
                "rpm": machine.rpm,
                "production_rate": round(
                    production_rate,
                    2
                ),
                "units_produced": round(
                    units_produced,
                    4
                ),
                "state": state,
                "criticality": machine.criticality,
                "grid_stress_kw": round(
                    self.grid_stress_kw,
                    2
                )
            }

            message = String()

            message.data = json.dumps(row)

            self.state_pub.publish(
                message
            )

            total += power

        # ------------------------------------------------------
        # Publish total factory demand.
        # ------------------------------------------------------
        total_message = Float64()

        total_message.data = total

        self.total_power_pub.publish(
            total_message
        )


def main() -> None:

    rclpy.init()

    node = FactoryTwinNode()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
