import csv
import json
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TelemetryLogger(Node):

    def __init__(self):
        super().__init__("telemetry_logger")

        self.csv_path = os.path.expanduser(
            "~/INDUS_TWIN/data/02_operations/machine_telemetry.csv"
        )

        self.fields = [
            "timestamp",
            "machine_id",
            "state",
            "power_kw",
            "energy_kwh",
            "load_percent",
            "temperature_c",
            "vibration_mm_s",
            "rpm",
            "production_rate",
            "units_produced"
        ]

        os.makedirs(os.path.dirname(self.csv_path), exist_ok=True)

        self.latest = {}
        self.last_write_minute = None

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

        self.get_logger().info(
            f"Logging telemetry every minute to {self.csv_path}"
        )

    def telemetry_callback(self, message):
        try:
            data = json.loads(message.data)

            self.latest[data["machine_id"]] = data

        except (json.JSONDecodeError, KeyError, TypeError) as error:
            self.get_logger().error(
                f"Invalid telemetry: {error}"
            )

    def check_write(self):
        current_minute = int(time.time() // 60)

        if self.last_write_minute is None:
            self.last_write_minute = current_minute
            return

        if current_minute != self.last_write_minute:

            timestamp = int(time.time())

            for machine_id, data in self.latest.items():

                row = {
                    "timestamp": timestamp,
                    "machine_id": machine_id,
                    "state": data.get("state"),
                    "power_kw": data.get("power_kw"),
                    "energy_kwh": data.get("energy_kwh"),
                    "load_percent": data.get("load_percent"),
                    "temperature_c": data.get("temperature"),
                    "vibration_mm_s": data.get("vibration"),
                    "rpm": data.get("rpm"),
                    "production_rate": data.get("production_rate"),
                    "units_produced": data.get("units_produced")
                }

                self.writer.writerow(row)

            self.file.flush()

            self.get_logger().info(
                f"Wrote {len(self.latest)} machine records"
            )

            self.last_write_minute = current_minute

    def destroy_node(self):
        self.file.close()
        super().destroy_node()


def main():
    rclpy.init()

    node = TelemetryLogger()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
