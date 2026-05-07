from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import MachineResponse, MachineCreate
from app.controller import machine_controller

# API Router for Hardware Management and Real-Time Monitoring
router = APIRouter(
    prefix="/machines",
    tags=["Machines"]
)

@router.get("/", response_model=List[MachineResponse])
def get_machines(db: Session = Depends(get_db)):
    """
    Fetches real-time status and performance metrics for all units.
    The controller calculates unique overhead costs per machine based on 
    specific consumption history, ensuring accurate data for the Machine Hub.
    """
    # Hardcoded shop_id=1 for current development and testing phase
    shop_id = 1
    return machine_controller.get_all_machines(db, shop_id=shop_id)

@router.post("/", response_model=MachineResponse, status_code=status.HTTP_201_CREATED)
def add_new_machine(machine_data: MachineCreate, db: Session = Depends(get_db)):
    """
    Adds a new machine unit to the database configuration.
    Initializes the unit with zero cycles and sets efficiency rates 
    based on the machine type (e.g., Washers vs. Dryers).
    """
    shop_id = 1
    return machine_controller.create_machine(db, machine_data, shop_id)

@router.delete("/{machine_id}", status_code=status.HTTP_200_OK)
def remove_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Permanently deletes a machine record.
    Used for decommissioning old hardware or correcting setup errors.
    """
    shop_id = 1
    return machine_controller.delete_machine(db, machine_id, shop_id)

@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def setup_default_machines(db: Session = Depends(get_db)):
    """
    Bootstrap endpoint to deploy a standard 12-unit hardware grid (6 Washers, 6 Dryers).
    Each unit is initialized with default consumption rates to enable 
    immediate profitability tracking in the dashboard.
    """
    shop_id = 1
    return machine_controller.initialize_shop_machines(db, shop_id)

@router.patch("/{machine_id}/maintenance", response_model=MachineResponse)
def toggle_maintenance(machine_id: int, db: Session = Depends(get_db)):
    """
    Toggles the maintenance state of a specific machine.
    Locking a machine prevents it from being selected in the booking flow 
    and clears active timers while preserving its historical profit data.
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
    Dedicated endpoint for the Monitoring Dashboard cards to fetch fresh cost analytics.
    It calls the PredictionService to return the current cost breakdown 
    (Electricity, Water, Detergent) based on the latest rates.
    """
    shop_id = 1
    # The controller's get_machine_by_id automatically re-calculates the 
    # overhead metrics using the PredictionService.
    return machine_controller.get_machine_by_id(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )

@router.get("/{machine_id}", response_model=MachineResponse)
def get_single_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the full profile and financial metrics for a single hardware unit.
    Used for detailed reporting or when editing individual machine configurations.
    """
    shop_id = 1
    return machine_controller.get_machine_by_id(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )