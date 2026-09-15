# run_pipeline.py
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Use current Python interpreter (important for venvs)
PYTHON = sys.executable

steps = [
    ("Feature Engineering", BASE_DIR / "feature_engineering.py"),  # 🔥 FIRST STEP

    ("Baseline", BASE_DIR / "save_baseline.py"),
    ("Anomaly detection", BASE_DIR / "anomaly.py"),
    ("Forecasting", BASE_DIR / "forecasting.py"),
    ("Maintenance", BASE_DIR / "maintenance.py"),
    ("Flexibility", BASE_DIR / "flexibility.py"),
    ("Production impact", BASE_DIR / "production_impact.py"),
    ("Feature Engineering", BASE_DIR / "feature_engineering.py"),
    ("Final decision", BASE_DIR / "final_decision.py"),
]


def run_step(name, script_path):
    print(f"\n🔷 Running: {name}")
    start_time = time.time()

    result = subprocess.run(
        [PYTHON, str(script_path)],
        capture_output=True,
        text=True
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print("⚠️ STDERR:")
        print(result.stderr)

    if result.returncode != 0:
        print(f"❌ Step FAILED: {name}")
        sys.exit(result.returncode)

    duration = time.time() - start_time
    print(f"✅ Completed: {name} ({duration:.2f}s)")


def run_pipeline():
    print("\n🚀 Starting INDUS_TWIN AI Pipeline...\n")

    for name, script in steps:
        if not script.exists():
            print(f"❌ Missing file: {script}")
            sys.exit(1)

        run_step(name, script)

    print("\n🎯 Pipeline completed successfully!")


if __name__ == "__main__":
    run_pipeline()