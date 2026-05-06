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
    Fetches real-time status and predictive performance metrics for all machines.
    This data populates the Machine Hub table and the Monitoring Grid cards.
    """
    # Hardcoded shop_id=1 for the current development phase.
    # The controller includes auto-fix logic for any NULL shop_id records.
    shop_id = 1
    return machine_controller.get_all_machines(db, shop_id=shop_id)

@router.post("/", response_model=MachineResponse, status_code=status.HTTP_201_CREATED)
def add_new_machine(machine_data: MachineCreate, db: Session = Depends(get_db)):
    """
    Adds a new machine unit to the shop configuration.
    Typically triggered via the 'Add Machine' modal in the dashboard.
    """
    shop_id = 1
    return machine_controller.create_machine(db, machine_data, shop_id)

@router.delete("/{machine_id}", status_code=status.HTTP_200_OK)
def remove_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Permanently removes a machine unit from the shop hardware inventory.
    """
    shop_id = 1
    return machine_controller.delete_machine(db, machine_id, shop_id)

@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def setup_default_machines(db: Session = Depends(get_db)):
    """
    Initial setup route to populate the database with a standard 12-unit configuration.
    Deploys 6 Washers (W1-W6) and 6 Dryers (D1-D6) for the shop.
    """
    shop_id = 1
    return machine_controller.initialize_shop_machines(db, shop_id)

@router.patch("/{machine_id}/maintenance", response_model=MachineResponse)
def toggle_maintenance(machine_id: int, db: Session = Depends(get_db)):
    """
    Toggles the maintenance state of a specific machine.
    Units marked as 'Maintenance' are restricted from new laundry bookings.
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
    Fetches the latest operational efficiency and cost metrics for a specific unit.
    Uses the PredictionService to calculate overhead based on total cycles.
    """
    shop_id = 1
    # Note: The controller's get_machine_by_id now automatically 
    # attaches the updated PredictionService metrics.
    return machine_controller.get_machine_by_id(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )

@router.get("/{machine_id}", response_model=MachineResponse)
def get_single_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the complete hardware profile and performance data for a single machine ID.
    """
    shop_id = 1
    return machine_controller.get_machine_by_id(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )