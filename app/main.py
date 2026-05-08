from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import engine, SessionLocal
from app import models
# Import the new settings_routes
from app.routes import auth_routes, booking_routes, machine_routes, setting_routes
from sqlalchemy.orm import Session

# --- UPDATED SEEDING & AUTO-FIX LOGIC ---

def seed_settings(db: Session):
    """
    Ensures that default optimization settings exist for shop_id=1.
    This prevents the UI from crashing during the first load.
    """
    existing_settings = db.query(models.Setting).filter(models.Setting.shop_id == 1).first()
    if not existing_settings:
        print("No settings found for Shop 1. Initializing default configuration...")
        default_settings = models.Setting(
            shop_id=1,
            wash_only_price=40.0,
            dry_only_price=30.0,
            full_service_price=60.0,
            electricity_rate=12.0,
            water_rate=50.0,
            detergent_cost_per_load=10.0,
            off_peak_hours="8:00 AM - 11:00 AM"
        )
        db.add(default_settings)
        db.commit()
        print("Default shop settings initialized successfully.")

def seed_machines():
    """
    1. Checks if the machines table is empty and populates it with shop_id=1.
    2. If machines exist but shop_id is NULL, it automatically updates them to 1.
    """
    db = SessionLocal()
    try:
        # Seed/Fix Settings first as machines depend on the shop structure
        seed_settings(db)

        # Step 1: Check for machines with NULL shop_id and fix them
        null_machines = db.query(models.Machine).filter(models.Machine.shop_id == None).all()
        if null_machines:
            print(f"Found {len(null_machines)} machines with NULL shop_id. Fixing now...")
            for m in null_machines:
                m.shop_id = 1
            db.commit()
            print("Existing machines updated to shop_id=1 successfully.")

        # Step 2: Initial seeding for empty hardware table
        machine_count = db.query(models.Machine).count()
        
        if machine_count == 0:
            print("No machines found. Initializing seed data with shop_id=1...")
            
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
            print(f"Successfully seeded {len(machines_to_add)} machines!")
        else:
            print(f"Machines already exist ({machine_count} units). Seed skipped.")
            
    except Exception as e:
        print(f"Seeding/Fixing Error: {e}")
        db.rollback()
    finally:
        db.close()

# 1. Lifespan Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("========================================")
    print("LaundryLink Backend started successfully")
    print("Architecture: Clean Routes/Controllers Split")
    
    try:
        # Syncing Tables (Creates the 'settings' table automatically)
        models.Base.metadata.create_all(bind=engine)
        print("PostgreSQL Tables Synced Successfully!")
        
        # Auto-fix and Auto-seed Data
        seed_machines()
        
    except Exception as e:
        print(f"Database Initialization Error: {e}")
        
    print("System Mode: Profit Optimization Ready")
    print("========================================")
    
    yield  
    
    print("Shutting down LaundryLink Backend...")

# 2. FastAPI Instance
app = FastAPI(
    title="LaundryLink API",
    description="Backend API for Laundry Income Optimization System",
    version="1.0.0",
    lifespan=lifespan
)

# 3. CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include Routes
app.include_router(auth_routes.router)
app.include_router(booking_routes.router)
app.include_router(machine_routes.router)
app.include_router(setting_routes.router) # <--- Added the settings router here

# 5. Health Check
@app.get("/")
def read_root():
    return {
        "status": "Online",
        "system": "LaundryLink Optimization Engine",
        "database": "PostgreSQL Connected",
        "modules_active": ["Auth", "Bookings", "Machines", "Settings"],
        "environment": "Development Sprint"
    }