from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Dict, Any, List
from pathlib import Path
import json

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
    def get_operational_insights(db: Session):
        return insight_engine.generate_operational_insight(db)

    # ─────────────────────────────────────────────────────────────────────────
    # DASHBOARD SUMMARY
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_dashboard_summary(db: Session, shop_id: int = 1):
        """
        Calculates aggregate summary statistics including current performance
        (reset based on operational hours), weekly totals, and expenses.
        """
        # 1. Fetch Operational Settings for Auto-Reset Logic
        settings = db.query(models.Setting).filter(
            models.Setting.shop_id == shop_id
        ).first()

        op_start_hour = settings.operation_start_hour if settings else 8

        now = datetime.now()
        today_reset_time = now.replace(
            hour=op_start_hour, minute=0, second=0, microsecond=0
        )

        # If current time is before the reset time, roll back to yesterday's reset
        if now < today_reset_time:
            today_reset_time -= timedelta(days=1)

        # 2. Fetch "Today" Revenue (since operation start)
        today_stats = db.query(
            func.sum(models.Booking.total_price).label("revenue"),
            func.count(models.Booking.id).label("bookings")
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.created_at >= today_reset_time
        ).first()

        # 3. Fetch Weekly Summary (last 7 days)
        seven_days_ago = now - timedelta(days=7)
        weekly_stats = db.query(
            func.sum(models.Booking.total_price).label("revenue")
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.created_at >= seven_days_ago
        ).first()

        # 4. Calculate Expenses
        total_revenue_weekly  = weekly_stats.revenue or 0.0
        total_expenses_weekly = total_revenue_weekly * 0.35  # 35% operational cost estimate

        # Previous week comparison
        last_week_start = now - timedelta(days=14)
        last_week_end   = now - timedelta(days=8)
        last_week_stats = db.query(
            func.sum(models.Booking.total_price).label("revenue"),
            func.count(models.Booking.id).label("bookings")
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.created_at >= last_week_start,
            models.Booking.created_at <= last_week_end
        ).first()

        # 5. Aggregate Service Volumes
        service_counts = db.query(
            models.Booking.service_type,
            func.count(models.Booking.id).label("total")
        ).filter(
            models.Booking.shop_id == shop_id
        ).group_by(models.Booking.service_type).all()

        service_map = {item.service_type: item.total for item in service_counts}

        # 6. Total Weight Volume (kg)
        total_kg = db.query(
            func.sum(models.Booking.weight)
        ).filter(models.Booking.shop_id == shop_id).scalar() or 0.0

        # 7. Average Revenue Per Service (all-time)
        total_rev_all_time = db.query(
            func.sum(models.Booking.total_price)
        ).filter(models.Booking.shop_id == shop_id).scalar() or 0.0

        total_bookings_all_time = db.query(
            func.count(models.Booking.id)
        ).filter(models.Booking.shop_id == shop_id).scalar() or 0

        avg_per_service = (
            total_rev_all_time / total_bookings_all_time
            if total_bookings_all_time > 0 else 0
        )

        # 8. AI Engine Data
        ai = AIEngine()
        predicted_count_today  = ai.get_predicted_bookings(datetime.now())
        projected_income_today = ai.calculate_projected_income(predicted_count_today)

        active_machines = db.query(models.Machine).filter(
            models.Machine.shop_id == shop_id,
            models.Machine.status == "Busy"
        ).count()

        return {
            "today_revenue":            round(float(today_stats.revenue or 0.0), 2),
            "weekly_revenue":           round(float(total_revenue_weekly), 2),
            "weekly_expenses":          round(float(total_expenses_weekly), 2),
            "last_week_revenue":        round(float(last_week_stats.revenue or 0.0), 2),
            "total_bookings":           today_stats.bookings or 0,
            "last_week_bookings":       last_week_stats.bookings or 0,
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
    def get_weekly_history(db: Session, shop_id: int = 1):
        """
        Provides historical income data for the last 7 days.
        """
        history_data = []
        for i in range(6, -1, -1):
            target_date   = datetime.now().date() - timedelta(days=i)
            actual_income = db.query(
                func.sum(models.Booking.total_price)
            ).filter(
                models.Booking.shop_id == shop_id,
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
    def get_forecast_data(db: Session, shop_id: int = 1):
        raw_forecast = PredictionService.get_revenue_forecast(days=7)
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
    def get_service_distribution(db: Session, shop_id: int = 1):
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
    def get_ai_prediction_metrics(db: Session) -> Dict[str, Any]:
        """
        Retrieves real-time accuracy metrics from the dynamic model_metrics.json file.
        """
        metrics_path = PredictionService.METRICS_PATH
        if not metrics_path.exists():
            return {"status": "error", "message": "Metrics configuration not found"}

        with open(metrics_path, "r") as f:
            data = json.load(f)

        return {
            "status":                   "success",
            "demand_forecasting_model": data.get("accuracy_percentage", 0.0),
            "utility_telemetry_model":  data.get("r2_score", 0.0) * 100
        }

    # ─────────────────────────────────────────────────────────────────────────
    # CUSTOMER SEGMENTS  (Phase 3: 18-day window + mock data exclusion)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_customer_segments(db: Session, shop_id: int = 1) -> List[dict]:
        """
        Returns a list of customer objects, each annotated with a behavioral
        segment assigned by the K-Means cluster engine.

        Phase 3 behaviour:
            - Delegates to AnalyticsService.get_customer_segments() which
              applies an 18-day rolling window and mock data exclusion before
              passing data to the cluster engine.
            - The 404 message now explicitly mentions the 18-day window so
              operators understand why they might see no data.

        Returns:
            List[dict] — each item contains:
                - customer_name   (str)
                - visit_frequency (int)
                - total_spent     (float)
                - avg_per_visit   (float)
                - segment         (str)   "Occasional" | "Regular" | "VIP"
                - segment_color   (str)   Tailwind color token for the badge
                - data_window     (str)   ISO start date of the 18-day window

        Raises:
            HTTPException 404 — no real bookings in the last 18 days.
            HTTPException 422 — input data is malformed or missing columns.
            HTTPException 500 — unexpected ML or database error.
        """
        # Deferred import to avoid circular dependency between controller and service
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
                        f"{SEGMENTATION_WINDOW_DAYS} days. "
                        "Add bookings or wait for recent data to generate segments."
                    )
                )

            return segments

        except HTTPException:
            # Re-raise FastAPI HTTP exceptions unchanged
            raise
        except ValueError as ve:
            # Raised by cluster_engine when the DataFrame is malformed
            raise HTTPException(
                status_code=422,
                detail=f"Segmentation data error: {str(ve)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Customer segmentation failed: {str(e)}"
            )