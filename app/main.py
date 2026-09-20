from dotenv import load_dotenv
load_dotenv()
import os
import re
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
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


# --- DATABASE SEEDING & DATA INTEGRITY LOGIC ---

def seed_settings(db: Session):
    """
    Ensures that default optimization settings exist for shop_id=1.
    This runs ONLY if the settings table is empty for this shop.
    """
    existing_settings = db.query(models.Setting).filter(models.Setting.shop_id == 1).first()
    
    if not existing_settings:
        print("Initial boot detected: No settings found for Shop 1. Seeding factory defaults...")
        
        default_settings = models.Setting(
            shop_id=1,
            operation_start_hour=8,
            full_service_price=210.0,
            regular_wash_price=65.0,  
            titan_wash_price=100.0,   
            comforter_price=150.0,    
            electricity_rate=12.0,
            water_rate=50.0,
            detergent_cost_per_load=10.0,
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
        scheduler.add_job(PredictionService.retrain_model, 'interval', hours=24)
        scheduler.start()
        print("AI Engine Scheduler: Automated 24-hour Training ONLINE")
        
    except Exception as e:
        print(f"Critical System Boot Error: {e}")
        
    print("Status: Profit Optimization Engine Online")
    print("====================================================")
    
    yield  # Application runs here
    
    # Graceful shutdown
    print("LaundryLink Backend: Initiating Graceful Shutdown...")
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