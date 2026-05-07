from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate, MachineUpdate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status

def _enrich(machine: Machine) -> Machine:
    """
    Data enrichment for the UI.
    Formats the accumulated database telemetry into a clean metrics object 
    for the React Dashboard's optimization logic.
    """
    # Safety check: Default None values to 0.0 to prevent calculation errors
    elec = machine.accumulated_electricity or 0.0
    water = machine.accumulated_water or 0.0
    detergent = machine.accumulated_detergent or 0.0

    # Create a structured metrics object for the frontend tables and cards
    machine.metrics = {
        "electricity_cost": round(elec, 2),
        "water_cost": round(water, 2),
        "detergent_cost": round(detergent, 2),
        "total_overhead": round(elec + water + detergent, 2)
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
    Fetches a single machine unit by its ID with full telemetry enrichment.
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
    Called when a laundry cycle is completed.
    Calculates costs based on Naga City utility rates and increments 
    the accumulated totals in the database for lifetime tracking.
    """
    machine = db.query(Machine).filter(Machine.id == machine_id).first()
    if not machine:
        return None

    # Calculate costs for this specific session via PredictionService
    costs = PredictionService.calculate_cycle_cost(machine.machine_type, duration_minutes)

    # Increment accumulated values in the DB (Safety: initialize with or 0.0)
    machine.total_cycles += 1
    machine.accumulated_electricity = (machine.accumulated_electricity or 0.0) + costs["electricity"]
    machine.accumulated_water = (machine.accumulated_water or 0.0) + costs["water"]
    machine.accumulated_detergent = (machine.accumulated_detergent or 0.0) + costs["detergent"]
    
    # Update lifetime profit (Current Price charged minus this session's overhead)
    overhead_sum = costs["electricity"] + costs["water"] + costs["detergent"]
    cycle_profit = (machine.current_price or 0.0) - overhead_sum
    machine.net_profit_accumulated = (machine.net_profit_accumulated or 0.0) + cycle_profit

    db.commit()
    db.refresh(machine)
    return _enrich(machine)

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int = 1):
    """
    Registers a new hardware unit. 
    Initializes all accumulated cost fields to 0.0 to ensure clean telemetry.
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
    Toggles the hardware maintenance state. 
    Maintenance mode blocks service availability and clears real-time countdowns.
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
        # Putting a machine in maintenance clears current cycle data for safety
        machine.status = "Maintenance"
        machine.remaining_time = 0
        machine.current_service_type = "None"
        machine.current_price = 0.0

    db.commit()
    db.refresh(machine)
    return _enrich(machine)

def initialize_shop_machines(db: Session, shop_id: int = 1):
    """
    Seed function to deploy the standard 12-unit laundry grid.
    Deploys 6 Washers and 6 Dryers with initialized zero-cost tracking.
    """
    existing = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing:
        return {"message": "Hardware grid is already initialized for this shop."}

    machines = []
    # Deploy standard grid: 6 Washers and 6 Dryers
    for m_type in ["Washer", "Dryer"]:
        for i in range(1, 7):
            machines.append(Machine(
                machine_type=m_type, 
                machine_number=i,
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
            ))

    db.add_all(machines)
    db.commit()
    return {"message": "12-unit suite deployed with real-time cost telemetry enabled."}