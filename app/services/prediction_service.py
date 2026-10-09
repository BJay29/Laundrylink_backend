import numpy as np
from typing import Dict, Any, Optional
import pickle
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
# Import the training logic from your ml_engine
from ml_engine.train import run_training_pipeline, run_pooled_training_pipeline
from app.services import weather_service


class PredictionService:
    """
    Core logic for calculating utility consumption and machine profitability,
    plus the 7-day bookings/income forecast used by the Financial Forecast page.

    get_revenue_forecast() resolves per shop using a 3-tier fallback:

        Tier 1 — Shop's own model (forecast_shop_{shop_id}.pkl):
            best accuracy, trained on this shop's own history + its own
            location's real historical weather. Needs 14+ days of data.

        Tier 2 — Pooled model (forecast_pooled.pkl):
            used when the shop has no model of its own yet. Predicts a
            booking RATIO from weekday + rain, scaled by the shop's own
            average daily bookings (or an assumed baseline).

        Tier 3 — Weather-only outlook:
            used only when the pooled model doesn't exist yet.
            predicted_bookings/projected_income are None.

    Every row carries "model_tier" so the frontend can show which tier
    produced it.

    REVERTED (revenue-based shop model): ang per-shop model ay kita
    (total_revenue) ang hinuhulaan. Ang booking_count/total_loads na
    kailangan nito bilang input ay kinukuha na sa "weekday_profile" ng
    artifact (average ng SARILING shop kada araw ng linggo), hindi na
    ang nakapirming 12 (weekday) / 18 (weekend). Ang predicted_bookings
    ay hinuhugot mula sa projected_income / average_ticket.

    BACKWARD COMPATIBILITY: ang artifact na walang "weekday_profile"
    ay gumagamit pa rin ng 12/18 fallback; ang artifact na may
    target="booking_count" (galing sa weather-driven version) ay
    patuloy ding gumagana hanggang mag-retrain.

    Weather: ang forecast loop ay nagsisimula sa bukas (offset 1) hanggang
    offset `days`, kaya humihingi ng days + 1 na araw ang _rain_lookup().
    Ang petsa ay kinukuha gamit ang _manila_now() (UTC+8).
    """

    # --- NAGA CITY UTILITY RATES ---
    ELEC_RATE_KWH = 8.83
    WATER_RATE_CUM = 37.90
    DETERGENT_FIXED = 12.75

    # --- HARDWARE SPECIFICATIONS (Wattage) ---
    WATTS_WASHER = 1200
    WATTS_DRYER = 5000

    # --- DEFAULT HARDWARE DURATIONS (Minutes) ---
    MACHINE_DURATIONS = {
        "washer": 45,
        "dryer":  40,
    }

    MODEL_DIR = Path(__file__).resolve().parents[2] / "ml_models"
    POOLED_MODEL_PATH = MODEL_DIR / "forecast_pooled.pkl"
    METRICS_PATH = MODEL_DIR / "model_metrics.json"

    # Philippines (UTC+8, walang DST)
    MANILA_TZ = timezone(timedelta(hours=8))

    # Assumed daily bookings for a shop with ZERO history (pooled tier only).
    ASSUMED_NEW_SHOP_DAILY_BOOKINGS = 12

    @classmethod
    def _manila_now(cls) -> datetime:
        """Kasalukuyang oras sa Asia/Manila, anuman ang timezone ng server."""
        return datetime.now(cls.MANILA_TZ)

    @classmethod
    def retrain_model(cls, shop_id: int = 1):
        """
        Triggers training of a single shop's own model. Called by the
        background scheduler every 24 hours, and by POST /analytics/retrain-model.
        """
        try:
            print(f"[{datetime.now()}] Automated training sequence initiated for shop {shop_id}.")
            run_training_pipeline(shop_id=shop_id)
            print(f"[{datetime.now()}] Automated training completed successfully for shop {shop_id}.")
        except Exception as e:
            print(f"[{datetime.now()}] Error during automated training for shop {shop_id}: {e}")

    @classmethod
    def retrain_pooled_model(cls):
        """
        Triggers training of the pooled/cold-start model across
        every eligible shop. Called by POST /analytics/retrain-pooled-model.
        """
        try:
            print(f"[{datetime.now()}] Pooled training sequence initiated.")
            run_pooled_training_pipeline()
            print(f"[{datetime.now()}] Pooled training completed successfully.")
        except Exception as e:
            print(f"[{datetime.now()}] Error during pooled training: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # SHOP CONTEXT HELPERS
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def _get_shop_context(cls, db, shop_id: int) -> Dict[str, Any]:
        """
        Pulls what every tier needs: the shop's coordinates (for real
        weather) and its own average ticket price (from its configured
        ServiceType catalog).

        NOTE: kung NULL ang latitude/longitude ng shop, ipinapasa pa rin
        ang None — ang weather_service.py na ang nag-a-apply ng Naga City
        fallback.
        """
        from app.models import Shop, ServiceType

        shop = db.query(Shop).filter(Shop.id == shop_id).first()
        active_services = (
            db.query(ServiceType)
            .filter(ServiceType.shop_id == shop_id, ServiceType.is_active == True)
            .all()
        )

        if active_services:
            average_ticket = sum(s.price for s in active_services) / len(active_services)
        else:
            average_ticket = 150.0

        return {
            "latitude": shop.latitude if shop else None,
            "longitude": shop.longitude if shop else None,
            "average_ticket": max(float(average_ticket), 1.0),
        }

    @classmethod
    def _get_shop_baselines(cls, db, shop_id: int, average_ticket: float) -> Dict[str, float]:
        """
        Baselines para i-scale ang pooled model's ratio prediction:
          - "bookings": karaniwang bookings kada araw
          - "revenue":  karaniwang kita kada araw
          - "ticket":   karaniwang halaga kada booking

        Prefers the shop's OWN historical averages; falls back to assumed
        values only for a shop with truly zero history.
        """
        from sqlalchemy import func
        from app.models import Booking

        rows = (
            db.query(
                func.date(Booking.created_at).label("d"),
                func.count(Booking.id).label("n"),
                func.sum(Booking.total_price).label("rev"),
            )
            .filter(Booking.shop_id == shop_id)
            .group_by(func.date(Booking.created_at))
            .all()
        )
        if rows:
            avg_bookings = sum(int(r.n or 0) for r in rows) / len(rows)
            avg_revenue = sum(float(r.rev or 0.0) for r in rows) / len(rows)
            if avg_bookings > 0:
                return {
                    "bookings": avg_bookings,
                    "revenue": avg_revenue,
                    "ticket": max(avg_revenue / avg_bookings, 1.0),
                }

        assumed = float(cls.ASSUMED_NEW_SHOP_DAILY_BOOKINGS)
        return {
            "bookings": assumed,
            "revenue": average_ticket * assumed,
            "ticket": average_ticket,
        }

    @classmethod
    def _rain_lookup(cls, latitude: Optional[float], longitude: Optional[float], days: int) -> Dict[Any, float]:
        """
        Mapping ng {petsa (Manila): rain_mm} para sa susunod na `days`
        na araw simula BUKAS. Humihingi ng `days + 1` na araw sa
        Open-Meteo dahil ang forecast_days=N ay today..today+(N-1) lang.
        """
        rain_frame = weather_service.get_forecast_rain_mm(latitude, longitude, days=days + 1)
        if rain_frame.empty:
            print(f"[{datetime.now()}] Weather lookup returned no data — rain_mm will default to 0.0.")
            return {}
        return {row.booking_date.date(): float(row.rain_mm) for row in rain_frame.itertuples()}

    @classmethod
    def _make_row(
        cls,
        target_date: datetime,
        predicted_bookings: Optional[int],
        projected_income: Optional[float],
        rain_mm: float,
        model_tier: str,
    ) -> Dict[str, Any]:
        """Isang forecast row sa format na inaasahan ng frontend."""
        return {
            "date": target_date.strftime("%Y-%m-%d"),
            "label": target_date.strftime("%b %d, %a"),
            "predicted_bookings": predicted_bookings,
            "projected_income": round(projected_income, 2) if projected_income is not None else None,
            "rain_mm": round(rain_mm, 1),
            "is_peak": target_date.weekday() in (0, 4, 5, 6),
            "model_tier": model_tier,
        }

    # ─────────────────────────────────────────────────────────────────────
    # TIER 1 — SHOP'S OWN MODEL
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def _forecast_from_shop_model(cls, model_path: Path, context: Dict[str, Any], days: int) -> list:
        with model_path.open("rb") as model_file:
            artifact = pickle.load(model_file)

        model = artifact["model"]
        feature_columns = artifact["feature_columns"]
        # Walang "target" = lumang artifact na kita (total_revenue) ang hinuhulaan.
        target = artifact.get("target", "total_revenue")
        average_ticket = max(float(artifact.get("average_ticket", context["average_ticket"])), 1.0)
        average_loads_per_booking = max(float(artifact.get("average_loads_per_booking", 1.0)), 1.0)
        last_day_index = int(artifact.get("last_day_index", 0))
        # Average ng SARILING shop kada araw ng linggo (mula sa training).
        weekday_profile = artifact.get("weekday_profile") or {}

        rain_by_date = cls._rain_lookup(context["latitude"], context["longitude"], days)

        today = cls._manila_now()
        forecast_rows = []
        for offset in range(1, days + 1):
            target_date = today + timedelta(days=offset)
            day_of_week = target_date.weekday()
            is_weekend = 1 if day_of_week in (5, 6) else 0
            rain_mm = rain_by_date.get(target_date.date(), 0.0)

            # booking_count / total_loads bilang input ng revenue model:
            # gamitin ang average ng shop para sa araw na iyon; kung
            # lumang artifact na walang profile, 12/18 fallback.
            profile = weekday_profile.get(day_of_week)
            if profile:
                expected_bookings = max(1, round(profile["bookings"]))
                expected_loads = max(1, round(profile["loads"]))
            else:
                expected_bookings = 18 if is_weekend else 12
                expected_loads = max(1, round(expected_bookings * average_loads_per_booking))

            feature_map = {
                "day_index": last_day_index + offset,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend,
                "rain_mm": rain_mm,
                "booking_count": expected_bookings,
                "total_loads": expected_loads,
            }
            features = [[feature_map[column] for column in feature_columns]]
            prediction = max(float(model.predict(features)[0]), 0.0)

            if target == "booking_count":
                predicted_bookings = max(0, round(prediction))
                projected_income = predicted_bookings * average_ticket
            else:
                projected_income = prediction
                predicted_bookings = max(0, round(projected_income / average_ticket))

            forecast_rows.append(
                cls._make_row(target_date, predicted_bookings, projected_income, rain_mm, "shop_model")
            )

        return forecast_rows

    # ─────────────────────────────────────────────────────────────────────
    # TIER 2 — POOLED MODEL
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def _forecast_from_pooled_model(cls, context: Dict[str, Any], baselines: Dict[str, float], days: int) -> list:
        with cls.POOLED_MODEL_PATH.open("rb") as model_file:
            artifact = pickle.load(model_file)

        model = artifact["model"]
        feature_columns = artifact["feature_columns"]
        # Walang "target" = lumang artifact na revenue_ratio ang hinuhulaan.
        target = artifact.get("target", "revenue_ratio")
        rain_by_date = cls._rain_lookup(context["latitude"], context["longitude"], days)

        today = cls._manila_now()
        forecast_rows = []
        for offset in range(1, days + 1):
            target_date = today + timedelta(days=offset)
            day_of_week = target_date.weekday()
            rain_mm = rain_by_date.get(target_date.date(), 0.0)

            feature_map = {
                "day_of_week": day_of_week,
                "is_weekend": 1 if day_of_week in (5, 6) else 0,
                "rain_mm": rain_mm,
            }
            features = [[feature_map[column] for column in feature_columns]]
            ratio = max(float(model.predict(features)[0]), 0.0)

            if target == "booking_ratio":
                predicted_bookings = max(0, round(ratio * baselines["bookings"]))
                projected_income = predicted_bookings * baselines["ticket"]
            else:
                projected_income = ratio * baselines["revenue"]
                predicted_bookings = max(0, round(projected_income / baselines["ticket"]))

            forecast_rows.append(
                cls._make_row(target_date, predicted_bookings, projected_income, rain_mm, "pooled_model")
            )

        return forecast_rows

    # ─────────────────────────────────────────────────────────────────────
    # TIER 3 — WEATHER-ONLY OUTLOOK
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def _forecast_weather_only(cls, context: Dict[str, Any], days: int) -> list:
        rain_by_date = cls._rain_lookup(context["latitude"], context["longitude"], days)

        today = cls._manila_now()
        forecast_rows = []
        for offset in range(1, days + 1):
            target_date = today + timedelta(days=offset)
            rain_mm = rain_by_date.get(target_date.date(), 0.0)
            forecast_rows.append(
                cls._make_row(target_date, None, None, rain_mm, "weather_only")
            )

        return forecast_rows

    # ─────────────────────────────────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def get_revenue_forecast(cls, shop_id: int, days: int = 7) -> list[Dict[str, Any]]:
        """
        Resolves the 7-day forecast for a specific shop through the
        3-tier fallback described in the class docstring.
        """
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            context = cls._get_shop_context(db, shop_id)
            shop_path = cls.MODEL_DIR / f"forecast_shop_{shop_id}.pkl"

            if shop_path.exists() and shop_path.stat().st_size > 0:
                return cls._forecast_from_shop_model(shop_path, context, days)

            if cls.POOLED_MODEL_PATH.exists() and cls.POOLED_MODEL_PATH.stat().st_size > 0:
                baselines = cls._get_shop_baselines(db, shop_id, context["average_ticket"])
                return cls._forecast_from_pooled_model(context, baselines, days)

            return cls._forecast_weather_only(context, days)
        finally:
            db.close()

    @classmethod
    def calculate_forecast_accuracy(cls) -> Dict[str, Any]:
        """Reads the dynamic accuracy metrics generated by the training pipeline."""
        if cls.METRICS_PATH.exists():
            with open(cls.METRICS_PATH, "r") as f:
                return json.load(f)

        return {
            "accuracy_percentage": 0.0,
            "mean_absolute_error": 0.0,
            "r2_score": 0.0
        }

    @classmethod
    def _get_shop_rates(cls, db, shop_id: int) -> Dict[str, float]:
        """
        Looks up THIS shop's own configured rates from Optimization
        Settings, instead of the hardcoded class constants. Falls back
        to the class constants only if the shop has no Setting row yet.

        NOTE: hindi ko ginalaw ang bahaging ito. Kung may AttributeError
        tungkol sa 'supplies_cost_per_load', i-check kung ano talaga ang
        pangalan ng column sa app/models.py (Setting) — ang lumang
        docstring ay nagsabing 'detergent_cost_per_load'.
        """
        from app.models import Setting
        settings = db.query(Setting).filter(Setting.shop_id == shop_id).first()
        if not settings:
            return {
                "electricity_rate": cls.ELEC_RATE_KWH,
                "water_rate": cls.WATER_RATE_CUM,
                "supplies_cost_per_load": cls.DETERGENT_FIXED,
            }
        return {
            "electricity_rate": settings.electricity_rate if settings.electricity_rate is not None else cls.ELEC_RATE_KWH,
            "water_rate": settings.water_rate if settings.water_rate is not None else cls.WATER_RATE_CUM,
            "supplies_cost_per_load": settings.supplies_cost_per_load if settings.supplies_cost_per_load is not None else cls.DETERGENT_FIXED,
        }

    @classmethod
    def calculate_cycle_cost(cls, db, shop_id: int, machine_type: str, duration_minutes: int) -> Dict[str, float]:
        """
        Calculates utility consumption based on duration and THIS SHOP'S
        OWN configured rates.
        Electricity = (Watts * Hours / 1000) * Rate.
        """
        rates = cls._get_shop_rates(db, shop_id)
        m_type = machine_type.lower().strip()
        hours = duration_minutes / 60

        # 1. Electricity
        watts = cls.WATTS_WASHER if m_type == "washer" else cls.WATTS_DRYER
        elec_consumed = (watts * hours) / 1000
        elec_cost = elec_consumed * rates["electricity_rate"]

        # 2. Water (washers only): ~50L (0.05 m³) per cycle
        water_cost = 0.0
        if m_type == "washer":
            water_cost = 0.05 * rates["water_rate"]

        # 3. Supplies (washers only) — formerly "Detergent"
        supplies_cost = rates["supplies_cost_per_load"] if m_type == "washer" else 0.0

        return {
            "electricity": round(elec_cost, 2),
            "water": round(water_cost, 2),
            "detergent": round(supplies_cost, 2),
            "total": round(elec_cost + water_cost + supplies_cost, 2)
        }

    @classmethod
    def get_overhead(cls, db, shop_id: int, machine_type: str) -> Dict[str, float]:
        """Standard cost breakdown per cycle for a machine type, using THIS shop's rates."""
        m_type = machine_type.lower().strip()
        duration = cls.MACHINE_DURATIONS.get(m_type, 45)
        costs = cls.calculate_cycle_cost(db, shop_id, m_type, duration)

        return {
            "electricity_cost": costs["electricity"],
            "water_cost": costs["water"],
            "detergent_cost": costs["detergent"],
            "total_overhead": costs["total"]
        }

    @classmethod
    def get_machine_runtime(cls, machine_type: str, service_type: str) -> int:
        """
        Determines hardware runtime based on the intensity of the service.
        """
        m_type = machine_type.lower().strip()
        s_type = (service_type or "").lower().strip()

        if any(keyword in s_type for keyword in ["comforter", "titan", "heavy", "bulk"]):
            return 60 if m_type == "washer" else 50

        return cls.MACHINE_DURATIONS.get(m_type, 45)

    @classmethod
    def calculate_metrics(cls, machine: Any, is_busy: bool = False) -> Dict[str, Any]:
        """
        Aggregates financial and operational data for the Dashboard.
        """
        acc_elec = getattr(machine, "accumulated_electricity", 0.0) or 0.0
        acc_water = getattr(machine, "accumulated_water", 0.0) or 0.0
        acc_detergent = getattr(machine, "accumulated_detergent", 0.0) or 0.0

        total_overhead = acc_elec + acc_water + acc_detergent
        accumulated_net = getattr(machine, "net_profit_accumulated", 0.0) or 0.0

        total_revenue = accumulated_net + total_overhead
        if total_revenue > 0:
            profit_margin = (accumulated_net / total_revenue) * 100
            profitability_rate = max(0.0, min(100.0, profit_margin))
        else:
            profitability_rate = 0.0

        service_type = getattr(machine, "current_service_type", "") or ""
        duration = cls.get_machine_runtime(machine.machine_type, service_type) if is_busy else 0

        return {
            "duration_minutes":    duration,
            "profitability_rate":  round(profitability_rate, 2),
            "net_profit":          round(accumulated_net, 2),
            "electricity_cost":    round(acc_elec, 2),
            "water_cost":          round(acc_water, 2),
            "detergent_cost":      round(acc_detergent, 2),
            "total_overhead":      round(total_overhead, 2)
        }

    @classmethod
    def calculate_utility_accuracy(cls) -> Dict[str, Any]:
        """Kept for compatibility with legacy components."""
        return cls.calculate_forecast_accuracy()