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
        """
        Fetches live operational insights regarding current machine telemetry status, 
        projected profit impacts, and business strategy suggestions.
        """
        # Calls the functional evaluation logic directly from app/services/insight_engine.py
        return insight_engine.generate_operational_insight(db)

    @staticmethod
    def get_dashboard_summary(db: Session, shop_id: int = 1):
        """
        Calculates aggregate summary statistics for the top-level dashboard metrics 
        and lower service breakdown counters.
        """
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        # 1. Fetch Actual Financial Income for Today
        today_revenue = db.query(func.sum(models.Booking.total_price)).filter(
            models.Booking.shop_id == shop_id,
            func.date(models.Booking.created_at) == today
        ).scalar() or 0.0

        # 2. Fetch Actual Financial Income for Yesterday
        yesterday_revenue = db.query(func.sum(models.Booking.total_price)).filter(
            models.Booking.shop_id == shop_id,
            func.date(models.Booking.created_at) == yesterday
        ).scalar() or 0.0

        # 3. Calculate Income Growth/Loss Percentage Relative to Yesterday
        income_growth = 0.0
        if yesterday_revenue > 0:
            income_growth = ((today_revenue - yesterday_revenue) / yesterday_revenue) * 100

        # 4. Aggregate Actual Service Volumes (Total Count partitioned by Type)
        service_counts = db.query(
            models.Booking.service_type, 
            func.count(models.Booking.id).label("total")
        ).filter(models.Booking.shop_id == shop_id).group_by(models.Booking.service_type).all()
        
        service_map = {item.service_type: item.total for item in service_counts}

        # 5. Calculate Average Global Ticket Value Income Per Service
        total_stats = db.query(
            func.sum(models.Booking.total_price).label("revenue"),
            func.count(models.Booking.id).label("count")
        ).filter(models.Booking.shop_id == shop_id).first()

        total_revenue = float(total_stats.revenue or 0.0)
        total_bookings = int(total_stats.count or 0)
        avg_per_service = round(total_revenue / total_bookings, 2) if total_bookings > 0 else 0.0

        # 6. Calculate Total Cumulative Hardware Load Weight Processing Volume (kg)
        total_kg = db.query(func.sum(models.Booking.weight)).filter(
            models.Booking.shop_id == shop_id
        ).scalar() or 0.0

        # 7. Query Forecast Projections directly from the central AIEngine
        ai = AIEngine()
        predicted_count_today = ai.get_predicted_bookings(datetime.now())
        projected_income_today = ai.calculate_projected_income(predicted_count_today)

        # 8. Fetch Total Number of Active Machines currently running a 'Busy' state
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
        Generates the sequential 7-day future prediction array for frontend graph rendering.
        Includes a matching historical trend matrix for comparative client visualizations.
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
        Returns an isolated proportional structural map of processing category totals 
        to evaluate seasonal business distribution trends.
        """
        distribution = db.query(
            models.Booking.service_type, 
            func.count(models.Booking.id).label("count")
        ).filter(models.Booking.shop_id == shop_id).group_by(models.Booking.service_type).all()

        return {item.service_type: item.count for item in distribution}

    @staticmethod
    def get_ai_prediction_metrics(db: Session) -> Dict[str, Any]:
        """
        Aggregates model mathematical accuracy configurations, statistical confidence indices, 
        and water/electricity hardware calibration logs for frontend ingestion.
        Accepts an open database connection context session parameters to review data targets.
        """
        ai = AIEngine()
        
        # Evaluate model mathematical variances using database constraints if required
        demand_metrics = ai.calculate_model_accuracy()
        
        # Evaluate hardware telemetry consumption coefficients and baseline calibration metrics
        utility_metrics = PredictionService.calculate_utility_accuracy()
        
        return {
            "status": "success",
            "demand_forecasting_model": demand_metrics,
            "utility_telemetry_model": utility_metrics
        }