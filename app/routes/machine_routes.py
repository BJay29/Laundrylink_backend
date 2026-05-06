from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import MachineResponse, MachineCreate
from app.controller import machine_controller

# API Router for Hardware Management and Monitoring
router = APIRouter(
    prefix="/machines",
    tags=["Machines"]
)

@router.get("/", response_model=List[MachineResponse])
def get_machines(db: Session = Depends(get_db)):
    """
    Fetches real-time status and independent performance metrics for all units.
    The controller now calculates unique overhead costs per machine based on 
    their specific cycle history rather than global averages.
    """
    # Hardcoded shop_id=1 for current development/testing phase
    shop_id = 1
    return machine_controller.get_all_machines(db, shop_id=shop_id)

@router.post("/", response_model=MachineResponse, status_code=status.HTTP_201_CREATED)
def add_new_machine(machine_data: MachineCreate, db: Session = Depends(get_db)):
    """
    Adds a new machine unit to the shop configuration.
    Initializes the unit with a 0 cycle count and type-specific efficiency rates 
    (e.g., higher electricity rates for Dryers).
    """
    shop_id = 1
    return machine_controller.create_machine(db, machine_data, shop_id)

@router.delete("/{machine_id}", status_code=status.HTTP_200_OK)
def remove_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Permanently removes a machine record from the inventory.
    Useful for hardware decommissioning or replacing old units.
    """
    shop_id = 1
    return machine_controller.delete_machine(db, machine_id, shop_id)

@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def setup_default_machines(db: Session = Depends(get_db)):
    """
    Bootstrap route to deploy a standard 12-unit hardware grid (6 Washers, 6 Dryers).
    Each machine is deployed with independent tracking enabled to ensure 
    distinct performance data in the Machine Hub dashboard.
    """
    shop_id = 1
    return machine_controller.initialize_shop_machines(db, shop_id)

@router.patch("/{machine_id}/maintenance", response_model=MachineResponse)
def toggle_maintenance(machine_id: int, db: Session = Depends(get_db)):
    """
    Toggles the maintenance state of a specific machine.
    This effectively 'locks' the machine from the Service Terminal booking flow 
    and resets active timers without losing the accumulated cycle history.
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
    Dedicated endpoint for the Monitoring Grid cards to fetch fresh cost analytics.
    It leverages the PredictionService to return the specific cost hierarchy 
    (Electricity > Water > Detergent) for the requested machine.
    """
    shop_id = 1
    # The controller's get_machine_by_id automatically triggers the 
    # PredictionService with the specific machine's historical data.
    return machine_controller.get_machine_by_id(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )

@router.get("/{machine_id}", response_model=MachineResponse)
def get_single_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the complete hardware profile and performance metrics for a single unit.
    Used when viewing a detailed machine report or editing hardware settings.
    """
    shop_id = 1
    return machine_controller.get_machine_by_id(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )