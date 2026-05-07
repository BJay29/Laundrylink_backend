from typing import Dict, Any

class PredictionService:
    """
    Single source of truth for machine cost calculations and profitability metrics.
    
    Calibrated Resource Rates:
    - Washer: Electricity ₱14.20 | Water ₱16.50 | Detergent ₱12.75 (100ml calibration)
    - Dryer:  Electricity ₱38.50 | Water ₱0.00  | Detergent ₱0.00  (High energy draw)
    """

    # --- COST RATES PER CYCLE (PHP) ---
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
    MACHINE_DURATIONS = {
        "washer": 45,
        "dryer":  40,
    }

    @classmethod
    def get_overhead(cls, machine_type: str, total_cycles: int = 0, is_busy: bool = False) -> Dict[str, float]:
        """
        Retrieves the cost breakdown based on hardware category and activity status.
        FIXED: Returns 0.0 costs if the machine has never been used and is not currently running.
        """
        m_type = machine_type.lower().strip()
        costs = cls.WASHER_COSTS if m_type == "washer" else cls.DRYER_COSTS

        # Activity Gate: If no cycles have occurred and machine isn't currently busy, 
        # we do not attribute any overhead costs to it.
        if total_cycles == 0 and not is_busy:
            return {
                "electricity_cost": 0.0,
                "water_cost":       0.0,
                "detergent_cost":   0.0,
                "total_overhead":   0.0,
            }

        # For machines with history, we calculate cumulative overhead based on cycles.
        # Note: If you want lifetime overhead, you would multiply these by total_cycles.
        # Currently, this returns the rate per cycle for the Telemetry Table.
        return {
            "electricity_cost": costs["electricity"],
            "water_cost":       costs["water"],
            "detergent_cost":   costs["detergent"],
            "total_overhead":   sum(costs.values()),
        }

    @classmethod
    def get_machine_runtime(cls, machine_type: str, service_type: str) -> int:
        """
        Calculates hardware runtime based on load intensity (e.g., Comforters).
        """
        m_type = machine_type.lower().strip()
        s_type = (service_type or "").lower().strip()

        if any(keyword in s_type for keyword in ["comforter", "titan", "heavy"]):
            return 60 if m_type == "washer" else 50
        
        return cls.MACHINE_DURATIONS.get(m_type, 45)

    @classmethod
    def calculate_metrics(cls, machine: Any, is_busy: bool = False) -> Dict[str, Any]:
        """
        Aggregates financial and operational data for the Dashboard.
        FIXED: Integrated cycle-count awareness to prevent displaying costs on unused machines.
        """
        # Get cycles from the machine model
        total_cycles = getattr(machine, "total_cycles", 0) or 0
        
        # Calculate overhead with the new activity check
        overhead = cls.get_overhead(machine.machine_type, total_cycles, is_busy)
        total_cost = overhead["total_overhead"]

        # Null-safe retrieval of lifetime net profit
        accumulated_net = getattr(machine, "net_profit_accumulated", 0.0) or 0.0

        # --- PROFITABILITY RATIO CALCULATION ---
        current_price = getattr(machine, "current_price", 0.0) or 0.0
        if current_price > 0 and total_cost > 0:
            profit_margin = ((current_price - total_cost) / current_price) * 100
            profitability_rate = max(0.0, min(100.0, profit_margin))
        else:
            profitability_rate = 0.0

        # --- HARDWARE TELEMETRY ---
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
            "is_active_consumption":  is_busy or total_cycles > 0,
        }