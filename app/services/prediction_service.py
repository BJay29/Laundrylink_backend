class PredictionService:
    """
    Handles the calculation of machine overhead costs based on usage cycles
    to provide realistic predictions for the Machine Hub dashboard.
    """

    @staticmethod
    def calculate_metrics(cycle_count: int, is_busy: bool = False):
        # Operational baseline from research/questionnaire data
        MONTHLY_UTILITIES = 10000.00
        MONTHLY_SUPPLIES = 40000.00
        
        # Estimated throughput (6 machines x 5 cycles/day x 30 days)
        # Used to derive the standard cost per individual cycle
        AVG_MONTHLY_CYCLES = 900 

        # Calculate unit rates per cycle
        detergent_rate = MONTHLY_SUPPLIES / AVG_MONTHLY_CYCLES
        utility_rate = MONTHLY_UTILITIES / AVG_MONTHLY_CYCLES

        # If cycle_count is 0, all costs remain 0.00
        # This ensures consumption 'stops' when the machine is idle
        if cycle_count <= 0:
            return {
                "detergent_cost": 0.00,
                "electricity_cost": 0.00,
                "water_cost": 0.00,
                "total_overhead": 0.00,
                "is_active_consumption": is_busy
            }

        # Splitting utility_rate: 65% for electricity, 35% for water
        electricity_cost = cycle_count * (utility_rate * 0.65)
        water_cost = cycle_count * (utility_rate * 0.35)
        detergent_cost = cycle_count * detergent_rate

        return {
            "detergent_cost": round(detergent_cost, 2),
            "electricity_cost": round(electricity_cost, 2),
            "water_cost": round(water_cost, 2),
            "total_overhead": round(detergent_cost + electricity_cost + water_cost, 2),
            "is_active_consumption": is_busy
        }