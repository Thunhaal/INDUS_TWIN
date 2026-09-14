# maintenance.py
import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data/02_operations"

TELEMETRY_FILE = DATA_DIR / "machine_telemetry.csv"
OUT_FILE = BASE_DIR / "maintenance_output.csv"

def compute_maintenance_risk(telemetry_df=None):
    if telemetry_df is None:
        if not Path(TELEMETRY_FILE).exists():
            print("Telemetry file not found.")
            return pd.DataFrame()
        telemetry_df = pd.read_csv(TELEMETRY_FILE).rename(columns=str.strip)

    df = telemetry_df.copy()

    # ensure required columns exist
    for col in ["temperature_c","vibration_mm_s","rpm"]:
        if col not in df.columns:
            df[col] = 0.0

    def zscore(s):
        std = s.std(ddof=0) if s.std(ddof=0) > 0 else 1.0
        return (s - s.mean()) / std

    df["z_temp"] = df.groupby("machine_id")["temperature_c"].transform(zscore)
    df["z_vib"] = df.groupby("machine_id")["vibration_mm_s"].transform(zscore)
    df["z_rpm"] = df.groupby("machine_id")["rpm"].transform(zscore)

    df["risk_raw"] = (
        df["z_temp"].abs() * 0.5 +
        df["z_vib"].abs() * 0.4 +
        df["z_rpm"].abs() * 0.1
    )

    df["maintenance_risk"] = df["risk_raw"].apply(lambda x: np.tanh(x / 3.0))

    def label(r):
        if r >= 0.7: return "HIGH"
        if r >= 0.4: return "MEDIUM"
        if r >= 0.15: return "LOW"
        return "NONE"

    df["maintenance_label"] = df["maintenance_risk"].apply(label)

    out = df[[
        "timestamp","machine_id",
        "temperature_c","vibration_mm_s","rpm",
        "maintenance_risk","maintenance_label"
    ]].copy()

    Path(OUT_FILE).parent.mkdir(parents=True, exist_ok=True)  # safe write
    out.to_csv(OUT_FILE, index=False)

    print(f"Saved maintenance -> {OUT_FILE}")
    return out

if __name__ == "__main__":
    compute_maintenance_risk()