class PredictionService:
    """
    Single source of truth for machine cost calculations and profitability metrics.
    
    Cost rates (calibrated to user survey data):
    - Washer: Electricity ₱14.20 | Water ₱16.50 | Detergent ₱12.75 per cycle
    - Dryer:  Electricity ₱38.50 | Water ₱0.00  | Detergent ₱0.00  per cycle
    
    Service durations:
    - Full Service / Regular Wash: 45 min base + 5 min per extra load
    - Titan Wash:                  60 min base
    - Comforter:                   90 min flat
    """

    # ── Cost rates per cycle ───────────────────────────────────────────────────
    WASHER_COSTS = {
        "electricity": 14.20,
        "water":       16.50,
        "detergent":   12.75,
    }
    DRYER_COSTS = {
        "electricity": 38.50,
        "water":        0.00,
        "detergent":    0.00,
    }

    # ── Service duration map (minutes) ────────────────────────────────────────
    SERVICE_DURATIONS = {
        "full service":       45,
        "regular wash":       45,
        "self-service (8kg)": 45,
        "titan wash (12kg)":  60,
        "comforter":          90,
    }

    @classmethod
    def get_overhead(cls, machine_type: str) -> dict:
        """Returns the cost breakdown for a machine type."""
        if machine_type.lower() == "washer":
            costs = cls.WASHER_COSTS
        else:
            costs = cls.DRYER_COSTS

        total = sum(costs.values())
        return {
            "electricity_cost": costs["electricity"],
            "water_cost":       costs["water"],
            "detergent_cost":   costs["detergent"],
            "total_overhead":   total,
        }

    @classmethod
    def get_duration(cls, service_type: str, loads: int = 1) -> int:
        """
        Returns exact cycle duration in minutes.
        Adds 5 minutes per additional load beyond the first.
        """
        key = (service_type or "").lower().strip()
        base = cls.SERVICE_DURATIONS.get(key, 45)
        extra = max(0, loads - 1) * 5
        return base + extra

    @classmethod
    def calculate_metrics(cls, machine, is_busy: bool = False) -> dict:
        """
        Calculates all analytics for a machine card / hub row.
        
        Returns:
            duration_minutes    – exact countdown time
            profitability_rate  – profit margin as % (0-100)
            net_profit          – lifetime net after overhead
            electricity_cost    – per-cycle cost
            water_cost          – per-cycle cost
            detergent_cost      – per-cycle cost
            total_overhead      – sum of all per-cycle costs
        """
        overhead = cls.get_overhead(machine.machine_type)
        total_cost = overhead["total_overhead"]

        # Net profit accumulated lifetime
        gross = getattr(machine, "net_profit_accumulated", 0.0) or 0.0

        # Profitability rate: (current_price - overhead) / current_price × 100
        current_price = getattr(machine, "current_price", 0.0) or 0.0
        if current_price > 0:
            profit_margin = ((current_price - total_cost) / current_price) * 100
            profitability_rate = max(0.0, min(100.0, profit_margin))
        else:
            profitability_rate = 0.0

        # Duration: only meaningful when busy
        service_type = getattr(machine, "current_service_type", "") or ""
        loads = 1  # default; actual loads not stored on machine
        duration = cls.get_duration(service_type, loads) if is_busy else 0

        return {
            "duration_minutes":       duration,
            "profitability_rate":     round(profitability_rate, 2),
            "net_profit":             round(gross, 2),
            "electricity_cost":       overhead["electricity_cost"],
            "water_cost":             overhead["water_cost"],
            "detergent_cost":         overhead["detergent_cost"],
            "total_overhead":         overhead["total_overhead"],
            "is_active_consumption":  is_busy,
        }
