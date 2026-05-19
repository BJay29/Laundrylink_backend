from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Dict, Any
from app import models
from app.services.ai_engine import AIEngine
from app.services.prediction_service import PredictionService
from app.services import insight_engine 

class AnalyticsController:
    """
    Handles the logic for data aggregation, comparison, and AI-driven forecasting.
    Includes Decision Support System (DSS) logic via Operational Insights.
    """

    @staticmethod
    def get_operational_insights(db: Session):
        """
        Fetches live operational insights regarding machine status, 
        profit impact, and strategic suggestions.
        """
        # Calls the logic from app/services/insight_engine.py
        return insight_engine.generate_operational_insight(db)

    @staticmethod
    def get_dashboard_summary(db: Session, shop_id: int = 1):
        """
        Calculates summary statistics for dashboard cards and service breakdowns.
        Replaces 'accuracy_rate' with 'avg_per_service' for the Overview Dashboard.
        """
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        # 1. Fetch Actual Income for Today
        today_revenue = db.query(func.sum(models.Booking.total_price)).filter(
            models.Booking.shop_id == shop_id,
            func.date(models.Booking.created_at) == today
        ).scalar() or 0.0

        # 2. Fetch Actual Income for Yesterday
        yesterday_revenue = db.query(func.sum(models.Booking.total_price)).filter(
            models.Booking.shop_id == shop_id,
            func.date(models.Booking.created_at) == yesterday
        ).scalar() or 0.0

        # 3. Calculate Income Growth Percentage
        income_growth = 0.0
        if yesterday_revenue > 0:
            income_growth = ((today_revenue - yesterday_revenue) / yesterday_revenue) * 100

        # 4. Aggregate Actual Service Volumes (Total Count per Type)
        service_counts = db.query(
            models.Booking.service_type, 
            func.count(models.Booking.id).label("total")
        ).filter(models.Booking.shop_id == shop_id).group_by(models.Booking.service_type).all()
        
        service_map = {item.service_type: item.total for item in service_counts}

        # 5. Calculate Average Income Per Service (Global Average)
        total_stats = db.query(
            func.sum(models.Booking.total_price).label("revenue"),
            func.count(models.Booking.id).label("count")
        ).filter(models.Booking.shop_id == shop_id).first()

        total_revenue = float(total_stats.revenue or 0.0)
        total_bookings = int(total_stats.count or 0)
        avg_per_service = round(total_revenue / total_bookings, 2) if total_bookings > 0 else 0.0

        # 6. Calculate Total Actual Weight (kg)
        total_kg = db.query(func.sum(models.Booking.weight)).filter(
            models.Booking.shop_id == shop_id
        ).scalar() or 0.0

        # 7. Get Predicted Data from AI Engine
        ai = AIEngine()
        predicted_count_today = ai.get_predicted_bookings(datetime.now())
        projected_income_today = ai.calculate_projected_income(predicted_count_today)

        # 8. Fetch Total Active Machines (Busy status)
        active_machines = db.query(models.Machine).filter(
            models.Machine.shop_id == shop_id,
            models.Machine.status == "Busy"
        ).count()

        return {
            "today_revenue": round(today_revenue, 2),
            "income_growth": round(income_growth, 2),
            "active_machines": active_machines,
            "predicted_bookings_today": predicted_count_today,
            "projected_income_today": projected_income_today,
            "avg_per_service": avg_per_service,
            "full_service": service_map.get("Full Service", 0),
            "titan_wash": service_map.get("Titan Wash", 0),
            "regular_wash": service_map.get("Regular Wash", 0),
            "comforter": service_map.get("Comforter", 0),
            "total_kg": round(total_kg, 2)
        }

    @staticmethod
    def get_forecast_data(db: Session, shop_id: int = 1):
        """
        Generates the 7-day forecast data for the frontend chart.
        Includes historical trend analysis for visual comparison.
        """
        ai = AIEngine()
        raw_forecast = ai.get_weekly_forecast(is_rainy_forecast=False)

        history_data = []
        for i in range(6, -1, -1):
            target_date = datetime.now().date() - timedelta(days=i)
            actual_income = db.query(func.sum(models.Booking.total_price)).filter(
                models.Booking.shop_id == shop_id,
                func.date(models.Booking.created_at) == target_date
            ).scalar() or 0.0
            
            history_data.append({
                "label": target_date.strftime("%b %d"),
                "actual_income": round(actual_income, 2)
            })

        return {
            "forecast": raw_forecast,
            "history": history_data
        }

    @staticmethod
    def get_service_distribution(db: Session, shop_id: int = 1):
        """
        Returns a distribution map of all services to analyze business trends.
        """
        distribution = db.query(
            models.Booking.service_type, 
            func.count(models.Booking.id).label("count")
        ).filter(models.Booking.shop_id == shop_id).group_by(models.Booking.service_type).all()

        return {item.service_type: item.count for item in distribution}

    @staticmethod
    def get_ai_prediction_metrics() -> Dict[str, Any]:
        """
        Aggregates operational accuracy parameters, math evaluation bounds, 
        and hardware consumption calibration scores for front-end analytics dashboard ingestion.
        """
        ai = AIEngine()
        # Evaluate historical stochastic variance checks
        demand_metrics = ai.calculate_model_accuracy()
        
        # Evaluate baseline mathematical hardware equation coefficients
        utility_metrics = PredictionService.calculate_utility_accuracy()
        
        return {
            "status": "success",
            "demand_forecasting_model": demand_metrics,
            "utility_telemetry_model": utility_metrics
        }