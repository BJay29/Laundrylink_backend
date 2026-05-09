import random
import numpy as np
from datetime import datetime, timedelta

class AIEngine:
    """
    Intelligent Engine for Laundry Income Optimization.
    Calculates demand forecasting based on historical shop patterns and service mix.
    """

    # Service pricing based on Hanna Wash Questionnaire
    PRICES = {
        "full_service": 210.0,
        "titan_wash": 100.0,
        "regular_wash": 65.0,
        "comforter": 150.0
    }

    # Probability weights for service types based on shop trends
    SERVICE_WEIGHTS = {
        "full_service": 0.40,  # 40% of customers
        "titan_wash": 0.20,    # 20% of customers
        "regular_wash": 0.30,  # 30% of customers
        "comforter": 0.10      # 10% of customers
    }

    # Add-on Constants
    DETERGENT_PRICE = 40.0
    DELIVERY_PRICE = 70.0
    RUSH_MULTIPLIER = 1.40  # 40% additional charge

    # Baseline volume from questionnaire
    WEEKDAY_BASE = 12
    WEEKEND_BASE = 25
    PEAK_DAYS = [0, 4, 5]  # Monday, Friday, Saturday

    @staticmethod
    def get_predicted_bookings(target_date: datetime, is_rainy: bool = False):
        """
        Predicts the number of bookings for a specific date.
        Incorporates peak days and weather surge variables.
        """
        day_of_week = target_date.weekday()
        
        # Determine base count based on peak day logic
        if day_of_week in AIEngine.PEAK_DAYS:
            base_count = AIEngine.WEEKEND_BASE
        else:
            base_count = AIEngine.WEEKDAY_BASE

        # Apply Weather Surge: 30-50% increase if rainy
        if is_rainy:
            surge = random.uniform(1.3, 1.5)
            base_count = int(base_count * surge)

        # Add Gaussian noise for natural variation to maintain accuracy
        noise = int(np.random.normal(0, 2))
        final_prediction = max(0, base_count + noise)
        
        return final_prediction

    @staticmethod
    def calculate_projected_income(predicted_bookings: int):
        """
        Calculates income by simulating service distribution for the predicted volume.
        """
        total_income = 0.0
        services = list(AIEngine.PRICES.keys())
        weights = [AIEngine.SERVICE_WEIGHTS[s] for s in services]

        for _ in range(predicted_bookings):
            # Select service type based on probability
            selected_service = random.choices(services, weights=weights)[0]
            price = AIEngine.PRICES[selected_service]

            # Simulate Add-ons
            # 35% chance of purchasing detergent
            if random.random() < 0.35:
                price += AIEngine.DETERGENT_PRICE
            
            # 15% chance of choosing Rush Service (40% markup)
            if random.random() < 0.15:
                price *= AIEngine.RUSH_MULTIPLIER

            # 10% chance of requiring Delivery
            if random.random() < 0.10:
                price += AIEngine.DELIVERY_PRICE

            total_income += price

        return round(total_income, 2)

    def get_weekly_forecast(self, is_rainy_forecast: bool = False):
        """
        Generates a 7-day forecast array for the React Frontend graph.
        """
        forecast_data = []
        today = datetime.now()

        for i in range(1, 8):
            future_date = today + timedelta(days=i)
            bookings = self.get_predicted_bookings(future_date, is_rainy_forecast)
            income = self.calculate_projected_income(bookings)

            forecast_data.append({
                "date": future_date.strftime("%Y-%m-%d"),
                "label": future_date.strftime("%b %d, %a"),  # e.g., "May 10, Sun"
                "predicted_bookings": bookings,
                "projected_income": income,
                "is_peak": future_date.weekday() in self.PEAK_DAYS
            })

        return forecast_data