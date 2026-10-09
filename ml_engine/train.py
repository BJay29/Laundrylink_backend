"""
Train the LaundryLink demand forecasting models.

REVERTED (revenue-based forecast): ang per-shop model ay hinuhulaan ulit
ang KITA kada araw (target = total_revenue) mula sa trend, araw ng
linggo, ulan, booking_count at total_loads.

Dahil hindi pa alam ang booking_count/total_loads ng mga susunod na
araw, sine-save sa artifact ang "weekday_profile": ang average ng
sariling shop ng bookings at loads para sa bawat araw ng linggo. Ito
ang ipinapasok ng PredictionService sa prediction (hindi na ang
nakapirming 12/18).

Ridge regression, baseline comparison, at "reliability" flag ay
nandito pa rin.

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

import matplotlib
matplotlib.use("Agg")  # walang GUI na kailangan (safe sa server)
import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score

from ml_engine.data_prep import (
    FEATURE_COLUMNS,
    POOLED_FEATURE_COLUMNS,
    TARGET_COLUMN,
    POOLED_TARGET_COLUMN,
    load_training_data,
    load_pooled_training_data,
)

# Configuration of paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT_ROOT / "ml_models"
REPORT_PATH = MODEL_DIR / "accuracy_report.png"
METRICS_PATH = MODEL_DIR / "model_metrics.json"


def shop_model_path(shop_id: int) -> Path:
    return MODEL_DIR / f"forecast_shop_{shop_id}.pkl"


POOLED_MODEL_PATH = MODEL_DIR / "forecast_pooled.pkl"

MIN_TRAINING_DAYS = 14
RECOMMENDED_MIN_DAYS = 30

# Mas mababa rito ang validation days, hindi pa mapagkakatiwalaan ang
# accuracy/R².
MIN_RELIABLE_VALIDATION_DAYS = 10

# Gaano karaming araw ang pinakamababa para sa training split.
MIN_TRAIN_ROWS = 10

# Regularization: pinipigilan ang sobrang laking coefficients kapag
# kaunti ang data.
RIDGE_ALPHA = 1.0

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _split_validation(frame):
    """
    Splits data into training and validation sets (time-ordered).
    Sinisiguro na may hindi bababa sa MIN_TRAIN_ROWS na training rows.
    """
    total = len(frame)
    validation_size = max(5, int(total * 0.20))
    validation_size = min(validation_size, max(2, total - MIN_TRAIN_ROWS))
    validation_size = min(validation_size, total - 2)
    train_frame = frame.iloc[:-validation_size].copy()
    validation_frame = frame.iloc[-validation_size:].copy()
    return train_frame, validation_frame


def _save_accuracy_report(validation_frame, predictions) -> None:
    """Generates and saves a plot comparing actual vs predicted daily revenue."""
    plt.figure(figsize=(10, 5))
    plt.plot(validation_frame["booking_date"], validation_frame[TARGET_COLUMN], marker="o", label="Actual")
    plt.plot(validation_frame["booking_date"], predictions, marker="x", label="Predicted")
    plt.title("LaundryLink Forecast Validation: Actual vs Predicted Daily Revenue")
    plt.xlabel("Date")
    plt.ylabel("Daily Revenue (PHP)")
    plt.xticks(rotation=35, ha="right")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(REPORT_PATH, dpi=160)
    plt.close()


def _coefficients(model, feature_columns) -> dict:
    return {column: round(float(coef), 4) for column, coef in zip(feature_columns, model.coef_)}


def _evaluate(y_true, y_pred, y_train) -> dict:
    """
    accuracy_percentage = 100 - WAPE, naka-clamp sa 0..100.
    baseline_mae = error ng simpleng "hulaan ang average ng training".
    beats_baseline = mas mahusay ba ang model kaysa sa simpleng average.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    mae = float(mean_absolute_error(y_true, y_pred))
    total_actual = float(np.abs(y_true).sum())
    if total_actual > 0:
        accuracy = max(0.0, min(100.0, 100.0 - (np.abs(y_true - y_pred).sum() / total_actual) * 100.0))
    else:
        accuracy = 0.0

    try:
        r2 = float(r2_score(y_true, y_pred))
    except Exception:
        r2 = 0.0

    baseline_prediction = float(np.mean(y_train)) if len(y_train) else 0.0
    baseline_mae = float(np.mean(np.abs(y_true - baseline_prediction)))

    return {
        "accuracy_percentage": round(accuracy, 2),
        "mean_absolute_error": round(mae, 2),
        "r2_score": round(r2, 4),
        "baseline_mae": round(baseline_mae, 2),
        "beats_baseline": bool(mae < baseline_mae),
    }


def _reliability(total_days: int, validation_days: int) -> str:
    """'low' kung kulang ang data para mapagkatiwalaan ang metrics."""
    if validation_days < MIN_RELIABLE_VALIDATION_DAYS or total_days < RECOMMENDED_MIN_DAYS:
        return "low"
    return "ok"


def _build_weekday_profile(frame) -> dict:
    """
    Average ng bookings at loads ng shop para sa bawat araw ng linggo
    (0=Lunes ... 6=Linggo). Kapag may araw ng linggo na walang data,
    gagamitin ang overall average ng shop.
    """
    overall_bookings = float(frame["booking_count"].mean())
    overall_loads = float(frame["total_loads"].mean())

    profile = {}
    for dow in range(7):
        group = frame[frame["day_of_week"] == dow]
        if len(group) > 0:
            profile[dow] = {
                "bookings": float(group["booking_count"].mean()),
                "loads": float(group["total_loads"].mean()),
            }
        else:
            profile[dow] = {"bookings": overall_bookings, "loads": overall_loads}
    return profile


def run_training_pipeline(shop_id: int = 1) -> dict:
    """
    Trains a SHOP-SPECIFIC model and saves it to forecast_shop_{shop_id}.pkl.
    Requires at least MIN_TRAINING_DAYS days of that shop's own daily
    booking history.

    Target: daily total_revenue. Features: day_index, day_of_week,
    is_weekend, rain_mm, booking_count, total_loads.
    """
    try:
        frame = load_training_data(shop_id=shop_id)
        if len(frame) < MIN_TRAINING_DAYS:
            raise ValueError(
                f"At least {MIN_TRAINING_DAYS} daily booking aggregates are required to train the model."
            )
        if len(frame) < RECOMMENDED_MIN_DAYS:
            logger.warning(
                "Shop %s has only %d days of data — metrics will be marked low-reliability "
                "until there are at least %d days.",
                shop_id, len(frame), RECOMMENDED_MIN_DAYS,
            )

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        train_frame, validation_frame = _split_validation(frame)

        model = Ridge(alpha=RIDGE_ALPHA)
        model.fit(train_frame[FEATURE_COLUMNS].to_numpy(), train_frame[TARGET_COLUMN].to_numpy())

        validation_predictions = model.predict(validation_frame[FEATURE_COLUMNS].to_numpy())
        validation_predictions = np.maximum(validation_predictions, 0.0)

        metrics = _evaluate(
            validation_frame[TARGET_COLUMN],
            validation_predictions,
            train_frame[TARGET_COLUMN],
        )
        metrics["validation_days"] = int(len(validation_frame))
        metrics["training_days"] = int(len(train_frame))
        metrics["reliability"] = _reliability(len(frame), len(validation_frame))

        coefficients = _coefficients(model, FEATURE_COLUMNS)
        logger.info(
            "Shop %s learned coefficients: %s (intercept %.2f). "
            "rain_mm = %+.4f PHP per extra mm of rain.",
            shop_id, coefficients, float(model.intercept_), coefficients.get("rain_mm", 0.0),
        )

        total_bookings_all = float(frame["booking_count"].sum())
        total_loads_all = float(frame["total_loads"].sum())
        average_ticket = (
            float(frame["total_revenue"].sum() / total_bookings_all)
            if total_bookings_all > 0 else 150.0
        )
        average_loads_per_booking = (
            total_loads_all / total_bookings_all if total_bookings_all > 0 else 1.0
        )
        last_day_index = int(frame["day_index"].max())
        weekday_profile = _build_weekday_profile(frame)

        artifact = {
            "model": model,
            "feature_columns": FEATURE_COLUMNS,
            "target": TARGET_COLUMN,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "shop_id": shop_id,
            "average_ticket": round(average_ticket, 2),
            "average_loads_per_booking": round(average_loads_per_booking, 3),
            "weekday_profile": weekday_profile,
            "last_day_index": last_day_index,
            "coefficients": coefficients,
            "metrics": metrics,
        }

        model_path = shop_model_path(shop_id)
        backup_path = MODEL_DIR / f"forecast_shop_{shop_id}_backup.pkl"
        if model_path.exists():
            shutil.copy(model_path, backup_path)

        with model_path.open("wb") as model_file:
            pickle.dump(artifact, model_file)

        # Global metrics file (legacy) — reflects the most recently trained shop.
        with open(METRICS_PATH, "w") as f:
            json.dump(metrics, f, indent=4)

        _save_accuracy_report(validation_frame, validation_predictions)

        logger.info(
            "Training complete for shop %s. Accuracy: %.2f%% (MAE %.2f vs baseline %.2f, "
            "beats baseline: %s, reliability: %s).",
            shop_id, metrics["accuracy_percentage"], metrics["mean_absolute_error"],
            metrics["baseline_mae"], metrics["beats_baseline"], metrics["reliability"],
        )
        return metrics

    except Exception as e:
        logger.error(f"Error during training pipeline for shop {shop_id}: {str(e)}")
        raise e


def run_pooled_training_pipeline() -> dict:
    """
    Trains the pooled/global cold-start model across every shop that has
    at least MIN_DAYS_FOR_POOLING days of history. Target is
    booking_ratio (each shop's day normalized against its own average
    daily bookings).
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

        model = Ridge(alpha=RIDGE_ALPHA)
        model.fit(train_frame[POOLED_FEATURE_COLUMNS].to_numpy(), train_frame[POOLED_TARGET_COLUMN].to_numpy())

        validation_predictions = model.predict(validation_frame[POOLED_FEATURE_COLUMNS].to_numpy())
        validation_predictions = np.maximum(validation_predictions, 0.0)

        mae = mean_absolute_error(validation_frame[POOLED_TARGET_COLUMN], validation_predictions)
        r2 = r2_score(validation_frame[POOLED_TARGET_COLUMN], validation_predictions)

        coefficients = _coefficients(model, POOLED_FEATURE_COLUMNS)
        logger.info(
            "Pooled model learned coefficients: %s (intercept %.4f). "
            "rain_mm = %+.4f booking-ratio per extra mm of rain.",
            coefficients, float(model.intercept_), coefficients.get("rain_mm", 0.0),
        )

        artifact = {
            "model": model,
            "feature_columns": POOLED_FEATURE_COLUMNS,
            "target": POOLED_TARGET_COLUMN,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "shop_count": int(frame["shop_id"].nunique()),
            "coefficients": coefficients,
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