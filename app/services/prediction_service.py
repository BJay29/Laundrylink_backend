import numpy as np
from typing import Dict, Any, Optional
import pickle
import json 
import os 
from datetime import datetime, timedelta
from pathlib import Path
# Import the training logic from your ml_engine
from ml_engine.train import run_training_pipeline, run_pooled_training_pipeline
from app.services import weather_service

class PredictionService:
    """
    Core logic for calculating utility consumption and machine profitability,
    plus the 7-day revenue/booking forecast used by the Financial Forecast page.

    UPDATED: get_revenue_forecast() now resolves per shop using a 3-tier
    fallback instead of always loading one single global forecast.pkl:

        Tier 1 — Shop's own model (forecast_shop_{shop_id}.pkl):
            best accuracy, trained on this shop's own history + its own
            location's real historical weather. Used once a shop has
            trained at least once (needs 14+ days of its own data).

        Tier 2 — Pooled model (forecast_pooled.pkl):
            used when the shop has no model of its own yet. Predicts a
            revenue RATIO (vs. a normal day) from weekday + rain, then
            scales that ratio by the shop's own average daily revenue
            if it has any bookings at all, or a literature-informed
            baseline booking count (see _get_shop_baseline_revenue) if
            it has none.

        Tier 3 — Weather-only outlook:
            used only when the pooled model itself doesn't exist yet
            (the whole platform is too new to have any shop cross the
            pooling threshold). Returns real forecasted rainfall per
            day with predicted_bookings/projected_income left as None,
            so the frontend can show an honest "insufficient data" state
            instead of a fabricated number.

    Every row in the response now carries "model_tier" so the frontend
    can show which tier produced it (see the dashboard badge design).
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

    # Assumed daily bookings for a shop with ZERO history, used only to
    # turn the pooled model's ratio prediction into a currency estimate
    # when there's nothing else to scale against. Matches AIEngine's own
    # WEEKDAY_BASE constant (app/services/ai_engine.py) so the two
    # forecasting systems in this codebase don't quietly disagree on
    # what "a normal new shop's day" looks like.
    ASSUMED_NEW_SHOP_DAILY_BOOKINGS = 12

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
        NEW — triggers training of the pooled/cold-start model across
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
        ServiceType catalog, so a new shop's income projection uses ITS
        OWN prices, not a system-wide guess, even before it has bookings).
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
            average_ticket = 150.0  # matches the historical system-wide default

        return {
            "latitude": shop.latitude if shop else None,
            "longitude": shop.longitude if shop else None,
            "average_ticket": max(float(average_ticket), 1.0),
        }

    @classmethod
    def _get_shop_baseline_revenue(cls, db, shop_id: int, average_ticket: float) -> float:
        """
        Baseline daily revenue used to scale the pooled model's ratio
        prediction into currency. Prefers the shop's OWN historical
        average if it has any bookings at all (self-calibrating even
        with sparse data); falls back to average_ticket * an assumed
        baseline booking count only for a shop with truly zero history.
        """
        from sqlalchemy import func
        from app.models import Booking

        rows = (
            db.query(
                func.date(Booking.created_at).label("d"),
                func.sum(Booking.total_price).label("rev"),
            )
            .filter(Booking.shop_id == shop_id)
            .group_by(func.date(Booking.created_at))
            .all()
        )
        if rows:
            return sum(float(r.rev or 0.0) for r in rows) / len(rows)

        return average_ticket * cls.ASSUMED_NEW_SHOP_DAILY_BOOKINGS

    @classmethod
    def _rain_lookup(cls, latitude: Optional[float], longitude: Optional[float], days: int) -> Dict[Any, float]:
        rain_frame = weather_service.get_forecast_rain_mm(latitude, longitude, days=days)
        if rain_frame.empty:
            return {}
        return {row.booking_date.date(): float(row.rain_mm) for row in rain_frame.itertuples()}

    # ─────────────────────────────────────────────────────────────────────
    # TIER 1 — SHOP'S OWN MODEL
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def _forecast_from_shop_model(cls, model_path: Path, context: Dict[str, Any], days: int) -> list:
        with model_path.open("rb") as model_file:
            artifact = pickle.load(model_file)

        model = artifact["model"]
        feature_columns = artifact["feature_columns"]
        average_ticket = max(float(artifact.get("average_ticket", context["average_ticket"])), 1.0)
        average_loads_per_booking = max(float(artifact.get("average_loads_per_booking", 1.0)), 1.0)
        last_day_index = int(artifact.get("last_day_index", 0))

        rain_by_date = cls._rain_lookup(context["latitude"], context["longitude"], days)

        today = datetime.now()
        forecast_rows = []
        for offset in range(1, days + 1):
            target_date = today + timedelta(days=offset)
            day_of_week = target_date.weekday()
            historical_day_index = last_day_index + offset
            estimated_bookings = 18 if day_of_week in (5, 6) else 12
            estimated_loads = max(1, round(estimated_bookings * average_loads_per_booking))
            rain_mm = rain_by_date.get(target_date.date(), 0.0)

            feature_map = {
                "day_index": historical_day_index,
                "day_of_week": day_of_week,
                "is_weekend": 1 if day_of_week in (5, 6) else 0,
                "booking_count": estimated_bookings,
                "total_loads": estimated_loads,
                "rain_mm": rain_mm,
            }
            features = [[feature_map[column] for column in feature_columns]]
            projected_income = max(float(model.predict(features)[0]), 0.0)
            predicted_bookings = max(0, round(projected_income / average_ticket))

            forecast_rows.append({
                "date": target_date.strftime("%Y-%m-%d"),
                "label": target_date.strftime("%b %d, %a"),
                "predicted_bookings": predicted_bookings,
                "projected_income": round(projected_income, 2),
                "rain_mm": round(rain_mm, 1),
                "is_peak": day_of_week in (0, 4, 5, 6),
                "model_tier": "shop_model",
            })

        return forecast_rows

    # ─────────────────────────────────────────────────────────────────────
    # TIER 2 — POOLED MODEL
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def _forecast_from_pooled_model(cls, context: Dict[str, Any], baseline_revenue: float, days: int) -> list:
        with cls.POOLED_MODEL_PATH.open("rb") as model_file:
            artifact = pickle.load(model_file)

        model = artifact["model"]
        feature_columns = artifact["feature_columns"]
        rain_by_date = cls._rain_lookup(context["latitude"], context["longitude"], days)

        today = datetime.now()
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
            revenue_ratio = max(float(model.predict(features)[0]), 0.0)
            projected_income = revenue_ratio * baseline_revenue
            predicted_bookings = max(0, round(projected_income / context["average_ticket"]))

            forecast_rows.append({
                "date": target_date.strftime("%Y-%m-%d"),
                "label": target_date.strftime("%b %d, %a"),
                "predicted_bookings": predicted_bookings,
                "projected_income": round(projected_income, 2),
                "rain_mm": round(rain_mm, 1),
                "is_peak": day_of_week in (0, 4, 5, 6),
                "model_tier": "pooled_model",
            })

        return forecast_rows

    # ─────────────────────────────────────────────────────────────────────
    # TIER 3 — WEATHER-ONLY OUTLOOK
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def _forecast_weather_only(cls, context: Dict[str, Any], days: int) -> list:
        rain_by_date = cls._rain_lookup(context["latitude"], context["longitude"], days)

        today = datetime.now()
        forecast_rows = []
        for offset in range(1, days + 1):
            target_date = today + timedelta(days=offset)
            rain_mm = rain_by_date.get(target_date.date(), 0.0)

            forecast_rows.append({
                "date": target_date.strftime("%Y-%m-%d"),
                "label": target_date.strftime("%b %d, %a"),
                "predicted_bookings": None,
                "projected_income": None,
                "rain_mm": round(rain_mm, 1),
                "is_peak": target_date.weekday() in (0, 4, 5, 6),
                "model_tier": "weather_only",
            })

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
                baseline_revenue = cls._get_shop_baseline_revenue(db, shop_id, context["average_ticket"])
                return cls._forecast_from_pooled_model(context, baseline_revenue, days)

            return cls._forecast_weather_only(context, days)
        finally:
            db.close()

    @classmethod
    def calculate_forecast_accuracy(cls) -> Dict[str, Any]:
        """
        Reads the dynamic accuracy metrics generated by the training pipeline.
        """
        if cls.METRICS_PATH.exists():
            with open(cls.METRICS_PATH, "r") as f:
                return json.load(f)
        
        # Fallback if metrics file has not been generated yet
        return {
            "accuracy_percentage": 0.0,
            "mean_absolute_error": 0.0,
            "r2_score": 0.0
        }

    @classmethod
    def calculate_cycle_cost(cls, machine_type: str, duration_minutes: int) -> Dict[str, float]:
        """
        Calculates utility consumption based on duration and Naga City rates.
        Electricity is calculated as: (Watts * Hours / 1000) * Rate.
        """
        m_type = machine_type.lower().strip()
        hours = duration_minutes / 60
        
        # 1. Electricity Calculation
        watts = cls.WATTS_WASHER if m_type == "washer" else cls.WATTS_DRYER
        elec_consumed = (watts * hours) / 1000
        elec_cost = elec_consumed * cls.ELEC_RATE_KWH

        # 2. Water Calculation (Washers only)
        # Based on average 50L consumption (0.05 cubic meters) per wash cycle
        water_cost = 0.0
        if m_type == "washer":
            water_cost = 0.05 * cls.WATER_RATE_CUM

        # 3. Detergent Calculation (Washers only)
        detergent_cost = cls.DETERGENT_FIXED if m_type == "washer" else 0.0

        return {
            "electricity": round(elec_cost, 2),
            "water": round(water_cost, 2),
            "detergent": detergent_cost,
            "total": round(elec_cost + water_cost + detergent_cost, 2)
        }

    @classmethod
    def get_overhead(cls, machine_type: str) -> Dict[str, float]:
        """
        Helper method used by controllers to get the standard cost breakdown
        per cycle for a specific machine type.
        """
        m_type = machine_type.lower().strip()
        duration = cls.MACHINE_DURATIONS.get(m_type, 45)
        costs = cls.calculate_cycle_cost(m_type, duration)
        
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
        Heavy loads like 'Comforters' increase duration, resulting in higher utility costs.
        """
        m_type = machine_type.lower().strip()
        s_type = (service_type or "").lower().strip()

        # Intensive services require longer runtimes
        if any(keyword in s_type for keyword in ["comforter", "titan", "heavy", "bulk"]):
            return 60 if m_type == "washer" else 50
        
        return cls.MACHINE_DURATIONS.get(m_type, 45)

    @classmethod
    def calculate_metrics(cls, machine: Any, is_busy: bool = False) -> Dict[str, Any]:
        """
        Aggregates financial and operational data for the Dashboard.
        Uses accumulated values from the database to reflect lifetime machine performance.
        """
        acc_elec = getattr(machine, "accumulated_electricity", 0.0) or 0.0
        acc_water = getattr(machine, "accumulated_water", 0.0) or 0.0
        acc_detergent = getattr(machine, "accumulated_detergent", 0.0) or 0.0
        
        total_overhead = acc_elec + acc_water + acc_detergent
        accumulated_net = getattr(machine, "net_profit_accumulated", 0.0) or 0.0

        # --- PROFITABILITY RATIO ---
        total_revenue = accumulated_net + total_overhead
        if total_revenue > 0:
            profit_margin = (accumulated_net / total_revenue) * 100
            profitability_rate = max(0.0, min(100.0, profit_margin))
        else:
            profitability_rate = 0.0

        # --- REAL-TIME TELEMETRY ---
        service_type = getattr(machine, "current_service_type", "") or ""
        duration = cls.get_machine_runtime(machine.machine_type, service_type) if is_busy else 0

        return {
            "duration_minutes":    duration,
            "profitability_rate":    round(profitability_rate, 2),
            "net_profit":            round(accumulated_net, 2),
            "electricity_cost":      round(acc_elec, 2),
            "water_cost":            round(acc_water, 2),
            "detergent_cost":        round(acc_detergent, 2),
            "total_overhead":        round(total_overhead, 2)
        }

    @classmethod
    def calculate_utility_accuracy(cls) -> Dict[str, Any]:
        """
        Reads the dynamic utility telemetry accuracy metrics from the configuration file.
        """
        # Kept for compatibility with legacy components
        return cls.calculate_forecast_accuracy()