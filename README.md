# INDUS_TWIN — PROJECT HANDOVER

## Important Codes :

## To Run overall system:

cd ~/INDUS_TWIN
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 launch gazebo_factory_twin factory_system.launch.py

## To run anamoly injector 

cd ~/INDUS_TWIN
source /opt/ros/jazzy/setup.bash
source install/setup.bash

python3 anomaly_injector.py

## PROJECT

INDUS_TWIN is a ROS 2 + Gazebo industrial digital twin for:

Industrial Energy-Waste Recovery and Grid-Resilient Manufacturing.

Core idea:

Energy waste detection
→ Recoverable flexibility
→ Production impact check
→ Virtual energy reserve
→ Grid-response optimization


## ENVIRONMENT

Ubuntu 24.04
ROS 2 Jazzy
Gazebo Sim
Python 3
Apache Spark

Project:

~/INDUS_TWIN

Keep separate from:

~/ros2_ws


## CURRENT FACTORY

Seven machines:

CNC_01
CNC_02
CNC_03
COMP_01
PUMP_01
HVAC_01
FURNACE_01

Gazebo world:

src/gazebo_factory_twin/worlds/factory_floor.sdf

ROS 2 factory node:

src/gazebo_factory_twin/gazebo_factory_twin/factory_twin_node.py


## ROS 2 TOPICS

Machine telemetry:

/factory/machine_state

Total factory power:

/factory/total_power_kw

Events:

/factory/events

Grid stress:

/factory/grid_stress_kw

Control:

/factory/control_command


## MACHINE TELEMETRY

Current telemetry fields:

timestamp
machine_id
state
power_kw
energy_kwh
load_percent
temperature
vibration
rpm
production_rate
units_produced
criticality
grid_stress_kw

Live telemetry rate:

~1 second


## MACHINE TELEMETRY CSV

File:

data/02_operations/machine_telemetry.csv

Schema:

timestamp,machine_id,state,power_kw,energy_kwh,load_percent,temperature_c,vibration_mm_s,rpm,production_rate,units_produced

Status:

WORKING

Historical logging:

~1 minute

7 machine records are written approximately every minute.


## PRODUCTION DATA CSV

File:

data/02_operations/production_data.csv

Schema:

timestamp,production_line,machine_id,product_id,target_units,actual_units,cycle_time_sec,downtime_sec,defect_count,quality_percent

Status:

WORKING

7 production records are written approximately every minute.


## LOGGERS

Telemetry logger:

src/gazebo_factory_twin/gazebo_factory_twin/telemetry_logger.py

Production logger:

src/gazebo_factory_twin/gazebo_factory_twin/production_logger.py

Both subscribe to:

/factory/machine_state


## FACTORY DATA

data/01_factory/factory_metadata.json

data/01_factory/machine_metadata.csv

data/01_factory/machine_constraints.csv

data/03_maintenance/maintenance_events.csv

data/04_grid/grid_data.csv

data/05_scenarios/scenario_data.csv


## CONTROL COMMANDS

SET_LOAD

Used for anomaly injection.

Example:

{
  "machine_id": "COMP_01",
  "command": "SET_LOAD",
  "load_percent": 110,
  "duration_sec": 60
}

REDUCE_LOAD

Used later by optimization/grid-response.

RESTORE_NORMAL

Returns machine to normal.


## ANOMALY INJECTOR

File:

~/INDUS_TWIN/anomaly_injector.py

Technology:

Python + Tkinter + ROS 2

Purpose:

Select machine
Select anomaly
Set target load using slider
Set duration
Inject anomaly
Restore normal

Current anomaly types:

Power Overload
Excessive Energy Consumption

Current load range:

50% to 130%

The anomaly injector has already been tested successfully.

Example:

COMP_01
~50 kW normal
→ ~56 kW
→ >110% load
→ ANOMALY


## BUILD

cd ~/INDUS_TWIN
source /opt/ros/jazzy/setup.bash
colcon build --packages-select gazebo_factory_twin --symlink-install
source install/setup.bash


## RUN FACTORY

source /opt/ros/jazzy/setup.bash
source ~/INDUS_TWIN/install/setup.bash

ros2 launch gazebo_factory_twin factory_twin.launch.py


## RUN TELEMETRY LOGGER

ros2 run gazebo_factory_twin telemetry_logger


## RUN PRODUCTION LOGGER

ros2 run gazebo_factory_twin production_logger


## VIEW TELEMETRY

ros2 topic echo /factory/machine_state


## PROJECT STATUS

DONE:

Gazebo factory
7-machine ROS 2 digital twin
Live telemetry
machine_telemetry.csv
production_data.csv
1-minute logging
SET_LOAD
REDUCE_LOAD
RESTORE_NORMAL
Tkinter anomaly injector


## NEXT FACTORY-SIDE TASK

Create one combined launch file:

factory_system.launch.py

Goal:

ros2 launch gazebo_factory_twin factory_system.launch.py

It should start:

Gazebo
Factory Twin
Telemetry Logger
Production Logger


# AI TEAM HANDOVER

The factory/simulation side is already working.

DO NOT rebuild the ROS 2 factory unnecessarily.

AI should consume live telemetry from:

/factory/machine_state

and use:

machine_telemetry.csv
production_data.csv
machine_metadata.csv
machine_constraints.csv
maintenance_events.csv
grid_data.csv
scenario_data.csv


## AI DATA

Recommended new directory:

data/06_ai/

Recommended derived feature file:

data/06_ai/ai_features.csv

Do not create unnecessary duplicate raw sensor CSV files.


## IMPORTANT AI FEATURES

power deviation
expected vs actual power
energy per unit
production efficiency
rolling power statistics
rolling production statistics
temperature deviation
vibration deviation
overload flag
idle-energy flag
shift
time of day
machine criticality
grid stress


## AI OUTPUTS

The AI should eventually output:

anomaly_score
anomaly_type
confidence
expected_power_kw
actual_power_kw
excess_power_kw
energy_waste
production_impact
recoverable_flexibility_kw
recommended_action


## AI MAIN QUESTIONS

1. Is the machine behaving abnormally?

2. How much energy is being wasted compared with its expected behaviour?

3. How much demand can safely be reduced without unacceptable production impact?


## AI PIPELINE

Historical data
+
Live/simulated data
↓
Feature engineering
↓
Machine-specific baseline
↓
Anomaly detection
↓
Energy-waste estimation
↓
Production-impact prediction
↓
Flexibility estimation
↓
Live inference


## IMPORTANT PROJECT CONCEPT

The AI should NOT only detect faults.

It should connect:

Machine condition
+
Energy consumption
+
Production behaviour

to determine:

Energy waste
+
Safe demand flexibility
+
Production impact.


## FINAL TARGET ARCHITECTURE

Gazebo Factory
↓
ROS 2 Factory Twin
↓
Live Telemetry
↓
AI Intelligence
↓
Energy-Waste Detection
↓
Production Impact
↓
Recoverable Flexibility
↓
Virtual Energy Reserve
↓
Optimization
↓
ROS 2 Control
↓
Factory Response