# save_baseline.py
import pandas as pd
import sys
from pathlib import Path

# ✅ consistent path setup (same as other modules)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data/02_operations"

TELEMETRY_FILE = DATA_DIR / "machine_telemetry.csv"
PRODUCTION_FILE = DATA_DIR / "production_data.csv"
OUT_FILE = BASE_DIR / "baseline_output.csv"

# load data
try:
    telemetry = pd.read_csv(TELEMETRY_FILE).rename(columns=str.strip)
    production = pd.read_csv(PRODUCTION_FILE).rename(columns=str.strip)
except FileNotFoundError:
    print("Missing CSV files in data/02_operations/")
    raise

# validate columns
if not {"machine_id", "power_kw", "state"}.issubset(telemetry.columns):
    print("machine_telemetry.csv missing required columns:", telemetry.columns.tolist())
    sys.exit(1)

if not {"machine_id", "timestamp"}.issubset(production.columns):
    print("production_data.csv missing some expected columns:", production.columns.tolist())

# merge
merge_on = ["timestamp", "machine_id"]

if all(c in telemetry.columns for c in merge_on) and all(c in production.columns for c in merge_on):
    df = pd.merge(telemetry, production, on=merge_on, how="left")
else:
    print("Falling back to telemetry-only baseline (no merge)")
    df = telemetry.copy()

# compute baseline
baseline = (
    df.groupby(["machine_id", "state"])["power_kw"]
    .mean()
    .reset_index()
    .rename(columns={"power_kw": "expected_power_kw"})
)

# save
Path(OUT_FILE).parent.mkdir(parents=True, exist_ok=True)
baseline.to_csv(OUT_FILE, index=False)

print(f"Wrote {OUT_FILE} (rows: {len(baseline)})")