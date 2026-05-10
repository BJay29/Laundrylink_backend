from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta, timezone
from app import models
from app.services.ai_engine import AIEngine

class AnalyticsController:
    """
    Handles data aggregation, historical comparison, and AI-driven forecasting.
    Updated to provide consistent 7-day baselines to prevent percentage calculation errors.
    """

    @staticmethod
    def get_dashboard_summary(db: Session, shop_id: int = 1):
        """
        Calculates summary statistics for the dashboard cards.
        Now includes 'actual_income' to ensure consistency with the Booking model.
        """
        # Using timezone-aware UTC for consistency with model defaults
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        # 1. Fetch Actual Income for Today (using actual_income field for precision)
        today_revenue = db.query(func.sum(models.Booking.actual_income)).filter(
            models.Booking.shop_id == shop_id,
            func.date(models.Booking.booking_timestamp) == today,
            models.Booking.status == "Completed"
        ).scalar() or 0.0

        # 2. Fetch Actual Income for Yesterday
        yesterday_revenue = db.query(func.sum(models.Booking.actual_income)).filter(
            models.Booking.shop_id == shop_id,
            func.date(models.Booking.booking_timestamp) == yesterday,
            models.Booking.status == "Completed"
        ).scalar() or 0.0

        # 3. Calculate Income Growth Percentage (Day-over-Day)
        income_growth = 0.0
        if yesterday_revenue > 0:
            income_growth = ((today_revenue - yesterday_revenue) / yesterday_revenue) * 100

        # 4. Aggregate Service Volumes
        service_counts = db.query(
            models.Booking.service_type, 
            func.count(models.Booking.id).label("total")
        ).filter(models.Booking.shop_id == shop_id).group_by(models.Booking.service_type).all()
        
        service_map = {item.service_type: item.total for item in service_counts}

        # 5. Calculate Total Actual Weight (kg) 
        total_kg = db.query(func.sum(models.Booking.weight)).filter(
            models.Booking.shop_id == shop_id
        ).scalar() or 0.0

        # 6. AI Engine Integration
        ai = AIEngine()
        predicted_count_today = ai.get_predicted_bookings(datetime.now())
        projected_income_today = ai.calculate_projected_income(predicted_count_today)

        # 7. Real-time Machine Telemetry
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
            "accuracy_rate": 88.4, # Example accuracy metric
            "full_service": service_map.get("Full Service", 0),
            "titan_wash": service_map.get("Titan Wash", 0),
            "regular_wash": service_map.get("Regular Wash", 0),
            "comforter": service_map.get("Comforter", 0),
            "total_kg": round(total_kg, 2)
        }

    @staticmethod
    def get_daily_historical_revenue(db: Session, shop_id: int, days: int = 7):
        """
        New Helper: Fetches a daily breakdown of income and bookings for a specific range.
        This provides the 'lastWeekActualRevenue' baseline needed for the 3 KPI cards.
        """
        history = []
        for i in range(days - 1, -1, -1):
            target_date = datetime.now(timezone.utc).date() - timedelta(days=i)
            
            # Aggregate income and booking counts for the specific day
            metrics = db.query(
                func.sum(models.Booking.actual_income).label("income"),
                func.count(models.Booking.id).label("bookings")
            ).filter(
                models.Booking.shop_id == shop_id,
                func.date(models.Booking.booking_timestamp) == target_date,
                models.Booking.status == "Completed"
            ).first()

            history.append({
                "date": target_date.isoformat(),
                "actual_income": round(metrics.income or 0.0, 2),
                "actual_bookings": metrics.bookings or 0
            })
        return history

    @staticmethod
    def get_forecast_data(db: Session, shop_id: int = 1):
        """
        Generates 7-day forecast vs 7-day historical data for charts.
        """
        ai = AIEngine()
        raw_forecast = ai.get_weekly_forecast()

        # Fetch history for the chart
        history_data = []
        for i in range(6, -1, -1):
            target_date = datetime.now(timezone.utc).date() - timedelta(days=i)
            actual_income = db.query(func.sum(models.Booking.actual_income)).filter(
                models.Booking.shop_id == shop_id,
                func.date(models.Booking.booking_timestamp) == target_date,
                models.Booking.status == "Completed"
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
        Returns distribution map for pie charts and AI weighting.
        """
        distribution = db.query(
            models.Booking.service_type, 
            func.count(models.Booking.id).label("count")
        ).filter(
            models.Booking.shop_id == shop_id,
            models.Booking.status == "Completed"
        ).group_by(models.Booking.service_type).all()

        return {item.service_type: item.count for item in distribution}