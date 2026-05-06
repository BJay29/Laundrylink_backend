from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status

def get_all_machines(db: Session, shop_id: int = None):
    """
    Retrieves all machines for a specific shop. 
    Includes real-time performance metrics calculation based on independent machine data.
    """
    target_shop_id = shop_id if shop_id is not None else 1
    
    query = db.query(Machine).filter(Machine.shop_id == target_shop_id)
    
    machines = query.order_by(
        Machine.machine_type.desc(), 
        Machine.machine_number.asc()
    ).all()

    for machine in machines:

        if machine.shop_id is None:
            machine.shop_id = 1
            
        # INDEPENDENT TRACKING: Ang PredictionService ay gagamit ng unique rates 
        # at cycle count ng mismong machine instance na ito.
        is_busy = machine.status == "Busy"
        machine.metrics = PredictionService.calculate_metrics(machine, is_busy)
    
    db.commit() 
    return machines

def get_machine_by_id(db: Session, machine_id: int, shop_id: int = None):
    """
    Retrieves a single machine's details with its specific calculated metrics.
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
    
    is_busy = machine.status == "Busy"
    machine.metrics = PredictionService.calculate_metrics(machine, is_busy)
    
    return machine

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int):
    """
    Manually creates a new machine unit.
    Initializes with specific consumption rates to maintain the cost hierarchy.
    """
    final_shop_id = shop_id if shop_id else 1
    
    # Defaults base sa realistic laundry data
    # Washer usually uses more water, Dryer uses more electricity
    is_washer = machine_data.machine_type.lower() == "washer"
    
    new_machine = Machine(
        machine_type=machine_data.machine_type,
        machine_number=machine_data.machine_number,
        status="Available",
        total_cycles=0, # Independent start
        avg_electricity=1.2 if is_washer else 3.5, 
        avg_water=60.0 if is_washer else 0.0,      
        avg_detergent=45.0 if is_washer else 0.0, 
        remaining_time=0,
        shop_id=final_shop_id
    )
    db.add(new_machine)
    db.commit()
    db.refresh(new_machine)
    return new_machine

def delete_machine(db: Session, machine_id: int, shop_id: int):
    """
    Permanently removes a machine record.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted"}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Updates the machine status to/from 'Maintenance'.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        machine.status = "Available"
    else:
        machine.status = "Maintenance"
        machine.remaining_time = 0 

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Standard deployment of 12 units (6W, 6D).
    Sets up independent efficiency rates per type to ensure realistic dashboard metrics.
    """
    final_shop_id = shop_id if shop_id else 1
    
    existing_check = db.query(Machine).filter(Machine.shop_id == final_shop_id).first()
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
                total_cycles=0,
                avg_electricity=1.2, # kWh
                avg_water=60.0,       # L
                avg_detergent=50.0,   # ml
                shop_id=final_shop_id,
                remaining_time=0
            )
        )
    
    # Generate 6 Dryers
    for i in range(1, 7):
        machines_to_add.append(
            Machine(
                machine_type="Dryer", 
                machine_number=i, 
                status="Available", 
                total_cycles=0,
                avg_electricity=3.0, 
                avg_water=0.0,
                avg_detergent=0.0,
                shop_id=final_shop_id,
                remaining_time=0
            )
        )

    db.add_all(machines_to_add)
    db.commit()
    return {"message": "Standard configuration (6W, 6D) deployed with realistic rates"}