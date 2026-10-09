"""
Database-to-feature preparation for LaundryLink forecasting.

REVERTED (revenue-based forecast): ang per-shop model ay hinuhulaan ulit
ang KITA (total_revenue) kada araw, gamit ang trend, araw ng linggo,
ulan, at booking_count/total_loads bilang input.

Ang booking_count at total_loads ay hindi pa alam sa mga susunod na
araw, kaya sa prediction time (PredictionService) ay ang AVERAGE NG
SARILING SHOP kada araw ng linggo ang ipinapasok (weekday_profile na
naka-save sa model artifact), hindi na ang nakapirming 12/18.

Ang pooled (cold-start) model ay booking_ratio pa rin ang target.
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
FEATURE_COLUMNS = [
    "day_index",
    "day_of_week",
    "is_weekend",
    "rain_mm",
    "booking_count",
    "total_loads",
]

# Ang hinuhulaan ng per-shop model: kita kada araw.
TARGET_COLUMN = "total_revenue"

# Feature columns used by the POOLED (multi-shop, cold-start) model.
POOLED_FEATURE_COLUMNS = ["day_of_week", "is_weekend", "rain_mm"]

# Ang pooled model ay booking_ratio ang hinuhulaan.
POOLED_TARGET_COLUMN = "booking_ratio"

# Minimum number of daily rows a shop must have before its data is
# folded into the pooled/global training set.
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

    frame["day_index"] = (frame["booking_date"] - first_date).dt.days.astype(int)
    frame["day_of_week"] = frame["booking_date"].dt.weekday.astype(int)
    frame["is_weekend"] = frame["day_of_week"].isin([5, 6]).astype(int)

    # Attach real historical rainfall for this shop's own location.
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
    model. Each shop's daily numbers are converted into RATIOS against
    that shop's own average so shops of different sizes combine cleanly.

    Shops with fewer than MIN_DAYS_FOR_POOLING days of data are skipped.
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
    """Establishes a database session and retrieves the booking data frame."""
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
    # Usage: python -m ml_engine.data_prep [shop_id]
    target_shop = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    df = load_training_data(shop_id=target_shop)
    if df.empty:
        print(f"No booking data available for shop {target_shop}.")
    else:
        print(f"Shop {target_shop}: {len(df)} days of data")
        print(df.tail(10).to_string(index=False))
        print("\nAverage per weekday (0=Mon ... 6=Sun):")
        print(
            df.groupby("day_of_week")[["booking_count", "total_loads", "total_revenue"]]
            .mean()
            .round(2)
            .to_string()
        )