class PredictionService:
    """
    Handles the calculation of machine overhead costs based on cumulative 
    usage and service-specific duration (Full Service, Titan, etc.).
    """

    # --- SERVICE TIME MAPPING (In Minutes) ---
    # Based on Hann Wash pricing: Wash (38-48m) + Dry (40m)
    SERVICE_CONFIG = {
        "Regular Wash": {"time": 38, "water_usage": True},
        "Titan Wash": {"time": 38, "water_usage": True},
        "Premium Wash": {"time": 48, "water_usage": True},
        "Full Service": {"time": 78, "water_usage": True},  # 38m Wash + 40m Dry
        "Comforter": {"time": 95, "water_usage": True},     # Extra heavy load
        "Dry Only (20min)": {"time": 20, "water_usage": False},
        "Dry Only (30min)": {"time": 30, "water_usage": False},
        "Dry Only (40min)": {"time": 40, "water_usage": False},
    }

    @staticmethod
    def calculate_booking_consumption(service_type: str):
        """
        Estimates the consumption costs for a single booking instance.
        This is called before saving a booking to update the machine's cumulative totals.
        """
        # --- CALIBRATED RATES (Laundry Industry Standards) ---
        ELECTRICITY_RATE_PER_MINUTE = 0.25  # Estimated cost per minute of machine operation
        WATER_COST_PER_LOAD = 4.80         # Fixed cost for water/drainage per wash cycle
        DETERGENT_COST_PER_LOAD = 11.25     # Cost for standard detergent/softener dose

        config = PredictionService.SERVICE_CONFIG.get(service_type, {"time": 30, "water_usage": True})
        duration = config["time"]

        # Calculate specific costs for this session
        electricity = duration * ELECTRICITY_RATE_PER_MINUTE
        water = WATER_COST_PER_LOAD if config["water_usage"] else 0.0
        detergent = DETERGENT_COST_PER_LOAD if config["water_usage"] else 0.0

        return {
            "electricity": electricity,
            "water": water,
            "detergent": detergent
        }

    @staticmethod
    def get_machine_metrics(machine, is_busy: bool = False):
        """
        Returns the historical cumulative metrics already stored in the machine model.
        This ensures the Machine Hub reflects real-world wear and tear.
        """
        # If total_cycles is 0, we ensure a clean slate for new hardware
        if machine.total_cycles <= 0:
            return {
                "detergent_cost": 0.00,
                "electricity_cost": 0.00,
                "water_cost": 0.00,
                "total_overhead": 0.00,
                "is_active_consumption": is_busy
            }

        # Return the stored cumulative totals from the database
        return {
            "detergent_cost": round(machine.total_detergent_cost, 2),
            "electricity_cost": round(machine.total_electricity_cost, 2),
            "water_cost": round(machine.total_water_cost, 2),
            "total_overhead": round(
                machine.total_detergent_cost + 
                machine.total_electricity_cost + 
                machine.total_water_cost, 2
            ),
            "is_active_consumption": is_busy
        }