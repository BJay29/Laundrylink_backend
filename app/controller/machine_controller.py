from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from fastapi import HTTPException, status
import random

def get_all_machines(db: Session, shop_id: int):
    """
    Retrieves all machines associated with a specific shop.
    Ordered by type (Washers first) and then by machine number to maintain 
    the consistent layout required for the Machine Hub table and Monitoring Grid.
    """
    return db.query(Machine).filter(Machine.shop_id == shop_id).order_by(
        Machine.machine_type.desc(),
        Machine.machine_number.asc()
    ).all()

def get_machine_by_id(db: Session, machine_id: int, shop_id: int):
    """
    Retrieves a single machine's details with shop ownership validation.
    Ensures users can only access or modify hardware belonging to their shop.
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
    Permanently removes a machine, triggered by the Machine Hub table actions.
    This change is reflected immediately in the Monitoring Grid layout.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted successfully"}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles the maintenance state of a machine.
    Blocked units cannot be assigned to new bookings in the Service Terminal.
    Clears remaining_time to ensure the UI timer disappears during maintenance.
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
    Updates resource costs per cycle shown in the Machine Hub table columns.
    Generates realistic cost data based on machine type.
    Washers consume water/detergent/elec; Dryers only consume electricity.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.total_cycles > 0:
        if machine.machine_type == "Washer":
            # Costs per cycle for Washers (Detergent, Elec, Water)
            machine.avg_detergent = round(random.uniform(15.00, 25.00), 2)
            machine.avg_electricity = round(random.uniform(10.00, 15.00), 2)
            machine.avg_water = round(random.uniform(5.00, 10.00), 2)
        else: 
            # Dryers have 0 water/detergent cost but higher electricity usage
            machine.avg_detergent = 0.00
            machine.avg_electricity = round(random.uniform(20.00, 30.00), 2)
            machine.avg_water = 0.00

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Auto-populates a new shop with the standard 12-unit layout (6 Washers, 6 Dryers).
    Prevents duplicate initialization if hardware is already registered.
    Essential for the initial setup shown in your Machine Hub dashboard.
    """
    existing_check = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing_check:
        return {"message": "Shop hardware is already initialized"}

    machines_to_add = []
    
    # Generate 6 Washer Units (W1 to W6)
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
    
    # Generate 6 Dryer Units (D1 to D6)
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