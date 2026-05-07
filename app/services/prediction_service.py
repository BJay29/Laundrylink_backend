from typing import Dict, Any

class PredictionService:
    """
    Single source of truth for machine cost calculations and profitability metrics.
    Updated for Naga City, Camarines Sur utility rates (2026).
    
    Resource Rates:
    - Electricity: ₱8.83/kWh (CASURECO II)
    - Water: ₱37.90/m3 (MNWD Commercial Rate)
    - Detergent: ₱12.75 (Fixed per Washer cycle)
    """

    # --- NAGA CITY UTILITY RATES ---
    ELEC_RATE_KWH = 8.83  
    WATER_RATE_CUM = 37.90  
    DETERGENT_FIXED = 12.75

    # --- HARDWARE SPECIFICATIONS (Wattage) ---
    # High wattage for Dryers ensures Electricity is the dominant cost.
    WATTS_WASHER = 1200 
    WATTS_DRYER = 5000  

    # --- DEFAULT HARDWARE DURATIONS (Minutes) ---
    MACHINE_DURATIONS = {
        "washer": 45,
        "dryer":  40,
    }

    @classmethod
    def calculate_cycle_cost(cls, machine_type: str, duration_minutes: int) -> Dict[str, float]:
        """
        Calculates utility consumption based on duration and Naga City rates.
        Electricity is calculated as: (Watts * Hours / 1000) * Rate.
        """
        m_type = machine_type.lower().strip()
        hours = duration_minutes / 60
        
        # 1. Electricity Calculation
        watts = cls.WATTS_WASHER if m_type == "washer" else cls.WATTS_DRYER
        elec_consumed = (watts * hours) / 1000
        elec_cost = elec_consumed * cls.ELEC_RATE_KWH

        # 2. Water Calculation (Washers only)
        # Based on average 50L consumption (0.05 cubic meters) per wash
        water_cost = 0.0
        if m_type == "washer":
            water_cost = 0.05 * cls.WATER_RATE_CUM

        # 3. Detergent Calculation (Washers only)
        detergent_cost = cls.DETERGENT_FIXED if m_type == "washer" else 0.0

        return {
            "electricity": round(elec_cost, 2),
            "water": round(water_cost, 2),
            "detergent": detergent_cost,
            "total": round(elec_cost + water_cost + detergent_cost, 2)
        }

    @classmethod
    def get_machine_runtime(cls, machine_type: str, service_type: str) -> int:
        """
        Determines hardware runtime based on the intensity of the service.
        Heavy loads like Comforters increase the duration, which increases utility cost.
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
        Uses accumulated values from the database to reflect lifetime costs.
        """
        # Retrieve accumulated costs from the Machine model (updated in machine_controller)
        acc_elec = getattr(machine, "accumulated_electricity", 0.0) or 0.0
        acc_water = getattr(machine, "accumulated_water", 0.0) or 0.0
        acc_detergent = getattr(machine, "accumulated_detergent", 0.0) or 0.0
        
        total_overhead = acc_elec + acc_water + acc_detergent
        accumulated_net = getattr(machine, "net_profit_accumulated", 0.0) or 0.0

        # --- PROFITABILITY RATIO ---
        # Calculation based on accumulated profit vs total overhead
        if (accumulated_net + total_overhead) > 0:
            profit_margin = (accumulated_net / (accumulated_net + total_overhead)) * 100
            profitability_rate = max(0.0, min(100.0, profit_margin))
        else:
            profitability_rate = 0.0

        # --- REAL-TIME TELEMETRY ---
        service_type = getattr(machine, "current_service_type", "") or ""
        # Duration is only displayed if the machine is currently 'Busy'
        duration = cls.get_machine_runtime(machine.machine_type, service_type) if is_busy else 0

        return {
            "duration_minutes":       duration,
            "profitability_rate":     round(profitability_rate, 2),
            "net_profit":             round(accumulated_net, 2),
            "electricity_cost":       round(acc_elec, 2),
            "water_cost":             round(acc_water, 2),
            "detergent_cost":         round(acc_detergent, 2),
            "total_overhead":         round(total_overhead, 2)
        }