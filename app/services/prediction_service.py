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
            location's real historical weather. Used once a shop has
            trained at least once (needs 14+ days of its own data).

        Tier 2 — Pooled model (forecast_pooled.pkl):
            used when the shop has no model of its own yet. Predicts a
            booking RATIO (vs. a normal day) from weekday + rain, then
            scales that ratio by the shop's own average daily bookings
            if it has any history, or an assumed baseline (see
            _get_shop_baselines) if it has none.

        Tier 3 — Weather-only outlook:
            used only when the pooled model itself doesn't exist yet.
            Returns real forecasted rainfall per day with
            predicted_bookings/projected_income left as None, so the
            frontend can show an honest "insufficient data" state
            instead of a fabricated number.

    Every row in the response carries "model_tier" so the frontend can
    show which tier produced it.

    UPDATED (weather-driven bookings forecast): ang model ay hinuhulaan
    na ang DAMI NG BOOKINGS (target = "booking_count" / "booking_ratio")
    mula sa trend, araw ng linggo, at forecast na ulan. Ang
    projected_income ay kinukuwenta na lang pagkatapos:

        projected_income = predicted_bookings x average_ticket

    Dati, ang model ay hinuhulaan ang kita at kailangan pa ng
    booking_count/total_loads bilang input — na hindi pa alam sa mga
    susunod na araw, kaya nilalagyan lang ng nakapirming 12 (weekday) /
    18 (weekend) at halos wala nang epekto ang ulan.

    BACKWARD COMPATIBILITY: ang mga lumang model file (walang "target"
    key sa artifact) ay patuloy pang gumagana sa lumang paraan hanggang
    sa mag-retrain — para hindi mawala ang charts habang hinihintay ang
    retraining.

    UPDATED (weather fix — rain_mm laging 0.0):
      1. Ang forecast loop ay nagsisimula sa bukas (offset 1) hanggang
         offset 7 (today + 7), pero ang Open-Meteo `forecast_days=7`
         ay nagbabalik lang ng today hanggang today + 6. Kaya humihingi
         na ng days + 1 na araw ang _rain_lookup().
      2. Ang petsa ay kinukuha gamit ang _manila_now() (UTC+8) para
         tumugma sa petsa ng weather data, anuman ang timezone ng server.
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

    # Philippines (UTC+8, walang DST) — tumutugma sa timezone="Asia/Manila"
    # na hinihingi natin sa Open-Meteo sa weather_service.py.
    MANILA_TZ = timezone(timedelta(hours=8))

    # Assumed daily bookings for a shop with ZERO history, used only to
    # turn the pooled model's ratio prediction into a booking count when
    # there's nothing else to scale against. Matches AIEngine's own
    # WEEKDAY_BASE constant (app/services/ai_engine.py) so the two
    # forecasting systems in this codebase don't quietly disagree on
    # what "a normal new shop's day" looks like.
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
        ServiceType catalog, so a new shop's income projection uses ITS
        OWN prices, not a system-wide guess, even before it has bookings).

        NOTE: kung NULL ang latitude/longitude ng shop, ipinapasa pa rin
        ang None dito — ang weather_service.py na ang nag-a-apply ng
        Naga City fallback (DEFAULT_LATITUDE/DEFAULT_LONGITUDE).
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
    def _get_shop_baselines(cls, db, shop_id: int, average_ticket: float) -> Dict[str, float]:
        """
        Baselines na ginagamit para i-scale ang pooled model's ratio
        prediction papunta sa totoong bilang:
          - "bookings": karaniwang bookings kada araw
          - "revenue":  karaniwang kita kada araw (para lang sa lumang
                        pooled artifacts na revenue_ratio pa ang target)
          - "ticket":   karaniwang halaga kada booking (revenue / bookings)

        Prefers the shop's OWN historical averages if it has any
        bookings at all; falls back to assumed values only for a shop
        with truly zero history.
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
        na araw simula BUKAS.

        Humihingi ng `days + 1` na araw sa Open-Meteo, dahil ang forecast
        loop ay tumatakbo mula bukas (offset 1) hanggang today + days —
        at ang `forecast_days=days` ay nagbabalik lang ng today hanggang
        today + (days - 1).
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

        rain_by_date = cls._rain_lookup(context["latitude"], context["longitude"], days)

        today = cls._manila_now()
        forecast_rows = []
        for offset in range(1, days + 1):
            target_date = today + timedelta(days=offset)
            day_of_week = target_date.weekday()
            is_weekend = 1 if day_of_week in (5, 6) else 0
            rain_mm = rain_by_date.get(target_date.date(), 0.0)

            # Para lang sa lumang artifacts na kailangan pa ng booking_count/
            # total_loads bilang input. Hindi ginagamit ng mga bagong model.
            legacy_bookings_guess = 18 if is_weekend else 12
            legacy_loads_guess = max(1, round(legacy_bookings_guess * average_loads_per_booking))

            feature_map = {
                "day_index": last_day_index + offset,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend,
                "rain_mm": rain_mm,
                "booking_count": legacy_bookings_guess,
                "total_loads": legacy_loads_guess,
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
    def _get_shop_rates(cls, db, shop_id: int) -> Dict[str, float]:
        """
        Looks up THIS shop's own configured rates from Optimization
        Settings, instead of the hardcoded class constants below (which
        were the actual bug: calculate_cycle_cost() ignored Setting
        entirely, so changing electricity_rate/water_rate/detergent_cost_per_load
        in the UI had zero effect on machine cost/profitability — those
        numbers were purely decorative). Falls back to the class
        constants only if the shop genuinely has no Setting row yet
        (shouldn't normally happen, but kept as a safety net so a
        missing row degrades gracefully instead of raising).

        FIXED: this previously read `settings.supplies_cost_per_load`,
        a rename that was never actually applied to the Setting model
        (app/models.py still defines the column as
        `detergent_cost_per_load`) — every call to get_overhead()
        (i.e. every booking creation / machine assignment) was raising
        AttributeError: 'Setting' object has no attribute
        'supplies_cost_per_load'. Reading the model's real attribute
        name here instead. The returned dict still uses the
        "supplies_cost_per_load" KEY (internal to this method and
        calculate_cycle_cost() below) — only the Setting attribute
        being read on the right-hand side changed.
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
        OWN configured rates (electricity_rate, water_rate,
        supplies_cost_per_load from Optimization Settings) — no longer
        the hardcoded Naga City class constants regardless of shop.
        Electricity is calculated as: (Watts * Hours / 1000) * Rate.
        """
        rates = cls._get_shop_rates(db, shop_id)
        m_type = machine_type.lower().strip()
        hours = duration_minutes / 60

        # 1. Electricity Calculation
        watts = cls.WATTS_WASHER if m_type == "washer" else cls.WATTS_DRYER
        elec_consumed = (watts * hours) / 1000
        elec_cost = elec_consumed * rates["electricity_rate"]

        # 2. Water Calculation (Washers only)
        # Based on average 50L consumption (0.05 cubic meters) per wash cycle
        water_cost = 0.0
        if m_type == "washer":
            water_cost = 0.05 * rates["water_rate"]

        # 3. Supplies Calculation (Washers only) — formerly "Detergent"
        supplies_cost = rates["supplies_cost_per_load"] if m_type == "washer" else 0.0

        return {
            "electricity": round(elec_cost, 2),
            "water": round(water_cost, 2),
            "detergent": round(supplies_cost, 2),  # dict key kept for now — see machine_controller.py note
            "total": round(elec_cost + water_cost + supplies_cost, 2)
        }

    @classmethod
    def get_overhead(cls, db, shop_id: int, machine_type: str) -> Dict[str, float]:
        """
        Helper method used by controllers to get the standard cost breakdown
        per cycle for a specific machine type, using THIS shop's own rates.
        """
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