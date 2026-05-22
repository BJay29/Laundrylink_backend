from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import engine, SessionLocal
from app import models
# Import inventory_routes and all other modules
from app.routes import (
    auth_routes, 
    booking_routes, 
    machine_routes, 
    setting_routes, 
    analytics_routes, 
    inventory_routes
)
from sqlalchemy.orm import Session

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

        # Fix legacy machine records
        null_machines = db.query(models.Machine).filter(models.Machine.shop_id == None).all()
        for m in null_machines:
            m.shop_id = 1
        db.commit()

        # Check machines
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
    
    try:
        # Syncing SQLAlchemy models with the database schema
        models.Base.metadata.create_all(bind=engine)
        print("PostgreSQL Schema Synchronization: COMPLETE")
        
        # Trigger data seeding
        seed_hardware_and_inventory()
        
    except Exception as e:
        print(f"Critical System Boot Error: {e}")
        
    print("Status: Profit Optimization Engine Online")
    print("====================================================")
    
    yield  
    
    print("LaundryLink Backend: Initiating Graceful Shutdown...")

# --- FASTAPI INSTANCE ---

app = FastAPI(
    title="LaundryLink API",
    description="Intelligent Backend for Laundry Income Optimization & Hardware Management",
    version="1.2.1",
    lifespan=lifespan
)

# --- CORS MIDDLEWARE FIX ---

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ROUTER REGISTRATION ---

app.include_router(auth_routes.router, prefix="/api/auth", tags=["Auth"])
app.include_router(booking_routes.router, prefix="/api/bookings", tags=["Bookings"])
app.include_router(machine_routes.router, prefix="/api/machines", tags=["Machines"])
app.include_router(setting_routes.router, prefix="/api/settings", tags=["Settings"])
app.include_router(analytics_routes.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(inventory_routes.router, prefix="/api/inventory", tags=["Inventory"])

# --- ROOT HEALTH CHECK ---

@app.get("/")
def read_root():
    return {
        "status": "Online",
        "system": "LaundryLink Optimization Engine",
        "database": "PostgreSQL Connected",
        "modules_active": ["Auth", "Bookings", "Machines", "Settings", "Analytics", "Inventory"]
    }