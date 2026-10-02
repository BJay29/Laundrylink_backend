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

UPDATED (Naga City fallback): dati, kapag walang latitude/longitude ang
shop (Shop.latitude/longitude ay nullable), nagre-return agad ng empty
DataFrame ang mga function dito — kaya laging rain_mm = 0.0 ang lumalabas
sa Weather Outlook strip. Ngayon, kapag walang coordinates ang shop,
gagamitin ang DEFAULT_LATITUDE/DEFAULT_LONGITUDE (Naga City, Camarines
Sur) para totoong weather pa rin ang makuha.

UPDATED (logging): hindi na tahimik na nilalamon ang mga error — may
warning log na kapag pumalya ang Open-Meteo call, para makita sa Render
logs kung bakit walang weather data.

UPDATED (short cache): ang FinancialForecast at Dashboard ay nag-poll
bawat 60 segundo, kaya may maliit na in-memory cache (30 minuto) para
hindi paulit-ulit na tumama sa Open-Meteo. Success results lang ang
kina-cache — hindi kina-cache ang pagkabigo.

UPDATED (recent days sa training data): ang Archive API ay may ilang
araw na delay — ang pinakabagong mga araw ay `null` ang precipitation_sum.
Dati, ginagawang 0.0 ang mga null na iyon, kaya ang mga pinakabagong
booking days ay "tuyo" ang turing sa training kahit umulan. Ngayon,
ang mga null na araw ay pinupunan muna mula sa Forecast API (past_days,
hanggang 92 araw pabalik), at saka lang 0.0 ang gagamitin kung wala
talagang data.

If the external call still fails for any reason, functions here return
an empty DataFrame rather than raising — callers treat missing weather
as rain_mm = 0.0 so a network hiccup never breaks the forecast graph
entirely.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
REQUEST_TIMEOUT_SECONDS = 10
MAX_PAST_DAYS = 92  # limit ng Forecast API para sa past_days

# Fallback location: Naga City, Camarines Sur — ginagamit kapag walang
# latitude/longitude ang shop sa database.
DEFAULT_LATITUDE = 13.6192
DEFAULT_LONGITUDE = 123.1814

MANILA_TZ = timezone(timedelta(hours=8))

# Cache ng forecast results: {key: (timestamp, DataFrame)}
_FORECAST_CACHE: Dict[Tuple[float, float, int], Tuple[float, pd.DataFrame]] = {}
FORECAST_CACHE_TTL_SECONDS = 30 * 60


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["booking_date", "rain_mm"])


def _resolve_coords(
    latitude: Optional[float], longitude: Optional[float]
) -> Tuple[float, float]:
    """Gamitin ang coordinates ng shop; kung wala, Naga City ang default."""
    if latitude is None or longitude is None:
        return DEFAULT_LATITUDE, DEFAULT_LONGITUDE
    return float(latitude), float(longitude)


def _parse_daily(payload: dict, keep_missing: bool = False) -> pd.DataFrame:
    """
    I-convert ang Open-Meteo `daily` block papunta sa DataFrame.
    keep_missing=True: ang null ay nagiging NaN (para mapunan pa);
    False: ang null ay nagiging 0.0.
    """
    daily = payload.get("daily", {}) or {}
    dates = daily.get("time", []) or []
    rain_values = daily.get("precipitation_sum", []) or []
    if not dates:
        return _empty_frame()

    missing_value = float("nan") if keep_missing else 0.0
    return pd.DataFrame({
        "booking_date": pd.to_datetime(dates),
        "rain_mm": [missing_value if value is None else float(value) for value in rain_values],
    })


def _fill_recent_from_forecast(
    frame: pd.DataFrame, latitude: float, longitude: float
) -> pd.DataFrame:
    """
    Punan ang mga NaN na araw (kadalasan ang pinakabagong ilang araw na
    wala pa sa Archive API) gamit ang Forecast API's past_days.
    """
    missing_mask = frame["rain_mm"].isna()
    if not missing_mask.any():
        return frame

    oldest_missing = frame.loc[missing_mask, "booking_date"].min().date()
    manila_today = datetime.now(MANILA_TZ).date()
    past_days = (manila_today - oldest_missing).days + 1
    past_days = max(1, min(past_days, MAX_PAST_DAYS))

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "precipitation_sum",
        "timezone": "Asia/Manila",
        "past_days": past_days,
        "forecast_days": 1,
    }
    try:
        response = requests.get(FORECAST_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        recent = _parse_daily(response.json())
    except Exception as exc:
        logger.warning("Open-Meteo past_days fill failed: %s", exc)
        return frame

    if recent.empty:
        return frame

    recent_by_date = dict(zip(recent["booking_date"], recent["rain_mm"]))
    frame = frame.copy()
    frame["rain_mm"] = [
        recent_by_date.get(day, value) if pd.isna(value) else value
        for day, value in zip(frame["booking_date"], frame["rain_mm"])
    ]
    return frame


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
    latitude, longitude = _resolve_coords(latitude, longitude)

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
        frame = _parse_daily(response.json(), keep_missing=True)
    except Exception as exc:
        # Network failure, bad coordinates, etc. — degrade gracefully.
        logger.warning("Open-Meteo archive request failed: %s", exc)
        return _empty_frame()

    if frame.empty:
        return frame

    frame = _fill_recent_from_forecast(frame, latitude, longitude)
    frame["rain_mm"] = frame["rain_mm"].fillna(0.0)
    return frame


def get_forecast_rain_mm(
    latitude: Optional[float],
    longitude: Optional[float],
    days: int = 7,
) -> pd.DataFrame:
    """
    Upcoming daily rainfall forecast (mm) for a shop's location, used at
    prediction time. Returns columns: booking_date, rain_mm.
    """
    latitude, longitude = _resolve_coords(latitude, longitude)

    cache_key = (round(latitude, 3), round(longitude, 3), days)
    cached = _FORECAST_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < FORECAST_CACHE_TTL_SECONDS:
        return cached[1].copy()

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
        frame = _parse_daily(response.json())
        if not frame.empty:
            _FORECAST_CACHE[cache_key] = (time.time(), frame)
        return frame.copy()
    except Exception as exc:
        logger.warning("Open-Meteo forecast request failed: %s", exc)
        return _empty_frame()