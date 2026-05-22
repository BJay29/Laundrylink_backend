"""
Train the LaundryLink revenue forecasting model.

Run from the project root:
    python -m ml_engine.train
"""

from __future__ import annotations

import pickle
import json  # Added for metrics storage
import os    # Added for path management
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score

from ml_engine.data_prep import FEATURE_COLUMNS, load_training_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT_ROOT / "ml_models"
MODEL_PATH = MODEL_DIR / "forecast.pkl"
REPORT_PATH = MODEL_DIR / "accuracy_report.png"
METRICS_PATH = MODEL_DIR / "model_metrics.json" # Added path for JSON


def _split_validation(frame):
    validation_size = max(7, int(len(frame) * 0.20))
    validation_size = min(validation_size, len(frame) - 2)
    train_frame = frame.iloc[:-validation_size].copy()
    validation_frame = frame.iloc[-validation_size:].copy()
    return train_frame, validation_frame


def _save_accuracy_report(validation_frame, predictions) -> None:
    plt.figure(figsize=(10, 5))
    plt.plot(validation_frame["booking_date"], validation_frame["total_revenue"], marker="o", label="Actual")
    plt.plot(validation_frame["booking_date"], predictions, marker="x", label="Predicted")
    plt.title("LaundryLink Forecast Validation: Actual vs Predicted Revenue")
    plt.xlabel("Date")
    plt.ylabel("Daily Revenue")
    plt.xticks(rotation=35, ha="right")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(REPORT_PATH, dpi=160)
    plt.close()


def train_forecast_model(shop_id: int = 1) -> dict:
    frame = load_training_data(shop_id=shop_id)
    if len(frame) < 14:
        raise ValueError("At least 14 daily booking aggregates are required before training.")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    train_frame, validation_frame = _split_validation(frame)

    model = LinearRegression()
    model.fit(train_frame[FEATURE_COLUMNS].to_numpy(), train_frame["total_revenue"].to_numpy())

    validation_predictions = model.predict(validation_frame[FEATURE_COLUMNS].to_numpy())
    validation_predictions = np.maximum(validation_predictions, 0.0)

    mae = mean_absolute_error(validation_frame["total_revenue"], validation_predictions)
    r2 = r2_score(validation_frame["total_revenue"], validation_predictions)
    mean_actual = validation_frame["total_revenue"].mean()
    accuracy_percentage = max(0.0, 100.0 - ((mae / mean_actual) * 100.0)) if mean_actual else 0.0

    artifact = {
        "model": model,
        "feature_columns": FEATURE_COLUMNS,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "shop_id": shop_id,
        "training_start_date": frame["booking_date"].min().date().isoformat(),
        "last_training_date": frame["booking_date"].max().date().isoformat(),
        "last_day_index": int(frame["day_index"].max()),
        "average_ticket": float(frame["total_revenue"].sum() / max(frame["booking_count"].sum(), 1)),
        "average_loads_per_booking": float(frame["total_loads"].sum() / max(frame["booking_count"].sum(), 1)),
        "metrics": {
            "accuracy_percentage": round(float(accuracy_percentage), 2),
            "mean_absolute_error": round(float(mae), 2),
            "r2_score": round(float(r2), 4),
            "validation_days": int(len(validation_frame)),
            "evaluation_method": "Linear Regression holdout validation on daily booking aggregates",
            "accuracy_report_path": str(REPORT_PATH),
        },
    }

    with MODEL_PATH.open("wb") as model_file:
        pickle.dump(artifact, model_file)

    # Save accuracy metrics to JSON for dynamic dashboard display
    metrics_data = {
        "demand_forecasting_model": artifact["metrics"],
        "last_updated": artifact["trained_at"]
    }
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics_data, f, indent=4)

    _save_accuracy_report(validation_frame, validation_predictions)
    return artifact["metrics"]

# --- ADDED THIS FUNCTION TO FIX YOUR IMPORT ERROR ---
def run_training_pipeline():
    """
    Wrapper function to be called by PredictionService.
    """
    return train_forecast_model()

def main() -> None:
    metrics = train_forecast_model()
    print(f"Model saved to {MODEL_PATH}")
    print(f"Accuracy report saved to {REPORT_PATH}")
    print(f"Metrics saved to {METRICS_PATH}")
    print(metrics)


if __name__ == "__main__":
    main()