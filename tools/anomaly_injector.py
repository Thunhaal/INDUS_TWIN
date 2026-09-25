from __future__ import annotations

import json
import time
import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from typing import Dict, List

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


# ============================================================
# MACHINE CONFIGURATION
# ============================================================

MACHINES = [
    "CNC_01",
    "CNC_02",
    "CNC_03",
    "COMP_01",
    "PUMP_01",
    "HVAC_01",
    "FURNACE_01",
]

ANOMALY_PROFILES = {
    "HIGH_LOAD": {
        "load": 120.0,
        "temperature": 30.0,
        "vibration": 4.5,
    },
    "THERMAL_OVERLOAD": {
        "load": 105.0,
        "temperature": 60.0,
        "vibration": 0.8,
    },
    "VIBRATION_SPIKE": {
        "load": 105.0,
        "temperature": 12.0,
        "vibration": 5.0,
    },
    "POWER_SURGE": {
        "load": 125.0,
        "temperature": 25.0,
        "vibration": 2.5,
    },
}

SEVERITIES = [
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
]


# ============================================================
# ROS BRIDGE
# ============================================================

class AnomalyROS(Node):

    def __init__(self, app):
        super().__init__("indus_twin_anomaly_injector")

        self.app = app

        self.command_pub = self.create_publisher(
            String,
            "/factory/control_command",
            20,
        )

        self.state_sub = self.create_subscription(
            String,
            "/factory/machine_state",
            self.on_machine_state,
            20,
        )

        self.event_sub = self.create_subscription(
            String,
            "/factory/events",
            self.on_factory_event,
            20,
        )

    # --------------------------------------------------------
    # Publish JSON command
    # --------------------------------------------------------

    def publish_command(
        self,
        payload: dict,
    ) -> None:

        message = String()

        message.data = json.dumps(
            payload
        )

        self.command_pub.publish(
            message
        )

        self.app.log_event(
            "TX",
            json.dumps(
                payload,
                separators=(
                    ",",
                    ":",
                ),
            ),
        )

    # --------------------------------------------------------
    # Machine telemetry
    # --------------------------------------------------------

    def on_machine_state(
        self,
        message: String,
    ) -> None:

        try:
            data = json.loads(
                message.data
            )

            machine_id = str(
                data.get(
                    "machine_id",
                    "",
                )
            )

            if machine_id:

                self.app.machine_data[
                    machine_id
                ] = data

                self.app.refresh_machine_table()

        except Exception as exc:

            self.get_logger().warning(
                f"Could not parse machine telemetry: {exc}"
            )

    # --------------------------------------------------------
    # Factory events
    # --------------------------------------------------------

    def on_factory_event(
        self,
        message: String,
    ) -> None:

        try:

            data = json.loads(
                message.data
            )

            event = str(
                data.get(
                    "event",
                    message.data,
                )
            )

            self.app.log_event(
                "FACTORY",
                event,
            )

        except Exception:

            self.app.log_event(
                "FACTORY",
                message.data,
            )


# ============================================================
# TKINTER APPLICATION
# ============================================================

class AnomalyInjectorApp:

    def __init__(
        self,
        root: tk.Tk,
    ) -> None:

        self.root = root

        self.root.title(
            "INDUS_TWIN — Anomaly Control Console"
        )

        self.root.geometry(
            "1280x820"
        )

        self.root.minsize(
            1100,
            720,
        )

        self.machine_data: Dict[
            str,
            dict,
        ] = {}

        self.event_history: List[str] = []

        self.ros = AnomalyROS(
            self
        )

        self.build_styles()
        self.build_ui()

        self.root.after(
            50,
            self.spin_ros,
        )

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.on_close,
        )

    # ========================================================
    # STYLING
    # ========================================================

    def build_styles(
        self,
    ) -> None:

        style = ttk.Style()

        try:
            style.theme_use(
                "clam"
            )
        except tk.TclError:
            pass

        style.configure(
            "Title.TLabel",
            font=(
                "Segoe UI",
                20,
                "bold",
            ),
        )

        style.configure(
            "Subtitle.TLabel",
            font=(
                "Segoe UI",
                10,
            ),
        )

        style.configure(
            "Section.TLabelframe",
            font=(
                "Segoe UI",
                10,
                "bold",
            ),
        )

        style.configure(
            "Action.TButton",
            font=(
                "Segoe UI",
                10,
                "bold",
            ),
            padding=8,
        )

        style.configure(
            "Danger.TButton",
            font=(
                "Segoe UI",
                10,
                "bold",
            ),
            padding=8,
        )

        style.configure(
            "Treeview",
            rowheight=30,
            font=(
                "Segoe UI",
                9,
            ),
        )

        style.configure(
            "Treeview.Heading",
            font=(
                "Segoe UI",
                9,
                "bold",
            ),
        )

    # ========================================================
    # UI
    # ========================================================

    def build_ui(
        self,
    ) -> None:

        # ----------------------------------------------------
        # Header
        # ----------------------------------------------------

        header = ttk.Frame(
            self.root,
            padding=16,
        )

        header.pack(
            fill="x"
        )

        title_frame = ttk.Frame(
            header
        )

        title_frame.pack(
            side="left",
            fill="x",
            expand=True,
        )

        ttk.Label(
            title_frame,
            text="INDUS_TWIN",
            style="Title.TLabel",
        ).pack(
            anchor="w"
        )

        ttk.Label(
            title_frame,
            text=(
                "Industrial Anomaly Control Console  "
                "•  ROS 2 Factory Twin"
            ),
            style="Subtitle.TLabel",
        ).pack(
            anchor="w",
            pady=(3, 0),
        )

        self.connection_label = ttk.Label(
            header,
            text="● ROS CONNECTED",
            font=(
                "Segoe UI",
                10,
                "bold",
            ),
        )

        self.connection_label.pack(
            side="right"
        )

        # ----------------------------------------------------
        # Main body
        # ----------------------------------------------------

        body = ttk.Panedwindow(
            self.root,
            orient="horizontal",
        )

        body.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=(0, 12),
        )

        left = ttk.Frame(
            body,
            padding=10,
        )

        right = ttk.Frame(
            body,
            padding=10,
        )

        body.add(
            left,
            weight=1,
        )

        body.add(
            right,
            weight=2,
        )

        self.build_control_panel(
            left
        )

        self.build_live_monitor(
            right
        )

        self.build_event_log(
            right
        )

    # ========================================================
    # CONTROL PANEL
    # ========================================================

    def build_control_panel(
        self,
        parent,
    ) -> None:

        # ----------------------------------------------------
        # Injection mode
        # ----------------------------------------------------

        mode_frame = ttk.LabelFrame(
            parent,
            text="INJECTION MODE",
            style="Section.TLabelframe",
            padding=10,
        )

        mode_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        self.mode_var = tk.StringVar(
            value="SINGLE"
        )

        ttk.Radiobutton(
            mode_frame,
            text="Single Machine",
            variable=self.mode_var,
            value="SINGLE",
            command=self.mode_changed,
        ).pack(
            side="left",
            padx=(0, 12),
        )

        ttk.Radiobutton(
            mode_frame,
            text="Multiple Machines",
            variable=self.mode_var,
            value="MULTIPLE",
            command=self.mode_changed,
        ).pack(
            side="left"
        )

        # ----------------------------------------------------
        # Machine selection
        # ----------------------------------------------------

        machine_frame = ttk.LabelFrame(
            parent,
            text="MACHINE SELECTION",
            style="Section.TLabelframe",
            padding=8,
        )

        machine_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        self.machine_list = tk.Listbox(
            machine_frame,
            height=8,
            selectmode=tk.SINGLE,
            exportselection=False,
            font=(
                "Consolas",
                10,
            ),
        )

        for machine in MACHINES:

            self.machine_list.insert(
                tk.END,
                machine,
            )

        self.machine_list.selection_set(
            0
        )

        self.machine_list.pack(
            fill="x"
        )

        # ----------------------------------------------------
        # Anomaly type
        # ----------------------------------------------------

        anomaly_frame = ttk.LabelFrame(
            parent,
            text="ANOMALY PARAMETERS",
            style="Section.TLabelframe",
            padding=10,
        )

        anomaly_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        self.anomaly_type_var = tk.StringVar(
            value="HIGH_LOAD"
        )

        self.severity_var = tk.StringVar(
            value="HIGH"
        )

        self.load_var = tk.DoubleVar(
            value=120.0
        )

        self.temperature_var = tk.DoubleVar(
            value=30.0
        )

        self.vibration_var = tk.DoubleVar(
            value=4.5
        )

        self.duration_var = tk.IntVar(
            value=60
        )

        self.add_combo_row(
            anomaly_frame,
            "Type",
            self.anomaly_type_var,
            list(
                ANOMALY_PROFILES.keys()
            ),
            self.apply_profile,
        )

        self.add_combo_row(
            anomaly_frame,
            "Severity",
            self.severity_var,
            SEVERITIES,
            self.apply_profile,
        )

        self.add_scale_row(
            anomaly_frame,
            "Load %",
            self.load_var,
            0,
            130,
            1,
        )

        self.add_scale_row(
            anomaly_frame,
            "Temp Δ °C",
            self.temperature_var,
            0,
            100,
            1,
        )

        self.add_scale_row(
            anomaly_frame,
            "Vibration Δ",
            self.vibration_var,
            0,
            10,
            0.1,
        )

        duration_row = ttk.Frame(
            anomaly_frame
        )

        duration_row.pack(
            fill="x",
            pady=5,
        )

        ttk.Label(
            duration_row,
            text="Duration (sec)",
            width=16,
        ).pack(
            side="left"
        )

        ttk.Entry(
            duration_row,
            textvariable=self.duration_var,
            width=10,
        ).pack(
            side="left"
        )

        # ----------------------------------------------------
        # Persistence
        # ----------------------------------------------------

        persistence_frame = ttk.LabelFrame(
            parent,
            text="PERSISTENCE LOGIC",
            style="Section.TLabelframe",
            padding=10,
        )

        persistence_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        ttk.Label(
            persistence_frame,
            text="Rolling window",
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            persistence_frame,
            text="8 readings",
            font=(
                "Segoe UI",
                10,
                "bold",
            ),
        ).grid(
            row=0,
            column=1,
            sticky="e",
        )

        ttk.Label(
            persistence_frame,
            text="Escalation threshold",
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(5, 0),
        )

        ttk.Label(
            persistence_frame,
            text="6 / 8 abnormal",
            font=(
                "Segoe UI",
                10,
                "bold",
            ),
        ).grid(
            row=1,
            column=1,
            sticky="e",
            pady=(5, 0),
        )

        persistence_frame.columnconfigure(
            1,
            weight=1,
        )

        # ----------------------------------------------------
        # Actions
        # ----------------------------------------------------

        action_frame = ttk.Frame(
            parent
        )

        action_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        ttk.Button(
            action_frame,
            text="⚠ INJECT ANOMALY",
            style="Action.TButton",
            command=self.inject_anomaly,
        ).pack(
            fill="x",
            pady=3,
        )

        ttk.Button(
            action_frame,
            text="STOP SELECTED ANOMALY",
            command=self.stop_selected_anomaly,
        ).pack(
            fill="x",
            pady=3,
        )

        ttk.Button(
            action_frame,
            text="RESET TRANSIENT CONTROLS",
            command=self.reset_all,
        ).pack(
            fill="x",
            pady=3,
        )

        # ----------------------------------------------------
        # Selected machine summary
        # ----------------------------------------------------

        self.summary_frame = ttk.LabelFrame(
            parent,
            text="SELECTED MACHINE",
            style="Section.TLabelframe",
            padding=10,
        )

        self.summary_frame.pack(
            fill="both",
            expand=True,
        )

        self.summary_text = tk.Text(
            self.summary_frame,
            height=12,
            width=35,
            state="disabled",
            font=(
                "Consolas",
                9,
            ),
        )

        self.summary_text.pack(
            fill="both",
            expand=True,
        )

        self.machine_list.bind(
            "<<ListboxSelect>>",
            lambda _event:
                self.update_summary(),
        )

    # ========================================================
    # UI HELPERS
    # ========================================================

    def add_combo_row(
        self,
        parent,
        label,
        variable,
        values,
        callback,
    ) -> None:

        row = ttk.Frame(
            parent
        )

        row.pack(
            fill="x",
            pady=4,
        )

        ttk.Label(
            row,
            text=label,
            width=16,
        ).pack(
            side="left"
        )

        combo = ttk.Combobox(
            row,
            textvariable=variable,
            values=values,
            state="readonly",
            width=23,
        )

        combo.pack(
            side="left",
            fill="x",
            expand=True,
        )

        combo.bind(
            "<<ComboboxSelected>>",
            lambda _event:
                callback(),
        )

    def add_scale_row(
        self,
        parent,
        label,
        variable,
        minimum,
        maximum,
        resolution,
    ) -> None:

        row = ttk.Frame(
            parent
        )

        row.pack(
            fill="x",
            pady=4,
        )

        ttk.Label(
            row,
            text=label,
            width=16,
        ).pack(
            side="left"
        )

        scale = tk.Scale(
            row,
            variable=variable,
            from_=minimum,
            to=maximum,
            resolution=resolution,
            orient="horizontal",
            showvalue=True,
            highlightthickness=0,
        )

        scale.pack(
            side="left",
            fill="x",
            expand=True,
        )

    # ========================================================
    # PROFILE LOGIC
    # ========================================================

    def apply_profile(
        self,
    ) -> None:

        anomaly_type = (
            self.anomaly_type_var.get()
        )

        profile = ANOMALY_PROFILES.get(
            anomaly_type
        )

        if not profile:
            return

        severity = (
            self.severity_var.get()
        )

        load = profile[
            "load"
        ]

        temperature = profile[
            "temperature"
        ]

        vibration = profile[
            "vibration"
        ]

        if severity == "LOW":

            load -= 8.0
            temperature *= 0.45
            vibration *= 0.45

        elif severity == "MEDIUM":

            load -= 3.0
            temperature *= 0.70
            vibration *= 0.70

        elif severity == "CRITICAL":

            load += 3.0
            temperature *= 1.20
            vibration *= 1.20

        self.load_var.set(
            max(
                0.0,
                min(
                    130.0,
                    load,
                ),
            )
        )

        self.temperature_var.set(
            max(
                0.0,
                temperature,
            )
        )

        self.vibration_var.set(
            max(
                0.0,
                vibration,
            )
        )

    # ========================================================
    # MACHINE SELECTION
    # ========================================================

    def selected_machines(
        self,
    ) -> List[str]:

        selected = [
            self.machine_list.get(
                i
            )
            for i in self.machine_list.curselection()
        ]

        if (
            self.mode_var.get()
            == "SINGLE"
        ):

            if selected:
                return selected[:1]

            return [
                MACHINES[0]
            ]

        return selected

    def mode_changed(
        self,
    ) -> None:

        if (
            self.mode_var.get()
            == "MULTIPLE"
        ):

            self.machine_list.config(
                selectmode=tk.MULTIPLE
            )

        else:

            self.machine_list.config(
                selectmode=tk.SINGLE
            )

            selected = (
                self.machine_list.curselection()
            )

            if len(selected) > 1:

                first = selected[0]

                self.machine_list.selection_clear(
                    0,
                    tk.END,
                )

                self.machine_list.selection_set(
                    first
                )

    # ========================================================
    # COMMANDS
    # ========================================================

    def inject_anomaly(
        self,
    ) -> None:

        machines = (
            self.selected_machines()
        )

        if not machines:

            messagebox.showwarning(
                "No Machine Selected",
                "Select at least one machine.",
            )

            return

        anomaly_type = (
            self.anomaly_type_var.get()
        )

        severity = (
            self.severity_var.get()
        )

        duration = max(
            1,
            int(
                self.duration_var.get()
            ),
        )

        for machine_id in machines:

            payload = {

                "command":
                    "ANOMALY_INJECT",

                "machine_id":
                    machine_id,

                "anomaly_type":
                    anomaly_type,

                "severity":
                    severity,

                "load_percent":
                    float(
                        self.load_var.get()
                    ),

                "temperature_offset_c":
                    float(
                        self.temperature_var.get()
                    ),

                "vibration_offset_mm_s":
                    float(
                        self.vibration_var.get()
                    ),

                "duration_sec":
                    duration,

                "source":
                    "TKINTER_ANOMALY_CONSOLE",

            }

            self.ros.publish_command(
                payload
            )

        self.log_event(
            "CONSOLE",
            (
                f"Injected {anomaly_type} / "
                f"{severity} into "
                f"{', '.join(machines)}"
            ),
        )

    def stop_selected_anomaly(
        self,
    ) -> None:

        machines = (
            self.selected_machines()
        )

        if not machines:
            return

        for machine_id in machines:

            payload = {
                "command":
                    "CLEAR_ANOMALY",
                "machine_id":
                    machine_id,
                "source":
                    "TKINTER_ANOMALY_CONSOLE",
            }

            self.ros.publish_command(
                payload
            )

    def reset_all(
        self,
    ) -> None:

        self.ros.publish_command(
            {
                "command":
                    "RESET_ALL",
                "source":
                    "TKINTER_ANOMALY_CONSOLE",
            }
        )

    # ========================================================
    # LIVE TABLE
    # ========================================================

    def build_live_monitor(
        self,
        parent,
    ) -> None:

        frame = ttk.LabelFrame(
            parent,
            text="LIVE MACHINE MONITOR",
            style="Section.TLabelframe",
            padding=8,
        )

        frame.pack(
            fill="both",
            expand=True,
            pady=(0, 10),
        )

        columns = (
            "machine",
            "state",
            "load",
            "temp",
            "vibration",
            "power",
            "persistence",
            "required",
        )

        self.machine_tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
        )

        headings = {
            "machine":
                "MACHINE",
            "state":
                "STATE",
            "load":
                "LOAD %",
            "temp":
                "TEMP °C",
            "vibration":
                "VIBRATION",
            "power":
                "POWER kW",
            "persistence":
                "6/8",
            "required":
                "MAINT.",
        }

        widths = {
            "machine": 90,
            "state": 110,
            "load": 75,
            "temp": 80,
            "vibration": 95,
            "power": 85,
            "persistence": 65,
            "required": 75,
        }

        for column in columns:

            self.machine_tree.heading(
                column,
                text=headings[
                    column
                ],
            )

            self.machine_tree.column(
                column,
                width=widths[
                    column
                ],
                anchor="center",
            )

        self.machine_tree.pack(
            fill="both",
            expand=True,
        )

        for machine in MACHINES:

            self.machine_tree.insert(
                "",
                tk.END,
                iid=machine,
                values=(
                    machine,
                    "WAITING",
                    "—",
                    "—",
                    "—",
                    "—",
                    "0/8",
                    "NO",
                ),
            )

        self.machine_tree.bind(
            "<<TreeviewSelect>>",
            self.tree_selection_changed,
        )

    def tree_selection_changed(
        self,
        _event=None,
    ) -> None:

        selected = (
            self.machine_tree.selection()
        )

        if not selected:
            return

        machine_id = selected[0]

        try:

            index = MACHINES.index(
                machine_id
            )

            self.machine_list.selection_clear(
                0,
                tk.END,
            )

            self.machine_list.selection_set(
                index
            )

            self.machine_list.see(
                index
            )

            self.update_summary()

        except ValueError:
            pass

    def refresh_machine_table(
        self,
    ) -> None:

        for machine_id in MACHINES:

            data = self.machine_data.get(
                machine_id
            )

            if not data:
                continue

            state = str(
                data.get(
                    "state",
                    "UNKNOWN",
                )
            )

            load = data.get(
                "load_percent"
            )

            temperature = data.get(
                "temperature"
            )

            vibration = data.get(
                "vibration"
            )

            power = data.get(
                "power_kw"
            )

            persistence = data.get(
                "persistence_count",
                0,
            )

            window = data.get(
                "persistence_window",
                8,
            )

            required = data.get(
                "maintenance_required",
                False,
            )

            self.machine_tree.item(
                machine_id,
                values=(
                    machine_id,
                    state,
                    self.fmt(
                        load
                    ),
                    self.fmt(
                        temperature
                    ),
                    self.fmt(
                        vibration
                    ),
                    self.fmt(
                        power
                    ),
                    f"{persistence}/{window}",
                    "YES"
                    if required
                    else "NO",
                ),
            )

        self.update_summary()

    # ========================================================
    # SELECTED MACHINE SUMMARY
    # ========================================================

    def update_summary(
        self,
    ) -> None:

        machines = (
            self.selected_machines()
        )

        if not machines:
            return

        machine_id = machines[0]

        data = self.machine_data.get(
            machine_id,
            {},
        )

        text = (
            f"MACHINE        : {machine_id}\n"
            f"STATE          : {data.get('state', 'WAITING')}\n"
            f"POWER          : {self.fmt(data.get('power_kw'))} kW\n"
            f"LOAD           : {self.fmt(data.get('load_percent'))} %\n"
            f"TEMPERATURE    : {self.fmt(data.get('temperature'))} °C\n"
            f"VIBRATION      : {self.fmt(data.get('vibration'))} mm/s\n"
            f"RPM            : {data.get('rpm', '—')}\n"
            f"PRODUCTION     : {self.fmt(data.get('production_rate'))} u/h\n"
            f"\n"
            f"ANOMALY        : {data.get('anomaly', False)}\n"
            f"TYPE           : {data.get('anomaly_type', 'NORMAL')}\n"
            f"SEVERITY       : {data.get('anomaly_severity', 'NONE')}\n"
            f"\n"
            f"PERSISTENCE    : "
            f"{data.get('persistence_count', 0)}/"
            f"{data.get('persistence_window', 8)}\n"
            f"ESCALATED      : "
            f"{data.get('persistence_escalated', False)}\n"
            f"MAINT. REQUIRED: "
            f"{data.get('maintenance_required', False)}\n"
            f"FAULTED        : "
            f"{data.get('faulted', False)}\n"
            f"FAULT CODE     : "
            f"{data.get('fault_code', 'NONE')}\n"
            f"DAMAGE LEVEL   : "
            f"{self.fmt(data.get('damage_level'))}\n"
        )

        self.summary_text.config(
            state="normal"
        )

        self.summary_text.delete(
            "1.0",
            tk.END,
        )

        self.summary_text.insert(
            tk.END,
            text,
        )

        self.summary_text.config(
            state="disabled"
        )

    # ========================================================
    # EVENT LOG
    # ========================================================

    def build_event_log(
        self,
        parent,
    ) -> None:

        frame = ttk.LabelFrame(
            parent,
            text="FACTORY EVENT LOG",
            style="Section.TLabelframe",
            padding=8,
        )

        frame.pack(
            fill="both",
            expand=True,
        )

        self.event_text = tk.Text(
            frame,
            height=10,
            state="disabled",
            font=(
                "Consolas",
                9,
            ),
        )

        scrollbar = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=self.event_text.yview,
        )

        self.event_text.configure(
            yscrollcommand=scrollbar.set
        )

        self.event_text.pack(
            side="left",
            fill="both",
            expand=True,
        )

        scrollbar.pack(
            side="right",
            fill="y",
        )

    def log_event(
        self,
        source: str,
        text: str,
    ) -> None:

        timestamp = time.strftime(
            "%H:%M:%S"
        )

        line = (
            f"[{timestamp}] "
            f"{source:<8} "
            f"{text}\n"
        )

        self.event_history.append(
            line
        )

        if len(
            self.event_history
        ) > 250:

            self.event_history = (
                self.event_history[-250:]
            )

        self.event_text.config(
            state="normal"
        )

        self.event_text.insert(
            tk.END,
            line,
        )

        self.event_text.see(
            tk.END
        )

        self.event_text.config(
            state="disabled"
        )

    # ========================================================
    # FORMATTER
    # ========================================================

    @staticmethod
    def fmt(
        value,
    ) -> str:

        if value is None:
            return "—"

        try:

            return f"{float(value):.2f}"

        except (
            TypeError,
            ValueError,
        ):

            return str(value)

    # ========================================================
    # ROS SPIN
    # ========================================================

    def spin_ros(
        self,
    ) -> None:

        try:

            if (
                rclpy.ok()
            ):

                rclpy.spin_once(
                    self.ros,
                    timeout_sec=0.01,
                )

                self.root.after(
                    50,
                    self.spin_ros,
                )

        except Exception as exc:

            self.connection_label.config(
                text="● ROS ERROR"
            )

            self.log_event(
                "ROS",
                str(exc),
            )

    # ========================================================
    # CLOSE
    # ========================================================

    def on_close(
        self,
    ) -> None:

        try:

            self.ros.destroy_node()

            if rclpy.ok():

                rclpy.shutdown()

        except Exception:
            pass

        self.root.destroy()


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    rclpy.init()

    root = tk.Tk()

    app = AnomalyInjectorApp(
        root
    )

    app.apply_profile()

    root.mainloop()


if __name__ == "__main__":
    main()
