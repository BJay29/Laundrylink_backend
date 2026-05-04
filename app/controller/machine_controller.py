from sqlalchemy.orm import Session
from app.models import Machine
from fastapi import HTTPException
import random # Temporary for mock profitability if real data is missing

def get_all_machines(db: Session, shop_id: int):
    """
    Retrieves all 12 machines for a specific shop.
    Used to populate the Machine Hub and Real-time Monitoring grid.
    """
    return db.query(Machine).filter(Machine.shop_id == shop_id).order_by(Machine.machine_type.desc(), Machine.machine_number.asc()).all()

def get_machine_by_id(db: Session, machine_id: int, shop_id: int):
    """
    Retrieves a single machine's details.
    """
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.shop_id == shop_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles the maintenance state of a machine.
    If Maintenance is ON: is_available is set to False (blocking it from Booking Modal).
    If Maintenance is OFF: status returns to Available and is_available is True.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        machine.status = "Available"
        machine.is_available = True
    else:
        machine.status = "Maintenance"
        machine.is_available = False # This prevents selection in the booking modal

    db.commit()
    db.refresh(machine)
    return machine

def update_machine_metrics(db: Session, machine_id: int, shop_id: int):
    """
    Calculates and updates profitability metrics for a specific machine.
    Logic follows the layout seen in image_d13564.png.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    # Example logic: Profitability based on cycle count vs a target of 300 cycles
    # In a real scenario, this would involve total_revenue - operating_costs
    target_efficiency = 300
    current_efficiency = (machine.total_cycles / target_efficiency) * 100
    machine.profitability_score = min(round(current_efficiency, 2), 100.0)
    
    # Utility overhead (Estimated cost per cycle)
    # Washers generally have higher water/electricity costs than dryers
    if machine.machine_type == "Washer":
        machine.estimated_cost_per_cycle = 45.0 # matches image_d13564.png examples
    else:
        machine.estimated_cost_per_cycle = 52.0

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Populates a new shop with the standard 12 machines (6 Washers, 6 Dryers).
    Each machine is initialized with base costs for profitability tracking.
    """
    existing = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing:
        return {"message": "Machines already initialized"}

    machines_to_create = []
    
    # Initialize 6 Washers
    for i in range(1, 7):
        machines_to_create.append(
            Machine(
                machine_type="Washer", 
                machine_number=i, 
                status="Available", 
                is_available=True,
                estimated_cost_per_cycle=45.0,
                shop_id=shop_id
            )
        )
    
    # Initialize 6 Dryers
    for i in range(1, 7):
        machines_to_create.append(
            Machine(
                machine_type="Dryer", 
                machine_number=i, 
                status="Available", 
                is_available=True,
                estimated_cost_per_cycle=50.0,
                shop_id=shop_id
            )
        )

    db.add_all(machines_to_create)
    db.commit()
    return {"message": "12 machines initialized successfully with profitability tracking"}