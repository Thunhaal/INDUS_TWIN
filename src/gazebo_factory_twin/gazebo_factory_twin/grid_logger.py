from __future__ import annotations

import csv
import json
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64, String


class GridLogger(Node):

    def __init__(self):
        super().__init__("grid_logger")

        self.csv_path = os.path.expanduser(
            "~/INDUS_TWIN/data/04_grid/grid_data.csv"
        )

        self.fields = [
            "timestamp",
            "grid_status",
            "available_grid_power_kw",
            "factory_demand_kw",
            "grid_import_limit_kw",
            "grid_stress_level",
            "required_reduction_kw",
            "grid_frequency_hz",
            "grid_voltage_v",
            "solar_available_kw",
            "solar_forecast_kw",
            "battery_soc_percent",
            "battery_available_power_kw",
            "electricity_tariff_rs_kwh"
        ]

        os.makedirs(
            os.path.dirname(self.csv_path),
            exist_ok=True
        )

        self.file = open(
            self.csv_path,
            "a",
            newline="",
            buffering=1
        )

        self.writer = csv.DictWriter(
            self.file,
            fieldnames=self.fields
        )

        if os.path.getsize(self.csv_path) == 0:
            self.writer.writeheader()

        self.latest_factory_demand = 0.0

        # Default scenario
        self.active_scenario = {
            "scenario_id": "NORMAL",
            "scenario_name": "Normal Operation",
            "scenario_type": "NORMAL",
            "grid_available_power_kw": 250.0,
            "solar_available_power_kw": 15.0,
            "required_reduction_kw": 0.0,
            "minimum_production_percent": 95.0,
            "battery_available_kwh": 100.0
        }

        self.last_write_minute = None

        # Factory demand
        self.power_subscription = self.create_subscription(
            Float64,
            "/factory/total_power_kw",
            self.factory_power_callback,
            10
        )

        # Active scenario
        self.scenario_subscription = self.create_subscription(
            String,
            "/factory/scenario",
            self.scenario_callback,
            10
        )

        self.timer = self.create_timer(
            1.0,
            self.check_write
        )

        self.get_logger().info(
            f"Grid logger started: {self.csv_path}"
        )

    def factory_power_callback(self, message: Float64):
        self.latest_factory_demand = max(
            0.0,
            float(message.data)
        )

    def scenario_callback(self, message: String):

        try:
            data = json.loads(message.data)

            # Only accept scenario updates that contain an ID.
            if not data.get("scenario_id"):
                return

            self.active_scenario = data

            self.get_logger().info(
                f"Scenario updated: "
                f"{data.get('scenario_id')} | "
                f"type={data.get('scenario_type')} | "
                f"required_reduction="
                f"{float(data.get('required_reduction_kw', 0.0)):.2f} kW"
            )

        except (
            json.JSONDecodeError,
            TypeError,
            ValueError
        ) as error:

            self.get_logger().error(
                f"Invalid scenario message: {error}"
            )

    def calculate_grid_state(self):

        scenario = self.active_scenario

        factory_demand = max(
            0.0,
            float(self.latest_factory_demand)
        )

        available_grid_power = max(
            0.0,
            float(
                scenario.get(
                    "grid_available_power_kw",
                    250.0
                )
                or 0.0
            )
        )

        required_reduction = max(
            0.0,
            float(
                scenario.get(
                    "required_reduction_kw",
                    0.0
                )
                or 0.0
            )
        )

        solar_available = max(
            0.0,
            float(
                scenario.get(
                    "solar_available_power_kw",
                    0.0
                )
                or 0.0
            )
        )

        battery_available_kwh = max(
            0.0,
            float(
                scenario.get(
                    "battery_available_kwh",
                    0.0
                )
                or 0.0
            )
        )

        scenario_type = str(
            scenario.get(
                "scenario_type",
                "NORMAL"
            )
        ).upper()

        # --------------------------------------------------
        # Physical grid stress
        # --------------------------------------------------

        if available_grid_power <= 0.0:
            demand_ratio = 1.0
        else:
            demand_ratio = (
                factory_demand
                / available_grid_power
            )

        if demand_ratio >= 1.0:
            stress = 1.0
        elif demand_ratio >= 0.90:
            stress = 0.75
        elif demand_ratio >= 0.80:
            stress = 0.50
        else:
            stress = 0.0

        # --------------------------------------------------
        # Scenario-driven stress
        # --------------------------------------------------

        if scenario_type == "GRID_STRESS":
            stress = max(stress, 0.75)

        elif scenario_type == "PEAK_DEMAND":
            stress = max(stress, 0.75)

        elif scenario_type == "CRITICAL_GRID":
            stress = 1.0

        elif scenario_type == "LOW_RENEWABLE":
            stress = max(stress, 0.25)

        # A scenario requesting a reduction means the grid
        # response requirement is active.
        if required_reduction > 0.0:
            stress = max(stress, 0.75)

        # --------------------------------------------------
        # Grid status
        # --------------------------------------------------

        if stress >= 1.0:
            grid_status = "CRITICAL"
        elif stress >= 0.75:
            grid_status = "STRESSED"
        elif stress >= 0.50:
            grid_status = "WARNING"
        else:
            grid_status = "NORMAL"

        # --------------------------------------------------
        # Prototype electrical conditions
        # --------------------------------------------------

        if grid_status == "CRITICAL":
            frequency = 49.75
            voltage = 405.0

        elif grid_status == "STRESSED":
            frequency = 49.85
            voltage = 410.0

        elif grid_status == "WARNING":
            frequency = 49.95
            voltage = 412.0

        else:
            frequency = 50.00
            voltage = 415.0

        # --------------------------------------------------
        # Tariff
        # --------------------------------------------------

        hour = time.localtime().tm_hour

        if 18 <= hour < 22:
            tariff = 10.50
        elif 6 <= hour < 18:
            tariff = 7.50
        else:
            tariff = 5.50

        # --------------------------------------------------
        # Battery
        # --------------------------------------------------

        battery_available_power = min(
            20.0,
            battery_available_kwh
        )

        # --------------------------------------------------
        # Important:
        #
        # required_reduction_kw comes directly from the active
        # scenario. It is NOT inferred from stress.
        # --------------------------------------------------

        return {
            "grid_status": grid_status,
            "available_grid_power_kw": available_grid_power,
            "factory_demand_kw": factory_demand,
            "grid_import_limit_kw": 250.0,
            "grid_stress_level": stress,
            "required_reduction_kw": required_reduction,
            "grid_frequency_hz": frequency,
            "grid_voltage_v": voltage,
            "solar_available_kw": solar_available,
            "solar_forecast_kw": solar_available,
            "battery_soc_percent": 80.0,
            "battery_available_power_kw": battery_available_power,
            "electricity_tariff_rs_kwh": tariff
        }

    def check_write(self):

        current_minute = int(
            time.time() // 60
        )

        if self.last_write_minute is None:
            self.last_write_minute = current_minute
            return

        if current_minute == self.last_write_minute:
            return

        grid = self.calculate_grid_state()

        row = {
            "timestamp": int(time.time()),
            **grid
        }

        self.writer.writerow(row)
        self.file.flush()

        self.get_logger().info(
            f"GRID: "
            f"scenario={self.active_scenario.get('scenario_id')} | "
            f"status={grid['grid_status']} | "
            f"demand={grid['factory_demand_kw']:.2f} kW | "
            f"available={grid['available_grid_power_kw']:.2f} kW | "
            f"required_reduction={grid['required_reduction_kw']:.2f} kW | "
            f"stress={grid['grid_stress_level']:.2f}"
        )

        self.last_write_minute = current_minute

    def destroy_node(self):
        try:
            self.file.close()
        except Exception:
            pass

        super().destroy_node()


def main():

    rclpy.init()

    node = GridLogger()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()