from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import MachineResponse, MachineCreate, MachineUpdate
from app.controller import machine_controller
from app import models
from app.security import get_current_user

# API Router for Hardware Management and Real-Time Telemetry
router = APIRouter(
    prefix="/machines",
    tags=["Machines"]
)


@router.get("/", response_model=List[MachineResponse])
def get_machines(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetches real-time status and performance metrics for all shop units.
    shop_id is derived from the logged-in user's JWT, not a query param —
    a user can never list another shop's machines by editing the URL.
    Read-only — no controller signature change needed here.
    """
    return machine_controller.get_all_machines(db, shop_id=current_user.shop_id)


@router.post("/", response_model=MachineResponse, status_code=status.HTTP_201_CREATED)
def add_new_machine(
    machine_data: MachineCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Registers a new hardware unit under the logged-in user's own shop.
    machine_data.shop_id (if present) is ignored — shop_id always comes
    from the JWT so a machine can never be registered under a different shop.
    """
    return machine_controller.create_machine(db, machine_data, current_user)


@router.patch("/{machine_id}", response_model=MachineResponse)
def update_machine_config(
    machine_id: int,
    update_data: MachineUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Updates machine details like Name, Type, or Operational Status.
    Useful for renaming units or assigning them to different service zones.

    UPDATED: machine_controller.update_machine() now takes current_user
    (not shop_id) so the resulting Activity Log entry can attribute this
    action to whoever performed it.
    """
    return machine_controller.update_machine(db, machine_id, update_data, current_user)


@router.delete("/{machine_id}", status_code=status.HTTP_200_OK)
def remove_machine(
    machine_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Decommissions a hardware unit.
    Uses the controller's delete logic which handles SET NULL constraints,
    ensuring machine records are removed without breaking historical booking logs.

    UPDATED: machine_controller.delete_machine() now takes current_user
    (not shop_id) for Activity Log attribution.
    """
    return machine_controller.delete_machine(db, machine_id, current_user)


@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def setup_default_machines(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Bootstrap endpoint to deploy a standard hardware grid (6 Washers, 6 Dryers)
    for the logged-in user's own shop.

    UPDATED: machine_controller.initialize_shop_machines() now takes
    current_user (not shop_id) for Activity Log attribution.
    """
    return machine_controller.initialize_shop_machines(db, current_user)


@router.patch("/{machine_id}/maintenance", response_model=MachineResponse)
def toggle_maintenance(
    machine_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Toggles the maintenance state of a specific unit.
    Prevents the machine from appearing in the 'Available' list during booking
    while signaling the frontend to display a 'Rose' (Critical) color state.

    UPDATED: machine_controller.toggle_machine_maintenance() now takes
    current_user (not shop_id) for Activity Log attribution.
    """
    return machine_controller.toggle_machine_maintenance(
        db=db,
        machine_id=machine_id,
        current_user=current_user
    )


@router.get("/{machine_id}/metrics", response_model=MachineResponse)
def get_machine_telemetry(
    machine_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    High-frequency endpoint for the Monitoring Dashboard.
    Forces a recalculation of predictive overhead metrics to catch
    performance drops.
    Read-only — no controller signature change needed here.
    """
    return machine_controller.get_machine_by_id(
        db=db,
        machine_id=machine_id,
        shop_id=current_user.shop_id
    )


@router.post("/reset-all", status_code=status.HTTP_200_OK)
def reset_all_statuses(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Emergency override to set all of the logged-in user's shop machines
    back to 'Available'. Useful for system synchronization after server
    restarts or testing cycles.

    UPDATED: machine_controller.reset_all_machines() now takes
    current_user (not shop_id) for Activity Log attribution.
    """
    return machine_controller.reset_all_machines(db, current_user)