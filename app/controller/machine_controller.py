from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate, MachineUpdate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status

def _enrich(machine: Machine) -> Machine:
    """
    Data enrichment for the UI.
    Formats the accumulated database values into a clean metrics object 
    for the React Dashboard.
    """
    # Create a structured metrics object for the frontend tables and cards
    machine.metrics = {
        "electricity_cost": round(machine.accumulated_electricity, 2),
        "water_cost": round(machine.accumulated_water, 2),
        "detergent_cost": round(machine.accumulated_detergent, 2),
        "total_overhead": round(
            machine.accumulated_electricity + 
            machine.accumulated_water + 
            machine.accumulated_detergent, 2
        )
    }
    return machine

def get_all_machines(db: Session, shop_id: int = 1):
    """
    Retrieves all hardware units sorted by type (Washers then Dryers).
    Applies the enrichment helper to format accumulated costs for the UI.
    """
    machines = (
        db.query(Machine)
        .filter(Machine.shop_id == shop_id)
        .order_by(Machine.machine_type.desc(), Machine.machine_number.asc())
        .all()
    )
    return [_enrich(m) for m in machines]

def get_machine_by_id(db: Session, machine_id: int, shop_id: int = 1):
    """
    Fetches a single machine unit by its ID.
    """
    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == shop_id
    ).first()

    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hardware unit with ID {machine_id} not found."
        )
    return _enrich(machine)

def update_machine_usage_stats(db: Session, machine_id: int, duration_minutes: int):
    """
    NEW: This function should be called when a laundry cycle is completed.
    It calculates costs based on Naga City rates and increments the 
    accumulated totals in the database.
    """
    machine = db.query(Machine).filter(Machine.id == machine_id).first()
    if not machine:
        return None

    # Calculate costs for this specific session
    costs = PredictionService.calculate_cycle_cost(machine.machine_type, duration_minutes)

    # Increment accumulated values in the DB
    machine.total_cycles += 1
    machine.accumulated_electricity += costs["electricity"]
    machine.accumulated_water += costs["water"]
    machine.accumulated_detergent += costs["detergent"]
    
    # Update profit (Price charged to customer minus the overhead we just calculated)
    # This assumes machine.current_price was set at the start of the booking
    cycle_profit = machine.current_price - (costs["electricity"] + costs["water"] + costs["detergent"])
    machine.net_profit_accumulated += cycle_profit

    db.commit()
    db.refresh(machine)
    return _enrich(machine)

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int = 1):
    """
    Registers a new unit. 
    Initializes all accumulated costs to 0.0 to ensure a clean start.
    """
    new_machine = Machine(
        machine_type=machine_data.machine_type,
        machine_number=machine_data.machine_number,
        status="Available",
        current_service_type="None",
        current_price=0.0,
        total_cycles=0,
        net_profit_accumulated=0.0,
        profitability_rate=0.0,
        accumulated_electricity=0.0,
        accumulated_water=0.0,
        accumulated_detergent=0.0,
        remaining_time=0,
        shop_id=shop_id
    )
    
    db.add(new_machine)
    db.commit()
    db.refresh(new_machine)
    return _enrich(new_machine)

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int = 1):
    """
    Toggles the maintenance state. Maintenance blocks the machine 
    and clears active service data.
    """
    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == shop_id
    ).first()

    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found.")

    if machine.status == "Maintenance":
        machine.status = "Available"
    else:
        machine.status = "Maintenance"
        machine.remaining_time = 0
        machine.current_service_type = "None"
        machine.current_price = 0.0

    db.commit()
    db.refresh(machine)
    return _enrich(machine)

def initialize_shop_machines(db: Session, shop_id: int = 1):
    """
    Seed function to deploy the standard 12-unit hardware suite.
    Sets all starting utility costs to zero.
    """
    existing = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing:
        return {"message": "Hardware grid already initialized."}

    machines = []
    # Deploy Washers (1-6) and Dryers (1-6)
    for m_type in ["Washer", "Dryer"]:
        for i in range(1, 7):
            machines.append(Machine(
                machine_type=m_type, machine_number=i,
                status="Available", current_service_type="None",
                current_price=0.0, total_cycles=0,
                net_profit_accumulated=0.0, profitability_rate=0.0,
                accumulated_electricity=0.0, accumulated_water=0.0, 
                accumulated_detergent=0.0,
                remaining_time=0, shop_id=shop_id
            ))

    db.add_all(machines)
    db.commit()
    return {"message": "12-unit suite deployed with Actual Backend cost tracking enabled."}