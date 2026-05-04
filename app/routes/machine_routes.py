from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import MachineResponse
from app.controller import machine_controller

router = APIRouter(
    prefix="/machines",
    tags=["Machines"]
)

@router.get("/", response_model=List[MachineResponse])
def get_machines(db: Session = Depends(get_db)):
    """
    Fetches the real-time status of all 12 machines (6 washers, 6 dryers).
    Used by the Machine Hub and Real-time Monitoring dashboard.
    """
    # Hardcoded shop_id=1 for development/testing phase
    shop_id = 1
    return machine_controller.get_all_machines(db, shop_id=shop_id)

@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def setup_default_machines(db: Session = Depends(get_db)):
    """
    One-time setup route to populate the database with the standard 12-unit configuration.
    Run this once to see the grid populated in your Monitoring Hub.
    """
    shop_id = 1
    return machine_controller.initialize_shop_machines(db, shop_id)

@router.patch("/{machine_id}/maintenance", response_model=MachineResponse)
def toggle_maintenance(machine_id: int, db: Session = Depends(get_db)):
    """
    Toggles the maintenance state of a specific machine.
    Blocks the machine from new bookings if enabled.
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
    Triggers a recalculation of profitability and efficiency for a specific unit.
    Useful for refreshing dashboard charts.
    """
    shop_id = 1
    return machine_controller.update_machine_metrics(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )

@router.get("/{machine_id}", response_model=MachineResponse)
def get_single_machine(machine_id: int, db: Session = Depends(get_db)):
    """
    Retrieves detailed information for a single hardware unit.
    """
    shop_id = 1
    return machine_controller.get_machine_by_id(
        db=db, 
        machine_id=machine_id, 
        shop_id=shop_id
    )