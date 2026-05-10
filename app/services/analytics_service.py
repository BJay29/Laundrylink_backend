from sqlalchemy.orm import Session
from app.controller.analytics_controller import AnalyticsController
from app.services.ai_engine import AIEngine
from datetime import datetime, timedelta, timezone

class AnalyticsService:
    """
    Service layer responsible for orchestrating data between the 
    AnalyticsController and the AIEngine for the Laundry Management System.
    Updated to provide comparative historical data for accurate forecasting.
    """

    def __init__(self, db: Session):
        self.db = db
        self.ai = AIEngine()

    def get_complete_dashboard_data(self, shop_id: int = 1):
        """
        Combines real-time database metrics with AI-driven insights.
        Includes a 'history' key to allow frontend trend calculations (vs last week).
        """
        # 1. Fetch current summary (Today's performance)
        actual_metrics = AnalyticsController.get_dashboard_summary(self.db, shop_id)
        
        # 2. Fetch service distribution (Pie chart data)
        distribution = AnalyticsController.get_service_distribution(self.db, shop_id) 
        
        # 3. Fetch graph data (Contains both Historical Actuals and Future Forecasts)
        graph_data = AnalyticsController.get_forecast_data(self.db, shop_id)

        # 4. Extract history specifically for KPI card comparisons
        # This prevents the "800% Trend" bug by giving the frontend a baseline.
        history_baseline = self._get_last_7_days_history(shop_id)

        return {
            "summary": actual_metrics,
            "history": history_baseline, # Essential for trend accuracy
            "distribution": distribution,
            "charts": graph_data,
            "ai_status": {
                "engine_active": True,
                "last_sync": datetime.now(timezone.utc).isoformat(),
                "recommendation": self._generate_ai_recommendation(actual_metrics)
            }
        }

    def _get_last_7_days_history(self, shop_id: int) -> list:
        """
        Helper to fetch daily totals for the past week.
        Used by the frontend to compare Projected Weekly Revenue vs Actual Weekly Revenue.
        """
        # Orchestrate call to controller to get daily breakdown of the last 7 days
        return AnalyticsController.get_daily_historical_revenue(self.db, shop_id, days=7)

    def _generate_ai_recommendation(self, metrics: dict) -> str:
        """
        Generates tactical business advice based on AI vs Actual gaps.
        """
        actual = metrics.get("today_revenue", 0)
        projected = metrics.get("projected_income_today", 0)

        # Avoid empty data recommendations
        if projected == 0:
            return "AI Engine is gathering data. Performance insights will be available shortly."

        if actual >= projected:
            return "Current revenue is exceeding AI projections. Optimize machine turnover to maintain momentum."
        elif actual < (projected * 0.7):
            return "Revenue is 30% below projection. Consider a 'Flash Sale' or 'Happy Hour' discount for off-peak slots."
        else:
            return "Revenue is slightly below target. Check for machine downtime or pending bookings that need completion."

    def get_service_efficiency(self, shop_id: int = 1):
        """
        Calculates efficiency by comparing total weight processed 
        against the number of bookings to find the average load per service.
        """
        summary = AnalyticsController.get_dashboard_summary(self.db, shop_id)
        total_kg = summary.get("total_kg", 0)
        
        # Aggregating all service types to get total volume
        total_bookings = (
            summary.get("full_service", 0) + 
            summary.get("titan_wash", 0) + 
            summary.get("regular_wash", 0) + 
            summary.get("comforter", 0)
        )

        # Calculate average weight per load (KPI for machine wear-and-tear)
        avg_load = total_kg / total_bookings if total_bookings > 0 else 0
        
        return {
            "total_processed_kg": total_kg,
            "total_bookings": total_bookings,
            "average_kg_per_load": round(avg_load, 2),
            "efficiency_rating": "Optimal" if 5 <= avg_load <= 8 else "Sub-optimal"
        }