# ai_api.py (in-memory, non-destructive)
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd
from pathlib import Path

import anomaly
import baseline

app = FastAPI(title="INDUS_TWIN AI API (in-memory)")

# ✅ paths fixed for GitHub
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"

class TelemetryRow(BaseModel):
    timestamp: Optional[int]
    machine_id: str
    state: Optional[str] = None
    power_kw: float
    energy_kwh: Optional[float] = None
    load_percent: Optional[float] = None
    temperature_c: Optional[float] = None
    vibration_mm_s: Optional[float] = None
    rpm: Optional[float] = None
    production_rate: Optional[float] = None
    units_produced: Optional[float] = None


def load_baseline():
    file = DATA_DIR / "baseline_output.csv"
    if file.exists():
        return pd.read_csv(file)
    try:
        return baseline.compute_baseline()
    except Exception:
        return pd.DataFrame(columns=["machine_id","state","expected_power_kw"])


def load_constraints():
    file = DATA_DIR / "machine_constraints.csv"
    if file.exists():
        return pd.read_csv(file)
    return pd.DataFrame()


def load_machine_thresholds():
    path = DATA_DIR / "machine_metadata.csv"
    if not path.exists():
        return {}

    md = pd.read_csv(path)
    for col in ["anomaly_threshold_kw","threshold_kw","threshold_kW"]:
        if col in md.columns:
            return dict(zip(md["machine_id"], pd.to_numeric(md[col], errors="coerce").fillna(0.0)))
    return {}


def compute_decisions(telemetry_df, baseline_df, constraints_df, anomalies_df):
    rows = []

    constraints_idx = {}
    if not constraints_df.empty and "machine_id" in constraints_df.columns:
        constraints_idx = constraints_df.set_index("machine_id").to_dict(orient="index")

    baseline_idx = {}
    if not baseline_df.empty and "machine_id" in baseline_df.columns:
        baseline_idx = (
            baseline_df.set_index(["machine_id","state"]).to_dict(orient="index")
            if set(["machine_id","state"]).issubset(baseline_df.columns)
            else baseline_df.set_index("machine_id").to_dict(orient="index")
        )

    anom_idx = {}
    if anomalies_df is not None and not anomalies_df.empty:
        if "state" in anomalies_df.columns:
            for _, r in anomalies_df.iterrows():
                anom_idx[(r["machine_id"], r.get("state"))] = r.to_dict()
        else:
            for _, r in anomalies_df.iterrows():
                anom_idx[(r["machine_id"], None)] = r.to_dict()

    for _, row in telemetry_df.iterrows():
        mid = row["machine_id"]
        state = row.get("state")
        actual = float(row.get("power_kw", 0.0))

        expected = None
        if (mid, state) in baseline_idx:
            expected = baseline_idx[(mid, state)].get("expected_power_kw")
        elif mid in baseline_idx:
            expected = baseline_idx[mid].get("expected_power_kw")

        expected = float(expected) if expected is not None and not pd.isna(expected) else actual
        deviation = actual - expected

        min_op = 0.0
        max_red = 0.0
        if mid in constraints_idx:
            min_op = float(constraints_idx[mid].get("min_operating_power_kw", 0.0) or 0.0)
            max_red = float(constraints_idx[mid].get("max_reduction_kw", 0.0) or 0.0)

        flexible = max(0.0, min(max_red, max(0.0, actual - min_op)))

        an_key = (mid, state) if (mid, state) in anom_idx else (mid, None)
        an_info = anom_idx.get(an_key, {})
        is_anom = bool(an_info.get("anomaly", False))
        an_type = an_info.get("anomaly_type", "NORMAL")

        temp = float(row.get("temperature_c") or 0.0)
        vib = float(row.get("vibration_mm_s") or 0.0)

        maintenance_risk = min(1.0, (temp/150.0)*0.5 + (vib/2.0)*0.5)

        if is_anom and str(an_type).upper().startswith("OVER"):
            action = f"RECOMMEND REDUCE up to {flexible:.2f} kW" if flexible > 0 else "NO SAFE FLEXIBILITY — Inspect"
        elif is_anom and str(an_type).upper().startswith("UNDER"):
            action = "UNDERUTILIZED — reschedule"
        elif flexible > 0:
            action = f"FLEX AVAILABLE {flexible:.2f} kW - demand response"
        else:
            action = "NO ACTION — monitor"

        rows.append({
            "machine_id": mid,
            "state": state,
            "actual_power_kw": actual,
            "expected_power_kw": expected,
            "deviation_kw": deviation,
            "flexible_power_kw": flexible,
            "anomaly": is_anom,
            "anomaly_type": an_type,
            "maintenance_risk": maintenance_risk,
            "recommended_action": action
        })

    return pd.DataFrame(rows)


@app.post("/infer")
def infer(row: TelemetryRow, threshold: float = 10.0):
    telemetry_df = pd.DataFrame([row.dict()])
    baseline_df = load_baseline()
    constraints_df = load_constraints()
    machine_thresholds = load_machine_thresholds()

    anomalies_df = anomaly.detect_anomalies(
        telemetry_df, baseline_df,
        threshold_kw=threshold,
        per_machine_thresholds=machine_thresholds
    )

    decisions_df = compute_decisions(telemetry_df, baseline_df, constraints_df, anomalies_df)

    return {
        "anomaly": anomalies_df.to_dict(orient="records"),
        "decision": decisions_df.to_dict(orient="records")
    }


@app.post("/infer/batch")
def infer_batch(rows: List[TelemetryRow], threshold: float = 10.0):
    telemetry_df = pd.DataFrame([r.dict() for r in rows])
    baseline_df = load_baseline()
    constraints_df = load_constraints()
    machine_thresholds = load_machine_thresholds()

    anomalies_df = anomaly.detect_anomalies(
        telemetry_df, baseline_df,
        threshold_kw=threshold,
        per_machine_thresholds=machine_thresholds
    )

    decisions_df = compute_decisions(telemetry_df, baseline_df, constraints_df, anomalies_df)

    return {
        "anomalies": anomalies_df.to_dict(orient="records"),
        "decisions": decisions_df.to_dict(orient="records")
    }