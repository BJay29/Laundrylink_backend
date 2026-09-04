"""
Weather data access for LaundryLink forecasting.

Uses Open-Meteo — free, no API key required. Two endpoints:
  - Archive API: real historical weather, used to build TRAINING data
    (paired with each shop's actual past booking dates).
  - Forecast API: upcoming weather, used at PREDICTION time for the
    next N days.

Both use `precipitation_sum` (total daily rainfall in mm) as the single
feature — this variable is available under the same name on both
endpoints, so training and prediction stay consistent (no mismatch
between "probability" at forecast time vs "actual mm" at training time).

If a shop has no latitude/longitude set (Shop.latitude/longitude are
nullable), or the external call fails for any reason, functions here
return an empty DataFrame rather than raising — callers treat missing
weather as rain_mm = 0.0 so a network hiccup never breaks the forecast
graph entirely.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
REQUEST_TIMEOUT_SECONDS = 10


def get_historical_rain_mm(
    latitude: Optional[float],
    longitude: Optional[float],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """
    Real historical daily rainfall (mm) for a shop's location, used to
    build training data. Returns columns: booking_date, rain_mm.
    """
    if latitude is None or longitude is None:
        return pd.DataFrame(columns=["booking_date", "rain_mm"])

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "daily": "precipitation_sum",
        "timezone": "Asia/Manila",
    }
    try:
        response = requests.get(ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        daily = response.json().get("daily", {})
        dates = daily.get("time", [])
        rain_values = daily.get("precipitation_sum", [])
        return pd.DataFrame({
            "booking_date": pd.to_datetime(dates),
            "rain_mm": [float(value or 0.0) for value in rain_values],
        })
    except Exception:
        # Network failure, bad coordinates, etc. — degrade gracefully.
        return pd.DataFrame(columns=["booking_date", "rain_mm"])


def get_forecast_rain_mm(
    latitude: Optional[float],
    longitude: Optional[float],
    days: int = 7,
) -> pd.DataFrame:
    """
    Upcoming daily rainfall forecast (mm) for a shop's location, used at
    prediction time. Returns columns: booking_date, rain_mm.
    """
    if latitude is None or longitude is None:
        return pd.DataFrame(columns=["booking_date", "rain_mm"])

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "precipitation_sum",
        "timezone": "Asia/Manila",
        "forecast_days": days,
    }
    try:
        response = requests.get(FORECAST_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        daily = response.json().get("daily", {})
        dates = daily.get("time", [])
        rain_values = daily.get("precipitation_sum", [])
        return pd.DataFrame({
            "booking_date": pd.to_datetime(dates),
            "rain_mm": [float(value or 0.0) for value in rain_values],
        })
    except Exception:
        return pd.DataFrame(columns=["booking_date", "rain_mm"])