from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from fastapi import HTTPException, status
import random

def get_all_machines(db: Session, shop_id: int):
    """
    Retrieves all machines associated with a specific shop.
    Ordered by type (Washers first) and then by machine number to maintain 
    the consistent layout required for the Machine Hub table.
    """
    return db.query(Machine).filter(Machine.shop_id == shop_id).order_by(
        Machine.machine_type.desc(), 
        Machine.machine_number.asc()
    ).all()

def get_machine_by_id(db: Session, machine_id: int, shop_id: int):
    """
    Retrieves a single machine's details. 
    Includes shop_id validation to ensure users can only access their own hardware.
    Raises a 404 error if the unit is not found.
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
    Manually adds a new machine to the database. 
    Triggered by the 'Add Machine' modal in the Machine Hub.
    Initializes all operational metrics (Detergent, Elec, Water) to 0.0.
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
    Permanently removes a machine from the database.
    Triggered by the trash icon in the Machine Hub table.
    This action will automatically reflect in the Monitoring Grid as the unit is removed.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted successfully"}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles the maintenance state of a machine.
    Units marked as 'Maintenance' are logically blocked from being assigned 
    to new bookings in the Service Terminal.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        machine.status = "Available"
        machine.remaining_time = 0
    else:
        # Forcing remaining_time to 0 when entering maintenance to clear the UI timer
        machine.status = "Maintenance"
        machine.remaining_time = 0 

    db.commit()
    db.refresh(machine)
    return machine

def update_performance_metrics(db: Session, machine_id: int, shop_id: int):
    """
    Updates average resource costs per cycle for the Machine Hub table columns.
    Simulates operational data by generating realistic cost ranges.
    Dryers are set to 0.0 for water and detergent as they only consume electricity.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.total_cycles > 0:
        if machine.machine_type == "Washer":
            # Simulated washer costs per cycle
            machine.avg_detergent = round(random.uniform(0.15, 0.25), 2)
            machine.avg_electricity = round(random.uniform(0.45, 0.60), 2)
            machine.avg_water = round(random.uniform(0.30, 0.40), 2)
        else: 
            # Dryers don't use detergent or water, higher electricity usage
            machine.avg_detergent = 0.00
            machine.avg_electricity = round(random.uniform(0.50, 0.70), 2)
            machine.avg_water = 0.00

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Pre-configures a new shop with a standard 12-unit layout (6 Washers, 6 Dryers).
    Used to quickly populate the system for a new owner without manual entry.
    Checks for existing machines first to prevent duplicate initialization.
    """
    existing_check = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing_check:
        return {"message": "Shop hardware is already initialized"}

    machines_to_add = []
    
    # Batch Generate 6 Washer Units
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
                remaining_time=0,
                shop_id=shop_id
            )
        )
    
    # Batch Generate 6 Dryer Units
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
                remaining_time=0,
                shop_id=shop_id
            )
        )

    db.add_all(machines_to_add)
    db.commit()
    return {"message": "Standard 12-unit configuration successfully deployed to shop"}