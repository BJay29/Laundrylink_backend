"""
Train the LaundryLink revenue forecasting models.

Run from the project root:
    python -m ml_engine.train                 # trains shop 1's own model
    python -m ml_engine.train --shop-id 3      # trains shop 3's own model
    python -m ml_engine.train --pooled         # trains the pooled/cold-start model
"""

from __future__ import annotations

import argparse
import pickle
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score

from ml_engine.data_prep import (
    FEATURE_COLUMNS,
    POOLED_FEATURE_COLUMNS,
    load_training_data,
    load_pooled_training_data,
)

# Configuration of paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT_ROOT / "ml_models"
REPORT_PATH = MODEL_DIR / "accuracy_report.png"
METRICS_PATH = MODEL_DIR / "model_metrics.json"

# UPDATED: each shop now gets its OWN artifact file, instead of every
# shop overwriting the same single "forecast.pkl". This is the actual
# fix for "every shop sees the same forecast graph" — the old single
# global MODEL_PATH meant whichever shop was trained last (always
# shop_id=1 by default) was the only model that ever existed.
def shop_model_path(shop_id: int) -> Path:
    return MODEL_DIR / f"forecast_shop_{shop_id}.pkl"


# NEW — the pooled/cold-start model, shared by every shop that doesn't
# have (or doesn't yet have) enough of its own history to train on.
POOLED_MODEL_PATH = MODEL_DIR / "forecast_pooled.pkl"

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
    """
    Trains a SHOP-SPECIFIC model and saves it to forecast_shop_{shop_id}.pkl.
    Requires at least 14 days of that shop's own daily booking history.
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

        # FIXED (kept from previous pass): prediction_service.py reads
        # average_ticket / average_loads_per_booking / last_day_index off
        # the artifact — computed here from the FULL frame so it reflects
        # the shop's true pricing and true latest trained day, not the
        # old hardcoded defaults.
        total_bookings_all = frame["booking_count"].sum()
        average_ticket = (
            float(frame["total_revenue"].sum() / total_bookings_all)
            if total_bookings_all > 0 else 150.0
        )
        average_loads_per_booking = (
            float(frame["total_loads"].sum() / total_bookings_all)
            if total_bookings_all > 0 else 1.0
        )
        last_day_index = int(frame["day_index"].max())

        artifact = {
            "model": model,
            "feature_columns": FEATURE_COLUMNS,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "shop_id": shop_id,
            "average_ticket": round(average_ticket, 2),
            "average_loads_per_booking": round(average_loads_per_booking, 4),
            "last_day_index": last_day_index,
            "metrics": {
                "accuracy_percentage": round(float(accuracy_percentage), 2),
                "mean_absolute_error": round(float(mae), 2),
                "r2_score": round(float(r2), 4),
                "validation_days": int(len(validation_frame)),
            },
        }

        model_path = shop_model_path(shop_id)
        backup_path = MODEL_DIR / f"forecast_shop_{shop_id}_backup.pkl"
        if model_path.exists():
            shutil.copy(model_path, backup_path)

        with model_path.open("wb") as model_file:
            pickle.dump(artifact, model_file)

        # Metrics file used by /analytics/accuracy — kept single/global
        # for now, always reflects whichever shop was trained most recently.
        with open(METRICS_PATH, "w") as f:
            json.dump(artifact["metrics"], f, indent=4)

        _save_accuracy_report(validation_frame, validation_predictions)

        logger.info(f"Training complete for shop {shop_id}. Accuracy: {accuracy_percentage}%")
        return artifact["metrics"]

    except Exception as e:
        logger.error(f"Error during training pipeline for shop {shop_id}: {str(e)}")
        raise e


def run_pooled_training_pipeline() -> dict:
    """
    NEW — trains the pooled/global cold-start model across every shop
    that has at least MIN_DAYS_FOR_POOLING days of history. Target is
    revenue_ratio (each shop's day normalized against its own average),
    not raw currency, so shops of different sizes combine cleanly.
    """
    try:
        frame = load_pooled_training_data()
        if len(frame) < 30:
            raise ValueError(
                "At least 30 pooled shop-days (across all contributing shops combined) "
                "are required to train the pooled model."
            )

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        train_frame, validation_frame = _split_validation(frame)

        model = LinearRegression()
        model.fit(train_frame[POOLED_FEATURE_COLUMNS].to_numpy(), train_frame["revenue_ratio"].to_numpy())

        validation_predictions = model.predict(validation_frame[POOLED_FEATURE_COLUMNS].to_numpy())
        validation_predictions = np.maximum(validation_predictions, 0.0)

        mae = mean_absolute_error(validation_frame["revenue_ratio"], validation_predictions)
        r2 = r2_score(validation_frame["revenue_ratio"], validation_predictions)

        artifact = {
            "model": model,
            "feature_columns": POOLED_FEATURE_COLUMNS,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "shop_count": int(frame["shop_id"].nunique()),
            "metrics": {
                "mean_absolute_error": round(float(mae), 4),
                "r2_score": round(float(r2), 4),
                "validation_rows": int(len(validation_frame)),
            },
        }

        if POOLED_MODEL_PATH.exists():
            shutil.copy(POOLED_MODEL_PATH, MODEL_DIR / "forecast_pooled_backup.pkl")

        with POOLED_MODEL_PATH.open("wb") as model_file:
            pickle.dump(artifact, model_file)

        logger.info(
            f"Pooled training complete. Shops used: {artifact['shop_count']}, "
            f"rows: {len(frame)}."
        )
        return artifact["metrics"]

    except Exception as e:
        logger.error(f"Error during pooled training pipeline: {str(e)}")
        raise e


def main() -> None:
    """CLI entry point for manual training triggers."""
    parser = argparse.ArgumentParser(description="Train LaundryLink forecasting models.")
    parser.add_argument("--shop-id", type=int, default=1, help="Shop to train an own model for.")
    parser.add_argument("--pooled", action="store_true", help="Train the pooled/cold-start model instead.")
    args = parser.parse_args()

    if args.pooled:
        metrics = run_pooled_training_pipeline()
        print(f"Pooled model saved: {POOLED_MODEL_PATH}")
    else:
        metrics = run_training_pipeline(shop_id=args.shop_id)
        print(f"Model saved: {shop_model_path(args.shop_id)}")

    print(f"Metrics: {metrics}")


if __name__ == "__main__":
    main()