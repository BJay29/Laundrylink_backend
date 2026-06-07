"""
ANALYTICS ROUTES — app/routes/analytics_routes.py
==================================================
Exposes all analytics, forecasting, and AI-driven endpoints
consumed by the LaundryLink dashboard frontend.

NEW: /analytics/customer-segments — K-Means behavioral segmentation.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.controller.analytics_controller import AnalyticsController
from app.services.analytics_service import AnalyticsService

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"]
)


@router.get("/dashboard-summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    """
    Returns aggregated KPI data for the main dashboard:
    today's revenue, active machines, service breakdown, and AI forecast.
    """
    try:
        shop_id = 1
        return AnalyticsController.get_dashboard_summary(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/forecast-graph")
def get_forecast_graph(db: Session = Depends(get_db)):
    """
    Returns the 7-day AI income and booking forecast data
    along with the AI-generated executive insight narrative.
    """
    try:
        shop_id = 1
        return AnalyticsController.get_forecast_data(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/service-distribution")
def get_service_distribution(db: Session = Depends(get_db)):
    """
    Returns the count of each service type for pie/bar chart rendering.
    """
    try:
        shop_id = 1
        return AnalyticsController.get_service_distribution(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/operational-insights")
def get_operational_insights(db: Session = Depends(get_db)):
    """
    Returns the Decision Support System (DSS) operational insight
    for the Optimization Tip card on the dashboard.
    """
    try:
        return AnalyticsController.get_operational_insights(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weekly-history")
def get_weekly_history(db: Session = Depends(get_db)):
    """
    Returns the last 7 days of actual income data for the history modal.
    """
    try:
        shop_id = 1
        return AnalyticsController.get_weekly_history(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accuracy")
def get_accuracy_metrics(db: Session = Depends(get_db)):
    """
    Returns AI model accuracy metrics read from model_metrics.json.
    Used by the Financial Forecast page AI Calibration section.
    """
    try:
        return AnalyticsController.get_ai_prediction_metrics(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retrain-model")
def retrain_model():
    """
    Manually triggers the AI model retraining pipeline.
    Normally runs automatically every 24 hours via the scheduler.
    """
    try:
        from app.services.prediction_service import PredictionService
        PredictionService.retrain_model()
        return {"status": "success", "message": "Model retraining triggered successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER SEGMENTATION  — NEW ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/customer-segments")
def get_customer_segments(db: Session = Depends(get_db)):
    """
    NEW ENDPOINT
    Returns a list of customers segmented into behavioral tiers
    using K-Means clustering on visit frequency and total spending.

    Segments:
        - Occasional : low visit count and low total spend
        - Regular    : moderate visit count and spend
        - VIP        : high visit count and/or high total spend

    Falls back to rule-based thresholds when fewer than 3 unique
    customers exist in the database.

    Response shape per customer:
        {
            "customer_name":   "Juan Dela Cruz",
            "visit_frequency": 12,
            "total_spent":     2580.00,
            "avg_per_visit":   215.00,
            "segment":         "Regular",
            "segment_color":   "sky"
        }

    Error responses:
        404 — No booking data found for this shop.
        422 — Input data is malformed or missing required fields.
        500 — Unexpected ML or database error.
    """
    shop_id = 1
    return AnalyticsController.get_customer_segments(db, shop_id)