from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
import json
import pickle

from app import models
from app.services.ai_engine import AIEngine
from app.services.prediction_service import PredictionService
from app.services import insight_engine


class AnalyticsController:
    """
    Handles the core operational logic for data aggregation, data comparison,
    and AI-driven forecasting analytics. Includes a Decision Support System (DSS)
    engine pipeline via Operational Insights.
    """

    # ─────────────────────────────────────────────────────────────────────────
    # OPERATIONAL INSIGHTS (DSS)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_operational_insights(db: Session, shop_id: int):
        """
        NEEDS VERIFICATION: insight_engine.generate_operational_insight()
        must accept and filter by shop_id.
        """
        return insight_engine.generate_operational_insight(db, shop_id)

    # ─────────────────────────────────────────────────────────────────────────
    # DASHBOARD SUMMARY
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_dashboard_summary(db: Session, shop_id: int):
        """
        Calculates aggregate summary statistics including current performance
        (reset based on operational hours), weekly totals, and expenses.

        Income = paid only; bookings count = all bookings (operational volume).
        """
        settings = db.query(models.Setting).filter(
            models.Setting.shop_id == shop_id
        ).first()

        op_start_hour = settings.operation_start_hour if settings else 8

        now = datetime.now()
        today_reset_time = now.replace(
            hour=op_start_hour, minute=0, second=0, microsecond=0
        )

        if now < today_reset_time:
            today_reset_time -= timedelta(days=1)

        today_revenue = db.query(
            func.sum(models.Booking.total_price)
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.payment_status == "paid",
            models.Booking.created_at >= today_reset_time
        ).scalar() or 0.0

        today_bookings_count = db.query(
            func.count(models.Booking.id)
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.created_at >= today_reset_time
        ).scalar() or 0

        seven_days_ago = now - timedelta(days=7)
        weekly_revenue = db.query(
            func.sum(models.Booking.total_price)
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.payment_status == "paid",
            models.Booking.created_at >= seven_days_ago
        ).scalar() or 0.0

        total_revenue_weekly  = weekly_revenue
        total_expenses_weekly = total_revenue_weekly * 0.35  # 35% operational cost estimate

        last_week_start = now - timedelta(days=14)
        last_week_end   = now - timedelta(days=8)
        last_week_revenue = db.query(
            func.sum(models.Booking.total_price)
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.payment_status == "paid",
            models.Booking.created_at >= last_week_start,
            models.Booking.created_at <= last_week_end
        ).scalar() or 0.0

        last_week_bookings_count = db.query(
            func.count(models.Booking.id)
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.created_at >= last_week_start,
            models.Booking.created_at <= last_week_end
        ).scalar() or 0

        service_counts = db.query(
            models.Booking.service_type,
            func.count(models.Booking.id).label("total")
        ).filter(
            models.Booking.shop_id == shop_id
        ).group_by(models.Booking.service_type).all()

        service_map = {item.service_type: item.total for item in service_counts}

        total_kg = db.query(
            func.sum(models.Booking.weight)
        ).filter(models.Booking.shop_id == shop_id).scalar() or 0.0

        total_rev_all_time = db.query(
            func.sum(models.Booking.total_price)
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.payment_status == "paid"
        ).scalar() or 0.0

        total_paid_bookings_all_time = db.query(
            func.count(models.Booking.id)
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.payment_status == "paid"
        ).scalar() or 0

        avg_per_service = (
            total_rev_all_time / total_paid_bookings_all_time
            if total_paid_bookings_all_time > 0 else 0
        )

        ai = AIEngine()
        predicted_count_today  = ai.get_predicted_bookings(datetime.now())
        projected_income_today = ai.calculate_projected_income(predicted_count_today)

        active_machines = db.query(models.Machine).filter(
            models.Machine.shop_id == shop_id,
            models.Machine.status == "Busy"
        ).count()

        return {
            "today_revenue":            round(float(today_revenue), 2),
            "weekly_revenue":           round(float(total_revenue_weekly), 2),
            "weekly_expenses":          round(float(total_expenses_weekly), 2),
            "last_week_revenue":        round(float(last_week_revenue), 2),
            "total_bookings":           today_bookings_count,
            "last_week_bookings":       last_week_bookings_count,
            "active_machines":          active_machines,
            "predicted_bookings_today": predicted_count_today,
            "projected_income_today":   projected_income_today,
            "full_service":             service_map.get("Full Service", 0),
            "titan_wash":               service_map.get("Titan Wash",   0),
            "regular_wash":             service_map.get("Regular Wash", 0),
            "comforter":                service_map.get("Comforter",    0),
            "total_kg":                 round(float(total_kg), 2),
            "avg_per_service":          round(float(avg_per_service), 2),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # WEEKLY HISTORY
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_weekly_history(db: Session, shop_id: int):
        """Historical PAID income for the last 7 days."""
        history_data = []
        for i in range(6, -1, -1):
            target_date   = datetime.now().date() - timedelta(days=i)
            actual_income = db.query(
                func.sum(models.Booking.total_price)
            ).filter(
                models.Booking.shop_id == shop_id,
                models.Booking.payment_status == "paid",
                func.date(models.Booking.created_at) == target_date
            ).scalar() or 0.0

            history_data.append({
                "label":         target_date.strftime("%b %d"),
                "actual_income": round(float(actual_income), 2)
            })
        return history_data

    # ─────────────────────────────────────────────────────────────────────────
    # FORECAST DATA
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_forecast_data(db: Session, shop_id: int):
        """
        Resolves the 7-day forecast through the 3-tier fallback
        (shop model -> pooled model -> weather-only).
        """
        raw_forecast = PredictionService.get_revenue_forecast(shop_id=shop_id, days=7)
        ai_narrative = insight_engine.generate_forecast_insight(raw_forecast)

        return {
            "forecast":             raw_forecast,
            "history":              AnalyticsController.get_weekly_history(db, shop_id),
            "ai_generated_insight": ai_narrative
        }

    # ─────────────────────────────────────────────────────────────────────────
    # SERVICE DISTRIBUTION
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_service_distribution(db: Session, shop_id: int):
        distribution = db.query(
            models.Booking.service_type,
            func.count(models.Booking.id).label("count")
        ).filter(
            models.Booking.shop_id == shop_id
        ).group_by(models.Booking.service_type).all()

        return {item.service_type: item.count for item in distribution}

    # ─────────────────────────────────────────────────────────────────────────
    # AI PREDICTION METRICS
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_ai_prediction_metrics(db: Session, shop_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Retrieves accuracy metrics for the AI Calibration section.

        UPDATED (metrics fix):
          - Hindi na nagbabalik ng imposibleng numero. Ang R² ay
            naka-clamp sa 0..100 (dati r2 * 100, kaya -2901% kapag
            negatibo ang R²).
          - Kapag walang sariling model ang shop (o walang metrics),
            None ang ibinabalik (hindi 0), para maipakita ng UI ang
            "Not enough data yet" sa halip na 0%.
          - May "reliability" ("low"/"ok") at "beats_baseline" na
            ibinabalik para makita kung mapagkakatiwalaan ang numero.

        Mga key na ibinabalik:
          demand_forecasting_model: accuracy % (0..100) o None
          utility_telemetry_model:  model-fit (R² clamped 0..100) o None
                                    (pangalan ng key ay iniwan para sa
                                    compatibility sa frontend)
        """
        data: Optional[Dict[str, Any]] = None

        if shop_id is not None:
            shop_model_path = PredictionService.MODEL_DIR / f"forecast_shop_{shop_id}.pkl"
            if not shop_model_path.exists() or shop_model_path.stat().st_size == 0:
                return AnalyticsController._empty_metrics("No trained model for this shop yet")
            try:
                with shop_model_path.open("rb") as model_file:
                    artifact = pickle.load(model_file)
                data = artifact.get("metrics")
            except Exception as e:
                print(f"[{datetime.now()}] Could not read metrics for shop {shop_id}: {e}")
                return AnalyticsController._empty_metrics("Could not read model metrics")
            if not data:
                return AnalyticsController._empty_metrics("Model has no metrics recorded")
        else:
            metrics_path = PredictionService.METRICS_PATH
            if not metrics_path.exists():
                return AnalyticsController._empty_metrics("Metrics configuration not found")
            with open(metrics_path, "r") as f:
                data = json.load(f)

        accuracy = data.get("accuracy_percentage")
        r2 = data.get("r2_score")

        demand = None if accuracy is None else round(max(0.0, min(100.0, float(accuracy))), 2)
        model_fit = None if r2 is None else round(max(0.0, min(100.0, float(r2) * 100.0)), 2)

        return {
            "status":                   "success",
            "demand_forecasting_model": demand,
            "utility_telemetry_model":  model_fit,
            "reliability":              data.get("reliability", "unknown"),
            "beats_baseline":           data.get("beats_baseline"),
            "validation_days":          data.get("validation_days"),
        }

    @staticmethod
    def _empty_metrics(message: str) -> Dict[str, Any]:
        """Walang magagamit na metrics: None (hindi 0) para tapat ang UI."""
        return {
            "status":                   "error",
            "message":                  message,
            "demand_forecasting_model": None,
            "utility_telemetry_model":  None,
            "reliability":              "none",
            "beats_baseline":           None,
            "validation_days":          None,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # CUSTOMER SEGMENTS (18-day window + mock data exclusion)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_customer_segments(db: Session, shop_id: int) -> List[dict]:
        """
        Returns customers annotated with a K-Means behavioral segment.
        NOTE: verify AnalyticsService.get_customer_segments(shop_id)
        filters Booking by shop_id internally.
        """
        from app.services.analytics_service import AnalyticsService, SEGMENTATION_WINDOW_DAYS
        from fastapi import HTTPException

        try:
            service  = AnalyticsService(db)
            segments = service.get_customer_segments(shop_id)

            if not segments:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"No real booking records found in the last "
                        f"{SEGMENTATION_WINDOW_DAYS} days for this shop. "
                        "Add bookings or wait for recent data to generate segments."
                    )
                )

            return segments

        except HTTPException:
            raise
        except ValueError as ve:
            raise HTTPException(
                status_code=422,
                detail=f"Segmentation data error: {str(ve)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Customer segmentation failed: {str(e)}"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # SALES SUMMARY (Today / This Week / This Month)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_sales_summary(db: Session, shop_id: int):
        """Total PAID income for Today / This Week / This Month."""
        settings = db.query(models.Setting).filter(
            models.Setting.shop_id == shop_id
        ).first()

        op_start_hour = settings.operation_start_hour if settings else 8

        now = datetime.now()
        today_reset_time = now.replace(
            hour=op_start_hour, minute=0, second=0, microsecond=0
        )
        if now < today_reset_time:
            today_reset_time -= timedelta(days=1)

        week_start = now - timedelta(days=7)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        today_income = db.query(func.sum(models.Booking.total_price)).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.payment_status == "paid",
            models.Booking.created_at >= today_reset_time
        ).scalar() or 0.0

        week_income = db.query(func.sum(models.Booking.total_price)).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.payment_status == "paid",
            models.Booking.created_at >= week_start
        ).scalar() or 0.0

        month_income = db.query(func.sum(models.Booking.total_price)).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.payment_status == "paid",
            models.Booking.created_at >= month_start
        ).scalar() or 0.0

        return {
            "today_income": round(float(today_income), 2),
            "week_income": round(float(week_income), 2),
            "month_income": round(float(month_income), 2),
        }