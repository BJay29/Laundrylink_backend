from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status

def get_all_machines(db: Session, shop_id: int = None):
    """
    Retrieves all machines for a specific shop. 
    Includes real-time performance metrics and profitability calculations.
    """
    # Use provided shop_id or default to 1
    target_shop_id = shop_id if shop_id is not None else 1
    
    # Strictly filter by shop_id to ensure terminal sync is accurate
    query = db.query(Machine).filter(Machine.shop_id == target_shop_id)
    
    machines = query.order_by(
        Machine.machine_type.desc(), 
        Machine.machine_number.asc()
    ).all()

    for machine in machines:
        # Maintenance: PredictionService calculates overhead costs
        # based on the unique consumption rates of this specific machine unit.
        is_busy = machine.status == "Busy"
        machine.metrics = PredictionService.calculate_metrics(machine, is_busy)

        # REAL-TIME PROFITABILITY CALCULATION
        # Logic: (Current Profit Margin / Transaction Price)
        if machine.current_price and machine.current_price > 0:
            total_overhead = machine.metrics.get("total_overhead", 0)
            current_profit = machine.current_price - total_overhead
            # Calculate what percentage of the current price is actual profit
            machine.profitability_rate = (current_profit / machine.current_price) * 100
        else:
            # Default to 0.0 if machine is idle to prevent DivisionByZero errors
            machine.profitability_rate = 0.0
    
    # Removed db.commit() here to prevent unnecessary DB locks during read operations
    return machines

def get_machine_by_id(db: Session, machine_id: int, shop_id: int = None):
    """
    Retrieves a single machine's details including current service type and price.
    Ensures the machine belongs to the requested shop.
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
    Manually creates a new machine unit with independent consumption rates.
    Initializes tracking for service types and profitability.
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
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted"}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
    """
    Toggles machine status between 'Available' and 'Maintenance'.
    Clears real-time service data if moved to maintenance to prevent ghosting on dashboard.
    """
    machine = get_machine_by_id(db, machine_id, shop_id)
    
    if machine.status == "Maintenance":
        machine.status = "Available"
    else:
        # When moving to maintenance, reset all active session data
        machine.status = "Maintenance"
        machine.remaining_time = 0 
        machine.current_service_type = "None"
        machine.current_price = 0.0

    db.commit()
    db.refresh(machine)
    return machine

def initialize_shop_machines(db: Session, shop_id: int):
    """
    Standard deployment of 12 units (6 Washers, 6 Dryers).
    Initializes each unit with the capacity for real-time service and profit tracking.
    """
    final_shop_id = shop_id if shop_id else 1
    
    # Check if shop already has machines to avoid duplicate initialization
    existing_check = db.query(Machine).filter(Machine.shop_id == final_shop_id).first()
    if existing_check:
        return {"message": "Shop hardware is already initialized"}

    machines_to_add = []
    
    # Deploy 6 Washers (Consumption: Water + Detergent + Light Electricity)
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
    
    # Deploy 6 Dryers (Consumption: High Electricity Only)
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
    return {"message": "Full 12-unit hardware suite deployed with real-time tracking enabled"}