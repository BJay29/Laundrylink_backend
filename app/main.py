from dotenv import load_dotenv
load_dotenv()
import os
import re
import uvicorn
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from sqlalchemy import func
from app.database import engine, SessionLocal
from app import models
# Import routes
from app.routes import (
    auth_routes, customer_auth_routes, booking_routes, machine_routes,
    setting_routes, analytics_routes, inventory_routes, activity_routes,
    shop_routes, websocket_routes, addon_routes, promo_routes,
    notification_routes, address_routes,
    webhook_routes,  # NEW — Supabase Auth webhook sync endpoint
)
from sqlalchemy.orm import Session
# Imports for 24-hour automated retraining
from apscheduler.schedulers.background import BackgroundScheduler
from app.services.prediction_service import PredictionService
from app.routes import upload_routes


# Minimum na bilang ng ARAW na may bookings bago i-train ang sariling
# model ng isang shop (kapareho ng 14-day floor sa ml_engine/train.py).
MIN_TRAINING_DAYS = 14

# Gaano katagal maghihintay pagkatapos mag-boot ang server bago tumakbo
# ang unang training (para tapos na ang startup at hindi nagsasabay).
STARTUP_TRAINING_DELAY_SECONDS = 60


# --- DATABASE SEEDING & DATA INTEGRITY LOGIC ---

def seed_settings(db: Session):
    """
    Ensures that default optimization settings exist for shop_id=1.
    This runs ONLY if the settings table is empty for this shop.

    FIXED: ang dating default_settings ay gumagamit ng mga field na
    wala na sa models.Setting (full_service_price, regular_wash_price,
    titan_wash_price, comforter_price, detergent_cost_per_load) — kaya
    TypeError ("invalid keyword argument") ang tinatamaan nito tuwing
    walang settings ang shop 1. Ang mga presyo ay nasa ServiceType na
    ngayon, at supplies_cost_per_load na ang pangalan ng dating
    detergent_cost_per_load.
    """
    existing_settings = db.query(models.Setting).filter(models.Setting.shop_id == 1).first()
    
    if not existing_settings:
        print("Initial boot detected: No settings found for Shop 1. Seeding factory defaults...")
        
        default_settings = models.Setting(
            shop_id=1,
            operation_start_hour=8,
            electricity_rate=12.0,
            water_rate=50.0,
            supplies_cost_per_load=10.0,
            off_peak_hours="8:00 AM - 11:00 AM"
        )
        db.add(default_settings)
        db.commit()
        print("Default shop settings successfully seeded.")
    else:
        print("Shop settings already initialized. Preserving user modifications.")

def seed_hardware_and_inventory():
    """
    1. Initializes settings, machines, and ensures database tables are ready.
    2. Acts as a safety layer to prevent crashes on startup.
    """
    db = SessionLocal()
    try:
        # Initialize Settings
        seed_settings(db)

        # Fix legacy machine records by assigning them to shop_id 1
        null_machines = db.query(models.Machine).filter(models.Machine.shop_id == None).all()
        for m in null_machines:
            m.shop_id = 1
        db.commit()

        # Seed machines if none exist
        if db.query(models.Machine).count() == 0:
            print("Seeding default 12 hardware units...")
            machines = [models.Machine(machine_number=i, machine_type="Washer" if i<=6 else "Dryer", status="Available", shop_id=1) for i in range(1, 13)]
            db.add_all(machines)
            db.commit()
            
    except Exception as e:
        print(f"Database Initialization/Seeding Error: {e}")
        db.rollback()
    finally:
        db.close()


# --- AUTOMATED FORECAST RETRAINING ---

def retrain_all_shops():
    """
    NEW: nagre-retrain ng sariling forecast model ng BAWAT shop na may
    sapat na data (hindi na shop 1 lang — ang PredictionService.
    retrain_model() ay may default na shop_id=1, kaya dati ay shop 1
    lang ang natatrain ng scheduler at hindi kailanman nabubuo ang
    model ng mga bagong shop).

    Ang eligible na shop ay iyong may hindi bababa sa MIN_TRAINING_DAYS
    na ARAW na may kahit isang booking. Ang bawat shop ay sariling
    try/except, kaya kapag pumalya ang isa, tuloy pa rin ang iba.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(
                models.Booking.shop_id,
                func.count(func.distinct(func.date(models.Booking.created_at))).label("booking_days"),
            )
            .group_by(models.Booking.shop_id)
            .all()
        )
        eligible_shop_ids = [row.shop_id for row in rows if row.booking_days >= MIN_TRAINING_DAYS]
    except Exception as e:
        print(f"[{datetime.now()}] Could not determine shops to retrain: {e}")
        return
    finally:
        db.close()

    if not eligible_shop_ids:
        print(f"[{datetime.now()}] Retraining skipped: no shop has {MIN_TRAINING_DAYS}+ days of bookings yet.")
        return

    print(f"[{datetime.now()}] Retraining forecast models for shops: {eligible_shop_ids}")
    for shop_id in eligible_shop_ids:
        try:
            PredictionService.retrain_model(shop_id=shop_id)
        except Exception as e:
            print(f"[{datetime.now()}] Retraining failed for shop {shop_id}: {e}")

# --- LIFESPAN MANAGER ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles backend startup and shutdown sequences.
    """
    print("====================================================")
    print("LaundryLink Backend: Initialization Sequence Started")
    
    # Initialize Scheduler
    scheduler = BackgroundScheduler()
    
    try:
        # Syncing SQLAlchemy models with the database schema
        models.Base.metadata.create_all(bind=engine)
        print("PostgreSQL Schema Synchronization: COMPLETE")
        
        # Trigger data seeding
        seed_hardware_and_inventory()

        # Initialize Automated 24-hour Retraining Scheduler
        #
        # UPDATED: (1) lahat ng eligible na shop ang tina-train, hindi
        # shop 1 lang; (2) may unang takbo ilang segundo pagkatapos
        # mag-boot — kailangan ito dahil sa Render, ang ml_models/ ay
        # nabubura sa bawat deploy/restart (at natutulog ang libreng
        # instance kapag walang gumagamit), kaya kung 24 oras lang ang
        # hihintayin, madalas ay wala pang model pagkatapos ng restart.
        scheduler.add_job(
            retrain_all_shops,
            'interval',
            hours=24,
            next_run_time=datetime.now() + timedelta(seconds=STARTUP_TRAINING_DELAY_SECONDS),
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        print("AI Engine Scheduler: Automated 24-hour Training ONLINE "
              f"(first run in {STARTUP_TRAINING_DELAY_SECONDS}s)")
        
    except Exception as e:
        print(f"Critical System Boot Error: {e}")
        
    print("Status: Profit Optimization Engine Online")
    print("====================================================")
    
    yield  # Application runs here
    
    # Graceful shutdown
    print("LaundryLink Backend: Initiating Graceful Shutdown...")
    if scheduler.running:
        scheduler.shutdown()
    print("AI Engine Scheduler: SHUTDOWN")

# --- FASTAPI INSTANCE ---

app = FastAPI(
    title="LaundryLink API",
    description="Intelligent Backend for Laundry Income Optimization & Hardware Management",
    version="1.2.1",
    lifespan=lifespan
)

# --- CORS MIDDLEWARE ---
ALLOWED_ORIGINS = [
    "https://laundry-link-kappa.vercel.app",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://localhost:5000",   
    "http://127.0.0.1:5000",
]

# NEW — regex na tumutugma sa KAHIT ANONG port sa localhost/127.0.0.1.
# Kailangan ito dahil ang Flutter web (flutter run -d chrome) ay
# gumagamit ng RANDOM PORT bawat run (hal. localhost:55095, iba ulit
# sa susunod) — imposibleng i-hardcode lahat sa ALLOWED_ORIGINS list
# sa itaas. Dev/testing convenience lang ito — hindi ito nagbibigay-daan
# sa mga production domain maliban sa eksaktong nakalista sa
# ALLOWED_ORIGINS.
LOCALHOST_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1):\d+$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=LOCALHOST_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
 
# --- GLOBAL EXCEPTION HANDLER ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    UPDATED: ang dating "if origin in ALLOWED_ORIGINS" check ay hindi
    kasama ang random Chrome dev ports (hal. localhost:55095) — kaya
    kahit successful na ang CORSMiddleware sa normal na requests,
    kapag may 500 error na naman (papasok dito ang handler na ito),
    mawawala ulit ang Access-Control-Allow-Origin header, at babalik
    ang parehong CORS error sa browser console kahit hindi na talaga
    tungkol sa CORS ang totoong problema. Ngayon, gumagamit na rin ito
    ng parehong LOCALHOST_ORIGIN_REGEX para tumugma sa localhost origin
    ORIGIN CHECK, kaparehong lohika ng CORSMiddleware mismo.
    """
    origin = request.headers.get("origin", "")
    headers = {}

    is_allowed = origin in ALLOWED_ORIGINS or bool(re.match(LOCALHOST_ORIGIN_REGEX, origin))

    if is_allowed:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"

    print(f"Unhandled server error on {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}"},
        headers=headers,
    )

# --- ROUTER REGISTRATION ---

app.include_router(auth_routes.router)
app.include_router(customer_auth_routes.router)
app.include_router(booking_routes.router)
app.include_router(machine_routes.router)
app.include_router(setting_routes.router)
app.include_router(analytics_routes.router)
app.include_router(inventory_routes.router)
app.include_router(activity_routes.router)
app.include_router(shop_routes.router)
app.include_router(websocket_routes.router)
app.include_router(addon_routes.router)
app.include_router(promo_routes.router)
app.include_router(upload_routes.router)
# NEW — notification bell/page endpoints (GET /notifications/mine,
# GET /notifications/unread-count, PATCH /notifications/{id}/read,
# PATCH /notifications/mark-all-read).
app.include_router(notification_routes.router)
# NEW — customer's saved addresses (GET /addresses/mine, POST /addresses/,
# PATCH /addresses/{id}, DELETE /addresses/{id}).
app.include_router(address_routes.router)
# NEW — Supabase Auth Database Webhook receiver (POST
# /webhooks/supabase-auth). Ito ang tinatawag ng Supabase kapag
# na-verify na ng isang user (customer o owner/staff) ang kanilang
# email/OTP, at dito sini-sync ang kanilang supabase_uid papunta sa
# Aiven Postgres (models.Customer o models.User).
app.include_router(webhook_routes.router)

# --- ROOT HEALTH CHECK ---

@app.get("/")
def read_root():
    return {
        "status": "Online",
        "system": "LaundryLink Optimization Engine",
        "database": "PostgreSQL Connected",
        "modules_active": [
            "Auth", "CustomerAuth", "Bookings", "Machines", "Settings",
            "Analytics", "Inventory", "Activity", "Shops", "Notifications",
            "Addresses", "AddOns", "PromoCodes",
            "SupabaseAuthWebhook",  # NEW
        ]
    }

# --- PRODUCTION ENTRY POINT ---

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)