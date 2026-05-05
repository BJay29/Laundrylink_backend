from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from fastapi import HTTPException, status
import random

def get_all_machines(db: Session, shop_id: int = None):
    """
    Retrieves all machines. Filters by shop if shop_id is provided.
    Dahil gusto nating i-fix ang data, kung walang shop_id na binigay, 
    mag-fo-force filter tayo sa shop_id=1.
    """
    # Force default shop_id to 1 if not provided to avoid null issues
    target_shop_id = shop_id if shop_id is not None else 1
    
    query = db.query(Machine).filter(Machine.shop_id == target_shop_id)
        
    machines = query.order_by(
        Machine.machine_type.desc(), # 'Washer' (W) bago 'Dryer' (D)
        Machine.machine_number.asc()
    ).all()

    # AUTO-UPDATE METRICS & NULL FIX: 
    # Habang nilo-loop ang machines, sisiguraduhin nating hindi null ang shop_id nila.
    for machine in machines:
        if machine.shop_id is None:
            machine.shop_id = 1
            
        if machine.total_cycles > 0:
            update_performance_metrics(db, machine.id, target_shop_id, commit=False)
    
    db.commit() # Isang commit lang para sa lahat ng updates at data fixes
    return machines

def get_machine_by_id(db: Session, machine_id: int, shop_id: int = None):
    """
    Retrieves a single machine's details. 
    Validation ensures the machine exists and belongs to the correct shop.
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
    return machine

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int):
    """
    Manually adds a new machine via the 'Add Machine' modal.
    Initializes all operational metrics to zero.
    """
    # Siguraduhing may shop_id na pumasok, kung wala, default to 1
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
    Permanently removes a machine from the database.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted successfully"}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles the maintenance state. Blocked units cannot be selected in Booking Modal.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    # Toggle logic
    if machine.status == "Maintenance":
        machine.status = "Available"
    else:
        # Kapag ginawang Maintenance, ititigil ang countdown
        machine.status = "Maintenance"
        machine.remaining_time = 0 

    db.commit()
    db.refresh(machine)
    return machine

def update_performance_metrics(db: Session, machine_id: int, shop_id: int, commit: bool = True):
    """
    Generates realistic cost data per cycle. 
    Internal logic for Machine Hub's performance tracking.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.total_cycles > 0:
        if machine.machine_type == "Washer":
            # Realistic consumption for Washers (PHP)
            machine.avg_detergent = round(random.uniform(12.00, 18.00), 2)
            machine.avg_electricity = round(random.uniform(8.00, 12.00), 2)
            machine.avg_water = round(random.uniform(4.00, 7.00), 2)
        else: 
            # Dryers mainly consume high electricity
            machine.avg_detergent = 0.00
            machine.avg_electricity = round(random.uniform(18.00, 28.00), 2)
            machine.avg_water = 0.00

    if commit:
        db.commit()
        db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Standard auto-setup: 6 Washers and 6 Dryers.
    Prevents duplicate setup for the same shop.
    """
    # Kung walang shop_id, default sa 1
    final_shop_id = shop_id if shop_id else 1
    
    existing_check = db.query(Machine).filter(Machine.shop_id == final_shop_id).first()
    if existing_check:
        return {"message": "Shop hardware is already initialized"}

    machines_to_add = []
    
    # Batch create Washers 1-6
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
    
    # Batch create Dryers 1-6
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