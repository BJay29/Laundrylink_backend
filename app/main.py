from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import engine, SessionLocal
from app import models
from app.routes import auth_routes, booking_routes, machine_routes
from sqlalchemy.orm import Session

# --- SEEDING LOGIC ---
def seed_machines():
    """
    Checks if the machines table is empty. 
    If yes, it populates the DB with 6 Washers and 6 Dryers.
    """
    db = SessionLocal()
    try:
        # I-check kung may laman na ang machines table
        machine_count = db.query(models.Machine).count()
        
        if machine_count == 0:
            print("No machines found. Initializing seed data...")
            
            machines_to_add = []
            
            # Mag-create ng 6 Washers
            for i in range(1, 7):
                machines_to_add.append(
                    models.Machine(
                        machine_number=i, 
                        machine_type="Washer", 
                        status="Available"
                    )
                )
            
            # Mag-create ng 6 Dryers
            for i in range(1, 7):
                machines_to_add.append(
                    models.Machine(
                        machine_number=i, 
                        machine_type="Dryer", 
                        status="Available"
                    )
                )
            
            db.add_all(machines_to_add)
            db.commit()
            print(f"Successfully seeded {len(machines_to_add)} machines!")
        else:
            print(f"Machines already exist ({machine_count} units). Skipping seed.")
            
    except Exception as e:
        print(f"Seeding Error: {e}")
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
        # Syncing Tables
        models.Base.metadata.create_all(bind=engine)
        print("PostgreSQL Tables Synced Successfully!")
        
        # Auto-seed Machines
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

# 3. CORS Fix:
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        # Dagdag mo dito yung production URL mo pag nag-deploy ka ng frontend
        # "https://your-frontend.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include Routes
app.include_router(auth_routes.router)
app.include_router(booking_routes.router)
app.include_router(machine_routes.router)

# 5. Health Check
@app.get("/")
def read_root():
    return {
        "status": "Online",
        "system": "LaundryLink Optimization Engine",
        "database": "PostgreSQL Connected",
        "modules_active": ["Auth", "Bookings", "Machines"],
        "environment": "Development Sprint"
    }