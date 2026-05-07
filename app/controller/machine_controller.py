from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status

def get_all_machines(db: Session, shop_id: int = None):
    """
    Retrieves all machines for a specific shop. 
    Calculates real-time performance metrics (Exact Time, Profitability) before returning to the Dashboard.
    """
    # Use provided shop_id or default to 1 for development environment
    target_shop_id = shop_id if shop_id is not None else 1
    
    # Filter by shop_id to ensure the monitoring hub displays only the shop's hardware
    query = db.query(Machine).filter(Machine.shop_id == target_shop_id)
    
    machines = query.order_by(
        Machine.machine_type.desc(), 
        Machine.machine_number.asc()
    ).all()

    for machine in machines:
        # Check if machine is running to trigger the PredictionService logic
        is_busy = machine.status.lower() == "busy"
        
        # 1. Fetch calculated metrics from the updated PredictionService
        # This returns the exact duration (38, 48, 90 mins) and overhead costs
        analytics = PredictionService.calculate_metrics(machine, is_busy)

        # 2. Sync Calculated Data with Machine Object for Frontend consumption
        # This maps the "Exact Time" to the remaining_time field
        machine.remaining_time = analytics.get("duration_minutes", 0)
        
        # Maps the calculated percentage to the progress bar field
        machine.profitability_rate = analytics.get("profitability_rate", 0.0)
        
        # Maps the current net profit to the label in the footer of the card
        machine.net_profit_accumulated = analytics.get("net_profit", 0.0)

        # Passes the cost breakdown (Electricity, Water, Detergent) to the Machine Hub
        machine.metrics = {
            "detergent_cost": analytics.get("detergent_cost", 0.0),
            "electricity_cost": analytics.get("electricity_cost", 0.0),
            "water_cost": analytics.get("water_cost", 0.0),
            "total_overhead": analytics.get("total_overhead", 0.0)
        }
    
    # Note: Changes are kept in-memory for live display; no db.commit() needed for GET
    return machines

def get_machine_by_id(db: Session, machine_id: int, shop_id: int = None):
    """
    Retrieves a single machine's details.
    Used for focused monitoring or detailed analysis of a specific hardware unit.
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
    
    is_busy = machine.status.lower() == "busy"
    analytics = PredictionService.calculate_metrics(machine, is_busy)
    
    # Sync calculated values for a single unit response
    machine.remaining_time = analytics.get("duration_minutes", 0)
    machine.profitability_rate = analytics.get("profitability_rate", 0.0)
    machine.net_profit_accumulated = analytics.get("net_profit", 0.0)
    machine.metrics = analytics
    
    return machine

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int):
    """
    Adds a new machine unit with preset consumption rates based on the shop's monthly averages.
    Initializes analytics tracking for profit and cycle counts.
    """
    final_shop_id = shop_id if shop_id else 1
    is_washer = machine_data.machine_type.lower() == "washer"
    
    new_machine = Machine(
        machine_type=machine_data.machine_type,
        machine_number=machine_data.machine_number,
        status="Available",
        current_service_type="None",
        current_price=0.0,
        total_cycles=0,
        net_profit_accumulated=0.0,
        profitability_rate=0.0,
        # Default consumption rates calibrated for accurate profit calculation
        avg_electricity=15.0 if is_washer else 25.0, # PHP cost equivalent
        avg_water=4.80 if is_washer else 0.0,        # PHP cost equivalent
        avg_detergent=11.25 if is_washer else 0.0,   # PHP cost equivalent
        remaining_time=0,
        shop_id=final_shop_id
    )
    db.add(new_machine)
    db.commit()
    db.refresh(new_machine)
    return new_machine

def delete_machine(db: Session, machine_id: int, shop_id: int):
    """
    Permanently removes a machine record and its associated data history.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted."}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles machine status between 'Available' and 'Maintenance'.
    Clears active session data when moving to maintenance to prevent incorrect dashboard timers.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        machine.status = "Available"
    else:
        # Force stop active tracking if the machine is taken offline
        machine.status = "Maintenance"
        machine.remaining_time = 0 
        machine.current_service_type = "None"
        machine.current_price = 0.0
        machine.profitability_rate = 0.0

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Automated deployment of a 12-unit hardware suite (6 Washers, 6 Dryers).
    Initializes each unit with the required consumption profiles for the Prediction Service.
    """
    final_shop_id = shop_id if shop_id else 1
    
    # Prevent duplicate hardware initialization
    existing_check = db.query(Machine).filter(Machine.shop_id == final_shop_id).first()
    if existing_check:
        return {"message": "Shop hardware is already initialized."}

    machines_to_add = []
    
    # Deploy Washers (Preset for Wash-specific overhead)
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
                profitability_rate=0.0,
                avg_electricity=15.0, # PHP based on price list costs
                avg_water=4.80,
                avg_detergent=11.25,
                shop_id=final_shop_id,
                remaining_time=0
            )
        )
    
    # Deploy Dryers (High Electricity Overhead, Zero Water/Detergent)
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
                profitability_rate=0.0,
                avg_electricity=25.0, # High intensity heating cost
                avg_water=0.0,
                avg_detergent=0.0,
                shop_id=final_shop_id,
                remaining_time=0
            )
        )

    db.add_all(machines_to_add)
    db.commit()
    return {"message": "Full 12-unit hardware suite deployed with predictive tracking enabled."}