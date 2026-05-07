from typing import Dict, Any

class PredictionService:
    """
    Single source of truth for machine cost calculations and profitability metrics.
    
    Calibrated Resource Rates:
    - Washer: Electricity ₱14.20 | Water ₱16.50 | Detergent ₱12.75 (100ml calibration)
    - Dryer:  Electricity ₱38.50 | Water ₱0.00  | Detergent ₱0.00  (High energy draw)
    
    Hardware Occupancy (Minutes):
    - Washer: 45m (Base) | 60m (Heavy/Comforter)
    - Dryer:  40m (Base) | 50m (Heavy/Comforter)
    """

    # --- COST RATES PER CYCLE (PHP) ---
    # Dryer electricity is set to 38.50 to reflect high-heat energy consumption
    WASHER_COSTS = {
        "electricity": 14.20,
        "water":       16.50,
        "detergent":   12.75,
    }
    DRYER_COSTS = {
        "electricity": 38.50,
        "water":         0.00,
        "detergent":     0.00,
    }

    # --- DEFAULT HARDWARE DURATIONS (Minutes) ---
    # Represents actual hardware occupancy time on the machine hub
    MACHINE_DURATIONS = {
        "washer": 45,
        "dryer":  40,
    }

    @classmethod
    def get_overhead(cls, machine_type: str) -> Dict[str, float]:
        """
        Retrieves the cost breakdown based on the hardware category.
        Used to determine the 'Total Expense' for a single transaction cycle.
        """
        m_type = machine_type.lower().strip()
        costs = cls.WASHER_COSTS if m_type == "washer" else cls.DRYER_COSTS

        return {
            "electricity_cost": costs["electricity"],
            "water_cost":       costs["water"],
            "detergent_cost":   costs["detergent"],
            "total_overhead":   sum(costs.values()),
        }

    @classmethod
    def get_machine_runtime(cls, machine_type: str, service_type: str) -> int:
        """
        Calculates the hardware runtime. 
        Adjusts the 'Remaining Time' based on load intensity (e.g., Comforters).
        """
        m_type = machine_type.lower().strip()
        s_type = (service_type or "").lower().strip()

        # Heavy Load Logic: Increases cycle time for industrial-grade washing/drying
        if any(keyword in s_type for keyword in ["comforter", "titan", "heavy"]):
            return 60 if m_type == "washer" else 50
        
        # Default standard cycle duration
        return cls.MACHINE_DURATIONS.get(m_type, 45)

    @classmethod
    def calculate_metrics(cls, machine: Any, is_busy: bool = False) -> Dict[str, Any]:
        """
        Aggregates financial and operational data for the Dashboard.
        Syncs with the React frontend to drive color-coded alerts and progress bars.
        """
        overhead = cls.get_overhead(machine.machine_type)
        total_cost = overhead["total_overhead"]

        # Null-safe retrieval of lifetime net profit from database
        accumulated_net = getattr(machine, "net_profit_accumulated", 0.0) or 0.0

        # --- PROFITABILITY RATIO CALCULATION ---
        # Formula: ((Revenue - Overhead) / Revenue) * 100
        current_price = getattr(machine, "current_price", 0.0) or 0.0
        if current_price > 0:
            profit_margin = ((current_price - total_cost) / current_price) * 100
            # Clamping the rate between 0 and 100 for consistent UI progress bars
            profitability_rate = max(0.0, min(100.0, profit_margin))
        else:
            profitability_rate = 0.0

        # --- HARDWARE TELEMETRY ---
        # If machine is busy, determine its countdown duration based on current service
        service_type = getattr(machine, "current_service_type", "") or ""
        duration = cls.get_machine_runtime(machine.machine_type, service_type) if is_busy else 0

        return {
            "duration_minutes":       duration,
            "profitability_rate":     round(profitability_rate, 2),
            "net_profit":             round(accumulated_net, 2),
            "electricity_cost":       overhead["electricity_cost"],
            "water_cost":             overhead["water_cost"],
            "detergent_cost":         overhead["detergent_cost"],
            "total_overhead":         overhead["total_overhead"],
            "is_active_consumption":  is_busy,
        }