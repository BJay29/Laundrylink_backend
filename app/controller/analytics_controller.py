from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from app import models
from app.services.ai_engine import AIEngine

class AnalyticsController:
    """
    Handles the logic for data aggregation, comparison, and AI-driven forecasting.
    """

    @staticmethod
    def get_dashboard_summary(db: Session, shop_id: int = 1):
        """
        Calculates summary statistics for dashboard cards including growth comparisons.
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

        # 4. Get Predicted Data from AI Engine for Today
        # This helps compare 'Actual' vs 'Predicted' in real-time
        ai = AIEngine()
        predicted_count_today = ai.get_predicted_bookings(datetime.now())
        projected_income_today = ai.calculate_projected_income(predicted_count_today)

        # 5. Fetch Total Active Machines
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
            "accuracy_rate": 85.5 # Static baseline, can be calculated dynamically later
        }

    @staticmethod
    def get_forecast_data(db: Session, shop_id: int = 1):
        """
        Generates the 7-day forecast data used by the Recharts/Chart.js frontend.
        """
        ai = AIEngine()
        # You can integrate a weather API here to toggle is_rainy_forecast
        raw_forecast = ai.get_weekly_forecast(is_rainy_forecast=False)

        # We can also fetch the last 7 days of ACTUAL data to show a 'History vs Forecast' trend
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
        Calculates which services are most used to refine AI weights.
        """
        distribution = db.query(
            models.Booking.service_type, 
            func.count(models.Booking.id).label("count")
        ).filter(models.Booking.shop_id == shop_id).group_by(models.Booking.service_type).all()

        return {item.service_type: item.count for item in distribution}