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
    elec = machine.accumulated_electricity or 0.0
    water = machine.accumulated_water or 0.0
    detergent = machine.accumulated_detergent or 0.0

    machine.metrics = {
        "electricity_cost": round(elec, 2),
        "water_cost": round(water, 2),
        "detergent_cost": round(detergent, 2),
        "total_overhead": round(elec + water + detergent, 2)
    }
    return machine


def delete_machine(db: Session, machine_id: int, shop_id: int):
    """
    Deletes a machine unit.
    Because of ondelete="SET NULL" in models.py, this will successfully
    remove the machine without deleting related booking history.

    NOTE: Removed the `shop_id: int = 1` default. shop_id must now always
    be explicitly passed in from the authenticated user's JWT — a silent
    default made it too easy to accidentally query/mutate shop 1's data.
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


def get_all_machines(db: Session, shop_id: int):
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


def get_machine_by_id(db: Session, machine_id: int, shop_id: int):
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


def update_machine(db: Session, machine_id: int, update_data: MachineUpdate, shop_id: int):
    """
    NEW FUNCTION — was referenced by machine_routes.py's PATCH /{machine_id}
    endpoint but was missing from the controller, which would have caused
    an AttributeError at runtime.

    Updates editable machine fields (status, telemetry overrides, pricing,
    etc). Only fields explicitly provided in the request are changed
    (partial update). Scoped to the requesting user's shop — a machine
    belonging to another shop returns 404, not silent success.
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

    update_fields = update_data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(machine, field, value)

    try:
        db.commit()
        db.refresh(machine)
        return _enrich(machine)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during update: {str(e)}"
        )


def update_machine_usage_stats(db: Session, machine_id: int, duration_minutes: int, shop_id: int):
    """
    Updates machine telemetry after a cycle is completed.
    Calculates utility costs and increments the lifetime profit tracking.

    Added shop_id filtering — previously this queried by machine_id alone
    with no shop check at all, meaning a machine ID belonging to another
    shop could have its telemetry silently updated if this were ever
    called with an untrusted machine_id.
    """
    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == shop_id
    ).first()
    if not machine:
        return None

    costs = PredictionService.calculate_cycle_cost(machine.machine_type, duration_minutes)

    machine.total_cycles += 1
    machine.accumulated_electricity = (machine.accumulated_electricity or 0.0) + costs["electricity"]
    machine.accumulated_water = (machine.accumulated_water or 0.0) + costs["water"]
    machine.accumulated_detergent = (machine.accumulated_detergent or 0.0) + costs["detergent"]

    overhead_sum = costs["electricity"] + costs["water"] + costs["detergent"]
    cycle_profit = (machine.current_price or 0.0) - overhead_sum
    machine.net_profit_accumulated = (machine.net_profit_accumulated or 0.0) + cycle_profit

    db.commit()
    db.refresh(machine)
    return _enrich(machine)


def create_machine(db: Session, machine_data: MachineCreate, shop_id: int):
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


def toggle_machine_maintenance(db: Session, machine_id: int, shop_id: int):
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


def initialize_shop_machines(db: Session, shop_id: int):
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


def reset_all_machines(db: Session, shop_id: int):
    """
    NEW FUNCTION — was referenced by machine_routes.py's POST /reset-all
    endpoint but was missing from the controller, which would have caused
    an AttributeError at runtime.

    Emergency override: sets every machine belonging to this shop back to
    'Available' and clears active-cycle telemetry (does NOT reset lifetime
    totals like total_cycles or net_profit_accumulated).
    """
    machines = db.query(Machine).filter(Machine.shop_id == shop_id).all()

    if not machines:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No machines found for this shop."
        )

    for machine in machines:
        machine.status = "Available"
        machine.remaining_time = 0
        machine.current_service_type = "None"
        machine.current_price = 0.0

    try:
        db.commit()
        return {"message": f"{len(machines)} machine(s) reset to Available."}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during reset: {str(e)}"
        )