"""
Database-to-feature preparation for LaundryLink forecasting.
"""

from __future__ import annotations

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
from app.models import Booking

# Feature columns used by the machine learning model
FEATURE_COLUMNS = ["day_index", "day_of_week", "is_weekend", "booking_count", "total_loads"]


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
        ]
    ]


def load_training_data(shop_id: int = 1) -> pd.DataFrame:
    """
    Establishes a database session and retrieves the booking data frame.
    """
    db = SessionLocal()
    try:
        return fetch_daily_booking_frame(db, shop_id=shop_id)
    finally:
        db.close()


if __name__ == "__main__":
    # Test script to print the last 10 entries of processed data
    df = load_training_data()
    print(df.tail(10).to_string(index=False) if not df.empty else "No booking data available.")