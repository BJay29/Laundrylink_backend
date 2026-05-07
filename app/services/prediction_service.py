class PredictionService:
    """
    Handles real-time calculations for machine monitoring on the dashboard.
    Calculates exact service duration, net profit, and profitability percentage
    based on shop price lists and operational overhead.
    """

    # --- SERVICE DATA MAPPING (Based on Shop Price List Image) ---
    # Maps service types to their exact duration in minutes for the Machine Card timer.
    # Service times are based on the physical price list image provided.
    SERVICE_MAPPER = {
        "Full Service": {"duration": 90, "base_cost": 45.00}, # Combined Wash (48) + Dry (40) + Service
        "Regular Wash": {"duration": 38, "base_cost": 19.80}, # 38 mins per price list
        "Titan Wash":   {"duration": 38, "base_cost": 25.00}, # 38 mins per price list
        "Comforter":    {"duration": 45, "base_cost": 35.00}  # Heavy load calibration
    }

    @staticmethod
    def calculate_metrics(machine, is_busy: bool = False):
        """
        Calculates overhead costs and profitability for machine cards.
        Ensures 'Exact Time' and 'Net Profit' are accurately reflected on the UI.
        Used to drive the progress bars and analytics in the Dashboard.
        """
        # --- CALIBRATED UTILITY RATES ---
        # Constants derived from monthly expense tracking (P10k Utilities / P40k Supplies).
        # These rates translate consumption into actual PHP costs.
        ELECTRICITY_RATE_PER_KWH = 12.50  
        WATER_RATE_PER_LITER = 0.08      
        DETERGENT_RATE_PER_ML = 0.25     

        cycle_count = machine.total_cycles
        
        # Retrieve exact duration and base cost mapping for the current service
        service_info = PredictionService.SERVICE_MAPPER.get(
            machine.current_service_type, 
            {"duration": 0, "base_cost": 0.00}
        )

        # 1. Calculate Lifetime Overhead Costs (Machine Hub Telemetry)
        # Overhead is 0 if no cycles have been recorded yet.
        if cycle_count <= 0:
            electricity_cost = 0.00
            water_cost = 0.00
            detergent_cost = 0.00
        else:
            # Uses the machine's average consumption per hardware cycle
            electricity_cost = cycle_count * machine.avg_electricity
            water_cost = cycle_count * machine.avg_water
            detergent_cost = cycle_count * machine.avg_detergent

        total_overhead = electricity_cost + water_cost + detergent_cost

        # 2. Profitability Calculation (For Dashboard Progress Bar and Net Profit label)
        # Net Profit = Current Price (Revenue) - Estimated overhead for the active cycle.
        current_net_profit = 0.0
        profit_percentage = 0.0
        
        if is_busy and machine.current_price > 0:
            # Calculate cost for the current active service to show real-time profit margin
            current_cycle_overhead = machine.avg_electricity + machine.avg_water + machine.avg_detergent
            current_net_profit = machine.current_price - current_cycle_overhead
            
            # Profitability Percentage drives the green progress bar on the Dashboard Card
            profit_percentage = (current_net_profit / machine.current_price) * 100

        # Ensure we return at least 0.00 and not negative values for display purposes
        display_profit = max(0.0, current_net_profit)
        display_percentage = max(0.0, profit_percentage)

        return {
            "detergent_cost": round(detergent_cost, 2),
            "electricity_cost": round(electricity_cost, 2),
            "water_cost": round(water_cost, 2),
            "total_overhead": round(total_overhead, 2),
            "duration_minutes": service_info["duration"], # Exact time (e.g., 38, 48, 90)
            "net_profit": round(display_profit, 2),
            "profitability_rate": round(display_percentage, 2),
            "is_active_consumption": is_busy
        }

    @staticmethod
    def get_service_duration(service_type: str) -> int:
        """
        Helper to retrieve exact minutes for a specific laundry service.
        Used by the Booking Controller to initialize a machine's remaining_time.
        """
        return PredictionService.SERVICE_MAPPER.get(service_type, {"duration": 0})["duration"]