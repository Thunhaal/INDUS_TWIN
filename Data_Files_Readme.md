File Structure:

IndusTwin/
│
├── README.md
├── Data_Files_Readme.md [This File]
│
├── data/
│   ├── 01_factory/
│   │   ├── factory_metadata.json [Overall factory-level information]
│   │   ├── machine_metadata.csv[MachineID and its configurations]
│   │   └── machine_constraints.csv[Constrains for each machine to avoid downtime during any failure or anamolies]
│   │
│   ├── 02_operations/
│   │   ├── machine_telemetry.csv[Real time Data stored here]
│   │   └── production_data.csv[Tells Usual Production Data]
│   │
│   ├── 03_maintenance/
│   │   └── maintenance_events.csv
│   │   └── info.txt[Contains Possible Debugged Descriptions]
|   | 
│   ├── 04_grid/
│   │   └── grid_data.csv [External electrical-grid conditions]
│   │
│   └── 05_scenarios/
│       └── scenario_data.csv
│
├── ros2_ws/
│   └── src/
│       └── factory_sim/
│
├── ai_engine/
│
├── optimization/
│
├── dashboard/
│
├── config/
│
└── docs/
