from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status
import random

def get_all_machines(db: Session, shop_id: int = None):
    """
    Retrieves all machines for a specific shop. 
    Defaults to shop_id=1 if no ID is provided to maintain data consistency.
    Includes real-time performance metrics calculation.
    """
    target_shop_id = shop_id if shop_id is not None else 1
    
    query = db.query(Machine).filter(Machine.shop_id == target_shop_id)
        
    machines = query.order_by(
        Machine.machine_type.desc(), # 'Washer' (W) comes before 'Dryer' (D)
        Machine.machine_number.asc()
    ).all()

    # Apply data fixes and attach real-time prediction metrics
    for machine in machines:
        # Data integrity: ensure no machine has a null shop_id
        if machine.shop_id is None:
            machine.shop_id = 1
            
        # Attach calculated metrics based on the PredictionService logic
        # This replaces the old random uniform calculation
        is_busy = machine.status == "Busy"
        machine.metrics = PredictionService.calculate_metrics(machine.total_cycles, is_busy)
    
    # Commit any automatic data fixes (like shop_id adjustments)
    db.commit() 
    return machines

def get_machine_by_id(db: Session, machine_id: int, shop_id: int = None):
    """
    Retrieves a single machine's details. 
    Validates ownership by checking the target_shop_id.
    """
    target_shop_id = shop_id if shop_id is not None else 1
    
    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == target_shop_id
    ).first()
    
    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Machine hardware unit not found or access denied"
        )
    
    # Attach metrics for the individual machine response
    is_busy = machine.status == "Busy"
    machine.metrics = PredictionService.calculate_metrics(machine.total_cycles, is_busy)
    
    return machine

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int):
    """
    Manually creates a new machine unit via the administrative dashboard.
    Initializes all operational counters and time to zero.
    """
    final_shop_id = shop_id if shop_id else 1
    
    new_machine = Machine(
        machine_type=machine_data.machine_type,
        machine_number=machine_data.machine_number,
        status="Available",
        total_cycles=0,
        avg_detergent=0.0,
        avg_electricity=0.0,
        avg_water=0.0,
        remaining_time=0,
        shop_id=final_shop_id
    )
    db.add(new_machine)
    db.commit()
    db.refresh(new_machine)
    return new_machine

def delete_machine(db: Session, machine_id: int, shop_id: int):
    """
    Permanently removes a machine record from the database.
    Used for hardware decommissioning.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted successfully"}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Updates the machine status to/from 'Maintenance'.
    Machines in maintenance cannot be selected for new laundry bookings.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        machine.status = "Available"
    else:
        # Reset remaining time to stop any active countdowns during repair
        machine.status = "Maintenance"
        machine.remaining_time = 0 

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Performs initial setup for new shops by deploying 6 Washers and 6 Dryers.
    Includes duplicate check to prevent overwriting existing hardware configurations.
    """
    final_shop_id = shop_id if shop_id else 1
    
    existing_check = db.query(Machine).filter(Machine.shop_id == final_shop_id).first()
    if existing_check:
        return {"message": "Shop hardware is already initialized"}

    machines_to_add = []
    
    # Generate standard Washer units (1-6)
    for i in range(1, 7):
        machines_to_add.append(
            Machine(
                machine_type="Washer", 
                machine_number=i, 
                status="Available", 
                shop_id=final_shop_id,
                remaining_time=0
            )
        )
    
    # Generate standard Dryer units (1-6)
    for i in range(1, 7):
        machines_to_add.append(
            Machine(
                machine_type="Dryer", 
                machine_number=i, 
                status="Available", 
                shop_id=final_shop_id,
                remaining_time=0
            )
        )

    db.add_all(machines_to_add)
    db.commit()
    return {"message": "Standard 12-unit configuration (6W, 6D) deployed successfully"}