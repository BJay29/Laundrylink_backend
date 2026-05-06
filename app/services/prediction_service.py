class PredictionService:
    """
    Handles the calculation of machine overhead costs based on independent 
    usage cycles and machine-specific efficiency rates.
    """

    @staticmethod
    def calculate_metrics(machine, is_busy: bool = False):
        """
        Calculates metrics based on a specific machine instance to ensure 
        independent tracking and realistic cost hierarchy.
        """
        # --- CALIBRATED RATES (Base sa bill ng laundry shop) ---
        # Electricity is usually the highest expense in laundry operations.
        ELECTRICITY_RATE_PER_KWH = 12.50  
        WATER_RATE_PER_LITER = 0.08      
        DETERGENT_RATE_PER_ML = 0.25     

        cycle_count = machine.total_cycles

        # If cycle_count is 0, all costs remain 0.00.
        # This ensures a new machine (e.g., Washer 2) starts with a clean slate.
        if cycle_count <= 0:
            return {
                "detergent_cost": 0.00,
                "electricity_cost": 0.00,
                "water_cost": 0.00,
                "total_overhead": 0.00,
                "is_active_consumption": is_busy
            }

        # --- INDEPENDENT CALCULATION ---
        # Uses the specific consumption rates of the machine (from models.py)
        # to ensure Washer 1 and Washer 2 don't have identical data.
        
        # 1. Electricity (Target: Highest Cost)
        electricity_cost = cycle_count * (machine.avg_electricity * ELECTRICITY_RATE_PER_KWH)
        
        # 2. Water (Target: Middle Cost)
        water_cost = cycle_count * (machine.avg_water * WATER_RATE_PER_LITER)
        
        # 3. Detergent (Target: Lowest Cost)
        detergent_cost = cycle_count * (machine.avg_detergent * DETERGENT_RATE_PER_ML)

        return {
            "detergent_cost": round(detergent_cost, 2),
            "electricity_cost": round(electricity_cost, 2),
            "water_cost": round(water_cost, 2),
            "total_overhead": round(detergent_cost + electricity_cost + water_cost, 2),
            "is_active_consumption": is_busy
        }