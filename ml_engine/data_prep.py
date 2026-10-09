"""
Database-to-feature preparation for LaundryLink forecasting.

UPDATED (weather-driven bookings forecast): ang model ay hinuhulaan na
ang DAMI NG BOOKINGS (hindi na ang kita) mula sa araw ng linggo, trend,
at ulan (rain_mm). Ang income ay kinukuwenta na lang pagkatapos:
predicted_bookings x average_ticket (see PredictionService).

Dati, kasama sa features ang booking_count at total_loads — pero hindi pa
alam ang mga iyon sa mga susunod na araw, kaya nilalagyan lang ng
nakapirming 12/18 sa prediction at halos wala nang epekto ang ulan.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

# Add project root to sys.path to ensure local imports work correctly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models import Booking, Shop
from app.services import weather_service

logger = logging.getLogger(__name__)

# Feature columns used by the PER-SHOP machine learning model.
# UPDATED: tinanggal ang "booking_count" at "total_loads" — ang mga iyon
# na ang TARGET/kahihinatnan, hindi na input. Ang natira ay mga bagay na
# alam na nang maaga: trend (day_index), araw ng linggo, at forecast na
# ulan (rain_mm, matched by date sa real historical weather sa training).
FEATURE_COLUMNS = ["day_index", "day_of_week", "is_weekend", "rain_mm"]

# Ang hinuhulaan ng per-shop model.
TARGET_COLUMN = "booking_count"

# Feature columns used by the POOLED (multi-shop, cold-start) model.
# No day_index here — meaningful lang iyon sa loob ng iisang shop's own
# trend. Weekday pattern + rain ang mga signal na nagge-generalize sa
# iba't ibang shop.
POOLED_FEATURE_COLUMNS = ["day_of_week", "is_weekend", "rain_mm"]

# UPDATED: ang pooled model ay hinuhulaan na ang booking_ratio (bookings
# ng araw / karaniwang bookings ng shop), hindi na revenue_ratio.
POOLED_TARGET_COLUMN = "booking_ratio"

# Minimum number of daily rows a shop must have before its data is
# folded into the pooled/global training set. Matches the 14-day floor
# already enforced for training a shop's own model in ml_engine/train.py,
# so a shop only ever "graduates" from contributing-to-pooled to
# having-its-own-model, never skips a state.
MIN_DAYS_FOR_POOLING = 14


def fetch_daily_booking_frame(db: Session, shop_id: int = 1) -> pd.DataFrame:
    """
    Query bookings grouped by created_at date and return training-ready daily rows.
    """
    rows: Iterable[tuple] = (
        db.query(
            func.date(Booking.created_at).label("booking_date"),
            func.count(Booking.id).label("booking_count"),
            func.coalesce(func.sum(Booking.loads), 0).label("total_loads"),
            func.coalesce(func.sum(Booking.weight), 0.0).label("total_weight"),
            func.coalesce(func.sum(Booking.total_price), 0.0).label("total_revenue"),
        )
        .filter(Booking.shop_id == shop_id)
        .group_by(func.date(Booking.created_at))
        .order_by(func.date(Booking.created_at))
        .all()
    )

    records = [
        {
            "booking_date": row.booking_date,
            "booking_count": int(row.booking_count or 0),
            "total_loads": int(row.total_loads or 0),
            "total_weight": float(row.total_weight or 0.0),
            "total_revenue": float(row.total_revenue or 0.0),
        }
        for row in rows
    ]

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return frame

    # Prepare time-series features
    frame["booking_date"] = pd.to_datetime(frame["booking_date"])
    first_date = frame["booking_date"].min()

    # Calculate index, weekday, and weekend status for the AI model
    frame["day_index"] = (frame["booking_date"] - first_date).dt.days.astype(int)
    frame["day_of_week"] = frame["booking_date"].dt.weekday.astype(int)
    frame["is_weekend"] = frame["day_of_week"].isin([5, 6]).astype(int)

    # Attach real historical rainfall for this shop's own location,
    # matched to each booking date.
    #
    # Kung walang latitude/longitude ang shop (NULL sa DB), ang
    # weather_service na ang gagamit ng Naga City fallback. Ang 0.0 ay
    # fallback na lang kapag talagang pumalya ang external call, para
    # hindi masira ang training.
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    rain_frame = weather_service.get_historical_rain_mm(
        shop.latitude if shop else None,
        shop.longitude if shop else None,
        frame["booking_date"].min().date(),
        frame["booking_date"].max().date(),
    )
    if not rain_frame.empty:
        frame = frame.merge(rain_frame, on="booking_date", how="left")
    else:
        logger.warning(
            "Shop %s: no historical weather data available — rain_mm set to 0.0 for all %d training days.",
            shop_id, len(frame),
        )
        frame["rain_mm"] = 0.0

    matched_days = int(frame["rain_mm"].notna().sum())
    frame["rain_mm"] = frame["rain_mm"].fillna(0.0)

    # Para madaling ma-verify pagkatapos mag-retrain: dapat hindi 0
    # ang "rainy days" kung umulan talaga sa panahong iyon.
    logger.info(
        "Shop %s: weather matched for %d/%d training days, %d day(s) with rain > 0 mm.",
        shop_id, matched_days, len(frame), int((frame["rain_mm"] > 0).sum()),
    )

    return frame[
        [
            "booking_date",
            "day_index",
            "day_of_week",
            "is_weekend",
            "booking_count",
            "total_loads",
            "total_weight",
            "total_revenue",
            "rain_mm",
        ]
    ]


def fetch_pooled_daily_frame(db: Session) -> pd.DataFrame:
    """
    Builds the multi-shop training set for the pooled/global cold-start
    model.

    Each contributing shop's daily booking_count and total_revenue are
    converted into RATIOS against that shop's own average — this is
    what lets a tiny shop and a big shop sit in the same training set
    without the big shop's raw numbers dominating the fit. The pooled
    model then learns "how much a day's bookings deviate from a shop's
    own normal, given the day of week and how much it rained" — a
    coefficient that transfers to a brand-new shop with zero history,
    scaled by that new shop's own baseline once it has one (see
    PredictionService._get_shop_baselines).

    UPDATED: ang target ay booking_ratio na (revenue_ratio ay nandito
    pa rin sa frame pero hindi na ginagamit sa training).

    Shops with fewer than MIN_DAYS_FOR_POOLING days of data are skipped
    entirely — not enough signal to compute a meaningful average yet.
    """
    shops = db.query(Shop).all()
    pooled_rows = []

    for shop in shops:
        shop_frame = fetch_daily_booking_frame(db, shop_id=shop.id)
        if shop_frame.empty or len(shop_frame) < MIN_DAYS_FOR_POOLING:
            continue

        avg_daily_bookings = shop_frame["booking_count"].mean()
        avg_daily_revenue = shop_frame["total_revenue"].mean()
        if avg_daily_bookings <= 0 or avg_daily_revenue <= 0:
            continue

        shop_frame = shop_frame.copy()
        shop_frame["booking_ratio"] = shop_frame["booking_count"] / avg_daily_bookings
        shop_frame["revenue_ratio"] = shop_frame["total_revenue"] / avg_daily_revenue
        shop_frame["shop_id"] = shop.id

        pooled_rows.append(
            shop_frame[
                ["shop_id", "booking_date", "day_of_week", "is_weekend", "rain_mm", "booking_ratio", "revenue_ratio"]
            ]
        )
    
    if not pooled_rows:
        return pd.DataFrame(
            columns=["shop_id", "booking_date", "day_of_week", "is_weekend", "rain_mm", "booking_ratio", "revenue_ratio"]
        )

    return pd.concat(pooled_rows, ignore_index=True)


def load_training_data(shop_id: int = 1) -> pd.DataFrame:
    """
    Establishes a database session and retrieves the booking data frame.
    """
    db = SessionLocal()
    try:
        return fetch_daily_booking_frame(db, shop_id=shop_id)
    finally:
        db.close()


def load_pooled_training_data() -> pd.DataFrame:
    """Establishes a database session and retrieves the pooled multi-shop frame."""
    db = SessionLocal()
    try:
        return fetch_pooled_daily_frame(db)
    finally:
        db.close()


if __name__ == "__main__":
    # Test script to print the last 10 entries of processed data
    df = load_training_data()
    print(df.tail(10).to_string(index=False) if not df.empty else "No booking data available.")