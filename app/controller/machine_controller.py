from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from fastapi import HTTPException, status
import random

def get_all_machines(db: Session, shop_id: int):
    """
    Retrieves all machines for a specific shop.
    Ordered by type (Washers first) and then number to maintain consistency in the Machine Hub table.
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

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int):
    """
    Manually adds a new machine to the shop. 
    Triggered by the 'Add Machine' button in the Machine Hub (image_b6637f.png).
    """
    new_machine = Machine(
        machine_type=machine_data.machine_type,
        machine_number=machine_data.machine_number,
        status="Available",
        total_cycles=0,
        avg_detergent=0.0,
        avg_electricity=0.0,
        avg_water=0.0,
        remaining_time=0,
        shop_id=shop_id
    )
    db.add(new_machine)
    db.commit()
    db.refresh(new_machine)
    return new_machine

def delete_machine(db: Session, machine_id: int, shop_id: int):
    """
    Permanently removes a machine from the shop.
    Triggered by the red delete icon in the Machine Hub table.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted successfully"}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles the maintenance state of a machine.
    Units in 'Maintenance' are blocked from selection in the Booking Modal.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        machine.status = "Available"
        machine.remaining_time = 0
    else:
        machine.status = "Maintenance"
        machine.remaining_time = 0 

    db.commit()
    db.refresh(machine)
    return machine

def update_performance_metrics(db: Session, machine_id: int, shop_id: int):
    """
    Calculates average resource costs per cycle for the Machine Hub table columns.
    Uses randomized mock data for costs to simulate operational intelligence.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.total_cycles > 0:
        # Simulate cost calculation (In a real app, these would come from utility sensors/bills)
        if machine.machine_type == "Washer":
            machine.avg_detergent = round(random.uniform(0.15, 0.25), 2)
            machine.avg_electricity = round(random.uniform(0.45, 0.60), 2)
            machine.avg_water = round(random.uniform(0.30, 0.40), 2)
        else: # Dryers don't use detergent or water
            machine.avg_detergent = 0.00
            machine.avg_electricity = round(random.uniform(0.50, 0.70), 2)
            machine.avg_water = 0.00

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Default setup for a new shop. Deploys 6 Washers and 6 Dryers.
    Used for initial hardware configuration.
    """
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
                avg_detergent=0.0,
                avg_electricity=0.0,
                avg_water=0.0,
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
                avg_detergent=0.0,
                avg_electricity=0.0,
                avg_water=0.0,
                shop_id=shop_id
            )
        )

    db.add_all(machines_to_add)
    db.commit()
    return {"message": "Standard 12-unit configuration successfully deployed to shop"}