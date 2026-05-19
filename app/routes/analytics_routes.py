from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.controller.analytics_controller import AnalyticsController

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics Hub"]
)

# Dependency to safely handle and instantiate a database connection session per request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/operational-insights")
def get_insights(db: Session = Depends(get_db)):
    """
    Retrieve real-time operational machine metrics and Decision Support System insights.
    Evaluates hardware failures to estimate profit loss and provide automated strategic remedies.
    """
    try:
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
    Fetch comprehensive dashboard KPIs, service counters, and historical trend comparisons.
    Returns:
    - Active revenue tracking and weekly growth metrics.
    - AI-predicted customer volumes vs projected daily target earnings.
    - Breakdown of services and total load capacity metrics in kilograms.
    """
    try:
        # Fetching summary which now includes last_week_revenue/bookings for trend calculation
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
    Generate data matrices for the 7-day linear forecast chart container.
    Merges historical business revenue streams with future model projections for comparison views.
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
    Retrieve product category distributions for charting systems.
    Provides live segmentation counters per service item to continuously calibrate AI models.
    """
    try:
        distribution = AnalyticsController.get_service_distribution(db, shop_id=1)
        return distribution
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error fetching service distribution metrics: {str(e)}"
        )

@router.get("/accuracy")
def get_ai_accuracy(db: Session = Depends(get_db)):
    """
    Retrieve statistical model accuracy calibrations and calibration configurations.
    Evaluates historical telemetry metrics to map variance indices for predictive 
    demand subsystems alongside utility consumption checking matrices.
    """
    try:
        accuracy_metrics = AnalyticsController.get_ai_prediction_metrics(db)
        return accuracy_metrics
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error executing AI accuracy model evaluation: {str(e)}"
        )