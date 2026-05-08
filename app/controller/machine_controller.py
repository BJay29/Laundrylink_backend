from sqlalchemy.orm import Session
from app.models import Machine, Booking
from app.schemas import MachineCreate, MachineUpdate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status

def _enrich(machine: Machine) -> Machine:
    """
    Data enrichment helper for the React UI.
    Converts raw database columns into a structured metrics object.
    Ensures None values are handled as 0.0 to prevent frontend crashes.
    """
    # Safety check: Default None values to 0.0 for calculations
    elec = machine.accumulated_electricity or 0.0
    water = machine.accumulated_water or 0.0
    detergent = machine.accumulated_detergent or 0.0

    # FIXED: Changed parentheses () to curly braces {} to correctly define the dictionary
    machine.metrics = {
        "electricity_cost": round(elec, 2),
        "water_cost": round(water, 2),
        "detergent_cost": round(detergent, 2),
        "total_overhead": round(elec + water + detergent, 2)
    }
    return machine

def delete_machine(db: Session, machine_id: int, shop_id: int = 1):
    """
    Deletes a machine unit. 
    Because of ondelete="SET NULL" in models.py, this will successfully 
    remove the machine without deleting related booking history.
    """
    machine = db.query(Machine).filter(
        Machine.id == machine_id, 
        Machine.shop_id == shop_id
    ).first()

    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Machine not found or already removed."
        )

    try:
        db.delete(machine)
        db.commit()
        return {"message": f"Machine {machine_id} successfully decommissioned."}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during deletion: {str(e)}"
        )

def get_all_machines(db: Session, shop_id: int = 1):
    """
    Retrieves all hardware units for a shop, sorted by type and number.
    Applies enrichment to provide formatted metrics to the frontend.
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
    Fetches a single machine unit with full telemetry enrichment.
    """
    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == shop_id
    ).first()

    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Machine unit ID {machine_id} not found."
        )
    return _enrich(machine)

def update_machine_usage_stats(db: Session, machine_id: int, duration_minutes: int):
    """
    Updates machine telemetry after a cycle is completed.
    Calculates utility costs and increments the lifetime profit tracking.
    """
    machine = db.query(Machine).filter(Machine.id == machine_id).first()
    if not machine:
        return None

    # Calculate costs for this session based on utility rates
    costs = PredictionService.calculate_cycle_cost(machine.machine_type, duration_minutes)

    # Accumulate telemetry data
    machine.total_cycles += 1
    machine.accumulated_electricity = (machine.accumulated_electricity or 0.0) + costs["electricity"]
    machine.accumulated_water = (machine.accumulated_water or 0.0) + costs["water"]
    machine.accumulated_detergent = (machine.accumulated_detergent or 0.0) + costs["detergent"]
    
    # Calculate and update net profit
    overhead_sum = costs["electricity"] + costs["water"] + costs["detergent"]
    cycle_profit = (machine.current_price or 0.0) - overhead_sum
    machine.net_profit_accumulated = (machine.net_profit_accumulated or 0.0) + cycle_profit

    db.commit()
    db.refresh(machine)
    return _enrich(machine)

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int = 1):
    """
    Registers a new hardware unit and initializes all telemetry fields to zero.
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
    Toggles the hardware state between Available and Maintenance.
    Entering maintenance clears real-time countdowns for safety.
    """
    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == shop_id
    ).first()

    if not machine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found.")

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
    Seed function to deploy a standard 12-unit laundry grid.
    Ensures clean telemetry initialization for all units.
    """
    existing = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing:
        return {"message": "Hardware grid is already initialized."}

    machines = []
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