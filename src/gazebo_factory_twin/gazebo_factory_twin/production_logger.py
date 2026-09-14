import csv
import json
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class ProductionLogger(Node):

    def __init__(self):
        super().__init__("production_logger")

        self.csv_path = os.path.expanduser(
            "~/INDUS_TWIN/data/02_operations/production_data.csv"
        )

        self.fields = [
            "timestamp",
            "production_line",
            "machine_id",
            "product_id",
            "target_units",
            "actual_units",
            "cycle_time_sec",
            "downtime_sec",
            "defect_count",
            "quality_percent"
        ]

        os.makedirs(
            os.path.dirname(self.csv_path),
            exist_ok=True
        )

        self.latest = {}
        self.last_write_minute = None

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

        self.subscription = self.create_subscription(
            String,
            "/factory/machine_state",
            self.telemetry_callback,
            20
        )

        self.timer = self.create_timer(
            1.0,
            self.check_write
        )

        self.get_logger().info(
            f"Logging production data every minute to "
            f"{self.csv_path}"
        )

    def telemetry_callback(self, message):
        try:
            data = json.loads(message.data)

            self.latest[data["machine_id"]] = data

        except (
            json.JSONDecodeError,
            KeyError,
            TypeError
        ) as error:

            self.get_logger().error(
                f"Invalid telemetry: {error}"
            )

    def check_write(self):

        current_minute = int(
            time.time() // 60
        )

        if self.last_write_minute is None:
            self.last_write_minute = current_minute
            return

        if current_minute != self.last_write_minute:

            timestamp = int(time.time())

            for machine_id, data in self.latest.items():

                production_rate = float(
                    data.get(
                        "production_rate",
                        0.0
                    )
                )

                units_produced = float(
                    data.get(
                        "units_produced",
                        0.0
                    )
                )

                power = float(
                    data.get(
                        "power_kw",
                        0.0
                    )
                )

                nominal_rate = max(
                    production_rate,
                    0.001
                )

                cycle_time = (
                    3600.0
                    / nominal_rate
                )

                load_percent = float(
                    data.get(
                        "load_percent",
                        100.0
                    )
                )

                downtime = 0.0

                if data.get("state") == "REDUCED":
                    downtime = 0.0

                target_units = round(
                    production_rate,
                    2
                )

                actual_units = round(
                    production_rate,
                    2
                )

                defect_count = 0

                quality_percent = 100.0

                if load_percent > 110.0:

                    defect_count = 1
                    quality_percent = 98.0

                elif load_percent > 100.0:

                    quality_percent = 99.0

                if production_rate <= 0.0:

                    actual_units = 0.0
                    quality_percent = 100.0

                row = {
                    "timestamp": timestamp,
                    "production_line": "LINE_01"
                    if machine_id not in [
                        "COMP_01",
                        "PUMP_01",
                        "HVAC_01"
                    ]
                    else "UTILITY",

                    "machine_id": machine_id,

                    "product_id": "PRODUCT_A",

                    "target_units": target_units,

                    "actual_units": actual_units,

                    "cycle_time_sec": round(
                        cycle_time,
                        2
                    ),

                    "downtime_sec": round(
                        downtime,
                        2
                    ),

                    "defect_count": defect_count,

                    "quality_percent": quality_percent
                }

                self.writer.writerow(row)

            self.file.flush()

            self.get_logger().info(
                f"Wrote {len(self.latest)} production records"
            )

            self.last_write_minute = current_minute

    def destroy_node(self):

        self.file.close()

        super().destroy_node()

def main():

    rclpy.init()

    node = ProductionLogger()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()