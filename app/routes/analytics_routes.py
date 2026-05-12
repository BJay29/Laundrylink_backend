from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.controller.analytics_controller import AnalyticsController

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"]
)

# Dependency to provide a database session for each request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/operational-insights")
def get_insights(db: Session = Depends(get_db)):
    """
    Retrieve real-time operational insights.
    Analyzes machine health to calculate profit impact and 
    provides strategic suggestions for the shop owner.
    """
    try:
        # Fetches the decision support logic from the controller
        insights = AnalyticsController.get_operational_insights(db)
        return insights
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error generating operational insights: {str(e)}"
        )

@router.get("/dashboard-summary")
def get_summary(db: Session = Depends(get_db)):
    """
    Fetch comprehensive dashboard metrics.
    Returns:
    - Revenue and growth trends.
    - AI-predicted bookings vs projected income.
    - Actual totals for Full Service, Titan Wash, Regular Wash, and Comforter.
    - Aggregated total weight (kg) for current bookings.
    """
    try:
        # Defaulting to shop_id=1 for the current development phase
        summary = AnalyticsController.get_dashboard_summary(db, shop_id=1)
        return summary
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error fetching dashboard summary: {str(e)}"
        )

@router.get("/forecast-graph")
def get_forecast(db: Session = Depends(get_db)):
    """
    Generate data for the 7-day financial forecast chart.
    Returns a combined dataset of historical income trends and AI-driven future projections.
    """
    try:
        forecast_data = AnalyticsController.get_forecast_data(db, shop_id=1)
        return forecast_data
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error generating forecast data: {str(e)}"
        )

@router.get("/service-distribution")
def get_distribution(db: Session = Depends(get_db)):
    """
    Retrieve the service utilization breakdown for distribution charts.
    Provides a real-time count of bookings per service type to validate AI weighting logic.
    """
    try:
        distribution = AnalyticsController.get_service_distribution(db, shop_id=1)
        return distribution
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error fetching service distribution metrics: {str(e)}"
        )