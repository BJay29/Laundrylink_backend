from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.controller.analytics_controller import AnalyticsController
from app.services.analytics_service import AnalyticsService, SEGMENTATION_WINDOW_DAYS
from app.security import get_current_shop_id  # ⬅️ BAGONG IMPORT

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"]
)


@router.get("/dashboard-summary")
def get_dashboard_summary(
    shop_id: int = Depends(get_current_shop_id),  # ⬅️ FIXED: galing sa JWT, hindi na hardcoded 1
    db: Session = Depends(get_db)
):
    """
    Returns aggregated KPI data for the main dashboard:
    today's revenue, active machines, service breakdown, and AI forecast.
    """
    try:
        return AnalyticsController.get_dashboard_summary(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/forecast-graph")
def get_forecast_graph(
    shop_id: int = Depends(get_current_shop_id),  # ⬅️ FIXED
    db: Session = Depends(get_db)
):
    """
    Returns the 7-day AI income and booking forecast data
    along with the AI-generated executive insight narrative.

    Each row now includes "model_tier" ("shop_model" | "pooled_model" |
    "weather_only") and "rain_mm" — see AnalyticsController.get_forecast_data()
    and PredictionService.get_revenue_forecast() for the 3-tier fallback.
    """
    try:
        return AnalyticsController.get_forecast_data(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/service-distribution")
def get_service_distribution(
    shop_id: int = Depends(get_current_shop_id),  # ⬅️ FIXED
    db: Session = Depends(get_db)
):
    """
    Returns the count of each service type for pie/bar chart rendering.
    """
    try:
        return AnalyticsController.get_service_distribution(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/operational-insights")
def get_operational_insights(
    shop_id: int = Depends(get_current_shop_id),  # ⬅️ FIXED — dating walang shop_id kahit paano
    db: Session = Depends(get_db)
):
    """
    Returns the Decision Support System (DSS) operational insight
    for the Optimization Tip card on the dashboard.

    NOTE: shop_id is now resolved from the JWT and passed through, but
    AnalyticsController.get_operational_insights() and the underlying
    insight_engine.generate_operational_insight() still need to be
    reviewed to confirm they actually filter by shop_id internally
    (rather than querying across all shops). Flagging this — the
    controller signature below is updated defensively, but the engine
    itself needs a look before this is fully verified as shop-scoped.
    """
    try:
        return AnalyticsController.get_operational_insights(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weekly-history")
def get_weekly_history(
    shop_id: int = Depends(get_current_shop_id),  # ⬅️ FIXED
    db: Session = Depends(get_db)
):
    """
    Returns the last 7 days of actual income data for the history modal.
    """
    try:
        return AnalyticsController.get_weekly_history(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accuracy")
def get_accuracy_metrics(db: Session = Depends(get_db)):
    """
    Returns AI model accuracy metrics read from model_metrics.json.
    Used by the Financial Forecast page AI Calibration section.
    Not shop-specific — this reflects whichever shop-specific model was
    trained most recently, so no shop_id is needed here.
    """
    try:
        return AnalyticsController.get_ai_prediction_metrics(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retrain-model")
def retrain_model(
    shop_id: int = Depends(get_current_shop_id),  # ⬅️ FIXED: dating always shop_id=1 regardless of caller
    db: Session = Depends(get_db)
):
    """
    Manually triggers the AI model retraining pipeline for the LOGGED-IN
    user's own shop. Normally runs automatically every 24 hours via the
    scheduler.

    FIXED: this previously called PredictionService.retrain_model() with
    no arguments, which trained shop_id=1's model regardless of which
    shop the caller actually belonged to — meaning any owner clicking
    "Retrain Model" was silently retraining shop 1's forecast, not
    their own. It now trains the caller's own shop.

    Requires 14+ days of this shop's own booking history — if the shop
    doesn't have that yet, the forecast graph will keep serving from the
    pooled/weather-only fallback tiers until it does.
    """
    try:
        from app.services.prediction_service import PredictionService
        PredictionService.retrain_model(shop_id=shop_id)
        return {"status": "success", "message": f"Model retraining triggered successfully for shop {shop_id}."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retrain-pooled-model")
def retrain_pooled_model(
    shop_id: int = Depends(get_current_shop_id),  # auth-gated, but not shop-scoped — see NOTE below
    db: Session = Depends(get_db)
):
    """
    NEW — manually triggers training of the pooled/cold-start model
    across every shop with enough history to contribute (see
    ml_engine.data_prep.fetch_pooled_daily_frame). This is what powers
    Tier 2 of a new shop's forecast, before that shop has trained a
    model of its own.

    NOTE: this affects the WHOLE platform's pooled model, not just the
    caller's shop — shop_id here is only used to confirm the caller is
    authenticated, same auth dependency as every other endpoint in this
    file. If you want this restricted to owners only (rather than any
    logged-in staff/manager), add a role check here once your role
    dependency is available — none of the other /analytics endpoints
    currently do role checks either, so this matches existing behavior
    until that's decided.
    """
    try:
        from app.services.prediction_service import PredictionService
        PredictionService.retrain_pooled_model()
        return {"status": "success", "message": "Pooled model retraining triggered successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER SEGMENTATION ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/customer-segments")
def get_customer_segments(
    shop_id: int = Depends(get_current_shop_id),  # ⬅️ FIXED: dating hardcoded 1
    db: Session = Depends(get_db)
):
    """
    Returns a list of customers segmented into behavioral tiers using
    K-Means clustering on visit frequency and total spending.

    FIXED: shop_id was previously hardcoded to 1 for EVERY logged-in
    user, regardless of which shop they actually belonged to — this was
    the root cause of the Customer Hub showing the wrong (or no)
    customers per shop. It now comes from the authenticated user's JWT,
    same as every other protected endpoint in this file.

    BEHAVIOUR (unchanged):
        - Only bookings from the last 18 days are included (rolling window).
        - Mock / test records (is_mock = True) are excluded before clustering.
        - Falls back to rule-based thresholds when fewer than 3 unique real
          customers exist within the 18-day window.

    Response envelope:
        {
            "window_days":  18,
            "window_start": "2026-05-20",
            "customers": [...]
        }

    Error responses:
        404 — No real bookings found in the last 18 days for THIS shop.
        422 — Input data is malformed or missing required fields.
        500 — Unexpected ML or database error.
    """
    window_start = (datetime.now() - timedelta(days=SEGMENTATION_WINDOW_DAYS)).strftime("%Y-%m-%d")

    # Delegate to controller — raises HTTPException on error
    customers = AnalyticsController.get_customer_segments(db, shop_id)

    # Wrap in an envelope that exposes the active window to the frontend
    return {
        "window_days":  SEGMENTATION_WINDOW_DAYS,
        "window_start": window_start,
        "customers":    customers,
    }