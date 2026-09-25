# INDUS_TWIN

## Industrial Energy Digital Twin with Energy-Waste Recovery Mapping for Grid-Resilient Manufacturing

INDUS_TWIN is a simulation-driven industrial energy management and digital-twin platform that models a manufacturing factory, machine operating states, production behavior, maintenance events, grid conditions, anomalies, and AI-assisted energy flexibility decisions.

The system combines:

- **ROS 2 Jazzy** for the factory digital twin and machine-state communication
- **Gazebo** for factory simulation
- **FastAPI** for backend APIs
- **React + Vite** for the web dashboard
- **Python AI modules** for anomaly detection, forecasting, maintenance risk, production impact, flexibility analysis, and control decisions
- **OR-Tools** for constrained optimization
- **Tkinter** for interactive anomaly injection
- **CSV-based runtime data logging** for telemetry, production, maintenance, grid, scenarios, and AI features

---

# 1. System Overview

INDUS_TWIN represents a simulated industrial factory containing seven machines:

| Machine | Type |
|---|---|
| CNC_01 | Production |
| CNC_02 | Production |
| CNC_03 | Production |
| COMP_01 | Utility / Process |
| PUMP_01 | Utility / Process |
| HVAC_01 | Utility / Process |
| FURNACE_01 | Utility / Process |

The digital twin continuously produces machine telemetry and factory operating information.

The platform then connects this information to the AI pipeline and dashboard.

```text
                    ┌──────────────────────┐
                    │   Gazebo Factory     │
                    │    Digital Twin      │
                    └──────────┬───────────┘
                               │
                               │ ROS 2
                               ▼
                    ┌──────────────────────┐
                    │     Telemetry /      │
                    │   Factory ROS Nodes  │
                    └──────────┬───────────┘
                               │
                 ┌─────────────┼─────────────┐
                 │             │             │
                 ▼             ▼             ▼
          Operations       Grid Data     Scenarios
             │
             ▼
       ┌───────────────────┐
       │   AI Pipeline     │
       │                   │
       │ Feature Engineer  │
       │ Baseline          │
       │ Anomaly           │
       │ Forecasting       │
       │ Maintenance Risk  │
       │ Production Impact │
       │ Flexibility       │
       │ Final Decision    │
       └─────────┬─────────┘
                 │
                 ▼
       ┌───────────────────┐
       │   FastAPI Backend  │
       └─────────┬─────────┘
                 │
                 ▼
       ┌───────────────────┐
       │ React / Vite UI   │
       │   INDUS_TWIN      │
       └───────────────────┘

       Tkinter Anomaly Injector
                 │
                 └──────► ROS 2 Factory Control
```

---

# 2. Main Features

## Factory Digital Twin

The ROS 2 factory twin models the lifecycle of all seven machines.

Machine states include:

- `RUNNING`
- `IDLE`
- `MAINTENANCE`
- `FAULT`

The factory twin publishes machine telemetry and responds to control commands.

---

## Persistent Anomaly Detection

The anomaly system uses a rolling persistence window.

Current logic:

```text
Rolling window = 8 telemetry readings
Persistent anomaly = 6 or more abnormal readings out of 8
```

Severity determines the resulting machine state:

```text
HIGH / CRITICAL
        ↓
      FAULT

LOW / MEDIUM
        ↓
       IDLE
```

Faulted or idle machines remain in their corresponding state until maintenance handling restores them.

---

# 3. Maintenance Lifecycle

Maintenance events are handled through a ticket lifecycle.

```text
SUBMITTED
    │
    ▼
ONGOING
    │
    ▼
COMPLETED
```

A maintenance ticket can also be reopened:

```text
ONGOING
   │
   ▼
SUBMITTED
```

Maintenance commands are connected to the ROS 2 factory.

Typical behavior:

```text
MAINTENANCE_START
        ↓
Machine enters MAINTENANCE

MAINTENANCE_COMPLETE
        ↓
Machine returns to RUNNING
```

The maintenance event manager records ticket information in:

```text
data/03_maintenance/maintenance_events.csv
```

---

# 4. AI Pipeline

The AI pipeline is organized into eight stages.

```text
1. Feature Engineering
        ↓
2. Baseline
        ↓
3. Anomaly Detection
        ↓
4. Forecasting
        ↓
5. Maintenance Risk
        ↓
6. Production Impact
        ↓
7. Flexibility Analysis
        ↓
8. Final Decision
```

## 4.1 Feature Engineering

Creates the feature set used by downstream AI modules from machine and operational data.

File:

```text
ai_engine/feature_engineering.py
```

---

## 4.2 Baseline

Establishes baseline operating behavior for the factory and machines.

Files:

```text
ai_engine/baseline.py
ai_engine/save_baseline.py
```

---

## 4.3 Anomaly Detection

Identifies abnormal machine operating behavior.

File:

```text
ai_engine/anomaly.py
```

Output:

```text
anomaly_output.csv
```

Generated outputs are excluded from the Git repository.

---

## 4.4 Forecasting

Produces energy/operational forecasts used by the decision pipeline.

File:

```text
ai_engine/forecasting.py
```

---

## 4.5 Maintenance Risk

Estimates maintenance-related risk based on machine behavior.

File:

```text
ai_engine/maintenance.py
```

The maintenance event manager connects detected conditions to maintenance tickets.

File:

```text
ai_engine/maintenance_event_manager.py
```

---

## 4.6 Production Impact

Estimates how machine conditions and energy-control actions affect production.

File:

```text
ai_engine/production_impact.py
```

---

## 4.7 Flexibility Analysis

Determines how much energy demand can be safely reduced while respecting operational constraints.

File:

```text
ai_engine/flexibility.py
```

---

## 4.8 Final Decision

Combines the AI results into a final control decision.

File:

```text
ai_engine/final_decision.py
```

The pipeline also contains:

```text
ai_engine/control_safety.py
```

which provides the safety validation layer for control actions.

---

# 5. Constrained Energy Optimization

INDUS_TWIN includes an optimizer for safe energy flexibility deployment.

File:

```text
ai_engine/optimizer.py
```

The optimizer considers machine controllability and operational constraints before recommending load reduction.

The project also includes a safety layer that evaluates:

```text
Maintenance Risk
        +
Production Constraints
        +
Machine Controllability
        ↓
Safe Control Decision
```

This prevents energy-control actions from blindly targeting machines that should remain operational.

---

# 6. What-If Simulator

The dashboard includes a What-If Simulator for scenario analysis.

The simulator is designed to explore the effect of operational changes before applying live controls.

Examples include:

- One machine outage
- Two machine outages
- Multiple machine outages
- Machine anomaly
- Different anomaly severity
- Renewable availability changes
- Grid reduction targets
- Combinations of the above

The simulator presents scenario effects such as:

- Power demand
- Energy use
- Production
- Good production
- Quality
- Downtime
- Grid import
- Machine-level consequences
- Safe flexibility
- Grid shortfall
- AI decision reasoning
- Safety envelope

The What-If simulation is separate from the live scenario controls. A What-If calculation does not automatically modify the factory.

---

# 7. Anomaly Injection Console

The anomaly injector is located at:

```text
tools/anomaly_injector.py
```

It is a Tkinter GUI connected to ROS 2.

The console supports:

- Machine selection
- Single-machine anomaly injection
- Multi-machine anomaly injection
- Anomaly type selection
- Severity selection
- Load adjustment
- Temperature adjustment
- Vibration adjustment
- Duration control
- Live machine monitoring
- Persistence monitoring
- Factory event logging

Example anomaly profiles include:

```text
HIGH_LOAD
THERMAL_OVERLOAD
VIBRATION_SPIKE
POWER_SURGE
```

The injector publishes commands through:

```text
/factory/control_command
```

and subscribes to factory state/event topics.

---

# 8. Backend

The backend is implemented with FastAPI.

Main backend file:

```text
dashboard/backend/main.py
```

Start the backend using:

```bash
cd ~/INDUS_TWIN
source .venv/bin/activate

python -m uvicorn dashboard.backend.main:app \
  --host 0.0.0.0 \
  --port 8000
```

Backend address:

```text
http://localhost:8000
```

FastAPI documentation:

```text
http://localhost:8000/docs
```

The backend exposes APIs for dashboard data including:

- Machine telemetry
- Production
- Quality
- Maintenance
- Grid data
- Scenario data
- AI data
- Analytics
- What-If simulation
- Control/scenario operations

---

# 9. Frontend

The dashboard is implemented using React and Vite.

Directory:

```text
dashboard/frontend/
```

Important files:

```text
dashboard/frontend/
├── index.html
├── package.json
├── package-lock.json
├── vite.config.js
├── public/
└── src/
```

The frontend communicates with the FastAPI backend.

Start the dashboard:

```bash
cd ~/INDUS_TWIN/dashboard/frontend
npm run dev -- --host 0.0.0.0
```

Dashboard address:

```text
http://localhost:5173
```

---

# 10. ROS 2 Factory

The ROS 2 package is located under:

```text
src/gazebo_factory_twin/
```

Important package files/directories include:

```text
src/gazebo_factory_twin/
├── gazebo_factory_twin/
├── launch/
├── worlds/
├── resource/
├── package.xml
├── setup.py
└── setup.cfg
```

The factory launch file is:

```text
indus_twin.launch.py
```

Launch the factory:

```bash
cd ~/INDUS_TWIN

source /opt/ros/jazzy/setup.bash
source ~/INDUS_TWIN/install/setup.bash

ros2 launch gazebo_factory_twin indus_twin.launch.py
```

If `install/` does not exist after cloning the repository, build the workspace first:

```bash
cd ~/INDUS_TWIN

source /opt/ros/jazzy/setup.bash

colcon build
```

Then:

```bash
source install/setup.bash
```

---

# 11. Data Architecture

Runtime data is organized under:

```text
data/
```

## Factory Data

```text
data/01_factory/
├── factory_metadata.json
├── machine_constraints.csv
└── machine_metadata.csv
```

These files describe the simulated factory and machine configuration.

---

## Operations Data

```text
data/02_operations/
├── machine_metadata.csv
├── machine_telemetry.csv
├── production_data.csv
└── quality_inspection.csv
```

`machine_metadata.csv` contains machine metadata.

The telemetry and production files are runtime-generated operational data.

---

## Maintenance Data

```text
data/03_maintenance/
├── info.txt
└── maintenance_events.csv
```

This stores maintenance-event records.

---

## Grid Data

```text
data/04_grid/
└── grid_data.csv
```

This stores simulated grid-related runtime data.

---

## Scenario Data

```text
data/05_scenarios/
└── scenario_data.csv
```

This stores scenario execution data.

---

## AI Features

```text
data/06_ai/
└── ai_features.csv
```

This stores the generated feature dataset used by the AI pipeline.

---

# 12. Factory Configuration

Global scenario configuration:

```text
config/scenarios.json
```

Factory metadata and machine constraints are stored under:

```text
data/01_factory/
```

This separates configuration from generated operational data.

---

# 13. Project File Structure

The important repository structure is:

```text
INDUS_TWIN/
│
├── ai_engine/
│   ├── ai_api.py
│   ├── anomaly.py
│   ├── baseline.py
│   ├── control_safety.py
│   ├── feature_engineering.py
│   ├── final_decision.py
│   ├── flexibility.py
│   ├── forecasting.py
│   ├── maintenance.py
│   ├── maintenance_event_manager.py
│   ├── optimizer.py
│   ├── production_impact.py
│   ├── production_quality.py
│   ├── quality_inspection.py
│   ├── run_pipeline.py
│   ├── save_baseline.py
│   ├── requirements.txt
│   └── streamlit_dashboard.py
│
├── config/
│   └── scenarios.json
│
├── data/
│   ├── 01_factory/
│   ├── 02_operations/
│   ├── 03_maintenance/
│   ├── 04_grid/
│   ├── 05_scenarios/
│   └── 06_ai/
│
├── dashboard/
│   ├── backend/
│   │   └── main.py
│   │
│   └── frontend/
│       ├── index.html
│       ├── package.json
│       ├── package-lock.json
│       ├── vite.config.js
│       ├── public/
│       └── src/
│
├── src/
│   └── gazebo_factory_twin/
│       ├── gazebo_factory_twin/
│       ├── launch/
│       ├── worlds/
│       ├── resource/
│       ├── package.xml
│       ├── setup.py
│       └── setup.cfg
│
├── tools/
│   └── anomaly_injector.py
│
├── anomaly_injector.py
├── Data_Files_Readme.md
├── README.md
├── requirements.txt
├── .gitignore
└── start_indus_twin.sh
```

Generated directories such as:

```text
build/
install/
log/
node_modules/
dist/
__pycache__/
```

are not source-code components and should remain excluded from Git.

The Python virtual environment is also kept local and excluded from Git:

```text
.venv/
```

---

# 14. One-Command Launcher

The project includes:

```text
start_indus_twin.sh
```

It opens separate terminals for the main components.

Run:

```bash
cd ~/INDUS_TWIN
chmod +x start_indus_twin.sh
./start_indus_twin.sh
```

The launcher starts:

```text
1. FastAPI Backend
2. React Frontend
3. ROS 2 Factory Twin
4. tools/anomaly_injector.py
```

The individual commands remain available if manual startup is preferred.

---

# 15. Manual Startup

## Terminal 1 — Backend

```bash
cd ~/INDUS_TWIN
source .venv/bin/activate

python -m uvicorn dashboard.backend.main:app \
  --host 0.0.0.0 \
  --port 8000
```

## Terminal 2 — Frontend

```bash
cd ~/INDUS_TWIN/dashboard/frontend

npm run dev -- --host 0.0.0.0
```

## Terminal 3 — ROS 2 Factory

```bash
cd ~/INDUS_TWIN

source /opt/ros/jazzy/setup.bash
source ~/INDUS_TWIN/install/setup.bash

ros2 launch gazebo_factory_twin indus_twin.launch.py
```

## Terminal 4 — Anomaly Injector

```bash
cd ~/INDUS_TWIN
source .venv/bin/activate

python tools/anomaly_injector.py
```

---

# 16. Typical Data Flow

A typical anomaly-to-decision workflow is:

```text
User selects machine
        ↓
Tkinter Anomaly Injector
        ↓
ROS 2 control command
        ↓
Factory Twin changes machine telemetry
        ↓
Telemetry Logger records data
        ↓
AI Feature Engineering
        ↓
Anomaly Detection
        ↓
Persistence Evaluation
        ↓
Maintenance Risk
        ↓
Production Impact
        ↓
Flexibility Analysis
        ↓
Safety Validation
        ↓
Final Decision
        ↓
FastAPI
        ↓
React Dashboard
```

For a persistent severe anomaly:

```text
Abnormal readings
      ↓
6 / 8 persistence
      ↓
HIGH / CRITICAL
      ↓
FAULT
      ↓
Maintenance ticket
      ↓
SUBMITTED
      ↓
ONGOING
      ↓
MAINTENANCE
      ↓
COMPLETED
      ↓
RUNNING
```

---

# 17. Grid-Resilience Workflow

The energy flexibility workflow is:

```text
Grid Scenario
      ↓
Current Factory Demand
      ↓
Machine Constraints
      ↓
Maintenance Risk
      ↓
Production Constraints
      ↓
Machine Controllability
      ↓
Optimization
      ↓
Safe Deployable Flexibility
      ↓
Control Decision
```

The system can distinguish between:

```text
Required Grid Reduction
        vs
Safe Deployable Flexibility
```

This allows the dashboard to show both the requested grid response and the amount that can actually be deployed without violating operational constraints.

---

# 18. Maintenance and Production Interaction

Production impact is treated as an operational constraint rather than evaluating energy savings alone.

Conceptually:

```text
Energy Reduction
      +
Production Impact
      +
Quality Impact
      +
Downtime
      +
Maintenance Risk
      ↓
Control Safety
```

This provides a basis for evaluating energy actions in the context of factory operations.

---

# 19. Runtime Files vs Source Files

## Source / Configuration

These should remain in the repository:

```text
ai_engine/*.py
config/
data/01_factory/
dashboard/
src/
tools/
README.md
Data_Files_Readme.md
requirements.txt
.gitignore
start_indus_twin.sh
```

## Generated / Runtime

These are generated while the system runs and should not be committed:

```text
build/
install/
log/
.venv/
node_modules/
dist/
__pycache__/
*.pyc
```

AI output CSV files are also runtime-generated:

```text
ai_engine/*_output.csv
```

and are excluded through `.gitignore`.

---

# 20. Requirements

The project expects the following major runtime components:

- Ubuntu/Linux environment
- ROS 2 Jazzy
- Gazebo
- Python
- Python virtual environment
- FastAPI / Uvicorn
- React
- Vite
- Node.js / npm
- Pandas
- NumPy
- Scikit-learn where required by the AI modules
- OR-Tools

Python dependencies are listed in:

```text
requirements.txt
```

The AI directory also contains:

```text
ai_engine/requirements.txt
```

Use the project requirements file appropriate to the environment being configured.

---

# 21. Fresh Clone Setup

After cloning the repository:

```bash
git clone <YOUR_REPOSITORY_URL>
cd INDUS_TWIN
```

Create/activate the Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Install frontend dependencies:

```bash
cd dashboard/frontend
npm install
cd ../..
```

Build the ROS 2 package:

```bash
source /opt/ros/jazzy/setup.bash
colcon build
```

Source the generated workspace:

```bash
source install/setup.bash
```

Then launch the system.

---

# 22. Useful URLs

When the system is running:

### Dashboard

```text
http://localhost:5173
```

### FastAPI

```text
http://localhost:8000
```

### FastAPI Swagger UI

```text
http://localhost:8000/docs
```

---

# 23. Common Troubleshooting

## `install/setup.bash` not found

Build the ROS workspace:

```bash
cd ~/INDUS_TWIN
source /opt/ros/jazzy/setup.bash
colcon build
source install/setup.bash
```

---

## Backend does not start

Check that the virtual environment exists:

```bash
ls ~/INDUS_TWIN/.venv/bin/activate
```

Then:

```bash
cd ~/INDUS_TWIN
source .venv/bin/activate
python -m uvicorn dashboard.backend.main:app --host 0.0.0.0 --port 8000
```

---

## Frontend does not start

Go to:

```bash
cd ~/INDUS_TWIN/dashboard/frontend
```

Install dependencies if necessary:

```bash
npm install
```

Then:

```bash
npm run dev -- --host 0.0.0.0
```

---

## Anomaly Injector does not start

Use the current injector:

```bash
cd ~/INDUS_TWIN
source .venv/bin/activate
python tools/anomaly_injector.py
```

---

## ROS 2 commands not found

Source ROS 2:

```bash
source /opt/ros/jazzy/setup.bash
```

Then source the workspace:

```bash
source ~/INDUS_TWIN/install/setup.bash
```

---

# 24. Git Repository Hygiene

Do not commit:

```text
.venv/
build/
install/
log/
node_modules/
dist/
__pycache__/
*.pyc
AI generated output CSVs
runtime telemetry
runtime production data
runtime grid/scenario data
```

The repository should contain the reproducible source code, configuration, factory definitions, and documentation rather than local environments and temporary runtime artifacts.

---

# 25. Project Philosophy

INDUS_TWIN is designed around the idea that industrial energy management should not be treated as a simple load-shedding problem.

An energy action must be evaluated together with:

```text
Factory State
+
Machine Health
+
Maintenance Risk
+
Production
+
Quality
+
Downtime
+
Grid Conditions
+
Machine Controllability
```

The digital twin provides the simulated operational environment.

ROS 2 provides machine and control communication.

The AI pipeline transforms telemetry into operational insights.

Optimization finds constrained flexibility.

Safety validation determines whether a control action is acceptable.

FastAPI exposes the system to the dashboard.

React provides the operator-facing interface.

Together, these components form the INDUS_TWIN industrial energy digital-twin workflow.
