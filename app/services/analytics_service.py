from sqlalchemy.orm import Session
from app.controller.analytics_controller import AnalyticsController
from app.services.ai_engine import AIEngine

class AnalyticsService:
    """
    Service layer responsible for orchestrating data between the 
    AnalyticsController and the AIEngine for the Laundry Management System.
    """

    def __init__(self, db: Session):
        self.db = db
        self.ai = AIEngine()

    def _calculate_percentage_trend(self, current: float, previous: float) -> dict:
        """
        Calculates the percentage difference between two values.
        Returns the formatted string and the status for UI styling.
        """
        if previous == 0:
            return {"trend": "0%", "status": "equal"}
        
        diff = current - previous
        percent = (diff / previous) * 100
        status = 'up' if percent > 0.5 else ('down' if percent < -0.5 else 'equal')
        
        return {
            "trend": f"{abs(round(percent, 1))}%",
            "status": status
        }

    def get_complete_dashboard_data(self, shop_id: int = 1):
        """
        Combines real-time database metrics with AI-driven insights
        and trend analysis for the dashboard frontend.
        """
        # Fetch actual metrics and historical context from the controller
        actual_metrics = AnalyticsController.get_dashboard_summary(self.db, shop_id)
        
        # Calculate trends for Revenue and Bookings
        current_rev = actual_metrics.get("today_revenue", 0)
        previous_rev = actual_metrics.get("last_week_revenue", 1) # Ensure default is 1 to avoid div by zero
        
        current_book = actual_metrics.get("total_bookings", 0)
        previous_book = actual_metrics.get("last_week_bookings", 1)

        rev_trend = self._calculate_percentage_trend(current_rev, previous_rev)
        book_trend = self._calculate_percentage_trend(current_book, previous_book)
        
        distribution = AnalyticsController.get_service_distribution(self.db, shop_id) 
        graph_data = AnalyticsController.get_forecast_data(self.db, shop_id)

        return {
            "summary": actual_metrics,
            "trends": {
                "revenue": rev_trend,
                "bookings": book_trend
            },
            "distribution": distribution,
            "charts": graph_data,
            "ai_status": {
                "engine_active": True,
                "last_sync": "Just now",
                "recommendation": self._generate_ai_recommendation(actual_metrics)
            }
        }

    def _generate_ai_recommendation(self, metrics: dict) -> str:
        """
        Internal logic to generate a recommendation based on revenue performance.
        """
        actual = metrics.get("today_revenue", 0)
        projected = metrics.get("projected_income_today", 0)

        if actual >= projected:
            return "Current revenue is meeting or exceeding AI projections. Maintain current staffing levels."
        elif actual < (projected * 0.7):
            return "Revenue is significantly lower than projected. Consider running a flash promotion."
        else:
            return "Revenue is slightly below target. Check machine availability and turnover speed."

    def get_service_efficiency(self, shop_id: int = 1):
        """
        Calculates efficiency by comparing total weight processed 
        against the number of bookings.
        """
        summary = AnalyticsController.get_dashboard_summary(self.db, shop_id)
        total_kg = summary.get("total_kg", 0)
        
        total_bookings = (
            summary.get("full_service", 0) + 
            summary.get("titan_wash", 0) + 
            summary.get("regular_wash", 0) + 
            summary.get("comforter", 0)
        )

        avg_load = total_kg / total_bookings if total_bookings > 0 else 0
        
        return {
            "total_processed_kg": total_kg,
            "total_bookings": total_bookings,
            "average_kg_per_load": round(avg_load, 2)
        }