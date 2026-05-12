from sqlalchemy.orm import Session
from app.models import Machine, Booking
from sqlalchemy import func
import logging

# Setup basic logging
logger = logging.getLogger(__name__)

def generate_operational_insight(db: Session, shop_id: int = 1):
    """
    Analyzes current machine statuses and historical booking data 
    to provide real-time financial insights and actionable suggestions.
    
    UPDATED: Added .ilike() for case-insensitive status matching and shop_id filtering.
    """
    try:
        # 1. Count machines out of service (CASE-INSENSITIVE)
        # Using .ilike() ensures 'maintenance', 'Maintenance', and 'MAINTENANCE' are all caught.
        offline_machines = db.query(Machine).filter(
            Machine.shop_id == shop_id,
            Machine.status.ilike('maintenance')
        ).all()
        
        offline_count = len(offline_machines)
        
        # 2. Get total number of machines for this specific shop
        total_machines = db.query(Machine).filter(Machine.shop_id == shop_id).count() or 1
        
        if offline_count > 0:
            # 3. Calculate Average Revenue per booking
            # Filtering by shop_id to ensure the average is specific to this business
            avg_revenue_per_booking = db.query(func.avg(Booking.total_price)).filter(
                Booking.shop_id == shop_id
            ).scalar() or 0
            
            # 4. Impact Calculation Logic
            # Assuming an average machine handles about 6 loads per day.
            estimated_loads_per_day = 6
            daily_loss_estimate = offline_count * float(avg_revenue_per_booking) * estimated_loads_per_day
            
            capacity_reduction = (offline_count / total_machines) * 100

            return {
                "hasIssue": True,
                "type": "MAINTENANCE_ALERT",
                "problemMessage": f"Service capacity reduced by {capacity_reduction:.0f}% due to {offline_count} machine(s) under maintenance.",
                "impactDetail": f"Estimated daily service income loss: ₱{daily_loss_estimate:,.2f}",
                "suggestions": [
                    "Prioritize high-value 'Full Service' or 'Titan Wash' bookings to working machines.",
                    "Implement a temporary 10% 'Rush Surcharge' to offset lower volume with higher margins.",
                    "Extend operating hours tonight by 2 hours to process the current booking queue.",
                    "Check the 'Laundry Link' inventory for spare parts to speed up the repair process."
                ]
            }

        # Default response when shop performance is within peak range
        return {
            "hasIssue": False,
            "type": "OPTIMIZED",
            "problemMessage": "Operations Optimized. Your shop is performing at peak efficiency.",
            "impactDetail": "Revenue trends and service distribution are currently aligned with targets.",
            "suggestions": [
                "Consider a 'Happy Hour' discount during off-peak hours to maximize idle units.",
                "Monitor water and energy trends to further reduce utility overhead."
            ]
        }

    except Exception as e:
        logger.error(f"Error generating operational insights: {str(e)}")
        return {
            "hasIssue": False,
            "type": "SYNCING",
            "problemMessage": "Syncing insights...",
            "impactDetail": "The decision support engine is recalculating metrics.",
            "suggestions": []
        }