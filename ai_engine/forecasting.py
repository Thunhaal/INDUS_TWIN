import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data/02_operations"

TELEMETRY_FILE = DATA_DIR / "machine_telemetry.csv"
OUT_FILE = BASE_DIR / "forecast_output.csv"

def forecast_for_machine(df_machine, horizons_min=[15,30,60]):
    if "timestamp" not in df_machine.columns or len(df_machine) < 3:
        last = float(df_machine["power_kw"].iloc[-1]) if len(df_machine) > 0 else 0.0
        return {f"pred_{m}min": last for m in horizons_min}

    dfm = df_machine.sort_values("timestamp").tail(30)

    x = pd.to_numeric(dfm["timestamp"], errors="coerce").fillna(0).values
    y = dfm["power_kw"].astype(float).values

    # 🔒 stability safeguard
    if len(x) < 3 or np.all(x == x[0]):
        return {f"pred_{m}min": float(y[-1]) for m in horizons_min}

    x0 = x.mean()
    slope, intercept = np.polyfit(x - x0, y, 1)

    last_time = x[-1]
    preds = {}

    for m in horizons_min:
        t_future = last_time + m * 60
        preds[f"pred_{m}min"] = float(max(slope * (t_future - x0) + intercept, 0.0))

    return preds


def run_forecast(telemetry_df=None):
    if telemetry_df is None:
        if not Path(TELEMETRY_FILE).exists():
            print("Telemetry file not found.")
            return pd.DataFrame()
        telemetry_df = pd.read_csv(TELEMETRY_FILE).rename(columns=str.strip)

    rows = []

    for mid, grp in telemetry_df.groupby("machine_id"):
        grp_sorted = grp.sort_values("timestamp")

        last_row = grp_sorted.iloc[-1]
        preds = forecast_for_machine(grp_sorted)  # ✅ only once, correct input

        row = {
            "machine_id": mid,
            "last_power_kw": float(last_row["power_kw"])
        }
        row.update(preds)
        rows.append(row)

    out = pd.DataFrame(rows)

    Path(OUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_FILE, index=False)

    print(f"Saved forecast -> {OUT_FILE}")
    return out


if __name__ == "__main__":
    run_forecast()