import pandas as pd
from pathlib import Path

# ✅ robust paths
BASE_DIR = Path(__file__).resolve().parent

DATA_OPS_DIR = BASE_DIR.parent / "data/02_operations"
DATA_FACTORY_DIR = BASE_DIR.parent / "data/01_factory"
DATA_AI_DIR = BASE_DIR.parent / "data/06_ai"

TELEMETRY_FILE = DATA_OPS_DIR / "machine_telemetry.csv"
CONSTRAINTS_FILE = DATA_FACTORY_DIR / "machine_constraints.csv"
AI_FEATURES_FILE = DATA_AI_DIR / "ai_features.csv"

BASELINE_FILE = BASE_DIR / "baseline_output.csv"
ANOMALY_FILE = BASE_DIR / "anomaly_output.csv"
MAINT_FILE = BASE_DIR / "maintenance_output.csv"

OUT_FILE = BASE_DIR / "final_decision_output.csv"


def compute_final_decision(
    telemetry_df=None,
    baseline_df=None,
    constraints_df=None,
    anomalies_df=None,
    maintenance_df=None,
    features_df=None
):

    # ---------------- LOAD ----------------
    if telemetry_df is None and TELEMETRY_FILE.exists():
        telemetry_df = pd.read_csv(TELEMETRY_FILE)

    if baseline_df is None and BASELINE_FILE.exists():
        baseline_df = pd.read_csv(BASELINE_FILE)

    if constraints_df is None and CONSTRAINTS_FILE.exists():
        constraints_df = pd.read_csv(CONSTRAINTS_FILE)

    if anomalies_df is None and ANOMALY_FILE.exists():
        anomalies_df = pd.read_csv(ANOMALY_FILE)

    if maintenance_df is None and MAINT_FILE.exists():
        maintenance_df = pd.read_csv(MAINT_FILE)

    if features_df is None and AI_FEATURES_FILE.exists():
        features_df = pd.read_csv(AI_FEATURES_FILE)

    if telemetry_df is None:
        raise FileNotFoundError("No telemetry available")

    telemetry_df["timestamp"] = pd.to_numeric(telemetry_df["timestamp"], errors="coerce").fillna(0)

    latest = telemetry_df.sort_values("timestamp").groupby("machine_id", as_index=False).last()

    # ---------------- BASELINE ----------------
    if baseline_df is not None and set(["machine_id","state"]).issubset(baseline_df.columns):
        master = latest.merge(baseline_df, on=["machine_id","state"], how="left")
    elif baseline_df is not None and "machine_id" in baseline_df.columns:
        master = latest.merge(baseline_df, on="machine_id", how="left")
    else:
        master = latest.copy()
        master["expected_power_kw"] = master["power_kw"]

    master["actual_power_kw"] = pd.to_numeric(master["power_kw"], errors="coerce").fillna(0)
    master["expected_power_kw"] = pd.to_numeric(master["expected_power_kw"], errors="coerce").fillna(master["actual_power_kw"])
    master["deviation_kw"] = master["actual_power_kw"] - master["expected_power_kw"]

    # ---------------- CONSTRAINTS ----------------
    if constraints_df is not None and "machine_id" in constraints_df.columns:
        master = master.merge(constraints_df, on="machine_id", how="left")
    else:
        master["min_operating_power_kw"] = 0.0
        master["max_reduction_kw"] = 0.0

    def compute_flex(r):
        minop = float(r.get("min_operating_power_kw") or 0)
        maxred = float(r.get("max_reduction_kw") or 0)
        return min(maxred, max(0, r["actual_power_kw"] - minop))

    master["flexible_power_kw"] = master.apply(compute_flex, axis=1)

    # ---------------- ANOMALY ----------------
    if anomalies_df is not None and not anomalies_df.empty:
        an_latest = anomalies_df.sort_values("timestamp").drop_duplicates("machine_id", keep="last")
        master = master.merge(an_latest[["machine_id","anomaly","anomaly_type"]], on="machine_id", how="left")
    else:
        master["anomaly"] = False
        master["anomaly_type"] = "NORMAL"

    # ---------------- MAINTENANCE ----------------
    if maintenance_df is not None and not maintenance_df.empty:
        maint_latest = maintenance_df.sort_values("timestamp").drop_duplicates("machine_id", keep="last")
        master = master.merge(maint_latest[["machine_id","maintenance_risk"]], on="machine_id", how="left")

    # ---------------- GRID INTELLIGENCE ----------------
    grid_stress = 1.0

    if features_df is not None and not features_df.empty:
        latest_feat = features_df.sort_values("timestamp").groupby("machine_id").last()
        master = master.merge(latest_feat[["grid_stress"]], on="machine_id", how="left")

        grid_stress = master["grid_stress"].mean()

    # ---------------- RANKING SCORE ----------------
    master["priority_score"] = (
        master["flexible_power_kw"] * 0.5 +
        master["deviation_kw"].abs() * 0.3 +
        (master.get("maintenance_risk", 0).fillna(0)) * 0.2
    )

    master["priority_rank"] = master["priority_score"].rank(ascending=False, method="dense")

    # ---------------- DECISION ----------------
    def recommend(r):
        if grid_stress > 1.2:
            if r["flexible_power_kw"] > 0:
                return f"GRID STRESS HIGH → REDUCE {r['flexible_power_kw']:.2f} kW"
        
        if r["anomaly"] and str(r["anomaly_type"]).startswith("OVER"):
            return f"REDUCE {r['flexible_power_kw']:.2f} kW"

        if r["flexible_power_kw"] > 0:
            return f"FLEX {r['flexible_power_kw']:.2f} kW available"

        return "MONITOR"

    master["recommended_action"] = master.apply(recommend, axis=1)

    # ---------------- OUTPUT ----------------
    out = master[[
        "machine_id",
        "actual_power_kw",
        "expected_power_kw",
        "deviation_kw",
        "flexible_power_kw",
        "priority_rank",
        "anomaly",
        "maintenance_risk",
        "recommended_action"
    ]].copy()

    out.to_csv(OUT_FILE, index=False)

    print(f"Saved FINAL DECISION -> {OUT_FILE}")
    print("\n=== TOP MACHINES TO CONTROL ===")
    print(out.sort_values("priority_rank").head(5))

    return out


if __name__ == "__main__":
    compute_final_decision()