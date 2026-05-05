from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import MachineResponse, MachineCreate
from app.controller import machine_controller

router = APIRouter(
    prefix="/machines",
    tags=["Machines"]
)

@router.get("/", response_model=List[MachineResponse])
def get_machines(db: Session = Depends(get_db)):
    """
    Fetches the real-time status and performance metrics of all machines.
    This endpoint feeds both the Machine Hub table and the Monitoring Grid cards.
    """
    # Hardcoded shop_id=1 para sa current development phase.
    # Ang controller ay may auto-fix logic na rin para sa mga NULL shop_id.
    shop_id = 1
    return machine_controller.get_all_machines(db, shop_id=shop_id)

@router.post("/", response_model=MachineResponse, status_code=status.HTTP_201_CREATED)
def add_new_machine(machine_data: MachineCreate, db: Session = Depends(get_db)):
    """
    Adds a new machine unit to the shop's configuration.
    Triggered by the 'Add Machine' modal.
    """
    shop_id = 1
    return machine_controller.create_machine(db, machine_data, shop_id)

@router.delete("/{machine_id}", status_code=status.HTTP_200_OK)
def remove_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Permanently deletes a machine unit from the shop hardware list.
    """
    shop_id = 1
    return machine_controller.delete_machine(db, machine_id, shop_id)

@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def setup_default_machines(db: Session = Depends(get_db)):
    """
    One-time setup route to populate the database with a 12-unit configuration.
    Deploys 6 Washers (W1-W6) and 6 Dryers (D1-D6).
    """
    shop_id = 1
    return machine_controller.initialize_shop_machines(db, shop_id)

@router.patch("/{machine_id}/maintenance", response_model=MachineResponse)
def toggle_maintenance(machine_id: int, db: Session = Depends(get_db)):
    """
    Toggles the maintenance status of a specific machine unit.
    Units in 'Maintenance' are blocked from selection in the Booking Modal.
    """
    shop_id = 1
    return machine_controller.toggle_machine_maintenance(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )

@router.get("/{machine_id}/metrics", response_model=MachineResponse)
def get_updated_metrics(machine_id: int, db: Session = Depends(get_db)):
    """
    Triggers a manual recalculation of operational efficiency.
    """
    shop_id = 1
    return machine_controller.update_performance_metrics(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )

@router.get("/{machine_id}", response_model=MachineResponse)
def get_single_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the complete hardware and performance profile for a single machine ID.
    """
    shop_id = 1
    return machine_controller.get_machine_by_id(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )