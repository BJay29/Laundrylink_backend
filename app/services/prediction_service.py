from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models import Setting

class PredictionService:
    """
    Core logic for calculating utility consumption and machine profitability.
    Dynamically fetches rates from the database with fallbacks for Naga City utility averages.
    """

    # --- FALLBACK NAGA CITY UTILITY RATES (Used if DB settings are missing) ---
    DEFAULT_ELEC_RATE = 8.83   # CASURECO II average
    DEFAULT_WATER_RATE = 37.90  # MNWD rate
    DEFAULT_DETERGENT = 12.75 

    # --- HARDWARE SPECIFICATIONS ---
    WATTS_WASHER = 1200 
    WATTS_DRYER = 5000  

    # --- DEFAULT DURATIONS (Minutes) ---
    MACHINE_DURATIONS = {
        "washer": 45,
        "dryer":  40,
    }

    @classmethod
    def get_settings(cls, db: Session, shop_id: int) -> Dict[str, float]:
        """
        Fetches dynamic rates from the Setting table for a specific shop.
        Ensures calculations match what the user configured in the UI.
        """
        settings = db.query(Setting).filter(Setting.shop_id == shop_id).first()
        if not settings:
            return {
                "elec": cls.DEFAULT_ELEC_RATE,
                "water": cls.DEFAULT_WATER_RATE,
                "detergent": cls.DEFAULT_DETERGENT
            }
        
        return {
            "elec": settings.electricity_rate or cls.DEFAULT_ELEC_RATE,
            "water": settings.water_rate or cls.DEFAULT_WATER_RATE,
            "detergent": settings.detergent_cost_per_load or cls.DEFAULT_DETERGENT
        }

    @classmethod
    def calculate_cycle_cost(
        cls, 
        machine_type: str, 
        duration_minutes: int, 
        rates: Optional[Dict[str, float]] = None
    ) -> Dict[str, float]:
        """
        Calculates real-time consumption costs based on duration and utility rates.
        Formula: (Watts * Hours / 1000) * Rate.
        """
        m_type = machine_type.lower().strip()
        hours = duration_minutes / 60
        
        # Use provided rates or fall back to defaults
        elec_rate = rates["elec"] if rates else cls.DEFAULT_ELEC_RATE
        water_rate = rates["water"] if rates else cls.DEFAULT_WATER_RATE
        detergent_rate = rates["detergent"] if rates else cls.DEFAULT_DETERGENT

        # 1. Electricity Calculation
        watts = cls.WATTS_WASHER if m_type == "washer" else cls.WATTS_DRYER
        elec_consumed = (watts * hours) / 1000
        elec_cost = elec_consumed * elec_rate

        # 2. Water Calculation (Washers only)
        # Assuming average 50L (0.05 m3) per standard cycle
        water_cost = 0.0
        if m_type == "washer":
            water_cost = 0.05 * water_rate

        # 3. Detergent Calculation (Washers only)
        detergent_cost = detergent_rate if m_type == "washer" else 0.0

        return {
            "electricity": round(elec_cost, 2),
            "water": round(water_cost, 2),
            "detergent": round(detergent_cost, 2),
            "total": round(elec_cost + water_cost + detergent_cost, 2)
        }

    @classmethod
    def get_machine_runtime(cls, machine_type: str, service_type: str) -> int:
        """
        Determines hardware runtime based on service intensity.
        Heavier items like Comforters require longer cycles, increasing utility overhead.
        """
        m_type = machine_type.lower().strip()
        s_type = (service_type or "").lower().strip()

        # Check for intensive keywords to adjust duration
        intensive_keywords = ["comforter", "titan", "heavy", "bulk", "rush"]
        if any(kw in s_type for kw in intensive_keywords):
            return 60 if m_type == "washer" else 50
        
        return cls.MACHINE_DURATIONS.get(m_type, 45)

    @classmethod
    def calculate_metrics(cls, machine: Any, is_busy: bool = False) -> Dict[str, Any]:
        """
        Aggregates machine performance for the Dashboard.
        Calculates Profitability Rate based on accumulated lifetime records.
        """
        # Fetch accumulated values from Machine SQLAlchemy model
        acc_elec = getattr(machine, "accumulated_electricity", 0.0) or 0.0
        acc_water = getattr(machine, "accumulated_water", 0.0) or 0.0
        acc_detergent = getattr(machine, "accumulated_detergent", 0.0) or 0.0
        accumulated_net = getattr(machine, "net_profit_accumulated", 0.0) or 0.0
        
        total_overhead = acc_elec + acc_water + acc_detergent

        # --- REVENUE ESTIMATION ---
        # Machine Revenue = Net Profit + Overhead Expenses
        total_revenue = accumulated_net + total_overhead
        
        # --- PROFITABILITY RATIO ---
        # Formula: (Net Profit / Total Revenue) * 100
        if total_revenue > 0:
            profit_margin = (accumulated_net / total_revenue) * 100
            # Clamp value between 0% and 100% to prevent logical errors in UI
            profitability_rate = max(0.0, min(100.0, profit_margin))
        else:
            profitability_rate = 0.0

        # --- REAL-TIME TELEMETRY ---
        s_type = getattr(machine, "current_service_type", "") or ""
        m_type = getattr(machine, "machine_type", "washer")
        duration = cls.get_machine_runtime(m_type, s_type) if is_busy else 0

        return {
            "duration_minutes": duration,
            "profitability_rate": round(profitability_rate, 2),
            "net_profit": round(accumulated_net, 2),
            "electricity_cost": round(acc_elec, 2),
            "water_cost": round(acc_water, 2),
            "detergent_cost": round(acc_detergent, 2),
            "total_overhead": round(total_overhead, 2)
        }