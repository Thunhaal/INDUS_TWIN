# feature_engineering.py
import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
OPS_DIR = DATA_DIR / "02_operations"
AI_DIR = DATA_DIR / "06_ai"

TELEMETRY_FILE = OPS_DIR / "machine_telemetry.csv"
PRODUCTION_FILE = OPS_DIR / "production_data.csv"
OUT_FILE = AI_DIR / "ai_features.csv"

EPS = 1e-6  # numerical stability


def compute_features():
    if not TELEMETRY_FILE.exists():
        print("Telemetry file missing.")
        return pd.DataFrame()

    telemetry = pd.read_csv(TELEMETRY_FILE).rename(columns=str.strip)

    production = (
        pd.read_csv(PRODUCTION_FILE).rename(columns=str.strip)
        if PRODUCTION_FILE.exists()
        else pd.DataFrame()
    )

    # ---- Merge ----
    if not production.empty and set(["timestamp", "machine_id"]).issubset(production.columns):
        df = pd.merge(telemetry, production, on=["timestamp", "machine_id"], how="left")
    else:
        df = telemetry.copy()

    # ---- Safety columns ----
    for col in ["power_kw", "temperature_c", "vibration_mm_s", "units_produced"]:
        if col not in df.columns:
            df[col] = 0.0

    # ---- Feature Engineering ----

    # 1. Rolling baseline
    df["rolling_power_mean"] = df.groupby("machine_id")["power_kw"].transform(
        lambda x: x.rolling(10, min_periods=1).mean()
    )

    # 2. Power deviation
    df["power_deviation"] = df["power_kw"] - df["rolling_power_mean"]

    # 3. Efficiency (output/input)
    df["efficiency"] = df["units_produced"] / (df["power_kw"] + EPS)

    # 4. Energy intensity (input/output)
    df["energy_per_unit"] = df["power_kw"] / (df["units_produced"] + EPS)

    # 5. Temperature deviation
    df["temp_mean"] = df.groupby("machine_id")["temperature_c"].transform("mean")
    df["temp_deviation"] = df["temperature_c"] - df["temp_mean"]

    # 6. Vibration deviation
    df["vib_mean"] = df.groupby("machine_id")["vibration_mm_s"].transform("mean")
    df["vibration_deviation"] = df["vibration_mm_s"] - df["vib_mean"]

    # 7. Rolling std (stability indicator)
    df["power_std"] = df.groupby("machine_id")["power_kw"].transform(
        lambda x: x.rolling(10, min_periods=1).std().fillna(0)
    )

    # 8. Overload flag
    df["overload_flag"] = (df["power_kw"] > df["rolling_power_mean"] * 1.2).astype(int)

    # 9. Idle energy flag
    df["idle_flag"] = ((df["units_produced"] == 0) & (df["power_kw"] > 0)).astype(int)

    # 10. Time feature (SAFE)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").fillna(0)
        df["hour"] = (df["timestamp"] // 3600) % 24
    else:
        df["timestamp"] = 0
        df["hour"] = 0

    # 11. Grid stress proxy
    df["grid_stress"] = df["power_kw"] / (df["rolling_power_mean"] + EPS)

    # ---- Final selection ----
    out = df[[
        "timestamp",
        "machine_id",
        "power_kw",
        "units_produced",
        "power_deviation",
        "efficiency",
        "energy_per_unit",
        "temp_deviation",
        "vibration_deviation",
        "power_std",
        "overload_flag",
        "idle_flag",
        "hour",
        "grid_stress"
    ]].copy()

    # ---- Save ----
    AI_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_FILE, index=False)

    print(f"Saved AI features -> {OUT_FILE} ({len(out)} rows)")
    return out


if __name__ == "__main__":
    compute_features()