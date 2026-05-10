from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import engine, SessionLocal
from app import models
# Added analytics_routes to the imports
from app.routes import auth_routes, booking_routes, machine_routes, setting_routes, analytics_routes
from sqlalchemy.orm import Session

# --- UPDATED SEEDING & DATA INTEGRITY LOGIC ---

def seed_settings(db: Session):
    """
    Ensures that default optimization settings exist for shop_id=1.
    This runs ONLY if the settings table is empty for this shop.
    Initializes pricing based on the standard college project requirements.
    """
    existing_settings = db.query(models.Setting).filter(models.Setting.shop_id == 1).first()
    
    if not existing_settings:
        print("Initial boot detected: No settings found for Shop 1. Seeding factory defaults...")
        
        # Default configuration used only for first-time setup.
        # Once seeded, the system will prioritize user updates in the DB.
        default_settings = models.Setting(
            shop_id=1,
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
        print("Shop settings already initialized. Skipping seed to preserve user modifications.")

def seed_machines():
    """
    1. Verifies existing hardware and updates any legacy NULL shop_ids to 1.
    2. Populates an empty machine table with 6 Washers and 6 Dryers.
    """
    db = SessionLocal()
    try:
        # Initialize Settings first to ensure the shop structure exists
        seed_settings(db)

        # Fix legacy data: Convert machines with NULL shop_id to default shop_id=1
        null_machines = db.query(models.Machine).filter(models.Machine.shop_id == None).all()
        if null_machines:
            print(f"Repair Mode: Found {len(null_machines)} machines with NULL shop_id. Fixing now...")
            for m in null_machines:
                m.shop_id = 1
            db.commit()
            print("Legacy hardware records successfully mapped to shop_id=1.")

        # Initial hardware seeding for fresh database installations
        machine_count = db.query(models.Machine).count()
        
        if machine_count == 0:
            print("Hardware Hub empty. Seeding 12 machine units with shop_id=1...")
            
            machines_to_add = []
            
            # Create 6 Washers (Assigned to shop_id=1)
            for i in range(1, 7):
                machines_to_add.append(
                    models.Machine(
                        machine_number=i, 
                        machine_type="Washer", 
                        status="Available",
                        shop_id=1
                    )
                )
            
            # Create 6 Dryers (Assigned to shop_id=1)
            for i in range(1, 7):
                machines_to_add.append(
                    models.Machine(
                        machine_number=i, 
                        machine_type="Dryer", 
                        status="Available",
                        shop_id=1
                    )
                )
            
            db.add_all(machines_to_add)
            db.commit()
            print(f"Successfully deployed {len(machines_to_add)} hardware units to Shop 1.")
        else:
            print(f"Machine Hub active: {machine_count} units detected. Seed skipped.")
            
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
    Ensures PostgreSQL table synchronization and data seeding on boot.
    """
    print("====================================================")
    print("LaundryLink Backend: Initialization Sequence Started")
    
    try:
        # Syncing SQLAlchemy models with the database schema
        models.Base.metadata.create_all(bind=engine)
        print("PostgreSQL Schema Synchronization: COMPLETE")
        
        # Trigger data seeding and hardware integrity checks
        seed_machines()
        
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
    version="1.2.0",
    lifespan=lifespan
)

# --- CORS MIDDLEWARE ---
# Allows cross-origin requests from the React/Vite development server

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", # Vite Default
        "http://localhost:5174", # Vite Alternative
        "http://localhost:3000", # Traditional React
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ROUTER REGISTRATION ---

app.include_router(auth_routes.router)
app.include_router(booking_routes.router)
app.include_router(machine_routes.router)
app.include_router(setting_routes.router)
app.include_router(analytics_routes.router)

# --- ROOT HEALTH CHECK ---

@app.get("/")
def read_root():
    """Returns the operational status and active modules of the backend."""
    return {
        "status": "Online",
        "system": "LaundryLink Optimization Engine",
        "database": "PostgreSQL Connected",
        "modules_active": ["Auth", "Bookings", "Machines", "Settings", "Analytics"],
        "environment": "Development Sprint"
    }