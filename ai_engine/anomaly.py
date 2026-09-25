from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

OPS_DIR = DATA_DIR / "02_operations"
FACTORY_DIR = DATA_DIR / "01_factory"

TELEMETRY_FILE = OPS_DIR / "machine_telemetry.csv"
BASELINE_FILE = BASE_DIR / "baseline_output.csv"
MACHINE_METADATA_FILE = FACTORY_DIR / "machine_metadata.csv"

OUT_FILE = BASE_DIR / "anomaly_output.csv"


# ============================================================
# DEFAULT SETTINGS
# ============================================================

DEFAULT_THRESHOLD_KW = 10.0
DEFAULT_THRESHOLD_PERCENT = 20.0

TEMP_Z_THRESHOLD = 3.0
VIBRATION_Z_THRESHOLD = 3.0

OVERLOAD_PERCENT = 105.0
SEVERE_OVERLOAD_PERCENT = 110.0

EPS = 1e-6


# ============================================================
# HELPERS
# ============================================================

def load_csv(path: Path) -> pd.DataFrame:
    """Load CSV safely and normalize column names."""

    if not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
        df.columns = [
            str(c).strip()
            for c in df.columns
        ]
        return df

    except Exception as exc:
        print(f"Could not read {path}: {exc}")
        return pd.DataFrame()


def numeric(
    df: pd.DataFrame,
    column: str,
    default: float = np.nan
) -> pd.Series:
    """Return a numeric series, creating the column if necessary."""

    if column not in df.columns:
        return pd.Series(
            default,
            index=df.index,
            dtype=float
        )

    return pd.to_numeric(
        df[column],
        errors="coerce"
    )


# ============================================================
# THRESHOLD
# ============================================================

def build_thresholds(
    telemetry_df: pd.DataFrame,
    default_kw: float,
    default_percent: float,
    per_machine_thresholds: Optional[Dict[str, float]] = None
) -> pd.DataFrame:
    """
    Create machine-specific anomaly thresholds.

    A machine-specific kW threshold is preferred when supplied.
    Otherwise the default kW threshold is used.

    Percentage threshold is also calculated to avoid using the
    same absolute threshold for machines with very different
    power ratings.
    """

    df = telemetry_df.copy()

    df["threshold_kw"] = float(default_kw)

    if (
        per_machine_thresholds
        and "machine_id" in df.columns
    ):

        for machine_id, value in per_machine_thresholds.items():

            mask = (
                df["machine_id"].astype(str)
                == str(machine_id)
            )

            try:
                df.loc[
                    mask,
                    "threshold_kw"
                ] = float(value)

            except (TypeError, ValueError):
                pass

    # Percentage threshold is used together with absolute kW.
    df["threshold_percent"] = float(
        default_percent
    )

    return df


# ============================================================
# CORE ANOMALY DETECTION
# ============================================================

def detect_anomalies(
    telemetry_df: pd.DataFrame,
    baseline_df: Optional[pd.DataFrame],
    threshold_kw: float = DEFAULT_THRESHOLD_KW,
    per_machine_thresholds: Optional[Dict[str, float]] = None,
    threshold_percent: float = DEFAULT_THRESHOLD_PERCENT
) -> pd.DataFrame:

    # --------------------------------------------------------
    # 1. Copy + normalize
    # --------------------------------------------------------

    t = telemetry_df.copy()
    t.columns = [
        str(c).strip()
        for c in t.columns
    ]

    if t.empty:
        return pd.DataFrame()

    if "machine_id" not in t.columns:
        raise KeyError(
            "telemetry missing required column 'machine_id'"
        )

    if "power_kw" not in t.columns:
        raise KeyError(
            "telemetry missing required column 'power_kw'"
        )

    t["machine_id"] = (
        t["machine_id"]
        .astype(str)
        .str.strip()
    )

    t["power_kw"] = numeric(
        t,
        "power_kw",
        default=0.0
    ).fillna(0.0)

    if "state" not in t.columns:
        t["state"] = "UNKNOWN"
    else:
        t["state"] = (
            t["state"]
            .fillna("UNKNOWN")
            .astype(str)
            .str.strip()
            .str.upper()
        )

    if "timestamp" in t.columns:
        t["timestamp"] = pd.to_numeric(
            t["timestamp"],
            errors="coerce"
        )

    # --------------------------------------------------------
    # 2. Merge baseline
    # --------------------------------------------------------

    if baseline_df is not None:
        b = baseline_df.copy()

        b.columns = [
            str(c).strip()
            for c in b.columns
        ]

    else:
        b = pd.DataFrame()

    if (
        not b.empty
        and "machine_id" in b.columns
        and "state" in b.columns
    ):

        b["machine_id"] = (
            b["machine_id"]
            .astype(str)
            .str.strip()
        )

        b["state"] = (
            b["state"]
            .fillna("UNKNOWN")
            .astype(str)
            .str.strip()
            .str.upper()
        )

        b["expected_power_kw"] = pd.to_numeric(
            b["expected_power_kw"],
            errors="coerce"
        )

        # Avoid duplicate machine/state baseline rows.
        b = b.drop_duplicates(
            subset=[
                "machine_id",
                "state"
            ],
            keep="last"
        )

        baseline_columns = [
            "machine_id",
            "state",
            "expected_power_kw"
        ]

        if "machine_expected_power_kw" in b.columns:
            baseline_columns.append(
                "machine_expected_power_kw"
            )

        merged = t.merge(
            b[baseline_columns],
            on=[
                "machine_id",
                "state"
            ],
            how="left"
        )

    elif (
        not b.empty
        and "machine_id" in b.columns
    ):

        b["machine_id"] = (
            b["machine_id"]
            .astype(str)
            .str.strip()
        )

        b["expected_power_kw"] = pd.to_numeric(
            b["expected_power_kw"],
            errors="coerce"
        )

        b = b.drop_duplicates(
            subset=["machine_id"],
            keep="last"
        )

        baseline_columns = [
            "machine_id",
            "expected_power_kw"
        ]

        if "machine_expected_power_kw" in b.columns:
            baseline_columns.append(
                "machine_expected_power_kw"
            )

        merged = t.merge(
            b[baseline_columns],
            on="machine_id",
            how="left"
        )

    else:

        merged = t.copy()

        merged["expected_power_kw"] = np.nan

    # --------------------------------------------------------
    # 3. Expected power fallback
    # --------------------------------------------------------

    merged["expected_power_kw"] = pd.to_numeric(
        merged["expected_power_kw"],
        errors="coerce"
    )

    if "machine_expected_power_kw" in merged.columns:

        merged["machine_expected_power_kw"] = pd.to_numeric(
            merged["machine_expected_power_kw"],
            errors="coerce"
        )

    else:

        merged["machine_expected_power_kw"] = np.nan

    # First try machine/state baseline.
    merged["expected_power_source"] = np.where(
        merged["expected_power_kw"].notna(),
        "MACHINE_STATE_BASELINE",
        "CURRENT_POWER_FALLBACK"
    )

    merged["expected_power_kw"] = (
        merged["expected_power_kw"]
        .fillna(
            merged["machine_expected_power_kw"]
        )
        .fillna(
            merged["power_kw"]
        )
    )

    # --------------------------------------------------------
    # 4. Power deviation
    # --------------------------------------------------------

    merged["deviation_kw"] = (
        merged["power_kw"]
        - merged["expected_power_kw"]
    )

    merged["deviation_percent"] = (
        merged["deviation_kw"]
        / (
            merged["expected_power_kw"].abs()
            + EPS
        )
    ) * 100.0

    merged["absolute_deviation_percent"] = (
        merged["deviation_percent"]
        .abs()
    )

    # --------------------------------------------------------
    # 5. Thresholds
    # --------------------------------------------------------

    merged = build_thresholds(
        merged,
        default_kw=threshold_kw,
        default_percent=threshold_percent,
        per_machine_thresholds=per_machine_thresholds
    )

    merged["kw_anomaly"] = (
        merged["deviation_kw"].abs()
        > merged["threshold_kw"]
    )

    merged["percent_anomaly"] = (
        merged["absolute_deviation_percent"]
        > merged["threshold_percent"]
    )

    merged["power_anomaly"] = (
        merged["kw_anomaly"]
        &
        merged["percent_anomaly"]
    )

    # If a machine is very small, a large percentage change
    # should still matter even when the absolute difference is
    # below 10 kW.
    merged["power_anomaly"] = (
        merged["power_anomaly"]
        |
        (
            merged["kw_anomaly"]
            &
            (
                merged["expected_power_kw"] < 50.0
            )
        )
    )

    # --------------------------------------------------------
    # 6. Load / rated-power information
    # --------------------------------------------------------

    metadata = load_csv(
        MACHINE_METADATA_FILE
    )

    if (
        not metadata.empty
        and "machine_id" in metadata.columns
    ):

        metadata["machine_id"] = (
            metadata["machine_id"]
            .astype(str)
            .str.strip()
        )

        if "rated_power_kw" in metadata.columns:

            metadata["rated_power_kw"] = pd.to_numeric(
                metadata["rated_power_kw"],
                errors="coerce"
            )

            metadata = (
                metadata[
                    [
                        "machine_id",
                        "rated_power_kw"
                    ]
                ]
                .drop_duplicates(
                    "machine_id"
                )
            )

            merged = merged.merge(
                metadata,
                on="machine_id",
                how="left"
            )

    if "rated_power_kw" not in merged.columns:
        merged["rated_power_kw"] = np.nan

    merged["rated_power_kw"] = pd.to_numeric(
        merged["rated_power_kw"],
        errors="coerce"
    )

    merged["rated_load_percent"] = (
        merged["power_kw"]
        / (
            merged["rated_power_kw"]
            + EPS
        )
    ) * 100.0

    merged["rated_load_available"] = (
        merged["rated_power_kw"].notna()
    )

    merged["rated_overload"] = (
        merged["rated_load_available"]
        &
        (
            merged["rated_load_percent"]
            > OVERLOAD_PERCENT
        )
    )

    merged["severe_overload"] = (
        merged["rated_load_available"]
        &
        (
            merged["rated_load_percent"]
            > SEVERE_OVERLOAD_PERCENT
        )
    )

    # --------------------------------------------------------
    # 7. Temperature anomaly
    # --------------------------------------------------------

    if "temperature_c" in merged.columns:

        merged["temperature_c"] = numeric(
            merged,
            "temperature_c"
        )

        temp_mean = (
            merged.groupby(
                "machine_id"
            )["temperature_c"]
            .transform("mean")
        )

        temp_std = (
            merged.groupby(
                "machine_id"
            )["temperature_c"]
            .transform(
                lambda x:
                x.std(ddof=0)
            )
        )

        temp_std = (
            temp_std
            .replace(0, np.nan)
            .fillna(1.0)
        )

        merged["temperature_zscore"] = (
            merged["temperature_c"]
            - temp_mean
        ) / (
            temp_std + EPS
        )

        merged["temperature_anomaly"] = (
            merged["temperature_zscore"]
            .abs()
            >= TEMP_Z_THRESHOLD
        )

    else:

        merged["temperature_zscore"] = 0.0
        merged["temperature_anomaly"] = False

    # --------------------------------------------------------
    # 8. Vibration anomaly
    # --------------------------------------------------------

    if "vibration_mm_s" in merged.columns:

        merged["vibration_mm_s"] = numeric(
            merged,
            "vibration_mm_s"
        )

        vib_mean = (
            merged.groupby(
                "machine_id"
            )["vibration_mm_s"]
            .transform("mean")
        )

        vib_std = (
            merged.groupby(
                "machine_id"
            )["vibration_mm_s"]
            .transform(
                lambda x:
                x.std(ddof=0)
            )
        )

        vib_std = (
            vib_std
            .replace(0, np.nan)
            .fillna(1.0)
        )

        merged["vibration_zscore"] = (
            merged["vibration_mm_s"]
            - vib_mean
        ) / (
            vib_std + EPS
        )

        merged["vibration_anomaly"] = (
            merged["vibration_zscore"]
            .abs()
            >= VIBRATION_Z_THRESHOLD
        )

    else:

        merged["vibration_zscore"] = 0.0
        merged["vibration_anomaly"] = False

    # --------------------------------------------------------
    # 9. Idle energy anomaly
    # --------------------------------------------------------

    if "units_produced" in merged.columns:

        merged["units_produced"] = numeric(
            merged,
            "units_produced"
        ).fillna(0.0)

        merged["idle_energy_anomaly"] = (
            (merged["units_produced"] <= EPS)
            &
            (merged["power_kw"] > 0)
            &
            (
                ~merged["state"].isin(
                    [
                        "OFF",
                        "STOPPED"
                    ]
                )
            )
        )

    elif "production_rate" in merged.columns:

        production_rate = numeric(
            merged,
            "production_rate"
        ).fillna(0.0)

        merged["idle_energy_anomaly"] = (
            (production_rate <= EPS)
            &
            (merged["power_kw"] > 0)
            &
            (
                ~merged["state"].isin(
                    [
                        "OFF",
                        "STOPPED"
                    ]
                )
            )
        )

    else:

        merged["idle_energy_anomaly"] = False

    # --------------------------------------------------------
    # 10. Overall anomaly
    # --------------------------------------------------------

    merged["anomaly"] = (
        merged["power_anomaly"]
        |
        merged["rated_overload"]
        |
        merged["temperature_anomaly"]
        |
        merged["vibration_anomaly"]
        |
        merged["idle_energy_anomaly"]
    )

    # --------------------------------------------------------
    # 11. Anomaly classification
    # --------------------------------------------------------

    def classify(row: pd.Series) -> str:

        if row["severe_overload"]:
            return "SEVERE_OVERLOAD"

        if row["rated_overload"]:
            return "OVERLOAD"

        if row["power_anomaly"]:

            if row["deviation_kw"] > 0:
                return "OVERCONSUMPTION"

            return "UNDERUTILIZATION"

        if row["temperature_anomaly"]:
            return "TEMPERATURE_ANOMALY"

        if row["vibration_anomaly"]:
            return "VIBRATION_ANOMALY"

        if row["idle_energy_anomaly"]:
            return "IDLE_ENERGY"

        return "NORMAL"

    merged["anomaly_type"] = (
        merged.apply(
            classify,
            axis=1
        )
    )

    # --------------------------------------------------------
    # 12. Severity
    # --------------------------------------------------------

    def severity(row: pd.Series) -> str:

        if not bool(row["anomaly"]):
            return "NONE"

        if (
            row["severe_overload"]
            or
            row["absolute_deviation_percent"] >= 40.0
            or
            abs(row["temperature_zscore"]) >= 4.0
            or
            abs(row["vibration_zscore"]) >= 4.0
        ):
            return "HIGH"

        if (
            row["absolute_deviation_percent"] >= 20.0
            or
            abs(row["temperature_zscore"]) >= 3.0
            or
            abs(row["vibration_zscore"]) >= 3.0
        ):
            return "MEDIUM"

        return "LOW"

    merged["severity"] = (
        merged.apply(
            severity,
            axis=1
        )
    )

    # --------------------------------------------------------
    # 13. Confidence
    #
    # Confidence is based on anomaly strength rather than
    # simply deviation/threshold. Multiple independent
    # indicators increase confidence.
    # --------------------------------------------------------

    kw_strength = (
        merged["deviation_kw"].abs()
        / (
            merged["threshold_kw"]
            + EPS
        )
    ).clip(
        0,
        3
    ) / 3.0

    percent_strength = (
        merged["absolute_deviation_percent"]
        / (
            merged["threshold_percent"]
            + EPS
        )
    ).clip(
        0,
        3
    ) / 3.0

    temp_strength = (
        merged["temperature_zscore"].abs()
        / TEMP_Z_THRESHOLD
    ).clip(
        0,
        1
    )

    vib_strength = (
        merged["vibration_zscore"].abs()
        / VIBRATION_Z_THRESHOLD
    ).clip(
        0,
        1
    )

    confidence = (
        kw_strength * 0.40
        +
        percent_strength * 0.30
        +
        temp_strength * 0.15
        +
        vib_strength * 0.15
    )

    # An explicit anomaly gets at least a meaningful
    # confidence floor when detected.
    confidence = np.where(
        merged["anomaly"],
        np.maximum(
            confidence,
            0.50
        ),
        confidence * 0.50
    )

    merged["confidence"] = (
        pd.Series(
            confidence,
            index=merged.index
        )
        .clip(0.0, 1.0)
    )

    # --------------------------------------------------------
    # 14. Recommended detection reason
    # --------------------------------------------------------

    def reason(row: pd.Series) -> str:

        reasons = []

        if row["power_anomaly"]:
            if row["deviation_kw"] > 0:
                reasons.append(
                    "POWER_ABOVE_EXPECTED"
                )
            else:
                reasons.append(
                    "POWER_BELOW_EXPECTED"
                )

        if row["rated_overload"]:
            reasons.append(
                "RATED_POWER_EXCEEDED"
            )

        if row["temperature_anomaly"]:
            reasons.append(
                "TEMPERATURE_DEVIATION"
            )

        if row["vibration_anomaly"]:
            reasons.append(
                "VIBRATION_DEVIATION"
            )

        if row["idle_energy_anomaly"]:
            reasons.append(
                "ENERGY_WHILE_IDLE"
            )

        if not reasons:
            return "NORMAL"

        return " + ".join(
            reasons
        )

    merged["detection_reason"] = (
        merged.apply(
            reason,
            axis=1
        )
    )

    # --------------------------------------------------------
    # 15. Final output
    # --------------------------------------------------------

    output_columns = [
        "timestamp",
        "machine_id",
        "state",

        "power_kw",
        "expected_power_kw",
        "expected_power_source",

        "deviation_kw",
        "deviation_percent",

        "threshold_kw",
        "threshold_percent",

        "rated_power_kw",
        "rated_load_percent",

        "anomaly",
        "anomaly_type",
        "severity",
        "confidence",
        "detection_reason",

        "temperature_zscore",
        "vibration_zscore"
    ]

    output_columns = [
        col
        for col in output_columns
        if col in merged.columns
    ]

    out = merged[
        output_columns
    ].copy()

    return out


# ============================================================
# STANDALONE PIPELINE
# ============================================================

def run(
    threshold_kw: float = DEFAULT_THRESHOLD_KW,
    threshold_percent: float = DEFAULT_THRESHOLD_PERCENT
):

    telemetry = load_csv(
        TELEMETRY_FILE
    )

    if telemetry.empty:

        print(
            "Telemetry file not found or empty."
        )

        return pd.DataFrame()

    baseline = (
        load_csv(
            BASELINE_FILE
        )
        if BASELINE_FILE.exists()
        else None
    )

    results = detect_anomalies(
        telemetry_df=telemetry,
        baseline_df=baseline,
        threshold_kw=threshold_kw,
        threshold_percent=threshold_percent
    )

    Path(OUT_FILE).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    results.to_csv(
        OUT_FILE,
        index=False
    )

    anomaly_count = int(
        results["anomaly"].sum()
    ) if "anomaly" in results.columns else 0

    print(
        f"\nSaved anomaly results -> "
        f"{OUT_FILE}"
    )

    print(
        f"Rows analysed: "
        f"{len(results)}"
    )

    print(
        f"Anomalies flagged: "
        f"{anomaly_count}"
    )

    if not results.empty:

        print(
            "\n=== ANOMALY COUNTS ==="
        )

        if "anomaly_type" in results.columns:

            print(
                results[
                    "anomaly_type"
                ]
                .value_counts()
                .to_string()
            )

        print(
            "\n=== RECENT RESULTS ==="
        )

        print(
            results.tail(15).to_string(
                index=False
            )
        )

    return results


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run()