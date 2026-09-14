# flexibility.py
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_OPS_DIR = BASE_DIR.parent / "data/02_operations"
DATA_FACTORY_DIR = BASE_DIR.parent / "data/01_factory"

TELEMETRY_FILE = DATA_OPS_DIR / "machine_telemetry.csv"
CONSTRAINTS_FILE = DATA_FACTORY_DIR / "machine_constraints.csv"
OUT_FILE = BASE_DIR / "flexibility_output.csv"

def compute_flexibility(telemetry_df=None, constraints_df=None):
    if telemetry_df is None:
        if not Path(TELEMETRY_FILE).exists():
            print("Telemetry file not found.")
            return pd.DataFrame()
        telemetry_df = pd.read_csv(TELEMETRY_FILE).rename(columns=str.strip)

    if constraints_df is None and Path(CONSTRAINTS_FILE).exists():
        constraints_df = pd.read_csv(CONSTRAINTS_FILE).rename(columns=str.strip)
    elif constraints_df is None:
        constraints_df = pd.DataFrame()

    # use latest telemetry per machine
    telemetry_df["timestamp"] = pd.to_numeric(telemetry_df["timestamp"], errors="coerce").fillna(0)
    latest = telemetry_df.sort_values("timestamp").groupby("machine_id", as_index=False).last()
    if "power_kw" not in latest.columns:
        latest["power_kw"] = 0.0

    # merge constraints
    if not constraints_df.empty and "machine_id" in constraints_df.columns:
        df = latest.merge(constraints_df, on="machine_id", how="left")
    else:
        df = latest.copy()
        df["min_operating_power_kw"] = 0.0
        df["max_reduction_kw"] = 0.0
        df["max_curtailment_duration_min"] = pd.NA

    df["actual_power_kw"] = pd.to_numeric(df["power_kw"], errors="coerce").fillna(0.0)
    df["min_operating_power_kw"] = pd.to_numeric(df.get("min_operating_power_kw", 0.0), errors="coerce").fillna(0.0)
    df["max_reduction_kw"] = pd.to_numeric(df.get("max_reduction_kw", 0.0), errors="coerce").fillna(0.0)

    def compute_flex_val(r):
        available = max(0.0, r["actual_power_kw"] - r["min_operating_power_kw"])
        return min(r["max_reduction_kw"], available)

    df["flexible_power_kw"] = df.apply(compute_flex_val, axis=1)

    out = df[[
        "machine_id",
        "actual_power_kw",
        "min_operating_power_kw",
        "max_reduction_kw",
        "flexible_power_kw",
        "max_curtailment_duration_min"
    ]].copy()

    Path(OUT_FILE).parent.mkdir(parents=True, exist_ok=True)  # safe write
    out.to_csv(OUT_FILE, index=False)

    print(f"Saved flexibility -> {OUT_FILE}")
    return out

if __name__ == "__main__":
    compute_flexibility()