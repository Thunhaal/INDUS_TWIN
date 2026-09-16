from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node


class AIEngineNode(Node):

    def __init__(self):
        super().__init__("ai_engine")

        # ====================================================
        # PROJECT PATHS
        # ====================================================

        self.project_dir = Path.home() / "INDUS_TWIN"

        self.pipeline = (
            self.project_dir
            / "ai_engine"
            / "run_pipeline.py"
        )

        # IMPORTANT:
        # Always use the project's virtual environment rather
        # than the system Python used by ROS 2.
        self.venv_python = (
            self.project_dir
            / ".venv"
            / "bin"
            / "python3"
        )

        # Fallback only if the venv executable doesn't exist.
        if self.venv_python.exists():
            self.python = str(self.venv_python)
        else:
            self.python = sys.executable

        # Run pipeline every 10 seconds.
        self.interval_sec = 10.0

        self.running = False

        self.timer = self.create_timer(
            self.interval_sec,
            self.run_pipeline
        )

        self.get_logger().info(
            "AI Engine started"
        )

        self.get_logger().info(
            f"Pipeline: {self.pipeline}"
        )

        self.get_logger().info(
            f"Python: {self.python}"
        )

        self.get_logger().info(
            f"Update interval: "
            f"{self.interval_sec:.0f} seconds"
        )

        # Run once immediately.
        self.run_pipeline()

    def run_pipeline(self):

        if self.running:
            self.get_logger().warning(
                "Previous AI pipeline is still running. "
                "Skipping this cycle."
            )
            return

        if not self.pipeline.exists():
            self.get_logger().error(
                f"Pipeline not found: {self.pipeline}"
            )
            return

        if not Path(self.python).exists():
            self.get_logger().error(
                f"Python interpreter not found: "
                f"{self.python}"
            )
            return

        self.running = True

        start = time.time()

        self.get_logger().info(
            "Running AI pipeline..."
        )

        try:

            result = subprocess.run(
                [
                    self.python,
                    str(self.pipeline)
                ],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=60
            )

            # ----------------------------------------------
            # PIPELINE OUTPUT
            # ----------------------------------------------

            if result.stdout:
                self.get_logger().info(
                    result.stdout
                )

            if result.stderr:
                self.get_logger().warning(
                    result.stderr
                )

            # ----------------------------------------------
            # RESULT
            # ----------------------------------------------

            if result.returncode == 0:

                elapsed = (
                    time.time()
                    - start
                )

                self.get_logger().info(
                    f"AI pipeline completed "
                    f"in {elapsed:.2f}s"
                )

            else:

                self.get_logger().error(
                    f"AI pipeline failed "
                    f"with return code "
                    f"{result.returncode}"
                )

        except subprocess.TimeoutExpired:

            self.get_logger().error(
                "AI pipeline exceeded "
                "60-second timeout."
            )

        except Exception as exc:

            self.get_logger().error(
                f"Could not execute AI pipeline: "
                f"{exc}"
            )

        finally:

            self.running = False


def main():

    rclpy.init()

    node = AIEngineNode()

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