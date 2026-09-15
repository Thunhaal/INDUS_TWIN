from pathlib import Path
import pandas as pd
from typing import Dict, Optional

DEFAULT_THRESHOLD_KW = 10.0

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data/02_operations"

TELEMETRY_FILE = DATA_DIR / "machine_telemetry.csv"
BASELINE_FILE = BASE_DIR / "baseline_output.csv"
OUT_FILE = BASE_DIR / "anomaly_output.csv"


def detect_anomalies(
    telemetry_df: pd.DataFrame,
    baseline_df: Optional[pd.DataFrame],
    threshold_kw: float = DEFAULT_THRESHOLD_KW,
    per_machine_thresholds: Optional[Dict[str, float]] = None
) -> pd.DataFrame:

    t = telemetry_df.copy().rename(columns=str.strip)
    b = baseline_df.copy().rename(columns=str.strip) if baseline_df is not None else pd.DataFrame()

    # --- Validate ---
    if "power_kw" not in t.columns:
        raise KeyError("telemetry missing required column 'power_kw'")

    t["power_kw"] = pd.to_numeric(t["power_kw"], errors="coerce").fillna(0.0)

    # --- Merge baseline ---
    if not b.empty and set(["machine_id", "state"]).issubset(b.columns):
        merged = pd.merge(t, b, on=["machine_id", "state"], how="left")
    elif not b.empty and "machine_id" in b.columns:
        merged = pd.merge(t, b, on="machine_id", how="left")
    else:
        merged = t.copy()
        merged["expected_power_kw"] = pd.NA

    # --- Ensure expected power ---
    merged["expected_power_kw"] = pd.to_numeric(
        merged.get("expected_power_kw"), errors="coerce"
    )

    merged["expected_power_kw_filled"] = merged["expected_power_kw"].fillna(merged["power_kw"])

    # --- Deviation ---
    merged["deviation_kw"] = merged["power_kw"] - merged["expected_power_kw_filled"]

    # --- Threshold logic ---
    def get_threshold(row):
        mid = row.get("machine_id")
        if per_machine_thresholds and mid in per_machine_thresholds:
            return float(per_machine_thresholds[mid])
        return float(threshold_kw)

    merged["threshold_kw"] = merged.apply(get_threshold, axis=1)

    # --- Anomaly detection ---
    merged["anomaly"] = merged["deviation_kw"].abs() > merged["threshold_kw"]

    # --- Type classification ---
    def classify(row):
        if row["deviation_kw"] > row["threshold_kw"]:
            return "OVERCONSUMPTION"
        elif row["deviation_kw"] < -row["threshold_kw"]:
            return "UNDERUTILIZATION"
        return "NORMAL"

    merged["anomaly_type"] = merged.apply(classify, axis=1)

    # --- Confidence score (NEW — important for AI output spec) ---
    merged["confidence"] = (
        merged["deviation_kw"].abs() / (merged["threshold_kw"] + 1e-6)
    ).clip(0, 5) / 5  # normalized 0–1

    # --- Final columns ---
    out_cols = [
        "timestamp",
        "machine_id",
        "state",
        "power_kw",
        "expected_power_kw",
        "deviation_kw",
        "threshold_kw",
        "anomaly",
        "anomaly_type",
        "confidence"
    ]

    out = merged[[c for c in out_cols if c in merged.columns]].copy()
    return out


# --- Pipeline entry ---
def run(threshold_kw: float = DEFAULT_THRESHOLD_KW):
    if not TELEMETRY_FILE.exists():
        print("Telemetry file not found.")
        return

    telemetry = pd.read_csv(TELEMETRY_FILE).rename(columns=str.strip)

    baseline = (
        pd.read_csv(BASELINE_FILE).rename(columns=str.strip)
        if BASELINE_FILE.exists()
        else None
    )

    df = detect_anomalies(telemetry, baseline, threshold_kw=threshold_kw)

    Path(OUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FILE, index=False)

    print(f"Wrote {OUT_FILE} ({int(df['anomaly'].sum())} anomalies flagged)")
    print("\n=== ANOMALY SAMPLE ===")
    print(df.head(20))


if __name__ == "__main__":
    run()