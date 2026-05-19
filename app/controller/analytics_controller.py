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
    Handles the core operational logic for data aggregation, data comparison, 
    and AI-driven forecasting analytics. Includes a Decision Support System (DSS) 
    engine pipeline via Operational Insights.
    """

    @staticmethod
    def get_operational_insights(db: Session):
        return insight_engine.generate_operational_insight(db)

    @staticmethod
    def get_dashboard_summary(db: Session, shop_id: int = 1):
        """
        Calculates aggregate summary statistics including current performance 
        and historical comparison for trends.
        """
        today = datetime.now().date()
        # Define date ranges for comparison
        seven_days_ago = today - timedelta(days=7)
        last_week_start = today - timedelta(days=14)
        last_week_end = today - timedelta(days=8)

        # 1. Fetch Current Week Stats (Last 7 days)
        current_week_stats = db.query(
            func.sum(models.Booking.total_price).label("revenue"),
            func.count(models.Booking.id).label("bookings")
        ).filter(
            models.Booking.shop_id == shop_id,
            func.date(models.Booking.created_at) >= seven_days_ago
        ).first()

        # 2. Fetch Previous Week Stats (For comparison)
        last_week_stats = db.query(
            func.sum(models.Booking.total_price).label("revenue"),
            func.count(models.Booking.id).label("bookings")
        ).filter(
            models.Booking.shop_id == shop_id,
            func.date(models.Booking.created_at) >= last_week_start,
            func.date(models.Booking.created_at) <= last_week_end
        ).first()

        today_revenue = current_week_stats.revenue or 0.0
        last_week_revenue = last_week_stats.revenue or 0.0
        
        today_bookings = current_week_stats.bookings or 0
        last_week_bookings = last_week_stats.bookings or 0

        # 3. Aggregate Service Volumes
        service_counts = db.query(
            models.Booking.service_type, 
            func.count(models.Booking.id).label("total")
        ).filter(models.Booking.shop_id == shop_id).group_by(models.Booking.service_type).all()
        
        service_map = {item.service_type: item.total for item in service_counts}

        # 4. Total Weight Volume (kg)
        total_kg = db.query(func.sum(models.Booking.weight)).filter(
            models.Booking.shop_id == shop_id
        ).scalar() or 0.0

        # 5. AI Engine Data
        ai = AIEngine()
        predicted_count_today = ai.get_predicted_bookings(datetime.now())
        projected_income_today = ai.calculate_projected_income(predicted_count_today)

        active_machines = db.query(models.Machine).filter(
            models.Machine.shop_id == shop_id,
            models.Machine.status == "Busy"
        ).count()

        return {
            "today_revenue": round(float(today_revenue), 2),
            "last_week_revenue": round(float(last_week_revenue), 2),
            "total_bookings": today_bookings,
            "last_week_bookings": last_week_bookings,
            "active_machines": active_machines,
            "predicted_bookings_today": predicted_count_today,
            "projected_income_today": projected_income_today,
            "full_service": service_map.get("Full Service", 0),
            "titan_wash": service_map.get("Titan Wash", 0),
            "regular_wash": service_map.get("Regular Wash", 0),
            "comforter": service_map.get("Comforter", 0),
            "total_kg": round(float(total_kg), 2)
        }

    @staticmethod
    def get_forecast_data(db: Session, shop_id: int = 1):
        ai = AIEngine()
        raw_forecast = ai.get_weekly_forecast(is_rainy_forecast=False)
        ai_narrative = insight_engine.generate_forecast_insight(raw_forecast)

        history_data = []
        for i in range(6, -1, -1):
            target_date = datetime.now().date() - timedelta(days=i)
            actual_income = db.query(func.sum(models.Booking.total_price)).filter(
                models.Booking.shop_id == shop_id,
                func.date(models.Booking.created_at) == target_date
            ).scalar() or 0.0
            
            history_data.append({
                "label": target_date.strftime("%b %d"),
                "actual_income": round(float(actual_income), 2)
            })

        return {
            "forecast": raw_forecast,
            "history": history_data,
            "ai_generated_insight": ai_narrative
        }

    @staticmethod
    def get_service_distribution(db: Session, shop_id: int = 1):
        distribution = db.query(
            models.Booking.service_type, 
            func.count(models.Booking.id).label("count")
        ).filter(models.Booking.shop_id == shop_id).group_by(models.Booking.service_type).all()
        return {item.service_type: item.count for item in distribution}

    @staticmethod
    def get_ai_prediction_metrics(db: Session) -> Dict[str, Any]:
        ai = AIEngine()
        return {
            "status": "success",
            "demand_forecasting_model": ai.calculate_model_accuracy(),
            "utility_telemetry_model": PredictionService.calculate_utility_accuracy()
        }