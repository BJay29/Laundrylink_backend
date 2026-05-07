from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate, MachineUpdate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status

def _enrich(machine: Machine) -> Machine:
    """
    In-memory data enrichment using the PredictionService.
    Calculates real-time metrics for the UI (Remaining Time, Profit Margin, 
    and Overhead Breakdown) without persisting temporary data to the DB.
    """
    is_busy = machine.status.lower() == "busy"
    analytics = PredictionService.calculate_metrics(machine, is_busy)

    # Injecting calculated fields for the frontend API response
    machine.remaining_time = analytics["duration_minutes"]
    machine.profitability_rate = analytics["profitability_rate"]
    machine.net_profit_accumulated = analytics["net_profit"]
    
    # Nested metrics object used by optimizationLogic.js for the Dashboard warnings
    machine.metrics = {
        "detergent_cost":   analytics["detergent_cost"],
        "electricity_cost": analytics["electricity_cost"],
        "water_cost":       analytics["water_cost"],
        "total_overhead":   analytics["total_overhead"],
    }
    return machine

def get_all_machines(db: Session, shop_id: int = 1):
    """
    Retrieves all hardware units sorted by type and number.
    Applies real-time telemetry enrichment to each unit.
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
    Fetches a single machine and re-calculates its current profitability margin.
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

def create_machine(db: Session, machine_data: MachineCreate, shop_id: int = 1):
    """
    Registers a new unit and sets its resource consumption coefficients.
    Washers are initialized with Soap/Water rates, while Dryers are Power-heavy.
    """
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
        # Default consumption constants based on 2026 utility rates
        avg_electricity=14.20 if is_washer else 38.50,
        avg_water=16.50 if is_washer else 0.0,
        avg_detergent=12.75 if is_washer else 0.0,
        remaining_time=0,
        shop_id=shop_id
    )
    
    db.add(new_machine)
    db.commit()
    db.refresh(new_machine)
    return _enrich(new_machine)

def delete_machine(db: Session, machine_id: int, shop_id: int = 1):
    """
    Deletes a machine record. Typically used for hardware decommissioning.
    """
    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == shop_id
    ).first()

    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found.")

    db.delete(machine)
    db.commit()
    return {"message": f"Hardware unit {machine.machine_type} {machine.machine_number} successfully removed."}

def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int = 1):
    """
    Toggles the maintenance state. Maintenance blocks the machine from 
    the booking flow and resets active cycle timers.
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
        # Reset active cycle telemetry when moving to maintenance
        machine.remaining_time = 0
        machine.current_service_type = "None"
        machine.current_price = 0.0
        machine.profitability_rate = 0.0

    db.commit()
    db.refresh(machine)
    return _enrich(machine)

def reset_all_machines(db: Session, shop_id: int = 1):
    """
    Emergency override: Force-resets all machines to Available.
    Clears all 'Busy' flags and active timers.
    """
    machines = db.query(Machine).filter(Machine.shop_id == shop_id).all()
    for m in machines:
        if m.status != "Maintenance":
            m.status = "Available"
            m.remaining_time = 0
            m.current_service_type = "None"
            m.current_price = 0.0
    
    db.commit()
    return {"message": "All operational units have been reset to Available status."}

def initialize_shop_machines(db: Session, shop_id: int = 1):
    """
    Seed function for the Naga College Foundation dev environment.
    Deploys 6 Washers and 6 Dryers with pre-calibrated utility rates.
    """
    existing = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing:
        return {"message": "Hardware grid already initialized for this shop."}

    machines = []
    # Deploy 6 Washers
    for i in range(1, 7):
        machines.append(Machine(
            machine_type="Washer", machine_number=i,
            status="Available", current_service_type="None",
            current_price=0.0, total_cycles=0,
            net_profit_accumulated=0.0, profitability_rate=0.0,
            avg_electricity=14.20, avg_water=16.50, avg_detergent=12.75,
            remaining_time=0, shop_id=shop_id
        ))
    
    # Deploy 6 Dryers (Notice the high 38.50 electricity rate)
    for i in range(1, 7):
        machines.append(Machine(
            machine_type="Dryer", machine_number=i,
            status="Available", current_service_type="None",
            current_price=0.0, total_cycles=0,
            net_profit_accumulated=0.0, profitability_rate=0.0,
            avg_electricity=38.50, avg_water=0.0, avg_detergent=0.0,
            remaining_time=0, shop_id=shop_id
        ))

    db.add_all(machines)
    db.commit()
    return {"message": "Standard 12-unit hardware suite deployed and ready for telemetry."}