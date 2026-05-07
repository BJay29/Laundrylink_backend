from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status

def get_all_machines(db: Session, shop_id: int = None):
    """
    Retrieves all machines for a specific shop. 
    Calculates real-time performance metrics and profitability percentages before returning.
    """
    # Use provided shop_id or default to 1 for development
    target_shop_id = shop_id if shop_id is not None else 1
    
    # Strictly filter by shop_id to ensure the monitoring hub is accurate
    query = db.query(Machine).filter(Machine.shop_id == target_shop_id)
    
    machines = query.order_by(
        Machine.machine_type.desc(), 
        Machine.machine_number.asc()
    ).all()

    for machine in machines:
        # PredictionService calculates overhead costs based on 
        # the unique consumption rates (electricity, water, detergent) of this unit.
        is_busy = machine.status == "Busy"
        machine.metrics = PredictionService.calculate_metrics(machine, is_busy)

        # --- REAL-TIME PROFITABILITY CALCULATION ---
        # Formula: ((Total Price - Total Overhead) / Total Price) * 100
        if machine.current_price and machine.current_price > 0:
            total_overhead = machine.metrics.get("total_overhead", 0)
            current_profit = machine.current_price - total_overhead
            
            # Calculates what percentage of the transaction price is actual profit
            machine.profitability_rate = round((current_profit / machine.current_price) * 100, 2)
        else:
            # Default to 0.0 if machine is idle to prevent DivisionByZero errors
            machine.profitability_rate = 0.0
    
    # Note: No db.commit() is needed here as we are only reading and calculating in-memory
    return machines

def get_machine_by_id(db: Session, machine_id: int, shop_id: int = None):
    """
    Retrieves a single machine's details.
    Used for focused monitoring of a specific hardware unit.
    """
    target_shop_id = shop_id if shop_id is not None else 1
    
    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == target_shop_id
    ).first()
    
    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Machine hardware unit not found or access denied."
        )
    
    is_busy = machine.status == "Busy"
    machine.metrics = PredictionService.calculate_metrics(machine, is_busy)
    
    return machine

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int):
    """
    Manually adds a new machine unit with independent consumption rates.
    Initializes analytics tracking for profit and cycle counts.
    """
    final_shop_id = shop_id if shop_id else 1
    
    # Set default efficiency rates based on machine type
    # Washers consume water/detergent; Dryers consume significantly more electricity
    is_washer = machine_data.machine_type.lower() == "washer"
    
    new_machine = Machine(
        machine_type=machine_data.machine_type,
        machine_number=machine_data.machine_number,
        status="Available",
        current_service_type="None",
        current_price=0.0,
        total_cycles=0,
        net_profit_accumulated=0.0,
        # Default consumption presets
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
    Permanently removes a machine record and its associated financial history.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted."}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles machine status between 'Available' and 'Maintenance'.
    Clears active session data when moving to maintenance to prevent 'ghost' timers.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        machine.status = "Available"
    else:
        # Force stop active tracking if the machine needs repair
        machine.status = "Maintenance"
        machine.remaining_time = 0 
        machine.current_service_type = "None"
        machine.current_price = 0.0

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Automated deployment of a 12-unit hardware suite (6 Washers, 6 Dryers).
    Initializes each unit with the required logic for profit and usage tracking.
    """
    final_shop_id = shop_id if shop_id else 1
    
    # Check for existing units to prevent duplicate deployment
    existing_check = db.query(Machine).filter(Machine.shop_id == final_shop_id).first()
    if existing_check:
        return {"message": "Shop hardware is already initialized."}

    machines_to_add = []
    
    # Deploy Washers (Consumption: Balanced Electricity + Water + Detergent)
    for i in range(1, 7):
        machines_to_add.append(
            Machine(
                machine_type="Washer", 
                machine_number=i, 
                status="Available", 
                current_service_type="None",
                current_price=0.0,
                total_cycles=0,
                net_profit_accumulated=0.0,
                avg_electricity=1.2,
                avg_water=60.0,
                avg_detergent=50.0,
                shop_id=final_shop_id,
                remaining_time=0
            )
        )
    
    # Deploy Dryers (Consumption: High Electricity Only)
    for i in range(1, 7):
        machines_to_add.append(
            Machine(
                machine_type="Dryer", 
                machine_number=i, 
                status="Available", 
                current_service_type="None",
                current_price=0.0,
                total_cycles=0,
                net_profit_accumulated=0.0,
                avg_electricity=3.0, 
                avg_water=0.0,
                avg_detergent=0.0,
                shop_id=final_shop_id,
                remaining_time=0
            )
        )

    db.add_all(machines_to_add)
    db.commit()
    return {"message": "Full 12-unit hardware suite deployed with live tracking enabled."}