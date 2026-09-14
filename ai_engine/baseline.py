# baseline.py
import pandas as pd
from pathlib import Path

# ✅ correct GitHub-safe paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data/02_operations"

TELEMETRY_FILE = DATA_DIR / "machine_telemetry.csv"
PRODUCTION_FILE = DATA_DIR / "production_data.csv"
OUT_FILE = BASE_DIR / "baseline_output.csv"

def compute_baseline(telemetry_df=None, production_df=None):
    """
    Return baseline DataFrame with columns ['machine_id','state','expected_power_kw'].
    If telemetry_df or production_df is None, reads CSVs from disk.
    """
    if telemetry_df is None:
        if not TELEMETRY_FILE.exists():
            return pd.DataFrame(columns=["machine_id","state","expected_power_kw"])
        telemetry_df = pd.read_csv(TELEMETRY_FILE).rename(columns=str.strip)

    if production_df is None and PRODUCTION_FILE.exists():
        production_df = pd.read_csv(PRODUCTION_FILE).rename(columns=str.strip)

    # Merge telemetry + production on timestamp+machine_id if both available
    if production_df is not None and "timestamp" in telemetry_df.columns and "timestamp" in production_df.columns:
        df = pd.merge(telemetry_df, production_df, on=["timestamp","machine_id"], how="left", suffixes=("","_prod"))
    else:
        df = telemetry_df.copy()

    # groupby machine+state to compute mean power
    if "machine_id" in df.columns and "state" in df.columns and "power_kw" in df.columns:
        baseline = df.groupby(["machine_id","state"], as_index=False)["power_kw"].mean().rename(columns={"power_kw":"expected_power_kw"})
    elif "machine_id" in df.columns and "power_kw" in df.columns:
        baseline = df.groupby(["machine_id"], as_index=False)["power_kw"].mean().rename(columns={"power_kw":"expected_power_kw"})
        baseline["state"] = "UNKNOWN"
    else:
        baseline = pd.DataFrame(columns=["machine_id","state","expected_power_kw"])

    return baseline


def save_baseline(out_file=OUT_FILE):
    baseline = compute_baseline()

    Path(out_file).parent.mkdir(parents=True, exist_ok=True)

    baseline.to_csv(out_file, index=False)
    print(f"Wrote {out_file} (rows): {len(baseline)}")
    return baseline


if __name__ == "__main__":
    save_baseline()