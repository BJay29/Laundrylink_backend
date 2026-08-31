from sqlalchemy.orm import Session
from app.models import Machine, Booking
from app.schemas import MachineCreate, MachineUpdate
from app.services.prediction_service import PredictionService
from app.controller.activity_controller import log_activity
from app import models
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


def delete_machine(db: Session, machine_id: int, current_user: models.User):
    """
    Deletes a machine unit.
    Because of ondelete="SET NULL" in models.py, this will successfully
    remove the machine without deleting related booking history.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id so this destructive action can be attributed to whoever
    performed it.
    """
    shop_id = current_user.shop_id

    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == shop_id
    ).first()

    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine not found or already removed."
        )

    machine_label = f"{machine.machine_type} #{machine.machine_number}"

    try:
        db.delete(machine)

        # --- ACTIVITY LOG ---
        log_activity(
            db, shop_id,
            actor_name=current_user.email,
            actor_role=current_user.role,
            description=f"Nag-tanggal ng machine: {machine_label}"
        )

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

    NOTE: read-only, no Activity Log entry — signature unchanged (still
    shop_id, not current_user), since no actor attribution is needed here.
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

    NOTE: read-only, no Activity Log entry.
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


def update_machine(db: Session, machine_id: int, update_data: MachineUpdate, current_user: models.User):
    """
    Updates editable machine fields (status, telemetry overrides, pricing,
    etc). Only fields explicitly provided in the request are changed
    (partial update). Scoped to the requesting user's shop — a machine
    belonging to another shop returns 404, not silent success.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id.
    """
    shop_id = current_user.shop_id

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

    machine_label = f"{machine.machine_type} #{machine.machine_number}"

    try:
        # --- ACTIVITY LOG ---
        changed_fields = ", ".join(update_fields.keys()) if update_fields else "no fields"
        log_activity(
            db, shop_id,
            actor_name=current_user.email,
            actor_role=current_user.role,
            description=f"Nag-update ng machine {machine_label} ({changed_fields})"
        )

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

    NOTE: this function is currently NOT called by any route (confirmed
    unused/dead code in an earlier pass) — left with the shop_id-only
    signature since there's no HTTP-request context (no current_user)
    calling it. If this is wired up later (e.g. a background job for
    auto-completing cycles), decide then whether it needs its own
    Activity Log entry or whether "system" should be logged as the actor.
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


def create_machine(db: Session, machine_data: MachineCreate, current_user: models.User):
    """
    Registers a new hardware unit and initializes all telemetry fields to zero.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id.
    """
    shop_id = current_user.shop_id

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
    db.flush()  # kailangan para makuha ang machine_type/machine_number bago mag-commit

    # --- ACTIVITY LOG ---
    log_activity(
        db, shop_id,
        actor_name=current_user.email,
        actor_role=current_user.role,
        description=f"Nagdagdag ng bagong machine: {new_machine.machine_type} #{new_machine.machine_number}"
    )

    db.commit()
    db.refresh(new_machine)
    return _enrich(new_machine)


def toggle_machine_maintenance(db: Session, machine_id: int, current_user: models.User):
    """
    Toggles the hardware state between Available and Maintenance.
    Entering maintenance clears real-time countdowns for safety.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id.
    """
    shop_id = current_user.shop_id

    machine = db.query(Machine).filter(
        Machine.id == machine_id,
        Machine.shop_id == shop_id
    ).first()

    if not machine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found.")

    machine_label = f"{machine.machine_type} #{machine.machine_number}"

    if machine.status == "Maintenance":
        machine.status = "Available"
        action_desc = f"Inilabas sa Maintenance ang {machine_label} — Available na ulit"
    else:
        machine.status = "Maintenance"
        machine.remaining_time = 0
        machine.current_service_type = "None"
        machine.current_price = 0.0
        action_desc = f"Inilagay sa Maintenance ang {machine_label}"

    # --- ACTIVITY LOG ---
    log_activity(
        db, shop_id,
        actor_name=current_user.email,
        actor_role=current_user.role,
        description=action_desc
    )

    db.commit()
    db.refresh(machine)
    return _enrich(machine)


def initialize_shop_machines(db: Session, current_user: models.User):
    """
    Seed function to deploy a standard 12-unit laundry grid.
    Ensures clean telemetry initialization for all units.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id.
    """
    shop_id = current_user.shop_id

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

    # --- ACTIVITY LOG ---
    log_activity(
        db, shop_id,
        actor_name=current_user.email,
        actor_role=current_user.role,
        description=f"Nag-deploy ng default 12-unit machine grid (6 Washer, 6 Dryer)"
    )

    db.commit()
    return {"message": "12-unit suite deployed with real-time cost telemetry enabled."}


def reset_all_machines(db: Session, current_user: models.User):
    """
    Emergency override: sets every machine belonging to this shop back to
    'Available' and clears active-cycle telemetry (does NOT reset lifetime
    totals like total_cycles or net_profit_accumulated).

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id. This is a shop-wide destructive-ish override, so it's
    important to know who triggered it.
    """
    shop_id = current_user.shop_id

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
        # --- ACTIVITY LOG ---
        log_activity(
            db, shop_id,
            actor_name=current_user.email,
            actor_role=current_user.role,
            description=f"Nag-reset ng lahat ng machines ({len(machines)} unit/s) pabalik sa Available"
        )

        db.commit()
        return {"message": f"{len(machines)} machine(s) reset to Available."}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during reset: {str(e)}"
        )