#!/bin/bash

PROJECT=~/INDUS_TWIN

echo "Starting backend..."
gnome-terminal --title="INDUS_TWIN — Backend" -- bash -c "
cd '$PROJECT' || exit 1
source .venv/bin/activate
python -m uvicorn dashboard.backend.main:app \
  --host 0.0.0.0 \
  --port 8000
"

echo "Starting frontend..."
gnome-terminal --title="INDUS_TWIN — Frontend" -- bash -c "
cd '$PROJECT/dashboard/frontend' || exit 1
npm run dev -- --host 0.0.0.0
"

echo "Starting ROS2 factory..."
gnome-terminal --title="INDUS_TWIN — ROS2 Factory" -- bash -c "
cd '$PROJECT' || exit 1
source /opt/ros/jazzy/setup.bash
source ~/INDUS_TWIN/install/setup.bash
ros2 launch gazebo_factory_twin indus_twin.launch.py
"

echo "Starting anomaly injector..."
gnome-terminal --title="INDUS_TWIN — Anomaly Injector" -- bash -c "
cd '$PROJECT' || exit 1
source .venv/bin/activate
python tools/anomaly_injector.py
"
