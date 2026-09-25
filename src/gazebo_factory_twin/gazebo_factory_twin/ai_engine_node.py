#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


PROJECT_DIR = Path.home() / "INDUS_TWIN"

# Make the project-level ai_engine package importable when this ROS node
# is launched from the installed ROS workspace.
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    from ai_engine import control_safety
    CONTROL_SAFETY_AVAILABLE = True
except Exception as exc:
    control_safety = None
    CONTROL_SAFETY_AVAILABLE = False
    CONTROL_SAFETY_IMPORT_ERROR = str(exc)


class AIEngineNode(Node):

    AI_INTERVAL_SEC = 10.0
    PIPELINE_TIMEOUT_SEC = 60
    OPTIMIZER_TIMEOUT_SEC = 30

    CONTROL_DURATION_SEC = 45
    CONTROL_COOLDOWN_SEC = 30.0
    TARGET_REAPPLY_THRESHOLD_KW = 1.0

    CONTROL_SCENARIOS = {
        "GRID_STRESS",
        "PEAK_DEMAND",
        "CRITICAL_GRID",
    }

    def __init__(self):
        super().__init__("ai_engine")

        self.project_dir = PROJECT_DIR
        self.ai_dir = self.project_dir / "ai_engine"

        self.pipeline = self.ai_dir / "run_pipeline.py"
        self.optimizer = self.ai_dir / "optimizer.py"
        self.maintenance_manager = self.ai_dir / "maintenance_event_manager.py"
        self.optimization_output = self.ai_dir / "optimization_output.csv"
        self.control_safety_output = self.ai_dir / "control_safety_output.csv"

        self.venv_python = (
            self.project_dir
            / "dashboard"
            / "backend"
            / ".venv"
            / "bin"
            / "python3"
        )

        self.python = (
            str(self.venv_python)
            if self.venv_python.exists()
            else sys.executable
        )

        # machine_id -> {"target_kw": float, "applied_at": epoch}
        self.last_applied_controls: dict[str, dict] = {}

        self.running = False
        self.cycle_number = 0

        self.control_publisher = self.create_publisher(
            String,
            "/factory/control_command",
            20,
        )

        self.control_status_publisher = self.create_publisher(
            String,
            "/factory/ai_control_status",
            20,
        )

        self.timer = self.create_timer(
            self.AI_INTERVAL_SEC,
            self.run_cycle,
        )

        self.get_logger().info("=" * 50)
        self.get_logger().info("INDUS_TWIN AI ENGINE STARTED")
        self.get_logger().info(f"Pipeline: {self.pipeline}")
        self.get_logger().info(f"Optimizer: {self.optimizer}")
        self.get_logger().info(f"Python: {self.python}")
        self.get_logger().info(f"AI interval: {self.AI_INTERVAL_SEC:.0f}s")
        self.get_logger().info(
            f"Control duration: {self.CONTROL_DURATION_SEC:.0f}s"
        )
        self.get_logger().info(
            "Automatic control scenarios: "
            + ", ".join(sorted(self.CONTROL_SCENARIOS))
        )

        if CONTROL_SAFETY_AVAILABLE:
            self.get_logger().info(
                "Control safety validator: AVAILABLE"
            )
        else:
            self.get_logger().error(
                "Control safety validator: UNAVAILABLE"
            )
            self.get_logger().error(
                f"Import error: {CONTROL_SAFETY_IMPORT_ERROR}"
            )

        self.get_logger().info("=" * 50)

        self.run_cycle()

    # ============================================================
    # MAIN AI CYCLE
    # ============================================================

    def run_cycle(self):
        if self.running:
            self.get_logger().warning(
                "Previous AI cycle is still running. Skipping this cycle."
            )
            return

        self.running = True
        self.cycle_number += 1
        cycle_start = time.time()

        self.get_logger().info("-" * 50)
        self.get_logger().info(f"AI CYCLE #{self.cycle_number}")

        try:
            if not self.run_pipeline():
                self.get_logger().error(
                    "Pipeline failed. Optimizer/control step skipped."
                )
                return

            if not self.run_optimizer():
                self.get_logger().error(
                    "Optimizer failed. Control step skipped."
                )
                return

            self.apply_optimized_controls()
            self.run_maintenance_manager()

        finally:
            self.running = False
            elapsed = time.time() - cycle_start
            self.get_logger().info(
                f"AI cycle #{self.cycle_number} completed in {elapsed:.2f}s"
            )

    # ============================================================
    # RUN PIPELINE
    # ============================================================

    def run_pipeline(self) -> bool:
        if not self.pipeline.exists():
            self.get_logger().error(
                f"Pipeline not found: {self.pipeline}"
            )
            return False

        if not Path(self.python).exists():
            self.get_logger().error(
                f"Python interpreter not found: {self.python}"
            )
            return False

        self.get_logger().info("Running AI pipeline...")

        try:
            result = subprocess.run(
                [self.python, str(self.pipeline)],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=self.PIPELINE_TIMEOUT_SEC,
            )

            if result.stdout:
                self.get_logger().info(result.stdout)

            if result.stderr:
                self.get_logger().warning(result.stderr)

            if result.returncode != 0:
                self.get_logger().error(
                    f"AI pipeline failed: return code {result.returncode}"
                )
                return False

            self.get_logger().info("AI pipeline completed.")
            return True

        except subprocess.TimeoutExpired:
            self.get_logger().error(
                f"AI pipeline exceeded {self.PIPELINE_TIMEOUT_SEC}s timeout."
            )
            return False

        except Exception as exc:
            self.get_logger().error(
                f"Could not execute AI pipeline: {exc}"
            )
            return False

    # ============================================================
    # RUN OPTIMIZER
    # ============================================================

    def run_optimizer(self) -> bool:
        if not self.optimizer.exists():
            self.get_logger().error(
                f"Optimizer not found: {self.optimizer}"
            )
            return False

        self.get_logger().info("Running constrained optimizer...")

        try:
            result = subprocess.run(
                [self.python, str(self.optimizer)],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=self.OPTIMIZER_TIMEOUT_SEC,
            )

            if result.stdout:
                self.get_logger().info(result.stdout)

            if result.stderr:
                self.get_logger().warning(result.stderr)

            if result.returncode != 0:
                self.get_logger().error(
                    f"Optimizer failed: return code {result.returncode}"
                )
                return False

            self.get_logger().info("Optimizer completed.")
            return True

        except subprocess.TimeoutExpired:
            self.get_logger().error(
                f"Optimizer exceeded {self.OPTIMIZER_TIMEOUT_SEC}s timeout."
            )
            return False

        except Exception as exc:
            self.get_logger().error(
                f"Could not execute optimizer: {exc}"
            )
            return False

    # ============================================================
    # LOAD OPTIMIZATION OUTPUT
    # ============================================================

    def load_optimization_output(self) -> list[dict]:
        if not self.optimization_output.exists():
            self.get_logger().error(
                f"Optimization output not found: {self.optimization_output}"
            )
            return []

        try:
            with open(
                self.optimization_output,
                "r",
                newline="",
                encoding="utf-8",
            ) as file:
                return [
                    dict(row)
                    for row in csv.DictReader(file)
                ]

        except Exception as exc:
            self.get_logger().error(
                f"Could not read optimization output: {exc}"
            )
            return []

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def safe_float(value, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            value = float(value)
            if value != value:
                return default
            return value
        except (TypeError, ValueError):
            return default

    @staticmethod
    def safe_bool(value, default: bool = False) -> bool:
        if value is None:
            return default

        if isinstance(value, bool):
            return value

        text = str(value).strip().lower()

        if text in {"true", "1", "yes", "y", "on"}:
            return True

        if text in {"false", "0", "no", "n", "off"}:
            return False

        return default

    @staticmethod
    def clean_text(value, default: str = "UNKNOWN") -> str:
        if value is None:
            return default

        text = str(value).strip()

        return text if text else default

    # ============================================================
    # SAFETY INPUT
    # ============================================================

    def build_safety_row(self, row: dict) -> dict:
        machine_id = self.clean_text(
            row.get("machine_id"),
            "",
        )

        state = self.clean_text(
            row.get("state"),
            "UNKNOWN",
        ).upper()

        maintenance_label = self.clean_text(
            row.get("maintenance_label"),
            "NONE",
        ).upper()

        maintenance_risk = self.safe_float(
            row.get("maintenance_risk"),
            0.0,
        )

        high_threshold = getattr(
            control_safety,
            "HIGH_RISK_THRESHOLD",
            0.80,
        )

        high_maintenance_risk = (
            maintenance_label in {"HIGH", "CRITICAL"}
            or maintenance_risk >= high_threshold
        )

        controllability = self.clean_text(
            row.get("controllability"),
            "UNKNOWN",
        ).upper()

        fixed_machine = self.safe_bool(
            row.get("fixed_machine"),
            controllability == "FIXED",
        )

        control_active = (
            machine_id in self.last_applied_controls
            or state in {
                "REDUCED",
                "CURTAILED",
                "SHIFTED",
                "CONTROLLED",
            }
        )

        if "production_safe" in row:
            production_safe = self.safe_bool(
                row.get("production_safe"),
                False,
            )
        else:
            production_safe = self.safe_bool(
                row.get("safe_to_reduce"),
                False,
            )

        current_power_kw = self.safe_float(
            row.get("current_power_kw"),
            self.safe_float(row.get("actual_power_kw"), 0.0),
        )

        normal_target_kw = self.safe_float(
            row.get("normal_target_kw"),
            self.safe_float(row.get("normal_power_kw"), current_power_kw),
        )

        min_operating_power_kw = self.safe_float(
            row.get("min_operating_power_kw"),
            0.0,
        )

        allowed_reduction_kw = self.safe_float(
            row.get("allowed_reduction_kw"),
            self.safe_float(
                row.get("max_reduction_kw"),
                self.safe_float(row.get("feasible_reduce_kw"), 0.0),
            ),
        )

        optimized_reduction_kw = self.safe_float(
            row.get("optimized_reduction_kw"),
            0.0,
        )

        optimized_target_kw = self.safe_float(
            row.get("optimized_target_kw"),
            current_power_kw - optimized_reduction_kw,
        )

        return {
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "optimized_reduction_kw": optimized_reduction_kw,
            "optimized_target_kw": optimized_target_kw,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": self.safe_bool(
                row.get("maintenance_trigger"),
                False,
            ),
            "maintenance_reason": self.clean_text(
                row.get("maintenance_reason"),
                "NORMAL",
            ),
            "criticality": self.clean_text(
                row.get("criticality"),
                "UNKNOWN",
            ).upper(),
            "controllability": controllability,
            "control_active": control_active,
            "high_maintenance_risk": high_maintenance_risk,
            "fixed_machine": fixed_machine,
            "production_safe": production_safe,
        }

    # ============================================================
    # SAFETY EVALUATION
    # ============================================================

    def evaluate_safety(
        self,
        row: dict,
        scenario_id: str,
    ) -> dict:

        machine_id = self.clean_text(
            row.get("machine_id"),
            "",
        )

        base = {
            "timestamp": int(time.time()),
            "scenario_id": scenario_id,
            "machine_id": machine_id,
            "optimization_action": self.clean_text(
                row.get("optimization_action"),
                "NO_ACTION",
            ).upper(),
        }

        if not CONTROL_SAFETY_AVAILABLE:
            return {
                **base,
                "safety_action": "HOLD",
                "safety_status": "SAFETY_MODULE_UNAVAILABLE",
                "safety_reason": CONTROL_SAFETY_IMPORT_ERROR,
                "validated_target_kw": self.safe_float(
                    row.get("current_power_kw"),
                    self.safe_float(row.get("actual_power_kw"), 0.0),
                ),
                "validated_reduction_kw": 0.0,
                "command": "",
            }

        try:
            import pandas as pd

            safety_input = pd.Series(
                self.build_safety_row(row)
            )

            result = control_safety.evaluate_machine(
                safety_input
            )

            if not isinstance(result, dict):
                raise TypeError(
                    "control_safety.evaluate_machine() did not return a dict"
                )

            return {
                **base,
                "safety_action": self.clean_text(
                    result.get("safety_action"),
                    "HOLD",
                ).upper(),
                "safety_status": self.clean_text(
                    result.get("safety_status"),
                    "UNKNOWN",
                ).upper(),
                "safety_reason": self.clean_text(
                    result.get("safety_reason"),
                    "UNKNOWN",
                ),
                "validated_target_kw": self.safe_float(
                    result.get("validated_target_kw"),
                    self.safe_float(
                        row.get("current_power_kw"),
                        self.safe_float(row.get("actual_power_kw"), 0.0),
                    ),
                ),
                "validated_reduction_kw": max(
                    0.0,
                    self.safe_float(
                        result.get("validated_reduction_kw"),
                        0.0,
                    ),
                ),
                "command": self.clean_text(
                    result.get("command"),
                    "",
                ),
            }

        except Exception as exc:
            self.get_logger().error(
                f"Safety evaluation failed for {machine_id}: {exc}"
            )

            return {
                **base,
                "safety_action": "HOLD",
                "safety_status": "SAFETY_EVALUATION_ERROR",
                "safety_reason": str(exc),
                "validated_target_kw": self.safe_float(
                    row.get("current_power_kw"),
                    self.safe_float(row.get("actual_power_kw"), 0.0),
                ),
                "validated_reduction_kw": 0.0,
                "command": "",
            }

    # ============================================================
    # SAVE SAFETY DECISIONS
    # ============================================================

    def save_safety_decisions(self, decisions: list[dict]) -> None:
        if not decisions:
            return

        self.control_safety_output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fields = [
            "timestamp",
            "scenario_id",
            "machine_id",
            "optimization_action",
            "safety_action",
            "safety_status",
            "safety_reason",
            "validated_target_kw",
            "validated_reduction_kw",
            "command",
        ]

        try:
            with open(
                self.control_safety_output,
                "w",
                newline="",
                encoding="utf-8",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=fields,
                )
                writer.writeheader()
                writer.writerows(
                    {
                        key: item.get(key, "")
                        for key in fields
                    }
                    for item in decisions
                )
        except Exception as exc:
            self.get_logger().error(
                f"Could not save control safety output: {exc}"
            )

    # ============================================================
    # APPLY OPTIMIZATION
    # ============================================================

    def apply_optimized_controls(self):
        rows = self.load_optimization_output()

        if not rows:
            self.publish_control_status(
                {
                    "timestamp": int(time.time()),
                    "status": "NO_OPTIMIZATION_OUTPUT",
                    "safety_enabled": CONTROL_SAFETY_AVAILABLE,
                }
            )
            return

        scenario_id = self.clean_text(
            rows[0].get("scenario_id"),
            "UNKNOWN",
        ).upper()

        scenario_status = self.clean_text(
            rows[0].get("scenario_status"),
            "UNKNOWN",
        ).upper()

        scenario_name = self.clean_text(
            rows[0].get("scenario_name"),
            "Unknown",
        )

        required_reduction = self.safe_float(
            rows[0].get("required_reduction_kw"),
            0.0,
        )

        # The optimizer uses explicit system-level fields. The previous
        # node looked for system_achievable_reduction_kw, which does not
        # exist in optimization_output.csv and therefore reported 0.00 kW.
        achievable_reduction = self.safe_float(
            rows[0].get("system_additional_achievable_reduction_kw"),
            self.safe_float(
                rows[0].get("system_selected_additional_reduction_kw"),
                0.0,
            ),
        )

        selected_reduction = self.safe_float(
            rows[0].get("system_selected_additional_reduction_kw"),
            0.0,
        )

        projected_reduction = self.safe_float(
            rows[0].get("system_projected_reduction_kw"),
            selected_reduction,
        )

        active_reduction = self.safe_float(
            rows[0].get("system_already_active_reduction_kw"),
            0.0,
        )

        remaining_gap = self.safe_float(
            rows[0].get("system_remaining_reduction_kw"),
            max(
                0.0,
                required_reduction - projected_reduction,
            ),
        )

        solver_status = self.clean_text(
            rows[0].get("solver_status"),
            "UNKNOWN",
        )

        # --------------------------------------------------------
        # Normal operation
        # --------------------------------------------------------

        if scenario_id not in self.CONTROL_SCENARIOS:
            restored = []

            for machine_id in list(
                self.last_applied_controls.keys()
            ):
                if self.send_restore_command(machine_id):
                    restored.append(machine_id)

            self.last_applied_controls.clear()

            self.publish_control_status(
                {
                    "timestamp": int(time.time()),
                    "status": "NORMAL_OPERATION",
                    "scenario_id": scenario_id,
                    "scenario_name": scenario_name,
                    "scenario_status": scenario_status,
                    "required_reduction_kw": required_reduction,
                    "achievable_reduction_kw": achievable_reduction,
                    "selected_reduction_kw": selected_reduction,
                    "projected_reduction_kw": projected_reduction,
                    "active_reduction_kw": active_reduction,
                    "remaining_gap_kw": remaining_gap,
                    "solver_status": solver_status,
                    "actions_applied": [],
                    "machines_restored": restored,
                    "safety_enabled": CONTROL_SAFETY_AVAILABLE,
                    "safety_summary": {},
                }
            )
            return

        # --------------------------------------------------------
        # Safety gate
        #
        # Every optimizer row is evaluated before any REDUCE
        # command can be sent.
        # --------------------------------------------------------

        safety_decisions = []

        desired_controls: dict[str, float] = {}
        restore_for_safety: set[str] = set()

        for row in rows:
            decision = self.evaluate_safety(
                row,
                scenario_id,
            )

            safety_decisions.append(decision)

            action = decision["safety_action"]
            machine_id = decision["machine_id"]

            if not machine_id:
                continue

            if action == "RESTORE":
                restore_for_safety.add(machine_id)
                continue

            optimization_action = self.clean_text(
                row.get("optimization_action"),
                "NO_ACTION",
            ).upper()

            # ------------------------------------------------------------
            # IMPORTANT ACTIVE-CONTROL PERSISTENCE RULE
            #
            # On the first cycle, a selected machine receives REDUCE and is
            # stored in last_applied_controls.
            #
            # On the next cycle, the telemetry/control state may already show
            # that the machine is under active control. The safety layer then
            # correctly returns:
            #
            #     HOLD / ALREADY_CONTROLLED
            #
            # That HOLD must NOT be interpreted as "restore". The machine
            # remains part of desired_controls so the existing control is
            # preserved until the optimizer stops selecting it or safety
            # explicitly requests RESTORE.
            # ------------------------------------------------------------

            if (
                action == "HOLD"
                and decision.get("safety_status")
                == "ALREADY_CONTROLLED"
                and machine_id in self.last_applied_controls
                and optimization_action == "REDUCE"
            ):
                existing_target = self.safe_float(
                    self.last_applied_controls[machine_id].get(
                        "target_kw"
                    ),
                    0.0,
                )

                if existing_target > 0.0:
                    desired_controls[machine_id] = existing_target

                continue

            if action != "REDUCE":
                continue

            if optimization_action != "REDUCE":
                continue

            reduction_kw = self.safe_float(
                row.get("optimized_reduction_kw"),
                0.0,
            )

            validated_reduction_kw = self.safe_float(
                decision.get("validated_reduction_kw"),
                0.0,
            )

            if reduction_kw <= 1e-6:
                continue

            if validated_reduction_kw <= 1e-6:
                continue

            target_kw = self.safe_float(
                decision.get("validated_target_kw"),
                0.0,
            )

            if target_kw <= 0.0:
                continue

            desired_controls[machine_id] = target_kw

        self.save_safety_decisions(safety_decisions)

        # --------------------------------------------------------
        # Restore safety-triggered machines immediately.
        # --------------------------------------------------------

        restored_for_safety = []

        for machine_id in restore_for_safety:
            if machine_id in self.last_applied_controls:
                if self.send_restore_command(machine_id):
                    restored_for_safety.append(machine_id)
                del self.last_applied_controls[machine_id]
            else:
                # Machine may have been reduced before this node restarted.
                # The safety validator already saw the reduced state.
                if self.send_restore_command(machine_id):
                    restored_for_safety.append(machine_id)

        # --------------------------------------------------------
        # Remove controls no longer selected.
        # --------------------------------------------------------

        restored_no_longer_selected = []

        for machine_id in list(
            self.last_applied_controls.keys()
        ):
            if machine_id not in desired_controls:
                if self.send_restore_command(machine_id):
                    restored_no_longer_selected.append(machine_id)

                del self.last_applied_controls[machine_id]

        # --------------------------------------------------------
        # Apply selected controls.
        # --------------------------------------------------------

        applied_actions = []
        current_time = time.time()

        for machine_id, target_kw in desired_controls.items():
            previous = self.last_applied_controls.get(
                machine_id
            )

            should_apply = False

            if previous is None:
                should_apply = True

            else:
                previous_target = self.safe_float(
                    previous.get("target_kw"),
                    0.0,
                )

                applied_at = self.safe_float(
                    previous.get("applied_at"),
                    0.0,
                )

                target_changed = (
                    abs(target_kw - previous_target)
                    >= self.TARGET_REAPPLY_THRESHOLD_KW
                )

                cooldown_expired = (
                    current_time - applied_at
                    >= self.CONTROL_COOLDOWN_SEC
                )

                if target_changed or cooldown_expired:
                    should_apply = True

            if not should_apply:
                continue

            if self.send_reduce_command(
                machine_id,
                target_kw,
            ):
                self.last_applied_controls[machine_id] = {
                    "target_kw": target_kw,
                    "applied_at": current_time,
                }

                applied_actions.append(
                    {
                        "machine_id": machine_id,
                        "target_kw": round(target_kw, 2),
                    }
                )

        # --------------------------------------------------------
        # Safety summary
        # --------------------------------------------------------

        safety_summary = {
            "REDUCE": sum(
                d["safety_action"] == "REDUCE"
                for d in safety_decisions
            ),
            "HOLD": sum(
                d["safety_action"] == "HOLD"
                for d in safety_decisions
            ),
            "RESTORE": sum(
                d["safety_action"] == "RESTORE"
                for d in safety_decisions
            ),
        }

        if restored_for_safety:
            control_status = "SAFETY_RESTORE_APPLIED"

        elif applied_actions:
            control_status = "CONTROLS_APPLIED"

        elif desired_controls:
            control_status = "CONTROLS_ALREADY_ACTIVE"

        elif required_reduction > 0:
            control_status = "GRID_STRESS_NO_SAFE_ACTION"

        else:
            control_status = "NO_CONTROL_REQUIRED"

        self.publish_control_status(
            {
                "timestamp": int(current_time),
                "status": control_status,
                "scenario_id": scenario_id,
                "scenario_name": scenario_name,
                "scenario_status": scenario_status,
                "required_reduction_kw": required_reduction,
                "achievable_reduction_kw": achievable_reduction,
                "selected_reduction_kw": selected_reduction,
                "projected_reduction_kw": projected_reduction,
                "active_reduction_kw": active_reduction,
                "remaining_gap_kw": remaining_gap,
                "solver_status": solver_status,
                "safety_enabled": CONTROL_SAFETY_AVAILABLE,
                "safety_summary": safety_summary,
                "actions_applied": applied_actions,
                "machines_restored_for_safety":
                    restored_for_safety,
                "machines_restored_no_longer_selected":
                    restored_no_longer_selected,
                "active_controls": [
                    {
                        "machine_id": machine_id,
                        "target_kw": state["target_kw"],
                    }
                    for machine_id, state
                    in self.last_applied_controls.items()
                ],
            }
        )

        self.get_logger().info(
            f"AI control status: {control_status} | "
            f"scenario={scenario_id} | "
            f"required={required_reduction:.2f} kW | "
            f"achievable={achievable_reduction:.2f} kW | "
            f"gap={remaining_gap:.2f} kW | "
            f"safety="
            f"REDUCE:{safety_summary['REDUCE']} "
            f"HOLD:{safety_summary['HOLD']} "
            f"RESTORE:{safety_summary['RESTORE']}"
        )

        for decision in safety_decisions:
            if decision["safety_action"] == "RESTORE":
                self.get_logger().warning(
                    f"SAFETY RESTORE → "
                    f"{decision['machine_id']}: "
                    f"{decision['safety_reason']}"
                )
            elif decision["safety_action"] == "HOLD":
                self.get_logger().info(
                    f"SAFETY HOLD → "
                    f"{decision['machine_id']}: "
                    f"{decision['safety_reason']}"
                )

                if (
                    decision.get("safety_status")
                    == "ALREADY_CONTROLLED"
                    and decision["machine_id"]
                    in self.last_applied_controls
                ):
                    self.get_logger().info(
                        f"CONTROL RETAINED → "
                        f"{decision['machine_id']}: "
                        f"existing target remains active"
                    )

    # ============================================================
    # SEND REDUCE COMMAND
    # ============================================================

    def send_reduce_command(
        self,
        machine_id: str,
        target_kw: float,
    ) -> bool:
        command = {
            "timestamp": int(time.time()),
            "source": "AI_OPTIMIZER",
            "machine_id": machine_id,
            "command": "REDUCE_LOAD",
            "target_kw": round(target_kw, 2),
            "duration_sec": self.CONTROL_DURATION_SEC,
        }

        message = String()
        message.data = json.dumps(command)
        self.control_publisher.publish(message)

        self.get_logger().info(
            f"AI CONTROL → {machine_id}: "
            f"target={target_kw:.2f} kW"
        )

        return True

    # ============================================================
    # RESTORE COMMAND
    # ============================================================

    def send_restore_command(
        self,
        machine_id: str,
    ) -> bool:
        command = {
            "timestamp": int(time.time()),
            "source": "AI_OPTIMIZER",
            "machine_id": machine_id,
            "command": "RESTORE_NORMAL",
        }

        message = String()
        message.data = json.dumps(command)
        self.control_publisher.publish(message)

        self.get_logger().info(
            f"AI CONTROL → {machine_id}: RESTORE_NORMAL"
        )

        return True

    # ============================================================
    # CONTROL STATUS PUBLISHER
    # ============================================================

    def publish_control_status(
        self,
        status: dict,
    ):
        message = String()
        message.data = json.dumps(status)
        self.control_status_publisher.publish(message)

    # ============================================================
    # MAINTENANCE EVENT MANAGER
    # ============================================================

    def run_maintenance_manager(self):
        if not self.maintenance_manager.exists():
            self.get_logger().warning(
                "Maintenance event manager not found."
            )
            return

        try:
            result = subprocess.run(
                [self.python, str(self.maintenance_manager)],
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.stdout:
                self.get_logger().info(result.stdout)

            if result.stderr:
                self.get_logger().warning(result.stderr)

            if result.returncode != 0:
                self.get_logger().error(
                    "Maintenance event manager failed: "
                    f"return code={result.returncode}"
                )

        except subprocess.TimeoutExpired:
            self.get_logger().error(
                "Maintenance event manager exceeded 30-second timeout."
            )

        except Exception as exc:
            self.get_logger().error(
                f"Maintenance event manager error: {exc}"
            )

    # ============================================================
    # SHUTDOWN
    # ============================================================

    def destroy_node(self):
        try:
            self.publish_control_status(
                {
                    "timestamp": int(time.time()),
                    "status": "AI_ENGINE_SHUTDOWN",
                    "active_controls_before_shutdown": [
                        {
                            "machine_id": machine_id,
                            "target_kw": state["target_kw"],
                        }
                        for machine_id, state
                        in self.last_applied_controls.items()
                    ],
                }
            )
        except Exception:
            pass

        super().destroy_node()


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
