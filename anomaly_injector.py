import json
import tkinter as tk
from tkinter import ttk

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


MACHINE_RATINGS = {
    "CNC_01": 28,
    "CNC_02": 30,
    "CNC_03": 26,
    "COMP_01": 50,
    "PUMP_01": 18,
    "HVAC_01": 35,
    "FURNACE_01": 78
}


class AnomalyInjectorNode(Node):

    def __init__(self):
        super().__init__("anomaly_injector")

        self.publisher = self.create_publisher(
            String,
            "/factory/control_command",
            10
        )

    def send_command(self, command):
        message = String()
        message.data = json.dumps(command)
        self.publisher.publish(message)

        self.get_logger().info(
            f"Command sent: {message.data}"
        )


class AnomalyGUI:

    def __init__(self, root, node):

        self.root = root
        self.node = node

        self.root.title("INDUS TWIN - Anomaly Injector")
        self.root.geometry("520x560")
        self.root.minsize(520, 560)
        self.root.resizable(False, False)

        main = ttk.Frame(root, padding=20)
        main.pack(fill="both", expand=True)

        title = ttk.Label(
            main,
            text="INDUS TWIN",
            font=("Arial", 20, "bold")
        )
        title.pack(pady=(0, 2))

        subtitle = ttk.Label(
            main,
            text="Industrial Anomaly Injection Tool",
            font=("Arial", 11)
        )
        subtitle.pack(pady=(0, 15))

        machine_frame = ttk.LabelFrame(
            main,
            text="Machine",
            padding=10
        )
        machine_frame.pack(fill="x", pady=5)

        self.machine_var = tk.StringVar(value="COMP_01")

        self.machine_dropdown = ttk.Combobox(
            machine_frame,
            textvariable=self.machine_var,
            values=list(MACHINE_RATINGS.keys()),
            state="readonly",
            width=35
        )
        self.machine_dropdown.pack()

        anomaly_frame = ttk.LabelFrame(
            main,
            text="Anomaly Type",
            padding=10
        )
        anomaly_frame.pack(fill="x", pady=5)

        self.anomaly_var = tk.StringVar(
            value="Power Overload"
        )

        self.anomaly_dropdown = ttk.Combobox(
            anomaly_frame,
            textvariable=self.anomaly_var,
            values=[
                "Power Overload",
                "Excessive Energy Consumption"
            ],
            state="readonly",
            width=35
        )
        self.anomaly_dropdown.pack()

        load_frame = ttk.LabelFrame(
            main,
            text="Target Load",
            padding=10
        )
        load_frame.pack(fill="x", pady=5)

        self.load_value = tk.DoubleVar(value=110)

        self.load_slider = tk.Scale(
            load_frame,
            from_=50,
            to=130,
            orient="horizontal",
            variable=self.load_value,
            resolution=1,
            length=400,
            showvalue=False,
            command=self.update_load_label
        )
        self.load_slider.pack()

        self.load_label = ttk.Label(
            load_frame,
            text="110%",
            font=("Arial", 14, "bold")
        )
        self.load_label.pack()

        duration_frame = ttk.LabelFrame(
            main,
            text="Duration",
            padding=10
        )
        duration_frame.pack(fill="x", pady=5)

        duration_inner = ttk.Frame(duration_frame)
        duration_inner.pack()

        ttk.Label(
            duration_inner,
            text="Duration (seconds):"
        ).pack(side="left", padx=5)

        self.duration_entry = ttk.Entry(
            duration_inner,
            width=10
        )
        self.duration_entry.insert(0, "60")
        self.duration_entry.pack(side="left")

        button_frame = ttk.Frame(main)
        button_frame.pack(pady=15)

        self.inject_button = ttk.Button(
            button_frame,
            text="INJECT ANOMALY",
            command=self.inject_anomaly
        )
        self.inject_button.grid(
            row=0,
            column=0,
            padx=10,
            ipadx=10,
            ipady=5
        )

        self.restore_button = ttk.Button(
            button_frame,
            text="RESTORE NORMAL",
            command=self.restore_normal
        )
        self.restore_button.grid(
            row=0,
            column=1,
            padx=10,
            ipadx=10,
            ipady=5
        )

        self.status_var = tk.StringVar(
            value="Status: Ready"
        )

        self.status_label = ttk.Label(
            main,
            textvariable=self.status_var,
            font=("Arial", 10)
        )
        self.status_label.pack(pady=5)

    def update_load_label(self, value):
        load = float(value)
        self.load_label.config(
            text=f"{load:.0f}%"
        )

    def inject_anomaly(self):

        machine_id = self.machine_var.get()
        load_percent = float(
            self.load_value.get()
        )

        try:
            duration = int(
                self.duration_entry.get()
            )

            if duration <= 0:
                raise ValueError

        except ValueError:

            self.status_var.set(
                "Status: Invalid duration"
            )

            return

        command = {
            "machine_id": machine_id,
            "command": "SET_LOAD",
            "load_percent": load_percent,
            "duration_sec": duration
        }

        self.node.send_command(command)

        target_power = (
            MACHINE_RATINGS[machine_id]
            * load_percent
            / 100.0
        )

        self.status_var.set(
            f"{machine_id} → "
            f"{load_percent:.0f}% "
            f"({target_power:.1f} kW) "
            f"for {duration}s"
        )

    def restore_normal(self):

        machine_id = self.machine_var.get()

        command = {
            "machine_id": machine_id,
            "command": "RESTORE_NORMAL"
        }

        self.node.send_command(command)

        self.status_var.set(
            f"{machine_id} → NORMAL"
        )


def main():

    rclpy.init()

    node = AnomalyInjectorNode()

    root = tk.Tk()

    AnomalyGUI(
        root,
        node
    )

    def ros_spin():

        rclpy.spin_once(
            node,
            timeout_sec=0.01
        )

        root.after(
            10,
            ros_spin
        )

    root.after(
        10,
        ros_spin
    )

    try:
        root.mainloop()

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
