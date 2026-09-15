# production_impact.py
import pandas as pd
from pathlib import Path

# ✅ GitHub-friendly paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

TELEMETRY_FILE = DATA_DIR / "machine_telemetry.csv"
PRODUCTION_FILE = DATA_DIR / "production_data.csv"
OUT_FILE = BASE_DIR / "production_impact_output.csv"

def estimate_production_impact(telemetry_df=None, production_df=None, reduce_kw=5.0, duration_min=15):
    if telemetry_df is None:
        if not Path(TELEMETRY_FILE).exists():
            return pd.DataFrame()
        telemetry_df = pd.read_csv(TELEMETRY_FILE).rename(columns=str.strip)

    if production_df is None and Path(PRODUCTION_FILE).exists():
        production_df = pd.read_csv(PRODUCTION_FILE).rename(columns=str.strip)

    latest = telemetry_df.sort_values("timestamp").groupby("machine_id", as_index=False).last()

    rows = []
    for _, r in latest.iterrows():
        mid = r["machine_id"]
        actual = float(r.get("power_kw", 0.0))

        # naive mapping: production_rate (units/min) to power; fallback small number
        prod_rate = float(r.get("production_rate") or 0.0)

        if prod_rate <= 0:
            est_units_per_min = 0.001
        else:
            est_units_per_min = prod_rate

        # estimated units lost = (reduce_kw / actual_power) * production during duration
        if actual <= 0:
            units_lost = 0.0
        else:
            fraction = min(1.0, reduce_kw / actual)
            units_expected = est_units_per_min * duration_min
            units_lost = fraction * units_expected

        rows.append({
            "machine_id": mid,
            "actual_power_kw": actual,
            "reduce_kw": reduce_kw,
            "duration_min": duration_min,
            "estimated_units_lost": units_lost
        })

    out = pd.DataFrame(rows)
    out.to_csv(OUT_FILE, index=False)
    print(f"Saved production impact -> {OUT_FILE}")
    return out


if __name__ == "__main__":
    estimate_production_impact()