from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import MachineResponse, MachineCreate, MachineUpdate
from app.controller import machine_controller

# API Router for Hardware Management and Real-Time Telemetry
router = APIRouter(
    prefix="/machines",
    tags=["Machines"]
)

@router.get("/", response_model=List[MachineResponse])
def get_machines(db: Session = Depends(get_db)):
    """
    Fetches real-time status and performance metrics for all shop units.
    The controller aggregates overhead costs (Electricity, Water, Detergent)
    to provide the Machine Hub with current profitability data.
    """
    # Hardcoded shop_id=1 for Naga College Foundation development phase
    shop_id = 1
    return machine_controller.get_all_machines(db, shop_id=shop_id)

@router.post("/", response_model=MachineResponse, status_code=status.HTTP_201_CREATED)
def add_new_machine(machine_data: MachineCreate, db: Session = Depends(get_db)):
    """
    Registers a new hardware unit.
    Initializes consumption coefficients based on type (Washer vs. Dryer)
    to ensure immediate tracking accuracy.
    """
    shop_id = 1
    return machine_controller.create_machine(db, machine_data, shop_id)

@router.patch("/{machine_id}", response_model=MachineResponse)
def update_machine_config(
    machine_id: int, 
    update_data: MachineUpdate, 
    db: Session = Depends(get_db)
):
    """
    Updates machine details like Name, Type, or Operational Status.
    Useful for renaming units or assigning them to different service zones.
    """
    shop_id = 1
    return machine_controller.update_machine(db, machine_id, update_data, shop_id)

@router.delete("/{machine_id}", status_code=status.HTTP_200_OK)
def remove_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Decommissions a hardware unit.
    Removes the record from active monitoring while allowing historical 
    booking data to remain for financial reporting integrity.
    """
    shop_id = 1
    return machine_controller.delete_machine(db, machine_id, shop_id)

@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def setup_default_machines(db: Session = Depends(get_db)):
    """
    Bootstrap endpoint to deploy a standard hardware grid (6 Washers, 6 Dryers).
    Each unit is pre-configured with standard consumption rates 
    compatible with the current PHP utility prices.
    """
    shop_id = 1
    return machine_controller.initialize_shop_machines(db, shop_id)

@router.patch("/{machine_id}/maintenance", response_model=MachineResponse)
def toggle_maintenance(machine_id: int, db: Session = Depends(get_db)):
    """
    Toggles the maintenance state of a specific unit.
    Prevents the machine from appearing in the 'Available' list during booking
    while signaling the frontend to display a 'Rose' (Critical) color state.
    """
    shop_id = 1
    return machine_controller.toggle_machine_maintenance(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )

@router.get("/{machine_id}/metrics", response_model=MachineResponse)
def get_machine_telemetry(machine_id: int, db: Session = Depends(get_db)):
    """
    High-frequency endpoint for the Monitoring Dashboard.
    Forces a recalculation of predictive overhead metrics to catch 
    sudden spikes in utility usage or performance drops.
    """
    shop_id = 1
    return machine_controller.get_machine_by_id(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )

@router.post("/reset-all", status_code=status.HTTP_200_OK)
def reset_all_statuses(db: Session = Depends(get_db)):
    """
    Emergency override to set all shop machines back to 'Available'.
    Useful for system synchronization after server restarts or testing cycles.
    """
    shop_id = 1
    return machine_controller.reset_all_machines(db, shop_id)