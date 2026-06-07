"""
Train the LaundryLink revenue forecasting model.

Run from the project root:
    python -m ml_engine.train
"""

from __future__ import annotations

import pickle
import json
import os
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score

from ml_engine.data_prep import FEATURE_COLUMNS, load_training_data

# Configuration of paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT_ROOT / "ml_models"
MODEL_PATH = MODEL_DIR / "forecast.pkl"
BACKUP_PATH = MODEL_DIR / "forecast_backup.pkl" # Added for safety
REPORT_PATH = MODEL_DIR / "accuracy_report.png"
METRICS_PATH = MODEL_DIR / "model_metrics.json"

# Setup logging for production monitoring
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _split_validation(frame):
    """Splits data into training and validation sets."""
    validation_size = max(7, int(len(frame) * 0.20))
    validation_size = min(validation_size, len(frame) - 2)
    train_frame = frame.iloc[:-validation_size].copy()
    validation_frame = frame.iloc[-validation_size:].copy()
    return train_frame, validation_frame


def _save_accuracy_report(validation_frame, predictions) -> None:
    """Generates and saves a visual plot comparing actual vs predicted revenue."""
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


def run_training_pipeline(shop_id: int = 1) -> dict:
    """Trains the model and updates the forecast artifact and metrics.
    Renamed from train_forecast_model to match prediction_service.py import.
    """
    try:
        frame = load_training_data(shop_id=shop_id)
        if len(frame) < 14:
            raise ValueError("At least 14 daily booking aggregates are required to train the model.")

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        train_frame, validation_frame = _split_validation(frame)

        # Initialize and train model
        model = LinearRegression()
        model.fit(train_frame[FEATURE_COLUMNS].to_numpy(), train_frame["total_revenue"].to_numpy())

        # Perform predictions and validation
        validation_predictions = model.predict(validation_frame[FEATURE_COLUMNS].to_numpy())
        validation_predictions = np.maximum(validation_predictions, 0.0)

        # Calculate performance metrics
        mae = mean_absolute_error(validation_frame["total_revenue"], validation_predictions)
        r2 = r2_score(validation_frame["total_revenue"], validation_predictions)
        mean_actual = validation_frame["total_revenue"].mean()
        accuracy_percentage = max(0.0, 100.0 - ((mae / mean_actual) * 100.0)) if mean_actual else 0.0

        # Create model artifact
        artifact = {
            "model": model,
            "feature_columns": FEATURE_COLUMNS,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "shop_id": shop_id,
            "metrics": {
                "accuracy_percentage": round(float(accuracy_percentage), 2),
                "mean_absolute_error": round(float(mae), 2),
                "r2_score": round(float(r2), 4),
                "validation_days": int(len(validation_frame)),
            },
        }

        # Backup current model before overwriting
        if MODEL_PATH.exists():
            shutil.copy(MODEL_PATH, BACKUP_PATH)

        # Save new model to binary file
        with MODEL_PATH.open("wb") as model_file:
            pickle.dump(artifact, model_file)

        # Save metrics to JSON for dashboard consumption
        with open(METRICS_PATH, "w") as f:
            json.dump(artifact["metrics"], f, indent=4)

        _save_accuracy_report(validation_frame, validation_predictions)
        
        logger.info(f"Training complete. Accuracy: {accuracy_percentage}%")
        return artifact["metrics"]

    except Exception as e:
        logger.error(f"Error during training pipeline: {str(e)}")
        raise e


def main() -> None:
    """Main entry point for manual training trigger."""
    metrics = run_training_pipeline()
    print(f"Model saved: {MODEL_PATH}")
    print(f"Metrics: {metrics}")


if __name__ == "__main__":
    main()