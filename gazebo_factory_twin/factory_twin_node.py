"""ROS 2 telemetry/control model for the Gazebo factory scene.

It uses JSON in std_msgs/String deliberately: each team member can consume the
fixed contract without installing custom message packages.
"""
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
    reduce_until: float = 0.0


class FactoryTwinNode(Node):
    def __init__(self) -> None:
        super().__init__("factory_twin")
        self.state_pub = self.create_publisher(String, "/factory/machine_state", 20)
        self.total_power_pub = self.create_publisher(Float64, "/factory/total_power_kw", 10)
        self.event_pub = self.create_publisher(String, "/factory/events", 10)
        self.create_subscription(String, "/factory/control_command", self.on_command, 20)
        self.create_subscription(Float64, "/factory/grid_stress_kw", self.on_grid_stress, 10)
        self.timer = self.create_timer(1.0, self.publish_snapshot)
        self.step = 0
        self.grid_stress_kw = 0.0
        self.last_time = time.time()
        self.machines = [
            Machine("CNC_01", 28, 26, 22, "HIGH", 49, .15, 2400),
            Machine("COMP_01", 50, 35, 18, "MEDIUM", 71, .32, 1450),
            Machine("PUMP_01", 18, 13, 12, "LOW", 53, .20, 1800),
            Machine("HVAC_01", 35, 27, 0, "LOW", 24, .04, 900),
            Machine("FURNACE_01", 78, 78, 16, "CRITICAL", 840, .11, 1200),
        ]
        self.emit_event("Factory digital twin online: publishing five machines")

    def emit_event(self, text: str) -> None:
        message = String(); message.data = json.dumps({"timestamp": int(time.time()), "event": text})
        self.event_pub.publish(message); self.get_logger().info(text)

    def on_grid_stress(self, message: Float64) -> None:
        self.grid_stress_kw = max(0.0, message.data)
        self.emit_event(f"GRID_STRESS: requested {self.grid_stress_kw:.1f} kW reduction")

    def on_command(self, message: String) -> None:
        """Accept: {machine_id, command: REDUCE_LOAD, target_kw, duration_sec}."""
        try:
            command = json.loads(message.data)
            machine = next(m for m in self.machines if m.machine_id == command["machine_id"])
            if command.get("command") != "REDUCE_LOAD":
                raise ValueError("only REDUCE_LOAD is supported")
            target = float(command["target_kw"])
            machine.reduction_kw = min(machine.nominal_kw - machine.min_kw, max(0.0, machine.nominal_kw - target))
            machine.reduce_until = time.time() + max(1, int(command.get("duration_sec", 900)))
            self.emit_event(f"CONTROL_APPLIED: {machine.machine_id} reduced by {machine.reduction_kw:.1f} kW")
        except (KeyError, ValueError, TypeError, json.JSONDecodeError, StopIteration) as error:
            self.emit_event(f"CONTROL_REJECTED: {error}")

    def publish_snapshot(self) -> None:
        now = time.time(); elapsed = now - self.last_time; self.last_time = now; self.step += 1
        total = 0.0
        for index, machine in enumerate(self.machines):
            if machine.reduce_until <= now:
                machine.reduction_kw = 0.0
            wave = math.sin((self.step + index * 3) / 3) * (1.8 if machine.machine_id != "FURNACE_01" else .6)
            inefficient = 7.0 if machine.machine_id == "COMP_01" and self.step % 45 in range(30, 37) else 0.0
            power = max(machine.min_kw if machine.reduction_kw else 0.0, machine.nominal_kw + wave + inefficient - machine.reduction_kw)
            machine.energy_kwh += power * elapsed / 3600
            row = {"timestamp": int(now), "machine_id": machine.machine_id, "power_kw": round(power, 2), "energy_kwh": round(machine.energy_kwh, 3), "temperature": round(machine.temperature + wave*.4 + inefficient*.25, 2), "vibration": round(machine.vibration + abs(wave)*.006 + inefficient*.012, 3), "rpm": machine.rpm, "production_rate": round(machine.production_rate * (1 - machine.reduction_kw / max(machine.nominal_kw, 1) * .25), 2), "state": "REDUCED" if machine.reduction_kw else "RUNNING", "criticality": machine.criticality, "grid_stress_kw": self.grid_stress_kw}
            msg = String(); msg.data = json.dumps(row); self.state_pub.publish(msg); total += power
        total_msg = Float64(); total_msg.data = total; self.total_power_pub.publish(total_msg)


def main() -> None:
    rclpy.init(); node = FactoryTwinNode()
    try: rclpy.spin(node)
    except KeyboardInterrupt: pass
    finally: node.destroy_node(); rclpy.shutdown()
