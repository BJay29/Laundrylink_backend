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
    # Hardcoded shop_id=1 for initial testing
    shop_id = 1
    return machine_controller.get_all_machines(db, shop_id=shop_id)

@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def setup_default_machines(db: Session = Depends(get_db)):
    """
    One-time setup route to populate the database with 6 washers and 6 dryers.
    Run this once when you start the project to see data in your dashboard.
    """
    shop_id = 1
    return machine_controller.initialize_shop_machines(db, shop_id)

@router.patch("/{machine_id}/status", response_model=MachineResponse)
def update_machine(
    machine_id: int, 
    new_status: str, 
    db: Session = Depends(get_db)
):
    """
    Manually overrides a machine's status. 
    Useful for marking a machine as 'Out of Order' or 'Maintenance'.
    """
    shop_id = 1
    return machine_controller.update_machine_status(
        db=db, 
        machine_id=machine_id, 
        new_status=new_status, 
        shop_id=shop_id
    )