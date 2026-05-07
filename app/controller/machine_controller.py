from sqlalchemy.orm import Session
from app.models import Machine
from app.schemas import MachineCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status


def _enrich(machine: Machine) -> Machine:
    """
    Applies PredictionService analytics to a machine object in-memory.
    No db.commit() — this is a read-only enrichment for API responses.
    """
    is_busy = machine.status.lower() == "busy"
    analytics = PredictionService.calculate_metrics(machine, is_busy)

    machine.remaining_time      = analytics["duration_minutes"]
    machine.profitability_rate  = analytics["profitability_rate"]
    machine.net_profit_accumulated = analytics["net_profit"]
    machine.metrics = {
        "detergent_cost":   analytics["detergent_cost"],
        "electricity_cost": analytics["electricity_cost"],
        "water_cost":       analytics["water_cost"],
        "total_overhead":   analytics["total_overhead"],
    }
    return machine


def get_all_machines(db: Session, shop_id: int = 1):
    machines = (
        db.query(Machine)
        .filter(Machine.shop_id == shop_id)
        .order_by(Machine.machine_type.desc(), Machine.machine_number.asc())
        .all()
    )
    return [_enrich(m) for m in machines]


def get_machine_by_id(db: Session, machine_id: int, shop_id: int = 1):
    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == shop_id
    ).first()

    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine not found."
        )
    return _enrich(machine)


def create_machine(db: Session, machine_data: MachineCreate, shop_id: int = 1):
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
        avg_electricity=14.20 if is_washer else 38.50,
        avg_water=16.50       if is_washer else 0.0,
        avg_detergent=12.75   if is_washer else 0.0,
        remaining_time=0,
        shop_id=shop_id
    )
    db.add(new_machine)
    db.commit()
    db.refresh(new_machine)
    return _enrich(new_machine)


def delete_machine(db: Session, machine_id: int, shop_id: int = 1):
    machine = get_machine_by_id(db, machine_id, shop_id)
    db.delete(machine)
    db.commit()
    return {"message": f"Machine {machine.machine_type} {machine.machine_number} deleted."}


def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int = 1):
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
        machine.profitability_rate = 0.0

    db.commit()
    db.refresh(machine)
    return _enrich(machine)


def initialize_shop_machines(db: Session, shop_id: int = 1):
    existing = db.query(Machine).filter(Machine.shop_id == shop_id).first()
    if existing:
        return {"message": "Shop hardware already initialized."}

    machines = []
    for i in range(1, 7):
        machines.append(Machine(
            machine_type="Washer", machine_number=i,
            status="Available", current_service_type="None",
            current_price=0.0, total_cycles=0,
            net_profit_accumulated=0.0, profitability_rate=0.0,
            avg_electricity=14.20, avg_water=16.50, avg_detergent=12.75,
            remaining_time=0, shop_id=shop_id
        ))
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
    return {"message": "12-unit hardware suite deployed successfully."}
