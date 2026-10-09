"""
Weather data access for LaundryLink forecasting.

Uses Open-Meteo — free, no API key required. Two endpoints:
  - Archive API: real historical weather, used to build TRAINING data.
  - Forecast API: upcoming weather, used at PREDICTION time.

Both use `precipitation_sum` (total daily rainfall in mm).

Naga City fallback: kapag walang latitude/longitude ang shop, gagamitin
ang DEFAULT_LATITUDE/DEFAULT_LONGITUDE.

Cache: 30 minuto para sa successful forecast results.

UPDATED (429 fix): dati, hindi kina-cache ang pagkabigo, kaya kapag
nag-429 (Too Many Requests) ang Open-Meteo, tinatamaan ulit ito sa
bawat poll (60s) at lalo lang nagtatagal ang limit. Ngayon:
  - Pagkatapos pumalya, may COOLDOWN (5 minuto) bago sumubok ulit.
  - Habang pumapalya, ibinabalik ang LUMANG cache (stale) kung meron,
    para hindi biglang 0.0 ang rain_mm.

UPDATED (recent days sa training data): ang mga null na araw sa Archive
API ay pinupunan muna mula sa Forecast API (past_days), at saka lang
0.0 kung wala talagang data.

Kapag pumalya pa rin ang external call, empty DataFrame ang ibinabalik
(hindi nagra-raise); ang callers ay gumagamit ng rain_mm = 0.0.
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

# Fallback location: Naga City, Camarines Sur
DEFAULT_LATITUDE = 13.6192
DEFAULT_LONGITUDE = 123.1814

MANILA_TZ = timezone(timedelta(hours=8))

# Cache ng forecast results: {key: (timestamp, DataFrame)}
_FORECAST_CACHE: Dict[Tuple[float, float, int], Tuple[float, pd.DataFrame]] = {}
FORECAST_CACHE_TTL_SECONDS = 30 * 60

# Cooldown pagkatapos pumalya ang forecast request: {key: unix_time_hanggang_kailan}
FORECAST_FAIL_COOLDOWN_SECONDS = 5 * 60
_FORECAST_FAIL_UNTIL: Dict[Tuple[float, float, int], float] = {}


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

    May cache (30 min), cooldown pagkatapos pumalya (5 min), at
    stale-cache fallback para hindi biglang 0.0 ang rain_mm.
    """
    latitude, longitude = _resolve_coords(latitude, longitude)

    cache_key = (round(latitude, 3), round(longitude, 3), days)
    now = time.time()

    cached = _FORECAST_CACHE.get(cache_key)
    if cached and (now - cached[0]) < FORECAST_CACHE_TTL_SECONDS:
        return cached[1].copy()

    # Kamakailan lang pumalya: huwag munang tumama ulit sa Open-Meteo.
    if now < _FORECAST_FAIL_UNTIL.get(cache_key, 0.0):
        return cached[1].copy() if cached else _empty_frame()

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
            _FORECAST_CACHE[cache_key] = (now, frame)
        _FORECAST_FAIL_UNTIL.pop(cache_key, None)
        return frame.copy()
    except Exception as exc:
        logger.warning(
            "Open-Meteo forecast request failed: %s (cooldown %d s)",
            exc, FORECAST_FAIL_COOLDOWN_SECONDS,
        )
        _FORECAST_FAIL_UNTIL[cache_key] = now + FORECAST_FAIL_COOLDOWN_SECONDS
        # Mas mabuti ang lumang (stale) cache kaysa 0.0 na ulan.
        return cached[1].copy() if cached else _empty_frame()