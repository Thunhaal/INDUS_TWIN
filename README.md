# INDUS_TWIN

## Gazebo Factory Twin

This is a standalone ROS 2 Jazzy + Gazebo factory simulator. Gazebo renders five colour-coded machines on a factory floor; the ROS node emits realistic power, energy, temperature, vibration, RPM, production and operating state for each machine every second.

## Build and launch

From the repository root:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --packages-select gazebo_factory_twin --symlink-install
source install/setup.bash
ros2 launch gazebo_factory_twin factory_twin.launch.py
```

Gazebo opens as the visual factory model. The Python node is your sensor/PLC simulator.

## Inspect the sensor data

Open a second terminal, source the same environments, then:

```bash
ros2 topic echo /factory/machine_state
ros2 topic echo /factory/total_power_kw
ros2 topic echo /factory/events
```

## Demo a grid event

```bash
ros2 topic pub --once /factory/grid_stress_kw std_msgs/msg/Float64 "{data: 25.0}"
```

## Demo a control response

This reduces the compressor to 40 kW for 20 minutes; its subsequent telemetry changes to `REDUCED`.

```bash
ros2 topic pub --once /factory/control_command std_msgs/msg/String "{data: '{\"machine_id\": \"COMP_01\", \"command\": \"REDUCE_LOAD\", \"target_kw\": 40, \"duration_sec\": 1200}'}"
```

## Fixed output contract

`/factory/machine_state` contains one JSON message per machine with this interface:

```json
{"timestamp": 1725340000, "machine_id": "COMP_01", "power_kw": 48.2, "energy_kwh": 124.6, "temperature": 71.4, "vibration": 0.32, "rpm": 1450, "production_rate": 18, "state": "RUNNING", "criticality": "MEDIUM"}
```
