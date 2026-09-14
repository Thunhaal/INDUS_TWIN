import streamlit as st
import pandas as pd
import subprocess
from pathlib import Path
import requests
import time
import random

# ---------------- CONFIG ----------------
st.set_page_config(page_title="INDUS_TWIN PRO", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
PIPELINE = BASE_DIR / "run_pipeline.py"

FD = BASE_DIR / "final_decision_output.csv"
AN = BASE_DIR / "anomaly_output.csv"
MA = BASE_DIR / "maintenance_output.csv"

# ---------------- HEADER ----------------
st.title("🏭 INDUS_TWIN — AI Energy Intelligence Dashboard")

# ---------------- AUTO REFRESH ----------------
refresh = st.sidebar.checkbox("🔄 Auto Refresh (5s)")
if refresh:
    time.sleep(5)
    st.experimental_rerun()

# ---------------- KPI SECTION ----------------
st.markdown("## 📊 System Overview")

if FD.exists():
    df = pd.read_csv(FD)

    total_machines = len(df)
    anomalies = df["anomaly"].sum() if "anomaly" in df.columns else 0
    avg_risk = df["maintenance_risk"].mean() if "maintenance_risk" in df.columns else 0
    total_flex = df["flexible_power_kw"].sum() if "flexible_power_kw" in df.columns else 0

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Machines", total_machines)
    c2.metric("Anomalies 🚨", int(anomalies))
    c3.metric("Avg Risk ⚠️", f"{avg_risk:.2f}")
    c4.metric("Total Flex (kW)", f"{total_flex:.2f}")

else:
    st.info("Run pipeline to generate data.")

# ---------------- PIPELINE CONTROL ----------------
st.markdown("## ⚙️ Pipeline Control")

if st.button("▶ Run Full Pipeline"):
    with st.spinner("Running pipeline..."):
        proc = subprocess.run(
            ["python", str(PIPELINE), "--threshold", "8"],
            capture_output=True,
            text=True
        )
        st.code(proc.stdout)
    st.success("Pipeline updated!")
    st.experimental_rerun()

# ---------------- LIVE API ----------------
st.markdown("## 🤖 Live AI Inference")

col1, col2 = st.columns(2)

with col1:
    api_url = st.text_input("API URL", "http://localhost:8000/infer")
    mid = st.text_input("Machine ID", "CNC_01")
    power = st.number_input("Power (kW)", value=30.0)
    state = st.selectbox("State", ["RUNNING", "IDLE", "OFF"])

    if st.button("⚡ Run Inference"):
        payload = {
            "timestamp": int(time.time()),
            "machine_id": mid,
            "state": state,
            "power_kw": float(power)
        }
        try:
            r = requests.post(api_url, json=payload, timeout=3)

            if r.status_code == 200:
                result = r.json()

                st.success("Inference Success")
                st.json(result)

                # highlight anomaly
                if result["anomaly"][0]["anomaly"]:
                    st.error("🚨 ANOMALY DETECTED!")
                else:
                    st.success("✅ NORMAL OPERATION")

            else:
                st.error(f"API Error: {r.status_code}")

        except Exception as e:
            st.error(f"API failed: {e}")

# ---------------- BATCH SIMULATION ----------------
with col2:
    st.markdown("### ⚡ Batch Simulation")

    if st.button("Simulate 5 Machines"):
        payload = []
        for i in range(5):
            payload.append({
                "timestamp": int(time.time()),
                "machine_id": f"M_{i}",
                "state": "RUNNING",
                "power_kw": random.uniform(20, 80)
            })

        try:
            r = requests.post(api_url.replace("/infer", "/infer/batch"), json=payload)
            st.json(r.json())
        except Exception as e:
            st.error(e)

# ---------------- DECISION TABLE ----------------
st.markdown("## 📋 Final Decisions")

if FD.exists():
    df = pd.read_csv(FD)

    def highlight(row):
        if row.get("anomaly") == True:
            return ["background-color: #ffcccc"] * len(row)
        return [""] * len(row)

    st.dataframe(df.style.apply(highlight, axis=1), height=350)

    # ---------------- CHARTS ----------------
    st.markdown("## 📊 Analytics")

    c1, c2 = st.columns(2)

    with c1:
        if "flexible_power_kw" in df.columns:
            st.markdown("### 🔋 Flexibility")
            st.bar_chart(df.set_index("machine_id")["flexible_power_kw"])

    with c2:
        if "deviation_kw" in df.columns:
            st.markdown("### ⚡ Power Deviation")
            st.bar_chart(df.set_index("machine_id")["deviation_kw"])

else:
    st.info("Run pipeline first.")

# ---------------- ANOMALIES ----------------
st.markdown("## 🚨 Recent Anomalies")

if AN.exists():
    an = pd.read_csv(AN)
    st.dataframe(an.sort_values("timestamp", ascending=False).head(20))
else:
    st.info("No anomaly data.")

# ---------------- MAINTENANCE ----------------
st.markdown("## 🔧 Maintenance Risk")

if MA.exists():
    ma = pd.read_csv(MA)
    st.dataframe(ma.sort_values("timestamp", ascending=False).head(20))
else:
    st.info("No maintenance data.")