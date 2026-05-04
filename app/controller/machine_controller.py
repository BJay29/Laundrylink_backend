from sqlalchemy.orm import Session
from app.models import Machine
from fastapi import HTTPException, status
import random

def get_all_machines(db: Session, shop_id: int):
    """
    Retrieves all 12 machines for a specific shop.
    Ordered by type (Washers first) and then number (1-6) to maintain grid consistency.
    """
    return db.query(Machine).filter(Machine.shop_id == shop_id).order_by(
        Machine.machine_type.desc(), 
        Machine.machine_number.asc()
    ).all()

def get_machine_by_id(db: Session, machine_id: int, shop_id: int):
    """
    Retrieves a single machine's details or raises a 404 error if not found.
    """
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.shop_id == shop_id).first()
    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Machine hardware unit not found"
        )
    return machine

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles the maintenance state of a machine.
    When set to Maintenance, the unit is blocked from being selected in the Booking Modal.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        # Return to Available state
        machine.status = "Available"
        machine.remaining_time = 0
    else:
        # Set to Maintenance state
        machine.status = "Maintenance"
        machine.remaining_time = 0 # Timers are irrelevant during maintenance

    db.commit()
    db.refresh(machine)
    return machine

def update_machine_metrics(db: Session, machine_id: int, shop_id: int):
    """
    Updates profitability and efficiency scores for a specific machine.
    Reflects metrics used in the Dashboard and Machine Hub profitability bars.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    # Logic: Profitability based on cycle count vs an efficiency target of 500 cycles
    target_efficiency_limit = 500
    calculated_score = (machine.total_cycles / target_efficiency_limit) * 100
    machine.profitability_score = min(round(calculated_score, 2), 100.0)
    
    # Utility overhead configuration
    # Washers typically incur higher water/power costs per cycle compared to dryers
    if machine.machine_type == "Washer":
        machine.estimated_cost_per_cycle = 45.0 
    else:
        machine.estimated_cost_per_cycle = 52.0

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Automatically populates a new shop with the required 12-machine setup.
    Includes 6 Washers and 6 Dryers with default profitability metrics.
    """
    # Check if the shop already has machines to prevent duplicates
    existing_check = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing_check:
        return {"message": "Shop hardware is already initialized"}

    machines_to_add = []
    
    # Generate 6 Washer Units
    for i in range(1, 7):
        machines_to_add.append(
            Machine(
                machine_type="Washer", 
                machine_number=i, 
                status="Available", 
                total_cycles=0,
                profitability_score=0.0,
                remaining_time=0,
                estimated_cost_per_cycle=45.0,
                shop_id=shop_id
            )
        )
    
    # Generate 6 Dryer Units
    for i in range(1, 7):
        machines_to_add.append(
            Machine(
                machine_type="Dryer", 
                machine_number=i, 
                status="Available", 
                total_cycles=0,
                profitability_score=0.0,
                remaining_time=0,
                estimated_cost_per_cycle=50.0,
                shop_id=shop_id
            )
        )

    db.add_all(machines_to_add)
    db.commit()
    return {"message": "Standard 12-unit configuration successfully deployed to shop"}