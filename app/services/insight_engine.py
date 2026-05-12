from sqlalchemy.orm import Session
from app.models import Machine, Booking
from sqlalchemy import func
import logging

# Setup basic logging to replace print statements
logger = logging.getLogger(__name__)

def generate_operational_insight(db: Session):
    """
    Analyzes current machine statuses and historical booking data 
    to provide real-time financial insights and actionable suggestions.
    """
    try:
        # 1. Count how many machines are currently out of service
        offline_count = db.query(Machine).filter(Machine.status == 'MAINTENANCE').count()
        
        # 2. Get total number of machines to calculate capacity percentage
        total_machines = db.query(Machine).count() or 1 # Avoid division by zero
        
        if offline_count > 0:
            # 3. Calculate Average Revenue per booking to estimate loss
            # We take the average of 'total_price' from all completed bookings
            avg_revenue_per_booking = db.query(func.avg(Booking.total_price)).scalar() or 0
            
            # 4. Impact Calculation Logic:
            # Assuming an average machine handles about 6 loads per day.
            # Loss = (Number of Offline Machines) * (Avg Price per Load) * (Estimated Loads per Day)
            estimated_loads_per_day = 6
            daily_loss_estimate = offline_count * avg_revenue_per_booking * estimated_loads_per_day
            
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

        # Default response when everything is running smoothly
        return {
            "hasIssue": False,
            "type": "OPTIMIZED",
            "problemMessage": "All systems are operational. Machine allocation is currently at peak efficiency.",
            "impactDetail": "Current service income is optimized across all available units.",
            "suggestions": [
                "Consider a 'Happy Hour' discount if machine idle time increases.",
                "Monitor water and energy trends to further optimize utility costs."
            ]
        }

    except Exception as e:
        logger.error(f"Error generating operational insights: {str(e)}")
        return {
            "hasIssue": False,
            "problemMessage": "Syncing insights...",
            "impactDetail": "Calculation temporarily unavailable.",
            "suggestions": []
        }