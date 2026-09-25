#!/usr/bin/env python3

"""
INDUS_TWIN Production Logger

Purpose
-------
Create a clean production history from /factory/machine_state.

Finished-product machines:
    CNC_01
    CNC_02
    CNC_03

Process / utility assets:
    FURNACE_01
    COMP_01
    PUMP_01
    HVAC_01

The logger writes one snapshot for each of the seven machines every
10 seconds.

Important:
- Utility/process assets are not counted as finished-product output.
- Only CNC machines generate PRODUCT_A production records.
- Production data keeps the same 10-column CSV schema used by the
  production-quality analytics engine.
"""


import csv
import json
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


# ============================================================================
# CURRENT FACTORY
# ============================================================================

ALL_MACHINES = [
    "CNC_01",
    "CNC_02",
    "CNC_03",
    "COMP_01",
    "PUMP_01",
    "HVAC_01",
    "FURNACE_01",
]


FINISHED_PRODUCT_MACHINES = {
    "CNC_01",
    "CNC_02",
    "CNC_03",
}


UTILITY_MACHINES = {
    "COMP_01",
    "PUMP_01",
    "HVAC_01",
}


PROCESS_MACHINES = {
    "FURNACE_01",
}


PRODUCTION_LINE = {
    "CNC_01": "LINE_01",
    "CNC_02": "LINE_01",
    "CNC_03": "LINE_01",
    "FURNACE_01": "LINE_01",
    "COMP_01": "UTILITY",
    "PUMP_01": "UTILITY",
    "HVAC_01": "UTILITY",
}


PRODUCT_ID = {
    "CNC_01": "PRODUCT_A",
    "CNC_02": "PRODUCT_A",
    "CNC_03": "PRODUCT_A",
}


# ============================================================================
# NODE
# ============================================================================

class ProductionLogger(Node):

    def __init__(self):

        super().__init__(
            "production_logger"
        )


        # ====================================================================
        # PATH
        # ====================================================================

        self.csv_path = os.path.expanduser(
            "~/INDUS_TWIN/data/02_operations/production_data.csv"
        )


        os.makedirs(
            os.path.dirname(
                self.csv_path
            ),
            exist_ok=True,
        )


        # ====================================================================
        # CSV SCHEMA
        # ====================================================================

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
            "quality_percent",
        ]


        # ====================================================================
        # TIMING
        # ====================================================================

        self.write_interval_sec = 10.0

        self.last_write_time = 0.0


        # ====================================================================
        # LIVE TELEMETRY CACHE
        # ====================================================================

        self.latest = {}

        # Per-machine planning target.  The first healthy RUNNING rate
        # establishes a baseline target with a 5% planning margin.  The
        # target is then held constant so downtime/anomalies reduce ACTUAL
        # output instead of silently reducing the target as well.
        self.target_rate_by_machine = {}


        # ====================================================================
        # OPEN FILE
        # ====================================================================

        file_exists = os.path.exists(
            self.csv_path
        )

        file_empty = (
            not file_exists
            or os.path.getsize(
                self.csv_path
            ) == 0
        )


        self.file = open(
            self.csv_path,
            "a",
            newline="",
            buffering=1,
        )


        self.writer = csv.DictWriter(
            self.file,
            fieldnames=self.fields,
        )


        if file_empty:

            self.writer.writeheader()

        else:

            self.validate_existing_header()


        # ====================================================================
        # ROS SUBSCRIBER
        # ====================================================================

        self.subscription = self.create_subscription(
            String,
            "/factory/machine_state",
            self.telemetry_callback,
            50,
        )


        # ====================================================================
        # TIMER
        # ====================================================================

        self.timer = self.create_timer(
            1.0,
            self.check_write,
        )


        # ====================================================================
        # STARTUP MESSAGE
        # ====================================================================

        self.get_logger().info(
            "=========================================="
        )

        self.get_logger().info(
            "INDUS_TWIN PRODUCTION LOGGER STARTED"
        )

        self.get_logger().info(
            f"Output: {self.csv_path}"
        )

        self.get_logger().info(
            "Source: /factory/machine_state"
        )

        self.get_logger().info(
            "Finished production machines: "
            + ", ".join(
                sorted(
                    FINISHED_PRODUCT_MACHINES
                )
            )
        )

        self.get_logger().info(
            "Utility machines: "
            + ", ".join(
                sorted(
                    UTILITY_MACHINES
                )
            )
        )

        self.get_logger().info(
            "Process machines: "
            + ", ".join(
                sorted(
                    PROCESS_MACHINES
                )
            )
        )

        self.get_logger().info(
            f"Write interval: "
            f"{self.write_interval_sec:.0f} seconds"
        )

        self.get_logger().info(
            "=========================================="
        )


    # ========================================================================
    # CSV HEADER VALIDATION
    # ========================================================================

    def validate_existing_header(self):

        try:

            with open(
                self.csv_path,
                "r",
                newline="",
                encoding="utf-8",
            ) as existing_file:

                reader = csv.reader(
                    existing_file
                )

                header = next(
                    reader,
                    None
                )


            if header != self.fields:

                self.get_logger().error(
                    "Existing production CSV header "
                    "does not match the expected schema."
                )

                self.get_logger().error(
                    f"Expected: {self.fields}"
                )

                self.get_logger().error(
                    f"Found:    {header}"
                )

                self.get_logger().error(
                    "Please repair/replace the CSV before "
                    "starting the production logger."
                )

        except Exception as error:

            self.get_logger().error(
                f"Could not validate production CSV: "
                f"{error}"
            )


    # ========================================================================
    # TELEMETRY CALLBACK
    # ========================================================================

    def telemetry_callback(
        self,
        message,
    ):

        try:

            data = json.loads(
                message.data
            )


            machine_id = str(
                data["machine_id"]
            ).strip()


            if machine_id not in ALL_MACHINES:

                return


            self.latest[
                machine_id
            ] = data


        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
        ) as error:

            self.get_logger().error(
                f"Invalid telemetry message: "
                f"{error}"
            )


    # ========================================================================
    # PRODUCTION VALUE HELPERS
    # ========================================================================

    def get_numeric(
        self,
        data,
        key,
        default=0.0,
    ):

        try:

            value = float(
                data.get(
                    key,
                    default,
                )
                or default
            )


            return value


        except (
            TypeError,
            ValueError,
        ):

            return default


    # ========================================================================
    # BUILD RECORD
    # ========================================================================

    def build_record(
        self,
        machine_id,
        data,
        timestamp,
    ):

        state = str(
            data.get(
                "state",
                "RUNNING",
            )
        ).strip().upper()


        production_rate = max(
            0.0,
            self.get_numeric(
                data,
                "production_rate",
                0.0,
            ),
        )


        load_percent = self.get_numeric(
            data,
            "load_percent",
            0.0,
        )


        # ====================================================================
        # DEFAULTS
        # ====================================================================

        production_line = PRODUCTION_LINE.get(
            machine_id,
            "UTILITY",
        )


        product_id = ""


        target_units = 0.0

        actual_units = 0.0

        cycle_time_sec = 0.0

        downtime_sec = 0.0

        defect_count = 0

        quality_percent = 100.0


        # ====================================================================
        # FINISHED-PRODUCT MACHINES
        # ====================================================================

        if machine_id in FINISHED_PRODUCT_MACHINES:

            product_id = PRODUCT_ID.get(
                machine_id,
                "PRODUCT_A",
            )


            # The factory telemetry production_rate is an instantaneous
            # production rate in units/hour.  Keep a planning target that is
            # established from the first healthy RUNNING observation and
            # held constant across later snapshots.
            if (
                machine_id not in self.target_rate_by_machine
                and production_rate > 0.0
                and state == "RUNNING"
            ):
                self.target_rate_by_machine[machine_id] = (
                    production_rate / 0.95
                )

            target_rate = self.target_rate_by_machine.get(
                machine_id,
                (production_rate / 0.95) if production_rate > 0.0 else 0.0,
            )

            target_units = round(
                target_rate,
                2,
            )

            actual_units = round(
                production_rate,
                2,
            )


            # Production cycle time in seconds.
            if production_rate > 0.0:

                cycle_time_sec = (
                    3600.0
                    / production_rate
                )

            else:

                cycle_time_sec = 0.0


            # A non-producing CNC is treated as production downtime.
            if (
                production_rate <= 0.0
                or state in {
                    "IDLE",
                    "FAULT",
                    "MAINTENANCE",
                    "STOPPED",
                }
            ):

                downtime_sec = (
                    self.write_interval_sec
                )


            # ---------------------------------------------------------------
            # PRODUCTION QUALITY MODEL
            # ---------------------------------------------------------------
            #
            # The production model includes a small, deterministic scrap rate
            # during normal manufacturing instead of reporting perfect
            # 100% quality.  CNC machines use staggered baseline defect rates
            # of 5.5%, 6.5% and 7.5%, producing an overall factory quality
            # around 93-94% under normal operation.
            #
            # Abnormal loading increases the defect rate so the demo can show
            # a visible quality impact when an anomaly is injected.
            #
            if production_rate > 0.0:

                base_defect_rates = {
                    "CNC_01": 0.055,
                    "CNC_02": 0.065,
                    "CNC_03": 0.075,
                }

                base_rate = base_defect_rates.get(
                    machine_id,
                    0.065,
                )

                if load_percent > 110.0:
                    defect_rate = min(
                        0.12,
                        base_rate + 0.05,
                    )
                elif load_percent > 100.0:
                    defect_rate = min(
                        0.10,
                        base_rate + 0.025,
                    )
                else:
                    defect_rate = base_rate

                defect_count = max(
                    1,
                    int(
                        round(
                            actual_units * defect_rate
                        )
                    ),
                )

                defect_count = min(
                    defect_count,
                    int(actual_units),
                )

                quality_percent = (
                    (
                        max(
                            0.0,
                            actual_units - defect_count,
                        )
                        / actual_units
                    )
                    * 100.0
                )

            else:

                defect_count = 0
                quality_percent = 100.0


        # ====================================================================
        # FURNACE
        # ====================================================================

        elif machine_id in PROCESS_MACHINES:

            # Furnace is a process stage, not a finished-product producer.
            #
            # It stays in the production-line view but contributes:
            #     completed = 0
            #     rejected = 0
            #
            # This prevents OEE from treating heating-process telemetry as
            # completed PRODUCT_A parts.
            production_line = "LINE_01"

            product_id = ""

            target_units = 0.0

            actual_units = 0.0

            cycle_time_sec = 0.0

            downtime_sec = 0.0

            defect_count = 0

            quality_percent = 100.0


        # ====================================================================
        # UTILITY MACHINES
        # ====================================================================

        elif machine_id in UTILITY_MACHINES:

            production_line = "UTILITY"

            product_id = ""

            target_units = 0.0

            actual_units = 0.0

            cycle_time_sec = 0.0

            # Utility downtime is not manufacturing downtime.
            downtime_sec = 0.0

            defect_count = 0

            quality_percent = 100.0


        # ====================================================================
        # FINAL ROW
        # ====================================================================

        return {
            "timestamp":
                timestamp,

            "production_line":
                production_line,

            "machine_id":
                machine_id,

            "product_id":
                product_id,

            "target_units":
                target_units,

            "actual_units":
                actual_units,

            "cycle_time_sec":
                round(
                    cycle_time_sec,
                    4,
                ),

            "downtime_sec":
                round(
                    downtime_sec,
                    2,
                ),

            "defect_count":
                defect_count,

            "quality_percent":
                round(
                    quality_percent,
                    2,
                ),
        }


    # ========================================================================
    # WRITE DATA
    # ========================================================================

    def check_write(self):

        now = time.time()


        if (
            self.last_write_time > 0.0
            and
            now - self.last_write_time
            <
            self.write_interval_sec
        ):

            return


        if not self.latest:

            return


        timestamp = int(
            now
        )


        records_written = 0


        # Always write in stable factory order.
        for machine_id in ALL_MACHINES:

            data = self.latest.get(
                machine_id
            )


            if data is None:

                continue


            row = self.build_record(
                machine_id,
                data,
                timestamp,
            )


            self.writer.writerow(
                row
            )


            records_written += 1


        if records_written > 0:

            self.last_write_time = now


            self.get_logger().info(
                f"Production snapshot written: "
                f"{records_written}/"
                f"{len(ALL_MACHINES)} machines"
            )


    # ========================================================================
    # SHUTDOWN
    # ========================================================================

    def destroy_node(self):

        try:

            if hasattr(
                self,
                "file",
            ):

                self.file.flush()

                self.file.close()

        except Exception:
            pass


        super().destroy_node()


# ============================================================================
# MAIN
# ============================================================================

def main(args=None):

    rclpy.init(
        args=args
    )


    node = ProductionLogger()


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
