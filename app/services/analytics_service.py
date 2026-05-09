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

    def get_complete_dashboard_data(self, shop_id: int = 1):
        """
        Combines real-time database metrics with AI-driven insights
        to provide a unified response for the dashboard frontend.
        """
        # Fetch actual metrics from the controller
        actual_metrics = AnalyticsController.get_dashboard_summary(self.db, shop_id)
        
        # Fetch distribution data to analyze service trends
        distribution = AnalyticsController.get_service_distribution(self.db, shop_id)
        
        # Fetch the historical and forecast graph data
        graph_data = AnalyticsController.get_forecast_data(self.db, shop_id)

        return {
            "summary": actual_metrics,
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
        Internal logic to generate a simple text recommendation 
        based on the relationship between actual and predicted income.
        """
        actual = metrics.get("today_revenue", 0)
        projected = metrics.get("projected_income_today", 0)

        if actual >= projected:
            return "Current revenue is meeting or exceeding AI projections. Maintain current staffing levels."
        elif actual < (projected * 0.7):
            return "Revenue is significantly lower than projected. Consider running a flash promotion for off-peak hours."
        else:
            return "Revenue is slightly below target. Check machine availability and turnover speed."

    def get_service_efficiency(self, shop_id: int = 1):
        """
        Calculates efficiency by comparing total weight processed 
        against the number of bookings to find the average load per service.
        """
        summary = AnalyticsController.get_dashboard_summary(self.db, shop_id)
        total_kg = summary.get("total_kg", 0)
        
        # Calculate total bookings across the main service types
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