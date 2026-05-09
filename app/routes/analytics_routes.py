from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.controller.analytics_controller import AnalyticsController

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"]
)

# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/dashboard-summary")
def get_summary(db: Session = Depends(get_db)):
    """
    Endpoint for the top summary cards (Revenue, Growth, Active Machines, AI Prediction).
    """
    try:
        # Defaulting to shop_id=1 for your current project setup
        summary = AnalyticsController.get_dashboard_summary(db, shop_id=1)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching dashboard summary: {str(e)}")

@router.get("/forecast-graph")
def get_forecast(db: Session = Depends(get_db)):
    """
    Endpoint for the Recharts graph showing historical trends and 7-day AI forecasts.
    """
    try:
        forecast_data = AnalyticsController.get_forecast_data(db, shop_id=1)
        return forecast_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating forecast: {str(e)}")

@router.get("/service-distribution")
def get_distribution(db: Session = Depends(get_db)):
    """
    Endpoint for the pie chart showing which services are most popular.
    This helps the user see if the AI weights match reality.
    """
    try:
        distribution = AnalyticsController.get_service_distribution(db, shop_id=1)
        return distribution
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching service distribution: {str(e)}")