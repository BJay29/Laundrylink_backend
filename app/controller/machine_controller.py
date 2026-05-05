from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from fastapi import HTTPException, status
import random

def get_all_machines(db: Session, shop_id: int = None):
    """
    Retrieves all machines. If shop_id is provided, filters by shop.
    Ordered by type (Washers first) and then by machine number.
    """
    query = db.query(Machine)
    
    # Kung may shop_id, i-filter lang ang para sa shop na iyon
    if shop_id:
        query = query.filter(Machine.shop_id == shop_id)
        
    return query.order_by(
        Machine.machine_type.desc(),
        Machine.machine_number.asc()
    ).all()

def get_machine_by_id(db: Session, machine_id: int, shop_id: int = None):
    """
    Retrieves a single machine's details. 
    Validation ensures the machine exists and belongs to the correct shop if provided.
    """
    query = db.query(Machine).filter(Machine.id == machine_id)
    
    if shop_id:
        query = query.filter(Machine.shop_id == shop_id)
        
    machine = query.first()
    
    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Machine hardware unit not found or access denied"
        )
    return machine

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int):
    """
    Manually adds a new machine via the 'Add Machine' modal.
    Initializes all operational metrics to zero for new units.
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
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted successfully"}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles the maintenance state of a machine.
    Blocked units cannot be assigned to new bookings.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        machine.status = "Available"
    else:
        machine.status = "Maintenance"
    
    # Siguraduhin na 0 ang remaining time kapag binago ang status
    machine.remaining_time = 0 

    db.commit()
    db.refresh(machine)
    return machine

def update_performance_metrics(db: Session, machine_id: int, shop_id: int):
    """
    Generates realistic cost data per cycle based on machine type.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.total_cycles > 0:
        if machine.machine_type == "Washer":
            # Costs for Washers (Detergent, Elec, Water)
            machine.avg_detergent = round(random.uniform(15.00, 25.00), 2)
            machine.avg_electricity = round(random.uniform(10.00, 15.00), 2)
            machine.avg_water = round(random.uniform(5.00, 10.00), 2)
        else: 
            # Dryers only consume electricity
            machine.avg_detergent = 0.00
            machine.avg_electricity = round(random.uniform(20.00, 30.00), 2)
            machine.avg_water = 0.00

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Auto-populates a shop with 6 Washers and 6 Dryers.
    Prevents duplicate initialization.
    """
    existing_check = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing_check:
        return {"message": "Shop hardware is already initialized"}

    machines_to_add = []
    
    # Generate 6 Washers
    for i in range(1, 7):
        machines_to_add.append(
            Machine(
                machine_type="Washer", 
                machine_number=i, 
                status="Available", 
                shop_id=shop_id
            )
        )
    
    # Generate 6 Dryers
    for i in range(1, 7):
        machines_to_add.append(
            Machine(
                machine_type="Dryer", 
                machine_number=i, 
                status="Available", 
                shop_id=shop_id
            )
        )

    db.add_all(machines_to_add)
    db.commit()
    return {"message": "Standard 12-unit configuration successfully deployed to shop"}